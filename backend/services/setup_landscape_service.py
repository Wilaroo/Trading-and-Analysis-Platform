"""
SetupLandscapeService — daily Bellafiore-Setup snapshot of the universe.
==========================================================================

Powers the 1st-person Setup-aware narrative line in the morning briefing,
EOD summary, and weekend prep documents. The improvement was requested
on 2026-04-29 evening:

    "I found 47 stocks in Gap & Go (incl AAPL, ORCL), 12 in Overextension
     (incl NVDA, COIN). Today I'm favoring momentum trades; I'll be
     looking to avoid mean-reversion on overextended names."

Voice rules: always 1st-person ("I found", "I'm favoring", "I'll be
looking to") because every operator-facing surface in SentCom speaks
*as the bot*, not *about* the bot.

Pipeline:
    1. Pull the top-N symbols by ADV from `symbol_adv_cache`
       (defaults to 200 — gives broad coverage of the active universe
       without overpaying on classifier latency).
    2. Batch-call `MarketSetupClassifier.classify(symbol)` on each.
       Classifier already 5-min-caches per symbol so morning briefings
       within the same 5-min window are nearly free.
    3. Group results by `MarketSetup`. Pick top 3-5 example symbols
       per setup, sorted by classifier confidence.
    4. Map each Setup to its dominant Trade family using the matrix:
        - Gap & Go / Range Break / Day 2 → momentum / continuation
        - Gap Down/Up Into S/R / Overextension / Volatility In Range
            → reversal / mean-reversion
    5. Render 1st-person narrative based on time of day:
        - Morning      ("I'm favoring …")
        - Mid-session  ("I'm watching …")
        - EOD          ("today shaped up as …")
        - Weekend      ("over the weekend I screened …")

The service caches its full snapshot for 60 seconds so back-to-back
briefing calls are O(1).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Map each Setup → (trade_family_label, narrative_verb_long, avoid_phrase)
# Used by the narrative renderer. Stays in sync with the operator's
# matrix because each entry was hand-derived from the "Best types of
# trades for this setup" line on the playbook screenshots.
_SETUP_TRADE_FAMILY: Dict[str, Tuple[str, str, str]] = {
    "gap_and_go": (
        "momentum / trend continuation",
        "9-EMA scalps, gap-give-and-go and VWAP continuations",
        "fades and mean-reversion plays",
    ),
    "range_break": (
        "momentum / trend continuation / pullbacks",
        "hitchhikers, second chances and first VWAP pullbacks",
        "premature fades before the breakout structure confirms",
    ),
    "day_2": (
        "pullback continuations",
        "Spencer scalps, fashionably-late entries and big-dog pullbacks",
        "fresh fades — the institutional accumulation is still building",
    ),
    "gap_down_into_support": (
        "reversal longs",
        "off-sides longs, rubber-band scalps and back-through-open reversals",
        "shorting into support — that's where big players are accumulating",
    ),
    "gap_up_into_resistance": (
        "reversal shorts",
        "Bella fades, off-sides shorts and rubber-band scalps",
        "chasing the gap — that's where big players are distributing",
    ),
    "overextension": (
        "reversal / mean-reversion",
        "Bella fades, bouncy-ball trades and rubber-band scalps",
        "momentum continuations — the move is unsustainable",
    ),
    "volatility_in_range": (
        "range-fade reversals",
        "off-sides, first-move-up/down fades and Bella fades at the band extremes",
        "trend-continuation trades — the range is dominant until proven otherwise",
    ),
}


@dataclass
class SetupGroup:
    setup: str                          # MarketSetup.value
    count: int
    examples: List[Tuple[str, float]]   # [(symbol, confidence), ...]


@dataclass
class LandscapeSnapshot:
    """Universe-wide Setup classification at a point in time."""
    timestamp: str
    sample_size: int
    classified: int                     # how many returned non-NEUTRAL
    groups: List[SetupGroup]            # sorted by count desc
    narrative: str                      # 1st-person paragraph for the briefing
    headline: str                       # 1-line teaser for chat / cards
    multi_index_regime: str = "unknown"  # composite regime label (Feb-2026)
    regime_confidence: float = 0.0
    regime_reasoning: List[str] = field(default_factory=list)


class SetupLandscapeService:
    """Batch-classifies the universe and renders 1st-person briefings."""

    DEFAULT_SAMPLE_SIZE = 200
    SNAPSHOT_TTL_SECONDS = 60
    EXAMPLES_PER_GROUP   = 5

    def __init__(self, db=None):
        self.db = db
        self._snapshot: Optional[LandscapeSnapshot] = None
        self._snapshot_at: Optional[datetime] = None

    # ───────── Public API ─────────

    async def get_snapshot(self, sample_size: int = DEFAULT_SAMPLE_SIZE,
                           context: str = "morning") -> LandscapeSnapshot:
        """Compute (or return cached) landscape snapshot.

        ``context`` selects the narrative voice:
          - "morning"     → forward-looking, "I'm favoring …"
          - "midday"      → in-progress, "I'm watching …"
          - "eod"         → retrospective, "today shaped up as …"
          - "weekend"     → prep, "over the weekend I screened …"
        """
        now = datetime.now(timezone.utc)
        if self._snapshot is not None and self._snapshot_at is not None:
            if (now - self._snapshot_at).total_seconds() < self.SNAPSHOT_TTL_SECONDS:
                return self._snapshot

        symbols = await self._pull_top_symbols(sample_size)
        groups = await self._classify_batch(symbols)
        # Multi-index regime context — single market-wide classification
        regime_label, regime_conf, regime_reasoning = await self._classify_multi_index_regime()
        narrative, headline = self._render_narrative(
            groups, len(symbols), context,
            regime_label=regime_label,
            regime_reasoning=regime_reasoning,
        )
        snap = LandscapeSnapshot(
            timestamp=now.isoformat(),
            sample_size=len(symbols),
            classified=sum(g.count for g in groups if g.setup != "neutral"),
            groups=groups,
            narrative=narrative,
            headline=headline,
            multi_index_regime=regime_label,
            regime_confidence=regime_conf,
            regime_reasoning=regime_reasoning,
        )
        self._snapshot = snap
        self._snapshot_at = now
        return snap

    def invalidate(self) -> None:
        self._snapshot = None
        self._snapshot_at = None

    # ───────── Internals ─────────

    async def _pull_top_symbols(self, n: int) -> List[str]:
        """Pull top-N symbols by ADV from `symbol_adv_cache`. Falls back
        to the scanner's recently-scanned set if Mongo is unreachable."""
        if self.db is None:
            return []
        try:
            cursor = self.db["symbol_adv_cache"].find(
                {"adv_dollars": {"$gt": 0}},
                {"_id": 0, "symbol": 1, "adv_dollars": 1},
            ).sort("adv_dollars", -1).limit(n)
            rows = await cursor.to_list(length=n)
            return [r["symbol"] for r in rows if r.get("symbol")]
        except Exception as e:
            logger.warning(f"_pull_top_symbols failed, returning []: {e}")
            return []

    async def _classify_batch(self, symbols: List[str]) -> List[SetupGroup]:
        from services.market_setup_classifier import (
            get_market_setup_classifier, MarketSetup,
        )
        classifier = get_market_setup_classifier(db=self.db)

        # Batch in slices so we don't fire 200 mongo reads at once if the
        # classifier cache is cold.
        results: Dict[str, List[Tuple[str, float]]] = {s.value: [] for s in MarketSetup}
        SLICE = 25
        for i in range(0, len(symbols), SLICE):
            batch = symbols[i:i + SLICE]
            tasks = [classifier.classify(s) for s in batch]
            outs = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, out in zip(batch, outs):
                if isinstance(out, Exception):
                    logger.debug(f"classify({sym}) raised: {out}")
                    continue
                results[out.setup.value].append((sym, out.confidence))

        groups: List[SetupGroup] = []
        for setup_name, examples in results.items():
            if not examples:
                continue
            examples.sort(key=lambda x: x[1], reverse=True)
            groups.append(SetupGroup(
                setup=setup_name,
                count=len(examples),
                examples=examples[: self.EXAMPLES_PER_GROUP],
            ))
        # Sort by count desc, but push 'neutral' to the bottom regardless
        groups.sort(key=lambda g: (g.setup != "neutral", g.count), reverse=True)
        return groups

    async def _classify_multi_index_regime(self) -> Tuple[str, float, List[str]]:
        """Run the multi-index regime classifier (SPY/QQQ/IWM/DIA).

        Returns (label_str, confidence, reasoning_list). Label defaults
        to 'unknown' on any failure so the briefing degrades gracefully.
        """
        try:
            from services.multi_index_regime_classifier import (
                get_multi_index_regime_classifier,
            )
            classifier = get_multi_index_regime_classifier(db=self.db)
            res = await classifier.classify()
            return res.label.value, res.confidence, list(res.reasoning)
        except Exception as e:
            logger.debug(f"_classify_multi_index_regime failed: {e}")
            return "unknown", 0.0, []

    # ───────── Narrative renderer ─────────

    def _render_narrative(self, groups: List[SetupGroup], sample_n: int,
                          context: str,
                          regime_label: str = "unknown",
                          regime_reasoning: Optional[List[str]] = None,
                          ) -> Tuple[str, str]:
        non_neutral = [g for g in groups if g.setup != "neutral" and g.count > 0]
        regime_line = self._regime_line(regime_label, regime_reasoning, context)
        if not non_neutral:
            base = self._fallback_narrative(sample_n, context)
            full = f"{regime_line}\n\n{base}" if regime_line else base
            return full, \
                f"I screened {sample_n} names but couldn't pin any to a clear daily Setup."

        # Headline: top group only, 1-liner.
        top = non_neutral[0]
        top_examples = ", ".join(s for s, _ in top.examples[:3])
        headline = (
            f"I'm seeing {top.count} names in {self._pretty_setup(top.setup)} "
            f"(top: {top_examples}). "
            f"That tilts me toward {_SETUP_TRADE_FAMILY[top.setup][0]} today."
        )

        # Full narrative paragraph.
        intro = self._intro_for_context(context, sample_n)
        lines: List[str] = []
        if regime_line:
            lines.append(regime_line)
            lines.append("")
        lines.append(intro)
        # List up to top 4 setup groups
        for g in non_neutral[:4]:
            ex = ", ".join(s for s, _ in g.examples[:5])
            lines.append(
                f"  • **{self._pretty_setup(g.setup)}** — {g.count} names "
                f"(incl. {ex})."
            )
        # Synthesize the favoring / avoiding clauses from the top group(s)
        favoring = _SETUP_TRADE_FAMILY[top.setup][1]
        avoiding = _SETUP_TRADE_FAMILY[top.setup][0 if False else 2]  # avoid_phrase
        action_clause = self._action_clause_for_context(context, favoring, avoiding)
        lines.append("")
        lines.append(action_clause)

        # If we have a strong secondary group, add a nuance line
        if len(non_neutral) >= 2 and non_neutral[1].count >= max(3, top.count // 3):
            second = non_neutral[1]
            second_family = _SETUP_TRADE_FAMILY[second.setup][0]
            lines.append(
                f"I'm also tracking the {second.count} names in "
                f"{self._pretty_setup(second.setup)} for {second_family} setups — "
                f"those will be my counter-context plays if the primary thesis stalls."
            )

        return "\n".join(lines), headline

    @staticmethod
    def _pretty_setup(setup: str) -> str:
        return {
            "gap_and_go":             "Gap & Go",
            "range_break":            "Range Break",
            "day_2":                  "Day 2 Continuation",
            "gap_down_into_support":  "Gap Down Into Support",
            "gap_up_into_resistance": "Gap Up Into Resistance",
            "overextension":          "Overextension",
            "volatility_in_range":    "Volatility In Range",
            "neutral":                "no clear Setup",
        }.get(setup, setup.replace("_", " ").title())

    @staticmethod
    def _regime_line(regime_label: str, reasoning: Optional[List[str]],
                     context: str) -> str:
        """Render a 1-line multi-index regime preface.

        Returns "" if regime is unknown — silent fallback so older
        operator-side flows that don't care about the regime are unaffected.
        """
        if not regime_label or regime_label == "unknown":
            return ""
        # 1st-person voice mirroring the rest of the narrative.
        verb_pre = {
            "morning": "Heading into the open",
            "midday":  "Mid-session",
            "eod":     "Today",
            "weekend": "Heading into next week",
        }.get(context, "Right now")
        regime_text = {
            "risk_on_broad":
                "I'm reading the multi-index tape as **risk-on broad** — SPY/QQQ/IWM/DIA all bid",
            "risk_on_growth":
                "I'm reading the tape as **risk-on, growth-led** — QQQ leading, SPY/IWM following",
            "risk_on_smallcap":
                "I'm reading the tape as **risk-on, small-cap leading** — IWM out front of SPY/QQQ",
            "risk_off_broad":
                "I'm reading the tape as **risk-off broad** — SPY/QQQ/IWM/DIA all under pressure",
            "risk_off_defensive":
                "I'm reading the tape as **risk-off defensive** — DIA holding while QQQ/IWM bleed",
            "bullish_divergence":
                "I'm seeing a **bullish small-cap divergence** — IWM leading higher while SPY lags",
            "bearish_divergence":
                "I'm seeing a **bearish breadth divergence** — SPY firm but IWM rolling over",
            "mixed":
                "The multi-index tape is **mixed** — no clear leadership across SPY/QQQ/IWM/DIA",
        }.get(regime_label, f"Multi-index regime: {regime_label.replace('_', ' ')}")
        # Lift one rationale bullet if available
        detail = ""
        if reasoning:
            for r in reasoning:
                if r.startswith(("SPY:", "QQQ:", "IWM:", "DIA:")):
                    detail = f" ({r})"
                    break
        return f"{verb_pre}, {regime_text}{detail}."

    @staticmethod
    def _intro_for_context(context: str, n: int) -> str:
        if context == "morning":
            return f"**Setup landscape — I screened {n} of the most-active names this morning:**"
        if context == "midday":
            return f"**Mid-session check — across the {n} names I'm watching:**"
        if context == "eod":
            return f"**EOD snapshot — across {n} names today shaped up as:**"
        if context == "weekend":
            return f"**Weekend prep — I screened {n} names heading into next week:**"
        return f"**Setup landscape ({n} names):**"

    @staticmethod
    def _action_clause_for_context(context: str, favoring: str, avoiding: str) -> str:
        if context == "morning":
            return (
                f"**Today I'm favoring** {favoring}. "
                f"**I'll be looking to avoid** {avoiding} until the tape proves otherwise."
            )
        if context == "midday":
            return (
                f"**I'm staying patient on** {favoring} and **stepping aside from** "
                f"{avoiding} for now."
            )
        if context == "eod":
            return (
                f"The day favored {favoring}; "
                f"the costliest mistakes would have been chasing {avoiding}."
            )
        if context == "weekend":
            return (
                f"**Heading into next week I'm preparing** {favoring} game plans, "
                f"and **I'll skip** {avoiding} unless the daily picture shifts."
            )
        return (
            f"I'm favoring {favoring}; I'll be looking to avoid {avoiding}."
        )

    @staticmethod
    def _fallback_narrative(sample_n: int, context: str) -> str:
        if context == "morning":
            return (
                f"**Setup landscape — I screened {sample_n} of the most-active names "
                "this morning, but no clear Bellafiore Setup is dominating yet.** "
                "I'll let the open's first 30 minutes confirm a daily structure "
                "before I lean into any Trade family — until then, I'm staying small "
                "and reactive."
            )
        return (
            f"I screened {sample_n} names but couldn't pin any to a clear "
            "daily Setup right now."
        )


# ───────── Module-level singleton ─────────

_landscape_instance: Optional[SetupLandscapeService] = None


def get_setup_landscape_service(db=None) -> SetupLandscapeService:
    global _landscape_instance
    if _landscape_instance is None:
        _landscape_instance = SetupLandscapeService(db=db)
    elif db is not None and _landscape_instance.db is None:
        _landscape_instance.db = db
    return _landscape_instance
