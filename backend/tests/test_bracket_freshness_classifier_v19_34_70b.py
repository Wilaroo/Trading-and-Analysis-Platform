"""v19.34.70 PATCH B — `_classify_bracket_freshness` validates tracked
orderIds against IB's live order cache.

Bug fixed (2026-05-21 incident): `/attach-brackets-to-unprotected` and
`protect-orphans` both checked `bool(trade.stop_order_id)` to decide
whether a trade was already protected. With 21 positions whose tracked
orderIds pointed at long-gone IB orders (pusher silently failed to
report cancel results → v19.34.65b stale-dropped the queue entries →
IB cleaned up the orders internally), every endpoint correctly
considered them "already_bracketed" and refused to act — leaving every
position naked at IB during market hours.

This test suite covers the `_classify_bracket_freshness` helper that
now backstops both endpoints. The classifier reads IB's live cache and
labels each tracked orderId as:
  - "live"       → present in IB cache
  - "stale"      → set in bot memory, missing from IB cache (cache
                   was queryable)
  - "unverified" → set in bot memory, IB cache could not be queried
                   (safety fallback to legacy memory-only trust)
  - "sim"        → SIM-* placeholder (paper mode)
  - "absent"     → no id in bot memory

The endpoints derive `has_real_stop` / `has_real_target` from these
labels.
"""
import types

import pytest

from routers.trading_bot import _classify_bracket_freshness


class _FakeTrade:
    def __init__(self, stop_oid=None, target_oid=None, target_oids=None):
        self.stop_order_id = stop_oid
        self.target_order_id = target_oid
        self.target_order_ids = target_oids or []


# --- LIVE classification ---
def test_live_stop_and_target_ids():
    """The happy path: bot tracks ids and IB cache confirms them live."""
    trade = _FakeTrade(stop_oid=4729, target_oid=4730)
    cls = _classify_bracket_freshness(trade, live_ids={4729, 4730},
                                       cache_available=True)
    assert cls["stop_state"] == "live"
    assert cls["target_state"] == "live"
    assert cls["has_real_stop"] is True
    assert cls["has_real_target"] is True


def test_live_target_via_plural_list():
    """target_order_ids list with at least one live id classifies the
    overall target as live."""
    trade = _FakeTrade(stop_oid=100, target_oids=[200, 300])
    cls = _classify_bracket_freshness(trade, live_ids={100, 300},
                                       cache_available=True)
    assert cls["target_state"] == "live"
    assert cls["has_real_target"] is True


# --- STALE classification (the 2026-05-21 bug) ---
def test_stale_ids_in_bot_memory_but_gone_from_ib():
    """The exact bug: bot tracks 4729/4730, IB cache has empty set,
    cache_available=True. Pre-fix: blindly trusted memory → returned
    has_real=True. Post-fix: returns has_real=False."""
    trade = _FakeTrade(stop_oid=4729, target_oid=4730)
    cls = _classify_bracket_freshness(trade, live_ids=set(),
                                       cache_available=True)
    assert cls["stop_state"] == "stale"
    assert cls["target_state"] == "stale"
    assert cls["has_real_stop"] is False
    assert cls["has_real_target"] is False


def test_mixed_live_stop_stale_target():
    """Stop is still live at IB but target got cleaned up — endpoint
    should NOT consider this fully bracketed and should re-attach."""
    trade = _FakeTrade(stop_oid=100, target_oid=200)
    cls = _classify_bracket_freshness(trade, live_ids={100},
                                       cache_available=True)
    assert cls["stop_state"] == "live"
    assert cls["target_state"] == "stale"
    assert cls["has_real_stop"] is True
    assert cls["has_real_target"] is False


def test_target_plural_all_stale():
    """If every id in target_order_ids is stale, target_state is
    stale (not live, not absent)."""
    trade = _FakeTrade(stop_oid=100, target_oids=[200, 300])
    cls = _classify_bracket_freshness(trade, live_ids={100},
                                       cache_available=True)
    assert cls["target_state"] == "stale"
    assert cls["has_real_target"] is False


# --- UNVERIFIED classification (safety fallback) ---
def test_unverified_when_cache_unavailable():
    """When ib_direct cannot be queried, classifier MUST fall back to
    'unverified' for every set id — and `has_real_*` MUST be True
    (trust bot memory). Refusing to act when blind is worse than
    occasionally double-attaching."""
    trade = _FakeTrade(stop_oid=100, target_oid=200)
    cls = _classify_bracket_freshness(trade, live_ids=set(),
                                       cache_available=False)
    assert cls["stop_state"] == "unverified"
    assert cls["target_state"] == "unverified"
    assert cls["has_real_stop"] is True
    assert cls["has_real_target"] is True


def test_unverified_target_plural_still_unverified():
    trade = _FakeTrade(stop_oid=100, target_oids=[200, 300])
    cls = _classify_bracket_freshness(trade, live_ids=set(),
                                       cache_available=False)
    assert cls["target_state"] == "unverified"
    assert cls["has_real_target"] is True


# --- SIM mode ---
def test_sim_ids_classified_as_sim():
    trade = _FakeTrade(stop_oid="SIM-STOP-abc", target_oid="SIM-TGT-xyz")
    cls = _classify_bracket_freshness(trade, live_ids=set(),
                                       cache_available=True)
    assert cls["stop_state"] == "sim"
    assert cls["target_state"] == "sim"
    assert cls["has_real_stop"] is False
    assert cls["has_real_target"] is False


def test_sim_mixed_with_real_target():
    """If sim and a real live id coexist in target_order_ids, the live
    one wins."""
    trade = _FakeTrade(stop_oid=100, target_oids=["SIM-TGT-xyz", 200])
    cls = _classify_bracket_freshness(trade, live_ids={100, 200},
                                       cache_available=True)
    assert cls["target_state"] == "live"
    assert cls["has_real_target"] is True


# --- ABSENT ---
def test_absent_when_no_ids_set():
    trade = _FakeTrade()
    cls = _classify_bracket_freshness(trade, live_ids={1, 2, 3},
                                       cache_available=True)
    assert cls["stop_state"] == "absent"
    assert cls["target_state"] == "absent"
    assert cls["has_real_stop"] is False
    assert cls["has_real_target"] is False


def test_partial_absent_stop_present_no_target():
    """Trade has a stop but no target at all — the v19.34.83
    refuse-to-stack rule will catch this in the endpoint; classifier
    just reports the labels."""
    trade = _FakeTrade(stop_oid=100)
    cls = _classify_bracket_freshness(trade, live_ids={100},
                                       cache_available=True)
    assert cls["stop_state"] == "live"
    assert cls["target_state"] == "absent"
    assert cls["has_real_stop"] is True
    assert cls["has_real_target"] is False


# --- Response shape ---
def test_response_shape_includes_audit_fields():
    """The classifier must return both the state labels AND the
    bot-tracked id values so the endpoint can include them in the
    audit response."""
    trade = _FakeTrade(stop_oid=4729, target_oids=[4730, 4731])
    cls = _classify_bracket_freshness(trade, live_ids={4730},
                                       cache_available=True)
    assert cls["stop_order_id"] == 4729
    assert sorted(cls["target_order_ids"]) == [4730, 4731]
    assert cls["target_state"] == "live"   # 4730 is live → overall live


# --- Garbage input safety ---
def test_garbage_string_id_treated_as_absent():
    trade = _FakeTrade(stop_oid="not-an-int-not-sim", target_oid=200)
    cls = _classify_bracket_freshness(trade, live_ids={200},
                                       cache_available=True)
    # Garbage non-SIM string → can't be cast → absent
    assert cls["stop_state"] == "absent"
    assert cls["has_real_stop"] is False


def test_empty_string_id_treated_as_absent():
    trade = _FakeTrade(stop_oid="", target_oid=200)
    cls = _classify_bracket_freshness(trade, live_ids={200},
                                       cache_available=True)
    assert cls["stop_state"] == "absent"
