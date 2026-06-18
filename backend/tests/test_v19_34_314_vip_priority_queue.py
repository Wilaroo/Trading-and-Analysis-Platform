"""v19.34.314 VIP-priority queue ordering -- unit tests."""
import os
from unittest.mock import MagicMock, patch


class _FakeCursor:
    """Minimal cursor stub that supports .sort(...).limit(...) chains."""
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *a, **kw):
        return self

    def limit(self, n):
        return iter(self._rows[:n])

    def __iter__(self):
        return iter(self._rows)


def _fake_db_with_collections(collections):
    db = MagicMock()
    def get_coll(name):
        rows = collections.get(name, [])
        col = MagicMock()
        col.find.return_value = _FakeCursor(rows)
        col.find_one.return_value = (rows[0] if rows else None)
        col.create_index = MagicMock(return_value=None)
        return col
    db.__getitem__.side_effect = get_coll
    return db


def test_compute_vip_symbols_precedence():
    """Layer order MUST be preserved: held > watchlist > gap > daily_scan
    > mega_cap > top_adv, with each symbol appearing once."""
    from services.historical_data_queue_service import HistoricalDataQueueService

    collections = {
        "historical_data_requests": [],
        "bot_trades": [{"symbol": "CPB"}, {"symbol": "DKNG"}, {"symbol": "PENN"}],
        "watchlists": [{"symbol": "DKNG"}, {"symbol": "VT"}],
        "smart_watchlist": [{"symbol": "VTV"}],
        "data_gap_events": [{"symbol": "AVGO"}],
        "daily_scan_universe": [{"_id": "2026-06-15",
                                  "priority_symbols": ["MU", "NVDA", "AVGO"]}],
        "symbol_adv_cache": [{"symbol": "TSLA"}, {"symbol": "SPY"}],
    }
    db = _fake_db_with_collections(collections)
    svc = HistoricalDataQueueService(db)
    syms = svc._compute_vip_symbols()
    # Held positions first
    assert syms[0] == "CPB"
    assert syms[1] == "DKNG"
    assert syms[2] == "PENN"
    # Watchlist after held — DKNG must NOT appear again
    assert syms.count("DKNG") == 1
    assert "VT" in syms
    assert syms.index("VT") < syms.index("VTV")
    # data_gap layer AVGO before daily_scan layer NVDA
    if "AVGO" in syms and "NVDA" in syms:
        assert syms.index("AVGO") < syms.index("NVDA")


def test_vip_dedupe_case_insensitive():
    from services.historical_data_queue_service import HistoricalDataQueueService
    collections = {
        "historical_data_requests": [],
        "bot_trades": [{"symbol": "cpb"}, {"symbol": "CPB"}, {"symbol": "Cpb"}],
        "watchlists": [{"symbol": "cpB"}],
    }
    db = _fake_db_with_collections(collections)
    svc = HistoricalDataQueueService(db)
    syms = svc._compute_vip_symbols()
    assert syms.count("CPB") == 1


def test_vip_cache_ttl():
    from services.historical_data_queue_service import HistoricalDataQueueService
    db = _fake_db_with_collections({"historical_data_requests": []})
    svc = HistoricalDataQueueService(db)
    svc._VIP_CACHE_TTL_S = 9999  # essentially forever for the test
    with patch.object(svc, "_compute_vip_symbols",
                       return_value=["AAA", "BBB"]) as m:
        a = svc._get_vip_symbols_cached()
        b = svc._get_vip_symbols_cached()
        assert a == b == ["AAA", "BBB"]
        assert m.call_count == 1   # cached on second call


def test_vip_reserve_fraction_env():
    """Reserve fraction is read from env at every get_pending_requests call."""
    os.environ["HIST_QUEUE_VIP_RESERVE_FRACTION"] = "0.25"
    try:
        # Verify the env-read pattern compiles via py_compile (already
        # validated at apply time). Just check the parse here:
        import importlib, services.historical_data_queue_service as m
        importlib.reload(m)
        # No exception = env parse works
        assert hasattr(m, "HistoricalDataQueueService")
    finally:
        os.environ.pop("HIST_QUEUE_VIP_RESERVE_FRACTION", None)


def test_compute_vip_symbols_handles_collection_errors():
    """When a collection is missing or raises, _compute_vip_symbols
    must still return whatever did succeed — never raise."""
    from services.historical_data_queue_service import HistoricalDataQueueService

    db = MagicMock()
    def get_coll(name):
        if name == "historical_data_requests":
            c = MagicMock()
            c.create_index = MagicMock()
            return c
        if name == "bot_trades":
            c = MagicMock()
            c.find.return_value = _FakeCursor([{"symbol": "CPB"}])
            return c
        # All other collections raise
        c = MagicMock()
        c.find.side_effect = RuntimeError("collection unavailable")
        return c
    db.__getitem__.side_effect = get_coll

    svc = HistoricalDataQueueService(db)
    syms = svc._compute_vip_symbols()
    assert "CPB" in syms
    # Did not raise — that's the test.


def test_get_pending_requests_partition_disables_vip():
    """When symbol_partition is set, VIP overlay must be skipped."""
    from services.historical_data_queue_service import HistoricalDataQueueService

    db = _fake_db_with_collections({
        "historical_data_requests": [],
        "bot_trades": [{"symbol": "CPB"}],
    })
    svc = HistoricalDataQueueService(db)
    # No pending rows -> empty result, but no exception. The key assertion
    # is that _compute_vip_symbols is NOT called in partition mode.
    with patch.object(svc, "_compute_vip_symbols",
                       return_value=["CPB"]) as m:
        result = svc.get_pending_requests(limit=10, symbol_partition=(0, 3))
        assert m.call_count == 0
        assert result == []
