#!/usr/bin/env python3
"""
patch_a8_freshness_gate.py  —  2026-06-22  (SentCom / DGX Spark)

ONE surgical, drift-guarded edit to backend/services/enhanced_scanner.py:
inserts a RESTART/FEED GUARD at the top of `_auto_execute_alert` (right after
the existing eligibility check), so a scanner (re)start can NEVER flush a
backlog of eligible setups into execution before live data + scan state are
re-established.

WHY (operator-traced 2026-06-22 via diag_a9_entry_provenance):
  ~14 stage_2_breakout positions opened in a single 17:54-18:03Z burst the
  instant the A6-enabled scanner came back, while the IB pusher was still cold
  ("no push data yet"). i.e. a "flush-on-restart", not 14 real-time decisions.

WHY NOT an alert-age gate:
  `created_at` is ambiguous here — daily alerts can carry a first-seen
  timestamp pinned via dedup/upsert, so age would either miss the flush or
  over-block legit re-detections. The restart/feed guard targets the actual
  failure mode directly and is immune to that ambiguity.

FIX — both the intraday (~line 4212) and A6 daily (~line 7421) auto-exec
callers funnel through `_auto_execute_alert`. Two cheap, FAIL-OPEN checks:
  (1) WARM-UP — hold auto-exec for the first AUTO_EXEC_WARMUP_SCANS loop
      cycles after (re)start (`_scan_count` resets to 0 on start and ticks
      every cycle in all branches). Gives pusher + universe time to warm and
      lets still-valid setups re-detect on fresh data before any fires.
  (2) FEED HEALTH — require the IB pusher to be connected (set
      AUTO_EXEC_REQUIRE_FEED=0 to disable). Skips when the live feed is down.

SAFE BY CONSTRUCTION: anchored span + sha256 pre-check; idempotent; backs up
.a8.bak; AST-compiles before committing.

Run from the repo root:
    PYTHONPATH=backend .venv/bin/python scripts/patch_a8_freshness_gate.py
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

BEGIN = "        # Check eligibility"
END = '            logger.info(f"🤖 Auto-executing alert: {alert.headline}")'
PRE_SHA = "3b98662a2aee96035b303122cb84f01bbd5485396cb9075b700c6fb091a692cf"
IDEMPOTENT_MARKER = "A8 RESTART/FEED GUARD"

NEW_BLOCK = '''        # Check eligibility
        if not alert.auto_execute_eligible:
            return

        # 2026-06-22 A8 RESTART/FEED GUARD — a (re)start must never FLUSH a
        # backlog of eligible setups into execution before live data + scan
        # state are re-established. Operator-traced 2026-06-22 (diag_a9): ~14
        # stage_2_breakout positions opened in one 17:54-18:03Z burst the
        # instant the A6-enabled scanner relaunched, pusher still cold. Both
        # the intraday and A6 daily callers funnel through here, so one guard
        # covers both. Fail-open: a parse/import error never blocks a signal.
        try:
            _warm = int(os.environ.get("AUTO_EXEC_WARMUP_SCANS", "5"))
        except (TypeError, ValueError):
            _warm = 5
        if _warm > 0 and getattr(self, "_scan_count", 0) < _warm:
            logger.info(
                f"🪫 A8 warm-up: HOLD auto-exec {alert.symbol} {alert.setup_type} "
                f"— scan #{getattr(self, '_scan_count', 0)} < warm-up {_warm} "
                f"(post-restart guard; arms after the feed/universe warm up)"
            )
            return
        if os.environ.get("AUTO_EXEC_REQUIRE_FEED", "1") not in ("0", "false", "False"):
            try:
                import routers.ib as _ibmod
                if not _ibmod.is_pusher_connected():
                    logger.info(
                        f"📴 A8 feed guard: HOLD auto-exec {alert.symbol} "
                        f"{alert.setup_type} — IB pusher not connected (no live data)"
                    )
                    return
            except Exception as _feed_err:
                logger.debug(f"A8 feed guard skip: {_feed_err}")

        try:
            logger.info(f"🤖 Auto-executing alert: {alert.headline}")'''


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    path = next((p for p in CANDIDATE_PATHS if os.path.isfile(p)), None)
    if not path:
        print("ERROR: enhanced_scanner.py not found. Run from the repo root.")
        sys.exit(2)
    path = os.path.abspath(path)
    content = open(path, encoding="utf-8").read()
    print(f"Target: {path}")
    print(f"PRE  whole-file sha256: {_sha(content)}")

    if IDEMPOTENT_MARKER in content:
        print("  idempotent marker present — already applied. ✅")
        sys.exit(0)

    i = content.find(BEGIN)
    j = content.find(END, i) if i != -1 else -1
    if i == -1 or j == -1:
        print("  ABORT — could not locate anchors. No changes written.")
        sys.exit(1)
    j_end = j + len(END)
    span = content[i:j_end]
    actual = _sha(span)
    if actual != PRE_SHA:
        print(f"  ABORT — span sha drift.\n      expected {PRE_SHA}\n      actual   {actual}\n"
              f"    `_auto_execute_alert` differs from what this patcher targets. No changes written.")
        sys.exit(1)

    new_content = content[:i] + NEW_BLOCK + content[j_end:]
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  ABORT — patched content failed to parse: {e}. No changes written.")
        sys.exit(1)

    bak = path + ".a8.bak"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  span verified ({PRE_SHA[:12]}…) -> inserted restart/feed guard ({len(span)}B -> {len(NEW_BLOCK)}B).")
    print(f"Backup written: {bak}")
    print(f"POST whole-file sha256: {_sha(new_content)}")
    print("✅ patch_a8 applied. Restart the backend to load it:")
    print("     ./start_backend.sh --force")
    print("   Tunables: AUTO_EXEC_WARMUP_SCANS=5 (cycles held after restart; 0=off) · "
          "AUTO_EXEC_REQUIRE_FEED=1 (0=off)")


if __name__ == "__main__":
    main()
