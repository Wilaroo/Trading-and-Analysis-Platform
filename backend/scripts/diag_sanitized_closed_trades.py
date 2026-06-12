#!/usr/bin/env python3
"""
diag_sanitized_closed_trades.py — READ-ONLY sanitization funnel probe (v2)
===========================================================================
sanitize_v2: layers the codebase's CANONICAL genuineness filter
(`trade_outcome_hygiene.classify_close`, v19.34.240/263) over the v1
funnel, plus explicit exclusions v1 missed:

  * legacy_orphan      — close_reason contains "orphan"
                         (orphaned_position_cleanup: 70 rows survived v1;
                          NO current code path produces this reason — it is
                          a removed legacy cleanup era)
  * emergency_flatten  — panic flatten-everything (not a per-trade exit)
  * hygiene_artifact   — classify_close(is_genuine=False): phantom sweeps,
                         purges, reconcile closes, operator external
                         flattens, corrupt-R externals, corrupt P&L
                         attribution, instant external unwinds, artifact
                         setup_types (imported_from_ib, reconciled_*)

Full funnel (first matching reason wins, order matters):
  1. provenance     2. learning_only   3. simulated     4. admin_close
  5. legacy_orphan  6. hygiene_artifact (tag breakdown printed)
  7. never_filled   8. no_exit_price   9. no_risk
 10. sub_10s_hold  11. absurd_r

Survivors = SANITIZED CORE (meta-labeling basis).
SCORED CORE = CORE rows with tqs_score > 0 (TQS-rescale basis).

Outputs: funnel + hygiene tag breakdown, monthly era histogram,
close_reason mix, per-grade A/B>=30 re-verdict, per-setup >=100
re-verdict, /tmp/sanitized_trade_ids.json (NO DB writes).

Run from repo root:
  .venv/bin/python /tmp/diag_sanitized_closed_trades.py
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

BOT_PROVENANCE = {"bot_fired", "bot", "", None}

ADMIN_CLOSE_PREFIXES = (
    "stale_pending", "phantom_sibling_purge", "consolidated",
    "broker_rejected", "execution_exception", "guardrail_veto",
    "intent_already_pending", "rejection_cooldown", "symbol_cooldown",
    "paper_phase", "simulation_phase", "operator_flatten_suppression",
    "emergency_flatten",
)

FILTER_VERSION = "sanitize_v2"
OUT_PATH = "/tmp/sanitized_trade_ids.json"


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services" / "trade_outcome_hygiene.py").exists():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t):
    pnl = t.get("net_pnl")
    if pnl in (None, 0):
        pnl = t.get("realized_pnl") if t.get("realized_pnl") not in (None, 0) else t.get("pnl")
    risk = _f(t.get("risk_amount"))
    pnl = _f(pnl)
    if pnl is None or not risk:
        return None
    return pnl / risk


def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hold_seconds(t):
    hs = _f(t.get("hold_seconds"))
    if hs is not None and hs > 0:
        return hs
    a, b = _parse_ts(t.get("executed_at")), _parse_ts(t.get("closed_at"))
    if a and b:
        return (b - a).total_seconds()
    return None


def _exclusion_reason(t, classify_close, hygiene_tags):
    if t.get("entered_by") not in BOT_PROVENANCE:
        return "provenance"
    ec = t.get("entry_context") or {}
    if t.get("learning_only") is True or ec.get("learning_only") is True:
        return "learning_only"
    if "[SIMULATED]" in (t.get("notes") or "") or t.get("trade_type") == "shadow":
        return "simulated"
    cr = str(t.get("close_reason") or "")
    if any(cr.startswith(p) for p in ADMIN_CLOSE_PREFIXES):
        return "admin_close"
    if "orphan" in cr.lower():
        return "legacy_orphan"
    genuine, tag = classify_close(
        close_reason=cr,
        entered_by=str(t.get("entered_by") or ""),
        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
        exit_price=_f(t.get("exit_price")),
        net_pnl=_f(t.get("net_pnl")),
        hold_seconds=_hold_seconds(t),
        setup_type=str(t.get("setup_type") or ""),
        direction=t.get("direction"),
        stop_price=_f(t.get("stop_price")),
        target_prices=t.get("target_prices"),
        realized_pnl=_f(t.get("realized_pnl")),
        shares=_f(t.get("shares")),
    )
    if not genuine:
        hygiene_tags[tag] += 1
        return "hygiene_artifact"
    fill = _f(t.get("fill_price")) or _f(t.get("entry_price")) or 0
    if fill <= 0 or (_f(t.get("shares")) or 0) <= 0:
        return "never_filled"
    if (_f(t.get("exit_price")) or 0) <= 0:
        return "no_exit_price"
    if (_f(t.get("risk_amount")) or 0) <= 0:
        return "no_risk"
    hs = _hold_seconds(t)
    if hs is not None and hs < 10:
        return "sub_10s_hold"
    r = _r_multiple(t)
    if r is not None and abs(r) > 10:
        return "absurd_r"
    return None  # survivor


def _bucket_stats(rows):
    rs = [r for r in (_r_multiple(t) for t in rows) if r is not None]
    if not rs:
        return "n=%4d (no usable R)" % len(rows)
    wins = sum(1 for r in rs if r > 0)
    return (f"n={len(rs):4d}  win%={100.0*wins/len(rs):5.1f}  "
            f"avgR={sum(rs)/len(rs):+.2f}  medR={median(rs):+.2f}")


def main():
    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    closed = list(db["bot_trades"].find(
        {"status": {"$regex": "^closed"}},
        {"_id": 0, "id": 1, "symbol": 1, "entered_by": 1, "learning_only": 1,
         "entry_context.learning_only": 1, "notes": 1, "trade_type": 1,
         "close_reason": 1, "fill_price": 1, "entry_price": 1, "exit_price": 1,
         "shares": 1, "risk_amount": 1, "net_pnl": 1, "realized_pnl": 1,
         "pnl": 1, "hold_seconds": 1, "executed_at": 1, "closed_at": 1,
         "created_at": 1, "tqs_score": 1, "tqs_grade": 1, "unified_grade": 1,
         "setup_type": 1, "trade_style": 1, "direction": 1, "stop_price": 1,
         "target_prices": 1}))

    print("=" * 78)
    print(f"SANITIZED CLOSED-TRADES PROBE ({FILTER_VERSION}) — {len(closed)} raw closed rows")
    print("=" * 78)

    excluded = defaultdict(list)
    hygiene_tags = defaultdict(int)
    core = []
    for t in closed:
        reason = _exclusion_reason(t, classify_close, hygiene_tags)
        (core.append(t) if reason is None else excluded[reason].append(t))

    print("\n[1] EXCLUSION FUNNEL (first matching reason wins):")
    order = ["provenance", "learning_only", "simulated", "admin_close",
             "legacy_orphan", "hygiene_artifact", "never_filled",
             "no_exit_price", "no_risk", "sub_10s_hold", "absurd_r"]
    for reason in order:
        rows = excluded.get(reason, [])
        print(f"     -{len(rows):5d}  {reason}")
        for ex in rows[:3]:
            print(f"             e.g. {str(ex.get('symbol')):6s} "
                  f"closed={str(ex.get('closed_at'))[:19]} "
                  f"reason={str(ex.get('close_reason'))[:40]}")
    print(f"     ={len(core):5d}  SANITIZED CORE survivors "
          f"({100.0*len(core)/max(len(closed),1):.1f}% of raw)")

    if hygiene_tags:
        print("\n     hygiene_artifact tag breakdown (classify_close):")
        for tag, n in sorted(hygiene_tags.items(), key=lambda x: -x[1]):
            print(f"       {n:5d}  {tag}")

    print("\n[2] SURVIVORS BY MONTH (era check):")
    by_month = defaultdict(list)
    blank_created = 0
    for t in core:
        ca = t.get("created_at") or ""
        if len(ca) >= 7:
            by_month[ca[:7]].append(t)
        else:
            blank_created += 1
            by_month["?"].append(t)
    for m in sorted(by_month):
        print(f"     {m}: {_bucket_stats(by_month[m])}")
    if blank_created:
        print(f"     ⚠ {blank_created} survivor(s) with blank created_at (v322s legacy)")

    print("\n[3] SURVIVOR close_reason MIX (top 15):")
    cr_counts = defaultdict(int)
    for t in core:
        cr_counts[str(t.get("close_reason") or "?")] += 1
    for cr, n in sorted(cr_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"     {n:5d}  {cr}")

    scored = [t for t in core if (_f(t.get("tqs_score")) or 0) > 0]
    print(f"\n[4] SCORED CORE (tqs_score>0): {len(scored)} of {len(core)} survivors")
    if scored:
        vals = sorted(float(t["tqs_score"]) for t in scored)
        n = len(vals)
        print(f"     tqs_score: min={vals[0]:.1f} p25={vals[n//4]:.1f} "
              f"p50={vals[n//2]:.1f} p75={vals[3*n//4]:.1f} max={vals[-1]:.1f}")
        by_grade = defaultdict(list)
        for t in scored:
            by_grade[str(t.get("tqs_grade") or t.get("unified_grade") or "?")].append(t)
        print("     per-grade outcomes (SANITIZED, scored):")
        for g in sorted(by_grade):
            print(f"       grade {g:>2s}: {_bucket_stats(by_grade[g])}")
        a = [r for g, rows in by_grade.items() if g.upper().startswith("A") for r in rows]
        b = [r for g, rows in by_grade.items() if g.upper().startswith("B") for r in rows]
        verdict = "SUFFICIENT ✅" if len(a) >= 30 and len(b) >= 30 else "INSUFFICIENT ❌"
        print(f"     → SANITIZED A n={len(a)}, B n={len(b)} — {verdict} for TQS rescale (≥30 each)")
    else:
        print("     → no scored survivors — TQS rescale has no clean evidence base.")

    per_setup = defaultdict(int)
    for t in core:
        per_setup[str(t.get("setup_type") or "?")] += 1
    print(f"\n[5] SANITIZED CLOSED TRADES PER SETUP ({len(per_setup)} setups):")
    for k, v in sorted(per_setup.items(), key=lambda x: -x[1])[:20]:
        tag = " ✅≥100" if v >= 100 else (" 🟡≥50" if v >= 50 else "")
        print(f"     {v:5d}  {k}{tag}")
    ready = sorted(k for k, v in per_setup.items() if v >= 100)
    print(f"     → meta-labeling READY after sanitization: {ready or 'NONE'}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filter_version": FILTER_VERSION,
        "raw_closed": len(closed),
        "core_count": len(core),
        "scored_count": len(scored),
        "core_ids": [t.get("id") for t in core if t.get("id")],
        "scored_ids": [t.get("id") for t in scored if t.get("id")],
    }
    Path(OUT_PATH).write_text(json.dumps(payload))
    print(f"\n[6] wrote sanitized id list → {OUT_PATH} "
          f"(core={len(core)}, scored={len(scored)})")

    print("\n" + "=" * 78)
    print(f"probe complete {datetime.now(timezone.utc).isoformat()[:19]}Z — no DB writes")


if __name__ == "__main__":
    main()
