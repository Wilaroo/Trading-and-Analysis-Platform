"""
v19.34.60 — `_find_existing_excess_slice` zombie exclusion.

Reproduces the bug operator hit during the v19.34.59 zombie sweep:
COIN/GOOG/BKNG/LIN/MU heals returned `new_trade_id == one of zombies_closed`,
because `_find_existing_excess_slice` matched a trade with
`setup_type='reconciled_excess_slice'` AND `remaining_shares=0` (zombie).
The grow-then-close-zombie sequence resulted in the just-grown trade
being immediately re-closed.

Test guarantees: a zombie with `setup_type='reconciled_excess_slice'`
is NEVER returned as a grow candidate.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.position_reconciler import PositionReconciler


class _FakeDir:
    def __init__(self, val):
        self.value = val


def _t(**kw):
    """Build a fake BotTrade-like object for the matcher."""
    defaults = dict(
        id="x",
        symbol="COIN",
        direction=_FakeDir("long"),
        remaining_shares=0,
        entered_by="",
        setup_type="",
        entry_time="2026-02-09T10:00:00",
        executed_at="2026-02-09T10:00:00",
        created_at="2026-02-09T10:00:00",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _bot(trades):
    return SimpleNamespace(
        _open_trades={t.id: t for t in trades},
    )


def _matcher():
    return PositionReconciler(db=None)


def test_zombie_with_reconciled_setup_is_excluded():
    """The exact bug: zombie has setup_type=reconciled_excess_slice +
    remaining_shares=0. Must NOT be returned as a grow candidate."""
    zombie = _t(
        id="zombie_1",
        setup_type="reconciled_excess_slice",
        remaining_shares=0,
    )
    bot = _bot([zombie])
    res = _matcher()._find_existing_excess_slice(bot, "COIN", _FakeDir("long"))
    assert res is None, (
        f"zombie (rs=0, setup=reconciled_excess_slice) must NOT be "
        f"a grow candidate, got id={getattr(res, 'id', None)}"
    )


def test_zombie_with_reconciled_entered_by_is_excluded():
    zombie = _t(
        id="zombie_2",
        entered_by="reconciled_excess_v19_34_15b",
        remaining_shares=0,
    )
    bot = _bot([zombie])
    assert _matcher()._find_existing_excess_slice(
        bot, "COIN", _FakeDir("long")
    ) is None


def test_live_reconciled_slice_still_matches():
    """Healthy reconciled-excess slice (rs>0) MUST still match — that's
    the v19.34.42 idempotency contract for legitimate growth."""
    live = _t(
        id="live_1",
        setup_type="reconciled_excess_slice",
        entered_by="reconciled_excess_v19_34_15b",
        remaining_shares=626,
    )
    bot = _bot([live])
    res = _matcher()._find_existing_excess_slice(bot, "COIN", _FakeDir("long"))
    assert res is not None
    assert res.id == "live_1"


def test_zombie_skipped_live_returned_when_both_present():
    """Mixed population: zombie + live reconciled-excess. Matcher returns
    the live one only; zombie is silently filtered."""
    zombie = _t(
        id="zombie_old",
        setup_type="reconciled_excess_slice",
        remaining_shares=0,
        entry_time="2026-02-09T08:00:00",  # older
    )
    live = _t(
        id="live_new",
        setup_type="reconciled_excess_slice",
        entered_by="reconciled_excess_v19_34_15b",
        remaining_shares=140,
        entry_time="2026-02-09T11:00:00",  # newer
    )
    bot = _bot([zombie, live])
    res = _matcher()._find_existing_excess_slice(bot, "COIN", _FakeDir("long"))
    assert res is not None
    assert res.id == "live_new"


def test_no_reconciled_slice_returns_none():
    plain = _t(id="plain", setup_type="trade_2_hold", entered_by="bot_fired",
               remaining_shares=626)
    bot = _bot([plain])
    assert _matcher()._find_existing_excess_slice(
        bot, "COIN", _FakeDir("long")
    ) is None


def test_direction_mismatch_excluded():
    short_slice = _t(
        id="short_1",
        direction=_FakeDir("short"),
        setup_type="reconciled_excess_slice",
        remaining_shares=100,
    )
    bot = _bot([short_slice])
    res = _matcher()._find_existing_excess_slice(bot, "COIN", _FakeDir("long"))
    assert res is None


def test_symbol_mismatch_excluded():
    other = _t(
        id="other_1", symbol="GOOG",
        setup_type="reconciled_excess_slice", remaining_shares=200,
    )
    bot = _bot([other])
    res = _matcher()._find_existing_excess_slice(bot, "COIN", _FakeDir("long"))
    assert res is None
