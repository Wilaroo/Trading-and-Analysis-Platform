"""
etf_classifier — v322n (2026-06-11 ETF universe audit).

Static ETF classification so the funnel can treat mechanical products
differently from genuine RS leaders, and so per-class EV can be measured
on bot_trades.

Classes:
    leveraged_inverse — geared / inverse index, sector & SINGLE-STOCK
                        products (RS ratings are leverage, not leadership)
    bond_cash         — treasury / credit / cash-equivalent funds
    income            — covered-call / dividend-income funds
    index_clone       — broad index trackers redundant with SPY/QQQ/IWM/DIA
    country_intl      — country / international region funds
    commodity         — physical/futures commodity funds
    crypto            — spot/futures crypto funds
    sector_thematic   — SPDR sectors + industry/thematic equity funds
                        (the only class with genuine trade candidacy)
    None              — not a known ETF (treated as a stock)

Policy (2026-06-11, user-approved):
    • Focus list: leveraged_inverse, bond_cash, income, index_clone are
      NOT focus-eligible — except the explicit carve-out TQQQ/SQQQ/
      SOXL/SOXS which the operator actively trades.
    • L1 recommendations: bond_cash, income, index_clone and SINGLE-STOCK
      leveraged products are dropped from the top-N ADV ranking (the
      always-on context ETF set is unaffected).
    • Nothing is barred from trading here — v322m's scalp floors handle
      thin products; per-class EV data decides future hard blocks.
"""
from typing import Optional, Set

# Index/sector leveraged & inverse products the operator KEEPS for the
# focus list (explicit carve-out, 2026-06-11).
FOCUS_EXEMPT: Set[str] = {"TQQQ", "SQQQ", "SOXL", "SOXS"}

# Single-stock leveraged/inverse products — never useful as L1 lines
# (the underlying is already streamed) and never RS "leaders".
SINGLE_STOCK_LEVERAGED: Set[str] = {
    "NVDL", "NVDU", "NVDD", "NVD", "NVDS",
    "TSLL", "TSLQ", "TSLR", "TSLZ", "TSLS",
    "AMDL", "AMDD", "MUU", "MUD",
    "PLTU", "PLTD", "MSTU", "MSTZ", "MSTX",
    "CONL", "COND", "GGLL", "GGLS",
    "AAPU", "AAPD", "MSFU", "MSFD",
    "METU", "METD", "AMZU", "AMZD",
    "AVGX", "AVGD", "SMCX", "SMCZ", "COIW", "COIG",
    "BABX", "PALU", "HOOX", "RBLU",
}

LEVERAGED_INVERSE: Set[str] = SINGLE_STOCK_LEVERAGED | FOCUS_EXEMPT | {
    "TZA", "TNA", "SPXU", "SPXS", "SPXL", "UPRO", "SSO", "SDS",
    "QID", "QLD", "SH", "PSQ", "SPDN", "DOG", "DXD", "SDOW", "UDOW",
    "UVXY", "VXX", "VIXY", "SVXY", "UVIX", "SVIX",
    "SCO", "UCO", "BOIL", "KOLD", "AGQ", "ZSL", "UGL", "GLL",
    "LABU", "LABD", "TECL", "TECS", "FAS", "FAZ", "ERX", "ERY",
    "NUGT", "DUST", "JNUG", "JDST", "WEBL", "WEBS", "TMF", "TMV",
    "YINN", "YANG", "FNGU", "FNGD", "BULZ", "BERZ", "SOXQ"[:0] or "URTY",
    "SRTY", "BITX", "BITI", "ETHU", "ETHD", "MJUS"[:0] or "DPST",
    "DRN", "DRV", "OILU", "OILD", "GUSH", "DRIP",
}

BOND_CASH: Set[str] = {
    "TLT", "IEF", "SHY", "SHV", "BIL", "SGOV", "JPST", "AGG", "BND",
    "BNDX", "LQD", "HYG", "JNK", "VCIT", "VCSH", "VCLT", "MUB", "VTEB",
    "EMB", "USHY", "IUSB", "GOVT", "TIP", "STIP", "VGIT", "VGSH",
    "VGLT", "SCHO", "SCHR", "FLOT", "MINT", "ICSH", "NEAR", "TBIL",
    "USFR", "SJNK", "ANGL", "BKLN", "SRLN", "TLH", "EDV", "ZROZ",
    "BSV", "BIV", "BLV", "SPTL", "SPTS", "SPIB", "SPAB", "FALN",
    "HYLB", "VMBS", "MBB", "PFF", "PGX", "EMLC", "BWX", "IGSB", "IGIB",
}

INCOME: Set[str] = {
    "JEPI", "JEPQ", "QQQI", "SPYI", "QYLD", "XYLD", "RYLD", "DIVO",
    "SCHD", "VYM", "DVY", "HDV", "SPHD", "SDY", "NOBL", "DGRO", "SVOL",
}

INDEX_CLONE: Set[str] = {
    "VOO", "IVV", "VTI", "RSP", "QQQM", "SPYM", "SPLG", "SCHX", "SCHB",
    "SCHG", "SCHA", "SPYG", "SPYV", "IVW", "IVE", "IWD", "IWF", "IWB",
    "IWV", "ITOT", "MDY", "SLY", "IJH", "IJR", "VB", "VO", "VV", "VTWO",
    "OEF", "QUAL", "VTV", "VUG", "MTUM", "USMV", "VLUE", "SIZE", "DGRW",
    "VTHR", "SPMD", "SPSM", "PRF", "IUSG", "IUSV", "VONG", "VONV",
}

COUNTRY_INTL: Set[str] = {
    "EFA", "EFV", "IEFA", "IEMG", "EEM", "VWO", "VEA", "VXUS", "ACWI",
    "VT", "ACWX", "VEU", "EWY", "EWZ", "EWJ", "EWT", "EWG", "EWU",
    "EWC", "EWA", "EWH", "EWL", "EWP", "EWQ", "EWI", "EWD", "EWN",
    "EWS", "EWM", "EWW", "EZA", "EPI", "INDA", "FXI", "KWEB", "MCHI",
    "ASHR", "ILF", "EWX", "FEZ", "EZU", "HEFA", "DXJ", "BBJP", "ARGT",
    "TUR", "GREK", "EPOL", "THD", "VNM", "EIDO", "EPHE", "KSA", "UAE",
}

COMMODITY: Set[str] = {
    "GLD", "IAU", "GLDM", "SGOL", "SLV", "SIVR", "PPLT", "PALL",
    "USO", "BNO", "UNG", "UNL", "DBC", "DBA", "PDBC", "CPER", "CORN",
    "WEAT", "SOYB", "CANE", "KRBN",
}

CRYPTO: Set[str] = {
    "IBIT", "BITO", "FBTC", "ARKB", "GBTC", "ETHA", "ETHE", "EZBC",
    "BITB", "HODL", "BTCO", "BRRR", "ETHW", "ETHV", "BTC", "DEFI",
}

SECTOR_THEMATIC: Set[str] = {
    # SPDR sectors
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
    "XLRE", "XLC",
    # industry / thematic equity funds
    "SMH", "SOXX", "IGV", "XBI", "IBB", "KRE", "KBE", "KIE", "XRT",
    "XOP", "OIH", "XME", "ITB", "XHB", "ITA", "PPA", "JETS", "IYR",
    "IYT", "IHI", "IHF", "XPH", "VNQ", "GDX", "GDXJ", "SIL", "SILJ",
    "COPX", "URA", "URNM", "REMX", "LIT", "TAN", "ICLN", "PBW", "FAN",
    "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ", "ARKX", "AIQ", "BOTZ",
    "ROBO", "IRBO", "HACK", "CIBR", "BUG", "SKYY", "CLOU", "WCLD",
    "FDN", "QTUM", "IPO", "ESPO", "HERO", "BETZ", "SOCL", "MSOS",
    "XT", "KOMP", "SPHB", "MAGS", "FFTY", "MOO", "PHO", "NLR", "GRID",
}

_CLASS_MAP = {}
for _syms, _cls in (
    (LEVERAGED_INVERSE, "leveraged_inverse"),
    (BOND_CASH, "bond_cash"),
    (INCOME, "income"),
    (INDEX_CLONE, "index_clone"),
    (COUNTRY_INTL, "country_intl"),
    (COMMODITY, "commodity"),
    (CRYPTO, "crypto"),
    (SECTOR_THEMATIC, "sector_thematic"),
):
    for _s in _syms:
        if _s:
            _CLASS_MAP[_s] = _cls

# Classes that can never be RS "leaders" — their rating is mechanical
# (leverage / yield / duration), not stock leadership.
FOCUS_INELIGIBLE_CLASSES = {
    "leveraged_inverse", "bond_cash", "income", "index_clone",
}

# Classes dropped from the pusher L1 top-N ADV ranking (the always-on
# context set — SPY/QQQ/TLT/HYG/GLD/sector SPDRs etc. — is unaffected).
L1_EXCLUDED_CLASSES = {"bond_cash", "income", "index_clone"}


def classify_etf(symbol: str) -> Optional[str]:
    """Class label for a known ETF, or None (treated as a stock)."""
    return _CLASS_MAP.get(str(symbol or "").upper().strip())


def is_etf(symbol: str) -> bool:
    return classify_etf(symbol) is not None


def is_focus_eligible(symbol: str) -> bool:
    """May this symbol appear on the Regime Focus List?

    Stocks and sector/thematic/country/commodity/crypto funds: yes.
    Mechanical products (leveraged, bond/cash, income, index clones): no —
    except the operator's explicit TQQQ/SQQQ/SOXL/SOXS carve-out."""
    sym = str(symbol or "").upper().strip()
    if sym in FOCUS_EXEMPT:
        return True
    return _CLASS_MAP.get(sym) not in FOCUS_INELIGIBLE_CLASSES


def is_l1_eligible(symbol: str) -> bool:
    """May this symbol take an L1 line via the top-N ADV ranking?

    Drops bond/cash, income, index clones and single-stock leveraged
    products — each line freed goes to an actual tradeable stock."""
    sym = str(symbol or "").upper().strip()
    if sym in SINGLE_STOCK_LEVERAGED:
        return False
    return _CLASS_MAP.get(sym) not in L1_EXCLUDED_CLASSES
