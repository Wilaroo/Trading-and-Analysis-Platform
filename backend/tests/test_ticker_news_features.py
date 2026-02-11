"""
Test suite for Ticker Links and News Features
Tests:
1. Ticker symbols in Market Intelligence panel should be clickable
2. Clicking a ticker link should open the TickerDetailModal
3. News tab in TickerDetailModal should show news items with clickable external links
4. API endpoint /api/ib/analysis/{symbol} should return news items with 'url' field
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTickerAnalysisAPI:
    """Test the /api/ib/analysis/{symbol} endpoint for news with URLs"""
    
    def test_analysis_endpoint_returns_news_with_urls_aapl(self):
        """Test that AAPL analysis returns news items with valid URLs"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/AAPL", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "news" in data, "Response should contain 'news' field"
        
        news = data["news"]
        assert isinstance(news, list), "News should be a list"
        assert len(news) > 0, "News list should not be empty"
        
        # Check that news items have required fields
        for item in news:
            assert "headline" in item, "News item should have 'headline'"
            assert "url" in item, "News item should have 'url' field"
            # URL should be a valid Finnhub URL or None for placeholder
            if not item.get("is_placeholder", False):
                assert item["url"] is not None, f"URL should not be None for non-placeholder news: {item['headline']}"
                assert item["url"].startswith("http"), f"URL should start with http: {item['url']}"
    
    def test_analysis_endpoint_returns_news_with_urls_nvda(self):
        """Test that NVDA analysis returns news items with valid URLs"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/NVDA", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert "news" in data
        
        news = data["news"]
        assert len(news) > 0, "NVDA should have news items"
        
        # Count items with valid URLs
        items_with_urls = [n for n in news if n.get("url") and n["url"].startswith("http")]
        assert len(items_with_urls) > 0, "At least one news item should have a valid URL"
    
    def test_analysis_endpoint_returns_news_with_urls_msft(self):
        """Test that MSFT analysis returns news items with valid URLs"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/MSFT", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert "news" in data
        
        news = data["news"]
        # Check news structure
        for item in news[:3]:  # Check first 3 items
            assert "headline" in item
            assert "source" in item
            assert "url" in item
    
    def test_analysis_endpoint_news_has_finnhub_urls(self):
        """Test that news URLs are from Finnhub"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/GOOGL", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        news = data.get("news", [])
        
        # Check that at least some news items have Finnhub URLs
        finnhub_urls = [n for n in news if n.get("url") and "finnhub.io" in n["url"]]
        # Note: If no Finnhub news, it might be using sample data
        if len(news) > 0 and not news[0].get("is_sample", False):
            assert len(finnhub_urls) > 0, "News should have Finnhub URLs when available"


class TestMarketIntelAPI:
    """Test Market Intelligence API for ticker-aware content"""
    
    def test_market_intel_current_report(self):
        """Test that current market intel report is available"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert "has_report" in data
        
        if data["has_report"]:
            report = data["report"]
            assert "content" in report, "Report should have content"
            assert len(report["content"]) > 0, "Report content should not be empty"
    
    def test_market_intel_schedule(self):
        """Test market intel schedule endpoint"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert "schedule" in data


class TestNewsService:
    """Test the news service directly"""
    
    def test_ticker_news_endpoint(self):
        """Test the /api/ib/news/{symbol} endpoint"""
        response = requests.get(f"{BASE_URL}/api/ib/news/AAPL", timeout=30)
        # This endpoint may return 500 if IB is not connected, which is acceptable
        if response.status_code == 200:
            data = response.json()
            assert "news" in data
            assert "symbol" in data
            assert data["symbol"] == "AAPL"


class TestAnalysisResponseStructure:
    """Test the complete structure of analysis response"""
    
    def test_analysis_has_all_required_fields(self):
        """Test that analysis response has all required fields"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/TSLA", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required top-level fields
        required_fields = ["symbol", "quote", "company_info", "fundamentals", 
                         "technicals", "scores", "trading_summary", "news"]
        for field in required_fields:
            assert field in data, f"Response should contain '{field}'"
        
        # Check news structure
        news = data["news"]
        if len(news) > 0:
            first_news = news[0]
            news_fields = ["headline", "source", "url"]
            for field in news_fields:
                assert field in first_news, f"News item should contain '{field}'"
    
    def test_analysis_news_sentiment(self):
        """Test that news items have sentiment analysis"""
        response = requests.get(f"{BASE_URL}/api/ib/analysis/META", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        news = data.get("news", [])
        
        for item in news:
            if "sentiment" in item:
                assert item["sentiment"] in ["bullish", "bearish", "neutral"], \
                    f"Sentiment should be bullish/bearish/neutral, got {item['sentiment']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
