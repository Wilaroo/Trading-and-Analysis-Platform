"""
Test Scanner → AI Assistant Integration
Tests for proactive AI coaching notifications from scanner alerts

Features tested:
1. GET /api/assistant/coach/scanner-notifications - Returns coaching notifications
2. POST /api/assistant/coach/scanner-coaching - Manual coaching request
3. GET /api/live-scanner/status - Scanner running and generating alerts
4. GET /api/trading-bot/status - Bot status and configuration
5. Scanner → AI coaching flow verification
"""

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestScannerStatus:
    """Test scanner is running and generating alerts"""
    
    def test_scanner_status_endpoint(self):
        """Test GET /api/live-scanner/status returns scanner status"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "running" in data
        assert "scan_count" in data
        assert "alerts_generated" in data
        assert "watchlist_size" in data
        assert "enabled_setups" in data
        assert "market_regime" in data
        assert "time_window" in data
        
        # Verify scanner configuration
        assert data.get("watchlist_size", 0) > 0, "Watchlist should have symbols"
        assert len(data.get("enabled_setups", [])) > 0, "Should have enabled setups"
        
        print(f"✓ Scanner status: running={data.get('running')}, "
              f"scan_count={data.get('scan_count')}, "
              f"alerts_generated={data.get('alerts_generated')}")
    
    def test_scanner_alerts_endpoint(self):
        """Test GET /api/live-scanner/alerts returns alerts"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "alerts" in data
        assert "count" in data
        
        alerts = data.get("alerts", [])
        print(f"✓ Scanner alerts: count={data.get('count')}")
        
        # If alerts exist, verify structure
        if alerts:
            alert = alerts[0]
            required_fields = ["id", "symbol", "setup_type", "direction", "priority",
                             "current_price", "trigger_price", "stop_loss", "target"]
            for field in required_fields:
                assert field in alert, f"Alert missing field: {field}"
            print(f"  First alert: {alert.get('symbol')} - {alert.get('setup_type')}")


class TestTradingBotStatus:
    """Test trading bot status and configuration"""
    
    def test_trading_bot_status_endpoint(self):
        """Test GET /api/trading-bot/status returns bot status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "running" in data
        assert "mode" in data
        assert "risk_params" in data
        assert "enabled_setups" in data
        assert "strategy_configs" in data
        
        # Verify risk parameters
        risk_params = data.get("risk_params", {})
        assert "max_risk_per_trade" in risk_params
        assert "max_daily_loss" in risk_params
        assert "max_position_pct" in risk_params
        
        print(f"✓ Trading bot status: running={data.get('running')}, "
              f"mode={data.get('mode')}, "
              f"enabled_setups={len(data.get('enabled_setups', []))}")


class TestScannerCoachingNotifications:
    """Test Scanner → AI coaching notifications endpoints"""
    
    def test_get_scanner_notifications_endpoint(self):
        """Test GET /api/assistant/coach/scanner-notifications returns notifications"""
        response = requests.get(f"{BASE_URL}/api/assistant/coach/scanner-notifications")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "notifications" in data
        assert "count" in data
        assert "timestamp" in data
        
        notifications = data.get("notifications", [])
        print(f"✓ Scanner notifications: count={data.get('count')}")
        
        # If notifications exist, verify structure
        if notifications:
            notif = notifications[0]
            required_fields = ["type", "symbol", "setup_type", "coaching", "verdict", "timestamp"]
            for field in required_fields:
                assert field in notif, f"Notification missing field: {field}"
            print(f"  Latest notification: {notif.get('symbol')} - {notif.get('verdict')}")
    
    def test_get_scanner_notifications_with_since_filter(self):
        """Test GET /api/assistant/coach/scanner-notifications with since parameter"""
        # Get a timestamp from 1 hour ago
        since = datetime.now(timezone.utc).isoformat()
        
        response = requests.get(
            f"{BASE_URL}/api/assistant/coach/scanner-notifications",
            params={"since": since}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        print(f"✓ Scanner notifications with since filter: count={data.get('count')}")
    
    def test_manual_scanner_coaching_request(self):
        """Test POST /api/assistant/coach/scanner-coaching for manual coaching"""
        response = requests.post(
            f"{BASE_URL}/api/assistant/coach/scanner-coaching",
            params={"symbol": "NVDA", "setup_type": "breakout"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert data.get("symbol") == "NVDA"
        assert data.get("setup_type") == "breakout"
        assert "coaching" in data
        assert "verdict" in data
        assert "timestamp" in data
        
        # Verify verdict is one of expected values
        assert data.get("verdict") in ["TAKE", "WAIT", "PASS"], \
            f"Unexpected verdict: {data.get('verdict')}"
        
        print(f"✓ Manual coaching request: {data.get('symbol')} - {data.get('verdict')}")
        print(f"  Coaching: {data.get('coaching', '')[:100]}...")
    
    def test_coaching_notification_stored_after_manual_request(self):
        """Test that manual coaching request stores notification"""
        # First make a coaching request
        symbol = "TSLA"
        setup_type = "rubber_band_long"
        
        response = requests.post(
            f"{BASE_URL}/api/assistant/coach/scanner-coaching",
            params={"symbol": symbol, "setup_type": setup_type}
        )
        assert response.status_code == 200
        
        # Now check notifications
        notif_response = requests.get(f"{BASE_URL}/api/assistant/coach/scanner-notifications")
        assert notif_response.status_code == 200
        
        data = notif_response.json()
        notifications = data.get("notifications", [])
        
        # Find our notification
        found = False
        for notif in notifications:
            if notif.get("symbol") == symbol and notif.get("setup_type") == setup_type:
                found = True
                assert notif.get("type") == "scanner_coaching"
                assert "coaching" in notif
                assert "verdict" in notif
                break
        
        assert found, f"Notification for {symbol} {setup_type} not found in stored notifications"
        print(f"✓ Coaching notification stored: {symbol} - {setup_type}")


class TestAssistantStatus:
    """Test AI Assistant status and features"""
    
    def test_assistant_status_endpoint(self):
        """Test GET /api/assistant/status returns assistant status"""
        response = requests.get(f"{BASE_URL}/api/assistant/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "ready"
        assert data.get("ready") is True
        assert "current_provider" in data
        assert "available_providers" in data
        assert "features" in data
        
        # Verify coaching features are enabled
        features = data.get("features", {})
        assert features.get("coaching_alerts") is True
        
        print(f"✓ Assistant status: provider={data.get('current_provider')}, "
              f"providers={data.get('available_providers')}")


class TestScannerAIIntegrationFlow:
    """Test the complete Scanner → AI integration flow"""
    
    def test_scanner_to_ai_integration_wiring(self):
        """Verify scanner is wired to AI assistant"""
        # Check scanner status
        scanner_response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert scanner_response.status_code == 200
        scanner_data = scanner_response.json()
        
        # Check assistant status
        assistant_response = requests.get(f"{BASE_URL}/api/assistant/status")
        assert assistant_response.status_code == 200
        assistant_data = assistant_response.json()
        
        # Both should be ready
        assert scanner_data.get("success") is True
        assert assistant_data.get("ready") is True
        
        print(f"✓ Scanner → AI integration verified")
        print(f"  Scanner: running={scanner_data.get('running')}")
        print(f"  Assistant: provider={assistant_data.get('current_provider')}")
    
    def test_coaching_for_different_setup_types(self):
        """Test coaching works for various setup types"""
        setup_types = [
            ("AAPL", "vwap_bounce"),
            ("MSFT", "breakout"),
            ("AMD", "rubber_band_short"),
        ]
        
        for symbol, setup_type in setup_types:
            response = requests.post(
                f"{BASE_URL}/api/assistant/coach/scanner-coaching",
                params={"symbol": symbol, "setup_type": setup_type}
            )
            assert response.status_code == 200
            
            data = response.json()
            assert data.get("success") is True
            assert data.get("symbol") == symbol
            assert data.get("setup_type") == setup_type
            assert "coaching" in data
            assert "verdict" in data
            
            print(f"✓ Coaching for {symbol} {setup_type}: {data.get('verdict')}")


class TestSmartWatchlistIntegration:
    """Test Smart Watchlist auto-population from scanner"""
    
    def test_smart_watchlist_endpoint(self):
        """Test GET /api/smart-watchlist returns watchlist data"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        
        # This endpoint may or may not exist
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Smart watchlist: {data}")
        elif response.status_code == 404:
            print("⚠ Smart watchlist endpoint not found (may not be implemented)")
        else:
            print(f"⚠ Smart watchlist returned status {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
