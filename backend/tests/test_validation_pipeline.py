"""
Test Suite for 5-Phase Auto-Validation Pipeline

Tests:
- Validation API endpoints (latest, history, batch-history, baselines)
- Setup models status endpoint (10 setup types with profiles)
- Post-training validator module imports and configuration
- Promotion decision logic
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ─── Validation API Endpoints ─────────────────────────────────────────────────

class TestValidationEndpoints:
    """Test validation API endpoints return correct structure"""
    
    def test_validation_latest_returns_success(self):
        """GET /api/ai-modules/validation/latest returns {success: true, validations: {}}"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/validation/latest", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=true, got {data}"
        assert "validations" in data, f"Missing 'validations' key in response: {data}"
        assert isinstance(data["validations"], dict), f"validations should be dict, got {type(data['validations'])}"
        print(f"✓ /validation/latest: success=true, {len(data['validations'])} validations")
    
    def test_validation_history_returns_success(self):
        """GET /api/ai-modules/validation/history returns {success: true, records: []}"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/validation/history", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=true, got {data}"
        assert "records" in data, f"Missing 'records' key in response: {data}"
        assert isinstance(data["records"], list), f"records should be list, got {type(data['records'])}"
        print(f"✓ /validation/history: success=true, {len(data['records'])} records")
    
    def test_validation_batch_history_returns_success(self):
        """GET /api/ai-modules/validation/batch-history returns {success: true, records: []}"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/validation/batch-history", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=true, got {data}"
        assert "records" in data, f"Missing 'records' key in response: {data}"
        assert isinstance(data["records"], list), f"records should be list, got {type(data['records'])}"
        print(f"✓ /validation/batch-history: success=true, {len(data['records'])} records")
    
    def test_validation_baselines_returns_success(self):
        """GET /api/ai-modules/validation/baselines returns {success: true, baselines: []}"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/validation/baselines", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=true, got {data}"
        assert "baselines" in data, f"Missing 'baselines' key in response: {data}"
        assert isinstance(data["baselines"], list), f"baselines should be list, got {type(data['baselines'])}"
        print(f"✓ /validation/baselines: success=true, {len(data['baselines'])} baselines")


# ─── Setup Models Status Endpoint ─────────────────────────────────────────────

class TestSetupModelsStatus:
    """Test setup models status endpoint returns 10 setup types with profiles"""
    
    EXPECTED_SETUP_TYPES = [
        "MOMENTUM", "SCALP", "BREAKOUT", "GAP_AND_GO", "RANGE",
        "REVERSAL", "TREND_CONTINUATION", "ORB", "VWAP", "MEAN_REVERSION"
    ]
    
    def test_setups_status_returns_10_types(self):
        """GET /api/ai-modules/timeseries/setups/status returns 10 setup types with profiles"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/setups/status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=true, got {data}"
        assert "models" in data, f"Missing 'models' key in response: {data}"
        
        models = data["models"]
        assert isinstance(models, dict), f"models should be dict, got {type(models)}"
        
        # Check we have all 10 setup types
        for setup_type in self.EXPECTED_SETUP_TYPES:
            assert setup_type in models, f"Missing setup type: {setup_type}"
            model_data = models[setup_type]
            
            # Each setup should have profiles
            assert "profiles" in model_data, f"{setup_type} missing 'profiles'"
            assert isinstance(model_data["profiles"], list), f"{setup_type} profiles should be list"
            assert len(model_data["profiles"]) > 0, f"{setup_type} should have at least 1 profile"
            
            # Check profile structure
            for profile in model_data["profiles"]:
                assert "bar_size" in profile, f"{setup_type} profile missing 'bar_size'"
        
        print(f"✓ /setups/status: {len(models)} setup types with profiles")
        for st in self.EXPECTED_SETUP_TYPES:
            profile_count = len(models[st]["profiles"])
            trained = models[st].get("profiles_trained", 0)
            print(f"  - {st}: {profile_count} profiles, {trained} trained")
    
    def test_setups_status_has_training_info(self):
        """Setup status includes training counts and totals"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/setups/status", timeout=30)
        data = response.json()
        
        # Check top-level training info
        assert "models_trained" in data, "Missing 'models_trained' count"
        assert "total_profiles" in data, "Missing 'total_profiles' count"
        
        print(f"✓ Training info: {data.get('models_trained', 0)}/{data.get('total_profiles', 0)} profiles trained")


# ─── Post-Training Validator Module ───────────────────────────────────────────

class TestPostTrainingValidator:
    """Test post_training_validator module imports and configuration"""
    
    def test_validator_imports_correctly(self):
        """Backend post_training_validator imports correctly with VALIDATION_CONFIG and PROMOTION_CRITERIA"""
        import sys
        sys.path.insert(0, '/app/backend')
        
        from services.ai_modules.post_training_validator import (
            VALIDATION_CONFIG, PROMOTION_CRITERIA
        )
        
        # Check VALIDATION_CONFIG has expected keys
        assert "num_symbols" in VALIDATION_CONFIG, "Missing num_symbols in VALIDATION_CONFIG"
        assert "mc_simulations" in VALIDATION_CONFIG, "Missing mc_simulations in VALIDATION_CONFIG"
        assert "wf_total_days" in VALIDATION_CONFIG, "Missing wf_total_days in VALIDATION_CONFIG"
        assert "mw_max_symbols" in VALIDATION_CONFIG, "Missing mw_max_symbols in VALIDATION_CONFIG"
        
        print(f"✓ VALIDATION_CONFIG: {list(VALIDATION_CONFIG.keys())}")
        
        # Check PROMOTION_CRITERIA has expected keys
        assert "min_trades" in PROMOTION_CRITERIA, "Missing min_trades in PROMOTION_CRITERIA"
        assert "min_win_rate" in PROMOTION_CRITERIA, "Missing min_win_rate in PROMOTION_CRITERIA"
        assert "min_sharpe" in PROMOTION_CRITERIA, "Missing min_sharpe in PROMOTION_CRITERIA"
        assert "max_mc_risk" in PROMOTION_CRITERIA, "Missing max_mc_risk in PROMOTION_CRITERIA"
        assert "min_wf_efficiency" in PROMOTION_CRITERIA, "Missing min_wf_efficiency in PROMOTION_CRITERIA"
        
        print(f"✓ PROMOTION_CRITERIA: {PROMOTION_CRITERIA}")
    
    def test_promotion_decision_no_baseline(self):
        """_make_promotion_decision correctly promotes when no baseline exists"""
        import sys
        sys.path.insert(0, '/app/backend')
        
        from services.ai_modules.post_training_validator import _make_promotion_decision
        
        # Simulate AI comparison result with good metrics
        ai_cmp = {
            "ai_filtered_trades": 50,
            "ai_filtered_win_rate": 55.0,  # 55% win rate
            "ai_filtered_sharpe": 1.2,
            "ai_filtered_pnl": 5000,
            "ai_edge_pnl": 1000,
        }
        
        # Monte Carlo with acceptable risk
        mc = {
            "risk_assessment": "MEDIUM",
            "probability_of_profit": 65,
            "worst_case_drawdown": 25,
        }
        
        # Walk-forward with good efficiency
        wf = {
            "avg_efficiency_ratio": 75,
            "is_robust": True,
        }
        
        # No baseline (first model)
        baseline = None
        
        decision = _make_promotion_decision(ai_cmp, mc, wf, baseline)
        
        assert decision["promote"] is True, f"Expected promote=True for first model, got {decision}"
        assert "First model" in decision["reason"] or "no baseline" in decision["reason"].lower(), \
            f"Expected 'First model' or 'no baseline' in reason, got: {decision['reason']}"
        
        print(f"✓ No baseline → promote=True: {decision['reason']}")
    
    def test_promotion_decision_extreme_risk_rejects(self):
        """_make_promotion_decision correctly rejects when Monte Carlo risk is EXTREME"""
        import sys
        sys.path.insert(0, '/app/backend')
        
        from services.ai_modules.post_training_validator import _make_promotion_decision
        
        # Good AI comparison
        ai_cmp = {
            "ai_filtered_trades": 50,
            "ai_filtered_win_rate": 55.0,
            "ai_filtered_sharpe": 1.2,
        }
        
        # EXTREME risk from Monte Carlo
        mc = {
            "risk_assessment": "EXTREME",
            "probability_of_profit": 30,
            "worst_case_drawdown": 60,
        }
        
        # Good walk-forward
        wf = {
            "avg_efficiency_ratio": 75,
            "is_robust": True,
        }
        
        baseline = None
        
        decision = _make_promotion_decision(ai_cmp, mc, wf, baseline)
        
        assert decision["promote"] is False, f"Expected promote=False for EXTREME risk, got {decision}"
        assert "EXTREME" in decision["reason"], f"Expected 'EXTREME' in reason, got: {decision['reason']}"
        
        print(f"✓ EXTREME risk → promote=False: {decision['reason']}")
    
    def test_promotion_decision_low_win_rate_rejects(self):
        """_make_promotion_decision rejects when win rate is below minimum"""
        import sys
        sys.path.insert(0, '/app/backend')
        
        from services.ai_modules.post_training_validator import _make_promotion_decision, PROMOTION_CRITERIA
        
        # Low win rate (below 35% threshold)
        ai_cmp = {
            "ai_filtered_trades": 50,
            "ai_filtered_win_rate": 30.0,  # 30% < 35% minimum
            "ai_filtered_sharpe": 0.5,
        }
        
        mc = {"risk_assessment": "LOW"}
        wf = {"avg_efficiency_ratio": 80}
        baseline = None
        
        decision = _make_promotion_decision(ai_cmp, mc, wf, baseline)
        
        min_wr = PROMOTION_CRITERIA["min_win_rate"] * 100
        assert decision["promote"] is False, f"Expected promote=False for low win rate, got {decision}"
        assert "Win rate" in decision["reason"] or "win rate" in decision["reason"].lower(), \
            f"Expected win rate mentioned in reason, got: {decision['reason']}"
        
        print(f"✓ Low win rate (30% < {min_wr}%) → promote=False: {decision['reason']}")


# ─── Validation Record Structure ──────────────────────────────────────────────

class TestValidationRecordStructure:
    """Test validation records have expected structure when data exists"""
    
    def test_validation_record_has_phases(self):
        """Validation records include phase data (ai_comparison, monte_carlo, walk_forward)"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/validation/history?limit=5", timeout=30)
        data = response.json()
        
        if not data.get("records"):
            pytest.skip("No validation records exist yet - models not trained")
        
        record = data["records"][0]
        
        # Check expected fields
        expected_fields = [
            "validation_id", "setup_type", "bar_size", "status", "reason",
            "ai_comparison", "monte_carlo", "walk_forward",
            "phases_passed", "phases_total", "validated_at"
        ]
        
        for field in expected_fields:
            assert field in record, f"Missing field '{field}' in validation record"
        
        print(f"✓ Validation record has all expected fields")
        print(f"  - Status: {record.get('status')}")
        print(f"  - Phases: {record.get('phases_passed')}/{record.get('phases_total')}")
        print(f"  - Reason: {record.get('reason', '')[:80]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
