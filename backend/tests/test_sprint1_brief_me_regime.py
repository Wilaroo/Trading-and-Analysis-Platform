"""
Sprint 1 Backend Tests - Brief Me Feature & Enhanced Market Regime
==================================================================
Tests for:
1. POST /api/agents/brief-me - AI-generated personalized market briefing
2. GET /api/market-regime/performance - Regime performance stats

Note: Regime performance shows 0 trades because existing trades don't have 
market_regime field tagged yet - this is expected behavior.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBriefMeAPI:
    """Tests for the Brief Me Agent endpoint"""
    
    def test_brief_me_quick_summary(self):
        """Test POST /api/agents/brief-me with detail_level='quick'"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Data assertions
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert data.get("detail_level") == "quick", f"Expected detail_level='quick', got: {data.get('detail_level')}"
        assert "summary" in data, f"Expected 'summary' in response, got: {data.keys()}"
        assert "generated_at" in data, f"Expected 'generated_at' in response"
        
        # Summary should be a string for quick mode
        summary = data.get("summary")
        assert isinstance(summary, str), f"Expected summary to be string for quick mode, got: {type(summary)}"
        assert len(summary) > 10, f"Summary too short: {summary}"
        
        print(f"Quick summary: {summary[:200]}...")
    
    def test_brief_me_detailed_summary(self):
        """Test POST /api/agents/brief-me with detail_level='detailed'"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Data assertions
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert data.get("detail_level") == "detailed", f"Expected detail_level='detailed', got: {data.get('detail_level')}"
        assert "summary" in data, f"Expected 'summary' in response"
        
        # Detailed mode returns dict with sections
        summary = data.get("summary")
        assert summary is not None, "Summary should not be None"
        
        # If dict, check for sections
        if isinstance(summary, dict):
            # Check for expected sections in detailed mode
            expected_sections = ["market_overview", "bot_status", "personalized_insights", "opportunities", "recommendation"]
            found_sections = [s for s in expected_sections if s in summary]
            print(f"Found sections: {found_sections}")
            # At least some sections should be present
            assert len(found_sections) >= 3 or "full_summary" in summary, f"Expected detailed sections, got: {summary.keys()}"
    
    def test_brief_me_data_structure(self):
        """Test that brief-me returns proper data structure"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check data field
        brief_data = data.get("data")
        assert brief_data is not None, "Expected 'data' field in response"
        
        # Check market_summary
        market_summary = brief_data.get("market_summary", {})
        assert "regime" in market_summary, f"Expected 'regime' in market_summary: {market_summary}"
        assert "regime_score" in market_summary, f"Expected 'regime_score' in market_summary"
        
        # Check your_bot section
        your_bot = brief_data.get("your_bot", {})
        assert "state" in your_bot, f"Expected 'state' in your_bot: {your_bot}"
        assert "running" in your_bot, f"Expected 'running' in your_bot"
        assert "today_pnl" in your_bot, f"Expected 'today_pnl' in your_bot"
        
        # Check personalized_insights
        insights = brief_data.get("personalized_insights", {})
        assert insights is not None, "Expected personalized_insights in data"
        
        print(f"Regime: {market_summary.get('regime')}, Bot running: {your_bot.get('running')}, Today P&L: {your_bot.get('today_pnl')}")
    
    def test_brief_me_default_detail_level(self):
        """Test brief-me with default (no detail_level specified)"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        # Default should be 'quick'
        assert data.get("detail_level") == "quick", f"Expected default 'quick', got: {data.get('detail_level')}"


class TestRegimePerformanceAPI:
    """Tests for the Market Regime Performance endpoint"""
    
    def test_regime_performance_endpoint(self):
        """Test GET /api/market-regime/performance"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/performance",
            timeout=15
        )
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Data assertions
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "current_regime" in data, f"Expected 'current_regime' in response"
        assert "performance_by_regime" in data, f"Expected 'performance_by_regime' in response"
        assert "your_edge_in_current" in data, f"Expected 'your_edge_in_current' in response"
        
        print(f"Current regime: {data.get('current_regime')}")
    
    def test_regime_performance_structure(self):
        """Test that performance_by_regime has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/performance",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        
        perf_by_regime = data.get("performance_by_regime", {})
        expected_regimes = ["RISK_ON", "HOLD", "RISK_OFF", "CONFIRMED_DOWN"]
        
        for regime in expected_regimes:
            assert regime in perf_by_regime, f"Expected regime '{regime}' in performance_by_regime"
            stats = perf_by_regime[regime]
            
            # Check expected fields in each regime stats
            assert "trades" in stats, f"Expected 'trades' in {regime} stats"
            assert "wins" in stats, f"Expected 'wins' in {regime} stats"
            assert "win_rate" in stats, f"Expected 'win_rate' in {regime} stats"
            assert "total_pnl" in stats, f"Expected 'total_pnl' in {regime} stats"
            assert "avg_pnl" in stats, f"Expected 'avg_pnl' in {regime} stats"
            
            print(f"{regime}: trades={stats.get('trades')}, win_rate={stats.get('win_rate')}%")
    
    def test_regime_performance_with_specific_regime(self):
        """Test GET /api/market-regime/performance?regime=RISK_ON"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/performance?regime=RISK_ON",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        # When specific regime requested, current_regime should reflect it
        assert data.get("current_regime") == "RISK_ON", f"Expected current_regime='RISK_ON', got: {data.get('current_regime')}"
    
    def test_your_edge_in_current_regime(self):
        """Test that your_edge_in_current reflects current regime stats"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/performance",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        
        current_regime = data.get("current_regime")
        your_edge = data.get("your_edge_in_current", {})
        perf_by_regime = data.get("performance_by_regime", {})
        
        # your_edge_in_current should match the current regime's stats
        if current_regime in perf_by_regime:
            expected_stats = perf_by_regime[current_regime]
            assert your_edge.get("trades") == expected_stats.get("trades"), "your_edge trades mismatch"
            assert your_edge.get("win_rate") == expected_stats.get("win_rate"), "your_edge win_rate mismatch"
        
        print(f"Your edge in {current_regime}: {your_edge}")


class TestExistingAgentEndpoints:
    """Test existing agent endpoints still work"""
    
    def test_agent_status(self):
        """Test GET /api/agents/status"""
        response = requests.get(
            f"{BASE_URL}/api/agents/status",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "orchestrator_ready" in data
        assert "agents" in data
        
        print(f"Agent status: orchestrator_ready={data.get('orchestrator_ready')}, agents={data.get('agents')}")
    
    def test_agent_metrics(self):
        """Test GET /api/agents/metrics"""
        response = requests.get(
            f"{BASE_URL}/api/agents/metrics",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        # Either success=True or error message (if no orchestrator)
        assert "success" in data or "error" in data


class TestMarketRegimeExistingEndpoints:
    """Test existing market regime endpoints still work"""
    
    def test_market_regime_summary(self):
        """Test GET /api/market-regime/summary"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/summary",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "state" in data, f"Expected 'state' in response"
        assert "composite_score" in data, f"Expected 'composite_score' in response"
        assert "signal_scores" in data, f"Expected 'signal_scores' in response"
        
        print(f"Regime: {data.get('state')}, Score: {data.get('composite_score')}")
    
    def test_market_regime_current(self):
        """Test GET /api/market-regime/current"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/current",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "state" in data
        assert "composite_score" in data
    
    def test_trading_implications(self):
        """Test GET /api/market-regime/trading-implications"""
        response = requests.get(
            f"{BASE_URL}/api/market-regime/trading-implications",
            timeout=15
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "state" in data
        assert "implications" in data or "recommendation" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
