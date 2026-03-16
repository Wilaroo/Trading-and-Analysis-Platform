"""
Multi-Timeframe Data Collection Backend Tests
==============================================

Tests for the new multi-timeframe data collection and simulation features:
- /api/ib-collector/multi-timeframe-collection endpoint
- /api/ib-collector/collection-presets endpoint
- /api/ib-collector/timeframe-stats endpoint
- /api/simulation/start with bar_size field
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

class TestCollectionPresets:
    """Tests for collection-presets endpoint"""
    
    def test_collection_presets_returns_success(self):
        """Verify collection-presets endpoint returns presets"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/collection-presets")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "presets" in data
        assert isinstance(data["presets"], list)
        assert len(data["presets"]) > 0
    
    def test_collection_presets_structure(self):
        """Verify each preset has required fields"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/collection-presets")
        data = response.json()
        
        required_fields = ["name", "description", "bar_size", "lookback", "collection_type"]
        
        for preset in data["presets"]:
            for field in required_fields:
                assert field in preset, f"Preset missing field: {field}"
    
    def test_collection_presets_contains_scalping(self):
        """Verify Scalping preset exists with 1 min bars"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/collection-presets")
        data = response.json()
        
        scalping_preset = next((p for p in data["presets"] if p["name"] == "Scalping"), None)
        assert scalping_preset is not None
        assert scalping_preset["bar_size"] == "1 min"
        assert scalping_preset["lookback"] == "1_day"
    
    def test_collection_presets_contains_day_trading(self):
        """Verify Day Trading preset exists with 5 mins bars"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/collection-presets")
        data = response.json()
        
        day_trading = next((p for p in data["presets"] if p["name"] == "Day Trading"), None)
        assert day_trading is not None
        assert day_trading["bar_size"] == "5 mins"


class TestTimeframeStats:
    """Tests for timeframe-stats endpoint"""
    
    def test_timeframe_stats_returns_success(self):
        """Verify timeframe-stats endpoint works"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/timeframe-stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
    
    def test_timeframe_stats_structure(self):
        """Verify timeframe stats has expected structure"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/timeframe-stats")
        data = response.json()
        
        assert "by_timeframe" in data
        assert "total" in data
        assert isinstance(data["by_timeframe"], list)
    
    def test_timeframe_stats_total_fields(self):
        """Verify total section has required fields"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/timeframe-stats")
        data = response.json()
        
        total = data.get("total", {})
        assert "unique_symbols" in total
        assert "total_bars" in total
        assert "timeframes_collected" in total


class TestMultiTimeframeCollection:
    """Tests for multi-timeframe-collection endpoint"""
    
    def test_multi_timeframe_collection_invalid_bar_size(self):
        """Verify invalid bar_size returns 400 error"""
        response = requests.post(
            f"{BASE_URL}/api/ib-collector/multi-timeframe-collection",
            params={"bar_size": "invalid", "lookback": "1_week"}
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Invalid bar_size" in data["detail"]
    
    def test_multi_timeframe_collection_invalid_lookback(self):
        """Verify invalid lookback returns 400 error"""
        response = requests.post(
            f"{BASE_URL}/api/ib-collector/multi-timeframe-collection",
            params={"bar_size": "5 mins", "lookback": "invalid"}
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Invalid lookback" in data["detail"]
    
    def test_multi_timeframe_collection_valid_request(self):
        """Verify valid collection request returns success or running message"""
        response = requests.post(
            f"{BASE_URL}/api/ib-collector/multi-timeframe-collection",
            params={
                "bar_size": "1 min",
                "lookback": "1_day",
                "collection_type": "smart"
            }
        )
        # Could return 200 success or 200 with "already running" 
        assert response.status_code == 200
        data = response.json()
        
        # Either successful start or already running is acceptable
        if data.get("success") is False:
            assert "error" in data
            # "Another collection job is already running" is valid
        else:
            assert data.get("success") is True


class TestSimulationBarSize:
    """Tests for simulation endpoints with bar_size support"""
    
    def test_simulation_jobs_returns_success(self):
        """Verify simulation jobs endpoint works"""
        response = requests.get(f"{BASE_URL}/api/simulation/jobs?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "jobs" in data
    
    def test_simulation_jobs_structure(self):
        """Verify simulation jobs have expected structure"""
        response = requests.get(f"{BASE_URL}/api/simulation/jobs?limit=5")
        data = response.json()
        
        jobs = data.get("jobs", [])
        if len(jobs) > 0:
            job = jobs[0]
            assert "id" in job
            assert "config" in job
            assert "status" in job
    
    def test_simulation_quick_test_endpoint(self):
        """Verify quick-test simulation endpoint works"""
        response = requests.post(f"{BASE_URL}/api/simulation/quick-test")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        assert "job_id" in data


class TestDataStatusEndpoint:
    """Tests for data-status endpoint"""
    
    def test_data_status_returns_success(self):
        """Verify data-status endpoint works"""
        response = requests.get(
            f"{BASE_URL}/api/ib-collector/data-status",
            params={"bar_size": "1 day"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
    
    def test_data_status_structure(self):
        """Verify data-status has expected fields"""
        response = requests.get(
            f"{BASE_URL}/api/ib-collector/data-status",
            params={"bar_size": "5 mins"}
        )
        data = response.json()
        
        assert "bar_size" in data
        assert "symbols_with_recent_data" in data
        assert "default_symbols_count" in data


class TestIBCollectorStats:
    """Tests for IB collector stats endpoint"""
    
    def test_stats_returns_success(self):
        """Verify stats endpoint works"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/stats")
        assert response.status_code == 200
        
        data = response.json()
        # stats endpoint returns data directly without success flag
        assert isinstance(data, dict)
    
    def test_queue_progress_endpoint(self):
        """Verify queue-progress endpoint works"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/queue-progress")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
