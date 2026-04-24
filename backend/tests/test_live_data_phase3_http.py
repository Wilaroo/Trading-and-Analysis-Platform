"""
Phase 3 HTTP smoke tests - hit the running backend at localhost:8001
for all Phase 3 live-data endpoints + regression checks on Phase 1/2 and
existing trade-journal endpoints.
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

SNAPSHOT_KEYS = {
    "success", "symbol", "latest_price", "latest_bar_time", "prev_close",
    "change_abs", "change_pct", "bar_size", "bar_count", "market_state",
    "source", "fetched_at", "error",
}


# ---------------- /api/live/symbol-snapshot/{symbol} ---------------------

class TestSymbolSnapshot:
    def test_symbol_snapshot_200_and_stable_shape(self):
        r = requests.get(f"{BASE_URL}/api/live/symbol-snapshot/SPY",
                         params={"bar_size": "5 mins"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Shape stability: all documented keys must be present
        missing = SNAPSHOT_KEYS - set(body.keys())
        assert not missing, f"Missing snapshot keys: {missing}"
        assert body["symbol"] == "SPY"
        assert body["bar_size"] == "5 mins"
        # In preview env pusher is unreachable → graceful degrade
        if body["success"] is False:
            assert body["error"], "error field must be populated on failure"

    def test_symbol_snapshot_invalid_symbol_never_5xx(self):
        r = requests.get(f"{BASE_URL}/api/live/symbol-snapshot/!!INVALID!!",
                         timeout=15)
        # Must never 500; either 200 with success=false or 400/422
        assert r.status_code < 500, r.text


# ---------------- /api/live/symbol-snapshots (bulk POST) -----------------

class TestSymbolSnapshotsBulk:
    def test_bulk_three_symbols(self):
        r = requests.post(
            f"{BASE_URL}/api/live/symbol-snapshots",
            json={"symbols": ["SPY", "QQQ", "VIX"], "bar_size": "5 mins"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["count"] == 3
        assert isinstance(body["snapshots"], list)
        assert len(body["snapshots"]) == 3
        # Every snapshot must still carry the stable shape
        for snap in body["snapshots"]:
            missing = SNAPSHOT_KEYS - set(snap.keys())
            assert not missing, f"Missing keys in bulk snapshot: {missing}"

    def test_bulk_bounded_to_20(self):
        many = [f"SYM{i:03d}" for i in range(50)]
        r = requests.post(
            f"{BASE_URL}/api/live/symbol-snapshots",
            json={"symbols": many, "bar_size": "5 mins"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert len(body["snapshots"]) <= 20, (
            f"DoS guard broken — got {len(body['snapshots'])} snapshots"
        )

    def test_bulk_invalid_payload_returns_graceful_failure(self):
        r = requests.post(
            f"{BASE_URL}/api/live/symbol-snapshots",
            json={"symbols": "not a list"},
            timeout=15,
        )
        # Must never 5xx
        assert r.status_code < 500, r.text
        # Either 200 w/ success=false or 4xx validation error
        if r.status_code == 200:
            body = r.json()
            assert body.get("success") is False


# ---------------- /api/live/briefing-snapshot ----------------------------

class TestBriefingSnapshot:
    def test_briefing_with_explicit_symbols(self):
        r = requests.get(
            f"{BASE_URL}/api/live/briefing-snapshot",
            params={"symbols": "SPY,QQQ,IWM,DIA,VIX"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["count"] == 5
        assert "market_state" in body
        assert "bar_size" in body
        assert isinstance(body["snapshots"], list)
        assert len(body["snapshots"]) == 5

    def test_briefing_defaults_when_no_symbols(self):
        r = requests.get(f"{BASE_URL}/api/live/briefing-snapshot", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["count"] == 5
        returned = {s["symbol"] for s in body["snapshots"]}
        expected = {"SPY", "QQQ", "IWM", "DIA", "VIX"}
        assert returned == expected, f"Default symbols mismatch: {returned}"


# ---------------- Regression checks (Phase 1/2 + existing) ---------------

class TestPhase12Regression:
    def test_subscribe_still_accepts(self):
        r = requests.post(f"{BASE_URL}/api/live/subscribe/SPY", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("accepted") is True

    def test_pusher_rpc_health_reachable_false(self):
        r = requests.get(f"{BASE_URL}/api/live/pusher-rpc-health", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # In preview env pusher is unreachable by design
        assert body.get("reachable") is False

    def test_sentcom_chart_still_responds(self):
        r = requests.get(
            f"{BASE_URL}/api/sentcom/chart",
            params={"symbol": "SPY", "timeframe": "5min", "days": 5},
            timeout=30,
        )
        # Must not 5xx; 200 expected (may have success=false on data outage)
        assert r.status_code < 500, r.text

    def test_trades_endpoint_still_works(self):
        r = requests.get(f"{BASE_URL}/api/trades", timeout=20)
        # Existing trade-journal endpoint must not regress after close_trade
        # modification (close_price_snapshot capture)
        assert r.status_code < 500, r.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
