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
                   "reaper_skip_working_order",
                   "orphan_relink_observe", "orphan_relinked_reaped_pending"):
            guard[ev] = db["state_integrity_events"].count_documents(
                {"event": ev, "ts": {"$gte": cutoff}})
    except Exception as e:  # collection may be absent
        guard["error"] = str(e)
    out["fill_race_guard_events"] = guard

    # G. monthly trend — is the leak tapering (e.g. after switching to
    # BOT_ORDER_PATH=direct) or still active? Buckets orphans by entry month.
    months = defaultdict(lambda: {"n": 0, "leak_r": 0.0, "leak_usd": 0.0})
    for t in orphans:
        oe = _entry_ts(t)
        key = oe.strftime("%Y-%m") if oe else "unknown"
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        months[key]["n"] += 1
        months[key]["leak_r"] += r if r is not None else 0.0
        months[key]["leak_usd"] += _fnum(t.get("realized_pnl")) or 0.0
    out["monthly_trend"] = [
        {"month": k, "n": v["n"], "leak_r": round(v["leak_r"], 2),
         "leak_usd": round(v["leak_usd"], 0)}
        for k, v in sorted(months.items())]

    # H. relink backtest — replay the v405 match criteria against historical
    # orphans so the benefit is quantifiable BEFORE enabling fix. Splits by
    # real vs learning_only (0.1x exploration) trades and tests window
    # sensitivity, since the reap->orphan gap is often > 90m.
    def _is_learning(doc):
        if doc.get("learning_only") is True:
            return True
        ec = doc.get("entry_context")
        return isinstance(ec, dict) and ec.get("learning_only") is True

    def _relink_stats(window_min):
        st = {"window_min": window_min,
              "matchable_real": 0, "matchable_learning": 0,
              "addressable_real": 0, "addressable_learning": 0,
              "addressable_leak_r_real": 0.0, "addressable_leak_usd_real": 0.0,
              "addressable_leak_r_learning": 0.0,
              "samples": []}
        widen_acc = []
        for t in orphans:
            oe = _entry_ts(t)
            oentry = _fnum(t.get("entry_price")) or _fnum(t.get("fill_price"))
            odir = str(t.get("direction") or "").lower()
            if oe is None or not oentry:
                continue
            key = ((t.get("symbol") or "").upper(), odir)
            try:
                qsh = int(t.get("shares") or 0)
            except (TypeError, ValueError):
                qsh = 0
            best = None
            for c in by_key.get(key, []):
                if not str(c.get("close_reason") or "").startswith("stale_pending"):
                    continue
                cc = _close_ts(c)
                if cc is None:
                    continue
                gap = (oe - cc).total_seconds() / 60.0
                if not (0 <= gap <= window_min):
                    continue
                psp = _fnum(c.get("stop_price"))
                if not psp or psp <= 0:
                    continue
                if odir == "long" and not (psp < oentry):
                    continue
                if odir == "short" and not (psp > oentry):
                    continue
                try:
                    osh = int(c.get("original_shares") or c.get("shares") or 0)
                except (TypeError, ValueError):
                    osh = 0
                if osh > 0 and qsh > 0 and not (0.5 <= qsh / osh <= 2.0):
                    continue
                best = c
                break  # by_key is time-ascending; last valid before entry stays
            if best is None:
                continue
            learn = _is_learning(best)
            if learn:
                st["matchable_learning"] += 1
            else:
                st["matchable_real"] += 1
            psp = _fnum(best.get("stop_price"))
            osp = _fnum(t.get("stop_price"))
            widen = None
            if osp and oentry and psp:
                syn = abs(oentry - osp)
                if syn > 0:
                    widen = round((abs(oentry - psp) - syn) / syn * 100.0, 1)
                    if not learn:
                        widen_acc.append(widen)
            reason = str(t.get("close_reason") or "")
            r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
            is_loss_stop = (("oca_closed_externally" in reason or "external" in reason
                             or "stop" in reason) and (r is not None and r < 0))
            if is_loss_stop:
                if learn:
                    st["addressable_learning"] += 1
                    st["addressable_leak_r_learning"] += r
                else:
                    st["addressable_real"] += 1
                    st["addressable_leak_r_real"] += r
                    st["addressable_leak_usd_real"] += _fnum(t.get("realized_pnl")) or 0.0
                if len(st["samples"]) < 12:
                    st["samples"].append({
                        "symbol": t.get("symbol"), "learning_only": learn,
                        "setup": best.get("setup_type"),
                        "orphan_stop": osp, "original_stop": psp,
                        "stop_widening_pct": widen,
                        "orphan_r": round(r, 2), "close_reason": reason[:26]})
        st["addressable_leak_r_real"] = round(st["addressable_leak_r_real"], 2)
        st["addressable_leak_usd_real"] = round(st["addressable_leak_usd_real"], 0)
        st["addressable_leak_r_learning"] = round(st["addressable_leak_r_learning"], 2)
        st["avg_stop_widening_pct_real"] = (round(sum(widen_acc) / len(widen_acc), 1)
                                            if widen_acc else None)
        return st

    out["relink_backtest"] = _relink_stats(gap_min)
    out["relink_window_sensitivity"] = [
        {"window_min": w,
         "matchable_real": s["matchable_real"],
         "matchable_learning": s["matchable_learning"],
         "addressable_real": s["addressable_real"],
         "addressable_leak_r_real": s["addressable_leak_r_real"]}
        for w, s in ((w, _relink_stats(w)) for w in (90, 360, 1440, 2880))]

    # I. leak concentration — where the -R actually lives (the re-link backtest
    # proved the leak is NOT recoverable-stop; this finds the real concentration).
    conc = {}
    # winners vs losers
    win_r = loss_r = 0.0
    n_win = n_loss = 0
    for t in orphans:
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        if r >= 0:
            n_win += 1
            win_r += r
        else:
            n_loss += 1
            loss_r += r
    conc["winners_vs_losers"] = {
        "n_winners": n_win, "sum_win_r": round(win_r, 2),
        "n_losers": n_loss, "sum_loss_r": round(loss_r, 2)}
    # synthetic_source x month
    sm = defaultdict(lambda: {"n": 0, "leak_r": 0.0})
    for t in orphans:
        oe = _entry_ts(t)
        mo = oe.strftime("%Y-%m") if oe else "?"
        src = str(t.get("synthetic_source") or "unknown")
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        sm[(src, mo)]["n"] += 1
        sm[(src, mo)]["leak_r"] += r if r is not None else 0.0
    conc["by_source_month"] = [
        {"source": k[0], "month": k[1], "n": v["n"], "leak_r": round(v["leak_r"], 2)}
        for k, v in sorted(sm.items())]
    # hold-duration buckets (entry -> close)
    buckets = [("<5m", 0, 5), ("5-30m", 5, 30), ("30m-2h", 30, 120),
               ("2h-1d", 120, 1440), (">1d", 1440, 10 ** 9)]
    hb = {b[0]: {"n": 0, "leak_r": 0.0} for b in buckets}
    hb["unknown"] = {"n": 0, "leak_r": 0.0}
    for t in orphans:
        oe, oc = _entry_ts(t), _close_ts(t)
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        rr = r if r is not None else 0.0
        if not oe or not oc:
            hb["unknown"]["n"] += 1
            hb["unknown"]["leak_r"] += rr
            continue
        mins = (oc - oe).total_seconds() / 60.0
        for name, lo, hi in buckets:
            if lo <= mins < hi:
                hb[name]["n"] += 1
                hb[name]["leak_r"] += rr
                break
    conc["hold_duration"] = [
        {"bucket": k, "n": v["n"], "leak_r": round(v["leak_r"], 2)}
        for k, v in hb.items() if v["n"] > 0]
    # has-predecessor split
    hp = {"with_pred": {"n": 0, "leak_r": 0.0}, "no_pred": {"n": 0, "leak_r": 0.0}}
    for t in orphans:
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        rr = r if r is not None else 0.0
        k = "with_pred" if find_predecessor(t) is not None else "no_pred"
        hp[k]["n"] += 1
        hp[k]["leak_r"] += rr
    conc["predecessor_split"] = {
        k: {"n": v["n"], "leak_r": round(v["leak_r"], 2)} for k, v in hp.items()}
    # worst 15 offenders with full detail
    scored = []
    for t in orphans:
        r = _clean_r(t.get("realized_pnl"), t.get("risk_amount"))
        if r is None:
            continue
        oe, oc = _entry_ts(t), _close_ts(t)
        hold = round((oc - oe).total_seconds() / 60.0, 1) if (oe and oc) else None
        e = _fnum(t.get("entry_price")) or _fnum(t.get("fill_price"))
        s = _fnum(t.get("stop_price"))
        spct = round(abs(e - s) / e * 100.0, 2) if (e and s and e > 0) else None
        scored.append({
            "symbol": t.get("symbol"), "r": round(r, 2),
            "usd": round(_fnum(t.get("realized_pnl")) or 0.0, 0),
            "entry": e, "stop": s, "stop_pct": spct, "hold_min": hold,
            "synthetic_source": t.get("synthetic_source"),
            "close_reason": str(t.get("close_reason") or "")[:26]})
    conc["worst_15"] = sorted(scored, key=lambda x: x["r"])[:15]
    out["leak_concentration"] = conc
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

    # 6) what do reaped stale_pending rows actually CONTAIN? (decides whether the
    #    v405 re-link can recover a real stop, or whether we need another source.)
    sp_sample = {"count": 0, "with_stop_price": 0, "with_targets": 0,
                 "with_entry_context": 0, "samples": []}
    try:
        rows = list(db["bot_trades"].find(
            {"close_reason": {"$regex": "^stale_pending"}},
            {"_id": 0, "id": 1, "symbol": 1, "direction": 1, "status": 1,
             "setup_type": 1, "stop_price": 1, "target_prices": 1,
             "entry_price": 1, "fill_price": 1, "original_shares": 1, "shares": 1,
             "market_regime": 1, "entry_context": 1, "close_reason": 1,
             "reaped_at": 1, "closed_at": 1}).sort("reaped_at", -1).limit(40))
        for d in rows:
            sp_sample["count"] += 1
            sp = d.get("stop_price")
            try:
                has_stop = sp is not None and float(sp) > 0
            except (TypeError, ValueError):
                has_stop = False
            if has_stop:
                sp_sample["with_stop_price"] += 1
            tp = d.get("target_prices") or []
            if isinstance(tp, list) and tp:
                sp_sample["with_targets"] += 1
            ec = d.get("entry_context")
            if isinstance(ec, dict) and ec:
                sp_sample["with_entry_context"] += 1
            if len(sp_sample["samples"]) < 8:
                sp_sample["samples"].append({
                    "symbol": d.get("symbol"), "setup_type": d.get("setup_type"),
                    "direction": d.get("direction"), "stop_price": sp,
                    "entry_price": d.get("entry_price") or d.get("fill_price"),
                    "targets": tp[:1] if isinstance(tp, list) else None,
                    "has_entry_context": bool(isinstance(ec, dict) and ec),
                    "entry_context_keys": (sorted(ec.keys())[:12]
                                           if isinstance(ec, dict) else None),
                    "close_reason": d.get("close_reason"),
                })
    except Exception as e:
        sp_sample["error"] = str(e)[:160]
    out["stale_pending_sample"] = sp_sample
    return out
