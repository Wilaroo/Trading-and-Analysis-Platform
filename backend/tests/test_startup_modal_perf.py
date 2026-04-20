"""
Test Suite: StartupModal Performance Fix
=========================================
Tests the fixes for:
1. /api/startup-check endpoint - should respond in <1 second (target ~100-300ms)
2. /api/health endpoint - should respond in <1 second (was 6-47 seconds before fix)
3. /api/ib-collector/fill-gaps - should return without hanging (was hanging indefinitely)

Root cause was:
- Alpaca SDK sync HTTP calls blocking asyncio event loop
- Individual service health checks taking 6-47 seconds each
- fill-gaps endpoint using sync pymongo calls blocking event loop

Fix applied:
- Single /api/startup-check endpoint using only in-memory state
- asyncio.to_thread() wrapping for sync SDK/DB calls
"""

import pytest
import requests
import os
import time
from datetime import datetime

# Get backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://xgb-triple-barrier.preview.emergentagent.com"


class TestStartupCheckEndpoint:
    """Tests for /api/startup-check endpoint performance and structure"""
    
    def test_startup_check_responds_quickly(self):
        """Test that /api/startup-check responds in under 1 second"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 1.0, f"Response took {elapsed:.2f}s, expected <1s"
        print(f"✓ /api/startup-check responded in {elapsed*1000:.0f}ms")
    
    def test_startup_check_response_structure(self):
        """Test that /api/startup-check returns correct JSON structure"""
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        
        # Required fields per the fix
        required_fields = ['backend', 'database', 'websocket', 'ib', 'ollama', 'timeseries', 'scanner', 'learning', 'timestamp']
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
            print(f"  ✓ Field '{field}' present: {data[field]}")
        
        # Backend, database, websocket should be True (core systems)
        assert data['backend'] == True, "Backend should be True"
        assert data['database'] == True, "Database should be True"
        assert data['websocket'] == True, "WebSocket should be True"
        
        # IB and Ollama expected to be False in preview environment
        # (per the review request: "IB Gateway and Ollama are not available")
        print(f"  ✓ IB connected: {data['ib']} (expected False in preview)")
        print(f"  ✓ Ollama available: {data['ollama']} (expected False in preview)")
        
        print(f"✓ /api/startup-check structure validated")
    
    def test_startup_check_rapid_sequential_calls(self):
        """Test 5-10 rapid sequential calls to ensure consistent fast response"""
        times = []
        
        for i in range(10):
            start = time.time()
            response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
            elapsed = time.time() - start
            times.append(elapsed)
            
            assert response.status_code == 200, f"Call {i+1} failed with status {response.status_code}"
            assert elapsed < 1.0, f"Call {i+1} took {elapsed:.2f}s, expected <1s"
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)
        
        print(f"✓ 10 rapid calls completed:")
        print(f"  - Average: {avg_time*1000:.0f}ms")
        print(f"  - Min: {min_time*1000:.0f}ms")
        print(f"  - Max: {max_time*1000:.0f}ms")
        
        # All calls should be under 1 second
        assert max_time < 1.0, f"Max response time {max_time:.2f}s exceeds 1s threshold"


class TestHealthEndpoint:
    """Tests for /api/health endpoint performance"""
    
    def test_health_responds_quickly(self):
        """Test that /api/health responds in under 1 second (was 6-47s before fix)"""
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert elapsed < 1.0, f"Response took {elapsed:.2f}s, expected <1s (was 6-47s before fix)"
        
        data = response.json()
        assert data.get('status') == 'healthy', f"Expected status 'healthy', got {data.get('status')}"
        
        print(f"✓ /api/health responded in {elapsed*1000:.0f}ms with status: {data.get('status')}")
    
    def test_health_multiple_calls(self):
        """Test multiple health calls to ensure consistent performance"""
        times = []
        
        for i in range(5):
            start = time.time()
            response = requests.get(f"{BASE_URL}/api/health", timeout=5)
            elapsed = time.time() - start
            times.append(elapsed)
            
            assert response.status_code == 200
            assert elapsed < 1.0, f"Call {i+1} took {elapsed:.2f}s"
        
        avg_time = sum(times) / len(times)
        print(f"✓ 5 health calls - Average: {avg_time*1000:.0f}ms, Max: {max(times)*1000:.0f}ms")


class TestFillGapsEndpoint:
    """Tests for /api/ib-collector/fill-gaps endpoint"""
    
    def test_fill_gaps_returns_without_hanging(self):
        """
        Test that /api/ib-collector/fill-gaps returns without hanging.
        
        Previously this endpoint hung indefinitely due to sync pymongo calls
        blocking the event loop. Now uses asyncio.to_thread() for DB operations.
        
        Note: This endpoint processes 442 symbols and creates 1392 queue entries,
        so it takes 20-30 seconds - this is expected behavior, not a hang.
        The key is that it RETURNS rather than hanging indefinitely.
        """
        print("Testing /api/ib-collector/fill-gaps (may take 20-60s)...")
        
        start = time.time()
        try:
            # Use 60s timeout as per the review request note
            response = requests.post(f"{BASE_URL}/api/ib-collector/fill-gaps", timeout=60)
            elapsed = time.time() - start
            
            # Should return a response (not hang)
            assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}"
            
            data = response.json()
            
            # Check response structure
            assert 'success' in data, "Response should have 'success' field"
            
            if data.get('success'):
                print(f"✓ /api/ib-collector/fill-gaps returned in {elapsed:.1f}s")
                print(f"  - Message: {data.get('message', 'N/A')}")
                print(f"  - Gaps found: {data.get('gaps_found', 'N/A')}")
                print(f"  - Total symbols: {data.get('total_unique_symbols', 'N/A')}")
            else:
                # Even if it fails, it should return quickly with an error
                print(f"✓ /api/ib-collector/fill-gaps returned error in {elapsed:.1f}s")
                print(f"  - Error: {data.get('error', data.get('message', 'Unknown'))}")
            
            # Key assertion: it should return within 60 seconds, not hang
            assert elapsed < 60, f"Endpoint took {elapsed:.1f}s, may be hanging"
            
        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            pytest.fail(f"fill-gaps endpoint timed out after {elapsed:.1f}s - may still be hanging")
        except requests.exceptions.ConnectionError as e:
            pytest.fail(f"Connection error: {e}")


class TestCoreSystemsReady:
    """Test that core systems are ready for the StartupModal"""
    
    def test_core_systems_green(self):
        """Test that Backend, WebSocket, Database show as ready"""
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        
        # Core systems should all be True
        assert data['backend'] == True, "Backend should be ready"
        assert data['database'] == True, "Database should be ready"
        assert data['websocket'] == True, "WebSocket should be ready"
        
        print("✓ Core systems (Backend, Database, WebSocket) all ready")
    
    def test_optional_services_status(self):
        """Test that optional services return valid status (True/False)"""
        response = requests.get(f"{BASE_URL}/api/startup-check", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        
        # Optional services should be boolean
        optional_services = ['ib', 'ollama', 'timeseries', 'scanner', 'learning']
        
        for service in optional_services:
            assert isinstance(data[service], bool), f"{service} should be boolean, got {type(data[service])}"
            status = "Ready" if data[service] else "Unavailable"
            print(f"  - {service}: {status}")
        
        print("✓ All optional services return valid boolean status")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
