"""v19.34.41 — Proactive Coach service regression tests.

Pure-function tests over `evaluate_trade()`. Pin the math for each of
the four coachable conditions plus stale-state dropping behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from services.proactive_coach_service import (
    ProactiveCoachService,
    SUGGESTION_TTL_S,
    evaluate_trade,
)


@dataclass
class _StubTrade:
    id: str = "TID-1"
    symbol: str = "DDOG"
    direction_value: str = "long"
    shares: int = 100
    entry_price: float = 200.0
    fill_price: float = 200.0
    stop_price: float = 196.0
    current_price: float = 200.0
    target_prices: List[float] = field(default_factory=lambda: [208.0, 216.0])

    @property
    def direction(self):
        return type("D", (), {"value": self.direction_value})()


# ─────────────────────── move_stop_to_breakeven ────────────────────────


def test_breakeven_long_at_1R():
    """Long up exactly 1R → breakeven suggestion fires."""
    t = _StubTrade(current_price=204.0)  # +$4 / $4 risk = 1R
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "move_stop_to_breakeven"]
    assert len(sugs) == 1
    assert sugs[0].proposed_action["payload"]["new_stop"] == 200.0
    assert sugs[0].severity == "suggest"


def test_breakeven_skipped_when_below_1R():
    t = _StubTrade(current_price=202.0)  # +$2 / $4 risk = 0.5R
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "move_stop_to_breakeven"]
    assert sugs == []


def test_breakeven_skipped_when_stop_already_at_or_above_be():
    """If operator already moved stop to BE, don't re-suggest."""
    t = _StubTrade(current_price=205.0, stop_price=200.0)
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "move_stop_to_breakeven"]
    assert sugs == []


def test_breakeven_short_mirror():
    """Short up 1R → suggest stop down to entry."""
    t = _StubTrade(direction_value="short", entry_price=250.0, fill_price=250.0,
                   stop_price=255.0, current_price=245.0,
                   target_prices=[240.0, 230.0])
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "move_stop_to_breakeven"]
    assert len(sugs) == 1
    assert sugs[0].proposed_action["payload"]["new_stop"] == 250.0


# ─────────────────────── tighten_stop_runner ────────────────────────


def test_runner_tighten_long_at_2R():
    """Long up 2R → trail stop to current - 0.5R."""
    t = _StubTrade(current_price=208.0)  # +$8 / $4 = 2R
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "tighten_stop_runner"]
    assert len(sugs) == 1
    # current=208, risk=4, new_stop = 208 - 2 = 206
    assert sugs[0].proposed_action["payload"]["new_stop"] == 206.0


def test_runner_skipped_when_below_2R():
    t = _StubTrade(current_price=205.0)  # 1.25R
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "tighten_stop_runner"]
    assert sugs == []


# ─────────────────────── take_partial_winner ────────────────────────


def test_partial_at_first_target():
    """Within 0.5% of first target → partial close suggestion."""
    t = _StubTrade(current_price=207.5)  # 0.24% below $208 target
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "take_partial_winner"]
    assert len(sugs) == 1
    # Half of 100 shares
    assert sugs[0].proposed_action["payload"]["partial_close_shares"] == 50


def test_partial_skipped_when_far_from_target():
    t = _StubTrade(current_price=204.0)
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "take_partial_winner"]
    assert sugs == []


# ─────────────────────── stop_proximity_warning ────────────────────────


def test_stop_proximity_warning_long():
    """Long current within 0.5% of stop → warning."""
    t = _StubTrade(current_price=196.5)  # 0.25% above $196 stop
    sugs = [s for s in evaluate_trade(t) if s.suggestion_type == "stop_proximity_warning"]
    assert len(sugs) == 1
    assert sugs[0].severity == "warn"
    assert sugs[0].proposed_action is None  # info-only, operator decides


# ─────────────────────── full state machine ────────────────────────


def test_zero_shares_yields_no_suggestions():
    """Closed trades (0 shares left) must be silent."""
    t = _StubTrade(shares=0)
    assert evaluate_trade(t) == []


def test_service_singleton_caches_and_lists():
    """ProactiveCoachService.scan_once + .all() round-trip."""
    coach = ProactiveCoachService()  # local instance, not the singleton

    class _BotStub:
        _open_trades = {"TID-1": _StubTrade(current_price=204.0)}

    n = coach.scan_once(_BotStub())
    assert n >= 1, "expected at least one suggestion (breakeven) for +1R long"
    snapshot = coach.all()
    assert isinstance(snapshot, list)
    assert all(isinstance(s, dict) for s in snapshot)
    assert all(set(s.keys()) >= {"id", "trade_id", "symbol", "headline", "severity"} for s in snapshot)


def test_service_drops_stale_trades_on_rescan():
    """If a trade closes, its suggestions must vanish on the next scan."""
    coach = ProactiveCoachService()

    class _Bot1:
        _open_trades = {"TID-1": _StubTrade(current_price=204.0)}

    coach.scan_once(_Bot1())
    assert len(coach.all()) >= 1

    # Trade closed → empty open_trades → suggestions gone.
    class _Bot2:
        _open_trades = {}

    coach.scan_once(_Bot2())
    assert coach.all() == []


def test_router_endpoint_registered():
    """/api/coach/proactive-suggestions must be discoverable."""
    from server import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/coach/proactive-suggestions" in paths
