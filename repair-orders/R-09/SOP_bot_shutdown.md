# SOP — Safe Bot / Copier Shutdown (on-box)

**Run on the ff-bot box only** (`/home/tom/futuresforged-bot/`). This cannot be done off-box / from a
repo session — there is no network path to the running services (bot :7331, copier :7332).

**Golden rule:** **flatten first, stop second.** Killing the process with open positions leaves them
live and unmanaged (no TP/SL/trail). Always confirm FLAT before stopping anything.

---

## Step 1 — Flatten all open positions
```bash
# same call Chart Studio's FLATTEN button makes:
curl -s -X POST http://localhost:7332/api/emergency \
  -H 'Content-Type: application/json' -d '{"scope":"account"}'
```

## Step 2 — Confirm FLAT (do not proceed until flat)
```bash
curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts\|qty'
# expect no open contracts. If anything remains, flatten again / close manually in the broker before Step 3.
```

## Step 3 — Identify the services (don't guess unit names)
```bash
sudo ss -ltnp | grep -E ':7331|:7332'          # note each PID
ps -o pid,cmd -p <PID_7331> <PID_7332>          # map PID -> script
systemctl list-units --type=service | grep -iE 'ff|bot|copier|futures'   # find the unit names
```

## Step 4 — Stop the services (copier first, then bot)
```bash
sudo systemctl stop <copier-service>            # :7332 first — stops new fan-out/orders
sudo systemctl stop <bot-service>               # :7331 — feed + signal engine
# If they are NOT systemd units, stop them the way they were started
# (e.g. the project's stop script, tmux/screen session, or: sudo kill <PID>; escalate to kill -9 only if needed).
```

## Step 5 — Verify down
```bash
sudo ss -ltnp | grep -E ':7331|:7332' || echo "both ports down — stopped."
```

---

## Notes
- **Prevent auto-restart:** if the units are `Restart=always` / enabled, also
  `sudo systemctl disable <service>` (or `systemctl stop` the socket/timer) so they don't respawn on boot.
  Re-enable with `sudo systemctl enable --now <service>` when bringing it back.
- **Restart later:** `sudo systemctl start <bot-service> && sudo systemctl start <copier-service>`, then
  reopen Chart Studio and confirm `SERVER ONLINE` + live L2 before trading.
- **Emergency only (positions already flat elsewhere):** `sudo kill <PID_7332> <PID_7331>`.
- This is a shutdown SOP only — it does **not** apply R-09 Fix A. Do that per
  `SOP_copier_trade_readiness.md` before trading again if it isn't yet applied.
