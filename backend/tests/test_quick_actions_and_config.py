"""
Test Quick Actions API and Config/Ollama Model API endpoints
Tests for iteration 42 - Startup Modal, Quick Actions, Ollama Model Toggle
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://dual-gpu-finbert.preview.emergentagent.com').rstrip('/')


class TestQuickActionsAPIs:
    """Tests for Quick Actions API endpoints: add-to-watchlist, create-alert, get alerts"""
    
    def test_add_to_watchlist_success(self):
        """Test POST /api/quick-actions/add-to-watchlist - add a symbol"""
        payload = {
            "symbol": "TEST_NVDA",
            "source": "quick_action",
            "reason": "Testing quick action add"
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/add-to-watchlist", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert data.get("symbol") == "TEST_NVDA", f"Expected symbol=TEST_NVDA, got {data.get('symbol')}"
        assert data.get("action") in ["added", "updated"], f"Expected action=added/updated, got {data.get('action')}"
        assert "message" in data, f"Expected message in response: {data}"
        print(f"✅ Add to watchlist: {data.get('message')}")
    
    def test_add_to_watchlist_duplicate(self):
        """Test POST /api/quick-actions/add-to-watchlist - duplicate should update"""
        payload = {
            "symbol": "TEST_NVDA",
            "source": "quick_action_dup",
            "reason": "Testing duplicate add"
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/add-to-watchlist", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("success") == True
        # Should indicate it was updated (already exists)
        print(f"✅ Add duplicate to watchlist: {data.get('message')}")
    
    def test_create_price_alert_success(self):
        """Test POST /api/quick-actions/create-alert - create price alert"""
        payload = {
            "symbol": "TEST_AAPL",
            "alert_type": "price",
            "condition": "above",
            "value": 200.00,
            "note": "Test alert from quick action"
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/create-alert", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data.get("success") == True, f"Expected success=True: {data}"
        assert data.get("symbol") == "TEST_AAPL", f"Expected symbol=TEST_AAPL: {data}"
        assert data.get("action") == "created", f"Expected action=created: {data}"
        assert "alert_id" in data, f"Expected alert_id in response: {data}"
        assert "description" in data, f"Expected description in response: {data}"
        print(f"✅ Create alert: {data.get('description')}")
    
    def test_create_percent_alert(self):
        """Test POST /api/quick-actions/create-alert - percent alert type"""
        payload = {
            "symbol": "TEST_MSFT",
            "alert_type": "percent",
            "condition": "below",
            "value": 5.0,
            "note": "Test percent alert"
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/create-alert", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("success") == True
        print(f"✅ Create percent alert: {data.get('description')}")
    
    def test_create_volume_alert(self):
        """Test POST /api/quick-actions/create-alert - volume alert type"""
        payload = {
            "symbol": "TEST_TSLA",
            "alert_type": "volume",
            "condition": "above",
            "value": 1000000,
            "note": "Test volume alert"
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/create-alert", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("success") == True
        print(f"✅ Create volume alert: {data.get('description')}")
    
    def test_create_alert_invalid_type(self):
        """Test POST /api/quick-actions/create-alert - invalid alert type should fail"""
        payload = {
            "symbol": "TEST_ERR",
            "alert_type": "invalid_type",
            "condition": "above",
            "value": 100.00
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/create-alert", json=payload)
        
        assert response.status_code == 400, f"Expected 400 for invalid type, got {response.status_code}"
        print(f"✅ Invalid alert type correctly rejected")
    
    def test_create_alert_invalid_condition(self):
        """Test POST /api/quick-actions/create-alert - invalid condition should fail"""
        payload = {
            "symbol": "TEST_ERR",
            "alert_type": "price",
            "condition": "invalid_cond",
            "value": 100.00
        }
        response = requests.post(f"{BASE_URL}/api/quick-actions/create-alert", json=payload)
        
        assert response.status_code == 400, f"Expected 400 for invalid condition, got {response.status_code}"
        print(f"✅ Invalid alert condition correctly rejected")
    
    def test_get_alerts_list(self):
        """Test GET /api/quick-actions/alerts - get all active alerts"""
        response = requests.get(f"{BASE_URL}/api/quick-actions/alerts")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data.get("success") == True, f"Expected success=True: {data}"
        assert "alerts" in data, f"Expected alerts list in response: {data}"
        assert "count" in data, f"Expected count in response: {data}"
        assert isinstance(data["alerts"], list), f"Expected alerts to be a list: {data}"
        print(f"✅ Get alerts: Found {data.get('count')} active alerts")
    
    def test_delete_alerts_for_symbol(self):
        """Test DELETE /api/quick-actions/alerts/{symbol} - delete test alerts"""
        # Delete test alerts we created
        for symbol in ["TEST_AAPL", "TEST_MSFT", "TEST_TSLA"]:
            response = requests.delete(f"{BASE_URL}/api/quick-actions/alerts/{symbol}")
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            data = response.json()
            assert data.get("success") == True
        print(f"✅ Delete alerts: Cleaned up test alerts")
    
    def test_remove_from_watchlist(self):
        """Test DELETE /api/quick-actions/remove-from-watchlist/{symbol}"""
        response = requests.delete(f"{BASE_URL}/api/quick-actions/remove-from-watchlist/TEST_NVDA")
        
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}"
        if response.status_code == 200:
            data = response.json()
            assert data.get("success") == True
            print(f"✅ Remove from watchlist: {data.get('message')}")
        else:
            print(f"✅ Remove from watchlist: Symbol already removed or not found")


class TestOllamaConfigAPIs:
    """Tests for Ollama Model Toggle and Config endpoints"""
    
    def test_get_config(self):
        """Test GET /api/config - get current configuration"""
        response = requests.get(f"{BASE_URL}/api/config")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "ollama_url" in data, f"Expected ollama_url in response: {data}"
        assert "ollama_model" in data, f"Expected ollama_model in response: {data}"
        assert "ollama_connected" in data, f"Expected ollama_connected in response: {data}"
        print(f"✅ Get config: ollama_model={data.get('ollama_model')}, ollama_url={data.get('ollama_url')[:30]}...")
    
    def test_ollama_model_change(self):
        """Test POST /api/config/ollama-model - change the model"""
        # Get current model first
        config_res = requests.get(f"{BASE_URL}/api/config")
        current_model = config_res.json().get("ollama_model", "qwen2.5:3b")
        
        # Try to change to a different model
        new_model = "llama3:8b" if current_model != "llama3:8b" else "qwen2.5:3b"
        
        payload = {"model": new_model}
        response = requests.post(f"{BASE_URL}/api/config/ollama-model", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response
        assert data.get("success") == True, f"Expected success=True: {data}"
        assert data.get("model") == new_model, f"Expected model={new_model}: {data}"
        assert "message" in data, f"Expected message in response: {data}"
        print(f"✅ Change Ollama model: Changed to {new_model}")
        
        # Restore original model
        restore_payload = {"model": current_model}
        restore_res = requests.post(f"{BASE_URL}/api/config/ollama-model", json=restore_payload)
        assert restore_res.status_code == 200, "Failed to restore original model"
        print(f"✅ Restored original model: {current_model}")
    
    def test_ollama_model_change_non_standard(self):
        """Test POST /api/config/ollama-model - non-standard model (should warn but work)"""
        payload = {"model": "custom-model:latest"}
        response = requests.post(f"{BASE_URL}/api/config/ollama-model", json=payload)
        
        # Should still work (with warning in logs) - API doesn't reject non-standard models
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("success") == True
        print(f"✅ Non-standard model accepted with warning")
        
        # Restore to standard model
        requests.post(f"{BASE_URL}/api/config/ollama-model", json={"model": "qwen2.5:3b"})
    
    def test_config_test_connection(self):
        """Test GET /api/config/test-connection - test Ollama connection"""
        response = requests.get(f"{BASE_URL}/api/config/test-connection")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Response should have connected field (may be true or false depending on Ollama availability)
        assert "connected" in data, f"Expected 'connected' field in response: {data}"
        
        if data.get("connected"):
            assert "models" in data, f"Expected 'models' if connected: {data}"
            print(f"✅ Test connection: Connected! Models: {data.get('models')}")
        else:
            assert "error" in data, f"Expected 'error' if not connected: {data}"
            print(f"✅ Test connection: Not connected (expected if ngrok not running): {data.get('error')}")


class TestHealthAndBasicAPIs:
    """Basic API health checks"""
    
    def test_health_endpoint(self):
        """Test GET /api/health - basic health check"""
        response = requests.get(f"{BASE_URL}/api/health")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✅ Health check passed")
    
    def test_smart_watchlist_endpoint(self):
        """Test GET /api/smart-watchlist - used by startup modal"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "watchlist" in data, f"Expected watchlist in response: {data}"
        print(f"✅ Smart watchlist: {len(data.get('watchlist', []))} items")
    
    def test_alpaca_status_endpoint(self):
        """Test GET /api/alpaca/status - used by startup modal"""
        response = requests.get(f"{BASE_URL}/api/alpaca/status")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "success" in data, f"Expected success field: {data}"
        print(f"✅ Alpaca status: success={data.get('success')}")
    
    def test_portfolio_endpoint(self):
        """Test GET /api/portfolio - used by startup modal"""
        response = requests.get(f"{BASE_URL}/api/portfolio")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "positions" in data, f"Expected positions in response: {data}"
        assert "summary" in data, f"Expected summary in response: {data}"
        print(f"✅ Portfolio endpoint accessible: {len(data.get('positions', []))} positions")
    
    def test_check_ollama_endpoint(self):
        """Test GET /api/assistant/check-ollama - used by startup modal"""
        response = requests.get(f"{BASE_URL}/api/assistant/check-ollama")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Either 'available' or 'ollama_available' should be present
        has_status = "available" in data or "ollama_available" in data
        assert has_status, f"Expected availability status: {data}"
        print(f"✅ Check Ollama endpoint accessible")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
