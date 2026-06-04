"""
v19.34.263 — external/OCA scalp-exit reclassification.

The 30d audit proved ~56% of scalp closes were lumped under
`oca_closed_externally`, and the hygiene layer discarded the <120s ones as
`instant_external_unwind` — so genuine scalp bracket fills (target/stop/
partial) never reached the EV scoreboard. These tests cover:

  1. The pure `reclassify_external_exit` decoder (price + pnl-reconstructed,
     long + short, target / stop / partial / corrupt-R / unresolved).
  2. `classify_close` now marks a price-confirmed external bracket fill GENUINE
     (overriding instant-unwind) WITHOUT regressing the legacy no-context paths.
  3. The `learning_reconciler.reprocess_external_closes` migration flips a stale
     non-genuine external scalp close back to genuine and refreshes strategy_stats.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mongomock  # noqa: E402
import pytest  # noqa: E402

from services.trade_outcome_hygiene import (  # noqa: E402
    classify_close, reclassify_external_exit, _is_external_bracket_reason,
)


# ── 1. pure decoder ─────────────────────────────────────────────────────────
def test_external_reason_detection():
    assert _is_external_bracket_reason("oca_closed_externally_v19_31") is True
    assert _is_external_bracket_reason("external_close_v19_34_15b") is True
    # operator / manual / reconcile flattens are NOT bracket fills
    assert _is_external_bracket_reason("operator_external_flatten") is False
    assert _is_external_bracket_reason("reconciled_external") is False
    assert _is_external_bracket_reason("stop_loss") is False


def test_reclass_long_target_via_price():
    eff, method, xp, rr = reclassify_external_exit(
        "oca_closed_externally_v19_31", direction="long",
        entry_price=100, exit_price=101.5, stop_price=99, target_prices=[101.5],
    )
    assert eff == "target" and method == "price" and rr == pytest.approx(1.5)


def test_reclass_long_stop_via_pnl_reconstructed():
    # exit_price absent → reconstruct from realized_pnl/shares.
    # entry 50, stop 49, 100 sh, realized -100 => exit 49 (== stop) => stop_loss.
    eff, method, xp, rr = reclassify_external_exit(
        "oca_closed_externally_v19_31", direction="long",
        entry_price=50, exit_price=None, stop_price=49, target_prices=[52],
        realized_pnl=-100, shares=100,
    )
    assert eff == "stop_loss" and method == "pnl_reconstructed"
    assert xp == pytest.approx(49.0) and rr == pytest.approx(-1.0)


def test_reclass_long_partial_mid_range():
    # entry 100, stop 98, target 104, exit 100.5 -> between levels -> partial.
    eff, method, xp, rr = reclassify_external_exit(
        "oca_closed_externally_v19_31", direction="long",
        entry_price=100, exit_price=100.5, stop_price=98, target_prices=[104],
    )
    assert eff == "external_partial"


def test_reclass_short_target():
    # short: entry 100, stop 102, target 96, exit 96 -> target.
    eff, _, _, rr = reclassify_external_exit(
        "external_close_x", direction="short",
        entry_price=100, exit_price=96, stop_price=102, target_prices=[96],
    )
    assert eff == "target" and rr == pytest.approx(2.0)


def test_reclass_corrupt_r_rejected():
    # entry 100, stop 99 (risk 1), reconstructed exit 200 -> R=100 -> corrupt.
    eff, method, _, rr = reclassify_external_exit(
        "oca_closed_externally_v19_31", direction="long",
        entry_price=100, exit_price=None, stop_price=99, target_prices=[101],
        realized_pnl=10000, shares=100,
    )
    assert eff is None and method == "corrupt_r"


def test_reclass_unresolved_without_levels():
    eff, method, _, _ = reclassify_external_exit(
        "oca_closed_externally_v19_31", direction="long",
        entry_price=100, exit_price=None, stop_price=None, target_prices=[],
        realized_pnl=-50, shares=100,
    )
    assert eff is None and method == "unresolved"


def test_reclass_not_external():
    eff, method, _, _ = reclassify_external_exit(
        "stop_loss", direction="long", entry_price=100, stop_price=99,
        target_prices=[102], realized_pnl=-100, shares=100,
    )
    assert eff is None and method == "not_external"


# ── 2. classify_close genuine-gate behavior ─────────────────────────────────
def test_classify_close_external_stop_now_genuine_with_context():
    # 60s OCA close that the OLD logic discarded as instant_external_unwind is
    # now GENUINE once the bracket context confirms a stop fill.
    g, tag = classify_close(
        "oca_closed_externally_v19_31", entry_price=50, exit_price=None,
        net_pnl=-100, hold_seconds=60, setup_type="scalp",
        direction="long", stop_price=49, target_prices=[52],
        realized_pnl=-100, shares=100,
    )
    assert g is True and tag == "external_stop_loss:pnl_reconstructed"


def test_classify_close_external_target_genuine():
    g, tag = classify_close(
        "oca_closed_externally_v19_31", entry_price=100, exit_price=101.5,
        net_pnl=150, hold_seconds=45, setup_type="scalp",
        direction="long", stop_price=99, target_prices=[101.5],
        realized_pnl=150, shares=100,
    )
    assert g is True and tag.startswith("external_target")


def test_classify_close_legacy_instant_unwind_preserved_without_context():
    # No bracket context supplied -> behaves exactly as pre-v263.
    g, tag = classify_close(
        "oca_closed_externally_v19_31", entry_price=48.95, exit_price=49.0,
        net_pnl=-2, hold_seconds=60,
    )
    assert g is False and tag == "instant_external_unwind"


def test_classify_close_corrupt_external_stays_nongenuine():
    g, tag = classify_close(
        "oca_closed_externally_v19_31", entry_price=100, exit_price=None,
        net_pnl=10000, hold_seconds=60, direction="long",
        stop_price=99, target_prices=[101], realized_pnl=10000, shares=100,
    )
    assert g is False and tag == "external_corrupt_r"


def test_operator_flatten_still_artifact_even_with_context():
    g, tag = classify_close(
        "operator_external_flatten", entry_price=100, exit_price=99,
        net_pnl=-100, hold_seconds=60, direction="long",
        stop_price=98, target_prices=[104], realized_pnl=-100, shares=100,
    )
    assert g is False and tag.startswith("artifact_reason")


# ── 3. migration end-to-end (mongomock) ─────────────────────────────────────
def _seed_db():
    db = mongomock.MongoClient().db
    # A genuine scalp that OCA-closed at its stop in 40s, exit_price absent.
    db.bot_trades.insert_one({
        "id": "scalp1", "symbol": "AAPL", "setup_type": "scalp_long",
        "status": "closed", "direction": "long", "timeframe": "scalp",
        "fill_price": 50.0, "stop_price": 49.0, "target_prices": [52.0],
        "shares": 100, "realized_pnl": -100.0, "net_pnl": -102.0,
        "close_reason": "oca_closed_externally_v19_31",
        "entered_by": "bot", "closed_at": "2026-06-01T14:30:40+00:00",
        "executed_at": "2026-06-01T14:30:00+00:00",
    })
    # Pre-existing STALE alert_outcome marked non-genuine by the old logic.
    db.alert_outcomes.insert_one({
        "trade_id": "scalp1", "setup_type": "scalp_long", "outcome": "lost",
        "pnl": -100.0, "net_pnl": -102.0, "r_multiple": -1.0,
        "close_reason": "oca_closed_externally_v19_31", "genuine": False,
        "hygiene_tag": "instant_external_unwind",
        "closed_at": "2026-06-01T14:30:40+00:00",
    })
    return db


def test_reprocess_flips_stale_external_to_genuine():
    from services import learning_reconciler as LR
    from services import pnl_compute
    db = _seed_db()
    pnl_compute._AO_DB = db  # point canonical writers at the mock

    rep = LR.reprocess_external_closes(db, commit=True, verbose=False)

    assert rep["external_rows"] == 1
    assert rep["by_kind"]["stop_loss"] == 1
    assert rep["flipped_to_genuine"] == 1
    ao = db.alert_outcomes.find_one({"trade_id": "scalp1"})
    assert ao["genuine"] is True
    assert ao["effective_close_reason"] == "stop_loss"
    assert ao["reclass_method"] in ("price", "pnl_reconstructed")
    # strategy_stats for the scalp family now exists + counts the trade.
    ss = db.strategy_stats.find_one({"setup_type": "scalp"})
    assert ss is not None and ss["alerts_triggered"] >= 1


def test_reprocess_dry_run_writes_nothing():
    from services import learning_reconciler as LR
    from services import pnl_compute
    db = _seed_db()
    pnl_compute._AO_DB = db
    rep = LR.reprocess_external_closes(db, commit=False, verbose=False)
    assert rep["reclassified"] == 1
    ao = db.alert_outcomes.find_one({"trade_id": "scalp1"})
    assert ao["genuine"] is False  # untouched in dry-run
