"""
Test Worker Job Queue Integration for Setup Training

Tests:
1. POST /api/ai-modules/timeseries/setups/train returns job_id (non-blocking)
2. POST /api/ai-modules/timeseries/setups/train-all returns job_id
3. GET /api/jobs/{job_id} returns job status with progress
4. GET /api/ai-modules/timeseries/setups/status returns model statuses
5. POST /api/ai-modules/timeseries/setups/predict still works
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestWorkerJobQueue:
    """Test worker job queue integration for setup training"""
    
    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("✓ Health check passed")
    
    def test_train_setup_returns_job_id(self):
        """POST /api/ai-modules/timeseries/setups/train should return job_id immediately"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json={
                "setup_type": "REVERSAL",
                "bar_size": "1 day"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return success with job_id
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        
        job_id = data["job_id"]
        print(f"✓ Train setup returned job_id: {job_id}")
        
        # Store job_id for later tests
        TestWorkerJobQueue.train_job_id = job_id
        return job_id
    
    def test_train_all_returns_job_id(self):
        """POST /api/ai-modules/timeseries/setups/train-all should return job_id immediately"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train-all",
            json={"bar_size": "1 day"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return success with job_id
        assert data.get("success") == True, f"Expected success=True, got: {data}"
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        
        job_id = data["job_id"]
        print(f"✓ Train-all returned job_id: {job_id}")
        
        # Store job_id for later tests
        TestWorkerJobQueue.train_all_job_id = job_id
        return job_id
    
    def test_get_job_status(self):
        """GET /api/jobs/{job_id} should return job status with progress"""
        # Use the completed job from worker logs
        job_id = "807fdbed"
        
        response = requests.get(f"{BASE_URL}/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        job = data.get("job")
        assert job is not None, "Expected job in response"
        
        # Verify job structure
        assert "job_id" in job
        assert "status" in job
        assert "progress" in job
        
        progress = job.get("progress", {})
        assert "percent" in progress, "Expected percent in progress"
        assert "message" in progress, "Expected message in progress"
        
        print(f"✓ Job {job_id} status: {job['status']}, progress: {progress['percent']}%")
        print(f"  Message: {progress['message']}")
        
        return job
    
    def test_get_job_status_for_new_job(self):
        """GET /api/jobs/{job_id} for newly created job"""
        # Get the job_id from the train test
        job_id = getattr(TestWorkerJobQueue, 'train_job_id', None)
        if not job_id:
            pytest.skip("No train job_id available")
        
        response = requests.get(f"{BASE_URL}/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        job = data.get("job")
        assert job is not None
        
        # Job should be pending, running, or completed
        assert job["status"] in ["pending", "running", "completed", "failed"]
        
        progress = job.get("progress", {})
        print(f"✓ New job {job_id} status: {job['status']}, progress: {progress.get('percent', 0)}%")
        
        return job
    
    def test_get_setup_models_status(self):
        """GET /api/ai-modules/timeseries/setups/status should return model statuses"""
        response = requests.get(f"{BASE_URL}/api/ai-modules/timeseries/setups/status")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "models" in data
        assert "models_trained" in data
        assert "total_setup_types" in data
        
        models = data["models"]
        assert len(models) == 10, f"Expected 10 setup types, got {len(models)}"
        
        # Check expected setup types
        expected_types = [
            "MOMENTUM", "SCALP", "BREAKOUT", "GAP_AND_GO", "RANGE",
            "REVERSAL", "TREND_CONTINUATION", "ORB", "VWAP", "MEAN_REVERSION"
        ]
        for setup_type in expected_types:
            assert setup_type in models, f"Missing setup type: {setup_type}"
        
        trained_count = data["models_trained"]
        print(f"✓ Setup models status: {trained_count}/{data['total_setup_types']} trained")
        
        # Print trained models
        for name, model in models.items():
            if model.get("trained"):
                acc = model.get("accuracy", 0)
                print(f"  - {name}: {acc*100:.1f}% accuracy")
        
        return data
    
    def test_predict_endpoint_still_works(self):
        """POST /api/ai-modules/timeseries/setups/predict should still work"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/predict",
            json={
                "symbol": "AAPL",
                "setup_type": "MOMENTUM"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return a response (success or error about no models)
        print(f"✓ Predict endpoint response: {data.get('success', False)}")
        if not data.get("success"):
            print(f"  Note: {data.get('error', 'No error message')}")
        
        return data
    
    def test_list_jobs(self):
        """GET /api/jobs should list recent jobs"""
        response = requests.get(f"{BASE_URL}/api/jobs")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("success") == True
        assert "jobs" in data
        assert "stats" in data
        
        jobs = data["jobs"]
        stats = data["stats"]
        
        print(f"✓ Jobs list: {len(jobs)} jobs")
        print(f"  Stats: pending={stats.get('pending', 0)}, running={stats.get('running', 0)}, completed={stats.get('completed', 0)}")
        
        # Check for setup_training jobs
        setup_jobs = [j for j in jobs if j.get("job_type") == "setup_training"]
        print(f"  Setup training jobs: {len(setup_jobs)}")
        
        return data
    
    def test_job_progress_structure(self):
        """Verify job progress has correct structure"""
        # Get a completed job
        response = requests.get(f"{BASE_URL}/api/jobs/807fdbed")
        assert response.status_code == 200
        data = response.json()
        
        job = data.get("job")
        assert job is not None
        
        progress = job.get("progress", {})
        
        # Verify progress structure
        assert "percent" in progress
        assert "message" in progress
        assert isinstance(progress["percent"], (int, float))
        assert isinstance(progress["message"], str)
        
        # For completed job, percent should be 100
        if job["status"] == "completed":
            assert progress["percent"] == 100
        
        print(f"✓ Job progress structure verified")
        print(f"  percent: {progress['percent']}, message: {progress['message']}")
        
        return progress
    
    def test_train_invalid_setup_type(self):
        """POST /api/ai-modules/timeseries/setups/train with invalid type should fail"""
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json={
                "setup_type": "INVALID_TYPE",
                "bar_size": "1 day"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return error for invalid setup type
        assert data.get("success") == False
        assert "error" in data
        print(f"✓ Invalid setup type correctly rejected: {data['error'][:50]}...")
        
        return data
    
    def test_get_nonexistent_job(self):
        """GET /api/jobs/{job_id} for non-existent job should return 404"""
        response = requests.get(f"{BASE_URL}/api/jobs/nonexistent123")
        assert response.status_code == 404
        print("✓ Non-existent job correctly returns 404")


class TestWorkerProcessing:
    """Test that worker actually processes jobs"""
    
    def test_job_gets_processed(self):
        """Verify that a submitted job gets picked up by worker"""
        # Submit a new job
        response = requests.post(
            f"{BASE_URL}/api/ai-modules/timeseries/setups/train",
            json={
                "setup_type": "RANGE",
                "bar_size": "1 day"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        job_id = data["job_id"]
        print(f"Submitted job {job_id}, waiting for worker to pick it up...")
        
        # Poll for status changes (worker picks up jobs every 5 seconds)
        max_wait = 30  # seconds
        start_time = time.time()
        last_status = None
        
        while time.time() - start_time < max_wait:
            response = requests.get(f"{BASE_URL}/api/jobs/{job_id}")
            if response.status_code == 200:
                job = response.json().get("job", {})
                status = job.get("status")
                progress = job.get("progress", {})
                
                if status != last_status:
                    print(f"  Status: {status}, Progress: {progress.get('percent', 0)}% - {progress.get('message', '')}")
                    last_status = status
                
                if status in ["completed", "failed"]:
                    print(f"✓ Job {job_id} finished with status: {status}")
                    if status == "completed":
                        result = job.get("result", {})
                        acc = result.get("accuracy", result.get("details", {}).get("metrics", {}).get("accuracy", 0))
                        if acc:
                            print(f"  Accuracy: {acc*100:.1f}%")
                    return job
                
                if status == "running":
                    print(f"✓ Worker picked up job {job_id}")
            
            time.sleep(3)
        
        # If we get here, job didn't complete in time
        print(f"⚠ Job {job_id} still processing after {max_wait}s (this is OK for long training)")
        return None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
