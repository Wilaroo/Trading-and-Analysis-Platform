"""
Advanced Support & Resistance Calculation Service
Combines multiple methodologies for comprehensive level identification:

1. PIVOT POINTS:
   - Classic (Floor Trader) Pivots
   - Fibonacci Pivots
   - Camarilla Pivots
   - Woodie Pivots
   - DeMark Pivots

2. HISTORICAL PRICE REACTION ZONES:
   - Swing high/low clustering
   - Price rejection areas
   - Multi-touch support/resistance
   - Breakout/breakdown levels

3. VOLUME PROFILE:
   - Point of Control (POC) - highest volume price
   - Value Area High (VAH) / Value Area Low (VAL)
   - High Volume Nodes (HVN)
   - Low Volume Nodes (LVN) - potential breakout zones

4. TECHNICAL LEVELS:
   - Moving averages (20, 50, 100, 200 SMA/EMA)
   - VWAP and anchored VWAPs
   - Previous day/week/month high/low/close
   - Round numbers and psychological levels
   - Gap levels (unfilled gaps)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import logging
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class LevelType(str, Enum):
    # Pivot Points
    PIVOT_CLASSIC = "Classic Pivot"
    PIVOT_FIBONACCI = "Fibonacci Pivot"
    PIVOT_CAMARILLA = "Camarilla Pivot"
    PIVOT_WOODIE = "Woodie Pivot"
    PIVOT_DEMARK = "DeMark Pivot"
    
    # Historical
    SWING_HIGH = "Swing High"
    SWING_LOW = "Swing Low"
    REACTION_ZONE = "Reaction Zone"
    MULTI_TOUCH = "Multi-Touch Level"
    
    # Volume Profile
    POC = "Point of Control"
    VAH = "Value Area High"
    VAL = "Value Area Low"
    HVN = "High Volume Node"
    LVN = "Low Volume Node"
    
    # Technical
    SMA_20 = "20 SMA"
    SMA_50 = "50 SMA"
    SMA_100 = "100 SMA"
    SMA_200 = "200 SMA"
    EMA_9 = "9 EMA"
    EMA_21 = "21 EMA"
    VWAP = "VWAP"
    
    # Reference Levels
    PREV_HIGH = "Previous High"
    PREV_LOW = "Previous Low"
    PREV_CLOSE = "Previous Close"
    WEEK_HIGH = "Week High"
    WEEK_LOW = "Week Low"
    MONTH_HIGH = "Month High"
    MONTH_LOW = "Month Low"
    HOD = "High of Day"
    LOD = "Low of Day"
    
    # Other
    ROUND_NUMBER = "Round Number"
    GAP_LEVEL = "Gap Level"
    ATH = "All-Time High"
    ATL = "All-Time Low"
    FIFTY_TWO_HIGH = "52-Week High"
    FIFTY_TWO_LOW = "52-Week Low"


@dataclass
class SRLevel:
    """Represents a single support/resistance level"""
    price: float
    level_type: LevelType
    strength: int  # 1-10 scale
    touches: int = 0  # Number of times price has tested this level
    is_support: bool = True
    is_resistance: bool = True
    volume_at_level: float = 0.0
    last_tested: Optional[datetime] = None
    notes: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "price": float(round(self.price, 2)),
            "type": self.level_type.value,
            "strength": int(self.strength),
            "touches": int(self.touches),
            "is_support": bool(self.is_support),
            "is_resistance": bool(self.is_resistance),
            "volume_at_level": float(round(self.volume_at_level, 0)),
            "last_tested": self.last_tested.isoformat() if self.last_tested else None,
            "notes": str(self.notes)
        }


@dataclass
class SRAnalysis:
    """Complete S/R analysis for a symbol"""
    symbol: str
    current_price: float
    timestamp: datetime
    
    # Categorized levels
    support_levels: List[SRLevel] = field(default_factory=list)
    resistance_levels: List[SRLevel] = field(default_factory=list)
    
    # Key levels
    nearest_support: Optional[SRLevel] = None
    nearest_resistance: Optional[SRLevel] = None
    strongest_support: Optional[SRLevel] = None
    strongest_resistance: Optional[SRLevel] = None
    
    # Volume profile
    poc: Optional[float] = None
    value_area_high: Optional[float] = None
    value_area_low: Optional[float] = None
    
    # Pivot points
    pivot_point: Optional[float] = None
    
    # Analysis metadata
    in_value_area: bool = False
    near_key_level: bool = False
    level_confluence: List[Dict] = field(default_factory=list)


class SupportResistanceService:
    """
    Advanced S/R calculation combining multiple methodologies
    """
    
    def __init__(self, alpaca_service=None, ib_service=None):
        self._alpaca = alpaca_service
        self._ib = ib_service
        self._cache: Dict[str, Tuple[SRAnalysis, datetime]] = {}
        self._cache_ttl = 300  # 5 minutes
        
        # Configuration
        self.swing_lookback = 20  # Bars to look back for swing highs/lows
        self.min_touches = 2  # Minimum touches to consider a reaction zone
        self.price_tolerance = 0.002  # 0.2% tolerance for level clustering
        self.volume_profile_bins = 50  # Number of price bins for volume profile
        
    async def get_sr_analysis(
        self,
        symbol: str,
        bars: List[Dict],
        current_price: float,
        include_pivots: bool = True,
        include_volume_profile: bool = True,
        include_reaction_zones: bool = True
    ) -> SRAnalysis:
        """
        Get comprehensive S/R analysis for a symbol
        
        Args:
            symbol: Stock symbol
            bars: List of OHLCV bars (daily recommended, at least 60 bars)
            current_price: Current stock price
            include_pivots: Calculate pivot points
            include_volume_profile: Calculate volume profile levels
            include_reaction_zones: Find historical reaction zones
        """
        # Check cache
        cache_key = f"{symbol}_{current_price:.2f}"
        if cache_key in self._cache:
            cached, cached_time = self._cache[cache_key]
            if (datetime.now(timezone.utc) - cached_time).total_seconds() < self._cache_ttl:
                return cached
        
        all_levels: List[SRLevel] = []
        
        if not bars or len(bars) < 5:
            return SRAnalysis(
                symbol=symbol,
                current_price=current_price,
                timestamp=datetime.now(timezone.utc)
            )
        
        # Extract price data
        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]
        closes = [bar["close"] for bar in bars]
        volumes = [bar.get("volume", 0) for bar in bars]
        
        # Get previous day data (most recent complete bar)
        prev_high = bars[-2]["high"] if len(bars) > 1 else bars[-1]["high"]
        prev_low = bars[-2]["low"] if len(bars) > 1 else bars[-1]["low"]
        prev_close = bars[-2]["close"] if len(bars) > 1 else bars[-1]["close"]
        
        # Today's data
        today_high = bars[-1]["high"]
        today_low = bars[-1]["low"]
        
        # === 1. PIVOT POINTS ===
        pivot_data = {}
        if include_pivots:
            pivot_levels, pivot_data = self._calculate_all_pivots(prev_high, prev_low, prev_close, bars[-1]["open"])
            all_levels.extend(pivot_levels)
        
        # === 2. HISTORICAL REACTION ZONES ===
        if include_reaction_zones and len(bars) >= 20:
            reaction_levels = self._find_reaction_zones(bars)
            all_levels.extend(reaction_levels)
            
            # Add swing highs/lows
            swing_levels = self._find_swing_points(bars)
            all_levels.extend(swing_levels)
        
        # === 3. VOLUME PROFILE ===
        volume_data = {}
        if include_volume_profile and len(bars) >= 20:
            volume_levels, volume_data = self._calculate_volume_profile(bars)
            all_levels.extend(volume_levels)
        
        # === 4. TECHNICAL LEVELS ===
        technical_levels = self._calculate_technical_levels(bars, current_price)
        all_levels.extend(technical_levels)
        
        # === 5. REFERENCE LEVELS ===
        reference_levels = self._get_reference_levels(bars, today_high, today_low, prev_high, prev_low, prev_close)
        all_levels.extend(reference_levels)
        
        # === 6. ROUND NUMBERS ===
        round_levels = self._get_round_number_levels(current_price)
        all_levels.extend(round_levels)
        
        # === 7. GAP LEVELS ===
        gap_levels = self._find_gap_levels(bars)
        all_levels.extend(gap_levels)
        
        # === CONSOLIDATE & CLUSTER LEVELS ===
        consolidated_levels = self._consolidate_levels(all_levels, current_price)
        
        # Separate into support and resistance
        support_levels = sorted(
            [lvl for lvl in consolidated_levels if lvl.price < current_price],
            key=lambda x: x.price,
            reverse=True
        )
        
        resistance_levels = sorted(
            [lvl for lvl in consolidated_levels if lvl.price > current_price],
            key=lambda x: x.price
        )
        
        # Find key levels
        nearest_support = support_levels[0] if support_levels else None
        nearest_resistance = resistance_levels[0] if resistance_levels else None
        strongest_support = max(support_levels, key=lambda x: x.strength) if support_levels else None
        strongest_resistance = max(resistance_levels, key=lambda x: x.strength) if resistance_levels else None
        
        # Find confluence zones (multiple levels clustered together)
        confluence_zones = self._find_confluence_zones(consolidated_levels, current_price)
        
        # Check if in value area
        in_value_area = False
        if volume_data.get("vah") and volume_data.get("val"):
            in_value_area = volume_data["val"] <= current_price <= volume_data["vah"]
        
        # Check if near key level
        near_key_level = False
        price_range = current_price * 0.005  # 0.5% range
        for level in consolidated_levels:
            if abs(level.price - current_price) <= price_range and level.strength >= 7:
                near_key_level = True
                break
        
        analysis = SRAnalysis(
            symbol=symbol,
            current_price=current_price,
            timestamp=datetime.now(timezone.utc),
            support_levels=support_levels[:10],  # Top 10 supports
            resistance_levels=resistance_levels[:10],  # Top 10 resistances
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            strongest_support=strongest_support,
            strongest_resistance=strongest_resistance,
            poc=volume_data.get("poc"),
            value_area_high=volume_data.get("vah"),
            value_area_low=volume_data.get("val"),
            pivot_point=pivot_data.get("pp"),
            in_value_area=in_value_area,
            near_key_level=near_key_level,
            level_confluence=confluence_zones
        )
        
        # Cache result
        self._cache[cache_key] = (analysis, datetime.now(timezone.utc))
        
        return analysis
    
    def _calculate_all_pivots(
        self,
        high: float,
        low: float,
        close: float,
        open_price: float
    ) -> Tuple[List[SRLevel], Dict]:
        """Calculate pivot points using multiple methodologies"""
        levels = []
        pivot_data = {}
        
        # === CLASSIC (FLOOR TRADER) PIVOTS ===
        pp = (high + low + close) / 3
        pivot_data["pp"] = pp
        
        # Classic resistance levels
        r1_classic = (2 * pp) - low
        r2_classic = pp + (high - low)
        r3_classic = high + 2 * (pp - low)
        
        # Classic support levels
        s1_classic = (2 * pp) - high
        s2_classic = pp - (high - low)
        s3_classic = low - 2 * (high - pp)
        
        levels.extend([
            SRLevel(pp, LevelType.PIVOT_CLASSIC, strength=8, notes="Central Pivot"),
            SRLevel(r1_classic, LevelType.PIVOT_CLASSIC, strength=6, notes="R1"),
            SRLevel(r2_classic, LevelType.PIVOT_CLASSIC, strength=5, notes="R2"),
            SRLevel(r3_classic, LevelType.PIVOT_CLASSIC, strength=4, notes="R3"),
            SRLevel(s1_classic, LevelType.PIVOT_CLASSIC, strength=6, notes="S1"),
            SRLevel(s2_classic, LevelType.PIVOT_CLASSIC, strength=5, notes="S2"),
            SRLevel(s3_classic, LevelType.PIVOT_CLASSIC, strength=4, notes="S3"),
        ])
        
        # === FIBONACCI PIVOTS ===
        range_hl = high - low
        
        r1_fib = pp + (0.382 * range_hl)
        r2_fib = pp + (0.618 * range_hl)
        r3_fib = pp + (1.000 * range_hl)
        
        s1_fib = pp - (0.382 * range_hl)
        s2_fib = pp - (0.618 * range_hl)
        s3_fib = pp - (1.000 * range_hl)
        
        levels.extend([
            SRLevel(r1_fib, LevelType.PIVOT_FIBONACCI, strength=6, notes="Fib R1 (38.2%)"),
            SRLevel(r2_fib, LevelType.PIVOT_FIBONACCI, strength=7, notes="Fib R2 (61.8%)"),
            SRLevel(r3_fib, LevelType.PIVOT_FIBONACCI, strength=5, notes="Fib R3 (100%)"),
            SRLevel(s1_fib, LevelType.PIVOT_FIBONACCI, strength=6, notes="Fib S1 (38.2%)"),
            SRLevel(s2_fib, LevelType.PIVOT_FIBONACCI, strength=7, notes="Fib S2 (61.8%)"),
            SRLevel(s3_fib, LevelType.PIVOT_FIBONACCI, strength=5, notes="Fib S3 (100%)"),
        ])
        
        # === CAMARILLA PIVOTS ===
        # Camarilla uses a different formula focusing on intraday trading
        r4_cam = close + (range_hl * 1.1 / 2)
        r3_cam = close + (range_hl * 1.1 / 4)
        r2_cam = close + (range_hl * 1.1 / 6)
        r1_cam = close + (range_hl * 1.1 / 12)
        
        s1_cam = close - (range_hl * 1.1 / 12)
        s2_cam = close - (range_hl * 1.1 / 6)
        s3_cam = close - (range_hl * 1.1 / 4)
        s4_cam = close - (range_hl * 1.1 / 2)
        
        # Camarilla R3/S3 are the key breakout levels, R4/S4 are extreme
        levels.extend([
            SRLevel(r3_cam, LevelType.PIVOT_CAMARILLA, strength=8, notes="Cam R3 (Breakout)"),
            SRLevel(r4_cam, LevelType.PIVOT_CAMARILLA, strength=6, notes="Cam R4 (Extreme)"),
            SRLevel(s3_cam, LevelType.PIVOT_CAMARILLA, strength=8, notes="Cam S3 (Breakdown)"),
            SRLevel(s4_cam, LevelType.PIVOT_CAMARILLA, strength=6, notes="Cam S4 (Extreme)"),
            SRLevel(r1_cam, LevelType.PIVOT_CAMARILLA, strength=4, notes="Cam R1"),
            SRLevel(r2_cam, LevelType.PIVOT_CAMARILLA, strength=5, notes="Cam R2"),
            SRLevel(s1_cam, LevelType.PIVOT_CAMARILLA, strength=4, notes="Cam S1"),
            SRLevel(s2_cam, LevelType.PIVOT_CAMARILLA, strength=5, notes="Cam S2"),
        ])
        
        # === WOODIE PIVOTS ===
        # Woodie gives more weight to the opening price
        pp_woodie = (high + low + (2 * open_price)) / 4
        
        r1_woodie = (2 * pp_woodie) - low
        r2_woodie = pp_woodie + (high - low)
        s1_woodie = (2 * pp_woodie) - high
        s2_woodie = pp_woodie - (high - low)
        
        levels.extend([
            SRLevel(pp_woodie, LevelType.PIVOT_WOODIE, strength=7, notes="Woodie PP"),
            SRLevel(r1_woodie, LevelType.PIVOT_WOODIE, strength=5, notes="Woodie R1"),
            SRLevel(r2_woodie, LevelType.PIVOT_WOODIE, strength=4, notes="Woodie R2"),
            SRLevel(s1_woodie, LevelType.PIVOT_WOODIE, strength=5, notes="Woodie S1"),
            SRLevel(s2_woodie, LevelType.PIVOT_WOODIE, strength=4, notes="Woodie S2"),
        ])
        
        # === DEMARK PIVOTS ===
        # DeMark pivots depend on the relationship between open and close
        if close < open_price:
            x = high + (2 * low) + close
        elif close > open_price:
            x = (2 * high) + low + close
        else:
            x = high + low + (2 * close)
        
        pp_demark = x / 4
        r1_demark = x / 2 - low
        s1_demark = x / 2 - high
        
        levels.extend([
            SRLevel(pp_demark, LevelType.PIVOT_DEMARK, strength=6, notes="DeMark PP"),
            SRLevel(r1_demark, LevelType.PIVOT_DEMARK, strength=5, notes="DeMark R1"),
            SRLevel(s1_demark, LevelType.PIVOT_DEMARK, strength=5, notes="DeMark S1"),
        ])
        
        return levels, pivot_data
    
    def _find_reaction_zones(self, bars: List[Dict]) -> List[SRLevel]:
        """Find historical price reaction zones where price reversed multiple times"""
        levels = []
        
        if len(bars) < 20:
            return levels
        
        # Collect all reversal points
        reversal_highs = []
        reversal_lows = []
        
        for i in range(2, len(bars) - 2):
            # Swing high: higher than 2 bars on each side
            if (bars[i]["high"] > bars[i-1]["high"] and 
                bars[i]["high"] > bars[i-2]["high"] and
                bars[i]["high"] > bars[i+1]["high"] and 
                bars[i]["high"] > bars[i+2]["high"]):
                reversal_highs.append({
                    "price": bars[i]["high"],
                    "index": i,
                    "volume": bars[i].get("volume", 0)
                })
            
            # Swing low: lower than 2 bars on each side
            if (bars[i]["low"] < bars[i-1]["low"] and 
                bars[i]["low"] < bars[i-2]["low"] and
                bars[i]["low"] < bars[i+1]["low"] and 
                bars[i]["low"] < bars[i+2]["low"]):
                reversal_lows.append({
                    "price": bars[i]["low"],
                    "index": i,
                    "volume": bars[i].get("volume", 0)
                })
        
        # Cluster reversal highs to find multi-touch resistance zones
        high_clusters = self._cluster_prices([r["price"] for r in reversal_highs])
        for cluster_price, count in high_clusters.items():
            if count >= self.min_touches:
                # Calculate average volume at this level
                cluster_volume = sum(
                    r["volume"] for r in reversal_highs 
                    if abs(r["price"] - cluster_price) / cluster_price < self.price_tolerance
                )
                
                strength = min(10, 5 + count)  # More touches = stronger level
                levels.append(SRLevel(
                    price=cluster_price,
                    level_type=LevelType.MULTI_TOUCH,
                    strength=strength,
                    touches=count,
                    is_support=False,
                    is_resistance=True,
                    volume_at_level=cluster_volume,
                    notes=f"Resistance tested {count}x"
                ))
        
        # Cluster reversal lows to find multi-touch support zones
        low_clusters = self._cluster_prices([r["price"] for r in reversal_lows])
        for cluster_price, count in low_clusters.items():
            if count >= self.min_touches:
                cluster_volume = sum(
                    r["volume"] for r in reversal_lows 
                    if abs(r["price"] - cluster_price) / cluster_price < self.price_tolerance
                )
                
                strength = min(10, 5 + count)
                levels.append(SRLevel(
                    price=cluster_price,
                    level_type=LevelType.MULTI_TOUCH,
                    strength=strength,
                    touches=count,
                    is_support=True,
                    is_resistance=False,
                    volume_at_level=cluster_volume,
                    notes=f"Support tested {count}x"
                ))
        
        return levels
    
    def _cluster_prices(self, prices: List[float]) -> Dict[float, int]:
        """Cluster similar prices together and count occurrences"""
        if not prices:
            return {}
        
        clusters = defaultdict(int)
        used = set()
        
        for i, price in enumerate(prices):
            if i in used:
                continue
            
            # Find all prices within tolerance
            cluster_prices = [price]
            for j, other_price in enumerate(prices):
                if j != i and j not in used:
                    if abs(price - other_price) / price < self.price_tolerance:
                        cluster_prices.append(other_price)
                        used.add(j)
            
            # Use average as cluster center
            cluster_center = sum(cluster_prices) / len(cluster_prices)
            clusters[cluster_center] = len(cluster_prices)
            used.add(i)
        
        return dict(clusters)
    
    def _find_swing_points(self, bars: List[Dict]) -> List[SRLevel]:
        """Find significant swing highs and lows"""
        levels = []
        
        if len(bars) < 10:
            return levels
        
        # Find the most significant swing high and low in different timeframes
        periods = [5, 10, 20]  # Short, medium, long-term swings
        
        for period in periods:
            if len(bars) < period + 2:
                continue
            
            # Recent swing high
            recent_bars = bars[-period:]
            swing_high = max(bar["high"] for bar in recent_bars)
            swing_low = min(bar["low"] for bar in recent_bars)
            
            strength = 4 + (period // 5)  # Longer period = stronger level
            
            # Find which bar had the swing high/low for volume info
            high_bar = next((b for b in recent_bars if b["high"] == swing_high), recent_bars[-1])
            low_bar = next((b for b in recent_bars if b["low"] == swing_low), recent_bars[-1])
            
            levels.append(SRLevel(
                price=swing_high,
                level_type=LevelType.SWING_HIGH,
                strength=strength,
                is_support=False,
                is_resistance=True,
                volume_at_level=high_bar.get("volume", 0),
                notes=f"{period}-bar swing high"
            ))
            
            levels.append(SRLevel(
                price=swing_low,
                level_type=LevelType.SWING_LOW,
                strength=strength,
                is_support=True,
                is_resistance=False,
                volume_at_level=low_bar.get("volume", 0),
                notes=f"{period}-bar swing low"
            ))
        
        return levels
    
    def _calculate_volume_profile(self, bars: List[Dict]) -> Tuple[List[SRLevel], Dict]:
        """
        Calculate volume profile to find:
        - POC (Point of Control): Price with highest volume
        - VAH (Value Area High): Upper bound of 70% volume
        - VAL (Value Area Low): Lower bound of 70% volume
        - HVN (High Volume Nodes): Clusters of high volume
        - LVN (Low Volume Nodes): Price ranges with low volume
        """
        levels = []
        volume_data = {}
        
        if len(bars) < 10:
            return levels, volume_data
        
        # Determine price range
        all_highs = [bar["high"] for bar in bars]
        all_lows = [bar["low"] for bar in bars]
        price_high = max(all_highs)
        price_low = min(all_lows)
        price_range = price_high - price_low
        
        if price_range <= 0:
            return levels, volume_data
        
        # Create price bins
        bin_size = price_range / self.volume_profile_bins
        volume_at_price = defaultdict(float)
        
        # Distribute volume across price levels (simple TPO approach)
        for bar in bars:
            bar_volume = bar.get("volume", 0)
            bar_range = bar["high"] - bar["low"]
            
            if bar_range <= 0:
                # If no range, put all volume at close
                price_bin = int((bar["close"] - price_low) / bin_size)
                volume_at_price[price_bin] += bar_volume
            else:
                # Distribute volume proportionally across the bar's range
                bins_in_bar = max(1, int(bar_range / bin_size))
                volume_per_bin = bar_volume / bins_in_bar
                
                start_bin = int((bar["low"] - price_low) / bin_size)
                end_bin = int((bar["high"] - price_low) / bin_size)
                
                for b in range(start_bin, min(end_bin + 1, self.volume_profile_bins)):
                    volume_at_price[b] += volume_per_bin
        
        if not volume_at_price:
            return levels, volume_data
        
        # Find POC (Point of Control)
        poc_bin = max(volume_at_price.keys(), key=lambda x: volume_at_price[x])
        poc_price = price_low + (poc_bin + 0.5) * bin_size
        volume_data["poc"] = poc_price
        
        levels.append(SRLevel(
            price=poc_price,
            level_type=LevelType.POC,
            strength=9,  # POC is very significant
            volume_at_level=volume_at_price[poc_bin],
            notes="Point of Control - Highest volume price"
        ))
        
        # Calculate Value Area (70% of volume)
        total_volume = sum(volume_at_price.values())
        target_volume = total_volume * 0.70
        
        # Start from POC and expand outward
        va_bins = {poc_bin}
        current_volume = volume_at_price[poc_bin]
        
        lower_bound = poc_bin - 1
        upper_bound = poc_bin + 1
        
        while current_volume < target_volume and (lower_bound >= 0 or upper_bound < self.volume_profile_bins):
            lower_vol = volume_at_price.get(lower_bound, 0) if lower_bound >= 0 else 0
            upper_vol = volume_at_price.get(upper_bound, 0) if upper_bound < self.volume_profile_bins else 0
            
            if lower_vol >= upper_vol and lower_bound >= 0:
                va_bins.add(lower_bound)
                current_volume += lower_vol
                lower_bound -= 1
            elif upper_bound < self.volume_profile_bins:
                va_bins.add(upper_bound)
                current_volume += upper_vol
                upper_bound += 1
            else:
                break
        
        # Calculate VAH and VAL
        if va_bins:
            vah_bin = max(va_bins)
            val_bin = min(va_bins)
            vah_price = price_low + (vah_bin + 1) * bin_size
            val_price = price_low + val_bin * bin_size
            
            volume_data["vah"] = vah_price
            volume_data["val"] = val_price
            
            levels.append(SRLevel(
                price=vah_price,
                level_type=LevelType.VAH,
                strength=7,
                notes="Value Area High - 70% volume upper bound"
            ))
            
            levels.append(SRLevel(
                price=val_price,
                level_type=LevelType.VAL,
                strength=7,
                notes="Value Area Low - 70% volume lower bound"
            ))
        
        # Find High Volume Nodes (HVN) - excluding POC
        avg_volume = total_volume / len(volume_at_price)
        hvn_threshold = avg_volume * 1.5
        
        for bin_idx, vol in volume_at_price.items():
            if bin_idx != poc_bin and vol >= hvn_threshold:
                hvn_price = price_low + (bin_idx + 0.5) * bin_size
                levels.append(SRLevel(
                    price=hvn_price,
                    level_type=LevelType.HVN,
                    strength=6,
                    volume_at_level=vol,
                    notes="High Volume Node"
                ))
        
        # Find Low Volume Nodes (LVN) - potential breakout zones
        lvn_threshold = avg_volume * 0.3
        for bin_idx, vol in volume_at_price.items():
            if vol <= lvn_threshold and vol > 0:
                lvn_price = price_low + (bin_idx + 0.5) * bin_size
                levels.append(SRLevel(
                    price=lvn_price,
                    level_type=LevelType.LVN,
                    strength=3,
                    volume_at_level=vol,
                    notes="Low Volume Node - potential fast move zone"
                ))
        
        return levels, volume_data
    
    def _calculate_technical_levels(self, bars: List[Dict], current_price: float) -> List[SRLevel]:
        """Calculate moving average and VWAP levels"""
        levels = []
        
        closes = [bar["close"] for bar in bars]
        
        # Simple Moving Averages
        ma_periods = [(20, LevelType.SMA_20, 6), (50, LevelType.SMA_50, 7), 
                      (100, LevelType.SMA_100, 5), (200, LevelType.SMA_200, 8)]
        
        for period, level_type, strength in ma_periods:
            if len(closes) >= period:
                sma = sum(closes[-period:]) / period
                levels.append(SRLevel(
                    price=sma,
                    level_type=level_type,
                    strength=strength,
                    notes=f"{period}-day SMA"
                ))
        
        # Exponential Moving Averages
        ema_periods = [(9, LevelType.EMA_9, 5), (21, LevelType.EMA_21, 6)]
        
        for period, level_type, strength in ema_periods:
            if len(closes) >= period:
                ema = self._calculate_ema(closes, period)
                if ema:
                    levels.append(SRLevel(
                        price=ema,
                        level_type=level_type,
                        strength=strength,
                        notes=f"{period}-day EMA"
                    ))
        
        # VWAP (for intraday - use typical price * volume approach)
        if len(bars) >= 1:
            vwap = self._calculate_vwap(bars[-20:])  # 20-day anchored VWAP
            if vwap:
                levels.append(SRLevel(
                    price=vwap,
                    level_type=LevelType.VWAP,
                    strength=8,
                    notes="20-day Anchored VWAP"
                ))
        
        return levels
    
    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_vwap(self, bars: List[Dict]) -> Optional[float]:
        """Calculate Volume Weighted Average Price"""
        if not bars:
            return None
        
        total_vp = 0
        total_volume = 0
        
        for bar in bars:
            typical_price = (bar["high"] + bar["low"] + bar["close"]) / 3
            volume = bar.get("volume", 0)
            total_vp += typical_price * volume
            total_volume += volume
        
        return total_vp / total_volume if total_volume > 0 else None
    
    def _get_reference_levels(
        self,
        bars: List[Dict],
        today_high: float,
        today_low: float,
        prev_high: float,
        prev_low: float,
        prev_close: float
    ) -> List[SRLevel]:
        """Get reference price levels"""
        levels = []
        
        # Today's levels
        levels.append(SRLevel(today_high, LevelType.HOD, strength=6, notes="Today's High"))
        levels.append(SRLevel(today_low, LevelType.LOD, strength=6, notes="Today's Low"))
        
        # Previous day levels
        levels.append(SRLevel(prev_high, LevelType.PREV_HIGH, strength=5, notes="Yesterday's High"))
        levels.append(SRLevel(prev_low, LevelType.PREV_LOW, strength=5, notes="Yesterday's Low"))
        levels.append(SRLevel(prev_close, LevelType.PREV_CLOSE, strength=4, notes="Yesterday's Close"))
        
        # Weekly levels (if we have enough data)
        if len(bars) >= 5:
            week_bars = bars[-5:]
            week_high = max(bar["high"] for bar in week_bars)
            week_low = min(bar["low"] for bar in week_bars)
            levels.append(SRLevel(week_high, LevelType.WEEK_HIGH, strength=6, notes="Week High"))
            levels.append(SRLevel(week_low, LevelType.WEEK_LOW, strength=6, notes="Week Low"))
        
        # Monthly levels
        if len(bars) >= 20:
            month_bars = bars[-20:]
            month_high = max(bar["high"] for bar in month_bars)
            month_low = min(bar["low"] for bar in month_bars)
            levels.append(SRLevel(month_high, LevelType.MONTH_HIGH, strength=7, notes="Month High"))
            levels.append(SRLevel(month_low, LevelType.MONTH_LOW, strength=7, notes="Month Low"))
        
        # 52-week high/low
        if len(bars) >= 252:
            year_bars = bars[-252:]
            year_high = max(bar["high"] for bar in year_bars)
            year_low = min(bar["low"] for bar in year_bars)
            levels.append(SRLevel(year_high, LevelType.FIFTY_TWO_HIGH, strength=9, notes="52-Week High"))
            levels.append(SRLevel(year_low, LevelType.FIFTY_TWO_LOW, strength=9, notes="52-Week Low"))
        
        return levels
    
    def _get_round_number_levels(self, current_price: float) -> List[SRLevel]:
        """Get psychological round number levels"""
        levels = []
        
        # Determine appropriate rounding based on price
        if current_price < 10:
            intervals = [0.5, 1, 2.5]
        elif current_price < 50:
            intervals = [1, 5, 10]
        elif current_price < 200:
            intervals = [5, 10, 25]
        elif current_price < 500:
            intervals = [10, 25, 50]
        else:
            intervals = [25, 50, 100]
        
        for interval in intervals:
            # Round up and down
            round_up = float(np.ceil(current_price / interval) * interval)
            round_down = float(np.floor(current_price / interval) * interval)
            
            # Add a few levels above and below
            for i in range(-2, 3):
                level_up = round_up + (i * interval)
                level_down = round_down + (i * interval)
                
                if level_up > 0 and abs(level_up - current_price) / current_price < 0.10:  # Within 10%
                    strength = 3 if interval == intervals[0] else 4 if interval == intervals[1] else 5
                    levels.append(SRLevel(
                        float(level_up),
                        LevelType.ROUND_NUMBER,
                        strength=strength,
                        notes=f"${level_up:.0f} round number"
                    ))
        
        # Remove duplicates
        seen = set()
        unique_levels = []
        for level in levels:
            if level.price not in seen:
                seen.add(level.price)
                unique_levels.append(level)
        
        return unique_levels
    
    def _find_gap_levels(self, bars: List[Dict]) -> List[SRLevel]:
        """Find unfilled gap levels"""
        levels = []
        
        if len(bars) < 2:
            return levels
        
        for i in range(1, len(bars)):
            prev_bar = bars[i-1]
            curr_bar = bars[i]
            
            # Gap up: current low > previous high
            if curr_bar["low"] > prev_bar["high"]:
                gap_size = curr_bar["low"] - prev_bar["high"]
                gap_pct = gap_size / prev_bar["close"] * 100
                
                if gap_pct >= 0.5:  # Significant gap (>0.5%)
                    # Gap fill level is the top of the gap
                    levels.append(SRLevel(
                        prev_bar["high"],
                        LevelType.GAP_LEVEL,
                        strength=5 if gap_pct < 2 else 6,
                        notes=f"Gap up fill level ({gap_pct:.1f}% gap)"
                    ))
            
            # Gap down: current high < previous low
            if curr_bar["high"] < prev_bar["low"]:
                gap_size = prev_bar["low"] - curr_bar["high"]
                gap_pct = gap_size / prev_bar["close"] * 100
                
                if gap_pct >= 0.5:
                    levels.append(SRLevel(
                        prev_bar["low"],
                        LevelType.GAP_LEVEL,
                        strength=5 if gap_pct < 2 else 6,
                        notes=f"Gap down fill level ({gap_pct:.1f}% gap)"
                    ))
        
        return levels
    
    def _consolidate_levels(self, levels: List[SRLevel], current_price: float) -> List[SRLevel]:
        """Consolidate nearby levels and combine their strength"""
        if not levels:
            return []
        
        # Filter out invalid levels
        valid_levels = [lvl for lvl in levels if lvl.price > 0]
        
        # Sort by price
        sorted_levels = sorted(valid_levels, key=lambda x: x.price)
        
        consolidated = []
        used = set()
        
        for i, level in enumerate(sorted_levels):
            if i in used:
                continue
            
            # Find nearby levels
            nearby = [level]
            for j, other in enumerate(sorted_levels):
                if j != i and j not in used:
                    if abs(level.price - other.price) / level.price < self.price_tolerance:
                        nearby.append(other)
                        used.add(j)
            
            # Consolidate into single level
            if nearby:
                avg_price = sum(n.price for n in nearby) / len(nearby)
                combined_strength = min(10, max(n.strength for n in nearby) + len(nearby) - 1)
                total_touches = sum(n.touches for n in nearby)
                total_volume = sum(n.volume_at_level for n in nearby)
                
                # Combine types
                types = list(set(n.level_type for n in nearby))
                primary_type = max(nearby, key=lambda x: x.strength).level_type
                
                # Create notes describing confluence
                if len(nearby) > 1:
                    notes = f"Confluence zone: {', '.join(t.value for t in types[:3])}"
                else:
                    notes = level.notes
                
                consolidated.append(SRLevel(
                    price=avg_price,
                    level_type=primary_type,
                    strength=combined_strength,
                    touches=total_touches,
                    is_support=avg_price < current_price,
                    is_resistance=avg_price > current_price,
                    volume_at_level=total_volume,
                    notes=notes
                ))
            
            used.add(i)
        
        # Sort by strength (descending)
        return sorted(consolidated, key=lambda x: x.strength, reverse=True)
    
    def _find_confluence_zones(self, levels: List[SRLevel], current_price: float) -> List[Dict]:
        """Find zones where multiple S/R levels cluster together"""
        confluence_zones = []
        
        # Group levels by proximity
        price_groups = defaultdict(list)
        
        for level in levels:
            # Round to create groups
            group_key = round(level.price, -1 if level.price > 100 else 0)
            price_groups[group_key].append(level)
        
        for group_price, group_levels in price_groups.items():
            if len(group_levels) >= 3:  # At least 3 levels for confluence
                avg_price = sum(l.price for l in group_levels) / len(group_levels)
                combined_strength = min(10, sum(l.strength for l in group_levels) / len(group_levels) + len(group_levels))
                
                confluence_zones.append({
                    "price": round(avg_price, 2),
                    "level_count": len(group_levels),
                    "types": list(set(l.level_type.value for l in group_levels)),
                    "strength": round(combined_strength, 1),
                    "is_support": avg_price < current_price,
                    "is_resistance": avg_price > current_price,
                    "distance_pct": round(abs(avg_price - current_price) / current_price * 100, 2)
                })
        
        return sorted(confluence_zones, key=lambda x: x["strength"], reverse=True)[:5]
    
    def get_key_levels_summary(self, analysis: SRAnalysis) -> Dict:
        """Get a concise summary of key S/R levels"""
        return {
            "symbol": analysis.symbol,
            "current_price": analysis.current_price,
            "nearest_support": analysis.nearest_support.to_dict() if analysis.nearest_support else None,
            "nearest_resistance": analysis.nearest_resistance.to_dict() if analysis.nearest_resistance else None,
            "strongest_support": analysis.strongest_support.to_dict() if analysis.strongest_support else None,
            "strongest_resistance": analysis.strongest_resistance.to_dict() if analysis.strongest_resistance else None,
            "volume_profile": {
                "poc": round(analysis.poc, 2) if analysis.poc else None,
                "value_area_high": round(analysis.value_area_high, 2) if analysis.value_area_high else None,
                "value_area_low": round(analysis.value_area_low, 2) if analysis.value_area_low else None,
                "in_value_area": analysis.in_value_area
            },
            "pivot_point": round(analysis.pivot_point, 2) if analysis.pivot_point else None,
            "near_key_level": analysis.near_key_level,
            "confluence_zones": analysis.level_confluence,
            "support_levels": [l.to_dict() for l in analysis.support_levels[:5]],
            "resistance_levels": [l.to_dict() for l in analysis.resistance_levels[:5]]
        }


# Singleton instance
_sr_service: Optional[SupportResistanceService] = None


def get_sr_service(alpaca_service=None, ib_service=None) -> SupportResistanceService:
    """Get or create the S/R service singleton"""
    global _sr_service
    if _sr_service is None:
        _sr_service = SupportResistanceService(alpaca_service, ib_service)
    return _sr_service
