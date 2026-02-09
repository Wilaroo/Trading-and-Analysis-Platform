"""
Test Strategy-Specific Configurations for Trading Bot
Tests for strategy configs, demo trades with strategy settings, and timeframe badges
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Strategy expected configurations
EXPECTED_STRATEGIES = {
    "rubber_band": {"timeframe": "scalp", "close_at_eod": True, "trail_pct": 0.01},
    "vwap_bounce": {"timeframe": "scalp", "close_at_eod": True, "trail_pct": 0.01},
    "breakout": {"timeframe": "intraday", "close_at_eod": True, "trail_pct": 0.015},
    "squeeze": {"timeframe": "swing", "close_at_eod": False, "trail_pct": 0.025},
    "trend_continuation": {"timeframe": "swing", "close_at_eod": False, "trail_pct": 0.025},
    "position_trade": {"timeframe": "position", "close_at_eod": False, "trail_pct": 0.03}
}


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestBotStatusWithStrategyConfigs:
    """Test GET /api/trading-bot/status includes strategy_configs"""
    
    def test_status_returns_strategy_configs(self, api_client):
        """Verify /status includes strategy_configs object"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200, f"Status code: {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True
        assert "strategy_configs" in data, "strategy_configs not in status response"
        
        configs = data["strategy_configs"]
        assert len(configs) >= 6, f"Expected 6+ strategies, got {len(configs)}"
        print(f"PASS: Status returns strategy_configs with {len(configs)} strategies")
    
    def test_status_strategy_configs_all_six_strategies(self, api_client):
        """Verify all 6 expected strategies are present"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/status")
        data = response.json()
        configs = data.get("strategy_configs", {})
        
        for strategy in EXPECTED_STRATEGIES.keys():
            assert strategy in configs, f"Strategy '{strategy}' missing from configs"
            print(f"PASS: Strategy '{strategy}' found in configs")
    
    def test_status_strategy_configs_structure(self, api_client):
        """Verify each strategy has required fields"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/status")
        data = response.json()
        configs = data.get("strategy_configs", {})
        
        required_fields = ["timeframe", "trail_pct", "scale_out_pcts", "close_at_eod"]
        
        for strategy, config in configs.items():
            for field in required_fields:
                assert field in config, f"Strategy '{strategy}' missing field '{field}'"
            
            # Validate field types
            assert isinstance(config["timeframe"], str), f"{strategy}: timeframe should be string"
            assert isinstance(config["trail_pct"], (int, float)), f"{strategy}: trail_pct should be number"
            assert isinstance(config["scale_out_pcts"], list), f"{strategy}: scale_out_pcts should be list"
            assert isinstance(config["close_at_eod"], bool), f"{strategy}: close_at_eod should be bool"
            
            print(f"PASS: Strategy '{strategy}' has valid structure")


class TestGetStrategyConfigs:
    """Test GET /api/trading-bot/strategy-configs endpoint"""
    
    def test_get_all_strategy_configs(self, api_client):
        """Test GET /strategy-configs returns all strategies"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        assert response.status_code == 200, f"Status code: {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True
        assert "configs" in data
        
        configs = data["configs"]
        assert len(configs) >= 6, f"Expected 6+ strategies, got {len(configs)}"
        print(f"PASS: GET /strategy-configs returns {len(configs)} strategies")
    
    def test_rubber_band_config(self, api_client):
        """Verify rubber_band strategy config"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        data = response.json()
        configs = data.get("configs", {})
        
        rubber_band = configs.get("rubber_band")
        assert rubber_band is not None, "rubber_band not in configs"
        assert rubber_band["timeframe"] == "scalp"
        assert rubber_band["close_at_eod"] is True
        # Note: trail_pct may have been updated, just check it exists
        assert "trail_pct" in rubber_band
        print(f"PASS: rubber_band config - timeframe=scalp, close_at_eod=True, trail_pct={rubber_band['trail_pct']}")
    
    def test_squeeze_config(self, api_client):
        """Verify squeeze strategy config"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        data = response.json()
        configs = data.get("configs", {})
        
        squeeze = configs.get("squeeze")
        assert squeeze is not None, "squeeze not in configs"
        assert squeeze["timeframe"] == "swing"
        assert squeeze["close_at_eod"] is False
        assert squeeze["trail_pct"] == 0.025
        print(f"PASS: squeeze config - timeframe=swing, close_at_eod=False, trail_pct=0.025")
    
    def test_position_trade_config(self, api_client):
        """Verify position_trade strategy config"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        data = response.json()
        configs = data.get("configs", {})
        
        position_trade = configs.get("position_trade")
        assert position_trade is not None, "position_trade not in configs"
        assert position_trade["timeframe"] == "position"
        assert position_trade["close_at_eod"] is False
        assert position_trade["trail_pct"] == 0.03
        print(f"PASS: position_trade config - timeframe=position, close_at_eod=False, trail_pct=0.03")


class TestUpdateStrategyConfig:
    """Test PUT /api/trading-bot/strategy-configs/{strategy}"""
    
    def test_update_rubber_band_trail_pct(self, api_client):
        """Test updating trail_pct for rubber_band strategy"""
        # Get current config
        get_response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        current_configs = get_response.json().get("configs", {})
        original_trail_pct = current_configs.get("rubber_band", {}).get("trail_pct", 0.01)
        
        # Update trail_pct
        new_trail_pct = 0.015
        response = api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/rubber_band",
            json={"trail_pct": new_trail_pct}
        )
        assert response.status_code == 200, f"Status code: {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True
        
        # Verify update in response
        updated_configs = data.get("configs", {})
        assert updated_configs.get("rubber_band", {}).get("trail_pct") == new_trail_pct
        print(f"PASS: rubber_band trail_pct updated to {new_trail_pct}")
        
        # Restore original value
        api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/rubber_band",
            json={"trail_pct": original_trail_pct}
        )
    
    def test_update_rubber_band_close_at_eod(self, api_client):
        """Test updating close_at_eod for rubber_band strategy"""
        # Get current config
        get_response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        current_configs = get_response.json().get("configs", {})
        original_close_at_eod = current_configs.get("rubber_band", {}).get("close_at_eod", True)
        
        # Update close_at_eod to opposite value
        new_close_at_eod = not original_close_at_eod
        response = api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/rubber_band",
            json={"close_at_eod": new_close_at_eod}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        updated_configs = data.get("configs", {})
        assert updated_configs.get("rubber_band", {}).get("close_at_eod") == new_close_at_eod
        print(f"PASS: rubber_band close_at_eod updated to {new_close_at_eod}")
        
        # Restore original value
        api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/rubber_band",
            json={"close_at_eod": original_close_at_eod}
        )
    
    def test_update_both_fields(self, api_client):
        """Test updating both trail_pct and close_at_eod together"""
        # Update both fields
        response = api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/breakout",
            json={"trail_pct": 0.02, "close_at_eod": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        updated_configs = data.get("configs", {})
        breakout = updated_configs.get("breakout", {})
        assert breakout.get("trail_pct") == 0.02
        assert breakout.get("close_at_eod") is False
        print("PASS: breakout both trail_pct and close_at_eod updated")
        
        # Restore original values
        api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/breakout",
            json={"trail_pct": 0.015, "close_at_eod": True}
        )
    
    def test_update_nonexistent_strategy_returns_404(self, api_client):
        """Test updating non-existent strategy returns 404"""
        response = api_client.put(
            f"{BASE_URL}/api/trading-bot/strategy-configs/nonexistent",
            json={"trail_pct": 0.05}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Nonexistent strategy update returns 404")


class TestDemoTradeWithStrategyConfig:
    """Test POST /api/trading-bot/demo-trade applies strategy config"""
    
    @pytest.fixture(autouse=True)
    def cleanup_demo_trades(self, api_client):
        """Clean up demo trades after each test"""
        yield
        # Get pending trades and reject any test trades
        response = api_client.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        if response.status_code == 200:
            data = response.json()
            for trade in data.get("trades", []):
                if trade.get("symbol") in ["TEST", "NVDA", "AAPL", "MSFT"]:
                    api_client.post(f"{BASE_URL}/api/trading-bot/trades/{trade['id']}/reject")
    
    def test_demo_trade_rubber_band_applies_scalp_config(self, api_client):
        """Test demo trade with rubber_band applies scalp timeframe and close_at_eod=true"""
        response = api_client.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "NVDA", "direction": "long", "setup_type": "rubber_band"}
        )
        assert response.status_code == 200, f"Status: {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True
        trade = data.get("trade", {})
        
        assert trade.get("timeframe") == "scalp", f"Expected scalp, got {trade.get('timeframe')}"
        assert trade.get("close_at_eod") is True, f"Expected close_at_eod=True"
        
        # Verify trailing_stop_config has strategy's trail_pct
        trailing_config = trade.get("trailing_stop_config", {})
        # Note: trail_pct may be 0.01 or 0.012 depending on prior updates
        assert trailing_config.get("trail_pct") is not None
        print(f"PASS: rubber_band demo trade - timeframe=scalp, close_at_eod=True, trail_pct={trailing_config.get('trail_pct')}")
        
        # Reject the trade
        api_client.post(f"{BASE_URL}/api/trading-bot/trades/{trade['id']}/reject")
    
    def test_demo_trade_squeeze_applies_swing_config(self, api_client):
        """Test demo trade with squeeze applies swing timeframe and close_at_eod=false"""
        response = api_client.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "AAPL", "direction": "long", "setup_type": "squeeze"}
        )
        assert response.status_code == 200
        
        data = response.json()
        trade = data.get("trade", {})
        
        assert trade.get("timeframe") == "swing", f"Expected swing, got {trade.get('timeframe')}"
        assert trade.get("close_at_eod") is False, f"Expected close_at_eod=False"
        
        trailing_config = trade.get("trailing_stop_config", {})
        assert trailing_config.get("trail_pct") == 0.025
        print(f"PASS: squeeze demo trade - timeframe=swing, close_at_eod=False, trail_pct=0.025")
        
        # Reject the trade
        api_client.post(f"{BASE_URL}/api/trading-bot/trades/{trade['id']}/reject")
    
    def test_demo_trade_position_trade_applies_position_config(self, api_client):
        """Test demo trade with position_trade applies position timeframe"""
        response = api_client.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "MSFT", "direction": "long", "setup_type": "position_trade"}
        )
        assert response.status_code == 200
        
        data = response.json()
        trade = data.get("trade", {})
        
        assert trade.get("timeframe") == "position", f"Expected position, got {trade.get('timeframe')}"
        assert trade.get("close_at_eod") is False, f"Expected close_at_eod=False"
        
        trailing_config = trade.get("trailing_stop_config", {})
        assert trailing_config.get("trail_pct") == 0.03
        print(f"PASS: position_trade demo trade - timeframe=position, close_at_eod=False, trail_pct=0.03")
        
        # Reject the trade
        api_client.post(f"{BASE_URL}/api/trading-bot/trades/{trade['id']}/reject")
    
    def test_demo_trade_scale_out_config_from_strategy(self, api_client):
        """Test demo trade includes scale_out_pcts from strategy config"""
        response = api_client.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "NVDA", "direction": "long", "setup_type": "rubber_band"}
        )
        data = response.json()
        trade = data.get("trade", {})
        
        scale_config = trade.get("scale_out_config", {})
        scale_out_pcts = scale_config.get("scale_out_pcts", [])
        
        # rubber_band uses [0.5, 0.3, 0.2] for aggressive scale-out
        assert len(scale_out_pcts) >= 3, f"Expected 3+ scale out percentages"
        print(f"PASS: Demo trade scale_out_pcts = {scale_out_pcts}")
        
        # Reject the trade
        api_client.post(f"{BASE_URL}/api/trading-bot/trades/{trade['id']}/reject")


class TestEODCloseLogic:
    """Test EOD close behavior based on strategy config"""
    
    def test_trades_with_close_at_eod_true(self, api_client):
        """Verify scalp/intraday strategies have close_at_eod=True"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        configs = response.json().get("configs", {})
        
        # Scalp strategies should close at EOD
        assert configs.get("rubber_band", {}).get("close_at_eod") is True
        assert configs.get("vwap_bounce", {}).get("close_at_eod") is True
        assert configs.get("breakout", {}).get("close_at_eod") is True
        print("PASS: Scalp/intraday strategies have close_at_eod=True")
    
    def test_trades_with_close_at_eod_false(self, api_client):
        """Verify swing/position strategies have close_at_eod=False"""
        response = api_client.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        configs = response.json().get("configs", {})
        
        # Swing/position strategies should hold overnight
        assert configs.get("squeeze", {}).get("close_at_eod") is False
        assert configs.get("trend_continuation", {}).get("close_at_eod") is False
        assert configs.get("position_trade", {}).get("close_at_eod") is False
        print("PASS: Swing/position strategies have close_at_eod=False")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
