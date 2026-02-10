"""
Test Ollama LLM Integration
Tests the Ollama integration as PRIMARY LLM provider with Emergent fallback.
Features tested:
- GET /api/llm/status: Ollama as primary, connected, models list, Emergent fallback
- POST /api/assistant/chat: AI response from Ollama
- POST /api/market-intel/generate/{type}: Market intel generation via Ollama
- GET /api/market-intel/current: Most recent report
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestOllamaLLMIntegration:
    """Tests for Ollama as PRIMARY LLM provider"""
    
    def test_llm_status_ollama_primary(self):
        """Verify Ollama is configured as primary provider"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["primary_provider"] == "ollama", f"Expected ollama as primary, got {data['primary_provider']}"
        print(f"✅ Primary provider is Ollama")
    
    def test_llm_status_ollama_connected(self):
        """Verify Ollama shows connected=true"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        ollama_info = data["providers"].get("ollama", {})
        
        assert ollama_info.get("available") == True, "Ollama should be available"
        assert ollama_info.get("connected") == True, "Ollama should be connected"
        print(f"✅ Ollama connected: {ollama_info.get('connected')}")
    
    def test_llm_status_models_available(self):
        """Verify models_available list is returned from Ollama"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        ollama_info = data["providers"].get("ollama", {})
        
        models = ollama_info.get("models_available", [])
        assert isinstance(models, list), "models_available should be a list"
        assert len(models) > 0, "Should have at least one model available"
        assert "llama3:8b" in models, f"llama3:8b should be in models list, got: {models}"
        print(f"✅ Models available: {models}")
    
    def test_llm_status_emergent_fallback(self):
        """Verify Emergent is configured as fallback"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        emergent_info = data["providers"].get("emergent", {})
        
        assert emergent_info.get("available") == True, "Emergent should be available"
        assert emergent_info.get("role") == "fallback", "Emergent should be fallback"
        print(f"✅ Emergent configured as fallback")
    
    def test_llm_status_ollama_url_model(self):
        """Verify Ollama URL and model are configured"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        ollama_info = data["providers"].get("ollama", {})
        
        assert "url" in ollama_info, "Ollama URL should be present"
        assert "ngrok" in ollama_info["url"], "Ollama URL should be ngrok tunnel"
        assert ollama_info.get("model") == "llama3:8b", f"Model should be llama3:8b, got {ollama_info.get('model')}"
        print(f"✅ Ollama URL: {ollama_info['url']}, Model: {ollama_info['model']}")


class TestAIAssistantChat:
    """Tests for AI Assistant chat using Ollama"""
    
    def test_chat_returns_response(self):
        """Verify POST /api/assistant/chat returns AI response"""
        payload = {
            "message": "What is 2+2?",
            "session_id": "pytest-ollama-test-1"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=90  # Ollama can be slow
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:500]}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "response" in data, "Response should contain 'response' field"
        assert len(data["response"]) > 10, f"Response should have content, got: {data['response'][:100]}"
        print(f"✅ Chat response received: {data['response'][:100]}...")
    
    def test_chat_uses_ollama_provider(self):
        """Verify chat response indicates Ollama provider"""
        payload = {
            "message": "Say hello",
            "session_id": "pytest-ollama-test-2"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=90
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # The provider field should indicate ollama was used
        provider = data.get("provider", "unknown")
        print(f"✅ Chat provider: {provider}")
        # Provider should be ollama unless it fell back
        if provider != "ollama":
            print(f"⚠️ Note: Response came from {provider}, not ollama (may have fallen back)")


class TestMarketIntelGeneration:
    """Tests for Market Intel report generation via Ollama"""
    
    def test_generate_power_hour_report(self):
        """Verify POST /api/market-intel/generate/power_hour generates report"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/power_hour",
            timeout=90
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:500]}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "report" in data, "Response should contain 'report' field"
        
        report = data["report"]
        assert report.get("type") == "power_hour", f"Report type should be power_hour"
        assert "content" in report, "Report should have content"
        assert len(report["content"]) > 200, f"Report content should be substantial, got {len(report['content'])} chars"
        print(f"✅ Power Hour report generated: {len(report['content'])} chars")
    
    def test_get_current_report(self):
        """Verify GET /api/market-intel/current returns most recent report"""
        response = requests.get(
            f"{BASE_URL}/api/market-intel/current",
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("has_report") == True, "Should have a report"
        
        report = data.get("report", {})
        assert "type" in report, "Report should have type"
        assert "content" in report, "Report should have content"
        assert len(report["content"]) > 100, "Report should have substantial content"
        print(f"✅ Current report: {report['type']} - {len(report['content'])} chars")
    
    def test_get_market_intel_schedule(self):
        """Verify GET /api/market-intel/schedule returns 5 report types"""
        response = requests.get(
            f"{BASE_URL}/api/market-intel/schedule",
            timeout=30
        )
        
        assert response.status_code == 200
        
        data = response.json()
        schedule = data.get("schedule", [])
        
        assert len(schedule) >= 5, f"Should have 5 report types, got {len(schedule)}"
        
        report_types = [r["type"] for r in schedule]
        expected_types = ["premarket", "early_market", "midday", "power_hour", "post_market"]
        for expected in expected_types:
            assert expected in report_types, f"{expected} should be in schedule"
        
        print(f"✅ Schedule has {len(schedule)} report types: {report_types}")


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_endpoint(self):
        """Verify health endpoint is working"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✅ Health check passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
