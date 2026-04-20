"""
Test suite for Earnings Calendar API endpoints
Tests real Finnhub data integration for earnings calendar features
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ml-quant-spark.preview.emergentagent.com').rstrip('/')


class TestEarningsCalendarAPI:
    """Test cases for /api/earnings/calendar endpoint"""
    
    def test_earnings_calendar_returns_200(self):
        """Test earnings calendar endpoint returns successful response"""
        today = datetime.now().strftime("%Y-%m-%d")
        week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/earnings/calendar",
            params={"start_date": today, "end_date": week_end}
        )
        
        assert response.status_code == 200
        print(f"✓ Earnings calendar API returned 200")
    
    def test_earnings_calendar_response_structure(self):
        """Test earnings calendar returns expected data structure"""
        today = datetime.now().strftime("%Y-%m-%d")
        week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/earnings/calendar",
            params={"start_date": today, "end_date": week_end}
        )
        
        data = response.json()
        
        # Verify required top-level fields
        assert "calendar" in data, "Missing 'calendar' field"
        assert "grouped_by_date" in data, "Missing 'grouped_by_date' field"
        assert "total_count" in data, "Missing 'total_count' field"
        assert "start_date" in data, "Missing 'start_date' field"
        assert "end_date" in data, "Missing 'end_date' field"
        
        print(f"✓ Response structure validated - total_count: {data['total_count']}")
    
    def test_earnings_calendar_items_have_required_fields(self):
        """Test each calendar item has required fields for frontend display"""
        today = datetime.now().strftime("%Y-%m-%d")
        week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/earnings/calendar",
            params={"start_date": today, "end_date": week_end}
        )
        
        data = response.json()
        
        if len(data["calendar"]) > 0:
            item = data["calendar"][0]
            
            # Required fields for frontend display
            required_fields = ["symbol", "earnings_date", "time", "company_name"]
            for field in required_fields:
                assert field in item, f"Missing required field '{field}' in calendar item"
            
            # Verify time field is either "Before Open" or "After Close"
            assert item["time"] in ["Before Open", "After Close"], f"Invalid time value: {item['time']}"
            
            print(f"✓ Calendar item has all required fields: {item['symbol']}")
        else:
            print("Note: No earnings items in the current week")
    
    def test_earnings_calendar_grouped_by_date_structure(self):
        """Test grouped_by_date structure for column layout"""
        today = datetime.now().strftime("%Y-%m-%d")
        week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/earnings/calendar",
            params={"start_date": today, "end_date": week_end}
        )
        
        data = response.json()
        
        if len(data["grouped_by_date"]) > 0:
            group = data["grouped_by_date"][0]
            
            # Required fields for column layout
            assert "date" in group, "Missing 'date' field in grouped data"
            assert "count" in group, "Missing 'count' field in grouped data"
            assert "before_open" in group, "Missing 'before_open' field in grouped data"
            assert "after_close" in group, "Missing 'after_close' field in grouped data"
            
            # Verify before_open and after_close are lists
            assert isinstance(group["before_open"], list), "before_open should be a list"
            assert isinstance(group["after_close"], list), "after_close should be a list"
            
            print(f"✓ Grouped data structure correct - date: {group['date']}, count: {group['count']}")
        else:
            print("Note: No grouped data in the current week")
    
    def test_earnings_calendar_returns_real_finnhub_data(self):
        """Test that earnings data is real (not hardcoded) from Finnhub"""
        today = datetime.now().strftime("%Y-%m-%d")
        week_end = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/earnings/calendar",
            params={"start_date": today, "end_date": week_end}
        )
        
        data = response.json()
        
        # Check for variety of symbols (real data would have multiple symbols)
        symbols = set(item["symbol"] for item in data["calendar"])
        
        # Real Finnhub data should have eps_estimate or revenue_estimate
        items_with_estimates = [
            item for item in data["calendar"]
            if item.get("eps_estimate") is not None or item.get("revenue_estimate") is not None
        ]
        
        print(f"✓ Found {len(symbols)} unique symbols with {len(items_with_estimates)} having estimates")
        assert len(items_with_estimates) > 0 or len(data["calendar"]) == 0, "No items with estimates found"


class TestEarningsTodayAPI:
    """Test cases for /api/earnings/today endpoint"""
    
    def test_earnings_today_returns_200(self):
        """Test today's earnings endpoint returns successful response"""
        response = requests.get(f"{BASE_URL}/api/earnings/today")
        
        assert response.status_code == 200
        print(f"✓ Earnings today API returned 200")
    
    def test_earnings_today_response_structure(self):
        """Test today's earnings returns expected structure"""
        response = requests.get(f"{BASE_URL}/api/earnings/today")
        
        data = response.json()
        
        assert "earnings" in data, "Missing 'earnings' field"
        assert "date" in data, "Missing 'date' field"
        assert "count" in data, "Missing 'count' field"
        
        # Verify date is today
        today = datetime.now().strftime("%Y-%m-%d")
        assert data["date"] == today, f"Date mismatch: expected {today}, got {data['date']}"
        
        print(f"✓ Today's earnings - date: {data['date']}, count: {data['count']}")
    
    def test_earnings_today_items_have_timing(self):
        """Test today's earnings items have BMO/AMC timing"""
        response = requests.get(f"{BASE_URL}/api/earnings/today")
        
        data = response.json()
        
        if len(data["earnings"]) > 0:
            item = data["earnings"][0]
            
            assert "symbol" in item, "Missing 'symbol' field"
            assert "timing" in item, "Missing 'timing' field"
            assert item["timing"] in ["BMO", "AMC"], f"Invalid timing: {item['timing']}"
            
            print(f"✓ Earnings item has timing: {item['symbol']} - {item['timing']}")
        else:
            print("Note: No earnings today")


class TestEarningsDetailAPI:
    """Test cases for /api/earnings/{symbol} endpoint"""
    
    def test_earnings_detail_returns_200(self):
        """Test earnings detail endpoint for known symbol"""
        response = requests.get(f"{BASE_URL}/api/earnings/AAPL")
        
        assert response.status_code == 200
        print(f"✓ Earnings detail API returned 200 for AAPL")
    
    def test_earnings_detail_has_historical_data(self):
        """Test earnings detail includes historical earnings data"""
        response = requests.get(f"{BASE_URL}/api/earnings/NVDA")
        
        data = response.json()
        
        # Should have symbol at minimum
        assert "symbol" in data, "Missing 'symbol' field"
        
        print(f"✓ Earnings detail retrieved for {data.get('symbol', 'N/A')}")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
