"""
Test startup stability endpoints - verifies backend APIs respond correctly
to support the frontend's sequential health checks and safePolling mechanism.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestStartupStabilityEndpoints:
    """Tests for endpoints used during app startup and polling"""
    
    def test_health_endpoint(self):
        """Test /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'healthy'
        print(f"✓ Health endpoint: {data}")
    
    def test_ib_status_endpoint(self):
        """Test /api/ib/status returns connection status"""
        response = requests.get(f"{BASE_URL}/api/ib/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        # IB may not be connected, but endpoint should respond
        assert 'connected' in data
        print(f"✓ IB status: connected={data.get('connected')}")
    
    def test_sentcom_status_endpoint(self):
        """Test /api/sentcom/status returns scanner status"""
        response = requests.get(f"{BASE_URL}/api/sentcom/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        print(f"✓ SentCom status: {data.get('status', {}).get('state')}")
    
    def test_assistant_check_ollama(self):
        """Test /api/assistant/check-ollama returns AI availability"""
        response = requests.get(f"{BASE_URL}/api/assistant/check-ollama", timeout=10)
        assert response.status_code == 200
        data = response.json()
        # Ollama may not be available, but endpoint should respond
        assert 'available' in data or 'ollama_available' in data
        print(f"✓ Ollama check: available={data.get('available') or data.get('ollama_available')}")
    
    def test_ai_modules_timeseries_status(self):
        """Test /api/ai-modules/timeseries/status returns AI module status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        print(f"✓ Timeseries AI status: {data.get('status', {})}")
    
    def test_learning_connectors_status(self):
        """Test /api/learning-connectors/status returns learning engine status"""
        response = requests.get(f"{BASE_URL}/api/learning-connectors/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        print(f"✓ Learning connectors status: {data.get('status', {})}")
    
    def test_trading_bot_dashboard_data(self):
        """Test /api/trading-bot/dashboard-data returns bot dashboard"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/dashboard-data", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        print(f"✓ Trading bot dashboard: bot_status={data.get('bot_status', {}).get('state')}")
    
    def test_market_context_session_status(self):
        """Test /api/market-context/session/status returns market session"""
        response = requests.get(f"{BASE_URL}/api/market-context/session/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') == True
        print(f"✓ Market session: {data.get('session', {}).get('name')}")


class TestConcurrentRequests:
    """Test that backend handles concurrent requests without crashing"""
    
    def test_concurrent_health_checks(self):
        """Simulate multiple concurrent health checks (like startup modal does)"""
        import concurrent.futures
        
        endpoints = [
            '/api/health',
            '/api/ib/status',
            '/api/sentcom/status',
            '/api/assistant/check-ollama',
            '/api/ai-modules/timeseries/status',
            '/api/learning-connectors/status',
        ]
        
        def check_endpoint(endpoint):
            try:
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
                return endpoint, response.status_code, None
            except Exception as e:
                return endpoint, None, str(e)
        
        # Run all checks concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(check_endpoint, ep) for ep in endpoints]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Verify all succeeded
        for endpoint, status, error in results:
            if error:
                print(f"✗ {endpoint}: ERROR - {error}")
            else:
                print(f"✓ {endpoint}: {status}")
            assert error is None, f"Endpoint {endpoint} failed: {error}"
            assert status == 200, f"Endpoint {endpoint} returned {status}"
        
        print(f"\n✓ All {len(endpoints)} concurrent requests succeeded")
    
    def test_sequential_health_checks_with_delay(self):
        """Test sequential health checks with 500ms delay (like StartupModal does)"""
        endpoints = [
            '/api/health',
            '/api/ib/status',
            '/api/sentcom/status',
            '/api/assistant/check-ollama',
            '/api/ai-modules/timeseries/status',
            '/api/learning-connectors/status',
        ]
        
        for endpoint in endpoints:
            response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
            assert response.status_code == 200, f"{endpoint} failed with {response.status_code}"
            print(f"✓ {endpoint}: {response.status_code}")
            time.sleep(0.5)  # 500ms delay like StartupModal
        
        print(f"\n✓ Sequential checks with 500ms delay completed successfully")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
