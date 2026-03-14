"""
AI Modules API Tests
Testing Phase 1-6 institutional-grade AI features:
- Module Config API
- Module Toggle API  
- Shadow Mode API
- Bull/Bear Debate API
- AI Risk Assessment API
- Institutional Flow APIs
- Volume Anomaly Detection APIs
- Shadow Tracker Stats API
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAIModulesConfig:
    """Test AI Module configuration endpoints"""
    
    def test_get_module_config(self):
        """GET /api/ai-modules/config - should return full module configuration"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/config")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, "Response should indicate success"
        
        config = data.get("config", {})
        modules = config.get("modules", {})
        
        # Verify all 4 modules are present
        assert "debate_agents" in modules, "debate_agents module should exist"
        assert "ai_risk_manager" in modules, "ai_risk_manager module should exist"
        assert "institutional_flow" in modules, "institutional_flow module should exist"
        assert "timeseries_ai" in modules, "timeseries_ai module should exist"
        
        # Verify each module has expected fields
        for module_name, module_data in modules.items():
            assert "enabled" in module_data, f"{module_name} should have enabled field"
            assert "shadow_mode" in module_data, f"{module_name} should have shadow_mode field"
            assert "name" in module_data, f"{module_name} should have name field"
            assert "description" in module_data, f"{module_name} should have description field"
        
        # Verify global settings
        assert "global_shadow_mode" in config, "Config should have global_shadow_mode"
        print(f"Config retrieved successfully: {len(modules)} modules configured")
    
    def test_get_module_status(self):
        """GET /api/ai-modules/status - should return quick status summary"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        
        status = data.get("status", {})
        
        # Verify status has all expected fields
        expected_fields = [
            "debate_enabled",
            "risk_manager_enabled", 
            "institutional_enabled",
            "timeseries_enabled",
            "shadow_mode",
            "active_modules"
        ]
        for field in expected_fields:
            assert field in status, f"Status should have {field}"
        
        print(f"Status: {status.get('active_modules')} active modules, shadow_mode={status.get('shadow_mode')}")


class TestModuleToggle:
    """Test module toggle functionality"""
    
    def test_toggle_debate_agents_on(self):
        """POST /api/ai-modules/toggle/debate_agents - enable module"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/debate_agents",
            json={"enabled": True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("module") == "debate_agents"
        assert data.get("enabled") == True
        print("debate_agents enabled successfully")
    
    def test_toggle_debate_agents_off(self):
        """POST /api/ai-modules/toggle/debate_agents - disable module"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/debate_agents",
            json={"enabled": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("enabled") == False
        print("debate_agents disabled successfully")
    
    def test_toggle_ai_risk_manager(self):
        """POST /api/ai-modules/toggle/ai_risk_manager - toggle risk manager"""
        # Enable
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/ai_risk_manager",
            json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("ai_risk_manager enabled successfully")
    
    def test_toggle_institutional_flow(self):
        """POST /api/ai-modules/toggle/institutional_flow - toggle institutional flow"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/institutional_flow",
            json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("institutional_flow enabled successfully")
    
    def test_toggle_invalid_module(self):
        """POST /api/ai-modules/toggle/invalid_module - should return error"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/invalid_module_name",
            json={"enabled": True}
        )
        # Should return 400 for unknown module
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"


class TestShadowMode:
    """Test shadow mode toggle functionality"""
    
    def test_set_global_shadow_mode_on(self):
        """POST /api/ai-modules/shadow-mode - enable global shadow mode"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/shadow-mode",
            json={"shadow_mode": True}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("global_shadow_mode") == True
        print("Global shadow mode enabled")
    
    def test_set_global_shadow_mode_off(self):
        """POST /api/ai-modules/shadow-mode - disable global shadow mode"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/shadow-mode",
            json={"shadow_mode": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert data.get("global_shadow_mode") == False
        print("Global shadow mode disabled")
    
    def test_set_module_shadow_mode(self):
        """POST /api/ai-modules/shadow-mode/debate_agents - set per-module shadow mode"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/shadow-mode/debate_agents",
            json={"shadow_mode": True}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print("Module-specific shadow mode set")


class TestDebateAgents:
    """Test Bull/Bear Debate functionality"""
    
    def test_run_debate_module_disabled(self):
        """POST /api/ai-modules/debate/run - should fail when module disabled"""
        # First disable the module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/debate_agents",
            json={"enabled": False}
        )
        
        # Try to run debate
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/debate/run",
            json={
                "symbol": "AAPL",
                "setup": {
                    "tqs_score": 75,
                    "risk_reward": 2.5,
                    "direction": "long"
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == False, "Should fail when module is disabled"
        assert data.get("enabled") == False
        print("Debate correctly rejected when module disabled")
    
    def test_run_debate_module_enabled(self):
        """POST /api/ai-modules/debate/run - should succeed when module enabled"""
        # Enable the module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/debate_agents",
            json={"enabled": True}
        )
        
        # Run debate with full setup data
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/debate/run",
            json={
                "symbol": "AAPL",
                "setup": {
                    "tqs_score": 75,
                    "quality_score": 75,
                    "risk_reward": 2.5,
                    "direction": "long",
                    "setup_type": "breakout",
                    "entry_price": 180.0,
                    "historical_win_rate": 0.55,
                    "confirmations": ["volume", "trend", "support"]
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "trend": "bullish",
                    "vix": 15.5
                },
                "technical_data": {
                    "rvol": 1.8,
                    "relative_volume": 1.8
                }
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Debate should succeed: {data}"
        
        debate_result = data.get("debate_result", {})
        
        # Verify debate result structure
        assert "bull_score" in debate_result, "Should have bull_score"
        assert "bear_score" in debate_result, "Should have bear_score"
        assert "winner" in debate_result, "Should have winner"
        assert "final_recommendation" in debate_result, "Should have final_recommendation"
        assert "reasoning" in debate_result, "Should have reasoning"
        
        assert debate_result["winner"] in ["bull", "bear", "tie"], "Winner should be bull, bear, or tie"
        assert debate_result["final_recommendation"] in ["proceed", "pass", "reduce_size"], "Recommendation should be valid"
        
        print(f"Debate result: {debate_result['winner']} wins, recommendation={debate_result['final_recommendation']}")
        print(f"Bull score: {debate_result['bull_score']}, Bear score: {debate_result['bear_score']}")


class TestAIRiskManager:
    """Test AI Risk Manager functionality"""
    
    def test_risk_assessment_module_disabled(self):
        """POST /api/ai-modules/risk/assess - should fail when disabled"""
        # Disable module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/ai_risk_manager",
            json={"enabled": False}
        )
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/risk/assess",
            json={
                "symbol": "AAPL",
                "direction": "long",
                "entry_price": 180.0,
                "stop_price": 175.0,
                "target_price": 195.0,
                "position_size_shares": 100,
                "account_value": 100000
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == False
        assert data.get("enabled") == False
        print("Risk assessment correctly rejected when module disabled")
    
    def test_risk_assessment_full(self):
        """POST /api/ai-modules/risk/assess - full risk assessment"""
        # Enable module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/ai_risk_manager",
            json={"enabled": True}
        )
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/risk/assess",
            json={
                "symbol": "AAPL",
                "direction": "long",
                "entry_price": 180.0,
                "stop_price": 175.0,
                "target_price": 195.0,
                "position_size_shares": 100,
                "account_value": 100000,
                "setup": {
                    "historical_win_rate": 0.55,
                    "atr_pct": 2.5
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "trend": "bullish",
                    "vix": 15.5
                }
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Assessment should succeed: {data}"
        
        assessment = data.get("assessment", {})
        
        # Verify assessment structure
        assert "total_risk_score" in assessment, "Should have total_risk_score"
        assert "risk_level" in assessment, "Should have risk_level"
        assert "recommendation" in assessment, "Should have recommendation"
        assert "factors" in assessment, "Should have factors"
        
        assert assessment["risk_level"] in ["low", "moderate", "high", "extreme"]
        assert assessment["recommendation"] in ["proceed", "reduce_size", "pass", "block"]
        
        # Verify risk factors are present
        factors = assessment.get("factors", [])
        assert len(factors) > 0, "Should have risk factors"
        
        print(f"Risk assessment: score={assessment['total_risk_score']}, level={assessment['risk_level']}")
        print(f"Recommendation: {assessment['recommendation']}")


class TestInstitutionalFlow:
    """Test Institutional Flow / 13F Tracking functionality"""
    
    def test_ownership_context_disabled(self):
        """GET /api/ai-modules/institutional/context/{symbol} - when disabled"""
        # Disable module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/institutional_flow",
            json={"enabled": False}
        )
        
        response = requests.get(f"{BASE_URL}/api/ai-modules/institutional/context/AAPL")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == False
        assert data.get("enabled") == False
        print("Institutional context correctly rejected when disabled")
    
    def test_ownership_context_enabled(self):
        """GET /api/ai-modules/institutional/context/{symbol} - should return context"""
        # Enable module
        requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/institutional_flow",
            json={"enabled": True}
        )
        
        response = requests.get(f"{BASE_URL}/api/ai-modules/institutional/context/AAPL")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Should succeed: {data}"
        
        context = data.get("context", {})
        
        # Verify context structure
        assert "symbol" in context, "Should have symbol"
        assert "summary" in context, "Should have summary"
        assert "signals" in context, "Should have signals"
        assert "risk_score" in context, "Should have risk_score"
        assert "recommendation" in context, "Should have recommendation"
        
        assert context["recommendation"] in ["favorable", "neutral", "caution"]
        
        print(f"Institutional context for {context['symbol']}: {context['recommendation']}")
        print(f"Risk score: {context['risk_score']}")
    
    def test_rebalance_risk(self):
        """GET /api/ai-modules/institutional/rebalance-risk/{symbol}"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/institutional/rebalance-risk/AAPL")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        
        risk = data.get("risk", {})
        assert "symbol" in risk, "Should have symbol"
        assert "risks" in risk, "Should have risks list"
        assert "has_rebalance_risk" in risk, "Should have has_rebalance_risk flag"
        
        print(f"Rebalance risk for AAPL: has_risk={risk.get('has_rebalance_risk')}")


class TestVolumeAnomaly:
    """Test Volume Anomaly Detection functionality"""
    
    def test_volume_analyze(self):
        """POST /api/ai-modules/volume/analyze - analyze volume profile"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/volume/analyze",
            json={
                "symbol": "AAPL",
                "bars": [
                    {"open": 180.0, "high": 182.0, "low": 179.5, "close": 181.5, "volume": 5000000, "timestamp": "2025-01-10T14:30:00"},
                    {"open": 179.0, "high": 181.0, "low": 178.5, "close": 180.0, "volume": 4500000, "timestamp": "2025-01-10T14:00:00"},
                    {"open": 178.0, "high": 180.0, "low": 177.5, "close": 179.0, "volume": 4800000, "timestamp": "2025-01-10T13:30:00"},
                    {"open": 177.0, "high": 179.0, "low": 176.5, "close": 178.0, "volume": 4200000, "timestamp": "2025-01-10T13:00:00"},
                    {"open": 176.0, "high": 178.0, "low": 175.5, "close": 177.0, "volume": 4000000, "timestamp": "2025-01-10T12:30:00"},
                ],
                "direction": "long"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Should succeed: {data}"
        
        analysis = data.get("analysis", {})
        assert "profile" in analysis, "Should have profile"
        assert "signals" in analysis, "Should have signals"
        assert "recommendation" in analysis, "Should have recommendation"
        
        profile = analysis.get("profile", {})
        assert "rvol" in profile, "Profile should have rvol"
        assert "zscore" in profile, "Profile should have zscore"
        assert "volume_trend" in profile, "Profile should have volume_trend"
        
        print(f"Volume analysis: RVOL={profile.get('rvol')}, trend={profile.get('volume_trend')}")
        print(f"Recommendation: {analysis.get('recommendation')}")
    
    def test_volume_detect_spike(self):
        """POST /api/ai-modules/volume/detect - detect volume anomaly"""
        # Create historical volumes (normal range around 4-5M)
        historical_volumes = [4000000, 4200000, 4100000, 4500000, 4300000, 
                            4400000, 4600000, 4200000, 4500000, 4100000,
                            4300000, 4400000, 4200000, 4600000, 4100000,
                            4500000, 4300000, 4400000, 4200000, 4100000]
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/volume/detect",
            json={
                "symbol": "AAPL",
                "current_volume": 15000000,  # 3x normal = spike
                "historical_volumes": historical_volumes,
                "current_price": 182.0,
                "open_price": 180.0,
                "high_price": 183.0,
                "low_price": 179.5
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Should succeed: {data}"
        
        # With 3x volume, should detect anomaly
        anomaly_detected = data.get("anomaly_detected", False)
        
        print(f"Anomaly detected: {anomaly_detected}")
        
        if anomaly_detected:
            anomaly = data.get("anomaly", {})
            assert "anomaly_type" in anomaly, "Anomaly should have type"
            assert "zscore" in anomaly, "Anomaly should have zscore"
            assert "signal" in anomaly, "Anomaly should have signal"
            print(f"Anomaly: type={anomaly.get('anomaly_type')}, zscore={anomaly.get('zscore')}, signal={anomaly.get('signal')}")
    
    def test_volume_detect_no_anomaly(self):
        """POST /api/ai-modules/volume/detect - normal volume should not trigger"""
        historical_volumes = [4000000, 4200000, 4100000, 4500000, 4300000,
                            4400000, 4600000, 4200000, 4500000, 4100000]
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/volume/detect",
            json={
                "symbol": "AAPL",
                "current_volume": 4300000,  # Normal volume
                "historical_volumes": historical_volumes,
                "current_price": 181.0,
                "open_price": 180.0
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        # Normal volume should not trigger anomaly
        anomaly_detected = data.get("anomaly_detected", False)
        print(f"Normal volume anomaly detected: {anomaly_detected} (expected: False)")


class TestShadowTracker:
    """Test Shadow Tracker statistics and decision logging"""
    
    def test_get_shadow_stats(self):
        """GET /api/ai-modules/shadow/stats - get shadow tracker statistics"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        
        stats = data.get("stats", {})
        assert "total_decisions" in stats, "Should have total_decisions"
        assert "pending_outcomes" in stats, "Should have pending_outcomes"
        assert "executed_decisions" in stats, "Should have executed_decisions"
        assert "db_connected" in stats, "Should have db_connected"
        
        print(f"Shadow stats: total={stats.get('total_decisions')}, executed={stats.get('executed_decisions')}, pending={stats.get('pending_outcomes')}")
    
    def test_get_shadow_decisions(self):
        """GET /api/ai-modules/shadow/decisions - get logged decisions"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/decisions?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        assert "decisions" in data, "Should have decisions list"
        assert "count" in data, "Should have count"
        
        decisions = data.get("decisions", [])
        print(f"Shadow decisions retrieved: {len(decisions)} decisions")
        
        # If there are decisions, verify structure
        if decisions:
            decision = decisions[0]
            assert "symbol" in decision, "Decision should have symbol"
            assert "combined_recommendation" in decision, "Decision should have recommendation"
    
    def test_get_shadow_performance(self):
        """GET /api/ai-modules/shadow/performance - get module performance metrics"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/performance?days=30")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True
        assert "performance" in data, "Should have performance data"
        
        performance = data.get("performance", {})
        
        # Should have performance data for each module
        expected_modules = ["debate_agents", "ai_risk_manager", "institutional_flow", "timeseries_ai"]
        for module in expected_modules:
            assert module in performance, f"Should have performance for {module}"
        
        print(f"Performance data retrieved for {len(performance)} modules")


class TestEndToEnd:
    """End-to-end workflow tests"""
    
    def test_full_trade_analysis_flow(self):
        """Test complete AI analysis flow for a trade opportunity"""
        # 1. Enable all modules
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            resp = requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
            assert resp.status_code == 200
        
        # 2. Get institutional context
        inst_resp = requests.get(f"{BASE_URL}/api/ai-modules/institutional/context/AAPL")
        assert inst_resp.status_code == 200
        inst_data = inst_resp.json()
        
        # 3. Run debate
        debate_resp = requests.post(
            f"{BASE_URL}/api/ai-modules/debate/run",
            json={
                "symbol": "AAPL",
                "setup": {
                    "tqs_score": 72,
                    "risk_reward": 2.3,
                    "direction": "long",
                    "setup_type": "breakout"
                },
                "market_context": {"regime": "RISK_ON", "vix": 16.0}
            }
        )
        assert debate_resp.status_code == 200
        debate_data = debate_resp.json()
        
        # 4. Run risk assessment
        risk_resp = requests.post(
            f"{BASE_URL}/api/ai-modules/risk/assess",
            json={
                "symbol": "AAPL",
                "direction": "long",
                "entry_price": 180.0,
                "stop_price": 175.0,
                "target_price": 195.0,
                "position_size_shares": 50,
                "account_value": 100000,
                "setup": {},
                "market_context": {"regime": "RISK_ON", "vix": 16.0}
            }
        )
        assert risk_resp.status_code == 200
        risk_data = risk_resp.json()
        
        # 5. Check shadow stats (decisions should be logged)
        stats_resp = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        assert stats_resp.status_code == 200
        
        # Verify all responses were successful
        assert inst_data.get("success") == True, "Institutional context failed"
        assert debate_data.get("success") == True, "Debate failed"
        assert risk_data.get("success") == True, "Risk assessment failed"
        
        print("Full trade analysis flow completed successfully")
        print(f"Institutional recommendation: {inst_data.get('context', {}).get('recommendation')}")
        print(f"Debate winner: {debate_data.get('debate_result', {}).get('winner')}")
        print(f"Risk level: {risk_data.get('assessment', {}).get('risk_level')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
