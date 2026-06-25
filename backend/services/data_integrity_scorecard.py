"""Unified Data-Integrity Scorecard (READ-ONLY) — workstream 2B.

Rolls the existing diagnostics into ONE pass/warn/fail view that answers
"is every feed flowing and every calculation honest?" before we trust the
cockpit (and the bot) with real money. Composes, fail-soft:

  • phase0_edge_coverage  — Entry-Edge archetype-cell completeness + darkest
                            Phase-0 field (services.entry_edge_coverage)
  • tqs_pillar_coverage   — per-pillar % defaulted = live feed darkness
                            (Tape / Fundamental / EV / Execution …)
  • tqs_calc_honesty      — does the grade actually rank realized-R, or is it
                            inverted/compressed (services.tqs_integrity)
  • ingest_freshness      — newest ib_historical_data write age (feed liveness)

Each probe is wrapped so a failure degrades to status='unknown' instead of
crashing the scorecard. Top-line verdict = worst real status (FAIL > WARN >
PASS). Drives the V6 Data & Connections / Data Confidence / Autopilot Go-No-Go
pages. Plan: memory/DATA_INTEGRITY_PLAN_2026-06.md
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_RANK = {"fail": 3, "warn": 2, "pass": 1, "info": 0, "unknown": 0}
_HEALTH_STATUS = {"green": "pass", "yellow": "warn", "red": "fail"}


def _band(value, pass_at, warn_at, higher_is_better=True):
    """Map a numeric value → pass/warn/fail against two thresholds."""
    if value is None:
        return "unknown"
    if higher_is_better:
        return "pass" if value >= pass_at else ("warn" if value >= warn_at else "fail")
    return "pass" if value <= pass_at else ("warn" if value <= warn_at else "fail")


def _check(name, status, value, detail=""):
    return {"name": name, "status": status, "value": value, "detail": detail}


def _phase0_edge_coverage(db, days):
    from services.entry_edge_coverage import generate_report
    rep = generate_report(db, days=days)
    cell = rep.get("archetype_cell") or {}
    n = rep.get("n", 0)
    complete = cell.get("complete_pct")
    # darkest Phase-0 field
    p0 = [r for r in rep.get("fields", []) if r.get("kind") == "phase0_new"]
    darkest = min(p0, key=lambda x: x["coverage_pct"]) if p0 else None
    subs = [
        _check("archetype_cell_complete",
               "info" if n == 0 else _band(complete, 60, 30),
               f"{complete}%" if complete is not None else "—",
               f"all {len(cell.get('dims', []))} dims present on closed trades "
               f"(n={n})"),
        _check("darkest_phase0_field",
               "info" if (n == 0 or not darkest) else _band(darkest["coverage_pct"], 70, 40),
               f"{darkest['field']} @ {darkest['coverage_pct']}%" if darkest else "—",
               "the Phase-0 dimension the Edge Score is most blind to"),
    ]
    return {"group": "phase0_edge_coverage", "headline": rep.get("headline"),
            "n": n, "checks": subs}


def _tqs_pillar_coverage(db, days):
    from services.tqs_integrity import _pillar_coverage
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pc = _pillar_coverage(db, cutoff)
    subs = []
    for p in pc.get("pillars", []):
        dp = p.get("defaulted_pct")
        # high defaulted% == the pillar's feed is dark (fed the neutral 50)
        subs.append(_check(
            f"pillar:{p['pillar']}",
            "info" if dp is None else _band(dp, 30, 60, higher_is_better=False),
            f"{dp}% defaulted" if dp is not None else "—",
            f"n={p.get('n')} mean={p.get('mean')}"))
    if not subs:
        subs = [_check("pillar_coverage", "info", "no data",
                       pc.get("note") or "gate has not logged pillar_scores yet")]
    return {"group": "tqs_pillar_coverage",
            "evaluations": pc.get("evaluations_with_pillars", 0), "checks": subs}


def _tqs_calc_honesty(db, days):
    from services.tqs_integrity import _grade_separation, _score_discrimination
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    gs = _grade_separation(db, cutoff)
    sd = _score_discrimination(db, cutoff)
    gverdict = gs.get("verdict")
    sverdict = sd.get("verdict")
    _g_insuff = (not gverdict) or ("insuff" in str(gverdict))
    _s_insuff = (not sverdict) or ("insuff" in str(sverdict))
    subs = [
        _check("grade_ranks_realized_r",
               "info" if _g_insuff else
               ("fail" if gverdict == "weak_or_inverted" else "pass"),
               gverdict or "—",
               "does the trade grade monotonically rank realized R"),
        _check("score_spread",
               "info" if _s_insuff else
               ("warn" if sverdict == "compressed" else "pass"),
               f"SD {sd.get('sd')}" if sd.get("sd") is not None else (sverdict or "—"),
               "quality_score must vary, not collapse to one band"),
    ]
    return {"group": "tqs_calc_honesty", "checks": subs}


def _feed_liveness(db):
    """Canonical live-feed health (pusher push-age + live-bar freshness + IB link),
    reused from system_health_service so the scorecard agrees with /api/system/health.
    NOTE: deliberately NOT keyed on `ib_historical_data` — that's the deep BACKFILL
    store (legitimately cold off-session); the LIVE path is pusher → live_bar_cache."""
    from services.system_health_service import build_health
    h = build_health(db)
    subs = {s.get("name"): s for s in h.get("subsystems", [])}
    checks = []
    for name in ("pusher_rpc", "live_bar_cache", "ib_gateway"):
        s = subs.get(name)
        if not s:
            checks.append(_check(name, "unknown", "—", "subsystem not reported"))
            continue
        checks.append(_check(
            name, _HEALTH_STATUS.get(s.get("status"), "unknown"),
            s.get("status", "—"), (s.get("detail") or "")[:120]))
    return {"group": "feed_liveness", "overall": h.get("overall"), "checks": checks}


def build_scorecard(db, days_edge: int = 45, days_tqs: int = 30) -> dict:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "groups": [], "verdict": "UNKNOWN", "score": "0/0",
    }
    if db is None:
        out["error"] = "db not initialised"
        return out

    probes = [
        ("phase0_edge_coverage", lambda: _phase0_edge_coverage(db, days_edge)),
        ("tqs_pillar_coverage", lambda: _tqs_pillar_coverage(db, days_tqs)),
        ("tqs_calc_honesty", lambda: _tqs_calc_honesty(db, days_tqs)),
        ("feed_liveness", lambda: _feed_liveness(db)),
    ]
    for name, fn in probes:
        try:
            out["groups"].append(fn())
        except Exception as e:
            logger.warning("data-scorecard probe %s failed: %s", name, e)
            out["groups"].append({"group": name, "checks": [
                _check(name, "unknown", "probe error", str(e)[:120])]})

    all_checks = [c for g in out["groups"] for c in g.get("checks", [])]
    worst = max((_RANK.get(c["status"], 0) for c in all_checks), default=0)
    out["verdict"] = {3: "FAIL", 2: "WARN", 1: "PASS", 0: "UNKNOWN"}[worst]
    scored = [c for c in all_checks if c["status"] in ("pass", "warn", "fail")]
    n_pass = sum(1 for c in scored if c["status"] == "pass")
    out["score"] = f"{n_pass}/{len(scored)}" if scored else "0/0"
    out["counts"] = {
        "pass": sum(1 for c in all_checks if c["status"] == "pass"),
        "warn": sum(1 for c in all_checks if c["status"] == "warn"),
        "fail": sum(1 for c in all_checks if c["status"] == "fail"),
        "unknown": sum(1 for c in all_checks if c["status"] in ("unknown", "info")),
    }
    return out
