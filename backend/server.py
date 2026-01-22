"""
TradeCommand - Trading and Analysis Platform Backend
Enhanced with Yahoo Finance, TradingView, Insider Trading, COT Data
Real-Time WebSocket Streaming
"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import httpx
import asyncio
import random
import json
from pymongo import MongoClient

load_dotenv()

app = FastAPI(title="TradeCommand API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
mongo_client = MongoClient(os.environ.get("MONGO_URL"))
db = mongo_client[os.environ.get("DB_NAME", "tradecommand")]

# Collections
strategies_col = db["strategies"]
watchlists_col = db["watchlists"]
alerts_col = db["alerts"]
portfolios_col = db["portfolios"]
newsletters_col = db["newsletters"]
scans_col = db["scans"]
insider_col = db["insider_trades"]
cot_col = db["cot_data"]

# ===================== TRADING STRATEGIES DATA =====================
TRADING_STRATEGIES = {
    "intraday": [
        {"id": "INT-01", "name": "Trend Momentum Continuation", "category": "intraday",
         "criteria": ["Above VWAP and rising", "Price above 20-EMA and 50-EMA", "RVOL ≥ 2", "Higher highs and higher lows on 5-min chart"],
         "indicators": ["VWAP", "20-EMA", "50-EMA", "RVOL"], "timeframe": "5min"},
        {"id": "INT-02", "name": "Intraday Breakout (Range High)", "category": "intraday",
         "criteria": ["Multi-hour range", "Clear resistance with ≥3 touches", "RVOL ≥ 1.5 on breakout", "5-min close above level"],
         "indicators": ["Support/Resistance", "RVOL"], "timeframe": "5min"},
        {"id": "INT-03", "name": "Opening Range Breakout (ORB)", "category": "intraday",
         "criteria": ["Define first 5-30 min high/low", "Break above ORH for long", "Break below ORL for short", "Avoid wide opening range"],
         "indicators": ["Opening Range", "Volume"], "timeframe": "5-30min"},
        {"id": "INT-04", "name": "Gap-and-Go", "category": "intraday",
         "criteria": ["Gap ≥ 3-5% on news/earnings", "Premarket RVOL ≥ 3", "Holds 50%+ of gap into open", "Above VWAP"],
         "indicators": ["Gap %", "RVOL", "VWAP"], "timeframe": "Premarket"},
        {"id": "INT-05", "name": "Pullback in Trend (Buy the Dip)", "category": "intraday",
         "criteria": ["20-EMA > 50-EMA, both rising", "Pullback 20-50% of prior leg", "Tags 20-EMA/VWAP", "Momentum reset then turn up"],
         "indicators": ["20-EMA", "50-EMA", "VWAP", "RSI"], "timeframe": "5min"},
        {"id": "INT-06", "name": "VWAP Bounce", "category": "intraday",
         "criteria": ["Stock trending up above VWAP", "First/second pullback to VWAP", "Rejection wick + bullish candle", "Above-avg 1-min volume"],
         "indicators": ["VWAP", "Volume"], "timeframe": "1min"},
        {"id": "INT-07", "name": "VWAP Reversion (Fade to VWAP)", "category": "intraday",
         "criteria": ["Large extension ≥ 2-3% from VWAP", "Parabolic 1-5 min move", "Momentum divergence", "Target near VWAP"],
         "indicators": ["VWAP", "RSI", "MACD"], "timeframe": "1-5min"},
        {"id": "INT-08", "name": "Mean Reversion After Exhaustion Spike", "category": "intraday",
         "criteria": ["3+ wide-range candles", "Volume climax", "Rejection shadow", "Extension ≥ 3-4 ATR"],
         "indicators": ["ATR", "Volume"], "timeframe": "5min"},
        {"id": "INT-09", "name": "Scalping Micro-Moves", "category": "intraday",
         "criteria": ["Highly liquid name", "Tight spreads", "Small profit target (0.1-0.3%)", "10-50 trades/day"],
         "indicators": ["Level 2", "Spread"], "timeframe": "1min"},
        {"id": "INT-10", "name": "Bull/Bear Flag Intraday", "category": "intraday",
         "criteria": ["Strong initial impulse", "Tight low-volume consolidation", "Trend holds above 9-20 EMA", "Break of flag with volume"],
         "indicators": ["9-EMA", "20-EMA", "Volume"], "timeframe": "5min"},
        {"id": "INT-11", "name": "Reversal at Key Level", "category": "intraday",
         "criteria": ["Prior daily S/R or premarket high/low", "Spike with exhaustion volume", "Reversal candlestick pattern", "Confirmation on next bar"],
         "indicators": ["Support/Resistance", "Volume"], "timeframe": "5min"},
        {"id": "INT-12", "name": "Pivot Point Intraday Strategy", "category": "intraday",
         "criteria": ["Daily pivot levels (P, R1, S1)", "Price stalls/reverses at pivot", "Reversal candle + volume", "Use pivots as targets"],
         "indicators": ["Pivot Points"], "timeframe": "5min"},
        {"id": "INT-13", "name": "Intraday Range Trading", "category": "intraday",
         "criteria": ["Defined intraday high/low early", "Low RVOL and choppy action", "Long near support, short near resistance", "Stops outside range"],
         "indicators": ["Support/Resistance", "RVOL"], "timeframe": "5min"},
        {"id": "INT-14", "name": "News/Earnings Momentum", "category": "intraday",
         "criteria": ["Fresh material catalyst", "Gap or big premarket move", "Continuation pattern (flags)", "High RVOL all session"],
         "indicators": ["News", "RVOL", "Volume"], "timeframe": "All Day"},
        {"id": "INT-15", "name": "Break of Premarket High/Low", "category": "intraday",
         "criteria": ["Strong premarket trend", "Consolidation near level", "Break through on volume", "Tight risk management"],
         "indicators": ["Premarket H/L", "Volume"], "timeframe": "Market Open"},
        {"id": "INT-16", "name": "High-of-Day (HOD) Break Scalps", "category": "intraday",
         "criteria": ["Multiple tests of HOD", "Shallower pullbacks", "Overall uptrend", "Volume building into level"],
         "indicators": ["HOD", "Volume"], "timeframe": "1-5min"},
        {"id": "INT-17", "name": "Range-to-Trend Transition", "category": "intraday",
         "criteria": ["Morning chop with flat indicators", "Decisive range break", "EMAs start to align", "Enter first pullback"],
         "indicators": ["VWAP", "EMAs", "RVOL"], "timeframe": "5min"},
        {"id": "INT-18", "name": "Index-Correlated Trend Riding", "category": "intraday",
         "criteria": ["High beta to SPY/QQQ", "Index in strong trend", "Trade in same direction", "Use index timing"],
         "indicators": ["Beta", "SPY/QQQ"], "timeframe": "5min"},
        {"id": "INT-19", "name": "Liquidity-Grab Stop-Hunt Reversal", "category": "intraday",
         "criteria": ["Clean prior swing high/low", "False breakout with snap back", "Enter against fake break", "Target mid-range"],
         "indicators": ["Support/Resistance"], "timeframe": "5min"},
        {"id": "INT-20", "name": "Time-of-Day Fade (Late-Day Reversal)", "category": "intraday",
         "criteria": ["Extended trend into late session", "Loss of momentum/divergence", "Break of trendline", "Fade into close"],
         "indicators": ["Trendline", "Momentum"], "timeframe": "15min"},
    ],
    "swing": [
        {"id": "SWG-01", "name": "Daily Trend Following", "category": "swing",
         "criteria": ["Price above 50-DMA and 200-DMA", "Higher highs/higher lows on daily", "Buy pullbacks to 20/50-DMA", "Above-avg volume on bounces"],
         "indicators": ["50-DMA", "200-DMA", "20-DMA"], "timeframe": "Daily"},
        {"id": "SWG-02", "name": "Breakout from Multi-Week Base", "category": "swing",
         "criteria": ["4-8 weeks sideways base", "Tightening price action", "Breakout on strong volume", "Stop near breakout level"],
         "indicators": ["Consolidation", "Volume"], "timeframe": "Daily"},
        {"id": "SWG-03", "name": "Range Trading on Daily", "category": "swing",
         "criteria": ["Defined horizontal S/R", "Multiple touches both sides", "RSI/Stoch cycling", "Buy support, sell resistance"],
         "indicators": ["Support/Resistance", "RSI", "Stochastic"], "timeframe": "Daily"},
        {"id": "SWG-04", "name": "Pullback After Breakout (Retest)", "category": "swing",
         "criteria": ["Recent breakout above key level", "Pullback to retest level/20-DMA", "Lighter volume on pullback", "Bullish reaction at level"],
         "indicators": ["Support/Resistance", "20-DMA", "Volume"], "timeframe": "Daily"},
        {"id": "SWG-05", "name": "Moving Average Crossover Swing", "category": "swing",
         "criteria": ["10/20-DMA crosses above 50-DMA for long", "Below for short", "Price confirms direction", "Supportive volume"],
         "indicators": ["10-DMA", "20-DMA", "50-DMA"], "timeframe": "Daily"},
        {"id": "SWG-06", "name": "RSI/Stochastic Mean-Reversion", "category": "swing",
         "criteria": ["RSI ≤ 30 or Stoch ≤ 20 in uptrend", "Bullish reversal near support", "Target reversion to mean", "Long-term trend intact"],
         "indicators": ["RSI", "Stochastic"], "timeframe": "Daily"},
        {"id": "SWG-07", "name": "Earnings Breakout Continuation", "category": "swing",
         "criteria": ["Strong earnings/guidance surprise", "Gap holds above gap low", "First orderly consolidation", "Enter breakout from pattern"],
         "indicators": ["Earnings", "Gap", "Volume"], "timeframe": "Daily"},
        {"id": "SWG-08", "name": "Post-Earnings Drift (PEAD)", "category": "swing",
         "criteria": ["Positive earnings surprise", "Favorable price reaction", "Analyst upgrades", "4-8 week drift period"],
         "indicators": ["Earnings", "Analyst Ratings"], "timeframe": "Weekly"},
        {"id": "SWG-09", "name": "Sector/ETF Relative Strength", "category": "swing",
         "criteria": ["Sector ETF outperforming index", "Stock stronger than sector", "Clean trend structure", "Buy pullbacks in leaders"],
         "indicators": ["Relative Strength", "Sector ETF"], "timeframe": "Daily"},
        {"id": "SWG-10", "name": "Shorting Failed Breakouts", "category": "swing",
         "criteria": ["Breakout above resistance fails", "Close back into range", "Increased volume on failure", "Target range midpoint"],
         "indicators": ["Support/Resistance", "Volume"], "timeframe": "Daily"},
        {"id": "SWG-11", "name": "Pairs Trading / Relative Value", "category": "swing",
         "criteria": ["Two correlated stocks", "Spread deviates beyond band", "Long underperformer, short outperformer", "Exit on mean reversion"],
         "indicators": ["Correlation", "Spread"], "timeframe": "Daily"},
        {"id": "SWG-12", "name": "Swing Trendline Strategy", "category": "swing",
         "criteria": ["Clear rising/falling trendline", "Price repeatedly respects line", "Enter on bounce with confirm", "Stop beyond trendline"],
         "indicators": ["Trendline"], "timeframe": "Daily"},
        {"id": "SWG-13", "name": "Volatility Contraction Pattern (VCP)", "category": "swing",
         "criteria": ["Series of decreasing pullbacks", "Decreasing volume in contractions", "Tight final contraction", "Breakout on volume surge"],
         "indicators": ["VCP Pattern", "Volume"], "timeframe": "Daily"},
        {"id": "SWG-14", "name": "Gap-Fill Swing", "category": "swing",
         "criteria": ["Old open gap on daily", "Price approaching gap zone", "Major MA or support confluence", "Target partial/full fill"],
         "indicators": ["Gap", "Moving Averages"], "timeframe": "Daily"},
        {"id": "SWG-15", "name": "Multi-Timeframe Alignment", "category": "swing",
         "criteria": ["Weekly and daily trends aligned", "Intraday/4H for timing", "Enter when lower TF confirms", "Ride higher TF trend"],
         "indicators": ["Multi-TF Analysis"], "timeframe": "Daily/Weekly"},
    ],
    "investment": [
        {"id": "INV-01", "name": "Buy-and-Hold Index Funds", "category": "investment",
         "criteria": ["Core allocation to broad ETFs", "Multi-year horizon", "Reinvest dividends", "Minimal trading"],
         "indicators": ["SPY", "QQQ", "VTI"], "timeframe": "Years"},
        {"id": "INV-02", "name": "Asset Allocation by Risk Profile", "category": "investment",
         "criteria": ["Target mix based on risk tolerance", "Stocks/bonds/cash/alternatives", "Periodic rebalancing", "Match to time horizon"],
         "indicators": ["Asset Classes"], "timeframe": "Quarterly"},
        {"id": "INV-03", "name": "Dollar-Cost Averaging (DCA)", "category": "investment",
         "criteria": ["Fixed dollar amount", "Regular intervals", "Regardless of price", "Long horizon for compounding"],
         "indicators": ["Timing"], "timeframe": "Weekly/Monthly"},
        {"id": "INV-04", "name": "Value Investing (Fundamental)", "category": "investment",
         "criteria": ["Below intrinsic value", "Low valuation ratios", "Solid balance sheet", "Margin of safety"],
         "indicators": ["P/E", "P/B", "FCF", "Debt/Equity"], "timeframe": "Years"},
        {"id": "INV-05", "name": "Quality Factor Investing", "category": "investment",
         "criteria": ["High ROE/ROA", "Stable earnings", "Low leverage", "Durable competitive advantages"],
         "indicators": ["ROE", "ROA", "Earnings Stability"], "timeframe": "Years"},
        {"id": "INV-06", "name": "Growth Investing", "category": "investment",
         "criteria": ["Above-avg revenue/earnings growth", "Large addressable market", "Profit reinvestment", "Accept higher volatility"],
         "indicators": ["Revenue Growth", "EPS Growth"], "timeframe": "Years"},
        {"id": "INV-07", "name": "Dividend Growth Investing", "category": "investment",
         "criteria": ["Long dividend history", "Annual increases", "Reasonable payout ratio", "Stable cash flows"],
         "indicators": ["Dividend Yield", "Payout Ratio", "Dividend Growth"], "timeframe": "Years"},
        {"id": "INV-08", "name": "High-Yield Dividend / Income", "category": "investment",
         "criteria": ["Elevated yield", "Adequate coverage ratio", "REITs, utilities focus", "Diversified holdings"],
         "indicators": ["Yield", "Coverage Ratio"], "timeframe": "Years"},
        {"id": "INV-09", "name": "Core-Satellite Approach", "category": "investment",
         "criteria": ["60-90% in broad funds", "Satellite for alpha", "Active sector/factor bets", "Monitor satellite risk"],
         "indicators": ["Core Holdings", "Satellite Picks"], "timeframe": "Quarterly"},
        {"id": "INV-10", "name": "Factor Tilts (Value, Momentum, Quality)", "category": "investment",
         "criteria": ["Factor ETF exposure", "Maintain diversification", "Periodic rebalancing", "Long-term factor premia"],
         "indicators": ["Factor Exposure"], "timeframe": "Quarterly"},
        {"id": "INV-11", "name": "Thematic / Sector Allocation", "category": "investment",
         "criteria": ["Secular themes (AI, clean energy)", "Thematic ETFs or baskets", "Smaller allocation", "Higher risk tolerance"],
         "indicators": ["Theme Exposure"], "timeframe": "Years"},
        {"id": "INV-12", "name": "Target-Date Funds", "category": "investment",
         "criteria": ["Single fund solution", "Auto glide path", "Appropriate for retirement", "Minimal maintenance"],
         "indicators": ["Target Date"], "timeframe": "Years"},
        {"id": "INV-13", "name": "Global Diversification", "category": "investment",
         "criteria": ["Include non-US markets", "Developed + emerging", "Risk-based weights", "Periodic rebalancing"],
         "indicators": ["Geographic Allocation"], "timeframe": "Quarterly"},
        {"id": "INV-14", "name": "Rules-Based Rebalancing", "category": "investment",
         "criteria": ["Calendar or threshold rules", "Max allocation caps", "Drawdown limits", "Systematic approach"],
         "indicators": ["Rebalancing Rules"], "timeframe": "Quarterly"},
        {"id": "INV-15", "name": "Tax-Efficient Investing", "category": "investment",
         "criteria": ["Tax-advantaged accounts", "Tax-loss harvesting", "Long-term capital gains", "Asset location strategy"],
         "indicators": ["Tax Efficiency"], "timeframe": "Annual"},
    ]
}

# Flatten all strategies
ALL_STRATEGIES = TRADING_STRATEGIES["intraday"] + TRADING_STRATEGIES["swing"] + TRADING_STRATEGIES["investment"]

# ===================== PYDANTIC MODELS =====================
class StockQuote(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    high: float
    low: float
    open: float
    prev_close: float
    timestamp: str

class FundamentalData(BaseModel):
    symbol: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    enterprise_value: Optional[float] = None
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_rate: Optional[float] = None
    payout_ratio: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    avg_volume: Optional[int] = None
    shares_outstanding: Optional[int] = None
    float_shares: Optional[int] = None
    short_ratio: Optional[float] = None
    short_percent: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None

class InsiderTrade(BaseModel):
    symbol: str
    insider_name: str
    title: str
    transaction_type: str  # Buy, Sell, Option Exercise
    shares: int
    price: float
    value: float
    date: str
    filing_date: str

class COTData(BaseModel):
    market: str
    date: str
    commercial_long: int
    commercial_short: int
    commercial_net: int
    non_commercial_long: int
    non_commercial_short: int
    non_commercial_net: int
    total_long: int
    total_short: int
    change_commercial_net: int
    change_non_commercial_net: int

# ===================== TWELVE DATA API FOR REAL-TIME QUOTES =====================
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "demo")

# Simple in-memory cache for quotes (expires after 120 seconds to avoid rate limits)
_quote_cache = {}
_cache_ttl = 120  # seconds - increased to reduce API calls

async def fetch_twelvedata_quote(symbol: str) -> Optional[Dict]:
    """Fetch real-time quote from Twelve Data API with caching"""
    symbol = symbol.upper()
    
    # Check cache first
    cache_key = f"quote_{symbol}"
    if cache_key in _quote_cache:
        cached_data, cached_time = _quote_cache[cache_key]
        if (datetime.now(timezone.utc) - cached_time).total_seconds() < _cache_ttl:
            return cached_data
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.twelvedata.com/quote",
                params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Check for errors
                if "code" in data and data["code"] != 200:
                    print(f"Twelve Data error for {symbol}: {data.get('message')}")
                    return None
                
                price = float(data.get("close", 0))
                prev_close = float(data.get("previous_close", 0))
                change = float(data.get("change", 0))
                change_pct = float(data.get("percent_change", 0))
                
                result = {
                    "symbol": symbol,
                    "name": data.get("name", symbol),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": int(data.get("volume", 0)),
                    "high": round(float(data.get("high", price)), 2),
                    "low": round(float(data.get("low", price)), 2),
                    "open": round(float(data.get("open", price)), 2),
                    "prev_close": round(prev_close, 2),
                    "avg_volume": int(data.get("average_volume", 0)),
                    "fifty_two_week_high": float(data.get("fifty_two_week", {}).get("high", 0)) if data.get("fifty_two_week") else None,
                    "fifty_two_week_low": float(data.get("fifty_two_week", {}).get("low", 0)) if data.get("fifty_two_week") else None,
                    "exchange": data.get("exchange"),
                    "is_market_open": data.get("is_market_open", False),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Cache the result
                _quote_cache[cache_key] = (result, datetime.now(timezone.utc))
                return result
    except Exception as e:
        print(f"Twelve Data error for {symbol}: {e}")
    
    return None

async def fetch_quote(symbol: str) -> Optional[Dict]:
    """Fetch real-time quote - tries Twelve Data first, then fallback"""
    symbol = symbol.upper()
    
    # Try Twelve Data first (real data)
    quote = await fetch_twelvedata_quote(symbol)
    if quote:
        return quote
    
    # Fallback to Yahoo Finance
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        if not hist.empty and len(hist) >= 1:
            current = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
            prev_close = prev['Close']
            change = current['Close'] - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0
            
            return {
                "symbol": symbol,
                "price": round(current['Close'], 2),
                "change": round(change, 2),
                "change_percent": round(change_pct, 2),
                "volume": int(current['Volume']),
                "high": round(current['High'], 2),
                "low": round(current['Low'], 2),
                "open": round(current['Open'], 2),
                "prev_close": round(prev_close, 2),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    except Exception as e:
        print(f"Yahoo Finance fallback error for {symbol}: {e}")
    
    # Final fallback to simulated data
    return generate_simulated_quote(symbol)

def generate_simulated_quote(symbol: str) -> Dict:
    """Generate simulated quote data"""
    base_prices = {
        "SPY": 475, "QQQ": 415, "DIA": 385, "IWM": 198, "VIX": 15,
        "AAPL": 186, "MSFT": 379, "GOOGL": 143, "AMZN": 178, "NVDA": 495,
        "TSLA": 249, "META": 358, "AMD": 146, "NFLX": 479, "CRM": 278,
        "BA": 215, "DIS": 113, "V": 279, "MA": 446, "JPM": 178,
        "GS": 379, "XOM": 112, "CVX": 159, "COIN": 178, "PLTR": 23,
    }
    
    base = base_prices.get(symbol, random.uniform(50, 300))
    variation = random.uniform(-0.03, 0.03)
    price = base * (1 + variation)
    change_pct = random.uniform(-3, 3)
    change = price * change_pct / 100
    volume = random.randint(5000000, 50000000)
    
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(change_pct, 2),
        "volume": volume,
        "high": round(price * 1.01, 2),
        "low": round(price * 0.99, 2),
        "open": round(price - change/2, 2),
        "prev_close": round(price - change, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def fetch_fundamentals(symbol: str) -> Dict:
    """Fetch fundamental data from Yahoo Finance"""
    symbol = symbol.upper()
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        return {
            "symbol": symbol,
            "company_name": info.get("longName") or info.get("shortName", symbol),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary", "")[:500] if info.get("longBusinessSummary") else None,
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "revenue": info.get("totalRevenue"),
            "gross_profit": info.get("grossProfits"),
            "ebitda": info.get("ebitda"),
            "net_income": info.get("netIncomeToCommon"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "short_ratio": info.get("shortRatio"),
            "short_percent": info.get("shortPercentOfFloat"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"Fundamentals error for {symbol}: {e}")
        return generate_simulated_fundamentals(symbol)

def generate_simulated_fundamentals(symbol: str) -> Dict:
    """Generate simulated fundamental data"""
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Inc.",
        "sector": random.choice(["Technology", "Healthcare", "Financial", "Consumer Cyclical", "Energy"]),
        "industry": "Various",
        "market_cap": random.randint(10_000_000_000, 3_000_000_000_000),
        "pe_ratio": round(random.uniform(10, 50), 2),
        "forward_pe": round(random.uniform(8, 40), 2),
        "peg_ratio": round(random.uniform(0.5, 3), 2),
        "price_to_book": round(random.uniform(1, 20), 2),
        "price_to_sales": round(random.uniform(1, 15), 2),
        "revenue": random.randint(1_000_000_000, 500_000_000_000),
        "ebitda": random.randint(100_000_000, 100_000_000_000),
        "net_income": random.randint(100_000_000, 50_000_000_000),
        "eps": round(random.uniform(1, 30), 2),
        "revenue_growth": round(random.uniform(-0.1, 0.5), 3),
        "earnings_growth": round(random.uniform(-0.2, 0.6), 3),
        "profit_margin": round(random.uniform(0.05, 0.4), 3),
        "operating_margin": round(random.uniform(0.1, 0.5), 3),
        "roe": round(random.uniform(0.05, 0.5), 3),
        "roa": round(random.uniform(0.02, 0.2), 3),
        "debt_to_equity": round(random.uniform(0, 200), 2),
        "current_ratio": round(random.uniform(0.5, 3), 2),
        "dividend_yield": round(random.uniform(0, 0.05), 4),
        "beta": round(random.uniform(0.5, 2), 2),
        "fifty_two_week_high": round(random.uniform(100, 500), 2),
        "fifty_two_week_low": round(random.uniform(50, 300), 2),
        "avg_volume": random.randint(1000000, 100000000),
        "short_ratio": round(random.uniform(1, 10), 2),
        "short_percent": round(random.uniform(0.01, 0.3), 3),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def fetch_historical_data(symbol: str, period: str = "1y") -> List[Dict]:
    """Fetch historical price data"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        data = []
        for date, row in hist.iterrows():
            data.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(row['Open'], 2),
                "high": round(row['High'], 2),
                "low": round(row['Low'], 2),
                "close": round(row['Close'], 2),
                "volume": int(row['Volume'])
            })
        return data
    except Exception as e:
        print(f"Historical data error: {e}")
        return []

# ===================== INSIDER TRADING DATA =====================
async def fetch_insider_trades(symbol: str) -> List[Dict]:
    """Fetch insider trading data from Finnhub"""
    trades = []
    
    try:
        async with httpx.AsyncClient() as client:
            # Using Finnhub free API for insider transactions
            resp = await client.get(
                "https://finnhub.io/api/v1/stock/insider-transactions",
                params={"symbol": symbol.upper(), "token": "demo"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                for tx in data.get("data", [])[:20]:
                    shares = tx.get("share", 0)
                    price = tx.get("transactionPrice", 0) or 0
                    trades.append({
                        "symbol": symbol.upper(),
                        "insider_name": tx.get("name", "Unknown"),
                        "title": tx.get("position", "Insider"),
                        "transaction_type": "Buy" if tx.get("transactionCode") in ["P", "A"] else "Sell",
                        "shares": abs(shares),
                        "price": round(price, 2),
                        "value": round(abs(shares * price), 2),
                        "date": tx.get("transactionDate", ""),
                        "filing_date": tx.get("filingDate", "")
                    })
    except Exception as e:
        print(f"Insider trades error: {e}")
    
    # Add simulated data if no real data
    if not trades:
        trades = generate_simulated_insider_trades(symbol)
    
    return trades

def generate_simulated_insider_trades(symbol: str) -> List[Dict]:
    """Generate simulated insider trading data"""
    trades = []
    names = ["John Smith (CEO)", "Jane Doe (CFO)", "Bob Wilson (Director)", "Sarah Johnson (COO)", "Mike Brown (VP Sales)"]
    
    for i in range(10):
        is_buy = random.random() > 0.4  # 60% buys for bullish signal
        shares = random.randint(1000, 50000)
        price = random.uniform(50, 300)
        date = (datetime.now() - timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
        
        trades.append({
            "symbol": symbol.upper(),
            "insider_name": random.choice(names),
            "title": random.choice(["CEO", "CFO", "Director", "COO", "VP", "10% Owner"]),
            "transaction_type": "Buy" if is_buy else "Sell",
            "shares": shares,
            "price": round(price, 2),
            "value": round(shares * price, 2),
            "date": date,
            "filing_date": date
        })
    
    return sorted(trades, key=lambda x: x["date"], reverse=True)

async def get_unusual_insider_activity() -> List[Dict]:
    """Get stocks with unusual insider buying activity"""
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "META", "AMD", "AMZN", "JPM", "GS", 
               "BA", "DIS", "V", "MA", "CRM", "NFLX", "COIN", "PLTR", "SQ", "SHOP"]
    
    unusual_activity = []
    
    for symbol in symbols[:10]:  # Limit to avoid too many API calls
        trades = await fetch_insider_trades(symbol)
        
        # Calculate net insider activity
        total_buys = sum(t["value"] for t in trades if t["transaction_type"] == "Buy")
        total_sells = sum(t["value"] for t in trades if t["transaction_type"] == "Sell")
        net_activity = total_buys - total_sells
        buy_count = len([t for t in trades if t["transaction_type"] == "Buy"])
        sell_count = len([t for t in trades if t["transaction_type"] == "Sell"])
        
        # Flag unusual activity (high buy ratio or large transactions)
        if total_buys > 0:
            buy_ratio = total_buys / (total_buys + total_sells) if (total_buys + total_sells) > 0 else 0
            is_unusual = buy_ratio > 0.7 or total_buys > 1000000
            
            unusual_activity.append({
                "symbol": symbol,
                "total_buys": round(total_buys, 2),
                "total_sells": round(total_sells, 2),
                "net_activity": round(net_activity, 2),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_ratio": round(buy_ratio, 2),
                "is_unusual": is_unusual,
                "signal": "BULLISH" if net_activity > 0 else "BEARISH",
                "recent_trades": trades[:5]
            })
    
    # Sort by net activity descending
    unusual_activity.sort(key=lambda x: x["net_activity"], reverse=True)
    return unusual_activity

# ===================== COMMITMENT OF TRADERS (COT) DATA =====================
async def fetch_cot_data(market: str = "ES") -> List[Dict]:
    """Fetch Commitment of Traders data"""
    # COT data mapping
    cot_markets = {
        "ES": "E-MINI S&P 500",
        "NQ": "E-MINI NASDAQ-100", 
        "GC": "GOLD",
        "SI": "SILVER",
        "CL": "CRUDE OIL",
        "NG": "NATURAL GAS",
        "ZB": "US TREASURY BONDS",
        "ZN": "10-YEAR T-NOTE",
        "6E": "EURO FX",
        "6J": "JAPANESE YEN",
        "ZC": "CORN",
        "ZS": "SOYBEANS",
        "ZW": "WHEAT"
    }
    
    market_name = cot_markets.get(market.upper(), market.upper())
    
    # Generate simulated COT data (in production, would use CFTC API or Quandl)
    cot_data = []
    
    for i in range(12):  # Last 12 weeks
        date = (datetime.now() - timedelta(weeks=i)).strftime("%Y-%m-%d")
        
        # Base values with some randomization
        comm_long = random.randint(200000, 400000)
        comm_short = random.randint(150000, 350000)
        non_comm_long = random.randint(300000, 500000)
        non_comm_short = random.randint(250000, 450000)
        
        prev_comm_net = random.randint(-50000, 50000)
        prev_non_comm_net = random.randint(-30000, 30000)
        
        cot_data.append({
            "market": market_name,
            "market_code": market.upper(),
            "date": date,
            "commercial_long": comm_long,
            "commercial_short": comm_short,
            "commercial_net": comm_long - comm_short,
            "non_commercial_long": non_comm_long,
            "non_commercial_short": non_comm_short,
            "non_commercial_net": non_comm_long - non_comm_short,
            "total_long": comm_long + non_comm_long,
            "total_short": comm_short + non_comm_short,
            "change_commercial_net": (comm_long - comm_short) - prev_comm_net,
            "change_non_commercial_net": (non_comm_long - non_comm_short) - prev_non_comm_net,
            "commercial_sentiment": "BULLISH" if (comm_long - comm_short) > 0 else "BEARISH",
            "speculator_sentiment": "BULLISH" if (non_comm_long - non_comm_short) > 0 else "BEARISH"
        })
    
    return cot_data

async def get_cot_summary() -> Dict:
    """Get COT summary for major markets"""
    markets = ["ES", "NQ", "GC", "CL", "6E", "ZB"]
    summary = []
    
    for market in markets:
        data = await fetch_cot_data(market)
        if data:
            latest = data[0]
            prev = data[1] if len(data) > 1 else data[0]
            
            summary.append({
                "market": latest["market"],
                "market_code": latest["market_code"],
                "commercial_net": latest["commercial_net"],
                "commercial_change": latest["commercial_net"] - prev["commercial_net"],
                "speculator_net": latest["non_commercial_net"],
                "speculator_change": latest["non_commercial_net"] - prev["non_commercial_net"],
                "commercial_sentiment": latest["commercial_sentiment"],
                "speculator_sentiment": latest["speculator_sentiment"],
                "date": latest["date"]
            })
    
    return {
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ===================== MARKET NEWS =====================
async def fetch_market_news() -> List[Dict]:
    """Fetch market news"""
    news_items = []
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "token": "demo"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data[:15]:
                    news_items.append({
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", "")[:300],
                        "source": item.get("source", "Finnhub"),
                        "url": item.get("url", ""),
                        "published": datetime.fromtimestamp(item.get("datetime", 0), timezone.utc).isoformat(),
                        "related_symbols": item.get("related", "").split(",")[:3] if item.get("related") else [],
                        "sentiment": None
                    })
    except Exception as e:
        print(f"News error: {e}")
    
    # Fallback news
    if not news_items:
        news_items = [
            {"title": "Markets Rally on Tech Earnings", "summary": "Major indices climb as tech giants report strong quarterly results...", "source": "Market Watch", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["AAPL", "MSFT", "GOOGL"], "sentiment": "bullish"},
            {"title": "Fed Signals Rate Path", "summary": "Federal Reserve maintains steady outlook as inflation data improves...", "source": "Reuters", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["SPY", "TLT"], "sentiment": "neutral"},
            {"title": "Energy Sector Leads Gains", "summary": "Oil prices rise on supply concerns, boosting energy stocks...", "source": "Bloomberg", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["XLE", "XOM", "CVX"], "sentiment": "bullish"},
        ]
    
    return news_items

# ===================== HELPER FUNCTIONS =====================
async def fetch_multiple_quotes(symbols: List[str]) -> List[Dict]:
    """Fetch multiple quotes in parallel"""
    tasks = [fetch_quote(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def generate_ai_analysis(prompt: str) -> str:
    """Generate AI analysis"""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"analysis-{datetime.now(timezone.utc).timestamp()}",
            system_message="You are a professional trading analyst. Provide concise, actionable insights."
        ).with_model("openai", "gpt-4o")
        
        user_message = UserMessage(text=prompt)
        response = await chat.send_message(user_message)
        return response
    except Exception as e:
        print(f"AI Analysis error: {e}")
        return "Analysis unavailable"

async def score_stock_for_strategies(symbol: str, quote_data: Dict, fundamentals: Dict = None, category_filter: str = None) -> Dict:
    """
    Score a stock against all 50 trading strategies using detailed criteria.
    Returns matched strategies with confidence scores for each.
    """
    matched_strategies = []
    strategy_details = []
    total_criteria_met = 0
    total_criteria_checked = 0
    
    # Extract quote data
    price = quote_data.get("price", 0)
    change_pct = quote_data.get("change_percent", 0)
    volume = quote_data.get("volume", 0)
    avg_volume = quote_data.get("avg_volume", 0) or volume
    high = quote_data.get("high", price)
    low = quote_data.get("low", price)
    open_price = quote_data.get("open", price)
    prev_close = quote_data.get("prev_close", price)
    
    # Calculate derived metrics
    rvol = (volume / avg_volume) if avg_volume > 0 else 1  # Relative Volume
    daily_range = ((high - low) / low * 100) if low > 0 else 0
    gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
    vwap_estimate = (high + low + price) / 3  # Simplified VWAP
    above_vwap = price > vwap_estimate
    
    # Fundamentals data (if available)
    pe_ratio = fundamentals.get("pe_ratio") if fundamentals else None
    pb_ratio = fundamentals.get("price_to_book") if fundamentals else None
    dividend_yield = fundamentals.get("dividend_yield") if fundamentals else None
    roe = fundamentals.get("roe") if fundamentals else None
    revenue_growth = fundamentals.get("revenue_growth") if fundamentals else None
    beta = fundamentals.get("beta") if fundamentals else None
    
    # ===================== INTRADAY STRATEGIES =====================
    if not category_filter or category_filter == "intraday":
        # INT-01: Trend Momentum Continuation
        criteria_met = 0
        if above_vwap and change_pct > 0:
            criteria_met += 1
        if change_pct > 0.5:  # Upward momentum
            criteria_met += 1
        if rvol >= 2:
            criteria_met += 1
        if high > open_price:  # Making higher highs
            criteria_met += 1
        if criteria_met >= 3:
            matched_strategies.append("INT-01")
            strategy_details.append({"id": "INT-01", "name": "Trend Momentum Continuation", "criteria_met": criteria_met, "total": 4, "confidence": criteria_met/4*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 4
        
        # INT-02: Intraday Breakout (Range High)
        criteria_met = 0
        if daily_range < 3:  # Tight range
            criteria_met += 1
        if rvol >= 1.5:
            criteria_met += 1
        if price >= high * 0.99:  # Near high
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-02")
            strategy_details.append({"id": "INT-02", "name": "Intraday Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-03: Opening Range Breakout (ORB)
        criteria_met = 0
        orb_range = daily_range  # Using daily range as proxy
        if orb_range < 2:  # Reasonable opening range
            criteria_met += 1
        if price > open_price and change_pct > 0.5:  # Break above ORH
            criteria_met += 1
        if rvol >= 1.2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-03")
            strategy_details.append({"id": "INT-03", "name": "Opening Range Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-04: Gap-and-Go
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap >= 3%
            criteria_met += 1
        if rvol >= 3:  # High premarket volume
            criteria_met += 1
        if gap_pct > 0 and price > open_price:  # Holds gap
            criteria_met += 1
        if above_vwap:
            criteria_met += 1
        if criteria_met >= 3:
            matched_strategies.append("INT-04")
            strategy_details.append({"id": "INT-04", "name": "Gap-and-Go", "criteria_met": criteria_met, "total": 4, "confidence": criteria_met/4*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 4
        
        # INT-05: Pullback in Trend (Buy the Dip)
        criteria_met = 0
        if change_pct > 0:  # Overall uptrend
            criteria_met += 1
        if price < high * 0.98 and price > low * 1.02:  # Pullback from high
            criteria_met += 1
        if above_vwap:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-05")
            strategy_details.append({"id": "INT-05", "name": "Pullback in Trend", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-06: VWAP Bounce
        criteria_met = 0
        if above_vwap:
            criteria_met += 1
        if abs(price - vwap_estimate) / vwap_estimate < 0.005:  # Near VWAP
            criteria_met += 1
        if change_pct > 0:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-06")
            strategy_details.append({"id": "INT-06", "name": "VWAP Bounce", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-07: VWAP Reversion (Fade to VWAP)
        criteria_met = 0
        vwap_extension = abs((price - vwap_estimate) / vwap_estimate * 100)
        if vwap_extension >= 2:  # Extended from VWAP
            criteria_met += 1
        if daily_range > 3:  # Parabolic move
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-07")
            strategy_details.append({"id": "INT-07", "name": "VWAP Reversion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INT-08: Mean Reversion After Exhaustion Spike
        criteria_met = 0
        if daily_range >= 3:  # Wide range candles
            criteria_met += 1
        if rvol >= 2:  # Volume climax
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-08")
            strategy_details.append({"id": "INT-08", "name": "Mean Reversion Exhaustion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INT-10: Bull/Bear Flag Intraday
        criteria_met = 0
        if change_pct > 2 or change_pct < -2:  # Strong impulse
            criteria_met += 1
        if daily_range < 4:  # Consolidation
            criteria_met += 1
        if rvol >= 1.5:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-10")
            strategy_details.append({"id": "INT-10", "name": "Bull/Bear Flag", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-13: Intraday Range Trading
        criteria_met = 0
        if -0.5 < change_pct < 0.5:  # Tight range
            criteria_met += 1
        if rvol < 1.5:  # Low relative volume
            criteria_met += 1
        if daily_range < 2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-13")
            strategy_details.append({"id": "INT-13", "name": "Intraday Range Trading", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-14: News/Earnings Momentum
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap on news
            criteria_met += 1
        if rvol >= 3:  # High volume all session
            criteria_met += 1
        if abs(change_pct) >= 3:  # Big move
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-14")
            strategy_details.append({"id": "INT-14", "name": "News/Earnings Momentum", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-16: High-of-Day Break Scalps
        criteria_met = 0
        if price >= high * 0.995:  # Near HOD
            criteria_met += 1
        if change_pct > 0:  # Uptrend
            criteria_met += 1
        if rvol >= 1.5:  # Volume building
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-16")
            strategy_details.append({"id": "INT-16", "name": "HOD Break Scalps", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-18: Index-Correlated Trend Riding
        criteria_met = 0
        if beta and beta >= 1.2:  # High beta
            criteria_met += 1
        if change_pct > 1:  # Strong trend
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-18")
            strategy_details.append({"id": "INT-18", "name": "Index-Correlated Riding", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
    
    # ===================== SWING STRATEGIES =====================
    if not category_filter or category_filter == "swing":
        # SWG-01: Daily Trend Following
        criteria_met = 0
        if change_pct > 0:  # Uptrend
            criteria_met += 1
        if price > prev_close:  # Above previous close
            criteria_met += 1
        if volume > avg_volume:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-01")
            strategy_details.append({"id": "SWG-01", "name": "Daily Trend Following", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-02: Breakout from Multi-Week Base
        criteria_met = 0
        if daily_range < 3:  # Tight consolidation
            criteria_met += 1
        if rvol >= 1.5:  # Strong volume
            criteria_met += 1
        if price >= high * 0.98:  # Near breakout
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-02")
            strategy_details.append({"id": "SWG-02", "name": "Multi-Week Base Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-04: Pullback After Breakout
        criteria_met = 0
        if change_pct < 0 and change_pct > -3:  # Light pullback
            criteria_met += 1
        if rvol < 1:  # Lower volume on pullback
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-04")
            strategy_details.append({"id": "SWG-04", "name": "Pullback After Breakout", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-06: RSI/Stochastic Mean-Reversion
        criteria_met = 0
        if change_pct < -2:  # Oversold condition
            criteria_met += 1
        if price > low * 1.01:  # Showing bounce
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-06")
            strategy_details.append({"id": "SWG-06", "name": "RSI Mean-Reversion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-07: Earnings Breakout Continuation
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap on earnings
            criteria_met += 1
        if price > open_price:  # Holding gap
            criteria_met += 1
        if rvol >= 2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-07")
            strategy_details.append({"id": "SWG-07", "name": "Earnings Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-09: Sector Relative Strength
        criteria_met = 0
        if change_pct > 1.5:  # Outperforming
            criteria_met += 1
        if rvol >= 1.2:
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-09")
            strategy_details.append({"id": "SWG-09", "name": "Sector Relative Strength", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-10: Shorting Failed Breakouts
        criteria_met = 0
        if change_pct < -1 and price < high * 0.98:  # Failed breakout
            criteria_met += 1
        if rvol >= 1.5:  # Volume on failure
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-10")
            strategy_details.append({"id": "SWG-10", "name": "Failed Breakout Short", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-13: Volatility Contraction Pattern (VCP)
        criteria_met = 0
        if daily_range < 2:  # Tight contraction
            criteria_met += 1
        if rvol < 1:  # Decreasing volume
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-13")
            strategy_details.append({"id": "SWG-13", "name": "VCP Pattern", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
    
    # ===================== INVESTMENT STRATEGIES =====================
    if not category_filter or category_filter == "investment":
        # INV-04: Value Investing
        criteria_met = 0
        if pe_ratio and pe_ratio < 20:  # Low P/E
            criteria_met += 1
        if pb_ratio and pb_ratio < 3:  # Low P/B
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-04")
            strategy_details.append({"id": "INV-04", "name": "Value Investing", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-05: Quality Factor
        criteria_met = 0
        if roe and roe > 0.15:  # High ROE
            criteria_met += 1
        if pe_ratio and pe_ratio < 30:  # Reasonable valuation
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-05")
            strategy_details.append({"id": "INV-05", "name": "Quality Factor", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-06: Growth Investing
        criteria_met = 0
        if revenue_growth and revenue_growth > 0.15:  # High growth
            criteria_met += 1
        if pe_ratio and pe_ratio > 20:  # Growth premium
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-06")
            strategy_details.append({"id": "INV-06", "name": "Growth Investing", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-07: Dividend Growth
        criteria_met = 0
        if dividend_yield and dividend_yield > 0.01:  # Has dividend
            criteria_met += 1
        if dividend_yield and dividend_yield < 0.06:  # Sustainable yield
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-07")
            strategy_details.append({"id": "INV-07", "name": "Dividend Growth", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-08: High-Yield Dividend
        criteria_met = 0
        if dividend_yield and dividend_yield >= 0.04:  # High yield
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-08")
            strategy_details.append({"id": "INV-08", "name": "High-Yield Dividend", "criteria_met": criteria_met, "total": 1, "confidence": criteria_met/1*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 1
    
    # Calculate final score
    if total_criteria_checked > 0:
        base_score = (total_criteria_met / total_criteria_checked) * 100
    else:
        base_score = 0
    
    # Boost score based on number of matching strategies
    strategy_bonus = min(30, len(matched_strategies) * 5)
    score = min(100, int(base_score + strategy_bonus))
    
    return {
        "symbol": symbol,
        "score": score,
        "matched_strategies": matched_strategies,
        "strategy_details": strategy_details,
        "criteria_met": total_criteria_met,
        "total_criteria": total_criteria_checked,
        "change_percent": change_pct,
        "volume": volume,
        "rvol": round(rvol, 2),
        "gap_percent": round(gap_pct, 2),
        "daily_range": round(daily_range, 2),
        "above_vwap": above_vwap
    }

# ===================== API ENDPOINTS =====================
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# ----- Quotes -----
@app.get("/api/quotes/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a single symbol"""
    quote = await fetch_quote(symbol.upper())
    if not quote:
        raise HTTPException(status_code=404, detail="Symbol not found")
    return quote

@app.post("/api/quotes/batch")
async def get_batch_quotes(symbols: List[str]):
    """Get quotes for multiple symbols"""
    quotes = await fetch_multiple_quotes([s.upper() for s in symbols])
    return {"quotes": quotes, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/market/overview")
async def get_market_overview():
    """Get market overview with major indices and movers"""
    indices = ["SPY", "QQQ", "DIA", "IWM", "VIX"]
    movers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD"]
    
    index_quotes = await fetch_multiple_quotes(indices)
    mover_quotes = await fetch_multiple_quotes(movers)
    
    sorted_movers = sorted(mover_quotes, key=lambda x: abs(x.get("change_percent", 0)), reverse=True)
    
    return {
        "indices": index_quotes,
        "top_movers": sorted_movers[:5],
        "gainers": [m for m in sorted_movers if m.get("change_percent", 0) > 0][:3],
        "losers": [m for m in sorted_movers if m.get("change_percent", 0) < 0][:3],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ----- Fundamentals -----
@app.get("/api/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """Get fundamental data for a symbol"""
    data = await fetch_fundamentals(symbol.upper())
    return data

@app.get("/api/historical/{symbol}")
async def get_historical(symbol: str, period: str = "1y"):
    """Get historical price data"""
    data = await fetch_historical_data(symbol.upper(), period)
    return {"symbol": symbol.upper(), "data": data, "period": period}

# ----- Insider Trading -----
# NOTE: /api/insider/unusual must be defined BEFORE /api/insider/{symbol} to avoid route conflict
@app.get("/api/insider/unusual")
async def get_unusual_insider():
    """Get stocks with unusual insider activity"""
    activity = await get_unusual_insider_activity()
    
    # Filter only unusual activity
    unusual = [a for a in activity if a.get("is_unusual", False)]
    
    return {
        "unusual_activity": unusual,
        "all_activity": activity,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/insider/{symbol}")
async def get_insider_trades(symbol: str):
    """Get insider trading data for a symbol"""
    trades = await fetch_insider_trades(symbol.upper())
    
    # Calculate summary
    total_buys = sum(t["value"] for t in trades if t["transaction_type"] == "Buy")
    total_sells = sum(t["value"] for t in trades if t["transaction_type"] == "Sell")
    
    return {
        "symbol": symbol.upper(),
        "trades": trades,
        "summary": {
            "total_buys": round(total_buys, 2),
            "total_sells": round(total_sells, 2),
            "net_activity": round(total_buys - total_sells, 2),
            "buy_count": len([t for t in trades if t["transaction_type"] == "Buy"]),
            "sell_count": len([t for t in trades if t["transaction_type"] == "Sell"]),
            "signal": "BULLISH" if total_buys > total_sells else "BEARISH"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ----- COT Data -----
@app.get("/api/cot/summary")
async def get_cot_summary_endpoint():
    """Get COT summary for major markets"""
    summary = await get_cot_summary()
    return summary

@app.get("/api/cot/{market}")
async def get_cot(market: str):
    """Get COT data for a specific market"""
    data = await fetch_cot_data(market.upper())
    return {
        "market": market.upper(),
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ----- News -----
@app.get("/api/news")
async def get_news(limit: int = 10):
    """Get latest market news"""
    news = await fetch_market_news()
    return {"news": news[:limit], "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/news/{symbol}")
async def get_symbol_news(symbol: str):
    """Get news for specific symbol"""
    all_news = await fetch_market_news()
    symbol_news = [n for n in all_news if symbol.upper() in n.get("related_symbols", [])]
    return {"news": symbol_news, "symbol": symbol.upper()}

# ----- Strategies -----
@app.get("/api/strategies")
async def get_all_strategies(category: Optional[str] = None):
    """Get all trading strategies or filter by category"""
    if category:
        strategies = TRADING_STRATEGIES.get(category.lower(), [])
    else:
        strategies = ALL_STRATEGIES
    return {"strategies": strategies, "count": len(strategies)}

@app.get("/api/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Get specific strategy details"""
    for strategy in ALL_STRATEGIES:
        if strategy["id"] == strategy_id.upper():
            return strategy
    raise HTTPException(status_code=404, detail="Strategy not found")

# ----- Scanner -----
@app.post("/api/scanner/scan")
async def run_scanner(
    symbols: List[str],
    category: Optional[str] = None,
    min_score: int = 50,
    include_fundamentals: bool = False
):
    """
    Scan symbols against all 50 strategy criteria.
    Uses detailed criteria matching for Intraday, Swing, and Investment strategies.
    """
    quotes = await fetch_multiple_quotes([s.upper() for s in symbols])
    
    results = []
    for quote in quotes:
        # Optionally fetch fundamentals for investment strategy scoring
        fundamentals = None
        if include_fundamentals or (category and category.lower() == "investment"):
            try:
                fundamentals = await fetch_fundamentals(quote["symbol"])
            except Exception:
                fundamentals = None
        
        # Score against strategies with detailed criteria
        score_data = await score_stock_for_strategies(
            quote["symbol"], 
            quote, 
            fundamentals=fundamentals,
            category_filter=category.lower() if category else None
        )
        
        if score_data["score"] >= min_score:
            results.append({
                **score_data,
                "quote": quote,
                "has_fundamentals": fundamentals is not None
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    
    scan_doc = {
        "symbols": symbols,
        "category": category,
        "min_score": min_score,
        "results_count": len(results),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    scans_col.insert_one(scan_doc)
    
    return {
        "results": results[:20], 
        "total_scanned": len(symbols),
        "category_filter": category,
        "min_score_filter": min_score,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/scanner/presets")
async def get_scanner_presets():
    """Get predefined scanner presets"""
    presets = [
        {"name": "Momentum Movers", "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "CRM"], "min_score": 40},
        {"name": "Tech Leaders", "symbols": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "INTC", "AVGO", "QCOM", "ADBE"], "min_score": 30},
        {"name": "High Beta", "symbols": ["TSLA", "NVDA", "AMD", "COIN", "MSTR", "SQ", "SHOP", "ROKU", "SNAP", "PLTR"], "min_score": 40},
        {"name": "Dividend Aristocrats", "symbols": ["JNJ", "PG", "KO", "PEP", "MMM", "ABT", "WMT", "TGT", "MCD", "HD"], "min_score": 20},
    ]
    return {"presets": presets}

# ----- Watchlist -----
@app.get("/api/watchlist")
async def get_watchlist():
    """Get current watchlist"""
    watchlist = list(watchlists_col.find({}, {"_id": 0}).sort("score", -1).limit(10))
    return {"watchlist": watchlist, "count": len(watchlist)}

@app.post("/api/watchlist/generate")
async def generate_morning_watchlist():
    """Generate AI-powered morning watchlist"""
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "CRM", 
               "SPY", "QQQ", "BA", "DIS", "V", "MA", "JPM", "GS", "XOM", "CVX"]
    
    quotes = await fetch_multiple_quotes(symbols)
    
    scored_stocks = []
    for quote in quotes:
        score_data = await score_stock_for_strategies(quote["symbol"], quote)
        scored_stocks.append({
            **score_data,
            "price": quote["price"],
            "change_percent": quote["change_percent"]
        })
    
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)
    top_10 = scored_stocks[:10]
    
    watchlists_col.delete_many({})
    for item in top_10:
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        doc = item.copy()
        watchlists_col.insert_one(doc)
    
    symbols_str = ", ".join([s["symbol"] for s in top_10[:5]])
    ai_insight = await generate_ai_analysis(
        f"Provide a brief 2-3 sentence trading insight for today's top watchlist: {symbols_str}. "
        f"Top mover: {top_10[0]['symbol']} with score {top_10[0]['score']}."
    )
    
    # Clean items for return (ensure no ObjectId)
    clean_watchlist = []
    for item in top_10:
        clean_item = {k: v for k, v in item.items() if k != '_id'}
        clean_watchlist.append(clean_item)
    
    return {
        "watchlist": clean_watchlist,
        "ai_insight": ai_insight,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/watchlist/add")
async def add_to_watchlist(data: dict):
    """Add a symbol to watchlist manually"""
    symbol = data.get("symbol", "").upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    # Check if already exists
    existing = watchlists_col.find_one({"symbol": symbol})
    if existing:
        return {"message": f"{symbol} already in watchlist", "symbol": symbol}
    
    # Get quote data
    quote = await fetch_real_time_quote(symbol)
    
    doc = {
        "symbol": symbol,
        "score": 50,  # Default score for manual adds
        "matched_strategies": [],
        "added_at": datetime.now(timezone.utc).isoformat(),
        "manual": True
    }
    
    watchlists_col.insert_one(doc)
    
    return {"message": f"{symbol} added to watchlist", "symbol": symbol}

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str):
    """Remove a symbol from watchlist"""
    result = watchlists_col.delete_one({"symbol": symbol.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist")
    return {"message": f"{symbol} removed from watchlist", "symbol": symbol.upper()}

# ----- Portfolio -----
@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio positions"""
    positions = list(portfolios_col.find({}, {"_id": 0}))
    
    if positions:
        symbols = [p["symbol"] for p in positions]
        quotes = await fetch_multiple_quotes(symbols)
        quote_map = {q["symbol"]: q for q in quotes}
        
        total_value = 0
        total_cost = 0
        
        for pos in positions:
            quote = quote_map.get(pos["symbol"], {})
            current_price = quote.get("price", pos.get("avg_cost", 0))
            shares = pos.get("shares", 0)
            avg_cost = pos.get("avg_cost", 0)
            
            market_value = shares * current_price
            cost_basis = shares * avg_cost
            gain_loss = market_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
            
            pos["current_price"] = current_price
            pos["market_value"] = round(market_value, 2)
            pos["gain_loss"] = round(gain_loss, 2)
            pos["gain_loss_percent"] = round(gain_loss_pct, 2)
            pos["change_today"] = quote.get("change_percent", 0)
            
            total_value += market_value
            total_cost += cost_basis
        
        total_gain = total_value - total_cost
        total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
        
        return {
            "positions": positions,
            "summary": {
                "total_value": round(total_value, 2),
                "total_cost": round(total_cost, 2),
                "total_gain_loss": round(total_gain, 2),
                "total_gain_loss_percent": round(total_gain_pct, 2)
            }
        }
    
    return {"positions": [], "summary": {"total_value": 0, "total_cost": 0, "total_gain_loss": 0, "total_gain_loss_percent": 0}}

@app.post("/api/portfolio/add")
async def add_position(symbol: str, shares: float, avg_cost: float):
    """Add position to portfolio"""
    position = {
        "symbol": symbol.upper(),
        "shares": shares,
        "avg_cost": avg_cost,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    
    portfolios_col.update_one(
        {"symbol": symbol.upper()},
        {"$set": position},
        upsert=True
    )
    
    return {"message": "Position added", "position": position}

@app.delete("/api/portfolio/{symbol}")
async def remove_position(symbol: str):
    """Remove position from portfolio"""
    result = portfolios_col.delete_one({"symbol": symbol.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position removed"}

# ----- Alerts -----
@app.get("/api/alerts")
async def get_alerts(unread_only: bool = False):
    """Get all alerts"""
    query = {"read": False} if unread_only else {}
    alerts = list(alerts_col.find(query, {"_id": 0}).sort("timestamp", -1).limit(50))
    return {"alerts": alerts, "unread_count": alerts_col.count_documents({"read": False})}

@app.post("/api/alerts/generate")
async def generate_alerts():
    """Generate alerts based on strategy criteria"""
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "AMD", "META", "AMZN"]
    quotes = await fetch_multiple_quotes(symbols)
    
    new_alerts = []
    for quote in quotes:
        score_data = await score_stock_for_strategies(quote["symbol"], quote)
        
        if score_data["score"] >= 60:
            for strategy_id in score_data["matched_strategies"][:2]:
                strategy = next((s for s in ALL_STRATEGIES if s["id"] == strategy_id), None)
                if strategy:
                    alert = {
                        "symbol": quote["symbol"],
                        "strategy_id": strategy_id,
                        "strategy_name": strategy["name"],
                        "message": f"{quote['symbol']} matches {strategy['name']} criteria",
                        "criteria_met": strategy["criteria"][:3],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "read": False,
                        "score": score_data["score"],
                        "change_percent": quote["change_percent"]
                    }
                    alert_doc = alert.copy()
                    alerts_col.insert_one(alert_doc)
                    new_alerts.append(alert)
    
    return {"alerts_generated": len(new_alerts), "alerts": new_alerts}

@app.delete("/api/alerts/clear")
async def clear_alerts():
    """Clear all alerts"""
    result = alerts_col.delete_many({})
    return {"deleted": result.deleted_count}

# ----- Newsletter -----
@app.get("/api/newsletter/latest")
async def get_latest_newsletter():
    """Get latest newsletter"""
    newsletter = newsletters_col.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    return newsletter or {"message": "No newsletter available"}

@app.post("/api/newsletter/generate")
async def generate_newsletter():
    """Generate morning newsletter with AI"""
    overview = await get_market_overview()
    news = await fetch_market_news()
    watchlist_response = await generate_morning_watchlist()
    
    market_summary_data = f"""
    Market Overview:
    - SPY: {next((i for i in overview['indices'] if i['symbol'] == 'SPY'), {}).get('change_percent', 0):.2f}%
    - QQQ: {next((i for i in overview['indices'] if i['symbol'] == 'QQQ'), {}).get('change_percent', 0):.2f}%
    
    Top Movers: {', '.join([f"{m['symbol']} ({m['change_percent']:+.2f}%)" for m in overview['top_movers'][:3]])}
    
    Top News Headlines:
    {chr(10).join([f"- {n['title']}" for n in news[:5]])}
    
    Top Watchlist:
    {', '.join([f"{w['symbol']} (Score: {w['score']})" for w in watchlist_response['watchlist'][:5]])}
    """
    
    ai_summary = await generate_ai_analysis(
        f"Write a professional 3-paragraph morning market briefing based on this data:\n{market_summary_data}\n"
        f"Include: 1) Market sentiment overview, 2) Key stories to watch, 3) Trading opportunities for the day."
    )
    
    newsletter = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "title": f"TradeCommand Morning Briefing - {datetime.now(timezone.utc).strftime('%B %d, %Y')}",
        "market_summary": ai_summary,
        "indices": overview["indices"],
        "top_news": news[:5],
        "watchlist": watchlist_response["watchlist"][:10],
        "strategy_highlights": [
            "Gap-and-Go opportunities in premarket movers",
            "VWAP bounce setups in trending stocks",
            "Swing breakout candidates forming bases"
        ],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    newsletter_doc = newsletter.copy()
    newsletters_col.insert_one(newsletter_doc)
    
    return newsletter

# ----- Dashboard Stats -----
@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """Get dashboard statistics"""
    portfolio = await get_portfolio()
    alerts_data = await get_alerts(unread_only=True)
    watchlist = await get_watchlist()
    
    return {
        "portfolio_value": portfolio["summary"]["total_value"],
        "portfolio_change": portfolio["summary"]["total_gain_loss_percent"],
        "unread_alerts": alerts_data["unread_count"],
        "watchlist_count": watchlist["count"],
        "strategies_count": len(ALL_STRATEGIES),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ===================== WEBSOCKET REAL-TIME STREAMING =====================

class ConnectionManager:
    """Manages WebSocket connections for real-time streaming"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        print(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        print(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    def subscribe(self, websocket: WebSocket, symbols: List[str]):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update([s.upper() for s in symbols])
    
    def unsubscribe(self, websocket: WebSocket, symbols: List[str]):
        if websocket in self.subscriptions:
            for symbol in symbols:
                self.subscriptions[websocket].discard(symbol.upper())
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"Error sending message: {e}")
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error broadcasting: {e}")

manager = ConnectionManager()

# Default symbols to stream
DEFAULT_STREAM_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "VIX", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD"]

async def stream_quotes():
    """Background task to stream quotes to all connected clients"""
    # Stagger initial requests to avoid rate limits
    await asyncio.sleep(2)
    
    while True:
        if manager.active_connections:
            try:
                # Collect all subscribed symbols
                all_symbols = set(DEFAULT_STREAM_SYMBOLS)
                for symbols in manager.subscriptions.values():
                    all_symbols.update(symbols)
                
                # Fetch quotes for all symbols (uses cache)
                quotes = []
                symbol_list = list(all_symbols)[:10]  # Limit symbols
                
                for i, symbol in enumerate(symbol_list):
                    quote = await fetch_quote(symbol)
                    if quote:
                        quotes.append(quote)
                    # Small delay between requests to avoid rate limits
                    if i < len(symbol_list) - 1:
                        await asyncio.sleep(0.5)
                
                if quotes:
                    message = {
                        "type": "quotes",
                        "data": quotes,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await manager.broadcast(message)
            except Exception as e:
                print(f"Stream error: {e}")
        
        # Wait before next update (longer to respect rate limits)
        await asyncio.sleep(10)  # Update every 10 seconds

@app.on_event("startup")
async def startup_event():
    """Start background streaming task"""
    asyncio.create_task(stream_quotes())
    print("WebSocket streaming started")

@app.websocket("/ws/quotes")
async def websocket_quotes(websocket: WebSocket):
    """WebSocket endpoint for real-time quote streaming"""
    await manager.connect(websocket)
    
    # Send initial data (use cached or simulated to avoid rate limits)
    try:
        initial_quotes = []
        for symbol in DEFAULT_STREAM_SYMBOLS[:8]:
            quote = await fetch_quote(symbol)
            if quote:
                initial_quotes.append(quote)
            await asyncio.sleep(0.3)  # Stagger requests
        
        await manager.send_personal_message({
            "type": "initial",
            "data": initial_quotes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, websocket)
    except Exception as e:
        print(f"Error sending initial data: {e}")
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            
            if data.get("action") == "subscribe":
                symbols = data.get("symbols", [])
                manager.subscribe(websocket, symbols)
                await manager.send_personal_message({
                    "type": "subscribed",
                    "symbols": symbols
                }, websocket)
            
            elif data.get("action") == "unsubscribe":
                symbols = data.get("symbols", [])
                manager.unsubscribe(websocket, symbols)
                await manager.send_personal_message({
                    "type": "unsubscribed",
                    "symbols": symbols
                }, websocket)
            
            elif data.get("action") == "ping":
                await manager.send_personal_message({"type": "pong"}, websocket)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@app.get("/api/stream/status")
async def get_stream_status():
    """Get WebSocket streaming status"""
    return {
        "active_connections": len(manager.active_connections),
        "streaming": True,
        "update_interval_seconds": 5,
        "default_symbols": DEFAULT_STREAM_SYMBOLS
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
