"""
v19.34.72 — Operator-flatten suppression regression
====================================================

Background
----------
When the position reconciler's two-tick gate (v19.34.71) confirms an
IB position has dropped to zero on a symbol the bot was tracking, the
close was NOT bot-initiated (the bot would have already moved the
trade out of `_open_trades` if it had). By construction this is either
an operator manual flatten in TWS or some external action.

Continuing to evaluate the SAME setup moments later actively fights
the operator's signal. v19.34.72 adds a per-session suppression set
that blocks re-entries on the symbol until UTC midnight or operator
intervention.

Assertions
----------
1. `OperatorFlattenSuppression.add(sym)` adds the symbol; `is_suppressed`
   reflects it; `get_entry` returns the full record.
2. Symbol lookups are case-insensitive.
3. `list_all()` returns a snapshot of every suppressed symbol.
4. `clear(symbol=...)` removes a single symbol and returns 1; missing
   symbol returns 0.
5. `clear(symbol=None)` removes everything and returns the count.
6. UTC day rollover auto-clears the set (no entries leak from previous
   day's session).
7. Singleton accessor `get_operator_flatten_suppression()` returns the
   same instance across calls.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, "/app/backend")


def _fresh_supp():
    from services.operator_flatten_suppression import OperatorFlattenSuppression
    return OperatorFlattenSuppression()


def test_add_and_is_suppressed():
    s = _fresh_supp()
    assert s.is_suppressed("NBIS") is False
    s.add("NBIS", reason="operator_external_flatten", trade_ids=["t-1", "t-2"])
    assert s.is_suppressed("NBIS") is True
    entry = s.get_entry("NBIS")
    assert entry["reason"] == "operator_external_flatten"
    assert entry["trade_ids"] == ["t-1", "t-2"]
    assert "added_at" in entry


def test_symbol_lookup_case_insensitive():
    s = _fresh_supp()
    s.add("nbis")
    assert s.is_suppressed("NBIS") is True
    assert s.is_suppressed("Nbis") is True
    assert s.get_entry("NBIS") is not None


def test_list_all_returns_snapshot():
    s = _fresh_supp()
    s.add("NBIS")
    s.add("AAPL")
    s.add("TSLA")
    snapshot = s.list_all()
    assert set(snapshot.keys()) == {"NBIS", "AAPL", "TSLA"}
    # Mutating the snapshot must not affect the live set.
    snapshot["NBIS"]["reason"] = "tampered"
    assert s.get_entry("NBIS")["reason"] != "tampered"


def test_clear_single_symbol():
    s = _fresh_supp()
    s.add("NBIS")
    s.add("AAPL")
    removed = s.clear(symbol="NBIS")
    assert removed == 1
    assert s.is_suppressed("NBIS") is False
    assert s.is_suppressed("AAPL") is True


def test_clear_missing_symbol_returns_zero():
    s = _fresh_supp()
    s.add("NBIS")
    removed = s.clear(symbol="DOES_NOT_EXIST")
    assert removed == 0
    assert s.is_suppressed("NBIS") is True


def test_clear_all_when_symbol_none():
    s = _fresh_supp()
    s.add("NBIS")
    s.add("AAPL")
    s.add("TSLA")
    removed = s.clear(symbol=None)
    assert removed == 3
    assert s.list_all() == {}


def test_utc_day_rollover_auto_clears():
    """Suppression is per-UTC-day. A new UTC date clears everything."""
    s = _fresh_supp()
    # Pin "today" via patching datetime.now inside the module.
    fixed_day_1 = datetime(2026, 5, 11, 23, 59, 0, tzinfo=timezone.utc)
    fixed_day_2 = fixed_day_1 + timedelta(days=1)

    with patch("services.operator_flatten_suppression.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_day_1
        # Allow other datetime usages to fall through.
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        s.add("NBIS")
        assert s.is_suppressed("NBIS") is True

        # Advance one day.
        mock_dt.now.return_value = fixed_day_2
        assert s.is_suppressed("NBIS") is False
        assert s.list_all() == {}


def test_singleton_returns_same_instance():
    from services.operator_flatten_suppression import (
        get_operator_flatten_suppression,
    )
    a = get_operator_flatten_suppression()
    b = get_operator_flatten_suppression()
    assert a is b


def test_empty_symbol_is_noop():
    s = _fresh_supp()
    s.add("")
    s.add(None)  # type: ignore
    assert s.list_all() == {}
    assert s.is_suppressed("") is False
    assert s.is_suppressed(None) is False  # type: ignore
