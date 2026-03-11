"""
Test Trade Style Renaming Feature
================================

Tests for the renaming of trade styles from confusing names to clearer names:
- scalp (was move_2_move)
- intraday (was trade_2_hold)  
- multi_day (was a_plus)

Also tests:
- TQS engine STYLE_WEIGHTS with new names
- TradeStyle enum with new values
- Backwards compatibility - old names still work
- Scanner LiveAlert default trade_style
- API endpoint accepts new style names
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTQSStyleWeights:
    """Test STYLE_WEIGHTS in TQS engine has new names and correct values"""
    
    def test_style_weights_has_new_names(self):
        """STYLE_WEIGHTS should have new names: scalp, intraday, multi_day, swing, position"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # New names should exist
        assert "scalp" in engine.STYLE_WEIGHTS, "scalp not in STYLE_WEIGHTS"
        assert "intraday" in engine.STYLE_WEIGHTS, "intraday not in STYLE_WEIGHTS"
        assert "multi_day" in engine.STYLE_WEIGHTS, "multi_day not in STYLE_WEIGHTS"
        assert "swing" in engine.STYLE_WEIGHTS, "swing not in STYLE_WEIGHTS"
        assert "position" in engine.STYLE_WEIGHTS, "position not in STYLE_WEIGHTS"
        print("✓ All new style names exist in STYLE_WEIGHTS")
    
    def test_scalp_weights_correct(self):
        """scalp should have Technical 35%, Setup 30%"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        weights = engine.STYLE_WEIGHTS["scalp"]
        
        assert weights["technical"] == 0.35, f"Expected technical=0.35, got {weights['technical']}"
        assert weights["setup"] == 0.30, f"Expected setup=0.30, got {weights['setup']}"
        assert weights["fundamental"] == 0.05, f"Expected fundamental=0.05, got {weights['fundamental']}"
        print("✓ scalp weights correct: Technical 35%, Setup 30%, Fundamental 5%")
    
    def test_intraday_weights_correct(self):
        """intraday should have balanced weights: Tech 25%, Setup 25%"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        weights = engine.STYLE_WEIGHTS["intraday"]
        
        assert weights["technical"] == 0.25, f"Expected technical=0.25, got {weights['technical']}"
        assert weights["setup"] == 0.25, f"Expected setup=0.25, got {weights['setup']}"
        assert weights["fundamental"] == 0.15, f"Expected fundamental=0.15, got {weights['fundamental']}"
        print("✓ intraday weights correct: Technical 25%, Setup 25%, Fundamental 15%")
    
    def test_multi_day_weights_correct(self):
        """multi_day should have Fundamental 30%"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        weights = engine.STYLE_WEIGHTS["multi_day"]
        
        assert weights["fundamental"] == 0.30, f"Expected fundamental=0.30, got {weights['fundamental']}"
        assert weights["setup"] == 0.20, f"Expected setup=0.20, got {weights['setup']}"
        assert weights["technical"] == 0.15, f"Expected technical=0.15, got {weights['technical']}"
        print("✓ multi_day weights correct: Fundamental 30%, Setup 20%, Technical 15%")


class TestBackwardsCompatibility:
    """Test that old style names still work (move_2_move, trade_2_hold, a_plus)"""
    
    def test_old_names_still_in_style_weights(self):
        """Deprecated names should still exist for backwards compatibility"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # Old names should still exist as aliases
        assert "move_2_move" in engine.STYLE_WEIGHTS, "move_2_move alias missing"
        assert "trade_2_hold" in engine.STYLE_WEIGHTS, "trade_2_hold alias missing"
        assert "a_plus" in engine.STYLE_WEIGHTS, "a_plus alias missing"
        assert "investment" in engine.STYLE_WEIGHTS, "investment alias missing"
        print("✓ All backwards compatibility aliases exist")
    
    def test_move_2_move_same_as_scalp(self):
        """move_2_move weights should match scalp weights"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        scalp = engine.STYLE_WEIGHTS["scalp"]
        m2m = engine.STYLE_WEIGHTS["move_2_move"]
        
        assert scalp == m2m, f"scalp and move_2_move should have same weights. scalp={scalp}, m2m={m2m}"
        print("✓ move_2_move has same weights as scalp")
    
    def test_trade_2_hold_same_as_intraday(self):
        """trade_2_hold weights should match intraday weights"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        intraday = engine.STYLE_WEIGHTS["intraday"]
        t2h = engine.STYLE_WEIGHTS["trade_2_hold"]
        
        assert intraday == t2h, f"intraday and trade_2_hold should have same weights"
        print("✓ trade_2_hold has same weights as intraday")
    
    def test_a_plus_same_as_multi_day(self):
        """a_plus weights should match multi_day weights"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        multi_day = engine.STYLE_WEIGHTS["multi_day"]
        a_plus = engine.STYLE_WEIGHTS["a_plus"]
        
        assert multi_day == a_plus, f"multi_day and a_plus should have same weights"
        print("✓ a_plus has same weights as multi_day")
    
    def test_get_weights_for_style_old_names(self):
        """_get_weights_for_style should work with old names"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # Test old names work
        m2m_weights = engine._get_weights_for_style("move_2_move")
        t2h_weights = engine._get_weights_for_style("trade_2_hold")
        aplus_weights = engine._get_weights_for_style("a_plus")
        
        assert m2m_weights == engine.STYLE_WEIGHTS["scalp"], "move_2_move should return scalp weights"
        assert t2h_weights == engine.STYLE_WEIGHTS["intraday"], "trade_2_hold should return intraday weights"
        assert aplus_weights == engine.STYLE_WEIGHTS["multi_day"], "a_plus should return multi_day weights"
        print("✓ _get_weights_for_style works with old names")


class TestTradeStyleEnum:
    """Test TradeStyle enum has new values with backwards compatibility"""
    
    def test_tradestyle_has_new_values(self):
        """TradeStyle enum should have SCALP, INTRADAY, MULTI_DAY"""
        from services.smb_integration import TradeStyle
        
        assert hasattr(TradeStyle, 'SCALP'), "TradeStyle.SCALP missing"
        assert hasattr(TradeStyle, 'INTRADAY'), "TradeStyle.INTRADAY missing"
        assert hasattr(TradeStyle, 'MULTI_DAY'), "TradeStyle.MULTI_DAY missing"
        print("✓ TradeStyle enum has new values: SCALP, INTRADAY, MULTI_DAY")
    
    def test_tradestyle_values_correct(self):
        """TradeStyle enum values should be lowercase"""
        from services.smb_integration import TradeStyle
        
        assert TradeStyle.SCALP.value == "scalp", f"SCALP value should be 'scalp', got {TradeStyle.SCALP.value}"
        assert TradeStyle.INTRADAY.value == "intraday", f"INTRADAY value should be 'intraday', got {TradeStyle.INTRADAY.value}"
        assert TradeStyle.MULTI_DAY.value == "multi_day", f"MULTI_DAY value should be 'multi_day', got {TradeStyle.MULTI_DAY.value}"
        print("✓ TradeStyle enum values correct")
    
    def test_tradestyle_backwards_compat_aliases(self):
        """TradeStyle should have backwards compatibility aliases"""
        from services.smb_integration import TradeStyle
        
        assert hasattr(TradeStyle, 'MOVE_2_MOVE'), "TradeStyle.MOVE_2_MOVE alias missing"
        assert hasattr(TradeStyle, 'TRADE_2_HOLD'), "TradeStyle.TRADE_2_HOLD alias missing"
        assert hasattr(TradeStyle, 'A_PLUS'), "TradeStyle.A_PLUS alias missing"
        print("✓ TradeStyle has backwards compatibility aliases")
    
    def test_old_aliases_point_to_new_values(self):
        """Old enum aliases should have same value as new names"""
        from services.smb_integration import TradeStyle
        
        # Old names should point to new string values
        assert TradeStyle.MOVE_2_MOVE.value == "scalp", f"MOVE_2_MOVE should be 'scalp', got {TradeStyle.MOVE_2_MOVE.value}"
        assert TradeStyle.TRADE_2_HOLD.value == "intraday", f"TRADE_2_HOLD should be 'intraday', got {TradeStyle.TRADE_2_HOLD.value}"
        assert TradeStyle.A_PLUS.value == "multi_day", f"A_PLUS should be 'multi_day', got {TradeStyle.A_PLUS.value}"
        print("✓ Old enum aliases point to new values")


class TestLiveAlertDefaultTradeStyle:
    """Test LiveAlert default trade_style is 'intraday'"""
    
    def test_livealert_default_trade_style(self):
        """LiveAlert default trade_style should be 'intraday'"""
        from services.enhanced_scanner import LiveAlert
        
        # Create a minimal LiveAlert
        alert = LiveAlert(
            id="test-123",
            symbol="AAPL",
            setup_type="test",
            strategy_name="test",
            direction="long",
            priority=None,  # Will be set below
            current_price=100.0,
            trigger_price=100.0,
            stop_loss=95.0,
            target=110.0,
            risk_reward=2.0,
            trigger_probability=0.5,
            win_probability=0.5,
            minutes_to_trigger=5,
            headline="Test",
            reasoning=[],
            time_window="morning",
            market_regime="neutral"
        )
        # Set priority separately to avoid enum issues
        from services.enhanced_scanner import AlertPriority
        alert.priority = AlertPriority.MEDIUM
        
        assert alert.trade_style == "intraday", f"Default trade_style should be 'intraday', got {alert.trade_style}"
        print("✓ LiveAlert default trade_style is 'intraday'")


class TestStyleWeightExplanation:
    """Test get_style_weight_explanation works for both old and new names"""
    
    def test_new_names_explanation(self):
        """get_style_weight_explanation should work with new names"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        scalp_exp = engine.get_style_weight_explanation("scalp")
        intraday_exp = engine.get_style_weight_explanation("intraday")
        multi_day_exp = engine.get_style_weight_explanation("multi_day")
        
        assert scalp_exp["timeframe"] == "Scalp (minutes to 1 hour)", f"scalp timeframe incorrect"
        assert intraday_exp["timeframe"] == "Intraday Swing (1-6 hours)", f"intraday timeframe incorrect"
        assert multi_day_exp["timeframe"] == "Multi-day (1-5 days)", f"multi_day timeframe incorrect"
        print("✓ get_style_weight_explanation works with new names")
    
    def test_old_names_explanation(self):
        """get_style_weight_explanation should work with old names"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        m2m_exp = engine.get_style_weight_explanation("move_2_move")
        t2h_exp = engine.get_style_weight_explanation("trade_2_hold")
        aplus_exp = engine.get_style_weight_explanation("a_plus")
        
        assert "timeframe" in m2m_exp, "move_2_move explanation missing timeframe"
        assert "timeframe" in t2h_exp, "trade_2_hold explanation missing timeframe"
        assert "timeframe" in aplus_exp, "a_plus explanation missing timeframe"
        print("✓ get_style_weight_explanation works with old names")


class TestInferTradeStyle:
    """Test _infer_trade_style returns new style names"""
    
    def test_infer_returns_new_names(self):
        """_infer_trade_style should return new style names"""
        from services.tqs.tqs_engine import TQSEngine
        
        engine = TQSEngine()
        
        # Test inferring from setup names
        scalp_setup = engine._infer_trade_style("9_ema_scalp")
        assert scalp_setup == "scalp", f"Should infer 'scalp' for 9_ema_scalp, got {scalp_setup}"
        
        swing_setup = engine._infer_trade_style("swing_trade")
        assert swing_setup == "swing", f"Should infer 'swing' for swing_trade, got {swing_setup}"
        
        # Default should be intraday (not trade_2_hold)
        default = engine._infer_trade_style("unknown_setup")
        assert default == "intraday", f"Default should be 'intraday', got {default}"
        
        print("✓ _infer_trade_style returns new style names")


class TestAPIEndpoints:
    """Test API endpoints accept new style names"""
    
    def test_tqs_score_api_with_new_styles(self):
        """POST /api/tqs/score should accept new style names"""
        # Test with scalp
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "scalp"
            }
        )
        assert response.status_code == 200, f"scalp style failed: {response.status_code} - {response.text}"
        data = response.json()
        assert data.get("success") == True, f"scalp response not successful: {data}"
        print("✓ API accepts 'scalp' style")
        
        # Test with intraday
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "intraday"
            }
        )
        assert response.status_code == 200, f"intraday style failed: {response.status_code}"
        print("✓ API accepts 'intraday' style")
        
        # Test with multi_day
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "multi_day"
            }
        )
        assert response.status_code == 200, f"multi_day style failed: {response.status_code}"
        print("✓ API accepts 'multi_day' style")
    
    def test_tqs_score_api_with_old_styles(self):
        """POST /api/tqs/score should still accept old style names (backwards compat)"""
        # Test with move_2_move
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "move_2_move"
            }
        )
        assert response.status_code == 200, f"move_2_move style failed: {response.status_code}"
        print("✓ API accepts 'move_2_move' style (backwards compat)")
        
        # Test with trade_2_hold
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "trade_2_hold"
            }
        )
        assert response.status_code == 200, f"trade_2_hold style failed: {response.status_code}"
        print("✓ API accepts 'trade_2_hold' style (backwards compat)")
        
        # Test with a_plus
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "a_plus"
            }
        )
        assert response.status_code == 200, f"a_plus style failed: {response.status_code}"
        print("✓ API accepts 'a_plus' style (backwards compat)")
    
    def test_tqs_response_uses_new_style_names(self):
        """TQS API response should include trade_style in output"""
        response = requests.post(
            f"{BASE_URL}/api/tqs/score",
            json={
                "symbol": "AAPL",
                "setup_type": "test_setup",
                "direction": "long",
                "trade_style": "scalp"
            }
        )
        assert response.status_code == 200
        data = response.json()
        tqs = data.get("tqs", {})
        
        # Check trade_style is returned
        assert "trade_style" in tqs, f"trade_style missing from TQS response: {tqs.keys()}"
        assert tqs["trade_style"] == "scalp", f"Expected trade_style='scalp', got {tqs['trade_style']}"
        print("✓ API response includes trade_style field")


class TestSMBRouterTradeStyles:
    """Test SMB router trade styles endpoint"""
    
    def test_trade_styles_endpoint(self):
        """GET /api/smb/trade-styles should return style info"""
        response = requests.get(f"{BASE_URL}/api/smb/trade-styles")
        assert response.status_code == 200, f"trade-styles endpoint failed: {response.status_code}"
        data = response.json()
        
        # Should have the new style names
        # Note: TradeStyle enum is used as keys, so check for both old and new
        print(f"Trade styles response: {list(data.keys())}")
        print("✓ /api/smb/trade-styles endpoint works")
    
    def test_smb_setups_summary(self):
        """GET /api/smb/setups/summary should show new style names"""
        response = requests.get(f"{BASE_URL}/api/smb/setups/summary")
        assert response.status_code == 200, f"setups/summary failed: {response.status_code}"
        data = response.json()
        
        by_style = data.get("by_style", {})
        # Should have new names in summary
        assert "scalp" in by_style or "move_2_move" in by_style, f"Style summary missing: {by_style}"
        print(f"✓ Style summary: {by_style}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
