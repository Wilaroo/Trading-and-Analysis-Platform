#!/usr/bin/env python3
"""
diag_v320b_classify.py — READ-ONLY classifier for the v320b candidates
=======================================================================
v320b's --check flagged 88 symbols / 58,759 rows but mixed two patterns:
  (1) GENUINE recycles like SPCX (small residue, big price jump)
  (2) Systemic INGESTION GAPS that look identical to the volume-only
      filter (e.g. dozens of unrelated tickers all showing
      window_start=2026-06-01 → likely the daily-bar ingest stalled)

This probe re-runs the v320a filter on every candidate AND computes:
  - price discontinuity     : max(new_med_close, old_med_close)
                              / min(new_med_close, old_med_close)
  - remove ratio            : removed / total
  - clustering by window_start (detects ingest gaps when many
    unrelated symbols share a date)

Then classifies each symbol:
  TRUE_RECYCLE     : price_ratio >= 3.0  AND  remove_ratio <= 0.30
                     AND window_start NOT shared by >=5 other symbols
  LIKELY_INGEST    : window_start shared by >=5 other symbols
  AMBIGUOUS        : anything else (manual review)

USAGE:
  .venv/bin/python /tmp/diag_v320b_classify.py
  .venv/bin/python /tmp/diag_v320b_classify.py --price-ratio 5
NO WRITES.
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import median as _median


def _load_env(repo: Path):
    for cand in (repo / "backend" / ".env",):
        if cand.is_file():
            for ln in cand.read_text().splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(),
                                          v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path.home() / "Trading-and-Analysis-Platform"))
    ap.add_argument("--gap-days", type=int, default=30)
    ap.add_argument("--vol-ratio", type=float, default=50.0)
    ap.add_argument("--price-ratio", type=float, default=3.0,
                    help="min price discontinuity for TRUE_RECYCLE")
    ap.add_argument("--remove-ratio", type=float, default=0.30,
                    help="max removed/total for TRUE_RECYCLE")
    ap.add_argument("--cluster-threshold", type=int, default=5,
                    help="window_start shared by N+ symbols → LIKELY_INGEST")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    _load_env(repo)
    sys.path.insert(0, str(repo / "backend"))

    from pymongo import MongoClient
    from services.ib_historical_collector import IBHistoricalCollector as IBC

    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    db = client[os.environ.get("DB_NAME") or "tradecommand"]
    src = db["ib_historical_data"]

    print("═" * 72)
    print(" diag_v320b_classify  —  READ-ONLY")
    print("═" * 72)
    print(f"  thresholds        : gap > {args.gap_days}d, vol_ratio ≥ {args.vol_ratio}×")
    print(f"  TRUE_RECYCLE      : price_ratio ≥ {args.price_ratio}× AND remove ≤ {args.remove_ratio*100:.0f}%")
    print(f"  LIKELY_INGEST     : window_start shared by ≥{args.cluster_threshold} symbols")
    print()

    syms = sorted(src.distinct("symbol", {"bar_size": "1 day"}))
    print(f"  scanning {len(syms):,} symbols …")

    rows = []
    for sym in syms:
        bars = list(src.find(
            {"symbol": sym, "bar_size": "1 day"},
            {"_id": 0, "date": 1, "volume": 1, "high": 1, "low": 1, "close": 1},
        ).sort("date", -1))
        if len(bars) < 3:
            continue
        dates  = [b.get("date")   for b in bars]
        vols   = [b.get("volume") for b in bars]
        highs  = [b.get("high")   for b in bars]
        lows   = [b.get("low")    for b in bars]
        closes = [b.get("close")  for b in bars]

        fd, fv, fh, fl, fc, meta = IBC._filter_pre_listing_pollution(
            dates, vols, highs, lows, closes,
            gap_threshold_days=args.gap_days,
            vol_ratio_threshold=args.vol_ratio,
        )
        if not meta["filter_applied"]:
            continue

        kept    = len(fd)
        removed = len(bars) - kept
        total   = len(bars)

        # Price discontinuity (median close newer cohort vs older cohort)
        newer_closes = [c for c in closes[:kept]      if c]
        older_closes = [c for c in closes[kept:total] if c]
        newer_vols   = [v for v in vols[:kept]        if v]
        older_vols   = [v for v in vols[kept:total]   if v]
        if not newer_closes or not older_closes:
            continue
        nm_c = _median(newer_closes)
        om_c = _median(older_closes)
        nm_v = _median(newer_vols) if newer_vols else 0
        om_v = _median(older_vols) if older_vols else 0
        price_ratio = max(nm_c, om_c) / min(nm_c, om_c) if min(nm_c, om_c) > 0 else float("inf")
        vol_ratio   = (nm_v / om_v) if om_v > 0 else float("inf")
        remove_pct  = removed / total

        rows.append({
            "sym": sym, "total": total, "kept": kept, "removed": removed,
            "remove_pct": remove_pct,
            "window_start": (meta["window_start_iso"] or "")[:10],
            "newer_close_med": nm_c, "older_close_med": om_c,
            "price_ratio": price_ratio,
            "newer_vol_med": nm_v, "older_vol_med": om_v,
            "vol_ratio": vol_ratio,
        })

    if not rows:
        print("  (no pollution candidates — nothing to classify)")
        return 0

    # ── Cluster by window_start to detect ingest gaps ──
    ws_counts = Counter(r["window_start"] for r in rows)
    ingest_dates = {d for d, n in ws_counts.items() if n >= args.cluster_threshold}

    def classify(r):
        if r["window_start"] in ingest_dates:
            return "LIKELY_INGEST"
        if (r["price_ratio"] >= args.price_ratio and
                r["remove_pct"] <= args.remove_ratio):
            return "TRUE_RECYCLE"
        return "AMBIGUOUS"

    for r in rows:
        r["class"] = classify(r)

    # ── Output groups ──
    def _show(group, label):
        sub = [r for r in rows if r["class"] == group]
        sub.sort(key=lambda r: -r["price_ratio"])
        print(f"\n─── {label} ({len(sub)} symbols) ─────────────")
        if not sub:
            print("   (none)")
            return
        print(f"   {'sym':<7} {'total':>6} {'rm':>5} {'rm%':>5}  "
              f"{'px_ratio':>8} {'vol_ratio':>10}  {'win_start':<11}  "
              f"{'old$':>7} → {'new$':>7}")
        print(f"   {'-' * 88}")
        for r in sub[:50]:
            pr = "inf" if r["price_ratio"] == float("inf") else f"{r['price_ratio']:.2f}"
            vr = "inf" if r["vol_ratio"]   == float("inf") else f"{r['vol_ratio']:.1f}"
            print(f"   {r['sym']:<7} {r['total']:>6} {r['removed']:>5} "
                  f"{r['remove_pct']*100:>4.1f}%  "
                  f"{pr:>8} {vr:>10}  {r['window_start']:<11}  "
                  f"{r['older_close_med']:>7.2f} → {r['newer_close_med']:>7.2f}")
        if len(sub) > 50:
            print(f"   ... ({len(sub) - 50} more)")

    _show("TRUE_RECYCLE",  "TRUE_RECYCLE — safe to quarantine")
    _show("LIKELY_INGEST", "LIKELY_INGEST_GAP — DO NOT quarantine (systemic issue)")
    _show("AMBIGUOUS",     "AMBIGUOUS — manual review")

    # ── Ingest-gap clustering view ──
    print()
    print("─── window_start clustering (top dates) ────────────────────────────")
    print(f"   {'date':<12} {'symbols':>8}")
    for d, n in ws_counts.most_common(15):
        flag = "  ← INGEST CLUSTER" if d in ingest_dates else ""
        print(f"   {d:<12} {n:>8}{flag}")

    # ── Summary ──
    cls_counts = Counter(r["class"] for r in rows)
    total_rm = {cls: sum(r["removed"] for r in rows if r["class"] == cls)
                for cls in cls_counts}
    print()
    print("─── summary ─────────────────────────────────────────────────────────")
    print(f"   {'class':<18} {'symbols':>8} {'rows_to_remove':>16}")
    for cls in ("TRUE_RECYCLE", "LIKELY_INGEST", "AMBIGUOUS"):
        print(f"   {cls:<18} {cls_counts.get(cls, 0):>8} "
              f"{total_rm.get(cls, 0):>16,}")
    print()
    print("Recommended next step: refine v320b to require price_ratio ≥ "
          f"{args.price_ratio:g}× AND remove_ratio ≤ {args.remove_ratio*100:.0f}%")
    print("Then quarantine only TRUE_RECYCLE symbols.")
    print()
    print("The LIKELY_INGEST cluster is a separate bug (May→June 2026 daily")
    print("backfill gap) — track as a follow-up `diag_ingest_continuity.py`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
