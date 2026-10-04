# Handoff 42 — Apply & Verify Fix A (manual-order sizing bypass) — R-09

**Single purpose:** make a manual Chart Studio order execute the **exact `contracts` count with no runner
leg**. Today a 1 MNQ manual trade fires **2** because the server runs `get_contracts()` (2-contract
minimum: 1 TP + 1 runner) on manual orders. This handoff does **only** Fix A — nothing else.

**Where to run:** on the **ff-bot box** (`/home/tom/futuresforged-bot/`) — Cowork session or any on-box
shell. Cannot be done off-box (no reach to the live engine).

**Client is already done:** Chart Studio POSTs `manual:true` + `strategy:'MANUAL'` + `contracts:<n>` to
`:7332/api/place_order`. This handoff is purely the **server** half.

> ⛔ **STOP — 2026-07-19 on-box finding supersedes the method below.** Reading the live code shows the
> manual path is `copier_engine.py` `/api/place_order` → `copy_trade(...)`, which passes `contracts`
> **verbatim** and **never calls `get_contracts()`**. The only `get_contracts()` call sites are
> `bot_engine.py:1903/1976` in the **autonomous signal loop**. Therefore:
> - **DO NOT run `r09_apply_fixA.py`.** Its pattern matches those signal-loop lines; the inserted `order.get(...)`
>   references a variable that doesn't exist there → `NameError` that breaks live signal trading.
> - The real 2-MNQ source (if any) is inside **`copy_trade()`** — fix belongs there, pending its review.
> - Also: the copier already reads `limit_price`/`stop_price`/`trail_pts`, so LMT/STP just need the client to send them.
>
> _The 2A/2B methods below are retained for history only and are NOT the current plan._

> Two ways to apply below — **A) the repo patcher** (preferred, idempotent, auto-backup) or **B) a manual
> edit** (fully inline; use if the repo isn't checked out on the box). Do one, not both.

---

## 0. Guardrails
- **SIM / EVAL account only** for the verify step. Do **not** test on the funded account.
- **Do NOT touch** signal-trade sizing or `enforce_limits()` (R-02 constraint). Only the manual branch.
- Keep a timestamped `.bak` before writing (the patcher does this automatically).
- `MNQ_PV` / `MES_PV` are the **existing** point-value constants — reuse, don't redefine.
- If the exact call site doesn't match the pattern below, **stop and report** (§5) — don't force it.

---

## 1. Locate the sizing call site
```bash
cd /home/tom/futuresforged-bot
# Which file serves POST /api/place_order?
grep -rn "place_order" ./*.py
# Every get_contracts() call site — find the one on the manual/place_order path:
grep -rn "get_contracts(" ./*.py
# Confirm the server reads the quantity from `contracts` and sees strategy/manual:
grep -rEn "get\(['\"](contracts|strategy|manual|instrument)['\"]" ./*.py
```
- If `get_contracts()` is **inside** the place_order handler's file → patch there.
- If the copier (:7332) **relays** to the bot (:7331) and sizing happens in `bot_engine.py`
  (~lines 1895–2020) → patch at that bot-side site, and confirm the copier forwards `manual` +
  `contracts` unchanged: `grep -rnE "requests.post|json=|:7331" ./*.py`.

Note the **file** and the **variable name of the incoming payload dict** (often `order`, sometimes
`data`/`req`/`body`/`payload`). You need both for Step 2.

---

## 2A. Apply with the repo patcher (preferred)
```bash
# from the checked-out repo (branch claude/client-copier-functions-nma9tx), folder repair-orders/R-09/
# dry-run (no write); add --site N if grep showed multiple get_contracts() sites,
# --order-var X if the payload dict isn't named `order`:
python3 r09_apply_fixA.py --file /home/tom/futuresforged-bot/<engine_or_copier>.py
# when the preview looks right, write it (saves a .bak first):
python3 r09_apply_fixA.py --file /home/tom/futuresforged-bot/<engine_or_copier>.py [--site N] [--order-var X] --apply
```
The patcher is idempotent (re-running is a no-op once the `R-09 manual bypass` marker is present) and only
matches the exact 4-tuple assignment `instr, pv, tp_c, run_c = get_contracts(`. If it reports "no match,"
use **2B**. Then go to Step 3.

## 2B. Apply by hand (inline — no repo needed)
Back up, then branch **before** the `get_contracts()` call. Replace `order` with the real payload var
from Step 1, and keep the original assignment intact under `else:`.

```bash
cp /home/tom/futuresforged-bot/<engine_or_copier>.py \
   /home/tom/futuresforged-bot/<engine_or_copier>.py.bak_R09_$(date +%Y%m%d_%H%M%S)
```

Find the line (indentation will vary — match it exactly):
```python
        instr, pv, tp_c, run_c = get_contracts(...)
```
Replace it with:
```python
        if order.get("manual") or order.get("strategy") == "MANUAL":
            # R-09 manual bypass — execute exact qty, no runner leg (Issue 1)
            instr = order.get("instrument", "MNQ")
            pv    = MNQ_PV if instr == "MNQ" else MES_PV
            tp_c  = max(1, int(order.get("contracts", 1)))   # wire key is "contracts", not "qty"
            run_c = 0
        else:
            instr, pv, tp_c, run_c = get_contracts(...)      # ORIGINAL line, unchanged, re-indented
```
Rules: gate on `strategy=="MANUAL" or manual` (the `or` keeps old clients working); read `contracts`;
`run_c = 0`; leave the signal path (`else:`) byte-for-byte the same.

---

## 3. Compile & restart
```bash
python3 -m py_compile /home/tom/futuresforged-bot/<engine_or_copier>.py   # must be silent (no error)
sudo systemctl restart <copier-or-bot-service>                            # the service that owns the patched file
# find the unit if unsure:  sudo ss -ltnp | grep -E ':7331|:7332'  →  systemctl status <unit>
```

---

## 4. Verify (SIM/EVAL account)
```bash
# 1 MNQ manual — must now size to exactly 1:
curl -s -X POST http://localhost:7332/api/place_order -H 'Content-Type: application/json' \
  -d '{"side":"BUY","direction":"BUY","manual":true,"instrument":"MNQ","contracts":1,"order_type":"MKT","strategy":"MANUAL"}'
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts\|qty'
# flatten before the next test:
curl -s -X POST http://localhost:7332/api/emergency -H 'Content-Type: application/json' -d '{"scope":"account"}'
```
Pass conditions:
- [ ] `contracts:1` manual → **exactly 1 MNQ**, **no runner leg** (was 2 before the fix).
- [ ] `contracts:3` manual → **3 MNQ**, `run_c = 0`.
- [ ] a **signal** trade → normal **TP + runner** sizing still applies (signal path untouched).

If any fails, roll back (§ below) and report.

---

## 5. Report back (closes R-09 Issue 1)
Paste: the patched **file + line**, whether the copier **sized locally or relayed**, the **`.bak` path**,
and the **before/after contract counts** from Step 4. Update `COPIER_ROUTING_MAP.md` (flip the manual-sizing
rows 🟡→✅) and OQ-1/OQ-2 in `SOP_copier_trade_readiness.md`.

---

## Rollback
```bash
cp /home/tom/futuresforged-bot/<engine_or_copier>.py.bak_R09_<timestamp> \
   /home/tom/futuresforged-bot/<engine_or_copier>.py
python3 -m py_compile /home/tom/futuresforged-bot/<engine_or_copier>.py && sudo systemctl restart <service>
```
Emergency stop (positions open): see `SOP_bot_shutdown.md` (flatten → confirm flat → stop copier then bot).

_Scope: this handoff is Fix A only. Full go-live (funded smoke test, LMT/STP decision, L2 checks) is
Handoff 41._
