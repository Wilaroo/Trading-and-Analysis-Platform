"""v401 — Just-in-time tape confirmation for fast (scalp/intraday) entries.

Reads a TOP-OF-BOOK quote snapshot from the IB pusher (existing
/rpc/quote-snapshot — NO new pusher endpoint required) and derives a tape_score
+ bid/ask imbalance via the SMB tape engine. Used to confirm order-flow right
before a fast-horizon entry, so tape data is available exactly when it matters
even though the 3 standing L2 slots can't cover the whole book.

Behaviour:
  • Whole feature dormant unless TAPE_JIT_CONFIRM=on (default off) → zero
    behaviour change until the operator flips it on live intraday.
  • When on, it is ADVISORY: stamps tape onto the trade + logs.
  • Blocking gate (reject entry when tape opposes the trade side) is opt-in via
    TAPE_JIT_GATE=on (default off).
  • get_tape_confirmation NEVER raises — failures return None (fail-open).
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Deadband around 0 imbalance so a near-balanced book is "neutral", not a signal.
_IMBALANCE_DEADBAND = 0.10


def _env_on(key: str, default: bool = False) -> bool:
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def jit_confirm_enabled() -> bool:
    """Master switch for the JIT tape read (default OFF — ships dormant)."""
    return _env_on("TAPE_JIT_CONFIRM", False)


def jit_gate_enabled() -> bool:
    """When ON, a tape read that OPPOSES the trade side blocks the entry."""
    return _env_on("TAPE_JIT_GATE", False)


def get_tape_confirmation(symbol: str, direction: str = "long") -> Optional[Dict]:
    """Top-of-book order-flow read for `symbol`.

    Returns {tape_score (0-10), imbalance (-1..1), bias, confirms (bool),
    source} or None when no quote is available. `confirms` = does the book
    imbalance support `direction` beyond the deadband. Never raises.
    """
    try:
        from services.ib_pusher_rpc import get_pusher_rpc_client
        from services.smb_unified_scoring import analyze_tape_from_quote_data

        client = get_pusher_rpc_client()
        if not client.is_configured():
            return None
        quote = client.quote_snapshot(symbol)
        if not quote:
            return None

        metrics = analyze_tape_from_quote_data(symbol, quote)
        imb = float(getattr(metrics, "bid_ask_imbalance", 0.0) or 0.0)
        ts = float(getattr(metrics, "tape_score", 0) or 0)

        is_long = str(direction).lower() in ("long", "buy", "bullish")
        if imb > _IMBALANCE_DEADBAND:
            bias = "bullish"
        elif imb < -_IMBALANCE_DEADBAND:
            bias = "bearish"
        else:
            bias = "neutral"
        confirms = (is_long and imb > _IMBALANCE_DEADBAND) or (
            not is_long and imb < -_IMBALANCE_DEADBAND
        )
        return {
            "tape_score": round(ts, 1),
            "imbalance": round(imb, 3),
            "bias": bias,
            "confirms": bool(confirms),
            "source": "quote_snapshot",
        }
    except Exception as e:
        logger.debug("[tape-jit] confirmation failed for %s: %s", symbol, e)
        return None
