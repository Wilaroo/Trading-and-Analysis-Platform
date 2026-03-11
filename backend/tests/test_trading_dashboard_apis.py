"""
Test Trading Dashboard APIs - Tests for the new Trading Dashboard page endpoints
Tests: Order Queue Status, Bot Status, Pushed Data endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTradingDashboardAPIs:
    """Tests for Trading Dashboard page API endpoints"""
    
    def test_order_queue_status_returns_success(self):
        """Test /api/ib/orders/queue/status returns queue data"""
        response = requests.get(f"{BASE_URL}/api/ib/orders/queue/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "pending_count" in data
        assert "executing_count" in data
        assert "completed_count" in data
        assert "pusher_active" in data
        assert isinstance(data["pending_count"], int)
        assert isinstance(data["executing_count"], int)
        assert isinstance(data["completed_count"], int)
        print(f"✓ Order Queue Status: pending={data['pending_count']}, executing={data['executing_count']}, completed={data['completed_count']}, pusher_active={data['pusher_active']}")
    
    def test_trading_bot_status_returns_success(self):
        """Test /api/trading-bot/status returns bot status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "running" in data
        assert "mode" in data
        assert "risk_params" in data
        assert "daily_stats" in data
        assert isinstance(data["running"], bool)
        assert data["mode"] in ["autonomous", "confirmation", "paused"]
        print(f"✓ Trading Bot Status: running={data['running']}, mode={data['mode']}")
    
    def test_trading_bot_daily_stats_structure(self):
        """Test daily_stats in bot status has expected structure"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        daily_stats = data.get("daily_stats", {})
        
        # Verify expected daily stats fields
        expected_fields = ["trades_executed", "trades_won", "trades_lost", "net_pnl", "win_rate"]
        for field in expected_fields:
            assert field in daily_stats, f"Missing {field} in daily_stats"
        
        print(f"✓ Daily Stats: trades={daily_stats.get('trades_executed', 0)}, win_rate={daily_stats.get('win_rate', 0)}%")
    
    def test_ib_pushed_data_returns_success(self):
        """Test /api/ib/pushed-data returns positions data structure"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200
        
        data = response.json()
        assert "connected" in data
        assert "quotes" in data
        assert "positions" in data
        assert "account" in data
        
        # Verify data types
        assert isinstance(data["connected"], bool)
        assert isinstance(data["quotes"], dict)
        assert isinstance(data["positions"], list)
        assert isinstance(data["account"], dict)
        
        print(f"✓ IB Pushed Data: connected={data['connected']}, positions_count={len(data['positions'])}, quotes_count={len(data['quotes'])}")
    
    def test_ib_status_endpoint(self):
        """Test /api/ib/status returns connection status"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "connected" in data
        assert isinstance(data["connected"], bool)
        
        # Pusher info should be present
        if "pusher" in data:
            print(f"✓ IB Status: connected={data['connected']}, pusher={data.get('pusher')}")
        else:
            print(f"✓ IB Status: connected={data['connected']}")
    
    def test_risk_params_structure(self):
        """Test risk parameters in bot status have expected structure"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        risk_params = data.get("risk_params", {})
        
        # Verify expected risk param fields
        expected_fields = ["max_risk_per_trade", "max_daily_loss", "max_position_pct", "max_open_positions"]
        for field in expected_fields:
            assert field in risk_params, f"Missing {field} in risk_params"
        
        print(f"✓ Risk Params: max_risk=${risk_params.get('max_risk_per_trade', 0)}, max_daily_loss=${risk_params.get('max_daily_loss', 0)}")
    
    def test_strategy_configs_present(self):
        """Test strategy configs are present in bot status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "strategy_configs" in data
        configs = data["strategy_configs"]
        assert isinstance(configs, dict)
        assert len(configs) > 0, "No strategy configs found"
        
        # Check first config has expected fields
        first_config = list(configs.values())[0]
        assert "timeframe" in first_config
        print(f"✓ Strategy Configs: {len(configs)} strategies configured")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
