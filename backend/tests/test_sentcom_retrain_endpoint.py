"""
Tests for POST /api/sentcom/retrain-model — the scorecard tile → targeted retrain
endpoint wired for ModelHealthScorecard.jsx.

Locks:
  - bar_size normalisation ("5min" / "5 mins" / "5m" all → "5 mins")
  - generic direction tiles enqueue a `training` job with full_universe=True
  - setup-specific tiles enqueue a `setup_training` job
  - unknown setup_type / bar_size raises HTTPException 400
  - job_queue_manager failures surface as success=false

Pure-function / coroutine-level tests with a mocked job_queue_manager —
no DB, no ML, no FastAPI TestClient (the local TestClient is broken by the
httpx-0.28 / starlette mismatch in this venv).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from routers.sentcom_chart import (
    _normalise_bar_size,
    retrain_model_from_scorecard,
    ScorecardRetrainRequest,
)


def _run(coro):
    return asyncio.run(coro)


# ─── _normalise_bar_size ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("5min", "5 mins"),
    ("5 mins", "5 mins"),
    ("5m", "5 mins"),
    ("5 min", "5 mins"),
    ("1min", "1 min"),
    ("1m", "1 min"),
    ("15MIN", "15 mins"),
    ("1hour", "1 hour"),
    ("1h", "1 hour"),
    ("1 hour", "1 hour"),
    ("daily", "1 day"),
    ("1day", "1 day"),
    ("1 day", "1 day"),
    ("1d", "1 day"),
])
def test_normalise_bar_size_aliases(raw, expected):
    assert _normalise_bar_size(raw) == expected


def test_normalise_bar_size_rejects_garbage():
    assert _normalise_bar_size("") is None
    assert _normalise_bar_size(None) is None
    assert _normalise_bar_size("not-a-timeframe") is None


# ─── Endpoint validation ────────────────────────────────────────────────────

def test_retrain_rejects_unknown_bar_size():
    req = ScorecardRetrainRequest(setup_type="__GENERIC__", bar_size="7 banana")
    with patch("services.ai_modules.ML_AVAILABLE", True):
        with pytest.raises(HTTPException) as exc:
            _run(retrain_model_from_scorecard(req))
    assert exc.value.status_code == 400
    assert "bar_size" in str(exc.value.detail).lower()


def test_retrain_rejects_unknown_setup_type():
    req = ScorecardRetrainRequest(setup_type="TOTALLY_FAKE_SETUP", bar_size="5 mins")
    with patch("services.ai_modules.ML_AVAILABLE", True):
        with pytest.raises(HTTPException) as exc:
            _run(retrain_model_from_scorecard(req))
    assert exc.value.status_code == 400
    detail = str(exc.value.detail).lower()
    assert "unknown" in detail or "setup_type" in detail


def test_retrain_blocks_when_ml_unavailable():
    """If xgboost is missing on this node, degrade gracefully — no exception."""
    req = ScorecardRetrainRequest(setup_type="__GENERIC__", bar_size="5 mins")
    with patch("services.ai_modules.ML_AVAILABLE", False):
        body = _run(retrain_model_from_scorecard(req))
    assert body["success"] is False
    assert body.get("ml_not_available") is True


# ─── Generic direction path ─────────────────────────────────────────────────

def test_retrain_generic_enqueues_training_job():
    """setup_type == __GENERIC__ must enqueue a full-universe `training` job
    for the specified bar_size, mirroring the full-universe training endpoint.
    """
    fake_mgr = AsyncMock()
    fake_mgr.create_job = AsyncMock(return_value={
        "success": True,
        "job": {"job_id": "abc-123"},
    })

    req = ScorecardRetrainRequest(setup_type="__GENERIC__", bar_size="5min")
    with patch("services.ai_modules.ML_AVAILABLE", True), \
         patch("services.job_queue_manager.job_queue_manager", fake_mgr):
        body = _run(retrain_model_from_scorecard(req))

    assert body["success"] is True
    assert body["job_id"] == "abc-123"
    assert body["kind"] == "generic_direction"
    assert body["bar_size"] == "5 mins"

    fake_mgr.create_job.assert_awaited_once()
    kwargs = fake_mgr.create_job.await_args.kwargs
    assert kwargs["job_type"] == "training"
    assert kwargs["params"]["full_universe"] is True
    assert kwargs["params"]["bar_size"] == "5 mins"


# ─── Setup-specific path ────────────────────────────────────────────────────

def test_retrain_setup_specific_enqueues_setup_training_job():
    """A valid (setup_type, bar_size) must enqueue a `setup_training` job."""
    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES
    setup_type = next(iter(SETUP_TRAINING_PROFILES.keys()))
    bar_size = SETUP_TRAINING_PROFILES[setup_type][0]["bar_size"]

    fake_mgr = AsyncMock()
    fake_mgr.create_job = AsyncMock(return_value={
        "success": True,
        "job": {"job_id": "setup-xyz"},
    })

    req = ScorecardRetrainRequest(setup_type=setup_type, bar_size=bar_size)
    with patch("services.ai_modules.ML_AVAILABLE", True), \
         patch("services.job_queue_manager.job_queue_manager", fake_mgr):
        body = _run(retrain_model_from_scorecard(req))

    assert body["success"] is True
    assert body["kind"] == "setup_specific"
    assert body["job_id"] == "setup-xyz"
    assert body["setup_type"] == setup_type.upper()
    assert body["bar_size"] == bar_size

    kwargs = fake_mgr.create_job.await_args.kwargs
    assert kwargs["job_type"] == "setup_training"
    assert kwargs["params"]["setup_type"] == setup_type.upper()
    assert kwargs["params"]["bar_size"] == bar_size


def test_retrain_setup_rejects_invalid_bar_size_for_setup():
    """If a bar_size is well-formed but not declared for that setup, 400."""
    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES
    setup_type = next(iter(SETUP_TRAINING_PROFILES.keys()))
    declared = {p["bar_size"] for p in SETUP_TRAINING_PROFILES[setup_type]}
    candidates = ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]
    undeclared = next((b for b in candidates if b not in declared), None)
    if undeclared is None:
        pytest.skip(f"setup {setup_type} declares all timeframes")

    req = ScorecardRetrainRequest(setup_type=setup_type, bar_size=undeclared)
    with patch("services.ai_modules.ML_AVAILABLE", True):
        with pytest.raises(HTTPException) as exc:
            _run(retrain_model_from_scorecard(req))
    assert exc.value.status_code == 400
    detail = str(exc.value.detail).lower()
    assert "not declared" in detail or "valid" in detail


# ─── Queue failure surfaces cleanly ─────────────────────────────────────────

def test_retrain_queue_failure_returns_success_false():
    """If job_queue_manager.create_job returns success=False we pass that through."""
    fake_mgr = AsyncMock()
    fake_mgr.create_job = AsyncMock(return_value={
        "success": False,
        "error": "queue at capacity",
    })

    req = ScorecardRetrainRequest(setup_type="__GENERIC__", bar_size="1 day")
    with patch("services.ai_modules.ML_AVAILABLE", True), \
         patch("services.job_queue_manager.job_queue_manager", fake_mgr):
        body = _run(retrain_model_from_scorecard(req))

    assert body["success"] is False
    assert body["error"] == "queue at capacity"
