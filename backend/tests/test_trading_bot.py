"""
Trading Bot API Tests
Tests for autonomous trading bot endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTradingBotStatus:
    """Test bot status endpoint"""
    
    def test_get_status_returns_200(self):
        """GET /api/trading-bot/status returns 200 with bot status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "running" in data
        assert "mode" in data
        assert "risk_params" in data
        assert "daily_stats" in data
        
    def test_status_contains_risk_params(self):
        """Status contains correct risk parameters"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        data = response.json()
        
        risk_params = data.get("risk_params", {})
        assert risk_params.get("max_risk_per_trade") == 2500.0
        assert risk_params.get("max_daily_loss") == 5000.0
        assert risk_params.get("starting_capital") == 1000000.0
        assert risk_params.get("max_position_pct") == 10.0
        assert risk_params.get("max_open_positions") == 5
        assert risk_params.get("min_risk_reward") == 1.5
        
    def test_status_contains_daily_stats(self):
        """Status contains daily statistics"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        data = response.json()
        
        daily_stats = data.get("daily_stats", {})
        assert "date" in daily_stats
        assert "trades_executed" in daily_stats
        assert "trades_won" in daily_stats
        assert "trades_lost" in daily_stats
        assert "net_pnl" in daily_stats
        assert "win_rate" in daily_stats
        assert "daily_limit_hit" in daily_stats


class TestTradingBotControl:
    """Test bot start/stop endpoints"""
    
    def test_start_bot(self):
        """POST /api/trading-bot/start starts the bot"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/start")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "mode" in data
        
        # Verify bot is running
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status.get("running") == True
        
    def test_stop_bot(self):
        """POST /api/trading-bot/stop stops the bot"""
        # First start the bot
        requests.post(f"{BASE_URL}/api/trading-bot/start")
        
        # Then stop it
        response = requests.post(f"{BASE_URL}/api/trading-bot/stop")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        # Verify bot is stopped
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status.get("running") == False


class TestTradingBotModes:
    """Test bot mode switching endpoints"""
    
    def test_set_autonomous_mode(self):
        """POST /api/trading-bot/mode/autonomous switches to autonomous mode"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/autonomous")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("mode") == "autonomous"
        
        # Verify mode changed
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status.get("mode") == "autonomous"
        
    def test_set_confirmation_mode(self):
        """POST /api/trading-bot/mode/confirmation switches to confirmation mode"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("mode") == "confirmation"
        
        # Verify mode changed
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status.get("mode") == "confirmation"
        
    def test_set_paused_mode(self):
        """POST /api/trading-bot/mode/paused pauses the bot"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/paused")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("mode") == "paused"
        
        # Verify mode changed
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status.get("mode") == "paused"
        
    def test_invalid_mode_returns_400(self):
        """POST /api/trading-bot/mode/invalid returns 400"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/invalid_mode")
        assert response.status_code == 400


class TestTradingBotTrades:
    """Test trade listing endpoints"""
    
    def test_get_pending_trades(self):
        """GET /api/trading-bot/trades/pending returns pending trades list"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "count" in data
        assert "trades" in data
        assert isinstance(data.get("trades"), list)
        
    def test_get_open_trades(self):
        """GET /api/trading-bot/trades/open returns open positions list"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "count" in data
        assert "trades" in data
        assert isinstance(data.get("trades"), list)
        
    def test_get_closed_trades(self):
        """GET /api/trading-bot/trades/closed returns closed trades history"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "count" in data
        assert "trades" in data
        assert isinstance(data.get("trades"), list)
        
    def test_get_closed_trades_with_limit(self):
        """GET /api/trading-bot/trades/closed?limit=10 respects limit parameter"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert len(data.get("trades", [])) <= 10


class TestTradingBotAccount:
    """Test account info endpoint"""
    
    def test_get_account_info(self):
        """GET /api/trading-bot/account returns Alpaca account info"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/account")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "account" in data
        assert "positions" in data
        
        account = data.get("account", {})
        # Alpaca paper account should have these fields
        assert "buying_power" in account
        assert "cash" in account
        assert "equity" in account


class TestTradingBotStats:
    """Test statistics endpoints"""
    
    def test_get_daily_stats(self):
        """GET /api/trading-bot/stats/daily returns daily statistics"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/stats/daily")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "stats" in data
        
        stats = data.get("stats", {})
        assert "date" in stats
        assert "trades_executed" in stats
        assert "net_pnl" in stats
        
    def test_get_performance_stats(self):
        """GET /api/trading-bot/stats/performance returns performance statistics"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/stats/performance")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "stats" in data
        
        stats = data.get("stats", {})
        assert "total_trades" in stats
        assert "total_pnl" in stats
        assert "win_rate" in stats


class TestTradingBotConfig:
    """Test configuration endpoints"""
    
    def test_update_risk_params(self):
        """POST /api/trading-bot/risk-params updates risk parameters"""
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/risk-params",
            json={"max_risk_per_trade": 3000.0}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "risk_params" in data
        assert data["risk_params"]["max_risk_per_trade"] == 3000.0
        
        # Reset to original value
        requests.post(
            f"{BASE_URL}/api/trading-bot/risk-params",
            json={"max_risk_per_trade": 2500.0}
        )
        
    def test_update_bot_config(self):
        """POST /api/trading-bot/config updates bot configuration"""
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/config",
            json={
                "enabled_setups": ["rubber_band", "breakout"],
                "scan_interval": 60
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        # Reset to original
        requests.post(
            f"{BASE_URL}/api/trading-bot/config",
            json={
                "enabled_setups": ["rubber_band", "breakout", "vwap_bounce", "squeeze"],
                "scan_interval": 30
            }
        )


class TestTradingBotPositions:
    """Test broker positions endpoint"""
    
    def test_get_broker_positions(self):
        """GET /api/trading-bot/positions returns broker positions"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/positions")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "positions" in data
        assert isinstance(data.get("positions"), list)


# Reset bot to confirmation mode after all tests
@pytest.fixture(scope="session", autouse=True)
def cleanup_after_tests():
    """Reset bot state after all tests"""
    yield
    # Reset to confirmation mode and stop bot
    requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
    requests.post(f"{BASE_URL}/api/trading-bot/stop")
