# WO-77-A: Warm NQ/ES on NinjaTrader Winbox

**Closes:** NQ fallback availability when Rithmic feed fails.  
**Depends on:** None.  
**Blocks:** 77-B (tier/degrade rules require warm prices available).

## Problem

On 2026-10-01 06:21 UTC, Rithmic ticker plant went offline (rpCode 13 / AMP billing). The NinjaTrader fallback (via FuturesForgedBridge addon) tried to serve NQ prices but failed:
- NQ contract was not in the bridge's warm list
- Bridge only had MNQ 09-26, ES 09-26 (stale, expired contracts)
- Watchdog correctly refused to synthesize chart off NQ=0.0
- Result: Full blackout despite NT backup existing

## Solution: 77-A

Update the NinjaTrader bridge's warm subscription list to include NQ and ES (full-size contracts) so they're available immediately when Rithmic fails.

### 1. Locate the config

On **winbox**, at:
```
%USERPROFILE%\Documents\NinjaTrader 8\ff_bridge.cfg
```

If the file does not exist, create it with the contents below.

### 2. Update or create ff_bridge.cfg

**Current (stale, insufficient):**
```
warm=MNQ 09-26,ES 09-26
```

**New (77-A complete):**
```
bind=0.0.0.0
port=36974
dryrun=false
warm=NQ,ES,MNQ,ES
pricewait=250
resolvewait=1200
warmtimeout=8000
mdthread=worker
```

**Explanation:**
- `warm=NQ,ES,MNQ,ES` — Subscribe/cache quotes for full-size NQ, ES, and micros MNQ, ES at startup
- No expiry (e.g., "09-26") — NinjaTrader resolves the front month automatically
- `bind=0.0.0.0` — Allow connections from other machines (ff-bot-prod via Tailscale)
- Other settings: defaults; tune if the log shows issues

### 3. Restart NinjaTrader

Once the config is saved:
1. Restart NinjaTrader (or just the FuturesForgedBridge AddOn if NT allows reload)
2. Check the NinjaTrader Log tab (Control Center → Log) for warming progress
3. Expect lines like:
   ```
   [FuturesForgedBridge] Warming NQ... resolved, subscribing...
   [FuturesForgedBridge] NQ ready (last px 23450.25)
   [FuturesForgedBridge] Warming ES... resolved, subscribing...
   [FuturesForgedBridge] ES ready (last px 5842.75)
   ```

### 4. Verify from ff-bot-prod

On the **ff-bot box**, test that the bridge is reachable and serving prices:

```bash
curl -X POST http://<winbox-ip>:36974 \
  -H "Content-Type: application/json" \
  -d '{"method":"STATE_REQ","account":"<nt-account-name>"}'
```

Expected response: Account state with position/balance, no timeout.

If you get `Connection refused` or timeout → bridge not running or not on correct port. Check NinjaTrader Log.

### 5. Test fallback

Once warmed, manually kill Rithmic on ff-bot-prod to verify the bot falls back to NT prices:

```bash
# On ff-bot-prod, stop the Rithmic connector
# (exact method depends on how it's integrated; usually a service or env flag)
sudo systemctl stop ff-rithmic  # if it exists, or equivalent
```

Monitor the bot log for fallback activation:
```
[FALLBACK] Rithmic down, switching to NinjaTrader prices
[NT BRIDGE] NQ 23450.25, ES 5842.75
```

Then restart Rithmic to restore primary feed.

## Acceptance

- [ ] ff_bridge.cfg updated with warm=NQ,ES,MNQ,ES
- [ ] NinjaTrader restarted; Log shows all four warming successfully
- [ ] Verified from ff-bot-prod: bridge responds to STATE_REQ
- [ ] (Optional, nice-to-have) Manually tested fallback activation

## Next: 77-B

Once 77-A is verified, implement 77-B (tier/degrade rules in bot_engine.py so strategies behave correctly when only NT prices are available).
