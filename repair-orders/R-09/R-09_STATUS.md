> ⛔ **SUPERSEDED 2026-07-19 — read this first.** Reading the live `copier_engine.py` disproved this
> order's core premise. Manual orders go `/api/place_order` → `copy_trade()` → `execute_order()`; they
> place `contracts` **verbatim** and **never call `get_contracts()`** (the only `get_contracts()` sites are
> `bot_engine.py`'s autonomous signal loop, so there is **no 2-contract minimum** on the manual path).
> **Do NOT apply R-09 Fix A / `r09_apply_fixA.py`** — it targets that signal loop and would break live
> signal trading. The real bug is an **order-vocabulary mismatch** (Chart Studio sends `BUY`/`MKT`; the
> copier expects `LONG`/`Market`), which made manual orders fail silently — and a latent `BUY→SELL` trap.
> Durable fix: branch **`claude/copier-order-normalization`** in the `futuresforged-bot` repo
> (`COPIER_ORDER_NORMALIZATION.md`). Everything below is retained for history only.

# R-09 — Chart Studio Manual Trade Bypass + Price Lag — STATUS
**Date:** 2026-07-14 **By:** Claude Code (off-box — Google Drive access only, NOT run on the ff-bot server)
**Companion to:** `2026-07-13 R-09 Chart Studio Manual Trade Fix and Price Lag Investigation`

---

## Scope note (read first)
Prior repair orders (R-03, R-07, …) were executed by agents running **directly on the ff-bot box / Tom's laptop** with live access to `/home/tom/futuresforged-bot/`. This session ran in an **isolated container with only Google Drive access** — the live box, its running services, and the current on-disk `bot_engine.py` (lines 1895–2020) were **not reachable**. So R-09's grep commands were not run against the live tree, and no live file was edited or service restarted.

The analysis below was done against the **current Drive snapshots**:
- `client_chart_studio.html` — 40,981 bytes (the 41 KB file R-09 names), `<title>FF · Chart Studio</title>`
- `dashboard.html` — 70,172 bytes, `<title>FuturesForged — Algo Engine</title>`

| R-09 item | Status |
|---|---|
| Issue 2 — price-lag investigation (INVESTIGATE FIRST, report before fixing) | ✅ **COMPLETE** — root cause found, evidence below |
| Issue 1 — manual-trade sizing bypass (FIX) | ⚠️ **READY-TO-APPLY** — exact server + client diffs below; server edit must be applied/verified on the live box |
| R-09's stated assumptions about Issue 1 | ⚠️ **Corrected** — manual orders do NOT go through :7331/get_contracts; they POST to the copier on :7332 and already carry `strategy:'MANUAL'` (details below) |

---

## Issue 2 — Chart Studio price lag — INVESTIGATION COMPLETE

### Root cause
**It is not a polling-cadence problem** — Chart Studio actually polls *faster* than the dashboard (1000 ms vs 1500 ms). The lag comes from the **data path and granularity**:

- **Chart Studio reads price from Supabase**, one or two network hops away from the feed:
  - Candle / "last price" = **1-minute OHLC bars** read back from the Supabase `bars` REST table (`tf=eq.1m`, price = bar **close** `c`). The bot must first *write* those bars to Supabase; the chart reads them back — so the price is delayed by the bot→Supabase publish + read round-trip, and only moves at **1-minute bar-close granularity**.
  - L2 ladder "current price" (`mid`) = the Supabase **`client_l2` edge function** proxy, not the bot's `/api/book` directly.
- **Dashboard reads the bot's own live in-memory state**, same-origin, one hop: `GET /api/state` on :7331 (the host that serves the page). Values are server-computed from the live feed — no Supabase, no bars, no 1-minute quantization.

### Evidence (verbatim, `client_chart_studio.html`)
Chart price = Supabase 1-minute bar close:
```
301  const POLL_BARS_MS = 1000;            // chart refresh cadence
410  var SB="https://osxwkgmjwtdyvqwlfyre.supabase.co", KEY="sb_publishable_...";
411  var r=await fetch(SB+"/rest/v1/bars?select=ts,o,h,l,c,v&symbol=eq."+chartRoot+"&tf=eq.1m&order=ts.desc&limit=400", ...);
785  pollBars();    setInterval(pollBars, POLL_BARS_MS);
```
L2 "current price" = Supabase edge proxy `mid`:
```
745  var L2_EDGE="https://osxwkgmjwtdyvqwlfyre.supabase.co/functions/v1/client_l2";
762  const lastPrice = (d.mid != null) ? d.mid : d.last_price;
842  pollL2();      setInterval(pollL2, 1000);
```
Even `/api/state` in Chart Studio points at the **copier on :7332**, a different service from the one the dashboard reads:
```
289  const ORDERFLOW_BASE = location.origin;                       // :7331 (bot, token-gated /api/book)
290  const COPIER_BASE    = `${location.protocol}//${location.hostname}:7332`;
291  const API = COPIER_BASE;
784  pollState();   setInterval(pollState, 1000);
```

### Evidence (verbatim, `dashboard.html`) — the accurate path
```
872  setInterval(poll, 1500);
877  const r = await fetch("/api/state", { headers: {"X-Bot-Token": window._BOT_TOKEN || ""} });
```
Dashboard's entire fetch surface is `/api/ready`, `/api/state`, and action endpoints — **no Supabase, no bars, no L2**. Position grid renders `pos.entry/stop/tp/direction` straight from that live state.

### Side-by-side
| | Chart Studio (lags) | Dashboard (accurate) |
|---|---|---|
| Transport | interval polling | interval polling |
| Price source | **Supabase** `bars` (1 m OHLC) + **Supabase** `client_l2` edge fn | bot's own `/api/state`, same-origin :7331 |
| Hops from feed | bot → Supabase → chart (round-trip) | bot in-memory → page (one hop) |
| Price type | **bar-close** (1-minute) / L2 mid via proxy | live feed-derived state |
| Poll interval | 1000 ms | 1500 ms |

### Recommended fix (per R-09, report before implementing — NOT applied)
Point Chart Studio's live-price readout at the **bot on the origin** the way the dashboard does — read `mid`/`last` from `:7331 /api/book` (via `botFetch`, token-gated) or `/api/state`, instead of the Supabase `bars` table and the `client_l2` edge function. Use tick/mid rather than 1-minute bar-close for the "current price" number. The candle *history* can stay on Supabase; only the **live price marker** needs to come from the bot. Awaiting Tom's go-ahead before any code change.

---

## Issue 1 — Manual trade hitting 2 MNQ minimum — READY-TO-APPLY

### What R-09 assumed vs. what the code actually does
R-09 says Chart Studio "routes orders through the bot's signal path (:7331) which enforces a 2-contract minimum in `get_contracts()`," and to "add a `manual=True` flag" and read `order.get("qty")`. The current client code differs on three points:

1. **Route:** manual orders `POST` to the **copier on :7332** (`API = COPIER_BASE`), endpoint `/api/place_order` — not the :7331 bot signal path.
2. **Manual intent is already sent:** the payload already sets **`strategy:'MANUAL'`**. So the server *receives* a manual marker today and is evidently **not honoring it** — it still runs sizing and emits the 2-contract (1 TP + 1 runner) minimum.
3. **Quantity key is `contracts`, not `qty`.** Any server bypass must read **`contracts`**, and the client already sends the exact quantity there.

Current client payload (`client_chart_studio.html`, lines 646–650, verbatim):
```js
const payload={side,direction:side,instrument:document.getElementById('instrument').value,
               contracts:Math.max(1,+qtyEl.value||1),order_type:orderType,strategy:'MANUAL'};
if(route) payload.group_id=route;
const r=await fetch(API+'/api/place_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
```

### Fix A (server) — bypass sizing for manual orders — **must be applied on the live box**
In the handler that processes `/api/place_order` (the copier service on :7332, and/or `bot_engine.py` order routing near lines 1895–2020 that R-09 cites — confirm on-box which one calls `get_contracts()` for these orders), branch **before** `get_contracts()` on the manual marker and use the raw `contracts` count, no runner leg:

```python
# order = incoming /api/place_order payload
if order.get("manual") or order.get("strategy") == "MANUAL":
    # Bypass get_contracts() — execute the exact quantity entered, no runner leg
    instr  = order.get("instrument", "MNQ")
    pv     = MNQ_PV if instr == "MNQ" else MES_PV
    tp_c   = max(1, int(order.get("contracts", 1)))   # NOTE: key is "contracts", not "qty"
    run_c  = 0
else:
    # Normal signal path — unchanged
    instr, pv, tp_c, run_c = get_contracts(...)
```
Notes:
- Keys match the real wire contract: gate on `strategy == "MANUAL"` (already sent) *and* accept an explicit `manual` flag; read quantity from **`contracts`**.
- Do **not** route manual `run_c` through the runner logic — `run_c = 0`.
- **Do not touch signal-trade sizing** or `enforce_limits()` (constraint carried from R-02).
- `MNQ_PV` / `MES_PV` / `NQ_PV` are the existing point-value constants in `bot_engine.py`.

### Fix B (client) — belt-and-suspenders explicit flag (optional; matches R-09 wording)
`strategy:'MANUAL'` already flags intent, but R-09 asks the UI to set `"manual": true` explicitly. One-line addition to the payload (line 646–647):
```js
const payload={side,direction:side,manual:true,
               instrument:document.getElementById('instrument').value,
               contracts:Math.max(1,+qtyEl.value||1),order_type:orderType,strategy:'MANUAL'};
```
This is safe with Fix A's `order.get("manual") or order.get("strategy")=="MANUAL"` guard. If Fix A gates on `strategy=='MANUAL'` alone, Fix B is not strictly required.

### Verify (on the box, after applying Fix A)
- Place a **1 MNQ** manual trade in Chart Studio → confirm **exactly 1 MNQ** executes, **no runner leg**.
- Place a **signal** trade → confirm normal sizing (TP + runner) still applies — signal path untouched.
- Confirm `contracts:3` manual → 3 MNQ, `run_c=0`.

---

## Guardrails honoured
- **Investigation-only for Issue 2**, per R-09 ("report findings before making any code changes"). No fix implemented.
- **No live file edited, no service restart** — off-box session, Drive snapshots only.
- Signal-trade sizing and `enforce_limits()` untouched in the proposed diffs (R-02 constraint).

## Handoff to whoever runs on-box next
1. Apply **Fix A** in the actual `/api/place_order` handler (confirm it's the copier :7332 service and/or `bot_engine.py` ~1895–2020) — the client already sends `strategy:'MANUAL'` + `contracts`, so the server change is the operative fix.
2. Optionally apply **Fix B** for an explicit `manual:true`.
3. Run the Issue-1 verify steps live.
4. For Issue 2, get Tom's go-ahead, then repoint Chart Studio's live-price readout from Supabase to the bot's `/api/book` / `/api/state` on :7331.

---
END — R-09 status
