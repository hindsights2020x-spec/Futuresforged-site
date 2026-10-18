# WO-77-C: Supabase Tier Visibility + @DDHealthbot Alerts

**Closes:** Operator blindness to feed degradation (no visibility that strategies are suppressed).  
**Depends on:** 77-A (warming) + 77-B (tier detection in bot_engine.py).  
**Blocks:** None (77-D independent).

## Problem

On 2026-10-01, when Rithmic failed:
- Bot silently suppressed L2-native strategies (Momentum)
- Operator didn't know why no Momentum signals fired
- No alert to @DDHealthbot that feed had degraded
- Invisible failure mode

## Solution: 77-C

Track data tier in Supabase `bot_health` and alert @DDHealthbot when tier drops below Tier 1.

### 1. Supabase Schema

Add to `bot_health` table (or `v_data_health` view):

```sql
-- New columns in bot_health (or new view v_data_health reading them):
ALTER TABLE bot_health ADD COLUMN IF NOT EXISTS data_tier INT;          -- 0-3
ALTER TABLE bot_health ADD COLUMN IF NOT EXISTS tier_name TEXT;         -- "FULL", "RT no-L2", etc.
ALTER TABLE bot_health ADD COLUMN IF NOT EXISTS feed_rithmic BOOLEAN;   -- connected?
ALTER TABLE bot_health ADD COLUMN IF NOT EXISTS feed_l2 BOOLEAN;        -- live?
ALTER TABLE bot_health ADD COLUMN IF NOT EXISTS feed_nt BOOLEAN;        -- NT fallback?
```

Or create a view `v_data_health`:

```sql
CREATE OR REPLACE VIEW v_data_health AS
SELECT
  ts,
  data_tier,
  tier_name,
  feed_rithmic,
  feed_l2,
  feed_nt,
  CASE
    WHEN data_tier < 1 THEN 'CRITICAL'
    WHEN data_tier < 2 THEN 'WARN'
    ELSE 'OK'
  END AS state,
  CASE
    WHEN data_tier < 1 THEN 'No Rithmic or bars'
    WHEN data_tier < 2 THEN 'L2 offline (bars only)'
    WHEN data_tier < 3 THEN 'NT fallback (may lag)'
    ELSE 'No feed'
  END AS reason
FROM bot_health
ORDER BY ts DESC;
```

### 2. Bot Engine: Emit Tier to Heartbeat

In `heartbeat.py`, add tier data to the `bot_health` row:

```python
# In heartbeat.py, in the part that builds the bot_health row:

# Get tier from bot_engine /api/state
tier_resp = requests.get(f"http://localhost:{DASHBOARD_PORT}/api/state", 
                         timeout=2).json()
data_tier = tier_resp.get("current_tier", 3)
tier_name = tier_resp.get("tier_name", "DARK")
feed_status = tier_resp.get("feed_status", {})

# Add to bot_health row
row_data = {
    ...existing fields...,
    "data_tier": data_tier,
    "tier_name": tier_name,
    "feed_rithmic": feed_status.get("rithmic", False),
    "feed_l2": feed_status.get("l2_live", False),
    "feed_nt": feed_status.get("nt_fallback", False),
}
```

### 3. Tier Alert Watcher (disk_watch.py pattern)

Create `tier_watch.py` (runs every 5 min, like disk_watch.py):

```python
#!/usr/bin/env python3
"""
tier_watch.py — monitor data tier and alert on degradation.

Similar to disk_watch.py: reads v_data_health, state machine (OK/WARN/CRITICAL),
routes to @DDHealthbot via ff_notifier.

Cadence: every 5 min via systemd timer.
State file: ~/.tier_watch_state.json
"""

import os
import json
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

TIER_NAMES = {0: "FULL", 1: "RT no-L2", 2: "DELAYED", 3: "DARK"}
STATE_FILE = os.path.expanduser("~/.tier_watch_state.json")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def read_current_tier():
    """Fetch latest tier from v_data_health (or bot_health)."""
    try:
        resp = requests.post(
            f"{SB_URL}/rest/v1/rpc/get_data_tier",
            headers={"Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"},
            json={},
            timeout=3
        )
        if resp.status_code == 200:
            return resp.json()  # Expected: {"data_tier": 0, "tier_name": "FULL"}
        return {"data_tier": 3, "tier_name": "DARK"}
    except Exception as e:
        print(f"[tier_watch] fetch error: {e}")
        return {"data_tier": 3, "tier_name": "DARK"}

def get_state():
    """Load persistent state; default to OK."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"state": "OK", "last_tier": 0}

def save_state(st):
    """Persist state."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(st, f)
    except Exception as e:
        print(f"[tier_watch] save error: {e}")

def decide(current_tier, last_state):
    """
    State machine: OK / WARN / CRITICAL + recovery.
    
    - OK: tier >= 1 (bars available)
    - WARN: tier == 1 (RT bars, no L2)
    - CRITICAL: tier < 1 (no bars or no Rithmic)
    
    Transitions and re-notify logic match disk_watch.py.
    """
    # Determine target state
    if current_tier < 1:
        target = "CRITICAL"
    elif current_tier < 2:
        target = "WARN"
    else:
        target = "OK"
    
    last = last_state.get("state", "OK")
    now = time.time()
    last_change = last_state.get("last_change", 0)
    
    # Transition?
    if target != last:
        return {
            "action": "transition",
            "from": last,
            "to": target,
            "tier": current_tier,
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
    """Send to @DDHealthbot via ff_notifier (same H-70E channel as disk_watch)."""
    try:
        import ff_notifier
        if msg_type == "transition":
            if data["to"] == "CRITICAL":
                emoji = "🚨"
                level = "ERROR"
            elif data["to"] == "WARN":
                emoji = "⚠️"
                level = "WARN"
            else:
                emoji = "✅"
                level = "INFO"
            
            msg = (f"{emoji} <b>Feed degraded: {data['from']} → {data['to']}</b>\n"
                   f"Tier {data['tier']}: {data['tier_name']}\n"
                   f"Bar-only strategies run; L2-native paused.")
            ff_notifier.notify_sync(msg, category="error", level=level)
        
        elif msg_type == "recovery":
            msg = (f"✅ <b>Feed recovered: {data['from']} → {data['to']}</b>\n"
                   f"All strategies running.")
            ff_notifier.notify_sync(msg, category="error", level="INFO")
        
        elif msg_type == "renotify":
            msg = (f"⚠️ <b>Still degraded: {data['state']}</b>\n"
                   f"Tier {data['tier']}: {data['tier_name']}")
            ff_notifier.notify_sync(msg, category="error", level="WARN")
    except Exception as e:
        print(f"[tier_watch] notify error: {e}")

def main():
    current = read_current_tier()
    current_tier = current.get("data_tier", 3)
    
    st = get_state()
    decision = decide(current_tier, st)
    
    if decision["action"] == "transition":
        notify("transition", decision)
        st["state"] = decision["to"]
        st["last_tier"] = current_tier
        st["last_change"] = time.time()
    
    elif decision["action"] == "recovery":
        notify("recovery", decision)
        st["state"] = decision["to"]
        st["last_change"] = time.time()
    
    elif decision["action"] == "renotify":
        notify("renotify", decision)
    
    save_state(st)
    print(f"[tier_watch] {decision['action']} | state={st.get('state')} | tier={current_tier}")

if __name__ == "__main__":
    main()
```

### 4. Systemd Units (like disk_watch)

Create `ff-tier-watch.service` and `ff-tier-watch.timer`:

```ini
# ff-tier-watch.service
[Unit]
Description=FuturesForged tier watcher
After=network.target

[Service]
Type=oneshot
User=tom
WorkingDirectory=/home/tom/futuresforged-bot
EnvironmentFile=/etc/ff/heartbeat.env
ExecStart=/usr/bin/python3 /home/tom/futuresforged-bot/tier_watch.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```ini
# ff-tier-watch.timer
[Unit]
Description=Run tier watcher every 5 minutes
Requires=ff-tier-watch.service

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
```

### 5. Acceptance Criteria

- [ ] `v_data_health` view created in Supabase (or columns added to bot_health)
- [ ] heartbeat.py populates data_tier, tier_name, feed_* columns
- [ ] tier_watch.py deployed to ff-bot-prod
- [ ] Systemd units installed + timer enabled
- [ ] Test: Simulate tier drop (kill Rithmic) → @DDHealthbot alert received
- [ ] Test: Restore Rithmic → recovery message sent
- [ ] Verify: Supabase query shows tier history

### 6. Operator Experience

When Rithmic fails (future outage):
1. Bot automatically suppresses L2-native strategies (77-B gate)
2. heartbeat.py writes `data_tier=2` to Supabase
3. tier_watch.py detects drop, sends 🚨 CRITICAL to @DDHealthbot
4. Operator sees alert and knows: "feed degraded, L2 down, bars-only running"
5. On recovery: ✅ alert sent, operator knows it's safe again

No more silent failures.

## Next: 77-D

Decommission Yahoo path (feed no longer used; clean up integration).
