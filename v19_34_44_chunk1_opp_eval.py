#!/usr/bin/env python3
"""
v19.34.44 — Stale Alert TTL deploy patch (CHUNK 1 of 5)

Scope: Insert the TTL gate at the top of OpportunityEvaluator.evaluate_opportunity.
Idempotent: re-running is a no-op once the marker is present.

Usage on DGX:
    cd ~/Trading-and-Analysis-Platform
    python3 v19_34_44_chunk1_opp_eval.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "backend" / "services" / "opportunity_evaluator.py"

ANCHOR = (
    "            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT\n"
    "\n"
    "            # ── v19.34.123 — Per-(symbol, direction) open-exposure cap ────"
)

NEW_BLOCK = '''            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT

            # ── v19.34.44 — Stale Alert TTL (default 30s) ─────────────────
            # Alerts that sit in the pipeline too long are no longer trading
            # the setup they detected — the price has moved, the trigger is
            # gone, and the resulting IB order either gets rejected or fills
            # at a worse price than the setup expected. Killing them at the
            # gate saves the round-trip and surfaces "scanner pipeline lag"
            # in the Scanner Quality Panel as `stale_alert_ttl`.
            #
            # Source: `alert["triggered_at_unix"]` (int seconds, set by
            # `enhanced_alerts.compose_alert`). Fail-OPEN if the field is
            # missing so legacy alert paths without timestamps still flow.
            # TTL is env-tunable via `STALE_ALERT_TTL_SECONDS`.
            try:
                import os as _os_ttl
                import time as _time_ttl
                _ttl_raw = _os_ttl.environ.get("STALE_ALERT_TTL_SECONDS", "30")
                try:
                    _ttl_secs = float(_ttl_raw) if _ttl_raw not in (None, "") else 30.0
                except (TypeError, ValueError):
                    _ttl_secs = 30.0
                if _ttl_secs > 0:
                    _triggered_unix = alert.get("triggered_at_unix")
                    # Fallback: parse ISO `triggered_at` if unix epoch absent.
                    if _triggered_unix is None:
                        _iso = alert.get("triggered_at")
                        if _iso:
                            try:
                                _triggered_unix = datetime.fromisoformat(
                                    str(_iso).replace("Z", "+00:00")
                                ).timestamp()
                            except (TypeError, ValueError):
                                _triggered_unix = None
                    if _triggered_unix is not None:
                        try:
                            _age = _time_ttl.time() - float(_triggered_unix)
                        except (TypeError, ValueError):
                            _age = 0.0
                        if _age >= _ttl_secs:
                            logger.warning(
                                "🕒 [v19.34.44 stale-alert-ttl] Dropping %s %s — "
                                "alert age %.1fs ≥ TTL %.0fs. Pipeline lag is "
                                "killing this setup before it can fire.",
                                symbol, setup_type, _age, _ttl_secs,
                            )
                            try:
                                bot.record_rejection(
                                    symbol=symbol, setup_type=setup_type,
                                    direction=direction_str,
                                    reason_code="stale_alert_ttl",
                                    context={
                                        "alert_age_seconds": round(_age, 2),
                                        "ttl_seconds": _ttl_secs,
                                        "triggered_at_unix": _triggered_unix,
                                    },
                                )
                            except Exception:
                                pass
                            try:
                                from services.trade_drop_recorder import record_trade_drop
                                record_trade_drop(
                                    getattr(bot, "_db", None),
                                    gate="stale_alert_ttl",
                                    symbol=symbol,
                                    setup_type=setup_type,
                                    direction=direction_str,
                                    reason=f"stale_alert_ttl: age={_age:.1f}s ≥ {_ttl_secs:.0f}s",
                                    context={
                                        "alert_age_seconds": round(_age, 2),
                                        "ttl_seconds": _ttl_secs,
                                    },
                                )
                            except Exception:
                                pass
                            return None
            except Exception as _ttl_err:
                # Fail-OPEN: a bug in the TTL gate must never block trading.
                logger.debug(
                    "[v19.34.44 stale-alert-ttl] gate crashed (allowing entry "
                    "as fail-open): %s", _ttl_err,
                )

            # ── v19.34.123 — Per-(symbol, direction) open-exposure cap ────'''


def main() -> int:
    if not TARGET.exists():
        print(f"❌ Target not found: {TARGET}")
        return 1
    src = TARGET.read_text()
    if "v19.34.44 stale-alert-ttl" in src:
        print(f"✅ v19.34.44 already applied to {TARGET.name} (idempotent no-op).")
        return 0
    if ANCHOR not in src:
        print(f"❌ Anchor block not found in {TARGET.name}. Aborting.")
        print("    Expected to find the line:")
        print("    '            direction = TradeDirection.LONG if direction_str == \\'long\\' …'")
        print("    immediately followed by the v19.34.123 comment header.")
        return 2
    new_src = src.replace(ANCHOR, NEW_BLOCK, 1)
    TARGET.write_text(new_src)
    print(f"✅ Applied v19.34.44 TTL gate to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
