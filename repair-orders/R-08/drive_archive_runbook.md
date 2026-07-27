# R-08 §5 — Drive folder archive (manual — connector can't do it)

**Why manual:** the Google Drive connector available to this session is read/copy/create only — it has **no
rename/move/update tool** — so the agent cannot rename folders. These are the exact steps for Tom (or any
session with a full Drive tool) to execute. **Nothing is deleted.**

## The two folders (from R-08 §5)

| Folder | ID | Modified | Contents |
|---|---|---|---|
| **A** (fuller — spec archive) | `1NydejrLg9Qc33gOCUPXyWlHRZNrG-mTb` | 2026-06-26 | ~10 items: `copier_server.py` (stale 10,340 b), `launcher.py`, `build_exe.bat`, schema SQL, `static/`, 5 retail `.md` specs |
| **B** (sparse — strict subset of A) | `199TgYmBbsNbRYBBzQr4HB7qmVOAIOJLs` | 2026-05-30 | only `copier_server.py` + `launcher.py`, byte-identical to A's copies |

Both folders' code is **stale** relative to the live source at `D:\TOM\FuturesForged-Copier\`
(`copier_server.py` there is 24,008 b, 2026-07-01). A's `.md` specs are still useful history; its `.py` is not.

## Steps (rename only)

1. Open folder **B** — https://drive.google.com/drive/folders/199TgYmBbsNbRYBBzQr4HB7qmVOAIOJLs
   → rename to **`Retail Launch (ARCHIVED stale 2026-05-30)`**
2. Open folder **A** — https://drive.google.com/drive/folders/1NydejrLg9Qc33gOCUPXyWlHRZNrG-mTb
   → rename to **`Retail Launch (spec archive — code stale, see D:\TOM)`**
3. Do **not** delete either. Do not touch the `.md` specs.

**Done when:** neither folder's name reads as "current," so no future session treats their `.py` as canonical.

*(R-08 §1's durable fix for the same root cause: `git init` the `D:\TOM\FuturesForged-Copier\` folder and
link it to the Vercel project so "which copy is live" can't recur.)*
