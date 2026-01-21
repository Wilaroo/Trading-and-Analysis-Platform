# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, and AI-powered insights.

## What's Been Implemented (Jan 21, 2026)

### Real-Time Data Integration
- **Twelve Data API** - Live quotes for stocks, ETFs, indices
- **Quote Caching** - 60-second cache to optimize API usage
- **Fallback System** - Yahoo Finance → Simulated data if APIs fail

### Core Features
1. **Dashboard** - Real-time portfolio tracking, market overview, top movers, alerts
2. **TradingView Charts** - Interactive professional charts with RSI, MACD, MA indicators
3. **Strategy Scanner** - Scan stocks against 50 trading strategies
4. **Trading Strategies** - 50 strategies (20 Intraday, 15 Swing, 15 Investment)
5. **Watchlist** - AI-ranked top 10 daily picks
6. **Portfolio Tracker** - Real-time P&L with live prices
7. **Alert Center** - Strategy match notifications
8. **Morning Newsletter** - AI-generated daily briefing

### Advanced Analysis
9. **Fundamentals Page** - Valuation, profitability, growth metrics
10. **Insider Trading** - Transaction history, unusual activity detection
11. **COT Data** - Commitment of Traders for futures markets

### Technical Stack
- **Frontend**: React + Tailwind CSS + TradingView Widget
- **Backend**: FastAPI + MongoDB
- **Data**: Twelve Data API (real-time), Yahoo Finance (fallback)
- **AI**: OpenAI GPT-4o via Emergent Universal Key

### API Endpoints
- `/api/quotes/{symbol}` - Real-time quote
- `/api/market/overview` - Live market indices
- `/api/fundamentals/{symbol}` - Company fundamentals
- `/api/insider/{symbol}` - Insider trading data
- `/api/cot/summary` - COT market summary
- `/api/strategies` - 50 trading strategies
- `/api/scanner/scan` - Strategy scanner
- Plus 10+ more endpoints

## Notes
- Real-time quotes via Twelve Data API (demo key: 8 req/min limit)
- Caching enabled to optimize API usage
- TradingView widget provides professional charting
- Insider/COT data simulated (production: SEC EDGAR/CFTC)
