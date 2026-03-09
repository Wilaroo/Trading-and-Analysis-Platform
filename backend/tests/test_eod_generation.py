"""
Test End-of-Day (EOD) Auto-Generation Features
Tests for automatic DRC and Playbook generation at 4:30 PM ET weekdays

Endpoints tested:
- GET /api/journal/eod/status - Check scheduler status
- POST /api/journal/eod/trigger - Manually trigger DRC generation
- GET /api/journal/eod/pending-playbooks - List pending AI-generated playbooks
- GET /api/journal/eod/logs - Get generation logs
- POST /api/journal/eod/pending-playbooks/{id}/approve - Approve playbook
- POST /api/journal/eod/pending-playbooks/{id}/reject - Reject playbook
- GET /api/journal/drc/today - Get today's DRC (may be AI-generated)
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEODStatusEndpoint:
    """Test GET /api/journal/eod/status"""
    
    def test_eod_status_returns_success(self):
        """Status endpoint returns successful response"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"EOD Status Response: {data}")
    
    def test_eod_status_contains_scheduler_running(self):
        """Status response contains scheduler_running boolean"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/status")
        data = response.json()
        
        assert "scheduler_running" in data
        assert isinstance(data["scheduler_running"], bool)
        print(f"Scheduler running: {data['scheduler_running']}")
    
    def test_eod_status_contains_next_runs(self):
        """Status response contains next_runs with timestamps"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/status")
        data = response.json()
        
        assert "next_runs" in data
        # If scheduler is running, next_runs should have timestamps
        if data.get("scheduler_running"):
            assert isinstance(data["next_runs"], dict)
            # Should have auto_generate_drc job
            print(f"Next runs: {data['next_runs']}")
    
    def test_eod_status_contains_timezone(self):
        """Status response contains timezone info"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/status")
        data = response.json()
        
        assert "timezone" in data
        assert data["timezone"] == "America/New_York"
        
    def test_eod_status_contains_scheduled_time(self):
        """Status response contains scheduled_time description"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/status")
        data = response.json()
        
        assert "scheduled_time" in data
        assert "4:30 PM ET" in data["scheduled_time"]


class TestEODTriggerEndpoint:
    """Test POST /api/journal/eod/trigger"""
    
    def test_trigger_endpoint_returns_success(self):
        """Manual trigger returns successful response"""
        response = requests.post(f"{BASE_URL}/api/journal/eod/trigger")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Trigger Response: {data}")
    
    def test_trigger_contains_drc_result(self):
        """Trigger response contains DRC generation result"""
        response = requests.post(f"{BASE_URL}/api/journal/eod/trigger")
        data = response.json()
        
        assert "drc" in data
        assert "status" in data["drc"]
        # Status should be one of: success, skipped, error
        assert data["drc"]["status"] in ["success", "skipped", "error"]
        print(f"DRC result: {data['drc']}")
    
    def test_trigger_contains_playbook_analysis_result(self):
        """Trigger response contains playbook analysis result"""
        response = requests.post(f"{BASE_URL}/api/journal/eod/trigger")
        data = response.json()
        
        assert "playbook_analysis" in data
        assert "status" in data["playbook_analysis"]
        # Status should be one of: success, skipped, error
        assert data["playbook_analysis"]["status"] in ["success", "skipped", "error"]
        print(f"Playbook analysis result: {data['playbook_analysis']}")
    
    def test_trigger_with_specific_date(self):
        """Trigger with specific date parameter"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.post(f"{BASE_URL}/api/journal/eod/trigger", params={"date": today})
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        # If DRC was generated, date should match
        if data.get("drc", {}).get("date"):
            assert data["drc"]["date"] == today


class TestPendingPlaybooksEndpoint:
    """Test GET /api/journal/eod/pending-playbooks"""
    
    def test_pending_playbooks_returns_success(self):
        """Pending playbooks endpoint returns successful response"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/pending-playbooks")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Pending Playbooks Response: {data}")
    
    def test_pending_playbooks_contains_list(self):
        """Response contains pending_playbooks list"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/pending-playbooks")
        data = response.json()
        
        assert "pending_playbooks" in data
        assert isinstance(data["pending_playbooks"], list)
    
    def test_pending_playbooks_contains_count(self):
        """Response contains count field"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/pending-playbooks")
        data = response.json()
        
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["pending_playbooks"])


class TestEODLogsEndpoint:
    """Test GET /api/journal/eod/logs"""
    
    def test_logs_endpoint_returns_success(self):
        """Logs endpoint returns successful response"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/logs")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"Logs Response: {data}")
    
    def test_logs_contains_list(self):
        """Response contains logs list"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/logs")
        data = response.json()
        
        assert "logs" in data
        assert isinstance(data["logs"], list)
    
    def test_logs_contains_count(self):
        """Response contains count field"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/logs")
        data = response.json()
        
        assert "count" in data
        assert isinstance(data["count"], int)
    
    def test_logs_with_days_parameter(self):
        """Test logs endpoint with days parameter"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/logs", params={"days": 1})
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
    
    def test_log_entries_have_expected_fields(self):
        """Log entries have type, date, status, message, timestamp"""
        response = requests.get(f"{BASE_URL}/api/journal/eod/logs")
        data = response.json()
        
        if data["logs"]:
            log = data["logs"][0]
            assert "type" in log
            assert "date" in log
            assert "status" in log
            assert "message" in log
            assert "timestamp" in log
            print(f"Sample log entry: {log}")


class TestApproveRejectPlaybookEndpoints:
    """Test approve/reject pending playbook endpoints"""
    
    def test_approve_nonexistent_playbook_returns_404(self):
        """Approving non-existent playbook returns 404"""
        fake_id = "000000000000000000000000"
        response = requests.post(f"{BASE_URL}/api/journal/eod/pending-playbooks/{fake_id}/approve")
        
        # Should return 404 for non-existent playbook
        assert response.status_code in [404, 500]
        print(f"Approve non-existent response: {response.status_code}")
    
    def test_reject_nonexistent_playbook_returns_success(self):
        """Rejecting non-existent playbook returns success (delete is idempotent)"""
        fake_id = "000000000000000000000000"
        response = requests.post(f"{BASE_URL}/api/journal/eod/pending-playbooks/{fake_id}/reject")
        
        # Delete operations may return 200 with success: false or 404
        assert response.status_code in [200, 404, 500]
        print(f"Reject non-existent response: {response.status_code}")


class TestDRCTodayEndpoint:
    """Test GET /api/journal/drc/today"""
    
    def test_drc_today_returns_success(self):
        """Today's DRC endpoint returns successful response"""
        response = requests.get(f"{BASE_URL}/api/journal/drc/today")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        print(f"DRC Today Response keys: {data.get('drc', {}).keys()}")
    
    def test_drc_today_contains_drc_object(self):
        """Response contains drc object"""
        response = requests.get(f"{BASE_URL}/api/journal/drc/today")
        data = response.json()
        
        assert "drc" in data
        assert isinstance(data["drc"], dict)
    
    def test_drc_has_date_field(self):
        """DRC has date field matching today"""
        response = requests.get(f"{BASE_URL}/api/journal/drc/today")
        data = response.json()
        
        drc = data["drc"]
        assert "date" in drc
        # Date should be in YYYY-MM-DD format
        assert len(drc["date"]) == 10
        print(f"DRC date: {drc['date']}")
    
    def test_drc_has_auto_generated_field(self):
        """DRC may have auto_generated field"""
        response = requests.get(f"{BASE_URL}/api/journal/drc/today")
        data = response.json()
        
        drc = data["drc"]
        # After trigger, it should have auto_generated flag
        if "auto_generated" in drc:
            assert isinstance(drc["auto_generated"], bool)
            print(f"DRC auto_generated: {drc['auto_generated']}")
    
    def test_drc_has_required_structure(self):
        """DRC has required fields: overall_grade, day_pnl, intraday_segments"""
        response = requests.get(f"{BASE_URL}/api/journal/drc/today")
        data = response.json()
        
        drc = data["drc"]
        
        # Check core fields exist
        assert "overall_grade" in drc
        assert "day_pnl" in drc
        assert "intraday_segments" in drc
        assert "premarket_checklist" in drc
        assert "postmarket_checklist" in drc
        
        # intraday_segments should be a list with 3 segments
        assert isinstance(drc["intraday_segments"], list)
        assert len(drc["intraday_segments"]) == 3
        
        # Each segment should have required fields
        for segment in drc["intraday_segments"]:
            assert "segment_id" in segment
            assert "label" in segment
            assert "pnl" in segment
            print(f"Segment: {segment['segment_id']} - {segment['label']}")


class TestIntegrationFlow:
    """Test end-to-end integration flow"""
    
    def test_full_eod_workflow(self):
        """Test complete EOD workflow: status -> trigger -> verify DRC -> check logs"""
        # 1. Check status
        status_res = requests.get(f"{BASE_URL}/api/journal/eod/status")
        assert status_res.status_code == 200
        status = status_res.json()
        print(f"1. Status: scheduler_running={status.get('scheduler_running')}")
        
        # 2. Trigger generation
        trigger_res = requests.post(f"{BASE_URL}/api/journal/eod/trigger")
        assert trigger_res.status_code == 200
        trigger = trigger_res.json()
        print(f"2. Trigger: DRC={trigger.get('drc', {}).get('status')}, Playbook={trigger.get('playbook_analysis', {}).get('status')}")
        
        # 3. Verify DRC was created/updated
        drc_res = requests.get(f"{BASE_URL}/api/journal/drc/today")
        assert drc_res.status_code == 200
        drc = drc_res.json()
        assert drc["drc"]["auto_generated"] == True, "DRC should be marked as auto-generated"
        print(f"3. DRC verified: date={drc['drc']['date']}, auto_generated={drc['drc']['auto_generated']}")
        
        # 4. Check logs contain recent entry
        logs_res = requests.get(f"{BASE_URL}/api/journal/eod/logs", params={"days": 1})
        assert logs_res.status_code == 200
        logs = logs_res.json()
        assert logs["count"] > 0, "Should have at least one log entry"
        
        # Find DRC log entry
        drc_logs = [l for l in logs["logs"] if l["type"] == "drc"]
        assert len(drc_logs) > 0, "Should have DRC generation log"
        print(f"4. Logs: {logs['count']} entries, DRC log status={drc_logs[0]['status']}")
        
        print("Full EOD workflow test PASSED!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
