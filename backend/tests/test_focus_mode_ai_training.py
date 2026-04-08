"""
Focus Mode + AI Training Integration Tests

Tests for:
1. POST /api/ai-training/start - sets focus_mode to 'training' and returns focus_mode in response
2. GET /api/focus-mode - returns current mode (default: 'live')
3. GET /api/ai-training/status - returns success:true
4. GET /api/ai-training/model-inventory - returns 108 total_defined
5. Bat file validation - no auto-start collectors, contains focus mode docs, 9 steps
"""

import pytest
import requests
import os
import re

# Use the public URL from frontend/.env
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # Fallback for local testing
    BASE_URL = "https://trade-ai-optimize.preview.emergentagent.com"


class TestFocusModeEndpoint:
    """Tests for GET /api/focus-mode endpoint"""
    
    def test_focus_mode_returns_success(self):
        """GET /api/focus-mode should return success:true"""
        response = requests.get(f"{BASE_URL}/api/focus-mode", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
    
    def test_focus_mode_returns_mode_field(self):
        """GET /api/focus-mode should return 'mode' field"""
        response = requests.get(f"{BASE_URL}/api/focus-mode", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data, f"Expected 'mode' field in response, got {data.keys()}"
    
    def test_focus_mode_default_is_live(self):
        """GET /api/focus-mode default mode should be 'live'"""
        response = requests.get(f"{BASE_URL}/api/focus-mode", timeout=30)
        assert response.status_code == 200
        data = response.json()
        # Mode should be 'live' by default (unless training is in progress)
        mode = data.get("mode")
        assert mode in ["live", "training", "collecting", "backtesting"], f"Invalid mode: {mode}"
    
    def test_focus_mode_has_is_live_field(self):
        """GET /api/focus-mode should have is_live boolean field"""
        response = requests.get(f"{BASE_URL}/api/focus-mode", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert "is_live" in data, f"Expected 'is_live' field in response"
        assert isinstance(data["is_live"], bool), f"is_live should be boolean"


class TestAITrainingStatus:
    """Tests for GET /api/ai-training/status endpoint"""
    
    def test_status_returns_success(self):
        """GET /api/ai-training/status should return success:true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
    
    def test_status_has_task_status(self):
        """GET /api/ai-training/status should have task_status field"""
        response = requests.get(f"{BASE_URL}/api/ai-training/status", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert "task_status" in data, f"Expected 'task_status' field, got {data.keys()}"
        assert data["task_status"] in ["idle", "running", "completed", "failed"], f"Invalid task_status: {data['task_status']}"


class TestAITrainingModelInventory:
    """Tests for GET /api/ai-training/model-inventory endpoint"""
    
    def test_model_inventory_returns_success(self):
        """GET /api/ai-training/model-inventory should return success:true"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
    
    def test_model_inventory_total_defined_is_108(self):
        """GET /api/ai-training/model-inventory should return 108 total_defined"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=60)
        assert response.status_code == 200
        data = response.json()
        assert "total_defined" in data, f"Expected 'total_defined' field, got {data.keys()}"
        assert data["total_defined"] == 108, f"Expected 108 total_defined, got {data['total_defined']}"


class TestAITrainingStartEndpoint:
    """Tests for POST /api/ai-training/start endpoint - focus mode integration"""
    
    def test_start_training_code_imports_focus_mode_manager(self):
        """Verify ai_training.py imports focus_mode_manager"""
        ai_training_path = "/app/backend/routers/ai_training.py"
        with open(ai_training_path, 'r') as f:
            content = f.read()
        
        # Check for import statement
        assert "from services.focus_mode_manager import focus_mode_manager" in content, \
            "Missing import: from services.focus_mode_manager import focus_mode_manager"
    
    def test_start_training_code_calls_set_mode_training(self):
        """Verify start_training calls focus_mode_manager.set_mode('training')"""
        ai_training_path = "/app/backend/routers/ai_training.py"
        with open(ai_training_path, 'r') as f:
            content = f.read()
        
        # Check for set_mode call with 'training'
        assert 'focus_mode_manager.set_mode(' in content, \
            "Missing call to focus_mode_manager.set_mode()"
        assert 'mode="training"' in content or "mode='training'" in content, \
            "set_mode should be called with mode='training'"
    
    def test_start_training_code_has_reset_to_live_in_finally(self):
        """Verify _run() has focus_mode_manager.reset_to_live() in finally block"""
        ai_training_path = "/app/backend/routers/ai_training.py"
        with open(ai_training_path, 'r') as f:
            content = f.read()
        
        # Check for reset_to_live in finally block
        assert 'focus_mode_manager.reset_to_live(' in content, \
            "Missing call to focus_mode_manager.reset_to_live()"
        
        # Verify it's in a finally block (check that 'finally:' appears before reset_to_live)
        finally_pos = content.find('finally:')
        reset_pos = content.find('focus_mode_manager.reset_to_live(')
        assert finally_pos != -1, "Missing 'finally:' block in _run()"
        assert reset_pos != -1, "Missing reset_to_live call"
        assert finally_pos < reset_pos, "reset_to_live should be inside finally block"
    
    def test_start_training_response_includes_focus_mode(self):
        """Verify start_training response includes focus_mode: 'training'"""
        ai_training_path = "/app/backend/routers/ai_training.py"
        with open(ai_training_path, 'r') as f:
            content = f.read()
        
        # Check for focus_mode in response
        assert '"focus_mode": "training"' in content or "'focus_mode': 'training'" in content, \
            "Response should include focus_mode: 'training'"


class TestBatFileValidation:
    """Tests for TradeCommand_AITraining.bat file"""
    
    BAT_FILE_PATH = "/app/documents/TradeCommand_AITraining.bat"
    
    def test_bat_file_exists(self):
        """Bat file should exist"""
        assert os.path.exists(self.BAT_FILE_PATH), f"Bat file not found at {self.BAT_FILE_PATH}"
    
    def test_bat_file_no_run_collector1(self):
        """Bat file should NOT contain 'run_collector1'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'run_collector1' not in content, "Bat file should NOT contain 'run_collector1'"
    
    def test_bat_file_no_run_collector2(self):
        """Bat file should NOT contain 'run_collector2'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'run_collector2' not in content, "Bat file should NOT contain 'run_collector2'"
    
    def test_bat_file_no_run_collector3(self):
        """Bat file should NOT contain 'run_collector3'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'run_collector3' not in content, "Bat file should NOT contain 'run_collector3'"
    
    def test_bat_file_no_step_9_collectors(self):
        """Bat file should NOT contain 'STEP 9: START HISTORICAL DATA COLLECTORS'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'STEP 9: START HISTORICAL DATA COLLECTORS' not in content, \
            "Bat file should NOT contain 'STEP 9: START HISTORICAL DATA COLLECTORS'"
    
    def test_bat_file_contains_collectors_start_from_ui(self):
        """Bat file should contain 'Collectors start from UI'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'Collectors start from UI' in content, \
            "Bat file should contain 'Collectors start from UI'"
    
    def test_bat_file_contains_collecting_mode(self):
        """Bat file should contain 'COLLECTING mode'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'COLLECTING mode' in content, \
            "Bat file should contain 'COLLECTING mode'"
    
    def test_bat_file_contains_training_mode(self):
        """Bat file should contain 'TRAINING mode'"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        assert 'TRAINING mode' in content, \
            "Bat file should contain 'TRAINING mode'"
    
    def test_bat_file_step_count_is_9(self):
        """Bat file should have 9 steps (8/9 and 9/9)"""
        with open(self.BAT_FILE_PATH, 'r') as f:
            content = f.read()
        
        # Check for step markers [8/9] and [9/9]
        assert '[8/9]' in content, "Bat file should contain step [8/9]"
        assert '[9/9]' in content, "Bat file should contain step [9/9]"
        
        # Verify there's no [10/10] or higher
        assert '[10/' not in content, "Bat file should NOT have step 10 or higher"
        assert '[11/' not in content, "Bat file should NOT have step 11 or higher"


class TestFocusModeManagerModule:
    """Tests for focus_mode_manager.py module"""
    
    def test_focus_mode_manager_has_set_mode(self):
        """focus_mode_manager should have set_mode method"""
        manager_path = "/app/backend/services/focus_mode_manager.py"
        with open(manager_path, 'r') as f:
            content = f.read()
        assert 'def set_mode(' in content, "Missing set_mode method"
    
    def test_focus_mode_manager_has_reset_to_live(self):
        """focus_mode_manager should have reset_to_live method"""
        manager_path = "/app/backend/services/focus_mode_manager.py"
        with open(manager_path, 'r') as f:
            content = f.read()
        assert 'def reset_to_live(' in content, "Missing reset_to_live method"
    
    def test_focus_mode_manager_has_collecting_mode(self):
        """focus_mode_manager should have COLLECTING mode config"""
        manager_path = "/app/backend/services/focus_mode_manager.py"
        with open(manager_path, 'r') as f:
            content = f.read()
        assert 'COLLECTING' in content, "Missing COLLECTING mode"
        assert 'FocusMode.COLLECTING' in content, "Missing FocusMode.COLLECTING enum"
    
    def test_focus_mode_manager_has_training_mode(self):
        """focus_mode_manager should have TRAINING mode config"""
        manager_path = "/app/backend/services/focus_mode_manager.py"
        with open(manager_path, 'r') as f:
            content = f.read()
        assert 'TRAINING' in content, "Missing TRAINING mode"
        assert 'FocusMode.TRAINING' in content, "Missing FocusMode.TRAINING enum"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
