"""
test_chart_markers_v19_34_25.py
================================
Verifies the v19.34.25 chart-marker overhaul in
`backend/routers/sentcom_chart.py::_fetch_trade_markers`:

  • Long entries paint green ▲ (`#10b981`), short entries red ▼ (`#f43f5e`)
    — previously cyan / purple which read as "exit colors" to operators.
  • Final exits color-code by outcome + reason:
       - Stop-loss exit (loss) → amber (#f59e0b), tag "SL"
       - Winning exit (target / trail-in-profit) → cyan (#22d3ee), tag "PT"
       - Other loss / manual close → rose (#f43f5e), tag "X"
  • `partial_exits` entries paint a small circle marker (no arrow) on the
    bar of each scale-out, color-coded by sign of partial_pnl.
  • Adopted-trade entries align to `ib_fill_time` when present (preferred
    over `entry_at` so the marker lands on the actual fill bar).
  • Open trades (no closed_at) STILL produce an entry marker provided the
    entry timestamp falls inside the chart window.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Module under test imports lazily; we patch the module-level `_db`
# directly so we don't need a real Mongo connection.
sys.path.insert(0, "/app/backend")
import routers.sentcom_chart as sc  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _setup_db(docs: list[dict]) -> None:
    """Inject a fake `_db` whose `bot_trades` collection returns docs."""
    coll = MagicMock()
    cursor = MagicMock()
    cursor.limit.return_value = docs
    coll.find.return_value = cursor
    sc._db = {"bot_trades": coll}


def teardown_function(_fn):  # noqa: D401
    sc._db = None  # leave the module clean between tests


def test_long_entry_marker_is_green_arrow_up():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 11.96,
        "entry_at": _iso(entry_dt),
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(entry_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    entries = [m for m in markers if m["shape"] == "arrowUp"]
    assert len(entries) == 1
    m = entries[0]
    assert m["color"] == "#10b981"
    assert m["position"] == "belowBar"


def test_short_entry_marker_is_red_arrow_down():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "short",
        "entry_price": 12.50,
        "entry_at": _iso(entry_dt),
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(entry_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    entries = [m for m in markers if m["shape"] == "arrowDown" and "entry" in m["text"]]
    assert len(entries) == 1
    assert entries[0]["color"] == "#f43f5e"
    assert entries[0]["position"] == "aboveBar"


def test_stop_loss_exit_is_amber_with_sl_tag():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    exit_dt = datetime(2026, 5, 13, 15, 0,  tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "exit_price": 11.80,
        "entry_at": _iso(entry_dt),
        "closed_at": _iso(exit_dt),
        "exit_reason": "stop_hit",
        "pnl": -20.0,
        "r_multiple": -1.0,
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(exit_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    exits = [m for m in markers if "exit" in m["text"]]
    assert len(exits) == 1
    assert exits[0]["color"] == "#f59e0b"
    assert exits[0]["text"].startswith("SL ")


def test_winning_exit_is_cyan_with_pt_tag():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    exit_dt = datetime(2026, 5, 13, 15, 0,  tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "exit_price": 12.50,
        "entry_at": _iso(entry_dt),
        "closed_at": _iso(exit_dt),
        "exit_reason": "target_hit",
        "pnl": 50.0,
        "r_multiple": 2.5,
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(exit_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    exits = [m for m in markers if "exit" in m["text"]]
    assert len(exits) == 1
    assert exits[0]["color"] == "#22d3ee"
    assert exits[0]["text"].startswith("PT ")


def test_partial_exits_paint_circle_dots():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    pe1_dt = datetime(2026, 5, 13, 14, 45, tzinfo=timezone.utc)
    pe2_dt = datetime(2026, 5, 13, 14, 55, tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "entry_at": _iso(entry_dt),
        "partial_exits": [
            {"exited_at": _iso(pe1_dt), "shares_sold": 50, "fill_price": 12.10, "partial_pnl": 5.0, "target_idx": 0},
            {"exited_at": _iso(pe2_dt), "shares_sold": 50, "fill_price": 12.20, "partial_pnl": 10.0, "target_idx": 1},
        ],
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(pe2_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    dots = [m for m in markers if m["shape"] == "circle"]
    assert len(dots) == 2
    assert all(d["color"] == "#10b981" for d in dots)  # both positive
    assert "scale-out T1" in dots[0]["text"]
    assert "scale-out T2" in dots[1]["text"]


def test_partial_exit_loss_paints_red_dot():
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    pe_dt = datetime(2026, 5, 13, 14, 45, tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "entry_at": _iso(entry_dt),
        "partial_exits": [
            {"exited_at": _iso(pe_dt), "shares_sold": 50, "fill_price": 11.90, "partial_pnl": -5.0},
        ],
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(pe_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    dots = [m for m in markers if m["shape"] == "circle"]
    assert len(dots) == 1
    assert dots[0]["color"] == "#f43f5e"


def test_ib_fill_time_overrides_entry_at():
    """Adopted-trade timing: ib_fill_time wins over entry_at."""
    fill_dt = datetime(2026, 5, 13, 14, 30, 5, tzinfo=timezone.utc)   # real IB fill
    record_dt = datetime(2026, 5, 13, 14, 30, 45, tzinfo=timezone.utc)  # 40s later
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "entry_at": _iso(record_dt),
        "ib_fill_time": _iso(fill_dt),
    }])
    start = int(fill_dt.timestamp()) - 3600
    end = int(record_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    entries = [m for m in markers if "entry" in m["text"]]
    assert len(entries) == 1
    assert entries[0]["time"] == int(fill_dt.timestamp())


def test_open_trade_still_paints_entry_marker():
    """v19.34.25 — open trades (no closed_at) must still paint entry."""
    entry_dt = datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc)
    _setup_db([{
        "symbol": "SMR",
        "direction": "long",
        "entry_price": 12.00,
        "entry_at": _iso(entry_dt),
        # No closed_at, no exit_price — open trade.
    }])
    start = int(entry_dt.timestamp()) - 3600
    end = int(entry_dt.timestamp()) + 3600
    markers = sc._fetch_trade_markers("SMR", start, end)
    entries = [m for m in markers if "entry" in m["text"]]
    exits = [m for m in markers if "exit" in m["text"]]
    assert len(entries) == 1
    assert len(exits) == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
