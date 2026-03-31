"""
Test AI-Enhanced Performance Dashboard APIs
Phase 4: AI metrics per strategy - win rate, gate decisions, edge trends
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ai-trading-bot-82.preview.emergentagent.com').rstrip('/')


class TestAIStrategyInsights:
    """Tests for GET /api/trades/ai/strategy-insights endpoint"""
    
    def test_strategy_insights_returns_success(self):
        """Verify endpoint returns success response"""
        response = requests.get(f"{BASE_URL}/api/trades/ai/strategy-insights", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "insights" in data
        print(f"SUCCESS: strategy-insights returned {len(data['insights'])} strategies")
    
    def test_strategy_insights_structure(self):
        """Verify insights contain expected fields per strategy"""
        response = requests.get(f"{BASE_URL}/api/trades/ai/strategy-insights", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        insights = data.get("insights", {})
        if insights:
            # Check first strategy has required fields
            first_strategy = list(insights.keys())[0]
            strategy_data = insights[first_strategy]
            
            required_fields = ["total_trades", "wins", "losses", "win_rate", "total_pnl", "avg_pnl", "gate_stats", "edge_trend"]
            for field in required_fields:
                assert field in strategy_data, f"Missing field: {field}"
            
            # Verify gate_stats structure
            gate_stats = strategy_data.get("gate_stats", {})
            if gate_stats:
                assert "total" in gate_stats, "gate_stats missing 'total'"
            
            print(f"SUCCESS: Strategy {first_strategy} has all required fields")
            print(f"  - Win rate: {strategy_data['win_rate']}%")
            print(f"  - Gate stats: {gate_stats}")
        else:
            print("INFO: No strategy insights data available (empty database)")


class TestAILearningStats:
    """Tests for GET /api/trades/ai/learning-stats endpoint"""
    
    def test_learning_stats_returns_success(self):
        """Verify endpoint returns success response"""
        response = requests.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "stats" in data
        print(f"SUCCESS: learning-stats returned stats")
    
    def test_learning_stats_structure(self):
        """Verify stats contain expected fields"""
        response = requests.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        stats = data.get("stats", {})
        assert "journal_outcomes" in stats, "Missing journal_outcomes count"
        
        if stats.get("journal_outcomes", 0) > 0:
            assert "outcomes" in stats, "Missing outcomes breakdown"
            outcomes = stats["outcomes"]
            print(f"SUCCESS: {stats['journal_outcomes']} journal outcomes")
            print(f"  - Outcomes: {outcomes}")
            
            # Check confidence_gate_accuracy if present
            if "confidence_gate_accuracy" in stats:
                print(f"  - Gate accuracy: {stats['confidence_gate_accuracy']}")
        else:
            print("INFO: No journal outcomes data available")


class TestPerformanceMatrix:
    """Tests for GET /api/trades/performance/matrix endpoint"""
    
    def test_matrix_returns_success(self):
        """Verify endpoint returns matrix data"""
        response = requests.get(f"{BASE_URL}/api/trades/performance/matrix", timeout=30)
        assert response.status_code == 200
        data = response.json()
        assert "matrix" in data
        assert "strategies" in data
        assert "contexts" in data
        print(f"SUCCESS: matrix returned {len(data['strategies'])} strategies, {len(data['contexts'])} contexts")
    
    def test_matrix_ai_metrics_enrichment(self):
        """Verify matrix contains AI metrics enrichment"""
        response = requests.get(f"{BASE_URL}/api/trades/performance/matrix", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        # Check for ai_strategy_metrics field
        assert "ai_strategy_metrics" in data, "Missing ai_strategy_metrics field"
        
        ai_metrics = data.get("ai_strategy_metrics", {})
        if ai_metrics:
            first_strategy = list(ai_metrics.keys())[0]
            strategy_metrics = ai_metrics[first_strategy]
            print(f"SUCCESS: AI metrics found for {len(ai_metrics)} strategies")
            print(f"  - {first_strategy}: {strategy_metrics}")
        else:
            print("INFO: No AI strategy metrics available")
    
    def test_matrix_top_combinations(self):
        """Verify top_combinations includes AI metrics"""
        response = requests.get(f"{BASE_URL}/api/trades/performance/matrix", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        top_combos = data.get("top_combinations", [])
        if top_combos:
            combo = top_combos[0]
            print(f"SUCCESS: Top combination: {combo['strategy']} in {combo['context']}")
            print(f"  - Win rate: {combo['win_rate']}%")
            if "ai_win_rate" in combo:
                print(f"  - AI win rate: {combo['ai_win_rate']}%")
            if "gate_go" in combo:
                print(f"  - Gate GO: {combo['gate_go']}, REDUCE: {combo.get('gate_reduce', 0)}")
        else:
            print("INFO: No top combinations available (need 3+ trades per combo)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
