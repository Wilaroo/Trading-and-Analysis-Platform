#!/usr/bin/env python3
"""
diag_tqs_metalabel_readiness.py — READ-ONLY data-sufficiency probe
==================================================================
Answers two backlog gating questions with real numbers:

  Q1 (TQS 0-100 rescale): do we have enough CLOSED, provenance-clean
     trades with TQS scores to prove grade A actually outperforms B?
     Reports per-grade sample counts, win rate, avg/median R, plus the
     raw tqs_score distribution (the "clustering" complaint).
     Split by provenance: bot-fired vs adopted/reconciled/orphan.

  Q2 (meta-labeling): how many closed trades per setup_type? The layer
     is gated on ~50-100 closed per canonical setup.

No writes. Run anytime (market open OK).
"""
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


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


BOT_PROVENANCE = {"bot_fired", "bot", "", None}


def _r_multiple(t):
    """Realized R: net_pnl (fallback pnl/realized_pnl) over planned risk."""
    pnl = t.get("net_pnl")
    if pnl in (None, 0):
        pnl = t.get("realized_pnl") if t.get("realized_pnl") not in (None, 0) else t.get("pnl")
    risk = t.get("risk_amount") or 0
    if pnl is None or not risk:
        return None
    try:
        return float(pnl) / float(risk)
    except (TypeError, ZeroDivisionError):
        return None


def _bucket_stats(rows):
    rs = [r for r in (_r_multiple(t) for t in rows) if r is not None]
    if not rs:
        return "n=%d (no usable R)" % len(rows)
    wins = sum(1 for r in rs if r > 0)
    return (f"n={len(rs):4d}  win%={100.0*wins/len(rs):5.1f}  "
            f"avgR={sum(rs)/len(rs):+.2f}  medR={median(rs):+.2f}")


def main():
    _load_env()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    col = db["bot_trades"]

    closed = list(col.find(
        {"status": {"$regex": "^closed"}},
        {"_id": 0, "tqs_score": 1, "tqs_grade": 1, "unified_grade": 1,
         "entered_by": 1, "setup_type": 1, "net_pnl": 1, "realized_pnl": 1,
         "pnl": 1, "risk_amount": 1, "trade_style": 1}))
    print("=" * 78)
    print(f"TQS / META-LABELING DATA-SUFFICIENCY PROBE — {len(closed)} closed rows")
    print("=" * 78)

    # ── Q1: TQS evidence ─────────────────────────────────────────────
    bot_rows = [t for t in closed if t.get("entered_by") in BOT_PROVENANCE]
    ext_rows = [t for t in closed if t.get("entered_by") not in BOT_PROVENANCE]
    print(f"\n[Q1] PROVENANCE: bot-fired={len(bot_rows)}  "
          f"adopted/reconciled/other={len(ext_rows)}")

    scored = [t for t in bot_rows if t.get("tqs_score") is not None]
    print(f"     bot-fired rows WITH tqs_score: {len(scored)}")
    if scored:
        vals = sorted(float(t["tqs_score"]) for t in scored)
        n = len(vals)
        print(f"     tqs_score distribution: min={vals[0]:.1f} "
              f"p25={vals[n//4]:.1f} p50={vals[n//2]:.1f} "
              f"p75={vals[3*n//4]:.1f} max={vals[-1]:.1f}"
              f"  (clustering = narrow p25→p75 band)")
        by_grade = defaultdict(list)
        for t in scored:
            by_grade[str(t.get("tqs_grade") or t.get("unified_grade") or "?")].append(t)
        print("     per-grade outcomes (bot-fired, closed):")
        for g in sorted(by_grade):
            print(f"       grade {g:>2s}: {_bucket_stats(by_grade[g])}")
        a = [r for g, rows in by_grade.items() if g.upper().startswith("A") for r in rows]
        b = [r for g, rows in by_grade.items() if g.upper().startswith("B") for r in rows]
        verdict = ("SUFFICIENT" if len(a) >= 30 and len(b) >= 30 else "INSUFFICIENT")
        print(f"     → A-grade n={len(a)}, B-grade n={len(b)} — {verdict} for an "
              f"A-vs-B proof (rule of thumb ≥30 each).")
    else:
        print("     → no scored rows: TQS rescale has NO evidence base yet.")

    # ── Q2: meta-labeling sample counts ──────────────────────────────
    per_setup = defaultdict(int)
    for t in bot_rows:
        per_setup[str(t.get("setup_type") or "?")] += 1
    ready_100 = {k: v for k, v in per_setup.items() if v >= 100}
    ready_50 = {k: v for k, v in per_setup.items() if 50 <= v < 100}
    print(f"\n[Q2] CLOSED BOT-FIRED TRADES PER SETUP ({len(per_setup)} setups):")
    for k, v in sorted(per_setup.items(), key=lambda x: -x[1])[:20]:
        tag = " ✅≥100" if v >= 100 else (" 🟡≥50" if v >= 50 else "")
        print(f"       {v:5d}  {k}{tag}")
    print(f"     → meta-labeling READY (≥100): {len(ready_100)} setup(s); "
          f"BORDERLINE (50-99): {len(ready_50)} setup(s).")
    if ready_100:
        print(f"       ready: {sorted(ready_100)}")

    print("\n" + "=" * 78)
    print(f"probe complete {datetime.now(timezone.utc).isoformat()[:19]}Z — no writes")


if __name__ == "__main__":
    main()
