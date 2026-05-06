"""
Portfolio Awareness Service - Proactive AI suggestions based on positions
Monitors open positions and generates alerts/suggestions without user prompting
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

class SuggestionPriority(Enum):
    CRITICAL = "critical"  # Immediate action needed (stop loss hit, huge loss)
    HIGH = "high"          # Important (large profit, earnings tomorrow)
    MEDIUM = "medium"      # Worth noting (sector exposure, correlation)
    LOW = "low"            # Informational (general suggestions)

class SuggestionType(Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    SCALE_OUT = "scale_out"
    SCALE_IN = "scale_in"
    SECTOR_EXPOSURE = "sector_exposure"
    CORRELATION_RISK = "correlation_risk"
    EARNINGS_WARNING = "earnings_warning"
    NEWS_ALERT = "news_alert"
    TECHNICAL_LEVEL = "technical_level"
    POSITION_SIZE = "position_size"
    MARKET_CONDITION = "market_condition"

# Sector mapping for common stocks
SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology", "GOOG": "Technology",
    "META": "Technology", "NVDA": "Technology", "AMD": "Technology", "INTC": "Technology",
    "CRM": "Technology", "ADBE": "Technology", "ORCL": "Technology", "CSCO": "Technology",
    "AVGO": "Technology", "TXN": "Technology", "QCOM": "Technology", "MU": "Technology",
    "AMAT": "Technology", "LRCX": "Technology", "KLAC": "Technology", "MRVL": "Technology",
    "NOW": "Technology", "SNOW": "Technology", "PLTR": "Technology", "NET": "Technology",
    "CRWD": "Technology", "ZS": "Technology", "DDOG": "Technology", "MDB": "Technology",
    # Consumer
    "AMZN": "Consumer", "TSLA": "Consumer", "HD": "Consumer", "NKE": "Consumer",
    "MCD": "Consumer", "SBUX": "Consumer", "TGT": "Consumer", "COST": "Consumer",
    "WMT": "Consumer", "LOW": "Consumer", "DG": "Consumer", "DLTR": "Consumer",
    # Healthcare
    "JNJ": "Healthcare", "UNH": "Healthcare", "PFE": "Healthcare", "MRK": "Healthcare",
    "ABBV": "Healthcare", "LLY": "Healthcare", "TMO": "Healthcare", "ABT": "Healthcare",
    "DHR": "Healthcare", "BMY": "Healthcare", "AMGN": "Healthcare", "GILD": "Healthcare",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials", "GS": "Financials",
    "MS": "Financials", "C": "Financials", "BLK": "Financials", "SCHW": "Financials",
    "AXP": "Financials", "V": "Financials", "MA": "Financials", "PYPL": "Financials",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy",
    "EOG": "Energy", "PXD": "Energy", "MPC": "Energy", "VLO": "Energy",
    "OXY": "Energy", "HAL": "Energy", "DVN": "Energy", "FANG": "Energy",
    # Communication
    "NFLX": "Communication", "DIS": "Communication", "CMCSA": "Communication",
    "T": "Communication", "VZ": "Communication", "TMUS": "Communication",
    # Industrials
    "CAT": "Industrials", "BA": "Industrials", "HON": "Industrials", "UNP": "Industrials",
    "UPS": "Industrials", "RTX": "Industrials", "DE": "Industrials", "LMT": "Industrials",
    # Materials
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials", "ECL": "Materials",
    "NEM": "Materials", "FCX": "Materials", "NUE": "Materials", "DOW": "Materials",
}

@dataclass
class PortfolioSuggestion:
    """A proactive suggestion from the portfolio awareness system"""
    id: str
    type: SuggestionType
    priority: SuggestionPriority
    symbol: Optional[str]
    title: str
    message: str
    reasoning: List[str]
    suggested_action: Optional[str]
    current_value: Optional[float]
    target_value: Optional[float]
    created_at: str
    expires_at: str
    dismissed: bool = False
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['type'] = self.type.value
        result['priority'] = self.priority.value
        return result


class PortfolioAwarenessService:
    """
    Monitors portfolio and generates proactive suggestions
    """
    
    def __init__(self, alpaca_service=None, finnhub_service=None, scanner_service=None):
        self._alpaca_service = alpaca_service
        self._finnhub_service = finnhub_service
        self._scanner_service = scanner_service
        self._suggestions: List[PortfolioSuggestion] = []
        self._last_check = None
        self._check_interval = 60  # seconds
        self._position_cache: List[Dict] = []
        self._running = False
        
        # Thresholds for suggestions
        self.PROFIT_SCALE_OUT_PCT = 15.0      # Suggest scale out at 15%+ profit
        self.PROFIT_TAKE_ALL_PCT = 25.0       # Suggest taking all at 25%+ profit
        self.LOSS_WARNING_PCT = -5.0          # Warn at 5% loss
        self.LOSS_STOP_PCT = -10.0            # Strong warning at 10% loss
        self.SECTOR_CONCENTRATION_PCT = 50.0  # Warn if >50% in one sector
        self.POSITION_SIZE_MAX_PCT = 25.0     # Warn if single position >25% of portfolio
        self.EARNINGS_WARNING_DAYS = 3        # Warn if earnings within 3 days
        
    async def initialize(self, alpaca_service=None, finnhub_service=None, scanner_service=None):
        """Initialize with service references"""
        if alpaca_service:
            self._alpaca_service = alpaca_service
        if finnhub_service:
            self._finnhub_service = finnhub_service
        if scanner_service:
            self._scanner_service = scanner_service
        logger.info("Portfolio Awareness Service initialized")
        
    async def start_monitoring(self):
        """Start the background monitoring loop"""
        if self._running:
            return
        self._running = True
        logger.info("Starting Portfolio Awareness monitoring")
        asyncio.create_task(self._monitoring_loop())
        
    async def stop_monitoring(self):
        """Stop the background monitoring loop"""
        self._running = False
        logger.info("Stopped Portfolio Awareness monitoring")
        
    async def _monitoring_loop(self):
        """Background loop that checks portfolio periodically"""
        while self._running:
            try:
                await self.analyze_portfolio()
            except Exception as e:
                logger.error(f"Error in portfolio monitoring: {e}")
            await asyncio.sleep(self._check_interval)
            
    async def analyze_portfolio(self) -> List[PortfolioSuggestion]:
        """
        Analyze current portfolio and generate suggestions
        """
        if not self._alpaca_service:
            logger.warning("Alpaca service not available for portfolio analysis")
            return []
            
        try:
            # Get current positions
            positions = await self._alpaca_service.get_positions()
            self._position_cache = positions
            
            if not positions:
                return []
                
            # Clear old suggestions (keep dismissed ones for a while)
            self._cleanup_old_suggestions()
            
            # Run all analysis checks
            new_suggestions = []
            
            # 1. Check profit/loss levels
            new_suggestions.extend(await self._check_profit_loss_levels(positions))
            
            # 2. Check sector concentration
            new_suggestions.extend(await self._check_sector_concentration(positions))
            
            # 3. Check position sizes
            new_suggestions.extend(await self._check_position_sizes(positions))
            
            # 4. Check for earnings warnings
            new_suggestions.extend(await self._check_earnings_warnings(positions))
            
            # 5. Check technical levels (if scanner available)
            new_suggestions.extend(await self._check_technical_levels(positions))
            
            # 6. Check correlation risk
            new_suggestions.extend(await self._check_correlation_risk(positions))
            
            # Add new suggestions (avoid duplicates)
            for suggestion in new_suggestions:
                if not self._suggestion_exists(suggestion):
                    self._suggestions.append(suggestion)
                    logger.info(f"New portfolio suggestion: {suggestion.title}")
                    
            self._last_check = datetime.now(timezone.utc)
            return self.get_active_suggestions()
            
        except Exception as e:
            logger.error(f"Error analyzing portfolio: {e}")
            return []
            
    async def _check_profit_loss_levels(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check positions for profit taking or stop loss warnings"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        for pos in positions:
            symbol = pos.get('symbol', '')
            pl_pct = pos.get('unrealized_plpc', 0) * 100  # Convert to percentage
            pl_dollars = pos.get('unrealized_pl', 0)
            current_price = pos.get('current_price', 0)
            avg_entry = pos.get('avg_entry_price', 0)
            qty = pos.get('qty', 0)
            
            # Large profit - suggest taking some off
            if pl_pct >= self.PROFIT_TAKE_ALL_PCT:
                suggestions.append(PortfolioSuggestion(
                    id=f"take_profit_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.TAKE_PROFIT,
                    priority=SuggestionPriority.HIGH,
                    symbol=symbol,
                    title=f"🎯 {symbol} up {pl_pct:.1f}% - Consider taking profits",
                    message=f"You're up ${pl_dollars:,.2f} ({pl_pct:.1f}%) on {symbol}. This is a significant gain - consider taking some or all profits.",
                    reasoning=[
                        f"Unrealized gain: ${pl_dollars:,.2f} ({pl_pct:.1f}%)",
                        f"Entry: ${avg_entry:.2f} → Current: ${current_price:.2f}",
                        f"Above {self.PROFIT_TAKE_ALL_PCT}% threshold for profit taking",
                        "Winners can become losers - lock in gains"
                    ],
                    suggested_action=f"Consider selling {int(qty * 0.5)}-{int(qty)} shares",
                    current_value=pl_pct,
                    target_value=0,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=4)).isoformat()
                ))
            elif pl_pct >= self.PROFIT_SCALE_OUT_PCT:
                suggestions.append(PortfolioSuggestion(
                    id=f"scale_out_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.SCALE_OUT,
                    priority=SuggestionPriority.MEDIUM,
                    symbol=symbol,
                    title=f"📈 {symbol} up {pl_pct:.1f}% - Consider scaling out",
                    message=f"Nice gain on {symbol}! Up ${pl_dollars:,.2f} ({pl_pct:.1f}%). Consider taking partial profits to lock in gains.",
                    reasoning=[
                        f"Unrealized gain: ${pl_dollars:,.2f} ({pl_pct:.1f}%)",
                        f"Entry: ${avg_entry:.2f} → Current: ${current_price:.2f}",
                        "Scale out 25-50% to reduce risk",
                        "Let remaining position ride with house money"
                    ],
                    suggested_action=f"Consider selling {int(qty * 0.25)}-{int(qty * 0.5)} shares",
                    current_value=pl_pct,
                    target_value=0,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=4)).isoformat()
                ))
                
            # Loss warnings
            elif pl_pct <= self.LOSS_STOP_PCT:
                suggestions.append(PortfolioSuggestion(
                    id=f"stop_loss_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.STOP_LOSS,
                    priority=SuggestionPriority.CRITICAL,
                    symbol=symbol,
                    title=f"🚨 {symbol} down {abs(pl_pct):.1f}% - Stop loss territory",
                    message=f"ALERT: {symbol} is down ${abs(pl_dollars):,.2f} ({pl_pct:.1f}%). This has exceeded typical stop loss levels. Review immediately.",
                    reasoning=[
                        f"Unrealized loss: ${pl_dollars:,.2f} ({pl_pct:.1f}%)",
                        f"Entry: ${avg_entry:.2f} → Current: ${current_price:.2f}",
                        f"Below {self.LOSS_STOP_PCT}% - typical stop loss level",
                        "Cut losers quickly - preserve capital"
                    ],
                    suggested_action=f"Consider closing position ({int(qty)} shares)",
                    current_value=pl_pct,
                    target_value=self.LOSS_STOP_PCT,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=1)).isoformat()
                ))
            elif pl_pct <= self.LOSS_WARNING_PCT:
                suggestions.append(PortfolioSuggestion(
                    id=f"loss_warning_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.STOP_LOSS,
                    priority=SuggestionPriority.HIGH,
                    symbol=symbol,
                    title=f"⚠️ {symbol} down {abs(pl_pct):.1f}% - Monitor closely",
                    message=f"{symbol} is down ${abs(pl_dollars):,.2f} ({pl_pct:.1f}%). Approaching stop loss territory.",
                    reasoning=[
                        f"Unrealized loss: ${pl_dollars:,.2f} ({pl_pct:.1f}%)",
                        f"Entry: ${avg_entry:.2f} → Current: ${current_price:.2f}",
                        "Consider your original thesis",
                        "Set a hard stop if not already in place"
                    ],
                    suggested_action=f"Review thesis or set stop at ${avg_entry * 0.9:.2f}",
                    current_value=pl_pct,
                    target_value=self.LOSS_STOP_PCT,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=2)).isoformat()
                ))
                
        return suggestions
        
    async def _check_sector_concentration(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check for over-concentration in a single sector"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        # Calculate total portfolio value
        total_value = sum(pos.get('market_value', 0) for pos in positions)
        if total_value <= 0:
            return []
            
        # Calculate sector exposure
        sector_values = {}
        sector_symbols = {}
        for pos in positions:
            symbol = pos.get('symbol', '')
            value = pos.get('market_value', 0)
            sector = SECTOR_MAP.get(symbol, 'Other')
            
            sector_values[sector] = sector_values.get(sector, 0) + value
            if sector not in sector_symbols:
                sector_symbols[sector] = []
            sector_symbols[sector].append(symbol)
            
        # Check for concentration
        for sector, value in sector_values.items():
            pct = (value / total_value) * 100
            if pct >= self.SECTOR_CONCENTRATION_PCT:
                symbols = sector_symbols.get(sector, [])
                suggestions.append(PortfolioSuggestion(
                    id=f"sector_concentration_{sector}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.SECTOR_EXPOSURE,
                    priority=SuggestionPriority.MEDIUM,
                    symbol=None,
                    title=f"🏭 Heavy {sector} exposure ({pct:.0f}%)",
                    message=f"Your portfolio is {pct:.0f}% in {sector} ({', '.join(symbols)}). Consider diversifying to reduce sector-specific risk.",
                    reasoning=[
                        f"{sector} allocation: ${value:,.2f} ({pct:.0f}%)",
                        f"Positions: {', '.join(symbols)}",
                        f"Above {self.SECTOR_CONCENTRATION_PCT}% concentration threshold",
                        "Sector rotation could hurt all positions simultaneously"
                    ],
                    suggested_action="Consider trimming some positions or hedging with sector ETF puts",
                    current_value=pct,
                    target_value=30.0,  # Ideal max sector exposure
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=8)).isoformat()
                ))
                
        return suggestions
        
    async def _check_position_sizes(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check for oversized individual positions"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        total_value = sum(pos.get('market_value', 0) for pos in positions)
        if total_value <= 0:
            return []
            
        for pos in positions:
            symbol = pos.get('symbol', '')
            value = pos.get('market_value', 0)
            pct = (value / total_value) * 100
            
            if pct >= self.POSITION_SIZE_MAX_PCT:
                suggestions.append(PortfolioSuggestion(
                    id=f"position_size_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.POSITION_SIZE,
                    priority=SuggestionPriority.MEDIUM,
                    symbol=symbol,
                    title=f"📊 {symbol} is {pct:.0f}% of portfolio",
                    message=f"{symbol} represents {pct:.0f}% of your portfolio (${value:,.2f}). Large single-stock exposure increases risk.",
                    reasoning=[
                        f"Position value: ${value:,.2f} ({pct:.0f}% of portfolio)",
                        f"Above {self.POSITION_SIZE_MAX_PCT}% single-position threshold",
                        "Single stock risk: earnings, news, sector moves",
                        "Consider trimming to reduce concentration"
                    ],
                    suggested_action="Consider reducing to 15-20% of portfolio",
                    current_value=pct,
                    target_value=20.0,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=8)).isoformat()
                ))
                
        return suggestions
        
    async def _check_earnings_warnings(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check if any held stocks have earnings coming up"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        if not self._finnhub_service:
            return []
            
        for pos in positions:
            symbol = pos.get('symbol', '')
            try:
                # Get earnings calendar for this symbol
                earnings = await self._finnhub_service.get_earnings_calendar(symbol)
                
                if earnings:
                    for earning in earnings[:1]:  # Just check next earnings
                        earnings_date_str = earning.get('date', '')
                        if earnings_date_str:
                            try:
                                earnings_date = datetime.strptime(earnings_date_str, '%Y-%m-%d')
                                days_until = (earnings_date - datetime.now()).days
                                
                                if 0 <= days_until <= self.EARNINGS_WARNING_DAYS:
                                    pl_pct = pos.get('unrealized_plpc', 0) * 100
                                    suggestions.append(PortfolioSuggestion(
                                        id=f"earnings_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                                        type=SuggestionType.EARNINGS_WARNING,
                                        priority=SuggestionPriority.HIGH if days_until <= 1 else SuggestionPriority.MEDIUM,
                                        symbol=symbol,
                                        title=f"📅 {symbol} earnings in {days_until} day{'s' if days_until != 1 else ''}",
                                        message=f"You hold {symbol} and earnings are {'TOMORROW' if days_until == 1 else 'TODAY' if days_until == 0 else f'in {days_until} days'}. Consider your strategy.",
                                        reasoning=[
                                            f"Earnings date: {earnings_date_str}",
                                            f"Current P/L: {pl_pct:.1f}%",
                                            "Earnings can cause large moves (5-20%+ either direction)",
                                            "Options IV typically elevated - consider hedging costs"
                                        ],
                                        suggested_action="Trim position, hold through, or hedge with options",
                                        current_value=days_until,
                                        target_value=0,
                                        created_at=now.isoformat(),
                                        expires_at=(now + timedelta(days=days_until + 1)).isoformat()
                                    ))
                            except ValueError:
                                pass
            except Exception as e:
                logger.debug(f"Could not check earnings for {symbol}: {e}")
                
        return suggestions
        
    async def _check_technical_levels(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check if positions are near key technical levels"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        if not self._scanner_service:
            return []
            
        for pos in positions:
            symbol = pos.get('symbol', '')
            current_price = pos.get('current_price', 0)
            
            try:
                # Try to get technical snapshot from scanner
                snapshot = await self._scanner_service.get_symbol_snapshot(symbol)
                if snapshot:
                    # Check distance to resistance
                    resistance = getattr(snapshot, 'resistance', None)
                    if resistance and current_price > 0:
                        dist_to_resistance = ((resistance - current_price) / current_price) * 100
                        if 0 < dist_to_resistance < 2.0:
                            suggestions.append(PortfolioSuggestion(
                                id=f"near_resistance_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                                type=SuggestionType.TECHNICAL_LEVEL,
                                priority=SuggestionPriority.MEDIUM,
                                symbol=symbol,
                                title=f"📍 {symbol} approaching resistance ${resistance:.2f}",
                                message=f"{symbol} is {dist_to_resistance:.1f}% from resistance at ${resistance:.2f}. Watch for breakout or rejection.",
                                reasoning=[
                                    f"Current: ${current_price:.2f}",
                                    f"Resistance: ${resistance:.2f} ({dist_to_resistance:.1f}% away)",
                                    "Could break out (add) or reject (trim)",
                                    "Watch volume for confirmation"
                                ],
                                suggested_action="Watch for breakout with volume to add, or trim if rejected",
                                current_value=current_price,
                                target_value=resistance,
                                created_at=now.isoformat(),
                                expires_at=(now + timedelta(hours=2)).isoformat()
                            ))
                            
                    # Check distance to support
                    support = getattr(snapshot, 'support', None)
                    if support and current_price > 0:
                        dist_to_support = ((current_price - support) / current_price) * 100
                        if 0 < dist_to_support < 2.0:
                            suggestions.append(PortfolioSuggestion(
                                id=f"near_support_{symbol}_{now.strftime('%Y%m%d%H%M%S')}",
                                type=SuggestionType.TECHNICAL_LEVEL,
                                priority=SuggestionPriority.HIGH,
                                symbol=symbol,
                                title=f"⚠️ {symbol} near support ${support:.2f}",
                                message=f"{symbol} is only {dist_to_support:.1f}% above support at ${support:.2f}. Critical level - watch for bounce or break.",
                                reasoning=[
                                    f"Current: ${current_price:.2f}",
                                    f"Support: ${support:.2f} ({dist_to_support:.1f}% below)",
                                    "Support break could accelerate losses",
                                    "Bounce could be add opportunity"
                                ],
                                suggested_action=f"Set stop below ${support:.2f} or trim if broken",
                                current_value=current_price,
                                target_value=support,
                                created_at=now.isoformat(),
                                expires_at=(now + timedelta(hours=2)).isoformat()
                            ))
            except Exception as e:
                logger.debug(f"Could not check technicals for {symbol}: {e}")
                
        return suggestions
        
    async def _check_correlation_risk(self, positions: List[Dict]) -> List[PortfolioSuggestion]:
        """Check for highly correlated positions"""
        suggestions = []
        now = datetime.now(timezone.utc)
        
        # Simple correlation check based on sector
        sector_counts = {}
        for pos in positions:
            symbol = pos.get('symbol', '')
            sector = SECTOR_MAP.get(symbol, 'Other')
            if sector not in sector_counts:
                sector_counts[sector] = []
            sector_counts[sector].append(symbol)
            
        # Flag sectors with 3+ positions
        for sector, symbols in sector_counts.items():
            if len(symbols) >= 3 and sector != 'Other':
                suggestions.append(PortfolioSuggestion(
                    id=f"correlation_{sector}_{now.strftime('%Y%m%d%H%M%S')}",
                    type=SuggestionType.CORRELATION_RISK,
                    priority=SuggestionPriority.LOW,
                    symbol=None,
                    title=f"🔗 {len(symbols)} correlated {sector} positions",
                    message=f"You have {len(symbols)} positions in {sector}: {', '.join(symbols)}. These tend to move together.",
                    reasoning=[
                        f"Positions: {', '.join(symbols)}",
                        "Same-sector stocks often move in tandem",
                        "Sector rotation could affect all positions",
                        "Consider diversifying across sectors"
                    ],
                    suggested_action="Consider keeping only your highest conviction pick",
                    current_value=len(symbols),
                    target_value=2,
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=12)).isoformat()
                ))
                
        return suggestions
        
    def _cleanup_old_suggestions(self):
        """Remove expired suggestions"""
        now = datetime.now(timezone.utc)
        self._suggestions = [
            s for s in self._suggestions
            if datetime.fromisoformat(s.expires_at.replace('Z', '+00:00')) > now
            or s.dismissed
        ]
        
    def _suggestion_exists(self, new_suggestion: PortfolioSuggestion) -> bool:
        """Check if a similar suggestion already exists"""
        for existing in self._suggestions:
            # Same type and symbol within last hour
            if (existing.type == new_suggestion.type and 
                existing.symbol == new_suggestion.symbol and
                not existing.dismissed):
                return True
        return False
        
    def get_active_suggestions(self) -> List[Dict]:
        """Get all active (non-dismissed, non-expired) suggestions"""
        now = datetime.now(timezone.utc)
        active = [
            s.to_dict() for s in self._suggestions
            if not s.dismissed and
            datetime.fromisoformat(s.expires_at.replace('Z', '+00:00')) > now
        ]
        # Sort by priority
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        active.sort(key=lambda x: priority_order.get(x['priority'], 4))
        return active
        
    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Dismiss a suggestion by ID"""
        for suggestion in self._suggestions:
            if suggestion.id == suggestion_id:
                suggestion.dismissed = True
                logger.info(f"Dismissed suggestion: {suggestion_id}")
                return True
        return False
        
    def get_portfolio_summary(self) -> Dict:
        """Get a summary of portfolio health"""
        positions = self._position_cache
        if not positions:
            return {"status": "no_positions", "suggestions_count": 0}
            
        total_value = sum(pos.get('market_value', 0) for pos in positions)
        total_pl = sum(pos.get('unrealized_pl', 0) for pos in positions)
        
        # Count by P/L status
        winners = len([p for p in positions if p.get('unrealized_pl', 0) > 0])
        losers = len([p for p in positions if p.get('unrealized_pl', 0) < 0])
        
        # Sector breakdown
        sectors = {}
        for pos in positions:
            sector = SECTOR_MAP.get(pos.get('symbol', ''), 'Other')
            sectors[sector] = sectors.get(sector, 0) + pos.get('market_value', 0)
            
        return {
            "status": "active",
            "total_positions": len(positions),
            "total_value": total_value,
            "total_pl": total_pl,
            "total_pl_pct": (total_pl / total_value * 100) if total_value > 0 else 0,
            "winners": winners,
            "losers": losers,
            "win_rate": (winners / len(positions) * 100) if positions else 0,
            "sectors": sectors,
            "suggestions_count": len(self.get_active_suggestions()),
            "last_check": self._last_check.isoformat() if self._last_check else None
        }


# Singleton instance
_portfolio_awareness_service: Optional[PortfolioAwarenessService] = None

def get_portfolio_awareness_service() -> PortfolioAwarenessService:
    global _portfolio_awareness_service
    if _portfolio_awareness_service is None:
        _portfolio_awareness_service = PortfolioAwarenessService()
    return _portfolio_awareness_service
