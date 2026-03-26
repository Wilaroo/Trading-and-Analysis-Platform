"""
P2/P3 Feature Tests - Data Heatmap, WebSocket Migration, Smart Filter Extraction
================================================================================
Tests for:
- P2: Data coverage heatmap (GET /api/ib-collector/data-coverage returns by_tier with timeframes)
- P3: WebSocket push types (confidence_gate, training_status, market_regime)
- P3: Smart filter extraction (smart_filter.py exists with SmartFilter class)
- Backend API endpoints for NIA panels
"""

import pytest
import requests
import os
import sys

# Add backend to path for imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestDataCoverageHeatmap:
    """P2: Data coverage heatmap endpoint tests"""
    
    def test_data_coverage_endpoint_returns_success(self):
        """GET /api/ib-collector/data-coverage should return success"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/data-coverage")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
    
    def test_data_coverage_has_by_tier(self):
        """Data coverage should have by_tier array for heatmap rows"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/data-coverage")
        assert response.status_code == 200
        data = response.json()
        assert "by_tier" in data, f"Missing by_tier in response: {data.keys()}"
        assert isinstance(data["by_tier"], list), f"by_tier should be list, got {type(data['by_tier'])}"
    
    def test_data_coverage_tiers_have_timeframes(self):
        """Each tier should have timeframes array for heatmap columns"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/data-coverage")
        assert response.status_code == 200
        data = response.json()
        
        by_tier = data.get("by_tier", [])
        if len(by_tier) > 0:
            for tier in by_tier:
                assert "tier" in tier, f"Tier missing 'tier' field: {tier}"
                assert "timeframes" in tier, f"Tier missing 'timeframes' field: {tier}"
                assert isinstance(tier["timeframes"], list), f"timeframes should be list"
                
                # Each timeframe should have coverage_pct for cell coloring
                for tf in tier["timeframes"]:
                    assert "timeframe" in tf, f"Timeframe missing 'timeframe' field: {tf}"
                    assert "coverage_pct" in tf, f"Timeframe missing 'coverage_pct' field: {tf}"
    
    def test_data_coverage_has_expected_tiers(self):
        """Should have intraday, swing, investment tiers"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/data-coverage")
        assert response.status_code == 200
        data = response.json()
        
        by_tier = data.get("by_tier", [])
        tier_names = [t.get("tier") for t in by_tier]
        
        # At least one tier should exist
        if len(tier_names) > 0:
            expected_tiers = ["intraday", "swing", "investment"]
            for expected in expected_tiers:
                assert expected in tier_names, f"Missing tier '{expected}' in {tier_names}"


class TestConfidenceGateEndpoints:
    """Backend: Confidence gate API endpoints"""
    
    def test_confidence_gate_summary(self):
        """GET /api/ai-training/confidence-gate/summary should return trading mode and stats"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "trading_mode" in data, f"Missing trading_mode in {data.keys()}"
        assert "today" in data, f"Missing today stats in {data.keys()}"
    
    def test_confidence_gate_decisions(self):
        """GET /api/ai-training/confidence-gate/decisions should return decision list"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "decisions" in data, f"Missing decisions in {data.keys()}"
        assert isinstance(data["decisions"], list), f"decisions should be list"
    
    def test_confidence_gate_evaluate(self):
        """POST /api/ai-training/confidence-gate/evaluate should return decision with reasoning"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "MSFT", "setup_type": "momentum", "direction": "long"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "decision" in data, f"Missing decision in {data.keys()}"
        assert "reasoning" in data, f"Missing reasoning in {data.keys()}"
        assert data["decision"] in ["GO", "REDUCE", "SKIP"], f"Invalid decision: {data['decision']}"


class TestRegimeAndTrainingEndpoints:
    """Backend: Regime and training status endpoints (used by WS streams)"""
    
    def test_regime_live_endpoint(self):
        """GET /api/ai-training/regime-live should return regime data"""
        response = requests.get(f"{BASE_URL}/api/ai-training/regime-live")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "regime" in data, f"Missing regime in {data.keys()}"
    
    def test_model_inventory_endpoint(self):
        """GET /api/ai-training/model-inventory should return categories"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "categories" in data, f"Missing categories in {data.keys()}"
    
    def test_training_status_endpoint(self):
        """GET /api/ai-training/status should return pipeline status"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"


class TestSmartFilterExtraction:
    """P3: Verify smart_filter.py was extracted from trading_bot_service.py"""
    
    def test_smart_filter_file_exists(self):
        """smart_filter.py should exist at /app/backend/services/smart_filter.py"""
        import os
        path = "/app/backend/services/smart_filter.py"
        assert os.path.exists(path), f"smart_filter.py not found at {path}"
    
    def test_smart_filter_has_class(self):
        """smart_filter.py should have SmartFilter class"""
        from services.smart_filter import SmartFilter
        assert SmartFilter is not None, "SmartFilter class not found"
    
    def test_smart_filter_has_evaluate_method(self):
        """SmartFilter should have evaluate method"""
        from services.smart_filter import SmartFilter
        sf = SmartFilter()
        assert hasattr(sf, 'evaluate'), "SmartFilter missing evaluate method"
    
    def test_smart_filter_has_config(self):
        """SmartFilter should have config property"""
        from services.smart_filter import SmartFilter
        sf = SmartFilter()
        config = sf.config
        assert isinstance(config, dict), f"config should be dict, got {type(config)}"
        assert "enabled" in config, "config missing 'enabled' key"
        assert "min_sample_size" in config, "config missing 'min_sample_size' key"
    
    def test_smart_filter_evaluate_returns_action(self):
        """SmartFilter.evaluate should return action dict"""
        from services.smart_filter import SmartFilter
        sf = SmartFilter()
        
        # Test with no historical data
        result = sf.evaluate(
            setup_type="breakout",
            quality_score=75,
            symbol="TEST",
            stats={"available": False}
        )
        
        assert isinstance(result, dict), f"evaluate should return dict, got {type(result)}"
        assert "action" in result, f"result missing 'action' key: {result}"
        assert result["action"] in ["PROCEED", "REDUCE_SIZE", "SKIP"], f"Invalid action: {result['action']}"
    
    def test_smart_filter_cold_start_bootstrap(self):
        """SmartFilter should handle cold-start (0W/0L) with REDUCE_SIZE"""
        from services.smart_filter import SmartFilter
        sf = SmartFilter()
        
        # Cold-start: sample_size >= min but wins+losses == 0
        result = sf.evaluate(
            setup_type="momentum",
            quality_score=80,
            symbol="COLD",
            stats={
                "available": True,
                "sample_size": 10,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "expected_value": 0
            }
        )
        
        assert result["action"] == "REDUCE_SIZE", f"Cold-start should return REDUCE_SIZE, got {result['action']}"
        assert result.get("bootstrap") == True, f"Cold-start should have bootstrap=True"
        assert result.get("adjustment_pct") == 0.5, f"Cold-start should have 50% adjustment"


class TestWebSocketStreamRegistration:
    """P3: Verify WebSocket streams are registered in server startup"""
    
    def test_server_has_stream_confidence_gate(self):
        """server.py should have stream_confidence_gate function"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("server", "/app/backend/server.py")
        # Just check the file contains the function definition
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        assert "async def stream_confidence_gate" in content, "Missing stream_confidence_gate function"
    
    def test_server_has_stream_training_status(self):
        """server.py should have stream_training_status function"""
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        assert "async def stream_training_status" in content, "Missing stream_training_status function"
    
    def test_server_has_stream_market_regime(self):
        """server.py should have stream_market_regime function"""
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        assert "async def stream_market_regime" in content, "Missing stream_market_regime function"
    
    def test_startup_registers_new_streams(self):
        """startup_event should register all 3 new WS streams"""
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        
        # Check that startup event creates tasks for new streams
        assert "asyncio.create_task(stream_confidence_gate())" in content, "stream_confidence_gate not registered in startup"
        assert "asyncio.create_task(stream_training_status())" in content, "stream_training_status not registered in startup"
        assert "asyncio.create_task(stream_market_regime())" in content, "stream_market_regime not registered in startup"
    
    def test_startup_log_mentions_new_streams(self):
        """startup_event print should mention new streams"""
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        
        # The print statement should mention the new streams
        assert "confidence gate" in content.lower() or "confidence_gate" in content, "startup log should mention confidence gate"


class TestNIAPanelEndpoints:
    """Backend endpoints used by NIA panels"""
    
    def test_ib_collector_stats(self):
        """GET /api/ib-collector/stats should return collection stats"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
    
    def test_ib_collector_queue_progress(self):
        """GET /api/ib-collector/queue-progress should return queue status"""
        response = requests.get(f"{BASE_URL}/api/ib-collector/queue-progress")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
    
    def test_simulation_jobs(self):
        """GET /api/simulation/jobs should return job list"""
        response = requests.get(f"{BASE_URL}/api/simulation/jobs", params={"limit": 10})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
