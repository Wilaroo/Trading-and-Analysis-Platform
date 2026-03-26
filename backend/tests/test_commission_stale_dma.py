"""
Test Commission Tracking, Stale Alert Timeout, Price Recalculation, IB LIVE Mode, and DMA Filter

Features tested:
1. Commission calculation: _calculate_commission(100) returns $1.00 (minimum), _calculate_commission(5000) returns $25.00
2. BotTrade dataclass has commission_per_share, commission_min, total_commissions, net_pnl fields
3. BotTrade.to_dict() includes total_commissions and net_pnl
4. confirm_trade has stale alert check with configurable timeouts (scalp=300s, swing=900s)
5. confirm_trade recalculates price from current quotes before execution
6. trade_executor_service _init_ib keeps LIVE mode when pusher is connected
7. _build_entry_context handles None technicals without crashing
8. _build_entry_context includes confidence_gate field in entry context
9. enhanced_scanner _process_new_alert has DMA filter for swing/position trade styles
10. DMA filter checks EMA50 for swings, SMA200 for position/investment
11. POST /api/ai-training/confidence-gate/evaluate returns decision with reasoning
12. GET /api/trading-bot/status returns healthy response
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestCommissionCalculation:
    """Test commission calculation logic - IB tiered: $0.005/share, $1.00 min"""
    
    def test_commission_minimum_100_shares(self):
        """100 shares * $0.005 = $0.50, but minimum is $1.00"""
        from services.trading_bot_service import TradingBotService
        
        commission = TradingBotService._calculate_commission(100)
        assert commission == 1.00, f"Expected $1.00 (minimum), got ${commission}"
        print(f"PASSED: _calculate_commission(100) = ${commission} (minimum applied)")
    
    def test_commission_5000_shares(self):
        """5000 shares * $0.005 = $25.00"""
        from services.trading_bot_service import TradingBotService
        
        commission = TradingBotService._calculate_commission(5000)
        assert commission == 25.00, f"Expected $25.00, got ${commission}"
        print(f"PASSED: _calculate_commission(5000) = ${commission}")
    
    def test_commission_200_shares(self):
        """200 shares * $0.005 = $1.00 (exactly at minimum)"""
        from services.trading_bot_service import TradingBotService
        
        commission = TradingBotService._calculate_commission(200)
        assert commission == 1.00, f"Expected $1.00, got ${commission}"
        print(f"PASSED: _calculate_commission(200) = ${commission}")
    
    def test_commission_1000_shares(self):
        """1000 shares * $0.005 = $5.00"""
        from services.trading_bot_service import TradingBotService
        
        commission = TradingBotService._calculate_commission(1000)
        assert commission == 5.00, f"Expected $5.00, got ${commission}"
        print(f"PASSED: _calculate_commission(1000) = ${commission}")


class TestBotTradeDataclass:
    """Test BotTrade dataclass has commission fields"""
    
    def test_bottrade_has_commission_fields(self):
        """BotTrade should have commission_per_share, commission_min, total_commissions, net_pnl"""
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
        
        trade = BotTrade(
            id="test123",
            symbol="AAPL",
            direction=TradeDirection.LONG,
            status=TradeStatus.PENDING,
            setup_type="test",
            timeframe="scalp",
            quality_score=80,
            quality_grade="A",
            entry_price=150.0,
            current_price=150.0,
            stop_price=148.0,
            target_prices=[155.0],
            shares=100,
            risk_amount=200.0,
            potential_reward=500.0,
            risk_reward_ratio=2.5
        )
        
        # Check fields exist with correct defaults
        assert hasattr(trade, 'commission_per_share'), "Missing commission_per_share field"
        assert hasattr(trade, 'commission_min'), "Missing commission_min field"
        assert hasattr(trade, 'total_commissions'), "Missing total_commissions field"
        assert hasattr(trade, 'net_pnl'), "Missing net_pnl field"
        
        assert trade.commission_per_share == 0.005, f"Expected 0.005, got {trade.commission_per_share}"
        assert trade.commission_min == 1.00, f"Expected 1.00, got {trade.commission_min}"
        assert trade.total_commissions == 0.0, f"Expected 0.0, got {trade.total_commissions}"
        assert trade.net_pnl == 0.0, f"Expected 0.0, got {trade.net_pnl}"
        
        print("PASSED: BotTrade has all commission fields with correct defaults")
    
    def test_bottrade_to_dict_includes_commission_fields(self):
        """BotTrade.to_dict() should include total_commissions and net_pnl"""
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
        
        trade = BotTrade(
            id="test456",
            symbol="MSFT",
            direction=TradeDirection.LONG,
            status=TradeStatus.OPEN,
            setup_type="momentum",
            timeframe="swing",
            quality_score=75,
            quality_grade="B",
            entry_price=400.0,
            current_price=405.0,
            stop_price=395.0,
            target_prices=[420.0],
            shares=50,
            risk_amount=250.0,
            potential_reward=1000.0,
            risk_reward_ratio=4.0
        )
        
        # Set some commission values
        trade.total_commissions = 5.50
        trade.net_pnl = 244.50  # realized_pnl - total_commissions
        
        trade_dict = trade.to_dict()
        
        assert 'total_commissions' in trade_dict, "to_dict() missing total_commissions"
        assert 'net_pnl' in trade_dict, "to_dict() missing net_pnl"
        assert trade_dict['total_commissions'] == 5.50, f"Expected 5.50, got {trade_dict['total_commissions']}"
        assert trade_dict['net_pnl'] == 244.50, f"Expected 244.50, got {trade_dict['net_pnl']}"
        
        print("PASSED: BotTrade.to_dict() includes total_commissions and net_pnl")


class TestStaleAlertTimeout:
    """Test stale alert timeout configuration in confirm_trade"""
    
    def test_stale_thresholds_exist(self):
        """Verify stale thresholds are defined: scalp=300s, swing=900s"""
        import inspect
        from services.trading_bot_service import TradingBotService
        
        # Get source code of confirm_trade method
        source = inspect.getsource(TradingBotService.confirm_trade)
        
        # Check for stale threshold definitions
        assert '"scalp": 300' in source or "'scalp': 300" in source, "Missing scalp=300s threshold"
        assert '"swing": 900' in source or "'swing': 900" in source, "Missing swing=900s threshold"
        
        print("PASSED: Stale thresholds defined - scalp=300s, swing=900s")
    
    def test_confirm_trade_has_stale_check(self):
        """confirm_trade should check alert age against timeframe thresholds"""
        import inspect
        from services.trading_bot_service import TradingBotService
        
        source = inspect.getsource(TradingBotService.confirm_trade)
        
        # Check for stale alert logic
        assert 'stale' in source.lower() or 'STALE' in source, "Missing stale alert check"
        assert 'max_age_seconds' in source, "Missing max_age_seconds variable"
        assert 'EXPIRED' in source, "Missing EXPIRED status handling"
        
        print("PASSED: confirm_trade has stale alert check logic")


class TestPriceRecalculation:
    """Test price recalculation on trade confirmation"""
    
    def test_confirm_trade_has_price_recalc(self):
        """confirm_trade should recalculate entry price from current quotes"""
        import inspect
        from services.trading_bot_service import TradingBotService
        
        source = inspect.getsource(TradingBotService.confirm_trade)
        
        # Check for price recalculation logic
        assert 'current_price' in source, "Missing current_price variable"
        assert 'get_pushed_quotes' in source, "Missing IB pushed quotes check"
        assert 'entry_price' in source, "Missing entry_price update"
        assert 'recalc' in source.lower() or 'Recalc' in source, "Missing recalculation logic"
        
        print("PASSED: confirm_trade has price recalculation logic")


class TestTradeExecutorIBMode:
    """Test trade_executor_service keeps LIVE mode when pusher connected"""
    
    def test_init_ib_keeps_live_mode(self):
        """_init_ib should keep LIVE mode when pusher is connected"""
        import inspect
        from services.trade_executor_service import TradeExecutorService
        
        source = inspect.getsource(TradeExecutorService._init_ib)
        
        # Check that LIVE mode is preserved when pusher connected
        assert 'is_pusher_connected' in source, "Missing pusher connection check"
        assert 'LIVE' in source, "Missing LIVE mode reference"
        assert 'order queue' in source.lower() or 'order_queue' in source.lower(), "Missing order queue reference"
        
        print("PASSED: _init_ib checks pusher connection and keeps LIVE mode")
    
    def test_executor_default_mode_is_live(self):
        """TradeExecutorService should default to LIVE mode"""
        from services.trade_executor_service import TradeExecutorService, ExecutorMode
        
        executor = TradeExecutorService()
        assert executor._mode == ExecutorMode.LIVE, f"Expected LIVE mode, got {executor._mode}"
        
        print("PASSED: TradeExecutorService defaults to LIVE mode")


class TestBuildEntryContext:
    """Test _build_entry_context handles None technicals and includes confidence_gate"""
    
    def test_build_entry_context_handles_none_technicals(self):
        """_build_entry_context should handle None technicals without crashing"""
        import inspect
        from services.trading_bot_service import TradingBotService
        
        source = inspect.getsource(TradingBotService._build_entry_context)
        
        # Check for safe technicals access
        assert 'or {}' in source, "Missing safe dict fallback for technicals"
        assert 'intelligence.get("technicals")' in source, "Missing technicals getter"
        
        print("PASSED: _build_entry_context handles None technicals safely")
    
    def test_build_entry_context_includes_confidence_gate(self):
        """_build_entry_context should include confidence_gate field"""
        import inspect
        from services.trading_bot_service import TradingBotService
        
        source = inspect.getsource(TradingBotService._build_entry_context)
        
        # Check for confidence_gate in context
        assert 'confidence_gate' in source, "Missing confidence_gate in entry context"
        assert 'confidence_gate_result' in source, "Missing confidence_gate_result parameter"
        
        print("PASSED: _build_entry_context includes confidence_gate field")


class TestDMAFilter:
    """Test DMA directional filter in enhanced_scanner"""
    
    def test_dma_filter_exists_in_process_new_alert(self):
        """_process_new_alert should have DMA filter for swing/position trades"""
        import inspect
        from services.enhanced_scanner import EnhancedBackgroundScanner
        
        source = inspect.getsource(EnhancedBackgroundScanner._process_new_alert)
        
        # Check for DMA filter
        assert 'DMA' in source, "Missing DMA filter reference"
        assert 'swing' in source.lower(), "Missing swing trade style check"
        assert 'position' in source.lower(), "Missing position trade style check"
        
        print("PASSED: _process_new_alert has DMA filter for swing/position trades")
    
    def test_dma_filter_checks_ema50_for_swings(self):
        """DMA filter should check EMA50 for swing trades"""
        import inspect
        from services.enhanced_scanner import EnhancedBackgroundScanner
        
        source = inspect.getsource(EnhancedBackgroundScanner._process_new_alert)
        
        # Check for EMA50 in swing filter
        assert 'ema_50' in source or 'EMA50' in source, "Missing EMA50 check"
        
        print("PASSED: DMA filter checks EMA50 for swings")
    
    def test_dma_filter_checks_sma200_for_investment(self):
        """DMA filter should check SMA200 for investment/position trades"""
        import inspect
        from services.enhanced_scanner import EnhancedBackgroundScanner
        
        source = inspect.getsource(EnhancedBackgroundScanner._process_new_alert)
        
        # Check for SMA200 in investment filter
        assert 'sma_200' in source or 'SMA200' in source, "Missing SMA200 check"
        
        print("PASSED: DMA filter checks SMA200 for investment/position trades")


class TestAPIEndpoints:
    """Test API endpoints"""
    
    def test_confidence_gate_evaluate(self):
        """POST /api/ai-training/confidence-gate/evaluate returns decision with reasoning"""
        response = requests.post(
            f"{BASE_URL}/api/ai-training/confidence-gate/evaluate",
            json={
                "symbol": "AAPL",
                "setup_type": "momentum",
                "direction": "long",
                "quality_score": 75
            },
            timeout=15
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert 'decision' in data, f"Missing 'decision' in response: {data}"
        assert 'reasoning' in data, f"Missing 'reasoning' in response: {data}"
        
        print(f"PASSED: POST /api/ai-training/confidence-gate/evaluate returns decision={data.get('decision')}")
    
    def test_trading_bot_status(self):
        """GET /api/trading-bot/status returns healthy response"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status", timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Should have some status fields
        assert isinstance(data, dict), f"Expected dict response, got {type(data)}"
        
        print(f"PASSED: GET /api/trading-bot/status returns 200 with status data")


class TestApplyCommission:
    """Test _apply_commission method updates trade correctly"""
    
    def test_apply_commission_updates_trade(self):
        """_apply_commission should update total_commissions and net_pnl"""
        from services.trading_bot_service import TradingBotService, BotTrade, TradeDirection, TradeStatus
        
        bot = TradingBotService()
        
        trade = BotTrade(
            id="test789",
            symbol="NVDA",
            direction=TradeDirection.LONG,
            status=TradeStatus.OPEN,
            setup_type="breakout",
            timeframe="intraday",
            quality_score=85,
            quality_grade="A",
            entry_price=500.0,
            current_price=510.0,
            stop_price=490.0,
            target_prices=[530.0],
            shares=200,
            risk_amount=2000.0,
            potential_reward=6000.0,
            risk_reward_ratio=3.0
        )
        
        # Set realized_pnl
        trade.realized_pnl = 2000.0
        
        # Apply commission for 200 shares
        commission = bot._apply_commission(trade, 200)
        
        # 200 * 0.005 = $1.00 (at minimum)
        assert commission == 1.00, f"Expected $1.00 commission, got ${commission}"
        assert trade.total_commissions == 1.00, f"Expected total_commissions=1.00, got {trade.total_commissions}"
        assert trade.net_pnl == 1999.00, f"Expected net_pnl=1999.00, got {trade.net_pnl}"
        
        # Apply another commission for exit (200 shares)
        commission2 = bot._apply_commission(trade, 200)
        
        assert commission2 == 1.00, f"Expected $1.00 commission, got ${commission2}"
        assert trade.total_commissions == 2.00, f"Expected total_commissions=2.00, got {trade.total_commissions}"
        assert trade.net_pnl == 1998.00, f"Expected net_pnl=1998.00, got {trade.net_pnl}"
        
        print("PASSED: _apply_commission correctly updates total_commissions and net_pnl")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
