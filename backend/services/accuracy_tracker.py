"""
AI Accuracy Tracking Service
Stores and retrieves historical accuracy statistics for AI responses.
Tracks validation results over time to measure improvement.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from pymongo import MongoClient, DESCENDING
import os

logger = logging.getLogger(__name__)


class AccuracyTracker:
    """
    Tracks AI response accuracy over time.
    Stores validation results in MongoDB for analysis.
    """
    
    def __init__(self):
        self._mongo_url = os.environ.get("MONGO_URL")
        self._db_name = os.environ.get("DB_NAME", "trade_command")
        self._client = None
        self._db = None
        self._collection = None
        self._init_db()
    
    def _init_db(self):
        """Initialize MongoDB connection"""
        try:
            if self._mongo_url:
                self._client = MongoClient(self._mongo_url)
                self._db = self._client[self._db_name]
                self._collection = self._db["ai_accuracy_tracking"]
                
                # Create indexes for efficient queries
                self._collection.create_index([("timestamp", DESCENDING)])
                self._collection.create_index([("intent", 1)])
                self._collection.create_index([("symbols", 1)])
                self._collection.create_index([("validated", 1)])
                
                logger.info("AI Accuracy Tracker initialized with MongoDB")
            else:
                logger.warning("No MONGO_URL - Accuracy tracking will be in-memory only")
        except Exception as e:
            logger.error(f"Failed to initialize accuracy tracker DB: {e}")
    
    def record_validation(self, 
                         user_message: str,
                         intent: str,
                         symbols: List[str],
                         validation_result: Dict,
                         response_length: int,
                         provider: str,
                         regeneration_count: int = 0) -> bool:
        """
        Record a validation result for accuracy tracking.
        
        Args:
            user_message: The original user query
            intent: Detected intent type
            symbols: List of symbols mentioned
            validation_result: The validation result dict
            response_length: Length of AI response
            provider: LLM provider used (ollama, gpt-4o, etc.)
            regeneration_count: Number of regeneration attempts
            
        Returns:
            True if recorded successfully
        """
        try:
            record = {
                "timestamp": datetime.now(timezone.utc),
                "user_message": user_message[:200],  # Truncate for storage
                "intent": intent,
                "symbols": symbols,
                "validated": validation_result.get("validated", True),
                "confidence": validation_result.get("confidence", 1.0),
                "issue_count": validation_result.get("issue_count", 0),
                "issues": validation_result.get("issues", []),
                "response_length": response_length,
                "provider": provider,
                "regeneration_count": regeneration_count,
                "issue_types": list(set(i.get("type") for i in validation_result.get("issues", []))),
                "severities": list(set(i.get("severity") for i in validation_result.get("issues", [])))
            }
            
            if self._collection is not None:
                self._collection.insert_one(record)
                logger.debug(f"Recorded accuracy: validated={record['validated']}, confidence={record['confidence']}")
                return True
            else:
                logger.debug(f"In-memory accuracy record: {record}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to record validation: {e}")
            return False
    
    def get_accuracy_stats(self, 
                          days: int = 7,
                          intent: Optional[str] = None,
                          symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get accuracy statistics for a time period.
        
        Args:
            days: Number of days to look back
            intent: Filter by specific intent type
            symbol: Filter by specific symbol
            
        Returns:
            Dictionary with accuracy statistics
        """
        try:
            if self._collection is None:
                return {"available": False, "error": "No database connection"}
            
            # Build query filter
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = {"timestamp": {"$gte": cutoff}}
            
            if intent:
                query["intent"] = intent
            if symbol:
                query["symbols"] = symbol
            
            # Get all records
            records = list(self._collection.find(query).sort("timestamp", DESCENDING))
            
            if not records:
                return {
                    "available": True,
                    "period_days": days,
                    "total_queries": 0,
                    "message": "No data for this period"
                }
            
            # Calculate statistics
            total = len(records)
            validated_count = sum(1 for r in records if r.get("validated", True))
            avg_confidence = sum(r.get("confidence", 1.0) for r in records) / total
            
            # Issue breakdown
            issue_types = {}
            for r in records:
                for issue_type in r.get("issue_types", []):
                    issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
            
            # Severity breakdown
            severity_counts = {"high": 0, "medium": 0, "low": 0}
            for r in records:
                for sev in r.get("severities", []):
                    if sev in severity_counts:
                        severity_counts[sev] += 1
            
            # Intent breakdown
            intent_stats = {}
            for r in records:
                i = r.get("intent", "unknown")
                if i not in intent_stats:
                    intent_stats[i] = {"total": 0, "validated": 0}
                intent_stats[i]["total"] += 1
                if r.get("validated", True):
                    intent_stats[i]["validated"] += 1
            
            # Calculate intent accuracy rates
            for i in intent_stats:
                stats = intent_stats[i]
                stats["accuracy_rate"] = round(stats["validated"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
            
            # Provider breakdown
            provider_stats = {}
            for r in records:
                p = r.get("provider", "unknown")
                if p not in provider_stats:
                    provider_stats[p] = {"total": 0, "validated": 0}
                provider_stats[p]["total"] += 1
                if r.get("validated", True):
                    provider_stats[p]["validated"] += 1
            
            for p in provider_stats:
                stats = provider_stats[p]
                stats["accuracy_rate"] = round(stats["validated"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
            
            # Regeneration stats
            regenerations = sum(1 for r in records if r.get("regeneration_count", 0) > 0)
            
            return {
                "available": True,
                "period_days": days,
                "filter": {
                    "intent": intent,
                    "symbol": symbol
                },
                "summary": {
                    "total_queries": total,
                    "validated_count": validated_count,
                    "validation_rate": round(validated_count / total * 100, 1),
                    "average_confidence": round(avg_confidence, 2),
                    "regeneration_count": regenerations,
                    "regeneration_rate": round(regenerations / total * 100, 1)
                },
                "issue_breakdown": issue_types,
                "severity_breakdown": severity_counts,
                "by_intent": intent_stats,
                "by_provider": provider_stats,
                "latest_timestamp": records[0].get("timestamp").isoformat() if records else None
            }
            
        except Exception as e:
            logger.error(f"Failed to get accuracy stats: {e}")
            return {"available": False, "error": str(e)}
    
    def get_recent_issues(self, limit: int = 10) -> List[Dict]:
        """
        Get the most recent validation issues for debugging.
        
        Args:
            limit: Maximum number of issues to return
            
        Returns:
            List of recent issues with context
        """
        try:
            if self._collection is None:
                return []
            
            # Find records with issues
            query = {"validated": False}
            records = list(self._collection.find(query)
                          .sort("timestamp", DESCENDING)
                          .limit(limit))
            
            issues = []
            for r in records:
                issues.append({
                    "timestamp": r.get("timestamp").isoformat() if r.get("timestamp") else None,
                    "user_message": r.get("user_message", "")[:100],
                    "intent": r.get("intent"),
                    "symbols": r.get("symbols", []),
                    "confidence": r.get("confidence"),
                    "issues": r.get("issues", [])[:3],  # Top 3 issues
                    "provider": r.get("provider"),
                    "regenerated": r.get("regeneration_count", 0) > 0
                })
            
            return issues
            
        except Exception as e:
            logger.error(f"Failed to get recent issues: {e}")
            return []
    
    def get_symbol_accuracy(self, symbol: str, days: int = 30) -> Dict:
        """
        Get accuracy statistics for a specific symbol.
        
        Args:
            symbol: Stock symbol to check
            days: Number of days to look back
            
        Returns:
            Symbol-specific accuracy stats
        """
        try:
            if self._collection is None:
                return {"available": False, "error": "No database connection"}
            
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = {
                "timestamp": {"$gte": cutoff},
                "symbols": symbol.upper()
            }
            
            records = list(self._collection.find(query))
            
            if not records:
                return {
                    "available": True,
                    "symbol": symbol.upper(),
                    "period_days": days,
                    "total_queries": 0,
                    "message": "No queries found for this symbol"
                }
            
            total = len(records)
            validated = sum(1 for r in records if r.get("validated", True))
            
            # Most common issue type for this symbol
            issue_types = {}
            for r in records:
                for i in r.get("issues", []):
                    t = i.get("type", "unknown")
                    issue_types[t] = issue_types.get(t, 0) + 1
            
            most_common_issue = max(issue_types.items(), key=lambda x: x[1])[0] if issue_types else None
            
            return {
                "available": True,
                "symbol": symbol.upper(),
                "period_days": days,
                "total_queries": total,
                "validated_count": validated,
                "accuracy_rate": round(validated / total * 100, 1),
                "most_common_issue": most_common_issue,
                "issue_breakdown": issue_types
            }
            
        except Exception as e:
            logger.error(f"Failed to get symbol accuracy: {e}")
            return {"available": False, "error": str(e)}


# Singleton instance
_accuracy_tracker = None

def get_accuracy_tracker() -> AccuracyTracker:
    """Get singleton accuracy tracker instance"""
    global _accuracy_tracker
    if _accuracy_tracker is None:
        _accuracy_tracker = AccuracyTracker()
    return _accuracy_tracker
