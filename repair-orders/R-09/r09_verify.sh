#!/usr/bin/env bash
# R-09 on-box verification (READ-ONLY) — run this in a Cowork / Claude Code session
# ON THE ff-bot box (the machine with /home/tom/futuresforged-bot/).
#
# It does NOT modify any file and does NOT place any order. It discovers exactly
# where the manual-order sizing happens so Fix A (bot_engine_manual_bypass.md) can
# be applied in the right place, and prints the copy/paste live before/after test.
#
# Usage:  bash r09_verify.sh [BOT_DIR]
set -uo pipefail
BOT_DIR="${1:-/home/tom/futuresforged-bot}"
say(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

say "0. Bot dir"
if [ ! -d "$BOT_DIR" ]; then echo "NOT FOUND: $BOT_DIR — pass the real path as arg 1"; exit 1; fi
ls -la "$BOT_DIR"/*.py 2>/dev/null | sed 's/^/  /'

say "1. Which process owns :7331 (bot) and :7332 (copier)?"
if command -v ss >/dev/null; then
  sudo ss -ltnp 2>/dev/null | grep -E ':7331|:7332' || ss -ltnp 2>/dev/null | grep -E ':7331|:7332' || echo "  (need sudo for PID mapping)"
else
  sudo netstat -ltnp 2>/dev/null | grep -E ':7331|:7332'
fi

say "2. Where is /api/place_order defined?"
grep -rn "place_order" "$BOT_DIR"/*.py | sed 's/^/  /'

say "3. Every get_contracts() call site (does the copier SIZE or RELAY?)"
grep -rn "get_contracts(" "$BOT_DIR"/*.py | sed 's/^/  /'
echo "  -- enforce_limits sites (do NOT touch these) --"
grep -rn "enforce_limits(" "$BOT_DIR"/*.py | sed 's/^/  /'

say "4. Payload keys the server reads (expect 'contracts'; check for 'strategy'/'manual')"
grep -rEn "get\(['\"](contracts|qty|strategy|manual|instrument)['\"]" "$BOT_DIR"/*.py | sed 's/^/  /'

say "5. If the copier RELAYS to the bot, confirm it forwards the payload unchanged"
grep -rnE "requests\.post|json=|:7331|forward|relay" "$BOT_DIR"/*.py | grep -i "place\|order\|7331\|relay\|forward" | sed 's/^/  /'

say "VERDICT / WHERE TO APPLY FIX A"
cat <<'EOF'
  - If get_contracts() appears INSIDE the /api/place_order handler's file (step 2 == step 3
    file), apply Fix A there: branch before get_contracts() on
    order.get("manual") or order.get("strategy")=="MANUAL"  ->  use raw int(order["contracts"]), run_c=0.
  - If the copier only RELAYS (step 5 shows it POSTs to :7331) and sizing is in bot_engine.py
    (~1895-2020), apply Fix A at that bot-side site and make sure the copier forwards
    'manual' + 'contracts' untouched.
  - See bot_engine_manual_bypass.md for the exact snippet + guardrails (do not touch signal
    sizing or enforce_limits; keep a .bak).
EOF

say "LIVE BEFORE/AFTER TEST (run MANUALLY — use a SIM/EVAL account, not the funded one)"
cat <<'EOF'
  # BEFORE the fix this should size to 2 MNQ; AFTER Fix A it should be exactly 1:
  curl -s -X POST http://localhost:7332/api/place_order \
    -H 'Content-Type: application/json' \
    -d '{"side":"BUY","direction":"BUY","manual":true,"instrument":"MNQ","contracts":1,"order_type":"MKT","strategy":"MANUAL"}'
  curl -s http://localhost:7332/api/state | python3 -m json.tool | grep -iA3 'position\|contracts\|qty'
  # Then a normal SIGNAL trade must still size TP + runner (signal path unchanged).
EOF
echo
echo "Done — paste this output back to close R-09 Issue 1."
