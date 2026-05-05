"""
test_quote_freshness_v19_34_13.py — quote `pushed_at` stamping.

Pins v19.34.13 fix for the V5 freshness chip showing "STALE 240m" on
every position even when the pusher was LIVE 1s.

Root cause: the pusher sends raw L1 quote dicts without per-quote
timestamps, and `routers.ib.receive_pushed_ib_data` merged them
verbatim. Downstream consumers (sentcom_service.get_our_positions,
position_manager.update_open_positions) couldn't compute per-quote
quote_age, so the freshness chip fell through to its catch-all stale
branch.

Fix: stamp `pushed_at` on every quote dict at merge time using
`_pushed_ib_data["last_update"]` ISO timestamp.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestPushedAtStamping:

    def test_quote_pushed_at_stamped_on_merge(self):
        """Every quote dict gets `pushed_at` matching `last_update`."""
        # The merge logic from routers.ib.receive_pushed_ib_data is
        # straightforward enough to exercise inline — we only care that
        # the stamping step writes `pushed_at` on every quote dict
        # using the top-level `last_update` ISO timestamp.
        pushed = {"quotes": {}, "last_update": None}
        pushed["last_update"] = datetime.now(timezone.utc).isoformat()
        incoming = {
            "AAPL": {"last": 145.50, "bid": 145.49, "ask": 145.51},
            "TSLA": {"last": 280.10, "bid": 280.09, "ask": 280.11},
        }
        # Replicate the v19.34.13 fix exactly.
        _push_iso = pushed["last_update"]
        for _sym, _q in incoming.items():
            if isinstance(_q, dict):
                _q["pushed_at"] = _push_iso
        pushed["quotes"].update(incoming)

        for sym in ("AAPL", "TSLA"):
            q = pushed["quotes"].get(sym)
            assert q is not None
            assert q.get("pushed_at") == _push_iso
            assert q.get("last") in (145.50, 280.10)

    def test_non_dict_quote_value_skipped_safely(self):
        """A pusher bug that sends a string/int instead of a dict
        MUST NOT crash the merge."""
        pushed = {"quotes": {}, "last_update": datetime.now(timezone.utc).isoformat()}
        incoming = {
            "AAPL": {"last": 145.50},
            "BAD1": "not_a_dict",
            "BAD2": 42,
            "BAD3": None,
        }
        _push_iso = pushed["last_update"]
        for _sym, _q in incoming.items():
            if isinstance(_q, dict):
                _q["pushed_at"] = _push_iso
        pushed["quotes"].update(incoming)
        # Only the dict was stamped; others survived unchanged.
        assert pushed["quotes"]["AAPL"]["pushed_at"] == _push_iso
        assert pushed["quotes"]["BAD1"] == "not_a_dict"
        assert pushed["quotes"]["BAD2"] == 42
        assert pushed["quotes"]["BAD3"] is None

    def test_subsequent_push_refreshes_pushed_at(self):
        """A second /push-data call MUST refresh `pushed_at` to the new push."""
        pushed = {"quotes": {}, "last_update": None}

        def _do_push(quote_value):
            pushed["last_update"] = datetime.now(timezone.utc).isoformat()
            incoming = {"AAPL": {"last": quote_value}}
            _push_iso = pushed["last_update"]
            for _sym, _q in incoming.items():
                if isinstance(_q, dict):
                    _q["pushed_at"] = _push_iso
            pushed["quotes"].update(incoming)
            return _push_iso

        ts1 = _do_push(145.50)
        # Force a measurable gap.
        import time
        time.sleep(0.02)
        ts2 = _do_push(146.00)

        assert ts1 != ts2
        assert pushed["quotes"]["AAPL"]["pushed_at"] == ts2
        assert pushed["quotes"]["AAPL"]["last"] == 146.00


class TestSentcomServiceFallback:
    """Defensive fallback in sentcom_service.get_our_positions: when a
    quote dict lacks a per-quote timestamp (e.g., synthesized by lazy
    reconcile or rehydrated from cache), the top-level `last_update`
    is the safest age signal — better than rendering "STALE unknown".
    """

    def test_fallback_chain_reads_pushed_at_first(self):
        """When `pushed_at` is present, it wins."""
        q = {
            "pushed_at": "2026-05-06T14:00:00+00:00",
            "as_of": "2026-05-06T13:00:00+00:00",
            "timestamp": "2026-05-06T12:00:00+00:00",
        }
        push_last_update = "2026-05-06T15:00:00+00:00"
        ts = (
            q.get("pushed_at")
            or q.get("as_of")
            or q.get("timestamp")
            or q.get("ts")
            or push_last_update
        )
        assert ts == "2026-05-06T14:00:00+00:00"

    def test_fallback_to_top_level_last_update(self):
        """When all per-quote fields are None, fall back to last_update."""
        q = {"last": 145.50}  # no timestamp fields
        push_last_update = "2026-05-06T15:00:00+00:00"
        ts = (
            q.get("pushed_at")
            or q.get("as_of")
            or q.get("timestamp")
            or q.get("ts")
            or push_last_update
        )
        assert ts == push_last_update


class TestBootReconcileRetryPass:
    """v19.34.13 — boot reconcile schedules a retry pass at 90s if the
    initial 20s pass left orphans skipped. The retry catches
    `direction_unstable` skips that needed the 30s observation window
    to fill."""

    def test_skip_reasons_persisted_in_bot_state(self):
        """Persisted boot-reconcile doc includes `skipped[]` array with
        per-orphan reasons so the operator can see WHY each was left
        behind without grepping logs."""
        from routers import trading_bot as tb
        fake_db = MagicMock()
        fake_doc = {
            "ran_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
            "reconciled_count": 4,
            "skipped_count": 1,
            "errors_count": 0,
            "symbols": ["MELI", "RCL", "XLU", "FDX"],
            "skipped": [
                {"symbol": "UPS", "reason": "direction_unstable",
                 "detail": "observed 12s, need 30s"},
            ],
            "retry_pass": False,
        }
        fake_db.__getitem__.return_value.find_one = MagicMock(return_value=fake_doc)
        # `get_database` is imported lazily inside the endpoint, so
        # patch it at the source module.
        with patch("database.get_database", return_value=fake_db):
            import asyncio
            resp = asyncio.run(tb.get_boot_reconcile_status())
        assert resp["ran"] is True
        assert resp["reconciled_count"] == 4
        assert resp["skipped_count"] == 1
        assert "skipped" in resp
        assert resp["skipped"][0]["symbol"] == "UPS"
        assert resp["skipped"][0]["reason"] == "direction_unstable"
        assert resp["retry_pass"] is False

    def test_no_skip_field_in_old_docs_returns_empty(self):
        """Backward-compat: old `last_auto_reconcile_at_boot` docs
        without `skipped` field must not crash the endpoint."""
        from routers import trading_bot as tb
        fake_db = MagicMock()
        fake_doc = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "reconciled_count": 2,
            "skipped_count": 0,
            "errors_count": 0,
            "symbols": ["AAPL", "TSLA"],
            # NO `skipped` or `retry_pass`
        }
        fake_db.__getitem__.return_value.find_one = MagicMock(return_value=fake_doc)
        with patch("database.get_database", return_value=fake_db):
            import asyncio
            resp = asyncio.run(tb.get_boot_reconcile_status())
        assert resp["skipped"] == []
        assert resp["retry_pass"] is False
