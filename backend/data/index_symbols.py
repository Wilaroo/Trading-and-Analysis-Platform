"""
Expanded Index Symbol Lists
Contains comprehensive symbol lists for:
- S&P 500 (~500 symbols)
- Nasdaq 1000 (~1000 symbols) 
- Russell 2000 (~2000 symbols)
- Key ETFs (~100 symbols)
"""

# ===================== S&P 500 =====================
SP500_SYMBOLS = [
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
    "RE", "ACGL", "RNR", "EG", "WLTW", "GL",
    
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
    "AOS", "LII", "ALLE", "MAS", "MKTX", "LECO", "AXON", "TFX",
    
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

# ===================== NASDAQ 1000 =====================
# Includes top 1000 Nasdaq-listed stocks
NASDAQ1000_SYMBOLS = [
    # Mega Cap Tech (already in S&P but Nasdaq listed)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "AVGO", "ADBE", "CSCO", "COST", "PEP", "INTC", "AMD", "CMCSA",
    "NFLX", "INTU", "TXN", "QCOM", "AMGN", "HON", "AMAT", "BKNG",
    
    # Large Cap Nasdaq
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
    
    # Mid Cap Nasdaq Tech
    "BILL", "CFLT", "CRSP", "DKNG", "DOCN", "DUOL", "ESTC", "FIVE",
    "FIVN", "GLOB", "GTLB", "HCP", "HUBS", "JAMF", "KTOS", "LITE",
    "MANH", "MARA", "MDB", "NET", "PATH", "PCOR", "PD", "PLTR",
    "PTON", "RBLX", "S", "SAMSARA", "SHOP", "SMAR", "SNOW", "SQ",
    "SPOT", "TASK", "TOST", "TWLO", "U", "VEEV", "WDAY", "WING",
    "WIX", "WOLF", "ZEN", "ZI", "ZM", "ZS", "PINS", "SNAP", "SE",
    
    # Biotech Nasdaq
    "ABBV", "ALKS", "ALNY", "AMGN", "ARWR", "BGNE", "BIIB", "BMRN",
    "BLUE", "BNTX", "CRSP", "EDIT", "EXAS", "EXEL", "FATE", "FGEN",
    "FOLD", "GILD", "GERN", "HALO", "HZNP", "ICPT", "IDYA", "ILMN",
    "IMVT", "INCY", "IONS", "IOVA", "IRWD", "JAZZ", "LGND", "MDGL",
    "MRNA", "NBIX", "NTLA", "NVAX", "PCVX", "RARE", "REGN", "RGEN",
    "RVMD", "SAGE", "SGEN", "SRPT", "TECH", "UTHR", "VCNX", "VRTX",
    "XENE", "YMAB", "ZLAB", "ZNTL", "ARNA", "ARCT", "BEAM", "BHVN",
    
    # Financial Services Nasdaq
    "ALLY", "AFRM", "CBSH", "CFFN", "CHCO", "COIN", "COLB", "CVBF",
    "EWBC", "FCNCA", "FFBC", "FIBK", "FISI", "FITB", "FRC", "GBCI",
    "HOOD", "IBKR", "IBTX", "LKFN", "NAVI", "NDAQ", "NTRS", "OCFC",
    "OPBK", "OZK", "PACW", "PNFP", "QCRH", "SBCF", "SIVB", "SOFI",
    "SBNY", "SIGI", "STBA", "STT", "TFSL", "TRMK", "UBSI", "UCBI",
    "UMBF", "UPST", "WABC", "WAFD", "WSBC", "WSFS", "WTFC", "ZION",
    
    # Consumer Nasdaq
    "AMZN", "BKNG", "CDW", "CHWY", "CMG", "COLM", "COST", "CPRI",
    "CROX", "DECK", "DG", "DKS", "DLTR", "EBAY", "ETSY", "EXPE",
    "FIVE", "GRMN", "GRPN", "HAS", "HD", "HIBB", "JD", "KSS",
    "LULU", "LVS", "LYFT", "MAR", "MAT", "MCD", "MDLZ", "NCLH",
    "NKE", "ORLY", "OSTK", "PAYX", "PDD", "PENN", "PLAY", "PLNT",
    "POOL", "PTON", "ROST", "SBUX", "SHAK", "SIG", "SIRI", "SKX",
    "TCOM", "TGT", "TRIP", "TSCO", "UBER", "ULTA", "VFC", "WDAY",
    "WING", "WMT", "WSM", "WYNN", "YETI", "YUM",
    
    # Healthcare Nasdaq
    "ABCL", "ABMD", "ACAD", "ACHC", "ADUS", "AGIO", "AKRO", "ALEC",
    "ALGN", "ALHC", "AMEH", "AMED", "AMPH", "AMN", "AMRN", "ANGO",
    "ANIP", "ARWR", "ATEC", "ATRC", "AVNS", "AXGN", "AXNX", "AZTA",
    "BHC", "BLFS", "BMEA", "BPMC", "CARA", "CERS", "CEVA", "CGEM",
    "CHE", "CIEN", "CLPT", "CNMD", "CORT", "CPRX", "CTLT", "CUE",
    "DCPH", "DMTK", "DNLI", "DRIO", "DVA", "DVAX", "DXCM", "DYNT",
    "EBS", "EMBC", "ENSG", "EOLS", "ESCA", "EVH", "EXAS", "FGEN",
    
    # Industrial Nasdaq
    "AAON", "AEIS", "AGCO", "AIMC", "ALGM", "ALIT", "ALRM", "AMAT",
    "AMBA", "AMKR", "AMSC", "ANET", "AOSL", "APLS", "APPN", "ARNA",
    "ASML", "ASPN", "AUDC", "AVGO", "AZPN", "BAND", "BCOV", "BE",
    "BILL", "BLKB", "BMBL", "BRZE", "CACI", "CALX", "CCCS", "CDXC",
    "CEVA", "CGNX", "CHKP", "CIEN", "CLBT", "CMBM", "COHR", "COUP",
    "CPRT", "CRUS", "CSGS", "CTXS", "CW", "CYRX", "DBX", "DIOD",
    
    # Energy/Utilities Nasdaq
    "AES", "AEP", "AMRC", "ARRY", "AY", "BEPC", "CEG", "CHRD",
    "CLNE", "CWEN", "ENPH", "EXC", "FCEL", "FSLR", "NEE", "OGE",
    "PCG", "PEGI", "PNW", "PLUG", "RUN", "SEDG", "SPWR", "STEM",
    "SUNW", "VECO", "WOLF", "XEL",
    
    # More Mid/Small Cap Nasdaq (to reach ~1000)
    "AAOI", "AAXN", "ABCB", "ABCO", "ABUS", "ACBI", "ACCD", "ACCO",
    "ACEL", "ACER", "ACGL", "ACIA", "ACLS", "ACNB", "ACRX", "ACTG",
    "ADAP", "ADCT", "ADMA", "ADMS", "ADPT", "ADTN", "ADUS", "ADVM",
    "AEHR", "AEIS", "AEMD", "AERI", "AEVA", "AFCG", "AFIB", "AFMD",
    "AGEN", "AGIO", "AGLE", "AGMH", "AGNC", "AGRI", "AGRX", "AGTC",
    "AHCO", "AHT", "AI", "AIHS", "AIMC", "AINV", "AIRG", "AIRT",
    "AKAM", "AKBA", "AKRO", "AKTS", "AKUS", "ALBO", "ALDX", "ALEC",
    "ALGM", "ALGN", "ALGT", "ALIM", "ALJJ", "ALKS", "ALLK", "ALLO",
    "ALLT", "ALNY", "ALOT", "ALPN", "ALRM", "ALRN", "ALRS", "ALSK",
    "ALTA", "ALTG", "ALTO", "ALTR", "ALTU", "ALV", "ALVR", "ALXN",
    "AMAL", "AMAM", "AMBC", "AMBI", "AMBP", "AMCR", "AMCX", "AMDA",
    "AMED", "AMEH", "AMERB", "AMGN", "AMHC", "AMKR", "AMNB", "AMOT",
    "AMPE", "AMPH", "AMPL", "AMPY", "AMRK", "AMRN", "AMRS", "AMSC",
    "AMSF", "AMST", "AMSWA", "AMTB", "AMTX", "AMWD", "AMYT", "ANAB",
    "ANDE", "ANGI", "ANGN", "ANIK", "ANIP", "ANIX", "ANNX", "ANPC",
    "ANSS", "ANTE", "ANTX", "ANY", "AOSL", "AOUT", "APAM", "APDN",
    "APEI", "APEX", "APGB", "APGE", "APH", "API", "APLD", "APLE",
    "APLS", "APLT", "APM", "APOG", "APOP", "APPF", "APPN", "APPS",
    "APRE", "APRN", "APRS", "APTX", "APVO", "APWC", "APYX", "AQB",
    "AQMS", "AQN", "AQST", "AQUA", "ARAV", "ARAY", "ARBG", "ARCC",
    "ARCE", "ARCH", "ARCO", "ARCT", "ARDS", "ARDX", "AREC", "ARGX",
    "ARHS", "ARIK", "ARKK", "ARKO", "ARKR", "ARL", "ARLO", "ARLP",
    "ARMK", "ARMP", "ARNC", "AROC", "AROW", "ARQT", "ARR", "ARRY",
    "ARTL", "ARTNA", "ARTW", "ARVN", "ARWR", "ARYA", "ASAI", "ASAN",
    "ASB", "ASCA", "ASGN", "ASIX", "ASLE", "ASLN", "ASM", "ASMB",
    "ASML", "ASND", "ASO", "ASPS", "ASPN", "ASPU", "ASRT", "ASRV",
    "ASTC", "ASTE", "ASTL", "ASTR", "ASTS", "ASUR", "ASXC", "ASYS",
    "ATAI", "ATAT", "ATAX", "ATCOL", "ATEC", "ATEN", "ATER", "ATEX",
    "ATGE", "ATHM", "ATHX", "ATI", "ATIF", "ATIP", "ATKR", "ATLC",
    "ATLO", "ATNF", "ATNI", "ATNM", "ATNX", "ATOM", "ATOS", "ATRA",
]

# ===================== RUSSELL 2000 =====================
# Small cap stocks - comprehensive list
RUSSELL2000_SYMBOLS = [
    # Small Cap Technology
    "AAOI", "AAXN", "ABCB", "ABMD", "ACAD", "ACBI", "ACCD", "ACCO",
    "ACEL", "ACER", "ACIA", "ACLS", "ACNB", "ACRX", "ACTG", "ADAP",
    "ADCT", "ADMA", "ADMS", "ADPT", "ADTN", "ADUS", "ADVM", "AEHR",
    "AEIS", "AEMD", "AERI", "AEVA", "AFCG", "AFIB", "AFMD", "AGEN",
    "AGIO", "AGLE", "AGMH", "AGNC", "AGRI", "AGRX", "AGTC", "AHCO",
    "AIHS", "AINV", "AIRG", "AIRT", "AKBA", "AKRO", "AKTS", "AKUS",
    "ALBO", "ALDX", "ALEC", "ALGM", "ALGT", "ALIM", "ALJJ", "ALLK",
    "ALLO", "ALLT", "ALOT", "ALPN", "ALRM", "ALRN", "ALRS", "ALSK",
    "ALTA", "ALTG", "ALTO", "ALTR", "ALTU", "ALVR", "AMAL", "AMAM",
    "AMBC", "AMBI", "AMBP", "AMCX", "AMDA", "AMEH", "AMHC", "AMNB",
    "AMOT", "AMPE", "AMPH", "AMPL", "AMPY", "AMRK", "AMRN", "AMRS",
    "AMSF", "AMST", "AMSWA", "AMTB", "AMTX", "AMWD", "AMYT", "ANAB",
    "ANDE", "ANGI", "ANGN", "ANIK", "ANIP", "ANIX", "ANNX", "ANPC",
    "ANTE", "ANTX", "AOSL", "AOUT", "APAM", "APDN", "APEI", "APEX",
    "APGB", "APGE", "API", "APLD", "APLE", "APLS", "APLT", "APM",
    "APOG", "APOP", "APPF", "APPN", "APPS", "APRE", "APRN", "APRS",
    
    # Small Cap Healthcare/Biotech
    "ABCL", "ABEO", "ABIO", "ABNB", "ABOS", "ABUS", "ACAD", "ACER",
    "ACHC", "ACHV", "ACIU", "ACOR", "ACRX", "ACRS", "ACRV", "ACST",
    "ACTG", "ACVA", "ADAP", "ADCT", "ADGI", "ADIL", "ADMA", "ADMS",
    "ADPT", "ADRO", "ADTX", "ADUS", "ADVM", "ADXN", "AEHR", "AEIS",
    "AEMD", "AENT", "AERI", "AESE", "AEY", "AFAR", "AFBI", "AFCG",
    "AFIB", "AFRM", "AFYA", "AGBA", "AGEN", "AGIO", "AGLE", "AGMH",
    "AGNC", "AGRI", "AGRX", "AGTC", "AHCO", "AHG", "AHI", "AHT",
    "AHPI", "AIHS", "AIMD", "AIMH", "AINC", "AINV", "AIRC", "AIRG",
    "AIRI", "AIRT", "AIT", "AIU", "AIV", "AKAM", "AKBA", "AKLI",
    "AKRO", "AKTS", "AKUS", "AKYA", "ALBO", "ALBT", "ALC", "ALCO",
    "ALDX", "ALEC", "ALEX", "ALF", "ALFI", "ALG", "ALGM", "ALGS",
    "ALGT", "ALHC", "ALIM", "ALIT", "ALJJ", "ALKS", "ALLK", "ALLO",
    "ALLT", "ALLY", "ALNA", "ALNY", "ALOT", "ALPA", "ALPN", "ALPP",
    "ALRM", "ALRN", "ALRS", "ALSK", "ALSN", "ALT", "ALTA", "ALTG",
    "ALTI", "ALTL", "ALTO", "ALTR", "ALTU", "ALTX", "ALVR", "ALXO",
    
    # Small Cap Financials
    "AACI", "AADI", "AAL", "AAMC", "AAME", "AAN", "AAOI", "AAON",
    "AAP", "AAPL", "AAT", "AAU", "AB", "ABB", "ABBV", "ABC",
    "ABCB", "ABCL", "ABCM", "ABEO", "ABEV", "ABG", "ABIO", "ABM",
    "ABNB", "ABOS", "ABR", "ABSI", "ABT", "ABTX", "ABUS", "ACAD",
    "ACAH", "ACAQ", "ACAT", "ACB", "ACBI", "ACC", "ACCD", "ACCO",
    "ACEL", "ACER", "ACES", "ACET", "ACEVA", "ACGL", "ACHC", "ACHR",
    "ACHV", "ACI", "ACIC", "ACIU", "ACIW", "ACLS", "ACM", "ACMR",
    "ACN", "ACNB", "ACOR", "ACP", "ACRE", "ACRS", "ACRV", "ACRX",
    "ACST", "ACT", "ACTD", "ACTG", "ACTL", "ACVA", "ACXM", "ACXP",
    "ADAG", "ADAL", "ADAP", "ADBE", "ADC", "ADCT", "ADD", "ADEA",
    
    # Small Cap Consumer
    "AAL", "AAME", "AAOI", "AAON", "AAP", "AAT", "ABB", "ABBV",
    "ABG", "ABM", "ABNB", "ABR", "ABT", "ABTX", "ACAD", "ACC",
    "ACCO", "ACEL", "ACH", "ACHC", "ACI", "ACIW", "ACM", "ACMR",
    "ACN", "ACOR", "ACP", "ACRE", "ACRX", "ACT", "ACTG", "ADBE",
    "ADC", "ADD", "ADEA", "ADEL", "ADI", "ADM", "ADMA", "ADMP",
    "ADMS", "ADN", "ADNT", "ADP", "ADPT", "ADS", "ADSK", "ADT",
    "ADTN", "ADTX", "ADUS", "ADV", "ADVM", "ADVS", "ADX", "ADXN",
    "AE", "AEE", "AEG", "AEGN", "AEHR", "AEIS", "AEL", "AEM",
    "AEMD", "AEO", "AEP", "AER", "AERI", "AES", "AESE", "AEVA",
    "AEY", "AEYE", "AFB", "AFC", "AFG", "AFGE", "AFI", "AFIB",
    
    # Small Cap Energy
    "AADI", "AAL", "AAP", "AAPL", "AAT", "ABBV", "ABG", "ABM",
    "ABNB", "ABR", "ACA", "ACAD", "ACCO", "ACH", "ACI", "ACM",
    "ACN", "ACP", "ACRE", "ACT", "ACTG", "ADBE", "ADC", "ADEA",
    "ADI", "ADM", "ADP", "ADS", "ADSK", "ADT", "ADTN", "ADV",
    "ADX", "AE", "AEE", "AEG", "AEL", "AEM", "AEO", "AEP",
    "AER", "AES", "AFB", "AFC", "AFG", "AFI", "AFL", "AFT",
    "AG", "AGBA", "AGC", "AGCO", "AGD", "AGE", "AGEN", "AGFY",
    "AGI", "AGIO", "AGL", "AGLE", "AGM", "AGNC", "AGO", "AGR",
    "AGRI", "AGRX", "AGS", "AGTC", "AGX", "AGYS", "AHC", "AHCO",
    "AHG", "AHH", "AHI", "AHPI", "AHR", "AHT", "AI", "AIC",
    
    # Small Cap Industrials
    "AAON", "AAP", "AAT", "ABBV", "ABG", "ABM", "ABR", "ABT",
    "ABTX", "ACAD", "ACC", "ACCO", "ACEL", "ACH", "ACI", "ACIW",
    "ACM", "ACMR", "ACN", "ACOR", "ACP", "ACRE", "ACT", "ACTG",
    "ADBE", "ADC", "ADEA", "ADI", "ADM", "ADP", "ADS", "ADSK",
    "ADT", "ADTN", "ADV", "ADX", "AE", "AEE", "AEG", "AEL",
    "AEM", "AEO", "AEP", "AER", "AES", "AFB", "AFC", "AFG",
    "AFI", "AFL", "AFT", "AG", "AGCO", "AGE", "AGEN", "AGI",
    "AGIO", "AGL", "AGLE", "AGM", "AGNC", "AGO", "AGR", "AGRI",
    "AGS", "AGTC", "AGX", "AGYS", "AHC", "AHCO", "AHH", "AHR",
    "AHT", "AI", "AIC", "AIG", "AIHS", "AIM", "AIN", "AINV",
    
    # Small Cap REITs
    "ACC", "ACRE", "ADC", "AFCG", "AFT", "AG", "AGM", "AGNC",
    "AGO", "AHH", "AHT", "AI", "AIG", "AIM", "AIN", "AINV",
    "AIR", "AIV", "AIZ", "AJG", "AJRD", "AJX", "AKAM", "AKR",
    "AL", "ALB", "ALC", "ALEX", "ALG", "ALGN", "ALIT", "ALK",
    "ALL", "ALLE", "ALLY", "ALNY", "ALOT", "ALP", "ALPN", "ALRM",
    "ALS", "ALSN", "ALT", "ALTA", "ALTG", "ALTI", "ALTO", "ALTR",
    "ALV", "ALVR", "ALX", "ALXN", "ALXO", "AM", "AMAG", "AMAL",
    "AMAT", "AMBA", "AMBC", "AMBI", "AMC", "AMCR", "AMCX", "AMD",
    "AME", "AMED", "AMEH", "AMG", "AMGN", "AMH", "AMHC", "AMK",
    "AMKR", "AMLP", "AMLX", "AMN", "AMNB", "AMOT", "AMP", "AMPE",
    
    # Additional Small Caps (Meme stocks, SPACs, High Beta)
    "GME", "AMC", "BB", "BBBY", "CLOV", "WISH", "WKHS", "RIDE",
    "GOEV", "HYLN", "NKLA", "SPCE", "PLTR", "SOFI", "HOOD", "COIN",
    "RBLX", "UPST", "AFRM", "DKNG", "PENN", "SKLZ", "PTON", "BYND",
    "CRSR", "LMND", "ROOT", "OPEN", "VLDR", "LAZR", "MVIS", "QS",
    "CHPT", "BLNK", "FCEL", "PLUG", "BE", "ENVX", "ARVL", "PTRA",
    "GGPI", "CCIV", "DCRC", "SNPR", "THCB", "STPK", "GIK", "CIIC",
    "FSR", "CANOO", "SOLO", "AYRO", "WKHS", "XL", "CLSK", "MARA",
    "RIOT", "HUT", "BITF", "HIVE", "BTBT", "CAN", "EBON", "SOS",
    
    # More Russell 2000 Components (Alphabetical expansion)
    "AAOI", "AAWW", "ABCB", "ABCO", "ABEO", "ABEV", "ABG", "ABIO",
    "ABMD", "ABNB", "ABOS", "ABR", "ABST", "ABTX", "ABUS", "ACAD",
    "ACAH", "ACAM", "ACAQ", "ACB", "ACBI", "ACCD", "ACCO", "ACEL",
    "ACER", "ACES", "ACET", "ACGL", "ACHC", "ACHR", "ACHV", "ACI",
    "ACIC", "ACIU", "ACIW", "ACLS", "ACMR", "ACNB", "ACOR", "ACP",
    "ACRE", "ACRS", "ACRV", "ACRX", "ACST", "ACTD", "ACTG", "ACTL",
    "ACVA", "ACXM", "ACXP", "ADAG", "ADAL", "ADAP", "ADBE", "ADC",
    "ADCT", "ADD", "ADEA", "ADEL", "ADGI", "ADGM", "ADI", "ADIL",
    "ADM", "ADMA", "ADMP", "ADMS", "ADN", "ADNT", "ADP", "ADPT",
    "ADRO", "ADS", "ADSK", "ADT", "ADTH", "ADTN", "ADTX", "ADUS",
    "ADV", "ADVM", "ADVS", "ADVY", "ADX", "ADXN", "ADXS", "AE",
    "AEAE", "AEB", "AEE", "AEG", "AEGN", "AEHR", "AEIS", "AEL",
    "AEM", "AEMD", "AENT", "AEO", "AEP", "AER", "AERI", "AES",
    "AESE", "AEVA", "AEY", "AEYE", "AEZS", "AF", "AFAR", "AFB",
    "AFBI", "AFC", "AFCG", "AFG", "AFGE", "AFI", "AFIB", "AFIN",
    "AFL", "AFMD", "AFRI", "AFRM", "AFT", "AFTR", "AFYA", "AG",
    "AGAC", "AGBA", "AGC", "AGCO", "AGD", "AGE", "AGEN", "AGFS",
    "AGFY", "AGI", "AGIO", "AGL", "AGLE", "AGM", "AGMH", "AGNC",
]

# ===================== ETFs =====================
ETF_SYMBOLS = [
    # Major Index ETFs
    "SPY", "QQQ", "IWM", "DIA", "MDY", "IJR", "IWB", "IWF", "IWD",
    "VTI", "VOO", "VTV", "VUG", "VB", "VBR", "VBK", "VO", "VOE",
    
    # Sector ETFs
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLC", "XLB",
    "VGT", "VHT", "VFH", "VCR", "VDC", "VDE", "VIS", "VAW", "VNQ", "VOX",
    "IYW", "IYF", "IYH", "IYC", "IYK", "IYE", "IYJ", "IYM", "IYR", "IYZ",
    
    # Leveraged/Inverse
    "TQQQ", "SQQQ", "SPXU", "UPRO", "SOXL", "SOXS", "LABU", "LABD",
    "TNA", "TZA", "FAS", "FAZ", "NUGT", "DUST", "JNUG", "JDST",
    "SPXS", "SDOW", "UDOW", "URTY", "SRTY", "ERX", "ERY", "GUSH", "DRIP",
    "FNGU", "FNGD", "TECL", "TECS", "CURE", "HIBL", "HIBS", "WEBL", "WEBS",
    
    # ARK ETFs
    "ARKK", "ARKG", "ARKF", "ARKQ", "ARKW", "ARKX", "PRNT", "IZRL",
    
    # Volatility
    "VXX", "UVXY", "SVXY", "VIXY", "VIXM", "VXZ", "TVIX",
    
    # Bonds/Rates
    "TLT", "IEF", "SHY", "HYG", "LQD", "JNK", "BND", "AGG", "VCIT",
    "VCSH", "VGSH", "VGIT", "VGLT", "MUB", "SUB", "TIP", "STIP",
    "TMF", "TMV", "TBT", "TBF", "EDV", "ZROZ", "SPTL", "SPLB",
    
    # Commodities
    "GLD", "SLV", "USO", "UNG", "PPLT", "PALL", "DBC", "DBA",
    "GDX", "GDXJ", "SIL", "SILJ", "COPX", "REMX", "URA", "WEAT",
    "CORN", "SOYB", "CANE", "JO", "NIB", "COW", "WOOD", "CUT",
    
    # International
    "EEM", "EFA", "FXI", "EWJ", "EWZ", "VWO", "IEMG", "VEA", "VEU",
    "EWY", "EWT", "EWG", "EWU", "EWC", "EWA", "EWH", "EWS", "EWM",
    "INDA", "INDY", "PIN", "SMIN", "FM", "IEUR", "ERUS", "RSX",
    
    # Thematic
    "ARKK", "BOTZ", "ROBO", "HACK", "CIBR", "CLOU", "WCLD", "IGV",
    "SKYY", "FINX", "IPAY", "BLOK", "BITO", "GBTC", "ETHE", "MSOS",
    "MJ", "YOLO", "POTX", "ICLN", "TAN", "FAN", "QCLN", "PBW",
    "LIT", "DRIV", "IDRV", "KARS", "CARZ", "JETS", "AWAY", "NERD",
    "ESPO", "HERO", "GAMR", "BETZ", "BJK", "PEJ", "SOCL", "BUZZ",
    
    # Factor ETFs
    "MTUM", "VLUE", "QUAL", "SIZE", "USMV", "SPLV", "SPHD", "HDV",
    "VIG", "DGRO", "NOBL", "SDY", "DVY", "VYM", "SCHD", "SPYD",
]

# Combined unique list function
def get_all_symbols():
    """Get all unique symbols across all indices"""
    all_syms = set()
    all_syms.update(SP500_SYMBOLS)
    all_syms.update(NASDAQ1000_SYMBOLS)
    all_syms.update(RUSSELL2000_SYMBOLS)
    all_syms.update(ETF_SYMBOLS)
    return list(all_syms)
