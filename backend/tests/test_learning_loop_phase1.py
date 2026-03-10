"""
Test Suite for Three-Speed Learning Architecture Phase 1 APIs
Tests all new learning loop endpoints defined in learning_dashboard.py
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLearningLoopStats:
    """Tests for GET /api/learning/loop/stats endpoint"""
    
    def test_learning_stats_no_filters(self):
        """Test getting learning stats without any filters"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, "Response should have success=True"
        assert "stats" in data, "Response should contain 'stats' field"
        assert "count" in data, "Response should contain 'count' field"
        assert isinstance(data["stats"], list), "Stats should be a list"
        print(f"PASS: Learning stats returned {data['count']} items")
    
    def test_learning_stats_with_setup_type_filter(self):
        """Test getting learning stats with setup_type filter"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/stats",
            params={"setup_type": "bull_flag"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert isinstance(data["stats"], list)
        print(f"PASS: Learning stats with setup_type filter returned {data['count']} items")
    
    def test_learning_stats_with_market_regime_filter(self):
        """Test getting learning stats with market_regime filter"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/stats",
            params={"market_regime": "strong_uptrend"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        print(f"PASS: Learning stats with market_regime filter returned {data['count']} items")
    
    def test_learning_stats_with_time_of_day_filter(self):
        """Test getting learning stats with time_of_day filter"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/stats",
            params={"time_of_day": "morning_momentum"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        print(f"PASS: Learning stats with time_of_day filter returned {data['count']} items")
    
    def test_learning_stats_with_multiple_filters(self):
        """Test getting learning stats with multiple filters"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/stats",
            params={
                "setup_type": "bull_flag",
                "market_regime": "strong_uptrend",
                "time_of_day": "morning_momentum"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        print(f"PASS: Learning stats with multiple filters returned {data['count']} items")


class TestContextualWinRate:
    """Tests for GET /api/learning/loop/contextual-winrate endpoint"""
    
    def test_contextual_winrate_required_param(self):
        """Test contextual win rate with required setup_type"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/contextual-winrate",
            params={"setup_type": "bull_flag"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "win_rate" in data, "Response should contain 'win_rate'"
        assert "sample_size" in data, "Response should contain 'sample_size'"
        assert "confidence" in data, "Response should contain 'confidence'"
        print(f"PASS: Contextual win rate: {data.get('win_rate', 0)*100:.0f}% with {data.get('confidence')} confidence")
    
    def test_contextual_winrate_missing_required_param(self):
        """Test contextual win rate without required setup_type returns 422"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/contextual-winrate")
        assert response.status_code == 422, f"Expected 422 for missing required param, got {response.status_code}"
        print("PASS: Missing setup_type correctly returns 422 validation error")
    
    def test_contextual_winrate_with_context_filters(self):
        """Test contextual win rate with additional context filters"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/contextual-winrate",
            params={
                "setup_type": "vwap_bounce",
                "market_regime": "range_bound",
                "time_of_day": "midday"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        print(f"PASS: Contextual win rate with filters returned confidence: {data.get('confidence')}")


class TestTradeOutcomes:
    """Tests for GET /api/learning/loop/outcomes endpoint"""
    
    def test_trade_outcomes_default(self):
        """Test getting recent trade outcomes with default params"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/outcomes")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "outcomes" in data, "Response should contain 'outcomes'"
        assert "count" in data, "Response should contain 'count'"
        assert isinstance(data["outcomes"], list), "Outcomes should be a list"
        print(f"PASS: Trade outcomes returned {data['count']} records")
    
    def test_trade_outcomes_with_limit(self):
        """Test getting trade outcomes with custom limit"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/outcomes",
            params={"limit": 5}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert len(data["outcomes"]) <= 5, "Should not exceed limit"
        print(f"PASS: Trade outcomes with limit=5 returned {data['count']} records")
    
    def test_trade_outcomes_with_setup_type(self):
        """Test getting trade outcomes filtered by setup_type"""
        response = requests.get(
            f"{BASE_URL}/api/learning/loop/outcomes",
            params={"setup_type": "bull_flag", "limit": 10}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        print(f"PASS: Trade outcomes with setup_type filter returned {data['count']} records")


class TestTraderProfile:
    """Tests for GET /api/learning/loop/profile endpoint"""
    
    def test_trader_profile(self):
        """Test getting trader profile for RAG"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/profile")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "profile" in data, "Response should contain 'profile'"
        assert "ai_context" in data, "Response should contain 'ai_context'"
        
        profile = data["profile"]
        # Verify expected profile fields exist
        expected_fields = ["profile_id", "best_setups", "worst_setups", "best_hours", 
                         "worst_hours", "overall_win_rate", "overall_profit_factor"]
        for field in expected_fields:
            assert field in profile, f"Profile should contain '{field}'"
        
        print(f"PASS: Trader profile returned with {len(profile.get('best_setups', []))} best setups")
        print(f"      AI Context: {data['ai_context'][:100]}..." if data['ai_context'] else "      AI Context: (empty)")


class TestTiltStatus:
    """Tests for GET /api/learning/loop/tilt-status endpoint"""
    
    def test_tilt_status(self):
        """Test getting current tilt status"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/tilt-status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "is_tilted" in data, "Response should contain 'is_tilted'"
        assert "severity" in data, "Response should contain 'severity'"
        
        # Verify valid severity values
        valid_severities = ["none", "mild", "moderate", "severe"]
        assert data["severity"] in valid_severities, f"Severity should be one of {valid_severities}"
        
        print(f"PASS: Tilt status: is_tilted={data['is_tilted']}, severity={data['severity']}")


class TestDailyAnalysis:
    """Tests for POST /api/learning/loop/daily-analysis endpoint"""
    
    def test_daily_analysis_trigger(self):
        """Test triggering daily analysis"""
        response = requests.post(f"{BASE_URL}/api/learning/loop/daily-analysis")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "analysis" in data, "Response should contain 'analysis'"
        
        analysis = data["analysis"]
        expected_fields = ["date", "trades_analyzed", "stats_updated", "profile_updated"]
        for field in expected_fields:
            assert field in analysis, f"Analysis should contain '{field}'"
        
        print(f"PASS: Daily analysis completed - analyzed {analysis.get('trades_analyzed', 0)} trades")
        print(f"      Stats updated: {analysis.get('stats_updated', 0)}")
        print(f"      Edge decay warnings: {len(analysis.get('edge_decay_warnings', []))}")


class TestLearningSystemHealth:
    """Tests for GET /api/learning/loop/health endpoint"""
    
    def test_learning_health(self):
        """Test getting learning system health status"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "health" in data, "Response should contain 'health'"
        
        health = data["health"]
        expected_fields = ["overall_status", "can_trade", "services"]
        for field in expected_fields:
            assert field in health, f"Health should contain '{field}'"
        
        # Verify valid status values
        valid_statuses = ["healthy", "degraded", "unavailable", "unknown"]
        assert health["overall_status"] in valid_statuses, f"Status should be one of {valid_statuses}"
        
        print(f"PASS: System health: {health['overall_status']}, can_trade={health['can_trade']}")
        print(f"      Services: {list(health.get('services', {}).keys())[:5]}...")


class TestLearningModelsDataStructures:
    """Tests to verify data structures match learning_models.py dataclasses"""
    
    def test_trade_outcome_structure(self):
        """Verify trade outcome data structure matches TradeOutcome dataclass"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/outcomes", params={"limit": 1})
        assert response.status_code == 200
        
        data = response.json()
        if data.get("count", 0) > 0:
            outcome = data["outcomes"][0]
            # Verify core TradeOutcome fields
            core_fields = ["id", "symbol", "setup_type", "outcome", "pnl", 
                          "entry_price", "exit_price", "context", "execution"]
            for field in core_fields:
                assert field in outcome, f"TradeOutcome should contain '{field}'"
            
            # Verify nested context structure
            if outcome.get("context"):
                context = outcome["context"]
                context_fields = ["market_regime", "time_of_day", "vix_regime"]
                for field in context_fields:
                    assert field in context, f"Context should contain '{field}'"
            
            print(f"PASS: TradeOutcome structure validated")
        else:
            print("PASS: No outcomes to validate (empty collection expected for Phase 1)")
    
    def test_learning_stats_structure(self):
        """Verify learning stats data structure matches LearningStats dataclass"""
        response = requests.get(f"{BASE_URL}/api/learning/loop/stats")
        assert response.status_code == 200
        
        data = response.json()
        if data.get("count", 0) > 0:
            stat = data["stats"][0]
            # Verify core LearningStats fields
            core_fields = ["context_key", "setup_type", "total_trades", "wins", 
                          "losses", "win_rate", "profit_factor"]
            for field in core_fields:
                assert field in stat, f"LearningStats should contain '{field}'"
            
            print(f"PASS: LearningStats structure validated")
        else:
            print("PASS: No stats to validate (empty collection expected for Phase 1)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
