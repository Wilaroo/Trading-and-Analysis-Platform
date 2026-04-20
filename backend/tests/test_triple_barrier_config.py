"""
Tests for triple_barrier_config get/save and round-trip behavior.
Uses mongomock to avoid requiring a live Mongo instance.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_triple_barrier_config.py -v
"""
import pytest

# mongomock is already in requirements.txt for similar tests; guard just in case
mongomock = pytest.importorskip("mongomock")

from services.ai_modules.triple_barrier_config import (
    get_tb_config, save_tb_config, list_all_configs, DEFAULT_PT, DEFAULT_SL,
)


def _make_db():
    client = mongomock.MongoClient()
    return client["tradecommand"]


def test_default_when_empty():
    db = _make_db()
    cfg = get_tb_config(db, "BREAKOUT", "5 mins", "long", default_max_bars=12)
    assert cfg["pt_atr_mult"] == DEFAULT_PT
    assert cfg["sl_atr_mult"] == DEFAULT_SL
    assert cfg["max_bars"] == 12
    assert cfg["source"] == "default"


def test_save_and_roundtrip():
    db = _make_db()
    save_tb_config(
        db, "VWAP", "1 day", "long",
        pt_atr_mult=2.5, sl_atr_mult=0.75,
        max_bars=20, atr_period=14,
        sweep_metrics={"down": 0.31, "flat": 0.32, "up": 0.37, "balance_score": 0.01},
    )
    cfg = get_tb_config(db, "VWAP", "1 day", "long", default_max_bars=20)
    assert cfg["pt_atr_mult"] == 2.5
    assert cfg["sl_atr_mult"] == 0.75
    assert cfg["max_bars"] == 20
    assert cfg["source"] == "db"
    assert cfg["chosen_at"] is not None


def test_cross_side_fallback():
    db = _make_db()
    # Save LONG only
    save_tb_config(db, "GAP_FILL", "5 mins", "long", 1.5, 0.5, 10, 14)
    # Ask for SHORT — should fall back to long-side config (cross_side)
    cfg = get_tb_config(db, "GAP_FILL", "5 mins", "short", default_max_bars=10)
    assert cfg["pt_atr_mult"] == 1.5
    assert cfg["sl_atr_mult"] == 0.5
    assert cfg["source"] == "db_cross_side"


def test_list_all():
    db = _make_db()
    save_tb_config(db, "ORB", "5 mins", "long", 2.0, 1.0, 12, 14)
    save_tb_config(db, "ORB", "5 mins", "short", 2.0, 1.0, 12, 14)
    save_tb_config(db, "MOMENTUM", "1 day", "long", 2.5, 1.0, 20, 14)
    configs = list_all_configs(db)
    assert len(configs) == 3
    # Compound key is unique
    keys = {(c["setup_type"], c["bar_size"], c["trade_side"]) for c in configs}
    assert len(keys) == 3


def test_upsert_replaces_existing():
    db = _make_db()
    save_tb_config(db, "TREND", "1 hour", "long", 2.0, 1.0, 15, 14)
    save_tb_config(db, "TREND", "1 hour", "long", 2.5, 0.75, 15, 14)
    configs = list_all_configs(db)
    trend = [c for c in configs if c["setup_type"] == "TREND"]
    assert len(trend) == 1
    assert trend[0]["pt_atr_mult"] == 2.5
    assert trend[0]["sl_atr_mult"] == 0.75
