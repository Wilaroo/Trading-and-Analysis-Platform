"""
Test AI Assistant and Trading Bot Integration
Tests for bot-AI deep integration features including:
- GET /api/trading-bot/trades/all endpoint
- AI chat with bot context awareness
- Bot Trades section data
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTradingBotTradesAll:
    """Test GET /api/trading-bot/trades/all endpoint"""
    
    def test_trades_all_returns_success(self):
        """Verify /trades/all endpoint returns success"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        print("PASS: /trades/all returns success=true")
    
    def test_trades_all_has_pending_field(self):
        """Verify response has pending field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        data = response.json()
        assert 'pending' in data
        assert isinstance(data['pending'], list)
        print(f"PASS: /trades/all has pending field with {len(data['pending'])} trades")
    
    def test_trades_all_has_open_field(self):
        """Verify response has open field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        data = response.json()
        assert 'open' in data
        assert isinstance(data['open'], list)
        print(f"PASS: /trades/all has open field with {len(data['open'])} trades")
    
    def test_trades_all_has_closed_field(self):
        """Verify response has closed field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        data = response.json()
        assert 'closed' in data
        assert isinstance(data['closed'], list)
        print(f"PASS: /trades/all has closed field with {len(data['closed'])} trades")
    
    def test_trades_all_has_daily_stats(self):
        """Verify response has daily_stats field with expected structure"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        data = response.json()
        assert 'daily_stats' in data
        daily_stats = data['daily_stats']
        
        # Check required fields
        required_fields = ['date', 'trades_executed', 'trades_won', 'trades_lost', 
                          'gross_pnl', 'net_pnl', 'win_rate']
        for field in required_fields:
            assert field in daily_stats, f"Missing field: {field}"
        
        print(f"PASS: daily_stats contains all required fields: {list(daily_stats.keys())}")
    
    def test_pending_trades_have_required_fields(self):
        """Verify pending trades have all required fields for Bot Trades section"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        data = response.json()
        
        if data['pending']:
            trade = data['pending'][0]
            required_fields = ['id', 'symbol', 'direction', 'timeframe', 'setup_type', 
                              'shares', 'entry_price', 'quality_grade', 'status']
            for field in required_fields:
                assert field in trade, f"Missing field: {field}"
            print(f"PASS: Pending trade has required fields: symbol={trade['symbol']}, direction={trade['direction']}, timeframe={trade['timeframe']}")
        else:
            print("SKIP: No pending trades to verify fields")


class TestAIBotContextIntegration:
    """Test AI Assistant's awareness of bot trades"""
    
    def test_ai_chat_endpoint_works(self):
        """Verify AI chat endpoint is functional"""
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json={"message": "hello", "session_id": "test_integration_1"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        assert 'response' in data
        print("PASS: AI chat endpoint is working")
    
    def test_ai_responds_to_bot_status_query(self):
        """AI should respond with bot information when asked about bot status"""
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json={"message": "What is the bot status?", "session_id": "test_integration_2"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        
        # Response should reference bot-related terms
        response_text = data.get('response', '').lower()
        bot_terms = ['bot', 'trade', 'pending', 'status', 'mode', 'capital', 'running']
        has_bot_context = any(term in response_text for term in bot_terms)
        
        assert has_bot_context, f"AI response should mention bot context. Response: {data.get('response', '')[:200]}"
        print(f"PASS: AI mentions bot context in response. Preview: {data.get('response', '')[:150]}...")
    
    def test_ai_knows_about_pending_trades(self):
        """AI should know about pending trades when asked"""
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json={"message": "What are the bot pending trades?", "session_id": "test_integration_3"}
        )
        assert response.status_code == 200
        data = response.json()
        
        response_text = data.get('response', '').upper()
        
        # Get actual pending trades
        trades_response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        trades_data = trades_response.json()
        pending_trades = trades_data.get('pending', [])
        
        if pending_trades:
            # AI should mention at least one of the pending trade symbols
            symbols = [t['symbol'] for t in pending_trades]
            symbols_mentioned = [s for s in symbols if s in response_text]
            
            assert len(symbols_mentioned) > 0, f"AI should mention pending trade symbols ({symbols}). Response: {response_text[:300]}"
            print(f"PASS: AI mentions pending trade symbols: {symbols_mentioned}")
        else:
            print("SKIP: No pending trades to verify")
    
    def test_ai_knows_specific_trade_details(self):
        """AI should know details like P&L, direction, setup type"""
        # First get actual trades
        trades_response = requests.get(f"{BASE_URL}/api/trading-bot/trades/all")
        trades_data = trades_response.json()
        pending_trades = trades_data.get('pending', [])
        
        if pending_trades:
            trade = pending_trades[0]
            symbol = trade['symbol']
            
            response = requests.post(
                f"{BASE_URL}/api/assistant/chat",
                json={"message": f"Tell me about the bot's {symbol} trade", "session_id": "test_integration_4"}
            )
            assert response.status_code == 200
            data = response.json()
            
            response_text = data.get('response', '').lower()
            
            # AI should mention some key details
            assert symbol.lower() in response_text, f"AI should mention {symbol}"
            print(f"PASS: AI provides details about {symbol} trade")
        else:
            print("SKIP: No pending trades to verify")


class TestDemoTradeCreation:
    """Test demo trade creation and AI awareness"""
    
    def test_create_demo_trade(self):
        """Creating a demo trade should work"""
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "GOOGL", "direction": "long", "setup_type": "breakout"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        assert 'trade' in data
        
        trade = data['trade']
        assert trade['symbol'] == 'GOOGL'
        assert trade['direction'] == 'long'
        assert trade['setup_type'] == 'breakout'
        assert trade['status'] == 'pending'
        print(f"PASS: Created demo trade for GOOGL with id={trade['id']}")
        
        # Store trade id for cleanup
        return trade['id']
    
    def test_ai_knows_about_new_demo_trade(self):
        """After creating demo trade, AI should know about it"""
        # Create a demo trade
        create_response = requests.post(
            f"{BASE_URL}/api/trading-bot/demo-trade",
            json={"symbol": "META", "direction": "short", "setup_type": "vwap_bounce"}
        )
        assert create_response.status_code == 200
        
        # Wait a moment for state to settle
        time.sleep(0.5)
        
        # Ask AI about pending trades
        response = requests.post(
            f"{BASE_URL}/api/assistant/chat",
            json={"message": "What bot trades are pending?", "session_id": "test_integration_5"}
        )
        assert response.status_code == 200
        data = response.json()
        
        response_text = data.get('response', '').upper()
        # META should be mentioned since we just created it
        assert 'META' in response_text, f"AI should mention META which was just created. Response: {response_text[:300]}"
        print("PASS: AI is aware of newly created META demo trade")


class TestEvaluateTradeEndpoint:
    """Test POST /api/trading-bot/evaluate-trade endpoint"""
    
    def test_evaluate_trade_endpoint(self):
        """Test AI evaluation of trade opportunities"""
        response = requests.post(
            f"{BASE_URL}/api/trading-bot/evaluate-trade",
            json={"symbol": "NVDA", "direction": "long", "setup_type": "squeeze"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return evaluation result
        assert 'evaluation' in data or 'verdict' in data or 'should_take' in data
        print(f"PASS: Evaluate trade endpoint returns: {list(data.keys())}")


class TestIndividualTradeEndpoints:
    """Test individual trade management endpoints"""
    
    def test_get_pending_trades(self):
        """GET /api/trading-bot/trades/pending should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        assert 'trades' in data
        print(f"PASS: /trades/pending returns {data.get('count', 0)} trades")
    
    def test_get_open_trades(self):
        """GET /api/trading-bot/trades/open should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        assert 'trades' in data
        print(f"PASS: /trades/open returns {data.get('count', 0)} trades")
    
    def test_get_closed_trades(self):
        """GET /api/trading-bot/trades/closed should work"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed")
        assert response.status_code == 200
        data = response.json()
        assert data.get('success') is True
        assert 'trades' in data
        print(f"PASS: /trades/closed returns {data.get('count', 0)} trades")


class TestBotStatus:
    """Test bot status endpoint contains all needed data"""
    
    def test_status_includes_strategy_configs(self):
        """Bot status should include strategy_configs"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        data = response.json()
        
        assert 'strategy_configs' in data
        configs = data['strategy_configs']
        
        expected_strategies = ['rubber_band', 'vwap_bounce', 'breakout', 'squeeze', 
                              'trend_continuation', 'position_trade']
        for strategy in expected_strategies:
            assert strategy in configs, f"Missing strategy: {strategy}"
        
        print(f"PASS: Status includes strategy_configs for all 6 strategies")
    
    def test_status_includes_daily_stats(self):
        """Bot status should include daily_stats"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        data = response.json()
        
        assert 'daily_stats' in data
        print(f"PASS: Status includes daily_stats")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
