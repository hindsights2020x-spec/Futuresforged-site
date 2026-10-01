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
        # free 8.0: clear of both hysteresis bands (F-002), so CRITICAL recovers to OK.
        prev = {"state": "CRITICAL", "since": 1000.0, "last_notify": 1000.0}
        msg, nxt = dw.decide("OK", _row("OK", free=8.0), prev, 5000.0, RENOTIFY)
        self.assertIsNotNone(msg)
        self.assertIn("recovered", msg)
        self.assertEqual(nxt["state"], "OK")
        # and a second OK evaluation is silent
        msg2, _ = dw.decide("OK", _row("OK", free=8.0), nxt, 6000.0, RENOTIFY)
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


class HysteresisTest(unittest.TestCase):
    """F-002: clearing needs more room than tripping, so a boundary hover cannot flap."""

    def _warn(self):
        return {"state": "WARN", "since": 1000.0, "last_notify": 1000.0}

    def _crit(self):
        return {"state": "CRITICAL", "since": 1000.0, "last_notify": 1000.0}

    def test_warn_hovering_just_above_trip_does_not_recover(self):
        msg, nxt = dw.decide("OK", _row("OK", free=5.4), self._warn(), 2000.0, RENOTIFY)
        self.assertIsNone(msg, "5.4 GiB is above the 5.0 trip but below the 6.0 clear")
        self.assertEqual(nxt["state"], "WARN")
        self.assertEqual(nxt["since"], 1000.0, "held alarm keeps its age")

    def test_flapping_at_5gib_sends_one_message_not_pairs(self):
        prev, sent = {"state": "OK", "since": 0.0, "last_notify": 0.0}, 0
        for i, (st, free) in enumerate([("WARN", 4.9), ("OK", 5.1)] * 6):
            msg, prev = dw.decide(st, _row(st, free=free), prev, 1000.0 + 300 * i, RENOTIFY)
            sent += msg is not None
        self.assertEqual(sent, 1, "one WARN, then held: no alarm/recovery pairs")

    def test_warn_clears_at_6gib(self):
        msg, nxt = dw.decide("OK", _row("OK", free=6.0), self._warn(), 2000.0, RENOTIFY)
        self.assertIn("recovered", msg)
        self.assertEqual(nxt["state"], "OK")

    def test_level_critical_holds_below_3gib(self):
        msg, nxt = dw.decide("WARN", _row("WARN", free=2.6, fill=0.0), self._crit(),
                             2000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertEqual(nxt["state"], "CRITICAL")

    def test_critical_steps_down_to_warn_inside_the_warn_band(self):
        msg, nxt = dw.decide("OK", _row("OK", free=4.0, fill=0.0), self._crit(),
                             2000.0, RENOTIFY)
        self.assertIsNotNone(msg)
        self.assertIn("WARN", msg)
        self.assertEqual(nxt["state"], "WARN")

    def test_rate_critical_holds_with_plenty_of_space_while_fill_above_clear(self):
        # Rate CRITICAL fires with ~11 GiB free; space alone must not clear it.
        msg, nxt = dw.decide("OK", _row("OK", free=11.0, fill=0.22), self._crit(),
                             2000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertEqual(nxt["state"], "CRITICAL")

    def test_rate_critical_clears_when_fill_drops_to_clear_band(self):
        msg, nxt = dw.decide("OK", _row("OK", free=11.0, fill=0.15), self._crit(),
                             2000.0, RENOTIFY)
        self.assertIn("recovered", msg)
        self.assertEqual(nxt["state"], "OK")

    def test_untrusted_rate_does_not_hold_critical(self):
        row = _row("OK", free=11.0, fill=0.40)
        row["samples"] = 10
        msg, nxt = dw.decide("OK", row, self._crit(), 2000.0, RENOTIFY)
        self.assertEqual(nxt["state"], "OK", "a rate under the 45-sample floor is not a value")

    def test_hysteresis_never_raises_an_alarm(self):
        prev = {"state": "OK", "since": 0.0, "last_notify": 0.0}
        msg, nxt = dw.decide("OK", _row("OK", free=5.5), prev, 2000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertEqual(nxt["state"], "OK")


class BlindMonitorTest(unittest.TestCase):
    """F-001: rows arriving but no disk reading > 30 min pages BLIND; rows stopped = silent."""

    def test_verdicts(self):
        self.assertFalse(dw.blind_verdict(60, 60))
        self.assertFalse(dw.blind_verdict(60, 29 * 60))
        self.assertTrue(dw.blind_verdict(60, 31 * 60))
        self.assertTrue(dw.blind_verdict(60, None), "rows but never a disk reading")
        self.assertIsNone(dw.blind_verdict(None, None), "no rows: cannot tell")
        self.assertIsNone(dw.blind_verdict(20 * 60, 40 * 60),
                          "rows stopped: heartbeat outage, owned by watch_config")

    def test_cycle_transition_renotify_recovery(self):
        msg, st = dw.decide_blind(True, {}, 1000.0, RENOTIFY, 31 * 60)
        self.assertIn("BLIND", msg)
        msg, st = dw.decide_blind(True, st, 1000.0 + 3 * H, RENOTIFY, 3 * H)
        self.assertIsNone(msg, "no re-notify before 4h")
        msg, st = dw.decide_blind(True, st, 1000.0 + 4 * H + 1, RENOTIFY, 4 * H)
        self.assertIn("still", msg)
        msg, st = dw.decide_blind(False, st, 1000.0 + 5 * H, RENOTIFY, 60)
        self.assertIn("reading again", msg)
        msg, st = dw.decide_blind(False, st, 1000.0 + 6 * H, RENOTIFY, 60)
        self.assertIsNone(msg)

    def test_cannot_tell_is_silent_and_preserves_blind(self):
        _, st = dw.decide_blind(True, {}, 1000.0, RENOTIFY, 31 * 60)
        msg, st2 = dw.decide_blind(None, st, 2000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertTrue(st2["blind"], "cannot-tell is not a recovery")

    def test_the_case_the_view_cannot_see(self):
        # Writer stopped 40 min ago: the view still holds the 40-min-old reading -> "OK",
        # so the level machine is silent; the blind machine is what pages.
        msg, _ = dw.decide("OK", _row("OK", free=11.0), {}, 1000.0, RENOTIFY)
        self.assertIsNone(msg)
        self.assertTrue(dw.blind_verdict(60, 40 * 60))


class HonestSendTest(unittest.TestCase):
    """F-004: a message counts as sent only when Telegram accepted it."""

    def setUp(self):
        self._orig = dw._notifier

    def tearDown(self):
        dw._notifier = self._orig

    def _fake(self, configured, raw):
        class N:
            pass
        n = N()
        n._configured = lambda: configured
        n._send_raw = lambda text: raw
        dw._notifier = lambda: n

    def test_unconfigured_is_not_sent(self):
        self._fake(False, True)
        self.assertFalse(dw.send("x"))

    def test_failed_post_is_not_sent(self):
        self._fake(True, False)
        self.assertFalse(dw.send("x"))

    def test_accepted_post_is_sent(self):
        self._fake(True, True)
        self.assertTrue(dw.send("x"))

    def test_main_does_not_advance_state_on_failed_send(self):
        import json, os, tempfile
        self._fake(True, False)
        d = tempfile.mkdtemp()
        orig_state, orig_force = dw.STATE_FILE, dw.FORCE
        dw.STATE_FILE = os.path.join(d, "s.json")
        dw.FORCE = "WARN"
        try:
            dw.main()
            with open(dw.STATE_FILE) as fh:
                st = json.load(fh)
            self.assertNotEqual(st.get("state"), "WARN",
                                "undelivered WARN must not be recorded, or it goes quiet 4h")
            self._fake(True, True)
            dw.main()
            with open(dw.STATE_FILE) as fh:
                self.assertEqual(json.load(fh)["state"], "WARN")
        finally:
            dw.STATE_FILE, dw.FORCE = orig_state, orig_force


class TelegramHtmlTest(unittest.TestCase):
    """F-005: parse_mode=HTML rejects a bare < > & with HTTP 400. Every real reason the
    view emits must reach Telegram escaped, or no real alarm is ever delivered."""

    ALLOWED_TAGS = ("<b>", "</b>", "<i>", "</i>")

    def _strip_tags(self, msg):
        for tag in self.ALLOWED_TAGS:
            msg = msg.replace(tag, "")
        return msg

    def test_view_reasons_match_the_sql(self):
        import os
        with open(os.path.join(os.path.dirname(dw.__file__), "v_disk_health.sql")) as fh:
            sql = fh.read()
        for reason in dw.VIEW_REASONS.values():
            self.assertIn("'%s'" % reason, sql, "VIEW_REASONS drifted from v_disk_health.sql")

    def test_every_view_reason_is_escaped(self):
        for key, reason in dw.VIEW_REASONS.items():
            state = "CRITICAL" if key.startswith("CRITICAL") else key
            for kind in ("transition", "renotify", "recovery"):
                msg = dw.build_message(state, {"free_gb_now": 1.0, "fill_gb_per_h": 0.3,
                                               "samples": 90, "reason": reason}, kind, 3600.0)
                body = self._strip_tags(msg)
                self.assertNotIn("<", body, "%s/%s: bare < would 400" % (key, kind))
                self.assertNotIn(">", body, "%s/%s: bare > would 400" % (key, kind))

    def test_forced_rows_carry_the_real_reason_text(self):
        import io, contextlib
        sent = []
        orig = (dw.send, dw.STATE_FILE, dw.FORCE)
        import os, tempfile
        dw.send = lambda text: sent.append(text) or True
        dw.STATE_FILE = os.path.join(tempfile.mkdtemp(), "s.json")
        try:
            for f in ("WARN", "CRITICAL"):
                dw.FORCE = f
                with contextlib.redirect_stdout(io.StringIO()):
                    dw.main()
        finally:
            dw.send, dw.STATE_FILE, dw.FORCE = orig
        self.assertEqual(len(sent), 2)
        self.assertIn("free &lt; 5.0 GiB", sent[0])
        self.assertIn("free &lt; 2.0 GiB", sent[1])


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
