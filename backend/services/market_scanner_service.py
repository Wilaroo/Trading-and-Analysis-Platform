"""
Market-Wide Strategy Scanner Service
====================================
Scans the entire US market for strategy signals with intelligent filtering.

Features:
- Full US market scanning (8000+ stocks)
- Pre-filters based on trade style (intraday, swing, investment)
- Background job processing with progress tracking
- Rate-limited data fetching via Hybrid Data Service
- Results ranked by expected R-multiple
- Sector-based heat maps
- Scheduled nightly scans
"""

import logging
import asyncio
import uuid
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
import os

logger = logging.getLogger(__name__)


class TradeStyle(str, Enum):
    """Trading style determines filters and strategies"""
    INTRADAY = "intraday"
    SWING = "swing"
    INVESTMENT = "investment"
    ALL = "all"


class ScanStatus(str, Enum):
    """Scan job status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScanFilters:
    """Pre-filters for market scanning"""
    trade_style: TradeStyle = TradeStyle.ALL
    
    # Volume filters (based on existing app filters)
    min_adv_intraday: int = 500_000      # Min ADV for intraday setups
    min_adv_swing: int = 100_000         # Min ADV for swing setups
    min_adv_investment: int = 50_000     # Min ADV for investment
    
    # RVOL filter
    min_rvol: float = 0.8                # Relative volume threshold
    
    # Price filters
    min_price: float = 5.0
    max_price: float = 500.0
    
    # Market cap filter (optional)
    min_market_cap: Optional[float] = None  # e.g., 1_000_000_000 for $1B+
    
    # Exclude filters
    exclude_otc: bool = True
    exclude_penny_stocks: bool = True    # < $5
    
    # Sector filter (optional)
    sectors: Optional[List[str]] = None  # e.g., ["Technology", "Healthcare"]
    
    def to_dict(self) -> Dict:
        return {
            "trade_style": self.trade_style.value,
            "min_adv_intraday": self.min_adv_intraday,
            "min_adv_swing": self.min_adv_swing,
            "min_adv_investment": self.min_adv_investment,
            "min_rvol": self.min_rvol,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "min_market_cap": self.min_market_cap,
            "exclude_otc": self.exclude_otc,
            "exclude_penny_stocks": self.exclude_penny_stocks,
            "sectors": self.sectors
        }


@dataclass
class ScanSignal:
    """A detected trading signal"""
    symbol: str
    strategy_id: str
    strategy_name: str
    category: str  # intraday, swing, investment
    signal_date: str
    signal_time: str = ""
    
    # Entry details
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    
    # Quality metrics
    expected_r: float = 0.0              # Expected R-multiple
    signal_strength: float = 0.0         # 0-100 confidence score
    
    # Context
    sector: str = ""
    market_cap: float = 0.0
    avg_volume: int = 0
    rvol: float = 0.0
    
    # Pattern details
    pattern_description: str = ""
    criteria_met: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MarketScanResult:
    """Results of a market-wide scan"""
    id: str
    name: str
    created_at: str
    completed_at: Optional[str] = None
    status: ScanStatus = ScanStatus.PENDING
    
    # Configuration
    trade_style: str = "all"
    strategies_scanned: List[str] = field(default_factory=list)
    filters: Dict = field(default_factory=dict)
    
    # Progress
    total_symbols: int = 0
    symbols_scanned: int = 0
    symbols_passed_filter: int = 0
    progress_pct: float = 0.0
    
    # Results
    signals: List[Dict] = field(default_factory=list)
    signals_by_strategy: Dict[str, int] = field(default_factory=dict)
    signals_by_sector: Dict[str, int] = field(default_factory=dict)
    
    # Top picks
    top_setups: List[Dict] = field(default_factory=list)  # Top 20 by expected R
    
    # Stats
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "status": self.status.value,
            "trade_style": self.trade_style,
            "strategies_scanned": self.strategies_scanned,
            "filters": self.filters,
            "total_symbols": self.total_symbols,
            "symbols_scanned": self.symbols_scanned,
            "symbols_passed_filter": self.symbols_passed_filter,
            "progress_pct": self.progress_pct,
            "total_signals": len(self.signals),
            "signals_by_strategy": self.signals_by_strategy,
            "signals_by_sector": self.signals_by_sector,
            "top_setups": self.top_setups[:20],
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message
        }


class MarketScannerService:
    """
    Service for scanning the entire US market for strategy signals.
    
    Uses:
    - Hybrid Data Service for market data (IB primary, Alpaca fallback)
    - Existing strategy definitions from strategies_data.py
    - Pre-filters from enhanced_scanner.py
    """
    
    # US Market stock lists
    SP500_COUNT = 503
    NASDAQ100_COUNT = 100
    RUSSELL2000_COUNT = 2000
    FULL_MARKET_COUNT = 8000
    
    # Batch processing
    BATCH_SIZE = 50  # Symbols per batch
    BATCH_DELAY = 1.0  # Seconds between batches
    
    # Sector mapping
    SECTORS = [
        "Technology", "Healthcare", "Financial", "Consumer Cyclical",
        "Communication Services", "Industrials", "Consumer Defensive",
        "Energy", "Utilities", "Real Estate", "Basic Materials"
    ]
    
    def __init__(self):
        self._db = None
        self._scans_collection = None
        self._signals_collection = None
        self._symbols_collection = None
        
        self._hybrid_data_service = None
        self._alpaca_service = None
        
        # Running jobs
        self._running_jobs: Dict[str, MarketScanResult] = {}
        self._job_tasks: Dict[str, asyncio.Task] = {}
        
        # Symbol universe cache
        self._symbol_universe: List[Dict] = []
        self._universe_last_updated: Optional[datetime] = None
        self._universe_cache_ttl = 604800  # 7 days (168 hours) - symbols don't change often
        
        # Scheduled scan
        self._nightly_scan_enabled = False
        self._nightly_scan_time = "20:00"  # 8 PM ET after market close
        
    def set_db(self, db):
        """Set MongoDB connection"""
        self._db = db
        if db is not None:
            self._scans_collection = db['market_scans']
            self._signals_collection = db['scan_signals']
            self._symbols_collection = db['us_symbols']
            
            # Create indexes
            self._scans_collection.create_index([("created_at", -1)])
            self._scans_collection.create_index([("status", 1)])
            self._signals_collection.create_index([("scan_id", 1)])
            self._signals_collection.create_index([("symbol", 1)])
            self._signals_collection.create_index([("strategy_id", 1)])
            
            logger.info("MarketScannerService: MongoDB connected")
    
    def set_hybrid_data_service(self, service):
        """Set hybrid data service for market data"""
        self._hybrid_data_service = service
        logger.info("MarketScannerService: Hybrid data service connected")
    
    def set_alpaca_service(self, service):
        """Set Alpaca service for symbol universe"""
        self._alpaca_service = service
        logger.info("MarketScannerService: Alpaca service connected")
    
    async def get_symbol_universe(self, refresh: bool = False) -> List[Dict]:
        """
        Get the full US stock universe with metadata.
        Cached for 7 days (symbols don't change frequently).
        """
        now = datetime.now(timezone.utc)
        
        # Check cache
        if not refresh and self._symbol_universe:
            if self._universe_last_updated:
                age = (now - self._universe_last_updated).total_seconds()
                if age < self._universe_cache_ttl:
                    return self._symbol_universe
        
        # Try to load from database first
        if self._symbols_collection is not None:
            cached = list(self._symbols_collection.find({}, {"_id": 0}))
            # Ensure no ObjectId fields remain (defensive)
            for doc in cached:
                if "_id" in doc:
                    del doc["_id"]
            if cached and len(cached) > 1000:
                cache_time = cached[0].get("cached_at") if cached else None
                if cache_time:
                    try:
                        cache_dt = datetime.fromisoformat(cache_time.replace("Z", "+00:00"))
                        if (now - cache_dt).total_seconds() < self._universe_cache_ttl:
                            self._symbol_universe = cached
                            self._universe_last_updated = cache_dt
                            logger.info(f"Loaded {len(cached)} symbols from database cache")
                            return self._symbol_universe
                    except Exception:
                        pass
        
        # Fetch fresh from Alpaca
        symbols = await self._fetch_symbol_universe()
        
        # Cache in database
        if symbols and self._symbols_collection is not None:
            try:
                # Clear old cache
                self._symbols_collection.delete_many({})
                
                # Add timestamp
                for s in symbols:
                    s["cached_at"] = now.isoformat()
                
                # Insert new
                self._symbols_collection.insert_many(symbols)
                logger.info(f"Cached {len(symbols)} symbols to database")
            except Exception as e:
                logger.error(f"Error caching symbols: {e}")
        
        self._symbol_universe = symbols
        self._universe_last_updated = now
        
        return symbols
    
    async def _fetch_symbol_universe(self) -> List[Dict]:
        """Fetch US stock universe from the IB historical data we already collect.

        Previously this called Alpaca's `get_all_assets`. Alpaca is fully
        removed from the live-data path — the universe now comes from the
        `ib_historical_data` collection (via IBDataProvider), which is the
        same source of truth used by training and the scanner.
        """
        try:
            from services.ib_data_provider import get_live_data_service
            live = get_live_data_service()
            symbol_strings = await live.get_all_assets()
            if not symbol_strings:
                logger.warning("IB universe empty, using default symbol list")
                return self._get_default_symbols()
            symbols = [
                {
                    "symbol": str(s),
                    "name": str(s),
                    "exchange": "IB",
                    "tradable": True,
                    "shortable": False,
                    "easy_to_borrow": False,
                }
                for s in symbol_strings
            ]
            logger.info(f"Fetched {len(symbols)} symbols from ib_historical_data")
            return symbols
        except Exception as e:
            logger.error(f"Error fetching symbol universe from IB: {e}")
            return self._get_default_symbols()
    
    def _get_default_symbols(self) -> List[Dict]:
        """Default symbol list (S&P 500 + popular stocks)"""
        # Core list of popular/liquid stocks
        default = [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "BRK.B", "UNH", "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA",
            "ABBV", "MRK", "LLY", "AVGO", "PEP", "KO", "COST", "TMO", "MCD",
            "WMT", "CSCO", "ACN", "ABT", "DHR", "NEE", "DIS", "VZ", "ADBE",
            "WFC", "PM", "TXN", "CRM", "NKE", "BMY", "RTX", "ORCL", "COP",
            "QCOM", "UPS", "HON", "T", "LOW", "MS", "INTC", "UNP", "CAT",
            "IBM", "BA", "INTU", "SPGI", "GS", "DE", "AMD", "BLK", "GILD",
            "AXP", "AMAT", "MDLZ", "CVS", "SBUX", "PLD", "ADI", "LMT", "ISRG",
            "MMC", "AMT", "SYK", "CI", "MO", "NOW", "ZTS", "CB", "TJX", "LRCX",
            "BKNG", "ADP", "SO", "REGN", "VRTX", "BSX", "PGR", "FISV", "CME",
            # Add more popular stocks
            "SPY", "QQQ", "IWM", "DIA", "ARKK", "XLF", "XLE", "XLK", "XLV",
            "COIN", "MARA", "RIOT", "SQ", "PYPL", "SHOP", "SNOW", "NET", "CRWD",
            "ZS", "DDOG", "MDB", "PLTR", "PATH", "U", "RBLX", "ABNB", "DASH"
        ]
        
        return [{"symbol": s, "name": s, "exchange": "NASDAQ/NYSE"} for s in default]
    
    async def start_market_scan(
        self,
        name: str = None,
        trade_style: TradeStyle = TradeStyle.ALL,
        strategies: List[str] = None,
        filters: ScanFilters = None,
        run_in_background: bool = True
    ) -> MarketScanResult:
        """
        Start a market-wide scan for strategy signals.
        
        Args:
            name: Name for this scan
            trade_style: Filter strategies by style (intraday/swing/investment/all)
            strategies: Specific strategy IDs to scan (None = all for style)
            filters: Pre-filters for symbols
            run_in_background: Run as background job
            
        Returns:
            MarketScanResult with job ID and initial status
        """
        scan_id = f"scan_{uuid.uuid4().hex[:12]}"
        
        if filters is None:
            filters = ScanFilters(trade_style=trade_style)
        
        if name is None:
            name = f"{trade_style.value.title()} Market Scan"
        
        # Get strategies for this style
        from data.strategies_data import TRADING_STRATEGIES_DATA
        
        available_strategies = []
        if trade_style == TradeStyle.ALL or trade_style == TradeStyle.INTRADAY:
            available_strategies.extend(TRADING_STRATEGIES_DATA.get("intraday", []))
        if trade_style == TradeStyle.ALL or trade_style == TradeStyle.SWING:
            available_strategies.extend(TRADING_STRATEGIES_DATA.get("swing", []))
        if trade_style == TradeStyle.ALL or trade_style == TradeStyle.INVESTMENT:
            available_strategies.extend(TRADING_STRATEGIES_DATA.get("investment", []))
        
        # Filter to specific strategies if provided
        if strategies:
            available_strategies = [s for s in available_strategies if s["id"] in strategies]
        
        strategy_ids = [s["id"] for s in available_strategies]
        
        result = MarketScanResult(
            id=scan_id,
            name=name,
            created_at=datetime.now(timezone.utc).isoformat(),
            trade_style=trade_style.value,
            strategies_scanned=strategy_ids,
            filters=filters.to_dict(),
            status=ScanStatus.PENDING
        )
        
        self._running_jobs[scan_id] = result
        
        if run_in_background:
            # Start background task
            task = asyncio.create_task(
                self._run_scan(scan_id, available_strategies, filters)
            )
            self._job_tasks[scan_id] = task
            
            return result
        else:
            # Run synchronously
            await self._run_scan(scan_id, available_strategies, filters)
            return self._running_jobs.get(scan_id, result)
    
    async def _run_scan(
        self,
        scan_id: str,
        strategies: List[Dict],
        filters: ScanFilters
    ):
        """Execute the market scan"""
        result = self._running_jobs.get(scan_id)
        if not result:
            return
        
        start_time = datetime.now(timezone.utc)
        result.status = ScanStatus.RUNNING
        
        try:
            # Get symbol universe
            all_symbols = await self.get_symbol_universe()
            result.total_symbols = len(all_symbols)
            
            # Apply pre-filters
            filtered_symbols = await self._apply_prefilters(all_symbols, filters)
            result.symbols_passed_filter = len(filtered_symbols)
            
            logger.info(f"Scan {scan_id}: {len(filtered_symbols)} symbols after pre-filter (from {len(all_symbols)})")
            
            all_signals: List[ScanSignal] = []
            
            # Process in batches
            for i in range(0, len(filtered_symbols), self.BATCH_SIZE):
                batch = filtered_symbols[i:i + self.BATCH_SIZE]
                
                # Check if cancelled
                if result.status == ScanStatus.CANCELLED:
                    break
                
                # Scan batch
                batch_signals = await self._scan_batch(batch, strategies, filters)
                all_signals.extend(batch_signals)
                
                # Update progress
                result.symbols_scanned = min(i + self.BATCH_SIZE, len(filtered_symbols))
                result.progress_pct = (result.symbols_scanned / len(filtered_symbols)) * 100
                
                # Small delay between batches
                await asyncio.sleep(self.BATCH_DELAY)
            
            # Process results
            result.signals = [s.to_dict() for s in all_signals]
            
            # Group by strategy
            for signal in all_signals:
                strategy_name = signal.strategy_name
                result.signals_by_strategy[strategy_name] = \
                    result.signals_by_strategy.get(strategy_name, 0) + 1
            
            # Group by sector
            for signal in all_signals:
                sector = signal.sector or "Unknown"
                result.signals_by_sector[sector] = \
                    result.signals_by_sector.get(sector, 0) + 1
            
            # Get top setups by expected R
            sorted_signals = sorted(all_signals, key=lambda x: x.expected_r, reverse=True)
            result.top_setups = [s.to_dict() for s in sorted_signals[:20]]
            
            result.status = ScanStatus.COMPLETED
            result.completed_at = datetime.now(timezone.utc).isoformat()
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            # Save to database
            if self._scans_collection is not None:
                self._scans_collection.insert_one(result.to_dict())
            
            if self._signals_collection is not None and all_signals:
                signal_docs = [{"scan_id": scan_id, **s.to_dict()} for s in all_signals]
                self._signals_collection.insert_many(signal_docs)
            
            logger.info(f"Scan {scan_id} completed: {len(all_signals)} signals found")
            
        except Exception as e:
            logger.error(f"Scan {scan_id} failed: {e}")
            result.status = ScanStatus.FAILED
            result.error_message = str(e)
    
    async def _apply_prefilters(
        self,
        symbols: List[Dict],
        filters: ScanFilters
    ) -> List[Dict]:
        """Apply pre-filters to symbol list"""
        filtered = []
        
        for sym_data in symbols:
            symbol = sym_data.get("symbol", "")
            
            # Skip OTC if configured
            if filters.exclude_otc:
                exchange = sym_data.get("exchange", "").upper()
                if "OTC" in exchange or "PINK" in exchange:
                    continue
            
            # Sector filter
            if filters.sectors:
                sector = sym_data.get("sector", "")
                if sector and sector not in filters.sectors:
                    continue
            
            filtered.append(sym_data)
        
        return filtered
    
    async def _scan_batch(
        self,
        symbols: List[Dict],
        strategies: List[Dict],
        filters: ScanFilters
    ) -> List[ScanSignal]:
        """Scan a batch of symbols for signals"""
        signals = []
        
        for sym_data in symbols:
            symbol = sym_data.get("symbol", "")
            
            try:
                # Fetch historical data
                if self._hybrid_data_service is None:
                    continue
                
                # Determine timeframe based on trade style
                if filters.trade_style == TradeStyle.INTRADAY:
                    timeframe = "5min"
                    days_back = 5
                elif filters.trade_style == TradeStyle.INVESTMENT:
                    timeframe = "1day"
                    days_back = 365
                else:  # swing or all
                    timeframe = "1day"
                    days_back = 60
                
                result = await self._hybrid_data_service.get_bars(
                    symbol=symbol,
                    timeframe=timeframe,
                    days_back=days_back
                )
                
                if not result.success or not result.bars:
                    continue
                
                bars = result.bars
                
                # Apply price filter
                last_price = bars[-1].get("close", 0)
                if last_price < filters.min_price or last_price > filters.max_price:
                    continue
                
                # Apply volume filter
                avg_volume = sum(b.get("volume", 0) for b in bars[-20:]) / min(20, len(bars))
                
                min_volume = filters.min_adv_swing
                if filters.trade_style == TradeStyle.INTRADAY:
                    min_volume = filters.min_adv_intraday
                elif filters.trade_style == TradeStyle.INVESTMENT:
                    min_volume = filters.min_adv_investment
                
                if avg_volume < min_volume:
                    continue
                
                # Check each strategy
                for strategy in strategies:
                    signal = await self._check_strategy_signal(
                        symbol, bars, strategy, sym_data, avg_volume
                    )
                    if signal:
                        signals.append(signal)
                
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
                continue
        
        return signals
    
    async def _check_strategy_signal(
        self,
        symbol: str,
        bars: List[Dict],
        strategy: Dict,
        sym_data: Dict,
        avg_volume: float
    ) -> Optional[ScanSignal]:
        """Check if a strategy signal is present"""
        if len(bars) < 5:
            return None
        
        strategy_id = strategy.get("id", "")
        strategy_name = strategy.get("name", "")
        category = strategy.get("category", "")
        
        # Get latest bar data
        current_bar = bars[-1]
        current_price = current_bar.get("close", 0)
        current_high = current_bar.get("high", current_price)
        current_low = current_bar.get("low", current_price)
        
        # Check strategy-specific conditions
        signal_detected = False
        criteria_met = []
        signal_strength = 0.0
        
        # Momentum strategies
        if "momentum" in strategy_name.lower() or category == "intraday":
            signal_detected, criteria_met, signal_strength = self._check_momentum_signal(bars)
        
        # Breakout strategies
        elif "breakout" in strategy_name.lower():
            signal_detected, criteria_met, signal_strength = self._check_breakout_signal(bars)
        
        # Mean reversion strategies
        elif "reversion" in strategy_name.lower() or "pullback" in strategy_name.lower():
            signal_detected, criteria_met, signal_strength = self._check_mean_reversion_signal(bars)
        
        # Swing strategies
        elif category == "swing":
            signal_detected, criteria_met, signal_strength = self._check_swing_signal(bars, strategy)
        
        # Investment strategies (check for value/growth criteria)
        elif category == "investment":
            signal_detected, criteria_met, signal_strength = self._check_investment_signal(bars, strategy)
        
        if not signal_detected:
            return None
        
        # Calculate entry/stop/target
        stop_pct = 0.02 if category == "intraday" else 0.05 if category == "swing" else 0.10
        target_pct = stop_pct * 2  # 2:1 R:R default
        
        stop_price = current_price * (1 - stop_pct)
        target_price = current_price * (1 + target_pct)
        
        # Calculate expected R
        risk = current_price - stop_price
        reward = target_price - current_price
        expected_r = (reward / risk) * (signal_strength / 100) if risk > 0 else 0
        
        return ScanSignal(
            symbol=symbol,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            category=category,
            signal_date=current_bar.get("timestamp", "")[:10],
            signal_time=current_bar.get("timestamp", "")[11:19] if len(current_bar.get("timestamp", "")) > 10 else "",
            entry_price=current_price,
            stop_price=stop_price,
            target_price=target_price,
            expected_r=expected_r,
            signal_strength=signal_strength,
            sector=sym_data.get("sector", ""),
            market_cap=sym_data.get("market_cap", 0),
            avg_volume=int(avg_volume),
            rvol=1.0,  # Would need real-time data for accurate RVOL
            pattern_description=f"{strategy_name} signal detected",
            criteria_met=criteria_met
        )
    
    def _check_momentum_signal(self, bars: List[Dict]) -> tuple:
        """Check for momentum signal"""
        if len(bars) < 5:
            return False, [], 0.0
        
        closes = [b.get("close", 0) for b in bars[-5:]]
        if closes[0] == 0:
            return False, [], 0.0
        
        # 4-bar momentum
        momentum = (closes[-1] - closes[0]) / closes[0] * 100
        
        criteria_met = []
        strength = 0.0
        
        if momentum >= 3.0:
            criteria_met.append(f"Strong momentum: {momentum:.1f}%")
            strength = min(100, momentum * 15)
        elif momentum >= 2.0:
            criteria_met.append(f"Moderate momentum: {momentum:.1f}%")
            strength = min(80, momentum * 12)
        else:
            return False, [], 0.0
        
        # Check for higher highs
        highs = [b.get("high", 0) for b in bars[-4:]]
        if all(highs[i] <= highs[i+1] for i in range(len(highs)-1)):
            criteria_met.append("Higher highs pattern")
            strength += 10
        
        return True, criteria_met, min(100, strength)
    
    def _check_breakout_signal(self, bars: List[Dict]) -> tuple:
        """Check for breakout signal"""
        if len(bars) < 20:
            return False, [], 0.0
        
        current_high = bars[-1].get("high", 0)
        recent_high = max(b.get("high", 0) for b in bars[-20:-1])
        
        criteria_met = []
        strength = 0.0
        
        if current_high > recent_high:
            breakout_pct = (current_high - recent_high) / recent_high * 100
            criteria_met.append(f"20-bar high breakout: {breakout_pct:.2f}%")
            strength = min(100, 50 + breakout_pct * 10)
            
            # Check volume confirmation
            current_vol = bars[-1].get("volume", 0)
            avg_vol = sum(b.get("volume", 0) for b in bars[-20:-1]) / 19
            if avg_vol > 0 and current_vol > avg_vol * 1.5:
                criteria_met.append("Volume confirmation")
                strength += 20
            
            return True, criteria_met, min(100, strength)
        
        return False, [], 0.0
    
    def _check_mean_reversion_signal(self, bars: List[Dict]) -> tuple:
        """Check for mean reversion signal"""
        if len(bars) < 20:
            return False, [], 0.0
        
        closes = [b.get("close", 0) for b in bars[-20:]]
        sma20 = sum(closes) / 20
        current = closes[-1]
        
        criteria_met = []
        strength = 0.0
        
        # Check for oversold bounce
        deviation = (current - sma20) / sma20 * 100
        
        if deviation < -3.0:  # 3% below SMA20
            criteria_met.append(f"Oversold: {deviation:.1f}% below 20-SMA")
            
            # Check for reversal candle
            if bars[-1].get("close", 0) > bars[-1].get("open", 0):
                criteria_met.append("Bullish reversal candle")
                strength = min(100, abs(deviation) * 10 + 30)
                return True, criteria_met, strength
        
        return False, [], 0.0
    
    def _check_swing_signal(self, bars: List[Dict], strategy: Dict) -> tuple:
        """Check for swing trading signal"""
        if len(bars) < 50:
            return False, [], 0.0
        
        closes = [b.get("close", 0) for b in bars]
        sma50 = sum(closes[-50:]) / 50
        sma20 = sum(closes[-20:]) / 20
        current = closes[-1]
        
        criteria_met = []
        strength = 0.0
        
        # Trend following: price above moving averages
        if current > sma20 > sma50:
            criteria_met.append("Uptrend: Price > 20-SMA > 50-SMA")
            
            # Check for pullback to 20-SMA
            recent_low = min(b.get("low", 0) for b in bars[-5:])
            if abs(recent_low - sma20) / sma20 < 0.02:  # Within 2% of 20-SMA
                criteria_met.append("Pullback to 20-SMA support")
                strength = 70
                
                # Volume confirmation
                if bars[-1].get("volume", 0) > bars[-2].get("volume", 0):
                    criteria_met.append("Volume increasing")
                    strength += 15
                
                return True, criteria_met, min(100, strength)
        
        return False, [], 0.0
    
    def _check_investment_signal(self, bars: List[Dict], strategy: Dict) -> tuple:
        """Check for investment signal (simplified technical check)"""
        if len(bars) < 200:
            return False, [], 0.0
        
        closes = [b.get("close", 0) for b in bars]
        sma200 = sum(closes[-200:]) / 200
        sma50 = sum(closes[-50:]) / 50
        current = closes[-1]
        
        criteria_met = []
        strength = 0.0
        
        # Long-term uptrend
        if current > sma50 > sma200:
            criteria_met.append("Long-term uptrend intact")
            
            # Check for reasonable entry (not overextended)
            extension = (current - sma50) / sma50 * 100
            if extension < 10:  # Less than 10% above 50-SMA
                criteria_met.append(f"Not overextended: {extension:.1f}% above 50-SMA")
                strength = 60
                
                # Golden cross check
                sma50_prev = sum(closes[-51:-1]) / 50
                sma200_prev = sum(closes[-201:-1]) / 200
                if sma50_prev <= sma200_prev and sma50 > sma200:
                    criteria_met.append("Recent golden cross")
                    strength += 25
                
                return True, criteria_met, min(100, strength)
        
        return False, [], 0.0
    
    async def get_scan_status(self, scan_id: str) -> Optional[Dict]:
        """Get status of a running or completed scan"""
        # Check running jobs first
        if scan_id in self._running_jobs:
            return self._running_jobs[scan_id].to_dict()
        
        # Check database
        if self._scans_collection is not None:
            result = self._scans_collection.find_one({"id": scan_id}, {"_id": 0})
            if result:
                return result
        
        return None
    
    async def get_scan_signals(
        self,
        scan_id: str,
        strategy_id: str = None,
        sector: str = None,
        min_expected_r: float = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get signals from a completed scan with optional filters"""
        if self._signals_collection is None:
            return []
        
        query = {"scan_id": scan_id}
        
        if strategy_id:
            query["strategy_id"] = strategy_id
        if sector:
            query["sector"] = sector
        if min_expected_r:
            query["expected_r"] = {"$gte": min_expected_r}
        
        signals = list(
            self._signals_collection.find(query, {"_id": 0})
            .sort("expected_r", -1)
            .limit(limit)
        )
        
        return signals
    
    async def list_scans(
        self,
        status: ScanStatus = None,
        trade_style: str = None,
        limit: int = 20
    ) -> List[Dict]:
        """List recent market scans"""
        if self._scans_collection is None:
            return []
        
        query = {}
        if status:
            query["status"] = status.value
        if trade_style:
            query["trade_style"] = trade_style
        
        scans = list(
            self._scans_collection.find(query, {"_id": 0, "signals": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        
        return scans
    
    async def cancel_scan(self, scan_id: str) -> bool:
        """Cancel a running scan"""
        if scan_id in self._running_jobs:
            self._running_jobs[scan_id].status = ScanStatus.CANCELLED
            
            if scan_id in self._job_tasks:
                self._job_tasks[scan_id].cancel()
                del self._job_tasks[scan_id]
            
            return True
        return False
    
    def get_service_status(self) -> Dict:
        """Get service status"""
        return {
            "db_connected": self._db is not None,
            "hybrid_data_connected": self._hybrid_data_service is not None,
            "symbol_universe_size": len(self._symbol_universe),
            "universe_last_updated": self._universe_last_updated.isoformat() if self._universe_last_updated else None,
            "running_scans": len(self._running_jobs),
            "nightly_scan_enabled": self._nightly_scan_enabled
        }


# Singleton instance
_market_scanner_service: Optional[MarketScannerService] = None


def get_market_scanner_service() -> MarketScannerService:
    """Get singleton instance"""
    global _market_scanner_service
    if _market_scanner_service is None:
        _market_scanner_service = MarketScannerService()
    return _market_scanner_service


def init_market_scanner_service(
    db=None,
    hybrid_data_service=None,
    alpaca_service=None
) -> MarketScannerService:
    """Initialize the market scanner service"""
    service = get_market_scanner_service()
    if db is not None:
        service.set_db(db)
    if hybrid_data_service is not None:
        service.set_hybrid_data_service(hybrid_data_service)
    if alpaca_service is not None:
        service.set_alpaca_service(alpaca_service)
    return service
