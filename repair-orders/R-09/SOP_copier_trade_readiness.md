# SOP — Client Copier Trade-Readiness (R-09)

**Purpose:** single procedure to take the client copier from "client changes done" to "confirmed
ready to trade," plus a register of the questions the existing files do **not** answer (and how to
answer each). Companion to `COPIER_ROUTING_MAP.md`.

**Environment reality:** the client (`client_chart_studio.html`) is complete and lives in this repo.
The sizing engine (`bot_engine.py` / `copier_server.py`, `get_contracts()`) lives **on the ff-bot box**
(`/home/tom/futuresforged-bot/`) and is **not in this repo**. Steps B–D are on-box.

**Accounts:** run every live test on a **SIM / EVAL** account, never the funded one, until Step D passes.

---

## Section A — Pre-flight routing verification (read-only, on-box)

1. Run the discovery script:
   ```bash
   bash r09_verify.sh /home/tom/futuresforged-bot
   ```
2. Confirm from its output:
   - [ ] `:7331` → bot process, `:7332` → copier process (Step 1 of the script).
   - [ ] which file defines `POST /api/place_order` (Step 2).
   - [ ] every `get_contracts()` call site, and whether the copier **sizes** or **relays** (Step 3/5) → resolves **OQ-1**.
   - [ ] server reads quantity from **`contracts`** (Step 4) → confirms client contract.
3. Confirm the client is unchanged and valid (off-box, already done here):
   ```bash
   node --check <(sed -n '/use strict/,/<\/script>/p' client_chart_studio.html)   # PASS
   grep -n "manual:true" client_chart_studio.html                                 # :649
   ```

---

## Section B — Apply Fix A (server sizing bypass)

Apply in the file Section A identified as the manual-order sizing site.

1. Dry-run (default — no write):
   ```bash
   python3 r09_apply_fixA.py --file /home/tom/futuresforged-bot/<engine>.py
   # multiple call sites? pick the MANUAL/place_order one:
   python3 r09_apply_fixA.py --file .../<engine>.py --site N
   # payload dict not named `order`? pass it:
   python3 r09_apply_fixA.py --file .../copier_server.py --order-var data
   ```
2. When the preview is correct, write (saves a timestamped `.bak` first):
   ```bash
   python3 r09_apply_fixA.py --file .../<engine>.py [--site N] [--order-var X] --apply
   ```
3. Compile + restart:
   ```bash
   python3 -m py_compile /home/tom/futuresforged-bot/<engine>.py
   sudo systemctl restart <copier-or-bot-service>   # or the project's restart method
   ```

**Guardrails (from `bot_engine_manual_bypass.md`):** gate on `strategy=="MANUAL" or manual`; read
`contracts`; `run_c=0`; **do not** touch signal sizing or `enforce_limits()`; keep the `.bak`.
If the copier **relays** to the bot (OQ-1 = relay), apply Fix A at the bot-side `get_contracts()` site
and confirm the copier forwards `manual` + `contracts` untouched.

---

## Section C — Verify (live, SIM/EVAL account)

```bash
curl -s -X POST http://localhost:7332/api/place_order \
  -H 'Content-Type: application/json' \
  -d '{"side":"BUY","direction":"BUY","manual":true,"instrument":"MNQ","contracts":1,"order_type":"MKT","strategy":"MANUAL"}'
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts\|qty'
```
- [ ] 1 MNQ manual → **exactly 1 MNQ**, **no runner leg** (was 2 before Fix A).
- [ ] `contracts:3` manual → **3 MNQ**, `run_c=0`.
- [ ] a **signal** trade → normal **TP + runner** sizing still applies (signal path untouched).

---

## Section D — Go / No-Go to trade

| Gate | Pass condition | State |
|---|---|---|
| Client routing | `COPIER_ROUTING_MAP.md` table all ✅ / 🟡-resolved | ✅ (client) |
| Fix A applied | patcher wrote + `py_compile` OK + service restarted | ⛔ pending on-box |
| Manual sizing | Section C 1-MNQ = 1, 3 = 3, no runner | ⛔ pending |
| Signal sizing | unchanged (TP+runner) | ⛔ pending |
| L2 live price | tracks market via `/api/book`, edge fallback works | ⛔ pending |
| Order types | MKT verified; LMT/STP **OQ-3** resolved or documented MKT-only | ⛔ see OQ-3 |

**Ready to trade only when every gate is ✅.** Today: **NO-GO** — client is ready, server Fix A and the
live verifies are outstanding.

---

## Section E — Open-Questions register (unknowns the existing files do not answer)

Each item: what's unknown, why it matters, and the exact command that resolves it. On resolution, update
`COPIER_ROUTING_MAP.md` (flip 🟡→✅) and this SOP.

| ID | Open question | Why it matters | How to resolve (on-box) |
|---|---|---|---|
| **OQ-1** | Does the copier **size** manual orders locally, or **relay** to the bot? | Determines which file Fix A lands in. | `grep -rn "get_contracts(\|requests.post\|:7331" /home/tom/futuresforged-bot/*.py` (r09_verify.sh Steps 3 & 5). |
| **OQ-2** | Exact file+line of the `get_contracts()` call on the manual path. | Precise Fix A target / `--site N`. | `r09_apply_fixA.py --file <engine>.py` lists sites. |
| **OQ-3** | What payload key does the copier read for a **LMT/STP price**? Client sends none. | LMT/STP orders currently priceless → reject/mis-price. Blocks non-MKT trading. | `grep -rEn "limit_price\|stop_price\|'price'\|\"price\"\|\bpx\b" /home/tom/futuresforged-bot/*.py`. Then wire a conditional price input in `placeOrder()` sending that key. |
| **OQ-4** | Exact `/api/state` schema (`groups`, `accounts`, `position`, `orders`). | `renderRoutes/Position/Pnl/History` assume field names. | `curl -s localhost:7332/api/state | python3 -m json.tool` — diff keys vs the map. |
| **OQ-5** | `/api/emergency` accepted `scope` values + response. | Confirm `{scope:'account'}` flattens as intended. | `grep -n "emergency\|scope" <copier>.py`; test on SIM. |
| **OQ-6** | `/api/book` symbol param + response shape on :7331. | L2 primary path correctness. | `curl -s -H "X-Bot-Token: $TOK" "localhost:7331/api/book?symbol=NQ"`. |
| **OQ-7** | `/api/modify_position` accepted `field` values + effect. | Chart drag-to-modify TP/SL/TRAIL. | `grep -n "modify_position\|field" <copier>.py`; test on SIM. |

**Rule (per this task):** any future question not answered by an existing file gets a new row here plus,
if it defines behaviour, an SOP section and a `COPIER_ROUTING_MAP.md` entry — do not leave it implicit.
