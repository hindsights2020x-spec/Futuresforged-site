# R-08 — Retail Tree Map + Gap Audit — COMPLETION STATUS

**Date:** 2026-07-27 **By:** Claude Code (off-box — connector access only: Supabase, Vercel, Google Drive, GitHub)
**Companion to:** `R-08-tree-map.md` (`2026-07-01`, Drive folder `2026-06-30 R-08 Retail Tree Map and Gap Audit`)

---

## Scope note (read first)

R-08 is an **audit** ("read/report only — no deploys, no Drive mutations"). Its §7 actions are mostly
Tom-gated (Stripe, VPS, NT8 micro-test), on-box, or need the local `D:\TOM\FuturesForged-Copier\` folder,
none of which this session can reach. This completion does three things:

1. **Re-verifies** R-08's findings as of 2026-07-27 (it was ~3.5 weeks old).
2. **Executes** the reachable actions Tom approved — one succeeded, two were blocked by connector limits.
3. **Packages** ready-to-run runbooks for everything that must be done on-box / by Tom.

**Verification reachability from this session:**
- ✅ **Supabase** (`osxwkgmjwtdyvqwlfyre`) — authenticated MCP, fully usable. This is the only surface I could
  verify authoritatively.
- ⚠️ **Live HTTP surfaces** (`futuresforged.com`, `app.futuresforged.com`, `get.futuresforged.com`) —
  **inconclusive**. Every URL returns a uniform `403` through both the sandbox egress proxy **and** Vercel's
  own authenticated fetch. A host R-08 found as **NXDOMAIN** (`get.`) returning the *same* 403 proves the 403
  is not real site state. Do **not** read these 403s as "the app is down."
- ⚠️ **Vercel MCP** — connected account exposes **no teams** and returns `403 Forbidden` when checking the
  FuturesForged deployments, i.e. this token does **not** have access to the FF Vercel projects (same gap
  R-08 noted: "no team scope exposed to the API").
- ⚠️ **Google Drive MCP** — read/copy/create only. **No rename/move/update tool**, so folder archiving
  (§5) cannot be executed from here.

---

## Actions Tom approved — outcomes

| Action | Outcome |
|---|---|
| **Supabase: signal-route smoke test** | ✅ **DONE** — write path + constraints + RLS + Realtime validated; test row inserted (test account, safe `pending`/`none` state) and deleted; table back to 0 rows. See `supabase_signal_route_smoke_test.sql`. |
| **Vercel: verify download/site state** | ⛔ **BLOCKED** — this session's Vercel token has no access to the FF projects (no teams; 403 on deployment lookup). Runbook to do it from Tom's account: `vercel_download_fix_runbook.md`. |
| **Drive: archive stale folders** | ⛔ **BLOCKED** — Drive connector has no rename/move tool. Exact manual steps: `drive_archive_runbook.md`. |

---

## Refreshed status of every R-08 surface (2026-07-27)

| Surface | R-08 (Jul 1) | Now (Jul 27) | Source |
|---|---|---|---|
| Web client dashboard (`app.futuresforged.com`) | ✅ Live (200) | ⚠️ Unverifiable from here (uniform 403 — see scope note) | — |
| Marketing site (`futuresforged.com`) | ✅ Live (200) | ⚠️ Unverifiable from here | — |
| **Retail download** (`futuresforged.com/FuturesForged.exe`) | ❌ 404 | ❌ Still broken (403 now, not 404 — response changed, still not downloadable) | egress + Vercel fetch |
| Customer portal / pricing (`/portal`, `/pricing`) | ⚠️ 404 | ⚠️ Unverifiable from here | — |
| **`get.futuresforged.com`** (RO#07 host) | ❌ NXDOMAIN | ⚠️ Vercel fetch could not create a share link for it → still not a reachable Vercel deployment | Vercel fetch |
| **Supabase backend** | ✅ Healthy | ✅ Healthy | Supabase MCP |
| **`signal_routes` rows** | **0** (path never exercised) | **Still 0** — DB write path now proven (smoke test), but no real client route has ever persisted | Supabase MCP |
| `signals` rows | 83 | **~117 (max id 128)** — bot is actively publishing | Supabase MCP |
| `customers` / `subscriptions` | 3 / 1 | **3 / 1** (unchanged; 1 of the 3 is the `+test1` test account) | Supabase MCP |
| Stripe | ⛔ Tom-gated | ⛔ Unchanged — `subscriptions` still 1 row | Supabase MCP |

**New observation:** the download URL moved from **404 → 403** and R-08's live `app.` moved from **200 → 403**
between Jul 1 and Jul 27. That *pattern* (everything now 403) is consistent with **Vercel Deployment
Protection having been enabled** on the project since the audit — but I cannot confirm it from here (my token
can't see the project). If Deployment Protection is on, it may be blocking legitimate customer access to
`app.futuresforged.com`; **Tom should check the Vercel dashboard** (see `vercel_download_fix_runbook.md` §0).

---

## Signal-route smoke test — detail (the one action executed)

**Goal (R-08 §6):** the accept/deny → route → exec path "has never actually run end to end in prod data."

**What was validated (DB side, authoritatively):**
- `signal_routes` schema: `id` (IDENTITY ALWAYS), `signal_id`→`signals(id)`, `customer_id`→`auth.users(id)`,
  `decision` CHECK ∈ {`pending`,`accepted`,`denied`}, `exec_status` CHECK ∈ {`none`,`sent`,`filled`,`rejected`},
  `UNIQUE(signal_id, customer_id)`. (Note: R-08 said "accept/deny"; the actual enum values are
  `accepted`/`denied`.)
- RLS: `own routes - select|update|insert`, all keyed on `auth.uid() = customer_id`. Correct for per-customer isolation.
- Realtime: both `signals` and `signal_routes` are in the `supabase_realtime` publication. ✅
- A synthetic route (signal 128, test account `tomolly88+test1@gmail.com`, `pending`/`none`) inserted cleanly,
  then deleted. Table returned to **0 rows, max_id 0**. No residue.

**What is still NOT proven (needs on-box / a live client):**
- A subscribed client actually **receiving** the Realtime insert.
- The `decision='accepted'` → `exec_status='sent'` → `filled` transition driving a real (or SIM) copier order.
  This was **deliberately not tested** — flipping a live route to `accepted`/`sent` could make a live copier
  place an order. That transition must be exercised on-box with the copier in SIM. See the runbook comment in
  `supabase_signal_route_smoke_test.sql`.

---

## What's left to close R-08 (owner-tagged)

| # | Item | Owner | Artifact |
|---|---|---|---|
| 1 | Fix the retail download (host decision: execute RO#07 `get.` R2, or route `futuresforged.com/FuturesForged.exe` to the binary) | Tom + Vercel | `vercel_download_fix_runbook.md` |
| 1b | Confirm whether Vercel Deployment Protection is blocking `app.futuresforged.com` for customers | Tom | `vercel_download_fix_runbook.md` §0 |
| 2 | Rebuild + NT8 micro-test the copier, then re-upload the exe once (1) has a home | Tom (box + NT8) | R-08 §7.2 / `FuturesForged-HANDOFF.md` |
| 3 | Prove signal route **client Realtime + copier exec** E2E (DB side done here) | On-box (copier in SIM) | `supabase_signal_route_smoke_test.sql` §"on-box E2E" |
| 4 | Archive the two stale "Retail Launch" Drive folders | Tom (manual) | `drive_archive_runbook.md` |
| 5 | `git init` the copier folder + link Vercel (end source-of-truth drift) | Tom (local) | R-08 §1 |
| 6 | Confirm/deny Stripe go-live | Tom | R-08 §7.6 |

---

## ADDENDUM 2026-07-27 — Vercel action unblocked via GitHub (source repos read)

Tom pointed out the sites are reachable via GitHub. Added `hindsights2020x-spec/futuresforged` and
`futuresforged-client` to the session and read the actual source. This **corrects R-08's "everything is
Vercel" premise**:

- **`futuresforged.com` (apex marketing) is GitHub Pages, not Vercel.** Repo `futuresforged` = a single static
  `index.html` + `CNAME futuresforged.com`. It contains **no download link and no `.exe`** — so the download
  404 is simply because the binary and a download button were never added here (independent of RO#07). Stripe
  CTAs are still `https://buy.stripe.com/YOUR_STARTER_LINK` / `YOUR_PRO_LINK` **placeholders** → Stripe still
  not live (confirms R-08 §7.6 from source, not just the 1-row table).
- **`app.futuresforged.com` (client app):** repo `futuresforged-client` = single-file static app
  (`index.html` ~111 KB + `studio.html`), `CNAME app.futuresforged.com`, a GitHub Pages deploy workflow
  (`.github/workflows/pages.yml`, on push to `master`) **and** a `vercel.json`. Its README says the **live**
  source is currently `ffpreview.vercel.app` and this repo is a *recovery backstop* "NOT yet the Vercel-linked
  canonical repo" — the Vercel project "lives in Tom's personal Vercel or the Cowork sandbox" (the MCP account
  "has no teams and cannot see it"). So the transition Vercel→GitHub-Pages is mid-flight.
- **`/portal` and `/pricing` 404 by design** — the client is a single-file app with "no multi-page tree," per
  its README. R-08's "unverified portal/pricing" flags are explained: those routes don't exist, they aren't missing pages.
- **What GitHub still can't tell us:** whether Vercel **Deployment Protection** is gating `app.` — that's a
  dashboard setting in Tom's personal Vercel account, not in the repo. Still a Tom check (runbook §0). The
  uniform 403 I saw earlier was my sandbox egress, not real site state.

**Net for the download fix:** it's now concrete — add a download button to the GitHub Pages apex repo pointing
at a hosted binary, and host the binary (RO#07 R2 / `get.futuresforged.com`, or in-repo). See the updated
`vercel_download_fix_runbook.md`. The binary itself (`D:\TOM\...\dist\FuturesForged.exe`, 14.7 MB) is still
local-only, so the host step needs Tom or the box.

Drive archive: rclone isn't installed in this sandbox and I have no Drive credentials here, so I still can't
execute it — `drive_archive_runbook.md` now includes the exact rclone commands for Tom's configured remote.

---

*No orders were placed. No Supabase rows persist from this session. No Drive or Vercel/GitHub-Pages site state
was mutated. Operator bot files were not touched. The two added repos were read-only.*
