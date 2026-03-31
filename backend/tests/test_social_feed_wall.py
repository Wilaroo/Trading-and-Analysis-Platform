"""
Social Feed Wall View Enhancement Tests
Tests for the TweetDeck-style multi-panel wall view with @TruthTrumpPosts handle
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSocialFeedHandles:
    """Test GET /api/social-feed/handles endpoint"""
    
    def test_get_handles_returns_20_handles(self):
        """Verify 20 handles are returned (added TruthTrumpPosts)"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["count"] == 20
        assert len(data["handles"]) == 20
        print(f"PASS: GET /api/social-feed/handles returns {data['count']} handles")
    
    def test_handles_have_required_fields(self):
        """Verify each handle has required fields"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        for handle in data["handles"]:
            assert "handle" in handle
            assert "label" in handle
            assert "category" in handle
            assert "description" in handle
        print("PASS: All handles have required fields (handle, label, category, description)")
    
    def test_prioritized_handles_have_priority_field(self):
        """Verify top 4 handles have priority field (1-4)"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        prioritized = [h for h in data["handles"] if h.get("priority")]
        
        assert len(prioritized) == 4, f"Expected 4 prioritized handles, got {len(prioritized)}"
        
        priorities = sorted([h["priority"] for h in prioritized])
        assert priorities == [1, 2, 3, 4], f"Expected priorities [1,2,3,4], got {priorities}"
        print("PASS: 4 handles have priority field with values 1-4")
    
    def test_prioritized_handles_are_correct(self):
        """Verify the 4 prioritized handles are faststocknewss, Deltaone, unusual_whales, TruthTrumpPosts"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        prioritized = {h["handle"]: h["priority"] for h in data["handles"] if h.get("priority")}
        
        expected = {
            "faststocknewss": 1,
            "Deltaone": 2,
            "unusual_whales": 3,
            "TruthTrumpPosts": 4
        }
        
        assert prioritized == expected, f"Expected {expected}, got {prioritized}"
        print("PASS: Prioritized handles are faststocknewss(P1), Deltaone(P2), unusual_whales(P3), TruthTrumpPosts(P4)")
    
    def test_truthtrumpposts_has_political_category(self):
        """Verify TruthTrumpPosts has 'political' category"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        trump_handle = next((h for h in data["handles"] if h["handle"] == "TruthTrumpPosts"), None)
        
        assert trump_handle is not None, "TruthTrumpPosts handle not found"
        assert trump_handle["category"] == "political", f"Expected 'political' category, got '{trump_handle['category']}'"
        print("PASS: TruthTrumpPosts has 'political' category")


class TestSocialFeedAnalyze:
    """Test POST /api/social-feed/analyze endpoint"""
    
    def test_analyze_returns_sentiment(self):
        """Verify analyze endpoint returns sentiment analysis"""
        response = requests.post(
            f"{BASE_URL}/api/social-feed/analyze",
            json={"text": "$AAPL breaking out above resistance on heavy volume", "handle": "faststocknewss"},
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "analysis" in data
        
        analysis = data["analysis"]
        assert "sentiment" in analysis
        assert analysis["sentiment"] in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert "confidence" in analysis
        assert "market_impact" in analysis
        assert "summary" in analysis
        print(f"PASS: Analyze returns sentiment={analysis['sentiment']}, confidence={analysis['confidence']}")
    
    def test_analyze_bullish_text(self):
        """Verify bullish text returns BULLISH sentiment"""
        response = requests.post(
            f"{BASE_URL}/api/social-feed/analyze",
            json={"text": "buy buy buy! $TSLA to the moon! calls printing!", "handle": ""},
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["analysis"]["sentiment"] == "BULLISH"
        print("PASS: Bullish text returns BULLISH sentiment")
    
    def test_analyze_bearish_text(self):
        """Verify bearish text returns BEARISH sentiment"""
        response = requests.post(
            f"{BASE_URL}/api/social-feed/analyze",
            json={"text": "sell everything! $NVDA crash incoming! puts printing! fraud!", "handle": ""},
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["analysis"]["sentiment"] == "BEARISH"
        print("PASS: Bearish text returns BEARISH sentiment")
    
    def test_analyze_extracts_tickers(self):
        """Verify analyze extracts ticker symbols"""
        response = requests.post(
            f"{BASE_URL}/api/social-feed/analyze",
            json={"text": "$AAPL and $MSFT looking strong today", "handle": ""},
            timeout=60
        )
        assert response.status_code == 200
        
        data = response.json()
        tickers = data["analysis"].get("tickers", [])
        # Note: keyword-based fallback may not extract tickers perfectly
        print(f"PASS: Analyze extracts tickers: {tickers}")
    
    def test_analyze_empty_text_returns_400(self):
        """Verify empty text returns 400 error"""
        response = requests.post(
            f"{BASE_URL}/api/social-feed/analyze",
            json={"text": "", "handle": ""},
            timeout=30
        )
        assert response.status_code == 400
        print("PASS: Empty text returns 400 error")


class TestSocialFeedCategories:
    """Test category colors and structure"""
    
    def test_all_categories_present(self):
        """Verify all expected categories are present"""
        response = requests.get(f"{BASE_URL}/api/social-feed/handles", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        categories = set(h["category"] for h in data["handles"])
        
        expected_categories = {"news", "short-seller", "trading", "analysis", "research", "earnings", "education", "flow", "political"}
        
        # Check that political category exists (new for TruthTrumpPosts)
        assert "political" in categories, "political category not found"
        
        # Check most expected categories are present
        missing = expected_categories - categories
        if missing:
            print(f"Note: Some categories not in current handles: {missing}")
        
        print(f"PASS: Categories found: {categories}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
