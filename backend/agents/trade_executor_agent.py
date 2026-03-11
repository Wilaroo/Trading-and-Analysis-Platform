"""
Trade Executor Agent
Handles trade execution requests safely.
LLM ONLY parses intent - CODE handles all numbers and execution.
"""
import time
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentType, AgentResponse, DataFetcher
from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class TradeIntent:
    """Parsed trade intent (from LLM)"""
    action: str  # buy, sell, close, add, reduce
    symbol: str
    quantity_type: str  # all, half, shares, dollars
    quantity_value: Optional[float] = None  # Only for shares/dollars type
    confirmed: bool = False


@dataclass  
class TradeOrder:
    """Validated trade order ready for execution (from CODE)"""
    symbol: str
    action: str  # BUY or SELL
    quantity: int  # ALWAYS from code, never from LLM
    order_type: str = "MKT"
    limit_price: Optional[float] = None
    current_price: float = 0.0
    position_value: float = 0.0


class TradeExecutorAgent(BaseAgent):
    """
    Safe trade execution agent.
    
    KEY SAFETY PRINCIPLE:
    - LLM: Parses language ("close TMC" -> {action: close, symbol: TMC})
    - CODE: Handles all numbers (looks up position, calculates quantity)
    
    This prevents hallucination of quantities.
    """
    
    def __init__(self, llm_provider: LLMProvider = None):
        super().__init__(
            agent_type=AgentType.TRADE_EXECUTOR,
            llm_provider=llm_provider,
            model="llama3:8b"  # Fast model - only parsing intent, not reasoning
        )
        
        self.data_fetcher: Optional[DataFetcher] = None
    
    def inject_services(self, services: Dict[str, Any]):
        """Inject services and create data fetcher"""
        super().inject_services(services)
        self.data_fetcher = DataFetcher(services)
    
    def get_system_prompt(self) -> str:
        """System prompt for trade intent parsing"""
        return """You parse trade commands. Extract the action and symbol ONLY.
DO NOT invent or guess quantities - the system will look those up.

Parse the user's trade command into JSON:
{
  "action": "close|buy|sell|add|reduce",
  "symbol": "TICKER",
  "quantity_type": "all|half|shares|dollars",
  "quantity_value": null or number (only if user specified exact shares/dollars)
}

Examples:
"close TMC" -> {"action": "close", "symbol": "TMC", "quantity_type": "all", "quantity_value": null}
"sell half my NVDA" -> {"action": "sell", "symbol": "NVDA", "quantity_type": "half", "quantity_value": null}
"buy 100 shares AAPL" -> {"action": "buy", "symbol": "AAPL", "quantity_type": "shares", "quantity_value": 100}

ONLY output JSON, nothing else."""
    
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Process a trade execution request.
        
        Flow:
        1. Parse intent with LLM (gets action + symbol)
        2. Look up REAL position from code (gets actual quantity)
        3. Validate trade is possible
        4. Queue order for execution
        """
        start = time.time()
        message = input_data.get("message", "")
        confirmed = input_data.get("confirmed", False)
        context = input_data.get("context", {})
        
        # Step 1: Parse trade intent with LLM
        intent = await self._parse_trade_intent(message, context)
        
        if not intent:
            return self._create_response(
                success=False,
                content={"message": "I couldn't understand that trade command. Try: 'close TMC' or 'sell NVDA'"},
                latency_ms=(time.time() - start) * 1000,
                error="Failed to parse trade intent"
            )
        
        # Step 2: Look up REAL position data from CODE (not LLM)
        positions = await self.data_fetcher.get_positions()
        position = self._find_position(positions, intent.symbol)
        
        if intent.action in ["close", "sell", "reduce"] and not position:
            return self._create_response(
                success=False,
                content={
                    "message": f"No position found in {intent.symbol}. Cannot {intent.action}.",
                    "intent": intent.__dict__,
                    "available_positions": [p.get("symbol") for p in positions]
                },
                latency_ms=(time.time() - start) * 1000,
                error=f"No position in {intent.symbol}"
            )
        
        # Step 3: Calculate order from CODE (verified data)
        order = self._calculate_order(intent, position)
        
        if not order:
            return self._create_response(
                success=False,
                content={"message": f"Could not create valid order for {intent.symbol}"},
                latency_ms=(time.time() - start) * 1000,
                error="Invalid order"
            )
        
        # Step 4: If not confirmed, ask for confirmation
        if not confirmed:
            return self._create_confirmation_response(intent, order, position, start)
        
        # Step 5: Execute the order
        result = await self._execute_order(order)
        
        return self._create_response(
            success=result.get("success", False),
            content=result,
            latency_ms=(time.time() - start) * 1000,
            model_used=self.default_model,
            metadata={"order": order.__dict__, "intent": intent.__dict__}
        )
    
    async def _parse_trade_intent(self, message: str, context: Dict = None) -> Optional[TradeIntent]:
        """
        Use LLM to parse trade intent from message.
        LLM only extracts action and symbol - NOT quantities.
        """
        # Check if this is a confirmation of previous intent
        if context and context.get("pending_trade"):
            pending = context["pending_trade"]
            confirmations = ["yes", "yeah", "yep", "confirm", "do it", "execute", "go", "ok"]
            if any(message.lower().strip().startswith(c) for c in confirmations):
                return TradeIntent(
                    action=pending.get("action", "close"),
                    symbol=pending.get("symbol", ""),
                    quantity_type=pending.get("quantity_type", "all"),
                    confirmed=True
                )
        
        # Use LLM to parse new intent
        response = await self._call_llm(
            prompt=f'Parse this trade command: "{message}"',
            temperature=0.1,
            max_tokens=100
        )
        
        if not response.success:
            # LLM unavailable - use simple pattern matching fallback
            logger.warning(f"LLM unavailable, using pattern matching fallback: {response.error}")
            return self._simple_parse(message)
        
        try:
            content = response.content.strip()
            # Handle markdown code blocks
            if "```" in content:
                content = content.split("```")[1].replace("json", "").strip()
            
            data = json.loads(content)
            
            return TradeIntent(
                action=data.get("action", "close"),
                symbol=data.get("symbol", "").upper(),
                quantity_type=data.get("quantity_type", "all"),
                quantity_value=data.get("quantity_value"),
                confirmed=False
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse trade intent: {e}")
            
            # Fallback: simple pattern matching
            return self._simple_parse(message)
    
    def _simple_parse(self, message: str) -> Optional[TradeIntent]:
        """Simple fallback parser for common patterns"""
        import re
        
        # Pattern 1: buy/sell N shares of SYMBOL (e.g., "buy 100 shares of AAPL")
        match = re.search(r'(buy|sell)\s+(\d+)\s+shares?\s+(?:of\s+)?([A-Z]{1,5})\b', message, re.IGNORECASE)
        if match:
            action = match.group(1).lower()
            quantity = int(match.group(2))
            symbol = match.group(3).upper()
            
            return TradeIntent(
                action=action,
                symbol=symbol,
                quantity_type="shares",
                quantity_value=quantity
            )
        
        # Pattern 2: buy/sell N SYMBOL (e.g., "buy 100 AAPL", "sell 50 NVDA")
        match = re.search(r'(buy|sell)\s+(\d+)\s+([A-Z]{1,5})\b', message, re.IGNORECASE)
        if match:
            action = match.group(1).lower()
            quantity = int(match.group(2))
            symbol = match.group(3).upper()
            
            return TradeIntent(
                action=action,
                symbol=symbol,
                quantity_type="shares",
                quantity_value=quantity
            )
        
        # Pattern 3: close/sell/buy SYMBOL (e.g., "close TMC", "sell NVDA", "buy AAPL")
        match = re.search(r'(close|sell|buy|exit)\s+([A-Z]{1,5})\b', message, re.IGNORECASE)
        if match:
            action = match.group(1).lower()
            if action == "exit":
                action = "close"
            symbol = match.group(2).upper()
            
            return TradeIntent(
                action=action,
                symbol=symbol,
                quantity_type="all"
            )
        
        return None
    
    def _find_position(self, positions: List[Dict], symbol: str) -> Optional[Dict]:
        """Find a position by symbol (CODE - verified data)"""
        symbol = symbol.upper()
        for pos in positions:
            if pos.get("symbol", "").upper() == symbol:
                return pos
        return None
    
    def _calculate_order(self, intent: TradeIntent, position: Optional[Dict]) -> Optional[TradeOrder]:
        """
        Calculate order details from CODE (not LLM).
        All quantities come from verified position data.
        """
        symbol = intent.symbol.upper()
        
        if intent.action in ["close", "sell", "reduce"]:
            if not position:
                return None
            
            # Get quantity from CODE (verified position data)
            total_shares = abs(float(position.get("position", position.get("shares", 0))))
            current_price = float(position.get("marketPrice", position.get("current_price", 0)))
            position_avg_cost = float(position.get("avgCost", position.get("averageCost", position.get("avg_cost", 0))))
            
            if total_shares == 0:
                return None
            
            # Calculate quantity based on type
            if intent.quantity_type == "all":
                quantity = int(total_shares)
            elif intent.quantity_type == "half":
                quantity = int(total_shares / 2)
            elif intent.quantity_type == "shares" and intent.quantity_value:
                quantity = min(int(intent.quantity_value), int(total_shares))
            else:
                quantity = int(total_shares)
            
            # Determine action based on position direction
            is_long = total_shares > 0
            action = "SELL" if is_long else "BUY"  # Close long = sell, close short = buy
            
            return TradeOrder(
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="MKT",
                current_price=current_price,
                position_value=quantity * current_price
            )
        
        elif intent.action in ["buy", "add"]:
            # For buys, we need to calculate based on account/risk
            # For now, return a placeholder - would integrate with risk service
            return TradeOrder(
                symbol=symbol,
                action="BUY",
                quantity=intent.quantity_value or 100,  # Default or specified
                order_type="MKT"
            )
        
        return None
    
    def _create_confirmation_response(self, intent: TradeIntent, order: TradeOrder, 
                                      position: Optional[Dict], start_time: float) -> AgentResponse:
        """Create a response asking for trade confirmation"""
        
        # Build confirmation message
        if intent.action in ["close", "sell"]:
            avg_cost = position.get("avgCost", position.get("averageCost", 0)) if position else 0
            unrealized_pnl = position.get("unrealizedPNL", position.get("unrealized_pnl", 0)) if position else 0
            
            message = f"""**Trade Confirmation Required**

**Action:** {order.action} {order.quantity:,} shares of {order.symbol}
**Current Price:** ${order.current_price:.2f}
**Position Value:** ${order.position_value:,.2f}
**Avg Cost:** ${avg_cost:.2f}
**Unrealized P&L:** ${unrealized_pnl:,.2f}

Reply **"yes"** to execute this trade."""
        else:
            message = f"""**Trade Confirmation Required**

**Action:** {order.action} {order.quantity:,} shares of {order.symbol}
**Order Type:** {order.order_type}

Reply **"yes"** to execute this trade."""
        
        return self._create_response(
            success=True,
            content={
                "message": message,
                "requires_confirmation": True,
                "pending_trade": {
                    "action": intent.action,
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "quantity_type": intent.quantity_type,
                    "order_action": order.action
                }
            },
            latency_ms=(time.time() - start_time) * 1000,
            model_used=self.default_model,
            metadata={"awaiting_confirmation": True}
        )
    
    async def _execute_order(self, order: TradeOrder) -> Dict:
        """
        Execute the order via the order queue service.
        Order goes to queue -> local pusher executes on IB.
        """
        try:
            # Get order queue service
            from services.order_queue_service import get_order_queue_service
            order_queue = get_order_queue_service()
            
            # Queue the order
            order_id = order_queue.queue_order({
                "symbol": order.symbol,
                "action": order.action,
                "quantity": order.quantity,
                "order_type": order.order_type,
                "limit_price": order.limit_price,
                "source": "trade_executor_agent"
            })
            
            logger.info(f"Order queued: {order.action} {order.quantity} {order.symbol} (ID: {order_id})")
            
            return {
                "success": True,
                "message": f"Order queued: {order.action} {order.quantity:,} shares of {order.symbol}",
                "order_id": order_id,
                "order_details": {
                    "symbol": order.symbol,
                    "action": order.action,
                    "quantity": order.quantity,
                    "order_type": order.order_type
                },
                "status": "queued",
                "next_step": "Your local IB pusher will execute this order"
            }
            
        except Exception as e:
            logger.error(f"Failed to queue order: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to queue order: {e}"
            }
