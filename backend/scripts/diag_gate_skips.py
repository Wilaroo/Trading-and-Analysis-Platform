#!/usr/bin/env python3
"""
diag_gate_skips.py — WHY is the confidence gate skipping ~100% of trades?

Read-only. Hits the local API, pulls the recent confidence-gate decision log,
and buckets every decision by the layer that drove it (meta-labeler hard veto /
active regime suppression / low confidence / GO / REDUCE). Prints the dominant
cause + average confidence + a sample reasoning chain so we know exactly which
gate layer to recalibrate.

Usage (on the DGX):
    .venv/bin/python backend/scripts/diag_gate_skips.py
    .venv/bin/python backend/scripts/diag_gate_skips.py --limit 200
"""
import json
import os
import sys
import urllib.request
from collections import Counter

BASE = os.environ.get("DIAG_API_BASE", "http://localhost:8001")
LIMIT = 100
if "--limit" in sys.argv:
    try:
        LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])
    except (ValueError, IndexError):
        pass


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
        return json.loads(r.read().decode())


def classify(d):
    """Return the bucket key for a single decision based on its reasoning."""
    dec = (d.get("decision") or "?").upper()
    r = " | ".join(d.get("reasoning") or [])
    rl = r.lower()
    if dec == "GO":
        return "GO ✅"
    if dec == "REDUCE":
        return "REDUCE ⚠️"
    # everything below is a SKIP — find the cause
    if "regime suppression" in rl and "skip" in rl:
        return "SKIP · regime-suppression (T6 expectancy table)"
    if "meta-labeler" in rl or "no edge" in rl or "p_win" in rl:
        return "SKIP · meta-labeler hard veto (p_win<0.5)"
    if "insufficient confirmation" in rl:
        return "SKIP · low confidence (below reduce threshold)"
    return f"SKIP · other ({dec})"


def main():
    print("=" * 70)
    print(f"CONFIDENCE-GATE SKIP DIAGNOSIS   ({BASE})")
    print("=" * 70)

    # 1) headline counters
    try:
        summ = _get("/api/ai-training/confidence-gate/summary")
        t = summ.get("today", {})
        print("\n■ TODAY (from gate.get_summary):")
        print(f"   mode        : {summ.get('trading_mode')}  — {summ.get('mode_reason')}")
        print(f"   evaluated   : {t.get('evaluated')}")
        print(f"   taken (GO)  : {t.get('taken')}")
        print(f"   skipped     : {t.get('skipped')}")
        print(f"   take_rate   : {t.get('take_rate')}")
    except Exception as e:
        print(f"   summary fetch failed: {e}")

    # 2) decision-log breakdown
    try:
        resp = _get(f"/api/ai-training/confidence-gate/decisions?limit={LIMIT}")
        ds = resp.get("decisions", [])
    except Exception as e:
        print(f"\n   decision-log fetch failed: {e}")
        return

    print(f"\n■ DECISION-LOG BREAKDOWN  (last {len(ds)} decisions)")
    if not ds:
        print("   (decision log empty — gate may not have run yet today)")
        return

    buckets = Counter(classify(d) for d in ds)
    confs = [d.get("confidence_score") for d in ds if d.get("confidence_score") is not None]
    avg_conf = round(sum(confs) / len(confs), 1) if confs else None
    print(f"   avg confidence score : {avg_conf}")
    print(f"   distinct regimes seen: {sorted({d.get('regime_state') for d in ds if d.get('regime_state')})}")
    print(f"   distinct directions  : {sorted({d.get('direction') for d in ds if d.get('direction')})}")
    print("\n   ┌─ DOMINANT CAUSE (most-common first) ─────────────────────")
    for k, v in buckets.most_common():
        bar = "█" * max(1, round(40 * v / len(ds)))
        print(f"   │ {v:4d}  {bar}  {k}")
    print("   └──────────────────────────────────────────────────────────")

    # 3) one full sample reasoning chain (the most common bucket)
    top_key = buckets.most_common(1)[0][0]
    sample = next((d for d in ds if classify(d) == top_key), ds[0])
    print(f"\n■ SAMPLE of the dominant bucket  [{top_key}]")
    print(f"   {sample.get('symbol')} {sample.get('setup_type')} {sample.get('direction')} "
          f"· score={sample.get('confidence_score')} · regime={sample.get('regime_state')} "
          f"· ai_regime={sample.get('ai_regime')} · mode={sample.get('trading_mode')}")
    print("   reasoning:")
    for line in (sample.get("reasoning") or []):
        print(f"     • {line}")

    print("\n■ VERDICT")
    top_v = buckets.most_common(1)[0][1]
    pct = round(100 * top_v / len(ds))
    print(f"   {pct}% of recent decisions are driven by: {top_key}")
    print("   → That is the layer to recalibrate. Share this output.")


if __name__ == "__main__":
    main()
