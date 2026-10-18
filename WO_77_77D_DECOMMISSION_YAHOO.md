# WO-77-D: Decommission Yahoo Data Path

**Closes:** Obsolete connector code + dependencies (replaced by Rithmic + NinjaTrader fallback).  
**Depends on:** None (independent of 77-A/B/C).  
**Blocks:** None.

## Problem

Yahoo market-data connector was a temporary fallback before Rithmic + NinjaTrader became standard. It's now:
- Unused (no active subscriptions)
- Unmaintained (API changes deprecated it)
- Dead weight in codebase (imports, config, test mocks)

With 77-A (NT warming) + 77-B/C (tier detection + alerts), Yahoo is redundant.

## Solution: 77-D

Remove Yahoo path cleanly.

### 1. Identify Yahoo Code

Search for Yahoo references in bot_engine.py and related files:

```bash
grep -rn "yahoo\|Yahoo\|YAHOO" /home/user/futuresforged-bot/ --include="*.py" | head -20
```

Expected hits:
- Imports: `from yahoo_connector import ...`
- Initialization: `_yc = YahooConnector(...)`
- Feed logic: `elif connector == "yahoo"`
- Config: `"connector": "yahoo"` in accounts
- Tests: `test_yahoo_...`

### 2. Removal Steps

In bot_engine.py and related files:

**A. Remove imports**
```python
# DELETE: from yahoo_connector import YahooConnector
# DELETE: import yahoo_connector
```

**B. Remove globals**
```python
# DELETE: _yc = None  # Yahoo connector (Handoff ...)
```

**C. Remove initialization**
```python
# DELETE: entire section that starts _yc = YahooConnector(...)
```

**D. Remove feed startup**
```python
# DELETE: if _yc: _yc.connect() or similar
```

**E. Remove execution logic**
```python
# DELETE: elif connector == "yahoo": ex = YahooExecutor(...)
# DELETE: elif connector == "yahoo": handle snapshot, etc.
```

**F. Remove from config fallback**
```python
# In ACCOUNTS or elsewhere, DELETE any fallback paths that mention yahoo
```

**G. Remove files** (if separate modules)
```bash
rm -f /home/tom/futuresforged-bot/yahoo_connector.py
rm -f /home/tom/futuresforged-bot/yahoo_executor.py
rm -f /home/tom/futuresforged-bot/test_yahoo_*.py
```

**H. Remove from .gitignore** (if yahoo-specific entries)
```
# DELETE lines like: .yahoo_cache, yahoo_token.json, etc.
```

### 3. Testing

```bash
# Compile to verify no syntax errors
python3 -m py_compile bot_engine.py

# Grep to ensure no lingering yahoo references
grep -r "yahoo\|Yahoo" /home/user/futuresforged-bot/ --include="*.py" || echo "Clean ✓"

# Run existing unit tests (should still pass)
python3 -m unittest discover -s . -p "test_*.py" -v
```

### 4. Documentation

Update CLAUDE.md or inline comments:
```
# OLD (if exists):
# Fallback chain: Rithmic → NinjaTrader → Yahoo (deprecated)

# NEW:
# Fallback chain: Rithmic → NinjaTrader
# (Yahoo removed 2026-10 per WO-77-D)
```

## Acceptance Criteria

- [ ] All Yahoo imports removed
- [ ] Yahoo connector initialization removed
- [ ] No "elif connector == 'yahoo'" or similar
- [ ] Yahoo module files deleted (if separate)
- [ ] Code compiles cleanly (no syntax errors)
- [ ] grep -r "yahoo" returns zero hits (case-insensitive)
- [ ] Existing unit tests still pass
- [ ] Commit message cites this WO-77-D spec

## Safety Notes

- This is **code cleanup only** — no behavioral change (Yahoo wasn't used)
- **Safe to do anytime** (no production impact)
- Can be done in parallel with other WO-77 parts
- Verify with `grep` before and after to ensure completeness

## Why Now?

With Rithmic + NinjaTrader fallback in place (77-A/B), Yahoo is no longer a fallback option. Keeping dead code:
- Increases surface area for bugs
- Confuses future maintainers
- Adds unused test mocks

Removing it makes the codebase cleaner and more maintainable.

## Next Steps

1. Identify all Yahoo references (grep)
2. Remove systematically (imports → globals → logic)
3. Compile + test
4. Commit with WO-77-D reference
5. Deploy (no box restart needed; code-only)

This is a **code cleanup** task — lower priority than 77-A/B/C, but good to do before merge to main.
