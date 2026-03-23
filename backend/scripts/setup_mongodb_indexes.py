"""
MongoDB Index Setup Script for SentCom AI Training
===================================================

Run this script once to add indexes that significantly speed up training queries.

Usage:
    python setup_mongodb_indexes.py

Or import and call:
    from setup_mongodb_indexes import setup_indexes
    setup_indexes("your_mongodb_connection_string")
"""

import os
import sys
from pymongo import MongoClient, ASCENDING, DESCENDING

def setup_indexes(mongo_url=None):
    """
    Create optimized indexes for AI training on ib_historical_data collection.
    
    Args:
        mongo_url: MongoDB connection string. If not provided, uses MONGO_URL env var.
    """
    if mongo_url is None:
        mongo_url = os.environ.get('MONGO_URL')
        if not mongo_url:
            print("ERROR: No MongoDB URL provided. Set MONGO_URL environment variable or pass as argument.")
            return False
    
    try:
        print("Connecting to MongoDB...")
        client = MongoClient(mongo_url)
        db = client['tradecommand']
        
        # Collection to index
        collection = db['ib_historical_data']
        
        print(f"Collection: ib_historical_data")
        print(f"Current document count: {collection.count_documents({}):,}")
        print()
        
        # Define indexes for training optimization
        indexes_to_create = [
            {
                "name": "bar_size_symbol_idx",
                "keys": [("bar_size", ASCENDING), ("symbol", ASCENDING)],
                "description": "Speeds up queries to get all symbols for a timeframe"
            },
            {
                "name": "bar_size_idx",
                "keys": [("bar_size", ASCENDING)],
                "description": "Speeds up distinct symbol queries by timeframe"
            },
            {
                "name": "symbol_barsize_date_idx",
                "keys": [("symbol", ASCENDING), ("bar_size", ASCENDING), ("date", ASCENDING)],
                "description": "Speeds up fetching historical bars for a symbol (unique index)"
            }
        ]
        
        # Get existing indexes
        existing_indexes = list(collection.list_indexes())
        existing_names = [idx['name'] for idx in existing_indexes]
        
        print("Creating indexes (this may take a few minutes for large collections)...")
        print()
        
        for idx in indexes_to_create:
            if idx['name'] in existing_names:
                print(f"  [SKIP] {idx['name']} - already exists")
            else:
                try:
                    print(f"  [CREATE] {idx['name']} - {idx['description']}")
                    collection.create_index(idx['keys'], name=idx['name'])
                    print(f"           Done!")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"           Already exists (different name)")
                    else:
                        print(f"           ERROR: {e}")
        
        print()
        print("=" * 50)
        print("Index setup complete!")
        print()
        print("Current indexes on ib_historical_data:")
        for idx in collection.list_indexes():
            print(f"  - {idx['name']}: {dict(idx['key'])}")
        
        # Clean up timeseries_models collection
        print()
        print("Cleaning up timeseries_models collection...")
        models_collection = db['timeseries_models']
        result = models_collection.delete_many({"model_id": None})
        print(f"  Deleted {result.deleted_count} documents with null model_id")
        
        # Drop the problematic unique index if it exists
        try:
            models_collection.drop_index("model_id_1")
            print("  Dropped old model_id_1 unique index")
        except:
            pass
        
        # Create proper index
        try:
            models_collection.create_index([("name", ASCENDING)], unique=True, name="name_unique")
            print("  Created name_unique index")
        except Exception as e:
            if "already exists" not in str(e).lower():
                print(f"  Warning: {e}")
        
        print()
        print("Setup complete! Training should now be significantly faster.")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    # Allow passing MongoDB URL as command line argument
    mongo_url = sys.argv[1] if len(sys.argv) > 1 else None
    setup_indexes(mongo_url)
