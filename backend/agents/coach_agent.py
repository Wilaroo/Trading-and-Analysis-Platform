"""
Coach Agent
Provides personalized trading guidance based on YOUR data and learning layers.
Uses the larger model for reasoning but all data comes from CODE.
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentType, AgentResponse, DataFetcher
from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class TradingContext:
    """Context for coaching, built from verified data"""
    positions: List[Dict]
    total_pnl: float
    winning_positions: int
    losing_positions: int
    largest_winner: Optional[Dict]
    largest_loser: Optional[Dict]
    portfolio_exposure: float
    performance_stats: Dict
    similar_past_trades: List[Dict]
    mistake_patterns: List[str]
    market_regime: str


class CoachAgent(BaseAgent):
    """
    Trading coach agent - provides personalized guidance.
    
    Data Flow:
    1. CODE fetches all position/performance data
    2. CODE builds context from learning layers
    3. LLM reasons over verified data
    4. LLM provides personalized guidance
    
    The LLM never invents numbers - it explains and advises based on real data.
    """
    
    def __init__(self, llm_provider: LLMProvider = None):
        super().__init__(
            agent_type=AgentType.COACH,
            llm_provider=llm_provider,
            model="gpt-oss:120b-cloud"  # Larger model for quality reasoning
        )
        
        self.data_fetcher: Optional[DataFetcher] = None
    
    def inject_services(self, services: Dict[str, Any]):
        """Inject services and create data fetcher"""
        super().inject_services(services)
        self.data_fetcher = DataFetcher(services)
    
    def get_system_prompt(self) -> str:
        """System prompt for coaching"""
        return """You are an expert trading coach. Your role is to provide personalized guidance based on the trader's ACTUAL data.

CRITICAL RULES:
1. ONLY reference numbers that appear in the VERIFIED DATA section below
2. NEVER invent or estimate any numbers
3. Reference the trader's specific patterns and history
4. Be encouraging but honest about areas for improvement
5. Give actionable advice based on their actual performance

Your coaching should:
- Reference their specific win rate, not general statistics
- Point out patterns in THEIR trading (from the data provided)
- Suggest improvements based on THEIR mistakes
- Celebrate THEIR wins with specific examples
- Warn about THEIR common pitfalls

Keep responses concise but insightful. Use their actual numbers."""
    
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Process a coaching request.
        
        Flow:
        1. Fetch all relevant data from CODE
        2. Build coaching context from learning layers
        3. Have LLM reason over verified data (or provide raw data if LLM unavailable)
        4. Return personalized guidance
        """
        start = time.time()
        message = input_data.get("message", "")
        query_type = input_data.get("query_type", "general")  # general, position, performance, trade_decision
        symbol = input_data.get("symbol")
        
        # Step 1: Fetch verified data from CODE
        context = await self._build_coaching_context(symbol)
        
        # For position queries, return data even if LLM is unavailable
        if query_type == "position":
            # Build position summary from CODE (no LLM needed)
            position_text = self._format_positions_for_display(context)
            
            # Try to get LLM commentary (but don't fail if unavailable)
            try:
                prompt = self._build_coaching_prompt(message, context, query_type)
                response = await self._call_llm(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=800
                )
                if response.success:
                    position_text = response.content
            except Exception as e:
                logger.warning(f"LLM unavailable for position commentary: {e}")
            
            return self._create_response(
                success=True,
                content={
                    "message": position_text,
                    "context_used": {
                        "positions_count": len(context.positions),
                        "total_pnl": context.total_pnl,
                        "performance_available": bool(context.performance_stats)
                    },
                    "positions": context.positions  # Include raw position data
                },
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only" if not response.success else response.model,
                metadata={"query_type": query_type}
            )
        
        # Step 2: Build prompt with verified data
        prompt = self._build_coaching_prompt(message, context, query_type)
        
        # Step 3: Get LLM guidance (reasoning over verified data)
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.7,
            max_tokens=1500
        )
        
        if not response.success:
            # Return basic info when LLM is unavailable
            basic_response = f"""**Connection Status**: Your local trading system appears to be offline.

**Portfolio Summary (from last sync)**:
- Total Positions: {len(context.positions)}
- Total P&L: ${context.total_pnl:,.2f}
- Winning: {context.winning_positions} | Losing: {context.losing_positions}

Please ensure your local IB Gateway and data pusher are running."""
            
            return self._create_response(
                success=True,  # Still success - we provided useful info
                content={"message": basic_response},
                latency_ms=(time.time() - start) * 1000,
                error=response.error,
                metadata={"llm_available": False}
            )
        
        return self._create_response(
            success=True,
            content={
                "message": response.content,
                "context_used": {
                    "positions_count": len(context.positions),
                    "total_pnl": context.total_pnl,
                    "performance_available": bool(context.performance_stats)
                }
            },
            latency_ms=(time.time() - start) * 1000,
            model_used=response.model,
            metadata={"query_type": query_type}
        )
    
    def _format_positions_for_display(self, context: TradingContext) -> str:
        """Format positions as text (no LLM needed)"""
        if not context.positions:
            return """**Your Current Positions**: None

You have no open positions at this time."""
        
        lines = ["**Your Current Positions**:\n"]
        for pos in context.positions:
            symbol = pos.get("symbol", "?")
            shares = pos.get("position", pos.get("shares", 0))
            price = pos.get("marketPrice", pos.get("current_price", 0))
            avg_cost = pos.get("avgCost", pos.get("averageCost", 0))
            pnl = pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0))
            pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{emoji} **{symbol}**: {shares:,.0f} shares @ ${avg_cost:.2f} → ${price:.2f} | P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)")
        
        lines.append(f"\n**Portfolio Summary**:")
        lines.append(f"- Total P&L: ${context.total_pnl:,.2f}")
        lines.append(f"- Winners: {context.winning_positions} | Losers: {context.losing_positions}")
        lines.append(f"- Exposure: ${context.portfolio_exposure:,.2f}")
        
        return "\n".join(lines)
    
    async def _build_coaching_context(self, symbol: str = None) -> TradingContext:
        """
        Build coaching context from CODE (verified data only).
        """
        # Fetch positions from IB
        positions = await self.data_fetcher.get_positions()
        
        # Calculate position metrics from CODE
        total_pnl = 0
        winning = 0
        losing = 0
        largest_winner = None
        largest_loser = None
        largest_win_pnl = 0
        largest_loss_pnl = 0
        
        for pos in positions:
            pnl = float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)))
            total_pnl += pnl
            
            if pnl > 0:
                winning += 1
                if pnl > largest_win_pnl:
                    largest_win_pnl = pnl
                    largest_winner = pos
            elif pnl < 0:
                losing += 1
                if pnl < largest_loss_pnl:
                    largest_loss_pnl = pnl
                    largest_loser = pos
        
        # Calculate exposure
        portfolio_exposure = sum(
            abs(float(p.get("position", 0)) * float(p.get("marketPrice", 0)))
            for p in positions
        )
        
        # Fetch performance stats from learning layer
        performance_stats = await self.data_fetcher.get_performance_stats(symbol=symbol)
        
        # Fetch similar past trades if symbol provided
        similar_trades = []
        if symbol:
            similar_trades = await self.data_fetcher.get_trade_history(symbol=symbol, limit=5)
        
        # Get mistake patterns from learning layer
        mistake_patterns = await self._get_mistake_patterns()
        
        # Detect market regime
        market_regime = await self._detect_market_regime()
        
        return TradingContext(
            positions=positions,
            total_pnl=total_pnl,
            winning_positions=winning,
            losing_positions=losing,
            largest_winner=largest_winner,
            largest_loser=largest_loser,
            portfolio_exposure=portfolio_exposure,
            performance_stats=performance_stats,
            similar_past_trades=similar_trades,
            mistake_patterns=mistake_patterns,
            market_regime=market_regime
        )
    
    async def _get_mistake_patterns(self) -> List[str]:
        """Get common mistake patterns from learning layer"""
        # This would integrate with the learning service
        # For now, return empty - will connect to actual service
        learning_service = self.get_service("learning_service")
        if learning_service is not None:
            try:
                patterns = await learning_service.get_mistake_patterns()
                return patterns
            except:
                pass
        return []
    
    async def _detect_market_regime(self) -> str:
        """Detect current market regime"""
        # This would integrate with market analysis
        # For now, return a default
        return "unknown"
    
    def _build_coaching_prompt(self, message: str, context: TradingContext, query_type: str) -> str:
        """Build prompt with verified data for LLM"""
        
        # Build position summary
        positions_text = ""
        if context.positions:
            positions_text = "YOUR CURRENT POSITIONS (VERIFIED FROM IB):\n"
            for pos in context.positions:
                symbol = pos.get("symbol", "?")
                shares = pos.get("position", pos.get("shares", 0))
                price = pos.get("marketPrice", pos.get("current_price", 0))
                avg_cost = pos.get("avgCost", pos.get("averageCost", 0))
                pnl = pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0))
                
                positions_text += f"  - {symbol}: {shares:,.0f} shares @ ${avg_cost:.2f} avg | "
                positions_text += f"Current: ${price:.2f} | P&L: ${pnl:,.2f}\n"
        else:
            positions_text = "YOUR CURRENT POSITIONS: None\n"
        
        # Build performance summary
        perf_text = ""
        if context.performance_stats:
            stats = context.performance_stats
            perf_text = f"""
YOUR PERFORMANCE STATS (VERIFIED):
  - Total Trades: {stats.get('total_trades', 'N/A')}
  - Win Rate: {stats.get('win_rate', 'N/A')}%
  - Average Winner: ${stats.get('avg_winner', 'N/A')}
  - Average Loser: ${stats.get('avg_loser', 'N/A')}
  - Profit Factor: {stats.get('profit_factor', 'N/A')}
"""
        
        # Build similar trades section
        similar_text = ""
        if context.similar_past_trades:
            similar_text = "\nSIMILAR PAST TRADES:\n"
            for trade in context.similar_past_trades[:3]:
                similar_text += f"  - {trade.get('symbol')} on {trade.get('date', '?')}: "
                similar_text += f"P&L ${trade.get('pnl', 0):,.2f}\n"
        
        # Build mistake patterns section
        mistakes_text = ""
        if context.mistake_patterns:
            mistakes_text = "\nYOUR COMMON PATTERNS TO WATCH:\n"
            for pattern in context.mistake_patterns[:3]:
                mistakes_text += f"  - {pattern}\n"
        
        # Portfolio summary
        summary = f"""
PORTFOLIO SUMMARY (VERIFIED):
  - Total Unrealized P&L: ${context.total_pnl:,.2f}
  - Winning Positions: {context.winning_positions}
  - Losing Positions: {context.losing_positions}
  - Portfolio Exposure: ${context.portfolio_exposure:,.2f}
"""
        
        if context.largest_winner:
            w = context.largest_winner
            summary += f"  - Largest Winner: {w.get('symbol')} (+${w.get('unrealizedPNL', 0):,.2f})\n"
        if context.largest_loser:
            l = context.largest_loser
            summary += f"  - Largest Loser: {l.get('symbol')} (${l.get('unrealizedPNL', 0):,.2f})\n"
        
        # Combine into full prompt
        prompt = f"""=== VERIFIED DATA (DO NOT MODIFY THESE NUMBERS) ===

{positions_text}
{summary}
{perf_text}
{similar_text}
{mistakes_text}

=== USER QUESTION ===
{message}

=== YOUR TASK ===
Provide personalized coaching based ONLY on the verified data above.
Reference their specific numbers and patterns.
Be concise but insightful."""
        
        return prompt
    
    async def get_in_trade_guidance(self, symbol: str, entry_price: float, 
                                    current_price: float, position_size: int) -> Dict:
        """
        Get real-time guidance for an active trade.
        All numbers come from parameters (CODE), LLM only advises.
        """
        start = time.time()
        
        # Calculate metrics from CODE
        pnl = (current_price - entry_price) * position_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        # Fetch context
        performance_stats = await self.data_fetcher.get_performance_stats(symbol=symbol)
        similar_trades = await self.data_fetcher.get_trade_history(symbol=symbol, limit=5)
        
        # Build guidance prompt
        prompt = f"""=== ACTIVE TRADE (VERIFIED DATA) ===

Symbol: {symbol}
Entry Price: ${entry_price:.2f}
Current Price: ${current_price:.2f}
Position Size: {position_size:,} shares
Current P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)

YOUR HISTORY WITH {symbol}:
{self._format_trade_history(similar_trades)}

YOUR OVERALL STATS:
- Win Rate: {performance_stats.get('win_rate', 'N/A')}%
- Avg Winner Exit: {performance_stats.get('avg_winner_r', 'N/A')}R

=== QUESTION ===
Based on my actual trading data, what should I do with this position right now?
Consider my historical patterns and tendencies.

Keep response under 150 words. Be specific and actionable."""
        
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.7,
            max_tokens=300
        )
        
        return {
            "success": response.success,
            "guidance": response.content if response.success else "Unable to generate guidance",
            "trade_metrics": {
                "symbol": symbol,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "position_size": position_size
            },
            "latency_ms": (time.time() - start) * 1000
        }
    
    def _format_trade_history(self, trades: List[Dict]) -> str:
        """Format trade history for prompt"""
        if not trades:
            return "No previous trades in this symbol."
        
        lines = []
        for t in trades[:5]:
            lines.append(f"  - {t.get('date', '?')}: {t.get('result', '?')} | P&L: ${t.get('pnl', 0):,.2f}")
        
        return "\n".join(lines)
