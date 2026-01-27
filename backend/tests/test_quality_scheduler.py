"""
Test suite for Quality Factor API and Scheduler API endpoints.
Tests the new features:
1. Quality Score API - GET /api/quality/score/{symbol}
2. Quality Enhancement API - POST /api/quality/enhance-opportunities
3. Scheduler Status API - GET /api/scheduler/status
4. Scheduler Schedule API - POST /api/scheduler/premarket/schedule
5. Scheduler Stop API - DELETE /api/scheduler/premarket/stop
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestQualityScoreAPI:
    """Tests for GET /api/quality/score/{symbol}"""
    
    def test_quality_score_aapl_returns_200(self):
        """Test quality score endpoint returns 200 for AAPL"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        assert response.status_code == 200
        
    def test_quality_score_returns_grade(self):
        """Test quality score returns grade (A+, A, B, C, etc.)"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        data = response.json()
        assert data.get("success") == True
        assert "data" in data
        assert "grade" in data["data"]
        assert data["data"]["grade"] in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
        
    def test_quality_score_returns_component_scores(self):
        """Test quality score returns 4-factor component scores"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        data = response.json()
        assert "data" in data
        assert "component_scores" in data["data"]
        components = data["data"]["component_scores"]
        # Check all 4 factors are present
        assert "accruals" in components
        assert "roe" in components
        assert "cfa" in components
        assert "da" in components
        
    def test_quality_score_returns_percentile_rank(self):
        """Test quality score returns percentile rank (0-100)"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        data = response.json()
        assert "data" in data
        assert "percentile_rank" in data["data"]
        percentile = data["data"]["percentile_rank"]
        assert isinstance(percentile, (int, float))
        assert 0 <= percentile <= 100
        
    def test_quality_score_returns_quality_signal(self):
        """Test quality score returns trading signal (LONG/SHORT/NEUTRAL)"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        data = response.json()
        assert "data" in data
        assert "quality_signal" in data["data"]
        assert data["data"]["quality_signal"] in ["LONG", "SHORT", "NEUTRAL"]
        
    def test_quality_score_returns_metrics(self):
        """Test quality score returns raw metrics"""
        response = requests.get(f"{BASE_URL}/api/quality/score/AAPL")
        data = response.json()
        assert "metrics" in data
        assert "symbol" in data["metrics"]
        assert data["metrics"]["symbol"] == "AAPL"
        
    def test_quality_score_msft(self):
        """Test quality score for MSFT"""
        response = requests.get(f"{BASE_URL}/api/quality/score/MSFT")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "data" in data
        assert "grade" in data["data"]
        
    def test_quality_score_nvda(self):
        """Test quality score for NVDA"""
        response = requests.get(f"{BASE_URL}/api/quality/score/NVDA")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True


class TestQualityEnhanceAPI:
    """Tests for POST /api/quality/enhance-opportunities"""
    
    def test_enhance_opportunities_returns_200(self):
        """Test enhance opportunities endpoint returns 200"""
        payload = {"opportunities": [{"symbol": "AAPL"}]}
        response = requests.post(
            f"{BASE_URL}/api/quality/enhance-opportunities",
            json=payload
        )
        assert response.status_code == 200
        
    def test_enhance_opportunities_adds_quality_data(self):
        """Test enhance opportunities adds quality data to each opportunity"""
        payload = {"opportunities": [{"symbol": "AAPL"}, {"symbol": "MSFT"}]}
        response = requests.post(
            f"{BASE_URL}/api/quality/enhance-opportunities",
            json=payload
        )
        data = response.json()
        assert data.get("success") == True
        assert "opportunities" in data
        assert len(data["opportunities"]) == 2
        
        # Check first opportunity has quality data
        opp = data["opportunities"][0]
        assert "quality" in opp
        assert "grade" in opp["quality"]
        assert "score" in opp["quality"]
        
    def test_enhance_opportunities_multiple_stocks(self):
        """Test enhance opportunities with multiple stocks"""
        payload = {"opportunities": [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
            {"symbol": "NVDA"}
        ]}
        response = requests.post(
            f"{BASE_URL}/api/quality/enhance-opportunities",
            json=payload
        )
        data = response.json()
        assert data.get("success") == True
        assert len(data["opportunities"]) == 3
        
        # Verify each has quality data
        for opp in data["opportunities"]:
            assert "quality" in opp
            assert "grade" in opp["quality"]


class TestSchedulerStatusAPI:
    """Tests for GET /api/scheduler/status"""
    
    def test_scheduler_status_returns_200(self):
        """Test scheduler status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        assert response.status_code == 200
        
    def test_scheduler_status_returns_running_state(self):
        """Test scheduler status returns running state"""
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        data = response.json()
        assert data.get("success") == True
        assert "scheduler" in data
        assert "running" in data["scheduler"]
        assert isinstance(data["scheduler"]["running"], bool)
        
    def test_scheduler_status_returns_tasks_list(self):
        """Test scheduler status returns tasks list"""
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        data = response.json()
        assert "scheduler" in data
        assert "tasks" in data["scheduler"]
        assert isinstance(data["scheduler"]["tasks"], list)
        
    def test_scheduler_status_returns_callback_registered(self):
        """Test scheduler status shows callback is registered"""
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        data = response.json()
        assert "scheduler" in data
        assert "premarket_callback_registered" in data["scheduler"]
        assert data["scheduler"]["premarket_callback_registered"] == True


class TestSchedulerScheduleAPI:
    """Tests for POST /api/scheduler/premarket/schedule"""
    
    def test_schedule_premarket_returns_200(self):
        """Test schedule premarket endpoint returns 200"""
        payload = {"hour": 6, "minute": 30}
        response = requests.post(
            f"{BASE_URL}/api/scheduler/premarket/schedule",
            json=payload
        )
        assert response.status_code == 200
        
    def test_schedule_premarket_returns_success_message(self):
        """Test schedule premarket returns success message"""
        payload = {"hour": 6, "minute": 30}
        response = requests.post(
            f"{BASE_URL}/api/scheduler/premarket/schedule",
            json=payload
        )
        data = response.json()
        assert data.get("success") == True
        assert "message" in data
        assert "6:30" in data["message"]
        
    def test_schedule_premarket_adds_task(self):
        """Test schedule premarket adds task to scheduler"""
        # First schedule
        payload = {"hour": 6, "minute": 30}
        requests.post(
            f"{BASE_URL}/api/scheduler/premarket/schedule",
            json=payload
        )
        
        # Check status
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        data = response.json()
        assert "premarket" in data["scheduler"]["tasks"]
        
    def test_schedule_premarket_custom_time(self):
        """Test schedule premarket with custom time"""
        payload = {"hour": 7, "minute": 0}
        response = requests.post(
            f"{BASE_URL}/api/scheduler/premarket/schedule",
            json=payload
        )
        data = response.json()
        assert data.get("success") == True
        assert "schedule" in data
        assert data["schedule"]["hour"] == 7
        assert data["schedule"]["minute"] == 0


class TestSchedulerStopAPI:
    """Tests for DELETE /api/scheduler/premarket/stop"""
    
    def test_stop_premarket_returns_200(self):
        """Test stop premarket endpoint returns 200"""
        response = requests.delete(f"{BASE_URL}/api/scheduler/premarket/stop")
        assert response.status_code == 200
        
    def test_stop_premarket_returns_success_message(self):
        """Test stop premarket returns success message"""
        response = requests.delete(f"{BASE_URL}/api/scheduler/premarket/stop")
        data = response.json()
        assert data.get("success") == True
        assert "message" in data
        
    def test_stop_premarket_removes_task(self):
        """Test stop premarket removes task from scheduler"""
        # First schedule
        requests.post(
            f"{BASE_URL}/api/scheduler/premarket/schedule",
            json={"hour": 6, "minute": 30}
        )
        
        # Then stop
        requests.delete(f"{BASE_URL}/api/scheduler/premarket/stop")
        
        # Check status
        response = requests.get(f"{BASE_URL}/api/scheduler/status")
        data = response.json()
        assert "premarket" not in data["scheduler"]["tasks"]


class TestQualityPanelDeleted:
    """Test that QualityPanel.jsx has been deleted"""
    
    def test_quality_panel_file_not_exists(self):
        """Verify QualityPanel.jsx file has been deleted"""
        import os
        quality_panel_path = "/app/frontend/src/components/QualityPanel.jsx"
        assert not os.path.exists(quality_panel_path), "QualityPanel.jsx should be deleted"


# Cleanup fixture to ensure scheduler is stopped after tests
@pytest.fixture(autouse=True, scope="module")
def cleanup_scheduler():
    """Cleanup scheduler after all tests"""
    yield
    # Stop scheduler after tests
    requests.delete(f"{BASE_URL}/api/scheduler/premarket/stop")
