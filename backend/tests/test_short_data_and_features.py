"""
Test Short Interest Data APIs and Short Setup Feature Extraction
=================================================================
Tests for Phase 2 short data integration:
1. Short Data API endpoints (IB + FINRA)
2. Short setup feature extraction (10 SHORT_* types)
3. Model inventory count (should be 80 total with shorts)
"""

import pytest
import requests
import os
import numpy as np

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestShortDataAPIs:
    """Test short interest data API endpoints"""

    def test_short_data_summary(self):
        """GET /api/short-data/summary - returns ib_symbols, finra_records, finra_unique_symbols counts"""
        response = requests.get(f"{BASE_URL}/api/short-data/summary", timeout=90)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        
        # Verify required fields exist
        assert "ib_symbols" in data, "Missing ib_symbols field"
        assert "finra_records" in data, "Missing finra_records field"
        assert "finra_unique_symbols" in data, "Missing finra_unique_symbols field"
        
        # Values should be integers >= 0
        assert isinstance(data["ib_symbols"], int), f"ib_symbols should be int, got {type(data['ib_symbols'])}"
        assert isinstance(data["finra_records"], int), f"finra_records should be int, got {type(data['finra_records'])}"
        assert isinstance(data["finra_unique_symbols"], int), f"finra_unique_symbols should be int, got {type(data['finra_unique_symbols'])}"
        
        # Optional fields
        assert "latest_settlement_date" in data, "Missing latest_settlement_date field"
        assert "hard_to_borrow_count" in data, "Missing hard_to_borrow_count field"
        
        print(f"Short data summary: IB={data['ib_symbols']}, FINRA records={data['finra_records']}, FINRA symbols={data['finra_unique_symbols']}")

    def test_short_data_symbol_aapl(self):
        """GET /api/short-data/symbol/AAPL - returns combined IB + FINRA short data"""
        response = requests.get(f"{BASE_URL}/api/short-data/symbol/AAPL", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert data.get("symbol") == "AAPL", f"Expected symbol=AAPL, got {data.get('symbol')}"
        
        # Should have ib_data and finra_data fields (may be null if no data)
        assert "ib_data" in data, "Missing ib_data field"
        assert "finra_data" in data, "Missing finra_data field"
        
        # Should have shortable status
        assert "shortable" in data, "Missing shortable field"
        assert "shortable_level" in data, "Missing shortable_level field"
        
        print(f"AAPL short data: shortable={data['shortable']}, level={data['shortable_level']}")
        if data.get("ib_data"):
            print(f"  IB data: {data['ib_data']}")
        if data.get("finra_data"):
            print(f"  FINRA data: {data['finra_data']}")

    def test_short_data_bulk(self):
        """GET /api/short-data/bulk?symbols=AAPL,MSFT - returns bulk short data"""
        response = requests.get(f"{BASE_URL}/api/short-data/bulk?symbols=AAPL,MSFT", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert "count" in data, "Missing count field"
        assert "data" in data, "Missing data field"
        
        # Data should be a list
        assert isinstance(data["data"], list), f"data should be list, got {type(data['data'])}"
        
        print(f"Bulk short data: count={data['count']}")
        for item in data["data"]:
            print(f"  {item.get('symbol')}: {item}")

    def test_ib_short_data_push(self):
        """POST /api/short-data/ib/push - accepts IB shortable data push payload"""
        payload = {
            "data": [
                {
                    "symbol": "TEST_SYMBOL",
                    "shortable_shares": 1000000,
                    "shortable_level": 3.0,
                    "timestamp": "2025-01-01T12:00:00Z"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/short-data/ib/push",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        assert "stored" in data, "Missing stored field"
        
        print(f"IB push result: stored={data['stored']}")


class TestModelInventory:
    """Test AI model inventory includes SHORT_* models"""

    def test_model_inventory_count(self):
        """GET /api/ai-training/model-inventory - should show 80 total models including SHORT_* types"""
        response = requests.get(f"{BASE_URL}/api/ai-training/model-inventory", timeout=90)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got {data}"
        
        # Check total model count - API returns total_defined not total_models
        total_defined = data.get("total_defined", 0)
        print(f"Total models defined in inventory: {total_defined}")
        
        # Should be 80 total (was 63 before shorts were added)
        assert total_defined >= 70, f"Expected at least 70 models, got {total_defined}"
        assert total_defined == 80, f"Expected exactly 80 models, got {total_defined}"
        
        # Check for SHORT_* setup types in the inventory
        categories = data.get("categories", {})
        setup_specific = categories.get("setup_specific", {})
        models = setup_specific.get("models", [])
        
        short_setups_found = []
        expected_short_setups = [
            "SHORT_SCALP", "SHORT_ORB", "SHORT_GAP_FADE", "SHORT_VWAP", "SHORT_BREAKDOWN",
            "SHORT_RANGE", "SHORT_MEAN_REVERSION", "SHORT_REVERSAL", "SHORT_MOMENTUM", "SHORT_TREND"
        ]
        
        for model in models:
            setup_type = model.get("setup_type", "")
            if setup_type.startswith("SHORT_") and setup_type not in short_setups_found:
                short_setups_found.append(setup_type)
        
        print(f"Short setups found in inventory: {short_setups_found}")
        
        # Verify all 10 short setup types are present
        for expected in expected_short_setups:
            assert expected in short_setups_found, f"Missing {expected} in model inventory"
        
        print(f"All 10 SHORT_* setup types verified in model inventory")


class TestShortSetupFeatures:
    """Test short setup feature extraction for all 10 SHORT_* types"""

    @pytest.fixture
    def sample_data(self):
        """Generate sample OHLCV data for feature extraction"""
        np.random.seed(42)
        n = 100
        
        # Generate realistic price data
        base_price = 100.0
        returns = np.random.normal(0, 0.02, n)
        closes = base_price * np.cumprod(1 + returns)
        
        # Generate OHLCV
        opens = closes * (1 + np.random.uniform(-0.01, 0.01, n))
        highs = np.maximum(opens, closes) * (1 + np.random.uniform(0, 0.02, n))
        lows = np.minimum(opens, closes) * (1 - np.random.uniform(0, 0.02, n))
        volumes = np.random.uniform(1000000, 5000000, n)
        
        return opens, highs, lows, closes, volumes

    def test_short_breakdown_features(self, sample_data):
        """Test SHORT_BREAKDOWN feature extraction"""
        from services.ai_modules.short_setup_features import short_breakdown_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_breakdown_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['dist_from_support', 'lower_low_streak', 'lower_high_streak', 
                        'down_vs_up_volume', 'breakdown_magnitude', 'upper_wick_ratio']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
            assert not np.isnan(features[key]), f"Feature {key} is NaN"
            assert not np.isinf(features[key]), f"Feature {key} is Inf"
        
        print(f"SHORT_BREAKDOWN features: {features}")

    def test_short_momentum_features(self, sample_data):
        """Test SHORT_MOMENTUM feature extraction"""
        from services.ai_modules.short_setup_features import short_momentum_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_momentum_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['bearish_momentum_accel', 'down_streak', 'ema_stack_bearish',
                        'below_ema_count', 'bearish_vol_alignment', 'rsi_decline']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_MOMENTUM features: {features}")

    def test_short_reversal_features(self, sample_data):
        """Test SHORT_REVERSAL feature extraction"""
        from services.ai_modules.short_setup_features import short_reversal_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_reversal_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['overbought_rsi', 'dist_from_recent_high', 'bearish_engulfing',
                        'shooting_star', 'volume_climax', 'bearish_divergence']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_REVERSAL features: {features}")

    def test_short_gap_fade_features(self, sample_data):
        """Test SHORT_GAP_FADE feature extraction"""
        from services.ai_modules.short_setup_features import short_gap_fade_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_gap_fade_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['gap_up_size', 'gap_fill_pct', 'post_gap_bearish',
                        'gap_vs_atr', 'gap_rejection', 'fade_volume_ratio']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_GAP_FADE features: {features}")

    def test_short_vwap_features(self, sample_data):
        """Test SHORT_VWAP feature extraction"""
        from services.ai_modules.short_setup_features import short_vwap_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_vwap_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 4, f"Expected at least 4 features, got {len(features)}"
        
        expected_keys = ['price_vs_vwap', 'below_vwap_duration', 'vwap_slope',
                        'vol_below_vwap_ratio', 'vwap_rejection']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_VWAP features: {features}")

    def test_short_mean_reversion_features(self, sample_data):
        """Test SHORT_MEAN_REVERSION feature extraction"""
        from services.ai_modules.short_setup_features import short_mean_reversion_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_mean_reversion_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['zscore_high', 'bb_upper_position', 'rsi_overbought_level',
                        'overextension_duration', 'momentum_deceleration', 'vol_at_high']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_MEAN_REVERSION features: {features}")

    def test_short_scalp_features(self, sample_data):
        """Test SHORT_SCALP feature extraction"""
        from services.ai_modules.short_setup_features import short_scalp_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_scalp_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['bearish_body', 'close_at_low', 'decline_speed',
                        'red_bar_ratio', 'downside_vol_expansion', 'spread_proxy']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_SCALP features: {features}")

    def test_short_orb_features(self, sample_data):
        """Test SHORT_ORB feature extraction"""
        from services.ai_modules.short_setup_features import short_orb_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_orb_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 4, f"Expected at least 4 features, got {len(features)}"
        
        expected_keys = ['below_or_low', 'dist_below_or', 'or_range_pct',
                        'breakdown_vol_ratio', 'first_bar_bearish']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_ORB features: {features}")

    def test_short_trend_features(self, sample_data):
        """Test SHORT_TREND feature extraction"""
        from services.ai_modules.short_setup_features import short_trend_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_trend_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 5, f"Expected at least 5 features, got {len(features)}"
        
        expected_keys = ['bearish_trend_strength', 'below_ma_count', 'ema21_rejection',
                        'lower_highs_count', 'macd_bearish']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_TREND features: {features}")

    def test_short_range_features(self, sample_data):
        """Test SHORT_RANGE feature extraction"""
        from services.ai_modules.short_setup_features import short_range_features
        
        opens, highs, lows, closes, volumes = sample_data
        features = short_range_features(opens, highs, lows, closes, volumes)
        
        assert isinstance(features, dict), "Features should be a dict"
        assert len(features) >= 4, f"Expected at least 4 features, got {len(features)}"
        
        expected_keys = ['range_position', 'below_range', 'time_in_range',
                        'breakdown_vol_surge', 'failed_upbreak']
        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"
        
        print(f"SHORT_RANGE features: {features}")

    def test_get_short_setup_features_api(self, sample_data):
        """Test the unified get_short_setup_features API for all 10 types"""
        from services.ai_modules.short_setup_features import (
            get_short_setup_features, 
            get_short_setup_feature_names,
            SHORT_SETUP_FEATURE_EXTRACTORS
        )
        
        opens, highs, lows, closes, volumes = sample_data
        
        # Verify all 10 short setup types are registered
        expected_types = [
            'SHORT_BREAKDOWN', 'SHORT_MOMENTUM', 'SHORT_REVERSAL', 'SHORT_GAP_FADE',
            'SHORT_VWAP', 'SHORT_MEAN_REVERSION', 'SHORT_SCALP', 'SHORT_ORB',
            'SHORT_TREND', 'SHORT_RANGE'
        ]
        
        assert len(SHORT_SETUP_FEATURE_EXTRACTORS) == 10, \
            f"Expected 10 short setup extractors, got {len(SHORT_SETUP_FEATURE_EXTRACTORS)}"
        
        for setup_type in expected_types:
            assert setup_type in SHORT_SETUP_FEATURE_EXTRACTORS, \
                f"Missing extractor for {setup_type}"
            
            # Test feature extraction
            features = get_short_setup_features(setup_type, opens, highs, lows, closes, volumes)
            assert isinstance(features, dict), f"{setup_type}: Features should be a dict"
            assert len(features) >= 4, f"{setup_type}: Expected at least 4 features, got {len(features)}"
            
            # Test feature names
            feature_names = get_short_setup_feature_names(setup_type)
            assert isinstance(feature_names, list), f"{setup_type}: Feature names should be a list"
            assert len(feature_names) >= 4, f"{setup_type}: Expected at least 4 feature names"
            
            # Verify all features are valid numbers
            for key, value in features.items():
                assert not np.isnan(value), f"{setup_type}: Feature {key} is NaN"
                assert not np.isinf(value), f"{setup_type}: Feature {key} is Inf"
            
            print(f"{setup_type}: {len(features)} features extracted")


class TestShortTrainingConfig:
    """Test short setup training configuration"""

    def test_short_setup_profiles_exist(self):
        """Verify all 10 SHORT_* setup types have training profiles"""
        from services.ai_modules.setup_training_config import (
            SETUP_TRAINING_PROFILES,
            get_setup_profiles,
            get_all_profile_count
        )
        
        expected_short_setups = [
            "SHORT_SCALP", "SHORT_ORB", "SHORT_GAP_FADE", "SHORT_VWAP", "SHORT_BREAKDOWN",
            "SHORT_RANGE", "SHORT_MEAN_REVERSION", "SHORT_REVERSAL", "SHORT_MOMENTUM", "SHORT_TREND"
        ]
        
        short_profile_count = 0
        for setup_type in expected_short_setups:
            assert setup_type in SETUP_TRAINING_PROFILES, \
                f"Missing training profile for {setup_type}"
            
            profiles = get_setup_profiles(setup_type)
            assert len(profiles) >= 1, f"{setup_type}: Expected at least 1 profile"
            short_profile_count += len(profiles)
            
            for profile in profiles:
                assert "bar_size" in profile, f"{setup_type}: Missing bar_size"
                assert "forecast_horizon" in profile, f"{setup_type}: Missing forecast_horizon"
                assert "direction" in profile, f"{setup_type}: Missing direction"
                assert profile["direction"] == "short", f"{setup_type}: direction should be 'short'"
            
            print(f"{setup_type}: {len(profiles)} profiles")
        
        # Check total profile count in SETUP_TRAINING_PROFILES
        total_profiles = get_all_profile_count()
        print(f"Total setup training profiles: {total_profiles}")
        
        # Short profiles should be 17 (10 types, some with 2 profiles)
        print(f"Short setup profiles: {short_profile_count}")
        assert short_profile_count >= 10, f"Expected at least 10 short profiles, got {short_profile_count}"
        
        # Total profiles should be at least 30 (long + short setups)
        assert total_profiles >= 30, f"Expected at least 30 total profiles, got {total_profiles}"

    def test_short_setup_types_in_pipeline(self):
        """Verify ALL_SHORT_SETUP_TYPES is defined in training pipeline"""
        from services.ai_modules.training_pipeline import ALL_SHORT_SETUP_TYPES
        
        expected_types = [
            "SHORT_SCALP", "SHORT_ORB", "SHORT_GAP_FADE", "SHORT_VWAP", "SHORT_BREAKDOWN",
            "SHORT_RANGE", "SHORT_MEAN_REVERSION", "SHORT_REVERSAL", "SHORT_MOMENTUM", "SHORT_TREND"
        ]
        
        assert len(ALL_SHORT_SETUP_TYPES) == 10, \
            f"Expected 10 short setup types, got {len(ALL_SHORT_SETUP_TYPES)}"
        
        for setup_type in expected_types:
            assert setup_type in ALL_SHORT_SETUP_TYPES, \
                f"Missing {setup_type} in ALL_SHORT_SETUP_TYPES"
        
        print(f"ALL_SHORT_SETUP_TYPES: {ALL_SHORT_SETUP_TYPES}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
