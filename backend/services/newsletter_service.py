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
        
    def set_ib_service(self, ib_service):
        """Set the IB service for market data"""
        self.ib_service = ib_service
    
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
        
        # Try to get additional data from IB if connected
        if self.ib_service:
            try:
                status = self.ib_service.get_connection_status()
                if status.get("connected"):
                    # Get index quotes
                    indices = ["SPY", "QQQ", "DIA", "IWM"]
                    index_quotes = await self.ib_service.get_quotes_batch(indices)
                    context["indices"] = {q["symbol"]: q for q in index_quotes if q.get("price")}
                    
                    # Get VIX
                    vix_quote = await self.ib_service.get_quote("VIX")
                    if vix_quote:
                        context["vix"] = vix_quote
            except Exception as e:
                logger.warning(f"Could not fetch IB data for newsletter: {e}")
        
        return context
    
    async def _generate_with_gpt(self, context_data: Dict) -> str:
        """Generate newsletter content using GPT via Emergent LLM"""
        
        if not self.api_key:
            logger.warning("Emergent LLM key not configured, using fallback")
            return self._generate_fallback_content(context_data)
        
        # Build the prompt
        prompt = self._build_newsletter_prompt(context_data)
        
        try:
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
                change = m.get("change_percent", m.get("quote", {}).get("change_percent", 0))
                movers_list.append(f"{symbol}: {change:+.2f}%")
            movers_text = f"\nTop Movers from Scanner: {', '.join(movers_list)}"
        
        # Format indices
        indices_text = ""
        if context_data.get("indices"):
            idx_list = []
            for sym, data in context_data["indices"].items():
                change = data.get("change_percent", 0)
                price = data.get("price", 0)
                idx_list.append(f"{sym}: ${price:.2f} ({change:+.2f}%)")
            indices_text = f"\nCurrent Index Levels: {', '.join(idx_list)}"
        
        # Format VIX
        vix_text = ""
        if context_data.get("vix"):
            vix = context_data["vix"]
            vix_text = f"\nVIX: {vix.get('price', 'N/A')} ({vix.get('change_percent', 0):+.2f}%)"
        
        prompt = f"""Write your premarket newsletter for {date}.

Search for and include:
1. Overnight futures movement and any gaps
2. International market performance (Europe, Asia)
3. Any major premarket news or earnings releases
4. Economic calendar events today
5. Fed speakers or important announcements

My Scanner Data:{movers_text}{indices_text}{vix_text}

Watchlist: {', '.join(context_data.get('watchlist', [])) or 'No specific watchlist'}

Generate a complete premarket briefing with specific, actionable trade ideas. Include price levels, stop losses, and targets where possible. Format your response as valid JSON."""

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
        """Parse the Perplexity response into structured newsletter format"""
        
        date = context_data.get("date", datetime.now().strftime("%A, %B %d, %Y"))
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Try to parse JSON response
        try:
            # Clean the content - remove markdown code blocks if present
            clean_content = content.strip()
            if clean_content.startswith("```"):
                # Remove opening code block
                clean_content = clean_content.split("\n", 1)[1] if "\n" in clean_content else clean_content[3:]
            if clean_content.endswith("```"):
                clean_content = clean_content[:-3]
            if clean_content.startswith("json"):
                clean_content = clean_content[4:].strip()
            
            parsed = json.loads(clean_content)
            
            return {
                "title": f"Premarket Briefing - {date}",
                "date": timestamp,
                "generated_at": timestamp,
                "market_outlook": {
                    "sentiment": parsed.get("market_sentiment", "neutral"),
                    "explanation": parsed.get("sentiment_explanation", ""),
                    "key_levels": parsed.get("key_levels", "See chart analysis"),
                    "focus": parsed.get("game_plan", "")[:200] if parsed.get("game_plan") else ""
                },
                "summary": parsed.get("overnight_recap", ""),
                "top_stories": self._format_catalyst_watch(parsed.get("catalyst_watch", [])),
                "opportunities": parsed.get("opportunities", []),
                "risk_factors": parsed.get("risk_factors", []),
                "game_plan": parsed.get("game_plan", ""),
                "watchlist": self._format_watchlist_from_opportunities(parsed.get("opportunities", [])),
                "raw_content": content
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
    
    def _format_catalyst_watch(self, catalysts: List) -> List[Dict]:
        """Format catalyst items as top stories"""
        stories = []
        for i, catalyst in enumerate(catalysts[:5]):
            if isinstance(catalyst, str):
                stories.append({
                    "headline": catalyst,
                    "summary": "",
                    "impact": "neutral"
                })
            elif isinstance(catalyst, dict):
                stories.append({
                    "headline": catalyst.get("event", catalyst.get("headline", "")),
                    "summary": catalyst.get("details", catalyst.get("summary", "")),
                    "impact": catalyst.get("impact", "neutral")
                })
        return stories
    
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
