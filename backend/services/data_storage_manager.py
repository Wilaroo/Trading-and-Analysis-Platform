"""
Data Storage Manager
====================

Centralized management of all learning and training data storage.
Ensures proper indexes, data retention, and easy retrieval.

Collections Managed:
- ib_historical_data: Historical OHLCV from IB Gateway
- simulation_jobs: Backtest simulation job records
- simulated_trades: Trades from simulations
- simulation_decisions: AI decisions from simulations
- shadow_decisions: Shadow mode AI decisions
- timeseries_predictions: Time-series model predictions
- timeseries_models: Saved model metadata
- calibration_history: Module calibration records
- learning_connectors: Connection states
- alert_outcomes: Alert performance tracking
- trade_outcomes: Real trade outcomes
- training_datasets: Prepared training data
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database

logger = logging.getLogger(__name__)


class DataStorageManager:
    """
    Centralized data storage management for all learning systems.
    
    Responsibilities:
    1. Ensure all collections have proper indexes
    2. Provide unified data retrieval methods
    3. Manage data retention/cleanup
    4. Track storage statistics
    """
    
    # Collection definitions with their indexes
    COLLECTIONS = {
        # IB Historical Data
        "ib_historical_data": {
            "description": "Historical OHLCV data from IB Gateway",
            "indexes": [
                IndexModel([("symbol", ASCENDING), ("bar_size", ASCENDING), ("date", ASCENDING)], unique=True),
                IndexModel([("symbol", ASCENDING), ("bar_size", ASCENDING)]),
                IndexModel([("bar_size", ASCENDING), ("symbol", ASCENDING)]),  # For training queries
                IndexModel([("bar_size", ASCENDING)]),  # For getting all symbols by timeframe
                IndexModel([("collected_at", DESCENDING)]),
                IndexModel([("date", DESCENDING)]),
            ],
            "retention_days": None,  # Keep forever
        },
        "ib_collection_jobs": {
            "description": "IB data collection job history",
            "indexes": [
                IndexModel([("id", ASCENDING)], unique=True),
                IndexModel([("start_time", DESCENDING)]),
                IndexModel([("status", ASCENDING)]),
            ],
            "retention_days": 90,
        },
        
        # Simulation Data
        "simulation_jobs": {
            "description": "Historical simulation/backtest jobs",
            "indexes": [
                IndexModel([("id", ASCENDING)], unique=True),
                IndexModel([("start_date", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("created_at", DESCENDING)]),
            ],
            "retention_days": None,  # Keep forever - valuable for learning
        },
        "simulated_trades": {
            "description": "Trades executed during simulations",
            "indexes": [
                IndexModel([("job_id", ASCENDING), ("symbol", ASCENDING)]),
                IndexModel([("symbol", ASCENDING), ("entry_time", DESCENDING)]),
                IndexModel([("used_for_training", ASCENDING)]),
                IndexModel([("pnl", DESCENDING)]),
            ],
            "retention_days": None,
        },
        "simulation_decisions": {
            "description": "AI decisions made during simulations",
            "indexes": [
                IndexModel([("job_id", ASCENDING), ("date", ASCENDING)]),
                IndexModel([("symbol", ASCENDING), ("date", DESCENDING)]),
                IndexModel([("decision", ASCENDING)]),
            ],
            "retention_days": None,
        },
        
        # Shadow Mode Data
        "shadow_decisions": {
            "description": "Shadow mode AI trading decisions",
            "indexes": [
                IndexModel([("symbol", ASCENDING), ("trigger_time", DESCENDING)]),
                IndexModel([("trigger_time", DESCENDING)]),
                IndexModel([("outcome_tracked", ASCENDING)]),
                IndexModel([("would_have_pnl", DESCENDING)]),
            ],
            "retention_days": None,  # Valuable for learning
        },
        
        # Time-Series Model Data
        "timeseries_predictions": {
            "description": "Time-series model predictions for tracking",
            "indexes": [
                IndexModel([("symbol", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("outcome_verified", ASCENDING)]),
                IndexModel([("prediction.direction", ASCENDING)]),
            ],
            "retention_days": 365,
        },
        "timeseries_models": {
            "description": "Saved time-series model metadata",
            "indexes": [
                IndexModel([("name", ASCENDING)], unique=True),  # Primary key is model name
                IndexModel([("model_id", ASCENDING)], sparse=True),  # Allow nulls with sparse
                IndexModel([("created_at", DESCENDING)]),
                IndexModel([("version", DESCENDING)]),
            ],
            "retention_days": None,  # Keep model history
        },
        
        # Learning System Data
        "calibration_history": {
            "description": "Module calibration records",
            "indexes": [
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("calibration_type", ASCENDING)]),
            ],
            "retention_days": 365,
        },
        "learning_connectors": {
            "description": "Learning connection states",
            "indexes": [
                IndexModel([("name", ASCENDING)], unique=True),
            ],
            "retention_days": None,
        },
        
        # Alert and Trade Outcomes
        "alert_outcomes": {
            "description": "Alert performance tracking",
            "indexes": [
                IndexModel([("symbol", ASCENDING), ("timestamp", DESCENDING)]),
                IndexModel([("setup_type", ASCENDING)]),
                IndexModel([("r_multiple", DESCENDING)]),
                IndexModel([("timestamp", DESCENDING)]),
            ],
            "retention_days": None,
        },
        "trade_outcomes": {
            "description": "Real trade outcome tracking",
            "indexes": [
                IndexModel([("symbol", ASCENDING), ("exit_time", DESCENDING)]),
                IndexModel([("strategy", ASCENDING)]),
                IndexModel([("pnl", DESCENDING)]),
            ],
            "retention_days": None,
        },
        
        # Prepared Training Data
        "training_datasets": {
            "description": "Prepared and labeled training datasets",
            "indexes": [
                IndexModel([("dataset_id", ASCENDING)], unique=True),
                IndexModel([("created_at", DESCENDING)]),
                IndexModel([("model_type", ASCENDING)]),
                IndexModel([("symbol", ASCENDING)]),
            ],
            "retention_days": 180,
        },
    }
    
    def __init__(self):
        self._db: Optional[Database] = None
        self._initialized = False
        
    def set_db(self, db: Database):
        """Set database connection and ensure indexes"""
        self._db = db
        if db is not None:
            self._ensure_indexes()
            self._initialized = True
            
    def _ensure_indexes(self):
        """Ensure all collections have proper indexes"""
        if self._db is None:
            return
            
        for collection_name, config in self.COLLECTIONS.items():
            try:
                collection = self._db[collection_name]
                
                # Create indexes
                for index in config["indexes"]:
                    try:
                        collection.create_indexes([index])
                    except Exception as e:
                        # Index might already exist
                        if "already exists" not in str(e).lower():
                            logger.warning(f"Index creation warning for {collection_name}: {e}")
                            
                logger.debug(f"Indexes ensured for {collection_name}")
                
            except Exception as e:
                logger.error(f"Error ensuring indexes for {collection_name}: {e}")
                
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get statistics about all stored data"""
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
            
        stats = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collections": {},
            "totals": {
                "total_documents": 0,
                "total_size_mb": 0
            }
        }
        
        for collection_name, config in self.COLLECTIONS.items():
            try:
                collection = self._db[collection_name]
                count = collection.count_documents({})
                
                # Get collection stats
                try:
                    coll_stats = self._db.command("collStats", collection_name)
                    size_mb = coll_stats.get("size", 0) / (1024 * 1024)
                except Exception:
                    size_mb = 0
                    
                stats["collections"][collection_name] = {
                    "description": config["description"],
                    "document_count": count,
                    "size_mb": round(size_mb, 2),
                    "retention_days": config["retention_days"],
                    "indexes": len(config["indexes"])
                }
                
                stats["totals"]["total_documents"] += count
                stats["totals"]["total_size_mb"] += size_mb
                
            except Exception as e:
                stats["collections"][collection_name] = {
                    "error": str(e)
                }
                
        stats["totals"]["total_size_mb"] = round(stats["totals"]["total_size_mb"], 2)
        return stats
        
    def get_learning_data_summary(self) -> Dict[str, Any]:
        """Get summary of all data available for learning"""
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
            
        summary = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_sources": {}
        }
        
        # IB Historical Data
        try:
            ib_data = self._db["ib_historical_data"]
            summary["data_sources"]["ib_historical"] = {
                "total_bars": ib_data.count_documents({}),
                "unique_symbols": len(ib_data.distinct("symbol")),
                "bar_sizes": list(ib_data.distinct("bar_size")),
                "date_range": self._get_date_range(ib_data, "date")
            }
        except Exception as e:
            summary["data_sources"]["ib_historical"] = {"error": str(e)}
            
        # Simulation Data
        try:
            sim_trades = self._db["simulated_trades"]
            summary["data_sources"]["simulations"] = {
                "total_trades": sim_trades.count_documents({}),
                "used_for_training": sim_trades.count_documents({"used_for_training": True}),
                "not_used": sim_trades.count_documents({"used_for_training": {"$ne": True}}),
                "unique_symbols": len(sim_trades.distinct("symbol"))
            }
        except Exception as e:
            summary["data_sources"]["simulations"] = {"error": str(e)}
            
        # Shadow Decisions
        try:
            shadow = self._db["shadow_decisions"]
            summary["data_sources"]["shadow_decisions"] = {
                "total_decisions": shadow.count_documents({}),
                "outcome_tracked": shadow.count_documents({"outcome_tracked": True}),
                "pending_outcome": shadow.count_documents({"outcome_tracked": {"$ne": True}}),
                "date_range": self._get_date_range(shadow, "trigger_time")
            }
        except Exception as e:
            summary["data_sources"]["shadow_decisions"] = {"error": str(e)}
            
        # Predictions
        try:
            preds = self._db["timeseries_predictions"]
            summary["data_sources"]["predictions"] = {
                "total_predictions": preds.count_documents({}),
                "verified": preds.count_documents({"outcome_verified": True}),
                "pending_verification": preds.count_documents({"outcome_verified": {"$ne": True}})
            }
        except Exception as e:
            summary["data_sources"]["predictions"] = {"error": str(e)}
            
        # Alert Outcomes
        try:
            alerts = self._db["alert_outcomes"]
            summary["data_sources"]["alert_outcomes"] = {
                "total_outcomes": alerts.count_documents({}),
                "positive_r": alerts.count_documents({"r_multiple": {"$gt": 0}}),
                "negative_r": alerts.count_documents({"r_multiple": {"$lte": 0}})
            }
        except Exception as e:
            summary["data_sources"]["alert_outcomes"] = {"error": str(e)}
            
        # Calculate total usable samples
        total_samples = 0
        for source, data in summary["data_sources"].items():
            if isinstance(data, dict) and "error" not in data:
                if "total_bars" in data:
                    total_samples += data["total_bars"]
                elif "total_trades" in data:
                    total_samples += data["total_trades"]
                elif "total_decisions" in data:
                    total_samples += data["total_decisions"]
                    
        summary["total_learning_samples"] = total_samples
        
        return summary
        
    def _get_date_range(self, collection, date_field: str) -> Dict[str, str]:
        """Get min/max date range for a collection"""
        try:
            earliest = collection.find_one({}, sort=[(date_field, ASCENDING)])
            latest = collection.find_one({}, sort=[(date_field, DESCENDING)])
            
            return {
                "earliest": earliest.get(date_field, "N/A") if earliest else "N/A",
                "latest": latest.get(date_field, "N/A") if latest else "N/A"
            }
        except Exception:
            return {"earliest": "N/A", "latest": "N/A"}
            
    def cleanup_old_data(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up data past retention period.
        
        Args:
            dry_run: If True, only report what would be deleted
        """
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
            
        results = {
            "success": True,
            "dry_run": dry_run,
            "collections": {}
        }
        
        now = datetime.now(timezone.utc)
        
        for collection_name, config in self.COLLECTIONS.items():
            retention_days = config.get("retention_days")
            if retention_days is None:
                results["collections"][collection_name] = {"status": "no_retention_policy"}
                continue
                
            cutoff_date = now - timedelta(days=retention_days)
            
            try:
                collection = self._db[collection_name]
                
                # Find date field (varies by collection)
                date_field = self._get_date_field(collection_name)
                if not date_field:
                    results["collections"][collection_name] = {"status": "no_date_field"}
                    continue
                    
                # Count documents to delete
                query = {date_field: {"$lt": cutoff_date.isoformat()}}
                count = collection.count_documents(query)
                
                if dry_run:
                    results["collections"][collection_name] = {
                        "would_delete": count,
                        "retention_days": retention_days,
                        "cutoff_date": cutoff_date.isoformat()
                    }
                else:
                    if count > 0:
                        result = collection.delete_many(query)
                        results["collections"][collection_name] = {
                            "deleted": result.deleted_count,
                            "retention_days": retention_days
                        }
                    else:
                        results["collections"][collection_name] = {"deleted": 0}
                        
            except Exception as e:
                results["collections"][collection_name] = {"error": str(e)}
                
        return results
        
    def _get_date_field(self, collection_name: str) -> Optional[str]:
        """Get the date field name for a collection"""
        date_fields = {
            "ib_historical_data": "collected_at",
            "ib_collection_jobs": "start_time",
            "simulation_jobs": "created_at",
            "shadow_decisions": "trigger_time",
            "timeseries_predictions": "timestamp",
            "calibration_history": "timestamp",
            "alert_outcomes": "timestamp",
            "training_datasets": "created_at",
        }
        return date_fields.get(collection_name)
        
    def export_training_data(
        self,
        source: str,
        symbol: str = None,
        limit: int = 10000,
        format: str = "list"
    ) -> Dict[str, Any]:
        """
        Export data for model training.
        
        Args:
            source: Data source (ib_historical, simulations, shadow_decisions)
            symbol: Optional symbol filter
            limit: Max records to return
            format: "list" or "dataframe_dict"
        """
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            if source == "ib_historical":
                collection = self._db["ib_historical_data"]
                query = {"symbol": symbol.upper()} if symbol else {}
                projection = {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "bar_size": 1}
                
            elif source == "simulations":
                collection = self._db["simulated_trades"]
                query = {"symbol": symbol.upper()} if symbol else {}
                projection = {"_id": 0}
                
            elif source == "shadow_decisions":
                collection = self._db["shadow_decisions"]
                query = {"outcome_tracked": True}
                if symbol:
                    query["symbol"] = symbol.upper()
                projection = {"_id": 0}
                
            else:
                return {"success": False, "error": f"Unknown source: {source}"}
                
            data = list(collection.find(query, projection).limit(limit))
            
            return {
                "success": True,
                "source": source,
                "symbol": symbol,
                "count": len(data),
                "data": data
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_storage_manager: Optional[DataStorageManager] = None


def get_storage_manager() -> DataStorageManager:
    """Get the singleton instance"""
    global _storage_manager
    if _storage_manager is None:
        _storage_manager = DataStorageManager()
    return _storage_manager


def init_storage_manager(db=None) -> DataStorageManager:
    """Initialize the storage manager"""
    manager = get_storage_manager()
    manager.set_db(db)
    return manager
