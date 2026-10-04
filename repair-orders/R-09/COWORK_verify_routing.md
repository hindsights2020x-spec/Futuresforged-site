# R-09 — Verify order routing on-box (Cowork)

Run these in a **Cowork session on the ff-bot box** (the machine with `/home/tom/futuresforged-bot/`).
The goal: prove **which service handles `POST /api/place_order`** and **where `get_contracts()` runs for
manual orders**, so Fix A lands in the right file. This is the verification this off-box session could not do.

## 1. Which process owns :7331 (bot) and :7332 (copier)?
```bash
sudo ss -ltnp | grep -E ':7331|:7332'
# Note each PID → then map PID to its script:
ps -o pid,cmd -p <PID_7331> <PID_7332>
```
Expected: :7331 = the bot (serves `/studio`, token-gated `/api/*`, owns the Rithmic feed);
:7332 = the copier (open `/api/place_order`, `/api/state`, `/api/bars`).

## 2. Where is `/api/place_order` defined?
```bash
grep -rn "place_order" /home/tom/futuresforged-bot/*.py
```
Open the file that owns it (likely `copier_server.py`).

## 3. Does that handler size the order (call get_contracts) or just relay it?
```bash
# In the place_order handler's file:
grep -n "get_contracts\|enforce_limits\|contracts\|strategy\|manual\|runner\|run_c\|tp_c" <handler_file>.py
# And across the tree, find every get_contracts call site:
grep -rn "get_contracts(" /home/tom/futuresforged-bot/*.py
```
- If **get_contracts() is called inside the place_order handler** → apply Fix A there.
- If the handler **relays to the bot (:7331)** and sizing happens in `bot_engine.py` (~1895–2020) →
  apply Fix A at that bot-side site, and confirm the copier forwards `manual` + `contracts` unchanged:
  ```bash
  grep -n "requests.post\|forward\|relay\|:7331\|place_order\|payload\|json=" <handler_file>.py
  ```

## 4. Confirm the exact payload keys the server reads
```bash
grep -n "\.get(\"contracts\"\|\.get('contracts'\|\.get(\"qty\"\|\"strategy\"\|'strategy'\|\"manual\"\|'manual'" <handler_file>.py bot_engine.py
```
Confirms the server reads **`contracts`** (matches the client) and whether it already looks at
`strategy` / `manual`. Fix A gates on `strategy == "MANUAL" or manual`.

## 5. Live confirmation of the current (broken) behaviour, before the fix
```bash
# Replay the exact manual payload the UI sends (1 MNQ) against the copier:
curl -s -X POST http://localhost:7332/api/place_order \
  -H 'Content-Type: application/json' \
  -d '{"side":"BUY","direction":"BUY","manual":true,"instrument":"MNQ","contracts":1,"order_type":"MKT","strategy":"MANUAL"}'
# Then check the resulting order/position size in state:
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 "position\|contracts\|qty"
```
Expect **2 MNQ today**; **1 MNQ after Fix A**. (Use a sim/eval account, not the live-funded one, for this test.)

## 6. Report back
Record: the two PIDs/scripts, the file+line that calls `get_contracts()` for manual orders, whether the
copier sizes or relays, and the before/after contract count from step 5. That closes R-09 Issue 1.
