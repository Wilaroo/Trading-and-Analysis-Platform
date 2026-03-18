"""
AI Module Tests

These tests verify the AI/ML modules are functioning correctly.
Run with: pytest tests/test_ai_modules.py -v
"""
import pytest
from fastapi.testclient import TestClient


class TestTimeSeriesAI:
    """Test Time-Series AI module"""
    
    def test_timeseries_status(self, test_client):
        """Test /api/ai-modules/timeseries/status returns model status"""
        response = test_client.get("/api/ai-modules/timeseries/status")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "status" in data
    
    def test_timeseries_predictions(self, test_client):
        """Test /api/ai-modules/timeseries/predictions returns recent predictions"""
        response = test_client.get("/api/ai-modules/timeseries/predictions?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "predictions" in data


class TestShadowTrading:
    """Test Shadow Trading module"""
    
    def test_shadow_decisions(self, test_client):
        """Test /api/ai-modules/shadow/decisions returns shadow trade decisions"""
        response = test_client.get("/api/ai-modules/shadow/decisions?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "decisions" in data
    
    def test_shadow_performance(self, test_client):
        """Test /api/ai-modules/shadow/performance returns performance metrics"""
        response = test_client.get("/api/ai-modules/shadow/performance?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


class TestAIModulesControl:
    """Test AI modules control endpoints"""
    
    def test_ai_modules_status(self, test_client):
        """Test /api/ai-modules/status returns all module statuses"""
        response = test_client.get("/api/ai-modules/status")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "status" in data
    
    def test_training_status(self, test_client):
        """Test /api/ai-modules/training-status returns training info"""
        response = test_client.get("/api/ai-modules/training-status")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


class TestMarketRegime:
    """Test Market Regime detection"""
    
    def test_market_regime_current(self, test_client):
        """Test /api/market-regime/current returns current regime"""
        response = test_client.get("/api/market-regime/current")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "regime" in data


class TestSentimentAnalysis:
    """Test Sentiment Analysis module"""
    
    def test_sector_performance(self, test_client):
        """Test /api/sector-analysis/performance returns sector data"""
        response = test_client.get("/api/sector-analysis/performance")
        assert response.status_code == 200
        data = response.json()
        # Should return sector performance data
        assert isinstance(data, (dict, list))
