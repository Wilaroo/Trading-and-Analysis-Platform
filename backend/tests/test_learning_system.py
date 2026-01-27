"""
Test suite for AI Learning System
Tests knowledge base APIs, scoring integration, and knowledge enhancement features.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLearningStatus:
    """Test GET /api/learn/status endpoint"""
    
    def test_learning_status_returns_200(self):
        """Verify learning status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/learn/status")
        assert response.status_code == 200
        
    def test_learning_status_has_knowledge_base_stats(self):
        """Verify knowledge base stats are returned"""
        response = requests.get(f"{BASE_URL}/api/learn/status")
        data = response.json()
        
        assert "knowledge_base" in data
        kb = data["knowledge_base"]
        assert "total_entries" in kb
        assert kb["total_entries"] >= 96, f"Expected ~96 entries, got {kb['total_entries']}"
        
    def test_learning_status_has_llm_info(self):
        """Verify LLM provider info is returned"""
        response = requests.get(f"{BASE_URL}/api/learn/status")
        data = response.json()
        
        assert "llm" in data
        assert "ready" in data
        assert data["ready"] == True, "LLM should be available"
        
    def test_knowledge_base_has_type_breakdown(self):
        """Verify knowledge base has type breakdown"""
        response = requests.get(f"{BASE_URL}/api/learn/status")
        data = response.json()
        
        kb = data["knowledge_base"]
        assert "by_type" in kb
        by_type = kb["by_type"]
        
        # Should have strategies, rules, etc.
        assert "strategy" in by_type
        assert by_type["strategy"] > 0, "Should have strategies"


class TestLearnFromText:
    """Test POST /api/learn/text endpoint"""
    
    def test_learn_text_returns_200(self):
        """Verify learning from text works"""
        payload = {
            "content": "Test strategy for pytest: When price breaks above resistance with volume, enter long with stop below the breakout level.",
            "source_name": "pytest_test"
        }
        response = requests.post(f"{BASE_URL}/api/learn/text", json=payload)
        assert response.status_code == 200
        
    def test_learn_text_extracts_entries(self):
        """Verify text learning extracts knowledge entries"""
        payload = {
            "content": "Important trading rule: Never risk more than 2% of account on a single trade. This is a fundamental risk management principle.",
            "source_name": "pytest_risk_rule"
        }
        response = requests.post(f"{BASE_URL}/api/learn/text", json=payload)
        data = response.json()
        
        assert data["success"] == True
        assert "details" in data
        assert data["details"]["entries_saved"] >= 1
        
    def test_learn_text_validates_content(self):
        """Verify short content is rejected"""
        payload = {
            "content": "Too short",
            "source_name": "test"
        }
        response = requests.post(f"{BASE_URL}/api/learn/text", json=payload)
        # Should return 422 for validation error
        assert response.status_code == 422


class TestAnalyzeWithKnowledge:
    """Test POST /api/learn/analyze/{symbol} endpoint"""
    
    def test_analyze_returns_200(self):
        """Verify analyze endpoint returns 200"""
        response = requests.post(
            f"{BASE_URL}/api/learn/analyze/AAPL",
            json={"rvol": 2.5, "gap_percent": 3.5, "vwap_position": "ABOVE"}
        )
        assert response.status_code == 200
        
    def test_analyze_returns_applicable_strategies(self):
        """Verify analyze returns applicable strategies from KB"""
        response = requests.post(
            f"{BASE_URL}/api/learn/analyze/TSLA",
            json={"rvol": 3.0, "gap_percent": 5.0, "vwap_position": "ABOVE", "rsi_14": 65}
        )
        data = response.json()
        
        assert data["success"] == True
        assert "analysis" in data
        analysis = data["analysis"]
        
        assert "applicable_strategies" in analysis
        assert len(analysis["applicable_strategies"]) > 0, "Should find applicable strategies"
        
    def test_analyze_returns_trade_bias(self):
        """Verify analyze returns trade bias"""
        response = requests.post(
            f"{BASE_URL}/api/learn/analyze/NVDA",
            json={"rvol": 2.0, "gap_percent": -3.0, "vwap_position": "BELOW"}
        )
        data = response.json()
        
        analysis = data["analysis"]
        assert "trade_bias" in analysis
        assert analysis["trade_bias"] in ["LONG", "SHORT", "NEUTRAL"]
        
    def test_analyze_returns_confidence(self):
        """Verify analyze returns confidence score"""
        response = requests.post(
            f"{BASE_URL}/api/learn/analyze/AMD",
            json={"rvol": 1.5, "gap_percent": 2.0}
        )
        data = response.json()
        
        analysis = data["analysis"]
        assert "confidence" in analysis
        assert isinstance(analysis["confidence"], (int, float))


class TestEnhanceOpportunities:
    """Test POST /api/learn/enhance-opportunities endpoint"""
    
    def test_enhance_returns_200(self):
        """Verify enhance endpoint returns 200"""
        payload = {
            "opportunities": [
                {"symbol": "AAPL", "price": 180.50, "change_percent": 2.5, "rvol": 2.0}
            ],
            "market_regime": "bullish"
        }
        response = requests.post(f"{BASE_URL}/api/learn/enhance-opportunities", json=payload)
        assert response.status_code == 200
        
    def test_enhance_adds_learned_strategies(self):
        """Verify enhance adds learned strategies to opportunities"""
        payload = {
            "opportunities": [
                {"symbol": "TSLA", "price": 250.00, "change_percent": 5.0, "rvol": 3.0},
                {"symbol": "NVDA", "price": 480.00, "change_percent": -2.0, "rvol": 1.5}
            ],
            "market_regime": "bullish"
        }
        response = requests.post(f"{BASE_URL}/api/learn/enhance-opportunities", json=payload)
        data = response.json()
        
        assert data["success"] == True
        assert "enhanced_opportunities" in data
        
        for opp in data["enhanced_opportunities"]:
            assert "learned_strategies" in opp
            assert "kb_trade_bias" in opp
            assert "kb_confidence" in opp
            
    def test_enhance_returns_strategy_insights(self):
        """Verify enhance returns top strategy insights"""
        payload = {
            "opportunities": [
                {"symbol": "META", "price": 350.00, "change_percent": 3.0, "rvol": 2.5}
            ],
            "market_regime": "neutral"
        }
        response = requests.post(f"{BASE_URL}/api/learn/enhance-opportunities", json=payload)
        data = response.json()
        
        assert "strategy_insights" in data
        assert "knowledge_stats" in data


class TestScoringKBIntegration:
    """Test scoring engine knowledge base integration"""
    
    def test_scoring_includes_kb_object(self):
        """Verify scoring response includes knowledge_base object"""
        payload = {
            "stock": {
                "symbol": "AAPL",
                "current_price": 180.50,
                "rvol": 2.5,
                "gap_percent": 3.5,
                "vwap": 179.00,
                "market_cap": 3000000000000
            }
        }
        response = requests.post(f"{BASE_URL}/api/scoring/analyze", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "knowledge_base" in data
        
    def test_scoring_kb_has_applicable_strategies(self):
        """Verify scoring KB has applicable_strategies"""
        payload = {
            "stock": {
                "symbol": "TSLA",
                "current_price": 250.00,
                "rvol": 3.0,
                "gap_percent": 5.0,
                "vwap": 245.00,
                "market_cap": 800000000000
            }
        }
        response = requests.post(f"{BASE_URL}/api/scoring/analyze", json=payload)
        data = response.json()
        
        kb = data["knowledge_base"]
        assert "applicable_strategies" in kb
        assert isinstance(kb["applicable_strategies"], list)
        
    def test_scoring_kb_has_trade_bias(self):
        """Verify scoring KB has kb_trade_bias"""
        payload = {
            "stock": {
                "symbol": "NVDA",
                "current_price": 480.00,
                "rvol": 2.0,
                "gap_percent": 4.0,
                "vwap": 475.00,
                "market_cap": 1200000000000
            }
        }
        response = requests.post(f"{BASE_URL}/api/scoring/analyze", json=payload)
        data = response.json()
        
        kb = data["knowledge_base"]
        assert "kb_trade_bias" in kb
        assert "kb_confidence" in kb


class TestHealthAndBasics:
    """Basic health and connectivity tests"""
    
    def test_health_endpoint(self):
        """Verify health endpoint works"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        
    def test_frontend_loads(self):
        """Verify frontend is accessible"""
        response = requests.get(BASE_URL)
        assert response.status_code == 200


# Cleanup test data
@pytest.fixture(scope="session", autouse=True)
def cleanup_test_entries():
    """Note: Test entries are created but not cleaned up to preserve KB state"""
    yield
    # Could add cleanup logic here if needed
    pass
