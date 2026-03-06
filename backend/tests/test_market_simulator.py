"""
Market Hours Simulator API Tests
Tests for /api/simulator/* endpoints that allow testing scanner alerts when markets are closed.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSimulatorStatus:
    """Tests for /api/simulator/status endpoint"""
    
    def test_get_status(self):
        """Test fetching simulator status"""
        response = requests.get(f"{BASE_URL}/api/simulator/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "running" in data
        assert "scenario" in data
        assert "alert_interval" in data
        assert "alerts_generated" in data
        assert "available_scenarios" in data
        
        # Validate available scenarios
        assert "bullish_momentum" in data["available_scenarios"]
        assert "bearish_reversal" in data["available_scenarios"]
        assert "range_bound" in data["available_scenarios"]
        assert "high_volatility" in data["available_scenarios"]
        print(f"✓ Status: running={data['running']}, scenario={data['scenario']}, interval={data['alert_interval']}s")


class TestSimulatorScenarios:
    """Tests for /api/simulator/scenarios endpoint"""
    
    def test_list_scenarios(self):
        """Test listing all available scenarios"""
        response = requests.get(f"{BASE_URL}/api/simulator/scenarios")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "scenarios" in data
        
        scenarios = data["scenarios"]
        assert "bullish_momentum" in scenarios
        assert "bearish_reversal" in scenarios
        assert "range_bound" in scenarios
        assert "high_volatility" in scenarios
        
        # Check descriptions
        assert "uptrend" in scenarios["bullish_momentum"].lower()
        assert "weakness" in scenarios["bearish_reversal"].lower() or "reversal" in scenarios["bearish_reversal"].lower()
        assert "choppy" in scenarios["range_bound"].lower() or "mean reversion" in scenarios["range_bound"].lower()
        assert "vix" in scenarios["high_volatility"].lower() or "volatility" in scenarios["high_volatility"].lower()
        
        print(f"✓ Found {len(scenarios)} scenarios: {list(scenarios.keys())}")


class TestSimulatorStartStop:
    """Tests for /api/simulator/start and /api/simulator/stop endpoints"""
    
    def test_stop_simulator(self):
        """Test stopping the simulator"""
        response = requests.post(f"{BASE_URL}/api/simulator/stop")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "stopped" in data["message"].lower() or "stop" in data["message"].lower()
        
        # Verify status shows stopped
        status_res = requests.get(f"{BASE_URL}/api/simulator/status")
        status_data = status_res.json()
        assert status_data["running"] is False
        print("✓ Simulator stopped successfully")
    
    def test_start_simulator_default(self):
        """Test starting simulator with default settings"""
        # First stop to ensure clean state
        requests.post(f"{BASE_URL}/api/simulator/stop")
        
        response = requests.post(f"{BASE_URL}/api/simulator/start")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["running"] is True
        assert "started" in data["message"].lower() or "start" in data["message"].lower()
        print(f"✓ Simulator started with default settings: scenario={data['scenario']}, interval={data['alert_interval']}s")
    
    def test_start_simulator_with_scenario(self):
        """Test starting simulator with specific scenario"""
        # Stop first
        requests.post(f"{BASE_URL}/api/simulator/stop")
        
        response = requests.post(f"{BASE_URL}/api/simulator/start?scenario=bullish_momentum")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["running"] is True
        assert data["scenario"] == "bullish_momentum"
        print(f"✓ Simulator started with bullish_momentum scenario")
    
    def test_start_simulator_with_interval(self):
        """Test starting simulator with specific interval"""
        # Stop first
        requests.post(f"{BASE_URL}/api/simulator/stop")
        
        response = requests.post(f"{BASE_URL}/api/simulator/start?interval=60")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["running"] is True
        assert data["alert_interval"] == 60
        print(f"✓ Simulator started with 60s interval")
    
    def test_start_simulator_with_all_params(self):
        """Test starting simulator with scenario and interval"""
        # Stop first
        requests.post(f"{BASE_URL}/api/simulator/stop")
        
        response = requests.post(f"{BASE_URL}/api/simulator/start?scenario=high_volatility&interval=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["running"] is True
        assert data["scenario"] == "high_volatility"
        assert data["alert_interval"] == 10
        print(f"✓ Simulator started with high_volatility scenario and 10s interval")
    
    def test_start_invalid_scenario(self):
        """Test starting simulator with invalid scenario returns 400"""
        response = requests.post(f"{BASE_URL}/api/simulator/start?scenario=invalid_scenario")
        assert response.status_code == 400
        
        data = response.json()
        assert "Invalid" in data.get("detail", "") or "invalid" in data.get("detail", "").lower()
        print("✓ Invalid scenario correctly rejected with 400")


class TestSimulatorGenerateAlert:
    """Tests for /api/simulator/generate endpoint"""
    
    def test_generate_single_alert(self):
        """Test generating a single alert on demand"""
        response = requests.post(f"{BASE_URL}/api/simulator/generate")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "alert" in data
        
        alert = data["alert"]
        # Validate alert structure
        assert "id" in alert
        assert "symbol" in alert
        assert "setup_type" in alert
        assert "direction" in alert
        assert alert["direction"] in ["long", "short"]
        assert "priority" in alert
        assert alert["priority"] in ["critical", "high", "medium", "low"]
        assert "current_price" in alert
        assert "trigger_price" in alert
        assert "stop_loss" in alert
        assert "target" in alert
        assert "risk_reward" in alert
        assert "headline" in alert
        assert "created_at" in alert
        assert "simulated" in alert
        assert alert["simulated"] is True
        
        print(f"✓ Generated alert: {alert['headline']} - {alert['priority']} priority")
    
    def test_generate_alert_has_sim_badge(self):
        """Test that generated alert has simulated flag for SIM badge"""
        response = requests.post(f"{BASE_URL}/api/simulator/generate")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        
        alert = data["alert"]
        assert alert.get("simulated") is True
        assert alert["id"].startswith("sim_")
        print(f"✓ Alert marked as simulated with ID prefix 'sim_'")


class TestSimulatorSetScenario:
    """Tests for /api/simulator/scenario/{scenario_name} endpoint"""
    
    def test_set_scenario_bullish(self):
        """Test setting scenario to bullish_momentum"""
        response = requests.post(f"{BASE_URL}/api/simulator/scenario/bullish_momentum")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["scenario"] == "bullish_momentum"
        assert "description" in data
        print(f"✓ Scenario set to bullish_momentum: {data['description']}")
    
    def test_set_scenario_bearish(self):
        """Test setting scenario to bearish_reversal"""
        response = requests.post(f"{BASE_URL}/api/simulator/scenario/bearish_reversal")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["scenario"] == "bearish_reversal"
        print(f"✓ Scenario set to bearish_reversal")
    
    def test_set_scenario_range_bound(self):
        """Test setting scenario to range_bound"""
        response = requests.post(f"{BASE_URL}/api/simulator/scenario/range_bound")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["scenario"] == "range_bound"
        print(f"✓ Scenario set to range_bound")
    
    def test_set_scenario_high_volatility(self):
        """Test setting scenario to high_volatility"""
        response = requests.post(f"{BASE_URL}/api/simulator/scenario/high_volatility")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["scenario"] == "high_volatility"
        print(f"✓ Scenario set to high_volatility")
    
    def test_set_invalid_scenario(self):
        """Test setting invalid scenario returns 400"""
        response = requests.post(f"{BASE_URL}/api/simulator/scenario/invalid_scenario")
        assert response.status_code == 400
        
        data = response.json()
        assert "Invalid" in data.get("detail", "") or "invalid" in data.get("detail", "").lower()
        print("✓ Invalid scenario correctly rejected with 400")


class TestSimulatorAlerts:
    """Tests for /api/simulator/alerts endpoint"""
    
    def test_get_simulated_alerts(self):
        """Test getting all generated alerts"""
        # First generate an alert to ensure there's data
        requests.post(f"{BASE_URL}/api/simulator/generate")
        
        response = requests.get(f"{BASE_URL}/api/simulator/alerts")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "count" in data
        assert "alerts" in data
        assert isinstance(data["alerts"], list)
        
        # Verify alerts have simulated flag
        if len(data["alerts"]) > 0:
            for alert in data["alerts"]:
                assert alert.get("simulated") is True
        
        print(f"✓ Retrieved {data['count']} simulated alerts")


class TestSimulatorIntegration:
    """Integration tests for full simulator workflow"""
    
    def test_full_workflow(self):
        """Test complete simulator workflow: stop -> start with config -> generate -> check alerts"""
        # 1. Stop simulator
        stop_res = requests.post(f"{BASE_URL}/api/simulator/stop")
        assert stop_res.status_code == 200
        
        # 2. Verify stopped
        status_res = requests.get(f"{BASE_URL}/api/simulator/status")
        assert status_res.json()["running"] is False
        
        # 3. Start with specific config
        start_res = requests.post(f"{BASE_URL}/api/simulator/start?scenario=bearish_reversal&interval=30")
        assert start_res.status_code == 200
        start_data = start_res.json()
        assert start_data["running"] is True
        assert start_data["scenario"] == "bearish_reversal"
        assert start_data["alert_interval"] == 30
        
        # 4. Generate an alert
        gen_res = requests.post(f"{BASE_URL}/api/simulator/generate")
        assert gen_res.status_code == 200
        gen_data = gen_res.json()
        assert gen_data["success"] is True
        generated_alert_id = gen_data["alert"]["id"]
        
        # 5. Check that alert appears in alerts list
        alerts_res = requests.get(f"{BASE_URL}/api/simulator/alerts")
        assert alerts_res.status_code == 200
        alerts_data = alerts_res.json()
        alert_ids = [a["id"] for a in alerts_data["alerts"]]
        assert generated_alert_id in alert_ids
        
        # 6. Stop simulator
        requests.post(f"{BASE_URL}/api/simulator/stop")
        
        print("✓ Full workflow passed: stop -> start -> generate -> verify -> stop")
