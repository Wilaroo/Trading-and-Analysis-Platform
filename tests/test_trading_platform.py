"""
TradeCommand Trading Platform - Backend API Tests
Tests for: Strategies, Scanner, Quotes, Fundamentals, Insider Trading, COT Data, Alerts
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://smarttrade-181.preview.emergentagent.com')

class TestHealthAndBasics:
    """Health check and basic API tests"""
    
    def test_health_endpoint(self):
        """Test health endpoint returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        print(f"✓ Health check passed: {data['status']}")

class TestStrategies:
    """Test all 50 trading strategies"""
    
    def test_get_all_strategies(self):
        """Test fetching all 50 strategies"""
        response = requests.get(f"{BASE_URL}/api/strategies")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 50
        assert len(data["strategies"]) == 50
        print(f"✓ All strategies loaded: {data['count']} strategies")
    
    def test_intraday_strategies(self):
        """Test intraday strategies (INT-*) - should be 20"""
        response = requests.get(f"{BASE_URL}/api/strategies", params={"category": "intraday"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 20
        # Verify all have INT- prefix
        for strategy in data["strategies"]:
            assert strategy["id"].startswith("INT-")
            assert strategy["category"] == "intraday"
        print(f"✓ Intraday strategies: {data['count']} (all INT-* prefixed)")
    
    def test_swing_strategies(self):
        """Test swing strategies (SWG-*) - should be 15"""
        response = requests.get(f"{BASE_URL}/api/strategies", params={"category": "swing"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 15
        for strategy in data["strategies"]:
            assert strategy["id"].startswith("SWG-")
            assert strategy["category"] == "swing"
        print(f"✓ Swing strategies: {data['count']} (all SWG-* prefixed)")
    
    def test_investment_strategies(self):
        """Test investment strategies (INV-*) - should be 15"""
        response = requests.get(f"{BASE_URL}/api/strategies", params={"category": "investment"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 15
        for strategy in data["strategies"]:
            assert strategy["id"].startswith("INV-")
            assert strategy["category"] == "investment"
        print(f"✓ Investment strategies: {data['count']} (all INV-* prefixed)")
    
    def test_strategy_details_structure(self):
        """Test strategy has detailed criteria"""
        response = requests.get(f"{BASE_URL}/api/strategies/INT-01")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "INT-01"
        assert data["name"] == "Trend Momentum Continuation"
        assert "criteria" in data
        assert len(data["criteria"]) >= 3  # Should have multiple criteria
        assert "indicators" in data
        assert "timeframe" in data
        print(f"✓ Strategy INT-01 has {len(data['criteria'])} criteria: {data['criteria']}")

class TestQuotes:
    """Test real-time quote endpoints"""
    
    def test_single_quote(self):
        """Test fetching single stock quote"""
        response = requests.get(f"{BASE_URL}/api/quotes/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "price" in data
        assert "change_percent" in data
        assert "volume" in data
        assert "high" in data
        assert "low" in data
        print(f"✓ AAPL quote: ${data['price']} ({data['change_percent']:+.2f}%)")
    
    def test_batch_quotes(self):
        """Test fetching multiple quotes"""
        symbols = ["AAPL", "MSFT", "GOOGL"]
        response = requests.post(f"{BASE_URL}/api/quotes/batch", json=symbols)
        assert response.status_code == 200
        data = response.json()
        assert "quotes" in data
        assert len(data["quotes"]) >= 1  # At least some quotes returned
        print(f"✓ Batch quotes returned: {len(data['quotes'])} quotes")
    
    def test_market_overview(self):
        """Test market overview endpoint"""
        response = requests.get(f"{BASE_URL}/api/market/overview")
        assert response.status_code == 200
        data = response.json()
        assert "indices" in data
        assert "top_movers" in data
        print(f"✓ Market overview: {len(data['indices'])} indices, {len(data['top_movers'])} movers")

class TestScanner:
    """Test strategy scanner with detailed criteria matching"""
    
    def test_scanner_presets(self):
        """Test scanner presets endpoint"""
        response = requests.get(f"{BASE_URL}/api/scanner/presets")
        assert response.status_code == 200
        data = response.json()
        assert "presets" in data
        print(f"✓ Scanner presets: {len(data['presets'])} presets available")
    
    def test_scanner_scan_with_results(self):
        """Test scanner returns RVOL, Gap%, Daily Range, VWAP position"""
        symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]
        response = requests.post(
            f"{BASE_URL}/api/scanner/scan",
            json=symbols,
            params={"min_score": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        
        # Check result structure includes new fields
        if len(data["results"]) > 0:
            result = data["results"][0]
            assert "symbol" in result
            assert "score" in result
            assert "matched_strategies" in result
            assert "rvol" in result  # Relative Volume
            assert "gap_percent" in result  # Gap %
            assert "daily_range" in result  # Daily Range
            assert "above_vwap" in result  # VWAP position
            assert "strategy_details" in result  # Detailed strategy matches
            
            print(f"✓ Scanner result for {result['symbol']}:")
            print(f"  - Score: {result['score']}")
            print(f"  - RVOL: {result['rvol']:.2f}x")
            print(f"  - Gap%: {result['gap_percent']:.2f}%")
            print(f"  - Daily Range: {result['daily_range']:.2f}%")
            print(f"  - VWAP: {'Above' if result['above_vwap'] else 'Below'}")
            print(f"  - Matched strategies: {len(result['matched_strategies'])}")
        else:
            print("✓ Scanner returned 0 results (no matches above threshold)")
    
    def test_scanner_strategy_details(self):
        """Test scanner returns detailed strategy criteria matching"""
        symbols = ["AAPL", "MSFT", "NVDA"]
        response = requests.post(
            f"{BASE_URL}/api/scanner/scan",
            json=symbols,
            params={"min_score": 5}  # Low threshold to get results
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data["results"]) > 0:
            result = data["results"][0]
            if result.get("strategy_details") and len(result["strategy_details"]) > 0:
                detail = result["strategy_details"][0]
                assert "id" in detail
                assert "name" in detail
                assert "criteria_met" in detail
                assert "total" in detail
                assert "confidence" in detail
                print(f"✓ Strategy detail for {detail['id']}: {detail['criteria_met']}/{detail['total']} criteria met ({detail['confidence']:.0f}% confidence)")
            else:
                print("✓ Scanner returned results but no strategy details (low match)")
        else:
            print("✓ Scanner returned 0 results")
    
    def test_scanner_category_filter(self):
        """Test scanner with category filter"""
        symbols = ["AAPL", "MSFT"]
        response = requests.post(
            f"{BASE_URL}/api/scanner/scan",
            json=symbols,
            params={"category": "intraday", "min_score": 5}
        )
        assert response.status_code == 200
        data = response.json()
        
        # If results, all matched strategies should be INT-*
        if len(data["results"]) > 0:
            for result in data["results"]:
                for strategy_id in result.get("matched_strategies", []):
                    assert strategy_id.startswith("INT-"), f"Expected INT-* strategy, got {strategy_id}"
            print(f"✓ Category filter working: only INT-* strategies matched")
        else:
            print("✓ Category filter test passed (no matches)")

class TestFundamentals:
    """Test fundamental data endpoints"""
    
    def test_fundamentals_endpoint(self):
        """Test fundamentals returns complete data"""
        response = requests.get(f"{BASE_URL}/api/fundamentals/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        
        # Check key fundamental fields
        expected_fields = ["market_cap", "pe_ratio", "sector", "industry"]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✓ Fundamentals for AAPL:")
        print(f"  - Market Cap: ${data.get('market_cap', 0)/1e9:.2f}B")
        print(f"  - P/E Ratio: {data.get('pe_ratio', 'N/A')}")
        print(f"  - Sector: {data.get('sector', 'N/A')}")

class TestInsiderTrading:
    """Test insider trading endpoints"""
    
    def test_insider_trades_by_symbol(self):
        """Test insider trades for specific symbol"""
        response = requests.get(f"{BASE_URL}/api/insider/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "trades" in data
        assert "summary" in data
        
        # Check summary structure
        summary = data["summary"]
        assert "total_buys" in summary
        assert "total_sells" in summary
        assert "signal" in summary
        
        print(f"✓ Insider trades for AAPL:")
        print(f"  - Total trades: {len(data['trades'])}")
        print(f"  - Signal: {summary['signal']}")
        print(f"  - Net activity: ${summary.get('net_activity', 0)/1e6:.2f}M")
    
    def test_unusual_insider_activity(self):
        """Test unusual insider activity endpoint"""
        response = requests.get(f"{BASE_URL}/api/insider/unusual")
        assert response.status_code == 200
        data = response.json()
        assert "all_activity" in data
        print(f"✓ Unusual insider activity: {len(data['all_activity'])} stocks analyzed")

class TestCOTData:
    """Test Commitment of Traders data endpoints"""
    
    def test_cot_summary(self):
        """Test COT summary endpoint"""
        response = requests.get(f"{BASE_URL}/api/cot/summary")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        print(f"✓ COT summary: {len(data['summary'])} markets")
    
    def test_cot_by_market(self):
        """Test COT data for specific market"""
        response = requests.get(f"{BASE_URL}/api/cot/ES")
        assert response.status_code == 200
        data = response.json()
        assert data["market"] == "ES"
        assert "data" in data
        
        if len(data["data"]) > 0:
            cot = data["data"][0]
            assert "commercial_long" in cot
            assert "commercial_short" in cot
            assert "commercial_net" in cot
            assert "non_commercial_long" in cot
            assert "non_commercial_short" in cot
            print(f"✓ COT data for ES: {len(data['data'])} weeks of data")
            print(f"  - Commercial Net: {cot['commercial_net']}")
            print(f"  - Speculator Net: {cot['non_commercial_net']}")

class TestAlerts:
    """Test alerts endpoints"""
    
    def test_generate_alerts(self):
        """Test alert generation"""
        response = requests.post(f"{BASE_URL}/api/alerts/generate")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        print(f"✓ Generated {len(data['alerts'])} alerts")
    
    def test_get_alerts(self):
        """Test getting alerts"""
        response = requests.get(f"{BASE_URL}/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        print(f"✓ Retrieved {len(data['alerts'])} alerts")

class TestDashboard:
    """Test dashboard endpoints"""
    
    def test_dashboard_stats(self):
        """Test dashboard stats endpoint"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert "portfolio_value" in data
        assert "strategies_count" in data
        assert data["strategies_count"] == 50
        print(f"✓ Dashboard stats: {data['strategies_count']} strategies, ${data['portfolio_value']} portfolio")

class TestNews:
    """Test news endpoints"""
    
    def test_market_news(self):
        """Test market news endpoint"""
        response = requests.get(f"{BASE_URL}/api/news")
        assert response.status_code == 200
        data = response.json()
        assert "news" in data
        print(f"✓ Market news: {len(data['news'])} articles")

class TestHistoricalData:
    """Test historical data endpoints"""
    
    def test_historical_data(self):
        """Test historical price data"""
        response = requests.get(f"{BASE_URL}/api/historical/AAPL", params={"period": "1mo"})
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "data" in data
        print(f"✓ Historical data for AAPL: {len(data['data'])} data points")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
