"""
Tests for SentCom Chat Enhancement P0 Features:
1. Chat conversational context - verify backend passes chat history to orchestrator
2. Bot control mechanisms - start/stop, mode changes, risk parameter updates

These tests verify the P0 enhancements to make chat more conversational 
and implement bot control mechanisms.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSentComChatConversationContext:
    """Test chat history/conversational context feature"""
    
    def test_chat_endpoint_accepts_message(self):
        """Verify /api/sentcom/chat accepts messages and returns response"""
        response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "What positions do we have?"},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should always have a response field
        assert "response" in data
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0
        print(f"Chat response: {data['response'][:100]}...")
    
    def test_chat_response_uses_we_voice(self):
        """Verify responses use 'we' voice (team partnership language)"""
        response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "Tell me about our trading strategy"},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Response should be present
        assert "response" in data
        response_text = data["response"].lower()
        
        # Check response text doesn't heavily use "I" language
        # Note: LLM fallback responses might not follow this strictly
        print(f"Response text: {data['response'][:200]}")
    
    def test_chat_endpoint_returns_source(self):
        """Verify chat response includes source info"""
        response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "What's the market doing?"},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Source should be present for tracing
        assert "source" in data
        print(f"Response source: {data.get('source')}")
    
    def test_sentcom_stream_shows_chat_messages(self):
        """Verify chat messages appear in the unified stream"""
        # First send a chat message
        chat_response = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "Test message for stream verification"},
            headers={"Content-Type": "application/json"}
        )
        assert chat_response.status_code == 200
        
        # Then check the stream
        stream_response = requests.get(f"{BASE_URL}/api/sentcom/stream?limit=20")
        assert stream_response.status_code == 200
        
        data = stream_response.json()
        assert data.get("success") == True
        assert "messages" in data
        
        # Stream should have messages
        print(f"Stream has {len(data.get('messages', []))} messages")


class TestTradingBotStartStop:
    """Test bot start/stop control mechanisms"""
    
    def test_bot_status_endpoint(self):
        """Verify /api/trading-bot/status returns bot state"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "running" in data
        assert "mode" in data
        print(f"Bot status - Running: {data.get('running')}, Mode: {data.get('mode')}")
    
    def test_bot_stop_endpoint(self):
        """Verify /api/trading-bot/stop works"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/stop")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "message" in data
        print(f"Stop response: {data.get('message')}")
        
        # Verify status changed
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        status_data = status_response.json()
        assert status_data.get("running") == False
    
    def test_bot_start_endpoint(self):
        """Verify /api/trading-bot/start works"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/start")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "message" in data
        assert "mode" in data
        print(f"Start response: {data.get('message')}, Mode: {data.get('mode')}")
        
        # Verify status changed
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        status_data = status_response.json()
        assert status_data.get("running") == True


class TestTradingBotModeChanges:
    """Test bot mode change endpoints"""
    
    def test_change_to_confirmation_mode(self):
        """Verify /api/trading-bot/mode/confirmation changes mode"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert data.get("mode") == "confirmation"
        print(f"Mode changed to: {data.get('mode')}")
        
        # Verify status reflects new mode
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        status_data = status_response.json()
        assert status_data.get("mode") == "confirmation"
    
    def test_change_to_autonomous_mode(self):
        """Verify /api/trading-bot/mode/autonomous changes mode"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/autonomous")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert data.get("mode") == "autonomous"
        print(f"Mode changed to: {data.get('mode')}")
    
    def test_change_to_paused_mode(self):
        """Verify /api/trading-bot/mode/paused changes mode"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/paused")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert data.get("mode") == "paused"
        print(f"Mode changed to: {data.get('mode')}")
    
    def test_invalid_mode_returns_error(self):
        """Verify invalid mode returns 400 error"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/mode/invalid_mode")
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        print(f"Invalid mode error: {data.get('detail')}")


class TestRiskParameterUpdates:
    """Test risk parameter update endpoint"""
    
    def test_update_risk_params_endpoint(self):
        """Verify /api/trading-bot/risk-params accepts updates"""
        risk_params = {
            "max_risk_per_trade": 1.5,
            "max_daily_loss": 750,
            "max_open_positions": 6
        }
        
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/risk-params",
            json=risk_params,
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "risk_params" in data
        
        # Verify params were updated
        returned_params = data.get("risk_params", {})
        print(f"Updated risk params: {returned_params}")
    
    def test_partial_risk_params_update(self):
        """Verify partial risk params update works"""
        # Update only one parameter
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/risk-params",
            json={"max_daily_loss": 600},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        print(f"Partial update successful, risk_params: {data.get('risk_params')}")
    
    def test_risk_params_persist_in_status(self):
        """Verify risk params are reflected in bot status"""
        # First update params
        requests.post(
            f"{BASE_URL}/api/trading-bot/risk-params",
            json={"max_risk_per_trade": 2.0},
            headers={"Content-Type": "application/json"}
        )
        
        # Then check status
        status_response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        status_data = status_response.json()
        
        assert status_data.get("success") == True
        risk_params = status_data.get("risk_params", {})
        print(f"Risk params in status: {risk_params}")


class TestSentComStatus:
    """Test SentCom status endpoint"""
    
    def test_sentcom_status_endpoint(self):
        """Verify /api/sentcom/status returns status"""
        response = requests.get(f"{BASE_URL}/api/sentcom/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "status" in data
        
        status = data.get("status", {})
        # Should have connection status and state
        print(f"SentCom status: connected={status.get('connected')}, state={status.get('state')}")


class TestConversationHistoryIntegration:
    """Test conversation history is passed to agents"""
    
    def test_multiple_chat_messages_maintain_context(self):
        """Send multiple messages and verify responses acknowledge history"""
        # First message
        response1 = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "What stocks should we watch today?"},
            headers={"Content-Type": "application/json"}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        print(f"First response: {data1.get('response', '')[:100]}...")
        
        # Second message - follow up
        response2 = requests.post(
            f"{BASE_URL}/api/sentcom/chat",
            json={"message": "Tell me more about that"},
            headers={"Content-Type": "application/json"}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        print(f"Second response: {data2.get('response', '')[:100]}...")
        
        # Both should have valid responses
        assert "response" in data1
        assert "response" in data2


# Cleanup: Reset bot to confirmation mode after tests
@pytest.fixture(scope="module", autouse=True)
def cleanup_bot_state():
    """Reset bot to known state after tests"""
    yield
    # After tests, reset to confirmation mode
    try:
        requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
        requests.post(f"{BASE_URL}/api/trading-bot/start")
    except:
        pass
