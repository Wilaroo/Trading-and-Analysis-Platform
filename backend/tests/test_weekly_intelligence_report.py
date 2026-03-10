"""
Test suite for Weekly Intelligence Report - Phase 5 Enhancement

Tests all 8 endpoints at /api/journal/weekly-report/*:
1. POST /api/journal/weekly-report/generate - Generate a weekly report
2. GET /api/journal/weekly-report/current - Get current week's report
3. GET /api/journal/weekly-report/stats - Service statistics
4. GET /api/journal/weekly-report/week/{year}/{week_number} - Get by year/week
5. GET /api/journal/weekly-report/{report_id} - Get specific report
6. GET /api/journal/weekly-report - Get recent reports (archive)
7. PUT /api/journal/weekly-report/{report_id}/reflection - Update personal reflection
8. POST /api/journal/weekly-report/{report_id}/complete - Mark report complete

Report structure verification:
- performance (PerformanceSnapshot)
- top_contexts, struggling_contexts (List[ContextInsight])
- edge_alerts (List[EdgeAlert])
- calibration_suggestions (List[CalibrationSuggestion])
- confirmation_insights (List[ConfirmationInsight])
- playbook_focus (List[PlaybookFocus])
- reflection (PersonalReflection)
"""

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestWeeklyReportGeneration:
    """Test weekly report generation endpoint"""
    
    def test_generate_weekly_report_current_week(self):
        """POST /api/journal/weekly-report/generate - Generate report for current week"""
        response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True, f"Expected success=True, got {data}"
        assert "report" in data, "Missing 'report' key in response"
        
        report = data["report"]
        self._verify_report_structure(report)
        
        # Verify report ID format: wir_YYYY_wWW
        assert report["id"].startswith("wir_"), f"Invalid report ID format: {report['id']}"
        assert report["week_number"] > 0 and report["week_number"] <= 53
        assert report["year"] >= 2024
        
        print(f"Generated report: {report['id']} for week {report['week_number']}/{report['year']}")
        print(f"  Week: {report['week_start']} to {report['week_end']}")
        
    def test_generate_weekly_report_with_force(self):
        """POST /api/journal/weekly-report/generate - Force regenerate report"""
        response = requests.post(
            f"{BASE_URL}/api/journal/weekly-report/generate",
            params={"force": True}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        print(f"Forced regeneration: {data['report']['id']}")
    
    def test_generate_weekly_report_specific_week(self):
        """POST /api/journal/weekly-report/generate - Generate for specific week"""
        # Generate for Jan 6, 2025 (Monday of a past week)
        response = requests.post(
            f"{BASE_URL}/api/journal/weekly-report/generate",
            params={"week_start": "2025-01-06"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        
        report = data["report"]
        assert report["week_start"] == "2025-01-06"
        assert report["year"] == 2025
        
        print(f"Generated report for specific week: {report['id']}")
        
    def _verify_report_structure(self, report):
        """Helper to verify complete report structure"""
        # Core identifiers
        required_fields = ["id", "week_number", "year", "week_start", "week_end"]
        for field in required_fields:
            assert field in report, f"Missing required field: {field}"
        
        # Performance snapshot
        assert "performance" in report, "Missing 'performance' section"
        perf = report["performance"]
        perf_fields = ["total_trades", "wins", "losses", "scratches", "win_rate", 
                       "total_pnl", "total_r", "avg_r_per_trade", "profit_factor",
                       "best_day", "best_day_pnl", "worst_day", "worst_day_pnl",
                       "avg_win", "avg_loss", "largest_win", "largest_loss",
                       "win_rate_change", "pnl_change"]
        for field in perf_fields:
            assert field in perf, f"Missing performance field: {field}"
        
        # Context insights sections
        assert "top_contexts" in report, "Missing 'top_contexts' section"
        assert isinstance(report["top_contexts"], list), "top_contexts should be a list"
        
        assert "struggling_contexts" in report, "Missing 'struggling_contexts' section"
        assert isinstance(report["struggling_contexts"], list), "struggling_contexts should be a list"
        
        # Edge alerts
        assert "edge_alerts" in report, "Missing 'edge_alerts' section"
        assert isinstance(report["edge_alerts"], list), "edge_alerts should be a list"
        
        # Calibration suggestions
        assert "calibration_suggestions" in report, "Missing 'calibration_suggestions' section"
        assert isinstance(report["calibration_suggestions"], list), "calibration_suggestions should be a list"
        
        # Confirmation insights
        assert "confirmation_insights" in report, "Missing 'confirmation_insights' section"
        assert isinstance(report["confirmation_insights"], list), "confirmation_insights should be a list"
        
        # Playbook focus
        assert "playbook_focus" in report, "Missing 'playbook_focus' section"
        assert isinstance(report["playbook_focus"], list), "playbook_focus should be a list"
        
        # Personal reflection
        assert "reflection" in report, "Missing 'reflection' section"
        reflection = report["reflection"]
        reflection_fields = ["what_went_well", "what_to_improve", "key_lessons",
                           "goals_for_next_week", "mood_rating", "confidence_rating", "notes"]
        for field in reflection_fields:
            assert field in reflection, f"Missing reflection field: {field}"
        
        # Metadata
        assert "generated_at" in report, "Missing 'generated_at'"
        assert "last_updated" in report, "Missing 'last_updated'"
        assert "is_complete" in report, "Missing 'is_complete'"
        
        print("  Report structure verified: All sections present")


class TestGetCurrentReport:
    """Test getting current week's report"""
    
    def test_get_current_weekly_report(self):
        """GET /api/journal/weekly-report/current - Get current week's report"""
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/current")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        # Verify current week
        now = datetime.now(timezone.utc)
        current_week = now.isocalendar()[1]
        current_year = now.year
        
        assert report["week_number"] == current_week, f"Expected week {current_week}, got {report['week_number']}"
        assert report["year"] == current_year, f"Expected year {current_year}, got {report['year']}"
        
        print(f"Current week report: {report['id']}")


class TestServiceStatistics:
    """Test service statistics endpoint"""
    
    def test_get_weekly_report_stats(self):
        """GET /api/journal/weekly-report/stats - Service statistics"""
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "db_connected" in data, "Missing 'db_connected' in stats"
        assert "reports_generated" in data, "Missing 'reports_generated' in stats"
        
        assert data["db_connected"] is True, "Database should be connected"
        assert isinstance(data["reports_generated"], int), "reports_generated should be an integer"
        assert data["reports_generated"] >= 0, "reports_generated should be non-negative"
        
        print(f"Service stats: db_connected={data['db_connected']}, reports_generated={data['reports_generated']}")


class TestGetReportByWeek:
    """Test getting report by year and week number"""
    
    def test_get_report_by_week_existing(self):
        """GET /api/journal/weekly-report/week/{year}/{week_number} - Existing report"""
        # First generate current week report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        gen_data = gen_response.json()
        year = gen_data["report"]["year"]
        week = gen_data["report"]["week_number"]
        
        # Now get by week
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/week/{year}/{week}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        report = data["report"]
        assert report["year"] == year
        assert report["week_number"] == week
        
        print(f"Retrieved report by week: {year}/w{week}")
    
    def test_get_report_by_week_nonexistent(self):
        """GET /api/journal/weekly-report/week/{year}/{week_number} - Non-existent report"""
        # Use a far future week that won't exist
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/week/2050/1")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        print(f"Non-existent week returns 404: {data['detail']}")


class TestGetReportById:
    """Test getting report by ID"""
    
    def test_get_report_by_id_existing(self):
        """GET /api/journal/weekly-report/{report_id} - Existing report"""
        # First generate report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        report_id = gen_response.json()["report"]["id"]
        
        # Get by ID
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/{report_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        assert data["report"]["id"] == report_id
        
        print(f"Retrieved report by ID: {report_id}")
    
    def test_get_report_by_id_nonexistent(self):
        """GET /api/journal/weekly-report/{report_id} - Non-existent report"""
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report/wir_2050_w99")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print("Non-existent report ID returns 404")


class TestGetRecentReports:
    """Test archive/list of recent reports"""
    
    def test_get_recent_reports(self):
        """GET /api/journal/weekly-report - Get recent reports"""
        response = requests.get(f"{BASE_URL}/api/journal/weekly-report")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "reports" in data
        assert "count" in data
        
        assert isinstance(data["reports"], list), "reports should be a list"
        assert data["count"] == len(data["reports"]), "count should match reports length"
        
        print(f"Recent reports: {data['count']} reports returned")
        
        # Verify reports are sorted by week descending
        if len(data["reports"]) >= 2:
            for i in range(len(data["reports"]) - 1):
                curr = data["reports"][i]
                next_r = data["reports"][i + 1]
                curr_week = curr["year"] * 100 + curr["week_number"]
                next_week = next_r["year"] * 100 + next_r["week_number"]
                assert curr_week >= next_week, "Reports should be sorted by week descending"
    
    def test_get_recent_reports_with_limit(self):
        """GET /api/journal/weekly-report - With custom limit"""
        response = requests.get(
            f"{BASE_URL}/api/journal/weekly-report",
            params={"limit": 5}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert len(data["reports"]) <= 5
        
        print(f"Recent reports (limit=5): {data['count']} returned")


class TestUpdateReflection:
    """Test updating personal reflection section"""
    
    def test_update_reflection_full(self):
        """PUT /api/journal/weekly-report/{report_id}/reflection - Full update"""
        # First generate report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        report_id = gen_response.json()["report"]["id"]
        
        # Update reflection
        reflection_data = {
            "what_went_well": "Followed my trading rules consistently",
            "what_to_improve": "Need to be more patient with entries",
            "key_lessons": "Smaller position sizes in volatile markets",
            "goals_for_next_week": "Focus on A+ setups only",
            "mood_rating": 4,
            "confidence_rating": 3,
            "notes": "Good week overall despite market volatility"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/journal/weekly-report/{report_id}/reflection",
            json=reflection_data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "report" in data
        
        # Verify reflection was updated
        updated_reflection = data["report"]["reflection"]
        assert updated_reflection["what_went_well"] == reflection_data["what_went_well"]
        assert updated_reflection["what_to_improve"] == reflection_data["what_to_improve"]
        assert updated_reflection["key_lessons"] == reflection_data["key_lessons"]
        assert updated_reflection["goals_for_next_week"] == reflection_data["goals_for_next_week"]
        assert updated_reflection["mood_rating"] == reflection_data["mood_rating"]
        assert updated_reflection["confidence_rating"] == reflection_data["confidence_rating"]
        assert updated_reflection["notes"] == reflection_data["notes"]
        
        print(f"Updated reflection for report: {report_id}")
        print(f"  Mood: {updated_reflection['mood_rating']}/5, Confidence: {updated_reflection['confidence_rating']}/5")
    
    def test_update_reflection_partial(self):
        """PUT /api/journal/weekly-report/{report_id}/reflection - Partial update"""
        # First generate report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        report_id = gen_response.json()["report"]["id"]
        
        # Partial update
        partial_data = {
            "what_went_well": "Great discipline today",
            "mood_rating": 5
        }
        
        response = requests.put(
            f"{BASE_URL}/api/journal/weekly-report/{report_id}/reflection",
            json=partial_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["report"]["reflection"]["what_went_well"] == partial_data["what_went_well"]
        assert data["report"]["reflection"]["mood_rating"] == partial_data["mood_rating"]
        
        print("Partial reflection update successful")
    
    def test_update_reflection_invalid_ratings(self):
        """PUT /api/journal/weekly-report/{report_id}/reflection - With boundary ratings"""
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        report_id = gen_response.json()["report"]["id"]
        
        # Test boundary values (1 and 5)
        for rating in [1, 5]:
            response = requests.put(
                f"{BASE_URL}/api/journal/weekly-report/{report_id}/reflection",
                json={"mood_rating": rating, "confidence_rating": rating}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["report"]["reflection"]["mood_rating"] == rating
            assert data["report"]["reflection"]["confidence_rating"] == rating
        
        print("Boundary rating values (1 and 5) accepted")
    
    def test_update_reflection_nonexistent_report(self):
        """PUT /api/journal/weekly-report/{report_id}/reflection - Non-existent report"""
        response = requests.put(
            f"{BASE_URL}/api/journal/weekly-report/wir_2050_w99/reflection",
            json={"what_went_well": "Test"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print("Non-existent report reflection update returns 404")


class TestMarkComplete:
    """Test marking report as complete"""
    
    def test_mark_report_complete(self):
        """POST /api/journal/weekly-report/{report_id}/complete - Mark complete"""
        # First generate report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert gen_response.status_code == 200
        
        report_id = gen_response.json()["report"]["id"]
        
        # Verify it starts as not complete
        get_response = requests.get(f"{BASE_URL}/api/journal/weekly-report/{report_id}")
        assert get_response.json()["report"]["is_complete"] is False
        
        # Mark complete
        response = requests.post(f"{BASE_URL}/api/journal/weekly-report/{report_id}/complete")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["success"] is True
        assert "message" in data
        assert "complete" in data["message"].lower()
        
        # Verify it's now complete
        get_response = requests.get(f"{BASE_URL}/api/journal/weekly-report/{report_id}")
        assert get_response.json()["report"]["is_complete"] is True
        
        print(f"Marked report complete: {report_id}")
    
    def test_mark_complete_nonexistent_report(self):
        """POST /api/journal/weekly-report/{report_id}/complete - Non-existent report"""
        response = requests.post(f"{BASE_URL}/api/journal/weekly-report/wir_2050_w99/complete")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print("Non-existent report complete returns 404")


class TestReportSectionDetails:
    """Test detailed section structures when data exists"""
    
    def test_verify_performance_snapshot_structure(self):
        """Verify PerformanceSnapshot fields and types"""
        response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert response.status_code == 200
        
        perf = response.json()["report"]["performance"]
        
        # Verify integer fields
        for field in ["total_trades", "wins", "losses", "scratches"]:
            assert isinstance(perf[field], int), f"{field} should be int"
        
        # Verify float fields
        float_fields = ["win_rate", "total_pnl", "total_r", "avg_r_per_trade", 
                        "profit_factor", "best_day_pnl", "worst_day_pnl",
                        "avg_win", "avg_loss", "largest_win", "largest_loss",
                        "win_rate_change", "pnl_change"]
        for field in float_fields:
            assert isinstance(perf[field], (int, float)), f"{field} should be numeric"
        
        # Verify string fields
        assert isinstance(perf["best_day"], str)
        assert isinstance(perf["worst_day"], str)
        
        print("PerformanceSnapshot structure verified")
    
    def test_verify_reflection_structure(self):
        """Verify PersonalReflection fields and types"""
        response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        assert response.status_code == 200
        
        reflection = response.json()["report"]["reflection"]
        
        # String fields
        for field in ["what_went_well", "what_to_improve", "key_lessons", 
                      "goals_for_next_week", "notes"]:
            assert isinstance(reflection[field], str), f"{field} should be string"
        
        # Integer rating fields (1-5)
        assert isinstance(reflection["mood_rating"], int)
        assert isinstance(reflection["confidence_rating"], int)
        assert 1 <= reflection["mood_rating"] <= 5 or reflection["mood_rating"] == 3  # default
        assert 1 <= reflection["confidence_rating"] <= 5 or reflection["confidence_rating"] == 3  # default
        
        print("PersonalReflection structure verified")


class TestDataPersistence:
    """Test data persistence after operations"""
    
    def test_reflection_persists_after_update(self):
        """Verify reflection data persists after update"""
        # Generate report
        gen_response = requests.post(f"{BASE_URL}/api/journal/weekly-report/generate")
        report_id = gen_response.json()["report"]["id"]
        
        # Update reflection
        test_data = {
            "what_went_well": "TEST_PERSISTENCE_CHECK",
            "mood_rating": 5
        }
        requests.put(
            f"{BASE_URL}/api/journal/weekly-report/{report_id}/reflection",
            json=test_data
        )
        
        # Get report again and verify persistence
        get_response = requests.get(f"{BASE_URL}/api/journal/weekly-report/{report_id}")
        assert get_response.status_code == 200
        
        fetched = get_response.json()["report"]["reflection"]
        assert fetched["what_went_well"] == test_data["what_went_well"]
        assert fetched["mood_rating"] == test_data["mood_rating"]
        
        print("Reflection data persists correctly")
    
    def test_complete_status_persists(self):
        """Verify complete status persists"""
        # Generate report
        gen_response = requests.post(
            f"{BASE_URL}/api/journal/weekly-report/generate",
            params={"week_start": "2025-01-13"}  # Use specific week to avoid conflicts
        )
        report_id = gen_response.json()["report"]["id"]
        
        # Mark complete
        requests.post(f"{BASE_URL}/api/journal/weekly-report/{report_id}/complete")
        
        # Get and verify
        get_response = requests.get(f"{BASE_URL}/api/journal/weekly-report/{report_id}")
        assert get_response.json()["report"]["is_complete"] is True
        
        print("Complete status persists correctly")


# Fixture for API session
@pytest.fixture(scope="module")
def api_session():
    """Create a session for API calls"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
