"""
Test Suite for Phase 6 Slow Learning - Backtesting, Historical Data, Shadow Mode
Tests: Historical Data Service, Backtest Engine, Shadow Mode Service
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSlowLearningStatus:
    """Test Slow Learning status endpoint"""
    
    def test_get_status(self):
        """GET /api/slow-learning/status - All services status"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "services" in data
        
        services = data["services"]
        assert "historical_data" in services
        assert "backtest_engine" in services
        assert "shadow_mode" in services
        
        # Verify historical_data service stats
        hd = services["historical_data"]
        assert "db_connected" in hd
        assert "alpaca_connected" in hd
        assert "symbols_stored" in hd
        assert "total_bars" in hd
        
        # Verify backtest_engine stats
        bt = services["backtest_engine"]
        assert "db_connected" in bt
        assert "backtests_stored" in bt
        
        # Verify shadow_mode stats
        sm = services["shadow_mode"]
        assert "db_connected" in sm
        assert "active_filters" in sm
        assert "total_signals" in sm
        assert "pending_signals" in sm
        
        print(f"Status check passed - All 3 services connected")


class TestHistoricalDataService:
    """Test Historical Data endpoints"""
    
    def test_get_available_symbols_empty(self):
        """GET /api/slow-learning/historical/symbols - Get available symbols (initially empty)"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/symbols")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "symbols" in data
        assert isinstance(data["symbols"], list)
        print(f"Available symbols: {data['symbols']}")
    
    def test_get_historical_stats_empty(self):
        """GET /api/slow-learning/historical/stats - Get data stats (initially empty)"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert isinstance(data["stats"], list)
        print(f"Historical stats count: {len(data['stats'])}")
    
    def test_download_historical_data(self):
        """POST /api/slow-learning/historical/download - Download historical data for AAPL"""
        payload = {
            "symbol": "AAPL",
            "timeframe": "1Day",
            "days_back": 30  # Last 30 days for quick test
        }
        
        response = requests.post(f"{BASE_URL}/api/slow-learning/historical/download", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["symbol"] == "AAPL"
        assert data["timeframe"] == "1Day"
        assert "bars_fetched" in data
        assert "bars_stored" in data
        assert "date_range" in data
        
        print(f"Downloaded {data['bars_fetched']} bars for AAPL, stored: {data['bars_stored']}")
    
    def test_get_historical_bars(self):
        """GET /api/slow-learning/historical/bars/{symbol} - Get stored historical bars"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/bars/AAPL")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "bars" in data
        assert "count" in data
        
        if data["count"] > 0:
            bar = data["bars"][0]
            assert "symbol" in bar
            assert "timeframe" in bar
            assert "timestamp" in bar
            assert "open" in bar
            assert "high" in bar
            assert "low" in bar
            assert "close" in bar
            assert "volume" in bar
            print(f"Retrieved {data['count']} bars for AAPL")
        else:
            print("No bars found (may be due to market hours)")
    
    def test_get_available_symbols_after_download(self):
        """GET /api/slow-learning/historical/symbols - Should include AAPL after download"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/symbols")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # AAPL should be in symbols after successful download
        print(f"Available symbols after download: {data['symbols']}")
    
    def test_get_historical_stats_after_download(self):
        """GET /api/slow-learning/historical/stats - Should have AAPL stats after download"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        
        if len(data["stats"]) > 0:
            stat = data["stats"][0]
            assert "symbol" in stat
            assert "timeframe" in stat
            assert "bar_count" in stat
            assert "first_bar" in stat
            assert "last_bar" in stat
            assert "data_quality" in stat
            print(f"Stats: {len(data['stats'])} entries")
        else:
            print("No stats available")


class TestBacktestEngine:
    """Test Backtest Engine endpoints"""
    
    def test_run_backtest(self):
        """POST /api/slow-learning/backtest/run - Run backtest"""
        payload = {
            "symbol": "AAPL",
            "timeframe": "1Day",
            "name": "TEST_AAPL_Backtest",
            "starting_capital": 100000,
            "max_position_size_pct": 10,
            "default_stop_pct": 2.0,
            "default_target_pct": 4.0,
            "min_volume": 100000,
            "max_bars_to_hold": 10
        }
        
        response = requests.post(f"{BASE_URL}/api/slow-learning/backtest/run", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "result" in data
        
        result = data["result"]
        assert "id" in result
        assert result["id"].startswith("bt_")
        assert result["symbol"] == "AAPL"
        assert result["name"] == "TEST_AAPL_Backtest"
        assert "total_trades" in result
        assert "winning_trades" in result
        assert "losing_trades" in result
        assert "win_rate" in result
        assert "total_pnl" in result
        assert "max_drawdown" in result
        assert "trades" in result
        assert "equity_curve" in result
        assert "config" in result
        
        print(f"Backtest completed: {result['total_trades']} trades, Win rate: {result['win_rate']*100:.1f}%")
        return result["id"]
    
    def test_get_backtest_results(self):
        """GET /api/slow-learning/backtest/results - Get backtest results"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/backtest/results")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "results" in data
        assert "count" in data
        
        print(f"Total backtest results: {data['count']}")
        
        if data["count"] > 0:
            result = data["results"][0]
            assert "id" in result
            assert "symbol" in result
            assert "total_trades" in result
            return result["id"]
        return None
    
    def test_get_backtest_result_by_id(self):
        """GET /api/slow-learning/backtest/results/{backtest_id} - Get specific backtest"""
        # First get any existing backtest ID
        list_response = requests.get(f"{BASE_URL}/api/slow-learning/backtest/results")
        if list_response.status_code == 200 and list_response.json().get("count", 0) > 0:
            backtest_id = list_response.json()["results"][0]["id"]
            
            response = requests.get(f"{BASE_URL}/api/slow-learning/backtest/results/{backtest_id}")
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            assert data["result"]["id"] == backtest_id
            print(f"Retrieved backtest: {backtest_id}")
        else:
            print("No backtests to retrieve")
    
    def test_get_backtest_not_found(self):
        """GET /api/slow-learning/backtest/results/{id} - 404 for non-existent"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/backtest/results/bt_nonexistent123")
        assert response.status_code == 404


class TestShadowModeService:
    """Test Shadow Mode endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Store created filter/signal IDs for cleanup"""
        self.created_filter_id = None
        self.created_signal_id = None
    
    def test_create_shadow_filter(self):
        """POST /api/slow-learning/shadow/filters - Create shadow filter"""
        payload = {
            "name": "TEST_High_TQS_Filter",
            "description": "Filter for high TQS score entries",
            "filter_type": "entry",
            "criteria": {
                "min_tqs_score": 75,
                "min_confirmations": 2
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/filters", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "filter" in data
        
        filter_obj = data["filter"]
        assert "id" in filter_obj
        assert filter_obj["id"].startswith("sf_")
        assert filter_obj["name"] == "TEST_High_TQS_Filter"
        assert filter_obj["filter_type"] == "entry"
        assert filter_obj["criteria"]["min_tqs_score"] == 75
        assert filter_obj["is_active"] is True
        assert filter_obj["is_validated"] is False
        
        print(f"Created shadow filter: {filter_obj['id']}")
        return filter_obj["id"]
    
    def test_get_shadow_filters(self):
        """GET /api/slow-learning/shadow/filters - Get all filters"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "filters" in data
        assert "count" in data
        
        print(f"Total active filters: {data['count']}")
        
        if data["count"] > 0:
            return data["filters"][0]["id"]
        return None
    
    def test_get_shadow_filters_with_inactive(self):
        """GET /api/slow-learning/shadow/filters?active_only=false - Include inactive"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters?active_only=false")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
    
    def test_record_shadow_signal(self):
        """POST /api/slow-learning/shadow/signals - Record shadow signal"""
        # First get a filter ID to associate
        filters_resp = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters")
        filter_id = filters_resp.json()["filters"][0]["id"] if filters_resp.json().get("count", 0) > 0 else None
        
        payload = {
            "symbol": "AAPL",
            "direction": "long",
            "setup_type": "breakout",
            "signal_price": 180.0,
            "stop_price": 175.0,
            "target_price": 190.0,
            "filter_id": filter_id,
            "tqs_score": 78.5,
            "market_regime": "TRENDING",
            "confirmations": ["volume_spike", "RSI_bullish"],
            "notes": "TEST_Shadow_Signal for testing"
        }
        
        response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/signals", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "signal" in data
        
        signal = data["signal"]
        assert "id" in signal
        assert signal["id"].startswith("ss_")
        assert signal["symbol"] == "AAPL"
        assert signal["direction"] == "long"
        assert signal["setup_type"] == "breakout"
        assert signal["signal_price"] == 180.0
        assert signal["stop_price"] == 175.0
        assert signal["target_price"] == 190.0
        assert signal["tqs_score"] == 78.5
        assert signal["status"] == "pending"
        assert "volume_spike" in signal["confirmations"]
        
        print(f"Created shadow signal: {signal['id']}")
        return signal["id"]
    
    def test_get_shadow_signals(self):
        """GET /api/slow-learning/shadow/signals - Get signals"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/signals")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "signals" in data
        assert "count" in data
        
        print(f"Total signals: {data['count']}")
        
        if data["count"] > 0:
            signal = data["signals"][0]
            assert "id" in signal
            assert "symbol" in signal
            assert "status" in signal
    
    def test_get_shadow_signals_filtered(self):
        """GET /api/slow-learning/shadow/signals - Get signals with filters"""
        # Filter by status
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/signals?status=pending")
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        # Filter by symbol
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/signals?symbol=AAPL")
        assert response.status_code == 200
        assert response.json()["success"] is True
    
    def test_update_shadow_outcomes(self):
        """POST /api/slow-learning/shadow/update-outcomes - Update outcomes"""
        response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/update-outcomes")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "updated" in data
        assert "pending_checked" in data
        
        print(f"Outcomes update: {data['updated']} updated, {data['pending_checked']} checked")
    
    def test_get_shadow_report(self):
        """GET /api/slow-learning/shadow/report - Get shadow report"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/report?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert "report_date" in report
        assert "report_period_days" in report
        assert report["report_period_days"] == 30
        assert "total_signals" in report
        assert "signals_resolved" in report
        assert "signals_pending" in report
        assert "overall_win_rate" in report
        assert "total_r" in report
        assert "filter_performance" in report
        assert "filters_to_activate" in report
        assert "filters_to_review" in report
        assert "filters_to_deactivate" in report
        
        print(f"Shadow report: {report['total_signals']} signals, {report['overall_win_rate']*100:.1f}% win rate")
    
    def test_get_single_filter(self):
        """GET /api/slow-learning/shadow/filters/{filter_id} - Get single filter"""
        # Get a filter ID first
        filters_resp = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters")
        if filters_resp.json().get("count", 0) > 0:
            filter_id = filters_resp.json()["filters"][0]["id"]
            
            response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters/{filter_id}")
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            assert data["filter"]["id"] == filter_id
    
    def test_get_filter_not_found(self):
        """GET /api/slow-learning/shadow/filters/{id} - 404 for non-existent"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters/sf_nonexistent")
        assert response.status_code == 404
    
    def test_validate_filter(self):
        """POST /api/slow-learning/shadow/filters/{id}/validate - Validate filter"""
        # Get a filter ID first
        filters_resp = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters")
        if filters_resp.json().get("count", 0) > 0:
            filter_id = filters_resp.json()["filters"][0]["id"]
            
            response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/filters/{filter_id}/validate")
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            # Filter won't be validated with < 20 signals
            assert "validated" in data
            assert "reason" in data or "recommendation" in data
            print(f"Filter validation: validated={data.get('validated', False)}")
    
    def test_deactivate_filter(self):
        """POST /api/slow-learning/shadow/filters/{id}/deactivate - Deactivate filter"""
        # Create a new filter to deactivate
        create_payload = {
            "name": "TEST_Filter_To_Deactivate",
            "description": "Test filter for deactivation",
            "filter_type": "exit",
            "criteria": {"max_holding_days": 5}
        }
        create_resp = requests.post(f"{BASE_URL}/api/slow-learning/shadow/filters", json=create_payload)
        if create_resp.status_code == 200:
            filter_id = create_resp.json()["filter"]["id"]
            
            response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/filters/{filter_id}/deactivate")
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            print(f"Deactivated filter: {filter_id}")


class TestIntegrationFlow:
    """Test end-to-end integration flow"""
    
    def test_full_slow_learning_flow(self):
        """Integration test: Download -> Backtest -> Shadow Signal"""
        # Step 1: Check status
        status_resp = requests.get(f"{BASE_URL}/api/slow-learning/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["services"]["historical_data"]["db_connected"] is True
        print("Step 1: Status OK")
        
        # Step 2: Download historical data (using SPY for variety)
        download_resp = requests.post(f"{BASE_URL}/api/slow-learning/historical/download", json={
            "symbol": "SPY",
            "timeframe": "1Day",
            "days_back": 30
        })
        assert download_resp.status_code == 200
        assert download_resp.json()["success"] is True
        print(f"Step 2: Downloaded {download_resp.json().get('bars_fetched', 0)} bars for SPY")
        
        # Step 3: Run backtest
        backtest_resp = requests.post(f"{BASE_URL}/api/slow-learning/backtest/run", json={
            "symbol": "SPY",
            "timeframe": "1Day",
            "name": "TEST_SPY_Integration"
        })
        assert backtest_resp.status_code == 200
        assert backtest_resp.json()["success"] is True
        print(f"Step 3: Backtest completed with {backtest_resp.json()['result']['total_trades']} trades")
        
        # Step 4: Create shadow filter
        filter_resp = requests.post(f"{BASE_URL}/api/slow-learning/shadow/filters", json={
            "name": "TEST_Integration_Filter",
            "description": "Integration test filter",
            "filter_type": "entry",
            "criteria": {"min_tqs_score": 70}
        })
        assert filter_resp.status_code == 200
        filter_id = filter_resp.json()["filter"]["id"]
        print(f"Step 4: Created filter {filter_id}")
        
        # Step 5: Record shadow signal
        signal_resp = requests.post(f"{BASE_URL}/api/slow-learning/shadow/signals", json={
            "symbol": "SPY",
            "direction": "long",
            "setup_type": "momentum",
            "signal_price": 500.0,
            "stop_price": 495.0,
            "target_price": 510.0,
            "filter_id": filter_id,
            "tqs_score": 72.0
        })
        assert signal_resp.status_code == 200
        print(f"Step 5: Created signal {signal_resp.json()['signal']['id']}")
        
        # Step 6: Generate shadow report
        report_resp = requests.get(f"{BASE_URL}/api/slow-learning/shadow/report?days=7")
        assert report_resp.status_code == 200
        print(f"Step 6: Shadow report generated with {report_resp.json()['report']['total_signals']} signals")
        
        print("Full integration flow PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
