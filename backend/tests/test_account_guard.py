"""
Tests for services/account_guard — paper/live two-account guard with
multi-alias support (login username + IB account number both valid).
"""
import pytest

from services import account_guard as ag


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("IB_ACCOUNT_LIVE", "IB_ACCOUNT_PAPER", "IB_ACCOUNT_ACTIVE"):
        monkeypatch.delenv(k, raising=False)
    yield


# ── _parse_aliases ────────────────────────────────────────────────────

def test_parse_aliases_empty():
    assert ag._parse_aliases(None) == []
    assert ag._parse_aliases("") == []
    assert ag._parse_aliases("   ") == []


def test_parse_aliases_single():
    assert ag._parse_aliases("paperesw100000") == ["paperesw100000"]


def test_parse_aliases_comma_separated():
    assert ag._parse_aliases("paperesw100000,DUN615665") == [
        "paperesw100000",
        "dun615665",
    ]


def test_parse_aliases_pipe_and_spaces():
    assert ag._parse_aliases("A | B   C,D") == ["a", "b", "c", "d"]


def test_parse_aliases_dedups_case_insensitive():
    assert ag._parse_aliases("X, x, X") == ["x"]


# ── load_account_expectation ──────────────────────────────────────────

def test_default_mode_is_paper(monkeypatch):
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_aliases == []
    assert exp.expected_account_id is None


def test_paper_mode_picks_paper_aliases(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_aliases == ["paperesw100000", "dun615665"]
    assert exp.paper_aliases == ["paperesw100000", "dun615665"]
    assert exp.live_aliases == ["esw100000"]
    # UI convenience fields
    assert exp.expected_account_id == "paperesw100000"
    assert exp.paper_account_id == "paperesw100000"
    assert exp.live_account_id == "esw100000"


def test_live_mode_picks_live_aliases(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000,U1234567")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "live")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "live"
    assert exp.expected_aliases == ["esw100000", "u1234567"]


def test_invalid_mode_falls_back_to_paper(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "gibberish")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "paper"
    assert exp.expected_aliases == ["paperesw100000"]


def test_mode_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "LIVE")
    exp = ag.load_account_expectation()
    assert exp.active_mode == "live"
    assert exp.expected_aliases == ["esw100000"]


# ── check_account_match ───────────────────────────────────────────────

def test_check_unconfigured_returns_ok():
    ok, reason = ag.check_account_match("whatever")
    assert ok is True
    assert reason == "unconfigured"


def test_check_paper_match_by_login(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match("paperesw100000")
    assert ok is True
    assert "matched 'paperesw100000'" in reason
    assert "(paper" in reason


def test_check_paper_match_by_account_number(monkeypatch):
    """The exact user case — IB reports the account NUMBER, not the login."""
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match("DUN615665")
    assert ok is True
    assert "matched 'dun615665'" in reason


def test_check_case_insensitive_match(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, _ = ag.check_account_match("dun615665")
    assert ok is True


def test_check_whitespace_tolerated(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, _ = ag.check_account_match("  paperesw100000  ")
    assert ok is True


def test_check_live_account_reported_while_paper_expected_blocks(monkeypatch):
    """Original user scenario: paper expected, live pusher → block + classify."""
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match("esw100000")
    assert ok is False
    assert "got esw100000" in reason
    assert "belongs to live mode" in reason


def test_check_unknown_account_blocks(monkeypatch):
    """Account that belongs to neither configured mode."""
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match("U9999999")
    assert ok is False
    assert "got U9999999" in reason
    # Shouldn't misclassify — it's not in either set.
    assert "belongs to" not in reason


def test_check_no_current_account_blocks(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    ok, reason = ag.check_account_match(None)
    assert ok is False
    assert "no account reported" in reason
    assert "paperesw100000/dun615665" in reason


# ── summarize_for_ui ──────────────────────────────────────────────────

def test_ui_payload_includes_aliases(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    payload = ag.summarize_for_ui("DUN615665")
    assert payload["active_mode"] == "paper"
    assert payload["expected_account_id"] == "paperesw100000"
    assert payload["expected_aliases"] == ["paperesw100000", "dun615665"]
    assert payload["current_account_id"] == "DUN615665"
    assert payload["live_aliases"] == ["esw100000"]
    assert payload["paper_aliases"] == ["paperesw100000", "dun615665"]
    assert payload["match"] is True


def test_ui_payload_flags_mismatch_with_alias_classification(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000,U1234567")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000,DUN615665")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    payload = ag.summarize_for_ui("U1234567")
    assert payload["match"] is False
    assert "belongs to live mode" in payload["reason"]
