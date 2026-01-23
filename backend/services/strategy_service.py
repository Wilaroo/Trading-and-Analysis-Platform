"""
Strategy Service
Manages trading strategies stored in MongoDB
"""
from typing import List, Dict, Optional
from datetime import datetime, timezone
from pymongo.database import Database
from pymongo import ASCENDING


class StrategyService:
    """Service for managing trading strategies"""
    
    def __init__(self, db: Database):
        self.db = db
        self.collection = db["strategies"]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create indexes for efficient querying"""
        self.collection.create_index([("id", ASCENDING)], unique=True)
        self.collection.create_index([("category", ASCENDING)])
        self.collection.create_index([("name", ASCENDING)])
    
    def get_all_strategies(self, category: Optional[str] = None) -> List[Dict]:
        """Get all strategies, optionally filtered by category"""
        query = {}
        if category:
            query["category"] = category.lower()
        
        strategies = list(self.collection.find(query, {"_id": 0}))
        return strategies
    
    def get_strategy_by_id(self, strategy_id: str) -> Optional[Dict]:
        """Get a single strategy by ID"""
        strategy = self.collection.find_one(
            {"id": strategy_id.upper()}, 
            {"_id": 0}
        )
        return strategy
    
    def get_strategies_by_ids(self, strategy_ids: List[str]) -> List[Dict]:
        """Get multiple strategies by their IDs"""
        strategies = list(self.collection.find(
            {"id": {"$in": [sid.upper() for sid in strategy_ids]}},
            {"_id": 0}
        ))
        return strategies
    
    def get_strategies_by_category(self, category: str) -> List[Dict]:
        """Get all strategies in a category"""
        return list(self.collection.find(
            {"category": category.lower()},
            {"_id": 0}
        ))
    
    def get_categories(self) -> List[str]:
        """Get all unique strategy categories"""
        return self.collection.distinct("category")
    
    def get_strategy_count(self) -> int:
        """Get total number of strategies"""
        return self.collection.count_documents({})
    
    def search_strategies(self, query: str) -> List[Dict]:
        """Search strategies by name or criteria"""
        regex_query = {"$regex": query, "$options": "i"}
        strategies = list(self.collection.find(
            {
                "$or": [
                    {"name": regex_query},
                    {"criteria": regex_query},
                    {"indicators": regex_query}
                ]
            },
            {"_id": 0}
        ))
        return strategies
    
    def add_strategy(self, strategy: Dict) -> bool:
        """Add a new strategy"""
        try:
            strategy["created_at"] = datetime.now(timezone.utc).isoformat()
            strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.collection.insert_one(strategy)
            return True
        except Exception as e:
            print(f"Error adding strategy: {e}")
            return False
    
    def update_strategy(self, strategy_id: str, updates: Dict) -> bool:
        """Update an existing strategy"""
        try:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            result = self.collection.update_one(
                {"id": strategy_id.upper()},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating strategy: {e}")
            return False
    
    def delete_strategy(self, strategy_id: str) -> bool:
        """Delete a strategy"""
        try:
            result = self.collection.delete_one({"id": strategy_id.upper()})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting strategy: {e}")
            return False
    
    def seed_strategies(self, strategies: List[Dict]) -> int:
        """Seed strategies into the database (bulk insert)"""
        if not strategies:
            return 0
        
        # Clear existing strategies
        self.collection.delete_many({})
        
        # Add timestamps
        now = datetime.now(timezone.utc).isoformat()
        for strategy in strategies:
            strategy["created_at"] = now
            strategy["updated_at"] = now
        
        # Insert all
        result = self.collection.insert_many(strategies)
        return len(result.inserted_ids)
    
    def is_seeded(self) -> bool:
        """Check if strategies have been seeded"""
        return self.collection.count_documents({}) > 0


# Singleton instance
_strategy_service: Optional[StrategyService] = None


def get_strategy_service(db: Database = None) -> StrategyService:
    """Get or create the strategy service singleton"""
    global _strategy_service
    if _strategy_service is None and db is not None:
        _strategy_service = StrategyService(db)
    return _strategy_service
