"""
Test Training Progress Dashboard Features
Tests for:
1. PHASE_CONFIGS with 10 phases
2. TrainingPipelineStatus class with auto phase transitions
3. add_completed() and add_error() methods
4. GET /api/ai-training/status returns pipeline_status with phase_history
5. GET /api/ai-training/model-inventory returns 108 models with regime_conditional (28)
"""

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')


class TestPhaseConfigs:
    """Test PHASE_CONFIGS constant has 10 phases with correct structure"""

    def test_phase_configs_has_10_entries(self):
        """PHASE_CONFIGS should have exactly 10 phase entries"""
        from services.ai_modules.training_pipeline import PHASE_CONFIGS
        assert len(PHASE_CONFIGS) == 10, f"Expected 10 phases, got {len(PHASE_CONFIGS)}"

    def test_phase_configs_keys(self):
        """PHASE_CONFIGS should have all expected phase keys"""
        from services.ai_modules.training_pipeline import PHASE_CONFIGS
        expected_keys = [
            'generic_directional', 'setup_specific', 'short_setup_specific',
            'volatility_prediction', 'exit_timing', 'sector_relative',
            'risk_of_ruin', 'regime_conditional', 'ensemble_meta', 'cnn_patterns'
        ]
        for key in expected_keys:
            assert key in PHASE_CONFIGS, f"Missing phase key: {key}"

    def test_phase_configs_structure(self):
        """Each phase config should have label, order, phase_num, expected_models"""
        from services.ai_modules.training_pipeline import PHASE_CONFIGS
        required_fields = ['label', 'order', 'phase_num', 'expected_models']
        for key, config in PHASE_CONFIGS.items():
            for field in required_fields:
                assert field in config, f"Phase {key} missing field: {field}"

    def test_phase_configs_order_values(self):
        """Phase order values should be 1-10"""
        from services.ai_modules.training_pipeline import PHASE_CONFIGS
        orders = [config['order'] for config in PHASE_CONFIGS.values()]
        assert sorted(orders) == list(range(1, 11)), f"Orders should be 1-10, got {sorted(orders)}"

    def test_phase_configs_expected_models(self):
        """Verify expected_models for key phases"""
        from services.ai_modules.training_pipeline import PHASE_CONFIGS
        assert PHASE_CONFIGS['generic_directional']['expected_models'] == 7
        assert PHASE_CONFIGS['setup_specific']['expected_models'] == 17
        assert PHASE_CONFIGS['short_setup_specific']['expected_models'] == 17
        assert PHASE_CONFIGS['volatility_prediction']['expected_models'] == 7
        assert PHASE_CONFIGS['exit_timing']['expected_models'] == 10
        assert PHASE_CONFIGS['sector_relative']['expected_models'] == 3
        assert PHASE_CONFIGS['risk_of_ruin']['expected_models'] == 6
        assert PHASE_CONFIGS['regime_conditional']['expected_models'] == 28
        assert PHASE_CONFIGS['ensemble_meta']['expected_models'] == 10
        assert PHASE_CONFIGS['cnn_patterns']['expected_models'] == 13


class TestTrainingPipelineStatus:
    """Test TrainingPipelineStatus class methods"""

    def test_status_class_exists(self):
        """TrainingPipelineStatus class should exist"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        assert TrainingPipelineStatus is not None

    def test_status_init_has_phase_history(self):
        """TrainingPipelineStatus should initialize with phase_history dict"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        state = status.get_status()
        assert 'phase_history' in state
        assert isinstance(state['phase_history'], dict)

    def test_update_auto_starts_phase(self):
        """update(phase=X) should auto-start a new phase in phase_history"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        status.update(phase='generic_directional')
        state = status.get_status()
        
        assert 'generic_directional' in state['phase_history']
        ph = state['phase_history']['generic_directional']
        assert ph['status'] == 'running'
        assert ph['label'] == 'Generic Directional'
        assert ph['order'] == 1
        assert ph['expected_models'] == 7
        assert 'started_at' in ph

    def test_update_auto_ends_previous_phase(self):
        """update(phase=Y) should auto-end previous phase X"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        
        # Start phase 1
        status.update(phase='generic_directional')
        # Start phase 2 (should end phase 1)
        status.update(phase='setup_specific')
        
        state = status.get_status()
        ph1 = state['phase_history']['generic_directional']
        ph2 = state['phase_history']['setup_specific']
        
        assert ph1['status'] == 'done'
        assert 'ended_at' in ph1
        assert ph1['elapsed_seconds'] >= 0
        assert ph2['status'] == 'running'

    def test_add_completed_increments_models_trained(self):
        """add_completed() should increment models_trained in current phase"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        status.update(phase='generic_directional')
        
        status.add_completed('model_1', 0.75)
        status.add_completed('model_2', 0.80)
        
        state = status.get_status()
        ph = state['phase_history']['generic_directional']
        assert ph['models_trained'] == 2

    def test_add_completed_computes_avg_accuracy(self):
        """add_completed() should compute running avg_accuracy"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        status.update(phase='generic_directional')
        
        status.add_completed('model_1', 0.70)
        status.add_completed('model_2', 0.80)
        
        state = status.get_status()
        ph = state['phase_history']['generic_directional']
        # avg = (0.70 + 0.80) / 2 = 0.75
        assert abs(ph['avg_accuracy'] - 0.75) < 0.001

    def test_add_error_increments_models_failed(self):
        """add_error() should increment models_failed in current phase"""
        from services.ai_modules.training_pipeline import TrainingPipelineStatus
        status = TrainingPipelineStatus(db=None)
        status.update(phase='generic_directional')
        
        status.add_error('model_1', 'Some error')
        status.add_error('model_2', 'Another error')
        
        state = status.get_status()
        ph = state['phase_history']['generic_directional']
        assert ph['models_failed'] == 2


class TestTrainingStatusAPI:
    """Test GET /api/ai-training/status endpoint"""

    def test_status_returns_success(self):
        """GET /api/ai-training/status should return success:true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True

    def test_status_has_task_status(self):
        """Response should have task_status field"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=30)
        data = response.json()
        assert 'task_status' in data
        assert data['task_status'] in ['idle', 'running', 'completed', 'failed']

    def test_status_has_pipeline_status_field(self):
        """Response should have pipeline_status field (may be null if no training)"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=30)
        data = response.json()
        assert 'pipeline_status' in data


class TestModelInventoryAPI:
    """Test GET /api/ai-training/model-inventory endpoint"""

    def test_inventory_returns_success(self):
        """GET /api/ai-training/model-inventory should return success:true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True

    def test_inventory_total_defined_is_108(self):
        """total_defined should be 108"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        data = response.json()
        assert data.get('total_defined') == 108

    def test_inventory_has_9_categories(self):
        """Should have 9 categories"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        data = response.json()
        categories = data.get('categories', {})
        assert len(categories) == 9

    def test_inventory_regime_conditional_has_28_models(self):
        """regime_conditional category should have 28 models"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=30)
        data = response.json()
        regime_cat = data.get('categories', {}).get('regime_conditional', {})
        models = regime_cat.get('models', [])
        assert len(models) == 28, f"Expected 28 regime_conditional models, got {len(models)}"


class TestFrontendConstants:
    """Test frontend ALL_PHASES constant matches backend PHASE_CONFIGS"""

    def test_all_phases_has_10_entries(self):
        """Frontend ALL_PHASES should have 10 entries matching backend"""
        # Read frontend file and check ALL_PHASES
        import re
        with open('/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx', 'r') as f:
            content = f.read()
        
        # Find ALL_PHASES array
        match = re.search(r'const ALL_PHASES = \[(.*?)\];', content, re.DOTALL)
        assert match, "ALL_PHASES constant not found in TrainingPipelinePanel.jsx"
        
        # Count entries by counting 'key:' occurrences
        phases_content = match.group(1)
        key_count = len(re.findall(r"key:\s*'", phases_content))
        assert key_count == 10, f"Expected 10 phases in ALL_PHASES, got {key_count}"

    def test_phase_tracker_component_exists(self):
        """PhaseTracker component should exist with data-testid='phase-tracker'"""
        with open('/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx', 'r') as f:
            content = f.read()
        
        assert "data-testid='phase-tracker'" in content or 'data-testid="phase-tracker"' in content, \
            "PhaseTracker should have data-testid='phase-tracker'"

    def test_phase_row_has_data_testid(self):
        """PhaseRow should have data-testid='phase-row-{key}'"""
        with open('/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx', 'r') as f:
            content = f.read()
        
        assert "data-testid={`phase-row-${phase.key}`}" in content, \
            "PhaseRow should have data-testid='phase-row-{key}'"

    def test_auto_poll_useeffect_exists(self):
        """Auto-poll useEffect with isTraining dependency should exist"""
        with open('/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx', 'r') as f:
            content = f.read()
        
        # Check for auto-poll pattern
        assert 'isTraining' in content, "isTraining variable should exist"
        assert 'setInterval' in content, "setInterval for auto-polling should exist"
        # Check isTraining is used in useEffect dependency
        assert '[isTraining' in content or ', isTraining]' in content, \
            "isTraining should be in useEffect dependency array"

    def test_no_tdz_error_isTraining_declared_before_use(self):
        """isTraining should be declared before being used in useEffect"""
        with open('/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx', 'r') as f:
            content = f.read()
        
        # Find isTraining declaration
        is_training_decl = content.find("const isTraining")
        # Find the auto-poll useEffect
        auto_poll_effect = content.find("if (!isTraining) return")
        
        assert is_training_decl > 0, "isTraining should be declared"
        assert auto_poll_effect > 0, "Auto-poll useEffect should exist"
        assert is_training_decl < auto_poll_effect, \
            "isTraining should be declared BEFORE being used in useEffect"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
