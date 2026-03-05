"""
Tests for IB Data Pusher Integration - Iteration 48
Testing: /api/ib/status, /api/ib/pusher-setup endpoints
Focus: Pusher status object, connection_source field, setup instructions
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestIBStatusEndpoint:
    """Tests for /api/ib/status endpoint - pusher status integration"""
    
    def test_ib_status_returns_200(self):
        """Test that /api/ib/status returns 200"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ /api/ib/status returns 200")
    
    def test_ib_status_has_pusher_object(self):
        """Test that status response contains pusher object"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "pusher" in data, "Response should contain 'pusher' object"
        pusher = data["pusher"]
        
        # Verify pusher object has required fields
        assert "connected" in pusher, "pusher should have 'connected' field"
        assert "last_update" in pusher, "pusher should have 'last_update' field"
        assert "positions_count" in pusher, "pusher should have 'positions_count' field"
        assert "quotes_count" in pusher, "pusher should have 'quotes_count' field"
        assert "stale" in pusher, "pusher should have 'stale' field"
        
        print(f"✓ Pusher object fields: connected={pusher['connected']}, positions={pusher['positions_count']}, quotes={pusher['quotes_count']}, stale={pusher['stale']}")
    
    def test_ib_status_has_connection_source(self):
        """Test that status response contains connection_source field"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "connection_source" in data, "Response should contain 'connection_source' field"
        connection_source = data["connection_source"]
        
        # connection_source should be one of: "direct", "pusher", "none"
        valid_sources = ["direct", "pusher", "none"]
        assert connection_source in valid_sources, f"connection_source should be one of {valid_sources}, got '{connection_source}'"
        
        print(f"✓ connection_source: '{connection_source}'")
    
    def test_ib_status_has_is_busy_field(self):
        """Test that status response contains is_busy field"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "is_busy" in data, "Response should contain 'is_busy' field"
        assert isinstance(data["is_busy"], bool), "is_busy should be boolean"
        
        print(f"✓ is_busy: {data['is_busy']}")
    
    def test_ib_status_connection_logic(self):
        """Test connection logic: pusher connected counts as overall connected"""
        response = requests.get(f"{BASE_URL}/api/ib/status")
        assert response.status_code == 200
        data = response.json()
        
        pusher_connected = data.get("pusher", {}).get("connected", False)
        direct_connected = data.get("connected", False)
        connection_source = data.get("connection_source", "none")
        
        # Verify logic: if pusher is connected, overall should be connected
        # If direct is connected but not pusher, connection_source should be "direct"
        # If neither connected, connection_source should be "none"
        if pusher_connected:
            assert direct_connected or connection_source == "pusher", "If pusher connected, overall should be connected or source='pusher'"
        elif direct_connected:
            assert connection_source == "direct", "If direct connected (not pusher), source should be 'direct'"
        else:
            assert connection_source == "none", "If nothing connected, source should be 'none'"
        
        print(f"✓ Connection logic verified: direct={direct_connected}, pusher={pusher_connected}, source={connection_source}")


class TestPusherSetupEndpoint:
    """Tests for /api/ib/pusher-setup endpoint"""
    
    def test_pusher_setup_returns_200(self):
        """Test that /api/ib/pusher-setup returns 200"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ /api/ib/pusher-setup returns 200")
    
    def test_pusher_setup_has_cloud_url(self):
        """Test that setup response contains cloud_url"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200
        data = response.json()
        
        assert "cloud_url" in data, "Response should contain 'cloud_url'"
        assert data["cloud_url"], "cloud_url should not be empty"
        assert data["cloud_url"].startswith("http"), "cloud_url should be a valid URL"
        
        print(f"✓ cloud_url: {data['cloud_url']}")
    
    def test_pusher_setup_has_push_endpoint(self):
        """Test that setup response contains push_endpoint"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200
        data = response.json()
        
        assert "push_endpoint" in data, "Response should contain 'push_endpoint'"
        assert "/api/ib/push-data" in data["push_endpoint"], "push_endpoint should contain /api/ib/push-data"
        
        print(f"✓ push_endpoint: {data['push_endpoint']}")
    
    def test_pusher_setup_has_setup_steps(self):
        """Test that setup response contains setup_steps array"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200
        data = response.json()
        
        assert "setup_steps" in data, "Response should contain 'setup_steps'"
        assert isinstance(data["setup_steps"], list), "setup_steps should be a list"
        assert len(data["setup_steps"]) >= 4, "Should have at least 4 setup steps"
        
        # Verify key steps are present
        steps_text = " ".join(data["setup_steps"]).lower()
        assert "pip install" in steps_text, "Steps should include pip install"
        assert "ib_insync" in steps_text, "Steps should mention ib_insync"
        assert "ib gateway" in steps_text.lower() or "tws" in steps_text.lower(), "Steps should mention IB Gateway or TWS"
        assert "cloud_url" in steps_text.lower(), "Steps should mention CLOUD_URL"
        
        print(f"✓ setup_steps: {len(data['setup_steps'])} steps provided")
        for i, step in enumerate(data["setup_steps"], 1):
            print(f"  Step {i}: {step[:60]}...")
    
    def test_pusher_setup_has_current_status(self):
        """Test that setup response contains current pusher status"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200
        data = response.json()
        
        # Should have current status fields
        assert "pusher_connected" in data, "Response should contain 'pusher_connected'"
        assert "positions_count" in data, "Response should contain 'positions_count'"
        assert "quotes_count" in data, "Response should contain 'quotes_count'"
        
        print(f"✓ Current status: connected={data['pusher_connected']}, positions={data['positions_count']}, quotes={data['quotes_count']}")
    
    def test_pusher_setup_has_script_info(self):
        """Test that setup response contains script name and requirements"""
        response = requests.get(f"{BASE_URL}/api/ib/pusher-setup")
        assert response.status_code == 200
        data = response.json()
        
        assert "script_name" in data, "Response should contain 'script_name'"
        assert data["script_name"] == "ib_data_pusher.py", f"script_name should be 'ib_data_pusher.py', got '{data['script_name']}'"
        
        assert "requirements" in data, "Response should contain 'requirements'"
        assert isinstance(data["requirements"], list), "requirements should be a list"
        assert "ib_insync" in data["requirements"], "requirements should include ib_insync"
        assert "aiohttp" in data["requirements"], "requirements should include aiohttp"
        
        print(f"✓ Script: {data['script_name']}, Requirements: {data['requirements']}")


class TestPushedDataEndpoint:
    """Tests for /api/ib/pushed-data endpoint"""
    
    def test_pushed_data_returns_200(self):
        """Test that /api/ib/pushed-data returns 200"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ /api/ib/pushed-data returns 200")
    
    def test_pushed_data_structure(self):
        """Test that pushed-data has expected structure"""
        response = requests.get(f"{BASE_URL}/api/ib/pushed-data")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["connected", "last_update", "quotes", "account", "positions"]
        for field in required_fields:
            assert field in data, f"Response should contain '{field}'"
        
        # Type checks
        assert isinstance(data["connected"], bool), "connected should be boolean"
        assert isinstance(data["quotes"], dict), "quotes should be a dict"
        assert isinstance(data["account"], dict), "account should be a dict"
        assert isinstance(data["positions"], list), "positions should be a list"
        
        print(f"✓ pushed-data structure: connected={data['connected']}, quotes={len(data['quotes'])}, positions={len(data['positions'])}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
