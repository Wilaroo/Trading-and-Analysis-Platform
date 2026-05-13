"""v19.34.144 — Position consolidator: clamp `proposed_total_shares`
to IB qty when ledger sum overshoots.

Bug surfaced 2026-02-13 (KMB phantom-share crisis): the bot's
`_open_trades` ledger held 144 KMB shares (across one or more
fragments) while IB only held 55. If the consolidator runs on a
multi-fragment KMB group, it computes `total_shares = 144` (the sum
of all fragments) and places ONE OCA bracket sized to 144 — which
overshoots IB. When the stop fires, the bot SELLS 144 shares but
IB only has 55, so the bot inadvertently opens an 89-share NAKED
SHORT.

v19.34.144 fix: clamp `proposed_total_shares` to
`min(ledger_sum, abs(ib_qty))` whenever the IB pusher snapshot says
IB has fewer shares than the ledger sum AND directions agree.

Tests cover:
  - 2 fragments summing to 144 with IB=55 → proposed_total_shares=55
  - 2 fragments summing to 144 with IB=144 → no clamp
  - 2 fragments summing to 60 with IB=100 → no clamp (ledger short)
  - LONG ledger vs SHORT IB → don't clamp (let sign-mismatch path own it)
  - IB snapshot missing → don't clamp (no data, safe default)
  - dry-run report exposes `ib_qty`, `clamped_to_ib_qty`,
    `ledger_sum_overshoot` for operator transparency
"""

from unittest.mock import MagicMock, patch
import pytest


def _make_trade(*, tid, symbol, shares, direction="long",
                entered_by=None, setup_type="bot_originated"):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.shares = shares
    t.remaining_shares = shares
    direction_mock = MagicMock()
    direction_mock.value = direction
    t.direction = direction_mock
    t.entered_by = entered_by
    t.setup_type = setup_type
    t.stop_price = 100.0
    t.target_prices = [110.0]
    t.fill_price = 105.0
    t.entry_price = 105.0
    t.unrealized_pnl = 0.0
    t.entry_time = "2026-02-13T10:00:00"
    return t


def _make_bot(*, open_trades):
    bot = MagicMock()
    bot._open_trades = open_trades
    return bot


def _patch_ib_positions(positions):
    """Patch `routers.ib._pushed_ib_data` for the clamp lookup."""
    import sys
    fake_ib = type(sys)("routers.ib")
    fake_ib._pushed_ib_data = {"positions": positions}
    return patch.dict(sys.modules, {"routers.ib": fake_ib})


# ────────────────────────────────────────────────────────────────────
# 1. The KMB case: ledger=144, IB=55 → clamp to 55
# ────────────────────────────────────────────────────────────────────

def test_kmb_ledger_overshoot_clamps_to_ib_qty():
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="t-entry", symbol="KMB", shares=55,
                     direction="long", setup_type="momentum_breakout")
    t2 = _make_trade(tid="t-excess", symbol="KMB", shares=89,
                     direction="long",
                     entered_by="reconciled_excess_v19_34_15b",
                     setup_type="reconciled_excess_slice")
    bot = _make_bot(open_trades={"t-entry": t1, "t-excess": t2})

    with _patch_ib_positions([
        {"symbol": "KMB", "position": 55, "avgCost": 135.0,
         "marketPrice": 134.5, "unrealizedPNL": -27.5},
    ]):
        consolidator = PositionConsolidator()
        diff = consolidator._build_diff(bot)

    assert diff["fragmented_groups"] == 1
    g = diff["groups"][0]
    assert g["symbol"] == "KMB"
    assert g["current_total_shares"] == 144   # raw ledger sum
    assert g["proposed_total_shares"] == 55   # clamped to IB qty
    assert g["clamped_to_ib_qty"] is True
    assert g["ib_qty"] == 55
    assert g["ledger_sum_overshoot"] == 89


def test_clamp_picks_non_reconciled_canonical_even_when_clamped():
    """Canonical pick must still prefer the non-reconciled (bot-originated)
    trade. The clamp affects sizing, not canonical choice."""
    from services.position_consolidator import PositionConsolidator
    t_bot = _make_trade(tid="t-bot", symbol="KMB", shares=55,
                        direction="long", setup_type="momentum_breakout")
    t_recon = _make_trade(tid="t-recon", symbol="KMB", shares=89,
                          direction="long",
                          entered_by="reconciled_excess_v19_34_15b",
                          setup_type="reconciled_excess_slice")
    bot = _make_bot(open_trades={"t-bot": t_bot, "t-recon": t_recon})

    with _patch_ib_positions([
        {"symbol": "KMB", "position": 55, "avgCost": 135.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    # Non-reconciled trade is canonical → t-bot.
    assert g["proposed_canonical"]["trade_id"] == "t-bot"
    # Siblings list contains the reconciled excess slice.
    sibling_ids = {s["trade_id"] for s in g["siblings_to_close"]}
    assert sibling_ids == {"t-recon"}


# ────────────────────────────────────────────────────────────────────
# 2. Ledger sum == IB qty → no clamp
# ────────────────────────────────────────────────────────────────────

def test_ledger_matches_ib_no_clamp():
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="a", symbol="AAPL", shares=72, direction="long")
    t2 = _make_trade(tid="b", symbol="AAPL", shares=72, direction="long")
    bot = _make_bot(open_trades={"a": t1, "b": t2})

    with _patch_ib_positions([
        {"symbol": "AAPL", "position": 144, "avgCost": 200.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    assert g["proposed_total_shares"] == 144
    assert g["clamped_to_ib_qty"] is False
    assert g["ledger_sum_overshoot"] == 0


# ────────────────────────────────────────────────────────────────────
# 3. Ledger < IB qty → no clamp (ledger is short, not over)
# ────────────────────────────────────────────────────────────────────

def test_ledger_short_of_ib_no_clamp():
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="a", symbol="MSFT", shares=30, direction="long")
    t2 = _make_trade(tid="b", symbol="MSFT", shares=30, direction="long")
    bot = _make_bot(open_trades={"a": t1, "b": t2})

    with _patch_ib_positions([
        {"symbol": "MSFT", "position": 100, "avgCost": 400.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    # Ledger sum (60) is LESS than IB (100) — no clamp.
    assert g["proposed_total_shares"] == 60
    assert g["clamped_to_ib_qty"] is False


# ────────────────────────────────────────────────────────────────────
# 4. Direction mismatch → don't clamp, let sign-mismatch path handle it
# ────────────────────────────────────────────────────────────────────

def test_direction_mismatch_skips_clamp():
    """If bot is LONG but IB is SHORT (or vice versa), the consolidator
    must NOT clamp — that's a sign-mismatch bug the diagnostic owns.
    Clamping here would mask the true direction conflict."""
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="a", symbol="WEIRD", shares=72, direction="long")
    t2 = _make_trade(tid="b", symbol="WEIRD", shares=72, direction="long")
    bot = _make_bot(open_trades={"a": t1, "b": t2})

    with _patch_ib_positions([
        # IB is SHORT 100 while ledger is LONG 144.
        {"symbol": "WEIRD", "position": -100, "avgCost": 50.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    assert g["proposed_total_shares"] == 144  # unclamped
    assert g["clamped_to_ib_qty"] is False
    assert g["ib_qty"] == -100  # preserved for operator inspection


# ────────────────────────────────────────────────────────────────────
# 5. IB snapshot missing → don't clamp (safe default)
# ────────────────────────────────────────────────────────────────────

def test_no_ib_snapshot_skips_clamp():
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="a", symbol="UNKNOWN", shares=72, direction="long")
    t2 = _make_trade(tid="b", symbol="UNKNOWN", shares=72, direction="long")
    bot = _make_bot(open_trades={"a": t1, "b": t2})

    # IB pusher has no position for UNKNOWN.
    with _patch_ib_positions([
        {"symbol": "OTHER", "position": 100, "avgCost": 50.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    assert g["proposed_total_shares"] == 144  # unclamped (no data)
    assert g["clamped_to_ib_qty"] is False
    assert g["ib_qty"] is None


def test_ib_module_unavailable_skips_clamp_safely():
    """If `routers.ib` itself blows up, the clamp must fall back to
    ledger sum and NOT raise."""
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="a", symbol="ANY", shares=72, direction="long")
    t2 = _make_trade(tid="b", symbol="ANY", shares=72, direction="long")
    bot = _make_bot(open_trades={"a": t1, "b": t2})

    with patch.object(
        PositionConsolidator, "_fetch_ib_qty_map", return_value={}
    ):
        diff = PositionConsolidator()._build_diff(bot)
    g = diff["groups"][0]
    assert g["proposed_total_shares"] == 144  # ledger sum, unclamped
    assert g["clamped_to_ib_qty"] is False


# ────────────────────────────────────────────────────────────────────
# 6. Short ledger over short IB — clamp still works on shorts
# ────────────────────────────────────────────────────────────────────

def test_short_ledger_overshoot_clamps():
    """Symmetric case: bot is SHORT 144, IB is SHORT 55 → clamp to 55."""
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="s1", symbol="TSLA", shares=72, direction="short")
    t2 = _make_trade(tid="s2", symbol="TSLA", shares=72, direction="short")
    bot = _make_bot(open_trades={"s1": t1, "s2": t2})

    with _patch_ib_positions([
        {"symbol": "TSLA", "position": -55, "avgCost": 400.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    g = diff["groups"][0]
    assert g["direction"] == "short"
    assert g["proposed_total_shares"] == 55
    assert g["clamped_to_ib_qty"] is True
    assert g["ledger_sum_overshoot"] == 89


# ────────────────────────────────────────────────────────────────────
# 7. Single fragment (N=1) → not in diff at all (no consolidation needed)
# ────────────────────────────────────────────────────────────────────

def test_single_fragment_not_in_diff_even_when_overshoots():
    """The consolidator only operates on N>1 groups. Single-fragment
    overshoot is handled by the share-drift reconciler, not the
    consolidator. Document this with a test so future agents don't
    accidentally widen the consolidator scope."""
    from services.position_consolidator import PositionConsolidator
    t1 = _make_trade(tid="solo", symbol="LONE", shares=144, direction="long")
    bot = _make_bot(open_trades={"solo": t1})

    with _patch_ib_positions([
        {"symbol": "LONE", "position": 55, "avgCost": 100.0},
    ]):
        diff = PositionConsolidator()._build_diff(bot)

    assert diff["fragmented_groups"] == 0
    assert diff["groups"] == []


# ────────────────────────────────────────────────────────────────────
# 8. The clamped value is what `_consolidate_one_group` reads to size
#    canonical.remaining_shares. (Integration sanity, not full e2e.)
# ────────────────────────────────────────────────────────────────────

def test_consolidate_one_group_reads_clamped_total_shares():
    """`_consolidate_one_group` does `total_shares = int(g["proposed_total_shares"])`
    on line 273 and `canonical.remaining_shares = total_shares` on
    line 318. The clamp in `_build_diff` is the only thing that
    keeps the canonical from being sized to phantom shares — this
    test enforces the contract that the diff's `proposed_total_shares`
    field IS what flows downstream.
    """
    from services.position_consolidator import PositionConsolidator
    import inspect
    src = inspect.getsource(PositionConsolidator._consolidate_one_group)
    # The contract: the method must read `proposed_total_shares` from
    # the group diff and assign it to `canonical.remaining_shares`.
    assert 'g["proposed_total_shares"]' in src or "g['proposed_total_shares']" in src
    assert "canonical.remaining_shares" in src
