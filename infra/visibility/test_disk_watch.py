"""H-74 tests — the 74-C watcher state machine, and the 74-B rule back-test.

Two halves:
  * StateMachineTest — proves decide() sends exactly once on transition, re-notifies
    on the 4h cadence and not before, recovers once, and is SILENT on UNKNOWN (never
    treating an unknown reading as recovery or as an alarm).
  * BackTestTest — replays the 2026-09-15/16 fill shape through a Python mirror of the
    v_disk_health rule and asserts the rate alarm fires ~30-45 min in, far ahead of the
    level alarm. Mirrors the authoritative SQL back-test (run against Supabase) so the
    threshold in §2b is checked, per the work order's "back-test it" gate.

Run:  python3 -m unittest test_disk_watch -v
Stdlib only; no network, no Supabase, no Telegram.
"""
import unittest

import disk_watch as dw

H = 3600.0
RENOTIFY = 4 * H


def _row(state, free=4.0, fill=0.05):
    return {"state": state, "free_gb_now": free, "fill_gb_per_h": fill,
            "samples": 90, "reason": state.lower()}


class StateMachineTest(unittest.TestCase):
    def test_ok_stays_silent(self):
        msg, nxt = dw.decide("OK", _row("OK"), {}, 1000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertEqual(nxt["state"], "OK")

    def test_ok_to_warn_sends_once(self):
        prev = {"state": "OK", "since": 0.0, "last_notify": 0.0}
        msg, nxt = dw.decide("WARN", _row("WARN"), prev, 1000.0, RENOTIFY)
        self.assertIsNotNone(msg)
        self.assertIn("WARN", msg)
        self.assertEqual(nxt["state"], "WARN")
        self.assertEqual(nxt["since"], 1000.0)
        self.assertEqual(nxt["last_notify"], 1000.0)

    def test_warn_does_not_reflap_before_4h(self):
        prev = {"state": "WARN", "since": 1000.0, "last_notify": 1000.0}
        msg, nxt = dw.decide("WARN", _row("WARN"), prev, 1000.0 + 3 * H, RENOTIFY)
        self.assertIsNone(msg, "no re-notify before the 4h cadence")
        self.assertEqual(nxt["last_notify"], 1000.0)

    def test_warn_renotifies_after_4h(self):
        prev = {"state": "WARN", "since": 1000.0, "last_notify": 1000.0}
        t = 1000.0 + 4 * H + 1
        msg, nxt = dw.decide("WARN", _row("WARN"), prev, t, RENOTIFY)
        self.assertIsNotNone(msg)
        self.assertIn("still", msg)
        self.assertEqual(nxt["last_notify"], t)
        self.assertEqual(nxt["since"], 1000.0, "since is preserved across a re-notify")

    def test_warn_to_critical_escalates_immediately(self):
        prev = {"state": "WARN", "since": 1000.0, "last_notify": 1000.0}
        msg, nxt = dw.decide("CRITICAL", _row("CRITICAL", free=1.5, fill=0.4),
                             prev, 1000.0 + 60, RENOTIFY)
        self.assertIsNotNone(msg, "escalation is a transition, not gated by the 4h timer")
        self.assertIn("CRITICAL", msg)
        self.assertEqual(nxt["state"], "CRITICAL")
        self.assertEqual(nxt["since"], 1000.0 + 60)

    def test_recovery_sends_once_then_silent(self):
        prev = {"state": "CRITICAL", "since": 1000.0, "last_notify": 1000.0}
        msg, nxt = dw.decide("OK", _row("OK"), prev, 5000.0, RENOTIFY)
        self.assertIsNotNone(msg)
        self.assertIn("recovered", msg)
        self.assertEqual(nxt["state"], "OK")
        # and a second OK evaluation is silent
        msg2, _ = dw.decide("OK", _row("OK"), nxt, 6000.0, RENOTIFY)
        self.assertIsNone(msg2)

    def test_unknown_is_silent_and_preserves_prior_alarm(self):
        prev = {"state": "CRITICAL", "since": 1000.0, "last_notify": 1000.0}
        msg, nxt = dw.decide("UNKNOWN", _row("UNKNOWN", free=None, fill=None),
                             prev, 2000.0, RENOTIFY)
        self.assertIsNone(msg, "UNKNOWN never sends")
        self.assertEqual(nxt["state"], "CRITICAL",
                         "UNKNOWN must not clear an alarm (it is not a recovery)")
        self.assertEqual(nxt["last_notify"], 1000.0)

    def test_unknown_does_not_manufacture_an_alarm(self):
        prev = {"state": "OK", "since": 0.0, "last_notify": 0.0}
        msg, nxt = dw.decide("UNKNOWN", _row("UNKNOWN", free=None, fill=None),
                             prev, 2000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertEqual(nxt["state"], "OK")


# ── 74-B rule mirror, kept identical to v_disk_health.sql ─────────────────────
def classify(samples, thresholds=(5.0, 2.0, 0.25), min_samples=45):
    """Mirror of v_disk_health. samples = list of (minute, free_gib) already inside the
    <=90m window, any order. Returns state string. Levels use the latest point; the rate
    is the secant across the window, trusted only at len >= min_samples."""
    warn_gb, crit_gb, rate_gb = thresholds
    if not samples:
        return "UNKNOWN"
    pts = sorted(samples)
    free_now = pts[-1][1]
    free_start = pts[0][1]
    span_min = pts[-1][0] - pts[0][0]
    fill = (free_start - free_now) / (span_min / 60.0) if span_min > 0 else None
    if free_now is None:
        return "UNKNOWN"
    if free_now < crit_gb:
        return "CRITICAL"
    if len(pts) >= min_samples and fill is not None and fill > rate_gb:
        return "CRITICAL"
    if free_now < warn_gb:
        return "WARN"
    return "OK"


def _window(timeline, m):
    """The <=90-minute window ending at evaluation minute m (1/min samples)."""
    return [(t, f) for (t, f) in timeline if m - 90 < t <= m]


class BackTestTest(unittest.TestCase):
    """Replay 18.5 GiB -> 0 at the event's AVERAGE rate and find first CRITICAL."""

    def _event_timeline(self, rate_gib_h, start_gib=18.5, warm=True):
        # warm box: 180 min of flat pre-event history so samples never gates.
        # cold box: history begins at event onset (samples grows from 0).
        lo = -180 if warm else 0
        tl = []
        for t in range(lo, 1201):
            free = start_gib if t <= 0 else max(start_gib - rate_gib_h * (t / 60.0), 0.0)
            tl.append((t, free))
        return tl

    def _first_critical(self, timeline):
        for m in range(1, 1201):
            if classify(_window(timeline, m)) == "CRITICAL":
                return m
        return None

    def test_warm_box_rate_alarm_fires_about_30_min_in(self):
        tl = self._event_timeline(0.75, warm=True)     # conservative: event average
        first = self._first_critical(tl)
        self.assertIsNotNone(first)
        self.assertLessEqual(first, 60, "rate alarm must fire within ~1h (order §2b gate)")
        self.assertGreaterEqual(first, 20)             # not instantaneous / not a flap
        # matches the authoritative SQL back-test (first_rate_critical_min = 30)
        self.assertEqual(first, 30)

    def test_cold_start_fires_by_45_min_when_samples_gate_binds(self):
        tl = self._event_timeline(0.75, warm=False)
        first = self._first_critical(tl)
        self.assertIsNotNone(first)
        # The samples>=45 guard binds: the window first holds 45 samples at minute 44
        # (t=0..44 inclusive), so firing is delayed from the warm-box 30 min to 44 min.
        self.assertEqual(first, 44)
        self.assertGreater(first, 30, "samples gate delays cold-start firing past the warm 30 min")
        self.assertLessEqual(first, 60, "still within ~1h")

    def test_rate_alarm_beats_the_level_alarm_by_hours(self):
        tl = self._event_timeline(0.75, warm=True)
        first_crit = self._first_critical(tl)
        first_below5 = next((t for (t, f) in tl if f < 5.0), None)
        self.assertIsNotNone(first_below5)
        self.assertLess(first_crit, first_below5)
        self.assertGreater(first_below5 - first_crit, 600,   # > 10 hours of head start
                           "the rate alarm's whole point is firing long before the level alarm")

    def test_normal_growth_never_alarms(self):
        # observed live normal ~0.076 GiB/h; well under 0.25 -> stays OK for a full day
        tl = self._event_timeline(0.076, warm=True)
        self.assertIsNone(self._first_critical(tl))

    def test_sparse_window_never_criticals_from_an_untrusted_rate(self):
        # 10 samples over the first 10 minutes of a steep fall: the secant looks huge,
        # but samples < 45 means the rate is not trusted, so it must NOT go CRITICAL on
        # the rate (the H-70E "unknown-as-value" class). Free is still high, so the
        # level keeps it OK — an untrusted rate simply doesn't escalate.
        steep = [(t, 18.5 - 1.5 * (t / 60.0)) for t in range(1, 11)]
        self.assertNotEqual(classify(steep), "CRITICAL")
        self.assertEqual(classify(steep), "OK")
        # and with no samples at all it is UNKNOWN, never healthy
        self.assertEqual(classify([]), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
