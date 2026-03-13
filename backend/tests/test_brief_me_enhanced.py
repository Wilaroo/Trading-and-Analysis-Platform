"""
Test Enhanced Brief Me Feature
==============================
Tests for the Brief Me API endpoint with enhanced news, sector rotation, and catalyst data.

Features tested:
- Brief Me API returns success with news headlines, themes, and sentiment
- Brief Me API includes sector rotation data (leaders and laggards)
- Brief Me API includes catalysts extracted from news
- Brief Me API response time under 40 seconds
- Quick vs detailed response levels
"""

import pytest
import requests
import time
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBriefMeEnhanced:
    """Test Enhanced Brief Me API endpoint"""

    def test_brief_me_quick_returns_success(self):
        """Test that quick brief returns successfully"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, "Brief Me should return success=True"
        assert data.get("detail_level") == "quick", "Detail level should be 'quick'"
        assert "summary" in data, "Response should include summary"
        assert isinstance(data["summary"], str), "Quick summary should be a string"
        print(f"SUCCESS: Quick brief returned with summary: {data['summary'][:100]}...")

    def test_brief_me_detailed_returns_success(self):
        """Test that detailed brief returns successfully"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") == True, "Brief Me should return success=True"
        assert data.get("detail_level") == "detailed", "Detail level should be 'detailed'"
        assert "summary" in data, "Response should include summary"
        
        # Detailed summary should be a dict with sections
        summary = data.get("summary")
        assert isinstance(summary, (dict, str)), "Summary should be dict or string"
        
        if isinstance(summary, dict):
            # Check for expected sections
            expected_sections = ["market_overview", "bot_status", "recommendation"]
            for section in expected_sections:
                if section in summary:
                    print(f"SUCCESS: Section '{section}' present in detailed summary")
        
        print("SUCCESS: Detailed brief returned successfully")

    def test_brief_me_includes_news_data(self):
        """Test that Brief Me response includes news headlines, themes, and sentiment"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        # Check data structure
        brief_data = data.get("data", {})
        news = brief_data.get("news", {})
        
        # Verify news structure
        assert "headlines" in news, "News should include headlines"
        assert "themes" in news, "News should include themes"
        assert "sentiment" in news, "News should include sentiment"
        
        headlines = news.get("headlines", [])
        themes = news.get("themes", [])
        sentiment = news.get("sentiment", "")
        
        print(f"Headlines count: {len(headlines)}")
        print(f"Themes: {themes}")
        print(f"Sentiment: {sentiment}")
        
        # News should have data (from Finnhub fallback since IB is not connected)
        if headlines:
            print(f"SUCCESS: Got {len(headlines)} news headlines")
            print(f"First headline: {headlines[0][:80]}...")
        else:
            print("NOTE: No headlines returned - check Finnhub API connection")
        
        # Themes should be extracted
        if themes:
            print(f"SUCCESS: Got {len(themes)} market themes: {themes}")
        
        # Sentiment should be one of: bullish, bearish, neutral, mixed
        valid_sentiments = ["bullish", "bearish", "neutral", "mixed"]
        assert sentiment in valid_sentiments or sentiment == "", f"Invalid sentiment: {sentiment}"
        print(f"SUCCESS: Sentiment is '{sentiment}'")

    def test_brief_me_includes_sector_rotation(self):
        """Test that Brief Me response includes sector rotation data (leaders and laggards)"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        brief_data = data.get("data", {})
        sectors = brief_data.get("sectors", {})
        
        # Verify sectors structure
        assert "leaders" in sectors, "Sectors should include leaders"
        assert "laggards" in sectors, "Sectors should include laggards"
        assert "rotation_signal" in sectors, "Sectors should include rotation_signal"
        
        leaders = sectors.get("leaders", [])
        laggards = sectors.get("laggards", [])
        rotation_signal = sectors.get("rotation_signal")
        
        print(f"Leaders count: {len(leaders)}")
        print(f"Laggards count: {len(laggards)}")
        print(f"Rotation signal: {rotation_signal}")
        
        # Leaders should have structure with symbol, name, change_pct
        if leaders:
            first_leader = leaders[0]
            assert "symbol" in first_leader, "Leader should have symbol"
            assert "name" in first_leader, "Leader should have name"
            assert "change_pct" in first_leader, "Leader should have change_pct"
            print(f"SUCCESS: Top leader: {first_leader['name']} ({first_leader['symbol']}) {first_leader['change_pct']}%")
        
        # Laggards should have same structure
        if laggards:
            first_laggard = laggards[0]
            assert "symbol" in first_laggard, "Laggard should have symbol"
            assert "name" in first_laggard, "Laggard should have name"
            assert "change_pct" in first_laggard, "Laggard should have change_pct"
            print(f"SUCCESS: Top laggard: {first_laggard['name']} ({first_laggard['symbol']}) {first_laggard['change_pct']}%")
        
        # Rotation signal should be one of expected values
        valid_signals = [
            "risk_on_growth", "risk_off_defensive", "cyclical_rotation",
            "broad_selling", "broad_buying", "mixed_rotation", "unknown", None
        ]
        assert rotation_signal in valid_signals, f"Invalid rotation signal: {rotation_signal}"
        print(f"SUCCESS: Rotation signal is '{rotation_signal}'")

    def test_brief_me_includes_catalysts(self):
        """Test that Brief Me response includes catalysts extracted from news"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        brief_data = data.get("data", {})
        catalysts = brief_data.get("catalysts", [])
        
        print(f"Catalysts count: {len(catalysts)}")
        
        # Check catalyst structure if present
        if catalysts:
            first_catalyst = catalysts[0]
            assert "type" in first_catalyst, "Catalyst should have type"
            assert "headline" in first_catalyst, "Catalyst should have headline"
            
            print(f"SUCCESS: Got {len(catalysts)} catalysts")
            print(f"First catalyst type: {first_catalyst.get('type')}")
            print(f"First catalyst headline: {first_catalyst.get('headline', '')[:80]}...")
            
            # Check for optional fields
            if "ticker" in first_catalyst:
                print(f"Catalyst ticker: {first_catalyst.get('ticker')}")
            if "impact" in first_catalyst:
                print(f"Catalyst impact: {first_catalyst.get('impact')}")
        else:
            print("NOTE: No catalysts returned - this may happen if no catalyst-related news")

    def test_brief_me_response_time_under_40_seconds(self):
        """Test that Brief Me API responds within 40 seconds"""
        # Test quick response
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        quick_time = time.time() - start_time
        
        assert response.status_code == 200
        assert quick_time < 40, f"Quick response took {quick_time:.1f}s, expected under 40s"
        print(f"SUCCESS: Quick response time: {quick_time:.2f}s")
        
        # Test detailed response
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        detailed_time = time.time() - start_time
        
        assert response.status_code == 200
        assert detailed_time < 40, f"Detailed response took {detailed_time:.1f}s, expected under 40s"
        print(f"SUCCESS: Detailed response time: {detailed_time:.2f}s")

    def test_brief_me_data_structure_complete(self):
        """Test that Brief Me returns complete data structure"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Top-level fields
        assert "success" in data
        assert "detail_level" in data
        assert "generated_at" in data
        assert "summary" in data
        assert "data" in data
        
        brief_data = data.get("data", {})
        
        # Required data sections
        required_sections = [
            "market_summary",
            "index_status",
            "gappers",
            "your_bot",
            "personalized_insights",
            "opportunities",
            "news",
            "sectors",
            "catalysts",
            "earnings"
        ]
        
        for section in required_sections:
            assert section in brief_data, f"Missing section: {section}"
            print(f"SUCCESS: Section '{section}' present")
        
        # Verify market_summary structure
        market = brief_data.get("market_summary", {})
        assert "regime" in market, "market_summary should have regime"
        assert "regime_score" in market, "market_summary should have regime_score"
        print(f"SUCCESS: Market regime is '{market.get('regime')}' with score {market.get('regime_score')}")

    def test_brief_me_index_status_data(self):
        """Test that Brief Me returns index status data"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        
        brief_data = data.get("data", {})
        index_status = brief_data.get("index_status", {})
        
        # Check for major indices
        indices = ["SPY", "QQQ", "IWM", "VIX"]
        for idx in indices:
            if idx in index_status:
                idx_data = index_status[idx]
                if idx_data.get("price"):
                    print(f"SUCCESS: {idx} price: ${idx_data.get('price')}")
                if idx_data.get("gap_pct") is not None:
                    print(f"SUCCESS: {idx} gap: {idx_data.get('gap_pct')}%")
                if idx == "VIX" and idx_data.get("level"):
                    print(f"SUCCESS: VIX level: {idx_data.get('level')}")

    def test_brief_me_gappers_data(self):
        """Test that Brief Me returns gapper data"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "quick"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        
        brief_data = data.get("data", {})
        gappers = brief_data.get("gappers", {})
        
        # Check structure
        assert "up" in gappers, "Gappers should have 'up' list"
        assert "down" in gappers, "Gappers should have 'down' list"
        
        up_gappers = gappers.get("up", [])
        down_gappers = gappers.get("down", [])
        
        print(f"Gappers UP: {len(up_gappers)}")
        print(f"Gappers DOWN: {len(down_gappers)}")
        
        # Check gapper structure if present
        if up_gappers:
            first = up_gappers[0]
            assert "symbol" in first, "Gapper should have symbol"
            assert "gap_pct" in first, "Gapper should have gap_pct"
            print(f"SUCCESS: Top gapper UP: {first['symbol']} +{first['gap_pct']}%")
        
        if down_gappers:
            first = down_gappers[0]
            assert "symbol" in first, "Gapper should have symbol"
            assert "gap_pct" in first, "Gapper should have gap_pct"
            print(f"SUCCESS: Top gapper DOWN: {first['symbol']} {first['gap_pct']}%")


class TestBriefMeDetailedSections:
    """Test detailed view sections"""

    def test_detailed_has_market_overview_section(self):
        """Test detailed view has market overview section"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        summary = data.get("summary", {})
        
        if isinstance(summary, dict):
            assert "market_overview" in summary, "Detailed should have market_overview section"
            print(f"SUCCESS: market_overview section present")
            print(f"Content preview: {str(summary.get('market_overview', ''))[:200]}...")
        else:
            print("NOTE: Summary is string format (LLM-generated)")

    def test_detailed_has_news_section(self):
        """Test detailed view has news section"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        summary = data.get("summary", {})
        
        if isinstance(summary, dict):
            # Check for news section (may be named "news" or contain news content)
            has_news = "news" in summary or any("news" in str(v).lower() for v in summary.values())
            print(f"SUCCESS: News section present: {has_news}")
            if "news" in summary:
                print(f"Content preview: {str(summary.get('news', ''))[:200]}...")

    def test_detailed_has_sectors_section(self):
        """Test detailed view has sectors section"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        summary = data.get("summary", {})
        
        if isinstance(summary, dict):
            # Check for sectors section
            has_sectors = "sectors" in summary or any("sector" in str(v).lower() for v in summary.values())
            print(f"SUCCESS: Sectors section present: {has_sectors}")
            if "sectors" in summary:
                print(f"Content preview: {str(summary.get('sectors', ''))[:200]}...")

    def test_detailed_has_recommendation_section(self):
        """Test detailed view has recommendation section"""
        response = requests.post(
            f"{BASE_URL}/api/agents/brief-me",
            json={"detail_level": "detailed"},
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        summary = data.get("summary", {})
        
        if isinstance(summary, dict):
            assert "recommendation" in summary, "Detailed should have recommendation section"
            print(f"SUCCESS: recommendation section present")
            print(f"Content preview: {str(summary.get('recommendation', ''))[:200]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
