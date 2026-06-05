#!/usr/bin/env python3
"""
retrain_readiness.py  (read-only)
=================================
Decides WHETHER and WHEN to retrain after the m-series taxonomy/execution
work (m5 canonical grading, m7 horizon lookback, m8 tidal_wave split,
m9 exit_archetype override). Companion to
memory/TRAINING_PIPELINE_AUDIT_2026-06.md.

Reports a GO / WAIT verdict per dimension:

  1. MODEL STALENESS   — per family: model count + newest/oldest last_trained
                         age. (Models predate the m-series ⇒ freshness retrain.)
  2. CORPUS FRESHNESS  — newest `date` per bar_size in ib_historical_data.
                         (Retrain only worthwhile on a fresh corpus.)
  3. NEW-LABEL ACCRUAL — closed bot_trades (+ alert_outcomes) for canonical
                         tidal_wave (momentum) & fading_bounce since the m8
                         migration. (Gates grade/EV + the m9 override.)
  4. m7 FLIP-RATE      — samples symbols with deep daily history, classifies
                         each at 30-bar vs 252-bar lookback (cache-bypassed),
                         % of market_setup labels that change ⇒ the timeseries-GBM
                         train/serve skew metric.

Read-only Mongo + classifier. Run from the backend dir on the DGX:
    python scripts/retrain_readiness.py
    python scripts/retrain_readiness.py --flip-sample 60 --accrual-since 2026-05-01
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
load_dotenv(_BACKEND / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")

# thresholds (env-tunable)
STALE_DAYS = float(os.environ.get("RETRAIN_STALE_DAYS", 21))
CORPUS_FRESH_DAYS = float(os.environ.get("RETRAIN_CORPUS_FRESH_DAYS", 5))
ACCRUAL_MIN = int(os.environ.get("RETRAIN_ACCRUAL_MIN", 30))
FLIP_MATERIAL_PCT = float(os.environ.get("RETRAIN_FLIP_MATERIAL_PCT", 15))


def _c(t, code):
    return f"\033[{code}m{t}\033[0m" if sys.stdout.isatty() else str(t)


def _go(t): return _c(t, "32")
def _wait(t): return _c(t, "33")
def _bad(t): return _c(t, "31")
def _b(t): return _c(t, "1")


def _age_days(ts) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 86400, 1)
    return None


# ── 1. model staleness ──────────────────────────────────────────────────────

def check_models(db):
    print(_b("\n1) MODEL STALENESS  (timeseries_models)"))
    docs = list(db["timeseries_models"].find(
        {}, {"_id": 0, "model_name": 1, "last_trained": 1, "saved_at": 1,
             "training_samples": 1, "accuracy": 1}))
    if not docs:
        print(_wait("   no models found in timeseries_models — first-train needed"))
        return "WAIT"
    ages = []
    for d in docs:
        a = _age_days(d.get("last_trained") or d.get("saved_at"))
        if a is not None:
            ages.append(a)
    newest = min(ages) if ages else None
    oldest = max(ages) if ages else None
    total_samples = sum(int(d.get("training_samples") or 0) for d in docs)
    print(f"   models present : {len(docs)}")
    print(f"   newest trained : {newest}d ago   oldest: {oldest}d ago")
    print(f"   total training samples (sum) : {total_samples}")
    if newest is None:
        print(_wait("   no usable timestamps"))
        return "WAIT"
    if newest > STALE_DAYS:
        print(_go(f"   → GO: newest model is {newest}d old (> {STALE_DAYS}d) — stale, refresh warranted"))
        return "GO"
    print(_wait(f"   → WAIT: models fresh (newest {newest}d ≤ {STALE_DAYS}d)"))
    return "WAIT"


# ── 2. corpus freshness ─────────────────────────────────────────────────────

def check_corpus(db):
    print(_b("\n2) CORPUS FRESHNESS  (ib_historical_data)"))
    ok = True
    for bar_size in ["1 day", "1 hour", "5 mins"]:
        doc = db["ib_historical_data"].find_one(
            {"bar_size": bar_size}, {"_id": 0, "date": 1}, sort=[("date", -1)])
        if not doc:
            print(f"   {bar_size:<8}: (none)")
            ok = False
            continue
        age = _age_days(doc.get("date"))
        tag = _go("fresh") if (age is not None and age <= CORPUS_FRESH_DAYS) else _wait("stale")
        if age is None or age > CORPUS_FRESH_DAYS:
            ok = ok and (bar_size != "1 day")  # daily freshness is the gate
        print(f"   {bar_size:<8}: newest {doc.get('date')}  ({age}d ago)  {tag}")
    verdict = "GO" if ok else "WAIT"
    print((_go if ok else _wait)(f"   → {verdict}: corpus "
          f"{'fresh enough to retrain on' if ok else 'daily bars stale — backfill before retrain'}"))
    return verdict


# ── 3. new-label accrual ────────────────────────────────────────────────────

def check_accrual(db, since: str):
    print(_b(f"\n3) NEW-LABEL ACCRUAL  (closed since {since})"))
    try:
        from services.setup_taxonomy import canonicalize
    except Exception:
        canonicalize = lambda s: (s or "").lower()  # noqa: E731

    def _count_closed(canon):
        n = 0
        cur = db["bot_trades"].find(
            {"status": {"$in": ["closed", "CLOSED"]},
             "closed_at": {"$gte": since},
             "setup_type": {"$exists": True, "$nin": [None, ""]}},
            {"_id": 0, "setup_type": 1})
        for t in cur:
            if canonicalize(t.get("setup_type")) == canon:
                n += 1
        return n

    res = {}
    for canon in ["tidal_wave", "fading_bounce"]:
        res[canon] = _count_closed(canon)
        tag = _go("enough") if res[canon] >= ACCRUAL_MIN else _wait("accruing")
        print(f"   {canon:<15}: {res[canon]:>4} closed trades   "
              f"(need ≥{ACCRUAL_MIN})  {tag}")
    verdict = "GO" if res.get("tidal_wave", 0) >= ACCRUAL_MIN else "WAIT"
    print((_go if verdict == "GO" else _wait)(
        f"   → {verdict}: new momentum tidal_wave edge "
        f"{'has enough samples' if verdict == 'GO' else 'still accruing'} "
        f"(grade/EV + m9 override gate)"))
    return verdict


# ── 4. m7 market_setup flip-rate ────────────────────────────────────────────

async def _flip_rate(db, sample: int):
    from services.market_setup_classifier import MarketSetupClassifier
    clf = MarketSetupClassifier(db=db)
    # symbols with deep daily history
    syms = db["ib_historical_data"].distinct("symbol", {"bar_size": "1 day"})
    flips, compared, skipped = 0, 0, 0
    examples = []
    for sym in syms:
        if compared >= sample:
            break
        try:
            bars_short = await clf._load_daily_bars(sym, history_days=30)
            bars_deep = await clf._load_daily_bars(sym, history_days=252)
            if len(bars_deep) <= max(len(bars_short), 40):
                skipped += 1
                continue
            clf._cache.pop(sym, None)
            r_short = await clf.classify(sym, daily_bars=bars_short)
            clf._cache.pop(sym, None)
            r_deep = await clf.classify(sym, daily_bars=bars_deep)
            compared += 1
            s1 = getattr(r_short.setup, "value", r_short.setup)
            s2 = getattr(r_deep.setup, "value", r_deep.setup)
            if s1 != s2:
                flips += 1
                if len(examples) < 8:
                    examples.append(f"{sym}: {s1}→{s2}")
        except Exception:
            skipped += 1
            continue
    return flips, compared, skipped, examples


def check_flip_rate(db, sample: int):
    print(_b(f"\n4) m7 market_setup FLIP-RATE  (30-bar vs 252-bar, sample {sample})"))
    try:
        flips, compared, skipped, examples = asyncio.run(_flip_rate(db, sample))
    except Exception as e:
        print(_wait(f"   could not run classifier flip-rate: {e}"))
        return "SKIP"
    if compared == 0:
        print(_wait("   no symbols with deep daily history to compare"))
        return "SKIP"
    pct = round((flips / compared) * 100, 1)
    print(f"   compared {compared} symbols  ({skipped} skipped for shallow history)")
    print(f"   flipped: {flips}  →  {_b(str(pct) + '%')}")
    for ex in examples:
        print(f"      {ex}")
    if pct >= FLIP_MATERIAL_PCT:
        print(_go(f"   → GO: flip-rate {pct}% ≥ {FLIP_MATERIAL_PCT}% — MATERIAL train/serve skew. "
                  f"Relabel timeseries-GBM market_setup with horizon lookback + retrain those GBMs."))
        return "GO"
    print(_wait(f"   → WAIT: flip-rate {pct}% < {FLIP_MATERIAL_PCT}% — skew negligible, no GBM relabel needed"))
    return "WAIT"


def main():
    ap = argparse.ArgumentParser(description="Retrain readiness probe (post m-series)")
    ap.add_argument("--flip-sample", type=int, default=40)
    ap.add_argument("--accrual-since", default="2026-05-01",
                    help="ISO date; count new-label closed trades since this")
    ap.add_argument("--skip-flip", action="store_true", help="skip the slower classifier flip-rate check")
    args = ap.parse_args()

    db = MongoClient(MONGO_URL)[DB_NAME]
    print(_b(f"Retrain-readiness probe → {DB_NAME}  ({datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC})"))

    v_models = check_models(db)
    v_corpus = check_corpus(db)
    v_accrual = check_accrual(db, args.accrual_since)
    v_flip = "SKIP" if args.skip_flip else check_flip_rate(db, args.flip_sample)

    print(_b("\n" + "═" * 64))
    print(_b("RECOMMENDATION"))
    freshness_retrain = (v_models == "GO" and v_corpus == "GO")
    if freshness_retrain:
        print(_go("  • FRESHNESS RETRAIN: GO — models stale + corpus fresh. "
                  "Run a standard trophy retrain (no config change)."))
    else:
        why = "models still fresh" if v_models != "GO" else "daily corpus stale (backfill first)"
        print(_wait(f"  • FRESHNESS RETRAIN: WAIT — {why}."))
    if v_flip == "GO":
        print(_go("  • m7 GBM RELABEL+RETRAIN: GO — material market_setup skew. "
                  "Thread trade_style into training-label generation, then retrain timeseries GBMs."))
    elif v_flip == "WAIT":
        print(_wait("  • m7 GBM RELABEL: not needed — flip-rate below material threshold."))
    if v_accrual == "GO":
        print(_go("  • NEW-LABEL EDGE: tidal_wave momentum has enough samples — "
                  "grade/EV + m9 override are now meaningful for it."))
    else:
        print(_wait("  • NEW-LABEL EDGE: still accruing — let tidal_wave/fading_bounce fills build."))
    print(_b("═" * 64))
    return 0


if __name__ == "__main__":
    sys.exit(main())
