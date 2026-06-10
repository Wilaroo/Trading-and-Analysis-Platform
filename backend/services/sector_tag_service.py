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

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def order_backfill_targets(untagged: Iterable[str], rated: Iterable[str],
                           cap: int = 0) -> List[str]:
    """v322e — pure: order deep-backfill targets. RS-rated symbols first
    (caller passes them best-rating-first), then the remaining untagged
    alphabetically. Deduped, uppercased, optionally capped."""
    untagged_set = {s.upper() for s in untagged if s}
    rated_first: List[str] = []
    seen = set()
    for s in rated:
        su = (s or "").upper()
        if su and su in untagged_set and su not in seen:
            rated_first.append(su)
            seen.add(su)
    rest = sorted(untagged_set - seen)
    out = rated_first + rest
    return out[:cap] if cap and cap > 0 else out


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


# ──────────────────────────── Industry → SPDR ETF ────────────────────────────
#
# Finnhub `finnhubIndustry` returns free-form-ish strings like "Technology",
# "Banking", "Pharmaceuticals", "Oil & Gas E&P" etc. None of these are GICS
# sector codes — we have to translate. Map below is hand-curated against
# the actual values Finnhub returns for the 200 most-active US tickers.
# Comparisons are case-insensitive and substring-based via `_industry_to_etf`.
#
# 2026-04-30 (operator P2): added so we can catch newly-listed names that
# aren't in STATIC_SECTOR_MAP yet without pushing a code change.

_INDUSTRY_TO_ETF: Dict[str, str] = {
    # Technology — XLK
    "technology":            "XLK",
    "semiconductor":         "XLK",
    "software":              "XLK",
    "computer hardware":     "XLK",
    "computer service":      "XLK",  # consulting, IT services
    "information technology":"XLK",
    "internet of things":    "XLK",
    "electronic equipment":  "XLK",
    # Communication — XLC
    "communication services":"XLC",
    "media":                 "XLC",
    "telecommunication":     "XLC",
    "internet":              "XLC",  # Finnhub uses "Internet" for META/GOOGL
    "broadcasting":          "XLC",
    "publishing":            "XLC",
    "entertainment":         "XLC",
    "interactive media":     "XLC",
    # Consumer Discretionary — XLY
    "consumer cyclical":     "XLY",
    "consumer discretionary":"XLY",
    "auto":                  "XLY",
    "automobile":            "XLY",
    "retail":                "XLY",
    "apparel":               "XLY",
    "leisure":               "XLY",
    "lodging":               "XLY",
    "travel":                "XLY",
    "homebuild":             "XLY",
    # Consumer Staples — XLP
    "consumer staples":      "XLP",
    "consumer defensive":    "XLP",
    "beverages":             "XLP",
    "tobacco":               "XLP",
    "food":                  "XLP",
    "household":             "XLP",
    "personal product":      "XLP",
    # Healthcare — XLV
    "health":                "XLV",
    "pharmaceutical":        "XLV",
    "biotech":               "XLV",
    "medical":               "XLV",
    "healthcare":            "XLV",
    "life sciences":         "XLV",
    "drug manufacturer":     "XLV",
    # Financials — XLF
    "financial":             "XLF",
    "bank":                  "XLF",
    "insurance":             "XLF",
    "capital market":        "XLF",
    "asset management":      "XLF",
    "credit service":        "XLF",
    "exchange":              "XLF",  # NYSE, ICE, CME (financial-exchange names)
    # Energy — XLE
    "energy":                "XLE",
    "oil":                   "XLE",
    "gas":                   "XLE",
    "petroleum":             "XLE",
    "fuel":                  "XLE",
    # Industrials — XLI
    "industrial":            "XLI",
    "aerospace":             "XLI",
    "defense":               "XLI",
    "machinery":             "XLI",
    "transportation":        "XLI",
    "logistic":              "XLI",
    "airline":               "XLI",
    "rail":                  "XLI",
    "construction":          "XLI",
    "engineer":              "XLI",
    "trucking":              "XLI",
    # Materials — XLB
    "materials":             "XLB",
    "chemical":              "XLB",
    "metal":                 "XLB",
    "mining":                "XLB",
    "steel":                 "XLB",
    "paper":                 "XLB",
    "container":             "XLB",
    # Real Estate — XLRE
    "real estate":           "XLRE",
    "reit":                  "XLRE",
    # Utilities — XLU
    "utilit":                "XLU",   # catches "utility" / "utilities"
    "electric":              "XLU",
    "water":                 "XLU",
    "renewable":             "XLU",
}

# Sectors that should win over generic substring matches when both
# fire on the same input. Order matters: earlier groups have higher
# priority. Each group lists ETF + the keys that should "claim" the
# string before falling through to longest-substring resolution.
#
# Why: "Biotechnology" contains both `biotech` (XLV) AND `technology`
# (XLK) — sorted-by-length-desc would wrongly pick XLK. "REIT -
# Industrial" contains both `reit` (XLRE) AND `industrial` (XLI).
# Etc.
_PRIORITY_OVERRIDES: List[tuple] = [
    # Most-specific first.
    ("XLV",  ["biotech", "pharmaceutical", "drug manufacturer",
              "life sciences", "healthcare", "medical"]),
    ("XLRE", ["reit", "real estate"]),
    ("XLU",  ["renewable energy", "utilit"]),
    ("XLE",  ["oil & gas", "petroleum", "natural gas"]),
]

# Industries that look sector-y but aren't covered by SPDR — return
# None so callers degrade to UNKNOWN rather than mis-classify them.
# Explicit blocklist beats trying to bucket every long-tail value.
_EXPLICIT_NONE: List[str] = [
    "cryptocurrency",
    "crypto ",      # leading space avoids "cryptosporidium" et al.
    "blockchain",
    "digital asset",
    "shell company",
    "spac",         # blank-check / SPACs
    "trust",        # closed-end funds, royalty trusts (heterogeneous sectors)
    "etf",          # the few non-SPDR ETF tickers in the universe
    "fund",
]


def _industry_to_etf(industry: Optional[str]) -> Optional[str]:
    """Resolve a free-form industry string to an SPDR sector ETF code.

    Resolution order:
      1. ``_EXPLICIT_NONE`` blocklist — return None for industries
         where mis-classification is worse than UNKNOWN.
      2. ``_PRIORITY_OVERRIDES`` — claim sector-conflict cases like
         "Biotechnology" (biotech beats tech) and "REIT - Industrial"
         (reit beats industrial).
      3. Longest-substring match into ``_INDUSTRY_TO_ETF``.

    Case-insensitive throughout. Returns ``None`` when no rule applies.
    """
    if not industry:
        return None
    needle = industry.lower()
    # 1. Explicit blocklist — UNKNOWN beats wrong sector tag.
    for blocked in _EXPLICIT_NONE:
        if blocked in needle:
            return None
    # 2. Priority overrides — sector-conflict resolution.
    for etf, keys in _PRIORITY_OVERRIDES:
        for k in keys:
            if k in needle:
                return etf
    # 3. Longest-substring match.
    for key in sorted(_INDUSTRY_TO_ETF.keys(), key=len, reverse=True):
        if key in needle:
            return _INDUSTRY_TO_ETF[key]
    return None


# ──────────────────────────── Service ────────────────────────────


class SectorTagService:
    """Synchronous tag lookups + async backfill against `symbol_adv_cache`."""

    def __init__(self, db=None):
        self.db = db
        self._map: Dict[str, str] = _build_full_map()
        # v322e — deep-backfill progress state (read by the status endpoint).
        self._deep_state: Dict = {"running": False}

    # ───────── Lookup ─────────

    def tag_symbol(self, symbol: str) -> Optional[str]:
        """Return the sector ETF code for ``symbol`` or ``None`` if unknown.

        SYNC, fast — only consults the in-memory static map. Use
        :py:meth:`tag_symbol_async` for the full fallback chain
        (Mongo cache → Finnhub) when the static miss matters.
        """
        if not symbol:
            return None
        return self._map.get(symbol.upper())

    async def tag_symbol_async(self, symbol: str) -> Optional[str]:
        """Async tag with full fallback chain — added 2026-04-30 (operator P2).

        Lookup order:
          1. STATIC_SECTOR_MAP (in-memory, instant) — same as :py:meth:`tag_symbol`.
          2. ``symbol_adv_cache.sector`` (Mongo cache from a prior backfill
             OR a prior Finnhub lookup persisted by step 3).
          3. Finnhub ``stock/profile2`` via ``fundamental_data_service`` —
             maps the returned ``industry`` string to an SPDR ETF via
             ``_industry_to_etf``. Network call, gated behind a 4s timeout
             inside the fundamental service.

        On Finnhub success, the result is persisted to
        ``symbol_adv_cache.sector`` so step 2 hits on subsequent calls
        (operator-confirmed: persist == yes).

        Returns ``None`` if every step fails — caller treats as UNKNOWN
        sector, downstream classifier degrades gracefully.
        """
        if not symbol:
            return None
        sym = symbol.upper()

        # 1. Static map
        hit = self._map.get(sym)
        if hit is not None:
            return hit

        # 2. Mongo cache (`symbol_adv_cache.sector`)
        if self.db is not None:
            try:
                doc = self.db["symbol_adv_cache"].find_one(
                    {"symbol": sym},
                    {"_id": 0, "sector": 1},
                )
                cached = (doc or {}).get("sector")
                if cached and cached in SECTOR_ETFS:
                    # Promote to in-memory map so future sync `tag_symbol`
                    # calls hit instantly.
                    self._map[sym] = cached
                    return cached
            except Exception as e:
                logger.debug(f"tag_symbol_async mongo lookup failed for {sym}: {e}")

        # 3. v19.34.176 — IB-native `reqContractDetails` lookup BEFORE
        # Finnhub. Uses Client 11 (`ib_direct_service`, which IS
        # connected on this DGX rig). Returns IB's Reuters-sourced
        # `industry` / `category` / `subcategory` triple — same shape
        # as Finnhub, fed through the same `_industry_to_etf` resolver.
        # Results persisted to `symbol_adv_cache.sector` so future
        # lookups hit step 2 (Mongo cache) instantly.
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib_direct = get_ib_direct_service()
            if ib_direct is not None:
                triple = await ib_direct.get_contract_industry(sym)
                if triple:
                    for key in ("category", "industry", "subcategory"):
                        ib_label = triple.get(key)
                        if not ib_label:
                            continue
                        etf = _industry_to_etf(ib_label)
                        if etf:
                            self._map[sym] = etf
                            if self.db is not None:
                                try:
                                    self.db["symbol_adv_cache"].update_one(
                                        {"symbol": sym},
                                        {"$set": {
                                            "sector": etf,
                                            "sector_name": SECTOR_ETFS.get(etf, etf),
                                            "sector_source": "ib_contract_details",
                                            "sector_source_industry": ib_label,
                                            "sector_source_triple": triple,
                                        }},
                                        upsert=True,
                                    )
                                except Exception as e:
                                    logger.debug(
                                        f"tag_symbol_async IB persist failed for {sym}: {e}"
                                    )
                            logger.info(
                                f"[SECTOR IB] {sym} → {etf} via IB {key} "
                                f"'{ib_label}' (persisted)"
                            )
                            return etf
        except Exception as e:
            logger.debug(f"tag_symbol_async IB lookup failed for {sym}: {e}")

        # 4. Finnhub fallback (network call). Gated behind a try/except —
        # any failure (no key, timeout, parse error) silently falls
        # through to None.
        try:
            from services.fundamental_data_service import get_fundamental_data_service
            fund_svc = get_fundamental_data_service()
            profile = await fund_svc.get_company_profile(sym)
            industry = (profile or {}).get("industry")
            etf = _industry_to_etf(industry)
            if etf:
                self._map[sym] = etf  # cache in-process
                # Persist to Mongo for next time. Best-effort —
                # never blocks the lookup on a write failure.
                if self.db is not None:
                    try:
                        self.db["symbol_adv_cache"].update_one(
                            {"symbol": sym},
                            {"$set": {
                                "sector": etf,
                                "sector_name": SECTOR_ETFS.get(etf, etf),
                                "sector_source": "finnhub_industry",
                                "sector_source_industry": industry,
                            }},
                            upsert=True,
                        )
                    except Exception as e:
                        logger.debug(
                            f"tag_symbol_async persist failed for {sym}: {e}"
                        )
                logger.info(
                    f"[SECTOR FALLBACK] {sym} → {etf} via Finnhub industry "
                    f"'{industry}' (persisted)"
                )
                return etf
        except Exception as e:
            logger.debug(f"tag_symbol_async Finnhub fallback failed for {sym}: {e}")

        return None

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

    # ───────── v322e — paced deep backfill (IB reqContractDetails chain) ─────────

    DEEP_BREAKER_STREAK = 25    # consecutive misses with IB down → abort

    def deep_backfill_status(self) -> Dict:
        """Sync snapshot of the deep-backfill progress for the status endpoint."""
        return dict(self._deep_state)

    def _ib_connected(self) -> bool:
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib = get_ib_direct_service()
            return bool(ib is not None and getattr(ib, "_connected", False))
        except Exception:
            return False

    async def deep_backfill_untagged(self, db=None, max_symbols: int = 4000,
                                     pace_s: float = 0.25,
                                     recompute_rs: bool = True) -> Dict:
        """v322e — paced FULL-CHAIN sector backfill over the untagged universe.

        Unlike :py:meth:`backfill_symbol_adv_cache` (static map only), each
        symbol goes through :py:meth:`tag_symbol_async` — static map → Mongo
        cache → **IB reqContractDetails (Client 11)** → Finnhub — so the
        ~3,000+ rated names outside the static map finally get sector tags
        and stop dropping off the Regime Focus List.

        Order: RS-leadership rated symbols first (best rating first), then
        the rest of `symbol_adv_cache`. Paced (`pace_s` sleep per network
        lookup) to stay friendly with the Client-11 socket. Circuit breaker:
        DEEP_BREAKER_STREAK consecutive misses while IB is disconnected
        aborts the run with a clear hint. Progress is exposed via
        :py:meth:`deep_backfill_status`. On completion, optionally re-runs
        the RS compute so `rs_leadership.sector` / `sector_rs_diff` pick up
        the new tags immediately (Mongo-only, cheap).
        """
        if db is None:
            db = self.db
        if db is None:
            return {"success": False, "error": "db is None"}
        if self._deep_state.get("running"):
            return {"success": False, "error": "deep backfill already running"}

        started_iso = datetime.now(timezone.utc).isoformat()
        self._deep_state = {
            "running": True, "started_at": started_iso, "processed": 0,
            "tagged": 0, "untaggable": 0, "targets": 0, "last_symbol": None,
            "aborted": None,
        }
        started_mono = time.monotonic()
        try:
            # Untagged universe (valid-ETF check in python — values like ""
            # or stale labels count as untagged).
            valid = set(SECTOR_ETFS.keys())
            untagged: List[str] = []
            for doc in db["symbol_adv_cache"].find(
                    {}, {"_id": 0, "symbol": 1, "sector": 1}):
                sym = doc.get("symbol")
                if sym and doc.get("sector") not in valid:
                    untagged.append(sym)

            # Rated symbols, best rating first (leaders get tagged first).
            rated: List[str] = []
            try:
                rated = [d["symbol"] for d in db["rs_leadership"].find(
                    {"symbol": {"$exists": True}, "rs_rating": {"$ne": None}},
                    {"_id": 0, "symbol": 1, "rs_rating": 1},
                ).sort("rs_rating", -1)]
            except Exception as e:
                logger.debug(f"[v322e] rs_leadership load failed: {e}")

            targets = order_backfill_targets(untagged, rated, cap=max_symbols)
            self._deep_state["targets"] = len(targets)
            logger.info(f"[v322e DEEP-BACKFILL] starting: {len(targets)} untagged "
                        f"targets ({len(rated)} rated, pace={pace_s}s)")

            tagged = 0
            untaggable = 0
            miss_streak = 0
            for i, sym in enumerate(targets):
                etf = await self.tag_symbol_async(sym)
                if etf:
                    tagged += 1
                    miss_streak = 0
                else:
                    untaggable += 1
                    miss_streak += 1
                self._deep_state.update(
                    processed=i + 1, tagged=tagged, untaggable=untaggable,
                    last_symbol=sym)
                if (miss_streak >= self.DEEP_BREAKER_STREAK
                        and not self._ib_connected()):
                    self._deep_state["aborted"] = (
                        f"{miss_streak} consecutive misses with IB Client-11 "
                        f"disconnected — connect IB Gateway and re-run")
                    logger.warning(f"[v322e DEEP-BACKFILL] {self._deep_state['aborted']}")
                    break
                if pace_s > 0:
                    await asyncio.sleep(pace_s)

            rs_summary = None
            if recompute_rs and tagged > 0 and not self._deep_state["aborted"]:
                try:
                    from services.rs_leadership_service import get_rs_leadership_service
                    rs_summary = await get_rs_leadership_service(db=db).compute_all()
                except Exception as e:
                    rs_summary = {"success": False, "error": str(e)}

            elapsed = round(time.monotonic() - started_mono, 1)
            summary = {
                "success": True, "targets": len(targets), "tagged": tagged,
                "untaggable": untaggable, "aborted": self._deep_state["aborted"],
                "elapsed_s": elapsed, "rs_recompute": rs_summary,
            }
            self._deep_state.update(running=False, finished_at=datetime.now(
                timezone.utc).isoformat(), result=summary)
            logger.info(f"[v322e DEEP-BACKFILL] done: {summary}")
            return summary
        except Exception as e:
            self._deep_state.update(running=False, aborted=str(e))
            logger.error(f"[v322e DEEP-BACKFILL] failed: {e}")
            return {"success": False, "error": str(e)}


# ──────────────────────────── Module-level singleton ────────────────────────────

_instance: Optional[SectorTagService] = None


def get_sector_tag_service(db=None) -> SectorTagService:
    global _instance
    if _instance is None:
        _instance = SectorTagService(db=db)
    elif db is not None and _instance.db is None:
        _instance.db = db
    return _instance
