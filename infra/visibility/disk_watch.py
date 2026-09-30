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


# ── pure state machine (unit-tested) ─────────────────────────────────────────
def decide(state, row, prev, now_ts, renotify_s):
    """Map (current view state, prev persisted state, now) -> (message_or_None, new_prev).

    prev / new_prev: {"state": str, "since": epoch, "last_notify": epoch}.
    Pure: no I/O, no clock — everything comes in as an argument so it can be tested.
    """
    prev = prev or {}
    prev_state  = prev.get("state", "OK")
    since       = prev.get("since", now_ts)
    last_notify = prev.get("last_notify", 0.0)

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
def send(text):
    """Reuse ff_notifier (the H-70E @DDHealthbot channel). Fall back to a direct POST
    to the SAME token+chat if ff_notifier can't be imported — still the same channel."""
    try:
        if BOT_DIR not in sys.path:
            sys.path.insert(0, BOT_DIR)
        import ff_notifier
        ff_notifier.notify_sync(text, category="error")
        return True
    except Exception as e:
        print("[disk_watch] ff_notifier unavailable (%r); direct POST to same chat" % (e,))
    tok = (os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip().strip('"')
    chat = (os.environ.get("TELEGRAM_CHAT_ID", "") or "").strip().strip('"')
    if not (tok and chat):
        print("[disk_watch] no TELEGRAM_BOT_TOKEN/CHAT_ID — cannot send")
        return False
    import urllib.parse
    data = urllib.parse.urlencode({"chat_id": chat, "parse_mode": "HTML",
                                   "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok, data=data)
    urllib.request.urlopen(req, timeout=8).read()
    return True


def main():
    now_ts = time.time()
    if FORCE in ("OK", "WARN", "CRITICAL", "UNKNOWN"):
        row = {"state": FORCE, "free_gb_now": 1.23 if FORCE == "CRITICAL" else 4.56,
               "fill_gb_per_h": 0.30 if FORCE == "CRITICAL" else 0.05,
               "samples": 90, "reason": "FORCED TEST (%s)" % FORCE}
        print("[disk_watch] FORCE=%s — bypassing the view for an acceptance test" % FORCE)
    else:
        row = read_view()
    state = (row.get("state") or "UNKNOWN").upper()

    prev = load_state()
    msg, new_prev = decide(state, row, prev, now_ts, RENOTIFY_S)
    ts_iso = datetime.now(timezone.utc).isoformat()
    if msg:
        ok = send(msg)
        print("%s state=%s sent=%s | %s" % (ts_iso, state, ok, row.get("reason")))
    else:
        print("%s state=%s (no message) | %s" % (ts_iso, state, row.get("reason")))
    save_state(new_prev)


if __name__ == "__main__":
    main()
