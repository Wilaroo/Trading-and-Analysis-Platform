"""
Short Interest Data Service
============================
Aggregates short interest data from two sources:
1. IB Gateway: Real-time shortableShares and shortable level
2. FINRA: Bi-monthly short interest reports (free Consolidated API)

Stores data in:
- `ib_short_data` — Real-time IB shortable shares (pushed by local pusher)
- `finra_short_interest` — Bi-monthly FINRA short interest reports
"""

import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger(__name__)

FINRA_API_URL = "https://api.finra.org/data/group/otcMarket/name/ConsolidatedShortInterest"


class ShortInterestService:

    def __init__(self, db):
        self.db = db

    async def store_ib_short_data(self, data: List[Dict]) -> Dict:
        """Store IB shortable shares data pushed from the local IB data pusher."""
        if not data:
            return {"stored": 0}

        from pymongo import UpdateOne
        ops = []
        for item in data:
            symbol = item.get("symbol", "").upper()
            if not symbol:
                continue
            ops.append(UpdateOne(
                {"symbol": symbol},
                {"$set": {
                    "symbol": symbol,
                    "shortable_shares": item.get("shortable_shares", 0),
                    "shortable_level": item.get("shortable_level", 0),
                    "last_updated": item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "source": "ib_gateway",
                }},
                upsert=True,
            ))

        if ops:
            result = self.db["ib_short_data"].bulk_write(ops, ordered=False)
            stored = result.upserted_count + result.modified_count
            logger.info(f"Stored IB short data for {stored} symbols")
            return {"stored": stored}
        return {"stored": 0}

    async def fetch_finra_short_interest(self, symbols: List[str] = None, settlement_date: str = None) -> Dict:
        """
        Fetch short interest data from FINRA's free Consolidated API.
        Includes NYSE, NASDAQ, and OTC data.
        Filters to ADV-qualifying symbols to keep storage efficient.
        """
        try:
            payload = {"limit": 5000}

            if settlement_date:
                payload["filter"] = [{
                    "fieldName": "settlementDate",
                    "fieldValueOperator": "eq",
                    "fieldValue": settlement_date,
                }]

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    FINRA_API_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

                if response.status_code != 200:
                    logger.error(f"FINRA API error: {response.status_code}")
                    return {"success": False, "error": f"FINRA API returned {response.status_code}"}

                records = response.json()

            if not records:
                return {"success": True, "records": 0, "message": "No data returned"}

            # Filter to qualifying symbols (ADV >= 500K) to avoid storing junk
            qualifying = None
            try:
                adv_symbols = set()
                for doc in self.db["symbol_adv_cache"].find({"avg_volume": {"$gte": 500000}}, {"symbol": 1, "_id": 0}):
                    adv_symbols.add(doc.get("symbol", "").upper())
                if adv_symbols:
                    qualifying = adv_symbols
            except Exception:
                pass

            from pymongo import UpdateOne
            ops = []
            stored_count = 0
            settle_date = ""

            for record in records:
                symbol = record.get("symbolCode", record.get("issueSymbolIdentifier", "")).upper()
                if not symbol:
                    continue

                if symbols and symbol not in [s.upper() for s in symbols]:
                    continue

                if qualifying and symbol not in qualifying:
                    continue

                short_interest = record.get("currentShortPositionQuantity", record.get("currentShortShareNumber", 0))
                prev_short_interest = record.get("previousShortPositionQuantity", record.get("previousShortShareNumber", 0))
                change_pct = record.get("changePercent", 0)
                adv = record.get("averageDailyVolumeQuantity", record.get("averageShortShareNumber", 0))
                days_to_cover = record.get("daysToCoverQuantity", record.get("daysToCoverNumber", 0))
                settle_date = record.get("settlementDate", settlement_date or "")
                market_class = record.get("marketClassCode", record.get("marketCategoryCode", ""))

                ops.append(UpdateOne(
                    {"symbol": symbol, "settlement_date": settle_date},
                    {"$set": {
                        "symbol": symbol,
                        "settlement_date": settle_date,
                        "short_interest": short_interest,
                        "prev_short_interest": prev_short_interest,
                        "change_pct": change_pct,
                        "avg_daily_volume": adv,
                        "days_to_cover": days_to_cover,
                        "market_class": market_class,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "source": "finra",
                    }},
                    upsert=True,
                ))
                stored_count += 1

            if ops:
                result = self.db["finra_short_interest"].bulk_write(ops, ordered=False)
                actual_stored = result.upserted_count + result.modified_count
                logger.info(f"Stored FINRA short interest for {actual_stored} symbols (settlement: {settle_date})")

            return {
                "success": True,
                "records": stored_count,
                "settlement_date": settle_date if stored_count > 0 else None,
                "total_from_api": len(records),
                "filtered_by_adv": qualifying is not None,
            }

        except Exception as e:
            logger.error(f"FINRA fetch error: {e}")
            return {"success": False, "error": str(e)}

    async def get_short_data_for_symbol(self, symbol: str) -> Dict:
        """Get combined short data for a symbol from both IB and FINRA."""
        symbol = symbol.upper()
        result = {"symbol": symbol, "ib_data": None, "finra_data": None}

        ib_doc = self.db["ib_short_data"].find_one({"symbol": symbol}, {"_id": 0})
        if ib_doc:
            result["ib_data"] = ib_doc

        finra_doc = self.db["finra_short_interest"].find_one(
            {"symbol": symbol}, {"_id": 0}, sort=[("settlement_date", -1)]
        )
        if finra_doc:
            result["finra_data"] = finra_doc

        result["shortable"] = True
        result["shortable_level"] = "unknown"

        if ib_doc:
            level = ib_doc.get("shortable_level", 0)
            result["shortable_shares"] = ib_doc.get("shortable_shares", 0)
            if level > 2.5:
                result["shortable_level"] = "easy"
            elif level > 1.5:
                result["shortable_level"] = "available"
            else:
                result["shortable_level"] = "hard_to_borrow"
                result["shortable"] = False

        if finra_doc:
            result["short_interest"] = finra_doc.get("short_interest", 0)
            result["days_to_cover"] = finra_doc.get("days_to_cover", 0)
            result["si_change_pct"] = finra_doc.get("change_pct", 0)

        return result

    async def get_short_data_bulk(self, symbols: List[str] = None, limit: int = 100) -> List[Dict]:
        """Get short data for multiple symbols (combined IB + FINRA)."""
        pipeline = [
            {"$sort": {"settlement_date": -1}},
            {"$group": {
                "_id": "$symbol",
                "short_interest": {"$first": "$short_interest"},
                "prev_short_interest": {"$first": "$prev_short_interest"},
                "change_pct": {"$first": "$change_pct"},
                "days_to_cover": {"$first": "$days_to_cover"},
                "settlement_date": {"$first": "$settlement_date"},
                "avg_daily_volume": {"$first": "$avg_daily_volume"},
            }},
            {"$limit": limit},
        ]
        if symbols:
            pipeline.insert(0, {"$match": {"symbol": {"$in": [s.upper() for s in symbols]}}})

        finra_map = {}
        for doc in self.db["finra_short_interest"].aggregate(pipeline):
            finra_map[doc["_id"]] = doc

        ib_query = {"symbol": {"$in": [s.upper() for s in symbols]}} if symbols else {}
        ib_map = {}
        for doc in self.db["ib_short_data"].find(ib_query, {"_id": 0}).limit(limit):
            ib_map[doc["symbol"]] = doc

        all_symbols = set(list(finra_map.keys()) + list(ib_map.keys()))
        if symbols:
            all_symbols = all_symbols.intersection(set(s.upper() for s in symbols))

        results = []
        for sym in sorted(all_symbols):
            entry = {"symbol": sym}
            ib = ib_map.get(sym)
            finra = finra_map.get(sym)

            if ib:
                entry["shortable_shares"] = ib.get("shortable_shares", 0)
                entry["shortable_level"] = ib.get("shortable_level", 0)
                entry["ib_updated"] = ib.get("last_updated", "")

            if finra:
                entry["short_interest"] = finra.get("short_interest", 0)
                entry["prev_short_interest"] = finra.get("prev_short_interest", 0)
                entry["si_change_pct"] = finra.get("change_pct", 0)
                entry["days_to_cover"] = finra.get("days_to_cover", 0)
                entry["settlement_date"] = finra.get("settlement_date", "")
                entry["avg_daily_volume"] = finra.get("avg_daily_volume", 0)

            results.append(entry)

        return results

    async def ensure_indexes(self):
        """Create indexes for short data collections."""
        self.db["ib_short_data"].create_index("symbol", unique=True)
        self.db["finra_short_interest"].create_index([("symbol", 1), ("settlement_date", -1)])
        self.db["finra_short_interest"].create_index("settlement_date")
        logger.info("Short data indexes created")
