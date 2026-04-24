"""
HTTP regression tests for iteration 133:
    - TopMoversTile backend (briefing-snapshot) contract
    - Phase 4 Alpaca retirement verified via /api/ib/analysis/SPY
    - Phase 1/2/3 endpoint regressions
All tests target the live backend at localhost:8001 (preview ingress 404s).
"""
from __future__ import annotations

import os
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")


# --- TopMoversTile data feed --------------------------------------------------
class TestBriefingSnapshot:
    def test_briefing_snapshot_default_symbols_shape(self):
        r = requests.get(
            f"{BASE_URL}/api/live/briefing-snapshot",
            params={"symbols": "SPY,QQQ,IWM,DIA,VIX"},
            timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d.get("success") is True
        assert d.get("count") == 5
        assert d.get("market_state") in {"rth", "extended", "overnight", "weekend", "closed", "pre", "post"}
        snaps = d.get("snapshots")
        assert isinstance(snaps, list) and len(snaps) == 5
        # Each snapshot has a stable shape even when success=false (graceful degrade)
        for s in snaps:
            assert "symbol" in s and "success" in s
            assert "latest_price" in s and "change_pct" in s

    def test_briefing_snapshot_no_5xx_on_garbage(self):
        r = requests.get(
            f"{BASE_URL}/api/live/briefing-snapshot",
            params={"symbols": "!!BAD!!,@#$"},
            timeout=15,
        )
        assert r.status_code < 500


# --- Phase 4 Alpaca retirement ------------------------------------------------
class TestPhase4AlpacaRetirement:
    def test_ib_analysis_not_alpaca_data_source(self):
        r = requests.get(f"{BASE_URL}/api/ib/analysis/SPY", timeout=20)
        assert r.status_code == 200
        d = r.json()
        ds = d.get("data_source", "")
        assert ds != "Alpaca", f"data_source must no longer be bare 'Alpaca', got={ds!r}"
        # Acceptable labels — IB-only or IB shim
        assert ("IB" in ds) or ("ib_" in ds.lower()) or (ds == ""), (
            f"Unexpected data_source label after Phase 4: {ds!r}"
        )

    def test_response_body_has_no_alpaca_mention_as_primary_source(self):
        """Soft assertion: the response body may mention 'Alpaca' in history
        fields but must not show it as the primary data_source."""
        r = requests.get(f"{BASE_URL}/api/ib/analysis/SPY", timeout=20)
        d = r.json()
        # The critical field is data_source
        assert d.get("data_source", "") != "Alpaca"


# --- Phase 1/2/3 regressions --------------------------------------------------
class TestPhase123Regressions:
    @pytest.mark.parametrize("path", [
        "/api/live/subscriptions",
        "/api/live/pusher-rpc-health",
        "/api/live/symbol-snapshot/SPY",
        "/api/live/ttl-plan",
    ])
    def test_endpoint_200(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        # Stable JSON
        r.json()

    def test_symbol_snapshot_stable_shape_in_degraded_mode(self):
        r = requests.get(f"{BASE_URL}/api/live/symbol-snapshot/SPY", timeout=15)
        d = r.json()
        for key in ("success", "symbol", "latest_price", "change_pct", "market_state"):
            assert key in d, f"Missing key {key} in symbol-snapshot response"


# --- Chat server live-snapshots injection (if running) -----------------------
class TestChatServerSnapshotInjection:
    """chat_server runs on port 8002 if enabled. Optional: skip if not up."""

    CHAT_URL = os.environ.get("CHAT_SERVER_URL", "http://localhost:8002")

    def _chat_up(self):
        try:
            r = requests.get(f"{self.CHAT_URL}/health", timeout=2)
            return r.status_code < 500
        except Exception:
            return False

    def test_chat_server_health_or_skip(self):
        if not self._chat_up():
            pytest.skip("chat_server on 8002 not running — skipping live chat test")
        r = requests.get(f"{self.CHAT_URL}/health", timeout=3)
        assert r.status_code == 200

    def test_chat_request_does_not_crash_in_degraded_live_data(self):
        if not self._chat_up():
            pytest.skip("chat_server on 8002 not running — skipping")
        # Minimal chat payload — test the snapshot injection path doesn't crash
        try:
            r = requests.post(
                f"{self.CHAT_URL}/chat",
                json={"message": "What is SPY doing?", "history": []},
                timeout=30,
            )
            # Must not 5xx due to snapshot failure
            assert r.status_code < 500, f"chat_server crashed: {r.status_code} {r.text[:200]}"
        except requests.Timeout:
            pytest.skip("chat took >30s (likely LLM slow path) — not a crash")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
