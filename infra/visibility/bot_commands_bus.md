# Rec #3 (alt) — `bot_commands` as an SSH-free command bus

Investigation of the existing `public.bot_commands` table as a cleaner alternative to Tailscale SSH for
letting an off-box/agent session **act** on the bot. Findings are from live Supabase metadata
(project `osxwkgmjwtdyvqwlfyre`, 2026-07-16).

## What exists today
| Aspect | Finding |
|---|---|
| Schema | `id`, `created_at default now()`, `command text NOT NULL`, `params jsonb`, `executed bool default false`, `executed_at timestamptz` |
| Shape | Classic **command queue**: enqueue a row → worker runs it → marks `executed=true, executed_at=now()` |
| RLS | one policy `admin all` = `is_ff_admin()` for ALL (using + with_check) |
| `is_ff_admin()` | `auth.jwt()->>'email' in ('tomolly88@gmail.com','ottruckline@gmail.com')` — i.e. the two owner emails |
| Realtime | **Not** published to `supabase_realtime` (only `signals` is) → any consumer must **poll**, not subscribe |
| Rows | 0, no table comment |

## The one thing that's unconfirmed (and why)
Whether the **live bot actually polls `bot_commands` and dispatches it** cannot be verified off-box — the
bot source isn't in any repo (exactly the gap Rec #1 fixes). The table looks built but is dormant (0 rows).
**Confirm on-box** before relying on it:
```bash
grep -rn "bot_commands" /home/tom/futuresforged-bot/*.py
# look for: a SELECT ... where executed=false loop, a command dispatch (if cmd=='restart' ...),
#           and an UPDATE ... set executed=true, executed_at=now()
```
- **If it polls + dispatches a fixed allowlist** → adopt it (Option C below); it beats SSH.
- **If it polls + `eval`/shell-execs `command`/`params`** → do NOT use until locked down (RCE via a DB row).
- **If nothing consumes it** → it's scaffolding; either wire the dispatcher (safe design below) or stick with
  SSH (SOP_03 Option A).

## Why it's attractive (if consumption is confirmed)
- **No new box exposure** — reuses the Supabase you already have; nothing new listens on the box.
- **Fully audited** — every action is a durable row (`command`, `params`, `created_at`, `executed_at`).
- **Already access-controlled** — only the two owner JWTs can read/write; the publishable/anon key cannot.
- **Agent-native** — an off-box agent signed in as an admin enqueues a row; no SSH keys, no sudoers.

## Safe design (the guardrails that make it acceptable on a trading box)
1. **Strict allowlist dispatcher.** The bot maps `command` to a fixed set of handlers and ignores anything
   else. Suggested vocabulary — **operational only, never order-placing**:
   `restart_copier`, `restart_bot`, `run_verify`, `redeploy` (git pull + deploy.sh), `heartbeat_now`,
   and at most `flatten` (already exposed via `/api/emergency`). **No** `place_order`, **no** raw shell,
   **no** `eval(params)`.
2. **Validate + bound `params`** per command (e.g. `redeploy` takes only a branch name matching `^[\w./-]+$`).
3. **Idempotency / no re-run.** Dispatch only `executed=false`; set `executed=true, executed_at=now()` in the
   same transaction before running side effects; ignore rows older than a TTL.
4. **Auth for the agent.** `is_ff_admin()` needs an **admin JWT** (owner login), not the anon key. Off-box
   agents authenticate with an owner session, or use the service-role key (box/agent-side secret only).
5. **Keep it control-plane-minimal.** This bus restarts/deploys/verifies; it must never become a way to
   inject trades. Trading stays on `/api/place_order` behind the tailnet + token.

## How an off-box admin agent would use it (once confirmed + allowlisted)
```sql
-- enqueue (as an FF admin session):
insert into public.bot_commands (command, params) values ('run_verify', '{}'::jsonb);
insert into public.bot_commands (command, params) values ('redeploy', '{"branch":"main"}'::jsonb);
-- watch for completion:
select id, command, executed, executed_at from public.bot_commands order by id desc limit 5;
```

## Recommendation
Treat this as **SOP_03 Option C — preferred once (a) on-box grep confirms the bot polls `bot_commands` and
(b) the dispatcher is a strict allowlist.** Until both are true, use Option A (Tailscale SSH). Do **not**
enqueue commands speculatively — if an unknown dispatcher is live, a single row could take real action.
_(This investigation only read metadata; no `bot_commands` rows were inserted.)_
