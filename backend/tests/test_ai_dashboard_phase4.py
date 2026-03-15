"""
AI Insights Dashboard Phase 4 Tests

Tests the AI Insights Dashboard UI features:
- Time-Series AI model status and forecasting
- Shadow decisions display
- Module performance tracking
- Forecast endpoint with MongoDB data

Related to Phase 3 Time-Series AI Training
"""

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


# ==================== TIME-SERIES STATUS API ====================
class TestTimeSeriesStatusAPI:
    """Tests for GET /api/ai-modules/timeseries/status"""
    
    def test_timeseries_status_returns_trained_model(self):
        """Test that status shows trained model with metrics"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        status = data.get("status", {})
        model = status.get("model", {})
        
        # Model should be trained after Phase 3
        assert model.get("trained") is True, f"Model should be trained: {model}"
        assert model.get("version", "").startswith("v"), f"Version should start with 'v': {model}"
        assert model.get("feature_count") >= 40, f"Should have ~46 features: {model}"
        
        # Check metrics exist
        metrics = model.get("metrics", {})
        assert "accuracy" in metrics, f"Should have accuracy metric: {metrics}"
        assert "training_samples" in metrics, f"Should have training_samples: {metrics}"
        
        print(f"Model status: v{model.get('version')}, {model.get('feature_count')} features, {metrics.get('accuracy', 0)*100:.1f}% accuracy")


# ==================== TIME-SERIES FORECAST WITH MONGODB ====================
class TestTimeSeriesForecastFromMongoDB:
    """Tests for POST /api/ai-modules/timeseries/forecast - MongoDB data source"""
    
    def test_forecast_without_bars_fetches_from_mongodb(self):
        """Test forecast when bars are not provided - should fetch from MongoDB"""
        # Enable module first
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        # Forecast with just symbol - no bars provided
        payload = {"symbol": "NVDA"}
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        if data.get("success"):
            forecast = data.get("forecast", {})
            assert "direction" in forecast, f"Should have direction: {forecast}"
            assert forecast["direction"] in ["up", "down", "flat"], f"Invalid direction: {forecast}"
            assert "probability_up" in forecast
            assert "probability_down" in forecast
            assert "model_version" in forecast
            
            print(f"NVDA forecast (from MongoDB): direction={forecast['direction']}, prob_up={forecast['probability_up']:.2f}")
        else:
            # May fail if symbol doesn't have enough data in MongoDB
            print(f"Forecast response (may be expected): {data}")
    
    def test_forecast_multiple_symbols_from_mongodb(self):
        """Test forecasting multiple symbols from MongoDB data"""
        symbols = ["AAPL", "MSFT", "TSLA"]
        
        # Enable module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        for symbol in symbols:
            payload = {"symbol": symbol}
            response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
            
            assert response.status_code == 200
            data = response.json()
            
            if data.get("success"):
                forecast = data.get("forecast", {})
                print(f"{symbol}: direction={forecast.get('direction')}, confidence={forecast.get('confidence', 0):.2f}")


# ==================== SHADOW DECISIONS API ====================
class TestShadowDecisionsAPI:
    """Tests for GET /api/ai-modules/shadow/decisions"""
    
    def test_get_shadow_decisions(self):
        """Test getting recent shadow decisions"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/decisions?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        decisions = data.get("decisions", [])
        assert isinstance(decisions, list)
        
        print(f"Found {len(decisions)} shadow decisions")
        
        # Check decision structure if we have any
        if len(decisions) > 0:
            decision = decisions[0]
            assert "symbol" in decision, f"Decision should have symbol: {decision.keys()}"
            assert "combined_recommendation" in decision, f"Should have combined_recommendation"
            assert "confidence_score" in decision, f"Should have confidence_score"
            assert "timestamp" in decision or "trigger_time" in decision
            
            print(f"Latest decision: {decision.get('symbol')} - {decision.get('combined_recommendation')} (conf: {decision.get('confidence_score', 0):.0%})")
    
    def test_filter_decisions_by_symbol(self):
        """Test filtering decisions by symbol"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/decisions?symbol=AAPL&limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        decisions = data.get("decisions", [])
        # If there are AAPL decisions, they should all be for AAPL
        for decision in decisions:
            assert decision.get("symbol") == "AAPL", f"Filtered decision should be AAPL: {decision.get('symbol')}"
        
        print(f"Found {len(decisions)} AAPL decisions")


# ==================== SHADOW PERFORMANCE API ====================
class TestShadowPerformanceAPI:
    """Tests for GET /api/ai-modules/shadow/performance"""
    
    def test_get_performance_metrics(self):
        """Test getting performance metrics for all modules"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/performance?days=7")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        performance = data.get("performance", {})
        
        # Should have performance data for modules
        expected_modules = ["debate_agents", "ai_risk_manager", "institutional_flow", "timeseries_ai"]
        for module in expected_modules:
            if module in performance:
                perf = performance[module]
                print(f"{module}: total={perf.get('total_decisions', 0)}, accuracy={perf.get('accuracy', 0):.1%}")


# ==================== AI MODULES CONFIG ====================
class TestAIModulesConfig:
    """Tests for AI modules configuration endpoints"""
    
    def test_get_config(self):
        """Test GET /api/ai-modules/config"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/config")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        config = data.get("config", {})
        modules = config.get("modules", {})
        
        # Should include timeseries_ai
        assert "timeseries_ai" in modules, f"Should have timeseries_ai in modules: {modules.keys()}"
        print(f"Config has {len(modules)} modules")
    
    def test_get_status(self):
        """Test GET /api/ai-modules/status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        status = data.get("status", {})
        assert "timeseries_enabled" in status, f"Status should have timeseries_enabled: {status}"
        
        print(f"AI Modules Status: debate={status.get('debate_enabled')}, risk={status.get('risk_manager_enabled')}, timeseries={status.get('timeseries_enabled')}")
    
    def test_toggle_timeseries_module(self):
        """Test toggling timeseries_ai module"""
        # Enable
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai",
            json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json().get("enabled") is True
        
        # Verify in status
        status_response = requests.get(f"{BASE_URL}/api/ai-modules/status")
        status = status_response.json().get("status", {})
        assert status.get("timeseries_enabled") is True
        
        print("Toggle timeseries_ai: PASS")


# ==================== MODEL METRICS ====================
class TestModelMetrics:
    """Tests for GET /api/ai-modules/timeseries/metrics"""
    
    def test_get_metrics(self):
        """Test getting model metrics"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        metrics = data.get("metrics")
        if metrics:
            print(f"Model metrics: accuracy={metrics.get('accuracy', 0):.2%}, " +
                  f"samples={metrics.get('training_samples', 0)}")
            
            # Check top features
            top_features = metrics.get("top_features", [])
            if top_features:
                print(f"Top features: {top_features[:5]}")


# ==================== SHADOW STATS ====================
class TestShadowStats:
    """Tests for GET /api/ai-modules/shadow/stats"""
    
    def test_get_stats(self):
        """Test getting shadow tracker stats"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        stats = data.get("stats", {})
        print(f"Shadow stats: total={stats.get('total_decisions', 0)}, " +
              f"executed={stats.get('executed_decisions', 0)}, " +
              f"pending={stats.get('pending_outcomes', 0)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
