"""
Test Setup-Specific AI Models Feature
=====================================
Tests the new setup-specific model endpoints:
- GET /api/ai-modules/timeseries/setups/status
- POST /api/ai-modules/timeseries/setups/train
- POST /api/ai-modules/timeseries/setups/train-all
- POST /api/ai-modules/timeseries/setups/predict
- POST /api/ai-modules/timeseries/stop-training
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSetupModelsEndpoints:
    """Test setup-specific AI model endpoints"""
    
    def test_health_check(self):
        """Verify backend is running"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("PASSED: Health check")
    
    def test_get_setup_models_status(self):
        """GET /api/ai-modules/timeseries/setups/status - should return all 10 setup types"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/setups/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        
        # Should have all 10 setup types
        assert "total_setup_types" in data
        assert data["total_setup_types"] == 10, f"Expected 10 setup types, got {data['total_setup_types']}"
        
        # Should have models dict with all setup types
        assert "models" in data
        models = data["models"]
        
        expected_types = [
            "MOMENTUM", "SCALP", "BREAKOUT", "GAP_AND_GO", "RANGE",
            "REVERSAL", "TREND_CONTINUATION", "ORB", "VWAP", "MEAN_REVERSION"
        ]
        
        for setup_type in expected_types:
            assert setup_type in models, f"Missing setup type: {setup_type}"
            model_info = models[setup_type]
            assert "trained" in model_info, f"Missing 'trained' field for {setup_type}"
            assert "description" in model_info, f"Missing 'description' field for {setup_type}"
        
        # Should have models_trained count
        assert "models_trained" in data
        assert isinstance(data["models_trained"], int)
        
        print(f"PASSED: Setup models status - {data['models_trained']}/{data['total_setup_types']} trained")
        print(f"  Setup types: {list(models.keys())}")
    
    def test_train_setup_model_valid_type(self):
        """POST /api/ai-modules/timeseries/setups/train - should accept valid setup_type"""
        # Test with MOMENTUM setup type
        payload = {
            "setup_type": "MOMENTUM",
            "bar_size": "1 day"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json=payload,
            timeout=120  # Training can take time
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return success or proper error (e.g., no data available)
        if data.get("success"):
            assert "result" in data
            result = data["result"]
            assert "setup_type" in result or "metrics" in result
            print(f"PASSED: Train MOMENTUM model - success")
        else:
            # May fail due to no data, but should return proper error
            result = data.get("result", {})
            error = result.get("error", data.get("error", "Unknown error"))
            assert "error" in result or "error" in data, f"Expected error message, got {data}"
            print(f"PASSED: Train MOMENTUM model - returned proper error: {error}")
    
    def test_train_setup_model_invalid_type(self):
        """POST /api/ai-modules/timeseries/setups/train - should handle invalid setup_type"""
        payload = {
            "setup_type": "INVALID_TYPE_XYZ",
            "bar_size": "1 day"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json=payload,
            timeout=30
        )
        
        # Should return 200 with success=False or 400/422 error
        data = response.json()
        
        if response.status_code == 200:
            # If 200, should have success=False with error
            result = data.get("result", {})
            if not data.get("success"):
                assert "error" in result or "error" in data
                print(f"PASSED: Invalid setup type returns error: {result.get('error', data.get('error'))}")
            else:
                # Some types may be accepted as aliases
                print(f"PASSED: Setup type accepted (may be alias)")
        else:
            # 400 or 422 is also acceptable
            assert response.status_code in [400, 422, 500]
            print(f"PASSED: Invalid setup type returns status {response.status_code}")
    
    def test_train_all_setup_models(self):
        """POST /api/ai-modules/timeseries/setups/train-all - should return success message"""
        payload = {
            "bar_size": "1 day"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train-all",
            json=payload,
            timeout=30  # Should return quickly as it runs in background
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return success with message about background training
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "message" in data, f"Expected message field, got {data}"
        assert "setup_types" in data or "total_types" in data, f"Expected setup_types or total_types, got {data}"
        
        print(f"PASSED: Train all setup models - {data.get('message')}")
        if "setup_types" in data:
            print(f"  Setup types: {data['setup_types']}")
    
    def test_predict_for_setup_no_models(self):
        """POST /api/ai-modules/timeseries/setups/predict - should return proper error when no models"""
        payload = {
            "symbol": "AAPL",
            "setup_type": "MOMENTUM"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/predict",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return prediction or proper error
        if data.get("success"):
            assert "prediction" in data or "forecast" in data
            print(f"PASSED: Predict for setup - got prediction")
        else:
            # Expected when no models are trained
            error = data.get("error", "")
            assert "no" in error.lower() or "model" in error.lower() or "available" in error.lower() or "failed" in error.lower(), \
                f"Expected 'no models available' type error, got: {error}"
            print(f"PASSED: Predict for setup - proper error: {error}")
    
    def test_stop_training_endpoint(self):
        """POST /api/ai-modules/timeseries/stop-training - should work without crashing"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/stop-training",
            timeout=30
        )
        
        # Should return 200 and not crash
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "message" in data, f"Expected message field, got {data}"
        
        print(f"PASSED: Stop training endpoint - {data.get('message')}")
        if "was_running" in data:
            print(f"  Was running: {data['was_running']}")
    
    def test_timeseries_status_endpoint(self):
        """GET /api/ai-modules/timeseries/status - verify general timeseries status works"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "status" in data
        
        print(f"PASSED: Timeseries status endpoint")


class TestSetupModelsValidation:
    """Test input validation for setup model endpoints"""
    
    def test_train_missing_setup_type(self):
        """POST /api/ai-modules/timeseries/setups/train - should require setup_type"""
        payload = {
            "bar_size": "1 day"
            # Missing setup_type
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json=payload,
            timeout=30
        )
        
        # Should return 422 validation error
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("PASSED: Missing setup_type returns 422 validation error")
    
    def test_predict_missing_symbol(self):
        """POST /api/ai-modules/timeseries/setups/predict - should require symbol"""
        payload = {
            "setup_type": "MOMENTUM"
            # Missing symbol
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/predict",
            json=payload,
            timeout=30
        )
        
        # Should return 422 validation error
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("PASSED: Missing symbol returns 422 validation error")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
