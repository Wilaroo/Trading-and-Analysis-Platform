"""
TradeCommand - Trading and Analysis Platform Backend
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
import httpx
import asyncio
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

class NewsItem(BaseModel):
    title: str
    summary: str
    source: str
    url: str
    published: str
    related_symbols: List[str] = []
    sentiment: Optional[str] = None

class WatchlistItem(BaseModel):
    symbol: str
    score: float
    matched_strategies: List[str]
    criteria_met: int
    total_criteria: int
    notes: Optional[str] = None

class Alert(BaseModel):
    symbol: str
    strategy_id: str
    strategy_name: str
    message: str
    criteria_met: List[str]
    timestamp: str
    read: bool = False

class PortfolioPosition(BaseModel):
    symbol: str
    shares: float
    avg_cost: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    gain_loss: Optional[float] = None
    gain_loss_percent: Optional[float] = None

class Newsletter(BaseModel):
    date: str
    title: str
    market_summary: str
    top_news: List[Dict[str, Any]]
    watchlist: List[Dict[str, Any]]
    strategy_highlights: List[str]
    created_at: str

# ===================== DATA FETCHING =====================
import random

# Sample stock data for demo mode
SAMPLE_STOCK_DATA = {
    "SPY": {"price": 475.32, "prev": 472.15},
    "QQQ": {"price": 415.67, "prev": 412.34},
    "DIA": {"price": 385.45, "prev": 383.21},
    "IWM": {"price": 198.34, "prev": 197.12},
    "VIX": {"price": 15.23, "prev": 16.45},
    "AAPL": {"price": 185.92, "prev": 183.45},
    "MSFT": {"price": 378.91, "prev": 375.23},
    "GOOGL": {"price": 142.56, "prev": 140.89},
    "AMZN": {"price": 178.34, "prev": 176.12},
    "NVDA": {"price": 495.22, "prev": 487.56},
    "TSLA": {"price": 248.67, "prev": 242.34},
    "META": {"price": 358.45, "prev": 354.12},
    "AMD": {"price": 145.78, "prev": 142.34},
    "NFLX": {"price": 478.90, "prev": 472.34},
    "CRM": {"price": 278.45, "prev": 275.67},
    "BA": {"price": 215.34, "prev": 212.45},
    "DIS": {"price": 112.67, "prev": 111.23},
    "V": {"price": 278.90, "prev": 276.45},
    "MA": {"price": 445.67, "prev": 442.12},
    "JPM": {"price": 178.45, "prev": 175.89},
    "GS": {"price": 378.90, "prev": 374.56},
    "XOM": {"price": 112.34, "prev": 110.67},
    "CVX": {"price": 158.90, "prev": 156.45},
    "COIN": {"price": 178.45, "prev": 172.34},
    "MSTR": {"price": 445.67, "prev": 432.12},
    "SQ": {"price": 78.90, "prev": 76.45},
    "SHOP": {"price": 68.45, "prev": 66.78},
    "ROKU": {"price": 72.34, "prev": 70.12},
    "SNAP": {"price": 12.45, "prev": 12.12},
    "PLTR": {"price": 22.78, "prev": 21.89},
    "JNJ": {"price": 158.90, "prev": 157.45},
    "PG": {"price": 168.45, "prev": 167.12},
    "KO": {"price": 62.34, "prev": 61.89},
    "PEP": {"price": 178.90, "prev": 177.45},
    "MMM": {"price": 98.45, "prev": 97.23},
    "ABT": {"price": 112.67, "prev": 111.45},
    "WMT": {"price": 168.90, "prev": 167.34},
    "TGT": {"price": 145.67, "prev": 143.89},
    "MCD": {"price": 298.45, "prev": 295.67},
    "HD": {"price": 358.90, "prev": 355.45},
    "INTC": {"price": 42.67, "prev": 41.89},
    "AVGO": {"price": 112.45, "prev": 110.23},
    "QCOM": {"price": 168.90, "prev": 166.45},
    "ADBE": {"price": 548.67, "prev": 542.34},
}

async def fetch_yahoo_quote(symbol: str) -> Optional[Dict]:
    """Fetch quote - uses sample data for demo mode"""
    symbol = symbol.upper()
    
    # First try yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        
        if not hist.empty:
            current = hist.iloc[-1]
            info = ticker.fast_info
            prev_close = info.get('previousClose', current['Close'])
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
        print(f"yfinance error for {symbol}: {e}")
    
    # Fallback to sample data
    if symbol in SAMPLE_STOCK_DATA:
        data = SAMPLE_STOCK_DATA[symbol]
        # Add some randomness for demo
        variation = random.uniform(-0.02, 0.02)
        price = data["price"] * (1 + variation)
        prev = data["prev"]
        change = price - prev
        change_pct = (change / prev) * 100
        volume = random.randint(5000000, 50000000)
        
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": volume,
            "high": round(price * 1.01, 2),
            "low": round(price * 0.99, 2),
            "open": round(prev * 1.001, 2),
            "prev_close": round(prev, 2),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # Generate generic sample data for unknown symbols
    base_price = random.uniform(50, 300)
    change_pct = random.uniform(-5, 5)
    change = base_price * change_pct / 100
    
    return {
        "symbol": symbol,
        "price": round(base_price, 2),
        "change": round(change, 2),
        "change_percent": round(change_pct, 2),
        "volume": random.randint(1000000, 20000000),
        "high": round(base_price * 1.02, 2),
        "low": round(base_price * 0.98, 2),
        "open": round(base_price - change/2, 2),
        "prev_close": round(base_price - change, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def fetch_multiple_quotes(symbols: List[str]) -> List[Dict]:
    """Fetch multiple quotes in parallel"""
    tasks = [fetch_yahoo_quote(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def fetch_market_news() -> List[Dict]:
    """Fetch market news from multiple sources"""
    news_items = []
    
    # Try Finnhub for general market news
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
        print(f"Error fetching news: {e}")
    
    # Fallback sample news if API fails
    if not news_items:
        news_items = [
            {"title": "Markets Rally on Tech Earnings", "summary": "Major indices climb as tech giants report strong quarterly results...", "source": "Market Watch", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["AAPL", "MSFT", "GOOGL"], "sentiment": "bullish"},
            {"title": "Fed Signals Rate Path", "summary": "Federal Reserve maintains steady outlook as inflation data improves...", "source": "Reuters", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["SPY", "TLT"], "sentiment": "neutral"},
            {"title": "Energy Sector Leads Gains", "summary": "Oil prices rise on supply concerns, boosting energy stocks...", "source": "Bloomberg", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["XLE", "XOM", "CVX"], "sentiment": "bullish"},
        ]
    
    return news_items

# ===================== AI ANALYSIS =====================
async def generate_ai_analysis(prompt: str) -> str:
    """Generate AI analysis using Emergent LLM"""
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

async def score_stock_for_strategies(symbol: str, quote_data: Dict) -> Dict:
    """Score a stock against trading strategies"""
    matched_strategies = []
    total_criteria_met = 0
    
    # Simplified scoring based on available data
    price = quote_data.get("price", 0)
    change_pct = quote_data.get("change_percent", 0)
    volume = quote_data.get("volume", 0)
    
    # Momentum check (simplified)
    if change_pct > 2:
        matched_strategies.append("INT-01")  # Trend Momentum
        matched_strategies.append("INT-04")  # Gap-and-Go
        total_criteria_met += 2
    
    if change_pct > 3:
        matched_strategies.append("INT-14")  # News Momentum
        total_criteria_met += 1
    
    if -0.5 < change_pct < 0.5:
        matched_strategies.append("INT-13")  # Range Trading
        total_criteria_met += 1
    
    if change_pct < -2:
        matched_strategies.append("SWG-06")  # Mean Reversion
        total_criteria_met += 1
    
    # Volume check (assuming high volume is > 1M)
    if volume > 1000000:
        total_criteria_met += 1
    
    score = min(100, (len(matched_strategies) * 15) + (total_criteria_met * 5))
    
    return {
        "symbol": symbol,
        "score": score,
        "matched_strategies": matched_strategies,
        "criteria_met": total_criteria_met,
        "total_criteria": 10,
        "change_percent": change_pct,
        "volume": volume
    }

# ===================== API ENDPOINTS =====================
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# ----- Quotes -----
@app.get("/api/quotes/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a single symbol"""
    quote = await fetch_yahoo_quote(symbol.upper())
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
    
    # Sort movers by change percent
    sorted_movers = sorted(mover_quotes, key=lambda x: abs(x.get("change_percent", 0)), reverse=True)
    
    return {
        "indices": index_quotes,
        "top_movers": sorted_movers[:5],
        "gainers": [m for m in sorted_movers if m.get("change_percent", 0) > 0][:3],
        "losers": [m for m in sorted_movers if m.get("change_percent", 0) < 0][:3],
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
    min_score: int = 50
):
    """Scan symbols against strategy criteria"""
    quotes = await fetch_multiple_quotes([s.upper() for s in symbols])
    
    results = []
    for quote in quotes:
        score_data = await score_stock_for_strategies(quote["symbol"], quote)
        if score_data["score"] >= min_score:
            results.append({
                **score_data,
                "quote": quote
            })
    
    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # Store scan results
    scan_doc = {
        "symbols": symbols,
        "category": category,
        "min_score": min_score,
        "results": results[:20],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    scans_col.insert_one(scan_doc)
    
    return {"results": results[:20], "total_scanned": len(symbols)}

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
    # Default symbols to scan
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
    
    # Sort by score and take top 10
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)
    top_10 = scored_stocks[:10]
    
    # Clear old watchlist and insert new
    watchlists_col.delete_many({})
    for item in top_10:
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        watchlists_col.insert_one(item)
    
    # Generate AI insights
    symbols_str = ", ".join([s["symbol"] for s in top_10[:5]])
    ai_insight = await generate_ai_analysis(
        f"Provide a brief 2-3 sentence trading insight for today's top watchlist: {symbols_str}. "
        f"Top mover: {top_10[0]['symbol']} with score {top_10[0]['score']}."
    )
    
    return {
        "watchlist": top_10,
        "ai_insight": ai_insight,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

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
    
    # Update or insert
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
    # Scan popular symbols
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
                    alerts_col.insert_one(alert)
                    new_alerts.append(alert)
    
    return {"alerts_generated": len(new_alerts), "alerts": new_alerts}

@app.put("/api/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str):
    """Mark alert as read"""
    from bson import ObjectId
    result = alerts_col.update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"read": True}}
    )
    return {"updated": result.modified_count > 0}

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
    # Fetch market data
    overview = await get_market_overview()
    news = await fetch_market_news()
    watchlist_response = await generate_morning_watchlist()
    
    # Format data for AI
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
    
    # Generate AI summary
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
    
    newsletters_col.insert_one(newsletter)
    
    # Remove _id before returning
    newsletter.pop("_id", None)
    
    return newsletter

@app.get("/api/newsletter/history")
async def get_newsletter_history(limit: int = 7):
    """Get newsletter history"""
    newsletters = list(newsletters_col.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    return {"newsletters": newsletters}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
