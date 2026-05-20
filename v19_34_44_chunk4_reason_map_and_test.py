#!/usr/bin/env python3
"""
v19.34.44 — Stale Alert TTL deploy patch (CHUNK 4 of 5)

Scope:
  4a. Register stale_alert_ttl in REASON_MAP (rejection_analytics_router).
  4b. Extend the source-scan in tests/test_trade_drop_instrumentation.py so the
      gate-coverage canary picks up gates wired inside opportunity_evaluator.py.

Idempotent.

Usage on DGX:
    cd ~/Trading-and-Analysis-Platform
    python3 v19_34_44_chunk4_reason_map_and_test.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ROUTER = ROOT / "backend" / "routers" / "rejection_analytics_router.py"
TEST_FILE = ROOT / "backend" / "tests" / "test_trade_drop_instrumentation.py"

ROUTER_ANCHOR = '    "stale_alert":        {"label": "Stale alert (TTL expired)",            "category": CAT_SCANNER_QUALITY},'
ROUTER_NEW = (
    '    "stale_alert":        {"label": "Stale alert (TTL expired)",            "category": CAT_SCANNER_QUALITY},\n'
    '    "stale_alert_ttl":    {"label": "Stale alert (pipeline-lag TTL)",        "category": CAT_SCANNER_QUALITY},'
)

TEST_ANCHOR_1 = (
    'ROOT = Path(__file__).resolve().parents[1]\n'
    'TRADING_BOT = (ROOT / "services" / "trading_bot_service.py").read_text()\n'
    'TRADE_EXEC = (ROOT / "services" / "trade_execution.py").read_text()\n'
)
TEST_NEW_1 = (
    'ROOT = Path(__file__).resolve().parents[1]\n'
    'TRADING_BOT = (ROOT / "services" / "trading_bot_service.py").read_text()\n'
    'TRADE_EXEC = (ROOT / "services" / "trade_execution.py").read_text()\n'
    '# v19.34.44 — Stale Alert TTL lives in the evaluator (upstream of the\n'
    '# bot/executor), so it has its own breadcrumb site we must scan too.\n'
    'OPP_EVAL = (ROOT / "services" / "opportunity_evaluator.py").read_text()\n'
)

TEST_ANCHOR_2 = (
    'def test_known_gates_match_instrumented_gates():\n'
    '    # Ensure no orphan gates in KNOWN_GATES that aren\'t actually wired.\n'
    '    instrumented_in_bot = set(re.findall(r\'gate="(\\w+)"\', TRADING_BOT))\n'
    '    instrumented_in_exec = set(re.findall(r\'gate="(\\w+)"\', TRADE_EXEC))\n'
    '    union = instrumented_in_bot | instrumented_in_exec\n'
)
TEST_NEW_2 = (
    'def test_known_gates_match_instrumented_gates():\n'
    '    # Ensure no orphan gates in KNOWN_GATES that aren\'t actually wired.\n'
    '    instrumented_in_bot = set(re.findall(r\'gate="(\\w+)"\', TRADING_BOT))\n'
    '    instrumented_in_exec = set(re.findall(r\'gate="(\\w+)"\', TRADE_EXEC))\n'
    '    instrumented_in_eval = set(re.findall(r\'gate="(\\w+)"\', OPP_EVAL))\n'
    '    union = instrumented_in_bot | instrumented_in_exec | instrumented_in_eval\n'
)


def patch_file(path: Path, anchor: str, new_block: str, marker: str, label: str) -> int:
    if not path.exists():
        print(f"❌ Target not found: {path}")
        return 1
    src = path.read_text()
    if marker in src:
        print(f"✅ {label} already applied (idempotent no-op).")
        return 0
    if anchor not in src:
        print(f"❌ Anchor block not found in {path.name} for {label}.")
        return 2
    path.write_text(src.replace(anchor, new_block, 1))
    print(f"✅ {label} applied to {path.name}")
    return 0


def main() -> int:
    rc1 = patch_file(
        ROUTER, ROUTER_ANCHOR, ROUTER_NEW,
        marker='"stale_alert_ttl":',
        label="REASON_MAP stale_alert_ttl",
    )
    if rc1 not in (0,):
        return rc1
    rc2 = patch_file(
        TEST_FILE, TEST_ANCHOR_1, TEST_NEW_1,
        marker='OPP_EVAL = ',
        label="OPP_EVAL source-scan import",
    )
    if rc2 not in (0,):
        return rc2
    rc3 = patch_file(
        TEST_FILE, TEST_ANCHOR_2, TEST_NEW_2,
        marker='instrumented_in_eval',
        label="OPP_EVAL source-scan union",
    )
    return rc3


if __name__ == "__main__":
    sys.exit(main())
