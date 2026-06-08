"""
regime_expectancy_calibrator.py  (T6, fork 2026-06)
===================================================
DATA-DRIVEN per-(setup × direction × regime_band) expectancy suppression.

WHY: the bot bleeds because counter-trend setups (vwap_fade_short etc.) get
steamrolled in strong uptrends while with-trend setups thrive (see
memory/SENTCOM_INVESTIGATION_2026-06-fork.md). A coarse family rule would kill
winners (gap_fade is +R in BULL, daily_breakout +1.55R). So we suppress per cell,
straight from realized expectancy, and let the table refresh itself.

HOW:
  clean_R = realized_pnl / risk_amount  (risk_amount>0, |R|<=10, artifacts excluded)
  regime band from the regime_score STORED ON THE TRADE (its regime at entry):
      BULL>60 | NEUT 46-60 | BEAR<=45
  Each trade is EXPONENTIALLY TIME-WEIGHTED by how recently it closed
  (half-life ~60d, capped at 180d of history) so the cell mean reacts to fresh
  edge-decay without the sample-starvation of a hard short window.

  cell = (canonical_setup, direction, band)  — primary
       → falls back to (canonical_setup, band) when the direction cell is thin.

  Suppression (only ever DOWNGRADES, never promotes):
      weighted_mean_R <= HARD_R (-0.50)  and  eff_n >= MIN_EFF_N  -> SKIP
      weighted_mean_R <= SOFT_R (-0.10)  and  eff_n >= MIN_EFF_N  -> REDUCE (x0.4)
      otherwise (or thin sample)                                  -> NONE (trust gate)

  Short(30d)/Mid(90d)/All-time means are stored as DISPLAY-ONLY diagnostics so the
  operator can eyeball edge-decay — they do NOT drive the decision in v1.

ROLLOUT: writes to `setup_regime_expectancy` collection (_id="current"). Mode lives
in the same collection (_id="config", {mode: "shadow"|"active"}); default "shadow".
Refreshed daily by trading_scheduler. Pure helpers (band_of / clean_r /
decide_suppression) are unit-tested without a DB.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.setup_taxonomy import canonicalize

logger = logging.getLogger(__name__)

# ── tunables (operator-signed-off, fork 2026-06) ───────────────────────────
HALF_LIFE_DAYS = 60.0
WINDOW_DAYS = 180
MIN_EFF_N = 25.0          # minimum effective (weighted) sample to act on a cell
HARD_R = -0.50            # weighted_mean_R <= this -> SKIP
SOFT_R = -0.12            # weighted_mean_R <= this -> REDUCE (was -0.10; raised to
                          # -0.12 so breakeven/high-value cells at ~-0.10
                          # (rs_leader_break, squeeze|long) are NOT trimmed —
                          # operator sign-off, fork 2026-06)
REDUCE_MULT = 0.4         # position multiplier applied on a soft suppression

# Artifacts / non-edge rows excluded from expectancy.
_ARTIFACTS = {"reconciled_orphan", "reconciled_excess_slice", "imported_from_ib"}

COLLECTION = "setup_regime_expectancy"


def _fnum(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN guard
    except Exception:
        return None


def clean_r(pnl, risk_amount) -> Optional[float]:
    """clean_R = realized_pnl / risk_amount, bounded to |R|<=10."""
    p = _fnum(pnl)
    ra = _fnum(risk_amount)
    if p is None or not ra or ra <= 0:
        return None
    r = p / ra
    if not (-10.0 <= r <= 10.0):
        return None
    return r


def band_of(score) -> Optional[str]:
    """Bucket a regime_score into BULL>60 / NEUT46-60 / BEAR<=45."""
    s = _fnum(score)
    if s is None:
        return None
    if s > 60:
        return "BULL>60"
    if s >= 46:
        return "NEUT46-60"
    return "BEAR<=45"


def norm_direction(d) -> str:
    return "short" if str(d or "").lower().startswith("short") else "long"


def _parse_dt(doc: Dict[str, Any]) -> Optional[datetime]:
    """Best-effort close timestamp for recency weighting (closed_at preferred)."""
    for f in ("closed_at", "exit_time", "entry_time", "created_at", "timestamp"):
        v = doc.get(f)
        if not v:
            continue
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    # last resort: ObjectId generation time
    oid = doc.get("_id")
    try:
        return oid.generation_time  # type: ignore[attr-defined]
    except Exception:
        return None


def _weight(age_days: float) -> float:
    """Exponential recency weight: 0.5 ** (age/half_life)."""
    if age_days < 0:
        age_days = 0.0
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def compute_table(rows, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Pure: build the expectancy table from an iterable of bot_trade dicts.

    Each row needs: realized_pnl, risk_amount, setup_type, direction, regime_score,
    and a close timestamp (closed_at/exit_time/...). Returns the persisted doc body
    (without _id) — see module docstring for the schema.
    """
    now = now or datetime.now(timezone.utc)

    # cell_key -> {"wsum": Σw, "wr": Σ(w*R), "raw_n": int,
    #              "d30":[R..], "d90":[R..], "all":[R..]}
    cells: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"wsum": 0.0, "wr": 0.0, "raw_n": 0, "d30": [], "d90": [], "all": []}
    )

    for r in rows:
        st = str(r.get("setup_type", "") or "")
        if not st or st in _ARTIFACTS or r.get("synthetic_source"):
            continue
        cr = clean_r(r.get("realized_pnl"), r.get("risk_amount"))
        if cr is None:
            continue
        b = band_of(r.get("regime_score"))
        if b is None:
            continue
        dt = _parse_dt(r)
        if dt is None:
            continue
        age = (now - dt).total_seconds() / 86400.0
        if age > WINDOW_DAYS:
            continue
        w = _weight(age)
        canon = canonicalize(st)
        direction = norm_direction(r.get("direction"))

        for key in (f"{canon}|{direction}|{b}", f"{canon}|{b}"):
            c = cells[key]
            c["wsum"] += w
            c["wr"] += w * cr
            c["raw_n"] += 1
            c["all"].append(cr)
            if age <= 30:
                c["d30"].append(cr)
            if age <= 90:
                c["d90"].append(cr)

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    out_cells: Dict[str, Any] = {}
    for key, c in cells.items():
        wsum = c["wsum"]
        out_cells[key] = {
            "weighted_mean_r": round(c["wr"] / wsum, 4) if wsum > 0 else None,
            "eff_n": round(wsum, 2),
            "raw_n": c["raw_n"],
            "diag": {  # DISPLAY-ONLY term structure (not used by decide_suppression)
                "r_30d": _mean(c["d30"]), "n_30d": len(c["d30"]),
                "r_90d": _mean(c["d90"]), "n_90d": len(c["d90"]),
                "r_all": _mean(c["all"]), "n_all": len(c["all"]),
            },
        }

    return {
        "generated_at": now.isoformat(),
        "params": {
            "half_life_days": HALF_LIFE_DAYS,
            "window_days": WINDOW_DAYS,
            "min_eff_n": MIN_EFF_N,
            "hard_r": HARD_R,
            "soft_r": SOFT_R,
            "reduce_mult": REDUCE_MULT,
        },
        "cell_count": len(out_cells),
        "cells": out_cells,
    }


def decide_suppression(
    cells: Dict[str, Any],
    canonical_setup: str,
    direction: str,
    band: Optional[str],
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure decision: should this (setup, direction, band) be suppressed?

    Returns {action: 'SKIP'|'REDUCE'|'NONE', cell_mean_r, eff_n, matched_key, reason}.
    Only ever downgrades; positive/thin cells -> NONE (trust the normal gate).
    """
    p = params or {}
    min_eff_n = p.get("min_eff_n", MIN_EFF_N)
    hard_r = p.get("hard_r", HARD_R)
    soft_r = p.get("soft_r", SOFT_R)

    none = {"action": "NONE", "cell_mean_r": None, "eff_n": 0.0,
            "matched_key": None, "reason": "insufficient data"}
    if not cells or not band:
        return none

    direction = norm_direction(direction)
    for key in (f"{canonical_setup}|{direction}|{band}", f"{canonical_setup}|{band}"):
        cell = cells.get(key)
        if not cell:
            continue
        eff_n = cell.get("eff_n") or 0.0
        r = cell.get("weighted_mean_r")
        if r is None or eff_n < min_eff_n:
            continue
        if r <= hard_r:
            return {"action": "SKIP", "cell_mean_r": r, "eff_n": eff_n,
                    "matched_key": key,
                    "reason": f"weighted_mean_R {r:+.2f} <= {hard_r} (n={eff_n:.0f})"}
        if r <= soft_r:
            return {"action": "REDUCE", "cell_mean_r": r, "eff_n": eff_n,
                    "matched_key": key,
                    "reason": f"weighted_mean_R {r:+.2f} <= {soft_r} (n={eff_n:.0f})"}
        return {"action": "NONE", "cell_mean_r": r, "eff_n": eff_n,
                "matched_key": key, "reason": f"weighted_mean_R {r:+.2f} ok"}
    return none


class RegimeExpectancyCalibrator:
    """Refreshes the expectancy table and the mode flag in MongoDB."""

    def __init__(self, db=None):
        self._db = db

    def set_db(self, db):
        self._db = db

    def refresh(self) -> Dict[str, Any]:
        """Recompute from bot_trades and upsert _id='current'. Read-only on input."""
        if self._db is None:
            return {"success": False, "reason": "no db"}
        rows = list(self._db.bot_trades.find(
            {"status": "closed"},
            {"_id": 1, "realized_pnl": 1, "risk_amount": 1, "setup_type": 1,
             "direction": 1, "regime_score": 1, "synthetic_source": 1,
             "closed_at": 1, "exit_time": 1, "entry_time": 1,
             "created_at": 1, "timestamp": 1},
        ))
        table = compute_table(rows)
        table["_id"] = "current"
        try:
            self._db[COLLECTION].update_one(
                {"_id": "current"}, {"$set": table}, upsert=True
            )
            logger.info(
                f"Regime expectancy refreshed: {table['cell_count']} cells "
                f"from {len(rows)} closed trades"
            )
            return {"success": True, "cell_count": table["cell_count"],
                    "trades": len(rows)}
        except Exception as e:
            logger.error(f"Failed to persist regime expectancy: {e}")
            return {"success": False, "reason": str(e)}

    def load(self) -> Optional[Dict[str, Any]]:
        if self._db is None:
            return None
        try:
            doc = self._db[COLLECTION].find_one({"_id": "current"})
            return doc or None
        except Exception as e:
            logger.debug(f"Could not load regime expectancy: {e}")
            return None

    def load_mode(self) -> str:
        """Return 'shadow' (default) or 'active'."""
        if self._db is None:
            return "shadow"
        try:
            cfg = self._db[COLLECTION].find_one({"_id": "config"})
            mode = (cfg or {}).get("mode", "shadow")
            return "active" if mode == "active" else "shadow"
        except Exception:
            return "shadow"

    def set_mode(self, mode: str) -> str:
        mode = "active" if mode == "active" else "shadow"
        if self._db is not None:
            self._db[COLLECTION].update_one(
                {"_id": "config"},
                {"$set": {"mode": mode, "_id": "config",
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
        return mode


_calibrator: Optional[RegimeExpectancyCalibrator] = None


def init_regime_expectancy_calibrator(db=None) -> RegimeExpectancyCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = RegimeExpectancyCalibrator(db=db)
    elif db is not None:
        _calibrator.set_db(db)
    return _calibrator
