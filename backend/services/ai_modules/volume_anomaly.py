"""
Volume Anomaly Detection Service - Enhanced Volume Analysis

Uses EXISTING data to detect institutional footprints:
- Z-score volume spikes
- Accumulation/Distribution detection  
- Time-of-day patterns
- Price absorption analysis

All FREE - uses data we already have in the system.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import statistics

logger = logging.getLogger(__name__)


@dataclass
class VolumeAnomaly:
    """A detected volume anomaly"""
    symbol: str = ""
    anomaly_type: str = ""  # "spike", "accumulation", "distribution", "absorption"
    
    # Metrics
    zscore: float = 0.0
    current_volume: int = 0
    average_volume: int = 0
    relative_volume: float = 0.0  # RVOL
    
    # Price context
    price_change_pct: float = 0.0
    price_at_detection: float = 0.0
    
    # Interpretation
    signal: str = ""  # "bullish", "bearish", "neutral"
    confidence: float = 0.0
    description: str = ""
    
    # Metadata
    detected_at: str = ""
    bar_time: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass 
class VolumeProfile:
    """Volume profile for a symbol"""
    symbol: str = ""
    
    # Current metrics
    current_volume: int = 0
    average_volume: int = 0
    rvol: float = 1.0
    zscore: float = 0.0
    
    # Trend
    volume_trend: str = "normal"  # "high", "normal", "low"
    
    # Recent anomalies
    recent_anomalies: List[Dict] = field(default_factory=list)
    
    # Institutional signals
    institutional_signal: str = "none"  # "accumulation", "distribution", "none"
    signal_confidence: float = 0.0
    
    # Analysis
    analysis: str = ""
    
    # Metadata
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class VolumeAnomalyService:
    """
    Enhanced volume anomaly detection using existing data.
    
    Detects:
    - Volume spikes (z-score > 3)
    - Accumulation (high volume + flat price)
    - Distribution (high volume + declining price)
    - Support defense (volume spike at key level)
    """
    
    # Thresholds
    ZSCORE_SPIKE_THRESHOLD = 3.0
    ZSCORE_ELEVATED_THRESHOLD = 2.0
    RVOL_HIGH_THRESHOLD = 2.0
    RVOL_LOW_THRESHOLD = 0.5
    PRICE_FLAT_THRESHOLD = 0.5  # 0.5% is "flat"
    
    def __init__(self):
        self._db = None
        self._historical_service = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._anomaly_col = db["volume_anomalies"]
            self._anomaly_col.create_index([("symbol", 1), ("detected_at", -1)])
            
    def set_historical_service(self, historical_service):
        """Set historical data service for fetching bars"""
        self._historical_service = historical_service
        
    def calculate_zscore(self, values: List[float], current: float) -> float:
        """Calculate z-score for current value"""
        if len(values) < 2:
            return 0.0
            
        try:
            mean = statistics.mean(values)
            stdev = statistics.stdev(values)
            
            if stdev == 0:
                return 0.0
                
            return (current - mean) / stdev
        except Exception:
            return 0.0
            
    def detect_anomaly(
        self,
        symbol: str,
        current_volume: int,
        historical_volumes: List[int],
        current_price: float,
        open_price: float,
        high_price: float = None,
        low_price: float = None
    ) -> Optional[VolumeAnomaly]:
        """
        Detect volume anomaly based on current and historical data.
        
        Args:
            symbol: Ticker symbol
            current_volume: Current bar's volume
            historical_volumes: List of recent volumes (20-50 bars recommended)
            current_price: Current price
            open_price: Open price for the period
            high_price: High price (optional)
            low_price: Low price (optional)
        """
        if len(historical_volumes) < 5:
            return None
            
        # Calculate metrics
        avg_volume = int(statistics.mean(historical_volumes))
        zscore = self.calculate_zscore([float(v) for v in historical_volumes], float(current_volume))
        rvol = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        price_change_pct = ((current_price - open_price) / open_price * 100) if open_price > 0 else 0
        
        # Check for anomaly conditions
        anomaly_type = None
        signal = "neutral"
        confidence = 0.0
        description = ""
        
        # Condition 1: Volume spike
        if zscore >= self.ZSCORE_SPIKE_THRESHOLD:
            anomaly_type = "spike"
            confidence = min(1.0, (zscore - 2) / 3)  # Scale confidence
            
            # Determine direction based on price action
            if price_change_pct > 1:
                signal = "bullish"
                description = f"Volume spike ({zscore:.1f}σ) with price up {price_change_pct:.1f}% - buying pressure"
            elif price_change_pct < -1:
                signal = "bearish"
                description = f"Volume spike ({zscore:.1f}σ) with price down {price_change_pct:.1f}% - selling pressure"
            else:
                # Price flat despite volume - accumulation/distribution
                if current_price > open_price:
                    signal = "bullish"
                    anomaly_type = "accumulation"
                    description = f"Volume spike ({zscore:.1f}σ) absorbed by buyers - accumulation"
                else:
                    signal = "bearish"
                    anomaly_type = "distribution"
                    description = f"Volume spike ({zscore:.1f}σ) absorbed by sellers - distribution"
                    
        # Condition 2: Accumulation pattern (high volume, flat/up price)
        elif zscore >= self.ZSCORE_ELEVATED_THRESHOLD and abs(price_change_pct) < self.PRICE_FLAT_THRESHOLD:
            anomaly_type = "absorption"
            confidence = 0.6
            
            # Check candle body vs wicks for direction
            if high_price and low_price and current_price:
                body = abs(current_price - open_price)
                total_range = high_price - low_price if high_price > low_price else 0.01
                body_ratio = body / total_range
                
                if body_ratio < 0.3:  # Small body, big wicks = absorption
                    if current_price > open_price:
                        signal = "bullish"
                        description = f"Price absorption (RVOL {rvol:.1f}x, flat price) - buyers absorbing supply"
                    else:
                        signal = "bearish"
                        description = f"Price absorption (RVOL {rvol:.1f}x, flat price) - sellers absorbing demand"
                        
        # Condition 3: Low volume warning
        elif rvol < self.RVOL_LOW_THRESHOLD:
            anomaly_type = "low_volume"
            signal = "neutral"
            confidence = 0.4
            description = f"Unusually low volume (RVOL {rvol:.2f}x) - lack of conviction"
            
        if anomaly_type:
            return VolumeAnomaly(
                symbol=symbol.upper(),
                anomaly_type=anomaly_type,
                zscore=round(zscore, 2),
                current_volume=current_volume,
                average_volume=avg_volume,
                relative_volume=round(rvol, 2),
                price_change_pct=round(price_change_pct, 2),
                price_at_detection=current_price,
                signal=signal,
                confidence=round(confidence, 2),
                description=description,
                detected_at=datetime.now(timezone.utc).isoformat(),
                bar_time=datetime.now(timezone.utc).isoformat()
            )
            
        return None
        
    def analyze_volume_profile(
        self,
        symbol: str,
        bars: List[Dict],
        lookback: int = 20
    ) -> VolumeProfile:
        """
        Analyze volume profile for a symbol using historical bars.
        
        Args:
            symbol: Ticker symbol
            bars: List of OHLCV bars (most recent first)
            lookback: Number of bars to analyze
        """
        if not bars or len(bars) < 2:
            return VolumeProfile(symbol=symbol, analysis="Insufficient data")
            
        # Get volumes
        volumes = [b.get("volume", 0) for b in bars[:lookback] if b.get("volume")]
        
        if not volumes:
            return VolumeProfile(symbol=symbol, analysis="No volume data")
            
        current_volume = volumes[0]
        historical_volumes = volumes[1:] if len(volumes) > 1 else volumes
        
        # Calculate metrics
        avg_volume = int(statistics.mean(historical_volumes)) if historical_volumes else current_volume
        rvol = current_volume / avg_volume if avg_volume > 0 else 1.0
        zscore = self.calculate_zscore([float(v) for v in historical_volumes], float(current_volume))
        
        # Determine volume trend
        if rvol >= self.RVOL_HIGH_THRESHOLD:
            volume_trend = "high"
        elif rvol <= self.RVOL_LOW_THRESHOLD:
            volume_trend = "low"
        else:
            volume_trend = "normal"
            
        # Look for recent anomalies
        recent_anomalies = []
        for i, bar in enumerate(bars[:min(10, len(bars))]):
            if i == 0:
                continue  # Skip current bar
                
            bar_volume = bar.get("volume", 0)
            bar_historical = [b.get("volume", 0) for b in bars[i+1:i+lookback+1] if b.get("volume")]
            
            if bar_historical:
                bar_zscore = self.calculate_zscore([float(v) for v in bar_historical], float(bar_volume))
                
                if abs(bar_zscore) >= self.ZSCORE_ELEVATED_THRESHOLD:
                    recent_anomalies.append({
                        "bar_index": i,
                        "zscore": round(bar_zscore, 2),
                        "volume": bar_volume,
                        "time": bar.get("timestamp", "")
                    })
                    
        # Detect institutional signal
        institutional_signal = "none"
        signal_confidence = 0.0
        
        if len(bars) >= 5:
            # Look at price vs volume relationship
            recent_bars = bars[:5]
            avg_price_change = statistics.mean([
                abs(b.get("close", 0) - b.get("open", 0)) / b.get("open", 1) * 100
                for b in recent_bars if b.get("open")
            ])
            avg_rvol = statistics.mean([
                b.get("volume", 0) / avg_volume if avg_volume > 0 else 1
                for b in recent_bars
            ])
            
            # High volume with low price movement = absorption
            if avg_rvol > 1.5 and avg_price_change < 0.5:
                price_direction = sum([
                    1 if b.get("close", 0) > b.get("open", 0) else -1
                    for b in recent_bars
                ])
                
                if price_direction > 0:
                    institutional_signal = "accumulation"
                    signal_confidence = min(0.8, avg_rvol / 3)
                elif price_direction < 0:
                    institutional_signal = "distribution"
                    signal_confidence = min(0.8, avg_rvol / 3)
                    
        # Build analysis
        analysis_parts = []
        
        if volume_trend == "high":
            analysis_parts.append(f"Volume {rvol:.1f}x average ({zscore:.1f}σ)")
        elif volume_trend == "low":
            analysis_parts.append(f"Volume below average ({rvol:.2f}x)")
        else:
            analysis_parts.append(f"Normal volume ({rvol:.1f}x)")
            
        if institutional_signal != "none":
            analysis_parts.append(f"Possible {institutional_signal} detected")
            
        if recent_anomalies:
            analysis_parts.append(f"{len(recent_anomalies)} recent volume anomalies")
            
        return VolumeProfile(
            symbol=symbol.upper(),
            current_volume=current_volume,
            average_volume=avg_volume,
            rvol=round(rvol, 2),
            zscore=round(zscore, 2),
            volume_trend=volume_trend,
            recent_anomalies=recent_anomalies,
            institutional_signal=institutional_signal,
            signal_confidence=round(signal_confidence, 2),
            analysis=". ".join(analysis_parts) + ".",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
    def get_volume_context_for_trade(
        self,
        symbol: str,
        bars: List[Dict],
        direction: str = "long"
    ) -> Dict[str, Any]:
        """
        Get volume context for trade decision.
        
        Returns actionable insights based on volume analysis.
        """
        profile = self.analyze_volume_profile(symbol, bars)
        
        signals = []
        risk_adjustment = 0.0  # Adjustment to risk assessment
        
        # High volume analysis
        if profile.volume_trend == "high":
            if profile.institutional_signal == "accumulation":
                if direction == "long":
                    signals.append("Accumulation detected - favorable for longs")
                    risk_adjustment -= 0.5
                else:
                    signals.append("Accumulation detected - caution on shorts")
                    risk_adjustment += 1.0
            elif profile.institutional_signal == "distribution":
                if direction == "short":
                    signals.append("Distribution detected - favorable for shorts")
                    risk_adjustment -= 0.5
                else:
                    signals.append("Distribution detected - caution on longs")
                    risk_adjustment += 1.0
            else:
                signals.append(f"Elevated volume ({profile.rvol:.1f}x) - increased activity")
                
        # Low volume warning
        elif profile.volume_trend == "low":
            signals.append(f"Low volume ({profile.rvol:.2f}x) - breakout may lack conviction")
            risk_adjustment += 0.5
            
        # Recent anomalies
        if profile.recent_anomalies:
            anomaly_count = len(profile.recent_anomalies)
            signals.append(f"{anomaly_count} volume anomalies in recent bars - watch for continuation")
            
        # Z-score warning
        if abs(profile.zscore) >= self.ZSCORE_SPIKE_THRESHOLD:
            signals.append(f"Extreme volume ({profile.zscore:.1f}σ) - potential reversal point")
            
        # Recommendation
        if risk_adjustment < 0:
            recommendation = "volume_favorable"
        elif risk_adjustment > 0.5:
            recommendation = "volume_caution"
        else:
            recommendation = "volume_neutral"
            
        return {
            "symbol": symbol,
            "direction": direction,
            "profile": profile.to_dict(),
            "signals": signals,
            "risk_adjustment": round(risk_adjustment, 2),
            "recommendation": recommendation,
            "summary": profile.analysis
        }
        
    def log_anomaly(self, anomaly: VolumeAnomaly):
        """Log detected anomaly to database"""
        if self._db is not None:
            try:
                self._anomaly_col.insert_one(anomaly.to_dict())
            except Exception as e:
                logger.warning(f"Error logging anomaly: {e}")
                
    def get_recent_anomalies(
        self,
        symbol: str = None,
        hours: int = 24,
        limit: int = 50
    ) -> List[VolumeAnomaly]:
        """Get recent volume anomalies"""
        if self._db is None:
            return []
            
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            query = {"detected_at": {"$gte": cutoff.isoformat()}}
            if symbol:
                query["symbol"] = symbol.upper()
                
            docs = list(
                self._anomaly_col
                .find(query)
                .sort("detected_at", -1)
                .limit(limit)
            )
            
            return [VolumeAnomaly(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]
            
        except Exception as e:
            logger.error(f"Error fetching anomalies: {e}")
            return []


# Singleton
_volume_anomaly_service: Optional[VolumeAnomalyService] = None


def get_volume_anomaly_service() -> VolumeAnomalyService:
    """Get singleton instance"""
    global _volume_anomaly_service
    if _volume_anomaly_service is None:
        _volume_anomaly_service = VolumeAnomalyService()
    return _volume_anomaly_service


def init_volume_anomaly_service(db=None, historical_service=None) -> VolumeAnomalyService:
    """Initialize service with dependencies"""
    service = get_volume_anomaly_service()
    if db is not None:
        service.set_db(db)
    if historical_service is not None:
        service.set_historical_service(historical_service)
    return service
