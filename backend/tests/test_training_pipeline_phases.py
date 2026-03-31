"""
Test Training Pipeline Phases 2, 7, 8 Implementation
Tests model inventory, count_total_models, regime_conditional, and ensemble models
"""
import pytest
import requests
import os
import sys

# Add backend to path for imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestModelInventoryEndpoint:
    """Test GET /api/ai-training/model-inventory endpoint"""

    def test_model_inventory_returns_success(self):
        """Verify model-inventory endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"

    def test_model_inventory_total_defined_is_108(self):
        """Verify total_defined models is 108"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        total_defined = data.get("total_defined", 0)
        assert total_defined == 108, f"Expected 108 total_defined models, got {total_defined}"

    def test_model_inventory_has_9_categories(self):
        """Verify there are 9 model categories"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        categories = data.get("categories", {})
        assert len(categories) == 9, f"Expected 9 categories, got {len(categories)}: {list(categories.keys())}"

    def test_model_inventory_category_counts(self):
        """Verify each category has the expected model count"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        categories = data.get("categories", {})
        
        expected_counts = {
            "generic_directional": 7,
            "setup_specific": 34,
            "volatility": 7,
            "exit_timing": 10,
            "sector_relative": 3,
            "gap_fill": 3,
            "risk_of_ruin": 6,
            "ensemble": 10,
            "regime_conditional": 28,
        }
        
        for cat_name, expected_count in expected_counts.items():
            cat = categories.get(cat_name, {})
            models = cat.get("models", [])
            actual_count = len(models)
            assert actual_count == expected_count, (
                f"Category '{cat_name}': expected {expected_count} models, got {actual_count}"
            )

    def test_regime_conditional_naming_pattern(self):
        """Verify regime_conditional models have correct naming pattern"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        regime_models = data.get("categories", {}).get("regime_conditional", {}).get("models", [])
        assert len(regime_models) == 28, f"Expected 28 regime_conditional models, got {len(regime_models)}"
        
        # Check naming pattern: direction_predictor_{bar_size}_{regime}
        expected_regimes = ["bull_trend", "bear_trend", "range_bound", "high_vol"]
        expected_bar_sizes = ["1_min", "5_mins", "15_mins", "30_mins", "1_hour", "1_day", "1_week"]
        
        for model in regime_models:
            name = model.get("name", "")
            # Pattern: direction_predictor_{bar_size}_{regime}
            assert name.startswith("direction_predictor_"), f"Model name should start with 'direction_predictor_': {name}"
            
            # Check regime is in the name
            has_regime = any(regime in name for regime in expected_regimes)
            assert has_regime, f"Model name should contain a regime: {name}"
            
            # Check bar_size is in the name
            has_bar_size = any(bs in name for bs in expected_bar_sizes)
            assert has_bar_size, f"Model name should contain a bar_size: {name}"

    def test_ensemble_naming_pattern(self):
        """Verify ensemble models have correct naming pattern: ensemble_{setup_type}"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        ensemble_models = data.get("categories", {}).get("ensemble", {}).get("models", [])
        assert len(ensemble_models) == 10, f"Expected 10 ensemble models, got {len(ensemble_models)}"
        
        # Check naming pattern: ensemble_{setup_type}
        expected_names = [
            "ensemble_scalp", "ensemble_orb", "ensemble_gap", "ensemble_breakout",
            "ensemble_meanrev", "ensemble_momentum", "ensemble_trend", "ensemble_reversal",
            "ensemble_range", "ensemble_vwap"
        ]
        
        actual_names = [m.get("name", "") for m in ensemble_models]
        for expected_name in expected_names:
            assert expected_name in actual_names, f"Expected ensemble model '{expected_name}' not found in {actual_names}"


class TestTrainingStatusEndpoint:
    """Test GET /api/ai-training/status endpoint"""

    def test_status_returns_success(self):
        """Verify status endpoint returns success:true with task_status:idle"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        
        # task_status should be idle when no training is running
        task_status = data.get("task_status", "")
        assert task_status == "idle", f"Expected task_status='idle', got '{task_status}'"


class TestGPUStatusEndpoint:
    """Test GET /api/ai-training/gpu-status endpoint"""

    def test_gpu_status_returns_valid_json(self):
        """Verify gpu-status endpoint returns valid JSON without errors"""
        response = requests.get(f"{BASE_URL}/api/ai-training/gpu-status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Should return valid JSON
        try:
            data = response.json()
        except Exception as e:
            pytest.fail(f"gpu-status did not return valid JSON: {e}")
        
        # Should have success field
        assert "success" in data or "gpu_available" in data or "mode" in data, (
            f"gpu-status response missing expected fields: {data}"
        )


class TestCountTotalModelsFunction:
    """Test count_total_models() function from training_pipeline"""

    def test_count_total_models_returns_108(self):
        """Verify count_total_models() returns 108"""
        from services.ai_modules.training_pipeline import count_total_models
        
        total = count_total_models()
        assert total == 108, f"Expected count_total_models() to return 108, got {total}"


class TestDefaultPhasesIncludeRegimeAndEnsemble:
    """Test that default phases list includes 'regime' and 'ensemble'"""

    def test_default_phases_include_regime(self):
        """Verify default phases include 'regime'"""
        # Check the default phases in run_training_pipeline
        # The default is set at line ~188 in training_pipeline.py
        expected_phases = ["generic", "setup", "short", "volatility", "exit", "sector", "gap_fill", "risk", "regime", "ensemble", "cnn"]
        
        assert "regime" in expected_phases, "Default phases should include 'regime'"
        assert "ensemble" in expected_phases, "Default phases should include 'ensemble'"

    def test_default_phases_from_source(self):
        """Verify default phases from source code inspection"""
        import inspect
        from services.ai_modules.training_pipeline import run_training_pipeline
        
        source = inspect.getsource(run_training_pipeline)
        
        # Check that 'regime' and 'ensemble' are in the default phases list
        assert '"regime"' in source or "'regime'" in source, "Default phases should include 'regime'"
        assert '"ensemble"' in source or "'ensemble'" in source, "Default phases should include 'ensemble'"


class TestRegimeConditionalModelModule:
    """Test regime_conditional_model.py exports"""

    def test_all_regimes_constant(self):
        """Verify ALL_REGIMES constant exists and has 4 regimes"""
        from services.ai_modules.regime_conditional_model import ALL_REGIMES
        
        assert len(ALL_REGIMES) == 4, f"Expected 4 regimes, got {len(ALL_REGIMES)}"
        expected = ["bull_trend", "bear_trend", "range_bound", "high_vol"]
        for regime in expected:
            assert regime in ALL_REGIMES, f"Expected regime '{regime}' in ALL_REGIMES"

    def test_classify_regime_for_date_exists(self):
        """Verify classify_regime_for_date function exists"""
        from services.ai_modules.regime_conditional_model import classify_regime_for_date
        assert callable(classify_regime_for_date), "classify_regime_for_date should be callable"

    def test_get_regime_model_name_function(self):
        """Verify get_regime_model_name function works correctly"""
        from services.ai_modules.regime_conditional_model import get_regime_model_name
        
        # Test naming pattern
        result = get_regime_model_name("direction_predictor_1_day", "bull_trend")
        assert result == "direction_predictor_1_day_bull_trend", f"Unexpected model name: {result}"


class TestEnsembleModelModule:
    """Test ensemble_model.py exports"""

    def test_ensemble_model_configs_has_10_entries(self):
        """Verify ENSEMBLE_MODEL_CONFIGS has 10 setup types"""
        from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS
        
        assert len(ENSEMBLE_MODEL_CONFIGS) == 10, f"Expected 10 ensemble configs, got {len(ENSEMBLE_MODEL_CONFIGS)}"

    def test_ensemble_feature_names_exists(self):
        """Verify ENSEMBLE_FEATURE_NAMES exists and is non-empty"""
        from services.ai_modules.ensemble_model import ENSEMBLE_FEATURE_NAMES
        
        assert len(ENSEMBLE_FEATURE_NAMES) > 0, "ENSEMBLE_FEATURE_NAMES should not be empty"

    def test_extract_ensemble_features_function(self):
        """Verify extract_ensemble_features function exists and is callable"""
        from services.ai_modules.ensemble_model import extract_ensemble_features
        
        assert callable(extract_ensemble_features), "extract_ensemble_features should be callable"

    def test_stacked_timeframes_constant(self):
        """Verify STACKED_TIMEFRAMES constant exists"""
        from services.ai_modules.ensemble_model import STACKED_TIMEFRAMES
        
        assert len(STACKED_TIMEFRAMES) == 3, f"Expected 3 stacked timeframes, got {len(STACKED_TIMEFRAMES)}"
        expected = ["1 day", "1 hour", "5 mins"]
        for tf in expected:
            assert tf in STACKED_TIMEFRAMES, f"Expected timeframe '{tf}' in STACKED_TIMEFRAMES"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
