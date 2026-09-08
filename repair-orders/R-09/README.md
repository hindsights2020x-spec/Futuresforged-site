# R-09 — Chart Studio: Manual Trade Bypass + Price Lag

Completion pack for repair order **R-09** (`2026-07-13 R-09 Chart Studio Manual Trade Fix and Price Lag
Investigation`, from Tom). Prepared 2026-07-14.

> **Environment note:** this pack was produced off-box (Google Drive access only, no reach to the live
> ff-bot server or its running `bot_engine.py`). Client-side changes are **implemented**; the server-side
> change and all **live verification** must be applied/run on-box — see `COWORK_verify_routing.md`.

## Contents
| File | What it is |
|---|---|
| `client_chart_studio.html` | Modified Chart Studio (41 KB → 42 KB). Implements the two client-side changes below. |
| `bot_engine_manual_bypass.md` | Issue 1 · Fix A — server-side sizing bypass for manual orders (ready to apply on-box). |
| `COWORK_verify_routing.md` | On-box (Cowork) steps to confirm which service sizes manual orders + live before/after test. |
| `COPIER_ROUTING_MAP.md` | Assembled function → route mapping for the whole client copier (proves every function's routing; flags server-contract unknowns as OQ-n). |
| `SOP_copier_trade_readiness.md` | Single trade-readiness procedure (verify → apply Fix A → verify → go/no-go) + Open-Questions register for anything the other files don't answer. |
| `SOP_bot_shutdown.md` | Safe on-box shutdown runbook (flatten → confirm flat → stop copier then bot → verify down). |
| `COWORK_HANDOFF_activate_live_trading.md` | Handoff 41 — end-to-end on-box handoff to finish R-09 and activate live trading (verify → Fix A → SIM verify → go-live → report). |
| `COWORK_HANDOFF_42_fixA.md` | Handoff 42 — focused, self-contained handoff to apply & verify **Fix A only** (repo patcher *or* inline manual edit + SIM verify + rollback). |

## Issue 1 — manual trade hitting 2 MNQ (FIX)
- **Client (done, in `client_chart_studio.html`):** `placeOrder()` now sends `manual:true` alongside the
  existing `strategy:'MANUAL'` and `contracts:<n>`. See `placeOrder()` (~line 649).
- **Server (ready, not applied):** branch before `get_contracts()` on `manual`/`strategy=='MANUAL'`, use raw
  `contracts`, `run_c=0`. See `bot_engine_manual_bypass.md`.
- **Correction to R-09's premise:** manual orders POST to the **copier on :7332** (`/api/place_order`) and
  already carry `strategy:'MANUAL'`; the quantity key is **`contracts`**, not `qty`. Confirm the exact
  `get_contracts()` call site on-box before applying (Cowork doc).

## Issue 2 — Chart Studio price lag (INVESTIGATED + client fix implemented)
- **Root cause:** not the poll interval (Chart Studio polls *faster*, 1000 ms vs the dashboard's 1500 ms).
  The lag is the **data path**: Chart Studio read its live price from **Supabase** (1-minute OHLC `bars`
  table + the `client_l2` edge proxy), a round-trip away from the feed and quantized to 1-minute bar-close,
  while the dashboard reads the bot's own live `/api/state` same-origin on :7331.
- **Client (done, in `client_chart_studio.html`):** `pollL2()` now reads the bot's **live `/api/book` on
  :7331 via `botFetch`** first (one hop from the feed, no Supabase relay, live `mid`), and only falls back
  to the Supabase `client_l2` edge for license-gated clients / when the bot origin isn't reachable. This is
  exactly the source the file's own comments (lines 280, 758) call "the real L2 source." Candle *history*
  intentionally stays on Supabase.
- **Verify on-box:** with the bot token present, confirm the L2 "current price" tracks the market with no
  visible lag vs the position grid; confirm license-gated clients still get L2 via the edge fallback.

## Status
- Issue 2 investigation: **complete.**
- Client changes (both issues): **implemented** here; JS passes `node --check`.
- Server Fix A + live verification: **pending on-box** (Cowork).
