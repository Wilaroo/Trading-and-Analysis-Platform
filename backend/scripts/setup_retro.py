#!/usr/bin/env python3
"""
setup_retro.py — Per-setup retro analyzer (v19.34.87).

Answers the question: "which setup_types are bleeding, and why?"

Reads `alert_outcomes` (the canonical post-close R-multiple ledger
fed by both enhanced_scanner.py and pnl_compute.py) for the last N
days and reports:

  1. Headline table: every setup_type ranked by total realized
     net_pnl (worst losers at top).
  2. Per-setup detail for setups that triggered concern thresholds:
     trade_grade A/B/C distribution × win_rate × avg_r.
  3. Top 5 worst losers per concerning setup (symbol, R, grade,
     close_reason) — actual examples to inspect manually.
  4. Verdict per setup, one of:
        KEEP_FULL_SIZE      avg_r >= +0.05R AND win >= 40% AND n >= 15
        KEEP_TIGHTEN_ENTRY  avg_r >= -0.05R AND grade-A win >= 50%
        REDUCE_SIZE         avg_r in [-0.15R, -0.05R) AND n >= 15
        PAUSE_AND_REVIEW    avg_r < -0.15R  OR  (n >= 20 AND win < 25%)
        INSUFFICIENT_DATA   n < 10
        NEUTRAL             didn't match any rule above

Usage:
    python3 backend/scripts/setup_retro.py
    python3 backend/scripts/setup_retro.py --setup vwap_fade
    python3 backend/scripts/setup_retro.py --days 60
    python3 backend/scripts/setup_retro.py --concerning-only

Args:
    --setup NAME           Only analyze one setup_type (base form, e.g.
                           "vwap_fade" matches both "_long" and "_short")
    --days N               Look-back window (default 30)
    --min-n N              Minimum sample size for full verdict (default 10)
    --concerning-only      Skip setups whose verdict is KEEP_FULL_SIZE
                           or INSUFFICIENT_DATA; print only the ones
                           that need action.

Read-only. Does not modify the database.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ----- env loading (no python-dotenv dep) ------------------------------------

def _load_env(env_path: Path) -> dict:
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ----- setup_type normalization ----------------------------------------------

_SUFFIXES = ("_long", "_short", "_l", "_s")


def _base(setup_type: Optional[str]) -> str:
    """Strip directional suffix so vwap_fade_long + vwap_fade_short
    are merged into a single bucket. Mirrors routers/scanner.py's _base()."""
    if not setup_type:
        return "(unknown)"
    s = setup_type.lower().strip()
    for suf in _SUFFIXES:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


# ----- verdict rules ---------------------------------------------------------

def verdict(n: int, win_pct: float, avg_r: float,
            grade_a_win_pct: Optional[float], min_n: int) -> str:
    if n < min_n:
        return "INSUFFICIENT_DATA"
    if avg_r < -0.15:
        return "PAUSE_AND_REVIEW"
    if n >= 20 and win_pct < 25.0:
        return "PAUSE_AND_REVIEW"
    if avg_r >= 0.05 and win_pct >= 40.0 and n >= 15:
        return "KEEP_FULL_SIZE"
    if -0.15 <= avg_r < -0.05 and n >= 15:
        return "REDUCE_SIZE"
    if avg_r >= -0.05 and grade_a_win_pct is not None and grade_a_win_pct >= 50.0:
        return "KEEP_TIGHTEN_ENTRY"
    return "NEUTRAL"


VERDICT_COLOR = {
    "KEEP_FULL_SIZE":     "\033[92m",  # green
    "KEEP_TIGHTEN_ENTRY": "\033[96m",  # cyan
    "NEUTRAL":            "\033[37m",  # light gray
    "REDUCE_SIZE":        "\033[93m",  # yellow
    "PAUSE_AND_REVIEW":   "\033[91m",  # red
    "INSUFFICIENT_DATA":  "\033[90m",  # dim gray
}
RESET = "\033[0m"


def color(text: str, v: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{VERDICT_COLOR.get(v, '')}{text}{RESET}"


# ----- main analysis ---------------------------------------------------------

def analyze(db, days: int, setup_filter: Optional[str], min_n: int):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = {"closed_at": {"$gte": cutoff}, "r_multiple": {"$ne": None}}
    if setup_filter:
        # Match base form: vwap_fade should match _long + _short + plain.
        sf = _base(setup_filter)
        q["setup_type"] = {"$regex": f"^{sf}(_long|_short|_l|_s)?$",
                           "$options": "i"}

    docs = list(db.alert_outcomes.find(q, {"_id": 0}))
    if not docs:
        print(f"No alert_outcomes in last {days}d "
              f"matching filter={setup_filter or '(any)'}.")
        return []

    # Bucket by normalized setup name.
    buckets: dict[str, list] = defaultdict(list)
    for d in docs:
        buckets[_base(d.get("setup_type"))].append(d)

    out = []
    for setup, rows in buckets.items():
        rs = [r["r_multiple"] for r in rows if r.get("r_multiple") is not None]
        pnls = [r.get("net_pnl") or r.get("pnl") or 0.0 for r in rows]
        wins = sum(1 for r in rs if r > 0)
        n = len(rs)
        win_pct = (100.0 * wins / n) if n else 0.0
        avg_r = statistics.fmean(rs) if rs else 0.0
        med_r = statistics.median(rs) if rs else 0.0
        total_pnl = sum(pnls)

        # Grade A subset
        grade_a = [r for r in rows
                   if str(r.get("trade_grade", "")).upper() == "A"
                   and r.get("r_multiple") is not None]
        if grade_a:
            ga_wins = sum(1 for r in grade_a if r["r_multiple"] > 0)
            grade_a_win_pct = 100.0 * ga_wins / len(grade_a)
            grade_a_avg_r = statistics.fmean(r["r_multiple"] for r in grade_a)
        else:
            grade_a_win_pct = None
            grade_a_avg_r = None

        v = verdict(n, win_pct, avg_r, grade_a_win_pct, min_n)

        out.append({
            "setup": setup,
            "n": n,
            "win_pct": win_pct,
            "avg_r": avg_r,
            "med_r": med_r,
            "total_pnl": total_pnl,
            "grade_a_n": len(grade_a),
            "grade_a_win_pct": grade_a_win_pct,
            "grade_a_avg_r": grade_a_avg_r,
            "verdict": v,
            "rows": rows,
        })

    # Sort: most painful (lowest total_pnl) first.
    out.sort(key=lambda x: x["total_pnl"])
    return out


# ----- pretty printers -------------------------------------------------------

def _fmt_pct(x: Optional[float]) -> str:
    return "  —  " if x is None else f"{x:>5.1f}%"


def _fmt_r(x: Optional[float]) -> str:
    return "  —  " if x is None else f"{x:+.2f}R"


def print_headline(results, days):
    print()
    print(f"=== Setup retro · last {days}d · sorted by total_pnl (worst first) ===")
    print()
    cols = ("setup", "n", "win%", "avg_R", "med_R", "total_pnl",
            "grade-A n", "grade-A win%", "grade-A avg_R", "verdict")
    header = (f"  {cols[0]:<22} {cols[1]:>4} {cols[2]:>6} "
              f"{cols[3]:>7} {cols[4]:>7} {cols[5]:>11} "
              f"{cols[6]:>9} {cols[7]:>12} {cols[8]:>13}   {cols[9]}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in results:
        line = (f"  {r['setup']:<22} {r['n']:>4} "
                f"{_fmt_pct(r['win_pct'])} {_fmt_r(r['avg_r'])} "
                f"{_fmt_r(r['med_r'])} "
                f"${r['total_pnl']:>+10,.2f} "
                f"{r['grade_a_n']:>9} "
                f"{_fmt_pct(r['grade_a_win_pct']):>12} "
                f"{_fmt_r(r['grade_a_avg_r']):>13}   "
                f"{color(r['verdict'], r['verdict'])}")
        print(line)
    print()


def _grade_breakdown(rows):
    """Return [(grade, n, win_pct, avg_r), ...] sorted A->C->unknown."""
    by_g: dict[str, list] = defaultdict(list)
    for r in rows:
        g = str(r.get("trade_grade", "?")).upper() or "?"
        rm = r.get("r_multiple")
        if rm is not None:
            by_g[g].append(rm)
    grade_order = ["A", "B", "C", "D", "F", "?"]
    out = []
    seen = set()
    for g in grade_order:
        if g in by_g:
            seen.add(g)
            rs = by_g[g]
            n = len(rs)
            win = 100.0 * sum(1 for x in rs if x > 0) / n
            avg = statistics.fmean(rs)
            out.append((g, n, win, avg))
    for g, rs in by_g.items():
        if g not in seen:
            n = len(rs)
            win = 100.0 * sum(1 for x in rs if x > 0) / n
            avg = statistics.fmean(rs)
            out.append((g, n, win, avg))
    return out


def print_detail(r):
    print(f"--- {r['setup']}  ({color(r['verdict'], r['verdict'])}) ---")
    breakdown = _grade_breakdown(r["rows"])
    print("  grade   n      win%       avg_R")
    for g, n, win, avg in breakdown:
        print(f"  {g:<5} {n:>4}   {win:>5.1f}%   {avg:+.2f}R")

    # Top 5 worst losers
    losers = sorted(
        [row for row in r["rows"] if row.get("r_multiple") is not None],
        key=lambda x: x["r_multiple"],
    )[:5]
    if losers:
        print("  worst 5 closes:")
        for row in losers:
            sym = row.get("symbol", "?")
            rm = row.get("r_multiple", 0.0)
            g = row.get("trade_grade", "?")
            reason = (row.get("close_reason") or row.get("outcome")
                      or "?")[:24]
            ca = (row.get("closed_at") or "")[:10]
            print(f"    {sym:<6} {rm:+.2f}R  grade={g!s:<3} "
                  f"reason={reason:<24} closed={ca}")
    print()


# ----- entrypoint ------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--setup", help="One setup_type to analyze (base form).")
    p.add_argument("--days", type=int, default=30,
                   help="Look-back window in days (default 30).")
    p.add_argument("--min-n", type=int, default=10,
                   help="Min sample size for full verdict (default 10).")
    p.add_argument("--concerning-only", action="store_true",
                   help="Suppress KEEP_FULL_SIZE / INSUFFICIENT_DATA rows.")
    p.add_argument("--env-path", default=None,
                   help="Path to backend/.env (default: auto-detect).")
    args = p.parse_args()

    # Locate .env. Default: <repo>/backend/.env where repo is auto-detected
    # by walking up from this script's location.
    if args.env_path:
        env_path = Path(args.env_path)
    else:
        here = Path(__file__).resolve()
        # scripts/setup_retro.py → backend/scripts/setup_retro.py → backend/.env
        env_path = here.parent.parent / ".env"
    if not env_path.exists():
        print(f"ERROR: .env not found at {env_path}", file=sys.stderr)
        sys.exit(2)

    env = _load_env(env_path)
    if "MONGO_URL" not in env or "DB_NAME" not in env:
        print("ERROR: MONGO_URL / DB_NAME missing from .env", file=sys.stderr)
        sys.exit(2)

    # Lazy import so the script's --help works even if pymongo is missing.
    from pymongo import MongoClient  # type: ignore
    db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]

    results = analyze(db, args.days, args.setup, args.min_n)
    if not results:
        return

    if args.concerning_only:
        results = [r for r in results
                   if r["verdict"] not in ("KEEP_FULL_SIZE", "INSUFFICIENT_DATA")]
        if not results:
            print("(no concerning setups in window)")
            return

    print_headline(results, args.days)

    concerning = [r for r in results
                  if r["verdict"] in ("REDUCE_SIZE", "PAUSE_AND_REVIEW",
                                       "KEEP_TIGHTEN_ENTRY", "NEUTRAL")]
    if concerning:
        print("=== Per-setup detail (concerning verdicts) ===\n")
        for r in concerning:
            print_detail(r)


if __name__ == "__main__":
    main()
