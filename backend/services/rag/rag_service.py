"""
RAG Service - Retrieval-Augmented Generation for Trading AI

The main service that orchestrates:
1. Indexing: Converting trade data to embeddings and storing in ChromaDB
2. Retrieval: Finding relevant context for AI prompts
3. Augmentation: Injecting personalized context into AI conversations

Features:
- Auto-sync from MongoDB on startup
- Incremental updates as new trades complete
- Multi-collection search (trades, playbooks, patterns)
- Context relevance scoring
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

from services.rag.embedding_service import get_embedding_service, EmbeddingService
from services.rag.vector_store import get_vector_store_service, VectorStoreService

logger = logging.getLogger(__name__)


class RAGService:
    """
    Retrieval-Augmented Generation service for personalized AI context.
    
    Usage:
    1. On startup, sync from MongoDB to ChromaDB
    2. On trade completion, index the new trade
    3. Before AI prompt, retrieve relevant context
    4. Inject context into the prompt
    """
    
    # Context template for AI injection
    CONTEXT_TEMPLATE = """
Based on your trading history, here's personalized context:

{context}

Use this information to provide specific, actionable advice tailored to the trader's actual performance and patterns.
"""
    
    def __init__(self):
        self._embedding_service: Optional[EmbeddingService] = None
        self._vector_store: Optional[VectorStoreService] = None
        self._db = None
        self._learning_loop = None
        
        self._last_sync: Optional[datetime] = None
        self._sync_in_progress = False
        
    def set_services(
        self,
        db=None,
        learning_loop=None
    ):
        """Wire up dependencies"""
        self._db = db
        self._learning_loop = learning_loop
        
        # Initialize embedding and vector store services
        self._embedding_service = get_embedding_service()
        self._vector_store = get_vector_store_service()
        
    def initialize(self):
        """Initialize the RAG service"""
        if self._vector_store:
            self._vector_store.initialize()
            logger.info("RAG service initialized")
            
    async def sync_from_mongodb(self, force: bool = False) -> Dict[str, Any]:
        """
        Sync data from MongoDB to ChromaDB.
        
        Called on startup or when switching machines.
        
        Args:
            force: If True, rebuild even if recently synced
            
        Returns:
            Sync statistics
        """
        if self._sync_in_progress:
            return {"status": "in_progress", "message": "Sync already in progress"}
            
        # Check if sync is needed
        if not force and self._last_sync:
            time_since_sync = datetime.now(timezone.utc) - self._last_sync
            if time_since_sync < timedelta(hours=1):
                return {
                    "status": "skipped",
                    "message": f"Recently synced {time_since_sync.seconds // 60} minutes ago"
                }
                
        self._sync_in_progress = True
        stats = {
            "trades_indexed": 0,
            "playbooks_indexed": 0,
            "patterns_indexed": 0,
            "errors": [],
            "duration_seconds": 0
        }
        
        start_time = datetime.now()
        
        try:
            # 1. Sync trade outcomes
            if self._db is not None:
                await self._sync_trade_outcomes(stats)
                
            # 2. Sync playbooks
            if self._db is not None:
                await self._sync_playbooks(stats)
                
            # 3. Sync daily insights
            if self._db is not None:
                await self._sync_daily_insights(stats)
                
            self._last_sync = datetime.now(timezone.utc)
            
        except Exception as e:
            logger.error(f"Sync error: {e}")
            stats["errors"].append(str(e))
            
        finally:
            self._sync_in_progress = False
            stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()
            
        logger.info(f"RAG sync complete: {stats['trades_indexed']} trades, {stats['playbooks_indexed']} playbooks")
        
        return stats
        
    async def _sync_trade_outcomes(self, stats: Dict):
        """Sync trade outcomes from MongoDB"""
        try:
            trade_outcomes_col = self._db["trade_outcomes"]
            
            # Get all trades from MongoDB
            trades = list(trade_outcomes_col.find({}).sort("created_at", -1).limit(1000))
            
            if not trades:
                return
                
            # Process in batches
            batch_size = 50
            documents = []
            
            for trade in trades:
                trade_dict = dict(trade)
                trade_dict.pop("_id", None)
                
                # Create embedding document
                doc = self._embedding_service.embed_trade_outcome(trade_dict)
                doc["id"] = trade_dict.get("id", str(trade.get("_id", "")))
                documents.append(doc)
                
                if len(documents) >= batch_size:
                    self._vector_store.add_documents_batch("trade_outcomes", documents)
                    stats["trades_indexed"] += len(documents)
                    documents = []
                    
            # Add remaining
            if documents:
                self._vector_store.add_documents_batch("trade_outcomes", documents)
                stats["trades_indexed"] += len(documents)
                
        except Exception as e:
            logger.error(f"Error syncing trade outcomes: {e}")
            stats["errors"].append(f"Trade sync: {str(e)}")
            
    async def _sync_playbooks(self, stats: Dict):
        """Sync playbooks from MongoDB"""
        try:
            playbooks_col = self._db["playbooks"]
            
            playbooks = list(playbooks_col.find({}))
            
            if not playbooks:
                return
                
            documents = []
            for playbook in playbooks:
                playbook_dict = dict(playbook)
                playbook_dict.pop("_id", None)
                
                doc = self._embedding_service.embed_playbook(playbook_dict)
                doc["id"] = playbook_dict.get("id", str(playbook.get("_id", "")))
                documents.append(doc)
                
            if documents:
                self._vector_store.add_documents_batch("playbooks", documents)
                stats["playbooks_indexed"] = len(documents)
                
        except Exception as e:
            logger.error(f"Error syncing playbooks: {e}")
            stats["errors"].append(f"Playbook sync: {str(e)}")
            
    async def _sync_daily_insights(self, stats: Dict):
        """Sync daily report card insights"""
        try:
            drc_col = self._db["daily_report_cards"]
            
            # Get recent DRCs
            drcs = list(drc_col.find({}).sort("date", -1).limit(30))
            
            if not drcs:
                return
                
            documents = []
            for drc in drcs:
                drc_dict = dict(drc)
                drc_dict.pop("_id", None)
                
                # Extract key insights
                parts = []
                date = drc_dict.get("date", "")
                parts.append(f"Daily Report Card for {date}")
                
                if drc_dict.get("market_summary"):
                    parts.append(f"Market: {drc_dict['market_summary']}")
                if drc_dict.get("what_worked"):
                    parts.append(f"What worked: {drc_dict['what_worked']}")
                if drc_dict.get("what_didnt_work"):
                    parts.append(f"What didn't work: {drc_dict['what_didnt_work']}")
                if drc_dict.get("lessons_learned"):
                    parts.append(f"Lessons: {drc_dict['lessons_learned']}")
                    
                text = ". ".join(parts)
                embedding = self._embedding_service.embed_text(text)
                
                documents.append({
                    "id": drc_dict.get("id", date),
                    "text": text,
                    "embedding": embedding,
                    "metadata": {
                        "date": date,
                        "type": "daily_report_card",
                        "market_regime": drc_dict.get("market_regime", "unknown")
                    }
                })
                
            if documents:
                self._vector_store.add_documents_batch("daily_insights", documents)
                
        except Exception as e:
            logger.error(f"Error syncing daily insights: {e}")
            
    async def index_trade_outcome(self, outcome: Dict):
        """
        Index a single trade outcome (called after trade completion).
        
        Args:
            outcome: Trade outcome dictionary
        """
        try:
            doc = self._embedding_service.embed_trade_outcome(outcome)
            doc["id"] = outcome.get("id", "")
            
            self._vector_store.add_document(
                collection_name="trade_outcomes",
                doc_id=doc["id"],
                text=doc["text"],
                embedding=doc["embedding"],
                metadata=doc["metadata"]
            )
            
            logger.debug(f"Indexed trade outcome: {outcome.get('symbol')} {outcome.get('setup_type')}")
            
        except Exception as e:
            logger.error(f"Error indexing trade outcome: {e}")
            
    async def retrieve_context(
        self,
        query: str,
        context: Dict = None,
        n_results: int = 5,
        collections: List[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve relevant context for an AI prompt.
        
        Args:
            query: User's question or current context
            context: Additional context (symbol, setup_type, etc.)
            n_results: Number of results per collection
            collections: Which collections to search (default: all)
            
        Returns:
            Dict with relevant context and metadata
        """
        if collections is None:
            collections = ["trade_outcomes", "playbooks", "daily_insights"]
            
        # Generate query embedding
        query_embedding = self._embedding_service.embed_query(query, context)
        
        all_results = []
        
        for collection in collections:
            try:
                # Build filters based on context
                where_filter = None
                if context:
                    if context.get("setup_type") and collection == "trade_outcomes":
                        where_filter = {"setup_type": context["setup_type"]}
                    elif context.get("symbol") and collection == "trade_outcomes":
                        where_filter = {"symbol": context["symbol"]}
                        
                results = self._vector_store.search(
                    collection_name=collection,
                    query_embedding=query_embedding,
                    n_results=n_results,
                    where=where_filter
                )
                
                for r in results:
                    r["collection"] = collection
                    all_results.append(r)
                    
            except Exception as e:
                logger.error(f"Error searching {collection}: {e}")
                
        # Sort by similarity
        all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        
        return {
            "results": all_results[:n_results * 2],  # Return top results across collections
            "query": query,
            "context": context,
            "total_found": len(all_results)
        }
        
    async def get_similar_trades(
        self,
        symbol: str = None,
        setup_type: str = None,
        market_regime: str = None,
        n_results: int = 10
    ) -> List[Dict]:
        """
        Find similar historical trades.
        
        Args:
            symbol: Filter by symbol
            setup_type: Filter by setup type
            market_regime: Filter by market regime
            n_results: Number of results
            
        Returns:
            List of similar trades with context
        """
        # Build query text
        parts = []
        if setup_type:
            parts.append(f"{setup_type} trade")
        if symbol:
            parts.append(f"on {symbol}")
        if market_regime:
            parts.append(f"in {market_regime} market")
            
        query = " ".join(parts) if parts else "recent trade"
        
        # Build filter
        where_filter = {}
        if setup_type:
            where_filter["setup_type"] = setup_type
        if market_regime:
            where_filter["market_regime"] = market_regime
            
        query_embedding = self._embedding_service.embed_text(query)
        
        results = self._vector_store.search(
            collection_name="trade_outcomes",
            query_embedding=query_embedding,
            n_results=n_results,
            where=where_filter if where_filter else None
        )
        
        return results
        
    def generate_ai_context(
        self,
        results: List[Dict],
        max_tokens: int = 1000
    ) -> str:
        """
        Generate context string for AI prompt injection.
        
        Args:
            results: Retrieved results from search
            max_tokens: Approximate token limit
            
        Returns:
            Formatted context string
        """
        if not results:
            return ""
            
        context_parts = []
        char_limit = max_tokens * 4  # Rough chars to tokens
        current_chars = 0
        
        # Group by collection
        trades = [r for r in results if r.get("collection") == "trade_outcomes"]
        playbooks = [r for r in results if r.get("collection") == "playbooks"]
        insights = [r for r in results if r.get("collection") == "daily_insights"]
        
        # Add trade context
        if trades:
            context_parts.append("**Similar Historical Trades:**")
            for t in trades[:5]:
                text = t.get("text", "")
                outcome = t.get("metadata", {}).get("outcome", "")
                pnl = t.get("metadata", {}).get("pnl", 0)
                
                line = f"- {text} (Result: {outcome}, ${pnl:.0f})"
                if current_chars + len(line) > char_limit:
                    break
                context_parts.append(line)
                current_chars += len(line)
                
        # Add playbook context
        if playbooks and current_chars < char_limit * 0.8:
            context_parts.append("\n**Relevant Playbooks:**")
            for p in playbooks[:2]:
                text = p.get("text", "")[:200]
                context_parts.append(f"- {text}")
                current_chars += len(text)
                
        # Add insight context
        if insights and current_chars < char_limit * 0.9:
            context_parts.append("\n**Recent Insights:**")
            for i in insights[:2]:
                text = i.get("text", "")[:150]
                context_parts.append(f"- {text}")
                
        if not context_parts:
            return ""
            
        context = "\n".join(context_parts)
        return self.CONTEXT_TEMPLATE.format(context=context)
        
    async def augment_prompt(
        self,
        user_message: str,
        current_context: Dict = None
    ) -> str:
        """
        Augment a user message with relevant context for the AI.
        
        Args:
            user_message: Original user message
            current_context: Current trading context (symbol, setup, etc.)
            
        Returns:
            Augmented prompt with RAG context
        """
        # Retrieve relevant context
        retrieval = await self.retrieve_context(
            query=user_message,
            context=current_context,
            n_results=5
        )
        
        results = retrieval.get("results", [])
        
        if not results:
            return user_message
            
        # Generate context injection
        context_str = self.generate_ai_context(results)
        
        if not context_str:
            return user_message
            
        # Combine context with user message
        augmented = f"{context_str}\n\n**User Question:** {user_message}"
        
        return augmented
        
    def get_stats(self) -> Dict[str, Any]:
        """Get RAG service statistics"""
        embedding_stats = self._embedding_service.get_stats() if self._embedding_service else {}
        vector_stats = self._vector_store.get_stats() if self._vector_store else {}
        
        return {
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "sync_in_progress": self._sync_in_progress,
            "embedding_service": embedding_stats,
            "vector_store": vector_stats
        }
        
    def needs_sync(self) -> bool:
        """Check if sync is needed (for auto-rebuild)"""
        if self._last_sync is None:
            return True
            
        # Check if vector store is empty
        if self._vector_store:
            counts = self._vector_store.get_all_counts()
            if sum(counts.values()) == 0:
                return True
                
        # Check if sync is stale (> 24 hours)
        time_since_sync = datetime.now(timezone.utc) - self._last_sync
        if time_since_sync > timedelta(hours=24):
            return True
            
        return False


# Singleton
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


def init_rag_service(db=None, learning_loop=None) -> RAGService:
    service = get_rag_service()
    service.set_services(db=db, learning_loop=learning_loop)
    service.initialize()
    return service
