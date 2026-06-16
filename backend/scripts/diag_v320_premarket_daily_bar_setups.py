#!/usr/bin/env python3
"""diag_v320_premarket_daily_bar_setups.py  —  READ-ONLY  (2026-06-16)

Scopes the v320 daily-bar premarket gate by ENUMERATING which setup_types
+ trade_styles actually fire before 10:00 AM ET, and proving (or
disproving) that they underperform vs ≥10:00 ET firings.

Output drives the patcher's gate whitelist — we do NOT guess.

Sections:
  1. Population — bot_trades fired in last 30 calendar days, split by ET
     time-of-day. Pre-10am ET vs ≥10am ET counts overall.
  2. Per-`trade_style` breakdown — counts + win-rate + avg net_pnl,
     pre-10am vs ≥10am.
  3. Per-`setup_type` breakdown (top 40 by volume) — same split,
     flagged ⚠️ if pre-10am underperforms ≥10am by ≥10 pp win-rate or
     ≥$5 avg net_pnl (default thresholds; tweak via env knobs).
  4. RECOMMENDED gate list — trade_styles and setup_types where the
     pre-10am-vs-≥10am evidence supports suppression.

Env knobs:
  V320_LOOKBACK_DAYS         (default 30)
  V320_PREMARKET_CUTOFF_ET   (default "10:00")
  V320_FLAG_WINRATE_PP       (default 10  — flag if pre-10am wins/total -
                              ≥10am wins/total falls by ≥ N percentage pts)
  V320_FLAG_AVGPNL_USD       (default 5.0 — flag if pre-10am avg net_pnl
                              is ≥ $N worse than ≥10am)
  V320_MIN_N_PER_BUCKET      (default 5   — skip groups with < N pre-10am
                              firings)

No writes. Run from repo root:
  .venv/bin/python backend/scripts/diag_v320_premarket_daily_bar_setups.py
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
LOOKBACK_DAYS = int(os.environ.get("V320_LOOKBACK_DAYS", "30"))
CUTOFF_ET = os.environ.get("V320_PREMARKET_CUTOFF_ET", "10:00")
FLAG_WR_PP = float(os.environ.get("V320_FLAG_WINRATE_PP", "10"))
FLAG_AVGPNL = float(os.environ.get("V320_FLAG_AVGPNL_USD", "5.0"))
MIN_N = int(os.environ.get("V320_MIN_N_PER_BUCKET", "5"))


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


def _cutoff_minutes():
    h, m = CUTOFF_ET.split(":")
    return int(h) * 60 + int(m)


def _bucket(ts_et):
    mins = ts_et.hour * 60 + ts_et.minute
    if mins < _cutoff_minutes():
        return "pre"
    return "post"


def _stats(rows):
    """Returns (n, wins, win_rate_pct, avg_pnl)."""
    n = len(rows)
    if n == 0:
        return 0, 0, None, None
    wins = sum(1 for r in rows if (r.get("net_pnl") or 0) > 0)
    pnls = [float(r.get("net_pnl") or 0) for r in rows]
    return n, wins, wins / n * 100, sum(pnls) / n


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    print(f"diag_v320_premarket_daily_bar_setups  "
          f"({datetime.now(ET):%Y-%m-%d %H:%M ET}, read-only)")
    print(f"  lookback={LOOKBACK_DAYS}d  cutoff_et={CUTOFF_ET}  "
          f"flag_wr_pp={FLAG_WR_PP}  flag_avgpnl=${FLAG_AVGPNL}  "
          f"min_n_per_bucket={MIN_N}")

    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    proj = {"_id": 0, "id": 1, "symbol": 1, "created_at": 1, "executed_at": 1,
            "trade_style": 1, "setup_type": 1, "setup_variant": 1,
            "direction": 1, "status": 1, "net_pnl": 1, "realized_pnl": 1,
            "close_reason": 1, "entered_by": 1}
    rows = []
    for d in db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": since}},
                 {"executed_at": {"$gte": since}}]},
        proj,
    ):
        ts = _parse(d.get("executed_at") or d.get("created_at"))
        if not ts:
            continue
        ts_et = ts.astimezone(ET)
        if ts_et.weekday() >= 5:
            continue   # skip weekends
        # RTH bucket only — pre-9:30 ET (extended hours) and post-16:00
        # ET are out of scope for this gate.
        mins = ts_et.hour * 60 + ts_et.minute
        if mins < 9 * 60 + 30 or mins > 16 * 60:
            continue
        d["_ts_et"] = ts_et
        d["_bucket"] = _bucket(ts_et)
        rows.append(d)

    # ── Section 1 ────────────────────────────────────────────────────────
    hr("Section 1 — Population (RTH only, last %dd, weekdays)" % LOOKBACK_DAYS)
    n_total = len(rows)
    n_pre = sum(1 for r in rows if r["_bucket"] == "pre")
    n_post = n_total - n_pre
    print(f"  total RTH bot_trades:    {n_total:,}")
    print(f"  pre-{CUTOFF_ET} ET:       {n_pre:,}  ({n_pre/n_total*100 if n_total else 0:.1f}%)")
    print(f"  ≥{CUTOFF_ET} ET:         {n_post:,}  ({n_post/n_total*100 if n_total else 0:.1f}%)")
    if n_pre == 0:
        print("  ⚠️  no pre-cutoff entries found — gate is moot. Verify "
              "bot_trades have populated created_at/executed_at fields.")
        return
    if n_post == 0:
        print("  ⚠️  no post-cutoff entries — population data may be skewed.")

    # ── Section 2 — per trade_style ────────────────────────────────────────
    hr("Section 2 — Per trade_style (pre vs ≥cutoff)")
    by_style = defaultdict(lambda: {"pre": [], "post": []})
    for r in rows:
        s = (r.get("trade_style") or "<none>").lower()
        by_style[s][r["_bucket"]].append(r)
    print(f"  {'trade_style':>14}  {'n_pre':>6} {'wr_pre':>7} "
          f"{'$avg_pre':>9}  | {'n_post':>6} {'wr_post':>7} {'$avg_post':>10}  flag")
    flagged_styles = []
    for s, b in sorted(by_style.items(), key=lambda x: -len(x[1]["pre"])):
        n_p, w_p, wr_p, avg_p = _stats(b["pre"])
        n_q, w_q, wr_q, avg_q = _stats(b["post"])
        if n_p < MIN_N:
            continue
        flag = ""
        if (wr_p is not None and wr_q is not None
                and (wr_q - wr_p) >= FLAG_WR_PP):
            flag = "⚠️"
        if (avg_p is not None and avg_q is not None
                and (avg_q - avg_p) >= FLAG_AVGPNL):
            flag = "⚠️"
        print(f"  {s:>14}  {n_p:>6} {wr_p or 0:>6.1f}% "
              f"${avg_p or 0:>+8.2f}  | "
              f"{n_q:>6} {wr_q or 0:>6.1f}% ${avg_q or 0:>+9.2f}  {flag}")
        if flag:
            flagged_styles.append((s, n_p, wr_p, avg_p, n_q, wr_q, avg_q))

    # ── Section 3 — per setup_type ─────────────────────────────────────────
    hr("Section 3 — Per setup_type (top 40 by pre-cutoff volume)")
    by_setup = defaultdict(lambda: {"pre": [], "post": []})
    for r in rows:
        s = (r.get("setup_type") or "<none>")
        by_setup[s][r["_bucket"]].append(r)
    print(f"  {'setup_type':>28}  {'n_pre':>6} {'wr_pre':>7} "
          f"{'$avg_pre':>9}  | {'n_post':>6} {'wr_post':>7} {'$avg_post':>10}  flag")
    flagged_setups = []
    ordered = sorted(by_setup.items(), key=lambda x: -len(x[1]["pre"]))[:40]
    for s, b in ordered:
        n_p, w_p, wr_p, avg_p = _stats(b["pre"])
        n_q, w_q, wr_q, avg_q = _stats(b["post"])
        if n_p < MIN_N:
            continue
        flag = ""
        if (wr_p is not None and wr_q is not None
                and (wr_q - wr_p) >= FLAG_WR_PP):
            flag = "⚠️"
        if (avg_p is not None and avg_q is not None
                and (avg_q - avg_p) >= FLAG_AVGPNL):
            flag = "⚠️"
        print(f"  {s:>28}  {n_p:>6} {wr_p or 0:>6.1f}% "
              f"${avg_p or 0:>+8.2f}  | "
              f"{n_q:>6} {wr_q or 0:>6.1f}% ${avg_q or 0:>+9.2f}  {flag}")
        if flag:
            flagged_setups.append((s, n_p, wr_p, avg_p, n_q, wr_q, avg_q))

    # ── Section 4 — recommended gate list ──────────────────────────────────
    hr("Section 4 — RECOMMENDED v320 gate list")
    print("  Statistically-justified gate candidates (pre-cutoff "
          "underperforms ≥cutoff by either win-rate margin or avg net_pnl):")
    if flagged_styles:
        print(f"\n  trade_styles to gate ({len(flagged_styles)}):")
        for (s, n_p, wr_p, avg_p, n_q, wr_q, avg_q) in flagged_styles:
            print(f"    • {s:<14}  n_pre={n_p:>4}  "
                  f"wr_pre={wr_p:.1f}% vs wr_post={wr_q:.1f}%  "
                  f"$avg_pre=${avg_p:+.2f} vs $avg_post=${avg_q:+.2f}")
    else:
        print("\n  trade_styles: none meet the flag thresholds.")
    if flagged_setups:
        print(f"\n  setup_types to gate ({len(flagged_setups)}):")
        for (s, n_p, wr_p, avg_p, n_q, wr_q, avg_q) in flagged_setups:
            print(f"    • {s:<28}  n_pre={n_p:>4}  "
                  f"wr_pre={wr_p:.1f}% vs wr_post={wr_q:.1f}%  "
                  f"$avg_pre=${avg_p:+.2f} vs $avg_post=${avg_q:+.2f}")
    else:
        print("\n  setup_types: none meet the flag thresholds.")

    print("\n  Hard-include (operator-asserted daily-bar styles, regardless of flag):")
    print("    • multi_day, swing, position, investment")
    print("\n  Next step: confirm this list, then ship the patcher to gate")
    print("  these styles/setups inside opportunity_evaluator.evaluate_opportunity")
    print(f"  when local ET time < {CUTOFF_ET}.")
    print("\nDONE.")


if __name__ == "__main__":
    main()
