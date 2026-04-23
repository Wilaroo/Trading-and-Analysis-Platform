"""
Tests for services/account_guard — paper/live two-account guard.
"""
import pytest

from services import account_guard as ag


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("IB_ACCOUNT_LIVE", "IB_ACCOUNT_PAPER", "IB_ACCOUNT_ACTIVE"):
        monkeypatch.delenv(k, raising=False)
    yield


# ── load_account_expectation ──────────────────────────────────────────

def test_default_mode_is_paper(monkeypatch):
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_account_id is None


def test_paper_mode_picks_paper_id(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_account_id == "paperesw100000"
    assert exp.live_account_id == "esw100000"
    assert exp.paper_account_id == "paperesw100000"


def test_live_mode_picks_live_id(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "live")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "live"
    assert exp.expected_account_id == "esw100000"


def test_invalid_mode_falls_back_to_paper(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "gibberish")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_account_id == "paperesw100000"


def test_mode_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "LIVE")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "live"
    assert exp.expected_account_id == "esw100000"


# ── check_account_match ───────────────────────────────────────────────

def test_check_unconfigured_returns_ok(monkeypatch):
    # No env vars → unconfigured → treated as OK (opt-in)
    ok, reason = ag.check_account_match("whatever")
    assert ok is True
    assert reason == "unconfigured"


def test_check_paper_match_ok(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match("paperesw100000")
    assert ok is True
    assert "ok (paper)" in reason


def test_check_case_insensitive_match(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, _ = ag.check_account_match("PAPERESW100000")
    assert ok is True


def test_check_live_when_expecting_paper_blocks():
    """The exact scenario from the user: expected paperesw100000, got esw100000."""
    import os
    os.environ["IB_ACCOUNT_LIVE"] = "esw100000"
    os.environ["IB_ACCOUNT_PAPER"] = "paperesw100000"
    os.environ["IB_ACCOUNT_ACTIVE"] = "paper"
    try:
        ok, reason = ag.check_account_match("esw100000")
        assert ok is False
        assert "expected paperesw100000" in reason
        assert "got esw100000" in reason
        assert "(paper)" in reason
    finally:
        for k in ("IB_ACCOUNT_LIVE", "IB_ACCOUNT_PAPER", "IB_ACCOUNT_ACTIVE"):
            os.environ.pop(k, None)


def test_check_no_current_account_blocks(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match(None)
    assert ok is False
    assert "no account reported" in reason


def test_check_whitespace_tolerated(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, _ = ag.check_account_match("  paperesw100000  ")
    assert ok is True


# ── summarize_for_ui ──────────────────────────────────────────────────

def test_ui_payload_shape(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    payload = ag.summarize_for_ui("paperesw100000")
    assert payload["active_mode"] == "paper"
    assert payload["expected_account_id"] == "paperesw100000"
    assert payload["current_account_id"] == "paperesw100000"
    assert payload["live_account_id"] == "esw100000"
    assert payload["paper_account_id"] == "paperesw100000"
    assert payload["match"] is True


def test_ui_payload_flags_mismatch(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    payload = ag.summarize_for_ui("esw100000")
    assert payload["match"] is False
    assert "expected paperesw100000" in payload["reason"]
