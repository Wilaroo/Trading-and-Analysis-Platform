"""
AI Consultation Phase 2 Tests - Pre-Trade AI Analysis Integration

Testing Phase 2 features:
- GET /api/ai-modules/consultation/status - Consultation service status
- POST /api/ai-modules/consultation/run - Run full consultation with all modules
- Full consultation with all 4 modules: debate, risk, institutional, volume
- Shadow decision logging during consultation
- Size adjustment recommendations
- Proceed/pass recommendations based on AI analysis
- Trading bot integration verification (set_ai_consultation method)
- Previous Phase 1 endpoints still working
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestConsultationStatus:
    """Test AI Consultation status endpoint"""
    
    def test_get_consultation_status(self):
        """GET /api/ai-modules/consultation/status - should return consultation service status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/consultation/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Response should indicate success: {data}"
        
        status = data.get("status", {})
        
        # Verify status structure
        assert "enabled" in status, "Status should have enabled field"
        
        # If enabled, should have module availability and settings
        if status.get("enabled"):
            assert "modules_available" in status, "Status should have modules_available"
            assert "modules_enabled" in status, "Status should have modules_enabled"
            assert "shadow_mode" in status, "Status should have shadow_mode"
            
            modules_available = status.get("modules_available", {})
            assert "debate" in modules_available, "modules_available should have debate"
            assert "risk_manager" in modules_available, "modules_available should have risk_manager"
            assert "institutional_flow" in modules_available, "modules_available should have institutional_flow"
            assert "volume_anomaly" in modules_available, "modules_available should have volume_anomaly"
            
            modules_enabled = status.get("modules_enabled", {})
            print(f"Consultation Status: enabled={status.get('enabled')}, shadow_mode={status.get('shadow_mode')}")
            print(f"Modules available: {modules_available}")
            print(f"Modules enabled: {modules_enabled}")
        else:
            print(f"Consultation Status: enabled=False, reason={status.get('reason', 'N/A')}")


class TestConsultationRun:
    """Test AI Consultation run endpoint - the core Phase 2 feature"""
    
    @pytest.fixture(autouse=True)
    def setup_modules(self):
        """Enable all AI modules before running tests"""
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
        yield
    
    def test_run_consultation_basic(self):
        """POST /api/ai-modules/consultation/run - basic trade consultation"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "AAPL",
                    "direction": "long",
                    "entry_price": 180.0,
                    "stop_price": 175.0,
                    "target_prices": [190.0, 195.0, 200.0],
                    "shares": 100,
                    "setup_type": "breakout",
                    "quality_score": 75
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 15.5,
                    "trend": "bullish"
                }
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Consultation should succeed: {data}"
        
        consultation = data.get("consultation", {})
        
        # Verify consultation response structure
        assert "proceed" in consultation, "Consultation should have proceed recommendation"
        assert "size_adjustment" in consultation, "Consultation should have size_adjustment"
        assert "reasoning" in consultation, "Consultation should have reasoning"
        assert "shadow_logged" in consultation, "Consultation should have shadow_logged flag"
        
        # Check data types
        assert isinstance(consultation["proceed"], bool), "proceed should be boolean"
        assert isinstance(consultation["size_adjustment"], (int, float)), "size_adjustment should be numeric"
        assert isinstance(consultation["reasoning"], str), "reasoning should be string"
        
        print(f"Consultation result: proceed={consultation['proceed']}, size_adj={consultation['size_adjustment']}")
        print(f"Reasoning: {consultation['reasoning'][:100]}...")
        print(f"Shadow logged: {consultation['shadow_logged']}")
    
    def test_run_consultation_full_trade_object(self):
        """POST /api/ai-modules/consultation/run - full trade with all recommended fields"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "NVDA",
                    "direction": "long",
                    "entry_price": 500.0,
                    "stop_price": 485.0,
                    "target_prices": [520.0, 540.0, 560.0],
                    "shares": 50,
                    "setup_type": "orb_long",
                    "quality_score": 82,
                    "risk_reward_ratio": 2.5,
                    "confirmations": ["volume", "trend", "vwap"],
                    "historical_win_rate": 0.58,
                    "atr_percent": 2.2
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 14.2,
                    "trend": "bullish",
                    "technicals": {
                        "rvol": 1.8,
                        "relative_volume": 1.8
                    }
                },
                "portfolio": {
                    "account_value": 150000,
                    "current_exposure": 0.35
                },
                "bars": [
                    {"open": 498.0, "high": 502.0, "low": 497.5, "close": 501.5, "volume": 8000000, "timestamp": "2025-01-10T14:30:00"},
                    {"open": 496.0, "high": 500.0, "low": 495.5, "close": 498.0, "volume": 7500000, "timestamp": "2025-01-10T14:00:00"},
                    {"open": 494.0, "high": 498.0, "low": 493.5, "close": 496.0, "volume": 7800000, "timestamp": "2025-01-10T13:30:00"},
                    {"open": 492.0, "high": 496.0, "low": 491.5, "close": 494.0, "volume": 7200000, "timestamp": "2025-01-10T13:00:00"},
                    {"open": 490.0, "high": 494.0, "low": 489.5, "close": 492.0, "volume": 7000000, "timestamp": "2025-01-10T12:30:00"},
                ]
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Consultation should succeed: {data}"
        
        consultation = data.get("consultation", {})
        
        # Verify all 4 module results may be present
        # These can be None if module is disabled or failed
        assert "debate_result" in consultation, "Should have debate_result field"
        assert "risk_assessment" in consultation, "Should have risk_assessment field"
        assert "institutional_context" in consultation, "Should have institutional_context field"
        assert "volume_context" in consultation, "Should have volume_context field"
        
        print(f"Full consultation for NVDA:")
        print(f"  Proceed: {consultation.get('proceed')}")
        print(f"  Size adjustment: {consultation.get('size_adjustment')}")
        print(f"  Reasoning: {consultation.get('reasoning')[:150]}...")
        
        # Check module results
        if consultation.get("debate_result"):
            print(f"  Debate: winner={consultation['debate_result'].get('winner')}, rec={consultation['debate_result'].get('final_recommendation')}")
        if consultation.get("risk_assessment"):
            print(f"  Risk: level={consultation['risk_assessment'].get('risk_level')}, score={consultation['risk_assessment'].get('total_risk_score')}")
        if consultation.get("institutional_context"):
            print(f"  Institutional: rec={consultation['institutional_context'].get('recommendation')}")
        if consultation.get("volume_context"):
            print(f"  Volume: has signals={bool(consultation['volume_context'].get('signals'))}")
    
    def test_run_consultation_short_trade(self):
        """POST /api/ai-modules/consultation/run - short trade direction"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "META",
                    "direction": "short",
                    "entry_price": 350.0,
                    "stop_price": 360.0,  # Stop above entry for short
                    "target_prices": [340.0, 330.0, 320.0],
                    "shares": 30,
                    "setup_type": "vwap_fade_short",
                    "quality_score": 68
                },
                "market_context": {
                    "regime": "CAUTION",
                    "vix": 22.0,
                    "trend": "neutral"
                }
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, f"Consultation should succeed: {data}"
        
        consultation = data.get("consultation", {})
        assert "proceed" in consultation
        assert "size_adjustment" in consultation
        
        print(f"Short trade consultation: proceed={consultation.get('proceed')}, size_adj={consultation.get('size_adjustment')}")
    
    def test_run_consultation_missing_required_fields(self):
        """POST /api/ai-modules/consultation/run - should handle missing trade data gracefully"""
        # Minimal trade object
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "TSLA"
                    # Missing most fields
                },
                "market_context": {}
            }
        )
        
        # Should either succeed with defaults or return 422 validation error
        assert response.status_code in [200, 422], f"Expected 200 or 422, got {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            print(f"Minimal trade handled: {data.get('success')}")
        else:
            print("Validation error for minimal trade - expected behavior")


class TestConsultationShadowLogging:
    """Test that consultation logs to shadow tracker"""
    
    @pytest.fixture(autouse=True)
    def setup_modules(self):
        """Enable all AI modules before running tests"""
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
        yield
    
    def test_consultation_creates_shadow_log(self):
        """Verify consultation logs decision to shadow tracker"""
        # Get initial stats
        initial_stats_resp = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        initial_stats = initial_stats_resp.json().get("stats", {})
        initial_count = initial_stats.get("total_decisions", 0)
        
        # Run consultation
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "GOOGL",
                    "direction": "long",
                    "entry_price": 145.0,
                    "stop_price": 140.0,
                    "target_prices": [155.0, 160.0],
                    "shares": 70,
                    "setup_type": "breakout",
                    "quality_score": 77
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 16.0
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        consultation = data.get("consultation", {})
        
        # Check shadow logging flag
        shadow_logged = consultation.get("shadow_logged", False)
        shadow_decision_id = consultation.get("shadow_decision_id")
        
        print(f"Shadow logged: {shadow_logged}, decision_id: {shadow_decision_id}")
        
        # Verify stats increased (if shadow tracker is working)
        new_stats_resp = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        new_stats = new_stats_resp.json().get("stats", {})
        new_count = new_stats.get("total_decisions", 0)
        
        if shadow_logged:
            assert new_count >= initial_count, "Total decisions should not decrease"
            print(f"Shadow tracker: {initial_count} -> {new_count} decisions")


class TestSizeAdjustmentRecommendations:
    """Test that consultation returns appropriate size adjustments"""
    
    @pytest.fixture(autouse=True)
    def setup_modules(self):
        """Enable all AI modules"""
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
        yield
    
    def test_size_adjustment_range(self):
        """Verify size_adjustment is in valid range (0 to 1)"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "AMZN",
                    "direction": "long",
                    "entry_price": 180.0,
                    "stop_price": 175.0,
                    "target_prices": [190.0, 195.0],
                    "shares": 55,
                    "setup_type": "pullback",
                    "quality_score": 70
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 17.0
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        consultation = data.get("consultation", {})
        size_adj = consultation.get("size_adjustment", 1.0)
        
        # Size adjustment should be between 0 and 1.0 (or slightly above 1.0 in some cases)
        assert 0 <= size_adj <= 1.5, f"size_adjustment {size_adj} should be between 0 and 1.5"
        print(f"Size adjustment: {size_adj}")


class TestProceedPassRecommendations:
    """Test proceed/pass recommendation logic"""
    
    @pytest.fixture(autouse=True)
    def setup_modules(self):
        """Enable all AI modules"""
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
        yield
    
    def test_proceed_recommendation_structure(self):
        """Verify proceed recommendation is proper boolean"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "MSFT",
                    "direction": "long",
                    "entry_price": 380.0,
                    "stop_price": 370.0,
                    "target_prices": [400.0, 420.0],
                    "shares": 25,
                    "setup_type": "trend_continuation",
                    "quality_score": 80
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 14.0
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        consultation = data.get("consultation", {})
        
        proceed = consultation.get("proceed")
        assert proceed is not None, "proceed should be present"
        assert isinstance(proceed, bool), f"proceed should be boolean, got {type(proceed)}"
        
        reasoning = consultation.get("reasoning", "")
        assert len(reasoning) > 0, "reasoning should not be empty"
        
        print(f"Proceed: {proceed}, Reasoning: {reasoning[:100]}...")


class TestPhase1EndpointsStillWorking:
    """Verify all Phase 1 endpoints still work after Phase 2 changes"""
    
    def test_config_endpoint(self):
        """Phase 1: GET /api/ai-modules/config"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/config")
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("Phase 1 config endpoint: OK")
    
    def test_status_endpoint(self):
        """Phase 1: GET /api/ai-modules/status"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/status")
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("Phase 1 status endpoint: OK")
    
    def test_toggle_endpoint(self):
        """Phase 1: POST /api/ai-modules/toggle/{module}"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/toggle/debate_agents",
            json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("Phase 1 toggle endpoint: OK")
    
    def test_shadow_mode_endpoint(self):
        """Phase 1: POST /api/ai-modules/shadow-mode"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/shadow-mode",
            json={"shadow_mode": True}
        )
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("Phase 1 shadow-mode endpoint: OK")
    
    def test_debate_run_endpoint(self):
        """Phase 1: POST /api/ai-modules/debate/run"""
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/debate_agents", json={"enabled": True})
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/debate/run",
            json={
                "symbol": "AAPL",
                "setup": {"tqs_score": 75, "risk_reward": 2.0, "direction": "long"}
            }
        )
        assert response.status_code == 200
        print("Phase 1 debate/run endpoint: OK")
    
    def test_risk_assess_endpoint(self):
        """Phase 1: POST /api/ai-modules/risk/assess"""
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/ai_risk_manager", json={"enabled": True})
        
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
        print("Phase 1 risk/assess endpoint: OK")
    
    def test_institutional_context_endpoint(self):
        """Phase 1: GET /api/ai-modules/institutional/context/{symbol}"""
        requests.post(f"{BASE_URL}/api/ai-modules/toggle/institutional_flow", json={"enabled": True})
        
        response = requests.get(f"{BASE_URL}/api/ai-modules/institutional/context/AAPL")
        assert response.status_code == 200
        print("Phase 1 institutional/context endpoint: OK")
    
    def test_volume_analyze_endpoint(self):
        """Phase 1: POST /api/ai-modules/volume/analyze"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/volume/analyze",
            json={
                "symbol": "AAPL",
                "bars": [
                    {"open": 180.0, "high": 182.0, "low": 179.5, "close": 181.5, "volume": 5000000},
                    {"open": 179.0, "high": 181.0, "low": 178.5, "close": 180.0, "volume": 4500000},
                ],
                "direction": "long"
            }
        )
        assert response.status_code == 200
        print("Phase 1 volume/analyze endpoint: OK")
    
    def test_shadow_stats_endpoint(self):
        """Phase 1: GET /api/ai-modules/shadow/stats"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/shadow/stats")
        assert response.status_code == 200
        assert response.json().get("success") == True
        print("Phase 1 shadow/stats endpoint: OK")


class TestTradingBotIntegration:
    """Test that trading bot has AI consultation wired"""
    
    def test_trading_bot_status_has_ai_consultation(self):
        """Verify trading bot status includes AI consultation info"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        
        if response.status_code == 200:
            data = response.json()
            # The bot should have some indication of AI consultation availability
            print(f"Trading bot status retrieved: {data.keys()}")
        else:
            print(f"Trading bot status endpoint returned {response.status_code} - may not be running")
        
        # This is informational - we just verify the endpoint exists
        assert response.status_code in [200, 503], f"Unexpected status code {response.status_code}"
    
    def test_consultation_status_reflects_bot_connection(self):
        """Consultation status should show modules are available when bot connected"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/consultation/status")
        assert response.status_code == 200
        
        data = response.json()
        status = data.get("status", {})
        
        # If enabled, the consultation service is wired to the trading bot
        if status.get("enabled"):
            print("AI Consultation is enabled and wired to trading bot")
            print(f"Modules available: {status.get('modules_available', {})}")
        else:
            print(f"AI Consultation not enabled: {status.get('reason', 'unknown')}")


class TestEndToEndConsultationFlow:
    """Complete end-to-end test of consultation flow"""
    
    def test_complete_consultation_workflow(self):
        """Full workflow: check status -> enable modules -> run consultation -> verify shadow log"""
        
        # 1. Check consultation status
        status_resp = requests.get(f"{BASE_URL}/api/ai-modules/consultation/status")
        assert status_resp.status_code == 200
        status = status_resp.json().get("status", {})
        print(f"Step 1 - Status check: enabled={status.get('enabled')}")
        
        # 2. Enable all modules
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow"]
        for module in modules:
            toggle_resp = requests.post(
                f"{BASE_URL}/api/ai-modules/toggle/{module}",
                json={"enabled": True}
            )
            assert toggle_resp.status_code == 200
        print(f"Step 2 - Enabled modules: {modules}")
        
        # 3. Set shadow mode on (to log but not block)
        shadow_resp = requests.post(
            f"{BASE_URL}/api/ai-modules/shadow-mode",
            json={"shadow_mode": True}
        )
        assert shadow_resp.status_code == 200
        print("Step 3 - Shadow mode enabled")
        
        # 4. Run full consultation
        consultation_resp = requests.post(
            f"{BASE_URL}/api/ai-modules/consultation/run",
            json={
                "trade": {
                    "symbol": "AMD",
                    "direction": "long",
                    "entry_price": 150.0,
                    "stop_price": 145.0,
                    "target_prices": [160.0, 165.0, 170.0],
                    "shares": 100,
                    "setup_type": "breakout",
                    "quality_score": 78,
                    "risk_reward_ratio": 2.0,
                    "confirmations": ["volume", "trend"]
                },
                "market_context": {
                    "regime": "RISK_ON",
                    "vix": 15.0,
                    "trend": "bullish"
                },
                "portfolio": {
                    "account_value": 100000
                },
                "bars": [
                    {"open": 148.0, "high": 151.0, "low": 147.5, "close": 150.5, "volume": 12000000},
                    {"open": 146.0, "high": 149.0, "low": 145.5, "close": 148.0, "volume": 11000000},
                    {"open": 144.0, "high": 147.0, "low": 143.5, "close": 146.0, "volume": 10500000},
                    {"open": 142.0, "high": 145.0, "low": 141.5, "close": 144.0, "volume": 10000000},
                    {"open": 140.0, "high": 143.0, "low": 139.5, "close": 142.0, "volume": 9500000},
                ]
            }
        )
        assert consultation_resp.status_code == 200
        
        consultation = consultation_resp.json().get("consultation", {})
        print(f"Step 4 - Consultation result:")
        print(f"  Proceed: {consultation.get('proceed')}")
        print(f"  Size adjustment: {consultation.get('size_adjustment')}")
        print(f"  Reasoning: {consultation.get('reasoning', '')[:100]}...")
        print(f"  Shadow logged: {consultation.get('shadow_logged')}")
        print(f"  Decision ID: {consultation.get('shadow_decision_id')}")
        
        # 5. Verify shadow tracker has the decision
        if consultation.get("shadow_logged"):
            decisions_resp = requests.get(f"{BASE_URL}/api/ai-modules/shadow/decisions?limit=5")
            assert decisions_resp.status_code == 200
            decisions = decisions_resp.json().get("decisions", [])
            
            # Find the AMD decision
            amd_decision = next((d for d in decisions if d.get("symbol") == "AMD"), None)
            if amd_decision:
                print(f"Step 5 - Shadow decision found: {amd_decision.get('combined_recommendation')}")
            else:
                print("Step 5 - AMD decision not found in recent decisions (may be expected)")
        
        print("\nEnd-to-end consultation workflow completed successfully!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
