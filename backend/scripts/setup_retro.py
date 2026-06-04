#!/usr/bin/env python3
"""setup_retro.py — Per-setup retro analyzer (v19.34.87)."""
from __future__ import annotations
import argparse, statistics, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _load_env(env_path: Path) -> dict:
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_SUFFIXES = ("_long", "_short", "_l", "_s")
def _base(setup_type: Optional[str]) -> str:
    if not setup_type: return "(unknown)"
    s = setup_type.lower().strip()
    for suf in _SUFFIXES:
        if s.endswith(suf): return s[:-len(suf)]
    return s


def verdict(n, win_pct, avg_r, grade_a_win_pct, min_n):
    if n < min_n: return "INSUFFICIENT_DATA"
    if avg_r < -0.15: return "PAUSE_AND_REVIEW"
    if n >= 20 and win_pct < 25.0: return "PAUSE_AND_REVIEW"
    if avg_r >= 0.05 and win_pct >= 40.0 and n >= 15: return "KEEP_FULL_SIZE"
    if -0.15 <= avg_r < -0.05 and n >= 15: return "REDUCE_SIZE"
    if avg_r >= -0.05 and grade_a_win_pct is not None and grade_a_win_pct >= 50.0:
        return "KEEP_TIGHTEN_ENTRY"
    return "NEUTRAL"


VERDICT_COLOR = {
    "KEEP_FULL_SIZE": "[92m", "KEEP_TIGHTEN_ENTRY": "[96m",
    "NEUTRAL": "[37m", "REDUCE_SIZE": "[93m",
    "PAUSE_AND_REVIEW": "[91m", "INSUFFICIENT_DATA": "[90m",
}
RESET = "[0m"
def color(text, v):
    if not sys.stdout.isatty(): return text
    return f"{VERDICT_COLOR.get(v, '')}{text}{RESET}"


def _dedup_docs(docs):
    """Dedupe alert_outcomes rows.

    Multiple write sites stamp the same close (bracket-OCA cascade,
    workflow-review reentry). Prefer trade_id as the canonical key,
    fall back to (symbol, close_reason, closed_at-minute, r_multiple).
    Keeps the first occurrence (chronologically).
    """
    seen = set(); unique = []
    for d in docs:
        tid = d.get("trade_id")
        if tid:
            key = ("tid", tid)
        else:
            ca = (d.get("closed_at") or "")[:16]  # YYYY-MM-DDTHH:MM
            r  = round(float(d.get("r_multiple") or 0.0), 4)
            key = ("composite", d.get("symbol"),
                   d.get("close_reason"), ca, r)
        if key in seen: continue
        seen.add(key); unique.append(d)
    return unique


def _is_phantom(doc):
    cr = str(doc.get("close_reason") or "").lower()
    return "phantom" in cr



def analyze(db, days, setup_filter, min_n, dedup=False, include_phantom=False):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = {"closed_at": {"$gte": cutoff}, "r_multiple": {"$ne": None}}
    if setup_filter:
        sf = _base(setup_filter)
        q["setup_type"] = {"$regex": f"^{sf}(_long|_short|_l|_s)?$", "$options": "i"}
    raw_docs = list(db.alert_outcomes.find(q, {"_id": 0}))
    n_raw = len(raw_docs)
    if not raw_docs:
        print(f"No alert_outcomes in last {days}d.")
        return []
    n_phantom = sum(1 for d in raw_docs if _is_phantom(d))
    if not include_phantom:
        raw_docs = [d for d in raw_docs if not _is_phantom(d)]
    docs = _dedup_docs(raw_docs) if dedup else raw_docs
    print(f"[dedup] raw={n_raw}  phantom={n_phantom}  "
          f"after_phantom_filter={len(raw_docs)}  unique={len(docs)}")
    buckets = defaultdict(list)
    for d in docs:
        buckets[_base(d.get("setup_type"))].append(d)
    out = []
    for setup, rows in buckets.items():
        rs = [r["r_multiple"] for r in rows if r.get("r_multiple") is not None]
        pnls = [r.get("net_pnl") or r.get("pnl") or 0.0 for r in rows]
        wins = sum(1 for r in rs if r > 0); n = len(rs)
        win_pct = (100.0 * wins / n) if n else 0.0
        avg_r = statistics.fmean(rs) if rs else 0.0
        med_r = statistics.median(rs) if rs else 0.0
        total_pnl = sum(pnls)
        grade_a = [r for r in rows
                   if str(r.get("trade_grade","")).upper() == "A"
                   and r.get("r_multiple") is not None]
        if grade_a:
            ga_wins = sum(1 for r in grade_a if r["r_multiple"] > 0)
            grade_a_win_pct = 100.0 * ga_wins / len(grade_a)
            grade_a_avg_r = statistics.fmean(r["r_multiple"] for r in grade_a)
        else:
            grade_a_win_pct = None; grade_a_avg_r = None
        v = verdict(n, win_pct, avg_r, grade_a_win_pct, min_n)
        out.append({
            "setup": setup, "n": n, "win_pct": win_pct,
            "avg_r": avg_r, "med_r": med_r, "total_pnl": total_pnl,
            "grade_a_n": len(grade_a),
            "grade_a_win_pct": grade_a_win_pct,
            "grade_a_avg_r": grade_a_avg_r,
            "verdict": v, "rows": rows,
        })
    out.sort(key=lambda x: x["total_pnl"])
    return out


def _fmt_pct(x): return "  —  " if x is None else f"{x:>5.1f}%"
def _fmt_r(x): return "  —  " if x is None else f"{x:+.2f}R"


def print_headline(results, days):
    print(f"\n=== Setup retro · last {days}d · sorted by total_pnl (worst first) ===\n")
    hdr = (f"  {'setup':<22} {'n':>4} {'win%':>6} {'avg_R':>7} "
           f"{'med_R':>7} {'total_pnl':>11} {'gA_n':>4} {'gA_win%':>9} "
           f"{'gA_avg_R':>10}   verdict")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for r in results:
        print(f"  {r['setup']:<22} {r['n']:>4} "
              f"{_fmt_pct(r['win_pct'])} {_fmt_r(r['avg_r'])} "
              f"{_fmt_r(r['med_r'])} ${r['total_pnl']:>+10,.2f} "
              f"{r['grade_a_n']:>4} {_fmt_pct(r['grade_a_win_pct']):>9} "
              f"{_fmt_r(r['grade_a_avg_r']):>10}   "
              f"{color(r['verdict'], r['verdict'])}")
    print()


def _grade_breakdown(rows):
    by_g = defaultdict(list)
    for r in rows:
        g = str(r.get("trade_grade","?")).upper() or "?"
        rm = r.get("r_multiple")
        if rm is not None: by_g[g].append(rm)
    order = ["A","B","C","D","F","?"]; out = []; seen=set()
    for g in order:
        if g in by_g:
            seen.add(g); rs = by_g[g]
            out.append((g, len(rs), 100.0*sum(1 for x in rs if x>0)/len(rs),
                        statistics.fmean(rs)))
    for g, rs in by_g.items():
        if g not in seen:
            out.append((g, len(rs), 100.0*sum(1 for x in rs if x>0)/len(rs),
                        statistics.fmean(rs)))
    return out


def print_detail(r):
    print(f"--- {r['setup']}  ({color(r['verdict'], r['verdict'])}) ---")
    print("  grade   n      win%       avg_R")
    for g, n, w, a in _grade_breakdown(r["rows"]):
        print(f"  {g:<5} {n:>4}   {w:>5.1f}%   {a:+.2f}R")
    losers = sorted(
        [row for row in r["rows"] if row.get("r_multiple") is not None],
        key=lambda x: x["r_multiple"])[:5]
    if losers:
        print("  worst 5 closes:")
        for row in losers:
            sym = row.get("symbol","?"); rm = row.get("r_multiple",0.0)
            g = row.get("trade_grade","?")
            reason = (row.get("close_reason") or row.get("outcome") or "?")[:24]
            ca = (row.get("closed_at") or "")[:10]
            print(f"    {sym:<6} {rm:+.2f}R  grade={g!s:<3} "
                  f"reason={reason:<24} closed={ca}")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--setup")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--min-n", type=int, default=10)
    p.add_argument("--concerning-only", action="store_true")
    p.add_argument("--env-path", default=None)
    p.add_argument("--dedup", action="store_true",
                   help="Enable dedup (default OFF — re-entries are distinct trades).")
    p.add_argument("--include-phantom", action="store_true",
                   help="Include rows with close_reason ~ 'phantom' (default OFF).")
    args = p.parse_args()

    if args.env_path:
        env_path = Path(args.env_path)
    else:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        print(f"ERROR: .env not found at {env_path}", file=sys.stderr); sys.exit(2)
    env = _load_env(env_path)
    if "MONGO_URL" not in env or "DB_NAME" not in env:
        print("ERROR: MONGO_URL / DB_NAME missing", file=sys.stderr); sys.exit(2)

    from pymongo import MongoClient
    db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    results = analyze(db, args.days, args.setup, args.min_n,
                      dedup=args.dedup,
                      include_phantom=args.include_phantom)
    if not results: return

    if args.concerning_only:
        results = [r for r in results
                   if r["verdict"] not in ("KEEP_FULL_SIZE", "INSUFFICIENT_DATA")]
        if not results:
            print("(no concerning setups in window)"); return

    print_headline(results, args.days)

    all_rows = [row for r in results for row in r["rows"]]
    offenders = _find_loop_offenders(all_rows, window_min=60, min_stops=3)
    print_loop_offenders(offenders, window_min=60)

    concerning = [r for r in results
                  if r["verdict"] in ("REDUCE_SIZE","PAUSE_AND_REVIEW",
                                       "KEEP_TIGHTEN_ENTRY","NEUTRAL")]
    if concerning:
        print("=== Per-setup detail (concerning verdicts) ===\n")
        for r in concerning: print_detail(r)


def _find_loop_offenders(docs, window_min=60, min_stops=3):
    """Symbols hit stop_loss >= min_stops times within window_min on
    the same setup — wastes capital (ETHU 5x stops in 22min)."""
    from datetime import datetime as _dt
    stops = []
    for d in docs:
        cr = str(d.get("close_reason") or "").lower()
        if "stop" not in cr: continue
        ts = d.get("closed_at")
        if not ts: continue
        try:
            t = _dt.fromisoformat(ts.replace("Z","+00:00"))
        except Exception:
            continue
        stops.append((d.get("symbol","?"), _base(d.get("setup_type")),
                      t, d.get("r_multiple", 0.0), d.get("trade_id")))
    stops.sort(key=lambda x: (x[0], x[1], x[2]))
    offenders = []
    i = 0
    while i < len(stops):
        j = i + 1
        while j < len(stops) and stops[j][0] == stops[i][0] \
                and stops[j][1] == stops[i][1] \
                and (stops[j][2] - stops[i][2]).total_seconds() / 60 <= window_min:
            j += 1
        if j - i >= min_stops:
            cluster = stops[i:j]
            total_r = sum(c[3] for c in cluster)
            span_min = (cluster[-1][2] - cluster[0][2]).total_seconds() / 60
            offenders.append({
                "symbol": cluster[0][0], "setup": cluster[0][1],
                "n_stops": len(cluster), "total_r": total_r,
                "span_min": span_min,
                "first": cluster[0][2].isoformat()[:19],
                "last":  cluster[-1][2].isoformat()[:19],
            })
            i = j
        else:
            i += 1
    offenders.sort(key=lambda x: x["total_r"])
    return offenders


def print_loop_offenders(offenders, window_min):
    if not offenders:
        print("=== Loop offenders: none ===\n"); return
    print(f"=== Loop offenders (>=3 stops within {window_min}min on same setup) ===\n")
    print(f"  {'symbol':<8} {'setup':<22} {'#stops':>6} {'total_R':>10} "
          f"{'span':>8}   first->last")
    for o in offenders:
        print(f"  {o['symbol']:<8} {o['setup']:<22} {o['n_stops']:>6} "
              f"{o['total_r']:+8.2f}R  {o['span_min']:>5.0f}m   "
              f"{o['first']} -> {o['last']}")
    print()

if __name__ == "__main__":
    main()
