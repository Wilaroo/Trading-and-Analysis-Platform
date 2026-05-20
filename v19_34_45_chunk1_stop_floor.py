#!/usr/bin/env python3
"""v19.34.45 chunk 1/2 — Stop-floor enforcement in opportunity_evaluator."""
from pathlib import Path
import sys

TARGET = Path(__file__).resolve().parent / "backend" / "services" / "opportunity_evaluator.py"

ANCHOR = '''                        stop_price = guard["stop"]
                    stop_guard_meta = guard
            except Exception as exc:
                logger.debug(f"stop-guard skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # Calculate targets if not provided
            if not target_prices:'''

NEW = '''                        stop_price = guard["stop"]
                    stop_guard_meta = guard
            except Exception as exc:
                logger.debug(f"stop-guard skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # \u2500\u2500 v19.34.45 \u2014 Guardrail-floor enforcement \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
            # If the (alert-supplied, possibly smart-levels-widened) stop
            # is tighter than 0.3 \u00d7 ATR, replace with the canonical
            # per-setup ATR-based stop. Sizer absorbs the wider risk.
            stop_floor_meta = None
            try:
                import os as _os_floor
                _enf_raw = _os_floor.environ.get("STOP_FLOOR_ENFORCE", "1")
                _enf_on = str(_enf_raw).strip().lower() not in ("0","","false","no","off")
                if _enf_on and stop_price and entry_price and atr and atr > 0:
                    try:
                        _floor_mult = float(_os_floor.environ.get(
                            "EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT", "0.3"
                        ))
                    except (TypeError, ValueError):
                        _floor_mult = 0.3
                    _distance = abs(float(entry_price) - float(stop_price))
                    _threshold = _floor_mult * float(atr)
                    if _distance < _threshold:
                        _orig_stop = float(stop_price)
                        _new_stop = self.calculate_atr_based_stop(
                            float(entry_price), direction, float(atr), setup_type, bot,
                        )
                        _new_distance = abs(float(entry_price) - float(_new_stop))
                        if _new_distance >= _threshold:
                            logger.warning(
                                "\U0001fa79 [v19.34.45 stop-floor] %s %s \u2014 alert stop "
                                "$%.4f (\u0394=$%.4f, %.1f%% of ATR $%.4f) below floor "
                                "%.2f\u00d7ATR=$%.4f. Recomputed via per-setup multiplier "
                                "\u2192 $%.4f (\u0394=$%.4f). Sizer will absorb the wider risk.",
                                symbol, setup_type, _orig_stop, _distance,
                                (_distance / float(atr)) * 100.0, float(atr),
                                _floor_mult, _threshold, _new_stop, _new_distance,
                            )
                            stop_price = _new_stop
                            stop_floor_meta = {
                                "applied": True,
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                                "original_distance": _distance,
                                "recomputed_distance": _new_distance,
                            }
                        else:
                            logger.error(
                                "\u26a0\ufe0f [v19.34.45 stop-floor] %s %s \u2014 alert stop AND "
                                "recomputed stop both below %.2f\u00d7ATR floor "
                                "(alert \u0394=$%.4f, recomputed \u0394=$%.4f, threshold "
                                "$%.4f). Check SETUP_MULTIPLIERS entry for %r.",
                                symbol, setup_type, _floor_mult,
                                _distance, _new_distance, _threshold, setup_type,
                            )
                            stop_floor_meta = {
                                "applied": False,
                                "reason": "recomputed_also_too_tight",
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                            }
            except Exception as _floor_err:
                logger.debug(
                    "[v19.34.45 stop-floor] enforce crashed (fail-open): %s",
                    _floor_err,
                )

            # Calculate targets if not provided
            if not target_prices:'''

src = TARGET.read_text()
if "v19.34.45 stop-floor" in src:
    print("\u2705 v19.34.45 already applied (idempotent).")
    sys.exit(0)
if ANCHOR not in src:
    print(f"\u274c Anchor not found in {TARGET.name}.")
    sys.exit(2)
TARGET.write_text(src.replace(ANCHOR, NEW, 1))
print(f"\u2705 v19.34.45 stop-floor applied to {TARGET.name}")
