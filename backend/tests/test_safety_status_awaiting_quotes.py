"""
Ensure /api/safety/status surfaces the new `live.awaiting_quotes` block that
the V5 UI's AwaitingQuotesPill consumes.

Uses the live backend on :8001 (via conftest.api_base_url) because the
TestClient/httpx versions in this env don't interoperate cleanly.
"""
import pytest
import requests


def test_status_exposes_live_block(api_base_url):
    r = requests.get(f"{api_base_url}/api/safety/status", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert "live" in body, "safety status must include live-block for V5 UI"
    live = body["live"]
    assert set(live.keys()) >= {
        "open_positions_count",
        "awaiting_quotes",
        "positions_missing_quotes",
    }
    assert isinstance(live["awaiting_quotes"], bool)
    assert isinstance(live["positions_missing_quotes"], list)
    assert isinstance(live["open_positions_count"], int)

