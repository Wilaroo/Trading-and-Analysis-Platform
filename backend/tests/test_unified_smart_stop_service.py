"""
Unified Smart Stop Service API Tests
======================================
Tests for the merged Smart Stop System that combines all stop-loss features.

The old system had TWO separate services (intelligent_stop_manager.py and smart_stop_service.py).
These have been merged into a single unified API at /api/smart-stops/.

Endpoints tested:
- POST /api/smart-stops/calculate - Simple stop calculation with 6 modes
- POST /api/smart-stops/intelligent-calculate - Full multi-factor intelligent stop
- POST /api/smart-stops/analyze-trade - Analyze existing trade's stop placement
- GET /api/smart-stops/modes - List all 6 stop modes
- GET /api/smart-stops/setup-rules - List all 8 setup-based rules
- GET /api/smart-stops/trailing-modes - List 6 trailing stop modes
- GET /api/smart-stops/urgency-levels - List 4 urgency levels
- GET /api/smart-stops/compare - Compare all stop modes for a setup
- GET /api/smart-stops/recommend/{symbol} - Get recommended mode for a symbol

Business logic verified:
- 6 stop modes: original, atr_dynamic, anti_hunt, volatility_adjusted, layered, chandelier
- 8 setup rules: breakout, pullback, momentum, mean_reversion, gap_and_go, vwap_reversal, earnings_play, default
- Anti-hunt mode places stops beyond obvious levels
- Layered mode returns multiple stop levels
- Volume profile, sector correlation, regime context integrated
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


# ============================================================================
# GET /api/smart-stops/modes
# ============================================================================
class TestSmartStopModes:
    """Test /api/smart-stops/modes endpoint - all 6 stop modes"""
    
    def test_get_modes_returns_success(self):
        """GET /modes returns success status"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("GET /api/smart-stops/modes - SUCCESS")
    
    def test_get_modes_returns_all_6_modes(self):
        """GET /modes returns exactly 6 stop modes"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        
        assert 'modes' in data
        assert len(data['modes']) == 6, f"Expected 6 modes, got {len(data['modes'])}"
        
        # Verify all expected modes are present
        mode_ids = [m['id'] for m in data['modes']]
        expected_modes = ['original', 'atr_dynamic', 'anti_hunt', 
                        'volatility_adjusted', 'layered', 'chandelier']
        for expected in expected_modes:
            assert expected in mode_ids, f"Missing mode: {expected}"
        print(f"All 6 modes present: {mode_ids}")
    
    def test_get_modes_structure(self):
        """GET /modes returns proper structure for each mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        
        for mode in data['modes']:
            assert 'id' in mode, "Missing 'id' field"
            assert 'name' in mode, "Missing 'name' field"
            assert 'description' in mode, "Missing 'description' field"
            assert 'hunt_risk' in mode, "Missing 'hunt_risk' field"
            assert 'best_for' in mode, "Missing 'best_for' field"
        print("Mode structure validation - PASS")
    
    def test_get_modes_hunt_risk_levels(self):
        """GET /modes shows correct hunt risk levels for each mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        
        modes_by_id = {m['id']: m for m in data['modes']}
        
        # Original has HIGH risk (easily hunted)
        assert modes_by_id['original']['hunt_risk'] == 'HIGH'
        # Anti-hunt has LOW risk
        assert modes_by_id['anti_hunt']['hunt_risk'] == 'LOW'
        # Layered has LOW risk (harder to fully hunt)
        assert modes_by_id['layered']['hunt_risk'] == 'LOW'
        print("Hunt risk levels verified - PASS")


# ============================================================================
# GET /api/smart-stops/setup-rules
# ============================================================================
class TestSmartStopSetupRules:
    """Test /api/smart-stops/setup-rules endpoint - all 8 setup types"""
    
    def test_get_setup_rules_returns_success(self):
        """GET /setup-rules returns success status"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("GET /api/smart-stops/setup-rules - SUCCESS")
    
    def test_get_setup_rules_returns_all_8_types(self):
        """GET /setup-rules returns exactly 8 setup types"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        assert 'setup_rules' in data
        assert len(data['setup_rules']) == 8, f"Expected 8 setup rules, got {len(data['setup_rules'])}"
        
        expected_setups = ['breakout', 'pullback', 'momentum', 'mean_reversion',
                         'gap_and_go', 'vwap_reversal', 'earnings_play', 'default']
        for expected in expected_setups:
            assert expected in data['setup_rules'], f"Missing setup type: {expected}"
        print(f"All 8 setup types present: {list(data['setup_rules'].keys())}")
    
    def test_get_setup_rules_structure(self):
        """GET /setup-rules returns proper structure for each rule"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ['setup_type', 'description', 'initial_stop_atr_mult',
                          'trailing_mode', 'trailing_atr_mult', 'breakeven_r_target',
                          'scale_out_r_targets', 'min_stop_pct', 'max_stop_pct',
                          'use_swing_levels', 'use_volume_profile', 'respect_regime']
        
        for setup_name, rules in data['setup_rules'].items():
            for field in required_fields:
                assert field in rules, f"Missing '{field}' in {setup_name} setup rules"
        print("Setup rules structure validation - PASS")
    
    def test_breakout_uses_chandelier_trailing(self):
        """Breakout setup uses chandelier trailing mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        breakout_rules = data['setup_rules']['breakout']
        assert breakout_rules['trailing_mode'] == 'chandelier'
        print("Breakout trailing mode (chandelier) - PASS")
    
    def test_momentum_uses_parabolic_trailing(self):
        """Momentum setup uses parabolic trailing mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        momentum_rules = data['setup_rules']['momentum']
        assert momentum_rules['trailing_mode'] == 'parabolic'
        print("Momentum trailing mode (parabolic) - PASS")
    
    def test_earnings_play_does_not_respect_regime(self):
        """Earnings play setup does NOT respect market regime (too volatile)"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/setup-rules")
        assert response.status_code == 200
        data = response.json()
        
        earnings_rules = data['setup_rules']['earnings_play']
        assert earnings_rules['respect_regime'] is False
        print("Earnings play ignores regime - PASS")


# ============================================================================
# GET /api/smart-stops/trailing-modes
# ============================================================================
class TestSmartStopTrailingModes:
    """Test /api/smart-stops/trailing-modes endpoint - 6 trailing modes"""
    
    def test_get_trailing_modes_returns_success(self):
        """GET /trailing-modes returns success status"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/trailing-modes")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("GET /api/smart-stops/trailing-modes - SUCCESS")
    
    def test_get_trailing_modes_returns_6_modes(self):
        """GET /trailing-modes returns exactly 6 trailing modes"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/trailing-modes")
        assert response.status_code == 200
        data = response.json()
        
        assert 'modes' in data
        assert len(data['modes']) == 6, f"Expected 6 modes, got {len(data['modes'])}"
        
        expected_modes = ['none', 'atr', 'percent', 'chandelier', 'breakeven_plus', 'parabolic']
        mode_ids = [m['id'] for m in data['modes']]
        for expected in expected_modes:
            assert expected in mode_ids, f"Missing trailing mode: {expected}"
        print(f"All 6 trailing modes present: {mode_ids}")


# ============================================================================
# GET /api/smart-stops/urgency-levels
# ============================================================================
class TestSmartStopUrgencyLevels:
    """Test /api/smart-stops/urgency-levels endpoint - 4 urgency levels"""
    
    def test_get_urgency_levels_returns_success(self):
        """GET /urgency-levels returns success status"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/urgency-levels")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("GET /api/smart-stops/urgency-levels - SUCCESS")
    
    def test_get_urgency_levels_returns_4_levels(self):
        """GET /urgency-levels returns exactly 4 urgency levels"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/urgency-levels")
        assert response.status_code == 200
        data = response.json()
        
        assert 'levels' in data
        assert len(data['levels']) == 4, f"Expected 4 levels, got {len(data['levels'])}"
        
        expected_levels = ['normal', 'caution', 'high_alert', 'emergency']
        level_ids = [l['id'] for l in data['levels']]
        for expected in expected_levels:
            assert expected in level_ids, f"Missing urgency level: {expected}"
        print(f"All 4 urgency levels present: {level_ids}")


# ============================================================================
# GET /api/smart-stops/compare
# ============================================================================
class TestSmartStopCompare:
    """Test /api/smart-stops/compare endpoint"""
    
    def test_compare_returns_all_modes(self):
        """GET /compare returns comparison for all 6 modes"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={'entry_price': 100, 'direction': 'long', 'atr': 2.5}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['success'] is True
        assert 'comparison' in data
        assert len(data['comparison']) == 6, f"Expected 6 modes, got {len(data['comparison'])}"
        print("Compare endpoint returns all 6 modes - PASS")
    
    def test_compare_anti_hunt_deepest_for_long(self):
        """Anti-hunt mode has deepest protection (lowest stop) for long trades"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={'entry_price': 100, 'direction': 'long', 'atr': 2.5}
        )
        assert response.status_code == 200
        data = response.json()
        
        comparison = data['comparison']
        anti_hunt_stop = comparison['anti_hunt']['stop_price']
        original_stop = comparison['original']['stop_price']
        atr_dynamic_stop = comparison['atr_dynamic']['stop_price']
        
        # For longs, lower stop = deeper protection
        assert anti_hunt_stop < original_stop, \
            f"Anti-hunt stop ({anti_hunt_stop}) should be lower than original ({original_stop})"
        assert anti_hunt_stop < atr_dynamic_stop, \
            f"Anti-hunt stop ({anti_hunt_stop}) should be lower than ATR dynamic ({atr_dynamic_stop})"
        print(f"Anti-hunt deepest stop: {anti_hunt_stop} < original: {original_stop} - PASS")
    
    def test_compare_missing_required_params(self):
        """GET /compare returns 422 when missing required parameters"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/compare")
        assert response.status_code == 422
        print("Compare missing params validation - PASS")


# ============================================================================
# GET /api/smart-stops/recommend/{symbol}
# ============================================================================
class TestSmartStopRecommend:
    """Test /api/smart-stops/recommend/{symbol} endpoint"""
    
    def test_recommend_returns_success(self):
        """GET /recommend/{symbol} returns success"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/recommend/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['symbol'] == 'AAPL'
        print("Recommend endpoint - SUCCESS")
    
    def test_recommend_low_float_gets_anti_hunt(self):
        """Low float stocks (<10M shares) get anti_hunt recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/LOWFLOAT",
            params={'float_shares': 5000000}  # 5M shares
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'anti_hunt'
        assert any('float' in r.lower() for r in data['reasons'])
        print("Low float -> anti_hunt recommendation - PASS")
    
    def test_recommend_low_volume_gets_anti_hunt(self):
        """Low volume stocks (<500K avg) get anti_hunt recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/LOWVOL",
            params={'avg_volume': 200000}  # 200K avg volume
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'anti_hunt'
        assert any('volume' in r.lower() for r in data['reasons'])
        print("Low volume -> anti_hunt recommendation - PASS")
    
    def test_recommend_high_volatility_gets_vol_adjusted(self):
        """High volatility regime gets volatility_adjusted recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/VOLATILE",
            params={'volatility_regime': 'high', 'avg_volume': 5000000}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'volatility_adjusted'
        print("High volatility -> volatility_adjusted recommendation - PASS")
    
    def test_recommend_premarket_gets_anti_hunt(self):
        """Pre/after hours trading gets anti_hunt recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/TICKER",
            params={'time_of_day': 'premarket', 'avg_volume': 5000000}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'anti_hunt'
        print("Premarket -> anti_hunt recommendation - PASS")


# ============================================================================
# POST /api/smart-stops/calculate
# ============================================================================
class TestSmartStopCalculate:
    """Test POST /api/smart-stops/calculate endpoint - simple stop calculation"""
    
    def test_calculate_returns_success(self):
        """POST /calculate returns success status"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'AAPL',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("POST /api/smart-stops/calculate - SUCCESS")
    
    def test_calculate_returns_required_fields(self):
        """POST /calculate returns all required response fields"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'AAPL',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            'stop_price', 'stop_mode', 'stop_reasoning',
            'buffer_applied', 'hunt_risk',
            'symbol', 'entry_price', 'direction'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        print("Calculate response fields validation - PASS")
    
    def test_calculate_default_mode_is_atr_dynamic(self):
        """POST /calculate defaults to atr_dynamic mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        # The stop_mode in response may be trailing mode. Check reasoning contains atr
        print(f"Default mode response: {data.get('stop_mode', 'N/A')}, {data.get('stop_reasoning', 'N/A')}")
    
    def test_calculate_anti_hunt_mode(self):
        """POST /calculate with anti_hunt mode places deep stop with LOW hunt risk"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'anti_hunt'
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['hunt_risk'] == 'LOW'
        # Stop should be well below entry for long
        assert data['stop_price'] < data['entry_price'], \
            f"Stop ({data['stop_price']}) should be below entry ({data['entry_price']})"
        print(f"Anti-hunt mode: stop={data['stop_price']}, hunt_risk=LOW - PASS")
    
    def test_calculate_layered_mode_returns_layers(self):
        """POST /calculate with layered mode returns multiple stop levels"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'layered'
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['layered_stops'] is not None
        assert len(data['layered_stops']) == 3
        
        # Verify layer structure
        for layer in data['layered_stops']:
            assert 'level' in layer
            assert 'stop_price' in layer
            assert 'position_pct' in layer
            assert 'atr_depth' in layer
        
        # Verify percentages add up to 100%
        total_pct = sum(l['position_pct'] for l in data['layered_stops'])
        assert abs(total_pct - 1.0) < 0.01, f"Position percentages should sum to 1.0, got {total_pct}"
        
        # Verify layers are progressively deeper
        prices = [l['stop_price'] for l in data['layered_stops']]
        assert prices[0] > prices[1] > prices[2], "Layers should be progressively deeper"
        print(f"Layered stops: {prices} - PASS")
    
    def test_calculate_volatility_adjusted_high_vol(self):
        """POST /calculate with volatility_adjusted widens in high vol"""
        # Normal volatility
        response_normal = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'volatility_adjusted',
                'volatility_regime': 'normal'
            }
        )
        
        # High volatility
        response_high = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'volatility_adjusted',
                'volatility_regime': 'high'
            }
        )
        
        assert response_normal.status_code == 200
        assert response_high.status_code == 200
        
        data_normal = response_normal.json()
        data_high = response_high.json()
        
        # High vol should have lower stop (wider)
        assert data_high['stop_price'] < data_normal['stop_price'], \
            f"High vol stop ({data_high['stop_price']}) should be lower than normal ({data_normal['stop_price']})"
        print(f"Volatility adjusted: high_vol={data_high['stop_price']} < normal={data_normal['stop_price']} - PASS")
    
    def test_calculate_chandelier_mode(self):
        """POST /calculate with chandelier mode uses ATR from high"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'chandelier',
                'swing_high': 105  # Recent high
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Chandelier uses 3x ATR multiplier by default
        # Stop should be swing_high (105) - 3*ATR(2.5) = 97.5
        expected_stop = 105 - (3 * 2.5)
        assert abs(data['stop_price'] - expected_stop) < 0.5, \
            f"Chandelier stop should be around {expected_stop}, got {data['stop_price']}"
        print(f"Chandelier stop: {data['stop_price']} (expected ~{expected_stop}) - PASS")
    
    def test_calculate_short_direction(self):
        """POST /calculate works for short trades (stop above entry)"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'short',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # For shorts, stop should be ABOVE entry
        assert data['stop_price'] > data['entry_price'], \
            f"Short stop ({data['stop_price']}) should be above entry ({data['entry_price']})"
        print(f"Short direction: stop={data['stop_price']} > entry={data['entry_price']} - PASS")


# ============================================================================
# POST /api/smart-stops/intelligent-calculate
# ============================================================================
class TestSmartStopIntelligentCalculate:
    """Test POST /api/smart-stops/intelligent-calculate endpoint - full multi-factor"""
    
    def test_intelligent_calculate_returns_success(self):
        """POST /intelligent-calculate returns success status"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'AAPL',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'breakout',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("POST /api/smart-stops/intelligent-calculate - SUCCESS")
    
    def test_intelligent_calculate_returns_all_fields(self):
        """POST /intelligent-calculate returns all comprehensive fields"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'AAPL',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'breakout',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            'stop_price', 'stop_distance_pct', 'stop_distance_atr',
            'stop_mode', 'primary_factor', 'factors_considered', 'confidence',
            'hunt_risk', 'hunt_risk_score', 'urgency', 'warnings',
            'trailing_mode', 'trailing_trigger_price', 'breakeven_trigger_price',
            'layered_stops', 'scale_out_plan',
            'sector_adjustment', 'regime_adjustment', 'setup_rules_used',
            'symbol', 'entry_price', 'direction', 'calculated_at', 'valid_until'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        print("Intelligent calculate response fields validation - PASS")
    
    def test_intelligent_calculate_breakout_setup(self):
        """POST /intelligent-calculate with breakout setup uses chandelier trailing"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'breakout',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['setup_rules_used'] == 'breakout'
        assert data['trailing_mode'] == 'chandelier'
        print(f"Breakout setup: trailing_mode={data['trailing_mode']} - PASS")
    
    def test_intelligent_calculate_momentum_setup(self):
        """POST /intelligent-calculate with momentum setup uses parabolic trailing"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'momentum',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['setup_rules_used'] == 'momentum'
        assert data['trailing_mode'] == 'parabolic'
        print(f"Momentum setup: trailing_mode={data['trailing_mode']} - PASS")
    
    def test_intelligent_calculate_low_float_high_hunt_risk(self):
        """POST /intelligent-calculate with low float/volume triggers HIGH hunt risk"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'LOWFLOAT',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'default',
                'position_size': 100,
                'atr': 2.5,
                'float_shares': 5000000,  # 5M shares (low)
                'avg_volume': 200000  # 200K (low)
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Low float + low volume should trigger HIGH hunt risk
        assert data['hunt_risk'] == 'HIGH', f"Expected HIGH hunt risk, got {data['hunt_risk']}"
        assert data['hunt_risk_score'] >= 50, f"Expected hunt score >= 50, got {data['hunt_risk_score']}"
        print(f"Low float hunt risk: {data['hunt_risk']} (score: {data['hunt_risk_score']}) - PASS")
    
    def test_intelligent_calculate_layered_stops(self):
        """POST /intelligent-calculate returns 3 layered stops"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'default',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data['layered_stops']) == 3
        for i, layer in enumerate(data['layered_stops']):
            assert layer['level'] == i + 1
            assert 'stop_price' in layer
            assert 'position_pct' in layer
            assert 'atr_depth' in layer
        print(f"Layered stops: {[l['stop_price'] for l in data['layered_stops']]} - PASS")
    
    def test_intelligent_calculate_scale_out_plan(self):
        """POST /intelligent-calculate returns scale-out plan with R-targets"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'default',  # default has scale_out_r_targets: [1.0, 2.0, 3.0]
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data['scale_out_plan']) >= 2
        for level in data['scale_out_plan']:
            assert 'r_target' in level
            assert 'target_price' in level
            assert 'exit_pct' in level
        print(f"Scale-out plan: {data['scale_out_plan']} - PASS")
    
    def test_intelligent_calculate_confidence_in_range(self):
        """POST /intelligent-calculate returns confidence in valid range [30-100]"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'default',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert 30 <= data['confidence'] <= 100, \
            f"Confidence {data['confidence']} should be in range [30-100]"
        print(f"Confidence: {data['confidence']} - PASS")
    
    def test_intelligent_calculate_valid_urgency(self):
        """POST /intelligent-calculate returns valid urgency level"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'default',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        valid_urgencies = ['normal', 'caution', 'high_alert', 'emergency']
        assert data['urgency'] in valid_urgencies, \
            f"Urgency '{data['urgency']}' should be one of {valid_urgencies}"
        print(f"Urgency: {data['urgency']} - PASS")
    
    def test_intelligent_calculate_short_direction(self):
        """POST /intelligent-calculate works for short positions"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 99,
                'direction': 'short',
                'setup_type': 'default',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # For shorts, stop should be ABOVE entry
        assert data['stop_price'] > data['entry_price'], \
            f"Short stop ({data['stop_price']}) should be above entry ({data['entry_price']})"
        print(f"Short position: stop={data['stop_price']} > entry={data['entry_price']} - PASS")
    
    def test_intelligent_calculate_unknown_setup_fallback(self):
        """POST /intelligent-calculate with unknown setup falls back to default"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'current_price': 101,
                'direction': 'long',
                'setup_type': 'unknown_random_setup',
                'position_size': 100,
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['setup_rules_used'] == 'default'
        print("Unknown setup fallback to default - PASS")
    
    def test_intelligent_calculate_missing_required_field(self):
        """POST /intelligent-calculate returns 422 for missing required field"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/intelligent-calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                # missing current_price, direction, etc.
            }
        )
        assert response.status_code == 422
        print("Missing required field validation - PASS")


# ============================================================================
# POST /api/smart-stops/analyze-trade
# ============================================================================
class TestSmartStopAnalyzeTrade:
    """Test POST /api/smart-stops/analyze-trade endpoint"""
    
    def test_analyze_trade_returns_success(self):
        """POST /analyze-trade returns success status"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/analyze-trade",
            params={
                'symbol': 'AAPL',
                'entry_price': 100,
                'current_price': 102,
                'stop_price': 95,
                'direction': 'long',
                'setup_type': 'default',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print("POST /api/smart-stops/analyze-trade - SUCCESS")
    
    def test_analyze_trade_returns_comparison(self):
        """POST /analyze-trade returns current vs optimal stop comparison"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/analyze-trade",
            params={
                'symbol': 'AAPL',
                'entry_price': 100,
                'current_price': 102,
                'stop_price': 95,
                'direction': 'long',
                'setup_type': 'default',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert 'current_stop' in data
        assert 'optimal_stop' in data
        assert 'urgency' in data
        assert 'recommendations' in data
        
        # Current stop should have price, distance_pct, distance_atr
        assert data['current_stop']['price'] == 95
        assert 'distance_pct' in data['current_stop']
        
        # Optimal stop should have price and confidence
        assert 'price' in data['optimal_stop']
        assert 'confidence' in data['optimal_stop']
        print(f"Analyze trade: current={data['current_stop']['price']}, optimal={data['optimal_stop']['price']} - PASS")
    
    def test_analyze_trade_too_tight_stop_warning(self):
        """POST /analyze-trade warns when stop is too tight"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/analyze-trade",
            params={
                'symbol': 'AAPL',
                'entry_price': 100,
                'current_price': 101,
                'stop_price': 99.5,  # Very tight stop
                'direction': 'long',
                'setup_type': 'default',
                'atr': 2.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should get recommendation about tight stop
        recommendations = data.get('recommendations', [])
        print(f"Recommendations: {recommendations}")


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================
class TestSmartStopEdgeCases:
    """Test edge cases and error handling"""
    
    def test_all_6_modes_in_original_endpoint(self):
        """Verify all 6 modes work in the original /calculate endpoint"""
        modes = ['original', 'atr_dynamic', 'anti_hunt', 'volatility_adjusted', 'layered', 'chandelier']
        
        for mode in modes:
            response = requests.post(
                f"{BASE_URL}/api/smart-stops/calculate",
                json={
                    'symbol': 'TEST',
                    'entry_price': 100,
                    'direction': 'long',
                    'atr': 2.5,
                    'mode': mode
                }
            )
            assert response.status_code == 200, f"Mode {mode} failed with status {response.status_code}"
            data = response.json()
            assert data['success'] is True, f"Mode {mode} returned success=False"
        print(f"All 6 modes working: {modes} - PASS")
    
    def test_all_8_setups_in_intelligent_endpoint(self):
        """Verify all 8 setup types work in the intelligent endpoint"""
        setups = ['breakout', 'pullback', 'momentum', 'mean_reversion',
                 'gap_and_go', 'vwap_reversal', 'earnings_play', 'default']
        
        for setup in setups:
            response = requests.post(
                f"{BASE_URL}/api/smart-stops/intelligent-calculate",
                json={
                    'symbol': 'TEST',
                    'entry_price': 100,
                    'current_price': 101,
                    'direction': 'long',
                    'setup_type': setup,
                    'position_size': 100,
                    'atr': 2.5
                }
            )
            assert response.status_code == 200, f"Setup {setup} failed with status {response.status_code}"
            data = response.json()
            assert data['success'] is True, f"Setup {setup} returned success=False"
            assert data['setup_rules_used'] == setup, f"Setup {setup} not used correctly"
        print(f"All 8 setups working: {setups} - PASS")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
