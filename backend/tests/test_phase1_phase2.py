"""
Tests for Phase 1 (100% IB Data Pipeline) and Phase 2 (XGBoost GPU Swap)

Validates:
1. Alpaca is NOT called in any scanning/trading path
2. MongoDB is the sole data source for intraday bars, daily bars, and quote fallbacks
3. XGBoost replaces LightGBM with correct parameter mapping
4. Model serialization uses XGBoost JSON (not pickle)
5. Staleness check works correctly
"""
import pytest
import sys
import os
import importlib
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPhase1AlpacaRemoval:
    """Verify Alpaca is completely removed from critical trading paths"""

    def test_realtime_technical_service_no_alpaca(self):
        """realtime_technical_service.py should have zero Alpaca references"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "realtime_technical_service.py")
        with open(filepath) as f:
            content = f.read()
        # Should not import or reference alpaca
        assert "from services.alpaca_service" not in content
        assert "self._alpaca_service" not in content
        assert "self.alpaca" not in content

    def test_stock_data_no_alpaca_in_quote_chain(self):
        """stock_data.py get_quote should not call Alpaca or TwelveData"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "stock_data.py")
        with open(filepath) as f:
            content = f.read()
        # Should not have Alpaca or TwelveData fetch methods
        assert "_fetch_alpaca_quote" not in content
        assert "_fetch_twelvedata_quote" not in content
        assert "_fetch_finnhub_quote" not in content
        # Should have MongoDB fallback
        assert "_fetch_mongodb_bar_quote" in content

    def test_enhanced_scanner_no_alpaca_calls(self):
        """enhanced_scanner.py should not call Alpaca for quotes or ADV"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "enhanced_scanner.py")
        with open(filepath) as f:
            content = f.read()
        # _get_quote_with_ib_priority should not reference alpaca_service.get_quote
        assert "alpaca_service.get_quote" not in content
        # _fetch_single_adv should not reference alpaca_service.get_bars
        assert "alpaca_service.get_bars" not in content

    def test_market_context_no_finnhub_candles(self):
        """market_context.py _fetch_historical_data should use MongoDB, not Finnhub"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "market_context.py")
        with open(filepath) as f:
            content = f.read()
        assert "stock_candles" not in content
        assert "ib_historical_data" in content

    def test_hybrid_data_no_alpaca_fallback(self):
        """hybrid_data_service.py should not fall back to Alpaca"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "hybrid_data_service.py")
        with open(filepath) as f:
            content = f.read()
        assert "_fetch_from_alpaca" not in content
        assert "StockBarsRequest" not in content


class TestPhase1StalenessCheck:
    """Test the staleness check in realtime_technical_service"""

    def test_staleness_fresh_data(self):
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        # Fresh data (1 hour old)
        bars = [{"timestamp": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}]
        assert svc._check_staleness(bars, max_age_hours=24) is False

    def test_staleness_stale_data(self):
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        # Stale data (48 hours old)
        bars = [{"timestamp": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()}]
        assert svc._check_staleness(bars, max_age_hours=24) is True

    def test_staleness_no_data(self):
        from services.realtime_technical_service import RealTimeTechnicalService
        svc = RealTimeTechnicalService()
        assert svc._check_staleness(None) is True
        assert svc._check_staleness([]) is True


class TestPhase2XGBoostSwap:
    """Verify XGBoost replaces LightGBM correctly"""

    def test_xgboost_imported(self):
        """timeseries_gbm.py should use xgboost, not lightgbm"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "timeseries_gbm.py")
        with open(filepath) as f:
            content = f.read()
        assert "import xgboost as xgb" in content
        assert "import lightgbm as lgb" not in content

    def test_xgboost_params(self):
        """Default params should be XGBoost format"""
        from services.ai_modules.timeseries_gbm import TimeSeriesGBM
        params = TimeSeriesGBM.DEFAULT_PARAMS
        assert params["objective"] == "binary:logistic"
        assert params["eval_metric"] == "auc"
        assert params["tree_method"] == "hist"
        assert params["max_depth"] == 8
        assert "device" in params  # Should be 'cuda' or 'cpu'

    def test_xgboost_train_basic(self):
        """XGBoost should be able to train a basic model"""
        import xgboost as xgb
        X = np.random.randn(1000, 20).astype(np.float32)
        y = np.random.randint(0, 2, 1000).astype(np.float32)
        dtrain = xgb.DMatrix(X, label=y)
        params = {"objective": "binary:logistic", "max_depth": 4, "verbosity": 0}
        model = xgb.train(params, dtrain, num_boost_round=5)
        preds = model.predict(dtrain)
        assert preds.shape == (1000,)
        assert 0 <= preds.min() <= preds.max() <= 1

    def test_model_serialization_format(self):
        """Model should serialize to XGBoost JSON, not pickle"""
        filepath = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules", "timeseries_gbm.py")
        with open(filepath) as f:
            content = f.read()
        assert '"model_format": "xgboost_json"' in content
        assert "pickle.dumps" not in content
        assert "pickle.loads" not in content.split("# Legacy")[0]  # No pickle in new code

    def test_prediction_output_contract(self):
        """XGBoost model predictions should maintain same output contract"""
        from services.ai_modules.timeseries_gbm import TimeSeriesGBM, Prediction
        model = TimeSeriesGBM()
        # Without trained model, should return flat prediction
        result = model.predict([], symbol="TEST")
        assert isinstance(result, Prediction)
        assert result.direction == "flat"
        assert result.confidence == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
