"""reconciled_orphan execution-leak RCA (read-only).

Root-causes the biggest $ leak in the system (~-19R). Hypothesis under test: a
bot-originated trade carrying a REAL entry_context (regime / TQS / original
stop) loses that state on a backend restart or IB reconnect, resurfaces as an
IB-only orphan, and `reconcile_orphan_positions` (position_reconciler.py:1655+)
materializes a brand-new `reconciled_orphan` BotTrade with a SYNTHETIC default
stop (`synthetic_source="default_pct"`, ~2%) + thesis-less entry_context
(regime UNKNOWN) + a fresh OCA. That tight stop then rides to a loss via
`oca_closed_externally_v19_31` (position_manager.py:422).

For every closed `reconciled_orphan` it:
  1. Computes realized clean_R + close_reason.
  2. Finds the PREDECESSOR = most recent NON-artifact bot_trade on the same
     (symbol, direction) whose entry preceded the orphan's entry.
  3. Compares orphan stop% vs predecessor stop% (synthetic stop tighter?).
  4. Measures gap predecessor.closed_at -> orphan.entry (re-adopt-loop signature).
  5. Reports whether predecessor carried recoverable entry_context/regime.

Pure read-model. Writes NOTHING.
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean

logger = logging.getLogger(__name__)

ARTIFACT_SETUPS = {"reconciled_orphan", "reconciled_excess_slice", "imported_from_ib"}


def _fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clean_r(pnl, risk):
    p, ra = _fnum(pnl), _fnum(risk)
    if p is None or ra is None or ra <= 0:
        return None
    return max(-10.0, min(10.0, p / ra))


def _parse_ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _entry_ts(t):
    return (_parse_ts(t.get("entry_time")) or _parse_ts(t.get("executed_at"))
            or _parse_ts(t.get("created_at")))


def _close_ts(t):
    return _parse_ts(t.get("closed_at")) or _parse_ts(t.get("executed_at"))


def _stop_pct(t):
    e = _fnum(t.get("entry_price")) or _fnum(t.get("fill_price"))
    s = _fnum(t.get("stop_price"))
    if not e or not s or e <= 0:
        return None
    return abs(e - s) / e * 100.0


def _has_real_context(t):
    ec = t.get("entry_context")
    if not isinstance(ec, dict) or ec.get("reconciled"):
        return False
    tqs = ec.get("tqs") if isinstance(ec.get("tqs"), dict) else {}
    has_tqs = bool(tqs.get("pillar_scores") or tqs.get("score") or tqs.get("grade"))
    reg = str(t.get("market_regime") or "").strip().upper()
    return has_tqs or reg not in ("", "UNKNOWN")


_PROJ = {"_id": 0, "id": 1, "symbol": 1, "direction": 1, "status": 1,
         "setup_type": 1, "entered_by": 1, "synthetic_source": 1,
         "entry_price": 1, "fill_price": 1, "stop_price": 1,
         "realized_pnl": 1, "risk_amount": 1, "close_reason": 1,
         "market_regime": 1, "entry_context": 1,
         "entry_time": 1, "executed_at": 1, "created_at": 1, "closed_at": 1}


def _pctile(sorted_vals, p):
    if not sorted_vals:
        return None
    i = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return round(sorted_vals[i], 1)


def generate_report(db, days: int = 120, gap_min: int = 120) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "readopt_window_min": gap_min,
    }
    if db is None:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    all_trades = list(db["bot_trades"].find(
        {"$or": [{"closed_at": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]},
        _PROJ))

    # Index non-artifact trades by (symbol, direction) for predecessor lookup.
    by_key = defaultdict(list)
    for t in all_trades:
        if str(t.get("setup_type") or "") in ARTIFACT_SETUPS:
            continue
        key = ((t.get("symbol") or "").upper(), str(t.get("direction") or "").lower())
        by_key[key].append(t)
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    for k in by_key:
        by_key[k].sort(key=lambda x: (_entry_ts(x) or _floor))

    def find_predecessor(orphan):
        key = ((orphan.get("symbol") or "").upper(),
               str(orphan.get("direction") or "").lower())
        oe = _entry_ts(orphan)
        if oe is None:
            return None
        best = None
        for t in by_key.get(key, []):
            te = _entry_ts(t)
            if te is None or te >= oe:
                continue
            best = t  # ascending sort -> last one before oe wins
        return best

    orphans = [t for t in all_trades
               if str(t.get("setup_type") or "") == "reconciled_orphan"
               and str(t.get("status") or "") == "closed"]

    # A. population + leak
    rs, dollars = [], 0.0
    for t in orphans:
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is not None:
            rs.append(r)
        dollars += _fnum(t.get("realized_pnl")) or 0.0
    out["population"] = {
        "n_closed_orphans": len(orphans),
        "total_realized_usd": round(dollars, 2),
        "total_clean_r": round(sum(rs), 2) if rs else 0.0,
        "mean_r": round(mean(rs), 3) if rs else None,
        "n_with_r": len(rs),
        "negative_r_count": sum(1 for x in rs if x < 0),
    }

    # B. close-reason breakdown
    cr = defaultdict(lambda: {"n": 0, "sum_r": 0.0, "sum_usd": 0.0})
    for t in orphans:
        reason = str(t.get("close_reason") or "?")
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        cr[reason]["n"] += 1
        cr[reason]["sum_r"] += r if r is not None else 0.0
        cr[reason]["sum_usd"] += _fnum(t.get("realized_pnl")) or 0.0
    out["close_reasons"] = [
        {"reason": k, "n": d["n"], "sum_r": round(d["sum_r"], 2),
         "sum_usd": round(d["sum_usd"], 0)}
        for k, d in sorted(cr.items(), key=lambda kv: kv[1]["sum_r"])]

    # C. synthetic-source split
    ss = defaultdict(lambda: {"n": 0, "sum_r": 0.0})
    for t in orphans:
        s = str(t.get("synthetic_source") or "unknown")
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        ss[s]["n"] += 1
        ss[s]["sum_r"] += r if r is not None else 0.0
    out["synthetic_source"] = [
        {"source": k, "n": d["n"], "sum_r": round(d["sum_r"], 2)}
        for k, d in sorted(ss.items(), key=lambda kv: kv[1]["sum_r"])]

    # D. predecessor linkage
    linked = recoverable = tighter = no_pred = 0
    gaps = []
    pred_reasons = Counter()
    readopt = []
    for t in orphans:
        pred = find_predecessor(t)
        if pred is None:
            no_pred += 1
            continue
        linked += 1
        if _has_real_context(pred):
            recoverable += 1
        ops, pps = _stop_pct(t), _stop_pct(pred)
        if ops is not None and pps is not None and ops < pps - 0.05:
            tighter += 1
        pc, oe = _close_ts(pred), _entry_ts(t)
        gap = (oe - pc).total_seconds() / 60.0 if (pc and oe) else None
        if gap is not None:
            gaps.append(gap)
        pred_reason = str(pred.get("close_reason") or "?")
        pred_reasons[pred_reason] += 1
        is_external = any(k in pred_reason for k in
                          ("oca_closed_externally", "external", "stop", "phantom"))
        if gap is not None and 0 <= gap <= gap_min and is_external:
            r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
            readopt.append({
                "symbol": t.get("symbol"),
                "gap_min": round(gap, 1),
                "pred_close_reason": pred_reason,
                "orphan_close_reason": str(t.get("close_reason") or "?"),
                "orphan_r": round(r, 2) if r is not None else None,
                "orphan_usd": round(_fnum(t.get("realized_pnl")) or 0.0, 0),
            })
    gaps.sort()
    out["predecessor_linkage"] = {
        "with_predecessor": linked,
        "no_predecessor": no_pred,
        "recoverable_context": recoverable,
        "orphan_stop_tighter_than_predecessor": tighter,
        "gap_min_p10": _pctile(gaps, 0.1),
        "gap_min_p50": _pctile(gaps, 0.5),
        "gap_min_p90": _pctile(gaps, 0.9),
        "gaps_within_window": sum(1 for g in gaps if 0 <= g <= gap_min),
        "gaps_measured": len(gaps),
        "predecessor_close_reasons": [
            {"reason": k, "n": n} for k, n in pred_reasons.most_common()],
    }

    # E. re-adopt-loop core
    loop_r = sum((s["orphan_r"] or 0.0) for s in readopt)
    loop_usd = sum(s["orphan_usd"] for s in readopt)
    out["readopt_loop"] = {
        "n": len(readopt),
        "leak_r": round(loop_r, 2),
        "leak_usd": round(loop_usd, 0),
        "samples": sorted(readopt, key=lambda s: (s["orphan_r"] if s["orphan_r"]
                                                  is not None else 0))[:15],
    }

    out["verdict"] = (
        f"{recoverable}/{len(orphans)} orphans had a predecessor with recoverable "
        f"context; {tighter} got a tighter stop than the original thesis; "
        f"re-adopt-loop core = {len(readopt)} trades / {round(loop_r, 2)}R — the "
        f"portion fixable by re-linking context+stop or refusing a fresh OCA on "
        f"thesis-less re-adopts.")

    # F. fill-race guard events — did the reaper's anti-orphan guards ever fire?
    # If these are ~0 while stale_pending predecessors dominate, the guards are
    # dead (direct-IB unavailable on a pusher-only deployment) → root cause.
    guard = {}
    try:
        for ev in ("pending_fill_attributed", "reaper_skip_likely_filled",
                   "reaper_skip_working_order"):
            guard[ev] = db["state_integrity_events"].count_documents(
                {"event": ev, "ts": {"$gte": cutoff}})
    except Exception as e:  # collection may be absent
        guard["error"] = str(e)
    out["fill_race_guard_events"] = guard
    return out


async def generate_diagnostics(db) -> dict:
    """Read-only runtime diagnostics for the orphan-leak fix decision.

    Reveals WHY the anti-orphan guards aren't firing on a pusher-only DGX:
    direct-IB connectivity, whether get_positions()/get_open_orders() return
    data, the pusher position snapshot, the fill-tape (ib_executions) health,
    and the relevant env flags. Calls are best-effort + guarded — never raises.
    """
    import os
    out = {"checked_at": datetime.now(timezone.utc).isoformat()}

    # 1) env flags that govern the guards / order path.
    out["env"] = {k: os.environ.get(k) for k in (
        "BOT_ORDER_PATH",
        "PENDING_FILL_ATTRIBUTION_ENABLED",
        "PENDING_REAPER_ENABLED",
        "PENDING_REAPER_CANCEL_FIRST",
        "PENDING_REAPER_MAX_AGE_S",
        "PENDING_REAPER_INTERVAL_S",
        "REAPER_PUSHER_FALLBACK",
        "IB_DIRECT_HOST", "IB_DIRECT_PORT", "IB_DIRECT_CLIENT_ID",
        "V320H_OCA_FIX_POLICY",
    )}

    # 2) direct-IB live read-only probes (the guards depend on these).
    ibd_info = {"available": False, "connected": False}
    try:
        from services.ib_direct_service import get_ib_direct_service
        ibd = get_ib_direct_service()
        if ibd is not None:
            ibd_info["available"] = bool(getattr(ibd, "is_available", lambda: True)())
            try:
                ibd_info["connected"] = bool(await ibd.ensure_connected())
            except Exception as e:
                ibd_info["connect_error"] = str(e)[:160]
            if ibd_info["connected"]:
                try:
                    pos = await ibd.get_positions()
                    ibd_info["get_positions_count"] = len(pos or [])
                except Exception as e:
                    ibd_info["get_positions_error"] = str(e)[:160]
                try:
                    oo = await ibd.get_open_orders()
                    ibd_info["get_open_orders_count"] = len(oo or [])
                except Exception as e:
                    ibd_info["get_open_orders_error"] = str(e)[:160]
                try:
                    ibd_info["session_fills_count"] = len(ibd._ib.fills() or [])
                except Exception:
                    pass
    except Exception as e:
        ibd_info["error"] = str(e)[:160]
    out["ib_direct"] = ibd_info

    # 3) pusher position snapshot (source of truth on the DGX).
    pusher = {}
    try:
        from routers.ib import _pushed_ib_data
        pos = (_pushed_ib_data or {}).get("positions") or []
        pusher["pushed_positions_count"] = len(pos)
        pusher["pushed_last_update"] = (_pushed_ib_data or {}).get("last_update")
        pusher["sample_symbols"] = [
            (p.get("symbol") or p.get("Symbol")) for p in pos[:8]]
    except Exception as e:
        pusher["error"] = str(e)[:160]
    try:
        snap = db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0})
        if snap:
            pusher["snapshot_positions_count"] = len((snap or {}).get("positions") or [])
            pusher["snapshot_last_update"] = (snap or {}).get("last_update")
    except Exception:
        pass
    out["pusher"] = pusher

    # 4) fill tape (ib_executions) health.
    fills = {}
    try:
        from services.ib_executions_persister import get_persister_stats
        fills["persister_stats"] = get_persister_stats()
    except Exception:
        pass
    try:
        coll = db["ib_executions"]
        fills["total"] = coll.count_documents({})
        wk = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        fills["last_7d"] = coll.count_documents({"time": {"$gte": wk}})
        latest = list(coll.find({}, {"_id": 0, "time": 1}).sort("time", -1).limit(1))
        fills["latest_time"] = latest[0]["time"] if latest else None
    except Exception as e:
        fills["error"] = str(e)[:160]
    out["fill_tape"] = fills

    # 5) for recent orphans: was there a real fill near the orphan's entry?
    #    (proves the position filled; the gap is attribution, not the fill.)
    near = {"checked": 0, "with_fill_within_15m": 0, "samples": []}
    try:
        recent_orphans = list(db["bot_trades"].find(
            {"setup_type": "reconciled_orphan", "status": "closed"},
            {"_id": 0, "symbol": 1, "entry_time": 1, "executed_at": 1,
             "created_at": 1}).sort("created_at", -1).limit(20))
        for o in recent_orphans:
            oe = _entry_ts(o)
            sym = (o.get("symbol") or "").upper()
            if not oe or not sym:
                continue
            near["checked"] += 1
            lo = (oe - timedelta(minutes=15)).isoformat()
            hi = (oe + timedelta(minutes=15)).isoformat()
            n = db["ib_executions"].count_documents(
                {"symbol": sym, "time": {"$gte": lo, "$lte": hi}})
            if n > 0:
                near["with_fill_within_15m"] += 1
            if len(near["samples"]) < 10:
                near["samples"].append({"symbol": sym, "orphan_entry": oe.isoformat(),
                                        "ib_fills_within_15m": n})
    except Exception as e:
        near["error"] = str(e)[:160]
    out["orphan_fill_corroboration"] = near
    return out
