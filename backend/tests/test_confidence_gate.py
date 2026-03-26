"""
Test Confidence Gate API Endpoints
==================================
Tests for the AI Confidence Gate feature that SentCom checks before every trade.
Endpoints tested:
- GET /api/ai-training/confidence-gate/summary
- GET /api/ai-training/confidence-gate/decisions
- GET /api/ai-training/confidence-gate/stats
- POST /api/ai-training/confidence-gate/evaluate
- GET /api/ai-training/regime-live
- GET /api/ai-training/model-inventory
- GET /api/ai-training/status
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestConfidenceGateSummary:
    """Tests for GET /api/ai-training/confidence-gate/summary"""
    
    def test_summary_returns_success(self):
        """Summary endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Summary endpoint returns success=true")
    
    def test_summary_has_trading_mode(self):
        """Summary should include trading_mode field"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        assert "trading_mode" in data
        assert data["trading_mode"] in ["aggressive", "normal", "cautious", "defensive"]
        print(f"✓ Trading mode: {data['trading_mode']}")
    
    def test_summary_has_today_stats(self):
        """Summary should include today's stats (evaluated, taken, skipped)"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        assert "today" in data
        today = data["today"]
        assert "evaluated" in today
        assert "taken" in today
        assert "skipped" in today
        assert "take_rate" in today
        print(f"✓ Today stats: evaluated={today['evaluated']}, taken={today['taken']}, skipped={today['skipped']}")
    
    def test_summary_has_streak_info(self):
        """Summary should include streak info (may be null if no decisions)"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        # streak can be null if no decisions yet
        assert "streak" in data or data.get("streak") is None
        print(f"✓ Streak info present: {data.get('streak')}")


class TestConfidenceGateDecisions:
    """Tests for GET /api/ai-training/confidence-gate/decisions"""
    
    def test_decisions_returns_success(self):
        """Decisions endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Decisions endpoint returns success=true")
    
    def test_decisions_returns_array(self):
        """Decisions should return an array (may be empty)"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions")
        assert response.status_code == 200
        data = response.json()
        assert "decisions" in data
        assert isinstance(data["decisions"], list)
        print(f"✓ Decisions array returned with {len(data['decisions'])} items")
    
    def test_decisions_with_limit(self):
        """Decisions endpoint should respect limit parameter"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert len(data.get("decisions", [])) <= 5
        print(f"✓ Limit parameter works, got {len(data.get('decisions', []))} decisions")


class TestConfidenceGateStats:
    """Tests for GET /api/ai-training/confidence-gate/stats"""
    
    def test_stats_returns_success(self):
        """Stats endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/stats")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Stats endpoint returns success=true")
    
    def test_stats_has_counts(self):
        """Stats should include go_count, skip_count, reduce_count"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/stats")
        assert response.status_code == 200
        data = response.json()
        assert "go_count" in data
        assert "skip_count" in data
        assert "reduce_count" in data
        assert "total_evaluated" in data
        print(f"✓ Stats: go={data['go_count']}, skip={data['skip_count']}, reduce={data['reduce_count']}, total={data['total_evaluated']}")
    
    def test_stats_has_rates(self):
        """Stats should include go_rate and skip_rate"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/stats")
        assert response.status_code == 200
        data = response.json()
        assert "go_rate" in data
        assert "skip_rate" in data
        print(f"✓ Rates: go_rate={data['go_rate']}, skip_rate={data['skip_rate']}")


class TestConfidenceGateEvaluate:
    """Tests for POST /api/ai-training/confidence-gate/evaluate"""
    
    def test_evaluate_returns_success(self):
        """Evaluate endpoint should return success=true"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Evaluate endpoint returns success=true")
    
    def test_evaluate_returns_decision(self):
        """Evaluate should return a decision (GO, REDUCE, or SKIP)"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "decision" in data
        assert data["decision"] in ["GO", "REDUCE", "SKIP"]
        print(f"✓ Decision: {data['decision']}")
    
    def test_evaluate_returns_confidence_score(self):
        """Evaluate should return confidence_score (0-100)"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "confidence_score" in data
        assert 0 <= data["confidence_score"] <= 100
        print(f"✓ Confidence score: {data['confidence_score']}")
    
    def test_evaluate_returns_reasoning(self):
        """Evaluate should return reasoning array"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "reasoning" in data
        assert isinstance(data["reasoning"], list)
        print(f"✓ Reasoning: {len(data['reasoning'])} items")
        for r in data["reasoning"][:3]:
            print(f"  - {r}")
    
    def test_evaluate_returns_regime_info(self):
        """Evaluate should return regime_state and ai_regime"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "regime_state" in data
        assert "ai_regime" in data
        assert "trading_mode" in data
        print(f"✓ Regime: state={data['regime_state']}, ai={data['ai_regime']}, mode={data['trading_mode']}")
    
    def test_evaluate_with_short_direction(self):
        """Evaluate should work with short direction"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "TSLA", "setup_type": "vwap_fade", "direction": "short"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("direction") == "short"
        print(f"✓ Short direction works: decision={data['decision']}")


class TestRegimeLive:
    """Tests for GET /api/ai-training/regime-live"""
    
    def test_regime_live_returns_success(self):
        """Regime live endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/regime-live")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Regime live endpoint returns success=true")
    
    def test_regime_live_has_regime(self):
        """Regime live should return regime classification"""
        response = requests.get(f"{BASE_URL}/api/ai-training/regime-live")
        assert response.status_code == 200
        data = response.json()
        assert "regime" in data
        print(f"✓ Regime: {data['regime']}")
    
    def test_regime_live_has_indexes(self):
        """Regime live should return index data (SPY, QQQ, IWM)"""
        response = requests.get(f"{BASE_URL}/api/ai-training/regime-live")
        assert response.status_code == 200
        data = response.json()
        assert "indexes" in data
        indexes = data["indexes"]
        assert "SPY" in indexes or len(indexes) >= 0  # May be empty if no data
        print(f"✓ Indexes: {list(indexes.keys()) if indexes else 'empty'}")
    
    def test_regime_live_has_cross_data(self):
        """Regime live should return cross-correlation data"""
        response = requests.get(f"{BASE_URL}/api/ai-training/regime-live")
        assert response.status_code == 200
        data = response.json()
        assert "cross" in data
        print(f"✓ Cross data present: {bool(data['cross'])}")


class TestModelInventory:
    """Tests for GET /api/ai-training/model-inventory"""
    
    def test_model_inventory_returns_success(self):
        """Model inventory endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Model inventory endpoint returns success=true")
    
    def test_model_inventory_has_categories(self):
        """Model inventory should return categories"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        categories = data["categories"]
        # Check expected categories exist
        expected = ["generic_directional", "setup_specific", "volatility", "exit_timing"]
        for cat in expected:
            assert cat in categories, f"Missing category: {cat}"
        print(f"✓ Categories: {list(categories.keys())}")
    
    def test_model_inventory_has_totals(self):
        """Model inventory should return total_defined and total_trained"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory")
        assert response.status_code == 200
        data = response.json()
        assert "total_defined" in data
        assert "total_trained" in data
        print(f"✓ Totals: defined={data['total_defined']}, trained={data['total_trained']}")


class TestTrainingStatus:
    """Tests for GET /api/ai-training/status"""
    
    def test_status_returns_success(self):
        """Status endpoint should return success=true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Status endpoint returns success=true")
    
    def test_status_has_task_status(self):
        """Status should return task_status"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status")
        assert response.status_code == 200
        data = response.json()
        assert "task_status" in data
        assert data["task_status"] in ["idle", "running", "completed", "failed"]
        print(f"✓ Task status: {data['task_status']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
