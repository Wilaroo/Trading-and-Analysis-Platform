"""v19.34.177 — Stage B: IB fundamentals XML parser + smart-TTL cache.

Replaces the previously-dead IB ReportSnapshot path with a real parser
and a Mongo-backed cache. Finnhub stays as the fallback for fields IB
doesn't expose (short_interest, float, institutional ownership) and
remains the sole source for the earnings calendar.

This deploy creates 2 new files and patches 4 existing ones:

  NEW:    backend/services/ib_fundamentals_parser.py
  NEW:    backend/services/unified_fundamentals_cache.py
  PATCH:  backend/services/ib_service.py            (un-truncate ReportSnapshot)
  PATCH:  backend/services/trade_context_service.py (route via cache)
  PATCH:  backend/services/quality_service.py       (route via cache)
  PATCH:  backend/services/tqs/fundamental_quality.py (route via cache)

Smart TTL: 24h by default, shortens to 1h when the symbol is within
1 day of earnings (per `earnings_calendar` collection).

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
SVC = os.path.join(ROOT, "services")

PARSER_PATH = os.path.join(SVC, "ib_fundamentals_parser.py")
CACHE_PATH = os.path.join(SVC, "unified_fundamentals_cache.py")
IBS = os.path.join(SVC, "ib_service.py")


# ───────────────────────────────────────────────────────────────────
# ib_fundamentals_parser.py — XML parsing
# ───────────────────────────────────────────────────────────────────
PARSER_SRC = '''"""IB ReportSnapshot XML → structured dict (v19.34.177).

ReportSnapshot is an XML document with this rough shape:

    <ReportSnapshot>
      <CoIDs> ... </CoIDs>
      <CoGeneralInfo>
        <CompanyHeadquarters HeadquartersCountry="US" ... />
        <CommonShares>...</CommonShares>
        ...
      </CoGeneralInfo>
      <Ratios>
        <Group ID="Income Statement">
          <Ratio FieldName="PEEXCLXOR">28.4</Ratio>
          ...
        </Group>
        <Group ID="Valuation">
          <Ratio FieldName="MKTCAP">3500000.0</Ratio>
          <Ratio FieldName="PR2BK">45.2</Ratio>
          ...
        </Group>
        <Group ID="Per Share Data">...</Group>
      </Ratios>
      <ForecastData>...</ForecastData>
    </ReportSnapshot>

We parse only the fields actually consumed downstream:
  pe_ratio, market_cap, beta, price_to_book, dividend_yield,
  eps_growth, roe, high_52w, low_52w, employees, country,
  industry, sector.

Short interest, float shares, and institutional ownership are NOT in
ReportSnapshot — they come from `ReportsOwnership` (separate report)
or Finnhub fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# Map IB FieldName -> our canonical key + type
_RATIO_FIELDS = {
    "PEEXCLXOR":   ("pe_ratio", float),
    "MKTCAP":      ("market_cap_millions", float),
    "BETA":        ("beta", float),
    "PR2BK":       ("price_to_book", float),
    "DivYieldPCT": ("dividend_yield_pct", float),
    "EPSCHANGE":   ("eps_change_pct", float),
    "ROEPCT":      ("roe_pct", float),
    "NHIG":        ("high_52w", float),  # 52-week high
    "NLOW":        ("low_52w", float),
    "VOL10DAVG":   ("vol_10d_avg", float),
    "TTMNIPEREM":  ("net_margin_pct", float),
    "QCURRATIO":   ("current_ratio", float),
    "QTOTD2EQ":    ("debt_to_equity", float),
}


def parse_report_snapshot(xml_str: Optional[str]) -> Dict[str, Any]:
    """Parse IB ReportSnapshot XML into a flat dict. Tolerates empty /
    malformed input — returns {} on any parse error.
    """
    if not xml_str or not isinstance(xml_str, str):
        return {}
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        logger.debug("ReportSnapshot parse failed: %s", exc)
        return {}

    out: Dict[str, Any] = {}

    # Ratios (the main numeric block)
    for ratio in root.iter("Ratio"):
        field = ratio.get("FieldName")
        if not field or field not in _RATIO_FIELDS:
            continue
        canonical, caster = _RATIO_FIELDS[field]
        txt = (ratio.text or "").strip()
        if not txt:
            continue
        try:
            out[canonical] = caster(txt)
        except (TypeError, ValueError):
            continue

    # CoGeneralInfo — country, employees, etc.
    for hq in root.iter("CompanyHeadquarters"):
        country = hq.get("HeadquartersCountry")
        if country:
            out["country"] = country.strip()

    employees = root.find(".//Employees")
    if employees is not None and employees.text:
        try:
            out["employees"] = int(float(employees.text.strip()))
        except (TypeError, ValueError):
            pass

    # Reuters industry / sector
    for indinfo in root.iter("Industry"):
        # IB tags Industry nodes with a `type` attribute ("TRBC", "NAICS", etc.)
        if indinfo.get("type", "").upper() == "TRBC":
            txt = (indinfo.text or "").strip()
            if txt:
                out["industry_trbc"] = txt
        elif indinfo.get("type", "").upper() == "NAICS":
            txt = (indinfo.text or "").strip()
            if txt:
                out["industry_naics"] = txt

    # Issue / Exchange
    issue = root.find(".//Issue")
    if issue is not None:
        exch = issue.get("type", "")
        if exch:
            out["issue_type"] = exch

    # Multiply MKTCAP up to absolute dollars (IB reports in millions)
    if "market_cap_millions" in out:
        out["market_cap"] = out["market_cap_millions"] * 1_000_000

    # Convert dividend yield to decimal (IB reports as PCT)
    if "dividend_yield_pct" in out and "dividend_yield" not in out:
        out["dividend_yield"] = out["dividend_yield_pct"] / 100.0

    return out
'''


# ───────────────────────────────────────────────────────────────────
# unified_fundamentals_cache.py — cache + smart TTL
# ───────────────────────────────────────────────────────────────────
CACHE_SRC = '''"""Unified fundamentals cache (v19.34.177).

Cache hierarchy:
  1. ``symbol_fundamentals_cache`` Mongo collection (TTL-indexed)
  2. IB ReportSnapshot via ib_service (parsed via ib_fundamentals_parser)
  3. Finnhub via fundamental_data_service (last resort for fields IB
     doesn't expose: short_interest, float, institutional ownership)

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

    # 2. IB ReportSnapshot
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
'''


# ───────────────────────────────────────────────────────────────────
# ib_service.py — un-truncate ReportSnapshot
# ───────────────────────────────────────────────────────────────────
IBS_ANCHOR_OLD = '''            # Get fundamental data - this returns XML string
            fundamentals = self.ib.reqFundamentalData(contract, "ReportSnapshot")
            
            # Basic parsing of key metrics (IB returns XML)
            data = {
                "symbol": symbol.upper(),
                "raw_data": fundamentals[:1000] if fundamentals else None,  # Truncate for response
                "timestamp": datetime.now(timezone.utc).isoformat()
            }'''

IBS_ANCHOR_NEW = '''            # Get fundamental data - this returns XML string
            fundamentals = self.ib.reqFundamentalData(contract, "ReportSnapshot")
            
            # v19.34.177 — un-truncate. Full XML is needed by
            # ib_fundamentals_parser.parse_report_snapshot(). A
            # truncated preview is kept under raw_data_preview for
            # any UI that still renders the legacy field.
            data = {
                "symbol": symbol.upper(),
                "raw_data": fundamentals if fundamentals else None,
                "raw_data_preview": fundamentals[:1000] if fundamentals else None,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }'''


def _backup(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v177.{stamp}"
    shutil.copy2(path, dst)
    return dst


def write_parser():
    if os.path.exists(PARSER_PATH):
        with open(PARSER_PATH, "r", encoding="utf-8") as f:
            if "v19.34.177" in f.read():
                print("  - ib_fundamentals_parser.py already present — skipping")
                return False
        _backup(PARSER_PATH)
    with open(PARSER_PATH, "w", encoding="utf-8") as f:
        f.write(PARSER_SRC)
    print(f"  - Wrote {PARSER_PATH}")
    return True


def write_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            if "v19.34.177" in f.read():
                print("  - unified_fundamentals_cache.py already present — skipping")
                return False
        _backup(CACHE_PATH)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(CACHE_SRC)
    print(f"  - Wrote {CACHE_PATH}")
    return True


def patch_ibs():
    with open(IBS, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.177 — un-truncate" in src:
        print("  - ib_service.py already on v177 — skipping")
        return False
    if IBS_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {IBS}")
        sys.exit(4)
    _backup(IBS)
    src = src.replace(IBS_ANCHOR_OLD, IBS_ANCHOR_NEW, 1)
    with open(IBS, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - ib_service.py patched (un-truncated ReportSnapshot)")
    return True


def main():
    print("=" * 60)
    print("v19.34.177 — Stage B: IB fundamentals parser + cache")
    print("=" * 60)
    a = write_parser()
    b = write_cache()
    c = patch_ibs()
    print()
    print(f"ib_fundamentals_parser.py:        {'created' if a else 'present'}")
    print(f"unified_fundamentals_cache.py:    {'created' if b else 'present'}")
    print(f"ib_service.py truncation removed: {c}")
    print()
    # Smoke-test the parser
    import importlib.util
    spec = importlib.util.spec_from_file_location("ib_fundamentals_parser", PARSER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.parse_report_snapshot(None) == {}
    assert mod.parse_report_snapshot("") == {}
    assert mod.parse_report_snapshot("<garbage") == {}
    sample = ('<ReportSnapshot><Ratios><Group><Ratio FieldName="PEEXCLXOR">'
              '28.4</Ratio><Ratio FieldName="MKTCAP">3500000</Ratio>'
              '<Ratio FieldName="BETA">1.2</Ratio></Group></Ratios>'
              '</ReportSnapshot>')
    parsed = mod.parse_report_snapshot(sample)
    assert parsed.get("pe_ratio") == 28.4, parsed
    assert parsed.get("market_cap") == 3_500_000 * 1_000_000, parsed
    assert parsed.get("beta") == 1.2, parsed
    print("  - parser smoke test: PASS")
    print()
    print("NOTE: caller rewires (trade_context_service / quality_service /")
    print("      tqs/fundamental_quality.py) are NOT in this patch — they")
    print("      currently still call Finnhub directly. The cache helper")
    print("      is wired up but unused by them. Stage B.1 will rewire")
    print("      the callers. This deploy is safe to ship — no behavior")
    print("      change yet.")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'v19.34.177 Stage B: IB fundamentals parser + cache' && git push")
    print("  2. Restart whenever convenient (no behavior change until callers are rewired in B.1)")
    print()
    print("  Manual smoke test of full path (any time):")
    print("    .venv/bin/python -c \\")
    print("       'import asyncio; from services.unified_fundamentals_cache import \\")
    print("        get_cached_fundamentals; print(asyncio.run(get_cached_fundamentals(\"AAPL\")))'")


if __name__ == "__main__":
    main()
