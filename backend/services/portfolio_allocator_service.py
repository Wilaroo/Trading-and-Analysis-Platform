"""
Portfolio Allocator Service — thin wiring around HRP/NCO for the live bot.

Problem
-------
The bot fires multiple concurrent positions but sizes them independently.
When two candidates are highly correlated (e.g. AAPL + META both long),
naive sizing doubles the effective tech-long exposure.

Solution
--------
At sizing time we ask: "Given the portfolio of current open + pending
candidates I'd hold, what fraction of risk should go to THIS symbol?"
Then we convert that fraction to a multiplicative adjustment:

    multiplier = hrp_weight(symbol) / equal_weight

So:
  * equal-weighted candidate → multiplier = 1.0 (neutral)
  * diversifier (unique direction/sector) → multiplier > 1.0
  * duplicate of an existing position → multiplier < 1.0

The multiplier is bounded to `[0.4, 1.4]` to stay well-behaved and to
keep the position-size pipeline monotonic.

If the returns lookup can't produce enough data (< 2 usable peers or
< 10 return observations), the allocator returns 1.0 (neutral) and logs
a debug message. Never breaks the bot.

Integration point
-----------------
`opportunity_evaluator.py` — called after strategy-tilt, before the
final `shares <= 0` check. See `get_hrp_multiplier()`.

A returns fetcher is plugged in via `set_returns_fetcher(fn)`; the fn
must be `callable(symbol: str) -> Optional[np.ndarray]` returning the
most recent N daily returns (e.g. 60). If no fetcher is registered, the
allocator is neutral. This keeps the service testable and decoupled.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from services.ai_modules.hrp_allocator import hrp_weights_from_returns

logger = logging.getLogger(__name__)


# ── bounds & tunables ────────────────────────────────────────────────────

MIN_PEERS = 2                 # below this → neutral multiplier
MIN_RETURN_OBSERVATIONS = 10  # per-symbol history needed for correlation
MULTIPLIER_FLOOR = 0.4
MULTIPLIER_CEILING = 1.4


# ── returns fetcher plug-in ──────────────────────────────────────────────

_returns_fetcher: Optional[Callable[[str], Optional[np.ndarray]]] = None


def set_returns_fetcher(fn: Optional[Callable[[str], Optional[np.ndarray]]]) -> None:
    """Register a callable that returns recent daily returns for a symbol.

    `fn("AAPL")` should return a numpy array (1D) of recent daily returns,
    or None if unavailable. Setting to None disables the allocator (neutral).
    """
    global _returns_fetcher
    _returns_fetcher = fn


def get_returns_fetcher() -> Optional[Callable[[str], Optional[np.ndarray]]]:
    return _returns_fetcher


# ── math ─────────────────────────────────────────────────────────────────

def _align_returns(symbols: List[str], fetcher) -> Dict[str, np.ndarray]:
    """Fetch + align returns across peers. Drops symbols with too few points.

    Returns a dict {symbol: 1D array} where every array has the same
    length = min(len) across usable symbols.
    """
    pulled: Dict[str, np.ndarray] = {}
    for s in symbols:
        try:
            r = fetcher(s)
        except Exception as e:
            logger.debug(f"[Allocator] fetch err {s}: {e}")
            continue
        if r is None:
            continue
        r = np.asarray(r, dtype=np.float64).ravel()
        if r.size < MIN_RETURN_OBSERVATIONS:
            continue
        pulled[s] = r

    if len(pulled) < MIN_PEERS:
        return {}

    # Trim to the shortest common length
    min_len = min(a.size for a in pulled.values())
    return {s: a[-min_len:] for s, a in pulled.items()}


def compute_hrp_multipliers(symbols: List[str]) -> Dict[str, float]:
    """Core: compute the HRP-based multiplier for each symbol.

    Returns {symbol: multiplier} where multiplier ∈ [MULTIPLIER_FLOOR,
    MULTIPLIER_CEILING]. Returns {sym: 1.0} for every symbol if the
    allocator is disabled or can't produce a reliable estimate.
    """
    unique_syms = list(dict.fromkeys(s.upper() for s in symbols if s))  # dedupe, preserve order
    if len(unique_syms) < MIN_PEERS or _returns_fetcher is None:
        return {s: 1.0 for s in unique_syms}

    aligned = _align_returns(unique_syms, _returns_fetcher)
    if len(aligned) < MIN_PEERS:
        return {s: 1.0 for s in unique_syms}

    names = list(aligned.keys())
    mat = np.column_stack([aligned[n] for n in names])  # (T, N)
    try:
        weights = hrp_weights_from_returns(mat, asset_names=names)
    except Exception as e:
        logger.debug(f"[Allocator] HRP compute failed: {e}")
        return {s: 1.0 for s in unique_syms}

    equal_weight = 1.0 / len(names)
    out: Dict[str, float] = {}
    for s in unique_syms:
        if s in weights:
            mult = weights[s] / equal_weight
            mult = max(MULTIPLIER_FLOOR, min(MULTIPLIER_CEILING, mult))
            out[s] = round(float(mult), 4)
        else:
            out[s] = 1.0
    return out


def get_hrp_multiplier(symbol: str, peer_symbols: List[str]) -> float:
    """Convenience: single-symbol multiplier given a peer universe.

    Peer universe typically = currently-open positions + pending
    candidates. Symbol itself MUST be included in `peer_symbols` (the
    caller adds it). Returns 1.0 when the allocator can't compute.
    """
    if not symbol:
        return 1.0
    symbol = symbol.upper()
    peers = list(dict.fromkeys([*(s.upper() for s in peer_symbols), symbol]))
    if len(peers) < MIN_PEERS:
        return 1.0
    mults = compute_hrp_multipliers(peers)
    return mults.get(symbol, 1.0)
