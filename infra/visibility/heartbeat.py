#!/usr/bin/env python3
"""FF bot health heartbeat — writes one row per service to Supabase `bot_health`.

Rec #2 of the visibility pack: gives off-box sessions a read-only view of
"is the bot up / what version is deployed / is it flat / did a fix land."

Stdlib only (no pip installs). Read-only against the box; the ONLY write is the
INSERT to Supabase. Configure via env (see ff-heartbeat.service / EnvironmentFile):

  SB_URL             e.g. https://osxwkgmjwtdyvqwlfyre.supabase.co   (required)
  SB_KEY             Supabase service-role key — box env only, NEVER committed (required)
  BOT_DIR            default /home/tom/futuresforged-bot
  COPIER_STATE_URL   default http://localhost:7332/api/state
  FIXES_APPLIED      optional comma list, e.g. "R-09-FixA"
"""
import json, os, re, socket, subprocess, urllib.request
from datetime import datetime, timezone

SB_URL    = os.environ.get("SB_URL", "").rstrip("/")
SB_KEY    = os.environ.get("SB_KEY", "")
BOT_DIR   = os.environ.get("BOT_DIR", "/home/tom/futuresforged-bot")
STATE_URL = os.environ.get("COPIER_STATE_URL", "http://localhost:7332/api/state")
FIXES     = [s.strip() for s in os.environ.get("FIXES_APPLIED", "").split(",") if s.strip()]
PORTS     = {"bot": 7331, "copier": 7332}


def port_up(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pid_on_port(port):
    try:
        out = subprocess.run(["ss", "-ltnHp", f"sport = :{port}"],
                             capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"pid=(\d+)", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def git_sha():
    try:
        return subprocess.run(["git", "-C", BOT_DIR, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3).stdout.strip() or None
    except Exception:
        return None


def open_positions():
    """Best-effort open-contract count from the copier's own /api/state (token-less)."""
    try:
        with urllib.request.urlopen(STATE_URL, timeout=2) as r:
            d = json.loads(r.read().decode())
        pos = d.get("position") or {}
        c = pos.get("contracts")
        return int(c) if c else 0
    except Exception:
        return None


def insert(rows):
    if not (SB_URL and SB_KEY):
        raise SystemExit("SB_URL / SB_KEY not set — see ff-heartbeat.service EnvironmentFile")
    req = urllib.request.Request(
        SB_URL + "/rest/v1/bot_health",
        data=json.dumps(rows).encode(), method="POST",
        headers={"Content-Type": "application/json", "apikey": SB_KEY,
                 "Authorization": "Bearer " + SB_KEY, "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def main():
    ts, sha, pos = datetime.now(timezone.utc).isoformat(), git_sha(), open_positions()
    rows = []
    for name, port in PORTS.items():
        up = port_up(port)
        rows.append({
            "ts": ts, "service": name, "port": port, "up": up,
            "pid": pid_on_port(port) if up else None,
            "git_sha": sha,
            "open_positions": pos if name == "copier" else None,
            "fixes_applied": FIXES or None,
        })
    insert(rows)
    print(ts, {r["service"]: r["up"] for r in rows}, "sha", sha, "pos", pos)


if __name__ == "__main__":
    main()
