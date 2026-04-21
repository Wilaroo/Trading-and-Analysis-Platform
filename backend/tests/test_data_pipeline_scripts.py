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


def _stg(alerts=0, executed=0, closed=0, with_r=0):
    return {"alerts": alerts, "executed": executed, "closed": closed, "with_r": with_r}


def test_classify_leak_healthy_full_funnel():
    assert gap.classify_leak(_stg(100, 50, 48, 48)) == "healthy"


def test_classify_leak_closure_gap_low_ratio():
    """Low closure ratio (e.g. 4/1220 = 0.3%) must flag as closure_gap,
    not mask it as r_gap just because a handful got closed."""
    assert gap.classify_leak(_stg(15000, 1220, 4, 0)) == "closure_gap"
    assert gap.classify_leak(_stg(14000, 2051, 57, 0)) == "closure_gap"  # 2.8%


def test_classify_leak_r_gap_when_closure_healthy():
    """≥30% closure rate → if r_multiple missing, it's a backfill gap."""
    assert gap.classify_leak(_stg(100, 50, 40, 0)) == "r_gap"   # 80% closed
    assert gap.classify_leak(_stg(20, 10, 3, 0)) == "r_gap"     # 30% closed


def test_classify_leak_execution_gap():
    # Alerts fire but nothing gets executed
    assert gap.classify_leak(_stg(500, 0, 0, 0)) == "execution_gap"


def test_classify_leak_closure_gap():
    # Trades executed but never marked closed
    assert gap.classify_leak(_stg(100, 50, 0, 0)) == "closure_gap"


def test_classify_leak_r_gap():
    # Trades closed with healthy ratio but r_multiple missing
    assert gap.classify_leak(_stg(100, 50, 48, 0)) == "r_gap"


def test_classify_leak_no_alerts():
    assert gap.classify_leak(_stg(0, 0, 0, 0)) == "no_alerts"


def test_classify_leak_priority_execution_before_closure():
    """If nothing is executed, execution_gap wins even with 0 closed."""
    assert gap.classify_leak(_stg(100, 0, 0, 0)) == "execution_gap"


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
