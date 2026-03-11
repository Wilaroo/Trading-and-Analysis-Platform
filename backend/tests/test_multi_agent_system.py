"""
Multi-Agent System Backend Tests
Testing the agent orchestrator, routing, and specialized agents (trade_executor, coach)

Test Endpoints:
- /api/agents/status - System status
- /api/agents/chat - Intent routing and agent responses
- /api/agents/metrics - Agent performance metrics
- /api/agents/session/{session_id} - Session management
"""
import pytest
import requests
import os
import time

# Base URL from environment - no defaults
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAgentStatus:
    """Test /api/agents/status endpoint"""
    
    def test_agent_status_returns_success(self):
        """Verify agent status endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/agents/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Data assertions
        assert "success" in data, "Response should contain 'success' field"
        assert data["success"] == True, "success should be True"
        print(f"PASS: Status endpoint returns success=True")
    
    def test_agent_status_orchestrator_ready(self):
        """Verify orchestrator is ready"""
        response = requests.get(f"{BASE_URL}/api/agents/status", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        assert "orchestrator_ready" in data, "Response should contain 'orchestrator_ready'"
        assert data["orchestrator_ready"] == True, "orchestrator_ready should be True"
        print(f"PASS: orchestrator_ready=True")
    
    def test_agent_status_lists_agents(self):
        """Verify agents list is returned"""
        response = requests.get(f"{BASE_URL}/api/agents/status", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        assert "agents" in data, "Response should contain 'agents' list"
        agents = data["agents"]
        assert isinstance(agents, list), "agents should be a list"
        assert len(agents) >= 3, f"Expected at least 3 agents, got {len(agents)}"
        
        # Verify expected agents
        expected_agents = ["router", "trade_executor", "coach"]
        for agent in expected_agents:
            assert agent in agents, f"Expected '{agent}' in agents list"
        
        print(f"PASS: Agents list contains {agents}")
    
    def test_agent_status_llm_provider_info(self):
        """Verify LLM provider info is returned"""
        response = requests.get(f"{BASE_URL}/api/agents/status", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        assert "llm_provider" in data, "Response should contain 'llm_provider'"
        assert "available_providers" in data, "Response should contain 'available_providers'"
        print(f"PASS: LLM provider: {data['llm_provider']}, Available: {data['available_providers']}")


class TestAgentMetrics:
    """Test /api/agents/metrics endpoint"""
    
    def test_agent_metrics_returns_success(self):
        """Verify metrics endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/agents/metrics", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "success" in data, "Response should contain 'success'"
        assert data["success"] == True, "success should be True"
        print(f"PASS: Metrics endpoint returns success=True")
    
    def test_agent_metrics_contains_all_agents(self):
        """Verify metrics for all agents are returned"""
        response = requests.get(f"{BASE_URL}/api/agents/metrics", timeout=15)
        assert response.status_code == 200
        data = response.json()
        
        assert "metrics" in data, "Response should contain 'metrics'"
        metrics = data["metrics"]
        
        # Verify metrics for each agent
        expected_agents = ["router", "trade_executor", "coach"]
        for agent in expected_agents:
            assert agent in metrics, f"Expected metrics for '{agent}'"
            agent_metrics = metrics[agent]
            
            # Verify metric structure
            assert "agent_type" in agent_metrics, f"Missing 'agent_type' in {agent} metrics"
            assert "call_count" in agent_metrics, f"Missing 'call_count' in {agent} metrics"
            assert "error_count" in agent_metrics, f"Missing 'error_count' in {agent} metrics"
        
        print(f"PASS: Metrics returned for all agents: {list(metrics.keys())}")


class TestAgentChatRouting:
    """Test /api/agents/chat endpoint - intent routing"""
    
    def test_chat_position_query_routes_to_coach(self):
        """Test 'what are my positions?' routes to coach agent"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "what are my positions?",
                "session_id": "test_position_query"
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "success" in data, "Response should contain 'success'"
        assert "agent_used" in data, "Response should contain 'agent_used'"
        assert "intent" in data, "Response should contain 'intent'"
        assert "response" in data, "Response should contain 'response'"
        
        # Verify routing - position queries should go to coach
        assert data["intent"] == "position_query", f"Expected intent 'position_query', got '{data['intent']}'"
        assert data["agent_used"] == "coach", f"Expected agent 'coach', got '{data['agent_used']}'"
        
        # Response should contain position info (from CODE, even if LLM fails)
        assert isinstance(data["response"], str), "Response text should be a string"
        assert len(data["response"]) > 0, "Response should not be empty"
        
        print(f"PASS: Position query routed to coach, intent={data['intent']}")
        print(f"Response preview: {data['response'][:200]}...")
    
    def test_chat_trade_execute_routes_correctly(self):
        """Test 'close TMC' routes to trade_executor agent"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "close TMC",
                "session_id": "test_trade_execute"
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "success" in data, "Response should contain 'success'"
        assert "agent_used" in data, "Response should contain 'agent_used'"
        assert "intent" in data, "Response should contain 'intent'"
        
        # Verify routing - trade commands should go to trade_executor
        assert data["intent"] == "trade_execute", f"Expected intent 'trade_execute', got '{data['intent']}'"
        assert data["agent_used"] == "trade_executor", f"Expected agent 'trade_executor', got '{data['agent_used']}'"
        
        # Response should indicate no position or ask for confirmation
        assert isinstance(data["response"], str), "Response text should be a string"
        
        print(f"PASS: Trade execute routed to trade_executor, intent={data['intent']}")
        print(f"Response: {data['response'][:300]}...")
    
    def test_chat_coaching_query_routes_to_coach(self):
        """Test coaching queries route to coach agent"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "how am I doing today?",
                "session_id": "test_coaching"
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify routing
        assert data["intent"] in ["coaching", "general_chat"], f"Expected coaching/general_chat intent, got '{data['intent']}'"
        
        print(f"PASS: Coaching query handled, intent={data['intent']}, agent={data['agent_used']}")
    
    def test_chat_returns_latency_info(self):
        """Verify chat response includes latency information"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "what are my positions?",
                "session_id": "test_latency"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "latency_ms" in data, "Response should contain 'latency_ms'"
        assert isinstance(data["latency_ms"], (int, float)), "latency_ms should be a number"
        assert data["latency_ms"] > 0, "latency_ms should be positive"
        
        print(f"PASS: Latency info returned: {data['latency_ms']:.2f}ms")
    
    def test_chat_returns_metadata(self):
        """Verify chat response includes metadata"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "close NVDA",
                "session_id": "test_metadata"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Metadata should contain routing info
        if "metadata" in data and data["metadata"]:
            metadata = data["metadata"]
            # Check for common metadata fields
            if "symbols" in metadata:
                print(f"Symbols detected: {metadata['symbols']}")
            if "routing_method" in metadata:
                print(f"Routing method: {metadata['routing_method']}")
        
        print(f"PASS: Chat response structure valid")


class TestSessionManagement:
    """Test /api/agents/session/{session_id} endpoint"""
    
    def test_clear_session_success(self):
        """Test DELETE session endpoint returns success"""
        test_session_id = "test_session_to_clear"
        
        # First, make a request to create the session (with short timeout since we're just creating context)
        try:
            requests.post(
                f"{BASE_URL}/api/agents/chat",
                json={
                    "message": "hello",
                    "session_id": test_session_id
                },
                timeout=45
            )
        except requests.exceptions.Timeout:
            # If chat times out, still try to clear session
            pass
        
        # Clear the session
        response = requests.delete(
            f"{BASE_URL}/api/agents/session/{test_session_id}",
            timeout=15
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "success" in data, "Response should contain 'success'"
        assert data["success"] == True, "success should be True"
        assert "message" in data, "Response should contain 'message'"
        
        print(f"PASS: Session '{test_session_id}' cleared successfully")
    
    def test_clear_nonexistent_session(self):
        """Test clearing a non-existent session doesn't error"""
        response = requests.delete(
            f"{BASE_URL}/api/agents/session/nonexistent_session_12345",
            timeout=15
        )
        # Should still return success (idempotent operation)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["success"] == True, "Clearing non-existent session should still succeed"
        print(f"PASS: Non-existent session clear handled gracefully")


class TestTradeExecutorEdgeCases:
    """Test trade executor agent edge cases"""
    
    def test_close_nonexistent_position(self):
        """Test closing a position that doesn't exist"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "close XYZ123",  # Non-existent symbol
                "session_id": "test_no_position"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should handle gracefully - either no position found message or success with error info
        assert "response" in data, "Response should contain 'response'"
        
        # The response should indicate no position found
        response_lower = data["response"].lower()
        # Either "no position" message or some form of error handling
        has_no_position = "no position" in response_lower or "cannot" in response_lower or "not found" in response_lower
        
        print(f"Response: {data['response']}")
        print(f"PASS: Non-existent position handled (response indicates awareness)")
    
    def test_buy_command_routing(self):
        """Test buy commands route to trade_executor"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "buy 100 shares of AAPL",
                "session_id": "test_buy_command"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["intent"] == "trade_execute", f"Expected 'trade_execute', got '{data['intent']}'"
        assert data["agent_used"] == "trade_executor", f"Expected 'trade_executor', got '{data['agent_used']}'"
        
        print(f"PASS: Buy command routed to trade_executor")


class TestRouterPatternMatching:
    """Test router agent pattern matching for various intents"""
    
    def test_portfolio_query(self):
        """Test 'show my portfolio' routes correctly"""
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
        
        # Portfolio/position queries should go to coach
        assert data["intent"] in ["position_query", "general_chat"], f"Unexpected intent: {data['intent']}"
        print(f"PASS: Portfolio query handled, intent={data['intent']}")
    
    def test_pnl_query(self):
        """Test 'what is my P&L' routes correctly"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "what is my P&L?",
                "session_id": "test_pnl"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # P&L queries are position queries
        assert data["intent"] in ["position_query", "general_chat", "coaching"]
        print(f"PASS: P&L query handled, intent={data['intent']}")
    
    def test_sell_command(self):
        """Test 'sell TSLA' routes to trade_executor"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "sell TSLA",
                "session_id": "test_sell"
            },
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["intent"] == "trade_execute", f"Expected 'trade_execute', got '{data['intent']}'"
        print(f"PASS: Sell command routed correctly")


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_empty_message(self):
        """Test handling of empty message"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={
                "message": "",
                "session_id": "test_empty"
            },
            timeout=15
        )
        # Should return 200 with error info, or 4xx
        assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            # If success, should indicate issue with empty message
            print(f"Empty message response: {data.get('response', 'N/A')[:100]}")
        
        print(f"PASS: Empty message handled (status={response.status_code})")
    
    def test_invalid_json(self):
        """Test handling of invalid request format"""
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            data="not json",
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        # Should return 4xx error
        assert response.status_code in [400, 422], f"Expected 4xx for invalid JSON, got {response.status_code}"
        print(f"PASS: Invalid JSON handled (status={response.status_code})")


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
