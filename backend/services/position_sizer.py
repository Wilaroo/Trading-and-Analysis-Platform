"""
Position Sizer Service - TQS-Based Dynamic Position Sizing

Calculates optimal position size based on:
- TQS score (higher = larger position)
- Account risk parameters
- Volatility (ATR-based)
- Circuit breaker constraints
- Kelly criterion (optional)

Position sizing modes:
1. Fixed Dollar Risk: Risk same $ amount per trade
2. Fixed Percent Risk: Risk same % of account per trade  
3. TQS-Scaled: Scale size based on TQS score
4. Kelly: Optimal sizing based on historical edge
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SizingMode(str, Enum):
    """Position sizing modes"""
    FIXED_DOLLAR = "fixed_dollar"
    FIXED_PERCENT = "fixed_percent"
    TQS_SCALED = "tqs_scaled"
    KELLY = "kelly"


@dataclass
class PositionSizeResult:
    """Result of position size calculation"""
    shares: int = 0
    dollar_risk: float = 0.0
    percent_risk: float = 0.0
    position_value: float = 0.0
    
    # Scaling factors applied
    tqs_multiplier: float = 1.0
    circuit_breaker_multiplier: float = 1.0
    volatility_multiplier: float = 1.0
    final_multiplier: float = 1.0
    
    # For transparency
    base_shares: int = 0  # Before scaling
    reasoning: str = ""
    warnings: list = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> Dict:
        return {
            "shares": self.shares,
            "dollar_risk": round(self.dollar_risk, 2),
            "percent_risk": round(self.percent_risk, 2),
            "position_value": round(self.position_value, 2),
            "scaling": {
                "tqs_multiplier": round(self.tqs_multiplier, 2),
                "circuit_breaker_multiplier": round(self.circuit_breaker_multiplier, 2),
                "volatility_multiplier": round(self.volatility_multiplier, 2),
                "final_multiplier": round(self.final_multiplier, 2)
            },
            "base_shares": self.base_shares,
            "reasoning": self.reasoning,
            "warnings": self.warnings
        }


@dataclass
class SizingConfig:
    """Configuration for position sizing"""
    mode: SizingMode = SizingMode.TQS_SCALED
    
    # Risk parameters
    max_risk_per_trade_pct: float = 1.0   # Max % of account to risk
    max_risk_per_trade_dollar: float = 500.0  # Max $ to risk
    max_position_pct: float = 10.0  # Max % of account in one position
    
    # TQS scaling
    tqs_min_score: float = 35.0   # Below this, don't trade
    tqs_base_score: float = 50.0  # At this score, use base size
    tqs_max_score: float = 85.0   # At this score, use max size
    tqs_min_multiplier: float = 0.25  # Minimum size at low TQS
    tqs_max_multiplier: float = 1.5   # Maximum size at high TQS
    
    # Volatility adjustment
    volatility_adjust: bool = True
    atr_target_pct: float = 2.0   # Target ATR%
    atr_min_multiplier: float = 0.5
    atr_max_multiplier: float = 1.5
    
    # Kelly criterion
    kelly_fraction: float = 0.25  # Use 25% of Kelly (quarter Kelly)
    
    def to_dict(self) -> Dict:
        return {
            "mode": self.mode.value,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_risk_per_trade_dollar": self.max_risk_per_trade_dollar,
            "max_position_pct": self.max_position_pct,
            "tqs_scaling": {
                "min_score": self.tqs_min_score,
                "base_score": self.tqs_base_score,
                "max_score": self.tqs_max_score,
                "min_multiplier": self.tqs_min_multiplier,
                "max_multiplier": self.tqs_max_multiplier
            },
            "volatility_adjust": self.volatility_adjust,
            "kelly_fraction": self.kelly_fraction
        }


class PositionSizerService:
    """
    Calculates optimal position sizes based on TQS and risk parameters.
    
    The formula for TQS-scaled sizing:
    1. Calculate base shares from risk ($ risk / risk per share)
    2. Apply TQS multiplier (based on score)
    3. Apply volatility multiplier (based on ATR)
    4. Apply circuit breaker constraints
    5. Cap at max position size
    """
    
    def __init__(self):
        self._config = SizingConfig()
        self._circuit_breaker = None
        self._learning_loop = None
        
    def set_services(self, circuit_breaker=None, learning_loop=None):
        """Wire up dependencies"""
        self._circuit_breaker = circuit_breaker
        self._learning_loop = learning_loop
        
    def configure(self, config: Dict[str, Any]):
        """Update sizing configuration"""
        if "mode" in config:
            self._config.mode = SizingMode(config["mode"])
        if "max_risk_per_trade_pct" in config:
            self._config.max_risk_per_trade_pct = config["max_risk_per_trade_pct"]
        if "max_risk_per_trade_dollar" in config:
            self._config.max_risk_per_trade_dollar = config["max_risk_per_trade_dollar"]
        if "max_position_pct" in config:
            self._config.max_position_pct = config["max_position_pct"]
            
        # TQS scaling
        if "tqs_min_score" in config:
            self._config.tqs_min_score = config["tqs_min_score"]
        if "tqs_base_score" in config:
            self._config.tqs_base_score = config["tqs_base_score"]
        if "tqs_max_score" in config:
            self._config.tqs_max_score = config["tqs_max_score"]
        if "tqs_min_multiplier" in config:
            self._config.tqs_min_multiplier = config["tqs_min_multiplier"]
        if "tqs_max_multiplier" in config:
            self._config.tqs_max_multiplier = config["tqs_max_multiplier"]
            
        logger.info(f"Position sizer configured: {self._config.to_dict()}")
        
    def get_config(self) -> Dict:
        """Get current configuration"""
        return self._config.to_dict()
        
    async def calculate_size(
        self,
        entry_price: float,
        stop_price: float,
        account_value: float,
        tqs_score: float = 50.0,
        atr_percent: float = 2.0,
        win_rate: float = 0.5,
        avg_win_r: float = 1.5,
        avg_loss_r: float = 1.0,
        circuit_breaker_multiplier: float = 1.0
    ) -> PositionSizeResult:
        """
        Calculate optimal position size.
        
        Args:
            entry_price: Planned entry price
            stop_price: Stop loss price
            account_value: Current account value
            tqs_score: Trade Quality Score (0-100)
            atr_percent: Current ATR as percentage of price
            win_rate: Historical win rate for this setup
            avg_win_r: Average R on winning trades
            avg_loss_r: Average R on losing trades
            circuit_breaker_multiplier: Constraint from circuit breakers
            
        Returns:
            PositionSizeResult with shares and all scaling factors
        """
        result = PositionSizeResult()
        
        # Validate inputs
        if entry_price <= 0 or stop_price <= 0:
            result.warnings.append("Invalid prices")
            return result
            
        if account_value <= 0:
            result.warnings.append("Invalid account value")
            return result
            
        # Calculate risk per share
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            risk_per_share = entry_price * 0.02  # Default 2% risk
            result.warnings.append("No stop specified, using 2% default")
            
        # 1. Calculate base position size (before any scaling)
        if self._config.mode == SizingMode.FIXED_DOLLAR:
            base_risk = self._config.max_risk_per_trade_dollar
            result.reasoning = f"Fixed ${base_risk:.0f} risk"
            
        elif self._config.mode == SizingMode.FIXED_PERCENT:
            base_risk = account_value * (self._config.max_risk_per_trade_pct / 100)
            result.reasoning = f"Fixed {self._config.max_risk_per_trade_pct}% risk"
            
        elif self._config.mode == SizingMode.KELLY:
            # Kelly criterion: f* = (bp - q) / b
            # where b = avg_win_r/avg_loss_r, p = win_rate, q = 1-p
            b = avg_win_r / avg_loss_r if avg_loss_r > 0 else 1.5
            p = win_rate
            q = 1 - p
            kelly_full = (b * p - q) / b if b > 0 else 0
            kelly_full = max(0, min(1, kelly_full))  # Bound 0-100%
            
            # Use fractional Kelly
            kelly_fraction = kelly_full * self._config.kelly_fraction
            base_risk = account_value * kelly_fraction
            result.reasoning = f"Kelly ({kelly_full*100:.1f}% full, using {kelly_fraction*100:.1f}%)"
            
        else:  # TQS_SCALED
            base_risk = account_value * (self._config.max_risk_per_trade_pct / 100)
            result.reasoning = f"TQS-scaled from {self._config.max_risk_per_trade_pct}% base"
            
        # Calculate base shares
        base_shares = int(base_risk / risk_per_share) if risk_per_share > 0 else 0
        result.base_shares = base_shares
        result.dollar_risk = base_shares * risk_per_share
        
        # 2. Apply TQS multiplier
        if self._config.mode == SizingMode.TQS_SCALED:
            result.tqs_multiplier = self._calculate_tqs_multiplier(tqs_score)
            
            if tqs_score < self._config.tqs_min_score:
                result.warnings.append(f"TQS {tqs_score:.1f} below minimum {self._config.tqs_min_score}")
        else:
            result.tqs_multiplier = 1.0
            
        # 3. Apply volatility adjustment
        if self._config.volatility_adjust:
            result.volatility_multiplier = self._calculate_volatility_multiplier(atr_percent)
        else:
            result.volatility_multiplier = 1.0
            
        # 4. Apply circuit breaker constraint
        result.circuit_breaker_multiplier = circuit_breaker_multiplier
        
        if circuit_breaker_multiplier < 1.0:
            result.warnings.append(f"Circuit breaker reducing size to {circuit_breaker_multiplier*100:.0f}%")
            
        # 5. Calculate final multiplier and shares
        result.final_multiplier = (
            result.tqs_multiplier *
            result.volatility_multiplier *
            result.circuit_breaker_multiplier
        )
        
        final_shares = int(base_shares * result.final_multiplier)
        
        # 6. Apply maximum position cap
        max_position_value = account_value * (self._config.max_position_pct / 100)
        max_shares_by_position = int(max_position_value / entry_price) if entry_price > 0 else 0
        
        if final_shares > max_shares_by_position:
            final_shares = max_shares_by_position
            result.warnings.append(f"Capped at max position {self._config.max_position_pct}%")
            
        # 7. Apply max risk cap
        final_risk = final_shares * risk_per_share
        max_risk = min(
            self._config.max_risk_per_trade_dollar,
            account_value * (self._config.max_risk_per_trade_pct / 100)
        )
        
        if final_risk > max_risk:
            final_shares = int(max_risk / risk_per_share)
            result.warnings.append(f"Capped at max risk ${max_risk:.0f}")
            
        # Set final values
        result.shares = max(0, final_shares)
        result.dollar_risk = result.shares * risk_per_share
        result.percent_risk = (result.dollar_risk / account_value * 100) if account_value > 0 else 0
        result.position_value = result.shares * entry_price
        
        return result
        
    def _calculate_tqs_multiplier(self, tqs_score: float) -> float:
        """
        Calculate size multiplier based on TQS score.
        
        Linear interpolation:
        - tqs_min_score -> tqs_min_multiplier
        - tqs_base_score -> 1.0
        - tqs_max_score -> tqs_max_multiplier
        """
        if tqs_score <= self._config.tqs_min_score:
            return self._config.tqs_min_multiplier
        elif tqs_score >= self._config.tqs_max_score:
            return self._config.tqs_max_multiplier
        elif tqs_score <= self._config.tqs_base_score:
            # Interpolate between min and base
            range_score = self._config.tqs_base_score - self._config.tqs_min_score
            range_mult = 1.0 - self._config.tqs_min_multiplier
            progress = (tqs_score - self._config.tqs_min_score) / range_score if range_score > 0 else 0
            return self._config.tqs_min_multiplier + (progress * range_mult)
        else:
            # Interpolate between base and max
            range_score = self._config.tqs_max_score - self._config.tqs_base_score
            range_mult = self._config.tqs_max_multiplier - 1.0
            progress = (tqs_score - self._config.tqs_base_score) / range_score if range_score > 0 else 0
            return 1.0 + (progress * range_mult)
            
    def _calculate_volatility_multiplier(self, atr_percent: float) -> float:
        """
        Adjust size based on current volatility.
        
        - High volatility -> smaller size (same dollar risk, fewer shares)
        - Low volatility -> larger size (but capped)
        """
        target_atr = self._config.atr_target_pct
        
        if atr_percent <= 0:
            return 1.0
            
        # Ratio of target to actual
        ratio = target_atr / atr_percent
        
        # Bound the multiplier
        return max(
            self._config.atr_min_multiplier,
            min(self._config.atr_max_multiplier, ratio)
        )
        
    def get_sizing_table(self, entry_price: float, stop_price: float, account_value: float) -> Dict[str, Any]:
        """
        Generate a table showing position sizes at different TQS scores.
        Useful for understanding the scaling.
        """
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            risk_per_share = entry_price * 0.02
            
        base_risk = account_value * (self._config.max_risk_per_trade_pct / 100)
        base_shares = int(base_risk / risk_per_share)
        
        table = []
        for score in [35, 50, 65, 75, 85, 95]:
            multiplier = self._calculate_tqs_multiplier(score)
            shares = int(base_shares * multiplier)
            dollar_risk = shares * risk_per_share
            
            table.append({
                "tqs_score": score,
                "multiplier": round(multiplier, 2),
                "shares": shares,
                "dollar_risk": round(dollar_risk, 2),
                "position_value": round(shares * entry_price, 2)
            })
            
        return {
            "entry_price": entry_price,
            "stop_price": stop_price,
            "risk_per_share": round(risk_per_share, 2),
            "account_value": account_value,
            "base_shares": base_shares,
            "scaling_table": table
        }


# Singleton
_position_sizer_service: Optional[PositionSizerService] = None


def get_position_sizer_service() -> PositionSizerService:
    global _position_sizer_service
    if _position_sizer_service is None:
        _position_sizer_service = PositionSizerService()
    return _position_sizer_service


def init_position_sizer_service(circuit_breaker=None, learning_loop=None) -> PositionSizerService:
    service = get_position_sizer_service()
    service.set_services(circuit_breaker=circuit_breaker, learning_loop=learning_loop)
    return service
