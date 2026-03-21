"""
Test Regime Performance API Endpoints
=====================================
Tests all regime performance API endpoints work correctly.
This file focuses on integration/API testing vs unit tests in test_regime_performance.py
"""
import pytest
import requests
import os

# Get API URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://sentcom-ai-forge.preview.emergentagent.com').rstrip('/')


class TestRegimePerformanceEndpoints:
    """Test all /api/regime-performance/* endpoints"""

    def test_summary_endpoint_returns_success(self):
        """Test /api/regime-performance/summary endpoint"""
        response = requests.get(f"{BASE_URL}/api/regime-performance/summary", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        assert "regimes" in data
        assert "total_trades" in data
        assert "generated_at" in data

    def test_strategies_endpoint_returns_success(self):
        """Test /api/regime-performance/strategies endpoint"""
        response = requests.get(f"{BASE_URL}/api/regime-performance/strategies", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        assert "count" in data
        assert "performance" in data
        assert isinstance(data["performance"], list)

    def test_strategies_endpoint_with_filters(self):
        """Test /api/regime-performance/strategies with filter parameters"""
        # Test with strategy_name filter
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/strategies",
            params={"strategy_name": "orb"},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True

        # Test with market_regime filter
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/strategies",
            params={"market_regime": "RISK_ON"},
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True

    def test_best_for_regime_risk_on(self):
        """Test /api/regime-performance/best-for-regime/RISK_ON endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/RISK_ON",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("regime") == "RISK_ON"
        assert "count" in data
        assert "best_strategies" in data
        assert isinstance(data["best_strategies"], list)

    def test_best_for_regime_caution(self):
        """Test /api/regime-performance/best-for-regime/CAUTION endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/CAUTION",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("regime") == "CAUTION"

    def test_best_for_regime_risk_off(self):
        """Test /api/regime-performance/best-for-regime/RISK_OFF endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/RISK_OFF",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("regime") == "RISK_OFF"

    def test_best_for_regime_confirmed_down(self):
        """Test /api/regime-performance/best-for-regime/CONFIRMED_DOWN endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/CONFIRMED_DOWN",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("regime") == "CONFIRMED_DOWN"

    def test_best_for_regime_invalid_regime_returns_400(self):
        """Test /api/regime-performance/best-for-regime with invalid regime returns 400"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/INVALID_REGIME",
            timeout=10
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    def test_best_for_regime_with_params(self):
        """Test /api/regime-performance/best-for-regime with query parameters"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/best-for-regime/RISK_ON",
            params={"min_trades": 1, "sort_by": "win_rate"},
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True

    def test_position_sizing_impact_endpoint(self):
        """Test /api/regime-performance/position-sizing-impact endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/position-sizing-impact",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "full_size_trades" in data
        assert "reduced_size_trades" in data
        assert "impact_summary" in data
        assert "generated_at" in data

    def test_recommendations_endpoint(self):
        """Test /api/regime-performance/recommendations endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/regime-performance/recommendations",
            timeout=10
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "recommendations" in data
        
        recommendations = data["recommendations"]
        # Verify all regimes are included
        expected_regimes = ["RISK_ON", "CAUTION", "RISK_OFF", "CONFIRMED_DOWN"]
        for regime in expected_regimes:
            assert regime in recommendations, f"Missing {regime} in recommendations"
            assert "top_strategies" in recommendations[regime]
            assert "suggested_position_size" in recommendations[regime]
            assert "notes" in recommendations[regime]


class TestMarketRegimeEndpoint:
    """Test /api/market-regime/* endpoints"""

    def test_current_regime_endpoint(self):
        """Test /api/market-regime/current returns current market regime state"""
        response = requests.get(f"{BASE_URL}/api/market-regime/current", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        # Verify required fields in market regime response
        assert "state" in data
        assert data["state"] in ["RISK_ON", "CAUTION", "RISK_OFF", "CONFIRMED_DOWN", "HOLD"]
        assert "composite_score" in data
        assert "risk_level" in data
        assert "confidence" in data
        assert "signal_blocks" in data
        assert "recommendation" in data
        assert "trading_implications" in data
        assert "last_updated" in data

    def test_current_regime_trading_implications(self):
        """Test /api/market-regime/current returns correct trading implications"""
        response = requests.get(f"{BASE_URL}/api/market-regime/current", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        implications = data.get("trading_implications", {})
        
        # Verify trading implications structure
        assert "position_sizing" in implications
        assert "favored_strategies" in implications
        assert "avoid_strategies" in implications
        assert "sector_focus" in implications
        assert "risk_tolerance" in implications

    def test_current_regime_signal_blocks(self):
        """Test /api/market-regime/current returns signal blocks"""
        response = requests.get(f"{BASE_URL}/api/market-regime/current", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        signal_blocks = data.get("signal_blocks", {})
        
        # Verify expected signal blocks exist
        expected_blocks = ["trend", "breadth", "ftd", "volume_vix"]
        for block in expected_blocks:
            assert block in signal_blocks, f"Missing signal block: {block}"
            block_data = signal_blocks[block]
            assert "name" in block_data
            assert "weight" in block_data
            assert "score" in block_data


class TestRegimePerformanceDataIntegrity:
    """Test data integrity for regime performance"""

    def test_performance_data_structure(self):
        """Test that performance data has correct structure"""
        response = requests.get(f"{BASE_URL}/api/regime-performance/strategies", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        if data["count"] > 0:
            # Verify structure of performance record
            perf = data["performance"][0]
            required_fields = [
                "strategy_name", "market_regime", "total_trades", 
                "winning_trades", "losing_trades", "total_pnl",
                "win_rate", "expectancy"
            ]
            for field in required_fields:
                assert field in perf, f"Missing field: {field}"

    def test_summary_aggregates_correctly(self):
        """Test that summary aggregates trades correctly"""
        response = requests.get(f"{BASE_URL}/api/regime-performance/summary", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        
        # Total trades should be sum of all regime trades
        total_from_regimes = sum(
            regime_data.get("total_trades", 0) 
            for regime_data in data.get("regimes", {}).values()
        )
        assert data["total_trades"] == total_from_regimes


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
