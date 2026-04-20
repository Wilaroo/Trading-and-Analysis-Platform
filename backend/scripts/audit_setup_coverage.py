"""
Setup Coverage Audit — run immediately after the big retrain finishes.

Purpose
-------
Your TRADING_TAXONOMY.md defines ~35 SMB-style setups (rubber_band, spencer_scalp,
9_ema_scalp, hitchhiker, bella_fade, ...) but the XGBoost pipeline currently only
trains 10 generic long + 10 generic short families (BREAKOUT / MOMENTUM / SCALP / ...).

This script answers: "Which of the 35 taxonomy setups have enough tagged
historical trades to train dedicated XGBoost + CNN models?"

It is the gating step before Phase 2E (setup-specific visual CNN meta-labeler)
and before Step 6 (adding dedicated SMB setup models).

Inputs
------
Reads from Mongo `tradecommand` DB:
    - trades            (manual journal entries)
    - bot_trades        (auto-executed)
    - trade_snapshots   (training-grade snapshots)
    - live_alerts       (scanner fires, even if not taken)

Key fields: `setup_type` (lowercase taxonomy code), `r_multiple` (outcome).

Output
------
    /tmp/setup_coverage_audit.md — table + recommendations
    stdout                       — compact summary

Run
---
    PYTHONPATH=backend python backend/scripts/audit_setup_coverage.py
    PYTHONPATH=backend python backend/scripts/audit_setup_coverage.py --min-count 50

Recommends which setups to promote to dedicated models for Phase 2E / Step 6
of the post-retrain roadmap (see /app/memory/PRD.md).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pymongo import MongoClient

# ── Config ──────────────────────────────────────────────────────────────

# 35 taxonomy codes from /app/documents/TRADING_TAXONOMY.md
# (some scanner fires use `<code>_long` / `<code>_short` variants — handled below)
TAXONOMY_SETUPS = [
    # Opening (9:30-9:45)
    "first_vwap_pullback", "first_move_up", "first_move_down",
    "bella_fade", "opening_drive", "back_through_open", "up_through_open",
    # Morning momentum (9:45-10:30)
    "orb", "hitchhiker", "gap_give_go", "gap_pick_roll",
    # Core session (10:30-13:30)
    "spencer_scalp", "second_chance", "backside", "off_sides",
    "fashionably_late", "big_dog", "puppy_dog",
    # Mean reversion (all day)
    "rubber_band", "vwap_bounce", "vwap_fade", "tidal_wave", "mean_reversion",
    # Consolidation / squeeze
    "squeeze", "9_ema_scalp", "abc_scalp",
    # Afternoon
    "hod_breakout", "time_of_day_fade",
    # Special
    "breaking_news", "volume_capitulation", "range_break",
    "breakout", "relative_strength", "gap_fade", "chart_pattern",
]

# If a stored setup_type has any of these as a prefix, bucket to the root.
# e.g. "rubber_band_long" → "rubber_band"
SUFFIXES = ["_long", "_short", "_confirmed"]
PREFIXES = ["approaching_"]

# Collections to scan
COLLECTIONS = ["trades", "bot_trades", "trade_snapshots", "live_alerts"]

# Default thresholds
DEFAULT_MIN_COUNT = 100
DEFAULT_MIN_WIN_RATE = 0.40  # below this we don't consider it worth training


# ── Helpers ─────────────────────────────────────────────────────────────

def normalize_setup_code(raw: Optional[str]) -> Optional[str]:
    """Map a stored setup_type value to its taxonomy root."""
    if not raw:
        return None
    code = str(raw).strip().lower()
    for p in PREFIXES:
        if code.startswith(p):
            code = code[len(p):]
    for s in SUFFIXES:
        if code.endswith(s):
            code = code[: -len(s)]
    return code or None


def get_db():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        # Sensible default for local Spark runs
        mongo_url = "mongodb://localhost:27017"
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    return client[db_name]


def _aggregate_collection(db, coll_name: str) -> Dict[str, Dict]:
    """Return per-setup stats pulled from one collection."""
    stats: Dict[str, Dict] = defaultdict(lambda: {
        "count": 0,
        "r_sum": 0.0,
        "r_samples": 0,
        "wins": 0,
        "losses": 0,
        "has_outcome": 0,
    })
    try:
        coll = db[coll_name]
    except Exception:
        return {}

    try:
        cursor = coll.find(
            {"setup_type": {"$exists": True, "$nin": [None, ""]}},
            {"setup_type": 1, "r_multiple": 1, "pnl": 1,
             "realized_pnl": 1, "outcome": 1, "status": 1, "_id": 0},
        )
    except Exception as e:
        print(f"[WARN] Could not query {coll_name}: {e}", file=sys.stderr)
        return {}

    for doc in cursor:
        code = normalize_setup_code(doc.get("setup_type"))
        if not code:
            continue
        s = stats[code]
        s["count"] += 1

        # R-multiple (preferred outcome measure)
        r = doc.get("r_multiple")
        if r is not None:
            try:
                r_val = float(r)
                s["r_sum"] += r_val
                s["r_samples"] += 1
                s["has_outcome"] += 1
                if r_val > 0:
                    s["wins"] += 1
                elif r_val < 0:
                    s["losses"] += 1
            except (TypeError, ValueError):
                pass
            continue

        # Fallback: use pnl sign
        pnl = doc.get("pnl") or doc.get("realized_pnl")
        if pnl is not None:
            try:
                p = float(pnl)
                s["has_outcome"] += 1
                if p > 0:
                    s["wins"] += 1
                elif p < 0:
                    s["losses"] += 1
            except (TypeError, ValueError):
                pass

    return stats


def merge_stats(all_stats: List[Dict[str, Dict]]) -> Dict[str, Dict]:
    """Merge per-collection stats into a unified per-setup dict."""
    merged: Dict[str, Dict] = defaultdict(lambda: {
        "count": 0, "r_sum": 0.0, "r_samples": 0,
        "wins": 0, "losses": 0, "has_outcome": 0,
    })
    for stats in all_stats:
        for code, s in stats.items():
            m = merged[code]
            for k in ("count", "r_sum", "r_samples",
                      "wins", "losses", "has_outcome"):
                m[k] += s[k]
    return merged


def finalize(merged: Dict[str, Dict]) -> List[Dict]:
    """Compute win_rate, avg_r, and verdict per setup. Returns sorted list."""
    rows = []
    for code, s in merged.items():
        decided = s["wins"] + s["losses"]
        win_rate = (s["wins"] / decided) if decided > 0 else None
        avg_r = (s["r_sum"] / s["r_samples"]) if s["r_samples"] > 0 else None
        rows.append({
            "setup_code": code,
            "count": s["count"],
            "has_outcome": s["has_outcome"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": win_rate,
            "avg_r": avg_r,
            "in_taxonomy": code in TAXONOMY_SETUPS,
        })
    rows.sort(key=lambda r: r["count"], reverse=True)
    return rows


def classify(row: Dict, min_count: int, min_win_rate: float) -> str:
    # too_few = not enough to compute reliable stats.
    # thin    = enough to have stats, but below training confidence.
    too_few_floor = min(20, max(5, min_count // 2))
    if row["count"] < too_few_floor:
        return "too_few"
    if row["count"] < min_count:
        return "thin"
    if row["win_rate"] is None:
        return "unknown_outcome"
    if row["win_rate"] < min_win_rate:
        return "negative_edge"
    return "trainable"


def render_markdown(rows: List[Dict], min_count: int,
                    min_win_rate: float) -> str:
    lines = [
        "# Setup Coverage Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Thresholds: min_count={min_count}, min_win_rate={min_win_rate:.0%}",
        "",
        "## Per-setup stats",
        "",
        "| setup_code | in_tax | # tagged | w-l | win_rate | avg_R | verdict |",
        "|------------|:------:|---------:|:---:|---------:|------:|---------|",
    ]
    summary = defaultdict(list)
    for r in rows:
        verdict = classify(r, min_count, min_win_rate)
        summary[verdict].append(r["setup_code"])
        wl = f"{r['wins']}-{r['losses']}"
        wr = f"{r['win_rate']*100:.1f}%" if r["win_rate"] is not None else "—"
        ar = f"{r['avg_r']:+.2f}R" if r["avg_r"] is not None else "—"
        tax = "✅" if r["in_taxonomy"] else "⚠️"
        lines.append(
            f"| `{r['setup_code']}` | {tax} | {r['count']} | {wl} | {wr} | {ar} | {verdict} |"
        )

    # Taxonomy setups with ZERO data
    seen = {r["setup_code"] for r in rows}
    missing = [c for c in TAXONOMY_SETUPS if c not in seen]

    lines += [
        "",
        "## Summary",
        "",
        f"- **Trainable** (≥{min_count} + win_rate ≥ {min_win_rate:.0%}): {len(summary['trainable'])}",
        f"  - {', '.join(summary['trainable']) if summary['trainable'] else '_none_'}",
        f"- **Thin** (20-{min_count} trades — collect more data): {len(summary['thin'])}",
        f"  - {', '.join(summary['thin']) if summary['thin'] else '_none_'}",
        f"- **Negative edge** (enough data but win_rate < {min_win_rate:.0%}): {len(summary['negative_edge'])}",
        f"  - {', '.join(summary['negative_edge']) if summary['negative_edge'] else '_none_'}",
        f"- **Too few** (< 20 trades): {len(summary['too_few'])}",
        f"- **Unknown outcome** (no r_multiple / pnl stored): {len(summary['unknown_outcome'])}",
        "",
        f"### Taxonomy codes with NO tagged data ({len(missing)})",
        "_These setups exist in TRADING_TAXONOMY.md but have never been tagged in Mongo._",
        "",
    ]
    for code in missing:
        lines.append(f"- `{code}`")

    # Non-taxonomy codes (scanner drift / legacy naming)
    non_tax = [r for r in rows if not r["in_taxonomy"] and r["count"] >= 10]
    if non_tax:
        lines += [
            "",
            "### Stored setup_types NOT in taxonomy (scanner drift?)",
            "_These appear in Mongo but are not in TRADING_TAXONOMY.md. "
            "Candidates for taxonomy addition or scanner cleanup._",
            "",
        ]
        for r in non_tax[:30]:
            lines.append(f"- `{r['setup_code']}` — {r['count']} rows")

    # Recommendations
    lines += [
        "",
        "## Recommendations",
        "",
        "### Phase 2E Tier-1 training targets",
        "_These setups have enough data AND a visual pattern signature "
        "(per SMB playbook). Train dedicated XGBoost + visual CNN pairs._",
        "",
    ]
    visual_priors = {
        "rubber_band", "9_ema_scalp", "abc_scalp", "spencer_scalp",
        "bella_fade", "first_vwap_pullback", "vwap_bounce", "vwap_fade",
        "opening_drive", "hitchhiker", "gap_give_go", "hod_breakout",
        "tidal_wave", "volume_capitulation",
    }
    tier1 = [c for c in summary["trainable"] if c in visual_priors]
    for code in tier1:
        lines.append(f"- `{code}`")
    if not tier1:
        lines.append("_none yet — need more tagged data on visual setups_")

    lines += [
        "",
        "### Immediate actions",
        "1. For every `trainable` + visual setup above, add a dedicated feature "
        "extractor in `setup_features.py` / `short_setup_features.py`.",
        "2. Run PT/SL sweep for each new setup code.",
        "3. Add to the next retrain cycle with `TB_USE_CUSUM=1 TB_USE_FFD_FEATURES=1`.",
        "4. Taxonomy codes with 0 tagged data → add scanner detectors OR remove "
        "from taxonomy (dead weight).",
        "5. Non-taxonomy codes in Mongo → decide: promote to taxonomy or rename "
        "at the scanner.",
        "",
    ]
    return "\n".join(lines)


def render_compact(rows: List[Dict], min_count: int,
                   min_win_rate: float) -> str:
    """Short stdout summary."""
    summary = defaultdict(list)
    for r in rows:
        summary[classify(r, min_count, min_win_rate)].append(r["setup_code"])
    seen = {r["setup_code"] for r in rows}
    missing = [c for c in TAXONOMY_SETUPS if c not in seen]

    lines = [
        "",
        "=" * 70,
        "SETUP COVERAGE AUDIT",
        "=" * 70,
        f"Total unique setup_types in Mongo: {len(rows)}",
        f"Taxonomy setups (of {len(TAXONOMY_SETUPS)}):",
        f"  ✅ trainable      : {len(summary['trainable'])}",
        f"  ⚠️  thin           : {len(summary['thin'])}",
        f"  ❌ negative edge  : {len(summary['negative_edge'])}",
        f"  🪹 too few         : {len(summary['too_few'])}",
        f"  ❓ unknown outcome : {len(summary['unknown_outcome'])}",
        f"  👻 zero data       : {len(missing)}",
        "",
        "Top 10 by volume:",
    ]
    for r in rows[:10]:
        wr = f"{r['win_rate']*100:.1f}%" if r["win_rate"] else "—"
        ar = f"{r['avg_r']:+.2f}R" if r["avg_r"] else "—"
        flag = "✅" if r["in_taxonomy"] else "⚠️ NON-TAX"
        lines.append(
            f"  {r['setup_code']:<28} count={r['count']:>5}  "
            f"win={wr:>6}  avgR={ar:>7}  {flag}"
        )
    lines += ["", "Full report written to /tmp/setup_coverage_audit.md", ""]
    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT,
                    help="Minimum # tagged trades to consider setup trainable.")
    ap.add_argument("--min-win-rate", type=float, default=DEFAULT_MIN_WIN_RATE,
                    help="Minimum win rate (0.0-1.0) to consider trainable.")
    ap.add_argument("--output", type=str, default="/tmp/setup_coverage_audit.md",
                    help="Output Markdown report path.")
    ap.add_argument("--json", type=str, default=None,
                    help="Optional JSON path for machine-readable output.")
    args = ap.parse_args()

    db = get_db()
    print(f"[audit] connected to db.{db.name}")

    all_stats = []
    for coll in COLLECTIONS:
        s = _aggregate_collection(db, coll)
        print(f"[audit] {coll:>20} → {len(s)} distinct setup_types")
        all_stats.append(s)

    merged = merge_stats(all_stats)
    rows = finalize(merged)

    md = render_markdown(rows, args.min_count, args.min_win_rate)
    Path(args.output).write_text(md)
    print(render_compact(rows, args.min_count, args.min_win_rate))

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, default=str))
        print(f"[audit] JSON written to {args.json}")


if __name__ == "__main__":
    main()
