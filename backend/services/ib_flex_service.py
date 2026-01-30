"""
IB Flex Web Service - Pulls verified trade history from Interactive Brokers
Uses the same Flex Query that Kinfo uses for verified trade data
"""
import httpx
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

class IBFlexService:
    """Service for retrieving verified trade data from Interactive Brokers Flex Web Service."""
    
    BASE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService"
    
    def __init__(self):
        self.token = os.environ.get("IB_FLEX_TOKEN")
        self.query_id = os.environ.get("IB_FLEX_QUERY_ID")
        
        if not self.token or not self.query_id:
            logger.warning("IB Flex credentials not configured")
    
    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.query_id)
    
    async def request_report(self) -> Optional[str]:
        """
        Request IB to generate a Flex report.
        Returns reference code for retrieving the report.
        """
        if not self.is_configured:
            logger.error("IB Flex not configured")
            return None
        
        url = f"{self.BASE_URL}.SendRequest"
        params = {
            "t": self.token,
            "q": self.query_id,
            "v": "3"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                
                # Parse XML response
                root = ET.fromstring(response.text)
                status = root.find("Status")
                
                if status is not None and status.text == "Success":
                    ref_code = root.find("ReferenceCode")
                    if ref_code is not None:
                        logger.info(f"Report requested, reference: {ref_code.text}")
                        return ref_code.text
                
                # Check for error
                error_code = root.find("ErrorCode")
                error_msg = root.find("ErrorMessage")
                if error_code is not None:
                    logger.error(f"IB Error {error_code.text}: {error_msg.text if error_msg is not None else 'Unknown'}")
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to request IB report: {e}")
            return None
    
    async def get_report(self, reference_code: str, max_retries: int = 10) -> Optional[str]:
        """
        Retrieve a generated Flex report using the reference code.
        IB may take time to generate reports, so we retry.
        """
        url = f"{self.BASE_URL}.GetStatement"
        params = {
            "t": self.token,
            "q": reference_code,
            "v": "3"
        }
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(url, params=params)
                    
                    # Check if still generating
                    if "FlexStatementResponse" in response.text:
                        root = ET.fromstring(response.text)
                        status = root.find("Status")
                        
                        if status is not None and status.text == "Warn":
                            # Report still being generated
                            error_code = root.find("ErrorCode")
                            if error_code is not None and error_code.text == "1019":
                                logger.info(f"Report generating, retry {attempt + 1}/{max_retries}...")
                                await asyncio.sleep(2)
                                continue
                    
                    # Success - return XML data
                    if "FlexQueryResponse" in response.text:
                        logger.info("Report retrieved successfully")
                        return response.text
                    
                    logger.warning(f"Unexpected response: {response.text[:200]}")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(2)
        
        return None
    
    def parse_trades(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse trade data from IB Flex XML response."""
        trades = []
        
        try:
            root = ET.fromstring(xml_data)
            
            # Find all trade confirmations
            for trade_elem in root.findall(".//TradeConfirm"):
                try:
                    trade = self._parse_trade_element(trade_elem)
                    if trade:
                        trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to parse trade: {e}")
                    continue
            
            # Also check for Trades elements (different report format)
            for trade_elem in root.findall(".//Trade"):
                try:
                    trade = self._parse_trade_element(trade_elem)
                    if trade:
                        trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to parse trade: {e}")
                    continue
            
            logger.info(f"Parsed {len(trades)} trades from IB report")
            
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
        
        return trades
    
    def _parse_trade_element(self, elem) -> Optional[Dict[str, Any]]:
        """Parse a single trade element from XML."""
        symbol = elem.get("symbol", "")
        if not symbol:
            return None
        
        # Parse date/time
        date_str = elem.get("tradeDate", "") or elem.get("dateTime", "")
        time_str = elem.get("tradeTime", "") or elem.get("orderTime", "")
        
        execution_time = None
        if date_str:
            try:
                if time_str:
                    execution_time = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M%S")
                else:
                    execution_time = datetime.strptime(date_str, "%Y%m%d")
                execution_time = execution_time.replace(tzinfo=timezone.utc)
            except:
                execution_time = datetime.now(timezone.utc)
        
        # Parse numeric values safely
        def safe_float(val, default=0.0):
            try:
                return float(val) if val else default
            except:
                return default
        
        return {
            "symbol": symbol,
            "underlying_symbol": elem.get("underlyingSymbol", symbol),
            "asset_class": elem.get("assetCategory", "STK"),
            "description": elem.get("description", ""),
            "transaction_type": "BUY" if elem.get("buySell", "").upper() in ["BUY", "B", "BOT"] else "SELL",
            "quantity": abs(safe_float(elem.get("quantity"))),
            "price": safe_float(elem.get("tradePrice") or elem.get("price")),
            "proceeds": safe_float(elem.get("proceeds")),
            "commission": abs(safe_float(elem.get("ibCommission") or elem.get("commission"))),
            "net_cash": safe_float(elem.get("netCash")),
            "cost_basis": safe_float(elem.get("costBasis")),
            "realized_pnl": safe_float(elem.get("fifoPnlRealized") or elem.get("realizedPnL")),
            "execution_time": execution_time,
            "order_id": elem.get("ibOrderID", "") or elem.get("orderID", ""),
            "exec_id": elem.get("ibExecID", "") or elem.get("execID", ""),
            "exchange": elem.get("exchange", ""),
            "currency": elem.get("currency", "USD"),
            "open_close": elem.get("openCloseIndicator", ""),
            "option_type": elem.get("putCall", ""),
            "strike": safe_float(elem.get("strike")),
            "expiry": elem.get("expiry", ""),
            "multiplier": safe_float(elem.get("multiplier"), 1.0),
        }
    
    async def fetch_trades(self) -> Optional[List[Dict[str, Any]]]:
        """Complete workflow to fetch and parse trades from IB."""
        if not self.is_configured:
            return None
        
        # Request report
        ref_code = await self.request_report()
        if not ref_code:
            return None
        
        # Wait a moment for IB to start generating
        await asyncio.sleep(1)
        
        # Retrieve report
        xml_data = await self.get_report(ref_code)
        if not xml_data:
            return None
        
        # Parse and return trades
        return self.parse_trades(xml_data)
    
    def calculate_performance_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate comprehensive performance metrics from trade data."""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "gross_profit": 0,
                "gross_loss": 0,
                "profit_factor": 0,
                "average_win": 0,
                "average_loss": 0,
                "largest_win": 0,
                "largest_loss": 0,
                "expectancy": 0,
            }
        
        # Filter closed trades with P&L
        pnl_trades = [t for t in trades if t.get("realized_pnl") is not None and t.get("realized_pnl") != 0]
        
        if not pnl_trades:
            return {
                "total_trades": len(trades),
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "note": "No closed trades with P&L data found"
            }
        
        winning = [t for t in pnl_trades if t["realized_pnl"] > 0]
        losing = [t for t in pnl_trades if t["realized_pnl"] < 0]
        
        gross_profit = sum(t["realized_pnl"] for t in winning)
        gross_loss = abs(sum(t["realized_pnl"] for t in losing))
        total_pnl = gross_profit - gross_loss
        
        win_rate = (len(winning) / len(pnl_trades) * 100) if pnl_trades else 0
        avg_win = gross_profit / len(winning) if winning else 0
        avg_loss = gross_loss / len(losing) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss)
        
        # By symbol analysis
        symbols = {}
        for t in pnl_trades:
            sym = t.get("underlying_symbol") or t.get("symbol")
            if sym not in symbols:
                symbols[sym] = {"trades": 0, "pnl": 0, "wins": 0}
            symbols[sym]["trades"] += 1
            symbols[sym]["pnl"] += t["realized_pnl"]
            if t["realized_pnl"] > 0:
                symbols[sym]["wins"] += 1
        
        # Sort by P&L
        best_symbols = sorted(symbols.items(), key=lambda x: x[1]["pnl"], reverse=True)[:5]
        worst_symbols = sorted(symbols.items(), key=lambda x: x[1]["pnl"])[:5]
        
        return {
            "total_trades": len(pnl_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "N/A",
            "average_win": round(avg_win, 2),
            "average_loss": round(avg_loss, 2),
            "largest_win": round(max([t["realized_pnl"] for t in winning], default=0), 2),
            "largest_loss": round(abs(min([t["realized_pnl"] for t in losing], default=0)), 2),
            "expectancy": round(expectancy, 2),
            "best_symbols": [{"symbol": s, **d} for s, d in best_symbols],
            "worst_symbols": [{"symbol": s, **d} for s, d in worst_symbols],
            "total_commissions": round(sum(t.get("commission", 0) for t in trades), 2),
        }


# Singleton instance
ib_flex_service = IBFlexService()
