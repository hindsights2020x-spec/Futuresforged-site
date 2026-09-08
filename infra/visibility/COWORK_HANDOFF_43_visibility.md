# Handoff 43 — Stand up the Visibility Pack (permanent fix for off-box blindness)

**Goal:** end the "pending on-box / can't see the live box" problem for good, in three ordered steps:
**(1)** version the bot + deploy from git, **(2)** a Supabase health heartbeat, **(3)** guarded agent
access. After this, off-box/agent sessions can read the real code, see live runtime state, and (optionally)
act — so repair orders like R-09 stop stalling.

**Where to run:** on the **ff-bot box** (`/home/tom/futuresforged-bot/`) + a one-time Supabase step.
**Repo pack:** `hindsights2020x-spec/futuresforged-site`, branch `claude/client-copier-functions-nma9tx`,
folder `infra/visibility/` (scripts + full SOPs). Do the steps **in order**; 1+2 are the high-value core.

---

## Step 1 — Bot in git + deploy-from-git  → `SOP_01_bot_in_git.md`
1. Create a **private** `futuresforged-bot` repo.
2. On the box: copy `bot.gitignore.sample` → `.gitignore`, `git init`, **review `git status` for secrets**,
   commit the baseline, push to `main`.
3. Install `deploy.sh`; from now on deploy with
   `sudo BRANCH=main ./deploy.sh <copier-unit> <bot-unit>` (pull → backup → py_compile → restart → stamp sha).
- [ ] Bot builds from git; `git log` shows the baseline; a test deploy restarts cleanly.

## Step 2 — Supabase health heartbeat  → `SOP_02_heartbeat.md`
1. ~~Apply `bot_health.sql`~~ ✅ **already applied** to project `osxwkgmjwtdyvqwlfyre` (2026-07-16) — the
   `bot_health` table + `bot_health_latest` view exist. Skip to installing the writer.
2. Install `heartbeat.py`; create `/etc/ff/heartbeat.env` (chmod 600) with `SB_URL` + **service-role** `SB_KEY`.
3. Smoke-test once, then install + enable `ff-heartbeat.timer` (every 15s).
4. From off-box, `GET /rest/v1/bot_health_latest` with the publishable key.
- [ ] Off-box query returns live up/down + `git_sha` + open-position count + `fixes_applied`.

## Step 3 — Guarded agent access (optional)  → `SOP_03_agent_access.md`
**First, check for the SSH-free path** (`bot_commands_bus.md`): a `bot_commands` queue already exists,
owner-gated. Confirm whether the bot polls it — `grep -rn "bot_commands" /home/tom/futuresforged-bot/*.py`.
If it polls + dispatches a fixed allowlist, prefer **Option C** (enqueue command rows, no SSH). Otherwise:
1. Create restricted `ffagent` user; install `ff-agent-sudoers.sample` → `/etc/sudoers.d/ff-agent`
   (swap in real unit names); `visudo -cf` must pass.
2. Gate SSH to the tailnet + `ffagent` via Tailscale ACLs. (Or register the box as a self-hosted CCR runner.)
- [ ] Either: `bot_commands` consumption confirmed + allowlist verified (Option C), **or** a trusted tailnet
  device can `ssh ffagent@ff-bot 'sudo bash .../r09_verify.sh'` and nothing else (Option A).

---

## Guardrails
- Everything here is **read / telemetry / deploy** — it never places or cancels orders.
- `/api/place_order` + `/api/emergency` stay behind the tailnet + token. Sudoers is a fixed allowlist — no
  shell, no editor, no wildcard.
- Secrets (service-role key, `*.env`, keys) live in `chmod 600` files on the box, never in git — check
  `git status` before the first bot commit.
- Funded go-live stays a human decision (Handoff 41 §7).

## Report back
Confirm: bot repo URL + baseline sha; `bot_health_latest` sample row (proves off-box visibility); whether
Step 3 was enabled. Once Steps 1–2 are up, re-run **Handoff 42** (Fix A) — it can now be verified off-box
via the heartbeat, and future ROs no longer stall on visibility.
