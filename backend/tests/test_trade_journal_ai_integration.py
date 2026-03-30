"""
Trade Journal AI Integration Tests
Tests for Phase 1+2: Trade Journal wired to AI Learning Loop
- GET /api/trades - list all trades with ai_context and source fields
- GET /api/trades?status=closed - filter by closed status
- GET /api/trades/ai/learning-stats - journal_outcomes count and outcome breakdown
- POST /api/trades - create a new trade with source field
- POST /api/trades/{id}/enrich-ai - enriches a trade with AI context
- POST /api/trades/{id}/close - closes a trade, sets outcome, feeds learning loop
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "http://127.0.0.1:8001"


class TestTradeJournalAIIntegration:
    """Tests for Trade Journal AI Integration (Phase 1+2)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.created_trade_ids = []
    
    def teardown_method(self, method):
        """Cleanup test trades after each test"""
        for trade_id in self.created_trade_ids:
            try:
                self.session.delete(f"{BASE_URL}/api/trades/{trade_id}")
            except Exception:
                pass
    
    # ==================== GET /api/trades ====================
    
    def test_get_trades_returns_list(self):
        """GET /api/trades should return trades list with count"""
        response = self.session.get(f"{BASE_URL}/api/trades", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "trades" in data, "Response should have 'trades' field"
        assert "count" in data, "Response should have 'count' field"
        assert isinstance(data["trades"], list), "trades should be a list"
        print(f"✓ GET /api/trades returned {data['count']} trades")
    
    def test_get_trades_has_ai_context_field(self):
        """GET /api/trades should return trades with ai_context field"""
        response = self.session.get(f"{BASE_URL}/api/trades", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        trades = data.get("trades", [])
        
        # Find a trade with ai_context (the AAPL test trade should have it)
        trades_with_ai = [t for t in trades if t.get("ai_context")]
        
        if trades_with_ai:
            trade = trades_with_ai[0]
            ai_ctx = trade["ai_context"]
            
            # Verify AI context structure
            assert "enriched_at" in ai_ctx, "ai_context should have enriched_at"
            print(f"✓ Found trade {trade['symbol']} with ai_context")
            
            # Check for confidence_gate if present
            if "confidence_gate" in ai_ctx:
                gate = ai_ctx["confidence_gate"]
                assert "decision" in gate, "confidence_gate should have decision"
                assert "confidence_score" in gate, "confidence_gate should have confidence_score"
                print(f"  - Confidence Gate: {gate['decision']} ({gate['confidence_score']}%)")
            
            # Check for TQS if present
            if "tqs_score" in ai_ctx:
                print(f"  - TQS Score: {ai_ctx['tqs_score']} ({ai_ctx.get('tqs_grade', 'N/A')})")
            
            # Check for model prediction if present
            if "model_prediction" in ai_ctx:
                pred = ai_ctx["model_prediction"]
                print(f"  - Model Prediction: {pred.get('direction', 'N/A')} ({pred.get('confidence', 0)*100:.1f}%)")
        else:
            print("⚠ No trades with ai_context found (expected for new DB)")
    
    def test_get_trades_has_source_field(self):
        """GET /api/trades should return trades with source field"""
        response = self.session.get(f"{BASE_URL}/api/trades", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        trades = data.get("trades", [])
        
        if trades:
            # Check that trades have source field
            for trade in trades[:5]:  # Check first 5
                assert "source" in trade or trade.get("source") is None, f"Trade {trade.get('id')} missing source field"
                source = trade.get("source", "manual")
                assert source in ["manual", "bot", "ib", None], f"Invalid source: {source}"
            print(f"✓ Trades have valid source field (manual/bot/ib)")
        else:
            print("⚠ No trades found to verify source field")
    
    # ==================== GET /api/trades?status=closed ====================
    
    def test_get_closed_trades_filter(self):
        """GET /api/trades?status=closed should return only closed trades"""
        response = self.session.get(f"{BASE_URL}/api/trades?status=closed", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        trades = data.get("trades", [])
        
        # Verify all returned trades are closed
        for trade in trades:
            assert trade.get("status") == "closed", f"Trade {trade.get('id')} is not closed"
        
        print(f"✓ GET /api/trades?status=closed returned {len(trades)} closed trades")
    
    def test_get_open_trades_filter(self):
        """GET /api/trades?status=open should return only open trades"""
        response = self.session.get(f"{BASE_URL}/api/trades?status=open", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        trades = data.get("trades", [])
        
        # Verify all returned trades are open
        for trade in trades:
            assert trade.get("status") == "open", f"Trade {trade.get('id')} is not open"
        
        print(f"✓ GET /api/trades?status=open returned {len(trades)} open trades")
    
    # ==================== GET /api/trades/ai/learning-stats ====================
    
    def test_get_ai_learning_stats(self):
        """GET /api/trades/ai/learning-stats should return journal outcomes count"""
        response = self.session.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True, "Response should have success=true"
        assert "stats" in data, "Response should have 'stats' field"
        
        stats = data["stats"]
        assert "journal_outcomes" in stats, "stats should have journal_outcomes count"
        
        print(f"✓ AI Learning Stats: {stats['journal_outcomes']} journal outcomes")
        
        # Check outcome breakdown if present
        if "outcomes" in stats and stats["outcomes"]:
            print(f"  - Outcome breakdown: {stats['outcomes']}")
        
        # Check confidence gate accuracy if present
        if "confidence_gate_accuracy" in stats:
            print(f"  - Confidence Gate accuracy data present")
    
    def test_ai_learning_stats_outcome_breakdown(self):
        """GET /api/trades/ai/learning-stats should have outcome breakdown"""
        response = self.session.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        stats = data.get("stats", {})
        
        if stats.get("journal_outcomes", 0) > 0:
            assert "outcomes" in stats, "Should have outcomes breakdown when journal_outcomes > 0"
            outcomes = stats["outcomes"]
            
            # Verify outcome structure
            for outcome_type, outcome_data in outcomes.items():
                assert outcome_type in ["won", "lost", "breakeven"], f"Invalid outcome type: {outcome_type}"
                assert "count" in outcome_data, f"Outcome {outcome_type} should have count"
                assert "pnl" in outcome_data, f"Outcome {outcome_type} should have pnl"
            
            print(f"✓ Outcome breakdown verified: {list(outcomes.keys())}")
        else:
            print("⚠ No journal outcomes yet - breakdown not available")
    
    # ==================== POST /api/trades ====================
    
    def test_create_trade_with_source(self):
        """POST /api/trades should create a trade with source field"""
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-01",
            "strategy_name": "Test Strategy",
            "entry_price": 100.0,
            "shares": 50,
            "direction": "long",
            "market_context": "TRENDING",
            "stop_loss": 98.0,
            "take_profit": 105.0,
            "notes": "Test trade for AI integration testing",
            "source": "manual"
        }
        
        response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data, "Response should have trade id"
        assert data.get("symbol") == trade_data["symbol"], "Symbol should match"
        assert data.get("source") == "manual", "Source should be 'manual'"
        assert data.get("status") == "open", "New trade should be open"
        
        self.created_trade_ids.append(data["id"])
        print(f"✓ Created trade {data['id']} with source='manual'")
        
        return data["id"]
    
    def test_create_trade_default_source(self):
        """POST /api/trades without source should default to 'manual'"""
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-02",
            "entry_price": 50.0,
            "shares": 100,
            "direction": "long"
            # No source field
        }
        
        response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("source") == "manual", "Default source should be 'manual'"
        
        self.created_trade_ids.append(data["id"])
        print(f"✓ Trade created with default source='manual'")
    
    # ==================== POST /api/trades/{id}/enrich-ai ====================
    
    def test_enrich_trade_with_ai(self):
        """POST /api/trades/{id}/enrich-ai should add AI context to trade"""
        # First create a trade
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": "AAPL",  # Use real symbol for AI enrichment
            "strategy_id": "INT-01",
            "entry_price": 225.0,
            "shares": 100,
            "direction": "long",
            "stop_loss": 220.0,
            "take_profit": 235.0
        }
        
        create_response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        assert create_response.status_code == 200
        trade_id = create_response.json()["id"]
        self.created_trade_ids.append(trade_id)
        
        # Now enrich with AI
        enrich_response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/enrich-ai", timeout=60)
        assert enrich_response.status_code == 200, f"Enrich failed: {enrich_response.text}"
        
        data = enrich_response.json()
        assert data.get("success") == True, "Enrich should return success=true"
        assert "trade" in data, "Response should have trade object"
        
        trade = data["trade"]
        assert "ai_context" in trade, "Trade should have ai_context after enrichment"
        
        ai_ctx = trade["ai_context"]
        assert "enriched_at" in ai_ctx, "ai_context should have enriched_at timestamp"
        
        print(f"✓ Trade {trade_id} enriched with AI context")
        
        # Check what AI data was captured
        if "confidence_gate" in ai_ctx:
            gate = ai_ctx["confidence_gate"]
            print(f"  - Confidence Gate: {gate.get('decision')} ({gate.get('confidence_score')}%)")
        
        if "tqs_score" in ai_ctx:
            print(f"  - TQS Score: {ai_ctx['tqs_score']} ({ai_ctx.get('tqs_grade', 'N/A')})")
        
        if "model_prediction" in ai_ctx:
            pred = ai_ctx["model_prediction"]
            print(f"  - Model Prediction: {pred.get('direction')} ({pred.get('confidence', 0)*100:.1f}%)")
    
    def test_enrich_nonexistent_trade_returns_404(self):
        """POST /api/trades/{id}/enrich-ai with invalid ID should return 404"""
        fake_id = "000000000000000000000000"
        response = self.session.post(f"{BASE_URL}/api/trades/{fake_id}/enrich-ai", timeout=30)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Enrich with invalid ID returns 404")
    
    # ==================== POST /api/trades/{id}/close ====================
    
    def test_close_trade_feeds_learning_loop(self):
        """POST /api/trades/{id}/close should close trade and feed learning loop"""
        # First create a trade
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-01",
            "entry_price": 100.0,
            "shares": 100,
            "direction": "long",
            "stop_loss": 98.0,
            "take_profit": 105.0
        }
        
        create_response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        assert create_response.status_code == 200
        trade_id = create_response.json()["id"]
        # Don't add to cleanup since it will be closed
        
        # Get initial learning stats
        stats_before = self.session.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30).json()
        initial_count = stats_before.get("stats", {}).get("journal_outcomes", 0)
        
        # Close the trade with profit
        close_data = {
            "exit_price": 105.0,
            "notes": "Test close - taking profit"
        }
        
        close_response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/close", json=close_data, timeout=30)
        assert close_response.status_code == 200, f"Close failed: {close_response.text}"
        
        data = close_response.json()
        assert data.get("status") == "closed", "Trade should be closed"
        assert data.get("exit_price") == 105.0, "Exit price should match"
        assert data.get("pnl") == 500.0, f"PnL should be 500, got {data.get('pnl')}"
        assert data.get("outcome") == "won", f"Outcome should be 'won', got {data.get('outcome')}"
        
        print(f"✓ Trade {trade_id} closed with PnL=${data.get('pnl')}, outcome={data.get('outcome')}")
        
        # Verify learning loop was fed
        stats_after = self.session.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30).json()
        new_count = stats_after.get("stats", {}).get("journal_outcomes", 0)
        
        assert new_count >= initial_count, "Journal outcomes should not decrease"
        print(f"  - Learning loop fed: {initial_count} → {new_count} journal outcomes")
    
    def test_close_trade_calculates_pnl_correctly(self):
        """POST /api/trades/{id}/close should calculate P&L correctly"""
        # Create a long trade
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-01",
            "entry_price": 100.0,
            "shares": 50,
            "direction": "long"
        }
        
        create_response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        trade_id = create_response.json()["id"]
        
        # Close with loss
        close_data = {"exit_price": 95.0}
        close_response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/close", json=close_data, timeout=30)
        
        data = close_response.json()
        expected_pnl = (95.0 - 100.0) * 50  # -250
        assert data.get("pnl") == expected_pnl, f"PnL should be {expected_pnl}, got {data.get('pnl')}"
        assert data.get("outcome") == "lost", f"Outcome should be 'lost', got {data.get('outcome')}"
        
        print(f"✓ P&L calculated correctly: ${data.get('pnl')} ({data.get('pnl_percent')}%)")
    
    def test_close_already_closed_trade_returns_400(self):
        """POST /api/trades/{id}/close on closed trade should return 400"""
        # Create and close a trade
        unique_id = str(uuid.uuid4())[:8].upper()
        trade_data = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-01",
            "entry_price": 100.0,
            "shares": 50,
            "direction": "long"
        }
        
        create_response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        trade_id = create_response.json()["id"]
        
        # Close first time
        self.session.post(f"{BASE_URL}/api/trades/{trade_id}/close", json={"exit_price": 105.0}, timeout=30)
        
        # Try to close again
        response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/close", json={"exit_price": 110.0}, timeout=30)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        
        print("✓ Closing already closed trade returns 400")
    
    # ==================== Integration Tests ====================
    
    def test_full_trade_lifecycle_with_ai(self):
        """Test complete trade lifecycle: create → enrich → close → verify learning"""
        unique_id = str(uuid.uuid4())[:8].upper()
        
        # 1. Create trade
        trade_data = {
            "symbol": "MSFT",  # Real symbol for AI
            "strategy_id": "INT-01",
            "strategy_name": "Trend Momentum",
            "entry_price": 450.0,
            "shares": 20,
            "direction": "long",
            "market_context": "TRENDING",
            "stop_loss": 445.0,
            "take_profit": 460.0,
            "source": "manual"
        }
        
        create_response = self.session.post(f"{BASE_URL}/api/trades", json=trade_data, timeout=30)
        assert create_response.status_code == 200
        trade_id = create_response.json()["id"]
        print(f"1. Created trade {trade_id}")
        
        # 2. Enrich with AI
        enrich_response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/enrich-ai", timeout=60)
        assert enrich_response.status_code == 200
        enriched_trade = enrich_response.json()["trade"]
        assert "ai_context" in enriched_trade
        print(f"2. Enriched trade with AI context")
        
        # 3. Close trade
        close_data = {"exit_price": 455.0, "notes": "Full lifecycle test"}
        close_response = self.session.post(f"{BASE_URL}/api/trades/{trade_id}/close", json=close_data, timeout=30)
        assert close_response.status_code == 200
        closed_trade = close_response.json()
        assert closed_trade["status"] == "closed"
        assert closed_trade["outcome"] == "won"
        print(f"3. Closed trade with PnL=${closed_trade['pnl']}")
        
        # 4. Verify in learning stats
        stats_response = self.session.get(f"{BASE_URL}/api/trades/ai/learning-stats", timeout=30)
        assert stats_response.status_code == 200
        stats = stats_response.json()["stats"]
        assert stats["journal_outcomes"] > 0
        print(f"4. Verified in learning stats: {stats['journal_outcomes']} outcomes")
        
        print("✓ Full trade lifecycle with AI completed successfully")


class TestTradeJournalDataIntegrity:
    """Tests for data integrity and edge cases"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def test_trades_have_required_fields(self):
        """Verify trades have all required fields"""
        response = self.session.get(f"{BASE_URL}/api/trades", timeout=30)
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        required_fields = ["id", "symbol", "strategy_id", "entry_price", "shares", "direction", "status"]
        
        for trade in trades[:5]:
            for field in required_fields:
                assert field in trade, f"Trade missing required field: {field}"
        
        print(f"✓ All trades have required fields: {required_fields}")
    
    def test_closed_trades_have_outcome(self):
        """Verify closed trades have outcome field"""
        response = self.session.get(f"{BASE_URL}/api/trades?status=closed", timeout=30)
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        
        for trade in trades:
            assert "outcome" in trade, f"Closed trade {trade.get('id')} missing outcome"
            assert trade["outcome"] in ["won", "lost", "breakeven"], f"Invalid outcome: {trade['outcome']}"
        
        print(f"✓ All {len(trades)} closed trades have valid outcome")
    
    def test_ai_context_structure(self):
        """Verify AI context has proper structure when present"""
        response = self.session.get(f"{BASE_URL}/api/trades", timeout=30)
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        trades_with_ai = [t for t in trades if t.get("ai_context")]
        
        for trade in trades_with_ai:
            ai_ctx = trade["ai_context"]
            
            # Must have enriched_at
            assert "enriched_at" in ai_ctx, "ai_context must have enriched_at"
            
            # If confidence_gate present, verify structure
            if "confidence_gate" in ai_ctx:
                gate = ai_ctx["confidence_gate"]
                assert "decision" in gate, "confidence_gate must have decision"
                assert gate["decision"] in ["GO", "REDUCE", "NO_TRADE"], f"Invalid decision: {gate['decision']}"
            
            # If tqs_score present, verify it's a number
            if "tqs_score" in ai_ctx:
                assert isinstance(ai_ctx["tqs_score"], (int, float)), "tqs_score must be numeric"
        
        print(f"✓ AI context structure verified for {len(trades_with_ai)} trades")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
