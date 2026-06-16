#!/usr/bin/env python3
"""diag_setup_trade_catalog_deep_audit.py  —  READ-ONLY  (2026-06-16)

Comprehensive census of the SentCom setup + trade landscape. Run before
making catalog-wide gating, scoring, or training decisions.

Sections (all read-only against bot_trades):
  1. Census         — every setup_type ever observed: count, first/last
                      fire, last-fire age, status (live/dead).
  2. Style mapping  — setup_type × trade_style cross-tab. Surfaces
                      setups that span styles (data-integrity flag).
  3. Bar dependency — heuristic flagging:
                        • DAILY-BAR (style ∈ multi_day/swing/position/
                          investment OR name contains "daily"|"weekly"|
                          "stage_2"|"trend_"|"rs_leader")
                        • INTRADAY  (style intraday/scalp AND no daily
                          hint)
                        • UNKNOWN   (no style)
  4. Performance    — per setup_type, lifetime: n, win-rate, breakeven %,
                      avg net_pnl, avg pnl_pct, avg hold_seconds,
                      avg MAE_R, avg MFE_R, expectancy_R.
  5. Entry time     — for each setup, distribution across RTH buckets
                      (pre-09:30 ET, 09:30-10:00, 10:00-15:30, 15:30-16:00,
                      post-16:00) — proves when each is "alive".
  6. Quality grade  — quality_grade × setup_type matrix (A/B/C/F).
  7. Source         — entered_by × setup_type (bot_fired vs reconciled
                      vs manual). Surfaces orphan / reconciled clutter.
  8. EOD exposure   — close_at_eod & status=closed at EOD vs intraday
                      close, per setup_type. Shows which setups SHOULD
                      hold overnight but DON'T (or vice versa).
  9. Dead setups    — fired in last 90d but ZERO firings in last 14d.
                      Candidates for archival or scanner-disable.
 10. Health flags   — composite warnings (e.g., setup with ≥20 firings
                      but 0% win-rate; setup with style mismatch; setup
                      whose name suggests daily but classified intraday).

Env knobs:
  V320_AUDIT_LOOKBACK_DAYS    (default 90)
  V320_DEAD_SETUP_MAX_AGE     (default 14)
  V320_MIN_TRADE_COUNT        (default 10  — perf rows below N suppressed)

Run from repo root:
  .venv/bin/python backend/scripts/diag_setup_trade_catalog_deep_audit.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

ET = ZoneInfo("America/New_York")
LOOKBACK = int(os.environ.get("V320_AUDIT_LOOKBACK_DAYS", "90"))
DEAD_AGE = int(os.environ.get("V320_DEAD_SETUP_MAX_AGE", "14"))
MIN_N = int(os.environ.get("V320_MIN_TRADE_COUNT", "10"))

DAILY_HINTS = ("daily", "weekly", "stage_2", "trend_", "rs_leader",
               "swing", "multi_day", "position_")
DAILY_STYLES = {"multi_day", "swing", "position", "investment"}


def hr(t):
    print("\n" + "=" * 100 + f"\n  {t}\n" + "=" * 100)


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


def _bar_dep(setup, style):
    name = (setup or "").lower()
    s = (style or "").lower()
    if s in DAILY_STYLES:
        return "DAILY"
    if any(h in name for h in DAILY_HINTS):
        return "DAILY"
    if s in ("intraday", "scalp"):
        return "INTRADAY"
    return "UNKNOWN"


def _et_bucket(ts_et):
    mins = ts_et.hour * 60 + ts_et.minute
    if mins < 9 * 60 + 30:
        return "pre_open"
    if mins < 10 * 60:
        return "0930_1000"
    if mins < 15 * 60 + 30:
        return "1000_1530"
    if mins <= 16 * 60:
        return "1530_1600"
    return "post_close"


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    print(f"diag_setup_trade_catalog_deep_audit  "
          f"({datetime.now(ET):%Y-%m-%d %H:%M ET}, read-only)")
    print(f"  lookback={LOOKBACK}d  dead_age={DEAD_AGE}d  min_n_perf={MIN_N}")

    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK)).isoformat()
    proj = {"_id": 0, "id": 1, "symbol": 1,
            "created_at": 1, "executed_at": 1, "closed_at": 1,
            "trade_style": 1, "setup_type": 1, "setup_variant": 1,
            "direction": 1, "status": 1, "entered_by": 1,
            "net_pnl": 1, "realized_pnl": 1, "pnl_pct": 1,
            "mae_r": 1, "mfe_r": 1, "hold_seconds": 1,
            "quality_grade": 1, "close_at_eod": 1, "close_reason": 1,
            "synthetic_source": 1}
    rows = list(db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": since}},
                 {"executed_at": {"$gte": since}}]},
        proj,
    ))
    n_total = len(rows)
    print(f"  loaded {n_total:,} bot_trades from last {LOOKBACK}d")

    if n_total == 0:
        print("  no trades in window. exit.")
        return

    # Pre-compute parsed timestamps
    for r in rows:
        r["_t_exec"] = _parse(r.get("executed_at") or r.get("created_at"))
        r["_t_close"] = _parse(r.get("closed_at"))

    # ── Section 1 ────────────────────────────────────────────────────────
    hr("Section 1 — Setup census (every setup_type fired in window)")
    by_setup = defaultdict(list)
    for r in rows:
        by_setup[r.get("setup_type") or "<none>"].append(r)
    print(f"  distinct setup_types: {len(by_setup)}")
    print(f"\n  {'setup_type':>32}  {'n':>5}  {'first_fire':>11}  "
          f"{'last_fire':>11}  {'last_age_d':>11}  status")
    now = datetime.now(timezone.utc)
    setup_summaries = {}
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1])):
        firsts = [r["_t_exec"] for r in lst if r["_t_exec"]]
        lasts = [r["_t_exec"] for r in lst if r["_t_exec"]]
        first = min(firsts) if firsts else None
        last = max(lasts) if lasts else None
        age_days = (now - last).days if last else None
        status = "DEAD" if age_days is not None and age_days > DEAD_AGE else "live"
        setup_summaries[s] = {"n": len(lst), "first": first, "last": last,
                              "age_days": age_days, "status": status}
        print(f"  {s:>32}  {len(lst):>5}  "
              f"{first.strftime('%Y-%m-%d') if first else '—':>11}  "
              f"{last.strftime('%Y-%m-%d') if last else '—':>11}  "
              f"{age_days if age_days is not None else '—':>11}  {status}")

    # ── Section 2 — style mapping ────────────────────────────────────────
    hr("Section 2 — setup_type × trade_style cross-tab (top 30 by volume)")
    cross = defaultdict(Counter)
    for r in rows:
        cross[r.get("setup_type") or "<none>"][
            (r.get("trade_style") or "<none>").lower()] += 1
    top30 = sorted(cross.items(), key=lambda kv: -sum(kv[1].values()))[:30]
    all_styles = set()
    for _, styles in top30:
        all_styles.update(styles.keys())
    styles_ordered = sorted(all_styles)
    print(f"  {'setup_type':>32}  " +
          "".join(f"{s[:10]:>11}" for s in styles_ordered) + "  multi?")
    multi_style_setups = []
    for s, styles in top30:
        cells = "".join(f"{styles.get(st, 0):>11}" for st in styles_ordered)
        n_styles = sum(1 for v in styles.values() if v > 0)
        multi = "⚠️ YES" if n_styles > 1 else ""
        if n_styles > 1:
            multi_style_setups.append((s, dict(styles)))
        print(f"  {s:>32}  {cells}  {multi}")
    if multi_style_setups:
        print(f"\n  ⚠️ {len(multi_style_setups)} setups split across multiple "
              f"trade_styles — possible data-integrity issue:")
        for s, st in multi_style_setups:
            print(f"    • {s}: {st}")

    # ── Section 3 — bar dependency ───────────────────────────────────────
    hr("Section 3 — Bar-dependency classification")
    dep_counts = Counter()
    dep_by_setup = {}
    for s, lst in by_setup.items():
        st_dom = Counter(r.get("trade_style") for r in lst).most_common(1)[0][0]
        dep = _bar_dep(s, st_dom)
        dep_counts[dep] += len(lst)
        dep_by_setup[s] = (dep, st_dom)
    print(f"  trade-count by bar-dependency:")
    for dep, n in dep_counts.most_common():
        print(f"    {dep:>10}: {n:,} trades")
    print(f"\n  setups → bar dependency (dominant style):")
    for s in sorted(dep_by_setup, key=lambda k: (-by_setup[k].__len__(), k)):
        dep, st = dep_by_setup[s]
        if setup_summaries[s]["status"] == "DEAD":
            continue
        print(f"    {s:>32}  → {dep:>8}  (style: {st or '—'})")

    # ── Section 4 — performance ──────────────────────────────────────────
    hr("Section 4 — Lifetime performance per setup (closed trades, n ≥ %d)" % MIN_N)
    print(f"  {'setup_type':>32}  {'n':>5}  {'win%':>5}  "
          f"{'be%':>5}  {'avg$':>9}  {'avg%':>7}  "
          f"{'hold_s':>7}  {'maeR':>6}  {'mfeR':>6}  {'EV_R':>6}")
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1])):
        closed = [r for r in lst if r.get("status") == "closed"]
        if len(closed) < MIN_N:
            continue
        n = len(closed)
        pnls = [float(r.get("net_pnl") or 0) for r in closed]
        wins = sum(1 for p in pnls if p > 0)
        breakeven = sum(1 for p in pnls if abs(p) < 0.005)
        pcts = [float(r.get("pnl_pct") or 0) for r in closed]
        holds = [float(r.get("hold_seconds") or 0) for r in closed]
        mae = _avg([r.get("mae_r") for r in closed])
        mfe = _avg([r.get("mfe_r") for r in closed])
        avg_p = sum(pnls) / n
        win_rate = wins / n * 100
        # Expectancy (R-multiple): wins×avg_win_R - losses×avg_loss_R
        win_R = _avg([r.get("mfe_r") for r in closed if (r.get("net_pnl") or 0) > 0])
        loss_R = _avg([r.get("mae_r") for r in closed if (r.get("net_pnl") or 0) < 0])
        ev_r = ((wins / n) * (win_R or 0)) - (((n - wins) / n) * abs(loss_R or 0))
        print(f"  {s:>32}  {n:>5}  {win_rate:>4.1f}%  "
              f"{breakeven/n*100:>4.1f}%  ${avg_p:>+8.2f}  "
              f"{_avg(pcts) or 0:>+6.2f}%  "
              f"{_avg(holds) or 0:>7.0f}  "
              f"{mae or 0:>+5.2f}  {mfe or 0:>+5.2f}  {ev_r:>+5.2f}")

    # ── Section 5 — entry-time distribution ──────────────────────────────
    hr("Section 5 — Entry-time distribution per setup (RTH buckets, ET)")
    print(f"  {'setup_type':>32}  {'pre_open':>9}  {'0930_1000':>10}  "
          f"{'1000_1530':>10}  {'1530_1600':>10}  {'post_close':>11}")
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1])):
        if setup_summaries[s]["status"] == "DEAD":
            continue
        c = Counter()
        for r in lst:
            if r["_t_exec"]:
                c[_et_bucket(r["_t_exec"].astimezone(ET))] += 1
        print(f"  {s:>32}  {c.get('pre_open',0):>9}  "
              f"{c.get('0930_1000',0):>10}  "
              f"{c.get('1000_1530',0):>10}  "
              f"{c.get('1530_1600',0):>10}  "
              f"{c.get('post_close',0):>11}")

    # ── Section 6 — quality grade matrix ─────────────────────────────────
    hr("Section 6 — quality_grade × setup_type")
    grades = ("A", "B", "C", "D", "F")
    print(f"  {'setup_type':>32}  " +
          "".join(f"{g:>5}" for g in grades) + "  other")
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1]))[:30]:
        c = Counter()
        for r in lst:
            g = (r.get("quality_grade") or "?").strip().upper()
            c[g if g in grades else "other"] += 1
        cells = "".join(f"{c.get(g, 0):>5}" for g in grades)
        print(f"  {s:>32}  {cells}  {c.get('other', 0):>5}")

    # ── Section 7 — entered_by source ────────────────────────────────────
    hr("Section 7 — entered_by × setup_type (data hygiene)")
    sources = Counter()
    src_by_setup = defaultdict(Counter)
    for r in rows:
        src = r.get("entered_by") or "<none>"
        sources[src] += 1
        src_by_setup[r.get("setup_type") or "<none>"][src] += 1
    print(f"  global entered_by counts:")
    for src, n in sources.most_common():
        print(f"    {src:>20}: {n:,}")
    print(f"\n  per setup (top 20 by volume):")
    top_srcs = [s for s, _ in sources.most_common(6)]
    print(f"  {'setup_type':>32}  " +
          "".join(f"{src[:10]:>11}" for src in top_srcs))
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1]))[:20]:
        c = src_by_setup[s]
        print(f"  {s:>32}  " +
              "".join(f"{c.get(src, 0):>11}" for src in top_srcs))

    # ── Section 8 — EOD exposure ────────────────────────────────────────
    hr("Section 8 — EOD-close vs intraday-close per setup (closed trades)")
    print(f"  {'setup_type':>32}  {'closed':>6}  {'eod_close':>10}  "
          f"{'intra_close':>12}  {'eod%':>6}  {'reasons (top 3)':<30}")
    for s, lst in sorted(by_setup.items(), key=lambda kv: -len(kv[1]))[:25]:
        closed = [r for r in lst if r.get("status") == "closed"]
        if not closed:
            continue
        eod = sum(1 for r in closed
                  if r.get("close_at_eod") is True
                  or "eod" in (r.get("close_reason") or "").lower())
        intra = len(closed) - eod
        reasons = Counter((r.get("close_reason") or "?") for r in closed).most_common(3)
        rstr = ", ".join(f"{r}×{n}" for r, n in reasons)
        print(f"  {s:>32}  {len(closed):>6}  {eod:>10}  {intra:>12}  "
              f"{eod/len(closed)*100:>5.1f}%  {rstr[:45]}")

    # ── Section 9 — dead setups ──────────────────────────────────────────
    hr(f"Section 9 — Dead setups (no fire in last {DEAD_AGE}d but fired in window)")
    dead = [(s, v) for s, v in setup_summaries.items()
            if v["status"] == "DEAD" and v["n"] > 0]
    if not dead:
        print("  (none)")
    for s, v in sorted(dead, key=lambda kv: -kv[1]["n"]):
        print(f"    {s:>32}  n={v['n']:>5}  last_fire="
              f"{v['last'].strftime('%Y-%m-%d') if v['last'] else '—'}  "
              f"age={v['age_days']}d")

    # ── Section 10 — composite health flags ──────────────────────────────
    hr("Section 10 — Composite health flags")
    flags = []
    for s, lst in by_setup.items():
        closed = [r for r in lst if r.get("status") == "closed"]
        if len(closed) >= 20:
            wins = sum(1 for r in closed if (r.get("net_pnl") or 0) > 0)
            if wins == 0:
                flags.append(("ZERO_WINRATE", s,
                              f"n={len(closed)} closed, 0 wins"))
        if s in dep_by_setup:
            dep, st = dep_by_setup[s]
            name = s.lower()
            if dep == "INTRADAY" and any(h in name for h in DAILY_HINTS):
                flags.append(("NAME_VS_STYLE_MISMATCH", s,
                              f"name suggests daily but classified {st}"))
            if dep == "DAILY" and st in ("scalp",):
                flags.append(("STYLE_INCONSISTENT", s,
                              f"daily-named but style={st}"))
    if not flags:
        print("  ✓ no composite flags raised.")
    for tag, s, note in flags:
        print(f"  ⚠️ [{tag}]  {s}  — {note}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
