"""
Test AI Comparison Backtest Feature
====================================
Tests for the new AI vs Setup comparison backtest functionality:
1. GET /api/backtest/ai-comparison/status - AI model status
2. POST /api/backtest/ai-comparison - Run AI comparison backtest
3. GET /api/market-scanner/symbols - Market scanner prefix change
4. Existing backtest endpoints still work
5. Concurrent API performance
"""

import pytest
import requests
import os
import time
import concurrent.futures

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://lightgbm-pipeline.preview.emergentagent.com').rstrip('/')


class TestAIComparisonStatus:
    """Test AI model status endpoint"""
    
    def test_ai_comparison_status_returns_json(self):
        """GET /api/backtest/ai-comparison/status returns valid JSON with expected fields"""
        response = requests.get(f"{BASE_URL}/api/backtest/ai-comparison/status", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "ai_available" in data, "Missing ai_available field"
        assert "model_version" in data, "Missing model_version field"
        assert "model_accuracy" in data, "Missing model_accuracy field"
        assert "feature_count" in data, "Missing feature_count field"
        
        # Validate types
        assert isinstance(data["ai_available"], bool), "ai_available should be boolean"
        assert isinstance(data["model_version"], str), "model_version should be string"
        assert isinstance(data["model_accuracy"], (int, float)), "model_accuracy should be numeric"
        assert isinstance(data["feature_count"], int), "feature_count should be integer"
        
        print(f"AI Status: available={data['ai_available']}, version={data['model_version']}, accuracy={data['model_accuracy']}, features={data['feature_count']}")


class TestAIComparisonBacktest:
    """Test AI comparison backtest endpoint"""
    
    def test_ai_comparison_backtest_sync(self):
        """POST /api/backtest/ai-comparison with run_in_background=false returns full results"""
        payload = {
            "symbols": ["AAPL", "MSFT", "NVDA"],
            "strategy": {
                "name": "ORB Test",
                "setup_type": "orb",
                "stop_pct": 2.0,
                "target_pct": 4.0,
                "max_bars_to_hold": 20,
                "position_size_pct": 10.0,
                "min_tqs_score": 0,
                "use_trailing_stop": False,
                "trailing_stop_pct": 1.0
            },
            "start_date": "2025-06-01",
            "end_date": "2026-03-01",
            "ai_confidence_threshold": 0.0,
            "run_in_background": False
        }
        
        response = requests.post(
            f"{BASE_URL}/api/backtest/ai-comparison",
            json=payload,
            timeout=120  # AI comparison can take time
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "result" in data, "Missing result field"
        
        result = data["result"]
        
        # Validate result structure
        assert "setup_only" in result, "Missing setup_only metrics"
        assert "ai_filtered" in result, "Missing ai_filtered metrics"
        assert "ai_only" in result, "Missing ai_only metrics"
        assert "symbol_results" in result, "Missing symbol_results"
        assert "recommendation" in result, "Missing recommendation"
        
        # Validate setup_only metrics
        setup_only = result["setup_only"]
        assert "total_trades" in setup_only, "setup_only missing total_trades"
        assert "win_rate" in setup_only, "setup_only missing win_rate"
        assert "total_pnl" in setup_only, "setup_only missing total_pnl"
        
        # Validate ai_filtered metrics
        ai_filtered = result["ai_filtered"]
        assert "total_trades" in ai_filtered, "ai_filtered missing total_trades"
        assert "win_rate" in ai_filtered, "ai_filtered missing win_rate"
        
        # Validate ai_only metrics
        ai_only = result["ai_only"]
        assert "total_trades" in ai_only, "ai_only missing total_trades"
        
        # Validate symbol_results
        assert isinstance(result["symbol_results"], list), "symbol_results should be a list"
        
        print(f"AI Comparison Results:")
        print(f"  Setup-only: {setup_only.get('total_trades')} trades, {setup_only.get('win_rate')}% WR")
        print(f"  AI+Setup: {ai_filtered.get('total_trades')} trades, {ai_filtered.get('win_rate')}% WR")
        print(f"  AI-only: {ai_only.get('total_trades')} trades, {ai_only.get('win_rate')}% WR")
        print(f"  Recommendation: {result.get('recommendation')}")
    
    def test_ai_comparison_backtest_background(self):
        """POST /api/backtest/ai-comparison with run_in_background=true returns job_id"""
        payload = {
            "symbols": ["AAPL"],
            "strategy": {
                "name": "Quick Test",
                "setup_type": "orb",
                "stop_pct": 2.0,
                "target_pct": 4.0,
                "max_bars_to_hold": 20,
                "position_size_pct": 10.0
            },
            "start_date": "2025-12-01",
            "end_date": "2026-01-01",
            "ai_confidence_threshold": 0.0,
            "run_in_background": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/backtest/ai-comparison",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "job_id" in data, "Missing job_id for background job"
        
        print(f"Background job started: {data['job_id']}")


class TestMarketScannerPrefixChange:
    """Test market scanner prefix change from /api/scanner to /api/market-scanner"""
    
    def test_market_scanner_symbols_endpoint(self):
        """GET /api/market-scanner/symbols returns valid response"""
        response = requests.get(f"{BASE_URL}/api/market-scanner/symbols", timeout=15)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "total_symbols" in data, "Missing total_symbols"
        assert "sample" in data, "Missing sample"
        
        print(f"Market Scanner: {data['total_symbols']} symbols available, sample: {data['sample'][:5]}")
    
    def test_market_scanner_status_endpoint(self):
        """GET /api/market-scanner/status returns valid response"""
        response = requests.get(f"{BASE_URL}/api/market-scanner/status", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        print(f"Market Scanner Status: {data}")


class TestExistingBacktestEndpoints:
    """Test that existing backtest endpoints still work"""
    
    def test_backtest_jobs_endpoint(self):
        """GET /api/backtest/jobs returns valid response"""
        response = requests.get(f"{BASE_URL}/api/backtest/jobs", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "jobs" in data, "Missing jobs field"
        
        print(f"Backtest Jobs: {len(data['jobs'])} jobs found")
    
    def test_backtest_strategies_endpoint(self):
        """GET /api/backtest/strategies returns valid response"""
        response = requests.get(f"{BASE_URL}/api/backtest/strategies", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "strategies" in data, "Missing strategies field"
        
        print(f"Backtest Strategies: {data.get('total', len(data['strategies']))} strategies available")
    
    def test_backtest_strategy_templates_endpoint(self):
        """GET /api/backtest/strategy-templates returns valid response"""
        response = requests.get(f"{BASE_URL}/api/backtest/strategy-templates", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "templates" in data, "Missing templates field"
        
        print(f"Strategy Templates: {len(data['templates'])} templates available")


class TestExistingAPIEndpoints:
    """Test that all previously working API endpoints still respond fast"""
    
    def test_startup_check_endpoint(self):
        """GET /api/startup-check responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/startup-check: {response.status_code} in {elapsed:.2f}s")
    
    def test_watchlist_endpoint(self):
        """GET /api/watchlist responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/watchlist", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/watchlist: {response.status_code} in {elapsed:.2f}s")
    
    def test_alerts_endpoint(self):
        """GET /api/alerts responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/alerts", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/alerts: {response.status_code} in {elapsed:.2f}s")
    
    def test_portfolio_endpoint(self):
        """GET /api/portfolio responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/portfolio", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/portfolio: {response.status_code} in {elapsed:.2f}s")
    
    def test_simulation_jobs_endpoint(self):
        """GET /api/simulation/jobs responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/simulation/jobs", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/simulation/jobs: {response.status_code} in {elapsed:.2f}s")
    
    def test_ai_modules_status_endpoint(self):
        """GET /api/ai-modules/status responds under 2s"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/ai-modules/status", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 2.0, f"Response took {elapsed:.2f}s, expected < 2s"
        
        print(f"/api/ai-modules/status: {response.status_code} in {elapsed:.2f}s")


class TestConcurrentAPIPerformance:
    """Test concurrent API requests complete without blocking"""
    
    def test_concurrent_requests_complete_under_2s(self):
        """6+ concurrent requests all respond under 2s"""
        endpoints = [
            "/api/startup-check",
            "/api/watchlist",
            "/api/alerts",
            "/api/portfolio",
            "/api/simulation/jobs",
            "/api/ai-modules/status",
            "/api/backtest/ai-comparison/status"
        ]
        
        def fetch_endpoint(endpoint):
            start = time.time()
            try:
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
                elapsed = time.time() - start
                return {
                    "endpoint": endpoint,
                    "status": response.status_code,
                    "elapsed": elapsed,
                    "success": response.status_code == 200 and elapsed < 2.0
                }
            except Exception as e:
                return {
                    "endpoint": endpoint,
                    "status": 0,
                    "elapsed": time.time() - start,
                    "success": False,
                    "error": str(e)
                }
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
            results = list(executor.map(fetch_endpoint, endpoints))
        
        total_time = time.time() - start_time
        
        # All should succeed
        all_success = all(r["success"] for r in results)
        
        print(f"\nConcurrent Request Results (total wall time: {total_time:.2f}s):")
        for r in results:
            status = "✓" if r["success"] else "✗"
            print(f"  {status} {r['endpoint']}: {r['status']} in {r['elapsed']:.2f}s")
        
        assert all_success, f"Some concurrent requests failed or took too long: {results}"
        assert total_time < 3.0, f"Total wall time {total_time:.2f}s exceeds 3s (should be parallel)"
        
        print(f"\nAll {len(endpoints)} concurrent requests completed successfully in {total_time:.2f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
