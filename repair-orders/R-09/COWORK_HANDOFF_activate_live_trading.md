# COWORK HANDOFF — Activate Live Trading on the Copier (R-09)

**To:** the Cowork / Claude Code session running **on the ff-bot box** (`/home/tom/futuresforged-bot/`).
**From:** off-box repo session (Google-repo access only, no reach to the live box).
**Goal:** finish R-09 and bring the copier to **confirmed live-trading readiness**. Everything client-side
is done; only on-box server work + live verification remain.

**Repo with this pack:** `hindsights2020x-spec/futuresforged-site`, branch
`claude/client-copier-functions-nma9tx`, folder `repair-orders/R-09/`.

---

## 0. Ground rules (read first)
- **SIM / EVAL account for every test in Steps 3–6.** Do **not** touch the funded account until Step 7.
- **Do not modify** signal-trade sizing or `enforce_limits()` (R-02 constraint).
- **One change at a time**, keep the timestamped `.bak` the patcher writes.
- If anything is ambiguous, **stop and report** (Step 8) rather than guess — this is live order flow.
- Reference docs in this folder: `COPIER_ROUTING_MAP.md`, `SOP_copier_trade_readiness.md`,
  `bot_engine_manual_bypass.md`, `COWORK_verify_routing.md`, `r09_verify.sh`, `r09_apply_fixA.py`,
  `SOP_bot_shutdown.md`.

---

## 1. Confirm state & pull the pack
```bash
cd /home/tom/futuresforged-bot            # the live engine dir
git -C /path/to/futuresforged-site fetch origin claude/client-copier-functions-nma9tx
git -C /path/to/futuresforged-site checkout claude/client-copier-functions-nma9tx
ls repair-orders/R-09/
# Confirm the deployed client already carries the R-09 client fixes:
grep -n "manual:true"   /path/to/deployed/client_chart_studio.html    # expect ~:649
grep -n "botFetch('/api/book" /path/to/deployed/client_chart_studio.html  # expect ~:757
```
If the deployed Chart Studio does **not** contain those, deploy `repair-orders/R-09/client_chart_studio.html`
to wherever :7331 serves `/studio` from, then continue.

## 2. Verify routing (read-only) — resolves OQ-1, OQ-2
```bash
bash repair-orders/R-09/r09_verify.sh /home/tom/futuresforged-bot
```
Record: PID→script for :7331 and :7332, the file that owns `POST /api/place_order`, every
`get_contracts()` call site, and whether the copier **sizes locally** or **relays to the bot**.
→ This tells you which file Fix A lands in.

## 3. Apply Fix A (manual-order sizing bypass)
```bash
# dry-run against the file Step 2 identified (add --site N if multiple call sites,
# --order-var X if the payload dict isn't named `order`):
python3 repair-orders/R-09/r09_apply_fixA.py --file <engine_or_copier>.py
# when the preview is correct:
python3 repair-orders/R-09/r09_apply_fixA.py --file <engine_or_copier>.py [--site N] [--order-var X] --apply
python3 -m py_compile <engine_or_copier>.py
sudo systemctl restart <copier-or-bot-service>
```
If Step 2 showed the copier **relays** to the bot, apply Fix A at the bot-side `get_contracts()` site and
confirm the copier forwards `manual` + `contracts` untouched (see `bot_engine_manual_bypass.md` §"If the
copier forwards…").

## 4. Verify manual sizing (SIM/EVAL) — the core R-09 fix
```bash
curl -s -X POST http://localhost:7332/api/place_order -H 'Content-Type: application/json' \
  -d '{"side":"BUY","direction":"BUY","manual":true,"instrument":"MNQ","contracts":1,"order_type":"MKT","strategy":"MANUAL"}'
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts\|qty'
```
- [ ] 1 MNQ manual → **exactly 1** MNQ, **no runner leg** (was 2 before Fix A).
- [ ] `contracts:3` manual → **3** MNQ, `run_c=0`.
- [ ] a **signal** trade → normal **TP + runner** sizing unchanged.
Flatten between tests: `curl -s -X POST localhost:7332/api/emergency -H 'Content-Type: application/json' -d '{"scope":"account"}'`

## 5. Verify the rest of the surface (SIM/EVAL) — resolves OQ-4…OQ-7
```bash
curl -s localhost:7332/api/state | python3 -m json.tool | head -40     # OQ-4: groups/accounts/position/orders present?
curl -s -H "X-Bot-Token: $BOT_TOK" "localhost:7331/api/book?symbol=NQ" # OQ-6: {bids,asks,mid}
```
- [ ] Chart Studio shows **SERVER ONLINE**, live L2 tracks market (via `/api/book`), position grid populates.
- [ ] FLATTEN button flattens (OQ-5). Chart drag-to-modify TP/SL adjusts (OQ-7).

## 6. Decide OQ-3 — LMT/STP price (only if you trade non-MKT from Chart Studio)
The UI has MKT/LMT/STP buttons but **sends no price**. Find the copier's price key:
```bash
grep -rEn "limit_price|stop_price|'price'|\"price\"|\bpx\b" /home/tom/futuresforged-bot/*.py
```
Then either (a) report the key back and request the client price-field wiring, or (b) keep Chart Studio
**MKT-only** and note it. Do not send LMT/STP live until resolved.

## 7. Go-live (funded account)
Only after Steps 4–5 pass and the Go/No-Go table in `SOP_copier_trade_readiness.md` is all ✅:
- [ ] Switch route/account to the funded copier group.
- [ ] Place **1 MNQ** manual as a smoke test → confirm exactly 1 fills correctly, appears in history/position.
- [ ] Confirm fan-out to subscribed subs behaves as expected for the selected group.
- [ ] Live trading active.

## 8. Report back (closes R-09)
Paste: the two PIDs/scripts, where `get_contracts()` runs for manual orders, the `.bak` path, the
before/after contract counts from Step 4, OQ-3 decision + price key (if any), and the Step 7 smoke-test
result. Update `COPIER_ROUTING_MAP.md` (flip resolved 🟡→✅) and the OQ register in
`SOP_copier_trade_readiness.md`.

---

## Rollback
```bash
cp <engine_or_copier>.py.bak_R09_<timestamp> <engine_or_copier>.py
python3 -m py_compile <engine_or_copier>.py && sudo systemctl restart <service>
```
Emergency stop: follow `SOP_bot_shutdown.md` (flatten → confirm flat → stop copier then bot).
