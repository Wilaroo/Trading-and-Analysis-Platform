"""Unit tests for the 3 data-pipeline cleanup scripts (2026-04-21).

Covers pure-logic helpers only — DB interaction is tested manually on Spark.
"""
import importlib.util
from pathlib import Path

import pytest


def _load(script_name: str):
    spec = importlib.util.spec_from_file_location(
        script_name,
        Path(__file__).resolve().parent.parent / "scripts" / f"{script_name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── backfill_r_multiples.compute_r_multiple ───────────────────────────────

backfill = _load("backfill_r_multiples")


def test_r_multiple_long_profitable_2R():
    # Entry 100, stop 95 (risk 5), exit 110 → (110-100)/5 = +2R
    assert backfill.compute_r_multiple(100, 95, 110, "long") == pytest.approx(2.0)


def test_r_multiple_long_stopped_minus_1R():
    assert backfill.compute_r_multiple(100, 95, 95, "long") == pytest.approx(-1.0)


def test_r_multiple_long_break_even():
    assert backfill.compute_r_multiple(100, 95, 100, "long") == 0.0


def test_r_multiple_short_profitable():
    # Entry 100, stop 105 (risk 5), exit 90 → (100-90)/5 = +2R
    assert backfill.compute_r_multiple(100, 105, 90, "short") == pytest.approx(2.0)


def test_r_multiple_short_stopped_minus_1R():
    assert backfill.compute_r_multiple(100, 105, 105, "short") == pytest.approx(-1.0)


def test_r_multiple_direction_aliases():
    # Same trade, different direction labels
    for alias in ("long", "LONG", "buy", "BUY", "up", "UP"):
        assert backfill.compute_r_multiple(100, 95, 110, alias) == pytest.approx(2.0)
    for alias in ("short", "SHORT", "sell", "down"):
        assert backfill.compute_r_multiple(100, 105, 90, alias) == pytest.approx(2.0)


def test_r_multiple_returns_none_on_bad_inputs():
    assert backfill.compute_r_multiple(None, 95, 110, "long") is None
    assert backfill.compute_r_multiple(100, None, 110, "long") is None
    assert backfill.compute_r_multiple(100, 95, None, "long") is None
    assert backfill.compute_r_multiple("oops", 95, 110, "long") is None
    assert backfill.compute_r_multiple(-1, 95, 110, "long") is None  # bad price
    assert backfill.compute_r_multiple(100, 100, 110, "long") is None  # zero risk
    assert backfill.compute_r_multiple(100, 95, 110, "") is None  # unknown dir
    assert backfill.compute_r_multiple(100, 95, 110, "sideways") is None


# ── diagnose_alert_outcome_gap.classify_leak ──────────────────────────────

gap = _load("diagnose_alert_outcome_gap")


def _stg(alerts=0, orders=None, cancelled=0, executed=0, closed=0, with_r=0):
    if orders is None:
        orders = executed + cancelled
    return {"alerts": alerts, "orders": orders, "cancelled": cancelled,
            "executed": executed, "closed": closed, "with_r": with_r}


def test_classify_leak_healthy_full_funnel():
    assert gap.classify_leak(_stg(alerts=100, executed=50, closed=48, with_r=48)) == "healthy"


def test_classify_leak_closure_gap_low_ratio():
    """Low closure ratio (e.g. 4/1220 = 0.3%) must flag as closure_gap,
    not mask it as r_gap just because a handful got closed."""
    assert gap.classify_leak(_stg(alerts=15000, executed=1220, closed=4, with_r=0)) == "closure_gap"
    assert gap.classify_leak(_stg(alerts=14000, executed=2051, closed=57, with_r=0)) == "closure_gap"


def test_classify_leak_r_gap_when_closure_healthy():
    """≥30% closure rate → if r_multiple missing, it's a backfill gap."""
    assert gap.classify_leak(_stg(alerts=100, executed=50, closed=40, with_r=0)) == "r_gap"
    assert gap.classify_leak(_stg(alerts=20, executed=10, closed=3, with_r=0)) == "r_gap"


def test_classify_leak_execution_gap():
    # Alerts fire but nothing gets executed (fills)
    assert gap.classify_leak(_stg(alerts=500, executed=0, closed=0, with_r=0)) == "execution_gap"


def test_classify_leak_closure_gap():
    # Trades filled but never marked closed
    assert gap.classify_leak(_stg(alerts=100, executed=50, closed=0, with_r=0)) == "closure_gap"


def test_classify_leak_r_gap():
    # Trades closed with healthy ratio but r_multiple missing
    assert gap.classify_leak(_stg(alerts=100, executed=50, closed=48, with_r=0)) == "r_gap"


def test_classify_leak_no_alerts():
    assert gap.classify_leak(_stg()) == "no_alerts"


def test_classify_leak_priority_execution_before_closure():
    """If nothing is executed, execution_gap wins even with 0 closed."""
    assert gap.classify_leak(_stg(alerts=100, executed=0, closed=0, with_r=0)) == "execution_gap"


# ── diagnose_alert_outcome_gap._norm (matches audit normalization) ────────

def test_norm_strips_suffixes_and_prefixes():
    assert gap._norm("rubber_band_long") == "rubber_band"
    assert gap._norm("RUBBER_BAND_SHORT") == "rubber_band"
    assert gap._norm("approaching_breakout") == "breakout"
    assert gap._norm("breakout_confirmed") == "breakout"
    assert gap._norm(None) is None
    assert gap._norm("") is None


# ── collapse_relative_strength.RENAME_MAP ─────────────────────────────────

collapse = _load("collapse_relative_strength")


def test_rename_map_covers_both_leader_and_laggard():
    assert collapse.RENAME_MAP["relative_strength_leader"] == "relative_strength_long"
    assert collapse.RENAME_MAP["relative_strength_laggard"] == "relative_strength_short"


def test_rename_targets_normalize_to_taxonomy_root():
    # After rename, audit script's _norm should collapse them to 'relative_strength'
    for old, new in collapse.RENAME_MAP.items():
        assert gap._norm(new) == "relative_strength", (
            f"{new} must normalize to taxonomy root 'relative_strength'"
        )


def test_collections_list_matches_audit_scope():
    # Must rename in the same 4 collections the audit script scans
    assert set(collapse.COLLECTIONS) == {
        "trades", "bot_trades", "trade_snapshots", "live_alerts"
    }


# ── backfill_closed_no_exit.infer_exit_from_pnl ───────────────────────────

fix_closed = _load("backfill_closed_no_exit")


def test_infer_exit_long_profitable():
    # Long 100 shares, fill=50, pnl=+500 → exit = 50 + 500/100 = 55
    assert fix_closed.infer_exit_from_pnl(50, 500, 100, "long") == pytest.approx(55.0)


def test_infer_exit_long_loss():
    # Long 100 shares, fill=50, pnl=-200 → exit = 50 - 2 = 48
    assert fix_closed.infer_exit_from_pnl(50, -200, 100, "long") == pytest.approx(48.0)


def test_infer_exit_short_profitable():
    # Short 100 shares, fill=50, pnl=+300 → exit = 50 - 3 = 47 (price dropped)
    assert fix_closed.infer_exit_from_pnl(50, 300, 100, "short") == pytest.approx(47.0)


def test_infer_exit_returns_none_on_missing_inputs():
    assert fix_closed.infer_exit_from_pnl(None, 100, 100, "long") is None
    assert fix_closed.infer_exit_from_pnl(50, None, 100, "long") is None
    assert fix_closed.infer_exit_from_pnl(50, 100, None, "long") is None
    assert fix_closed.infer_exit_from_pnl(50, 100, 0, "long") is None
    assert fix_closed.infer_exit_from_pnl(-1, 100, 100, "long") is None
    assert fix_closed.infer_exit_from_pnl(50, 100, 100, "sideways") is None


def test_infer_exit_direction_aliases():
    for alias in ("long", "LONG", "buy", "up"):
        assert fix_closed.infer_exit_from_pnl(50, 500, 100, alias) == pytest.approx(55.0)
    for alias in ("short", "sell", "down"):
        assert fix_closed.infer_exit_from_pnl(50, 300, 100, alias) == pytest.approx(47.0)


def test_infer_exit_roundtrip_with_r_multiple():
    """Derived exit must produce a sensible r_multiple when fed back."""
    # Long 100 sh, entry=50, stop=48 (risk $2), exit=55 → pnl=500, r=+2.5R
    derived_exit = fix_closed.infer_exit_from_pnl(50, 500, 100, "long")
    r = backfill.compute_r_multiple(50, 48, derived_exit, "long")
    assert r == pytest.approx(2.5)


# ── fix_inverted_short_stops.diagnose_inverted_stop ───────────────────────

fix_inverted = _load("fix_inverted_short_stops")


def test_diagnose_correct_short_stop_is_ok():
    # Short: stop ABOVE entry → fine
    assert fix_inverted.diagnose_inverted_stop("short", 100, 105, 103) == "ok"


def test_diagnose_long_direction_is_ok():
    """Non-shorts shouldn't be flagged even if stop < entry (that's correct for long)."""
    assert fix_inverted.diagnose_inverted_stop("long", 100, 95, 110) == "ok"


def test_diagnose_inverted_short_flagged_as_direction_flip():
    # Short with stop BELOW entry = corruption. Classify as direction_flip.
    assert fix_inverted.diagnose_inverted_stop("short", 100, 95, 110) == "direction_flip"
    assert fix_inverted.diagnose_inverted_stop("short", 100, 95, 92) == "direction_flip"


def test_diagnose_ambiguous_on_missing_inputs():
    assert fix_inverted.diagnose_inverted_stop(None, 100, 95, 110) == "ambiguous"
    assert fix_inverted.diagnose_inverted_stop("short", None, 95, 110) == "ambiguous"
    assert fix_inverted.diagnose_inverted_stop("short", 100, None, 110) == "ambiguous"
    assert fix_inverted.diagnose_inverted_stop("short", 100, 95, None) == "ambiguous"
