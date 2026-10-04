# Completion record — Work Order 74 (H-74): disk-space telemetry and alarm

**Closes:** R-42 **D1**. **Machine:** `ff-bot-prod`. **Date:** 2026-09-30.
**Deliverables in repo:** `infra/visibility/` — `v_disk_health.sql`, `disk_watch.py`,
`test_disk_watch.py`, `ff-disk-watch.service`, `ff-disk-watch.timer`, `SOP_04_disk_alarm.md`.

## Outcome by row

### 74-A — telemetry — DONE (already live, different shape)
Superseded the work order's original `extra->>'disk_free_gb'` plan **per the 74-A collision
note**: B9 (ops_item 33, migration `b9_bot_health_host_metrics`) already added DISCRETE columns
`disk_free_bytes`, `disk_pct_used`, `swap_pct_used`, `mem_pct_used`, and B9's `host_metrics()`
populates them on every heartbeat row. **Verified live:** disk columns present on every 1-min
row since **2026-09-30 03:18 UTC** (git_sha `8983781`); latest reading 12.2 GiB free, 63.8% used.
Adding jsonb `disk_free_gb` keys now would duplicate this — not done, deliberately.
Percent is `used/(used+available)` (df-style) and NULL means "not measured", per the note's
carry-over rules.

### 74-B — thresholds + view — DONE (built + verified + back-tested)
`v_disk_health` applied as migration `h74_74b_v_disk_health` (repo copy `v_disk_health.sql`),
reading B9's **discrete** `disk_free_bytes` (indexable, df-consistent) rather than jsonb — the
note's recommended base. Thresholds: **WARN <5.0 GiB** (prune floor), **CRITICAL <2.0 GiB**
(L2 recorder pause), **CRITICAL fill >0.25 GiB/h**. B9's single 2 GB warn is superseded; B9 had
no rate signal.
- **Rate method chosen:** secant across the available window (≤90 min), trusted only at
  `samples >= 45` — a short post-restart window returns UNKNOWN, never CRITICAL (the H-70E
  "unknown-as-value" class).
- **Verified live:** `state=OK, free 12.21 GiB, samples 90, fill 0.076 GiB/h`. Observed normal
  fill (0.076) sits right on the derivation's ~0.06 GiB/h, well under 0.25 — reality confirms §2b.
- **Back-test (work order §4 gate):** replayed 18.5 GiB → 0 at the event average (0.75 GiB/h)
  through the exact view rule in SQL. **Rate alarm fires at minute 30**, vs the level alarm at
  minute ~1085 (~18 h) — a **~17.6-hour** head start. Cold-start (samples gate binding) fires at
  minute 44. Both within "about an hour in", so §2b holds and does not need revisiting.

### 74-C — routing — CODE COMPLETE, closure is box-gated
`disk_watch.py` reads `v_disk_health` and routes WARN/CRITICAL/recovery to **@DDHealthbot -> Tom
over the existing H-70E path** (`ff_notifier.notify_sync`, category `error`) — no second channel.
Cadence: one message on transition, re-notify every 4h while in state, one on recovery. UNKNOWN
is silent and never counts as recovery. State persisted atomically in a small JSON file.
`systemd` timer evaluates every 5 min. **13 unit tests pass** (transition-once, 4h re-notify,
escalation, recovery-once, UNKNOWN-silence, plus the back-test mirror).

**Not closed.** The row's evidence is *a received message*, not code or a row — R-42 D5 is this
failure's third appearance and detection worked every time; what failed was reaching a person.
So 74-C stays **open** until, on the box:
1. deploy per `SOP_04_disk_alarm.md` §1;
2. run the forced WARN/CRITICAL/recovery test (§2.3) — `FF_DISK_WATCH_FORCE`, no disk-filling;
3. **Tom confirms he received the three Telegram messages.**

## Human/box-gated remainder
- Deploy `disk_watch.py` + units to `ff-bot-prod`; add `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
  to `/etc/ff/heartbeat.env` (the same creds the bot already uses).
- Confirm receipt of the three test messages → then set ops_item 74-C `done` with that evidence.

## Scope held (each its own order)
D2 (recorder_health writer), D3 (l2rec runtime-reconnect restart), D4 (broker-flag reminder),
D6 (log volume), and the 18 GB root cause (R-42). Not widened.
