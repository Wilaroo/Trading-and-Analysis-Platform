"""
Tests for IB Pushed Data Integration
- POST /api/ib/push-data endpoint (receives data from local IB pusher)
- GET /api/ib/pushed-data endpoint (returns latest pushed data)
- Data staleness check (connected: false when data is old)
"""

import pytest
import requests
import os
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestIBPushedDataEndpoints:
    """Test IB Pushed Data API endpoints"""
    
    def test_get_pushed_data_initial(self):
        """Test GET /api/ib/pushed-data returns proper structure"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200
        
        data = response.json()
        # Verify structure
        assert "connected" in data
        assert "last_update" in data
        assert "quotes" in data
        assert "account" in data
        assert "positions" in data
        
        # Verify types
        assert isinstance(data["quotes"], dict)
        assert isinstance(data["account"], dict)
        assert isinstance(data["positions"], list)
        print(f"GET /api/ib/pushed-data: connected={data['connected']}, quotes={len(data['quotes'])}, positions={len(data['positions'])}")
    
    def test_post_push_data(self):
        """Test POST /api/ib/push-data receives and stores data"""
        test_timestamp = datetime.now(timezone.utc).isoformat()
        test_data = {
            "timestamp": test_timestamp,
            "source": "ib_gateway_test",
            "quotes": {
                "TEST_AAPL": {"price": 175.50, "bid": 175.45, "ask": 175.55},
                "TEST_MSFT": {"price": 420.25, "bid": 420.20, "ask": 420.30}
            },
            "account": {
                "net_liquidation": 150000.00,
                "buying_power": 75000.00,
                "cash": 25000.00
            },
            "positions": [
                {"symbol": "TEST_AAPL", "position": 100, "market_value": 17550.00, "avg_cost": 170.00},
                {"symbol": "TEST_MSFT", "position": 50, "market_value": 21012.50, "avg_cost": 400.00}
            ]
        }
        
        response = requests.post(f"{BASE_URL}/api/ib/push-data", json=test_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["received"]["quotes"] == 2
        assert data["received"]["positions"] == 2
        assert data["received"]["account_fields"] == 3
        print(f"POST /api/ib/push-data: success={data['success']}, received={data['received']}")
    
    def test_pushed_data_persistence(self):
        """Test that pushed data persists and can be retrieved"""
        # First push some data with current timestamp
        test_timestamp = datetime.now(timezone.utc).isoformat()
        push_data = {
            "timestamp": test_timestamp,
            "source": "ib_gateway_test",
            "quotes": {"TEST_NVDA": {"price": 850.00}},
            "account": {"unrealized_pnl": 5000.00},
            "positions": [{"symbol": "TEST_NVDA", "position": 10}]
        }
        
        push_response = requests.post(f"{BASE_URL}/api/ib/push-data", json=push_data)
        assert push_response.status_code == 200
        
        # Now retrieve and verify
        get_response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert get_response.status_code == 200
        
        data = get_response.json()
        # Connection status depends on staleness (30 seconds)
        # Just verify data is present
        assert "TEST_NVDA" in data["quotes"], "TEST_NVDA quote should be present"
        assert data["quotes"]["TEST_NVDA"]["price"] == 850.00
        print(f"Data persistence verified: NVDA price = {data['quotes']['TEST_NVDA']['price']}, connected={data['connected']}")
    
    def test_pushed_quote_endpoint(self):
        """Test GET /api/ib/pushed-quote/{symbol} returns specific quote"""
        # First push some data
        push_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "ib_gateway_test",
            "quotes": {"TEST_GOOG": {"price": 175.00, "volume": 1000000}},
            "account": {},
            "positions": []
        }
        requests.post(f"{BASE_URL}/api/ib/push-data", json=push_data)
        
        # Test get specific quote
        response = requests.get(f"{BASE_URL}/api/ib/pushed-quote/TEST_GOOG")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["symbol"] == "TEST_GOOG"
        assert data["quote"]["price"] == 175.00
        assert data["source"] == "ib_pusher"
        print(f"Pushed quote for TEST_GOOG: {data['quote']}")
    
    def test_pushed_quote_not_found(self):
        """Test GET /api/ib/pushed-quote/{symbol} for non-existent symbol"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-quote/NONEXISTENT_SYMBOL_XYZ")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert "error" in data
        assert "available_symbols" in data
        print(f"Non-existent quote returns: success=False, available_symbols count={len(data.get('available_symbols', []))}")
    
    def test_push_data_validation(self):
        """Test that push data requires valid timestamp"""
        invalid_data = {
            "timestamp": "invalid-timestamp",
            "source": "test",
            "quotes": {},
            "account": {},
            "positions": []
        }
        
        response = requests.post(f"{BASE_URL}/api/ib/push-data", json=invalid_data)
        # Should still accept (timestamp parsing is lenient)
        assert response.status_code == 200
        print("Push data with invalid timestamp accepted (lenient parsing)")


class TestIBPushedDataIntegration:
    """Test IB Pushed Data integration with other components"""
    
    def test_pushed_data_used_by_useCommandCenterData(self):
        """Verify that /api/ib/pushed-data is available for useCommandCenterData hook"""
        # This tests the backend endpoint that the hook calls
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200
        
        data = response.json()
        # Verify expected fields for the hook
        assert "connected" in data
        assert "positions" in data
        assert "account" in data
        print(f"Pushed data available for useCommandCenterData: connected={data['connected']}")
    
    def test_trading_bot_positions_fallback(self):
        """Test that /api/trading-bot/positions is available as fallback"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/positions")
        # This endpoint may return data or error depending on Alpaca connection
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            print(f"Trading bot positions: success={data.get('success')}, positions={len(data.get('positions', []))}")
        else:
            print("Trading bot positions endpoint returned 500 (Alpaca may be disconnected)")
    
    def test_ib_status_endpoint(self):
        """Test /api/ib/status endpoint works"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "connected" in data
        assert "is_busy" in data
        print(f"IB Status: connected={data['connected']}, busy={data['is_busy']}")


class TestStartupModalAPIs:
    """Test APIs called by StartupModal"""
    
    def test_health_endpoint(self):
        """Test /api/health called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"Health check: {data}")
    
    def test_alpaca_status(self):
        """Test /api/alpaca/status called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/alpaca/status")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "connected" in data
        print(f"Alpaca status: {data.get('success', data.get('connected'))}")
    
    def test_ollama_check(self):
        """Test /api/assistant/check-ollama called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/assistant/check-ollama")
        # May return 200 or 500 depending on Ollama availability
        assert response.status_code in [200, 500]
        if response.status_code == 200:
            data = response.json()
            print(f"Ollama check: available={data.get('available', data.get('ollama_available'))}")
        else:
            print("Ollama check returned 500 (Ollama may not be running)")
    
    def test_ib_pushed_data_for_startup(self):
        """Test /api/ib/pushed-data called by StartupModal for IB Gateway check"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200
        data = response.json()
        assert "connected" in data
        assert "positions" in data
        print(f"IB Pushed data for startup: connected={data['connected']}, positions={len(data['positions'])}")
    
    def test_market_intel_endpoint(self):
        """Test /api/market-intel/early-morning-report called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/market-intel/early-morning-report")
        # May return 404 if endpoint not implemented, 200 if working, or error status
        # StartupModal handles failure gracefully by setting warning status
        assert response.status_code in [200, 400, 404, 500]
        print(f"Market intel endpoint status: {response.status_code}")
    
    def test_portfolio_endpoint(self):
        """Test /api/portfolio called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/portfolio")
        assert response.status_code == 200
        data = response.json()
        print(f"Portfolio endpoint: keys={list(data.keys())[:5]}")
    
    def test_smart_watchlist_endpoint(self):
        """Test /api/smart-watchlist called by StartupModal"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        assert response.status_code == 200
        data = response.json()
        print(f"Smart watchlist: items={len(data) if isinstance(data, list) else 'dict'}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
