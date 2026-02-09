"""
Test Suite: Tab Navigation & AI Learning Context Integration (Iteration 17)

Tests for:
- Backend: /api/learning/strategy-stats returns correct data
- Backend: /api/assistant/chat with strategy performance questions
- Backend: Scheduler started on server startup (log verification done separately)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLearningStrategyStats:
    """Tests for GET /api/learning/strategy-stats endpoint"""
    
    def test_strategy_stats_returns_200(self):
        """Strategy stats endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/learning/strategy-stats returned 200")
    
    def test_strategy_stats_returns_success_true(self):
        """Strategy stats returns success=true"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        print(f"✓ Strategy stats returned success=True")
    
    def test_strategy_stats_contains_stats_object(self):
        """Strategy stats contains stats object with per-strategy data"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        data = response.json()
        assert "stats" in data, f"Missing 'stats' key in response"
        stats = data["stats"]
        print(f"✓ Strategy stats contains {len(stats)} strategies: {list(stats.keys())}")
        
        # Verify at least some expected strategies
        if stats:
            sample_strategy = list(stats.keys())[0]
            sample_data = stats[sample_strategy]
            
            # Verify expected fields
            expected_fields = ["total_trades", "wins", "losses", "win_rate", "total_pnl", "avg_pnl"]
            for field in expected_fields:
                assert field in sample_data, f"Missing '{field}' in strategy stats"
            
            print(f"✓ Strategy '{sample_strategy}' contains all expected fields: {expected_fields}")
            print(f"  Sample data: {sample_data}")


class TestAIChatWithPerformanceQueries:
    """Tests for /api/assistant/chat with strategy performance questions"""
    
    def test_chat_strategy_performance_question(self):
        """AI chat handles 'how are my strategies performing' question"""
        payload = {
            "message": "how are my strategies performing?",
            "session_id": "test_perf_session_17"
        }
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=30  # AI responses can take 10-15 seconds
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check response has content
        assert "response" in data or "message" in data, f"Missing response content: {data}"
        
        response_text = data.get("response", data.get("message", ""))
        print(f"✓ AI responded to strategy performance question (length: {len(response_text)} chars)")
        print(f"  Response preview: {response_text[:200]}...")
        
        # Verify response mentions strategies or performance
        response_lower = response_text.lower()
        has_strategy_content = any(word in response_lower for word in 
                                   ["strategy", "performance", "win", "trade", "p&l", "pnl"])
        assert has_strategy_content, f"Response doesn't mention strategies: {response_text[:500]}"
        print(f"✓ Response contains strategy/performance-related content")
    
    def test_chat_tuning_recommendations_question(self):
        """AI chat handles 'any tuning recommendations' question"""
        payload = {
            "message": "any tuning recommendations for my strategies?",
            "session_id": "test_tuning_session_17"
        }
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        response_text = data.get("response", data.get("message", ""))
        print(f"✓ AI responded to tuning recommendations question (length: {len(response_text)} chars)")
        print(f"  Response preview: {response_text[:200]}...")
        
        # Response should either mention recommendations or that there are none
        response_lower = response_text.lower()
        has_relevant_content = any(word in response_lower for word in 
                                   ["recommendation", "tuning", "suggest", "parameter", "pending", "no "])
        assert has_relevant_content, f"Response doesn't address recommendations: {response_text[:500]}"
        print(f"✓ Response contains tuning-related content")


class TestLearningRecommendations:
    """Tests for /api/learning/recommendations endpoint"""
    
    def test_recommendations_returns_200(self):
        """Recommendations endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/learning/recommendations")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/learning/recommendations returned 200")
    
    def test_recommendations_structure(self):
        """Recommendations returns correct structure"""
        response = requests.get(f"{BASE_URL}/api/learning/recommendations")
        data = response.json()
        assert data.get("success") == True, f"Expected success=True"
        assert "recommendations" in data, f"Missing 'recommendations' key"
        
        recs = data["recommendations"]
        print(f"✓ Found {len(recs)} pending recommendations")
        
        if recs:
            rec = recs[0]
            expected_fields = ["id", "strategy", "parameter", "current_value", "suggested_value"]
            for field in expected_fields:
                assert field in rec, f"Missing '{field}' in recommendation"
            print(f"  Sample: {rec['strategy']}.{rec['parameter']}: {rec['current_value']} -> {rec['suggested_value']}")


class TestTuningHistory:
    """Tests for /api/learning/tuning-history endpoint"""
    
    def test_tuning_history_returns_200(self):
        """Tuning history endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/learning/tuning-history returned 200")
    
    def test_tuning_history_structure(self):
        """Tuning history returns correct structure"""
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history?limit=10")
        data = response.json()
        assert data.get("success") == True, f"Expected success=True"
        assert "history" in data, f"Missing 'history' key"
        
        history = data["history"]
        print(f"✓ Found {len(history)} tuning history entries")
        
        if history:
            entry = history[0]
            expected_fields = ["strategy", "parameter", "old_value", "new_value"]
            for field in expected_fields:
                assert field in entry, f"Missing '{field}' in history entry"
            print(f"  Sample: {entry['strategy']}.{entry['parameter']}: {entry['old_value']} -> {entry['new_value']}")


class TestAnalyzeEndpoint:
    """Tests for /api/learning/analyze endpoint"""
    
    def test_analyze_endpoint_exists(self):
        """POST /api/learning/analyze endpoint exists and accepts requests"""
        # Just verify the endpoint exists - full analysis takes ~15s
        response = requests.post(
            f"{BASE_URL}/api/learning/analyze",
            json={},
            timeout=60  # Long timeout for AI analysis
        )
        # Accept 200 (success) or 422/400 (validation)
        assert response.status_code in [200, 422, 400], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/learning/analyze returned {response.status_code}")


class TestHealthAndBasics:
    """Basic health checks"""
    
    def test_health_endpoint(self):
        """Health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print(f"✓ GET /api/health returned 200")
    
    def test_trading_bot_status(self):
        """Trading bot status endpoint works"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        data = response.json()
        print(f"✓ Trading bot status: {data.get('mode', 'unknown')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
