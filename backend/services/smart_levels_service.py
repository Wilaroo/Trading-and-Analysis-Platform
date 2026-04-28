"""
smart_levels_service.py — unified Support / Resistance computation.

Fuses three independent S/R sources into a single ranked list:

  1. **Volume Profile** — Price bins with the highest accumulated volume
     (HVN = High-Volume Nodes). Price tends to mean-revert toward HVNs
     and accelerate through Low-Volume Nodes (LVNs).

  2. **Swing pivots** — Local price extrema (peaks / troughs) over a
     timeframe-appropriate window. Uses a simple ±k-bar comparison so
     the algorithm is deterministic and dependency-free (no scipy).

  3. **Floor pivots** — Classic PP / S1 / S2 / R1 / R2 / S3 / R3 derived
     from the prior session's H/L/C. Anchor period is timeframe-aware
     (intraday → daily anchor; daily/weekly → monthly anchor).

Each candidate level carries a `kind` tag and a `strength` score in
[0, 1]. Levels within `cluster_pct` of one another are merged into a
single zone (their strengths sum, capped at 1.0). The fused output is
split into `support` (≤ current price) and `resistance` (> current
price), each sorted by distance to current price.

Public API:
  - `compute_smart_levels(db, symbol, timeframe) -> dict`
  - `compute_path_multiplier(db, symbol, bar_size, entry, stop, direction) -> float`

The HTTP wrapper lives in `routers/sentcom_chart.py` — this module is
pure logic (no FastAPI / no Mongo writes) so it's trivially unit-testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# ─── Timeframe knobs ────────────────────────────────────────────────────────

# bar_size string used by `ib_historical_data` for each frontend timeframe.
_BAR_SIZE = {
    "1min":  "1 min",
    "5min":  "5 mins",
    "15min": "15 mins",
    "1hour": "1 hour",
    "1day":  "1 day",
}

# How many bars to load into the smart-levels engine per timeframe.
# More bars = better Volume Profile + more pivots, but slower compute.
_BARS_LOOKBACK = {
    "1min":  600,    # ~ 1.5 trading days
    "5min":  600,    # ~ 1 week
    "15min": 600,    # ~ 3 weeks
    "1hour": 600,    # ~ 4 months
    "1day":  500,    # ~ 2 years
}

# Swing-pivot half-window (k bars on either side must be lower/higher).
_PIVOT_K = {
    "1min":  5,
    "5min":  5,
    "15min": 4,
    "1hour": 4,
    "1day":  3,
}

# Floor-pivot anchor period: which prior bar do we base PP/S1/R1 on?
_FLOOR_PIVOT_ANCHOR_BAR_SIZE = {
    "1min":  "1 day",
    "5min":  "1 day",
    "15min": "1 day",
    "1hour": "1 day",
    "1day":  "1 week",
}

# Number of price bins for the volume profile.
_VOL_BINS = 64

# Cluster-merge tolerance (level_pct of price). Two raw levels closer
# than this fraction of price are merged into a single zone.
_CLUSTER_PCT = 0.0035   # ~35 bps

# Top-K outputs returned per side after cluster + sort.
_TOP_K_PER_SIDE = 6

# Per-source strength weights — tuned against the Tier-1 SMB setups
# that map most cleanly to each source.
_STRENGTH_WEIGHTS = {
    "vp_poc":        1.00,   # the single strongest level on the chart
    "vp_hvn":        0.55,
    "swing":         0.45,
    "floor_pivot_p": 0.65,   # PP — daily/weekly midline; meaningful
    "floor_pivot":   0.50,   # S1/R1
    "floor_pivot_2": 0.35,   # S2/R2
    "floor_pivot_3": 0.20,   # S3/R3 (rarely visited)
}


# ─── Data loaders ──────────────────────────────────────────────────────────

def _load_bars(db, symbol: str, bar_size: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch the most recent `limit` bars for `(symbol, bar_size)`,
    returned in ascending date order. Tolerates both string and datetime
    `date` fields (the `ib_historical_data` collection has historically
    been heterogeneous).
    """
    if db is None:
        return []
    try:
        coll = db["ib_historical_data"]
        cursor = coll.find(
            {"symbol": symbol, "bar_size": bar_size},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ).sort("date", -1).limit(int(limit))
        rows = list(cursor)
    except Exception:
        return []
    rows.reverse()
    return rows


def _bar_dt(bar: Dict[str, Any]) -> Optional[datetime]:
    raw = bar.get("date")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        s = str(raw)
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ─── Volume Profile ────────────────────────────────────────────────────────

def _compute_volume_profile(bars: List[Dict[str, Any]], num_bins: int) -> Dict[str, Any]:
    """Return `{poc_price, hvn_prices: [...]} `. HVN bins are those whose
    volume ≥ 70% of POC volume (canonical threshold). Empty profile if
    bars are insufficient or all-zero-volume."""
    if not bars:
        return {"poc_price": None, "hvn_prices": []}
    lo = min(float(b["low"])  for b in bars if b.get("low")  is not None)
    hi = max(float(b["high"]) for b in bars if b.get("high") is not None)
    if not (hi > lo):
        return {"poc_price": None, "hvn_prices": []}

    bin_size = (hi - lo) / num_bins
    volumes = [0.0] * num_bins
    for b in bars:
        v = float(b.get("volume") or 0)
        if v <= 0:
            continue
        blow  = max(lo, float(b["low"]))
        bhigh = min(hi, float(b["high"]))
        if bhigh < blow:
            continue
        si = max(0, int((blow  - lo) / bin_size))
        ei = min(num_bins - 1, int((bhigh - lo) / bin_size))
        span = ei - si + 1
        if span <= 0:
            continue
        per = v / span
        for i in range(si, ei + 1):
            volumes[i] += per

    if max(volumes) <= 0:
        return {"poc_price": None, "hvn_prices": []}

    poc_idx = max(range(num_bins), key=lambda i: volumes[i])
    poc_vol = volumes[poc_idx]
    poc_price = lo + (poc_idx + 0.5) * bin_size
    hvn_threshold = poc_vol * 0.70

    hvn_prices: List[float] = []
    for i, v in enumerate(volumes):
        if i == poc_idx or v < hvn_threshold:
            continue
        hvn_prices.append(lo + (i + 0.5) * bin_size)

    return {
        "poc_price": poc_price,
        "hvn_prices": hvn_prices,
        "bin_size": bin_size,
        "volumes": volumes,
        "lo": lo,
        "hi": hi,
    }


# ─── Swing pivots ──────────────────────────────────────────────────────────

def _compute_swing_pivots(bars: List[Dict[str, Any]], k: int) -> Tuple[List[float], List[float]]:
    """Detect swing-high (resistance) and swing-low (support) candidates
    using a ±k-bar comparison. O(N*k) but k is tiny (3-5). Returns
    `(swing_highs, swing_lows)` with all numeric prices. Doesn't dedupe
    — the cluster step downstream merges nearby touches."""
    if len(bars) < 2 * k + 1:
        return [], []
    highs: List[float] = []
    lows:  List[float] = []
    for i in range(k, len(bars) - k):
        h = float(bars[i]["high"])
        lo_bar = float(bars[i]["low"])
        is_high = all(h >= float(bars[j]["high"]) for j in range(i - k, i + k + 1) if j != i)
        is_low  = all(lo_bar <= float(bars[j]["low"])  for j in range(i - k, i + k + 1) if j != i)
        if is_high:
            highs.append(h)
        if is_low:
            lows.append(lo_bar)
    return highs, lows


# ─── Floor pivots ──────────────────────────────────────────────────────────

def _compute_floor_pivots(prior_high: float, prior_low: float, prior_close: float) -> Dict[str, float]:
    """Standard floor-pivot formulas. PP = (H + L + C) / 3.
       R1 = 2*PP - L     S1 = 2*PP - H
       R2 = PP + (H-L)   S2 = PP - (H-L)
       R3 = H + 2*(PP-L) S3 = L - 2*(H-PP)
    """
    pp = (prior_high + prior_low + prior_close) / 3.0
    rng = prior_high - prior_low
    return {
        "pp": pp,
        "r1": 2 * pp - prior_low,
        "s1": 2 * pp - prior_high,
        "r2": pp + rng,
        "s2": pp - rng,
        "r3": prior_high + 2 * (pp - prior_low),
        "s3": prior_low  - 2 * (prior_high - pp),
    }


def _load_floor_pivots(db, symbol: str, anchor_bar_size: str) -> Dict[str, float]:
    """Load the prior-completed bar at the anchor timeframe and compute
    floor pivots. Empty dict if data missing."""
    bars = _load_bars(db, symbol, anchor_bar_size, limit=2)
    if len(bars) < 1:
        return {}
    # If we have at least 2 bars, use the SECOND-to-most-recent (the
    # most-recent may be in-progress for daily / weekly anchors during
    # market hours).
    prior = bars[-2] if len(bars) >= 2 else bars[-1]
    try:
        return _compute_floor_pivots(
            float(prior["high"]), float(prior["low"]), float(prior["close"]),
        )
    except (KeyError, ValueError, TypeError):
        return {}


# ─── Clustering + scoring ──────────────────────────────────────────────────

def _cluster_and_rank(
    candidates: List[Dict[str, Any]],
    current_price: float,
) -> List[Dict[str, Any]]:
    """Merge nearby candidates (within `_CLUSTER_PCT` of price) into
    zones. Each cluster keeps the strongest `kind` label and sums
    (capped at 1.0) the strengths of its members."""
    if not candidates:
        return []
    candidates = sorted(candidates, key=lambda c: c["price"])

    clusters: List[Dict[str, Any]] = []
    tol = _CLUSTER_PCT * max(1e-9, current_price)
    for c in candidates:
        if not clusters or abs(c["price"] - clusters[-1]["price_avg"]) > tol:
            clusters.append({
                "price_avg": c["price"],
                "price_low": c["price"],
                "price_high": c["price"],
                "members": [c],
                "strength": c["strength"],
                "kind": c["kind"],
            })
        else:
            cl = clusters[-1]
            cl["members"].append(c)
            cl["price_low"]  = min(cl["price_low"],  c["price"])
            cl["price_high"] = max(cl["price_high"], c["price"])
            n = len(cl["members"])
            cl["price_avg"] = sum(m["price"] for m in cl["members"]) / n
            cl["strength"] = min(1.0, cl["strength"] + c["strength"] * 0.6)
            # Promote label to the strongest constituent
            if c["strength"] > max(m["strength"] for m in cl["members"][:-1]):
                cl["kind"] = c["kind"]

    out: List[Dict[str, Any]] = []
    for cl in clusters:
        out.append({
            "price": round(cl["price_avg"], 4),
            "price_low":  round(cl["price_low"],  4),
            "price_high": round(cl["price_high"], 4),
            "kind": cl["kind"],
            "strength": round(min(1.0, cl["strength"]), 3),
            "touches": len(cl["members"]),
        })
    return out


# ─── Public API ────────────────────────────────────────────────────────────

def compute_smart_levels(db, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Compute fused, ranked support + resistance levels for the
    `(symbol, timeframe)` pair. Returns:
      {
        "current_price": float | None,
        "support":    [{price, kind, strength, ...}, ...],
        "resistance": [...],
        "sources": {                   # raw debug data
            "vp_poc": float | None,
            "vp_hvn_count": int,
            "swing_high_count": int,
            "swing_low_count": int,
            "floor_pivots": {...} | {},
        },
        "timeframe": str,
      }
    """
    bar_size = _BAR_SIZE.get(timeframe)
    if not bar_size:
        return {
            "current_price": None,
            "support": [], "resistance": [], "sources": {},
            "timeframe": timeframe,
            "error": f"unsupported timeframe '{timeframe}'",
        }

    bars = _load_bars(db, symbol, bar_size, limit=_BARS_LOOKBACK[timeframe])
    if len(bars) < 10:
        return {
            "current_price": None,
            "support": [], "resistance": [], "sources": {},
            "timeframe": timeframe,
            "error": "insufficient bars",
        }
    current_price = float(bars[-1]["close"])

    # ── Source 1: Volume Profile ──
    vp = _compute_volume_profile(bars, _VOL_BINS)
    candidates: List[Dict[str, Any]] = []
    if vp["poc_price"] is not None:
        candidates.append({
            "price": vp["poc_price"],
            "kind": "VP_POC",
            "strength": _STRENGTH_WEIGHTS["vp_poc"],
        })
    for hp in vp["hvn_prices"]:
        candidates.append({
            "price": hp,
            "kind": "HVN",
            "strength": _STRENGTH_WEIGHTS["vp_hvn"],
        })

    # ── Source 2: Swing pivots ──
    swing_highs, swing_lows = _compute_swing_pivots(bars, _PIVOT_K[timeframe])
    for h in swing_highs:
        candidates.append({"price": h, "kind": "SWING_HIGH",
                            "strength": _STRENGTH_WEIGHTS["swing"]})
    for lvl in swing_lows:
        candidates.append({"price": lvl, "kind": "SWING_LOW",
                            "strength": _STRENGTH_WEIGHTS["swing"]})

    # ── Source 3: Floor pivots ──
    fp = _load_floor_pivots(db, symbol, _FLOOR_PIVOT_ANCHOR_BAR_SIZE[timeframe])
    if fp:
        candidates.append({"price": fp["pp"], "kind": "PP",
                            "strength": _STRENGTH_WEIGHTS["floor_pivot_p"]})
        for k_name, lab in (("r1", "R1"), ("s1", "S1")):
            candidates.append({"price": fp[k_name], "kind": lab,
                                "strength": _STRENGTH_WEIGHTS["floor_pivot"]})
        for k_name, lab in (("r2", "R2"), ("s2", "S2")):
            candidates.append({"price": fp[k_name], "kind": lab,
                                "strength": _STRENGTH_WEIGHTS["floor_pivot_2"]})
        for k_name, lab in (("r3", "R3"), ("s3", "S3")):
            candidates.append({"price": fp[k_name], "kind": lab,
                                "strength": _STRENGTH_WEIGHTS["floor_pivot_3"]})

    # ── Cluster and rank ──
    fused = _cluster_and_rank(candidates, current_price)

    support    = [c for c in fused if c["price"] < current_price]
    resistance = [c for c in fused if c["price"] >= current_price]
    # Sort each side by strength DESC then by distance ASC (closer wins
    # ties). Top-K cap so the chart doesn't get noisy.
    support.sort(   key=lambda c: (-c["strength"],  current_price - c["price"]))
    resistance.sort(key=lambda c: (-c["strength"], c["price"] - current_price))
    support    = support[:_TOP_K_PER_SIDE]
    resistance = resistance[:_TOP_K_PER_SIDE]

    return {
        "current_price": round(current_price, 4),
        "support": support,
        "resistance": resistance,
        "sources": {
            "vp_poc": round(vp["poc_price"], 4) if vp["poc_price"] is not None else None,
            "vp_hvn_count": len(vp["hvn_prices"]),
            "swing_high_count": len(swing_highs),
            "swing_low_count": len(swing_lows),
            "floor_pivots": {k: round(v, 4) for k, v in fp.items()} if fp else {},
        },
        "timeframe": timeframe,
        "bar_count": len(bars),
    }


# ─── Path multiplier (for opportunity_evaluator) ───────────────────────────

# How much volume in the (entry → stop) zone is "thick"?  Tuned against
# the canonical Volume Profile literature — anything > 30% of total
# profile volume is "fat" and tends to chop.
_PATH_VOL_FAT_PCT  = 0.30
_PATH_VOL_LEAN_PCT = 0.10
_PATH_MULT_FAT     = 0.70   # downsize when stop-zone is thick
_PATH_MULT_LEAN    = 1.00   # full size when stop-zone is clean
_PATH_MULT_DEFAULT = 0.85


def compute_path_multiplier(
    db,
    symbol: str,
    bar_size: str,
    entry: float,
    stop: float,
    direction: str,
) -> Dict[str, Any]:
    """Return `{multiplier, reason, vol_pct, ...}` describing how much
    of the volume profile sits in the price corridor between `entry`
    and `stop` on the wrong side of the trade.

    LONG  → wrong side is below entry, down to stop.
    SHORT → wrong side is above entry, up to stop.

    Multiplier ∈ [_PATH_MULT_FAT, _PATH_MULT_LEAN]. 1.0 ⇒ clean LVN,
    no resistance to your stop zone (full size). 0.7 ⇒ thick HVN
    cluster between you and the stop (downsize).

    `bar_size` should usually match the timeframe the bot evaluated the
    setup on (5 mins for scalps, 1 day for swings). Always returns a
    well-formed dict; defaults to multiplier=1.0 with reason
    `insufficient_data` when Mongo / inputs aren't workable.
    """
    out_default = {
        "multiplier": 1.0,
        "reason": "insufficient_data",
        "vol_pct": None,
        "entry": entry,
        "stop": stop,
        "direction": direction,
    }
    if not entry or not stop or entry == stop:
        return out_default

    # Use enough bars to make the profile statistically meaningful but
    # not so many that ancient regimes dominate the distribution.
    bars = _load_bars(db, symbol, bar_size, limit=300)
    if len(bars) < 30:
        return out_default

    vp = _compute_volume_profile(bars, _VOL_BINS)
    if vp.get("poc_price") is None or not vp.get("volumes"):
        return out_default

    lo = vp["lo"]
    bin_size = vp["bin_size"]
    volumes  = vp["volumes"]
    total_vol = sum(volumes)
    if total_vol <= 0:
        return out_default

    # Define the path corridor.
    direction_norm = (direction or "").lower()
    if direction_norm in {"long", "buy", "up"}:
        path_low, path_high = float(min(entry, stop)), float(max(entry, stop))
    elif direction_norm in {"short", "sell", "down"}:
        path_low, path_high = float(min(entry, stop)), float(max(entry, stop))
    else:
        return {**out_default, "reason": "unknown_direction"}

    if path_high <= lo or path_low >= lo + bin_size * len(volumes):
        # Path corridor entirely outside the profile range → no info.
        return {**out_default, "reason": "path_outside_profile"}

    si = max(0,                int((path_low  - lo) / bin_size))
    ei = min(len(volumes) - 1, int((path_high - lo) / bin_size))
    if ei < si:
        return out_default
    path_vol = sum(volumes[si:ei + 1])
    vol_pct = path_vol / total_vol

    if vol_pct >= _PATH_VOL_FAT_PCT:
        mult, reason = _PATH_MULT_FAT,    "thick_hvn_in_stop_zone"
    elif vol_pct <= _PATH_VOL_LEAN_PCT:
        mult, reason = _PATH_MULT_LEAN,   "clean_lvn_to_stop"
    else:
        mult, reason = _PATH_MULT_DEFAULT, "moderate_volume_in_path"

    return {
        "multiplier": round(mult, 3),
        "reason": reason,
        "vol_pct": round(vol_pct, 3),
        "entry": entry,
        "stop": stop,
        "direction": direction_norm,
        "path_low": round(path_low, 4),
        "path_high": round(path_high, 4),
    }
