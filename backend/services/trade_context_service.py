"""
Trade Context Service - Captures complete market context at trade time

This service is responsible for gathering ALL relevant context data when a trade
alert is generated. This context is then stored with the trade outcome for learning.

Data sources:
- Alpaca: Quotes, SPY/QQQ/VIX prices
- IB Gateway: Level 2, fundamentals (optional)
- Internal: Sector rankings, technicals, news sentiment
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from dataclasses import asdict

from models.learning_models import (
    TradeContext, 
    FundamentalContext, 
    TechnicalContext,
    MarketRegime,
    TimeOfDay,
    VolatilityRegime
)

logger = logging.getLogger(__name__)


class TradeContextService:
    """Captures complete context snapshot when a trade setup appears"""
    
    def __init__(self):
        self._alpaca_service = None
        self._ib_service = None
        self._sector_service = None
        self._news_service = None
        self._technical_service = None
        self._sentiment_service = None
        self._db = None
        
        # Cache for expensive lookups (short TTL)
        self._context_cache = {}
        self._cache_ttl_seconds = 30  # Cache context data for 30 seconds
        
    def set_services(
        self,
        alpaca_service=None,
        ib_service=None,
        sector_service=None,
        news_service=None,
        technical_service=None,
        sentiment_service=None,
        db=None
    ):
        """Wire up dependencies"""
        self._alpaca_service = alpaca_service
        self._ib_service = ib_service
        self._sector_service = sector_service
        self._news_service = news_service
        self._technical_service = technical_service
        self._sentiment_service = sentiment_service
        self._db = db
        
    async def capture_context(
        self, 
        symbol: str,
        setup_type: str = "",
        alert_priority: str = "medium",
        tape_score: float = 0.0,
        tape_confirmation: bool = False,
        smb_score: int = 25,
        trade_grade: str = "B"
    ) -> TradeContext:
        """
        Capture complete context snapshot for a trade opportunity.
        
        This is called when a scanner alert is generated, BEFORE execution.
        The context is then stored with the trade outcome for later analysis.
        """
        context = TradeContext()
        
        try:
            # 1. Market-wide context (SPY, QQQ, VIX)
            await self._capture_market_context(context)
            
            # 2. Time context
            self._capture_time_context(context)
            
            # 3. Sector context
            await self._capture_sector_context(context, symbol)
            
            # 4. Symbol fundamentals (from IB or cache)
            await self._capture_fundamental_context(context, symbol)
            
            # 5. Symbol technicals
            await self._capture_technical_context(context, symbol)
            
            # 6. News/Sentiment
            await self._capture_sentiment_context(context, symbol)
            
            # 7. Alert metadata
            context.alert_priority = alert_priority
            context.tape_score = tape_score
            context.tape_confirmation = tape_confirmation
            context.smb_score = smb_score
            context.trade_grade = trade_grade
            
            context.captured_at = datetime.now(timezone.utc).isoformat()
            
        except Exception as e:
            logger.error(f"Error capturing context for {symbol}: {e}")
            # Return partial context - graceful degradation
            
        return context
    
    async def _capture_market_context(self, context: TradeContext):
        """Capture SPY, QQQ, VIX data"""
        try:
            if self._alpaca_service is None:
                return
                
            # Get market quotes
            quotes = await self._alpaca_service.get_quotes_batch(['SPY', 'QQQ', 'IWM'])
            
            if 'SPY' in quotes:
                spy_quote = quotes['SPY']
                spy_change = spy_quote.get('change_percent', 0.0)
                context.spy_change_percent = spy_change
                context.market_regime = self._classify_regime(spy_change)
                
            if 'QQQ' in quotes:
                context.qqq_change_percent = quotes['QQQ'].get('change_percent', 0.0)
                
            # Get VIX from IB service or use fallback
            vix_level = await self._get_vix_level()
            context.vix_level = vix_level
            context.vix_regime = self._classify_vix_regime(vix_level)
            
        except Exception as e:
            logger.warning(f"Error capturing market context: {e}")
            
    def _classify_regime(self, spy_change: float) -> MarketRegime:
        """Classify market regime from SPY change"""
        if spy_change >= 1.5:
            return MarketRegime.STRONG_UPTREND
        elif spy_change >= 0.5:
            return MarketRegime.WEAK_UPTREND
        elif spy_change <= -1.5:
            return MarketRegime.STRONG_DOWNTREND
        elif spy_change <= -0.5:
            return MarketRegime.WEAK_DOWNTREND
        else:
            return MarketRegime.RANGE_BOUND
            
    def _classify_vix_regime(self, vix: float) -> VolatilityRegime:
        """Classify VIX level"""
        if vix < 15:
            return VolatilityRegime.LOW
        elif vix < 20:
            return VolatilityRegime.NORMAL
        elif vix < 30:
            return VolatilityRegime.ELEVATED
        elif vix < 40:
            return VolatilityRegime.HIGH
        else:
            return VolatilityRegime.EXTREME
            
    async def _get_vix_level(self) -> float:
        """Get VIX level from IB service (pushed data or direct) or estimate"""
        try:
            if self._ib_service is not None:
                vix_data = self._ib_service.get_vix()
                if vix_data and vix_data.get('price'):
                    return float(vix_data['price'])
        except Exception as e:
            logger.debug(f"Error getting VIX from IB: {e}")
        
        # Fallback: Try to get from pushed data directly
        try:
            from routers.ib import get_vix_from_pushed_data
            vix_data = get_vix_from_pushed_data()
            if vix_data and vix_data.get('price'):
                return float(vix_data['price'])
        except Exception:
            pass
            
        # Default to normal VIX if unavailable
        return 18.0
        
    def _capture_time_context(self, context: TradeContext):
        """Capture time-of-day context"""
        now = datetime.now(timezone(timedelta(hours=-5)))  # Eastern time
        
        context.day_of_week = now.weekday()
        
        # Calculate minutes from market open (9:30 AM ET)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        context.minutes_from_open = int((now - market_open).total_seconds() / 60)
        
        # Classify time of day
        hour = now.hour
        minute = now.minute
        time_minutes = hour * 60 + minute
        
        if time_minutes < 9 * 60 + 30:
            context.time_of_day = TimeOfDay.PRE_MARKET
        elif time_minutes < 9 * 60 + 35:
            context.time_of_day = TimeOfDay.OPENING_AUCTION
        elif time_minutes < 10 * 60:
            context.time_of_day = TimeOfDay.OPENING_DRIVE
        elif time_minutes < 11 * 60:
            context.time_of_day = TimeOfDay.MORNING_MOMENTUM
        elif time_minutes < 12 * 60:
            context.time_of_day = TimeOfDay.LATE_MORNING
        elif time_minutes < 14 * 60:
            context.time_of_day = TimeOfDay.MIDDAY
        elif time_minutes < 15 * 60 + 30:
            context.time_of_day = TimeOfDay.AFTERNOON
        elif time_minutes < 16 * 60:
            context.time_of_day = TimeOfDay.CLOSE
        else:
            context.time_of_day = TimeOfDay.AFTER_HOURS
            
    async def _capture_sector_context(self, context: TradeContext, symbol: str):
        """Capture sector performance context"""
        try:
            if self._sector_service is None:
                return
                
            # Get sector for symbol
            sector_context = await self._sector_service.get_stock_sector_context(symbol)
            
            if sector_context:
                context.sector = sector_context.get('sector', 'unknown')
                context.sector_performance_rank = sector_context.get('sector_rank', 6)
                context.sector_is_leader = sector_context.get('is_leader', False)
                
        except Exception as e:
            logger.warning(f"Error capturing sector context for {symbol}: {e}")
            
    async def _capture_fundamental_context(self, context: TradeContext, symbol: str):
        """Capture fundamental data from IB or cache"""
        fundamentals = FundamentalContext()
        
        try:
            # Try IB Gateway first
            if self._ib_service is not None:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                
                if ib_data and ib_data.get('success'):
                    fund = ib_data.get('data', {})
                    fundamentals.short_interest_percent = fund.get('short_interest_percent', 0.0)
                    fundamentals.float_shares = fund.get('float_shares', 0)
                    fundamentals.institutional_ownership_percent = fund.get('institutional_ownership_percent', 0.0)
                    fundamentals.pe_ratio = fund.get('pe_ratio')
                    fundamentals.market_cap = fund.get('market_cap')
                    
            # Check for upcoming earnings
            if self._db is not None:
                earnings = self._check_earnings_proximity(symbol)
                if earnings:
                    fundamentals.earnings_days_away = earnings.get('days_away')
                    fundamentals.earnings_score = earnings.get('score', 0)
                    if fundamentals.earnings_days_away is not None and fundamentals.earnings_days_away <= 7:
                        fundamentals.has_catalyst = True
                        fundamentals.catalyst_type = "earnings"
                        
        except Exception as e:
            logger.warning(f"Error capturing fundamental context for {symbol}: {e}")
            
        context.fundamentals = fundamentals
        
    def _check_earnings_proximity(self, symbol: str) -> Optional[Dict]:
        """Check if symbol has earnings coming up"""
        try:
            if self._db is None:
                return None
                
            earnings_col = self._db['earnings_calendar']
            now = datetime.now(timezone.utc)
            
            # Look for earnings in next 14 days
            upcoming = earnings_col.find_one({
                'symbol': symbol,
                'date': {'$gte': now.isoformat(), '$lte': (now + timedelta(days=14)).isoformat()}
            })
            
            if upcoming:
                earnings_date = datetime.fromisoformat(upcoming['date'].replace('Z', '+00:00'))
                days_away = (earnings_date - now).days
                return {
                    'days_away': days_away,
                    'score': upcoming.get('earnings_score', 0)
                }
                
        except Exception:
            pass
            
        return None
        
    async def _capture_technical_context(self, context: TradeContext, symbol: str):
        """Capture technical indicators"""
        technicals = TechnicalContext()
        
        try:
            if self._technical_service is not None:
                snapshot = await self._technical_service.get_technical_snapshot(symbol)
                
                if snapshot:
                    # TechnicalSnapshot is a dataclass, access attributes directly
                    technicals.rsi = getattr(snapshot, 'rsi_14', 50.0)
                    technicals.atr = getattr(snapshot, 'atr', 0.0)
                    technicals.atr_percent = getattr(snapshot, 'atr_percent', 0.0)
                    technicals.vwap_distance_percent = getattr(snapshot, 'dist_from_vwap', 0.0)
                    technicals.relative_volume = getattr(snapshot, 'rvol', 1.0)
                    
                    # MA stack from moving averages
                    ema_20 = getattr(snapshot, 'ema_20', 0)
                    ema_50 = getattr(snapshot, 'ema_50', 0)
                    sma_200 = getattr(snapshot, 'sma_200', 0)
                    if ema_20 > ema_50 > sma_200:
                        technicals.ma_stack = "bullish"
                    elif ema_20 < ema_50 < sma_200:
                        technicals.ma_stack = "bearish"
                    else:
                        technicals.ma_stack = "neutral"
                        
                    # Squeeze
                    technicals.squeeze_active = getattr(snapshot, 'squeeze_on', False)
                    
                    # Support/Resistance distances (calculate from levels)
                    price = getattr(snapshot, 'current_price', 0)
                    support = getattr(snapshot, 'support', 0)
                    resistance = getattr(snapshot, 'resistance', 0)
                    if price > 0 and support > 0:
                        technicals.support_distance_percent = ((price - support) / price) * 100
                    if price > 0 and resistance > 0:
                        technicals.resistance_distance_percent = ((resistance - price) / price) * 100
                    
        except Exception as e:
            logger.warning(f"Error capturing technical context for {symbol}: {e}")
            
        context.technicals = technicals
        
    async def _capture_sentiment_context(self, context: TradeContext, symbol: str):
        """Capture news sentiment"""
        try:
            if self._sentiment_service is not None:
                sentiment = await self._sentiment_service.analyze_sentiment(symbol)
                
                if sentiment:
                    # SentimentResult is a dataclass - access attributes directly
                    context.news_sentiment = sentiment.sentiment_score if hasattr(sentiment, 'sentiment_score') else 0.0
                    context.has_recent_news = (sentiment.news_count > 0) if hasattr(sentiment, 'news_count') else False
                    
                    headlines = sentiment.key_headlines if hasattr(sentiment, 'key_headlines') else []
                    if headlines:
                        context.news_headline = headlines[0] if isinstance(headlines[0], str) else headlines[0].get('headline', '')
                        
        except Exception as e:
            logger.warning(f"Error capturing sentiment context for {symbol}: {e}")


# Singleton instance
_trade_context_service: Optional[TradeContextService] = None


def get_trade_context_service() -> TradeContextService:
    """Get the singleton trade context service"""
    global _trade_context_service
    if _trade_context_service is None:
        _trade_context_service = TradeContextService()
    return _trade_context_service


def init_trade_context_service(
    alpaca_service=None,
    ib_service=None,
    sector_service=None,
    news_service=None,
    technical_service=None,
    sentiment_service=None,
    db=None
) -> TradeContextService:
    """Initialize the trade context service with dependencies"""
    service = get_trade_context_service()
    service.set_services(
        alpaca_service=alpaca_service,
        ib_service=ib_service,
        sector_service=sector_service,
        news_service=news_service,
        technical_service=technical_service,
        sentiment_service=sentiment_service,
        db=db
    )
    return service
