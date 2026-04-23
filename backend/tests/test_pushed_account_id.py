"""
Regression test for the `current_account_id: null` bug in /api/safety/status.

The safety router used to read `ib.get_status().get("account_id")` — but the
IBService connection-status payload never contained that field. The pusher
state keeps it under `_pushed_ib_data["account"][<key>]["account"]` (see
routers/ib.py:get_account_summary — the working path).

This test locks in that `get_pushed_account_id()` mirrors that extraction,
so the account_guard stops surfacing `null` whenever the pusher is live.
"""
from __future__ import annotations

import pytest

from routers import ib as ib_router


@pytest.fixture(autouse=True)
def _reset_pushed_data():
    snap = dict(ib_router._pushed_ib_data)
    ib_router._pushed_ib_data["account"] = {}
    yield
    ib_router._pushed_ib_data.clear()
    ib_router._pushed_ib_data.update(snap)


def test_returns_none_when_pushed_account_empty():
    ib_router._pushed_ib_data["account"] = {}
    assert ib_router.get_pushed_account_id() is None


def test_returns_none_when_account_is_not_dict():
    ib_router._pushed_ib_data["account"] = "broken"  # type: ignore[assignment]
    assert ib_router.get_pushed_account_id() is None


def test_extracts_first_nested_account_value():
    # Mirrors the real pusher shape: each AccountValue is keyed by tag+currency
    # and its body carries the `account` id as a field.
    ib_router._pushed_ib_data["account"] = {
        "NetLiquidation|USD": {"value": "100000", "currency": "USD", "account": "paperesw100000"},
        "BuyingPower|USD": {"value": "400000", "currency": "USD", "account": "paperesw100000"},
    }
    assert ib_router.get_pushed_account_id() == "paperesw100000"


def test_extracts_live_account_when_thats_what_pusher_reports():
    """The exact user-facing scenario: env expects paper but pusher has live."""
    ib_router._pushed_ib_data["account"] = {
        "NetLiquidation|USD": {"value": "250000", "currency": "USD", "account": "esw100000"},
    }
    assert ib_router.get_pushed_account_id() == "esw100000"


def test_skips_entries_without_account_field():
    ib_router._pushed_ib_data["account"] = {
        "Noise": {"value": "x"},
        "Real": {"value": "y", "account": "paperesw100000"},
    }
    assert ib_router.get_pushed_account_id() == "paperesw100000"


def test_account_id_feeds_through_to_summarize_for_ui(monkeypatch):
    """End-to-end wiring: pushed data → helper → account_guard.summarize_for_ui."""
    from services import account_guard

    monkeypatch.setenv("IB_ACCOUNT_LIVE", "esw100000")
    monkeypatch.setenv("IB_ACCOUNT_PAPER", "paperesw100000")
    monkeypatch.setenv("IB_ACCOUNT_ACTIVE", "paper")

    ib_router._pushed_ib_data["account"] = {
        "NetLiquidation|USD": {"value": "250000", "currency": "USD", "account": "esw100000"},
    }
    current = ib_router.get_pushed_account_id()
    payload = account_guard.summarize_for_ui(current)

    assert payload["current_account_id"] == "esw100000"
    assert payload["expected_account_id"] == "paperesw100000"
    assert payload["match"] is False
    assert "expected paperesw100000" in payload["reason"]
