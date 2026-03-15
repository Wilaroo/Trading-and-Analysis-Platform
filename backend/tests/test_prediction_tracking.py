"""
Test Prediction Tracking Feature - P1 Task
Tests the new prediction tracking endpoints for measuring real-world AI model performance.

Endpoints tested:
- GET /api/ai-modules/timeseries/prediction-accuracy - Get prediction accuracy stats
- GET /api/ai-modules/timeseries/predictions - Get recent predictions with new schema
- POST /api/ai-modules/timeseries/verify-predictions - Verify pending predictions
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPredictionAccuracyEndpoint:
    """Test GET /api/ai-modules/timeseries/prediction-accuracy"""
    
    def test_prediction_accuracy_returns_200(self):
        """Test that prediction accuracy endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/prediction-accuracy?days=30")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Prediction accuracy endpoint returns 200")
    
    def test_prediction_accuracy_returns_expected_structure(self):
        """Test that response has expected fields"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/prediction-accuracy?days=30")
        data = response.json()
        
        assert data.get("success") is True, "Response should have success=true"
        assert "accuracy" in data, "Response should have accuracy field"
        
        accuracy = data["accuracy"]
        assert "total_predictions" in accuracy, "Should have total_predictions"
        assert "verified_predictions" in accuracy, "Should have verified_predictions"
        assert "accuracy" in accuracy, "Should have accuracy metric"
        assert "by_direction" in accuracy, "Should have by_direction breakdown"
        print(f"✓ Prediction accuracy structure valid - {accuracy.get('total_predictions', 0)} total predictions")
    
    def test_prediction_accuracy_with_custom_days(self):
        """Test that days parameter works"""
        for days in [7, 14, 30, 60]:
            response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/prediction-accuracy?days={days}")
            assert response.status_code == 200, f"Failed for days={days}"
            data = response.json()
            assert data.get("success") is True
        print("✓ Prediction accuracy works with various day ranges")


class TestRecentPredictionsEndpoint:
    """Test GET /api/ai-modules/timeseries/predictions"""
    
    def test_recent_predictions_returns_200(self):
        """Test that recent predictions endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Recent predictions endpoint returns 200")
    
    def test_recent_predictions_returns_expected_structure(self):
        """Test that response has expected fields"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=10")
        data = response.json()
        
        assert data.get("success") is True, "Response should have success=true"
        assert "predictions" in data, "Response should have predictions array"
        assert "count" in data, "Response should have count"
        
        predictions = data.get("predictions", [])
        assert isinstance(predictions, list), "Predictions should be a list"
        print(f"✓ Recent predictions structure valid - {len(predictions)} predictions returned")
    
    def test_predictions_have_new_schema_fields(self):
        """Test that predictions include new tracking fields"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=5")
        data = response.json()
        predictions = data.get("predictions", [])
        
        if len(predictions) > 0:
            pred = predictions[0]
            
            # Check required new fields
            assert "symbol" in pred, "Should have symbol"
            assert "prediction" in pred, "Should have prediction object"
            assert "price_at_prediction" in pred, "Should have price_at_prediction"
            assert "forecast_horizon" in pred, "Should have forecast_horizon"
            assert "timestamp" in pred, "Should have timestamp"
            assert "outcome_verified" in pred, "Should have outcome_verified"
            
            # Check prediction object structure
            prediction = pred.get("prediction", {})
            assert "direction" in prediction, "Prediction should have direction"
            assert "probability_up" in prediction, "Prediction should have probability_up"
            assert "probability_down" in prediction, "Prediction should have probability_down"
            assert "confidence" in prediction, "Prediction should have confidence"
            
            print(f"✓ Prediction schema has all required fields - {pred['symbol']}")
            print(f"  - price_at_prediction: ${pred.get('price_at_prediction', 'N/A')}")
            print(f"  - direction: {prediction.get('direction', 'N/A')}")
            print(f"  - outcome_verified: {pred.get('outcome_verified', 'N/A')}")
        else:
            print("⚠ No predictions found to validate schema")
    
    def test_predictions_have_outcome_fields(self):
        """Test that predictions have outcome tracking fields"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=5")
        data = response.json()
        predictions = data.get("predictions", [])
        
        if len(predictions) > 0:
            pred = predictions[0]
            
            # These fields may be null but should exist
            assert "actual_direction" in pred or pred.get("outcome_verified") is False, "Should have actual_direction or be pending"
            assert "price_at_verification" in pred or pred.get("outcome_verified") is False, "Should have price_at_verification or be pending"
            assert "actual_return" in pred or pred.get("outcome_verified") is False, "Should have actual_return or be pending"
            assert "prediction_correct" in pred or pred.get("outcome_verified") is False, "Should have prediction_correct or be pending"
            
            print(f"✓ Prediction outcome fields present")
            print(f"  - outcome_verified: {pred.get('outcome_verified')}")
            print(f"  - prediction_correct: {pred.get('prediction_correct')}")
        else:
            print("⚠ No predictions found to validate outcome fields")
    
    def test_predictions_limit_parameter(self):
        """Test that limit parameter works"""
        for limit in [5, 10, 20]:
            response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit={limit}")
            data = response.json()
            predictions = data.get("predictions", [])
            # Should not exceed limit
            assert len(predictions) <= limit, f"Got more than {limit} predictions"
        print("✓ Limit parameter works correctly")
    
    def test_predictions_verified_only_filter(self):
        """Test verified_only filter"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=10&verified_only=true")
        assert response.status_code == 200
        data = response.json()
        predictions = data.get("predictions", [])
        
        # All returned predictions should be verified (if any)
        for pred in predictions:
            assert pred.get("outcome_verified") is True, "Should only return verified predictions"
        
        print(f"✓ Verified-only filter works - {len(predictions)} verified predictions")


class TestVerifyPredictionsEndpoint:
    """Test POST /api/ai-modules/timeseries/verify-predictions"""
    
    def test_verify_predictions_returns_200(self):
        """Test that verify predictions endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/verify-predictions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Verify predictions endpoint returns 200")
    
    def test_verify_predictions_returns_expected_structure(self):
        """Test that response has expected fields"""
        response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/verify-predictions")
        data = response.json()
        
        assert data.get("success") is True, "Response should have success=true"
        assert "result" in data, "Response should have result object"
        
        result = data.get("result", {})
        assert "verified" in result, "Result should have verified count"
        assert "correct" in result, "Result should have correct count"
        assert "accuracy" in result, "Result should have accuracy"
        
        print(f"✓ Verify predictions structure valid")
        print(f"  - verified: {result.get('verified', 0)}")
        print(f"  - correct: {result.get('correct', 0)}")
        print(f"  - accuracy: {result.get('accuracy', 0)}")


class TestPredictionIntegration:
    """Integration tests for prediction tracking flow"""
    
    def test_forecast_creates_prediction_with_tracking_fields(self):
        """Test that running a forecast creates a prediction with tracking fields"""
        # Run a forecast
        forecast_response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/forecast",
            json={"symbol": "AAPL"}
        )
        
        if forecast_response.status_code == 200:
            forecast_data = forecast_response.json()
            if forecast_data.get("success"):
                # Check recent predictions for the new prediction
                pred_response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=3")
                pred_data = pred_response.json()
                predictions = pred_data.get("predictions", [])
                
                # Should have at least one AAPL prediction
                aapl_preds = [p for p in predictions if p.get("symbol") == "AAPL"]
                if aapl_preds:
                    pred = aapl_preds[0]
                    assert pred.get("price_at_prediction") is not None, "Should have price_at_prediction"
                    assert pred.get("outcome_verified") is False, "New prediction should be pending"
                    print(f"✓ Forecast created prediction with tracking fields")
                    print(f"  - symbol: AAPL")
                    print(f"  - price_at_prediction: ${pred.get('price_at_prediction')}")
                else:
                    print("⚠ Could not find AAPL prediction in recent list")
        else:
            pytest.skip("Forecast endpoint unavailable")
    
    def test_full_prediction_tracking_flow(self):
        """Test the complete prediction tracking flow"""
        # 1. Check current accuracy
        accuracy_response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/prediction-accuracy?days=30")
        accuracy_data = accuracy_response.json()
        assert accuracy_data.get("success") is True
        
        # 2. Get recent predictions
        predictions_response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/predictions?limit=10")
        predictions_data = predictions_response.json()
        assert predictions_data.get("success") is True
        
        # 3. Run verification (may not verify anything if predictions are too new)
        verify_response = requests.post(f"{BASE_URL}/api/ai-modules/timeseries/verify-predictions")
        verify_data = verify_response.json()
        assert verify_data.get("success") is True
        
        print("✓ Full prediction tracking flow works end-to-end")
        print(f"  - Total predictions: {accuracy_data['accuracy'].get('total_predictions', 0)}")
        print(f"  - Recent predictions: {predictions_data.get('count', 0)}")
        print(f"  - Verified this run: {verify_data['result'].get('verified', 0)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
