"""
Sector-Relative Model

Predicts whether a stock will OUTPERFORM or UNDERPERFORM its sector ETF
over the next N bars. This removes market-wide noise — if the whole
market drops 2% but your stock only drops 1%, that's actually alpha.

Sector ETF Mappings:
  XLK  - Technology         XLF  - Financials
  XLE  - Energy             XLV  - Healthcare
  XLI  - Industrials        XLC  - Communication
  XLY  - Consumer Disc.     XLP  - Consumer Staples
  XLU  - Utilities          XLRE - Real Estate
  XLB  - Materials

Features (10 sector-relative features):
  sector_rel_return_5      — Stock's 5-bar return minus sector ETF's 5-bar return
  sector_rel_return_10     — Stock's 10-bar return minus sector ETF's 10-bar return
  sector_rel_rsi           — Stock RSI minus sector ETF RSI (normalized)
  sector_rel_volume        — Stock's relative volume vs sector ETF's relative volume
  sector_rel_momentum      — Stock momentum rank within its sector
  sector_beta              — Stock's beta to its sector ETF (10-bar rolling)
  sector_corr              — Correlation of stock returns to sector returns (10-bar)
  sector_dispersion        — How spread out sector members are (sector-level vol)
  sector_rotation_score    — Is money flowing INTO or OUT of this sector?
  sector_rel_strength_rank — Stock's RS rank vs SPY relative to sector's RS rank

Target: OUTPERFORM (1) vs UNDERPERFORM (0)
  Stock's forward N-bar return > Sector ETF's forward N-bar return
"""

import logging
import numpy as np
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Sector ETF -> list of example member symbols (not exhaustive, used for mapping)
SECTOR_ETF_MAP = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLC":  "Communication Services",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "XLB":  "Materials",
}

ALL_SECTOR_ETFS = list(SECTOR_ETF_MAP.keys())

SECTOR_REL_FEATURE_NAMES = [
    "sector_rel_return_5",
    "sector_rel_return_10",
    "sector_rel_rsi",
    "sector_rel_volume",
    "sector_rel_momentum",
    "sector_beta",
    "sector_corr",
    "sector_dispersion",
    "sector_rotation_score",
    "sector_rel_strength_rank",
]


def compute_sector_relative_features(
    stock_closes: np.ndarray,
    stock_volumes: np.ndarray,
    sector_closes: np.ndarray,
    sector_volumes: np.ndarray,
    spy_closes: np.ndarray = None,
) -> Dict[str, float]:
    """
    Compute sector-relative features.
    All arrays: most-recent-first, at least 20 bars.
    """
    feats = {}
    n = min(len(stock_closes), len(sector_closes))

    if n < 20:
        return {name: 0.0 for name in SECTOR_REL_FEATURE_NAMES}

    # Helper: N-bar return
    def _ret(arr, period):
        if len(arr) > period and arr[period] > 0:
            return (arr[0] - arr[period]) / arr[period]
        return 0.0

    # 1. Relative return (5-bar)
    stock_ret_5 = _ret(stock_closes, 5)
    sector_ret_5 = _ret(sector_closes, 5)
    feats["sector_rel_return_5"] = stock_ret_5 - sector_ret_5

    # 2. Relative return (10-bar)
    stock_ret_10 = _ret(stock_closes, 10)
    sector_ret_10 = _ret(sector_closes, 10)
    feats["sector_rel_return_10"] = stock_ret_10 - sector_ret_10

    # 3. Relative RSI
    def _rsi(closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        c = closes[:period + 1][::-1]
        deltas = np.diff(c)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        ag = np.mean(gains) if len(gains) > 0 else 0
        al = np.mean(losses) if len(losses) > 0 else 0.0001
        if al == 0:
            return 100.0
        return 100 - (100 / (1 + ag / al))

    stock_rsi = _rsi(stock_closes)
    sector_rsi = _rsi(sector_closes)
    feats["sector_rel_rsi"] = (stock_rsi - sector_rsi) / 50  # Normalized to ~[-2, 2]

    # 4. Relative volume
    stock_rvol = stock_volumes[0] / np.mean(stock_volumes[:20]) if np.mean(stock_volumes[:20]) > 0 else 1.0
    sector_rvol = sector_volumes[0] / np.mean(sector_volumes[:20]) if np.mean(sector_volumes[:20]) > 0 else 1.0
    feats["sector_rel_volume"] = stock_rvol - sector_rvol

    # 5. Momentum rank (simplified: stock momentum vs sector momentum)
    stock_mom = _ret(stock_closes, 5)
    sector_mom = _ret(sector_closes, 5)
    feats["sector_rel_momentum"] = stock_mom - sector_mom

    # 6. Beta to sector (10-bar rolling)
    stock_rets = np.diff(stock_closes[:11]) / stock_closes[1:11]
    sector_rets = np.diff(sector_closes[:11]) / sector_closes[1:11]
    if len(stock_rets) >= 5 and np.var(sector_rets) > 0:
        feats["sector_beta"] = float(np.cov(stock_rets, sector_rets)[0, 1] / np.var(sector_rets))
    else:
        feats["sector_beta"] = 1.0

    # 7. Correlation to sector
    if len(stock_rets) >= 5 and np.std(stock_rets) > 0 and np.std(sector_rets) > 0:
        corr = np.corrcoef(stock_rets, sector_rets)[0, 1]
        feats["sector_corr"] = 0.0 if np.isnan(corr) else float(corr)
    else:
        feats["sector_corr"] = 0.0

    # 8. Sector dispersion (how spread out sector returns are — proxy via sector vol)
    if len(sector_rets) >= 5:
        feats["sector_dispersion"] = float(np.std(sector_rets))
    else:
        feats["sector_dispersion"] = 0.0

    # 9. Sector rotation score (is money flowing in/out — use sector ETF 5-bar return)
    feats["sector_rotation_score"] = sector_ret_5

    # 10. Relative strength vs SPY
    if spy_closes is not None and len(spy_closes) >= 11:
        spy_ret_10 = _ret(spy_closes, 10)
        stock_rs = stock_ret_10 - spy_ret_10
        sector_rs = sector_ret_10 - spy_ret_10
        feats["sector_rel_strength_rank"] = stock_rs - sector_rs
    else:
        feats["sector_rel_strength_rank"] = feats["sector_rel_return_10"]

    # Sanitize
    for key in feats:
        val = feats[key]
        if np.isnan(val) or np.isinf(val):
            feats[key] = 0.0

    return feats


def compute_sector_relative_target(
    stock_closes: np.ndarray,
    sector_closes: np.ndarray,
    current_idx: int,
    forecast_horizon: int,
) -> Optional[int]:
    """
    Compute sector-relative target.
    stock_closes, sector_closes: chronological (oldest first)
    Returns 1 (OUTPERFORM) if stock return > sector return, else 0.
    """
    n = min(len(stock_closes), len(sector_closes))
    if current_idx + forecast_horizon >= n:
        return None

    stock_ret = (stock_closes[current_idx + forecast_horizon] - stock_closes[current_idx]) / stock_closes[current_idx]
    sector_ret = (sector_closes[current_idx + forecast_horizon] - sector_closes[current_idx]) / sector_closes[current_idx]

    if stock_closes[current_idx] <= 0 or sector_closes[current_idx] <= 0:
        return None

    return 1 if stock_ret > sector_ret else 0


SECTOR_MODEL_CONFIGS = {
    "1 day":  {"forecast_horizon": 5,  "model_name": "sector_rel_daily"},
    "1 hour": {"forecast_horizon": 6,  "model_name": "sector_rel_1hour"},
    "5 mins": {"forecast_horizon": 12, "model_name": "sector_rel_5min"},
}


class SectorMapper:
    """
    Maps individual stocks to their sector ETF.
    Uses MongoDB to look up sector assignments, with a default mapping cache.
    """

    # Default sector assignments for well-known symbols
    # In production, this would be loaded from a sector classification database
    _TECH_SYMBOLS = {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "INTC", "QCOM", "TXN", "AMAT"}
    _FINANCE_SYMBOLS = {"JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "USB", "PNC", "TFC", "BK", "CME", "ICE"}
    _ENERGY_SYMBOLS = {"XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PXD", "VLO", "PSX", "OXY", "HES", "DVN", "FANG", "HAL", "BKR"}
    _HEALTH_SYMBOLS = {"UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD", "ISRG", "MDT", "SYK"}

    _DEFAULT_MAP = {}
    for sym in _TECH_SYMBOLS:
        _DEFAULT_MAP[sym] = "XLK"
    for sym in _FINANCE_SYMBOLS:
        _DEFAULT_MAP[sym] = "XLF"
    for sym in _ENERGY_SYMBOLS:
        _DEFAULT_MAP[sym] = "XLE"
    for sym in _HEALTH_SYMBOLS:
        _DEFAULT_MAP[sym] = "XLV"

    def __init__(self, db=None):
        self._db = db
        self._cache = dict(self._DEFAULT_MAP)

    def get_sector_etf(self, symbol: str) -> Optional[str]:
        """Get sector ETF for a symbol. Returns None if unknown."""
        if symbol in self._cache:
            return self._cache[symbol]

        # Try to look up from DB if available
        if self._db is not None:
            try:
                doc = self._db.get_collection("symbol_sectors").find_one(
                    {"symbol": symbol}, {"_id": 0, "sector_etf": 1}
                )
                if doc and "sector_etf" in doc:
                    self._cache[symbol] = doc["sector_etf"]
                    return doc["sector_etf"]
            except Exception:
                pass

        # Default to XLK for unknown (most common in typical watchlists)
        return None

    def get_all_sector_etfs(self) -> List[str]:
        return ALL_SECTOR_ETFS
