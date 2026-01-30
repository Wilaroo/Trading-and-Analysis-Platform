"""
Chart Patterns Recognition and Knowledge Base
Based on ChartGuys chart pattern cheat sheet
Used for AI pattern recognition, trade opportunity evaluation, and coaching
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class PatternBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternType(Enum):
    CONTINUATION = "continuation"
    REVERSAL = "reversal"
    INDETERMINATE = "indeterminate"


@dataclass
class ChartPattern:
    name: str
    bias: PatternBias
    pattern_type: PatternType
    characteristics: str
    description: str
    entry: str
    stop: str
    target: str
    reliability: str
    invalidation: str
    consolidation: bool = False
    typically_breaks: str = "Up or Down"


CHART_PATTERNS: Dict[str, ChartPattern] = {
    # ==================== BULLISH CONTINUATION PATTERNS ====================
    "ascending_triangle": ChartPattern(
        name="Ascending Triangle",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Flat resistance with rising lows",
        description="Horizontal resistance repeatedly caps price while higher lows compress price upward; a breakout clears overhead supply.",
        entry="Close above flat resistance or retest/flip to support",
        stop="Below the last rising swing low or below breakout retest",
        target="Add triangle height (widest part) to breakout level",
        reliability="Improves with multiple touches and higher lows; watch for volume expansion on breakout",
        invalidation="Rejection that closes back beneath resistance and breaks the rising trendline",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "ascending_channel": ChartPattern(
        name="Ascending Channel",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Parallel rising trendlines",
        description="A trend progresses between two upward-parallel boundaries; pullbacks to the lower boundary attract dip buyers.",
        entry="Buy near lower rail with reversal trigger or on breakout above upper rail",
        stop="Below lower rail (for buy-the-dip) or below the trigger swing low",
        target="Opposite boundary as near-term target; breakout = channel width projected",
        reliability="Mean-reverting within channel; trend at risk if lower rail breaks on volume",
        invalidation="Sustained breakdown of lower rail with expanding volume",
        consolidation=False,
        typically_breaks="Up or Down"
    ),
    
    "bull_flag": ChartPattern(
        name="Bull Flag",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Small parallel channel after a sharp rally",
        description="A sharp advance (flagpole) followed by a brief, downward-tilting or horizontal channel that drifts against the trend; a breakout continues the prior leg.",
        entry="Breakout close above flag top (or intraday break with volume)",
        stop="Below lower flag boundary or most recent higher low",
        target="Project flagpole height from breakout; conservative = flag height",
        reliability="Best after strong, liquid advance; volume should contract in the flag and expand on breakout",
        invalidation="Close back inside/below the flag after breakout or loss of prior swing low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "bull_pennant": ChartPattern(
        name="Bull Pennant",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Small contracting triangle after a sharp rally",
        description="An impulse leg higher, a corrective pause/flag, and a second leg mirroring the first in distance or proportion.",
        entry="Close above the pennant's upper trendline",
        stop="Below the lower trendline or last higher low",
        target="Project pole height from breakout of pennant",
        reliability="Volume typically dries up into the apex and expands on the break",
        invalidation="Failure back into the pennant or breakdown below pennant base",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "cup_and_handle": ChartPattern(
        name="Cup and Handle",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Rounded base with shallow handle",
        description="A rounded U-shaped base that rebuilds sponsorship, followed by a short, light-volume pullback (handle) before a breakout over the rim.",
        entry="Breakout over handle high (often with volume surge)",
        stop="Below handle low or 20% of base depth (tight)",
        target="Add cup depth (rim to bottom) to rim/handle-breakout",
        reliability="Best when handle is tight and forms in the upper half of the base",
        invalidation="Deep/loose handle (>15%), or failure back below rim after breakout",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "falling_wedge_uptrend": ChartPattern(
        name="Falling Wedge (in Uptrend)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Converging pullback against trend",
        description="Price pulls back in a narrowing, downward-sloping range as momentum wanes against the dominant uptrend; upside break resumes trend.",
        entry="Close above upper wedge line or breakout + retest entry",
        stop="Below recent swing low or below lower wedge line",
        target="Measure back to start of wedge or add wedge height at breakout",
        reliability="Higher odds with diminishing volume and bullish momentum divergence",
        invalidation="Failure back into wedge or making a lower low beyond wedge start",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "wyckoff_reaccumulation": ChartPattern(
        name="Wyckoff Re-Accumulation",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Mid-trend base in an uptrend; may include a brief spring/shakeout",
        description="After markup, price builds a range with contracting volume; a Sign of Strength (SOS) and Last Point of Support (LPS) confirm continuation.",
        entry="Breakout over resistance (SOS) or LPS retest that holds",
        stop="Below LPS or spring low",
        target="Project range height from breakout; extend with prior leg symmetry",
        reliability="Improves with tighter pullbacks and volume expansion on SOS",
        invalidation="Failure back into range with loss of LPS/spring",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    # ==================== BEARISH CONTINUATION PATTERNS ====================
    "descending_triangle": ChartPattern(
        name="Descending Triangle",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Flat support with falling highs",
        description="Sellers push lower highs into a flat support floor; a decisive break of the base typically extends the downtrend.",
        entry="Close below horizontal base or base-break retest failure",
        stop="Above most recent lower high or above base after failed retest",
        target="Subtract triangle height from breakdown level",
        reliability="Higher probability with multiple lower highs and expanding volume on break",
        invalidation="Reclaiming the base with strength and breaking the downtrend line",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "descending_channel": ChartPattern(
        name="Descending Channel",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Parallel falling trendlines",
        description="A downtrend contained between two parallel falling lines; rallies to the upper rail often fade.",
        entry="Short near upper rail with reversal trigger or on breakdown below lower rail",
        stop="Above upper rail (for fade) or above breakdown bar high",
        target="Opposite boundary as near-term target; breakout = channel width projected",
        reliability="Mean-reverting within channel; trend risk if upper rail breaks",
        invalidation="Sustained break and hold above upper rail",
        consolidation=False,
        typically_breaks="Up or Down"
    ),
    
    "bear_flag": ChartPattern(
        name="Bear Flag",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Small parallel channel after a sharp decline",
        description="A sharp selloff (flagpole) followed by a brief, upward-tilting or horizontal channel that drifts against the trend; breakdown resumes decline.",
        entry="Breakdown close below flag base",
        stop="Above upper flag boundary or last lower high",
        target="Project flagpole height down from breakdown; conservative = flag height",
        reliability="Best after impulsive selloff; expansion in volume/ATR on break helps",
        invalidation="Close back into/above the flag after breakdown",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "bear_pennant": ChartPattern(
        name="Bear Pennant",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Small contracting triangle after a sharp decline",
        description="A brief, symmetrical triangle that forms after a steep decline; usually resolves lower with the trend.",
        entry="Close below lower pennant line",
        stop="Above upper pennant line or last minor swing high",
        target="Project pole height from pennant breakdown",
        reliability="Volume contraction into apex; expansion on breakdown",
        invalidation="Rejection that closes back inside the pennant after breakdown",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "rising_wedge_downtrend": ChartPattern(
        name="Rising Wedge (in Downtrend)",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Converging counter-trend bounce",
        description="Price rises within narrowing, upward-sloping lines during a broader downtrend; momentum fades before breakdown.",
        entry="Close below lower wedge line",
        stop="Above last swing high or above upper wedge line",
        target="Measure back to wedge origin or subtract wedge height from breakdown",
        reliability="Throwbacks common; divergences often precede breakdown",
        invalidation="Reclaiming and holding above upper wedge line",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "wyckoff_redistribution": ChartPattern(
        name="Wyckoff Re-Distribution",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.CONTINUATION,
        characteristics="Mid-trend range in a downtrend; upthrusts above resistance tend to fail",
        description="After markdown, price forms a range; Sign of Weakness (SOW) and Last Point of Supply (LPSY) rallies fail, leading to continuation.",
        entry="Breakdown through support (SOW) or LPSY failure below resistance",
        stop="Above LPSY or UT/UTAD high",
        target="Subtract range height from breakdown; aim to prior base or leg symmetry",
        reliability="Strongest with drying volume on rallies and expansion on SOW/break",
        invalidation="Reclaim and hold above range resistance/UT high",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    # ==================== BULLISH REVERSAL PATTERNS ====================
    "inverse_head_shoulders": ChartPattern(
        name="Inverse Head & Shoulders",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Three-lows structure; neckline break confirms",
        description="Left shoulder low, lower head, right shoulder higher low; breakout through neckline signals reversal.",
        entry="Close above neckline or neckline retest/throwback that holds",
        stop="Below most recent shoulder low",
        target="Project head-to-neckline distance upward from breakout",
        reliability="Best with rising volume into right shoulder and expansion on break",
        invalidation="Neckline rejection with loss of right shoulder low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "double_bottom": ChartPattern(
        name="Double Bottom (W)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Two similar lows; confirm on peak-between breakout",
        description="Price makes two comparable lows separated by a rally; confirmation comes on a breakout above the intervening peak.",
        entry="Close above the middle peak or retest of that level as support",
        stop="Below the second low",
        target="Add height from lows to middle peak to breakout",
        reliability="Higher odds if second low undercuts slightly on lighter volume (bear trap)",
        invalidation="Break back below the second low after breakout",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "double_bottom_adam_eve": ChartPattern(
        name="Double Bottom (Adam & Eve)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Pointed first low (Adam), rounded second (Eve)",
        description="A V-shaped first low followed by a wider, rounded second low; breakout above the middle peak confirms.",
        entry="Close above middle peak; retest entry acceptable",
        stop="Below Eve's low",
        target="Add pattern height (lowest low to peak between) to breakout",
        reliability="Shape mix often traps shorts; still needs confirmation",
        invalidation="Slip back below breakout and loss of Eve's low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "triple_bottom": ChartPattern(
        name="Triple Bottom",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Three similar lows",
        description="Three comparable swing lows forming a broad base; breakout above intervening highs confirms reversal.",
        entry="Close above resistance formed by intervening highs",
        stop="Below the third low (or average of lows)",
        target="Add base height to breakout above resistance",
        reliability="Rarer; ensure decisive breakout to avoid range continuation",
        invalidation="Failure back into range and loss of recent higher low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "diamond_bottom": ChartPattern(
        name="Diamond Bottom",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Broadening then contracting",
        description="Volatility expands (broadens) then contracts into a diamond; an upside break often flips the trend.",
        entry="Close above upper right edge of diamond",
        stop="Below the last swing low inside/right after breakout",
        target="Add diamond height to breakout",
        reliability="Whipsaws inside the pattern are common; wait for decisive break",
        invalidation="Break back into diamond with momentum",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "falling_wedge_reversal": ChartPattern(
        name="Falling Wedge (after Downtrend)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Converging decline losing momentum",
        description="A narrowing, downward-sloping structure that indicates waning selling pressure; upside break flips trend.",
        entry="Close above upper wedge line or retest entry",
        stop="Below recent swing low",
        target="Return to wedge start or add wedge height from breakout",
        reliability="Improves with bullish divergence and drying volume",
        invalidation="Failure back into wedge or break of breakout retest low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "rounding_bottom": ChartPattern(
        name="Rounding Bottom (Saucer)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Gradual accumulation",
        description="A long, gentle U-shape representing a shift from distribution to accumulation; breakout typically leads to sustained trend.",
        entry="Breakout over rim highs or on early higher-low with confirmation",
        stop="Below last higher low within right side of base",
        target="Add base depth to breakout (rim)",
        reliability="Slow to form; stronger in quality names / indices",
        invalidation="Close back below rim and failure of higher-low structure",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    "descending_broadening_wedge": ChartPattern(
        name="Descending Broadening Wedge",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Diverging falling trendlines",
        description="Price falls with expanding swings; often resolves higher but direction not assured.",
        entry="Edge fades or trade the break with confirmation",
        stop="Beyond opposite edge or recent swing",
        target="Project wedge height from break (direction-dependent)",
        reliability="Similar to ascending variant; look for momentum shifts",
        invalidation="Reversal that re-enters wedge and breaks your trigger swing",
        consolidation=False,
        typically_breaks="Up or Down"
    ),
    
    "bump_run_bullish": ChartPattern(
        name="Bump-and-Run Reversal (Bullish)",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Steep decline, exhaustion bump, then trendline break",
        description="An accelerating downtrend ends with a selling climax (bump), then price breaks the downtrend line and runs higher.",
        entry="Close above downtrend line or on successful retest",
        stop="Below post-break retest low",
        target="Run back to lead-in trendline; extensions via prior congestion",
        reliability="Identification subjective; trendline break + retest improves odds",
        invalidation="Return below downtrend line with momentum",
        consolidation=False,
        typically_breaks="Up"
    ),
    
    "wyckoff_accumulation": ChartPattern(
        name="Wyckoff Accumulation",
        bias=PatternBias.BULLISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Phased base after a downtrend; may spring under support then recover",
        description="Range builds through SC/AR/ST; optional spring undercuts support and snaps back; SOS and LPS confirm markup.",
        entry="Breakout over resistance (SOS) or LPS retest that holds",
        stop="Below LPS or spring low",
        target="Project range height from breakout; use prior congestion for extensions",
        reliability="Best with contracting volume in base and expansion on SOS; spring not required",
        invalidation="Failure back into range with loss of LPS/spring low",
        consolidation=True,
        typically_breaks="Up"
    ),
    
    # ==================== BEARISH REVERSAL PATTERNS ====================
    "head_shoulders": ChartPattern(
        name="Head & Shoulders",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Three-highs structure; neckline break confirms",
        description="Left shoulder high, higher head, right shoulder lower high; breakdown through neckline signals reversal.",
        entry="Close below neckline or neckline throwback failure",
        stop="Above the right shoulder high",
        target="Project head-to-neckline distance downward from breakdown",
        reliability="Best with declining volume from head to right shoulder; volume expansion on break",
        invalidation="Neckline reclaim and rally above right shoulder",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "double_top": ChartPattern(
        name="Double Top (M)",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Two similar highs; confirm on trough-between breakdown",
        description="Two comparable peaks separated by a pullback; confirmation comes on a break of the intervening low.",
        entry="Close below the middle trough; add on throwback failure",
        stop="Above second peak",
        target="Subtract height from highs to intervening low from breakdown",
        reliability="Better if second high is weaker or shows bearish divergence",
        invalidation="Reclaim above the second peak after breakdown",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "double_top_adam_eve": ChartPattern(
        name="Double Top (Adam & Eve)",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Pointed first high (Adam), rounded second (Eve)",
        description="A sharp, pointed first peak followed by a wider, rounded second peak; breakdown through the middle trough confirms.",
        entry="Close below the middle trough; add on throwback failure",
        stop="Above Eve's rounded high",
        target="Subtract pattern height from breakdown",
        reliability="Distinct peak shapes can trap longs; still requires confirmation",
        invalidation="Reclaim above Eve's high",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "triple_top": ChartPattern(
        name="Triple Top",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Three similar highs",
        description="Three attempts to break resistance fail; breakdown below intervening lows confirms.",
        entry="Close below support formed by intervening lows",
        stop="Above the third peak",
        target="Subtract base height from breakdown below support",
        reliability="Rarer; ensure strong breakdown to avoid range continuation",
        invalidation="Reclaim of support and breakout above peaks",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "diamond_top": ChartPattern(
        name="Diamond Top",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Broadening then contracting",
        description="Volatility first expands then contracts into a diamond; breakdown often leads to swift declines.",
        entry="Close below lower right edge of diamond",
        stop="Above last swing high just before/after breakdown",
        target="Subtract diamond height from breakdown",
        reliability="Whippy until resolution; wait for decisive break",
        invalidation="Break back into diamond with momentum",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "rising_wedge_reversal": ChartPattern(
        name="Rising Wedge (after Uptrend)",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Converging advance losing momentum",
        description="Price advances within narrowing, upward-sloping lines; momentum fades and breakdown often flips trend.",
        entry="Close below lower wedge line or on retest failure",
        stop="Above last swing high or above upper wedge line",
        target="Move back to wedge start or subtract wedge height from breakdown",
        reliability="Bearish divergences and light volume into apex strengthen odds",
        invalidation="Sustained reclaim above upper wedge line",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "rounding_top": ChartPattern(
        name="Rounding Top",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Gradual distribution",
        description="A gentle inverted U-shape reflecting distribution; breakdown can accelerate once support gives way.",
        entry="Close below the base support or after a failed retest",
        stop="Above the most recent lower high on the right side",
        target="Subtract base depth from breakdown",
        reliability="Long development; confirmation improves reliability",
        invalidation="Reclaim of base and higher-highs sequence",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    "ascending_broadening_wedge": ChartPattern(
        name="Ascending Broadening Wedge",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Diverging rising trendlines",
        description="Price rises with expanding swings; control alternates, often resolving lower but not guaranteed.",
        entry="Edge fades with reversal trigger or trade the break direction",
        stop="Beyond the opposite edge or recent swing extreme",
        target="Project wedge height from break (direction-dependent)",
        reliability="Whippy; ensure multiple touches (3 per side) for validity",
        invalidation="Sharp reclaim through the wedge after break",
        consolidation=False,
        typically_breaks="Up or Down"
    ),
    
    "bump_run_bearish": ChartPattern(
        name="Bump-and-Run Reversal (Bearish)",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Steep advance, exhaustion bump, then trendline break",
        description="An accelerating uptrend ends with a buying climax (bump), then price breaks the uptrend line and runs lower.",
        entry="Close below uptrend line or on failed retest",
        stop="Above post-break retest high",
        target="Run back to lead-in trendline; further to prior congestion",
        reliability="Subjective; trendline break + retest failure improves odds",
        invalidation="Sustained reclaim above broken trendline",
        consolidation=False,
        typically_breaks="Down"
    ),
    
    "wyckoff_distribution": ChartPattern(
        name="Wyckoff Distribution",
        bias=PatternBias.BEARISH,
        pattern_type=PatternType.REVERSAL,
        characteristics="Phased top after an uptrend; upthrusts (UT/UTAD) above resistance often fail",
        description="Range forms via BC/AR/ST; UT/UTAD traps longs; SOW and LPSY confirm markdown.",
        entry="Breakdown through support (SOW) or LPSY failure below resistance",
        stop="Above LPSY or UT/UTAD high",
        target="Subtract range height from breakdown; aim to prior base",
        reliability="Better with drying volume on rallies and expansion on SOW/break",
        invalidation="Reclaim and hold above resistance/UTAD high",
        consolidation=True,
        typically_breaks="Down"
    ),
    
    # ==================== NEUTRAL/INDETERMINATE PATTERNS ====================
    "symmetrical_triangle": ChartPattern(
        name="Symmetrical Triangle / Equilibrium",
        bias=PatternBias.NEUTRAL,
        pattern_type=PatternType.INDETERMINATE,
        characteristics="Lower highs & higher lows; pressure builds",
        description="Converging trendlines compress price; breakout direction is uncertain but often follows the prior trend.",
        entry="Break + close beyond a trendline; add on retest",
        stop="Beyond opposite trendline or prior swing",
        target="Project height of widest part from breakout",
        reliability="Later-stage breaks near apex can be weaker; watch volume",
        invalidation="Return inside triangle after breakout with loss of retest low / high",
        consolidation=True,
        typically_breaks="Up or Down"
    ),
    
    "broadening_formation": ChartPattern(
        name="Broadening Formation / Megaphone",
        bias=PatternBias.NEUTRAL,
        pattern_type=PatternType.INDETERMINATE,
        characteristics="Expanding highs / lows; rising volatility",
        description="Diverging trendlines create higher highs and lower lows; volatility increases and direction is uncertain until resolution.",
        entry="Edge reversals with confirmation or trend break continuation",
        stop="Beyond recent swing outside the edge you're trading",
        target="Targets less reliable; swing trade edges or project height post-break",
        reliability="High whipsaw risk; manage size and wait for decisive breaks for trend trades",
        invalidation="Rapid reversal that violates your edge or break direction",
        consolidation=False,
        typically_breaks="Up or Down"
    ),
    
    "rectangle": ChartPattern(
        name="Rectangle / Trading Range",
        bias=PatternBias.NEUTRAL,
        pattern_type=PatternType.INDETERMINATE,
        characteristics="Horizontal support and resistance boundaries",
        description="Price consolidates between clear horizontal boundaries; breakout direction determined by prior trend context.",
        entry="Breakout above resistance (long) or below support (short); or fade edges within range",
        stop="Beyond opposite boundary or recent swing",
        target="Project rectangle height from breakout",
        reliability="Multiple touches on both boundaries increases reliability",
        invalidation="Return inside range after breakout; loss of breakout retest level",
        consolidation=True,
        typically_breaks="Up or Down"
    ),
}


class ChartPatternService:
    """Service for chart pattern recognition and analysis"""
    
    def __init__(self):
        self.patterns = CHART_PATTERNS
    
    def get_all_patterns(self) -> List[Dict]:
        """Get all chart patterns as list of dicts"""
        return [self._pattern_to_dict(key, p) for key, p in self.patterns.items()]
    
    def get_pattern(self, pattern_id: str) -> Optional[Dict]:
        """Get a specific pattern by ID"""
        pattern = self.patterns.get(pattern_id)
        if pattern:
            return self._pattern_to_dict(pattern_id, pattern)
        return None
    
    def get_patterns_by_bias(self, bias: str) -> List[Dict]:
        """Get patterns filtered by bias (bullish, bearish, neutral)"""
        bias_enum = PatternBias(bias.lower())
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.bias == bias_enum
        ]
    
    def get_patterns_by_type(self, pattern_type: str) -> List[Dict]:
        """Get patterns filtered by type (continuation, reversal, indeterminate)"""
        type_enum = PatternType(pattern_type.lower())
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.pattern_type == type_enum
        ]
    
    def get_bullish_continuation(self) -> List[Dict]:
        """Get bullish continuation patterns"""
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.bias == PatternBias.BULLISH and p.pattern_type == PatternType.CONTINUATION
        ]
    
    def get_bearish_continuation(self) -> List[Dict]:
        """Get bearish continuation patterns"""
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.bias == PatternBias.BEARISH and p.pattern_type == PatternType.CONTINUATION
        ]
    
    def get_bullish_reversal(self) -> List[Dict]:
        """Get bullish reversal patterns"""
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.bias == PatternBias.BULLISH and p.pattern_type == PatternType.REVERSAL
        ]
    
    def get_bearish_reversal(self) -> List[Dict]:
        """Get bearish reversal patterns"""
        return [
            self._pattern_to_dict(key, p) 
            for key, p in self.patterns.items() 
            if p.bias == PatternBias.BEARISH and p.pattern_type == PatternType.REVERSAL
        ]
    
    def search_patterns(self, query: str) -> List[Dict]:
        """Search patterns by name, characteristics, or description"""
        query_lower = query.lower()
        results = []
        for key, p in self.patterns.items():
            if (query_lower in p.name.lower() or 
                query_lower in p.characteristics.lower() or 
                query_lower in p.description.lower()):
                results.append(self._pattern_to_dict(key, p))
        return results
    
    def get_pattern_for_condition(self, is_uptrend: bool, is_reversal: bool) -> List[Dict]:
        """Get patterns appropriate for current market condition"""
        results = []
        for key, p in self.patterns.items():
            # For uptrend continuation, want bullish continuation
            # For uptrend reversal, want bearish reversal
            # For downtrend continuation, want bearish continuation
            # For downtrend reversal, want bullish reversal
            if is_uptrend:
                if is_reversal and p.bias == PatternBias.BEARISH and p.pattern_type == PatternType.REVERSAL:
                    results.append(self._pattern_to_dict(key, p))
                elif not is_reversal and p.bias == PatternBias.BULLISH and p.pattern_type == PatternType.CONTINUATION:
                    results.append(self._pattern_to_dict(key, p))
            else:  # downtrend
                if is_reversal and p.bias == PatternBias.BULLISH and p.pattern_type == PatternType.REVERSAL:
                    results.append(self._pattern_to_dict(key, p))
                elif not is_reversal and p.bias == PatternBias.BEARISH and p.pattern_type == PatternType.CONTINUATION:
                    results.append(self._pattern_to_dict(key, p))
        return results
    
    def get_knowledge_for_ai(self) -> str:
        """Get formatted pattern knowledge for AI context"""
        sections = []
        
        # Bullish Continuation
        sections.append("=== BULLISH CONTINUATION PATTERNS ===")
        for p in self.get_bullish_continuation():
            sections.append(f"\n**{p['name']}**")
            sections.append(f"Characteristics: {p['characteristics']}")
            sections.append(f"Entry: {p['entry']}")
            sections.append(f"Stop: {p['stop']}")
            sections.append(f"Target: {p['target']}")
        
        # Bearish Continuation
        sections.append("\n\n=== BEARISH CONTINUATION PATTERNS ===")
        for p in self.get_bearish_continuation():
            sections.append(f"\n**{p['name']}**")
            sections.append(f"Characteristics: {p['characteristics']}")
            sections.append(f"Entry: {p['entry']}")
            sections.append(f"Stop: {p['stop']}")
            sections.append(f"Target: {p['target']}")
        
        # Bullish Reversal
        sections.append("\n\n=== BULLISH REVERSAL PATTERNS ===")
        for p in self.get_bullish_reversal():
            sections.append(f"\n**{p['name']}**")
            sections.append(f"Characteristics: {p['characteristics']}")
            sections.append(f"Entry: {p['entry']}")
            sections.append(f"Stop: {p['stop']}")
            sections.append(f"Target: {p['target']}")
        
        # Bearish Reversal
        sections.append("\n\n=== BEARISH REVERSAL PATTERNS ===")
        for p in self.get_bearish_reversal():
            sections.append(f"\n**{p['name']}**")
            sections.append(f"Characteristics: {p['characteristics']}")
            sections.append(f"Entry: {p['entry']}")
            sections.append(f"Stop: {p['stop']}")
            sections.append(f"Target: {p['target']}")
        
        return "\n".join(sections)
    
    def _pattern_to_dict(self, key: str, pattern: ChartPattern) -> Dict:
        """Convert pattern dataclass to dict"""
        return {
            "id": key,
            "name": pattern.name,
            "bias": pattern.bias.value,
            "pattern_type": pattern.pattern_type.value,
            "characteristics": pattern.characteristics,
            "description": pattern.description,
            "entry": pattern.entry,
            "stop": pattern.stop,
            "target": pattern.target,
            "reliability": pattern.reliability,
            "invalidation": pattern.invalidation,
            "consolidation": pattern.consolidation,
            "typically_breaks": pattern.typically_breaks
        }


# Singleton instance
_chart_pattern_service: Optional[ChartPatternService] = None


def get_chart_pattern_service() -> ChartPatternService:
    """Get singleton chart pattern service"""
    global _chart_pattern_service
    if _chart_pattern_service is None:
        _chart_pattern_service = ChartPatternService()
    return _chart_pattern_service
