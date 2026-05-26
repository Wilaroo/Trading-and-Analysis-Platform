#!/usr/bin/env python3
"""bar_pipeline_diagnostic_phase_d.py — v19.34.155 (P2-2)

Read-only diagnostic for the `ib_historical_data` bar pipeline. Runs
six independent checks and reports PASS / WARN / FAIL per check.

Six checks
----------
1.  RECENCY        Latest `collected_at` per (symbol, bar_size) over
                   the lookback window. WARN if any tracked symbol is
                   silent for > sla minutes during what should be an
                   RTH session.
2.  RTH_VOLUME     For each tracked symbol's "1 min" bars, count per
                   trading day. PASS if ≥ 370 (95% of the 390-minute
                   RTH session); WARN 300-370; FAIL < 300.
3.  GAPS           For each (symbol, day) `1 min` series, find runs of
                   ≥ 3 consecutive missing minutes. Worst 10 reported.
4.  AGG_CONSISTENT For a sampled (symbol, day), verify the `5 mins`
                   bars roll up cleanly from the underlying `1 min`
                   bars (open=first.open, close=last.close,
                   high=max.high, low=min.low, vol=sum.volume).
5.  UNIVERSE       Compare `smart_watchlist` collection (the bot's
                   active scanner universe) to the symbols actually
                   delivering bars in the last 24h. Lists missing
                   subscriptions.
6.  QUARTER_SLICE  Optional via `--quarter Q1|Q2|Q3|Q4 --year 2025`.
                   Re-runs checks 1-3 over the specified calendar
                   quarter — useful for postmortem of bar-pipeline
                   restoration history.

Usage (on DGX)
--------------
    PYTHONPATH=backend python3 backend/scripts/bar_pipeline_diagnostic_phase_d.py
    PYTHONPATH=backend python3 backend/scripts/bar_pipeline_diagnostic_phase_d.py --json
    PYTHONPATH=backend python3 backend/scripts/bar_pipeline_diagnostic_phase_d.py --quarter Q4 --year 2025
    PYTHONPATH=backend python3 backend/scripts/bar_pipeline_diagnostic_phase_d.py --lookback-days 7

Exit codes: 0 = all PASS, 1 = at least one WARN, 2 = at least one FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta, timezone

from typing import Any, Dict, List, Optional, Tuple

# Path setup so .env loading works the same way the backend does.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_ROOT, ".env"))
except Exception:
    pass


# ── Severities ────────────────────────────────────────────────────────
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
SEV_RANK = {PASS: 0, WARN: 1, FAIL: 2}


def _max_sev(a: str, b: str) -> str:
    return a if SEV_RANK.get(a, 0) >= SEV_RANK.get(b, 0) else b


def _date_str(dt) -> str:
    if isinstance(dt, str):
        return dt[:10]
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    return str(dt)[:10]


def _parse_bar_date(raw) -> Optional[datetime]:
    """The `date` field on stored bars can be a Python datetime, a
    string ISO timestamp, or sometimes a numeric epoch. Best-effort
    parse to a UTC-naive datetime."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(raw))
        except (OSError, ValueError):
            return None
    if isinstance(raw, str):
        # Common shapes: "2026-02-13 09:30:00", "2026-02-13T09:30:00",
        # "20260213 09:30:00 US/Eastern", "20260213" (1-day bar).
        s = raw.strip().replace("T", " ")
        # Strip TZ suffix if present.
        if " US/" in s:
            s = s.split(" US/")[0]
        if " UTC" in s:
            s = s.replace(" UTC", "")
        for fmt in (
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            "%Y%m%d %H:%M:%S", "%Y%m%d %H:%M",
            "%Y-%m-%d", "%Y%m%d",
        ):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _quarter_window(quarter: str, year: int) -> Tuple[datetime, datetime]:
    q_map = {
        "Q1": (1, 3), "Q2": (4, 6), "Q3": (7, 9), "Q4": (10, 12),
    }
    if quarter not in q_map:
        raise ValueError(f"bad quarter '{quarter}'; expected Q1|Q2|Q3|Q4")
    m_start, m_end = q_map[quarter]
    start = datetime(year, m_start, 1)
    if m_end == 12:
        end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(year, m_end + 1, 1) - timedelta(seconds=1)
    return start, end


# ── Mongo ────────────────────────────────────────────────────────────


def _connect_db():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        print("[FATAL] MONGO_URL / DB_NAME not set in backend/.env",
              file=sys.stderr)
        sys.exit(3)
    return MongoClient(mongo_url).get_database(db_name)


# ── Checks ───────────────────────────────────────────────────────────


def check_recency(db, *, lookback_days: int, sla_minutes: int) -> dict:
    """Check 1: latest collected_at per (symbol, bar_size)."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    pipeline = [
        {"$match": {"collected_at": {"$gte": cutoff_iso}}},
        {"$group": {
            "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
            "latest": {"$max": "$collected_at"},
            "count": {"$sum": 1},
        }},
    ]
    rows = list(db.ib_historical_data.aggregate(pipeline, allowDiskUse=True))
    now = datetime.now(timezone.utc)
    sla = timedelta(minutes=sla_minutes)
    stale: List[dict] = []
    for r in rows:
        try:
            latest_dt = datetime.fromisoformat(r["latest"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            continue
        if (now - latest_dt) > sla:
            stale.append({
                "symbol": r["_id"]["symbol"],
                "bar_size": r["_id"]["bar_size"],
                "latest": r["latest"],
                "lag_minutes": int((now - latest_dt).total_seconds() // 60),
                "bar_count_in_window": r["count"],
            })
    stale.sort(key=lambda s: -s["lag_minutes"])
    severity = WARN if stale else PASS
    return {
        "check": "RECENCY",
        "severity": severity,
        "summary": (f"{len(stale)} of {len(rows)} (symbol, bar_size) "
                    f"pairs are > {sla_minutes}min stale"),
        "lookback_days": lookback_days,
        "sla_minutes": sla_minutes,
        "stale_top": stale[:10],
        "total_pairs": len(rows),
    }


def check_rth_volume(db, *, lookback_days: int,
                     expect_full: int = 390, threshold_pct: float = 0.95,
                     fail_pct: float = 0.77) -> dict:
    """Check 2: 1-min bars per RTH day per symbol."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rows = list(db.ib_historical_data.find(
        {"bar_size": "1 min", "collected_at": {"$gte": cutoff_iso}},
        {"_id": 0, "symbol": 1, "date": 1, "collected_at": 1},
    ))
    per_day: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in rows:
        d = _parse_bar_date(r.get("date"))
        if not d:
            continue
        key = (r["symbol"], d.strftime("%Y-%m-%d"))
        per_day[key] += 1

    pass_thr = int(expect_full * threshold_pct)
    fail_thr = int(expect_full * fail_pct)
    findings: List[dict] = []
    sev = PASS
    for (sym, day), cnt in per_day.items():
        # Skip weekends entirely (the pipeline shouldn't be producing
        # RTH 1-min bars on Sat/Sun anyway).
        try:
            if datetime.strptime(day, "%Y-%m-%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        if cnt < fail_thr:
            findings.append({"symbol": sym, "day": day, "count": cnt, "severity": FAIL})
            sev = _max_sev(sev, FAIL)
        elif cnt < pass_thr:
            findings.append({"symbol": sym, "day": day, "count": cnt, "severity": WARN})
            sev = _max_sev(sev, WARN)
    findings.sort(key=lambda f: f["count"])
    return {
        "check": "RTH_VOLUME",
        "severity": sev,
        "summary": (f"{len(findings)} (symbol, day) pairs under {pass_thr} "
                    f"1-min bars (of expected {expect_full})"),
        "expect_full_session": expect_full,
        "pass_threshold": pass_thr,
        "fail_threshold": fail_thr,
        "low_count_top": findings[:10],
        "total_symbol_days_checked": len(per_day),
    }


def check_gaps(db, *, lookback_days: int, min_gap: int = 3) -> dict:
    """Check 3: runs of ≥ `min_gap` consecutive missing 1-min bars
    during RTH (09:30–16:00 ET-implied UTC range)."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rows = list(db.ib_historical_data.find(
        {"bar_size": "1 min", "collected_at": {"$gte": cutoff_iso}},
        {"_id": 0, "symbol": 1, "date": 1},
    ))
    # Group bar timestamps per (symbol, day).
    series: Dict[Tuple[str, str], List[datetime]] = defaultdict(list)
    for r in rows:
        dt = _parse_bar_date(r.get("date"))
        if not dt:
            continue
        # Only RTH-ish minutes (cheap heuristic — pipeline already
        # filters to RTH; this guards against edge cases like
        # extended-hours leakage that would inflate gap detection).
        if dt.time() < dtime(9, 30) or dt.time() > dtime(16, 0):
            continue
        series[(r["symbol"], dt.strftime("%Y-%m-%d"))].append(dt)

    gaps_found: List[dict] = []
    for (sym, day), times in series.items():
        try:
            if datetime.strptime(day, "%Y-%m-%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        times.sort()
        biggest_gap = 0
        for i in range(1, len(times)):
            delta_min = int((times[i] - times[i - 1]).total_seconds() // 60)
            if delta_min > biggest_gap:
                biggest_gap = delta_min
        if biggest_gap >= min_gap:
            gaps_found.append({
                "symbol": sym,
                "day": day,
                "biggest_gap_minutes": biggest_gap,
                "bar_count": len(times),
            })
    gaps_found.sort(key=lambda f: -f["biggest_gap_minutes"])
    sev = PASS if not gaps_found else (
        FAIL if any(g["biggest_gap_minutes"] >= 15 for g in gaps_found) else WARN
    )
    return {
        "check": "GAPS",
        "severity": sev,
        "summary": (f"{len(gaps_found)} (symbol, day) pairs have intra-session "
                    f"gaps ≥ {min_gap}min"),
        "min_gap_minutes_flagged": min_gap,
        "worst_gaps_top": gaps_found[:10],
        "total_symbol_days_checked": len(series),
    }


def check_aggregation_consistency(db, *, sample_size: int = 5) -> dict:
    """Check 4: sampled (symbol, day) — verify `5 mins` rolls up from
    `1 min`. Random-ish sample via natural Mongo order."""
    pipeline = [
        {"$match": {"bar_size": "5 mins"}},
        {"$sample": {"size": sample_size}},
        {"$project": {"_id": 0, "symbol": 1, "date": 1}},
    ]
    samples = list(db.ib_historical_data.aggregate(pipeline))
    findings: List[dict] = []
    checked = 0
    for s in samples:
        dt = _parse_bar_date(s.get("date"))
        if not dt:
            continue
        five_min_start = dt
        five_min_end = dt + timedelta(minutes=5)
        # Fetch the 1-min bars covering the same window.
        # Date storage isn't always a real datetime, so we use a string
        # range based on the 5-min bar's own day.
        day_str = dt.strftime("%Y-%m-%d")
        one_min_rows = list(db.ib_historical_data.find({
            "symbol": s["symbol"], "bar_size": "1 min",
        }, {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1,
            "close": 1, "volume": 1}))
        candidates = []
        for r in one_min_rows:
            r_dt = _parse_bar_date(r.get("date"))
            if not r_dt:
                continue
            if r_dt.strftime("%Y-%m-%d") != day_str:
                continue
            if five_min_start <= r_dt < five_min_end:
                candidates.append((r_dt, r))
        if not candidates:
            findings.append({
                "symbol": s["symbol"], "date": s.get("date"),
                "issue": "no underlying 1-min bars found for the 5-min window",
                "severity": WARN,
            })
            continue
        candidates.sort(key=lambda t: t[0])
        bars = [c[1] for c in candidates]
        # Fetch the 5-min row itself for comparison.
        five = db.ib_historical_data.find_one({
            "symbol": s["symbol"], "bar_size": "5 mins", "date": s.get("date"),
        })
        if not five:
            continue
        checked += 1
        try:
            exp_open = float(bars[0]["open"])
            exp_close = float(bars[-1]["close"])
            exp_high = max(float(b["high"]) for b in bars)
            exp_low = min(float(b["low"]) for b in bars)
            exp_vol = sum(float(b.get("volume") or 0) for b in bars)
        except (KeyError, TypeError, ValueError):
            continue
        tol = 1e-4
        mismatches = []
        if abs(float(five["open"]) - exp_open) > tol:
            mismatches.append(f"open {five['open']}≠{exp_open}")
        if abs(float(five["close"]) - exp_close) > tol:
            mismatches.append(f"close {five['close']}≠{exp_close}")
        if abs(float(five["high"]) - exp_high) > tol:
            mismatches.append(f"high {five['high']}≠{exp_high}")
        if abs(float(five["low"]) - exp_low) > tol:
            mismatches.append(f"low {five['low']}≠{exp_low}")
        # Volume tolerance is looser: IB sometimes reports 5-min volume
        # as an aggregated tick count that doesn't match 1-min sums.
        if exp_vol > 0 and abs(float(five.get("volume") or 0) - exp_vol) / max(exp_vol, 1.0) > 0.10:
            mismatches.append(f"volume {five.get('volume')}≠{exp_vol} (>10%)")
        if mismatches:
            findings.append({
                "symbol": s["symbol"], "date": s.get("date"),
                "mismatches": mismatches, "bars_in_window": len(bars),
                "severity": WARN,
            })
    sev = WARN if findings else PASS
    return {
        "check": "AGG_CONSISTENT",
        "severity": sev,
        "summary": (f"{len(findings)} of {checked} sampled 5-min bars "
                    f"failed to match their 1-min roll-up"),
        "sample_size_requested": sample_size,
        "actually_checked": checked,
        "findings": findings,
    }


def check_universe(db, *, lookback_hours: int = 24) -> dict:
    """Check 5: smart_watchlist vs symbols delivering bars."""
    # Universe — the bot's active scanner watchlist.
    universe_docs = list(db.smart_watchlist.find(
        {"_type": "watchlist_item"},
        {"_id": 0, "symbol": 1, "pinned": 1, "expires_at": 1},
    ))
    universe = {(d.get("symbol") or "").upper() for d in universe_docs if d.get("symbol")}

    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    delivered = set(
        (s or "").upper()
        for s in db.ib_historical_data.distinct(
            "symbol", {"collected_at": {"$gte": cutoff_iso}}
        )
        if s
    )

    missing = sorted(universe - delivered)
    extra = sorted(delivered - universe)

    sev = WARN if missing else PASS
    return {
        "check": "UNIVERSE",
        "severity": sev,
        "summary": (f"{len(missing)} of {len(universe)} watchlist symbols had "
                    f"NO bars in last {lookback_hours}h"),
        "universe_size": len(universe),
        "delivered_in_window": len(delivered),
        "missing_from_pipeline_top": missing[:20],
        "extra_not_in_watchlist_top": extra[:20],
        "lookback_hours": lookback_hours,
    }


def check_quarter_slice(db, *, quarter: str, year: int) -> dict:
    """Check 6: re-run RECENCY/RTH_VOLUME/GAPS over a calendar quarter."""
    start, end = _quarter_window(quarter, year)
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    rows = list(db.ib_historical_data.find(
        {"bar_size": "1 min",
         "collected_at": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0, "symbol": 1, "date": 1},
    ))
    per_day: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in rows:
        d = _parse_bar_date(r.get("date"))
        if not d:
            continue
        per_day[(r["symbol"], d.strftime("%Y-%m-%d"))] += 1

    findings_low: List[dict] = []
    for (sym, day), cnt in per_day.items():
        try:
            if datetime.strptime(day, "%Y-%m-%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        if cnt < 300:
            findings_low.append({"symbol": sym, "day": day, "count": cnt})

    findings_low.sort(key=lambda f: f["count"])
    sev = PASS if not findings_low else (
        FAIL if len(findings_low) > 50 else WARN
    )
    return {
        "check": "QUARTER_SLICE",
        "severity": sev,
        "summary": (f"{quarter} {year}: {len(findings_low)} (symbol, day) "
                    f"pairs had < 300 1-min bars"),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "total_symbol_days_in_window": len(per_day),
        "low_volume_top": findings_low[:20],
    }


# ── Pretty printer ───────────────────────────────────────────────────


def _emoji(sev: str) -> str:
    return {PASS: "🟢", WARN: "🟡", FAIL: "🔴"}.get(sev, "⚪")


def _print_report(report: dict) -> None:
    print("─" * 78)
    print(f"  BAR PIPELINE DIAGNOSTIC — Phase D  (run: {report['run_at']})")
    print(f"  overall: {_emoji(report['overall'])} {report['overall']}")
    print("─" * 78)
    for c in report["checks"]:
        print(f"  {_emoji(c['severity'])} {c['severity']:<4}  {c['check']}")
        print(f"        {c['summary']}")
        if c["check"] == "RECENCY" and c.get("stale_top"):
            for s in c["stale_top"][:5]:
                print(f"          • {s['symbol']:<8} {s['bar_size']:<8} "
                      f"lag={s['lag_minutes']}min latest={s['latest']}")
        elif c["check"] == "RTH_VOLUME" and c.get("low_count_top"):
            for f in c["low_count_top"][:5]:
                print(f"          • {f['symbol']:<8} {f['day']}  "
                      f"count={f['count']}/{c['expect_full_session']}  [{f['severity']}]")
        elif c["check"] == "GAPS" and c.get("worst_gaps_top"):
            for f in c["worst_gaps_top"][:5]:
                print(f"          • {f['symbol']:<8} {f['day']}  "
                      f"biggest_gap={f['biggest_gap_minutes']}min  bars={f['bar_count']}")
        elif c["check"] == "AGG_CONSISTENT" and c.get("findings"):
            for f in c["findings"][:5]:
                ms = ", ".join(f.get("mismatches") or [])
                print(f"          • {f['symbol']:<8} {f.get('date')}  {ms or f.get('issue')}")
        elif c["check"] == "UNIVERSE":
            if c.get("missing_from_pipeline_top"):
                print(f"          missing from pipeline: "
                      f"{', '.join(c['missing_from_pipeline_top'][:10])}"
                      + ("…" if len(c['missing_from_pipeline_top']) > 10 else ""))
            if c.get("extra_not_in_watchlist_top"):
                print(f"          extra (delivered but not watch'd): "
                      f"{', '.join(c['extra_not_in_watchlist_top'][:10])}"
                      + ("…" if len(c['extra_not_in_watchlist_top']) > 10 else ""))
        elif c["check"] == "QUARTER_SLICE" and c.get("low_volume_top"):
            for f in c["low_volume_top"][:5]:
                print(f"          • {f['symbol']:<8} {f['day']}  count={f['count']}")
        print()
    print("─" * 78)


# ── Main ─────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lookback-days", type=int, default=7,
                    help="Days of history for recency/RTH/gaps checks (default 7)")
    ap.add_argument("--sla-minutes", type=int, default=15,
                    help="Max acceptable lag for RECENCY check (default 15 min)")
    ap.add_argument("--min-gap", type=int, default=3,
                    help="Minimum minute-gap to flag in GAPS check (default 3)")
    ap.add_argument("--quarter", choices=["Q1", "Q2", "Q3", "Q4"], default=None,
                    help="Optional: run QUARTER_SLICE check for this quarter")
    ap.add_argument("--year", type=int, default=datetime.now().year,
                    help="Calendar year for --quarter (default current year)")
    ap.add_argument("--json", action="store_true",
                    help="Emit raw JSON instead of pretty report")
    args = ap.parse_args()

    db = _connect_db()
    checks: List[dict] = []
    checks.append(check_recency(
        db, lookback_days=args.lookback_days,
        sla_minutes=args.sla_minutes,
    ))
    checks.append(check_rth_volume(db, lookback_days=args.lookback_days))
    checks.append(check_gaps(
        db, lookback_days=args.lookback_days, min_gap=args.min_gap,
    ))
    checks.append(check_aggregation_consistency(db, sample_size=5))
    checks.append(check_universe(db, lookback_hours=24))
    if args.quarter:
        checks.append(check_quarter_slice(db, quarter=args.quarter, year=args.year))

    overall = PASS
    for c in checks:
        overall = _max_sev(overall, c["severity"])

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": args.lookback_days,
        "quarter": args.quarter,
        "year": args.year if args.quarter else None,
        "overall": overall,
        "checks": checks,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    return {PASS: 0, WARN: 1, FAIL: 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
