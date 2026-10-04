# SOP 03 — Guarded agent access to the box (Rec #3)

**Why:** with #1 and #2 done, off-box sessions can *read* code and *see* runtime state — but still can't
*act*. This gives an authorized agent restricted hands on the box so it can run the verify/apply/restart
itself instead of writing a handoff for a human. Do this **after** #1 and #2, and only if you want agents
to close repair orders end-to-end.

**Run on the ff-bot box.** ~20 min. Security-sensitive — read the guardrails first.

## Option A (recommended) — Tailscale SSH + a restricted user
You already run a tailnet, so no new public exposure.
```bash
# 1. Dedicated, unprivileged user for the agent
sudo useradd -m -s /bin/bash ffagent

# 2. Restrict what it may sudo — read-only verify, restart/status the two units, list ports. Nothing else.
sudo cp /path/to/repo/infra/visibility/ff-agent-sudoers.sample /etc/sudoers.d/ff-agent
sudo sed -i 's/ff-copier/<your-copier-unit>/g; s/ff-bot/<your-bot-unit>/g' /etc/sudoers.d/ff-agent
sudo visudo -cf /etc/sudoers.d/ff-agent          # MUST print "parsed OK"

# 3. Gate SSH to the tailnet + this user via Tailscale ACLs (grant only trusted devices ssh to ffagent).
#    Keep the box's SSH bound to the tailnet interface, not the public IP.
```
An agent session on a trusted tailnet device can now run, e.g.:
`ssh ffagent@ff-bot 'sudo bash /home/tom/futuresforged-bot/r09_verify.sh'`.

## Option C — `bot_commands` Supabase command bus (preferred, if confirmed) → `bot_commands_bus.md`
A `public.bot_commands` queue already exists (RLS-gated to the two owner emails via `is_ff_admin()`). If the
live bot **polls and dispatches it via a strict allowlist**, an off-box admin agent can enqueue
`restart_copier` / `run_verify` / `redeploy` rows with **no SSH and full audit** — cleaner than Option A.
It's **not** on Realtime, so consumption is by polling and is **unconfirmed off-box**; verify on-box first:
`grep -rn "bot_commands" /home/tom/futuresforged-bot/*.py`. See `bot_commands_bus.md` for the safe design
(allowlist only, never order-placing) and usage. Until confirmed + allowlisted, use Option A.

## Option B — self-hosted Claude Code runner on the box
Register the box as a self-hosted CCR environment/pool so "on-box Cowork" is always one trigger away from
the web UI — the agent runs *in* the box's context (full repo + shell), no SSH round-trip. Best when you
want to launch on-box work from claude.ai directly. Scope its working dir to the bot repo.

## Guardrails (non-negotiable — this is a live trading box)
- **Least privilege:** the sudoers file grants a fixed command allowlist — no shell, no editor, no wildcard.
  Never add `ALL` or an editor to it.
- **Never expose order endpoints:** `/api/place_order` and `/api/emergency` stay behind the tailnet + token;
  agent access is for verify/deploy/restart, not a public control plane.
- **Keep humans in the loop for funded go-live:** agents may apply + SIM-verify; the funded smoke test
  (Handoff 41 §7) stays a human decision.
- **Auditability:** prefer the restricted user + sudoers (every action is logged) over sharing `tom`.
- Rotate the tailnet auth key / revoke the device if an agent session is retired.
