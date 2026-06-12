#!/usr/bin/env python3
"""
apply_v325.py — HSBG: Horizon-Scaled Bracket Geometry
======================================================
Fixes the root cause the PT-reachability probe condemned (2026-06-12):
on 102 sanitized trades, median stop = 3.46% of entry (1.75 "ATR"),
median PT1 = 2.54R ≈ 4.85 ATR-units, MFE median 0.00R, PT1 touched by
0/101 trades, and NO counterfactual PT placement (0.5–2.0R) flips avgR
positive — because the R-DENOMINATOR is mis-scaled: intraday brackets
are sized off the DAILY ATR, so all price action is noise inside them.

WHAT CHANGES (backend/services/opportunity_evaluator.py only)
--------------------------------------------------------------
1. CANONICAL DAILY-ATR BASIS — the heterogeneous alert/technicals/2%
   ATR input is normalized against the collector's symbol_adv_cache
   .atr_pct with a plausibility window (0.3%–20% of price). Every
   downstream geometry decision now shares one DAILY basis.
2. HORIZON-SCALED STOPS — calculate_atr_based_stop gains an optional
   `trade_style` param. When the evaluator passes it, scalp stops are
   scaled ×HSBG_SCALP_FRAC (default 0.39 = √(60/390)) and intraday
   stops ×HSBG_INTRADAY_FRAC (default 0.35). Swing/position/investment
   UNCHANGED. Callers that do not pass trade_style (e.g. the
   /retune-stop endpoint, which feeds a 5-MINUTE ATR) keep the exact
   old behavior.
3. DETECTOR-STOP HORIZON CAP — detector-supplied stops on scalp/
   intraday styles are capped (tighten-only) at
   HSBG_DETECTOR_STOP_CAP_MULT (1.5) × the canonical horizon stop.
4. STOP-FLOOR COHERENCE — the v19.34.45 floor threshold (0.3×ATR) is
   scaled by the same horizon fraction so it can't undo the fix.
5. PT REACHABILITY STAMP + GATE — every trade stamps entry_context
   .multipliers.hsbg with {atr basis, horizon frac, hold window, reach
   envelope = daily_atr×√(hold/390), stop/pt1 envelope ratios}. PT1 at
   >0.85× reach emits a ⚠️ stream warning; >1.5× reach BLOCKS the trade
   (reason_code=hsbg_pt_unreachable). Tripwire, not routine filter —
   post-fix geometry lands ~0.4–0.8×.

R-rungs, target-snap, M0 ladder, StopManager BE/trail are untouched —
they all inherit the corrected geometry automatically (targets are
R-multiples of the now-properly-sized risk; sizer buys more shares for
the same $ risk budget).

ENV TUNABLES (all optional)
---------------------------
  HSBG_ENABLED=1                  kill switch ("0" reverts everything)
  HSBG_SCALP_FRAC=0.39            scalp stop fraction of daily ATR mult
  HSBG_INTRADAY_FRAC=0.35         intraday stop fraction
  HSBG_MIN_STOP_PCT_SCALP=0.0015  floor: 0.15% of entry
  HSBG_MIN_STOP_PCT_INTRADAY=0.0035
  HSBG_DETECTOR_STOP_CAP_MULT=1.5
  HSBG_REACH_WARN_RATIO=0.85
  HSBG_REACH_BLOCK_RATIO=1.5
  HSBG_REACH_GATE_MODE=block      "warn" = never block

Also writes backend/tests/test_v325_hsbg.py (unit + static tests).
SAFE TO RUN MULTIPLE TIMES (idempotent).

Run from repo root:  .venv/bin/python /tmp/apply_v325.py
Then: .venv/bin/python -m pytest backend/tests/test_v325_hsbg.py -q
Then: git add -A && git commit -m "v325: horizon-scaled bracket geometry + reach gate" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

EVAL_REL = "backend/services/opportunity_evaluator.py"

CHUNKS = [
    # ── C1: canonical daily-ATR basis + style/frac resolution ─────────
    (
        "atr_basis_normalization",
        '''            # Extract ATR from intelligence for volatility-adjusted sizing
            atr = alert.get('atr', 0)
            atr_percent = alert.get('atr_percent', 0)

            if not atr and intelligence.get('technicals'):
                tech = intelligence['technicals']
                atr = tech.get('atr', current_price * 0.02)
                atr_percent = tech.get('atr_percent', 2.0)
            elif not atr:
                atr = current_price * 0.02
                atr_percent = 2.0
''',
        '''            # Extract ATR from intelligence for volatility-adjusted sizing
            atr = alert.get('atr', 0)
            atr_percent = alert.get('atr_percent', 0)

            if not atr and intelligence.get('technicals'):
                tech = intelligence['technicals']
                atr = tech.get('atr', current_price * 0.02)
                atr_percent = tech.get('atr_percent', 2.0)
            elif not atr:
                atr = current_price * 0.02
                atr_percent = 2.0

            # ── v325 HSBG — canonical DAILY-ATR basis ─────────────────
            # The PT-reachability probe (2026-06-12) found entry_context
            # .atr units are heterogeneous: some alerts carry intraday
            # ATR, some daily, some fall through to the hardcoded 2%-of-
            # price guess. Every downstream geometry decision (stop
            # multiplier, stop floor, R-rung targets, reach gate) assumes
            # a DAILY basis — resolve one explicitly:
            #   1. collector's symbol_adv_cache.atr_pct (14d daily ATR/close)
            #   2. alert/technicals atr IF plausibly daily (0.3%–20% of px)
            #   3. 2% of price (last resort, flagged in meta)
            hsbg_atr_meta = {"source": "fallback_2pct"}
            try:
                _px_ref = float(current_price) if current_price else 0.0
                _atr_daily = None
                _db_hsbg = getattr(bot, "_db", None)
                if _db_hsbg is None:
                    _db_hsbg = getattr(bot, "db", None)
                if _db_hsbg is not None and symbol and _px_ref > 0:
                    try:
                        _doc = _db_hsbg["symbol_adv_cache"].find_one(
                            {"symbol": symbol.upper()}, {"atr_pct": 1, "_id": 0})
                        if _doc and _doc.get("atr_pct"):
                            _cand = float(_doc["atr_pct"]) * _px_ref
                            if 0.003 * _px_ref <= _cand <= 0.20 * _px_ref:
                                _atr_daily = _cand
                                hsbg_atr_meta = {
                                    "source": "symbol_adv_cache",
                                    "atr_pct": round(float(_doc["atr_pct"]), 6),
                                }
                    except Exception:
                        _atr_daily = None
                if _atr_daily is None and atr and _px_ref > 0:
                    # Trust the alert/technicals ATR only when plausibly a
                    # DAILY range. An intraday 5-min ATR (typically <0.3%
                    # of price) fails this window and falls through to the
                    # 2% guess instead of poisoning geometry.
                    if 0.003 * _px_ref <= float(atr) <= 0.20 * _px_ref:
                        _atr_daily = float(atr)
                        hsbg_atr_meta = {"source": "alert_or_technicals"}
                if _atr_daily is None and _px_ref > 0:
                    _atr_daily = _px_ref * 0.02
                if _atr_daily and _atr_daily > 0:
                    if abs(_atr_daily - float(atr or 0)) > 1e-9:
                        logger.info(
                            "[v325 HSBG] %s ATR basis normalized: %.4f → %.4f (%s)",
                            symbol, float(atr or 0), _atr_daily,
                            hsbg_atr_meta["source"],
                        )
                    atr = _atr_daily
                    if _px_ref > 0:
                        atr_percent = (_atr_daily / _px_ref) * 100.0
                    hsbg_atr_meta["atr_daily"] = round(_atr_daily, 6)
            except Exception as _hsbg_atr_err:
                logger.debug("[v325 HSBG] atr-basis normalize skipped: %s", _hsbg_atr_err)

            # Canonical trade style + horizon fraction for geometry
            # decisions (scalp/intraday get horizon-scaled stops; swing/
            # position/investment keep the daily basis, frac=1.0).
            hsbg_style = self._resolve_geometry_style(alert, setup_type)
            hsbg_frac = self._hsbg_horizon_frac(hsbg_style)
''',
    ),
    # ── C2a: calculate_atr_based_stop signature ───────────────────────
    (
        "atr_stop_signature",
        '''    def calculate_atr_based_stop(self, entry_price: float, direction, atr: float, setup_type: str, bot: 'TradingBotService') -> float:
        """Calculate stop loss based on ATR with setup-specific multiplier."""
''',
        '''    def calculate_atr_based_stop(self, entry_price: float, direction, atr: float, setup_type: str, bot: 'TradingBotService', trade_style: str = None) -> float:
        """Calculate stop loss based on ATR with setup-specific multiplier.

        v325 HSBG — when `trade_style` is passed, `atr` is treated as the
        canonical DAILY ATR and scalp/intraday distances are additionally
        scaled by the horizon fraction (√(hold/390)-style) so intraday
        brackets stop being sized for multi-day holds. Callers that omit
        `trade_style` (e.g. /retune-stop, which feeds a 5-MINUTE ATR)
        keep the exact pre-v325 behavior.
        """
''',
    ),
    # ── C2b: horizon scaling before the direction return ──────────────
    (
        "atr_stop_horizon_scaling",
        '''        except Exception as _cap_err:
            logger.debug(f"[atr_stop] v169 cap skipped: {_cap_err}")

        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
''',
        '''        except Exception as _cap_err:
            logger.debug(f"[atr_stop] v169 cap skipped: {_cap_err}")

        # ── v325 HSBG — horizon scaling (only when trade_style passed) ─
        if trade_style is not None:
            try:
                _style = self._resolve_geometry_style(
                    {"trade_style": trade_style}, setup_type,
                )
                _frac = self._hsbg_horizon_frac(_style)
                if _frac < 1.0:
                    _raw_dist = stop_distance
                    stop_distance = stop_distance * _frac
                    _floor_pct = self._hsbg_min_stop_pct(_style)
                    if entry_price > 0 and stop_distance < entry_price * _floor_pct:
                        stop_distance = entry_price * _floor_pct
                    logger.info(
                        "[v325 HSBG] %s stop horizon-scaled (style=%s frac=%.2f): "
                        "Δ$%.4f → Δ$%.4f (%.2f%% of entry)",
                        setup_type, _style, _frac, _raw_dist, stop_distance,
                        (stop_distance / entry_price * 100.0) if entry_price else 0.0,
                    )
            except Exception as _hsbg_err:
                logger.debug("[v325 HSBG] horizon scaling skipped: %s", _hsbg_err)

        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
''',
    ),
    # ── C3: HSBG helper methods (after _target_ladder_rungs) ──────────
    (
        "hsbg_helpers",
        '''        if trade_style_lower == 'intraday':
            return [1.5, 2.5]
        return [1.5, 2.5, 4.0]


    @staticmethod
    def classify_time_window(now_et) -> str:
''',
        '''        if trade_style_lower == 'intraday':
            return [1.5, 2.5]
        return [1.5, 2.5, 4.0]

    # ════════════════════════════════════════════════════════════════
    # v325 HSBG — Horizon-Scaled Bracket Geometry helpers
    # ════════════════════════════════════════════════════════════════
    # Probe-backed (diag_pt_reachability, 2026-06-12): intraday brackets
    # sized off the DAILY ATR put PT1 at ~2-6× the price travel a few-
    # hour hold statistically provides → 0/101 PT1 touches. These
    # helpers scale stop distances to the hold horizon and measure
    # target reachability against a √time diffusion envelope.

    @staticmethod
    def _hsbg_enabled() -> bool:
        import os as _os
        return str(_os.environ.get("HSBG_ENABLED", "1")).strip().lower() not in (
            "0", "false", "no", "off",
        )

    @classmethod
    def _resolve_geometry_style(cls, alert, setup_type) -> str:
        """Canonical trade style for geometry decisions. Uses the same
        trade_style_classifier the rest of the stack uses (trade_2_hold
        defers to the setup-derived style). `unknown` maps to intraday —
        identical to the trade-create default (trade_style=trade_2_hold
        → intraday horizon)."""
        su = (setup_type or '').strip().lower()
        if su in cls._SCALP_SETUPS:
            return 'scalp'
        ts = ((alert.get('trade_style') if isinstance(alert, dict) else None) or '')
        try:
            from services.trade_style_classifier import resolve_trade_style
            style = resolve_trade_style({"trade_style": ts, "setup_type": setup_type})
        except Exception:
            style = str(ts).strip().lower() or "unknown"
        if style in ("unknown", "", "trade_2_hold"):
            return "intraday"
        return style

    @classmethod
    def _hsbg_horizon_frac(cls, style: str) -> float:
        """Stop-distance scaling fraction vs the DAILY ATR basis.
        scalp ≈ √(60/390)=0.39 · intraday 0.35 · everything else 1.0
        (multi-day holds are correctly sized off the daily ATR)."""
        import os as _os
        if not cls._hsbg_enabled():
            return 1.0
        s = (style or '').strip().lower()
        try:
            if s == 'scalp':
                return max(0.05, min(1.0, float(_os.environ.get("HSBG_SCALP_FRAC", "0.39"))))
            if s in ('intraday', 'trade_2_hold'):
                return max(0.05, min(1.0, float(_os.environ.get("HSBG_INTRADAY_FRAC", "0.35"))))
        except (TypeError, ValueError):
            pass
        return 1.0

    @staticmethod
    def _hsbg_min_stop_pct(style: str) -> float:
        """Absolute floor on the horizon-scaled stop distance (fraction
        of entry) so an ultra-quiet symbol can't produce a sub-noise stop."""
        import os as _os
        s = (style or '').strip().lower()
        try:
            if s == 'scalp':
                return float(_os.environ.get("HSBG_MIN_STOP_PCT_SCALP", "0.0015"))
            return float(_os.environ.get("HSBG_MIN_STOP_PCT_INTRADAY", "0.0035"))
        except (TypeError, ValueError):
            return 0.0035

    @staticmethod
    def _hsbg_hold_minutes(style: str, now_et=None) -> float:
        """Expected remaining hold window in RTH-minute units.
        scalp = min(SCALP_DECAY_MINUTES, time-to-close) · intraday =
        time-to-close (full 390 premarket/weekend) · multi-day styles =
        trading-days × 390."""
        import os as _os
        s = (style or '').strip().lower()
        mins_to_close = 390.0
        try:
            from zoneinfo import ZoneInfo
            _now = now_et or datetime.now(ZoneInfo("America/New_York"))
            if _now.weekday() < 5:
                _open = _now.replace(hour=9, minute=30, second=0, microsecond=0)
                _close = _now.replace(hour=16, minute=0, second=0, microsecond=0)
                if _now > _open:
                    mins_to_close = max(15.0, (_close - _now).total_seconds() / 60.0)
        except Exception:
            mins_to_close = 390.0
        if s == 'scalp':
            try:
                scalp_hold = float(_os.environ.get("SCALP_DECAY_MINUTES", "60") or 60)
            except (TypeError, ValueError):
                scalp_hold = 60.0
            return min(scalp_hold, mins_to_close)
        if s in ('intraday', 'trade_2_hold', ''):
            return min(390.0, mins_to_close)
        _days = {'swing': 10, 'multi_day': 5, 'position': 30, 'investment': 90}.get(s, 10)
        return _days * 390.0

    @classmethod
    def _hsbg_reach_envelope(cls, daily_atr: float, style: str, now_et=None) -> float:
        """Expected |price travel| within the remaining hold window:
        daily_atr × √(hold_minutes / 390). The diffusion scale the reach
        gate measures PT1 distance against."""
        hold = cls._hsbg_hold_minutes(style, now_et=now_et)
        try:
            return max(0.0, float(daily_atr)) * ((hold / 390.0) ** 0.5)
        except (TypeError, ValueError):
            return 0.0


    @staticmethod
    def classify_time_window(now_et) -> str:
''',
    ),
    # ── C4: detector-stop horizon cap (after wrong-side guard) ────────
    (
        "detector_stop_horizon_cap",
        '''            except Exception as _ws_err:
                logger.debug(f"[v19.34.183 wrong-side-stop] skipped for {symbol}: {_ws_err}")
''',
        '''            except Exception as _ws_err:
                logger.debug(f"[v19.34.183 wrong-side-stop] skipped for {symbol}: {_ws_err}")

            # ── v325 HSBG — detector-stop horizon cap (scalp/intraday) ─
            # Detector-supplied stops bypass calculate_atr_based_stop, so
            # a structurally wide stop (e.g. below a daily swing low)
            # re-creates the exact geometry the PT-reachability probe
            # condemned: ~1.3-2.5× DAILY ATR on a position that lives
            # minutes-to-hours. Cap (tighten-only) the distance at
            # HSBG_DETECTOR_STOP_CAP_MULT × the canonical horizon stop.
            # Multi-day styles untouched (their v183 5% cap exists).
            hsbg_stop_cap_meta = None
            try:
                if (self._hsbg_enabled() and stop_price and entry_price
                        and hsbg_frac < 1.0 and atr and atr > 0):
                    import os as _os_hsbg
                    try:
                        _cap_mult = float(_os_hsbg.environ.get(
                            "HSBG_DETECTOR_STOP_CAP_MULT", "1.5"))
                    except (TypeError, ValueError):
                        _cap_mult = 1.5
                    _canon = self.calculate_atr_based_stop(
                        float(entry_price), direction, float(atr), setup_type, bot,
                        trade_style=hsbg_style,
                    )
                    _canon_dist = abs(float(entry_price) - float(_canon))
                    _dist = abs(float(entry_price) - float(stop_price))
                    _cap_dist = _canon_dist * _cap_mult
                    if _cap_dist > 0 and _dist > _cap_dist:
                        _is_long = (direction == TradeDirection.LONG)
                        _new_stop = (entry_price - _cap_dist) if _is_long else (entry_price + _cap_dist)
                        logger.info(
                            "✂️ [v325 HSBG] %s %s detector stop Δ$%.4f (%.2f%% of "
                            "entry) exceeds horizon cap Δ$%.4f — tightened → $%.4f",
                            symbol, hsbg_style, _dist,
                            _dist / entry_price * 100.0, _cap_dist, _new_stop,
                        )
                        hsbg_stop_cap_meta = {
                            "applied": True,
                            "original_stop": round(float(stop_price), 4),
                            "capped_stop": round(_new_stop, 4),
                            "cap_mult": _cap_mult,
                            "canon_dist": round(_canon_dist, 4),
                        }
                        stop_price = _new_stop
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "info",
                                "event": "hsbg_stop_capped",
                                "symbol": symbol,
                                "text": (
                                    f"✂️ {symbol} {hsbg_style} stop "
                                    f"{_dist/entry_price*100:.1f}% → "
                                    f"{_cap_dist/entry_price*100:.1f}% (horizon cap) — "
                                    f"bracket sized for its actual hold window"
                                ),
                                "metadata": {"source": "opportunity_evaluator",
                                             "guard": "v325_hsbg_stop_cap",
                                             **hsbg_stop_cap_meta},
                            })
                        except Exception:
                            pass
            except Exception as _hsbg_cap_err:
                logger.debug("[v325 HSBG] detector-stop cap skipped: %s", _hsbg_cap_err)
''',
    ),
    # ── C5a/b/c: pass trade_style at the evaluator call sites ─────────
    (
        "callsite_initial_stop",
        '''            # Calculate ATR-based stop if not provided
            if not stop_price:
                stop_price = self.calculate_atr_based_stop(entry_price, direction, atr, setup_type, bot)
''',
        '''            # Calculate ATR-based stop if not provided
            if not stop_price:
                stop_price = self.calculate_atr_based_stop(
                    entry_price, direction, atr, setup_type, bot,
                    trade_style=hsbg_style,  # v325 HSBG
                )
''',
    ),
    (
        "callsite_wrong_side",
        '''                        _orig_ws = float(stop_price)
                        stop_price = self.calculate_atr_based_stop(
                            entry_price, direction, atr, setup_type, bot
                        )
''',
        '''                        _orig_ws = float(stop_price)
                        stop_price = self.calculate_atr_based_stop(
                            entry_price, direction, atr, setup_type, bot,
                            trade_style=hsbg_style,  # v325 HSBG
                        )
''',
    ),
    (
        "callsite_stop_floor_recompute",
        '''                        _orig_stop = float(stop_price)
                        _new_stop = self.calculate_atr_based_stop(
                            float(entry_price), direction, float(atr), setup_type, bot,
                        )
''',
        '''                        _orig_stop = float(stop_price)
                        _new_stop = self.calculate_atr_based_stop(
                            float(entry_price), direction, float(atr), setup_type, bot,
                            trade_style=hsbg_style,  # v325 HSBG
                        )
''',
    ),
    # ── C6: stop-floor threshold scaled by the horizon fraction ───────
    (
        "stop_floor_horizon_threshold",
        '''                    _distance = abs(float(entry_price) - float(stop_price))
                    _threshold = _floor_mult * float(atr)
''',
        '''                    _distance = abs(float(entry_price) - float(stop_price))
                    # v325 HSBG — floor measured on the horizon-scaled
                    # basis, otherwise a 0.3×DAILY-ATR floor would undo
                    # the scalp/intraday tightening every time.
                    _threshold = _floor_mult * float(atr) * (hsbg_frac or 1.0)
''',
    ),
    # ── C7: PT reachability stamp + gate (after target-snap) ──────────
    (
        "reach_gate",
        '''            except Exception as exc:
                logger.debug(f"target-snap skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")
''',
        '''            except Exception as exc:
                logger.debug(f"target-snap skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # ── v325 HSBG — PT reachability stamp + gate ───────────────
            # Stamp every trade with its geometry-vs-time ratio; warn on
            # borderline brackets; hard-block ones that are mathematically
            # configured to fail (PT1 needs >1.5× the price travel the
            # hold window statistically provides). Post-v325 geometry
            # lands ~0.4-0.8× — the block is a tripwire against future
            # regressions (bad detector stop / corrupt ATR), not a
            # routine filter. HSBG_REACH_GATE_MODE=warn disables blocking.
            hsbg_meta = None
            try:
                if atr and atr > 0 and target_prices and entry_price:
                    import os as _os_reach
                    _envelope = self._hsbg_reach_envelope(float(atr), hsbg_style)
                    _pt1_dist = abs(float(target_prices[0]) - float(entry_price))
                    _stop_dist = abs(float(entry_price) - float(stop_price)) if stop_price else 0.0
                    _ratio = (_pt1_dist / _envelope) if _envelope > 0 else None
                    hsbg_meta = {
                        "style": hsbg_style,
                        "frac": round(hsbg_frac, 4),
                        "atr_daily": round(float(atr), 6),
                        "atr_source": hsbg_atr_meta.get("source"),
                        "hold_minutes": round(self._hsbg_hold_minutes(hsbg_style), 1),
                        "reach_envelope": round(_envelope, 4),
                        "stop_env_ratio": round(_stop_dist / _envelope, 4) if _envelope > 0 else None,
                        "pt1_env_ratio": round(_ratio, 4) if _ratio is not None else None,
                        "stop_cap": hsbg_stop_cap_meta,
                    }
                    try:
                        _warn_at = float(_os_reach.environ.get("HSBG_REACH_WARN_RATIO", "0.85"))
                    except (TypeError, ValueError):
                        _warn_at = 0.85
                    try:
                        _block_at = float(_os_reach.environ.get("HSBG_REACH_BLOCK_RATIO", "1.5"))
                    except (TypeError, ValueError):
                        _block_at = 1.5
                    _gate_mode = str(_os_reach.environ.get(
                        "HSBG_REACH_GATE_MODE", "block")).strip().lower()
                    if (_ratio is not None and _ratio > _block_at
                            and _gate_mode == "block" and self._hsbg_enabled()):
                        logger.warning(
                            "🚫 [v325 HSBG reach-gate] Blocking %s %s — PT1 needs "
                            "%.2fx the expected price travel for a %s hold "
                            "(PT1 Δ$%.2f vs envelope $%.2f).",
                            symbol, setup_type, _ratio, hsbg_style,
                            _pt1_dist, _envelope,
                        )
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "rejection",
                                "event": "hsbg_reach_gate_block",
                                "symbol": symbol,
                                "text": (
                                    f"🚫 {symbol} {setup_type} blocked — PT1 at "
                                    f"{_ratio:.1f}× reach ({hsbg_style} hold, envelope "
                                    f"${_envelope:.2f}). Unreachable bracket geometry."
                                ),
                                "metadata": {"source": "opportunity_evaluator",
                                             **hsbg_meta},
                            })
                        except Exception:
                            pass
                        try:
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type,
                                direction=direction_str,
                                reason_code="hsbg_pt_unreachable",
                                context=hsbg_meta,
                            )
                        except Exception:
                            pass
                        return None
                    if _ratio is not None and _ratio > _warn_at:
                        logger.info(
                            "⚠️ [v325 HSBG reach-gate] %s %s borderline geometry — "
                            "PT1 at %.2fx reach (warn>%.2f).",
                            symbol, setup_type, _ratio, _warn_at,
                        )
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "warning",
                                "event": "hsbg_reach_gate_warn",
                                "symbol": symbol,
                                "text": (
                                    f"⚠️ {symbol} PT1 at {_ratio:.2f}× reach for a "
                                    f"{hsbg_style} hold — borderline bracket geometry"
                                ),
                                "metadata": {"source": "opportunity_evaluator",
                                             **hsbg_meta},
                            })
                        except Exception:
                            pass
            except Exception as _reach_err:
                logger.debug("[v325 HSBG] reach gate skipped: %s", _reach_err)
''',
    ),
    # ── C8: stamp hsbg meta into entry_context.multipliers ────────────
    (
        "entry_context_stamp",
        '''                    multipliers_meta={
                        "position": position_multipliers,
                        "stop_guard": stop_guard_meta,
                        "target_snap": target_snap_meta,
                    },
''',
        '''                    multipliers_meta={
                        "position": position_multipliers,
                        "stop_guard": stop_guard_meta,
                        "target_snap": target_snap_meta,
                        # v325 — geometry/reachability stamps (atr basis,
                        # horizon frac, reach envelope, pt1_env_ratio).
                        "hsbg": hsbg_meta,
                    },
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v325_hsbg.py"

TEST_CONTENT = '''"""v325 HSBG — Horizon-Scaled Bracket Geometry unit + static tests."""
import os
import sys
import py_compile
from pathlib import Path

import pytest


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services.opportunity_evaluator import OpportunityEvaluator  # noqa: E402

EV = OpportunityEvaluator()
SRC = (ROOT / "backend" / "services" / "opportunity_evaluator.py").read_text()


class _RiskParams:
    min_atr_multiplier = 1.0
    max_atr_multiplier = 3.0
    base_atr_multiplier = 1.5


class _Bot:
    risk_params = _RiskParams()
    _db = None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("HSBG_ENABLED", "HSBG_SCALP_FRAC", "HSBG_INTRADAY_FRAC",
              "HSBG_MIN_STOP_PCT_SCALP", "HSBG_MIN_STOP_PCT_INTRADAY",
              "SCALP_DECAY_MINUTES"):
        monkeypatch.delenv(k, raising=False)


# ── helpers ──────────────────────────────────────────────────────────

def test_frac_defaults():
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("scalp") - 0.39) < 1e-9
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("intraday") - 0.35) < 1e-9
    for s in ("swing", "multi_day", "position", "investment", ""):
        assert OpportunityEvaluator._hsbg_horizon_frac(s) == 1.0


def test_frac_env_override(monkeypatch):
    monkeypatch.setenv("HSBG_SCALP_FRAC", "0.5")
    assert abs(OpportunityEvaluator._hsbg_horizon_frac("scalp") - 0.5) < 1e-9


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("HSBG_ENABLED", "0")
    assert OpportunityEvaluator._hsbg_horizon_frac("scalp") == 1.0
    assert OpportunityEvaluator._hsbg_horizon_frac("intraday") == 1.0


def test_hold_minutes_multiday():
    assert OpportunityEvaluator._hsbg_hold_minutes("swing") == 10 * 390.0
    assert OpportunityEvaluator._hsbg_hold_minutes("position") == 30 * 390.0
    assert OpportunityEvaluator._hsbg_hold_minutes("investment") == 90 * 390.0


def test_hold_minutes_scalp_capped():
    assert OpportunityEvaluator._hsbg_hold_minutes("scalp") <= 60.0


def test_reach_envelope_math():
    # Full-session intraday hold from a weekend perspective: hold could be
    # 390 (weekend/premarket) or less intraday — envelope must be
    # daily_atr * sqrt(hold/390) <= daily_atr for intraday.
    env = OpportunityEvaluator._hsbg_reach_envelope(2.0, "intraday")
    assert 0 < env <= 2.0
    # Scalp at <=60min: <= 2.0 * sqrt(60/390) ≈ 0.785
    env_s = OpportunityEvaluator._hsbg_reach_envelope(2.0, "scalp")
    assert env_s <= 2.0 * ((60.0 / 390.0) ** 0.5) + 1e-9
    # Swing: sqrt(10) ≈ 3.16x daily
    env_sw = OpportunityEvaluator._hsbg_reach_envelope(2.0, "swing")
    assert abs(env_sw - 2.0 * (10 ** 0.5)) < 1e-6


# ── style resolution ─────────────────────────────────────────────────

def test_style_scalp_setup_wins():
    assert OpportunityEvaluator._resolve_geometry_style({}, "nine_ema_scalp") == "scalp"
    assert OpportunityEvaluator._resolve_geometry_style(None, "scalp") == "scalp"


def test_style_explicit_multiday_kept():
    a = {"trade_style": "position"}
    assert OpportunityEvaluator._resolve_geometry_style(a, "stage_2_breakout") == "position"


def test_style_generic_defaults_intraday():
    assert OpportunityEvaluator._resolve_geometry_style({}, "no_such_setup_xyz") == "intraday"
    assert OpportunityEvaluator._resolve_geometry_style(
        {"trade_style": "trade_2_hold"}, "no_such_setup_xyz") == "intraday"


# ── stop math ────────────────────────────────────────────────────────

def test_scalp_stop_horizon_scaled():
    # atr=3, entry=100, 'scalp' mult=0.5 → raw Δ=1.5 → ×0.39 = 0.585
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0, "scalp", _Bot(),
                                       trade_style="scalp")
    assert abs(stop - (100.0 - 0.585)) < 1e-6


def test_intraday_stop_horizon_scaled():
    # vwap_continuation mult=1.25 → raw Δ=3.75 → ×0.35 = 1.3125
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0,
                                       "vwap_continuation", _Bot(),
                                       trade_style="intraday")
    assert abs(stop - (100.0 - 1.3125)) < 1e-6


def test_swing_stop_unchanged():
    # breakout mult=1.5 → Δ=4.5 regardless of HSBG
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0,
                                       "breakout", _Bot(), trade_style="swing")
    assert abs(stop - 95.5) < 1e-6


def test_legacy_callers_without_style_unchanged():
    # /retune-stop feeds a 5-min ATR and omits trade_style → exact old math.
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 2.0, "scalp", _Bot())
    assert abs(stop - 99.0) < 1e-6  # 0.5 × 2.0, no horizon scaling


def test_min_stop_pct_floor(monkeypatch):
    # Force a microscopic scaled stop; floor must catch it at 0.15%.
    monkeypatch.setenv("HSBG_SCALP_FRAC", "0.05")
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 0.5, "scalp", _Bot(),
                                       trade_style="scalp")
    # raw Δ = 0.25 → ×0.05 = 0.0125 < floor 0.15 → Δ = 0.15
    assert abs(stop - 99.85) < 1e-6


def test_kill_switch_restores_old_stop(monkeypatch):
    monkeypatch.setenv("HSBG_ENABLED", "0")
    stop = EV.calculate_atr_based_stop(100.0, _direction_long(), 3.0, "scalp", _Bot(),
                                       trade_style="scalp")
    assert abs(stop - 98.5) < 1e-6  # 0.5 × 3.0, unscaled


def _direction_long():
    from services.trading_bot_service import TradeDirection
    return TradeDirection.LONG


# ── static assertions ────────────────────────────────────────────────

def test_compiles():
    py_compile.compile(
        str(ROOT / "backend" / "services" / "opportunity_evaluator.py"), doraise=True)


def test_reach_gate_present():
    assert "hsbg_pt_unreachable" in SRC
    assert "HSBG_REACH_BLOCK_RATIO" in SRC
    assert "hsbg_reach_gate_block" in SRC
    assert '"hsbg": hsbg_meta' in SRC


def test_detector_cap_present():
    assert "HSBG_DETECTOR_STOP_CAP_MULT" in SRC
    assert "hsbg_stop_capped" in SRC


def test_stop_floor_scaled():
    assert "_floor_mult * float(atr) * (hsbg_frac or 1.0)" in SRC


def test_atr_basis_normalized():
    assert "symbol_adv_cache" in SRC
    assert "fallback_2pct" in SRC
'''


def _find_repo_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / EVAL_REL).exists():
            return cand
    print("FATAL: run from repo root (backend/ not found)")
    sys.exit(1)


def main() -> None:
    root = _find_repo_root()
    print(f"repo root: {root}\n── {EVAL_REL}")
    path = root / EVAL_REL
    text = path.read_text()
    changed = False
    for name, old, new in CHUNKS:
        if new in text:
            print(f"  [SKIP] {name} — already applied")
            continue
        if old not in text:
            print(f"  [FAIL] {name} — anchor not found. File drifted. ABORTING (no partial writes).")
            sys.exit(2)
        if text.count(old) != 1:
            print(f"  [FAIL] {name} — anchor not unique ({text.count(old)}). ABORTING.")
            sys.exit(2)
        text = text.replace(old, new, 1)
        changed = True
        print(f"  [OK]   {name}")
    if changed:
        path.write_text(text)

    try:
        py_compile.compile(str(path), doraise=True)
        print("\n[OK]   py_compile passed")
    except py_compile.PyCompileError as exc:
        print(f"\n[FAIL] py_compile FAILED: {exc}")
        sys.exit(3)

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"[OK]   wrote {TEST_REL}")

    print("""
v325 APPLIED.

Next steps:
  1. .venv/bin/python -m pytest backend/tests/test_v325_hsbg.py -q
  2. git add -A && git commit -m "v325: horizon-scaled bracket geometry + reach gate" && git push
  3. Restart the app (commit FIRST — StartTrading.bat runs `git checkout -- .`)
  4. Watch the stream for:
       [v325 HSBG] ... stop horizon-scaled ...     (every scalp/intraday eval)
       ✂️ ... horizon cap                            (wide detector stops tightened)
       ⚠️ ... borderline bracket geometry            (PT1 > 0.85× reach)
       🚫 ... Unreachable bracket geometry           (PT1 > 1.5× reach — should be rare)
  5. After a few sessions, re-run diag_pt_reachability.py — PT1 touch-rate
     should move off 0%, and bot_trades.entry_context.multipliers.hsbg
     carries the stamps for before/after comparison.

Kill switch: HSBG_ENABLED=0 in backend/.env reverts all geometry changes.
""")


if __name__ == "__main__":
    main()
