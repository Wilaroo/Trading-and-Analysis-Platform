#!/usr/bin/env python3
"""Generate scripts/patch_a6_daily_autoexec.py — wires _scan_daily_setups swing/
multi_day/position alerts into the auto-executor WITHOUT the intraday tape gate.

Single-file anchored patch on services/enhanced_scanner.py (9.7k lines). Whole-file
PRE-SHA guard + one function-sized anchored chunk (old _scan_daily_setups -> new
[helper method + _scan_daily_setups with two call-site hand-offs]). Pinned to the
live DGX function bytes (OLD_B64 from extract_func_generic, func sha 3cbc26...).
"""
import base64
import hashlib

PRE_FILE_SHA = "8061578717d37e5964b5d73920ea660c52afed1cc7f9302586f5a83b5a7a45d1"
PRE_FUNC_SHA = "3cbc263a4c33576aac918901b64ea1f63d395b901e06306e740327e8dcdb9a81"

old_func = base64.b64decode(open("/tmp/a6_old_b64.txt").read().strip()).decode("utf-8")
assert hashlib.sha256(old_func.encode()).hexdigest() == PRE_FUNC_SHA, "OLD_B64 func sha mismatch"

HELPER = '''    async def _maybe_auto_execute_daily(self, alert):
        """v19.34.287b — auto-execute longer-horizon (swing / multi_day / position)
        setups produced by _scan_daily_setups. Tape confirmation is an INTRADAY
        microstructure gate and does NOT apply to these holds (operator 2026-06-22);
        horizon is separated by scan path, so the intraday tape requirement in
        _scan_symbol is left untouched. Mirrors the intraday EV quality gate
        (priority HIGH/CRITICAL + _passes_ev_quality_gate) MINUS tape + intraday-stale.
        The bot's _evaluate_opportunity (confidence gate + max_open_positions +
        sizing) stays the FINAL authority — this only lets the alert REACH it.
        Runs in the same scan tick the alert was detected (bars include today's live
        bar), so eligibility is evaluated on realtime data. Never raises."""
        try:
            if not self._auto_execute_enabled:
                return
            eligible = (
                getattr(alert, "priority", None) is not None
                and alert.priority.value in (
                    AlertPriority.CRITICAL.value, AlertPriority.HIGH.value)
                and self._passes_ev_quality_gate(alert)
            )
            alert.auto_execute_eligible = eligible
            if eligible:
                await self._auto_execute_alert(alert)
        except Exception:
            pass

'''

# two distinct call sites (built-in checks loop = 32-space indent; DAILY_DETECTORS
# loop = 36-space indent). Append the hand-off after each.
SITE1_OLD = (
    "                                await self._process_new_alert(alert)\n"
    "                                alerts_found += 1\n"
)
SITE1_NEW = (
    "                                await self._process_new_alert(alert)\n"
    "                                alerts_found += 1\n"
    "                                await self._maybe_auto_execute_daily(alert)\n"
)
SITE2_OLD = (
    "                                    await self._process_new_alert(alert)\n"
    "                                    alerts_found += 1\n"
)
SITE2_NEW = (
    "                                    await self._process_new_alert(alert)\n"
    "                                    alerts_found += 1\n"
    "                                    await self._maybe_auto_execute_daily(alert)\n"
)

assert old_func.count(SITE1_OLD) == 1, f"SITE1 count={old_func.count(SITE1_OLD)}"
assert old_func.count(SITE2_OLD) == 1, f"SITE2 count={old_func.count(SITE2_OLD)}"
assert old_func.startswith("    async def _scan_daily_setups(self):"), "func head unexpected"

mod_func = old_func.replace(SITE1_OLD, SITE1_NEW, 1).replace(SITE2_OLD, SITE2_NEW, 1)
new_func = HELPER + mod_func

# sanity compile the new method+function in a class shell
_shell = "class _S:\n" + "\n".join(
    ("    " + ln) if ln.strip() else ln for ln in new_func.split("\n"))
# new_func is already 4-indent methods; wrap minimal class to compile
compile("class _S:\n" + new_func, "a6_newfunc", "exec")

old_b64 = base64.b64encode(old_func.encode()).decode()
new_b64 = base64.b64encode(new_func.encode()).decode()
print("old_func sha:", hashlib.sha256(old_func.encode()).hexdigest()[:12])
print("new_func sha:", hashlib.sha256(new_func.encode()).hexdigest()[:12])
print("old len:", len(old_func), "new len:", len(new_func))

patcher = '''#!/usr/bin/env python3
"""
patch_a6_daily_autoexec.py  —  v19.34.287b
"Auto-execute longer-horizon setups (regression fix)"

ROOT CAUSE (diag A5/A6, operator-confirmed): _scan_daily_setups builds every
swing/multi_day/position alert and calls ONLY _process_new_alert — it never
evaluated auto_execute_eligible nor called _auto_execute_alert. The sole executor
path (_scan_symbol) HARD-requires intraday tape_confirmation, which daily setups
never compute (tape_signals empty, tape_score default). Net: the bulk of
HIGH/CRITICAL alerts were display-only and never traded.

FIX: add a horizon-aware hand-off. _scan_daily_setups now calls a new
_maybe_auto_execute_daily(alert) after each _process_new_alert. That gate mirrors
the intraday EV quality gate (priority HIGH/CRITICAL + _passes_ev_quality_gate)
but DROPS the tape requirement (tape is intraday-only). The intraday/scalp path
is UNTOUCHED — it still requires tape. The bot's _evaluate_opportunity
(confidence gate + max_open_positions + sizing) remains the final authority, so
this is bounded by your existing risk layer.

1 file, 1 anchored chunk: replaces the live _scan_daily_setups function with
[new helper method + same function + two one-line hand-offs]. Whole-file PRE-SHA
guarded; aborts on drift; .a6bak backup; --check dry-run; idempotent.
Backend restart required.

USAGE (repo root):
  .venv/bin/python scripts/patch_a6_daily_autoexec.py --check
  .venv/bin/python scripts/patch_a6_daily_autoexec.py
  ./start_backend.sh --force
  git add backend/ scripts/ memory/ && git commit -m "v19.34.287b (A6): auto-execute longer-horizon setups (no tape gate)" && git push origin main
Rollback: restore services/enhanced_scanner.py.a6bak + restart.
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = "backend/services/enhanced_scanner.py"
PRE_FILE_SHA = __PRE_FILE__
OLD_B64 = __OLD__
NEW_B64 = __NEW__


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING] {PATH} — run from repo root. ABORT."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    text = cur.decode("utf-8")
    old = base64.b64decode(OLD_B64).decode("utf-8")
    new = base64.b64decode(NEW_B64).decode("utf-8")

    if new in text and old not in text:
        print(f"  [ALREADY] {PATH} — _maybe_auto_execute_daily already wired."); return
    if cur_sha != PRE_FILE_SHA:
        print(f"  [DRIFT] {PATH}")
        print(f"    expected whole-file PRE {PRE_FILE_SHA}")
        print(f"    found on disk           {cur_sha}")
        print(f"    rebase: PYTHONPATH=backend .venv/bin/python backend/scripts/extract_func_generic.py services/enhanced_scanner.py _scan_daily_setups")
        sys.exit(4)
    c = text.count(old)
    if c != 1:
        print(f"  [ANCHOR] _scan_daily_setups matched {c} times (need 1) — ABORT."); sys.exit(3)
    new_text = text.replace(old, new, 1)
    new_bytes = new_text.encode("utf-8")
    print(f"  [PATCH ] {PATH}  whole-file {cur_sha[:12]} -> {sha(new_bytes)[:12]}")
    print(f"           + new method _maybe_auto_execute_daily; 2 daily-loop hand-offs")
    if CHECK:
        print("\\n  [CHECK OK] 1 file to patch. Re-run without --check."); return
    bak = PATH + ".a6bak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(new_bytes)
    print(f"  [PATCHED] {PATH} -> {sha(new_bytes)[:12]}  (backup {bak})")
    print("\\n  NEXT: ./start_backend.sh --force ; then commit.")


if __name__ == "__main__":
    main()
'''
patcher = (patcher
           .replace("__PRE_FILE__", repr(PRE_FILE_SHA))
           .replace("__OLD__", repr(old_b64))
           .replace("__NEW__", repr(new_b64)))
out = "/app/scripts/patch_a6_daily_autoexec.py"
open(out, "w", encoding="utf-8").write(patcher)
print("wrote", out, len(patcher), "bytes")
