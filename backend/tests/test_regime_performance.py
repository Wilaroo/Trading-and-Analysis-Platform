"""
Test Regime Performance Tracking Service
Tests the regime-aware trade logging and performance analysis features.
"""
import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

# Add backend to path
import sys
sys.path.insert(0, '/app/backend')

from services.regime_performance_service import (
    RegimePerformanceService,
    init_regime_performance_service,
    get_regime_performance_service
)


class TestRegimePerformanceService:
    """Tests for the RegimePerformanceService"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock MongoDB database"""
        db = MagicMock()
        db['regime_performance'].find.return_value = []
        db['regime_trade_log'].find.return_value = []
        db['regime_trade_log'].aggregate.return_value = []
        db['regime_performance'].create_index = MagicMock()
        db['regime_trade_log'].create_index = MagicMock()
        db['regime_trade_log'].update_one = MagicMock()
        db['regime_performance'].update_one = MagicMock()
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create a service instance with mock db"""
        service = RegimePerformanceService()
        service.set_db(mock_db)
        return service
    
    def test_service_initialization(self, service, mock_db):
        """Test that the service initializes correctly"""
        assert service._db is not None
        assert service._performance_collection is not None
        assert service._trade_log_collection is not None
        # Verify indexes were created
        assert mock_db['regime_performance'].create_index.called
        assert mock_db['regime_trade_log'].create_index.called
    
    @pytest.mark.asyncio
    async def test_log_trade_success(self, service, mock_db):
        """Test logging a trade successfully"""
        # Sample trade data
        trade_data = {
            "trade_id": "test123",
            "setup_type": "orb",
            "market_regime": "RISK_ON",
            "direction": "LONG",
            "realized_pnl": 150.50,
            "shares": 100,
            "entry_price": 50.0,
            "exit_price": 51.5,
            "regime_score": 75.0,
            "regime_position_multiplier": 1.0,
            "risk_amount": 100.0,
            "closed_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Log the trade
        await service.log_trade(trade_data)
        
        # Verify trade was logged to collection
        mock_db['regime_trade_log'].update_one.assert_called_once()
        call_args = mock_db['regime_trade_log'].update_one.call_args
        assert call_args[0][0] == {"trade_id": "test123"}  # Filter
        assert "pnl" in call_args[0][1]["$set"]  # Update data
        assert call_args[0][1]["$set"]["is_winner"] == True  # Positive PnL
    
    @pytest.mark.asyncio
    async def test_log_trade_losing_trade(self, service, mock_db):
        """Test logging a losing trade"""
        trade_data = {
            "trade_id": "test456",
            "setup_type": "rubber_band",
            "market_regime": "RISK_OFF",
            "direction": "LONG",
            "realized_pnl": -75.25,
            "shares": 50,
            "entry_price": 100.0,
            "exit_price": 98.5,
            "regime_score": 35.0,
            "regime_position_multiplier": 0.5,
            "risk_amount": 75.0
        }
        
        await service.log_trade(trade_data)
        
        call_args = mock_db['regime_trade_log'].update_one.call_args
        assert call_args[0][1]["$set"]["is_winner"] == False
        assert call_args[0][1]["$set"]["market_regime"] == "RISK_OFF"
    
    @pytest.mark.asyncio
    async def test_log_trade_with_r_multiple(self, service, mock_db):
        """Test R-multiple calculation in trade logging"""
        trade_data = {
            "trade_id": "test789",
            "setup_type": "spencer_scalp",
            "market_regime": "CAUTION",
            "direction": "SHORT",
            "realized_pnl": 200.0,
            "shares": 100,
            "entry_price": 50.0,
            "exit_price": 48.0,
            "risk_amount": 100.0  # 1R = $100
        }
        
        await service.log_trade(trade_data)
        
        call_args = mock_db['regime_trade_log'].update_one.call_args
        logged_data = call_args[0][1]["$set"]
        # R-multiple should be 200/100 = 2.0
        assert logged_data["r_multiple"] == 2.0
    
    @pytest.mark.asyncio
    async def test_get_regime_summary_empty(self, service, mock_db):
        """Test getting regime summary with no data"""
        mock_db['regime_trade_log'].aggregate.return_value = []
        
        summary = await service.get_regime_summary()
        
        assert "regimes" in summary
        assert summary["total_trades"] == 0
        assert "generated_at" in summary
    
    @pytest.mark.asyncio
    async def test_get_regime_summary_with_data(self, service, mock_db):
        """Test getting regime summary with aggregated data"""
        mock_db['regime_trade_log'].aggregate.return_value = [
            {
                "_id": "RISK_ON",
                "total_trades": 10,
                "winning_trades": 7,
                "total_pnl": 1500.0,
                "avg_r_multiple": 1.5,
                "unique_strategies": ["orb", "spencer_scalp", "breakout"]
            },
            {
                "_id": "RISK_OFF",
                "total_trades": 5,
                "winning_trades": 2,
                "total_pnl": -300.0,
                "avg_r_multiple": 0.5,
                "unique_strategies": ["rubber_band"]
            }
        ]
        
        summary = await service.get_regime_summary()
        
        assert summary["total_trades"] == 15
        assert "RISK_ON" in summary["regimes"]
        assert summary["regimes"]["RISK_ON"]["win_rate"] == 70.0
        assert summary["regimes"]["RISK_OFF"]["win_rate"] == 40.0
    
    @pytest.mark.asyncio
    async def test_get_strategy_regime_performance(self, service, mock_db):
        """Test getting strategy performance by regime"""
        mock_db['regime_performance'].find.return_value = [
            {
                "strategy_name": "orb",
                "market_regime": "RISK_ON",
                "total_trades": 20,
                "win_rate": 65.0,
                "total_pnl": 2500.0,
                "expectancy": 125.0
            }
        ]
        
        results = await service.get_strategy_regime_performance(
            strategy_name="orb",
            market_regime="RISK_ON"
        )
        
        assert len(results) == 1
        assert results[0]["strategy_name"] == "orb"
        assert results[0]["market_regime"] == "RISK_ON"
    
    @pytest.mark.asyncio
    async def test_get_best_strategies_for_regime(self, service, mock_db):
        """Test getting best strategies for a specific regime"""
        mock_results = MagicMock()
        mock_results.sort.return_value.limit.return_value = [
            {"strategy_name": "orb", "expectancy": 150.0},
            {"strategy_name": "spencer_scalp", "expectancy": 120.0}
        ]
        mock_db['regime_performance'].find.return_value = mock_results
        
        results = await service.get_best_strategies_for_regime(
            market_regime="RISK_ON",
            min_trades=5,
            sort_by="expectancy"
        )
        
        mock_db['regime_performance'].find.assert_called_once()


class TestRegimePerformanceIntegration:
    """Integration tests for regime performance with trading bot"""
    
    @pytest.mark.asyncio
    async def test_trading_bot_logs_to_regime_service(self):
        """Test that trading bot logs closed trades to regime service"""
        from services.trading_bot_service import TradingBotService, BotTrade, TradeDirection, TradeStatus
        
        # Create a mock regime performance service
        mock_regime_service = AsyncMock()
        
        # Create trading bot and wire the service
        bot = TradingBotService()
        bot.set_regime_performance_service(mock_regime_service)
        
        # Create a mock closed trade
        trade = BotTrade(
            id="test_trade_001",
            symbol="AAPL",
            direction=TradeDirection.LONG,
            status=TradeStatus.CLOSED,
            setup_type="orb",
            timeframe="intraday",
            quality_score=75,
            quality_grade="B+",
            entry_price=150.0,
            current_price=153.0,
            stop_price=148.0,
            target_prices=[152.0, 154.0, 156.0],
            shares=100,
            risk_amount=200.0,
            potential_reward=400.0,
            risk_reward_ratio=2.0,
            exit_price=153.0,
            realized_pnl=300.0,
            market_regime="RISK_ON",
            regime_score=72.0,
            regime_position_multiplier=1.0,
            closed_at=datetime.now(timezone.utc).isoformat()
        )
        
        # Call the logging method
        await bot._log_trade_to_regime_performance(trade)
        
        # Verify the regime service was called
        mock_regime_service.log_trade.assert_called_once()
        
        # Verify the trade data passed to the service
        call_args = mock_regime_service.log_trade.call_args
        trade_data = call_args[0][0]
        
        assert trade_data["trade_id"] == "test_trade_001"
        assert trade_data["setup_type"] == "orb"
        assert trade_data["market_regime"] == "RISK_ON"
        assert trade_data["realized_pnl"] == 300.0
        assert trade_data["regime_position_multiplier"] == 1.0


class TestRegimePerformanceAPI:
    """API endpoint tests"""
    
    @pytest.mark.asyncio
    async def test_api_endpoints_respond(self):
        """Test that all API endpoints respond correctly"""
        import httpx
        
        # Get the API URL from env
        api_url = "https://trading-heartbeat.preview.emergentagent.com"
        
        endpoints = [
            "/api/regime-performance/summary",
            "/api/regime-performance/strategies",
            "/api/regime-performance/best-for-regime/RISK_ON",
            "/api/regime-performance/position-sizing-impact",
            "/api/regime-performance/recommendations"
        ]
        
        async with httpx.AsyncClient() as client:
            for endpoint in endpoints:
                resp = await client.get(f"{api_url}{endpoint}", timeout=10)
                assert resp.status_code == 200, f"Endpoint {endpoint} failed with {resp.status_code}"
                data = resp.json()
                assert data.get("success") == True, f"Endpoint {endpoint} returned success=False"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
