"""
API Health and Basic Connectivity Tests

These tests verify the basic API endpoints are working correctly.
Run with: pytest tests/test_api_health.py -v
"""
import pytest
import requests


class TestHealthEndpoints:
    """Test health check endpoints"""
    
    def test_health_endpoint(self, api_client, api_base_url):
        """Test /api/health returns healthy status"""
        response = requests.get(f"{api_base_url}/api/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
    
    def test_health_returns_json(self, api_client, api_base_url):
        """Test /api/health returns proper JSON"""
        response = requests.get(f"{api_base_url}/api/health", timeout=10)
        assert "application/json" in response.headers["content-type"]


class TestSystemEndpoints:
    """Test system monitoring endpoints"""
    
    def test_system_monitor(self, api_client, api_base_url):
        """Test /api/system/monitor returns system status"""
        response = requests.get(f"{api_base_url}/api/system/monitor", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data
        assert "services" in data
        assert "summary" in data


class TestIBConnectionEndpoints:
    """Test IB connection status endpoints"""
    
    def test_ib_status(self, api_client, api_base_url):
        """Test /api/ib/status returns connection info"""
        response = requests.get(f"{api_base_url}/api/ib/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "connected" in data or "status" in data
    
    def test_ib_pushed_data(self, api_client, api_base_url):
        """Test /api/ib/pushed-data returns data structure"""
        response = requests.get(f"{api_base_url}/api/ib/pushed-data", timeout=10)
        assert response.status_code == 200
        data = response.json()
        # Should have these keys even if empty
        assert "connected" in data or "positions" in data or "account" in data


class TestCollectionModeEndpoints:
    """Test data collection mode endpoints"""
    
    def test_collection_mode_status(self, api_client, api_base_url):
        """Test /api/ib/collection-mode/status returns queue info"""
        response = requests.get(f"{api_base_url}/api/ib/collection-mode/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "collection_mode" in data
        assert "queue" in data
        
        # Queue should have standard fields
        queue = data["queue"]
        assert "pending" in queue
        assert "completed" in queue
        assert "total" in queue
    
    def test_mode_status(self, api_client, api_base_url):
        """Test /api/ib/mode/status returns operating mode"""
        response = requests.get(f"{api_base_url}/api/ib/mode/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data
        assert "priority_collection" in data


class TestSentComEndpoints:
    """Test SentCom AI endpoints"""
    
    def test_sentcom_status(self, api_client, api_base_url):
        """Test /api/sentcom/status returns AI status"""
        response = requests.get(f"{api_base_url}/api/sentcom/status", timeout=10)
        # May return 200 or 503 depending on AI availability
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "success" in data
    
    def test_sentcom_stream(self, api_client, api_base_url):
        """Test /api/sentcom/stream returns message stream"""
        response = requests.get(f"{api_base_url}/api/sentcom/stream?limit=10", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "messages" in data


class TestMarketContextEndpoints:
    """Test market context endpoints"""
    
    def test_market_session_status(self, api_client, api_base_url):
        """Test /api/market-context/session/status returns session info"""
        response = requests.get(f"{api_base_url}/api/market-context/session/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "session" in data
