"""
Test API optimization changes - Verifies endpoints still return valid responses quickly
after cache TTL increases and polling interval changes.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAPIOptimization:
    """Test that all APIs work correctly after optimization changes"""
    
    def test_health_endpoint(self):
        """Health check should respond quickly"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'healthy'
        assert elapsed < 2, f"Health check took {elapsed}s, should be under 2s"
        print(f"Health endpoint: {elapsed:.3f}s")
    
    def test_trading_bot_status(self):
        """GET /api/trading-bot/status should return valid response"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/trading-bot/status", timeout=15)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'mode' in data  # confirmation, autonomous, paused
        assert 'risk_params' in data
        assert 'daily_stats' in data
        assert 'enabled_setups' in data
        assert elapsed < 5, f"Bot status took {elapsed}s, should be under 5s"
        print(f"Bot status endpoint: {elapsed:.3f}s, mode={data.get('mode')}")
    
    def test_learning_strategy_stats(self):
        """GET /api/learning/strategy-stats should return strategy performance data"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats", timeout=15)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'stats' in data
        
        # Verify strategy data structure
        stats = data['stats']
        for strategy_name, strategy_stats in stats.items():
            assert 'total_trades' in strategy_stats
            assert 'wins' in strategy_stats
            assert 'losses' in strategy_stats
            assert 'win_rate' in strategy_stats
            assert 'total_pnl' in strategy_stats
            
        assert elapsed < 5, f"Strategy stats took {elapsed}s, should be under 5s"
        print(f"Strategy stats endpoint: {elapsed:.3f}s, strategies={list(stats.keys())}")
    
    def test_trading_bot_trades_all(self):
        """GET /api/trading-bot/trades/all should return trade lists"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all", timeout=15)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'pending' in data
        assert 'open' in data
        assert 'closed' in data
        assert 'daily_stats' in data
        assert elapsed < 5, f"Trades all took {elapsed}s, should be under 5s"
        print(f"Trades all endpoint: {elapsed:.3f}s, pending={len(data['pending'])}, open={len(data['open'])}, closed={len(data['closed'])}")
    
    def test_demo_trade_creation(self):
        """POST /api/trading-bot/demo-trade should still work correctly"""
        start = time.time()
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={
                "symbol": "TEST_OPT",
                "direction": "long",
                "setup_type": "breakout"
            },
            timeout=15
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'trade' in data
        
        trade = data['trade']
        assert trade['symbol'] == 'TEST_OPT'
        assert trade['direction'] == 'long'
        assert trade['status'] == 'pending'
        assert elapsed < 5, f"Demo trade took {elapsed}s, should be under 5s"
        print(f"Demo trade endpoint: {elapsed:.3f}s, trade_id={trade.get('id')}")
    
    def test_learning_recommendations(self):
        """GET /api/learning/recommendations should return tuning recommendations"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/learning/recommendations", timeout=15)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'recommendations' in data
        assert elapsed < 5, f"Recommendations took {elapsed}s, should be under 5s"
        print(f"Recommendations endpoint: {elapsed:.3f}s, count={len(data.get('recommendations', []))}")
    
    def test_learning_tuning_history(self):
        """GET /api/learning/tuning-history should return history"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history", timeout=15)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        assert 'history' in data
        assert elapsed < 5, f"Tuning history took {elapsed}s, should be under 5s"
        print(f"Tuning history endpoint: {elapsed:.3f}s, count={len(data.get('history', []))}")
