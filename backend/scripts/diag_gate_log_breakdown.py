#!/usr/bin/env python3
"""
diag_gate_log_breakdown.py — read the REAL gate decisions (offline).

Aggregates the persisted `confidence_gate_log` to answer: what's the actual
GO/REDUCE/SKIP take-rate, in what trading mode, and WHY are SKIPs skipping
(score vs threshold? regime suppression? meta-labeler veto?).

Run from repo root:
    source .venv/bin/activate && python backend/scripts/diag_gate_log_breakdown.py
"""
import re
import sys
from pathlib import Path
from collections import Counter

import numpy as np
from pymongo import MongoClient


def load_db():
    env = {}
    for line in Path("backend/.env").read_text().splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]


MODE_THRESH = {  # fallback only; we parse the real threshold from reasoning
    "AGGRESSIVE": 28, "NORMAL": 38, "CAUTIOUS": 50, "DEFENSIVE": 60,
}


def reason_bucket(d):
    r = " ".join(str(x) for x in (d.get("reasoning") or [])).lower()
    dec = (d.get("decision") or "?").upper()
    if dec in ("GO", "REDUCE"):
        return f"__{dec}"
    sup = d.get("regime_suppression")
    if sup and (sup is True or (isinstance(sup, dict) and sup)):
        if "suppress" in r or "regime" in r:
            return "SKIP: regime suppression (T6)"
    if "no edge" in r or "p(win)" in r or "meta-label" in r or "force" in r:
        return "SKIP: meta-labeler hard veto (p_win<0.5)"
    if "insufficient confirmation" in r or "need" in r:
        return "SKIP: score < threshold (additive starvation)"
    return "SKIP: other"


def main():
    col = load_db()["confidence_gate_log"]
    n = col.estimated_document_count()
    if n == 0:
        print("confidence_gate_log is EMPTY — the gate hasn't logged any live decisions.")
        print("That itself is the finding: the scanner/engine isn't feeding candidates to the gate.")
        return

    docs = list(col.find({}, {
        "decision": 1, "confidence_score": 1, "trading_mode": 1,
        "regime_suppression": 1, "reasoning": 1, "setup_type": 1,
        "direction": 1, "symbol": 1, "timestamp": 1, "_id": 0,
    }).sort("timestamp", -1).limit(5000))

    ts = [d.get("timestamp") for d in docs if d.get("timestamp")]
    print(f"=== confidence_gate_log: {n:,} total, analyzing last {len(docs)} ===")
    if ts:
        print(f"time range: {min(ts)[:19]}  →  {max(ts)[:19]}\n")

    dec = Counter(str(d.get("decision", "?")).upper() for d in docs)
    tot = sum(dec.values())
    print("DECISIONS:")
    for k in ("GO", "REDUCE", "SKIP", "?"):
        if dec.get(k):
            print(f"  {k:<7} {dec[k]:>6}  ({dec[k]/tot*100:5.1f}%)")
    take = (dec.get("GO", 0) + dec.get("REDUCE", 0)) / tot * 100
    print(f"  → TAKE-RATE (GO+REDUCE): {take:.1f}%\n")

    print("TRADING MODE:")
    for m, c in Counter(str(d.get("trading_mode", "?")) for d in docs).most_common():
        print(f"  {m:<12} {c:>6}  ({c/tot*100:5.1f}%)")
    print()

    scores = np.array([float(d.get("confidence_score", 0) or 0) for d in docs])
    skips = [d for d in docs if str(d.get("decision", "")).upper() == "SKIP"]
    sk_scores = np.array([float(d.get("confidence_score", 0) or 0) for d in skips]) if skips else np.array([])
    print("CONFIDENCE SCORE:")
    print(f"  all:   min={scores.min():.0f} p25={np.percentile(scores,25):.0f} "
          f"median={np.median(scores):.0f} p75={np.percentile(scores,75):.0f} max={scores.max():.0f}")
    if len(sk_scores):
        print(f"  skips: min={sk_scores.min():.0f} median={np.median(sk_scores):.0f} max={sk_scores.max():.0f}")
    # parse the real GO threshold from reasoning text
    thr = []
    for d in docs:
        for r in (d.get("reasoning") or []):
            m = re.search(r"need (\d+(?:\.\d+)?) for GO", str(r))
            if m:
                thr.append(float(m.group(1)))
    if thr:
        print(f"  GO threshold seen in log: {sorted(set(thr))}\n")
    else:
        print()

    print("SKIP-CAUSE BREAKDOWN:")
    for k, c in Counter(reason_bucket(d) for d in docs).most_common():
        if k.startswith("__"):
            continue
        print(f"  {c:>6}  ({c/tot*100:5.1f}%)  {k}")
    print()

    print("Sample recent SKIPs (symbol | setup | dir | score | last reason):")
    for d in skips[:15]:
        rs = (d.get("reasoning") or ["-"])[-1]
        print(f"  {str(d.get('symbol','?')):<6} {str(d.get('setup_type','?')):<16} "
              f"{str(d.get('direction','?')):<5} score={d.get('confidence_score')} | {str(rs)[:70]}")


if __name__ == "__main__":
    main()
