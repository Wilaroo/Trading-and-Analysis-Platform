"""
IB Historical Data Collector Service
=====================================

Systematically collects historical data from IB Gateway to build a comprehensive
learning database for SentCom's AI systems.

Key Features:
1. Batch collection of historical OHLCV data for multiple symbols
2. Respects IB rate limits (1 request at a time, pacing)
3. Stores data in MongoDB for model training
4. Supports multiple bar sizes (1min, 5min, 15min, 1hour, 1day)
5. Background collection that can run overnight
6. Progress tracking and resume capability

IB Historical Data Limitations:
- 30 seconds or smaller bars: ~6 months history
- 1 minute bars: ~1 year history
- 5 minute bars: ~2 years history
- 1 day bars: ~20 years history
- Rate limit: ~10 requests per second (we use 1 per 2 seconds to be safe)
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


class CollectionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CollectionJob:
    """Represents a historical data collection job"""
    id: str
    symbols: List[str]
    bar_size: str
    duration: str
    start_time: str
    status: CollectionStatus = CollectionStatus.PENDING
    end_time: Optional[str] = None
    symbols_completed: int = 0
    symbols_failed: int = 0
    total_bars_collected: int = 0
    current_symbol: str = ""
    errors: List[str] = field(default_factory=list)
    progress_pct: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "status": self.status.value
        }


class IBHistoricalCollector:
    """
    Collects historical data from IB Gateway and stores in MongoDB.
    
    This service is designed to run in the background, collecting data
    overnight or during low-activity periods to build a comprehensive
    learning database.
    """
    
    COLLECTION_NAME = "ib_historical_data"
    JOBS_COLLECTION = "ib_collection_jobs"
    
    # IB rate limiting - be conservative to avoid disconnects
    REQUEST_DELAY_SECONDS = 2.0  # Wait between requests
    MAX_RETRIES = 3
    
    # Bar size configurations
    BAR_CONFIGS = {
        "1 min": {"max_duration": "1 D", "max_history_days": 365},
        "5 mins": {"max_duration": "2 D", "max_history_days": 730},
        "15 mins": {"max_duration": "1 W", "max_history_days": 730},
        "1 hour": {"max_duration": "1 M", "max_history_days": 1825},
        "1 day": {"max_duration": "1 Y", "max_history_days": 7300},
    }
    
    def __init__(self):
        self._db = None
        self._data_col = None
        self._jobs_col = None
        self._ib_service = None
        self._alpaca_service = None
        self._market_scanner = None  # Use existing market scanner for symbol universe
        self._running_job: Optional[CollectionJob] = None
        self._cancel_requested = False
        self._all_us_symbols: List[str] = []
        
        # Batch processing config
        self.BATCH_SIZE = 100  # Symbols per batch checkpoint
        self.BATCH_DELAY = 0.5  # Seconds between batch saves
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._data_col = db[self.COLLECTION_NAME]
            self._jobs_col = db[self.JOBS_COLLECTION]
            
            # Create indexes
            self._data_col.create_index([("symbol", 1), ("bar_size", 1), ("date", 1)], unique=True)
            self._data_col.create_index([("symbol", 1), ("bar_size", 1)])
            self._data_col.create_index([("collected_at", DESCENDING)])
            self._jobs_col.create_index([("start_time", DESCENDING)])
            self._jobs_col.create_index([("id", 1)], unique=True)
            
    def set_ib_service(self, ib_service):
        """Set IB service for data collection"""
        self._ib_service = ib_service
        
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for fetching US stock universe"""
        self._alpaca_service = alpaca_service
        
    def set_market_scanner(self, market_scanner):
        """Set market scanner service for symbol universe (preferred)"""
        self._market_scanner = market_scanner
        logger.info("IB Collector: Using market scanner for symbol universe")
        
    async def get_all_us_symbols(self, min_price: float = 1.0, max_price: float = 1000.0) -> List[str]:
        """
        Fetch all tradeable US stocks using the market scanner service.
        
        Priority:
        1. Market Scanner (already has caching and Alpaca integration)
        2. Direct Alpaca API
        3. Fallback to default symbols
        
        Args:
            min_price: Minimum stock price filter
            max_price: Maximum stock price filter
            
        Returns:
            List of symbols meeting criteria
        """
        # Check cache first
        if self._all_us_symbols and len(self._all_us_symbols) > 100:
            return self._all_us_symbols
        
        symbols = []
        
        # Method 1: Use Market Scanner (preferred - already has caching)
        if self._market_scanner:
            try:
                universe = await self._market_scanner.get_symbol_universe()
                if universe and len(universe) > 100:
                    symbols = [s.get("symbol") for s in universe if s.get("symbol")]
                    logger.info(f"Got {len(symbols)} symbols from market scanner")
            except Exception as e:
                logger.warning(f"Market scanner failed: {e}")
        
        # Method 2: Try direct Alpaca
        if not symbols and self._alpaca_service:
            try:
                assets = await self._alpaca_service.get_all_assets()
                if assets:
                    for asset in assets:
                        if (asset.get("tradable") and 
                            asset.get("status") == "active" and
                            asset.get("exchange") in ["NYSE", "NASDAQ", "ARCA", "AMEX"]):
                            symbols.append(asset.get("symbol"))
                    logger.info(f"Got {len(symbols)} symbols from Alpaca")
            except Exception as e:
                logger.warning(f"Alpaca service failed: {e}")
        
        # Method 3: Try to load from database cache
        if not symbols and self._db is not None:
            try:
                cache = self._db["us_symbols"].find({}, {"symbol": 1, "_id": 0})
                cached_symbols = [doc.get("symbol") for doc in cache if doc.get("symbol")]
                if len(cached_symbols) > 100:
                    symbols = cached_symbols
                    logger.info(f"Got {len(symbols)} symbols from database cache")
            except Exception as e:
                logger.warning(f"Database cache failed: {e}")
        
        # Method 4: Fallback to default
        if not symbols:
            symbols = self.get_default_symbols()
            logger.info(f"Using {len(symbols)} default symbols")
        
        self._all_us_symbols = symbols
        return symbols
        
    def get_default_symbols(self) -> List[str]:
        """Get default symbols for data collection"""
        return [
            # Major indices ETFs
            "SPY", "QQQ", "IWM", "DIA",
            # Tech mega caps
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            # Financials
            "JPM", "BAC", "GS", "MS", "WFC", "C",
            # Healthcare
            "JNJ", "UNH", "PFE", "ABBV", "MRK",
            # Consumer
            "WMT", "COST", "HD", "MCD", "NKE", "SBUX",
            # Energy
            "XOM", "CVX", "COP", "SLB",
            # Industrial
            "CAT", "BA", "GE", "HON", "UPS",
            # Semiconductors
            "AVGO", "QCOM", "INTC", "MU", "AMAT",
            # Other high-volume
            "COIN", "PLTR", "SOFI", "RIVN", "LCID", "NIO",
            # VIX products
            "VXX", "UVXY"
        ]
    
    async def build_adv_cache(self, batch_size: int = 100) -> Dict[str, Any]:
        """
        Build/refresh the ADV (Average Daily Volume) cache for all symbols.
        This enables accurate filtering by liquidity.
        
        Fetches 20-day volume data from Alpaca for all symbols in the universe.
        
        Args:
            batch_size: Number of symbols to process per batch
            
        Returns:
            Summary of cache build operation
        """
        if self._alpaca_service is None:
            return {"success": False, "error": "Alpaca service not available"}
            
        if self._db is None:
            return {"success": False, "error": "Database not available"}
        
        # Get all symbols from market scanner
        all_symbols = []
        if self._market_scanner:
            try:
                universe = await self._market_scanner.get_symbol_universe()
                all_symbols = [s.get("symbol") for s in universe if s.get("symbol")]
            except Exception as e:
                logger.warning(f"Could not get universe from scanner: {e}")
        
        if not all_symbols:
            # Fall back to direct Alpaca fetch
            all_symbols = await self.get_all_us_symbols()
        
        if not all_symbols:
            return {"success": False, "error": "Could not fetch symbol list"}
        
        logger.info(f"Building ADV cache for {len(all_symbols)} symbols...")
        
        # Process in batches
        adv_cache_col = self._db["symbol_adv_cache"]
        processed = 0
        cached = 0
        errors = 0
        
        for i in range(0, len(all_symbols), batch_size):
            batch = all_symbols[i:i + batch_size]
            
            try:
                # Fetch bars for batch
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                import os
                
                api_key = os.environ.get("ALPACA_API_KEY", "")
                secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
                
                if not api_key or not secret_key:
                    return {"success": False, "error": "Alpaca keys not configured"}
                
                client = StockHistoricalDataClient(api_key, secret_key)
                
                from datetime import datetime, timedelta, timezone
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=30)  # 30 days for 20 trading days
                
                request = StockBarsRequest(
                    symbol_or_symbols=batch,
                    timeframe=TimeFrame.Day,
                    start=start,
                    end=end
                )
                
                bars = client.get_stock_bars(request)
                
                # Calculate ADV for each symbol
                for symbol in batch:
                    try:
                        symbol_bars = bars.get(symbol, [])
                        if symbol_bars and len(symbol_bars) > 0:
                            volumes = [b.volume for b in symbol_bars[-20:]]
                            avg_volume = sum(volumes) / len(volumes) if volumes else 0
                            
                            # Upsert to cache
                            adv_cache_col.update_one(
                                {"symbol": symbol},
                                {"$set": {
                                    "symbol": symbol,
                                    "avg_volume": avg_volume,
                                    "sample_days": len(volumes),
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }},
                                upsert=True
                            )
                            cached += 1
                    except Exception as e:
                        logger.debug(f"Error processing {symbol}: {e}")
                        errors += 1
                
                processed += len(batch)
                logger.info(f"ADV cache progress: {processed}/{len(all_symbols)} ({cached} cached)")
                
                # Rate limit
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error processing batch: {e}")
                errors += len(batch)
                processed += len(batch)
        
        # Create index
        try:
            adv_cache_col.create_index("avg_volume")
            adv_cache_col.create_index("symbol", unique=True)
        except:
            pass
        
        return {
            "success": True,
            "total_symbols": len(all_symbols),
            "cached": cached,
            "errors": errors,
            "message": f"ADV cache built for {cached} symbols"
        }
    
    async def get_adv_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the ADV cache"""
        if self._db is None:
            return {"cached": False, "count": 0}
            
        try:
            adv_col = self._db["symbol_adv_cache"]
            total = adv_col.count_documents({})
            
            # Count by ADV threshold
            adv_100k = adv_col.count_documents({"avg_volume": {"$gte": 100_000}})
            adv_500k = adv_col.count_documents({"avg_volume": {"$gte": 500_000}})
            adv_1m = adv_col.count_documents({"avg_volume": {"$gte": 1_000_000}})
            
            return {
                "cached": total > 0,
                "total_symbols": total,
                "adv_100k_plus": adv_100k,
                "adv_500k_plus": adv_500k,
                "adv_1m_plus": adv_1m
            }
        except Exception as e:
            return {"cached": False, "error": str(e)}
    
    async def get_liquid_symbols(self, min_adv: int = 100_000) -> List[str]:
        """
        Get liquid US stocks filtered by Average Daily Volume (ADV).
        
        Uses market scanner to dynamically fetch and filter the full universe.
        
        Args:
            min_adv: Minimum average daily volume (default 100K for broad coverage)
            
        Returns:
            List of liquid symbols meeting ADV criteria
        """
        liquid_symbols = []
        
        # Method 1: Use market scanner to get filtered universe (PREFERRED)
        if self._market_scanner is not None:
            try:
                # Get the full symbol universe from market scanner
                universe = await self._market_scanner.get_symbol_universe()
                
                if universe:
                    # Filter by ADV if volume data is available
                    for sym_data in universe:
                        symbol = sym_data.get("symbol")
                        # Check if we have volume data
                        avg_volume = sym_data.get("avg_volume", 0) or sym_data.get("adv", 0)
                        
                        if avg_volume >= min_adv:
                            liquid_symbols.append(symbol)
                        elif avg_volume == 0:
                            # No volume data - include based on exchange (major exchanges are liquid)
                            exchange = sym_data.get("exchange", "")
                            if exchange in ["NASDAQ", "NYSE", "ARCA", "BATS"]:
                                liquid_symbols.append(symbol)
                    
                    if liquid_symbols:
                        logger.info(f"Got {len(liquid_symbols)} symbols from market scanner (ADV >= {min_adv:,})")
                        return liquid_symbols
                        
            except Exception as e:
                logger.warning(f"Market scanner fetch failed: {e}")
        
        # Method 2: Check database for pre-computed ADV data
        if self._db is not None:
            try:
                # Look for symbols with ADV data
                cursor = self._db["symbol_adv_cache"].find(
                    {"avg_volume": {"$gte": min_adv}},
                    {"symbol": 1, "_id": 0}
                ).limit(10000)
                liquid_symbols = [doc["symbol"] for doc in cursor if doc.get("symbol")]
                
                if liquid_symbols:
                    logger.info(f"Got {len(liquid_symbols)} liquid symbols from ADV cache (min_adv={min_adv:,})")
                    return liquid_symbols
            except Exception as e:
                logger.debug(f"ADV cache not available: {e}")
        
        # Method 3: Fall back to curated list (known liquid stocks)
        liquid_symbols = self._get_known_liquid_symbols()
        logger.info(f"Using {len(liquid_symbols)} known liquid symbols as fallback")
        
        return liquid_symbols
    
    def _get_known_liquid_symbols(self) -> List[str]:
        """
        Curated list of ~1,500+ known liquid US stocks.
        These stocks typically have ADV > 500,000 and are suitable for active trading.
        """
        # Major ETFs (50)
        etfs = [
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "VEA", "VWO", "EFA",
            "IEMG", "VNQ", "BND", "AGG", "LQD", "TLT", "GLD", "SLV", "USO", "UNG",
            "XLF", "XLE", "XLK", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB",
            "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ", "SOXL", "SOXS", "TQQQ", "SQQQ",
            "UVXY", "VXX", "SVXY", "SPXU", "SPXS", "TNA", "TZA", "FAS", "FAZ",
            "HYG", "JNK", "EMB", "VIG", "SCHD", "VYM", "DVY", "JEPI", "JEPQ",
            "XBI", "IBB", "XOP", "OIH", "KRE", "XHB", "ITB", "KWEB", "FXI", "EWZ"
        ]
        
        # Full S&P 500 components (500)
        sp500 = [
            # Top 100 by market cap
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH",
            "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA", "ABBV", "MRK",
            "LLY", "AVGO", "PEP", "KO", "COST", "TMO", "MCD", "WMT", "CSCO", "ACN",
            "ABT", "DHR", "NEE", "DIS", "VZ", "ADBE", "WFC", "PM", "TXN", "CRM",
            "NKE", "BMY", "RTX", "ORCL", "COP", "QCOM", "UPS", "HON", "T", "LOW",
            "MS", "INTC", "UNP", "CAT", "IBM", "BA", "INTU", "SPGI", "GS", "DE",
            "AMD", "BLK", "GILD", "AXP", "AMAT", "MDLZ", "CVS", "SBUX", "PLD", "ADI",
            "LMT", "ISRG", "MMC", "AMT", "SYK", "CI", "MO", "NOW", "ZTS", "CB",
            "TJX", "LRCX", "BKNG", "ADP", "SO", "REGN", "VRTX", "BSX", "PGR", "FISV",
            "CME", "SCHW", "BDX", "CL", "EOG", "MU", "ITW", "SNPS", "CDNS", "NOC",
            # 101-200
            "DUK", "SHW", "ICE", "CSX", "PNC", "ETN", "MCK", "FDX", "AON", "KLAC",
            "EQIX", "APD", "EMR", "TGT", "NSC", "AZO", "ORLY", "FCX", "PSA", "AEP",
            "PXD", "HUM", "MCHP", "GD", "ADSK", "MPC", "MSI", "WM", "TRV", "EW",
            "JCI", "SLB", "F", "GM", "OXY", "KMB", "MNST", "D", "HLT", "ROP",
            "CMG", "NXPI", "MAR", "AIG", "STZ", "FTNT", "IQV", "PAYX", "TEL", "A",
            "GIS", "EXC", "BIIB", "HES", "KHC", "YUM", "PCAR", "SYY", "CTSH", "AFL",
            "DOW", "VLO", "ROST", "PSX", "HAL", "WELL", "KMI", "ON", "IDXX", "MSCI",
            "WMB", "DVN", "EL", "CTAS", "CARR", "DXCM", "DD", "ODFL", "DHI", "GWW",
            "HSY", "WBD", "FAST", "EXR", "KEYS", "CPRT", "VRSK", "VMC", "ANSS", "CSGP",
            "IT", "CDW", "FANG", "AME", "MTD", "XYL", "TSCO", "BRO", "DOV", "HPQ",
            # 201-300
            "RMD", "WAT", "GPN", "LH", "FTV", "CHD", "BR", "IRM", "STE", "PTC",
            "HOLX", "TRGP", "WAB", "PKI", "ALGN", "MOH", "WST", "CINF", "MKC", "AVB",
            "NTRS", "MTB", "HBAN", "RF", "FE", "DTE", "VTR", "ARE", "LDOS", "CFG",
            "DGX", "TDY", "BIO", "NDAQ", "TER", "LKQ", "EXPD", "COO", "ATO", "FMC",
            "NI", "KEY", "JBHT", "POOL", "DPZ", "ETSY", "FICO", "SBNY", "URI", "TECH",
            "PKG", "AES", "J", "IP", "CCL", "BBY", "CPB", "AKAM", "TYL", "GL",
            "AAL", "UAL", "DAL", "LUV", "ALK", "JBLU", "SAVE", "HA", "SKYW",
            "K", "SJM", "HRL", "CAG", "LW", "BG", "ADM", "TSN", "HRL", "PPC",
            "CLX", "CL", "CHD", "SPB", "EL", "COTY", "TPR", "CPRI", "PVH", "RL",
            "NVR", "LEN", "DHI", "PHM", "TOL", "MTH", "MDC", "KBH", "TMHC", "MHO",
            # 301-400
            "HPE", "NTAP", "WDC", "STX", "PSTG", "DELL", "NCR", "ZBRA", "JNPR", "ANET",
            "FFIV", "SWKS", "MRVL", "WOLF", "CRUS", "SLAB", "LSCC", "RMBS", "MPWR",
            "LNT", "EVRG", "CMS", "WEC", "ES", "AEE", "CNP", "PNW", "OGE", "NRG",
            "HWM", "TXT", "GE", "LHX", "HII", "LDOS", "SAIC", "BWA", "LEA", "ALV",
            "BEN", "TROW", "IVZ", "JHG", "SEIC", "FHI", "EV", "AMG", "APAM", "CG",
            "TFC", "ZION", "SIVB", "SBNY", "CMA", "FCNCA", "FRC", "PACW", "WAL", "EWBC",
            "MLM", "VMC", "MAS", "FND", "BLDR", "OC", "EXP", "USG", "GMS", "TREX",
            "EMN", "CE", "ALB", "FMC", "IFF", "PPG", "RPM", "SHW", "AXTA", "CABOT",
            "SEE", "IP", "PKG", "GPK", "SLGN", "BLL", "CCK", "ATR", "SON", "WRK",
            "FLEX", "JBL", "SANM", "PLXS", "TTMI", "BDC", "APH", "TEL", "GRMN"
        ]
        
        # NASDAQ 100 + high-growth tech (100)
        nasdaq_growth = [
            "NFLX", "PYPL", "CMCSA", "PDD", "ABNB", "MELI", "WDAY", "TEAM", "ZS", "DDOG",
            "MDB", "NET", "CRWD", "PANW", "OKTA", "ZM", "DOCU", "SPLK", "SNOW", "PLTR",
            "U", "RBLX", "COIN", "HOOD", "SOFI", "UPST", "AFRM", "BILL", "HUBS", "TWLO",
            "RIVN", "LCID", "NIO", "XPEV", "LI", "GRAB", "SE", "SHOP", "SQ", "LSPD",
            "MARA", "RIOT", "BITF", "HUT", "CLSK", "CIFR", "IREN", "BTBT", "GREE", "CAN",
            "ROKU", "TTD", "MGNI", "APPS", "PUBM", "DV", "IAS", "ZETA", "BRZE", "SEMR",
            "CFLT", "MNDY", "PATH", "AI", "GTLB", "ESTC", "NEWR", "SUMO", "FROG", "PD",
            "APP", "BMBL", "MTCH", "PINS", "SNAP", "TWTR", "RDDT", "HOOD", "CPNG", "DUOL",
            "DOCN", "LIDR", "IONQ", "RGTI", "QBTS", "QUBT", "ARQQ", "FORM", "LASR",
            "LAZR", "VLDR", "INVZ", "AEYE", "OUST", "MVIS", "CINT"
        ]
        
        # High-volume speculative/meme stocks (80)
        high_volume = [
            "AMC", "GME", "BBBY", "SNDL", "TLRY", "CGC", "ACB", "CRON", "OGI", "HEXO",
            "SPCE", "PLUG", "FCEL", "BLDP", "BE", "CHPT", "QS", "GOEV", "FSR", "WKHS",
            "RIDE", "NKLA", "HYLN", "ARVL", "REE", "FFIE", "MULN", "PTRA", "LEV", "EVGO",
            "ATER", "BBIG", "PROG", "CLOV", "WISH", "SKLZ", "SDC", "ROOT", "LMND", "OPEN",
            "RDFN", "CVNA", "CARG", "VRM", "STNE", "PAGS", "NU", "PSFE", "AFRM", "UPST",
            "SOFI", "LC", "UWMC", "RKT", "GHLD", "TREE", "LDI", "COOP", "ESSC", "TMTG",
            "DWAC", "CFVI", "NKLA", "GOEV", "REE", "VLDR", "LAZR", "OUST", "INVZ", "AEYE",
            "BB", "NOK", "EXPR", "KOSS", "NAKD", "CENN", "PRTY", "BGFV", "DKNG", "PENN"
        ]
        
        # Biotech & Healthcare (80)
        biotech = [
            "MRNA", "BNTX", "NVAX", "SGEN", "ALNY", "INCY", "BMRN", "EXEL", "SRPT", "RARE",
            "IONS", "UTHR", "NBIX", "SGEN", "FOLD", "HALO", "ARWR", "PTCT", "XLRN", "BLUE",
            "EDIT", "CRSP", "NTLA", "BEAM", "VERV", "PRME", "RXRX", "DNA", "DNAY", "TWST",
            "CERS", "IOVA", "AGEN", "FATE", "KITE", "JUNO", "CELG", "GILD", "AMGN", "BIIB",
            "ILMN", "EXAS", "GH", "NVTA", "PACB", "BNGO", "TWST", "CDNA", "MYGN", "NEO",
            "HZNP", "JAZZ", "LGND", "SUPN", "PRGO", "PAHC", "CTLT", "WST", "TFX", "HOLX",
            "DXCM", "PODD", "TNDM", "IRTC", "OFIX", "NUVA", "GMED", "LIVN", "PEN", "INSP",
            "VEEV", "CNC", "MOH", "HUM", "UNH", "ANTM", "CI", "CVS", "WBA", "RAD"
        ]
        
        # Financials & REITs (80)
        financials = [
            "C", "BAC", "WFC", "USB", "PNC", "TFC", "CFG", "KEY", "RF", "FITB",
            "ZION", "CMA", "HBAN", "MTB", "NTRS", "STT", "BK", "ALLY", "COF", "DFS",
            "AXP", "SYF", "PYPL", "V", "MA", "GPN", "FIS", "FISV", "FLT", "WU",
            "MET", "PRU", "ALL", "HIG", "LNC", "CINF", "GL", "AIZ", "KMPR", "PFG",
            "O", "VICI", "DLR", "CCI", "SBAC", "SPG", "AVB", "EQR", "MAA", "UDR",
            "PSA", "EXR", "CUBE", "LSI", "COLD", "REXR", "PLD", "DRE", "FR", "STAG",
            "WPC", "ADC", "NNN", "STOR", "EPRT", "SRC", "FCPT", "GTY", "PINE", "GOOD",
            "AMH", "INVH", "RDFN", "Z", "ZG", "RDFN", "OPEN", "OPAD", "COMP", "RMAX"
        ]
        
        # Energy & Materials (60)
        energy_materials = [
            "XOM", "CVX", "COP", "EOG", "PXD", "DVN", "FANG", "OXY", "HES", "MRO",
            "APA", "MTDR", "PR", "CTRA", "OVV", "SM", "RRC", "AR", "SWN", "EQT",
            "SLB", "HAL", "BKR", "NOV", "FTI", "HP", "OII", "RIG", "DO", "VAL",
            "VLO", "MPC", "PSX", "DINO", "PBF", "HFC", "DK", "CVI", "PAR", "PARR",
            "LIN", "APD", "ECL", "SHW", "PPG", "NEM", "FCX", "NUE", "STLD", "CLF",
            "AA", "ATI", "CMC", "RS", "SCHN", "ZEUS", "X", "ARNC", "CENX", "KALU"
        ]
        
        # Industrials & Defense (60)
        industrials = [
            "GE", "HON", "MMM", "CAT", "DE", "EMR", "ETN", "ROK", "AME", "ROP",
            "IR", "PH", "ITW", "DOV", "GNRC", "CMI", "PCAR", "AGCO", "OSK", "TEX",
            "BA", "LMT", "RTX", "NOC", "GD", "LHX", "HII", "TDG", "TXT", "HWM",
            "UPS", "FDX", "XPO", "JBHT", "KNX", "WERN", "LSTR", "ODFL", "SAIA", "OLD",
            "CSX", "UNP", "NSC", "KSU", "CP", "CNI", "WAB", "TRN", "GBX", "RAIL",
            "AAL", "UAL", "DAL", "LUV", "ALK", "JBLU", "SAVE", "HA", "SKYW", "MESA"
        ]
        
        # Combine all lists and remove duplicates
        all_symbols = (etfs + sp500 + nasdaq_growth + high_volume + 
                       biotech + financials + energy_materials + industrials)
        unique_symbols = list(dict.fromkeys(all_symbols))  # Preserve order, remove dupes
        
        return unique_symbols
    
    async def start_full_market_collection(
        self,
        bar_size: str = "1 day",
        duration: str = "1 M",
        min_price: float = 1.0,
        max_price: float = 1000.0,
        batch_size: int = 500
    ) -> Dict[str, Any]:
        """
        Start collection for ALL tradeable US stocks.
        
        This is a long-running job that can take hours. It will:
        1. Fetch all US stock symbols from Alpaca
        2. Filter by price range
        3. Collect historical data in batches
        4. Can be paused/resumed
        
        Args:
            bar_size: Bar size (recommend "1 day" for full market)
            duration: Duration per request
            min_price: Minimum stock price filter
            max_price: Maximum stock price filter
            batch_size: How many symbols to process before saving checkpoint
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        # Get all US symbols
        logger.info("Fetching all US stock symbols...")
        symbols = await self.get_all_us_symbols(min_price, max_price)
        
        if not symbols:
            return {
                "success": False,
                "error": "Could not fetch US stock list. Check Alpaca connection."
            }
            
        logger.info(f"Starting full market collection for {len(symbols)} symbols")
        
        # Start collection with all symbols
        return await self.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False
        )
    
    async def start_liquid_collection(
        self,
        bar_size: str = "1 day",
        duration: str = "1 M",
        min_adv: int = 100_000
    ) -> Dict[str, Any]:
        """
        Start collection for LIQUID US stocks only (filtered by ADV).
        
        This is faster than full market (~2-3 hours vs 10+ hours) and focuses
        on stocks that are actually tradeable with good liquidity.
        
        Args:
            bar_size: Bar size (default "1 day")
            duration: Duration per request (default "1 M" = 1 month)
            min_adv: Minimum average daily volume (default 100K)
            
        Returns:
            Job info dict
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        # Get liquid symbols
        logger.info(f"Fetching liquid US stocks (ADV >= {min_adv:,})...")
        symbols = await self.get_liquid_symbols(min_adv=min_adv)
        
        if not symbols:
            return {
                "success": False,
                "error": "Could not fetch liquid stock list."
            }
            
        logger.info(f"Starting liquid collection for {len(symbols)} symbols (ADV >= {min_adv:,})")
        
        # Start collection
        return await self.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False
        )
    
    async def start_collection(
        self,
        symbols: List[str] = None,
        bar_size: str = "5 mins",
        duration: str = "1 M",
        use_defaults: bool = True
    ) -> Dict[str, Any]:
        """
        Start a historical data collection job.
        
        Args:
            symbols: List of symbols to collect (uses defaults if None)
            bar_size: Bar size (1 min, 5 mins, 15 mins, 1 hour, 1 day)
            duration: Duration per request (1 D, 2 D, 1 W, 1 M, etc.)
            use_defaults: If True and no symbols provided, use default list
            
        Returns:
            Job info dict
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        if bar_size not in self.BAR_CONFIGS:
            return {
                "success": False,
                "error": f"Invalid bar_size. Choose from: {list(self.BAR_CONFIGS.keys())}"
            }
            
        if symbols is None or len(symbols) == 0:
            if use_defaults:
                symbols = self.get_default_symbols()
            else:
                return {"success": False, "error": "No symbols provided"}
                
        # Create job
        job = CollectionJob(
            id=f"collect_{uuid.uuid4().hex[:8]}",
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            start_time=datetime.now(timezone.utc).isoformat()
        )
        
        self._running_job = job
        self._cancel_requested = False
        
        # Save job to database
        if self._jobs_col is not None:
            self._jobs_col.insert_one(job.to_dict())
            
        # Start collection in background
        asyncio.create_task(self._run_collection(job))
        
        return {
            "success": True,
            "job_id": job.id,
            "message": f"Started collecting {len(symbols)} symbols with {bar_size} bars",
            "symbols_count": len(symbols)
        }
        
    async def _run_collection(self, job: CollectionJob):
        """Run the collection job"""
        job.status = CollectionStatus.RUNNING
        self._update_job(job)
        
        try:
            total_symbols = len(job.symbols)
            
            for i, symbol in enumerate(job.symbols):
                if self._cancel_requested:
                    job.status = CollectionStatus.CANCELLED
                    break
                    
                job.current_symbol = symbol
                job.progress_pct = (i / total_symbols) * 100
                self._update_job(job)
                
                try:
                    bars_collected = await self._collect_symbol_data(
                        symbol, job.bar_size, job.duration
                    )
                    job.total_bars_collected += bars_collected
                    job.symbols_completed += 1
                    logger.info(f"Collected {bars_collected} bars for {symbol} ({i+1}/{total_symbols})")
                    
                except Exception as e:
                    job.symbols_failed += 1
                    job.errors.append(f"{symbol}: {str(e)}")
                    logger.error(f"Failed to collect {symbol}: {e}")
                    
                # Rate limit - wait between requests
                await asyncio.sleep(self.REQUEST_DELAY_SECONDS)
                
            # Job completed
            if job.status != CollectionStatus.CANCELLED:
                job.status = CollectionStatus.COMPLETED
                
        except Exception as e:
            job.status = CollectionStatus.FAILED
            job.errors.append(f"Job failed: {str(e)}")
            logger.error(f"Collection job failed: {e}")
            
        finally:
            job.end_time = datetime.now(timezone.utc).isoformat()
            job.progress_pct = 100.0
            job.current_symbol = ""
            self._update_job(job)
            self._running_job = None
            
    async def _collect_symbol_data(
        self, 
        symbol: str, 
        bar_size: str, 
        duration: str
    ) -> int:
        """
        Collect historical data for a single symbol.
        
        Returns number of bars collected.
        """
        if not self._ib_service:
            raise Exception("IB service not configured")
            
        bars_collected = 0
        retries = 0
        
        while retries < self.MAX_RETRIES:
            try:
                # Call IB service for historical data
                result = await self._ib_service.get_historical_data(
                    symbol=symbol,
                    duration=duration,
                    bar_size=bar_size
                )
                
                if result.get("success") and result.get("data"):
                    bars = result["data"]
                    
                    # Store in database
                    if self._data_col is not None:
                        for bar in bars:
                            try:
                                self._data_col.update_one(
                                    {
                                        "symbol": symbol,
                                        "bar_size": bar_size,
                                        "date": bar["date"]
                                    },
                                    {
                                        "$set": {
                                            "open": bar["open"],
                                            "high": bar["high"],
                                            "low": bar["low"],
                                            "close": bar["close"],
                                            "volume": bar["volume"],
                                            "collected_at": datetime.now(timezone.utc).isoformat()
                                        }
                                    },
                                    upsert=True
                                )
                                bars_collected += 1
                            except Exception as e:
                                # Duplicate key errors are fine
                                if "duplicate" not in str(e).lower():
                                    logger.warning(f"Error storing bar: {e}")
                                    
                    return bars_collected
                else:
                    error = result.get("error", "Unknown error")
                    if "pacing" in error.lower() or "limit" in error.lower():
                        # Rate limit hit, wait longer
                        await asyncio.sleep(10)
                        retries += 1
                    else:
                        raise Exception(error)
                        
            except Exception:
                retries += 1
                if retries >= self.MAX_RETRIES:
                    raise
                await asyncio.sleep(5)
                
        return bars_collected
        
    def _update_job(self, job: CollectionJob):
        """Update job in database"""
        if self._jobs_col is not None:
            self._jobs_col.update_one(
                {"id": job.id},
                {"$set": job.to_dict()},
                upsert=True
            )
            
    def cancel_collection(self) -> Dict[str, Any]:
        """Cancel the running collection job"""
        if not self._running_job:
            return {"success": False, "error": "No job running"}
            
        self._cancel_requested = True
        return {
            "success": True,
            "message": "Cancellation requested",
            "job_id": self._running_job.id
        }
        
    def get_job_status(self, job_id: str = None) -> Dict[str, Any]:
        """Get status of a collection job"""
        if job_id is None and self._running_job:
            return {
                "success": True,
                "job": self._running_job.to_dict()
            }
            
        if self._jobs_col is None:
            return {"success": False, "error": "Database not connected"}
            
        if job_id:
            job = self._jobs_col.find_one({"id": job_id}, {"_id": 0})
            if job:
                return {"success": True, "job": job}
            return {"success": False, "error": "Job not found"}
            
        # Return current running job
        if self._running_job:
            return {"success": True, "job": self._running_job.to_dict()}
        return {"success": True, "job": None, "message": "No job running"}
        
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about collected data"""
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            # Count by bar size
            pipeline = [
                {"$group": {
                    "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
                    "count": {"$sum": 1},
                    "earliest": {"$min": "$date"},
                    "latest": {"$max": "$date"}
                }},
                {"$group": {
                    "_id": "$_id.bar_size",
                    "symbols": {"$sum": 1},
                    "total_bars": {"$sum": "$count"}
                }}
            ]
            
            bar_stats = list(self._data_col.aggregate(pipeline))
            
            # Total unique symbols
            unique_symbols = self._data_col.distinct("symbol")
            
            # Recent collections
            recent = list(self._data_col.find(
                {},
                {"symbol": 1, "bar_size": 1, "collected_at": 1, "_id": 0}
            ).sort("collected_at", -1).limit(10))
            
            return {
                "success": True,
                "stats": {
                    "unique_symbols": len(unique_symbols),
                    "symbols_list": unique_symbols[:50],  # First 50
                    "by_bar_size": {s["_id"]: {"symbols": s["symbols"], "bars": s["total_bars"]} for s in bar_stats},
                    "total_bars": sum(s["total_bars"] for s in bar_stats),
                    "recent_collections": recent
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {"success": False, "error": str(e)}
            
    def get_job_history(self, limit: int = 10) -> Dict[str, Any]:
        """Get history of collection jobs"""
        if self._jobs_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            jobs = list(self._jobs_col.find(
                {},
                {"_id": 0}
            ).sort("start_time", -1).limit(limit))
            
            return {
                "success": True,
                "jobs": jobs,
                "count": len(jobs)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def get_symbol_data(
        self,
        symbol: str,
        bar_size: str = "5 mins",
        limit: int = 1000
    ) -> Dict[str, Any]:
        """Get collected data for a symbol"""
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            bars = list(self._data_col.find(
                {"symbol": symbol.upper(), "bar_size": bar_size},
                {"_id": 0}
            ).sort("date", -1).limit(limit))
            
            return {
                "success": True,
                "symbol": symbol,
                "bar_size": bar_size,
                "bars": bars,
                "count": len(bars)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_ib_collector: Optional[IBHistoricalCollector] = None


def get_ib_collector() -> IBHistoricalCollector:
    """Get the singleton instance"""
    global _ib_collector
    if _ib_collector is None:
        _ib_collector = IBHistoricalCollector()
    return _ib_collector


def init_ib_collector(db=None, ib_service=None, alpaca_service=None) -> IBHistoricalCollector:
    """Initialize the IB historical collector"""
    collector = get_ib_collector()
    collector.set_db(db)
    if ib_service:
        collector.set_ib_service(ib_service)
    if alpaca_service:
        collector.set_alpaca_service(alpaca_service)
    return collector
