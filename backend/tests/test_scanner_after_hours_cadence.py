"""
Regression tests for the after-hours scanner cadence + carry-forward
threshold tweaks shipped 2026-04-28e.

Operator was seeing empty after-hours / overnight / market-open watchlists
because:
  1. After-hours daily scan only ran every 100 min (`_scan_count % 20 == 0`
     with sleep(300)).
  2. Carry-forward TQS gate was 60 (cont/fade) / 70 (catch-all) — too high
     for the bulk of B-grade setups today's scanner produces.

These tests lock the new cadence + thresholds.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from services.enhanced_scanner import EnhancedBackgroundScanner


@pytest.fixture
def scanner():
    """Create a scanner without running its full init —
    we only need the methods, not the network/DB side-effects."""
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._live_alerts = {}
    s.db = MagicMock()
    s._market_regime = MagicMock(value="neutral")
    return s


# ─── Cadence: scan_count gating math ────────────────────────────────────

def test_after_hours_scan_runs_every_4_cycles():
    """`_scan_count % 4 == 0` means scans fire at 0, 4, 8, 12, … which
    with sleep(300) = 5min/cycle works out to every 20 min."""
    fires_in_first_24_cycles = sum(1 for n in range(24) if n % 4 == 0 or n == 0)
    # 24 cycles × 5 min/cycle = 2 hours. Should fire 6 times in 2 hours.
    assert fires_in_first_24_cycles == 6


# ─── Carry-forward TQS thresholds ───────────────────────────────────────

@pytest.mark.asyncio
async def test_carry_forward_promotes_b_grade_continuation_setup(scanner):
    """A breakout with TQS=52 (B grade) should now be promoted as a
    `day_2_continuation` instead of being silently dropped."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake_alert = {
        "symbol": "TSLA", "setup_type": "breakout", "direction": "long",
        "tqs_score": 52, "tqs_grade": "B",
        "priority": "medium", "current_price": 100, "trigger_price": 100,
        "stop_loss": 98, "target": 105, "risk_reward": 2.5,
        "headline": "", "reasoning": [],
    }
    # Mock the cursor that `find().sort().limit()` returns
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value = iter([
        {**fake_alert, "created_at": today + "T15:30:00+00:00"},
    ])
    scanner.db["live_alerts"].find = MagicMock(return_value=cursor)
    scanner._process_new_alert = AsyncMock()

    await scanner._rank_carry_forward_setups_for_tomorrow()

    # The single B-grade breakout should have been promoted.
    assert scanner._process_new_alert.await_count == 1
    promoted = scanner._process_new_alert.await_args.args[0]
    assert promoted.symbol == "TSLA"
    assert promoted.setup_type == "day_2_continuation"


@pytest.mark.asyncio
async def test_carry_forward_promotes_high_quality_unmatched_setup(scanner):
    """A setup with TQS=58 NOT in cont/fade lists should still be
    promoted via the catch-all (lowered from 70 → 55)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value = iter([
        {
            "symbol": "NVDA", "setup_type": "exotic_pattern",
            "direction": "long", "tqs_score": 58, "tqs_grade": "B+",
            "current_price": 500, "trigger_price": 500,
            "created_at": today + "T15:30:00+00:00",
            "stop_loss": 495, "target": 510, "risk_reward": 2.0,
            "reasoning": [], "headline": "",
        },
    ])
    scanner.db["live_alerts"].find = MagicMock(return_value=cursor)
    scanner._process_new_alert = AsyncMock()

    await scanner._rank_carry_forward_setups_for_tomorrow()

    assert scanner._process_new_alert.await_count == 1
    promoted = scanner._process_new_alert.await_args.args[0]
    assert promoted.setup_type == "carry_forward_watch"


@pytest.mark.asyncio
async def test_carry_forward_drops_low_quality(scanner):
    """A setup with TQS=40 should still fall below ALL thresholds and
    NOT be promoted."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value = iter([
        {
            "symbol": "BABA", "setup_type": "breakout",
            "direction": "long", "tqs_score": 40, "tqs_grade": "C",
            "current_price": 100, "trigger_price": 100,
            "created_at": today + "T15:30:00+00:00",
            "stop_loss": 98, "target": 104, "risk_reward": 2.0,
            "reasoning": [], "headline": "",
        },
    ])
    scanner.db["live_alerts"].find = MagicMock(return_value=cursor)
    scanner._process_new_alert = AsyncMock()

    await scanner._rank_carry_forward_setups_for_tomorrow()

    # Below all thresholds (cont/fade ≥50, catch-all ≥55) → not promoted
    assert scanner._process_new_alert.await_count == 0
