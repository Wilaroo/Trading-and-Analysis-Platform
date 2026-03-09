"""
TraderSync Import Service
Imports trades from TraderSync CSV exports and creates playbook entries
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List
import csv
import io
from bson import ObjectId


class TraderSyncImportService:
    """Service for importing trades from TraderSync"""
    
    # TraderSync CSV column mappings (common export format)
    COLUMN_MAPPINGS = {
        "Symbol": "symbol",
        "Trade Date": "trade_date",
        "Entry Date": "entry_date",
        "Exit Date": "exit_date",
        "Entry Price": "entry_price",
        "Exit Price": "exit_price",
        "Quantity": "shares",
        "Side": "direction",
        "P&L": "pnl",
        "P&L %": "pnl_percent",
        "Gross P&L": "gross_pnl",
        "Net P&L": "net_pnl",
        "Commissions": "commissions",
        "Tags": "tags",
        "Notes": "notes",
        "Setup": "setup_type",
        "Strategy": "strategy_name",
        "Entry Time": "entry_time",
        "Exit Time": "exit_time",
        "Duration": "duration",
        "R Multiple": "r_multiple",
        "Risk": "risk_amount",
        "MAE": "mae",
        "MFE": "mfe"
    }
    
    def __init__(self, db):
        self.db = db
        self.imported_trades_col = db["tradersync_imports"]
        self.trades_col = db["trades"]
        
        # Create indexes
        self.imported_trades_col.create_index([("import_batch_id", 1)])
        self.imported_trades_col.create_index([("symbol", 1), ("trade_date", -1)])
        self.imported_trades_col.create_index([("setup_type", 1)])
    
    async def import_csv(self, csv_content: str, batch_name: str = None) -> Dict:
        """
        Import trades from TraderSync CSV content
        
        Returns:
        - import_batch_id: ID of the import batch
        - total_trades: Number of trades imported
        - trades: List of imported trade data
        """
        now = datetime.now(timezone.utc)
        batch_id = str(ObjectId())
        
        if not batch_name:
            batch_name = f"TraderSync Import {now.strftime('%Y-%m-%d %H:%M')}"
        
        # Parse CSV
        reader = csv.DictReader(io.StringIO(csv_content))
        
        imported_trades = []
        errors = []
        
        for row_num, row in enumerate(reader, start=1):
            try:
                trade = self._parse_row(row, batch_id)
                if trade:
                    imported_trades.append(trade)
            except Exception as e:
                errors.append({"row": row_num, "error": str(e)})
        
        # Insert all trades
        if imported_trades:
            self.imported_trades_col.insert_many(imported_trades)
        
        # Create import summary
        summary = {
            "import_batch_id": batch_id,
            "batch_name": batch_name,
            "total_trades": len(imported_trades),
            "errors": len(errors),
            "error_details": errors[:10],  # First 10 errors
            "imported_at": now.isoformat(),
            "date_range": self._get_date_range(imported_trades),
            "symbols": list(set(t.get("symbol", "") for t in imported_trades)),
            "setup_types": list(set(t.get("setup_type", "") for t in imported_trades if t.get("setup_type")))
        }
        
        return summary
    
    def _parse_row(self, row: Dict, batch_id: str) -> Optional[Dict]:
        """Parse a single CSV row into trade data"""
        trade = {
            "import_batch_id": batch_id,
            "imported_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Map columns
        for csv_col, field_name in self.COLUMN_MAPPINGS.items():
            if csv_col in row and row[csv_col]:
                value = row[csv_col].strip()
                
                # Type conversions
                if field_name in ["entry_price", "exit_price", "pnl", "gross_pnl", "net_pnl", 
                                  "commissions", "r_multiple", "risk_amount", "mae", "mfe", "pnl_percent"]:
                    try:
                        # Remove $ and % signs, handle parentheses for negative
                        value = value.replace("$", "").replace("%", "").replace(",", "")
                        if "(" in value:
                            value = "-" + value.replace("(", "").replace(")", "")
                        trade[field_name] = float(value) if value else None
                    except Exception:
                        trade[field_name] = None
                elif field_name in ["shares"]:
                    try:
                        trade[field_name] = int(float(value))
                    except Exception:
                        trade[field_name] = 0
                elif field_name == "direction":
                    trade[field_name] = "long" if value.lower() in ["long", "buy", "b"] else "short"
                elif field_name == "tags":
                    trade[field_name] = [t.strip() for t in value.split(",") if t.strip()]
                else:
                    trade[field_name] = value
        
        # Require at least symbol
        if not trade.get("symbol"):
            return None
        
        trade["symbol"] = trade["symbol"].upper()
        
        return trade
    
    def _get_date_range(self, trades: List[Dict]) -> Dict:
        """Get date range of imported trades"""
        dates = []
        for t in trades:
            for date_field in ["trade_date", "entry_date"]:
                if t.get(date_field):
                    try:
                        dates.append(t[date_field])
                    except Exception:
                        pass
        
        if not dates:
            return {"start": None, "end": None}
        
        dates.sort()
        return {"start": dates[0], "end": dates[-1]}
    
    async def get_imported_trades(
        self,
        batch_id: str = None,
        symbol: str = None,
        setup_type: str = None,
        min_pnl: float = None,
        min_r_multiple: float = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get imported trades with filters"""
        query = {}
        
        if batch_id:
            query["import_batch_id"] = batch_id
        if symbol:
            query["symbol"] = symbol.upper()
        if setup_type:
            query["setup_type"] = {"$regex": setup_type, "$options": "i"}
        if min_pnl is not None:
            query["pnl"] = {"$gte": min_pnl}
        if min_r_multiple is not None:
            query["r_multiple"] = {"$gte": min_r_multiple}
        
        trades = list(self.imported_trades_col.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit))
        
        return trades
    
    async def get_trades_for_playbook_generation(
        self,
        min_r_multiple: float = 1.5,
        min_trades_per_setup: int = 2
    ) -> Dict:
        """
        Get trades grouped by setup type that are good candidates for playbooks
        
        Criteria:
        - Winning trades (pnl > 0)
        - R multiple >= min_r_multiple
        - Setup type is defined
        - At least min_trades_per_setup trades of that setup
        """
        pipeline = [
            # Filter winning trades with setup type
            {"$match": {
                "pnl": {"$gt": 0},
                "setup_type": {"$exists": True, "$ne": ""},
            }},
            # Group by setup type
            {"$group": {
                "_id": "$setup_type",
                "count": {"$sum": 1},
                "total_pnl": {"$sum": "$pnl"},
                "avg_pnl": {"$avg": "$pnl"},
                "avg_r_multiple": {"$avg": {"$ifNull": ["$r_multiple", 0]}},
                "symbols": {"$addToSet": "$symbol"},
                "trades": {"$push": {
                    "symbol": "$symbol",
                    "trade_date": "$trade_date",
                    "entry_price": "$entry_price",
                    "exit_price": "$exit_price",
                    "pnl": "$pnl",
                    "r_multiple": "$r_multiple",
                    "notes": "$notes",
                    "tags": "$tags"
                }}
            }},
            # Filter by minimum trades
            {"$match": {"count": {"$gte": min_trades_per_setup}}},
            # Sort by total P&L
            {"$sort": {"total_pnl": -1}}
        ]
        
        results = list(self.imported_trades_col.aggregate(pipeline))
        
        return {
            "setup_types": results,
            "total_setups": len(results),
            "criteria": {
                "min_r_multiple": min_r_multiple,
                "min_trades_per_setup": min_trades_per_setup
            }
        }
    
    async def get_import_batches(self, limit: int = 20) -> List[Dict]:
        """Get list of import batches"""
        pipeline = [
            {"$group": {
                "_id": "$import_batch_id",
                "imported_at": {"$first": "$imported_at"},
                "trade_count": {"$sum": 1},
                "total_pnl": {"$sum": {"$ifNull": ["$pnl", 0]}},
                "symbols": {"$addToSet": "$symbol"}
            }},
            {"$sort": {"imported_at": -1}},
            {"$limit": limit}
        ]
        
        batches = list(self.imported_trades_col.aggregate(pipeline))
        
        return [
            {
                "batch_id": b["_id"],
                "imported_at": b["imported_at"],
                "trade_count": b["trade_count"],
                "total_pnl": round(b["total_pnl"], 2),
                "symbol_count": len(b["symbols"])
            }
            for b in batches
        ]
    
    async def delete_import_batch(self, batch_id: str) -> Dict:
        """Delete an import batch"""
        result = self.imported_trades_col.delete_many({"import_batch_id": batch_id})
        return {"deleted": result.deleted_count}


# Singleton instance
_tradersync_service: Optional[TraderSyncImportService] = None

def get_tradersync_service(db=None) -> TraderSyncImportService:
    global _tradersync_service
    if _tradersync_service is None and db is not None:
        _tradersync_service = TraderSyncImportService(db)
    return _tradersync_service
