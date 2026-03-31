"""
Social Feed Service - Manages Twitter/X handles and AI sentiment analysis.
Stores handle configuration in MongoDB and provides sentiment analysis on pasted tweet text.
"""
import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Default handles the user wants to follow
DEFAULT_HANDLES = [
    {"handle": "faststocknewss", "label": "Fast Stock News", "category": "news", "description": "Breaking stock market news and headlines", "priority": 1},
    {"handle": "Deltaone", "label": "DeltaOne", "category": "news", "description": "Real-time macro and market-moving headlines", "priority": 2},
    {"handle": "unusual_whales", "label": "Unusual Whales", "category": "flow", "description": "Unusual options activity and dark pool flow alerts", "priority": 3},
    {"handle": "TruthTrumpPosts", "label": "Trump Posts", "category": "political", "description": "Truth Social posts from Donald Trump - market-moving political commentary", "priority": 4},
    {"handle": "TheShortBear", "label": "The Short Bear", "category": "short-seller", "description": "Short-selling research and bearish analysis"},
    {"handle": "OracleNYSE", "label": "Oracle NYSE", "category": "analysis", "description": "NYSE flow analysis and trade ideas"},
    {"handle": "ttvresearch", "label": "TTV Research", "category": "research", "description": "Technical and fundamental research"},
    {"handle": "TradetheMatrix1", "label": "Trade the Matrix", "category": "trading", "description": "Active day trading and momentum plays"},
    {"handle": "ResearchGrizzly", "label": "Grizzly Research", "category": "short-seller", "description": "Short-selling investigative research"},
    {"handle": "HindendburgRes", "label": "Hindenburg Research", "category": "short-seller", "description": "Activist short-selling research reports"},
    {"handle": "Qullamaggie", "label": "Qullamaggie", "category": "trading", "description": "Swing trading momentum breakouts"},
    {"handle": "CitronResearch", "label": "Citron Research", "category": "short-seller", "description": "Activist short-selling and market commentary"},
    {"handle": "eWhispers", "label": "Earnings Whispers", "category": "earnings", "description": "Earnings expectations, whisper numbers, and calendars"},
    {"handle": "PaulJSingh", "label": "Paul J Singh", "category": "trading", "description": "Small-cap trading and stock analysis"},
    {"handle": "sspencer_smb", "label": "Steve Spencer (SMB)", "category": "education", "description": "SMB Capital partner, trading education and coaching"},
    {"handle": "szaman", "label": "S. Zaman", "category": "trading", "description": "Active trading and market analysis"},
    {"handle": "alphatrends", "label": "Alpha Trends", "category": "analysis", "description": "Technical analysis and market trends"},
    {"handle": "InvestorsLive", "label": "InvestorsLive", "category": "trading", "description": "Day trading and small-cap momentum plays"},
    {"handle": "TheShortSniper", "label": "The Short Sniper", "category": "short-seller", "description": "Short-selling focused trade ideas"},
    {"handle": "TheOneLanceB", "label": "Lance B", "category": "trading", "description": "Day trading and market commentary"},
]

CATEGORY_COLORS = {
    "news": "#3b82f6",        # blue
    "short-seller": "#ef4444", # red
    "trading": "#10b981",      # emerald
    "analysis": "#8b5cf6",     # violet
    "research": "#f59e0b",     # amber
    "earnings": "#06b6d4",     # cyan
    "education": "#ec4899",    # pink
    "flow": "#f97316",         # orange
    "political": "#dc2626",    # red-600
}


class SocialFeedService:
    def __init__(self, db):
        self.db = db
        self.config_collection = db["social_feed_config"] if db is not None else None
        self.analyses_collection = db["social_feed_analyses"] if db is not None else None
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Ensure default handles exist in DB. Re-seed if handle list changed."""
        if self.config_collection is None:
            return
        existing = self.config_collection.find_one({"_id": "handles_config"})
        if not existing or len(existing.get("handles", [])) != len(DEFAULT_HANDLES):
            self.config_collection.replace_one(
                {"_id": "handles_config"},
                {
                    "_id": "handles_config",
                    "handles": DEFAULT_HANDLES,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
                upsert=True
            )

    def get_handles(self) -> List[Dict]:
        """Get configured handles list."""
        if self.config_collection is None:
            return DEFAULT_HANDLES
        doc = self.config_collection.find_one({"_id": "handles_config"})
        if doc:
            return doc.get("handles", DEFAULT_HANDLES)
        return DEFAULT_HANDLES

    def update_handles(self, handles: List[Dict]) -> Dict:
        """Update handles configuration."""
        if self.config_collection is None:
            return {"success": False, "error": "Database not available"}
        self.config_collection.update_one(
            {"_id": "handles_config"},
            {"$set": {
                "handles": handles,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        return {"success": True, "count": len(handles)}

    def add_handle(self, handle: str, label: str = "", category: str = "trading", description: str = "") -> Dict:
        """Add a single handle to the list."""
        handles = self.get_handles()
        # Check if already exists
        if any(h["handle"].lower() == handle.lower() for h in handles):
            return {"success": False, "error": f"@{handle} already in list"}
        handles.append({
            "handle": handle,
            "label": label or handle,
            "category": category,
            "description": description
        })
        return self.update_handles(handles)

    def remove_handle(self, handle: str) -> Dict:
        """Remove a handle from the list."""
        handles = self.get_handles()
        new_handles = [h for h in handles if h["handle"].lower() != handle.lower()]
        if len(new_handles) == len(handles):
            return {"success": False, "error": f"@{handle} not found"}
        return self.update_handles(new_handles)

    def analyze_sentiment(self, text: str, handle: str = "") -> Dict:
        """
        Analyze sentiment of pasted tweet text using AI.
        Returns sentiment, market impact, tickers mentioned, and brief analysis.
        """
        prompt = self._build_sentiment_prompt(text, handle)
        analysis = self._call_llm_for_sentiment(prompt)

        # Store in DB for future reference
        if self.analyses_collection is not None:
            self.analyses_collection.insert_one({
                "text": text[:500],
                "handle": handle,
                "analysis": analysis,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            })

        return analysis

    def get_recent_analyses(self, limit: int = 20) -> List[Dict]:
        """Get recent sentiment analyses."""
        if self.analyses_collection is None:
            return []
        cursor = self.analyses_collection.find(
            {},
            {"_id": 0}
        ).sort("analyzed_at", -1).limit(limit)
        return list(cursor)

    def _build_sentiment_prompt(self, text: str, handle: str) -> str:
        """Build the prompt for AI sentiment analysis."""
        handle_ctx = ""
        if handle:
            handles = self.get_handles()
            match = next((h for h in handles if h["handle"].lower() == handle.lower()), None)
            if match:
                handle_ctx = f"\nSource: @{handle} ({match.get('description', 'Market commentator')})\nCategory: {match.get('category', 'trading')}\n"

        return (
            f"You are a market sentiment analyst. Analyze this social media post for trading implications.\n"
            f"{handle_ctx}\n"
            f"POST:\n\"{text}\"\n\n"
            f"Respond in this EXACT JSON format (no markdown, just raw JSON):\n"
            f'{{"sentiment": "BULLISH|BEARISH|NEUTRAL", '
            f'"confidence": 0.0-1.0, '
            f'"market_impact": "HIGH|MEDIUM|LOW", '
            f'"tickers": ["AAPL", "TSLA"], '
            f'"summary": "One sentence summary of the market implication", '
            f'"action": "Brief suggested action for a trader"}}'
        )

    def _call_llm_for_sentiment(self, prompt: str) -> Dict:
        """Call LLM for sentiment analysis. Same fallback chain as trade_snapshots."""
        import httpx

        # Try Ollama HTTP proxy
        try:
            from server import is_http_ollama_proxy_connected, call_ollama_via_http_proxy
            if is_http_ollama_proxy_connected():
                model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
                messages = [
                    {"role": "system", "content": "You are a market sentiment analyst. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ]
                response = call_ollama_via_http_proxy(messages, model=model, max_tokens=300)
                if response:
                    return self._parse_sentiment_response(response)
        except Exception as e:
            logger.debug(f"Ollama proxy not available: {e}")

        # Try direct Ollama
        ollama_url = os.environ.get("OLLAMA_URL", "")
        if ollama_url:
            try:
                model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
                resp = httpx.post(
                    f"{ollama_url.rstrip('/')}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are a market sentiment analyst. Always respond with valid JSON only."},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "options": {"num_predict": 300}
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "")
                    return self._parse_sentiment_response(content)
            except Exception as e:
                logger.debug(f"Direct Ollama failed: {e}")

        # Try Emergent LLM
        emergent_key = os.environ.get("EMERGENT_LLM_KEY", "")
        if emergent_key:
            try:
                from emergentintegrations.llm.chat import chat, ChatMessage
                messages = [
                    ChatMessage(role="system", content="You are a market sentiment analyst. Always respond with valid JSON only."),
                    ChatMessage(role="user", content=prompt)
                ]
                response = chat(
                    api_key=emergent_key,
                    model="claude-sonnet-4-20250514",
                    messages=messages
                )
                if response and response.message:
                    return self._parse_sentiment_response(response.message)
            except Exception as e:
                logger.debug(f"Emergent LLM failed: {e}")

        # Fallback - basic keyword analysis
        return self._basic_sentiment_analysis(prompt)

    def _parse_sentiment_response(self, text: str) -> Dict:
        """Parse LLM JSON response into sentiment dict."""
        import json
        try:
            # Try to extract JSON from the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass
        return self._basic_sentiment_analysis(text)

    def _basic_sentiment_analysis(self, text: str) -> Dict:
        """Basic keyword-based sentiment when LLM is unavailable."""
        text_lower = text.lower()
        bullish_words = ["buy", "long", "bull", "breakout", "upgrade", "beat", "surge", "rally", "moon", "calls", "up"]
        bearish_words = ["sell", "short", "bear", "breakdown", "downgrade", "miss", "crash", "dump", "puts", "fraud", "overvalued"]

        bull_count = sum(1 for w in bullish_words if w in text_lower)
        bear_count = sum(1 for w in bearish_words if w in text_lower)

        if bull_count > bear_count:
            sentiment = "BULLISH"
            confidence = min(0.5 + (bull_count - bear_count) * 0.1, 0.8)
        elif bear_count > bull_count:
            sentiment = "BEARISH"
            confidence = min(0.5 + (bear_count - bull_count) * 0.1, 0.8)
        else:
            sentiment = "NEUTRAL"
            confidence = 0.4

        # Extract potential tickers ($AAPL style)
        import re
        tickers = re.findall(r'\$([A-Z]{1,5})', text)

        return {
            "sentiment": sentiment,
            "confidence": round(confidence, 2),
            "market_impact": "MEDIUM",
            "tickers": tickers[:5],
            "summary": "Basic keyword analysis (AI not connected). Connect Ollama for full analysis.",
            "action": "Review the post context manually for trading implications."
        }


# Singleton
_social_feed_service = None

def get_social_feed_service():
    return _social_feed_service

def init_social_feed_service(db):
    global _social_feed_service
    _social_feed_service = SocialFeedService(db)
    return _social_feed_service
