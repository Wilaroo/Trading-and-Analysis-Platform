"""v19.34.150 — IB pusher position health diagnostic regression.

Pins the failure-mode classification logic in
`/api/diagnostic/ib-pusher-position-health`. The operator's live
audit shows 21/21 positions with `unrealizedPNL=0` — this endpoint
must classify that as "🔴 reqAccountUpdates() is DEAD" with a
clear remediation pointer, not a generic "stale".
"""

import sys
from unittest.mock import MagicMock

import pytest


def _patch_pusher(monkeypatch, *, positions, last_update=None,
                  connected=True, push_count=100, recent_ts=None):
    """Mock `routers.ib` so the diagnostic endpoint reads our fixture."""
    fake = type(sys)("routers.ib")
    fake._pushed_ib_data = {
        "positions": positions,
        "last_update": last_update,
        "connected": connected,
    }
    fake._push_count_total = push_count
    from collections import deque
    fake._push_timestamps = deque(recent_ts or [], maxlen=120)
    monkeypatch.setitem(sys.modules, "routers.ib", fake)


# ────────────────────────────────────────────────────────────────────
# 1. Failure-mode classification
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_account_updates_dead(monkeypatch):
    """0/21 unrealizedPNL AND 0/21 marketPrice → 🔴 callback dead."""
    import time
    positions = [
        {"symbol": f"S{i:02d}", "position": 100,
         "avgCost": 50.0,    # avgCost present (reqPositions alive)
         "marketPrice": 0,
         "unrealizedPNL": 0}
        for i in range(21)
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()

    assert resp["success"] is True
    assert resp["total_positions"] == 21
    assert resp["field_stats"]["unrealizedPNL"]["non_zero_count"] == 0
    assert resp["field_stats"]["marketPrice"]["non_zero_count"] == 0
    # avgCost is healthy → ONLY the account-updates-dead diagnosis,
    # NOT the avgCost-dead diagnosis.
    joined = " | ".join(resp["diagnosis"])
    assert "reqAccountUpdates" in joined
    assert "DEAD" in joined
    assert "Restart" in joined or "restart" in joined
    # Should NOT diagnose avgCost dead since avgCost is 50.0 everywhere.
    assert "`avgCost` is zero" not in joined


@pytest.mark.asyncio
async def test_avg_cost_dead_diagnosis(monkeypatch):
    """avgCost=0 across the board → 🔴 avgCost-dead diagnosis fires."""
    import time
    positions = [
        {"symbol": "AAPL", "position": 100,
         "avgCost": 0, "marketPrice": 0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "`avgCost` is zero" in joined
    assert "pusher started BEFORE" in joined.lower() or \
           "started before" in joined.lower()


@pytest.mark.asyncio
async def test_partial_unrealized_missing(monkeypatch):
    """Some symbols have unrealizedPNL, some don't → per-symbol issue."""
    import time
    positions = [
        {"symbol": "GOOD1", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "GOOD2", "position": 50, "avgCost": 200.0,
         "marketPrice": 201.0, "unrealizedPNL": 50.0},
        {"symbol": "BAD1", "position": 100, "avgCost": 30.0,
         "marketPrice": 0, "unrealizedPNL": 0},
        {"symbol": "BAD2", "position": 200, "avgCost": 40.0,
         "marketPrice": 0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "2/4 live positions have `unrealizedPNL=0`" in joined
    assert "per-symbol subscription" in joined.lower()


@pytest.mark.asyncio
async def test_market_price_only_dead(monkeypatch):
    """marketPrice present, unrealizedPNL zero → less-severe diagnosis."""
    import time
    positions = [
        {"symbol": "X", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "deferring PnL" in joined.lower() or \
           "self-heals" in joined.lower()


@pytest.mark.asyncio
async def test_slow_pusher_heartbeat_warning(monkeypatch):
    """<2 pushes in last 60s triggers heartbeat warning (calibrated to
    push_interval=10s baseline of 6/min)."""
    import time
    positions = [
        {"symbol": "X", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
    ]
    _patch_pusher(
        monkeypatch, positions=positions,
        recent_ts=[time.time() - 30],  # only 1 push in last 60s
    )
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "Pusher heartbeat is slow" in joined or \
           "pusher heartbeat is slow" in joined.lower()


@pytest.mark.asyncio
async def test_stale_last_update(monkeypatch):
    """last_update > 60s ago → 'pusher likely dead' warning."""
    from datetime import datetime, timezone, timedelta
    import time
    stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    positions = [
        {"symbol": "X", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
    ]
    _patch_pusher(
        monkeypatch, positions=positions, last_update=stale,
        recent_ts=[time.time()] * 60,
    )
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "Last push was" in joined or "pusher likely dead" in joined.lower()


@pytest.mark.asyncio
async def test_empty_positions_classified_correctly(monkeypatch):
    """Pusher has never sent positions → distinct diagnosis (not a
    health failure, just "never connected")."""
    _patch_pusher(monkeypatch, positions=[])
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["total_positions"] == 0
    joined = " | ".join(resp["diagnosis"])
    assert "never pushed" in joined.lower() or "reset" in joined.lower()


@pytest.mark.asyncio
async def test_healthy_pusher_clean_diagnosis(monkeypatch):
    """All fields populated → "✅ healthy" diagnosis."""
    import time
    positions = [
        {"symbol": f"S{i}", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "marketValue": 5100.0,
         "unrealizedPNL": 100.0, "realizedPNL": 0.0}
        for i in range(5)
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"])
    assert "healthy" in joined.lower()


# ────────────────────────────────────────────────────────────────────
# 2. Per-field stats correctness
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_field_stats_count_correctly(monkeypatch):
    import time
    positions = [
        {"symbol": "A", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "B", "position": 50, "avgCost": 30.0,
         "marketPrice": 0, "unrealizedPNL": 0},
        # C missing marketPrice entirely
        {"symbol": "C", "position": 25, "avgCost": 20.0,
         "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    fs = resp["field_stats"]

    # marketPrice: 1 non-zero (A), 1 zero (B), 1 missing (C)
    assert fs["marketPrice"]["non_zero_count"] == 1
    assert fs["marketPrice"]["zero_count"] == 1
    assert fs["marketPrice"]["missing_count"] == 1
    assert fs["marketPrice"]["presence_pct"] == pytest.approx(33.3, abs=0.1)

    # unrealizedPNL: 1 non-zero (A), 2 zero (B, C)
    assert fs["unrealizedPNL"]["non_zero_count"] == 1
    assert fs["unrealizedPNL"]["zero_count"] == 2
    assert fs["unrealizedPNL"]["missing_count"] == 0

    # avgCost: 3 non-zero
    assert fs["avgCost"]["non_zero_count"] == 3
    assert fs["avgCost"]["presence_pct"] == 100.0


@pytest.mark.asyncio
async def test_sample_non_zero_value_carried(monkeypatch):
    import time
    positions = [
        {"symbol": "A", "position": 100, "avgCost": 50.0,
         "marketPrice": 0, "unrealizedPNL": 0},
        {"symbol": "B", "position": 50, "avgCost": 30.0,
         "marketPrice": 31.0, "unrealizedPNL": 50.0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    sample = resp["field_stats"]["marketPrice"]["sample_non_zero"]
    assert sample is not None
    assert sample["symbol"] == "B"
    assert sample["value"] == 31.0


@pytest.mark.asyncio
async def test_per_symbol_drilldown_complete(monkeypatch):
    import time
    positions = [
        {"symbol": "AAPL", "position": 100, "avgCost": 200.0,
         "marketPrice": 205.0, "unrealizedPNL": 500.0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    per_sym = resp["per_symbol"]
    assert len(per_sym) == 1
    row = per_sym[0]
    assert row["symbol"] == "AAPL"
    assert row["position"] == 100.0
    assert row["avgCost"] == 200.0
    assert row["marketPrice"] == 205.0
    assert row["unrealizedPNL"] == 500.0


@pytest.mark.asyncio
async def test_non_numeric_field_treated_as_missing(monkeypatch):
    """Garbage values (string, None) increment missing_count, not zero."""
    import time
    positions = [
        {"symbol": "WEIRD", "position": 100, "avgCost": "N/A",
         "marketPrice": None, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    fs = resp["field_stats"]
    assert fs["avgCost"]["missing_count"] == 1
    assert fs["marketPrice"]["missing_count"] == 1
    assert fs["unrealizedPNL"]["zero_count"] == 1



# ────────────────────────────────────────────────────────────────────
# 3. v19.34.150b — Ghost (position==0) row filtering & health enum
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_position_ghost_excluded_from_field_stats(monkeypatch):
    """IB Gateway leaves position=0 ghost records after intraday closes.
    They have a live marketPrice but all PnL fields are 0. Field stats
    must compute presence_pct against LIVE positions only, not ghosts.
    """
    import time
    positions = [
        # 4 real live positions — fully populated
        {"symbol": "A", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "B", "position": -50, "avgCost": 30.0,
         "marketPrice": 29.0, "unrealizedPNL": 50.0},
        {"symbol": "C", "position": 200, "avgCost": 20.0,
         "marketPrice": 21.0, "unrealizedPNL": 200.0},
        {"symbol": "D", "position": 75, "avgCost": 100.0,
         "marketPrice": 101.0, "unrealizedPNL": 75.0},
        # 2 ghosts — closed intraday, IB still streaming the quote
        {"symbol": "GHOST1", "position": 0, "avgCost": 0,
         "marketPrice": 12.5, "marketValue": 0, "unrealizedPNL": 0},
        {"symbol": "GHOST2", "position": 0, "avgCost": 0,
         "marketPrice": 55.0, "marketValue": 0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()

    assert resp["total_positions"] == 6
    assert resp["live_position_count"] == 4
    assert resp["ghost_zero_position_count"] == 2

    fs = resp["field_stats"]
    assert fs["unrealizedPNL"]["non_zero_count"] == 4
    assert fs["unrealizedPNL"]["zero_count"] == 0
    assert fs["unrealizedPNL"]["presence_pct"] == 100.0
    assert fs["marketPrice"]["non_zero_count"] == 4
    assert fs["marketPrice"]["presence_pct"] == 100.0

    joined = " | ".join(resp["diagnosis"])
    assert "reqAccountUpdates" not in joined or "DEAD" not in joined


@pytest.mark.asyncio
async def test_ghost_rows_tagged_in_per_symbol(monkeypatch):
    """per_symbol still surfaces ghosts (for visibility) but flags them."""
    import time
    positions = [
        {"symbol": "LIVE", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "GHOST", "position": 0, "avgCost": 0,
         "marketPrice": 25.0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    rows = {r["symbol"]: r for r in resp["per_symbol"]}
    assert rows["LIVE"]["is_ghost"] is False
    assert rows["GHOST"]["is_ghost"] is True


@pytest.mark.asyncio
async def test_all_ghost_no_live_distinct_diagnosis(monkeypatch):
    """Pusher has records but zero are live → distinct, not "callback dead"."""
    import time
    positions = [
        {"symbol": "G1", "position": 0, "avgCost": 0,
         "marketPrice": 10.0, "unrealizedPNL": 0},
        {"symbol": "G2", "position": 0, "avgCost": 0,
         "marketPrice": 20.0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["live_position_count"] == 0
    assert resp["ghost_zero_position_count"] == 2
    joined = " | ".join(resp["diagnosis"]).lower()
    assert "ghost" in joined or "no live" in joined
    assert "reqaccountupdates" not in joined


@pytest.mark.asyncio
async def test_health_enum_green(monkeypatch):
    import time
    positions = [
        {"symbol": f"S{i}", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0}
        for i in range(5)
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["health"] == "green"


@pytest.mark.asyncio
async def test_health_enum_red_when_account_updates_dead(monkeypatch):
    import time
    positions = [
        {"symbol": f"S{i}", "position": 100, "avgCost": 50.0,
         "marketPrice": 0, "unrealizedPNL": 0}
        for i in range(5)
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["health"] == "red"


@pytest.mark.asyncio
async def test_health_enum_amber_on_partial(monkeypatch):
    import time
    positions = [
        {"symbol": "GOOD", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "BAD", "position": 50, "avgCost": 30.0,
         "marketPrice": 0, "unrealizedPNL": 0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 60)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["health"] == "amber"


@pytest.mark.asyncio
async def test_health_enum_unknown_when_disconnected(monkeypatch):
    _patch_pusher(monkeypatch, positions=[], connected=False)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["health"] == "unknown"


# ────────────────────────────────────────────────────────────────────
# 4. v19.34.150c — Cold-start debouncing + cadence-aware heartbeat
#                  + stuck_symbols surfacing
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cold_start_holds_health_unknown(monkeypatch):
    """First ~5 pushes after pusher restart should NOT be classified RED.
    With only 2 total pushes since boot, even an all-zeros payload is
    'too early to tell' — IB Gateway hasn't delivered the first
    updatePortfolio() batch yet.
    """
    import time
    positions = [
        {"symbol": f"S{i}", "position": 100, "avgCost": 50.0,
         "marketPrice": 0, "unrealizedPNL": 0}
        for i in range(21)
    ]
    _patch_pusher(
        monkeypatch, positions=positions,
        recent_ts=[time.time()] * 2,
        push_count=2,  # cold start
    )
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["cold_start"] is True
    assert resp["health"] == "unknown"
    # Heartbeat warning must NOT fire while cold-starting
    joined = " | ".join(resp["diagnosis"])
    assert "heartbeat is slow" not in joined.lower()


@pytest.mark.asyncio
async def test_after_warmup_account_updates_dead_still_red(monkeypatch):
    """Cold-start guard must NOT mask a genuine reqAccountUpdates failure.
    With 50 total pushes, the pusher has been running long enough that
    all-zeros marketPrice/unrealizedPNL IS a real callback death.
    """
    import time
    positions = [
        {"symbol": f"S{i}", "position": 100, "avgCost": 50.0,
         "marketPrice": 0, "unrealizedPNL": 0}
        for i in range(21)
    ]
    _patch_pusher(
        monkeypatch, positions=positions,
        recent_ts=[time.time()] * 6,
        push_count=50,
    )
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["cold_start"] is False
    assert resp["health"] == "red"


@pytest.mark.asyncio
async def test_heartbeat_threshold_recalibrated_to_pusher_cadence(monkeypatch):
    """ib_data_pusher.push_interval=10s → 6/min baseline.
    A reading of 5/min is normal (not a warning).
    A reading of 1/min IS a warning.
    """
    import time
    positions = [
        {"symbol": "X", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
    ]

    # 5 pushes/min — within tolerance. No warning.
    _patch_pusher(
        monkeypatch, positions=positions,
        recent_ts=[time.time() - i for i in range(5)],
        push_count=50,
    )
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"]).lower()
    assert "heartbeat is slow" not in joined

    # 1 push/min — clearly stalled. Warning fires.
    _patch_pusher(
        monkeypatch, positions=positions,
        recent_ts=[time.time()],
        push_count=50,
    )
    resp = await ib_pusher_position_health()
    joined = " | ".join(resp["diagnosis"]).lower()
    assert "heartbeat is slow" in joined
    assert "push_interval=10s" in joined  # cadence transparency


@pytest.mark.asyncio
async def test_stuck_symbols_surfaced(monkeypatch):
    """Live positions with unrealizedPNL=0 are listed in `stuck_symbols`."""
    import time
    positions = [
        {"symbol": "AAPL", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
        {"symbol": "TSLA", "position": 50, "avgCost": 200.0,
         "marketPrice": 0, "unrealizedPNL": 0},  # stuck
        {"symbol": "GHOST", "position": 0, "avgCost": 0,
         "marketPrice": 10.0, "unrealizedPNL": 0},  # ghost, NOT stuck
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 6, push_count=50)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["stuck_symbols"] == ["TSLA"]
    assert "GHOST" not in resp["stuck_symbols"]


@pytest.mark.asyncio
async def test_pushes_per_minute_expected_in_response(monkeypatch):
    """Response surfaces the expected baseline so UI can render
    `recent / expected` without hardcoding."""
    import time
    positions = [
        {"symbol": "X", "position": 100, "avgCost": 50.0,
         "marketPrice": 51.0, "unrealizedPNL": 100.0},
    ]
    _patch_pusher(monkeypatch, positions=positions,
                  recent_ts=[time.time()] * 6, push_count=50)
    from routers.diagnostic_router import ib_pusher_position_health
    resp = await ib_pusher_position_health()
    assert resp["pushes_per_minute_expected"] == 6
