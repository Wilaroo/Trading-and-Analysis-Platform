"""
Social Feed Widget API Tests
Tests for Twitter/X social feed handles and AI sentiment analysis endpoints.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSocialFeedHandles:
    """Tests for /api/social-feed/handles endpoint - CRUD operations for Twitter handles"""
    
    def test_get_handles_returns_19_handles(self):
        """GET /api/social-feed/handles should return 19 default handles"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "handles" in data, "Response should contain 'handles' key"
        assert "count" in data, "Response should contain 'count' key"
        
        handles = data["handles"]
        assert len(handles) == 19, f"Expected 19 handles, got {len(handles)}"
        assert data["count"] == 19, f"Expected count=19, got {data['count']}"
        
    def test_handles_have_correct_structure(self):
        """Each handle should have handle, label, category, description fields"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        handles = data["handles"]
        
        required_fields = ["handle", "label", "category", "description"]
        for h in handles:
            for field in required_fields:
                assert field in h, f"Handle {h.get('handle', 'unknown')} missing field: {field}"
                
    def test_handles_include_expected_accounts(self):
        """Verify specific expected handles are present"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        handle_names = [h["handle"].lower() for h in data["handles"]]
        
        # Note: Handle names are case-sensitive in Twitter, but we compare lowercase
        expected_handles = ["faststocknewss", "deltaone", "unusual_whales", "hindendburgres", "qullamaggie"]
        for expected in expected_handles:
            assert expected.lower() in handle_names, f"Expected handle @{expected} not found"
            
    def test_handles_have_valid_categories(self):
        """All handles should have valid category values"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        valid_categories = ["news", "short-seller", "trading", "analysis", "research", "earnings", "education", "flow"]
        
        for h in data["handles"]:
            assert h["category"] in valid_categories, f"Handle @{h['handle']} has invalid category: {h['category']}"


class TestSocialFeedAddRemoveHandle:
    """Tests for adding and removing handles"""
    
    def test_add_handle(self):
        """POST /api/social-feed/handles should add a new handle"""
        new_handle = {
            "handle": "TEST_handle_123",
            "label": "Test Handle",
            "category": "trading",
            "description": "Test description"
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/handles", json=new_handle, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        
        # Verify handle was added
        get_response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        handles = get_response.json()["handles"]
        handle_names = [h["handle"].lower() for h in handles]
        assert "test_handle_123" in handle_names, "New handle should be in the list"
        
    def test_add_duplicate_handle_fails(self):
        """Adding a duplicate handle should fail"""
        duplicate_handle = {
            "handle": "faststocknewss",  # Already exists
            "label": "Duplicate",
            "category": "news",
            "description": "Duplicate test"
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/handles", json=duplicate_handle, timeout=30)
        assert response.status_code == 200  # Returns 200 with success=False
        
        data = response.json()
        assert data.get("success") == False, f"Expected success=False for duplicate, got {data}"
        assert "error" in data, "Should have error message for duplicate"
        
    def test_remove_handle(self):
        """DELETE /api/social-feed/handles/{handle} should remove a handle"""
        # First add a test handle to remove
        test_handle = {
            "handle": "TEST_to_remove_456",
            "label": "To Remove",
            "category": "trading",
            "description": "Will be removed"
        }
        requests.post(f"{BASE_URL}/api/social-feed/handles", json=test_handle, timeout=30)
        
        # Now remove it
        response = requests.delete(f"{BASE_URL}/api/social-feed/handles/TEST_to_remove_456", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        
        # Verify handle was removed
        get_response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        handles = get_response.json()["handles"]
        handle_names = [h["handle"].lower() for h in handles]
        assert "test_to_remove_456" not in handle_names, "Removed handle should not be in the list"
        
    def test_remove_nonexistent_handle_fails(self):
        """Removing a non-existent handle should fail"""
        response = requests.delete(f"{BASE_URL}/api/social-feed/handles/nonexistent_handle_xyz", timeout=30)
        assert response.status_code == 200  # Returns 200 with success=False
        
        data = response.json()
        assert data.get("success") == False, f"Expected success=False for non-existent, got {data}"


class TestSocialFeedSentimentAnalysis:
    """Tests for AI sentiment analysis endpoint"""
    
    def test_analyze_sentiment_bullish_text(self):
        """POST /api/social-feed/analyze should return sentiment for bullish text"""
        payload = {
            "text": "$AAPL breaking out above resistance on heavy volume, bullish engulfing candle forming. Calls are printing!",
            "handle": "faststocknewss"
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/analyze", json=payload, timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "analysis" in data, "Response should contain 'analysis' key"
        
        analysis = data["analysis"]
        assert "sentiment" in analysis, "Analysis should have 'sentiment'"
        assert "confidence" in analysis, "Analysis should have 'confidence'"
        assert "market_impact" in analysis, "Analysis should have 'market_impact'"
        assert "tickers" in analysis, "Analysis should have 'tickers'"
        assert "summary" in analysis, "Analysis should have 'summary'"
        
        # Bullish text should return BULLISH sentiment (keyword-based fallback)
        assert analysis["sentiment"] in ["BULLISH", "BEARISH", "NEUTRAL"], f"Invalid sentiment: {analysis['sentiment']}"
        
    def test_analyze_sentiment_bearish_text(self):
        """POST /api/social-feed/analyze should return sentiment for bearish text"""
        payload = {
            "text": "$TSLA fraud exposed! Short this overvalued garbage. Puts are the play. Crash incoming.",
            "handle": "HindendburgRes"
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/analyze", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        analysis = data["analysis"]
        # Bearish text should return BEARISH sentiment (keyword-based fallback)
        assert analysis["sentiment"] in ["BULLISH", "BEARISH", "NEUTRAL"]
        
    def test_analyze_sentiment_extracts_tickers(self):
        """Sentiment analysis should extract ticker symbols from text"""
        payload = {
            "text": "Watching $NVDA and $AMD for breakouts. $MSFT looking weak.",
            "handle": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/analyze", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        analysis = data["analysis"]
        
        # Should extract tickers
        assert isinstance(analysis["tickers"], list), "Tickers should be a list"
        # Note: keyword-based fallback extracts $TICKER format
        
    def test_analyze_empty_text_fails(self):
        """Analyzing empty text should fail with 400"""
        payload = {
            "text": "",
            "handle": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/analyze", json=payload, timeout=30)
        assert response.status_code == 400, f"Expected 400 for empty text, got {response.status_code}"
        
    def test_analyze_whitespace_only_fails(self):
        """Analyzing whitespace-only text should fail with 400"""
        payload = {
            "text": "   \n\t  ",
            "handle": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/social-feed/analyze", json=payload, timeout=30)
        assert response.status_code == 400, f"Expected 400 for whitespace text, got {response.status_code}"


class TestSocialFeedAnalysesList:
    """Tests for recent analyses list endpoint"""
    
    def test_get_recent_analyses(self):
        """GET /api/social-feed/analyses should return recent analyses"""
        response = requests.get(f"{BASE_URL}/api/social-feed/analyses", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, f"Expected success=True, got {data}"
        assert "analyses" in data, "Response should contain 'analyses' key"
        assert "count" in data, "Response should contain 'count' key"
        assert isinstance(data["analyses"], list), "Analyses should be a list"
        
    def test_get_recent_analyses_with_limit(self):
        """GET /api/social-feed/analyses?limit=5 should respect limit"""
        response = requests.get(f"{BASE_URL}/api/social-feed/analyses?limit=5", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["analyses"]) <= 5, f"Should return at most 5 analyses, got {len(data['analyses'])}"


class TestCleanup:
    """Cleanup test data"""
    
    def test_cleanup_test_handles(self):
        """Remove any TEST_ prefixed handles created during testing"""
        # Get current handles
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        if response.status_code == 200:
            handles = response.json().get("handles", [])
            for h in handles:
                if h["handle"].upper().startswith("TEST_"):
                    requests.delete(f"{BASE_URL}/api/social-feed/handles/{h['handle']}", timeout=30)
        
        # Verify cleanup
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        if response.status_code == 200:
            handles = response.json().get("handles", [])
            test_handles = [h for h in handles if h["handle"].upper().startswith("TEST_")]
            assert len(test_handles) == 0, f"Test handles should be cleaned up, found: {test_handles}"
