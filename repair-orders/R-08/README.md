# R-08 — Retail Tree Map + Gap Audit (completion pack)

Completion pack for repair order **R-08** (`R-08-tree-map.md`, `2026-07-01`, from the Cowork audit session).
Prepared 2026-07-27.

> **Environment note:** produced off-box with connector access only (Supabase, Vercel, Google Drive, GitHub) —
> no reach to the ff-bot box, the NT8 machine, or the local `D:\TOM\FuturesForged-Copier\` folder. R-08 is an
> **audit**, so "completion" here = re-verify its findings, execute the reachable actions, and package
> ready-to-run runbooks for the rest.

## Contents
| File | What it is |
|---|---|
| `R-08_STATUS.md` | The completion status — refreshed surface table (Jul 27 vs Jul 1), outcomes of the 3 approved actions, and the owner-tagged "what's left" list. **Start here.** |
| `supabase_signal_route_smoke_test.sql` | The reproducible signal-route smoke test that was **executed** (write path + constraints + RLS + Realtime validated, cleaned up to 0 rows) + the on-box E2E steps not run here. |
| `vercel_download_fix_runbook.md` | Runbook to fix the broken retail download and to check whether Deployment Protection is now blocking `app.futuresforged.com`. Not executed — this session's Vercel token has no access to the FF projects. |
| `drive_archive_runbook.md` | Manual steps to archive the two stale "Retail Launch" Drive folders (§5). Not executed — the Drive connector has no rename/move tool. |

## Actions Tom approved — outcomes
- ✅ **Supabase signal-route smoke test** — done. DB-side accept/deny→route path proven; `signal_routes` back
  to 0 rows. Client-Realtime + copier-exec E2E still needs an on-box subscriber.
- ⛔ **Vercel download/site verification** — blocked: token lacks access to the FF Vercel projects. Runbook provided.
- ⛔ **Drive folder archive** — blocked: connector can't rename. Manual steps provided.

## Headline (refreshed)
- **Download still broken** (`futuresforged.com/FuturesForged.exe`): 404 on Jul 1 → 403 now. Root cause
  unchanged — RO#07 (`get.futuresforged.com`) was never executed, so nothing hosts the binary.
- **New flag:** every FF URL now returns 403 (was 200 for `app.`), consistent with Vercel Deployment
  Protection having been enabled since the audit — **verify it isn't blocking real customers.**
- **`signal_routes` still 0 rows**; `signals` grew 83 → ~117 (bot actively publishing). Backend healthy.
- Stripe still Tom-gated (1 subscription row, unchanged).

## Status
- Re-verification (Supabase): **complete.**
- Reachable action executed: **1 of 3** (2 blocked by connector limits, both with runbooks).
- Everything else: **on-box / Tom-gated**, itemized in `R-08_STATUS.md`.
