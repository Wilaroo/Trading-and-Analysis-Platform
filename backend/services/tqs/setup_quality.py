"""
Setup Quality Service - 25% of TQS Score

Evaluates the quality of the trade setup itself:
- Pattern clarity and strength
- Historical win rate for this setup
- Expected Value (EV) in R-multiples
- Tape reading confirmation
- SMB grade (A/B/C)
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _env_on(key: str, default: bool = True) -> bool:
    """True if env var `key` is truthy (or unset and default=True). Used to gate
    the v19.34.230 setup-pillar de-compression so it is instantly reversible."""
    import os
    v = os.environ.get(key)
    if v in (None, ""):
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _canonical_base_setup(setup_type: str) -> str:
    """v19.34.271 (Issue 3) — resolve the canonical base key the
    learning_stats 'corrected store' is keyed on, so the win_rate/EV pillar
    reads the artifact-free, direction-collapsed bucket. MUST stay in lockstep
    with learning_loop_service.rebuild_learning_stats_from_all_outcomes.
    Reversible via LEARNING_CANONICAL_BASE (default ON)."""
    raw = setup_type or ""
    if _env_on("LEARNING_CANONICAL_BASE", True):
        try:
            from services.setup_taxonomy import canonicalize
            return canonicalize(raw) or raw.lower()
        except Exception:
            pass
    return raw.lower().replace("_long", "").replace("_short", "")


@dataclass
class SetupQualityScore:
    """Result of setup quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"  # A/B/C/D/F
    
    # Component scores (0-100 each)
    pattern_score: float = 50.0
    win_rate_score: float = 50.0
    ev_score: float = 50.0
    tape_score: float = 50.0
    smb_score: float = 50.0
    
    # Raw values
    win_rate: float = 0.5
    expected_value_r: float = 0.0
    tape_confirmation: bool = False
    smb_grade: str = "B"
    
    # Reasoning
    factors: list = None
    display_ctx: dict = None  # v391 — extra raw bits for sub-score descriptors
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
        if self.display_ctx is None:
            self.display_ctx = {}

    def _display(self) -> Dict:
        from services.tqs.descriptors import disp, humanize
        c = self.display_ctx
        base = c.get("base_setup") or "unknown"
        src = c.get("pattern_source", "")
        if src.startswith("family:"):
            pat_read = f"{humanize(base)} · {src.split(':',1)[1]} family (est.)"
        elif src.startswith("class:"):
            pat_read = f"{humanize(base)} · {src.split(':',1)[1]} class (est.)"
        elif src == "unknown":
            pat_read = f"{humanize(base)} · unranked (neutral)"
        else:
            pat_read = f"{humanize(base)} pattern"
        wr_read = f"{self.win_rate*100:.0f}% historical win rate"
        if c.get("ev_is_proxy"):
            ev_read = f"Est. from {c.get('risk_reward', 0):.1f}:1 R:R · no live expectancy"
        else:
            ev_read = f"Expectancy {self.expected_value_r:+.2f}R"
        tr = c.get("tape_raw", 0.0)
        if c.get("tape_forced_absent"):
            tape_read = "Tape n/a for this horizon"
        elif self.tape_confirmation:
            tape_read = "Order-flow confirms setup"
        elif tr >= 4:
            tape_read = f"Tape reading {tr:.0f}/10"
        elif tr > 0:
            tape_read = f"Weak tape reading {tr:.0f}/10"
        else:
            tape_read = "No tape-reading data"
        smb_read = f"Grade {self.smb_grade or '—'} · 5-var {c.get('smb_5var', 0)}/50"
        return {
            "pattern": disp("Pattern", self.pattern_score, pat_read),
            "win_rate": disp("Win Rate", self.win_rate_score, wr_read),
            "expected_value": disp("Expected Value", self.ev_score, ev_read,
                                   proxy=c.get("ev_is_proxy")),
            "tape": disp("Tape", self.tape_score, tape_read,
                         absent=(c.get("tape_forced_absent") or (tr == 0 and not self.tape_confirmation))),
            "smb": disp("SMB", self.smb_score, smb_read),
        }
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "pattern": round(self.pattern_score, 1),
                "win_rate": round(self.win_rate_score, 1),
                "expected_value": round(self.ev_score, 1),
                "tape": round(self.tape_score, 1),
                "smb": round(self.smb_score, 1)
            },
            "display": self._display(),
            "raw_values": {
                "win_rate": round(self.win_rate, 3),
                "expected_value_r": round(self.expected_value_r, 2),
                "tape_confirmation": self.tape_confirmation,
                "smb_grade": self.smb_grade
            },
            "factors": self.factors
        }


class SetupQualityService:
    """Evaluates setup quality - 25% of TQS"""
    
    # Setup type quality rankings (based on SMB methodology)
    SETUP_BASE_SCORES = {
        # Tier 1 - High probability setups
        "first_vwap_pullback": 85,
        "opening_drive": 80,
        "orb": 80,  # Opening Range Breakout
        "bull_flag": 78,
        "bear_flag": 78,
        "vwap_bounce": 75,
        "vwap_fade": 75,
        
        # Tier 2 - Solid setups
        "rubber_band": 72,
        "breakout": 70,
        "squeeze": 70,
        "gap_and_go": 68,
        "gap_fade": 68,
        "hitchhiker": 68,
        "second_chance": 65,
        
        # Tier 3 - Context dependent
        "mean_reversion": 62,
        "relative_strength": 60,
        "hod_breakout": 60,
        "range_break": 58,
        "pennant": 58,
        "triangle": 55,
        
        # Tier 4 - Lower probability
        "wedge": 52,
        "double_bottom": 50,
        "double_top": 50,
        "head_shoulders": 48,
        
        # Default
        "unknown": 50
    }
    
    def __init__(self):
        self._learning_loop = None
        self._scanner = None
        
    def set_services(self, learning_loop=None, scanner=None):
        """Wire up dependencies"""
        self._learning_loop = learning_loop
        self._scanner = scanner

    # v393 — taxonomy-derived pattern base. When a setup's canonical base is not
    # in the hand-tuned SETUP_BASE_SCORES, derive a tier-appropriate base from
    # the shared setup taxonomy (strategy_family → setup_class) instead of the
    # old punitive flat 50. Anchored to the explicit map's tiers so the fallback
    # slots just below the tier-1 named patterns of the same family. Future-proof:
    # any new classified setup auto-gets a sensible base, never 50 again.
    _FAMILY_BASE = {
        "breakout": 68, "continuation": 66, "reversion": 62,
        "reversal": 58, "rotation": 60, "swing": 64, "position": 62,
    }

    def _pattern_base(self, base_setup: str):
        """Return (base_score:int, source:str). explicit → family → class → unknown."""
        if base_setup in self.SETUP_BASE_SCORES:
            return self.SETUP_BASE_SCORES[base_setup], "explicit"
        try:
            from services.setup_taxonomy import strategy_family, setup_class
            fam = strategy_family(base_setup)
            if fam in self._FAMILY_BASE:
                return self._FAMILY_BASE[fam], f"family:{fam}"
            cls = setup_class(base_setup)
            if cls in self._FAMILY_BASE:
                return self._FAMILY_BASE[cls], f"class:{cls}"
        except Exception:
            pass
        return 55, "unknown"
        
    async def calculate_score(
        self,
        setup_type: str,
        symbol: str,
        trade_style: Optional[str] = None,
        tape_score: float = 0.0,
        tape_confirmation: bool = False,
        smb_grade: str = "B",
        smb_5var_score: int = 25,
        risk_reward: float = 2.0,
        alert_priority: str = "medium",
        win_rate_override: Optional[float] = None,
        ev_r_override: Optional[float] = None
    ) -> SetupQualityScore:
        """
        Calculate setup quality score (0-100).
        
        Components:
        - Pattern base score (20%): Inherent setup quality
        - Historical win rate (25%): Your actual performance
        - Expected Value (20%): Risk-adjusted return
        - Tape confirmation (20%): Order flow support
        - SMB grade (15%): Overall setup grade
        """
        result = SetupQualityScore()
        result.tape_confirmation = tape_confirmation
        result.smb_grade = smb_grade
        
        # 1. Pattern Base Score (20% weight)
        base_setup = _canonical_base_setup(setup_type)
        pattern_base, _pattern_src = self._pattern_base(base_setup)
        result.pattern_score = pattern_base
        
        if pattern_base >= 75:
            result.factors.append(f"High-quality {base_setup} pattern (+)")
        elif pattern_base < 55:
            result.factors.append(f"Lower probability {base_setup} setup (-)")
            
        # 2. Historical Win Rate Score (25% weight)
        win_rate = 0.5  # Default
        ev_r = 0.0
        # v19.34.230 (A1) — track whether a REAL expected-value figure was
        # available. When it wasn't (the common case — learning loop lacks
        # per-setup samples), the de-compression path derives the EV sub-score
        # from the alert's R:R instead of pinning it at the flat 30.
        has_ev_data = False
        
        # v19.34.213 — prefer the win_rate / EV the scanner already stamped on the
        # alert (strategy_win_rate / strategy_ev_r). Pre-fix this pillar ALWAYS
        # re-fetched via learning_loop.get_contextual_win_rate(), which needs >=5
        # contextual samples and otherwise returned the 0.5/0.0 default for 100%
        # of alerts — flooring the highest-weighted TQS pillar (empirically the
        # setup pillar was pinned near 43, never reaching B).
        if win_rate_override is not None:
            win_rate = win_rate_override
            if ev_r_override is not None:
                ev_r = ev_r_override
                has_ev_data = True
        elif self._learning_loop:
            try:
                stats = await self._learning_loop.get_contextual_win_rate(setup_type=base_setup)
                # v401 — lowered 5→3: now that alert_outcomes logging is restored
                # + backfilled, let real contextual EV displace the R:R proxy with
                # fewer samples (was starving the highest-weighted setup pillar).
                if stats.get("sample_size", 0) >= 3:
                    win_rate = stats.get("win_rate", 0.5)
                    ev_r = stats.get("expected_value_r", 0.0)
                    has_ev_data = True
            except Exception as e:
                logger.debug(f"Could not get learning stats: {e}")
                
        result.win_rate = win_rate
        result.expected_value_r = ev_r
        
        # Convert win rate to score (40% = 0, 50% = 50, 60% = 75, 70%+ = 100)
        if win_rate >= 0.70:
            result.win_rate_score = 100
            result.factors.append(f"Excellent win rate: {win_rate*100:.0f}% (++)")
        elif win_rate >= 0.60:
            result.win_rate_score = 75 + (win_rate - 0.60) * 250
            result.factors.append(f"Good win rate: {win_rate*100:.0f}% (+)")
        elif win_rate >= 0.50:
            result.win_rate_score = 50 + (win_rate - 0.50) * 250
        else:
            # v19.34.305 — remove the 40%→0 cliff. Win rate in ISOLATION is not
            # edge: a 40%-win / +2R setup is highly profitable. Expectancy (EV)
            # now carries that signal (its sub-weight is raised below), so a low
            # win rate is scored linearly (0%→0 … 50%→50) instead of being
            # auto-zeroed, which used to tank legitimate low-win/high-R setups.
            result.win_rate_score = max(0.0, win_rate * 100.0)
            if win_rate < 0.40:
                result.factors.append(f"Poor win rate: {win_rate*100:.0f}% (--)")
            else:
                result.factors.append(f"Below average win rate: {win_rate*100:.0f}% (-)")
            
        # 3. Expected Value Score (20% weight)
        # EV of 0.5R+ is good, 1R+ is excellent
        # v19.34.230 (A1) — when NO real EV figure is available (the common case;
        # learning loop lacks per-setup samples), the legacy code pinned ev_score
        # at the flat 30 (ev_r=0 default) for ~the whole book, freezing 20% of the
        # Setup pillar (diagnostic: expected_value med=30, p10-p90 all 20-30).
        # Instead derive the EV sub-score from the alert's R:R — a real, per-alert
        # varying input — so the pillar regains variance AND a high-R:R setup can
        # lift its ceiling. Env-gated; reversible to the legacy mapping.
        _decompress_setup = _env_on("TQS_SETUP_DECOMPRESS", True)
        if _decompress_setup and not has_ev_data:
            _rr = risk_reward if (risk_reward and risk_reward > 0) else 2.0
            result.ev_score = max(10.0, min(95.0, 25.0 + (_rr - 1.0) * 22.0))
            result.factors.append(f"EV proxy from R:R {_rr:.1f}:1 (no live EV data)")
        elif ev_r >= 1.0:
            result.ev_score = 100
            result.factors.append(f"Excellent EV: {ev_r:.2f}R (++)")
        elif ev_r >= 0.5:
            result.ev_score = 70 + (ev_r - 0.5) * 60
            result.factors.append(f"Positive EV: {ev_r:.2f}R (+)")
        elif ev_r >= 0.2:
            result.ev_score = 50 + (ev_r - 0.2) * 66.67
        elif ev_r >= 0:
            result.ev_score = 30 + ev_r * 100
        else:
            result.ev_score = max(0, 30 + ev_r * 30)
            result.factors.append(f"Negative EV: {ev_r:.2f}R (-)")
            
        # 4. Tape Confirmation Score (20% weight)
        # tape_score is typically 0-10 from scanner.
        # v393 — INTEGRITY FIX: tape_score == 0 means NO tape/L2 reading was
        # available (diag v392: 68% of the book), not a weak read. The old
        # `else 30` punished absence as if it were a weak tape. Distinguish
        # genuinely-absent (→ neutral 50) from measured-weak (0<score<4 → keep
        # the penalty). Mirrors the v391 absent→neutral philosophy.
        # v401 — HORIZON-AWARE TAPE: order-flow/tape only adds edge on fast
        # setups; for swing/position it's noise AND almost always absent (no L2
        # slot). Drop it explicitly (mark absent → renorm removes it) instead of
        # carrying a phantom neutral 50. Env-reversible via TQS_TAPE_HORIZON_AWARE.
        _tape_horizon_drop = (
            _env_on("TQS_TAPE_HORIZON_AWARE", True)
            and (trade_style or "").strip().lower() in ("swing", "position")
        )
        _tape_absent = _tape_horizon_drop or (
            (tape_score is None or tape_score <= 0) and not tape_confirmation
        )
        if _tape_absent:
            result.tape_score = 50.0
            if _tape_horizon_drop:
                result.factors.append(
                    f"Tape dropped for {trade_style} horizon (order-flow not predictive)"
                )
        else:
            normalized_tape = min(tape_score / 10.0, 1.0) * 100 if tape_score > 0 else 30
            if tape_confirmation:
                result.tape_score = max(normalized_tape, 80)
                result.factors.append("Tape reading confirms setup (+)")
            else:
                result.tape_score = min(normalized_tape, 60)
                if 0 < tape_score < 4:
                    result.factors.append("Weak tape reading (-)")
                
        # 5. SMB Grade Score (15% weight)
        smb_grade_scores = {"A+": 100, "A": 95, "B+": 80, "B": 65, "C+": 50, "C": 35, "D": 20, "F": 0}
        # v19.34.230 (A2) — a MISSING / uninformative SMB grade was scored as
        # "C" (35), a near-failing constant that dragged 15% of the Setup pillar
        # down for ~the whole book (diagnostic: smb med=35, stdev=1.5). An absent
        # signal should be NEUTRAL (50), not punitive. Real, corroborated grades
        # are scored exactly as before. "Uninformative" = no grade / "C" with the
        # default-ish 5-var band (no strong 5-var lift either way). Env-gated.
        _smb_uninformative = (
            (smb_grade in (None, "", "C")) and (20 <= (smb_5var_score or 0) < 40)
        )
        if _env_on("TQS_SETUP_DECOMPRESS", True) and _smb_uninformative:
            result.smb_score = 50.0
            result.factors.append("SMB grade uninformative → neutral 50 (decompress)")
        else:
            result.smb_score = smb_grade_scores.get(smb_grade, 65)
        
        # Also factor in 5-variable score (0-50 scale)
        if smb_5var_score >= 40:
            result.smb_score = min(100, result.smb_score + 15)
            result.factors.append(f"Strong SMB 5-var score: {smb_5var_score}/50 (+)")
        elif smb_5var_score < 20:
            result.smb_score = max(0, result.smb_score - 15)
            result.factors.append(f"Weak SMB 5-var score: {smb_5var_score}/50 (-)")
            
        # Bonus for alert priority
        if alert_priority == "critical":
            result.pattern_score = min(100, result.pattern_score + 10)
            result.factors.append("Critical priority alert (+)")
        elif alert_priority == "high":
            result.pattern_score = min(100, result.pattern_score + 5)
            
        # R:R bonus — skip when the EV sub-score was ALREADY derived from R:R
        # (v19.34.230 A1 decompress path) to avoid double-counting R:R.
        if not (_decompress_setup and not has_ev_data):
            if risk_reward >= 3.0:
                result.ev_score = min(100, result.ev_score + 10)
                result.factors.append(f"Excellent R:R of {risk_reward:.1f}:1 (+)")
            elif risk_reward < 1.5:
                result.ev_score = max(0, result.ev_score - 10)
                result.factors.append(f"Poor R:R of {risk_reward:.1f}:1 (-)")
            
        # v391 — stash raw bits the to_dict descriptor layer needs.
        result.display_ctx = {
            "base_setup": base_setup,
            "pattern_source": _pattern_src,
            "ev_is_proxy": bool(_decompress_setup and not has_ev_data),
            "risk_reward": risk_reward if (risk_reward and risk_reward > 0) else 2.0,
            "tape_raw": tape_score,
            "tape_forced_absent": _tape_horizon_drop,  # v401 horizon-aware drop
            "smb_5var": smb_5var_score,
        }

        # v400 (TQS4) — env-gated neutralization of two flagged setup sub-scores,
        # proven by diag_setup_pillar_probe (read-only, 14/21/30d windows):
        #   pattern : the 75-90 score bucket LOSES every window (0% win, avgR
        #             -0.34..-0.36; opening_drive=85 -> 0% win) while low-scored
        #             setups (fashionably_late 51, vwap_continuation 54) win. The
        #             static SMB tier ranking is mildly ANTI-predictive (-0.08..-0.14).
        #   win_rate: DEGENERATE — raw historical WR pinned ~0.55 for ~95% of the
        #             book (score stuck ~62); ~no signal (the -0.62 14d blip was a
        #             1-outlier artifact). Dial provided for completeness/A-B.
        # Each shrinks toward neutral 50: s -> 50 + (s-50)*k. Default k=1.0 = byte-
        # identical no-op (DORMANT). Tunable + reversible via env; A/B live like TQS2.
        import os as _os
        def _shrink_k(_key):
            try:
                return float(_os.environ.get(_key, "1.0"))
            except (TypeError, ValueError):
                return 1.0
        _pat_k = _shrink_k("TQS_SETUP_PATTERN_SHRINK")
        if _pat_k != 1.0:
            _pat_old = result.pattern_score
            result.pattern_score = max(0.0, min(100.0, 50.0 + (result.pattern_score - 50.0) * _pat_k))
            result.factors.append(f"Pattern ranking shrunk {_pat_old:.0f}->{result.pattern_score:.0f} (TQS_SETUP_PATTERN_SHRINK={_pat_k:.2f})")
        _wr_k = _shrink_k("TQS_SETUP_WR_SHRINK")
        if _wr_k != 1.0:
            _wr_old = result.win_rate_score
            result.win_rate_score = max(0.0, min(100.0, 50.0 + (result.win_rate_score - 50.0) * _wr_k))
            result.factors.append(f"Win-rate score shrunk {_wr_old:.0f}->{result.win_rate_score:.0f} (TQS_SETUP_WR_SHRINK={_wr_k:.2f})")

        # Calculate weighted total
        # v19.34.305 — rebalance sub-weights so realized EXPECTANCY (EV) carries
        # the most authority and raw win-rate carries less. Win rate alone isn't
        # edge; EV is. Old: pattern .20 / win .25 / ev .20 / tape .20 / smb .15.
        # New: ev .30 (up), win .15 (down) — a low-EV setup can no longer hide
        # behind a clean-looking pattern, and a high-EV/low-win setup isn't
        # auto-graded D. Sum still 1.00.
        result.score = (
            result.pattern_score * 0.20 +
            result.win_rate_score * 0.15 +
            result.ev_score * 0.30 +
            result.tape_score * 0.20 +
            result.smb_score * 0.15
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
_setup_quality_service: Optional[SetupQualityService] = None


def get_setup_quality_service() -> SetupQualityService:
    global _setup_quality_service
    if _setup_quality_service is None:
        _setup_quality_service = SetupQualityService()
    return _setup_quality_service
