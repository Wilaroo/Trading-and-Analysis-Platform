"""
Trading Platform API Tests - Iteration 38
Tests for positions, AI assistant, trading bot, and core features.
"""
import pytest
import requests
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://sentcom-regime.preview.emergentagent.com"


class TestHealthAndStatus:
    """Basic health and status checks"""
    
    def test_health_endpoint(self):
        """Test API health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"✅ Health check passed: {data}")

    def test_llm_status(self):
        """Test LLM provider status endpoint"""
        response = requests.get(f"{BASE_URL}/api/llm/status")
        assert response.status_code == 200
        data = response.json()
        assert "primary_provider" in data
        assert "providers" in data
        print(f"✅ LLM status: primary={data['primary_provider']}")


class TestAlpacaPositions:
    """Test Alpaca positions API - critical for trading platform"""
    
    def test_trading_bot_positions(self):
        """Test trading bot positions endpoint returns Alpaca positions"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/positions")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "positions" in data
        positions = data["positions"]
        
        # Verify we have the expected positions (MSFT, NVDA)
        symbols = [p["symbol"] for p in positions]
        print(f"✅ Positions found: {symbols}")
        
        # Verify position structure
        for pos in positions:
            assert "symbol" in pos
            assert "qty" in pos
            assert "current_price" in pos
            assert "unrealized_pnl" in pos
        
        # Verify specific positions
        assert "MSFT" in symbols, "MSFT position not found"
        assert "NVDA" in symbols, "NVDA position not found"
        
        # Find MSFT and verify structure
        msft = next(p for p in positions if p["symbol"] == "MSFT")
        assert msft["qty"] > 0, "MSFT should have positive quantity"
        print(f"✅ MSFT: {msft['qty']} shares @ ${msft['avg_entry_price']:.2f}")
        
        nvda = next(p for p in positions if p["symbol"] == "NVDA")
        assert nvda["qty"] > 0, "NVDA should have positive quantity"
        print(f"✅ NVDA: {nvda['qty']} shares @ ${nvda['avg_entry_price']:.2f}")


class TestTradingBot:
    """Test trading bot status and configuration"""
    
    def test_bot_status(self):
        """Test trading bot status endpoint"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "running" in data
        assert "mode" in data
        assert "risk_params" in data
        print(f"✅ Bot status: running={data['running']}, mode={data['mode']}")

    def test_bot_trades(self):
        """Test bot trades all endpoint"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "pending" in data
        assert "open" in data
        assert "closed" in data
        print(f"✅ Bot trades: pending={len(data['pending'])}, open={len(data['open'])}, closed={len(data['closed'])}")


class TestScannerAndAlerts:
    """Test scanner and alerts functionality"""
    
    def test_live_scanner_alerts(self):
        """Test live scanner alerts endpoint"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "alerts" in data
        alerts = data["alerts"]
        print(f"✅ Scanner alerts: {len(alerts)} active")
        
        # Verify alert structure if we have alerts
        if alerts:
            alert = alerts[0]
            assert "symbol" in alert
            assert "setup_type" in alert
            assert "direction" in alert
            print(f"  Sample alert: {alert['symbol']} - {alert['setup_type']} ({alert['direction']})")

    def test_live_scanner_status(self):
        """Test live scanner status"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        print(f"✅ Scanner status: {data}")


class TestMarketIntel:
    """Test Market Intel service"""
    
    def test_market_intel_current(self):
        """Test current market intel endpoint"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        assert response.status_code == 200
        data = response.json()
        # May or may not have a report, but should return successfully
        print(f"✅ Market intel current: has_report={data.get('has_report', False)}")

    def test_market_intel_reports(self):
        """Test market intel reports list"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        assert response.status_code == 200
        data = response.json()
        print(f"✅ Market intel reports endpoint OK")


class TestDashboardInit:
    """Test dashboard initialization batch endpoint"""
    
    def test_dashboard_init(self):
        """Test dashboard batch init endpoint"""
        response = requests.get(f"{BASE_URL}/api/dashboard/init")
        assert response.status_code == 200
        data = response.json()
        
        # Should contain multiple data sources
        print(f"✅ Dashboard init keys: {list(data.keys())}")


class TestResearchBudget:
    """Test Tavily research budget"""
    
    def test_research_budget(self):
        """Test research budget endpoint"""
        response = requests.get(f"{BASE_URL}/api/research/budget")
        assert response.status_code == 200
        data = response.json()
        assert "credits_used" in data
        assert "credits_remaining" in data
        print(f"✅ Research budget: {data['credits_used']}/{data['monthly_limit']} credits used ({data['usage_percent']}%)")


class TestSmartWatchlist:
    """Test smart watchlist"""
    
    def test_smart_watchlist(self):
        """Test smart watchlist endpoint"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        assert response.status_code == 200
        data = response.json()
        print(f"✅ Smart watchlist endpoint OK")


class TestEarningsCalendar:
    """Test earnings calendar"""
    
    def test_earnings_calendar(self):
        """Test earnings calendar endpoint"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar")
        assert response.status_code == 200
        data = response.json()
        assert "calendar" in data
        print(f"✅ Earnings calendar: {len(data.get('calendar', []))} events")


class TestSystemMonitor:
    """Test system monitoring"""
    
    def test_system_monitor(self):
        """Test system monitor endpoint"""
        response = requests.get(f"{BASE_URL}/api/system/monitor")
        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data
        print(f"✅ System status: {data.get('overall_status')}")


class TestCoachingNotifications:
    """Test AI coaching notifications"""
    
    def test_coaching_notifications(self):
        """Test coaching scanner notifications endpoint"""
        response = requests.get(f"{BASE_URL}/api/assistant/coach/scanner-notifications")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        notifications = data.get("notifications", [])
        print(f"✅ Coaching notifications: {len(notifications)} notifications")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
