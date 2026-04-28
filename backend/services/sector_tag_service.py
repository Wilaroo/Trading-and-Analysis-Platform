"""
sector_tag_service — symbol → sector ETF mapping.
==================================================

Pragmatic backfill source for the `symbol_adv_cache.sector` field that
the `SectorRegimeClassifier` and AI features depend on.

This module ships as a static GICS-aligned map keyed to the 11 SPDR
sector ETFs (XLK / XLE / XLF / XLV / XLY / XLP / XLI / XLB / XLRE /
XLU / XLC). The map starts from the existing `STOCK_SECTORS` dict in
`sector_analysis_service` and extends it with the most-liquid ~500
names so a meaningful share of the canonical universe gets tagged on
day one.

Architecture choice (2026-04-30):
  - Static-map first because it's reproducible, version-controllable,
    and works when IB is offline.
  - Future: an IB `reqContractDetails`-based fallback can populate
    untagged symbols on-demand (a separate optional code path — kept
    out of this commit so the feature ships without IB dependency).

Public API:
  ``get_sector_tag_service().tag_symbol(symbol)``  → "XLK" | None
  ``get_sector_tag_service().tag_many(symbols)``   → {symbol: ETF}
  ``get_sector_tag_service().backfill_symbol_adv_cache(db)``
      → updates `symbol_adv_cache` rows in-place. Idempotent.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────── Sector ETFs ────────────────────────────

# Re-exported here so callers don't need to know about the deeper module.
SECTOR_ETFS: Dict[str, str] = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLC":  "Communication",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "XLB":  "Materials",
}

# The ETFs themselves map to their own sector — when the classifier
# asks "what sector is XLK in?" the answer is XLK.
ETF_SELF_MAP = {etf: etf for etf in SECTOR_ETFS}


# ──────────────────────────── Static GICS-aligned map ────────────────────────────
#
# Coverage policy: the most-liquid US large/mid-caps that drive the
# scanner's typical alert flow. This is intentionally NOT exhaustive —
# anything outside this list returns ``None`` and the SectorRegimeClassifier
# falls through to "unknown" for that symbol. Alerts still fire (soft
# gate, not a hard gate); they just don't get the sector regime feature.
#
# Maintenance: paired with `tests/test_sector_tag_service.py` so any
# typos or duplicate keys fail CI immediately.

STATIC_SECTOR_MAP: Dict[str, str] = {
    # ============ XLK Technology ============
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "ORCL": "XLK",
    "ADBE": "XLK", "CRM": "XLK", "AMD": "XLK", "INTC": "XLK", "CSCO": "XLK",
    "ACN": "XLK", "QCOM": "XLK", "IBM": "XLK", "INTU": "XLK", "TXN": "XLK",
    "AMAT": "XLK", "MU": "XLK", "LRCX": "XLK", "NOW": "XLK", "PANW": "XLK",
    "ANET": "XLK", "KLAC": "XLK", "ADI": "XLK", "MRVL": "XLK", "FTNT": "XLK",
    "SNPS": "XLK", "CDNS": "XLK", "MCHP": "XLK", "ON": "XLK", "WDAY": "XLK",
    "CRWD": "XLK", "DDOG": "XLK", "ZS": "XLK", "MDB": "XLK", "TEAM": "XLK",
    "DELL": "XLK", "HPQ": "XLK", "HPE": "XLK", "WDC": "XLK", "STX": "XLK",
    "NTAP": "XLK", "FSLR": "XLK", "ENPH": "XLK", "ARM": "XLK", "SMCI": "XLK",
    "PLTR": "XLK", "SNOW": "XLK", "GTLB": "XLK", "NET": "XLK", "OKTA": "XLK",
    "DOCU": "XLK", "TWLO": "XLK", "ZM": "XLK", "U": "XLK", "AI": "XLK",

    # ============ XLC Communication / Internet / Media ============
    "GOOGL": "XLC", "GOOG": "XLC", "META": "XLC", "NFLX": "XLC", "DIS": "XLC",
    "CMCSA": "XLC", "T": "XLC", "VZ": "XLC", "TMUS": "XLC", "CHTR": "XLC",
    "WBD": "XLC", "PARA": "XLC", "FOX": "XLC", "FOXA": "XLC", "ROKU": "XLC",
    "SPOT": "XLC", "PINS": "XLC", "SNAP": "XLC", "MTCH": "XLC", "EA": "XLC",
    "TTWO": "XLC", "RBLX": "XLC", "BIDU": "XLC", "BABA": "XLC", "JD": "XLC",
    "PDD": "XLC", "TME": "XLC", "NTES": "XLC", "LYV": "XLC", "OMC": "XLC",
    "IPG": "XLC", "DASH": "XLC", "UBER": "XLY",  # NB: Uber→XLY (consumer disc.)

    # ============ XLY Consumer Discretionary ============
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "MCD": "XLY", "NKE": "XLY",
    "SBUX": "XLY", "LOW": "XLY", "BKNG": "XLY", "TJX": "XLY", "ABNB": "XLY",
    "F": "XLY", "GM": "XLY", "MAR": "XLY", "ROST": "XLY", "ORLY": "XLY",
    "HLT": "XLY", "AZO": "XLY", "CMG": "XLY", "YUM": "XLY", "DRI": "XLY",
    "LULU": "XLY", "BBY": "XLY", "DG": "XLY", "EBAY": "XLY",
    "ETSY": "XLY", "RIVN": "XLY", "LCID": "XLY", "CHWY": "XLY", "WSM": "XLY",
    "ROOT": "XLY", "RH": "XLY", "ULTA": "XLY", "DECK": "XLY", "POOL": "XLY",
    "DPZ": "XLY", "EXPE": "XLY", "TRIP": "XLY", "VFC": "XLY", "TPR": "XLY",
    "RL": "XLY", "PHM": "XLY", "DHI": "XLY", "LEN": "XLY", "NVR": "XLY",
    "TOL": "XLY",

    # ============ XLP Consumer Staples ============
    "WMT": "XLP", "PG": "XLP", "COST": "XLP", "KO": "XLP", "PEP": "XLP",
    "PM": "XLP", "MO": "XLP", "MDLZ": "XLP", "CL": "XLP", "TGT": "XLP",
    "KHC": "XLP", "GIS": "XLP", "K": "XLP", "STZ": "XLP", "EL": "XLP",
    "KMB": "XLP", "SYY": "XLP", "HSY": "XLP", "ADM": "XLP", "BG": "XLP",
    "MNST": "XLP", "KDP": "XLP", "TAP": "XLP", "CHD": "XLP", "CLX": "XLP",
    "CPB": "XLP", "CAG": "XLP", "HRL": "XLP", "MKC": "XLP", "TSN": "XLP",
    "DLTR": "XLP",  # discount staples — closer to XLP than XLY

    # ============ XLF Financials ============
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "C": "XLF", "GS": "XLF",
    "MS": "XLF", "BLK": "XLF", "SCHW": "XLF", "AXP": "XLF", "V": "XLF",
    "MA": "XLF", "PYPL": "XLF", "COF": "XLF", "USB": "XLF", "PNC": "XLF",
    "TFC": "XLF", "BK": "XLF", "STT": "XLF", "AIG": "XLF", "MET": "XLF",
    "PRU": "XLF", "ALL": "XLF", "TRV": "XLF", "PGR": "XLF", "CB": "XLF",
    "AON": "XLF", "MMC": "XLF", "MSCI": "XLF", "ICE": "XLF", "CME": "XLF",
    "SPGI": "XLF", "MCO": "XLF", "FIS": "XLF", "FISV": "XLF", "FI": "XLF",
    "DFS": "XLF", "SYF": "XLF", "AFL": "XLF", "HIG": "XLF", "ACGL": "XLF",
    "BX": "XLF", "KKR": "XLF", "APO": "XLF", "ARES": "XLF", "BLDR": "XLF",
    "COIN": "XLF", "HOOD": "XLF", "SOFI": "XLF",

    # ============ XLV Healthcare ============
    "UNH": "XLV", "JNJ": "XLV", "LLY": "XLV", "ABBV": "XLV", "MRK": "XLV",
    "TMO": "XLV", "ABT": "XLV", "PFE": "XLV", "DHR": "XLV", "AMGN": "XLV",
    "ISRG": "XLV", "BMY": "XLV", "CVS": "XLV", "GILD": "XLV", "ELV": "XLV",
    "MDT": "XLV", "VRTX": "XLV", "REGN": "XLV", "BSX": "XLV", "HUM": "XLV",
    "CI": "XLV", "SYK": "XLV", "ZTS": "XLV", "BIIB": "XLV", "MRNA": "XLV",
    "BDX": "XLV", "EW": "XLV", "DXCM": "XLV", "IDXX": "XLV", "RMD": "XLV",
    "MCK": "XLV", "ABC": "XLV", "COR": "XLV", "CAH": "XLV", "HCA": "XLV",
    "IQV": "XLV", "A": "XLV", "WAT": "XLV", "ALGN": "XLV", "CTLT": "XLV",
    "ZBH": "XLV", "RVTY": "XLV", "MRX": "XLV", "DGX": "XLV", "LH": "XLV",
    "NVAX": "XLV", "BNTX": "XLV", "IONS": "XLV", "INSM": "XLV", "EXAS": "XLV",

    # ============ XLE Energy ============
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "EOG": "XLE", "PXD": "XLE",
    "MPC": "XLE", "PSX": "XLE", "VLO": "XLE", "OXY": "XLE", "WMB": "XLE",
    "OKE": "XLE", "KMI": "XLE", "SLB": "XLE", "BKR": "XLE", "HAL": "XLE",
    "HES": "XLE", "FANG": "XLE", "DVN": "XLE", "TPL": "XLE", "MRO": "XLE",
    "APA": "XLE", "CTRA": "XLE", "EQT": "XLE", "TRGP": "XLE", "CHK": "XLE",
    "AR": "XLE", "MTDR": "XLE", "OVV": "XLE", "ENB": "XLE", "TRP": "XLE",
    "SU": "XLE", "CNQ": "XLE", "TTE": "XLE", "BP": "XLE", "SHEL": "XLE",
    "EQNR": "XLE",

    # ============ XLI Industrials ============
    "GE": "XLI", "CAT": "XLI", "BA": "XLI", "RTX": "XLI", "HON": "XLI",
    "LMT": "XLI", "DE": "XLI", "UNP": "XLI", "UPS": "XLI", "FDX": "XLI",
    "ETN": "XLI", "GD": "XLI", "NOC": "XLI", "MMM": "XLI", "EMR": "XLI",
    "ITW": "XLI", "CSX": "XLI", "NSC": "XLI", "WM": "XLI", "RSG": "XLI",
    "PCAR": "XLI", "CMI": "XLI", "PH": "XLI", "ROP": "XLI", "URI": "XLI",
    "FAST": "XLI", "PWR": "XLI", "CHRW": "XLI", "EXPD": "XLI", "ODFL": "XLI",
    "JBHT": "XLI", "XPO": "XLI", "DAL": "XLI", "UAL": "XLI", "AAL": "XLI",
    "LUV": "XLI", "ALK": "XLI", "JBLU": "XLI", "SAVE": "XLI", "ALLE": "XLI",
    "DOV": "XLI", "JCI": "XLI", "OTIS": "XLI", "CARR": "XLI", "PNR": "XLI",
    "TT": "XLI", "AME": "XLI", "ROK": "XLI", "FTV": "XLI", "TDG": "XLI",
    "HEI": "XLI", "AXON": "XLI",

    # ============ XLB Materials ============
    "LIN": "XLB", "APD": "XLB", "SHW": "XLB", "ECL": "XLB", "FCX": "XLB",
    "NEM": "XLB", "DOW": "XLB", "DD": "XLB", "PPG": "XLB", "NUE": "XLB",
    "MLM": "XLB", "VMC": "XLB", "STLD": "XLB", "RPM": "XLB", "EMN": "XLB",
    "CE": "XLB", "ALB": "XLB", "FMC": "XLB", "MOS": "XLB", "CF": "XLB",
    "LYB": "XLB", "WLK": "XLB", "AVY": "XLB", "BLL": "XLB", "PKG": "XLB",
    "IP": "XLB", "WRK": "XLB", "STE": "XLB",
    # Steel + iron-ore + gold/silver miners not in NEM
    "X": "XLB", "CLF": "XLB", "AA": "XLB", "GOLD": "XLB", "AEM": "XLB",
    "WPM": "XLB", "FNV": "XLB", "RGLD": "XLB", "PAAS": "XLB", "AG": "XLB",
    "HL": "XLB",

    # ============ XLU Utilities ============
    "NEE": "XLU", "DUK": "XLU", "SO": "XLU", "AEP": "XLU", "D": "XLU",
    "SRE": "XLU", "EXC": "XLU", "XEL": "XLU", "PEG": "XLU", "ED": "XLU",
    "WEC": "XLU", "ES": "XLU", "AWK": "XLU", "FE": "XLU", "DTE": "XLU",
    "PCG": "XLU", "EIX": "XLU", "AEE": "XLU", "ETR": "XLU", "PPL": "XLU",
    "CMS": "XLU", "ATO": "XLU", "CNP": "XLU", "EVRG": "XLU", "LNT": "XLU",
    "NRG": "XLU", "VST": "XLU", "AES": "XLU",

    # ============ XLRE Real Estate / REITs ============
    "PLD": "XLRE", "AMT": "XLRE", "EQIX": "XLRE", "WELL": "XLRE", "DLR": "XLRE",
    "CCI": "XLRE", "PSA": "XLRE", "O": "XLRE", "SPG": "XLRE", "VICI": "XLRE",
    "EQR": "XLRE", "EXR": "XLRE", "AVB": "XLRE", "INVH": "XLRE", "MAA": "XLRE",
    "ESS": "XLRE", "ARE": "XLRE", "VTR": "XLRE", "CPT": "XLRE", "UDR": "XLRE",
    "REG": "XLRE", "BXP": "XLRE", "SBAC": "XLRE", "WPC": "XLRE", "DOC": "XLRE",
    "HST": "XLRE", "KIM": "XLRE", "FRT": "XLRE", "IRM": "XLRE",
}


def _build_full_map() -> Dict[str, str]:
    """Compose the complete tag map: ETFs map to themselves + static map."""
    out: Dict[str, str] = {}
    out.update(ETF_SELF_MAP)
    out.update(STATIC_SECTOR_MAP)
    return out


# ──────────────────────────── Service ────────────────────────────


class SectorTagService:
    """Synchronous tag lookups + async backfill against `symbol_adv_cache`."""

    def __init__(self, db=None):
        self.db = db
        self._map: Dict[str, str] = _build_full_map()

    # ───────── Lookup ─────────

    def tag_symbol(self, symbol: str) -> Optional[str]:
        """Return the sector ETF code for ``symbol`` or ``None`` if unknown."""
        if not symbol:
            return None
        return self._map.get(symbol.upper())

    def tag_many(self, symbols: Iterable[str]) -> Dict[str, Optional[str]]:
        """Batch tag — returns ``{symbol: ETF | None}``."""
        return {s: self.tag_symbol(s) for s in symbols}

    def coverage(self, symbols: Iterable[str]) -> Dict[str, float]:
        """Compute tag-coverage % for a symbol list — useful for the
        backfill script's progress reporting."""
        syms = list(symbols)
        n = len(syms)
        if n == 0:
            return {"total": 0, "tagged": 0, "coverage_pct": 0.0}
        tagged = sum(1 for s in syms if self.tag_symbol(s) is not None)
        return {
            "total": n,
            "tagged": tagged,
            "coverage_pct": round((tagged / n) * 100.0, 1),
        }

    def all_tags(self) -> Dict[str, str]:
        """Return a copy of the full mapping — for diagnostics & tests."""
        return dict(self._map)

    # ───────── Backfill ─────────

    async def backfill_symbol_adv_cache(self, db=None) -> Dict[str, int]:
        """Walk every doc in ``symbol_adv_cache`` and write a ``sector``
        field where one is missing. Idempotent — already-tagged docs are
        left alone (so re-running is safe).

        Returns ``{tagged: N, skipped: N, untaggable: N, total: N}``.
        """
        if db is None:
            db = self.db
        if db is None:
            return {"tagged": 0, "skipped": 0, "untaggable": 0, "total": 0,
                    "error": "db is None"}

        col = db["symbol_adv_cache"]
        total = 0
        tagged = 0
        skipped = 0
        untaggable = 0
        # Use a small batch to avoid loading the whole universe
        cursor = col.find({}, {"_id": 0, "symbol": 1, "sector": 1})
        for doc in cursor:
            total += 1
            sym = doc.get("symbol")
            if not sym:
                untaggable += 1
                continue
            if doc.get("sector"):
                skipped += 1
                continue
            etf = self.tag_symbol(sym)
            if etf is None:
                untaggable += 1
                continue
            try:
                col.update_one(
                    {"symbol": sym},
                    {"$set": {"sector": etf,
                              "sector_name": SECTOR_ETFS.get(etf, etf)}},
                )
                tagged += 1
            except Exception as e:
                logger.warning(f"backfill_symbol_adv_cache update {sym} failed: {e}")
                untaggable += 1
        logger.info(
            f"[SECTOR BACKFILL] total={total} tagged={tagged} "
            f"skipped(already_tagged)={skipped} untaggable={untaggable}"
        )
        return {"total": total, "tagged": tagged, "skipped": skipped,
                "untaggable": untaggable}


# ──────────────────────────── Module-level singleton ────────────────────────────

_instance: Optional[SectorTagService] = None


def get_sector_tag_service(db=None) -> SectorTagService:
    global _instance
    if _instance is None:
        _instance = SectorTagService(db=db)
    elif db is not None and _instance.db is None:
        _instance.db = db
    return _instance
