"""
Trading Rules Engine - Consolidated knowledge from all SMB cheat sheets
Provides market context analysis, setup validation, and trade management rules
"""
from typing import Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum


class MarketRegime(Enum):
    HIGH_STRENGTH_HIGH_WEAKNESS = "volatile_two_way"
    HIGH_STRENGTH_LOW_WEAKNESS = "strong_uptrend"
    HIGH_WEAKNESS_LOW_STRENGTH = "strong_downtrend"
    LOW_STRENGTH_LOW_WEAKNESS = "choppy_range"
    BREAKOUT_MOMENTUM = "momentum_market"
    RANGE_FADE = "mean_reversion_market"


class TimeOfDay(Enum):
    OPENING_DRIVE = "opening_drive"  # 9:30-9:45
    MORNING_MOMENTUM = "morning_momentum"  # 9:45-10:00
    MORNING_SESSION = "morning_session"  # 10:00-10:45
    LATE_MORNING = "late_morning"  # 10:45-11:30
    MIDDAY = "midday"  # 11:30-1:30
    AFTERNOON = "afternoon"  # 1:30-3:00
    CLOSE = "close"  # 3:00-4:00


class TradingRulesEngine:
    """
    Consolidated trading rules from SMB cheat sheets:
    - Range Break, Spencer Scalp, Tidal Wave, Second Chance, Rubber Band
    - Fashionably Late, Puppy Dog, ORB Enhanced, HitchHiker
    - Breaking News, Back$ide, Off Sides, Gap Give and Go
    """
    
    def __init__(self):
        self.setup_rules = self._build_setup_rules()
        self.market_context_rules = self._build_market_context_rules()
        self.time_rules = self._build_time_rules()
        self.volume_rules = self._build_volume_rules()
        self.exit_rules = self._build_exit_rules()
        self.avoidance_rules = self._build_avoidance_rules()
        self.catalyst_scoring = self._build_catalyst_scoring()
    
    # ==================== MARKET CONTEXT RULES ====================
    
    def _build_market_context_rules(self) -> Dict:
        return {
            "regime_identification": {
                "high_strength_high_weakness": {
                    "description": "Volatile two-way action",
                    "indicators": ["Wide SPY range", "VIX elevated", "Both longs and shorts working"],
                    "preferred_strategies": ["Range Break", "Second Chance", "Off Sides"],
                    "avoid": ["Directional bias trades"],
                    "position_sizing": "Normal to reduced"
                },
                "high_strength_low_weakness": {
                    "description": "Strong uptrend - buy dips",
                    "indicators": ["SPY making HH/HL", "VIX declining", "Sector breadth positive"],
                    "preferred_strategies": ["Spencer Scalp", "HitchHiker", "Gap Give and Go", "Trend Momentum"],
                    "avoid": ["Short scalps", "Fade setups", "Off Sides short"],
                    "position_sizing": "Full size on longs"
                },
                "high_weakness_low_strength": {
                    "description": "Strong downtrend - sell rallies",
                    "indicators": ["SPY making LH/LL", "VIX rising", "Sector breadth negative"],
                    "preferred_strategies": ["Tidal Wave", "Back$ide inverse", "Off Sides short"],
                    "avoid": ["Long scalps", "Breakout longs"],
                    "position_sizing": "Full size on shorts"
                },
                "low_strength_low_weakness": {
                    "description": "Choppy/rangebound - be very selective",
                    "indicators": ["Tight SPY range", "Low volume", "No clear direction"],
                    "preferred_strategies": ["Mean Reversion", "VWAP Fade", "Range Trading"],
                    "avoid": ["Momentum trades", "Breakouts", "Large position sizes"],
                    "position_sizing": "Reduced 50%"
                },
                "breakout_momentum": {
                    "description": "Market rewarding momentum",
                    "indicators": ["Clean breaks holding", "RVOL elevated across market", "Gaps not filling"],
                    "preferred_strategies": ["ORB", "HitchHiker", "Spencer Scalp", "Gap Give and Go"],
                    "avoid": ["Fade trades", "Mean reversion", "Off Sides"],
                    "position_sizing": "Full size"
                },
                "range_fade": {
                    "description": "Market rewarding mean reversion",
                    "indicators": ["Failed breakouts", "Gaps filling", "Chop at levels"],
                    "preferred_strategies": ["Off Sides", "VWAP Fade", "Rubber Band", "Back$ide"],
                    "avoid": ["Breakout trades", "Momentum continuation"],
                    "position_sizing": "Normal"
                }
            },
            "intraday_assessment": {
                "morning_check": [
                    "Overnight futures action and gap direction",
                    "Premarket volume and range",
                    "Key news/earnings releases",
                    "VIX level and direction",
                    "Sector rotation themes"
                ],
                "continuous_monitoring": [
                    "NYSE TICK readings (extreme = +/-1000)",
                    "SPY/QQQ/IWM correlation",
                    "Sector ETF performance",
                    "Volume vs average (RVOL)",
                    "Key level holds/breaks"
                ],
                "reassessment_triggers": [
                    "Major news release",
                    "Fed speaker/economic data",
                    "Failed breakout/breakdown",
                    "Volume spike",
                    "Sector rotation shift"
                ]
            }
        }
    
    # ==================== VOLUME RULES ====================
    
    def _build_volume_rules(self) -> Dict:
        return {
            "rvol_thresholds": {
                "minimum_in_play": 1.5,
                "strong_interest": 2.0,
                "high_conviction": 3.0,
                "exceptional": 5.0,
                "rubber_band_ideal": 5.0
            },
            "volume_patterns": {
                "consolidation_decrease": {
                    "description": "Volume should decrease during consolidation",
                    "threshold": "50% or less of prior candles",
                    "applies_to": ["Spencer Scalp", "Gap Give and Go", "Puppy Dog", "HitchHiker", "Big Dog Consolidation"]
                },
                "volume_capitulation": {
                    "description": "Extreme volume spike signaling exhaustion/capitulation",
                    "threshold": "2x or more the 2nd highest volume candle of day",
                    "applies_to": ["Volume Capitulation (Stuffed Trade)"],
                    "significance": "Buyers giving up - orders absorbed by sellers"
                },
                "breakout_increase": {
                    "description": "Volume should spike on breakout",
                    "threshold": "30%+ increase on break candle",
                    "applies_to": ["All breakout strategies"]
                },
                "equal_volume_bars": {
                    "description": "Sustained volume during consolidation",
                    "pattern": "Similar sized volume bars = institutional accumulation",
                    "applies_to": ["Spencer Scalp"]
                },
                "low_volume_before_break": {
                    "description": "Quiet before the storm",
                    "pattern": "Low volume bar immediately before break",
                    "applies_to": ["Spencer Scalp", "Range Break"]
                },
                "top_5_volume": {
                    "description": "Snapback candle should be high volume",
                    "pattern": "Entry candle in top 5 volume bars of day",
                    "applies_to": ["Rubber Band Scalp"]
                }
            },
            "arvol_rules": {
                "description": "Average Relative Volume for trailing stops",
                "threshold": 3.0,
                "action": "Trail with 2-min bars if ARVOL > 3"
            }
        }
    
    # ==================== TIME OF DAY RULES ====================
    
    def _build_time_rules(self) -> Dict:
        return {
            "optimal_windows": {
                "opening_auction": {
                    "time": "9:30-9:35 AM",
                    "strategies": ["Back-Through Open", "First VWAP Pullback", "Bella Fade", "First Move Up", "First Move Down"],
                    "characteristics": ["Maximum institutional activity", "Opening order flow", "Liquidity grabs"],
                    "caution": "Widest spreads, fastest moves - require tape reading skills"
                },
                "opening_drive": {
                    "time": "9:35-9:45 AM",
                    "strategies": ["Gap Give and Go", "HitchHiker", "ORB"],
                    "characteristics": ["Highest volatility", "Gap resolution", "Institutional positioning"],
                    "caution": "Wide stops, fast moves"
                },
                "morning_momentum": {
                    "time": "9:45-10:00 AM",
                    "strategies": ["Spencer Scalp", "Second Chance", "Trend Momentum"],
                    "characteristics": ["Continuation of opening moves", "First pullbacks"],
                    "caution": "Avoid chasing extended moves"
                },
                "morning_session": {
                    "time": "10:00-10:45 AM",
                    "strategies": ["Spencer Scalp", "Back$ide", "Fashionably Late", "Second Chance", "Off Sides"],
                    "characteristics": ["Best overall trading window", "Clear trends established"],
                    "caution": "None - prime time"
                },
                "late_morning": {
                    "time": "10:45-11:30 AM",
                    "strategies": ["Back$ide", "Second Chance", "Range Break", "Fashionably Late"],
                    "characteristics": ["Trends continuing or reversing", "Second chances on moves"],
                    "caution": "Watch for midday transition"
                },
                "midday": {
                    "time": "11:30 AM-1:30 PM",
                    "strategies": ["Mean Reversion", "VWAP trades", "Off Sides"],
                    "characteristics": ["Lower volume", "Choppier action", "Range-bound"],
                    "caution": "Reduce size, be selective"
                },
                "afternoon": {
                    "time": "1:30-3:00 PM",
                    "strategies": ["Second Chance", "Trend continuation"],
                    "characteristics": ["Volume picks up", "Institutional repositioning"],
                    "caution": "Only ranging stocks for Spencer Scalp"
                },
                "close": {
                    "time": "3:00-4:00 PM",
                    "strategies": ["Time-of-Day Fade", "MOC imbalance plays"],
                    "characteristics": ["Final positioning", "Potential reversals"],
                    "caution": "Increased volatility, wider stops"
                }
            },
            "strategy_time_restrictions": {
                "Gap Give and Go": {"trigger_before": "9:45 AM"},
                "HitchHiker": {"setup_before": "9:59 AM"},
                "Spencer Scalp": {"avoid_after_3pm": True, "exception": "ranging stocks only"},
                "ORB": {"time_exit_options": ["10:30 AM", "11:30 AM"]}
            }
        }
    
    # ==================== SETUP RULES ====================
    
    def _build_setup_rules(self) -> Dict:
        return {
            "consolidation_patterns": {
                "tight_range": {
                    "description": "Consolidation < 20% of day's range",
                    "applies_to": ["Spencer Scalp"],
                    "quality_indicator": True
                },
                "duration": {
                    "minimum": "3 minutes",
                    "optimal_spencer": "20+ minutes",
                    "maximum_gap_give_go": "7 minutes",
                    "hitchhiker": "5-20 minutes"
                },
                "location": {
                    "hod_area": "Near high of day for longs",
                    "lod_area": "Near low of day for shorts",
                    "backside_rule": "> halfway between LOD and VWAP",
                    "gap_give_go": "Above key support level"
                }
            },
            "price_patterns": {
                "higher_highs_higher_lows": {
                    "description": "Trend confirmation",
                    "applies_to": ["Back$ide", "Trend trades"],
                    "minimum_count": 2
                },
                "weaker_bounces": {
                    "description": "3+ iterations of weaker bounces",
                    "applies_to": ["Tidal Wave/Bouncy Ball"],
                    "confirms": "Exhaustion of buyers"
                },
                "double_high_double_low": {
                    "description": "Range with 2 highs and 2 lows",
                    "applies_to": ["Off Sides"],
                    "confirms": "Battle zone established"
                },
                "double_bar_break": {
                    "description": "Single candle clears highs of 2+ prior candles",
                    "applies_to": ["Rubber Band Scalp"],
                    "entry_trigger": True
                }
            },
            "moving_average_rules": {
                "9_ema": {
                    "above_9ema": "Bullish bias - majority of trading above",
                    "below_9ema": "Bearish bias",
                    "cross_vwap": "Fashionably Late trigger",
                    "trail_stop": "Exit on close below 9-EMA",
                    "retouch": "Entry on pullback to 9-EMA (Breaking News trend)"
                },
                "vwap": {
                    "above_vwap": "Bullish intraday bias",
                    "below_vwap": "Bearish intraday bias",
                    "target": "Back$ide exit target",
                    "bounce": "VWAP Bounce strategy entry",
                    "fade": "VWAP Reversion target"
                }
            },
            "support_resistance_rules": {
                "touch_count": {
                    "minimum": 3,
                    "description": "S/R needs 3+ touches to be valid"
                },
                "key_levels": [
                    "Prior day high/low",
                    "Premarket high/low",
                    "Opening range high/low",
                    "VWAP",
                    "Round numbers",
                    "Higher timeframe levels (daily/weekly)"
                ],
                "breakout_validation": {
                    "volume_confirmation": "Required",
                    "hold_above_level": "Required for long",
                    "retest_becomes_support": "Second Chance setup"
                }
            }
        }
    
    # ==================== EXIT RULES ====================
    
    def _build_exit_rules(self) -> Dict:
        return {
            "scaling_methods": {
                "thirds": {
                    "description": "Exit in 3 parts",
                    "targets": ["1:1 R:R", "2:1 R:R", "3:1 R:R or runner"],
                    "applies_to": ["Spencer Scalp", "Rubber Band"]
                },
                "halves": {
                    "description": "Exit in 2 parts",
                    "targets": ["2x measured move", "3x measured move"],
                    "applies_to": ["Tidal Wave/Bouncy Ball"]
                },
                "waves": {
                    "description": "Exit on momentum waves",
                    "first_wave": "1/2 into first rush slowing",
                    "second_wave": "1/2 into grinding acceleration",
                    "applies_to": ["HitchHiker", "Bella Fade"]
                },
                "move2move": {
                    "description": "Exit in 2 legs based on price action",
                    "first_leg": "1/2 into first leg of move",
                    "second_leg": "1/2 into second leg continuation",
                    "applies_to": ["First Move Up", "First Move Down", "Gap Give and Go"]
                },
                "full_exit": {
                    "description": "All out at single target",
                    "target": "VWAP",
                    "applies_to": ["Back$ide", "First VWAP Pullback"]
                },
                "momentum_exit": {
                    "description": "Exit when momentum dies",
                    "triggers": ["Close below 9-EMA", "Two-bar break against"],
                    "applies_to": ["Back-Through Open"]
                }
            },
            "measured_moves": {
                "description": "Target = entry + (range height)",
                "calculation": {
                    "long": "Entry + (High of range - Low of range)",
                    "short": "Entry - (High of range - Low of range)"
                },
                "multipliers": {
                    "conservative": "1x measured move",
                    "standard": "2x measured move",
                    "extended": "3x measured move"
                }
            },
            "trail_stop_methods": {
                "9_ema_trail": {
                    "description": "Trail with 9-EMA on timeframe",
                    "exit_trigger": "Close below 9-EMA",
                    "applies_to": ["Second Chance", "Trend trades"]
                },
                "bar_by_bar": {
                    "description": "Trail with prior bar low (long) or high (short)",
                    "timeframe": "2-min if ARVOL > 3",
                    "applies_to": ["ORB Enhanced"]
                },
                "double_bar_break_exit": {
                    "description": "Exit on two consecutive bars against position",
                    "applies_to": ["Gap Give and Go"]
                }
            },
            "time_exits": {
                "orb_time_stops": ["10:30 AM", "11:30 AM"],
                "end_of_day": "Close all intraday positions by 3:55 PM"
            }
        }
    
    # ==================== STOP LOSS RULES ====================
    
    def get_stop_loss_rules(self) -> Dict:
        return {
            "placement_rules": {
                "consolidation_based": {
                    "description": "$.02 below consolidation low (long) or above high (short)",
                    "applies_to": ["Spencer Scalp", "Gap Give and Go", "HitchHiker", "Puppy Dog"]
                },
                "higher_low_based": {
                    "description": "$.02 below most recent higher low",
                    "applies_to": ["Back$ide"]
                },
                "range_based": {
                    "description": "$.01 outside range boundary",
                    "applies_to": ["Off Sides", "Range Break"]
                },
                "lod_based": {
                    "description": "$.02 below low of day",
                    "applies_to": ["Rubber Band (snapback candle low)"]
                },
                "support_based": {
                    "description": "$.02 below broken resistance (now support)",
                    "applies_to": ["Second Chance"]
                }
            },
            "attempt_limits": {
                "one_and_done": ["Back$ide", "Off Sides", "HitchHiker"],
                "two_strikes": ["Rubber Band - max 2 attempts per day"],
                "re_entry_allowed": {
                    "Gap Give and Go": "Within 3 minutes if range breaks again",
                    "Second Chance": "Never take 3rd time"
                }
            },
            "catalyst_adjustment": {
                "+/-10 catalyst": "Tighter stops - high conviction",
                "+/-6 catalyst": "Wider stops - less certainty"
            }
        }
    
    # ==================== AVOIDANCE RULES ====================
    
    def _build_avoidance_rules(self) -> Dict:
        return {
            "universal_avoidance": [
                "Fighting the bigger picture trend",
                "Trading against SPY/QQQ/IWM direction",
                "Overtrading in choppy conditions",
                "Ignoring market context",
                "Setting monetary profit goals",
                "Trading without predefined stop loss"
            ],
            "strategy_specific": {
                "spencer_scalp": [
                    "After 3 legs into consolidation",
                    "After 3 PM (except ranging stocks)",
                    "Consolidation not near HOD"
                ],
                "rubber_band": [
                    "In cleanly trending markets",
                    "After 2 failed attempts",
                    "Snapback candle not in top 5 volume"
                ],
                "hitchhiker": [
                    "Choppy consolidations (large wicks)",
                    "Initial move was single large candle",
                    "Multiple prior break attempts"
                ],
                "backside": [
                    "Day 1 breakout on higher timeframe",
                    "Stock gapped below higher TF range",
                    "Market trending against trade",
                    "Range not > halfway LOD to VWAP"
                ],
                "off_sides": [
                    "Day 1 breakout stocks with 8+ catalyst",
                    "Market trending opposite to trade",
                    "Slow choppy action after break",
                    "Momentum market conditions"
                ],
                "gap_give_go": [
                    "Consolidation BELOW support level",
                    "Consolidation > 50% of opening move",
                    "Not In Play stock",
                    "Move closes > 50% of gap before consolidation",
                    "Multiple failed attempts before consolidation"
                ],
                "second_chance": [
                    "Never take 3rd time on same setup",
                    "Fighting bigger picture trend"
                ],
                "fashionably_late": [
                    "Price action flat/choppy after turn",
                    "9-EMA flat for 15+ min after turn"
                ],
                "first_vwap_pullback": [
                    "Buying too extended/parabolic",
                    "Pullback goes below premarket high",
                    "Choppy or slow opening auction",
                    "Pullback breaks below VWAP"
                ],
                "first_move_up": [
                    "Slow controlled buying (buying program)",
                    "Initial buying breaks important resistance",
                    "Buying pressure after entry",
                    "VWAP acts as support (institutions buying)"
                ],
                "first_move_down": [
                    "Slow controlled selling (selling program)",
                    "Initial selling breaks important support",
                    "Selling pressure after entry",
                    "VWAP acts as resistance (institutions selling)"
                ],
                "bella_fade": [
                    "Negative catalyst weighing on stock",
                    "Stock consolidates near lows for long",
                    "Stock breaks support",
                    "Catalyst more than 8 (too strong)",
                    "Breaking strong technical level"
                ],
                "back_through_open": [
                    "Catalyst not at least 8+",
                    "Market trending opposite direction",
                    "Chop or pause after entry - should work right away",
                    "Range-bound market",
                    "Market fading moves"
                ],
                "9_ema_scalp": [
                    "No strong catalyst or setup",
                    "Choppy opening move",
                    "Too big a move before 9-EMA test (trend near end)"
                ],
                "abc_scalp": [
                    "Trendline not well connected with red bars",
                    "Trendline not smooth with wicks above",
                    "Last candle out of place from trendline"
                ],
                "big_dog_consolidation": [
                    "Consolidation less than 15 minutes",
                    "Volume not declining into breakout",
                    "Price below VWAP/9-EMA/21-EMA during consolidation"
                ],
                "volume_capitulation": [
                    "Capitulation volume less than 2x 2nd highest bar",
                    "Move not overextended",
                    "No tape confirmation on flush"
                ],
                "hod_breakout": [
                    "Catalyst less than 9",
                    "Earlier in day (works best afternoon)",
                    "HOD break doesn't hold - reclaims below"
                ],
                "breaking_news": [
                    "Overreacting without catalyst scoring",
                    "Ignoring market context",
                    "Trading without clear plan",
                    "Emotional decision making"
                ]
            },
            "market_condition_avoidance": {
                "choppy_low_volume": [
                    "Reduce all position sizes 50%",
                    "Avoid momentum/breakout strategies",
                    "Focus on mean reversion only"
                ],
                "high_vix_volatile": [
                    "Wider stops required",
                    "Reduce position sizes",
                    "Faster scaling out"
                ],
                "trending_strongly": [
                    "Avoid fade/mean reversion trades",
                    "Avoid Off Sides in direction of trend",
                    "Focus on pullback entries"
                ]
            }
        }
    
    # ==================== CATALYST SCORING ====================
    
    def _build_catalyst_scoring(self) -> Dict:
        return {
            "scale": {
                "range": "-10 to +10",
                "description": "Score catalyst impact immediately upon news"
            },
            "positive_scores": {
                "+10": {
                    "examples": ["Acquisition announcement", "FDA approval", "Massive earnings beat"],
                    "action": "Strong conviction long",
                    "stop_adjustment": "Tighter - high conviction"
                },
                "+8 to +9": {
                    "examples": ["Major earnings beat", "Significant upgrade", "New contract win"],
                    "action": "High conviction long"
                },
                "+6 to +7": {
                    "examples": ["Solid beat", "Positive guidance", "Sector tailwind"],
                    "action": "Standard long setup"
                },
                "+3 to +5": {
                    "examples": ["Minor positive news", "In-line results", "Mild upgrade"],
                    "action": "Wait for technical setup"
                }
            },
            "neutral_scores": {
                "-2 to +2": {
                    "examples": ["Mixed news", "No clear impact", "Already priced in"],
                    "action": "No catalyst-based trade",
                    "focus": "Technical setups only"
                }
            },
            "negative_scores": {
                "-3 to -5": {
                    "examples": ["Minor miss", "Lowered guidance", "Mild downgrade"],
                    "action": "Wait for technical short setup"
                },
                "-6 to -7": {
                    "examples": ["Significant miss", "Major downgrade", "Contract loss"],
                    "action": "Standard short setup"
                },
                "-8 to -9": {
                    "examples": ["Major earnings miss", "Severe guidance cut", "Regulatory issue"],
                    "action": "High conviction short"
                },
                "-10": {
                    "examples": ["Fraud revealed", "Bankruptcy", "Delisting", "Major scandal"],
                    "action": "Strong conviction short",
                    "stop_adjustment": "Tighter - high conviction"
                }
            },
            "scoring_tips": [
                "Score immediately - first instinct often correct",
                "Consider market's current expectations",
                "Check if news is genuinely surprising",
                "Low institutional participation = muted reaction",
                "Keep emotions in check - score objectively"
            ]
        }
    
    # ==================== GAME PLAN FRAMEWORK ====================
    
    def get_game_plan_framework(self) -> Dict:
        return {
            "daily_routine": {
                "pre_market": [
                    "Review overnight futures and gaps",
                    "Identify In Play stocks via scanner",
                    "Score any catalyst from -10 to +10",
                    "Mark key levels on charts",
                    "Assess market context regime"
                ],
                "game_plan_creation": [
                    "Select 3-5 high conviction setups maximum",
                    "Create IF/THEN statements for each:",
                    "  - IF [condition], THEN [entry]",
                    "  - IF [target hit], THEN [exit partial]",
                    "  - IF [stop hit], THEN [full exit]",
                    "Define specific risk per trade"
                ],
                "during_session": [
                    "Execute game plan - no improvising",
                    "Set alerts at key levels",
                    "Monitor market context for changes",
                    "Adapt plan if regime shifts",
                    "Review what's working TODAY"
                ],
                "post_market": [
                    "Review all trades vs plan",
                    "Note what setups worked",
                    "Identify mistakes/improvements",
                    "Update playbook knowledge"
                ]
            },
            "if_then_template": {
                "entry": "IF [price action + volume + context], THEN enter [direction] with [size]",
                "stop": "IF price hits [level], THEN exit full position",
                "target_1": "IF price reaches [1R], THEN exit 1/3 position",
                "target_2": "IF price reaches [2R], THEN exit 1/3 position", 
                "runner": "IF price continues, THEN trail with [9-EMA/bar low]"
            },
            "common_mistakes": [
                "Setting monetary profit goals",
                "Overcomplicating IF/THEN statements",
                "Not being specific enough",
                "Ignoring market context",
                "Not adapting to conditions",
                "Overtrading outside plan"
            ]
        }
    
    # ==================== STRATEGY SELECTOR ====================
    
    def get_recommended_strategies(self, market_regime: str, time_of_day: str, 
                                    rvol: float = 1.0, has_catalyst: bool = False) -> List[Dict]:
        """
        Returns recommended strategies based on current conditions
        """
        recommendations = []
        
        regime_prefs = self.market_context_rules["regime_identification"].get(market_regime, {})
        preferred = regime_prefs.get("preferred_strategies", [])
        avoid = regime_prefs.get("avoid", [])
        
        time_prefs = self.time_rules["optimal_windows"].get(time_of_day, {})
        time_strategies = time_prefs.get("strategies", [])
        
        # Score each strategy based on conditions
        strategy_scores = {
            "Spencer Scalp": 0,
            "HitchHiker": 0,
            "Gap Give and Go": 0,
            "ORB": 0,
            "Trend Momentum": 0,
            "Back$ide": 0,
            "Off Sides": 0,
            "Rubber Band": 0,
            "Second Chance": 0,
            "Tidal Wave": 0,
            "Mean Reversion": 0,
            "Breaking News": 0,
            "Fashionably Late": 0,
            "Range Break": 0,
            "First VWAP Pullback": 0,
            "First Move Up": 0,
            "First Move Down": 0,
            "Bella Fade": 0,
            "Back-Through Open": 0,
            "9 EMA Scalp": 0,
            "ABC Scalp": 0,
            "Up Through Open": 0,
            "Gap Pick and Roll": 0,
            "Big Dog Consolidation": 0,
            "Volume Capitulation": 0,
            "HOD Breakout": 0,
            "Opening Drive": 0
        }
        
        # Add points for regime preference
        for strat in preferred:
            if strat in strategy_scores:
                strategy_scores[strat] += 3
        
        # Add points for time preference
        for strat in time_strategies:
            if strat in strategy_scores:
                strategy_scores[strat] += 2
        
        # Subtract points for avoidance
        for strat in avoid:
            if strat in strategy_scores:
                strategy_scores[strat] -= 5
        
        # Volume bonus
        if rvol >= 3.0:
            for strat in ["Spencer Scalp", "HitchHiker", "Gap Give and Go", "ORB", "First VWAP Pullback", "Back-Through Open"]:
                strategy_scores[strat] += 2
        if rvol >= 5.0:
            strategy_scores["Rubber Band"] += 3
        
        # Catalyst bonus
        if has_catalyst:
            strategy_scores["Breaking News"] += 4
            strategy_scores["Gap Give and Go"] += 2
            strategy_scores["Back-Through Open"] += 3
            strategy_scores["First VWAP Pullback"] += 2
        
        # Opening auction bonus for early times
        if time_of_day in ["opening_auction", "opening_drive"]:
            for strat in ["First VWAP Pullback", "First Move Up", "First Move Down", "Bella Fade", "Back-Through Open", "Up Through Open", "Opening Drive"]:
                strategy_scores[strat] += 3
        
        # Afternoon bonus
        if time_of_day in ["afternoon", "close"]:
            strategy_scores["HOD Breakout"] += 3
        
        # Consolidation strategies for mid-session
        if time_of_day in ["morning_session", "late_morning"]:
            for strat in ["Big Dog Consolidation", "Spencer Scalp", "ABC Scalp", "9 EMA Scalp"]:
                strategy_scores[strat] += 2
        
        # Sort and return top recommendations
        sorted_strategies = sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True)
        
        for strat, score in sorted_strategies[:5]:
            if score > 0:
                recommendations.append({
                    "strategy": strat,
                    "score": score,
                    "regime_match": strat in preferred,
                    "time_match": strat in time_strategies,
                    "avoid": strat in avoid
                })
        
        return recommendations
    
    # ==================== VALIDATION ====================
    
    def validate_setup(self, strategy_id: str, conditions: Dict) -> Dict:
        """
        Validates if current conditions meet strategy requirements
        """
        validation = {
            "valid": True,
            "warnings": [],
            "blockers": [],
            "score": 100
        }
        
        # Check RVOL
        rvol = conditions.get("rvol", 1.0)
        if rvol < self.volume_rules["rvol_thresholds"]["minimum_in_play"]:
            validation["warnings"].append(f"RVOL {rvol} below minimum 1.5x")
            validation["score"] -= 20
        
        # Check market alignment
        if conditions.get("against_market_trend"):
            validation["blockers"].append("Trading against market trend")
            validation["valid"] = False
            validation["score"] -= 50
        
        # Check time of day
        current_time = conditions.get("time_of_day", "")
        strategy_time_rules = self.time_rules.get("strategy_time_restrictions", {}).get(strategy_id, {})
        
        if strategy_time_rules:
            if strategy_time_rules.get("avoid_after_3pm") and current_time == "close":
                validation["warnings"].append("Strategy not recommended after 3 PM")
                validation["score"] -= 30
        
        # Check avoidance rules
        strategy_avoidance = self.avoidance_rules.get("strategy_specific", {}).get(
            strategy_id.lower().replace(" ", "_"), []
        )
        
        for avoid_condition in strategy_avoidance:
            if conditions.get(avoid_condition.lower().replace(" ", "_")):
                validation["blockers"].append(f"Avoidance condition: {avoid_condition}")
                validation["valid"] = False
                validation["score"] -= 25
        
        return validation


# ==================== SINGLETON ====================
_trading_rules_engine: Optional[TradingRulesEngine] = None

def get_trading_rules_engine() -> TradingRulesEngine:
    global _trading_rules_engine
    if _trading_rules_engine is None:
        _trading_rules_engine = TradingRulesEngine()
    return _trading_rules_engine
