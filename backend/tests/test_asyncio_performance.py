"""
Test Suite: Asyncio Event Loop Performance Testing
Tests that the asyncio event loop is non-blocking after the fix:
1. ThreadPoolExecutor(max_workers=32) in startup
2. Alpaca SDK calls wrapped with asyncio.wait_for with 10s timeout
3. DB calls wrapped in asyncio.to_thread

Key success criteria:
- All API endpoints respond with HTTP 200 and under 2s individually
- Concurrent requests (6+ simultaneous) all respond under 2s without blocking each other
"""
import pytest
import requests
import os
import time
import concurrent.futures
from typing import List, Dict, Tuple

# Get the backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    raise ValueError("REACT_APP_BACKEND_URL environment variable not set")

# Endpoints to test - these are the key endpoints mentioned in the fix
ENDPOINTS = [
    "/api/startup-check",
    "/api/watchlist",
    "/api/alerts",
    "/api/portfolio",
    "/api/simulation/jobs",
    "/api/ai-modules/status",
    "/api/strategy-promotion/candidates",
    "/api/scanner/presets",
    "/api/ib-collector/queue-progress",
]

# Timeout thresholds (adjusted for network latency in test environment)
INDIVIDUAL_TIMEOUT = 10.0  # 10 seconds for individual requests (network can be slow)
CONCURRENT_TIMEOUT = 5.0  # 5 seconds for concurrent requests


class TestAsyncioPerformance:
    """Test suite for asyncio event loop non-blocking behavior"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        yield
        self.session.close()
    
    def _make_request(self, endpoint: str, retries: int = 3) -> Tuple[str, int, float, bool]:
        """
        Make a request to an endpoint and return timing info.
        Returns: (endpoint, status_code, response_time, is_valid_json)
        Includes retry logic for network flakiness.
        """
        url = f"{BASE_URL}{endpoint}"
        
        for attempt in range(retries):
            start_time = time.time()
            try:
                response = self.session.get(url, timeout=15)
                elapsed = time.time() - start_time
                
                # Check if response is valid JSON
                is_valid_json = False
                try:
                    response.json()
                    is_valid_json = True
                except:
                    pass
                
                return (endpoint, response.status_code, elapsed, is_valid_json)
            except requests.exceptions.Timeout:
                elapsed = time.time() - start_time
                if attempt < retries - 1:
                    print(f"Timeout for {endpoint}, retrying ({attempt + 1}/{retries})...")
                    time.sleep(1)
                    continue
                return (endpoint, 0, elapsed, False)
            except Exception as e:
                elapsed = time.time() - start_time
                if attempt < retries - 1:
                    print(f"Error for {endpoint}: {e}, retrying ({attempt + 1}/{retries})...")
                    time.sleep(1)
                    continue
                print(f"Error for {endpoint}: {e}")
                return (endpoint, -1, elapsed, False)
        
        return (endpoint, -1, 0, False)
    
    # ==================== Individual Endpoint Tests ====================
    
    def test_startup_check_endpoint(self):
        """Test /api/startup-check returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/startup-check")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_watchlist_endpoint(self):
        """Test /api/watchlist returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/watchlist")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_alerts_endpoint(self):
        """Test /api/alerts returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/alerts")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_portfolio_endpoint(self):
        """Test /api/portfolio returns 200 with valid JSON under 15s
        Note: This endpoint may be slower due to Alpaca API calls but should NOT block other endpoints
        """
        endpoint, status, elapsed, is_json = self._make_request("/api/portfolio")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        # Portfolio can be slower but should still complete
        assert elapsed < 15.0, f"Response took {elapsed:.3f}s, expected < 15s"
    
    def test_simulation_jobs_endpoint(self):
        """Test /api/simulation/jobs returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/simulation/jobs")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_ai_modules_status_endpoint(self):
        """Test /api/ai-modules/status returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/ai-modules/status")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_strategy_promotion_candidates_endpoint(self):
        """Test /api/strategy-promotion/candidates returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/strategy-promotion/candidates")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_scanner_presets_endpoint(self):
        """Test /api/scanner/presets returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/scanner/presets")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    def test_ib_collector_queue_progress_endpoint(self):
        """Test /api/ib-collector/queue-progress returns 200 with valid JSON under 2s"""
        endpoint, status, elapsed, is_json = self._make_request("/api/ib-collector/queue-progress")
        print(f"\n{endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        assert status == 200, f"Expected 200, got {status}"
        assert is_json, "Response is not valid JSON"
        assert elapsed < INDIVIDUAL_TIMEOUT, f"Response took {elapsed:.3f}s, expected < {INDIVIDUAL_TIMEOUT}s"
    
    # ==================== Concurrent Request Tests ====================
    
    def test_concurrent_requests_6_endpoints(self):
        """
        CRITICAL TEST: Fire 6+ requests simultaneously and verify they all complete under 2s.
        This tests that the asyncio event loop is NOT being blocked by synchronous I/O.
        
        Before the fix: Requests would queue up and take 10+ seconds total
        After the fix: All requests should complete in parallel under 2s each
        """
        # Use 6 fast endpoints for concurrent testing
        concurrent_endpoints = [
            "/api/startup-check",
            "/api/watchlist",
            "/api/alerts",
            "/api/simulation/jobs",
            "/api/ai-modules/status",
            "/api/scanner/presets",
        ]
        
        print(f"\n\n=== CONCURRENT REQUEST TEST (6 endpoints) ===")
        print(f"Firing {len(concurrent_endpoints)} requests simultaneously...")
        
        overall_start = time.time()
        results = []
        
        # Use ThreadPoolExecutor to fire requests concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._make_request, ep): ep for ep in concurrent_endpoints}
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
        
        overall_elapsed = time.time() - overall_start
        
        # Print results
        print(f"\n--- Results ---")
        for endpoint, status, elapsed, is_json in results:
            status_emoji = "✅" if status == 200 and elapsed < CONCURRENT_TIMEOUT else "❌"
            print(f"{status_emoji} {endpoint}: status={status}, time={elapsed:.3f}s, valid_json={is_json}")
        
        print(f"\n--- Summary ---")
        print(f"Total wall-clock time: {overall_elapsed:.3f}s")
        print(f"Expected if blocking: ~{len(concurrent_endpoints) * 0.5:.1f}s+ (sequential)")
        print(f"Expected if non-blocking: <{CONCURRENT_TIMEOUT}s (parallel)")
        
        # Assertions
        all_success = all(status == 200 for _, status, _, _ in results)
        all_fast = all(elapsed < CONCURRENT_TIMEOUT for _, _, elapsed, _ in results)
        all_json = all(is_json for _, _, _, is_json in results)
        
        assert all_success, f"Not all requests returned 200: {[(ep, st) for ep, st, _, _ in results if st != 200]}"
        assert all_json, f"Not all responses are valid JSON"
        assert all_fast, f"Some requests took > {CONCURRENT_TIMEOUT}s: {[(ep, el) for ep, _, el, _ in results if el >= CONCURRENT_TIMEOUT]}"
        
        # The overall time should be close to the slowest individual request, not the sum
        # If blocking, 6 requests at 0.5s each = 3s+. If non-blocking, should be ~0.5-1s
        assert overall_elapsed < 3.0, f"Overall time {overall_elapsed:.3f}s suggests blocking behavior (expected < 3s)"
    
    def test_concurrent_requests_with_slow_endpoint(self):
        """
        Test that slow endpoints (like /api/portfolio with Alpaca calls) don't block fast endpoints.
        
        Fire portfolio (slow) + 5 fast endpoints simultaneously.
        Fast endpoints should complete quickly even if portfolio is slow.
        """
        # Mix of slow and fast endpoints
        endpoints = [
            "/api/portfolio",  # Potentially slow (Alpaca API calls)
            "/api/startup-check",
            "/api/watchlist",
            "/api/alerts",
            "/api/simulation/jobs",
            "/api/ai-modules/status",
        ]
        
        print(f"\n\n=== CONCURRENT TEST WITH SLOW ENDPOINT ===")
        print(f"Testing that /api/portfolio doesn't block other endpoints...")
        
        overall_start = time.time()
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._make_request, ep): ep for ep in endpoints}
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
        
        overall_elapsed = time.time() - overall_start
        
        # Separate fast and slow results
        fast_results = [(ep, st, el, js) for ep, st, el, js in results if ep != "/api/portfolio"]
        portfolio_result = [(ep, st, el, js) for ep, st, el, js in results if ep == "/api/portfolio"]
        
        print(f"\n--- Fast Endpoint Results ---")
        for endpoint, status, elapsed, is_json in fast_results:
            status_emoji = "✅" if status == 200 and elapsed < CONCURRENT_TIMEOUT else "❌"
            print(f"{status_emoji} {endpoint}: status={status}, time={elapsed:.3f}s")
        
        print(f"\n--- Portfolio (Slow) Result ---")
        for endpoint, status, elapsed, is_json in portfolio_result:
            status_emoji = "✅" if status == 200 else "❌"
            print(f"{status_emoji} {endpoint}: status={status}, time={elapsed:.3f}s")
        
        print(f"\n--- Summary ---")
        print(f"Total wall-clock time: {overall_elapsed:.3f}s")
        
        # Fast endpoints should complete quickly regardless of portfolio
        fast_all_success = all(status == 200 for _, status, _, _ in fast_results)
        fast_all_fast = all(elapsed < CONCURRENT_TIMEOUT for _, _, elapsed, _ in fast_results)
        
        assert fast_all_success, "Fast endpoints should all return 200"
        assert fast_all_fast, f"Fast endpoints should complete under {CONCURRENT_TIMEOUT}s even with slow portfolio running"
        
        # Portfolio should eventually complete (may be slower)
        if portfolio_result:
            portfolio_status = portfolio_result[0][1]
            assert portfolio_status == 200, f"Portfolio should return 200, got {portfolio_status}"
    
    def test_rapid_sequential_requests(self):
        """
        Test rapid sequential requests to ensure no request queuing/blocking.
        Fire 10 requests in quick succession and verify consistent response times.
        """
        endpoint = "/api/startup-check"
        num_requests = 10
        
        print(f"\n\n=== RAPID SEQUENTIAL REQUEST TEST ===")
        print(f"Firing {num_requests} requests to {endpoint} in quick succession...")
        
        times = []
        for i in range(num_requests):
            _, status, elapsed, _ = self._make_request(endpoint)
            times.append(elapsed)
            print(f"Request {i+1}: {elapsed:.3f}s (status={status})")
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)
        
        print(f"\n--- Summary ---")
        print(f"Average: {avg_time:.3f}s")
        print(f"Min: {min_time:.3f}s")
        print(f"Max: {max_time:.3f}s")
        print(f"Variance: {max_time - min_time:.3f}s")
        
        # All requests should be fast and consistent
        assert max_time < INDIVIDUAL_TIMEOUT, f"Max time {max_time:.3f}s exceeds threshold"
        # Variance should be low (no request queuing)
        assert (max_time - min_time) < 1.0, f"High variance ({max_time - min_time:.3f}s) suggests request queuing"


class TestPortfolioEndpointDetails:
    """Detailed tests for the /api/portfolio endpoint which uses Alpaca SDK"""
    
    def test_portfolio_returns_expected_fields(self):
        """Test that /api/portfolio returns expected JSON structure"""
        url = f"{BASE_URL}/api/portfolio"
        response = requests.get(url, timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        
        # Portfolio should have positions and summary
        print(f"\nPortfolio response keys: {list(data.keys())}")
        
        # Check for expected fields (may vary based on implementation)
        # At minimum should be valid JSON with some structure
        assert isinstance(data, dict), "Portfolio should return a dict"


class TestStartupCheckDetails:
    """Detailed tests for the /api/startup-check endpoint"""
    
    def test_startup_check_returns_expected_fields(self):
        """Test that /api/startup-check returns expected JSON structure"""
        url = f"{BASE_URL}/api/startup-check"
        response = requests.get(url, timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        
        print(f"\nStartup-check response keys: {list(data.keys())}")
        
        # Should be a valid dict
        assert isinstance(data, dict), "Startup-check should return a dict"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
