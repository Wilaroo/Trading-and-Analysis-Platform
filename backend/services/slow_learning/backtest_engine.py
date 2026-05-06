"""
Backtest Engine - Phase 6 Slow Learning

DEPRECATED: This basic engine is superseded by AdvancedBacktestEngine in
advanced_backtest_engine.py, which supports multi-strategy comparison,
walk-forward optimization, Monte Carlo simulation, AI comparison, and 
market-wide backtesting. New features should use the advanced engine.

This file is kept for backwards compatibility with /api/slow-learning/backtest/* endpoints.

Runs trading strategies against historical data to validate performance.
Supports multiple strategy types, position sizing, and detailed reporting.

Features:
- Strategy simulation on historical bars
- TQS-based entry filtering
- Multiple exit strategies
- Detailed performance metrics
- Comparison against benchmarks
"""

import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    TARGET = "target"
    STOP = "stop"
    TIME = "time"
    TRAILING_STOP = "trailing_stop"
    END_OF_DATA = "end_of_data"


@dataclass
class BacktestTrade:
    """A single trade in the backtest"""
    id: str = ""
    symbol: str = ""
    direction: str = "long"
    entry_date: str = ""
    entry_price: float = 0.0
    exit_date: str = ""
    exit_price: float = 0.0
    shares: int = 0
    stop_price: float = 0.0
    target_price: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0
    max_favorable_excursion: float = 0.0  # Best unrealized P&L
    max_adverse_excursion: float = 0.0    # Worst unrealized P&L
    setup_type: str = ""
    tqs_score: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run"""
    # Capital and position sizing
    starting_capital: float = 100000.0
    max_position_size_pct: float = 10.0  # Max 10% of capital per trade
    max_concurrent_positions: int = 5
    
    # Risk management
    default_stop_pct: float = 2.0   # 2% stop loss
    default_target_pct: float = 4.0  # 4% take profit
    use_trailing_stop: bool = False
    trailing_stop_pct: float = 1.5
    
    # Entry filters
    min_tqs_score: float = 60.0
    min_volume: int = 100000
    min_price: float = 5.0
    max_price: float = 500.0
    
    # Time filters
    max_bars_to_hold: int = 20  # Exit after N bars if still open
    
    # Strategy
    setup_types: List[str] = field(default_factory=list)  # Empty = all setups
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BacktestResult:
    """Complete backtest results"""
    id: str = ""
    name: str = ""
    symbol: str = ""
    timeframe: str = ""
    start_date: str = ""
    end_date: str = ""
    config: Dict = field(default_factory=dict)
    
    # Performance metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    avg_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    largest_winner: float = 0.0
    largest_loser: float = 0.0
    
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # R metrics
    total_r: float = 0.0
    avg_r: float = 0.0
    expectancy: float = 0.0  # Expected R per trade
    
    # Time metrics
    avg_bars_held: float = 0.0
    avg_winner_bars: float = 0.0
    avg_loser_bars: float = 0.0
    
    # Trade list
    trades: List[Dict] = field(default_factory=list)
    
    # Equity curve
    equity_curve: List[Dict] = field(default_factory=list)
    
    # Metadata
    created_at: str = ""
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BacktestEngine:
    """
    Runs backtests on historical data.
    
    Process:
    1. Load historical bars
    2. Apply entry signals based on strategy
    3. Simulate trade execution
    4. Track exits (stop, target, time)
    5. Calculate performance metrics
    """
    
    def __init__(self):
        self._db = None
        self._backtest_results_col = None
        self._historical_data_service = None
        self._tqs_engine = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._backtest_results_col = db['backtest_results']
            
    def set_historical_data_service(self, service):
        """Set historical data service"""
        self._historical_data_service = service
        
    def set_tqs_engine(self, engine):
        """Set TQS engine for scoring"""
        self._tqs_engine = engine
        
    async def run_backtest(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start_date: str = None,
        end_date: str = None,
        config: BacktestConfig = None,
        name: str = None,
        entry_signal_fn: Callable = None
    ) -> BacktestResult:
        """
        Run a backtest on historical data.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe
            start_date: Backtest start date
            end_date: Backtest end date
            config: Backtest configuration
            name: Name for this backtest
            entry_signal_fn: Custom entry signal function
            
        Returns:
            BacktestResult with all metrics
        """
        start_time = datetime.now(timezone.utc)
        
        if config is None:
            config = BacktestConfig()
            
        result = BacktestResult(
            id=f"bt_{uuid.uuid4().hex[:12]}",
            name=name or f"Backtest {symbol}",
            symbol=symbol.upper(),
            timeframe=timeframe,
            config=config.to_dict(),
            created_at=start_time.isoformat()
        )
        
        # Get historical bars
        bars = await self._get_bars(symbol, timeframe, start_date, end_date)
        
        if not bars:
            result.total_trades = 0
            return result
            
        result.start_date = bars[0]["timestamp"][:10]
        result.end_date = bars[-1]["timestamp"][:10]
        
        # Run simulation
        trades, equity_curve = await self._simulate_trading(
            bars, config, entry_signal_fn
        )
        
        # Calculate metrics
        result = self._calculate_metrics(result, trades, equity_curve, config)
        
        # Store result
        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        if self._backtest_results_col is not None:
            self._backtest_results_col.insert_one(result.to_dict())
            
        return result
        
    async def _get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> List[Dict]:
        """Get bars from historical data service or Alpaca"""
        bars = []
        
        # Try historical data service first
        if self._historical_data_service is not None:
            bars = await self._historical_data_service.get_bars(
                symbol, timeframe, start_date, end_date
            )
            
        # If no stored data, fetch from Alpaca directly
        if not bars:
            try:
                from services.alpaca_service import get_alpaca_service
                alpaca = get_alpaca_service()
                if alpaca:
                    bars = await alpaca.get_bars(symbol, timeframe, limit=500)
            except Exception as e:
                logger.warning(f"Could not fetch bars: {e}")
                
        return bars
        
    async def _simulate_trading(
        self,
        bars: List[Dict],
        config: BacktestConfig,
        entry_signal_fn: Callable = None
    ) -> tuple:
        """
        Simulate trading on historical bars.
        
        Returns (trades, equity_curve)
        """
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []
        
        capital = config.starting_capital
        open_positions: List[Dict] = []
        
        for i, bar in enumerate(bars):
            current_price = bar["close"]
            timestamp = bar["timestamp"]
            
            # Track equity
            position_value = sum(
                p["shares"] * current_price for p in open_positions
            )
            total_equity = capital + position_value
            equity_curve.append({
                "timestamp": timestamp,
                "equity": total_equity,
                "capital": capital,
                "positions": len(open_positions)
            })
            
            # Check exits for open positions
            positions_to_close = []
            for pos in open_positions:
                exit_reason = self._check_exit(bar, pos, config, i - pos["entry_bar_idx"])
                if exit_reason:
                    positions_to_close.append((pos, exit_reason, current_price))
                    
            # Process exits
            for pos, reason, exit_price in positions_to_close:
                trade = self._close_position(pos, exit_price, reason, timestamp, i)
                trades.append(trade)
                capital += trade.pnl + (pos["shares"] * pos["entry_price"])
                open_positions.remove(pos)
                
            # Check for new entry signals
            if len(open_positions) < config.max_concurrent_positions:
                should_enter = False
                
                if entry_signal_fn:
                    should_enter = entry_signal_fn(bars[:i+1], config)
                else:
                    # Default: simple momentum entry
                    should_enter = self._default_entry_signal(bars, i, config)
                    
                if should_enter:
                    # Calculate position size
                    position_value = capital * (config.max_position_size_pct / 100)
                    shares = int(position_value / current_price)
                    
                    if shares > 0 and bar.get("volume", 0) >= config.min_volume:
                        # Open position
                        stop_price = current_price * (1 - config.default_stop_pct / 100)
                        target_price = current_price * (1 + config.default_target_pct / 100)
                        
                        open_positions.append({
                            "id": f"pos_{uuid.uuid4().hex[:8]}",
                            "entry_price": current_price,
                            "entry_date": timestamp,
                            "entry_bar_idx": i,
                            "shares": shares,
                            "stop_price": stop_price,
                            "target_price": target_price,
                            "highest_price": current_price,
                            "lowest_price": current_price
                        })
                        
                        capital -= shares * current_price
                        
        # Close remaining positions at end
        if bars and open_positions:
            final_price = bars[-1]["close"]
            final_timestamp = bars[-1]["timestamp"]
            for pos in open_positions:
                trade = self._close_position(
                    pos, final_price, ExitReason.END_OF_DATA.value,
                    final_timestamp, len(bars) - 1
                )
                trades.append(trade)
                
        return trades, equity_curve
        
    def _default_entry_signal(
        self,
        bars: List[Dict],
        current_idx: int,
        config: BacktestConfig
    ) -> bool:
        """
        Default entry signal: Simple moving average crossover.
        
        Enter when:
        - Price above 20-bar SMA
        - Volume above average
        - Price making higher highs
        """
        if current_idx < 20:
            return False
            
        current = bars[current_idx]
        
        # Check price filter
        if current["close"] < config.min_price or current["close"] > config.max_price:
            return False
            
        # Calculate 20-bar SMA
        closes = [bars[i]["close"] for i in range(current_idx - 19, current_idx + 1)]
        sma_20 = sum(closes) / len(closes)
        
        # Entry conditions
        price_above_sma = current["close"] > sma_20
        higher_high = current["high"] > bars[current_idx - 1]["high"]
        
        # Volume check
        volumes = [bars[i]["volume"] for i in range(current_idx - 19, current_idx + 1)]
        avg_volume = sum(volumes) / len(volumes)
        volume_ok = current["volume"] > avg_volume * 0.8
        
        return price_above_sma and higher_high and volume_ok
        
    def _check_exit(
        self,
        bar: Dict,
        position: Dict,
        config: BacktestConfig,
        bars_held: int
    ) -> Optional[str]:
        """Check if position should be exited"""
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        
        # Update tracking
        position["highest_price"] = max(position["highest_price"], high)
        position["lowest_price"] = min(position["lowest_price"], low)
        
        # Check stop loss
        if low <= position["stop_price"]:
            return ExitReason.STOP.value
            
        # Check target
        if high >= position["target_price"]:
            return ExitReason.TARGET.value
            
        # Check trailing stop
        if config.use_trailing_stop:
            trail_stop = position["highest_price"] * (1 - config.trailing_stop_pct / 100)
            if low <= trail_stop:
                return ExitReason.TRAILING_STOP.value
                
        # Check time stop
        if bars_held >= config.max_bars_to_hold:
            return ExitReason.TIME.value
            
        return None
        
    def _close_position(
        self,
        position: Dict,
        exit_price: float,
        exit_reason: str,
        exit_timestamp: str,
        exit_bar_idx: int
    ) -> BacktestTrade:
        """Close a position and create trade record"""
        entry_price = position["entry_price"]
        shares = position["shares"]
        
        pnl = (exit_price - entry_price) * shares
        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
        
        # Calculate R multiple
        risk_per_share = entry_price - position["stop_price"]
        r_multiple = (exit_price - entry_price) / risk_per_share if risk_per_share > 0 else 0
        
        # Calculate excursions
        mfe = (position["highest_price"] - entry_price) * shares
        mae = (position["lowest_price"] - entry_price) * shares
        
        return BacktestTrade(
            id=position["id"],
            direction="long",
            entry_date=position["entry_date"],
            entry_price=entry_price,
            exit_date=exit_timestamp,
            exit_price=exit_price,
            shares=shares,
            stop_price=position["stop_price"],
            target_price=position["target_price"],
            pnl=pnl,
            pnl_percent=pnl_percent,
            r_multiple=r_multiple,
            exit_reason=exit_reason,
            bars_held=exit_bar_idx - position["entry_bar_idx"],
            max_favorable_excursion=mfe,
            max_adverse_excursion=mae
        )
        
    def _calculate_metrics(
        self,
        result: BacktestResult,
        trades: List[BacktestTrade],
        equity_curve: List[Dict],
        config: BacktestConfig
    ) -> BacktestResult:
        """Calculate comprehensive backtest metrics"""
        result.trades = [t.to_dict() for t in trades]
        result.equity_curve = equity_curve
        result.total_trades = len(trades)
        
        if not trades:
            return result
            
        # Win/loss stats
        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl < 0]
        
        result.winning_trades = len(winners)
        result.losing_trades = len(losers)
        result.win_rate = len(winners) / len(trades) if trades else 0
        
        # P&L stats
        pnls = [t.pnl for t in trades]
        result.total_pnl = sum(pnls)
        result.total_pnl_pct = (result.total_pnl / config.starting_capital) * 100
        result.avg_pnl = result.total_pnl / len(trades)
        
        if winners:
            result.avg_winner = sum(t.pnl for t in winners) / len(winners)
            result.largest_winner = max(t.pnl for t in winners)
        if losers:
            result.avg_loser = sum(t.pnl for t in losers) / len(losers)
            result.largest_loser = min(t.pnl for t in losers)
            
        # Profit factor
        gross_profit = sum(t.pnl for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # R metrics
        rs = [t.r_multiple for t in trades]
        result.total_r = sum(rs)
        result.avg_r = result.total_r / len(trades)
        result.expectancy = (result.win_rate * result.avg_winner) - ((1 - result.win_rate) * abs(result.avg_loser)) if result.avg_loser else 0
        
        # Time metrics
        bars_held = [t.bars_held for t in trades]
        result.avg_bars_held = sum(bars_held) / len(trades)
        if winners:
            result.avg_winner_bars = sum(t.bars_held for t in winners) / len(winners)
        if losers:
            result.avg_loser_bars = sum(t.bars_held for t in losers) / len(losers)
            
        # Drawdown
        if equity_curve:
            equities = [e["equity"] for e in equity_curve]
            peak = equities[0]
            max_dd = 0
            max_dd_pct = 0
            
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = peak - eq
                dd_pct = (dd / peak) * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
                max_dd_pct = max(max_dd_pct, dd_pct)
                
            result.max_drawdown = max_dd
            result.max_drawdown_pct = max_dd_pct
            
        return result
        
    async def get_backtest_results(
        self,
        symbol: str = None,
        limit: int = 20
    ) -> List[BacktestResult]:
        """Get stored backtest results"""
        if self._backtest_results_col is None:
            return []
            
        query = {}
        if symbol:
            query["symbol"] = symbol.upper()
            
        docs = list(
            self._backtest_results_col
            .find(query, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        
        return [BacktestResult(**d) for d in docs]
        
    async def get_backtest_result(self, backtest_id: str) -> Optional[BacktestResult]:
        """Get a specific backtest result"""
        if self._backtest_results_col is None:
            return None
            
        doc = self._backtest_results_col.find_one({"id": backtest_id}, {"_id": 0})
        if doc:
            return BacktestResult(**doc)
            
        return None
        
    async def delete_backtest(self, backtest_id: str) -> bool:
        """Delete a backtest result"""
        if self._backtest_results_col is None:
            return False
            
        result = self._backtest_results_col.delete_one({"id": backtest_id})
        return result.deleted_count > 0
        
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        count = 0
        if self._backtest_results_col is not None:
            count = self._backtest_results_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "backtests_stored": count
        }


# Singleton
_backtest_engine: Optional[BacktestEngine] = None


def get_backtest_engine() -> BacktestEngine:
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine()
    return _backtest_engine


def init_backtest_engine(
    db=None,
    historical_data_service=None,
    tqs_engine=None
) -> BacktestEngine:
    engine = get_backtest_engine()
    if db is not None:
        engine.set_db(db)
    if historical_data_service is not None:
        engine.set_historical_data_service(historical_data_service)
    if tqs_engine is not None:
        engine.set_tqs_engine(tqs_engine)
    return engine
