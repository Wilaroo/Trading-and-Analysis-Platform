"""
v313 tests:
  1. Env-tunable triple-barrier defaults (TB_PT_MULT / TB_SL_MULT / TB_ATR_PERIOD)
     wired through triple_barrier_config as the single source of truth.
  2. BSON-safe backtest-result insert (_safe_insert_result) that trims raw trade
     logs instead of losing the whole document on "BSON document too large".
"""
import importlib
import os

import pytest


# ── 1. Barrier env defaults ──────────────────────────────────────────────

def _reload_tb_config():
    import services.ai_modules.triple_barrier_config as tbc
    return importlib.reload(tbc)


def test_default_barrier_unchanged_without_env(monkeypatch):
    for k in ("TB_PT_MULT", "TB_SL_MULT", "TB_ATR_PERIOD"):
        monkeypatch.delenv(k, raising=False)
    tbc = _reload_tb_config()
    assert tbc.get_global_tb_defaults() == (2.0, 1.0, 14)
    assert tbc.DEFAULT_PT == 2.0 and tbc.DEFAULT_SL == 1.0


def test_env_overrides_barrier(monkeypatch):
    monkeypatch.setenv("TB_PT_MULT", "1.5")
    monkeypatch.setenv("TB_SL_MULT", "1.0")
    monkeypatch.setenv("TB_ATR_PERIOD", "20")
    tbc = _reload_tb_config()
    assert tbc.get_global_tb_defaults() == (1.5, 1.0, 20)


def test_symmetric_barrier_supported(monkeypatch):
    monkeypatch.setenv("TB_PT_MULT", "1.0")
    monkeypatch.setenv("TB_SL_MULT", "1.0")
    monkeypatch.delenv("TB_ATR_PERIOD", raising=False)
    tbc = _reload_tb_config()
    pt, sl, atr = tbc.get_global_tb_defaults()
    assert pt == sl == 1.0 and atr == 14


# ── 2. BSON-safe insert ──────────────────────────────────────────────────

class _FakeCol:
    """Mimics a Mongo collection that rejects docs over a byte budget."""
    def __init__(self, limit_bytes):
        self.limit = limit_bytes
        self.inserted = None

    def insert_one(self, doc):
        # rough size proxy: count trade entries
        n = len(doc.get("trades", []))
        for sr in doc.get("strategy_results", []) or []:
            n += len(sr.get("trades", []))
        if n > self.limit:
            raise Exception(f"BSON document too large ({n} > {self.limit})")
        self.inserted = doc


def _get_safe_insert():
    from services.slow_learning.advanced_backtest_engine import _safe_insert_result
    return _safe_insert_result


def test_small_doc_inserts_unchanged():
    safe_insert = _get_safe_insert()
    col = _FakeCol(limit_bytes=1000)
    doc = {"summary": {"win_rate": 0.5}, "trades": [{"pnl": 1}] * 10}
    safe_insert(col, doc)
    assert col.inserted is not None
    assert len(col.inserted["trades"]) == 10
    assert "trades_truncated" not in col.inserted


def test_oversize_doc_trims_trades_keeps_summary():
    safe_insert = _get_safe_insert()
    col = _FakeCol(limit_bytes=500)  # 200-cap × 2 arrays = 400, fits under 500
    doc = {
        "summary": {"win_rate": 0.6, "sharpe": 1.2},
        "strategy_results": [{"strategy_name": "A", "win_rate": 0.6, "trades": [{"pnl": 1}] * 5000}],
        "trades": [{"pnl": 1}] * 5000,
    }
    safe_insert(col, doc)
    assert col.inserted is not None
    # Summary survives
    assert col.inserted["summary"]["sharpe"] == 1.2
    # Raw trades capped to 200 and original count recorded
    assert len(col.inserted["trades"]) == 200
    assert col.inserted["trades_truncated"] == 5000
    assert len(col.inserted["strategy_results"][0]["trades"]) == 200


def test_extreme_oversize_drops_trades_entirely():
    safe_insert = _get_safe_insert()
    col = _FakeCol(limit_bytes=50)  # even 200 cap (per array) won't fit
    doc = {"summary": {"x": 1}, "trades": [{"pnl": 1}] * 100000}
    safe_insert(col, doc)
    assert col.inserted is not None
    assert col.inserted.get("trades", []) == []  # dropped
    assert col.inserted["summary"]["x"] == 1


def test_non_size_error_reraises():
    safe_insert = _get_safe_insert()

    class _BrokenCol:
        def insert_one(self, doc):
            raise Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        safe_insert(_BrokenCol(), {"trades": []})
