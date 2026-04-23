"""
Historical Simulation Engine - Full SentCom Bot Backtesting
============================================================

This engine runs the complete SentCom trading bot simulation on historical data:
1. Fetches 1 year of historical data for all US stocks
2. Applies first-gate filters (ADV, RVOL, price criteria)
3. Runs the full AI agent pipeline (Debate, Risk, Institutional, Time-Series)
4. Simulates trade execution and position management
5. Tracks all decisions and outcomes for learning

Usage:
    engine = HistoricalSimulationEngine(db)
    await engine.initialize()
    job_id = await engine.start_simulation(config)
    status = await engine.get_job_status(job_id)
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import json

logger = logging.getLogger(__name__)


class SimulationStatus(str, Enum):
    """Status of a simulation job"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SimulationConfig:
    """Configuration for a historical simulation run"""
    # Time period
    start_date: str  # ISO format
    end_date: str    # ISO format
    
    # Stock filters (first gate)
    min_adv: int = 100_000          # Minimum average daily volume
    min_price: float = 5.0           # Minimum stock price
    max_price: float = 500.0         # Maximum stock price
    min_rvol: float = 0.8            # Minimum relative volume
    
    # Universe selection
    universe: str = "all"            # "all", "sp500", "nasdaq100", "custom"
    custom_symbols: List[str] = field(default_factory=list)
    
    # Simulation settings
    starting_capital: float = 100_000.0
    max_position_pct: float = 10.0   # Max % of capital per trade
    max_open_positions: int = 5
    use_ai_agents: bool = True       # Use full AI consultation pipeline
    
    # Data source
    data_source: str = "alpaca"      # "alpaca", "ib", "mongodb"
    
    # Multi-timeframe support
    bar_size: str = "1 day"          # "1 min", "5 mins", "15 mins", "1 hour", "1 day"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SimulatedTrade:
    """A simulated trade with full context"""
    id: str
    symbol: str
    setup_type: str
    direction: str  # "long" or "short"
    
    # Entry
    entry_date: str
    entry_price: float
    shares: int
    entry_reason: str
    
    # AI Agent decisions
    ai_consultation: Dict = field(default_factory=dict)
    timeseries_forecast: Dict = field(default_factory=dict)
    debate_result: Dict = field(default_factory=dict)
    risk_assessment: Dict = field(default_factory=dict)
    
    # Exit (filled when trade closes)
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    
    # P&L
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None
    
    # Status
    status: str = "open"  # open, closed, stopped_out
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass 
class SimulationJob:
    """A simulation job with status and results"""
    id: str
    config: SimulationConfig
    status: SimulationStatus = SimulationStatus.PENDING
    
    # Progress
    current_date: Optional[str] = None
    symbols_processed: int = 0
    symbols_total: int = 0
    trades_simulated: int = 0
    
    # Timing
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    estimated_completion: Optional[str] = None
    
    # Results summary
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Error tracking
    error_message: Optional[str] = None
    errors: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        import math
        d = asdict(self)
        d['config'] = self.config.to_dict()
        d['status'] = self.status.value
        # Sanitize float values to be JSON-safe (no inf/nan)
        for key, value in d.items():
            if isinstance(value, float):
                if math.isinf(value) or math.isnan(value):
                    d[key] = 0.0
        return d


class HistoricalSimulationEngine:
    """
    Engine for running complete SentCom bot simulations on historical data.
    """
    
    # Collections
    JOBS_COLLECTION = "simulation_jobs"
    TRADES_COLLECTION = "simulated_trades"
    DECISIONS_COLLECTION = "simulation_decisions"
    
    def __init__(self, db=None):
        self._db = db
        self._running_jobs: Dict[str, asyncio.Task] = {}
        
        # Services (injected during initialization)
        self._alpaca_service = None
        self._ib_service = None
        self._timeseries_model = None
        self._trade_consultation = None
        self._scoring_engine = None
        
        # Symbol universe cache
        self._all_us_symbols: List[str] = []
        self._sp500_symbols: List[str] = []
        
        logger.info("HistoricalSimulationEngine initialized")
    
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        
    def set_services(
        self,
        alpaca_service=None,
        ib_service=None,
        timeseries_model=None,
        trade_consultation=None,
        scoring_engine=None
    ):
        """Inject required services"""
        self._alpaca_service = alpaca_service
        self._ib_service = ib_service
        self._timeseries_model = timeseries_model
        self._trade_consultation = trade_consultation
        self._scoring_engine = scoring_engine
        
    async def initialize(self):
        """Initialize engine and load symbol universes"""
        logger.info("Initializing Historical Simulation Engine...")
        
        # Load US symbol universe
        await self._load_symbol_universes()
        
        # Ensure indexes
        if self._db is not None:
            self._db[self.JOBS_COLLECTION].create_index("id", unique=True)
            self._db[self.TRADES_COLLECTION].create_index([("job_id", 1), ("symbol", 1)])
            self._db[self.DECISIONS_COLLECTION].create_index([("job_id", 1), ("date", 1)])
            
        logger.info(f"Engine initialized with {len(self._all_us_symbols)} US symbols")
        
    async def _load_symbol_universes(self):
        """Load symbol lists from Alpaca or cache"""
        try:
            # Try to load from MongoDB cache first
            if self._db is not None:
                cached = self._db["symbol_universe"].find_one({"type": "us_stocks"})
                if cached:
                    self._all_us_symbols = cached.get("symbols", [])
                    logger.info(f"Loaded {len(self._all_us_symbols)} symbols from cache")
                    
            # If no cache, try Alpaca
            if not self._all_us_symbols:
                assets = await self._get_alpaca_assets()
                if assets:
                    self._all_us_symbols = [
                        a['symbol'] for a in assets 
                        if a.get('tradable') and a.get('status') == 'active'
                        and a.get('exchange') in ['NYSE', 'NASDAQ', 'ARCA', 'BATS']
                    ]
                    logger.info(f"Loaded {len(self._all_us_symbols)} tradeable US symbols from Alpaca")
                    
                    # Cache for future use
                    if self._db is not None and self._all_us_symbols:
                        self._db["symbol_universe"].update_one(
                            {"type": "us_stocks"},
                            {"$set": {"symbols": self._all_us_symbols, "updated": datetime.now(timezone.utc).isoformat()}},
                            upsert=True
                        )
                        
            # Load S&P 500 if available
            if self._db is not None:
                sp500 = self._db["symbol_universe"].find_one({"type": "sp500"})
                if sp500:
                    self._sp500_symbols = sp500.get("symbols", [])
                    
        except Exception as e:
            logger.error(f"Error loading symbol universes: {e}")
            
        # Fallback to default symbols if none loaded
        if not self._all_us_symbols:
            self._all_us_symbols = self._get_default_symbols()
            logger.info(f"Using {len(self._all_us_symbols)} default liquid symbols")
    
    async def _get_alpaca_assets(self) -> List[Dict]:
        """DEPRECATED: now returns the IB universe.

        Kept as a method name so existing call sites keep working; Alpaca has
        been fully removed from the live-data path. Returns the distinct
        symbol list from `ib_historical_data` in Alpaca-asset shape for BC.
        """
        try:
            from services.ib_data_provider import get_live_data_service
            live = get_live_data_service()
            symbols = await live.get_all_assets()
            return [
                {"symbol": s, "name": s, "class": "us_equity", "status": "active", "tradable": True}
                for s in symbols
            ]
        except Exception as e:
            logger.error(f"Error fetching IB universe for simulator: {e}")
            return []
    
    def _get_default_symbols(self) -> List[str]:
        """Default liquid US symbols when API unavailable"""
        return [
            # Tech giants
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "AMD", "INTC", "CRM", "ORCL", "ADBE", "NFLX", "PYPL", "SHOP",
            # Finance
            "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP",
            # Healthcare
            "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT",
            # Consumer
            "WMT", "HD", "COST", "TGT", "NKE", "SBUX", "MCD", "DIS",
            # Energy
            "XOM", "CVX", "COP", "SLB", "EOG", "PXD", "MPC", "VLO",
            # Industrial
            "CAT", "BA", "HON", "UPS", "GE", "MMM", "LMT", "RTX",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV"
        ]
    
    async def start_simulation(self, config: SimulationConfig) -> str:
        """
        Start a new historical simulation job.
        
        Returns:
            job_id: Unique identifier for tracking the job
        """
        job_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        job = SimulationJob(
            id=job_id,
            config=config,
            status=SimulationStatus.PENDING,
            started_at=datetime.now(timezone.utc).isoformat()
        )
        
        # Save job to database
        if self._db is not None:
            self._db[self.JOBS_COLLECTION].insert_one(job.to_dict())
        
        # Start background task
        task = asyncio.create_task(self._run_simulation(job))
        self._running_jobs[job_id] = task
        
        logger.info(f"Started simulation job {job_id}")
        return job_id
    
    async def _run_simulation(self, job: SimulationJob):
        """Main simulation loop"""
        try:
            job.status = SimulationStatus.RUNNING
            self._update_job(job)
            
            config = job.config
            
            # Get symbols to simulate
            symbols = await self._get_simulation_symbols(config)
            job.symbols_total = len(symbols)
            self._update_job(job)
            
            logger.info(f"Simulation {job.id}: Processing {len(symbols)} symbols")
            
            # Parse date range
            start_date = datetime.fromisoformat(config.start_date.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(config.end_date.replace('Z', '+00:00'))
            
            # Initialize simulation state
            capital = config.starting_capital
            open_positions: Dict[str, SimulatedTrade] = {}
            all_trades: List[SimulatedTrade] = []
            equity_curve: List[Dict] = []
            
            # Simulate day by day
            current_date = start_date
            trading_days = 0
            
            while current_date <= end_date:
                # Skip weekends
                if current_date.weekday() >= 5:
                    current_date += timedelta(days=1)
                    continue
                    
                trading_days += 1
                job.current_date = current_date.isoformat()
                
                # Process each symbol
                for i, symbol in enumerate(symbols):
                    if job.status == SimulationStatus.CANCELLED:
                        return
                        
                    try:
                        # Get historical data for this day
                        bars = await self._get_historical_bars(
                            symbol, 
                            current_date - timedelta(days=60),  # Need lookback
                            current_date,
                            bar_size=config.bar_size
                        )
                        
                        if not bars or len(bars) < 20:
                            continue
                        
                        # Apply first-gate filters
                        if not self._passes_first_gate(bars, config):
                            continue
                        
                        # Check for entry signals
                        signals = await self._detect_signals(symbol, bars, current_date)
                        
                        for signal in signals:
                            # Skip if already have position
                            if symbol in open_positions:
                                continue
                                
                            # Skip if at max positions
                            if len(open_positions) >= config.max_open_positions:
                                continue
                            
                            # Run AI consultation if enabled
                            ai_decision = None
                            if config.use_ai_agents:
                                ai_decision = await self._run_ai_consultation(
                                    symbol, bars, signal, current_date
                                )
                                
                                # Log the decision
                                self._log_decision(job.id, {
                                    "date": current_date.isoformat(),
                                    "symbol": symbol,
                                    "signal": signal,
                                    "ai_decision": ai_decision
                                })
                                
                                # Check if AI recommends passing
                                if ai_decision and ai_decision.get("recommendation") == "pass":
                                    continue
                            
                            # Create simulated trade
                            trade = await self._create_simulated_trade(
                                symbol, bars, signal, current_date, 
                                capital, config, ai_decision
                            )
                            
                            if trade:
                                open_positions[symbol] = trade
                                all_trades.append(trade)
                                job.trades_simulated += 1
                                
                                # Update capital
                                capital -= trade.entry_price * trade.shares
                        
                        # Manage open positions
                        for pos_symbol, position in list(open_positions.items()):
                            if pos_symbol == symbol:
                                exit_result = await self._check_exit(
                                    position, bars, current_date
                                )
                                
                                if exit_result:
                                    # Close position
                                    position.exit_date = current_date.isoformat()
                                    position.exit_price = exit_result["price"]
                                    position.exit_reason = exit_result["reason"]
                                    position.status = "closed"
                                    
                                    # Calculate P&L
                                    if position.direction == "long":
                                        pnl = (position.exit_price - position.entry_price) * position.shares
                                    else:
                                        pnl = (position.entry_price - position.exit_price) * position.shares
                                        
                                    position.realized_pnl = pnl
                                    position.realized_pnl_pct = pnl / (position.entry_price * position.shares) * 100
                                    
                                    # Update capital
                                    capital += position.exit_price * position.shares + pnl
                                    
                                    # Remove from open positions
                                    del open_positions[pos_symbol]
                                    
                                    # Save trade
                                    self._save_trade(job.id, position)
                                    
                    except Exception as e:
                        logger.warning(f"Error processing {symbol} on {current_date}: {e}")
                        job.errors.append({
                            "date": current_date.isoformat(),
                            "symbol": symbol,
                            "error": str(e)
                        })
                
                # Record equity curve
                open_value = 0.0
                for p in open_positions.values():
                    close_price = await self._get_close_price(p.symbol, current_date)
                    open_value += p.shares * (close_price if close_price else p.entry_price)
                    
                equity_curve.append({
                    "date": current_date.isoformat(),
                    "cash": capital,
                    "positions_value": open_value,
                    "total_equity": capital + open_value
                })
                
                # Update progress
                job.symbols_processed = len(symbols)
                self._update_job(job)
                
                # Progress to next day
                current_date += timedelta(days=1)
                
                # Yield to event loop periodically
                if trading_days % 5 == 0:
                    await asyncio.sleep(0.1)
            
            # Close any remaining positions at end
            for symbol, position in open_positions.items():
                bars = await self._get_historical_bars(symbol, end_date - timedelta(days=5), end_date, bar_size=config.bar_size)
                if bars:
                    position.exit_date = end_date.isoformat()
                    position.exit_price = bars[-1].get("close", position.entry_price)
                    position.exit_reason = "simulation_end"
                    position.status = "closed"
                    
                    if position.direction == "long":
                        pnl = (position.exit_price - position.entry_price) * position.shares
                    else:
                        pnl = (position.entry_price - position.exit_price) * position.shares
                        
                    position.realized_pnl = pnl
                    position.realized_pnl_pct = pnl / (position.entry_price * position.shares) * 100
                    
                    self._save_trade(job.id, position)
            
            # Calculate final statistics
            self._calculate_statistics(job, all_trades, equity_curve, config.starting_capital)
            
            job.status = SimulationStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc).isoformat()
            self._update_job(job)
            
            logger.info(f"Simulation {job.id} completed: {job.total_trades} trades, "
                       f"{job.win_rate:.1f}% win rate, ${job.total_pnl:.2f} P&L")
            
        except Exception as e:
            logger.error(f"Simulation {job.id} failed: {e}", exc_info=True)
            job.status = SimulationStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc).isoformat()
            self._update_job(job)
    
    async def _get_simulation_symbols(self, config: SimulationConfig) -> List[str]:
        """Get list of symbols to simulate based on config"""
        if config.universe == "custom" and config.custom_symbols:
            return config.custom_symbols
        elif config.universe == "sp500":
            return self._sp500_symbols or self._get_default_symbols()[:100]
        elif config.universe == "nasdaq100":
            # Would need to load NASDAQ 100 list
            return self._get_default_symbols()[:100]
        else:
            # All US stocks - filter by basic criteria first
            return self._all_us_symbols or self._get_default_symbols()
    
    async def _get_historical_bars(
        self, 
        symbol: str, 
        start: datetime, 
        end: datetime,
        bar_size: str = "1 day"
    ) -> List[Dict]:
        """Get historical OHLCV bars for a symbol with specified bar size from unified ib_historical_data"""
        try:
            if self._db is not None:
                # Use unified ib_historical_data collection (contains both IB and migrated Alpaca data)
                ib_bars = list(self._db["ib_historical_data"].find(
                    {
                        "symbol": symbol,
                        "bar_size": bar_size,
                        "date": {
                            "$gte": start.strftime("%Y-%m-%d") if bar_size == "1 day" else start.isoformat(),
                            "$lte": end.strftime("%Y-%m-%d") if bar_size == "1 day" else end.isoformat()
                        }
                    },
                    {"_id": 0}
                ).sort("date", 1))
                
                if ib_bars and len(ib_bars) >= 5:
                    # Convert IB format to simulation format
                    return [{
                        "timestamp": bar.get("date"),
                        "open": bar.get("open"),
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "close": bar.get("close"),
                        "volume": bar.get("volume"),
                        "symbol": symbol,
                        "bar_size": bar_size
                    } for bar in ib_bars]
            
            # Fetch from Alpaca if not in database (only supports daily) and cache to ib_historical_data
            if self._alpaca_service and bar_size == "1 day":
                bars = await self._fetch_alpaca_bars(symbol, start, end)
                
                # Cache the data to unified collection
                if bars and self._db:
                    from datetime import timezone as tz
                    for bar in bars:
                        timestamp = bar.get("timestamp", "")
                        date_str = timestamp[:10] if isinstance(timestamp, str) else timestamp.strftime("%Y-%m-%d")
                        self._db["ib_historical_data"].update_one(
                            {"symbol": symbol, "bar_size": "1 day", "date": date_str},
                            {"$set": {
                                "symbol": symbol,
                                "bar_size": "1 day", 
                                "date": date_str,
                                "open": bar.get("open"),
                                "high": bar.get("high"),
                                "low": bar.get("low"),
                                "close": bar.get("close"),
                                "volume": bar.get("volume"),
                                "source": "alpaca",
                                "collected_at": datetime.now(tz.utc).isoformat()
                            }},
                            upsert=True
                        )
                
                return bars
                
        except Exception as e:
            logger.warning(f"Error fetching bars for {symbol}: {e}")
        
        return []
    
    async def _fetch_alpaca_bars(
        self, 
        symbol: str, 
        start: datetime, 
        end: datetime
    ) -> List[Dict]:
        """DEPRECATED name — now reads bars from ib_historical_data.

        Kept as a method name so existing call sites keep working. Alpaca is
        fully removed from the live-data path. Delegates to IBDataProvider,
        which reads the 178M-row `ib_historical_data` collection.
        """
        try:
            from services.ib_data_provider import get_live_data_service
            live = get_live_data_service()
            span_days = max(1, int((end - start).total_seconds() / 86400))
            limit = min(span_days + 5, 10000)
            bars = await live.get_bars(symbol=symbol, timeframe="1Day", limit=limit)
            # Filter to requested window
            out = []
            for b in bars:
                try:
                    ts = datetime.fromisoformat(str(b["timestamp"]).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=start.tzinfo)
                    if start <= ts <= end:
                        out.append({
                            "timestamp": b["timestamp"],
                            "open": b["open"],
                            "high": b["high"],
                            "low": b["low"],
                            "close": b["close"],
                            "volume": b["volume"],
                            "vwap": b.get("vwap") or b["close"],
                        })
                except Exception:
                    continue
            return out
        except Exception as e:
            logger.warning(f"IB bar fetch error for {symbol}: {e}")
        return []
    
    def _passes_first_gate(self, bars: List[Dict], config: SimulationConfig) -> bool:
        """Check if stock passes first-gate filters"""
        if not bars:
            return False
            
        # Get latest bar
        latest = bars[-1]
        price = latest.get("close", 0)
        
        # Price filter
        if price < config.min_price or price > config.max_price:
            return False
        
        # ADV filter (average of last 20 days volume)
        if len(bars) >= 20:
            adv = sum(b.get("volume", 0) for b in bars[-20:]) / 20
            if adv < config.min_adv:
                return False
        
        # RVOL filter (today's volume vs 20-day average)
        if len(bars) >= 20:
            avg_vol = sum(b.get("volume", 0) for b in bars[-21:-1]) / 20
            today_vol = bars[-1].get("volume", 0)
            rvol = today_vol / avg_vol if avg_vol > 0 else 0
            if rvol < config.min_rvol:
                return False
        
        return True
    
    async def _detect_signals(
        self, 
        symbol: str, 
        bars: List[Dict], 
        date: datetime
    ) -> List[Dict]:
        """Detect trading signals from price action"""
        signals = []
        
        if len(bars) < 20:
            return signals
            
        latest = bars[-1]
        
        close = latest.get("close", 0)
        open_price = latest.get("open", 0)
        high = latest.get("high", 0)
        low = latest.get("low", 0)
        volume = latest.get("volume", 0)
        
        # Calculate indicators
        closes = [b.get("close", 0) for b in bars]
        
        # 20-day SMA
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else close
        
        # RSI (14-period)
        rsi = self._calculate_rsi(closes, 14)
        
        # VWAP approximation
        vwap = latest.get("vwap", close)
        
        # Average volume
        avg_vol = sum(b.get("volume", 0) for b in bars[-20:]) / 20
        rvol = volume / avg_vol if avg_vol > 0 else 1
        
        # Detect setups
        
        # ===== GAP STRATEGIES =====
        
        # Gap and Go (>2% gap up with volume) - Your favorite!
        if len(bars) >= 2:
            prev_close = bars[-2].get("close", 0)
            gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            
            # Gap and Go LONG (gap up)
            if gap_pct > 2 and rvol > 1.5:
                signals.append({
                    "type": "gap_and_go",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": low * 0.98,
                    "target_price": close * 1.03,
                    "strength": min(gap_pct / 5 * 100, 100)
                })
            
            # Gap Give and Go (gap fills partially then resumes)
            if gap_pct > 3 and close > (prev_close + open_price) / 2:  # Holding above 50% of gap
                if close > open_price and rvol > 1.2:  # Green candle with volume
                    signals.append({
                        "type": "gap_give_go",
                        "direction": "long",
                        "entry_price": close,
                        "stop_price": prev_close * 1.005,  # Just above gap fill
                        "target_price": open_price * 1.02,  # Back to gap high
                        "strength": 72
                    })
            
            # Gap Down Reversal (SHORT setup)
            if gap_pct < -2 and rvol > 1.5:
                if close < open_price:  # Red candle confirming weakness
                    signals.append({
                        "type": "gap_down_fade",
                        "direction": "short",
                        "entry_price": close,
                        "stop_price": high * 1.02,
                        "target_price": close * 0.97,
                        "strength": 65
                    })
        
        # ===== VWAP STRATEGIES =====
        
        # VWAP Bounce (price pulls back to VWAP and bounces)
        if close > sma20 and abs(low - vwap) / vwap < 0.005:  # Within 0.5% of VWAP
            if close > open_price:  # Green candle
                signals.append({
                    "type": "vwap_bounce",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": vwap * 0.99,
                    "target_price": close * 1.02,
                    "strength": 70
                })
        
        # First VWAP Pullback (INT-35) - First touch of VWAP after move
        if close > sma20 and low <= vwap * 1.002 and close > vwap:
            if rvol > 1.0:
                signals.append({
                    "type": "first_vwap_pullback",
                    "direction": "long", 
                    "entry_price": close,
                    "stop_price": vwap * 0.985,
                    "target_price": close * 1.025,
                    "strength": 75
                })
        
        # VWAP Fade (price extended above VWAP, mean reversion SHORT)
        if close > vwap * 1.03 and rsi > 70:  # >3% above VWAP and overbought
            signals.append({
                "type": "vwap_fade",
                "direction": "short",
                "entry_price": close,
                "stop_price": high * 1.01,
                "target_price": vwap * 1.01,  # Back toward VWAP
                "strength": 65
            })
        
        # ===== MOMENTUM STRATEGIES =====
        
        # HitchHiker (Gap + Hold + Continuation)
        if len(bars) >= 2:
            prev_close = bars[-2].get("close", 0)
            gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if gap_pct > 2 and close > vwap and rvol >= 2.0:
                dist_from_high = (high - close) / close * 100
                if dist_from_high < 1.5:  # Consolidating near highs
                    signals.append({
                        "type": "hitchhiker",
                        "direction": "long",
                        "entry_price": close,
                        "stop_price": vwap * 0.98,
                        "target_price": high * 1.03,
                        "strength": 80
                    })
        
        # Trend Momentum Continuation
        if close > sma20 and closes[-1] > closes[-2] > closes[-3]:  # 3 green days
            if rvol > 1.0:
                signals.append({
                    "type": "trend_continuation",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": sma20 * 0.98,
                    "target_price": close * 1.04,
                    "strength": 68
                })
        
        # ===== REVERSAL STRATEGIES =====
        
        # Oversold bounce (RSI < 30 with reversal)
        if rsi < 30 and close > open_price:
            signals.append({
                "type": "oversold_bounce",
                "direction": "long",
                "entry_price": close,
                "stop_price": low * 0.98,
                "target_price": close * 1.04,
                "strength": 60
            })
        
        # Overbought Fade (RSI > 70 with reversal)
        if rsi > 70 and close < open_price:
            signals.append({
                "type": "overbought_fade",
                "direction": "short",
                "entry_price": close,
                "stop_price": high * 1.02,
                "target_price": close * 0.96,
                "strength": 60
            })
        
        # ===== BREAKOUT STRATEGIES =====
        
        # Breakout (new 20-day high with volume)
        high_20 = max(b.get("high", 0) for b in bars[-21:-1]) if len(bars) > 20 else high
        if close > high_20 and rvol > 1.2:
            signals.append({
                "type": "breakout",
                "direction": "long",
                "entry_price": close,
                "stop_price": high_20 * 0.98,
                "target_price": close * 1.05,
                "strength": 75
            })
        
        # Breakdown (new 20-day low with volume) - SHORT
        low_20 = min(b.get("low", float('inf')) for b in bars[-21:-1]) if len(bars) > 20 else low
        if close < low_20 and rvol > 1.2:
            signals.append({
                "type": "breakdown",
                "direction": "short",
                "entry_price": close,
                "stop_price": low_20 * 1.02,
                "target_price": close * 0.95,
                "strength": 75
            })
        
        # ===== CONSOLIDATION/FLAG STRATEGIES =====
        
        # Bull Flag (uptrend, tight consolidation, breakout)
        if len(bars) >= 5:
            # Check for prior uptrend (5-day gain)
            five_day_return = (close - bars[-5].get("close", close)) / bars[-5].get("close", close) * 100
            # Check for tight range in last 3 days
            recent_range = max(b.get("high", 0) for b in bars[-3:]) - min(b.get("low", float('inf')) for b in bars[-3:])
            avg_range = sum(b.get("high", 0) - b.get("low", 0) for b in bars[-10:-3]) / 7 if len(bars) >= 10 else recent_range
            
            if five_day_return > 5 and recent_range < avg_range * 0.6:  # Tight consolidation after run
                if close > open_price:  # Breakout candle
                    signals.append({
                        "type": "bull_flag",
                        "direction": "long",
                        "entry_price": close,
                        "stop_price": min(b.get("low", close) for b in bars[-3:]) * 0.99,
                        "target_price": close * 1.05,
                        "strength": 78
                    })
        
        # Puppy Dog Consolidation (tight range after gap)
        if len(bars) >= 3:
            recent_range_pct = (max(b.get("high", 0) for b in bars[-3:]) - min(b.get("low", float('inf')) for b in bars[-3:])) / close * 100
            if recent_range_pct < 3 and close > sma20:  # Very tight, in uptrend
                signals.append({
                    "type": "puppy_dog",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": min(b.get("low", close) for b in bars[-3:]) * 0.99,
                    "target_price": close * 1.03,
                    "strength": 65
                })
        
        # ============================================================
        # ADDITIONAL STRATEGIES (From Your 77 Strategies)
        # ============================================================
        
        # Calculate additional indicators
        prev_close = bars[-2].get("close", 0) if len(bars) >= 2 else close
        gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
        ema9 = self._calculate_ema(closes, 9)
        ema20_val = self._calculate_ema(closes, 20)
        ema50 = self._calculate_ema(closes, 50) if len(closes) >= 50 else sma20
        
        # Gap Pick and Roll
        if len(bars) >= 2 and gap_pct > 2 and gap_pct < 5:
            if close < open_price and close > prev_close:
                signals.append({
                    "type": "gap_pick_roll",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": prev_close * 0.99,
                    "target_price": close * 1.025,
                    "strength": 68
                })
        
        # Gap Fill Swing
        if len(bars) >= 2 and gap_pct < -3 and close > open_price:
            signals.append({
                "type": "gap_fill_swing",
                "direction": "long",
                "entry_price": close,
                "stop_price": low * 0.98,
                "target_price": prev_close,
                "strength": 65
            })
        
        # Range-to-Trend Transition
        if len(bars) >= 10:
            recent_highs = [b.get("high", 0) for b in bars[-10:]]
            if close > max(recent_highs[:-1]) and rvol > 1.2:
                range_10 = max(recent_highs) - min(b.get("low", float('inf')) for b in bars[-10:])
                signals.append({
                    "type": "range_to_trend",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": close - (range_10 * 0.5),
                    "target_price": close + range_10,
                    "strength": 72
                })
        
        # Daily Trend Following
        if close > ema20_val > ema50 and close > sma20 and rvol > 0.8:
            signals.append({
                "type": "daily_trend",
                "direction": "long",
                "entry_price": close,
                "stop_price": ema20_val * 0.97,
                "target_price": close * 1.05,
                "strength": 65
            })
        
        # ORB (adapted for daily)
        if len(bars) >= 2 and gap_pct > 1 and close > open_price * 1.01 and rvol > 1.5:
            signals.append({
                "type": "orb",
                "direction": "long",
                "entry_price": close,
                "stop_price": open_price * 0.99,
                "target_price": close * 1.03,
                "strength": 75
            })
        
        # HOD Break
        if close == high and rvol > 1.3:
            signals.append({
                "type": "hod_break",
                "direction": "long",
                "entry_price": close,
                "stop_price": low * 0.98,
                "target_price": close * 1.04,
                "strength": 70
            })
        
        # Base Breakout (Multi-Week)
        if len(bars) >= 20:
            high_20 = max(b.get("high", 0) for b in bars[-20:])
            low_20 = min(b.get("low", float('inf')) for b in bars[-20:])
            range_pct = (high_20 - low_20) / close * 100
            if range_pct < 10 and close > high_20 and rvol > 1.5:
                signals.append({
                    "type": "base_breakout",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": low_20,
                    "target_price": close * 1.08,
                    "strength": 80
                })
        
        # Buy the Dip
        if close > ema50 and low < ema20_val and close > ema20_val and close > open_price:
            signals.append({
                "type": "buy_the_dip",
                "direction": "long",
                "entry_price": close,
                "stop_price": ema20_val * 0.97,
                "target_price": close * 1.04,
                "strength": 72
            })
        
        # Breakout Retest
        if len(bars) >= 5:
            prev_high = max(b.get("high", 0) for b in bars[-6:-1])
            if bars[-3].get("close", 0) > prev_high:
                if low < prev_high * 1.01 and close > prev_high:
                    signals.append({
                        "type": "breakout_retest",
                        "direction": "long",
                        "entry_price": close,
                        "stop_price": prev_high * 0.98,
                        "target_price": close * 1.05,
                        "strength": 75
                    })
        
        # Exhaustion Reversal
        if len(bars) >= 2:
            prev_range = bars[-2].get("high", 0) - bars[-2].get("low", 0)
            day_range = high - low
            if day_range > prev_range * 2 and close < open_price and rsi > 70:
                signals.append({
                    "type": "exhaustion_reversal",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": high * 1.01,
                    "target_price": close * 0.96,
                    "strength": 70
                })
        
        # Stop Hunt Reversal
        if len(bars) >= 20:
            high_20 = max(b.get("high", 0) for b in bars[-21:-1])
            if high > high_20 and close < high_20:
                signals.append({
                    "type": "stop_hunt_reversal",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": high * 1.01,
                    "target_price": close * 0.96,
                    "strength": 72
                })
        
        # Bear Flag
        if len(bars) >= 5:
            five_day_return = (close - bars[-5].get("close", close)) / bars[-5].get("close", close) * 100
            recent_range = max(b.get("high", 0) for b in bars[-3:]) - min(b.get("low", float('inf')) for b in bars[-3:])
            avg_range = sum(b.get("high", 0) - b.get("low", 0) for b in bars[-10:-3]) / 7 if len(bars) >= 10 else recent_range
            if five_day_return < -5 and recent_range < avg_range * 0.6 and close < open_price:
                signals.append({
                    "type": "bear_flag",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": max(b.get("high", close) for b in bars[-3:]) * 1.01,
                    "target_price": close * 0.95,
                    "strength": 78
                })
        
        # Big Dog Consolidation
        if len(bars) >= 5:
            range_5 = max(b.get("high", 0) for b in bars[-5:]) - min(b.get("low", float('inf')) for b in bars[-5:])
            range_5_pct = range_5 / close * 100 if close > 0 else 0
            if 3 < range_5_pct < 8 and close > sma20 and close > open_price and rvol > 1.0:
                signals.append({
                    "type": "big_dog",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": min(b.get("low", close) for b in bars[-5:]) * 0.99,
                    "target_price": close * 1.04,
                    "strength": 68
                })
        
        # VCP (Volatility Contraction Pattern)
        if len(bars) >= 20:
            vol_10 = sum(b.get("high", 0) - b.get("low", 0) for b in bars[-10:]) / 10
            vol_20 = sum(b.get("high", 0) - b.get("low", 0) for b in bars[-20:-10]) / 10
            if vol_10 < vol_20 * 0.6 and close > sma20 and close > open_price:
                signals.append({
                    "type": "vcp",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": close - (vol_10 * 2),
                    "target_price": close * 1.06,
                    "strength": 75
                })
        
        # 9 EMA Cross
        if len(bars) >= 2 and close > ema9 and bars[-2].get("close", 0) < ema9 and rvol > 1.0:
            signals.append({
                "type": "9_ema_cross",
                "direction": "long",
                "entry_price": close,
                "stop_price": ema9 * 0.98,
                "target_price": close * 1.03,
                "strength": 65
            })
        
        # MA Crossover
        if len(bars) >= 3:
            prev_ema9 = self._calculate_ema([b.get("close", 0) for b in bars[:-1]], 9)
            prev_ema20 = self._calculate_ema([b.get("close", 0) for b in bars[:-1]], 20)
            if ema9 > ema20_val and prev_ema9 <= prev_ema20:
                signals.append({
                    "type": "ma_crossover",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": ema20_val * 0.97,
                    "target_price": close * 1.05,
                    "strength": 70
                })
            if ema9 < ema20_val and prev_ema9 >= prev_ema20:
                signals.append({
                    "type": "ma_crossover_short",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": ema20_val * 1.03,
                    "target_price": close * 0.95,
                    "strength": 70
                })
        
        # Range Break
        if len(bars) >= 10:
            range_high = max(b.get("high", 0) for b in bars[-10:])
            range_low = min(b.get("low", float('inf')) for b in bars[-10:])
            range_mid = (range_high + range_low) / 2
            
            if close > range_high and rvol > 1.2:
                signals.append({
                    "type": "range_break",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": range_mid,
                    "target_price": close + (range_high - range_low),
                    "strength": 72
                })
            
            # Range Fade at Top
            if high >= range_high * 0.99 and close < open_price:
                signals.append({
                    "type": "range_fade_top",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": range_high * 1.02,
                    "target_price": range_mid,
                    "strength": 65
                })
            
            # Range Fade at Bottom
            if low <= range_low * 1.01 and close > open_price:
                signals.append({
                    "type": "range_fade_bottom",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": range_low * 0.98,
                    "target_price": range_mid,
                    "strength": 65
                })
        
        # Volume Capitulation
        if rvol > 3.0:
            if close < open_price and (high - close) > (close - low) * 2:
                signals.append({
                    "type": "volume_capitulation_short",
                    "direction": "short",
                    "entry_price": close,
                    "stop_price": high * 1.01,
                    "target_price": close * 0.95,
                    "strength": 70
                })
            if close > open_price and (close - low) > (high - close) * 2:
                signals.append({
                    "type": "volume_capitulation_long",
                    "direction": "long",
                    "entry_price": close,
                    "stop_price": low * 0.99,
                    "target_price": close * 1.05,
                    "strength": 70
                })
        
        return signals
    
    def _calculate_ema(self, closes: List[float], period: int) -> float:
        """Calculate EMA"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        
        for price in closes[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(closes) < period + 1:
            return 50
            
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    async def _run_ai_consultation(
        self,
        symbol: str,
        bars: List[Dict],
        signal: Dict,
        date: datetime
    ) -> Optional[Dict]:
        """Run full AI agent consultation pipeline"""
        consultation = {
            "symbol": symbol,
            "date": date.isoformat(),
            "signal": signal,
            "recommendation": "proceed",
            "confidence": 0.5,
            "agents": {}
        }
        
        try:
            # Time-Series AI forecast
            if self._timeseries_model:
                # Format bars for prediction (most recent first)
                recent_bars = bars[-50:][::-1] if len(bars) >= 50 else bars[::-1]
                forecast = self._timeseries_model.predict(recent_bars, symbol)
                consultation["agents"]["timeseries"] = forecast.to_dict() if forecast else None
                
                # Adjust recommendation based on forecast
                if forecast:
                    if signal["direction"] == "long" and forecast.direction == "down":
                        consultation["confidence"] -= 0.2
                    elif signal["direction"] == "short" and forecast.direction == "up":
                        consultation["confidence"] -= 0.2
                    elif signal["direction"] == forecast.direction:
                        consultation["confidence"] += 0.1
            
            # Trade consultation service (if available)
            if self._trade_consultation:
                try:
                    full_consultation = await self._trade_consultation.consult_on_trade({
                        "symbol": symbol,
                        "setup_type": signal["type"],
                        "direction": signal["direction"],
                        "entry_price": signal["entry_price"],
                        "bars": bars[-50:] if len(bars) >= 50 else bars
                    })
                    
                    if full_consultation:
                        consultation["agents"]["debate"] = full_consultation.get("debate")
                        consultation["agents"]["risk"] = full_consultation.get("risk_assessment")
                        consultation["agents"]["institutional"] = full_consultation.get("institutional_context")
                        
                        # Use consultation recommendation
                        rec = full_consultation.get("combined_recommendation", "proceed")
                        consultation["recommendation"] = rec
                        consultation["confidence"] = full_consultation.get("confidence_score", 0.5)
                        
                except Exception as e:
                    logger.warning(f"Trade consultation error: {e}")
            
            # Final decision
            if consultation["confidence"] < 0.3:
                consultation["recommendation"] = "pass"
            elif consultation["confidence"] < 0.5:
                consultation["recommendation"] = "reduce_size"
                
        except Exception as e:
            logger.warning(f"AI consultation error for {symbol}: {e}")
            
        return consultation
    
    async def _create_simulated_trade(
        self,
        symbol: str,
        bars: List[Dict],
        signal: Dict,
        date: datetime,
        capital: float,
        config: SimulationConfig,
        ai_decision: Optional[Dict]
    ) -> Optional[SimulatedTrade]:
        """Create a simulated trade entry"""
        try:
            entry_price = signal["entry_price"]
            
            # Position sizing
            position_value = capital * (config.max_position_pct / 100)
            
            # Reduce size if AI recommends
            if ai_decision and ai_decision.get("recommendation") == "reduce_size":
                position_value *= 0.5
            
            shares = int(position_value / entry_price)
            
            if shares < 1:
                return None
            
            trade = SimulatedTrade(
                id=f"trade_{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                setup_type=signal["type"],
                direction=signal["direction"],
                entry_date=date.isoformat(),
                entry_price=entry_price,
                shares=shares,
                entry_reason=f"{signal['type']} signal with {signal.get('strength', 50):.0f}% strength",
                ai_consultation=ai_decision or {},
                timeseries_forecast=ai_decision.get("agents", {}).get("timeseries") if ai_decision else {},
                debate_result=ai_decision.get("agents", {}).get("debate") if ai_decision else {},
                risk_assessment=ai_decision.get("agents", {}).get("risk") if ai_decision else {}
            )
            
            return trade
            
        except Exception as e:
            logger.warning(f"Error creating trade for {symbol}: {e}")
            return None
    
    async def _check_exit(
        self,
        position: SimulatedTrade,
        bars: List[Dict],
        date: datetime
    ) -> Optional[Dict]:
        """Check if position should be exited"""
        if not bars:
            return None
            
        latest = bars[-1]
        current_price = latest.get("close", position.entry_price)
        high = latest.get("high", current_price)
        low = latest.get("low", current_price)
        
        # Calculate stop/target hits based on direction
        if position.direction == "long":
            stop_hit = low <= position.entry_price * 0.98  # 2% stop
            target_hit = high >= position.entry_price * 1.04  # 4% target
        else:
            stop_hit = high >= position.entry_price * 1.02
            target_hit = low <= position.entry_price * 0.96
        
        # Check exits
        if stop_hit:
            return {
                "price": position.entry_price * (0.98 if position.direction == "long" else 1.02),
                "reason": "stop_loss"
            }
        
        if target_hit:
            return {
                "price": position.entry_price * (1.04 if position.direction == "long" else 0.96),
                "reason": "target_reached"
            }
        
        # Time-based exit (hold max 5 days)
        entry_date = datetime.fromisoformat(position.entry_date.replace('Z', '+00:00'))
        days_held = (date - entry_date).days
        
        if days_held >= 5:
            return {
                "price": current_price,
                "reason": "time_exit"
            }
        
        return None
    
    async def _get_close_price(self, symbol: str, date: datetime) -> Optional[float]:
        """Get closing price for a symbol on a date from unified ib_historical_data"""
        try:
            if self._db is not None:
                date_str = date.strftime("%Y-%m-%d")
                bar = self._db["ib_historical_data"].find_one(
                    {
                        "symbol": symbol,
                        "bar_size": "1 day",
                        "date": {"$lte": date_str}
                    },
                    sort=[("date", -1)]
                )
                if bar:
                    return bar.get("close")
        except Exception:
            pass
        return None
    
    def _calculate_statistics(
        self,
        job: SimulationJob,
        trades: List[SimulatedTrade],
        equity_curve: List[Dict],
        starting_capital: float
    ):
        """Calculate performance statistics"""
        closed_trades = [t for t in trades if t.status == "closed" and t.realized_pnl is not None]
        
        if not closed_trades:
            return
            
        job.total_trades = len(closed_trades)
        job.winning_trades = sum(1 for t in closed_trades if t.realized_pnl > 0)
        job.losing_trades = sum(1 for t in closed_trades if t.realized_pnl <= 0)
        job.total_pnl = sum(t.realized_pnl for t in closed_trades)
        
        job.win_rate = job.winning_trades / job.total_trades if job.total_trades > 0 else 0  # Store as decimal 0.0-1.0
        
        winning = [t.realized_pnl for t in closed_trades if t.realized_pnl > 0]
        losing = [abs(t.realized_pnl) for t in closed_trades if t.realized_pnl <= 0]
        
        job.avg_win = sum(winning) / len(winning) if winning else 0
        job.avg_loss = sum(losing) / len(losing) if losing else 0
        
        total_wins = sum(winning)
        total_losses = abs(sum(losing))  # abs since losses are negative
        job.profit_factor = total_wins / total_losses if total_losses > 0 else 0.0  # Use 0 instead of inf for JSON
        
        # Max drawdown
        if equity_curve:
            equities = [e["total_equity"] for e in equity_curve]
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd
            job.max_drawdown = max_dd
        
        # Sharpe ratio (simplified - daily returns)
        if equity_curve and len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                r = (equity_curve[i]["total_equity"] - equity_curve[i-1]["total_equity"]) / equity_curve[i-1]["total_equity"]
                returns.append(r)
            
            if returns:
                import statistics
                avg_return = sum(returns) / len(returns)
                std_return = statistics.stdev(returns) if len(returns) > 1 else 0
                job.sharpe_ratio = (avg_return * 252) / (std_return * (252 ** 0.5)) if std_return > 0 else 0
    
    def _update_job(self, job: SimulationJob):
        """Update job in database"""
        if self._db is not None:
            self._db[self.JOBS_COLLECTION].update_one(
                {"id": job.id},
                {"$set": job.to_dict()},
                upsert=True
            )
    
    def _save_trade(self, job_id: str, trade: SimulatedTrade):
        """Save trade to database"""
        if self._db is not None:
            trade_dict = trade.to_dict()
            trade_dict["job_id"] = job_id
            self._db[self.TRADES_COLLECTION].update_one(
                {"id": trade.id},
                {"$set": trade_dict},
                upsert=True
            )
    
    def _log_decision(self, job_id: str, decision: Dict):
        """Log AI decision for learning"""
        if self._db is not None:
            decision["job_id"] = job_id
            decision["logged_at"] = datetime.now(timezone.utc).isoformat()
            self._db[self.DECISIONS_COLLECTION].insert_one(decision)
    
    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get status of a simulation job"""
        if self._db is not None:
            job = self._db[self.JOBS_COLLECTION].find_one(
                {"id": job_id},
                {"_id": 0}
            )
            return job
        return None
    
    async def get_job_trades(self, job_id: str, limit: int = 100) -> List[Dict]:
        """Get trades from a simulation job"""
        if self._db is not None:
            return list(self._db[self.TRADES_COLLECTION].find(
                {"job_id": job_id},
                {"_id": 0}
            ).sort("entry_date", -1).limit(limit))
        return []
    
    async def get_job_decisions(self, job_id: str, limit: int = 100) -> List[Dict]:
        """Get AI decisions from a simulation job"""
        if self._db is not None:
            return list(self._db[self.DECISIONS_COLLECTION].find(
                {"job_id": job_id},
                {"_id": 0}
            ).sort("date", -1).limit(limit))
        return []
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running simulation job"""
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            
            if self._db is not None:
                self._db[self.JOBS_COLLECTION].update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": SimulationStatus.CANCELLED.value,
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
            return True
        return False
    
    async def get_all_jobs(self, limit: int = 20) -> List[Dict]:
        """Get all simulation jobs"""
        import math
        
        def sanitize_floats(d):
            """Recursively sanitize float values to be JSON-safe"""
            if isinstance(d, dict):
                return {k: sanitize_floats(v) for k, v in d.items()}
            elif isinstance(d, list):
                return [sanitize_floats(item) for item in d]
            elif isinstance(d, float):
                if math.isinf(d) or math.isnan(d):
                    return 0.0
                return d
            return d
        
        if self._db is not None:
            jobs = list(self._db[self.JOBS_COLLECTION].find(
                {},
                {"_id": 0}
            ).sort("started_at", -1).limit(limit))
            
            # Sanitize all float values and fix legacy win_rate values
            sanitized_jobs = []
            for job in jobs:
                job = sanitize_floats(job)
                # Fix legacy win_rate stored as percentage (100) instead of decimal (1.0)
                if job.get('win_rate', 0) > 1:
                    job['win_rate'] = job['win_rate'] / 100
                sanitized_jobs.append(job)
            
            return sanitized_jobs
        return []


# Singleton instance
_simulation_engine: Optional[HistoricalSimulationEngine] = None


def get_simulation_engine() -> HistoricalSimulationEngine:
    """Get or create the simulation engine instance"""
    global _simulation_engine
    if _simulation_engine is None:
        _simulation_engine = HistoricalSimulationEngine()
    return _simulation_engine


def init_simulation_engine(db, **services):
    """Initialize the simulation engine with dependencies"""
    global _simulation_engine
    _simulation_engine = HistoricalSimulationEngine(db)
    _simulation_engine.set_services(**services)
    return _simulation_engine
