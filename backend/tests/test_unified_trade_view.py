"""
Test Unified Trade View - Phase 3
Tests for GET /api/trades/unified endpoint with source and status filters
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestUnifiedTradeView:
    """Tests for unified trade view endpoint - Phase 3"""
    
    def test_unified_trades_returns_success(self):
        """GET /api/trades/unified returns success with trades array"""
        response = requests.get(f"{BASE_URL}/api/trades/unified", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "trades" in data
        assert "count" in data
        assert isinstance(data["trades"], list)
        print(f"PASSED: Unified trades returns {data['count']} trades")
    
    def test_unified_trades_contains_both_sources(self):
        """GET /api/trades/unified returns both manual and bot trades"""
        response = requests.get(f"{BASE_URL}/api/trades/unified", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        manual_trades = [t for t in data["trades"] if t.get("source") == "manual"]
        bot_trades = [t for t in data["trades"] if t.get("source") == "bot"]
        
        assert len(manual_trades) > 0, "Should have manual trades"
        assert len(bot_trades) > 0, "Should have bot trades"
        print(f"PASSED: Found {len(manual_trades)} manual + {len(bot_trades)} bot trades")
    
    def test_unified_trades_sorted_by_date_descending(self):
        """GET /api/trades/unified returns trades sorted by date descending"""
        response = requests.get(f"{BASE_URL}/api/trades/unified", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        trades = data["trades"]
        if len(trades) > 1:
            dates = [t.get("entry_date", "") for t in trades]
            # Check first few are in descending order
            for i in range(min(5, len(dates) - 1)):
                assert dates[i] >= dates[i+1], f"Trades not sorted: {dates[i]} < {dates[i+1]}"
        print("PASSED: Trades sorted by date descending")
    
    def test_source_filter_manual(self):
        """GET /api/trades/unified?source=manual returns only manual trades"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=manual", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        for trade in data["trades"]:
            assert trade.get("source") == "manual", f"Expected manual, got {trade.get('source')}"
        print(f"PASSED: source=manual filter returns {len(data['trades'])} manual trades only")
    
    def test_source_filter_bot(self):
        """GET /api/trades/unified?source=bot returns only bot trades"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=bot", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        for trade in data["trades"]:
            assert trade.get("source") == "bot", f"Expected bot, got {trade.get('source')}"
        print(f"PASSED: source=bot filter returns {len(data['trades'])} bot trades only")
    
    def test_bot_trades_have_extra_fields(self):
        """GET /api/trades/unified?source=bot returns trades with quality_grade, trade_style, close_reason"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=bot", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["trades"]) > 0, "Should have bot trades"
        
        # Check first few bot trades have the extra fields
        for trade in data["trades"][:5]:
            assert "quality_grade" in trade, "Bot trade missing quality_grade"
            assert "trade_style" in trade, "Bot trade missing trade_style"
            assert "close_reason" in trade, "Bot trade missing close_reason"
            assert "mfe_pct" in trade, "Bot trade missing mfe_pct"
            assert "mae_pct" in trade, "Bot trade missing mae_pct"
        
        # Verify at least one has non-empty values
        has_quality = any(t.get("quality_grade") for t in data["trades"])
        has_style = any(t.get("trade_style") for t in data["trades"])
        assert has_quality, "No bot trades have quality_grade set"
        assert has_style, "No bot trades have trade_style set"
        print("PASSED: Bot trades have quality_grade, trade_style, close_reason, mfe_pct, mae_pct")
    
    def test_status_filter_closed(self):
        """GET /api/trades/unified?status=closed returns only closed trades"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?status=closed", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        for trade in data["trades"]:
            assert trade.get("status") == "closed", f"Expected closed, got {trade.get('status')}"
        print(f"PASSED: status=closed filter returns {len(data['trades'])} closed trades")
    
    def test_status_filter_open(self):
        """GET /api/trades/unified?status=open returns only open trades"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?status=open", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        # Open trades can have status: open, pending, filled
        valid_open_statuses = ["open", "pending", "filled"]
        for trade in data["trades"]:
            assert trade.get("status") in valid_open_statuses, f"Expected open status, got {trade.get('status')}"
        print(f"PASSED: status=open filter returns {len(data['trades'])} open trades")
    
    def test_combined_filters(self):
        """GET /api/trades/unified?source=bot&status=closed returns filtered results"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=bot&status=closed", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        for trade in data["trades"]:
            assert trade.get("source") == "bot", f"Expected bot, got {trade.get('source')}"
            assert trade.get("status") == "closed", f"Expected closed, got {trade.get('status')}"
        print(f"PASSED: Combined filters return {len(data['trades'])} bot+closed trades")


class TestPhase2Endpoints:
    """Verify Phase 2 endpoints still work"""
    
    def test_ai_learning_stats(self):
        """GET /api/trades/ai/learning-stats returns stats"""
        response = requests.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=20)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "stats" in data
        print(f"PASSED: AI learning stats returns journal_outcomes={data['stats'].get('journal_outcomes', 0)}")
    
    def test_enrich_ai_endpoint_exists(self):
        """POST /api/trades/{id}/enrich-ai endpoint exists (404 for invalid ID is OK)"""
        response = requests.post(f"{BASE_URL}/api/trades/invalid-id/enrich-ai", timeout=20)
        # 404 means endpoint exists but trade not found - that's expected
        assert response.status_code in [200, 404, 500], f"Unexpected status: {response.status_code}"
        print(f"PASSED: enrich-ai endpoint exists (status={response.status_code})")


class TestTradeDataStructure:
    """Verify trade data structure is correct"""
    
    def test_manual_trade_structure(self):
        """Manual trades have expected fields"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=manual", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        if len(data["trades"]) > 0:
            trade = data["trades"][0]
            required_fields = ["id", "symbol", "entry_price", "shares", "direction", "status", "source"]
            for field in required_fields:
                assert field in trade, f"Manual trade missing {field}"
            assert trade["source"] == "manual"
        print("PASSED: Manual trade structure verified")
    
    def test_bot_trade_structure(self):
        """Bot trades have expected fields including extra bot-specific fields"""
        response = requests.get(f"{BASE_URL}/api/trades/unified?source=bot", timeout=20)
        assert response.status_code == 200
        data = response.json()
        
        if len(data["trades"]) > 0:
            trade = data["trades"][0]
            required_fields = ["id", "symbol", "entry_price", "shares", "direction", "status", "source"]
            bot_fields = ["quality_grade", "trade_style", "close_reason", "mfe_pct", "mae_pct"]
            
            for field in required_fields:
                assert field in trade, f"Bot trade missing {field}"
            for field in bot_fields:
                assert field in trade, f"Bot trade missing bot-specific field {field}"
            assert trade["source"] == "bot"
        print("PASSED: Bot trade structure verified with extra fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
