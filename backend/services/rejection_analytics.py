"""
Rejection analytics — surfaces "which gates are over-tight?" from the
new `sentcom_thoughts` rejection feed (shipped 2026-04-29 afternoon-4).

The existing `multiplier_threshold_optimizer` tunes smart_levels
thresholds based on `bot_trades` lift; `gate_calibrator` tunes
confidence-gate thresholds based on `confidence_gate_log` outcomes.
Neither consumes the rich rejection-narrative data we now persist.

This service fills that gap. Aggregates rejection events by reason_code
over a window, cross-references with subsequent `bot_trades` for the
same (symbol, setup_type) tuple, and reports:

  - How often each gate code fires (volume per rejection reason)
  - How often a rejected setup later trades successfully despite the
    rejection (signal that the gate may be over-tight)

Output is read-only, designed to feed back into operator review +
future automated calibration. Wire-up to live calibration is a
follow-on PR — first we need a few weeks of data + observation to
confirm the signal is stable before touching live thresholds.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REJECTION_KINDS = {"rejection", "skip"}


def _normalise_setup(s: Optional[str]) -> str:
    if not s:
        return "unknown"
    s = str(s)
    for suf in ("_long", "_short"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def compute_rejection_analytics(
    db,
    *,
    days: int = 7,
    min_count: int = 3,
) -> Dict[str, Any]:
    """Compute rejection analytics from `sentcom_thoughts` + `bot_trades`.

    Args:
        db: Mongo handle (the app's main DB)
        days: lookback window
        min_count: skip reason_codes that fired fewer times than this

    Returns:
        {
          "success": True,
          "window_days": days,
          "total_rejections": int,
          "by_reason_code": [
            {
              "reason_code": "tqs_too_low",
              "count": 47,
              "symbols": ["NVDA", "AAPL", ...] (top 10),
              "post_rejection_trades": 12,  # times we later traded same
                                             # (symbol, setup) within 24h
              "post_rejection_wins": 8,
              "post_rejection_win_rate_pct": 66.7,
              "verdict": "gate_potentially_overtight" | "gate_calibrated" | "insufficient_data",
            },
            ...
          ],
          "calibration_hints": [...]
        }

    Never raises — returns {success: False, error} on any failure.
    """
    if db is None:
        return {"success": False, "error": "db_unavailable"}

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days or 7))
        cursor = db["sentcom_thoughts"].find(
            {
                "created_at": {"$gte": cutoff},
                "kind": {"$in": list(REJECTION_KINDS)},
            },
            {"_id": 0, "symbol": 1, "metadata": 1, "created_at": 1},
        )
        rows = list(cursor)
    except Exception as e:
        logger.debug(f"rejection_analytics: thoughts query failed: {e}")
        return {"success": False, "error": str(e)[:120]}

    if not rows:
        return {
            "success": True,
            "window_days": days,
            "total_rejections": 0,
            "by_reason_code": [],
            "calibration_hints": [],
        }

    # Group by reason_code
    by_code: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        meta = r.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        code = (meta.get("reason_code") or "unknown").lower()
        symbol = (r.get("symbol") or "").upper()
        setup = _normalise_setup(meta.get("setup_type"))
        bucket = by_code.setdefault(code, {
            "count": 0,
            "symbols": {},
            "rejections": [],
        })
        bucket["count"] += 1
        if symbol:
            bucket["symbols"][symbol] = bucket["symbols"].get(symbol, 0) + 1
        bucket["rejections"].append({
            "symbol": symbol,
            "setup": setup,
            "ts": r.get("created_at"),
        })

    # Cross-reference with bot_trades for "post-rejection trades"
    try:
        trade_cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days or 7) + 1)).isoformat()
        trade_cursor = db["bot_trades"].find(
            {
                "status": {"$in": ["closed", "open"]},
                "executed_at": {"$gte": trade_cutoff},
            },
            {
                "_id": 0, "symbol": 1, "setup_type": 1,
                "executed_at": 1, "realized_pnl": 1, "net_pnl": 1,
                "close_reason": 1,
            },
        )
        trades = list(trade_cursor)
    except Exception as e:
        logger.debug(f"rejection_analytics: bot_trades query failed: {e}")
        trades = []

    by_sym_setup: Dict[str, List[Dict[str, Any]]] = {}
    for t in trades:
        key = f"{(t.get('symbol') or '').upper()}:{_normalise_setup(t.get('setup_type'))}"
        by_sym_setup.setdefault(key, []).append(t)

    buckets: List[Dict[str, Any]] = []
    hints: List[str] = []
    for code, b in by_code.items():
        # Count unique post-rejection trades (each trade can only count
        # once even if multiple rejections precede it).
        post_trade_ids: set = set()
        post_winning_trade_ids: set = set()
        for rej in b["rejections"]:
            try:
                ts = rej.get("ts")
                if isinstance(ts, datetime):
                    rej_time = ts
                else:
                    rej_time = datetime.fromisoformat(
                        str(ts).replace("Z", "+00:00")
                    )
                # Mongo can return naive datetimes (mongomock; older drivers
                # without tz_aware=True). Normalise to UTC-aware so the
                # comparisons below don't crash.
                if rej_time.tzinfo is None:
                    rej_time = rej_time.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            window_end = rej_time + timedelta(hours=24)
            key = f"{rej['symbol']}:{rej['setup']}"
            for t in by_sym_setup.get(key, []):
                exec_str = t.get("executed_at") or ""
                try:
                    exec_dt = datetime.fromisoformat(exec_str.replace("Z", "+00:00"))
                    if exec_dt.tzinfo is None:
                        exec_dt = exec_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if rej_time <= exec_dt <= window_end:
                    tid = f"{key}:{exec_str}"
                    post_trade_ids.add(tid)
                    pnl = t.get("net_pnl") or t.get("realized_pnl") or 0
                    if pnl and float(pnl) > 0:
                        post_winning_trade_ids.add(tid)
        post_trades = len(post_trade_ids)
        post_wins = len(post_winning_trade_ids)

        if b["count"] < min_count:
            verdict = "insufficient_data"
        elif post_trades < 5:
            verdict = "insufficient_data"
        else:
            wr = post_wins / post_trades
            if wr >= 0.65:
                verdict = "gate_potentially_overtight"
                hints.append(
                    f"⚠️ '{code}' fired {b['count']}× but post-rejection win rate is "
                    f"{int(wr*100)}% ({post_wins}/{post_trades}) — gate may be over-tight"
                )
            elif wr >= 0.45:
                verdict = "gate_borderline"
            else:
                verdict = "gate_calibrated"

        top_syms = sorted(b["symbols"].items(), key=lambda kv: -kv[1])[:10]
        buckets.append({
            "reason_code": code,
            "count": b["count"],
            "symbols": [s for s, _ in top_syms],
            "post_rejection_trades": post_trades,
            "post_rejection_wins": post_wins,
            "post_rejection_win_rate_pct": (
                round(post_wins / post_trades * 100, 1)
                if post_trades else None
            ),
            "verdict": verdict,
        })

    buckets.sort(key=lambda x: -x["count"])

    return {
        "success": True,
        "window_days": days,
        "total_rejections": sum(b["count"] for b in buckets),
        "by_reason_code": buckets,
        "calibration_hints": hints,
    }
