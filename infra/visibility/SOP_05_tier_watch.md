# SOP 05 — Tier watch (WO-77-C, closes visibility of data tier degradation)

Deploy + acceptance for the tier-watch daemon on `ff-bot-prod`.
All commands run on the box unless marked **[off-box]**.

## What this is

- **77-B tier tracking** — bot_engine.py detects feed tier (0=full, 1=bars-only, 2=fallback, 3=dark) — **Already deployed** (code review in claude/read-r09-complete-wy3mzy).
- **Heartbeat tier telemetry** — heartbeat.py fetches tier from bot /api/state and writes data_tier, tier_name, feed_status columns to Supabase bot_health — **Already live** (deploy heartbeat.py from site repo).
- **77-C watcher** — tier_watch.py reads bot_health tier, state machine (OK/WARN/CRITICAL), routes transitions to @DDHealthbot — **This is what you deploy below.**

## 1. Deploy the watcher

From the site repo checkout, copy the watcher and units to the box:

```bash
# Copy tier_watch.py next to heartbeat.py / disk_watch.py
sudo -u tom cp infra/visibility/tier_watch.py /home/tom/futuresforged-bot/tier_watch.py

# Install systemd units
sudo cp infra/visibility/ff-tier-watch.service /etc/systemd/system/
sudo cp infra/visibility/ff-tier-watch.timer   /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable --now ff-tier-watch.timer
```

## 2. Acceptance (WO-77 closure) — the messages, not the rows

1. **Heartbeat populated with tier data** — [off-box]
   ```sql
   select ts, data_tier, tier_name, feed_rithmic, feed_l2, feed_nt 
   from bot_health 
   where service='bot' 
   order by ts desc limit 1;
   ```
   → should show data_tier (0-3), tier_name, and feed status booleans.

2. **Tier watcher running** — [on-box]
   ```bash
   systemctl status ff-tier-watch.timer
   journalctl -u ff-tier-watch.service -n 20 --no-pager
   ```
   → should show "[tier_watch] idle state=OK tier=0" (or whatever current tier is).

3. **Test: Simulate tier drop** — Do NOT kill real feeds; use test override
   ```bash
   # Stop the timer to avoid races
   sudo systemctl stop ff-tier-watch.timer
   rm -f ~/.tier_watch_state.json   # clean slate
   
   # Simulate WARN transition (tier 1 = bars only, no L2)
   # Edit ~/.tier_watch_state.json manually or trigger via db update
   # For testing: manually set a Tier 1 row in bot_health, then run:
   sudo -u tom python3 /home/tom/futuresforged-bot/tier_watch.py
   ```
   Expected: Message to @DDHealthbot:
   ```
   ⚠️ Feed degraded: OK → WARN
   Tier 1: RT no-L2 (Rithmic bars only)
   Strategy impact: bar-only run; L2-native paused.
   ```

4. **Test: Recovery** — Restore to Tier 0
   ```bash
   # Simulate recovery back to Tier 0
   # (set bot_health tier back to 0, then run watcher)
   sudo -u tom python3 /home/tom/futuresforged-bot/tier_watch.py
   ```
   Expected: Message to @DDHealthbot:
   ```
   ✅ Feed recovered: WARN → OK
   All strategies running again.
   ```

5. **Clean up test state**
   ```bash
   rm -f ~/.tier_watch_state.json
   sudo systemctl start ff-tier-watch.timer
   ```

## 3. Verify it's running

```bash
systemctl status ff-tier-watch.timer
journalctl -u ff-tier-watch.service --follow
```

On each 5-min tick, should log:
```
[tier_watch] idle state=OK tier=0
[tier_watch] transition OK → WARN (tier 1)  # when tier drops
[tier_watch] recovery WARN → OK              # when tier recovers
```

## Scope / not this order

WO-77-A (warming), 77-B (tier gating), 77-D (decommission Yahoo) are independent.
Do not widen this one.
