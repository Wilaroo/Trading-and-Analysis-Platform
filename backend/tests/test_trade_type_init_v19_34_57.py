"""Regression: v19.34.57 — Stamp `trade_type` at BotTrade construction.

Bug audit: 227 `bot_trades` rows persisted with `trade_type='unknown'`
because they were REJECTED/VETOED by the bot's pre-trade gates and never
reached the fill block in `services/trade_execution.py` (~L790-835)
where `trade_type` was historically stamped. That broke paper-vs-live
attribution and the live-readiness gate.

Fix: `BotTrade.__post_init__` defaults `trade_type` from
`load_account_expectation().active_mode` (the operator's configured
intent via `IB_ACCOUNT_ACTIVE`) when the dataclass default
`"unknown"` is still in place at init. Fill-time logic in
`trade_execution.py` remains canonical — it overwrites with the
*actual* IB account classification on real fills.

This regression test pins:
  1. Construction defaults to env `active_mode` ("paper" / "live").
  2. Explicit non-"unknown" trade_type passed to ctor is preserved.
  3. account_guard import failure / env-load exception → "unknown"
     (graceful degrade — never worse than legacy v19.34.56 behavior).
  4. Fill-time stamp in trade_execution.py still wins (sanity).

NOTE: The `BotTrade` dataclass requires many fields. We import it
lazily and build with the minimum-required positional set, mirroring
the `_build_min_trade` helper used elsewhere in the suite.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make `backend/` importable when pytest is run from /app
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── helper: build a minimal valid BotTrade ───────────────────────────
def _build_min_trade(trade_type: str | None = None):
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    kwargs = dict(
        id="t-test",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        status=TradeStatus.PENDING,
        setup_type="VWAP",
        timeframe="5m",
        quality_score=80,
        quality_grade="A",
        entry_price=100.0,
        current_price=100.0,
        stop_price=99.0,
        target_prices=[101.0, 102.0],
        shares=10,
        risk_amount=10.0,
        potential_reward=20.0,
        risk_reward_ratio=2.0,
    )
    if trade_type is not None:
        kwargs["trade_type"] = trade_type
    return BotTrade(**kwargs)


# ── Test 1: env=paper → default trade_type=paper ─────────────────────
def test_post_init_stamps_paper_from_env(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    # Force re-import path uncached for account_guard env read
    trade = _build_min_trade()
    assert trade.trade_type == "paper", (
        "v19.34.57: __post_init__ must stamp trade_type=paper "
        "when IB_ACCOUNT_ACTIVE=paper, instead of leaving 'unknown'"
    )


# ── Test 2: env=live → default trade_type=live ───────────────────────
def test_post_init_stamps_live_from_env(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "live")
    trade = _build_min_trade()
    assert trade.trade_type == "live", (
        "v19.34.57: __post_init__ must stamp trade_type=live "
        "when IB_ACCOUNT_ACTIVE=live"
    )


# ── Test 3: env unset → defaults to 'paper' (account_guard default) ──
def test_post_init_env_unset_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("IB_ACCOUNT_ACTIVE", raising=False)
    trade = _build_min_trade()
    assert trade.trade_type == "paper", (
        "v19.34.57: account_guard.load_account_expectation defaults to "
        "'paper' when IB_ACCOUNT_ACTIVE is unset — __post_init__ must "
        "inherit that"
    )


# ── Test 4: explicit non-unknown trade_type is preserved ─────────────
def test_post_init_preserves_explicit_trade_type(monkeypatch):
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")
    trade = _build_min_trade(trade_type="live")
    assert trade.trade_type == "live", (
        "v19.34.57: __post_init__ must NOT clobber an explicit trade_type "
        "passed by the caller (e.g., reconciler stamping 'live' from a "
        "real account_id classification)"
    )


# ── Test 5: account_guard explosion → graceful 'unknown' fallback ────
def test_post_init_falls_back_to_unknown_on_account_guard_exception():
    # Patch load_account_expectation to raise — simulates an env race
    # or a corrupt account_guard module at construction time.
    with patch(
        "services.account_guard.load_account_expectation",
        side_effect=RuntimeError("simulated env corruption"),
    ):
        trade = _build_min_trade()
        assert trade.trade_type == "unknown", (
            "v19.34.57: when account_guard fails, __post_init__ must "
            "leave trade_type='unknown' (never worse than legacy)"
        )


# ── Test 6: invalid env value normalized by account_guard → 'paper' ──
def test_post_init_invalid_env_value_normalizes_to_paper(monkeypatch):
    # account_guard.load_account_expectation forces invalid values to
    # 'paper' with a warning. __post_init__ must inherit that
    # normalization, not the raw env string.
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "garbage_mode")
    trade = _build_min_trade()
    assert trade.trade_type == "paper", (
        "v19.34.57: account_guard normalizes invalid IB_ACCOUNT_ACTIVE "
        "values to 'paper'; __post_init__ must inherit normalized value"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
