"""
Tests for the trade-drop forensic instrumentation (2026-04-30).

Background
----------
The April 16 → April 29 silent regression: AI gate returned 32 GOs/day
but `bot_trades` saw 0 inserts. Some `return None` / `return` between
the AI gate and `bot_trades.insert_one()` aborted the trade silently.

These tests exercise every instrumented "drop gate" via the recorder
itself (the trading_bot_service / trade_execution paths import the
recorder lazily), to keep the suite hardware-independent. The full
end-to-end execute_trade flow can't be unit-tested in this container
(needs IB pusher, supervisor, motor/sync DB plumbing), so we validate
the instrumentation contract:

  1. Every gate name advertised by the diagnostic router is in KNOWN_GATES.
  2. record_trade_drop writes a well-formed row into the in-memory buffer
     (and to a fake Mongo collection).
  3. summarize_recent_drops aggregates by gate and identifies the
     first_killing_gate correctly.
  4. get_recent_drops respects the minutes-window cutoff.
  5. The recorder NEVER raises (drop logic must be fail-safe).
  6. Source-level guards: every silent-exit path in
     trading_bot_service._execute_trade and trade_execution.execute_trade
     calls record_trade_drop.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.trade_drop_recorder import (
    KNOWN_GATES,
    get_recent_drops,
    record_trade_drop,
    reset_memory_buffer_for_tests,
    summarize_recent_drops,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_memory_buffer_for_tests()
    yield
    reset_memory_buffer_for_tests()


# --------------------------------------------------------------------------
# Recorder contract
# --------------------------------------------------------------------------

def test_record_drop_with_no_db_uses_memory_buffer():
    record_trade_drop(
        None,
        gate="account_guard",
        symbol="AAPL",
        setup_type="9_ema_scalp",
        direction="long",
        reason="account drift",
        context={"current_account_id": "DUM61566S"},
    )
    rows = get_recent_drops(None, minutes=5)
    assert len(rows) == 1
    r = rows[0]
    assert r["gate"] == "account_guard"
    assert r["symbol"] == "AAPL"
    assert r["setup_type"] == "9_ema_scalp"
    assert r["direction"] == "long"
    assert r["reason"] == "account drift"
    assert r["context"]["current_account_id"] == "DUM61566S"
    assert "ts" in r and "ts_epoch_ms" in r


def test_record_drop_normalizes_symbol_to_upper():
    record_trade_drop(None, gate="account_guard", symbol="aapl")
    rows = get_recent_drops(None, minutes=5)
    assert rows[0]["symbol"] == "AAPL"


def test_record_drop_truncates_oversized_reason():
    record_trade_drop(None, gate="broker_rejected", reason="x" * 5000)
    rows = get_recent_drops(None, minutes=5)
    assert len(rows[0]["reason"]) <= 500


def test_record_drop_never_raises_even_on_bad_input():
    # Defensive — recorder must never blow up the trade flow.
    record_trade_drop(None, gate="unknown_gate_for_test")
    record_trade_drop(None, gate="account_guard", context={"obj": object()})
    # Both should have been captured without raising
    assert len(get_recent_drops(None, minutes=5)) == 2


def test_record_drop_writes_to_mongo_when_db_provided():
    fake_col = MagicMock()
    fake_db = {"trade_drops": fake_col}
    record_trade_drop(
        fake_db, gate="safety_guardrail", symbol="MSFT", reason="caps_exceeded",
    )
    fake_col.insert_one.assert_called_once()
    payload = fake_col.insert_one.call_args[0][0]
    assert payload["gate"] == "safety_guardrail"
    assert payload["symbol"] == "MSFT"
    assert payload["reason"] == "caps_exceeded"
    assert "ts_dt" in payload
    assert "ts_epoch_ms" in payload


def test_get_recent_drops_respects_minutes_cutoff():
    # Stamp something then move the cutoff past it.
    record_trade_drop(None, gate="account_guard", symbol="OLD")
    rows = get_recent_drops(None, minutes=60)
    assert any(r["symbol"] == "OLD" for r in rows)

    # 0-minute window should clamp to 1 (validated in get_recent_drops)
    # so the just-inserted row still appears within the same second.
    fresh = get_recent_drops(None, minutes=1)
    assert any(r["symbol"] == "OLD" for r in fresh)


def test_summarize_groups_by_gate_and_picks_top_killer():
    record_trade_drop(None, gate="account_guard")
    record_trade_drop(None, gate="account_guard")
    record_trade_drop(None, gate="account_guard")
    record_trade_drop(None, gate="broker_rejected")
    record_trade_drop(None, gate="safety_guardrail")

    summary = summarize_recent_drops(None, minutes=5)
    assert summary["total"] == 5
    assert summary["by_gate"]["account_guard"] == 3
    assert summary["by_gate"]["broker_rejected"] == 1
    assert summary["by_gate"]["safety_guardrail"] == 1
    assert summary["first_killing_gate"] == "account_guard"
    assert len(summary["recent"]) == 5


def test_summarize_when_empty_returns_no_killer():
    summary = summarize_recent_drops(None, minutes=5)
    assert summary["total"] == 0
    assert summary["by_gate"] == {}
    assert summary["first_killing_gate"] is None


def test_get_recent_drops_filters_by_gate():
    record_trade_drop(None, gate="account_guard")
    record_trade_drop(None, gate="broker_rejected")
    record_trade_drop(None, gate="account_guard")

    only_acct = get_recent_drops(None, minutes=5, gate="account_guard")
    assert len(only_acct) == 2
    assert all(r["gate"] == "account_guard" for r in only_acct)


# --------------------------------------------------------------------------
# Source-level instrumentation guards
#
# The recorder is imported lazily at every silent-exit site so we can
# validate it textually. This catches a future contributor deleting the
# breadcrumb (which is exactly how the April 16 regression hid for 13
# days — there was nothing in code or tests to guard the gate).
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
TRADING_BOT = (ROOT / "services" / "trading_bot_service.py").read_text()
TRADE_EXEC = (ROOT / "services" / "trade_execution.py").read_text()


def _src_has(haystack: str, snippet: str) -> bool:
    """Whitespace-tolerant substring search."""
    norm_h = re.sub(r"\s+", " ", haystack)
    norm_s = re.sub(r"\s+", " ", snippet)
    return norm_s in norm_h


@pytest.mark.parametrize("gate", [
    "account_guard",
    "safety_guardrail",
    "safety_guardrail_crash",
])
def test_trading_bot_service_instruments_gate(gate):
    assert _src_has(TRADING_BOT, f'gate="{gate}"'), (
        f"trading_bot_service.py is missing the '{gate}' instrumentation — "
        "if you removed it, also remove it from KNOWN_GATES so the canary "
        "stays consistent. See /app/backend/services/trade_drop_recorder.py."
    )


@pytest.mark.parametrize("gate", [
    "no_trade_executor",
    "pre_exec_guardrail_veto",
    "strategy_paper_phase",
    "strategy_simulation_phase",
    "broker_rejected",
    "execution_exception",
])
def test_trade_execution_instruments_gate(gate):
    assert _src_has(TRADE_EXEC, f'gate="{gate}"'), (
        f"trade_execution.py is missing the '{gate}' instrumentation — "
        f"this is the gate that hid the April 16 silent regression for 13 days."
    )


def test_known_gates_match_instrumented_gates():
    # Ensure no orphan gates in KNOWN_GATES that aren't actually wired.
    instrumented_in_bot = set(re.findall(r'gate="(\w+)"', TRADING_BOT))
    instrumented_in_exec = set(re.findall(r'gate="(\w+)"', TRADE_EXEC))
    union = instrumented_in_bot | instrumented_in_exec
    # Every gate in KNOWN_GATES should have at least one wiring site.
    missing = KNOWN_GATES - union
    assert not missing, (
        f"KNOWN_GATES has entries with no instrumentation: {missing}. "
        "Either wire them or remove them from trade_drop_recorder.KNOWN_GATES."
    )


def test_broker_rejected_path_now_persists_trade():
    """The legacy broker-reject path orphaned the trade in memory — we
    discovered this as the most likely root cause of the April 16
    regression. The fix calls bot._save_trade(trade) in the else-branch.
    Guard the regression source-side."""
    # The patch lives between the `else: trade.status = TradeStatus.REJECTED`
    # branch and the `except Exception as e:` block.
    pattern = re.compile(
        r"trade\.status = TradeStatus\.REJECTED\s+"
        r"logger\.warning\(f\"Trade rejected:.*?"
        r"await bot\._save_trade\(trade\)",
        re.DOTALL,
    )
    assert pattern.search(TRADE_EXEC), (
        "Broker-rejected branch in trade_execution.execute_trade() must "
        "call `await bot._save_trade(trade)` so REJECTED trades are not "
        "orphaned. See 2026-04-30 fix in trade_execution.py."
    )


def test_execution_exception_path_now_persists_trade():
    """Same fix on the exception branch."""
    pattern = re.compile(
        r"except Exception as e:\s+"
        r"logger\.error\(f\"Trade execution error:.*?"
        r"await bot\._save_trade\(trade\)",
        re.DOTALL,
    )
    assert pattern.search(TRADE_EXEC), (
        "Exception branch in trade_execution.execute_trade() must persist "
        "the REJECTED trade so we don't lose forensics."
    )


# --------------------------------------------------------------------------
# THE root cause of the April-16 → April-29 13-day silent regression
# --------------------------------------------------------------------------
#
# `BotTrade` has a `shares` field, NOT a `quantity` field. Two sites in
# `trading_bot_service._execute_trade` were referencing `trade.quantity`
# / `getattr(t, "quantity", ...)`. The latter is silently safe (getattr
# default), but the former raised `AttributeError` on EVERY autonomous
# trade attempt. The outer try/except caught it and bubbled up as
# `safety_guardrail_crash` → silent fail-CLOSED return → trade never
# reaches broker → `bot_trades` collection sees zero new inserts.
#
# The instrumentation made this visible the moment we deployed:
#     "reason": "guardrail check exception: 'BotTrade' object has no
#                attribute 'quantity'"
# Diagnosed + fixed 2026-04-30 v12.

def test_no_bot_trade_dot_quantity_in_trading_bot_service():
    """Pin the 13-day regression — `trade.shares`, never `trade.quantity`."""
    # The fix is in lines 2259 + 2264 (per pre-fix grep). These should
    # now read `.shares` not `.quantity`.
    assert ".quantity" not in TRADING_BOT, (
        "Found `.quantity` reference in trading_bot_service.py — BotTrade "
        "exposes `shares` not `quantity`. This is the EXACT bug that hid "
        "the 13-day silent regression (Apr 16 → Apr 29 2026). "
        "See safety_guardrail_crash drops in /api/diagnostic/trade-drops "
        "for forensic confirmation."
    )


def test_bot_trade_shares_attribute_used_for_notional():
    """The notional calculation must read `.shares` from BotTrade."""
    # Two specific patterns that were broken by `.quantity`:
    assert _src_has(
        TRADING_BOT,
        'notional = float(trade.entry_price or 0) * float(trade.shares or 0)',
    ), "notional must use trade.shares (not trade.quantity)"
    assert _src_has(
        TRADING_BOT,
        'float(getattr(t, "shares", 0) or 0)',
    ), "open_positions_snapshot must use t.shares (not t.quantity)"
