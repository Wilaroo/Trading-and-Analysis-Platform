"""
Detailed Chart Pattern Analysis Knowledge Base
Based on ChartGuys comprehensive pattern analysis pages
Provides in-depth psychology, reliability stats, trade plans, and nuances for each pattern
"""
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class DetailedPatternAnalysis:
    """Comprehensive pattern analysis with all trading details"""
    name: str
    definition: str
    psychology: str
    reliability_stats: str
    trade_plan: str
    nuances_and_traps: str
    when_to_skip: str
    summary: str


DETAILED_PATTERN_ANALYSIS: Dict[str, DetailedPatternAnalysis] = {
    
    # ==================== BULL FLAG ====================
    "bull_flag": DetailedPatternAnalysis(
        name="Bull Flag",
        definition="""The Bull Flag forms after a strong advance (flagpole) followed by a brief consolidation that drifts against the trend:
- A sharp flagpole rally on heavy volume
- A flag: small downward-sloping channel or rectangle consolidating gains
- Volume typically diminishes during the flag
- Breakout above flag resistance signals continuation""",
        psychology="""The bull flag reflects healthy profit-taking within an uptrend:
- After a sharp advance, short-term traders take profits, causing a minor pullback
- The pullback attracts buyers looking for value, but selling pressure keeps rallies contained
- The result is a controlled drift against the trend that shakes out weak hands
- When resistance gives way, buyers rush back in, continuing the prior momentum""",
        reliability_stats="""Bulkowski's research shows bull flags to be strong continuation setups:
- Upward breakout frequency: ~67%
- Failure rate: ~12%
- Average rise after breakout: ~22%
- Target met rate: ~65%
- Throwback frequency: ~55%

Performance improves when the flag retraces less than half the pole and volume contracts during the flag.""",
        trade_plan="""Entry: Buy on breakout above flag resistance (close above upper trendline). Aggressive traders may enter near the bottom of the flag channel.

Stop Loss: Below lower flag boundary or the most recent higher low within the flag.

Targets: 
- Minimum = Project flagpole height from breakout point
- Secondary = Flag height projected upward
- Extensions = Prior resistance zones

Invalidation: If price breaks below the flag support and holds, or fails to reclaim breakout level after initial push.""",
        nuances_and_traps="""Common pitfalls:
- Overextended poles: If the initial rally is too vertical, exhaustion may prevent continuation
- Too-long consolidations: Flags that drift sideways too long lose their momentum edge
- Volume divergence: Rising volume inside the flag may suggest distribution, not accumulation
- Fakeouts: Quick pops above resistance followed by rejection are common; wait for confirmation
- Shallow vs deep flags: Shallow flags (<38.2% retracement) tend to outperform deep ones""",
        when_to_skip="""Skip this pattern when:
- The flag retraces more than half the pole
- Volume expands during the flag formation
- The consolidation lasts longer than the pole took to form
- Overall market context has turned bearish
- The stock is already overextended on higher timeframes""",
        summary="""The Bull Flag is a bullish continuation pattern that breaks upward ~67% of the time with ~22% average gains. It represents controlled profit-taking before buyers reassert control. Look for shallow consolidations with diminishing volume, followed by breakout confirmation with expanding volume."""
    ),
    
    # ==================== BEAR FLAG ====================
    "bear_flag": DetailedPatternAnalysis(
        name="Bear Flag",
        definition="""The Bear Flag is the bearish mirror of the bull flag, occurring after a sharp downward impulse:
- A steep flagpole down on heavy volume
- A flag: small upward-sloping channel or rectangle that consolidates against the downtrend
- Volume typically diminishes during the flag
- Breakdown below flag support signals continuation of the downtrend""",
        psychology="""The bear flag reflects temporary relief buying within a downtrend:
- After a steep decline, short-sellers take profits, causing price to bounce slightly
- Optimistic dip buyers step in, but their efforts lack conviction
- The result is a weak, upward consolidation against the dominant bearish momentum
- Once support gives way, sellers reassert themselves, resuming the downtrend""",
        reliability_stats="""Bulkowski's analysis shows bear flags to be strong continuation setups:
- Downward breakout frequency: ~67%
- Failure rate: ~12%
- Average decline: ~19%
- Target met rate: ~65%
- Pullback frequency: ~55%

They perform best when the flag portion is shallow and retraces less than half the pole.""",
        trade_plan="""Entry: Short on breakdown below flag support (close under lower trendline). Aggressive traders may pre-emptively short near the top of the flag channel.

Stop Loss: Above the upper flag boundary or recent swing high.

Targets:
- Minimum = Project flagpole length downward from breakdown
- Secondary = Nearby support zones

Invalidation: If price breaks above the flag resistance and holds.""",
        nuances_and_traps="""Common pitfalls:
- Overextended conditions: If the pole is too steep, the market may already be oversold
- Sideways drift: Sometimes the "flag" is flat instead of sloping upward; these act more like rectangles
- Volume divergence: If buying volume expands inside the flag, it may suggest reversal, not continuation
- Short squeeze risk: Heavily shorted stocks can trap bears on flag failures""",
        when_to_skip="""Skip this pattern when:
- The flag retraces more than half the pole
- Price consolidates for too long — risk of reversal builds
- Overall market context has turned bullish
- The stock is already deeply oversold on higher timeframes""",
        summary="""The Bear Flag is a bearish continuation setup, breaking down ~67% of the time with ~19% average declines. It represents weak countertrend buying before sellers reassert control. Look for shallow upward consolidations with diminishing volume, followed by breakdown confirmation."""
    ),
    
    # ==================== HEAD & SHOULDERS ====================
    "head_shoulders": DetailedPatternAnalysis(
        name="Head & Shoulders",
        definition="""The Head & Shoulders is a bearish reversal pattern that signals a potential end to an uptrend:
- Left Shoulder: A rally followed by a decline
- Head: A higher rally forming the peak, then another decline
- Right Shoulder: A lower rally that fails to reach the head's height
- Neckline: Support connecting the lows between shoulders and head
- Breakout: Confirmed when price closes below the neckline with volume""",
        psychology="""This pattern depicts the transition from bullish to bearish control:
- Left Shoulder: Bulls push price higher, showing strength
- Head: Buyers make one more push to new highs, but selling pressure increases
- Right Shoulder: A final rally attempt fails to exceed the head, showing buyers are losing control
- Neckline break: Sellers dominate, launching a new downtrend as support breaks

The psychology reflects diminishing buying conviction and growing distribution by smart money.""",
        reliability_stats="""Bulkowski's data confirms its reliability as a reversal pattern:
- Downward breakout frequency: ~66%
- Failure rate: ~14%
- Average decline after breakdown: ~22%
- Throwback frequency: ~65% (retests are common)
- Target met rate: ~68%

Best performance comes with declining volume into the head and right shoulder, followed by expansion on breakdown.""",
        trade_plan="""Entry: Short when price closes below the neckline. Aggressive traders may enter on weakness at the right shoulder.

Stop Loss: Above the right shoulder (conservative) or above neckline retest (aggressive).

Targets:
- Minimum = Distance from head to neckline projected downward
- Secondary = Major support zones or Fibonacci levels

Invalidation: A sustained break above the right shoulder high invalidates the setup.""",
        nuances_and_traps="""Common pitfalls:
- Neckline slope: A downward-sloping neckline reduces reliability; upward slopes are more bearish
- Volume signature: Declining volume on rallies into the right shoulder is ideal
- False breakdowns: Sometimes price dips below neckline then quickly recovers
- Pattern completion time: Very quick formations (days) are less reliable than those spanning weeks
- Shoulders should be roughly symmetric in time and price""",
        when_to_skip="""Skip this pattern when:
- The head isn't clearly higher than shoulders
- Neckline support is extremely strong (multiple failed tests historically)
- Breakdown volume is weak
- Broader market is strongly bullish, overriding local patterns""",
        summary="""The Head & Shoulders is a bearish reversal, breaking down ~66% of the time with ~22% average declines. It highlights buyer exhaustion and the shift to seller control, confirmed by breakdown below the neckline with volume expansion."""
    ),
    
    # ==================== INVERSE HEAD & SHOULDERS ====================
    "inverse_head_shoulders": DetailedPatternAnalysis(
        name="Inverse Head & Shoulders",
        definition="""The Inverse Head & Shoulders is the bullish mirror image of the standard pattern, signaling reversal of a downtrend:
- Left Shoulder: A decline followed by a rally
- Head: A deeper decline forming the lowest point, then another rally
- Right Shoulder: A shallower decline that fails to reach the head's depth
- Neckline: Resistance across the highs between shoulders and head
- Breakout: Confirmed when price closes above the neckline with volume""",
        psychology="""This pattern depicts seller exhaustion and the re-emergence of buyers:
- Left Shoulder: Bears push price lower but demand responds
- Head: Sellers make one more push to a deeper low, but buying pressure increases
- Right Shoulder: A final attempt to drive lower fails to exceed the head, showing sellers are losing control
- Neckline break: Buyers regain dominance, launching a new uptrend as resistance breaks""",
        reliability_stats="""Bulkowski's data confirms its strength:
- Upward breakout frequency: ~68%
- Failure rate: ~11%
- Average rise after breakout: ~35%
- Throwback frequency: ~58%
- Target met rate: ~67%

This makes it one of the most reliable bullish reversal patterns.""",
        trade_plan="""Entry: Buy on breakout above the neckline. Aggressive traders may enter during right shoulder formation.

Stop Loss: Below the right shoulder (conservative) or below the head (extra conservative).

Targets:
- Minimum = Distance from head to neckline projected upward
- Secondary = Prior resistance zones or extensions

Invalidation: Breakdown below the head after formation negates the setup.""",
        nuances_and_traps="""Common pitfalls:
- Neckline slope: An upward-sloping neckline increases reliability; downward slopes weaken it
- Volume signature: Declining volume into the head and right shoulder, followed by surge on breakout, is ideal
- False breakouts: Neckline clearance without volume often stalls
- Symmetry: More symmetrical shoulders tend to perform better""",
        when_to_skip="""Skip this pattern when:
- The head isn't clearly deeper than shoulders
- Neckline resistance is extremely strong and repeatedly unbroken
- Breakout volume is weak
- Broader market is bearish, reducing bullish odds""",
        summary="""The Inverse Head & Shoulders is a bullish reversal, breaking upward ~68% of the time with ~35% average gains. It highlights seller exhaustion and buyer re-emergence, confirmed by breakout volume above neckline resistance."""
    ),
    
    # ==================== DOUBLE TOP ====================
    "double_top": DetailedPatternAnalysis(
        name="Double Top (M)",
        definition="""The Double Top is a bearish reversal pattern that signals a potential end to an uptrend:
- Two prominent peaks at roughly the same price level, separated by a trough
- A neckline (support level) formed at the lowest point between the two peaks
- Volume usually declines on the second peak
- Confirmation comes when price breaks below the neckline with volume

Visually, it resembles the letter M, with two highs and a breakdown below support.""",
        psychology="""The double top captures the shift from bullish control to bearish dominance:
- The first peak reflects strong demand driving prices higher
- A pullback follows as profit-taking occurs
- Buyers return to test the prior high, but this second rally meets strong resistance — sellers overwhelm buyers at the same price level
- The failure to surpass the first peak erodes confidence, especially as volume wanes
- When the neckline breaks, buyers who entered on the second rally are trapped, adding fuel to the selloff as stops are triggered

This psychology makes the double top one of the most recognizable and emotionally charged reversal setups.""",
        reliability_stats="""Bulkowski's large-scale studies highlight effectiveness:
- Downward breakout frequency: ~65%
- Failure rate: ~17% (price rallies back above peaks)
- Average decline after breakdown: ~20%
- Pullback (retest of neckline): ~65%
- Target met rate: ~64%

The pattern works best when the two peaks are distinct (separated by weeks, not days), and when volume declines on the second peak.""",
        trade_plan="""Entry: Short when price closes below the neckline. Aggressive traders may enter early on weakness at the second peak, but confirmation is safer.

Stop Loss: Above the second peak (conservative) or above neckline retest (aggressive).

Targets:
- Minimum = Distance between peak and neckline projected downward
- Secondary = Major support zones or Fibonacci levels

Invalidation: A sustained break above the second peak invalidates the setup.""",
        nuances_and_traps="""Common pitfalls:
- Time between peaks: Too short (a few candles) reduces reliability; best setups span weeks
- Volume divergence: Declining volume on the second peak improves odds; rising volume reduces reliability
- Throwbacks: Price often retests the neckline after breakdown
- Overextended uptrends: A double top at the end of a parabolic run may lead to sharper-than-average declines
- False breakdowns: Sometimes price dips below the neckline then quickly recovers, trapping shorts""",
        when_to_skip="""Skip this pattern when:
- The two peaks are not at similar levels — pattern may be invalid
- Overall market trend is strongly bullish, which can override the local reversal
- The neckline is sloping upward strongly — less bearish implication
- The pattern forms in very short timeframes with little volume data""",
        summary="""The Double Top is a bearish reversal formation that breaks downward ~65% of the time with ~20% average declines. It reflects failure to overcome resistance twice and a loss of bullish momentum. Traders should wait for neckline confirmation, manage stops carefully, and expect frequent retests."""
    ),
    
    # ==================== DOUBLE BOTTOM ====================
    "double_bottom": DetailedPatternAnalysis(
        name="Double Bottom (W)",
        definition="""The Double Bottom is the bullish mirror image of the double top, signaling a potential reversal of a downtrend:
- Two lows at roughly the same level, separated by a rally
- A neckline (resistance) formed at the peak of the intervening rally
- Volume often declines on the second low and increases on breakout
- Confirmation comes when price closes above the neckline with volume

Visually, it resembles the letter W, with two troughs and a breakout above resistance.""",
        psychology="""The double bottom reflects seller exhaustion and buyer resurgence:
- The first trough forms as sellers push price down aggressively
- A relief rally occurs, but bears reassert control, dragging price back toward prior lows
- At the second trough, selling pressure diminishes — bears can't drive significantly lower
- Buyers sense value and step in more strongly, sparking demand
- Breakout above the neckline confirms control has shifted to bulls""",
        reliability_stats="""Bulkowski's research shows the double bottom to be a solid bullish reversal:
- Upward break frequency: ~65%
- Failure rate: ~16% (price falls back below lows)
- Average rise after breakout: ~35%
- Throwback (retest of neckline): ~64%
- Target met rate: ~66%

Reliability increases when the two troughs are spaced apart (weeks/months), and when volume is heavier on the breakout than at the bottoms.""",
        trade_plan="""Entry: Buy when price breaks above neckline. Aggressive traders may enter on confirmation of the second low with tight stops.

Stop Loss: Below the second trough (conservative) or just under neckline (aggressive).

Targets:
- Minimum = Distance from neckline to trough projected upward
- Secondary = Prior resistance zones

Invalidation: Breakdown below the second trough invalidates the reversal.""",
        nuances_and_traps="""Common pitfalls:
- Premature entries: Many traders enter before neckline breakout, risking false reversals
- Volume importance: Weak breakout volume reduces success odds
- Retests: Neckline retests are common and can shake out early buyers
- Deep second troughs: If the second trough is much deeper, it may signal continuation, not reversal
- Time separation: Short gaps between lows reduce pattern validity""",
        when_to_skip="""Skip this pattern when:
- Neckline resistance is extremely strong (multiple failed tests historically)
- Broader market trend remains bearish
- Troughs are uneven or too close together
- No volume expansion occurs on breakout""",
        summary="""The Double Bottom is a bullish reversal pattern that breaks upward ~65% of the time with ~35% average gains. It reflects exhausted sellers and the return of demand. Reliability improves with well-spaced troughs, declining volume into the second low, and breakout volume expansion."""
    ),
    
    # ==================== ASCENDING TRIANGLE ====================
    "ascending_triangle": DetailedPatternAnalysis(
        name="Ascending Triangle",
        definition="""An Ascending Triangle is a continuation pattern that often forms during an uptrend:
- A horizontal resistance line across swing highs, showing a ceiling of supply
- A rising support line connecting higher lows, showing increasingly aggressive buying
- Multiple touches (ideally at least two highs and two lows) to validate the formation
- Volume typically contracts as price coils

The pattern usually resolves within 2/3 to 3/4 of the way to the triangle's apex.""",
        psychology="""The ascending triangle reflects a battle between buyers and sellers:
- Sellers repeatedly defend a fixed price level (resistance), creating the flat top
- Buyers, however, step in at progressively higher prices, forming the rising bottom trendline
- This squeezing dynamic builds pressure. If sellers can't absorb the increasingly aggressive demand, buyers will overwhelm resistance and spark an upside breakout
- A downward break occurs if demand suddenly evaporates, and the rising support line gives way""",
        reliability_stats="""According to Thomas Bulkowski's extensive research:
- Breakout direction: 63% upward, 37% downward
- Failure rate: ~17%
- Average rise after upward breakout: ~35%
- Average decline after downward breakout: ~16%
- Percentage reaching measured move target: ~70%
- Throwback rate: ~64%
- Timeframe validity: Most reliable on daily charts

These stats suggest the ascending triangle is among the more reliable continuation setups, but throwback frequency means traders should anticipate retests.""",
        trade_plan="""Entry: Enter on breakout close above resistance. Aggressive traders may enter on intraday breakouts, but confirmation is safer.

Stop Loss: Place just below the most recent higher low (for upside breaks) or just above resistance (for downside breaks).

Targets:
- Measured move: Height of the base (difference between horizontal resistance and lowest swing low) projected upward from breakout
- Partial targets at 50% and full height projections are common

Invalidation: If price breaks back below the breakout level after confirmation and fails to reclaim it quickly, the pattern is invalidated.""",
        nuances_and_traps="""Common pitfalls:
- Late apex breaks: If price drifts all the way to the tip of the triangle, reliability decreases. The best breakouts occur 2/3–3/4 into the pattern
- False breakouts: A quick wick above resistance followed by rejection is common. Volume confirmation helps filter these out
- Throwbacks: Expect the breakout level to be retested. This can shake out early entries, but provides a second chance for patient traders
- Trend context: Works best as a continuation in an established uptrend. When seen in a downtrend, success rates drop
- Liquidity conditions: In thinly traded markets, ascending triangles are more prone to false breaks""",
        when_to_skip="""Skip this pattern when:
- The pattern forms too close to the apex without breakout
- Volume fails to contract during formation (suggests lack of coiling energy)
- Overall market conditions are strongly bearish
- The pattern is too small (a few candles); noise overwhelms structure""",
        summary="""The ascending triangle is a robust continuation pattern, historically breaking upward ~63% of the time with an average gain of ~35% when it succeeds. Traders should respect throwbacks and avoid late-apex structures. Confirmation and volume are key."""
    ),
    
    # ==================== CUP AND HANDLE ====================
    "cup_and_handle": DetailedPatternAnalysis(
        name="Cup and Handle",
        definition="""The Cup and Handle is a bullish chart pattern that typically signals continuation of an uptrend:
- Cup: A rounded bottom resembling a "U" shape reflecting gradual correction and recovery. Ideally spans several weeks to months
- Handle: A smaller pullback that drifts downward or sideways after the cup's recovery peak. Often slopes slightly downward on lighter volume
- Breakout: Occurs when price closes above the handle's resistance (the prior cup peak) with strong volume

A valid cup and handle should have a well-formed rounded base and a shallow handle (not more than ~1/3 of the cup depth).""",
        psychology="""The cup and handle represents consolidation followed by renewed bullish demand:
- Cup phase: After a prior advance, traders take profits, leading to a rounded decline. Selling pressure gradually fades, and buyers return, pushing price back to prior highs
- Handle phase: At the former resistance, traders again take profits. Instead of a sharp rejection, the pullback is modest and controlled. This "handle" shakes out weak hands while institutions accumulate
- Breakout: When the handle resolves upward, it shows buyers have absorbed supply and are ready to drive a new advance

This psychology makes the cup and handle a powerful base structure for long-term continuation.""",
        reliability_stats="""Bulkowski's studies show strong performance:
- Upward breakout frequency: ~65%
- Failure rate: ~14%
- Average rise after breakout: ~34%
- Throwback frequency: ~65% (retests are common)
- Target met rate: ~68%

Longer-duration cups (months rather than weeks) with shallow handles tend to produce the best results.""",
        trade_plan="""Entry: Buy when price breaks above the handle's resistance (cup rim). Some traders pre-position during the handle, but confirmation is safer.

Stop Loss: Below the handle's low (conservative) or below breakout point (aggressive).

Targets:
- Minimum = Depth of cup projected upward from breakout
- Secondary = Measured extensions, often 1.5x to 2x the cup depth

Invalidation: Failure occurs if price breaks down below the handle low and does not recover.""",
        nuances_and_traps="""Common pitfalls:
- Deep handles: If the handle retraces more than ~1/3 of the cup depth, reliability falls
- V-shaped cups: Sharp V bottoms lack the controlled accumulation of a rounded cup and are less reliable
- Premature breakouts: Early pushes above the rim without proper handle formation often fail
- Volume is key: Volume should contract in the cup and handle, then expand on breakout
- Time factor: A well-formed cup often takes weeks or months; very short ones tend to be noise""",
        when_to_skip="""Skip this pattern when:
- The handle forms too deep or too long
- Breakout volume is weak
- The cup looks more like a "V" than a rounded base
- Overall market context is bearish, which can override bullish setups""",
        summary="""The Cup and Handle is a bullish continuation/reversal pattern that breaks upward ~65% of the time, averaging ~34% gains. It reflects profit-taking, controlled consolidation, and renewed demand. Reliability is highest with rounded cups, shallow handles, and strong breakout volume."""
    ),
    
    # ==================== FALLING WEDGE ====================
    "falling_wedge": DetailedPatternAnalysis(
        name="Falling Wedge (after Downtrend)",
        definition="""The Falling Wedge in a downtrend is a bullish reversal pattern:
- Both support and resistance lines slope downward and converge
- Price prints lower highs and lower lows, but the declines weaken over time
- Volume often diminishes as the wedge matures
- The breakout is typically upward, marking the end of the downtrend""",
        psychology="""The wedge signals exhaustion of selling:
- Sellers still drive price lower, but each attempt has less strength
- Buyers gradually step in earlier, absorbing supply at higher points
- This shift in balance builds pressure for an eventual upside breakout
- When resistance breaks, short covering and new buying fuel the rally

The psychology is one of gradual capitulation by sellers and reassertion of demand.""",
        reliability_stats="""Bulkowski's falling wedge research:
- Upward break frequency: ~68%
- Failure rate: ~11%
- Average rise after upward breakout: ~38%
- Average decline after downward breakout: ~15%
- Throwback frequency: ~60%

This makes the Falling Wedge one of the more reliable bullish reversal patterns.""",
        trade_plan="""Entry: Go long on breakout above wedge resistance. Conservative traders wait for a throwback retest.

Stop Loss: Place below the wedge's final swing low.

Targets:
- Minimum = Wedge height projected upward
- Additional = Key resistance zones from prior structure

Invalidation: If price breaks below wedge support after forming, the reversal fails.""",
        nuances_and_traps="""Common pitfalls:
- False breakdowns: Price may dip briefly below support before reversing upward
- Timing: Breakouts closer to the 2/3–3/4 point of the wedge are stronger than late-apex breaks
- Volume confirmation: A surge on breakout supports authenticity
- Context: Most effective at the end of extended declines or after capitulation""",
        when_to_skip="""Skip this pattern when:
- Broader market conditions remain strongly bearish, as breakouts may fail
- Wedge is very small or forms over only a few sessions
- Volume expands during formation → may indicate ongoing selling pressure, not exhaustion""",
        summary="""The Falling Wedge in a downtrend is a bullish reversal pattern that breaks upward ~68% of the time, producing ~38% average gains. It reflects exhausted sellers and the re-emergence of buyers. Reliability is highest at the end of extended downtrends."""
    ),
    
    # ==================== RISING WEDGE ====================
    "rising_wedge": DetailedPatternAnalysis(
        name="Rising Wedge (after Uptrend)",
        definition="""The Rising Wedge in an uptrend is a bearish reversal pattern that often develops at the end of an extended bullish run:
- Two upward-sloping, converging trendlines: support below and resistance above
- Price action makes higher highs and higher lows, but each successive high rises at a diminishing rate
- Volume generally contracts as the pattern matures, reflecting waning participation
- A valid wedge requires at least two touches on each trendline

This structure signals that, while bulls are still able to advance, their progress is slowing.""",
        psychology="""The rising wedge at the end of an uptrend reflects exhaustion of buying power:
- Bulls have driven a strong advance, but as price consolidates upward, the lack of conviction shows through narrowing swings
- Each high is higher than the last, but sellers appear earlier, pressing the resistance line
- Buyers are still present, pushing in at higher lows, but the eagerness to chase price upward fades
- The result is a tight upward squeeze, where the pressure eventually shifts in favor of sellers

When support breaks, it often catches late buyers — those who entered near the top anticipating continuation — leading to a sharp downward reaction as stop losses are triggered.""",
        reliability_stats="""Bulkowski's studies show strong bearish reliability:
- Downward break frequency: ~69%
- Failure rate: ~10%
- Average decline after downward breakout: ~15%
- Average rise after upward breakout: ~28%
- Pullback (after breakdown) frequency: ~56%
- Target met rate: ~65%

These figures show the rising wedge is one of the more reliable bearish reversal patterns when appearing after an uptrend.""",
        trade_plan="""Entry: Enter short when price closes below the wedge's rising support. Aggressive traders may enter on intraday breakdown; conservative traders wait for a daily close or retest.

Stop Loss: Place just above the last swing high inside the wedge or above wedge resistance.

Targets:
- Minimum = Project the wedge's maximum height downward from breakdown point
- Secondary = Nearby major support zones or Fibonacci retracements

Invalidation: If price breaks convincingly above wedge resistance and holds, the reversal thesis fails.""",
        nuances_and_traps="""Common pitfalls:
- False upside breaks: Sometimes price pops briefly above resistance, triggering breakout buyers, before rolling over hard. This bull trap is especially common late in euphoric rallies
- Late-apex breakouts: If price drifts toward the point of convergence without resolving, the pattern loses energy and reliability
- Volume confirmation: A true breakdown is usually accompanied by a surge in volume
- Trend strength: In powerful secular bull markets, rising wedges may resolve sideways instead of down""",
        when_to_skip="""Skip this pattern when:
- The wedge forms within a strong bull market where broader momentum is overwhelming
- The pattern is very shallow and resembles an upward channel
- Volume expands during the wedge instead of contracting, suggesting active accumulation""",
        summary="""The Rising Wedge in an uptrend is a reliable bearish reversal, breaking downward ~69% of the time and averaging ~15% declines. It reflects buyer exhaustion and hidden distribution at the top of a rally. Traders should confirm with volume, be cautious of false upside breaks, and favor breakdown entries with well-placed stops."""
    ),
    
    # ==================== SYMMETRICAL TRIANGLE ====================
    "symmetrical_triangle": DetailedPatternAnalysis(
        name="Symmetrical Triangle / Equilibrium",
        definition="""A Symmetrical Triangle forms when price action contracts between lower highs and higher lows, producing two converging trendlines of roughly equal slope:
- Neither side is horizontal; both trendlines angle toward the apex
- Requires at least two swing highs and two swing lows to validate
- Price typically breaks out in the direction of the prior trend, but symmetrical triangles are less predictive than ascending/descending versions""",
        psychology="""The symmetrical triangle represents balance and indecision:
- Sellers push price lower, but buyers defend progressively higher levels
- Each swing contracts in size, showing reduced volatility and energy coiling
- The result is a "neutral" setup — neither buyers nor sellers have a visible edge until the breakout
- A breakout in the direction of the prevailing trend is more likely, but counter-trend moves happen often""",
        reliability_stats="""Bulkowski's data indicates mid-tier reliability:
- Breakout direction: 60% continue the prior trend, 40% reverse
- Failure rate: ~15%
- Average move after breakout: ~34% rise, ~15% decline
- Target met rate: ~64%
- Throwback/pullback frequency: ~59%

Because the breakout direction is less biased, symmetrical triangles are harder to trade purely on structure — context matters.""",
        trade_plan="""Entry: Enter on breakout candle close beyond one of the trendlines.

Stop Loss: Place on the opposite side of the pattern (just inside the triangle).

Targets: 
- Height of the base projected from the breakout point
- Consider scaling out since these patterns are less directional

Invalidation: Breakout fails if price re-enters and sustains inside the triangle after breakout.""",
        nuances_and_traps="""Common pitfalls:
- Neutrality: Don't assume a bullish outcome — these are nearly 50/50 setups compared to ascending/descending
- False breaks: Common if breakout occurs without volume
- Late breaks: As with all triangles, breaks near the apex tend to fail
- Trend bias: Reliability increases when trading in the direction of the prior trend""",
        when_to_skip="""Skip this pattern when:
- Pattern is too short (needs at least 2–3 weeks on daily charts)
- Breakout occurs with no volume
- Market context strongly contradicts the breakout direction
- Be wary of 1h or smaller formations where chop dominates""",
        summary="""The Symmetrical Triangle is a neutral pattern with a slight bias towards continuation, with ~60% chance to break in the direction of the prior trend. Average gains are ~34% on upward breaks and ~15% on downward. Traders should rely on volume and broader trend context, as false breakouts are frequent."""
    ),
    
    # ==================== WYCKOFF ACCUMULATION ====================
    "wyckoff_accumulation": DetailedPatternAnalysis(
        name="Wyckoff Accumulation",
        definition="""The Wyckoff Accumulation schematic is a bullish reversal pattern that describes how "composite operators" (large, informed market participants) accumulate shares after a prolonged downtrend. It unfolds in five phases (A–E):

**Phase A (Stopping the Downtrend):** Preliminary support (PS) and selling climax (SC) appear. Volume surges as panicked sellers capitulate. An automatic rally (AR) follows, then a secondary test (ST) retests the SC area.

**Phase B (Building a Cause):** A prolonged trading range develops. Institutions accumulate quietly. Volume contracts overall.

**Phase C (The Spring):** Price briefly dips below established support (spring/shakeout), triggering stops. Smart money absorbs this supply, marking the final low.

**Phase D (Markup Initiation):** Price rallies showing Sign of Strength (SOS). Last Points of Support (LPS) form — pullbacks where demand dominates.

**Phase E (Trend Emergence):** Full markup begins. Price leaves the range decisively.""",
        psychology="""The Wyckoff Accumulation maps directly onto trader emotions:
- Phase A (Fear and Capitulation): Retail traders panic-sell into the SC. Smart money absorbs at discounts
- Phase B (Indecision): The crowd sees a choppy range. Retail interprets it as weakness, while institutions accumulate stealthily
- Phase C (Deception): The Spring is psychological warfare. Traders are shaken out by the false breakdown. Shorts pile in, only to be trapped
- Phase D (Recognition): Demand shows itself. Higher lows convince latecomers that a new trend may be forming
- Phase E (Greed): Markup accelerates. FOMO buyers rush in, but the best entries have already passed

This psychology explains the transfer of assets from weak hands to strong hands.""",
        reliability_stats="""Modern practitioners provide guidelines:
- Breakout odds: Accumulation ranges resolve upward roughly 65–70% of the time if properly identified
- Failure rate: ~15% (springs can become breakdowns if context is misread)
- Average rally post-accumulation: Often retraces 50–100% of the preceding downtrend
- Spring effectiveness: About 60% of accumulation schematics include a spring; others launch directly from Phase B
- Throwback frequency: ~55%""",
        trade_plan="""Multiple entry points depending on risk tolerance:

**Aggressive entry:** Buy the Spring or subsequent low-volume test in Phase C.
- Stop loss = just below Spring low
- High risk/reward but prone to failure if it's not a true spring

**Moderate entry:** Buy the Sign of Strength (SOS) breakout in Phase D.
- Stop loss = below Last Point of Support (LPS)
- Confirmation reduces risk

**Conservative entry:** Buy during Phase E breakout above range resistance.
- Stop loss = below prior breakout zone
- Safest but least favorable risk/reward

**Targets:**
- First target = measured move (height of accumulation range projected upward)
- Secondary = retracement of prior downtrend (50–100%)

**Invalidation:** Breakdown below the Spring low (or SC in spring-less setups) negates the pattern.""",
        nuances_and_traps="""Common pitfalls:
- Not every range is accumulation: Many sideways structures are distribution or continuation
- Springs vs true breakdowns: Springs work only if volume is absorbed. If breakdown volume expands, the pattern fails
- Re-accumulation confusion: Accumulation after uptrends (re-accumulation) looks similar but functions differently
- Length of Phase B: Longer ranges generally create stronger markups ("cause and effect" principle)
- Overfitting: Traders often force Wyckoff labels onto messy ranges
- Volume analysis is critical: Without tracking supply/demand through volume, the schematic loses edge""",
        when_to_skip="""Skip this pattern when:
- Price action lacks distinct phases — especially without a clear SC/AR foundation
- Broader market is bearish, as macro trends can overwhelm local accumulation
- Volume expands on breakdown attempts (suggesting distribution, not absorption)
- Accumulation range is extremely short (few sessions), increasing chance it's noise""",
        summary="""The Wyckoff Accumulation schematic is a multi-phase bullish reversal pattern, breaking upward ~65–70% of the time. It reflects institutional absorption of supply after a downtrend, marked by a selling climax, range-building, spring/shakeout, and eventual markup. Traders can enter aggressively at the Spring, moderately at SOS/LPS, or conservatively on breakout, with risk/reward varying accordingly. Reliability hinges on volume confirmation and accurate phase recognition."""
    ),
}


class DetailedPatternService:
    """Service for accessing detailed pattern analysis"""
    
    def __init__(self):
        self.analyses = DETAILED_PATTERN_ANALYSIS
    
    def get_detailed_analysis(self, pattern_id: str) -> Optional[Dict]:
        """Get detailed analysis for a specific pattern"""
        analysis = self.analyses.get(pattern_id)
        if analysis:
            return {
                "name": analysis.name,
                "definition": analysis.definition,
                "psychology": analysis.psychology,
                "reliability_stats": analysis.reliability_stats,
                "trade_plan": analysis.trade_plan,
                "nuances_and_traps": analysis.nuances_and_traps,
                "when_to_skip": analysis.when_to_skip,
                "summary": analysis.summary
            }
        return None
    
    def get_all_pattern_ids(self) -> list:
        """Get list of all pattern IDs with detailed analysis"""
        return list(self.analyses.keys())
    
    def search_detailed(self, query: str) -> Optional[Dict]:
        """Search for a pattern by name or keyword"""
        query_lower = query.lower()
        for pattern_id, analysis in self.analyses.items():
            if (query_lower in analysis.name.lower() or 
                query_lower in pattern_id.lower() or
                query_lower in analysis.definition.lower()):
                return self.get_detailed_analysis(pattern_id)
        return None
    
    def get_formatted_for_ai(self, pattern_id: str) -> str:
        """Get formatted detailed analysis for AI context"""
        analysis = self.get_detailed_analysis(pattern_id)
        if not analysis:
            return f"No detailed analysis found for '{pattern_id}'"
        
        return f"""
=== DETAILED ANALYSIS: {analysis['name']} ===

**DEFINITION & IDENTIFICATION:**
{analysis['definition']}

**PATTERN PSYCHOLOGY:**
{analysis['psychology']}

**RELIABILITY STATISTICS:**
{analysis['reliability_stats']}

**TRADE PLAN:**
{analysis['trade_plan']}

**NUANCES & COMMON TRAPS:**
{analysis['nuances_and_traps']}

**WHEN TO SKIP:**
{analysis['when_to_skip']}

**SUMMARY:**
{analysis['summary']}
"""


# Singleton
_detailed_service: Optional[DetailedPatternService] = None

def get_detailed_pattern_service() -> DetailedPatternService:
    global _detailed_service
    if _detailed_service is None:
        _detailed_service = DetailedPatternService()
    return _detailed_service
