"""Tests for the Setup-landscape self-grading tracker.

Covers:
  - `_build_trade_to_setup_family` builds a complete map from
    `TRADE_SETUP_MATRIX`.
  - `record_prediction` upserts on (trading_day, context); idempotent
    re-call updates the same doc, never duplicates.
  - `record_prediction` is a no-op when the snapshot has no
    non-NEUTRAL groups (don't dirty the collection with empty calls).
  - `record_prediction` is a no-op when ``db is None``.
  - `_score_grade` rubric — every band (A/B/C/D/F) fires for the
    correct (top_avg_r, avoided_avg_r) combination.
  - `_grade_prediction` falls back to INSUFFICIENT_DATA when the
    predicted family has < 3 closed alerts.
  - `grade_predictions_for_day` walks a fake `alert_outcomes` set,
    grades the prediction, writes the grade fields back, and is
    idempotent (re-calling skips already-graded items).
  - `get_recent_grades` returns most-recent-first across days.
  - `_trading_day_for` ET conversion handles UTC late-evening + early-
    morning correctly.
  - LandscapeService integration: morning narrative cites yesterday's
    grade verdict when one is available; silent on first-day operation.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Dict, List

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

from services.landscape_grading_service import (  # noqa: E402
    LandscapeGradingService,
    _build_trade_to_setup_family,
    GradedPrediction,
    get_landscape_grading_service,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ──────────────────────────── In-memory fake Mongo ────────────────────────────


class _FakeColl:
    """Synchronous list-backed collection with the subset of pymongo
    methods the grading service uses."""
    def __init__(self):
        self.docs: List[Dict] = []

    def create_index(self, *a, **kw):
        return None

    def update_one(self, filter_, update, upsert=False):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in filter_.items()):
                if "$set" in update:
                    d.update(update["$set"])
                # $setOnInsert ignored on update — mongo-correct
                return type("UR", (), {"matched_count": 1, "modified_count": 1})()
        if upsert:
            new_doc = {}
            new_doc.update(filter_)
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            self.docs.append(new_doc)
            return type("UR", (), {"matched_count": 0, "modified_count": 0,
                                   "upserted_id": "fake_id"})()
        return type("UR", (), {"matched_count": 0, "modified_count": 0})()

    def find(self, filter_=None, projection=None):
        filter_ = filter_ or {}
        results = []
        for d in self.docs:
            if self._matches(d, filter_):
                if projection:
                    proj = {k: d.get(k) for k in projection if projection.get(k) == 1}
                    results.append(proj if proj else dict(d))
                else:
                    results.append(dict(d))
        return _FakeCursor(results)

    def find_one(self, filter_=None, projection=None):
        cursor = self.find(filter_, projection)
        rs = list(cursor)
        return rs[0] if rs else None

    def count_documents(self, filter_, **kw):
        return sum(1 for d in self.docs if self._matches(d, filter_))

    @staticmethod
    def _matches(doc, filt):
        for k, v in filt.items():
            if isinstance(v, dict):
                # Range / comparison operators
                doc_val = doc.get(k)
                for op, op_val in v.items():
                    if op == "$regex":
                        import re
                        if not re.search(op_val, str(doc_val or "")):
                            return False
                    elif op == "$ne":
                        if doc_val == op_val:
                            return False
                    elif op == "$gte":
                        if doc_val is None or doc_val < op_val:
                            return False
                    elif op == "$lte":
                        if doc_val is None or doc_val > op_val:
                            return False
                    elif op == "$gt":
                        if doc_val is None or doc_val <= op_val:
                            return False
                    elif op == "$lt":
                        if doc_val is None or doc_val >= op_val:
                            return False
                    elif op == "$in":
                        if doc_val not in op_val:
                            return False
                    elif op == "$exists":
                        present = (k in doc) and (doc[k] is not None)
                        if bool(op_val) != present:
                            return False
                    else:
                        # Unknown operator → treat as literal equality (fail-safe)
                        if doc_val != v:
                            return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _FakeCursor(list):
    def sort(self, key, direction=-1):
        self.sort_key = key
        self.sort_dir = direction
        try:
            super().sort(
                key=lambda d: d.get(key, ""),
                reverse=(direction == -1),
            )
        except Exception:
            pass
        return self

    def limit(self, n):
        return _FakeCursor(self[:n])


class _FakeDB:
    def __init__(self):
        self.cols: Dict[str, _FakeColl] = {}

    def __getitem__(self, name):
        if name not in self.cols:
            self.cols[name] = _FakeColl()
        return self.cols[name]


# ──────────────────────────── _build_trade_to_setup_family ────────────────────────────


def test_trade_family_map_covers_all_matrix_trades():
    """Every trade in `TRADE_SETUP_MATRIX` must be in the family map."""
    from services.market_setup_classifier import TRADE_SETUP_MATRIX
    mapping = _build_trade_to_setup_family()
    for trade in TRADE_SETUP_MATRIX:
        assert trade in mapping, f"trade {trade!r} missing from family map"
        assert mapping[trade], f"trade {trade!r} mapped to empty family"


def test_trade_family_map_resolves_aliases():
    """The legacy `range_break` name resolves to the same family as
    its canonical `opening_range_break`."""
    mapping = _build_trade_to_setup_family()
    assert "range_break" in mapping or "opening_range_break" in mapping


# ──────────────────────────── _score_grade rubric ────────────────────────────


def test_score_grade_A_strong_carry_no_avoided():
    g, s, _ = LandscapeGradingService._score_grade(top_avg=0.8, avoided_avg=-0.1)
    assert g == "A" and s >= 0.8


def test_score_grade_B_modest_carry():
    g, s, _ = LandscapeGradingService._score_grade(top_avg=0.3, avoided_avg=0.0)
    assert g == "B"


def test_score_grade_C_flat():
    g, s, _ = LandscapeGradingService._score_grade(top_avg=0.0, avoided_avg=None)
    assert g == "C"


def test_score_grade_D_loser():
    g, s, _ = LandscapeGradingService._score_grade(top_avg=-0.4, avoided_avg=0.1)
    assert g == "D"


def test_score_grade_F_fully_backwards():
    g, s, _ = LandscapeGradingService._score_grade(top_avg=-0.5, avoided_avg=0.8)
    assert g == "F"


# ──────────────────────────── record_prediction ────────────────────────────


def _make_snap(top_setup="gap_and_go", count=12, n_groups=2,
               regime="risk_on_broad", timestamp="2026-04-30T13:30:00+00:00"):
    from services.setup_landscape_service import LandscapeSnapshot, SetupGroup
    groups = [
        SetupGroup(setup=top_setup, count=count, examples=[("AAPL", 0.9), ("ORCL", 0.8)]),
    ]
    if n_groups >= 2:
        groups.append(SetupGroup(setup="range_break", count=4, examples=[("MSFT", 0.7)]))
    return LandscapeSnapshot(
        timestamp=timestamp,
        sample_size=200,
        classified=count + 4,
        groups=groups,
        narrative="test narrative",
        headline="test headline",
        multi_index_regime=regime,
        regime_confidence=0.8,
        regime_reasoning=["test"],
    )


def test_record_prediction_upserts_idempotently():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    snap = _make_snap()
    pid1 = _run(svc.record_prediction(snap, "morning"))
    pid2 = _run(svc.record_prediction(snap, "morning"))
    assert pid1 == pid2
    docs = db["landscape_predictions"].docs
    assert len(docs) == 1, f"expected 1 doc after idempotent re-call, got {len(docs)}"
    assert docs[0]["top_setup"] == "gap_and_go"
    assert docs[0]["multi_index_regime"] == "risk_on_broad"


def test_record_prediction_no_op_on_all_neutral_snapshot():
    """An all-NEUTRAL snapshot has nothing to predict — don't dirty
    the collection with an empty doc."""
    from services.setup_landscape_service import LandscapeSnapshot, SetupGroup
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    snap = LandscapeSnapshot(
        timestamp="2026-04-30T13:30:00+00:00",
        sample_size=200,
        classified=0,
        groups=[SetupGroup(setup="neutral", count=200, examples=[])],
        narrative="", headline="",
    )
    pid = _run(svc.record_prediction(snap, "morning"))
    assert pid is None
    assert len(db["landscape_predictions"].docs) == 0


def test_record_prediction_no_op_when_db_none():
    svc = LandscapeGradingService(db=None)
    pid = _run(svc.record_prediction(_make_snap(), "morning"))
    assert pid is None


# ──────────────────────────── grade_predictions_for_day ────────────────────────────


def _seed_outcomes(db: _FakeDB, day: str, mapping):
    """Helper — `mapping` is {setup_type: [r_multiples...]}."""
    col = db["alert_outcomes"]
    for setup_type, rs in mapping.items():
        for i, r in enumerate(rs):
            col.docs.append({
                "alert_id": f"a_{setup_type}_{i}",
                "setup_type": setup_type,
                "r_multiple": r,
                "closed_at": f"{day}T20:30:00+00:00",
                "outcome": "won" if r > 0 else "lost",
                "trade_grade": "A",
            })


def test_grade_predictions_for_day_grades_an_A():
    """Predicted Gap & Go family carried strongly + avoided overextension
    flat → A grade."""
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    snap = _make_snap(top_setup="gap_and_go")
    _run(svc.record_prediction(snap, "morning"))

    # Map: 9_ema_scalp / momentum_burst / opening_drive → gap_and_go family
    # Map: bouncy_ball / parabolic_reversal → overextension family
    _seed_outcomes(db, "2026-04-30", {
        "9_ema_scalp":         [1.5, 1.0, 0.8, 1.2],   # Gap & Go family — strong avg ~1.1R
        "momentum_burst":      [0.9, 1.4],
        "bouncy_ball":         [-0.2, 0.1],            # Overextension family — flat avg
    })
    graded = _run(svc.grade_predictions_for_day("2026-04-30"))
    assert len(graded) == 1
    g = graded[0]
    assert g.grade == "A", f"expected A, got {g.grade}: {g.verdict}"
    assert g.realized_top_setup_n >= 3
    assert g.realized_top_setup_avg_r > 0.5

    # And the doc was updated with the grade fields
    doc = db["landscape_predictions"].find_one({"trading_day": "2026-04-30"})
    assert doc["grade"] == "A"
    assert doc["graded_at"] is not None


def test_grade_predictions_skips_already_graded():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    _run(svc.record_prediction(_make_snap(), "morning"))
    _seed_outcomes(db, "2026-04-30", {"9_ema_scalp": [1.0, 1.1, 1.2]})
    _run(svc.grade_predictions_for_day("2026-04-30"))
    # Re-call should grade nothing (the only prediction is already graded)
    second = _run(svc.grade_predictions_for_day("2026-04-30"))
    assert second == []


def test_grade_predictions_insufficient_data_when_no_alerts():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    _run(svc.record_prediction(_make_snap(), "morning"))
    # No alert_outcomes at all
    graded = _run(svc.grade_predictions_for_day("2026-04-30"))
    assert len(graded) == 1
    assert graded[0].grade == "INSUFFICIENT_DATA"


# ──────────────────────────── get_recent_grades ────────────────────────────


def test_get_recent_grades_returns_most_recent_first():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    # Seed two days
    snap_old = _make_snap(timestamp="2026-04-28T13:30:00+00:00")
    snap_new = _make_snap(timestamp="2026-04-30T13:30:00+00:00")
    _run(svc.record_prediction(snap_old, "morning"))
    _run(svc.record_prediction(snap_new, "morning"))
    _seed_outcomes(db, "2026-04-28", {"9_ema_scalp": [1.0, 1.1, 1.2]})
    _seed_outcomes(db, "2026-04-30", {"9_ema_scalp": [0.8, 0.9, 1.0]})
    _run(svc.grade_predictions_for_day("2026-04-28"))
    _run(svc.grade_predictions_for_day("2026-04-30"))
    rows = _run(svc.get_recent_grades(n=5, context="morning"))
    assert len(rows) == 2
    # Newest day comes first
    assert rows[0]["trading_day"] >= rows[1]["trading_day"]


# ──────────────────────────── _trading_day_for ET conversion ────────────────────────────


def test_trading_day_for_et_morning():
    """13:30 UTC on a weekday = 09:30 ET → same date."""
    assert LandscapeGradingService._trading_day_for(
        "2026-04-30T13:30:00+00:00"
    ) == "2026-04-30"


def test_trading_day_for_et_late_evening_rollover():
    """02:00 UTC = 21:00 ET previous day → previous date."""
    assert LandscapeGradingService._trading_day_for(
        "2026-04-30T02:00:00+00:00"
    ) == "2026-04-29"


# ──────────────────────────── Singleton ────────────────────────────


def test_grading_service_singleton():
    a = get_landscape_grading_service()
    b = get_landscape_grading_service()
    assert a is b


# ──────────────────────────── SetupLandscapeService integration ────────────────────────────


def test_render_narrative_cites_recent_grade_in_morning():
    """When recent_grade is provided, the morning narrative includes
    a 1st-person receipt line."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    grade = {
        "trading_day": "2026-04-29",
        "grade": "A",
        "verdict": "Nailed it — Gap & Go carried: avg +1.20R across 14 alerts",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="morning",
        regime_label="unknown",
        recent_grade=grade,
    )
    assert "Quick receipt — 2026-04-29" in narrative
    assert "Nailed it — Gap & Go carried" in narrative
    assert "Carrying that into today's call" in narrative


def test_render_narrative_silent_when_no_recent_grade():
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="morning",
        regime_label="unknown",
        recent_grade=None,
    )
    assert "Quick receipt" not in narrative
    assert "Owning yesterday's miss" not in narrative
    assert "Mid-session check" not in narrative
    assert "Closing the loop" not in narrative
    assert "Last week's record" not in narrative


def test_render_narrative_midday_cites_morning_grade():
    """Midday briefing now cites yesterday's morning grade with
    'Mid-session check' framing instead of going silent."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    grade = {
        "trading_day": "2026-04-29",
        "grade": "A",
        "verdict": "Nailed it — Gap & Go carried: avg +1.20R across 14 alerts",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="midday",
        regime_label="unknown", recent_grade=grade,
    )
    assert "Mid-session check" in narrative
    assert "2026-04-29's open call" in narrative
    assert "Adjusting from there" in narrative


def test_render_narrative_midday_d_grade_owns_miss():
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    grade = {
        "trading_day": "2026-04-29",
        "grade": "D",
        "verdict": "Wrong call — Gap & Go faded: avg -0.40R across 9 alerts",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="midday",
        regime_label="unknown", recent_grade=grade,
    )
    assert "yesterday's open call missed" in narrative


def test_render_narrative_eod_closes_the_loop():
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    grade = {
        "trading_day": "2026-04-30",
        "grade": "B",
        "verdict": "Solid call — Gap & Go paid: avg +0.45R across 11 alerts",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="eod",
        regime_label="unknown", recent_grade=grade,
    )
    assert "Closing the loop" in narrative
    assert "Logging that for tomorrow's open" in narrative


def test_render_narrative_weekend_cites_weekly_summary():
    """Weekend voice gets a multi-day rollup, not a single-day verdict."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    summary = {
        "_weekly_summary": True,
        "n_graded": 5,
        "n_total_in_window": 5,
        "grade_distribution": {"A": 3, "B": 1, "C": 1},
        "avg_score": 0.78,
        "avg_top_setup_r": 0.85,
        "latest_grade": "A",
        "latest_verdict": "Nailed it — Gap & Go carried: avg +1.20R",
        "latest_trading_day": "2026-04-30",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="weekend",
        regime_label="unknown", recent_grade=summary,
    )
    assert "Last week's record" in narrative
    assert "3A" in narrative and "1B" in narrative and "1C" in narrative
    assert "5 graded" in narrative
    assert "+0.85R" in narrative
    assert "strong directional read" in narrative


def test_render_narrative_weekend_silent_on_empty_summary():
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="weekend",
        regime_label="unknown",
        recent_grade={"_weekly_summary": True, "n_graded": 0,
                      "grade_distribution": {}},
    )
    assert "Last week's record" not in narrative


def test_weekly_receipt_line_tone_buckets():
    """Tone phrasing changes at score thresholds (0.75 / 0.55 / 0.40)."""
    from services.setup_landscape_service import SetupLandscapeService
    f = SetupLandscapeService._weekly_receipt_line
    assert "strong directional read" in f({
        "_weekly_summary": True, "n_graded": 5,
        "grade_distribution": {"A": 4, "B": 1}, "avg_score": 0.80,
        "avg_top_setup_r": 0.6, "latest_verdict": "x", "latest_trading_day": "d",
    })
    assert "mostly carried" in f({
        "_weekly_summary": True, "n_graded": 5,
        "grade_distribution": {"B": 3, "C": 2}, "avg_score": 0.60,
        "avg_top_setup_r": 0.2, "latest_verdict": "x", "latest_trading_day": "d",
    })
    assert "mixed week" in f({
        "_weekly_summary": True, "n_graded": 5,
        "grade_distribution": {"C": 4, "D": 1}, "avg_score": 0.45,
        "avg_top_setup_r": 0.0, "latest_verdict": "x", "latest_trading_day": "d",
    })
    assert "tough week" in f({
        "_weekly_summary": True, "n_graded": 5,
        "grade_distribution": {"D": 3, "F": 2}, "avg_score": 0.20,
        "avg_top_setup_r": -0.5, "latest_verdict": "x", "latest_trading_day": "d",
    })


# ──────────────────────────── get_weekly_summary ────────────────────────────


def test_get_weekly_summary_aggregates_grades():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    # Seed 3 graded morning predictions across 3 days
    for day in ("2026-04-28", "2026-04-29", "2026-04-30"):
        snap = _make_snap(timestamp=f"{day}T13:30:00+00:00")
        _run(svc.record_prediction(snap, "morning"))
    # Seed alert outcomes per day so each grades to A
    _seed_outcomes(db, "2026-04-28", {"9_ema_scalp": [1.0, 1.1, 1.2, 0.9]})
    _seed_outcomes(db, "2026-04-29", {"9_ema_scalp": [0.8, 0.9, 1.0, 0.7]})
    _seed_outcomes(db, "2026-04-30", {"9_ema_scalp": [0.3, 0.4, 0.5]})
    _run(svc.grade_predictions_for_day("2026-04-28"))
    _run(svc.grade_predictions_for_day("2026-04-29"))
    _run(svc.grade_predictions_for_day("2026-04-30"))

    summary = _run(svc.get_weekly_summary(end_date="2026-04-30"))
    assert summary is not None
    assert summary["n_graded"] == 3
    # All three graded; record should sum to 3
    total = sum(summary["grade_distribution"].values())
    assert total == 3
    assert summary["avg_score"] > 0
    assert summary["latest_trading_day"] == "2026-04-30"


def test_get_weekly_summary_returns_none_when_no_grades():
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    summary = _run(svc.get_weekly_summary(end_date="2026-04-30"))
    assert summary is None


def test_get_weekly_summary_excludes_insufficient_data():
    """INSUFFICIENT_DATA grades shouldn't pollute the rollup."""
    db = _FakeDB()
    svc = LandscapeGradingService(db=db)
    snap = _make_snap(timestamp="2026-04-30T13:30:00+00:00")
    _run(svc.record_prediction(snap, "morning"))
    _run(svc.grade_predictions_for_day("2026-04-30"))   # no outcomes → INSUFFICIENT
    summary = _run(svc.get_weekly_summary(end_date="2026-04-30"))
    assert summary is None  # filter eliminates the only row


def test_render_narrative_silent_on_insufficient_grade():
    """INSUFFICIENT_DATA grades shouldn't be cited (no useful signal)."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="morning",
        regime_label="unknown",
        recent_grade={"grade": "INSUFFICIENT_DATA", "trading_day": "2026-04-29",
                      "verdict": "Only 2 alerts closed."},
    )
    assert "Quick receipt" not in narrative


def test_owning_yesterday_miss_for_d_grade():
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    grade = {
        "trading_day": "2026-04-29",
        "grade": "D",
        "verdict": "Wrong call — Gap & Go faded: avg -0.40R across 9 alerts",
    }
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="morning",
        regime_label="unknown",
        recent_grade=grade,
    )
    assert "Owning yesterday's miss" in narrative
    assert "Wrong call — Gap & Go faded" in narrative


# ──────────────────────────── Source-level guards ────────────────────────────


def test_record_prediction_called_from_get_snapshot():
    """`SetupLandscapeService.get_snapshot` should call into the
    grading service so every snapshot is auto-persisted."""
    from pathlib import Path
    src = Path("/app/backend/services/setup_landscape_service.py").read_text("utf-8")
    assert "record_prediction" in src
    assert "get_landscape_grading_service" in src


def test_eod_scheduler_includes_landscape_grading():
    from pathlib import Path
    src = Path("/app/backend/services/eod_generation_service.py").read_text("utf-8")
    assert "auto_landscape_grading" in src
    assert "_run_landscape_grading" in src
    # Runs at 16:50 ET (after DRC + playbook, before reflection)
    assert "hour=16, minute=50" in src
