"""
v19.31.14 (2026-05-04) — Tests for boot-reconcile status pill endpoint
+ funnel drift_warning surfacing + vote_breakdown panel wiring.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if query is None or all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


class _FakeDB:
    def __init__(self):
        self.bot_state = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── boot-reconcile-status endpoint ────────────────────────────────


@pytest.mark.asyncio
async def test_boot_reconcile_status_no_doc_returns_ran_false():
    from routers.trading_bot import get_boot_reconcile_status
    db = _FakeDB()
    with patch("database.get_database", return_value=db):
        res = await get_boot_reconcile_status(pill_visible_seconds=600)
    assert res["ran"] is False
    assert res["show_pill"] is False
    assert res["reconciled_count"] == 0


@pytest.mark.asyncio
async def test_boot_reconcile_status_recent_run_show_pill_true():
    from routers.trading_bot import get_boot_reconcile_status
    db = _FakeDB()
    ran_iso = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    db.bot_state.docs = [{
        "_id": "last_auto_reconcile_at_boot",
        "ran_at": ran_iso,
        "reconciled_count": 5,
        "skipped_count": 1,
        "errors_count": 0,
        "symbols": ["AAPL", "MSFT", "TSLA", "NVDA", "META"],
    }]
    with patch("database.get_database", return_value=db):
        res = await get_boot_reconcile_status(pill_visible_seconds=600)
    assert res["ran"] is True
    assert res["show_pill"] is True
    assert res["reconciled_count"] == 5
    assert res["skipped_count"] == 1
    assert 100 < res["age_seconds"] < 140
    assert "AAPL" in res["symbols"]


@pytest.mark.asyncio
async def test_boot_reconcile_status_stale_run_hides_pill():
    """Run ≥ pill_visible_seconds ago → show_pill False."""
    from routers.trading_bot import get_boot_reconcile_status
    db = _FakeDB()
    ran_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.bot_state.docs = [{
        "_id": "last_auto_reconcile_at_boot",
        "ran_at": ran_iso,
        "reconciled_count": 3,
        "skipped_count": 0,
        "errors_count": 0,
        "symbols": [],
    }]
    with patch("database.get_database", return_value=db):
        res = await get_boot_reconcile_status(pill_visible_seconds=600)
    assert res["ran"] is True
    assert res["show_pill"] is False
    assert res["age_seconds"] > 600


@pytest.mark.asyncio
async def test_boot_reconcile_status_zero_claims_still_returns_ran_true():
    """No-op boot reconcile → ran=True, claims=0, but pill should
    still show briefly so operator knows it ran."""
    from routers.trading_bot import get_boot_reconcile_status
    db = _FakeDB()
    ran_iso = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    db.bot_state.docs = [{
        "_id": "last_auto_reconcile_at_boot",
        "ran_at": ran_iso,
        "reconciled_count": 0,
        "skipped_count": 0,
        "errors_count": 0,
        "symbols": [],
    }]
    with patch("database.get_database", return_value=db):
        res = await get_boot_reconcile_status(pill_visible_seconds=600)
    assert res["ran"] is True
    assert res["show_pill"] is True
    assert res["reconciled_count"] == 0


@pytest.mark.asyncio
async def test_boot_reconcile_status_db_unavailable_safe_default():
    """When db.get_database returns None, must not raise."""
    from routers.trading_bot import get_boot_reconcile_status
    with patch("database.get_database", return_value=None):
        res = await get_boot_reconcile_status(pill_visible_seconds=600)
    assert res["ran"] is False
    assert res["show_pill"] is False


# ─── Funnel drift_warning structural test ──────────────────────────


def test_funnel_endpoint_exposes_drift_warning_field():
    """The 'fired' stage in the funnel must include `fired_via_shadow`,
    `fired_via_trades`, and `drift_warning` (None when in tolerance,
    str when out)."""
    src = (BACKEND_DIR / "services" / "decision_trail.py").read_text()
    assert "fired_via_shadow" in src
    assert "fired_via_trades" in src
    assert "drift_warning" in src


def test_funnel_ui_renders_drift_warning():
    """Frontend must surface the drift_warning chip."""
    f = Path("/app/frontend/src/pages/DiagnosticsPage.jsx").read_text()
    assert "funnel-drift-warning" in f
    assert "Shadow drift" in f
    assert "fired_via_shadow" in f
    assert "fired_via_trades" in f


# ─── Vote-breakdown panel wiring ───────────────────────────────────


def test_vote_breakdown_aggregator_exists_in_backend():
    src = (BACKEND_DIR / "services" / "decision_trail.py").read_text()
    assert "_aggregate_vote_breakdown" in src
    assert "long_votes" in src
    assert "disagreement_rate" in src


def test_vote_breakdown_panel_wired_in_diagnostics_page():
    """The Module Scorecard tab must render `<ModuleVoteBreakdownPanel>`
    when the backend payload includes vote_breakdown."""
    f = Path("/app/frontend/src/pages/DiagnosticsPage.jsx").read_text()
    assert "ModuleVoteBreakdownPanel" in f
    assert "vote-breakdown-panel" in f
    assert "vote_breakdown" in f


# ─── Boot-reconcile pill component wiring ──────────────────────────


def test_boot_reconcile_pill_component_exists():
    p = Path("/app/frontend/src/components/sentcom/v5/BootReconcilePill.jsx")
    assert p.exists()
    content = p.read_text()
    assert "boot-reconcile-pill" in content
    assert "boot-reconcile-status" in content


def test_boot_reconcile_pill_wired_in_sentcom_v5_view():
    f = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text()
    assert "BootReconcilePill" in f
    assert "import BootReconcilePill" in f
