"""v19.34.169 — Pre-market deploy: POSITION-tier stop cap + EOD heartbeat.

Idempotent edits to:
  1. backend/services/opportunity_evaluator.py
       Inject a 5%-of-entry stop_distance cap for ATR multipliers >= 2.5
       (INVESTMENT and POSITION horizons). Operator-tunable via env
       MAX_STOP_PCT_INVESTMENT / MAX_STOP_PCT_POSITION.

  2. backend/services/position_manager.py
       Inject an EOD heartbeat that writes one sentcom_thought per
       minute inside the EOD window so the operator can SEE the
       scheduler firing.

The script is IDEMPOTENT — re-running produces the same final state.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /.../backend
OE = os.path.join(ROOT, "services", "opportunity_evaluator.py")
PM = os.path.join(ROOT, "services", "position_manager.py")


STOP_CAP_BLOCK = '''        # ── v19.34.169 — POSITION/INVESTMENT stop_pct cap ─────────────
        # Multi-day setups (rs_leader_break, accumulation_entry,
        # power_trend_stack, stage_2_breakout, etc.) use 2.5-3.0× ATR
        # multipliers which on high-priced volatile names produce
        # 12-14% raw stop distances (e.g. ALAB $326 → $40/share stop).
        # Combined with the fixed risk_per_trade budget, share counts
        # collapse to 1-3. Cap the stop at 5% of entry for these
        # horizons so the risk-per-share stays reasonable while the
        # strategy keeps its multi-day intent. Operator-tunable via
        # env: `MAX_STOP_PCT_POSITION` / `MAX_STOP_PCT_INVESTMENT`.
        # Scalps and intraday setups untouched.
        try:
            import os as _os
            multi_day_caps = {
                # Setups with ATR multiplier >= 2.5 (investment + position)
                'investment': float(_os.environ.get("MAX_STOP_PCT_INVESTMENT", "0.05")),
                'position':   float(_os.environ.get("MAX_STOP_PCT_POSITION",   "0.05")),
            }
            # Bucket by multiplier — 2.5+ is investment/position horizon.
            cap_pct = None
            if multiplier >= 3.0:
                cap_pct = multi_day_caps['position']
            elif multiplier >= 2.5:
                cap_pct = multi_day_caps['investment']
            if cap_pct and entry_price > 0:
                cap_distance = entry_price * cap_pct
                if stop_distance > cap_distance:
                    logger.info(
                        f"[atr_stop] v169 cap: setup={setup_type} mult={multiplier} "
                        f"raw_stop={stop_distance:.3f} ({stop_distance/entry_price*100:.1f}%) "
                        f"→ capped at {cap_pct*100:.0f}% = {cap_distance:.3f}"
                    )
                    stop_distance = cap_distance
        except Exception as _cap_err:
            logger.debug(f"[atr_stop] v169 cap skipped: {_cap_err}")

'''

OE_ANCHOR_OLD = '''            multiplier = max(bot.risk_params.min_atr_multiplier, min(multiplier, bot.risk_params.max_atr_multiplier))
        stop_distance = atr * multiplier
        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
'''

OE_ANCHOR_NEW = '''            multiplier = max(bot.risk_params.min_atr_multiplier, min(multiplier, bot.risk_params.max_atr_multiplier))
        stop_distance = atr * multiplier

''' + STOP_CAP_BLOCK + '''        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
'''


EOD_HEARTBEAT_BLOCK = '''        # ── v19.34.169 — EOD HEARTBEAT (observability) ────────────────
        # Emit a sentcom_thought once per minute while inside the EOD
        # window so the operator can SEE the scheduler firing from the
        # UI. Prior to v169 the EOD code ran silently when there were
        # no positions to close, which looked identical to "scheduler
        # never fired". Dedupes per HH:MM stamp via in-process attr.
        try:
            hb_stamp = now_et.strftime("%Y-%m-%d %H:%M")
            last_hb = getattr(bot, "_eod_last_heartbeat_stamp", None)
            if last_hb != hb_stamp:
                bot._eod_last_heartbeat_stamp = hb_stamp
                db = getattr(bot, "_db", None) or getattr(bot, "db", None)
                if db is not None:
                    eod_eligible_count = db["bot_trades"].count_documents({
                        "closed_at": None,
                        "exit_price": None,
                        "fill_price": {"$ne": None},
                        "close_at_eod": True,
                    })
                    db["sentcom_thoughts"].insert_one({
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "category": "eod_heartbeat",
                        "thought": (
                            f"EOD window tick {hb_stamp} ET — eligible "
                            f"close_at_eod positions: {eod_eligible_count}, "
                            f"executed_today={bot._eod_close_executed_today}, "
                            f"half_day={is_half_day}, "
                            f"window={eod_hour:02d}:{eod_minute:02d}-{market_close_hour:02d}:00 ET"
                        ),
                        "metadata": {
                            "eligible_positions": eod_eligible_count,
                            "executed_today": bot._eod_close_executed_today,
                            "is_half_day": is_half_day,
                            "eod_hour": eod_hour,
                            "eod_minute": eod_minute,
                        },
                    })
        except Exception as hb_err:
            logger.debug(f"v19.34.169: EOD heartbeat write failed: {hb_err}")

'''

PM_ANCHOR_OLD = '''        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return

        # ── v19.34.153 P0 EOD ghost-flatten + T-2/T-1 fallbacks ──────
'''

PM_ANCHOR_NEW = '''        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return

''' + EOD_HEARTBEAT_BLOCK + '''        # ── v19.34.153 P0 EOD ghost-flatten + T-2/T-1 fallbacks ──────
'''


def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v169.{stamp}"
    shutil.copy2(path, dst)
    return dst


def patch_oe() -> bool:
    with open(OE, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.169 — POSITION/INVESTMENT stop_pct cap" in src:
        print("  - opportunity_evaluator.py already has v169 stop cap — skipping")
        return False
    if OE_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {OE} — cannot patch")
        print("       (the calculate_atr_based_stop block may have been refactored)")
        sys.exit(2)
    bak = _backup(OE)
    print(f"  - Backup: {bak}")
    src = src.replace(OE_ANCHOR_OLD, OE_ANCHOR_NEW, 1)
    with open(OE, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - opportunity_evaluator.py patched (stop_pct cap)")
    return True


def patch_pm() -> bool:
    with open(PM, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.169 — EOD HEARTBEAT" in src:
        print("  - position_manager.py already has v169 EOD heartbeat — skipping")
        return False
    if PM_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {PM} — cannot patch")
        sys.exit(3)
    bak = _backup(PM)
    print(f"  - Backup: {bak}")
    src = src.replace(PM_ANCHOR_OLD, PM_ANCHOR_NEW, 1)
    with open(PM, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - position_manager.py patched (EOD heartbeat)")
    return True


def main():
    print("=" * 60)
    print("v19.34.169 — Pre-market sizing+EOD observability deploy")
    print("=" * 60)
    oe_changed = patch_oe()
    pm_changed = patch_pm()
    print()
    print(f"opportunity_evaluator.py changed: {oe_changed}")
    print(f"position_manager.py changed:      {pm_changed}")
    print()
    print("Next steps:")
    print("  1. .venv/bin/python -m pytest backend/tests/test_v19_34_169_stop_cap.py -v")
    print("  2. git add -A && git commit -m 'v19.34.169: POSITION stop cap + EOD heartbeat'")
    print("  3. Restart backend (./start_backend.sh --force)")
    print("  4. After EOD window today, check:")
    print("     db.sentcom_thoughts.find({category:'eod_heartbeat'}).sort({_id:-1}).limit(20)")


if __name__ == "__main__":
    main()
