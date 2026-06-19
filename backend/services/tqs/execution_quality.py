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


# ── v19.34.219 — direct trade_outcomes reader ─────────────────────────────
# The Execution pillar previously pulled recent outcomes via
# `learning_loop.get_recent_outcomes()`, but that reference returns EMPTY inside
# the TQS-engine context (the learning loop's collections are wired in a
# deferred background init, and the engine captured the loop before/around it),
# so the pillar fell back to the all-default constant. Read `trade_outcomes`
# DIRECTLY via a cached pymongo client (same pattern as pnl_compute) so the
# pillar's recent_win_rate / consecutive_losses are always the live tape.
_TO_CLIENT = None
_TO_DB = None


def _get_trade_outcomes_collection():
    global _TO_CLIENT, _TO_DB
    if _TO_DB is not None:
        return _TO_DB["trade_outcomes"]
    import os
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        return None
    try:
        from pymongo import MongoClient
        _TO_CLIENT = MongoClient(mongo_url, serverSelectionTimeoutMS=1500)
        _TO_DB = _TO_CLIENT[os.environ.get("DB_NAME", "tradecommand")]
        return _TO_DB["trade_outcomes"]
    except Exception as e:
        logger.debug("[exec-pillar] trade_outcomes mongo init failed: %s", e)
        return None


def _recent_trade_outcomes(limit: int = 30):
    """Newest-first raw trade_outcomes dicts. Empty list on any failure."""
    coll = _get_trade_outcomes_collection()
    if coll is None:
        return []
    try:
        return list(coll.find(
            {}, {"outcome": 1, "actual_r": 1, "created_at": 1, "execution": 1}
        ).sort("created_at", -1).limit(limit))
    except Exception as e:
        logger.debug("[exec-pillar] trade_outcomes read failed: %s", e)
        return []


# ── v19.34.230 (B3) — per-setup_type execution-history map ────────────────
# The Execution pillar's `history_score` was pinned at the 60 default for the
# whole book (diagnostic: history med=60, stdev=0.00) because the per-setup
# `learning_loop.get_recent_outcomes(setup_type=…)` returns EMPTY in the
# TQS-engine context. Compute it DIRECTLY from `trade_outcomes`, grouped by
# setup_type, once per TTL (shared across every alert in a scan cycle → one
# cheap aggregation, not a query per alert), and shrink toward the 60 neutral by
# sample size so thin-data setups barely move. Env-gated + fail-open.
_HIST_CACHE = {"map": {}, "fetched_at": 0.0}


def _env_on(key: str, default: bool = True) -> bool:
    import os
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _env_int(key: str, default: int) -> int:
    import os
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _norm_setup(setup_type: str) -> str:
    return (setup_type or "").lower().replace("_long", "").replace("_short", "")


def _setup_history_map() -> Dict[str, Dict]:
    """{base_setup_type -> {"n": int, "score": float(0-100)}} from trade_outcomes.

    Score prefers avg execution_quality_score (0-1 → 0-100); falls back to the
    win-rate proxy when exec-quality is unavailable. TTL-cached. Empty/stale-safe.
    """
    import time
    now = time.time()
    ttl = _env_int("TQS_EXEC_HIST_TTL_SEC", 900)
    if _HIST_CACHE["map"] and (now - _HIST_CACHE["fetched_at"]) < ttl:
        return _HIST_CACHE["map"]
    coll = _get_trade_outcomes_collection()
    if coll is None:
        return _HIST_CACHE["map"]
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=_env_int("TQS_EXEC_HIST_WINDOW_DAYS", 30))).isoformat()
    try:
        rows = list(coll.aggregate([
            {"$match": {"outcome": {"$in": ["won", "lost", "breakeven"]},
                        "created_at": {"$gte": cutoff}}},
            {"$group": {
                "_id": "$setup_type",
                "n": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$eq": ["$outcome", "won"]}, 1, 0]}},
                "avg_exec_q": {"$avg": "$execution.execution_quality_score"},
            }},
        ]))
    except Exception as e:
        logger.debug("[exec-decompress] aggregation failed: %s", e)
        return _HIST_CACHE["map"]
    merged: Dict[str, Dict] = {}
    for r in rows:
        base = _norm_setup(r.get("_id") or "")
        n = int(r.get("n") or 0)
        if not base or n <= 0:
            continue
        aeq = r.get("avg_exec_q")
        if aeq and aeq > 0:
            raw = max(0.0, min(100.0, float(aeq) * 100.0))
        else:
            raw = (int(r.get("wins") or 0) / n) * 100.0
        m = merged.setdefault(base, {"n": 0, "wsum": 0.0})
        m["n"] += n
        m["wsum"] += raw * n
    out = {b: {"n": v["n"], "score": (v["wsum"] / v["n"]) if v["n"] else 60.0}
           for b, v in merged.items()}
    _HIST_CACHE["map"] = out
    _HIST_CACHE["fetched_at"] = now
    logger.info("[exec-decompress] setup-history map refreshed: %d setups", len(out))
    return out


def _field(o, name, default=None):
    """Read `name` from a mongo dict OR a TradeOutcome object."""
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def _derive_live_execution_state(outcomes) -> Dict:
    """v19.34.217/219 — compute the execution-state inputs the pillar needs from
    a NEWEST-FIRST list of recent outcomes (raw `trade_outcomes` dicts OR
    TradeOutcome objects) so the Execution pillar discriminates instead of
    pinning at the all-default constant.

      recent_win_rate    = wins / (wins + losses)
      consecutive_losses = trailing loss streak from the most-recent close
      tilt_severity      = severe(>=5) / moderate(>=3) / mild(>=2) / none
      avg_r_capture_pct  = mean of available r_capture_percent, else None
    """
    wins = losses = 0
    consec = 0
    counting = True  # stop counting the trailing streak at the first non-loss
    r_caps = []
    for o in outcomes:  # newest-first (sorted created_at DESC by caller)
        oc = str(_field(o, "outcome", "")).lower()
        if oc == "won":
            wins += 1
            counting = False
        elif oc == "lost":
            losses += 1
            if counting:
                consec += 1
        else:
            counting = False
        ex = _field(o, "execution", None)
        rc = (ex.get("r_capture_percent", 0) if isinstance(ex, dict)
              else getattr(ex, "r_capture_percent", 0) if ex else 0)
        if rc and rc > 0:
            r_caps.append(rc)

    sample = wins + losses
    recent_wr = (wins / sample) if sample else 0.5
    if consec >= 5:
        sev = "severe"
    elif consec >= 3:
        sev = "moderate"
    elif consec >= 2:
        sev = "mild"
    else:
        sev = "none"
    return {
        "sample": sample,
        "recent_win_rate": recent_wr,
        "consecutive_losses": consec,
        "is_tilted": consec >= 2,
        "tilt_severity": sev,
        "avg_r_capture_pct": (sum(r_caps) / len(r_caps)) if r_caps else None,
    }


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
    display_ctx: dict = None  # v391 — extra raw bits for sub-score descriptors
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
        if self.warnings is None:
            self.warnings = []
        if self.display_ctx is None:
            self.display_ctx = {}

    def _display(self) -> Dict:
        from services.tqs.descriptors import disp
        c = self.display_ctx
        n = c.get("recent_sample", 0)
        # History
        hn = c.get("history_n")
        hist_read = (f"Setup exec track record (n={hn})" if hn
                     else "Limited execution history")
        # Tilt
        tilt_read = ("No tilt · 0 consecutive losses" if not self.is_tilted
                     else f"{self.tilt_severity.title()} tilt · {self.consecutive_losses} consec losses")
        # Entry tendency
        if c.get("entry_data_absent"):
            entry_read = "No entry-execution data yet"
        elif self.tends_to_chase:
            entry_read = f"Chases entries · slippage {self.avg_entry_slippage_pct:.2f}%"
        else:
            entry_read = f"Avg entry slippage {self.avg_entry_slippage_pct:.2f}%"
        # Exit tendency
        exit_read = (f"R-capture {self.avg_r_capture_pct:.0f}%"
                     + (" · exits early" if self.tends_to_exit_early else ""))
        # Streak
        streak_read = (f"{self.recent_win_rate*100:.0f}% win rate"
                       + (f" · last {n} closes" if n else ""))
        return {
            "history": disp("History", self.history_score, hist_read),
            "tilt": disp("Tilt", self.tilt_score, tilt_read),
            "entry_tendency": disp("Entry Tendency", self.entry_tendency_score,
                                   entry_read, absent=c.get("entry_data_absent")),
            "exit_tendency": disp("Exit Tendency", self.exit_tendency_score, exit_read),
            "streak": disp("Streak", self.streak_score, streak_read,
                           absent=(n == 0)),
        }
    
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
            "warnings": self.warnings,
            "display": self._display()
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

        # v19.34.217 — the persisted `trader_profiles` doc is only written by
        # the EOD `run_daily_analysis` batch; when that hasn't populated it the
        # profile comes back at all-defaults (total_trades=0, win_rate=0,
        # consecutive_losses=0) and the pillar pins at a constant. Detect that
        # and derive the execution-state inputs LIVE from the fresh
        # trade_outcomes feed instead.
        profile_has_data = bool(profile and getattr(profile, "total_trades", 0))

        if profile_has_data:
            # Extract execution-tendency data (slippage / chase / r-capture /
            # today). recent_win_rate + consecutive_losses are OVERRIDDEN below
            # from the live tape (the profile's aggregation is unreliable).
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

        # v19.34.218/219 — recent_win_rate + consecutive_losses are OBJECTIVE
        # facts from the outcome tape. The in-memory trader profile is unreliable
        # for them (overall_win_rate aggregates to 0; tilt counter resets) AND
        # learning_loop.get_recent_outcomes() returns EMPTY in the TQS-engine
        # context (deferred init). So read `trade_outcomes` DIRECTLY via pymongo
        # and ALWAYS override these fields when any outcomes exist.
        try:
            recent = _recent_trade_outcomes(limit=30)
            if not recent and self._learning_loop:
                # last-resort fallback to the loop (e.g. tests with a fake loop)
                recent = await self._learning_loop.get_recent_outcomes(limit=30)
            live = _derive_live_execution_state(recent)
            result.display_ctx["recent_sample"] = live["sample"]
            if live["sample"] > 0:
                result.recent_win_rate = live["recent_win_rate"]
                result.consecutive_losses = live["consecutive_losses"]
                result.is_tilted = live["is_tilted"]
                result.tilt_severity = live["tilt_severity"]
                if not profile_has_data and live["avg_r_capture_pct"] is not None:
                    result.avg_r_capture_pct = live["avg_r_capture_pct"]
                    result.tends_to_exit_early = live["avg_r_capture_pct"] < 50
                result.factors.append(
                    f"Live exec state from {live['sample']} recent closes "
                    f"(win {live['recent_win_rate']*100:.0f}%, "
                    f"{live['consecutive_losses']} consec losses)"
                )
            else:
                logger.warning(
                    "[v19.34.219 exec-pillar] no recent trade_outcomes found — "
                    "recent_win_rate/consecutive_losses fall back to defaults"
                )
        except Exception as e:
            logger.debug(f"Could not derive live execution state: {e}")
                
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

        # v19.34.230 (B3) — replace the pinned-60 default with a PER-SETUP_TYPE
        # history score read live from trade_outcomes (TTL-cached aggregation),
        # shrunk toward 60 by sample size so thin-data setups barely move. This
        # gives the Execution pillar real cross-sectional variance by setup
        # instead of a flat constant (diagnostic: history stdev=0.00). Env-gated;
        # any failure falls back to exactly the legacy 60 behaviour.
        if _env_on("TQS_EXEC_DECOMPRESS", True):
            try:
                hmap = _setup_history_map()
                rec = hmap.get(_norm_setup(setup_type))
                if rec and rec.get("n", 0) > 0:
                    result.display_ctx["history_n"] = int(rec["n"])
                    K = float(_env_int("TQS_EXEC_HIST_SHRINK_K", 10))
                    n = float(rec["n"])
                    raw = float(rec["score"])
                    result.history_score = 60.0 + (raw - 60.0) * (n / (n + K))
                    result.factors.append(
                        f"Per-setup exec history {_norm_setup(setup_type)}: "
                        f"raw {raw:.0f} (n={int(n)}) → {result.history_score:.0f}"
                    )
            except Exception as e:
                logger.debug(f"[exec-decompress] per-setup history failed: {e}")
            
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
        # v391 — INTEGRITY FIX: entry slippage / chase ONLY come from the EOD
        # `trader_profiles` batch (no live derivation, unlike exit-tendency).
        # When that profile is empty, slippage defaulted to 0.0 → scored 85 +
        # "Excellent entry execution (+)" — i.e. ABSENCE was reported as
        # EXCELLENCE. Neutralise to 50 with an honest descriptor instead.
        _entry_data_absent = not profile_has_data
        if _entry_data_absent:
            result.entry_tendency_score = 50
        elif result.tends_to_chase:
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
        result.display_ctx["entry_data_absent"] = _entry_data_absent
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
