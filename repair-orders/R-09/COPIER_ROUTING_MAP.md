# Client Copier — Function → Route Mapping

**Segment:** FF Chart Studio client (`client_chart_studio.html`) ↔ copier / bot / Supabase.
**Assembled:** 2026-07-14 (from the client source + R-09 docs). **Scope:** client-observable routing.
**Legend:** ✅ confirmed from client source · 🟡 server contract asserted by client, **confirm on-box** · 📄 see Open-Questions register in `SOP_copier_trade_readiness.md`.

> This is the assembled answer to *"are all functions properly routed?"* — every network-touching
> client function, the service it targets, the endpoint, auth, and payload/response shape it assumes.
> Anything the client cannot prove (the server's actual behaviour) is marked 🟡 and cross-referenced to
> an Open Question (OQ-n) with the on-box command that resolves it.

---

## 1. Endpoint bases (`client_chart_studio.html:289–298`)

| Const | Value | Resolves to | Auth |
|---|---|---|---|
| `ORDERFLOW_BASE` | `location.origin` | **Bot :7331** (serves this page, owns Rithmic feed) | token-gated — `X-Bot-Token: window._BOT_TOKEN` via `botFetch()` |
| `COPIER_BASE` / `API` | `${protocol}//${hostname}:7332` | **Copier :7332** | open (no token) |
| `SB` | `https://osxwkgmjwtdyvqwlfyre.supabase.co` | **Supabase** REST + edge | `apikey`/`Bearer` publishable key, or `?key=<license>` |

Host-relative by design (RO#03): bases derive from `window.location`, so the page works over the
tailnet IP / `ff-bot.futuresforged.com`, not just localhost.

---

## 2. Function → route map

| # | Client function | Source | Method | Service | Endpoint | Auth | Payload / params | Expected response | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `botFetch()` | :295 | (wrapper) | Bot :7331 | `ORDERFLOW_BASE + path` | `X-Bot-Token` | caller-supplied | caller-supplied | ✅ |
| 2 | `pollBars()` | :406 | GET | Supabase | `/rest/v1/bars?symbol=eq.<root>&tf=eq.1m&order=ts.desc&limit=400` | apikey/Bearer | — | `[{ts,o,h,l,c,v}]` | ✅ (candle history intentionally on Supabase) |
| 3 | `placeOrder()` | :639 | POST | **Copier :7332** | `/api/place_order` | none | `{side,direction,manual:true,instrument,contracts,order_type,strategy:'MANUAL'[,group_id]}` | `{ok, results?[], msg?}` | ✅ client / 🟡 server sizing → **OQ-1, OQ-3** |
| 4 | `renderRoutes()` | :660 | (render) | — | reads `state.groups` / `state.accounts` | — | — | — | ✅ / 🟡 state shape → **OQ-4** |
| 5 | `flatten()` | :691 | POST | Copier :7332 | `/api/emergency` | none | `{scope:'account'}` | any 2xx | ✅ / 🟡 → **OQ-5** |
| 6 | `pollState()` | :733 | GET | Copier :7332 | `/api/state` | none | — | `{position,orders[],groups[],accounts{}}` | ✅ / 🟡 schema → **OQ-4** |
| 7 | `renderPosition/Pnl/History` | :695/710/722 | (render) | — | reads `state.position`, `state.orders` | — | — | — | ✅ |
| 8 | `pollL2()` — primary | :757 | GET | Bot :7331 | `/api/book?symbol=<sym>` | `X-Bot-Token` | `symbol` | `{bids[[px,sz]],asks[[px,sz]],mid}` | ✅ client / 🟡 → **OQ-6** |
| 9 | `pollL2()` — fallback | :766 | GET | Supabase edge | `/functions/v1/client_l2?key=<lic>&symbol=<sym>` | `?key=<license>` | `key,symbol` | `{bids,asks,mid\|last_price}` | ✅ (403 = tier-gated, handled) |
| 10 | `pollPositions()` | :803 | GET | Supabase | `/rest/v1/positions?status=eq.open&symbol=eq.<instr>&select=side,entry,tp,tp1,tp2,sl,trail,qty` | apikey/Bearer | — | `[{side,entry,tp,tp1,tp2,sl,trail,qty}]` | ✅ (chart entry/TP/SL lines) |
| 11 | chart drag → modify | :854 | POST | Copier :7332 | `/api/modify_position` | none | `{symbol,field,price}` | any 2xx (fire-and-forget) | ✅ client / 🟡 → **OQ-7** |

### Symbol mapping (`:298,:302`)
`ROOT_BY_INSTRUMENT`: `NQ→NQ, ES→ES, MNQ→NQ, MES→ES` (chart root). `BOOK_SYM`: `MNQ→NQ, MES→ES`
(micros track the full-size book for L2).

---

## 3. Routing verdict

- **Trading actions** (place / flatten / modify) → **Copier :7332** — consistent. ✅
- **Live L2** → **Bot :7331 `/api/book`** first (one hop from feed), Supabase edge fallback for
  license-gated clients — R-09 Issue 2 fix. ✅
- **History** (candles, open-position lines) → **Supabase** — intentional, not a defect. ✅
- **No orphaned or mis-targeted calls.** `node --check` passes.

**Every client function is routed to a defined endpoint on the correct service.** The remaining
uncertainty is entirely *server-side contract* (does the copier honour `manual`, what price key does it
read for LMT/STP, exact `/api/state` schema) — enumerated as OQ-1…OQ-7 in the SOP and resolvable only
on-box.

---

## 4. Client-only limitation flagged during assembly

`order_type` can be `MKT | LMT | STP` (`:230–233`) but the UI has **no price input** — LMT/STP orders
POST with `order_type` and **no price**. See **OQ-3** for the resolution procedure (identify the copier's
price key, then wire the field). Until resolved, treat Chart Studio as **MKT-only** for live trading.
