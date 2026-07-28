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

## Option B — rclone (Tom said Drive is connected via rclone)

rclone is **not** installed in the agent sandbox and there are no Drive credentials here, so the agent can't run
this. Run it wherever your rclone Drive remote is configured (assume the remote is named `gdrive` — check with
`rclone listremotes`). rclone renames a folder via a same-parent server-side move:

```bash
# folder B  -> ARCHIVED
rclone backend move gdrive: --drive-folder-id 199TgYmBbsNbRYBBzQr4HB7qmVOAIOJLs \
  -o name="Retail Launch (ARCHIVED stale 2026-05-30)"

# folder A  -> spec archive
rclone backend move gdrive: --drive-folder-id 1NydejrLg9Qc33gOCUPXyWlHRZNrG-mTb \
  -o name="Retail Launch (spec archive — code stale, see D:\\TOM)"
```

If your rclone build doesn't support the `backend move` rename op, the portable fallback is
`rclone moveto "gdrive:<oldpath>" "gdrive:<newpath>"` using the folders' full paths (this moves contents; the
folder-id rename above is preferred as it keeps the same folder object and its share links). Verify with
`rclone lsd gdrive:` (or `rclone lsf --dirs-only`) that both names updated and nothing was deleted.

*(R-08 §1's durable fix for the same root cause: `git init` the `D:\TOM\FuturesForged-Copier\` folder and
link it to the Vercel project so "which copy is live" can't recur.)*
