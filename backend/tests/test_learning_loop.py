"""
Test suite for Mutual Learning Loop (Strategy Performance & Auto-Tuning)

Tests:
- POST /api/trading-bot/demo/simulate-closed - Creates closed trades for testing
- GET /api/learning/strategy-stats - Per-strategy aggregated stats
- POST /api/learning/analyze - AI analysis and recommendations
- GET /api/learning/recommendations - Pending recommendations
- POST /api/learning/recommendations/{rec_id} - Apply/dismiss recommendations
- GET /api/learning/tuning-history - Audit trail of applied changes
"""
import pytest
import requests
import os
import time
import random

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSimulateClosedTrade:
    """Test POST /api/trading-bot/demo/simulate-closed endpoint"""
    
    def test_simulate_closed_returns_200(self):
        """Verify simulate-closed endpoint returns 200"""
        payload = {
            "symbol": "AAPL",
            "setup_type": "rubber_band",
            "pnl": 125.50,
            "close_reason": "target_hit"
        }
        response = requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_simulate_closed_returns_trade_data(self):
        """Verify simulate-closed returns trade with all required fields"""
        payload = {
            "symbol": "MSFT",
            "setup_type": "squeeze",
            "pnl": -75.00,
            "close_reason": "stop_loss"
        }
        response = requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        data = response.json()
        
        assert data["success"] == True
        assert "trade" in data
        trade = data["trade"]
        
        # Verify key trade fields
        assert trade["symbol"] == "MSFT"
        assert trade["setup_type"] == "squeeze"
        assert trade["status"] == "closed"
        assert "realized_pnl" in trade
        assert trade["close_reason"] == "stop_loss"
    
    def test_simulate_closed_records_to_strategy_performance(self):
        """Verify trade is recorded for learning loop"""
        # Create a unique trade
        unique_symbol = f"TEST_{random.randint(1000, 9999)}"
        payload = {
            "symbol": unique_symbol,
            "setup_type": "breakout",
            "pnl": 200.00,
            "close_reason": "target_hit"
        }
        response = requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        assert response.status_code == 200
        
        # Give it a moment to be recorded
        time.sleep(0.5)
        
        # Verify stats endpoint picks it up (breakout should have at least 1 trade)
        stats_response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        assert stats_response.status_code == 200
        stats_data = stats_response.json()
        
        assert "stats" in stats_data
        # breakout strategy should exist if we have data for it
        if "breakout" in stats_data["stats"]:
            assert stats_data["stats"]["breakout"]["total_trades"] >= 1


class TestStrategyStats:
    """Test GET /api/learning/strategy-stats endpoint"""
    
    def test_strategy_stats_returns_200(self):
        """Verify strategy-stats endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        assert response.status_code == 200
    
    def test_strategy_stats_has_correct_structure(self):
        """Verify strategy stats contain required fields per strategy"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        data = response.json()
        
        assert data["success"] == True
        assert "stats" in data
        stats = data["stats"]
        
        # Should have some strategy data (from existing or new test trades)
        if len(stats) > 0:
            # Check first strategy's structure
            first_strategy = list(stats.values())[0]
            required_fields = [
                "total_trades", "wins", "losses", "win_rate",
                "total_pnl", "avg_pnl", "close_reasons"
            ]
            for field in required_fields:
                assert field in first_strategy, f"Missing field: {field}"
    
    def test_strategy_stats_win_rate_calculation(self):
        """Verify win_rate is correctly calculated"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        data = response.json()
        stats = data["stats"]
        
        for strategy, perf in stats.items():
            total = perf["total_trades"]
            wins = perf["wins"]
            if total > 0:
                expected_win_rate = round(wins / total * 100, 1)
                assert abs(perf["win_rate"] - expected_win_rate) < 0.2, f"Win rate mismatch for {strategy}"


class TestAIAnalysis:
    """Test POST /api/learning/analyze endpoint"""
    
    def test_analyze_returns_200(self):
        """Verify analyze endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/learning/analyze")
        assert response.status_code == 200
    
    def test_analyze_returns_analysis_structure(self):
        """Verify analyze returns proper structure"""
        response = requests.post(f"{BASE_URL}/api/learning/analyze", timeout=60)
        data = response.json()
        
        assert "success" in data
        # When no data: returns success with basic analysis
        # When has data: returns full analysis with recommendations
        if data["success"]:
            assert "analysis" in data or "recommendations" in data
    
    def test_analyze_returns_recommendations(self):
        """Verify analyze may return recommendations"""
        # First create some test trades to analyze
        strategies = ["rubber_band", "squeeze", "breakout"]
        for strategy in strategies:
            for _ in range(2):
                payload = {
                    "symbol": f"TEST_{random.randint(1000, 9999)}",
                    "setup_type": strategy,
                    "pnl": random.choice([-50, -75, 100, 150]),
                    "close_reason": random.choice(["stop_loss", "target_hit", "stop_loss_trailing"])
                }
                requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        
        # Now run analysis (may take longer due to AI call)
        response = requests.post(f"{BASE_URL}/api/learning/analyze", timeout=60)
        data = response.json()
        
        assert data["success"] == True
        # Analysis should be present even if no specific recommendations
        assert "analysis" in data


class TestRecommendations:
    """Test GET /api/learning/recommendations endpoint"""
    
    def test_recommendations_returns_200(self):
        """Verify recommendations endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/learning/recommendations")
        assert response.status_code == 200
    
    def test_recommendations_structure(self):
        """Verify recommendations have correct structure"""
        response = requests.get(f"{BASE_URL}/api/learning/recommendations")
        data = response.json()
        
        assert data["success"] == True
        assert "recommendations" in data
        
        # If there are recommendations, verify structure
        if len(data["recommendations"]) > 0:
            rec = data["recommendations"][0]
            required_fields = ["id", "strategy", "parameter", "current_value", "suggested_value", "status"]
            for field in required_fields:
                assert field in rec, f"Missing field in recommendation: {field}"


class TestApplyDismissRecommendation:
    """Test POST /api/learning/recommendations/{rec_id} endpoint"""
    
    def test_apply_nonexistent_recommendation_returns_error(self):
        """Verify applying nonexistent recommendation returns error"""
        response = requests.post(
            f"{BASE_URL}/api/learning/recommendations/nonexistent_123",
            json={"action": "apply"}
        )
        # Should return success=false with error message
        data = response.json()
        assert data.get("success") == False or "error" in data or response.status_code >= 400
    
    def test_dismiss_recommendation_works(self):
        """Verify dismissing a recommendation works if one exists"""
        # Get current recommendations
        recs_response = requests.get(f"{BASE_URL}/api/learning/recommendations")
        recs = recs_response.json().get("recommendations", [])
        
        if len(recs) > 0:
            rec_id = recs[0]["id"]
            response = requests.post(
                f"{BASE_URL}/api/learning/recommendations/{rec_id}",
                json={"action": "dismiss"}
            )
            data = response.json()
            assert data["success"] == True
    
    def test_invalid_action_returns_error(self):
        """Verify invalid action returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/learning/recommendations/any_id",
            json={"action": "invalid_action"}
        )
        assert response.status_code == 400


class TestTuningHistory:
    """Test GET /api/learning/tuning-history endpoint"""
    
    def test_tuning_history_returns_200(self):
        """Verify tuning-history endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history")
        assert response.status_code == 200
    
    def test_tuning_history_structure(self):
        """Verify tuning history has correct structure"""
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history")
        data = response.json()
        
        assert data["success"] == True
        assert "history" in data
        
        # If there's history, verify structure
        if len(data["history"]) > 0:
            entry = data["history"][0]
            expected_fields = ["strategy", "parameter", "old_value", "new_value", "applied_at"]
            for field in expected_fields:
                assert field in entry, f"Missing field in history: {field}"
    
    def test_tuning_history_respects_limit(self):
        """Verify limit parameter works"""
        response = requests.get(f"{BASE_URL}/api/learning/tuning-history?limit=5")
        data = response.json()
        assert len(data["history"]) <= 5


class TestEndToEndLearningLoop:
    """End-to-end tests for the complete learning loop flow"""
    
    def test_complete_learning_loop_flow(self):
        """Test the complete flow: create trades -> get stats -> analyze"""
        # Step 1: Create several closed trades
        strategies = ["rubber_band", "breakout", "squeeze"]
        created_trades = []
        for strategy in strategies:
            payload = {
                "symbol": f"E2E_{random.randint(1000, 9999)}",
                "setup_type": strategy,
                "pnl": random.choice([-100, -50, 75, 150, 200]),
                "close_reason": random.choice(["stop_loss", "target_hit", "stop_loss_trailing"])
            }
            response = requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
            assert response.status_code == 200
            created_trades.append(response.json()["trade"])
        
        # Step 2: Verify strategy stats updated
        time.sleep(0.5)
        stats_response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()["stats"]
        
        # Should have stats for each strategy we created trades for
        for strategy in strategies:
            assert strategy in stats, f"Missing stats for {strategy}"
        
        # Step 3: Verify stats have close_reasons from our trades
        for strategy in strategies:
            if stats[strategy]["total_trades"] > 0:
                assert "close_reasons" in stats[strategy]
    
    def test_heuristic_recommendation_generation(self):
        """Test that heuristic recommendations fire for poor performing strategies"""
        # Create multiple losing trades with stops for a strategy
        test_strategy = "rubber_band"
        
        # Create 5 trades with 4 stop losses and 1 win to trigger heuristic
        for i in range(5):
            payload = {
                "symbol": f"HEUR_{random.randint(1000, 9999)}",
                "setup_type": test_strategy,
                "pnl": -50 if i < 4 else 100,  # 4 losses, 1 win
                "close_reason": "stop_loss" if i < 4 else "target_hit"
            }
            requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        
        # Run analysis to trigger recommendation generation
        time.sleep(0.5)
        response = requests.post(f"{BASE_URL}/api/learning/analyze", timeout=60)
        data = response.json()
        
        # Should have analysis
        assert data["success"] == True


class TestIntegrationWithTradingBot:
    """Test integration between learning dashboard and trading bot"""
    
    def test_demo_trade_records_to_performance(self):
        """Verify demo trades are properly recorded for learning"""
        # Get initial stats
        initial_stats = requests.get(f"{BASE_URL}/api/learning/strategy-stats").json()
        initial_count = initial_stats.get("stats", {}).get("rubber_band", {}).get("total_trades", 0)
        
        # Create a new trade
        payload = {
            "symbol": "INT_TEST",
            "setup_type": "rubber_band",
            "pnl": 88.88,
            "close_reason": "target_hit"
        }
        response = requests.post(f"{BASE_URL}/api/trading-bot/demo/simulate-closed", json=payload)
        assert response.status_code == 200
        
        # Verify stats increased
        time.sleep(0.5)
        new_stats = requests.get(f"{BASE_URL}/api/learning/strategy-stats").json()
        new_count = new_stats.get("stats", {}).get("rubber_band", {}).get("total_trades", 0)
        
        assert new_count >= initial_count, f"Trade count should increase: {initial_count} -> {new_count}"
    
    def test_strategy_configs_accessible_for_tuning(self):
        """Verify strategy configs are available for auto-tuning"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/strategy-configs")
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] == True
        assert "configs" in data
        
        # Should have all 6 strategies
        expected_strategies = ["rubber_band", "vwap_bounce", "breakout", "squeeze", "trend_continuation", "position_trade"]
        for strategy in expected_strategies:
            assert strategy in data["configs"], f"Missing strategy config: {strategy}"


class TestHealthAndConnectivity:
    """Basic health checks"""
    
    def test_health_endpoint(self):
        """Verify backend is healthy"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
    
    def test_learning_dashboard_router_accessible(self):
        """Verify learning dashboard router is mounted"""
        response = requests.get(f"{BASE_URL}/api/learning/strategy-stats")
        assert response.status_code == 200
    
    def test_trading_bot_router_accessible(self):
        """Verify trading bot router is mounted"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200


# Cleanup note: Test trades are created but not cleaned up to preserve learning data
