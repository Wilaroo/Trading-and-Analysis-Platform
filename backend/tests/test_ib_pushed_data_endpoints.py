"""
Test IB Pushed Data Endpoints and Related Features
Tests IB data pusher integration, VIX retrieval, Alpaca fallback, 
trading bot status, config test-connection, and script serving.

IB data pusher may not be running during testing (user's local script).
Tests verify endpoints handle both connected and disconnected states gracefully.
"""
import pytest
import requests
import os

# Get base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIBPushedDataEndpoints:
    """Tests for IB pushed data endpoints"""
    
    def test_ib_status_endpoint(self):
        """Test /api/ib/status returns valid response with pusher status"""
        response = requests.get(f"{BASE_URL}/api/ib/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure
        assert "connected" in data, "Missing 'connected' field"
        assert "pusher" in data, "Missing 'pusher' field"
        
        # Verify pusher sub-fields
        pusher = data["pusher"]
        assert "connected" in pusher, "Pusher missing 'connected' field"
        assert "last_update" in pusher, "Pusher missing 'last_update' field"
        assert "positions_count" in pusher, "Pusher missing 'positions_count' field"
        assert "quotes_count" in pusher, "Pusher missing 'quotes_count' field"
        
        # Check connection source handling
        assert "connection_source" in data, "Missing 'connection_source' field"
        assert data["connection_source"] in ["pusher", "direct", "none"], \
            f"Invalid connection_source: {data['connection_source']}"
        
        print(f"✅ IB Status: connected={data['connected']}, source={data['connection_source']}")
        print(f"   Pusher: connected={pusher['connected']}, quotes={pusher['quotes_count']}")
    
    def test_ib_pushed_data_endpoint(self):
        """Test /api/ib/pushed-data returns cached IB data"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify response structure
        assert "connected" in data, "Missing 'connected' field"
        assert "last_update" in data, "Missing 'last_update' field"
        assert "quotes" in data, "Missing 'quotes' field"
        assert "account" in data, "Missing 'account' field"
        assert "positions" in data, "Missing 'positions' field"
        assert "level2" in data, "Missing 'level2' field"
        
        # Verify types
        assert isinstance(data["quotes"], dict), "quotes should be a dict"
        assert isinstance(data["positions"], list), "positions should be a list"
        assert isinstance(data["level2"], dict), "level2 should be a dict"
        
        print(f"✅ Pushed Data: connected={data['connected']}")
        print(f"   Quotes: {len(data['quotes'])}, Positions: {len(data['positions'])}")
    
    def test_ib_level2_endpoint_with_symbol(self):
        """Test /api/ib/level2/{symbol} endpoint"""
        # Test with SPY - common symbol
        response = requests.get(f"{BASE_URL}/api/ib/level2/SPY", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Response structure varies based on whether L2 data is available
        if data.get("success"):
            assert "symbol" in data, "Missing 'symbol' field"
            assert "bids" in data, "Missing 'bids' field"
            assert "asks" in data, "Missing 'asks' field"
            assert "imbalance" in data, "Missing 'imbalance' field"
            print(f"✅ Level 2 for SPY: {len(data.get('bids', []))} bids, {len(data.get('asks', []))} asks")
        else:
            # L2 data not available - verify error format
            assert "error" in data, "Expected 'error' field when no L2 data"
            assert "available_symbols" in data, "Should list available_symbols"
            print(f"✅ Level 2 endpoint working (no data available for SPY)")
            print(f"   Available symbols: {data.get('available_symbols', [])}")
    
    def test_ib_level2_endpoint_unknown_symbol(self):
        """Test /api/ib/level2/{symbol} with unknown symbol"""
        response = requests.get(f"{BASE_URL}/api/ib/level2/ZZZZZZ", timeout=15)
        assert response.status_code == 200, "Should return 200 with error message"
        
        data = response.json()
        assert data.get("success") is False, "Should return success=false for unknown symbol"
        assert "error" in data, "Should have error message"
        print(f"✅ Level 2 unknown symbol handled: {data.get('error')}")


class TestVIXDataRetrieval:
    """Tests for VIX data from pushed IB data"""
    
    def test_vix_in_pushed_data(self):
        """Test VIX is included in pushed quotes if available"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        quotes = data.get("quotes", {})
        
        if "VIX" in quotes:
            vix = quotes["VIX"]
            assert "last" in vix or "close" in vix, "VIX should have price data"
            price = vix.get("last") or vix.get("close")
            print(f"✅ VIX data available: {price}")
        else:
            print(f"✅ VIX not in pushed data (pusher may not be connected)")
    
    def test_pushed_quote_endpoint_vix(self):
        """Test /api/ib/pushed-quote/VIX endpoint"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-quote/VIX", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert "symbol" in data, "Missing 'symbol' field"
        assert data["symbol"] == "VIX", "Symbol should be VIX"
        
        if data["success"]:
            assert "quote" in data, "Should have quote when successful"
            assert "source" in data, "Should have source field"
            print(f"✅ VIX quote available from {data['source']}")
        else:
            assert "error" in data, "Should have error when not successful"
            print(f"✅ VIX quote endpoint working (data not available)")


class TestAlpacaFallbackQuote:
    """Tests for Alpaca quote endpoint with IB fallback"""
    
    def test_alpaca_quote_prefer_ib_true(self):
        """Test /api/alpaca/quote/{symbol} with prefer_ib=true (default)"""
        response = requests.get(f"{BASE_URL}/api/alpaca/quote/AAPL", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert data["success"] is True, "Expected success=true"
        assert "data" in data, "Missing 'data' field"
        
        quote = data["data"]
        assert "symbol" in quote, "Quote missing 'symbol'"
        assert "price" in quote, "Quote missing 'price'"
        assert "source" in quote, "Quote missing 'source'"
        
        # Source should be either ib_pusher (if connected) or alpaca
        assert quote["source"] in ["ib_pusher", "alpaca"], f"Unexpected source: {quote['source']}"
        print(f"✅ AAPL quote: ${quote['price']} from {quote['source']}")
    
    def test_alpaca_quote_prefer_ib_false(self):
        """Test /api/alpaca/quote/{symbol}?prefer_ib=false to force Alpaca"""
        response = requests.get(f"{BASE_URL}/api/alpaca/quote/AAPL?prefer_ib=false", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, "Expected success=true"
        
        quote = data["data"]
        # When prefer_ib=false, should use Alpaca
        assert quote["source"] == "alpaca", f"Expected alpaca source when prefer_ib=false, got {quote['source']}"
        print(f"✅ AAPL quote (Alpaca forced): ${quote['price']} from {quote['source']}")
    
    def test_alpaca_status_endpoint(self):
        """Test /api/alpaca/status endpoint"""
        response = requests.get(f"{BASE_URL}/api/alpaca/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert "status" in data, "Missing 'status' field"
        print(f"✅ Alpaca status: {data['status']}")


class TestTradingBotStatus:
    """Tests for trading bot status endpoint"""
    
    def test_trading_bot_status(self):
        """Test /api/trading-bot/status endpoint"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert data["success"] is True, "Expected success=true"
        
        # Verify key status fields
        assert "mode" in data, "Missing 'mode' field"
        assert "is_running" in data, "Missing 'is_running' field"
        
        print(f"✅ Trading Bot Status: mode={data['mode']}, running={data['is_running']}")
        
        # Additional fields to verify
        if "risk_params" in data:
            risk = data["risk_params"]
            print(f"   Risk params: max_risk=${risk.get('max_risk_per_trade', 'N/A')}")
        
        if "account" in data and data["account"]:
            account = data["account"]
            print(f"   Account: equity=${account.get('equity', 'N/A')}")


class TestConfigTestConnection:
    """Tests for config test-connection endpoint"""
    
    def test_config_test_connection_endpoint(self):
        """Test /api/config/test-connection endpoint"""
        response = requests.get(f"{BASE_URL}/api/config/test-connection", timeout=20)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "connected" in data, "Missing 'connected' field"
        
        if data["connected"]:
            assert "models" in data, "Should have 'models' when connected"
            assert "method" in data, "Should have 'method' when connected"
            print(f"✅ Ollama connected via {data['method']}")
            print(f"   Models: {data.get('models', [])}")
        else:
            # Not connected is expected if no Ollama running
            assert "error" in data, "Should have 'error' when not connected"
            print(f"✅ Ollama test-connection working (not connected: {data.get('error', 'unknown')})")
    
    def test_config_endpoint(self):
        """Test /api/config endpoint returns current config"""
        response = requests.get(f"{BASE_URL}/api/config", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "ollama_url" in data, "Missing 'ollama_url' field"
        assert "ollama_model" in data, "Missing 'ollama_model' field"
        
        print(f"✅ Config: model={data['ollama_model']}")


class TestScriptServingEndpoints:
    """Tests for script serving endpoints"""
    
    def test_ib_data_pusher_script(self):
        """Test /api/scripts/ib_data_pusher.py endpoint"""
        response = requests.get(f"{BASE_URL}/api/scripts/ib_data_pusher.py", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        content = response.text
        assert len(content) > 100, "Script content seems too short"
        assert "IBDataPusher" in content, "Should contain IBDataPusher class"
        assert "ib_insync" in content, "Should reference ib_insync library"
        assert "push_data_to_cloud" in content, "Should contain push_data_to_cloud method"
        
        print(f"✅ ib_data_pusher.py served: {len(content)} bytes")
    
    def test_start_trading_bat_script(self):
        """Test /api/scripts/StartTrading.bat endpoint"""
        response = requests.get(f"{BASE_URL}/api/scripts/StartTrading.bat", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        content = response.text
        assert len(content) > 100, "Script content seems too short"
        
        # Verify key content from StartTrading.bat
        assert "paperesw100000" in content, "Should contain paper trading username"
        assert "IB_SYMBOLS" in content, "Should contain IB_SYMBOLS variable"
        assert "ib_data_pusher.py" in content, "Should reference ib_data_pusher.py"
        assert "CLOUD_URL" in content, "Should contain CLOUD_URL variable"
        
        print(f"✅ StartTrading.bat served: {len(content)} bytes")
        print(f"   Contains paper account credentials: paperesw100000")
    
    def test_script_not_found(self):
        """Test /api/scripts/{name} returns 404 for unknown scripts"""
        response = requests.get(f"{BASE_URL}/api/scripts/unknown_script.py", timeout=15)
        assert response.status_code == 404, f"Expected 404 for unknown script, got {response.status_code}"
        print(f"✅ Unknown script returns 404")


class TestLearningContextMarketSnapshot:
    """Tests for learning context provider market snapshot functionality"""
    
    def test_medium_learning_status(self):
        """Test /api/medium-learning/status to verify context provider integration"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/status", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        
        if data.get("success"):
            print(f"✅ Medium Learning Status: {data}")
        else:
            # Still valid - may not have trades yet
            print(f"✅ Medium Learning Status endpoint working")


class TestPusherSetupInfo:
    """Tests for pusher setup information endpoint"""
    
    def test_pusher_setup_endpoint(self):
        """Test /api/ib/pusher-setup returns setup information"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "cloud_url" in data, "Missing 'cloud_url' field"
        assert "push_endpoint" in data, "Missing 'push_endpoint' field"
        assert "status_endpoint" in data, "Missing 'status_endpoint' field"
        assert "setup_steps" in data, "Missing 'setup_steps' field"
        
        # Verify setup steps is a list
        assert isinstance(data["setup_steps"], list), "setup_steps should be a list"
        assert len(data["setup_steps"]) > 0, "Should have at least one setup step"
        
        print(f"✅ Pusher Setup Info:")
        print(f"   Cloud URL: {data['cloud_url']}")
        print(f"   Push endpoint: {data['push_endpoint']}")
        print(f"   Pusher connected: {data.get('pusher_connected', False)}")


class TestFundamentalsEndpoint:
    """Tests for fundamentals data endpoint"""
    
    def test_fundamentals_endpoint_single(self):
        """Test /api/ib/fundamentals/{symbol} endpoint"""
        response = requests.get(f"{BASE_URL}/api/ib/fundamentals/AAPL", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        
        if data["success"]:
            assert "symbol" in data, "Should have symbol when successful"
            print(f"✅ Fundamentals for AAPL available")
        else:
            assert "error" in data, "Should have error when not successful"
            print(f"✅ Fundamentals endpoint working (no data available)")
    
    def test_fundamentals_endpoint_all(self):
        """Test /api/ib/fundamentals endpoint for all fundamentals"""
        response = requests.get(f"{BASE_URL}/api/ib/fundamentals", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert "count" in data, "Missing 'count' field"
        assert "symbols" in data, "Missing 'symbols' field"
        
        print(f"✅ All Fundamentals: {data['count']} symbols available")


class TestInPlayStocks:
    """Tests for in-play stocks endpoint"""
    
    def test_inplay_stocks_endpoint(self):
        """Test /api/ib/inplay-stocks endpoint"""
        response = requests.get(f"{BASE_URL}/api/ib/inplay-stocks", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Missing 'success' field"
        assert "symbols" in data, "Missing 'symbols' field"
        assert "count" in data, "Missing 'count' field"
        
        symbols = data["symbols"]
        assert isinstance(symbols, list), "symbols should be a list"
        
        # Core ETFs should always be included
        core_etfs = {"SPY", "QQQ", "IWM"}
        symbols_set = set(symbols)
        present_core = core_etfs.intersection(symbols_set)
        
        print(f"✅ In-Play Stocks: {data['count']} symbols")
        print(f"   Core ETFs present: {list(present_core)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
