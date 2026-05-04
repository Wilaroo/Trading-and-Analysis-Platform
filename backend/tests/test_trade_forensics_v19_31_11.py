"""
v19.31.11 (2026-05-04) — regression pin for the trade-forensics
classifier + endpoint join logic.

Classifier verdicts pinned:
  clean / phantom_v27 / phantom_v31 / reset_orphaned /
  auto_reconciled / manual_or_external / unexplained_drift

The endpoint joins:
  - bot_trades (in window)
  - ib_live_snapshot.current
  - sentcom_thoughts (sweep + reconcile events)
  - bot_trades_reset_log (affected_ids)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Fake collection helpers ────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])

    def _matches(self, doc, query):
        if not query:
            return True
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
                continue
            if k == "$and":
                if not all(self._matches(doc, sub) for sub in v):
                    return False
                continue
            actual = doc
            for part in k.split("."):
                if isinstance(actual, dict):
                    actual = actual.get(part)
                else:
                    actual = None
                    break
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$regex" in v:
                    import re
                    flags = re.IGNORECASE if "i" in (v.get("$options", "")) else 0
                    if actual is None or not re.search(v["$regex"], str(actual), flags):
                        return False
            else:
                if actual != v:
                    return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if self._matches(d, query)]
        if sort:
            for k, direction in reversed(sort):
                rows.sort(key=lambda r: r.get(k) or "", reverse=direction == -1)
        if limit:
            rows = rows[:limit]
        return iter(rows)

    def find_one(self, query=None, projection=None):
        rows = list(self.find(query, projection))
        return rows[0] if rows else None


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.ib_live_snapshot = _FakeColl()
        self.sentcom_thoughts = _FakeColl()
        self.bot_trades_reset_log = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── Helpers to build fixtures ──────────────────────────────────────


def _trade(id_, symbol, direction="long", status="closed",
           realized_pnl=100, fill_price=100.0, exit_price=101.0,
           hours_ago=2):
    base = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "id": id_,
        "symbol": symbol,
        "direction": direction,
        "shares": 100,
        "fill_price": fill_price,
        "exit_price": exit_price,
        "status": status,
        "executed_at": base,
        "closed_at": base if status == "closed" else None,
        "created_at": base,
        "realized_pnl": realized_pnl,
        "r_multiple": 2.0,
        "close_reason": "target_hit" if status == "closed" else None,
        "setup_type": "vwap_bounce_long",
    }


def _ib_position(symbol, position=0.0, realized=0.0, unrealized=0.0,
                  avg_cost=0.0, market_price=0.0, market_value=0.0):
    return {
        "symbol": symbol, "position": position,
        "realizedPNL": realized, "unrealizedPNL": unrealized,
        "avgCost": avg_cost, "marketPrice": market_price,
        "marketValue": market_value,
    }


def _sweep_event(symbol, event):
    return {
        "symbol": symbol,
        "kind": "info" if "v19_27" in event else "warning",
        "content": f"Auto sweep for {symbol}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"event": event, "reason": event},
    }


def _reconcile_event(symbols):
    return {
        "kind": "info",
        "content": f"Auto-reconcile claimed {len(symbols)} positions",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "event": "auto_reconcile_at_boot",
            "symbols": list(symbols),
            "reason": "auto_reconcile_at_boot",
        },
    }


@pytest.fixture
def patch_db():
    from routers import diagnostics as diag_router
    fake = _FakeDB()
    original = diag_router._db
    diag_router._db = fake
    yield fake
    diag_router._db = original


# ─── Classifier unit tests (no endpoint) ────────────────────────────


def test_classifier_clean_when_ledgers_match():
    from routers.diagnostics import _classify_symbol_verdict
    bot_rows = [_trade("t1", "AAPL", realized_pnl=100)]
    verdict, _ = _classify_symbol_verdict(
        bot_rows=bot_rows, ib_pos=0, ib_realized=100,
        sweep_events=[], reconcile_events=[], reset_touched=False,
    )
    assert verdict == "clean"


def test_classifier_phantom_v31_when_oca_swept():
    from routers.diagnostics import _classify_symbol_verdict
    verdict, expl = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "LITE", realized_pnl=0)],
        ib_pos=0, ib_realized=112.66,
        sweep_events=[{"event": "phantom_v19_31_oca_closed_swept"}],
        reconcile_events=[], reset_touched=False,
    )
    assert verdict == "phantom_v31"
    assert "OCA bracket" in expl


def test_classifier_phantom_v27_when_leftover_swept():
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "OKLO")],
        ib_pos=0, ib_realized=0,
        sweep_events=[{"event": "phantom_v19_27_leftover_swept"}],
        reconcile_events=[], reset_touched=False,
    )
    assert verdict == "phantom_v27"


def test_classifier_unexplained_drift():
    """Bot says +$200 realized, IB says +$50 — gap > $5 threshold."""
    from routers.diagnostics import _classify_symbol_verdict
    verdict, expl = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "X", realized_pnl=200)],
        ib_pos=0, ib_realized=50,
        sweep_events=[], reconcile_events=[], reset_touched=False,
    )
    assert verdict == "unexplained_drift"
    assert "$+200" in expl or "+200" in expl
    assert "+50" in expl


def test_classifier_drift_within_tolerance_is_clean():
    """Bot $100.50, IB $100.00 — within $5 tolerance, should be clean."""
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "X", realized_pnl=100.50)],
        ib_pos=0, ib_realized=100.00,
        sweep_events=[], reconcile_events=[], reset_touched=False,
    )
    assert verdict == "clean"


def test_classifier_auto_reconciled_with_recon_event():
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "APH", status="open")],
        ib_pos=588, ib_realized=0,
        sweep_events=[],
        reconcile_events=[{"event": "auto_reconcile_at_boot"}],
        reset_touched=False,
    )
    assert verdict == "auto_reconciled"


def test_classifier_reset_orphaned():
    """Reset wiped row + IB still holds shares = orphaned."""
    from routers.diagnostics import _classify_symbol_verdict
    verdict, expl = _classify_symbol_verdict(
        bot_rows=[],  # row was wiped
        ib_pos=500,
        ib_realized=0,
        sweep_events=[],
        reconcile_events=[],
        reset_touched=True,
    )
    assert verdict == "reset_orphaned"
    assert "survival guard" in expl.lower() or "v19.31.1" in expl


def test_classifier_manual_or_external():
    """IB has shares, no bot row, no reconcile — TWS / external trade."""
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[],
        ib_pos=300, ib_realized=0,
        sweep_events=[], reconcile_events=[], reset_touched=False,
    )
    assert verdict == "manual_or_external"


def test_classifier_inactive_when_no_data():
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[], ib_pos=0, ib_realized=0,
        sweep_events=[], reconcile_events=[], reset_touched=False,
    )
    assert verdict == "inactive"


def test_classifier_phantom_v31_takes_precedence_over_drift():
    """When both phantom_v31 sweep AND drift would match, phantom wins
    (more specific explanation)."""
    from routers.diagnostics import _classify_symbol_verdict
    verdict, _ = _classify_symbol_verdict(
        bot_rows=[_trade("t1", "LITE", realized_pnl=0)],
        ib_pos=0, ib_realized=999,  # huge drift
        sweep_events=[{"event": "phantom_v19_31_oca_closed_swept"}],
        reconcile_events=[], reset_touched=False,
    )
    assert verdict == "phantom_v31"


# ─── Endpoint integration tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_clean_symbol(patch_db):
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [_trade("t1", "AAPL", realized_pnl=200)]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [_ib_position("AAPL", position=0, realized=200)],
    }]
    res = await get_trade_forensics(days=1)
    assert res["success"] is True
    syms = {s["symbol"]: s for s in res["symbols"]}
    assert "AAPL" in syms
    assert syms["AAPL"]["verdict"] == "clean"
    assert syms["AAPL"]["bot"]["closed_count"] == 1
    assert syms["AAPL"]["ib"]["realized_pnl_today"] == 200.0
    assert syms["AAPL"]["drift_usd"] == 0.0


@pytest.mark.asyncio
async def test_endpoint_phantom_v31_lite_scenario(patch_db):
    """The exact LITE scenario from operator's morning: bot tracked
    62sh short, IB OCA-closed, v19.31 sweep cleaned."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("lite-1", "LITE", direction="short", status="closed",
               realized_pnl=0, fill_price=992.37, exit_price=973.71),
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [_ib_position("LITE", position=0, realized=112.66)],
    }]
    patch_db.sentcom_thoughts.docs = [
        _sweep_event("LITE", "phantom_v19_31_oca_closed_swept"),
    ]
    res = await get_trade_forensics(days=1)
    syms = {s["symbol"]: s for s in res["symbols"]}
    assert syms["LITE"]["verdict"] == "phantom_v31"
    assert syms["LITE"]["sweep_count"] == 1
    # Timeline contains both bot events + the sweep
    timeline_kinds = [t["kind"] for t in syms["LITE"]["timeline"]]
    assert any("phantom_v19_31_oca_closed_swept" in k for k in timeline_kinds)


@pytest.mark.asyncio
async def test_endpoint_summary_by_verdict(patch_db):
    """Summary aggregates verdicts across all symbols."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("t1", "AAPL", realized_pnl=100),
        _trade("t2", "LITE", realized_pnl=0),
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [
            _ib_position("AAPL", position=0, realized=100),
            _ib_position("LITE", position=0, realized=112),
            _ib_position("MANUAL", position=300, realized=0),  # tws-trade
        ],
    }]
    patch_db.sentcom_thoughts.docs = [
        _sweep_event("LITE", "phantom_v19_31_oca_closed_swept"),
    ]
    res = await get_trade_forensics(days=1)
    by_verdict = res["summary"]["by_verdict"]
    assert by_verdict.get("clean") == 1
    assert by_verdict.get("phantom_v31") == 1
    assert by_verdict.get("manual_or_external") == 1


@pytest.mark.asyncio
async def test_endpoint_auto_reconcile_event_with_symbol_array(patch_db):
    """auto_reconcile_at_boot carries a metadata.symbols[] array — each
    symbol should be tagged auto_reconciled."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("t1", "APH", status="open", realized_pnl=0),
        _trade("t2", "STX", status="open", realized_pnl=0),
    ]
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [
            _ib_position("APH", position=588),
            _ib_position("STX", position=274),
        ],
    }]
    patch_db.sentcom_thoughts.docs = [
        _reconcile_event(["APH", "STX"]),
    ]
    res = await get_trade_forensics(days=1)
    syms = {s["symbol"]: s for s in res["symbols"]}
    assert syms["APH"]["verdict"] == "auto_reconciled"
    assert syms["STX"]["verdict"] == "auto_reconciled"
    assert syms["APH"]["reconcile_count"] >= 1


@pytest.mark.asyncio
async def test_endpoint_inactive_symbols_excluded(patch_db):
    """A symbol that's only in IB snapshot with 0 position and 0 PnL
    (e.g. a closed-yesterday symbol IB still echoes) shouldn't show
    in the symbols list — it's pure noise."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = []
    patch_db.ib_live_snapshot.docs = [{
        "_id": "current",
        "positions": [
            _ib_position("ZOMBIE", position=0, realized=0, unrealized=0),
        ],
    }]
    res = await get_trade_forensics(days=1)
    syms = [s["symbol"] for s in res["symbols"]]
    assert "ZOMBIE" not in syms
