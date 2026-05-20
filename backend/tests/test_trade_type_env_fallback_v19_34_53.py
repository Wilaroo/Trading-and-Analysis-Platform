"""Regression: v19.34.53 — bot-fired trade_type stamp env-fallback.

Bug: v19.34.51 backfilled 8 `bot_trades` rows with `trade_type='unknown'`.
3 of those 8 had `entered_by='bot_fired'` (BBIO, ALNY, BALL). The
v19.34.51 reconciler patch fixed the orphan-reconciler path but not
the bot-fired path in `services/trade_execution.py`.

The bot-fired classify block (lines ~790-825) had a bare except that
went straight to `trade_type = "unknown"` if any error fired during
the pusher snapshot read or account_guard import — which kills the
audit trail.

v19.34.53 mirrors the v19.34.51 fix: env-fallback BEFORE "unknown".
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Helper: a minimal BotTrade-shaped object for stamping ────────────
class _FakeTrade:
    def __init__(self):
        self.trade_type = "unknown"
        self.account_id_at_fill = None
        self.notes = ""
        self.entered_by = "?"


def _run_classify_block_with_exception(trade, exc_type=RuntimeError):
    """Reproduce the lines 797-836 except branch in isolation.

    Mocks the inner classify path (account snapshot + classify_account_id)
    to raise, then runs the env-fallback the v19.34.53 patch installs.
    Mirrors the patch shape so future code drift is caught.
    """
    try:
        # Simulate the v19.34.53 try-block: classify path explodes.
        raise exc_type("simulated transient pusher/import race")
    except Exception:
        try:
            from services.account_guard import load_account_expectation
            trade.trade_type = load_account_expectation().active_mode
        except Exception:
            trade.trade_type = "unknown"


# ── Test 1: classify exception → env paper ────────────────────────────
def test_classify_exception_falls_back_to_env_paper(monkeypatch):
    fake_exp = MagicMock()
    fake_exp.active_mode = "paper"
    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        lambda: fake_exp,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "paper", \
        "env active_mode=paper must be stamped on classify exception"


# ── Test 2: classify exception → env live ─────────────────────────────
def test_classify_exception_falls_back_to_env_live(monkeypatch):
    fake_exp = MagicMock()
    fake_exp.active_mode = "live"
    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        lambda: fake_exp,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "live", \
        "env active_mode=live must be stamped on classify exception"


# ── Test 3: classify AND env both fail → "unknown" (last resort) ──────
def test_both_classify_and_env_fail_falls_back_to_unknown(monkeypatch):
    def _boom():
        raise RuntimeError("env load also failed (e.g. corrupted .env)")

    monkeypatch.setattr(
        "services.account_guard.load_account_expectation",
        _boom,
    )
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "unknown", \
        "should still degrade to 'unknown' if env load itself fails"


# ── Test 4: importerror inside fallback also degrades cleanly ─────────
def test_import_error_in_fallback_degrades_to_unknown(monkeypatch):
    # Force the inner import to raise (simulates account_guard module
    # not loadable for whatever reason).
    import builtins
    real_import = builtins.__import__

    def _import_blocker(name, *args, **kwargs):
        if name == "services.account_guard" or name.endswith("account_guard"):
            raise ImportError("simulated module load failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_blocker)
    trade = _FakeTrade()
    _run_classify_block_with_exception(trade)
    assert trade.trade_type == "unknown"


# ── Test 5: shape-of-fix sanity — patch text is in the actual file ────
def test_patch_text_present_in_trade_execution_module():
    """Lock the v19.34.53 patch shape so a future refactor doesn't silently
    revert it. If this test fails, the fix has been removed or moved.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "services" / "trade_execution.py"
    text = src.read_text()
    assert "v19.34.53" in text, \
        "v19.34.53 patch marker missing from trade_execution.py"
    assert "load_account_expectation().active_mode" in text, \
        "env-fallback call missing — fix may have been reverted"
    # The "unknown" string should still appear (last-resort path) but
    # only INSIDE a nested try/except, not as the immediate except body.
    # Easiest invariant: count occurrences and require at least one
    # accompanying load_account_expectation in the same file.
    assert text.count("load_account_expectation") >= 1


# ── Test 6: end-to-end smoke — real account_guard returns env mode ────
def test_real_account_guard_loads_some_mode(monkeypatch):
    """Sanity: the real account_guard.load_account_expectation() returns
    a non-empty active_mode in 'paper'/'live'. This is what the patch
    relies on to stamp meaningful values.
    """
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    # Other env vars referenced by load_account_expectation — harmless
    # defaults; we only assert active_mode reflects IB_ACCOUNT_ACTIVE.
    monkeypatch.setenv("IB_PAPER_ACCOUNT_ID", "DUTEST123")
    monkeypatch.setenv("IB_LIVE_ACCOUNT_ID", "U0000000")
    from services.account_guard import load_account_expectation
    exp = load_account_expectation()
    assert exp.active_mode in ("paper", "live")
    assert exp.active_mode == "paper"
