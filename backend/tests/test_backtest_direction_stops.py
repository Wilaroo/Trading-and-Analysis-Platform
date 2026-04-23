"""
Regression tests for the "simulated exit ignores stops" bug fix
(2026-04-22) in advanced_backtest_engine.py.

Covers all three simulation methods:
- _simulate_strategy
- _simulate_strategy_with_ai
- _simulate_strategy_with_gate

For each: verify stop/target hits correctly for SHORT AND LONG
using direction-aware high/low comparisons, and that PnL is
computed with the correct sign.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.slow_learning.advanced_backtest_engine import (
    AdvancedBacktestEngine,
    StrategyConfig,
)


# ---------- Helpers ----------

def _bar(ts, o, h, l, c, v=1_000_000):
    return {
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def _long_setup(stop_pct=2.0, target_pct=4.0, max_bars=10):
    return StrategyConfig(
        name="long_test",
        setup_type="orb",  # long
        stop_pct=stop_pct,
        target_pct=target_pct,
        max_bars_to_hold=max_bars,
        position_size_pct=10.0,
    )


def _short_setup(stop_pct=2.0, target_pct=4.0, max_bars=10):
    return StrategyConfig(
        name="short_test",
        setup_type="short_orb",  # short
        stop_pct=stop_pct,
        target_pct=target_pct,
        max_bars_to_hold=max_bars,
        position_size_pct=10.0,
    )


def _build_bars_entry_then_stop_up(entry_price: float, stop_above_pct: float):
    """Bars designed to force a SHORT stop hit (price rips up through stop)."""
    # entry bar (flat, so no premature stop/target)
    bars = [_bar(f"2026-01-01T09:{30+i:02d}:00", entry_price, entry_price + 0.01,
                 entry_price - 0.01, entry_price) for i in range(3)]
    # next bar: high blows through stop
    stop_price = entry_price * (1 + stop_above_pct / 100)
    bars.append(_bar("2026-01-01T09:33:00", entry_price,
                     stop_price + 0.50, entry_price - 0.10, entry_price + 0.05))
    return bars, stop_price


def _build_bars_entry_then_target_down(entry_price: float, target_below_pct: float):
    """Bars designed to force a SHORT target hit (price drops to target)."""
    bars = [_bar(f"2026-01-01T09:{30+i:02d}:00", entry_price, entry_price + 0.01,
                 entry_price - 0.01, entry_price) for i in range(3)]
    target_price = entry_price * (1 - target_below_pct / 100)
    bars.append(_bar("2026-01-01T09:33:00", entry_price, entry_price + 0.10,
                     target_price - 0.50, entry_price - 0.05))
    return bars, target_price


def _build_bars_entry_then_stop_down(entry_price: float, stop_below_pct: float):
    """Bars designed to force a LONG stop hit (price drops through stop)."""
    bars = [_bar(f"2026-01-01T09:{30+i:02d}:00", entry_price, entry_price + 0.01,
                 entry_price - 0.01, entry_price) for i in range(3)]
    stop_price = entry_price * (1 - stop_below_pct / 100)
    bars.append(_bar("2026-01-01T09:33:00", entry_price, entry_price + 0.10,
                     stop_price - 0.50, entry_price - 0.05))
    return bars, stop_price


def _build_bars_entry_then_target_up(entry_price: float, target_above_pct: float):
    """Bars designed to force a LONG target hit (price rips up)."""
    bars = [_bar(f"2026-01-01T09:{30+i:02d}:00", entry_price, entry_price + 0.01,
                 entry_price - 0.01, entry_price) for i in range(3)]
    target_price = entry_price * (1 + target_above_pct / 100)
    bars.append(_bar("2026-01-01T09:33:00", entry_price,
                     target_price + 0.50, entry_price - 0.10, entry_price + 0.05))
    return bars, target_price


@pytest.fixture
def engine():
    return AdvancedBacktestEngine()


# ---------- _simulate_strategy ----------

@pytest.mark.asyncio
async def test_simulate_strategy_short_stop_triggers_on_high(engine):
    """SHORT: stop must fire when bar HIGH exceeds stop_price (above entry)."""
    entry = 100.0
    bars, expected_stop = _build_bars_entry_then_stop_up(entry, stop_above_pct=2.0)
    strategy = _short_setup(stop_pct=2.0)

    # Force entry on first bar
    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve = await engine._simulate_strategy("TEST", bars, strategy, 100_000)

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "short"
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(expected_stop, rel=1e-6)
    # SHORT stopped out => PnL negative
    assert t.pnl < 0


@pytest.mark.asyncio
async def test_simulate_strategy_short_target_triggers_on_low(engine):
    entry = 100.0
    bars, expected_target = _build_bars_entry_then_target_down(entry, target_below_pct=4.0)
    strategy = _short_setup(target_pct=4.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve = await engine._simulate_strategy("TEST", bars, strategy, 100_000)

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "short"
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(expected_target, rel=1e-6)
    # SHORT hit target below entry => profit
    assert t.pnl > 0


@pytest.mark.asyncio
async def test_simulate_strategy_long_stop_triggers_on_low(engine):
    entry = 100.0
    bars, expected_stop = _build_bars_entry_then_stop_down(entry, stop_below_pct=2.0)
    strategy = _long_setup(stop_pct=2.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve = await engine._simulate_strategy("TEST", bars, strategy, 100_000)

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long"
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(expected_stop, rel=1e-6)
    assert t.pnl < 0


@pytest.mark.asyncio
async def test_simulate_strategy_long_target_triggers_on_high(engine):
    entry = 100.0
    bars, expected_target = _build_bars_entry_then_target_up(entry, target_above_pct=4.0)
    strategy = _long_setup(target_pct=4.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve = await engine._simulate_strategy("TEST", bars, strategy, 100_000)

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long"
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(expected_target, rel=1e-6)
    assert t.pnl > 0


# ---------- _simulate_strategy_with_gate ----------

class _DummyGate:
    async def evaluate(self, **_kwargs):
        return {"decision": "GO", "position_multiplier": 1.0}


@pytest.mark.asyncio
async def test_gate_short_stop_triggers_and_pnl_negative(engine):
    engine._confidence_gate = _DummyGate()
    entry = 100.0
    bars, expected_stop = _build_bars_entry_then_stop_up(entry, stop_above_pct=2.0)
    strategy = _short_setup(stop_pct=2.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve, stats = await engine._simulate_strategy_with_gate(
            "TEST", bars, strategy, 100_000, lookback_bars=0,
        )

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "short"
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(expected_stop, rel=1e-6)
    assert t.pnl < 0
    assert stats["go"] == 1


@pytest.mark.asyncio
async def test_gate_short_target_triggers_and_pnl_positive(engine):
    engine._confidence_gate = _DummyGate()
    entry = 100.0
    bars, expected_target = _build_bars_entry_then_target_down(entry, target_below_pct=4.0)
    strategy = _short_setup(target_pct=4.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve, _stats = await engine._simulate_strategy_with_gate(
            "TEST", bars, strategy, 100_000, lookback_bars=0,
        )

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "short"
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(expected_target, rel=1e-6)
    assert t.pnl > 0


@pytest.mark.asyncio
async def test_gate_long_stop_triggers_and_pnl_negative(engine):
    engine._confidence_gate = _DummyGate()
    entry = 100.0
    bars, expected_stop = _build_bars_entry_then_stop_down(entry, stop_below_pct=2.0)
    strategy = _long_setup(stop_pct=2.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        trades, _curve, _stats = await engine._simulate_strategy_with_gate(
            "TEST", bars, strategy, 100_000, lookback_bars=0,
        )

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long"
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(expected_stop, rel=1e-6)
    assert t.pnl < 0


# ---------- _simulate_strategy_with_ai ----------

class _DummyAIPrediction:
    def __init__(self, direction, confidence=0.9):
        self.direction = direction
        self.confidence = confidence


@pytest.mark.asyncio
async def test_ai_short_stop_triggers_and_pnl_negative(engine):
    entry = 100.0
    bars, expected_stop = _build_bars_entry_then_stop_up(entry, stop_above_pct=2.0)
    strategy = _short_setup(stop_pct=2.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        with patch.object(engine, "_get_ai_prediction",
                          return_value=_DummyAIPrediction("down", 0.9)):
            trades, _curve = await engine._simulate_strategy_with_ai(
                "TEST", bars, strategy, 100_000,
                ai_mode="filter", confidence_threshold=0.5, lookback_bars=0,
            )

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "short"
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(expected_stop, rel=1e-6)
    assert t.pnl < 0


@pytest.mark.asyncio
async def test_ai_long_target_triggers_and_pnl_positive(engine):
    entry = 100.0
    bars, expected_target = _build_bars_entry_then_target_up(entry, target_above_pct=4.0)
    strategy = _long_setup(target_pct=4.0)

    with patch.object(engine, "_check_entry_signal",
                      side_effect=lambda b, s, rb: b["timestamp"].endswith("09:30:00")):
        with patch.object(engine, "_get_ai_prediction",
                          return_value=_DummyAIPrediction("up", 0.9)):
            trades, _curve = await engine._simulate_strategy_with_ai(
                "TEST", bars, strategy, 100_000,
                ai_mode="filter", confidence_threshold=0.5, lookback_bars=0,
            )

    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long"
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(expected_target, rel=1e-6)
    assert t.pnl > 0
