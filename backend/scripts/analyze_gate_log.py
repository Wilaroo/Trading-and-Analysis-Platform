"""
Confidence Gate Log Analyzer
============================

Empirical per-layer diagnostic for the 13-layer Confidence Gate.

WHY
---
Phase 13 revalidation (2026-04-23) rejected every setup because the stacked
13-layer AND-gate filtered ~100% of candidates. We need data, not theory, on
which layers are pulling weight vs. adding friction before we touch models.

WHAT IT DOES
------------
Reads `confidence_gate_log` (deployed already persists structured reasoning
per evaluation — see confidence_gate.py line ~750) and for every layer emits:

    count          — how many evaluations the layer actually fired on
    fire_rate      — share of all evaluations where the layer contributed
    positive_rate  — share of fires with score delta > 0
    negative_rate  — share of fires with score delta < 0
    mean_delta     — mean signed point contribution when fired
    median_delta   — median signed point contribution
    stdev_delta    — dispersion across fires

When the log has outcome_tracked=True docs, we also compute:

    win_rate_when_layer_positive   — conditional WR given layer gave +N
    win_rate_when_layer_negative   — conditional WR given layer gave -N
    edge_when_positive_vs_overall  — positive contribution's win rate delta vs baseline

That "edge" number is the one we care about — a layer whose "fires positive"
win rate is LOWER than the overall baseline is actively hurting us.

OUTPUT
------
    /tmp/gate_log_stats.md   — markdown report (human-readable)
    /tmp/gate_log_stats.json — machine-readable for NIA / further analysis

STDOUT gets the summary table.

USAGE
-----
    PYTHONPATH=backend python backend/scripts/analyze_gate_log.py
    PYTHONPATH=backend python backend/scripts/analyze_gate_log.py --days 30
    PYTHONPATH=backend python backend/scripts/analyze_gate_log.py --setup SCALP --direction long
"""
from __future__ import annotations
import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pymongo import MongoClient


# ── Layer classification ────────────────────────────────────────────────
# Order matters: first matching rule wins. Patterns are anchored on the
# reasoning line. This mirrors the free-form reasoning prefixes emitted
# by services/ai_modules/confidence_gate.py and is the contract this
# analyzer depends on.

LAYER_SPECS: List[Tuple[str, re.Pattern, str]] = [
    ("layer_1_regime",       re.compile(r"^Regime\b"),                         "Regime Check"),
    ("layer_3_consensus",    re.compile(r"^(Model consensus|No trained models)"), "Model Consensus"),
    ("layer_4_live_pred",    re.compile(r"^Live\b"),                           "Live Model Prediction"),
    ("layer_5_cross_model",  re.compile(r"^Cross-model"),                      "Cross-Model Agreement"),
    ("layer_6_quality",      re.compile(r"^Quality score"),                    "Quality Score"),
    ("layer_7_learning",     re.compile(r"^Learning Loop"),                    "Learning Loop Feedback"),
    ("layer_8_cnn",          re.compile(r"^CNN visual"),                       "CNN Visual Pattern"),
    ("layer_9_tft",          re.compile(r"^TFT\b"),                            "TFT Multi-Timeframe"),
    ("layer_10_vae",         re.compile(r"^VAE\b"),                            "VAE Regime"),
    ("layer_11_cnn_lstm",    re.compile(r"^CNN-LSTM"),                         "CNN-LSTM Temporal"),
    ("layer_12_ensemble",    re.compile(r"^Ensemble meta-labeler"),            "Ensemble Meta-Labeler"),
    ("layer_13_finbert",     re.compile(r"^FinBERT sentiment"),                "FinBERT Sentiment"),
]

LAYER_LABELS = {k: label for k, _, label in LAYER_SPECS}

# Final decision strings — excluded from per-layer attribution
DECISION_LINE_RE = re.compile(r"^(Borderline confidence|Insufficient confirmation)")

# Extract a signed integer delta from a reasoning line.
# Matches the last "(+N...)" or "(-N...)" group, which is the score-delta
# convention in confidence_gate.py. Examples it must catch:
#   "Quality score HIGH (80) (+10)"                          → +10
#   "Regime BEARISH — against long (-10, size -30%)"         → -10
#   "Live xgb_... DISAGREES (...) (-5, size -15%)"           → -5
#   "FinBERT sentiment: bullish (...) aligned STRONG (+10)"  → +10
DELTA_RE = re.compile(r"\(([+-]\d+)(?:[^)]*?)\)\s*$")


def classify_layer(line: str) -> Optional[str]:
    if not line:
        return None
    s = line.strip()
    if DECISION_LINE_RE.match(s):
        return None
    for key, pat, _label in LAYER_SPECS:
        if pat.search(s):
            return key
    return None


def extract_delta(line: str) -> Optional[int]:
    """Return the signed score delta if the line encodes one, else None.

    None means the layer fired but stayed neutral (e.g. "Regime NEUTRAL (score 55)").
    """
    if not line:
        return None
    m = DELTA_RE.search(line.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


# ── Per-doc layer extraction ────────────────────────────────────────────

def layer_deltas_for_doc(doc: Dict[str, Any]) -> Dict[str, int]:
    """Return {layer_key: summed_delta} for one gate-log doc.

    A layer may emit multiple reasoning lines; we sum their deltas so the
    aggregate reflects net contribution per evaluation.
    Layers that fired neutrally (no signed delta) register with a 0.
    """
    deltas: Dict[str, int] = {}
    reasoning = doc.get("reasoning") or []
    if not isinstance(reasoning, list):
        return deltas
    for line in reasoning:
        key = classify_layer(line)
        if not key:
            continue
        d = extract_delta(line)
        current = deltas.get(key)
        if d is None:
            if current is None:
                deltas[key] = 0
            # else: keep already-recorded numeric delta for this layer
        else:
            deltas[key] = (current or 0) + d
    return deltas


# ── Aggregation ─────────────────────────────────────────────────────────

def aggregate(docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute per-layer stats + decision breakdown + optional outcome edge."""
    per_layer: Dict[str, List[int]] = defaultdict(list)
    decision_counts = {"GO": 0, "REDUCE": 0, "SKIP": 0}
    outcome_counts = {"win": 0, "loss": 0, "scratch": 0}
    # For outcome-correlation: per-layer list of (delta, outcome_str)
    per_layer_outcomes: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

    total = 0
    outcome_tracked = 0

    for doc in docs:
        total += 1
        decision = doc.get("decision", "")
        if decision in decision_counts:
            decision_counts[decision] += 1

        deltas = layer_deltas_for_doc(doc)
        for key, delta in deltas.items():
            per_layer[key].append(delta)

        if doc.get("outcome_tracked") is True:
            outcome = (doc.get("trade_outcome") or "").strip().lower()
            if outcome in outcome_counts:
                outcome_counts[outcome] += 1
                outcome_tracked += 1
                for key, delta in deltas.items():
                    per_layer_outcomes[key].append((delta, outcome))

    baseline_win_rate = (
        outcome_counts["win"] / outcome_tracked if outcome_tracked else None
    )

    layers_report: Dict[str, Dict[str, Any]] = {}
    for key, _pat, label in LAYER_SPECS:
        series = per_layer.get(key, [])
        count = len(series)
        positives = [d for d in series if d > 0]
        negatives = [d for d in series if d < 0]
        layer = {
            "label": label,
            "count": count,
            "fire_rate": round(count / total, 4) if total else 0.0,
            "positive_count": len(positives),
            "negative_count": len(negatives),
            "neutral_count": count - len(positives) - len(negatives),
            "positive_rate": round(len(positives) / count, 4) if count else 0.0,
            "negative_rate": round(len(negatives) / count, 4) if count else 0.0,
            "mean_delta": round(statistics.fmean(series), 3) if series else 0.0,
            "median_delta": round(statistics.median(series), 3) if series else 0.0,
            "stdev_delta": round(statistics.pstdev(series), 3) if len(series) > 1 else 0.0,
        }

        out_pairs = per_layer_outcomes.get(key, [])
        if out_pairs and baseline_win_rate is not None:
            pos_pairs = [o for d, o in out_pairs if d > 0]
            neg_pairs = [o for d, o in out_pairs if d < 0]
            layer["tracked_outcomes"] = len(out_pairs)
            if pos_pairs:
                wr_pos = sum(1 for o in pos_pairs if o == "win") / len(pos_pairs)
                layer["win_rate_when_positive"] = round(wr_pos, 4)
                layer["edge_when_positive"] = round(wr_pos - baseline_win_rate, 4)
                layer["n_positive_tracked"] = len(pos_pairs)
            if neg_pairs:
                wr_neg = sum(1 for o in neg_pairs if o == "win") / len(neg_pairs)
                layer["win_rate_when_negative"] = round(wr_neg, 4)
                layer["edge_when_negative"] = round(wr_neg - baseline_win_rate, 4)
                layer["n_negative_tracked"] = len(neg_pairs)

        layers_report[key] = layer

    return {
        "total_evaluations": total,
        "decision_counts": decision_counts,
        "decision_distribution": {
            k: round(v / total, 4) if total else 0.0 for k, v in decision_counts.items()
        },
        "outcome_tracked": outcome_tracked,
        "outcome_counts": outcome_counts,
        "baseline_win_rate": round(baseline_win_rate, 4) if baseline_win_rate is not None else None,
        "layers": layers_report,
    }


# ── CLI / reporting ────────────────────────────────────────────────────

def _build_query(args: argparse.Namespace) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if args.days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        q["timestamp"] = {"$gte": cutoff.isoformat()}
    if args.symbol:
        q["symbol"] = args.symbol.upper()
    if args.setup:
        q["setup_type"] = args.setup.upper()
    if args.direction:
        q["direction"] = args.direction.lower()
    if args.outcome_only:
        q["outcome_tracked"] = True
    return q


def render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Confidence Gate Log — Per-Layer Diagnostic")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append(f"- Total evaluations: **{report['total_evaluations']}**")
    lines.append(f"- Decision mix: {report['decision_counts']}")
    lines.append(f"- Outcome-tracked: {report['outcome_tracked']}")
    if report["baseline_win_rate"] is not None:
        lines.append(f"- Baseline win rate: **{report['baseline_win_rate']:.1%}**")
    lines.append("")
    lines.append("## Per-Layer Contribution")
    lines.append("")
    lines.append("| Layer | Fire rate | +rate | -rate | mean Δ | median Δ | stdev | WR(+) | edge(+) | n+ |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for key, _pat, _label in LAYER_SPECS:
        L = report["layers"].get(key, {})
        wr_pos = L.get("win_rate_when_positive")
        edge_pos = L.get("edge_when_positive")
        n_pos = L.get("n_positive_tracked")
        lines.append(
            f"| {L.get('label', key)} "
            f"| {L.get('fire_rate', 0):.1%} "
            f"| {L.get('positive_rate', 0):.1%} "
            f"| {L.get('negative_rate', 0):.1%} "
            f"| {L.get('mean_delta', 0):+.2f} "
            f"| {L.get('median_delta', 0):+.2f} "
            f"| {L.get('stdev_delta', 0):.2f} "
            f"| {f'{wr_pos:.1%}' if wr_pos is not None else '—'} "
            f"| {f'{edge_pos:+.1%}' if edge_pos is not None else '—'} "
            f"| {n_pos if n_pos is not None else '—'} |"
        )
    lines.append("")
    lines.append("## Friction-vs-Edge Verdict (heuristic)")
    lines.append("")
    verdicts = verdict_per_layer(report)
    for key, v in verdicts.items():
        lines.append(f"- **{LAYER_LABELS[key]}**: {v}")
    return "\n".join(lines) + "\n"


def verdict_per_layer(report: Dict[str, Any]) -> Dict[str, str]:
    """Heuristic verdict per layer: edge / friction / low-data / neutral."""
    baseline = report.get("baseline_win_rate")
    total = report.get("total_evaluations", 0)
    out: Dict[str, str] = {}
    for key, _pat, _label in LAYER_SPECS:
        L = report["layers"].get(key, {})
        count = L.get("count", 0)
        fr = L.get("fire_rate", 0)

        if total < 100 or count < 30:
            out[key] = f"LOW DATA (n={count})"
            continue

        edge_pos = L.get("edge_when_positive")
        n_pos = L.get("n_positive_tracked", 0)

        if edge_pos is None or baseline is None or n_pos < 20:
            # No outcome data yet — fall back to coverage/mean
            if fr < 0.05:
                out[key] = f"DORMANT (fire_rate={fr:.1%})"
            elif abs(L.get("mean_delta", 0)) < 0.5:
                out[key] = f"LOW IMPACT (mean Δ={L.get('mean_delta', 0):+.2f})"
            else:
                out[key] = f"PENDING OUTCOMES (n={count}, mean Δ={L.get('mean_delta', 0):+.2f})"
            continue

        if edge_pos >= 0.03:
            out[key] = f"EDGE (+{edge_pos:.1%} WR lift over baseline, n+={n_pos})"
        elif edge_pos <= -0.03:
            out[key] = f"FRICTION ({edge_pos:+.1%} WR drag, n+={n_pos}) — consider pruning"
        else:
            out[key] = f"NEUTRAL ({edge_pos:+.1%} WR shift, n+={n_pos})"
    return out


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    return client[db_name]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze confidence_gate_log for per-layer contribution.")
    parser.add_argument("--days", type=int, default=14, help="Lookback window (default 14)")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--setup", type=str, default=None)
    parser.add_argument("--direction", type=str, default=None, choices=["long", "short"])
    parser.add_argument("--outcome-only", action="store_true", help="Only include outcome_tracked=True docs")
    parser.add_argument("--limit", type=int, default=0, help="Hard cap on docs (0 = no cap)")
    parser.add_argument("--out-md", type=str, default="/tmp/gate_log_stats.md")
    parser.add_argument("--out-json", type=str, default="/tmp/gate_log_stats.json")
    args = parser.parse_args(argv)

    db = get_db()
    query = _build_query(args)
    cursor = db["confidence_gate_log"].find(query, {"_id": 0})
    if args.limit > 0:
        cursor = cursor.limit(args.limit)

    docs = list(cursor)
    report = aggregate(docs)
    report["query"] = query
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    with open(args.out_json, "w") as f:
        json.dump(report, f, default=str, indent=2)
    md = render_markdown(report)
    with open(args.out_md, "w") as f:
        f.write(md)

    print(md)
    print(f"\nWrote {args.out_md} and {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
