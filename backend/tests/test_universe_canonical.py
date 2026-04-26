"""
Canonical Universe contract tests
=================================

Locks the invariant that smart-backfill, backfill_readiness, and the AI
training pipeline all read from `services.symbol_universe.get_universe`
with the same dollar-volume thresholds — so they can never drift apart
again the way they did pre-2026-04-26 (share-volume vs dollar-volume,
2,648 vs 1,186 symbols).
"""
from __future__ import annotations

import importlib
import inspect
from typing import Any, Dict, List, Optional

import pytest


# ---- Mocks ------------------------------------------------------------

class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __iter__(self):
        return iter(self._docs)


class _Coll:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.updates: List[Dict[str, Any]] = []
        self.database = None  # filled in by _DB

    def find(self, query: Dict[str, Any], proj=None):
        return _Cursor(d for d in self.docs if _matches(d, query))

    def find_one(self, query: Dict[str, Any], proj=None, sort=None):
        for d in self.docs:
            if _matches(d, query):
                return dict(d)
        return None

    def count_documents(self, query: Dict[str, Any], limit: Optional[int] = None) -> int:
        n = 0
        for d in self.docs:
            if _matches(d, query):
                n += 1
                if limit and n >= limit:
                    break
        return n

    def update_one(self, filt, update, upsert=False):
        target = None
        for d in self.docs:
            if _matches(d, filt):
                target = d
                break
        if target is None:
            if not upsert:
                class _Res:
                    modified_count = 0
                return _Res()
            target = {**filt}
            for op_key, op_val in (update.get("$setOnInsert") or {}).items():
                target[op_key] = op_val
            self.docs.append(target)
        for op_key, op_val in (update.get("$set") or {}).items():
            target[op_key] = op_val
        for op_key, op_val in (update.get("$inc") or {}).items():
            target[op_key] = (target.get(op_key) or 0) + op_val
        self.updates.append({"filt": filt, "update": update})
        class _Res:
            modified_count = 1
        return _Res()


def _matches(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            if "$gte" in v and not (doc.get(k) is not None and doc.get(k) >= v["$gte"]):
                return False
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
        else:
            if doc.get(k) != v:
                return False
    return True


class _DB:
    def __init__(self, adv_docs=None):
        self._adv = _Coll(adv_docs or [])
        self._adv.database = self

    def __getitem__(self, name):
        if name == "symbol_adv_cache":
            return self._adv
        return _Coll()


# ---- Threshold contract ----------------------------------------------

def test_thresholds_are_dollar_volume_per_user_2026_04_26():
    """Locked: $50M / $10M / $2M dollar-volume thresholds. If product
    decides to move them, they must move HERE in symbol_universe.py —
    not in random places across collector / readiness / training."""
    from services import symbol_universe as su
    assert su.INTRADAY_THRESHOLD == 50_000_000
    assert su.SWING_THRESHOLD == 10_000_000
    assert su.INVESTMENT_THRESHOLD == 2_000_000
    assert su.DOLLAR_VOL_THRESHOLDS == {
        "intraday": 50_000_000,
        "swing": 10_000_000,
        "investment": 2_000_000,
    }


def test_classify_tier_maps_dollar_volume_correctly():
    from services.symbol_universe import classify_tier
    assert classify_tier(75_000_000) == "intraday"
    assert classify_tier(50_000_000) == "intraday"
    assert classify_tier(49_999_999) == "swing"
    assert classify_tier(10_000_000) == "swing"
    assert classify_tier(9_999_999) == "investment"
    assert classify_tier(2_000_000) == "investment"
    assert classify_tier(1_999_999) is None
    assert classify_tier(0) is None
    assert classify_tier(None) is None


# ---- get_universe contract -------------------------------------------

def _adv_fixture():
    """Mix of intraday/swing/investment/sub-threshold/unqualifiable rows."""
    return [
        {"symbol": "AAPL",  "avg_dollar_volume": 200_000_000},   # intraday
        {"symbol": "MSFT",  "avg_dollar_volume":  60_000_000},   # intraday
        {"symbol": "TSLA",  "avg_dollar_volume":  50_000_000},   # intraday (boundary)
        {"symbol": "DIS",   "avg_dollar_volume":  20_000_000},   # swing
        {"symbol": "ROKU",  "avg_dollar_volume":  10_000_000},   # swing (boundary)
        {"symbol": "PLTR",  "avg_dollar_volume":   5_000_000},   # investment
        {"symbol": "ABCD",  "avg_dollar_volume":   2_000_000},   # investment (boundary)
        {"symbol": "TINY",  "avg_dollar_volume":     500_000},   # unqualified
        {"symbol": "DEAD",  "avg_dollar_volume": 100_000_000,
         "unqualifiable": True},                                 # excluded
    ]


def test_get_universe_intraday_only_includes_50M_plus():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    intraday = get_universe(db, "intraday")
    assert intraday == {"AAPL", "MSFT", "TSLA"}


def test_get_universe_swing_includes_intraday_and_swing():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    swing = get_universe(db, "swing")
    assert swing == {"AAPL", "MSFT", "TSLA", "DIS", "ROKU"}


def test_get_universe_investment_includes_all_qualified():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    investment = get_universe(db, "investment")
    assert investment == {"AAPL", "MSFT", "TSLA", "DIS", "ROKU", "PLTR", "ABCD"}


def test_get_universe_all_alias_matches_investment():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    assert get_universe(db, "all") == get_universe(db, "investment")


def test_get_universe_excludes_unqualifiable_by_default():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    # DEAD has $100M avg_dollar_volume but unqualifiable=True → must be
    # filtered out of every tier query.
    assert "DEAD" not in get_universe(db, "intraday")
    assert "DEAD" not in get_universe(db, "swing")
    assert "DEAD" not in get_universe(db, "investment")


def test_get_universe_can_include_unqualifiable_for_diagnostics():
    from services.symbol_universe import get_universe
    db = _DB(_adv_fixture())
    full = get_universe(db, "intraday", include_unqualifiable=True)
    assert "DEAD" in full


def test_get_universe_rejects_unknown_tier():
    from services.symbol_universe import get_universe
    db = _DB([])
    with pytest.raises(ValueError):
        get_universe(db, "scalp")


# ---- mark_unqualifiable promotion semantics --------------------------

def test_mark_unqualifiable_promotes_after_threshold_strikes():
    from services import symbol_universe as su
    db = _DB([{"symbol": "FOO", "avg_dollar_volume": 100_000_000}])

    r1 = su.mark_unqualifiable(db, "FOO", reason="No security definition")
    assert r1["failure_count"] == 1
    assert r1["unqualifiable"] is False
    assert r1["promoted_now"] is False

    r2 = su.mark_unqualifiable(db, "FOO", reason="No security definition")
    assert r2["failure_count"] == 2
    assert r2["unqualifiable"] is False

    r3 = su.mark_unqualifiable(db, "FOO", reason="No security definition")
    assert r3["failure_count"] == su.UNQUALIFIABLE_FAILURE_THRESHOLD
    assert r3["unqualifiable"] is True
    assert r3["promoted_now"] is True

    # Already promoted — calling again does NOT re-emit promoted_now=True.
    r4 = su.mark_unqualifiable(db, "FOO", reason="No security definition")
    assert r4["unqualifiable"] is True
    assert r4["promoted_now"] is False

    # And the symbol is now excluded from the universe.
    assert "FOO" not in su.get_universe(db, "intraday")


def test_mark_unqualifiable_upserts_unknown_symbol():
    from services import symbol_universe as su
    db = _DB([])
    r = su.mark_unqualifiable(db, "ZZZZ")
    assert r["success"] is True
    assert r["failure_count"] == 1


def test_reset_unqualifiable_clears_flag():
    from services import symbol_universe as su
    db = _DB([{"symbol": "DEAD", "avg_dollar_volume": 100_000_000,
               "unqualifiable": True, "unqualifiable_failure_count": 5}])
    assert su.reset_unqualifiable(db, "DEAD") is True
    # DEAD should now reappear in the universe.
    assert "DEAD" in su.get_universe(db, "intraday")


# ---- Source-level invariant: smart-backfill + readiness use the SAME
#      universe primitive. This is the test that prevents future drift.
# ----------------------------------------------------------------------

def test_smart_backfill_uses_canonical_universe_module():
    """`_smart_backfill_sync` must derive its universe via
    services.symbol_universe (not its own ad-hoc dollar-volume query)."""
    src = inspect.getsource(
        importlib.import_module("services.ib_historical_collector")
    )
    assert "from .symbol_universe import" in src or \
           "from services.symbol_universe import" in src, (
        "ib_historical_collector must import from services.symbol_universe "
        "so smart-backfill, readiness, and training share one universe definition."
    )


def test_readiness_uses_canonical_universe_module():
    """Same contract for backfill_readiness_service."""
    src = inspect.getsource(
        importlib.import_module("services.backfill_readiness_service")
    )
    assert "from .symbol_universe import" in src or \
           "from services.symbol_universe import" in src, (
        "backfill_readiness_service must import from services.symbol_universe "
        "so its 'intraday universe' matches smart-backfill's exactly."
    )


def test_readiness_no_longer_uses_share_volume_threshold():
    """Locks out the share-volume regression — the discrepancy that
    inflated training to 4,000+ symbols pre-2026-04-26."""
    src = inspect.getsource(
        importlib.import_module("services.backfill_readiness_service")
    )
    assert 'avg_volume": {"$gte": 500_000' not in src, (
        "backfill_readiness_service must NOT use share-volume thresholds. "
        "Use services.symbol_universe.get_universe(db, 'intraday') instead."
    )


def test_default_iberndate_format_is_hyphen():
    """User confirmed 2026-04-26: default to IB-recommended hyphen
    format. Silences Warning 2174 + future-proofs against IB removing
    space-form support."""
    src = inspect.getsource(
        importlib.import_module("services.ib_historical_collector")
    )
    assert 'IB_ENDDATE_FORMAT", "hyphen"' in src, (
        'IB_ENDDATE_FORMAT default must be "hyphen" (was "space" until 2026-04-26).'
    )


# ---- Bar-size → tier mapping contract --------------------------------

def test_bar_size_to_tier_mapping_is_canonical():
    """1m–30m must train on intraday tier; 1h/1d on swing+; 1w on
    investment+. This is the contract every training phase relies on."""
    from services.symbol_universe import BAR_SIZE_TIER
    assert BAR_SIZE_TIER["1 min"]   == "intraday"
    assert BAR_SIZE_TIER["5 mins"]  == "intraday"
    assert BAR_SIZE_TIER["15 mins"] == "intraday"
    assert BAR_SIZE_TIER["30 mins"] == "intraday"
    assert BAR_SIZE_TIER["1 hour"]  == "swing"
    assert BAR_SIZE_TIER["1 day"]   == "swing"
    assert BAR_SIZE_TIER["1 week"]  == "investment"


def test_get_universe_for_bar_size_routes_correctly():
    from services.symbol_universe import get_universe_for_bar_size
    db = _DB(_adv_fixture())
    # 1-min training pulls the intraday universe.
    assert get_universe_for_bar_size(db, "1 min")  == {"AAPL", "MSFT", "TSLA"}
    # 1-hour training pulls swing+ (intraday ⊂ swing).
    assert get_universe_for_bar_size(db, "1 hour") == {"AAPL", "MSFT", "TSLA",
                                                       "DIS", "ROKU"}
    # 1-week training pulls investment+ (everything qualified).
    assert get_universe_for_bar_size(db, "1 week") == {"AAPL", "MSFT", "TSLA",
                                                       "DIS", "ROKU", "PLTR",
                                                       "ABCD"}


def test_universe_stats_exposes_per_bar_size_training_projection():
    from services.symbol_universe import get_universe_stats
    db = _DB(_adv_fixture())
    stats = get_universe_stats(db)
    per_bs = stats.get("training_universe_per_bar_size", {})
    assert "1 min" in per_bs and per_bs["1 min"]["tier"] == "intraday"
    assert per_bs["1 min"]["symbols"] == 3   # AAPL, MSFT, TSLA
    assert per_bs["1 hour"]["symbols"] == 5  # + DIS, ROKU
    assert per_bs["1 week"]["symbols"] == 7  # + PLTR, ABCD


# ---- Training pipeline integration invariants ------------------------

def test_training_pipeline_uses_canonical_universe_module():
    """get_available_symbols MUST go through services.symbol_universe.
    Locks out the historical 'rank by share volume from raw adv cache'
    regression that drove training to 4,000+ symbols pre-2026-04-26."""
    src = inspect.getsource(
        importlib.import_module("services.ai_modules.training_pipeline")
    )
    assert "get_universe_for_bar_size" in src, (
        "training_pipeline must call get_universe_for_bar_size so the "
        "AI training universe matches smart-backfill + readiness."
    )


def test_timeseries_service_uses_canonical_universe_module():
    src = inspect.getsource(
        importlib.import_module("services.ai_modules.timeseries_service")
    )
    assert "get_universe_for_bar_size" in src, (
        "timeseries_service get_training_symbols must call "
        "get_universe_for_bar_size to share the canonical universe."
    )


def test_post_training_validator_excludes_unqualifiable():
    """Validator must respect the canonical universe's unqualifiable
    flag, otherwise validation backtests run on dead/delisted symbols."""
    src = inspect.getsource(
        importlib.import_module("services.ai_modules.post_training_validator")
    )
    assert '"unqualifiable":' in src and '$ne' in src, (
        "_get_validation_symbols must filter out unqualifiable symbols."
    )
