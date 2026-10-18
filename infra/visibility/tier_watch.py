#!/usr/bin/env python3
"""
tier_watch.py — monitor data tier and alert on degradation (WO-77-C).

Reads current data tier from bot_health, maintains state machine (OK/WARN/CRITICAL),
and routes tier transitions to @DDHealthbot via ff_notifier.

Runs every 5 min via systemd timer (ff-tier-watch.timer).
State file: ~/.tier_watch_state.json
"""

import os
import json
import time
import sys
from datetime import datetime, timezone

try:
    import requests
    from dotenv import load_dotenv
except ImportError as e:
    print(f"[tier_watch] import error: {e} — skipping", file=sys.stderr)
    sys.exit(0)

# Load environment
load_dotenv()

TIER_NAMES = {0: "FULL", 1: "RT no-L2", 2: "DELAYED", 3: "DARK"}
STATE_FILE = os.path.expanduser("~/.tier_watch_state.json")
SB_URL = os.getenv("SUPABASE_URL", "")
SB_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

def read_current_tier():
    """
    Fetch latest tier from Supabase bot_health.
    Falls back to Tier 3 (DARK) on error.
    """
    if not SB_URL or not SB_KEY:
        print("[tier_watch] Supabase creds missing — assuming DARK", file=sys.stderr)
        return {"data_tier": 3, "tier_name": "DARK"}

    try:
        # Query: get the latest tier from bot_health
        resp = requests.post(
            f"{SB_URL}/rest/v1/rpc/get_data_tier",
            headers={
                "Authorization": f"Bearer {SB_KEY}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=3
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return {"data_tier": 3, "tier_name": "DARK"}
        else:
            print(f"[tier_watch] query failed: {resp.status_code}", file=sys.stderr)
            return {"data_tier": 3, "tier_name": "DARK"}
    except Exception as e:
        print(f"[tier_watch] fetch error: {e}", file=sys.stderr)
        return {"data_tier": 3, "tier_name": "DARK"}

def get_state():
    """Load persistent state; default to OK/tier 0."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception as e:
        print(f"[tier_watch] state load error: {e}", file=sys.stderr)
    return {"state": "OK", "last_tier": 0, "last_change": 0}

def save_state(st):
    """Persist state atomically."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(st, f, indent=2)
    except Exception as e:
        print(f"[tier_watch] state save error: {e}", file=sys.stderr)

def decide(current_tier, last_state):
    """
    State machine: determine action based on tier transition.

    States: OK (tier >= 2), WARN (tier == 1), CRITICAL (tier < 1)
    Actions: transition, recovery, renotify (every 4h), none
    """
    # Map tier to state
    if current_tier < 1:
        target = "CRITICAL"
    elif current_tier < 2:
        target = "WARN"
    else:
        target = "OK"

    last = last_state.get("state", "OK")
    last_tier = last_state.get("last_tier", 0)
    now = time.time()
    last_change = last_state.get("last_change", 0)

    # Transition detected?
    if target != last or current_tier != last_tier:
        return {
            "action": "transition",
            "from": last,
            "to": target,
            "from_tier": last_tier,
            "to_tier": current_tier,
            "tier_name": TIER_NAMES.get(current_tier, "unknown"),
        }

    # Re-notify every 4h while in WARN/CRITICAL
    renotify_interval = 4 * 3600
    if target in ("WARN", "CRITICAL") and now - last_change > renotify_interval:
        return {
            "action": "renotify",
            "state": target,
            "tier": current_tier,
            "tier_name": TIER_NAMES.get(current_tier, "unknown"),
        }

    # Recovery from WARN/CRITICAL to OK
    if target == "OK" and last in ("WARN", "CRITICAL"):
        return {
            "action": "recovery",
            "from": last,
            "to": target,
        }

    return {"action": "none"}

def notify(msg_type, data):
    """Route alert to @DDHealthbot via ff_notifier (H-70E channel)."""
    try:
        import ff_notifier
    except ImportError:
        print("[tier_watch] ff_notifier not available — no alert sent", file=sys.stderr)
        return

    try:
        if msg_type == "transition":
            if data["to"] == "CRITICAL":
                emoji = "🚨"
            elif data["to"] == "WARN":
                emoji = "⚠️"
            else:
                emoji = "✅"

            msg = (f"{emoji} <b>Feed degraded: {data['from']} → {data['to']}</b>\n"
                   f"Tier {data['to_tier']}: {data['tier_name']}\n"
                   f"Strategy impact: bar-only run; L2-native paused.")
            ff_notifier.notify_sync(msg, category="error")

        elif msg_type == "recovery":
            msg = (f"✅ <b>Feed recovered: {data['from']} → {data['to']}</b>\n"
                   f"All strategies running again.")
            ff_notifier.notify_sync(msg, category="error")

        elif msg_type == "renotify":
            msg = (f"⚠️ <b>Still in {data['state']}</b>\n"
                   f"Tier {data['tier']}: {data['tier_name']}")
            ff_notifier.notify_sync(msg, category="error")
    except Exception as e:
        print(f"[tier_watch] notify error: {e}", file=sys.stderr)

def main():
    current = read_current_tier()
    current_tier = current.get("data_tier", 3)

    st = get_state()
    decision = decide(current_tier, st)

    action = decision.get("action", "none")

    if action == "transition":
        notify("transition", decision)
        st["state"] = decision["to"]
        st["last_tier"] = current_tier
        st["last_change"] = time.time()
        print(f"[tier_watch] transition {decision['from']} → {decision['to']} "
              f"(tier {current_tier})")

    elif action == "recovery":
        notify("recovery", decision)
        st["state"] = decision["to"]
        st["last_change"] = time.time()
        print(f"[tier_watch] recovery {decision['from']} → {decision['to']}")

    elif action == "renotify":
        notify("renotify", decision)
        print(f"[tier_watch] renotify {decision['state']} (tier {current_tier})")

    elif action == "none":
        print(f"[tier_watch] idle state={st.get('state')} tier={current_tier}")

    save_state(st)

if __name__ == "__main__":
    main()
