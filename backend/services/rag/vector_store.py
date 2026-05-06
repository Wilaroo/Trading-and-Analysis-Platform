"""
Vector Store Service - ChromaDB wrapper for RAG

Manages the ChromaDB vector database for:
- Storing trade outcome embeddings
- Storing playbook embeddings
- Similarity search for RAG retrieval

Features:
- Persistent storage (survives restarts)
- Auto-rebuild from MongoDB on startup
- Multiple collections (trades, playbooks, patterns)

Note: ChromaDB is optional - if not installed, vector features will be disabled.
"""

import logging
from typing import Optional, List, Dict, Any
import os

logger = logging.getLogger(__name__)

# Check if ChromaDB is available
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
    logger.info("ChromaDB is available")
except ImportError:
    logger.warning("ChromaDB not installed - vector store features will be disabled")

# ChromaDB client (lazy loaded)
_chroma_client = None
_persist_directory = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chromadb")


def get_chroma_client():
    """Get or initialize ChromaDB client"""
    global _chroma_client
    
    if not CHROMADB_AVAILABLE:
        logger.warning("ChromaDB not available - returning None")
        return None
        
    if _chroma_client is None:
        try:
            # Ensure directory exists
            os.makedirs(_persist_directory, exist_ok=True)
            
            # Initialize persistent client
            _chroma_client = chromadb.PersistentClient(
                path=_persist_directory,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDB initialized at {_persist_directory}")
            
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            return None
            
    return _chroma_client


class VectorStoreService:
    """
    Manages ChromaDB collections for RAG.
    
    Collections:
    - trade_outcomes: Historical trade data with context
    - playbooks: Trading playbooks and strategies
    - patterns: Chart patterns and setups
    - daily_insights: Daily report card insights
    """
    
    COLLECTIONS = {
        "trade_outcomes": {
            "description": "Historical trades with full context",
            "metadata_fields": ["symbol", "setup_type", "direction", "outcome", "pnl", "actual_r", "market_regime", "time_of_day"]
        },
        "playbooks": {
            "description": "Trading playbooks and strategies",
            "metadata_fields": ["name", "setup_type", "type"]
        },
        "patterns": {
            "description": "Chart patterns and setup templates",
            "metadata_fields": ["pattern_type", "direction", "success_rate"]
        },
        "daily_insights": {
            "description": "Daily trading insights and lessons",
            "metadata_fields": ["date", "type", "market_regime"]
        }
    }
    
    def __init__(self):
        self._client = None
        self._collections: Dict[str, Any] = {}
        self._initialized = False
        
    def initialize(self):
        """Initialize ChromaDB client and collections"""
        if self._initialized:
            return
            
        try:
            self._client = get_chroma_client()
            
            # Create or get collections
            for name, config in self.COLLECTIONS.items():
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    metadata={"description": config["description"]}
                )
                
            self._initialized = True
            logger.info(f"Vector store initialized with {len(self._collections)} collections")
            
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            raise
            
    def _ensure_initialized(self):
        """Ensure the store is initialized"""
        if not self._initialized:
            self.initialize()
            
    def add_document(
        self,
        collection_name: str,
        doc_id: str,
        text: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None
    ):
        """
        Add a single document to a collection.
        
        Args:
            collection_name: Target collection
            doc_id: Unique document ID
            text: Original text
            embedding: Vector embedding
            metadata: Optional metadata
        """
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            raise ValueError(f"Unknown collection: {collection_name}")
            
        collection = self._collections[collection_name]
        
        # Clean metadata (ChromaDB requires specific types)
        clean_metadata = {}
        if metadata:
            for k, v in metadata.items():
                if v is not None:
                    if isinstance(v, (str, int, float, bool)):
                        clean_metadata[k] = v
                    else:
                        clean_metadata[k] = str(v)
                        
        try:
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[clean_metadata] if clean_metadata else None
            )
        except Exception as e:
            logger.error(f"Error adding document {doc_id}: {e}")
            raise
            
    def add_documents_batch(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]]
    ):
        """
        Add multiple documents to a collection.
        
        Args:
            collection_name: Target collection
            documents: List of dicts with id, text, embedding, metadata
        """
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            raise ValueError(f"Unknown collection: {collection_name}")
            
        if not documents:
            return
            
        collection = self._collections[collection_name]
        
        ids = []
        embeddings = []
        texts = []
        metadatas = []
        
        for doc in documents:
            ids.append(doc["id"])
            embeddings.append(doc["embedding"])
            texts.append(doc.get("text", ""))
            
            # Clean metadata
            clean_meta = {}
            if doc.get("metadata"):
                for k, v in doc["metadata"].items():
                    if v is not None:
                        if isinstance(v, (str, int, float, bool)):
                            clean_meta[k] = v
                        else:
                            clean_meta[k] = str(v)
            metadatas.append(clean_meta)
            
        try:
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )
            logger.info(f"Added {len(documents)} documents to {collection_name}")
        except Exception as e:
            logger.error(f"Error in batch add: {e}")
            raise
            
    def search(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 5,
        where: Dict = None,
        where_document: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents.
        
        Args:
            collection_name: Collection to search
            query_embedding: Query vector
            n_results: Number of results to return
            where: Metadata filter
            where_document: Document content filter
            
        Returns:
            List of matching documents with scores
        """
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            raise ValueError(f"Unknown collection: {collection_name}")
            
        collection = self._collections[collection_name]
        
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                where_document=where_document,
                include=["documents", "metadatas", "distances"]
            )
            
            # Format results
            formatted = []
            if results and results["ids"]:
                for i, doc_id in enumerate(results["ids"][0]):
                    formatted.append({
                        "id": doc_id,
                        "text": results["documents"][0][i] if results["documents"] else "",
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                        "similarity": 1 - results["distances"][0][i] if results["distances"] else 1
                    })
                    
            return formatted
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
            
    def delete_document(self, collection_name: str, doc_id: str):
        """Delete a document by ID"""
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            return
            
        collection = self._collections[collection_name]
        
        try:
            collection.delete(ids=[doc_id])
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {e}")
            
    def get_collection_count(self, collection_name: str) -> int:
        """Get number of documents in a collection"""
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            return 0
            
        collection = self._collections[collection_name]
        return collection.count()
        
    def get_all_counts(self) -> Dict[str, int]:
        """Get document counts for all collections"""
        self._ensure_initialized()
        
        return {name: col.count() for name, col in self._collections.items()}
        
    def clear_collection(self, collection_name: str):
        """Clear all documents from a collection"""
        self._ensure_initialized()
        
        if collection_name not in self._collections:
            return
            
        # Delete and recreate collection
        try:
            self._client.delete_collection(collection_name)
            config = self.COLLECTIONS[collection_name]
            self._collections[collection_name] = self._client.create_collection(
                name=collection_name,
                metadata={"description": config["description"]}
            )
            logger.info(f"Collection {collection_name} cleared")
        except Exception as e:
            logger.error(f"Error clearing collection {collection_name}: {e}")
            
    def reset_all(self):
        """Reset all collections (delete all data)"""
        self._ensure_initialized()
        
        for name in list(self._collections.keys()):
            self.clear_collection(name)
            
        logger.warning("All vector store collections reset")
        
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics"""
        self._ensure_initialized()
        
        counts = self.get_all_counts()
        
        return {
            "persist_directory": _persist_directory,
            "collections": list(self._collections.keys()),
            "document_counts": counts,
            "total_documents": sum(counts.values())
        }


# Singleton
_vector_store_service: Optional[VectorStoreService] = None


def get_vector_store_service() -> VectorStoreService:
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service


def init_vector_store_service() -> VectorStoreService:
    service = get_vector_store_service()
    service.initialize()
    return service
