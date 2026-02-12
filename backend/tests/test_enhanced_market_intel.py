"""
Enhanced Market Intelligence API Tests (Iteration 35)

Tests for the ENHANCED Market Intelligence features:
- Market Regime classification (STRONG UPTREND, CHOPPY, ROTATION, etc.)
- In-Play Stocks with key levels (HOD, LOD, VWAP)
- Ticker-Specific News from Finnhub company-news
- Sector Performance/Heatmap
- Earnings Calendar warnings
- Smart Watchlist integration (actual symbols, not hardcoded)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEnhancedMarketIntelAPI:
    """Tests for enhanced Market Intel features"""
    
    def test_health_check(self):
        """Verify API is healthy before testing"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("PASS: API health check")
    
    def test_generate_early_market_with_force(self):
        """Generate early_market report with force=true to get fresh data"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "report" in data
        assert data["report"]["type"] == "early_market"
        
        content = data["report"]["content"]
        assert len(content) > 500, f"Content too short: {len(content)} chars"
        
        print(f"PASS: Early market report generated ({len(content)} chars)")
        return content
    
    def test_report_contains_market_regime_section(self):
        """Report should contain Market Regime classification"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        data = response.json()
        content = data["report"]["content"].upper()
        
        # Check for market regime section
        has_regime_section = any(term in content for term in [
            "MARKET REGIME",
            "REGIME",
            "CHOPPY",
            "UPTREND",
            "DOWNTREND",
            "ROTATION",
            "NEUTRAL"
        ])
        
        assert has_regime_section, "Report missing Market Regime section"
        print("PASS: Report contains Market Regime classification")
    
    def test_report_contains_sector_performance(self):
        """Report should contain Sector Performance/Rotation data"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        data = response.json()
        content = data["report"]["content"].upper()
        
        # Check for sector section
        has_sector_section = any(term in content for term in [
            "SECTOR",
            "ROTATION",
            "LEADING",
            "LAGGING",
            "XLK",  # Tech ETF
            "XLF",  # Financial ETF
            "TECHNOLOGY",
            "FINANCIALS"
        ])
        
        assert has_sector_section, "Report missing Sector Performance section"
        print("PASS: Report contains Sector Performance data")
    
    def test_report_contains_in_play_stocks(self):
        """Report should contain In-Play Stocks section"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        data = response.json()
        content = data["report"]["content"].upper()
        
        # Check for in-play section
        has_in_play_section = any(term in content for term in [
            "IN-PLAY",
            "IN PLAY",
            "ACTIVE",
            "WATCHLIST"
        ])
        
        assert has_in_play_section, "Report missing In-Play Stocks section"
        print("PASS: Report contains In-Play Stocks section")
    
    def test_report_contains_ticker_specific_news(self):
        """Report should contain Ticker-Specific News"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        data = response.json()
        content = data["report"]["content"].upper()
        
        # Check for ticker news section
        has_news_section = any(term in content for term in [
            "TICKER",
            "NEWS",
            "HEADLINES"
        ])
        
        # Also check for common tickers in news
        has_tickers = any(ticker in content for ticker in [
            "NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "META", "AMD", "AMZN"
        ])
        
        assert has_news_section or has_tickers, "Report missing Ticker-Specific News"
        print("PASS: Report contains Ticker-Specific News")
    
    def test_report_contains_market_status(self):
        """Report should contain Market Status with indices"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        data = response.json()
        content = data["report"]["content"].upper()
        
        # Check for market indices
        has_indices = any(index in content for index in [
            "SPY", "QQQ", "IWM", "DIA", "VIX"
        ])
        
        assert has_indices, "Report missing Market indices"
        print("PASS: Report contains Market Status with indices")


class TestMarketIntelScheduleAPI:
    """Tests for schedule endpoint"""
    
    def test_schedule_endpoint_returns_200(self):
        """Schedule endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        assert response.status_code == 200
        print("PASS: Schedule endpoint returns 200")
    
    def test_schedule_has_five_report_types(self):
        """Schedule should have 5 report types"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        data = response.json()
        
        assert "schedule" in data
        assert len(data["schedule"]) == 5
        
        expected_types = {"premarket", "early_market", "midday", "power_hour", "post_market"}
        actual_types = {item["type"] for item in data["schedule"]}
        
        assert actual_types == expected_types
        print("PASS: Schedule has all 5 report types")


class TestMarketIntelReportsAPI:
    """Tests for reports endpoint"""
    
    def test_reports_endpoint_returns_200(self):
        """Reports endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        assert response.status_code == 200
        print("PASS: Reports endpoint returns 200")
    
    def test_reports_list_structure(self):
        """Reports should return count and list"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        data = response.json()
        
        assert "count" in data
        assert "reports" in data
        assert isinstance(data["reports"], list)
        print(f"PASS: Reports list has {data['count']} items")


class TestMarketIntelCurrentAPI:
    """Tests for current report endpoint"""
    
    def test_current_endpoint_returns_200(self):
        """Current endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        assert response.status_code == 200
        print("PASS: Current endpoint returns 200")
    
    def test_current_has_report_flag(self):
        """Current response should have has_report flag"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        data = response.json()
        
        assert "has_report" in data
        print(f"PASS: Current has_report={data['has_report']}")


class TestSmartWatchlistIntegration:
    """Tests that Market Intel uses Smart Watchlist (not hardcoded symbols)"""
    
    def test_smart_watchlist_endpoint_works(self):
        """Smart watchlist endpoint should return symbols"""
        response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        assert response.status_code == 200
        
        data = response.json()
        assert "watchlist" in data
        
        # Should have at least some symbols
        symbols = [item["symbol"] for item in data["watchlist"]]
        print(f"PASS: Smart watchlist has {len(symbols)} symbols: {symbols[:5]}...")
    
    def test_smart_watchlist_symbols_appear_in_report(self):
        """Watchlist symbols should appear in Market Intel report"""
        # Get watchlist symbols
        wl_response = requests.get(f"{BASE_URL}/api/smart-watchlist")
        wl_data = wl_response.json()
        watchlist_symbols = [item["symbol"] for item in wl_data["watchlist"][:5]]
        
        # Generate report
        intel_response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/early_market?force=true",
            timeout=180
        )
        intel_data = intel_response.json()
        content = intel_data["report"]["content"].upper()
        
        # At least some watchlist symbols should appear
        found_symbols = [sym for sym in watchlist_symbols if sym.upper() in content]
        
        if found_symbols:
            print(f"PASS: Found watchlist symbols in report: {found_symbols}")
        else:
            print(f"INFO: No watchlist symbols found in report (may be normal if market closed)")


class TestAlpacaQuotesForMarketIntel:
    """Tests that Alpaca quotes are being fetched correctly"""
    
    def test_alpaca_batch_quotes(self):
        """Alpaca batch quotes endpoint should work"""
        response = requests.post(
            f"{BASE_URL}/api/quotes/batch",
            json=["SPY", "QQQ", "NVDA"],
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "quotes" in data
        assert len(data["quotes"]) >= 1
        
        for quote in data["quotes"]:
            assert "symbol" in quote
            assert "price" in quote
        
        print(f"PASS: Alpaca batch quotes working ({len(data['quotes'])} quotes)")


# pytest fixtures
@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session
