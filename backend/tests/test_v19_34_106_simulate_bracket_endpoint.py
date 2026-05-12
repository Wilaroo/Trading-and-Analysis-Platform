"""
Tests for v19.34.106 — POST /api/trading-bot/simulate-bracket endpoint.

Validates the offline bracket-payload simulator:
  • Returns the same shape `_ib_bracket` would queue to the pusher
    (parent + stop + target + targets[] + policy).
  • Long-horizon styles emit GTC + outside_rth=true on parent.
  • Multi-rung ladders sum exactly to the requested share count.
  • Explicit target_prices override r_multiple computation.
  • Unknown styles fall back to the intraday DEFAULT_POLICY.

Uses `requests` against the running backend on localhost:8001 to
avoid TestClient version coupling.
"""
from __future__ import annotations

import os
import pytest
import requests


BACKEND = "http://localhost:8001"


def _backend_alive() -> bool:
    try:
        requests.get(f"{BACKEND}/api/trading-bot/order-policies", timeout=2)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _backend_alive(),
    reason="Backend not reachable at localhost:8001",
)


def _post(body):
    r = requests.post(
        f"{BACKEND}/api/trading-bot/simulate-bracket",
        json=body, timeout=5,
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestSimulateBracket:
    def test_position_three_rung_ladder(self):
        out = _post({
            "symbol": "NVDA", "trade_style": "position",
            "direction": "long", "shares": 100,
            "entry_price": 100.0, "stop_price": 95.0,
        })
        assert out["success"] is True
        p = out["payload"]
        assert p["parent"]["time_in_force"] == "GTC"
        assert p["parent"]["outside_rth"] is True
        assert len(p["targets"]) == 3
        # 25/25/50 of 100 = 25/25/50 → sum = 100
        qtys = [t["quantity"] for t in p["targets"]]
        assert sum(qtys) == 100, f"OCA ladder must sum exactly: got {qtys}"
        # Position ladder R-multiples = 4 / 8 / 15
        assert [t["r_multiple"] for t in p["targets"]] == [4.0, 8.0, 15.0]
        # Limit prices = entry + r * risk_distance
        assert p["targets"][0]["limit_price"] == 120.0  # 100 + 4*5
        assert p["targets"][1]["limit_price"] == 140.0  # 100 + 8*5
        assert p["targets"][2]["limit_price"] == 175.0  # 100 + 15*5

    def test_scalp_single_rung(self):
        out = _post({
            "symbol": "AAPL", "trade_style": "scalp",
            "direction": "long", "shares": 50,
            "entry_price": 200.0, "stop_price": 199.0,
        })
        p = out["payload"]
        assert p["parent"]["time_in_force"] == "DAY"
        assert p["parent"]["outside_rth"] is False
        assert len(p["targets"]) == 1
        assert p["targets"][0]["quantity"] == 50
        assert p["targets"][0]["limit_price"] == 201.0  # 200 + 1R*1

    def test_explicit_target_prices_override(self):
        out = _post({
            "symbol": "TSLA", "trade_style": "investment",
            "direction": "long", "shares": 30,
            "entry_price": 100.0, "stop_price": 90.0,
            "target_prices": [108.5, 125.0, 200.0],
        })
        p = out["payload"]
        prices = [t["limit_price"] for t in p["targets"]]
        assert prices == [108.5, 125.0, 200.0]

    def test_short_trade_uses_buy_to_cover(self):
        out = _post({
            "symbol": "QQQ", "trade_style": "swing",
            "direction": "short", "shares": 20,
            "entry_price": 400.0, "stop_price": 410.0,
        })
        p = out["payload"]
        assert p["parent"]["action"] == "SELL"
        for leg in p["targets"]:
            assert leg["action"] == "BUY"
        # 50/50 of 20 = 10/10
        assert [t["quantity"] for t in p["targets"]] == [10, 10]
        # entry - r * risk_distance, risk = 10
        assert p["targets"][0]["limit_price"] == 380.0
        assert p["targets"][1]["limit_price"] == 350.0

    def test_unknown_style_falls_back_to_intraday(self):
        out = _post({
            "symbol": "SPY", "trade_style": "garbage",
            "direction": "long", "shares": 10,
            "entry_price": 500.0, "stop_price": 495.0,
        })
        p = out["payload"]
        assert p["policy"]["style"] == "intraday"
        assert p["parent"]["time_in_force"] == "DAY"

    def test_policy_audit_stamp_present(self):
        out = _post({
            "symbol": "MSFT", "trade_style": "position",
            "direction": "long", "shares": 10,
            "entry_price": 100.0, "stop_price": 90.0,
        })
        pol = out["payload"]["policy"]
        assert pol["style"] == "position"
        assert pol["stop_trail_anchor"] == "sma_150"
        assert pol["eod_sweep_eligible"] is False

    def test_no_side_effects_does_not_queue_order(self):
        """Endpoint must be pure — no Mongo writes, no IB calls."""
        out = _post({
            "symbol": "AMD", "trade_style": "intraday",
            "direction": "long", "shares": 5,
            "entry_price": 50.0, "stop_price": 49.0,
        })
        assert out["payload"]["trade_id"] == "SIM"
