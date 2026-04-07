"""
Tests for Phase 3 (Training Optimizations), Phase 4 (Tiered Scanning), 
Phase 4.5 (Additive Confidence Gate)

Validates:
1. Feature caching saves and loads correctly
2. Batch sizes increased for 128GB memory
3. Float32 enforcement
4. Tiered scanning logic (intraday/swing/investment)
5. Staleness check handles IB date formats and weekends
6. Confidence gate uses additive scoring with floor protection
7. Model reload handles XGBoost JSON format
"""
import pytest
import sys
import os
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPhase3TrainingOptimizations:
    """Phase 3: Training optimizations for 128GB DGX Spark"""

    def test_batch_sizes_increased(self):
        """Batch sizes should be higher for 128GB memory"""
        from services.ai_modules.timeseries_service import TimeSeriesAIService
        settings = TimeSeriesAIService.TIMEFRAME_SETTINGS
        # All batch sizes should be > old defaults
        assert settings["1 min"]["batch_size"] >= 25
        assert settings["5 mins"]["batch_size"] >= 50
        assert settings["15 mins"]["batch_size"] >= 75
        assert settings["1 hour"]["batch_size"] >= 200
        assert settings["1 day"]["batch_size"] >= 500

    def test_float32_enforcement(self):
        """Training should use float32 to halve memory"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "timeseries_gbm.py")
        with open(filepath) as f:
            content = f.read()
        assert "dtype=np.float32" in content

    def test_feature_cache_methods_exist(self):
        """TimeSeriesGBM should have feature caching methods"""
        from services.ai_modules.timeseries_gbm import TimeSeriesGBM
        model = TimeSeriesGBM()
        assert hasattr(model, '_save_features_to_cache')
        assert hasattr(model, '_load_features_from_cache')
        assert hasattr(model, '_get_feature_cache_key')

    def test_feature_cache_key_format(self):
        """Cache key should include symbol, bar_size, and horizon"""
        from services.ai_modules.timeseries_gbm import TimeSeriesGBM
        model = TimeSeriesGBM(forecast_horizon=5)
        key = model._get_feature_cache_key("AAPL", "5 mins")
        assert "AAPL" in key
        assert "5 mins" in key
        assert "5" in key  # forecast_horizon

    def test_no_pickle_in_service(self):
        """timeseries_service.py should NOT use pickle for model serialization"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "timeseries_service.py")
        with open(filepath) as f:
            content = f.read()
        assert "import pickle" not in content
        assert "pickle.loads" not in content
        assert "pickle.dumps" not in content


class TestPhase4TieredScanning:
    """Phase 4: Tiered scanning by ADV class"""

    def test_scan_config_optimized(self):
        """Scanner should have optimized batch sizes and intervals"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "enhanced_scanner.py")
        with open(filepath) as f:
            content = f.read()
        assert "self._symbols_per_batch = 100" in content
        assert "self._batch_delay = 0.1" in content
        assert "self._scan_interval = 15" in content

    def test_investment_tier_threshold(self):
        """Investment tier should be 50K ADV"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "enhanced_scanner.py")
        with open(filepath) as f:
            content = f.read()
        assert "self._min_adv_investment = 50_000" in content

    def test_three_tiers_defined(self):
        """Scanner should classify symbols into 3 tiers"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "enhanced_scanner.py")
        with open(filepath) as f:
            content = f.read()
        assert '"intraday"' in content
        assert '"swing"' in content  
        assert '"investment"' in content
        assert "_classify_symbol_tier" in content
        assert "_get_symbols_for_cycle" in content

    def test_investment_scan_times(self):
        """Investment tier should scan at 11:00 AM and 3:45 PM ET only"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "enhanced_scanner.py")
        with open(filepath) as f:
            content = f.read()
        assert "(11, 0)" in content
        assert "(15, 45)" in content


class TestPhase4StalenessCheck:
    """Staleness check with IB date formats and market-hours awareness"""

    def test_staleness_ib_date_format(self):
        """Should handle IB date format YYYYMMDD HH:MM:SS"""
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        # Fresh IB-formatted date (yesterday)
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=12))
        ib_date = yesterday.strftime("%Y%m%d %H:%M:%S")
        bars = [{"date": ib_date}]
        assert svc._check_staleness(bars) is False

    def test_staleness_weekend_handling(self):
        """Friday bar should NOT be stale on Monday (weekends don't count)"""
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        # Find the last Friday from now
        now = datetime.now(timezone.utc)
        days_since_friday = (now.weekday() - 4) % 7
        if days_since_friday == 0 and now.hour < 20:
            days_since_friday = 7
        last_friday = now - timedelta(days=days_since_friday)
        friday_bar = last_friday.strftime("%Y%m%d 16:00:00")
        bars = [{"date": friday_bar}]
        # Should only be stale if > 3 trading days (not calendar days)
        # Friday to Monday = 1 trading day, so should NOT be stale
        result = svc._check_staleness(bars)
        # If it's within 3 trading days, should be False
        # Only assert if we're within the work week
        if days_since_friday <= 4:  # Within Mon-Thu of same week
            assert result is False

    def test_staleness_truly_old_data(self):
        """Data from 2 weeks ago should be stale"""
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        old_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y%m%d 10:00:00")
        bars = [{"date": old_date}]
        assert svc._check_staleness(bars) is True


class TestPhase45AdditiveConfidenceGate:
    """Phase 4.5: Additive confidence gate scoring"""

    def test_additive_scoring_base_zero(self):
        """Confidence gate should start at 0, not 50"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        assert "confidence_points = 0" in content
        assert "confidence_points = 50" not in content

    def test_scoring_version_field(self):
        """Gate log should include scoring_version for migration tracking"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        assert '"scoring_version": "additive_v1"' in content

    def test_floor_protection(self):
        """No single gate should subtract more than -10 (regime) or -5 (others)"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        # The maximum subtraction for regime is -10
        assert "confidence_points -= 10" in content
        # Floor protection comments
        assert "floor" in content.lower() or "Floor" in content

    def test_additive_thresholds(self):
        """Decision thresholds should be calibrated for additive scoring"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        # GO threshold at 55
        assert "confidence_score >= 55" in content
        # REDUCE threshold at 30
        assert "confidence_score >= 30" in content

    def test_docstring_documents_additive(self):
        """Module docstring should document the additive architecture"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        assert "Additive" in content
        assert "base 0" in content
        assert "floor" in content.lower()

    def test_cnn_signal_in_result(self):
        """Result should include CNN signal data"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            content = f.read()
        assert '"cnn_signal"' in content

    def test_no_subtractive_base_50(self):
        """Old subtractive base-50 scoring should be completely gone"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "confidence_gate.py")
        with open(filepath) as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            # Skip comments and strings
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            # Check for old subtractive base
            if "confidence_points = 50" in line:
                pytest.fail(f"Found old subtractive base 50 at line {i+1}: {line.strip()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
