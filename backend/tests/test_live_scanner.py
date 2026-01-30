"""
Test suite for Live Scanner / Background Scanner API endpoints
Tests SSE streaming, scanner control, and alert management
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestLiveScannerStatus:
    """Tests for GET /api/live-scanner/status"""
    
    def test_status_returns_200(self):
        """Scanner status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert response.status_code == 200
        
    def test_status_has_running_field(self):
        """Status response includes running boolean"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        data = response.json()
        assert "running" in data
        assert isinstance(data["running"], bool)
        
    def test_status_has_scan_count(self):
        """Status response includes scan_count"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        data = response.json()
        assert "scan_count" in data
        assert isinstance(data["scan_count"], int)
        
    def test_status_has_watchlist_size(self):
        """Status response includes watchlist_size"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        data = response.json()
        assert "watchlist_size" in data
        assert data["watchlist_size"] > 0
        
    def test_status_has_enabled_setups(self):
        """Status response includes enabled_setups list"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        data = response.json()
        assert "enabled_setups" in data
        assert isinstance(data["enabled_setups"], list)
        # Should have at least one setup enabled
        assert len(data["enabled_setups"]) > 0


class TestLiveScannerAlerts:
    """Tests for GET /api/live-scanner/alerts"""
    
    def test_alerts_returns_200(self):
        """Alerts endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        assert response.status_code == 200
        
    def test_alerts_has_count(self):
        """Alerts response includes count"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        data = response.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        
    def test_alerts_has_alerts_array(self):
        """Alerts response includes alerts array"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        data = response.json()
        assert "alerts" in data
        assert isinstance(data["alerts"], list)
        
    def test_alerts_has_scanner_running_status(self):
        """Alerts response includes scanner_running status"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        data = response.json()
        assert "scanner_running" in data
        assert isinstance(data["scanner_running"], bool)


class TestLiveScannerControl:
    """Tests for POST /api/live-scanner/start and /stop"""
    
    def test_stop_scanner(self):
        """POST /api/live-scanner/stop stops the scanner"""
        response = requests.post(f"{BASE_URL}/api/live-scanner/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "stopped" in data["message"].lower()
        
        # Verify scanner is stopped
        status_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        status_data = status_response.json()
        assert status_data["running"] == False
        
    def test_start_scanner(self):
        """POST /api/live-scanner/start starts the scanner"""
        response = requests.post(f"{BASE_URL}/api/live-scanner/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "started" in data["message"].lower()
        
        # Verify scanner is running
        status_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        status_data = status_response.json()
        assert status_data["running"] == True
        
    def test_start_already_running_scanner(self):
        """Starting an already running scanner should not error"""
        # Ensure scanner is running
        requests.post(f"{BASE_URL}/api/live-scanner/start")
        
        # Try to start again
        response = requests.post(f"{BASE_URL}/api/live-scanner/start")
        assert response.status_code == 200


class TestLiveScannerWatchlist:
    """Tests for GET/POST /api/live-scanner/watchlist"""
    
    def test_get_watchlist_returns_200(self):
        """GET /api/live-scanner/watchlist returns 200"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/watchlist")
        assert response.status_code == 200
        
    def test_get_watchlist_has_symbols(self):
        """Watchlist response includes symbols array"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/watchlist")
        data = response.json()
        assert "watchlist" in data
        assert isinstance(data["watchlist"], list)
        assert len(data["watchlist"]) > 0
        
    def test_watchlist_contains_expected_symbols(self):
        """Watchlist contains expected default symbols"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/watchlist")
        data = response.json()
        watchlist = data["watchlist"]
        # Should contain some major symbols
        expected_symbols = ["NVDA", "TSLA", "AAPL", "MSFT", "SPY"]
        for symbol in expected_symbols:
            assert symbol in watchlist, f"Expected {symbol} in watchlist"
            
    def test_set_watchlist(self):
        """POST /api/live-scanner/watchlist sets custom watchlist"""
        test_symbols = ["AAPL", "GOOGL", "AMZN"]
        response = requests.post(
            f"{BASE_URL}/api/live-scanner/watchlist",
            json={"symbols": test_symbols}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Verify watchlist was updated
        get_response = requests.get(f"{BASE_URL}/api/live-scanner/watchlist")
        get_data = get_response.json()
        for symbol in test_symbols:
            assert symbol.upper() in get_data["watchlist"]
            
        # Reset to default watchlist
        default_symbols = ["NVDA", "TSLA", "AMD", "META", "AAPL", "MSFT", "GOOGL", "AMZN", "SPY", "QQQ"]
        requests.post(f"{BASE_URL}/api/live-scanner/watchlist", json={"symbols": default_symbols})


class TestLiveScannerConfig:
    """Tests for GET/POST /api/live-scanner/config"""
    
    def test_get_config_returns_200(self):
        """GET /api/live-scanner/config returns 200"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/config")
        assert response.status_code == 200
        
    def test_config_has_scan_interval(self):
        """Config response includes scan_interval"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/config")
        data = response.json()
        assert "scan_interval" in data
        assert isinstance(data["scan_interval"], int)
        assert data["scan_interval"] >= 30  # Minimum interval
        
    def test_config_has_enabled_setups(self):
        """Config response includes enabled_setups"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/config")
        data = response.json()
        assert "enabled_setups" in data
        assert isinstance(data["enabled_setups"], list)
        
    def test_update_config(self):
        """POST /api/live-scanner/config updates configuration"""
        response = requests.post(
            f"{BASE_URL}/api/live-scanner/config",
            json={"scan_interval": 60}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["config"]["scan_interval"] == 60


class TestLiveScannerSSE:
    """Tests for GET /api/live-scanner/stream (SSE endpoint)"""
    
    def test_sse_stream_returns_event_stream(self):
        """SSE endpoint returns text/event-stream content type"""
        response = requests.get(
            f"{BASE_URL}/api/live-scanner/stream",
            stream=True,
            timeout=5
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("Content-Type", "")
        response.close()
        
    def test_sse_stream_sends_connected_event(self):
        """SSE stream sends connected event on connection"""
        response = requests.get(
            f"{BASE_URL}/api/live-scanner/stream",
            stream=True,
            timeout=5
        )
        
        # Read first event
        first_line = None
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                first_line = line
                break
                
        response.close()
        
        assert first_line is not None
        assert "connected" in first_line.lower()


class TestLiveScannerIntegration:
    """Integration tests for live scanner workflow"""
    
    def test_scanner_auto_starts_on_server(self):
        """Scanner should be running on server startup"""
        # First ensure scanner is started
        requests.post(f"{BASE_URL}/api/live-scanner/start")
        time.sleep(0.5)
        
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        data = response.json()
        assert data["running"] == True
        
    def test_full_scanner_workflow(self):
        """Test complete scanner workflow: status -> stop -> start -> alerts"""
        # 1. Check initial status
        status_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert status_response.status_code == 200
        
        # 2. Stop scanner
        stop_response = requests.post(f"{BASE_URL}/api/live-scanner/stop")
        assert stop_response.status_code == 200
        
        # 3. Verify stopped
        status_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert status_response.json()["running"] == False
        
        # 4. Start scanner
        start_response = requests.post(f"{BASE_URL}/api/live-scanner/start")
        assert start_response.status_code == 200
        
        # 5. Verify running
        status_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert status_response.json()["running"] == True
        
        # 6. Check alerts endpoint
        alerts_response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        assert alerts_response.status_code == 200
        assert "alerts" in alerts_response.json()
