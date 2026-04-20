"""
Triple-Barrier Label Config — per (setup_type, bar_size) PT/SL/horizon overrides.

Reference: Mlfinlab's `labeling.get_events()` with `pt_sl` list — same concept,
implemented natively so we stay GPU-friendly and dependency-free.

Storage:
    Mongo collection `triple_barrier_config` — one doc per (setup_type, bar_size)
    Fields:
        setup_type:        "BREAKOUT" | "VWAP" | ... | "_GENERIC_" (fallback)
        bar_size:          "5 mins", "1 day", etc.
        trade_side:        "long" | "short"
        pt_atr_mult:       Profit-target ATR multiple
        sl_atr_mult:       Stop-loss ATR multiple
        max_bars:          Time-barrier (bars until timeout)
        atr_period:        ATR smoothing length
        chosen_at:         ISO timestamp of last sweep
        sweep_metrics:     {down_pct, flat_pct, up_pct, balance_score, info_gain}

Defaults (if no Mongo entry exists):
    pt=2.0, sl=1.0, max_bars=<setup_forecast_horizon>, atr_period=14

Usage:
    cfg = get_tb_config(db, "BREAKOUT", "5 mins", trade_side="long",
                        default_max_bars=12)
    labels = triple_barrier_labels(
        highs, lows, closes,
        pt_atr_mult=cfg["pt_atr_mult"],
        sl_atr_mult=cfg["sl_atr_mult"],
        max_bars=cfg["max_bars"],
        atr_period=cfg["atr_period"],
    )
"""

from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

COLLECTION = "triple_barrier_config"

DEFAULT_PT = 2.0
DEFAULT_SL = 1.0
DEFAULT_ATR_PERIOD = 14


def _key(setup_type: str, bar_size: str, trade_side: str) -> Dict[str, str]:
    return {
        "setup_type": setup_type.upper(),
        "bar_size": bar_size,
        "trade_side": trade_side.lower(),
    }


def get_tb_config(
    db,
    setup_type: str,
    bar_size: str,
    trade_side: str = "long",
    default_max_bars: int = 20,
) -> Dict[str, Any]:
    """Look up PT/SL/horizon config; fall back to generic defaults."""
    if db is not None:
        try:
            doc = db[COLLECTION].find_one(
                _key(setup_type, bar_size, trade_side),
                {"_id": 0},
            )
            if doc:
                return {
                    "pt_atr_mult": float(doc.get("pt_atr_mult", DEFAULT_PT)),
                    "sl_atr_mult": float(doc.get("sl_atr_mult", DEFAULT_SL)),
                    "max_bars": int(doc.get("max_bars", default_max_bars)),
                    "atr_period": int(doc.get("atr_period", DEFAULT_ATR_PERIOD)),
                    "source": "db",
                    "chosen_at": doc.get("chosen_at"),
                }
            # Fallback 1: any-side entry (if we only swept long, reuse for short)
            doc = db[COLLECTION].find_one(
                {"setup_type": setup_type.upper(), "bar_size": bar_size},
                {"_id": 0},
            )
            if doc:
                return {
                    "pt_atr_mult": float(doc.get("pt_atr_mult", DEFAULT_PT)),
                    "sl_atr_mult": float(doc.get("sl_atr_mult", DEFAULT_SL)),
                    "max_bars": int(doc.get("max_bars", default_max_bars)),
                    "atr_period": int(doc.get("atr_period", DEFAULT_ATR_PERIOD)),
                    "source": "db_cross_side",
                    "chosen_at": doc.get("chosen_at"),
                }
        except Exception as e:
            logger.debug(f"tb_config lookup failed ({setup_type}/{bar_size}): {e}")
    return {
        "pt_atr_mult": DEFAULT_PT,
        "sl_atr_mult": DEFAULT_SL,
        "max_bars": default_max_bars,
        "atr_period": DEFAULT_ATR_PERIOD,
        "source": "default",
        "chosen_at": None,
    }


def save_tb_config(
    db,
    setup_type: str,
    bar_size: str,
    trade_side: str,
    pt_atr_mult: float,
    sl_atr_mult: float,
    max_bars: int,
    atr_period: int,
    sweep_metrics: Optional[Dict[str, Any]] = None,
):
    """Persist a chosen config after a sweep."""
    if db is None:
        return
    doc = {
        **_key(setup_type, bar_size, trade_side),
        "pt_atr_mult": float(pt_atr_mult),
        "sl_atr_mult": float(sl_atr_mult),
        "max_bars": int(max_bars),
        "atr_period": int(atr_period),
        "chosen_at": datetime.now(timezone.utc).isoformat(),
        "sweep_metrics": sweep_metrics or {},
    }
    db[COLLECTION].update_one(
        _key(setup_type, bar_size, trade_side),
        {"$set": doc},
        upsert=True,
    )
    logger.info(
        f"[tb_config] saved {setup_type}/{bar_size}/{trade_side} "
        f"pt={pt_atr_mult} sl={sl_atr_mult} max_bars={max_bars}"
    )


def list_all_configs(db) -> list:
    """Enumerate all saved configs for UI display."""
    if db is None:
        return []
    return list(db[COLLECTION].find({}, {"_id": 0}))
