"""
FinBERT Sentiment Analysis + Finnhub News Collector
=====================================================
Phase 5c: Financial news sentiment scoring using ProsusAI/FinBERT.

Architecture:
    1. Finnhub Collector: Fetches ticker-tagged news, caches in MongoDB `news_articles` collection
    2. FinBERT Scorer: Runs ProsusAI/finbert on cached headlines/summaries
    3. Sentiment Aggregator: Computes per-symbol daily sentiment scores
    4. Confidence Gate (INACTIVE): Ready to wire as Layer 12 when user enables it

Data Flow:
    Finnhub API → MongoDB (news_articles) → FinBERT scoring → MongoDB (news_sentiment)
                                                                    ↓
                                                        Confidence Gate Layer 12 (disabled)

Collections:
    - news_articles: Raw articles from Finnhub {symbol, headline, summary, source, datetime, url}
    - news_sentiment: Scored articles {symbol, headline, sentiment, score, positive, negative, neutral}

Usage:
    # Collect news
    collector = FinnhubNewsCollector(db, api_key="your_key")
    await collector.collect_news(symbols=["AAPL", "TSLA"], days_back=30)

    # Score with FinBERT
    scorer = FinBERTSentiment(db)
    await scorer.score_unscored_articles(batch_size=100)

    # Get aggregated sentiment for a symbol
    sentiment = scorer.get_symbol_sentiment("AAPL", lookback_days=5)
"""

import logging
import time
import asyncio
import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# FinBERT labels in order of model output
FINBERT_LABELS = ["positive", "negative", "neutral"]


class FinnhubNewsCollector:
    """
    Collects financial news from Finnhub free tier and caches in MongoDB.

    Rate limits: 60 calls/min on free tier (shared across all Finnhub endpoints).
    Strategy: Batch by symbol, respect rate limits, deduplicate by article ID.
    """

    NEWS_COLLECTION = "news_articles"

    def __init__(self, db=None, api_key: str = None):
        self._db = db
        self._api_key = api_key
        self._client = None
        self._calls_this_minute = 0
        self._minute_start = time.time()

    def _get_client(self):
        """Lazy-init Finnhub client."""
        if self._client is None:
            try:
                import finnhub
                if not self._api_key:
                    import os
                    self._api_key = os.environ.get("FINNHUB_API_KEY", "")
                if not self._api_key:
                    raise ValueError("FINNHUB_API_KEY not set")
                self._client = finnhub.Client(api_key=self._api_key)
            except ImportError:
                raise ImportError("finnhub-python not installed: pip install finnhub-python")
        return self._client

    async def _rate_limit(self):
        """Respect Finnhub 60 calls/min rate limit."""
        now = time.time()
        if now - self._minute_start >= 60:
            self._calls_this_minute = 0
            self._minute_start = now

        if self._calls_this_minute >= 55:  # Leave headroom
            sleep_time = 60 - (now - self._minute_start) + 1
            logger.info(f"[FINNHUB] Rate limit approaching, sleeping {sleep_time:.0f}s")
            await asyncio.sleep(sleep_time)
            self._calls_this_minute = 0
            self._minute_start = time.time()

        self._calls_this_minute += 1

    def _ensure_indexes(self):
        """Create indexes for efficient querying."""
        if self._db is None:
            return
        col = self._db[self.NEWS_COLLECTION]
        col.create_index([("finnhub_id", 1)], unique=True, sparse=True)
        col.create_index([("symbol", 1), ("datetime", -1)])
        col.create_index([("scored", 1)])

    async def collect_news(
        self,
        symbols: List[str],
        days_back: int = 30,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Collect news articles from Finnhub for given symbols.

        Args:
            symbols: List of stock tickers
            days_back: How many days of history to fetch (max ~365 on free tier)
            progress_callback: Optional callback(symbol, articles_found)

        Returns:
            Summary dict with counts
        """
        client = self._get_client()
        self._ensure_indexes()

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        total_articles = 0
        total_new = 0
        total_dupes = 0
        errors = []

        for idx, symbol in enumerate(symbols):
            try:
                await self._rate_limit()

                # Run the blocking Finnhub call in a thread
                loop = asyncio.get_event_loop()
                articles = await loop.run_in_executor(
                    None,
                    lambda s=symbol: client.company_news(s, _from=start_str, to=end_str)
                )

                if not articles:
                    continue

                new_count = 0
                for article in articles:
                    # Deduplicate by Finnhub article ID
                    finnhub_id = str(article.get("id", ""))
                    if not finnhub_id:
                        continue

                    # Check if already exists
                    existing = self._db[self.NEWS_COLLECTION].find_one(
                        {"finnhub_id": finnhub_id}, {"_id": 1}
                    )
                    if existing:
                        total_dupes += 1
                        continue

                    # Parse datetime
                    article_ts = article.get("datetime", 0)
                    article_dt = datetime.fromtimestamp(article_ts, tz=timezone.utc) if article_ts else None

                    doc = {
                        "finnhub_id": finnhub_id,
                        "symbol": symbol,
                        "headline": article.get("headline", ""),
                        "summary": article.get("summary", ""),
                        "source": article.get("source", ""),
                        "url": article.get("url", ""),
                        "image": article.get("image", ""),
                        "category": article.get("category", ""),
                        "datetime": article_dt.isoformat() if article_dt else None,
                        "datetime_ts": article_ts,
                        "related": article.get("related", ""),
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "scored": False,
                        "sentiment": None,
                    }

                    try:
                        self._db[self.NEWS_COLLECTION].insert_one(doc)
                        new_count += 1
                    except Exception:
                        total_dupes += 1

                total_articles += len(articles)
                total_new += new_count

                if idx % 50 == 0:
                    logger.info(
                        f"[FINNHUB] Progress: {idx + 1}/{len(symbols)} symbols, "
                        f"{total_new} new articles, {total_dupes} dupes"
                    )

                if progress_callback:
                    progress_callback(symbol, len(articles))

            except Exception as e:
                errors.append(f"{symbol}: {e}")
                if "API limit" in str(e) or "429" in str(e):
                    logger.warning("[FINNHUB] Rate limited, waiting 60s...")
                    await asyncio.sleep(60)
                    self._calls_this_minute = 0
                    self._minute_start = time.time()

        result = {
            "success": True,
            "symbols_queried": len(symbols),
            "total_articles_found": total_articles,
            "new_articles_stored": total_new,
            "duplicates_skipped": total_dupes,
            "errors": errors[:10] if errors else None,
            "date_range": f"{start_str} to {end_str}",
        }

        logger.info(f"[FINNHUB] Collection complete: {total_new} new articles from {len(symbols)} symbols")
        return result

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get stats about the news collection."""
        if self._db is None:
            return {}

        col = self._db[self.NEWS_COLLECTION]
        total = col.estimated_document_count()
        unscored = col.count_documents({"scored": False})
        scored = col.count_documents({"scored": True})

        # Symbol coverage
        symbols = col.distinct("symbol")

        # Date range
        oldest = col.find_one({}, {"_id": 0, "datetime": 1}, sort=[("datetime_ts", 1)])
        newest = col.find_one({}, {"_id": 0, "datetime": 1}, sort=[("datetime_ts", -1)])

        return {
            "total_articles": total,
            "scored": scored,
            "unscored": unscored,
            "unique_symbols": len(symbols),
            "oldest_article": oldest.get("datetime") if oldest else None,
            "newest_article": newest.get("datetime") if newest else None,
        }

class YahooRSSNewsCollector:
    """
    Collects financial news from Yahoo Finance's free RSS feeds and writes
    them into the same `news_articles` collection as the Finnhub collector.

    Why Yahoo RSS:
        - No API key, no auth, no rate-limit quotas (unlike Finnhub's 60/min)
        - Covers mainstream press releases, analyst notes, earnings coverage
        - Complements Finnhub coverage — different editorial mix
        - 20-30 most recent headlines per ticker (latest ~7 days of news)

    Writes into the SAME collection as Finnhub so FinBERT scoring treats both
    sources uniformly. Deduplication is by article URL (Yahoo doesn't expose
    a stable article ID the way Finnhub does).
    """

    NEWS_COLLECTION = "news_articles"
    RSS_URL_TEMPLATE = "https://finance.yahoo.com/rss/headline?s={symbol}"
    # Be a polite client — Yahoo sometimes throttles obvious bot UAs.
    _HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SentComBot/1.0)"}

    def __init__(self, db=None):
        self._db = db

    def _ensure_indexes(self):
        if self._db is None:
            return
        col = self._db[self.NEWS_COLLECTION]
        # Yahoo articles are keyed by URL since there's no finnhub_id
        col.create_index([("url", 1)], unique=True, sparse=True)
        col.create_index([("symbol", 1), ("datetime_ts", -1)])
        col.create_index([("scored", 1)])

    async def collect_news(
        self,
        symbols: List[str],
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Collect RSS headlines for each symbol. Returns summary dict."""
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed; cannot collect Yahoo RSS")
            return {"success": False, "error": "feedparser not installed"}

        self._ensure_indexes()
        total_articles = 0
        total_new = 0
        total_dupes = 0
        errors = []

        for idx, symbol in enumerate(symbols):
            try:
                url = self.RSS_URL_TEMPLATE.format(symbol=symbol.upper())
                # feedparser blocks on network — run in thread
                loop = asyncio.get_event_loop()
                feed = await loop.run_in_executor(
                    None,
                    lambda u=url: feedparser.parse(u, request_headers=self._HEADERS),
                )

                entries = getattr(feed, "entries", []) or []
                if not entries:
                    continue

                new_count = 0
                for entry in entries:
                    link = getattr(entry, "link", "") or ""
                    if not link:
                        continue

                    # Dedup against existing articles (from Yahoo OR Finnhub)
                    if self._db[self.NEWS_COLLECTION].find_one({"url": link}, {"_id": 1}):
                        total_dupes += 1
                        continue

                    # Yahoo RSS gives `published_parsed` as a time.struct_time
                    pub = getattr(entry, "published_parsed", None)
                    if pub:
                        try:
                            article_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                        except Exception:
                            article_dt = datetime.now(timezone.utc)
                    else:
                        article_dt = datetime.now(timezone.utc)

                    doc = {
                        "source_feed": "yahoo_rss",
                        "symbol": symbol.upper(),
                        "headline": getattr(entry, "title", "") or "",
                        "summary": getattr(entry, "summary", "") or "",
                        "source": "yahoo",
                        "url": link,
                        "datetime": article_dt.isoformat(),
                        "datetime_ts": article_dt.timestamp(),
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "scored": False,
                    }
                    try:
                        self._db[self.NEWS_COLLECTION].insert_one(doc)
                        new_count += 1
                        total_new += 1
                    except Exception as e:
                        # Race or dupe from another concurrent insert — safe to skip
                        if "duplicate key" not in str(e).lower():
                            logger.debug(f"Yahoo insert skipped for {symbol}: {e}")

                total_articles += len(entries)
                if progress_callback:
                    try:
                        progress_callback(symbol, new_count)
                    except Exception:
                        pass

                # Tiny courtesy pause every 50 symbols — avoids Yahoo throttling
                if (idx + 1) % 50 == 0:
                    await asyncio.sleep(1)

            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
                logger.warning(f"[YAHOO-RSS] Failed for {symbol}: {e}")

        logger.info(
            f"[YAHOO-RSS] Collection complete: {total_new} new, "
            f"{total_dupes} duplicate, {len(errors)} errors from {len(symbols)} symbols"
        )
        return {
            "success": True,
            "source": "yahoo_rss",
            "total_seen": total_articles,
            "new_articles": total_new,
            "duplicates": total_dupes,
            "errors": len(errors),
            "symbols_processed": len(symbols),
        }




class FinBERTSentiment:
    """
    FinBERT sentiment scorer using ProsusAI/finbert from HuggingFace.

    Scores news articles as positive/negative/neutral with confidence scores.
    Results cached in MongoDB for fast lookup during trading decisions.
    """

    MODEL_NAME = "ProsusAI/finbert"
    NEWS_COLLECTION = "news_articles"
    SENTIMENT_COLLECTION = "news_sentiment"

    def __init__(self, db=None):
        self._db = db
        self._model = None
        self._tokenizer = None
        self._device = None
        self._loaded = False

    def _load_model(self):
        """Load FinBERT model and tokenizer (lazy — first call only)."""
        if self._loaded:
            return

        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification

            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"[FinBERT] Loading {self.MODEL_NAME} on {self._device}...")

            self._tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.MODEL_NAME)
            self._model.to(self._device)
            self._model.eval()

            self._loaded = True
            logger.info(f"[FinBERT] Model loaded successfully on {self._device}")

        except ImportError:
            raise ImportError("transformers not installed: pip install transformers torch")
        except Exception as e:
            logger.error(f"[FinBERT] Failed to load model: {e}")
            raise

    def score_text(self, text: str) -> Dict[str, float]:
        """
        Score a single text with FinBERT.

        Returns:
            {"sentiment": "positive", "score": 0.85, "positive": 0.92, "negative": 0.03, "neutral": 0.05}
        """
        import torch

        self._load_model()

        inputs = self._tokenizer(
            text, return_tensors="pt", truncation=True,
            padding=True, max_length=512
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1).cpu().numpy()[0]

        sentiment_idx = int(np.argmax(probs))
        sentiment = FINBERT_LABELS[sentiment_idx]
        score = float(probs[0] - probs[1])  # positive - negative

        return {
            "sentiment": sentiment,
            "score": score,
            "positive": float(probs[0]),
            "negative": float(probs[1]),
            "neutral": float(probs[2]),
        }

    def score_batch(self, texts: List[str], batch_size: int = 32) -> List[Dict[str, float]]:
        """
        Score a batch of texts efficiently.
        """
        import torch

        self._load_model()
        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            inputs = self._tokenizer(
                batch, return_tensors="pt", truncation=True,
                padding=True, max_length=512
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1).cpu().numpy()

            for p in probs:
                sentiment_idx = int(np.argmax(p))
                results.append({
                    "sentiment": FINBERT_LABELS[sentiment_idx],
                    "score": float(p[0] - p[1]),
                    "positive": float(p[0]),
                    "negative": float(p[1]),
                    "neutral": float(p[2]),
                })

        return results

    async def score_unscored_articles(self, batch_size: int = 100, max_articles: int = 10000) -> Dict[str, Any]:
        """
        Score all unscored articles in the news_articles collection.
        Writes sentiment back to the article doc AND to the news_sentiment collection.
        """
        if self._db is None:
            return {"success": False, "error": "No database"}

        # Ensure indexes
        self._db[self.SENTIMENT_COLLECTION].create_index([("symbol", 1), ("datetime", -1)])
        self._db[self.SENTIMENT_COLLECTION].create_index([("symbol", 1), ("date", 1)])

        # Fetch unscored articles
        cursor = self._db[self.NEWS_COLLECTION].find(
            {"scored": False, "headline": {"$ne": ""}},
            {"_id": 0, "finnhub_id": 1, "symbol": 1, "headline": 1, "summary": 1, "datetime": 1, "source": 1}
        ).limit(max_articles)

        articles = list(cursor)
        if not articles:
            return {"success": True, "scored": 0, "message": "No unscored articles"}

        logger.info(f"[FinBERT] Scoring {len(articles)} articles...")

        # Build texts: use headline + summary for better context
        texts = []
        for a in articles:
            headline = a.get("headline", "")
            summary = a.get("summary", "")
            text = f"{headline}. {summary}" if summary else headline
            texts.append(text[:512])  # FinBERT max length

        # Score in batches
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(
            None,
            lambda: self.score_batch(texts, batch_size=batch_size)
        )

        # Write scores back
        scored_count = 0
        for article, score_data in zip(articles, scores):
            finnhub_id = article.get("finnhub_id")
            symbol = article.get("symbol", "")

            # Update original article
            self._db[self.NEWS_COLLECTION].update_one(
                {"finnhub_id": finnhub_id},
                {"$set": {
                    "scored": True,
                    "sentiment": score_data,
                    "scored_at": datetime.now(timezone.utc).isoformat(),
                }}
            )

            # Also write to sentiment collection for fast aggregation
            article_dt = article.get("datetime", "")
            date_str = article_dt[:10] if article_dt else ""

            self._db[self.SENTIMENT_COLLECTION].update_one(
                {"finnhub_id": finnhub_id},
                {"$set": {
                    "finnhub_id": finnhub_id,
                    "symbol": symbol,
                    "headline": article.get("headline", ""),
                    "source": article.get("source", ""),
                    "datetime": article_dt,
                    "date": date_str,
                    **score_data,
                    "scored_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True
            )
            scored_count += 1

        # Log distribution
        sentiments = [s["sentiment"] for s in scores]
        dist = {s: sentiments.count(s) for s in set(sentiments)}
        avg_score = np.mean([s["score"] for s in scores])

        logger.info(
            f"[FinBERT] Scored {scored_count} articles — "
            f"distribution: {dist}, avg_score: {avg_score:.3f}"
        )

        return {
            "success": True,
            "scored": scored_count,
            "distribution": dist,
            "average_score": float(avg_score),
        }

    def get_symbol_sentiment(
        self,
        symbol: str,
        lookback_days: int = 5,
        min_articles: int = 3
    ) -> Dict[str, Any]:
        """
        Get aggregated sentiment for a symbol over recent days.

        This is what the Confidence Gate would call (when enabled).

        Returns:
            {
                "symbol": "AAPL",
                "sentiment": "positive",
                "score": 0.42,        # avg positive - negative
                "confidence": 0.78,    # how consistent the sentiment is
                "article_count": 12,
                "positive_pct": 0.67,
                "negative_pct": 0.17,
                "neutral_pct": 0.17,
                "has_sentiment": True,
            }
        """
        if self._db is None:
            return {"has_sentiment": False, "symbol": symbol}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        articles = list(self._db[self.SENTIMENT_COLLECTION].find(
            {"symbol": symbol, "datetime": {"$gte": cutoff}},
            {"_id": 0, "sentiment": 1, "score": 1, "positive": 1, "negative": 1, "neutral": 1}
        ))

        if len(articles) < min_articles:
            return {"has_sentiment": False, "symbol": symbol, "article_count": len(articles)}

        scores = [a["score"] for a in articles]
        sentiments = [a["sentiment"] for a in articles]

        n = len(articles)
        avg_score = float(np.mean(scores))
        score_std = float(np.std(scores))

        positive_pct = sentiments.count("positive") / n
        negative_pct = sentiments.count("negative") / n
        neutral_pct = sentiments.count("neutral") / n

        # Determine overall sentiment
        if avg_score > 0.15:
            overall = "positive"
        elif avg_score < -0.15:
            overall = "negative"
        else:
            overall = "neutral"

        # Confidence: higher when articles agree (low std), lower when mixed
        confidence = max(0.0, min(1.0, 1.0 - score_std))

        return {
            "has_sentiment": True,
            "symbol": symbol,
            "sentiment": overall,
            "score": avg_score,
            "confidence": confidence,
            "article_count": n,
            "positive_pct": positive_pct,
            "negative_pct": negative_pct,
            "neutral_pct": neutral_pct,
        }

    def get_market_sentiment(self, lookback_days: int = 3) -> Dict[str, Any]:
        """
        Get broad market sentiment across all symbols.
        Useful for regime overlay.
        """
        if self._db is None:
            return {"has_sentiment": False}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        pipeline = [
            {"$match": {"datetime": {"$gte": cutoff}}},
            {"$group": {
                "_id": None,
                "avg_score": {"$avg": "$score"},
                "count": {"$sum": 1},
                "positive_count": {"$sum": {"$cond": [{"$eq": ["$sentiment", "positive"]}, 1, 0]}},
                "negative_count": {"$sum": {"$cond": [{"$eq": ["$sentiment", "negative"]}, 1, 0]}},
                "neutral_count": {"$sum": {"$cond": [{"$eq": ["$sentiment", "neutral"]}, 1, 0]}},
            }},
        ]

        result = list(self._db[self.SENTIMENT_COLLECTION].aggregate(pipeline))
        if not result:
            return {"has_sentiment": False}

        r = result[0]
        n = r["count"]
        return {
            "has_sentiment": True,
            "market_score": r["avg_score"],
            "article_count": n,
            "positive_pct": r["positive_count"] / n if n > 0 else 0,
            "negative_pct": r["negative_count"] / n if n > 0 else 0,
            "neutral_pct": r["neutral_count"] / n if n > 0 else 0,
            "lookback_days": lookback_days,
        }
