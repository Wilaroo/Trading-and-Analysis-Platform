"""Tests for TradeAutopsy duplicate-id defensive selection (2026-04-22).

A historical cleanup script left duplicate docs with identical `id` fields
— one zeroed-out, one with real trade data. Autopsy must pick the real
one, not the sanitized one.
"""
from services.trade_autopsy import TradeAutopsy


class _FakeCollection:
    """Minimal Mongo collection stub returning whatever docs were seeded."""
    def __init__(self, docs):
        self._docs = docs

    def find(self, filter_, projection=None):
        tid = filter_.get("id")
        return [d for d in self._docs if d.get("id") == tid]

    def find_one(self, filter_, projection=None, sort=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in filter_.items() if not isinstance(v, dict)):
                return d
        return None

    def estimated_document_count(self):
        return len(self._docs)


class _FakeDB:
    def __init__(self, bot_trades=None, gate_decisions=None, live_alerts=None):
        self._colls = {
            "bot_trades": _FakeCollection(bot_trades or []),
            "gate_decisions": _FakeCollection(gate_decisions or []),
            "live_alerts": _FakeCollection(live_alerts or []),
        }

    def __getitem__(self, name):
        return self._colls[name]


def test_autopsy_prefers_real_loss_over_zeroed_duplicate():
    """Classic PD case: one doc zeroed by cleanup, another has the real -7294 loss."""
    docs = [
        {"id": "c81075d0", "symbol": "PD", "setup_type": "imported_from_ib",
         "direction": "long", "entry_price": 7.305, "stop_price": 7.0,
         "exit_price": 0, "realized_pnl": 0.0, "status": "closed_manual",
         "close_reason": "Legacy cleanup — validator fail-open era"},
        {"id": "c81075d0", "symbol": "PD", "setup_type": "imported_from_ib",
         "direction": "long", "entry_price": 7.305, "stop_price": 7.0,
         "exit_price": 6.24, "realized_pnl": -7294.18, "r_multiple": -3.4918,
         "status": "closed", "close_reason": "stop_loss"},
    ]
    autopsy = TradeAutopsy(_FakeDB(bot_trades=docs)).autopsy("c81075d0")
    assert autopsy is not None
    assert autopsy["status"] == "closed"                           # winner picked
    assert autopsy["outcome"]["verdict"] == "loss"
    assert autopsy["outcome"]["realized_R"] == -3.492    # rounded to 3 dp
    assert autopsy["outcome"]["pnl_usd"] == -7294.18


def test_autopsy_single_doc_returns_it_verbatim():
    docs = [{"id": "t1", "symbol": "AAPL", "setup_type": "rubber_band",
             "direction": "long", "entry_price": 100, "stop_price": 98,
             "exit_price": 104, "realized_pnl": 400, "r_multiple": 2.0,
             "status": "closed"}]
    r = TradeAutopsy(_FakeDB(bot_trades=docs)).autopsy("t1")
    assert r["outcome"]["verdict"] == "win"


def test_autopsy_returns_none_for_missing_trade():
    assert TradeAutopsy(_FakeDB(bot_trades=[])).autopsy("missing") is None


def test_autopsy_prefers_nonzero_pnl_when_r_multiple_missing_on_both():
    """When neither has r_multiple, pick the one with real pnl."""
    docs = [
        {"id": "x", "symbol": "A", "direction": "long",
         "realized_pnl": 0.0, "exit_price": 0, "status": "cleaned"},
        {"id": "x", "symbol": "A", "direction": "long",
         "realized_pnl": -500, "exit_price": 95, "status": "closed",
         "entry_price": 100, "stop_price": 98},
    ]
    r = TradeAutopsy(_FakeDB(bot_trades=docs)).autopsy("x")
    assert r["status"] == "closed"
    assert r["outcome"]["pnl_usd"] == -500.0
