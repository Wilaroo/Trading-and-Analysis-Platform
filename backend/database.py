"""
Database connection module for SentCom.
Provides access to the MongoDB database instance.
"""
from pymongo import MongoClient
from pymongo.database import Database
import os
from typing import Optional

_db: Optional[Database] = None
_client: Optional[MongoClient] = None


def init_database() -> Database:
    """Initialize the database connection."""
    global _db, _client
    
    if _db is None:
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME", "tradecommand")
        
        if not mongo_url:
            raise ValueError("MONGO_URL environment variable not set")
        
        _client = MongoClient(mongo_url)
        _db = _client[db_name]
    
    return _db


def get_database() -> Optional[Database]:
    """Get the database instance. Returns None if not initialized."""
    global _db
    
    if _db is None:
        try:
            return init_database()
        except Exception:
            return None
    
    return _db


def set_database(db: Database):
    """Set the database instance (used by server.py)."""
    global _db
    _db = db
