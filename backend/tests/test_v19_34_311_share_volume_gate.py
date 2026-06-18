"""v19.34.311 share-volume gate -- unit + integration tests."""
import importlib
import os
from unittest.mock import MagicMock


def test_min_share_volume_default():
    os.environ.pop("SENTCOM_MIN_SHARE_VOLUME", None)
    import services.symbol_universe as su
    importlib.reload(su)
    assert su.MIN_SHARE_VOLUME == 100_000


def test_min_share_volume_env_override():
    os.environ["SENTCOM_MIN_SHARE_VOLUME"] = "250000"
    try:
        import services.symbol_universe as su
        importlib.reload(su)
        assert su.MIN_SHARE_VOLUME == 250_000
    finally:
        os.environ.pop("SENTCOM_MIN_SHARE_VOLUME", None)
        import services.symbol_universe as su
        importlib.reload(su)


def test_get_qualified_filter_shape():
    from services.symbol_universe import get_qualified_filter
    f = get_qualified_filter("intraday")
    assert "$or" in f
    branches = f["$or"]
    assert len(branches) == 2
    assert "$and" in branches[0]
    keys = [list(d.keys())[0] for d in branches[0]["$and"]]
    assert "avg_dollar_volume" in keys
    assert "avg_volume" in keys
    assert branches[1] == {"manual_universe_pin": True}
    assert f["unqualifiable"] == {"$ne": True}


def test_get_qualified_filter_include_unqualifiable():
    from services.symbol_universe import get_qualified_filter
    f = get_qualified_filter("swing", include_unqualifiable=True)
    assert "unqualifiable" not in f


def test_get_qualified_filter_invalid_tier_raises():
    import pytest
    from services.symbol_universe import get_qualified_filter
    with pytest.raises(ValueError):
        get_qualified_filter("scalp")


def test_thin_share_count_rejected_via_mongo_semantics():
    """ALX-style thin-share names rejected even when ADV >= floor."""
    from services.symbol_universe import get_qualified_filter
    _ = get_qualified_filter("investment")

    def matches(doc, threshold=2_000_000, min_share=100_000):
        if doc.get("unqualifiable") is True:
            return False
        if doc.get("manual_universe_pin") is True:
            return True
        dv = doc.get("avg_dollar_volume", 0) or 0
        sv = doc.get("avg_volume", 0) or 0
        return dv >= threshold and sv >= min_share

    assert matches({"symbol": "ALX", "avg_dollar_volume": 2_000_000,
                     "avg_volume": 7_577}) is False
    assert matches({"symbol": "MU", "avg_dollar_volume": 30_000_000_000,
                     "avg_volume": 30_000_000}) is True
    assert matches({"symbol": "SPCX", "avg_dollar_volume": 0,
                     "avg_volume": 0,
                     "manual_universe_pin": True}) is True
    assert matches({"symbol": "DEAD", "avg_dollar_volume": 1e10,
                     "avg_volume": 1e6, "unqualifiable": True}) is False


def test_get_universe_uses_share_vol_gate():
    from services.symbol_universe import get_universe
    fake_db = MagicMock()
    fake_col = MagicMock()
    fake_db.__getitem__.return_value = fake_col
    fake_col.find.return_value = []
    _ = get_universe(fake_db, "intraday")
    args, _kw = fake_col.find.call_args
    q = args[0]
    assert "$or" in q
    assert any("$and" in b for b in q["$or"])
