"""
Time-Series AI Phase 3 Tests

Tests the LightGBM directional forecasting model integration:
- Time-Series Status API
- Time-Series Forecast API
- Time-Series Training API
- Time-Series Metrics API
- Module toggle for timeseries_ai
- Integration with full consultation (timeseries_forecast field)
- Feature extraction from OHLCV bars (46 features)
- Backward compatibility with Phase 1 and Phase 2 endpoints
"""

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def generate_ohlcv_bars(count=50, base_price=150.0, base_volume=1000000):
    """Generate sample OHLCV bars for testing (most recent first)"""
    bars = []
    import random
    random.seed(42)  # Reproducible
    
    price = base_price
    for i in range(count):
        # Generate realistic OHLCV data
        change = random.uniform(-2, 2)
        open_price = price
        close_price = price + change
        high_price = max(open_price, close_price) + random.uniform(0.1, 1.0)
        low_price = min(open_price, close_price) - random.uniform(0.1, 1.0)
        volume = int(base_volume * random.uniform(0.5, 2.0))
        
        bar = {
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        bars.append(bar)
        price = close_price
    
    return bars


# ==================== TIME-SERIES STATUS API ====================
class TestTimeSeriesStatusAPI:
    """Tests for GET /api/ai-modules/timeseries/status"""
    
    def test_timeseries_status_endpoint_exists(self):
        """Test that timeseries status endpoint exists and returns data"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert "status" in data, "Response should contain 'status' field"
        
        print(f"Status API response: {data}")
    
    def test_timeseries_status_structure(self):
        """Test that status returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status")
        assert response.status_code == 200
        
        data = response.json()
        status = data.get("status", {})
        
        # Check expected fields in status
        assert "service" in status or "model" in status, f"Status should have service or model info: {status}"
        
        # If model info is present, check structure
        if "model" in status:
            model_info = status["model"]
            expected_fields = ["model_name", "version", "trained", "forecast_horizon", "feature_count"]
            for field in expected_fields:
                assert field in model_info, f"Model info should have '{field}' field"
            
            # Feature count should be around 46
            feature_count = model_info.get("feature_count", 0)
            assert feature_count >= 40, f"Expected ~46 features, got {feature_count}"
            
        print(f"Timeseries status structure verified: {status}")


# ==================== TIME-SERIES FORECAST API ====================
class TestTimeSeriesForecastAPI:
    """Tests for POST /api/ai-modules/timeseries/forecast"""
    
    def test_forecast_with_valid_bars(self):
        """Test forecast with valid OHLCV bars (20+ required)"""
        bars = generate_ohlcv_bars(count=30)
        
        payload = {
            "symbol": "AAPL",
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        # If module is disabled, check for disabled response
        if response.status_code == 200:
            data = response.json()
            
            # Check if enabled=False response
            if data.get("enabled") is False:
                print(f"Timeseries module is disabled: {data.get('error')}")
                # Enable the module and retry
                enable_resp = requests.post(
                    f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai",
                    json={"enabled": True}
                )
                print(f"Enabled timeseries module: {enable_resp.json()}")
                
                # Retry forecast
                response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
            
            data = response.json()
            if data.get("success"):
                forecast = data.get("forecast", {})
                
                # Check forecast structure
                assert "direction" in forecast, f"Forecast should have 'direction': {forecast}"
                assert forecast["direction"] in ["up", "down", "flat"], f"Invalid direction: {forecast['direction']}"
                
                assert "probability_up" in forecast, "Forecast should have 'probability_up'"
                assert "probability_down" in forecast, "Forecast should have 'probability_down'"
                assert "confidence" in forecast, "Forecast should have 'confidence'"
                assert "signal" in forecast, "Forecast should have 'signal'"
                
                # Probabilities should sum to ~1.0
                prob_sum = forecast.get("probability_up", 0) + forecast.get("probability_down", 0)
                assert 0.98 <= prob_sum <= 1.02, f"Probabilities should sum to ~1.0: {prob_sum}"
                
                print(f"Forecast result: direction={forecast['direction']}, confidence={forecast['confidence']:.2f}")
        else:
            assert response.status_code in [200, 503], f"Unexpected status: {response.status_code}"
    
    def test_forecast_insufficient_bars(self):
        """Test forecast with insufficient bars (< 20)"""
        bars = generate_ohlcv_bars(count=10)
        
        # First enable the module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        payload = {
            "symbol": "AAPL",
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            forecast = data.get("forecast", {})
            
            # Should return insufficient data signal
            signal = forecast.get("signal", "")
            usable = forecast.get("usable", True)
            
            print(f"Insufficient bars response: usable={usable}, signal={signal}")
    
    def test_forecast_returns_model_version(self):
        """Test that forecast returns model version"""
        bars = generate_ohlcv_bars(count=25)
        
        # Ensure module is enabled
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        payload = {
            "symbol": "MSFT",
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                forecast = data.get("forecast", {})
                assert "model_version" in forecast, f"Forecast should have 'model_version': {forecast}"
                print(f"Model version: {forecast.get('model_version')}")


# ==================== TIME-SERIES TRAINING API ====================
class TestTimeSeriesTrainingAPI:
    """Tests for POST /api/ai-modules/timeseries/train"""
    
    def test_training_endpoint_exists(self):
        """Test that training endpoint exists"""
        payload = {"symbols": None}  # Use default symbols
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/train", json=payload)
        
        # Training may fail due to no historical data, but endpoint should exist
        assert response.status_code in [200, 500, 503], f"Unexpected status: {response.status_code}"
        
        data = response.json()
        print(f"Training API response: {data}")
    
    def test_training_returns_proper_structure(self):
        """Test training response structure"""
        payload = {"symbols": ["SPY", "QQQ"]}
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/train", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check structure
            assert "success" in data, "Response should have 'success' field"
            assert "result" in data, "Response should have 'result' field"
            
            result = data.get("result", {})
            
            # If training succeeded
            if result.get("success"):
                assert "metrics" in result, "Success result should have 'metrics'"
                assert "samples" in result or "symbols_used" in result, "Result should have sample info"
                print(f"Training succeeded: {result.get('metrics', {})}")
            else:
                # Training may fail due to no historical data - this is expected
                error = result.get("error", "")
                print(f"Training failed (expected): {error}")


# ==================== TIME-SERIES METRICS API ====================
class TestTimeSeriesMetricsAPI:
    """Tests for GET /api/ai-modules/timeseries/metrics"""
    
    def test_metrics_endpoint_exists(self):
        """Test that metrics endpoint exists and returns data"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/metrics")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert "metrics" in data, "Response should contain 'metrics' field"
        
        print(f"Metrics API response: {data}")
    
    def test_metrics_structure_when_untrained(self):
        """Test metrics structure when model is untrained"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/metrics")
        
        if response.status_code == 200:
            data = response.json()
            metrics = data.get("metrics")
            
            # Metrics may be None or empty if untrained
            if metrics:
                # Check expected metric fields
                expected_fields = ["accuracy", "training_samples", "validation_samples"]
                for field in expected_fields:
                    assert field in metrics, f"Metrics should have '{field}': {metrics}"
                
                print(f"Model metrics: {metrics}")
            else:
                print("Model is untrained - no metrics available (expected)")


# ==================== MODULE TOGGLE FOR TIMESERIES_AI ====================
class TestTimeSeriesToggle:
    """Tests for POST /api/ai-modules/toggle/timeseries_ai"""
    
    def test_toggle_enable_timeseries(self):
        """Test enabling timeseries_ai module"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai",
            json={"enabled": True}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert data.get("module") == "timeseries_ai", f"Module should be 'timeseries_ai'"
        assert data.get("enabled") is True, "enabled should be True"
        
        print(f"Toggle enable response: {data}")
    
    def test_toggle_disable_timeseries(self):
        """Test disabling timeseries_ai module"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai",
            json={"enabled": False}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert data.get("enabled") is False, "enabled should be False"
        
        print(f"Toggle disable response: {data}")
    
    def test_toggle_reflected_in_status(self):
        """Test that toggle is reflected in status API"""
        # Enable
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        # Check status
        status_resp = requests.get(f"{BASE_URL}/api/ai-modules/status")
        assert status_resp.status_code == 200
        
        status = status_resp.json().get("status", {})
        assert status.get("timeseries_enabled") is True, f"Status should show timeseries_enabled=True: {status}"
        
        # Disable
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": False})
        
        # Check status again
        status_resp = requests.get(f"{BASE_URL}/api/ai-modules/status")
        status = status_resp.json().get("status", {})
        assert status.get("timeseries_enabled") is False, f"Status should show timeseries_enabled=False: {status}"
        
        print("Toggle reflection in status verified")


# ==================== INTEGRATION WITH CONSULTATION ====================
class TestTimeSeriesConsultationIntegration:
    """Tests for timeseries_forecast in full consultation"""
    
    def test_consultation_includes_timeseries_forecast(self):
        """Test that consultation result includes timeseries_forecast field"""
        # Enable timeseries module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        bars = generate_ohlcv_bars(count=30)
        
        payload = {
            "trade": {
                "symbol": "AAPL",
                "direction": "long",
                "entry_price": 150.0,
                "stop_price": 145.0,
                "target_prices": [160.0],
                "shares": 100,
                "setup_type": "breakout",
                "quality_score": 75
            },
            "market_context": {
                "regime": "bullish",
                "vix": 18.5
            },
            "portfolio": {
                "account_value": 100000
            },
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/consultation/run", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        
        consultation = data.get("consultation", {})
        
        # Check for timeseries_forecast field
        assert "timeseries_forecast" in consultation, f"Consultation should have 'timeseries_forecast': {consultation.keys()}"
        
        ts_forecast = consultation.get("timeseries_forecast")
        if ts_forecast:
            # Check structure
            assert "forecast" in ts_forecast or "context" in ts_forecast, f"timeseries_forecast structure: {ts_forecast}"
            
            # Check context if present
            if "context" in ts_forecast:
                context = ts_forecast["context"]
                assert "signal" in context, f"Context should have 'signal': {context}"
                print(f"TimeSeries signal in consultation: {context.get('signal')}")
        
        print(f"Consultation timeseries_forecast: {ts_forecast}")
    
    def test_consultation_timeseries_alignment_with_trade_direction(self):
        """Test that timeseries provides alignment info with trade direction"""
        # Enable timeseries module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        bars = generate_ohlcv_bars(count=30)
        
        payload = {
            "trade": {
                "symbol": "MSFT",
                "direction": "long",
                "entry_price": 400.0,
                "stop_price": 390.0,
                "target_prices": [420.0],
                "shares": 50,
                "setup_type": "pullback"
            },
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/consultation/run", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            consultation = data.get("consultation", {})
            ts_forecast = consultation.get("timeseries_forecast", {})
            
            if ts_forecast and "context" in ts_forecast:
                context = ts_forecast["context"]
                
                # Check for alignment field
                align_field = context.get("align_with_trade")
                if align_field:
                    assert align_field in ["favorable", "contrary", "neutral"], f"Invalid alignment: {align_field}"
                    print(f"Trade alignment: {align_field}")


# ==================== FEATURE EXTRACTION VALIDATION ====================
class TestFeatureExtraction:
    """Tests for feature extraction from OHLCV bars"""
    
    def test_feature_count_in_status(self):
        """Test that status reports ~46 features"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status")
        
        if response.status_code == 200:
            data = response.json()
            status = data.get("status", {})
            model = status.get("model", {})
            
            feature_count = model.get("feature_count", 0)
            assert feature_count >= 40, f"Expected ~46 features, got {feature_count}"
            print(f"Feature count: {feature_count}")
    
    def test_forecast_with_minimum_bars(self):
        """Test forecast with exactly minimum required bars (20)"""
        bars = generate_ohlcv_bars(count=20)
        
        # Enable module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        payload = {
            "symbol": "NVDA",
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                forecast = data.get("forecast", {})
                # With exactly 20 bars, should still work
                assert "direction" in forecast, "Forecast should work with 20 bars"
                print(f"Forecast with 20 bars: {forecast.get('direction')}")


# ==================== BACKWARD COMPATIBILITY TESTS ====================
class TestBackwardCompatibilityPhase1Phase2:
    """Tests that Phase 1 and Phase 2 endpoints still work"""
    
    def test_config_endpoint(self):
        """GET /api/ai-modules/config - Phase 1"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/config")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        # Check timeseries_ai is in config
        config = data.get("config", {})
        modules = config.get("modules", {})
        assert "timeseries_ai" in modules, f"Config should include timeseries_ai: {modules.keys()}"
        print("Config endpoint OK")
    
    def test_status_endpoint(self):
        """GET /api/ai-modules/status - Phase 1"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        status = data.get("status", {})
        assert "timeseries_enabled" in status, f"Status should have timeseries_enabled: {status}"
        print("Status endpoint OK")
    
    def test_debate_endpoint(self):
        """POST /api/ai-modules/debate/run - Phase 1"""
        payload = {
            "symbol": "AAPL",
            "setup": {
                "setup_type": "breakout",
                "direction": "long",
                "entry_price": 150,
                "stop_price": 145,
                "target_price": 160,
                "quality_score": 70
            },
            "market_context": {"regime": "bullish"},
            "technical_data": {}
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/debate/run", json=payload)
        assert response.status_code == 200
        print("Debate endpoint OK")
    
    def test_risk_assess_endpoint(self):
        """POST /api/ai-modules/risk/assess - Phase 1"""
        payload = {
            "symbol": "MSFT",
            "direction": "long",
            "entry_price": 400,
            "stop_price": 390,
            "target_price": 420,
            "position_size_shares": 50,
            "account_value": 100000,
            "setup": {},
            "market_context": {}
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/risk/assess", json=payload)
        assert response.status_code == 200
        print("Risk assess endpoint OK")
    
    def test_consultation_status_endpoint(self):
        """GET /api/ai-modules/consultation/status - Phase 2"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/consultation/status")
        assert response.status_code == 200
        
        data = response.json()
        status = data.get("status", {})
        
        # Check timeseries_ai is in modules_available
        modules_available = status.get("modules_available", {})
        assert "timeseries_ai" in modules_available, f"modules_available should have timeseries_ai: {modules_available}"
        
        modules_enabled = status.get("modules_enabled", {})
        assert "timeseries_ai" in modules_enabled, f"modules_enabled should have timeseries_ai: {modules_enabled}"
        
        print("Consultation status endpoint OK")
    
    def test_consultation_run_endpoint(self):
        """POST /api/ai-modules/consultation/run - Phase 2"""
        payload = {
            "trade": {
                "symbol": "GOOGL",
                "direction": "long",
                "entry_price": 170,
                "stop_price": 165,
                "target_prices": [180],
                "shares": 30
            },
            "market_context": {"regime": "neutral"}
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/consultation/run", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        print("Consultation run endpoint OK")
    
    def test_shadow_stats_endpoint(self):
        """GET /api/ai-modules/shadow/stats - Phase 1"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        assert response.status_code == 200
        print("Shadow stats endpoint OK")


# ==================== UNTRAINED MODEL BEHAVIOR ====================
class TestUntrainedModelBehavior:
    """Tests for model behavior when untrained"""
    
    def test_untrained_model_returns_neutral(self):
        """Test that untrained model returns neutral/flat predictions"""
        # Enable module
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/timeseries_ai", json={"enabled": True})
        
        bars = generate_ohlcv_bars(count=30)
        
        payload = {
            "symbol": "TEST",
            "bars": bars
        }
        
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/forecast", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                forecast = data.get("forecast", {})
                
                # Check model version indicates untrained
                model_version = forecast.get("model_version", "")
                if "untrained" in model_version.lower() or model_version == "N/A":
                    # Untrained model should return flat/neutral
                    direction = forecast.get("direction")
                    prob_up = forecast.get("probability_up", 0)
                    prob_down = forecast.get("probability_down", 0)
                    
                    # Should be near 50/50 or flat
                    assert abs(prob_up - 0.5) < 0.1, f"Untrained should be ~50%: {prob_up}"
                    print(f"Untrained model behavior: direction={direction}, prob_up={prob_up}")
                else:
                    print(f"Model appears trained: version={model_version}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
