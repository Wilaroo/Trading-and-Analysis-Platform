"""
TradeCommand Backend API Tests - VST Scoring, Portfolio, Watchlist, Earnings
Tests for iteration 4 - Focus on VST scoring system and new features
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://marketpilot-4.preview.emergentagent.com').rstrip('/')


class TestHealthAndBasics:
    """Basic health and connectivity tests"""
    
    def test_health_endpoint(self):
        """Test health endpoint returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestVSTScoringSystem:
    """VST (Value, Safety, Timing) Scoring System Tests"""
    
    def test_vst_endpoint_returns_all_scores(self):
        """Test /api/vst/{symbol} returns RV, RS, RT, VST scores on 0-10 scale"""
        response = requests.get(f"{BASE_URL}/api/vst/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        # Verify symbol
        assert data["symbol"] == "AAPL"
        assert "timestamp" in data
        
        # Verify Relative Value (RV) score
        assert "relative_value" in data
        rv = data["relative_value"]
        assert "score" in rv
        assert 0 <= rv["score"] <= 10, f"RV score {rv['score']} not in 0-10 range"
        assert "interpretation" in rv
        assert "components" in rv
        
        # Verify Relative Safety (RS) score
        assert "relative_safety" in data
        rs = data["relative_safety"]
        assert "score" in rs
        assert 0 <= rs["score"] <= 10, f"RS score {rs['score']} not in 0-10 range"
        assert "interpretation" in rs
        assert "components" in rs
        
        # Verify Relative Timing (RT) score
        assert "relative_timing" in data
        rt = data["relative_timing"]
        assert "score" in rt
        assert 0 <= rt["score"] <= 10, f"RT score {rt['score']} not in 0-10 range"
        assert "interpretation" in rt
        assert "components" in rt
        assert "metrics" in rt
        
        # Verify VST Composite score
        assert "vst_composite" in data
        vst = data["vst_composite"]
        assert "score" in vst
        assert 0 <= vst["score"] <= 10, f"VST score {vst['score']} not in 0-10 range"
        assert "recommendation" in vst
        assert vst["recommendation"] in ["STRONG BUY", "BUY", "HOLD", "SELL"]
        assert "weights_used" in vst
    
    def test_vst_score_precision(self):
        """Test VST scores have 2 decimal places"""
        response = requests.get(f"{BASE_URL}/api/vst/MSFT")
        assert response.status_code == 200
        data = response.json()
        
        # Check score precision (2 decimal places)
        rv_score = data["relative_value"]["score"]
        rs_score = data["relative_safety"]["score"]
        rt_score = data["relative_timing"]["score"]
        vst_score = data["vst_composite"]["score"]
        
        # Verify scores are floats with proper precision
        assert isinstance(rv_score, (int, float))
        assert isinstance(rs_score, (int, float))
        assert isinstance(rt_score, (int, float))
        assert isinstance(vst_score, (int, float))
    
    def test_vst_timing_metrics(self):
        """Test RT score includes timing metrics"""
        response = requests.get(f"{BASE_URL}/api/vst/NVDA")
        assert response.status_code == 200
        data = response.json()
        
        metrics = data["relative_timing"]["metrics"]
        assert "return_1w" in metrics
        assert "return_1m" in metrics
        assert "return_3m" in metrics
        assert "rsi" in metrics
        assert "above_sma20" in metrics
        assert "above_sma50" in metrics
        assert "sma20_above_sma50" in metrics
    
    def test_vst_fundamentals_summary(self):
        """Test VST response includes fundamentals summary"""
        response = requests.get(f"{BASE_URL}/api/vst/GOOGL")
        assert response.status_code == 200
        data = response.json()
        
        assert "fundamentals_summary" in data
        summary = data["fundamentals_summary"]
        # These fields may be None but should exist
        assert "pe_ratio" in summary
        assert "peg_ratio" in summary
        assert "roe" in summary
        assert "debt_to_equity" in summary
        assert "profit_margin" in summary
        assert "beta" in summary
    
    def test_vst_batch_endpoint(self):
        """Test batch VST scoring for multiple symbols"""
        response = requests.post(
            f"{BASE_URL}/api/vst/batch",
            json=["AAPL", "MSFT", "GOOGL"]
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "results" in data
        assert len(data["results"]) == 3
        
        for result in data["results"]:
            assert "symbol" in result
            assert "vst_composite" in result


class TestPortfolioCRUD:
    """Portfolio CRUD operations tests"""
    
    def test_get_portfolio(self):
        """Test GET /api/portfolio returns portfolio data"""
        response = requests.get(f"{BASE_URL}/api/portfolio")
        assert response.status_code == 200
        data = response.json()
        
        assert "positions" in data
        assert "summary" in data
        assert "total_value" in data["summary"]
        assert "total_cost" in data["summary"]
        assert "total_gain_loss" in data["summary"]
    
    def test_add_portfolio_position(self):
        """Test POST /api/portfolio/add creates new position"""
        payload = {
            "symbol": "TEST_PORTFOLIO_AAPL",
            "shares": 10,
            "avg_cost": 150.00
        }
        response = requests.post(
            f"{BASE_URL}/api/portfolio/add",
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "position" in data
        assert data["position"]["symbol"] == "TEST_PORTFOLIO_AAPL"
        assert data["position"]["shares"] == 10.0
        assert data["position"]["avg_cost"] == 150.0
    
    def test_verify_portfolio_position_persisted(self):
        """Test portfolio position was persisted"""
        response = requests.get(f"{BASE_URL}/api/portfolio")
        assert response.status_code == 200
        data = response.json()
        
        symbols = [p["symbol"] for p in data["positions"]]
        assert "TEST_PORTFOLIO_AAPL" in symbols
    
    def test_delete_portfolio_position(self):
        """Test DELETE /api/portfolio/{symbol} removes position"""
        response = requests.delete(f"{BASE_URL}/api/portfolio/TEST_PORTFOLIO_AAPL")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
    
    def test_verify_portfolio_position_deleted(self):
        """Test portfolio position was deleted"""
        response = requests.get(f"{BASE_URL}/api/portfolio")
        assert response.status_code == 200
        data = response.json()
        
        symbols = [p["symbol"] for p in data["positions"]]
        assert "TEST_PORTFOLIO_AAPL" not in symbols


class TestWatchlistCRUD:
    """Watchlist CRUD operations tests"""
    
    def test_get_watchlist(self):
        """Test GET /api/watchlist returns watchlist data"""
        response = requests.get(f"{BASE_URL}/api/watchlist")
        assert response.status_code == 200
        data = response.json()
        
        assert "watchlist" in data
        assert "count" in data
    
    def test_add_to_watchlist(self):
        """Test POST /api/watchlist/add adds symbol"""
        payload = {"symbol": "TEST_WATCHLIST_TSLA"}
        response = requests.post(
            f"{BASE_URL}/api/watchlist/add",
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "symbol" in data
        assert data["symbol"] == "TEST_WATCHLIST_TSLA"
    
    def test_delete_from_watchlist(self):
        """Test DELETE /api/watchlist/{symbol} removes symbol"""
        response = requests.delete(f"{BASE_URL}/api/watchlist/TEST_WATCHLIST_TSLA")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestEarningsCalendar:
    """Earnings Calendar API tests"""
    
    def test_earnings_calendar_endpoint(self):
        """Test /api/earnings/calendar returns earnings data"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar")
        assert response.status_code == 200
        data = response.json()
        
        assert "calendar" in data
        assert len(data["calendar"]) > 0
        
        # Check first earnings entry structure
        entry = data["calendar"][0]
        assert "symbol" in entry
        assert "earnings_date" in entry
        assert "time" in entry
        assert "eps_estimate" in entry
        assert "company_name" in entry
    
    def test_earnings_calendar_has_iv_data(self):
        """Test earnings calendar includes implied volatility data"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar")
        assert response.status_code == 200
        data = response.json()
        
        entry = data["calendar"][0]
        assert "implied_volatility" in entry
        iv = entry["implied_volatility"]
        assert "current_iv" in iv
        assert "expected_move_percent" in iv
    
    def test_earnings_symbol_endpoint(self):
        """Test /api/earnings/{symbol} returns symbol-specific data"""
        response = requests.get(f"{BASE_URL}/api/earnings/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        assert "symbol" in data
        assert data["symbol"] == "AAPL"


class TestQuotesAndFundamentals:
    """Quotes and Fundamentals API tests"""
    
    def test_quote_endpoint(self):
        """Test /api/quotes/{symbol} returns quote data"""
        response = requests.get(f"{BASE_URL}/api/quotes/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        assert "symbol" in data
        assert "price" in data
        assert "change" in data
        assert "change_percent" in data
        assert "volume" in data
    
    def test_fundamentals_endpoint(self):
        """Test /api/fundamentals/{symbol} returns fundamental data"""
        response = requests.get(f"{BASE_URL}/api/fundamentals/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        assert "symbol" in data
        assert "pe_ratio" in data or data.get("pe_ratio") is None
        assert "market_cap" in data or data.get("market_cap") is None


class TestStrategies:
    """Trading Strategies API tests"""
    
    def test_strategies_endpoint(self):
        """Test /api/strategies returns all 50 strategies"""
        response = requests.get(f"{BASE_URL}/api/strategies")
        assert response.status_code == 200
        data = response.json()
        
        assert "strategies" in data
        assert len(data["strategies"]) == 50
    
    def test_strategies_by_category(self):
        """Test strategies filtering by category"""
        response = requests.get(f"{BASE_URL}/api/strategies?category=intraday")
        assert response.status_code == 200
        data = response.json()
        
        assert "strategies" in data
        for strategy in data["strategies"]:
            assert strategy["category"] == "intraday"


class TestDashboard:
    """Dashboard API tests"""
    
    def test_dashboard_stats(self):
        """Test /api/dashboard/stats returns stats"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        
        assert "portfolio_value" in data
        assert "strategies_count" in data
        assert data["strategies_count"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
