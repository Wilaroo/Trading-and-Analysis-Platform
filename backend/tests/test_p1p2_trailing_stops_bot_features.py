"""
Test P1/P2 Features: Trailing Stops, Auto-Trail Positions, Bot Thoughts, Dashboard Data
================================================================================

Tests for:
- POST /api/smart-stops/calculate-trailing-stop
- POST /api/smart-stops/auto-trail-positions
- GET /api/trading-bot/thoughts
- GET /api/trading-bot/dashboard-data
- GET /api/ib/historical/{symbol} (Charts tab data)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTrailingStopEndpoints:
    """Tests for new trailing stop calculation endpoints"""
    
    def test_calculate_trailing_stop_atr_mode(self):
        """Test trailing stop calculation with ATR mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate-trailing-stop",
            params={
                "symbol": "AAPL",
                "entry_price": 200,
                "current_price": 210,
                "current_stop": 195,
                "highest_price": 212,
                "direction": "long",
                "trailing_mode": "atr"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["symbol"] == "AAPL"
        assert "new_stop" in data
        assert "should_trail" in data
        assert "reasoning" in data
        assert "pnl_pct" in data
        assert "lock_in_profit_pct" in data
        assert "trailing_mode" in data
        assert "peak_price" in data
        print(f"ATR trailing stop: current={data['current_stop']}, new={data['new_stop']}, should_trail={data['should_trail']}")
    
    def test_calculate_trailing_stop_percent_mode(self):
        """Test trailing stop with percent trailing mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate-trailing-stop",
            params={
                "symbol": "NVDA",
                "entry_price": 150,
                "current_price": 160,
                "current_stop": 145,
                "highest_price": 165,
                "direction": "long",
                "trailing_mode": "percent"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["trailing_mode"] == "percent"
        print(f"Percent trailing stop: {data['reasoning']}")
    
    def test_calculate_trailing_stop_chandelier_mode(self):
        """Test trailing stop with chandelier mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate-trailing-stop",
            params={
                "symbol": "TSLA",
                "entry_price": 300,
                "current_price": 320,
                "current_stop": 290,
                "highest_price": 325,
                "direction": "long",
                "trailing_mode": "chandelier"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["trailing_mode"] == "chandelier"
    
    def test_calculate_trailing_stop_parabolic_mode(self):
        """Test trailing stop with parabolic accelerating mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate-trailing-stop",
            params={
                "symbol": "AMD",
                "entry_price": 100,
                "current_price": 110,
                "current_stop": 95,
                "highest_price": 112,
                "direction": "long",
                "trailing_mode": "parabolic"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["trailing_mode"] == "parabolic"
        # Parabolic should tighten with profit
        assert "tightening with profit" in data.get("reasoning", "").lower() or data["should_trail"]
    
    def test_calculate_trailing_stop_short_position(self):
        """Test trailing stop for short position"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate-trailing-stop",
            params={
                "symbol": "META",
                "entry_price": 500,
                "current_price": 480,
                "current_stop": 510,
                "lowest_price": 475,
                "direction": "short",
                "trailing_mode": "atr"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["pnl_pct"] > 0  # Short position should show positive P&L when price is down
        print(f"Short position trailing: {data['reasoning']}")


class TestAutoTrailPositions:
    """Tests for auto-trail all positions endpoint"""
    
    def test_auto_trail_positions_returns_success(self):
        """Test auto-trail endpoint returns success"""
        response = requests.post(f"{BASE_URL}/api/smart-stops/auto-trail-positions")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "positions_analyzed" in data
        assert "recommendations" in data
        assert "message" in data
        print(f"Auto-trail: analyzed {data['positions_analyzed']} positions, {len(data['recommendations'])} recommendations")
    
    def test_auto_trail_recommendations_structure(self):
        """Test that recommendations have correct structure"""
        response = requests.post(f"{BASE_URL}/api/smart-stops/auto-trail-positions")
        
        assert response.status_code == 200
        data = response.json()
        
        for rec in data["recommendations"]:
            assert "symbol" in rec
            assert "direction" in rec
            assert "current_stop" in rec
            assert "suggested_stop" in rec
            assert "pnl_pct" in rec
            assert "lock_in_profit_pct" in rec
            assert "reasoning" in rec
            assert "priority" in rec
            assert rec["priority"] in ["high", "medium", "low"]


class TestBotThoughtsEndpoint:
    """Tests for bot thoughts/reasoning endpoint"""
    
    def test_get_bot_thoughts_success(self):
        """Test bot thoughts endpoint returns successfully"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts", params={"limit": 5})
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "thoughts" in data
        print(f"Got {len(data['thoughts'])} thoughts from bot")
    
    def test_bot_thoughts_structure(self):
        """Test that thoughts have correct structure"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts", params={"limit": 10})
        
        assert response.status_code == 200
        data = response.json()
        
        for thought in data["thoughts"]:
            assert "text" in thought
            assert "timestamp" in thought
            assert "confidence" in thought
            assert "action_type" in thought
            # action_type should be one of expected values
            valid_actions = ["scanning", "entry", "monitoring", "exit", "stop_warning", "watching"]
            assert thought["action_type"] in valid_actions
    
    def test_bot_thoughts_limit(self):
        """Test that limit parameter works"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts", params={"limit": 3})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["thoughts"]) <= 3


class TestDashboardDataEndpoint:
    """Tests for dashboard data endpoint"""
    
    def test_dashboard_data_success(self):
        """Test dashboard data endpoint returns successfully"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "bot_status" in data
        assert "today_pnl" in data
        assert "open_pnl" in data
        assert "open_trades" in data
    
    def test_dashboard_bot_status_structure(self):
        """Test bot status structure in dashboard data"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        
        assert response.status_code == 200
        data = response.json()
        bot_status = data["bot_status"]
        
        assert "running" in bot_status
        assert "mode" in bot_status
        assert "state" in bot_status
    
    def test_dashboard_open_trades_structure(self):
        """Test open trades structure"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        
        assert response.status_code == 200
        data = response.json()
        
        for trade in data["open_trades"]:
            assert "symbol" in trade
            assert "direction" in trade
            assert "status" in trade
            # Optional but commonly present
            if "entry_price" in trade:
                assert isinstance(trade["entry_price"], (int, float))


class TestHistoricalDataEndpoint:
    """Tests for historical data endpoint (Charts tab)"""
    
    def test_historical_data_spy(self):
        """Test historical data for SPY"""
        response = requests.get(
            f"{BASE_URL}/api/ib/historical/SPY",
            params={"duration": "1 D", "bar_size": "5 mins"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "symbol" in data
        assert "bars" in data
        assert len(data["bars"]) > 0
        
        # Check bar structure
        bar = data["bars"][0]
        assert "time" in bar
        assert "open" in bar
        assert "high" in bar
        assert "low" in bar
        assert "close" in bar
        print(f"Got {len(data['bars'])} bars for SPY")
    
    def test_historical_data_different_timeframes(self):
        """Test historical data with different timeframes"""
        timeframes = [
            ("1 D", "1 min"),
            ("1 D", "5 mins"),
            ("2 D", "15 mins"),
            ("5 D", "1 hour"),
        ]
        
        for duration, bar_size in timeframes:
            response = requests.get(
                f"{BASE_URL}/api/ib/historical/AAPL",
                params={"duration": duration, "bar_size": bar_size}
            )
            
            assert response.status_code == 200
            data = response.json()
            # May return empty if IB is busy, but should not error
            assert "bars" in data
            print(f"AAPL {duration}/{bar_size}: {len(data.get('bars', []))} bars")


class TestSmartStopCalculate:
    """Tests for basic smart stop calculation"""
    
    def test_calculate_smart_stop_atr_mode(self):
        """Test basic stop calculation"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                "symbol": "AAPL",
                "entry_price": 200,
                "direction": "long",
                "atr": 4.0,
                "mode": "atr_dynamic"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["stop_price"] < 200  # Stop should be below entry for long
        # Reasoning should mention ATR method
        assert "atr" in data["stop_reasoning"].lower() or "ATR" in data["stop_reasoning"]


class TestBotStatus:
    """Tests for bot status endpoint"""
    
    def test_bot_status(self):
        """Test bot status returns correctly"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "running" in data
        assert "mode" in data
        assert "risk_params" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
