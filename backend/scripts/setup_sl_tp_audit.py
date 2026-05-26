#!/usr/bin/env python3
"""
setup_sl_tp_audit.py — Stop-loss / Target-profit width audit (v19.34.161).

Diagnostic-only. Reads `bot_trades` for closed trades over a lookback
window and produces a per-(style, setup_base) report answering the
operator's question:

    "Are our scalp / intraday setups using too wide a range between
     stop_loss and target_profit?"

For each bucket the script computes:

    n              : trades closed in window
    target_hit_%   : % closed with close_reason ∈ {target_hit, target_1/2/3}
    stop_hit_%     : % closed with close_reason ∈ {stop_loss, stop_*}
    other_%        : % closed any other way (eod, trailing, manual, …)
    avg_th_RR      : theoretical R:R at entry (potential_reward/risk_amount)
    avg_real_R     : actual R-multiple realized
    avg_MFE_R      : average maximum favorable excursion in R-multiples
                      ← key signal: "did price ever get close to target?"
    avg_MAE_R      : average maximum adverse excursion in R-multiples
                      ← key signal: "did price punch through the stop?"
    target_reach   : avg_MFE_R / target_R_avg
                      ← <0.5 means targets are placed too far for typical
                        MFE — operator should tighten T1.
    stop_pressure  : avg_MAE_R / -1.0
                      ← >0.8 means stops are routinely touched — operator
                        may be stopping out on noise; widen or use ATR.
    med_minutes    : median time-in-trade (minutes)
    verdict        : human label, one of:
        ✅ OK                     — RR healthy, target_reach >= 0.7
        🔶 TARGET_TOO_FAR        — avg_MFE_R << target_R AND target_hit_% < 15
        🔶 STOP_TOO_TIGHT        — stop_hit_% > 60 AND avg_MAE_R near -1.0
        🔶 STOP_TOO_LOOSE        — avg_MAE_R << -1.0 (MAE deeper than stop
                                   should ever go — stop is being slipped)
        ⚠️  WIDE_RR_LOW_HIT      — avg_th_RR > 3.0 AND target_hit_% < 20
                                   (the user's exact complaint signature)
        ❓ INSUFFICIENT_DATA     — n < min-n

Usage:
    python3 backend/scripts/setup_sl_tp_audit.py
    python3 backend/scripts/setup_sl_tp_audit.py --days 60
    python3 backend/scripts/setup_sl_tp_audit.py --style scalp
    python3 backend/scripts/setup_sl_tp_audit.py --style intraday --min-n 5
    python3 backend/scripts/setup_sl_tp_audit.py --json

Read-only. Does NOT modify the database.

Output: prints a ranked table to stdout (worst RR-misalignment first)
plus per-bucket detail when --verbose. Use --json for machine
consumption (downstream notebook / Slack bot).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── env loading ──
def _load_env(env_path: Path) -> dict:
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
sys.path.insert(0, str(BACKEND_ROOT))
ENV = _load_env(BACKEND_ROOT / ".env")
MONGO_URL = os.environ.get("MONGO_URL") or ENV.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or ENV.get("DB_NAME")

from services.trade_style_classifier import (  # noqa: E402
    resolve_trade_style, _strip_directional_suffix, TRADE_STYLE_META,
)


# ── close-reason classification ──
TARGET_REASONS = {"target_hit", "target_1", "target_2", "target_3",
                  "take_profit", "tp_hit", "scale_out_t1", "scale_out_t2",
                  "scale_out_t3"}
STOP_REASONS = {"stop_loss", "stop_hit", "stop_loss_phantom_recovery",
                "stop_loss_trailing", "trailing_stop", "trailing_stop_hit",
                "stop_loss_breakeven"}


def _is_target_hit(reason: Optional[str]) -> bool:
    if not reason:
        return False
    r = str(reason).lower()
    if r in TARGET_REASONS:
        return True
    return r.startswith("target")


def _is_stop_hit(reason: Optional[str]) -> bool:
    if not reason:
        return False
    r = str(reason).lower()
    if r in STOP_REASONS:
        return True
    return r.startswith("stop")


# ── verdict rules ──
def _verdict(*, n: int, min_n: int, target_hit_pct: float,
             stop_hit_pct: float, avg_th_rr: float, avg_real_r: float,
             avg_mfe_r: float, avg_mae_r: float, target_r_avg: float) -> str:
    if n < min_n:
        return "❓ INSUFFICIENT_DATA"
    # Operator's exact complaint signature.
    if avg_th_rr > 3.0 and target_hit_pct < 20.0:
        return "⚠️  WIDE_RR_LOW_HIT"
    if target_r_avg > 0 and avg_mfe_r / target_r_avg < 0.4 and target_hit_pct < 15.0:
        return "🔶 TARGET_TOO_FAR"
    if stop_hit_pct > 60.0 and avg_mae_r > -1.05:
        return "🔶 STOP_TOO_TIGHT"
    if avg_mae_r < -1.10:
        return "🔶 STOP_TOO_LOOSE"
    return "✅ OK"


# ── main aggregation ──
def analyze(db, *, days: int, style_filter: Optional[str], min_n: int) -> List[Dict[str, Any]]:
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query: Dict[str, Any] = {
        "status": {"$in": ["closed", "CLOSED"]},
        "closed_at": {"$gte": cutoff_iso},
    }

    docs = list(db.bot_trades.find(query, {
        "_id": 0,
        "symbol": 1, "setup_type": 1, "setup_variant": 1,
        "trade_style": 1, "timeframe": 1,
        "entry_price": 1, "fill_price": 1, "stop_price": 1, "target_prices": 1,
        "risk_amount": 1, "potential_reward": 1, "risk_reward_ratio": 1,
        "target_r_multiple": 1,
        "realized_pnl": 1, "net_pnl": 1,
        "close_reason": 1, "created_at": 1, "executed_at": 1, "closed_at": 1,
        "mfe_r": 1, "mae_r": 1, "mfe_pct": 1, "mae_pct": 1,
        "direction": 1, "shares": 1,
    }))

    if not docs:
        return []

    # Bucket by (style, setup_base).
    buckets: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for d in docs:
        style = resolve_trade_style(d)
        if style_filter and style != style_filter:
            continue
        setup_base = _strip_directional_suffix(
            str(d.get("setup_type") or "unknown").lower()
        )
        buckets[(style, setup_base)].append(d)

    results: List[Dict[str, Any]] = []
    for (style, setup_base), rows in buckets.items():
        n = len(rows)

        # Close-reason rates.
        target_hits = sum(1 for r in rows if _is_target_hit(r.get("close_reason")))
        stop_hits   = sum(1 for r in rows if _is_stop_hit(r.get("close_reason")))
        other       = n - target_hits - stop_hits

        # Theoretical RR (from entry).
        rrs = []
        for r in rows:
            risk = r.get("risk_amount") or 0
            reward = r.get("potential_reward") or 0
            if risk > 0 and reward > 0:
                rrs.append(float(reward) / float(risk))
            elif r.get("risk_reward_ratio"):
                rrs.append(float(r["risk_reward_ratio"]))
        avg_th_rr = statistics.fmean(rrs) if rrs else 0.0

        # Realized R (best-effort: derive from entry/stop/exit if r_multiple missing).
        real_rs = []
        for r in rows:
            entry = r.get("fill_price") or r.get("entry_price")
            stop = r.get("stop_price")
            # exit estimated from realized_pnl / shares
            shares = r.get("shares")
            pnl = r.get("realized_pnl") or r.get("net_pnl")
            if entry and stop and shares and pnl is not None:
                try:
                    risk_per_share = abs(float(entry) - float(stop))
                    if risk_per_share > 0:
                        per_share_pnl = float(pnl) / max(int(shares), 1)
                        real_rs.append(per_share_pnl / risk_per_share)
                except Exception:
                    pass
        avg_real_r = statistics.fmean(real_rs) if real_rs else 0.0

        # MFE / MAE in R-multiples (already pre-computed on the trade).
        mfes = [float(r["mfe_r"]) for r in rows if r.get("mfe_r") is not None]
        maes = [float(r["mae_r"]) for r in rows if r.get("mae_r") is not None]
        avg_mfe_r = statistics.fmean(mfes) if mfes else 0.0
        avg_mae_r = statistics.fmean(maes) if maes else 0.0

        # Target R as set at entry (`target_r_multiple` defaulted to 2.0 in BotTrade).
        targets_r = [float(r["target_r_multiple"]) for r in rows
                     if r.get("target_r_multiple") is not None]
        target_r_avg = statistics.fmean(targets_r) if targets_r else 2.0

        # Time-in-trade in minutes (median).
        durations = []
        for r in rows:
            ca = r.get("created_at") or r.get("executed_at")
            cz = r.get("closed_at")
            if ca and cz:
                try:
                    d0 = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
                    d1 = datetime.fromisoformat(str(cz).replace("Z", "+00:00"))
                    durations.append((d1 - d0).total_seconds() / 60.0)
                except Exception:
                    pass
        med_minutes = statistics.median(durations) if durations else None

        target_hit_pct = 100.0 * target_hits / n
        stop_hit_pct = 100.0 * stop_hits / n
        target_reach = (avg_mfe_r / target_r_avg) if target_r_avg > 0 else 0.0
        stop_pressure = abs(avg_mae_r)

        v = _verdict(
            n=n, min_n=min_n,
            target_hit_pct=target_hit_pct, stop_hit_pct=stop_hit_pct,
            avg_th_rr=avg_th_rr, avg_real_r=avg_real_r,
            avg_mfe_r=avg_mfe_r, avg_mae_r=avg_mae_r,
            target_r_avg=target_r_avg,
        )

        results.append({
            "style": style,
            "style_label": TRADE_STYLE_META.get(style, TRADE_STYLE_META["unknown"])["label"],
            "setup": setup_base,
            "n": n,
            "target_hit_pct": round(target_hit_pct, 1),
            "stop_hit_pct":   round(stop_hit_pct,   1),
            "other_pct":      round(100.0 * other / n, 1),
            "avg_th_RR":      round(avg_th_rr, 2),
            "avg_real_R":     round(avg_real_r, 2),
            "avg_MFE_R":      round(avg_mfe_r, 2),
            "avg_MAE_R":      round(avg_mae_r, 2),
            "target_R_avg":   round(target_r_avg, 2),
            "target_reach":   round(target_reach, 2),
            "stop_pressure":  round(stop_pressure, 2),
            "med_minutes":    (round(med_minutes, 1) if med_minutes is not None else None),
            "verdict":        v,
        })

    # Sort: worst verdicts first, then by RR misalignment.
    VERDICT_RANK = {
        "⚠️  WIDE_RR_LOW_HIT": 0,
        "🔶 TARGET_TOO_FAR":   1,
        "🔶 STOP_TOO_TIGHT":   2,
        "🔶 STOP_TOO_LOOSE":   3,
        "✅ OK":               4,
        "❓ INSUFFICIENT_DATA": 5,
    }
    results.sort(key=lambda x: (VERDICT_RANK.get(x["verdict"], 9), -x["n"]))
    return results


# ── pretty printers ──
def print_table(results: List[Dict[str, Any]], days: int) -> None:
    if not results:
        print(f"No closed bot_trades in last {days}d.")
        return
    print()
    print(f"=== SL/TP audit · last {days}d · ranked by RR misalignment ===")
    print()
    print(f"{'Style':<10} {'Setup':<25} {'N':>4} {'TgtHit%':>7} {'StpHit%':>7} {'ThRR':>5} {'RealR':>6} {'MFE_R':>6} {'MAE_R':>6} {'TgtReach':>8} {'Med min':>8}  Verdict")
    print("─" * 130)
    for r in results:
        med = f"{r['med_minutes']}" if r["med_minutes"] is not None else "—"
        print(
            f"{r['style']:<10} {r['setup']:<25} {r['n']:>4} "
            f"{r['target_hit_pct']:>6}% {r['stop_hit_pct']:>6}% "
            f"{r['avg_th_RR']:>5} {r['avg_real_R']:>+6} "
            f"{r['avg_MFE_R']:>+6} {r['avg_MAE_R']:>+6} "
            f"{r['target_reach']:>8} {med:>8}  {r['verdict']}"
        )
    print()
    print("Legend:")
    print("  TgtHit% = % closed via target / take_profit / scale_out")
    print("  StpHit% = % closed via stop / trailing-stop")
    print("  ThRR    = theoretical R:R at entry (potential_reward / risk_amount)")
    print("  RealR   = average realized R-multiple")
    print("  MFE_R   = avg max favorable excursion (in R) — how close did price come to target?")
    print("  MAE_R   = avg max adverse excursion (in R) — how deep into the stop did price go?")
    print("  TgtReach= MFE_R / target_R_avg — <0.5 = target placed too far")
    print()
    print("Actionable verdicts:")
    print("  ⚠️  WIDE_RR_LOW_HIT  → ThRR>3.0 AND TgtHit<20%: scalp/intraday with intraday-swing targets")
    print("                        FIX: shorten T1 / use ATR-aware target placement.")
    print("  🔶 TARGET_TOO_FAR    → MFE_R<<TargetR AND TgtHit<15%: stop loss is fine but target is unreachable")
    print("                        FIX: drop T1 to within 0.5*MFE_R; let scale-outs ladder up.")
    print("  🔶 STOP_TOO_TIGHT    → StpHit>60% AND MAE_R≈-1.0: getting stopped on noise")
    print("                        FIX: widen stop or switch to ATR-anchored stop.")
    print("  🔶 STOP_TOO_LOOSE    → MAE_R<-1.10: stop being slipped (gap-throughs / slippage)")
    print("                        FIX: investigate execution venue / use IOC limits.")


def print_summary_by_style(results: List[Dict[str, Any]]) -> None:
    by_style = defaultdict(list)
    for r in results:
        by_style[r["style"]].append(r)
    print()
    print("=== Roll-up by style ===")
    print()
    for style, rows in by_style.items():
        n_total = sum(x["n"] for x in rows)
        n_actionable = sum(1 for x in rows if x["verdict"].startswith(("⚠️", "🔶")))
        print(f"  {style:<10} {n_total:>4} trades  ·  {len(rows)} setups  ·  {n_actionable} actionable")


def main():
    p = argparse.ArgumentParser(description="SL/TP width audit (read-only).")
    p.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30).")
    p.add_argument("--style", default=None, choices=list(TRADE_STYLE_META.keys()),
                   help="Restrict to one style bucket.")
    p.add_argument("--min-n", type=int, default=5,
                   help="Minimum trade count for a verdict beyond INSUFFICIENT_DATA (default 5).")
    p.add_argument("--json", action="store_true", help="Emit JSON (skips pretty print).")
    args = p.parse_args()

    if not MONGO_URL:
        sys.exit("MONGO_URL not set in env. Aborting.")
    try:
        from pymongo import MongoClient
    except ImportError:
        sys.exit("pymongo not installed — `pip install pymongo` first.")

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    db = client[DB_NAME] if DB_NAME else client.get_default_database()

    results = analyze(db, days=args.days, style_filter=args.style, min_n=args.min_n)

    if args.json:
        print(json.dumps({
            "days": args.days,
            "style_filter": args.style,
            "min_n": args.min_n,
            "n_buckets": len(results),
            "results": results,
        }, indent=2, default=str))
        return

    print_table(results, args.days)
    print_summary_by_style(results)
    actionable = [r for r in results if r["verdict"].startswith(("⚠️", "🔶"))]
    if actionable:
        print()
        print(f"⚠️  {len(actionable)} actionable bucket(s) flagged. Review top entries above.")


if __name__ == "__main__":
    main()
