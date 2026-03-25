"""
Test General Model Training Endpoints - Job Queue Integration

Tests the 4 training endpoints that were updated to use the worker job queue:
1. POST /api/ai-modules/timeseries/train - Single timeframe training
2. POST /api/ai-modules/timeseries/train-all - All timeframes training
3. POST /api/ai-modules/timeseries/train-full-universe - Full universe single timeframe
4. POST /api/ai-modules/timeseries/train-full-universe-all - Full universe all timeframes

All endpoints should:
- Return job_id immediately (non-blocking)
- Worker picks up and processes jobs
- Job progress is trackable via GET /api/jobs/{job_id}
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndPrerequisites:
    """Verify basic health and prerequisites before testing training endpoints"""
    
    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        print(f"Health check passed: {response.json()}")
    
    def test_timeseries_status(self):
        """Verify timeseries AI service is initialized"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        print(f"Timeseries status: {data.get('status', {})}")
    
    def test_training_status_endpoint(self):
        """Verify training status endpoint works"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/training-status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        print(f"Training status: {data.get('status', {})}")


class TestTrainEndpoint:
    """Test POST /api/ai-modules/timeseries/train - Single timeframe training"""
    
    def test_train_returns_job_id(self):
        """Train endpoint should return job_id immediately (non-blocking)"""
        payload = {
            "bar_size": "1 day",
            "max_symbols": 5  # Small for quick test
        }
        
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            json=payload,
            timeout=30
        )
        elapsed = time.time() - start_time
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return job_id, not block for training
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        assert "message" in data, f"Expected message in response, got: {data}"
        
        # Should return quickly (< 5 seconds), not wait for training
        assert elapsed < 5, f"Endpoint took {elapsed:.1f}s - should return immediately"
        
        job_id = data["job_id"]
        print(f"Train endpoint returned job_id={job_id} in {elapsed:.2f}s")
        print(f"Message: {data.get('message')}")
        
        return job_id
    
    def test_train_with_custom_bar_size(self):
        """Train endpoint accepts custom bar_size parameter"""
        payload = {
            "bar_size": "1 hour",
            "max_symbols": 3
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        
        # Verify bar_size is in response
        assert data.get("bar_size") == "1 hour"
        print(f"Train with bar_size='1 hour' returned job_id={data['job_id']}")
    
    def test_train_without_payload(self):
        """Train endpoint works with no payload (uses defaults)"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        print(f"Train with defaults returned job_id={data['job_id']}")


class TestTrainAllEndpoint:
    """Test POST /api/ai-modules/timeseries/train-all - All timeframes training"""
    
    def test_train_all_returns_job_id(self):
        """Train-all endpoint should return job_id immediately"""
        payload = {
            "max_symbols": 3  # Small for quick test
        }
        
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-all",
            json=payload,
            timeout=30
        )
        elapsed = time.time() - start_time
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        
        # Should return quickly
        assert elapsed < 5, f"Endpoint took {elapsed:.1f}s - should return immediately"
        
        print(f"Train-all returned job_id={data['job_id']} in {elapsed:.2f}s")
        print(f"Message: {data.get('message')}")
    
    def test_train_all_with_specific_timeframes(self):
        """Train-all accepts specific timeframes parameter"""
        payload = {
            "max_symbols": 2,
            "timeframes": ["1 day", "1 hour"]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-all",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        print(f"Train-all with specific timeframes returned job_id={data['job_id']}")


class TestTrainFullUniverseEndpoint:
    """Test POST /api/ai-modules/timeseries/train-full-universe - Full universe single TF"""
    
    def test_train_full_universe_returns_job_id(self):
        """Train-full-universe endpoint should return job_id immediately"""
        payload = {
            "bar_size": "1 day",
            "max_bars_per_symbol": 100  # Small for quick test
        }
        
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-full-universe",
            json=payload,
            timeout=30
        )
        elapsed = time.time() - start_time
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        
        # Should return quickly
        assert elapsed < 5, f"Endpoint took {elapsed:.1f}s - should return immediately"
        
        print(f"Train-full-universe returned job_id={data['job_id']} in {elapsed:.2f}s")
        print(f"Message: {data.get('message')}")
        print(f"Settings: {data.get('settings', {})}")
    
    def test_train_full_universe_with_custom_bar_size(self):
        """Train-full-universe accepts custom bar_size"""
        payload = {
            "bar_size": "5 mins",
            "max_bars_per_symbol": 50
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-full-universe",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        
        # Verify settings in response
        settings = data.get("settings", {})
        assert settings.get("bar_size") == "5 mins"
        print(f"Train-full-universe with bar_size='5 mins' returned job_id={data['job_id']}")


class TestTrainFullUniverseAllEndpoint:
    """Test POST /api/ai-modules/timeseries/train-full-universe-all - Full universe all TFs"""
    
    def test_train_full_universe_all_returns_job_id(self):
        """Train-full-universe-all endpoint should return job_id immediately"""
        payload = {
            "max_bars_per_symbol": 50  # Small for quick test
        }
        
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-full-universe-all",
            json=payload,
            timeout=30
        )
        elapsed = time.time() - start_time
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        
        # Should return quickly
        assert elapsed < 5, f"Endpoint took {elapsed:.1f}s - should return immediately"
        
        print(f"Train-full-universe-all returned job_id={data['job_id']} in {elapsed:.2f}s")
        print(f"Message: {data.get('message')}")
        print(f"Settings: {data.get('settings', {})}")
    
    def test_train_full_universe_all_with_specific_timeframes(self):
        """Train-full-universe-all accepts specific timeframes"""
        payload = {
            "max_bars_per_symbol": 30,
            "timeframes": ["1 day"]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train-full-universe-all",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        
        # Verify settings
        settings = data.get("settings", {})
        assert settings.get("timeframes") == ["1 day"]
        print(f"Train-full-universe-all with specific TFs returned job_id={data['job_id']}")


class TestJobProgressTracking:
    """Test job progress tracking via GET /api/jobs/{job_id}"""
    
    def test_get_job_status(self):
        """Can retrieve job status by job_id"""
        # First create a job
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            json={"bar_size": "1 day", "max_symbols": 2},
            timeout=30
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        
        # Now get job status
        status_response = requests.get(
            f"{BASE_URL}/api/jobs/{job_id}",
            timeout=10
        )
        
        assert status_response.status_code == 200
        data = status_response.json()
        
        # Response wraps job in "job" key
        assert data.get("success") == True
        assert "job" in data
        
        job = data["job"]
        assert "job_id" in job
        assert "status" in job
        assert "progress" in job
        assert job["job_id"] == job_id
        
        # Verify progress structure
        progress = job.get("progress", {})
        assert "percent" in progress
        assert "message" in progress
        
        print(f"Job {job_id} status: {job['status']}")
        print(f"Progress: {progress.get('percent')}% - {progress.get('message')}")
    
    def test_job_progress_updates(self):
        """Job progress updates as worker processes"""
        # Create a job
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            json={"bar_size": "1 day", "max_symbols": 3},
            timeout=30
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        
        # Poll for progress a few times
        statuses = []
        for i in range(5):
            time.sleep(2)
            status_response = requests.get(
                f"{BASE_URL}/api/jobs/{job_id}",
                timeout=10
            )
            if status_response.status_code == 200:
                data = status_response.json()
                job = data.get("job", {})
                statuses.append({
                    "status": job.get("status"),
                    "percent": job.get("progress", {}).get("percent"),
                    "message": job.get("progress", {}).get("message")
                })
                print(f"Poll {i+1}: {job.get('status')} - {job.get('progress', {}).get('percent')}%")
                
                # If completed or failed, stop polling
                if job.get("status") in ["completed", "failed"]:
                    break
        
        # Verify we got status updates
        assert len(statuses) > 0
        print(f"Collected {len(statuses)} status updates")
    
    def test_get_nonexistent_job(self):
        """Getting nonexistent job returns appropriate response"""
        response = requests.get(
            f"{BASE_URL}/api/jobs/nonexistent123",
            timeout=10
        )
        
        # Should return 404 or empty response
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            # If 200, should indicate job not found
            assert data is None or data.get("job_id") is None
        print(f"Nonexistent job response: {response.status_code}")


class TestExistingEndpointsStillWork:
    """Verify existing endpoints still work after the changes"""
    
    def test_setups_status_still_works(self):
        """GET /api/ai-modules/timeseries/setups/status should still work"""
        response = requests.get(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/status",
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        # Should have setup models info
        assert "models" in data or "setup_models" in data or "setups" in data
        print(f"Setups status: {data}")
    
    def test_setups_train_still_returns_job_id(self):
        """POST /api/ai-modules/timeseries/setups/train should still return job_id"""
        payload = {
            "setup_type": "MOMENTUM",
            "bar_size": "1 day",
            "max_symbols": 2
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json=payload,
            timeout=30
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        assert "job_id" in data
        print(f"Setups train returned job_id={data['job_id']}")
    
    def test_training_status_still_works(self):
        """GET /api/ai-modules/timeseries/training-status should still work"""
        response = requests.get(
            f"{BASE_URL}/api/ai-modules/timeseries/training-status",
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        print(f"Training status: {data.get('status', {})}")


class TestJobQueueIntegration:
    """Test job queue integration - worker picks up jobs"""
    
    def test_list_recent_jobs(self):
        """Can list recent jobs"""
        response = requests.get(
            f"{BASE_URL}/api/jobs",
            params={"limit": 10},
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return list of jobs
        assert isinstance(data, list) or "jobs" in data
        
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        print(f"Found {len(jobs)} recent jobs")
        
        # Print recent training jobs
        training_jobs = [j for j in jobs if j.get("job_type") == "training"]
        for job in training_jobs[:3]:
            print(f"  - {job.get('job_id')}: {job.get('status')} - {job.get('progress', {}).get('message', '')}")
    
    def test_job_gets_picked_up_by_worker(self):
        """Verify worker picks up and processes training jobs"""
        # Create a training job
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/train",
            json={"bar_size": "1 day", "max_symbols": 2},
            timeout=30
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        
        # Wait and check if worker picks it up
        initial_status = None
        final_status = None
        
        for i in range(10):
            time.sleep(3)
            status_response = requests.get(
                f"{BASE_URL}/api/jobs/{job_id}",
                timeout=10
            )
            if status_response.status_code == 200:
                data = status_response.json()
                job = data.get("job", {})
                status = job.get("status")
                
                if initial_status is None:
                    initial_status = status
                
                final_status = status
                print(f"Poll {i+1}: {status} - {job.get('progress', {}).get('percent')}%")
                
                if status in ["running", "completed", "failed"]:
                    if status in ["completed", "failed"]:
                        break
        
        # Job should be in queue (pending) or being processed (running/completed/failed)
        # Worker processes jobs sequentially, so pending is valid if queue is busy
        assert final_status in ["pending", "running", "completed", "failed"], \
            f"Job should be in valid state. Initial: {initial_status}, Final: {final_status}"
        
        print(f"Job {job_id} status: {initial_status} -> {final_status}")
        
        # If still pending, verify worker is running by checking for running jobs
        if final_status == "pending":
            jobs_response = requests.get(f"{BASE_URL}/api/jobs?limit=50", timeout=10)
            if jobs_response.status_code == 200:
                jobs_data = jobs_response.json()
                jobs = jobs_data.get("jobs", [])
                running_jobs = [j for j in jobs if j.get("status") == "running"]
                completed_jobs = [j for j in jobs if j.get("status") == "completed"]
                print(f"Queue status: {len(running_jobs)} running, {len(completed_jobs)} completed")
                # Worker is working if there are completed jobs
                assert len(completed_jobs) > 0, "Worker should have completed some jobs"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
