# SOP 02 — Supabase health heartbeat (Rec #2)

**Why:** gives any off-box session a read-only answer to "is the bot up / what version is deployed / is it
flat / did a fix land" — the exact questions that can't be answered off-box today. Uses the Supabase stack
you already have (same as bars/positions), so no new infrastructure.

**Run on the ff-bot box + once in Supabase.** ~10 min.

## 1. Create the table  ✅ ALREADY DONE
Applied to the **FuturesForged** Supabase project (`osxwkgmjwtdyvqwlfyre`) on 2026-07-16 via migration
`bot_health_visibility` — `public.bot_health` + indexes + `bot_health_latest` view + read-only RLS policy
exist now. `bot_health.sql` (this folder) is the idempotent source if you ever need to re-apply/rebuild.
**Skip to Step 2.**

## 2. Install the writer + secrets on the box
```bash
cp /path/to/repo/infra/visibility/heartbeat.py /home/tom/futuresforged-bot/ && chmod +x heartbeat.py

sudo mkdir -p /etc/ff
sudo tee /etc/ff/heartbeat.env >/dev/null <<'ENV'
SB_URL=https://osxwkgmjwtdyvqwlfyre.supabase.co
SB_KEY=<SUPABASE_SERVICE_ROLE_KEY>
BOT_DIR=/home/tom/futuresforged-bot
FIXES_APPLIED=R-09-FixA
ENV
sudo chmod 600 /etc/ff/heartbeat.env      # secret — service-role key, box only, never in git
```
> Use the **service-role** key (bypasses RLS for inserts). It lives only in this 600 file, never committed.

## 3. Smoke-test, then schedule every 15s
```bash
sudo bash -c 'set -a; . /etc/ff/heartbeat.env; set +a; python3 /home/tom/futuresforged-bot/heartbeat.py'
# expect a line like:  2026-... {'bot': True, 'copier': True} sha 1a2b3c pos 0

sudo cp /path/to/repo/infra/visibility/ff-heartbeat.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ff-heartbeat.timer
systemctl list-timers ff-heartbeat.timer
```

## 4. Read it from off-box (verify visibility)
```bash
curl -s "$SB_URL/rest/v1/bot_health_latest?select=service,up,git_sha,open_positions,fixes_applied,ts" \
  -H "apikey: <PUBLISHABLE_KEY>" -H "Authorization: Bearer <PUBLISHABLE_KEY>"
```
Any off-box session (which already has the publishable key) can now see live up/down, deployed sha, open
positions, and which fixes are applied.

## Guardrails
- Service-role key **only** in `/etc/ff/heartbeat.env` (chmod 600). The publishable key is read-only by RLS.
- Health rows expose up/down, sha, and an open-position **count** (not order details). To hide even that
  from the publishable key, change the policy in `bot_health.sql` from `to anon` to `to authenticated`.
- This is **telemetry only** — it never places or cancels orders.
