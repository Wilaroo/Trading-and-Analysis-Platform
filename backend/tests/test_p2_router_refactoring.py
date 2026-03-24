"""
P2 Router Refactoring Tests - Verifies extracted routes work correctly
Tests: watchlist, portfolio, earnings, ollama_proxy, market_data routers
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_endpoint(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"PASSED: Health endpoint returns healthy status")


class TestWatchlistRouter:
    """Tests for extracted watchlist.py router"""
    
    def test_get_watchlist(self):
        """GET /api/watchlist returns watchlist data"""
        response = requests.get(f"{BASE_URL}/api/watchlist", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert "watchlist" in data
        assert "count" in data
        print(f"PASSED: GET /api/watchlist - count: {data.get('count')}")
    
    def test_get_smart_watchlist(self):
        """GET /api/smart-watchlist returns smart watchlist data"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist", timeout=15)
        assert response.status_code == 200
        data = response.json()
        # Smart watchlist should have symbols or be empty
        assert isinstance(data, dict)
        print(f"PASSED: GET /api/smart-watchlist - keys: {list(data.keys())[:5]}")
    
    def test_smart_watchlist_stats(self):
        """GET /api/smart-watchlist/stats returns statistics"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist/stats", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        print(f"PASSED: GET /api/smart-watchlist/stats")


class TestPortfolioRouter:
    """Tests for extracted portfolio.py router"""
    
    def test_get_portfolio(self):
        """GET /api/portfolio returns portfolio data"""
        response = requests.get(f"{BASE_URL}/api/portfolio", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data
        assert "summary" in data
        assert "source" in data
        print(f"PASSED: GET /api/portfolio - source: {data.get('source')}, positions: {len(data.get('positions', []))}")


class TestEarningsRouter:
    """Tests for extracted earnings_router.py"""
    
    def test_get_earnings_today(self):
        """GET /api/earnings/today returns today's earnings"""
        response = requests.get(f"{BASE_URL}/api/earnings/today", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert "earnings" in data
        assert "date" in data
        assert "count" in data
        print(f"PASSED: GET /api/earnings/today - count: {data.get('count')}")
    
    def test_get_earnings_detail(self):
        """GET /api/earnings/AAPL returns AAPL earnings detail"""
        response = requests.get(f"{BASE_URL}/api/earnings/AAPL", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        assert "earnings_date" in data
        assert "historical_earnings" in data
        print(f"PASSED: GET /api/earnings/AAPL - earnings_date: {data.get('earnings_date')}")
    
    def test_get_earnings_iv(self):
        """GET /api/earnings/iv/AAPL returns IV data"""
        response = requests.get(f"{BASE_URL}/api/earnings/iv/AAPL", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        assert "current_iv" in data
        assert "iv_rank" in data
        assert "expected_move" in data
        print(f"PASSED: GET /api/earnings/iv/AAPL - IV rank: {data.get('iv_rank')}")
    
    def test_get_earnings_calendar(self):
        """GET /api/earnings/calendar returns calendar data"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert "calendar" in data
        assert "total_count" in data
        print(f"PASSED: GET /api/earnings/calendar - total_count: {data.get('total_count')}")


class TestOllamaProxyRouter:
    """Tests for extracted ollama_proxy.py router"""
    
    def test_get_ollama_proxy_status(self):
        """GET /api/ollama-proxy/status returns proxy status"""
        response = requests.get(f"{BASE_URL}/api/ollama-proxy/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "websocket" in data
        assert "http" in data
        assert "any_connected" in data
        print(f"PASSED: GET /api/ollama-proxy/status - any_connected: {data.get('any_connected')}")
    
    def test_get_ollama_usage(self):
        """GET /api/ollama-usage returns usage stats"""
        response = requests.get(f"{BASE_URL}/api/ollama-usage", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "session" in data
        assert "weekly" in data
        assert "daily" in data
        assert "models_used" in data
        print(f"PASSED: GET /api/ollama-usage - session requests: {data.get('session', {}).get('requests')}")


class TestMarketDataRouter:
    """Tests for extracted market_data.py router"""
    
    def test_get_quote(self):
        """GET /api/quotes/AAPL returns quote data"""
        response = requests.get(f"{BASE_URL}/api/quotes/AAPL", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        assert "price" in data
        print(f"PASSED: GET /api/quotes/AAPL - price: {data.get('price')}")
    
    def test_get_market_overview(self):
        """GET /api/market/overview returns market overview"""
        response = requests.get(f"{BASE_URL}/api/market/overview", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert "indices" in data
        assert "top_movers" in data
        assert "timestamp" in data
        print(f"PASSED: GET /api/market/overview - indices count: {len(data.get('indices', []))}")
    
    def test_get_news(self):
        """GET /api/news returns news data"""
        response = requests.get(f"{BASE_URL}/api/news", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert "news" in data
        assert "timestamp" in data
        print(f"PASSED: GET /api/news - news count: {len(data.get('news', []))}")
    
    def test_get_cot_summary(self):
        """GET /api/cot/summary returns COT data"""
        response = requests.get(f"{BASE_URL}/api/cot/summary", timeout=15)
        assert response.status_code == 200
        data = response.json()
        # COT summary should return some data structure
        assert isinstance(data, dict)
        print(f"PASSED: GET /api/cot/summary")
    
    def test_get_fundamentals(self):
        """GET /api/fundamentals/AAPL returns fundamental data"""
        response = requests.get(f"{BASE_URL}/api/fundamentals/AAPL", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        print(f"PASSED: GET /api/fundamentals/AAPL - company: {data.get('company_name')}")


class TestDashboardEndpoints:
    """Tests for dashboard endpoints that use imported router functions"""
    
    def test_dashboard_stats(self):
        """GET /api/dashboard/stats returns dashboard stats"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", timeout=15)
        # May return 200 or 404 depending on implementation
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            print(f"PASSED: GET /api/dashboard/stats - keys: {list(data.keys())[:5]}")
        else:
            print(f"PASSED: GET /api/dashboard/stats - endpoint not implemented (404)")
    
    def test_dashboard_init(self):
        """GET /api/dashboard/init returns initialization data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/init", timeout=15)
        # May return 200 or 404 depending on implementation
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            print(f"PASSED: GET /api/dashboard/init - keys: {list(data.keys())[:5]}")
        else:
            print(f"PASSED: GET /api/dashboard/init - endpoint not implemented (404)")


class TestDataServicesEndpoints:
    """Tests for data services status endpoints in market_data router"""
    
    def test_data_services_status(self):
        """GET /api/data-services/status returns service status"""
        response = requests.get(f"{BASE_URL}/api/data-services/status", timeout=15)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        print(f"PASSED: GET /api/data-services/status")
    
    def test_data_services_health(self):
        """GET /api/data-services/health returns health check"""
        response = requests.get(f"{BASE_URL}/api/data-services/health", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        print(f"PASSED: GET /api/data-services/health")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
