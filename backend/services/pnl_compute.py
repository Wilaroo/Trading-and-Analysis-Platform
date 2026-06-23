"""
pnl_compute.py — v19.34.123 (Feb 2026)
─────────────────────────────────────────────────────────────────────────────
Shared close-PnL writer for every close path that doesn't go through
`position_manager.close_trade`.

WHY THIS EXISTS:
  Pre-v123 only `position_manager.close_trade()` computed `realized_pnl`
  on close. Every other close path — `operator_external_flatten`,
  `zombie_cleanup_v19_34_19`, `shrunk_to_zero_v19_34_20b`,
  `wrong_direction_phantom_swept_v19_29`, `_phantom_recovery_v19_34_27`,
  the OCA-ext detection path — set `status=CLOSED` and `exit_price` but
  left `realized_pnl` and `net_pnl` at their initial 0/None values.

  Result: `_daily_stats.net_pnl` aggregator saw ~$0 across most closes
  even when the broker showed −$25k. The kill-switch (which reads
  `_daily_stats.net_pnl`) couldn't fire. Setup grading was blind. The
  Closed Today panel showed dozens of "$0.00" rows that were actually
  realized losses.

  Surfaced during the Feb 2026 −$25k incident; mongoshell aggregate over
  `bot_trades` confirmed ~90% of closed rows had `net_pnl: 0 / null`.

CONTRACT:
  This module computes `realized_pnl` and `net_pnl` for a trade-shaped
  object at close time. It is INTENTIONALLY tolerant of partial data
  (best-effort fallback chain on exit_price) because the silent close
  paths are exactly the ones where IB doesn't hand us a fill — operator
  closed in TWS, OCA fired externally, zombie cleanup ran post-fact.

USAGE:
  Every silent close path replaces this pattern:
      trade.status = TradeStatus.CLOSED
      trade.closed_at = now_iso
      trade.close_reason = "<reason>"
      trade.unrealized_pnl = 0
  with:
      apply_close_pnl(trade, reason="<reason>")
      trade.status = TradeStatus.CLOSED
      # closed_at / close_reason / unrealized_pnl set by apply_close_pnl

  Returns the dict used (for logging / tests):
      {realized_pnl, net_pnl, exit_price, exit_price_source, commission}
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── v19.34.124 — alert_outcomes writer (best-effort, fire-and-forget) ──
# Synchronous pymongo client cached on first call. Falls back to a no-op
# silently if MONGO_URL is missing (preview pod, tests, etc.).

_AO_CLIENT = None  # cached MongoClient
_AO_DB = None


def _get_outcomes_collection():
    """Lazy-init the alert_outcomes collection handle. Returns None
    when MongoDB is unreachable / not configured so callers can skip
    cleanly.

    v19.34.396 — prefer the app's SHARED, proven-healthy DB handle (the
    same client that already writes bot_trades) over a private lazy
    client. The private client was a single point of SILENT failure:
    once its first connect timed out (1.5s) or its cached handle went
    stale, every subsequent close wrote NOTHING for days while logging
    only at DEBUG (the 2026-06-05 → 06-23 alert_outcomes outage)."""
    global _AO_CLIENT, _AO_DB
    if _AO_DB is None:
        try:
            from database import get_database
            shared = get_database()
            if shared is not None:
                _AO_DB = shared
        except Exception as e:
            logger.debug("[pnl_compute] shared db handle unavailable: %s", e)
    if _AO_DB is not None:
        return _AO_DB["alert_outcomes"]
    import os
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        return None
    try:
        from pymongo import MongoClient
        _AO_CLIENT = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        _AO_DB = _AO_CLIENT[os.environ.get("DB_NAME", "tradecommand")]
        return _AO_DB["alert_outcomes"]
    except Exception as e:
        logger.warning(
            "[pnl_compute] alert_outcomes mongo init FAILED — outcomes will "
            "NOT persist until this recovers: %s", e,
        )
        return None


def _hold_seconds(trade: Any) -> Optional[float]:
    """Best-effort hold time (s) from executed_at -> closed_at. v19.34.240."""
    a = getattr(trade, "executed_at", None) or getattr(trade, "created_at", None)
    b = getattr(trade, "closed_at", None)
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db_ = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        return (db_ - da).total_seconds()
    except Exception:
        return None


def _backfill_excursion_floor(trade: Any, mfe_r_floor: float, mae_r_floor: float) -> None:
    """v19.34.240 (Part B) — fill mfe_r/mae_r on the trade + bot_trades doc from
    the realized entry->exit excursion ONLY when the manage loop left them 0
    (sub-minute closes never accumulated a tick). Never overwrites a real peak."""
    if _get_outcomes_collection() is None or _AO_DB is None:
        return
    cur_mfe = float(getattr(trade, "mfe_r", 0) or 0)
    cur_mae = float(getattr(trade, "mae_r", 0) or 0)
    set_fields: Dict[str, Any] = {}
    if cur_mfe == 0 and mfe_r_floor:
        v = round(float(mfe_r_floor), 3)
        set_fields["mfe_r"] = v
        try:
            trade.mfe_r = v
        except Exception:
            pass
    if cur_mae == 0 and mae_r_floor:
        v = round(float(mae_r_floor), 3)
        set_fields["mae_r"] = v
        try:
            trade.mae_r = v
        except Exception:
            pass
    if set_fields:
        set_fields["excursion_floor_source"] = "pnl_compute_v19_34_240"
        tid = getattr(trade, "id", None)
        if tid:
            _AO_DB["bot_trades"].update_one(
                {"$or": [{"trade_id": tid}, {"id": tid}]}, {"$set": set_fields}
            )


def _record_alert_outcome_bestEffort(
    trade: Any, reason: str, pnl: Dict[str, float],
    exit_price: float, exit_source: str,
) -> None:
    """Write one row to `alert_outcomes` from the trade's data. This is
    intentionally schema-COMPATIBLE with `enhanced_scanner.record_alert_outcome`
    so consumers (setup-grading, learning loop, /diagnostic/setup-winrate-
    breakdown) can read both without branching."""
    global _AO_DB, _AO_CLIENT
    coll = _get_outcomes_collection()
    if coll is None:
        return
    realized = pnl.get("realized_pnl", 0.0)
    # Outcome derived from realized PnL (single source of truth post-v123).
    if realized > 0:
        outcome = "won"
    elif realized < 0:
        outcome = "lost"
    else:
        outcome = "scratch"

    # Best-effort R-multiple: (exit - entry) / (entry - stop)
    r_multiple = 0.0
    try:
        entry = float(getattr(trade, "fill_price", 0) or 0)
        stop = float(getattr(trade, "stop_price", 0) or getattr(trade, "stop_loss", 0) or 0)
        if entry > 0 and stop > 0:
            risk_per_share = abs(entry - stop)
            if risk_per_share > 0:
                d_obj = getattr(trade, "direction", None)
                dv = getattr(d_obj, "value", str(d_obj) if d_obj else "long").lower()
                if dv == "long":
                    pps = exit_price - entry
                else:
                    pps = entry - exit_price
                # v19.34.396 — restore the single-leg R assignment that a prior
                # refactor dropped (left r_multiple pinned at 0.0 for every
                # single-exit close → TQS grade separation read all-zero R).
                r_multiple = round(pps / risk_per_share, 4)
    except Exception:
        pass

    # v19.34.306 — BLENDED trade R. The single-leg calc above (final exit_price
    # vs entry over the FULL risk) OVER-states trades that scale out and trail a
    # runner: alert_outcomes is upserted 1-row-per-trade, so the row ends up
    # carrying the runner leg's big R as if the whole position achieved it
    # (e.g. daily_breakout +2.32R / ~8R avg winner over n=17). When scale-out
    # partials exist, recompute R as the POSITION-WEIGHTED total realized P&L
    # over the full-position risk dollars. Env-gated (TQS_BLENDED_R, default on).
    # Single-exit trades have no partials → keep the single-leg value above.
    if os.environ.get("TQS_BLENDED_R", "true").strip().lower() not in ("0", "false", "no", "off"):
        try:
            _soc = getattr(trade, "scale_out_config", None) or {}
            _partials = _soc.get("partial_exits", []) or []
            if _partials:
                _entry = float(getattr(trade, "fill_price", 0) or 0)
                _stop = float(getattr(trade, "stop_price", 0)
                              or getattr(trade, "stop_loss", 0) or 0)
                _orig = int(abs(getattr(trade, "original_shares", 0)
                                or getattr(trade, "shares", 0) or 0))
                _risk_dollars = abs(_entry - _stop) * _orig
                if _risk_dollars > 0:
                    _partial_pnl = sum(float(p.get("pnl", 0) or 0) for p in _partials)
                    _total_realized = _partial_pnl + float(pnl.get("realized_pnl", 0) or 0)
                    r_multiple = round(_total_realized / _risk_dollars, 3)
        except Exception:
            pass

    # v19.34.307 — risk-basis sanity guard. A trade with a real protective stop
    # loses ~-1R (a bit more on slippage/gaps). An |R| beyond ±20 means the risk
    # basis (entry/stop) is corrupt — e.g. stop ≈ entry → a tiny denominator
    # produced the -28R seen on some gap_give_go closes. Flag such rows so the
    # learning loop / EV recompute can exclude them, and clamp the stored value
    # so the raw scoreboard can't be polluted by garbage-in risk inputs.
    r_risk_unreliable = False
    try:
        _e = float(getattr(trade, "fill_price", 0) or 0)
        _s = float(getattr(trade, "stop_price", 0) or getattr(trade, "stop_loss", 0) or 0)
        if _e > 0 and (abs(_e - _s) < max(0.01, 0.0015 * _e)):
            r_risk_unreliable = True
        if abs(r_multiple) > 20.0:
            r_risk_unreliable = True
            r_multiple = max(-20.0, min(20.0, r_multiple))
    except Exception:
        pass

    # v19.34.240 — trade-outcome hygiene: classify GENUINE strategy close vs
    # execution/reconciliation artifact (phantom sweep, sub-minute external OCA
    # unwind, operator flatten, corrupt entry==exit pnl). Non-genuine closes are
    # tagged + EXCLUDED from the strategy_stats EV feed so the setup scoreboard
    # isn't polluted by drift/phantom wreckage (see diag_accum_oca_drill).
    # v19.34.263 — effective (reclassified) close reason for external/OCA bracket
    # fills. Stamped onto the alert_outcome so scalp/intraday analytics can read
    # the TRUE exit kind (target / stop_loss / external_partial) instead of the
    # opaque `oca_closed_externally`. Default = the raw reason (no reclass).
    _effective_reason = reason
    _reclass_method = "none"
    try:
        from services.trade_outcome_hygiene import (
            classify_close, excursion_floor, reclassify_external_exit,
        )
        _entry_px = float(getattr(trade, "fill_price", 0) or 0)
        _stop_px = float(getattr(trade, "stop_price", 0) or getattr(trade, "stop_loss", 0) or 0)
        _dir_obj = getattr(trade, "direction", None)
        _dir = getattr(_dir_obj, "value", str(_dir_obj) if _dir_obj else "long").lower()
        _tps = getattr(trade, "target_prices", None)
        if not _tps:
            _t1 = getattr(trade, "tp_price", None) or getattr(trade, "target", None)
            _tps = [_t1] if _t1 else []
        _shares = pnl.get("shares") or getattr(trade, "shares", None)
        _genuine, _hyg_tag = classify_close(
            close_reason=reason,
            entered_by=str(getattr(trade, "entered_by", "") or ""),
            entry_price=_entry_px, exit_price=exit_price,
            net_pnl=pnl.get("net_pnl", 0.0), hold_seconds=_hold_seconds(trade),
            setup_type=str(getattr(trade, "setup_type", "") or ""),
            direction=_dir, stop_price=_stop_px, target_prices=_tps,
            realized_pnl=realized, shares=_shares,
        )
        _eff, _reclass_method, _, _ = reclassify_external_exit(
            close_reason=reason, direction=_dir, entry_price=_entry_px,
            exit_price=exit_price, stop_price=_stop_px, target_prices=_tps,
            realized_pnl=realized, shares=_shares,
        )
        if _eff:
            _effective_reason = _eff
        _mfe_r_floor, _mae_r_floor = excursion_floor(_dir, _entry_px, exit_price, _stop_px)
    except Exception:
        _genuine, _hyg_tag, _mfe_r_floor, _mae_r_floor = True, "genuine", 0.0, 0.0

    doc = {
        # Use trade.id as the de-duplication / join key. Schema is a
        # SUPERSET of scanner's writer — extra fields are additive.
        "alert_id": getattr(trade, "id", None) or getattr(trade, "alert_id", None),
        "trade_id": getattr(trade, "id", None),
        "symbol": getattr(trade, "symbol", None),
        "setup_type": getattr(trade, "setup_type", None),
        "direction": (lambda d: getattr(d, "value", str(d) if d else None))(
            getattr(trade, "direction", None)
        ),
        "outcome": outcome,
        "pnl": realized,
        "net_pnl": pnl.get("net_pnl", 0.0),
        "r_multiple": r_multiple,
        # v19.34.307 — corrupt entry/stop basis (R clamped/flagged above).
        "r_risk_unreliable": r_risk_unreliable,
        # v19.34.89 — trade_grade fallback chain.
        # Historical bug: writer read ONLY `trade.trade_grade`, but the
        # canonical SMB grade (set by setup_grader at signal time) lives
        # on `trade.smb_grade`. Result: ~180 `alert_outcomes` docs had
        # `trade_grade=None`, breaking `setup_retro.py`'s A/B/C bucket
        # analysis. Fall back to `smb_grade` when `trade_grade` is unset.
        "trade_grade": (
            getattr(trade, "trade_grade", None)
            or getattr(trade, "smb_grade", None)
        ),
        "entry_price": getattr(trade, "fill_price", None),
        "exit_price": exit_price,
        "exit_price_source": exit_source,
        "stop_loss": getattr(trade, "stop_price", None) or getattr(trade, "stop_loss", None),
        "target": getattr(trade, "tp_price", None) or getattr(trade, "target", None),
        "shares": pnl.get("shares") or getattr(trade, "shares", None),
        "close_reason": reason,
        "closed_at": getattr(trade, "closed_at", datetime.now(timezone.utc).isoformat()),
        "recorded_by": "pnl_compute_v19_34_124",
        # v19.34.240 — hygiene classification + excursion floor (audit-preserved)
        "genuine": _genuine,
        "hygiene_tag": _hyg_tag,
        "effective_close_reason": _effective_reason,
        "reclass_method": _reclass_method,
        "mfe_r_floor": round(_mfe_r_floor, 3),
        "mae_r_floor": round(_mae_r_floor, 3),
    }
    try:
        # Upsert keyed on trade_id so retry-on-failure paths don't
        # create duplicate outcome rows.
        coll.update_one(
            {"trade_id": doc["trade_id"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception as e:
        # v19.34.396 — a write failure here previously logged at DEBUG and
        # left the cached _AO_DB in place, so a single stale/dead handle
        # silently dropped EVERY subsequent outcome (18-day outage). Warn +
        # drop the cached handle so the next close re-resolves a fresh one.
        logger.warning(
            "[pnl_compute] alert_outcomes upsert FAILED (self-healing handle): %s", e,
        )
        _AO_DB = None
        _AO_CLIENT = None

    # ── v19.34.216 — LIVE EV HOOK ─────────────────────────────────────────
    # Keep `strategy_stats` (the TQS Setup-pillar EV / real-win-rate feed)
    # fresh on EVERY close. Pre-v216 only `enhanced_scanner.record_alert_outcome`
    # updated strategy_stats, and it required alert_id ∈ scanner._live_alerts —
    # which the modern reconciler/operator/manage-loop close paths bypass. So
    # strategy_stats was orphaned (EV=0 for ~100% of alerts; see backfill).
    # This upsert mirrors `backfill_strategy_stats.py` math + keying so the
    # one-time backfill and the live feed converge. Best-effort; never blocks.
    # v19.34.240 — but ONLY for GENUINE strategy closes. Artifact closes
    # (phantom sweep / instant external unwind / operator flatten / corrupt pnl)
    # are excluded so they can't pollute the EV scoreboard.
    if _genuine:
        try:
            _upsert_strategy_stats_bestEffort(
                trade, outcome, r_multiple, pnl.get("net_pnl", 0.0),
            )
        except Exception as _ss_err:
            logger.debug("[v19.34.216 strategy_stats] live hook skipped: %s", _ss_err)
    else:
        logger.debug(
            "[v19.34.240 hygiene] strategy_stats SKIPPED for %s close (%s)",
            getattr(trade, "symbol", "?"), _hyg_tag,
        )

    # v19.34.240 (Part B) — finalize MFE/MAE on bot_trades from the realized
    # entry->exit excursion when the manage loop never populated it.
    try:
        _backfill_excursion_floor(trade, _mfe_r_floor, _mae_r_floor)
    except Exception as _ex_err:
        logger.debug("[v19.34.240 excursion] floor backfill skipped: %s", _ex_err)

    # v19.34.88 — Post-stop cooldown stamp. On any close whose reason
    # starts with "stop" (stop_loss, stop_loss_phantom_recovery,
    # stop_loss_trailing, etc.), record the (symbol, setup_base) pair
    # into the in-memory cooldown registry so opportunity_evaluator
    # can refuse same-symbol+setup re-entries for the next
    # POST_STOP_COOLDOWN_MINUTES window. This is the v19.34.87
    # setup_retro finding fix: prevents ETHU-style 5x-stops-in-22min
    # bleed cascades.
    try:
        if str(reason or "").lower().startswith("stop"):
            from services.post_stop_cooldown import get_registry
            get_registry().record_stop(
                symbol=getattr(trade, "symbol", None),
                setup_type=getattr(trade, "setup_type", None),
            )
    except Exception as _cd_err:
        logger.debug(
            "[v19.34.88 post-stop-cooldown] stamp failed (non-fatal): %s",
            _cd_err,
        )


def _base_setup(setup_type: Any) -> str:
    """Normalize a setup_type to the family key the TQS Setup pillar queries
    (`enhanced_scanner` consumer at L3201): strip the _long/_short suffix.
    MUST match `backfill_strategy_stats.base_setup` exactly."""
    return str(setup_type or "").split("_long")[0].split("_short")[0]


# ── v19.34.284 — legacy-row artifact guard ──────────────────────────────────
# `recompute_strategy_stats_for_setup` filters on the `genuine` flag, but
# alert_outcomes rows written BEFORE the v240 hygiene tagging predate that field
# entirely. `d.get("genuine", True)` therefore defaults legacy artifact rows
# (reconciled_orphan / reconciled_excess_slice / phantom sweeps) to genuine=True,
# so they leaked back into the EV/win-rate feed and dragged the Smart Filter into
# over-gating. This re-derives genuineness from setup_type/close_reason using the
# SAME substrings as trade_outcome_hygiene.classify_close, regardless of whether
# the row carries a `genuine` flag.
_ARTIFACT_SETUP_SUBSTR_FALLBACK = ("reconciled", "imported", "phantom")
_ARTIFACT_REASON_SUBSTR_FALLBACK = (
    "phantom", "sweep", "purge", "reconcile", "external_flatten", "operator_external",
)


def _is_reconciliation_artifact(setup_type: Any, close_reason: Any) -> bool:
    """True when a row is an execution/reconciliation artifact (NOT a genuine
    strategy close) judged purely from its setup_type / close_reason — used to
    exclude legacy rows that have no `genuine` field. Mirrors the hygiene
    module's substrings; imports them when available, else uses the fallback."""
    try:
        from services.trade_outcome_hygiene import (
            _ARTIFACT_SETUP_SUBSTRINGS as _ss,
            _ARTIFACT_REASON_SUBSTRINGS as _rs,
        )
    except Exception:
        _ss, _rs = _ARTIFACT_SETUP_SUBSTR_FALLBACK, _ARTIFACT_REASON_SUBSTR_FALLBACK
    st = str(setup_type or "").lower()
    rr = str(close_reason or "").lower()
    if any(sub in st for sub in _ss):
        return True
    if any(sub in rr for sub in _rs):
        return True
    return False


_WIN_TOK = {"won", "win", "winner", "target", "target_hit", "profit", "tp",
            "take_profit", "profit_target"}
_LOSS_TOK = {"lost", "loss", "loser", "stopped", "stop", "stop_hit",
             "stopped_out", "sl", "stop_loss"}


def _classify_outcome(outcome, r, pnl):
    """win/loss/None — outcome string first, then R, then pnl (matches
    backfill_strategy_stats._classify)."""
    o = str(outcome or "").lower().strip()
    if o in _WIN_TOK:
        return "win"
    if o in _LOSS_TOK:
        return "loss"
    if r is not None and r != 0:
        return "win" if r > 0 else "loss"
    if pnl:
        return "win" if pnl > 0 else "loss"
    return None


_WIN_TOK = {"won", "win", "winner", "target", "target_hit", "profit", "tp",
            "take_profit", "profit_target"}
_LOSS_TOK = {"lost", "loss", "loser", "stopped", "stop", "stop_hit",
             "stopped_out", "sl", "stop_loss"}


def _classify_outcome(outcome, r, pnl):
    """win/loss/None — outcome string first, then R, then pnl (matches
    backfill_strategy_stats._classify)."""
    o = str(outcome or "").lower().strip()
    if o in _WIN_TOK:
        return "win"
    if o in _LOSS_TOK:
        return "loss"
    if r is not None and r != 0:
        return "win" if r > 0 else "loss"
    if pnl:
        return "win" if pnl > 0 else "loss"
    return None


def recompute_strategy_stats_for_setup(base: str, genuine_only: bool = True) -> Optional[dict]:
    """v19.34.249 (F3) — CANONICAL strategy_stats recompute for ONE setup family
    from `alert_outcomes` (which is upserted 1-row-per-trade, keyed on trade_id).

    Replaces the v216 per-close-EVENT incremental counter, which double-counted
    scale-out partials — every `apply_close_pnl` call bumped alerts_triggered/won
    and appended to r_outcomes — inflating win_rate + EV away from the realized
    whole-trade truth (accumulation_entry read 52%/+0.62R when the realized rate
    was 11%/-0.43R). Recomputing from alert_outcomes makes win_rate AND EV share
    the SAME whole-trade sample and makes the live feed converge with the nightly
    backfill_strategy_stats.py. Math/keying mirror that script exactly.
    `genuine_only` excludes hygiene-tagged artifacts."""
    if _get_outcomes_collection() is None or _AO_DB is None or not base:
        return None
    try:
        ao = _AO_DB["alert_outcomes"]
        rows = [
            d for d in ao.find(
                {}, {"_id": 1, "setup_type": 1, "outcome": 1, "r_multiple": 1,
                     "net_pnl": 1, "pnl": 1, "closed_at": 1, "genuine": 1,
                     "close_reason": 1, "r_risk_unreliable": 1})
            if _base_setup(d.get("setup_type")) == base
        ]
        if genuine_only:
            # Exclude both flagged artifacts AND legacy rows (no `genuine` field)
            # that decode to reconciliation/phantom artifacts by setup/reason.
            # v19.34.307 — also drop rows with a corrupt risk basis (stop ≈ entry
            # → absurd R), which would otherwise skew avg_r / EV.
            rows = [
                d for d in rows
                if d.get("genuine", True) is not False
                and d.get("r_risk_unreliable") is not True
                and not _is_reconciliation_artifact(
                    d.get("setup_type"), d.get("close_reason"))
            ]
        rows.sort(key=lambda d: (str(d.get("closed_at", "")), str(d.get("_id", ""))))

        trig = won = lost = 0
        r_all = []
        total_pnl = 0.0
        for d in rows:
            r = d.get("r_multiple")
            r = float(r) if isinstance(r, (int, float)) else None
            pnl_v = d.get("net_pnl")
            if pnl_v is None:
                pnl_v = d.get("pnl")
            pnl_v = float(pnl_v) if isinstance(pnl_v, (int, float)) else 0.0
            cls = _classify_outcome(d.get("outcome"), r, pnl_v)
            if cls is None:
                continue
            trig += 1
            won += 1 if cls == "win" else 0
            lost += 1 if cls == "loss" else 0
            total_pnl += pnl_v
            if r is not None:
                r_all.append(r)

        r_out = r_all[-100:]  # last-100 retained for storage only
        win_rate = (won / trig) if trig else 0.0
        # v19.34.305 — EV must be the realized expectancy of the SAME sample the
        # win_rate is measured over. The legacy code mixed full-sample win_rate
        # with last-100 avg_win/avg_loss, so EV diverged from the realized mean
        # (e.g. -0.13R "Expected Value" vs +0.01R "avg_r" on the same card). Use
        # the FULL window sample (r_all) for both, which makes EV == mean(R) and
        # eliminates the contradiction. avg_win_r/avg_loss_r are also computed on
        # the full sample for display consistency.
        n_all = len(r_all)
        wins_r = [x for x in r_all if x > 0]
        losses_r = [x for x in r_all if x <= 0]
        avg_win_r = (sum(wins_r) / len(wins_r)) if wins_r else 0.0
        avg_loss_r = abs(sum(losses_r) / len(losses_r)) if losses_r else 1.0
        avg_rr = (sum(r_all) / n_all) if n_all else 0.0
        ev = avg_rr if n_all >= 5 else 0.0  # realized expectancy == mean(R)
        profit_factor = (
            (sum(wins_r) / abs(sum(losses_r)))
            if losses_r and sum(losses_r) != 0 else 0.0
        )
        doc = {
            "setup_type": base,
            "total_alerts": trig,
            "alerts_triggered": trig,
            "alerts_won": won,
            "alerts_lost": lost,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "avg_rr_achieved": round(avg_rr, 3),
            # v19.34.305 — expose the realized mean + sample size under the field
            # names the TQS card-detail / drill-down read, so the displayed EV,
            # avg_r and n all come from this one artifact-free recompute.
            "avg_r": round(avg_rr, 4),
            "sample_size": trig,
            "total_trades": trig,
            "r_outcomes": [round(x, 4) for x in r_out],
            "avg_win_r": round(avg_win_r, 4),
            "avg_loss_r": round(avg_loss_r, 4),
            "expected_value_r": round(ev, 4),
            "genuine_only": genuine_only,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "recomputed_by": "pnl_compute_v19_34_249",
        }
        _AO_DB["strategy_stats"].update_one(
            {"setup_type": base}, {"$set": doc}, upsert=True,
        )
        return doc
    except Exception as e:
        logger.debug("[v19.34.249 strategy_stats] recompute failed for %s: %s", base, e)
        return None


def _upsert_strategy_stats_bestEffort(
    trade: Any, outcome: str, r_multiple: Optional[float], net_pnl: float,
) -> None:
    """v19.34.249 (F3) — now a thin wrapper. Stats are RECOMPUTED whole-trade from
    `alert_outcomes` for the trade's setup family (the alert_outcomes row for THIS
    trade is already upserted by the caller before this runs), so scale-out
    partials can no longer inflate the counters. The `outcome`/`r_multiple`/
    `net_pnl` args are retained for signature compatibility with the v216 caller."""
    bs = _base_setup(getattr(trade, "setup_type", None))
    if not bs:
        return
    doc = recompute_strategy_stats_for_setup(bs, genuine_only=True)
    if doc is not None:
        logger.info(
            "[v19.34.249 strategy_stats] %s recomputed → EV=%.3fR win=%.0f%% (#trades=%d)",
            bs, doc["expected_value_r"], doc["win_rate"] * 100, doc["alerts_triggered"],
        )


def compute_close_pnl(
    *,
    direction: str,
    fill_price: float,
    exit_price: float,
    shares: int,
    commission: float = 0.0,
) -> Dict[str, float]:
    """Pure-math PnL computation. Direction: 'long' or 'short'.
    Long PnL  = (exit - fill) × shares − commission
    Short PnL = (fill - exit) × shares − commission
    """
    d = (direction or "long").strip().lower()
    sh = abs(int(shares or 0))
    fp = float(fill_price or 0.0)
    xp = float(exit_price or 0.0)
    if d == "short":
        gross = (fp - xp) * sh
    else:
        gross = (xp - fp) * sh
    net = gross - float(commission or 0.0)
    return {
        "realized_pnl": round(gross, 2),
        "net_pnl":      round(net, 2),
        "commission":   round(float(commission or 0.0), 2),
    }


def _resolve_exit_price(trade: Any, explicit: Optional[float]) -> tuple[float, str]:
    """Best-effort exit price + audit source label.

    Priority:
      1. Explicit (caller passed in a known fill_price from IB execution)
      2. trade.exit_price (already set by an earlier close attempt)
      3. trade.current_price (last quote from pusher)
      4. trade.fill_price (PnL=0 marker — last resort)
    """
    if explicit is not None:
        try:
            v = float(explicit)
            if v > 0:
                return v, "explicit"
        except (TypeError, ValueError):
            pass
    for attr, label in (
        ("exit_price",    "existing_exit_price"),
        ("current_price", "current_price"),
        ("fill_price",    "fill_price_fallback"),
    ):
        try:
            v = float(getattr(trade, attr, 0) or 0)
            if v > 0:
                return v, label
        except (TypeError, ValueError):
            continue
    return 0.0, "no_price_available"


def apply_close_pnl(
    trade: Any,
    *,
    reason: str,
    exit_price: Optional[float] = None,
    commission: Optional[float] = None,
    now_iso: Optional[str] = None,
    record_outcome: bool = True,
) -> Dict[str, Any]:
    """Compute and write realized_pnl + net_pnl onto `trade` in-place.
    ALSO writes: exit_price, close_reason, closed_at, unrealized_pnl=0,
    remaining_shares=0, exit_price_source (audit breadcrumb).

    v19.34.124: When `record_outcome=True` (default), ALSO writes an
    `alert_outcomes` row to MongoDB so the setup-grading + learning
    loop have data. Best-effort fire-and-forget — failures here never
    block the close.

    Returns the computed dict for logging / tests. NEVER raises — silent
    failures are logged and the function returns a best-effort dict.
    """
    out: Dict[str, Any] = {"reason": reason}
    try:
        # Shares at close = original shares filled (NOT remaining, which
        # may already be 0 from a peel). For partial-peel close paths,
        # the caller adjusts via the explicit `shares_override` semantics
        # below (passed via attribute) if needed.
        shares = int(abs(getattr(trade, "shares", 0) or 0))
        if hasattr(trade, "_close_shares_override"):
            try:
                shares = int(abs(getattr(trade, "_close_shares_override", 0) or 0))
            except Exception:
                pass

        direction = str(getattr(trade, "direction", "long"))
        # Handle TradeDirection enum
        if hasattr(getattr(trade, "direction", None), "value"):
            direction = str(trade.direction.value)
        direction = direction.strip().lower()

        fill_price = float(getattr(trade, "fill_price", 0) or 0)
        resolved_exit, source = _resolve_exit_price(trade, exit_price)

        # Commission: caller-supplied OR existing total_commissions OR 0
        if commission is None:
            commission = float(getattr(trade, "total_commissions", 0) or 0)

        pnl = compute_close_pnl(
            direction=direction,
            fill_price=fill_price,
            exit_price=resolved_exit,
            shares=shares,
            commission=commission,
        )

        # Write back onto trade
        trade.exit_price = resolved_exit
        trade.realized_pnl = pnl["realized_pnl"]
        trade.net_pnl = pnl["net_pnl"]
        trade.unrealized_pnl = 0.0
        trade.remaining_shares = 0
        trade.close_reason = reason
        trade.closed_at = now_iso or datetime.now(timezone.utc).isoformat()
        # Audit breadcrumb so downstream readers know how exit_price was
        # resolved — operators reviewing tape see "approximated from
        # current_price" vs an authoritative IB fill.
        try:
            trade._exit_price_source = source
        except Exception:
            pass

        out.update(pnl)
        out["exit_price"] = resolved_exit
        out["exit_price_source"] = source
        out["shares"] = shares
        out["direction"] = direction

        # v19.34.124 — Feed alert_outcomes for grading + learning loop.
        # Pre-v124 only `enhanced_scanner.record_alert_outcome` wrote to
        # this collection AND it required alert_id ∈ scanner._live_alerts
        # (which excluded reconciler/operator close paths). Result:
        # `alert_outcomes` collection was empty / stale, EOD grading and
        # learning loop had no signal. Direct write here covers EVERY
        # close path that uses apply_close_pnl.
        if record_outcome:
            try:
                _record_alert_outcome_bestEffort(trade, reason, pnl, resolved_exit, source)
            except Exception as _ao_err:
                logger.debug(
                    "[pnl_compute] alert_outcomes write skipped: %s", _ao_err,
                )

        return out
    except Exception as exc:
        logger.error(
            "[pnl_compute] apply_close_pnl FAILED for %s (reason=%s): %s",
            getattr(trade, "id", "?"), reason, exc, exc_info=True,
        )
        # Last-resort: at minimum stamp the close metadata so subsequent
        # readers still see status/closed_at correctly.
        try:
            trade.closed_at = now_iso or datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0.0
            trade.remaining_shares = 0
        except Exception:
            pass
        out["error"] = str(exc)[:200]
        return out
