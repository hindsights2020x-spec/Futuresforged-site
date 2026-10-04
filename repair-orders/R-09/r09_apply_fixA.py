#!/usr/bin/env python3
"""R-09 Fix A patcher — manual-order sizing bypass.

⛔ DO NOT USE (2026-07-19). On-box review found manual orders go through
copier_engine.py /api/place_order -> copy_trade() and NEVER call get_contracts().
The only `instr, pv, tp_c, run_c = get_contracts(` sites are bot_engine.py:1903/1976
in the AUTONOMOUS SIGNAL LOOP — patching them injects an `order` NameError that breaks
live signal trading. The real fix belongs in copy_trade(). Kept for history only.
See COWORK_HANDOFF_42_fixA.md (STOP banner).
"""
_DEPRECATED_DOC = """R-09 Fix A patcher — manual-order sizing bypass.

Idempotent, DRY-RUN by default, writes a timestamped .bak before any change.
Inserts a bypass immediately before a `instr, pv, tp_c, run_c = get_contracts(...)`
call site so manual orders execute the exact `contracts` count with no runner leg.

Usage:
  # 1) dry-run against the handler r09_verify.sh identified:
  python3 r09_apply_fixA.py --file /home/tom/futuresforged-bot/bot_engine.py
  # if it reports multiple call sites, pick the MANUAL/place_order one:
  python3 r09_apply_fixA.py --file .../bot_engine.py --site 2
  # 2) when the preview looks right, write it:
  python3 r09_apply_fixA.py --file .../bot_engine.py --site 2 --apply

  # if your payload dict isn't named `order`, pass it (e.g. req/data/body/payload):
  python3 r09_apply_fixA.py --file .../copier_server.py --order-var data --apply
"""
import argparse, re, sys, shutil, time

MARKER = "R-09 manual bypass"

ap = argparse.ArgumentParser()
ap.add_argument("--file", required=True, help="handler file that calls get_contracts() for manual orders")
ap.add_argument("--order-var", default="order", help="incoming payload dict variable name (default: order)")
ap.add_argument("--site", type=int, default=None, help="1-based index when there are multiple call sites")
ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run preview only)")
a = ap.parse_args()

src = open(a.file).read().splitlines(keepends=True)
if MARKER in "".join(src):
    print("Already patched (marker present) — no change made."); sys.exit(0)

pat = re.compile(r'^(\s*)instr\s*,\s*pv\s*,\s*tp_c\s*,\s*run_c\s*=\s*get_contracts\(')
hits = [i for i, l in enumerate(src) if pat.match(l)]
if not hits:
    print("No `instr, pv, tp_c, run_c = get_contracts(` line found in this file.")
    print("Confirm the LHS names / file with r09_verify.sh, or apply Fix A by hand")
    print("(see bot_engine_manual_bypass.md).")
    sys.exit(2)
if len(hits) > 1 and a.site is None:
    print(f"{len(hits)} get_contracts() call sites — re-run with --site N for the MANUAL/place_order one:")
    for n, i in enumerate(hits, 1):
        print(f"  {n}: line {i+1}: {src[i].rstrip()}")
    sys.exit(3)

i = hits[(a.site - 1) if a.site else 0]
ind = pat.match(src[i]).group(1)
ov = a.order_var
block = (
    f'{ind}if {ov}.get("manual") or {ov}.get("strategy") == "MANUAL":\n'
    f'{ind}    # {MARKER} — execute exact qty, no runner leg (R-09 Issue 1)\n'
    f'{ind}    instr = {ov}.get("instrument", "MNQ")\n'
    f'{ind}    pv    = MNQ_PV if instr == "MNQ" else MES_PV\n'
    f'{ind}    tp_c  = max(1, int({ov}.get("contracts", 1)))\n'
    f'{ind}    run_c = 0\n'
    f'{ind}else:\n'
    f'{ind}    ' + src[i][len(ind):]        # original assignment, re-indented under else
)
new = src[:i] + [block] + src[i + 1:]

print("---- preview (context) ----")
print("".join(new[max(0, i - 3):i + 10]), end="")
print("---------------------------")
if not a.apply:
    print("[dry-run] looks right? re-run with --apply to write (a .bak is saved first)."); sys.exit(0)

bak = a.file + f".bak_R09_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(a.file, bak)
open(a.file, "w").write("".join(new))
print(f"Applied. Backup: {bak}")
print("Now: python3 -m py_compile", a.file, "&& restart the service, then run the live test.")
