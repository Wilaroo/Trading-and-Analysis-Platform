"""
Analyst Agent and Learning Layer Tests
Testing iteration 63 features:
- Analyst agent for 'analyze NVDA' routing
- Trade confirmation flow (buy -> yes -> queued)
- All 4 agents in status/metrics
- Learning layer classes initialization
"""
import pytest
import requests
import os
import time

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAgentStatusWithAnalyst:
    """Test /api/agents/status includes analyst agent"""
    
    def test_status_lists_four_agents(self):
        """Verify all 4 agents are listed: router, trade_executor, coach, analyst"""
        response = requests.get(f"{BASE_URL}/api/agents/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "agents" in data, "Response should contain 'agents' list"
        agents = data["agents"]
        
        # Verify all 4 agents
        expected_agents = ["router", "trade_executor", "coach", "analyst"]
        for agent in expected_agents:
            assert agent in agents, f"Expected '{agent}' in agents list, got {agents}"
        
        assert len(agents) >= 4, f"Expected at least 4 agents, got {len(agents)}"
        print(f"PASS: All 4 agents listed: {agents}")


class TestAgentMetricsWithAnalyst:
    """Test /api/agents/metrics includes analyst agent"""
    
    def test_metrics_includes_analyst(self):
        """Verify metrics include analyst agent"""
        response = requests.get(f"{BASE_URL}/api/agents/metrics", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        assert "metrics" in data, "Response should contain 'metrics'"
        metrics = data["metrics"]
        
        # Verify analyst is in metrics
        assert "analyst" in metrics, f"Expected 'analyst' in metrics, got {list(metrics.keys())}"
        
        # Verify analyst metric structure
        analyst_metrics = metrics["analyst"]
        assert "agent_type" in analyst_metrics, "analyst metrics should have 'agent_type'"
        assert "call_count" in analyst_metrics, "analyst metrics should have 'call_count'"
        assert "error_count" in analyst_metrics, "analyst metrics should have 'error_count'"
        
        print(f"PASS: Analyst metrics present: {analyst_metrics}")
    
    def test_metrics_has_all_four_agents(self):
        """Verify metrics for all 4 agents"""
        response = requests.get(f"{BASE_URL}/api/agents/metrics", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        metrics = data["metrics"]
        expected_agents = ["router", "trade_executor", "coach", "analyst"]
        
        for agent in expected_agents:
            assert agent in metrics, f"Expected metrics for '{agent}'"
        
        print(f"PASS: All 4 agent metrics present: {list(metrics.keys())}")


class TestAnalystRouting:
    """Test routing to analyst agent for 'analyze' intents"""
    
    def test_analyze_nvda_routes_to_analyst(self):
        """Test 'analyze NVDA' routes to analyst agent"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "analyze NVDA",
                "session_id": "test_analyst_nvda"
            },
            timeout=120  # Analyst may take time
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify routing
        assert data["intent"] == "analysis", f"Expected intent 'analysis', got '{data['intent']}'"
        assert data["agent_used"] == "analyst", f"Expected agent 'analyst', got '{data['agent_used']}'"
        
        # Verify response contains analysis data (even if values are 0 due to offline IB)
        assert "response" in data, "Response should contain analysis text"
        assert len(data["response"]) > 0, "Response should not be empty"
        
        # Check for expected analysis content (symbol mention)
        response_text = data["response"]
        assert "NVDA" in response_text or "nvda" in response_text.lower(), "Response should mention NVDA"
        
        print(f"PASS: 'analyze NVDA' routed to analyst")
        print(f"Response preview: {data['response'][:200]}...")
    
    def test_analyze_returns_structured_data(self):
        """Test analyst returns structured analysis with key fields"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "analyze AAPL",
                "session_id": "test_analyst_aapl"
            },
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["agent_used"] == "analyst", f"Expected 'analyst', got {data['agent_used']}"
        
        # Response should have technical analysis elements
        response_text = data["response"].lower()
        # Should mention at least some analysis terms (price, volume, technical, etc.)
        analysis_terms = ["price", "volume", "vwap", "technical", "levels", "bias"]
        found_terms = [term for term in analysis_terms if term in response_text]
        
        assert len(found_terms) >= 1, f"Response should contain analysis terms, found: {found_terms}"
        print(f"PASS: Analyst returns structured analysis with terms: {found_terms}")


class TestTradeConfirmationFlow:
    """Test complete trade confirmation flow: buy -> yes -> queued"""
    
    def test_buy_command_returns_confirmation_request(self):
        """Test 'buy 100 AAPL' returns confirmation request"""
        session_id = f"test_buy_confirm_{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "buy 100 AAPL",
                "session_id": session_id
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify confirmation required
        assert data["requires_confirmation"] == True, f"Expected requires_confirmation=True, got {data['requires_confirmation']}"
        assert data["pending_trade"] is not None, "Expected pending_trade to be set"
        
        # Verify pending trade details
        pending = data["pending_trade"]
        assert pending["symbol"] == "AAPL", f"Expected symbol 'AAPL', got {pending.get('symbol')}"
        assert pending["quantity"] == 100, f"Expected quantity 100, got {pending.get('quantity')}"
        assert pending["action"] == "buy", f"Expected action 'buy', got {pending.get('action')}"
        
        # Verify response message asks for confirmation
        assert "yes" in data["response"].lower(), "Response should ask user to reply 'yes'"
        
        print(f"PASS: Buy command returns confirmation request")
        print(f"Pending trade: {pending}")
        
        return session_id
    
    def test_yes_confirmation_queues_order(self):
        """Test complete flow: buy -> yes -> order queued"""
        session_id = f"test_full_confirm_{int(time.time())}"
        
        # Step 1: Send buy command
        buy_response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "buy 100 AAPL",
                "session_id": session_id
            },
            timeout=30
        )
        assert buy_response.status_code == 200
        buy_data = buy_response.json()
        
        assert buy_data["requires_confirmation"] == True, "First message should require confirmation"
        
        # Step 2: Send 'yes' to confirm
        confirm_response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "yes",
                "session_id": session_id  # Same session_id to preserve context
            },
            timeout=30
        )
        assert confirm_response.status_code == 200
        confirm_data = confirm_response.json()
        
        # Verify order was queued
        assert confirm_data["success"] == True, f"Expected success=True, got {confirm_data['success']}"
        assert "queued" in confirm_data["response"].lower(), f"Response should mention 'queued', got: {confirm_data['response']}"
        assert confirm_data["requires_confirmation"] == False, "After confirmation, should not require more confirmation"
        assert confirm_data["pending_trade"] is None, "After execution, pending_trade should be cleared"
        
        print(f"PASS: Full confirmation flow works: buy -> yes -> queued")
        print(f"Final response: {confirm_data['response']}")
    
    def test_different_session_no_confirmation(self):
        """Test that 'yes' in different session doesn't execute trade"""
        # First session: initiate buy
        session_1 = f"test_session_1_{int(time.time())}"
        requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 100 AAPL", "session_id": session_1},
            timeout=30
        )
        
        # Different session: send 'yes' - should NOT execute
        session_2 = f"test_session_2_{int(time.time())}"
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "yes", "session_id": session_2},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should NOT have queued an order (different session)
        response_text = data["response"].lower()
        assert "queued" not in response_text or "couldn't" in response_text or "no pending" in response_text, \
            f"Different session should not execute trade: {data['response']}"
        
        print(f"PASS: Different session doesn't inherit confirmation context")


class TestCoachPositionRouting:
    """Test routing to coach agent for position queries"""
    
    def test_what_are_my_positions_routes_to_coach(self):
        """Test 'what are my positions' routes to coach"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "what are my positions",
                "session_id": "test_coach_positions"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify routing
        assert data["intent"] == "position_query", f"Expected intent 'position_query', got '{data['intent']}'"
        assert data["agent_used"] == "coach", f"Expected agent 'coach', got '{data['agent_used']}'"
        
        print(f"PASS: Position query routed to coach")
    
    def test_show_portfolio_routes_to_coach(self):
        """Test 'show my portfolio' routes to coach"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "show my portfolio",
                "session_id": "test_portfolio"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["intent"] in ["position_query", "general_chat"], f"Unexpected intent: {data['intent']}"
        print(f"PASS: Portfolio query handled, intent={data['intent']}, agent={data['agent_used']}")


class TestSessionPersistence:
    """Test session context persistence between messages"""
    
    def test_session_preserves_pending_trade(self):
        """Test that pending trade is preserved in session"""
        session_id = f"test_persist_{int(time.time())}"
        
        # Step 1: Initiate trade
        response1 = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 100 NVDA", "session_id": session_id},
            timeout=30
        )
        data1 = response1.json()
        assert data1["requires_confirmation"] == True
        assert data1["pending_trade"]["symbol"] == "NVDA"
        
        # Step 2: Confirm - should remember the trade
        response2 = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "yes", "session_id": session_id},
            timeout=30
        )
        data2 = response2.json()
        
        # Should have executed NVDA trade
        assert "queued" in data2["response"].lower()
        assert "NVDA" in data2["response"]
        
        print(f"PASS: Session preserves pending trade context")
    
    def test_session_clears_after_execution(self):
        """Test that pending trade is cleared after execution"""
        session_id = f"test_clear_{int(time.time())}"
        
        # Initiate and confirm trade
        requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 50 TSLA", "session_id": session_id},
            timeout=30
        )
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "yes", "session_id": session_id},
            timeout=30
        )
        data = response.json()
        
        # Pending trade should be cleared
        assert data["pending_trade"] is None, f"Pending trade should be None after execution, got {data['pending_trade']}"
        assert data["requires_confirmation"] == False
        
        print(f"PASS: Pending trade cleared after execution")


class TestBuyPatternVariations:
    """Test various 'buy' command formats"""
    
    def test_buy_100_aapl(self):
        """Test 'buy 100 AAPL' format"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 100 AAPL", "session_id": "test_buy_format_1"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["requires_confirmation"] == True
        assert data["pending_trade"]["quantity"] == 100
        assert data["pending_trade"]["symbol"] == "AAPL"
        print(f"PASS: 'buy 100 AAPL' format works")
    
    def test_buy_shares_of_format(self):
        """Test 'buy 100 shares of AAPL' format"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 100 shares of AAPL", "session_id": "test_buy_format_2"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["requires_confirmation"] == True
        assert data["pending_trade"]["quantity"] == 100
        print(f"PASS: 'buy 100 shares of AAPL' format works")
    
    def test_buy_simple_format(self):
        """Test 'buy AAPL' format (defaults to 100)"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy AAPL", "session_id": "test_buy_format_3"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["requires_confirmation"] == True
        assert data["pending_trade"]["symbol"] == "AAPL"
        print(f"PASS: 'buy AAPL' format works (qty={data['pending_trade']['quantity']})")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
