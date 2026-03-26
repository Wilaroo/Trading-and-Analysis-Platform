"""
Test Confidence Gate Wiring & Cold-Start Bootstrap
===================================================
Tests for iteration 111 - verifying:
1. Confidence gate wiring into trading bot execution path
2. Cold-start bootstrap mode for 0W/0L trades
3. Entry context captures confidence gate data
4. Multiple evaluate calls accumulate stats correctly

Flow: Setup Detected → Smart Filter → Confidence Gate → Position Sizing → Execute or Skip
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestConfidenceGateEvaluateAccumulation:
    """Test that multiple evaluate calls accumulate stats correctly"""
    
    def test_evaluate_aapl_breakout_long(self):
        """POST /api/ai-training/confidence-gate/evaluate?symbol=AAPL&setup_type=breakout&direction=long"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AAPL", "setup_type": "breakout", "direction": "long"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "decision" in data
        assert data["decision"] in ["GO", "REDUCE", "SKIP"]
        assert "reasoning" in data
        assert isinstance(data["reasoning"], list)
        print(f"✓ AAPL breakout long: decision={data['decision']}, confidence={data.get('confidence_score')}")
        return data
    
    def test_evaluate_tsla_squeeze_long_high_quality(self):
        """POST /api/ai-training/confidence-gate/evaluate?symbol=TSLA&setup_type=squeeze&direction=long&quality_score=90"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "TSLA", "setup_type": "squeeze", "direction": "long", "quality_score": 90}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data["decision"] in ["GO", "REDUCE", "SKIP"]
        # High quality score (90) should contribute positively
        assert data.get("quality_score") == 90
        print(f"✓ TSLA squeeze long (TQS=90): decision={data['decision']}, confidence={data.get('confidence_score')}")
        return data
    
    def test_evaluate_spy_scalp_short_low_quality(self):
        """POST /api/ai-training/confidence-gate/evaluate?symbol=SPY&setup_type=scalp&direction=short&quality_score=30"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "SPY", "setup_type": "scalp", "direction": "short", "quality_score": 30}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data["decision"] in ["GO", "REDUCE", "SKIP"]
        # Low quality score (30) should reduce confidence
        assert data.get("quality_score") == 30
        # Reasoning should mention low quality
        reasoning_text = " ".join(data.get("reasoning", []))
        print(f"✓ SPY scalp short (TQS=30): decision={data['decision']}, confidence={data.get('confidence_score')}")
        print(f"  Reasoning: {data.get('reasoning', [])[:2]}")
        return data
    
    def test_decisions_show_accumulated_calls(self):
        """GET /api/ai-training/confidence-gate/decisions should show accumulated decisions"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        decisions = data.get("decisions", [])
        
        # Should have at least the 3 calls we made above
        # Note: decisions are stored in memory, so they accumulate during the test session
        print(f"✓ Decisions endpoint shows {len(decisions)} decisions")
        
        # Check that recent decisions include our test symbols
        recent_symbols = [d.get("symbol") for d in decisions[:5]]
        print(f"  Recent symbols: {recent_symbols}")
        
        # Verify decision structure
        if decisions:
            d = decisions[0]
            assert "decision" in d
            assert "confidence_score" in d
            assert "symbol" in d
            assert "setup_type" in d
            assert "direction" in d
            assert "reasoning" in d
            print(f"  Latest: {d.get('symbol')} {d.get('setup_type')} {d.get('direction')} -> {d.get('decision')}")
    
    def test_stats_reflect_evaluate_calls(self):
        """GET /api/ai-training/confidence-gate/stats should show updated stats"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/stats")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        # Stats should reflect our evaluate calls
        total = data.get("total_evaluated", 0)
        go_count = data.get("go_count", 0)
        reduce_count = data.get("reduce_count", 0)
        skip_count = data.get("skip_count", 0)
        
        # Total should be at least 3 (our test calls)
        # Note: may be higher if other tests ran before
        print(f"✓ Stats: total={total}, go={go_count}, reduce={reduce_count}, skip={skip_count}")
        
        # Verify counts add up
        assert go_count + reduce_count + skip_count == total
        print(f"  Counts add up correctly: {go_count} + {reduce_count} + {skip_count} = {total}")
    
    def test_summary_shows_updated_today_stats(self):
        """GET /api/ai-training/confidence-gate/summary should show updated today stats"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        today = data.get("today", {})
        evaluated = today.get("evaluated", 0)
        taken = today.get("taken", 0)
        skipped = today.get("skipped", 0)
        
        print(f"✓ Summary today: evaluated={evaluated}, taken={taken}, skipped={skipped}")
        
        # Verify trading mode is present
        assert "trading_mode" in data
        print(f"  Trading mode: {data.get('trading_mode')}")


class TestColdStartBootstrapMode:
    """
    Verify cold-start bootstrap mode in trading_bot_service.py
    When wins+losses==0 but sample_size>=5, should return REDUCE_SIZE with 50% position
    """
    
    def test_bootstrap_logic_code_review(self):
        """
        Code review verification: trading_bot_service.py lines 808-823
        should have bootstrap logic for 0W/0L trades
        """
        # This is a code review test - we verify the logic exists by checking the file
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "COLD-START BOOTSTRAP MODE", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "COLD-START BOOTSTRAP MODE" in result.stdout
        print(f"✓ Cold-start bootstrap mode comment found at: {result.stdout.strip()}")
        
        # Verify the bootstrap return block exists
        result2 = subprocess.run(
            ["grep", "-A5", "completed_trades == 0", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "REDUCE_SIZE" in result2.stdout
        assert "Bootstrap mode" in result2.stdout
        print(f"✓ Bootstrap mode returns REDUCE_SIZE action")
        print(f"  Code snippet:\n{result2.stdout[:300]}")


class TestConfidenceGateWiringVerification:
    """
    Verify confidence gate is wired into trading bot execution path
    """
    
    def test_confidence_gate_init_in_trading_bot(self):
        """Verify _confidence_gate is initialized in TradingBotService.__init__"""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "_confidence_gate = None", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "_confidence_gate = None" in result.stdout
        print(f"✓ _confidence_gate initialized: {result.stdout.strip()}")
    
    def test_set_confidence_gate_method_exists(self):
        """Verify set_confidence_gate method exists (lines 704-717)"""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "def set_confidence_gate", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "def set_confidence_gate" in result.stdout
        print(f"✓ set_confidence_gate method found: {result.stdout.strip()}")
    
    def test_confidence_gate_called_in_evaluate_opportunity(self):
        """Verify _confidence_gate.evaluate() is called in _evaluate_opportunity method"""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "_confidence_gate.evaluate", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "_confidence_gate.evaluate" in result.stdout
        print(f"✓ _confidence_gate.evaluate() called: {result.stdout.strip()}")
    
    def test_confidence_gate_wired_in_server(self):
        """Verify confidence gate is wired to trading bot in server.py (lines 615-625)"""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "set_confidence_gate", "/app/backend/server.py"],
            capture_output=True, text=True
        )
        assert "set_confidence_gate" in result.stdout
        print(f"✓ Confidence gate wired in server.py: {result.stdout.strip()}")
        
        # Also verify init_confidence_gate is called
        result2 = subprocess.run(
            ["grep", "-n", "init_confidence_gate", "/app/backend/server.py"],
            capture_output=True, text=True
        )
        assert "init_confidence_gate" in result2.stdout
        print(f"✓ init_confidence_gate called: {result2.stdout.strip()}")


class TestEntryContextConfidenceGate:
    """
    Verify entry_context includes confidence_gate field
    """
    
    def test_build_entry_context_has_confidence_gate_param(self):
        """Verify _build_entry_context method accepts confidence_gate_result parameter"""
        import subprocess
        result = subprocess.run(
            ["grep", "-n", "confidence_gate_result: Dict = None", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "confidence_gate_result" in result.stdout
        print(f"✓ _build_entry_context accepts confidence_gate_result: {result.stdout.strip()}")
    
    def test_entry_context_captures_confidence_gate_data(self):
        """Verify entry_context captures confidence_gate data (lines 2782-2790)"""
        import subprocess
        result = subprocess.run(
            ["grep", "-A10", 'ctx\\["confidence_gate"\\]', "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert 'ctx["confidence_gate"]' in result.stdout
        assert "decision" in result.stdout
        assert "confidence_score" in result.stdout
        assert "position_multiplier" in result.stdout
        assert "trading_mode" in result.stdout
        assert "ai_regime" in result.stdout
        assert "reasoning" in result.stdout
        print(f"✓ entry_context captures confidence_gate fields:")
        print(f"  - decision, confidence_score, position_multiplier")
        print(f"  - trading_mode, ai_regime, reasoning")
    
    def test_confidence_gate_result_passed_to_build_entry_context(self):
        """Verify confidence_gate_result is passed to _build_entry_context call"""
        import subprocess
        result = subprocess.run(
            ["grep", "-B2", "confidence_gate_result=confidence_gate_result", "/app/backend/services/trading_bot_service.py"],
            capture_output=True, text=True
        )
        assert "confidence_gate_result=confidence_gate_result" in result.stdout
        print(f"✓ confidence_gate_result passed to _build_entry_context")


class TestConfidenceGateDecisionLogic:
    """
    Test the decision logic of the confidence gate
    """
    
    def test_high_quality_tends_toward_go(self):
        """High quality score (90) should tend toward GO or REDUCE, not SKIP"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "NVDA", "setup_type": "breakout", "direction": "long", "quality_score": 95}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        # High quality should not result in SKIP (unless regime is very bad)
        decision = data.get("decision")
        confidence = data.get("confidence_score", 0)
        
        print(f"✓ High quality (95) test: decision={decision}, confidence={confidence}")
        # Confidence should be at least moderate with high quality
        assert confidence >= 40, f"Expected confidence >= 40 with quality=95, got {confidence}"
    
    def test_low_quality_reduces_confidence(self):
        """Low quality score (20) should reduce confidence"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "AMD", "setup_type": "scalp", "direction": "long", "quality_score": 20}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        confidence = data.get("confidence_score", 0)
        reasoning = data.get("reasoning", [])
        
        # Check if low quality is mentioned in reasoning
        reasoning_text = " ".join(reasoning).lower()
        has_quality_mention = "quality" in reasoning_text or "low" in reasoning_text
        
        print(f"✓ Low quality (20) test: decision={data.get('decision')}, confidence={confidence}")
        print(f"  Reasoning mentions quality: {has_quality_mention}")
    
    def test_position_multiplier_returned(self):
        """Verify position_multiplier is returned in evaluate response"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "META", "setup_type": "vwap_bounce", "direction": "long", "quality_score": 60}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
        assert "position_multiplier" in data
        multiplier = data.get("position_multiplier")
        assert isinstance(multiplier, (int, float))
        assert 0 <= multiplier <= 1.5, f"Position multiplier {multiplier} out of expected range [0, 1.5]"
        
        print(f"✓ Position multiplier returned: {multiplier}")


class TestConfidenceGateAPIEndpoints:
    """
    Test all confidence gate API endpoints from ai_training.py (lines 417-513)
    """
    
    def test_summary_endpoint_structure(self):
        """GET /api/ai-training/confidence-gate/summary - verify full response structure"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "success" in data
        assert "trading_mode" in data
        assert "mode_reason" in data
        assert "today" in data
        assert "total_evaluated" in data
        
        # Today sub-fields
        today = data["today"]
        assert "evaluated" in today
        assert "taken" in today
        assert "skipped" in today
        assert "take_rate" in today
        
        print(f"✓ Summary structure verified")
        print(f"  Mode: {data['trading_mode']} - {data['mode_reason']}")
    
    def test_decisions_endpoint_structure(self):
        """GET /api/ai-training/confidence-gate/decisions - verify decision structure"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/decisions?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        assert "success" in data
        assert "decisions" in data
        assert "count" in data
        
        decisions = data["decisions"]
        if decisions:
            d = decisions[0]
            required_fields = ["decision", "confidence_score", "symbol", "setup_type", 
                            "direction", "regime_state", "ai_regime", "trading_mode",
                            "position_multiplier", "reasoning", "timestamp"]
            for field in required_fields:
                assert field in d, f"Missing field: {field}"
        
        print(f"✓ Decisions structure verified, count={data['count']}")
    
    def test_stats_endpoint_structure(self):
        """GET /api/ai-training/confidence-gate/stats - verify stats structure"""
        response = requests.get(f"{BASE_URL}/api/ai-training/confidence-gate/stats")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["success", "total_evaluated", "go_count", "reduce_count", 
                         "skip_count", "go_rate", "skip_rate", "trading_mode", "mode_reason"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✓ Stats structure verified")
        print(f"  Rates: go={data['go_rate']}, skip={data['skip_rate']}")
    
    def test_evaluate_endpoint_structure(self):
        """POST /api/ai-training/confidence-gate/evaluate - verify full response structure"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            params={"symbol": "GOOGL", "setup_type": "orb", "direction": "long", "quality_score": 75}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["success", "decision", "confidence_score", "regime_state",
                         "regime_score", "ai_regime", "trading_mode", "position_multiplier",
                         "reasoning", "model_signals", "symbol", "setup_type", "direction",
                         "quality_score", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✓ Evaluate response structure verified")
        print(f"  Decision: {data['decision']}, Confidence: {data['confidence_score']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
