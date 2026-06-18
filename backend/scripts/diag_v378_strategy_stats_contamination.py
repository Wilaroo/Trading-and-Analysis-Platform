#!/usr/bin/env python3
"""
v378 — STRATEGY_STATS CONTAMINATION DIAG (Issue 3, READ-ONLY, nothing written).

smart_filter SKIPs a setup when its `strategy_stats.win_rate < 0.35` (REDUCE < 0.45).
That win_rate is recomputed by pnl_compute.recompute_strategy_stats_for_setup from
`alert_outcomes` over the ENTIRE history (no recency window). This diag proves whether
stale/garbage-era genuine rows are dragging good setups below the 0.35 veto line by
recomputing the SAME artifact-free math across recency windows (all / 90d / 60d / 30d)
and flagging FALSE VETOES (stored/all-time < 0.35 but recent >= 0.35).

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v378_strategy_stats_contamination.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v378_strategy_stats_contamination.py --setup stage_2_breakout
"""
import sys
from datetime import datetime, timezone

SKIP_WR = 0.35
REDUCE_WR = 0.45
MIN_SAMPLE = 5

try:
    from services.pnl_compute import (
        _base_setup, _classify_outcome, _is_reconciliation_artifact)
except Exception as e:  # pragma: no cover
    print(f"FATAL: run with PYTHONPATH=backend ({e})")
    sys.exit(1)


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


def _ep(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v < 1e12 else float(v) / 1000.0
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _iso(ep):
    return "?" if ep is None else datetime.fromtimestamp(ep, tz=timezone.utc).strftime("%Y-%m-%d")


def recompute(rows, since_ep=None, winsor=3.0):
    """Mirror recompute_strategy_stats_for_setup (genuine-only) + optional recency
    window + R winsorization (v336 clamp) so a -261R artifact can't poison win/EV."""
    trig = won = lost = 0
    r_all = []
    oldest = newest = None
    for d in rows:
        cep = _ep(d.get("closed_at"))
        if since_ep is not None and (cep is None or cep < since_ep):
            continue
        r = d.get("r_multiple")
        r = float(r) if isinstance(r, (int, float)) else None
        if r is not None and winsor:
            r = max(-winsor, min(winsor, r))
        pnl_v = d.get("net_pnl")
        if pnl_v is None:
            pnl_v = d.get("pnl")
        pnl_v = float(pnl_v) if isinstance(pnl_v, (int, float)) else 0.0
        cls = _classify_outcome(d.get("outcome"), r, pnl_v)
        if cls is None:
            continue
        trig += 1
        won += 1 if cls == "win" else 0
        lost += 1 if cls == "loss" else 0
        if r is not None:
            r_all.append(r)
        if cep is not None:
            oldest = cep if oldest is None else min(oldest, cep)
            newest = cep if newest is None else max(newest, cep)
    wr = (won / trig) if trig else 0.0
    ev = (sum(r_all) / len(r_all)) if len(r_all) >= 5 else 0.0
    return {"n": trig, "won": won, "lost": lost, "win_rate": wr, "ev": ev,
            "oldest": oldest, "newest": newest}


def genuine_rows_for(ao, base):
    rows = [
        d for d in ao.find(
            {}, {"_id": 1, "setup_type": 1, "outcome": 1, "r_multiple": 1,
                 "net_pnl": 1, "pnl": 1, "closed_at": 1, "genuine": 1,
                 "close_reason": 1, "r_risk_unreliable": 1})
        if _base_setup(d.get("setup_type")) == base
    ]
    return [
        d for d in rows
        if d.get("genuine", True) is not False
        and d.get("r_risk_unreliable") is not True
        and not _is_reconciliation_artifact(d.get("setup_type"), d.get("close_reason"))
    ]


def main():
    db = _load_db()
    one = _arg("--setup", None)
    now = datetime.now(timezone.utc).timestamp()
    W = {"90d": now - 90 * 86400, "60d": now - 60 * 86400, "30d": now - 30 * 86400}

    ss = {d.get("setup_type"): d for d in db.strategy_stats.find({}, {"_id": 0})}
    print(f"strategy_stats setups stored: {len(ss)}")

    # which setups would smart_filter SKIP/REDUCE on the STORED stats?
    targets = []
    for st, d in ss.items():
        wr = float(d.get("win_rate", 0) or 0)
        n = int(d.get("alerts_triggered", 0) or d.get("total_alerts", 0) or 0)
        if one:
            if _base_setup(st) == one or st == one:
                targets.append(st)
        elif n >= MIN_SAMPLE and wr < REDUCE_WR:
            targets.append(st)
    if one and not targets:
        targets = [one]

    print("\n" + "=" * 96)
    print(f"FALSE-VETO SCAN — stored win_rate vs artifact-free recompute by window "
          f"(SKIP<{SKIP_WR:.2f} / REDUCE<{REDUCE_WR:.2f}, min n {MIN_SAMPLE})")
    print("=" * 96)
    hdr = f"{'setup':<26}{'stored_wr':>10}{'all_wr/n':>14}{'90d_wr/n':>14}{'60d_wr/n':>14}{'30d_wr/n':>14}  verdict"
    print(hdr)
    print("-" * len(hdr))

    ao = db.alert_outcomes
    false_vetoes = []
    for st in sorted(set(targets)):
        base = _base_setup(st)
        rows = genuine_rows_for(ao, base)
        if not rows:
            print(f"{st:<26}{'(no genuine alert_outcomes rows)':>40}")
            continue
        allw = recompute(rows)
        w90, w60, w30 = (recompute(rows, W["90d"]), recompute(rows, W["60d"]),
                         recompute(rows, W["30d"]))
        stored_wr = float(ss.get(st, {}).get("win_rate", 0) or 0)

        def cell(w):
            return f"{w['win_rate']*100:4.0f}%/{w['n']:<4}"
        # false veto = stored or all-time would SKIP, but a recent window clears SKIP
        worst = min(stored_wr, allw["win_rate"])
        best_recent = max(w90["win_rate"] if w90["n"] >= MIN_SAMPLE else 0,
                          w60["win_rate"] if w60["n"] >= MIN_SAMPLE else 0,
                          w30["win_rate"] if w30["n"] >= MIN_SAMPLE else 0)
        verdict = ""
        if worst < SKIP_WR <= best_recent:
            verdict = "★ FALSE VETO (recent clears SKIP)"
            false_vetoes.append(st)
        elif worst < REDUCE_WR <= best_recent:
            verdict = "~ recent clears REDUCE"
        elif allw["win_rate"] < SKIP_WR:
            verdict = "genuinely weak (all windows)"
        print(f"{st:<26}{stored_wr*100:8.0f}% {cell(allw):>13}{cell(w90):>14}"
              f"{cell(w60):>14}{cell(w30):>14}  {verdict}")
        if one:
            print(f"    data span: {_iso(allw['oldest'])} → {_iso(allw['newest'])}  "
                  f"all-time EV {allw['ev']:+.3f}R · 60d EV {w60['ev']:+.3f}R · "
                  f"30d EV {w30['ev']:+.3f}R")

    print("\n" + "=" * 96)
    if false_vetoes:
        print(f"★ {len(false_vetoes)} FALSE VETO setup(s) — stale data drags them below the "
              f"0.35 SKIP line, recent window proves them tradeable:")
        for s in false_vetoes:
            print(f"    - {s}")
        print("\n  => Issue 3 fix candidate: recompute strategy_stats over a RECENT window")
        print("     (e.g. last 60-90d genuine, winsorized R) instead of all-time.")
    else:
        print("No false vetoes detected in scanned setups (stats not contaminated, or")
        print("the weak setups are genuinely weak across recent windows too).")
    print("=" * 96)


if __name__ == "__main__":
    main()
