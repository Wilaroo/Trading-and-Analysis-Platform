"""
Triple-Barrier Labeling — López de Prado's method for tradeable targets
=======================================================================

Replaces binary up/down labels (which cause majority-class collapse and have
no tradeable interpretation) with a 3-class label tied to what a trader would
actually experience:

    +1   Upper barrier hit first  → profit target achieved before stop
     0   Time barrier hit first   → neither target nor stop reached (noise)
    -1   Lower barrier hit first  → stop-loss triggered before target

Each barrier is defined as a multiple of recent ATR (or fixed %), so the
labels adapt to each symbol's volatility regime.

Why this fixes the DL majority-class collapse:
    - Binary labels: in a bull regime ~53% of samples are "up" → model just
      predicts up always → 53% val accuracy that looks fine but has zero edge.
    - Triple-barrier: the time-exit class (0) eats 30-60% of samples, so no
      single class is a cheap win. The model must actually learn barrier-
      relevant structure (momentum + volatility) to beat baseline.

Usage:
    from services.ai_modules.triple_barrier_labeler import triple_barrier_labels

    labels = triple_barrier_labels(
        highs, lows, closes,
        start_idx=entry_bar_idx,
        pt_atr_mult=2.0,   # 2 × ATR profit target
        sl_atr_mult=1.0,   # 1 × ATR stop loss
        max_bars=20,       # time barrier (20-bar holding period)
        atr_period=14,
    )
    # returns array of {-1, 0, +1} per entry
"""

import numpy as np
from typing import Union


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """True Range rolling mean. Returns array same length as inputs; first `period` values are NaN."""
    tr1 = highs - lows
    prev_close = np.concatenate(([closes[0]], closes[:-1]))
    tr2 = np.abs(highs - prev_close)
    tr3 = np.abs(lows - prev_close)
    tr = np.maximum.reduce([tr1, tr2, tr3])
    atr_out = np.full_like(tr, np.nan, dtype=np.float64)
    if len(tr) >= period:
        # Simple moving average ATR (Wilder's smoothing is a minor refinement we skip here)
        for i in range(period - 1, len(tr)):
            atr_out[i] = np.mean(tr[i - period + 1:i + 1])
    return atr_out


def triple_barrier_label_single(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry_idx: int,
    pt_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_bars: int = 20,
    atr_value: Union[float, None] = None,
) -> int:
    """
    Label a single entry at bar `entry_idx`.
    Returns +1 / 0 / -1 (profit target / time / stop loss hit first).

    If insufficient future bars exist, returns 0 (time barrier).
    """
    n = len(closes)
    if entry_idx >= n - 1:
        return 0
    if atr_value is None or not np.isfinite(atr_value) or atr_value <= 0:
        return 0  # Can't label without volatility estimate

    entry_price = closes[entry_idx]
    upper = entry_price + pt_atr_mult * atr_value
    lower = entry_price - sl_atr_mult * atr_value
    end_idx = min(entry_idx + max_bars, n - 1)

    for i in range(entry_idx + 1, end_idx + 1):
        # Check whether the bar's range crossed either barrier.
        # Convention: if both are hit in same bar, assume SL hit first (conservative).
        hit_lower = lows[i] <= lower
        hit_upper = highs[i] >= upper
        if hit_lower and hit_upper:
            return -1  # Conservative: assume stop hit first
        if hit_lower:
            return -1
        if hit_upper:
            return 1

    return 0  # Time barrier


def triple_barrier_labels(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry_indices: np.ndarray = None,
    pt_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_bars: int = 20,
    atr_period: int = 14,
) -> np.ndarray:
    """
    Vectorized-ish triple-barrier labeling.

    Args:
        highs, lows, closes: np.ndarray of OHLC arrays (same length N)
        entry_indices: indices into the arrays where entries happen.
                       If None, labels every bar from `atr_period` onwards.
        pt_atr_mult, sl_atr_mult: profit target / stop loss as multiple of ATR
        max_bars: maximum holding period before time barrier fires
        atr_period: bars used to estimate ATR at each entry

    Returns:
        np.ndarray of ints (+1 / 0 / -1), one per entry_index.
    """
    if entry_indices is None:
        entry_indices = np.arange(atr_period, len(closes) - 1)

    atr_series = atr(highs, lows, closes, period=atr_period)
    labels = np.zeros(len(entry_indices), dtype=np.int64)

    for j, idx in enumerate(entry_indices):
        labels[j] = triple_barrier_label_single(
            highs, lows, closes,
            entry_idx=int(idx),
            pt_atr_mult=pt_atr_mult,
            sl_atr_mult=sl_atr_mult,
            max_bars=max_bars,
            atr_value=float(atr_series[idx]) if idx < len(atr_series) else None,
        )

    return labels


def label_to_class_index(label: int) -> int:
    """Map triple-barrier label (-1/0/+1) to 3-class index (0/1/2) for CE loss."""
    return {-1: 0, 0: 1, 1: 2}.get(int(label), 1)


def class_index_to_direction(class_idx: int) -> str:
    """Map 3-class prediction index (0/1/2) back to direction string."""
    return {0: "down", 1: "flat", 2: "up"}.get(int(class_idx), "flat")


def label_distribution(labels: np.ndarray) -> dict:
    """Sanity check — returns class balance for logging."""
    total = len(labels)
    if total == 0:
        return {"down": 0.0, "flat": 0.0, "up": 0.0, "total": 0}
    return {
        "down": float(np.sum(labels == -1)) / total,
        "flat": float(np.sum(labels == 0)) / total,
        "up": float(np.sum(labels == 1)) / total,
        "total": total,
    }


def validate_label_distribution(
    labels: np.ndarray,
    *,
    min_class_pct: float = 0.10,
    flat_max_pct: float = 0.55,
    dominant_max_pct: float = 0.70,
) -> dict:
    """Health check that flags pathological class distributions.

    Returns a dict with:
        status:        "healthy" | "warning" | "critical"
        distribution:  {down, flat, up, total}
        issues:        list of human-readable problem descriptions
        recommendations: list of actionable fixes (sweep, retrain, etc.)

    Thresholds (tunable):
        min_class_pct     = 0.10  — any class below this is too rare
                                    for the model to learn it reliably
        flat_max_pct      = 0.55  — FLAT class eating >55% means
                                    barriers are too wide / horizon too
                                    long, training degenerates into
                                    "predict FLAT always"
        dominant_max_pct  = 0.70  — any class >70% → majority-class
                                    collapse, model has no edge

    Invoked by the trainer after labelling; a warning log is emitted
    when status != "healthy" so the operator knows to sweep PT/SL.
    """
    dist = label_distribution(labels)
    total = dist["total"]
    issues: list = []
    recs: list = []

    if total == 0:
        return {
            "status": "critical",
            "distribution": dist,
            "issues": ["no labels — upstream data missing"],
            "recommendations": ["check entry_indices and input bars before labelling"],
        }

    for cls_name in ("down", "flat", "up"):
        pct = dist[cls_name]
        if pct < min_class_pct:
            issues.append(
                f"{cls_name.upper()} class only {pct*100:.1f}% of samples "
                f"(< {min_class_pct*100:.0f}%) — model can't learn this class"
            )

    if dist["flat"] > flat_max_pct:
        issues.append(
            f"FLAT class {dist['flat']*100:.1f}% > {flat_max_pct*100:.0f}% — "
            "barriers too wide or max_bars too long; FLAT absorbs most signal"
        )
        recs.append(
            "Lower max_bars or tighten PT/SL. Run the triple-barrier config "
            "sweep (run_triple_barrier_sweep.py) per setup."
        )

    max_class = max(("down", "flat", "up"), key=lambda c: dist[c])
    if dist[max_class] > dominant_max_pct:
        issues.append(
            f"{max_class.upper()} class dominates at {dist[max_class]*100:.1f}% "
            f"(> {dominant_max_pct*100:.0f}%) — majority-class collapse likely"
        )
        recs.append(
            "Apply class-balance weighting (balanced_sqrt already active) + "
            "consider symmetric PT=SL to remove reward asymmetry bias."
        )

    status = "healthy"
    if issues:
        status = "critical" if dist[max_class] > dominant_max_pct else "warning"

    return {
        "status": status,
        "distribution": dist,
        "issues": issues,
        "recommendations": recs or (["distribution looks healthy"] if status == "healthy" else []),
    }
