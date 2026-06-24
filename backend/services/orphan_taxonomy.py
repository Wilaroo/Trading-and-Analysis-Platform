"""reconciled_orphan CREATION-CAUSE taxonomy (read-only).

The orphan_leak_rca module measures the $ leak and backtests stop/relink fixes.
This module answers the upstream question the operator asked — "why are we even
still creating orphans?" — by classifying every closed `reconciled_orphan` by
HOW it lost tracking, so each creation path can be sealed at the source
("stitch the cut, don't band-aid the stop").

Creation-cause classes (priority order, first match wins):
  1. reaped_pending_filled  — a bot PENDING filled at IB but the fill wasn't
       attributed (direct-IB flap); the stale-pending reaper closed it
       `stale_pending_*` and popped it from `_pending_trades`; the reconciler
       adopted the live fill as a synthetic orphan. Marker:
       `synthetic_source=relinked_reaped_pending` /
       `entry_context.relinked_from_reaped_pending`, OR a stale_pending
       predecessor on (symbol,direction) closed within `stale_window_min`.
       FIX: pending-fill attribution + reaper pusher-fallback; v405 relink seals.
  2. exit_overfill_residual — a bot position closed (target/OCA/EOD/trailing/
       scale) but the close over/under-filled, leaving a RESIDUAL share count
       that resurfaced. Marker: a normal-exit predecessor closed ≤near_window
       before, orphan qty a fraction (ratio ≤0.75) of the closed size.
       FIX: close/scale-out fill verification + post-close residual sweep.
  3. readopt_loop — a FULL position closed externally (OCA stop fired at IB /
       phantom-swept / emergency-flatten) and the reconciler RE-ADOPTED the
       re-appearing same-size position, often repeatedly. Marker: an
       external/oca/stop/phantom predecessor (real trade OR prior orphan) closed
       ≤readopt_window before, orphan qty ≈ full (ratio >0.75).
       FIX: durable post-close re-adopt suppression (extend recently_closed
       cooldown; verify-flat-at-IB before re-adopt) [reconcile_orphan_positions].
  4. share_drift_excess — the bot already tracked the symbol when the orphan
       spawned (IB qty > bot qty → excess adopted as a *separate* row). Marker:
       `synthetic_source=share_drift_excess` OR a concurrently-OPEN non-artifact
       trade overlapped the orphan.
       FIX: share-drift reconciler GROWS the tracked slice, never spawns.
  5. restart_orphan — tracking lost across a backend restart; boot auto-reconcile
       adopted the live IB position. Marker: `auto_reconcile_at_boot` ≤10m before
       (best-effort; stream store is TTL-7d).
       FIX: durable open-trade hydration on boot (rehydrate, don't re-adopt).
  6. true_foreign — no predecessor on the symbol in the lookback; a genuinely
       external/manual position. FIX: flatten, don't adopt.
  7. unclassified — a predecessor exists but matched no class (manual review).

Pure read-model. Writes NOTHING.
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from services.orphan_leak_rca import (
    ARTIFACT_SETUPS, _fnum, _clean_r, _parse_ts, _entry_ts, _close_ts,
)

logger = logging.getLogger(__name__)

# Normal (intended) exit close-reasons — exit-overfill residual signature.
_NORMAL_EXIT_MARKERS = (
    "target_", "oca_closed_externally", "eod_auto_close", "trailing",
    "take_profit", "scale", "stop_loss", "external_close",
)
# External/forced close-reasons — re-adopt-loop signature (full re-appearance).
_EXTERNAL_MARKERS = (
    "oca_closed_externally", "external", "stop", "phantom",
    "wrong_direction", "emergency_flatten",
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
    "readopt_loop": (
        "durable post-close re-adopt suppression — extend/persist the "
        "recently_closed cooldown + verify-flat-at-IB BEFORE re-adopting "
        "[position_reconciler.reconcile_orphan_positions]."),
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
                    stale_window_min: int = 1440, readopt_window_min: int = 480,
                    foreign_lookback_days: int = 30) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "near_window_min": near_window_min,
        "stale_window_min": stale_window_min,
        "readopt_window_min": readopt_window_min,
        "foreign_lookback_days": foreign_lookback_days,
        "classes_legend": _FIX_SITE,
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    pred_cutoff = (now - timedelta(days=days + foreign_lookback_days)).isoformat()

    all_trades = list(db["bot_trades"].find(
        {"$or": [{"closed_at": {"$gte": pred_cutoff}},
                 {"created_at": {"$gte": pred_cutoff}},
                 {"reaped_at": {"$gte": pred_cutoff}}]},
        _PROJ))

    _floor = datetime.min.replace(tzinfo=timezone.utc)
    by_key = defaultdict(list)        # non-artifact by (sym, dir)
    by_sym = defaultdict(list)        # non-artifact by sym
    orphans_by_key = defaultdict(list)  # reconciled_orphan by (sym, dir)
    for t in all_trades:
        sym = (t.get("symbol") or "").upper()
        dir_l = str(t.get("direction") or "").lower()
        if str(t.get("setup_type") or "") == "reconciled_orphan":
            orphans_by_key[(sym, dir_l)].append(t)
        if _is_artifact(t):
            continue
        by_key[(sym, dir_l)].append(t)
        by_sym[sym].append(t)
    for k in by_key:
        by_key[k].sort(key=lambda x: (_entry_ts(x) or _floor))
    for k in orphans_by_key:
        orphans_by_key[k].sort(key=lambda x: (_entry_ts(x) or _floor))

    # Best-effort boot-event index (auto_reconcile_at_boot, TTL ~7d).
    boot_events = []
    try:
        for ev in db["sentcom_thoughts"].find(
                {"event": "auto_reconcile_at_boot"},
                {"_id": 0, "timestamp": 1, "metadata": 1}):
            ts = _parse_ts(ev.get("timestamp"))
            if ts:
                md = ev.get("metadata") or {}
                syms = {(s or "").upper() for s in (md.get("symbols") or [])}
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
        best = None
        oq = _qty(o)
        for c in by_key.get((sym, dir_l), []):
            if not str(c.get("close_reason") or "").startswith("stale_pending"):
                continue
            cc = _close_ts(c) or _parse_ts(c.get("reaped_at"))
            gap = _gap_min(oe, cc)
            if gap is None or not (0 <= gap <= stale_window_min):
                continue
            cq = _qty(c)
            if cq > 0 and oq > 0 and not (0.3 <= oq / cq <= 3.0):
                continue
            best = (c, round(gap, 1))
        return best

    def _exit_residual_predecessor(o, sym, oe):
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
                if ratio is None or ratio > 0.75:
                    continue
                cand = (c, round(gap, 1), round(ratio, 2))
                if best is None or cand[1] < best[1]:
                    best = cand
        return best

    def _readopt_predecessor(o, sym, dir_l, oe):
        """A FULL-size external/forced close just before the orphan — the same
        position re-appearing and being re-adopted (the re-adopt loop). Searches
        prior real trades AND prior orphans on (sym,dir)."""
        oq = _qty(o)
        oid = o.get("id")
        best = None
        candidates = list(by_key.get((sym, dir_l), [])) + \
            list(orphans_by_key.get((sym, dir_l), []))
        for c in candidates:
            if c.get("id") == oid:
                continue
            cr = str(c.get("close_reason") or "")
            if not any(m in cr for m in _EXTERNAL_MARKERS):
                continue
            cc = _close_ts(c)
            gap = _gap_min(oe, cc)
            if gap is None or not (0 <= gap <= readopt_window_min):
                continue
            cq = _qty(c)
            ratio = (oq / cq) if (cq > 0 and oq > 0) else None
            if ratio is not None and ratio <= 0.75:
                continue  # residual → exit_overfill territory, not full re-adopt
            cand = (c, round(gap, 1), round(ratio, 2) if ratio else None,
                    str(c.get("setup_type") or ""))
            if best is None or cand[1] < best[1]:
                best = cand
        return best

    def _concurrent_open(o, sym, oe):
        oid = o.get("id")
        odir = str(o.get("direction") or "").lower()
        for c in by_sym.get(sym, []):
            if c.get("id") == oid:
                continue
            ce, cc = _entry_ts(c), _close_ts(c)
            if ce is None or oe is None:
                continue
            if ce <= oe and (cc is None or cc >= oe):
                cdir = str(c.get("direction") or "").lower()
                return c, ("same_dir" if cdir == odir else "opp_dir")
        return None, None

    def _any_predecessor(sym, dir_l, oe):
        lb = (oe - timedelta(days=foreign_lookback_days)) if oe else None
        last = None
        for c in by_key.get((sym, dir_l), []):
            ce = _entry_ts(c)
            if ce is None or oe is None:
                continue
            if lb <= ce < oe:
                last = c
        return last

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
            ev.update(marker="stale_pending_predecessor",
                      pred_close_reason=str(sp[0].get("close_reason") or ""),
                      gap_min=sp[1], pred_trade_id=sp[0].get("id"))
            return "reaped_pending_filled", ev

        # 2) exit_overfill_residual
        xp = _exit_residual_predecessor(o, sym, oe)
        if xp:
            ev.update(marker="normal_exit_predecessor_residual",
                      pred_close_reason=str(xp[0].get("close_reason") or ""),
                      gap_min=xp[1], qty_ratio_orphan_over_pred=xp[2],
                      pred_trade_id=xp[0].get("id"))
            return "exit_overfill_residual", ev

        # 3) readopt_loop
        rp = _readopt_predecessor(o, sym, dir_l, oe)
        if rp:
            ev.update(marker="external_close_full_readopt",
                      pred_close_reason=str(rp[0].get("close_reason") or ""),
                      gap_min=rp[1], qty_ratio_orphan_over_pred=rp[2],
                      pred_setup=rp[3], pred_trade_id=rp[0].get("id"))
            return "readopt_loop", ev

        # 4) share_drift_excess
        if ss == "share_drift_excess":
            ev["marker"] = "synthetic_source_share_drift"
            return "share_drift_excess", ev
        co, cdir = _concurrent_open(o, sym, oe)
        if co is not None:
            ev.update(marker="concurrent_open_trade", concurrent_dir=cdir,
                      concurrent_trade_id=co.get("id"),
                      concurrent_setup=co.get("setup_type"))
            return "share_drift_excess", ev

        # 5) restart_orphan
        bn = _boot_near(sym, oe)
        if bn is not None:
            ev.update(marker="auto_reconcile_at_boot", boot_gap_min=bn)
            return "restart_orphan", ev

        # 6) true_foreign
        ap = _any_predecessor(sym, dir_l, oe)
        if ap is None:
            ev["marker"] = "no_predecessor_in_lookback"
            return "true_foreign", ev

        # 7) unclassified
        ev.update(marker="predecessor_no_class_match",
                  pred_close_reason=str(ap.get("close_reason") or ""),
                  pred_trade_id=ap.get("id"))
        return "unclassified", ev

    # Aggregate per class.
    classes = defaultdict(lambda: {
        "n": 0, "leak_r": 0.0, "leak_usd": 0.0,
        "n_with_r": 0, "n_losers": 0, "markers": Counter(), "samples": []})
    total_r = total_usd = 0.0
    n_with_r = 0
    cls_cache = {}  # trade_id -> (cls, ev), so we classify each orphan once
    for o in orphans:
        cls, ev = classify(o)
        cls_cache[o.get("id")] = (cls, ev)
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
            oc = _close_ts(o)
            c["samples"].append({
                "symbol": o.get("symbol"), "direction": o.get("direction"),
                "qty": _qty(o), "synthetic_source": o.get("synthetic_source"),
                "r": round(r, 2) if r is not None else None,
                "usd": round(usd, 0),
                "close_reason": str(o.get("close_reason") or "")[:28],
                "hold_min": (round(_gap_min(oc, oe := _entry_ts(o)), 1)
                             if (_entry_ts(o) and oc) else None),
                "entry_month": (_entry_ts(o).strftime("%Y-%m")
                                if _entry_ts(o) else None),
                "evidence": ev,
            })

    out["population"] = {
        "n_closed_orphans": len(orphans),
        "total_leak_r": round(total_r, 2),
        "total_leak_usd": round(total_usd, 0),
        "n_with_r": n_with_r,
        "mean_r": round(total_r / n_with_r, 3) if n_with_r else None,
    }

    breakdown = []
    for cls, c in classes.items():
        mean_abs_r = (abs(c["leak_r"]) / c["n_with_r"]) if c["n_with_r"] else 0.0
        usd_per = abs(c["leak_usd"]) / c["n"] if c["n"] else 0.0
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
            # Flag classes whose R is inflated by tiny-risk residuals (high
            # |R| per trade but small $ per trade) so the ranking isn't misread.
            "tiny_risk_r_inflated": bool(mean_abs_r > 1.5 and usd_per < 80),
            "markers": dict(c["markers"]),
            "fix_site": _FIX_SITE.get(cls, ""),
            "samples": sorted(c["samples"],
                              key=lambda s: (s["r"] if s["r"] is not None else 0)),
        })
    out["taxonomy_by_r"] = sorted(breakdown, key=lambda x: x["leak_r"])
    out["taxonomy_by_usd"] = sorted(
        [{k: b[k] for k in ("creation_cause", "n", "leak_usd", "leak_r",
                            "pct_of_orphans", "tiny_risk_r_inflated", "fix_site")}
         for b in breakdown], key=lambda x: x["leak_usd"])
    # Back-compat alias (worst-R first).
    out["taxonomy"] = out["taxonomy_by_r"]

    # Monthly trend per class.
    month_class = defaultdict(lambda: defaultdict(lambda: {"n": 0, "leak_r": 0.0,
                                                           "leak_usd": 0.0}))
    for o in orphans:
        cls, _ = cls_cache[o.get("id")]
        oe = _entry_ts(o)
        mo = oe.strftime("%Y-%m") if oe else "unknown"
        r = _clean_r(o.get("realized_pnl"), o.get("risk_amount"))
        month_class[mo][cls]["n"] += 1
        month_class[mo][cls]["leak_r"] += r if r is not None else 0.0
        month_class[mo][cls]["leak_usd"] += _fnum(o.get("realized_pnl")) or 0.0
    out["monthly_by_class"] = [
        {"month": mo,
         "classes": {cls: {"n": d["n"], "leak_r": round(d["leak_r"], 2),
                           "leak_usd": round(d["leak_usd"], 0)}
                     for cls, d in sorted(cm.items())}}
        for mo, cm in sorted(month_class.items())]

    # v405 relink coverage.
    relink = {"reaped_pending_orphans": 0, "already_relinked_fix": 0,
              "would_relink_observe_marker": 0}
    for o in orphans:
        cls, ev = cls_cache[o.get("id")]
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
    relink["note"] = (
        "observe=0 is expected if all reaped_pending orphans predate the v405 "
        "deploy — the relink only fires at orphan-CREATION time going forward.")
    out["relink_coverage"] = relink

    # Verdict — rank by $ (R is distorted by tiny-risk residuals) + by R.
    if breakdown:
        by_usd = sorted(breakdown, key=lambda x: x["leak_usd"])
        worst_usd = by_usd[0]
        seq_usd = " → ".join(f"{b['creation_cause']}(${int(b['leak_usd'])})"
                             for b in by_usd if b["leak_usd"] < 0)
        out["verdict"] = (
            f"{len(orphans)} closed orphans / {out['population']['total_leak_usd']}$ "
            f"/ {out['population']['total_leak_r']}R. Rank by DOLLARS (R is "
            f"inflated by tiny-risk residuals — see tiny_risk_r_inflated): "
            f"biggest $ leak = {worst_usd['creation_cause']} "
            f"({worst_usd['n']} orphans, ${int(worst_usd['leak_usd'])}). "
            f"Seal order by $: {seq_usd or 'no negative classes'}. "
            f"Each class maps to a code site — see fix_site.")
    else:
        out["verdict"] = "No closed reconciled_orphan rows in the window."
    return out
