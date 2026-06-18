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

from datetime import datetime, timezone
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


# ─── Runtime threshold overrides ───────────────────────────────────────────
#
# 2026-04-28e: the nightly `multiplier_threshold_optimizer` writes
# adjusted thresholds into `multiplier_threshold_history`. The snap
# functions below read overrides via `_get_active_thresholds(db)` —
# cached for 5 min so we don't hit Mongo on every call.
import time as _time

_THRESHOLD_CACHE: Dict[str, Any] = {"ts": 0.0, "values": None}
_THRESHOLD_CACHE_TTL_SEC = 300


def invalidate_threshold_cache() -> None:
    """Force the next `_get_active_thresholds` call to re-read from
    Mongo. Called by the optimizer immediately after persisting new
    values so live trading picks them up within seconds."""
    _THRESHOLD_CACHE["ts"] = 0.0
    _THRESHOLD_CACHE["values"] = None


def _get_active_thresholds(db) -> Dict[str, float]:
    """Return `{stop_min_level_strength, target_snap_outside_pct,
    path_vol_fat_pct}` — the most recent applied optimizer values, or
    the module defaults if no override exists. Cached `_THRESHOLD_CACHE_TTL_SEC`."""
    now = _time.time()
    if _THRESHOLD_CACHE["values"] is not None and (now - _THRESHOLD_CACHE["ts"]) < _THRESHOLD_CACHE_TTL_SEC:
        return _THRESHOLD_CACHE["values"]

    defaults = {
        "stop_min_level_strength": _STOP_MIN_LEVEL_STRENGTH,
        "target_snap_outside_pct": _TARGET_SNAP_OUTSIDE_PCT,
        "path_vol_fat_pct":        _PATH_VOL_FAT_PCT,
    }
    values = dict(defaults)

    if db is None:
        _THRESHOLD_CACHE.update({"ts": now, "values": values})
        return values

    try:
        doc = db["multiplier_threshold_history"].find_one(
            {"applied": True},
            sort=[("ran_at", -1)],
            projection={"_id": 0, "thresholds_after": 1},
        )
        if doc and isinstance(doc.get("thresholds_after"), dict):
            for k in defaults:
                v = doc["thresholds_after"].get(k)
                if v is None:
                    continue
                try:
                    values[k] = float(v)
                except (TypeError, ValueError):
                    continue
    except Exception:
        # Fail-open: caller still gets module defaults.
        pass

    _THRESHOLD_CACHE.update({"ts": now, "values": values})
    return values


# ─── Stop-placement guard (for opportunity_evaluator) ──────────────────────

# Bar-size ↔ frontend-timeframe mapping used when the bot calls into us
# with the historical-collector bar_size string.
_BAR_SIZE_TO_TF = {
    "1 min":   "1min",
    "5 mins":  "5min",
    "15 mins": "15min",
    "30 mins": "15min",   # close enough — same daily-pivot anchor
    "1 hour":  "1hour",
    "1 day":   "1day",
}

# Snap-buffer: how close (as a fraction of price) the proposed stop has
# to be to a strong S/R level for us to widen it. 50bps catches the
# typical "stop sitting just inside an HVN" case without firing on
# every nearby pivot.
_STOP_SNAP_BUFFER_PCT = 0.005

# Cap on how far we're allowed to widen the original stop (preserves
# the position-sizing risk math — a runaway stop would silently change
# R:R and bypass the bot's risk caps).
_STOP_MAX_WIDEN_PCT = 0.40

# Only levels whose `strength` >= this value are eligible to widen a
# stop. Filters out noise pivots that wouldn't provide meaningful
# support / resistance.
_STOP_MIN_LEVEL_STRENGTH = 0.50


def compute_stop_guard(
    db,
    symbol: str,
    bar_size: str,
    entry: float,
    proposed_stop: float,
    direction: str,
) -> Dict[str, Any]:
    """Return `{stop, snapped, ...}` where `stop` may be a widened
    version of `proposed_stop` if a strong S/R level sits in (or just
    past) the danger zone.

    Rule of thumb (LONG, mirror for SHORT):
      1. Find strong supports near `proposed_stop` — defined as any
         support whose price sits in
         `[proposed_stop - buffer, proposed_stop + 2*buffer]`.
      2. If any are found, snap `stop` to `lowest_level − ε` so the
         stop sits just past the cluster instead of inside it. ε is
         5 bps of price (or 1 cent, whichever is larger).
      3. Cap the new stop at `(1 + _STOP_MAX_WIDEN_PCT)` of the
         original distance — never let the snap silently 2x the risk.

    Always returns a well-formed dict; defaults to `snapped=False,
    stop=proposed_stop` when we can't resolve a good snap target.
    """
    out_default = {
        "stop": float(proposed_stop),
        "snapped": False,
        "reason": "stop_clear_of_levels",
        "original_stop": float(proposed_stop),
    }
    if not entry or not proposed_stop or entry == proposed_stop:
        return {**out_default, "reason": "invalid_inputs"}

    tf = _BAR_SIZE_TO_TF.get(bar_size, "5min")
    levels = compute_smart_levels(db, symbol, tf)
    if levels.get("error"):
        return {**out_default, "reason": "no_levels"}

    direction_norm = (direction or "").lower()
    epsilon = max(0.01, float(entry) * 0.0005)
    original_distance = abs(entry - proposed_stop)
    max_distance = original_distance * (1 + _STOP_MAX_WIDEN_PCT)
    buffer = float(entry) * _STOP_SNAP_BUFFER_PCT
    # Pull the currently-active min-strength threshold (may be tuned
    # nightly by `multiplier_threshold_optimizer`).
    active_min_strength = _get_active_thresholds(db)["stop_min_level_strength"]

    if direction_norm in {"long", "buy", "up"}:
        supports = levels.get("support") or []
        # Levels that sit in the snap-buffer zone around proposed_stop.
        # We bias the upper edge of the buffer wider (2×) because a
        # support level *above* proposed_stop is more dangerous (price
        # has to break through it before reaching our stop) than one
        # below.
        nearby = [
            s for s in supports
            if s.get("strength", 0) >= active_min_strength
            and (s["price"] - buffer) <= proposed_stop <= (s["price"] + 2 * buffer)
        ]
        if not nearby:
            return out_default
        target = min(nearby, key=lambda s: s["price"])
        new_stop = target["price"] - epsilon
        new_distance = abs(entry - new_stop)
        if new_distance > max_distance:
            return {
                **out_default,
                "reason": "would_exceed_max_widen",
                "level_price": target["price"],
                "level_kind": target["kind"],
            }
        if new_stop >= proposed_stop:
            return {**out_default, "reason": "no_widening_needed"}
        return {
            "stop": round(new_stop, 4),
            "snapped": True,
            "reason": "snapped_below_support",
            "level_kind": target["kind"],
            "level_price": target["price"],
            "level_strength": target.get("strength"),
            "original_stop": float(proposed_stop),
            "widen_pct": round((new_distance / original_distance) - 1.0, 3),
        }

    if direction_norm in {"short", "sell", "down"}:
        resistances = levels.get("resistance") or []
        nearby = [
            r for r in resistances
            if r.get("strength", 0) >= active_min_strength
            and (r["price"] - 2 * buffer) <= proposed_stop <= (r["price"] + buffer)
        ]
        if not nearby:
            return out_default
        target = max(nearby, key=lambda r: r["price"])
        new_stop = target["price"] + epsilon
        new_distance = abs(entry - new_stop)
        if new_distance > max_distance:
            return {
                **out_default,
                "reason": "would_exceed_max_widen",
                "level_price": target["price"],
                "level_kind": target["kind"],
            }
        if new_stop <= proposed_stop:
            return {**out_default, "reason": "no_widening_needed"}
        return {
            "stop": round(new_stop, 4),
            "snapped": True,
            "reason": "snapped_above_resistance",
            "level_kind": target["kind"],
            "level_price": target["price"],
            "level_strength": target.get("strength"),
            "original_stop": float(proposed_stop),
            "widen_pct": round((new_distance / original_distance) - 1.0, 3),
        }

    return {**out_default, "reason": "unknown_direction"}


# ─── Trailing-stop snap (liquidity-aware breakeven + trail updates) ──────

# Max distance (as fraction of price) from `current_price` we'll search
# for a liquidity-anchored stop. Wider than `_STOP_SNAP_BUFFER_PCT`
# because at trail-time the move is already underway and we want the
# nearest *meaningful* HVN, not just one within stop-placement
# walking distance.
_TRAIL_SNAP_SEARCH_PCT = 0.02   # 2% — covers a typical day's range


def compute_trailing_stop_snap(
    db,
    symbol: str,
    bar_size: str,
    entry: float,
    current_price: float,
    proposed_stop: float,
    direction: str,
    floor_at_breakeven: bool = True,
) -> Dict[str, Any]:
    """Snap a trailing stop to the nearest strong S/R level on the
    *protected* side of the trade — liquidity-aware replacement for
    fixed-% trail / breakeven-at-entry behaviour.

    LONG (mirror for SHORT):
      1. Pull supports BELOW `current_price` whose strength meets the
         active min threshold and that sit within
         `_TRAIL_SNAP_SEARCH_PCT` below `current_price`.
      2. Take the *highest* such support (closest to price → tightest
         trail backed by real liquidity).
      3. `new_stop = support_price - epsilon` (just past the cluster).
      4. Constraints:
         - `new_stop >= proposed_stop` (only ratchet UP, never give back)
         - if `floor_at_breakeven`, `new_stop >= entry` is NOT enforced;
           the operator's spec calls for snapping *below* entry to the
           HVN. But we still floor at `proposed_stop` so we never
           regress mid-trade.
         - `new_stop < current_price - epsilon` (defensive — never
           place stop above the price it's protecting).

    Always returns a well-formed dict; defaults to
    `{stop: proposed_stop, snapped: False, reason: ...}` when no
    suitable level is found.
    """
    out_default = {
        "stop": float(proposed_stop),
        "snapped": False,
        "reason": "no_levels_in_range",
        "original_stop": float(proposed_stop),
    }

    if not entry or not current_price or not proposed_stop:
        return {**out_default, "reason": "invalid_inputs"}

    # Accept either the historical-collector bar_size string ("5 mins")
    # or the frontend timeframe code ("5min").
    tf = _BAR_SIZE_TO_TF.get(bar_size, bar_size if bar_size in _BAR_SIZE else "5min")
    levels = compute_smart_levels(db, symbol, tf)
    if levels.get("error"):
        return {**out_default, "reason": "no_levels"}

    direction_norm = (direction or "").lower()
    epsilon = max(0.01, float(current_price) * 0.0005)
    search_floor = float(current_price) * (1 - _TRAIL_SNAP_SEARCH_PCT)
    search_ceiling = float(current_price) * (1 + _TRAIL_SNAP_SEARCH_PCT)
    active_min_strength = _get_active_thresholds(db)["stop_min_level_strength"]

    if direction_norm in {"long", "buy", "up"}:
        supports = levels.get("support") or []
        # Levels strictly below `current_price` and within the search
        # window. Strength gate keeps noise pivots out.
        candidates = [
            s for s in supports
            if s.get("strength", 0) >= active_min_strength
            and search_floor <= s["price"] < (current_price - epsilon)
        ]
        if not candidates:
            return out_default
        # Highest support below price = tightest trail backed by liquidity.
        target = max(candidates, key=lambda s: s["price"])
        new_stop = round(target["price"] - epsilon, 4)
        if new_stop < proposed_stop:
            # Don't loosen — only ratchet up.
            return {**out_default, "reason": "would_loosen_stop"}
        return {
            "stop": new_stop,
            "snapped": True,
            "reason": "snapped_to_hvn_below",
            "level_kind": target["kind"],
            "level_price": target["price"],
            "level_strength": target.get("strength"),
            "original_stop": float(proposed_stop),
        }

    if direction_norm in {"short", "sell", "down"}:
        resistances = levels.get("resistance") or []
        candidates = [
            r for r in resistances
            if r.get("strength", 0) >= active_min_strength
            and (current_price + epsilon) < r["price"] <= search_ceiling
        ]
        if not candidates:
            return out_default
        # Lowest resistance above price = tightest trail backed by liquidity.
        target = min(candidates, key=lambda r: r["price"])
        new_stop = round(target["price"] + epsilon, 4)
        if new_stop > proposed_stop:
            # For shorts, "ratchet" means stops move DOWN (closer to
            # entry from above). Reject moves that would loosen.
            return {**out_default, "reason": "would_loosen_stop"}
        return {
            "stop": new_stop,
            "snapped": True,
            "reason": "snapped_to_hvn_above",
            "level_kind": target["kind"],
            "level_price": target["price"],
            "level_strength": target.get("strength"),
            "original_stop": float(proposed_stop),
        }

    return {**out_default, "reason": "unknown_direction"}


# ─── Target-snap (mirror of stop_guard, for take-profit prices) ────────────

# How wide of a window around each proposed target do we search for a
# liquidity level? Asymmetric — bias toward levels just past the
# target (where the actual liquidity sits), with a small inside buffer.
_TARGET_SNAP_INSIDE_PCT  = 0.005   # 50 bps before the target
_TARGET_SNAP_OUTSIDE_PCT = 0.012   # 120 bps past the target

# Caps on target adjustment vs original distance from entry. Pulling
# in (taking profit earlier) is usually fine; extending must be small
# so risk:reward math doesn't drift.
_TARGET_MAX_PULL_PCT   = 0.30   # max -30% of original distance
_TARGET_MAX_EXTEND_PCT = 0.15   # max +15% of original distance

# Min level strength required to trigger a snap.
_TARGET_MIN_LEVEL_STRENGTH = 0.50


def _snap_one_target(
    proposed_target: float,
    entry: float,
    direction_norm: str,
    levels: Dict[str, Any],
    epsilon: float,
    outside_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute a possibly-snapped variant of a single target. Returns
    `{target, snapped, ...}`. `direction_norm` is already lowered.
    `outside_pct` overrides the module-default `_TARGET_SNAP_OUTSIDE_PCT`
    when supplied (used by the live tuning path)."""
    out_default = {
        "target": float(proposed_target),
        "snapped": False,
        "reason": "no_nearby_level",
        "original_target": float(proposed_target),
    }
    if not entry or not proposed_target:
        return {**out_default, "reason": "invalid_inputs"}

    original_distance = abs(proposed_target - entry)
    inside_buf  = float(entry) * _TARGET_SNAP_INSIDE_PCT
    outside_buf = float(entry) * (outside_pct if outside_pct is not None else _TARGET_SNAP_OUTSIDE_PCT)
    min_dist = original_distance * (1 - _TARGET_MAX_PULL_PCT)
    max_dist = original_distance * (1 + _TARGET_MAX_EXTEND_PCT)

    if direction_norm in {"long", "buy", "up"}:
        resistances = levels.get("resistance") or []
        # Search window: [target - inside, target + outside]
        nearby = [
            r for r in resistances
            if r.get("strength", 0) >= _TARGET_MIN_LEVEL_STRENGTH
            and (proposed_target - inside_buf) <= r["price"] <= (proposed_target + outside_buf)
        ]
        if not nearby:
            return out_default
        # Choose the LOWEST nearby resistance — taking profits before
        # the first liquidity wall is more reliable than waiting for a
        # second.
        target_level = min(nearby, key=lambda r: r["price"])
        new_target = target_level["price"] - epsilon
        new_distance = abs(new_target - entry)
        if new_distance < min_dist or new_distance > max_dist:
            return {
                **out_default,
                "reason": "would_exceed_target_caps",
                "level_price": target_level["price"],
                "level_kind": target_level["kind"],
            }
        if new_target <= entry:    # never let a long target slip below entry
            return out_default
        return {
            "target": round(new_target, 4),
            "snapped": True,
            "reason": "snapped_below_resistance",
            "level_kind": target_level["kind"],
            "level_price": target_level["price"],
            "level_strength": target_level.get("strength"),
            "original_target": float(proposed_target),
            "shift_pct": round((new_distance / original_distance) - 1.0, 3),
        }

    if direction_norm in {"short", "sell", "down"}:
        supports = levels.get("support") or []
        nearby = [
            s for s in supports
            if s.get("strength", 0) >= _TARGET_MIN_LEVEL_STRENGTH
            and (proposed_target - outside_buf) <= s["price"] <= (proposed_target + inside_buf)
        ]
        if not nearby:
            return out_default
        target_level = max(nearby, key=lambda s: s["price"])
        new_target = target_level["price"] + epsilon
        new_distance = abs(new_target - entry)
        if new_distance < min_dist or new_distance > max_dist:
            return {
                **out_default,
                "reason": "would_exceed_target_caps",
                "level_price": target_level["price"],
                "level_kind": target_level["kind"],
            }
        if new_target >= entry:    # never let a short target slip above entry
            return out_default
        return {
            "target": round(new_target, 4),
            "snapped": True,
            "reason": "snapped_above_support",
            "level_kind": target_level["kind"],
            "level_price": target_level["price"],
            "level_strength": target_level.get("strength"),
            "original_target": float(proposed_target),
            "shift_pct": round((new_distance / original_distance) - 1.0, 3),
        }

    return {**out_default, "reason": "unknown_direction"}


def compute_target_snap(
    db,
    symbol: str,
    bar_size: str,
    entry: float,
    proposed_targets: List[float],
    direction: str,
) -> Dict[str, Any]:
    """Snap each proposed target to just before the nearest strong S/R
    cluster on the move side.

    Returns:
      {
        "targets": [t1, t2, t3, ...],   # adjusted prices, length-preserved
        "details": [{...per-target meta...}, ...],
        "any_snapped": bool,
      }

    The output's `targets` list always has the same length as the input,
    so the evaluator can drop it in without restructuring downstream
    code (TP1/TP2/TP3 stay positional). Targets that collapse onto each
    other (e.g. two pre-snap targets land on the same resistance) get
    nudged ε apart so order-management logic doesn't see duplicates.
    """
    out_targets: List[float] = []
    out_details: List[Dict[str, Any]] = []
    any_snapped = False

    if not proposed_targets:
        return {"targets": [], "details": [], "any_snapped": False}

    direction_norm = (direction or "").lower()
    levels = compute_smart_levels(db, symbol, _BAR_SIZE_TO_TF.get(bar_size, "5min"))
    if levels.get("error"):
        # Fallback: pass through unchanged
        return {
            "targets": [float(t) for t in proposed_targets],
            "details": [{"target": float(t), "snapped": False, "reason": "no_levels"}
                        for t in proposed_targets],
            "any_snapped": False,
        }
    # Pull active thresholds (optimizer may tune `outside_pct`).
    active_outside_pct = _get_active_thresholds(db)["target_snap_outside_pct"]

    epsilon = max(0.01, float(entry) * 0.0005)
    for t in proposed_targets:
        det = _snap_one_target(float(t), float(entry), direction_norm, levels, epsilon, active_outside_pct)
        if det["snapped"]:
            any_snapped = True
        out_targets.append(det["target"])
        out_details.append(det)

    # Dedup collapsed targets (preserve ordering).
    if direction_norm in {"long", "buy", "up"}:
        for i in range(1, len(out_targets)):
            if out_targets[i] <= out_targets[i - 1]:
                out_targets[i] = round(out_targets[i - 1] + epsilon, 4)
                out_details[i] = {**out_details[i], "deduped": True}
    elif direction_norm in {"short", "sell", "down"}:
        for i in range(1, len(out_targets)):
            if out_targets[i] >= out_targets[i - 1]:
                out_targets[i] = round(out_targets[i - 1] - epsilon, 4)
                out_details[i] = {**out_details[i], "deduped": True}

    return {
        "targets": out_targets,
        "details": out_details,
        "any_snapped": any_snapped,
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
    # Active fat-pct threshold (optimizer may tune nightly).
    active_fat_pct = _get_active_thresholds(db)["path_vol_fat_pct"]

    if vol_pct >= active_fat_pct:
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
