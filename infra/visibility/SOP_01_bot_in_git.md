# SOP 01 — Put the bot in git & deploy FROM git (Rec #1)

**Why:** the live `bot_engine.py` / `copier_server.py` exist only on the box, so every off-box session
works against Drive/Git *snapshots* and stalls at "pending on-box." Versioning the bot turns fixes into
real diffs/PRs, gives history + one-command rollback, and ends snapshot-vs-live drift.

**Run on the ff-bot box.** ~15 min, one-time setup + a deploy habit.

## 1. Create the private repo
Create a **private** GitHub repo `futuresforged-bot` (empty). Do **not** make it public — it's a live
trading engine.

## 2. Import the current live tree (secrets excluded)
```bash
cd /home/tom/futuresforged-bot
cp /path/to/repo/infra/visibility/bot.gitignore.sample .gitignore   # excludes *.env, keys, logs, data, .bak
git init && git add -A
git status                      # <-- REVIEW: confirm NO secrets/keys/.env are staged
git commit -m "Import live ff-bot tree (baseline)"
git branch -M main
git remote add origin git@github.com:<org>/futuresforged-bot.git
git push -u origin main
```
If anything sensitive is staged, add it to `.gitignore` and `git rm --cached <file>` before committing.

## 3. Deploy FROM git from now on
Put `deploy.sh` (this folder) in the bot dir and use it for every change:
```bash
cp /path/to/repo/infra/visibility/deploy.sh /home/tom/futuresforged-bot/ && chmod +x deploy.sh
sudo BRANCH=main ./deploy.sh <copier-unit> <bot-unit>   # pull -> backup -> py_compile -> restart -> stamp sha
```
`deploy.sh` refuses to restart if `py_compile` fails, tars a pre-deploy backup, and (if the heartbeat is
installed) publishes the new `git_sha` off-box immediately.

## 4. Payoff for future work
- Off-box/agent sessions read the **real** files → e.g. R-09 Fix A becomes a reviewed PR, not a snapshot guess.
- `git log` / `git revert` for audit + rollback; CI can `py_compile`/lint on push.
- The health heartbeat (SOP 02) reports the deployed `git_sha`, so you can confirm off-box exactly what's running.

## Guardrails
- **Private repo only.** Never commit `*.env`, keys, tokens, or account data — the `.gitignore` blocks the
  common ones; still eyeball `git status` on the first commit.
- Keep `deploy.sh`'s pre-deploy tar backups until a deploy is confirmed healthy.
