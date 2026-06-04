#!/usr/bin/env python3
"""
diag_mae_mfe_reconstruct.py  (READ-ONLY)
========================================
Reconstructs MAE / MFE from PRICE BARS for *legitimately bot-entered*
trades, so the analysis is independent of how the trade was actually
exited (bot stop/target, EOD, or a manual IB/UI close during the build-out).

It answers the operator's question — "are our entries, stops, targets, or
time horizons off?" — on TRUSTWORTHY data by simulating the bracket to its
natural conclusion.

For each legit trade it walks the bars from entry and computes TWO views:

  REALIZED window  (entry → actual close):
      what price actually did during the real (often premature) hold.

  MANAGED window   (entry → first of {target hit, stop hit, horizon end}):
      what a PROPERLY-MANAGED bracket would have yielded — removes the
      contamination of manual/EOD/phantom early closes.

  Per trade:  risk = |entry - stop|,  target_R = |target - entry| / risk
              MFE_R / MAE_R (both windows), managed_outcome
              (target / stop / timeout), managed_R, minutes-to-MFE-peak.

Aggregated per (style, setup):  median MFE_R / MAE_R, target_reach,
managed target-hit/stop-hit/timeout %, median managed_R (the TRUE edge if
managed), and a verdict: TARGET_TOO_FAR / STOP_TOO_TIGHT / STOP_TOO_LOOSE /
GIVES_BACK (time decay) / EDGE_OK / EDGE_NEGATIVE.

LEGIT filter: entered_by == 'bot_fired', has entry+stop+target+direction,
and close_reason is not a wrong-direction/flip artifact. Use --since to
restrict to the clean pipeline era.

Imports the live trade_style_classifier, so run from repo root + venv:
    .venv/bin/python backend/scripts/diag_mae_mfe_reconstruct.py --days 90 --since 2026-05-15
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

INTRADAY_STYLES = {"scalp", "intraday"}
# bars to fetch per style for the MANAGED window (bounded)
STYLE_HORIZON_MIN = {"scalp": 90, "intraday": 390}        # same-session
STYLE_HORIZON_DAYS = {"multi_day": 5, "swing": 15, "investment": 60, "position": 120}
FLIP_HINTS = ("wrong_direction", "flip", "flipped")


def _bootstrap_path():
    for cand in (Path.cwd() / "backend", Path.cwd()):
        if (cand / "services" / "trade_style_classifier.py").exists():
            sys.path.insert(0, str(cand)); return
    try:
        here = Path(__file__).resolve().parents[1]
        if (here / "services" / "trade_style_classifier.py").exists():
            sys.path.insert(0, str(here))
    except NameError:
        pass


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("ERROR: MONGO_URL / DB_NAME not set."); sys.exit(1)
    return MongoClient(url, serverSelectionTimeoutMS=5000)[name]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _discover_intraday_barsize(db):
    """Find the finest intraday bar_size + its time field by sampling."""
    sizes = db["ib_historical_data"].distinct("bar_size")
    pref = ["1 min", "1min", "1 minute", "2 mins", "5 mins", "5 min", "5min",
            "15 mins", "15 min", "15min"]
    chosen = next((s for s in pref if s in sizes), None)
    if not chosen:
        chosen = next((s for s in sizes if "min" in str(s).lower()), None)
    if not chosen:
        return None, None
    doc = db["ib_historical_data"].find_one({"bar_size": chosen})
    tfield = next((f for f in ("timestamp", "datetime", "date", "time", "t")
                   if doc and f in doc), None)
    return chosen, tfield


def _fetch_bars(db, symbol, bar_size, tfield, start, end, daily=False):
    """Bars for symbol in absolute-time [start, end].

    The `date` field is an ISO string with INCONSISTENT timezones across
    rows (some `-04:00` ET, some `+00:00` UTC), so a string range query is
    invalid. We bound volume with a tz-agnostic YYYY-MM-DD prefix range,
    then parse each bar to absolute UTC and filter precisely in Python.
    """
    pad_lo = (start.date() - timedelta(days=1)).isoformat()
    pad_hi = (end.date() + timedelta(days=1)).isoformat()
    q = {"symbol": symbol.upper(), "bar_size": bar_size,
         tfield: {"$gte": pad_lo, "$lte": pad_hi + "T99"}}
    cur = db["ib_historical_data"].find(
        q, {"_id": 0, tfield: 1, "high": 1, "low": 1, "close": 1, "open": 1}
    ).sort(tfield, 1)
    # for daily bars, include the entry-day bar (its timestamp is midnight,
    # which is < the intraday entry time) → floor the lower bound to the day.
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) if daily else start
    out = []
    for b in cur:
        bt = _dt(b.get(tfield))
        hi, low = _num(b.get("high")), _num(b.get("low"))
        if bt is not None and hi is not None and low is not None and lo <= bt <= end:
            out.append((bt, hi, low))
    return out


def _walk(bars, entry, stop, target, is_long, entry_ts):
    """Walk bars; return (mfe_r, mae_r, managed_outcome, managed_R, min_to_peak)."""
    risk = abs(entry - stop)
    if risk <= 0 or not bars:
        return None
    best_fav = 0.0      # max favorable price move (signed positive)
    worst_adv = 0.0     # max adverse price move (signed positive)
    peak_ts = entry_ts
    outcome, managed_r = "timeout", None
    for bt, hi, lo in bars:
        fav = (hi - entry) if is_long else (entry - lo)
        adv = (entry - lo) if is_long else (hi - entry)
        if fav > best_fav:
            best_fav, peak_ts = fav, bt
        if adv > worst_adv:
            worst_adv = adv
        # managed bracket: which level hit first within this bar?
        hit_t = (hi >= target) if is_long else (lo <= target)
        hit_s = (lo <= stop) if is_long else (hi >= stop)
        if outcome == "timeout":
            if hit_s and hit_t:
                outcome, managed_r = "stop", -1.0      # ambiguous bar → assume stop (conservative)
                break
            if hit_t:
                outcome, managed_r = "target", abs(target - entry) / risk
                break
            if hit_s:
                outcome, managed_r = "stop", -1.0
                break
    if managed_r is None:  # timeout → mark to last close-ish (use best/worst midpoint = realized at horizon)
        last = bars[-1]
        last_px = last[2] if is_long else last[1]  # approx last price by low/high
        managed_r = ((last[1] + last[2]) / 2 - entry) / risk * (1 if is_long else -1)
    mfe_r = best_fav / risk
    mae_r = -worst_adv / risk
    min_to_peak = max(0.0, (peak_ts - entry_ts).total_seconds() / 60.0)
    return mfe_r, mae_r, outcome, managed_r, min_to_peak


def _verdict(n, min_n, med_mfe, med_mae, tgt_r, tgt_hit, stop_hit, timeout,
             med_managed_r, med_mfe_minus_managed):
    if n < min_n:
        return "❓ INSUFFICIENT_DATA"
    if tgt_r > 0 and med_mfe / tgt_r < 0.5 and tgt_hit < 20:
        return "🔶 TARGET_TOO_FAR"
    if stop_hit > 55 and med_mfe > 1.0:
        return "🔶 STOP_TOO_TIGHT (price often ran favorable after stop)"
    if med_mae < -1.10:
        return "🔶 STOP_TOO_LOOSE/SLIPPED"
    if timeout > 50 and med_mfe_minus_managed > 0.5:
        return "🔶 GIVES_BACK (peaks then fades → trail/cut sooner)"
    if med_managed_r > 0.2:
        return "✅ EDGE_OK"
    return "⚠️ EDGE_NEGATIVE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--since", type=str, default=None, help="clean-era start YYYY-MM-DD")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--max-trades", type=int, default=1500)
    args = ap.parse_args()
    _bootstrap_path(); _load_env()
    try:
        from services.trade_style_classifier import resolve_trade_style
    except Exception as e:
        print(f"ERROR importing trade_style_classifier: {e}"); sys.exit(1)
    db = _db()
    floor = args.since or (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"\n{'#'*104}\n#  MAE/MFE BAR-RECONSTRUCTION (legit bot trades)   since={floor}\n{'#'*104}")

    bar_size, tfield = _discover_intraday_barsize(db)
    print(f"intraday bars: bar_size={bar_size!r} time_field={tfield!r}  | daily bars: 'date'")

    proj = {"_id": 0, "symbol": 1, "setup_type": 1, "setup_variant": 1,
            "trade_style": 1, "timeframe": 1, "direction": 1, "entered_by": 1,
            "entry_price": 1, "fill_price": 1, "stop_price": 1, "stop_loss": 1,
            "target_price": 1, "target_prices": 1, "realized_pnl": 1,
            "risk_amount": 1, "close_reason": 1, "executed_at": 1, "entry_time": 1,
            "closed_at": 1, "exit_time": 1, "learning_only": 1, "entry_context": 1}
    raw = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": floor}}, proj).limit(args.max_trades * 3))

    # legit filter
    legit = []
    skipped = defaultdict(int)
    for t in raw:
        if t.get("learning_only") is True or (t.get("entry_context") or {}).get("learning_only") is True:
            skipped["learning_only"] += 1; continue
        if str(t.get("entered_by") or "").lower() != "bot_fired":
            skipped["not_bot_fired"] += 1; continue
        cr = str(t.get("close_reason") or "").lower()
        if any(h in cr for h in FLIP_HINTS):
            skipped["flip/wrong_dir"] += 1; continue
        entry = _num(t.get("entry_price")) or _num(t.get("fill_price"))
        stop = _num(t.get("stop_price")) or _num(t.get("stop_loss"))
        tps = t.get("target_prices") if isinstance(t.get("target_prices"), list) else None
        tgt = _num(tps[0]) if tps else _num(t.get("target_price"))
        ets = _dt(t.get("executed_at") or t.get("entry_time"))
        cts = _dt(t.get("closed_at") or t.get("exit_time"))
        if not (entry and stop and tgt and ets and cts) or entry <= 0:
            skipped["missing entry/stop/target/ts"] += 1; continue
        t["_e"], t["_s"], t["_t"], t["_ets"], t["_cts"] = entry, stop, tgt, ets, cts
        legit.append(t)
    print(f"\nclosed since {floor}: {len(raw)}   legit bot trades w/ stop+target: {len(legit)}")
    print("  skipped: " + "  ".join(f"{k}={v}" for k, v in sorted(skipped.items(), key=lambda x: -x[1])))
    if not legit:
        print("\nNo legit trades — widen --days or check --since.")
        return

    agg = defaultdict(lambda: defaultdict(list))
    no_bars = 0
    done = 0
    for t in legit[:args.max_trades]:
        style = resolve_trade_style(t)
        is_long = str(getattr(t.get("direction"), "value", t.get("direction")) or "long").lower() != "short"
        entry, stop, tgt, ets, cts = t["_e"], t["_s"], t["_t"], t["_ets"], t["_cts"]
        # managed-window end + bar source by style
        if style in INTRADAY_STYLES or style == "unknown":
            hz_end = min(ets + timedelta(minutes=STYLE_HORIZON_MIN.get(style, 390)),
                         ets.replace(hour=20, minute=0, second=0, microsecond=0))  # RTH close (EDT)
            bs, tf, daily = bar_size, tfield, False
        else:
            hz_end = ets + timedelta(days=STYLE_HORIZON_DAYS.get(style, 15))
            bs, tf, daily = "1 day", "date", True
        win_end = max(cts, hz_end)
        bars = _fetch_bars(db, t["symbol"], bs, tf, ets, win_end, daily=daily)
        if not bars:
            no_bars += 1; continue
        realized_bars = [b for b in bars if b[0] <= cts]
        rz = _walk(realized_bars or bars[:1], entry, stop, tgt, is_long, ets)
        mg = _walk(bars, entry, stop, tgt, is_long, ets)
        if not mg:
            continue
        mfe_r, mae_r, outcome, managed_r, peak_min = mg
        tgt_r = abs(tgt - entry) / abs(entry - stop)
        key = (style, (t.get("setup_type") or "?"))
        a = agg[key]
        a["mfe"].append(mfe_r); a["mae"].append(mae_r); a["tgt_r"].append(tgt_r)
        a["managed_r"].append(managed_r); a["outcome"].append(outcome)
        a["peak_min"].append(peak_min)
        a["rz_mfe"].append(rz[0] if rz else 0.0)
        a["gap"].append(mfe_r - managed_r)
        done += 1
    print(f"reconstructed: {done}   (no bars available: {no_bars})\n")

    # report
    print(f"{'style/setup':<34}{'n':>4}{'medMFE':>7}{'medMAE':>7}{'tgtR':>6}"
          f"{'reach':>6}{'tHit%':>6}{'sHit%':>6}{'TO%':>5}{'mgdR':>6}{'peakM':>6}  verdict")
    print("-" * 128)
    rows = []
    for (style, setup), a in agg.items():
        n = len(a["mfe"])
        med_mfe = statistics.median(a["mfe"]); med_mae = statistics.median(a["mae"])
        tgt_r = statistics.median(a["tgt_r"]); med_mgd = statistics.median(a["managed_r"])
        reach = med_mfe / tgt_r if tgt_r > 0 else 0
        oc = a["outcome"]
        th = 100.0 * oc.count("target") / n; sh = 100.0 * oc.count("stop") / n
        to = 100.0 * oc.count("timeout") / n
        peak = statistics.median(a["peak_min"])
        gap = statistics.median(a["gap"])
        v = _verdict(n, args.min_n, med_mfe, med_mae, tgt_r, th, sh, to, med_mgd, gap)
        rows.append((n, style, setup, med_mfe, med_mae, tgt_r, reach, th, sh, to, med_mgd, peak, v))
    for n, style, setup, mfe, mae, tr, reach, th, sh, to, mgd, peak, v in sorted(rows, key=lambda x: -x[0]):
        if n < 3:
            continue
        print(f"{(style+'/'+setup)[:33]:<34}{n:>4}{mfe:>7.2f}{mae:>7.2f}{tr:>6.2f}"
              f"{reach:>6.2f}{th:>6.0f}{sh:>6.0f}{to:>5.0f}{mgd:>+6.2f}{peak:>6.0f}  {v}")

    print(f"\n{'='*104}\nHOW TO READ\n{'='*104}")
    print("• medMFE/medMAE = median max favorable/adverse excursion in R (bar-reconstructed).")
    print("• tgtR = planned reward in R; reach = medMFE/tgtR. reach<0.5 → TARGET too far for typical move.")
    print("• tHit/sHit/TO% = if managed to conclusion, % hitting target / stop / timing out.")
    print("• mgdR = MEDIAN R if the bracket were managed properly = the setup's TRUE edge (free of")
    print("         your manual/EOD/phantom early closes).")
    print("• peakM = median minutes to MFE peak → informs time-decay / max-hold tuning.")
    print("• GIVES_BACK verdict = price peaks well above where a managed exit lands → trail/cut sooner.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
