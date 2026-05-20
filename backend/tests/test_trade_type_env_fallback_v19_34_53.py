"""Regression: v19.34.53 — bot-fired trade_type stamp env-fallback."""

import pytest
from unittest.mock import MagicMock


class _FakeTrade:
    def __init__(self):
        self.trade_type = "unknown"
        self.account_id_at_fill = None
        self.notes = ""
        self.entered_by = "?"


def _run_classify_block_with_exception(trade, exc_type=RuntimeError):
    try:
        raise exc_type("simulated transient pusher/import race")
    except Exception:
        try:
            from services.account_guard import load_account_expectation
            trade.trade_type = load_account_expectation().active_mode
        except Exception:
            trade.trade_type = "unknown"


def test_classify_exception_falls_back_to_env_paper(monkeypatch):
    fake_exp = MagicMock()
    fake_exp.active_mode = "paper"
    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        lambda: fake_exp,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "paper"


def test_classify_exception_falls_back_to_env_live(monkeypatch):
    fake_exp = MagicMock()
    fake_exp.active_mode = "live"
    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        lambda: fake_exp,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "live"


def test_both_classify_and_env_fail_falls_back_to_unknown(monkeypatch):
    def _boom():
        raise RuntimeError("env load also failed (e.g. corrupted .env)")
    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        _boom,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "unknown"


def test_import_error_in_fallback_degrades_to_unknown(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _import_blocker(name, *args, **kwargs):
        if "account_guard" in name:
            raise ImportError("simulated module load failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_blocker)
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "unknown"


def test_patch_text_present_in_trade_execution_module():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "services" / "trade_execution.py"
    text = src.read_text()
    assert "v19.34.53" in text
    assert "load_account_expectation().active_mode" in text


def test_real_account_guard_loads_some_mode(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    monkeypatch.setenv("IB_PAPER_ACCOUNT_ID", "DUTEST123")
    monkeypatch.setenv("IB_LIVE_ACCOUNT_ID", "U0000000")
    from services.account_guard import load_account_expectation
    exp = load_account_expectation()
    assert exp.active_mode in ("paper", "live")
    assert exp.active_mode == "paper"
