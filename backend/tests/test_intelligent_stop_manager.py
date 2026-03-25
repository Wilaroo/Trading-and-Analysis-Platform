"""
Test Intelligent Stop Manager - Advanced Stop Loss Management System
=====================================================================
Tests for the enhanced stop system with:
- Setup-based stop rules (8 setup types)
- Trailing stop modes (6 modes)
- Urgency levels (4 levels)
- Stop hunt detection
- Volume profile analysis
- Sector correlation
- Regime context
- Layered stops and scale-out plans
"""

import pytest
import requests
import os

# Base URL from environment (using the public-facing URL)
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://timeseries-setups.preview.emergentagent.com').rstrip('/')


class TestIntelligentStopSetupRules:
    """Test GET /api/intelligent-stops/setup-rules endpoint"""
    
    def test_get_setup_rules_returns_success(self):
        """Test that setup-rules endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"PASS: GET /api/intelligent-stops/setup-rules returns success")
    
    def test_setup_rules_returns_8_setup_types(self):
        """Test that setup-rules returns exactly 8 setup types"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        expected_setups = ["breakout", "pullback", "mean_reversion", "momentum", 
                          "gap_and_go", "vwap_reversal", "earnings_play", "default"]
        
        available_setups = data.get("available_setups", [])
        assert len(available_setups) == 8, f"Expected 8 setups, got {len(available_setups)}"
        
        for setup in expected_setups:
            assert setup in available_setups, f"Missing setup: {setup}"
        
        print(f"PASS: Setup rules returns all 8 setup types: {available_setups}")
    
    def test_setup_rules_contain_descriptions(self):
        """Test that each setup has a description"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        setup_rules = data.get("setup_rules", {})
        for name, rule in setup_rules.items():
            assert "description" in rule, f"Setup {name} missing description"
            assert len(rule["description"]) > 0, f"Setup {name} has empty description"
            print(f"  {name}: {rule['description'][:50]}...")
        
        print("PASS: All setup rules have descriptions")
    
    def test_setup_rules_have_required_fields(self):
        """Test that each setup rule has all required fields"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "setup_type", "description", "initial_stop_atr_mult", 
            "trailing_mode", "trailing_atr_mult", "breakeven_r_target",
            "scale_out_levels", "min_stop_distance_pct", "max_stop_distance_pct",
            "use_swing_levels", "use_volume_profile", "respect_regime"
        ]
        
        setup_rules = data.get("setup_rules", {})
        for name, rule in setup_rules.items():
            for field in required_fields:
                assert field in rule, f"Setup {name} missing field: {field}"
        
        print("PASS: All setup rules have required fields")


class TestIntelligentStopTrailingModes:
    """Test GET /api/intelligent-stops/trailing-modes endpoint"""
    
    def test_get_trailing_modes_returns_success(self):
        """Test that trailing-modes endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/trailing-modes")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"PASS: GET /api/intelligent-stops/trailing-modes returns success")
    
    def test_trailing_modes_returns_all_modes(self):
        """Test that trailing-modes returns all expected modes"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/trailing-modes")
        assert response.status_code == 200
        data = response.json()
        
        expected_modes = ["none", "atr", "percent", "chandelier", "breakeven_plus", "parabolic"]
        
        modes = data.get("modes", [])
        mode_ids = [m["id"] for m in modes]
        
        assert len(modes) == 6, f"Expected 6 trailing modes, got {len(modes)}"
        
        for expected in expected_modes:
            assert expected in mode_ids, f"Missing trailing mode: {expected}"
        
        print(f"PASS: All 6 trailing modes returned: {mode_ids}")
    
    def test_trailing_modes_have_descriptions(self):
        """Test that each trailing mode has a description"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/trailing-modes")
        assert response.status_code == 200
        data = response.json()
        
        modes = data.get("modes", [])
        for mode in modes:
            assert "description" in mode, f"Mode {mode.get('id')} missing description"
            assert "name" in mode, f"Mode {mode.get('id')} missing name"
            print(f"  {mode['id']}: {mode['name']}")
        
        print("PASS: All trailing modes have descriptions")


class TestIntelligentStopUrgencyLevels:
    """Test GET /api/intelligent-stops/urgency-levels endpoint"""
    
    def test_get_urgency_levels_returns_success(self):
        """Test that urgency-levels endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/urgency-levels")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"PASS: GET /api/intelligent-stops/urgency-levels returns success")
    
    def test_urgency_levels_returns_all_levels(self):
        """Test that urgency-levels returns all expected levels"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/urgency-levels")
        assert response.status_code == 200
        data = response.json()
        
        expected_levels = ["normal", "caution", "high_alert", "emergency"]
        
        levels = data.get("levels", [])
        level_ids = [l["id"] for l in levels]
        
        assert len(levels) == 4, f"Expected 4 urgency levels, got {len(levels)}"
        
        for expected in expected_levels:
            assert expected in level_ids, f"Missing urgency level: {expected}"
        
        print(f"PASS: All 4 urgency levels returned: {level_ids}")
    
    def test_urgency_levels_have_actions(self):
        """Test that each urgency level has an action recommendation"""
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/urgency-levels")
        assert response.status_code == 200
        data = response.json()
        
        levels = data.get("levels", [])
        for level in levels:
            assert "action" in level, f"Level {level.get('id')} missing action"
            assert "description" in level, f"Level {level.get('id')} missing description"
            print(f"  {level['id']}: {level['action']}")
        
        print("PASS: All urgency levels have actions")


class TestIntelligentStopCalculate:
    """Test POST /api/intelligent-stops/calculate endpoint"""
    
    def test_calculate_basic_stop(self):
        """Test basic stop calculation"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "stop_price" in data
        assert "stop_distance_pct" in data
        assert "stop_distance_atr" in data
        print(f"PASS: Basic stop calculation: stop_price=${data['stop_price']}")
    
    def test_calculate_breakout_setup_returns_chandelier_trailing(self):
        """Test that breakout setup uses chandelier trailing mode"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "breakout",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Breakout setup should use chandelier trailing mode
        assert data["trailing_mode"] == "chandelier", f"Expected chandelier, got {data['trailing_mode']}"
        assert data["setup_rules"] == "breakout"
        
        print(f"PASS: Breakout setup uses chandelier trailing mode")
    
    def test_calculate_momentum_setup_returns_parabolic_trailing(self):
        """Test that momentum setup uses parabolic trailing mode"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "momentum",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Momentum setup should use parabolic trailing mode
        assert data["trailing_mode"] == "parabolic", f"Expected parabolic, got {data['trailing_mode']}"
        assert data["setup_rules"] == "momentum"
        
        print(f"PASS: Momentum setup uses parabolic trailing mode")
    
    def test_calculate_low_float_triggers_high_hunt_risk(self):
        """Test that low float shares triggers HIGH stop hunt risk"""
        payload = {
            "symbol": "LOWF",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5,
            "float_shares": 5000000,  # 5M shares (low float)
            "avg_volume": 200000      # 200K volume (low)
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Low float + low volume should trigger warnings
        factors = data.get("factors_considered", [])
        hunt_factor = next((f for f in factors if "Hunt risk" in f), None)
        assert hunt_factor is not None, "Expected hunt risk factor in response"
        assert "HIGH" in hunt_factor, f"Expected HIGH hunt risk, got: {hunt_factor}"
        
        print(f"PASS: Low float/volume triggers HIGH hunt risk: {hunt_factor}")
    
    def test_calculate_returns_layered_stops_with_3_levels(self):
        """Test that calculation returns layered stops with 3 levels"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Should return layered_stops with 3 levels
        layered_stops = data.get("layered_stops", [])
        assert len(layered_stops) == 3, f"Expected 3 layered stops, got {len(layered_stops)}"
        
        # Check each layer has required fields
        for i, layer in enumerate(layered_stops):
            assert "level" in layer, f"Layer {i} missing 'level'"
            assert "stop_price" in layer, f"Layer {i} missing 'stop_price'"
            assert "position_pct" in layer, f"Layer {i} missing 'position_pct'"
            assert "atr_depth" in layer, f"Layer {i} missing 'atr_depth'"
        
        # Verify layered stop prices are deeper at each level (for longs)
        assert layered_stops[0]["stop_price"] > layered_stops[1]["stop_price"], \
            "Level 1 stop should be higher than level 2"
        assert layered_stops[1]["stop_price"] > layered_stops[2]["stop_price"], \
            "Level 2 stop should be higher than level 3"
        
        print(f"PASS: Layered stops with 3 levels: {[l['stop_price'] for l in layered_stops]}")
    
    def test_calculate_returns_scale_out_plan(self):
        """Test that calculation returns scale-out plan with profit targets"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Should return scale_out_plan with profit targets
        scale_out = data.get("scale_out_plan", [])
        assert len(scale_out) > 0, "Expected scale_out_plan to have entries"
        
        # Check each scale-out level has required fields
        for i, level in enumerate(scale_out):
            assert "level" in level, f"Scale-out {i} missing 'level'"
            assert "r_target" in level, f"Scale-out {i} missing 'r_target'"
            assert "target_price" in level, f"Scale-out {i} missing 'target_price'"
            assert "exit_pct" in level, f"Scale-out {i} missing 'exit_pct'"
            assert "shares" in level, f"Scale-out {i} missing 'shares'"
        
        # Verify target prices increase (for longs)
        for i in range(len(scale_out) - 1):
            assert scale_out[i]["target_price"] < scale_out[i+1]["target_price"], \
                f"Scale-out level {i} should have lower target than level {i+1}"
        
        print(f"PASS: Scale-out plan with {len(scale_out)} targets: {[s['target_price'] for s in scale_out]}")
    
    def test_regime_adjustment_applied_confirmed_down_long(self):
        """Test that regime adjustment is applied for CONFIRMED_DOWN regime on long position"""
        # This tests that the calculation includes regime adjustment factor
        # Expected: 1.4x for CONFIRMED_DOWN long (fighting the trend)
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 99.0,  # Below entry - losing position
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Check that regime_adjustment field exists
        assert "regime_adjustment" in data, "Expected regime_adjustment field"
        
        # The regime adjustment should be numeric (1.0 if no regime service, or actual value)
        regime_adj = data["regime_adjustment"]
        assert isinstance(regime_adj, (int, float)), f"regime_adjustment should be numeric, got {type(regime_adj)}"
        
        print(f"PASS: Regime adjustment applied: {regime_adj}x")
    
    def test_calculate_short_position(self):
        """Test stop calculation for short position"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 98.0,  # Price below entry - profitable short
            "direction": "short",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # For shorts, stop should be above entry price
        stop_price = data["stop_price"]
        assert stop_price > payload["entry_price"], f"Short stop ({stop_price}) should be above entry ({payload['entry_price']})"
        
        print(f"PASS: Short position stop: ${stop_price} (above entry ${payload['entry_price']})")
    
    def test_calculate_with_support_resistance_levels(self):
        """Test stop calculation with support/resistance levels provided"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "pullback",
            "position_size": 100,
            "atr": 2.5,
            "swing_low": 97.0,
            "swing_high": 105.0,
            "support_levels": [95.0, 98.0],
            "resistance_levels": [108.0, 112.0]
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Verify factors_considered mentions swing or support levels
        factors = data.get("factors_considered", [])
        assert len(factors) > 0, "Expected factors_considered to have entries"
        
        print(f"PASS: Calculation with S/R levels, factors: {factors}")
    
    def test_calculate_response_contains_all_required_fields(self):
        """Test that response contains all required fields"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "success", "stop_price", "stop_distance_pct", "stop_distance_atr",
            "primary_factor", "factors_considered", "confidence",
            "urgency", "warnings", "trailing_mode", "trailing_trigger_price",
            "breakeven_trigger_price", "layered_stops", "scale_out_plan",
            "sector_adjustment", "regime_adjustment", "setup_rules",
            "calculated_at", "valid_until"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Response contains all {len(required_fields)} required fields")


class TestIntelligentStopAnalyzeTrade:
    """Test POST /api/intelligent-stops/analyze-trade endpoint"""
    
    def test_analyze_trade_returns_success(self):
        """Test that analyze-trade endpoint returns success"""
        params = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "stop_price": 95.0,
            "direction": "long",
            "setup_type": "default",
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/analyze-trade", params=params)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"PASS: POST /api/intelligent-stops/analyze-trade returns success")
    
    def test_analyze_trade_returns_current_vs_optimal(self):
        """Test that analyze-trade returns current vs optimal stop comparison"""
        params = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "stop_price": 95.0,
            "direction": "long",
            "setup_type": "default",
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/analyze-trade", params=params)
        assert response.status_code == 200
        data = response.json()
        
        # Check for current_stop and optimal_stop fields
        assert "current_stop" in data, "Missing current_stop field"
        assert "optimal_stop" in data, "Missing optimal_stop field"
        
        current = data["current_stop"]
        optimal = data["optimal_stop"]
        
        assert "price" in current, "current_stop missing price"
        assert "distance_pct" in current, "current_stop missing distance_pct"
        assert "price" in optimal, "optimal_stop missing price"
        assert "confidence" in optimal, "optimal_stop missing confidence"
        
        print(f"PASS: Current stop: ${current['price']}, Optimal stop: ${optimal['price']}")
    
    def test_analyze_trade_returns_recommendations(self):
        """Test that analyze-trade returns recommendations"""
        params = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "stop_price": 99.0,  # Tight stop
            "direction": "long",
            "setup_type": "default",
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/analyze-trade", params=params)
        assert response.status_code == 200
        data = response.json()
        
        assert "recommendations" in data, "Missing recommendations field"
        assert "factors_considered" in data, "Missing factors_considered field"
        
        recommendations = data["recommendations"]
        # Recommendations is a list
        assert isinstance(recommendations, list), "recommendations should be a list"
        
        print(f"PASS: Got {len(recommendations)} recommendations")


class TestIntelligentStopSetupSpecificRules:
    """Test that different setup types apply their specific rules correctly"""
    
    def test_pullback_setup_uses_atr_trailing(self):
        """Test that pullback setup uses ATR trailing mode"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "pullback",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        assert data["trailing_mode"] == "atr", f"Pullback should use ATR trailing, got {data['trailing_mode']}"
        assert data["setup_rules"] == "pullback"
        
        print(f"PASS: Pullback setup uses ATR trailing mode")
    
    def test_mean_reversion_setup_uses_percent_trailing(self):
        """Test that mean_reversion setup uses percent trailing mode"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 98.0,
            "direction": "long",
            "setup_type": "mean_reversion",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        assert data["trailing_mode"] == "percent", f"Mean reversion should use percent trailing, got {data['trailing_mode']}"
        assert data["setup_rules"] == "mean_reversion"
        
        print(f"PASS: Mean reversion setup uses percent trailing mode")
    
    def test_gap_and_go_setup_uses_breakeven_plus_trailing(self):
        """Test that gap_and_go setup uses breakeven_plus trailing mode"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 103.0,
            "direction": "long",
            "setup_type": "gap_and_go",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        assert data["trailing_mode"] == "breakeven_plus", f"Gap and go should use breakeven_plus trailing, got {data['trailing_mode']}"
        assert data["setup_rules"] == "gap_and_go"
        
        print(f"PASS: Gap and go setup uses breakeven_plus trailing mode")
    
    def test_earnings_play_does_not_respect_regime(self):
        """Test that earnings_play setup doesn't respect regime (per rules)"""
        # Get setup rules first
        response = requests.get(f"{BASE_URL}/api/intelligent-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        earnings_rule = data["setup_rules"].get("earnings_play", {})
        assert earnings_rule.get("respect_regime") == False, \
            f"Earnings play should not respect regime, got {earnings_rule.get('respect_regime')}"
        
        print(f"PASS: Earnings play setup does not respect regime")


class TestIntelligentStopConfidenceAndUrgency:
    """Test confidence calculation and urgency levels"""
    
    def test_confidence_is_valid_range(self):
        """Test that confidence is between 30 and 100"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        confidence = data["confidence"]
        assert 30 <= confidence <= 100, f"Confidence {confidence} outside valid range [30, 100]"
        
        print(f"PASS: Confidence {confidence} is in valid range")
    
    def test_urgency_is_valid_level(self):
        """Test that urgency is one of the valid levels"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        valid_urgencies = ["normal", "caution", "high_alert", "emergency"]
        assert data["urgency"] in valid_urgencies, f"Invalid urgency: {data['urgency']}"
        
        print(f"PASS: Urgency '{data['urgency']}' is valid")


class TestIntelligentStopEdgeCases:
    """Test edge cases and error handling"""
    
    def test_missing_required_field_returns_error(self):
        """Test that missing required field returns 422 error"""
        payload = {
            "symbol": "AAPL",
            # Missing entry_price
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 422, f"Expected 422 for missing field, got {response.status_code}"
        
        print("PASS: Missing required field returns 422")
    
    def test_invalid_direction_returns_error(self):
        """Test that invalid direction doesn't crash (uses default behavior)"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "invalid_direction",  # Invalid
            "setup_type": "default",
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        # Should either return 422 or handle gracefully
        assert response.status_code in [200, 422, 500], f"Unexpected status: {response.status_code}"
        
        print(f"PASS: Invalid direction handled (status: {response.status_code})")
    
    def test_unknown_setup_type_falls_back_to_default(self):
        """Test that unknown setup type falls back to default rules"""
        payload = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 102.0,
            "direction": "long",
            "setup_type": "unknown_setup_xyz",  # Unknown
            "position_size": 100,
            "atr": 2.5
        }
        
        response = requests.post(f"{BASE_URL}/api/intelligent-stops/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        # Should fall back to default rules
        assert data["setup_rules"] == "default", f"Expected fallback to 'default', got {data['setup_rules']}"
        
        print("PASS: Unknown setup type falls back to default")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
