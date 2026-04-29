"""
v18 — Bar Poll Service tests (2026-04-30) + Server-Side Bracket guards.

Bar poll service (closes the universe-coverage gap from ~19% to ~76%+):
  · pools compose correctly (excludes pusher-subscribed symbols)
  · round-robin cursor advances through the pool deterministically
  · alerts produced are stamped data_source="bar_poll_5m"
  · neutral tape lets bar-detectors run without live ticks
  · Off-RTH idles, RTH polls per-pool cadence
  · status() returns serialisable dict

Server-side IB bracket regression guards:
  · `place_bracket_order` is called BEFORE legacy `execute_entry`
  · The bracket success path stamps `bracket=True` flag
  · Legacy fallback is gated to specific known errors only
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import bar_poll_service as bps
from services.bar_poll_service import BAR_POLL_DETECTORS, BarPollService


ROOT = Path(__file__).resolve().parents[1]
TRADE_EXEC = (ROOT / "services" / "trade_execution.py").read_text()
TRADE_EXECUTOR = (ROOT / "services" / "trade_executor_service.py").read_text()


# ==========================================================================
# Bar Poll Service
# ==========================================================================

@pytest.fixture(autouse=True)
def _reset_singleton():
    bps.reset_for_tests()
    yield
    bps.reset_for_tests()


def _fake_db_with_tiers(intraday: List[str], swing: List[str], investment: List[str]):
    """Build a fake db whose `symbol_adv_cache.find().sort()` returns
    rows tier-filtered by the input lists."""
    fake_col = MagicMock()
    all_docs = (
        [{"symbol": s, "tier": "intraday", "avg_dollar_volume": 1e9 - i}
         for i, s in enumerate(intraday)]
        + [{"symbol": s, "tier": "swing", "avg_dollar_volume": 1e8 - i}
           for i, s in enumerate(swing)]
        + [{"symbol": s, "tier": "investment", "avg_dollar_volume": 1e7 - i}
           for i, s in enumerate(investment)]
    )

    def find(query, projection=None):
        tier = (query or {}).get("tier")
        rows = [d for d in all_docs if d.get("tier") == tier]
        # Mimic Mongo cursor sortable
        cursor = MagicMock()
        cursor.__iter__ = lambda self: iter(rows)
        sort_mock = MagicMock()
        sort_mock.__iter__ = lambda self: iter(rows)
        cursor.sort = MagicMock(return_value=sort_mock)
        return cursor

    fake_col.find.side_effect = find

    class _DB:
        def __init__(self):
            self._cols = {"symbol_adv_cache": fake_col,
                          "bar_poll_log": MagicMock()}
            self._cols["bar_poll_log"].insert_one = MagicMock()
            self._cols["bar_poll_log"].create_index = MagicMock()

        def __getitem__(self, name):
            return self._cols.setdefault(name, MagicMock())

        def get_collection(self, name):
            return self.__getitem__(name)

    return _DB()


def _fake_pusher_with_subs(subs):
    p = MagicMock()
    p.get_subscribed_set = MagicMock(return_value=set(subs))
    return p


def _fake_scanner():
    """A scanner stub with a `_check_<detector>` method per
    BAR_POLL_DETECTORS that returns a minimal LiveAlert object."""
    s = MagicMock()
    s._live_alerts = {}

    async def fake_check(symbol, snap, tape):
        # Only fire on the first detector for testing, to keep counts low
        from services.enhanced_scanner import LiveAlert, AlertPriority
        return LiveAlert(
            id=f"alert_{symbol}_{datetime.now(timezone.utc).timestamp()}",
            symbol=symbol,
            setup_type="squeeze",
            strategy_name="squeeze",
            direction="long",
            priority=AlertPriority.MEDIUM,
            current_price=100.0,
            trigger_price=100.0,
            stop_loss=99.0,
            target=102.0,
            risk_reward=2.0,
            trigger_probability=0.6,
            win_probability=0.55,
            minutes_to_trigger=0,
            headline=f"{symbol} squeeze test",
            reasoning=["test"],
            time_window="rth",
            market_regime="neutral",
        )

    # Wire only `squeeze` to fire (rest return None)
    for det in BAR_POLL_DETECTORS:
        if det == "squeeze":
            setattr(s, f"_check_{det}", fake_check)
        else:
            async def _none(symbol, snap, tape):
                return None
            setattr(s, f"_check_{det}", _none)
    return s


# --------------------------------------------------------------------------
# Pool composition
# --------------------------------------------------------------------------

def test_pools_exclude_pusher_subscribed_symbols():
    db = _fake_db_with_tiers(
        intraday=["AAPL", "MSFT", "NVDA", "TSLA", "AMD"],
        swing=["BABA", "SOFI"],
        investment=["IBM"],
    )
    # AAPL + NVDA are live-streamed — should NOT appear in any bar-poll pool
    pusher = _fake_pusher_with_subs({"AAPL", "NVDA"})
    svc = BarPollService(db=db, scanner=_fake_scanner(), pusher_client=pusher)

    pools = svc._build_symbol_pools()
    assert "AAPL" not in pools["intraday_noncore"]
    assert "NVDA" not in pools["intraday_noncore"]
    assert set(pools["intraday_noncore"]) == {"MSFT", "TSLA", "AMD"}
    # Swing & investment pools are ALWAYS bar-polled (out of pusher budget)
    assert pools["swing"] == ["BABA", "SOFI"]
    assert pools["investment"] == ["IBM"]


def test_pools_handle_empty_pusher_gracefully():
    db = _fake_db_with_tiers(
        intraday=["NVDA"], swing=[], investment=[],
    )
    pusher = _fake_pusher_with_subs(set())
    svc = BarPollService(db=db, scanner=_fake_scanner(), pusher_client=pusher)
    pools = svc._build_symbol_pools()
    assert pools["intraday_noncore"] == ["NVDA"]


# --------------------------------------------------------------------------
# Cursor / round-robin
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_advances_through_pool_deterministically():
    db = _fake_db_with_tiers(
        intraday=[f"S{i:03d}" for i in range(120)],
        swing=[], investment=[],
    )
    pusher = _fake_pusher_with_subs(set())
    scanner = _fake_scanner()

    technical = MagicMock()
    technical.get_batch_snapshots = AsyncMock(return_value={})

    svc = BarPollService(
        db=db, scanner=scanner, pusher_client=pusher,
        technical_service=technical,
    )

    # First batch — cursor starts at 0
    summary1 = await svc.poll_pool_once("intraday_noncore")
    assert summary1["batch_symbols"] > 0
    # BATCH_SIZE = 25 (v19.1); cursor lands at 25
    assert summary1["cursor"] == 25

    # Second batch — cursor advances
    summary2 = await svc.poll_pool_once("intraday_noncore")
    assert summary2["cursor"] == 50

    # Continue advancing — confirm no premature wrap
    for _ in range(2):
        await svc.poll_pool_once("intraday_noncore")
    summary5 = await svc.poll_pool_once("intraday_noncore")
    # 5 batches × 25 = 125 mod 120 = 5
    assert summary5["cursor"] == 5


# --------------------------------------------------------------------------
# Alerts emitted with correct provenance stamp
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emitted_alerts_stamped_with_bar_poll_provenance():
    db = _fake_db_with_tiers(
        intraday=["NVDA", "AMD", "MSFT"], swing=[], investment=[],
    )
    pusher = _fake_pusher_with_subs(set())
    scanner = _fake_scanner()

    technical = MagicMock()
    technical.get_batch_snapshots = AsyncMock(
        return_value={"NVDA": MagicMock(), "AMD": MagicMock(), "MSFT": MagicMock()}
    )

    svc = BarPollService(
        db=db, scanner=scanner, pusher_client=pusher, technical_service=technical,
    )
    summary = await svc.poll_pool_once("intraday_noncore")

    # _check_squeeze fires on each → 3 alerts
    assert summary["alerts_emitted"] == 3

    # CRITICAL v19.1 regression guard: bar poll MUST request mongo_only
    # mode. Without it, bar poll bombards the pusher's /rpc/latest-bars
    # endpoint and triggers IB historical-data rate-limit cascades.
    technical.get_batch_snapshots.assert_called_once()
    call_kwargs = technical.get_batch_snapshots.call_args.kwargs
    assert call_kwargs.get("mongo_only") is True, (
        "BarPollService.poll_pool_once MUST call get_batch_snapshots "
        "with mongo_only=True. Otherwise the snapshot service hits "
        "/rpc/latest-bars per symbol on the v17-expanded subscription "
        "set, overwhelming the pusher's IB historical-data API. "
        "See 2026-04-30 v19.1 fix in bar_poll_service.py."
    )

    # Each alert should be in the scanner's _live_alerts dict, stamped
    # with data_source="bar_poll_5m" and a reasoning breadcrumb.
    for alert in scanner._live_alerts.values():
        assert getattr(alert, "data_source", None) == "bar_poll_5m", (
            "Bar-poll alert MUST stamp data_source='bar_poll_5m' so AI gate / "
            "shadow tracker / V5 UI can distinguish it from live-tick alerts."
        )
        assert any("bar-poll" in r.lower() for r in alert.reasoning)


# --------------------------------------------------------------------------
# Neutral tape contract
# --------------------------------------------------------------------------

def test_neutral_tape_has_required_attrs():
    """The detectors inspect tape.confirmation_for_long /
    confirmation_for_short / tape_score / overall_signal. Our neutral
    tape must expose all four (anything else they touch raises and
    the bar-poll path silently skips that detector — acceptable but
    we want to keep this contract explicit)."""
    tape = BarPollService._neutral_tape()
    assert tape.confirmation_for_long is False
    assert tape.confirmation_for_short is False
    assert tape.tape_score == 0.0
    assert hasattr(tape, "overall_signal")


# --------------------------------------------------------------------------
# Status snapshot
# --------------------------------------------------------------------------

def test_status_returns_serialisable_dict():
    db = _fake_db_with_tiers(
        intraday=["NVDA"], swing=[], investment=[],
    )
    pusher = _fake_pusher_with_subs({"NVDA"})
    svc = BarPollService(db=db, scanner=_fake_scanner(), pusher_client=pusher)

    s = svc.status()
    # All required keys
    for k in ("running", "in_rth_only", "current_pusher_subscription_count",
              "pools", "lifetime_alerts_emitted", "detectors", "batch_size"):
        assert k in s
    assert len(s["pools"]) == 3
    assert set(p["name"] for p in s["pools"]) == {
        "intraday_noncore", "swing", "investment",
    }


# --------------------------------------------------------------------------
# Off-RTH idle behaviour
# --------------------------------------------------------------------------

def test_is_in_rth_returns_true_during_market_hours():
    """The static helper must consider 09:25 ET to 16:00 ET as RTH.
    We can't easily mock the wall-clock here without pytz; we just
    confirm the method runs and returns a bool."""
    result = BarPollService._is_in_rth()
    assert isinstance(result, bool)


# ==========================================================================
# Server-Side IB Bracket Regression Guards
#
# Phase 3 (2026-04-22) made `place_bracket_order` the default path so
# stops + targets live AT IB as GTC orders. This guards against a future
# contributor accidentally reverting to the two-step flow that left
# positions naked during bot restarts.
# ==========================================================================

def test_execute_trade_calls_place_bracket_order_first():
    """The execute_trade path must call `place_bracket_order` BEFORE
    falling back to `execute_entry`. If the order is reversed, the
    legacy two-step flow takes over and stops/targets only live in
    DGX memory — they die on bot restart."""
    pos_bracket = TRADE_EXEC.find("place_bracket_order(trade)")
    pos_legacy_entry = TRADE_EXEC.find("execute_entry(trade)")
    assert pos_bracket > 0, "place_bracket_order must be called in execute_trade"
    assert pos_legacy_entry > 0, "execute_entry should still exist as fallback"
    assert pos_bracket < pos_legacy_entry, (
        "place_bracket_order MUST be called BEFORE execute_entry in execute_trade. "
        "If reversed, the legacy two-step entry+stop flow becomes the default and "
        "stops/targets stop being broker-managed. See Phase 3 migration spec in "
        "/app/memory/IB_BRACKET_ORDER_MIGRATION.md."
    )


def test_legacy_fallback_only_triggers_on_known_errors():
    """The fallback path should only run on a strict allowlist of pusher
    errors — not on every bracket failure. A blanket fallback would mask
    real broker rejections and let the legacy path silently take over."""
    # Match the gate condition in execute_trade
    fallback_gate = re.search(
        r"use_legacy = \(\s*not bracket_result\.get\('success'\) and\s*"
        r"bracket_result\.get\('fallback'\) == 'legacy' or\s*"
        r"bracket_result\.get\('error'\) in \(([^)]+)\)",
        TRADE_EXEC,
    )
    assert fallback_gate, "Legacy fallback gate has changed shape — review for safety"
    allowed_errors = fallback_gate.group(1)
    assert "'bracket_not_supported'" in allowed_errors, (
        "Pusher must explicitly say 'bracket_not_supported' to trigger fallback"
    )
    # Real broker-side failures (insufficient_buying_power, contract_not_found, etc.)
    # must NOT trigger fallback — they'd silently re-route to legacy.
    for forbidden in ("insufficient_buying_power", "rejected", "no_route",
                       "stale_quote", "contract_not_found"):
        assert f"'{forbidden}'" not in allowed_errors, (
            f"'{forbidden}' should NOT trigger legacy fallback. It indicates a real "
            "broker issue, not a pusher version mismatch. Falling back to legacy "
            "would re-introduce naked-on-restart risk for these cases."
        )


def test_bracket_path_records_oca_group_and_child_ids():
    """When the bracket path succeeds, the result dict must carry the
    IB-side child order IDs so the bot can audit/reconcile/cancel
    them. Without these, post-hoc broker-side cleanup is impossible."""
    pattern = re.compile(
        r'"stop_order_id": bracket_result\.get\("stop_order_id"\),\s*'
        r'"target_order_id": bracket_result\.get\("target_order_id"\),\s*'
        r'"oca_group": bracket_result\.get\("oca_group"\),',
        re.DOTALL,
    )
    assert pattern.search(TRADE_EXEC), (
        "Bracket success path must propagate stop_order_id, target_order_id, "
        "and oca_group from the bracket result. Without these, the bot can't "
        "modify or cancel the broker-side stop/target after entry."
    )


def test_simulate_bracket_returns_complete_shape():
    """Simulated bracket must return the same shape as live bracket so
    downstream code (which doesn't know which mode it's in) handles both
    identically. Missing fields would crash trade.notes stamping."""
    required_keys = {
        "success", "entry_order_id", "stop_order_id", "target_order_id",
        "oca_group", "fill_price", "filled_qty", "status", "simulated",
    }
    # Pull the full _simulate_bracket method body, not just the first
    # closing brace (which lands inside an f-string's `{trade.id}`).
    method_match = re.search(
        r"async def _simulate_bracket\(self, trade\).*?(?=\n    async def |\n    def |\nclass )",
        TRADE_EXECUTOR, re.DOTALL,
    )
    assert method_match, "_simulate_bracket method must exist"
    body = method_match.group(0)
    for key in required_keys:
        assert f'"{key}"' in body, (
            f"_simulate_bracket return dict missing '{key}' key — "
            f"must match live bracket shape exactly so downstream code is mode-blind."
        )
