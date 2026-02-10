"""
Market Intelligence API Tests

Tests for the Market Intelligence & Strategy Playbook feature:
- GET /api/market-intel/schedule - Returns 5 report types with schedule times
- GET /api/market-intel/current - Returns current report
- GET /api/market-intel/reports - Returns today's generated reports
- POST /api/market-intel/generate/{type} - Generates a specific report type
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestMarketIntelSchedule:
    """Tests for /api/market-intel/schedule endpoint"""
    
    def test_schedule_returns_200(self):
        """Schedule endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        assert response.status_code == 200
        print("PASS: Schedule endpoint returns 200")
    
    def test_schedule_returns_5_report_types(self):
        """Schedule should have exactly 5 report types"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        data = response.json()
        
        assert "schedule" in data
        assert len(data["schedule"]) == 5
        print(f"PASS: Schedule has 5 report types")
    
    def test_schedule_has_correct_report_types(self):
        """Schedule should contain premarket, early_market, midday, power_hour, post_market"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        data = response.json()
        
        expected_types = ["premarket", "early_market", "midday", "power_hour", "post_market"]
        actual_types = [item["type"] for item in data["schedule"]]
        
        assert set(actual_types) == set(expected_types)
        print(f"PASS: All 5 report types present: {actual_types}")
    
    def test_schedule_has_correct_times(self):
        """Schedule should have correct scheduled times"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        data = response.json()
        
        expected_times = {
            "premarket": "8:30",
            "early_market": "10:30",
            "midday": "14:00",
            "power_hour": "14:30",
            "post_market": "16:30"
        }
        
        for item in data["schedule"]:
            assert item["type"] in expected_times
            assert item["scheduled_time"] == expected_times[item["type"]], \
                f"Expected {expected_times[item['type']]} for {item['type']}, got {item['scheduled_time']}"
        
        print("PASS: All report types have correct scheduled times")
    
    def test_schedule_items_have_required_fields(self):
        """Each schedule item should have required fields"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule")
        data = response.json()
        
        required_fields = ["type", "label", "icon", "scheduled_time", "is_past", "is_current", "generated"]
        
        for item in data["schedule"]:
            for field in required_fields:
                assert field in item, f"Missing field '{field}' in schedule item"
        
        print("PASS: All schedule items have required fields")


class TestMarketIntelCurrent:
    """Tests for /api/market-intel/current endpoint"""
    
    def test_current_returns_200(self):
        """Current endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        assert response.status_code == 200
        print("PASS: Current endpoint returns 200")
    
    def test_current_has_report_flag(self):
        """Current response should indicate if report exists"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        data = response.json()
        
        assert "has_report" in data
        print(f"PASS: has_report flag present, value: {data['has_report']}")
    
    def test_current_returns_report_if_available(self):
        """If has_report is true, report object should exist"""
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        data = response.json()
        
        if data["has_report"]:
            assert "report" in data
            assert data["report"] is not None
            assert "type" in data["report"]
            assert "content" in data["report"]
            assert "generated_at_et" in data["report"]
            print(f"PASS: Report exists with type '{data['report']['type']}'")
        else:
            print("INFO: No report available at current time")


class TestMarketIntelReports:
    """Tests for /api/market-intel/reports endpoint"""
    
    def test_reports_returns_200(self):
        """Reports endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        assert response.status_code == 200
        print("PASS: Reports endpoint returns 200")
    
    def test_reports_has_count(self):
        """Reports response should have count field"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        data = response.json()
        
        assert "count" in data
        assert isinstance(data["count"], int)
        print(f"PASS: Reports count: {data['count']}")
    
    def test_reports_list_structure(self):
        """Reports list should be an array"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        data = response.json()
        
        assert "reports" in data
        assert isinstance(data["reports"], list)
        print(f"PASS: Reports is a list with {len(data['reports'])} items")
    
    def test_report_objects_have_required_fields(self):
        """Each report should have required fields"""
        response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        data = response.json()
        
        if data["count"] > 0:
            required_fields = ["type", "label", "icon", "content", "generated_at", "generated_at_et", "date"]
            
            for report in data["reports"]:
                for field in required_fields:
                    assert field in report, f"Missing field '{field}' in report"
            
            print("PASS: All reports have required fields")
        else:
            print("INFO: No reports to validate")


class TestMarketIntelGenerate:
    """Tests for /api/market-intel/generate/{type} endpoint"""
    
    def test_generate_invalid_type_returns_400(self):
        """Generating invalid report type should return 400"""
        response = requests.post(f"{BASE_URL}/api/market-intel/generate/invalid_type")
        assert response.status_code == 400
        
        data = response.json()
        assert "detail" in data
        assert "Invalid report type" in data["detail"]
        print("PASS: Invalid report type returns 400 with error detail")
    
    def test_generate_premarket_returns_success(self):
        """Generating premarket report should succeed (may be cached)"""
        response = requests.post(f"{BASE_URL}/api/market-intel/generate/premarket", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "report" in data
        assert data["report"]["type"] == "premarket"
        
        cached = data.get("cached", False)
        print(f"PASS: Premarket report generated (cached={cached})")
    
    def test_generate_early_market_returns_success(self):
        """Generating early_market report should succeed"""
        response = requests.post(f"{BASE_URL}/api/market-intel/generate/early_market", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["report"]["type"] == "early_market"
        print(f"PASS: Early market report generated")
    
    def test_generate_report_has_ai_content(self):
        """Generated report should have substantial AI content"""
        response = requests.post(f"{BASE_URL}/api/market-intel/generate/premarket", timeout=60)
        data = response.json()
        
        content = data["report"]["content"]
        # AI-generated content should be substantial (> 500 chars)
        assert len(content) > 500, f"Content too short: {len(content)} chars"
        
        # Content should have structured sections
        has_sections = any(marker in content for marker in ["**", "1.", "RECAP", "STRATEGY", "GAME PLAN"])
        assert has_sections, "Content lacks structured sections"
        
        print(f"PASS: Report has substantial AI content ({len(content)} chars)")
    
    def test_generate_valid_types_list(self):
        """All valid types should be accepted"""
        valid_types = ["premarket", "early_market", "midday", "power_hour", "post_market"]
        
        for report_type in valid_types:
            response = requests.post(f"{BASE_URL}/api/market-intel/generate/{report_type}", timeout=90)
            assert response.status_code == 200, f"Failed for type: {report_type}"
            assert response.json()["success"] is True
        
        print(f"PASS: All 5 valid report types accepted")


class TestMarketIntelIntegration:
    """Integration tests for Market Intelligence flow"""
    
    def test_generate_then_verify_in_reports(self):
        """Generated report should appear in reports list"""
        # Generate a report
        gen_response = requests.post(f"{BASE_URL}/api/market-intel/generate/premarket", timeout=60)
        assert gen_response.status_code == 200
        generated_report = gen_response.json()["report"]
        
        # Verify it appears in today's reports
        reports_response = requests.get(f"{BASE_URL}/api/market-intel/reports")
        reports = reports_response.json()["reports"]
        
        premarket_reports = [r for r in reports if r["type"] == "premarket"]
        assert len(premarket_reports) > 0, "Generated premarket report not found in reports list"
        
        print("PASS: Generated report appears in reports list")
    
    def test_current_returns_most_recent_applicable(self):
        """Current endpoint should return most recent applicable report"""
        # First ensure we have a report
        requests.post(f"{BASE_URL}/api/market-intel/generate/premarket", timeout=60)
        
        # Get current report
        response = requests.get(f"{BASE_URL}/api/market-intel/current")
        data = response.json()
        
        if data["has_report"]:
            assert data["report"]["type"] in ["premarket", "early_market", "midday", "power_hour", "post_market"]
            print(f"PASS: Current returns {data['report']['type']} report")
        else:
            print("INFO: No applicable report for current time")


# Pytest fixtures
@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session
