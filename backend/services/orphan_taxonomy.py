"""reconciled_orphan CREATION-CAUSE taxonomy (read-only).

The orphan_leak_rca module measures the $ leak and backtests stop/relink fixes.
This module answers the upstream question the operator asked — "why are we even
still creating orphans?" — by classifying every closed `reconciled_orphan` by
HOW it lost tracking, so each creation path can be sealed at the source
("stitch the cut, don't band-aid the stop").

Creation-cause classes (priority order, first match wins):
  1. reaped_pending_filled  — a bot PENDING filled at IB but the fill wasn't
       attributed (direct-IB flap); the 300s stale-pending reaper closed it
       `stale_pending_*` and popped it from `_pending_trades`; the reconciler
       then adopted the live fill as a synthetic orphan. The v405 relink targets
       exactly this class. Marker: `synthetic_source=relinked_reaped_pending` /
       `entry_context.relinked_from_reaped_pending`, OR a stale_pending
       predecessor on (symbol,direction) closed just before the orphan's entry.
       FIX SITE: pending-fill attribution + reaper guards (pusher fallback).
  2. exit_overfill_residual — a bot position was closed (target / OCA / EOD /
       trailing / scale) but the close order over- or under-filled, leaving a
       residual share count that resurfaced as an orphan. Marker: a normal-exit
       predecessor on the symbol closed just before the orphan, with the orphan
       qty a fraction (residual) of the predecessor's original size.
       FIX SITE: close/scale-out fill verification + residual sweep.
  3. share_drift_excess — the bot already tracked the symbol when the orphan
       spawned (IB qty > bot qty → excess shares adopted as a *separate* row).
       Marker: a concurrently-OPEN non-artifact trade overlapped the orphan, or
       `synthetic_source=share_drift_excess`.
       FIX SITE: share-drift reconciler (grow the tracked slice, never spawn).
  4. restart_orphan — tracking was lost across a backend restart; the boot
       auto-reconcile adopted the live IB position fresh. Marker: an
       `auto_reconcile_at_boot` event within ~10m before the orphan's entry
       (best-effort; the stream store is TTL-7d so only recent ones resolve).
       FIX SITE: durable open-trade hydration on boot (rehydrate, don't re-adopt).
  5. true_foreign — the bot never traded this (symbol,direction) in the lookback;
       a genuinely external/manual position. Marker: no predecessor at all.
       FIX SITE: flatten (don't adopt) genuinely foreign positions.
  6. unclassified — a predecessor exists but fits none of the above cleanly.

Pure read-model. Writes NOTHING.
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean

from services.orphan_leak_rca import (
    ARTIFACT_SETUPS, _fnum, _clean_r, _parse_ts, _entry_ts, _close_ts,
)

logger = logging.getLogger(__name__)

# Normal (intended) exit close-reasons — distinguishes an exit-overfill residual
# from a stale-pending reap. stale_pending handled separately (class 1).
_NORMAL_EXIT_MARKERS = (
    "target_", "oca_closed_externally", "eod_auto_close", "trailing",
    "take_profit", "scale", "stop_loss", "phantom", "external_close",
)

_PROJ = {"_id": 0, "id": 1, "symbol": 1, "direction": 1, "status": 1,
         "setup_type": 1, "entered_by": 1, "synthetic_source": 1,
         "entry_price": 1, "fill_price": 1, "stop_price": 1,
         "shares": 1, "original_shares": 1,
         "realized_pnl": 1, "risk_amount": 1, "close_reason": 1,
         "market_regime": 1, "entry_context": 1,
         "entry_time": 1, "executed_at": 1, "created_at": 1,
         "closed_at": 1, "reaped_at": 1, "updated_at": 1}

_FIX_SITE = {
    "reaped_pending_filled": (
        "_attribute_pending_fills + stale-pending reaper guards "
        "(pusher position fallback so a filled PENDING is promoted, not reaped) "
        "[trading_bot_service.py]; v405 relink seals the residual."),
    "exit_overfill_residual": (
        "close/scale-out fill verification + post-close residual sweep "
        "[position_manager.close_trade / check_and_execute_scale_out]."),
    "share_drift_excess": (
        "share-drift reconciler — GROW the tracked slice instead of spawning a "
        "separate reconciled row [position_reconciler.reconcile_share_drift]."),
    "restart_orphan": (
        "durable open-trade hydration on boot — rehydrate `_open_trades` from "
        "Mongo BEFORE boot auto-reconcile adopts the live IB position "
        "[trading_bot_service.start]."),
    "true_foreign": (
        "FLATTEN genuinely-foreign positions instead of adopting them "
        "[reconcile_orphan_positions: refuse-adopt + place_close_market]."),
    "unclassified": "manual review — predecessor exists but fits no known class.",
}


def _qty(t):
    for k in ("shares", "original_shares"):
        v = _fnum(t.get(k))
        if v and v > 0:
            return int(v)
    return 0


def _is_artifact(t):
    return str(t.get("setup_type") or "") in ARTIFACT_SETUPS


def _gap_min(later_ts, earlier_ts):
    if not later_ts or not earlier_ts:
        return None
    return (later_ts - earlier_ts).total_seconds() / 60.0


def generate_report(db, days: int = 120, near_window_min: int = 240,
                    foreign_lookback_days: int = 30) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "near_window_min": near_window_min,
        "foreign_lookback_days": foreign_lookback_days,
        "classes_legend": _FIX_SITE,
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    # Predecessors may sit just before the window — widen the lookup so we don't
    # mislabel an orphan true_foreign when its predecessor is one day older.
    pred_cutoff = (now - timedelta(days=days + foreign_lookback_days)).isoformat()

    all_trades = list(db["bot_trades"].find(
        {"$or": [{"closed_at": {"$gte": pred_cutoff}},
                 {"created_at": {"$gte": pred_cutoff}},
                 {"reaped_at": {"$gte": pred_cutoff}}]},
        _PROJ))

    _floor = datetime.min.replace(tzinfo=timezone.utc)
    # Non-artifact trades indexed by (symbol, direction), entry-ascending.
    by_key = defaultdict(list)
    # All non-artifact trades by symbol (for concurrent-open overlap detection).
    by_sym = defaultdict(list)
    for t in all_trades:
        if _is_artifact(t):
            continue
        sym = (t.get("symbol") or "").upper()
        dir_l = str(t.get("direction") or "").lower()
        by_key[(sym, dir_l)].append(t)
        by_sym[sym].append(t)
    for k in by_key:
        by_key[k].sort(key=lambda x: (_entry_ts(x) or _floor))

    # Best-effort boot-event index (auto_reconcile_at_boot lives in
    # sentcom_thoughts, TTL ~7d — only recent orphans will resolve a boot).
    boot_events = []
    try:
        for ev in db["sentcom_thoughts"].find(
                {"event": "auto_reconcile_at_boot"},
                {"_id": 0, "timestamp": 1, "metadata": 1}):
            ts = _parse_ts(ev.get("timestamp"))
            if ts:
                syms = set()
                md = ev.get("metadata") or {}
                for s in (md.get("symbols") or []):
                    syms.add((s or "").upper())
                boot_events.append((ts, syms))
    except Exception as e:
        out["boot_events_error"] = str(e)[:160]
    boot_events.sort(key=lambda x: x[0])

    def _boot_near(sym, oe, max_gap_min=10.0):
        if oe is None:
            return None
        for ts, syms in boot_events:
            gap = _gap_min(oe, ts)
            if gap is None or gap < 0 or gap > max_gap_min:
                continue
            if not syms or sym in syms:
                return round(gap, 1)
        return None

    orphans = [t for t in all_trades
               if str(t.get("setup_type") or "") == "reconciled_orphan"
               and str(t.get("status") or "") == "closed"
               and (_entry_ts(t) or _floor).isoformat() >= cutoff]

    def _stale_predecessor(o, sym, dir_l, oe):
        """A stale_pending reap on the same (symbol,direction) closed just
        before the orphan's entry — the reaped_pending_filled signature."""
        best = None
        oq = _qty(o)
        for c in by_key.get((sym, dir_l), []):
            if not str(c.get("close_reason") or "").startswith("stale_pending"):
                continue
            cc = _close_ts(c) or _parse_ts(c.get("reaped_at"))
            gap = _gap_min(oe, cc)
            if gap is None or not (0 <= gap <= near_window_min):
                continue
            cq = _qty(c)
            if cq > 0 and oq > 0 and not (0.4 <= oq / cq <= 2.5):
                continue
            best = (c, round(gap, 1))  # ascending → last valid before entry wins
        return best

    def _exit_predecessor(o, sym, oe):
        """A normal-exit close on the SAME symbol (either direction — an overfill
        flips direction) just before the orphan; orphan qty a residual fraction."""
        best = None
        oq = _qty(o)
        for dir_l in ("long", "short"):
            for c in by_key.get((sym, dir_l), []):
                cr = str(c.get("close_reason") or "")
                if cr.startswith("stale_pending"):
                    continue
                if not any(m in cr for m in _NORMAL_EXIT_MARKERS):
                    continue
                cc = _close_ts(c)
                gap = _gap_min(oe, cc)
                if gap is None or not (0 <= gap <= near_window_min):
                    continue
                cq = _qty(c)
                ratio = (oq / cq) if (cq > 0 and oq > 0) else None
                # Residual = orphan is a fraction of the closed size (over/under-fill).
                if ratio is None or ratio > 0.75:
                    continue
                cand = (c, round(gap, 1), round(ratio, 2))
                if best is None or cand[1] < best[1]:
                    best = cand
        return best

    def _concurrent_open(o, sym, oe):
        """A non-artifact trade whose [entry, close] window contained the orphan's
        entry — the bot already tracked the symbol (share-drift excess spawn)."""
        oid = o.get("id")
        for c in by_sym.get(sym, []):
            if c.get("id") == oid:
                continue
            ce, cc = _entry_ts(c), _close_ts(c)
            if ce is None or oe is None:
                continue
            if ce <= oe and (cc is None or cc >= oe):
                return c
        return None

    def _any_predecessor(sym, dir_l, oe):
        lb = (oe - timedelta(days=foreign_lookback_days)) if oe else None
        for c in by_key.get((sym, dir_l), []):
            ce = _entry_ts(c)
            if ce is None or oe is None:
                continue
            if lb <= ce < oe:
                return c
        return None

    def classify(o):
        sym = (o.get("symbol") or "").upper()
        dir_l = str(o.get("direction") or "").lower()
        oe = _entry_ts(o)
        ec = o.get("entry_context") if isinstance(o.get("entry_context"), dict) else {}
        ss = str(o.get("synthetic_source") or "")
        ev = {}

        # 1) reaped_pending_filled
        if ss == "relinked_reaped_pending" or ec.get("relinked_from_reaped_pending"):
            ev["marker"] = "relink_marker"
            return "reaped_pending_filled", ev
        sp = _stale_predecessor(o, sym, dir_l, oe)
        if sp:
            ev["marker"] = "stale_pending_predecessor"
            ev["pred_close_reason"] = str(sp[0].get("close_reason") or "")
            ev["gap_min"] = sp[1]
            ev["pred_trade_id"] = sp[0].get("id")
            return "reaped_pending_filled", ev

        # 2) exit_overfill_residual
        xp = _exit_predecessor(o, sym, oe)
        if xp:
            ev["marker"] = "normal_exit_predecessor_residual"
            ev["pred_close_reason"] = str(xp[0].get("close_reason") or "")
            ev["gap_min"] = xp[1]
            ev["qty_ratio_orphan_over_pred"] = xp[2]
            ev["pred_trade_id"] = xp[0].get("id")
            return "exit_overfill_residual", ev

        # 3) share_drift_excess
        if ss == "share_drift_excess":
            ev["marker"] = "synthetic_source_share_drift"
            return "share_drift_excess", ev
        co = _concurrent_open(o, sym, oe)
        if co is not None:
            ev["marker"] = "concurrent_open_trade"
            ev["concurrent_trade_id"] = co.get("id")
            ev["concurrent_setup"] = co.get("setup_type")
            return "share_drift_excess", ev

        # 4) restart_orphan
        bn = _boot_near(sym, oe)
        if bn is not None:
            ev["marker"] = "auto_reconcile_at_boot"
            ev["boot_gap_min"] = bn
            return "restart_orphan", ev

        # 5) true_foreign
        ap = _any_predecessor(sym, dir_l, oe)
        if ap is None:
            ev["marker"] = "no_predecessor_in_lookback"
            return "true_foreign", ev

        # 6) unclassified — a predecessor exists but matched no class.
        ev["marker"] = "predecessor_no_class_match"
        ev["pred_close_reason"] = str(ap.get("close_reason") or "")
        ev["pred_trade_id"] = ap.get("id")
        return "unclassified", ev

    # Aggregate per class.
    classes = defaultdict(lambda: {
        "n": 0, "leak_r": 0.0, "leak_usd": 0.0,
        "n_with_r": 0, "n_losers": 0, "markers": Counter(), "samples": []})
    total_r = total_usd = 0.0
    n_with_r = 0
    for o in orphans:
        cls, ev = classify(o)
        r = _clean_r(o.get("realized_pnl"), o.get("risk_amount"))
        usd = _fnum(o.get("realized_pnl")) or 0.0
        c = classes[cls]
        c["n"] += 1
        c["leak_usd"] += usd
        total_usd += usd
        if r is not None:
            c["leak_r"] += r
            c["n_with_r"] += 1
            total_r += r
            n_with_r += 1
            if r < 0:
                c["n_losers"] += 1
        c["markers"][ev.get("marker", "?")] += 1
        if len(c["samples"]) < 12:
            oe = _entry_ts(o)
            oc = _close_ts(o)
            c["samples"].append({
                "symbol": o.get("symbol"),
                "direction": o.get("direction"),
                "qty": _qty(o),
                "synthetic_source": o.get("synthetic_source"),
                "r": round(r, 2) if r is not None else None,
                "usd": round(usd, 0),
                "close_reason": str(o.get("close_reason") or "")[:28],
                "hold_min": (round(_gap_min(oc, oe), 1)
                             if (oe and oc) else None),
                "entry_month": oe.strftime("%Y-%m") if oe else None,
                "evidence": ev,
            })

    out["population"] = {
        "n_closed_orphans": len(orphans),
        "total_leak_r": round(total_r, 2),
        "total_leak_usd": round(total_usd, 0),
        "n_with_r": n_with_r,
        "mean_r": round(total_r / n_with_r, 3) if n_with_r else None,
    }

    # Class breakdown, worst leak first.
    breakdown = []
    for cls, c in classes.items():
        breakdown.append({
            "creation_cause": cls,
            "n": c["n"],
            "pct_of_orphans": (round(100.0 * c["n"] / len(orphans), 1)
                               if orphans else 0.0),
            "leak_r": round(c["leak_r"], 2),
            "leak_usd": round(c["leak_usd"], 0),
            "n_losers": c["n_losers"],
            "mean_r": (round(c["leak_r"] / c["n_with_r"], 3)
                       if c["n_with_r"] else None),
            "markers": dict(c["markers"]),
            "fix_site": _FIX_SITE.get(cls, ""),
            "samples": sorted(c["samples"],
                              key=lambda s: (s["r"] if s["r"] is not None else 0)),
        })
    breakdown.sort(key=lambda x: x["leak_r"])  # most-negative first
    out["taxonomy"] = breakdown

    # Monthly trend per class — is a given creation path tapering or still live?
    month_class = defaultdict(lambda: defaultdict(lambda: {"n": 0, "leak_r": 0.0}))
    for o in orphans:
        cls, _ = classify(o)
        oe = _entry_ts(o)
        mo = oe.strftime("%Y-%m") if oe else "unknown"
        r = _clean_r(o.get("realized_pnl"), o.get("risk_amount"))
        month_class[mo][cls]["n"] += 1
        month_class[mo][cls]["leak_r"] += r if r is not None else 0.0
    out["monthly_by_class"] = [
        {"month": mo,
         "classes": {cls: {"n": d["n"], "leak_r": round(d["leak_r"], 2)}
                     for cls, d in sorted(cm.items())}}
        for mo, cm in sorted(month_class.items())]

    # v405 relink coverage — directly answers "did observe-mode fire / how much of
    # the reaped_pending class does relink already address?"
    relink = {"reaped_pending_orphans": 0, "already_relinked_fix": 0,
              "would_relink_observe_marker": 0}
    for o in orphans:
        cls, ev = classify(o)
        if cls != "reaped_pending_filled":
            continue
        relink["reaped_pending_orphans"] += 1
        if str(o.get("synthetic_source") or "") == "relinked_reaped_pending":
            relink["already_relinked_fix"] += 1
        elif ev.get("marker") == "stale_pending_predecessor":
            relink["would_relink_observe_marker"] += 1
    try:
        relink["state_integrity_events"] = {
            ev: db["state_integrity_events"].count_documents(
                {"event": ev, "ts": {"$gte": cutoff}})
            for ev in ("orphan_relink_observe", "orphan_relinked_reaped_pending")}
    except Exception as e:
        relink["state_integrity_events_error"] = str(e)[:160]
    out["relink_coverage"] = relink

    # Verdict — dominant creation cause + recommended seal sequence.
    if breakdown:
        worst = breakdown[0]
        ranked = sorted(breakdown, key=lambda x: x["leak_r"])
        seq = " → ".join(f"{b['creation_cause']}({b['leak_r']}R)"
                         for b in ranked if b["leak_r"] < 0)
        out["verdict"] = (
            f"{len(orphans)} closed orphans / {out['population']['total_leak_r']}R. "
            f"Dominant creation cause by leak: {worst['creation_cause']} "
            f"({worst['n']} orphans, {worst['leak_r']}R). "
            f"Seal order (worst→least): {seq or 'no negative classes'}. "
            f"Each class maps to a specific code site — see fix_site.")
    else:
        out["verdict"] = "No closed reconciled_orphan rows in the window."
    return out
