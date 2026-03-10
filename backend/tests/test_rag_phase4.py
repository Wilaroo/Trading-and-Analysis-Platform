"""
RAG (Retrieval-Augmented Generation) API Tests - Phase 4

Tests the RAG Knowledge Base endpoints for personalized AI context:
- GET /api/rag/stats - RAG service statistics
- GET /api/rag/needs-sync - Check if sync is needed
- POST /api/rag/sync - Sync data from MongoDB to ChromaDB
- POST /api/rag/retrieve - Retrieve relevant context for a query
- POST /api/rag/augment-prompt - Augment user message with RAG context
- POST /api/rag/similar-trades - Find similar historical trades
- GET /api/rag/collections - Get collection information
- GET /api/rag/embedding-stats - Get embedding cache statistics
- POST /api/rag/clear-cache - Clear embedding cache
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestRAGStats:
    """Test RAG service statistics endpoint"""
    
    def test_get_rag_stats_success(self):
        """GET /api/rag/stats - Should return RAG service statistics"""
        response = requests.get(f"{BASE_URL}/api/rag/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "stats" in data
        
        stats = data["stats"]
        assert "last_sync" in stats
        assert "sync_in_progress" in stats
        assert isinstance(stats["sync_in_progress"], bool)
        
        # Embedding service stats
        assert "embedding_service" in stats
        embedding_stats = stats["embedding_service"]
        assert embedding_stats["model"] == "all-MiniLM-L6-v2"
        assert "cache_size" in embedding_stats
        assert "cache_hits" in embedding_stats
        assert "cache_misses" in embedding_stats
        assert "hit_rate" in embedding_stats
        
        # Vector store stats
        assert "vector_store" in stats
        vector_stats = stats["vector_store"]
        assert vector_stats["persist_directory"] == "/app/backend/data/chromadb"
        assert "collections" in vector_stats
        assert "document_counts" in vector_stats
        assert "total_documents" in vector_stats


class TestRAGNeedsSync:
    """Test needs-sync endpoint"""
    
    def test_needs_sync_returns_boolean(self):
        """GET /api/rag/needs-sync - Should return sync status"""
        response = requests.get(f"{BASE_URL}/api/rag/needs-sync")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "needs_sync" in data
        assert isinstance(data["needs_sync"], bool)


class TestRAGSync:
    """Test sync endpoint"""
    
    def test_sync_force_true(self):
        """POST /api/rag/sync?force=true - Should perform sync immediately"""
        response = requests.post(f"{BASE_URL}/api/rag/sync?force=true")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "result" in data
        
        result = data["result"]
        assert "trades_indexed" in result
        assert "playbooks_indexed" in result
        assert "patterns_indexed" in result
        assert "errors" in result
        assert "duration_seconds" in result
        
        # Should have numeric values
        assert isinstance(result["trades_indexed"], int)
        assert isinstance(result["playbooks_indexed"], int)
        assert isinstance(result["duration_seconds"], (int, float))
    
    def test_sync_background(self):
        """POST /api/rag/sync - Should start sync in background"""
        response = requests.post(f"{BASE_URL}/api/rag/sync")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        # Either returns message (background) or result (if recently synced)
        assert "message" in data or "result" in data


class TestRAGRetrieve:
    """Test context retrieval endpoint"""
    
    def test_retrieve_context_basic(self):
        """POST /api/rag/retrieve - Should retrieve context for query"""
        payload = {
            "query": "momentum breakout setup",
            "n_results": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "retrieval" in data
        
        retrieval = data["retrieval"]
        assert "results" in retrieval
        assert "query" in retrieval
        assert retrieval["query"] == "momentum breakout setup"
        assert "total_found" in retrieval
        
        # Results should be a list
        assert isinstance(retrieval["results"], list)
    
    def test_retrieve_with_context(self):
        """POST /api/rag/retrieve - Should handle context filtering"""
        payload = {
            "query": "how did this setup perform",
            "context": {
                "symbol": "AAPL",
                "setup_type": "momentum_breakout"
            },
            "n_results": 3
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["retrieval"]["context"] == payload["context"]
    
    def test_retrieve_with_collections_filter(self):
        """POST /api/rag/retrieve - Should filter by collections"""
        payload = {
            "query": "trading strategy",
            "n_results": 5,
            "collections": ["playbooks"]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        # All results should be from playbooks collection
        for result in data["retrieval"]["results"]:
            if result.get("collection"):
                assert result["collection"] == "playbooks"


class TestRAGAugmentPrompt:
    """Test prompt augmentation endpoint"""
    
    def test_augment_prompt_basic(self):
        """POST /api/rag/augment-prompt - Should augment user message"""
        payload = {
            "user_message": "How should I trade momentum breakouts?"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/augment-prompt",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "original_message" in data
        assert "augmented_prompt" in data
        assert "was_augmented" in data
        
        assert data["original_message"] == payload["user_message"]
        assert isinstance(data["was_augmented"], bool)
        
        # If augmented, the prompt should be longer
        if data["was_augmented"]:
            assert len(data["augmented_prompt"]) > len(data["original_message"])
            assert "User Question:" in data["augmented_prompt"]
    
    def test_augment_prompt_with_context(self):
        """POST /api/rag/augment-prompt - Should use context for retrieval"""
        payload = {
            "user_message": "What's my win rate for this setup?",
            "current_context": {
                "symbol": "NVDA",
                "setup_type": "gap_and_go"
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/augment-prompt",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["original_message"] == payload["user_message"]


class TestRAGSimilarTrades:
    """Test similar trades endpoint"""
    
    def test_similar_trades_by_setup_type(self):
        """POST /api/rag/similar-trades - Should find similar trades by setup"""
        payload = {
            "setup_type": "momentum_breakout",
            "n_results": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/similar-trades",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "similar_trades" in data
        assert "count" in data
        
        assert isinstance(data["similar_trades"], list)
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["similar_trades"])
    
    def test_similar_trades_by_symbol(self):
        """POST /api/rag/similar-trades - Should find similar trades by symbol"""
        payload = {
            "symbol": "AAPL",
            "n_results": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/similar-trades",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "similar_trades" in data
    
    def test_similar_trades_by_market_regime(self):
        """POST /api/rag/similar-trades - Should filter by market regime"""
        payload = {
            "market_regime": "bullish",
            "n_results": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/similar-trades",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
    
    def test_similar_trades_combined_filters(self):
        """POST /api/rag/similar-trades - Should handle multiple filters"""
        payload = {
            "symbol": "TSLA",
            "setup_type": "gap_and_go",
            "market_regime": "volatile",
            "n_results": 3
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/similar-trades",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True


class TestRAGCollections:
    """Test collections info endpoint"""
    
    def test_get_collections_info(self):
        """GET /api/rag/collections - Should return collection information"""
        response = requests.get(f"{BASE_URL}/api/rag/collections")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "collections" in data
        
        collections = data["collections"]
        
        # Should have 4 collections
        expected_collections = ["trade_outcomes", "playbooks", "patterns", "daily_insights"]
        for col_name in expected_collections:
            assert col_name in collections
            assert "description" in collections[col_name]
            assert "metadata_fields" in collections[col_name]
        
        # Verify trade_outcomes metadata fields
        trade_fields = collections["trade_outcomes"]["metadata_fields"]
        assert "symbol" in trade_fields
        assert "setup_type" in trade_fields
        assert "direction" in trade_fields
        assert "outcome" in trade_fields


class TestRAGEmbeddingStats:
    """Test embedding statistics endpoint"""
    
    def test_get_embedding_stats(self):
        """GET /api/rag/embedding-stats - Should return embedding stats"""
        response = requests.get(f"{BASE_URL}/api/rag/embedding-stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "stats" in data
        
        stats = data["stats"]
        assert stats["model"] == "all-MiniLM-L6-v2"
        assert "cache_size" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "hit_rate" in stats
        
        # Hit rate should be between 0 and 1
        assert 0 <= stats["hit_rate"] <= 1


class TestRAGClearCache:
    """Test clear cache endpoint"""
    
    def test_clear_embedding_cache(self):
        """POST /api/rag/clear-cache - Should clear embedding cache"""
        response = requests.post(f"{BASE_URL}/api/rag/clear-cache")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["message"] == "Embedding cache cleared"
        
        # Verify cache was cleared by checking stats
        stats_response = requests.get(f"{BASE_URL}/api/rag/embedding-stats")
        stats_data = stats_response.json()
        
        assert stats_data["stats"]["cache_size"] == 0
        assert stats_data["stats"]["cache_hits"] == 0
        assert stats_data["stats"]["cache_misses"] == 0


class TestRAGIntegration:
    """Integration tests for RAG workflow"""
    
    def test_full_rag_workflow(self):
        """Test complete RAG workflow: sync -> retrieve -> augment"""
        # Step 1: Sync (force to ensure fresh data)
        sync_response = requests.post(f"{BASE_URL}/api/rag/sync?force=true")
        assert sync_response.status_code == 200
        assert sync_response.json()["success"] is True
        
        # Step 2: Check stats
        stats_response = requests.get(f"{BASE_URL}/api/rag/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()["stats"]
        assert stats["sync_in_progress"] is False
        
        # Step 3: Retrieve context
        retrieve_payload = {
            "query": "best momentum setups",
            "n_results": 5
        }
        retrieve_response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=retrieve_payload
        )
        assert retrieve_response.status_code == 200
        
        # Step 4: Augment prompt
        augment_payload = {
            "user_message": "What are my best performing setups?"
        }
        augment_response = requests.post(
            f"{BASE_URL}/api/rag/augment-prompt",
            json=augment_payload
        )
        assert augment_response.status_code == 200
        augment_data = augment_response.json()
        
        assert augment_data["success"] is True
        assert augment_data["original_message"] == augment_payload["user_message"]
    
    def test_embedding_model_performance(self):
        """Test that embedding model handles multiple queries efficiently"""
        queries = [
            "momentum breakout on AAPL",
            "gap and go setup for TSLA",
            "reversal pattern in volatile market",
            "high short interest squeeze"
        ]
        
        for query in queries:
            payload = {"query": query, "n_results": 3}
            response = requests.post(
                f"{BASE_URL}/api/rag/retrieve",
                json=payload
            )
            assert response.status_code == 200
            assert response.json()["success"] is True
        
        # Check embedding stats after multiple queries
        stats_response = requests.get(f"{BASE_URL}/api/rag/embedding-stats")
        assert stats_response.status_code == 200


class TestRAGVectorStore:
    """Test vector store persistence and collections"""
    
    def test_vector_store_collections_exist(self):
        """Verify all 4 collections exist in vector store"""
        stats_response = requests.get(f"{BASE_URL}/api/rag/stats")
        assert stats_response.status_code == 200
        
        vector_stats = stats_response.json()["stats"]["vector_store"]
        
        expected_collections = ["trade_outcomes", "playbooks", "patterns", "daily_insights"]
        for col in expected_collections:
            assert col in vector_stats["collections"]
            assert col in vector_stats["document_counts"]
    
    def test_vector_store_persist_directory(self):
        """Verify vector store uses correct persist directory"""
        stats_response = requests.get(f"{BASE_URL}/api/rag/stats")
        assert stats_response.status_code == 200
        
        vector_stats = stats_response.json()["stats"]["vector_store"]
        assert vector_stats["persist_directory"] == "/app/backend/data/chromadb"


class TestRAGEdgeCases:
    """Test edge cases and error handling"""
    
    def test_retrieve_empty_query(self):
        """POST /api/rag/retrieve - Should handle empty query gracefully"""
        payload = {
            "query": "",
            "n_results": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=payload
        )
        
        # Should return 200 with empty or zero results
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_retrieve_large_n_results(self):
        """POST /api/rag/retrieve - Should handle large n_results"""
        payload = {
            "query": "trading strategy",
            "n_results": 100
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/retrieve",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_similar_trades_no_filters(self):
        """POST /api/rag/similar-trades - Should handle no filters"""
        payload = {
            "n_results": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/rag/similar-trades",
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
