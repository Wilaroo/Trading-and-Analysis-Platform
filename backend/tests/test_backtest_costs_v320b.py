"""
v320b Tier-1b — Execution-cost modeling in advanced_backtest_engine.

Synthetic pinning tests — container/DGX-safe: no DB, no IB required.
Drives the REAL `_simulate_strategy` loop with a stub engine whose entry
signal is controlled per-bar via bars[i]["signal"].

Pins:
  1. Pure helpers: _slip / _commission / _stop_fill / _target_fill / _bt_cost_cfg.
  2. NEXT-BAR-OPEN fills: a signal on bar i fills at bar i+1's OPEN.
  3. Entry slippage: fill = open * (1 + bps/10000) for longs.
  4. GAP-THROUGH stops: bar opens below the stop → fill at the open, not the stop.
  5. Commission: round-trip max(min, shares*rate)*2 subtracted from pnl.
  6. BT_COSTS=0 → byte-identical legacy behaviour (close fills, exact stops).

Run (DGX, from backend/):  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_backtest_costs_v320b.py -v
Run (container):           cd /app/backend && python -m pytest tests/test_backtest_costs_v320b.py -v
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.slow_learning.advanced_backtest_engine import (  # noqa: E402
    AdvancedBacktestEngine,
    StrategyConfig,
    _bt_cost_cfg,
    _commission,
    _slip,
    _stop_fill,
    _target_fill,
)


class _StubEngine:
    """Minimal engine stub: entry signal fires only when bar carries signal=True."""

    def _check_entry_signal(self, bar, strategy, recent_bars):
        return bool(bar.get("signal", False))


def _bars(specs):
    """Build OHLCV bars from compact specs. Defaults keep stops/targets safe."""
    out = []
    for k, s in enumerate(specs):
        c = s.get("c", 100.0)
        o = s.get("o", c)
        out.append({
            "timestamp": f"2026-03-{(k % 27) + 1:02d}T10:00:00",
            "open": o,
            "high": s.get("h", max(c, o) + 0.4),
            "low": s.get("l", min(c, o) - 0.4),
            "close": c,
            "volume": 1_000_000,
            "signal": s.get("signal", False),
        })
    return out


def _strategy(max_hold=5):
    return StrategyConfig(
        name="t", setup_type="breakout", stop_pct=2.0, target_pct=4.0,
        position_size_pct=10.0, max_bars_to_hold=max_hold,
    )


def _run(bars, strategy, capital=100_000.0):
    return asyncio.run(
        AdvancedBacktestEngine._simulate_strategy(_StubEngine(), "TEST", bars, strategy, capital)
    )


def _set_costs(monkeypatch, *, costs="1", slip="0", comm="0", comm_min="0", next_bar="1"):
    monkeypatch.setenv("BT_COSTS", costs)
    monkeypatch.setenv("BT_SLIPPAGE_BPS", slip)
    monkeypatch.setenv("BT_COMMISSION_PER_SHARE", comm)
    monkeypatch.setenv("BT_COMMISSION_MIN", comm_min)
    monkeypatch.setenv("BT_NEXT_BAR_FILLS", next_bar)


# ── 1. pure helpers ──────────────────────────────────────────────────────────

def test_slip_adverse_direction():
    assert _slip(100.0, True, 10.0) == pytest.approx(100.10)    # buy fills higher
    assert _slip(100.0, False, 10.0) == pytest.approx(99.90)    # sell fills lower
    assert _slip(100.0, True, 0.0) == 100.0                     # zero bps = no-op
    assert _slip(0.0, True, 10.0) == 0.0                        # bad price = no-op


def test_commission_minimum_and_per_share():
    cfg = {"commission_per_share": 0.005, "commission_min": 1.0}
    assert _commission(100, cfg) == 1.0       # 100 * 0.005 = 0.50 → min kicks in
    assert _commission(1000, cfg) == 5.0      # 1000 * 0.005 = 5.00
    assert _commission(0, cfg) == 0.0
    assert _commission(100, {"commission_per_share": 0.0, "commission_min": 1.0}) == 0.0


def test_stop_fill_gap_through():
    # LONG: stop 98 — open gapped to 96 → you get 96 (worse), open at 99 → exact stop
    assert _stop_fill(98.0, 96.0, False) == 96.0
    assert _stop_fill(98.0, 99.0, False) == 98.0
    # SHORT: stop 102 — open gapped to 104 → you get 104 (worse)
    assert _stop_fill(102.0, 104.0, True) == 104.0
    assert _stop_fill(102.0, 101.0, True) == 102.0


def test_target_fill_gap_through():
    # LONG target 104 — open gapped to 106 → 106 (better); open 103 → exact limit
    assert _target_fill(104.0, 106.0, False) == 106.0
    assert _target_fill(104.0, 103.0, False) == 104.0
    # SHORT target 96 — open gapped to 94 → 94 (better)
    assert _target_fill(96.0, 94.0, True) == 94.0
    assert _target_fill(96.0, 97.0, True) == 96.0


def test_cost_cfg_master_switch(monkeypatch):
    monkeypatch.setenv("BT_COSTS", "0")
    cfg = _bt_cost_cfg()
    assert cfg["enabled"] is False
    assert cfg["slippage_bps"] == 0.0
    assert cfg["commission_per_share"] == 0.0
    assert cfg["next_bar_fills"] is False
    monkeypatch.setenv("BT_COSTS", "1")
    monkeypatch.delenv("BT_SLIPPAGE_BPS", raising=False)
    cfg = _bt_cost_cfg()
    assert cfg["enabled"] is True
    assert cfg["slippage_bps"] == 2.0  # default


# ── 2/3. next-bar-open fills + entry slippage ────────────────────────────────

def test_next_bar_open_fill(monkeypatch):
    _set_costs(monkeypatch)  # costs on, slippage 0, commission 0
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True          # signal at bar 5, close 100
    specs[6] = {"c": 101.0, "o": 101.0}  # next bar opens at 101
    for k in range(7, 12):
        specs[k] = {"c": 101.0, "o": 101.0}
    trades, _ = _run(_bars(specs), _strategy(max_hold=3))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == pytest.approx(101.0), "must fill at NEXT bar's open, not signal close"
    assert t.entry_date == "2026-03-07"  # bar index 6


def test_entry_slippage_applied(monkeypatch):
    _set_costs(monkeypatch, slip="10")  # 10 bps
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True
    for k in range(6, 12):
        specs[k] = {"c": 101.0, "o": 101.0}
    trades, _ = _run(_bars(specs), _strategy(max_hold=3))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == pytest.approx(101.0 * 1.001)  # adverse for a buy
    assert t.slippage_cost == pytest.approx((t.entry_price - 101.0) * t.shares)


# ── 4. gap-through stop ──────────────────────────────────────────────────────

def test_gap_through_stop_fills_at_open(monkeypatch):
    _set_costs(monkeypatch)
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True
    specs[6] = {"c": 100.0, "o": 100.0}             # fill at 100 → stop 98, target 104
    specs[7] = {"c": 100.0, "o": 100.0}
    specs[8] = {"c": 95.0, "o": 95.0, "l": 94.0, "h": 95.5}  # opens BELOW the 98 stop
    trades, _ = _run(_bars(specs), _strategy(max_hold=8))
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(95.0), "gap-through stop must fill at the open"
    assert t.pnl == pytest.approx((95.0 - 100.0) * t.shares)


def test_gap_up_through_target_fills_at_open(monkeypatch):
    _set_costs(monkeypatch)
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True
    specs[6] = {"c": 100.0, "o": 100.0}             # fill 100 → target 104
    specs[7] = {"c": 100.0, "o": 100.0}
    specs[8] = {"c": 105.0, "o": 105.0, "h": 105.5, "l": 104.5}  # opens ABOVE target
    trades, _ = _run(_bars(specs), _strategy(max_hold=8))
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(105.0), "gap through limit target fills at the (better) open"


# ── 5. commission ────────────────────────────────────────────────────────────

def test_round_trip_commission_subtracted(monkeypatch):
    _set_costs(monkeypatch, comm="0.005", comm_min="1.0")
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True  # fill bar6 at 100, flat forever → time exit at 100
    trades, _ = _run(_bars(specs), _strategy(max_hold=3))
    assert len(trades) == 1
    t = trades[0]
    assert t.shares == 100                       # 10% of 100k @ $100
    assert t.commission == pytest.approx(2.0)    # max(1, 100*0.005)=1 per side × 2
    assert t.pnl == pytest.approx(-2.0)          # flat price → pure commission loss


# ── 6. legacy mode is fully preserved ────────────────────────────────────────

def test_bt_costs_off_restores_legacy_behaviour(monkeypatch):
    _set_costs(monkeypatch, costs="0")
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True
    specs[8] = {"c": 95.0, "o": 95.0, "l": 94.0, "h": 95.5}  # gap below stop
    trades, _ = _run(_bars(specs), _strategy(max_hold=8))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == pytest.approx(100.0), "legacy fills at SIGNAL bar close"
    assert t.entry_date == "2026-03-06"           # bar index 5 (signal bar)
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(98.0), "legacy fills at EXACT stop price"
    assert t.commission == 0.0
    assert t.pnl == pytest.approx((98.0 - 100.0) * t.shares)


def test_costs_reduce_pnl_vs_legacy(monkeypatch):
    """Same winning tape (intrabar target hit, NO gaps) with and without costs
    → the costs version must earn LESS (slippage + commission drag)."""
    specs = [{"c": 100.0} for _ in range(12)]
    specs[5]["signal"] = True
    for k in range(6, 12):
        specs[k] = {"c": 100.0, "o": 100.0}
    # bar 9 rises THROUGH the target intrabar (open stays below it → no gap fill)
    specs[9] = {"c": 104.0, "o": 103.5, "h": 104.8, "l": 103.4}

    _set_costs(monkeypatch, costs="0")
    legacy_trades, _ = _run(_bars(specs), _strategy(max_hold=8))
    _set_costs(monkeypatch, costs="1", slip="5", comm="0.005", comm_min="1.0")
    cost_trades, _ = _run(_bars(specs), _strategy(max_hold=8))

    assert len(legacy_trades) == 1 and len(cost_trades) == 1
    assert cost_trades[0].pnl < legacy_trades[0].pnl, (
        f"costs must reduce PnL: legacy={legacy_trades[0].pnl:.2f} "
        f"vs costs={cost_trades[0].pnl:.2f}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
