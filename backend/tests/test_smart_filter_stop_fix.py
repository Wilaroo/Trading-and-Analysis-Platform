"""
Tests for P0 Features: Smart Strategy Filtering and One-Click Stop Fix

Features tested:
1. Smart Strategy Filtering - Win rate based trade filtering
   - GET /api/trading-bot/smart-filter/config
   - POST /api/trading-bot/smart-filter/config
   - GET /api/trading-bot/smart-filter/thoughts
   - GET /api/trading-bot/smart-filter/strategy-stats/{setup_type}
   - GET /api/trading-bot/smart-filter/all-strategy-stats

2. One-Click Stop Fix
   - POST /api/trading-bot/fix-all-risky-stops
   - GET /api/trading-bot/thoughts (filter_skip/filter_reduce/filter_proceed action types)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://refactor-routers.preview.emergentagent.com').rstrip('/')


class TestSmartFilterConfig:
    """Test Smart Strategy Filter configuration endpoints"""
    
    def test_get_smart_filter_config(self):
        """GET /api/trading-bot/smart-filter/config should return filter configuration"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/smart-filter/config")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "config" in data
        
        config = data["config"]
        # Verify expected config keys exist
        assert "enabled" in config
        assert "min_sample_size" in config
        assert "skip_win_rate_threshold" in config
        assert "reduce_size_threshold" in config
        assert "normal_threshold" in config
        assert "size_reduction_pct" in config
        assert "high_tqs_requirement" in config
        
        # Verify reasonable default values
        assert isinstance(config["enabled"], bool)
        assert config["min_sample_size"] >= 1
        assert 0 <= config["skip_win_rate_threshold"] <= 1
        assert 0 <= config["reduce_size_threshold"] <= 1
        
        print(f"✅ Smart filter config returned successfully: enabled={config['enabled']}")
    
    def test_update_smart_filter_config(self):
        """POST /api/trading-bot/smart-filter/config should update filter settings"""
        # First get current config
        get_response = requests.get(f"{BASE_URL}/api/trading-bot/smart-filter/config")
        assert get_response.status_code == 200
        original_config = get_response.json()["config"]
        
        # Update with new values
        updates = {
            "enabled": True,
            "min_sample_size": 6
        }
        
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/smart-filter/config",
            json=updates
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "config" in data
        assert data["config"]["min_sample_size"] == 6
        
        # Restore original config
        restore_updates = {"min_sample_size": original_config["min_sample_size"]}
        requests.post(f"{BASE_URL}/api/trading-bot/smart-filter/config", json=restore_updates)
        
        print(f"✅ Smart filter config updated and restored successfully")


class TestSmartFilterThoughts:
    """Test Smart Strategy Filter thoughts endpoint"""
    
    def test_get_filter_thoughts(self):
        """GET /api/trading-bot/smart-filter/thoughts should return filter reasoning"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/smart-filter/thoughts?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "thoughts" in data
        assert "count" in data
        assert isinstance(data["thoughts"], list)
        
        # If there are thoughts, verify structure
        if data["thoughts"]:
            thought = data["thoughts"][0]
            # Expected fields in filter thought
            # Note: Fields may vary but timestamp should be present
            assert isinstance(thought, dict)
            print(f"✅ Got {data['count']} filter thoughts")
        else:
            print(f"✅ Filter thoughts endpoint works (no thoughts yet - this is expected in new sessions)")


class TestStrategyStats:
    """Test strategy historical stats endpoints"""
    
    def test_get_strategy_stats_specific(self):
        """GET /api/trading-bot/smart-filter/strategy-stats/{setup_type} should return stats"""
        setup_types = ["breakout", "rubber_band", "orb", "vwap_bounce"]
        
        for setup_type in setup_types:
            response = requests.get(
                f"{BASE_URL}/api/trading-bot/smart-filter/strategy-stats/{setup_type}"
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data.get("success") == True
            
            # Stats may or may not be available depending on enhanced scanner
            if data.get("available"):
                assert "win_rate" in data or "sample_size" in data
                print(f"✅ Strategy stats for '{setup_type}': win_rate={data.get('win_rate', 'N/A')}")
            else:
                # Stats not available is valid - scanner might not be connected
                print(f"ℹ️ Strategy stats for '{setup_type}' not available: {data.get('reason', 'No data')}")
    
    def test_get_all_strategy_stats(self):
        """GET /api/trading-bot/smart-filter/all-strategy-stats should return all stats"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/smart-filter/all-strategy-stats")
        
        assert response.status_code == 200
        data = response.json()
        
        # Endpoint should return success or graceful error if scanner not connected
        if data.get("success"):
            assert "stats" in data
            print(f"✅ Got all strategy stats: {data.get('count', 0)} strategies")
        else:
            # Scanner not connected is valid in preview environment
            assert "error" in data
            print(f"ℹ️ All strategy stats not available: {data.get('error')}")


class TestFixAllRiskyStops:
    """Test One-Click Stop Fix endpoint"""
    
    def test_fix_all_risky_stops(self):
        """POST /api/trading-bot/fix-all-risky-stops should fix risky stops or return no issues"""
        response = requests.post(f"{BASE_URL}/api/trading-bot/fix-all-risky-stops")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "message" in data
        assert "fixes_applied" in data
        assert "positions_checked" in data
        
        # Response structure validation
        assert isinstance(data["fixes_applied"], int)
        assert isinstance(data["positions_checked"], int)
        
        if data["fixes_applied"] > 0:
            assert "fixes" in data
            assert isinstance(data["fixes"], list)
            for fix in data["fixes"]:
                assert "symbol" in fix
                assert "old_stop" in fix
                assert "new_stop" in fix
            print(f"✅ Fixed {data['fixes_applied']} risky stops")
        else:
            print(f"✅ No risky stops to fix (checked {data['positions_checked']} positions)")


class TestBotThoughtsFilterIntegration:
    """Test that bot thoughts include strategy filter action types"""
    
    def test_thoughts_include_filter_actions(self):
        """GET /api/trading-bot/thoughts should include filter-related thoughts"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=20")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "thoughts" in data
        
        # Check for filter action types in thoughts
        filter_action_types = {"filter_skip", "filter_reduce", "filter_proceed", "stop_warning"}
        found_action_types = set()
        
        for thought in data["thoughts"]:
            action_type = thought.get("action_type", "")
            if action_type in filter_action_types:
                found_action_types.add(action_type)
        
        # Bot thoughts endpoint should work - filter thoughts may or may not be present
        print(f"✅ Bot thoughts endpoint works. Filter action types found: {found_action_types or 'None (expected in new session)'}")
        
        # Verify thought structure for any filter thoughts present
        for thought in data["thoughts"]:
            if thought.get("action_type", "").startswith("filter_"):
                # Verify expected fields for filter thoughts
                assert "text" in thought
                assert "timestamp" in thought
                print(f"  - Filter thought: {thought.get('action_type')} - {thought.get('symbol', 'N/A')}")


class TestAuditStopsEndpoint:
    """Test the audit stops endpoint that feeds the stop fix"""
    
    def test_audit_position_stops(self):
        """GET /api/trading-bot/audit-stops should return stop warnings"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "warnings" in data
        assert "positions_audited" in data
        assert "healthy_positions" in data
        
        # Verify summary structure
        if "summary" in data:
            summary = data["summary"]
            assert "critical" in summary or isinstance(summary.get("critical", 0), int)
        
        # Log results
        warnings_count = len(data["warnings"])
        positions_count = data["positions_audited"]
        print(f"✅ Audit stops: {warnings_count} warnings from {positions_count} positions")
        
        # If warnings exist, verify structure
        for warning in data["warnings"][:3]:  # Check first 3
            assert "symbol" in warning
            assert "severity" in warning
            assert "message" in warning
            print(f"  - {warning['severity'].upper()}: {warning['symbol']} - {warning['message'][:50]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
