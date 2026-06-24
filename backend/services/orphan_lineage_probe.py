"""Orphan lineage forensic probe (read-only) — Seal #2 investigation.

The v407 taxonomy found ~$1.9k of the orphan leak in positions with NO bot_trade
predecessor in 240 days (SHLD/UAL/VRT…). The operator confirmed the bot is the
SOLE opener, so these MUST be bot positions whose record vanished. This probe
finds out WHERE the record went by cross-referencing each record-less orphan
against the bot's UNBOUNDED trade history, `order_queue`, and `ib_executions`:

  - lineage_recent — a genuine bot_trade exists within 240d (taxonomy would have
      relinked it; not actually record-less — shown for completeness).
  - old_lineage    — a genuine bot_trade exists but OLDER than 240d → just an old
      swing/position the taxonomy window missed. FIX: widen relink window; benign.
  - order_no_trade — the bot QUEUED an order (order_queue) but no bot_trade row
      exists → the `bot_trades` write/persist gap. FIX at the write site.
  - truly_absent   — nothing anywhere (no bot_trade, no order_queue). Either a
      pre-bot legacy position or a record hard-deleted. FIX: investigate retention
      / adopt-with-wide-stop-or-flatten policy for contextless positions.

Pure read-model. Writes NOTHING.
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from services.orphan_leak_rca import _fnum, _clean_r, _entry_ts, _close_ts, _parse_ts

logger = logging.getLogger(__name__)

_RECONCILED_SETUPS = ("reconciled_orphan", "reconciled_excess_slice")


def _is_genuine(t):
    if str(t.get("setup_type") or "") in _RECONCILED_SETUPS:
        return False
    if str(t.get("entered_by") or "").startswith("reconciled"):
        return False
    return True


def generate_report(db, days: int = 120, lineage_window_days: int = 240) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "lineage_window_days": lineage_window_days,
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    _floor = datetime.min.replace(tzinfo=timezone.utc)

    orphans = list(db["bot_trades"].find(
        {"setup_type": "reconciled_orphan", "status": "closed",
         "$or": [{"closed_at": {"$gte": cutoff}}, {"entry_time": {"$gte": cutoff}}]},
        {"_id": 0}))
    orphans = [o for o in orphans if (_entry_ts(o) or _floor).isoformat() >= cutoff]

    # Symbol-level caches so repeated symbols don't re-query.
    oq_cache, ie_cache = {}, {}

    def _order_queue_hits(sym):
        if sym in oq_cache:
            return oq_cache[sym]
        try:
            n = db["order_queue"].count_documents({"symbol": sym})
            latest = None
            if n:
                cur = db["order_queue"].find(
                    {"symbol": sym},
                    {"_id": 0, "created_at": 1, "submitted_at": 1, "status": 1,
                     "action": 1, "trade_id": 1}).sort("created_at", -1).limit(1)
                latest = next(iter(cur), None)
        except Exception as e:
            n, latest = -1, {"error": str(e)[:80]}
        oq_cache[sym] = (n, latest)
        return oq_cache[sym]

    def _ib_exec_hits(sym):
        if sym in ie_cache:
            return ie_cache[sym]
        try:
            n = db["ib_executions"].count_documents({"symbol": sym})
        except Exception:
            n = -1
        ie_cache[sym] = n
        return n

    def _genuine_lineage(sym, dir_l, oid):
        """Most recent genuine bot_trade on (sym,dir), UNBOUNDED in time."""
        try:
            cur = db["bot_trades"].find(
                {"symbol": sym, "direction": dir_l,
                 "setup_type": {"$nin": list(_RECONCILED_SETUPS)}},
                {"_id": 0, "id": 1, "setup_type": 1, "entered_by": 1,
                 "close_reason": 1, "entry_time": 1, "closed_at": 1,
                 "reaped_at": 1, "stop_price": 1}).sort("entry_time", -1).limit(8)
        except Exception:
            return None
        for d in cur:
            if d.get("id") == oid or not _is_genuine(d):
                continue
            return d
        return None

    buckets = defaultdict(lambda: {"n": 0, "usd": 0.0, "leak_r": 0.0,
                                   "symbols": Counter(), "samples": []})
    for o in orphans:
        sym = (o.get("symbol") or "").upper()
        dir_l = str(o.get("direction") or "").lower()
        usd = _fnum(o.get("realized_pnl")) or 0.0
        r = _clean_r(o.get("realized_pnl"), o.get("risk_amount"))

        pred = _genuine_lineage(sym, dir_l, o.get("id"))
        ev = {}
        if pred is not None:
            # Reaped/rejected predecessors have a null entry_time — fall back to
            # their close/reap time so the recency (and relinkability) is honest.
            pe = _entry_ts(pred)
            pc = _close_ts(pred) or _parse_ts(pred.get("reaped_at"))
            basis_ts = pe or pc
            days_ago = (now - basis_ts).days if basis_ts else None
            ev = {"pred_id": pred.get("id"),
                  "pred_setup": pred.get("setup_type"),
                  "pred_close_reason": pred.get("close_reason"),
                  "pred_recency_days_ago": days_ago,
                  "pred_recency_basis": ("entry" if pe else "close" if pc else None)}
            # Has lineage → Seal #1 (v408) relinks it, UNLESS it's a genuinely old
            # swing (older than the relink window).
            if days_ago is not None and days_ago > lineage_window_days:
                cls = "old_lineage"
            else:
                cls = "relinkable_lineage"
        else:
            oq_n, oq_latest = _order_queue_hits(sym)
            ie_n = _ib_exec_hits(sym)
            ev = {"order_queue_hits": oq_n, "ib_executions_hits": ie_n,
                  "order_queue_latest": oq_latest}
            cls = "order_no_trade" if (oq_n and oq_n > 0) else "truly_absent"

        b = buckets[cls]
        b["n"] += 1
        b["usd"] += usd
        if r is not None:
            b["leak_r"] += r
        b["symbols"][sym] += 1
        oe, oc = _entry_ts(o), _close_ts(o)
        if len(b["samples"]) < 20:
            b["samples"].append({
                "symbol": sym, "direction": o.get("direction"),
                "qty": int(_fnum(o.get("shares")) or _fnum(o.get("original_shares")) or 0),
                "usd": round(usd, 0), "r": round(r, 2) if r is not None else None,
                "close_reason": str(o.get("close_reason") or "")[:28],
                "entry_month": oe.strftime("%Y-%m") if oe else None,
                "evidence": ev,
            })

    out["population"] = {"n_closed_orphans": len(orphans)}
    breakdown = []
    for cls, b in buckets.items():
        breakdown.append({
            "lineage_class": cls,
            "n": b["n"], "leak_usd": round(b["usd"], 0),
            "leak_r": round(b["leak_r"], 2),
            "top_symbols": b["symbols"].most_common(12),
            "samples": sorted(b["samples"], key=lambda s: s["usd"]),
        })
    breakdown.sort(key=lambda x: x["leak_usd"])
    out["lineage"] = breakdown
    out["legend"] = {
        "relinkable_lineage": "genuine bot_trade predecessor (often a reaped/"
            "rejected pending) — Seal #1 (v408 relink) heals it by inheriting the "
            "real stop/context.",
        "old_lineage": "genuine bot_trade but OLDER than the window — old swing; "
            "widen RECONCILE_RELINK_ANY_WINDOW_MIN.",
        "order_no_trade": "order_queue exists (often status=filled) but NO bot_trade "
            "— the bot_trades write/persist gap (the record-less bug).",
        "truly_absent": "no bot_trade and no order_queue (may have direct "
            "ib_executions fills) — direct-path fill that never created a tracked "
            "trade / legacy / hard-deleted record.",
    }
    worst = breakdown[0] if breakdown else None
    out["verdict"] = (
        (f"{len(orphans)} closed orphans probed. Biggest $ lineage class: "
         f"{worst['lineage_class']} ({worst['n']} orphans, ${int(worst['leak_usd'])}). "
         "relinkable_lineage ⇒ Seal #1 (v408) heals it (flip to fix); "
         "order_no_trade/truly_absent ⇒ Seal #2 source fix (fill→bot_trade write "
         "gap on the direct/queue path).")
        if worst else "No closed reconciled_orphan rows in the window.")
    return out
