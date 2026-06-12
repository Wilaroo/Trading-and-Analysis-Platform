#!/usr/bin/env python3
"""
diag_squeeze_style_split.py — READ-ONLY verify probe (run anytime, market open OK)
===================================================================================
Question: is the "squeeze intraday-vs-swing trade_style split" (ROADMAP P1,
2026-06-05 backlog) already fixed by the v322u write-side reconciler
(timeframe follows trade_style on conflict), or does it still need code?

Checks:
  1. All squeeze* rows ever: (setup_type, trade_style, timeframe) combo counts.
  2. Same combos split PRE vs POST v322u go-live (2026-06-12 08:30 ET boot).
  3. Repo-wide style/tf coherence: every (trade_style, timeframe) pair that
     violates STYLE_TO_TIMEFRAME, with row counts + last-seen date.
  4. Bonus: duplicate-row check for the old save_trade _id/id split
     (answers "do we even need repair_dedupe_bot_trades?").

No writes. Output is a paste-back report.
"""
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


STYLE_TO_TIMEFRAME = {
    "scalp": "scalp",
    "intraday": "intraday",
    "multi_day": "swing",
    "swing": "swing",
    "position": "position",
    "investment": "position",
}
V322U_LIVE = "2026-06-12T12:30:00"  # 08:30 ET boot in UTC


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    col = db["bot_trades"]

    print("=" * 78)
    print("SQUEEZE STYLE/TF SPLIT — VERIFY PROBE (read-only)")
    print("=" * 78)

    # ── 1+2. squeeze rows, pre/post v322u ─────────────────────────────
    combos_pre, combos_post = Counter(), Counter()
    for t in col.find({"setup_type": {"$regex": "squeeze", "$options": "i"}},
                      {"_id": 0, "setup_type": 1, "trade_style": 1,
                       "timeframe": 1, "created_at": 1}):
        key = (t.get("setup_type"), t.get("trade_style"), t.get("timeframe"))
        ca = str(t.get("created_at") or "")
        (combos_post if ca >= V322U_LIVE else combos_pre)[key] += 1
    print("\n[1] SQUEEZE combos PRE-v322u (history):")
    for k, n in sorted(combos_pre.items(), key=lambda x: -x[1]):
        print(f"    {n:5d}x  setup={k[0]!r:32s} style={k[1]!r:16s} tf={k[2]!r}")
    if not combos_pre:
        print("    (none)")
    print("\n[2] SQUEEZE combos POST-v322u (since 08:30 ET today):")
    for k, n in sorted(combos_post.items(), key=lambda x: -x[1]):
        print(f"    {n:5d}x  setup={k[0]!r:32s} style={k[1]!r:16s} tf={k[2]!r}")
    if not combos_post:
        print("    (none yet — no squeeze fired since boot)")

    # ── 3. repo-wide style/tf coherence violations ────────────────────
    print("\n[3] ALL style/tf pairs violating STYLE_TO_TIMEFRAME:")
    viol = defaultdict(lambda: [0, ""])
    for t in col.find({}, {"_id": 0, "trade_style": 1, "timeframe": 1,
                           "created_at": 1, "setup_type": 1}):
        style = str(t.get("trade_style") or "").lower()
        tf = str(t.get("timeframe") or "").lower()
        want = STYLE_TO_TIMEFRAME.get(style)
        if want and tf and tf != want:
            k = (style, tf, t.get("setup_type"))
            viol[k][0] += 1
            ca = str(t.get("created_at") or "")
            if ca > viol[k][1]:
                viol[k][1] = ca
    if viol:
        for k, (n, last) in sorted(viol.items(), key=lambda x: -x[1][0])[:25]:
            flag = "  ⚠ POST-v322u!" if last >= V322U_LIVE else ""
            print(f"    {n:5d}x  style={k[0]!r:12s} tf={k[1]!r:10s} "
                  f"setup={k[2]!r:28s} last={last[:19]}{flag}")
        print(f"    ({len(viol)} distinct violating combos; legacy rows expected —"
              f" only ⚠ POST-v322u rows mean the reconciler missed something)")
    else:
        print("    NONE — fully coherent ✅")

    # ── 4. duplicate-row check (old save_trade _id/id split) ─────────
    print("\n[4] DUPLICATE-ROW CHECK (same `id`, multiple Mongo rows):")
    dups = list(col.aggregate([
        {"$group": {"_id": "$id", "n": {"$sum": 1},
                    "statuses": {"$addToSet": "$status"},
                    "syms": {"$addToSet": "$symbol"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 20},
    ]))
    if dups:
        for d in dups:
            print(f"    id={str(d['_id'])[:12]:12s} rows={d['n']} "
                  f"sym={d['syms']} statuses={d['statuses']}")
        print(f"    → {len(dups)}+ duplicate ids found: repair_dedupe sweep IS needed.")
    else:
        print("    NONE — no legacy duplicates; repair_dedupe sweep NOT needed ✅")

    print("\n" + "=" * 78)
    print(f"probe complete {datetime.now(timezone.utc).isoformat()[:19]}Z — no writes performed")


if __name__ == "__main__":
    main()
