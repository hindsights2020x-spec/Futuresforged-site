# R-08 §7.1 — Retail download fix + site 403 (runbook)

## UPDATE 2026-07-27 — actual hosting confirmed via GitHub (corrects R-08's Vercel assumption)

Read the real source (`hindsights2020x-spec/futuresforged` + `futuresforged-client`):
- **`futuresforged.com` is GitHub Pages, not Vercel** — repo `futuresforged`, a single static `index.html` +
  `CNAME`. It has **no download button and no `.exe`**. So the download 404 is because the file + link were
  never added to this repo — fixable here directly (see §1A).
- **`app.futuresforged.com`** = repo `futuresforged-client` (single-file app; GitHub Pages workflow + a
  `vercel.json`; live source currently `ffpreview.vercel.app` in Tom's personal Vercel, mid-canonicalization).
- **Deployment Protection** can't be read from the repo — still a Vercel-dashboard check (§0). The earlier
  uniform 403 was the agent's sandbox egress, **not** real site state (a GitHub Pages missing file returns
  404, which is exactly what the real apex does for the absent `.exe`).

**Why the original runbook said "Vercel":** R-08 assumed the whole line was Vercel. The apex is Pages; only the
app's canonical deploy is Vercel (personal account, MCP can't see it — no teams, 403 on lookup).

### §1A. Fix the download on the GitHub Pages apex (doable in-repo)
1. **Host the binary.** Either commit `FuturesForged.exe` into the `futuresforged` repo (GitHub Pages serves
   it at `futuresforged.com/FuturesForged.exe`; note GitHub's 100 MB/file limit — the 14.7 MB exe is fine),
   **or** host it on RO#07 R2 / `get.futuresforged.com` (§1 below) and link out to that. The binary lives at
   `D:\TOM\FuturesForged-Copier\dist\FuturesForged.exe` — a human/box must supply it; the agent can't reach it.
2. **Add a download CTA** to `futuresforged/index.html` (today its CTAs only go to `#pricing` / Stripe). Insert
   near the hero:
   ```html
   <a class="btn btn-primary" href="https://get.futuresforged.com/FuturesForged.exe" download>
     Download for Windows
   </a>
   ```
   (or `href="/FuturesForged.exe"` if hosting in-repo). Push to the Pages branch; the workflow redeploys.
3. Verify logged-out: `curl -IL https://futuresforged.com/FuturesForged.exe` → `200` +
   `content-type: application/octet-stream`.

> The agent did **not** make this edit — it changes the live customer marketing site and the host (in-repo vs
> R2) is Tom's call. Say the word and I'll open a PR against `futuresforged` with the button wired to whichever
> host you pick.

---

## (original) Vercel-account steps — still relevant for the app + protection

**Why runbook, not executed:** this session's Vercel MCP token exposes **no teams** and returns
`403 Forbidden` on the FuturesForged deployment lookups — it does **not** have access to the FF Vercel
projects. So the agent can't inspect or change them. Run these from Tom's own Vercel account/CLI.

## §0. First: is Deployment Protection blocking customers? (check this before anything else)

Between the R-08 audit (Jul 1) and 2026-07-27, the observed responses changed:
`futuresforged.com/FuturesForged.exe` **404 → 403**, and `app.futuresforged.com` **200 → 403**. Everything now
returns a uniform 403 (even from Vercel's own authenticated fetch). That pattern is consistent with **Vercel
Deployment Protection** (Vercel Authentication / password) having been turned on across the project.

- Vercel dashboard → **futuresforged** project → **Settings → Deployment Protection**.
- If **Vercel Authentication** is ON for production, `app.futuresforged.com` is gated for real customers too —
  almost certainly **not** intended for a customer-facing app. Turn it off for production (or scope it to
  preview deployments only), then re-test `https://app.futuresforged.com/` in a logged-out browser.
- Confirm the production deployment for `app.` is **Ready** (not errored/rolled back).

## §1. Fix the broken download

R-08: `https://futuresforged.com/FuturesForged.exe` is the advertised path but 404s (now 403s). Root cause per
R-08 §4: **RO#07 was never executed** — `get.futuresforged.com` is NXDOMAIN, so there is no host serving the
binary. Pick ONE:

**Option A — serve it off the apex (fastest).** Put the current built binary
(`D:\TOM\FuturesForged-Copier\dist\FuturesForged.exe`, 14.7 MB) where the apex deployment serves static files
(e.g. `public/FuturesForged.exe` in the marketing project) and redeploy. Verify:
`curl -IL https://futuresforged.com/FuturesForged.exe` → `200` + `content-type: application/octet-stream`.
Caveat: large binaries in a Vercel static deploy — confirm it's within limits; otherwise use Option B.

**Option B — execute RO#07 (R2 + `get.` subdomain), the intended design.** Create the `get.futuresforged.com`
host (Cloudflare R2 or similar), upload the binary, DNS the subdomain, then point the marketing "Download"
button at `https://get.futuresforged.com/FuturesForged.exe`. Verify the subdomain resolves and the file
downloads logged-out.

**Do not ship to customers until** `curl -IL <download-url>` returns `200` from a logged-out client, **and**
the binary served is the rebuilt one with NT8 routing/account-linking (R-08 §7.2 — gated on the NT8 micro-test).

## §2. If you want the agent to do this next time

Attach a Vercel token that has access to the FF team/projects (or run from the local folder with `vercel` CLI
linked). Then a session could inspect `list_projects`/`list_deployments`, read Deployment Protection, and add
the static route or redirect directly.
