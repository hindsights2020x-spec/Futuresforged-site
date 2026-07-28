-- R-08 · Signal-route smoke test (Supabase project osxwkgmjwtdyvqwlfyre)
-- Purpose: prove the accept/deny -> route -> exec write path that R-08 flagged as
--          "never exercised" (signal_routes had 0 rows).
-- Ran off-box 2026-07-27 via the Supabase MCP (service role, RLS bypassed).
-- SAFE: uses the +test1 account and the pending/none initial state, so no live
--       copier can act on it. Committed insert+delete emits real Realtime events,
--       then cleans up to 0 rows.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- 0. Schema / policy inspection (read-only) — what the smoke test relies on
-- ─────────────────────────────────────────────────────────────────────────────
-- signal_routes columns:
--   id           bigint  IDENTITY ALWAYS  (do NOT supply)
--   signal_id    bigint  FK -> signals(id)      ON DELETE CASCADE
--   customer_id  uuid    FK -> auth.users(id)   ON DELETE CASCADE
--   decision     text    CHECK in ('pending','accepted','denied')   default 'pending'
--   exec_status  text    CHECK in ('none','sent','filled','rejected') default 'none'
--   created_at   timestamptz default now()
--   UNIQUE (signal_id, customer_id)
-- RLS policies (all keyed on auth.uid() = customer_id):
--   "own routes - select" (SELECT), "own routes - update" (UPDATE), "own routes - write" (INSERT)
-- Realtime: signals AND signal_routes are both in publication supabase_realtime.

-- Re-run these to confirm before/after:
select count(*) as routes_before from signal_routes;                                  -- expect 0
select (select id from signals order by id desc limit 1) as latest_signal_id;         -- e.g. 128
select id, email from auth.users where email = 'tomolly88+test1@gmail.com';           -- test account

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Insert a synthetic route in the SAFE state (no exec semantics)
-- ─────────────────────────────────────────────────────────────────────────────
-- Replace :sig with latest_signal_id and :test_uid with the +test1 auth id.
insert into signal_routes (signal_id, customer_id, decision, exec_status)
values (128, '2fbb3172-99a5-4efb-9b11-a3ce14841d39', 'pending', 'none')
returning id, signal_id, customer_id, decision, exec_status, created_at;
-- RESULT 2026-07-27: id=2, pending/none, all constraints satisfied. ✅

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Clean up (leave prod at 0 rows)
-- ─────────────────────────────────────────────────────────────────────────────
delete from signal_routes where id = 2;                 -- use the id returned above
select count(*) as routes_after, coalesce(max(id),0) max_id from signal_routes;       -- RESULT: 0, 0 ✅
-- NB: a data-modifying CTE's delete is NOT visible to a sibling count() in the same
-- statement (MVCC) — verify with a SEPARATE select, as above.

-- ─────────────────────────────────────────────────────────────────────────────
-- on-box E2E (NOT run here — do this with the copier in SIM, never live)
-- ─────────────────────────────────────────────────────────────────────────────
-- The DB write path is proven. The remaining unknowns need a live subscriber:
--   a) client dashboard subscribed to signal_routes Realtime actually RECEIVES the insert;
--   b) decision 'accepted' -> exec_status 'sent' -> 'filled' drives a copier order.
-- Exercise on-box with the copier forced to SIM:
--   1. Insert a pending route for the +test1 account (step 1 above).
--   2. In the test client, confirm the route appears via Realtime.
--   3. Accept it in the UI (decision -> 'accepted'); confirm copier picks it up and
--      exec_status advances to 'sent' then 'filled' against a SIM account.
--   4. Delete the row. Confirm 0 rows.
-- Do NOT run step 3 against a live/funded account.
