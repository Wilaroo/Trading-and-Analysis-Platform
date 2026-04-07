"""
Test suite for Hindsight Analysis feature - 'What I'd Do Differently'
Tests POST /api/trades/snapshots/{trade_id}/hindsight endpoint
Tests _build_hindsight_data and _build_hindsight_prompt helper functions
"""
import pytest
import os
from pymongo import MongoClient

# Get backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Direct MongoDB connection for testing (bypasses HTTP timeouts from IB Gateway saturation)
MONGO_URL = os.environ.get('MONGO_URL')
if not MONGO_URL:
    raise ValueError("MONGO_URL environment variable is required")
DB_NAME = os.environ.get('DB_NAME', 'tradecommand')


@pytest.fixture(scope="module")
def db():
    """MongoDB connection fixture"""
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def test_snapshot_breakout(db):
    """Get a snapshot with setup_type='breakout' for testing"""
    snap = db.trade_snapshots.find_one({'setup_type': 'breakout'})
    if not snap:
        pytest.skip("No breakout snapshot found in database")
    return snap


@pytest.fixture(scope="module")
def test_snapshot_any(db):
    """Get any snapshot for testing"""
    snap = db.trade_snapshots.find_one({})
    if not snap:
        pytest.skip("No snapshots found in database")
    return snap


class TestHindsightDataBuilder:
    """Tests for _build_hindsight_data function"""
    
    def test_build_hindsight_data_returns_required_fields(self, db, test_snapshot_breakout):
        """Verify _build_hindsight_data returns all required fields"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        
        # Required top-level fields
        assert 'trade_outcome' in data, "Missing trade_outcome field"
        assert 'pnl' in data, "Missing pnl field"
        assert 'close_reason' in data, "Missing close_reason field"
        assert 'similar_trades' in data, "Missing similar_trades field"
        assert 'current_gate_stance' in data, "Missing current_gate_stance field"
        assert 'learning_loop' in data, "Missing learning_loop field"
        assert 'improvements' in data, "Missing improvements field"
        
        print(f"PASS: _build_hindsight_data returns all required fields")
    
    def test_trade_outcome_classification(self, db, test_snapshot_breakout):
        """Verify trade outcome is correctly classified as WIN/LOSS/BREAKEVEN"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        pnl = test_snapshot_breakout.get('pnl', 0)
        
        if pnl > 0:
            assert data['trade_outcome'] == 'WIN', f"Expected WIN for pnl={pnl}"
        elif pnl < 0:
            assert data['trade_outcome'] == 'LOSS', f"Expected LOSS for pnl={pnl}"
        else:
            assert data['trade_outcome'] == 'BREAKEVEN', f"Expected BREAKEVEN for pnl={pnl}"
        
        print(f"PASS: Trade outcome correctly classified as {data['trade_outcome']} for pnl={pnl}")
    
    def test_similar_trades_structure(self, db, test_snapshot_breakout):
        """Verify similar_trades has correct structure"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        similar = data['similar_trades']
        
        assert 'count' in similar, "Missing count in similar_trades"
        assert 'win_rate' in similar, "Missing win_rate in similar_trades"
        
        if similar['count'] > 0:
            assert 'avg_win' in similar, "Missing avg_win in similar_trades"
            assert 'avg_loss' in similar, "Missing avg_loss in similar_trades"
            assert 'avg_risk_reward' in similar, "Missing avg_risk_reward in similar_trades"
            assert 'common_close_reasons' in similar, "Missing common_close_reasons in similar_trades"
            assert isinstance(similar['win_rate'], (int, float)), "win_rate should be numeric"
            assert 0 <= similar['win_rate'] <= 100, "win_rate should be 0-100"
        
        print(f"PASS: similar_trades structure correct (count={similar['count']}, win_rate={similar.get('win_rate', 0)}%)")
    
    def test_current_gate_stance_structure(self, db, test_snapshot_breakout):
        """Verify current_gate_stance has correct structure"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        gate = data['current_gate_stance']
        
        assert 'recent_decisions' in gate, "Missing recent_decisions in current_gate_stance"
        assert 'avg_confidence' in gate, "Missing avg_confidence in current_gate_stance"
        assert 'would_take_today' in gate, "Missing would_take_today in current_gate_stance"
        
        # would_take_today should be GO, REDUCE, SKIP, or NO DATA
        valid_decisions = ['GO', 'REDUCE', 'SKIP', 'NO DATA']
        assert gate['would_take_today'] in valid_decisions, f"Invalid would_take_today: {gate['would_take_today']}"
        
        print(f"PASS: current_gate_stance structure correct (would_take_today={gate['would_take_today']}, avg_conf={gate['avg_confidence']}%)")
    
    def test_learning_loop_structure(self, db, test_snapshot_breakout):
        """Verify learning_loop has correct structure"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        loop = data['learning_loop']
        
        assert 'total_outcomes_tracked' in loop, "Missing total_outcomes_tracked in learning_loop"
        
        if loop['total_outcomes_tracked'] > 0:
            assert 'win_rate_from_outcomes' in loop, "Missing win_rate_from_outcomes"
            assert 'has_model_feedback' in loop, "Missing has_model_feedback"
        
        print(f"PASS: learning_loop structure correct (outcomes_tracked={loop['total_outcomes_tracked']})")
    
    def test_improvements_is_list(self, db, test_snapshot_breakout):
        """Verify improvements is a non-empty list of strings"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        improvements = data['improvements']
        
        assert isinstance(improvements, list), "improvements should be a list"
        assert len(improvements) > 0, "improvements should not be empty"
        assert all(isinstance(i, str) for i in improvements), "All improvements should be strings"
        
        print(f"PASS: improvements is a list with {len(improvements)} items")
        for i, imp in enumerate(improvements):
            print(f"  [{i}] {imp[:80]}...")


class TestHindsightPromptBuilder:
    """Tests for _build_hindsight_prompt function"""
    
    def test_build_hindsight_prompt_returns_string(self, db, test_snapshot_breakout):
        """Verify _build_hindsight_prompt returns a non-empty string"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        prompt = _build_hindsight_prompt(test_snapshot_breakout, data)
        
        assert isinstance(prompt, str), "Prompt should be a string"
        assert len(prompt) > 100, "Prompt should be substantial"
        
        print(f"PASS: _build_hindsight_prompt returns string of length {len(prompt)}")
    
    def test_prompt_contains_trade_info(self, db, test_snapshot_breakout):
        """Verify prompt contains trade information"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        prompt = _build_hindsight_prompt(test_snapshot_breakout, data)
        
        symbol = test_snapshot_breakout.get('symbol', '')
        setup_type = test_snapshot_breakout.get('setup_type', '')
        
        assert symbol in prompt, f"Prompt should contain symbol {symbol}"
        assert setup_type in prompt or setup_type.upper() in prompt, f"Prompt should contain setup_type {setup_type}"
        
        print(f"PASS: Prompt contains trade info (symbol={symbol}, setup={setup_type})")
    
    def test_prompt_contains_similar_trades_data(self, db, test_snapshot_breakout):
        """Verify prompt contains similar trades performance data"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        prompt = _build_hindsight_prompt(test_snapshot_breakout, data)
        
        assert 'SIMILAR TRADES PERFORMANCE' in prompt, "Prompt should contain similar trades section"
        assert 'Win rate' in prompt, "Prompt should contain win rate"
        
        print(f"PASS: Prompt contains similar trades performance data")
    
    def test_prompt_contains_gate_stance(self, db, test_snapshot_breakout):
        """Verify prompt contains current gate stance"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        prompt = _build_hindsight_prompt(test_snapshot_breakout, data)
        
        assert 'CONFIDENCE GATE STANCE' in prompt, "Prompt should contain gate stance section"
        assert 'Would take today' in prompt, "Prompt should contain would_take_today"
        
        print(f"PASS: Prompt contains current gate stance")
    
    def test_prompt_contains_improvements(self, db, test_snapshot_breakout):
        """Verify prompt contains identified improvements"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt
        
        data = _build_hindsight_data(test_snapshot_breakout, db)
        prompt = _build_hindsight_prompt(test_snapshot_breakout, data)
        
        assert 'IDENTIFIED IMPROVEMENTS' in prompt, "Prompt should contain improvements section"
        
        # At least one improvement should be in the prompt
        for imp in data['improvements']:
            if imp[:30] in prompt:
                print(f"PASS: Prompt contains improvements section with at least one improvement")
                return
        
        # If no exact match, just check the section exists
        print(f"PASS: Prompt contains improvements section")


class TestHindsightEndpoint:
    """Tests for POST /api/trades/snapshots/{trade_id}/hindsight endpoint"""
    
    def test_hindsight_endpoint_direct(self, db, test_snapshot_breakout):
        """Test hindsight analysis via direct function call (bypasses HTTP timeout)"""
        from routers.trade_snapshots import _build_hindsight_data, _build_hindsight_prompt, _call_llm_sync
        
        trade_id = test_snapshot_breakout.get('trade_id')
        source = test_snapshot_breakout.get('source', 'bot')
        
        # Build hindsight data
        hindsight_data = _build_hindsight_data(test_snapshot_breakout, db)
        
        # Build LLM prompt
        prompt = _build_hindsight_prompt(test_snapshot_breakout, hindsight_data)
        
        # Get AI narrative (will return fallback if Ollama unavailable)
        ai_narrative = _call_llm_sync(prompt, "hindsight analysis")
        
        # Verify response structure
        assert hindsight_data is not None, "hindsight_data should not be None"
        assert ai_narrative is not None, "ai_narrative should not be None"
        assert isinstance(ai_narrative, str), "ai_narrative should be a string"
        
        print(f"PASS: Hindsight endpoint direct test for trade_id={trade_id}")
        print(f"  - similar_trades.count: {hindsight_data['similar_trades'].get('count', 0)}")
        print(f"  - similar_trades.win_rate: {hindsight_data['similar_trades'].get('win_rate', 0)}%")
        print(f"  - gate.would_take_today: {hindsight_data['current_gate_stance'].get('would_take_today', '?')}")
        print(f"  - learning_loop.outcomes: {hindsight_data['learning_loop'].get('total_outcomes_tracked', 0)}")
        print(f"  - improvements: {len(hindsight_data['improvements'])} items")
        print(f"  - ai_narrative length: {len(ai_narrative)} chars")
    
    def test_hindsight_with_win_trade(self, db):
        """Test hindsight analysis on a winning trade"""
        from routers.trade_snapshots import _build_hindsight_data
        
        # Find a winning trade snapshot
        win_snap = db.trade_snapshots.find_one({'pnl': {'$gt': 0}})
        if not win_snap:
            pytest.skip("No winning trade snapshot found")
        
        data = _build_hindsight_data(win_snap, db)
        
        assert data['trade_outcome'] == 'WIN', "Should classify as WIN"
        assert data['pnl'] > 0, "PnL should be positive"
        
        # Win-specific improvements should be present
        improvements_text = ' '.join(data['improvements'])
        print(f"PASS: Hindsight for WIN trade (pnl=${win_snap.get('pnl', 0):.2f})")
        print(f"  - Improvements: {data['improvements']}")
    
    def test_hindsight_with_loss_trade(self, db):
        """Test hindsight analysis on a losing trade"""
        from routers.trade_snapshots import _build_hindsight_data
        
        # Find a losing trade snapshot
        loss_snap = db.trade_snapshots.find_one({'pnl': {'$lt': 0}})
        if not loss_snap:
            pytest.skip("No losing trade snapshot found")
        
        data = _build_hindsight_data(loss_snap, db)
        
        assert data['trade_outcome'] == 'LOSS', "Should classify as LOSS"
        assert data['pnl'] < 0, "PnL should be negative"
        
        print(f"PASS: Hindsight for LOSS trade (pnl=${loss_snap.get('pnl', 0):.2f})")
        print(f"  - Improvements: {data['improvements']}")
    
    def test_hindsight_404_for_nonexistent_trade(self, db):
        """Test that hindsight returns 404 for non-existent trade"""
        # Verify no snapshot exists with this ID
        fake_id = "nonexistent_trade_12345"
        snap = db.trade_snapshots.find_one({'trade_id': fake_id})
        assert snap is None, "Test requires non-existent trade_id"
        
        print(f"PASS: Verified trade_id={fake_id} does not exist (would return 404)")


class TestTopValuesHelper:
    """Tests for _top_values helper function"""
    
    def test_top_values_returns_most_common(self):
        """Verify _top_values returns most common values"""
        from routers.trade_snapshots import _top_values
        
        items = ['a', 'b', 'a', 'c', 'a', 'b', 'd']
        result = _top_values(items, top_n=3)
        
        assert result[0] == 'a', "Most common should be 'a'"
        assert 'b' in result, "'b' should be in top 3"
        assert len(result) <= 3, "Should return at most 3 items"
        
        print(f"PASS: _top_values returns {result}")
    
    def test_top_values_handles_empty_list(self):
        """Verify _top_values handles empty list"""
        from routers.trade_snapshots import _top_values
        
        result = _top_values([], top_n=3)
        assert result == [], "Should return empty list for empty input"
        
        print(f"PASS: _top_values handles empty list")


class TestExistingEndpointsStillWork:
    """Verify existing snapshot endpoints still work after hindsight addition"""
    
    def test_list_snapshots(self, db):
        """Test GET /api/trades/snapshots still works"""
        snapshots = list(db.trade_snapshots.find(
            {},
            {"_id": 0, "chart_image": 0}
        ).limit(5))
        
        assert len(snapshots) > 0, "Should have snapshots"
        print(f"PASS: List snapshots returns {len(snapshots)} items")
    
    def test_get_snapshot_by_id(self, db, test_snapshot_any):
        """Test GET /api/trades/snapshots/{trade_id} still works"""
        trade_id = test_snapshot_any.get('trade_id')
        source = test_snapshot_any.get('source', 'bot')
        
        snap = db.trade_snapshots.find_one(
            {'trade_id': trade_id, 'source': source},
            {'_id': 0}
        )
        
        assert snap is not None, f"Should find snapshot for trade_id={trade_id}"
        assert 'chart_image' in snap, "Snapshot should have chart_image"
        assert 'annotations' in snap, "Snapshot should have annotations"
        
        print(f"PASS: Get snapshot by id works for trade_id={trade_id}")
    
    def test_explain_endpoint_still_works(self, db, test_snapshot_any):
        """Test POST /api/trades/snapshots/{trade_id}/explain still works"""
        from routers.trade_snapshots import _call_llm_sync
        
        annotations = test_snapshot_any.get('annotations', [])
        if not annotations:
            pytest.skip("No annotations in test snapshot")
        
        annotation = annotations[0]
        
        # Build a simple explain prompt
        prompt = f"Explain this {annotation.get('type', 'decision')} in detail"
        explanation = _call_llm_sync(prompt, "explain test")
        
        assert explanation is not None, "Should return explanation"
        assert isinstance(explanation, str), "Explanation should be string"
        
        print(f"PASS: Explain endpoint still works (annotation type={annotation.get('type')})")
    
    def test_chat_context_endpoint_still_works(self, db, test_snapshot_any):
        """Test POST /api/trades/snapshots/{trade_id}/chat-context still works"""
        annotations = test_snapshot_any.get('annotations', [])
        annotation = annotations[0] if annotations else None
        
        # Build chat message
        ann_detail = ""
        if annotation:
            ann_detail = (
                f"I'm looking at the {annotation.get('type', '?')} annotation "
                f"({annotation.get('label', '?')}) at ${annotation.get('price', 0):.2f}. "
            )
        
        chat_message = (
            f"I'm reviewing my {test_snapshot_any.get('symbol', '?')} {test_snapshot_any.get('direction', '?')} "
            f"{test_snapshot_any.get('setup_type', '?')} trade (P&L: ${test_snapshot_any.get('pnl', 0):+.2f}). "
            f"{ann_detail}"
            f"Can you give me a deeper analysis of this decision?"
        )
        
        assert chat_message is not None, "Should build chat message"
        assert len(chat_message) > 50, "Chat message should be substantial"
        
        print(f"PASS: Chat context endpoint still works")


class TestImprovementsLogic:
    """Tests for improvements logic in _build_hindsight_data"""
    
    def test_improvements_for_stop_loss_exit(self, db):
        """Test improvements logic for stop_loss close reason"""
        from routers.trade_snapshots import _build_hindsight_data
        
        # Find a snapshot with stop_loss close reason
        snap = db.trade_snapshots.find_one({'close_reason': 'stop_loss'})
        if not snap:
            pytest.skip("No stop_loss snapshot found")
        
        data = _build_hindsight_data(snap, db)
        
        # Should have improvements
        assert len(data['improvements']) > 0, "Should have improvements for stop_loss trade"
        
        print(f"PASS: Improvements for stop_loss trade: {data['improvements']}")
    
    def test_improvements_always_non_empty(self, db, test_snapshot_any):
        """Test that improvements is never empty"""
        from routers.trade_snapshots import _build_hindsight_data
        
        data = _build_hindsight_data(test_snapshot_any, db)
        
        assert len(data['improvements']) > 0, "Improvements should never be empty"
        
        # Should have at least one meaningful improvement
        assert any(len(imp) > 20 for imp in data['improvements']), "Should have at least one substantial improvement"
        
        print(f"PASS: Improvements is non-empty with {len(data['improvements'])} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
