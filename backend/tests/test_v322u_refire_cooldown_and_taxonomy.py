"""
v322u — Broker-rejection re-fire churn killer + style/timeframe coherence
=========================================================================

Two mission-critical fixes for the find→take→manage→close loop:

1. RE-FIRE CHURN (TAKE phase). The v19.34.8 rejection cooldown only
   fired when the broker's error text matched an ~18-token structural
   allow-list. Any IB wording outside it (tick-size Error 110, margin
   variants, pacing violations, "reason not given") got NO cooldown and
   the scan loop re-fired the identical signal every tick — probe
   2026-06-11 caught the same signal fired 11× in a row. v322u flips the
   broker-rejection boundary to DEFAULT-DENY via
   `mark_rejection(..., assume_structural=True)`: only an EXPLICIT
   transient match bypasses the cooldown. Guardrail-veto / evaluator
   call sites keep legacy allow-list behavior.

2. TAXONOMY COHERENCE (MANAGE/CLOSE phase). `timeframe` came from
   STRATEGY_CONFIG[setup_type] while `trade_style` came from the
   scanner's SETUP_TO_STYLE — two parallel per-setup tables that drift
   (probe found style=swing + tf=intraday rows). Consequences:
     a. scalp-style trades stamped tf="intraday" escaped the
        v19.34.171 scalp-decay sweep forever;
     b. a swing-style trade stamped tf="scalp" would be wrongly
        flattened at 60 min.
   Fixes: write-side `reconcile_timeframe_with_style` (style wins at
   trade creation) + read-side style-aware selection in
   `check_scalp_decay` (covers legacy rows already in Mongo).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "backend")

_BACKEND_DIR = Path(__file__).resolve().parents[1]


# ──────────────────────────────────────────────────────────────────────
# 1. Re-fire churn: default-deny at the broker boundary
# ──────────────────────────────────────────────────────────────────────
def _fresh_cooldown():
    from services.rejection_cooldown_service import RejectionCooldown
    return RejectionCooldown(default_cooldown_seconds=300)


def test_unknown_broker_reason_cools_down_with_assume_structural():
    """The 11×-re-fire fingerprint: an IB wording absent from the
    structural allow-list MUST now cool down at the broker boundary."""
    cd = _fresh_cooldown()
    entry = cd.mark_rejection(
        symbol="NBIS", setup_type="orb_breakout",
        reason="Error 110: The price does not conform to the minimum "
               "price variation for this contract.",
        assume_structural=True,
    )
    assert entry is not None, (
        "v322u regression: unlisted broker rejection got NO cooldown — "
        "the scan loop will re-fire the same signal every tick again."
    )
    active = cd.is_in_cooldown("NBIS", "orb_breakout")
    assert active is not None and active.rejection_count == 1


def test_empty_broker_reason_cools_down_with_assume_structural():
    """IB sometimes rejects with no usable text — default-deny must
    still cool down (empty reason ≠ transient)."""
    cd = _fresh_cooldown()
    entry = cd.mark_rejection(
        symbol="MU", setup_type="gap_and_go", reason="",
        assume_structural=True,
    )
    assert entry is not None
    assert cd.is_in_cooldown("MU", "gap_and_go") is not None


def test_transient_reason_bypasses_even_with_assume_structural():
    """Explicit transient wording stays retry-able."""
    cd = _fresh_cooldown()
    entry = cd.mark_rejection(
        symbol="COIN", setup_type="vwap_fade", reason="stale_quote",
        assume_structural=True,
    )
    assert entry is None
    assert cd.is_in_cooldown("COIN", "vwap_fade") is None


def test_legacy_allowlist_behavior_unchanged_without_flag():
    """Guardrail-veto / evaluator call sites (no flag) keep the v19.34.8
    allow-list semantics: unlisted reasons do NOT cool down."""
    cd = _fresh_cooldown()
    assert cd.mark_rejection(
        symbol="XLU", setup_type="range_break",
        reason="stop distance too tight vs ATR",
    ) is None
    # …and structural reasons still do.
    assert cd.mark_rejection(
        symbol="XLU", setup_type="range_break",
        reason="insufficient buying_power",
    ) is not None


def test_repeat_unknown_rejection_extends_cooldown():
    """Spiral rate-limiting must work for default-deny entries too."""
    cd = _fresh_cooldown()
    cd.mark_rejection(symbol="LRCX", setup_type="breakout",
                      reason="Order rejected - reason not given",
                      assume_structural=True)
    entry = cd.mark_rejection(symbol="LRCX", setup_type="breakout",
                              reason="Order rejected - reason not given",
                              assume_structural=True)
    assert entry is not None and entry.rejection_count == 2


def test_is_transient_rejection_helper():
    from services.rejection_cooldown_service import is_transient_rejection
    assert is_transient_rejection("stale_quote during eval") is True
    assert is_transient_rejection("Error 201: margin requirement") is False
    assert is_transient_rejection("") is False
    assert is_transient_rejection(None) is False


def test_broker_branch_passes_assume_structural_static():
    """Static guard: the broker-rejection branch in trade_execution.py
    must call mark_rejection with assume_structural=True."""
    src = (_BACKEND_DIR / "services" / "trade_execution.py").read_text("utf-8")
    assert "assume_structural=True" in src, (
        "v322u regression: broker-rejection branch lost default-deny — "
        "unlisted IB rejections will re-fire every tick again."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Taxonomy coherence: write-side reconciler
# ──────────────────────────────────────────────────────────────────────
def test_reconcile_timeframe_with_style_mappings():
    from services.opportunity_evaluator import reconcile_timeframe_with_style
    # Conflict → style wins
    assert reconcile_timeframe_with_style("intraday", "scalp") == ("scalp", True)
    assert reconcile_timeframe_with_style("intraday", "swing") == ("swing", True)
    assert reconcile_timeframe_with_style("intraday", "multi_day") == ("swing", True)
    assert reconcile_timeframe_with_style("scalp", "position") == ("position", True)
    assert reconcile_timeframe_with_style("scalp", "investment") == ("position", True)
    # Agreement → untouched
    assert reconcile_timeframe_with_style("scalp", "scalp") == ("scalp", False)
    assert reconcile_timeframe_with_style("intraday", "intraday") == ("intraday", False)
    # Legacy/generic/unknown styles carry no horizon info → untouched
    assert reconcile_timeframe_with_style("intraday", "trade_2_hold") == ("intraday", False)
    assert reconcile_timeframe_with_style("intraday", "move_2_move") == ("intraday", False)
    assert reconcile_timeframe_with_style("intraday", "reconciled") == ("intraday", False)
    assert reconcile_timeframe_with_style("intraday", "") == ("intraday", False)
    assert reconcile_timeframe_with_style("intraday", None) == ("intraday", False)


def test_evaluator_calls_reconciler_static():
    src = (_BACKEND_DIR / "services" / "opportunity_evaluator.py").read_text("utf-8")
    assert "reconcile_timeframe_with_style(" in src.split("def reconcile_timeframe_with_style", 1)[1], (
        "v322u regression: evaluator no longer reconciles timeframe with "
        "trade_style at trade creation."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Taxonomy coherence: read-side style-aware decay sweep
# ──────────────────────────────────────────────────────────────────────
def _decay_trade(trade_id, symbol, tf, style, age_minutes=120):
    return SimpleNamespace(
        id=trade_id, symbol=symbol, timeframe=tf, trade_style=style,
        status="open",
        executed_at=(datetime.now(timezone.utc)
                     - timedelta(minutes=age_minutes)).isoformat(),
    )


def _run_decay_sweep(trades):
    """Drive the REAL check_scalp_decay with a stub bot; return the set
    of trade_ids it flattened."""
    from services.position_manager import PositionManager

    closed = []

    async def close_trade(trade_id, reason=None):
        closed.append(trade_id)
        return True

    bot = SimpleNamespace(
        _open_trades={t.id: t for t in trades},
        close_trade=close_trade,
    )

    old_env = {k: os.environ.get(k) for k in
               ("SCALP_DECAY_ENABLED", "SCALP_DECAY_MINUTES",
                "SCALP_DECAY_MIN_TIME_TO_CLOSE")}
    os.environ["SCALP_DECAY_ENABLED"] = "1"
    os.environ["SCALP_DECAY_MINUTES"] = "60"
    # Defeat the wall-clock proximity-to-close gate so the test is
    # deterministic at any time of day.
    os.environ["SCALP_DECAY_MIN_TIME_TO_CLOSE"] = "-100000"
    try:
        asyncio.run(PositionManager.check_scalp_decay(None, bot))
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return set(closed)


def test_decay_catches_scalp_style_with_intraday_tf():
    """Failure mode 1: scalp-STYLE trade mislabeled tf=intraday escaped
    decay forever. Style-aware selection must catch it."""
    closed = _run_decay_sweep([
        _decay_trade("t-scalp-drift", "NBIS", tf="intraday", style="scalp"),
    ])
    assert "t-scalp-drift" in closed, (
        "v322u regression: scalp-style trade with drifted tf=intraday "
        "escaped the decay sweep."
    )


def test_decay_protects_swing_style_with_scalp_tf():
    """Failure mode 2 (defensive): swing-style trade mislabeled tf=scalp
    must NEVER be decay-flattened."""
    closed = _run_decay_sweep([
        _decay_trade("t-swing-drift", "CASY", tf="scalp", style="swing"),
        _decay_trade("t-multiday-drift", "ALAB", tf="scalp", style="multi_day"),
    ])
    assert closed == set(), (
        "v322u regression: swing/multi_day-style trades with drifted "
        "tf=scalp were wrongly decay-flattened."
    )


def test_decay_still_processes_plain_scalps_and_skips_young_ones():
    """Regression guard for the original v19.34.171 behavior."""
    closed = _run_decay_sweep([
        _decay_trade("t-old-scalp", "GLD", tf="scalp", style="scalp",
                     age_minutes=120),
        _decay_trade("t-young-scalp", "SLV", tf="scalp", style="scalp",
                     age_minutes=10),
        _decay_trade("t-intraday", "IWM", tf="intraday",
                     style="intraday", age_minutes=300),
    ])
    assert closed == {"t-old-scalp"}, (
        f"expected only the 2h-old scalp to flatten, got {closed}"
    )
