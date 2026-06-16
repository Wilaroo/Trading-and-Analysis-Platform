#!/usr/bin/env python3
"""diag_oca_close_reason_landscape.py  —  READ-ONLY  (2026-06-16)

Audits the systemic mis-labeling of OCA-external closes. For every
bot_trade with close_reason='oca_closed_externally_v19_31', cross-refs
the matching SELL fill in ib_executions and CLASSIFIES the real close:

  * target_N_hit     — exec price ≈ target_prices[i] (±$0.05)
  * stop_loss        — exec order_id matches stop_order_id
  * external_unknown — IB-side OCA close we genuinely can't classify
                       (target_order_ids capture bug + price doesn't
                       match any known target)

Outputs: counts + per-month split + sample mis-labeled wins +
projected impact on win-rate / target-hit rate / avg-PnL once relabeled.
"""
from __future__ import annotations
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

TARGET_TOL = 0.05    # $-tolerance for "exec price matches target"


def hr(t):
    print("\n" + "=" * 92 + f"\n  {t}\n" + "=" * 92)


def _parse(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    print(f"diag_oca_close_reason_landscape  "
          f"({datetime.now(timezone.utc).isoformat()[:19]}Z, read-only)")
    print(f"  target_tolerance = ±${TARGET_TOL}")

    # ── load all oca_externally-closed bot_trades ───────────────────────
    oca_q = {"close_reason": "oca_closed_externally_v19_31",
             "status": "closed"}
    rows = list(db["bot_trades"].find(oca_q, {
        "_id": 0, "id": 1, "symbol": 1, "direction": 1, "shares": 1,
        "entry_price": 1, "fill_price": 1, "exit_price": 1,
        "stop_price": 1, "target_prices": 1, "target_order_ids": 1,
        "entry_order_id": 1, "stop_order_id": 1,
        "created_at": 1, "executed_at": 1, "closed_at": 1,
        "realized_pnl": 1, "net_pnl": 1, "setup_type": 1, "trade_style": 1,
    }))
    print(f"  loaded {len(rows):,} oca_closed_externally_v19_31 trades")

    if not rows:
        return

    # ── classify each ───────────────────────────────────────────────────
    hr("Section 1 — Classification of OCA closes via ib_executions cross-ref")
    classification = Counter()
    relabel_examples = defaultdict(list)
    per_month = defaultdict(Counter)
    no_exec_match = []

    for t in rows:
        closed_at = _parse(t.get("closed_at"))
        if not closed_at:
            classification["no_closed_at"] += 1
            continue
        month = closed_at.strftime("%Y-%m")

        # Look up the SELL exec for this symbol near closed_at (±15 min).
        from datetime import timedelta
        win_start = (closed_at - timedelta(minutes=15)).isoformat()
        win_end = (closed_at + timedelta(minutes=15)).isoformat()
        time_clauses = []
        for tf in ("time", "exec_time", "ts"):
            time_clauses.append({tf: {"$gte": win_start, "$lte": win_end}})
        exec_q = {
            "symbol": t.get("symbol"),
            "$and": [
                {"$or": [{"side": "SELL"}, {"action": "SELL"}]} if
                (t.get("direction") or "").lower() == "long" else
                {"$or": [{"side": "BUY"}, {"action": "BUY"}]},
                {"$or": time_clauses},
            ],
        }
        # Match shares within ±1 (allow partial fills).
        sh = t.get("shares") or 0
        ex = None
        for cand in db["ib_executions"].find(exec_q):
            cand_sh = cand.get("shares") or cand.get("qty") or 0
            if abs(float(cand_sh) - float(sh)) <= 1:
                ex = cand
                break
            if ex is None:
                ex = cand

        if ex is None:
            classification["no_exec_match"] += 1
            no_exec_match.append(t)
            per_month[month]["no_exec_match"] += 1
            continue

        ex_price = float(ex.get("price") or ex.get("fill_price")
                         or ex.get("avg_price") or 0)
        ex_oid = str(ex.get("order_id") or "")

        # Stop hit?
        stop_oid = str(t.get("stop_order_id") or "")
        if stop_oid and ex_oid == stop_oid:
            classification["stop_loss"] += 1
            per_month[month]["stop_loss"] += 1
            relabel_examples["stop_loss"].append(
                (t["id"], t["symbol"], ex_price, t.get("stop_price")))
            continue

        # Target hit? Check price match against any target.
        targets = t.get("target_prices") or []
        matched = None
        for i, tp in enumerate(targets):
            if tp is None:
                continue
            if abs(ex_price - float(tp)) <= TARGET_TOL:
                matched = i + 1
                break
        # Also check target_order_ids for direct match.
        tgt_oids = [str(x) for x in (t.get("target_order_ids") or [])]
        if matched is None and ex_oid in tgt_oids:
            matched = tgt_oids.index(ex_oid) + 1

        if matched is not None:
            tag = f"target_{matched}_hit"
            classification[tag] += 1
            per_month[month][tag] += 1
            relabel_examples[tag].append(
                (t["id"], t["symbol"], ex_price,
                 targets[matched-1] if matched-1 < len(targets) else "?",
                 t.get("realized_pnl"), t.get("net_pnl"), t.get("setup_type")))
            continue

        # Unknown — true external or partial fill we can't classify
        classification["external_unknown"] += 1
        per_month[month]["external_unknown"] += 1

    total = sum(classification.values())
    print(f"  total classified: {total:,}\n")
    for tag, n in classification.most_common():
        pct = n / total * 100 if total else 0
        print(f"    {tag:>22} : {n:>5,}  ({pct:>5.1f}%)")

    # ── per-month ───────────────────────────────────────────────────────
    hr("Section 2 — Per-month classification (last 12 months)")
    months = sorted(per_month)[-12:]
    tags = sorted({tag for cnt in per_month.values() for tag in cnt})
    print(f"  {'month':>9}  " + "".join(f"{t[:10]:>12}" for t in tags) + "  total")
    for m in months:
        cnts = per_month[m]
        cells = "".join(f"{cnts.get(t, 0):>12}" for t in tags)
        print(f"  {m:>9}  {cells}  {sum(cnts.values()):>6}")

    # ── sample relabeled wins ───────────────────────────────────────────
    hr("Section 3 — Sample target hits we'd recover (top 10 each)")
    for tag in ("target_1_hit", "target_2_hit"):
        ex = relabel_examples.get(tag, [])
        if not ex:
            continue
        print(f"\n  {tag}: {len(ex)} samples (showing 10)")
        print(f"    {'id':>10} {'sym':>6} {'exec$':>9} {'target$':>9} "
              f"{'realized':>9} {'net_pnl':>9}  setup")
        for t_id, sym, p, tp, rp, np_, st in ex[:10]:
            print(f"    {t_id[:10]:>10} {sym:>6} {p:>8.2f}  {tp:>8}  "
                  f"{rp or 0:>9.2f}  {np_ or 0:>9.2f}  {st or '-'}")

    if relabel_examples.get("stop_loss"):
        print(f"\n  stop_loss samples: {len(relabel_examples['stop_loss'])} (showing 5)")
        for t_id, sym, p, sp in relabel_examples["stop_loss"][:5]:
            print(f"    {t_id[:10]:>10}  {sym:>6}  exec@{p}  stop@{sp}")

    # ── projected impact ────────────────────────────────────────────────
    hr("Section 4 — Projected impact of relabel")
    n_tgt = sum(v for k, v in classification.items() if k.startswith("target"))
    n_stop = classification.get("stop_loss", 0)
    n_unk = classification.get("external_unknown", 0)
    n_nomatch = classification.get("no_exec_match", 0)
    print("  After v320h relabel pass:")
    print(f"    • {n_tgt:,} new `target_N_hit` records "
          f"({n_tgt/total*100 if total else 0:.1f}% of OCA pool)")
    print(f"    • {n_stop:,} new `stop_loss_via_oca` records "
          f"({n_stop/total*100 if total else 0:.1f}%)")
    print(f"    • {n_unk:,} stay as `external_unknown` "
          f"({n_unk/total*100 if total else 0:.1f}%)")
    print(f"    • {n_nomatch:,} need ib_executions backfill "
          f"({n_nomatch/total*100 if total else 0:.1f}%)")
    print("\n  This validates whether v320h-style surgical OCA relabel pass")
    print("  is worth shipping. Each target-hit recovery also requires")
    print("  exit_price / net_pnl / pnl_pct rebuild (same as v320g pattern).")
    print("\nDONE.")


if __name__ == "__main__":
    main()
