"""v19.34.315 — ib_executions persister: unit + idempotency tests."""
from unittest.mock import MagicMock


def test_doc_from_fill_shape():
    from services.ib_executions_persister import _doc_from_fill
    fill = MagicMock()
    fill.contract.symbol = "DVN"
    fill.execution.execId = "X1"
    fill.execution.orderId = 100
    fill.execution.permId = 9999
    fill.execution.acctNumber = "DUN615665"
    fill.execution.side = "SLD"
    fill.execution.shares = 158
    fill.execution.price = 44.46
    fill.execution.time = None
    fill.execution.lastLiquidity = 1
    fill.commissionReport.commission = 1.18
    fill.commissionReport.realizedPNL = 53.92
    doc = _doc_from_fill(fill)
    assert doc is not None
    assert doc["exec_id"] == "X1"
    assert doc["symbol"] == "DVN"
    assert doc["side"] == "SELL"      # "SLD" normalized
    assert doc["shares"] == 158
    assert doc["price"] == 44.46
    assert doc["realized_pnl"] == 53.92
    assert doc["source"] == "ib_persister_v19_34_315"


def test_doc_from_fill_no_exec_id_returns_none():
    from services.ib_executions_persister import _doc_from_fill
    fill = MagicMock()
    fill.execution.execId = ""
    assert _doc_from_fill(fill) is None


def test_doc_from_fill_no_commission_report_safe():
    from services.ib_executions_persister import _doc_from_fill
    fill = MagicMock()
    fill.contract.symbol = "TST"
    fill.execution.execId = "X2"
    fill.execution.orderId = 1
    fill.execution.permId = 0
    fill.execution.acctNumber = "A"
    fill.execution.side = "BOT"
    fill.execution.shares = 10
    fill.execution.price = 1.0
    fill.execution.time = None
    fill.execution.lastLiquidity = 0
    fill.commissionReport = None
    doc = _doc_from_fill(fill)
    assert doc is not None
    assert doc["commission"] == 0.0
    assert doc["realized_pnl"] == 0.0


def test_normalize_side():
    from services.ib_executions_persister import _normalize_side
    assert _normalize_side("BOT") == "BUY"
    assert _normalize_side("BOUGHT") == "BUY"
    assert _normalize_side("SLD") == "SELL"
    assert _normalize_side("SOLD") == "SELL"
    assert _normalize_side("sell_short") == "SELL"
    assert _normalize_side("BUY") == "BUY"
    assert _normalize_side(None) == "?"
    assert _normalize_side("") == "?"


def test_persist_batch_idempotent():
    """Same fill processed twice → 1 insert + 1 skipped_dupe."""
    from services.ib_executions_persister import _persist_batch
    inserted_keys = set()

    class _Result:
        def __init__(self, upserted):
            self.upserted_id = "newid" if upserted else None

    class _Coll:
        def update_one(self, query, update, upsert=False):
            eid = query["exec_id"]
            if eid in inserted_keys:
                return _Result(False)
            inserted_keys.add(eid)
            return _Result(True)

    class _DB:
        def __getitem__(self, _name):
            return _Coll()

    db = _DB()
    fill = MagicMock()
    fill.contract.symbol = "ABC"
    fill.execution.execId = "EXEC42"
    fill.execution.orderId = 1
    fill.execution.permId = 1
    fill.execution.acctNumber = "X"
    fill.execution.side = "BOT"
    fill.execution.shares = 10
    fill.execution.price = 1.0
    fill.execution.time = None
    fill.execution.lastLiquidity = 1
    fill.commissionReport.commission = 0.0
    fill.commissionReport.realizedPNL = 0.0

    ins1, dup1, err1 = _persist_batch(db, [fill])
    assert (ins1, dup1, err1) == (1, 0, 0)

    ins2, dup2, err2 = _persist_batch(db, [fill])
    assert (ins2, dup2, err2) == (0, 1, 0)


def test_persister_stats_keys_present():
    from services.ib_executions_persister import get_persister_stats
    s = get_persister_stats()
    for k in ("iterations", "inserted", "skipped_dupes",
              "errors", "last_run", "last_inserted"):
        assert k in s, f"missing key {k}"
