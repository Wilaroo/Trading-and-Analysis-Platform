"""
ETF-Based Trading Universe
===========================
Symbols organized by ETF membership (SPY, QQQ, IWM) with priority-based scanning.

Priority:
- Tier 1: SPY constituents (S&P 500 large caps) - Always scanned
- Tier 2: QQQ constituents (Nasdaq-100 tech/growth) - Always scanned  
- Tier 3: IWM constituents (Russell 2000 small caps) - Rotating batches

Volume Filters:
- General scanning: avg daily volume >= 100,000
- Intraday/scalp setups: avg daily volume >= 500,000

Refresh Schedule:
- Quarterly (March, June, September, December)
- Last updated: February 2026

Next refresh due: March 2026
"""

from datetime import datetime, timezone
from typing import List, Dict, Set

# ===================== METADATA =====================
UNIVERSE_METADATA = {
    "last_updated": "2026-02-11",
    "next_rebalance": "2026-03-20",  # Third Friday of March (quarterly rebalance)
    "version": "2.0",
    "source": "ETF constituents (SPY, QQQ, IWM)"
}

# Quarterly rebalance schedule (third Friday of rebalance month)
REBALANCE_DATES = [
    "2026-03-20",  # Q1
    "2026-06-19",  # Q2
    "2026-09-18",  # Q3
    "2026-12-18",  # Q4
]

# ===================== VOLUME THRESHOLDS =====================
VOLUME_FILTERS = {
    "general_min_adv": 100_000,     # Minimum avg daily volume for general scanning
    "intraday_min_adv": 500_000,    # Minimum avg daily volume for intraday/scalp setups
    "scalp_min_adv": 500_000,       # Same as intraday
}

# ===================== SPY CONSTITUENTS (S&P 500) =====================
# ~500 large cap stocks - PRIORITY TIER 1
SPY_SYMBOLS = [
    # Technology (65)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "AVGO", "ORCL", "CSCO", "CRM", "ADBE", "ACN", "IBM", "INTC",
    "AMD", "TXN", "QCOM", "INTU", "AMAT", "NOW", "ADI", "LRCX",
    "MU", "KLAC", "SNPS", "CDNS", "MCHP", "APH", "MSI", "FTNT",
    "PANW", "ADSK", "CTSH", "ANSS", "KEYS", "CDW", "ZBRA", "TYL",
    "EPAM", "IT", "AKAM", "FFIV", "JNPR", "WDC", "STX", "NTAP",
    "HPQ", "HPE", "DELL", "ANET", "MPWR", "SWKS", "QRVO", "TER",
    "ON", "NXPI", "MRVL", "GEN", "ENPH", "SEDG", "FSLR", "GLW",
    
    # Financials (70)
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "AXP",
    "SPGI", "CME", "ICE", "MCO", "CB", "PGR", "MMC", "AON", "TRV",
    "AIG", "ALL", "MET", "PRU", "AFL", "HIG", "CINF", "L", "BRO",
    "USB", "PNC", "TFC", "COF", "DFS", "SYF", "KEY", "CFG", "FITB",
    "HBAN", "RF", "ZION", "MTB", "NTRS", "STT", "BK", "NDAQ", "CBOE",
    "MSCI", "FDS", "MKTX", "VRSN", "RJF", "SEIC", "LPLA", "SF",
    "HOOD", "SOFI", "COIN", "WTW", "AJG", "RYAN", "ERIE", "AIZ",
    "RE", "ACGL", "RNR", "EG", "GL",
    
    # Healthcare (65)
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "DHR",
    "BMY", "AMGN", "GILD", "CVS", "ELV", "CI", "HCA", "ISRG", "SYK",
    "MDT", "BDX", "BSX", "ZBH", "EW", "REGN", "VRTX", "BIIB", "MRNA",
    "ILMN", "DXCM", "IDXX", "IQV", "MTD", "A", "WST", "TECH", "HOLX",
    "BAX", "RMD", "ALGN", "COO", "PODD", "TFX", "XRAY", "HSIC", "HUM",
    "CNC", "MOH", "DVA", "VTRS", "ZTS", "LH", "DGX", "CAH", "MCK",
    "ABC", "COR", "INCY", "BMRN", "EXAS", "SRPT", "ALNY", "HZNP",
    
    # Consumer Discretionary (60)
    "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "TJX", "BKNG", "MAR",
    "HLT", "YUM", "CMG", "DG", "DLTR", "ROST", "BBY", "ORLY", "AZO",
    "TSCO", "ULTA", "POOL", "WSM", "RH", "DRI", "LVS", "WYNN", "MGM",
    "CZR", "NCLH", "CCL", "RCL", "EXPE", "ABNB", "GRMN", "LEN", "DHI",
    "PHM", "NVR", "TOL", "KMX", "AN", "LAD", "GPC", "AAP", "APTV",
    "BWA", "LEA", "GM", "F", "RIVN", "LCID", "EBAY", "ETSY", "W",
    
    # Consumer Staples (35)
    "WMT", "PG", "COST", "KO", "PEP", "PM", "MO", "MDLZ", "CL",
    "EL", "GIS", "K", "KMB", "SYY", "HSY", "KHC", "KR", "WBA",
    "STZ", "TAP", "ADM", "CAG", "CPB", "HRL", "SJM", "MKC",
    "CHD", "CLX", "TSN", "BG", "INGR", "DAR", "USFD", "PFGC",
    
    # Energy (30)
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY",
    "PXD", "DVN", "HES", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE",
    "TRGP", "LNG", "CTRA", "APA", "MRO", "NOV", "CHK", "RRC", "AR",
    "EQT", "CNX", "MGY",
    
    # Industrials (75)
    "UNP", "UPS", "HON", "RTX", "CAT", "DE", "BA", "GE", "LMT",
    "MMM", "FDX", "NOC", "GD", "CSX", "NSC", "ITW", "EMR", "ETN",
    "ROK", "PH", "CMI", "PCAR", "ODFL", "JBHT", "CHRW", "EXPD",
    "XPO", "DAL", "UAL", "AAL", "LUV", "ALK", "JBLU", "WM", "RSG",
    "AME", "ROP", "IR", "DOV", "SWK", "FAST", "GWW", "CTAS", "PAYX",
    "VRSK", "BR", "LDOS", "J", "FTV", "TDG", "HWM", "WAB", "TT",
    "CARR", "OTIS", "SNA", "IEX", "GNRC", "XYL", "NDSN", "RBC",
    "AOS", "LII", "ALLE", "MAS", "LECO", "AXON",
    
    # Materials (30)
    "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DD", "DOW",
    "PPG", "CTVA", "VMC", "MLM", "ALB", "EMN", "CE", "CF", "MOS",
    "IFF", "FMC", "LYB", "WRK", "PKG", "IP", "AVY", "SEE", "BLL",
    "AMCR", "BALL", "RPM",
    
    # Utilities (30)
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG",
    "ED", "WEC", "ES", "AWK", "DTE", "AEE", "ETR", "FE", "PPL",
    "CMS", "EVRG", "AES", "NI", "CNP", "PNW", "ATO", "NRG", "LNT",
    "OGE", "POR", "NWE",
    
    # Real Estate (30)
    "PLD", "AMT", "EQIX", "CCI", "PSA", "DLR", "O", "WELL", "SPG",
    "VICI", "AVB", "EQR", "VTR", "ARE", "BXP", "UDR", "ESS", "MAA",
    "SUI", "ELS", "CPT", "PEAK", "KIM", "REG", "FRT", "HST", "IRM",
    "CBRE", "JLL", "CSGP",
    
    # Communication Services (25)
    "DIS", "CMCSA", "NFLX", "VZ", "T", "TMUS", "CHTR", "WBD", "PARA",
    "FOX", "FOXA", "EA", "TTWO", "MTCH", "OMC", "IPG", "LUMN", "DISH",
    "ROKU", "LYV", "MSGS", "SIRI", "IHRT", "NWSA", "NWS",
]

# ===================== QQQ CONSTITUENTS (NASDAQ-100) =====================
# ~100 large cap tech/growth stocks - PRIORITY TIER 1
QQQ_SYMBOLS = [
    # Mega Cap
    "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "COST", "ADBE", "PEP", "CSCO", "NFLX", "AMD", "CMCSA",
    "INTC", "INTU", "TMUS", "TXN", "QCOM", "AMGN", "HON", "AMAT",
    
    # Large Cap Tech
    "BKNG", "ISRG", "SBUX", "VRTX", "ADP", "GILD", "MDLZ", "ADI",
    "REGN", "LRCX", "PYPL", "FISV", "PANW", "KLAC", "MU", "SNPS",
    "CDNS", "MNST", "MAR", "ORLY", "MELI", "FTNT", "CTAS", "CSX",
    "MCHP", "KDP", "ADSK", "ABNB", "NXPI", "AEP", "DXCM", "PCAR",
    "AZN", "PAYX", "CPRT", "MRNA", "ROST", "CHTR", "KHC", "LULU",
    
    # High Growth Tech
    "WDAY", "EXC", "CRWD", "ODFL", "IDXX", "XEL", "FAST", "CTSH",
    "MRVL", "EA", "DLTR", "VRSK", "BIIB", "GEHC", "CSGP", "TEAM",
    "DDOG", "ZS", "ANSS", "ILMN", "FANG", "WBD", "CEG", "BKR",
    "TTD", "ALGN", "EBAY", "SIRI", "ZM", "LCID", "RIVN", "ENPH",
    "OKTA", "DOCU", "SPLK", "ON", "DASH", "COIN", "HOOD", "PLTR",
    
    # Additional Nasdaq-100
    "PDD", "JD", "MSTR", "ARM", "SMCI", "CPNG", "DKNG", "RBLX",
    "PTON", "SNOW", "UBER", "LYFT", "SPOT", "PINS", "SNAP", "SQ",
]

# ===================== IWM CONSTITUENTS (RUSSELL 2000) =====================
# Small caps - PRIORITY TIER 3 (rotating batches)
IWM_SYMBOLS = [
    # Small Cap Technology (High Volume)
    "SMCI", "IONQ", "SOUN", "RGTI", "BIGC", "DUOL", "GLBE", "DOCS",
    "PYCR", "VERX", "TTWO", "BILL", "CFLT", "ESTC", "GTLB", "HUBS",
    "JAMF", "KTOS", "LITE", "MANH", "MDB", "NET", "PATH", "PCOR",
    "PD", "SMAR", "TASK", "TOST", "TWLO", "U", "VEEV", "WIX",
    "WOLF", "ZEN", "ZI", "CWAN", "DLO", "FRSH", "GENI", "GLOB",
    "HCP", "KNBE", "LSPD", "NCNO", "NTNX", "OLO", "PAYC", "PING",
    "QLYS", "QTWO", "RAMP", "RPD", "SDGR", "SMAR", "SPSC", "TENB",
    "VRNS", "WK", "YEXT", "ZUO", "APLS", "CRNC", "DCBO", "ENVX",
    
    # Small Cap Biotech/Healthcare (High Volume)
    "ABCL", "ACAD", "ALKS", "ALNY", "ARWR", "BEAM", "BGNE", "BHVN",
    "BLUE", "CRSP", "EDIT", "EXAS", "EXEL", "FATE", "FOLD", "GERN",
    "HALO", "ICPT", "IDYA", "IONS", "IOVA", "IRWD", "JAZZ", "LGND",
    "MDGL", "NBIX", "NTLA", "NVAX", "PCVX", "RARE", "RGEN", "RVMD",
    "SAGE", "SRPT", "UTHR", "VCNX", "XENE", "YMAB", "ZLAB", "ZNTL",
    "ARCT", "ARNA", "AUPH", "BCRX", "BGRY", "BMEA", "CARA", "CERS",
    "CGEM", "CLVS", "CPRX", "DCPH", "DNLI", "DRIO", "DVAX", "FGEN",
    
    # Small Cap Financials (High Volume)
    "AFRM", "ALLY", "COIN", "HOOD", "IBKR", "LPLA", "NAVI", "NDAQ",
    "SOFI", "UPST", "OZK", "PACW", "PNFP", "SBCF", "UBSI", "UCBI",
    "UMBF", "WAFD", "WSFS", "WTFC", "CBSH", "COLB", "CVBF", "EWBC",
    "FCNCA", "FFBC", "FIBK", "FITB", "GBCI", "LKFN", "NTRS", "OCFC",
    "STT", "TRMK", "ZION", "ABCB", "BANC", "BOKF", "BPOP",
    
    # Small Cap Consumer (High Volume)
    "CHWY", "CVNA", "DKS", "ETSY", "FIVE", "GRPN", "HIBB", "LULU",
    "OSTK", "PENN", "PLAY", "PLNT", "SHAK", "SIG", "SKX", "WING",
    "YETI", "BROS", "CAKE", "CAVA", "COOK", "EAT", "EYE", "FWRG",
    "JACK", "KRUS", "LOCO", "PRTY", "PSMT", "TXRH",
    "BJRI", "BLMN", "CBRL", "CHUY", "DENN", "DIN", "FRGI", "GTIM",
    
    # Small Cap Energy (High Volume)
    "AMLP", "AM", "AROC", "CIVI", "CPE", "CRGY", "DMLP", "DRQ",
    "ERF", "GPOR", "GPRK", "HESM", "HLX", "HP", "KOS", "LPI",
    "MTDR", "MUR", "NOG", "OVV", "PARR", "PDCE", "PDS", "PR",
    "PTEN", "REPX", "RIG", "ROCC", "SD", "SM", "SWN", "TDW",
    "TRGP", "TTI", "USAC", "VNOM", "VTS", "WTI", "WTTR", "XEC",
    
    # Small Cap Industrials (High Volume)
    "AAL", "ALK", "ARCB", "ASGN", "ATKR", "AWI", "AYI", "BECN",
    "BLDR", "BMI", "BWXT", "CACI", "CAR", "CIR", "CLH", "CNXN",
    "CRS", "CW", "DY", "EBC", "ENS", "ESE", "EXPO", "FELE",
    "FIX", "FLOW", "FORM", "FSS", "GBX", "GEF", "GFF", "GHC",
    "GMS", "GNW", "HI", "HNI", "HRI", "HXL", "IBOC", "IESC",
    
    # Small Cap REITs (High Volume)
    "ACC", "ADC", "AGNC", "AIV", "AKR", "ALEX", "APLE", "BFS",
    "BRG", "BXMT", "CIO", "CLPR", "CTO", "DEA", "DEI", "ELME",
    "EPR", "ESRT", "FAF", "GEO", "GMRE", "GTY", "HIW", "INN",
    "IIPR", "JBGS", "KRG", "LAMR", "LXP", "MAC", "MDV", "MPW",
    "NHI", "NNN", "OFC", "OHI", "OUT", "PCH", "PDM", "PEB",
    
    # High Beta / Meme / SPACs (High Volume)
    "GME", "AMC", "BB", "CLOV", "WISH", "WKHS", "RIDE", "GOEV",
    "HYLN", "NKLA", "SPCE", "SKLZ", "BYND", "CRSR", "LMND", "ROOT",
    "OPEN", "VLDR", "LAZR", "MVIS", "QS", "CHPT", "BLNK", "FCEL",
    "PLUG", "BE", "ARVL", "PTRA", "FSR", "SOLO", "AYRO", "XL",
    "CLSK", "MARA", "RIOT", "HUT", "BITF", "HIVE", "BTBT", "CAN",
    
    # Additional Russell 2000 (Alphabetical - High Volume Focus)
    "AAOI", "AAXJ", "ABCB", "ABCM", "ABEO", "ABG", "ABM", "ABNB",
    "ABR", "ABST", "ABUS", "ACAD", "ACBI", "ACCD", "ACCO", "ACEL",
    "ACER", "ACIA", "ACLS", "ACMR", "ACNB", "ACOR", "ACRE", "ACRX",
    "ACTG", "ADAP", "ADCT", "ADEA", "ADI", "ADMA", "ADNT", "ADP",
    "ADPT", "ADSK", "ADTN", "ADUS", "ADVM", "ADXN", "AEHR", "AEIS",
    "AEMD", "AERI", "AEVA", "AFCG", "AFG", "AFIB", "AFMD", "AGEN",
    "AGIO", "AGLE", "AGNC", "AGRI", "AGRX", "AGTC", "AHCO", "AIHS",
    "AINV", "AIRG", "AIRT", "AKAM", "AKBA", "AKRO", "AKTS", "AKUS",
    "ALBO", "ALDX", "ALEC", "ALGM", "ALGN", "ALGT", "ALHC", "ALIM",
    "ALJJ", "ALKS", "ALLK", "ALLO", "ALLT", "ALLY", "ALNY", "ALOT",
    "ALPN", "ALRM", "ALRS", "ALSK", "ALTA", "ALTG", "ALTO", "ALTR",
    "ALVR", "ALXO", "AMAL", "AMBA", "AMBC", "AMCR", "AMCX", "AMED",
    "AMEH", "AMGN", "AMKR", "AMNB", "AMOT", "AMPE", "AMPH", "AMPL",
    "AMPY", "AMRN", "AMRS", "AMSC", "AMSF", "AMSWA", "AMTB", "AMTX",
    "AMWD", "AMYT", "ANAB", "ANDE", "ANGI", "ANIK", "ANIP", "ANSS",
    "ANTE", "AOSL", "AOUT", "APAM", "APDN", "APEI", "APEX", "APGE",
    "APLD", "APLE", "APLS", "APLT", "APOG", "APPF", "APPN", "APPS",
    "APRN", "APTX", "APVO", "APYX", "AQMS", "AQST", "AQUA", "ARAV",
    "ARAY", "ARCC", "ARCH", "ARCO", "ARCT", "ARDX", "ARES", "ARGX",
    "ARHS", "ARKK", "ARKO", "ARLO", "ARMK", "AROC", "AROW", "ARQT",
    "ARRY", "ARTL", "ARTNA", "ARVN", "ARWR", "ASAI", "ASAN", "ASB",
    "ASGN", "ASIX", "ASLE", "ASML", "ASND", "ASO", "ASPN", "ASPS",
    "ASRT", "ASTC", "ASTE", "ASTR", "ASTS", "ASUR", "ASXC", "ATAI",
    "ATEC", "ATEN", "ATER", "ATGE", "ATHM", "ATHX", "ATKR", "ATLC",
    "ATLO", "ATNF", "ATNI", "ATNM", "ATOM", "ATOS", "ATRA",
]

# ===================== KEY ETFs (Always Scanned) =====================
ETF_SYMBOLS = [
    # Major Index ETFs
    "SPY", "QQQ", "IWM", "DIA", "MDY", "IJR",
    
    # Sector ETFs
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLC", "XLB",
    
    # Leveraged
    "TQQQ", "SQQQ", "SPXU", "UPRO", "SOXL", "SOXS", "TNA", "TZA",
    
    # Volatility
    "VXX", "UVXY", "SVXY",
    
    # Key Thematic
    "ARKK", "ARKG", "ARKF", "ARKW",
    
    # Commodities
    "GLD", "SLV", "USO", "GDX",
]


# ===================== HELPER FUNCTIONS =====================

def get_spy_symbols() -> List[str]:
    """Get SPY constituents (Tier 1 priority)"""
    return list(set(SPY_SYMBOLS))

def get_qqq_symbols() -> List[str]:
    """Get QQQ constituents (Tier 1 priority)"""
    return list(set(QQQ_SYMBOLS))

def get_iwm_symbols() -> List[str]:
    """Get IWM constituents (Tier 3 rotating)"""
    return list(set(IWM_SYMBOLS))

def get_etf_symbols() -> List[str]:
    """Get key ETFs (always scanned)"""
    return list(set(ETF_SYMBOLS))

def get_tier1_symbols() -> List[str]:
    """
    Get Tier 1 symbols (SPY + QQQ + ETFs)
    These are scanned every cycle
    """
    tier1 = set(SPY_SYMBOLS)
    tier1.update(QQQ_SYMBOLS)
    tier1.update(ETF_SYMBOLS)
    return list(tier1)

def get_tier3_symbols() -> List[str]:
    """
    Get Tier 3 symbols (IWM only, excluding those in Tier 1)
    These are scanned in rotating batches
    """
    tier1 = set(get_tier1_symbols())
    tier3 = set(IWM_SYMBOLS) - tier1
    return list(tier3)

def get_all_symbols() -> List[str]:
    """Get all unique symbols across all tiers"""
    all_syms = set()
    all_syms.update(SPY_SYMBOLS)
    all_syms.update(QQQ_SYMBOLS)
    all_syms.update(IWM_SYMBOLS)
    all_syms.update(ETF_SYMBOLS)
    return list(all_syms)

def get_universe_stats() -> Dict:
    """Get statistics about the symbol universe"""
    spy = set(SPY_SYMBOLS)
    qqq = set(QQQ_SYMBOLS)
    iwm = set(IWM_SYMBOLS)
    etfs = set(ETF_SYMBOLS)
    
    tier1 = spy | qqq | etfs
    tier3 = iwm - tier1
    
    return {
        "spy_count": len(spy),
        "qqq_count": len(qqq),
        "iwm_count": len(iwm),
        "etf_count": len(etfs),
        "tier1_count": len(tier1),
        "tier3_count": len(tier3),
        "total_unique": len(spy | qqq | iwm | etfs),
        "overlap_spy_qqq": len(spy & qqq),
        "metadata": UNIVERSE_METADATA
    }

def is_rebalance_due() -> bool:
    """Check if quarterly rebalance is due"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for rebal_date in REBALANCE_DATES:
        if today >= rebal_date and rebal_date > UNIVERSE_METADATA["last_updated"]:
            return True
    return False

def get_next_rebalance_date() -> str:
    """Get the next quarterly rebalance date"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for rebal_date in REBALANCE_DATES:
        if rebal_date > today:
            return rebal_date
    return "2027-03-19"  # Next year Q1


# ===================== LEGACY COMPATIBILITY =====================
# Keep these for backward compatibility with existing code

SP500_SYMBOLS = SPY_SYMBOLS
NASDAQ1000_SYMBOLS = QQQ_SYMBOLS  # QQQ is Nasdaq-100, close enough
RUSSELL2000_SYMBOLS = IWM_SYMBOLS
