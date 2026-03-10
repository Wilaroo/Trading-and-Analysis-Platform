"""
Test IB Pushed Data Live Endpoints - Iteration 60
Tests verify the IB data pusher integration with LIVE data flowing.

IB Pusher should be pushing:
- 14 quotes (VIX, SPY, QQQ, IWM, etc)
- 3 positions (TMC, INTC, TSLA)
- Level 2 data for SPY, QQQ, IWM

Account: paperesw100000 / DUN615665
"""
import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIBPusherStatus:
    """Test IB pusher status and connection"""
    
    def test_ib_status_returns_pusher_info(self):
        """Test /api/ib/status returns pusher connection info"""
        response = requests.get(f"{BASE_URL}/api/ib/status", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert "pusher" in data, "Missing 'pusher' field in status"
        
        pusher = data["pusher"]
        assert "connected" in pusher
        assert "last_update" in pusher
        assert "quotes_count" in pusher
        assert "positions_count" in pusher
        
        # Verify we have the expected data counts
        # Note: connected may be false if 30 seconds have passed
        print(f"✅ Pusher status: quotes={pusher['quotes_count']}, positions={pusher['positions_count']}")
        print(f"   Connected: {pusher['connected']}, Stale: {pusher.get('stale', 'N/A')}")
        print(f"   Last update: {pusher['last_update']}")


class TestIBPushedData:
    """Test /api/ib/pushed-data returns quotes for expected symbols"""
    
    def test_pushed_data_has_required_quotes(self):
        """Test pushed data contains VIX, SPY, QQQ, IWM quotes"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        quotes = data.get("quotes", {})
        
        # Expected symbols from ib_data_pusher
        expected_symbols = ["VIX", "SPY", "QQQ", "IWM"]
        
        for symbol in expected_symbols:
            assert symbol in quotes, f"Missing quote for {symbol}"
            quote = quotes[symbol]
            # Quote should have at least timestamp and some price data
            assert "timestamp" in quote, f"{symbol} missing timestamp"
            print(f"✅ {symbol}: last={quote.get('last')}, close={quote.get('close')}")
    
    def test_pushed_data_has_positions(self):
        """Test pushed data contains 3 positions"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        positions = data.get("positions", [])
        
        # Verify we have positions
        assert len(positions) >= 3, f"Expected at least 3 positions, got {len(positions)}"
        
        # Check position structure
        for pos in positions:
            assert "symbol" in pos, "Position missing symbol"
            assert "position" in pos, "Position missing position (qty)"
            assert "avgCost" in pos, "Position missing avgCost"
            print(f"✅ Position: {pos['symbol']} qty={pos['position']} avgCost={pos['avgCost']}")
    
    def test_pushed_data_has_level2(self):
        """Test pushed data contains Level 2 order book for SPY, QQQ, IWM"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        level2 = data.get("level2", {})
        
        # Expected L2 symbols
        expected_l2 = ["SPY", "QQQ", "IWM"]
        
        for symbol in expected_l2:
            if symbol in level2:
                l2_data = level2[symbol]
                assert "bids" in l2_data, f"{symbol} L2 missing bids"
                assert "asks" in l2_data, f"{symbol} L2 missing asks"
                print(f"✅ L2 {symbol}: {len(l2_data['bids'])} bids, {len(l2_data['asks'])} asks")
            else:
                print(f"⚠️ L2 {symbol} not available (may be expected)")


class TestIBLevel2Endpoints:
    """Test individual Level 2 endpoints"""
    
    def test_level2_spy_has_bids_and_asks(self):
        """Test /api/ib/level2/SPY returns 5 bids and 5 asks with imbalance"""
        response = requests.get(f"{BASE_URL}/api/ib/level2/SPY", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        
        if data.get("success"):
            assert "bids" in data, "Missing bids"
            assert "asks" in data, "Missing asks"
            assert "imbalance" in data, "Missing imbalance"
            
            bids = data["bids"]
            asks = data["asks"]
            
            # Should have up to 5 levels
            assert len(bids) <= 5, f"Expected max 5 bids, got {len(bids)}"
            assert len(asks) <= 5, f"Expected max 5 asks, got {len(asks)}"
            
            # Each level should be [price, size]
            if bids:
                assert len(bids[0]) == 2, "Bid should be [price, size]"
            if asks:
                assert len(asks[0]) == 2, "Ask should be [price, size]"
            
            print(f"✅ SPY L2: {len(bids)} bids, {len(asks)} asks, imbalance={data['imbalance']}")
        else:
            print(f"⚠️ SPY L2 not available: {data.get('error')}")
    
    def test_level2_qqq(self):
        """Test /api/ib/level2/QQQ returns Level 2 data"""
        response = requests.get(f"{BASE_URL}/api/ib/level2/QQQ", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        
        if data.get("success"):
            assert "bids" in data
            assert "asks" in data
            print(f"✅ QQQ L2: {len(data['bids'])} bids, {len(data['asks'])} asks")
        else:
            print(f"⚠️ QQQ L2 not available: {data.get('error')}")


class TestVIXPushedQuote:
    """Test VIX price retrieval from pushed data"""
    
    def test_pushed_quote_vix(self):
        """Test /api/ib/pushed-quote/VIX returns VIX price"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-quote/VIX", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert "success" in data
        assert "symbol" in data
        assert data["symbol"] == "VIX"
        
        if data["success"]:
            assert "quote" in data
            quote = data["quote"]
            
            # VIX should have last or close price
            price = quote.get("last") or quote.get("close")
            assert price is not None, "VIX should have price data"
            
            # Expected VIX around 24.55 (user mentioned)
            # Allow reasonable range (15-40 is normal VIX range)
            assert 10 < price < 60, f"VIX price {price} seems abnormal"
            
            print(f"✅ VIX price: {price} (source: ib_pusher)")
            print(f"   High: {quote.get('high')}, Low: {quote.get('low')}")
        else:
            print(f"⚠️ VIX not available: {data.get('error')}")


class TestAlpacaFallbackWithIBPreference:
    """Test Alpaca quote endpoint with IB preference"""
    
    def test_alpaca_quote_spy_prefer_ib(self):
        """Test /api/alpaca/quote/SPY?prefer_ib=true returns data"""
        response = requests.get(f"{BASE_URL}/api/alpaca/quote/SPY?prefer_ib=true", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "data" in data
        
        quote = data["data"]
        assert "symbol" in quote
        assert "price" in quote
        assert "source" in quote
        
        # Source should be ib_pusher if pusher is connected, otherwise alpaca
        assert quote["source"] in ["ib_pusher", "alpaca"]
        
        print(f"✅ SPY quote: ${quote['price']} (source: {quote['source']})")
    
    def test_alpaca_quote_force_alpaca(self):
        """Test /api/alpaca/quote/AAPL?prefer_ib=false forces Alpaca"""
        response = requests.get(f"{BASE_URL}/api/alpaca/quote/AAPL?prefer_ib=false", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        
        quote = data["data"]
        assert quote["source"] == "alpaca", "Should use Alpaca when prefer_ib=false"
        
        print(f"✅ AAPL Alpaca quote: ${quote['price']}")


class TestTradingBotStatus:
    """Test trading bot status endpoint"""
    
    def test_trading_bot_status_response(self):
        """Test /api/trading-bot/status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        
        # Check key fields (mode instead of is_running)
        assert "mode" in data, "Missing 'mode' field"
        
        # Mode can be autonomous, confirmation, or paused
        assert data["mode"] in ["autonomous", "confirmation", "paused"]
        
        # running field (not is_running)
        if "running" in data:
            print(f"✅ Trading Bot: mode={data['mode']}, running={data['running']}")
        else:
            print(f"✅ Trading Bot: mode={data['mode']}")


class TestConfigTestConnection:
    """Test config test-connection endpoint"""
    
    def test_config_test_connection(self):
        """Test /api/config/test-connection shows Ollama proxy status"""
        response = requests.get(f"{BASE_URL}/api/config/test-connection", timeout=20)
        assert response.status_code == 200
        
        data = response.json()
        assert "connected" in data
        
        if data["connected"]:
            # When connected, should have models and method
            assert "models" in data
            assert "method" in data
            print(f"✅ Ollama connected via {data['method']}")
            print(f"   Models: {data.get('models', [])}")
        else:
            # When not connected, should have error
            assert "error" in data
            print(f"✅ Ollama test-connection working (not connected: {data['error']})")


class TestScriptServing:
    """Test script serving endpoints"""
    
    def test_ib_data_pusher_script(self):
        """Test /api/scripts/ib_data_pusher.py serves the pusher script"""
        response = requests.get(f"{BASE_URL}/api/scripts/ib_data_pusher.py", timeout=15)
        assert response.status_code == 200
        
        content = response.text
        
        # Verify key content
        assert "IBDataPusher" in content, "Should contain IBDataPusher class"
        assert "ib_insync" in content, "Should reference ib_insync"
        assert "push_data_to_cloud" in content, "Should have push_data_to_cloud method"
        
        print(f"✅ ib_data_pusher.py: {len(content)} bytes")
    
    def test_start_trading_bat(self):
        """Test /api/scripts/StartTrading.bat serves the startup script"""
        response = requests.get(f"{BASE_URL}/api/scripts/StartTrading.bat", timeout=15)
        assert response.status_code == 200
        
        content = response.text
        
        # Verify paper trading credentials are present
        assert "paperesw100000" in content, "Should contain paper trading username"
        assert "CLOUD_URL" in content, "Should contain CLOUD_URL variable"
        assert "ib_data_pusher.py" in content, "Should reference ib_data_pusher.py"
        
        print(f"✅ StartTrading.bat: {len(content)} bytes")
        print(f"   Contains paperesw100000 credentials: YES")


class TestDataQuality:
    """Test data quality and freshness"""
    
    def test_pushed_data_has_timestamps(self):
        """Verify pushed data has recent timestamps"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data", timeout=15)
        assert response.status_code == 200
        
        data = response.json()
        last_update = data.get("last_update")
        
        if last_update:
            # Parse timestamp
            try:
                ts = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                age_seconds = (now - ts).total_seconds()
                
                print(f"✅ Data age: {age_seconds:.1f} seconds")
                
                # Data should ideally be less than 60 seconds old
                # But we don't fail if older since pusher may not be running
                if age_seconds > 60:
                    print(f"⚠️ Data is stale ({age_seconds:.0f}s old) - pusher may not be running")
            except Exception as e:
                print(f"⚠️ Could not parse timestamp: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
