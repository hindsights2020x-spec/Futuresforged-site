#!/usr/bin/env bash
# Rec #1 — deploy the FF bot FROM GIT: pull -> backup -> py_compile -> restart -> stamp sha.
# Makes the live tree == a known git sha, killing the "Drive snapshot vs live file" drift.
#
# Usage:  sudo BOT_DIR=/home/tom/futuresforged-bot BRANCH=main ./deploy.sh <unit1> [unit2 ...]
#   e.g.  sudo ./deploy.sh ff-copier ff-bot
set -euo pipefail
BOT_DIR="${BOT_DIR:-/home/tom/futuresforged-bot}"
BRANCH="${BRANCH:-main}"
UNITS=("$@")
[ ${#UNITS[@]} -gt 0 ] || { echo "pass the systemd unit(s) to restart, e.g. ./deploy.sh ff-copier ff-bot"; exit 2; }

cd "$BOT_DIR"

echo "== backup (pre-deploy safety) =="
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="/home/tom/ff-bot-backup-$STAMP.tgz"
tar czf "$BK" -C "$BOT_DIR" . --exclude='.git' --exclude='__pycache__'
echo "  $BK"

echo "== pull =="
git fetch --all --prune
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
SHA="$(git rev-parse --short HEAD)"

echo "== compile (fail before restart if syntax is broken) =="
python3 -m py_compile ./*.py

echo "== restart =="
for u in "${UNITS[@]}"; do sudo systemctl restart "$u"; done
sleep 2
for u in "${UNITS[@]}"; do
  if systemctl is-active --quiet "$u"; then echo "  $u active"; else echo "  $u FAILED — roll back from $BK"; exit 1; fi
done

echo "== deployed sha $SHA =="
# push the new sha to off-box visibility immediately, if the heartbeat is installed
if [ -x "$BOT_DIR/heartbeat.py" ]; then
  [ -f /etc/ff/heartbeat.env ] && set -a && . /etc/ff/heartbeat.env && set +a
  python3 "$BOT_DIR/heartbeat.py" || true
fi
