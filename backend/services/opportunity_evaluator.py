"""
Opportunity Evaluator — Extracted from trading_bot_service.py

The core trade evaluation pipeline:
1. Smart Strategy Filtering (historical performance gate)
2. AI Confidence Gate (regime + model consensus)
3. Intelligence Gathering (news, technicals, institutional)
4. Position Sizing (volatility + regime adjusted)
5. AI Trade Consultation
6. Trade Object Creation with rich entry context
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


# ── v322u — Taxonomy coherence: timeframe follows trade_style ────────
# STRATEGY_CONFIG[setup_type]["timeframe"] and the scanner-stamped
# trade_style (trade_style_classifier.SETUP_TO_STYLE / SMB registry
# default_style) are two PARALLEL per-setup tables that drift
# independently. Probe 2026-06-11 found bot_trades rows with
# style=swing + tf=intraday; the inverse (style=scalp + tf=intraday)
# silently exempts scalps from the v19.34.171 scalp-decay sweep, and
# a swing mislabeled tf=scalp would get wrongly flattened at 60 min.
# The style is the policy-bearing axis (order_policy_registry, EOD
# policy and sizing key on it), so on conflict the style-derived
# horizon wins. Legacy/generic SMB styles (trade_2_hold, move_2_move,
# a_plus, reconciled, ...) carry no horizon info → table value kept.
STYLE_TO_TIMEFRAME: Dict[str, str] = {
    "scalp": "scalp",
    "intraday": "intraday",
    "multi_day": "swing",
    "swing": "swing",
    "position": "position",
    "investment": "position",
}


def reconcile_timeframe_with_style(timeframe_str, trade_style) -> Tuple[str, bool]:
    """v322u — Return (timeframe, changed). Style-derived horizon wins
    on conflict; styles without a canonical horizon leave it untouched."""
    style = str(trade_style or "").strip().lower()
    tf_from_style = STYLE_TO_TIMEFRAME.get(style)
    if tf_from_style and tf_from_style != str(timeframe_str or "").lower():
        return tf_from_style, True
    return timeframe_str, False


# ── v19.34.247 (2026-06-03) — EOD no-new-entries cut resolver ───────
# Pure helper so the EOD gate's time math is unit-testable and its
# operator-facing strings stay in lockstep with the bot's ACTUAL
# EOD-flatten time (15:45 ET since v19.34.154) instead of a stale
# hardcoded 15:55.
def _eod_fmt12(h: int, m: int) -> str:
    """Format an ET (24h) time as a compact 12h '3:45pm'-style string."""
    hr = h - 12 if h > 12 else (h if h else 12)
    return f"{hr}:{m:02d}pm"


def _eod_cut_times(eod_hour: int, eod_minute: int, grace_min: int) -> Dict[str, Any]:
    """Resolve HARD/SOFT no-new-entry cuts from the bot's EOD-flatten time.

    HARD cut == the flatten time (no fresh entry once flatten starts).
    SOFT cut == HARD − grace (warn-only late-momentum window).
    """
    hard_cut = int(eod_hour) * 60 + int(eod_minute)
    soft_cut = hard_cut - max(0, int(grace_min))
    soft_h, soft_m = divmod(soft_cut, 60)
    return {
        "hard_cut": hard_cut,
        "soft_cut": soft_cut,
        "hard_str": _eod_fmt12(int(eod_hour), int(eod_minute)),
        "soft_str": _eod_fmt12(soft_h, soft_m),
        "hard_hhmm": f"{int(eod_hour):02d}:{int(eod_minute):02d}",
        "soft_hhmm": f"{soft_h:02d}:{soft_m:02d}",
    }



# ── v19.34.156 (P3-A) — Grade-based position-size multiplier ────────
# A-grade setups trade full size; lower grades downscale proportionally.
# Operator choices:
#   Q1b: D=0.1× (vanishingly small, real money for learning — not skip)
#   Q2b: unknown/missing → treated as D (strict, no silent default-to-B)
# v19.34.228 — recalibrated for the percentile-graded TQS (grades now spread
# A/B/C/D/F by rank instead of 100% C). Conservative + risk-neutral on average:
# C unchanged at 0.3× so the mean position size stays ~today's, just
# concentrated into higher-conviction setups. F added explicitly (was falling
# through to D's default).
# Tunable via env: `POSITION_SIZE_GRADE_{A,B,C,D,F}_MULT`.
_GRADE_MULTIPLIER_DEFAULTS = {
    "A": 1.0,
    "B": 0.6,
    "C": 0.3,
    "D": 0.15,
    "F": 0.1,
}


def _resolve_grade_multiplier(grade: Optional[str]) -> Tuple[float, str]:
    """Return (multiplier, normalized_grade) for the given grade string.

    Normalization rules:
      • None / empty / "?" / non-string → treated as "D" (strict default
        per operator choice Q2b).
      • Letter is upper-cased and only the first character considered
        (so "A-", "A+", "a", "A grade" all collapse to "A").
      • Letters outside {A,B,C,D,F} → "D" (strict).
    """
    import os as _os

    def _envf(key: str, default: float) -> float:
        v = _os.environ.get(key)
        if v in (None, ""):
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    table = {
        "A": _envf("POSITION_SIZE_GRADE_A_MULT", _GRADE_MULTIPLIER_DEFAULTS["A"]),
        "B": _envf("POSITION_SIZE_GRADE_B_MULT", _GRADE_MULTIPLIER_DEFAULTS["B"]),
        "C": _envf("POSITION_SIZE_GRADE_C_MULT", _GRADE_MULTIPLIER_DEFAULTS["C"]),
        "D": _envf("POSITION_SIZE_GRADE_D_MULT", _GRADE_MULTIPLIER_DEFAULTS["D"]),
        "F": _envf("POSITION_SIZE_GRADE_F_MULT", _GRADE_MULTIPLIER_DEFAULTS["F"]),
    }
    if not isinstance(grade, str) or not grade.strip():
        return (table["D"], "D")
    g = grade.strip()[0].upper()
    if g not in table:
        return (table["D"], "D")
    return (table[g], g)



class OpportunityEvaluator:
    """Evaluates scanner alerts and builds fully-qualified trade objects."""

    async def evaluate_opportunity(self, alert: Dict, bot: 'TradingBotService') -> Optional['BotTrade']:
        """Evaluate an alert and create a trade if it meets criteria"""
        from services.trading_bot_service import (
            BotMode, BotTrade, TradeDirection, TradeStatus, TradeTimeframe,
            STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG,
        )

        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT


            # ── v19.34.320 — Daily-bar premarket gate ── BEGIN ────────
            # Suppress daily-bar-consuming setups before the cutoff ET
            # time. Today's daily bar isn't mature until the first 30
            # min of RTH have passed (~10:00 ET). Setups whose
            # trade_style in multi_day/swing/position/investment OR
            # setup_type in daily-bar list read TODAY's daily OHLCV ->
            # pre-cutoff fires consume incomplete/whippy data.
            #
            # Env: V320_DAILY_BAR_GATE_POLICY in {block,observe,off}
            #      V320_DAILY_BAR_CUTOFF_ET (HH:MM America/New_York)
            #      V320_DAILY_BAR_STYLES   (comma list)
            #      V320_DAILY_BAR_SETUPS   (comma list)
            try:
                import os as _os_v320
                _v320_policy = (_os_v320.environ.get(
                    "V320_DAILY_BAR_GATE_POLICY", "block")
                    or "block").lower().strip()
                if _v320_policy not in ("block", "observe", "off"):
                    _v320_policy = "block"
                if _v320_policy != "off":
                    from zoneinfo import ZoneInfo as _ZI_v320
                    _v320_cutoff = (_os_v320.environ.get(
                        "V320_DAILY_BAR_CUTOFF_ET", "10:00") or "10:00")
                    _h, _m = _v320_cutoff.split(":")
                    _cutoff_min = int(_h) * 60 + int(_m)
                    _now_et = datetime.now(_ZI_v320("America/New_York"))
                    _now_min = _now_et.hour * 60 + _now_et.minute
                    if _now_min < _cutoff_min:
                        _styles_env = _os_v320.environ.get(
                            "V320_DAILY_BAR_STYLES",
                            "multi_day,swing,position,investment")
                        _setups_env = _os_v320.environ.get(
                            "V320_DAILY_BAR_SETUPS",
                            "daily_breakout,rs_leader_break,"
                            "stage_2_breakout,power_trend_stack,"
                            "pocket_pivot,three_week_tight,"
                            "accumulation_entry,daily_squeeze")
                        _v320_styles = {s.strip().lower() for s in _styles_env.split(",") if s.strip()}
                        _v320_setups = {s.strip().lower() for s in _setups_env.split(",") if s.strip()}
                        _alert_style = (alert.get("trade_style") or "").lower().strip()
                        _alert_setup = (setup_type or "").lower().strip()
                        _hit_style = _alert_style in _v320_styles
                        _hit_setup = _alert_setup in _v320_setups
                        if _hit_style or _hit_setup:
                            if _v320_policy == "block":
                                try:
                                    bot.record_rejection(
                                        symbol=symbol, setup_type=setup_type,
                                        direction=direction_str,
                                        reason_code="v320_daily_bar_premarket_gate",
                                        context={
                                            "policy": "v19.34.320_premarket_gate",
                                            "cutoff_et": _v320_cutoff,
                                            "now_et": _now_et.strftime("%H:%M"),
                                            "matched_style": _alert_style if _hit_style else None,
                                            "matched_setup": _alert_setup if _hit_setup else None,
                                        },
                                    )
                                except Exception:
                                    pass
                                logger.info(
                                    "\U0001f6ab [v19.34.320] daily-bar gate BLOCK "
                                    "%s/%s (style=%s, setup=%s, now=%s ET, cutoff=%s ET)",
                                    symbol, setup_type, _alert_style or "-",
                                    _alert_setup or "-",
                                    _now_et.strftime("%H:%M"), _v320_cutoff,
                                )
                                return None
                            elif _v320_policy == "observe":
                                logger.info(
                                    "\U0001f441\ufe0f [v19.34.320 OBSERVE] daily-bar gate would BLOCK "
                                    "%s/%s (style=%s, setup=%s, now=%s ET)",
                                    symbol, setup_type, _alert_style or "-",
                                    _alert_setup or "-", _now_et.strftime("%H:%M"),
                                )
            except Exception as _v320_err:
                logger.debug("v320 daily-bar gate threw (allowing through): %s", _v320_err)
            # ── v19.34.320 — Daily-bar premarket gate ── END ──────────

            # ── v19.34.173 — Setup-grade F-gate ──────────────────────
            # Block alerts whose setup_type is graded F over the
            # rolling 30d window. The previous behaviour was
            # observe-only (label-only, no block). Operator confirmed
            # default = block. Env-tunable to "micro" (keep current
            # 0.1x sizing + mark `learning_only=True`) or "full"
            # (ignore grade — pre-v173 behaviour).
            #
            # Trades dropped here land in `trade_drops` with reason
            # code `setup_grade_f_block` so the operator can see how
            # many alerts the gate filtered.
            try:
                import os as _os_fg
                _f_policy = (_os_fg.environ.get("F_GRADE_POLICY", "block") or "block").lower().strip()
                if _f_policy not in ("block", "micro", "full"):
                    _f_policy = "block"
                if _f_policy != "full" and setup_type:
                    from services.setup_grading_service import get_setup_grading_service
                    _grade_svc = get_setup_grading_service()
                    _setup_grade = _grade_svc.get_grade_warning(setup_type)
                    if _setup_grade == "F":
                        if _f_policy == "block":
                            try:
                                bot.record_rejection(
                                    symbol=symbol, setup_type=setup_type,
                                    direction=direction_str,
                                    reason_code="setup_grade_f_block",
                                    context={
                                        "policy": "v19.34.173_f_gate_block",
                                        "rolling_grade": "F",
                                        "f_grade_policy_env": _f_policy,
                                    },
                                )
                            except Exception:
                                pass
                            logger.info(
                                "🚫 [v19.34.173 F-GATE] Blocking %s %s — setup graded F "
                                "(F_GRADE_POLICY=block). Set F_GRADE_POLICY=micro to "
                                "trade at 0.1x size with learning_only=True flag.",
                                symbol, setup_type,
                            )
                            return None
                        elif _f_policy == "micro":
                            # Continue evaluating; tag the alert so the
                            # downstream sizing path AND the grading
                            # aggregator both know this is a learning-only
                            # micro trade (excluded from avg_R computation
                            # to avoid the commission-poisoned feedback loop).
                            alert["learning_only"] = True
                            logger.info(
                                "🧪 [v19.34.173 F-MICRO] %s %s graded F — trading as "
                                "learning_only at 0.1x. Excluded from grade aggregation.",
                                symbol, setup_type,
                            )
            except Exception as _fg_err:
                logger.debug(f"v19.34.173 F-gate check error: {_fg_err}")

            # ── v19.34.194 — Volatility floor + cash-equivalent blocklist ──
            # Stops ultra-low-volatility tickers (e.g. $BIL and other T-bill /
            # ultra-short ETFs) from ever becoming trades. They clear the ADV
            # liquidity floor but have ~0 daily range, so detectors fire on
            # noise and the R:R ladder produces absurd targets (the BIL R:R
            # 0.02 incident). Two hard gates, both fail-OPEN on any error:
            #   1. CASH_EQUIVALENT_BLOCKLIST — explicit symbol blocklist
            #      (primary tool; named T-bill / ultra-short ETFs).
            #   2. MIN_TRADE_ATR_PCT — daily ATR% floor as a FRACTION
            #      (default 0.003 = 0.3%; catches unlisted junk but is
            #      deliberately below SPY/QQQ ~0.7-1.4% so index ETFs pass).
            #      ATR% sourced from alert atr/price, else the collector's
            #      `symbol_adv_cache.atr_pct`. 0 disables. Blocks ONLY when a
            #      measurement is available.
            # Drops land in `trade_drops` via record_rejection.
            try:
                import os as _os_q9
                _sym_u = (symbol or "").upper()

                # 1) Cash-equivalent / ultra-short ETF blocklist.
                _bl_raw = _os_q9.environ.get(
                    "CASH_EQUIVALENT_BLOCKLIST",
                    "BIL,BILS,SGOV,SHV,SHY,ICSH,GBIL,CLTL,USFR,TFLO,FLOT,"
                    "JPST,MINT,NEAR,GSY,VGSH,SCHO,SPTS,BSV,FLRN,TBIL,XHLF",
                )
                _blocklist = {s.strip().upper() for s in _bl_raw.split(",") if s.strip()}
                if _sym_u and _sym_u in _blocklist:
                    logger.info(
                        "🚫 [v19.34.194 cash-equiv] Blocking %s — cash-equivalent "
                        "/ ultra-short ETF (CASH_EQUIVALENT_BLOCKLIST).", _sym_u,
                    )
                    try:
                        bot.record_rejection(
                            symbol=symbol, setup_type=setup_type,
                            direction=direction_str,
                            reason_code="cash_equivalent_blocklist",
                            context={"blocklist": "v19.34.194"},
                        )
                    except Exception:
                        pass
                    return None

                # 2) Daily ATR% floor (fraction).
                try:
                    _min_atr_pct = float(_os_q9.environ.get("MIN_TRADE_ATR_PCT", "0.003"))
                except (TypeError, ValueError):
                    _min_atr_pct = 0.003
                if _min_atr_pct > 0:
                    _atr_pct = None
                    _atr = (alert.get("atr") or alert.get("atr_14")
                            or alert.get("atr_value"))
                    _px = (alert.get("price") or alert.get("current_price")
                           or alert.get("entry_price") or alert.get("trigger_price"))
                    try:
                        if _atr and _px and float(_px) > 0:
                            _atr_pct = abs(float(_atr)) / float(_px)
                    except (TypeError, ValueError):
                        _atr_pct = None
                    if _atr_pct is None:
                        # Fall back to the collector's daily ATR% (fraction).
                        _db_q9 = getattr(bot, "_db", None)
                        if _db_q9 is None:
                            _db_q9 = getattr(bot, "db", None)
                        if _db_q9 is not None and _sym_u:
                            try:
                                _doc = _db_q9["symbol_adv_cache"].find_one(
                                    {"symbol": _sym_u}, {"atr_pct": 1, "_id": 0})
                                if _doc and _doc.get("atr_pct") is not None:
                                    _atr_pct = float(_doc["atr_pct"])
                            except Exception:
                                _atr_pct = None
                    # Block ONLY when we have a measurement (fail-open otherwise).
                    if _atr_pct is not None and _atr_pct < _min_atr_pct:
                        logger.info(
                            "🚫 [v19.34.194 atr-floor] Blocking %s %s — daily "
                            "ATR%% %.3f%% < floor %.3f%% (too quiet to trade).",
                            _sym_u, setup_type, _atr_pct * 100, _min_atr_pct * 100,
                        )
                        try:
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type,
                                direction=direction_str,
                                reason_code="atr_floor_too_low",
                                context={
                                    "atr_pct": round(_atr_pct, 6),
                                    "min_atr_pct": _min_atr_pct,
                                },
                            )
                        except Exception:
                            pass
                        return None
            except Exception as _q9_err:
                logger.debug(
                    "[v19.34.194 vol-floor] gate crashed (fail-open): %s", _q9_err,
                )

            # ── v19.34.323 — SHORT-FADE eligibility gate (v334 stop-overrun) ──
            # diag_v334 proved the catastrophic stop-overrun tail (~$23k of
            # $26k excess loss) is ~90% SHORTS and ~88% vwap_fade_short:
            # shorting STRENGTH on low-priced / illiquid names with absurdly
            # tight stops (WTI $2.84/2c stop->exit 3.21; PRCT $26.67/4c->27.02;
            # USO 0.03% stop). The stop engine fired correctly — the loss is
            # gap/squeeze slippage on a no-edge entry held overnight. Cheapest
            # bulletproof fix: never enter the danger profile. Two fail-OPEN
            # levers on SHORT fade/reversion setups only:
            #   1. MIN_SHORT_FADE_PRICE  (default $5)  — kills sub-$5 squeezers.
            #   2. MIN_SHORT_FADE_STOP_PCT (default 1.0%) — kills noise-stop
            #      fades (stop distance < pct of price) that any squeeze blows
            #      straight through.
            # Env: SHORT_FADE_GATE_POLICY in {block,observe,off} (default block);
            #      SHORT_FADE_SETUP_KEYWORDS (csv substring match on setup_type).
            # Drops land in `trade_drops` via record_rejection.
            try:
                import os as _os_sf
                _sf_policy = (_os_sf.environ.get(
                    "SHORT_FADE_GATE_POLICY", "block") or "block").lower()
                if _sf_policy != "off" and str(direction_str).lower().startswith("s"):
                    _sym_sf = (symbol or "").upper()
                    _su_l = str(setup_type or "").lower()
                    _kw_raw = _os_sf.environ.get(
                        "SHORT_FADE_SETUP_KEYWORDS",
                        "fade,bounce,reversion,rubber_band,off_sides,backside",
                    )
                    _kws = [k.strip() for k in _kw_raw.split(",") if k.strip()]
                    if any(k in _su_l for k in _kws):
                        _px_sf = (alert.get("price") or alert.get("current_price")
                                  or alert.get("entry_price")
                                  or alert.get("trigger_price"))
                        _stop_sf = (alert.get("stop_loss")
                                    or alert.get("stop_price"))
                        try:
                            _px_sf = float(_px_sf) if _px_sf else None
                        except (TypeError, ValueError):
                            _px_sf = None
                        try:
                            _stop_sf = float(_stop_sf) if _stop_sf else None
                        except (TypeError, ValueError):
                            _stop_sf = None
                        try:
                            _min_price = float(_os_sf.environ.get(
                                "MIN_SHORT_FADE_PRICE", "5.0"))
                        except (TypeError, ValueError):
                            _min_price = 5.0
                        try:
                            _min_stop_pct = float(_os_sf.environ.get(
                                "MIN_SHORT_FADE_STOP_PCT", "0.010"))
                        except (TypeError, ValueError):
                            _min_stop_pct = 0.010
                        _block_reason = None
                        _sf_ctx = {}
                        if (_px_sf is not None and _min_price > 0
                                and _px_sf < _min_price):
                            _block_reason = "short_fade_low_price"
                            _sf_ctx = {"price": round(_px_sf, 4),
                                       "min_price": _min_price}
                        elif (_px_sf and _stop_sf and _min_stop_pct > 0):
                            _sd_pct = abs(_stop_sf - _px_sf) / _px_sf
                            if _sd_pct < _min_stop_pct:
                                _block_reason = "short_fade_stop_too_tight"
                                _sf_ctx = {"stop_pct": round(_sd_pct, 5),
                                           "min_stop_pct": _min_stop_pct,
                                           "price": round(_px_sf, 4),
                                           "stop": round(_stop_sf, 4)}
                        if _block_reason:
                            logger.info(
                                "\U0001f6ab [v19.34.323 short-fade] %s %s %s — %s %s",
                                ("OBSERVE" if _sf_policy == "observe" else "BLOCK"),
                                _sym_sf, setup_type, _block_reason, _sf_ctx,
                            )
                            if _sf_policy != "observe":
                                try:
                                    bot.record_rejection(
                                        symbol=symbol, setup_type=setup_type,
                                        direction=direction_str,
                                        reason_code=_block_reason,
                                        context=_sf_ctx,
                                    )
                                except Exception:
                                    pass
                                return None
            except Exception as _sf_err:
                logger.debug(
                    "[v19.34.323 short-fade] gate crashed (fail-open): %s",
                    _sf_err,
                )

            # ── v19.34.44 — Stale Alert TTL (default 30s) ─────────────
            # Alerts that sit in the pipeline too long are no longer trading
            # the setup they detected. Kill them at the gate to save the IB
            # round-trip and surface pipeline lag in the Scanner Quality
            # Panel as `stale_alert_ttl`. Fail-OPEN on missing timestamp.
            try:
                import os as _os_ttl
                import time as _time_ttl
                _ttl_raw = _os_ttl.environ.get("STALE_ALERT_TTL_SECONDS", "30")
                try:
                    _ttl_secs = float(_ttl_raw) if _ttl_raw not in (None, "") else 30.0
                except (TypeError, ValueError):
                    _ttl_secs = 30.0
                if _ttl_secs > 0:
                    _triggered_unix = alert.get("triggered_at_unix")
                    if _triggered_unix is None:
                        _iso = alert.get("triggered_at")
                        if _iso:
                            try:
                                _triggered_unix = datetime.fromisoformat(
                                    str(_iso).replace("Z", "+00:00")
                                ).timestamp()
                            except (TypeError, ValueError):
                                _triggered_unix = None
                    # v402 — fail-CLOSED on missing/unparseable alert timestamp.
                    # Pre-fix this branch was skipped when no timestamp existed
                    # (fail-OPEN). STALE_ALERT_POLICY = block|observe|off.
                    _stale_policy = _os_ttl.environ.get(
                        "STALE_ALERT_POLICY", "block").strip().lower()
                    if _triggered_unix is None and _stale_policy in ("block", "observe"):
                        logger.warning(
                            "\U0001f552 [v402 stale-policy=%s] %s %s has NO usable "
                            "alert timestamp \u2014 treating as STALE.",
                            _stale_policy, symbol, setup_type,
                        )
                        if _stale_policy == "block":
                            _triggered_unix = _time_ttl.time() - (_ttl_secs + 1.0)
                    if _triggered_unix is not None:
                        try:
                            _age = _time_ttl.time() - float(_triggered_unix)
                        except (TypeError, ValueError):
                            _age = 0.0
                        if _age >= _ttl_secs:
                            logger.warning(
                                "🕒 [v19.34.44 stale-alert-ttl] Dropping %s %s — "
                                "alert age %.1fs ≥ TTL %.0fs.",
                                symbol, setup_type, _age, _ttl_secs,
                            )
                            try:
                                bot.record_rejection(
                                    symbol=symbol, setup_type=setup_type,
                                    direction=direction_str,
                                    reason_code="stale_alert_ttl",
                                    context={
                                        "alert_age_seconds": round(_age, 2),
                                        "ttl_seconds": _ttl_secs,
                                        "triggered_at_unix": _triggered_unix,
                                    },
                                )
                            except Exception:
                                pass
                            # v19.34.164: record_rejection now persists
                            # to `trade_drops` itself — explicit
                            # record_trade_drop call removed to avoid
                            # double-counting.
                            return None
            except Exception as _ttl_err:
                logger.debug(
                    "[v19.34.44 stale-alert-ttl] gate crashed (fail-open): %s",
                    _ttl_err,
                )

            # ── v19.34.88 — Per-(symbol, setup_base) post-stop cooldown ──
            # If this (symbol, setup_base) hit a stop_loss in the last
            # POST_STOP_COOLDOWN_MINUTES (default 30), refuse the new
            # entry. Setup-type normalisation drops _long/_short suffix
            # so the cooldown traps re-entries in either direction.
            #
            # Surfaced via record_rejection so the SIGNAL PASS pill
            # and rejection-analytics dashboard show the count.
            #
            # Origin: v19.34.87 setup_retro found 21 stops in 25min
            # across ETHU/CHWY/AJG/BALL on 2026-05-14 for -17.68R.
            # Fail-OPEN on any exception so a bug here can't lock the
            # bot out of trading.
            try:
                from services.post_stop_cooldown import get_registry
                _remaining = get_registry().seconds_remaining(symbol, setup_type)
                if _remaining is not None and _remaining > 0:
                    logger.warning(
                        "🧊 [v19.34.88 post-stop-cooldown] Refusing %s %s — "
                        "stopped in last %.0fs (cooldown %.0fs remaining).",
                        symbol, setup_type,
                        (1800.0 - _remaining), _remaining,
                    )
                    try:
                        bot.record_rejection(
                            symbol=symbol, setup_type=setup_type,
                            direction=direction_str,
                            reason_code="post_stop_cooldown",
                            context={
                                "cooldown_remaining_seconds": round(_remaining, 1),
                            },
                        )
                    except Exception:
                        pass
                    # v19.34.164: record_rejection now persists to
                    # `trade_drops` itself — explicit record_trade_drop
                    # call removed to avoid double-counting.
                    return None
            except Exception as _psc_err:
                logger.debug(
                    "[v19.34.88 post-stop-cooldown] gate crashed (fail-open): %s",
                    _psc_err,
                )

            # ── v19.34.123 — Per-(symbol, direction) open-exposure cap ────
            # Setup-type-AGNOSTIC. The Feb 2026 incident showed the bot
            # firing 28 separate RJF SHORT entries in 76 minutes because
            # the existing `(symbol, setup_type)` cooldown lets the
            # classifier cycle through 6+ setup_types on the same level
            # — each fresh bucket bypasses the others. This guard runs
            # FIRST and asks the simplest question: is there an existing
            # open canonical for this (symbol, direction)? If yes,
            # refuse the new entry regardless of setup_type.
            #
            # The "canonical" concept maps to ANY open trade in
            # `bot._open_trades` matching (symbol, direction). The
            # consolidator merges siblings into canonicals; this guard
            # ensures we don't even create the siblings in the first
            # place.
            #
            # Operator override: set `risk_params.allow_multiple_entries_per_symbol_dir`
            # to True to disable this guard (default False, the safe
            # post-incident behavior).
            allow_multi = bool(getattr(
                bot.risk_params, "allow_multiple_entries_per_symbol_dir", False,
            ))
            if not allow_multi:
                try:
                    existing_canonical = None
                    for _t in (bot._open_trades or {}).values():
                        _t_sym = (getattr(_t, "symbol", "") or "").upper()
                        _t_dir = getattr(_t, "direction", None)
                        _t_dir_v = getattr(_t_dir, "value", str(_t_dir) if _t_dir else "long").lower()
                        if _t_sym == (symbol or "").upper() and _t_dir_v == direction_str.lower():
                            existing_canonical = _t
                            break
                    if existing_canonical is not None:
                        _tid = getattr(existing_canonical, "id", "?")
                        logger.warning(
                            "🛑 [v19.34.123 sym-dir-cap] Refusing %s %s entry — "
                            "open canonical %s already exists for (%s, %s). "
                            "Setup_type=%s. Set allow_multiple_entries_per_symbol_dir=True to override.",
                            symbol, setup_type, _tid, symbol, direction_str, setup_type,
                        )
                        try:
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type,
                                direction=direction_str,
                                reason_code="symbol_direction_open_cap_v123",
                                context={
                                    "open_canonical_id": _tid,
                                    "open_canonical_setup": getattr(existing_canonical, "setup_type", None),
                                    "open_canonical_shares": getattr(existing_canonical, "shares", None),
                                    "policy": "v19.34.123_setup_agnostic_cap",
                                },
                            )
                        except Exception:
                            pass
                        return None
                except Exception as _cap_err:
                    logger.error(
                        "[v19.34.123 sym-dir-cap] guard crashed (allowing entry "
                        "as fail-open): %s", _cap_err,
                    )

            # ── v19.29 (2026-05-01) — EOD no-new-entries gate ────────
            # Operator caught LITE 12sh @ $902.77 entered at 3:59pm
            # 2026-05-01 with OCA bracket auto-cancelled at 4:00pm,
            # leaving raw long overnight w/ no protection.
            #
            # v19.34.247 (2026-06-03) — EOD-aware re-pin. The HARD cut
            # was a stale hardcoded 15:55, but the actual EOD-flatten
            # loop moved to 15:45 ET in v19.34.154 (12:55 on half-days).
            # That left a 15:45-15:55 hole where the bot could open a
            # FRESH entry *while the flatten loop was already running* —
            # exactly the unprotected-overnight risk this gate exists to
            # stop. HARD cut is now pinned to the bot's real EOD-flatten
            # time; SOFT cut = HARD − grace (env EOD_NO_ENTRY_GRACE_MIN,
            # default 10m), warn-only. All operator-facing text is built
            # from the resolved times so the banner never goes stale.
            try:
                import os as _os_eod
                from datetime import datetime as _dt_eod
                from zoneinfo import ZoneInfo as _ZI
                _et_now = _dt_eod.now(_ZI("America/New_York"))
                if _et_now.weekday() < 5:  # Mon-Fri only
                    _et_minutes = _et_now.hour * 60 + _et_now.minute
                    _is_half_day = _os_eod.environ.get(
                        "EOD_HALF_DAY_TODAY", ""
                    ).lower() in ("true", "1", "yes")
                    if _is_half_day:
                        _eod_h, _eod_m = 12, 55
                    else:
                        _eod_h = int(getattr(bot, "_eod_close_hour", 15) or 15)
                        _eod_m = int(getattr(bot, "_eod_close_minute", 45) or 45)
                    try:
                        _grace = int(_os_eod.environ.get("EOD_NO_ENTRY_GRACE_MIN", "10"))
                    except Exception:
                        _grace = 10
                    _cuts = _eod_cut_times(_eod_h, _eod_m, _grace)
                    HARD_CUT = _cuts["hard_cut"]
                    SOFT_CUT = _cuts["soft_cut"]
                    _hard_str = _cuts["hard_str"]
                    _soft_str = _cuts["soft_str"]
                    _hard_hhmm = _cuts["hard_hhmm"]
                    _soft_hhmm = _cuts["soft_hhmm"]

                    if _et_minutes >= HARD_CUT:
                        logger.warning(
                            "🛑 [v19.29 EOD-HARD-CUT] %s %s rejected at "
                            "%02d:%02d ET — past %s, EOD flatten window "
                            "owns the run into the close.",
                            symbol, setup_type, _et_now.hour, _et_now.minute,
                            _hard_str,
                        )
                        try:
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type,
                                direction=direction_str,
                                reason_code="eod_no_new_entries",
                                context={
                                    "et_time": _et_now.isoformat(),
                                    "policy": f"hard cut at {_hard_hhmm} ET",
                                },
                            )
                        except Exception:
                            pass
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "filter",
                                "event": "eod_no_new_entries_hard",
                                "symbol": symbol,
                                "text": (
                                    f"⏰ Passing on {symbol} {setup_type} — "
                                    f"past {_hard_str} ET, EOD flatten window "
                                    f"owns the run into the close."
                                ),
                                "metadata": {
                                    "policy": "v19.29_eod_hard_cut",
                                    "cutoff_et": _hard_hhmm,
                                },
                            })
                        except Exception:
                            pass
                        return None
                    elif _et_minutes >= SOFT_CUT:
                        # Soft cut: log + stream warn, but still let the
                        # trade through. Operator wanted a short grace for
                        # late afternoon momentum.
                        logger.info(
                            "⚠️ [v19.29 EOD-SOFT-CUT] %s %s after %s ET — "
                            "late afternoon momentum window. Allowing but "
                            "flagging for review.",
                            symbol, setup_type, _soft_str,
                        )
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "warning",
                                "event": "eod_no_new_entries_soft",
                                "symbol": symbol,
                                "text": (
                                    f"⚠️ Late-day {symbol} {setup_type} — "
                                    f"past {_soft_str} ET, in the {_grace}-min "
                                    f"grace window. Hard cut at {_hard_str}."
                                ),
                                "metadata": {
                                    "policy": "v19.29_eod_soft_cut",
                                    "cutoff_et": _soft_hhmm,
                                },
                            })
                        except Exception:
                            pass
            except Exception as _eod_err:
                logger.debug(f"v19.29 EOD gate check error: {_eod_err}")

            # V5 Unified Stream — surface "I'm thinking about this one now"
            # so the operator sees the bot's reasoning trail in real time
            # instead of having to grep logs. Fires once per evaluation
            # (dedup happens inside emit_stream_event), kept under 80 chars
            # so it doesn't dominate the stream visually.
            try:
                from services.sentcom_service import emit_stream_event
                tqs = alert.get('tqs_score') or alert.get('score') or 0
                grade = alert.get('tqs_grade') or alert.get('trade_grade') or ''
                grade_part = f" {grade}" if grade else ""
                await emit_stream_event({
                    "kind": "evaluation",
                    "event": "evaluating_setup",
                    "symbol": symbol,
                    "text": (
                        f"🤔 Evaluating {symbol} {setup_type} {direction_str.upper()} "
                        f"(TQS {tqs:.0f}{grade_part})"
                    ),
                    "metadata": {
                        "setup_type": setup_type,
                        "direction": direction_str,
                        "tqs_score": tqs,
                        "alert_priority": alert.get("priority"),
                    },
                })
            except Exception:
                pass

            # Get current price - try IB pushed data first, then Alpaca
            current_price = alert.get('current_price', 0)
            if not current_price:
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if symbol in quotes:
                            q = quotes[symbol]
                            current_price = q.get('last') or q.get('close') or 0
                except Exception:
                    pass

            # Fallback to Alpaca
            if not current_price and bot._alpaca_service:
                quote = await bot._alpaca_service.get_quote(symbol)
                current_price = quote.get('price', 0) if quote else 0

            if not current_price:
                print(f"   ❌ No price available for {symbol}")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="no_price",
                    context={"why": "Neither IB pusher nor Alpaca returned a price"},
                )
                return None

            print(f"   📈 {symbol}: price=${current_price:.2f}")

            # ==================== SMART STRATEGY FILTERING ====================
            strategy_filter = bot._evaluate_strategy_filter(
                setup_type=setup_type,
                quality_score=int(alert.get('tqs_score') or alert.get('score') or 70),
                symbol=symbol
            )

            filter_action = strategy_filter.get("action", "PROCEED")
            filter_reasoning = strategy_filter.get("reasoning", "")
            filter_adjustment = strategy_filter.get("adjustment_pct", 1.0)
            filter_win_rate = strategy_filter.get("win_rate", 0)

            if filter_action != "PROCEED" or (filter_win_rate and filter_win_rate > 0):
                bot._add_filter_thought({
                    "text": filter_reasoning,
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "win_rate": filter_win_rate,
                    "action": filter_action,
                    "stats": strategy_filter.get("stats", {})
                })

            if filter_action == "SKIP":
                print(f"   📊 [SMART FILTER] {filter_reasoning}")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="smart_filter_skip",
                    context={
                        "why": filter_reasoning,
                        "win_rate": filter_win_rate,
                        "stats": strategy_filter.get("stats", {}),
                    },
                )
                return None

            # ==================== AI CONFIDENCE GATE ====================
            confidence_gate_result = None
            confidence_multiplier = 1.0
            # Init early — referenced by build_entry_context() before the
            # AI consultation block that assigns it. Without this, INTC /
            # AAPL / MSFT etc trigger
            #   `cannot access local variable 'ai_consultation_result'
            #    where it is not associated with a value`
            # on every scan cycle, vetoing the trade as `evaluator_veto`.
            # 2026-04-29 (afternoon-14).
            #
            # ⚠ v19.34.67 NOTE: This `=None` init silenced the
            # UnboundLocalError but ALSO meant build_entry_context()
            # received None and wrote an empty ai_modules dict — leaving
            # ai_decision_audit.consulted_count=0 for every live trade
            # since 2026-04-29. The current fix is a write-back inside
            # the consult block (search for v19.34.67). The structural
            # fix — moving the entire AI consult call BEFORE trade
            # construction so build_entry_context gets the populated
            # result on the first pass — is a separate follow-up.
            ai_consultation_result: Optional[Dict[str, Any]] = None

            if hasattr(bot, '_confidence_gate') and bot._confidence_gate is not None:
                try:
                    # GAP 1 FIX: Use TQS score (richer 5-pillar assessment) instead of raw scanner score
                    gate_quality = alert.get('tqs_score') or alert.get('score', 70)
                    # Ensure it's numeric (TQS can be float)
                    gate_quality = int(gate_quality) if gate_quality else 70

                    confidence_gate_result = await bot._confidence_gate.evaluate(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction.value if hasattr(direction, 'value') else str(direction),
                        quality_score=gate_quality,
                        entry_price=alert.get('trigger_price', current_price),
                        stop_price=alert.get('stop_price', 0),
                        regime_engine=bot._market_regime_engine,
                        alert_id=alert.get('id') or alert.get('alert_id'),
                        pillar_scores=(alert.get('tqs_pillar_scores')
                                       or alert.get('_post_gate_tqs_pillars')),
                    )

                    gate_decision = confidence_gate_result.get("decision", "GO")
                    gate_confidence = confidence_gate_result.get("confidence_score", 50)
                    gate_reasoning = confidence_gate_result.get("reasoning", [])
                    confidence_multiplier = confidence_gate_result.get("position_multiplier", 1.0)
                    gate_mode = confidence_gate_result.get("trading_mode", "normal")

                    reasoning_summary = "; ".join(gate_reasoning[:4]) if gate_reasoning else "No reasoning"
                    bot._add_filter_thought({
                        "text": f"🧠 [CONFIDENCE GATE] {gate_decision} ({gate_confidence}% conf, {gate_mode} mode) — {reasoning_summary}",
                        "symbol": symbol,
                        "setup_type": setup_type,
                        "action": f"GATE_{gate_decision}",
                        "confidence_score": gate_confidence,
                        "trading_mode": gate_mode,
                    })

                    # ── P3 Seam-3: SHADOW-ARM HARNESS ───────────────────
                    # Record the live dual-gate decision (champion) + the
                    # two challenger arms (unified_1a2a, gate_off) into the
                    # EXISTING shadow_signals engine BEFORE the SKIP early-
                    # return, so the harness also captures the gate's vetoes
                    # (the whole point: measure the 68% over-veto). Best-
                    # effort, fully guarded — NEVER raises into the live
                    # decision path, NEVER touches IB. Toggle: SHADOW_ARMS_ENABLED.
                    try:
                        from services.shadow_arms import record_shadow_arms
                        await record_shadow_arms(
                            bot, alert,
                            grade=(alert.get('tqs_grade') or alert.get('trade_grade')),
                            tqs_score=(alert.get('tqs_score') or alert.get('score')),
                            gate_result=confidence_gate_result,
                            champion_decision=gate_decision,
                            champion_conf_mult=confidence_multiplier,
                            current_price=current_price,
                            direction=direction_str,
                            regime=(alert.get('market_regime') or ''),
                        )
                    except Exception:
                        pass

                    if gate_decision == "SKIP":
                        print(f"   🧠 [CONFIDENCE GATE] SKIP ({gate_confidence}% conf) — {reasoning_summary}")
                        bot.record_rejection(
                            symbol=symbol, setup_type=setup_type, direction=direction_str,
                            reason_code="gate_skip",
                            context={
                                "why": reasoning_summary,
                                "confidence_score": gate_confidence,
                                "trading_mode": gate_mode,
                            },
                        )
                        return None
                    elif gate_decision == "REDUCE":
                        print(f"   🧠 [CONFIDENCE GATE] REDUCE ({gate_confidence}% conf, {confidence_multiplier:.0%} size) — {reasoning_summary}")
                    else:
                        print(f"   🧠 [CONFIDENCE GATE] GO ({gate_confidence}% conf) — {reasoning_summary}")

                except Exception as e:
                    logger.warning(
                        "Confidence gate error (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )
                    print(f"   ⚠️ Confidence gate error: {str(e)[:100]}")

            # ==================== GAP 3 FIX: POST-GATE TQS RECALCULATION ====================
            # The Confidence Gate produces the richest AI data (setup-specific live prediction,
            # model consensus, learning loop feedback). Recalculate TQS with this data so the
            # trade's quality score reflects the full AI pipeline.
            if confidence_gate_result and confidence_gate_result.get("live_prediction"):
                try:
                    from services.tqs.tqs_engine import get_tqs_engine
                    tqs_engine = get_tqs_engine()
                    
                    pred = confidence_gate_result["live_prediction"]
                    pred_dir = pred.get("direction", "flat")
                    pred_conf = pred.get("confidence", 0)
                    trade_is_long = direction_str.lower() in ("long", "buy")
                    model_agrees = (
                        (trade_is_long and pred_dir == "up") or
                        (not trade_is_long and pred_dir == "down")
                    )
                    
                    recalc_tqs = await tqs_engine.calculate_tqs(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction_str,
                        trade_style=alert.get("trade_style"),
                        tape_score=alert.get("tape_score", 0),
                        tape_confirmation=alert.get("tape_confirmation", False),
                        smb_grade=alert.get("smb_grade", "B"),
                        smb_5var_score=alert.get("smb_score_total", 25),
                        risk_reward=alert.get("risk_reward", 2.0),
                        alert_priority=alert.get("priority", "medium"),
                        win_rate=(alert.get("strategy_win_rate") or None),
                        expected_value_r=(alert.get("strategy_ev_r") or None),
                        ai_model_direction=pred_dir,
                        ai_model_confidence=pred_conf,
                        ai_model_agrees=model_agrees,
                    )
                    
                    if recalc_tqs:
                        # Store the AI-enriched TQS for the trade
                        alert["_post_gate_tqs_score"] = recalc_tqs.score
                        alert["_post_gate_tqs_grade"] = recalc_tqs.grade
                        alert["_post_gate_tqs_action"] = recalc_tqs.action
                        # v19.34.175 — persist the AI-enriched 5-pillar
                        # breakdown so the UI drill-down reflects the richest
                        # (post-confidence-gate) TQS computation.
                        try:
                            _rd = recalc_tqs.to_dict()
                            alert["_post_gate_tqs_pillars"] = _rd.get("pillar_scores", {}) or {}
                            alert["_post_gate_tqs_pillar_grades"] = recalc_tqs.pillar_grades or {}
                            alert["_post_gate_tqs_breakdown"] = _rd.get("breakdown", {}) or {}
                            alert["_post_gate_tqs_weights"] = recalc_tqs.weights_used or {}
                        except Exception:
                            pass
                        logger.debug(
                            f"Post-gate TQS for {symbol}: {recalc_tqs.score:.1f} "
                            f"(pre-gate: {alert.get('tqs_score', 'N/A')})"
                        )

                        # ── v322x — TQS enrichment observability ─────────
                        # The "🤔 Evaluating" thought fires with the
                        # PRE-gate TQS, but the trade card shows this
                        # POST-gate (AI-enriched) score stamped at trade
                        # creation. When enrichment shifts the number the
                        # operator saw two unexplained values (e.g. XOM
                        # eval'd "54 C" but card "60 B"). Surface the shift
                        # explicitly so the trail reads 54 C → 60 B.
                        try:
                            _pre_s = float(alert.get("tqs_score") or 0)
                            _post_s = float(recalc_tqs.score or 0)
                            _pre_g = str(alert.get("tqs_grade") or "")
                            _post_g = str(recalc_tqs.grade or "")
                            if abs(_post_s - _pre_s) >= 1.0 or (_pre_g and _post_g and _pre_g != _post_g):
                                from services.sentcom_service import emit_stream_event
                                _pre_lbl = f"{_pre_s:.0f}" + (f" {_pre_g}" if _pre_g else "")
                                _post_lbl = f"{_post_s:.0f}" + (f" {_post_g}" if _post_g else "")
                                await emit_stream_event({
                                    "kind": "evaluation",
                                    "event": "tqs_enriched",
                                    "symbol": symbol,
                                    "text": (
                                        f"🧮 {symbol} TQS enriched {_pre_lbl} → {_post_lbl} "
                                        f"after AI consult ("
                                        f"{'model agrees' if model_agrees else 'model disagrees'}, "
                                        f"{float(pred_conf or 0):.0f}% conf)"
                                    ),
                                    "metadata": {
                                        "setup_type": setup_type,
                                        "pre_gate_tqs": _pre_s,
                                        "post_gate_tqs": _post_s,
                                        "pre_gate_grade": _pre_g,
                                        "post_gate_grade": _post_g,
                                        "model_agrees": model_agrees,
                                    },
                                })
                        except Exception as _tqs_obs_err:
                            logger.debug(f"v322x TQS enrichment thought error: {_tqs_obs_err}")
                except Exception as e:
                    logger.debug(f"Post-gate TQS recalculation failed (non-critical): {e}")

            # ==================== ENHANCED INTELLIGENCE GATHERING ====================
            intelligence = await bot._gather_trade_intelligence(symbol, alert)

            score_adjustment = bot._calculate_intelligence_adjustment(intelligence)

            # Extract ATR from intelligence for volatility-adjusted sizing
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

            # Get trade parameters from alert
            entry_price = alert.get('trigger_price', current_price)
            stop_price = alert.get('stop_price', 0)
            target_prices = alert.get('targets', [])

            # Calculate ATR-based stop if not provided
            if not stop_price:
                stop_price = self.calculate_atr_based_stop(
                    entry_price, direction, atr, setup_type, bot,
                    trade_style=hsbg_style,  # v325 HSBG
                )

            # ── v19.34.183 — Wrong-side stop guard (entry/sizing path) ───
            # A long must have stop < entry; a short stop > entry. A detector
            # that emits an inverted stop (e.g. a squeeze whose price already
            # ran past the band, leaving a stale trigger) would otherwise size
            # off |entry-stop| and submit a backwards bracket. Discard the
            # inverted stop and recompute the canonical per-setup ATR stop,
            # which is always on the correct side of entry.
            try:
                if stop_price and entry_price:
                    _is_long = (direction == TradeDirection.LONG)
                    _wrong_side = ((_is_long and stop_price >= entry_price) or
                                   ((not _is_long) and stop_price <= entry_price))
                    if _wrong_side:
                        _orig_ws = float(stop_price)
                        stop_price = self.calculate_atr_based_stop(
                            entry_price, direction, atr, setup_type, bot,
                            trade_style=hsbg_style,  # v325 HSBG
                        )
                        logger.warning(
                            f"🩹 [v19.34.183 wrong-side-stop] {symbol} "
                            f"{'LONG' if _is_long else 'SHORT'} alert stop ${_orig_ws:.2f} on "
                            f"wrong side of entry ${entry_price:.2f} — recomputed → ${stop_price:.2f}"
                        )
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "warning",
                                "event": "wrong_side_stop_recomputed",
                                "symbol": symbol,
                                "text": (
                                    f"🩹 {symbol} {'long' if _is_long else 'short'} "
                                    f"stop ${_orig_ws:.2f} was wrong side of entry "
                                    f"${entry_price:.2f} — recomputed ${stop_price:.2f}"
                                ),
                                "metadata": {"source": "opportunity_evaluator",
                                             "guard": "v19.34.183_wrong_side_stop",
                                             "original_stop": _orig_ws,
                                             "new_stop": stop_price},
                            })
                        except Exception:
                            pass
            except Exception as _ws_err:
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

            # ── v19.34.183 — Position/investment stop-cap for DETECTOR stops ─
            # v169 caps multi-day stops at 5% of entry, but that cap lives
            # inside calculate_atr_based_stop, which only runs when the alert
            # supplies NO stop. Detectors like stage_2_breakout / weekly_breakout
            # DO supply a wide structural stop (e.g. BMO 30w-SMA stop = 16.8%),
            # bypassing the cap and re-collapsing share counts to 1-3. Apply the
            # same cap here to detector-supplied stops on position/investment
            # horizons. Only ever TIGHTENS an over-wide stop; never loosens.
            try:
                import os as _os_scap
                _style = str(alert.get('trade_style', '') or '').lower()
                if _style in ('position', 'investment') and stop_price and entry_price:
                    _cap_pct = float(_os_scap.environ.get(
                        "MAX_STOP_PCT_POSITION" if _style == 'position' else "MAX_STOP_PCT_INVESTMENT",
                        "0.05",
                    ))
                    _dist = abs(float(entry_price) - float(stop_price))
                    _cap_dist = float(entry_price) * _cap_pct
                    if _cap_pct and _cap_dist > 0 and _dist > _cap_dist:
                        _is_long = (direction == TradeDirection.LONG)
                        _new_stop = (entry_price - _cap_dist) if _is_long else (entry_price + _cap_dist)
                        logger.info(
                            f"[v19.34.183 stop-cap] {symbol} {_style} detector stop "
                            f"${stop_price:.2f} ({_dist/entry_price*100:.1f}%) > {_cap_pct*100:.0f}% cap "
                            f"— tightened → ${_new_stop:.2f}"
                        )
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "info",
                                "event": "position_stop_capped",
                                "symbol": symbol,
                                "text": (
                                    f"✂️ {symbol} {_style} stop {_dist/entry_price*100:.1f}% "
                                    f"capped to {_cap_pct*100:.0f}% (${stop_price:.2f}→${_new_stop:.2f}) "
                                    f"— keeps share sizing sane"
                                ),
                                "metadata": {"source": "opportunity_evaluator",
                                             "guard": "v19.34.183_stop_cap",
                                             "style": _style,
                                             "capped_stop": _new_stop},
                            })
                        except Exception:
                            pass
                        stop_price = _new_stop
            except Exception as _scap_err:
                logger.debug(f"[v19.34.183 stop-cap] skipped for {symbol}: {_scap_err}")

            # ── Stop-placement guard (2026-04-28e) ──
            # Before targets / position size, ask Smart S/R if our stop
            # is sitting inside a Volume-Profile / pivot cluster. If so,
            # widen it to just past the cluster (capped at +40% of the
            # original distance to preserve sizing risk math). Stops are
            # NEVER tightened — only widened.
            stop_guard_meta = None
            try:
                sym_for_guard = alert.get("symbol") if isinstance(alert, dict) else None
                guard_bs = "5 mins"
                if isinstance(alert, dict):
                    guard_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
                db_for_guard = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None else getattr(bot, "db", None))
                if sym_for_guard and db_for_guard is not None and stop_price:
                    from services.smart_levels_service import compute_stop_guard
                    dir_str = "long" if direction == TradeDirection.LONG else "short"
                    guard = compute_stop_guard(
                        db_for_guard, sym_for_guard.upper(), guard_bs,
                        float(entry_price), float(stop_price), dir_str,
                    )
                    if guard.get("snapped"):
                        logger.info(
                            f"Stop-guard widened {sym_for_guard} "
                            f"{dir_str.upper()} stop {stop_price:.2f} → "
                            f"{guard['stop']:.2f} (past {guard['level_kind']} "
                            f"@ {guard['level_price']:.2f}, widen "
                            f"{guard['widen_pct']:+.0%})"
                        )
                        stop_price = guard["stop"]
                    stop_guard_meta = guard
            except Exception as exc:
                logger.debug(f"stop-guard skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # ── v19.34.45 — Guardrail-floor enforcement ─────────
            # If the (alert-supplied, possibly smart-levels-widened) stop
            # is tighter than 0.3 × ATR, replace with the canonical
            # per-setup ATR-based stop. Sizer absorbs the wider risk.
            stop_floor_meta = None
            try:
                import os as _os_floor
                _enf_raw = _os_floor.environ.get("STOP_FLOOR_ENFORCE", "1")
                _enf_on = str(_enf_raw).strip().lower() not in ("0","","false","no","off")
                if _enf_on and stop_price and entry_price and atr and atr > 0:
                    try:
                        _floor_mult = float(_os_floor.environ.get(
                            "EXECUTION_GUARDRAIL_MIN_STOP_ATR_MULT", "0.3"
                        ))
                    except (TypeError, ValueError):
                        _floor_mult = 0.3
                    _distance = abs(float(entry_price) - float(stop_price))
                    # v325 HSBG — floor measured on the horizon-scaled
                    # basis, otherwise a 0.3×DAILY-ATR floor would undo
                    # the scalp/intraday tightening every time.
                    _threshold = _floor_mult * float(atr) * (hsbg_frac or 1.0)
                    if _distance < _threshold:
                        _orig_stop = float(stop_price)
                        _new_stop = self.calculate_atr_based_stop(
                            float(entry_price), direction, float(atr), setup_type, bot,
                            trade_style=hsbg_style,  # v325 HSBG
                        )
                        _new_distance = abs(float(entry_price) - float(_new_stop))
                        if _new_distance >= _threshold:
                            logger.warning(
                                "🩹 [v19.34.45 stop-floor] %s %s — alert stop "
                                "$%.4f (Δ=$%.4f, %.1f%% of ATR $%.4f) below floor "
                                "%.2f×ATR=$%.4f. Recomputed via per-setup multiplier "
                                "→ $%.4f (Δ=$%.4f). Sizer will absorb the wider risk.",
                                symbol, setup_type, _orig_stop, _distance,
                                (_distance / float(atr)) * 100.0, float(atr),
                                _floor_mult, _threshold, _new_stop, _new_distance,
                            )
                            stop_price = _new_stop
                            stop_floor_meta = {
                                "applied": True,
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                                "original_distance": _distance,
                                "recomputed_distance": _new_distance,
                            }
                        else:
                            logger.error(
                                "⚠️ [v19.34.45 stop-floor] %s %s — alert stop AND "
                                "recomputed stop both below %.2f×ATR floor "
                                "(alert Δ=$%.4f, recomputed Δ=$%.4f, threshold "
                                "$%.4f). Check SETUP_MULTIPLIERS entry for %r.",
                                symbol, setup_type, _floor_mult,
                                _distance, _new_distance, _threshold, setup_type,
                            )
                            stop_floor_meta = {
                                "applied": False,
                                "reason": "recomputed_also_too_tight",
                                "original_stop": _orig_stop,
                                "recomputed_stop": _new_stop,
                                "atr": float(atr),
                                "floor_atr_mult": _floor_mult,
                            }
            except Exception as _floor_err:
                logger.debug(
                    "[v19.34.45 stop-floor] enforce crashed (fail-open): %s",
                    _floor_err,
                )

            # Calculate targets if not provided — trade-style-aware ladder
            # (v19.34.112). See OpportunityEvaluator._target_ladder_rungs.
            if not target_prices:
                risk = abs(entry_price - stop_price)
                rungs = self._target_ladder_rungs(alert, setup_type)
                if direction == TradeDirection.LONG:
                    target_prices = [entry_price + risk * r for r in rungs]
                else:
                    target_prices = [entry_price - risk * r for r in rungs]

            # ── Target snap (2026-04-28e) ──
            # For each computed target, snap to just before the nearest
            # strong S/R cluster on the move side. Catches the "2.5R
            # target sits 40 cents short of a thick HVN" failure mode.
            target_snap_meta = None
            try:
                sym_for_targets = alert.get("symbol") if isinstance(alert, dict) else None
                tgt_bs = "5 mins"
                if isinstance(alert, dict):
                    tgt_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
                db_for_targets = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None else getattr(bot, "db", None))
                # ── v19.34.112 — Skip target-snap for scalps ────────────
                # target-snap is designed to *widen* targets to just
                # before the nearest S/R cluster on the move side. For
                # swing/position trades targeting 2-4R, that's a few
                # cents of slippage to capture a thicker resting bid.
                # For a scalp targeting 1R in <5 minutes, a snap can
                # easily push the target 30-50 bp further out — far
                # enough that the move never reaches it inside the
                # holding window. Treat scalps as "tight target, take
                # what's there"; do not widen.
                _ts = (
                    (alert.get('trade_style') if isinstance(alert, dict) else None) or ''
                ).strip().lower()
                _su = (setup_type or '').strip().lower()
                _is_scalp_for_snap = (
                    _ts == 'scalp'
                    or _su in {'scalp', 'nine_ema_scalp', 'spencer_scalp', 'abc_scalp'}
                )
                if _is_scalp_for_snap:
                    logger.debug(
                        f"target-snap skipped for {sym_for_targets} — "
                        f"scalp trade-style does not widen targets."
                    )
                elif sym_for_targets and db_for_targets is not None and target_prices:
                    from services.smart_levels_service import compute_target_snap
                    dir_str = "long" if direction == TradeDirection.LONG else "short"
                    snap = compute_target_snap(
                        db_for_targets, sym_for_targets.upper(), tgt_bs,
                        float(entry_price), [float(t) for t in target_prices], dir_str,
                    )
                    if snap.get("any_snapped"):
                        logger.info(
                            f"Target-snap {sym_for_targets} {dir_str.upper()} "
                            f"targets {[round(t, 2) for t in target_prices]} → "
                            f"{[round(t, 2) for t in snap['targets']]}"
                        )
                        target_prices = snap["targets"]
                    target_snap_meta = snap.get("details")
            except Exception as exc:
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

            # Calculate position size with volatility adjustment + Volume-Profile path multiplier (2026-04-28e)
            # + v19.34.156 grade-based scaler (P3-A) + v19.34.157 MR regime scaler (P3-C).
            symbol_for_vp = alert.get("symbol") if isinstance(alert, dict) else None
            if isinstance(alert, dict):
                scanner_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
                # ── v19.34.175 — TQS is the SINGLE SOURCE OF TRUTH for sizing.
                # Operator choice A (2026-05-29): plumb the real TQS grade into
                # the grade scaler with the existing multiplier table
                # (A=1.0 / B=0.7 / C=0.3 / D=0.1). Pre-fix this read `smb_grade`,
                # which (a) was never threaded into this dict — so the scaler
                # defaulted to D (0.1x) on EVERY trade — and (b) double-counted
                # SMB, which is already 15% of the TQS Setup pillar. SMB grade is
                # now retained for AUDIT ONLY (stamped on the trade record).
                # Prefer the AI-enriched post-gate TQS grade, then the pre-gate
                # TQS grade, then legacy trade_grade. Missing/unknown → D (strict,
                # per Q2b) inside `_resolve_grade_multiplier`.
                alert_grade = (
                    alert.get("_post_gate_tqs_grade")
                    or alert.get("tqs_grade")
                    or alert.get("trade_grade")
                )
                # v19.34.157 — setup_type drives the MR family lookup
                # (MR vs momentum vs breakout). Unknown setups produce a
                # neutral 1.0× multiplier (never blocks).
                alert_setup_type = alert.get("setup_type")
            else:
                scanner_bs = "5 mins"
                alert_grade = None
                alert_setup_type = None
            position_multipliers: Dict[str, Any] = {}
            shares, risk_amount = self.calculate_position_size(
                entry_price, stop_price, direction, bot, atr, atr_percent,
                symbol=symbol_for_vp, bar_size=scanner_bs,
                multipliers_out=position_multipliers,
                grade=alert_grade,
                setup_type=alert_setup_type,
                proven_outcomes=(alert.get("proven_outcomes") if isinstance(alert, dict) else None),
            )

            # ==================== SMART STRATEGY FILTER SIZE ADJUSTMENT ====================
            if filter_action == "REDUCE_SIZE" and filter_adjustment < 1.0:
                original_shares = shares
                shares = max(1, int(shares * filter_adjustment))
                risk_amount = risk_amount * filter_adjustment
                print(f"   📊 [SMART FILTER] Reduced size: {original_shares} -> {shares} shares ({filter_adjustment*100:.0f}%)")

            # ==================== CONFIDENCE GATE SIZE ADJUSTMENT ====================
            if confidence_multiplier < 1.0:
                original_shares = shares
                shares = max(1, int(shares * confidence_multiplier))
                risk_amount = risk_amount * confidence_multiplier
                gate_conf = confidence_gate_result.get("confidence_score", 0) if confidence_gate_result else 0
                print(f"   🧠 [CONFIDENCE GATE] Reduced size: {original_shares} -> {shares} shares ({confidence_multiplier*100:.0f}%, {gate_conf}% conf)")

            # ==================== STRATEGY TILT (long/short Sharpe bias) ====================
            # Re-weights size by rolling 30-day per-side Sharpe so cold streaks
            # on one side shrink while the hot side grows. Bounded [0.5x, 1.5x];
            # neutral when either side has fewer than 10 closed trades.
            try:
                from services.strategy_tilt import get_strategy_tilt_cached, get_side_tilt_multiplier
                tilt = get_strategy_tilt_cached(getattr(bot, "_db", None))
                tilt_mult = get_side_tilt_multiplier(
                    direction.value if hasattr(direction, "value") else str(direction),
                    tilt,
                )
                if abs(tilt_mult - 1.0) > 1e-3:
                    original_shares = shares
                    shares = max(1, int(shares * tilt_mult))
                    risk_amount = risk_amount * tilt_mult
                    print(f"   ⚖️ [STRATEGY TILT] {original_shares} -> {shares} shares "
                          f"(x{tilt_mult:.2f}, long_Sh={tilt.get('sharpe_long', 0):.2f}, "
                          f"short_Sh={tilt.get('sharpe_short', 0):.2f})")
            except Exception as _tilt_err:
                logger.debug(f"[StrategyTilt] skipped: {_tilt_err}")

            # ==================== HRP PORTFOLIO ALLOCATOR ====================
            # Down-weight candidates that are correlated with existing open
            # positions. Neutral (1.0) when fewer than 2 peers or when the
            # returns fetcher isn't registered — never breaks sizing.
            try:
                from services.portfolio_allocator_service import get_hrp_multiplier
                open_symbols = [t.symbol for t in bot._open_trades.values()
                                if getattr(t, "symbol", None)]
                pending_symbols = [t.symbol for t in bot._pending_trades.values()
                                   if getattr(t, "symbol", None) and t.symbol != symbol]
                peer_symbols = list(dict.fromkeys(open_symbols + pending_symbols + [symbol]))
                hrp_mult = get_hrp_multiplier(symbol, peer_symbols)
                if abs(hrp_mult - 1.0) > 1e-3:
                    original_shares = shares
                    shares = max(1, int(shares * hrp_mult))
                    risk_amount = risk_amount * hrp_mult
                    print(f"   🌐 [HRP ALLOCATOR] {original_shares} -> {shares} shares "
                          f"(x{hrp_mult:.2f}, peers={len(peer_symbols)})")
            except Exception as _hrp_err:
                logger.debug(f"[HRPAllocator] skipped: {_hrp_err}")

            if shares <= 0:
                # v19.34.70 — Distinguish "cap-saturated" zero from generic
                # sizing-zero. When the sizer hits the per-symbol exposure
                # cap, follow-up cycles on (symbol, setup_type) will keep
                # producing 0 shares for the same reason → death by a
                # thousand cuts (operator-observed NBIS thrashing
                # 2026-05-11). Route to `symbol_exposure_saturated` which
                # is registered as STRUCTURAL in the cooldown service so
                # subsequent re-evaluations get throttled by the
                # per-(symbol, setup_type) cooldown.
                cap_saturated = (
                    isinstance(position_multipliers, dict)
                    and position_multipliers.get("block_reason") == "symbol_exposure_saturated"
                )
                if cap_saturated:
                    _existing = float(position_multipliers.get("existing_sym_exposure", 0))
                    _cap = float(position_multipliers.get("safety_cap_usd", 0))
                    print(
                        f"   ❌ {symbol} symbol_exposure_saturated "
                        f"(existing ${_existing:,.0f} ≥ cap ${_cap:,.0f}) → "
                        f"triggering rejection cooldown."
                    )
                    bot.record_rejection(
                        symbol=symbol, setup_type=setup_type, direction=direction_str,
                        reason_code="symbol_exposure_saturated",
                        context={
                            "entry_price": float(entry_price),
                            "existing_sym_exposure_usd": _existing,
                            "safety_cap_usd": _cap,
                            "why": (
                                "Per-symbol exposure cap reached. Further "
                                "entries on this symbol+setup will be "
                                "skipped until cooldown expires or exposure "
                                "drops below cap."
                            ),
                        },
                    )
                    # Feed the per-(symbol, setup_type) cooldown so the
                    # next ~5 min of evaluations are silently dropped
                    # instead of regenerating fresh trade_ids every cycle.
                    try:
                        from services.rejection_cooldown_service import get_rejection_cooldown
                        get_rejection_cooldown().mark_rejection(
                            symbol=symbol,
                            setup_type=setup_type or "unknown",
                            reason="symbol_exposure_saturated",
                        )
                    except Exception as _cd_err:
                        logger.debug(
                            f"v19.34.70 mark_rejection(cap_saturated) failed: {_cd_err}"
                        )
                    return None

                print(f"   ❌ Position size = 0 (entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f})")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="position_size_zero",
                    context={
                        "entry_price": float(entry_price),
                        "stop_price": float(stop_price),
                        "risk_amount": float(risk_amount),
                        "why": "Position sizer returned 0 shares — usually means equity unavailable or risk caps too tight for this entry/stop distance",
                    },
                )
                return None

            print(f"   📊 {symbol}: {shares} shares, entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f}")

            # ── v19.34.179 — Portfolio-level exposure cap (AUTONOMOUS path) ──
            # The v19.34.96/98 position-style (30%) + long-horizon (55%)
            # exposure caps were ONLY wired into the manual submit_trade
            # router path, so unattended bot entries could pile simultaneous
            # long-horizon bets past the intended portfolio concentration
            # (starving scalp/intraday buying power — the exact case the
            # guard was built for). Mirror the submit_trade clamp here so
            # autopilot honors the same caps. Fail-open: any error logs and
            # proceeds (per-symbol + per-trade caps still apply).
            try:
                _style = (alert.get("trade_style") if isinstance(alert, dict) else None) or ""
                _style = str(_style).strip().lower()
                if _style and entry_price > 0:
                    from services.portfolio_exposure_guard import (
                        LONG_HORIZON_STYLES, POSITION_STYLES, compute_exposure,
                    )
                    _acct_val = 0.0
                    try:
                        _acct_val = float(await bot._get_account_value() or 0)
                    except Exception:
                        _acct_val = 0.0
                    if _acct_val > 0:
                        try:
                            from services.position_sizer import get_position_sizer_service
                            _scfg = get_position_sizer_service().get_config()
                            _pos_cap = float(_scfg.get("max_position_style_exposure_pct", 30.0))
                            _lh_cap = float(_scfg.get("max_long_horizon_exposure_pct", 55.0))
                        except Exception:
                            _pos_cap, _lh_cap = 30.0, 55.0
                        _open = list((getattr(bot, "_open_trades", {}) or {}).values())
                        for _styles, _cap_pct, _label in (
                            (POSITION_STYLES, _pos_cap, "position-style"),
                            (LONG_HORIZON_STYLES, _lh_cap, "long-horizon"),
                        ):
                            if _style not in _styles:
                                continue
                            _snap = compute_exposure(_open, _acct_val, cap_pct=_cap_pct, styles=_styles)
                            _cap_shares = int(_snap.remaining_value // entry_price) if entry_price > 0 else 0
                            if shares > _cap_shares:
                                print(
                                    f"   🧱 {symbol} portfolio {_cap_pct:.0f}% {_label} cap: "
                                    f"${_snap.remaining_value:,.0f} remaining → {_cap_shares} shares "
                                    f"(was {shares})"
                                )
                                shares = max(0, _cap_shares)
                        if shares <= 0:
                            print(f"   ❌ {symbol} blocked by portfolio exposure cap (style={_style})")
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type, direction=direction_str,
                                reason_code="portfolio_exposure_cap",
                                context={
                                    "trade_style": _style,
                                    "why": ("Portfolio-level exposure cap (position-style 30% / "
                                            "long-horizon 55%) is saturated — no room for additional "
                                            "long-horizon exposure. Protects scalp/intraday buying power."),
                                },
                            )
                            return None
            except Exception as _exp_err:
                logger.debug(f"v19.34.179 portfolio exposure clamp skipped for {symbol}: {_exp_err}")

            # Calculate risk/reward
            primary_target = target_prices[0] if target_prices else entry_price
            potential_reward = abs(primary_target - entry_price) * shares
            risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0

            if risk_reward_ratio < bot.risk_params.effective_min_rr(setup_type):
                # 2026-05-01 v19.21 — Per-setup R:R override. Mean-reversion
                # setups (gap_fade, vwap_fade, etc.) have bounded targets and
                # need a relaxed floor; trend/breakout setups have unbounded
                # targets and keep the strict 2.0 gate. The narrative now
                # surfaces the SETUP-SPECIFIC threshold, not the global one,
                # so the operator's Bot's Brain stream shows the right number.
                _eff_min = bot.risk_params.effective_min_rr(setup_type)

                # ── v19.34.181 — auto-ladder fallback ──────────────────
                # Detector-supplied targets for longer-horizon setups are
                # often set near daily structure while the stop is a wide
                # (2.5-3× ATR) swing/position stop, collapsing R:R below the
                # gate (observed: stage_2/three_week_tight at R:R 0.02-0.76).
                # Before rejecting, re-derive the target from the ACTUAL risk
                # using the trade-style R ladder, picking the smallest rung
                # that clears the effective min R:R — so these ideas get a
                # timeframe-appropriate target instead of dying on a too-close
                # detector target. Stop is left untouched.
                _risk_ps = abs(entry_price - stop_price)
                if _risk_ps > 0 and shares > 0 and risk_amount > 0:
                    _rungs = self._target_ladder_rungs(alert, setup_type)
                    _chosen = next((r for r in _rungs if r >= _eff_min), _rungs[-1])
                    _ladder = [r for r in _rungs if r >= _chosen] or [_chosen]
                    if direction == TradeDirection.LONG:
                        _new_targets = [entry_price + _risk_ps * r for r in _ladder]
                    else:
                        _new_targets = [entry_price - _risk_ps * r for r in _ladder]
                    _new_primary = _new_targets[0]
                    _new_reward = abs(_new_primary - entry_price) * shares
                    _new_rr = _new_reward / risk_amount if risk_amount > 0 else 0
                    if _new_rr >= _eff_min:
                        print(
                            f"   🪜 {symbol} R:R {risk_reward_ratio:.2f} < {_eff_min} "
                            f"— auto-ladder fallback → target ${_new_primary:.2f} "
                            f"(R:R {_new_rr:.2f}, {_chosen}R)"
                        )
                        target_prices = _new_targets
                        primary_target = _new_primary
                        potential_reward = _new_reward
                        risk_reward_ratio = _new_rr

            if risk_reward_ratio < bot.risk_params.effective_min_rr(setup_type):
                _eff_min = bot.risk_params.effective_min_rr(setup_type)
                print(f"   ❌ R:R {risk_reward_ratio:.2f} < {_eff_min} min required (setup={setup_type})")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="rr_below_min",
                    context={
                        "rr_ratio": round(risk_reward_ratio, 2),
                        "min_required": _eff_min,
                        "global_min": bot.risk_params.min_risk_reward,
                        "entry_price": float(entry_price),
                        "stop_price": float(stop_price),
                        "primary_target": float(primary_target),
                        "shares": int(shares),
                    },
                )
                return None

            print(f"   ✅ {symbol}: R:R={risk_reward_ratio:.2f}, target=${primary_target:.2f}, reward=${potential_reward:.2f}")

            # Get quality score with intelligence adjustment
            base_score = alert.get('score', 70)
            quality_score = min(100, max(0, base_score + score_adjustment))
            quality_grade = self.score_to_grade(quality_score)

            # Generate explanation with intelligence data
            explanation = self.generate_explanation(alert, shares, entry_price, stop_price, target_prices, intelligence, bot)

            # Get strategy config for this setup type
            strategy_cfg = STRATEGY_CONFIG.get(setup_type, DEFAULT_STRATEGY_CONFIG)
            timeframe_val = strategy_cfg["timeframe"]
            timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
            # v322u — taxonomy coherence: when the scanner-resolved
            # trade_style maps to a canonical horizon that conflicts with
            # the per-setup STRATEGY_CONFIG table, the style wins (it
            # drives order policy / EOD / decay). See STYLE_TO_TIMEFRAME.
            timeframe_str, _tf_reconciled = reconcile_timeframe_with_style(
                timeframe_str, alert.get("trade_style"))
            if _tf_reconciled:
                logger.info(
                    "[v322u TAXONOMY] %s %s: timeframe → %r "
                    "(follows trade_style=%r, STRATEGY_CONFIG said %r)",
                    symbol, setup_type, timeframe_str,
                    alert.get("trade_style"), strategy_cfg["timeframe"],
                )
            trail_pct = strategy_cfg.get("trail_pct", 0.02)
            scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
            # v19.34.245 — derive close_at_eod from the trade-style POLICY when
            # the setup's STRATEGY_CONFIG omits the key, instead of a blanket
            # True default. Position/swing/investment setups missing the key were
            # wrongly flagged for EOD close (swept before stop/target, skewing
            # the learning loop). Policy is the authoritative source of truth.
            close_at_eod = strategy_cfg.get("close_at_eod")
            if close_at_eod is None:
                from services.order_policy_registry import get_policy_for_trade
                close_at_eod = get_policy_for_trade({"setup_type": setup_type}).close_at_eod

            # Get current market regime
            current_regime = bot._current_regime or "UNKNOWN"
            regime_score = 50.0
            regime_multiplier = bot._regime_position_multipliers.get(current_regime, 1.0)

            if current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0
            elif current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7

            if bot._market_regime_engine is not None:
                try:
                    regime_data = await bot._market_regime_engine.get_current_regime()
                    regime_score = regime_data.get("composite_score", 50.0)
                except Exception:
                    pass

            # ── v19.34.175 — canonical TQS grade/score for this trade.
            # TQS is the single source of truth; `unified_grade` = TQS grade
            # (falls back to the legacy quality_grade only when TQS is entirely
            # absent, e.g. a legacy/synthetic alert with no scanner enrichment).
            tqs_grade_final = (
                alert.get("_post_gate_tqs_grade")
                or alert.get("tqs_grade")
                or ""
            )
            tqs_score_final = (
                alert.get("_post_gate_tqs_score")
                or alert.get("tqs_score")
                or 0
            )
            unified_grade_final = tqs_grade_final or quality_grade

            # Create trade
            trade = BotTrade(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                direction=direction,
                status=TradeStatus.PENDING,
                setup_type=setup_type,
                timeframe=timeframe_str,
                quality_score=quality_score,
                quality_grade=quality_grade,
                trade_style=self._resolve_geometry_style(alert, setup_type),
                smb_grade=alert.get("smb_grade", quality_grade),
                tqs_score=float(tqs_score_final or 0),
                tqs_grade=tqs_grade_final,
                unified_grade=unified_grade_final,
                tape_score=alert.get("tape_score", 5),
                target_r_multiple=alert.get("target_r_multiple", risk_reward_ratio),
                direction_bias=alert.get("direction_bias", "both"),
                entry_price=entry_price,
                current_price=current_price,
                stop_price=stop_price,
                target_prices=target_prices,
                shares=shares,
                # v19.34.36 — stamp alert_id so the learning loop's pending
                # context lookup and decision_trail join can resolve.
                alert_id=alert.get("alert_id"),
                # 2026-04-30 v19.13 — initialize remaining_shares +
                # original_shares at TRADE-CREATE time, not on first
                # manage-loop tick. Pre-fix: a partial exit landing
                # before the first manage tick would decrement
                # remaining_shares while original_shares was still 0,
                # distorting all percentage-based scale-out math.
                remaining_shares=shares,
                original_shares=shares,
                risk_amount=risk_amount,
                potential_reward=potential_reward,
                risk_reward_ratio=risk_reward_ratio,
                created_at=datetime.now(timezone.utc).isoformat(),
                estimated_duration=self.estimate_duration(setup_type),
                explanation=explanation,
                close_at_eod=close_at_eod,
                market_regime=current_regime,
                regime_score=regime_score,
                regime_position_multiplier=regime_multiplier,
                setup_variant=alert.get("strategy_name", alert.get("setup_variant", setup_type)),
                entry_context=self.build_entry_context(
                    alert, intelligence, current_regime, regime_score,
                    filter_action, filter_win_rate, atr, atr_percent,
                    confidence_gate_result=confidence_gate_result,
                    multipliers_meta={
                        "position": position_multipliers,
                        "stop_guard": stop_guard_meta,
                        "target_snap": target_snap_meta,
                        # v325 — geometry/reachability stamps (atr basis,
                        # horizon frac, reach envelope, pt1_env_ratio).
                        "hsbg": hsbg_meta,
                    },
                    # 2026-04-28f: AI module results were previously
                    # only landed under `explanation.ai_consultation`,
                    # making them invisible to the analytics + the
                    # Q3 verification curl. Now mirrored into
                    # `entry_context.ai_modules` for unified inspection.
                    ai_consultation_result=ai_consultation_result,
                ),
                scale_out_config={
                    "enabled": True,
                    "targets_hit": [],
                    "scale_out_pcts": scale_pcts,
                    "partial_exits": []
                },
                trailing_stop_config={
                    "enabled": True,
                    "mode": "original",
                    "original_stop": stop_price,
                    "current_stop": stop_price,
                    "trail_pct": trail_pct,
                    "trail_atr_mult": 1.5,
                    "high_water_mark": 0.0,
                    "low_water_mark": 0.0,
                    "stop_adjustments": []
                }
            )

            logger.info(f"Trade opportunity created: {symbol} {direction.value} {shares} shares @ ${entry_price:.2f}")
            print(f"   🎯 Trade object created: {trade.id} {symbol} {direction.value}")

            # ==================== AI TRADE CONSULTATION (Phase 2) ====================
            ai_consultation_result = None
            if hasattr(bot, '_ai_consultation') and bot._ai_consultation:
                try:
                    market_context = {
                        "regime": current_regime,
                        "vix": intelligence.get("market_data", {}).get("vix", 0),
                        "trend": intelligence.get("market_data", {}).get("trend", "neutral"),
                        "technicals": intelligence.get("technicals", {}),
                        "session": bot._get_current_session()
                    }

                    portfolio_context = {
                        "account_value": await bot._get_account_value(),
                        "open_positions": len(bot._open_trades),
                        "positions": [t.to_dict() for t in bot._open_trades.values()]
                    }

                    bars = intelligence.get("bars", [])

                    ai_consultation_result = await bot._ai_consultation.consult_on_trade(
                        trade=trade.to_dict(),
                        market_context=market_context,
                        portfolio=portfolio_context,
                        bars=bars
                    )

                    if ai_consultation_result:
                        consult_rec = ai_consultation_result.get("reasoning", "No AI analysis")
                        shadow_mode = ai_consultation_result.get("shadow_logged", False)
                        decision_id = ai_consultation_result.get("shadow_decision_id", "")

                        print(f"   🧠 [AI Consultation] {consult_rec[:100]}")

                        if not ai_consultation_result.get("proceed", True):
                            print(f"   ❌ [AI BLOCKED] {ai_consultation_result.get('reasoning', '')}")
                            logger.info(f"AI Consultation BLOCKED trade {symbol}: {consult_rec}")
                            if shadow_mode and decision_id:
                                trade.explanation.ai_shadow_decision_id = decision_id
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type, direction=direction_str,
                                reason_code="ai_consultation_block",
                                context={
                                    "why": consult_rec[:300],
                                    "shadow_decision_id": decision_id,
                                },
                            )
                            return None

                        size_adj = ai_consultation_result.get("size_adjustment", 1.0)
                        if size_adj < 1.0:
                            original_shares = trade.shares
                            trade.shares = max(1, int(trade.shares * size_adj))
                            trade.risk_amount = trade.risk_amount * size_adj
                            trade.potential_reward = trade.potential_reward * size_adj
                            print(f"   📉 [AI SIZE ADJ] {original_shares} -> {trade.shares} shares ({size_adj*100:.0f}%)")

                        if shadow_mode and decision_id:
                            if not hasattr(trade, 'ai_shadow_decision_id'):
                                trade.ai_shadow_decision_id = decision_id

                        if trade.explanation:
                            trade.explanation.ai_consultation = {
                                "proceed": ai_consultation_result.get("proceed", True),
                                "size_adjustment": size_adj,
                                "reasoning": consult_rec[:300],
                                "shadow_decision_id": decision_id
                            }

                        # v19.34.67 — Write the AI module decisions back
                        # into trade.entry_context.ai_modules. The build_entry_context
                        # call earlier in this function ran BEFORE the consult fired
                        # (variable-ordering bug masked by a 2026-04-29 `=None`
                        # defensive init), so ai_modules was always empty and the
                        # ai_decision_audit endpoint reported consulted_count=0
                        # for every single trade since then. This back-fill is
                        # the surgical fix; the proper reordering of consult
                        # BEFORE trade-build is deferred to a structural follow-up.
                        ai_modules_ctx = self._build_ai_modules_ctx(ai_consultation_result)
                        if ai_modules_ctx is not None and isinstance(trade.entry_context, dict):
                            trade.entry_context["ai_modules"] = ai_modules_ctx

                except Exception as e:
                    logger.warning(
                        "AI Consultation failed (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )
                    print(f"   ⚠️ AI Consultation error: {str(e)[:100]}")

            # AI evaluation - legacy
            if hasattr(bot, '_ai_assistant') and bot._ai_assistant:
                try:
                    ai_result = await bot._ai_assistant.evaluate_bot_opportunity(trade.to_dict())
                    if ai_result.get("success") and trade.explanation:
                        trade.explanation.ai_evaluation = ai_result.get("analysis", "")
                        trade.explanation.ai_verdict = ai_result.get("verdict", "CAUTION")
                        if ai_result.get("verdict") == "REJECT":
                            print(f"   🤖 AI REJECTED trade: {ai_result.get('analysis', '')[:150]}")
                            logger.info(f"AI REJECTED trade {symbol}: {ai_result.get('analysis', '')[:100]}")
                            if bot._mode != BotMode.AUTONOMOUS:
                                # v19.34.164: surface the legacy-AI veto
                                # so the Diagnostics tab shows why this
                                # trade died (previously a silent return).
                                try:
                                    bot.record_rejection(
                                        symbol=symbol, setup_type=setup_type,
                                        direction=direction_str,
                                        reason_code="ai_verdict_reject",
                                        context={
                                            "why": str(ai_result.get("analysis", ""))[:300],
                                            "verdict": ai_result.get("verdict"),
                                            "mode": "non_autonomous",
                                        },
                                    )
                                except Exception:
                                    pass
                                return None
                            else:
                                print("   ⚠️ Overriding AI rejection in AUTONOMOUS mode")
                except Exception as e:
                    logger.warning(
                        "AI evaluation failed (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )

            print(f"   ✅ Returning trade object {trade.id}")

            # ==================== TRADE AUDIT LOG (P2 2026-04-23) ====================
            # Best-effort snapshot of the full decision trail for post-mortem
            # forensics. Never blocks trade flow.
            try:
                from services.trade_audit_service import record_audit_entry
                record_audit_entry(
                    getattr(bot, "_db", None),
                    trade,
                    gate_result=confidence_gate_result,
                    model_prediction=ai_prediction if "ai_prediction" in locals() else None,
                    regime=str(current_regime) if current_regime else None,
                    multipliers={
                        "smart_filter": smart_multiplier if "smart_multiplier" in locals() else None,
                        "confidence_gate": confidence_multiplier,
                        "regime": regime_multiplier if "regime_multiplier" in locals() else None,
                        "strategy_tilt": tilt_mult if "tilt_mult" in locals() else None,
                        "hrp_allocator": hrp_mult if "hrp_mult" in locals() else None,
                    },
                )
            except Exception as _audit_err:
                logger.debug(f"[TradeAudit] skipped: {_audit_err}")

            return trade

        except Exception as e:
            print(f"   ❌ Exception in _evaluate_opportunity: {e}")
            # 2026-04-30 v14: `logger.exception` writes the traceback
            # into the log line itself — `traceback.print_exc()` below
            # only reaches stdout, which can be lost when supervisor
            # rotates. Both paths kept so the operator's terminal AND
            # backend.log show the failure source.
            logger.exception(
                "Error evaluating opportunity (%s): %s",
                type(e).__name__, e,
            )
            import traceback
            traceback.print_exc()
            try:
                bot.record_rejection(
                    symbol=symbol if "symbol" in locals() else "?",
                    setup_type=setup_type if "setup_type" in locals() else "?",
                    direction=direction_str if "direction_str" in locals() else "long",
                    reason_code="evaluator_exception",
                    context={"error": str(e)[:300]},
                )
            except Exception:
                pass
            return None

    # ==================== HELPERS ====================

    def calculate_position_size(self, entry_price: float, stop_price: float, direction, bot: 'TradingBotService', atr: float = None, atr_percent: float = None, symbol: Optional[str] = None, bar_size: str = "5 mins", multipliers_out: Optional[Dict[str, Any]] = None, grade: Optional[str] = None, setup_type: Optional[str] = None, proven_outcomes: Optional[int] = None) -> Tuple[int, float]:
        """Calculate position size based on risk management rules with volatility and market regime adjustment.

        2026-04-28e: also applies a Volume-Profile path multiplier — if the
        price corridor between entry and stop is sitting in a thick HVN
        cluster, the trade is downsized (chop-through risk). Skipped
        silently when `symbol` is None (legacy callers) or the profile
        can't be computed.

        v19.34.156 (P3-A): also applies a `grade_multiplier` so A-grade
        setups trade full size and lower grades downscale proportionally:
          A = 1.0× | B = 0.7× | C = 0.3× | D / unknown = 0.1× (strict)
        Operator-tunable via env: `POSITION_SIZE_GRADE_{A,B,C,D}_MULT`.
        Per operator choice Q1b/Q2b, D and unknown both fall to 0.1× so
        every alert ALWAYS sizes — no silent "skip on missing grade"
        path. The vanishingly-small position is intentional: keeps real
        capital on the line for learning without meaningful risk.

        If `multipliers_out` (a dict) is supplied, the function records
        per-multiplier values into it under keys `volatility`, `regime`,
        `vp_path`, `grade`, `grade_multiplier` — used by
        `build_entry_context` to surface multiplier provenance for
        post-trade analytics.
        """
        from services.trading_bot_service import TradeDirection

        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0, 0
        adjusted_max_risk = bot.risk_params.max_risk_per_trade
        volatility_multiplier = 1.0
        if bot.risk_params.use_volatility_sizing and atr_percent:
            if atr_percent < 1.5:
                volatility_multiplier = 1.3
            elif atr_percent < 2.5:
                volatility_multiplier = 1.1
            elif atr_percent < 3.5:
                volatility_multiplier = 1.0
            elif atr_percent < 5.0:
                volatility_multiplier = 0.8
            else:
                volatility_multiplier = 0.6
            volatility_multiplier *= bot.risk_params.volatility_scale_factor
            adjusted_max_risk = bot.risk_params.max_risk_per_trade * volatility_multiplier
        regime_multiplier = 1.0
        if bot._current_regime:
            base_regime_multiplier = bot._regime_position_multipliers.get(bot._current_regime, 1.0)
            if bot._current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0
            elif bot._current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7
            else:
                regime_multiplier = base_regime_multiplier
            adjusted_max_risk *= regime_multiplier
            if regime_multiplier < 1.0:
                logger.debug(f"Position size adjusted by regime ({bot._current_regime}): {regime_multiplier:.0%}")

        # ── Volume-Profile path multiplier (2026-04-28e) ──
        # Asks: how thick is the price corridor between entry and stop?
        # Thick HVN cluster → likely chop through stop → downsize.
        # Clean LVN airpocket → fast move on either side → full size.
        vp_path_multiplier = 1.0
        try:
            db = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None else getattr(bot, "db", None))
            if symbol and db is not None:
                from services.smart_levels_service import compute_path_multiplier
                dir_str = "long" if direction == TradeDirection.LONG else "short"
                vpr = compute_path_multiplier(
                    db, symbol.upper(), bar_size,
                    float(entry_price), float(stop_price), dir_str,
                )
                vp_path_multiplier = float(vpr.get("multiplier", 1.0))
                if vp_path_multiplier < 1.0:
                    adjusted_max_risk *= vp_path_multiplier
                    logger.debug(
                        f"Position size adjusted by VP path ({vpr.get('reason')}, "
                        f"vol_pct={vpr.get('vol_pct')}): {vp_path_multiplier:.0%}"
                    )
        except Exception as exc:
            # Non-fatal: never let the profile lookup block trade execution.
            logger.debug(f"VP path multiplier skipped for {symbol}: {exc}")

        # ── v19.34.156 (P3-A) Grade multiplier ───────────────────────
        # Sized AFTER vp_path so all the prior gates (volatility, regime,
        # vp_path) have already shaped `adjusted_max_risk` — the grade
        # then applies a clean A/B/C/D scalar on top. Surfaced in
        # `multipliers_out` for postmortem analytics.
        grade_multiplier, normalized_grade = _resolve_grade_multiplier(grade)
        if grade_multiplier != 1.0:
            adjusted_max_risk *= grade_multiplier
            logger.debug(
                f"Position size adjusted by grade ({normalized_grade}): "
                f"{grade_multiplier:.0%}"
            )

        # ── v19.34.157 (P3-C) Mean-Reversion regime multiplier ──────
        # Looks up the (symbol, bar_size) MR metrics cache and applies
        # a setup-vs-regime alignment scalar:
        #   MR setups in MR_STRONG → 1.3×   |   MR in TRENDING → 0.5×
        #   Momentum in TRENDING   → 1.2×   |   Momentum in MR  → 0.7×
        #   Breakout in TRENDING   → 1.1×   |   Breakout in MR  → 0.8×
        # NEUTRAL / unknown setup always 1.0×. Operator choice 3a:
        # this is sizing-only, NOT a hard veto.  No-data → 1.0× (never
        # blocks a trade because the MR signal isn't available yet).
        mr_multiplier = 1.0
        mr_regime = "NEUTRAL"
        mr_reason = "no_lookup"
        mr_hurst: Optional[float] = None
        mr_half_life: Optional[float] = None
        try:
            db = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None else getattr(bot, "db", None))
            if symbol and db is not None:
                from services.mean_reversion_metrics import (
                    compute_mr_metrics, get_mr_multiplier,
                )
                _mr = compute_mr_metrics(db, symbol, bar_size=bar_size)
                mr_multiplier, mr_reason = get_mr_multiplier(_mr, setup_type)
                mr_regime = _mr.get("regime_tag") or "NEUTRAL"
                mr_hurst = _mr.get("hurst")
                mr_half_life = _mr.get("half_life_bars")
                if mr_multiplier != 1.0:
                    adjusted_max_risk *= mr_multiplier
                    logger.debug(
                        f"Position size adjusted by MR regime "
                        f"({mr_reason}): {mr_multiplier:.0%}"
                    )
        except Exception as mr_err:
            # Never let the MR lookup block trade execution.
            logger.debug(f"MR regime multiplier skipped for {symbol}: {mr_err}")

        # ── v19.34.294 (Audit Phase 3, P2-B) — cold-start size haircut ──────
        # Setups with fewer than COLD_START_MIN_OUTCOMES (default 20) graded
        # outcomes pass the scanner's EV gate on GRACE alone — they have no
        # proven expectancy yet. For UNMANAGED paper trading, full-size capital
        # on an unproven setup is the residual risk flagged in Phase 2 (P2-B).
        # Haircut their size to COLD_START_SIZE_MULT (default 0.33x) until they
        # earn enough outcomes. Applies ONLY when `proven_outcomes` is supplied
        # (the scanner auto-exec path stamps it); manual/legacy callers pass
        # None → no haircut (preserves existing behaviour). Fully env-tunable
        # and reversible (COLD_START_SIZE_MULT=1.0 disables).
        cold_start_multiplier = 1.0
        cold_start_applied = False
        if proven_outcomes is not None:
            import os as _os_cs

            def _csf(_k: str, _d: float) -> float:
                _v = _os_cs.environ.get(_k)
                if _v in (None, ""):
                    return _d
                try:
                    return float(_v)
                except (TypeError, ValueError):
                    return _d

            try:
                _cs_min = int(_csf("COLD_START_MIN_OUTCOMES", 20.0))
            except (TypeError, ValueError):
                _cs_min = 20
            _cs_mult = _csf("COLD_START_SIZE_MULT", 0.33)
            if int(proven_outcomes) < _cs_min and 0.0 < _cs_mult < 1.0:
                cold_start_multiplier = _cs_mult
                cold_start_applied = True
                adjusted_max_risk *= cold_start_multiplier
                logger.info(
                    "🐣 [v19.34.294 cold-start] %s — %d/%d proven outcomes; "
                    "sizing at %.0f%% (COLD_START_SIZE_MULT).",
                    symbol or "?", int(proven_outcomes), _cs_min, _cs_mult * 100,
                )
                # v19.34.296 — print() too: server.py has no logging.basicConfig
                # so service-module logger.info() is dropped from /tmp/backend.log.
                # print(flush=True) makes the haircut greppable (same pattern as
                # the v123 kill-switch monitor).
                print(
                    f"🐣 [v19.34.294 cold-start] {symbol or '?'} — "
                    f"{int(proven_outcomes)}/{_cs_min} proven outcomes; "
                    f"sizing at {_cs_mult * 100:.0f}% (COLD_START_SIZE_MULT).",
                    flush=True,
                )

        # ── v19.34.295 — per-setup size haircut (operator throttle) ─────────
        # Reduce size on chronically underperforming / over-traded setups
        # WITHOUT removing them (keeps collecting outcome data). Env-driven and
        # DEFAULT-OFF (empty → no-op), so deploying is behaviour-neutral until
        # the operator opts in — safe to apply mid-session. Format:
        #   SETUP_SIZE_HAIRCUTS="squeeze:0.33,vwap_fade:0.5"
        # Audit Phase 5: `squeeze` = 421 trades / 32% win / −$24k (biggest
        # single bleed). Base-keyed (squeeze_long/squeeze_short → "squeeze").
        setup_haircut_multiplier = 1.0
        setup_haircut_applied = False
        if setup_type:
            import os as _os_sh
            _raw_hc = (_os_sh.environ.get("SETUP_SIZE_HAIRCUTS", "") or "").strip()
            if _raw_hc:
                _hc_map = {}
                for _part in _raw_hc.split(","):
                    if ":" not in _part:
                        continue
                    _k, _v = _part.split(":", 1)
                    try:
                        _m = float(_v)
                    except (TypeError, ValueError):
                        continue
                    if 0.0 < _m <= 1.0:
                        _hc_map[_k.strip().lower()] = _m
                _base_setup = (str(setup_type).lower()
                               .split("_long")[0].split("_short")[0].strip())
                _hc = _hc_map.get(_base_setup) or _hc_map.get(str(setup_type).lower())
                if _hc and 0.0 < _hc < 1.0:
                    setup_haircut_multiplier = _hc
                    setup_haircut_applied = True
                    adjusted_max_risk *= _hc
                    logger.info(
                        "✂️ [v19.34.295 setup-haircut] %s sized at %.0f%% "
                        "(SETUP_SIZE_HAIRCUTS).", setup_type, _hc * 100,
                    )
                    # v19.34.296 — print() too (see cold-start note above) so the
                    # throttle is visible in /tmp/backend.log.
                    print(
                        f"✂️ [v19.34.295 setup-haircut] {setup_type} sized at "
                        f"{_hc * 100:.0f}% (SETUP_SIZE_HAIRCUTS).", flush=True,
                    )

        max_shares_by_risk = int(adjusted_max_risk / risk_per_share)
        max_position_value = bot.risk_params.starting_capital * (bot.risk_params.max_position_pct / 100)
        max_shares_by_capital = int(max_position_value / entry_price)

        # 2026-04-30 v19.4 — Absolute notional clamp.
        # `max_position_pct` floats with equity (50% of $1M = $500k vs 50%
        # of $250k = $125k). Operators often want a HARD ceiling (e.g.,
        # "never put more than $100k in one name regardless of equity")
        # so the bot doesn't auto-fatten when the paper account compounds.
        # Disabled when set to 0; otherwise the sizer can never produce a
        # notional larger than this value.
        max_notional = float(getattr(bot.risk_params, "max_notional_per_trade", 0) or 0)
        if max_notional > 0:
            max_shares_by_notional = int(max_notional / entry_price)
            shares = max(min(max_shares_by_risk, max_shares_by_capital, max_shares_by_notional), 1)
        else:
            shares = max(min(max_shares_by_risk, max_shares_by_capital), 1)

        # v19.34.29 — Sync sizer with execution_guardrails cap.
        # AMZN was vetoed daily by `notional_over_cap $106k>$100k` because
        # the sizer ignored the 40%-equity guardrail. Pre-clamp here.
        try:
            import os as _os
            def _envf(k, d):
                v = _os.environ.get(k)
                try: return float(v) if v not in (None, "") else d
                except: return d
            _gp = _envf("EXECUTION_GUARDRAIL_MAX_NOTIONAL_PCT", 0.40)
            _gt = _envf("EXECUTION_GUARDRAIL_NOTIONAL_CAP_TOLERANCE", 0.005)
            _eq = float(getattr(bot.risk_params, "starting_capital", 0) or 0)
            if _gp > 0 and _eq > 0 and entry_price > 0:
                _gc = _gp * _eq * (1.0 + _gt)
                _max_shares_by_guard = int(_gc / entry_price)
                if _max_shares_by_guard > 0:
                    shares = max(min(shares, _max_shares_by_guard), 1)
        except Exception as _e:
            logger.debug(f"execution-guardrail sizer pre-clamp skipped: {_e}")

        # 2026-05-01 v19.20 — Safety-cap-aware sizing (operator request).
        # The opportunity sizer and the downstream SafetyGuardrails had two
        # independent ceilings (max_position_pct=50% vs max_symbol_exposure_usd=$15k)
        # that routinely collided: sizer produced a $50k notional, safety
        # rejected it, the bot logged "symbol_exposure exceeds cap" every
        # cycle → Deep Feed flooded with rejections and no trades ever hit
        # the broker. Clamping the sizer here to the SMALLER of the two caps
        # means the bot sizes down to fit the safety rail instead of being
        # blocked by it. Existing exposure on the same symbol is subtracted
        # so stacking into an already-held name still respects the cap.
        try:
            from services.safety_guardrails import get_safety_guardrails
            _safety_cap = float(get_safety_guardrails().config.max_symbol_exposure_usd or 0)
            if _safety_cap > 0 and entry_price > 0:
                _existing_sym_exposure = 0.0
                if symbol:
                    sym_upper = symbol.upper()
                    for _t in (bot._open_trades or {}).values():
                        try:
                            if (getattr(_t, "symbol", "") or "").upper() == sym_upper:
                                _existing_sym_exposure += (
                                    float(getattr(_t, "entry_price", 0) or 0)
                                    * float(getattr(_t, "shares", 0) or 0)
                                )
                        except Exception:
                            continue
                _remaining_cap = max(0.0, _safety_cap - _existing_sym_exposure)
                _max_shares_by_safety = int(_remaining_cap / entry_price)
                if _max_shares_by_safety > 0:
                    shares = max(min(shares, _max_shares_by_safety), 1)
                else:
                    # Symbol already at/over cap — return 0 shares so the
                    # upstream flow rejects cleanly instead of wasting an
                    # evaluate → safety-block cycle.
                    #
                    # v19.34.70 — Tag this branch DISTINCTLY (operator
                    # discovered 2026-05-11 NBIS thrashing: bot kept
                    # re-evaluating NBIS every 30-60s, sizer kept
                    # producing 0 shares for cap reasons, rejection
                    # reason `position_size_zero` did NOT trigger the
                    # rejection cooldown — so the bot looped death-by-
                    # a-thousand-cuts style for 70+ minutes producing
                    # fragmented fills until something else broke it.
                    # The distinct reason code feeds the cooldown via
                    # `STRUCTURAL_REJECTION_REASONS` so subsequent
                    # cycles on (NBIS, setup) are skipped silently
                    # until either the cap clears or the cooldown
                    # expires.
                    shares = 0
                    if multipliers_out is not None:
                        multipliers_out["block_reason"] = "symbol_exposure_saturated"
                        multipliers_out["existing_sym_exposure"] = _existing_sym_exposure
                        multipliers_out["safety_cap_usd"] = _safety_cap
        except Exception as _cap_err:
            # Never let the safety-cap lookup break sizing; fall through to
            # legacy behaviour if the guardrail is misconfigured.
            logger.debug(f"safety-cap sizer clamp skipped: {_cap_err}")

        risk_amount = shares * risk_per_share
        if risk_amount > adjusted_max_risk:
            shares = int(adjusted_max_risk / risk_per_share)
            risk_amount = shares * risk_per_share
        # Surface multiplier provenance for entry_context analytics.
        if multipliers_out is not None:
            multipliers_out.update({
                "volatility": round(volatility_multiplier, 3),
                "regime": round(regime_multiplier, 3),
                "vp_path": round(vp_path_multiplier, 3),
                # v19.34.156 (P3-A) — grade provenance for post-trade analytics
                "grade": normalized_grade,
                "grade_multiplier": round(grade_multiplier, 3),
                # v19.34.157 (P3-C) — MR-regime provenance
                "mr_regime": mr_regime,
                "mr_multiplier": round(mr_multiplier, 3),
                "mr_hurst": round(mr_hurst, 3) if isinstance(mr_hurst, (int, float)) else None,
                "mr_half_life_bars": round(mr_half_life, 2) if isinstance(mr_half_life, (int, float)) else None,
                "mr_reason": mr_reason,
                # v19.34.294 (P2-B) — cold-start haircut provenance
                "cold_start_multiplier": round(cold_start_multiplier, 3),
                "cold_start_applied": cold_start_applied,
                "proven_outcomes": int(proven_outcomes) if proven_outcomes is not None else None,
                # v19.34.295 — per-setup haircut provenance
                "setup_haircut_multiplier": round(setup_haircut_multiplier, 3),
                "setup_haircut_applied": setup_haircut_applied,
            })
        return shares, risk_amount

    def calculate_atr_based_stop(self, entry_price: float, direction, atr: float, setup_type: str, bot: 'TradingBotService', trade_style: str = None) -> float:
        """Calculate stop loss based on ATR with setup-specific multiplier.

        v325 HSBG — when `trade_style` is passed, `atr` is treated as the
        canonical DAILY ATR and scalp/intraday distances are additionally
        scaled by the horizon fraction (√(hold/390)-style) so intraday
        brackets stop being sized for multi-day holds. Callers that omit
        `trade_style` (e.g. /retune-stop, which feeds a 5-MINUTE ATR)
        keep the exact pre-v325 behavior.
        """
        from services.trading_bot_service import TradeDirection

        multiplier, is_scalp_setup, resolution = self._resolve_atr_multiplier(setup_type, bot)
        if resolution == "horizon_fallback":
            logger.info(
                f"[atr_stop] setup_type={setup_type!r} not in SETUP_MULTIPLIERS — "
                f"using horizon-default multiplier={multiplier} (no longer silent base_atr fallback)."
            )
        elif resolution == "unknown":
            logger.warning(
                f"[atr_stop] UNKNOWN setup_type={setup_type!r} — clamped to base_atr_multiplier="
                f"{multiplier}. Add this setup to SETUP_MULTIPLIERS in opportunity_evaluator.py."
            )
        if not is_scalp_setup:
            # v19.34.112 — Scalp multipliers (0.4-0.5×) intentionally sit
            # BELOW the global `min_atr_multiplier` floor (typically 1.0×).
            # The floor exists to protect non-scalp setups from a noisy
            # config; scalps need to legitimately go tighter. Skip the
            # clamp ONLY for known scalp setups.
            multiplier = max(bot.risk_params.min_atr_multiplier, min(multiplier, bot.risk_params.max_atr_multiplier))
        stop_distance = atr * multiplier

        # ── v19.34.169 — POSITION/INVESTMENT stop_pct cap ─────────────
        # Multi-day setups (rs_leader_break, accumulation_entry,
        # power_trend_stack, stage_2_breakout, etc.) use 2.5-3.0× ATR
        # multipliers which on high-priced volatile names produce
        # 12-14% raw stop distances (e.g. ALAB $326 → $40/share stop).
        # Combined with the fixed risk_per_trade budget, share counts
        # collapse to 1-3. Cap the stop at 5% of entry for these
        # horizons so the risk-per-share stays reasonable while the
        # strategy keeps its multi-day intent. Operator-tunable via
        # env: `MAX_STOP_PCT_POSITION` / `MAX_STOP_PCT_INVESTMENT`.
        # Scalps and intraday setups untouched.
        try:
            import os as _os
            multi_day_caps = {
                # Setups with ATR multiplier >= 2.5 (investment + position)
                'investment': float(_os.environ.get("MAX_STOP_PCT_INVESTMENT", "0.05")),
                'position':   float(_os.environ.get("MAX_STOP_PCT_POSITION",   "0.05")),
            }
            # Bucket by multiplier — 2.5+ is investment/position horizon.
            cap_pct = None
            if multiplier >= 3.0:
                cap_pct = multi_day_caps['position']
            elif multiplier >= 2.5:
                cap_pct = multi_day_caps['investment']
            if cap_pct and entry_price > 0:
                cap_distance = entry_price * cap_pct
                if stop_distance > cap_distance:
                    logger.info(
                        f"[atr_stop] v169 cap: setup={setup_type} mult={multiplier} "
                        f"raw_stop={stop_distance:.3f} ({stop_distance/entry_price*100:.1f}%) "
                        f"→ capped at {cap_pct*100:.0f}% = {cap_distance:.3f}"
                    )
                    stop_distance = cap_distance
        except Exception as _cap_err:
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

    # ── v19.34.118 (Feb 2026) — Comprehensive setup ATR multipliers ──
    # Pre-v118 the multiplier table only covered 8 setup names. Every
    # other classifier output — `day_2_continuation` (carry-forward
    # overnight), `daily_breakout` (swing), `weekly_breakout`
    # (investment), `stage_2_breakout` (position), `orb_long_confirmed`
    # (intraday variant), `mean_reversion_short` (direction-suffixed),
    # etc. — fell through to `bot.risk_params.base_atr_multiplier`
    # (default 1.5×). For a Day-2 short like ONON / RJF, 1.5×ATR is a
    # ~3-hour intraday stop, not the wider swing budget the trade
    # actually needs. Conversely a `stage_2_breakout` getting 1.5×ATR
    # is way too tight for a 3-month position hold.
    #
    # SETUP_MULTIPLIERS now exhaustively keys every setup the scanner,
    # daily-scan, and carry-forward pipeline can emit. Direction- and
    # state-suffixed variants (`_long`, `_short`, `_confirmed`,
    # `approaching_`) normalize back to the canonical name. Anything
    # still not found falls back to a HORIZON-default (scalp / intraday
    # / swing / investment / position) instead of the legacy 1.5×, and
    # writes a structured log so we can add it explicitly next pass.
    SETUP_MULTIPLIERS: Dict[str, float] = {
        # ── SCALPS (0.4-0.5× ATR) ──────────────────────────────────────
        'scalp':                  0.5,
        '9_ema_scalp':            0.4,
        'nine_ema_scalp':         0.4,
        'spencer_scalp':          0.5,
        'abc_scalp':              0.5,
        'rubber_band_scalp_long': 0.5,
        'rubber_band_scalp_short':0.5,
        'breakout_scalp':         0.5,
        'hitchhiker':             0.5,
        'gap_give_go':            0.5,
        'gap_pick_roll':          0.5,
        'second_chance':          0.5,
        'backside':               0.5,
        'off_sides':              0.5,
        'fashionably_late':       0.5,
        'first_move_up':          0.5,
        'first_move_down':        0.5,
        'bella_fade':             0.5,
        'fading_bounce':          0.5,
        'volume_capitulation':    0.5,
        'time_of_day_fade':       0.5,
        'big_dog':                0.5,
        'puppy_dog':              0.5,
        'bouncy_ball':            0.5,
        # ── INTRADAY MOMENTUM (1.0-1.5× ATR) ───────────────────────────
        'tidal_wave':             1.25,
        'rubber_band':            1.0,
        'rubber_band_long':       1.0,
        'rubber_band_short':      1.0,
        'vwap_bounce':            1.0,
        'vwap_bounce_long':       1.0,
        'vwap_fade':              1.0,
        'vwap_fade_long':         1.0,
        'vwap_fade_short':        1.0,
        'vwap_reclaim_long':      1.0,
        'vwap_rejection':         1.0,
        'vwap_reversal':          1.0,
        'vwap_continuation':      1.25,
        'first_vwap_pullback':    1.0,
        'mean_reversion':         1.0,
        'mean_reversion_long':    1.0,
        'mean_reversion_short':   1.0,
        'gap_fade':               1.25,
        'gap_and_go':             1.25,
        'gap_fill_open':          1.25,
        'orb':                    1.25,
        'orb_long':               1.25,
        'orb_short':              1.25,
        'orb_long_confirmed':     1.25,
        'opening_drive':          1.25,
        'opening_range_break':    1.25,
        'short_orb':              1.25,
        'breakout':               1.5,
        'breakout_confirmed':     1.5,
        'breakdown':              1.5,
        'breakdown_confirmed':    1.5,
        'short_breakdown':        1.5,
        'momentum':               1.5,
        'momentum_breakout':      1.5,
        'momentum_continuation':  1.5,
        'squeeze':                1.5,
        'short_squeeze_intraday': 1.5,
        'hod_breakout':           1.5,
        'lod_breakdown':          1.5,
        'range_break':            1.5,
        'range_break_confirmed':  1.5,
        'premarket_high_break':   1.5,
        'back_through_open':      1.25,
        'up_through_open':        1.25,
        'lhld':                   1.25,
        'chart_pattern':          1.5,
        'relative_strength':      1.5,
        'relative_strength_leader':  1.5,
        'relative_strength_laggard': 1.5,
        'relative_weakness':      1.5,
        'breaking_news':          1.5,
        'the_3_30_trade':         1.25,
        'off_sides_short':        1.0,
        'abcd_short':             1.0,
        'pullback':               1.25,
        'ema_pullback':           1.25,
        'trade_2_hold':           1.5,
        # ── DAY-2 / CARRY-FORWARD (1.75× ATR) ──────────────────────────
        # These are overnight-held intraday trades carried into the
        # next session. Stops need slightly wider headroom for the
        # gap-open volatility window without bloating to full swing.
        'day_2':                  1.75,
        'day_2_continuation':     1.75,
        'carry_forward_watch':    1.75,
        'trend_continuation':     1.75,
        'trend_continuation_short': 1.75,  # v19.34.282
        # ── SWING (1.75-2.0× ATR, daily-bar driven) ───────────────────
        'daily_squeeze':          2.0,
        'daily_breakout':         2.0,
        'base_breakout':          2.0,
        'pocket_pivot':           1.75,
        'three_week_tight':       1.75,
        'vcp_breakout':           2.0,
        'bull_flag_break':        1.75,
        'bear_flag_break':        1.75,
        'ascending_triangle_break':  1.75,
        'descending_triangle_break': 1.75,
        'cup_with_high_handle':   2.0,
        'earnings_play':          2.0,
        # ── INVESTMENT (2.5× ATR, weekly-bar / multi-quarter) ──────────
        'weekly_breakout':        2.5,
        'weekly_base':            2.5,
        'multi_quarter_base_break':  2.5,
        'rs_leader_break':        2.5,
        'fifty_two_week_high_break': 2.5,
        'power_trend_stack':      2.5,
        'accumulation_entry':     2.5,
        # ── POSITION (3.0× ATR, Stage analysis / 200DMA) ──────────────
        'stage_1_to_2_transition': 3.0,
        'stage_2_breakout':        3.0,
        'stage_3_to_4_breakdown':  3.0,
        'golden_cross_filtered':   3.0,
        'death_cross_filtered':    3.0,
        'two_hundred_day_reclaim': 3.0,
        'two_hundred_day_loss':    3.0,
        # ── SYSTEM / RECONCILIATION TAGS ──────────────────────────────
        # These are stamped by reconcilers / importers, not the scanner.
        # Default to base intraday so existing positions don't get a
        # surprise re-stop.
        'reconciled_orphan':       1.5,
        'reconciled_excess_slice': 1.5,
        'imported_from_ib':        1.5,
        'manual':                  1.5,
        'bot_fired':               1.5,
        'default':                 1.5,
        'performance_review':      1.5,
        # ── Approaching / pre-trigger variants (intraday momentum) ────
        # Scanner emits these before the actual break confirms; same
        # horizon as the parent breakout, slightly tighter so the stop
        # doesn't sit past the breakout level itself.
        'approaching_hod':         1.5,
        'approaching_breakout':    1.5,
        'approaching_orb':         1.25,
        'approaching_range_break': 1.5,
    }

    _SCALP_SETUPS = frozenset({
        'scalp', '9_ema_scalp', 'nine_ema_scalp', 'spencer_scalp', 'abc_scalp',
        'rubber_band_scalp_long', 'rubber_band_scalp_short', 'breakout_scalp',
        'hitchhiker', 'gap_give_go', 'gap_pick_roll', 'second_chance',
        'backside', 'off_sides', 'fashionably_late', 'first_move_up',
        'first_move_down', 'bella_fade', 'fading_bounce', 'volume_capitulation',
        'time_of_day_fade', 'big_dog', 'puppy_dog', 'bouncy_ball',
    })

    # Horizon-default fallback when the setup_type lands here without an
    # exact key match (e.g. a new scanner-only variant before it's
    # explicitly cataloged). Derived from SETUP_REGISTRY default_style.
    _HORIZON_DEFAULTS: Dict[str, float] = {
        'scalp':      0.5,
        'intraday':   1.5,
        'swing':      1.75,
        'multi_day':  1.75,
        'investment': 2.5,
        'position':   3.0,
    }

    @classmethod
    def _normalize_setup_type(cls, setup_type: Optional[str]) -> str:
        """Strip direction / state suffixes and approaching_ prefixes so
        scanner variants resolve to a canonical SETUP_MULTIPLIERS key.

        E.g. `orb_long_confirmed` → tries `orb_long_confirmed` (hit),
        else `orb_long` (hit), else `orb` (hit). `approaching_orb` →
        `orb`. Keeps fully-qualified entries when they exist so the
        table can override the canonical default per direction.
        """
        if not setup_type:
            return ''
        s = setup_type.strip().lower()
        if s in cls.SETUP_MULTIPLIERS:
            return s
        for prefix in ('approaching_',):
            if s.startswith(prefix):
                trimmed = s[len(prefix):]
                if trimmed in cls.SETUP_MULTIPLIERS:
                    return trimmed
                s = trimmed
                break
        for suffix in ('_confirmed', '_long', '_short'):
            if s.endswith(suffix):
                trimmed = s[: -len(suffix)]
                if trimmed in cls.SETUP_MULTIPLIERS:
                    return trimmed
        return s

    @classmethod
    def _resolve_atr_multiplier(
        cls,
        setup_type: Optional[str],
        bot: 'TradingBotService',
    ) -> Tuple[float, bool, str]:
        """Resolve (multiplier, is_scalp_setup, resolution_kind) for a
        setup_type. resolution_kind is one of: `exact`, `normalized`,
        `horizon_fallback`, `unknown`."""
        raw = (setup_type or '').strip().lower()
        if raw in cls.SETUP_MULTIPLIERS:
            return cls.SETUP_MULTIPLIERS[raw], raw in cls._SCALP_SETUPS, 'exact'
        canonical = cls._normalize_setup_type(setup_type)
        if canonical and canonical in cls.SETUP_MULTIPLIERS:
            return (
                cls.SETUP_MULTIPLIERS[canonical],
                canonical in cls._SCALP_SETUPS,
                'normalized',
            )
        # Horizon-default fallback via SETUP_REGISTRY.
        try:
            from services.smb_integration import SETUP_REGISTRY
            cfg = SETUP_REGISTRY.get(canonical) or SETUP_REGISTRY.get(raw)
            if cfg is not None:
                style = cfg.default_style.value
                mult = cls._HORIZON_DEFAULTS.get(style, bot.risk_params.base_atr_multiplier)
                return mult, style == 'scalp', 'horizon_fallback'
        except Exception:
            pass
        return bot.risk_params.base_atr_multiplier, False, 'unknown'

    @staticmethod
    def score_to_grade(score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90: return "A+"
        if score >= 80: return "A"
        if score >= 70: return "B+"
        if score >= 60: return "B"
        if score >= 50: return "C"
        return "F"

    @staticmethod
    def estimate_duration(setup_type: str) -> str:
        """Estimate trade duration based on setup type"""
        durations = {
            "rubber_band": "30min - 2hr",
            "breakout": "1hr - 4hr",
            "vwap_bounce": "15min - 1hr",
            "squeeze": "2hr - 1day"
        }
        return durations.get(setup_type, "1hr - 4hr")

    def build_entry_context(
        self, alert: Dict, intelligence: Dict, regime: str,
        regime_score: float, filter_action: str, filter_win_rate: float,
        atr: float, atr_percent: float, confidence_gate_result: Dict = None,
        multipliers_meta: Optional[Dict[str, Any]] = None,
        ai_consultation_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build rich entry context capturing WHY this trade was taken.
        This snapshot records the conditions and signals at the moment of entry
        for post-trade analysis and AI learning.
        """
        ctx = {}

        # 1. Setup identification
        ctx["scanner_setup_type"] = alert.get("setup_type", "")
        ctx["strategy_name"] = alert.get("strategy_name", "")
        ctx["setup_category"] = alert.get("setup_category", "")
        ctx["score"] = alert.get("score", 0)
        ctx["trigger_probability"] = alert.get("trigger_probability", 0)
        ctx["tape_confirmation"] = alert.get("tape_confirmation", False)
        ctx["priority"] = alert.get("priority", "medium")
        if isinstance(ctx["priority"], type) and hasattr(ctx["priority"], "value"):
            ctx["priority"] = ctx["priority"].value

        # v19.34.173 — propagate learning_only flag from F-micro alerts so
        # setup_grading_service._aggregate_day excludes them from avg_R.
        ctx["learning_only"] = bool(alert.get("learning_only", False))

        # 2. Market regime context
        ctx["market_regime"] = regime
        ctx["regime_score"] = regime_score

        # 3. Strategy filter context (smart filter)
        ctx["filter_action"] = filter_action
        ctx["filter_win_rate"] = filter_win_rate
        ctx["strategy_win_rate"] = alert.get("strategy_win_rate", 0)

        # 4. Volatility context
        ctx["atr"] = round(atr, 4) if atr else 0
        ctx["atr_percent"] = round(atr_percent, 2) if atr_percent else 0
        ctx["rvol"] = alert.get("rvol", 0) or alert.get("relative_volume", 0)

        # v19.34.251 (F2) — persist catalyst_tag + signed gap_pct at entry so the
        # Phase-D edge ranker can bucket realized trade_outcomes by catalyst+gap.
        # Stamped on the alert at scan time (enhanced_scanner._process_new_alert);
        # captured here into entry_context, which both the live close path and
        # the learning_reconciler read when writing trade_outcomes.
        ctx["catalyst_tag"] = (alert.get("catalyst_tag") or "") or ""
        ctx["catalyst_summary"] = alert.get("catalyst_summary", "") or ""
        try:
            ctx["gap_pct"] = round(float(alert.get("gap_pct", 0.0) or 0.0), 2)
        except (TypeError, ValueError):
            ctx["gap_pct"] = 0.0

        # 5. Technical signals from intelligence
        if intelligence:
            tech = intelligence.get("technicals") or {}
            ctx["technicals"] = {
                "trend": tech.get("trend", ""),
                "rsi": tech.get("momentum", 0),
                "vwap_relation": tech.get("vwap_relation", ""),
                "volume_trend": tech.get("volume_trend", ""),
                "support_nearby": tech.get("near_support", False),
                "resistance_nearby": tech.get("near_resistance", False),
            }

            if intelligence.get("news"):
                ctx["catalyst"] = {
                    "has_catalyst": True,
                    "headline_count": len(intelligence["news"]) if isinstance(intelligence["news"], list) else 1,
                }

            if intelligence.get("institutional"):
                inst = intelligence["institutional"]
                ctx["institutional"] = {
                    "dark_pool_signal": inst.get("dark_pool_signal", ""),
                    "block_trade_alert": inst.get("block_trade_alert", False),
                }

        # 6. Time context
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        ctx["entry_time_et"] = now_et.strftime("%H:%M:%S")
        ctx["time_window"] = self.classify_time_window(now_et)

        # 7. AI prediction context (if available)
        if hasattr(self, '_last_ai_prediction') and self._last_ai_prediction:
            pred = self._last_ai_prediction
            if pred.get("symbol") == alert.get("symbol"):
                ctx["ai_prediction"] = {
                    "direction": pred.get("direction", ""),
                    "confidence": pred.get("confidence", 0),
                    "regime_aligned": pred.get("regime_adjustment", {}).get("regime_aligned"),
                }

        # 8. Confidence gate context
        if confidence_gate_result:
            ctx["confidence_gate"] = {
                "decision": confidence_gate_result.get("decision", ""),
                "decision_id": confidence_gate_result.get("decision_id", ""),  # v19.34.311b: exact attribution key
                "confidence_score": confidence_gate_result.get("confidence_score", 0),
                "position_multiplier": confidence_gate_result.get("position_multiplier", 1.0),
                "trading_mode": confidence_gate_result.get("trading_mode", ""),
                "ai_regime": confidence_gate_result.get("ai_regime", ""),
                "reasoning": confidence_gate_result.get("reasoning", [])[:5],
            }
            # Include live model prediction if available
            if confidence_gate_result.get("live_prediction"):
                pred = confidence_gate_result["live_prediction"]
                ctx["confidence_gate"]["live_prediction"] = {
                    "direction": pred.get("direction", "flat"),
                    "confidence": pred.get("confidence", 0),
                    "model_used": pred.get("model_used", ""),
                }
            # Include learning loop feedback if available
            if confidence_gate_result.get("learning_feedback"):
                fb = confidence_gate_result["learning_feedback"]
                ctx["confidence_gate"]["learning_feedback"] = {
                    "points": fb.get("points", 0),
                    "reasoning": fb.get("reasoning", ""),
                }
            # Include cross-model agreement (GAP 4)
            if confidence_gate_result.get("cross_model_agreement"):
                ctx["confidence_gate"]["cross_model_agreement"] = confidence_gate_result["cross_model_agreement"]

        # 9. Post-gate TQS recalculation (GAP 3: AI-enriched quality score)
        pre_gate_tqs = alert.get("tqs_score", 0)
        post_gate_tqs = alert.get("_post_gate_tqs_score")
        if post_gate_tqs:
            ctx["tqs"] = {
                "pre_gate_score": round(pre_gate_tqs, 1) if pre_gate_tqs else None,
                "post_gate_score": round(post_gate_tqs, 1),
                "post_gate_grade": alert.get("_post_gate_tqs_grade", ""),
                "post_gate_action": alert.get("_post_gate_tqs_action", ""),
                "delta": round(post_gate_tqs - pre_gate_tqs, 1) if pre_gate_tqs else None,
                # v19.34.175 — unified grade + full 5-pillar breakdown for the
                # operator UI drill-down (prefer the richer post-gate data).
                "unified_grade": alert.get("_post_gate_tqs_grade") or alert.get("tqs_grade") or "",
                "score": round(post_gate_tqs, 1),
                "pillar_scores": alert.get("_post_gate_tqs_pillars") or alert.get("tqs_pillar_scores") or {},
                "pillar_grades": alert.get("_post_gate_tqs_pillar_grades") or alert.get("tqs_pillar_grades") or {},
                "breakdown": alert.get("_post_gate_tqs_breakdown") or alert.get("tqs_breakdown") or {},
                "weights": alert.get("_post_gate_tqs_weights") or alert.get("tqs_weights") or {},
            }
        elif pre_gate_tqs:
            ctx["tqs"] = {
                "pre_gate_score": round(pre_gate_tqs, 1),
                # v19.34.175 — pre-gate path (no confidence-gate live prediction).
                "unified_grade": alert.get("tqs_grade") or "",
                "score": round(pre_gate_tqs, 1),
                "pillar_scores": alert.get("tqs_pillar_scores") or {},
                "pillar_grades": alert.get("tqs_pillar_grades") or {},
                "breakdown": alert.get("tqs_breakdown") or {},
                "weights": alert.get("tqs_weights") or {},
            }

        # 10. Liquidity-aware multipliers (2026-04-28e)
        # Captures the full provenance of every dial that touched the
        # trade: the volatility / regime / VP-path multipliers from
        # `calculate_position_size`, plus stop-guard + target-snap
        # results. Powers `/api/trading-bot/multiplier-analytics`.
        if multipliers_meta:
            mult_ctx: Dict[str, Any] = {}
            pos_m = multipliers_meta.get("position") or {}
            if pos_m:
                mult_ctx["volatility"] = pos_m.get("volatility", 1.0)
                mult_ctx["regime"]     = pos_m.get("regime", 1.0)
                mult_ctx["vp_path"]    = pos_m.get("vp_path", 1.0)
                # v19.34.159 — surface v156 grade-scaling + v157 mean-reversion
                # regime fields that previously landed in `position_multipliers`
                # but never propagated to `entry_context.multipliers`. Operator
                # needs these for the "Why this size?" UI tooltip so every fill
                # explains its own sizing chain (grade × regime × MR-fit).
                # Defensive: each key is only emitted when present, so legacy
                # trades (pre-v156) still render cleanly.
                for _k in ("grade", "grade_multiplier",
                          "mr_regime", "mr_multiplier",
                          "mr_hurst", "mr_half_life_bars", "mr_reason"):
                    if _k in pos_m and pos_m[_k] is not None:
                        mult_ctx[_k] = pos_m[_k]

            sg = multipliers_meta.get("stop_guard") or {}
            if isinstance(sg, dict) and sg:
                mult_ctx["stop_guard"] = {
                    "snapped":        bool(sg.get("snapped", False)),
                    "reason":         sg.get("reason"),
                    "level_kind":     sg.get("level_kind"),
                    "level_price":    sg.get("level_price"),
                    "level_strength": sg.get("level_strength"),
                    "original_stop":  sg.get("original_stop"),
                    "widen_pct":      sg.get("widen_pct"),
                }

            ts = multipliers_meta.get("target_snap")
            if isinstance(ts, list) and ts:
                # Compact per-target snap log: only fields useful for analytics.
                mult_ctx["target_snap"] = [
                    {
                        "snapped":         bool(d.get("snapped", False)),
                        "reason":          d.get("reason"),
                        "level_kind":      d.get("level_kind"),
                        "level_price":     d.get("level_price"),
                        "shift_pct":       d.get("shift_pct"),
                        "original_target": d.get("original_target"),
                        "target":          d.get("target"),
                    }
                    for d in ts if isinstance(d, dict)
                ]

            if mult_ctx:
                ctx["multipliers"] = mult_ctx

        # 11. AI module decisions (2026-04-28f) — Bear/Bull debate,
        # AI risk manager, institutional flow, time series forecast.
        # Surfaced HERE in entry_context so they're queryable from
        # `bot_trades` and feed analytics + the Q3 verification curl.
        # Was previously only landing under `explanation.ai_consultation`.
        ai_ctx = self._build_ai_modules_ctx(ai_consultation_result)
        if ai_ctx is not None:
            ctx["ai_modules"] = ai_ctx

        return ctx

    @staticmethod
    def _build_ai_modules_ctx(ai_consultation_result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Translate a raw AI consultation result into the shape that
        lives under `entry_context.ai_modules` and is read by the
        ai_decision_audit_service (consulted_count / aligned_count).

        Returns None when there's nothing to record — caller must guard.

        v19.34.67 — extracted so the consult write-back path (right
        after the consultation completes in evaluate_opportunity) can
        reuse the same mapping. Previously the consult result was only
        consumed inside build_entry_context, but build_entry_context
        runs BEFORE the consult fires (variable-ordering bug masked by
        a 2026-04-29 `ai_consultation_result = None` defensive init),
        so ai_modules was always empty across all live trades.
        """
        if not (ai_consultation_result and isinstance(ai_consultation_result, dict)):
            return None
        ai_ctx: Dict[str, Any] = {
            "consulted":       True,
            "proceed":         bool(ai_consultation_result.get("proceed", True)),
            "size_adjustment": ai_consultation_result.get("size_adjustment"),
            "summary":         ai_consultation_result.get("summary"),
        }
        # Fold in per-module results when present. Source keys come
        # from the consult layer; ec_keys are the canonical fields the
        # audit service reads from bot_trades.entry_context.ai_modules.
        for module_key, ec_key in (
            ("debate",         "debate"),
            ("risk_assessment","risk_manager"),
            ("institutional",  "institutional_flow"),
            ("time_series",    "time_series"),
        ):
            m = ai_consultation_result.get(module_key)
            if m:
                ai_ctx[ec_key] = m
        return ai_ctx

    @staticmethod
    def _target_ladder_rungs(alert, setup_type):
        """v19.34.112 / v19.34.181 — R-multiple target ladder keyed off
        trade_style (with setup_type fallback). Returned rungs are applied
        to the per-share risk to build timeframe-appropriate targets:
          • Scalp     → [1.0R, 1.5R]
          • Intraday  → [1.5R, 2.5R]
          • Position/Investment → [2R, 4R, 8R]   (runner-friendly)
          • Swing/Multi-day/unknown → [1.5R, 2.5R, 4R]  (legacy default)
        """
        trade_style_lower = (
            (alert.get('trade_style') if isinstance(alert, dict) else None) or ''
        ).strip().lower()
        setup_lower = (setup_type or '').strip().lower()
        if (trade_style_lower == 'scalp'
                or setup_lower in {'scalp', 'nine_ema_scalp',
                                   'spencer_scalp', 'abc_scalp'}):
            return [1.0, 1.5]
        if trade_style_lower in {'position', 'investment'}:
            return [2.0, 4.0, 8.0]
        if trade_style_lower == 'intraday':
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
        """Classify the current ET time into a trading time window."""
        h, m = now_et.hour, now_et.minute
        t = h * 60 + m
        if t < 9 * 60 + 30:
            return "pre_market"
        elif t < 9 * 60 + 45:
            return "opening_auction"
        elif t < 10 * 60:
            return "opening_drive"
        elif t < 10 * 60 + 30:
            return "morning_momentum"
        elif t < 11 * 60 + 30:
            return "morning_session"
        elif t < 12 * 60:
            return "late_morning"
        elif t < 13 * 60 + 30:
            return "midday"
        elif t < 15 * 60:
            return "afternoon"
        elif t < 16 * 60:
            return "power_hour"
        else:
            return "after_hours"

    def generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float], intelligence: Dict, bot: 'TradingBotService'):
        """Generate detailed explanation for the trade with intelligence data"""
        from services.trading_bot_service import TradeExplanation

        symbol = alert.get('symbol', '')
        setup_type = alert.get('setup_type', '')
        direction = alert.get('direction', 'long')

        risk_per_share = abs(entry - stop)
        total_risk = shares * risk_per_share
        target_1_profit = abs(targets[0] - entry) * shares if targets else 0

        # Build technical reasons from alert + intelligence
        technical_reasons = alert.get('technical_reasons', [
            f"Setup type: {setup_type}",
            f"Score: {alert.get('score', 'N/A')}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%"
        ])

        if intelligence and intelligence.get('technicals'):
            tech = intelligence['technicals']
            if tech.get('trend'):
                technical_reasons.append(f"Trend: {tech['trend']}")
            if tech.get('momentum'):
                technical_reasons.append(f"RSI: {tech['momentum']:.0f}")
            if tech.get('volume_trend'):
                technical_reasons.append(f"Volume: {tech['volume_trend']}")

        fundamental_reasons = alert.get('fundamental_reasons', [])
        if intelligence and intelligence.get('news'):
            news = intelligence['news']
            if news.get('sentiment'):
                fundamental_reasons.append(f"News sentiment: {news['sentiment']}")
            if news.get('key_topics'):
                fundamental_reasons.append(f"Key topics: {', '.join(news['key_topics'])}")
            if news.get('summary'):
                fundamental_reasons.append(f"Latest: {news['summary'][:100]}...")

        all_warnings = alert.get('warnings', []).copy()
        if intelligence:
            all_warnings.extend(intelligence.get('warnings', []))

        confidence_factors = [
            f"Quality score: {alert.get('score', 0)}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%",
            f"Risk/Reward: {abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
        ]

        if intelligence and intelligence.get('enhancements'):
            confidence_factors.extend(intelligence['enhancements'])

        return TradeExplanation(
            summary=f"{setup_type.replace('_', ' ').title()} setup identified on {symbol}. "
                    f"{'Buying' if direction == 'long' else 'Shorting'} {shares} shares at ${entry:.2f} "
                    f"with stop at ${stop:.2f} and target at ${targets[0]:.2f}.",

            setup_identified=alert.get('headline', f"{setup_type} pattern detected"),

            technical_reasons=technical_reasons,

            fundamental_reasons=fundamental_reasons,

            risk_analysis={
                "risk_per_share": f"${risk_per_share:.2f}",
                "total_risk": f"${total_risk:.2f}",
                "max_risk_allowed": f"${bot.risk_params.max_risk_per_trade:.2f}",
                "risk_pct_of_capital": f"{(total_risk / bot.risk_params.starting_capital * 100):.2f}%",
                "risk_reward_ratio": f"{abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
            },

            entry_logic=f"Enter at ${entry:.2f} when price reaches trigger level. "
                       f"Current price is ${alert.get('current_price', 0):.2f}.",

            exit_logic=f"Stop loss at ${stop:.2f} ({(risk_per_share/entry*100):.1f}% from entry). "
                      f"Primary target at ${targets[0]:.2f} ({(abs(targets[0]-entry)/entry*100):.1f}% gain). "
                      f"Consider scaling out at subsequent targets.",

            position_sizing_logic=f"Position size: {shares} shares (${shares * entry:,.2f} value). "
                                 f"Based on max risk ${bot.risk_params.max_risk_per_trade:,.0f} "
                                 f"÷ risk per share ${risk_per_share:.2f} = {int(bot.risk_params.max_risk_per_trade/risk_per_share)} max shares. "
                                 f"Capped at {bot.risk_params.max_position_pct}% of capital.",

            confidence_factors=confidence_factors,

            warnings=all_warnings
        )
