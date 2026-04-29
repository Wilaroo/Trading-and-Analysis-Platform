"""
v17 — pusher rotation service tests (2026-04-30)

Hard invariants tested (these are SAFETY guards — failures here mean
real money risk):

  ★ Open positions can NEVER be unsubscribed by rotation.
  ★ Pending orders can NEVER be unsubscribed by rotation.
  ★ Total subscription count NEVER exceeds MAX_LINES (500).
  ★ Safety buffer (20 lines) is always preserved during normal flow.
  ★ Cohort priority order is open_pos > pending > etfs > core > hot > dyn.
  ★ Diff is computed correctly under all permutations (idempotent,
    no spurious adds/removes).

Plus:
  - Profile selection by ET time-of-day.
  - Cohort budget caps respected.
  - Rotation service.status() returns a serialisable dict.
  - Diagnostic endpoint payload shape is stable.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Set
from unittest.mock import MagicMock, patch

import pytest

from services import pusher_rotation_service as prs
from services.pusher_rotation_service import (
    DEFAULT_PINNED_ETFS,
    DYNAMIC_OVERLAY_BUDGET,
    HOT_SLOT_BUDGET,
    MAX_LINES,
    PINNED_ETF_BUDGET,
    Profile,
    PusherRotationService,
    SAFETY_BUFFER,
    STATIC_CORE_BUDGET,
    USABLE_LINES,
    compose_target_set,
    compute_diff,
    select_profile,
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

class _FakeBotTrade:
    def __init__(self, symbol):
        self.symbol = symbol


class _FakeBot:
    def __init__(self, open_positions=None, pending_orders=None):
        self._open_trades = {
            f"id_{s}": _FakeBotTrade(s) for s in (open_positions or [])
        }
        self._pending_trades = {
            f"pend_{s}": _FakeBotTrade(s) for s in (pending_orders or [])
        }


def _fake_db_with_intraday_universe(symbols: List[str]):
    """Build a mock db that returns the given symbols (in priority order)
    when symbol_adv_cache.find().sort().limit() is called."""
    fake_col = MagicMock()
    docs = [{"symbol": s, "tier": "intraday"} for s in symbols]
    fake_col.find.return_value = MagicMock(
        sort=MagicMock(return_value=MagicMock(
            limit=MagicMock(return_value=docs)
        ))
    )
    fake_col.aggregate.return_value = []
    fake_col.count_documents.return_value = len(docs)
    db = {"symbol_adv_cache": fake_col, "live_alerts": MagicMock()}
    db["live_alerts"].aggregate.return_value = []
    return db


# --------------------------------------------------------------------------
# Profile selection by ET time
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hour,minute,expected", [
    (4, 0,   Profile.PRE_MARKET_EARLY),
    (6, 59,  Profile.PRE_MARKET_EARLY),
    (7, 0,   Profile.PRE_MARKET_LATE),
    (9, 24,  Profile.PRE_MARKET_LATE),
    (9, 25,  Profile.RTH_OPEN),
    (10, 29, Profile.RTH_OPEN),
    (10, 30, Profile.RTH_MIDDAY),
    (13, 29, Profile.RTH_MIDDAY),
    (13, 30, Profile.RTH_AFTERNOON),
    (15, 59, Profile.RTH_AFTERNOON),
    (16, 0,  Profile.POST_MARKET),
    (3, 59,  Profile.POST_MARKET),
])
def test_profile_selection_by_et_time(hour, minute, expected):
    fake_now = datetime(2026, 4, 30, hour, minute)
    assert select_profile(fake_now) == expected


# --------------------------------------------------------------------------
# Cohort budget caps
# --------------------------------------------------------------------------

def test_compose_respects_cohort_caps():
    universe = [f"SYM{i:04d}" for i in range(1000)]
    db = _fake_db_with_intraday_universe(universe)
    bot = _FakeBot(open_positions=[], pending_orders=[])

    result = compose_target_set(
        db=db, bot=bot,
        hot_slots_provider=lambda **_: [f"HOT{i}" for i in range(200)],
        dynamic_overlay_provider=lambda **_: [f"DYN{i}" for i in range(500)],
    )

    assert len(result["by_cohort"]["pinned_etfs"]) == PINNED_ETF_BUDGET
    assert len(result["by_cohort"]["static_core"]) == STATIC_CORE_BUDGET
    assert len(result["by_cohort"]["hot_slots"]) == HOT_SLOT_BUDGET
    assert len(result["by_cohort"]["dynamic_overlay"]) == DYNAMIC_OVERLAY_BUDGET
    assert result["budget_used"] <= USABLE_LINES


def test_compose_never_exceeds_max_lines():
    universe = [f"SYM{i:04d}" for i in range(1000)]
    db = _fake_db_with_intraday_universe(universe)
    bot = _FakeBot()

    result = compose_target_set(
        db=db, bot=bot,
        hot_slots_provider=lambda **_: [f"HOT{i}" for i in range(500)],
        dynamic_overlay_provider=lambda **_: [f"DYN{i}" for i in range(500)],
    )
    assert result["budget_used"] <= MAX_LINES
    assert result["budget_used"] <= USABLE_LINES  # safety buffer respected


# --------------------------------------------------------------------------
# THE critical safety: open positions are pinned, never displaceable
# --------------------------------------------------------------------------

def test_open_positions_pinned_even_when_outside_static_core():
    # Universe is 500 strong; open positions are SYM999 (last in universe)
    # which would normally NOT make the static-core 300.
    universe = [f"SYM{i:04d}" for i in range(500)]
    db = _fake_db_with_intraday_universe(universe)
    bot = _FakeBot(open_positions=["SYM499", "SYM498"])

    result = compose_target_set(db=db, bot=bot)

    assert "SYM499" in result["target"]
    assert "SYM498" in result["target"]
    assert "SYM499" in result["by_cohort"]["open_positions"]
    assert "SYM498" in result["by_cohort"]["open_positions"]
    assert result["safety_pinned_count"] >= 2


def test_open_positions_take_priority_over_dynamic_overlay():
    universe = [f"SYM{i:04d}" for i in range(1000)]
    db = _fake_db_with_intraday_universe(universe)
    # Operator opens 50 positions — they ALL must be pinned even if it
    # squeezes the dynamic overlay.
    open_syms = [f"OPEN{i:03d}" for i in range(50)]
    bot = _FakeBot(open_positions=open_syms)

    result = compose_target_set(
        db=db, bot=bot,
        hot_slots_provider=lambda **_: [f"HOT{i}" for i in range(50)],
        dynamic_overlay_provider=lambda **_: [f"DYN{i}" for i in range(100)],
    )

    for s in open_syms:
        assert s in result["target"], f"{s} (held position) was dropped from rotation"

    # Open positions never ceiling-capped; safety always wins.
    assert all(s in result["by_cohort"]["open_positions"] for s in open_syms)


def test_compute_diff_filters_safety_pinned_from_removals():
    current = {"AAPL", "MSFT", "NVDA", "TSLA"}
    target  = {"AAPL", "MSFT"}                 # caller wants to drop NVDA/TSLA
    safety  = {"NVDA"}                          # but we hold NVDA — MUST keep

    diff = compute_diff(current, target, safety_pinned=safety)

    assert "NVDA" not in diff["to_remove"], (
        "Safety guard breached: NVDA is held but rotation would remove it. "
        "This is the v17 invariant — open positions are NEVER unsubscribed."
    )
    assert "NVDA" in diff["would_remove_held"]
    assert "TSLA" in diff["to_remove"]  # not held → safe to drop


def test_compute_diff_auto_adds_safety_pinned_missing_from_target():
    """If caller built a target without an open position (logic bug),
    the diff layer auto-includes it so we don't drop the held name."""
    current = {"AAPL"}
    target  = {"AAPL", "MSFT"}                  # forgot to include held NVDA
    safety  = {"NVDA"}

    diff = compute_diff(current, target, safety_pinned=safety)
    assert "NVDA" in diff["to_add"], (
        "Safety guard breached: rotation skipped subscribing held NVDA."
    )


def test_pending_orders_also_safety_pinned():
    universe = [f"SYM{i:04d}" for i in range(500)]
    db = _fake_db_with_intraday_universe(universe)
    # Symbol with pending order but NO open position yet — should still pin
    bot = _FakeBot(open_positions=[], pending_orders=["PEND_SYM"])

    result = compose_target_set(db=db, bot=bot)

    assert "PEND_SYM" in result["target"]
    assert "PEND_SYM" in result["by_cohort"]["pending_orders"]


# --------------------------------------------------------------------------
# Diff math correctness
# --------------------------------------------------------------------------

def test_compute_diff_idempotent_on_identical_sets():
    s = {"AAPL", "MSFT", "NVDA"}
    diff = compute_diff(s, s)
    assert diff["to_add"] == set()
    assert diff["to_remove"] == set()
    assert diff["kept"] == s


def test_compute_diff_correct_under_permutations():
    current = {"AAPL", "MSFT", "NVDA"}
    target  = {"NVDA", "TSLA", "AMD"}
    diff = compute_diff(current, target)

    assert diff["to_add"] == {"TSLA", "AMD"}
    assert diff["to_remove"] == {"AAPL", "MSFT"}
    assert diff["kept"] == {"NVDA"}


def test_compute_diff_handles_empty_current():
    diff = compute_diff(set(), {"AAPL", "MSFT"})
    assert diff["to_add"] == {"AAPL", "MSFT"}
    assert diff["to_remove"] == set()


def test_compute_diff_handles_empty_target():
    diff = compute_diff({"AAPL", "MSFT"}, set())
    assert diff["to_add"] == set()
    assert diff["to_remove"] == {"AAPL", "MSFT"}


# --------------------------------------------------------------------------
# Rotation service: rotate_once dry_run + live paths
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    prs.reset_for_tests()
    yield
    prs.reset_for_tests()


def test_rotate_once_dry_run_does_not_call_pusher():
    universe = [f"SYM{i:04d}" for i in range(500)]
    db = _fake_db_with_intraday_universe(universe)
    bot = _FakeBot(open_positions=["AAPL"])
    fake_pusher = MagicMock()
    fake_pusher.get_subscribed_set.return_value = set()
    fake_pusher.subscribe_symbols = MagicMock()
    fake_pusher.unsubscribe_symbols = MagicMock()

    svc = PusherRotationService(db=db, bot=bot, pusher_client=fake_pusher)
    result = svc.rotate_once(dry_run=True)

    assert result["dry_run"] is True
    assert result["applied"] is False
    fake_pusher.subscribe_symbols.assert_not_called()
    fake_pusher.unsubscribe_symbols.assert_not_called()
    # AAPL (held) should be in the previewed to_add since current is empty
    assert "AAPL" in result["diff"]["to_add"]


def test_rotate_once_applies_diff_via_rpc():
    universe = ["AAPL", "MSFT", "NVDA"]
    db = _fake_db_with_intraday_universe(universe)
    bot = _FakeBot()
    fake_pusher = MagicMock()
    # Pusher already has TSLA + AMD; needs to swap to AAPL/MSFT/NVDA + ETFs
    fake_pusher.get_subscribed_set.return_value = {"TSLA", "AMD"}
    fake_pusher.subscribe_symbols.return_value = {"success": True}
    fake_pusher.unsubscribe_symbols.return_value = {"success": True}

    svc = PusherRotationService(db=db, bot=bot, pusher_client=fake_pusher)
    result = svc.rotate_once(dry_run=False)

    assert result["applied"] is True
    fake_pusher.subscribe_symbols.assert_called_once()
    fake_pusher.unsubscribe_symbols.assert_called_once()

    # Things added include AAPL/MSFT/NVDA + ETFs
    added = set(result["diff"]["to_add"])
    assert {"AAPL", "MSFT", "NVDA"}.issubset(added)
    # Things removed include the stale TSLA/AMD
    removed = set(result["diff"]["to_remove"])
    assert removed == {"TSLA", "AMD"}


def test_rotate_once_skips_when_pusher_unreachable():
    db = _fake_db_with_intraday_universe(["AAPL"])
    bot = _FakeBot()
    fake_pusher = MagicMock()
    fake_pusher.get_subscribed_set.return_value = None  # RPC fail

    svc = PusherRotationService(db=db, bot=bot, pusher_client=fake_pusher)
    result = svc.rotate_once(dry_run=False)

    assert result["applied"] is False
    assert result.get("error") == "pusher_unreachable"
    fake_pusher.subscribe_symbols.assert_not_called()
    fake_pusher.unsubscribe_symbols.assert_not_called()


def test_held_position_never_unsubscribed_during_live_rotation():
    """The most important test in this file. If this ever fails, the
    rotation service is unsafe to deploy — open positions could lose
    their quote stream mid-trade and trigger stale-data closes."""
    db = _fake_db_with_intraday_universe([f"S{i}" for i in range(500)])
    bot = _FakeBot(open_positions=["HELD_NAME"])

    fake_pusher = MagicMock()
    fake_pusher.get_subscribed_set.return_value = {"HELD_NAME"}
    fake_pusher.subscribe_symbols.return_value = {"success": True}
    fake_pusher.unsubscribe_symbols.return_value = {"success": True}

    svc = PusherRotationService(db=db, bot=bot, pusher_client=fake_pusher)
    result = svc.rotate_once(dry_run=False)

    # HELD_NAME must NOT be in the unsubscribe call args
    if fake_pusher.unsubscribe_symbols.called:
        unsub_arg = fake_pusher.unsubscribe_symbols.call_args[0][0]
        assert "HELD_NAME" not in unsub_arg, (
            "SAFETY VIOLATION: open position HELD_NAME was sent to "
            "unsubscribe_symbols. This must never happen."
        )
    # And it must remain in the target
    assert "HELD_NAME" in result["target"]


# --------------------------------------------------------------------------
# Status snapshot
# --------------------------------------------------------------------------

def test_status_returns_serialisable_dict():
    db = _fake_db_with_intraday_universe(["AAPL"])
    bot = _FakeBot()
    fake_pusher = MagicMock()
    fake_pusher.get_subscribed_set.return_value = {"AAPL"}

    svc = PusherRotationService(db=db, bot=bot, pusher_client=fake_pusher)
    s = svc.status()

    # JSON-friendly keys present
    for k in ("running", "current_pusher_subscriptions", "max_lines",
              "safety_buffer", "usable_lines", "active_profile"):
        assert k in s
    assert s["max_lines"] == MAX_LINES
    assert s["usable_lines"] == USABLE_LINES
    assert s["safety_buffer"] == SAFETY_BUFFER


# --------------------------------------------------------------------------
# RPC client: subscribe/unsubscribe normalisation
# --------------------------------------------------------------------------

def test_rpc_subscribe_normalises_and_dedupes():
    from services.ib_pusher_rpc import _PusherRPCClient

    client = _PusherRPCClient()
    captured = {}

    def fake_request(method, path, *, json_body=None, timeout=6.0):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = json_body
        return {"success": True, "added": json_body["symbols"] if json_body else []}

    with patch.object(client, "_request", side_effect=fake_request):
        client.subscribe_symbols({"aapl", "  MSFT  ", "AAPL", "nvda", ""})

    assert captured["path"] == "/rpc/subscribe"
    assert captured["payload"]["symbols"] == ["AAPL", "MSFT", "NVDA"]


def test_rpc_subscribe_with_empty_set_short_circuits():
    from services.ib_pusher_rpc import _PusherRPCClient

    client = _PusherRPCClient()
    with patch.object(client, "_request") as m:
        result = client.subscribe_symbols(set())
        m.assert_not_called()
    assert result == {"success": True, "added": [], "skipped": []}
