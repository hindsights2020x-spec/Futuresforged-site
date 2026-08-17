#!/usr/bin/env python3
"""FF bot health heartbeat — writes one row per service to Supabase `bot_health`.

Gives off-box sessions a read-only view of "is the bot up / what version is
deployed / is it flat". Pure stdlib (no pip, no venv needed) and read-only
against the box — the only write is the INSERT to Supabase.

ZERO new secrets: it reuses the Supabase service creds the box already has in
`.env` (the same ones retail_feed_push.py / retail_mirror.py use). Resolution
order for URL / KEY (first hit wins), from the real environment first, then the
bot `.env` file:
    URL : RETAIL_SUPABASE_URL | SUPABASE_URL | SB_URL
    KEY : RETAIL_SUPABASE_SERVICE_KEY | SUPABASE_SERVICE_KEY | SB_KEY

Run (cron, every minute):
    * * * * * cd /home/tom/futuresforged-bot && /usr/bin/python3 heartbeat.py >> /tmp/ff_heartbeat.log 2>&1
"""
import json, os, re, socket, subprocess, urllib.request
from datetime import datetime, timezone

BOT_DIR   = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
STATE_URL = os.environ.get("COPIER_STATE_URL", "http://localhost:7332/api/state")
FIXES     = [s.strip() for s in os.environ.get("FIXES_APPLIED", "").split(",") if s.strip()]
PORTS     = {"bot": 7331, "copier": 7332}


def _load_env_file(path):
    """Minimal .env parser (KEY=VALUE), stdlib only. Never raises."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _resolve_creds():
    envf = _load_env_file(os.path.join(BOT_DIR, ".env"))
    def pick(*names):
        for n in names:
            v = os.environ.get(n) or envf.get(n)
            if v:
                return v
        return ""
    url = pick("RETAIL_SUPABASE_URL", "SUPABASE_URL", "SB_URL").rstrip("/")
    key = pick("RETAIL_SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_KEY", "SB_KEY")
    return url, key


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
    # Prefer the deploy marker if the deploy writes one; fall back to git.
    try:
        with open(os.path.join(BOT_DIR, ".deployed_sha")) as f:
            s = f.read().strip()
            if s:
                return s[:12]
    except Exception:
        pass
    try:
        return subprocess.run(["git", "-C", BOT_DIR, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3).stdout.strip() or None
    except Exception:
        return None


def open_positions():
    try:
        with urllib.request.urlopen(STATE_URL, timeout=2) as r:
            d = json.loads(r.read().decode())
        pos = d.get("position") or {}
        c = pos.get("contracts")
        return int(c) if c else 0
    except Exception:
        return None


def insert(url, key, rows):
    req = urllib.request.Request(
        url + "/rest/v1/bot_health",
        data=json.dumps(rows).encode(), method="POST",
        headers={"Content-Type": "application/json", "apikey": key,
                 "Authorization": "Bearer " + key, "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def main():
    url, key = _resolve_creds()
    if not (url and key):
        raise SystemExit("no Supabase creds — set RETAIL_SUPABASE_URL/RETAIL_SUPABASE_SERVICE_KEY "
                         "(checked env + %s/.env)" % BOT_DIR)
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
    insert(url, key, rows)
    print(ts, {r["service"]: r["up"] for r in rows}, "sha", sha, "pos", pos)


if __name__ == "__main__":
    main()
