"""
v19.34.249 — tests for the learning-loop coverage reconciler (F1) + the canonical
genuine strategy_stats recompute (F3).

F1: reconciler ingests closed bot_trades missing from the sinks, using stored
    entry-time context, GENUINE-only into trade_outcomes, idempotently.
F3: strategy_stats win_rate AND EV are recomputed whole-trade from alert_outcomes
    (1 row/trade) so scale-out partials can't inflate them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import mongomock  # noqa: E402
import pytest  # noqa: E402

from services import learning_reconciler as LR  # noqa: E402
from services import pnl_compute as PC  # noqa: E402


# ── F3: classification + recompute math ─────────────────────────────
def test_classify_outcome_priority():
    assert PC._classify_outcome("won", None, None) == "win"
    assert PC._classify_outcome("stopped_out", None, None) == "loss"
    assert PC._classify_outcome("", 1.5, None) == "win"
    assert PC._classify_outcome("", -0.5, None) == "loss"
    assert PC._classify_outcome("", None, 100) == "win"
    assert PC._classify_outcome("scratch", 0, 0) is None


def _wire_pc_to(db):
    """Point pnl_compute's lazy _AO_DB handle at a mongomock db."""
    PC._AO_DB = db


def test_recompute_whole_trade_and_genuine_filter():
    db = mongomock.MongoClient().db
    _wire_pc_to(db)
    # 10 genuine accumulation_entry trades: 2 winners (+2R,+1R), 8 losers (-1R)
    rows = []
    for i in range(2):
        rows.append({"setup_type": "accumulation_entry_long", "outcome": "won",
                     "r_multiple": 2.0 if i == 0 else 1.0, "net_pnl": 100,
                     "closed_at": f"2026-06-0{i+1}", "genuine": True})
    for i in range(8):
        rows.append({"setup_type": "accumulation_entry_long", "outcome": "lost",
                     "r_multiple": -1.0, "net_pnl": -50,
                     "closed_at": f"2026-06-1{i}", "genuine": True})
    # 5 NON-genuine phantom winners that must be EXCLUDED
    for i in range(5):
        rows.append({"setup_type": "accumulation_entry_long", "outcome": "won",
                     "r_multiple": 5.0, "net_pnl": 500,
                     "closed_at": f"2026-06-2{i}", "genuine": False})
    db["alert_outcomes"].insert_many(rows)

    doc = PC.recompute_strategy_stats_for_setup("accumulation_entry", genuine_only=True)
    assert doc is not None
    assert doc["alerts_triggered"] == 10          # phantom 5 excluded
    assert doc["alerts_won"] == 2
    assert doc["win_rate"] == pytest.approx(0.20)  # 2/10, NOT inflated by phantom
    # avg_win_r=(2+1)/2=1.5 ; avg_loss_r=1.0 ; EV=0.2*1.5-0.8*1.0 = -0.50
    assert doc["expected_value_r"] == pytest.approx(-0.50, abs=1e-6)
    assert doc["genuine_only"] is True


def test_recompute_excludes_phantom_changes_sign():
    db = mongomock.MongoClient().db
    _wire_pc_to(db)
    db["alert_outcomes"].insert_many([
        {"setup_type": "squeeze", "outcome": "lost", "r_multiple": -1.0,
         "net_pnl": -50, "closed_at": "2026-06-01", "genuine": True} for _ in range(6)
    ] + [
        {"setup_type": "squeeze", "outcome": "won", "r_multiple": 9.0,
         "net_pnl": 900, "closed_at": "2026-06-02", "genuine": False}
    ])
    incl = PC.recompute_strategy_stats_for_setup("squeeze", genuine_only=False)
    excl = PC.recompute_strategy_stats_for_setup("squeeze", genuine_only=True)
    assert excl["alerts_triggered"] == 6 and excl["alerts_won"] == 0
    assert incl["alerts_triggered"] == 7 and incl["alerts_won"] == 1  # phantom leaks in


# ── F1: reconciler doc-build + ingest ───────────────────────────────
def test_build_trade_outcome_doc_uses_entry_context_and_computes_r():
    bt = {
        "id": "T1", "alert_id": "A1", "symbol": "NVDA", "setup_type": "squeeze_long",
        "direction": "long", "fill_price": 100.0, "exit_price": 104.0, "stop_price": 98.0,
        "target_prices": [106.0], "realized_pnl": 400.0, "shares": 100,
        "executed_at": "2026-06-03T14:30:00+00:00", "closed_at": "2026-06-03T18:00:00+00:00",
        "market_regime": "RISK_ON", "entry_context": {"vwap_dist": 0.5},
    }
    doc = LR._build_trade_outcome_doc(bt, genuine=True)
    assert doc["actual_r"] == pytest.approx(2.0)        # (104-100)/(100-98)=2.0
    assert doc["planned_r"] == pytest.approx(3.0)        # (106-100)/2
    assert doc["outcome"] == "won"
    assert doc["context"]["market_regime"] == "RISK_ON"  # stored entry-time, not recapture
    assert doc["context"]["vwap_dist"] == 0.5
    assert doc["bot_trade_id"] == "T1"
    assert doc["backfilled"] is True


def test_build_trade_outcome_doc_short_and_missing_prices():
    short = LR._build_trade_outcome_doc(
        {"id": "S1", "direction": "short", "fill_price": 50, "exit_price": 48,
         "stop_price": 51, "realized_pnl": 200}, genuine=True)
    assert short["actual_r"] == pytest.approx(2.0)       # (50-48)/(51-50)
    assert LR._build_trade_outcome_doc({"id": "X", "fill_price": 10}, genuine=True) is None


def test_exit_price_reconstructed_from_realized_pnl():
    """v249b — OCA-external/EOD sweeps lack exit_price; reconstruct from
    realized_pnl/shares so the bracket target/stop fills aren't lost."""
    # long, entry 100, +600 pnl over 200sh → +3/sh → exit 103 ; risk (100-98)=2 → R=1.5
    bt = {"id": "OCA1", "direction": "long", "fill_price": 100.0, "stop_price": 98.0,
          "realized_pnl": 600.0, "shares": 200}  # NOTE: no exit_price
    assert LR._resolve_exit(bt, 100.0, "long") == pytest.approx(103.0)
    doc = LR._build_trade_outcome_doc(bt, genuine=True)
    assert doc is not None and doc["exit_price"] == pytest.approx(103.0)
    assert doc["actual_r"] == pytest.approx(1.5)
    # short reconstruction
    assert LR._resolve_exit(
        {"direction": "short", "realized_pnl": 200, "shares": 100}, 50.0, "short"
    ) == pytest.approx(48.0)


def test_reconcile_autowires_ao_db_when_none():
    """Standalone-script bug fix: reconcile must point pnl_compute._AO_DB at the
    passed db when it's None, else alert_outcomes/strategy_stats writes no-op."""
    db = mongomock.MongoClient().db
    PC._AO_DB = None  # simulate standalone (no MONGO_URL)
    db["bot_trades"].insert_one(
        {"id": "W1", "status": "closed", "symbol": "AMD", "setup_type": "squeeze_long",
         "direction": "long", "fill_price": 100, "stop_price": 98, "target_prices": [106],
         "realized_pnl": 300, "net_pnl": 295, "shares": 100,  # no exit_price → reconstruct
         "close_reason": "oca_closed_externally_v19_31", "entered_by": "bot",
         "closed_at": "2026-06-03T18:00:00+00:00", "entry_context": {}})
    rep = LR.reconcile(db, commit=True, verbose=False)
    assert PC._AO_DB is db                           # auto-wired
    assert rep["ao_written"] == 1 and rep["to_written"] == 1
    assert db["alert_outcomes"].count_documents({}) == 1   # actually persisted now
    assert db["strategy_stats"].count_documents({"setup_type": "squeeze"}) == 1  # recomputed


def _seed_db():
    db = mongomock.MongoClient().db
    _wire_pc_to(db)
    db["bot_trades"].insert_many([
        # genuine OCA-external close (the leak) — must land in BOTH sinks
        {"id": "G1", "status": "closed", "symbol": "AMD", "setup_type": "squeeze_long",
         "direction": "long", "fill_price": 100, "exit_price": 103, "stop_price": 98,
         "target_prices": [106], "realized_pnl": 300, "net_pnl": 295, "shares": 100,
         "close_reason": "oca_closed_externally_v19_31", "entered_by": "bot",
         "executed_at": "2026-06-03T14:00:00+00:00", "closed_at": "2026-06-03T18:00:00+00:00",
         "market_regime": "RISK_ON", "entry_context": {}},
        # phantom sweep — alert_outcomes only (tagged), NOT trade_outcomes
        {"id": "P1", "status": "closed", "symbol": "XYZ",
         "setup_type": "wrong_direction_phantom_swept_v19_29",
         "direction": "long", "fill_price": 10, "exit_price": 10, "stop_price": 9,
         "realized_pnl": 0, "net_pnl": 0, "shares": 10,
         "close_reason": "wrong_direction_phantom_swept_v19_29", "entered_by": "bot",
         "closed_at": "2026-06-03T18:00:00+00:00", "entry_context": {}},
        # already-recorded trade — must be skipped (idempotency)
        {"id": "DONE", "status": "closed", "symbol": "TSLA", "setup_type": "vwap_fade_long",
         "direction": "long", "fill_price": 200, "exit_price": 198, "stop_price": 202,
         "realized_pnl": -200, "net_pnl": -205, "shares": 100,
         "close_reason": "stop_loss", "entered_by": "bot",
         "closed_at": "2026-06-03T18:00:00+00:00", "entry_context": {}},
    ])
    db["trade_outcomes"].insert_one({"bot_trade_id": "DONE", "setup_type": "vwap_fade_long"})
    db["alert_outcomes"].insert_one({"trade_id": "DONE", "setup_type": "vwap_fade_long"})
    return db


def test_reconcile_ingests_genuine_skips_phantom_and_done():
    db = _seed_db()
    rep = LR.reconcile(db, commit=True, verbose=False)
    # G1 → both sinks ; P1 → alert_outcomes only ; DONE → skipped
    assert rep["to_written"] == 1                         # only G1 into trade_outcomes
    assert rep["to_skipped_nongenuine"] == 1              # P1 phantom kept out of TO
    assert rep["ao_written"] == 2                         # G1 + P1 into alert_outcomes
    to_ids = {d["bot_trade_id"] for d in db["trade_outcomes"].find()}
    assert "G1" in to_ids and "P1" not in to_ids and "DONE" in to_ids
    ao_ids = {d["trade_id"] for d in db["alert_outcomes"].find()}
    assert {"G1", "P1", "DONE"} <= ao_ids


def test_reconcile_is_idempotent():
    db = _seed_db()
    LR.reconcile(db, commit=True, verbose=False)
    n_to = db["trade_outcomes"].count_documents({})
    n_ao = db["alert_outcomes"].count_documents({})
    rep2 = LR.reconcile(db, commit=True, verbose=False)  # second run
    assert rep2["to_written"] == 0 and rep2["ao_written"] == 0
    assert db["trade_outcomes"].count_documents({}) == n_to
    assert db["alert_outcomes"].count_documents({}) == n_ao


def test_reconcile_dry_run_writes_nothing():
    db = _seed_db()
    before_to = db["trade_outcomes"].count_documents({})
    rep = LR.reconcile(db, commit=False, verbose=False)
    assert rep["to_written"] == 1 and rep["ao_written"] == 2   # would-write counts
    assert db["trade_outcomes"].count_documents({}) == before_to  # but nothing written
