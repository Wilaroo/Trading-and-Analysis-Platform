"""Seal #2 — fill→bot_trade WRITE-GAP probe (READ-ONLY, base-trade_id-keyed).

Finds `order_queue` rows the pusher marked FILLED whose BASE trade_id (synthetic
CLOSE-/ADOPT-/SCALE- prefixes stripped) has NO `bot_trades` row — a confirmed fill
the bot never persisted as a tracked trade. For each true gap it determines:

  • PRE vs POST the v19.34.6 pre-submit-write fix (2026-05-05) — post-fix gaps are
    the LIVE leak (an entry path that bypasses _execute_trade's pre-write).
  • MECHANISM:
      consolidated_in_memory — base is in a bracket_lifecycle_events.merged_from_siblings
        (record lives in the canonical; not a true loss).
      became_reconciled_orphan — a reconciled_orphan exists within ±3d (filled → lost
        tracking → adopted with a synthetic stop → bled). THE Seal #2 target.
      truly_untracked — no record anywhere (often $0: ETF/hedge fills that netted flat).
  • $ leak = sum over DISTINCT downstream orphans (counted once).

Writes NOTHING. Active heal is a later, flag-gated step.
Endpoint: GET /api/slow-learning/orphan-fill-heal/report?days=120
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from services.orphan_leak_rca import _fnum, _parse_ts

logger = logging.getLogger(__name__)

_FILLED_STATES = ("filled", "partial")
_RECONCILED_SETUPS = ("reconciled_orphan", "reconciled_excess_slice")
_PREFIX = re.compile(
    r'^(CLOSE|ADOPT-STOP|ADOPT|EXIT|STOP|TGT|TARGET|SCALE|TRIM|FLATTEN|FLAT)-', re.I)
_MATCH_WINDOW_DAYS = 3
_PRESUBMIT_FIX = datetime(2026, 5, 5, tzinfo=timezone.utc)   # v19.34.6 pre-write landed


def _base_id(tid):
    if not tid:
        return tid
    prev, t = None, str(tid)
    while prev != t:
        prev = t
        t = _PREFIX.sub("", t)
    return t


def _opening_action(leg):
    a = (leg.get("action") or "").upper()
    if not a:
        a = ((leg.get("parent") or {}).get("action") or "").upper()
    return a if a in ("BUY", "SELL") else None


def _leg_qty(leg):
    return _fnum(leg.get("filled_qty")) or _fnum(leg.get("quantity")) \
        or _fnum((leg.get("parent") or {}).get("quantity"))


def generate_report(db, days: int = 120) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "presubmit_fix_date": _PRESUBMIT_FIX.strftime("%Y-%m-%d"),
        "mode": "observe",
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    try:
        rows = list(db["order_queue"].find(
            {"status": {"$in": list(_FILLED_STATES)}, "trade_id": {"$ne": None},
             "$or": [{"executed_at": {"$gte": cutoff}}, {"queued_at": {"$gte": cutoff}}]},
            {"_id": 0, "trade_id": 1, "symbol": 1, "action": 1, "parent": 1,
             "quantity": 1, "filled_qty": 1, "fill_price": 1,
             "executed_at": 1, "queued_at": 1}))
    except Exception as e:
        out["error"] = "order_queue scan failed: %s" % (str(e)[:120])
        return out

    # consolidation siblings (record lives in the canonical, not lost)
    merged = set()
    try:
        for e in db["bracket_lifecycle_events"].find(
                {"merged_from_siblings": {"$exists": True}},
                {"_id": 0, "merged_from_siblings": 1}):
            for x in (e.get("merged_from_siblings") or []):
                if x:
                    merged.add(_base_id(x))
    except Exception:
        pass

    grp = defaultdict(lambda: {"rows": [], "entry_leg": None})
    for r in rows:
        tid = r.get("trade_id")
        b = _base_id(tid)
        g = grp[b]
        g["rows"].append(r)
        if tid == b and _opening_action(r):
            cur = g["entry_leg"]
            if cur is None or str(r.get("executed_at") or "") < str(cur.get("executed_at") or "~"):
                g["entry_leg"] = r

    classes = Counter()
    period = Counter()                     # pre_fix / post_fix / unknown
    mech = Counter()                       # post-fix mechanism buckets
    mech_orphans = defaultdict(dict)       # mechanism → {orphan_id: pnl}
    gaps = []
    bt_cache = {}
    for b, g in grp.items():
        if b in bt_cache:
            has_bt = bt_cache[b]
        else:
            try:
                has_bt = db["bot_trades"].find_one({"id": b}, {"_id": 1}) is not None
            except Exception:
                has_bt = True
            bt_cache[b] = has_bt
        if has_bt:
            classes["has_record"] += 1
            continue

        cls = "entry_write_gap" if g["entry_leg"] is not None else "exit_only_orders_no_base"
        classes[cls] += 1
        if cls != "entry_write_gap":
            continue

        op = g["entry_leg"]
        sym = (op.get("symbol") or "").upper()
        fts = _parse_ts(op.get("executed_at") or op.get("queued_at"))
        action = _opening_action(op)
        direction = "long" if action == "BUY" else "short" if action == "SELL" else None
        qty = _leg_qty(op)

        seg = "unknown" if fts is None else ("post_fix" if fts >= _PRESUBMIT_FIX else "pre_fix")
        period[seg] += 1

        best, best_dd = None, None
        try:
            for c in db["bot_trades"].find(
                    {"symbol": sym, "setup_type": {"$in": list(_RECONCILED_SETUPS)}},
                    {"_id": 0, "id": 1, "realized_pnl": 1, "entry_time": 1,
                     "executed_at": 1, "closed_at": 1, "close_reason": 1}):
                ct = _parse_ts(c.get("entry_time") or c.get("executed_at") or c.get("closed_at"))
                if fts and ct and abs((ct - fts).days) <= _MATCH_WINDOW_DAYS:
                    dd = abs((ct - fts).total_seconds())
                    if best_dd is None or dd < best_dd:
                        best_dd, best = dd, c
        except Exception:
            pass

        if b in merged:
            mechanism = "consolidated_in_memory"
        elif best:
            mechanism = "became_reconciled_orphan"
        else:
            mechanism = "truly_untracked"

        downstream = None
        if best:
            downstream = {"orphan_id": best["id"],
                          "realized_pnl": _fnum(best.get("realized_pnl")),
                          "close_reason": str(best.get("close_reason") or "")[:32]}
        if seg == "post_fix":
            mech[mechanism] += 1
            if best:
                mech_orphans[mechanism][best["id"]] = _fnum(best.get("realized_pnl")) or 0.0

        gaps.append({
            "base_trade_id": b, "symbol": sym, "direction": direction,
            "filled_qty": int(qty) if qty else None,
            "entry_price": _fnum(op.get("fill_price")),
            "executed_at": op.get("executed_at") or op.get("queued_at"),
            "period": seg, "mechanism": mechanism,
            "downstream_reconciled_orphan": downstream,
        })

    post_orphan_usd = round(sum(mech_orphans.get("became_reconciled_orphan", {}).values()), 0)
    n_post_orphans = len(mech_orphans.get("became_reconciled_orphan", {}))
    gaps.sort(key=lambda x: ((x["downstream_reconciled_orphan"] or {}).get("realized_pnl") or 0.0))

    # v414 — full executed_at date histogram of the post-fix orphan-causing gaps
    # (NOT capped like `samples`). Answers ongoing-leak vs one-time-deploy-window:
    # a single dominant date == a restart-window batch; a spread == a live bypass.
    _post_orphan_gaps = [g for g in gaps if g["period"] == "post_fix"
                         and g["mechanism"] == "became_reconciled_orphan"]
    _date_hist = Counter((g.get("executed_at") or "")[:10] for g in _post_orphan_gaps)

    out["population"] = {
        "filled_order_queue_rows": len(rows),
        "distinct_base_trade_ids": len(grp),
        "classes": dict(classes),
    }
    out["by_period"] = dict(period)
    out["post_fix_mechanism"] = {
        m: {"n": mech[m], "leaked_usd": round(sum(mech_orphans[m].values()), 0),
            "n_orphans": len(mech_orphans[m])}
        for m in mech
    }
    out["live_leak"] = {
        "n_post_fix_orphan_gaps": mech.get("became_reconciled_orphan", 0),
        "leaked_usd": post_orphan_usd,
        "n_distinct_orphans": n_post_orphans,
        "note": "post-fix filled entries with NO bot_trade that became synthetic-stop "
                "orphans — the live Seal #2 leak (entry path bypassing the pre-submit write).",
    }
    out["post_fix_orphan_date_histogram"] = dict(sorted(_date_hist.items()))
    out["samples"] = [g for g in gaps if g["period"] == "post_fix"
                      and g["mechanism"] == "became_reconciled_orphan"][:20]
    out["verdict"] = (
        ("LIVE Seal #2 leak: %d post-fix filled entries with no bot_trade became "
         "synthetic-stop orphans ≈ $%d (%d distinct orphans). Mechanism = an entry path "
         "that bypasses the v19.34.6 pre-submit write. Fix: guarantee the tracked "
         "bot_trade at fill (pre-write at the bypass site + a flag-gated fill-confirm "
         "reconciler), so these are never adopted as contextless orphans." % (
             mech.get("became_reconciled_orphan", 0), int(post_orphan_usd), n_post_orphans))
        if mech.get("became_reconciled_orphan") else
        "No post-fix orphan-causing write gaps detected in the window.")
    return out
