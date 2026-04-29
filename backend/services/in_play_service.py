"""
InPlayService — unified "in play" qualification for the scanner + AI assistant.
================================================================================

Background (2026-04-30 unification):
Two independent definitions of "in play" existed in the codebase:

  1. **Live scanner** (`enhanced_scanner._min_rvol_filter = 0.8`) — a single
     RVOL ≥ 0.8 floor. That's it. No gap, no ATR, no spread, no halt.

  2. **AI assistant** (`alert_system.AlertSystem.check_in_play`) — a richer
     0-100 scorer using RVOL ≥ 2.0, gap ≥ 3%, ATR ≥ 1.5%, spread ≤ 0.3%,
     bonuses for catalyst / short interest / low float. *Not* wired into
     the live scanner — only invoked by `ai_market_intelligence`.

Result: the AI assistant could say "AAPL is in play (score 65)" while the
scanner had already silently rejected the same symbol on the RVOL floor,
or vice-versa. Confusing for the operator and a real source of bug
reports.

This service is the single source of truth. Both paths now call the same
``score_from_snapshot`` (live) or ``score_from_market_data`` (AI assistant)
function, persist thresholds to ``bot_state.in_play_config``, and stamp
the same fields on every ``LiveAlert``.

By default the service runs in **SOFT mode** — it computes the score and
stamps it on the alert, but does NOT reject alerts. This preserves the
current alert flow for the operator who's tuned thresholds against the
v1 RVOL≥0.8 behaviour. To opt-in to strict gating (fewer, higher-quality
alerts), flip ``strict_gate=true`` in the config endpoint.

Public API:
    svc = get_in_play_service(db=db)
    qual = svc.score_from_snapshot(snapshot, spread_pct=0.05)
    qual = svc.score_from_market_data({"rvol": 2.5, "gap_pct": 4.0, ...})
    cfg  = svc.get_config()        # dict
    svc.update_config({...})        # persists to bot_state
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────── DataClass ────────────────────────────


@dataclass
class InPlayQualification:
    """Unified in-play qualification result.

    Mirror-shape of the legacy `alert_system.InPlayQualification` so
    existing AI-assistant call sites can swap the import without code
    changes.
    """
    is_in_play: bool                                # final boolean for STRICT-mode gating
    score: int                                      # 0-100
    reasons: List[str] = field(default_factory=list)
    disqualifiers: List[str] = field(default_factory=list)
    rvol: float = 1.0
    gap_pct: float = 0.0
    atr_pct: float = 1.0
    spread_pct: float = 0.0
    has_catalyst: bool = False
    short_interest: Optional[float] = None
    float_shares: Optional[float] = None


# ──────────────────────────── Service ────────────────────────────


class InPlayService:
    """Configurable in-play scorer used by both the live scanner and the
    AI market-intelligence layer. Thresholds are persisted in
    ``bot_state.in_play_config`` so operator tuning survives restarts.

    The service is intentionally **stateless across calls** — it loads
    config once on init, exposes ``update_config()`` for live edits,
    and otherwise just computes scores.
    """

    # Threshold defaults — the strictness shipped to AI assistant in v1.
    # Tuned to score most "tradeable" tape as in_play, not just the
    # overextended movers.
    DEFAULT_CONFIG: Dict = {
        "min_rvol":            2.0,        # RVOL ≥ this earns +15
        "min_gap_pct":         3.0,        # |gap| ≥ this earns +15
        "min_atr_pct":         1.5,        # ATR% ≥ this earns +8
        "max_spread_pct":      0.3,        # spread > this earns -10 disqualifier
        "min_qualifying_score": 30,        # is_in_play = True if score ≥ this
        "max_disqualifiers":   2,          # AND disqualifier count < this
        "strict_gate":         False,      # When True, scanner rejects alerts
                                           # for which is_in_play is False
        "high_rvol_strong":    5.0,        # RVOL ≥ this earns +35 (instead of +15)
        "high_rvol_modest":    3.0,        # RVOL ≥ this earns +25
        "big_gap_strong":      8.0,        # |gap| ≥ this earns +25 (instead of +15)
        "big_atr_strong":      3.0,        # ATR ≥ this earns +15 (instead of +8)
        "low_float_threshold": 20_000_000,
        "high_short_pct":      20.0,
    }

    BOT_STATE_KEY = "in_play_config"

    def __init__(self, db=None):
        self.db = db
        self._config: Dict = dict(self.DEFAULT_CONFIG)
        if db is not None:
            self._load_config()

    # ───────── Public API ─────────

    def get_config(self) -> Dict:
        return dict(self._config)

    def update_config(self, updates: Dict) -> Dict:
        """Persist threshold updates to ``bot_state.in_play_config``.

        Only known keys (those in ``DEFAULT_CONFIG``) are accepted — silently
        drops unknowns so a typo in the API call doesn't poison config.
        """
        clean: Dict = {}
        for k, v in updates.items():
            if k not in self.DEFAULT_CONFIG:
                continue
            # Coerce to the type of the default (so the API can pass strings)
            try:
                if isinstance(self.DEFAULT_CONFIG[k], bool):
                    clean[k] = bool(v) if not isinstance(v, str) else v.lower() in ("true", "1", "yes")
                elif isinstance(self.DEFAULT_CONFIG[k], int):
                    clean[k] = int(v)
                else:
                    clean[k] = float(v)
            except (TypeError, ValueError):
                continue
        if not clean:
            return self.get_config()
        self._config.update(clean)
        if self.db is not None:
            try:
                self.db["bot_state"].update_one(
                    {"_id": self.BOT_STATE_KEY},
                    {"$set": {"_id": self.BOT_STATE_KEY, **self._config}},
                    upsert=True,
                )
            except Exception as e:
                logger.warning(f"persist in_play_config failed: {e}")
        return self.get_config()

    def is_strict_gate(self) -> bool:
        return bool(self._config.get("strict_gate", False))

    def score_from_snapshot(
        self,
        snapshot,
        spread_pct: float = 0.0,
        has_catalyst: bool = False,
        short_interest: Optional[float] = None,
        float_shares: Optional[float] = None,
    ) -> InPlayQualification:
        """Score from a `realtime_technical_service.TechnicalSnapshot`.
        Used by the live scanner — snapshot already exists at the gate
        point, no extra fetches needed."""
        rvol = float(getattr(snapshot, "rvol", 1.0))
        gap_pct = float(getattr(snapshot, "gap_pct", 0.0))
        atr_pct = float(getattr(snapshot, "atr_percent", 1.0))
        return self._score(
            rvol=rvol, gap_pct=gap_pct, atr_pct=atr_pct,
            spread_pct=spread_pct, has_catalyst=has_catalyst,
            short_interest=short_interest, float_shares=float_shares,
        )

    def score_from_market_data(self, market_data: Dict) -> InPlayQualification:
        """Score from a generic dict of market signals — preserved for
        the AI assistant's existing call shape so the migration is a
        one-line import swap.
        """
        return self._score(
            rvol=float(market_data.get("rvol", 1.0)),
            gap_pct=float(market_data.get("gap_pct", 0.0)),
            atr_pct=float(market_data.get("atr_pct", 1.0)),
            spread_pct=float(market_data.get("spread_pct", 0.0)),
            has_catalyst=bool(market_data.get("has_catalyst", False)),
            short_interest=market_data.get("short_interest"),
            float_shares=market_data.get("float_shares"),
        )

    # ───────── Internals ─────────

    def _score(
        self, rvol: float, gap_pct: float, atr_pct: float, spread_pct: float,
        has_catalyst: bool, short_interest: Optional[float],
        float_shares: Optional[float],
    ) -> InPlayQualification:
        cfg = self._config
        score = 0
        reasons: List[str] = []
        disqualifiers: List[str] = []

        # ── RVOL (most important) ──
        if rvol >= cfg["high_rvol_strong"]:
            score += 35
            reasons.append(f"🔥 Exceptional volume (RVOL: {rvol:.1f}x) — very active")
        elif rvol >= cfg["high_rvol_modest"]:
            score += 25
            reasons.append(f"High volume (RVOL: {rvol:.1f}x)")
        elif rvol >= cfg["min_rvol"]:
            score += 15
            reasons.append(f"Above-average volume (RVOL: {rvol:.1f}x)")
        else:
            disqualifiers.append(f"Low relative volume ({rvol:.1f}x) — not in play")

        # ── Gap ──
        abs_gap = abs(gap_pct)
        if abs_gap >= cfg["big_gap_strong"]:
            score += 25
            reasons.append(f"🚀 Large gap {'up' if gap_pct > 0 else 'down'} ({gap_pct:+.1f}%)")
        elif abs_gap >= cfg["min_gap_pct"]:
            score += 15
            reasons.append(f"Gapping {'up' if gap_pct > 0 else 'down'} ({gap_pct:+.1f}%)")

        # ── ATR / range ──
        if atr_pct >= cfg["big_atr_strong"]:
            score += 15
            reasons.append(f"High daily range ({atr_pct:.1f}%) — good for scalping")
        elif atr_pct >= cfg["min_atr_pct"]:
            score += 8
            reasons.append(f"Decent range ({atr_pct:.1f}%)")
        else:
            disqualifiers.append(f"Tight range ({atr_pct:.1f}%) — difficult to scalp")

        # ── Spread ──
        if spread_pct > cfg["max_spread_pct"]:
            score -= 10
            disqualifiers.append(f"Wide spread ({spread_pct:.2f}%) — hurts entries/exits")

        # ── Catalyst / short / float bonuses ──
        if has_catalyst:
            score += 15
            reasons.append("Has news/catalyst driving movement")
        if short_interest is not None and short_interest >= cfg["high_short_pct"]:
            score += 10
            reasons.append(f"High short interest ({short_interest:.1f}%) — squeeze potential")
        if float_shares is not None and float_shares < cfg["low_float_threshold"]:
            score += 5
            reasons.append("Low float — can move fast")

        is_in_play = (
            score >= cfg["min_qualifying_score"]
            and len(disqualifiers) < cfg["max_disqualifiers"]
        )

        return InPlayQualification(
            is_in_play=is_in_play,
            score=max(0, min(100, score)),
            reasons=reasons,
            disqualifiers=disqualifiers,
            rvol=rvol,
            gap_pct=gap_pct,
            atr_pct=atr_pct,
            spread_pct=spread_pct,
            has_catalyst=has_catalyst,
            short_interest=short_interest,
            float_shares=float_shares,
        )

    def _load_config(self) -> None:
        if self.db is None:
            return
        try:
            doc = self.db["bot_state"].find_one({"_id": self.BOT_STATE_KEY})
        except Exception as e:
            logger.debug(f"in_play_config load failed: {e}")
            return
        if not doc:
            return
        for k, v in doc.items():
            if k == "_id" or k not in self.DEFAULT_CONFIG:
                continue
            self._config[k] = v


# ──────────────────────────── Module-level singleton ────────────────────────────

_instance: Optional[InPlayService] = None


def get_in_play_service(db=None) -> InPlayService:
    global _instance
    if _instance is None:
        _instance = InPlayService(db=db)
    elif db is not None and _instance.db is None:
        _instance.db = db
        _instance._load_config()
    return _instance
