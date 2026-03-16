"""
Test Analytics Tab Integration - Backtest, Shadow Mode, Scheduler APIs
Tests Priority 1 & 2 items:
1. Trading Scheduler Service
2. Learning Context Provider Service
3. Backtest UI APIs
4. Shadow Mode UI APIs
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://chat-input-debug.preview.emergentagent.com')


class TestSchedulerService:
    """Tests for Trading Scheduler Service - automated task scheduling"""
    
    def test_scheduler_status(self):
        """GET /api/scheduler/status - Returns scheduler status and configured services"""
        response = requests.get(f"{BASE_URL}/api/scheduler/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "is_running" in data
        assert "is_market_hours" in data
        assert "jobs" in data
        assert "services_configured" in data
        
        # Verify services configured
        services = data["services_configured"]
        assert "medium_learning" in services
        assert "weekly_report" in services
        assert "shadow_mode" in services
        assert "edge_decay" in services
        print(f"Scheduler status: is_running={data['is_running']}, jobs={len(data['jobs'])}")
    
    def test_scheduler_jobs(self):
        """GET /api/scheduler/jobs - Returns list of scheduled jobs"""
        response = requests.get(f"{BASE_URL}/api/scheduler/jobs", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "jobs" in data
        
        jobs = data["jobs"]
        # Expect 4 jobs: shadow_update, daily_analysis, edge_decay_check, weekly_report
        assert len(jobs) >= 4
        
        job_ids = [j["id"] for j in jobs]
        assert "shadow_update" in job_ids
        assert "daily_analysis" in job_ids
        assert "edge_decay_check" in job_ids
        assert "weekly_report" in job_ids
        
        print(f"Found {len(jobs)} scheduled jobs: {job_ids}")
    
    def test_scheduler_run_task_now(self):
        """POST /api/scheduler/run/{task_type} - Manually trigger a task"""
        response = requests.post(f"{BASE_URL}/api/scheduler/run/edge_decay_check", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Edge decay check triggered: {data.get('message')}")
    
    def test_scheduler_history(self):
        """GET /api/scheduler/history - Returns task execution history"""
        response = requests.get(f"{BASE_URL}/api/scheduler/history?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "history" in data
        assert "count" in data
        print(f"Task history: {data['count']} entries")


class TestBacktestAPI:
    """Tests for Backtest Panel APIs"""
    
    def test_backtest_run(self):
        """POST /api/slow-learning/backtest/run - Run a backtest"""
        payload = {
            "symbol": "AAPL",
            "timeframe": "1Day",
            "name": "TEST_Backtest_Integration",
            "starting_capital": 100000,
            "max_position_size_pct": 10,
            "default_stop_pct": 2.0,
            "default_target_pct": 4.0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/slow-learning/backtest/run",
            json=payload,
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "result" in data
        
        result = data["result"]
        assert "id" in result
        assert "name" in result
        assert "symbol" in result
        assert "total_trades" in result
        assert "win_rate" in result
        assert "total_pnl" in result
        assert "equity_curve" in result
        
        print(f"Backtest result: id={result['id']}, trades={result['total_trades']}, win_rate={result['win_rate']}")
    
    def test_backtest_get_results(self):
        """GET /api/slow-learning/backtest/results - Get stored backtest results"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/backtest/results", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "results" in data
        print(f"Stored backtests: {len(data['results'])} results")


class TestShadowModeAPI:
    """Tests for Shadow Mode Panel APIs"""
    
    def test_shadow_filters_get(self):
        """GET /api/slow-learning/shadow/filters - Get all shadow filters"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/filters", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "filters" in data
        assert "count" in data
        
        print(f"Shadow filters: {data['count']} filters")
        
        if data["count"] > 0:
            filter_data = data["filters"][0]
            assert "id" in filter_data
            assert "name" in filter_data
            assert "filter_type" in filter_data
            assert "is_active" in filter_data
            assert "win_rate" in filter_data
    
    def test_shadow_signals_get(self):
        """GET /api/slow-learning/shadow/signals - Get shadow signals"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/signals?limit=20", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "signals" in data
        assert "count" in data
        
        print(f"Shadow signals: {data['count']} signals")
        
        if data["count"] > 0:
            signal = data["signals"][0]
            assert "id" in signal
            assert "symbol" in signal
            assert "direction" in signal
            assert "signal_price" in signal
            assert "stop_price" in signal
            assert "target_price" in signal
            assert "status" in signal
    
    def test_shadow_report(self):
        """GET /api/slow-learning/shadow/report - Get shadow mode report"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/shadow/report?days=30", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "report" in data
        
        report = data["report"]
        assert "total_signals" in report
        assert "signals_pending" in report
        assert "overall_win_rate" in report
        assert "total_r" in report
        
        print(f"Shadow report: {report['total_signals']} signals, {report['overall_win_rate']*100:.0f}% win rate")
    
    def test_shadow_filter_create(self):
        """POST /api/slow-learning/shadow/filters - Create new filter"""
        payload = {
            "name": "TEST_Integration_Filter_New",
            "description": "Created by integration test",
            "filter_type": "entry",
            "criteria": {"min_tqs_score": 65}
        }
        
        response = requests.post(
            f"{BASE_URL}/api/slow-learning/shadow/filters",
            json=payload,
            timeout=30
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "filter" in data
        
        created_filter = data["filter"]
        assert created_filter["name"] == "TEST_Integration_Filter_New"
        print(f"Created filter: {created_filter['id']}")
    
    def test_shadow_signal_record(self):
        """POST /api/slow-learning/shadow/signals - Record shadow signal"""
        payload = {
            "symbol": "MSFT",
            "direction": "long",
            "setup_type": "breakout",
            "signal_price": 400.0,
            "stop_price": 395.0,
            "target_price": 410.0,
            "tqs_score": 75.0,
            "notes": "TEST_Integration signal"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/slow-learning/shadow/signals",
            json=payload,
            timeout=30
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "signal" in data
        
        signal = data["signal"]
        assert signal["symbol"] == "MSFT"
        assert signal["status"] == "pending"
        print(f"Recorded signal: {signal['id']}")
    
    def test_shadow_update_outcomes(self):
        """POST /api/slow-learning/shadow/update-outcomes - Update signal outcomes"""
        response = requests.post(f"{BASE_URL}/api/slow-learning/shadow/update-outcomes", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Update outcomes: {data.get('updated', 0)} signals updated")


class TestLearningContextProvider:
    """Tests for Learning Context Provider - AI assistant integration"""
    
    def test_slow_learning_status(self):
        """GET /api/slow-learning/status - Check all slow learning services"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        # Verify all 3 slow learning services are tracked (nested under "services")
        services = data.get("services", {})
        assert "historical_data" in services
        assert "backtest_engine" in services
        assert "shadow_mode" in services
        
        print(f"Slow learning status: historical={services['historical_data']}, backtest={services['backtest_engine']}, shadow={services['shadow_mode']}")


class TestHistoricalDataAPI:
    """Tests for Historical Data Service"""
    
    def test_historical_symbols(self):
        """GET /api/slow-learning/historical/symbols - Get stored symbols"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/symbols", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "symbols" in data
        print(f"Historical data symbols: {len(data['symbols'])} symbols stored")
    
    def test_historical_stats(self):
        """GET /api/slow-learning/historical/stats - Get data stats"""
        response = requests.get(f"{BASE_URL}/api/slow-learning/historical/stats", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "stats" in data
        print(f"Historical stats: {len(data['stats'])} entries")


class TestMediumLearningIntegration:
    """Tests for Medium Learning service status"""
    
    def test_medium_learning_calibration_config(self):
        """GET /api/medium-learning/calibration/config - Get calibration config"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/calibration/config", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Calibration config retrieved")
    
    def test_medium_learning_calibration_analyze(self):
        """POST /api/medium-learning/calibration/analyze - Analyze and get recommendations"""
        response = requests.post(f"{BASE_URL}/api/medium-learning/calibration/analyze?lookback_days=30", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Calibration recommendations: {data.get('count', 0)} found")
    
    def test_medium_learning_status(self):
        """GET /api/medium-learning/status - Get all services status"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        assert "services" in data
        print(f"Medium learning status: services loaded")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
