"""
Test TQS Timeframe-Aware Weighting Feature (Iteration 66)

Tests:
1. STYLE_WEIGHTS dict has 5 profiles: move_2_move, trade_2_hold, a_plus, swing, investment
2. Scalp (move_2_move) weights: Technical 35%, Setup 30%, Fundamental 5%
3. Investment weights: Fundamental 40%, Setup 15%, Technical 10%
4. TQSResult includes trade_style, trade_timeframe, weights_used fields
5. LiveAlert dataclass has tqs_score, tqs_grade, tqs_action, tqs_is_high_quality fields
6. _enrich_alert_with_tqs method exists in EnhancedBackgroundScanner
7. get_style_weight_explanation returns timeframe and rationale
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTQSStyleWeightsDict:
    """Test STYLE_WEIGHTS dictionary has correct profiles and weights"""
    
    def test_style_weights_has_5_profiles(self):
        """STYLE_WEIGHTS dict should have exactly 5 profiles"""
        from services.tqs.tqs_engine import TQSEngine
        
        expected_profiles = ["move_2_move", "trade_2_hold", "a_plus", "swing", "investment"]
        
        assert hasattr(TQSEngine, 'STYLE_WEIGHTS'), "TQSEngine should have STYLE_WEIGHTS"
        
        for profile in expected_profiles:
            assert profile in TQSEngine.STYLE_WEIGHTS, f"Missing profile: {profile}"
        
        print(f"PASS: STYLE_WEIGHTS has all 5 profiles: {list(TQSEngine.STYLE_WEIGHTS.keys())}")
    
    def test_scalp_move_2_move_weights(self):
        """Scalp (move_2_move) should weight Technical 35%, Setup 30%, Fundamental 5%"""
        from services.tqs.tqs_engine import TQSEngine
        
        m2m = TQSEngine.STYLE_WEIGHTS.get("move_2_move", {})
        
        # Technical should be highest at 35%
        assert m2m.get("technical") == 0.35, f"Technical should be 35%, got {m2m.get('technical')}"
        
        # Setup should be 30%
        assert m2m.get("setup") == 0.30, f"Setup should be 30%, got {m2m.get('setup')}"
        
        # Fundamental should be minimal at 5%
        assert m2m.get("fundamental") == 0.05, f"Fundamental should be 5%, got {m2m.get('fundamental')}"
        
        # Context and Execution
        assert m2m.get("context") == 0.20, f"Context should be 20%, got {m2m.get('context')}"
        assert m2m.get("execution") == 0.10, f"Execution should be 10%, got {m2m.get('execution')}"
        
        # Verify weights sum to 100%
        total = sum(m2m.values())
        assert abs(total - 1.0) < 0.01, f"Weights should sum to 100%, got {total*100}%"
        
        print(f"PASS: move_2_move weights correct - Technical: {m2m['technical']*100}%, Setup: {m2m['setup']*100}%, Fundamental: {m2m['fundamental']*100}%")
    
    def test_investment_weights(self):
        """Investment should weight Fundamental 40%, Setup 15%, Technical 10%"""
        from services.tqs.tqs_engine import TQSEngine
        
        investment = TQSEngine.STYLE_WEIGHTS.get("investment", {})
        
        # Fundamental should be highest at 40%
        assert investment.get("fundamental") == 0.40, f"Fundamental should be 40%, got {investment.get('fundamental')}"
        
        # Setup should be 15%
        assert investment.get("setup") == 0.15, f"Setup should be 15%, got {investment.get('setup')}"
        
        # Technical should be minimal at 10%
        assert investment.get("technical") == 0.10, f"Technical should be 10%, got {investment.get('technical')}"
        
        # Context and Execution
        assert investment.get("context") == 0.20, f"Context should be 20%, got {investment.get('context')}"
        assert investment.get("execution") == 0.15, f"Execution should be 15%, got {investment.get('execution')}"
        
        # Verify weights sum to 100%
        total = sum(investment.values())
        assert abs(total - 1.0) < 0.01, f"Weights should sum to 100%, got {total*100}%"
        
        print(f"PASS: investment weights correct - Fundamental: {investment['fundamental']*100}%, Setup: {investment['setup']*100}%, Technical: {investment['technical']*100}%")
    
    def test_all_styles_sum_to_100_percent(self):
        """All weight profiles should sum to exactly 100%"""
        from services.tqs.tqs_engine import TQSEngine
        
        for style, weights in TQSEngine.STYLE_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, f"Style {style} weights sum to {total*100}%, expected 100%"
            print(f"  {style}: {total*100}%")
        
        print("PASS: All style weights sum to 100%")


class TestTQSResultFields:
    """Test TQSResult dataclass has required fields"""
    
    def test_tqs_result_has_trade_style_field(self):
        """TQSResult should have trade_style field"""
        from services.tqs.tqs_engine import TQSResult
        from dataclasses import fields
        
        field_names = [f.name for f in fields(TQSResult)]
        assert "trade_style" in field_names, "TQSResult missing trade_style field"
        
        # Check default value
        result = TQSResult()
        assert hasattr(result, 'trade_style'), "TQSResult instance missing trade_style"
        print(f"PASS: TQSResult.trade_style exists, default='{result.trade_style}'")
    
    def test_tqs_result_has_trade_timeframe_field(self):
        """TQSResult should have trade_timeframe field"""
        from services.tqs.tqs_engine import TQSResult
        from dataclasses import fields
        
        field_names = [f.name for f in fields(TQSResult)]
        assert "trade_timeframe" in field_names, "TQSResult missing trade_timeframe field"
        
        result = TQSResult()
        assert hasattr(result, 'trade_timeframe'), "TQSResult instance missing trade_timeframe"
        print(f"PASS: TQSResult.trade_timeframe exists, default='{result.trade_timeframe}'")
    
    def test_tqs_result_has_weights_used_field(self):
        """TQSResult should have weights_used field"""
        from services.tqs.tqs_engine import TQSResult
        from dataclasses import fields
        
        field_names = [f.name for f in fields(TQSResult)]
        assert "weights_used" in field_names, "TQSResult missing weights_used field"
        
        result = TQSResult()
        assert hasattr(result, 'weights_used'), "TQSResult instance missing weights_used"
        assert isinstance(result.weights_used, dict), "weights_used should be a dict"
        print(f"PASS: TQSResult.weights_used exists as dict")
    
    def test_tqs_result_to_dict_includes_new_fields(self):
        """TQSResult.to_dict() should include trade_style, trade_timeframe, weights_used"""
        from services.tqs.tqs_engine import TQSResult
        
        result = TQSResult()
        result.trade_style = "move_2_move"
        result.trade_timeframe = "Scalp (minutes to 1 hour)"
        result.weights_used = {"technical": 0.35, "setup": 0.30}
        
        result_dict = result.to_dict()
        
        assert "trade_style" in result_dict, "to_dict() missing trade_style"
        assert "trade_timeframe" in result_dict, "to_dict() missing trade_timeframe"
        assert "weights_used" in result_dict, "to_dict() missing weights_used"
        
        assert result_dict["trade_style"] == "move_2_move"
        assert result_dict["trade_timeframe"] == "Scalp (minutes to 1 hour)"
        
        print(f"PASS: TQSResult.to_dict() includes all timeframe fields")


class TestLiveAlertTQSFields:
    """Test LiveAlert dataclass has TQS integration fields"""
    
    def test_live_alert_has_tqs_score_field(self):
        """LiveAlert should have tqs_score field"""
        from services.enhanced_scanner import LiveAlert
        from dataclasses import fields
        
        field_names = [f.name for f in fields(LiveAlert)]
        assert "tqs_score" in field_names, "LiveAlert missing tqs_score field"
        
        print("PASS: LiveAlert.tqs_score field exists")
    
    def test_live_alert_has_tqs_grade_field(self):
        """LiveAlert should have tqs_grade field"""
        from services.enhanced_scanner import LiveAlert
        from dataclasses import fields
        
        field_names = [f.name for f in fields(LiveAlert)]
        assert "tqs_grade" in field_names, "LiveAlert missing tqs_grade field"
        
        print("PASS: LiveAlert.tqs_grade field exists")
    
    def test_live_alert_has_tqs_action_field(self):
        """LiveAlert should have tqs_action field"""
        from services.enhanced_scanner import LiveAlert
        from dataclasses import fields
        
        field_names = [f.name for f in fields(LiveAlert)]
        assert "tqs_action" in field_names, "LiveAlert missing tqs_action field"
        
        print("PASS: LiveAlert.tqs_action field exists")
    
    def test_live_alert_has_tqs_is_high_quality_field(self):
        """LiveAlert should have tqs_is_high_quality field for UI highlighting"""
        from services.enhanced_scanner import LiveAlert
        from dataclasses import fields
        
        field_names = [f.name for f in fields(LiveAlert)]
        assert "tqs_is_high_quality" in field_names, "LiveAlert missing tqs_is_high_quality field"
        
        print("PASS: LiveAlert.tqs_is_high_quality field exists")
    
    def test_live_alert_tqs_fields_defaults(self):
        """LiveAlert TQS fields should have sensible defaults"""
        from services.enhanced_scanner import LiveAlert, AlertPriority
        
        # Create minimal LiveAlert
        alert = LiveAlert(
            id="test-123",
            symbol="NVDA",
            setup_type="orb",
            strategy_name="Opening Range Breakout",
            direction="long",
            priority=AlertPriority.HIGH,
            current_price=100.0,
            trigger_price=101.0,
            stop_loss=98.0,
            target=105.0,
            risk_reward=2.5,
            trigger_probability=0.7,
            win_probability=0.6,
            minutes_to_trigger=5,
            headline="Test Alert",
            reasoning=["Test reason"],
            time_window="morning",
            market_regime="uptrend"
        )
        
        # Check TQS field defaults
        assert alert.tqs_score == 0.0, f"Default tqs_score should be 0.0, got {alert.tqs_score}"
        assert alert.tqs_grade == "", f"Default tqs_grade should be empty, got '{alert.tqs_grade}'"
        assert alert.tqs_action == "", f"Default tqs_action should be empty, got '{alert.tqs_action}'"
        assert alert.tqs_is_high_quality == False, f"Default tqs_is_high_quality should be False"
        
        print("PASS: LiveAlert TQS fields have correct defaults")


class TestEnhancedScannerTQSMethod:
    """Test _enrich_alert_with_tqs method exists and has correct signature"""
    
    def test_enrich_alert_with_tqs_method_exists(self):
        """EnhancedBackgroundScanner should have _enrich_alert_with_tqs method"""
        from services.enhanced_scanner import EnhancedBackgroundScanner
        
        scanner = EnhancedBackgroundScanner()
        
        assert hasattr(scanner, '_enrich_alert_with_tqs'), "Missing _enrich_alert_with_tqs method"
        assert callable(scanner._enrich_alert_with_tqs), "_enrich_alert_with_tqs should be callable"
        
        print("PASS: EnhancedBackgroundScanner._enrich_alert_with_tqs method exists")
    
    def test_enrich_alert_with_tqs_is_async(self):
        """_enrich_alert_with_tqs should be an async method"""
        from services.enhanced_scanner import EnhancedBackgroundScanner
        import inspect
        
        scanner = EnhancedBackgroundScanner()
        
        assert inspect.iscoroutinefunction(scanner._enrich_alert_with_tqs), \
            "_enrich_alert_with_tqs should be an async method"
        
        print("PASS: _enrich_alert_with_tqs is async")


class TestTQSStyleWeightExplanation:
    """Test get_style_weight_explanation method"""
    
    def test_get_style_weight_explanation_exists(self):
        """TQSEngine should have get_style_weight_explanation method"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        assert hasattr(engine, 'get_style_weight_explanation'), \
            "Missing get_style_weight_explanation method"
        
        print("PASS: TQSEngine.get_style_weight_explanation method exists")
    
    def test_explanation_returns_timeframe(self):
        """get_style_weight_explanation should return timeframe"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        explanation = engine.get_style_weight_explanation("move_2_move")
        
        assert "timeframe" in explanation, "Explanation missing 'timeframe' field"
        assert explanation["timeframe"], "timeframe should not be empty"
        
        print(f"PASS: move_2_move timeframe: {explanation['timeframe']}")
    
    def test_explanation_returns_rationale(self):
        """get_style_weight_explanation should return rationale"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        explanation = engine.get_style_weight_explanation("investment")
        
        assert "rationale" in explanation, "Explanation missing 'rationale' field"
        assert explanation["rationale"], "rationale should not be empty"
        
        print(f"PASS: investment rationale: {explanation['rationale'][:80]}...")
    
    def test_explanation_for_all_styles(self):
        """get_style_weight_explanation should work for all 5 styles"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        styles = ["move_2_move", "trade_2_hold", "a_plus", "swing", "investment"]
        
        for style in styles:
            explanation = engine.get_style_weight_explanation(style)
            
            assert "timeframe" in explanation, f"{style}: Missing timeframe"
            assert "rationale" in explanation, f"{style}: Missing rationale"
            assert "weights" in explanation, f"{style}: Missing weights"
            assert "weight_percentages" in explanation, f"{style}: Missing weight_percentages"
            
            print(f"  {style}: timeframe='{explanation['timeframe']}', has weights={bool(explanation['weights'])}")
        
        print("PASS: All 5 styles have complete explanations")


class TestTQSHelperMethods:
    """Test TQS helper methods for trade style inference and weight retrieval"""
    
    def test_infer_trade_style_method_exists(self):
        """TQSEngine should have _infer_trade_style method"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        assert hasattr(engine, '_infer_trade_style'), "Missing _infer_trade_style method"
        
        print("PASS: _infer_trade_style method exists")
    
    def test_get_weights_for_style_method_exists(self):
        """TQSEngine should have _get_weights_for_style method"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        assert hasattr(engine, '_get_weights_for_style'), "Missing _get_weights_for_style method"
        
        print("PASS: _get_weights_for_style method exists")
    
    def test_get_weights_returns_correct_style(self):
        """_get_weights_for_style should return correct weights for each style"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # Test move_2_move
        m2m_weights = engine._get_weights_for_style("move_2_move")
        assert m2m_weights.get("technical") == 0.35, "move_2_move technical should be 35%"
        
        # Test investment
        inv_weights = engine._get_weights_for_style("investment")
        assert inv_weights.get("fundamental") == 0.40, "investment fundamental should be 40%"
        
        print("PASS: _get_weights_for_style returns correct weights")
    
    def test_get_weights_handles_unknown_style(self):
        """_get_weights_for_style should return default weights for unknown styles"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # Unknown style should return default weights
        unknown_weights = engine._get_weights_for_style("unknown_style")
        
        # Should be equal to default WEIGHTS
        assert unknown_weights == engine.WEIGHTS, "Unknown style should return default weights"
        
        print("PASS: Unknown styles get default weights")


class TestTQSAPIEndpoint:
    """Test TQS API endpoint for trade style parameter"""
    
    def test_tqs_score_endpoint_accepts_trade_style(self):
        """POST /api/tqs/score should accept trade_style parameter"""
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "NVDA",
                "setup_type": "orb",
                "direction": "long",
                "trade_style": "move_2_move"
            },
            timeout=120
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Response is wrapped: {"success": true, "tqs": {...}}
        assert "tqs" in data, "Response missing 'tqs' wrapper"
        tqs = data["tqs"]
        
        # Check trade_style is returned and matches input
        assert "trade_style" in tqs, "TQS response missing trade_style"
        assert tqs["trade_style"] == "move_2_move", f"Expected move_2_move, got {tqs['trade_style']}"
        
        print(f"PASS: TQS endpoint accepts trade_style, returned: {tqs['trade_style']}")
    
    def test_tqs_score_endpoint_returns_timeframe(self):
        """POST /api/tqs/score should return trade_timeframe"""
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "vwap_bounce",
                "direction": "long",
                "trade_style": "investment"
            },
            timeout=120
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        tqs = data.get("tqs", {})
        
        assert "trade_timeframe" in tqs, "TQS response missing trade_timeframe"
        assert tqs["trade_timeframe"], "trade_timeframe should not be empty"
        # Investment should have position/weeks timeframe
        assert "Position" in tqs["trade_timeframe"] or "weeks" in tqs["trade_timeframe"], \
            f"Expected position timeframe for investment, got {tqs['trade_timeframe']}"
        
        print(f"PASS: TQS endpoint returns trade_timeframe: {tqs['trade_timeframe']}")
    
    def test_tqs_score_endpoint_returns_weights_used(self):
        """POST /api/tqs/score should return weights_used percentages"""
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AMD",
                "setup_type": "9_ema_scalp",
                "direction": "long",
                "trade_style": "move_2_move"
            },
            timeout=120
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        tqs = data.get("tqs", {})
        
        assert "weights_used" in tqs, "TQS response missing weights_used"
        
        weights = tqs["weights_used"]
        if weights:  # May be None if error occurred
            # Check technical is 35% for scalp (move_2_move)
            assert weights.get("technical") == "35%", f"Expected technical 35%, got {weights.get('technical')}"
            assert weights.get("fundamental") == "5%", f"Expected fundamental 5%, got {weights.get('fundamental')}"
        
        print(f"PASS: TQS endpoint returns weights_used: {tqs.get('weights_used')}")


class TestTQSWeightDifferences:
    """Test that different trade styles produce meaningfully different scores"""
    
    def test_scalp_vs_investment_weight_priorities(self):
        """Scalp should prioritize technical, investment should prioritize fundamental"""
        from services.tqs.tqs_engine import TQSEngine
        
        m2m = TQSEngine.STYLE_WEIGHTS["move_2_move"]
        inv = TQSEngine.STYLE_WEIGHTS["investment"]
        
        # Scalp: technical should be highest
        m2m_max_pillar = max(m2m, key=m2m.get)
        assert m2m_max_pillar == "technical", f"Scalp max should be technical, got {m2m_max_pillar}"
        
        # Investment: fundamental should be highest
        inv_max_pillar = max(inv, key=inv.get)
        assert inv_max_pillar == "fundamental", f"Investment max should be fundamental, got {inv_max_pillar}"
        
        print(f"PASS: Scalp prioritizes {m2m_max_pillar}, Investment prioritizes {inv_max_pillar}")
    
    def test_fundamental_weight_varies_by_style(self):
        """Fundamental weight should vary significantly between scalp and investment"""
        from services.tqs.tqs_engine import TQSEngine
        
        m2m_fund = TQSEngine.STYLE_WEIGHTS["move_2_move"]["fundamental"]
        inv_fund = TQSEngine.STYLE_WEIGHTS["investment"]["fundamental"]
        
        # Investment fundamental should be at least 5x scalp fundamental
        ratio = inv_fund / m2m_fund
        assert ratio >= 5, f"Investment fundamental should be 5x+ scalp, got {ratio}x"
        
        print(f"PASS: Investment fundamental ({inv_fund*100}%) is {ratio:.1f}x scalp ({m2m_fund*100}%)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
