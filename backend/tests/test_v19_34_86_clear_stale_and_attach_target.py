"""
v19.34.86 — clear-stale-bracket-ids + attach-target-only endpoints
==================================================================

Two complementary operator endpoints that together close the gap
the v83 `stop_present_no_target_refusing_to_stack` skip exposes.

clear-stale-bracket-ids
-----------------------
After manually cancelling an oversized OCA in TWS (the 2026-05-12
PEP scenario), the bot's stop_order_id / target_order_id still
point at the now-dead orders. Any reader thinks the trade is
"already bracketed" and refuses to re-arm. This endpoint nulls
the stale pointers. Never touches IB.

attach-target-only
------------------
For trades that have a real live stop but no target id, submits ONE
LMT target leg via queue_order, sharing the existing trade's OCA
group when present. Replaces the "cancel + re-attach full OCA"
workaround that briefly leaves the position naked.

Test coverage
-------------
clear-stale-bracket-ids:
  1. Dry-run reports plan, doesn't mutate.
  2. Apply nulls stop/target/oca, persists, writes audit.
  3. Trade with nothing to clear → action=skipped_no_change.
  4. Partial clear (clear_stop only) keeps target intact and keeps oca_group.
  5. clear_stop=False AND clear_target=False → 400.
  6. Unknown symbol → success with empty plan + helpful message.

attach-target-only:
  1. Dry-run returns preview, doesn't queue.
  2. Apply queues a LMT leg, updates bot trade state, persists.
  3. Refuses when no stop_present_no_target candidate exists.
  4. Computes target_price from target_pct when no override given.
  5. Resolves trade_id explicitly when provided.
  6. Pusher offline → success=False, no queue_order call.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/app/backend")


def _mk_trade(tid, symbol, shares, *, stop_order_id=None, target_order_id=None,
              target_order_ids=None, oca_group=None, direction="long",
              entry_price=100.0):
    return SimpleNamespace(
        id=tid, symbol=symbol, shares=shares, remaining_shares=shares,
        entry_price=entry_price, fill_price=entry_price,
        stop_price=None, target_prices=None,
        direction=SimpleNamespace(value=direction),
        stop_order_id=stop_order_id,
        target_order_id=target_order_id,
        target_order_ids=list(target_order_ids or []),
        oca_group=oca_group,
        notes="",
    )


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot, orig_exec = tb._trading_bot, tb._trade_executor
    save_mock = MagicMock(return_value=None)
    drift_coll = MagicMock()
    bot = SimpleNamespace(
        _open_trades=OrderedDict(),
        _save_trade=save_mock,
        _db={"share_drift_events": drift_coll},
    )
    executor = SimpleNamespace()
    tb._trading_bot = bot
    tb._trade_executor = executor
    yield bot, executor, tb, save_mock, drift_coll
    tb._trading_bot, tb._trade_executor = orig_bot, orig_exec


# ── clear-stale-bracket-ids ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_dry_run_reports_plan_no_mutation(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="a591c2f4", target_order_id="44e085c4",
            oca_group="ADOPT-OCA-PEP-x",
        )),
    ])
    resp = await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
        symbol="PEP", clear_stop=True, clear_target=True, dry_run=True,
        reason="post-TWS-cancel-of-oversized-OCA",
    ))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert resp["plan"][0]["action"] == "will_clear"
    # No mutation.
    assert bot._open_trades["t-pep"].stop_order_id == "a591c2f4"
    assert bot._open_trades["t-pep"].target_order_id == "44e085c4"
    save_mock.assert_not_called()
    drift.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_clear_apply_nulls_ids_and_audits(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="a591c2f4", target_order_id="44e085c4",
            target_order_ids=["44e085c4"],
            oca_group="ADOPT-OCA-PEP-x",
        )),
    ])
    resp = await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
        symbol="PEP", clear_stop=True, clear_target=True, dry_run=False,
        reason="post-TWS-cancel",
    ))
    assert resp["success"] is True
    assert len(resp["cleared"]) == 1
    t = bot._open_trades["t-pep"]
    assert t.stop_order_id is None
    assert t.target_order_id is None
    assert t.target_order_ids == []
    assert t.oca_group is None  # both legs cleared → oca nulled too
    save_mock.assert_called_once()
    drift.insert_one.assert_called_once()
    audit = drift.insert_one.call_args[0][0]
    assert audit["event"] == "clear_stale_bracket_ids_v19_34_86"
    assert audit["symbol"] == "PEP"
    assert audit["cleared_stop"] is True
    assert audit["cleared_target"] is True


@pytest.mark.asyncio
async def test_clear_partial_keeps_target_and_oca(patched_app):
    """clear_stop=True, clear_target=False → stop nulls, target stays,
    oca_group stays (the surviving target leg's OCA membership matters)."""
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="STALE-STP", target_order_id="LIVE-TGT",
            oca_group="OCA-X",
        )),
    ])
    resp = await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
        symbol="PEP", clear_stop=True, clear_target=False, dry_run=False,
    ))
    assert resp["success"] is True
    t = bot._open_trades["t-pep"]
    assert t.stop_order_id is None
    assert t.target_order_id == "LIVE-TGT"
    assert t.oca_group == "OCA-X"   # NOT cleared


@pytest.mark.asyncio
async def test_clear_nothing_to_change_lands_in_skipped(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id=None, target_order_id=None,
        )),
    ])
    resp = await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
        symbol="PEP", clear_stop=True, clear_target=True, dry_run=False,
    ))
    assert resp["success"] is True
    assert resp["cleared"] == []
    assert resp["skipped"][0]["action"] == "skipped_no_change"


@pytest.mark.asyncio
async def test_clear_both_flags_false_is_400(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade("t-pep", "PEP", 971, stop_order_id="x")),
    ])
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
            symbol="PEP", clear_stop=False, clear_target=False, dry_run=False,
        ))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_clear_unknown_symbol_returns_empty_plan(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict()
    resp = await tb.clear_stale_bracket_ids(tb.ClearStaleBracketIdsRequest(
        symbol="ZZZ", clear_stop=True, clear_target=True, dry_run=False,
    ))
    assert resp["success"] is True
    assert "No open trades for ZZZ" in resp["message"]


# ── attach-target-only ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_attach_target_dry_run_returns_preview(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="LIVE-STP", oca_group="OCA-A", entry_price=149.42,
        )),
    ])
    resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
        symbol="PEP", target_price=137.47, dry_run=True,
    ))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    p = resp["preview"]
    assert p["symbol"] == "PEP"
    assert p["action"] == "BUY"   # short cover
    assert p["qty"] == 971
    assert p["target_price"] == 137.47
    assert p["oca_group"] == "OCA-A"
    # No order placed.
    assert bot._open_trades["t-pep"].target_order_id is None


@pytest.mark.asyncio
async def test_attach_target_apply_queues_and_updates_trade(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="LIVE-STP", oca_group="OCA-A", entry_price=149.42,
        )),
    ])
    with patch("routers.ib.queue_order", return_value="QUEUED-LMT-001") as qo, \
         patch("routers.ib.is_pusher_connected", return_value=True):
        resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
            symbol="PEP", target_price=137.47, dry_run=False,
            reason="post-cleanup re-arm missing target",
        ))
    assert resp["success"] is True
    assert resp["dry_run"] is False
    submitted = resp["submitted"]
    assert submitted["target_order_id"] == "QUEUED-LMT-001"
    # queue_order was called with the right shape.
    qo.assert_called_once()
    arg = qo.call_args[0][0]
    assert arg["symbol"] == "PEP"
    assert arg["action"] == "BUY"
    assert arg["quantity"] == 971
    assert arg["order_type"] == "LMT"
    assert arg["limit_price"] == 137.47
    assert arg["stop_price"] is None
    assert arg["oca_group"] == "OCA-A"
    # In-memory state updated.
    t = bot._open_trades["t-pep"]
    assert t.target_order_id == "QUEUED-LMT-001"
    assert "QUEUED-LMT-001" in t.target_order_ids
    assert "v19.34.86 attach-target-only" in t.notes
    save_mock.assert_called_once()


@pytest.mark.asyncio
async def test_attach_target_uses_pct_when_no_explicit_target(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="LIVE-STP", entry_price=149.42,
        )),
    ])
    resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
        symbol="PEP", target_pct=8.0, dry_run=True,
    ))
    assert resp["success"] is True
    # Short: entry * (1 - 8/100) = 149.42 * 0.92 = 137.4664 → rounded 137.47
    assert resp["preview"]["target_price"] == 137.47


@pytest.mark.asyncio
async def test_attach_target_explicit_trade_id_overrides_symbol_resolution(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 500, stop_order_id="STP-1")),
        ("t-pep-2", _mk_trade("t-pep-2", "PEP", 471, stop_order_id="STP-2")),
    ])
    resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
        trade_id="t-pep-2", target_price=137.47, dry_run=True,
    ))
    assert resp["success"] is True
    assert resp["preview"]["trade_id"] == "t-pep-2"
    assert resp["preview"]["qty"] == 471


@pytest.mark.asyncio
async def test_attach_target_no_matching_trade_returns_error(patched_app):
    """When no trade has the stop_present_no_target signature, refuse
    and direct the operator to attach-brackets-to-unprotected."""
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971,
            stop_order_id="LIVE-STP", target_order_id="ALREADY-HAS-TGT",
        )),
    ])
    resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
        symbol="PEP", target_price=137.47, dry_run=False,
    ))
    assert resp["success"] is False
    assert "attach-brackets-to-unprotected" in resp["error"]


@pytest.mark.asyncio
async def test_attach_target_pusher_offline_refuses(patched_app):
    bot, executor, tb, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep", _mk_trade(
            "t-pep", "PEP", 971, direction="short",
            stop_order_id="LIVE-STP", entry_price=149.42,
        )),
    ])
    with patch("routers.ib.queue_order") as qo, \
         patch("routers.ib.is_pusher_connected", return_value=False):
        resp = await tb.attach_target_only(tb.AttachTargetOnlyRequest(
            symbol="PEP", target_price=137.47, dry_run=False,
        ))
    assert resp["success"] is False
    assert "pusher_offline" in resp["error"]
    qo.assert_not_called()
