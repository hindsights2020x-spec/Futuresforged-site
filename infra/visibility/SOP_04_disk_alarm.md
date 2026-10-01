# SOP 04 — Disk-space alarm (H-74, closes R-42 D1)

Deploy + acceptance for the disk-space telemetry and alarm on `ff-bot-prod`.
All commands run on the box unless marked **[off-box]**.

## What this is
- **74-A telemetry** — `bot_health.disk_free_bytes` / `disk_pct_used` (+ `swap_pct_used`,
  `mem_pct_used`). **Already live** via B9's `host_metrics()` (deployed since 2026-09-30
  03:18 UTC). Nothing to deploy for 74-A.
- **74-B view** — `v_disk_health` in Supabase. **Already applied** (migration
  `h74_74b_v_disk_health`; repo copy `v_disk_health.sql`). WARN <5 GiB, CRITICAL <2 GiB,
  CRITICAL fill >0.25 GiB/h, `samples>=45` guard.
- **74-C watcher** — `disk_watch.py` + `ff-disk-watch.{service,timer}`. **This is what you
  deploy below.** It reads `v_disk_health` and routes to the existing H-70E @DDHealthbot ->
  Tom channel via `ff_notifier` (no second channel).

## 1. Deploy the watcher
```bash
# from the site repo checkout, copy the watcher next to heartbeat.py / ff_notifier.py
sudo -u tom cp infra/visibility/disk_watch.py /home/tom/futuresforged-bot/disk_watch.py

# creds: add the H-70E Telegram vars to the heartbeat env (same token/chat the bot uses)
sudo sh -c 'grep -q TELEGRAM_BOT_TOKEN /etc/ff/heartbeat.env || cat >> /etc/ff/heartbeat.env <<EOF
TELEGRAM_BOT_TOKEN=<same token ff_notifier uses>
TELEGRAM_CHAT_ID=<the @DDHealthbot -> Tom chat id>
EOF'
sudo chmod 600 /etc/ff/heartbeat.env

# install the units
sudo cp infra/visibility/ff-disk-watch.service /etc/systemd/system/
sudo cp infra/visibility/ff-disk-watch.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ff-disk-watch.timer
```

## 2. Acceptance (work order §4) — the messages, not the rows

1. **Telemetry present** — [off-box]
   `select disk_free_bytes, disk_pct_used from bot_health order by ts desc limit 1;` → numbers.
2. **View sane** — [off-box]
   `select * from v_disk_health;` → plausible `fill_gb_per_h`, `samples>=45`, `state`.
3. **A real message for each condition.** Use the built-in test override — do NOT fill the disk.
   Each run should land a Telegram message **Tom actually receives**:
   ```bash
   sudo systemctl stop ff-disk-watch.timer          # avoid a real eval racing the test
   rm -f /home/tom/futuresforged-bot/.disk_watch_state.json   # start from OK

   # WARN transition
   sudo -u tom env $(grep -v '^#' /etc/ff/heartbeat.env | xargs) \
     FF_DISK_WATCH_FORCE=WARN python3 /home/tom/futuresforged-bot/disk_watch.py

   # CRITICAL transition (escalation)
   sudo -u tom env $(grep -v '^#' /etc/ff/heartbeat.env | xargs) \
     FF_DISK_WATCH_FORCE=CRITICAL python3 /home/tom/futuresforged-bot/disk_watch.py

   # RECOVERY
   sudo -u tom env $(grep -v '^#' /etc/ff/heartbeat.env | xargs) \
     FF_DISK_WATCH_FORCE=OK python3 /home/tom/futuresforged-bot/disk_watch.py
   ```
   Expect three messages: ⚠️ WARN, 🚨 CRITICAL, ✅ recovered. **Confirm receipt in Telegram.**
   That receipt is the evidence that closes ops_item 74-C — a log line or a row is not enough.
4. **Recovery clears state** — after the OK run, `.disk_watch_state.json` shows `"state":"OK"`.
5. **Short window is silent** — `FF_DISK_WATCH_FORCE=UNKNOWN ... disk_watch.py` sends nothing.
6. **Send is honest (F-004)** — each run prints `sent=True|False`. `sent=False` means Telegram did not accept it (no creds, FF_TELEGRAM_ALERTS=0, or HTTP error); the state file is NOT advanced, so the next run retries instead of going quiet for 4h.
7. **Blind monitor (F-001)** — not exercised by FORCE. Unforced runs also read bot_health directly and page "FF disk monitor BLIND" if rows arrive (newest <= 15 min) but none has disk_free_bytes for > 30 min. Rows stopped entirely = heartbeat outage, silent here (watch_config owns it).
8. **Hysteresis (F-002)** — WARN clears only at >= 6.0 GiB; CRITICAL clears only at >= 3.0 GiB and fill <= 0.20 GiB/h (or rate untrusted). The FORCE=OK row uses 8.9 GiB / 0.05 GiB/h so the step-3 recovery still fires.
6. **Heartbeat survives a disk read failure** — covered by B9's 16 tests; `host_metrics()`
   is wrapped so a `statvfs` failure leaves the columns NULL and never drops the row.

```bash
rm -f /home/tom/futuresforged-bot/.disk_watch_state.json   # clean slate after testing
sudo systemctl start ff-disk-watch.timer
```

## 3. Verify it's running
```bash
systemctl status ff-disk-watch.timer
journalctl -u ff-disk-watch.service -n 20 --no-pager     # each run prints state + reason
```

## Scope / not this order
D2 (recorder_health writer), D3 (l2rec runtime-reconnect restart), D4 (broker-flag
reminder), D6 (log volume), and the 18 GB root cause (R-42) are each their own order.
Do not widen this one.
