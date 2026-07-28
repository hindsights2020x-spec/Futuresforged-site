-- Rec #2 — Supabase `bot_health` table for off-box visibility.
-- Additive and idempotent. Apply via the Supabase SQL editor, the CLI, or MCP apply_migration.
-- Writes come from heartbeat.py using the SERVICE-ROLE key (bypasses RLS).
-- Reads use the publishable/anon key (same as the client already uses for bars/positions).

create table if not exists public.bot_health (
  id             bigint generated always as identity primary key,
  ts             timestamptz not null default now(),
  service        text        not null,          -- 'bot' | 'copier'
  port           int,
  up             boolean     not null,
  pid            int,
  git_sha        text,
  open_positions int,
  last_signal_ts timestamptz,
  fixes_applied  text[],
  extra          jsonb
);

create index if not exists bot_health_ts_idx         on public.bot_health (ts desc);
create index if not exists bot_health_service_ts_idx on public.bot_health (service, ts desc);

-- Latest row per service — the one an off-box session queries for "current state".
create or replace view public.bot_health_latest as
  select distinct on (service) *
  from public.bot_health
  order by service, ts desc;

-- RLS: read-only for anon (off-box visibility); inserts only via service role, which
-- bypasses RLS so no insert policy is needed. Tighten `to anon` -> `to authenticated`
-- if you don't want the publishable key to read health.
alter table public.bot_health enable row level security;

drop policy if exists bot_health_read on public.bot_health;
create policy bot_health_read on public.bot_health
  for select to anon using (true);

-- Optional retention: keep 7 days. Schedule via pg_cron if the extension is enabled.
-- select cron.schedule('bot_health_prune','*/30 * * * *',
--   $$delete from public.bot_health where ts < now() - interval '7 days'$$);
