#!/usr/bin/env python3
"""H-74 / 74-C — disk-space alarm watcher for ff-bot-prod.

Reads v_disk_health (H-74/74-B) from Supabase and routes WARN / CRITICAL / recovery
to @DDHealthbot -> Tom over the EXISTING H-70E Telegram path (ff_notifier). It does
NOT open a second channel and it does NOT touch bot_engine.

Why a separate process (not in heartbeat.py): the heartbeat stays stateless and
must never be blocked or crashed by alerting. This watcher owns the alarm state and
the network send. Run it from a systemd timer every ~5 min (ff-disk-watch.timer).

Cadence (work order §2d / R-42 §5.3):
  * ONE message on a state TRANSITION (not per evaluation),
  * while still WARN/CRITICAL, RE-NOTIFY every 4h,
  * ONE message on RECOVERY to OK.

UNKNOWN (sparse window / no reading in 90m) is SILENT and never counts as recovery:
an unknown reading is not a value. This is the H-70E failure class the samples>=45
guard in v_disk_health exists to prevent, enforced again here.

Hysteresis (channel F-002): the view trips WARN at < 5.0 GiB and CRITICAL at < 2.0 GiB
or fill > 0.25 GiB/h. Clearing needs more room than tripping, so free space hovering at
a boundary cannot send alternating alarm/recovery pairs until the channel gets muted:
  * WARN clears only at >= 6.0 GiB free;
  * CRITICAL clears only at >= 3.0 GiB free AND (fill rate untrusted or <= 0.20 GiB/h).
    A rate CRITICAL can fire with plenty of space, so space alone never clears it.

Blind monitor (channel F-001): if bot_health rows are still arriving (newest <= 15 min)
but none has carried disk_free_bytes for > 30 min, the disk alarm cannot see the disk.
The view cannot say so (it keeps the last reading for 90 min, then goes UNKNOWN, which
is silent), so this watcher asks bot_health directly and pages BLIND on its own
transition / 4h re-notify / recovery cycle. If bot_health rows stop altogether that is
the heartbeat's outage, owned by watch_config, and stays silent here.

Honest send (channel F-004): a message counts as sent only when Telegram accepted it.
ff_notifier.notify_sync() returns None whether or not it delivered, so the watcher uses
ff_notifier._send_raw() (True/False) and does NOT advance its state on a failed send:
the next run tries again instead of going quiet for 4 hours on a send that never left.

Stdlib only. Fail-safe: any error is printed and exits non-zero WITHOUT sending a
bogus alarm or corrupting the state file.

Env:
  SB_URL, SB_KEY                        Supabase REST base + service-role key (reuse heartbeat's)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  the @DDHealthbot -> Tom channel (reused via ff_notifier)
  FF_TELEGRAM_ALERTS=1                  master switch (honored via ff_notifier)
  BOT_DIR         default /home/tom/futuresforged-bot   (to import ff_notifier)
  FF_DISK_WATCH_STATE  default $BOT_DIR/.disk_watch_state.json
  FF_DISK_RENOTIFY_H   default 4        re-notify cadence, hours
  FF_DISK_WATCH_FORCE  optional: OK|WARN|CRITICAL|UNKNOWN  -- test override, bypasses the view
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

SB_URL     = os.environ.get("SB_URL", "").rstrip("/")
SB_KEY     = os.environ.get("SB_KEY", "")
BOT_DIR    = os.environ.get("BOT_DIR", "/home/tom/futuresforged-bot")
STATE_FILE = os.environ.get("FF_DISK_WATCH_STATE", os.path.join(BOT_DIR, ".disk_watch_state.json"))
RENOTIFY_S = float(os.environ.get("FF_DISK_RENOTIFY_H", "4")) * 3600.0
FORCE      = (os.environ.get("FF_DISK_WATCH_FORCE", "") or "").strip().upper()

ALARM_STATES = ("WARN", "CRITICAL")
RANK = {"OK": 0, "WARN": 1, "CRITICAL": 2}

WARN_CLEAR_GB      = 6.0    # F-002: WARN trips < 5.0, clears >= 6.0
CRIT_CLEAR_GB      = 3.0    # F-002: level CRITICAL trips < 2.0, clears >= 3.0
CRIT_CLEAR_FILL    = 0.20   # F-002: rate CRITICAL trips > 0.25 GiB/h, clears <= 0.20
RATE_MIN_SAMPLES   = 45     # same trust floor as v_disk_health

BLIND_ROWS_MAX_S   = 15 * 60   # F-001: bot_health counts as "arriving" if newest <= 15 min
BLIND_DISK_MAX_S   = 30 * 60   # F-001: no disk reading for > 30 min while rows arrive


# ── view read ────────────────────────────────────────────────────────────────
def read_view():
    """GET the single v_disk_health row. Returns a dict. Raises on transport error."""
    if not (SB_URL and SB_KEY):
        raise SystemExit("SB_URL / SB_KEY not set — reuse the heartbeat EnvironmentFile")
    req = urllib.request.Request(
        SB_URL + "/rest/v1/v_disk_health?select=*",
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        rows = json.loads(r.read().decode())
    if not rows:
        # No row at all (empty table) — treat as UNKNOWN, never as healthy.
        return {"state": "UNKNOWN", "free_gb_now": None, "fill_gb_per_h": None,
                "samples": 0, "reason": "v_disk_health returned no row"}
    return rows[0]


def _get(path):
    req = urllib.request.Request(
        SB_URL + path,
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def _parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_telemetry_ages(now_ts):
    """(rows_age_s, disk_age_s) from bot_health directly — NOT the view, which keeps the
    last reading for 90 min and then goes UNKNOWN. Either may be None (no such row).
    Raises on transport error; the caller treats that as "could not tell"."""
    newest = _get("/rest/v1/bot_health?select=ts&service=eq.bot&order=ts.desc&limit=1")
    disk = _get("/rest/v1/bot_health?select=ts&service=eq.bot"
                "&disk_free_bytes=not.is.null&order=ts.desc&limit=1")
    t_rows = _parse_ts(newest[0]["ts"]) if newest else None
    t_disk = _parse_ts(disk[0]["ts"]) if disk else None
    return (None if t_rows is None else now_ts - t_rows,
            None if t_disk is None else now_ts - t_disk)


def blind_verdict(rows_age_s, disk_age_s):
    """True = rows arriving but no disk reading for > 30 min (blind).
    False = disk readings are current. None = cannot tell: no rows, or the rows
    themselves have stopped (the heartbeat's outage, not ours) — silent."""
    if rows_age_s is None or rows_age_s > BLIND_ROWS_MAX_S:
        return None
    if disk_age_s is None or disk_age_s > BLIND_DISK_MAX_S:
        return True
    return False


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── message text ─────────────────────────────────────────────────────────────
def _fmt(row):
    free = _f(row.get("free_gb_now"))
    fill = _f(row.get("fill_gb_per_h"))
    free_s = "%.2f GiB" % free if free is not None else "unknown"
    fill_s = "%+.3f GiB/h" % fill if fill is not None else "unknown"
    return free_s, fill_s, int(row.get("samples") or 0), (row.get("reason") or "")


def build_message(state, row, kind, age_s):
    """kind in {'transition','renotify','recovery'}. Names the numbers + the action."""
    free_s, fill_s, samples, reason = _fmt(row)
    age_h = age_s / 3600.0
    if state == "CRITICAL":
        head = "\U0001F6A8 <b>FF disk CRITICAL</b>"
        action = "Free disk now — L2 recorders pause at 2 GiB and capture is lost."
    elif state == "WARN":
        head = "⚠️ <b>FF disk WARN</b>"
        action = "Prune floor crossed; the box is shedding data. Watch for the 2 GiB recorder pause."
    else:  # OK / recovery
        head = "✅ <b>FF disk recovered</b>"
        action = "Back to OK."
    if kind == "renotify":
        head += " <i>(still, %.1fh)</i>" % age_h
    elif kind == "recovery":
        pass
    body = "%s\nfree %s · fill %s · samples %d\n%s\n<i>%s</i>" % (
        head, free_s, fill_s, samples, reason, action)
    return body


def build_blind_message(kind, disk_age_s, age_s):
    disk_s = ("%.0f min" % (disk_age_s / 60.0)) if disk_age_s is not None else "ever"
    if kind == "recovery":
        return ("✅ <b>FF disk monitor reading again</b>\n"
                "bot_health is carrying disk_free_bytes again; the disk alarm can see the disk.")
    head = "⚠️ <b>FF disk monitor BLIND</b>"
    if kind == "renotify":
        head += " <i>(still, %.1fh)</i>" % (age_s / 3600.0)
    return ("%s\nbot_health rows are arriving but none has a disk reading for %s.\n"
            "<i>The disk alarm cannot see the disk: a full disk would NOT page. "
            "Check heartbeat.py host_metrics() on ff-bot-prod.</i>" % (head, disk_s))


# ── pure state machines (unit-tested) ────────────────────────────────────────
def apply_hysteresis(state, row, prev_state):
    """F-002. Hold an alarm until the reading clears the wider band, so a value hovering
    at a trip point does not flap. Only ever holds an alarm; never raises one."""
    if state not in RANK or prev_state not in ALARM_STATES:
        return state
    if RANK[state] >= RANK[prev_state]:
        return state
    free = _f(row.get("free_gb_now"))
    fill = _f(row.get("fill_gb_per_h"))
    rate_trusted = int(row.get("samples") or 0) >= RATE_MIN_SAMPLES
    if free is None:
        return state            # cannot judge a band without a reading; the view decides
    held = state
    if prev_state == "CRITICAL":
        rate_hot = rate_trusted and fill is not None and fill > CRIT_CLEAR_FILL
        if free < CRIT_CLEAR_GB or rate_hot:
            return "CRITICAL"
    if free < WARN_CLEAR_GB:
        held = "WARN"
    return held if RANK[held] > RANK[state] else state


def decide_blind(blind, prev, now_ts, renotify_s, disk_age_s=None):
    """F-001 state machine, separate from the level/rate one. blind is True/False/None.
    None (cannot tell) is silent and preserves the prior state, like UNKNOWN."""
    prev = prev or {}
    was = bool(prev.get("blind", False))
    since = prev.get("since", now_ts)
    last_notify = prev.get("last_notify", 0.0)
    if blind is None:
        return None, {"blind": was, "since": since, "last_notify": last_notify}
    if blind:
        if not was:
            return (build_blind_message("transition", disk_age_s, 0.0),
                    {"blind": True, "since": now_ts, "last_notify": now_ts})
        if now_ts - last_notify >= renotify_s:
            return (build_blind_message("renotify", disk_age_s, now_ts - since),
                    {"blind": True, "since": since, "last_notify": now_ts})
        return None, {"blind": True, "since": since, "last_notify": last_notify}
    if was:
        return (build_blind_message("recovery", disk_age_s, now_ts - since),
                {"blind": False, "since": now_ts, "last_notify": 0.0})
    return None, {"blind": False, "since": since, "last_notify": 0.0}


def decide(state, row, prev, now_ts, renotify_s):
    """Map (current view state, prev persisted state, now) -> (message_or_None, new_prev).

    prev / new_prev: {"state": str, "since": epoch, "last_notify": epoch}.
    Pure: no I/O, no clock — everything comes in as an argument so it can be tested.
    """
    prev = prev or {}
    prev_state  = prev.get("state", "OK")
    since       = prev.get("since", now_ts)
    last_notify = prev.get("last_notify", 0.0)

    state = apply_hysteresis(state, row, prev_state)

    # UNKNOWN: silent, and it does NOT clear or change an existing alarm state.
    if state == "UNKNOWN":
        return None, {"state": prev_state, "since": since, "last_notify": last_notify}

    if state in ALARM_STATES:
        if state != prev_state:                       # transition (incl. escalate/de-escalate)
            return (build_message(state, row, "transition", 0.0),
                    {"state": state, "since": now_ts, "last_notify": now_ts})
        if now_ts - last_notify >= renotify_s:        # same state, time to re-notify
            return (build_message(state, row, "renotify", now_ts - since),
                    {"state": state, "since": since, "last_notify": now_ts})
        return (None, {"state": state, "since": since, "last_notify": last_notify})

    # state == OK
    if prev_state in ALARM_STATES:                    # recovery
        return (build_message("OK", row, "recovery", now_ts - since),
                {"state": "OK", "since": now_ts, "last_notify": 0.0})
    return (None, {"state": "OK", "since": since, "last_notify": 0.0})


# ── state file ───────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)                        # atomic; never a half-written state


# ── send (reuse H-70E path, no second channel) ───────────────────────────────
def _load_env_file(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _notifier():
    """ff_notifier reads TELEGRAM_* from os.environ ONCE AT IMPORT and is silently inert
    without them; a systemd oneshot may not have them. Fill them from BOT_DIR/.env first
    (same fix as heartbeat.py _notifier), then import."""
    envf = _load_env_file(os.path.join(BOT_DIR, ".env"))
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FF_TELEGRAM_ALERTS"):
        v = os.environ.get(k) or envf.get(k)
        if v:
            os.environ[k] = v
    if BOT_DIR not in sys.path:
        sys.path.insert(0, BOT_DIR)
    import ff_notifier
    return ff_notifier


def send(text):
    """Reuse the H-70E @DDHealthbot channel. Returns True ONLY when Telegram accepted
    the message (F-004): ff_notifier._send_raw returns True/False, notify_sync does not.
    Falls back to a direct POST to the SAME token+chat if ff_notifier can't be imported."""
    try:
        n = _notifier()
    except Exception as e:
        print("[disk_watch] ff_notifier unavailable (%r); direct POST to same chat" % (e,))
        n = None
    if n is not None:
        try:
            if not n._configured():
                print("[disk_watch] NOT SENT — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing "
                      "or FF_TELEGRAM_ALERTS=0")
                return False
            return bool(n._send_raw(text))
        except Exception as e:
            print("[disk_watch] NOT SENT — ff_notifier failed: %r" % (e,))
            return False
    tok = (os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip().strip('"')
    chat = (os.environ.get("TELEGRAM_CHAT_ID", "") or "").strip().strip('"')
    if not (tok and chat):
        print("[disk_watch] NOT SENT — no TELEGRAM_BOT_TOKEN/CHAT_ID")
        return False
    import urllib.parse
    data = urllib.parse.urlencode({"chat_id": chat, "parse_mode": "HTML",
                                   "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok, data=data)
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception as e:
        print("[disk_watch] NOT SENT — direct POST failed: %r" % (e,))
        return False


def main():
    now_ts = time.time()
    if FORCE in ("OK", "WARN", "CRITICAL", "UNKNOWN"):
        free = {"CRITICAL": 1.23, "OK": 8.9}.get(FORCE, 4.56)
        row = {"state": FORCE, "free_gb_now": free,
               "fill_gb_per_h": 0.30 if FORCE == "CRITICAL" else 0.05,
               "samples": 90, "reason": "FORCED TEST (%s)" % FORCE}
        print("[disk_watch] FORCE=%s — bypassing the view for an acceptance test" % FORCE)
    else:
        row = read_view()
    state = (row.get("state") or "UNKNOWN").upper()
    ts_iso = datetime.now(timezone.utc).isoformat()

    saved = load_state()
    # Older state files are the flat level dict; the blind machine lives under "blind_watch".
    prev_level = {k: saved[k] for k in ("state", "since", "last_notify") if k in saved}
    prev_blind = saved.get("blind_watch") or {}

    msg, new_level = decide(state, row, prev_level, now_ts, RENOTIFY_S)
    if msg:
        ok = send(msg)
        print("%s state=%s->%s sent=%s | %s" % (ts_iso, state, new_level["state"], ok,
                                                row.get("reason")))
        if not ok:
            new_level = prev_level      # F-004: not delivered = not advanced; retry next run
    else:
        print("%s state=%s->%s (no message) | %s" % (ts_iso, state, new_level["state"],
                                                     row.get("reason")))

    # F-001 blind check: skipped under FORCE (an acceptance test must not depend on it).
    new_blind = prev_blind
    if not FORCE:
        try:
            rows_age, disk_age = read_telemetry_ages(now_ts)
            blind = blind_verdict(rows_age, disk_age)
        except Exception as e:
            print("[disk_watch] blind check could not read bot_health: %r" % (e,))
            rows_age = disk_age = blind = None
        bmsg, new_blind = decide_blind(blind, prev_blind, now_ts, RENOTIFY_S, disk_age)
        if bmsg:
            ok = send(bmsg)
            print("%s blind=%s sent=%s rows_age_s=%s disk_age_s=%s" % (
                ts_iso, blind, ok, rows_age, disk_age))
            if not ok:
                new_blind = prev_blind

    out = dict(new_level)
    out["blind_watch"] = new_blind
    save_state(out)


if __name__ == "__main__":
    main()
