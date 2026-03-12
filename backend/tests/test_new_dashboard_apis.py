"""
Test suite for new trading bot dashboard APIs
Tests the three new endpoints:
1. GET /api/trading-bot/dashboard-data
2. GET /api/trading-bot/performance/equity-curve
3. GET /api/trading-bot/thoughts
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestDashboardDataAPI:
    """Tests for GET /api/trading-bot/dashboard-data endpoint"""
    
    def test_dashboard_data_returns_200(self):
        """Dashboard data endpoint should return 200 status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_dashboard_data_structure(self):
        """Dashboard data should contain all required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True, "Response should have success=True"
        
        # Check required fields exist
        required_fields = [
            'bot_status',
            'today_pnl',
            'open_pnl',
            'open_trades',
            'watching_setups',
            'recent_thoughts',
            'performance_summary'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_dashboard_data_bot_status_structure(self):
        """Bot status should have running, mode, and state fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200
        
        data = response.json()
        bot_status = data.get('bot_status', {})
        
        assert 'running' in bot_status, "bot_status missing 'running' field"
        assert 'mode' in bot_status, "bot_status missing 'mode' field"
        assert 'state' in bot_status, "bot_status missing 'state' field"
        
        # Validate mode is valid value
        valid_modes = ['autonomous', 'confirmation', 'paused']
        assert bot_status.get('mode') in valid_modes, f"Invalid bot mode: {bot_status.get('mode')}"
    
    def test_dashboard_data_pnl_values_are_numeric(self):
        """P&L values should be numeric"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data.get('today_pnl'), (int, float)), "today_pnl should be numeric"
        assert isinstance(data.get('open_pnl'), (int, float)), "open_pnl should be numeric"
    
    def test_dashboard_data_open_trades_is_list(self):
        """Open trades should be a list"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data.get('open_trades'), list), "open_trades should be a list"
    
    def test_dashboard_data_open_trade_structure(self):
        """Each open trade should have required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data")
        assert response.status_code == 200
        
        data = response.json()
        open_trades = data.get('open_trades', [])
        
        if len(open_trades) > 0:
            trade = open_trades[0]
            required_trade_fields = ['id', 'symbol', 'direction', 'status', 'entry_price', 'stop_price']
            for field in required_trade_fields:
                assert field in trade, f"Trade missing required field: {field}"


class TestEquityCurveAPI:
    """Tests for GET /api/trading-bot/performance/equity-curve endpoint"""
    
    def test_equity_curve_returns_200(self):
        """Equity curve endpoint should return 200 status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=today")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_equity_curve_structure(self):
        """Equity curve should have required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=today")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True, "Response should have success=True"
        
        required_fields = ['equity_curve', 'trade_markers', 'summary']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_equity_curve_period_today(self):
        """Test equity curve with period=today"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=today")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('period') == 'today', "Period should be 'today'"
        assert isinstance(data.get('equity_curve'), list), "equity_curve should be a list"
    
    def test_equity_curve_period_week(self):
        """Test equity curve with period=week"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=week")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('period') == 'week', "Period should be 'week'"
    
    def test_equity_curve_period_month(self):
        """Test equity curve with period=month"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=month")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('period') == 'month', "Period should be 'month'"
    
    def test_equity_curve_period_ytd(self):
        """Test equity curve with period=ytd"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=ytd")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('period') == 'ytd', "Period should be 'ytd'"
    
    def test_equity_curve_period_all(self):
        """Test equity curve with period=all"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=all")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('period') == 'all', "Period should be 'all'"
    
    def test_equity_curve_summary_structure(self):
        """Summary should contain performance stats"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/performance/equity-curve?period=today")
        assert response.status_code == 200
        
        data = response.json()
        summary = data.get('summary', {})
        
        summary_fields = ['total_pnl', 'trades_count', 'win_rate', 'avg_r', 'best_trade', 'worst_trade']
        for field in summary_fields:
            assert field in summary, f"Summary missing field: {field}"


class TestBotThoughtsAPI:
    """Tests for GET /api/trading-bot/thoughts endpoint"""
    
    def test_thoughts_returns_200(self):
        """Thoughts endpoint should return 200 status"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_thoughts_structure(self):
        """Thoughts response should have required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True, "Response should have success=True"
        assert 'thoughts' in data, "Response should have 'thoughts' field"
        assert isinstance(data.get('thoughts'), list), "thoughts should be a list"
    
    def test_thoughts_limit_parameter(self):
        """Limit parameter should control number of thoughts returned"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=3")
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get('thoughts', [])
        assert len(thoughts) <= 3, f"Should return at most 3 thoughts, got {len(thoughts)}"
    
    def test_thoughts_entry_structure(self):
        """Each thought should have required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get('thoughts', [])
        
        if len(thoughts) > 0:
            thought = thoughts[0]
            required_fields = ['text', 'timestamp', 'confidence', 'action_type']
            for field in required_fields:
                assert field in thought, f"Thought missing required field: {field}"
            
            # Validate confidence is in valid range
            confidence = thought.get('confidence')
            assert isinstance(confidence, (int, float)), "confidence should be numeric"
            assert 0 <= confidence <= 100, f"confidence should be 0-100, got {confidence}"
    
    def test_thoughts_action_types(self):
        """Action types should be valid values"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get('thoughts', [])
        
        valid_action_types = ['entry', 'exit', 'watching', 'monitoring', 'scanning', 'alert', 'offline']
        
        for thought in thoughts:
            action_type = thought.get('action_type')
            assert action_type in valid_action_types, f"Invalid action_type: {action_type}"
    
    def test_thoughts_first_person_text(self):
        """Thoughts text should be in first person (contain I/I'm/I'll)"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get('thoughts', [])
        
        first_person_indicators = ["I ", "I'm", "I'll", "I've"]
        
        for thought in thoughts:
            text = thought.get('text', '')
            has_first_person = any(indicator in text for indicator in first_person_indicators)
            assert has_first_person, f"Thought not in first person: {text[:50]}..."


class TestExistingBotEndpoints:
    """Tests for existing bot endpoints to ensure they still work"""
    
    def test_bot_status_endpoint(self):
        """GET /api/trading-bot/status should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True
    
    def test_trades_open_endpoint(self):
        """GET /api/trading-bot/trades/open should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True
        assert 'trades' in data
    
    def test_trades_closed_endpoint(self):
        """GET /api/trading-bot/trades/closed should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True
        assert 'trades' in data
    
    def test_stats_daily_endpoint(self):
        """GET /api/trading-bot/stats/daily should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/stats/daily")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True
        assert 'stats' in data
    
    def test_stats_performance_endpoint(self):
        """GET /api/trading-bot/stats/performance should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/stats/performance")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('success') == True
        assert 'stats' in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
