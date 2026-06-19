"""
Fundamental Quality Service - 15% of TQS Score

Evaluates fundamental factors:
- Catalyst presence (earnings, news, sector rotation)
- Short interest (squeeze potential)
- Float size (supply/demand dynamics)
- Institutional ownership
- Earnings proximity and score
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FundamentalQualityScore:
    """Result of fundamental quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    catalyst_score: float = 50.0
    short_interest_score: float = 50.0
    float_score: float = 50.0
    institutional_score: float = 50.0
    earnings_score: float = 50.0
    financial_score: float = 50.0  # v389 — ROE/margin/growth/leverage
    
    # Raw values
    has_catalyst: bool = False
    catalyst_type: str = ""
    short_interest_pct: float = 0.0
    float_shares_millions: float = 0.0
    institutional_pct: float = 0.0
    days_to_earnings: Optional[int] = None
    earnings_catalyst_score: int = 0  # -10 to +10
    
    # Reasoning
    factors: list = None
    display_ctx: dict = None  # v391 — extra raw bits for sub-score descriptors
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
        if self.display_ctx is None:
            self.display_ctx = {}

    def _display(self) -> Dict:
        from services.tqs.descriptors import disp
        c = self.display_ctx
        # Catalyst
        if self.has_catalyst and self.catalyst_type:
            cat_read = f"{self.catalyst_type.replace('_', ' ').title()} catalyst"
        elif c.get("has_recent_news"):
            sent = c.get("news_sentiment", 0.0)
            tone = "positive" if sent > 0.1 else "negative" if sent < -0.1 else "mixed"
            cat_read = f"Recent {tone} news"
        else:
            cat_read = "No clear catalyst"
        # Short interest
        if c.get("si_absent"):
            dtc = c.get("days_to_cover")
            si_read = (f"Days-to-cover {dtc:.1f} (no SI%)" if dtc
                       else "No short-interest data")
        else:
            si_read = f"Short interest {self.short_interest_pct:.1f}%"
        # Float
        fl = self.float_shares_millions
        flt_read = ("No float data" if c.get("float_absent")
                    else (f"Float {fl/1000:.2f}B" if fl >= 1000 else f"Float {fl:.0f}M"))
        # Institutional
        inst_read = ("No institutional data" if c.get("inst_absent")
                     else f"Institutional ownership {self.institutional_pct:.0f}%")
        # Earnings
        if self.days_to_earnings is not None:
            earn_read = f"Earnings in {self.days_to_earnings}d"
        elif c.get("post_earnings"):
            earn_read = f"Recent earnings {c.get('post_earnings')}"
        else:
            earn_read = "No earnings within 14d"
        # Financial
        fin_read = (f"IB financials ({c.get('financial_n', 0)}/4 metrics)"
                    if c.get("has_financials") else "No IB financials")
        return {
            "catalyst": disp("Catalyst", self.catalyst_score, cat_read),
            "short_interest": disp("Short Interest", self.short_interest_score,
                                   si_read, absent=c.get("si_absent") and not c.get("days_to_cover")),
            "float": disp("Float", self.float_score, flt_read, absent=c.get("float_absent")),
            "institutional": disp("Institutional", self.institutional_score,
                                  inst_read, absent=c.get("inst_absent")),
            "earnings": disp("Earnings", self.earnings_score, earn_read),
            "financial": disp("Financials", self.financial_score, fin_read,
                              absent=not c.get("has_financials")),
        }

    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "catalyst": round(self.catalyst_score, 1),
                "short_interest": round(self.short_interest_score, 1),
                "float": round(self.float_score, 1),
                "institutional": round(self.institutional_score, 1),
                "earnings": round(self.earnings_score, 1),
                "financial": round(self.financial_score, 1)
            },
            "display": self._display(),
            "raw_values": {
                "has_catalyst": self.has_catalyst,
                "catalyst_type": self.catalyst_type,
                "short_interest_pct": round(self.short_interest_pct, 2),
                "float_shares_millions": round(self.float_shares_millions, 1),
                "institutional_pct": round(self.institutional_pct, 1),
                "days_to_earnings": self.days_to_earnings,
                "earnings_catalyst_score": self.earnings_catalyst_score
            },
            "factors": self.factors
        }


class FundamentalQualityService:
    """Evaluates fundamental quality - 15% of TQS"""
    
    def __init__(self):
        self._ib_service = None
        self._news_service = None
        self._db = None
        
    def set_services(self, ib_service=None, news_service=None, db=None):
        """Wire up dependencies"""
        self._ib_service = ib_service
        self._news_service = news_service
        self._db = db
        
    async def calculate_score(
        self,
        symbol: str,
        direction: str = "long",
        # Pre-fetched data (optional)
        has_catalyst: Optional[bool] = None,
        catalyst_type: Optional[str] = None,
        short_interest_pct: Optional[float] = None,
        float_shares: Optional[int] = None,
        institutional_pct: Optional[float] = None,
        days_to_earnings: Optional[int] = None,
        earnings_catalyst_score: Optional[int] = None,
        has_recent_news: Optional[bool] = None,
        news_sentiment: Optional[float] = None
    ) -> FundamentalQualityScore:
        """
        Calculate fundamental quality score (0-100).
        
        Components:
        - Catalyst presence (30%): News, earnings, sector rotation
        - Short interest (20%): Squeeze potential for longs
        - Float analysis (20%): Supply/demand
        - Institutional ownership (15%): Smart money
        - Earnings proximity (15%): Risk/opportunity
        """
        result = FundamentalQualityScore()
        is_long = direction.lower() == "long"
        _dtc = None  # v385 — FINRA days-to-cover (squeeze fallback when SI% absent)
        _fin = {}  # v389 — IB ReportSnapshot financials (roe/margin/growth/leverage)
        _post_earn = None  # v390 — most recent reported earnings surprise (drift)
        
        # Fetch fundamental data if not provided
        # v19.34.177.1 — route through unified_fundamentals_cache. The
        # cache handles IB-first → Finnhub fallback → Mongo persistence
        # → smart TTL. Replaces the v170.2 inline gate + Finnhub stub.
        try:
            from services.unified_fundamentals_cache import get_cached_fundamentals
            cached = await get_cached_fundamentals(symbol)
            if cached:
                # IB ReportSnapshot doesn't expose short_interest / float /
                # institutional %, but the cache will eventually carry
                # them if a ReportsOwnership integration is added.
                if short_interest_pct is None:
                    short_interest_pct = cached.get("short_interest_percent")
                if float_shares is None:
                    float_shares = cached.get("float_shares")
                if institutional_pct is None:
                    institutional_pct = cached.get("institutional_ownership_percent")
                _dtc = cached.get("days_to_cover")  # v385
                _fin = {  # v389 — IB ReportSnapshot financials (v396 codes)
                    "roe": cached.get("roe_pct"),
                    "margin": cached.get("net_margin_pct"),
                    "growth": (cached.get("proj_lt_growth_pct")
                               if cached.get("proj_lt_growth_pct") is not None
                               else cached.get("eps_change_pct")),
                    "d2e": cached.get("debt_to_equity"),
                }
        except Exception as e:
            logger.debug(f"unified_fundamentals_cache lookup failed for {symbol}: {e}")
                
        # v19.34.220 — read recent news from the FRESH local `news_articles`
        # cache (Finnhub + Yahoo collectors, ~92k docs, updated continuously,
        # FinBERT-scored) instead of the live `news_service.get_ticker_news`.
        # That live path tries IB historical news FIRST with a 30s timeout (it
        # hangs in this ib-direct deployment) and then Finnhub (rate-limited to
        # ~60/min) — completely unusable per-alert across 100+ alerts/scan, which
        # is why catalyst was floored at "no catalyst" (40 → 30% of the pillar).
        # The cache query is a fast indexed lookup: no hang, no rate limit.
        # `news_articles.sentiment` is the FinBERT dict
        # {"sentiment": "positive|negative|neutral", "score": <pos-neg, -1..1>}
        # (None until scored).
        if (self._db is not None and has_catalyst is None
                and has_recent_news is None):
            try:
                from datetime import datetime, timezone, timedelta
                cutoff = (datetime.now(timezone.utc)
                          - timedelta(hours=72)).isoformat()
                rows = list(self._db["news_articles"].find(
                    {"symbol": symbol, "datetime": {"$gte": cutoff}},
                    {"_id": 0, "sentiment": 1},
                ).sort("datetime", -1).limit(20))
                if rows:
                    has_recent_news = True
                    vals = []
                    for r in rows:
                        s = r.get("sentiment")
                        if isinstance(s, dict):
                            sc = s.get("score")
                            if sc is not None:
                                vals.append(max(-1.0, min(1.0, float(sc))))
                            else:
                                lbl = str(s.get("sentiment", "")).lower()
                                vals.append(1.0 if lbl == "positive"
                                            else -1.0 if lbl == "negative" else 0.0)
                        elif isinstance(s, str) and s:
                            lbl = s.lower()
                            vals.append(1.0 if lbl in ("positive", "bullish")
                                        else -1.0 if lbl in ("negative", "bearish")
                                        else 0.0)
                    if vals:
                        news_sentiment = sum(vals) / len(vals)
            except Exception as e:
                logger.debug(f"news cache enrichment failed for {symbol}: {e}")

        # Check earnings calendar
        if self._db is not None and days_to_earnings is None:
            try:
                from datetime import datetime, timezone, timedelta
                earnings_col = self._db["earnings_calendar"]
                if earnings_col is not None:
                    now = datetime.now(timezone.utc)
                    upcoming = earnings_col.find_one({
                        "symbol": symbol,
                        "date": {"$gte": now.isoformat(), "$lte": (now + timedelta(days=14)).isoformat()}
                    })
                    if upcoming:
                        earnings_date = datetime.fromisoformat(upcoming["date"].replace("Z", "+00:00"))
                        days_to_earnings = (earnings_date - now).days
                        earnings_catalyst_score = upcoming.get("earnings_score", 0)
            except Exception as e:
                logger.debug(f"Could not check earnings: {e}")

        # v390 — recent earnings SURPRISE (post-earnings drift): a fresh BEAT is a
        # strong momentum tailwind; a MISS is a drag. Looks back ~10 calendar days.
        if self._db is not None:
            try:
                from datetime import datetime, timezone, timedelta
                _now = datetime.now(timezone.utc)
                recent = self._db["earnings_calendar"].find_one({
                    "symbol": symbol, "is_reported": True,
                    "date": {"$gte": (_now - timedelta(days=10)).isoformat(),
                             "$lte": _now.isoformat()},
                }, sort=[("date", -1)])
                if recent and recent.get("eps_result"):
                    _post_earn = {"result": recent.get("eps_result"),
                                  "eps_surp": recent.get("eps_surprise_pct"),
                                  "rev_result": recent.get("revenue_result")}
            except Exception as e:
                logger.debug(f"Could not check recent earnings: {e}")
                
        # v19.34.309 — track which fundamental data points are genuinely
        # ABSENT. Pre-fix, absent institutional% defaulted to a 50% raw
        # value that SCORED 80, absent float (100M) scored 65, and absent
        # earnings scored 60 — feeding the TQS fundamental pillar an
        # optimistic ~57 baseline for symbols we have NO data on. Below we
        # still set placeholder raw values (for display) but force each
        # genuinely-absent component to a NEUTRAL 50, never optimistic.
        _si_absent = short_interest_pct is None
        _float_absent = float_shares is None
        _inst_absent = institutional_pct is None
        _earnings_absent = days_to_earnings is None

        # Use defaults
        short_interest_pct = short_interest_pct if short_interest_pct is not None else 5.0
        float_shares = float_shares if float_shares is not None else 100_000_000
        institutional_pct = institutional_pct if institutional_pct is not None else 50.0
        has_catalyst = has_catalyst if has_catalyst is not None else False
        catalyst_type = catalyst_type if catalyst_type else ""
        earnings_catalyst_score = earnings_catalyst_score if earnings_catalyst_score is not None else 0
        has_recent_news = has_recent_news if has_recent_news is not None else False
        news_sentiment = news_sentiment if news_sentiment is not None else 0.0
        
        result.short_interest_pct = short_interest_pct
        result.float_shares_millions = float_shares / 1_000_000
        result.institutional_pct = institutional_pct
        result.has_catalyst = has_catalyst
        result.catalyst_type = catalyst_type
        result.days_to_earnings = days_to_earnings
        result.earnings_catalyst_score = earnings_catalyst_score
        
        # 1. Catalyst Score (30% weight)
        if has_catalyst:
            if catalyst_type == "earnings":
                if earnings_catalyst_score >= 7:
                    result.catalyst_score = 95
                    result.factors.append(f"Strong earnings catalyst (score: {earnings_catalyst_score}) (++)")
                elif earnings_catalyst_score >= 4:
                    result.catalyst_score = 80
                    result.factors.append("Positive earnings catalyst (+)")
                elif earnings_catalyst_score > 0:
                    result.catalyst_score = 65
                else:
                    result.catalyst_score = 50
            elif catalyst_type == "news":
                if news_sentiment > 0.5:
                    result.catalyst_score = 85
                    result.factors.append("Strong positive news catalyst (+)")
                elif news_sentiment > 0:
                    result.catalyst_score = 70
                    result.factors.append("Positive news catalyst (+)")
                elif news_sentiment < -0.3:
                    result.catalyst_score = 35
                    result.factors.append("Negative news catalyst (-)")
                else:
                    result.catalyst_score = 55
            elif catalyst_type == "sector_rotation":
                result.catalyst_score = 75
                result.factors.append("Sector rotation catalyst (+)")
            else:
                result.catalyst_score = 70
        elif has_recent_news:
            if is_long and news_sentiment > 0.3:
                result.catalyst_score = 65
                result.factors.append("Recent positive news (+)")
            elif not is_long and news_sentiment < -0.3:
                result.catalyst_score = 65
                result.factors.append("Recent negative news supports short (+)")
            else:
                result.catalyst_score = 50
        else:
            result.catalyst_score = 40
            result.factors.append("No clear catalyst (-)")
            
        # 2. Short Interest Score (20% weight)
        # High SI is bullish for longs (squeeze), bearish for shorts (crowded)
        if is_long:
            if short_interest_pct >= 20:
                result.short_interest_score = 95
                result.factors.append(f"High short interest {short_interest_pct:.1f}% - squeeze potential (++)")
            elif short_interest_pct >= 15:
                result.short_interest_score = 85
                result.factors.append(f"Elevated short interest {short_interest_pct:.1f}% (+)")
            elif short_interest_pct >= 10:
                result.short_interest_score = 70
            elif short_interest_pct >= 5:
                result.short_interest_score = 55
            else:
                result.short_interest_score = 45
        else:  # short
            if short_interest_pct >= 25:
                result.short_interest_score = 30
                result.factors.append(f"Very high SI {short_interest_pct:.1f}% - crowded short (-)")
            elif short_interest_pct >= 15:
                result.short_interest_score = 45
                result.factors.append(f"High SI {short_interest_pct:.1f}% - some squeeze risk (-)")
            elif short_interest_pct >= 8:
                result.short_interest_score = 65
            else:
                result.short_interest_score = 80
                result.factors.append(f"Low SI {short_interest_pct:.1f}% - room to run short (+)")
                
        # 3. Float Score (20% weight)
        # Low float = more volatile, better for momentum
        float_millions = result.float_shares_millions
        
        if float_millions <= 20:
            result.float_score = 90
            result.factors.append(f"Low float ({float_millions:.0f}M) - high movement potential (+)")
        elif float_millions <= 50:
            result.float_score = 80
        elif float_millions <= 100:
            result.float_score = 65
        elif float_millions <= 300:
            result.float_score = 50
        elif float_millions <= 500:
            result.float_score = 40
        else:
            result.float_score = 35
            result.factors.append(f"Large float ({float_millions:.0f}M) - harder to move (-)")
            
        # 4. Institutional Ownership Score (15% weight)
        # 30-70% is ideal - smart money but not over-owned.
        # v391 — INTEGRITY FIX: only score/annotate when data is genuinely
        # present. Pre-fix, absent inst data fell to the placeholder default
        # 50% which landed in the 40-70 "ideal" band and emitted a FALSE
        # positive factor ("Good institutional ownership (50%) (+)") moments
        # before the absent-data neutraliser overwrote the score to 50 —
        # leaving a contradictory, fabricated green factor on the alert.
        if not _inst_absent:
            if 40 <= institutional_pct <= 70:
                result.institutional_score = 80
                result.factors.append(f"Good institutional ownership ({institutional_pct:.0f}%) (+)")
            elif 30 <= institutional_pct < 40:
                result.institutional_score = 70
            elif 70 < institutional_pct <= 85:
                result.institutional_score = 60
            elif institutional_pct > 85:
                result.institutional_score = 45
                result.factors.append(f"Over-owned by institutions ({institutional_pct:.0f}%) (-)")
            elif 15 <= institutional_pct < 30:
                result.institutional_score = 55
            else:
                result.institutional_score = 40
                result.factors.append(f"Low institutional ownership ({institutional_pct:.0f}%) (-)")
            
        # 5. Earnings Proximity Score (15% weight)
        if days_to_earnings is not None:
            if days_to_earnings <= 2:
                # Right before earnings - high risk
                if earnings_catalyst_score >= 5:
                    result.earnings_score = 70
                    result.factors.append(f"Earnings in {days_to_earnings} days - high conviction play")
                else:
                    result.earnings_score = 35
                    result.factors.append(f"Earnings in {days_to_earnings} days - binary event risk (-)")
            elif days_to_earnings <= 7:
                if earnings_catalyst_score >= 3:
                    result.earnings_score = 65
                    result.factors.append(f"Earnings approaching in {days_to_earnings} days")
                else:
                    result.earnings_score = 50
            elif days_to_earnings <= 14:
                result.earnings_score = 55
            else:
                result.earnings_score = 60
        else:
            result.earnings_score = 60  # No earnings soon - neutral

        # v390 — post-earnings drift overrides proximity when a fresh report exists:
        # a recent BEAT (esp. with revenue beat) is a momentum tailwind; MISS a drag.
        if _post_earn:
            _res = (_post_earn.get("result") or "").upper()
            _sp = _post_earn.get("eps_surp")
            _rev = (_post_earn.get("rev_result") or "").upper()
            if _res == "BEAT":
                _b = 78 if (_sp is not None and _sp >= 10) else 70
                if _rev == "BEAT":
                    _b += 6
                result.earnings_score = min(92, _b)
                result.factors.append(
                    f"Recent earnings BEAT{' + rev beat' if _rev == 'BEAT' else ''} — drift (+)")
            elif _res == "MISS":
                _b = 30 if (_sp is not None and _sp <= -10) else 38
                if _rev == "MISS":
                    _b -= 5
                result.earnings_score = max(22, _b)
                result.factors.append("Recent earnings MISS — drift (-)")
            
        # v19.34.309 — absent-data → NEUTRAL 50 (not optimistic). Applied
        # AFTER per-component scoring so PRESENT data is scored exactly as
        # before; only genuinely-absent inputs are neutralised. Without
        # this, a symbol we have no fundamentals on scored inst=80,
        # float=65, earnings=60 → an unearned ~57 pillar baseline.
        if _si_absent:
            # v385 — before neutralising, fall back to FINRA days-to-cover (needs
            # NO float, ~80% universe coverage). High DTC = squeeze fuel for longs /
            # crowded-short risk for shorts. Only when SI% is genuinely unavailable.
            if _dtc and _dtc > 0:
                if is_long:
                    result.short_interest_score = (95 if _dtc >= 10 else 85 if _dtc >= 7
                                                   else 70 if _dtc >= 5 else 60 if _dtc >= 3
                                                   else 52 if _dtc >= 1.5 else 45)
                    result.factors.append(f"Days-to-cover {_dtc:.1f} — squeeze fuel (+)")
                else:
                    result.short_interest_score = (30 if _dtc >= 10 else 42 if _dtc >= 7
                                                   else 55 if _dtc >= 5 else 65 if _dtc >= 3
                                                   else 75 if _dtc >= 1.5 else 80)
                    result.factors.append(f"Days-to-cover {_dtc:.1f} — crowded short (-)")
            else:
                result.short_interest_score = 50.0
                result.factors.append("Short-interest data absent → neutral 50")
        if _float_absent:
            result.float_score = 50.0
            result.factors.append("Float data absent → neutral 50")
        if _inst_absent:
            result.institutional_score = 50.0
            result.factors.append("Institutional-ownership data absent → neutral 50")
        if _earnings_absent and not _post_earn:  # v390 — keep post-earnings drift score
            result.earnings_score = 50.0

        # v389 — Financial-quality sub-score from IB ReportSnapshot (ROE, net
        # margin, EPS growth, leverage). Average the available components; absent
        # → neutral 50 (no penalty for names IB doesn't cover).
        _fc = []
        _roe = _fin.get("roe")
        if _roe is not None:
            _fc.append(90 if _roe >= 20 else 78 if _roe >= 15 else 66 if _roe >= 10
                       else 56 if _roe >= 5 else 48 if _roe >= 0 else 35)
        _mg = _fin.get("margin")
        if _mg is not None:
            _fc.append(90 if _mg >= 20 else 75 if _mg >= 10 else 62 if _mg >= 5
                       else 50 if _mg >= 0 else 35)
        _gr = _fin.get("growth")
        if _gr is not None:
            _fc.append(88 if _gr >= 25 else 72 if _gr >= 10 else 58 if _gr >= 0
                       else 45 if _gr >= -10 else 32)
        _de = _fin.get("d2e")
        if _de is not None:
            _fc.append(80 if _de <= 0.3 else 68 if _de <= 0.7 else 55 if _de <= 1.5
                       else 45 if _de <= 3 else 35)
        if _fc:
            result.financial_score = sum(_fc) / len(_fc)
            result.factors.append(
                f"Financials {result.financial_score:.0f} (ROE/margin/growth/lev, {len(_fc)}/4)")
        else:
            result.financial_score = 50.0

        # v391 — stash raw bits the to_dict descriptor layer needs.
        result.display_ctx = {
            "has_recent_news": bool(has_recent_news),
            "news_sentiment": news_sentiment,
            "si_absent": _si_absent,
            "days_to_cover": _dtc,
            "float_absent": _float_absent,
            "inst_absent": _inst_absent,
            "post_earnings": ((_post_earn.get("result") or "").upper() or None) if _post_earn else None,
            "has_financials": bool(_fc),
            "financial_n": len(_fc),
        }

        # Calculate weighted total (v389 — added financial 0.20; trimmed others)
        result.score = (
            result.catalyst_score * 0.25 +
            result.short_interest_score * 0.20 +
            result.float_score * 0.15 +
            result.institutional_score * 0.10 +
            result.earnings_score * 0.10 +
            result.financial_score * 0.20
        )
        
        # Assign grade
        if result.score >= 85:
            result.grade = "A"
        elif result.score >= 75:
            result.grade = "B+"
        elif result.score >= 65:
            result.grade = "B"
        elif result.score >= 55:
            result.grade = "C+"
        elif result.score >= 45:
            result.grade = "C"
        elif result.score >= 35:
            result.grade = "D"
        else:
            result.grade = "F"
            
        return result


# Singleton
_fundamental_quality_service: Optional[FundamentalQualityService] = None


def get_fundamental_quality_service() -> FundamentalQualityService:
    global _fundamental_quality_service
    if _fundamental_quality_service is None:
        _fundamental_quality_service = FundamentalQualityService()
    return _fundamental_quality_service
