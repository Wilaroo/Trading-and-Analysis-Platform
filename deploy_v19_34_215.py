#!/usr/bin/env python3
"""
deploy_v19_34_215.py — ma_stack from snapshot.trend. Builds on v213/v214.

Idempotent, anchor-based, abort-safe. 1 edit:

  E1. tqs/technical_quality.py — replace the broken mixed-timeframe
      `ema_20 > ema_50 > sma_200` ma_stack derivation (pinned to "neutral"
      100% of the time) with the snapshot's already-computed, v166-tolerant
      `trend` field (uptrend->bullish, downtrend->bearish, sideways->neutral).
      The pillar's trend sub-score is already direction-aware, so this lifts it
      correctly for both longs and shorts.

Run from repo root. Commits + pushes on success.
"""
import os
import sys

REPO = os.getcwd()

EDITS = [
    ("backend/services/tqs/technical_quality.py", "E1-ma-stack-trend",
     """                    # MA stack from moving averages
                    ema20 = getattr(snapshot, "ema_20", 0)
                    ema50 = getattr(snapshot, "ema_50", 0)
                    sma200 = getattr(snapshot, "sma_200", 0)
                    if ema20 > ema50 > sma200:
                        ma_stack = "bullish"
                    elif ema20 < ema50 < sma200:
                        ma_stack = "bearish"
                    else:
                        ma_stack = "neutral\"""",
     """                    # MA stack from the snapshot's already-computed trend.
                    # v19.34.215 — pre-fix this re-derived a broken
                    # `ema_20 > ema_50 > sma_200` stack that MIXED timeframes
                    # (intraday ema_20 vs daily ema_50/sma_200) and fell back to
                    # current_price when daily bars were missing — pinning
                    # ma_stack to "neutral" for 100% of alerts. The snapshot
                    # already classifies trend with intraday EMA9/EMA20 + a 0.25%
                    # tolerance and the v166 macro-veto; reuse it directly so the
                    # (already direction-aware) trend sub-score actually moves.
                    snap_trend = str(getattr(snapshot, "trend", "sideways")).lower()
                    if snap_trend == "uptrend":
                        ma_stack = "bullish"
                    elif snap_trend == "downtrend":
                        ma_stack = "bearish"
                    else:  # sideways / unknown
                        ma_stack = "neutral\""""),
]


def main():
    planned, already, mismatch, cache = [], [], [], {}
    for path, tag, old, new in EDITS:
        full = os.path.join(REPO, path)
        if not os.path.exists(full):
            mismatch.append((tag, f"file not found: {path}")); continue
        if full not in cache:
            cache[full] = open(full, encoding="utf-8").read()
        c = cache[full]
        if old in c:
            cache[full] = c.replace(old, new, 1); planned.append((path, tag))
        elif new in c:
            already.append((path, tag))
        else:
            mismatch.append((tag, f"anchor not found in {path}"))

    print("=" * 64); print("v19.34.215 deploy"); print("=" * 64)
    for p, t in planned:  print(f"  WILL APPLY : {t:20s} {p}")
    for p, t in already:  print(f"  already ok : {t:20s} {p}")
    for t, w in mismatch: print(f"  !! MISMATCH: {t:20s} {w}")

    if mismatch:
        print("\nABORTING — anchor mismatch. NOTHING written. Paste this back."); sys.exit(2)
    if not planned:
        print("\nNothing to do — already applied (idempotent no-op)."); sys.exit(0)

    for full, content in cache.items():
        open(full, "w", encoding="utf-8").write(content)
    import ast
    for path in {p for p, _ in planned}:
        ast.parse(open(os.path.join(REPO, path), encoding="utf-8").read())
    print(f"\nApplied {len(planned)} edit(s). Syntax OK.")

    rc = os.system('git add -A && git commit -m "v19.34.215: ma_stack derives from '
                   'snapshot.trend (kills the always-neutral mixed-timeframe stack)" '
                   '&& git push')
    if rc != 0:
        print("\n⚠️  git push non-zero — resolve before restart (wipe hazard)."); sys.exit(4)
    print("\n✅ Committed + pushed. Restart the backend to load.")


if __name__ == "__main__":
    main()
