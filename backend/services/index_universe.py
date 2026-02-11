"""
Index Universe Manager
Manages symbol lists for major indices:
- S&P 500 (~500 symbols)
- Nasdaq 100 (~100 symbols)
- Russell 2000 (~2000 symbols)

Supports wave-based scanning with tiered priority
"""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import random

logger = logging.getLogger(__name__)


class IndexType(str, Enum):
    SP500 = "sp500"
    NASDAQ100 = "nasdaq100"
    RUSSELL2000 = "russell2000"
    ETF = "etf"
    CUSTOM = "custom"


@dataclass
class IndexUniverse:
    """Container for index symbols with metadata"""
    index_type: IndexType
    symbols: List[str]
    last_updated: datetime
    
    @property
    def count(self) -> int:
        return len(self.symbols)


class IndexUniverseManager:
    """
    Manages the full trading universe across major indices
    with support for wave-based scanning
    """
    
    def __init__(self):
        self._indices: Dict[IndexType, IndexUniverse] = {}
        self._wave_position: int = 0
        self._wave_size: int = 200
        
        # Initialize with static lists
        self._load_static_indices()
    
    def _load_static_indices(self):
        """Load static index constituent lists"""
        
        # S&P 500 - Top ~500 large cap US stocks
        sp500_symbols = [
            # Technology
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "AVGO", "ORCL", "CSCO", "CRM", "ADBE", "ACN", "IBM", "INTC",
            "AMD", "TXN", "QCOM", "INTU", "AMAT", "NOW", "ADI", "LRCX",
            "MU", "KLAC", "SNPS", "CDNS", "MCHP", "APH", "MSI", "FTNT",
            "PANW", "ADSK", "CTSH", "ANSS", "KEYS", "CDW", "ZBRA", "TYL",
            "EPAM", "IT", "AKAM", "FFIV", "JNPR", "WDC", "STX", "NTAP",
            "HPQ", "HPE", "DELL", "ANET", "MPWR", "SWKS", "QRVO", "TER",
            "ON", "NXPI", "MRVL", "GEN", "ENPH", "SEDG", "FSLR",
            
            # Financials
            "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "AXP",
            "SPGI", "CME", "ICE", "MCO", "CB", "PGR", "MMC", "AON", "TRV",
            "AIG", "ALL", "MET", "PRU", "AFL", "HIG", "CINF", "L", "BRO",
            "USB", "PNC", "TFC", "COF", "DFS", "SYF", "KEY", "CFG", "FITB",
            "HBAN", "RF", "ZION", "MTB", "NTRS", "STT", "BK", "FRC", "SIVB",
            "NDAQ", "CBOE", "MSCI", "FDS", "MKTX", "VRSN",
            
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "DHR",
            "BMY", "AMGN", "GILD", "CVS", "ELV", "CI", "HCA", "ISRG", "SYK",
            "MDT", "BDX", "BSX", "ZBH", "EW", "REGN", "VRTX", "BIIB", "MRNA",
            "ILMN", "DXCM", "IDXX", "IQV", "MTD", "A", "WST", "TECH", "HOLX",
            "BAX", "RMD", "ALGN", "COO", "PODD", "TFX", "XRAY", "HSIC", "HUM",
            "CNC", "MOH", "DVA", "VTRS", "ZTS", "LH", "DGX", "CAH", "MCK",
            
            # Consumer Discretionary
            "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "TJX", "BKNG", "MAR",
            "HLT", "YUM", "CMG", "DG", "DLTR", "ROST", "BBY", "ORLY", "AZO",
            "TSCO", "ULTA", "POOL", "WSM", "RH", "DRI", "LVS", "WYNN", "MGM",
            "CZR", "NCLH", "CCL", "RCL", "EXPE", "ABNB", "GRMN", "LEN", "DHI",
            "PHM", "NVR", "TOL", "KMX", "AN", "LAD", "GPC", "AAP", "APTV",
            "BWA", "LEA", "BRG", "GM", "F", "RIVN", "LCID",
            
            # Consumer Staples
            "WMT", "PG", "COST", "KO", "PEP", "PM", "MO", "MDLZ", "CL",
            "EL", "GIS", "K", "KMB", "SYY", "HSY", "KHC", "KR", "WBA",
            "STZ", "TAP", "BF.B", "ADM", "CAG", "CPB", "HRL", "SJM", "MKC",
            "CHD", "CLX", "CLORX", "TSN",
            
            # Energy
            "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY",
            "PXD", "DVN", "HES", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE",
            "TRGP", "LNG", "CTRA", "APA", "MRO", "NOV",
            
            # Industrials
            "UNP", "UPS", "HON", "RTX", "CAT", "DE", "BA", "GE", "LMT",
            "MMM", "FDX", "NOC", "GD", "CSX", "NSC", "ITW", "EMR", "ETN",
            "ROK", "PH", "CMI", "PCAR", "ODFL", "JBHT", "CHRW", "EXPD",
            "XPO", "DAL", "UAL", "AAL", "LUV", "ALK", "JBLU", "WM", "RSG",
            "AME", "ROP", "IR", "DOV", "SWK", "FAST", "GWW", "CTAS", "PAYX",
            "VRSK", "BR", "LDOS", "J", "FTV", "TDG", "HWM", "WAB", "TT",
            
            # Materials
            "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DD", "DOW",
            "PPG", "CTVA", "VMC", "MLM", "ALB", "EMN", "CE", "CF", "MOS",
            "IFF", "FMC", "LYB", "WRK", "PKG", "IP", "AVY", "SEE", "BLL",
            "AMCR", "BALL",
            
            # Utilities
            "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG",
            "ED", "WEC", "ES", "AWK", "DTE", "AEE", "ETR", "FE", "PPL",
            "CMS", "EVRG", "AES", "NI", "CNP", "PNW", "ATO", "NRG", "LNT",
            
            # Real Estate
            "PLD", "AMT", "EQIX", "CCI", "PSA", "DLR", "O", "WELL", "SPG",
            "VICI", "AVB", "EQR", "VTR", "ARE", "BXP", "UDR", "ESS", "MAA",
            "SUI", "ELS", "CPT", "PEAK", "KIM", "REG", "FRT", "HST", "IRM",
            
            # Communication Services
            "GOOG", "GOOGL", "META", "DIS", "CMCSA", "NFLX", "VZ", "T",
            "TMUS", "CHTR", "WBD", "PARA", "FOX", "FOXA", "EA", "TTWO",
            "MTCH", "OMC", "IPG",
        ]
        
        # Nasdaq 100 - Top tech-heavy large caps
        nasdaq100_symbols = [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "AVGO", "PEP", "COST", "CSCO", "ADBE", "AMD", "CMCSA", "NFLX",
            "INTC", "INTU", "TXN", "QCOM", "AMGN", "HON", "AMAT", "BKNG",
            "ISRG", "SBUX", "VRTX", "ADP", "GILD", "MDLZ", "ADI", "REGN",
            "LRCX", "PYPL", "FISV", "PANW", "KLAC", "MU", "SNPS", "CDNS",
            "MNST", "MAR", "ORLY", "MELI", "FTNT", "CTAS", "CSX", "MCHP",
            "KDP", "ADSK", "ABNB", "NXPI", "AEP", "DXCM", "PCAR", "AZN",
            "PAYX", "CPRT", "MRNA", "ROST", "CHTR", "KHC", "LULU", "WDAY",
            "EXC", "CRWD", "ODFL", "IDXX", "XEL", "FAST", "CTSH", "MRVL",
            "EA", "DLTR", "VRSK", "BIIB", "GEHC", "CSGP", "TEAM", "DDOG",
            "ZS", "ANSS", "ILMN", "FANG", "WBD", "CEG", "BKR", "TTD",
            "ALGN", "EBAY", "SIRI", "ZM", "LCID", "RIVN", "ENPH", "OKTA",
            "DOCU", "SPLK",
        ]
        
        # Russell 2000 - Small caps (representative sample, full list would be 2000)
        # Including most liquid/tradeable names
        russell2000_symbols = [
            # Small Cap Tech
            "APPS", "AXON", "CALX", "CRUS", "DIOD", "ENTG", "FORM", "GLOB",
            "GSHD", "HLIT", "INSP", "ITRI", "KLIC", "LSCC", "MANH", "MASI",
            "MXIM", "NCNO", "OLED", "PEGA", "PLXS", "QLYS", "RMBS", "SLAB",
            "SMTC", "SPSC", "TENB", "TTEC", "VICR", "VIAV", "WRAP", "XPER",
            "ACLS", "AMBA", "APPN", "BAND", "BLKB", "BRZE", "CCCS", "CGNX",
            "CHKP", "COHR", "CREE", "CRUS", "EXTR", "FIVN", "FOXF", "GTLS",
            "ICHR", "INST", "LITE", "LPSN", "MGNI", "MIME", "MXL", "NEOG",
            "NOVT", "NVMI", "ONTO", "PAYO", "PCTY", "PRGS", "PSTG", "PWSC",
            "QTWO", "RIOT", "RPD", "RUBI", "SANM", "SCWX", "SMAR", "SPNS",
            "SPWR", "SSYS", "TBBK", "TDC", "TNDM", "TREE", "TTGT", "VECO",
            
            # Small Cap Healthcare/Biotech
            "ABCL", "ACAD", "AGIO", "AKRO", "ALKS", "ALNY", "ARVN", "ATRA",
            "BEAM", "BHVN", "BLUE", "BMRN", "CARA", "CERS", "CHRS", "CNMD",
            "CORT", "CRSP", "DCPH", "DNLI", "EDIT", "EXAS", "FATE", "FOLD",
            "GERN", "GTHX", "HALOZ", "HALO", "HRMY", "ICPT", "IMVT", "INSM",
            "IONS", "IOVA", "IRWD", "KPTI", "KROS", "KRYS", "LEGN", "LGND",
            "MCRB", "MDGL", "MEDP", "MGNX", "MRUS", "NBIX", "NKTR", "NTRA",
            "NVAX", "PCVX", "PLRX", "PRTA", "PTCT", "PCRX", "RARE", "RCKT",
            "RCUS", "REPL", "RGEN", "RVMD", "RXRX", "SAGE", "SGEN", "SGMO",
            "SNDX", "SRPT", "STOK", "TARS", "TGTX", "TVTX", "TWST", "UTHR",
            "VCNX", "VERA", "VNDA", "VRTX", "XENE", "XNCR", "YMAB", "ZLAB",
            
            # Small Cap Financials
            "AFRM", "ALLY", "CADE", "CBSH", "COLB", "CWBC", "EWBC", "FFBC",
            "FHN", "GBCI", "HOMB", "IBKR", "IBOC", "IBTX", "ITIC", "LKFN",
            "MBIN", "NAVI", "OZK", "PNFP", "PPBI", "QCRH", "SBCF", "SFBS",
            "SFNC", "STBA", "TBBK", "TCBI", "TFSL", "TOWN", "UBSI", "UCBI",
            "UMBF", "WABC", "WAFD", "WSBC", "WTFC",
            
            # Small Cap Consumer
            "ABMD", "AEO", "ANF", "BCPC", "BIG", "BJRI", "BLMN", "BOOT",
            "BROS", "CAKE", "CHUY", "COTY", "CRI", "CROX", "DBI", "DECK",
            "DKS", "EAT", "EYE", "FIVE", "FOXF", "FWRD", "GDEN", "GES",
            "GOLF", "GOOS", "GPRO", "GRBK", "GRWG", "HAYW", "HBI", "HIBB",
            "HLF", "HZO", "JACK", "JJSF", "KNX", "KRUS", "KSS", "LEVI",
            "LITE", "LL", "LZB", "MCRI", "MELI", "MODG", "NCLH", "NWSA",
            "ODP", "OXM", "PGNY", "PLAY", "PLNT", "PLCE", "PRPL", "PZZA",
            "RGS", "RVLV", "SHAK", "SHOO", "SIG", "SKX", "SMP", "SNBR",
            "SONO", "STAA", "TXRH", "URBN", "USFD", "VFC", "WING", "WRBY",
            "WSM", "WWW", "YETI",
            
            # Small Cap Energy
            "AM", "AR", "AROC", "BCEI", "BHGE", "BOOM", "CALLON", "CDEV",
            "CHK", "CLR", "CNX", "CTRA", "CVE", "DEN", "DO", "EGY", "EPM",
            "ERF", "FANG", "FET", "GPOR", "HLX", "HP", "HPK", "LBRT",
            "LPI", "MGY", "MTDR", "MUR", "NBR", "NE", "NEX", "NOG", "OAS",
            "OIS", "OVV", "PARR", "PDCE", "PDS", "PTEN", "RES", "RIG",
            "RRC", "RTLR", "SM", "SN", "SWN", "TDW", "TELL", "TPIC", "TRP",
            "VAL", "VET", "WHD", "WPX", "WTI", "XEC",
            
            # Small Cap Industrials
            "AAON", "AGCO", "AIMC", "AJRD", "ALSN", "ARCB", "ASGN", "ATKR",
            "AWI", "AYI", "B", "BBSI", "BCO", "BDC", "BERY", "BLD", "BLDR",
            "CBZ", "CNHI", "CRAI", "CW", "DY", "ESAB", "EXP", "EXPO",
            "FELE", "GATX", "GBX", "GEF", "GGG", "GMS", "GNRC", "GVA",
            "HNI", "HRI", "HUBG", "HUBB", "HXL", "IEX", "KAI", "KBR",
            "KFRC", "KMT", "KNX", "LECO", "LII", "MAN", "MATW", "MBC",
            "MIDD", "MLI", "MMS", "MOG.A", "MSA", "MSM", "MWA", "NJR",
            "NPO", "NVT", "OFLX", "OSIS", "PATK", "PGTI", "PLPC", "PNR",
            "POWL", "RBC", "RRX", "SAIA", "SITE", "SKY", "SNA", "SSD",
            "STRL", "SUM", "SXI", "TKR", "TNC", "TREX", "TRN", "UFI",
            "UFPI", "VMI", "WERN", "WLK", "WOR", "WWD", "XYL",
            
            # Small Cap REITs
            "ACC", "ADC", "APLE", "BXMT", "CIO", "COLD", "CONE", "CUZ",
            "DEA", "DEI", "DOC", "EGP", "EPR", "FCPT", "FR", "FSP", "GOOD",
            "GTY", "HIW", "IIPR", "JBGS", "KRG", "LAMR", "LTC", "MAC",
            "NXRT", "OFC", "OHI", "OUT", "PEB", "PGRE", "PK", "PLYM",
            "ROIC", "RPT", "RYN", "SBAC", "SKT", "STAR", "STAG", "STOR",
            "SUI", "TRU", "UE", "UNIT", "VER", "VNO", "WPC", "WRE", "XHR",
            
            # Meme/High Volatility (often in play)
            "GME", "AMC", "BB", "BBBY", "CLOV", "WISH", "WKHS", "RIDE",
            "GOEV", "HYLN", "NKLA", "SPCE", "PLTR", "SOFI", "HOOD", "COIN",
            "RBLX", "UPST", "AFRM", "DKNG", "PENN", "SKLZ", "PTON", "BYND",
            "CRSR", "LMND", "ROOT", "OPEN", "VLDR", "LAZR", "MVIS", "QS",
        ]
        
        # Key ETFs for market context
        etf_symbols = [
            # Major Index ETFs
            "SPY", "QQQ", "IWM", "DIA", "MDY", "IJR",
            # Sector ETFs
            "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLC", "XLB",
            # Leveraged/Inverse
            "TQQQ", "SQQQ", "SPXU", "UPRO", "SOXL", "SOXS", "LABU", "LABD",
            "TNA", "TZA", "FAS", "FAZ", "NUGT", "DUST", "JNUG", "JDST",
            # ARK ETFs
            "ARKK", "ARKG", "ARKF", "ARKQ", "ARKW", "ARKX",
            # Volatility
            "VXX", "UVXY", "SVXY", "VIXY",
            # Bonds/Rates
            "TLT", "IEF", "SHY", "HYG", "LQD", "JNK",
            # Commodities
            "GLD", "SLV", "USO", "UNG", "PPLT", "PALL",
            # International
            "EEM", "EFA", "FXI", "EWJ", "EWZ", "VWO",
        ]
        
        # Store indices
        now = datetime.now(timezone.utc)
        
        self._indices[IndexType.SP500] = IndexUniverse(
            index_type=IndexType.SP500,
            symbols=list(set(sp500_symbols)),  # Remove duplicates
            last_updated=now
        )
        
        self._indices[IndexType.NASDAQ100] = IndexUniverse(
            index_type=IndexType.NASDAQ100,
            symbols=list(set(nasdaq100_symbols)),
            last_updated=now
        )
        
        self._indices[IndexType.RUSSELL2000] = IndexUniverse(
            index_type=IndexType.RUSSELL2000,
            symbols=list(set(russell2000_symbols)),
            last_updated=now
        )
        
        self._indices[IndexType.ETF] = IndexUniverse(
            index_type=IndexType.ETF,
            symbols=etf_symbols,
            last_updated=now
        )
        
        logger.info(f"Loaded index universe: SP500={self._indices[IndexType.SP500].count}, "
                    f"NASDAQ100={self._indices[IndexType.NASDAQ100].count}, "
                    f"RUSSELL2000={self._indices[IndexType.RUSSELL2000].count}, "
                    f"ETFs={self._indices[IndexType.ETF].count}")
    
    # ==================== PUBLIC API ====================
    
    def get_full_universe(self) -> List[str]:
        """Get all unique symbols across all indices"""
        all_symbols: Set[str] = set()
        for index in self._indices.values():
            all_symbols.update(index.symbols)
        return list(all_symbols)
    
    def get_index_symbols(self, index_type: IndexType) -> List[str]:
        """Get symbols for a specific index"""
        if index_type in self._indices:
            return self._indices[index_type].symbols
        return []
    
    def get_universe_count(self) -> int:
        """Get total unique symbol count"""
        return len(self.get_full_universe())
    
    def get_wave(self, wave_number: int, wave_size: int = 200) -> List[str]:
        """Get a specific wave of symbols for scanning"""
        all_symbols = self.get_full_universe()
        start_idx = wave_number * wave_size
        end_idx = start_idx + wave_size
        return all_symbols[start_idx:end_idx]
    
    def get_next_wave(self, wave_size: int = 200) -> tuple[List[str], int]:
        """Get next wave and advance position"""
        all_symbols = self.get_full_universe()
        total_waves = (len(all_symbols) + wave_size - 1) // wave_size
        
        current_wave = self._wave_position
        start_idx = current_wave * wave_size
        end_idx = min(start_idx + wave_size, len(all_symbols))
        
        symbols = all_symbols[start_idx:end_idx]
        
        # Advance to next wave (wrap around)
        self._wave_position = (self._wave_position + 1) % total_waves
        
        return symbols, current_wave
    
    def reset_wave_position(self):
        """Reset wave position to start"""
        self._wave_position = 0
    
    def get_wave_info(self, wave_size: int = 200) -> Dict:
        """Get information about wave scanning progress"""
        total_symbols = self.get_universe_count()
        total_waves = (total_symbols + wave_size - 1) // wave_size
        
        return {
            "total_symbols": total_symbols,
            "wave_size": wave_size,
            "total_waves": total_waves,
            "current_wave": self._wave_position,
            "symbols_scanned": min(self._wave_position * wave_size, total_symbols),
            "progress_pct": round(self._wave_position / total_waves * 100, 1) if total_waves > 0 else 0
        }
    
    def get_priority_symbols(self, count: int = 200) -> List[str]:
        """
        Get high-priority symbols (most liquid/active)
        Returns Nasdaq 100 + top ETFs
        """
        priority = []
        
        # ETFs first (market context)
        priority.extend(self.get_index_symbols(IndexType.ETF)[:20])
        
        # Nasdaq 100 (most liquid tech)
        priority.extend(self.get_index_symbols(IndexType.NASDAQ100))
        
        # Fill with S&P 500 top names
        remaining = count - len(priority)
        if remaining > 0:
            sp500 = self.get_index_symbols(IndexType.SP500)
            priority.extend(sp500[:remaining])
        
        return list(dict.fromkeys(priority))[:count]  # Remove duplicates, keep order
    
    def get_stats(self) -> Dict:
        """Get universe statistics"""
        return {
            "sp500": self._indices[IndexType.SP500].count,
            "nasdaq100": self._indices[IndexType.NASDAQ100].count,
            "russell2000": self._indices[IndexType.RUSSELL2000].count,
            "etfs": self._indices[IndexType.ETF].count,
            "total_unique": self.get_universe_count(),
            "wave_info": self.get_wave_info()
        }


# Singleton
_universe_manager: Optional[IndexUniverseManager] = None


def get_index_universe() -> IndexUniverseManager:
    """Get or create the index universe manager"""
    global _universe_manager
    if _universe_manager is None:
        _universe_manager = IndexUniverseManager()
    return _universe_manager
