"""
Knowledge Base Service
Stores and retrieves trading knowledge, strategies, patterns, and insights.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from bson import ObjectId
import os
from pymongo import MongoClient, ASCENDING, TEXT
import logging

logger = logging.getLogger(__name__)

# MongoDB connection
_db = None

def _get_db():
    """Get MongoDB database connection"""
    global _db
    if _db is None:
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "tradecommand")
        client = MongoClient(mongo_url)
        _db = client[db_name]
    return _db


class KnowledgeService:
    """
    Service for managing the trading knowledge base.
    Supports strategies, patterns, insights, rules, and general notes.
    """
    
    COLLECTION = "knowledge_base"
    
    # Valid knowledge types
    TYPES = ["strategy", "pattern", "insight", "rule", "note", "indicator", "checklist"]
    
    # Valid categories
    CATEGORIES = [
        "entry", "exit", "risk_management", "position_sizing", 
        "market_condition", "technical", "fundamental", "sentiment",
        "premarket", "intraday", "swing", "general"
    ]
    
    def __init__(self):
        self.db = _get_db()
        self.collection = self.db[self.COLLECTION]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create indexes for efficient querying"""
        try:
            # Text index for full-text search
            self.collection.create_index([
                ("title", TEXT),
                ("content", TEXT),
                ("tags", TEXT)
            ], name="text_search")
            
            # Index for type filtering
            self.collection.create_index([("type", ASCENDING)], name="type_idx")
            
            # Index for category filtering
            self.collection.create_index([("category", ASCENDING)], name="category_idx")
            
            # Index for tags
            self.collection.create_index([("tags", ASCENDING)], name="tags_idx")
            
            # Compound index for common queries
            self.collection.create_index([
                ("type", ASCENDING),
                ("category", ASCENDING),
                ("created_at", ASCENDING)
            ], name="type_category_date_idx")
            
            logger.info("Knowledge base indexes created")
        except Exception as e:
            logger.warning(f"Could not create indexes: {e}")
    
    def add(self, 
            title: str, 
            content: str, 
            type: str = "note",
            category: str = "general",
            tags: List[str] = None,
            source: str = "user",
            confidence: int = 80,
            metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Add a new knowledge entry.
        
        Args:
            title: Short title/name for the entry
            content: Full content/description
            type: One of TYPES (strategy, pattern, insight, rule, note, indicator, checklist)
            category: One of CATEGORIES
            tags: List of tags for filtering
            source: Where this came from (user, backtest, observation, research)
            confidence: Confidence level 0-100
            metadata: Additional structured data (e.g., conditions for strategies)
        
        Returns:
            The created entry with ID
        """
        # Validate type
        if type not in self.TYPES:
            type = "note"
        
        # Validate category
        if category not in self.CATEGORIES:
            category = "general"
        
        entry = {
            "title": title,
            "content": content,
            "type": type,
            "category": category,
            "tags": tags or [],
            "source": source,
            "confidence": max(0, min(100, confidence)),
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "is_active": True,
            "usage_count": 0  # Track how often this is referenced
        }
        
        result = self.collection.insert_one(entry)
        entry["id"] = str(result.inserted_id)
        if "_id" in entry:
            del entry["_id"]
        
        logger.info(f"Added knowledge entry: {title} ({type})")
        return entry
    
    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get a single entry by ID"""
        try:
            doc = self.collection.find_one({"_id": ObjectId(entry_id)})
            if doc:
                doc["id"] = str(doc["_id"])
                del doc["_id"]
                return doc
        except Exception as e:
            logger.error(f"Error getting entry {entry_id}: {e}")
        return None
    
    def update(self, entry_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing entry"""
        try:
            # Don't allow updating certain fields
            protected = ["_id", "id", "created_at"]
            for field in protected:
                updates.pop(field, None)
            
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            result = self.collection.find_one_and_update(
                {"_id": ObjectId(entry_id)},
                {"$set": updates},
                return_document=True
            )
            
            if result:
                result["id"] = str(result["_id"])
                del result["_id"]
                logger.info(f"Updated knowledge entry: {entry_id}")
                return result
        except Exception as e:
            logger.error(f"Error updating entry {entry_id}: {e}")
        return None
    
    def delete(self, entry_id: str) -> bool:
        """Delete an entry (soft delete by default)"""
        try:
            result = self.collection.update_one(
                {"_id": ObjectId(entry_id)},
                {"$set": {"is_active": False, "deleted_at": datetime.now(timezone.utc).isoformat()}}
            )
            if result.modified_count > 0:
                logger.info(f"Deleted knowledge entry: {entry_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting entry {entry_id}: {e}")
        return False
    
    def hard_delete(self, entry_id: str) -> bool:
        """Permanently delete an entry"""
        try:
            result = self.collection.delete_one({"_id": ObjectId(entry_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error hard deleting entry {entry_id}: {e}")
        return False
    
    def search(self, 
               query: str = None,
               type: str = None,
               category: str = None,
               tags: List[str] = None,
               limit: int = 50,
               include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Search the knowledge base.
        
        Args:
            query: Text search query (searches title, content, tags)
            type: Filter by type
            category: Filter by category
            tags: Filter by tags (any match)
            limit: Max results to return
            include_inactive: Include deleted entries
        
        Returns:
            List of matching entries
        """
        filter_query = {}
        
        # Active filter
        if not include_inactive:
            filter_query["is_active"] = True
        
        # Text search
        if query:
            filter_query["$text"] = {"$search": query}
        
        # Type filter
        if type and type in self.TYPES:
            filter_query["type"] = type
        
        # Category filter
        if category and category in self.CATEGORIES:
            filter_query["category"] = category
        
        # Tags filter
        if tags:
            filter_query["tags"] = {"$in": tags}
        
        try:
            # If text search, sort by relevance; otherwise by date
            if query:
                cursor = self.collection.find(
                    filter_query,
                    {"score": {"$meta": "textScore"}}
                ).sort([("score", {"$meta": "textScore"})]).limit(limit)
            else:
                cursor = self.collection.find(filter_query).sort("updated_at", -1).limit(limit)
            
            results = []
            for doc in cursor:
                doc["id"] = str(doc["_id"])
                del doc["_id"]
                results.append(doc)
            
            return results
        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return []
    
    def get_by_type(self, type: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all entries of a specific type"""
        return self.search(type=type, limit=limit)
    
    def get_strategies(self, category: str = None) -> List[Dict[str, Any]]:
        """Get all active strategies, optionally filtered by category"""
        return self.search(type="strategy", category=category, limit=100)
    
    def get_rules(self, category: str = None) -> List[Dict[str, Any]]:
        """Get all active rules"""
        return self.search(type="rule", category=category, limit=100)
    
    def get_checklists(self) -> List[Dict[str, Any]]:
        """Get all checklists"""
        return self.search(type="checklist", limit=50)
    
    def increment_usage(self, entry_id: str) -> None:
        """Increment the usage count for an entry"""
        try:
            self.collection.update_one(
                {"_id": ObjectId(entry_id)},
                {"$inc": {"usage_count": 1}}
            )
        except Exception as e:
            logger.warning(f"Could not increment usage for {entry_id}: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        try:
            total = self.collection.count_documents({"is_active": True})
            
            # Count by type
            type_counts = {}
            for t in self.TYPES:
                type_counts[t] = self.collection.count_documents({"type": t, "is_active": True})
            
            # Count by category
            category_counts = {}
            for c in self.CATEGORIES:
                count = self.collection.count_documents({"category": c, "is_active": True})
                if count > 0:
                    category_counts[c] = count
            
            # Get most used entries
            top_used = list(self.collection.find(
                {"is_active": True},
                {"_id": 0, "title": 1, "type": 1, "usage_count": 1}
            ).sort("usage_count", -1).limit(5))
            
            return {
                "total_entries": total,
                "by_type": type_counts,
                "by_category": category_counts,
                "top_used": top_used
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"total_entries": 0, "by_type": {}, "by_category": {}, "top_used": []}
    
    def export_all(self) -> List[Dict[str, Any]]:
        """Export all active entries for backup"""
        return self.search(limit=10000)
    
    def import_entries(self, entries: List[Dict[str, Any]]) -> int:
        """Import multiple entries (for restore)"""
        count = 0
        for entry in entries:
            # Remove ID fields to create new entries
            entry.pop("id", None)
            entry.pop("_id", None)
            try:
                self.collection.insert_one(entry)
                count += 1
            except Exception as e:
                logger.warning(f"Could not import entry: {e}")
        return count


# Singleton instance
_knowledge_service: Optional[KnowledgeService] = None

def get_knowledge_service() -> KnowledgeService:
    """Get the singleton knowledge service instance"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
