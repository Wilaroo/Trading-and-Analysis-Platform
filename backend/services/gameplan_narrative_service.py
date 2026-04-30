"""
GamePlanNarrativeService — Phase 2 of the v19.20 briefing depth upgrade.

The Morning Briefing "Stocks in play" card used to render `SYMBOL · Technical
Setup` with no guidance. Operator request:

    "this give me no guidance or tells what the setup is or what we should be
     looking for, targets, S/R areas, possible entries and exits, etc."

This service composes a per-symbol PM-style game plan by:

1. Pulling a live `TechnicalSnapshot` (VWAP, ORH/ORL, HOD/LOD, prev close,
   ATR, support/resistance, etc.) from the existing RealTimeTechnicalService
   so every level in the briefing is IB-sourced, NOT hallucinated.

2. Building deterministic bullets (key levels, triggers, invalidation,
   targets) from the snapshot + the alert's stored setup type. These always
   render even if Ollama is offline.

3. Calling Ollama `gpt-oss:120b-cloud` (via the existing HTTP proxy in
   routers/ollama_proxy.py) for a 2-3 sentence trader narrative. The prompt
   explicitly tells the model to use tickers as plain `$TSLA`-style tokens
   so the frontend can render them as clickable chips.

4. Returning a stable shape: { bullets, narrative, referenced_symbols,
   levels_used, llm_used } so the UI can render whether or not the LLM
   was reachable.

Cache: in-memory TTL 5 min keyed on (symbol, gameplan_date) — the morning
briefing refreshes every 2 min, we don't want to pound Ollama each tick.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 2026-05-01 v19.20 — tight cache so briefing refresh doesn't hammer the LLM.
_CACHE_TTL_SECONDS = 300.0
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")

# Pre-canned setup copy so the bullets render even when the model is mute.
_SETUP_DESCRIPTIONS = {
    "squeeze":               "Bollinger Band compression inside Keltner — volatility expansion pending.",
    "orb":                   "First-30-min opening range break with volume.",
    "orb_long":              "Break and hold above opening-range high.",
    "orb_short":             "Break and hold below opening-range low.",
    "vwap_bounce":           "Pullback to VWAP in a trending day — long on reclaim.",
    "vwap_fade":             "Price pushed far from VWAP — fade the extension back to mean.",
    "vwap_fade_long":        "Oversold below VWAP — long the mean-reversion snap back up.",
    "vwap_fade_short":       "Overbought above VWAP — short the mean-reversion fade down.",
    "vwap_continuation":     "Trending with VWAP sloping — pullback entry in the direction of the trend.",
    "rubber_band":           "ATR-extended from 9-EMA — play the snap back toward mean.",
    "rubber_band_long":      "Stretched below — long the snap back up.",
    "rubber_band_short":     "Stretched above — short the snap back down.",
    "bouncy_ball":           "Down-move, failed bounce (lower-high), short the support break.",
    "the_3_30_trade":        "Power-hour break of the afternoon range after an all-day trend.",
    "off_sides":             "Squeeze the offsides — late longs trapped, short the reversal.",
    "off_sides_short":       "Late longs trapped — short the reversal to flush them.",
    "hod_breakout":          "Break of the high-of-day on confirming volume.",
    "premarket_high_break":  "Break of pre-market high on volume — Gap & Go continuation.",
    "opening_drive":         "Trend-day open driving off the print without pullback.",
    "gap_fade":              "Fade the opening gap back toward prior close / VWAP.",
    "gap_give_go":           "Gap up, pullback, second-leg continuation higher.",
    "mean_reversion":        "Extreme move away from mean — play the snap back.",
    "mean_reversion_long":   "Oversold tape — long the reversion back to mean.",
    "mean_reversion_short":  "Overbought tape — short the reversion back to mean.",
    "9_ema_scalp":           "Pullback to 9-EMA in a trending day — quick scalp.",
    "nine_ema_scalp":        "Pullback to 9-EMA in a trending day — quick scalp.",
    "trend_continuation":    "In-trend pullback — add in the direction of the trend.",
    "breaking_news":         "News catalyst on heavy volume — ride the first leg.",
    "base_breakout":         "Break of a tight consolidation base on volume.",
    "day_2_continuation":    "Yesterday's setup held into the close — continuation watch.",
    "carry_forward_watch":   "B-grade setup from yesterday — re-look as a watchlist name.",
}


class GamePlanNarrativeService:
    """
    Build per-symbol briefing cards mixing deterministic bullets + an
    Ollama-generated trader narrative. Designed to run natively on the DGX
    (same box as Ollama) but falls back to bullets-only when the HTTP
    proxy is not connected (preview/sandbox or Ollama offline).
    """

    def __init__(self, technical_service=None):
        self._technical_service = technical_service
        # cache_key -> (expires_at_ts, payload_dict)
        self._cache: Dict[Tuple[str, str], Tuple[float, Dict]] = {}

    def set_technical_service(self, service):
        """Late-bind the realtime_technical_service singleton."""
        self._technical_service = service

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def build_card(
        self,
        *,
        symbol: str,
        stock_in_play: Dict,
        gameplan_date: str,
        market_bias: Optional[str] = None,
        market_regime: Optional[str] = None,
        use_llm: bool = True,
    ) -> Dict:
        """
        Compose the card for a single stock_in_play entry. Safe to call on
        every UI refresh — results are TTL-cached per (symbol, date).
        """
        symbol = (symbol or "").upper()
        cache_key = (symbol, gameplan_date)
        now_ts = datetime.now(timezone.utc).timestamp()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now_ts:
            return cached[1]

        snapshot = await self._safe_get_snapshot(symbol)
        levels = self._extract_levels(snapshot, stock_in_play)
        bullets = self._build_bullets(
            symbol=symbol,
            stock_in_play=stock_in_play,
            levels=levels,
        )
        narrative_text, llm_used = ("", False)
        if use_llm:
            narrative_text, llm_used = await self._try_llm_narrative(
                symbol=symbol,
                stock_in_play=stock_in_play,
                levels=levels,
                bullets=bullets,
                market_bias=market_bias,
                market_regime=market_regime,
            )
        referenced = self._extract_referenced_symbols(narrative_text, primary=symbol)

        payload = {
            "symbol": symbol,
            "setup_type": stock_in_play.get("setup_type", ""),
            "direction": stock_in_play.get("direction", "long"),
            "setup_description": _SETUP_DESCRIPTIONS.get(
                stock_in_play.get("setup_type", ""), ""
            ),
            "bullets": bullets,
            "narrative": narrative_text,
            "referenced_symbols": referenced,
            "levels": levels,
            "llm_used": llm_used,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cache[cache_key] = (now_ts + _CACHE_TTL_SECONDS, payload)
        return payload

    # ------------------------------------------------------------------ #
    # Internals — level extraction
    # ------------------------------------------------------------------ #
    async def _safe_get_snapshot(self, symbol: str):
        """Fetch TechnicalSnapshot; return None on any failure (pre-market,
        missing bars, symbol not found, etc.). Narrative still renders —
        we just lose live VWAP/ORH/ORL enrichment."""
        if not self._technical_service:
            return None
        try:
            return await self._technical_service.get_technical_snapshot(symbol)
        except Exception as exc:
            logger.debug(f"narrative snapshot fetch failed for {symbol}: {exc}")
            return None

    def _extract_levels(self, snapshot, stock_in_play: Dict) -> Dict:
        """Merge snapshot-derived live levels with the alert's stored plan
        levels. Snapshot wins when present (fresher), stock_in_play fills
        the gaps (carry-forward EOD case, snapshot unavailable)."""
        key_levels = stock_in_play.get("key_levels") or {}
        direction = stock_in_play.get("direction", "long")
        entry = self._f(key_levels.get("entry")) or self._f(stock_in_play.get("entry_price"))
        stop = self._f(key_levels.get("stop"))
        t1 = self._f(key_levels.get("target_1"))
        t2 = self._f(key_levels.get("target_2"))

        out: Dict = {
            "entry": entry,
            "stop": stop,
            "target_1": t1,
            "target_2": t2,
            "direction": direction,
        }
        if snapshot is not None:
            out.update({
                "current_price": self._f(getattr(snapshot, "current_price", None)),
                "vwap":          self._f(getattr(snapshot, "vwap", None)),
                "prev_close":    self._f(getattr(snapshot, "prev_close", None)),
                "high_of_day":   self._f(getattr(snapshot, "high_of_day", None)),
                "low_of_day":    self._f(getattr(snapshot, "low_of_day", None)),
                "or_high":       self._f(getattr(snapshot, "or_high", None)),
                "or_low":        self._f(getattr(snapshot, "or_low", None)),
                "support":       self._f(getattr(snapshot, "support", None)),
                "resistance":    self._f(getattr(snapshot, "resistance", None)),
                "atr":           self._f(getattr(snapshot, "atr", None)),
                "ema_9":         self._f(getattr(snapshot, "ema_9", None)),
                "rsi_14":        self._f(getattr(snapshot, "rsi_14", None)),
                "above_vwap":    bool(getattr(snapshot, "above_vwap", False)),
                "gap_pct":       self._f(getattr(snapshot, "gap_pct", None)),
            })
        # Light-weight measured-move target when not provided by the alert.
        if out.get("target_1") in (None, 0) and out.get("atr") and out.get("current_price"):
            mm = out["atr"] * 2.0
            if direction == "long":
                out["measured_move_target"] = round(out["current_price"] + mm, 2)
            else:
                out["measured_move_target"] = round(out["current_price"] - mm, 2)
        return out

    # ------------------------------------------------------------------ #
    # Internals — deterministic bullets
    # ------------------------------------------------------------------ #
    def _build_bullets(self, *, symbol: str, stock_in_play: Dict, levels: Dict) -> List[str]:
        """Render the bullet points that always display, even if Ollama
        is offline. Bullets intentionally use `$TICKER` syntax so the
        frontend can make them clickable the same way as the narrative."""
        setup_type = stock_in_play.get("setup_type", "")
        direction = (levels.get("direction") or "long").lower()
        side = "LONG" if direction == "long" else "SHORT"

        bullets: List[str] = []

        # Setup line
        desc = _SETUP_DESCRIPTIONS.get(setup_type, "")
        if setup_type:
            pretty_setup = setup_type.replace("_", " ").title()
            bullets.append(f"Setup: {pretty_setup} {side}{' — ' + desc if desc else ''}")
        elif side:
            bullets.append(f"Direction: {side}")

        # Key levels line (entry / stop / targets)
        entry = levels.get("entry")
        stop = levels.get("stop")
        t1 = levels.get("target_1") or levels.get("measured_move_target")
        t2 = levels.get("target_2")
        if entry or stop or t1:
            parts = []
            if entry:
                parts.append(f"entry ${entry:.2f}")
            if stop:
                parts.append(f"stop ${stop:.2f}")
            if t1:
                parts.append(f"T1 ${t1:.2f}")
            if t2:
                parts.append(f"T2 ${t2:.2f}")
            bullets.append("Plan: " + " · ".join(parts))

        # Live context line (only when snapshot available)
        if levels.get("vwap") is not None:
            ctx_parts = [f"VWAP ${levels['vwap']:.2f}"]
            if levels.get("current_price") is not None:
                above = "above" if levels.get("above_vwap") else "below"
                ctx_parts.append(f"price ${levels['current_price']:.2f} ({above} VWAP)")
            if levels.get("or_high") and levels.get("or_low"):
                ctx_parts.append(f"OR ${levels['or_low']:.2f}–${levels['or_high']:.2f}")
            if levels.get("high_of_day") and levels.get("low_of_day"):
                ctx_parts.append(f"HOD ${levels['high_of_day']:.2f} / LOD ${levels['low_of_day']:.2f}")
            bullets.append("Context: " + " · ".join(ctx_parts))

        # Trigger line — what the bot is watching for.
        trigger = self._trigger_sentence(symbol, setup_type, direction, levels)
        if trigger:
            bullets.append(f"Trigger: {trigger}")

        # Invalidation line — when to walk away.
        invalidation = self._invalidation_sentence(symbol, direction, levels)
        if invalidation:
            bullets.append(f"Invalidate: {invalidation}")

        return bullets

    def _trigger_sentence(
        self, symbol: str, setup_type: str, direction: str, levels: Dict,
    ) -> str:
        """One-liner describing the entry trigger the bot is waiting on."""
        entry = levels.get("entry")
        vwap = levels.get("vwap")
        or_high = levels.get("or_high")
        or_low = levels.get("or_low")

        if setup_type in {"vwap_bounce", "vwap_fade_long"} and vwap:
            return f"Reclaim of VWAP (${vwap:.2f}) with volume — long on confirmation."
        if setup_type == "vwap_fade_short" and vwap:
            return f"Rejection of VWAP (${vwap:.2f}) from above — short the fade."
        if setup_type in {"orb_long", "orb", "hod_breakout"} and or_high:
            return f"Break & hold above ${or_high:.2f} (OR high / HOD) on volume."
        if setup_type == "orb_short" and or_low:
            return f"Break & hold below ${or_low:.2f} (OR low) on volume."
        if setup_type == "premarket_high_break" and entry:
            return f"Break of pre-market high (${entry:.2f}) on volume."
        if setup_type == "bouncy_ball" and levels.get("low_of_day"):
            return f"Break of LOD (${levels['low_of_day']:.2f}) after failed bounce."
        if setup_type in {"squeeze"} and entry:
            direction_word = "above" if direction == "long" else "below"
            return f"Break {direction_word} ${entry:.2f} on BB-KC expansion."
        if entry:
            word = "above" if direction == "long" else "below"
            return f"Entry trigger ${entry:.2f} ({word} the line)."
        return ""

    def _invalidation_sentence(self, symbol: str, direction: str, levels: Dict) -> str:
        stop = levels.get("stop")
        if not stop:
            return ""
        if direction == "long":
            return f"Close below ${stop:.2f} — thesis broken, flat."
        return f"Close above ${stop:.2f} — thesis broken, flat."

    # ------------------------------------------------------------------ #
    # Internals — Ollama narrative
    # ------------------------------------------------------------------ #
    async def _try_llm_narrative(
        self, *, symbol: str, stock_in_play: Dict, levels: Dict,
        bullets: List[str], market_bias: Optional[str],
        market_regime: Optional[str],
    ) -> Tuple[str, bool]:
        """Call Ollama GPT-OSS 120B via HTTP proxy. Return ('', False) on
        any failure so the UI still shows the deterministic bullets."""
        try:
            from routers.ollama_proxy import call_ollama_via_http_proxy
        except Exception:
            return "", False
        import os

        model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        system_prompt = (
            "You are a senior proprietary-trading coach writing the per-stock "
            "game plan for a live trader. Keep it to 2-3 tight sentences, "
            "trader jargon is OK, no fluff. ALWAYS refer to tickers as $SYMBOL "
            "(dollar-prefix, uppercase) so the UI can render them as links. "
            "Mention specific levels when supplied. End with the one "
            "scenario you are most focused on."
        )
        context_lines = [
            f"Symbol: ${symbol}",
            f"Setup: {stock_in_play.get('setup_type', '')} "
            f"{(levels.get('direction') or 'long').upper()}",
        ]
        if market_bias:
            context_lines.append(f"Market bias: {market_bias}")
        if market_regime:
            context_lines.append(f"Regime: {market_regime}")
        # Flatten levels we trust onto the prompt.
        for lbl, key in [
            ("Entry", "entry"), ("Stop", "stop"),
            ("Target 1", "target_1"), ("Target 2", "target_2"),
            ("Measured Move", "measured_move_target"),
            ("VWAP", "vwap"), ("Prev Close", "prev_close"),
            ("HOD", "high_of_day"), ("LOD", "low_of_day"),
            ("OR High", "or_high"), ("OR Low", "or_low"),
            ("Support", "support"), ("Resistance", "resistance"),
            ("ATR", "atr"), ("RSI14", "rsi_14"),
        ]:
            v = levels.get(key)
            if v not in (None, 0):
                context_lines.append(f"{lbl}: ${v:.2f}" if lbl != "RSI14" else f"{lbl}: {v:.0f}")
        user_prompt = (
            "Write the per-stock narrative for today's game plan based on "
            "the context below.\n\n" + "\n".join(context_lines) +
            "\n\nKeep it 2-3 sentences max. Use $TICKER for any ticker mentioned."
        )

        try:
            result = await call_ollama_via_http_proxy(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options={"num_ctx": 2048, "temperature": 0.45, "num_predict": 220},
                timeout=45.0,
            )
        except Exception as exc:
            logger.debug(f"narrative LLM call failed for {symbol}: {exc}")
            return "", False

        if not result.get("success"):
            return "", False
        content = (result.get("response") or {}).get("message", {}).get("content", "")
        return content.strip(), bool(content.strip())

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _extract_referenced_symbols(self, text: str, primary: str) -> List[str]:
        """Pull any $TICKER tokens from the narrative so the UI can render
        them as clickable chips. Primary symbol is always first; duplicates
        dropped while preserving order."""
        found = [primary]
        for m in _TICKER_RE.finditer(text or ""):
            sym = m.group(1)
            if sym not in found:
                found.append(sym)
        return found

    @staticmethod
    def _f(x) -> Optional[float]:
        try:
            if x is None:
                return None
            v = float(x)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None


_singleton: Optional[GamePlanNarrativeService] = None


def get_gameplan_narrative_service() -> GamePlanNarrativeService:
    global _singleton
    if _singleton is None:
        _singleton = GamePlanNarrativeService()
    return _singleton
