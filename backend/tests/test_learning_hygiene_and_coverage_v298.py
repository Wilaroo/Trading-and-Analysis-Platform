"""
v19.34.298 — Audit Phase 6 (Track/Learn) fixes: learning-store hygiene + coverage.

L1 — the `trade_outcomes` store (AI confidence-gate calibration + tilt) must learn
     ONLY from GENUINE strategy closes (target / stop / trail / EOD / time-decay).
     Phantom / reconciled / operator-flatten / external-instant-unwind artifacts
     must be EXCLUDED so they can't calibrate the ML gate the unmanaged
     forward-test relies on.

L2 — the v162 fast-EOD path (`_eod_close_one_fast`) previously fed NEITHER outcome
     store, so EOD closes taught the bot nothing. The shared helper now records
     them (hygiene-gated), so EOD + time-decay closes still teach target/stop/decay.

OPERATOR REQUIREMENT (2026-06-08): time-decay AND EOD closes MUST keep feeding the
learning loop. These tests pin that explicitly (test_*_genuine_keeps_learning).

Exercised in isolation via `_is_genuine_close_for_learning` +
`_record_learning_outcome` (no DB / IB).
"""
import asyncio
import types

from services.position_manager import PositionManager


# ─────────────────────────── helpers / fakes ───────────────────────────

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _pm():
    return object.__new__(PositionManager)


class _Dir:
    def __init__(self, v):
        self.value = v


def _trade(*, reason_setup="orb", entered_by="scanner_auto", direction="long",
           fill=10.0, exit=10.5, stop=9.5, target=11.0, realized=50.0,
           net=49.0, shares=100):
    return types.SimpleNamespace(
        id="t1", alert_id="a1", symbol="ABC",
        setup_type=reason_setup, entered_by=entered_by,
        direction=_Dir(direction), trade_style="intraday",
        fill_price=fill, exit_price=exit, stop_price=stop, stop_loss=stop,
        target_prices=[target], target=target, tp_price=target,
        realized_pnl=realized, net_pnl=net, shares=shares,
        executed_at="2026-06-08T13:30:00+00:00",
        closed_at="2026-06-08T15:45:00+00:00",
        created_at="2026-06-08T13:30:00+00:00",
        confirmation_signals=[], entry_context={"catalyst_tag": "news", "gap_pct": 2.1},
    )


def _bot_with_loop():
    captured = []

    async def _rec(**kwargs):
        captured.append(kwargs)

    ll = types.SimpleNamespace(record_trade_outcome=_rec)
    bot = types.SimpleNamespace(_learning_loop=ll)
    return bot, captured


async def _drive(pm, bot, trade, reason):
    pm._record_learning_outcome(bot, trade, reason)
    await asyncio.sleep(0)  # let the create_task'd coroutine run


# ─────────────────────────── L1: genuineness gate ───────────────────────────

def test_target_and_stop_are_genuine():
    pm = _pm()
    assert pm._is_genuine_close_for_learning(_trade(), "target")[0] is True
    assert pm._is_genuine_close_for_learning(_trade(realized=-100, net=-101), "stop_loss")[0] is True


def test_time_decay_is_genuine():
    """OPERATOR REQUIREMENT: time-decay closes must keep teaching the bot."""
    pm = _pm()
    g, _ = pm._is_genuine_close_for_learning(_trade(reason_setup="scalp"), "scalp_time_decay")
    assert g is True


def test_eod_is_genuine():
    """OPERATOR REQUIREMENT: EOD closes must keep teaching the bot."""
    pm = _pm()
    for reason in ("eod_auto_close", "eod_auto_close_v162", "eod_window_1545"):
        g, _ = pm._is_genuine_close_for_learning(_trade(), reason)
        assert g is True, f"{reason} should be genuine"


def test_phantom_sweep_is_artifact():
    pm = _pm()
    g, tag = pm._is_genuine_close_for_learning(
        _trade(), "wrong_direction_phantom_swept_v19_29")
    assert g is False and "artifact_reason" in tag


def test_reconciled_entry_is_artifact():
    pm = _pm()
    g, tag = pm._is_genuine_close_for_learning(
        _trade(entered_by="reconciled_excess_v19_34_15b"), "stop_loss")
    assert g is False and "non_bot_entry" in tag


def test_reconciled_setup_is_artifact():
    pm = _pm()
    g, tag = pm._is_genuine_close_for_learning(
        _trade(reason_setup="reconciled_orphan"), "stop_loss")
    assert g is False and "artifact_setup" in tag


def test_operator_flatten_is_artifact():
    pm = _pm()
    g, tag = pm._is_genuine_close_for_learning(_trade(), "operator_external_flatten")
    assert g is False


def test_hygiene_kill_switch_disables_filter(monkeypatch):
    monkeypatch.setenv("LEARNING_HYGIENE_FILTER", "false")
    pm = _pm()
    # An artifact reason passes when the filter is disabled (legacy behavior).
    g, tag = pm._is_genuine_close_for_learning(
        _trade(), "wrong_direction_phantom_swept_v19_29")
    assert g is True and tag == "hygiene_disabled"


# ─────────────────────────── L1+L2: recording behaviour ───────────────────────────

def test_genuine_close_records_to_learning():
    pm = _pm()
    bot, captured = _bot_with_loop()
    _run(_drive(pm, bot, _trade(), "target"))
    assert len(captured) == 1
    assert captured[0]["outcome"] == "won"
    assert captured[0]["symbol"] == "ABC"
    assert captured[0]["catalyst_tag"] == "news"


def test_time_decay_close_records_to_learning():
    """OPERATOR REQUIREMENT pinned end-to-end."""
    pm = _pm()
    bot, captured = _bot_with_loop()
    _run(_drive(pm, bot, _trade(reason_setup="scalp"), "scalp_time_decay"))
    assert len(captured) == 1


def test_eod_close_records_to_learning():
    """OPERATOR REQUIREMENT pinned end-to-end (covers v162 EOD path reason)."""
    pm = _pm()
    bot, captured = _bot_with_loop()
    _run(_drive(pm, bot, _trade(), "eod_auto_close_v162"))
    assert len(captured) == 1


def test_artifact_close_does_not_record():
    pm = _pm()
    bot, captured = _bot_with_loop()
    _run(_drive(pm, bot, _trade(), "wrong_direction_phantom_swept_v19_29"))
    assert captured == []


def test_no_learning_loop_is_noop():
    pm = _pm()
    bot = types.SimpleNamespace(_learning_loop=None)
    # Should not raise.
    _run(_drive(pm, bot, _trade(), "target"))


def test_breakeven_outcome_label():
    pm = _pm()
    bot, captured = _bot_with_loop()
    _run(_drive(pm, bot, _trade(realized=0.0, net=0.0), "eod_auto_close"))
    assert len(captured) == 1
    assert captured[0]["outcome"] == "breakeven"
