"""
Test suite for Phase 5 Medium Learning - Daily Analysis APIs

Tests all 16 endpoints at /api/medium-learning/*:
1. Service status and health
2. Calibration service (config, analyze, history)
3. Context performance (update, report, all)
4. Confirmation validation (validate, all)
5. Playbook performance (update, report, all)
6. Edge decay (analyze, all, decaying)
7. Daily analysis (combined EOD run)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestMediumLearningStatus:
    """Test service status endpoint"""
    
    def test_medium_learning_status(self):
        """GET /api/medium-learning/status - Service health check"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["success"] is True, f"Expected success=True, got {data}"
        assert "services" in data, "Missing 'services' key"
        
        services = data["services"]
        # Verify all 5 services are present
        assert "calibration" in services, "Missing calibration service"
        assert "context_performance" in services, "Missing context_performance service"
        assert "confirmation_validator" in services, "Missing confirmation_validator service"
        assert "playbook_performance" in services, "Missing playbook_performance service"
        assert "edge_decay" in services, "Missing edge_decay service"
        
        # Each service should have db_connected flag
        for service_name, service_stats in services.items():
            assert "db_connected" in service_stats, f"Service {service_name} missing db_connected"
            assert service_stats["db_connected"] is True, f"Service {service_name} not connected to DB"
            
        print(f"All 5 Medium Learning services are healthy: {list(services.keys())}")


class TestCalibrationService:
    """Test calibration endpoints"""
    
    def test_get_calibration_config(self):
        """GET /api/medium-learning/calibration/config - Get calibration configuration"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/calibration/config")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "config" in data
        
        config = data["config"]
        # Verify TQS thresholds
        assert "tqs_strong_buy_threshold" in config
        assert "tqs_buy_threshold" in config
        assert "tqs_hold_threshold" in config
        assert "tqs_avoid_threshold" in config
        
        # Verify regime adjustments
        assert "regime_adjustments" in config
        
        # Verify default values
        assert config["tqs_strong_buy_threshold"] == 80
        assert config["tqs_buy_threshold"] == 65
        assert config["tqs_hold_threshold"] == 50
        assert config["tqs_avoid_threshold"] == 35
        
        print(f"Calibration config: TQS thresholds={config['tqs_strong_buy_threshold']}/{config['tqs_buy_threshold']}/{config['tqs_hold_threshold']}/{config['tqs_avoid_threshold']}")
    
    def test_analyze_and_recommend(self):
        """POST /api/medium-learning/calibration/analyze - Analyze and recommend threshold changes"""
        response = requests.post(
            f"{BASE_URL}/api/medium-learning/calibration/analyze",
            params={"lookback_days": 30}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "recommendations" in data
        assert "count" in data
        
        # Count should match list length
        assert data["count"] == len(data["recommendations"])
        
        # With no trade data, we expect 0 recommendations
        print(f"Calibration analysis: {data['count']} recommendations generated")
        
        # If recommendations exist, verify structure
        for rec in data["recommendations"]:
            assert "parameter" in rec
            assert "current_value" in rec
            assert "recommended_value" in rec
            assert "reason" in rec
            assert "confidence" in rec
    
    def test_get_calibration_history(self):
        """GET /api/medium-learning/calibration/history - Get calibration history"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/calibration/history",
            params={"limit": 50, "applied_only": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "history" in data
        assert "count" in data
        assert isinstance(data["history"], list)
        
        print(f"Calibration history: {data['count']} records")
    
    def test_get_calibration_history_applied_only(self):
        """GET /api/medium-learning/calibration/history - Applied only filter"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/calibration/history",
            params={"limit": 50, "applied_only": True}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        print(f"Applied calibrations: {data['count']} records")


class TestContextPerformanceService:
    """Test context performance endpoints"""
    
    def test_update_context_performance(self):
        """POST /api/medium-learning/context-performance/update - Update context performance"""
        response = requests.post(f"{BASE_URL}/api/medium-learning/context-performance/update")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "contexts_updated" in data
        
        print(f"Context performance update: {data['contexts_updated']} contexts updated")
    
    def test_generate_performance_report(self):
        """GET /api/medium-learning/context-performance/report - Generate performance report"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/context-performance/report",
            params={"report_type": "weekly"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert "report_date" in report
        assert "report_type" in report
        assert "total_trades" in report
        assert "overall_win_rate" in report
        assert "best_contexts" in report
        assert "worst_contexts" in report
        assert "heat_map" in report
        
        print(f"Performance report: type={report['report_type']}, trades={report['total_trades']}, win_rate={report['overall_win_rate']}")
    
    def test_generate_performance_report_daily(self):
        """GET /api/medium-learning/context-performance/report - Daily report"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/context-performance/report",
            params={"report_type": "daily"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["report"]["report_type"] == "daily"
    
    def test_generate_performance_report_monthly(self):
        """GET /api/medium-learning/context-performance/report - Monthly report"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/context-performance/report",
            params={"report_type": "monthly"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["report"]["report_type"] == "monthly"
    
    def test_get_all_context_performance(self):
        """GET /api/medium-learning/context-performance/all - Get all context performances"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/context-performance/all")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "contexts" in data
        assert "count" in data
        assert isinstance(data["contexts"], list)
        
        print(f"All context performances: {data['count']} contexts tracked")
    
    def test_lookup_context_performance(self):
        """GET /api/medium-learning/context-performance/lookup - Lookup specific context"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/context-performance/lookup",
            params={"setup_type": "bull_flag", "market_regime": "uptrend", "time_of_day": "morning"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # May or may not have performance data
        print(f"Context lookup: performance={'found' if data.get('performance') else 'not found'}")


class TestConfirmationValidatorService:
    """Test confirmation validation endpoints"""
    
    def test_validate_confirmations(self):
        """POST /api/medium-learning/confirmation/validate - Validate confirmations"""
        response = requests.post(
            f"{BASE_URL}/api/medium-learning/confirmation/validate",
            params={"lookback_days": 30}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert "report_date" in report
        assert "total_trades_analyzed" in report
        assert "confirmation_stats" in report
        assert "most_effective" in report
        assert "least_effective" in report
        assert "best_combinations" in report
        assert "recommendations" in report
        
        print(f"Confirmation validation: {report['total_trades_analyzed']} trades analyzed, {len(report['confirmation_stats'])} confirmation types")
    
    def test_get_all_confirmation_stats(self):
        """GET /api/medium-learning/confirmation/all - Get all confirmation stats"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/confirmation/all")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert "confirmation_types" in data
        
        # Verify expected confirmation types are present
        expected_types = ["volume", "rvol", "tape", "l2_support", "vwap_respect", "trend_alignment", "sector_momentum", "news_catalyst"]
        for ct in expected_types:
            assert ct in data["confirmation_types"], f"Missing confirmation type: {ct}"
        
        print(f"Confirmation stats: {len(data['stats'])} stats, types={data['confirmation_types']}")
    
    def test_get_confirmation_stats_specific_type(self):
        """GET /api/medium-learning/confirmation/stats/{confirmation_type} - Get specific confirmation stats"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/confirmation/stats/volume")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # Stats may be null if not yet calculated
        if data.get("stats"):
            stats = data["stats"]
            assert "confirmation_type" in stats
            assert "win_rate_with" in stats
            assert "win_rate_without" in stats
            assert "effectiveness_score" in stats
            print(f"Volume confirmation stats: effectiveness_score={stats['effectiveness_score']}")
        else:
            print("Volume confirmation stats: not yet calculated")


class TestPlaybookPerformanceService:
    """Test playbook performance endpoints"""
    
    def test_update_playbook_performance(self):
        """POST /api/medium-learning/playbook/update - Update playbook performance"""
        response = requests.post(
            f"{BASE_URL}/api/medium-learning/playbook/update",
            params={"lookback_days": 90}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "playbooks_updated" in data
        assert "total_trades" in data
        
        print(f"Playbook update: {data['playbooks_updated']} playbooks updated from {data['total_trades']} trades")
    
    def test_generate_playbook_report(self):
        """GET /api/medium-learning/playbook/report - Generate playbook report"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/playbook/report",
            params={"lookback_days": 90}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert "report_date" in report
        assert "total_playbooks" in report
        assert "total_trades" in report
        assert "top_performing_playbooks" in report
        assert "underperforming_playbooks" in report
        assert "biggest_execution_gaps" in report
        assert "playbooks_to_focus" in report
        assert "playbooks_to_review" in report
        assert "playbooks_to_avoid" in report
        assert "all_playbooks" in report
        
        print(f"Playbook report: {report['total_playbooks']} playbooks, {report['total_trades']} trades")
    
    def test_get_all_playbook_performance(self):
        """GET /api/medium-learning/playbook - Get all playbook performances"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/playbook")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "playbooks" in data
        assert "count" in data
        assert isinstance(data["playbooks"], list)
        
        print(f"All playbook performances: {data['count']} playbooks tracked")
    
    def test_get_specific_playbook_performance(self):
        """GET /api/medium-learning/playbook/{setup_type} - Get specific playbook performance"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/playbook/bull_flag")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # Performance may be null if no data
        if data.get("performance"):
            perf = data["performance"]
            assert "playbook_name" in perf
            assert "setup_type" in perf
            assert "win_rate" in perf
            print(f"Bull flag playbook: win_rate={perf['win_rate']}")
        else:
            print("Bull flag playbook: no performance data yet")


class TestEdgeDecayService:
    """Test edge decay endpoints"""
    
    def test_analyze_edge_decay(self):
        """POST /api/medium-learning/edge-decay/analyze - Analyze edge decay"""
        response = requests.post(f"{BASE_URL}/api/medium-learning/edge-decay/analyze")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert "report_date" in report
        assert "total_edges_tracked" in report
        assert "edges_decaying" in report
        assert "edges_improving" in report
        assert "edges_stable" in report
        assert "critical_alerts" in report
        assert "warnings" in report
        assert "edges_to_pause" in report
        assert "edges_to_monitor" in report
        assert "edges_performing_well" in report
        assert "all_edges" in report
        
        print(f"Edge decay: {report['total_edges_tracked']} edges tracked, {report['edges_decaying']} decaying, {report['edges_stable']} stable")
    
    def test_get_all_edge_metrics(self):
        """GET /api/medium-learning/edge-decay - Get all edge metrics"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/edge-decay")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "edges" in data
        assert "count" in data
        
        print(f"All edge metrics: {data['count']} edges tracked")
    
    def test_get_decaying_edges(self):
        """GET /api/medium-learning/edge-decay/decaying/list - Get decaying edges"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/edge-decay/decaying/list")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "decaying_edges" in data
        assert "count" in data
        
        print(f"Decaying edges: {data['count']} edges showing decay")
    
    def test_get_specific_edge_metrics(self):
        """GET /api/medium-learning/edge-decay/{edge_name} - Get specific edge metrics"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/edge-decay/bull_flag")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        # Metrics may be null if no data
        if data.get("metrics"):
            metrics = data["metrics"]
            assert "edge_id" in metrics
            assert "name" in metrics
            assert "decay_score" in metrics
            assert "is_decaying" in metrics
            print(f"Bull flag edge: decay_score={metrics['decay_score']}, is_decaying={metrics['is_decaying']}")
        else:
            print("Bull flag edge: no metrics yet")


class TestDailyAnalysis:
    """Test combined daily analysis endpoint"""
    
    def test_run_daily_analysis(self):
        """POST /api/medium-learning/daily-analysis - Run complete EOD analysis"""
        response = requests.post(f"{BASE_URL}/api/medium-learning/daily-analysis")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "timestamp" in data
        
        # Verify all 5 analysis components ran
        assert "calibration" in data
        assert "context_performance" in data
        assert "confirmations" in data
        assert "playbooks" in data
        assert "edge_decay" in data
        
        # Calibration results
        assert "recommendations_count" in data["calibration"]
        
        # Context performance results
        assert "contexts_updated" in data["context_performance"]
        
        # Confirmation results
        assert "trades_analyzed" in data["confirmations"]
        assert "most_effective" in data["confirmations"]
        assert "least_effective" in data["confirmations"]
        
        # Playbook results
        assert "playbooks_updated" in data["playbooks"]
        assert "total_trades" in data["playbooks"]
        
        # Edge decay results
        assert "total_edges" in data["edge_decay"]
        assert "decaying" in data["edge_decay"]
        
        print(f"Daily analysis complete:")
        print(f"  - Calibration: {data['calibration']['recommendations_count']} recommendations")
        print(f"  - Context: {data['context_performance']['contexts_updated']} contexts updated")
        print(f"  - Confirmations: {data['confirmations']['trades_analyzed']} trades analyzed")
        print(f"  - Playbooks: {data['playbooks']['playbooks_updated']} playbooks updated")
        print(f"  - Edge Decay: {data['edge_decay']['total_edges']} edges tracked, {data['edge_decay']['decaying']} decaying")


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_calibration_analyze_different_lookback(self):
        """Test calibration with different lookback periods"""
        for days in [7, 14, 60]:
            response = requests.post(
                f"{BASE_URL}/api/medium-learning/calibration/analyze",
                params={"lookback_days": days}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            print(f"Calibration analysis ({days} days lookback): {data['count']} recommendations")
    
    def test_performance_report_with_custom_lookback(self):
        """Test performance report with custom lookback"""
        response = requests.get(
            f"{BASE_URL}/api/medium-learning/context-performance/report",
            params={"report_type": "weekly", "lookback_days": 14}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_confirmation_validation_short_lookback(self):
        """Test confirmation validation with short lookback"""
        response = requests.post(
            f"{BASE_URL}/api/medium-learning/confirmation/validate",
            params={"lookback_days": 7}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_nonexistent_confirmation_type(self):
        """Test getting stats for non-existent confirmation type"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/confirmation/stats/nonexistent_type")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return None/null for stats
        assert data.get("stats") is None or data.get("message")
    
    def test_nonexistent_playbook(self):
        """Test getting performance for non-existent playbook"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/playbook/nonexistent_playbook")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return None/null or message
    
    def test_nonexistent_edge(self):
        """Test getting metrics for non-existent edge"""
        response = requests.get(f"{BASE_URL}/api/medium-learning/edge-decay/nonexistent_edge")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return None/null or message


# Fixture for session-based testing
@pytest.fixture(scope="module")
def api_session():
    """Create a session for API calls"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
