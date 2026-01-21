# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform for tracking real-time stock quotes, scanning for strategy-matching opportunities, and generating AI-powered watchlists and newsletters.

## What's Been Implemented

### Core Features (Jan 21, 2026)
1. **Dashboard** - Main overview with portfolio stats, market performance chart, top movers, alerts
2. **TradingView Charts** - Interactive charts with RSI, MACD, Moving Averages via TradingView widget
3. **Strategy Scanner** - Scan stocks against 50 trading strategies with customizable filters
4. **Trading Strategies** - 50 strategies across 3 categories:
   - Intraday (20): Gap-and-Go, VWAP Bounce, ORB, Scalping, etc.
   - Swing (15): Daily Trend Following, VCP, Earnings Breakout, etc.
   - Investment (15): Buy-and-Hold, DCA, Value Investing, etc.
5. **Watchlist** - AI-ranked top 10 daily picks with strategy scoring
6. **Portfolio Tracker** - Track positions with real-time P&L
7. **Alert Center** - In-app notifications for strategy matches
8. **Morning Newsletter** - AI-generated daily market briefing

### NEW Features (Jan 21, 2026)
9. **Fundamentals Page** - Yahoo Finance data including:
   - Valuation metrics (P/E, P/B, PEG, P/S)
   - Profitability (Profit Margin, ROE, ROA, EPS)
   - Growth metrics (Revenue/Earnings Growth)
   - Financial Health (Debt/Equity, Current Ratio)
   - Dividends (Yield, Payout Ratio)
   - Trading Info (Beta, 52W High/Low, Short %)

10. **Insider Trading Page** - Track unusual insider activity:
    - By Symbol search with transaction history
    - Summary showing total buys/sells, net activity, signal
    - Unusual Activity tab showing stocks with abnormal insider buying

11. **COT Data Page** - Commitment of Traders analysis:
    - Market Summary for major futures (ES, NQ, GC, CL, 6E, ZB)
    - Commercial vs Non-Commercial positions
    - Net positions and weekly changes
    - Bullish/Bearish sentiment indicators

### Technical Stack
- **Frontend**: React + Tailwind CSS + Framer Motion + Recharts + TradingView Widget
- **Backend**: FastAPI + MongoDB
- **AI**: OpenAI GPT-4o via Emergent Universal Key
- **Data Sources**: 
  - Yahoo Finance (yfinance) for quotes and fundamentals
  - Finnhub for news
  - Simulated data for Insider Trading and COT (production would use SEC EDGAR / CFTC)

### API Endpoints
- `/api/health` - Health check
- `/api/quotes/{symbol}` - Get stock quote
- `/api/quotes/batch` - Get multiple quotes
- `/api/market/overview` - Market overview with indices
- `/api/news` - Market news feed
- `/api/strategies` - All 50 trading strategies
- `/api/scanner/scan` - Run strategy scanner
- `/api/watchlist` - Manage watchlist
- `/api/watchlist/generate` - AI-powered watchlist generation
- `/api/portfolio` - Portfolio CRUD operations
- `/api/alerts` - Alert management
- `/api/newsletter/generate` - AI newsletter generation
- **NEW** `/api/fundamentals/{symbol}` - Fundamental analysis
- **NEW** `/api/historical/{symbol}` - Historical price data
- **NEW** `/api/insider/{symbol}` - Insider trading data
- **NEW** `/api/insider/unusual` - Unusual insider activity
- **NEW** `/api/cot/{market}` - COT data by market
- **NEW** `/api/cot/summary` - COT market summary

## Prioritized Backlog

### P0 - Critical (Next Phase)
- [ ] Interactive Brokers API integration for real trading
- [ ] Live real-time data feeds (WebSocket)
- [ ] User authentication system

### P1 - High Priority
- [ ] Real SEC EDGAR integration for insider trading
- [ ] Real CFTC data integration for COT
- [ ] Technical indicator calculations (VWAP, EMA, RSI, etc.)
- [ ] Price alerts with push notifications
- [ ] Historical performance tracking

### P2 - Medium Priority
- [ ] Strategy backtesting
- [ ] Custom strategy builder
- [ ] Multi-account support
- [ ] Export reports to PDF

### P3 - Nice to Have
- [ ] Mobile responsive improvements
- [ ] Dark/light theme toggle
- [ ] Social features (share watchlists)
- [ ] Options chain analysis

## Notes
- TradingView widget integrated for professional charting
- Insider Trading and COT data use simulated data (marked in UI)
- External preview URL routing through Kubernetes ingress
- All AI features use Emergent Universal Key
