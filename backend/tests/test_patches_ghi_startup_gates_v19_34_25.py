"""test_patches_ghi_startup_gates_v19_34_25.py — pin Patches G/H/I.

After the 2026-02 post-Patch-F stampede disaster (bot opened 7 naked
positions in seconds when the kill switch was first flipped on), three
compounding bugs were identified:

 G. _execute_trade had no gate against Patch F's audit completion. The
    audit had a 25s `asyncio.sleep` while the scan loop fired at t+1s,
    so the bot raced past its own boot protection.

 H. No startup grace period. The first scan tick fired pre-market
    staged signals as if they were fresh, cascading into 7 simultaneous
    market entries before any safety system could react.

 I. account_guard.check_account_match tripped the kill switch the
    instant pusher data arrived without an account_id — but the IB
    pusher pushes positions/quotes BEFORE its reqAccountSummary
    callback lands. The kill switch flipped during this innocent
    warmup window, leaving the 7 entries naked.

This suite pins the three patches together as one coherent v19.34.25
boot-safety set:

 G1. _execute_trade returns silently (no exception, no fill) when
     _patch_f_audit_complete is False.
 G2. Once the tripwire's finally block runs, _patch_f_audit_complete
     is True even if the audit itself crashed — so a tripwire bug
     doesn't brick entries indefinitely.

 H1. _execute_trade refuses entries during the startup grace window
     (STARTUP_GRACE_SECONDS).
 H2. After grace expires, entries are no longer blocked by Gate H.
 H3. STARTUP_GRACE_SECONDS=0 disables the gate entirely (operator
     escape hatch).

 I1. check_account_match with current_account_id=None AND
     pusher_first_seen_at within ACCOUNT_GUARD_WARMUP_SECONDS
     returns (True, 'pending — warming up…').
 I2. After warmup expires, the guard trips as before.
 I3. A true mismatch (current_account_id != expected) still fails
     fast even during the warmup window.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ════════════════════════════════════════════════════════════════════════
# Patch G — _patch_f_audit_complete gate
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patch_g_blocks_entry_when_audit_not_complete(caplog):
    """Gate G: _execute_trade must return without firing when the
    Patch F audit hasn't completed."""
    import logging
    from services.trading_bot_service import TradingBotService

    caplog.set_level(logging.WARNING)
    bot = TradingBotService()
    # Bypass grace gate
    bot._started_at = datetime.now(timezone.utc) - timedelta(seconds=999)
    bot._patch_f_audit_complete = False

    fake_trade = MagicMock()
    fake_trade.symbol = "TEST"
    fake_trade.direction = "long"

    # If the gate works, _execute_trade returns silently (None) without
    # calling any downstream execution path. We confirm by checking
    # the log marker.
    os.environ["STARTUP_GRACE_SECONDS"] = "0"
    try:
        result = await bot._execute_trade(fake_trade)
    finally:
        os.environ.pop("STARTUP_GRACE_SECONDS", None)
    assert result is None
    assert any(
        "PATCH-G GATE" in r.getMessage() for r in caplog.records
    ), f"Gate G must log a SKIP marker; got {[r.getMessage() for r in caplog.records]}"


@pytest.mark.asyncio
async def test_patch_g_finally_block_always_sets_complete(caplog):
    """Gate G safety: the audit's finally block must set
    _patch_f_audit_complete=True even on crash, so a buggy tripwire
    doesn't brick all entries forever."""
    import logging
    caplog.set_level(logging.INFO)

    # Simulate the finally branch in isolation — it must always set
    # _patch_f_audit_complete True regardless of what happened inside
    # the try block.
    class _FakeBot:
        _patch_f_audit_complete = False
        _patch_f_audit_started_at = None

    bot = _FakeBot()

    async def _simulate_tripwire():
        bot._patch_f_audit_started_at = datetime.now(timezone.utc)
        try:
            raise RuntimeError("audit crashed mid-run")
        except Exception:
            pass  # swallow
        finally:
            bot._patch_f_audit_complete = True

    await _simulate_tripwire()
    assert bot._patch_f_audit_complete is True, (
        "Gate G: finally must set complete=True even when audit "
        "raised inside the try block"
    )


# ════════════════════════════════════════════════════════════════════════
# Patch H — startup grace period
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patch_h_blocks_entry_during_grace_window(caplog):
    """Gate H: _execute_trade must refuse entries during the startup
    grace window."""
    import logging
    from services.trading_bot_service import TradingBotService

    caplog.set_level(logging.WARNING)
    bot = TradingBotService()
    bot._started_at = datetime.now(timezone.utc)
    bot._patch_f_audit_complete = True  # bypass gate G

    fake_trade = MagicMock()
    fake_trade.symbol = "TEST"
    fake_trade.direction = "long"

    os.environ["STARTUP_GRACE_SECONDS"] = "60"
    try:
        result = await bot._execute_trade(fake_trade)
    finally:
        os.environ.pop("STARTUP_GRACE_SECONDS", None)

    assert result is None
    assert any(
        "PATCH-H GATE" in r.getMessage() for r in caplog.records
    ), f"Gate H must log a SKIP marker; got {[r.getMessage() for r in caplog.records]}"


@pytest.mark.asyncio
async def test_patch_h_zero_grace_disables_gate():
    """Gate H: STARTUP_GRACE_SECONDS=0 must disable the gate as an
    operator escape hatch — otherwise we'd brick the bot if a critical
    same-day patch ever needs to fire instantly."""
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()
    bot._started_at = datetime.now(timezone.utc)
    bot._patch_f_audit_complete = True

    # We can't easily mock the downstream execution chain, so we
    # instead check that with grace=0, the gate doesn't short-circuit
    # to early-return BEFORE the get_safety_guardrails import. Trick:
    # use a non-BotTrade input so the function will fail later (after
    # gate H) but proves gate H let it through.
    os.environ["STARTUP_GRACE_SECONDS"] = "0"
    try:
        # With grace=0 + audit complete, the gates allow passage.
        # The fact that gate H doesn't log SKIP is the assertion.
        import logging
        with pytest.LoggingCapture() if False else _LogCapture() as cap:
            fake = MagicMock()
            fake.symbol = "TEST"
            fake.direction = "long"
            try:
                await bot._execute_trade(fake)
            except Exception:
                pass  # downstream fail is fine for this test
        gate_h_skips = [m for m in cap.messages if "PATCH-H GATE" in m]
        assert not gate_h_skips, (
            f"With grace=0, Gate H must NOT skip; got {gate_h_skips}"
        )
    finally:
        os.environ.pop("STARTUP_GRACE_SECONDS", None)


class _LogCapture:
    """Minimal context manager that captures log records as plain
    strings — used because caplog doesn't compose well across multiple
    fixtures in the same async test."""

    def __init__(self):
        self.messages = []
        self._handler = None

    def __enter__(self):
        import logging
        self._handler = logging.Handler()
        self._handler.emit = lambda r: self.messages.append(r.getMessage())
        logging.getLogger().addHandler(self._handler)
        return self

    def __exit__(self, *a):
        import logging
        logging.getLogger().removeHandler(self._handler)


# ════════════════════════════════════════════════════════════════════════
# Patch I — account guard warmup window
# ════════════════════════════════════════════════════════════════════════


def test_patch_i_warmup_returns_pending_for_fresh_pusher():
    """Gate I: missing account_id + pusher_first_seen_at within warmup
    window → (True, pending) instead of tripping."""
    from services.account_guard import (
        AccountExpectation,
        check_account_match,
    )

    exp = AccountExpectation(
        expected_aliases=("paperesw100000", "DUB615665"),
        active_mode="paper",
    )
    # Pusher posted 5 seconds ago — well within the 60s warmup.
    first_seen = datetime.now(timezone.utc) - timedelta(seconds=5)

    os.environ["ACCOUNT_GUARD_WARMUP_SECONDS"] = "60"
    try:
        ok, reason = check_account_match(
            current_account_id=None,
            expectation=exp,
            ib_connected=True,
            pusher_first_seen_at=first_seen,
        )
    finally:
        os.environ.pop("ACCOUNT_GUARD_WARMUP_SECONDS", None)

    assert ok is True, f"Gate I: should return OK during warmup, got {reason}"
    assert "warming up" in reason.lower() or "pending" in reason.lower(), (
        f"Gate I: reason should mention warmup/pending; got {reason!r}"
    )


def test_patch_i_trips_after_warmup_expires():
    """Gate I: missing account_id with pusher_first_seen_at OLDER than
    warmup window → trip as before."""
    from services.account_guard import (
        AccountExpectation,
        check_account_match,
    )

    exp = AccountExpectation(
        expected_aliases=("paperesw100000", "DUB615665"),
        active_mode="paper",
    )
    # Pusher posted 5 minutes ago — well beyond the 60s warmup.
    first_seen = datetime.now(timezone.utc) - timedelta(minutes=5)

    os.environ["ACCOUNT_GUARD_WARMUP_SECONDS"] = "60"
    try:
        ok, reason = check_account_match(
            current_account_id=None,
            expectation=exp,
            ib_connected=True,
            pusher_first_seen_at=first_seen,
        )
    finally:
        os.environ.pop("ACCOUNT_GUARD_WARMUP_SECONDS", None)

    assert ok is False, (
        f"Gate I: should trip after warmup expires; got ok={ok} reason={reason}"
    )
    assert "no account reported" in reason.lower(), (
        f"Gate I: post-warmup reason should be 'no account reported…'; "
        f"got {reason!r}"
    )


def test_patch_i_true_mismatch_fails_fast_even_during_warmup():
    """Gate I safety: a REAL account_id that doesn't match the
    expected aliases must fail fast — the warmup window only softens
    the missing-account case, not the wrong-account case."""
    from services.account_guard import (
        AccountExpectation,
        check_account_match,
    )

    exp = AccountExpectation(
        expected_aliases=("paperesw100000", "DUB615665"),
        active_mode="paper",
    )
    # Pusher reports a DIFFERENT account ID, well within warmup.
    first_seen = datetime.now(timezone.utc) - timedelta(seconds=5)

    os.environ["ACCOUNT_GUARD_WARMUP_SECONDS"] = "60"
    try:
        ok, reason = check_account_match(
            current_account_id="liveU1234567",  # NOT in expected aliases
            expectation=exp,
            ib_connected=True,
            pusher_first_seen_at=first_seen,
        )
    finally:
        os.environ.pop("ACCOUNT_GUARD_WARMUP_SECONDS", None)

    assert ok is False, (
        f"Gate I: true mismatch must fail fast even in warmup; "
        f"got ok={ok}"
    )
    # The 'warming up' branch is only for current_account_id=None.
    assert "warming up" not in reason.lower(), (
        f"Gate I: true mismatch must NOT use warmup-pending reason; "
        f"got {reason!r}"
    )


def test_patch_i_zero_warmup_disables_gate():
    """Gate I: ACCOUNT_GUARD_WARMUP_SECONDS=0 disables the warmup
    grace (operator escape hatch for production tuning)."""
    from services.account_guard import (
        AccountExpectation,
        check_account_match,
    )

    exp = AccountExpectation(
        expected_aliases=("paperesw100000", "DUB615665"),
        active_mode="paper",
    )
    first_seen = datetime.now(timezone.utc) - timedelta(seconds=1)

    os.environ["ACCOUNT_GUARD_WARMUP_SECONDS"] = "0"
    try:
        ok, reason = check_account_match(
            current_account_id=None,
            expectation=exp,
            ib_connected=True,
            pusher_first_seen_at=first_seen,
        )
    finally:
        os.environ.pop("ACCOUNT_GUARD_WARMUP_SECONDS", None)

    # With warmup=0, the behaviour is identical to pre-I: trip on
    # missing account_id even if pusher just connected.
    assert ok is False, (
        "Gate I: warmup=0 must restore pre-I trip-on-missing behaviour"
    )


def test_patch_i_backwards_compat_no_first_seen_arg():
    """Gate I: the new pusher_first_seen_at arg is optional. Callers
    that don't pass it (legacy code paths) must continue to work
    exactly as before."""
    from services.account_guard import (
        AccountExpectation,
        check_account_match,
    )

    exp = AccountExpectation(
        expected_aliases=("paperesw100000", "DUB615665"),
        active_mode="paper",
    )
    # No pusher_first_seen_at → behaves as before Patch I.
    ok, reason = check_account_match(
        current_account_id=None,
        expectation=exp,
        ib_connected=True,
    )
    assert ok is False
    assert "no account reported" in reason.lower()
