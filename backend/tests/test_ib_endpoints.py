"""
IB Router Endpoint Tests

These tests verify the IB-related API endpoints.
Run with: pytest tests/test_ib_endpoints.py -v
"""
import pytest
from fastapi.testclient import TestClient


class TestHistoricalDataEndpoints:
    """Test historical data collection endpoints"""
    
    def test_get_pending_requests(self, test_client):
        """Test /api/ib/historical-data/pending returns pending requests"""
        response = test_client.get("/api/ib/historical-data/pending")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "requests" in data
        assert isinstance(data["requests"], list)
    
    def test_mongodb_diagnostics(self, test_client):
        """Test /api/ib/mongodb/diagnostics returns database info"""
        response = test_client.get("/api/ib/mongodb/diagnostics")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "connection" in data
            assert "collections" in data


class TestScannerEndpoints:
    """Test scanner endpoints"""
    
    def test_enhanced_scanner(self, test_client):
        """Test /api/ib/scanner/enhanced runs scanner"""
        response = test_client.post(
            "/api/ib/scanner/enhanced",
            json={"scan_type": "top_gainers", "max_results": 5}
        )
        # May return 200 or 503 if IB not connected
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "results" in data or "error" in data


class TestAlertEndpoints:
    """Test alert endpoints"""
    
    def test_get_price_alerts(self, test_client):
        """Test /api/ib/alerts/price returns alert list"""
        response = test_client.get("/api/ib/alerts/price")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        assert "count" in data
    
    def test_create_price_alert(self, test_client):
        """Test creating a price alert"""
        alert_data = {
            "symbol": "TEST",
            "target_price": 100.00,
            "direction": "ABOVE",
            "note": "Test alert"
        }
        response = test_client.post("/api/ib/alerts/price", json=alert_data)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "created"
        assert "alert" in data
        
        # Clean up - delete the alert
        alert_id = data["alert"]["id"]
        delete_response = test_client.delete(f"/api/ib/alerts/price/{alert_id}")
        assert delete_response.status_code == 200
    
    def test_get_enhanced_alerts(self, test_client):
        """Test /api/ib/alerts/enhanced returns enhanced alerts"""
        response = test_client.get("/api/ib/alerts/enhanced?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        assert "count" in data


class TestNewsEndpoints:
    """Test news endpoints"""
    
    def test_get_news_providers(self, test_client):
        """Test /api/ib/news/providers returns provider list"""
        response = test_client.get("/api/ib/news/providers")
        # May return 200 or 500 if IB not connected
        assert response.status_code in [200, 500]
        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "providers" in data


class TestOrderEndpoints:
    """Test order-related endpoints"""
    
    def test_get_order_queue(self, test_client):
        """Test /api/ib/orders/queue returns order queue"""
        response = test_client.get("/api/ib/orders/queue")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "pending" in data or "counts" in data
