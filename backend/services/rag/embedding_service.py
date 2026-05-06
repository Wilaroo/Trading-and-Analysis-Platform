"""
Embedding Service - Converts text to vector embeddings

Uses sentence-transformers for high-quality embeddings.
Supports caching to avoid redundant computations.

Model: all-MiniLM-L6-v2 (fast, good quality, 384 dimensions)
"""

import logging
from typing import Optional, List, Dict, Any
import hashlib

logger = logging.getLogger(__name__)

# Global model instance (lazy loaded)
_embedding_model = None
_model_name = "all-MiniLM-L6-v2"


def get_embedding_model():
    """Get or initialize the embedding model (lazy loading)"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {_model_name}")
            _embedding_model = SentenceTransformer(_model_name)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    return _embedding_model


class EmbeddingService:
    """
    Generates embeddings for text using sentence-transformers.
    
    Features:
    - Lazy model loading (only loads when first needed)
    - Caching to avoid redundant computations
    - Batch processing for efficiency
    """
    
    def __init__(self):
        self._model = None
        self._cache: Dict[str, List[float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._max_cache_size = 10000
        
    def _get_model(self):
        """Get embedding model (lazy load)"""
        if self._model is None:
            self._model = get_embedding_model()
        return self._model
        
    def _cache_key(self, text: str) -> str:
        """Generate cache key for text"""
        return hashlib.md5(text.encode()).hexdigest()
        
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats (embedding vector)
        """
        if not text or not text.strip():
            return [0.0] * 384  # Return zero vector for empty text
            
        # Check cache
        cache_key = self._cache_key(text)
        if cache_key in self._cache:
            self._cache_hits += 1
            return self._cache[cache_key]
            
        self._cache_misses += 1
        
        try:
            model = self._get_model()
            embedding = model.encode(text, convert_to_numpy=True).tolist()
            
            # Add to cache (with size limit)
            if len(self._cache) < self._max_cache_size:
                self._cache[cache_key] = embedding
                
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return [0.0] * 384
            
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
            
        # Separate cached and uncached
        results = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []
        
        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = [0.0] * 384
                continue
                
            cache_key = self._cache_key(text)
            if cache_key in self._cache:
                self._cache_hits += 1
                results[i] = self._cache[cache_key]
            else:
                self._cache_misses += 1
                uncached_indices.append(i)
                uncached_texts.append(text)
                
        # Batch embed uncached texts
        if uncached_texts:
            try:
                model = self._get_model()
                embeddings = model.encode(uncached_texts, convert_to_numpy=True).tolist()
                
                for idx, (orig_idx, text) in enumerate(zip(uncached_indices, uncached_texts)):
                    embedding = embeddings[idx]
                    results[orig_idx] = embedding
                    
                    # Add to cache
                    if len(self._cache) < self._max_cache_size:
                        cache_key = self._cache_key(text)
                        self._cache[cache_key] = embedding
                        
            except Exception as e:
                logger.error(f"Error in batch embedding: {e}")
                # Fill remaining with zero vectors
                for idx in uncached_indices:
                    if results[idx] is None:
                        results[idx] = [0.0] * 384
                        
        return results
        
    def embed_trade_outcome(self, outcome: Dict) -> Dict[str, Any]:
        """
        Create embedding document from a trade outcome.
        
        Generates rich text representation including:
        - Setup type and direction
        - Entry/exit context
        - Market conditions
        - Execution quality
        - Result and lessons
        """
        # Build text representation
        parts = []
        
        # Basic trade info
        symbol = outcome.get("symbol", "")
        setup_type = outcome.get("setup_type", "unknown")
        direction = outcome.get("direction", "long")
        result = outcome.get("outcome", "unknown")
        pnl = outcome.get("pnl", 0)
        actual_r = outcome.get("actual_r", 0)
        
        parts.append(f"{setup_type} trade on {symbol} going {direction}")
        parts.append(f"Result: {result} with {actual_r:.2f}R (${pnl:.2f})")
        
        # Context
        context = outcome.get("context", {})
        if context:
            regime = context.get("market_regime", "unknown")
            time_of_day = context.get("time_of_day", "unknown")
            vix = context.get("vix_level", 0)
            sector = context.get("sector", "unknown")
            
            parts.append(f"Market: {regime} regime, {time_of_day}, VIX {vix:.1f}")
            parts.append(f"Sector: {sector}")
            
            # Technicals
            techs = context.get("technicals", {})
            if techs:
                rsi = techs.get("rsi", 50)
                rvol = techs.get("relative_volume", 1)
                parts.append(f"RSI: {rsi:.0f}, RVOL: {rvol:.1f}x")
                
            # Fundamentals
            funds = context.get("fundamentals", {})
            if funds:
                si = funds.get("short_interest_percent", 0)
                if si > 10:
                    parts.append(f"High short interest: {si:.1f}%")
                    
        # Execution
        execution = outcome.get("execution", {})
        if execution:
            slippage = execution.get("entry_slippage_percent", 0)
            r_capture = execution.get("r_capture_percent", 0)
            
            if abs(slippage) > 0.2:
                parts.append(f"Entry slippage: {slippage:.2f}%")
            if r_capture > 0:
                parts.append(f"R-capture: {r_capture:.0f}%")
                
        # Confirmation signals
        signals = outcome.get("confirmation_signals", [])
        if signals:
            parts.append(f"Confirmations: {', '.join(signals)}")
            
        # Create full text
        full_text = ". ".join(parts)
        
        # Generate embedding
        embedding = self.embed_text(full_text)
        
        return {
            "id": outcome.get("id", ""),
            "text": full_text,
            "embedding": embedding,
            "metadata": {
                "symbol": symbol,
                "setup_type": setup_type,
                "direction": direction,
                "outcome": result,
                "pnl": pnl,
                "actual_r": actual_r,
                "market_regime": context.get("market_regime", "unknown"),
                "time_of_day": context.get("time_of_day", "unknown"),
                "created_at": outcome.get("created_at", "")
            }
        }
        
    def embed_playbook(self, playbook: Dict) -> Dict[str, Any]:
        """
        Create embedding document from a playbook.
        """
        parts = []
        
        name = playbook.get("name", "")
        setup_type = playbook.get("setup_type", "")
        description = playbook.get("description", "")
        entry_rules = playbook.get("entry_rules", [])
        exit_rules = playbook.get("exit_rules", [])
        
        parts.append(f"Playbook: {name}")
        parts.append(f"Setup: {setup_type}")
        if description:
            parts.append(description)
        if entry_rules:
            parts.append(f"Entry rules: {'. '.join(entry_rules)}")
        if exit_rules:
            parts.append(f"Exit rules: {'. '.join(exit_rules)}")
            
        full_text = ". ".join(parts)
        embedding = self.embed_text(full_text)
        
        return {
            "id": playbook.get("id", ""),
            "text": full_text,
            "embedding": embedding,
            "metadata": {
                "name": name,
                "setup_type": setup_type,
                "type": "playbook"
            }
        }
        
    def embed_query(self, query: str, context: Dict = None) -> List[float]:
        """
        Create embedding for a user query with optional context.
        
        Args:
            query: User's question or search query
            context: Optional context (current symbol, setup, etc.)
            
        Returns:
            Embedding vector
        """
        # Enhance query with context if provided
        enhanced_query = query
        
        if context:
            context_parts = []
            if context.get("symbol"):
                context_parts.append(f"symbol: {context['symbol']}")
            if context.get("setup_type"):
                context_parts.append(f"setup: {context['setup_type']}")
            if context.get("market_regime"):
                context_parts.append(f"market: {context['market_regime']}")
                
            if context_parts:
                enhanced_query = f"{query} [{', '.join(context_parts)}]"
                
        return self.embed_text(enhanced_query)
        
    def get_stats(self) -> Dict[str, Any]:
        """Get embedding service statistics"""
        return {
            "model": _model_name,
            "cache_size": len(self._cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": self._cache_hits / (self._cache_hits + self._cache_misses) if (self._cache_hits + self._cache_misses) > 0 else 0
        }
        
    def clear_cache(self):
        """Clear the embedding cache"""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info("Embedding cache cleared")


# Singleton
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
