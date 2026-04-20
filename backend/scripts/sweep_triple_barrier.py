#!/usr/bin/env python3
"""
PT/SL Grid Sweep for Triple-Barrier Labels
============================================
Reference: López de Prado, AFML Ch. 3; Mlfinlab's `labeling.get_events` with `pt_sl`.

For each (setup_type, bar_size, trade_side) combination, sweeps a grid of
pt_atr_mult × sl_atr_mult and picks the combination that:

  1. Produces a BALANCED class distribution (no class < min_pct, no class > max_pct)
  2. Maximizes an "information gain" proxy: distance from uniform (1/3, 1/3, 1/3)
     — WRONG direction: we actually want balance, not skew
     — CORRECT: minimize abs(chi-square from uniform) → pick closest to uniform
  3. Secondary tiebreak: lower FLAT fraction (more tradeable labels)

Persists the chosen config per (setup_type, bar_size, trade_side) into Mongo
collection `triple_barrier_config`. Training workers then read this at label-gen
time via `get_tb_config()`.

Usage:
    PYTHONPATH=backend python backend/scripts/sweep_triple_barrier.py
    PYTHONPATH=backend python backend/scripts/sweep_triple_barrier.py --setup BREAKOUT --bar-size "5 mins"
    PYTHONPATH=backend python backend/scripts/sweep_triple_barrier.py --symbols 200 --dry-run
"""

from __future__ import annotations
import os
import sys
import argparse
import logging
from pathlib import Path

# Ensure backend importable
_BE = Path(__file__).resolve().parents[1]
if str(_BE) not in sys.path:
    sys.path.insert(0, str(_BE))

import numpy as np
from datetime import datetime, timezone
from pymongo import MongoClient

from services.ai_modules.triple_barrier_labeler import triple_barrier_labels, label_to_class_index
from services.ai_modules.triple_barrier_config import save_tb_config

logger = logging.getLogger("sweep_triple_barrier")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Grid to sweep
PT_GRID = [1.5, 2.0, 2.5, 3.0]
SL_GRID = [0.5, 1.0, 1.5, 2.0]
ATR_PERIOD = 14

# Balance requirements
MIN_CLASS_PCT = 0.12   # no class below 12%
MAX_CLASS_PCT = 0.60   # no class above 60%
MIN_EVENTS = 500       # need enough labeled events per sweep cell


def _load_bars(db, symbol: str, bar_size: str, max_bars: int = 5000):
    """Load recent bars for a symbol, oldest first."""
    cursor = db["ib_historical_data"].find(
        {"symbol": symbol, "bar_size": bar_size},
        {"_id": 0, "date": 1, "high": 1, "low": 1, "close": 1},
    ).sort("date", -1).limit(max_bars)
    bars = list(cursor)
    bars.reverse()
    return bars


def _sweep_one(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    max_bars: int, trade_side: str,
) -> dict:
    """Return {(pt, sl): {counts, balance_score}} for all grid cells."""
    results = {}

    # For shorts: negate series so PT/SL roles invert automatically
    if trade_side == "short":
        s_highs = (-lows).astype(np.float64)
        s_lows = (-highs).astype(np.float64)
        s_closes = (-closes).astype(np.float64)
    else:
        s_highs = highs.astype(np.float64)
        s_lows = lows.astype(np.float64)
        s_closes = closes.astype(np.float64)

    for pt in PT_GRID:
        for sl in SL_GRID:
            raw = triple_barrier_labels(
                s_highs, s_lows, s_closes,
                pt_atr_mult=pt, sl_atr_mult=sl,
                max_bars=max_bars, atr_period=ATR_PERIOD,
            )
            cls = np.array([label_to_class_index(int(v)) for v in raw], dtype=np.int64)
            if len(cls) < 1:
                continue
            n_down = float(np.sum(cls == 0)) / len(cls)
            n_flat = float(np.sum(cls == 1)) / len(cls)
            n_up = float(np.sum(cls == 2)) / len(cls)
            # Balance score: chi-square distance from uniform (1/3 each). Lower = better.
            uniform = 1.0 / 3.0
            chi2 = ((n_down - uniform) ** 2 + (n_flat - uniform) ** 2 + (n_up - uniform) ** 2) / uniform
            results[(pt, sl)] = {
                "down": n_down, "flat": n_flat, "up": n_up,
                "n_events": len(cls),
                "balance_score": float(chi2),
            }
    return results


def _pick_best(sweep: dict) -> tuple:
    """Pick PT/SL combo meeting balance constraints with lowest chi-square distance
    from uniform. Tiebreaker: lower FLAT fraction (more tradeable)."""
    eligible = []
    for (pt, sl), m in sweep.items():
        if m["n_events"] < MIN_EVENTS:
            continue
        if min(m["down"], m["flat"], m["up"]) < MIN_CLASS_PCT:
            continue
        if max(m["down"], m["flat"], m["up"]) > MAX_CLASS_PCT:
            continue
        eligible.append((pt, sl, m))
    if not eligible:
        # Fall back to best-effort: lowest balance_score overall
        best = min(sweep.items(), key=lambda kv: kv[1]["balance_score"])
        return best[0][0], best[0][1], best[1], False
    best = min(eligible, key=lambda e: (e[2]["balance_score"], e[2]["flat"]))
    return best[0], best[1], best[2], True


def sweep_setup(
    db, setup_type: str, bar_size: str, trade_side: str,
    symbols: list, max_bars: int, sample_cap: int = 150,
    dry_run: bool = False,
) -> dict:
    """Sweep one (setup_type, bar_size, trade_side) across a symbol sample."""
    agg = {}  # (pt, sl) -> aggregated counts across symbols

    total = min(sample_cap, len(symbols))
    logger.info(f"[{setup_type}/{bar_size}/{trade_side}] sweeping {total} symbols...")

    valid_symbols = 0
    for i, sym in enumerate(symbols[:sample_cap], 1):
        try:
            bars = _load_bars(db, sym, bar_size)
            if len(bars) < 50 + max_bars:
                continue
            highs = np.array([b["high"] for b in bars])
            lows = np.array([b["low"] for b in bars])
            closes = np.array([b["close"] for b in bars])
            per_sym = _sweep_one(highs, lows, closes, max_bars, trade_side)
            for k, m in per_sym.items():
                if k not in agg:
                    agg[k] = {"down_sum": 0, "flat_sum": 0, "up_sum": 0, "n_events": 0}
                agg[k]["down_sum"] += m["down"] * m["n_events"]
                agg[k]["flat_sum"] += m["flat"] * m["n_events"]
                agg[k]["up_sum"] += m["up"] * m["n_events"]
                agg[k]["n_events"] += m["n_events"]
            valid_symbols += 1
            if i % 25 == 0:
                logger.info(f"  processed {i}/{total} ({valid_symbols} valid)")
        except Exception as e:
            logger.debug(f"  {sym} skipped: {e}")
            continue

    if not agg or valid_symbols == 0:
        logger.warning(f"[{setup_type}/{bar_size}/{trade_side}] no data — using defaults")
        return {"chosen_pt": 2.0, "chosen_sl": 1.0, "max_bars": max_bars, "eligible": False}

    # Normalize to fractions
    final = {}
    for k, v in agg.items():
        n = v["n_events"]
        if n == 0:
            continue
        d = v["down_sum"] / n
        f = v["flat_sum"] / n
        u = v["up_sum"] / n
        chi2 = (((d - 1/3) ** 2 + (f - 1/3) ** 2 + (u - 1/3) ** 2) / (1/3))
        final[k] = {"down": d, "flat": f, "up": u, "n_events": n, "balance_score": chi2}

    pt, sl, metrics, eligible = _pick_best(final)
    logger.info(
        f"[{setup_type}/{bar_size}/{trade_side}] CHOSEN pt={pt} sl={sl} max_bars={max_bars} "
        f"→ DOWN={metrics['down']*100:.1f}% FLAT={metrics['flat']*100:.1f}% UP={metrics['up']*100:.1f}% "
        f"balance={metrics['balance_score']:.3f} {'✓' if eligible else '(FALLBACK — no eligible)'}"
    )

    if not dry_run:
        save_tb_config(
            db, setup_type, bar_size, trade_side,
            pt_atr_mult=pt, sl_atr_mult=sl,
            max_bars=max_bars, atr_period=ATR_PERIOD,
            sweep_metrics={**metrics, "eligible": eligible, "symbols_used": valid_symbols},
        )

    return {
        "chosen_pt": pt, "chosen_sl": sl, "max_bars": max_bars,
        "eligible": eligible,
        "dist": {"down": metrics["down"], "flat": metrics["flat"], "up": metrics["up"]},
        "symbols": valid_symbols,
    }


def _get_cached_symbols(db, bar_size: str, min_bars: int = 100, limit: int = 500) -> list:
    """Pull the most-data-rich symbols for a given bar_size."""
    pipeline = [
        {"$match": {"bar_size": bar_size}},
        {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": min_bars}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    try:
        return [d["_id"] for d in db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True)]
    except Exception as e:
        logger.warning(f"symbol query failed: {e}")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", default=None, help="Setup type (default: all)")
    ap.add_argument("--bar-size", default=None, help="Bar size (default: all)")
    ap.add_argument("--side", choices=["long", "short", "both"], default="both")
    ap.add_argument("--symbols", type=int, default=150, help="Symbol cap per sweep")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        # Fall back to backend/.env
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("MONGO_URL="):
                    mongo_url = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("DB_NAME="):
                    os.environ.setdefault("DB_NAME", line.split("=", 1)[1].strip().strip('"'))
    if not mongo_url:
        print("ERROR: MONGO_URL not set. Set it in env or backend/.env")
        sys.exit(1)
    db = MongoClient(mongo_url)[os.environ.get("DB_NAME", "tradecommand")]

    # Load setup profiles
    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES

    targets = []
    for setup, profiles in SETUP_TRAINING_PROFILES.items():
        if args.setup and setup.upper() != args.setup.upper():
            continue
        for prof in profiles:
            if args.bar_size and prof["bar_size"] != args.bar_size:
                continue
            targets.append((setup, prof["bar_size"], prof["forecast_horizon"]))

    if not targets:
        logger.error("No setup/bar_size combos matched filters.")
        sys.exit(2)

    sides = ["long", "short"] if args.side == "both" else [args.side]
    logger.info(f"Running sweep: {len(targets)} profiles × {len(sides)} sides = {len(targets)*len(sides)} combos")

    results_summary = []
    for setup_type, bar_size, fh in targets:
        symbols = _get_cached_symbols(db, bar_size)
        if not symbols:
            logger.warning(f"{setup_type}/{bar_size}: no symbols available — skipping")
            continue
        for side in sides:
            res = sweep_setup(
                db, setup_type, bar_size, side,
                symbols=symbols, max_bars=fh,
                sample_cap=args.symbols, dry_run=args.dry_run,
            )
            results_summary.append({
                "setup": setup_type, "bar_size": bar_size, "side": side,
                **res,
            })

    # Summary table
    logger.info("=" * 100)
    logger.info(f"{'Setup':<18}{'BarSize':<12}{'Side':<7}{'PT':<6}{'SL':<6}{'MaxB':<6}{'DOWN%':<8}{'FLAT%':<8}{'UP%':<8}{'Elig':<6}{'Syms'}")
    logger.info("-" * 100)
    for r in results_summary:
        dist = r.get("dist", {"down": 0, "flat": 0, "up": 0})
        logger.info(
            f"{r['setup']:<18}{r['bar_size']:<12}{r['side']:<7}"
            f"{r['chosen_pt']:<6.1f}{r['chosen_sl']:<6.1f}{r['max_bars']:<6}"
            f"{dist['down']*100:<8.1f}{dist['flat']*100:<8.1f}{dist['up']*100:<8.1f}"
            f"{'✓' if r['eligible'] else '✗':<6}{r.get('symbols', 0)}"
        )
    logger.info("=" * 100)
    logger.info(f"{'DRY RUN — no writes' if args.dry_run else f'Saved {len(results_summary)} configs to Mongo'}")


if __name__ == "__main__":
    main()
