#!/usr/bin/env python3
"""
patch_a10_trigger_drift_gate.py  —  2026-06-22  (SentCom / DGX Spark)

ONE surgical, drift-guarded edit to backend/services/enhanced_scanner.py:
inserts a TRIGGER RE-VALIDATION GATE into `_auto_execute_alert` (right after
the A8 restart/feed guard, immediately before the auto-exec try-block), so the
bot can NEVER enter a setup whose LIVE price has drifted too far from the
alert's ORIGINAL trigger level.

WHY (operator-traced 2026-06-22 via diag_a8 / diag_a9 + code read of
`_scan_daily_setups` + `_maybe_auto_execute_daily`):
  A8's restart/feed guard stopped the INSTANT post-restart burst, but a steady
  DRIP of old-`created_at` `stage_2_breakout` positions kept executing later.
  Root cause is NOT a stale-price replay — `_scan_daily_setups` rebuilds each
  daily-breakout alert every cycle on fresh bars (current_price IS live). The
  problem is that `trigger_price` is the STABLE daily breakout level, so the
  detector keeps re-firing every cycle while price stays beyond it, and
  `_auto_execute_alert` enters at an ever-more-EXTENDED live price far past the
  clean break. (The old `created_at` is a dedup/upsert first-seen labeling
  artifact, which is exactly why an alert-age gate is the wrong tool.)

FIX — re-fetch the live quote via `_get_quote_with_ib_priority` and SKIP the
execution when |live - trigger| / trigger exceeds
AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT (default 2.0%). Universal: both the intraday
(~_scan_symbol) and A6 daily (`_maybe_auto_execute_daily`) callers funnel
through `_auto_execute_alert`, so one gate covers both.

  • Policy knob   AUTO_EXEC_TRIGGER_DRIFT_POLICY = block | observe | off
                  (default "block"; "observe" logs but still executes; "off"
                  disables the gate entirely).
  • Threshold     AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT = 2.0  (percent; 0 disables).
  • FAIL-OPEN     no trigger_price / no live quote / any error → never blocks.

SAFE BY CONSTRUCTION: anchored span + sha256 pre-check; idempotent; backs up
.a10.bak; AST-compiles before committing. Aborts on drift with rebase hint.

Run from the repo root:
    .venv/bin/python scripts/patch_a10_trigger_drift_gate.py --check   # dry run
    .venv/bin/python scripts/patch_a10_trigger_drift_gate.py           # apply
    .venv/bin/python scripts/patch_a10_trigger_drift_gate.py --rollback
"""
import hashlib
import os
import sys
import ast
import shutil

CANDIDATE_PATHS = [
    "backend/services/enhanced_scanner.py",
    "services/enhanced_scanner.py",
    os.path.join(os.path.dirname(__file__), "..", "backend", "services", "enhanced_scanner.py"),
]

# Anchor: the END of the A8 feed-guard block through the auto-exec try-line.
BEGIN = '            except Exception as _feed_err:\n                logger.debug(f"A8 feed guard skip: {_feed_err}")'
END = '        try:\n            logger.info(f"🤖 Auto-executing alert: {alert.headline}")'
PRE_SHA = "a4b86c98838358c76ea0a491c60c6a6edc706284467eefe36ed6f2a774848e45"
IDEMPOTENT_MARKER = "A10 TRIGGER RE-VALIDATION GATE"

NEW_BLOCK = '''            except Exception as _feed_err:
                logger.debug(f"A8 feed guard skip: {_feed_err}")

        # 2026-06-22 A10 TRIGGER RE-VALIDATION GATE — never enter a setup whose
        # LIVE price has drifted too far from the alert's ORIGINAL trigger.
        # WHY (operator-traced 2026-06-22, diag_a9 + code read): _scan_daily_setups
        # rebuilds daily-breakout alerts every cycle on fresh bars (current_price
        # IS live), but trigger_price is the STABLE daily breakout level — so a
        # setup keeps re-firing and auto-executing at an ever-more-EXTENDED price
        # long after the clean break (the "stale drip" A8's restart guard could
        # not stop; the old created_at is a dedup-upsert labeling artifact, not a
        # price replay). Re-fetch the live quote and SKIP when the drift exceeds
        # AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT. Universal: the intraday AND A6 daily
        # callers funnel through here. FAIL-OPEN: no trigger / no live quote / any
        # error never blocks a valid signal. Env-reversible.
        try:
            _drift_policy = os.environ.get("AUTO_EXEC_TRIGGER_DRIFT_POLICY", "block").lower()
            _trig = float(getattr(alert, "trigger_price", 0.0) or 0.0)
            if _drift_policy != "off" and _trig > 0:
                _q = await self._get_quote_with_ib_priority(alert.symbol)
                _live = float((_q or {}).get("price", 0.0) or 0.0)
                if _live > 0:
                    try:
                        _max_drift = float(os.environ.get("AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT", "2.0"))
                    except (TypeError, ValueError):
                        _max_drift = 2.0
                    _drift = abs(_live - _trig) / _trig * 100.0
                    if _max_drift > 0 and _drift > _max_drift:
                        logger.info(
                            f"\\U0001f6ab A10 trigger-drift gate "
                            f"({'BLOCK' if _drift_policy == 'block' else 'OBSERVE'}): "
                            f"{alert.symbol} {alert.setup_type} \\u2014 live {_live:.2f} drifted "
                            f"{_drift:.2f}% from trigger {_trig:.2f} "
                            f"(max {_max_drift:.2f}%); skipping stale/extended entry"
                        )
                        if _drift_policy == "block":
                            return
        except Exception as _drift_err:
            logger.debug(f"A10 trigger-drift gate skip: {_drift_err}")

        try:
            logger.info(f"🤖 Auto-executing alert: {alert.headline}")'''


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _find_path():
    path = next((p for p in CANDIDATE_PATHS if os.path.isfile(p)), None)
    if not path:
        print("ERROR: enhanced_scanner.py not found. Run from the repo root.")
        sys.exit(2)
    return os.path.abspath(path)


def rollback():
    path = _find_path()
    bak = path + ".a10.bak"
    if not os.path.isfile(bak):
        print(f"No backup at {bak} — nothing to roll back.")
        sys.exit(1)
    shutil.copy2(bak, path)
    print(f"Rolled back {path} from {bak}.")
    print(f"POST whole-file sha256: {_sha(open(path, encoding='utf-8').read())}")


def main(check_only=False):
    path = _find_path()
    content = open(path, encoding="utf-8").read()
    print(f"Target: {path}")
    print(f"PRE  whole-file sha256: {_sha(content)}")

    if IDEMPOTENT_MARKER in content:
        print("  idempotent marker present — already applied. \u2705")
        return

    i = content.find(BEGIN)
    j = content.find(END, i) if i != -1 else -1
    if i == -1 or j == -1:
        print("  ABORT — could not locate anchors. No changes written.")
        print("    rebase: grep -n -A 90 'async def _auto_execute_alert' "
              "backend/services/enhanced_scanner.py  (paste it back so I can re-anchor)")
        sys.exit(1)
    if content.count(BEGIN) != 1 or content.count(END) != 1:
        print(f"  ABORT — anchor not unique (BEGIN x{content.count(BEGIN)}, "
              f"END x{content.count(END)}). No changes written.")
        sys.exit(1)
    j_end = j + len(END)
    span = content[i:j_end]
    actual = _sha(span)
    if actual != PRE_SHA:
        print(f"  ABORT — span sha drift.\n      expected {PRE_SHA}\n      actual   {actual}\n"
              f"    `_auto_execute_alert` differs from what this patcher targets. No changes written.\n"
              f"    rebase: grep -n -A 90 'async def _auto_execute_alert' "
              f"backend/services/enhanced_scanner.py")
        sys.exit(1)

    new_content = content[:i] + NEW_BLOCK + content[j_end:]
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  ABORT — patched content failed to parse: {e}. No changes written.")
        sys.exit(1)

    if check_only:
        print(f"  --check OK: span verified ({PRE_SHA[:12]}\u2026); patched file AST-compiles.")
        print(f"  PREDICTED POST whole-file sha256: {_sha(new_content)}")
        print("  (no changes written)")
        return

    bak = path + ".a10.bak"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  span verified ({PRE_SHA[:12]}\u2026) -> inserted trigger-drift gate "
          f"({len(span)}B -> {len(NEW_BLOCK)}B).")
    print(f"Backup written: {bak}")
    print(f"POST whole-file sha256: {_sha(new_content)}")
    print("\u2705 patch_a10 applied. Restart the backend to load it:")
    print("     ./start_backend.sh --force")
    print("   Tunables (backend/.env, all optional):")
    print("     AUTO_EXEC_TRIGGER_DRIFT_POLICY=block   # block | observe | off")
    print("     AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT=2.0    # percent; 0 disables")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        main(check_only=("--check" in sys.argv))
