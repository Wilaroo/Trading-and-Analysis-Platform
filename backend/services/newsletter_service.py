"""
Newsletter Service - Generates AI-powered premarket briefings using GPT via Emergent LLM
Provides daytrader-style morning newsletters with market context and opportunities
"""
import logging
import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Emergent LLM API configuration
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")


class NewsletterService:
    """Service for generating AI-powered premarket newsletters"""
    
    def __init__(self, ib_service=None):
        self.ib_service = ib_service
        self.api_key = EMERGENT_LLM_KEY
        self._stock_service = None
        self._alpaca_service = None
        self._ai_assistant = None
        
    def set_ib_service(self, ib_service):
        """Set the IB service for market data"""
        self.ib_service = ib_service
    
    def set_stock_service(self, stock_service):
        """Set the stock service for Alpaca data"""
        self._stock_service = stock_service
    
    def set_alpaca_service(self, alpaca_service):
        """Set the Alpaca service directly"""
        self._alpaca_service = alpaca_service
    
    def set_ai_assistant(self, ai_assistant):
        """Set the AI assistant for smart-routed LLM calls"""
        self._ai_assistant = ai_assistant
    
    async def _get_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote with Alpaca priority"""
        # Try stock_service first (has Alpaca)
        if self._stock_service:
            try:
                quote = await self._stock_service.get_quote(symbol)
                if quote and quote.get("price", 0) > 0:
                    return quote
            except:
                pass
        
        # Fallback to IB
        if self.ib_service:
            return await self.ib_service.get_quote(symbol)
        
        return None
    
    async def _get_quotes_batch(self, symbols: List[str]) -> List[Dict]:
        """Get batch quotes with Alpaca priority"""
        # Try Alpaca first
        if self._alpaca_service:
            try:
                alpaca_quotes = await self._alpaca_service.get_quotes_batch(symbols)
                if alpaca_quotes:
                    return list(alpaca_quotes.values())
            except:
                pass
        
        # Fallback to IB
        if self.ib_service:
            return await self.ib_service.get_quotes_batch(symbols)
        
        return []
    
    async def generate_premarket_newsletter(
        self,
        top_movers: List[Dict] = None,
        market_context: Dict = None,
        custom_watchlist: List[str] = None
    ) -> Dict:
        """
        Generate a premarket newsletter written from a daytrader's perspective.
        Uses GPT via Emergent LLM for market intelligence.
        """
        try:
            # Gather market context
            context_data = await self._gather_market_context(
                top_movers=top_movers,
                market_context=market_context,
                custom_watchlist=custom_watchlist
            )
            
            # Generate newsletter content via GPT
            newsletter_content = await self._generate_with_gpt(context_data)
            
            # Parse and structure the response
            newsletter = self._parse_newsletter_response(newsletter_content, context_data)
            
            return newsletter
            
        except Exception as e:
            logger.error(f"Error generating newsletter: {e}")
            return self._get_fallback_newsletter(str(e))
    
    async def _gather_market_context(
        self,
        top_movers: List[Dict] = None,
        market_context: Dict = None,
        custom_watchlist: List[str] = None
    ) -> Dict:
        """Gather all relevant market data for newsletter generation"""
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%A, %B %d, %Y"),
            "top_movers": top_movers or [],
            "market_context": market_context or {},
            "watchlist": custom_watchlist or []
        }
        
        # Get real-time market news
        try:
            from services.news_service import get_news_service
            news_service = get_news_service()
            news_summary = await news_service.get_market_summary()
            
            if news_summary.get("available"):
                context["market_news"] = {
                    "headlines": news_summary.get("headlines", [])[:10],
                    "themes": news_summary.get("themes", []),
                    "overall_sentiment": news_summary.get("overall_sentiment", "unknown"),
                    "sentiment_breakdown": news_summary.get("sentiment_breakdown", {})
                }
                logger.info(f"Loaded {len(news_summary.get('headlines', []))} market news headlines")
        except Exception as e:
            logger.warning(f"Could not fetch market news: {e}")
        
        # Get index quotes using Alpaca priority
        try:
            indices = ["SPY", "QQQ", "DIA", "IWM"]
            index_quotes = await self._get_quotes_batch(indices)
            context["indices"] = {q["symbol"]: q for q in index_quotes if q.get("price")}
            
            # Get VIX - requires IB since it's an index (Alpaca doesn't have indices)
            if self.ib_service:
                try:
                    status = self.ib_service.get_connection_status()
                    if status.get("connected"):
                        vix_quote = await self.ib_service.get_quote("VIX")
                        if vix_quote:
                            context["vix"] = vix_quote
                except:
                    pass
        except Exception as e:
            logger.warning(f"Could not fetch market data for newsletter: {e}")
        
        # Get strategy recommendations from knowledge base
        try:
            from services.knowledge_integration import get_knowledge_integration
            ki = get_knowledge_integration()
            
            # Enhance opportunities with knowledge base insights and news
            if top_movers:
                enhanced = await ki.enhance_market_intelligence(
                    top_movers, 
                    market_regime=market_context.get("regime", "neutral") if market_context else "neutral",
                    include_news=True
                )
                context["kb_insights"] = enhanced.get("top_strategy_insights", [])
                context["kb_stats"] = enhanced.get("knowledge_base_stats", {})
                
                # Add ticker-specific news from enhanced opportunities
                if enhanced.get("opportunities"):
                    for opp in enhanced["opportunities"]:
                        if opp.get("news"):
                            context.setdefault("ticker_news", {})[opp["symbol"]] = opp["news"]
        except Exception as e:
            logger.warning(f"Could not get knowledge base insights: {e}")
        
        return context
    
    async def _generate_with_gpt(self, context_data: Dict) -> str:
        """Generate newsletter content using GPT via Emergent LLM"""
        
        if not self.api_key:
            logger.warning("Emergent LLM key not configured, using fallback")
            return self._generate_fallback_content(context_data)
        
        # Build the prompt
        prompt = self._build_newsletter_prompt(context_data)
        
        try:
            # Use shared AI assistant with smart routing (deep = GPT-4o)
            if self._ai_assistant:
                system_message = """You are an experienced daytrader writing your morning premarket newsletter. 
Your writing style is:
- Direct and actionable - traders need to know what to watch NOW
- Confident but measured - acknowledge uncertainty where it exists
- Data-driven - cite specific numbers, levels, and percentages
- Time-conscious - premarket is limited, focus on what matters TODAY

Structure your response as JSON with these sections:
- market_sentiment: (bullish/bearish/neutral) with a 1-2 sentence explanation
- overnight_recap: Key overnight developments (futures, international markets, crypto)
- key_levels: Important S/R levels for SPY/QQQ
- opportunities: Array of 3-5 stocks to watch with entry/stop/target ideas
- catalyst_watch: Earnings, economic data, fed speakers today
- risk_factors: What could derail the setup
- game_plan: Your specific trading plan for today

Return ONLY valid JSON, no markdown code blocks."""
                
                messages = [{"role": "user", "content": prompt}]
                response = await self._ai_assistant._call_llm(messages, system_message, complexity="deep")
                return response
            
            # Fallback: direct Emergent call if AI assistant not wired
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            system_message = """You are an experienced daytrader writing your morning premarket newsletter. 
Your writing style is:
- Direct and actionable - traders need to know what to watch NOW
- Confident but measured - acknowledge uncertainty where it exists
- Data-driven - cite specific numbers, levels, and percentages
- Time-conscious - premarket is limited, focus on what matters TODAY

Structure your response as JSON with these sections:
- market_sentiment: (bullish/bearish/neutral) with a 1-2 sentence explanation
- overnight_recap: Key overnight developments (futures, international markets, crypto)
- key_levels: Important S/R levels for SPY/QQQ
- opportunities: Array of 3-5 stocks to watch with entry/stop/target ideas
- catalyst_watch: Earnings, economic data, fed speakers today
- risk_factors: What could derail the setup
- game_plan: Your specific trading plan for today

Return ONLY valid JSON, no markdown code blocks."""
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"market-intel-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                system_message=system_message
            ).with_model("openai", "gpt-4o")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            return response
                        
        except Exception as e:
            logger.error(f"Error calling GPT via Emergent LLM: {e}")
            return self._generate_fallback_content(context_data)
    
    def _build_newsletter_prompt(self, context_data: Dict) -> str:
        """Build the prompt for newsletter generation"""
        
        date = context_data.get("date", datetime.now().strftime("%A, %B %d, %Y"))
        
        # Format top movers
        movers_text = ""
        if context_data.get("top_movers"):
            movers_list = []
            for m in context_data["top_movers"][:10]:
                symbol = m.get("symbol", "N/A")
                change = m.get("change_percent") or m.get("quote", {}).get("change_percent") or 0
                try:
                    change = float(change)
                    movers_list.append(f"{symbol}: {change:+.2f}%")
                except (ValueError, TypeError):
                    movers_list.append(f"{symbol}")
            movers_text = f"\nTop Movers from Scanner: {', '.join(movers_list)}"
        
        # Format indices
        indices_text = ""
        if context_data.get("indices"):
            idx_list = []
            for sym, data in context_data["indices"].items():
                try:
                    change = float(data.get("change_percent", 0) or 0)
                    price = float(data.get("price", 0) or 0)
                    idx_list.append(f"{sym}: ${price:.2f} ({change:+.2f}%)")
                except (ValueError, TypeError):
                    idx_list.append(f"{sym}")
            indices_text = f"\nCurrent Index Levels: {', '.join(idx_list)}"
        
        # Format VIX
        vix_text = ""
        if context_data.get("vix"):
            vix = context_data["vix"]
            try:
                vix_price = vix.get('price', 'N/A')
                vix_change = float(vix.get('change_percent', 0) or 0)
                vix_text = f"\nVIX: {vix_price} ({vix_change:+.2f}%)"
            except (ValueError, TypeError):
                vix_text = f"\nVIX: {vix.get('price', 'N/A')}"
        
        # Format knowledge base strategy insights
        kb_insights_text = ""
        if context_data.get("kb_insights"):
            insights_list = []
            for insight in context_data["kb_insights"][:5]:
                title = insight.get("title", "")
                applicable = insight.get("applicable_to", [])
                if title and applicable:
                    insights_list.append(f"- {title} (applies to: {', '.join(applicable[:3])})")
            if insights_list:
                kb_insights_text = "\n\nKNOWLEDGE BASE STRATEGY INSIGHTS:\n" + "\n".join(insights_list)
        
        # Knowledge base stats
        kb_stats_text = ""
        if context_data.get("kb_stats"):
            stats = context_data["kb_stats"]
            total = stats.get("total_entries", 0)
            if total > 0:
                kb_stats_text = f"\n(Analysis backed by {total} learned trading strategies/rules)"
        
        # Format real-time market news
        news_text = ""
        if context_data.get("market_news"):
            news = context_data["market_news"]
            headlines = news.get("headlines", [])
            themes = news.get("themes", [])
            sentiment = news.get("overall_sentiment", "unknown")
            
            if headlines:
                news_text = f"\n\nREAL-TIME MARKET NEWS:\nOverall Sentiment: {sentiment.upper()}"
                if themes:
                    news_text += f"\nKey Themes: {', '.join(themes[:5])}"
                news_text += "\nTop Headlines:"
                for i, headline in enumerate(headlines[:8], 1):
                    news_text += f"\n  {i}. {headline}"
        
        # Format ticker-specific news
        ticker_news_text = ""
        if context_data.get("ticker_news"):
            ticker_news = context_data["ticker_news"]
            if ticker_news:
                ticker_news_text = "\n\nTICKER-SPECIFIC NEWS:"
                for symbol, news_data in list(ticker_news.items())[:5]:
                    if news_data and news_data.get("headlines"):
                        ticker_news_text += f"\n{symbol}: {news_data['headlines'][0][:80]}..."
        
        prompt = f"""Write your premarket newsletter for {date}.

REAL-TIME DATA TO USE:{news_text}

Search for and include:
1. Overnight futures movement and any gaps
2. International market performance (Europe, Asia)
3. Any major premarket news or earnings releases
4. Economic calendar events today
5. Fed speakers or important announcements

My Scanner Data:{movers_text}{indices_text}{vix_text}{ticker_news_text}{kb_insights_text}{kb_stats_text}

Watchlist: {', '.join(context_data.get('watchlist', []) or []) or 'No specific watchlist'}

IMPORTANT: Use the REAL-TIME MARKET NEWS above to provide accurate, current market analysis. Reference specific headlines when discussing market themes.

Generate a complete premarket briefing with specific, actionable trade ideas. Use the knowledge base strategy insights to inform your recommendations. Include price levels, stop losses, and targets where possible. Format your response as valid JSON."""

        return prompt
    
    def _generate_fallback_content(self, context_data: Dict) -> str:
        """Generate basic content when API is unavailable"""
        
        # Build a basic newsletter from available data
        movers = context_data.get("top_movers", [])
        opportunities = []
        
        for m in movers[:5]:
            symbol = m.get("symbol", "")
            quote = m.get("quote", m)
            change = quote.get("change_percent", 0)
            price = quote.get("price", 0)
            
            if change > 3:
                direction = "LONG"
                reasoning = "Strong momentum, gap up"
            elif change < -3:
                direction = "SHORT"
                reasoning = "Weak momentum, gap down"
            else:
                direction = "WATCH"
                reasoning = "Consolidating, wait for direction"
            
            opportunities.append({
                "symbol": symbol,
                "direction": direction,
                "price": price,
                "change_percent": change,
                "reasoning": reasoning
            })
        
        return json.dumps({
            "market_sentiment": "neutral",
            "sentiment_explanation": "Market data requires live connection to analyze sentiment.",
            "overnight_recap": "Connect to IB Gateway and configure Perplexity API for live overnight analysis.",
            "key_levels": {
                "SPY": {"support": "Check charts", "resistance": "Check charts"},
                "QQQ": {"support": "Check charts", "resistance": "Check charts"}
            },
            "opportunities": opportunities,
            "catalyst_watch": ["Enable Perplexity API for economic calendar integration"],
            "risk_factors": ["Limited data available - connect to IB Gateway for full analysis"],
            "game_plan": "1. Connect to IB Gateway\n2. Configure Perplexity API key\n3. Run scanner for opportunities"
        })
    
    def _parse_newsletter_response(self, content: str, context_data: Dict) -> Dict:
        """Parse the GPT response into structured newsletter format"""
        
        date = context_data.get("date", datetime.now().strftime("%A, %B %d, %Y"))
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Try to parse JSON response
        try:
            # Clean the content - remove markdown code blocks if present
            clean_content = content.strip()
            
            # Remove ```json or ``` at start
            if clean_content.startswith("```json"):
                clean_content = clean_content[7:]
            elif clean_content.startswith("```"):
                clean_content = clean_content[3:]
            
            # Remove ``` at end
            if clean_content.endswith("```"):
                clean_content = clean_content[:-3]
            
            clean_content = clean_content.strip()
            
            parsed = json.loads(clean_content)
            
            # Handle different response formats from GPT
            sentiment = parsed.get("market_sentiment") or parsed.get("sentiment", "neutral")
            explanation = parsed.get("explanation") or parsed.get("sentiment_explanation", "")
            overnight = parsed.get("overnight_recap") or parsed.get("summary", "")
            
            return {
                "title": f"Premarket Briefing - {date}",
                "date": timestamp,
                "generated_at": timestamp,
                "market_outlook": {
                    "sentiment": sentiment,
                    "explanation": explanation,
                    "key_levels": parsed.get("key_levels", "See chart analysis"),
                    "focus": (parsed.get("game_plan", "") or "")[:200] if isinstance(parsed.get("game_plan"), str) else ""
                },
                "summary": overnight,
                "top_stories": self._format_catalyst_watch(parsed.get("catalyst_watch", [])),
                "opportunities": self._normalize_opportunities(self._ensure_list(parsed.get("opportunities", []))),
                "risk_factors": self._ensure_list(parsed.get("risk_factors", [])),
                "game_plan": parsed.get("game_plan", "") if isinstance(parsed.get("game_plan"), str) else str(parsed.get("game_plan", "")),
                "watchlist": self._format_watchlist_from_opportunities(parsed.get("opportunities", [])),
                "raw_content": content,
                "needs_generation": False
            }
            
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse JSON response: {e}")
            # Return with raw content as summary
            return {
                "title": f"Premarket Briefing - {date}",
                "date": timestamp,
                "generated_at": timestamp,
                "market_outlook": {
                    "sentiment": "neutral",
                    "explanation": "AI-generated analysis",
                    "key_levels": "",
                    "focus": ""
                },
                "summary": content[:1000] if content else "Newsletter generation failed",
                "top_stories": [],
                "opportunities": [],
                "risk_factors": [],
                "game_plan": content if content else "",
                "watchlist": [],
                "raw_content": content
            }
    
    def _format_catalyst_watch(self, catalysts) -> List[Dict]:
        """Format catalyst items as top stories"""
        stories = []
        # Handle if catalysts is a dict instead of list
        if isinstance(catalysts, dict):
            catalysts = list(catalysts.values()) if catalysts else []
        if not isinstance(catalysts, list):
            catalysts = [catalysts] if catalysts else []
            
        for catalyst in catalysts[:5]:
            if isinstance(catalyst, str):
                stories.append({
                    "headline": catalyst,
                    "summary": "",
                    "impact": "neutral"
                })
            elif isinstance(catalyst, dict):
                stories.append({
                    "headline": catalyst.get("event", catalyst.get("headline", str(catalyst))),
                    "summary": catalyst.get("details", catalyst.get("summary", "")),
                    "impact": catalyst.get("impact", "neutral")
                })
        return stories
    
    def _ensure_list(self, value) -> List:
        """Ensure value is a list"""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.values())
        if isinstance(value, str):
            return [value]
        return [value]
    
    def _normalize_opportunities(self, opportunities: List) -> List[Dict]:
        """Normalize opportunity objects to ensure consistent format with symbol field"""
        normalized = []
        for opp in opportunities:
            if isinstance(opp, dict):
                # Extract symbol from various possible field names
                symbol = (opp.get("symbol") or 
                         opp.get("ticker") or 
                         opp.get("stock") or 
                         opp.get("name", "").split()[0] if opp.get("name") else "")
                
                if symbol:
                    # Clean up symbol (remove $ if present)
                    symbol = symbol.replace("$", "").upper().strip()
                    
                    normalized.append({
                        "symbol": symbol,
                        "direction": opp.get("direction", opp.get("bias", "WATCH")).upper(),
                        "entry": opp.get("entry", opp.get("entry_price")),
                        "target": opp.get("target", opp.get("target_price", opp.get("price_target"))),
                        "stop": opp.get("stop", opp.get("stop_loss", opp.get("stop_price"))),
                        "reasoning": opp.get("reasoning", opp.get("reason", opp.get("rationale", opp.get("notes", "")))),
                        "price": opp.get("price", opp.get("current_price")),
                        "change_percent": opp.get("change_percent", opp.get("change"))
                    })
            elif isinstance(opp, str):
                # If it's just a string, try to extract ticker symbol
                parts = opp.split()
                if parts:
                    symbol = parts[0].replace("$", "").upper().strip()
                    if symbol.isalpha() and len(symbol) <= 5:
                        normalized.append({
                            "symbol": symbol,
                            "direction": "WATCH",
                            "reasoning": opp
                        })
        return normalized
    
    def _format_watchlist_from_opportunities(self, opportunities: List[Dict]) -> List[Dict]:
        """Format opportunities as watchlist items"""
        watchlist = []
        for i, opp in enumerate(opportunities[:10]):
            if isinstance(opp, dict):
                symbol = opp.get("symbol", opp.get("ticker", ""))
                if symbol:
                    # Calculate a simple score based on available data
                    score = 70  # Base score
                    if opp.get("direction") in ["LONG", "SHORT"]:
                        score += 10
                    if opp.get("entry") or opp.get("target"):
                        score += 10
                    
                    watchlist.append({
                        "symbol": symbol,
                        "score": min(score, 100),
                        "reason": opp.get("reasoning", opp.get("reason", "AI identified opportunity")),
                        "direction": opp.get("direction", "WATCH"),
                        "entry": opp.get("entry"),
                        "target": opp.get("target"),
                        "stop": opp.get("stop")
                    })
        return watchlist
    
    def _get_fallback_newsletter(self, error: str) -> Dict:
        """Return a fallback newsletter when generation fails"""
        timestamp = datetime.now(timezone.utc).isoformat()
        date = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        
        return {
            "title": f"Premarket Briefing - {date}",
            "date": timestamp,
            "generated_at": timestamp,
            "market_outlook": {
                "sentiment": "neutral",
                "explanation": "Unable to generate AI analysis",
                "key_levels": "Check TradingView for key levels",
                "focus": "Manual analysis required"
            },
            "summary": f"Newsletter generation encountered an error: {error}. Please check your Perplexity API configuration and try again.",
            "top_stories": [],
            "opportunities": [],
            "risk_factors": ["Newsletter generation failed - use manual analysis"],
            "game_plan": "1. Check API configuration\n2. Verify IB Gateway connection\n3. Use scanner for opportunities",
            "watchlist": [],
            "error": error
        }


# Global service instance
_newsletter_service: Optional[NewsletterService] = None


def get_newsletter_service() -> NewsletterService:
    """Get or create the newsletter service instance"""
    global _newsletter_service
    if _newsletter_service is None:
        _newsletter_service = NewsletterService()
    return _newsletter_service


def init_newsletter_service(ib_service=None) -> NewsletterService:
    """Initialize newsletter service with optional IB service"""
    global _newsletter_service
    _newsletter_service = NewsletterService(ib_service)
    return _newsletter_service
