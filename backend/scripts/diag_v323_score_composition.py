#!/usr/bin/env python3
"""
v323 — CONFIDENCE SCORE COMPOSITION (READ-ONLY)

After v322 dropped the meta wall, v322b showed admitted setups still die because
their confidence_score is low (median ~22 vs GO=38). This diag answers WHY: it
attributes the additive scoring points to each LAYER (from the reasoning log),
so we see which layers add points, which drag, and what GO decisions have that
SKIP/REDUCE decisions lack. That tells us whether GO=38 is miscalibrated or
setups genuinely lack confirmation.

Parses signed point deltas in the reasoning (e.g. "(+15)", "(-25)", "+5 pts")
and buckets them by layer keyword. Also cross-tabs score by decision.

Usage:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v323_score_composition.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v323_score_composition.py --hours 8
"""
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

# layer keyword → label (first match wins, order matters)
LAYERS = [
    ("meta-labeler", "meta_labeler"), ("ensemble meta", "meta_labeler"),
    ("regime", "regime"),
    ("in-play", "quality_inplay"), ("tqs", "quality_inplay"), ("quality", "quality_inplay"),
    ("mtf", "mtf"), ("multi-timeframe", "mtf"), ("timeframe", "mtf"),
    ("sector", "sector"),
    ("rs rating", "rs"), ("relative strength", "rs"), ("rs ", "rs"),
    ("edge decay", "learning"), ("learning", "learning"),
    ("cross-model", "cross_model"), ("agreement", "cross_model"),
    ("cnn-lstm", "cnn_lstm"), ("cnn", "cnn"), ("tft", "tft"), ("vae", "vae"),
    ("tape", "tape"), ("catalyst", "catalyst"), ("news", "catalyst"),
    ("pattern", "pattern"), ("volume", "volume"),
]
PT_PAREN = re.compile(r"\(([+-]\d+)\)")
PT_PTS = re.compile(r"([+-]\d+)\s*pts?\b", re.I)

GO_THRESH = {"normal": 38, "cautious": 50, "defensive": 60, "aggressive": 28}


def _layer_of(line):
    low = line.lower()
    for kw, lab in LAYERS:
        if kw in low:
            return lab
    return "other"


def _points(line):
    pts = [int(m) for m in PT_PAREN.findall(line)]
    pts += [int(m) for m in PT_PTS.findall(line)]
    return sum(pts) if pts else None


def main():
    hours = 8
    if "--hours" in sys.argv:
        try:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        except Exception:
            hours = 8
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = list(db.confidence_gate_log.find(
        {"timestamp": {"$gte": iso}},
        {"_id": 0, "decision": 1, "reasoning": 1, "confidence_score": 1,
         "trading_mode": 1, "quality_score": 1}))

    print(f"\n=== v323 SCORE COMPOSITION — last {hours}h ===\n")
    if not rows:
        print("  No decisions in window. Re-run during/after RTH.\n")
        return
    print(f"  decisions: {len(rows)}")
    dec = Counter(r.get("decision", "?") for r in rows)
    print(f"  GO/REDUCE/SKIP: {dec.get('GO',0)}/{dec.get('REDUCE',0)}/{dec.get('SKIP',0)}\n")

    # ---- score distribution by decision ----
    print("=" * 72)
    print("SCORE distribution by decision")
    print("=" * 72)
    by_dec = defaultdict(list)
    for r in rows:
        cs = r.get("confidence_score")
        if cs is not None:
            by_dec[r.get("decision", "?")].append(float(cs))
    for d in ("GO", "REDUCE", "SKIP"):
        xs = by_dec.get(d, [])
        if xs:
            xs.sort()
            print(f"  {d:<7} n={len(xs):<5} min={xs[0]:.0f} median={median(xs):.0f} "
                  f"mean={mean(xs):.0f} max={xs[-1]:.0f}")

    # ---- per-layer point attribution (all decisions) ----
    print("\n" + "=" * 72)
    print("LAYER point attribution (across all decisions)")
    print("=" * 72)
    layer_pts = defaultdict(list)      # label -> [points when present]
    layer_pos = Counter(); layer_neg = Counter()
    for r in rows:
        seen = set()
        for line in (r.get("reasoning") or []):
            p = _points(str(line))
            if p is None:
                continue
            lab = _layer_of(str(line))
            layer_pts[lab].append(p)
            if p > 0:
                layer_pos[lab] += 1
            elif p < 0:
                layer_neg[lab] += 1
    print(f"  {'layer':<16} {'fires':>6} {'+cnt':>5} {'-cnt':>5} {'sum':>7} {'mean':>6}")
    for lab in sorted(layer_pts, key=lambda x: -sum(layer_pts[x])):
        ps = layer_pts[lab]
        print(f"  {lab:<16} {len(ps):>6} {layer_pos[lab]:>5} {layer_neg[lab]:>5} "
              f"{sum(ps):>7} {mean(ps):>6.1f}")

    # ---- GO vs SKIP layer contribution gap ----
    print("\n" + "=" * 72)
    print("WHAT GO HAS THAT SKIP LACKS (mean points/decision by layer)")
    print("=" * 72)
    def per_dec_layer(decision):
        agg = defaultdict(float); cnt = 0
        for r in rows:
            if r.get("decision") != decision:
                continue
            cnt += 1
            for line in (r.get("reasoning") or []):
                p = _points(str(line))
                if p is not None:
                    agg[_layer_of(str(line))] += p
        return ({k: v / cnt for k, v in agg.items()} if cnt else {}), cnt
    go_avg, n_go = per_dec_layer("GO")
    sk_avg, n_sk = per_dec_layer("SKIP")
    labs = sorted(set(go_avg) | set(sk_avg), key=lambda x: -(go_avg.get(x, 0) - sk_avg.get(x, 0)))
    print(f"  (GO n={n_go}, SKIP n={n_sk})")
    print(f"  {'layer':<16} {'GO avg':>8} {'SKIP avg':>9} {'GO-SKIP':>8}")
    for lab in labs:
        g = go_avg.get(lab, 0.0); s = sk_avg.get(lab, 0.0)
        print(f"  {lab:<16} {g:>8.1f} {s:>9.1f} {g - s:>8.1f}")

    # ---- sample reasoning (so operator can sanity-check parsing) ----
    print("\n" + "=" * 72)
    print("SAMPLE reasoning lines (parse sanity-check)")
    print("=" * 72)
    shown = 0
    for r in rows:
        for line in (r.get("reasoning") or []):
            if _points(str(line)) is not None:
                print(f"  [{_layer_of(str(line))}|{_points(str(line)):+d}] {str(line)[:90]}")
                shown += 1
                break
        if shown >= 8:
            break

    print("\n=== READING THE RESULT ===")
    print("• 'GO-SKIP' column = the layers that separate winners from skips. Big positive")
    print("    gaps are the layers that actually earn GO; layers near 0 don't discriminate.")
    print("• If most setups score ~22 and no single layer reliably adds enough to reach 38,")
    print("    the scoring is STARVED (few layers fire) — options: lower GO_threshold, or")
    print("    add/boost a discriminating layer. If a layer DRAGS (large -sum) broadly, it")
    print("    may be miscalibrated.")
    print("• Verify the SAMPLE lines parsed to the right layer/points before trusting sums.\n")


if __name__ == "__main__":
    main()
