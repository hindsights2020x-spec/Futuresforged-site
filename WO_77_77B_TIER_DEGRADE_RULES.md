# WO-77-B: Tier/Degrade Rules in bot_engine.py

**Closes:** Strategies blindly running on degraded data, causing silent entry failures.  
**Depends on:** 77-A (NQ/ES warming on NinjaTrader winbox; must be done first).  
**Blocks:** 77-C (legibility + @DDHealthbot alerts — depends on tier tracking).

## Problem

On 2026-10-01, when Rithmic went offline:
- Bot tried to run Sweep Reverse, Box MR, etc. on stale/missing L2 data
- Entries silently failed (no L2, no bars, no update)
- Operator saw "running" but trades weren't happening
- No way to know if strategies were suppressed or just quiet

## Solution: 77-B

Implement a **tiered data model** that tracks feed quality and suppresses strategies that can't run on the current tier.

### Data Tiers

| Tier | Feed State | L2 Ready | NQ/ES Bars | Strategy Behavior |
|------|---|---|---|---|
| **Tier 0** (FULL) | Rithmic OK | ✓ | ✓ | All strategies run normally |
| **Tier 1** (RT no-L2) | Rithmic OK, but L2 down | ✗ | ✓ | Bar-only strategies run (Sweep, Box MR); hybrids skip unless opt-in |
| **Tier 2** (DELAYED) | NinjaTrader only; bars old | ✗ | ~ (stale) | Bar strategies suppress; exits only; hybrids off |
| **Tier 3** (DARK) | No feed at all | ✗ | ✗ | Nothing new; manage exits only |

### Strategy Classification

```python
# New in bot_engine.py, after STRATEGY_REGISTRY:

STRATEGY_TIERS = {
    # Bar-only (Tier 1+)
    "sweep_reverse":  {"type": "bar",      "min_tier": 1},
    "box_mr_london":  {"type": "bar",      "min_tier": 1},
    "box_mr_power":   {"type": "bar",      "min_tier": 1},
    
    # L2-dependent (Tier 0 only)
    "momentum_nq":    {"type": "l2_native", "min_tier": 0},
    "momentum_es":    {"type": "l2_native", "min_tier": 0},
}

def get_data_tier():
    """
    Determine feed tier (0-3) based on connector state and bar freshness.
    
    Tier 0: Rithmic connected, L2 live
    Tier 1: Rithmic connected, L2 offline
    Tier 2: Rithmic down, using NT fallback (bars may be stale)
    Tier 3: No feed at all
    """
    rithmic_ok = _rc and getattr(_rc, "connected", False)
    nt_ok = _nt and getattr(_nt, "connected", False)
    
    # Check L2 freshness (if recording)
    l2_fresh = False
    if _l2_mom and _l2_mom.cfg.enabled:
        # Last update in the last 10s?
        try:
            l2_age = time.time() - _l2_mom._last_frame_ts
            l2_fresh = l2_age < 10
        except:
            pass
    
    # Bar freshness (1m bars within last 5 min)
    bars_fresh = _is_feed_ok()
    
    if rithmic_ok and l2_fresh:
        return 0  # FULL: Rithmic + L2
    elif rithmic_ok and bars_fresh:
        return 1  # RT no-L2: Rithmic bars only
    elif nt_ok and bars_fresh:
        return 2  # DELAYED: NT fallback (may lag)
    else:
        return 3  # DARK: No feed
```

### Entry Gating (in engine_loop, line ~2700)

In the strategy check loop, add tier gating:

```python
# Around line 2700, BEFORE calling check_fn(acct):
for sid, check_fn in STRATEGY_REGISTRY.items():
    if not state["strategies"].get(sid, {}).get("enabled"):
        continue
    
    # ── NEW: Tier/degrade gate ──────────────────────────
    tier = get_data_tier()
    strat_info = STRATEGY_TIERS.get(sid)
    if not strat_info:
        continue  # unknown strategy, skip
    
    if tier < strat_info["min_tier"]:
        reason = TIER_NAMES.get(tier, f"tier_{tier}")
        gate_stats.record(f"{sid}_tier_gate", False, f"tier={reason}")
        if tier < 2:  # Only log on serious degradation
            log(f"[TIER-GATE] {sid} suppressed: requires tier {strat_info['min_tier']}, "
                f"current {tier} ({reason})", "INFO")
        continue
    
    # ── end tier gate ──────────────────────────────────
    
    signal = check_fn(acct)
    # ... rest of signal processing
```

### Tier Telemetry

Add to the heartbeat/dashboard status:

```python
# In the /api/status endpoint (around line 4080):
"current_tier": get_data_tier(),
"tier_name": TIER_NAMES.get(get_data_tier(), "unknown"),
"feed_status": {
    "rithmic": _rc and getattr(_rc, "connected", False),
    "l2_live": _l2_mom and _l2_mom.cfg.enabled and _l2_mom._last_frame_ts is not None,
    "bars_fresh": _is_feed_ok(),
    "nt_fallback": _nt and getattr(_nt, "connected", False),
}
```

### Tier Names (for logging)

```python
TIER_NAMES = {
    0: "FULL (Rithmic + L2)",
    1: "RT no-L2 (Rithmic bars only)",
    2: "DELAYED (NinjaTrader fallback)",
    3: "DARK (no feed)",
}
```

### Exit Behavior (Unchanged)

Exits are NEVER suppressed, even on Tier 3:
- Entry gates are tier-aware
- Exit logic (running stop, take-profit) always runs
- If a position exists, exit logic runs regardless of tier
- This prevents "stuck" positions when feed goes out

## Implementation Checklist

- [ ] Add `STRATEGY_TIERS` dict after `STRATEGY_REGISTRY`
- [ ] Add `TIER_NAMES` dict
- [ ] Add `get_data_tier()` function
- [ ] Add tier gate in engine_loop strategy loop (before `signal = check_fn(acct)`)
- [ ] Add tier telemetry to `/api/status` response
- [ ] Test: Run on Tier 0 (normal) → all strategies run
- [ ] Test: Disable L2_RECORD → Tier 1 → momentum strategies skip, bars run
- [ ] Test: Kill Rithmic → Tier 2 → bars-only run on NT prices
- [ ] Test: Kill all feeds → Tier 3 → no new entries, exits still work
- [ ] Verify gate_stats captures tier rejections

## Notes

- Tier detection is **read-only** — no config changes needed
- Tier gating is **soft** — a suppressed signal just moves to the next check
- Exits are **never gated** — a running position always attempts to exit
- Hybrids (if later added) would use `type: "hybrid"` and degrade rules per the spec

## Next: 77-C

Once 77-B is coded and tested, implement 77-C (data_tier visibility in Supabase + @DDHealthbot alerts when tier drops).
