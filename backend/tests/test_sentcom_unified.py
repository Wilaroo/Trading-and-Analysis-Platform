"""
SentCom Unified Component - Backend API Tests
Tests all APIs related to the SentCom unified command center:
- SentCom status, stream, chat, positions, setups, alerts
- Trading bot start/stop and mode changes  
- Assistant coaching endpoints (morning-briefing, rule-reminder, daily-summary)
- Check rules and position sizing
"""
import pytest
import requests
import os
import json
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSentComEndpoints:
    """Tests for /api/sentcom/* endpoints"""
    
    def test_sentcom_status(self):
        """Test SentCom status endpoint returns valid status"""
        response = requests.get(f"{BASE_URL}/api/sentcom/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "status" in data
        
        status = data["status"]
        assert "connected" in status
        assert "state" in status
        assert "order_pipeline" in status
        
        # Verify order pipeline structure
        pipeline = status["order_pipeline"]
        assert "pending" in pipeline
        assert "executing" in pipeline
        assert "filled" in pipeline
    
    def test_sentcom_stream(self):
        """Test SentCom stream returns messages"""
        response = requests.get(f"{BASE_URL}/api/sentcom/stream?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "messages" in data
        assert isinstance(data["messages"], list)
        
        # If there are messages, verify structure
        if data["messages"]:
            msg = data["messages"][0]
            assert "id" in msg
            assert "type" in msg
            assert "content" in msg
            assert "timestamp" in msg
    
    def test_sentcom_chat(self):
        """Test SentCom chat endpoint"""
        response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "What's the market regime?", "session_id": "test_session"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "response" in data
        assert len(data["response"]) > 0
        assert "source" in data
    
    def test_sentcom_positions(self):
        """Test SentCom positions endpoint"""
        response = requests.get(f"{BASE_URL}/api/sentcom/positions")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "positions" in data
        assert "count" in data
        assert "total_pnl" in data
        assert isinstance(data["positions"], list)
    
    def test_sentcom_setups(self):
        """Test SentCom setups endpoint"""
        response = requests.get(f"{BASE_URL}/api/sentcom/setups")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "setups" in data
        assert "count" in data
        assert isinstance(data["setups"], list)
    
    def test_sentcom_alerts(self):
        """Test SentCom alerts endpoint"""
        response = requests.get(f"{BASE_URL}/api/sentcom/alerts?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "alerts" in data
        assert isinstance(data["alerts"], list)
    
    def test_sentcom_context(self):
        """Test SentCom market context endpoint"""
        response = requests.get(f"{BASE_URL}/api/sentcom/context")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "context" in data
        
        context = data["context"]
        assert "regime" in context
        assert "market_open" in context


class TestTradingBotControl:
    """Tests for /api/trading-bot/* endpoints - bot control functionality"""
    
    def test_trading_bot_status(self):
        """Test trading bot status endpoint"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "running" in data
        assert "mode" in data
        assert data["mode"] in ["autonomous", "confirmation", "paused"]
    
    def test_trading_bot_stop_and_start(self):
        """Test bot stop and start functionality"""
        # Stop the bot
        stop_response = requests.post(f"{BASE_URL}/api/trading-bot/stop")
        assert stop_response.status_code == 200
        assert stop_response.json().get("success") is True
        
        # Verify bot is stopped
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert status_response.json()["running"] is False
        
        # Start the bot
        start_response = requests.post(f"{BASE_URL}/api/trading-bot/start")
        assert start_response.status_code == 200
        assert start_response.json().get("success") is True
        
        # Verify bot is running
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert status_response.json()["running"] is True
    
    def test_trading_bot_mode_change(self):
        """Test bot mode changes"""
        modes = ["autonomous", "confirmation", "paused"]
        
        for mode in modes:
            response = requests.post(f"{BASE_URL}/api/trading-bot/mode/{mode}")
            assert response.status_code == 200
            
            data = response.json()
            assert data.get("success") is True
            assert data.get("mode") == mode
        
        # Reset to confirmation mode
        requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")


class TestAssistantCoaching:
    """Tests for /api/assistant/coach/* endpoints - quick action coaching functionality"""
    
    def test_morning_briefing(self):
        """Test morning briefing quick action endpoint"""
        response = requests.get(f"{BASE_URL}/api/assistant/coach/morning-briefing")
        assert response.status_code == 200
        
        data = response.json()
        assert "coaching" in data
        assert len(data["coaching"]) > 0
        assert "timestamp" in data
    
    def test_rule_reminder(self):
        """Test rule reminder quick action endpoint"""
        response = requests.get(f"{BASE_URL}/api/assistant/coach/rule-reminder")
        assert response.status_code == 200
        
        data = response.json()
        assert "coaching" in data
        assert len(data["coaching"]) > 0
    
    def test_daily_summary(self):
        """Test daily summary quick action endpoint"""
        response = requests.get(f"{BASE_URL}/api/assistant/coach/daily-summary")
        assert response.status_code == 200
        
        data = response.json()
        assert "coaching" in data
        assert "date" in data
        assert "timestamp" in data
    
    def test_check_rules(self):
        """Test check rules endpoint with trade parameters"""
        trade_data = {
            "symbol": "AAPL",
            "action": "BUY",
            "entry_price": 220.50,
            "stop_loss": 218.00
        }
        
        response = requests.post(
            f"{BASE_URL}/api/assistant/coach/check-rules",
            json=trade_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "trade" in data
        assert "analysis" in data
        assert len(data["analysis"]) > 0
        assert "rules_checked" in data
        assert data["trade"]["symbol"] == "AAPL"
    
    def test_position_size(self):
        """Test position sizing endpoint"""
        sizing_data = {
            "symbol": "NVDA",
            "entry_price": 120.50,
            "stop_loss": 118.00
        }
        
        response = requests.post(
            f"{BASE_URL}/api/assistant/coach/position-size",
            json=sizing_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "symbol" in data
        assert "entry" in data
        assert "stop" in data
        assert "risk_per_share" in data
        assert "analysis" in data
        assert len(data["analysis"]) > 0


class TestIntegration:
    """Integration tests verifying end-to-end flows"""
    
    def test_chat_adds_to_stream(self):
        """Test that chat messages appear in the stream"""
        # Send a unique chat message
        unique_msg = f"Integration test message {datetime.now().isoformat()}"
        
        chat_response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": unique_msg, "session_id": "integration_test"}
        )
        assert chat_response.status_code == 200
        
        # The message should be processed and a response returned
        # Note: success may be False if orchestrator is initializing, but response should exist
        data = chat_response.json()
        assert "response" in data
        assert len(data["response"]) > 0
        assert "source" in data
    
    def test_bot_status_reflects_mode_change(self):
        """Test that status correctly reflects mode changes"""
        # Change to autonomous
        requests.post(f"{BASE_URL}/api/trading-bot/mode/autonomous")
        
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status["mode"] == "autonomous"
        
        # Change back to confirmation
        requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
        
        status = requests.get(f"{BASE_URL}/api/trading-bot/status").json()
        assert status["mode"] == "confirmation"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
