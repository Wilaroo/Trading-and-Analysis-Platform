"""
test_position_panel_reality_v19_27.py — pin v19.27 position-panel
reality reconciliation behaviour.

Operator hit a multi-bug screenshot 2026-05-01 after several restarts:
  - 4 of 10 rows (SOFI/SBUX/MO/OKLO) rendered as orphans even though
    the bot opened them today
  - HOOD and BP showed duplicate rows (2 BotTrade records each, 1 IB
    net position each)
  - OKLO SHORT 0sh ghost row

Three coordinated fixes shipped:
  1. Smart `source` detection in `sentcom_service.get_our_positions`
     based on share-count reconciliation between bot's `_open_trades`
     peer-sum and IB's net position. Sources: `bot` (clean),
     `partial` (bot tracks SOME), `stale_bot` (phantom shares),
     `ib` (true orphan).
  2. Symbol-level grouping in `OpenPositionsV5.jsx` — collapses
     multiple BotTrade records for same symbol+direction into ONE
     aggregate row, expandable to reveal underlying trades.
  3. Auto-sweep 0sh phantoms in `position_manager.update_open_positions`
     — silent transition `remaining_shares==0 AND ib_shares==0
     → status: closed`.

Tests run pure-Python — no Mongo, no IB.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------------------------------------------------------
# Fix 1: _classify_source_v19_27
# --------------------------------------------------------------------------

def test_classify_source_clean_bot_match():
    """Bot tracks 200 SOFI long, IB shows 200 SOFI long → 'bot'."""
    from services.sentcom_service import SentComService
    ib = {"SOFI": {"qty": 200, "direction": "long", "abs_qty": 200, "avg_cost": 16, "market_price": 16}}
    out = SentComService._classify_source_v19_27(
        symbol="SOFI", direction="long", bot_total=200, ib_pos_by_symbol=ib
    )
    assert out == "bot"


def test_classify_source_partial_drift():
    """Bot tracks 5,000 SOFI but IB has 18,364 → 'partial' (bot tracks
    SOME). The orphan-row branch in get_our_positions emits an extra
    row for the unclaimed remainder so operator sees the gap."""
    from services.sentcom_service import SentComService
    ib = {"SOFI": {"qty": 18364, "direction": "long", "abs_qty": 18364,
                   "avg_cost": 16, "market_price": 16}}
    out = SentComService._classify_source_v19_27(
        symbol="SOFI", direction="long", bot_total=5000, ib_pos_by_symbol=ib
    )
    assert out == "partial"


def test_classify_source_stale_bot_phantom():
    """Bot tracks 200 OKLO short but IB shows 0 OKLO → 'stale_bot'.
    The auto-sweep loop in position_manager (Fix 3) closes these on
    the next manage cycle."""
    from services.sentcom_service import SentComService
    out = SentComService._classify_source_v19_27(
        symbol="OKLO", direction="short", bot_total=200, ib_pos_by_symbol={}
    )
    assert out == "stale_bot"


def test_classify_source_ib_only_orphan():
    """Bot tracks 0, IB has shares → 'bot' for the bot row (which won't
    exist anyway since bot_total=0). The IB-position loop will emit
    an orphan row separately."""
    from services.sentcom_service import SentComService
    out = SentComService._classify_source_v19_27(
        symbol="SBUX", direction="long", bot_total=0, ib_pos_by_symbol={}
    )
    assert out == "bot"


def test_classify_source_direction_mismatch_marks_stale():
    """Bot has long IB has short for same symbol → 'stale_bot'. The
    bot's long is phantom; the IB short renders separately as its
    own row in the IB-position loop."""
    from services.sentcom_service import SentComService
    ib = {"OKLO": {"qty": -200, "direction": "short", "abs_qty": 200,
                   "avg_cost": 50, "market_price": 50}}
    out = SentComService._classify_source_v19_27(
        symbol="OKLO", direction="long", bot_total=200, ib_pos_by_symbol=ib
    )
    assert out == "stale_bot"


def test_classify_source_tolerates_one_share_rounding():
    """Bot tracks 199 SOFI, IB has 200. ±1 share noise tolerance →
    classifies as clean 'bot' (avoids false-partial spam from
    fractional avgCost rounding)."""
    from services.sentcom_service import SentComService
    ib = {"SOFI": {"qty": 200, "direction": "long", "abs_qty": 200,
                   "avg_cost": 16, "market_price": 16}}
    out = SentComService._classify_source_v19_27(
        symbol="SOFI", direction="long", bot_total=199, ib_pos_by_symbol=ib
    )
    assert out == "bot"


# --------------------------------------------------------------------------
# Fix 1: source-level pin on aggregation in get_our_positions
# --------------------------------------------------------------------------

def test_get_our_positions_builds_bot_shares_aggregate_map():
    """`get_our_positions` must build a `bot_shares_by_symbol` map
    keyed by (symbol, direction) before the bot-trade loop, and pass
    it into `_classify_source_v19_27`."""
    import inspect
    from services.sentcom_service import SentComService
    src = inspect.getsource(SentComService.get_our_positions)
    assert "bot_shares_by_symbol" in src
    assert "ib_pos_by_symbol" in src
    assert "_classify_source_v19_27" in src


def test_get_our_positions_emits_orphan_remainder_for_partial():
    """In the IB-position loop, when bot_total > 0 AND bot_total <
    ib_abs, the function must compute `orphan_shares_signed` and emit
    a row for ONLY the unclaimed remainder (not the full IB position).
    Pre-v19.27 the function would skip the entire IB position when ANY
    bot trade existed — losing visibility on the gap."""
    import inspect
    from services.sentcom_service import SentComService
    src = inspect.getsource(SentComService.get_our_positions)
    assert "orphan_shares_signed" in src
    assert "unclaimed_shares" in src
    assert "ib_total_shares" in src
    assert "bot_tracked_shares" in src
    # Source on the orphan-row branch must be `partial` when bot
    # tracks some, `ib` only when bot tracks zero.
    assert '"partial" if bot_total_for_dir > 0 else "ib"' in src


def test_get_our_positions_skips_clean_and_stale_bot_in_ib_loop():
    """When bot_total matches IB net (clean) OR exceeds it (stale_bot),
    the IB-position loop must NOT emit an extra row — the bot row
    already covers the position. Source-level pin."""
    import inspect
    from services.sentcom_service import SentComService
    src = inspect.getsource(SentComService.get_our_positions)
    # Clean match → continue
    assert "abs(bot_total_for_dir - ib_abs) <= 1" in src
    # Stale-bot → continue (auto-sweep handles cleanup)
    assert "if bot_total_for_dir > ib_abs:" in src


# --------------------------------------------------------------------------
# Fix 3: auto-sweep 0sh phantoms in position_manager
# --------------------------------------------------------------------------

def test_position_manager_has_phantom_sweep_block():
    """`update_open_positions` must include the v19.27 auto-sweep
    block at the top of the loop. Source-level pin so a refactor
    can't drop the cleanup."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "v19.27" in src
    assert "phantom_auto_swept" in src or "phantom-sweep" in src
    assert "_open_trades.pop" in src
    # Must check IB pusher state — never sweep based on stale data.
    assert "is_pusher_connected" in src


def test_phantom_sweep_skips_when_pusher_disconnected():
    """If pusher is offline, the sweep block must be a no-op. We can't
    trust `_pushed_ib_data['positions']` is current — better to leave
    the phantom in place than auto-close based on stale state."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    # When pusher fails, ib_pos_map should be set to None and the
    # iteration must short-circuit.
    assert "ib_pos_map = None" in src
    assert "if ib_pos_map is not None:" in src


def test_phantom_sweep_skips_brand_new_fills():
    """A trade with executed_at < 30s ago must NOT be swept — IB may
    not have caught up with the fill yet. Source-level pin on the
    age guard."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "age_s < 30" in src


def test_phantom_sweep_only_on_remaining_shares_zero():
    """The sweep must only fire when `remaining_shares == 0`. Skipping
    None / uninitialised values is critical because the existing line
    119 initialises remaining_shares from `shares` for new fills —
    we'd otherwise sweep brand-new trades."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "_rem != 0" in src
    assert "_rem is None" in src


def test_phantom_sweep_emits_stream_event():
    """When a phantom is swept, the v19.27 block must emit a Unified
    Stream event so the operator sees `🧹 Auto-swept phantom OKLO …`
    in the stream — not silent state mutation."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "emit_stream_event" in src
    assert "phantom_auto_swept" in src


# --------------------------------------------------------------------------
# Fix 2: V5 frontend grouping (source-level pins)
# --------------------------------------------------------------------------

def test_v5_groups_by_symbol_direction():
    """OpenPositionsV5.jsx must implement `groupBySymbolDirection`
    that buckets multiple trades for the same symbol+direction into
    one aggregate row."""
    panel = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "sentcom" / "v5" / "OpenPositionsV5.jsx"
    src = panel.read_text()
    assert "groupBySymbolDirection" in src
    # Aggregate fields must be summed correctly
    assert "totalShares" in src
    assert "totalNotional" in src
    assert "weighted" in src.lower() or "avgEntry" in src
    # Must show the underlying members on expand
    assert "GroupMemberRow" in src
    assert "_members" in src
    assert "_is_single" in src
    assert "_unclaimed_shares" in src


def test_v5_renders_source_badges():
    """V5 must render distinct badges for `partial` / `stale_bot` /
    `ib` so operator can tell at a glance what's going on."""
    panel = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "sentcom" / "v5" / "OpenPositionsV5.jsx"
    src = panel.read_text()
    assert "SOURCE_BADGE" in src
    assert "ORPHAN" in src
    assert "PARTIAL" in src
    assert "STALE" in src


def test_v5_reconcile_button_counts_partial_and_ib():
    """Reconcile button must count BOTH `ib` (true orphans) AND
    `partial` (orphan remainders). Stale_bot is handled by the
    auto-sweep — no operator action needed."""
    panel = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "sentcom" / "v5" / "OpenPositionsV5.jsx"
    src = panel.read_text()
    assert "g.source === 'ib' || g.source === 'partial'" in src
    # The button label uses the new count
    assert "Reconcile ${reconcileCount}" in src.replace("`", "${")


def test_v5_multi_count_badge_shows_when_member_count_gt_one():
    """When a group has >1 underlying trade, render a `2×` badge so
    operator knows the row aggregates multiple bot brackets."""
    panel = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "sentcom" / "v5" / "OpenPositionsV5.jsx"
    src = panel.read_text()
    assert "memberCount > 1" in src
    assert "memberCount}×" in src or 'memberCount} ×' in src or 'memberCount}×' in src
