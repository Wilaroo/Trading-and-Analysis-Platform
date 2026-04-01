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
import asyncio
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
            result = await asyncio.to_thread(
                self.db["ib_short_data"].bulk_write, ops, ordered=False
            )
            stored = result.upserted_count + result.modified_count
            logger.info(f"Stored IB short data for {stored} symbols")
            return {"stored": stored}
        return {"stored": 0}

    async def _discover_latest_settlement_date(self) -> str:
        """Probe FINRA to find the most recent available settlement date."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        # FINRA publishes bi-monthly (~every 2 weeks). Probe narrow windows
        # starting from the most recent, expanding if empty.
        for days_back in [15, 30, 45, 60]:
            start = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
            end = (now - timedelta(days=max(0, days_back - 15))).strftime("%Y-%m-%d") if days_back > 15 else now.strftime("%Y-%m-%d")
            # For the first window, end = today
            if days_back == 15:
                end = now.strftime("%Y-%m-%d")

            payload = {
                "limit": 1,
                "offset": 0,
                "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": start, "endDate": end}],
            }
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(FINRA_API_URL, json=payload, headers=headers)
                if resp.status_code == 200 and resp.json():
                    date = resp.json()[0].get("settlementDate", "")
                    logger.info(f"FINRA discovery: found date {date} in window {start}..{end}")
                    return date
            except Exception:
                continue

        # Fallback: broad 90-day window, use the date from the first record
        start = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        payload = {"limit": 1, "offset": 0, "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": start, "endDate": now.strftime("%Y-%m-%d")}]}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(FINRA_API_URL, json=payload, headers=headers)
            if resp.status_code == 200 and resp.json():
                return resp.json()[0].get("settlementDate", "")
        except Exception:
            pass
        return ""

    async def fetch_finra_short_interest(self, symbols: List[str] = None, settlement_date: str = None, force: bool = False) -> Dict:
        """
        Fetch short interest from FINRA's free Consolidated API.
        - Auto-discovers latest settlement date if none provided
        - Skips if we already have that date fully populated (unless force=True)
        - Fetches ONLY the target date (no multi-date bloat)
        - Filters to ADV-qualifying symbols
        - Upserts by symbol only (1 record per symbol, latest wins)
        - Cleans up older settlement dates after successful fetch
        """
        try:
            # 1. Determine target settlement date
            target_date = settlement_date
            if not target_date:
                target_date = await self._discover_latest_settlement_date()
                if not target_date:
                    return {"success": False, "error": "Could not discover latest FINRA settlement date"}

            # 2. Check if we already have this date fully populated
            if not force:
                existing = self.db["finra_short_interest"].count_documents({"settlement_date": target_date})
                if existing >= 2000:  # ~2500 qualifying symbols expected
                    logger.info(f"FINRA date {target_date} already populated ({existing} records). Use force=True to re-fetch.")
                    return {
                        "success": True,
                        "records": existing,
                        "settlement_date": target_date,
                        "total_from_api": 0,
                        "skipped": True,
                        "message": f"Already have {existing} records for {target_date}. Use force=true to re-fetch.",
                    }

            # 3. Load qualifying symbols
            qualifying = None
            try:
                adv_symbols = set()
                for doc in self.db["symbol_adv_cache"].find({"avg_volume": {"$gte": 500000}}, {"symbol": 1, "_id": 0}):
                    adv_symbols.add(doc.get("symbol", "").upper())
                if adv_symbols:
                    qualifying = adv_symbols
                    logger.info(f"ADV filter loaded: {len(qualifying)} qualifying symbols")
            except Exception as e:
                logger.warning(f"Could not load ADV cache: {e}")

            symbols_upper = set(s.upper() for s in symbols) if symbols else None

            # 4. Paginate ONLY for the target date
            date_filter = [{"fieldName": "settlementDate", "startDate": target_date, "endDate": target_date}]
            from pymongo import UpdateOne
            total_stored = 0
            total_from_api = 0
            total_skipped_adv = 0
            offset = 0
            page_size = 5000
            max_pages = 5  # Single date has ~10-15K records, 3 pages is plenty

            for page in range(max_pages):
                payload = {
                    "limit": page_size,
                    "offset": offset,
                    "dateRangeFilters": date_filter,
                }

                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        FINRA_API_URL, json=payload,
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                    )

                if response.status_code != 200:
                    logger.error(f"FINRA API error page {page}: {response.status_code}")
                    break

                records = response.json()
                total_from_api += len(records)
                logger.info(f"FINRA page {page+1} (offset {offset}): {len(records)} records for {target_date}")

                if not records:
                    break

                ops = []
                for record in records:
                    symbol = record.get("symbolCode", "").upper().strip()
                    if not symbol:
                        continue
                    if symbols_upper and symbol not in symbols_upper:
                        continue
                    if qualifying and symbol not in qualifying:
                        total_skipped_adv += 1
                        continue

                    ops.append(UpdateOne(
                        {"symbol": symbol},
                        {"$set": {
                            "symbol": symbol,
                            "settlement_date": target_date,
                            "short_interest": record.get("currentShortPositionQuantity", 0),
                            "prev_short_interest": record.get("previousShortPositionQuantity", 0),
                            "change_pct": record.get("changePercent", 0),
                            "avg_daily_volume": record.get("averageDailyVolumeQuantity", 0),
                            "days_to_cover": record.get("daysToCoverQuantity", 0),
                            "market_class": record.get("marketClassCode", ""),
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "source": "finra",
                        }},
                        upsert=True,
                    ))

                if ops:
                    result = self.db["finra_short_interest"].bulk_write(ops, ordered=False)
                    page_stored = result.upserted_count + result.modified_count
                    total_stored += page_stored
                    logger.info(f"FINRA page {page+1}: stored {page_stored} (total: {total_stored})")

                if len(records) < page_size:
                    break
                offset += page_size

            # 5. Clean up old settlement dates (keep only the latest)
            if total_stored > 0:
                deleted = self.db["finra_short_interest"].delete_many(
                    {"settlement_date": {"$ne": target_date, "$exists": True}}
                )
                if deleted.deleted_count > 0:
                    logger.info(f"Cleaned up {deleted.deleted_count} stale records from older settlement dates")

            logger.info(f"FINRA fetch complete: {total_stored} stored, {total_skipped_adv} skipped (not in ADV), {total_from_api} from API")
            return {
                "success": True,
                "records": total_stored,
                "settlement_date": target_date,
                "total_from_api": total_from_api,
                "filtered_by_adv": qualifying is not None,
                "adv_qualifying_count": len(qualifying) if qualifying else 0,
                "skipped_not_qualifying": total_skipped_adv,
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
        """Get short data for multiple symbols (combined IB + FINRA). Single record per symbol."""
        query = {}
        if symbols:
            query["symbol"] = {"$in": [s.upper() for s in symbols]}

        finra_map = {}
        for doc in self.db["finra_short_interest"].find(query, {"_id": 0}).limit(limit):
            finra_map[doc["symbol"]] = doc

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
        self.db["finra_short_interest"].create_index("symbol", unique=True)
        self.db["finra_short_interest"].create_index("settlement_date")
        logger.info("Short data indexes created")
