#!/usr/bin/env python3
"""
TradeCommand Backend API Testing
Tests all API endpoints for the trading platform
"""
import requests
import sys
import json
from datetime import datetime
from typing import Dict, List, Any

class TradeCommandAPITester:
    def __init__(self, base_url="http://localhost:8001"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.session = requests.Session()
        self.session.timeout = 30

    def log_test(self, name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"    {details}")
        
        if success:
            self.tests_passed += 1
        else:
            self.failed_tests.append({"name": name, "details": details})

    def test_endpoint(self, method: str, endpoint: str, expected_status: int = 200, 
                     data: Dict = None, params: Dict = None, test_name: str = None) -> tuple:
        """Test a single API endpoint"""
        if not test_name:
            test_name = f"{method} {endpoint}"
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data, params=params)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url, params=params)
            elif method.upper() == 'PUT':
                response = self.session.put(url, json=data, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")

            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json()
                    self.log_test(test_name, True, f"Status: {response.status_code}")
                    return True, response_data
                except json.JSONDecodeError:
                    self.log_test(test_name, True, f"Status: {response.status_code} (No JSON)")
                    return True, {}
            else:
                self.log_test(test_name, False, f"Expected {expected_status}, got {response.status_code}")
                return False, {}

        except Exception as e:
            self.log_test(test_name, False, f"Error: {str(e)}")
            return False, {}

    def test_health_endpoint(self):
        """Test health check endpoint"""
        print("\n🔍 Testing Health Endpoint...")
        success, data = self.test_endpoint('GET', '/api/health', test_name="Health Check")
        
        if success and data:
            if 'status' in data and data['status'] == 'healthy':
                self.log_test("Health Status Check", True, "Status is 'healthy'")
            else:
                self.log_test("Health Status Check", False, f"Unexpected status: {data.get('status')}")

    def test_strategies_endpoints(self):
        """Test strategy-related endpoints"""
        print("\n🔍 Testing Strategy Endpoints...")
        
        # Test get all strategies
        success, data = self.test_endpoint('GET', '/api/strategies', test_name="Get All Strategies")
        
        if success and data:
            strategies = data.get('strategies', [])
            count = data.get('count', 0)
            
            # Verify we have 50 strategies
            if count == 50:
                self.log_test("Strategy Count Check", True, f"Found {count} strategies")
            else:
                self.log_test("Strategy Count Check", False, f"Expected 50, got {count}")
            
            # Count by category
            intraday_count = len([s for s in strategies if s.get('category') == 'intraday'])
            swing_count = len([s for s in strategies if s.get('category') == 'swing'])
            investment_count = len([s for s in strategies if s.get('category') == 'investment'])
            
            # Verify category counts
            if intraday_count == 20:
                self.log_test("Intraday Strategy Count", True, f"Found {intraday_count} intraday strategies")
            else:
                self.log_test("Intraday Strategy Count", False, f"Expected 20, got {intraday_count}")
                
            if swing_count == 15:
                self.log_test("Swing Strategy Count", True, f"Found {swing_count} swing strategies")
            else:
                self.log_test("Swing Strategy Count", False, f"Expected 15, got {swing_count}")
                
            if investment_count == 15:
                self.log_test("Investment Strategy Count", True, f"Found {investment_count} investment strategies")
            else:
                self.log_test("Investment Strategy Count", False, f"Expected 15, got {investment_count}")
        
        # Test category filtering
        for category in ['intraday', 'swing', 'investment']:
            success, data = self.test_endpoint('GET', '/api/strategies', 
                                             params={'category': category}, 
                                             test_name=f"Get {category.title()} Strategies")
        
        # Test specific strategy
        success, data = self.test_endpoint('GET', '/api/strategies/INT-01', test_name="Get Specific Strategy")

    def test_scanner_endpoints(self):
        """Test scanner-related endpoints"""
        print("\n🔍 Testing Scanner Endpoints...")
        
        # Test scanner presets
        success, data = self.test_endpoint('GET', '/api/scanner/presets', test_name="Get Scanner Presets")
        
        # Test scanner scan
        scan_data = ["AAPL", "MSFT", "GOOGL"]
        success, data = self.test_endpoint('POST', '/api/scanner/scan', 
                                         data=scan_data,
                                         params={'min_score': 30},
                                         test_name="Run Scanner")

    def test_market_endpoints(self):
        """Test market data endpoints"""
        print("\n🔍 Testing Market Data Endpoints...")
        
        # Test market overview
        success, data = self.test_endpoint('GET', '/api/market/overview', test_name="Market Overview")
        
        # Test single quote
        success, data = self.test_endpoint('GET', '/api/quotes/AAPL', test_name="Single Quote")
        
        # Test batch quotes
        batch_data = ["AAPL", "MSFT", "GOOGL"]
        success, data = self.test_endpoint('POST', '/api/quotes/batch', 
                                         data=batch_data, 
                                         test_name="Batch Quotes")
        
        # Test news
        success, data = self.test_endpoint('GET', '/api/news', test_name="Market News")

    def test_watchlist_endpoints(self):
        """Test watchlist endpoints"""
        print("\n🔍 Testing Watchlist Endpoints...")
        
        # Test get watchlist
        success, data = self.test_endpoint('GET', '/api/watchlist', test_name="Get Watchlist")
        
        # Test generate watchlist
        success, data = self.test_endpoint('POST', '/api/watchlist/generate', test_name="Generate Watchlist")

    def test_portfolio_endpoints(self):
        """Test portfolio endpoints"""
        print("\n🔍 Testing Portfolio Endpoints...")
        
        # Test get portfolio
        success, data = self.test_endpoint('GET', '/api/portfolio', test_name="Get Portfolio")
        
        # Test add position
        success, data = self.test_endpoint('POST', '/api/portfolio/add',
                                         params={'symbol': 'AAPL', 'shares': 10, 'avg_cost': 150.0},
                                         test_name="Add Portfolio Position")
        
        # Test remove position (cleanup)
        success, data = self.test_endpoint('DELETE', '/api/portfolio/AAPL', 
                                         expected_status=200,
                                         test_name="Remove Portfolio Position")

    def test_alerts_endpoints(self):
        """Test alerts endpoints"""
        print("\n🔍 Testing Alerts Endpoints...")
        
        # Test get alerts
        success, data = self.test_endpoint('GET', '/api/alerts', test_name="Get Alerts")
        
        # Test generate alerts
        success, data = self.test_endpoint('POST', '/api/alerts/generate', test_name="Generate Alerts")
        
        # Test clear alerts
        success, data = self.test_endpoint('DELETE', '/api/alerts/clear', test_name="Clear Alerts")

    def test_fundamentals_endpoints(self):
        """Test fundamentals endpoints"""
        print("\n🔍 Testing Fundamentals Endpoints...")
        
        # Test fundamentals for AAPL
        success, data = self.test_endpoint('GET', '/api/fundamentals/AAPL', test_name="Get AAPL Fundamentals")
        
        if success and data:
            required_fields = ['symbol', 'company_name', 'market_cap', 'pe_ratio']
            missing_fields = [field for field in required_fields if field not in data]
            
            if not missing_fields:
                self.log_test("Fundamentals Data Structure", True, "All required fields present")
            else:
                self.log_test("Fundamentals Data Structure", False, f"Missing fields: {missing_fields}")
        
        # Test historical data
        success, data = self.test_endpoint('GET', '/api/historical/AAPL', test_name="Get Historical Data")

    def test_insider_trading_endpoints(self):
        """Test insider trading endpoints"""
        print("\n🔍 Testing Insider Trading Endpoints...")
        
        # Test insider trades for AAPL
        success, data = self.test_endpoint('GET', '/api/insider/AAPL', test_name="Get AAPL Insider Trades")
        
        if success and data:
            if 'trades' in data and 'summary' in data:
                self.log_test("Insider Data Structure", True, "Trades and summary present")
                
                # Check summary fields
                summary = data['summary']
                required_summary_fields = ['total_buys', 'total_sells', 'net_activity', 'signal']
                missing_fields = [field for field in required_summary_fields if field not in summary]
                
                if not missing_fields:
                    self.log_test("Insider Summary Structure", True, "All summary fields present")
                else:
                    self.log_test("Insider Summary Structure", False, f"Missing fields: {missing_fields}")
            else:
                self.log_test("Insider Data Structure", False, "Missing trades or summary")
        
        # Test unusual insider activity
        success, data = self.test_endpoint('GET', '/api/insider/unusual', test_name="Get Unusual Insider Activity")
        
        if success and data:
            if 'unusual_activity' in data and 'all_activity' in data:
                self.log_test("Unusual Activity Structure", True, "Activity data present")
            else:
                self.log_test("Unusual Activity Structure", False, "Missing activity data")

    def test_cot_endpoints(self):
        """Test COT (Commitment of Traders) endpoints"""
        print("\n🔍 Testing COT Endpoints...")
        
        # Test COT data for ES (E-Mini S&P 500)
        success, data = self.test_endpoint('GET', '/api/cot/ES', test_name="Get ES COT Data")
        
        if success and data:
            if 'data' in data and len(data['data']) > 0:
                self.log_test("COT Data Structure", True, f"Found {len(data['data'])} COT records")
                
                # Check first record structure
                first_record = data['data'][0]
                required_fields = ['commercial_long', 'commercial_short', 'non_commercial_long', 'non_commercial_short']
                missing_fields = [field for field in required_fields if field not in first_record]
                
                if not missing_fields:
                    self.log_test("COT Record Structure", True, "All required fields present")
                else:
                    self.log_test("COT Record Structure", False, f"Missing fields: {missing_fields}")
            else:
                self.log_test("COT Data Structure", False, "No COT data found")
        
        # Test COT summary
        success, data = self.test_endpoint('GET', '/api/cot/summary', test_name="Get COT Summary")
        
        if success and data:
            if 'summary' in data and len(data['summary']) > 0:
                self.log_test("COT Summary Structure", True, f"Found {len(data['summary'])} market summaries")
            else:
                self.log_test("COT Summary Structure", False, "No summary data found")

    def test_newsletter_endpoints(self):
        """Test newsletter endpoints"""
        print("\n🔍 Testing Newsletter Endpoints...")
        
        # Test get latest newsletter
        success, data = self.test_endpoint('GET', '/api/newsletter/latest', test_name="Get Latest Newsletter")
        
        # Test generate newsletter
        success, data = self.test_endpoint('POST', '/api/newsletter/generate', test_name="Generate Newsletter")

    def test_dashboard_endpoints(self):
        """Test dashboard endpoints"""
        print("\n🔍 Testing Dashboard Endpoints...")
        
        # Test dashboard stats
        success, data = self.test_endpoint('GET', '/api/dashboard/stats', test_name="Dashboard Stats")

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting TradeCommand API Tests...")
        print(f"📡 Testing against: {self.base_url}")
        
        # Run all test suites
        self.test_health_endpoint()
        self.test_strategies_endpoints()
        self.test_scanner_endpoints()
        self.test_market_endpoints()
        self.test_watchlist_endpoints()
        self.test_portfolio_endpoints()
        self.test_alerts_endpoints()
        self.test_newsletter_endpoints()
        self.test_dashboard_endpoints()
        
        # Print summary
        print(f"\n📊 Test Summary:")
        print(f"   Total Tests: {self.tests_run}")
        print(f"   Passed: {self.tests_passed}")
        print(f"   Failed: {len(self.failed_tests)}")
        print(f"   Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.failed_tests:
            print(f"\n❌ Failed Tests:")
            for test in self.failed_tests:
                print(f"   - {test['name']}: {test['details']}")
        
        return self.tests_passed == self.tests_run

def main():
    """Main test runner"""
    tester = TradeCommandAPITester()
    success = tester.run_all_tests()
    
    # Return appropriate exit code
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())