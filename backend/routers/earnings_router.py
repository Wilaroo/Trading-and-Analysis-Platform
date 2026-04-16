"""
Earnings Router - Calendar, analysis, IV data endpoints
Extracted from server.py for modularity
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
import random
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Earnings"])

# Dependencies injected via init
_stock_service = None
_get_all_symbols_set = None


def init_earnings_router(stock_service, get_all_symbols_set_fn):
    global _stock_service, _get_all_symbols_set
    _stock_service = stock_service
    _get_all_symbols_set = get_all_symbols_set_fn


# ===================== HELPER FUNCTIONS =====================

def generate_earnings_play_strategy(avg_reaction: float, iv_rank: float, expected_move: float, historical: list, beat_rate: float) -> Dict:
    """Generate earnings play strategy based on historical patterns and user's trading strategies"""
    
    # Analyze historical patterns
    positive_reactions = sum(1 for h in historical if h["stock_reaction"] > 0)
    negative_reactions = len(historical) - positive_reactions
    avg_positive = sum(h["stock_reaction"] for h in historical if h["stock_reaction"] > 0) / max(positive_reactions, 1)
    avg_negative = sum(h["stock_reaction"] for h in historical if h["stock_reaction"] <= 0) / max(negative_reactions, 1)
    max_reaction = max(h["stock_reaction"] for h in historical)
    min_reaction = min(h["stock_reaction"] for h in historical)
    
    # Determine directional bias
    if avg_reaction >= 5:
        bias = "Strong Bullish"
        direction = "LONG"
    elif avg_reaction >= 2:
        bias = "Bullish"
        direction = "LONG"
    elif avg_reaction >= 0:
        bias = "Slight Bullish"
        direction = "LONG"
    elif avg_reaction >= -2:
        bias = "Slight Bearish"
        direction = "SHORT"
    elif avg_reaction >= -5:
        bias = "Bearish"
        direction = "SHORT"
    else:
        bias = "Strong Bearish"
        direction = "SHORT"
    
    # Generate strategy suggestions based on user's trading style patterns
    strategies = []
    
    # High conviction momentum plays
    if positive_reactions >= 3 and avg_positive >= 5:
        strategies.append({
            "name": "Gap & Go Long",
            "type": "momentum_long",
            "category": "intraday",
            "reasoning": f"Strong historical beat pattern: {positive_reactions}/4 positive reactions, avg +{avg_positive:.1f}%",
            "entry": "Enter on gap up confirmation above premarket high",
            "stop": "Below VWAP or gap fill level",
            "confidence": min(85, positive_reactions * 18 + avg_positive * 2)
        })
    
    if negative_reactions >= 3 and avg_negative <= -5:
        strategies.append({
            "name": "Gap Down Short",
            "type": "momentum_short",
            "category": "intraday",
            "reasoning": f"Consistent weakness post-earnings: {negative_reactions}/4 drops, avg {avg_negative:.1f}%",
            "entry": "Short on failed bounce attempt below VWAP",
            "stop": "Above premarket high or R1",
            "confidence": min(85, negative_reactions * 18 + abs(avg_negative) * 2)
        })
    
    # Reversal plays based on expected move vs historical
    if abs(avg_reaction) < expected_move * 0.6:
        strategies.append({
            "name": "Fade the Move",
            "type": "reversal",
            "category": "intraday",
            "reasoning": f"Stock typically moves {abs(avg_reaction):.1f}% vs {expected_move:.1f}% expected - fade extreme reactions",
            "entry": "Wait for overextension then fade toward VWAP",
            "stop": "New high/low of day",
            "confidence": min(75, 50 + (expected_move - abs(avg_reaction)) * 3)
        })
    
    # Swing trade setups
    if beat_rate >= 65 and avg_reaction > 2:
        strategies.append({
            "name": "Post-Earnings Momentum Swing",
            "type": "swing_long",
            "category": "swing",
            "reasoning": f"{beat_rate:.0f}% beat rate with {avg_reaction:+.1f}% avg follow-through",
            "entry": "Buy dip to 9 EMA on day after earnings",
            "stop": "Below earnings day low",
            "confidence": min(80, beat_rate * 0.8 + avg_reaction * 3)
        })
    
    # High volatility plays
    if expected_move >= 8:
        if direction == "LONG":
            strategies.append({
                "name": "Breakout Long",
                "type": "breakout",
                "category": "intraday",
                "reasoning": f"High expected move ({expected_move:.1f}%) with bullish historical bias",
                "entry": "Buy break of premarket high with volume",
                "stop": "Below VWAP",
                "confidence": min(70, 40 + expected_move * 2 + avg_reaction * 2)
            })
        else:
            strategies.append({
                "name": "Breakdown Short",
                "type": "breakdown",
                "category": "intraday",
                "reasoning": f"High expected move ({expected_move:.1f}%) with bearish historical bias",
                "entry": "Short break of premarket low with volume",
                "stop": "Above VWAP",
                "confidence": min(70, 40 + expected_move * 2 + abs(avg_reaction) * 2)
            })
    
    # VWAP-based plays
    if iv_rank >= 50:
        strategies.append({
            "name": "VWAP Reclaim/Rejection",
            "type": "vwap_play",
            "category": "intraday",
            "reasoning": f"Elevated IV ({iv_rank:.0f}%) suggests institutional activity - watch VWAP for direction",
            "entry": "Long on VWAP reclaim with hold, Short on VWAP rejection",
            "stop": "Opposite side of VWAP",
            "confidence": min(70, 45 + iv_rank * 0.4)
        })
    
    # Sort by confidence
    strategies.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    
    return {
        "bias": bias,
        "direction": direction,
        "avg_reaction": avg_reaction,
        "win_rate": round(positive_reactions / len(historical) * 100, 0) if historical else 50,
        "max_gain": max_reaction,
        "max_loss": min_reaction,
        "strategies": strategies[:3],  # Top 3 strategies
        "historical_pattern": {
            "positive_count": positive_reactions,
            "negative_count": negative_reactions,
            "avg_positive_move": round(avg_positive, 1),
            "avg_negative_move": round(avg_negative, 1)
        }
    }


def generate_earnings_data(symbol: str, earnings_date: str) -> Dict:
    """Generate simulated earnings data for a symbol"""
    random.seed(hash(symbol + earnings_date))
    
    # Simulate historical earnings data
    eps_estimates = round(random.uniform(0.5, 5.0), 2)
    eps_actual = round(eps_estimates * random.uniform(0.85, 1.25), 2)
    revenue_estimates = round(random.uniform(10, 100), 2)  # In billions
    revenue_actual = round(revenue_estimates * random.uniform(0.92, 1.15), 2)
    
    # Historical earnings (last 4 quarters)
    historical = []
    for i in range(4):
        quarter_date = (datetime.now() - timedelta(days=90 * (i + 1))).strftime("%Y-%m-%d")
        hist_eps_est = round(eps_estimates * random.uniform(0.8, 1.2), 2)
        hist_eps_act = round(hist_eps_est * random.uniform(0.85, 1.25), 2)
        surprise_pct = round(((hist_eps_act - hist_eps_est) / abs(hist_eps_est)) * 100, 2) if hist_eps_est != 0 else 0
        historical.append({
            "date": quarter_date,
            "quarter": f"Q{4 - i} {datetime.now().year - (1 if i >= 2 else 0)}",
            "eps_estimate": hist_eps_est,
            "eps_actual": hist_eps_act,
            "eps_surprise": round(hist_eps_act - hist_eps_est, 2),
            "eps_surprise_percent": surprise_pct,
            "revenue_estimate": round(revenue_estimates * random.uniform(0.85, 1.15), 2),
            "revenue_actual": round(revenue_estimates * random.uniform(0.88, 1.18), 2),
            "stock_reaction": round(random.uniform(-8, 12), 2)  # % move after earnings
        })
    
    # Implied volatility data
    current_iv = round(random.uniform(25, 80), 1)
    historical_iv = round(current_iv * random.uniform(0.7, 1.3), 1)
    iv_rank = round(random.uniform(20, 95), 1)
    iv_percentile = round(random.uniform(15, 98), 1)
    expected_move = round(random.uniform(3, 15), 2)
    
    # Earnings whispers (analyst expectations vs whisper numbers)
    whisper_eps = round(eps_estimates * random.uniform(0.95, 1.15), 2)
    analyst_count = random.randint(5, 35)
    
    # Sentiment data
    sentiments = ["Bullish", "Bearish", "Neutral", "Very Bullish", "Very Bearish"]
    sentiment_weights = [0.25, 0.15, 0.35, 0.15, 0.10]
    whisper_sentiment = random.choices(sentiments, weights=sentiment_weights)[0]
    
    return {
        "symbol": symbol,
        "earnings_date": earnings_date,
        "time": random.choice(["Before Open", "After Close"]),
        "fiscal_quarter": f"Q{random.randint(1, 4)} {datetime.now().year}",
        
        # Estimates
        "eps_estimate": eps_estimates,
        "revenue_estimate_b": revenue_estimates,
        "whisper_eps": whisper_eps,
        "whisper_vs_consensus": round(((whisper_eps - eps_estimates) / eps_estimates) * 100, 2),
        
        # Analyst data
        "analyst_count": analyst_count,
        "analyst_revisions_up": random.randint(0, analyst_count // 2),
        "analyst_revisions_down": random.randint(0, analyst_count // 3),
        
        # Implied Volatility
        "implied_volatility": {
            "current_iv": current_iv,
            "historical_iv_30d": historical_iv,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "expected_move_percent": expected_move,
            "expected_move_dollar": round(random.uniform(5, 50), 2),
            "straddle_price": round(random.uniform(2, 20), 2),
            "iv_crush_expected": round(random.uniform(15, 45), 1)
        },
        
        # Whisper data
        "whisper": {
            "eps": whisper_eps,
            "sentiment": whisper_sentiment,
            "confidence": round(random.uniform(50, 95), 1),
            "beat_probability": round(random.uniform(35, 75), 1),
            "historical_beat_rate": round(random.uniform(50, 85), 1)
        },
        
        # Historical earnings
        "historical_earnings": historical,
        
        # Average surprise
        "avg_eps_surprise_4q": round(sum(h["eps_surprise_percent"] for h in historical) / 4, 2),
        "avg_stock_reaction_4q": round(sum(h["stock_reaction"] for h in historical) / 4, 2),
        
        # Earnings Play Strategy based on historical patterns
        "earnings_play": generate_earnings_play_strategy(
            avg_reaction=round(sum(h["stock_reaction"] for h in historical) / 4, 2),
            iv_rank=iv_rank,
            expected_move=expected_move,
            historical=historical,
            beat_rate=round(random.uniform(50, 85), 1)
        )
    }


# Well-known company name lookup (avoids per-symbol API calls)
COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "META": "Meta Platforms", "NVDA": "NVIDIA", "TSLA": "Tesla",
    "BRK.B": "Berkshire Hathaway", "JPM": "JPMorgan Chase", "V": "Visa",
    "JNJ": "Johnson & Johnson", "WMT": "Walmart", "PG": "Procter & Gamble",
    "MA": "Mastercard", "HD": "Home Depot", "CVX": "Chevron", "MRK": "Merck",
    "ABBV": "AbbVie", "PEP": "PepsiCo", "KO": "Coca-Cola", "AVGO": "Broadcom",
    "COST": "Costco", "TMO": "Thermo Fisher", "MCD": "McDonald's",
    "CSCO": "Cisco", "ACN": "Accenture", "ABT": "Abbott Labs",
    "DHR": "Danaher", "NKE": "Nike", "TXN": "Texas Instruments",
    "PM": "Philip Morris", "NEE": "NextEra Energy", "UNH": "UnitedHealth",
    "LIN": "Linde", "LOW": "Lowe's", "UNP": "Union Pacific",
    "ORCL": "Oracle", "ADBE": "Adobe", "CRM": "Salesforce",
    "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm", "AMAT": "Applied Materials",
    "MU": "Micron", "LRCX": "Lam Research", "KLAC": "KLA Corp",
    "FDX": "FedEx", "UPS": "UPS", "DG": "Dollar General",
    "LEN": "Lennar", "LULU": "Lululemon", "CCL": "Carnival",
    "GME": "GameStop", "WBA": "Walgreens", "GIS": "General Mills",
    "DRI": "Darden Restaurants", "DOCU": "DocuSign", "PATH": "UiPath",
    "NIO": "NIO Inc", "BNTX": "BioNTech", "MRVL": "Marvell Technology",
    "HPE": "Hewlett Packard", "CRWD": "CrowdStrike", "SNOW": "Snowflake",
    "PANW": "Palo Alto Networks", "ZS": "Zscaler", "DDOG": "Datadog",
    "NET": "Cloudflare", "SQ": "Block Inc", "SHOP": "Shopify",
    "ROKU": "Roku", "SNAP": "Snap Inc", "PINS": "Pinterest",
    "COIN": "Coinbase", "HOOD": "Robinhood", "SOFI": "SoFi Technologies",
    "PLTR": "Palantir", "RIVN": "Rivian", "LCID": "Lucid Motors",
    "CPB": "Campbell Soup", "CAG": "Conagra", "PVH": "PVH Corp",
    "KMX": "CarMax", "BLNK": "Blink Charging", "LAZR": "Luminar",
    "FCEL": "FuelCell Energy", "PLUG": "Plug Power", "SNDL": "SNDL Inc",
    "LUNR": "Intuitive Machines", "GRWG": "GrowGeneration",
    "ABM": "ABM Industries", "CBRL": "Cracker Barrel",
    "SIG": "Signet Jewelers", "PD": "PagerDuty", "AI": "C3.ai",
}


# ===================== ENDPOINTS =====================

@router.get("/earnings/calendar")
async def get_earnings_calendar(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    symbols: Optional[str] = None
):
    """Get earnings calendar from Finnhub (real data)"""
    
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    
    # Fetch real earnings data from Finnhub
    raw_earnings = await _stock_service.get_earnings_calendar(from_date=start_date, to_date=end_date)
    
    # Filter to symbols in our scanning universe for relevance
    universe = _get_all_symbols_set()
    
    # Filter by requested symbols if provided, otherwise use universe
    if symbols:
        symbol_list = {s.strip().upper() for s in symbols.split(",")}
        raw_earnings = [e for e in raw_earnings if e.get("symbol") in symbol_list]
    else:
        raw_earnings = [e for e in raw_earnings if e.get("symbol") in universe]
    
    # Build calendar entries from real Finnhub data
    calendar = []
    for entry in raw_earnings:
        sym = entry.get("symbol", "")
        if not sym:
            continue
        
        hour = entry.get("hour", "")
        time_label = "Before Open" if hour == "bmo" else "After Close"
        earnings_date = entry.get("date", "")
        
        eps_est = entry.get("epsEstimate")
        eps_act = entry.get("epsActual")
        rev_est = entry.get("revenueEstimate")
        rev_act = entry.get("revenueActual")
        
        # Deterministic seed per symbol
        random.seed(hash(sym + earnings_date))
        
        # Simulated stock price (seeded by symbol for consistency)
        sim_price = round(random.uniform(15, 400), 2)
        
        # Expected move
        expected_move_pct = round(random.uniform(2, 12), 2)
        expected_move_dollar = round(sim_price * expected_move_pct / 100, 2)
        
        # Earnings score: A+ to F
        has_reported = eps_act is not None
        if has_reported and eps_est is not None and eps_est != 0:
            eps_surprise_pct = ((eps_act - eps_est) / abs(eps_est)) * 100
            rev_surprise_pct = ((rev_act - rev_est) / abs(rev_est)) * 100 if rev_est and rev_act and rev_est != 0 else 0
            combined = eps_surprise_pct * 0.6 + rev_surprise_pct * 0.4
            if combined >= 10: score_label, score_value = "A+", 95
            elif combined >= 5: score_label, score_value = "A", 85
            elif combined >= 1: score_label, score_value = "B+", 75
            elif combined >= -1: score_label, score_value = "B", 65
            elif combined >= -5: score_label, score_value = "C", 50
            elif combined >= -10: score_label, score_value = "D", 35
            else: score_label, score_value = "F", 15
        else:
            if eps_est is not None and rev_est is not None:
                base = 60 + random.randint(-15, 15)
                if abs(eps_est) > 1: base += 5
                if rev_est and rev_est > 1e9: base += 5
                base = max(20, min(95, base))
                if base >= 80: score_label = "A"
                elif base >= 65: score_label = "B+"
                elif base >= 50: score_label = "B"
                elif base >= 35: score_label = "C"
                else: score_label = "D"
                score_value = base
            else:
                score_label, score_value = "N/A", 0
        
        item = {
            "symbol": sym,
            "earnings_date": earnings_date,
            "time": time_label,
            "company_name": COMPANY_NAMES.get(sym, sym),
            "eps_estimate": eps_est,
            "eps_actual": eps_act,
            "revenue_estimate": rev_est,
            "revenue_actual": rev_act,
            "quarter": entry.get("quarter"),
            "year": entry.get("year"),
            "has_reported": has_reported,
            "expected_move": {
                "percent": expected_move_pct,
                "dollar": expected_move_dollar
            },
            "earnings_score": {
                "label": score_label,
                "value": score_value,
                "type": "actual" if has_reported else "projected"
            },
        }
        
        # Add surprise data if already reported
        if has_reported and eps_est and eps_est != 0:
            item["eps_surprise"] = {
                "amount": round(eps_act - eps_est, 4),
                "percent": round(((eps_act - eps_est) / abs(eps_est)) * 100, 2)
            }
        
        calendar.append(item)
    
    # Sort by date then symbol
    calendar.sort(key=lambda x: (x["earnings_date"], x["symbol"]))
    
    # Group by date
    grouped = {}
    for item in calendar:
        date = item["earnings_date"]
        if date not in grouped:
            grouped[date] = {"date": date, "count": 0, "before_open": [], "after_close": []}
        grouped[date]["count"] += 1
        if item["time"] == "Before Open":
            grouped[date]["before_open"].append(item)
        else:
            grouped[date]["after_close"].append(item)
    
    return {
        "calendar": calendar,
        "grouped_by_date": list(grouped.values()),
        "start_date": start_date,
        "end_date": end_date,
        "total_count": len(calendar)
    }


@router.get("/earnings/today")
async def get_earnings_today():
    """Get earnings for today and this week"""
    today = datetime.now().strftime("%Y-%m-%d")
    week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Get calendar data
    calendar_data = await get_earnings_calendar(start_date=today, end_date=week_end)
    
    # Filter for today
    today_earnings = [e for e in calendar_data["calendar"] if e["earnings_date"] == today]
    
    # Convert to simpler format for widget
    earnings_list = []
    for e in today_earnings:
        earnings_list.append({
            "symbol": e["symbol"],
            "name": e.get("company_name", ""),
            "timing": "BMO" if e.get("time") == "Before Open" else "AMC",
            "time": e.get("time", ""),
            "rating": e.get("earnings_play", {}).get("strategy", {}).get("quality", "B"),
            "catalyst_score": e.get("iv_percentile", 50),
            "expected_move": e.get("expected_move", {}).get("percent", 0)
        })
    
    return {
        "earnings": earnings_list,
        "date": today,
        "count": len(earnings_list)
    }


@router.get("/earnings/{symbol}")
async def get_earnings_detail(symbol: str):
    """Get detailed earnings data for a specific symbol"""
    
    # Get next earnings date (simulated)
    random.seed(hash(symbol))
    days_until_earnings = random.randint(1, 45)
    earnings_date = (datetime.now() + timedelta(days=days_until_earnings)).strftime("%Y-%m-%d")
    
    earnings_data = await generate_earnings_data(symbol.upper(), earnings_date)
    
    # Add more detailed historical data
    detailed_history = []
    for i in range(8):  # Last 8 quarters
        quarter_date = (datetime.now() - timedelta(days=90 * (i + 1))).strftime("%Y-%m-%d")
        random.seed(hash(symbol + quarter_date))
        
        eps_est = round(random.uniform(0.5, 5.0), 2)
        eps_act = round(eps_est * random.uniform(0.85, 1.25), 2)
        rev_est = round(random.uniform(10, 100), 2)
        rev_act = round(rev_est * random.uniform(0.92, 1.15), 2)
        
        detailed_history.append({
            "date": quarter_date,
            "quarter": f"Q{((4 - i) % 4) + 1} {datetime.now().year - ((i + 1) // 4)}",
            "eps_estimate": eps_est,
            "eps_actual": eps_act,
            "eps_surprise": round(eps_act - eps_est, 2),
            "eps_surprise_percent": round(((eps_act - eps_est) / abs(eps_est)) * 100, 2) if eps_est != 0 else 0,
            "revenue_estimate_b": rev_est,
            "revenue_actual_b": rev_act,
            "revenue_surprise_percent": round(((rev_act - rev_est) / abs(rev_est)) * 100, 2) if rev_est != 0 else 0,
            "stock_price_before": round(random.uniform(100, 500), 2),
            "stock_price_after": round(random.uniform(100, 500), 2),
            "stock_reaction_1d": round(random.uniform(-10, 15), 2),
            "stock_reaction_5d": round(random.uniform(-15, 20), 2),
            "iv_before": round(random.uniform(30, 80), 1),
            "iv_after": round(random.uniform(20, 50), 1),
            "volume_vs_avg": round(random.uniform(1.5, 5.0), 2)
        })
    
    earnings_data["detailed_history"] = detailed_history
    
    # Calculate statistics
    beat_count = sum(1 for h in detailed_history if h["eps_surprise"] > 0)
    earnings_data["statistics"] = {
        "beat_rate": round((beat_count / len(detailed_history)) * 100, 1),
        "avg_surprise": round(sum(h["eps_surprise_percent"] for h in detailed_history) / len(detailed_history), 2),
        "avg_stock_reaction": round(sum(h["stock_reaction_1d"] for h in detailed_history) / len(detailed_history), 2),
        "max_positive_reaction": max(h["stock_reaction_1d"] for h in detailed_history),
        "max_negative_reaction": min(h["stock_reaction_1d"] for h in detailed_history),
        "avg_iv_crush": round(sum((h["iv_before"] - h["iv_after"]) for h in detailed_history) / len(detailed_history), 1)
    }
    
    return earnings_data


@router.get("/earnings/iv/{symbol}")
def get_earnings_iv(symbol: str):
    """Get implied volatility analysis for earnings"""
    random.seed(hash(symbol + "iv"))
    
    # Current IV data
    current_iv = round(random.uniform(25, 80), 1)
    iv_30d = round(current_iv * random.uniform(0.7, 1.1), 1)
    iv_60d = round(current_iv * random.uniform(0.65, 1.0), 1)
    
    # IV term structure (days to expiration)
    term_structure = []
    for dte in [7, 14, 21, 30, 45, 60, 90]:
        term_structure.append({
            "dte": dte,
            "iv": round(current_iv * (1 + random.uniform(-0.15, 0.25) * (30 - dte) / 30), 1)
        })
    
    # Historical IV before earnings
    historical_iv = []
    for i in range(4):
        historical_iv.append({
            "quarter": f"Q{4 - i}",
            "iv_1w_before": round(random.uniform(35, 90), 1),
            "iv_1d_before": round(random.uniform(40, 100), 1),
            "iv_1d_after": round(random.uniform(20, 50), 1),
            "iv_crush_percent": round(random.uniform(25, 55), 1),
            "actual_move": round(random.uniform(2, 15), 2),
            "expected_move": round(random.uniform(4, 18), 2),
            "move_vs_expected": round(random.uniform(-50, 50), 1)
        })
    
    return {
        "symbol": symbol.upper(),
        "current_iv": current_iv,
        "iv_30d_avg": iv_30d,
        "iv_60d_avg": iv_60d,
        "iv_rank": round(random.uniform(20, 95), 1),
        "iv_percentile": round(random.uniform(15, 98), 1),
        "term_structure": term_structure,
        "historical_earnings_iv": historical_iv,
        "expected_move": {
            "percent": round(random.uniform(4, 15), 2),
            "dollar": round(random.uniform(5, 50), 2),
            "straddle_cost": round(random.uniform(3, 25), 2),
            "strangle_cost": round(random.uniform(2, 18), 2)
        },
        "recommendation": random.choice([
            "IV elevated - consider selling premium",
            "IV low relative to historical - consider buying straddles",
            "Neutral IV - wait for better setup",
            "High IV rank - good for iron condors"
        ])
    }
