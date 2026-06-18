#!/usr/bin/env python3
"""
v379 — smart_filter INPUT PROBE (READ-ONLY).

QUESTION THIS ANSWERS
---------------------
When the live bot blocks a borderline setup with
  "... TQS (X) doesn't meet threshold (75)"
is the number X actually the 5-pillar TQS, or is it the alert's
trigger_probability x 100?

WHY IT MATTERS
--------------
smart_filter.evaluate() is called as:
    quality_score = alert.get('score', 70)         # opportunity_evaluator.py:648
and the MAIN bot loop builds that dict as:
    'score': int((alert.trigger_probability or 0.5) * 100)   # trading_bot_service.py:4779
    'tqs_score': alert.tqs_score                              # SEPARATE key
while the AUTO-EXECUTE path builds it as:
    'score': int(tqs_score) or 80                            # scanner_integration.py:68
So depending on the entry path, smart_filter's "quality_score" is EITHER
trigger_probability x100 (main loop) OR the real TQS (auto-execute). The reject
string hard-codes the word "TQS" regardless (smart_filter.py:152), so the label
can lie. This probe reads the LIVE data and tells us which value was really
compared.

DISPOSITIVE TEST
----------------
The composite TQS is a weighted AVERAGE of 5 pillars and (per
grade_calibration.py) maxes at ~68 live. trigger_probability is clamped to
[0.15, 0.90] => trigger_probability x100 in [15, 90]. Therefore:
  * any compared value X in (68, 90]  => CANNOT be TQS => it's trigger_prob x100.
  * X <= 68                            => ambiguous; resolved by joining the
                                          drop to its live_alerts row and
                                          checking which field equals X.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v379_smartfilter_input_probe.py --days 7
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v379_smartfilter_input_probe.py --days 7 --symbol SNDK
"""
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

DROP_COLLECTION = "trade_drops"
ALERT_COLLECTIONS = ["live_alerts", "live_scanner_alerts", "alerts"]
# parse "TQS (60) ... threshold (75)" — tolerant of ints/floats and wording.
_TQS_RE = re.compile(r"TQS\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*\).*?threshold\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*\)",
                     re.IGNORECASE | re.DOTALL)
# join window: a live_alerts row counts as "the alert behind this drop" if its
# timestamp is within this many seconds of the drop.
JOIN_WINDOW_S = 1800.0


def _arg(flag, default, cast=str):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _epoch(d):
    """Best-effort epoch seconds from a doc's timestamp-ish fields."""
    for k in ("ts_epoch_ms", "ts", "created_at", "timestamp", "dropped_at",
              "fired_at", "detected_at", "at"):
        v = d.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            return float(v) / 1000.0 if v > 1e12 else float(v)
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            # date-only "YYYY-MM-DD"
            try:
                return datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
    return None


def _base(st):
    return str(st or "").split("_long")[0].split("_short")[0].split("_confirmed")[0]


def _drop_text(d):
    ctx = d.get("context") or {}
    if isinstance(ctx, dict):
        for k in ("why", "narrative"):
            v = ctx.get(k)
            if isinstance(v, str) and v:
                m = _TQS_RE.search(v)
                if m:
                    return v, m
    r = d.get("reason")
    if isinstance(r, str) and r:
        return r, _TQS_RE.search(r)
    return "", None


def _fmt(x):
    return "n/a" if x is None else f"{x:.0f}"


def main():
    days = _arg("--days", 7, float)
    only_symbol = _arg("--symbol", None)
    if only_symbol:
        only_symbol = only_symbol.upper()
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    db = _load_db()

    # 1) pull smart_filter_skip drops in window
    q = {"gate": "smart_filter_skip"}
    if only_symbol:
        q["symbol"] = only_symbol
    drops = []
    for d in db[DROP_COLLECTION].find(q, {"_id": 0}):
        ep = _epoch(d)
        if ep is None or ep >= since:
            drops.append((ep, d))
    drops.sort(key=lambda t: (t[0] or 0), reverse=True)
    print("=" * 80)
    print(f"smart_filter_skip drops (last {days}d"
          + (f", symbol={only_symbol}" if only_symbol else "") + f"): {len(drops)}")
    print("=" * 80)

    # 2) choose alert collection
    alert_col = None
    for c in ALERT_COLLECTIONS:
        try:
            if db[c].estimated_document_count() > 0:
                alert_col = c
                break
        except Exception:
            continue
    print(f"alert collection for join: {alert_col}\n")

    # split into the two SKIP branches: borderline-TQS (parseable) vs low-win-rate
    borderline = [(ep, d, m) for (ep, d) in drops for (_, m) in [_drop_text(d)] if m]
    other = [(ep, d) for (ep, d) in drops if not _drop_text(d)[1]]

    # ── Section A — DISPOSITIVE: distribution of the compared value ──────────
    print("-" * 80)
    print("A. COMPARED-VALUE DISTRIBUTION  (the 'X' in 'TQS (X) ... threshold (Y)')")
    print("-" * 80)
    comp_vals = [float(m.group(1)) for (_, _, m) in borderline]
    thresholds = sorted({float(m.group(2)) for (_, _, m) in borderline})
    if comp_vals:
        cv = sorted(comp_vals)
        gt68 = sum(1 for x in cv if x > 68)
        ge75 = sum(1 for x in cv if x >= 75)
        print(f"  borderline-band skips parsed: {len(cv)}   thresholds seen: {thresholds}")
        print(f"  compared X:  min={min(cv):.0f}  med={cv[len(cv)//2]:.0f}  max={max(cv):.0f}")
        print(f"  X > 68 (IMPOSSIBLE for TQS -> must be trigger_prob x100): {gt68} "
              f"({gt68/len(cv)*100:.1f}%)")
        print(f"  X >= 75 (would PASS the borderline gate):                {ge75} "
              f"({ge75/len(cv)*100:.1f}%)")
        if gt68 > 0:
            print("  >>> DISPOSITIVE: at least one compared value exceeds the TQS ceiling (68).")
            print("  >>> smart_filter is being fed trigger_probability x100, NOT the TQS.")
    else:
        print("  (no borderline-band 'TQS (X)...threshold' skips in window — all")
        print("   smart_filter_skip rows were the low-win-rate SKIP branch.)")
    print(f"\n  low-win-rate (non-borderline) smart_filter_skip rows: {len(other)}")

    # ── Section B — per-drop JOIN to the live alert ──────────────────────────
    print("\n" + "-" * 80)
    print("B. PER-DROP JOIN  — compared X vs the alert's trigger_prob x100 vs tqs_score")
    print("-" * 80)
    print(f"  {'symbol':<8} {'setup':<22} {'X':>4} {'trig*100':>8} {'tqs':>5} "
          f"{'win%':>5}  verdict")
    verdicts = defaultdict(int)

    # preload candidate alerts per symbol to limit queries
    syms = sorted({(d.get('symbol') or '').upper() for (_, d, _) in borderline if d.get('symbol')})
    alerts_by_sym = defaultdict(list)
    if alert_col and syms:
        for a in db[alert_col].find({"symbol": {"$in": syms}}, {"_id": 0}):
            alerts_by_sym[(a.get("symbol") or "").upper()].append(a)

    for ep, d, m in borderline[:60]:
        sym = (d.get("symbol") or "").upper()
        setup = d.get("setup_type") or "?"
        X = float(m.group(1))
        win = None
        ctx = d.get("context") or {}
        if isinstance(ctx, dict) and isinstance(ctx.get("win_rate"), (int, float)):
            win = float(ctx["win_rate"]) * (100 if ctx["win_rate"] <= 1.0 else 1)

        # find nearest-in-time alert for this symbol, prefer same setup/base
        best = None
        best_dt = None
        for a in alerts_by_sym.get(sym, []):
            a_ep = _epoch(a)
            if a_ep is None or ep is None:
                continue
            dt = abs(a_ep - ep)
            if dt > JOIN_WINDOW_S:
                continue
            same = (a.get("setup_type") == setup) or (_base(a.get("setup_type")) == _base(setup))
            # prefer same-setup; among those, the closest in time
            score = (0 if same else 1, dt)
            if best is None or score < best_dt:
                best, best_dt = a, score

        trig = tqs = None
        if best is not None:
            tp = best.get("trigger_probability")
            if isinstance(tp, (int, float)):
                trig = round(float(tp) * 100)
            ts = best.get("tqs_score")
            if isinstance(ts, (int, float)) and ts > 0:
                tqs = round(float(ts))

        # verdict
        if trig is None and tqs is None:
            v = "NO_ALERT_MATCH"
        else:
            match_trig = (trig is not None and abs(X - trig) <= 1)
            match_tqs = (tqs is not None and abs(X - tqs) <= 1)
            if match_trig and not match_tqs:
                v = "TRIGGER_PROB"
            elif match_tqs and not match_trig:
                v = "TQS"
            elif match_trig and match_tqs:
                v = "BOTH_MATCH"
            elif X > 68:
                v = "TRIGGER_PROB(X>68)"
            else:
                v = "NEITHER_MATCH"
        verdicts[v] += 1
        print(f"  {sym:<8} {setup[:22]:<22} {X:>4.0f} {_fmt(trig):>8} {_fmt(tqs):>5} "
              f"{_fmt(win):>5}  {v}")

    if len(borderline) > 60:
        print(f"  ... ({len(borderline) - 60} more borderline rows not shown)")

    # ── VERDICT ───────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    for k, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<22} {n}")
    trig_total = verdicts.get("TRIGGER_PROB", 0) + verdicts.get("TRIGGER_PROB(X>68)", 0)
    tqs_total = verdicts.get("TQS", 0)
    print("")
    if trig_total and trig_total >= tqs_total:
        print("  ==> smart_filter is gating on TRIGGER_PROBABILITY x100 (the main-loop")
        print("      wiring at trading_bot_service.py:4779). The reject string's 'TQS'")
        print("      label is a MISNOMER. Fix = feed the real tqs_score into smart_filter")
        print("      (mirror the confidence-gate GAP-1 fix) AND grade-calibrate the gate.")
    elif tqs_total and not trig_total:
        print("  ==> smart_filter is gating on the REAL TQS (auto-execute wiring). The")
        print("      original 'TQS 75 is unreachable' diagnosis holds for this path.")
        print("      Fix = grade-calibrate the borderline gate (>= B).")
    else:
        print("  ==> Inconclusive from joins (stale/missing alert rows). Lean on Section A:")
        print("      if any compared X > 68 it is necessarily trigger_probability x100.")


if __name__ == "__main__":
    main()
