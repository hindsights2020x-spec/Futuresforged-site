-- H-74 / 74-B — disk-space health view over bot_health host metrics.
-- Applied to Supabase project osxwkgmjwtdyvqwlfyre as migration h74_74b_v_disk_health.
-- Kept here as the repo record; additive and idempotent (create or replace).
--
-- Reads B9's DISCRETE column disk_free_bytes (statvfs f_bavail*f_frsize), NOT extra jsonb.
-- Discrete is indexable, needs no jsonb extraction, and matches `df -h` / the column comment.
-- (B9 = ops_item 33, migration b9_bot_health_host_metrics, deployed and live since
--  2026-09-30 03:18 UTC. 74-A telemetry is therefore already satisfied in this shape;
--  the work order's original extra->>'disk_free_gb' plan is superseded by discrete columns
--  per the 74-A collision note.)
--
-- Levels use only the latest reading. The fill rate is a secant over the available window
-- (<=90 min) and is trusted only at samples >= 45 (>=45 min at 1/min) so a short
-- post-restart window returns UNKNOWN, never CRITICAL — the H-70E "unknown-as-value" class.
--
-- Thresholds (74-B, derived from the systems themselves):
--   WARN     free < 5.0 GiB   -- the prune job's own floor; below it the box sheds data
--   CRITICAL free < 2.0 GiB   -- L2_RECORD_MIN_FREE_GB / L2_EVENT_MIN_FREE_GB; recorders pause
--   CRITICAL fill > 0.25 GiB/h over a trusted window  -- ~4x normal (~0.06), ~3x below the
--                                                         09-15/16 event average (>=0.75)
-- B9's single 2 GB warn is superseded by these; B9 had no fill-rate signal.

create or replace view public.v_disk_health as
with s as (
  select ts, disk_free_bytes::numeric / 1073741824.0 as free_gib
  from public.bot_health
  where service = 'bot'
    and ts > now() - interval '90 minutes'
    and disk_free_bytes is not null
),
w as (
  select
    (select free_gib from s order by ts desc limit 1) as free_now,
    (select free_gib from s order by ts asc  limit 1) as free_start,
    (select max(ts)  from s) as newest_ts,
    (select min(ts)  from s) as oldest_ts,
    (select count(*) from s) as samples
),
r as (
  select
    free_now, free_start, samples,
    case when samples >= 2 and newest_ts > oldest_ts
         then (free_start - free_now)
              / (extract(epoch from (newest_ts - oldest_ts)) / 3600.0)
         else null end as fill_per_h
  from w
)
select
  round(free_now, 2)   as free_gb_now,
  round(free_start, 2) as free_gb_window_start,
  samples,
  round(fill_per_h, 3) as fill_gb_per_h,
  (samples >= 45)      as rate_trusted,
  case
    when free_now is null then 'UNKNOWN'
    when free_now < 2.0 then 'CRITICAL'
    when samples >= 45 and fill_per_h > 0.25 then 'CRITICAL'
    when free_now < 5.0 then 'WARN'
    else 'OK'
  end as state,
  case
    when free_now is null then 'no disk reading in last 90m'
    when free_now < 2.0 then 'free < 2.0 GiB - L2 recorders paused, capture being lost'
    when samples >= 45 and fill_per_h > 0.25 then 'fill rate > 0.25 GiB/h over a trusted window'
    when free_now < 5.0 then 'free < 5.0 GiB - prune floor, system shedding data'
    else 'ok'
  end as reason
from r;

comment on view public.v_disk_health is
  'H-74/74-B: disk WARN/CRITICAL + fill-rate over bot_health.disk_free_bytes. Rate trusted only at samples>=45; UNKNOWN never escalates to CRITICAL. Read by the 74-C @DDHealthbot watcher.';
