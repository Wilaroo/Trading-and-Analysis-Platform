"""
Smart Stop Service API Tests
=============================
Tests for P2 Smart Stop Loss feature with anti-hunt capabilities.

Endpoints tested:
- GET /api/smart-stops/modes - Get all 6 stop modes
- GET /api/smart-stops/compare - Compare all modes for a trade setup
- GET /api/smart-stops/recommend/{symbol} - Get recommended mode
- POST /api/smart-stops/calculate - Calculate smart stop with specified mode

Business logic verified:
- Anti-hunt mode places stop BEYOND obvious levels (deepest protection)
- Layered mode returns multiple stop levels with position percentages
- Volatility-adjusted mode widens stops in high volatility
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSmartStopModes:
    """Test /api/smart-stops/modes endpoint"""
    
    def test_get_modes_returns_success(self):
        """GET /modes returns success status"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
    
    def test_get_modes_returns_all_6_modes(self):
        """GET /modes returns exactly 6 stop modes"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        
        assert 'modes' in data
        assert len(data['modes']) == 6
        
        # Verify all expected modes are present
        mode_ids = [m['id'] for m in data['modes']]
        expected_modes = ['original', 'atr_dynamic', 'anti_hunt', 
                        'volatility_adjusted', 'layered', 'chandelier']
        for expected in expected_modes:
            assert expected in mode_ids, f"Missing mode: {expected}"
    
    def test_get_modes_structure(self):
        """GET /modes returns proper structure for each mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/modes")
        assert response.status_code == 200
        data = response.json()
        
        for mode in data['modes']:
            assert 'id' in mode
            assert 'name' in mode
            assert 'description' in mode
            assert 'hunt_risk' in mode
            assert 'best_for' in mode
    
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
        assert len(data['comparison']) == 6
    
    def test_compare_returns_correct_entry_and_direction(self):
        """GET /compare echoes back input parameters"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={'entry_price': 150.50, 'direction': 'short', 'atr': 3.0}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['entry_price'] == 150.50
        assert data['direction'] == 'short'
        assert data['atr'] == 3.0
    
    def test_compare_mode_structure(self):
        """GET /compare returns proper structure for each mode"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={'entry_price': 100, 'direction': 'long', 'atr': 2.5}
        )
        assert response.status_code == 200
        data = response.json()
        
        for mode_id, mode_data in data['comparison'].items():
            assert 'stop_price' in mode_data
            assert 'risk_percent' in mode_data
            assert 'buffer_applied' in mode_data
            assert 'hunt_risk' in mode_data
            assert 'reasoning' in mode_data
    
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
        # Anti-hunt should be lower than original and atr_dynamic
        assert anti_hunt_stop < original_stop, \
            f"Anti-hunt stop ({anti_hunt_stop}) should be lower than original ({original_stop})"
        assert anti_hunt_stop < atr_dynamic_stop, \
            f"Anti-hunt stop ({anti_hunt_stop}) should be lower than ATR dynamic ({atr_dynamic_stop})"
    
    def test_compare_returns_ranked_protection(self):
        """GET /compare returns modes ranked by protection level"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={'entry_price': 100, 'direction': 'long', 'atr': 2.5}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert 'ranked_by_protection' in data
        assert isinstance(data['ranked_by_protection'], list)
        assert len(data['ranked_by_protection']) == 6
    
    def test_compare_with_support_resistance(self):
        """GET /compare works with support and resistance levels"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/compare",
            params={
                'entry_price': 100, 
                'direction': 'long', 
                'atr': 2.5,
                'support': 95.0,
                'resistance': 105.0
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True


class TestSmartStopRecommend:
    """Test /api/smart-stops/recommend/{symbol} endpoint"""
    
    def test_recommend_returns_success(self):
        """GET /recommend/{symbol} returns success"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/recommend/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['symbol'] == 'AAPL'
    
    def test_recommend_returns_valid_mode(self):
        """GET /recommend returns a valid stop mode"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/recommend/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        valid_modes = ['original', 'atr_dynamic', 'anti_hunt', 
                      'volatility_adjusted', 'layered', 'chandelier']
        assert data['recommended_mode'] in valid_modes
    
    def test_recommend_includes_description_and_reasons(self):
        """GET /recommend includes description and reasoning"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/recommend/AAPL")
        assert response.status_code == 200
        data = response.json()
        
        assert 'description' in data
        assert 'reasons' in data
        assert isinstance(data['reasons'], list)
        assert len(data['reasons']) > 0
    
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
    
    def test_recommend_high_volatility_gets_vol_adjusted(self):
        """High volatility regime gets volatility_adjusted recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/VOLATILE",
            params={'volatility_regime': 'high', 'avg_volume': 5000000}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'volatility_adjusted'
        assert any('volatility' in r.lower() for r in data['reasons'])
    
    def test_recommend_premarket_gets_anti_hunt(self):
        """Pre/after hours trading gets anti_hunt recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/TICKER",
            params={'time_of_day': 'premarket', 'avg_volume': 5000000}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'anti_hunt'
        assert any('premarket' in r.lower() for r in data['reasons'])
    
    def test_recommend_liquid_stock_normal_gets_atr_dynamic(self):
        """Liquid stocks in normal conditions get atr_dynamic recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/smart-stops/recommend/LIQUID",
            params={
                'avg_volume': 10000000,  # 10M volume (very liquid)
                'volatility_regime': 'normal',
                'time_of_day': 'regular'
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['recommended_mode'] == 'atr_dynamic'


class TestSmartStopCalculate:
    """Test POST /api/smart-stops/calculate endpoint"""
    
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
            'buffer_applied', 'anti_hunt_buffer', 'hunt_risk',
            'symbol', 'entry_price', 'direction'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_calculate_anti_hunt_mode(self):
        """POST /calculate with anti_hunt mode places deep stop"""
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
        
        assert data['stop_mode'] == 'anti_hunt'
        assert data['hunt_risk'] == 'LOW'
        # Anti-hunt should have significant buffer
        assert data['anti_hunt_buffer'] > 0
        # Stop should be well below entry for long
        assert data['stop_price'] < data['entry_price'] - 5
    
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
        
        assert data['stop_mode'] == 'layered'
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
        # High vol should have larger buffer
        assert data_high['buffer_applied'] > data_normal['buffer_applied']
    
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
        
        assert data['stop_mode'] == 'chandelier'
        # Chandelier uses 3x ATR multiplier by default
        # Stop should be swing_high (105) - 3*ATR(2.5) = 97.5
        expected_stop = 105 - (3 * 2.5)
        assert abs(data['stop_price'] - expected_stop) < 0.5, \
            f"Chandelier stop should be around {expected_stop}, got {data['stop_price']}"
    
    def test_calculate_original_mode_high_risk(self):
        """POST /calculate with original mode has HIGH hunt risk"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'mode': 'original'
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data['stop_mode'] == 'original'
        assert data['hunt_risk'] == 'HIGH'
        # Original should have 0 anti-hunt buffer
        assert data['anti_hunt_buffer'] == 0
    
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
    
    def test_calculate_with_support_level(self):
        """POST /calculate considers support level for stop placement"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5,
                'support_level': 95.0,
                'mode': 'original'
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Stop should be below support level
        assert data['stop_price'] < 95.0


class TestSmartStopEdgeCases:
    """Test edge cases and error handling"""
    
    def test_compare_missing_required_params(self):
        """GET /compare returns 422 when missing required parameters"""
        response = requests.get(f"{BASE_URL}/api/smart-stops/compare")
        assert response.status_code == 422
    
    def test_calculate_default_mode_is_atr_dynamic(self):
        """POST /calculate defaults to atr_dynamic mode"""
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 2.5
                # mode not specified
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['stop_mode'] == 'atr_dynamic'
    
    def test_calculate_enforces_max_stop_distance(self):
        """POST /calculate enforces maximum stop distance constraint (8%)"""
        # Use very large ATR that would exceed 8% distance
        response = requests.post(
            f"{BASE_URL}/api/smart-stops/calculate",
            json={
                'symbol': 'TEST',
                'entry_price': 100,
                'direction': 'long',
                'atr': 10.0,  # Very large ATR
                'mode': 'chandelier'  # Uses 3x ATR = 30 which exceeds 8%
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Stop distance should be capped at 8%
        stop_distance_pct = abs(data['entry_price'] - data['stop_price']) / data['entry_price']
        assert stop_distance_pct <= 0.082, \
            f"Stop distance ({stop_distance_pct*100:.1f}%) should be capped at 8%"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
