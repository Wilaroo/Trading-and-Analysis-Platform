#!/usr/bin/env python3
"""
v19.34.44 — Stale Alert TTL deploy patch (CHUNK 3 of 5)

Scope: Add `stale_alert_ttl` branch to _compose_rejection_narrative so the
Bot's Brain UI panel narrates the drop in plain English.
Idempotent.

Usage on DGX:
    cd ~/Trading-and-Analysis-Platform
    python3 v19_34_44_chunk3_narrative.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "backend" / "services" / "trading_bot_service.py"

ANCHOR = '''        if reason_code == "oversized_notional":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — required position "
                f"size would blow past my max-notional-per-trade cap. Setup "
                f"is fine, but the trade plan doesn't fit."
            )

        # Generic fallback — never throw, never produce empty text.'''

NEW_BLOCK = '''        if reason_code == "oversized_notional":
            return (
                f"⏭️ Passing on {symbol} {setup_display} — required position "
                f"size would blow past my max-notional-per-trade cap. Setup "
                f"is fine, but the trade plan doesn't fit."
            )
        if reason_code == "stale_alert_ttl":
            age_secs = ctx.get("alert_age_seconds")
            ttl_secs = ctx.get("ttl_seconds")
            age_phrase = f" ({age_secs:.0f}s old, TTL {int(ttl_secs)}s)" if (
                age_secs is not None and ttl_secs is not None
            ) else ""
            return (
                f"🕒 Passing on {symbol} {setup_display} — this alert sat "
                f"in the pipeline too long{age_phrase}. By now the trigger "
                f"price has moved and the setup is no longer the one the "
                f"scanner detected. Killing it here saves a round-trip to "
                f"IB and a near-certain bad fill."
            )

        # Generic fallback — never throw, never produce empty text.'''


def main() -> int:
    if not TARGET.exists():
        print(f"❌ Target not found: {TARGET}")
        return 1
    src = TARGET.read_text()
    if 'reason_code == "stale_alert_ttl"' in src:
        print("✅ stale_alert_ttl narrative branch already present (idempotent no-op).")
        return 0
    if ANCHOR not in src:
        print(f"❌ Anchor block not found in {TARGET.name}. Aborting.")
        return 2
    TARGET.write_text(src.replace(ANCHOR, NEW_BLOCK, 1))
    print(f"✅ Added stale_alert_ttl narrative branch in {TARGET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
