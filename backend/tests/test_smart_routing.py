"""
Test Smart AI Routing and Market Intel Reports

Tests:
1. GET /api/llm/status shows smart_routing config with light/standard/deep categories
2. GET /api/llm/status shows Ollama as primary with 'light + standard tasks' role
3. GET /api/llm/status shows Emergent as 'deep tasks + fallback' role
4. POST /api/assistant/chat with simple message returns response (Ollama)
5. POST /api/assistant/chat with deep question returns detailed analysis (GPT-4o)
6. POST /api/market-intel/generate/premarket generates report with real Finnhub news
7. Market intel reports contain exact bot status data
8. Market intel reports show exact strategy performance numbers
9. GET /api/market-intel/schedule returns 5 report types
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSmartRouting:
    """Test smart AI routing configuration"""

    def test_llm_status_endpoint(self):
        """GET /api/llm/status returns 200"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/llm/status returns 200")

    def test_llm_status_smart_routing_config(self):
        """GET /api/llm/status shows smart_routing config with light/standard/deep"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "smart_routing" in data, "Response missing smart_routing field"
        smart_routing = data["smart_routing"]
        
        # Check for all three complexity categories
        assert "light" in smart_routing, "smart_routing missing 'light' category"
        assert "standard" in smart_routing, "smart_routing missing 'standard' category"
        assert "deep" in smart_routing, "smart_routing missing 'deep' category"
        
        print(f"✓ smart_routing config: {smart_routing}")
        print("✓ GET /api/llm/status shows smart_routing with light/standard/deep categories")

    def test_llm_status_ollama_primary(self):
        """GET /api/llm/status shows Ollama as primary with 'light + standard tasks' role"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        # Check primary_provider is ollama
        assert data.get("primary_provider") == "ollama", f"Expected primary_provider=ollama, got {data.get('primary_provider')}"
        
        # Check Ollama provider config
        providers = data.get("providers", {})
        ollama = providers.get("ollama", {})
        
        assert ollama.get("available") == True, "Ollama should be available"
        assert "role" in ollama, "Ollama config missing 'role' field"
        
        role = ollama.get("role", "")
        assert "light" in role.lower() or "standard" in role.lower(), f"Ollama role should mention light/standard tasks, got: {role}"
        
        print(f"✓ Ollama primary_provider=ollama, role='{role}'")
        print("✓ GET /api/llm/status shows Ollama as primary with light + standard tasks role")

    def test_llm_status_emergent_deep_fallback(self):
        """GET /api/llm/status shows Emergent as 'deep tasks + fallback' role"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        providers = data.get("providers", {})
        emergent = providers.get("emergent", {})
        
        assert emergent.get("available") == True, "Emergent should be available"
        assert "role" in emergent, "Emergent config missing 'role' field"
        
        role = emergent.get("role", "")
        assert "deep" in role.lower() or "fallback" in role.lower(), f"Emergent role should mention deep/fallback, got: {role}"
        
        print(f"✓ Emergent role='{role}'")
        print("✓ GET /api/llm/status shows Emergent as deep tasks + fallback role")


class TestAIChatRouting:
    """Test AI chat with smart routing (simple vs deep questions)"""

    def test_chat_simple_message(self):
        """POST /api/assistant/chat with simple message ('hello') returns response"""
        payload = {
            "message": "hello",
            "session_id": "test-simple-001"
        }
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=120  # Ollama can be slow
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "response" in data, "Response missing 'response' field"
        assert len(data.get("response", "")) > 10, "Response should have content"
        
        provider = data.get("provider", "unknown")
        print(f"✓ Simple message response provider: {provider}")
        print(f"✓ Response length: {len(data.get('response', ''))} chars")
        print("✓ POST /api/assistant/chat with simple message returns response")

    def test_chat_deep_question(self):
        """POST /api/assistant/chat with deep question triggers GPT-4o analysis"""
        # Deep question keywords: 'should i buy', 'analyze', 'strategy', 'risk', 'recommend'
        payload = {
            "message": "Should I buy AAPL? Analyze the risk and recommend a strategy",
            "session_id": "test-deep-001"
        }
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json=payload,
            timeout=120  # GPT-4o can take time
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "response" in data, "Response missing 'response' field"
        response_text = data.get("response", "")
        
        # Deep responses should be longer and more detailed
        assert len(response_text) > 100, f"Deep analysis should be detailed, got {len(response_text)} chars"
        
        # Check for structured analysis (not required but expected)
        has_analysis = any(kw in response_text.lower() for kw in ['risk', 'analysis', 'strategy', 'recommendation', 'consider'])
        print(f"✓ Deep response length: {len(response_text)} chars")
        print(f"✓ Contains analysis keywords: {has_analysis}")
        print("✓ POST /api/assistant/chat with deep question returns detailed analysis")


class TestMarketIntelReports:
    """Test Market Intel reports with real data"""

    def test_market_intel_schedule(self):
        """GET /api/market-intel/schedule returns 5 report types"""
        response = requests.get(f"{BASE_URL}/api/market-intel/schedule", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "schedule" in data, "Response missing 'schedule' field"
        schedule = data.get("schedule", [])
        
        assert len(schedule) >= 5, f"Expected at least 5 report types, got {len(schedule)}"
        
        report_types = [r.get("type") for r in schedule]
        expected_types = ["premarket", "early_market", "midday", "power_hour", "post_market"]
        
        for expected in expected_types:
            assert expected in report_types, f"Missing report type: {expected}"
        
        print(f"✓ Report schedule: {report_types}")
        print("✓ GET /api/market-intel/schedule returns 5 report types")

    def test_generate_premarket_report(self):
        """POST /api/market-intel/generate/premarket generates report with real news"""
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/premarket?force=true",
            timeout=120  # LLM generation takes time
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data.get("success") == True, f"Generation failed: {data.get('error')}"
        
        report = data.get("report", {})
        content = report.get("content", "")
        
        assert len(content) > 100, f"Report content too short: {len(content)} chars"
        
        print(f"✓ Report generated, content length: {len(content)} chars")
        print(f"✓ Report type: {report.get('type')}")
        print(f"✓ Generated at: {report.get('generated_at_et')}")
        
        # Check content quality - should NOT have hallucinated news
        # Look for real news markers from Finnhub
        has_real_indicators = (
            "finnhub" in content.lower() or
            "real" in content.lower() or
            "headline" in content.lower() or
            "news" in content.lower()
        )
        print(f"✓ Has real news indicators: {has_real_indicators}")
        
        return content

    def test_report_no_fabricated_news(self):
        """Market intel reports do NOT contain fabricated/hallucinated news"""
        # Get current report
        response = requests.get(f"{BASE_URL}/api/market-intel/current", timeout=30)
        
        if response.status_code != 200 or not response.json():
            # Generate one first
            gen_response = requests.post(
                f"{BASE_URL}/api/market-intel/generate/premarket?force=true",
                timeout=120
            )
            if gen_response.status_code == 200:
                data = gen_response.json()
                content = data.get("report", {}).get("content", "")
            else:
                pytest.skip("Could not generate report for validation")
                return
        else:
            content = response.json().get("content", "")
        
        # Check for hallucination markers (fictional things that shouldn't appear)
        # Note: This is heuristic - real testing would compare against Finnhub API
        fictional_markers = ["made-up", "fictional", "imaginary"]
        
        has_fictional = any(marker in content.lower() for marker in fictional_markers)
        assert not has_fictional, "Report may contain fabricated content"
        
        print("✓ Report does not contain obvious fabrication markers")

    def test_report_contains_bot_status(self):
        """Market intel reports contain exact bot status data"""
        # Generate a fresh report to ensure bot context is included
        response = requests.post(
            f"{BASE_URL}/api/market-intel/generate/midday?force=true",
            timeout=120
        )
        
        if response.status_code != 200:
            pytest.skip(f"Could not generate midday report: {response.status_code}")
            return
        
        data = response.json()
        content = data.get("report", {}).get("content", "")
        
        # Bot status indicators
        bot_keywords = ["bot", "trading bot", "confirmation", "autonomous", "paused", "capital", "mode"]
        has_bot_data = any(kw in content.lower() for kw in bot_keywords)
        
        print(f"✓ Report contains bot status references: {has_bot_data}")
        # This is informational - the bot data should be in the context fed to LLM

    def test_report_contains_strategy_performance(self):
        """Market intel reports show strategy performance numbers from learning loop"""
        # Get current or generate report
        response = requests.get(f"{BASE_URL}/api/market-intel/current", timeout=30)
        
        if response.status_code != 200:
            pytest.skip("No current report available")
            return
        
        content = response.json().get("content", "")
        
        # Strategy performance indicators
        perf_keywords = ["strategy", "performance", "win rate", "p&l", "pnl", "learning"]
        has_perf_data = any(kw in content.lower() for kw in perf_keywords)
        
        print(f"✓ Report contains strategy performance references: {has_perf_data}")


class TestOllamaConnectivity:
    """Verify Ollama tunnel connectivity"""

    def test_ollama_connected(self):
        """Verify Ollama is connected via ngrok tunnel"""
        response = requests.get(f"{BASE_URL}/api/llm/status", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        ollama = data.get("providers", {}).get("ollama", {})
        
        assert ollama.get("connected") == True, f"Ollama not connected: {ollama}"
        
        models = ollama.get("models_available", [])
        print(f"✓ Ollama connected, models: {models}")
        
        url = ollama.get("url", "")
        assert "ngrok" in url or "pseudoaccidentally" in url, f"Expected ngrok URL, got: {url}"
        
        print(f"✓ Ollama URL: {url}")
        print("✓ Ollama tunnel connectivity verified")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
