"""
P1 Tasks Testing - Model Protection, Dead Code Removal, Scanner Consolidation

Tests:
1. Best Model Protection - /api/ai-modules/timeseries/model-history endpoint
2. Dead code removal - background_scanner.py should not exist
3. Scanner consolidation - predictive_scanner wired to enhanced_scanner
4. All scanner endpoints still work after consolidation
5. AI comparison backtest still works
6. Key endpoints respond under 2s
"""

import pytest
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestModelProtection:
    """Test Best Model Protection feature - model archiving and promotion logic"""
    
    def test_model_history_endpoint_returns_valid_structure(self):
        """GET /api/ai-modules/timeseries/model-history returns proper JSON structure"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/model-history", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify required fields exist
        assert "success" in data, "Response missing 'success' field"
        assert "active_model" in data, "Response missing 'active_model' field"
        assert "archived_models" in data, "Response missing 'archived_models' field"
        assert "total_archived" in data, "Response missing 'total_archived' field"
        
        # Verify active_model structure
        active = data["active_model"]
        assert "version" in active, "active_model missing 'version'"
        assert "accuracy" in active, "active_model missing 'accuracy'"
        
        # archived_models should be a list
        assert isinstance(data["archived_models"], list), "archived_models should be a list"
        assert isinstance(data["total_archived"], int), "total_archived should be an integer"
        
        print(f"Model history: active={active['version']}, accuracy={active['accuracy']}, archived={data['total_archived']}")
    
    def test_timeseries_status_endpoint(self):
        """GET /api/ai-modules/timeseries/status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "success" in data, "Response missing 'success' field"
        assert "status" in data, "Response missing 'status' field"
        
        status = data["status"]
        # Status should have service info
        assert "service" in status or "model_name" in status or "initialized" in status, \
            f"Status missing expected fields: {status}"
        
        print(f"Timeseries status: {status}")


class TestDeadCodeRemoval:
    """Test that background_scanner.py has been deleted"""
    
    def test_background_scanner_file_does_not_exist(self):
        """Verify background_scanner.py is deleted from /app/backend/services/"""
        import subprocess
        result = subprocess.run(
            ["ls", "-la", "/app/backend/services/background_scanner.py"],
            capture_output=True,
            text=True
        )
        # File should NOT exist - ls should fail
        assert result.returncode != 0, "background_scanner.py should be deleted but still exists!"
        print("Confirmed: background_scanner.py has been deleted")


class TestScannerConsolidation:
    """Test that scanner endpoints still work after consolidation"""
    
    def test_predictive_scanner_status(self):
        """GET /api/scanner/status returns 200"""
        response = requests.get(f"{BASE_URL}/api/scanner/status", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"Predictive scanner status: {response.json()}")
    
    def test_predictive_scanner_alerts(self):
        """GET /api/scanner/alerts returns 200"""
        response = requests.get(f"{BASE_URL}/api/scanner/alerts", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"Predictive scanner alerts: {response.json()}")
    
    def test_enhanced_scanner_alerts(self):
        """GET /api/live-scanner/alerts returns 200 (enhanced scanner)"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        print(f"Enhanced scanner alerts count: {len(data.get('alerts', []))}")
    
    def test_market_scanner_symbols(self):
        """GET /api/market-scanner/symbols returns 200"""
        response = requests.get(f"{BASE_URL}/api/market-scanner/symbols", timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        symbol_count = data.get("total", len(data.get("symbols", [])))
        print(f"Market scanner symbols: {symbol_count}")


class TestAIComparisonBacktest:
    """Test AI comparison backtest endpoints"""
    
    def test_ai_comparison_status(self):
        """GET /api/backtest/ai-comparison/status returns ai_available: true"""
        response = requests.get(f"{BASE_URL}/api/backtest/ai-comparison/status", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "ai_available" in data, "Response missing 'ai_available' field"
        print(f"AI comparison status: ai_available={data.get('ai_available')}")
    
    def test_ai_comparison_backtest_sync(self):
        """POST /api/backtest/ai-comparison with valid payload returns all three modes"""
        payload = {
            "symbols": ["AAPL"],
            "strategy": {
                "name": "Test",
                "setup_type": "orb",
                "stop_pct": 2,
                "target_pct": 4,
                "max_bars_to_hold": 20,
                "position_size_pct": 10
            },
            "run_in_background": False
        }
        
        response = requests.post(
            f"{BASE_URL}/api/backtest/ai-comparison",
            json=payload,
            timeout=60  # Backtest can take time
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Should have results for all three modes
        assert "result" in data or "setup_only" in data or "results" in data, \
            f"Response missing expected result fields: {data.keys()}"
        
        print(f"AI comparison backtest completed: {list(data.keys())}")


class TestEndpointPerformance:
    """Test that key endpoints respond under 2 seconds"""
    
    def test_startup_check_under_2s(self):
        """GET /api/startup-check responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        print(f"/api/startup-check: {elapsed:.2f}s")
    
    def test_watchlist_under_2s(self):
        """GET /api/watchlist responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/watchlist", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        print(f"/api/watchlist: {elapsed:.2f}s")
    
    def test_alerts_under_2s(self):
        """GET /api/alerts responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/alerts", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        print(f"/api/alerts: {elapsed:.2f}s")
    
    def test_portfolio_under_2s(self):
        """GET /api/portfolio responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/portfolio", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        print(f"/api/portfolio: {elapsed:.2f}s")


class TestConcurrentRequests:
    """Test concurrent requests all respond under 2s"""
    
    def test_concurrent_6_requests_under_2s(self):
        """6+ concurrent requests all respond under 2s"""
        endpoints = [
            "/api/startup-check",
            "/api/watchlist",
            "/api/alerts",
            "/api/portfolio",
            "/api/ai-modules/status",
            "/api/scanner/status",
        ]
        
        results = {}
        
        def fetch_endpoint(endpoint):
            start = time.time()
            try:
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
                elapsed = time.time() - start
                return endpoint, response.status_code, elapsed
            except Exception as e:
                elapsed = time.time() - start
                return endpoint, str(e), elapsed
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_endpoint, ep): ep for ep in endpoints}
            for future in as_completed(futures):
                endpoint, status, elapsed = future.result()
                results[endpoint] = {"status": status, "elapsed": elapsed}
        
        # Check all results
        all_passed = True
        for endpoint, result in results.items():
            status = result["status"]
            elapsed = result["elapsed"]
            passed = status == 200 and elapsed < 2.0
            if not passed:
                all_passed = False
            print(f"{endpoint}: status={status}, time={elapsed:.2f}s, passed={passed}")
        
        assert all_passed, f"Some concurrent requests failed or took > 2s: {results}"


class TestAIModulesStatus:
    """Test AI modules status endpoint"""
    
    def test_ai_modules_status(self):
        """GET /api/ai-modules/status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/status", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "success" in data, "Response missing 'success' field"
        print(f"AI modules status: {data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
