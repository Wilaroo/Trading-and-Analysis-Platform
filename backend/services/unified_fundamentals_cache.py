"""Unified fundamentals cache (v19.34.202).

Cache hierarchy:
  1. ``symbol_fundamentals_cache`` Mongo collection (TTL-indexed)
  2. IB ReportSnapshot via ib_direct (live clientId-11 socket) — carries
     valuation + float + shares-outstanding (``<SharesOut TotalFloat=...>``).
     Falls back to the legacy ib_service worker only if ib_direct is down.
  3. Finnhub via fundamental_data_service (valuation cross-check / fallback)
  4. FINRA short-interest shares ÷ IB shares-outstanding → ``short_interest_percent``

Smart TTL:
  * 24h normally
  * 1h when the symbol is within 1 day of earnings (per the
    ``earnings_calendar`` collection — fundamentals can change
    materially overnight on earnings day).

All callers (trade_context_service, quality_service,
tqs/fundamental_quality) should now go through ``get_cached_fundamentals``
rather than calling IB / Finnhub directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COLLECTION = "symbol_fundamentals_cache"
INSTITUTIONAL_COLLECTION = "institutional_ownership_cache"
DEFAULT_TTL_HOURS = 24
EARNINGS_PROXIMITY_TTL_HOURS = 1  # within 1d of earnings → fresh data more often


_db = None  # Lazy-initialised


def _get_db():
    global _db
    if _db is not None:
        return _db
    try:
        import os
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"), serverSelectionTimeoutMS=2000)
        _db = client[os.environ.get("DB_NAME", "tradecommand")]
        # Ensure TTL index on expires_at
        try:
            _db[COLLECTION].create_index(
                "expires_at", expireAfterSeconds=0, background=True
            )
            _db[COLLECTION].create_index("symbol", unique=True, background=True)
        except Exception:
            pass
    except Exception as exc:
        logger.debug("unified_fundamentals_cache: DB init failed: %s", exc)
    return _db


def compute_short_interest_pct(si_shares, shares_out) -> Optional[float]:
    """Short interest as a % of shares outstanding (rounded), or None if the
    inputs are missing/invalid. Pure — unit-testable without IB/Mongo."""
    try:
        if si_shares and shares_out and float(shares_out) > 0:
            return round(100.0 * float(si_shares) / float(shares_out), 2)
    except (TypeError, ValueError):
        pass
    return None


def _ttl_hours_for(symbol: str, db) -> int:
    """Smart TTL: 1h if within 1 day of earnings, else 24h."""
    if db is None:
        return DEFAULT_TTL_HOURS
    try:
        now = datetime.now(timezone.utc)
        soon = now + timedelta(days=1)
        row = db["earnings_calendar"].find_one({
            "symbol": symbol,
            "date": {"$gte": now.isoformat(), "$lte": soon.isoformat()},
        })
        if row:
            return EARNINGS_PROXIMITY_TTL_HOURS
    except Exception:
        pass
    return DEFAULT_TTL_HOURS


async def get_cached_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Return cached fundamentals for ``symbol``, fetching via IB or
    Finnhub on cache miss. Returns ``None`` only if EVERY source fails.

    Returned dict has a normalised shape (subset of):
      pe_ratio, market_cap, market_cap_millions, beta, price_to_book,
      dividend_yield, dividend_yield_pct, eps_change_pct, roe_pct,
      high_52w, low_52w, country, industry_trbc, industry_naics,
      employees, short_interest_percent, float_shares,
      institutional_ownership_percent
    plus metadata: ``source``, ``fetched_at``, ``expires_at``.
    """
    if not symbol:
        return None
    symbol = symbol.upper()
    db = _get_db()

    # 1. Mongo cache hit?
    if db is not None:
        try:
            cached = db[COLLECTION].find_one({"symbol": symbol})
            if cached:
                # TTL index removes expired docs automatically — but
                # double-check in case the sweep hasn't run yet.
                exp = cached.get("expires_at")
                if isinstance(exp, datetime) and exp > datetime.now(timezone.utc):
                    return cached
        except Exception as exc:
            logger.debug("Cache read failed for %s: %s", symbol, exc)

    merged: Dict[str, Any] = {"symbol": symbol}
    source_chain = []

    # 2. IB ReportSnapshot — prefer the LIVE ib_direct socket (clientId 11).
    # The legacy ib_service worker is usually disconnected on this deploy
    # (which is why every cached doc historically came from Finnhub), so
    # ib_direct is the real IB path. ReportSnapshot is ~10KB and carries
    # float + shares-outstanding via <SharesOut TotalFloat=...>. (v19.34.202)
    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_report_snapshot
        ibd = get_ib_direct_service()
        if ibd is not None and ibd.is_connected():
            xml = await ibd.get_fundamental_report(symbol, "ReportSnapshot")
            if xml:
                parsed = parse_report_snapshot(xml)
                if parsed:
                    merged.update(parsed)
                    source_chain.append("ib_direct_report_snapshot")
    except Exception as exc:
        logger.debug("ib_direct fundamentals lookup failed for %s: %s", symbol, exc)

    # 2b. Legacy ib_service ReportSnapshot — only if ib_direct didn't deliver.
    if "ib_direct_report_snapshot" not in source_chain:
        try:
            from services.ib_service import get_ib_service
            from services.ib_fundamentals_parser import parse_report_snapshot
            ib = get_ib_service()
            if ib is not None:
                status = ib.get_connection_status()
                if status and status.get("connected"):
                    ib_resp = await ib.get_fundamentals(symbol)
                    if ib_resp and ib_resp.get("success"):
                        raw = (ib_resp.get("data") or {}).get("raw_data") or ""
                        parsed = parse_report_snapshot(raw)
                        if parsed:
                            merged.update(parsed)
                            source_chain.append("ib_report_snapshot")
        except Exception as exc:
            logger.debug("IB fundamentals lookup failed for %s: %s", symbol, exc)

    # 3. Finnhub supplement (fills fields IB doesn't expose + valuation
    # cross-check)
    needs_finnhub = (
        "pe_ratio" not in merged
        or "market_cap" not in merged
        or "beta" not in merged
    )
    if needs_finnhub:
        try:
            from services.fundamental_data_service import get_fundamental_data_service
            fund_svc = get_fundamental_data_service()
            fdata = await fund_svc.get_fundamentals(symbol)
            if fdata is not None:
                if "pe_ratio" not in merged and fdata.pe_ratio is not None:
                    merged["pe_ratio"] = fdata.pe_ratio
                if "market_cap" not in merged and fdata.market_cap is not None:
                    merged["market_cap"] = fdata.market_cap
                if "beta" not in merged and fdata.beta is not None:
                    merged["beta"] = fdata.beta
                if "dividend_yield" not in merged and fdata.dividend_yield is not None:
                    merged["dividend_yield"] = fdata.dividend_yield
                if "high_52w" not in merged and fdata.high_52_week is not None:
                    merged["high_52w"] = fdata.high_52_week
                if "low_52w" not in merged and fdata.low_52_week is not None:
                    merged["low_52w"] = fdata.low_52_week
                source_chain.append("finnhub")
        except Exception as exc:
            logger.debug("Finnhub fundamentals lookup failed for %s: %s", symbol, exc)

    # 3.5 Short-interest % — FINRA short-interest shares ÷ shares-outstanding.
    # Float/shares come from IB ReportSnapshot above; FINRA gives raw short
    # shares (no %). This is the only place we can compute a real SI%. The
    # FINRA feed is bi-monthly (that IS the accurate cadence — there is no
    # realtime short interest). (v19.34.202)
    shares_out = merged.get("shares_outstanding") or merged.get("float_shares")
    if shares_out and float(shares_out) > 0 and db is not None:
        try:
            from services.short_interest_service import ShortInterestService
            si = await ShortInterestService(db).get_short_data_for_symbol(symbol)
            si_shares = (si or {}).get("short_interest")
            pct = compute_short_interest_pct(si_shares, shares_out)
            if pct is not None:
                merged["short_interest_percent"] = pct
                if (si or {}).get("days_to_cover") is not None:
                    merged["days_to_cover"] = si["days_to_cover"]
                source_chain.append("finra_short")
        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)

    # 3.6 Institutional ownership % — merged from the separately-maintained
    # `institutional_ownership_cache` (populated weekly by
    # refresh_institutional_ownership; the IB ReportsOwnership doc is multi-MB
    # so it can't live in this 24h hot path). (v19.34.204)
    if db is not None:
        try:
            inst = db[INSTITUTIONAL_COLLECTION].find_one({"symbol": symbol})
            if inst and inst.get("institutional_ownership_percent") is not None:
                merged["institutional_ownership_percent"] = \
                    inst["institutional_ownership_percent"]
                source_chain.append("ib_ownership")
        except Exception as exc:
            logger.debug("Institutional ownership lookup failed for %s: %s",
                         symbol, exc)

    if not source_chain:
        return None

    # 4. Persist with smart TTL
    ttl_hours = _ttl_hours_for(symbol, db)
    now = datetime.now(timezone.utc)
    merged["fetched_at"] = now
    merged["expires_at"] = now + timedelta(hours=ttl_hours)
    merged["source"] = "+".join(source_chain)
    merged["ttl_hours"] = ttl_hours

    if db is not None:
        try:
            db[COLLECTION].update_one(
                {"symbol": symbol}, {"$set": merged}, upsert=True
            )
        except Exception as exc:
            logger.debug("Cache write failed for %s: %s", symbol, exc)

    return merged



async def refresh_institutional_ownership(symbol: str, db=None) -> Optional[float]:
    """v19.34.204 — fetch IB ReportsOwnership (multi-MB) for ``symbol`` via the
    live ib_direct socket, compute institutional ownership %, and upsert it into
    ``institutional_ownership_cache``. Returns the % or None.

    MUST run inside the backend process (where the clientId-11 socket lives).
    Heavy (3–6 MB/symbol) → intended for a weekly off-hours job, NOT the hot
    path. shares-outstanding is read from the existing fundamentals cache
    (populated by ReportSnapshot) so we express ownership as % of shares-out.
    """
    if db is None:
        db = _get_db()
    if db is None:
        return None
    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_reports_ownership
        ibd = get_ib_direct_service()
        if ibd is None or not ibd.is_connected():
            return None

        shares_out = None
        cached = db[COLLECTION].find_one({"symbol": symbol},
                                         {"shares_outstanding": 1})
        if cached:
            shares_out = cached.get("shares_outstanding")

        xml = await ibd.get_fundamental_report(symbol, "ReportsOwnership",
                                               timeout=60.0)
        if not xml:
            return None
        parsed = parse_reports_ownership(xml, shares_outstanding=shares_out)
        pct = parsed.get("institutional_ownership_percent")
        if pct is None:
            return None
        db[INSTITUTIONAL_COLLECTION].update_one(
            {"symbol": symbol},
            {"$set": {
                "symbol": symbol,
                "institutional_ownership_percent": pct,
                "num_institutional_holders": parsed.get("num_institutional_holders"),
                "float_shares_ownership": parsed.get("float_shares"),
                "fetched_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return pct
    except Exception as exc:
        logger.debug("refresh_institutional_ownership failed for %s: %s",
                     symbol, exc)
        return None
