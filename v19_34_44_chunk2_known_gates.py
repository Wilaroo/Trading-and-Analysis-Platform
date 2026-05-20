#!/usr/bin/env python3
"""
v19.34.44 — Stale Alert TTL deploy patch (CHUNK 2 of 5)

Scope: Register `stale_alert_ttl` in KNOWN_GATES inside trade_drop_recorder.
Idempotent.

Usage on DGX:
    cd ~/Trading-and-Analysis-Platform
    python3 v19_34_44_chunk2_known_gates.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "backend" / "services" / "trade_drop_recorder.py"

ANCHOR = (
    '    "no_trade_executor",        # bot._trade_executor is None\n'
    '    "pre_exec_guardrail_veto",  # services.execution_guardrails ran_all_guardrails veto'
)

NEW_BLOCK = (
    '    "no_trade_executor",        # bot._trade_executor is None\n'
    '    "stale_alert_ttl",          # v19.34.44 opportunity_evaluator pipeline-lag TTL\n'
    '    "pre_exec_guardrail_veto",  # services.execution_guardrails ran_all_guardrails veto'
)


def main() -> int:
    if not TARGET.exists():
        print(f"❌ Target not found: {TARGET}")
        return 1
    src = TARGET.read_text()
    if '"stale_alert_ttl"' in src:
        print(f"✅ stale_alert_ttl already in KNOWN_GATES (idempotent no-op).")
        return 0
    if ANCHOR not in src:
        print(f"❌ Anchor block not found in {TARGET.name}. Aborting.")
        return 2
    TARGET.write_text(src.replace(ANCHOR, NEW_BLOCK, 1))
    print(f"✅ Registered stale_alert_ttl in {TARGET.name}.KNOWN_GATES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
