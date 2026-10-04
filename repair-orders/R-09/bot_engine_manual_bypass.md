# R-09 · Issue 1 · Fix A (server) — manual-order sizing bypass

**Applies to:** the handler that serves `POST /api/place_order` — the **copier service on :7332**, and/or
`bot_engine.py` order routing (~lines 1895–2020) if that is where `get_contracts()` is invoked for
manual orders. **Confirm the exact site on-box first** (see `COWORK_verify_routing.md`).

**Why:** Chart Studio's manual orders already POST `strategy:'MANUAL'` + `contracts:<n>` (and, after this
pack, `manual:true`) to `/api/place_order`. The server currently ignores that and still runs
`get_contracts()`, which forces a **2-contract minimum (1 TP + 1 runner)** — so a 1 MNQ manual trade fires 2.

## The change
Branch **before** `get_contracts()` on the manual marker; use the raw `contracts` count with **no runner leg**.

```python
# order = the parsed /api/place_order payload
if order.get("manual") or order.get("strategy") == "MANUAL":
    # R-09: bypass get_contracts() sizing — execute the exact quantity entered, no runner leg.
    instr = order.get("instrument", "MNQ")
    pv    = MNQ_PV if instr == "MNQ" else MES_PV
    tp_c  = max(1, int(order.get("contracts", 1)))   # wire key is "contracts", NOT "qty"
    run_c = 0
else:
    # Normal signal path — unchanged.
    instr, pv, tp_c, run_c = get_contracts(...)
```

## Rules / guardrails
- Gate on **`strategy == "MANUAL"`** (already sent today) **and** an explicit **`manual`** flag (added by this
  pack's client). Either is sufficient — the `or` keeps it backward-compatible with older clients.
- Read the quantity from **`contracts`** (not `qty`). The client sends the exact count there.
- `run_c = 0` — do **not** route the manual quantity through runner logic.
- **Do not** touch signal-trade sizing or `enforce_limits()` (constraint carried from R-02).
- `MNQ_PV` / `MES_PV` / `NQ_PV` are the existing point-value constants — reuse them, don't redefine.
- Keep an idempotent `.bak` backup before writing (house convention), e.g.
  `cp bot_engine.py bot_engine.py.bak_R09_$(date +%Y%m%d_%H%M%S)`.

## If the copier forwards to the bot instead of sizing locally
If `COWORK_verify_routing.md` shows the copier (:7332) merely **relays** manual orders to the bot's
signal path (:7331) — and the sizing happens there — apply the same branch at the bot-side entry point
(the `bot_engine.py` ~1895–2020 region R-09 cited) and make sure the copier **forwards the `manual`
flag and `contracts`** untouched in the relayed payload.

## Verify (live, on-box)
1. 1 MNQ manual via Chart Studio → **exactly 1 MNQ** executes, **no runner leg**.
2. A **signal** trade → normal TP + runner sizing still applies (signal path untouched).
3. `contracts:3` manual → 3 MNQ, `run_c = 0`.
