"""
v19.31.4 (2026-05-04) — regression pin for the Diagnostics Data Quality
Pack: pipeline-funnel `combined_recommendation` predicate fix +
per-module `vote_breakdown` in the scorecard.

The bugs:
  1. `build_pipeline_funnel` matched `combined_recommendation in
     ('BUY', 'STRONG_BUY')` but the actual values written by
     `shadow_tracker.ShadowDecision` are `'proceed'` / `'pass'` /
     `'reduce_size'` (line 46). Result: `ai_passed` was always 0,
     making the entire funnel useless.
  2. `build_module_scorecard` only surfaced aggregate accuracy_rate
     per module. Operator needed per-module vote breakdown
     (long_votes / short_votes / disagreement_rate vs final consensus)
     to spot directional bias.

These tests pin the exact predicate behavior + the new vote_breakdown
shape on a fake Mongo.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake Mongo ─────────────────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = docs or []

    def _matches(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            if k == "$and":
                if not all(self._matches(doc, sub) for sub in v):
                    return False
                continue
            actual = doc
            for part in k.split("."):
                if isinstance(actual, dict):
                    actual = actual.get(part)
                else:
                    actual = None
                    break
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$gt" in v and not (actual is not None and actual > v["$gt"]):
                    return False
                if "$in" in v and actual not in v["$in"]:
                    return False
                if "$nin" in v and actual in v["$nin"]:
                    return False
            else:
                if actual != v:
                    return False
        return True

    def count_documents(self, query):
        return sum(1 for d in self.docs if self._matches(d, query))

    def find(self, query=None, projection=None):
        if query is None:
            return list(self.docs)
        return [d for d in self.docs if self._matches(d, query)]

    def aggregate(self, pipeline):
        # Minimal aggregation: $match → $sort → $group with $first
        rows = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                rows = [r for r in rows if self._matches(r, stage["$match"])]
            elif "$sort" in stage:
                # only need single-key sort
                k, direction = next(iter(stage["$sort"].items()))
                rows.sort(key=lambda r: r.get(k, ""), reverse=direction == -1)
            elif "$group" in stage:
                spec = stage["$group"]
                groups: Dict[Any, Dict] = {}
                key_expr = spec["_id"]
                for r in rows:
                    key = r.get(key_expr.lstrip("$")) if isinstance(key_expr, str) else None
                    if key not in groups:
                        new = {"_id": key}
                        for fname, fop in spec.items():
                            if fname == "_id":
                                continue
                            if "$first" in fop:
                                new[fname] = r.get(fop["$first"].lstrip("$"))
                        groups[key] = new
                rows = list(groups.values())
        return iter(rows)


class _FakeDB:
    def __init__(self):
        self.shadow_decisions = _FakeColl()
        self.bot_trades = _FakeColl()
        self.shadow_module_performance = _FakeColl()
        self.shadow_module_weights = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


def _shadow(combined_rec, was_executed=False, debate_winner=None,
            risk_rec=None, ts_dir=None, hours_ago=1):
    """Helper to build a shadow_decisions row."""
    trigger_time = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "id": f"sd_{combined_rec}_{hours_ago}",
        "trigger_time": trigger_time,
        "combined_recommendation": combined_rec,
        "was_executed": was_executed,
        "debate_result": {"winner": debate_winner} if debate_winner else {},
        "risk_assessment": {"recommendation": risk_rec} if risk_rec else {},
        "timeseries_forecast": {"direction": ts_dir} if ts_dir else {},
        "institutional_context": {},
    }


# ─── build_pipeline_funnel tests ─────────────────────────────────────


def test_funnel_ai_passed_now_matches_proceed_not_BUY():
    """The exact bug: predicate now matches 'proceed' (the real value),
    not 'BUY' (which never appears)."""
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", was_executed=True),
        _shadow("proceed", was_executed=True),
        _shadow("pass"),
        _shadow("reduce_size"),
    ]
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["emitted"] == 4
    assert stages["ai_passed"] == 2  # only 2 are "proceed"
    # Pre-fix this returned 0


def test_funnel_legacy_uppercase_proceed_also_matches():
    """Defensive: PROCEED / Proceed casing also counts."""
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("PROCEED"),
        _shadow("Proceed"),
        _shadow("proceed"),
    ]
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["ai_passed"] == 3


def test_funnel_old_BUY_value_no_longer_inflates_ai_passed():
    """Pre-fix the old predicate matched 'BUY' (which the system never
    writes). Confirm a row with that legacy junk value isn't counted."""
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("BUY"),  # garbage value, should NOT count
        _shadow("STRONG_BUY"),  # garbage value, should NOT count
        _shadow("proceed"),  # real value
    ]
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["ai_passed"] == 1


def test_funnel_risk_passed_drops_rejected_rows():
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", risk_rec="proceed"),
        _shadow("proceed", risk_rec="reject"),
        _shadow("proceed", risk_rec="approve"),
        _shadow("proceed", risk_rec="REJECT"),
        _shadow("proceed", risk_rec="block"),
    ]
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["ai_passed"] == 5
    # 3 are NOT rejected/blocked: 'proceed', 'approve', and the row
    # with no risk_rec at all… wait — all 5 here have risk_rec set.
    # Of these: 'proceed', 'approve' pass; 'reject', 'REJECT', 'block' fail.
    assert stages["risk_passed"] == 2


def test_funnel_fired_uses_max_of_shadow_and_trades():
    """When shadow.was_executed and bot_trades disagree, take the max
    so the funnel stays monotonic (fired >= risk_passed)."""
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.shadow_decisions.docs = [
        _shadow("proceed", was_executed=True),
        _shadow("proceed", was_executed=True),
    ]
    db.bot_trades.docs = [
        {"id": "t1", "executed_at": cutoff, "status": "open"},
        {"id": "t2", "executed_at": cutoff, "status": "open"},
        {"id": "t3", "executed_at": cutoff, "status": "open"},  # 3rd trade with no shadow
        {"id": "t4", "executed_at": cutoff, "status": "open"},  # 4th
    ]
    res = build_pipeline_funnel(db, days=1)
    fired_stage = next(s for s in res["stages"] if s["stage"] == "fired")
    assert fired_stage["count"] == 4  # max(2, 4)
    assert fired_stage["fired_via_shadow"] == 2
    assert fired_stage["fired_via_trades"] == 4
    # The drift > max(2, 10% of 4 = 0.4 → 2) check: |2 - 4| == 2,
    # > max(2, ...) is False (not strictly greater), so no warning.
    # Confirm the stage at least has the field.
    assert "drift_warning" in fired_stage


def test_funnel_winners_excludes_losers_and_open():
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.bot_trades.docs = [
        {"id": "w1", "executed_at": cutoff, "status": "closed", "realized_pnl": 100},
        {"id": "w2", "executed_at": cutoff, "status": "closed", "pnl": 50},
        {"id": "l1", "executed_at": cutoff, "status": "closed", "realized_pnl": -50},
        {"id": "open1", "executed_at": cutoff, "status": "open", "pnl": 999},
    ]
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["winners"] == 2


def test_funnel_monotonicity_typical_pipeline():
    """Realistic scenario: 100 emitted → 30 proceed → 25 risk-passed →
    20 fired → 12 winners. Confirm conversion percentages are correct."""
    from services.decision_trail import build_pipeline_funnel
    db = _FakeDB()
    # 100 emitted: 30 proceed, 70 pass
    db.shadow_decisions.docs = (
        [_shadow("proceed", was_executed=(i < 20), risk_rec="proceed" if i < 25 else "reject", hours_ago=1)
         for i in range(30)]
        + [_shadow("pass", hours_ago=1) for _ in range(70)]
    )
    # 12 winners
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.bot_trades.docs = (
        [{"id": f"w{i}", "executed_at": cutoff, "status": "closed", "pnl": 50}
         for i in range(12)]
        + [{"id": f"l{i}", "executed_at": cutoff, "status": "closed", "pnl": -10}
           for i in range(8)]
    )
    res = build_pipeline_funnel(db, days=1)
    stages = {s["stage"]: s["count"] for s in res["stages"]}
    assert stages["emitted"] == 100
    assert stages["ai_passed"] == 30
    assert stages["risk_passed"] == 25
    assert stages["fired"] == 20
    assert stages["winners"] == 12

    # Conversion percentages
    convs = {s["stage"]: s.get("conversion_pct") for s in res["stages"]}
    assert convs["ai_passed"] == 30.0
    assert convs["risk_passed"] == round(25 / 30 * 100, 1)
    assert convs["fired"] == round(20 / 25 * 100, 1)
    assert convs["winners"] == 60.0


# ─── _aggregate_vote_breakdown tests ─────────────────────────────────


def test_vote_breakdown_debate_long_short_hold():
    from services.decision_trail import _aggregate_vote_breakdown
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", debate_winner="bull"),
        _shadow("proceed", debate_winner="bull"),
        _shadow("pass", debate_winner="bear"),
        _shadow("pass", debate_winner="tie"),
    ]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    bd = _aggregate_vote_breakdown(db, cutoff)
    assert bd["debate_agents"]["long_votes"] == 2
    assert bd["debate_agents"]["short_votes"] == 1
    assert bd["debate_agents"]["hold_votes"] == 1
    assert bd["debate_agents"]["total_votes"] == 4


def test_vote_breakdown_debate_disagreement_rate():
    """Module says bull but final says pass → disagreement."""
    from services.decision_trail import _aggregate_vote_breakdown
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", debate_winner="bull"),  # agree
        _shadow("pass", debate_winner="bull"),     # disagree
        _shadow("pass", debate_winner="bear"),     # agree
        _shadow("proceed", debate_winner="bear"),  # disagree
    ]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    bd = _aggregate_vote_breakdown(db, cutoff)
    # 2 of 4 agreed, 2 disagreed → 50%
    assert bd["debate_agents"]["agreed_with_final"] == 2
    assert bd["debate_agents"]["disagreement_rate"] == 50.0


def test_vote_breakdown_risk_manager_tally():
    from services.decision_trail import _aggregate_vote_breakdown
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", risk_rec="proceed"),
        _shadow("proceed", risk_rec="approve"),
        _shadow("pass", risk_rec="reject"),
        _shadow("proceed", risk_rec="reduce"),
    ]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    bd = _aggregate_vote_breakdown(db, cutoff)
    rm = bd["risk_manager"]
    assert rm["proceed_votes"] == 2
    assert rm["reject_votes"] == 1
    assert rm["reduce_votes"] == 1
    assert rm["total_votes"] == 4


def test_vote_breakdown_timeseries_directions():
    from services.decision_trail import _aggregate_vote_breakdown
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", ts_dir="up"),
        _shadow("proceed", ts_dir="bullish"),
        _shadow("pass", ts_dir="down"),
        _shadow("pass", ts_dir="neutral"),
    ]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    bd = _aggregate_vote_breakdown(db, cutoff)
    ts = bd["timeseries"]
    assert ts["up_votes"] == 2
    assert ts["down_votes"] == 1
    assert ts["neutral_votes"] == 1


def test_vote_breakdown_silent_module_does_not_count():
    """A row with no debate_result.winner shouldn't add to debate
    totals. But other modules in the same row still count if present."""
    from services.decision_trail import _aggregate_vote_breakdown
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", debate_winner="bull", risk_rec="proceed"),
        _shadow("proceed", risk_rec="proceed"),  # debate silent
        _shadow("proceed", debate_winner="bull"),  # risk silent
    ]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    bd = _aggregate_vote_breakdown(db, cutoff)
    assert bd["debate_agents"]["total_votes"] == 2
    assert bd["risk_manager"]["total_votes"] == 2


def test_module_scorecard_now_includes_vote_breakdown_field():
    """The full scorecard endpoint output must carry vote_breakdown."""
    from services.decision_trail import build_module_scorecard
    db = _FakeDB()
    db.shadow_decisions.docs = [
        _shadow("proceed", debate_winner="bull", risk_rec="proceed"),
    ]
    res = build_module_scorecard(db, days=7)
    assert "vote_breakdown" in res
    assert "debate_agents" in res["vote_breakdown"]
    assert res["vote_breakdown"]["debate_agents"]["long_votes"] == 1


# ─── Source-level pin ───────────────────────────────────────────────


def test_source_pin_funnel_uses_proceed_not_BUY():
    """Catch a future regression that re-introduces the BUY/STRONG_BUY
    matcher."""
    import inspect
    from services.decision_trail import build_pipeline_funnel
    src = inspect.getsource(build_pipeline_funnel)
    assert "proceed" in src.lower()
    # Critical: the OLD bad values must NOT be the sole match anymore.
    # If they appear at all (defensive comments), they must be next to
    # 'proceed' in the same predicate.
    if '"BUY"' in src or "'BUY'" in src:
        # ok if it's defensive — but proceed must dominate
        assert src.lower().count("proceed") >= src.upper().count("BUY")
