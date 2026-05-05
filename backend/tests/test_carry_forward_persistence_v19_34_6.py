"""
test_carry_forward_persistence_v19_34_6.py — pin the v19.34.6
carry-forward gameplan persistence so morning prep workflow survives
backend restarts.

2026-05-05 v19.34.6 — operator-filed bug from 2026-05-04 EVE:

  > SCANNER · LIVE panel showed 4 rich `carry_forward_watch` cards
  > (SBUX/IAU/MA/SYK) during the day with full bot reasoning. On hard
  > refresh of the app outside RTH, the cards disappeared and only
  > today's actual position (STX) remained.

Root cause: `EnhancedBackgroundScanner._live_alerts` is in-memory
only. When the operator hard-refreshed (or the backend restarted),
the dict was re-initialized empty.

Fix: persist carry-forward alerts to `carry_forward_alerts` Mongo
collection on creation + hydrate them back into `_live_alerts` on
scanner startup. This test file pins both ends of that contract.

All tests are pure-Python — no IB Gateway, no network, no real DB.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_carry_forward_doc(**overrides):
    """A representative Mongo doc for a persisted carry-forward alert,
    matching what `_persist_carry_forward_alert` writes via
    `LiveAlert.to_dict()`."""
    base = {
        "id": "cf_MELI_carry_forward_watch_1730000000",
        "symbol": "MELI",
        "setup_type": "carry_forward_watch",
        "strategy_name": "carry_forward_watch",
        "direction": "long",
        "priority": "medium",
        "current_price": 1820.0,
        "trigger_price": 1820.0,
        "stop_loss": 1800.0,
        "target": 1860.0,
        "risk_reward": 2.0,
        "trigger_probability": 0.65,
        "win_probability": 0.65,
        "minutes_to_trigger": 0,
        "headline": "CARRY-FORWARD MELI (carry forward watch) — TQS 65",
        "reasoning": ["Today's day_2_continuation graded B+ — MELI on tomorrow's watchlist."],
        "time_window": "CLOSED",
        "market_regime": "neutral",
        "scan_tier": "swing",
        "trade_style": "multi_day",
        "created_at": "2026-05-05T20:30:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",  # always in future
        "status": "active",
        "tqs_score": 65.0,
        "tqs_grade": "B+",
        "last_persisted_at": "2026-05-05T20:30:00+00:00",
    }
    base.update(overrides)
    return base


def _new_scanner(db=None):
    """Construct a real EnhancedBackgroundScanner without spinning up
    its scan loop or services. Uses the dataclass machinery to keep
    the LiveAlert / AlertPriority types intact."""
    from services.enhanced_scanner import EnhancedBackgroundScanner
    s = EnhancedBackgroundScanner(db=db)
    return s


# --------------------------------------------------------------------------
# Tests — persist
# --------------------------------------------------------------------------

class TestCarryForwardPersistV19_34_6:

    def test_persist_writes_upsert_with_id(self):
        """`_persist_carry_forward_alert` MUST upsert by id with the
        full dataclass payload."""
        from services.enhanced_scanner import LiveAlert, AlertPriority

        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        scanner = _new_scanner(db=db)

        alert = LiveAlert(
            id="cf_HOOD_1",
            symbol="HOOD",
            setup_type="carry_forward_watch",
            strategy_name="carry_forward_watch",
            direction="long",
            priority=AlertPriority.HIGH,
            current_price=72.0,
            trigger_price=72.0,
            stop_loss=70.0,
            target=76.0,
            risk_reward=2.0,
            trigger_probability=0.65,
            win_probability=0.65,
            minutes_to_trigger=0,
            headline="CF HOOD",
            reasoning=["Day-2 continuation viable"],
            time_window="CLOSED",
            market_regime="risk_on",
        )

        scanner._persist_carry_forward_alert(alert)

        coll.update_one.assert_called_once()
        call_args = coll.update_one.call_args
        # Filter: keyed by `id`
        assert call_args[0][0] == {"id": "cf_HOOD_1"}
        # Update: $set the full doc
        update_doc = call_args[0][1]["$set"]
        assert update_doc["symbol"] == "HOOD"
        assert update_doc["setup_type"] == "carry_forward_watch"
        # priority must be str-encoded for JSON-friendly Mongo storage
        assert update_doc["priority"] == "high"
        # last_persisted_at stamped
        assert "last_persisted_at" in update_doc
        # upsert flag MUST be true so first-time insert works
        assert call_args[1]["upsert"] is True

    def test_persist_no_db_is_silent_noop(self):
        """When scanner is constructed without a DB (test runs / pre-init),
        the call must NOT raise."""
        from services.enhanced_scanner import LiveAlert, AlertPriority

        scanner = _new_scanner(db=None)
        alert = LiveAlert(
            id="cf_X_1", symbol="X", setup_type="carry_forward_watch",
            strategy_name="carry_forward_watch", direction="long",
            priority=AlertPriority.LOW,
            current_price=1.0, trigger_price=1.0, stop_loss=0.9, target=1.1,
            risk_reward=1.0, trigger_probability=0.5, win_probability=0.5,
            minutes_to_trigger=0,
            headline="x", reasoning=[], time_window="CLOSED", market_regime="neutral",
        )
        scanner._persist_carry_forward_alert(alert)
        # No exception → pass

    def test_persist_creates_indexes(self):
        """We index by expires_at (cleanup queries), symbol, and
        setup_type. Idempotent per Mongo create_index semantics."""
        from services.enhanced_scanner import LiveAlert, AlertPriority

        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        scanner = _new_scanner(db=db)
        alert = LiveAlert(
            id="cf_X_1", symbol="X", setup_type="carry_forward_watch",
            strategy_name="carry_forward_watch", direction="long",
            priority=AlertPriority.LOW,
            current_price=1.0, trigger_price=1.0, stop_loss=0.9, target=1.1,
            risk_reward=1.0, trigger_probability=0.5, win_probability=0.5,
            minutes_to_trigger=0,
            headline="x", reasoning=[], time_window="CLOSED", market_regime="neutral",
        )
        scanner._persist_carry_forward_alert(alert)

        index_calls = [c[0][0] for c in coll.create_index.call_args_list]
        assert "expires_at" in index_calls
        assert "symbol" in index_calls
        assert "setup_type" in index_calls


# --------------------------------------------------------------------------
# Tests — hydrate
# --------------------------------------------------------------------------

class TestCarryForwardHydrateV19_34_6:

    @pytest.mark.asyncio
    async def test_hydrate_loads_non_expired_into_live_alerts(self):
        """The morning prep workflow: scanner started, _live_alerts is
        empty, the hydrate call MUST pull yesterday's carry-forwards
        from Mongo into the dict."""
        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        docs = [
            _make_carry_forward_doc(id="cf_SBUX_1", symbol="SBUX"),
            _make_carry_forward_doc(id="cf_IAU_1", symbol="IAU"),
            _make_carry_forward_doc(id="cf_MA_1", symbol="MA"),
            _make_carry_forward_doc(id="cf_SYK_1", symbol="SYK"),
        ]
        coll.find = MagicMock(return_value=docs)

        scanner = _new_scanner(db=db)
        # Confirm the dict starts empty
        assert scanner._live_alerts == {}

        n = await scanner._hydrate_carry_forward_alerts_from_mongo()

        assert n == 4
        assert len(scanner._live_alerts) == 4
        for sym in ("SBUX", "IAU", "MA", "SYK"):
            assert any(a.symbol == sym for a in scanner._live_alerts.values())

    @pytest.mark.asyncio
    async def test_hydrate_skips_dismissed_alerts(self):
        """The Mongo query MUST filter `status != "dismissed"` so the
        operator's manual dismissals stick across restart."""
        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        captured_query = {}

        def _find(q, projection=None):
            captured_query["q"] = q
            return [_make_carry_forward_doc()]

        coll.find = _find
        scanner = _new_scanner(db=db)

        await scanner._hydrate_carry_forward_alerts_from_mongo()

        assert captured_query["q"]["status"] == {"$ne": "dismissed"}

    @pytest.mark.asyncio
    async def test_hydrate_skips_expired_alerts(self):
        """The query MUST filter on `expires_at >= now`."""
        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        captured_query = {}

        def _find(q, projection=None):
            captured_query["q"] = q
            return []

        coll.find = _find
        scanner = _new_scanner(db=db)

        await scanner._hydrate_carry_forward_alerts_from_mongo()

        # expires_at filter is OR-ed with NULL (so legacy un-stamped
        # alerts also hydrate)
        assert "$or" in captured_query["q"]
        or_clauses = captured_query["q"]["$or"]
        assert any("expires_at" in c and "$gte" in c.get("expires_at", {}) for c in or_clauses)

    @pytest.mark.asyncio
    async def test_hydrate_no_db_is_silent_noop(self):
        """Without a DB: returns 0, doesn't raise."""
        scanner = _new_scanner(db=None)
        n = await scanner._hydrate_carry_forward_alerts_from_mongo()
        assert n == 0

    @pytest.mark.asyncio
    async def test_hydrate_does_not_duplicate_when_already_in_memory(self):
        """If the in-memory dict already has the alert (e.g. a cycle
        already populated it), hydrate MUST NOT clobber or duplicate."""
        from services.enhanced_scanner import LiveAlert, AlertPriority

        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        # Mongo has 1 doc with id=cf_HOOD
        coll.find = MagicMock(return_value=[
            _make_carry_forward_doc(id="cf_HOOD_1", symbol="HOOD",
                                     trigger_price=99.0),
        ])

        scanner = _new_scanner(db=db)
        # Pre-populate in-memory with a different price (to detect clobber)
        existing = LiveAlert(
            id="cf_HOOD_1", symbol="HOOD", setup_type="carry_forward_watch",
            strategy_name="carry_forward_watch", direction="long",
            priority=AlertPriority.MEDIUM,
            current_price=72.0, trigger_price=72.0, stop_loss=70.0, target=76.0,
            risk_reward=2.0, trigger_probability=0.5, win_probability=0.5,
            minutes_to_trigger=0,
            headline="x", reasoning=[], time_window="CLOSED", market_regime="neutral",
        )
        scanner._live_alerts["cf_HOOD_1"] = existing

        n = await scanner._hydrate_carry_forward_alerts_from_mongo()

        # NOT hydrated (already in memory)
        assert n == 0
        # Original price preserved
        assert scanner._live_alerts["cf_HOOD_1"].trigger_price == 72.0

    @pytest.mark.asyncio
    async def test_inflate_live_alert_handles_unknown_field(self):
        """Forward-compatibility: if Mongo has fields that the LiveAlert
        dataclass doesn't (e.g. a future field added then rolled back),
        hydrate MUST drop them silently rather than crash."""
        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        doc = _make_carry_forward_doc(id="cf_AAPL_1", symbol="AAPL")
        doc["unknown_future_field"] = "this should be ignored"
        coll.find = MagicMock(return_value=[doc])

        scanner = _new_scanner(db=db)
        n = await scanner._hydrate_carry_forward_alerts_from_mongo()

        assert n == 1
        a = scanner._live_alerts["cf_AAPL_1"]
        assert a.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_hydrate_priority_string_back_to_enum(self):
        """Mongo stores priority as a string; hydrate MUST map it back
        to the AlertPriority enum so downstream comparisons work."""
        from services.enhanced_scanner import AlertPriority

        db = MagicMock()
        coll = MagicMock()
        db.carry_forward_alerts = coll

        doc = _make_carry_forward_doc(id="cf_X_1", priority="high")
        coll.find = MagicMock(return_value=[doc])

        scanner = _new_scanner(db=db)
        await scanner._hydrate_carry_forward_alerts_from_mongo()

        assert scanner._live_alerts["cf_X_1"].priority is AlertPriority.HIGH


# --------------------------------------------------------------------------
# Tests — start() integration
# --------------------------------------------------------------------------

class TestStartHydrateIntegrationV19_34_6:

    @pytest.mark.asyncio
    async def test_start_calls_hydrate(self):
        """`scanner.start()` MUST call `_hydrate_carry_forward_alerts_from_mongo`
        BEFORE spinning up the scan loop. This is the operator's
        morning workflow safety net."""
        scanner = _new_scanner(db=None)

        # Stub out the loop spin so we can assert on hydrate without
        # actually running a real scan
        called = {"hydrate": 0, "loop_started": False}

        async def _stub_hydrate():
            called["hydrate"] += 1
            return 0

        async def _stub_loop():
            called["loop_started"] = True

        scanner._hydrate_carry_forward_alerts_from_mongo = _stub_hydrate
        scanner._scan_loop = _stub_loop

        await scanner.start()
        # Give the spawned task a chance to run
        await asyncio.sleep(0.01)

        assert called["hydrate"] == 1, (
            "scanner.start() did NOT call the hydrate helper — the "
            "morning gameplan workflow won't survive backend restarts"
        )
        # Stop the scanner cleanly so the test doesn't leak
        await scanner.stop()
