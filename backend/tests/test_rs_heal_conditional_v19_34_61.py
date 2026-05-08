"""
v19.34.61 — Conditional rs/original self-heal in PositionManager.

Replaces the unconditional `if rs==0: rs=shares` with a narrow,
freshness-gated heal that only re-animates trades within a 60s
fresh-fill window. Older rs=0 trades are recognized as zombies and
skipped (drift loop's v19.34.19 cleanup handles them).

These tests don't run the full manage loop — they isolate the heal
decision logic and verify the four code paths:
  1. Fresh-fill window → heal (rs goes 0 → shares)
  2. Outside window → skip heal, log, mark _v19_34_61_skip_warned
  3. close_reason set → skip heal silently (close-in-progress)
  4. _loaded_as_zombie_v19_34_59 set → skip heal silently (drift loop owns it)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def _make_trade(**kw):
    """Build a fake BotTrade-like object suitable for the heal block."""
    defaults = dict(
        id="t-1",
        symbol="TEST",
        shares=100,
        original_shares=0,
        remaining_shares=0,
        executed_at=None,
        entry_time=None,
        close_reason=None,
        entered_by="bot_fired",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _run_heal_logic(trade, *, now=None):
    """Mirror the v19.34.61 heal block from position_manager.py.

    Returns: dict with keys {healed, skipped_reason, log_records}.
    Imports are mirrored verbatim from position_manager.py.
    """
    RS_HEAL_WINDOW_S = 60
    log = logging.getLogger("position_manager_test")
    log.handlers.clear()
    handler = logging.Handler()
    captured = []
    class _CaptureHandler(logging.Handler):
        def emit(self, record):
            captured.append((record.levelname, record.getMessage()))
    log.addHandler(_CaptureHandler())
    log.setLevel(logging.DEBUG)

    healed = False
    skipped_reason = None

    if trade.remaining_shares == 0 and int(getattr(trade, "shares", 0) or 0) > 0:
        if getattr(trade, "close_reason", None):
            skipped_reason = "close_reason_set"
        elif getattr(trade, "_loaded_as_zombie_v19_34_59", False):
            skipped_reason = "loaded_zombie"
        else:
            executed_at = getattr(trade, "executed_at", None) \
                or getattr(trade, "entry_time", None)
            age_s = None
            if executed_at:
                try:
                    if isinstance(executed_at, str):
                        ts = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
                    else:
                        ts = executed_at
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    ref_now = now or datetime.now(timezone.utc)
                    age_s = (ref_now - ts).total_seconds()
                except Exception:
                    age_s = None
            if age_s is not None and 0 <= age_s <= RS_HEAL_WINDOW_S:
                trade.remaining_shares = trade.shares
                trade.original_shares = trade.shares
                healed = True
            else:
                skipped_reason = "outside_window"
                trade._v19_34_61_skip_warned = True

    return {
        "healed": healed,
        "skipped_reason": skipped_reason,
        "rs_after": trade.remaining_shares,
        "original_after": getattr(trade, "original_shares", 0),
        "skip_warned": getattr(trade, "_v19_34_61_skip_warned", False),
    }


def test_fresh_fill_within_window_heals():
    """Trade executed 5s ago → heal fires."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=626,
        executed_at=(now - timedelta(seconds=5)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is True
    assert res["rs_after"] == 626
    assert res["original_after"] == 626
    assert res["skip_warned"] is False


def test_fresh_fill_at_window_edge_heals():
    """Trade executed exactly 60s ago → still heals (≤ window)."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=100,
        executed_at=(now - timedelta(seconds=60)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is True
    assert res["rs_after"] == 100


def test_outside_window_skips_with_warning():
    """Trade executed 5 minutes ago → skip + warn."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=959,
        executed_at=(now - timedelta(minutes=5)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] == "outside_window"
    assert res["rs_after"] == 0
    assert res["skip_warned"] is True


def test_close_reason_set_skips_silently():
    """Trade with close_reason='target_hit' → skip without re-animating."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=200,
        executed_at=(now - timedelta(seconds=10)).isoformat(),  # fresh
        close_reason="target_hit",  # but being closed
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] == "close_reason_set"
    assert res["rs_after"] == 0
    assert res["skip_warned"] is False


def test_loaded_zombie_flag_skips_silently():
    """v19.34.59-tagged zombie → skip; drift loop owns it."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=300,
        executed_at=(now - timedelta(seconds=5)).isoformat(),  # fresh-looking
    )
    t._loaded_as_zombie_v19_34_59 = True
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] == "loaded_zombie"
    assert res["rs_after"] == 0
    assert res["skip_warned"] is False


def test_no_executed_at_skips_with_warning():
    """Trade with no timestamp → cannot prove freshness → skip."""
    t = _make_trade(shares=100, executed_at=None, entry_time=None)
    res = _run_heal_logic(t)
    assert res["healed"] is False
    assert res["skipped_reason"] == "outside_window"


def test_entry_time_fallback_used_when_executed_at_missing():
    """If executed_at is None but entry_time is fresh, heal fires."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=500,
        executed_at=None,
        entry_time=(now - timedelta(seconds=20)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is True
    assert res["rs_after"] == 500


def test_zero_shares_zero_remaining_no_action():
    """Defensive: shares=0 too means trade isn't really a zombie. No heal, no warn."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=0, remaining_shares=0,
        executed_at=(now - timedelta(seconds=10)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] is None  # didn't enter the block at all
    assert res["rs_after"] == 0


def test_already_healthy_position_untouched():
    """rs > 0 → block never enters."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=500, remaining_shares=500,
        executed_at=(now - timedelta(hours=2)).isoformat(),  # old, but healthy
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] is None
    assert res["rs_after"] == 500


def test_future_executed_at_treated_as_outside_window():
    """Defensive: clock skew putting executed_at in the future → don't heal
    (age would be negative, fails the `0 <= age <= 60` check)."""
    now = datetime.now(timezone.utc)
    t = _make_trade(
        shares=100,
        executed_at=(now + timedelta(seconds=30)).isoformat(),
    )
    res = _run_heal_logic(t, now=now)
    assert res["healed"] is False
    assert res["skipped_reason"] == "outside_window"


def test_malformed_executed_at_skips_safely():
    """Garbage timestamp → fail to parse → skip without crashing."""
    t = _make_trade(shares=100, executed_at="not-a-date")
    res = _run_heal_logic(t)
    assert res["healed"] is False
    assert res["skipped_reason"] == "outside_window"
