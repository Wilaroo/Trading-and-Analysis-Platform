"""
Execution Quality Service - 15% of TQS Score

Evaluates YOUR execution quality and current state:
- Historical execution quality for this setup
- Current tilt state (consecutive losses)
- Entry/exit tendency analysis
- Recent performance streak
- Position sizing appropriateness
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExecutionQualityScore:
    """Result of execution quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    history_score: float = 50.0
    tilt_score: float = 100.0  # Starts high, decreases with tilt
    entry_tendency_score: float = 50.0
    exit_tendency_score: float = 50.0
    streak_score: float = 50.0
    
    # Raw values
    is_tilted: bool = False
    tilt_severity: str = "none"
    consecutive_losses: int = 0
    avg_entry_slippage_pct: float = 0.0
    tends_to_chase: bool = False
    avg_r_capture_pct: float = 75.0
    tends_to_exit_early: bool = False
    recent_win_rate: float = 0.5
    trades_today: int = 0
    pnl_today: float = 0.0
    
    # Reasoning
    factors: list = None
    warnings: list = None  # Critical warnings about execution
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "history": round(self.history_score, 1),
                "tilt": round(self.tilt_score, 1),
                "entry_tendency": round(self.entry_tendency_score, 1),
                "exit_tendency": round(self.exit_tendency_score, 1),
                "streak": round(self.streak_score, 1)
            },
            "raw_values": {
                "is_tilted": self.is_tilted,
                "tilt_severity": self.tilt_severity,
                "consecutive_losses": self.consecutive_losses,
                "avg_entry_slippage_pct": round(self.avg_entry_slippage_pct, 2),
                "tends_to_chase": self.tends_to_chase,
                "avg_r_capture_pct": round(self.avg_r_capture_pct, 1),
                "tends_to_exit_early": self.tends_to_exit_early,
                "recent_win_rate": round(self.recent_win_rate, 3),
                "trades_today": self.trades_today,
                "pnl_today": round(self.pnl_today, 2)
            },
            "factors": self.factors,
            "warnings": self.warnings
        }


class ExecutionQualityService:
    """Evaluates execution quality - 15% of TQS"""
    
    def __init__(self):
        self._learning_loop = None
        
    def set_services(self, learning_loop=None):
        """Wire up dependencies"""
        self._learning_loop = learning_loop
        
    async def calculate_score(
        self,
        symbol: str,
        setup_type: str,
        direction: str = "long",
        planned_position_size: int = 100,
        account_value: float = 100000.0
    ) -> ExecutionQualityScore:
        """
        Calculate execution quality score (0-100).
        
        Components:
        - Historical execution (25%): Your past execution quality
        - Tilt state (30%): Current emotional/performance state
        - Entry tendencies (15%): Chase rate, slippage
        - Exit tendencies (15%): R-capture, early exits
        - Recent streak (15%): Hot/cold hand
        """
        result = ExecutionQualityScore()
        
        # Fetch trader profile and execution history
        profile = None
        if self._learning_loop:
            try:
                profile = await self._learning_loop.get_trader_profile()
            except Exception as e:
                logger.debug(f"Could not fetch trader profile: {e}")
                
        if profile:
            # Extract execution data
            result.is_tilted = profile.current_tilt_state.is_tilted
            result.tilt_severity = profile.current_tilt_state.tilt_severity
            result.consecutive_losses = profile.current_tilt_state.consecutive_losses
            result.avg_entry_slippage_pct = profile.avg_entry_slippage_percent
            result.tends_to_chase = profile.tends_to_chase
            result.avg_r_capture_pct = profile.avg_r_capture_percent
            result.tends_to_exit_early = profile.tends_to_exit_early
            result.trades_today = profile.trades_today
            result.pnl_today = profile.pnl_today
            
            # Get recent win rate
            if profile.overall_win_rate > 0:
                result.recent_win_rate = profile.overall_win_rate
                
        # 1. Historical Execution Score (25% weight)
        # Based on overall execution quality
        if self._learning_loop:
            try:
                # Get execution stats for this setup
                outcomes = await self._learning_loop.get_recent_outcomes(limit=20, setup_type=setup_type)
                if outcomes:
                    # Calculate average execution quality
                    exec_scores = [o.execution.execution_quality_score for o in outcomes if o.execution]
                    if exec_scores:
                        avg_exec = sum(exec_scores) / len(exec_scores)
                        result.history_score = avg_exec * 100
                        
                        if avg_exec >= 0.7:
                            result.factors.append(f"Strong execution history ({avg_exec*100:.0f}%) (+)")
                        elif avg_exec < 0.4:
                            result.factors.append(f"Weak execution history ({avg_exec*100:.0f}%) (-)")
            except Exception as e:
                logger.debug(f"Could not analyze execution history: {e}")
                
        # Default if no history
        if result.history_score == 50.0:
            result.history_score = 60  # Slightly optimistic default
            
        # 2. Tilt Score (30% weight) - Critical!
        if result.is_tilted:
            if result.tilt_severity == "severe":
                result.tilt_score = 10
                result.warnings.append("SEVERE TILT DETECTED - Consider stepping away!")
                result.factors.append(f"Severe tilt: {result.consecutive_losses} consecutive losses (--)")
            elif result.tilt_severity == "moderate":
                result.tilt_score = 35
                result.warnings.append("Moderate tilt detected - Reduce position size")
                result.factors.append(f"Moderate tilt: {result.consecutive_losses} consecutive losses (-)")
            elif result.tilt_severity == "mild":
                result.tilt_score = 60
                result.factors.append(f"Mild tilt: {result.consecutive_losses} consecutive losses")
        else:
            result.tilt_score = 100
            
        # Additional tilt factors
        if result.consecutive_losses >= 2:
            result.tilt_score = min(result.tilt_score, 70 - (result.consecutive_losses - 2) * 15)
            
        # Check PnL today
        if result.pnl_today < -500:
            result.tilt_score = max(20, result.tilt_score - 20)
            result.warnings.append(f"Down ${abs(result.pnl_today):.0f} today - Consider taking a break")
            
        # 3. Entry Tendency Score (15% weight)
        if result.tends_to_chase:
            result.entry_tendency_score = 40
            result.factors.append(f"Tendency to chase entries (avg slippage: {result.avg_entry_slippage_pct:.2f}%) (-)")
        elif result.avg_entry_slippage_pct > 0.3:
            result.entry_tendency_score = 50
            result.factors.append(f"Entry slippage higher than ideal ({result.avg_entry_slippage_pct:.2f}%)")
        elif result.avg_entry_slippage_pct < 0.1:
            result.entry_tendency_score = 85
            result.factors.append("Excellent entry execution (+)")
        else:
            result.entry_tendency_score = 70
            
        # 4. Exit Tendency Score (15% weight)
        if result.tends_to_exit_early:
            result.exit_tendency_score = 40
            result.factors.append(f"Tendency to exit early (avg R-capture: {result.avg_r_capture_pct:.0f}%) (-)")
        elif result.avg_r_capture_pct < 50:
            result.exit_tendency_score = 45
            result.factors.append(f"Low R-capture ({result.avg_r_capture_pct:.0f}%)")
        elif result.avg_r_capture_pct >= 80:
            result.exit_tendency_score = 90
            result.factors.append(f"Excellent R-capture ({result.avg_r_capture_pct:.0f}%) (+)")
        elif result.avg_r_capture_pct >= 60:
            result.exit_tendency_score = 70
        else:
            result.exit_tendency_score = 55
            
        # 5. Recent Streak Score (15% weight)
        if result.recent_win_rate >= 0.65:
            result.streak_score = 90
            result.factors.append(f"Hot hand: {result.recent_win_rate*100:.0f}% recent win rate (+)")
        elif result.recent_win_rate >= 0.55:
            result.streak_score = 75
        elif result.recent_win_rate >= 0.45:
            result.streak_score = 55
        elif result.recent_win_rate >= 0.35:
            result.streak_score = 40
            result.factors.append(f"Cold streak: {result.recent_win_rate*100:.0f}% recent win rate (-)")
        else:
            result.streak_score = 25
            result.warnings.append(f"Very cold streak: {result.recent_win_rate*100:.0f}% win rate - Review strategy")
            
        # Position sizing check
        position_pct = (planned_position_size * 50) / account_value * 100  # Assuming ~$50/share avg
        if position_pct > 5 and result.is_tilted:
            result.warnings.append("Position size too large for current tilt state - Reduce by 50%")
        elif position_pct > 10:
            result.factors.append("Large position size - Ensure proper risk management")
            
        # Calculate weighted total
        result.score = (
            result.history_score * 0.25 +
            result.tilt_score * 0.30 +
            result.entry_tendency_score * 0.15 +
            result.exit_tendency_score * 0.15 +
            result.streak_score * 0.15
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
_execution_quality_service: Optional[ExecutionQualityService] = None


def get_execution_quality_service() -> ExecutionQualityService:
    global _execution_quality_service
    if _execution_quality_service is None:
        _execution_quality_service = ExecutionQualityService()
    return _execution_quality_service
