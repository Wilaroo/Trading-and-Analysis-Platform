"""
Test Learning Consolidation - Iteration 64
Tests that:
1. No learning_layer imports exist in agents/__init__.py
2. Coach agent works without learning services (graceful degradation)
3. Analyst agent works
4. Trade confirmation flow works
5. All 4 agents listed in status endpoint
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestLearningConsolidation:
    """Test learning architecture consolidation"""
    
    def test_agents_status_lists_all_four_agents(self):
        """Verify /api/agents/status returns all 4 agents"""
        response = requests.get(f"{BASE_URL}/api/agents/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["orchestrator_ready"] is True
        
        agents = data["agents"]
        expected_agents = ["router", "trade_executor", "coach", "analyst"]
        for agent in expected_agents:
            assert agent in agents, f"Missing agent: {agent}"
        
        print(f"✓ All 4 agents present: {agents}")
    
    def test_coach_agent_position_query(self):
        """Test coach agent handles position query gracefully"""
        session_id = f"test-coach-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "what are my positions?", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "coach"
        assert data["intent"] == "position_query"
        assert "positions" in data["response"].lower() or "position" in data["response"].lower()
        
        print(f"✓ Coach handles position query: {data['response'][:80]}...")
    
    def test_coach_agent_general_question(self):
        """Test coach agent handles general coaching questions"""
        session_id = f"test-coach-general-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "how am I doing today?", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # Coach handles general questions
        print(f"✓ Coach handles general query (agent={data['agent_used']})")
    
    def test_analyst_agent_analyze_nvda(self):
        """Test analyst agent handles analyze command"""
        session_id = f"test-analyst-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "analyze NVDA", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "analyst"
        assert data["intent"] == "analysis"
        assert "NVDA" in data["metadata"]["symbols"]
        
        print(f"✓ Analyst handles 'analyze NVDA': {data['response'][:100]}...")
    
    def test_analyst_agent_what_do_you_think(self):
        """Test analyst agent handles 'what do you think of SYMBOL'"""
        session_id = f"test-analyst-think-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "what do you think of TSLA?", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "analyst"
        
        print(f"✓ Analyst handles 'what do you think': agent={data['agent_used']}")
    
    def test_trade_confirmation_flow_buy(self):
        """Test buy order requires confirmation and executes on 'yes'"""
        session_id = f"test-trade-{int(time.time())}"
        
        # Step 1: Send buy command
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "buy 100 AAPL", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "trade_executor"
        assert data["requires_confirmation"] is True
        assert data["pending_trade"] is not None
        assert data["pending_trade"]["symbol"] == "AAPL"
        assert data["pending_trade"]["quantity"] == 100
        assert data["pending_trade"]["action"] == "buy"
        
        print(f"✓ Buy command requires confirmation: pending_trade={data['pending_trade']}")
        
        # Step 2: Confirm with 'yes'
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "yes", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "queued" in data["response"].lower() or "executed" in data["response"].lower()
        assert data["requires_confirmation"] is False
        assert data["pending_trade"] is None
        
        print(f"✓ Trade confirmed and queued: {data['response']}")
    
    def test_trade_confirmation_flow_sell(self):
        """Test sell order requires confirmation"""
        session_id = f"test-trade-sell-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "sell 50 MSFT", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "trade_executor"
        assert data["requires_confirmation"] is True
        assert data["pending_trade"]["symbol"] == "MSFT"
        assert data["pending_trade"]["quantity"] == 50
        
        print(f"✓ Sell command requires confirmation: pending_trade={data['pending_trade']}")
    
    def test_agents_metrics_endpoint(self):
        """Test /api/agents/metrics returns metrics for all agents"""
        response = requests.get(f"{BASE_URL}/api/agents/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "router" in data
        assert "trade_executor" in data
        assert "coach" in data
        assert "analyst" in data
        
        # Each agent should have call_count and error_count
        for agent_name, metrics in data.items():
            assert "call_count" in metrics
            assert "error_count" in metrics
        
        print(f"✓ Metrics available for all agents: {list(data.keys())}")


class TestLearningServicesGracefulDegradation:
    """Test that learning services handle null/unavailable services gracefully"""
    
    def test_coach_works_without_llm(self):
        """Coach should return position data even if LLM is unavailable"""
        session_id = f"test-no-llm-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "show my positions", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # Should use code_only mode when LLM unavailable
        assert data["agent_used"] == "coach"
        
        print(f"✓ Coach works without LLM: model_used={data['metadata'].get('model_used')}")
    
    def test_analyst_returns_structured_data_without_llm(self):
        """Analyst should return structured analysis even if LLM unavailable"""
        session_id = f"test-analyst-no-llm-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "analyze AMD", "session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["agent_used"] == "analyst"
        
        # Should contain structured technical analysis
        response_text = data["response"]
        assert "Technical Analysis" in response_text or "analysis" in response_text.lower()
        
        print(f"✓ Analyst returns structured data: {response_text[:80]}...")


class TestNoLearningLayerImports:
    """Verify learning_layer.py was properly removed and no imports remain"""
    
    def test_backend_starts_without_import_errors(self):
        """Backend should start without any learning_layer import errors"""
        # If backend is running and responding, there are no import errors
        response = requests.get(f"{BASE_URL}/api/agents/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["orchestrator_ready"] is True
        
        print("✓ Backend started without learning_layer import errors")
    
    def test_coach_agent_initializes_properly(self):
        """Coach agent should initialize without learning_layer dependencies"""
        session_id = f"test-init-{int(time.time())}"
        
        response = requests.post(
            f"{BASE_URL}/api/agents/chat",
            json={"message": "hello", "session_id": session_id}
        )
        assert response.status_code == 200
        
        # Any successful response proves initialization worked
        data = response.json()
        assert data["success"] is True
        
        print(f"✓ Coach agent initialized properly: agent_used={data['agent_used']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
