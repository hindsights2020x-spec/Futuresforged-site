# FF Visibility Pack — permanent fix for off-box blindness

The recurring problem: the live bot runs only on the ff-bot box, so off-box sessions work against
snapshots and stall at "pending on-box." This pack closes the gap in three ordered steps. Do them in
order — each builds on the last. Full deploy runbook: `COWORK_HANDOFF_43_visibility.md` (Handoff 43).

| # | Rec | Closes | Files | SOP |
|---|---|---|---|---|
| 1 | **Bot in git + deploy-from-git** | code visibility + snapshot/live drift | `deploy.sh`, `bot.gitignore.sample` | `SOP_01_bot_in_git.md` |
| 2 | **Supabase health heartbeat** | runtime visibility (up/down, sha, positions, fixes) | `heartbeat.py`, `bot_health.sql`, `ff-heartbeat.service`, `ff-heartbeat.timer` | `SOP_02_heartbeat.md` |
| 3 | **Guarded agent access** | agents can *act*, not just read | `ff-agent-sudoers.sample` | `SOP_03_agent_access.md` |

**Recommended:** do **1 + 2 first** — together they remove ~90% of the blindness with no new
infrastructure and no new attack surface. Add **3** when you want agents to close repair orders end-to-end.

## Guardrails (whole pack)
- Everything here is **read/telemetry/deploy** — none of it places or cancels orders.
- Order endpoints (`/api/place_order`, `/api/emergency`) stay behind the tailnet + token, always.
- Secrets (service-role key, `*.env`, keys) live in `chmod 600` files on the box, **never** in git.
- Funded go-live stays a human decision (Handoff 41 §7).

_All scripts are staged here to be carried on-box; they cannot run from an off-box repo session._
