# Handoff 44 — Deploy the copier order-normalization fix to the live box

**Goal:** get the merged fix (PR #9, `futuresforged-bot` `main`) onto the running box and restart the copier
(:7332), so Chart Studio manual orders actually execute — with the correct side and quantity.

**Where:** on the **ff-bot box** (`/home/tom/futuresforged-bot/`), as `tom` (or via Cowork on the box).
**Account:** do the verify (Step 5) on a **SIM / EVAL** account first. Do not touch the funded account until it passes.

> **Why not `deploy.sh` / `git pull` here?** The box's local `main` has an **unpushed** "Import live ff-bot
> tree (baseline)" commit, so it has diverged from `origin/main` — a fast-forward pull will fail. PR #9
> changed only `copier_engine.py` (plus a test + doc), so we pull **just that file**. No merge/rebase, no
> risk to the box's other local changes (e.g. modified `bot_engine.py`). Reconcile full git hygiene later.

---

## 1. Back up the current copier
```bash
cd /home/tom/futuresforged-bot
cp copier_engine.py copier_engine.py.bak_$(date +%Y%m%d_%H%M%S)
```

## 2. Pull ONLY the merged file(s) from GitHub
```bash
git fetch origin main
git checkout origin/main -- copier_engine.py
# optional (test + doc, harmless):
git checkout origin/main -- test_order_normalization.py COPIER_ORDER_NORMALIZATION.md
```

## 3. Compile + run the test (must both pass before restarting)
```bash
python3 -m py_compile copier_engine.py
python3 -m unittest test_order_normalization -v      # expect: 5 tests OK
```

## 4. Restart the copier service
```bash
sudo ss -ltnp | grep :7332                # find the process/unit that owns :7332
sudo systemctl restart <copier-unit>      # use the unit name from above
sudo systemctl is-active <copier-unit>    # expect: active
```
If it's not a systemd unit, restart it the way it was started (its launch script / tmux / screen).

## 5. Verify on SIM / EVAL
```bash
# BUY 1 MNQ market in Chart Studio's vocabulary — must place a BUY of exactly 1:
curl -s -X POST http://localhost:7332/api/place_order -H 'Content-Type: application/json' \
  -d '{"side":"BUY","direction":"BUY","instrument":"MNQ","contracts":1,"order_type":"MKT"}'
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts'

# bad input must now be REJECTED loudly (was a silent ok:true before):
curl -s -i -X POST http://localhost:7332/api/place_order -H 'Content-Type: application/json' \
  -d '{"direction":"UP","instrument":"NQ","contracts":1,"order_type":"MKT"}'   # expect HTTP 400
```
Pass conditions:
- [ ] `BUY` places a **BUY** (not a SELL) of **exactly 1**.
- [ ] a `SELL` places a **SELL**.
- [ ] LMT/STP with a price work (`order_type:"LMT"` + `limit_price`).
- [ ] bad input returns **HTTP 400** with a message.
- [ ] the copier dashboard's own `LONG`/`Market` orders still work unchanged.

Flatten between tests:
```bash
curl -s -X POST http://localhost:7332/api/emergency -H 'Content-Type: application/json' -d '{"scope":"account"}'
```

## 6. Rollback (if anything looks wrong)
```bash
cp copier_engine.py.bak_<timestamp> copier_engine.py
sudo systemctl restart <copier-unit>
```

## 7. Report back
Confirm: the copier unit name, the SIM BUY result (side + qty), the 400 on bad input, and that funded
trading is or isn't switched on. That closes the manual-order fix end to end.

_Later, when not mid-session: reconcile the box's local `main` with `origin/main` (rebase the unpushed
baseline commit) so future deploys can use `deploy.sh` normally._
