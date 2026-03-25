"""
Test Full AI Simulation endpoints in advanced_backtest_router.py
Tests the unified backtesting engine endpoints for Full AI Pipeline Simulation
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known completed job ID for testing
TEST_JOB_ID = "sim_ce720089dca3"


class TestFullAISimulationEndpoints:
    """Test Full AI Simulation API endpoints"""
    
    def test_health_check(self):
        """Verify backend is healthy before running tests"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("✓ Backend health check passed")
    
    def test_list_simulation_jobs(self):
        """Test GET /api/backtest/full-ai-simulation/jobs returns jobs list"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/jobs?limit=20")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert data.get("success") is True
        assert "jobs" in data
        assert isinstance(data["jobs"], list)
        
        # Verify at least one job exists (we know sim_ce720089dca3 exists)
        assert len(data["jobs"]) > 0
        
        # Verify job structure
        job = data["jobs"][0]
        assert "id" in job
        assert "status" in job
        assert "config" in job
        print(f"✓ Jobs list returned {len(data['jobs'])} jobs")
    
    def test_get_simulation_status(self):
        """Test GET /api/backtest/full-ai-simulation/status/{job_id}"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/status/{TEST_JOB_ID}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert data.get("success") is True
        assert "job" in data
        
        job = data["job"]
        assert job.get("id") == TEST_JOB_ID
        assert job.get("status") == "completed"
        assert "config" in job
        assert "total_trades" in job
        assert "win_rate" in job
        assert "total_pnl" in job
        
        # Verify job has 28 trades as expected
        assert job.get("total_trades") == 28
        print(f"✓ Job status returned: {job['status']} with {job['total_trades']} trades")
    
    def test_get_simulation_status_not_found(self):
        """Test GET /api/backtest/full-ai-simulation/status/{job_id} with invalid ID"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/status/invalid_job_id_12345")
        assert response.status_code == 404
        print("✓ Invalid job ID returns 404")
    
    def test_get_simulation_summary(self):
        """Test GET /api/backtest/full-ai-simulation/summary/{job_id}"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/summary/{TEST_JOB_ID}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert data.get("success") is True
        assert data.get("job_id") == TEST_JOB_ID
        assert "summary" in data
        
        summary = data["summary"]
        
        # Verify summary stats
        assert "total_trades" in summary
        assert "winners" in summary
        assert "losers" in summary
        assert "win_rate" in summary
        assert "total_pnl" in summary
        assert "avg_win" in summary
        assert "avg_loss" in summary
        assert "profit_factor" in summary
        assert "total_decisions" in summary
        
        # Verify symbols breakdown exists
        assert "symbols_breakdown" in summary
        assert isinstance(summary["symbols_breakdown"], dict)
        assert len(summary["symbols_breakdown"]) > 0
        
        # Verify symbols breakdown structure
        for symbol, breakdown in summary["symbols_breakdown"].items():
            assert "trades" in breakdown
            assert "pnl" in breakdown
            assert "wins" in breakdown
        
        print(f"✓ Summary returned with {summary['total_trades']} trades, {len(summary['symbols_breakdown'])} symbols")
    
    def test_get_simulation_trades(self):
        """Test GET /api/backtest/full-ai-simulation/trades/{job_id}"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/trades/{TEST_JOB_ID}?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert data.get("success") is True
        assert data.get("job_id") == TEST_JOB_ID
        assert "trades" in data
        assert "count" in data
        
        trades = data["trades"]
        assert isinstance(trades, list)
        assert len(trades) > 0
        
        # Verify trade structure
        trade = trades[0]
        assert "id" in trade
        assert "symbol" in trade
        assert "direction" in trade
        assert "entry_price" in trade
        assert "exit_price" in trade
        assert "shares" in trade
        assert "realized_pnl" in trade
        assert "setup_type" in trade
        assert "exit_reason" in trade
        
        # Verify AI consultation data exists
        assert "ai_consultation" in trade
        if trade["ai_consultation"]:
            assert "recommendation" in trade["ai_consultation"]
        
        print(f"✓ Trades returned {len(trades)} trades with full details")
    
    def test_get_simulation_decisions(self):
        """Test GET /api/backtest/full-ai-simulation/decisions/{job_id}"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/decisions/{TEST_JOB_ID}?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert data.get("success") is True
        assert data.get("job_id") == TEST_JOB_ID
        assert "decisions" in data
        assert "count" in data
        
        decisions = data["decisions"]
        assert isinstance(decisions, list)
        assert len(decisions) > 0
        
        # Verify decision structure
        decision = decisions[0]
        assert "date" in decision
        assert "symbol" in decision
        assert "signal" in decision
        assert "ai_decision" in decision
        
        # Verify signal structure
        signal = decision["signal"]
        assert "type" in signal
        assert "direction" in signal
        assert "strength" in signal
        
        # Verify AI decision structure
        ai_decision = decision["ai_decision"]
        assert "recommendation" in ai_decision
        assert "confidence" in ai_decision
        
        # Verify timeseries forecast exists in agents
        if "agents" in ai_decision and ai_decision["agents"]:
            if "timeseries" in ai_decision["agents"]:
                ts = ai_decision["agents"]["timeseries"]
                assert "direction" in ts
                assert "probability_up" in ts
                assert "probability_down" in ts
        
        print(f"✓ Decisions returned {len(decisions)} AI decisions with signal and forecast data")
    
    def test_trades_limit_parameter(self):
        """Test that limit parameter works for trades endpoint"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/trades/{TEST_JOB_ID}?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["trades"]) <= 5
        print(f"✓ Trades limit parameter works: returned {len(data['trades'])} trades")
    
    def test_decisions_limit_parameter(self):
        """Test that limit parameter works for decisions endpoint"""
        response = requests.get(f"{BASE_URL}/api/backtest/full-ai-simulation/decisions/{TEST_JOB_ID}?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["decisions"]) <= 5
        print(f"✓ Decisions limit parameter works: returned {len(data['decisions'])} decisions")


class TestOtherBacktestTabs:
    """Regression tests for other backtest tabs (Quick Test, AI Comparison, Market-Wide)"""
    
    def test_quick_backtest_strategies(self):
        """Test GET /api/backtest/strategies for Quick Test tab"""
        response = requests.get(f"{BASE_URL}/api/backtest/strategies")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") is True
        assert "strategies" in data
        print(f"✓ Quick Test strategies endpoint works: {len(data.get('strategies', []))} strategies")
    
    def test_general_backtest_jobs(self):
        """Test GET /api/backtest/jobs - general jobs list used by multiple tabs"""
        response = requests.get(f"{BASE_URL}/api/backtest/jobs?limit=10")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") is True
        assert "jobs" in data
        print(f"✓ General backtest jobs endpoint works: {len(data.get('jobs', []))} jobs")
    
    def test_ai_comparison_status(self):
        """Test GET /api/backtest/ai-comparison/status for AI Comparison tab"""
        response = requests.get(f"{BASE_URL}/api/backtest/ai-comparison/status")
        # This endpoint may return 404 if no job is running, which is acceptable
        assert response.status_code in [200, 404]
        print(f"✓ AI Comparison status endpoint responds: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
