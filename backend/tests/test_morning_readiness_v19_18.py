"""
v19.18 — Morning Readiness aggregator (2026-04-30).

Single-call "is the bot ready for fully automated trading today?"
endpoint mounted at GET /api/system/morning-readiness.

Aggregates 5 checks rolled into one verdict (green/yellow/red):
  1. backfill_data_fresh
  2. ib_pipeline_alive
  3. trading_bot_configured
  4. scanner_running
  5. open_positions_clean

Tests pin:
  - The 5-check structure stays intact.
  - The verdict aggregation honours the green<yellow<red precedence.
  - Each individual check handles missing/broken dependencies without
    raising (the operator-facing endpoint must never 500).
  - The summary line format is stable for Slack DM consumption.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class _FakeBot:
    _SENTINEL = object()
    def __init__(self, *, eod_enabled=True, eod_hour=15, eod_minute=55,
                 risk_params=_SENTINEL, open_trades=None):
        self._eod_close_enabled = eod_enabled
        self._eod_close_hour = eod_hour
        self._eod_close_minute = eod_minute
        self._risk_params = (
            risk_params if risk_params is not self._SENTINEL
            else {"starting_capital": 250000}
        )
        self._open_trades = open_trades or {}


class _FakeTrade:
    def __init__(self, symbol="AAPL", close_at_eod=True, opened_at=None,
                 shares=100):
        self.symbol = symbol
        self.close_at_eod = close_at_eod
        self.opened_at = opened_at
        self.shares = shares
        self.remaining_shares = shares


class _FakeMongoCol:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find_one(self, query=None, projection=None, sort=None):
        # Sort by 'date' desc if requested; tiny implementation.
        if sort and len(sort) >= 1 and sort[0][0] == "date" and sort[0][1] == -1:
            for d in sorted(self.docs, key=lambda x: x.get("date", ""),
                            reverse=True):
                return d
        elif sort and len(sort) >= 1 and sort[0][0] == "completed_at":
            for d in sorted(self.docs,
                            key=lambda x: x.get("completed_at", ""),
                            reverse=(sort[0][1] == -1)):
                return d
        return self.docs[0] if self.docs else None


class _FakeMongoDB:
    """Minimal mongo stub — only the calls morning_readiness uses."""
    def __init__(self, *, daily_bars=None, queue_completed=None,
                 has_pusher_heartbeat=False, pusher_age_s=10):
        self._daily = _FakeMongoCol(daily_bars or [])
        self._queue = _FakeMongoCol(queue_completed or [])
        self._has_pusher = has_pusher_heartbeat
        self._pusher_age_s = pusher_age_s
        self._cols = {
            "ib_historical_data": self._daily,
            "historical_data_requests": self._queue,
        }
        if self._has_pusher:
            now = datetime.now(timezone.utc)
            ts = now - timedelta(seconds=self._pusher_age_s)
            self._cols["pusher_heartbeat"] = _FakeMongoCol([{"ts": ts}])

    def __getitem__(self, name):
        if name not in self._cols:
            return _FakeMongoCol([])
        return self._cols[name]

    def list_collection_names(self):
        return list(self._cols.keys())


def _today_iso():
    return date.today().isoformat()


def _yesterday_iso():
    return (date.today() - timedelta(days=1)).isoformat()


# --------------------------------------------------------------------------
# 1. backfill_data_fresh
# --------------------------------------------------------------------------

def test_backfill_data_fresh_green_when_all_critical_have_expected_session():
    """When all 10 critical symbols have a daily bar at the v19.17
    expected session date, status is green."""
    from services.morning_readiness_service import (
        _check_backfill_data_fresh, _CRITICAL_SYMBOLS,
    )

    # Mock the v19.17 helper to return a fixed expected session.
    expected = date(2026, 4, 28)
    fake_collector = MagicMock()
    fake_collector._expected_latest_session_date.return_value = expected

    daily_bars = []
    for sym in _CRITICAL_SYMBOLS:
        # Use a fake col per symbol — the real find_one filters by symbol.
        daily_bars.append({"symbol": sym, "bar_size": "1 day",
                           "date": expected.isoformat()})

    class _PerSymbolCol:
        def find_one(self, query=None, projection=None, sort=None):
            wanted = query.get("symbol")
            for d in daily_bars:
                if d["symbol"] == wanted:
                    return d
            return None

    db = MagicMock()
    db.__getitem__.return_value = _PerSymbolCol()

    with patch(
        "services.ib_historical_collector.get_ib_collector",
        return_value=fake_collector,
    ):
        out = _check_backfill_data_fresh(db)
    assert out["status"] == "green"
    assert out["expected_session"] == expected.isoformat()


def test_backfill_data_fresh_red_when_critical_symbol_stale():
    """If even ONE critical symbol's daily bar is older than the
    v19.17 expected session, fire red."""
    from services.morning_readiness_service import (
        _check_backfill_data_fresh, _CRITICAL_SYMBOLS,
    )

    expected = date(2026, 4, 28)
    fake_collector = MagicMock()
    fake_collector._expected_latest_session_date.return_value = expected

    # All fresh except NVDA.
    bars = {sym: expected.isoformat() for sym in _CRITICAL_SYMBOLS}
    bars["NVDA"] = (expected - timedelta(days=2)).isoformat()

    class _Col:
        def find_one(self, query=None, projection=None, sort=None):
            sym = query.get("symbol")
            return {"date": bars[sym]} if sym in bars else None

    db = MagicMock()
    db.__getitem__.return_value = _Col()

    with patch(
        "services.ib_historical_collector.get_ib_collector",
        return_value=fake_collector,
    ):
        out = _check_backfill_data_fresh(db)
    assert out["status"] == "red"
    stale = out["stale_symbols"]
    assert len(stale) == 1
    assert stale[0]["symbol"] == "NVDA"
    assert stale[0]["days_behind"] == 2
    # Operator-facing fix message is included.
    assert "Collect Data" in out["fix"]


def test_backfill_data_fresh_handles_missing_bars():
    """Symbols without ANY daily bar in Mongo are flagged stale."""
    from services.morning_readiness_service import _check_backfill_data_fresh

    expected = date(2026, 4, 28)
    fake_collector = MagicMock()
    fake_collector._expected_latest_session_date.return_value = expected

    class _Col:
        def find_one(self, query=None, projection=None, sort=None):
            return None  # nothing in Mongo

    db = MagicMock()
    db.__getitem__.return_value = _Col()

    with patch(
        "services.ib_historical_collector.get_ib_collector",
        return_value=fake_collector,
    ):
        out = _check_backfill_data_fresh(db)
    assert out["status"] == "red"
    assert all(s["last"] is None for s in out["stale_symbols"])


# --------------------------------------------------------------------------
# 3. trading_bot_configured
# --------------------------------------------------------------------------

def test_trading_bot_configured_green_with_v19_14_defaults():
    """Bot with EOD enabled at 15:55 + risk_params populated → green."""
    from services.morning_readiness_service import _check_trading_bot_configured

    bot = _FakeBot(eod_enabled=True, eod_hour=15, eod_minute=55,
                   risk_params={"starting_capital": 250_000,
                                "max_notional_per_trade_usd": 100_000})
    out = _check_trading_bot_configured(MagicMock(), bot=bot)
    assert out["status"] == "green"
    assert out["eod_window_et"] == "15:55"
    assert out["starting_capital"] == 250_000


def test_trading_bot_configured_red_when_eod_disabled():
    """Operator-disabled EOD → autopilot RED."""
    from services.morning_readiness_service import _check_trading_bot_configured

    bot = _FakeBot(eod_enabled=False)
    out = _check_trading_bot_configured(MagicMock(), bot=bot)
    assert out["status"] == "red"
    assert "DISABLED" in out["detail"]


def test_trading_bot_configured_yellow_when_eod_drifted_from_default():
    """EOD set to 15:30 (way too early) → yellow warning."""
    from services.morning_readiness_service import _check_trading_bot_configured

    bot = _FakeBot(eod_enabled=True, eod_hour=15, eod_minute=30)
    out = _check_trading_bot_configured(MagicMock(), bot=bot)
    assert out["status"] == "yellow"
    assert "unusual" in out["detail"]


def test_trading_bot_configured_red_when_risk_params_missing():
    """No risk_params → autopilot RED."""
    from services.morning_readiness_service import _check_trading_bot_configured

    bot = _FakeBot(risk_params={})
    out = _check_trading_bot_configured(MagicMock(), bot=bot)
    assert out["status"] == "red"


# --------------------------------------------------------------------------
# 5. open_positions_clean
# --------------------------------------------------------------------------

def test_open_positions_clean_green_with_no_carryovers():
    from services.morning_readiness_service import _check_open_positions_clean

    bot = _FakeBot(open_trades={
        "T1": _FakeTrade(symbol="AAPL", close_at_eod=True,
                         opened_at=datetime.now(timezone.utc)),
        "T2": _FakeTrade(symbol="NVDA", close_at_eod=False,
                         opened_at=datetime.now(timezone.utc)
                                   - timedelta(days=3)),  # swing — fine
    })
    out = _check_open_positions_clean(MagicMock(), bot=bot)
    assert out["status"] == "green"
    assert out["swing_holding"] == 1


def test_open_positions_clean_red_when_intraday_carried_overnight():
    """An intraday trade opened YESTERDAY that's still open today is
    a v19.14 EOD failure — must surface as red."""
    from services.morning_readiness_service import _check_open_positions_clean

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    bot = _FakeBot(open_trades={
        "T1": _FakeTrade(symbol="AAPL", close_at_eod=True,
                         opened_at=yesterday),
    })
    out = _check_open_positions_clean(MagicMock(), bot=bot)
    assert out["status"] == "red"
    assert len(out["stuck_positions"]) == 1
    assert out["stuck_positions"][0]["symbol"] == "AAPL"
    assert "CLOSE ALL NOW" in out["fix"]


def test_open_positions_clean_yellow_when_ib_has_positions_bot_doesnt_track():
    """v19.18 add — IB account has positions the bot isn't tracking
    (manual holdings, seeds, out-of-scope trades). Bot will NOT
    auto-close these at EOD; surface as YELLOW so operator decides.
    """
    from services.morning_readiness_service import _check_open_positions_clean

    bot = _FakeBot(open_trades={})  # bot tracks nothing

    def _fake_get_positions():
        return [
            {"symbol": "NVDA", "position": 50, "avg_cost": 200.0},
            {"symbol": "TSLA", "position": 25, "avg_cost": 180.0},
            {"symbol": "GOOGL", "position": 10, "avg_cost": 170.0},
        ]

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.get_pushed_positions", side_effect=_fake_get_positions):
        out = _check_open_positions_clean(MagicMock(), bot=bot)

    assert out["status"] == "yellow"
    assert len(out["ib_only_positions"]) == 3
    symbols = {p["symbol"] for p in out["ib_only_positions"]}
    assert symbols == {"NVDA", "TSLA", "GOOGL"}
    assert "not tracked by bot" in out["detail"]


def test_open_positions_clean_green_when_bot_tracks_all_ib_positions():
    """If bot's tracked positions match IB's account state, status is
    green — everything is bot-managed and will auto-close correctly."""
    from services.morning_readiness_service import _check_open_positions_clean

    now = datetime.now(timezone.utc)
    bot = _FakeBot(open_trades={
        "T1": _FakeTrade(symbol="NVDA", close_at_eod=True, opened_at=now),
        "T2": _FakeTrade(symbol="TSLA", close_at_eod=True, opened_at=now),
    })

    def _fake_get_positions():
        return [
            {"symbol": "NVDA", "position": 50, "avg_cost": 200.0},
            {"symbol": "TSLA", "position": 25, "avg_cost": 180.0},
        ]

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.get_pushed_positions", side_effect=_fake_get_positions):
        out = _check_open_positions_clean(MagicMock(), bot=bot)

    assert out["status"] == "green"


# --------------------------------------------------------------------------
# Aggregation + verdict
# --------------------------------------------------------------------------

def test_verdict_red_when_any_check_red():
    from services.morning_readiness_service import _aggregate_verdict

    checks = {
        "a": {"status": "green"},
        "b": {"status": "red"},
        "c": {"status": "green"},
    }
    assert _aggregate_verdict(checks) == "red"


def test_verdict_yellow_when_only_yellows():
    from services.morning_readiness_service import _aggregate_verdict

    checks = {
        "a": {"status": "green"},
        "b": {"status": "yellow"},
        "c": {"status": "yellow"},
    }
    assert _aggregate_verdict(checks) == "yellow"


def test_verdict_green_when_all_green():
    from services.morning_readiness_service import _aggregate_verdict

    checks = {
        "a": {"status": "green"},
        "b": {"status": "green"},
    }
    assert _aggregate_verdict(checks) == "green"


def test_summary_format_for_green():
    from services.morning_readiness_service import _build_summary

    s = _build_summary("green", {})
    assert s.startswith("[")
    assert "AUTOPILOT GREEN" in s


def test_summary_format_for_red_lists_blockers():
    from services.morning_readiness_service import _build_summary

    s = _build_summary("red", {
        "backfill_data_fresh": {"status": "red"},
        "ib_pipeline_alive": {"status": "green"},
        "trading_bot_configured": {"status": "green"},
        "scanner_running": {"status": "red"},
        "open_positions_clean": {"status": "green"},
    })
    assert "BLOCKED" in s
    assert "backfill_data_fresh" in s
    assert "scanner_running" in s


# --------------------------------------------------------------------------
# Top-level shape pin
# --------------------------------------------------------------------------

def test_compute_morning_readiness_response_shape():
    """The endpoint contract — shape must be stable."""
    from services.morning_readiness_service import compute_morning_readiness

    db = MagicMock()
    # The internal checks will all fail on this MagicMock-without-shape,
    # but compute_morning_readiness must still return a valid envelope.
    out = compute_morning_readiness(db, bot=None)
    assert "verdict" in out
    assert "ready_for_autopilot" in out
    assert "summary" in out
    assert "checks" in out
    assert set(out["checks"].keys()) == {
        "backfill_data_fresh",
        "ib_pipeline_alive",
        "trading_bot_configured",
        "scanner_running",
        "open_positions_clean",
    }
    assert "is_rth" in out
    assert "generated_at_et" in out
    assert "generated_at_utc" in out


def test_compute_morning_readiness_never_raises():
    """Even with a totally broken db (raises on every call), the endpoint
    must return a valid envelope — operator must never see a 500."""
    from services.morning_readiness_service import compute_morning_readiness

    class _BrokenDB:
        def __getitem__(self, name):
            raise RuntimeError("mongo offline")
        def list_collection_names(self):
            raise RuntimeError("mongo offline")

    out = compute_morning_readiness(_BrokenDB(), bot=None)
    # Status will be red, but the envelope must be intact.
    assert out["verdict"] in {"green", "yellow", "red"}
    assert "checks" in out
