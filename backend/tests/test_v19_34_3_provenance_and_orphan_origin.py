"""
v19.34.3 (2026-05-04) — Tests for the operator-discovered VALE bug:
the position_reconciler was silently materializing IB orphans with
default 2% SL / 2.0 R:R that didn't reflect the bot's real REJECT
verdicts on those same setups.

Phases shipped:
  A. Provenance — `entered_by` field on BotTrade ("bot_fired" |
     "reconciled_external" | "manual"). Prior verdicts pulled from
     sentcom_thoughts at reconcile time + persisted on the trade.
  B. Conflict warning — when ≥2 of last 3 verdicts were rejections,
     emit HIGH-priority `reconcile_prior_verdict_conflict_v19_34_3`
     stream event so the operator never silently inherits a setup
     the bot was actively rejecting.
  C. Smart synthetic SL/PT — reconciler prefers entry/stop/target
     numbers from the bot's last verdict over synthetic defaults
     when they're directionally consistent with the IB position.
     Stamp `synthetic_source: "last_verdict" | "default_pct"`.
  D. Forensic backfill — `GET /api/diagnostics/orphan-origin/{symbol}`
     returns bot_trades + reset_log + sentcom_thoughts + shadow_decisions
     timeline + verdict summary so the operator can answer "where
     did this position come from?".
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Lightweight fakes ─────────────────────────────────────────────


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _matches(self, doc, query):
        if not query:
            return True
        for k, v in query.items():
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
            else:
                if actual != v:
                    return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=None):
        rows = [d for d in self.docs if self._matches(d, query or {})]
        if sort:
            for k, direction in reversed(sort):
                rows.sort(key=lambda r: r.get(k) or "", reverse=direction == -1)
        if isinstance(limit, int):
            rows = rows[:limit]
        return iter(rows)

    def find_one(self, query=None, projection=None, sort=None):
        rows = list(self.find(query, projection, sort=sort))
        return rows[0] if rows else None

    def count_documents(self, query=None):
        return sum(1 for _ in self.find(query or {}))


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.bot_trades_reset_log = _FakeColl()
        self.sentcom_thoughts = _FakeColl()
        self.shadow_decisions = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


# ─── Phase A: BotTrade schema carries entered_by + provenance ──────


def test_bot_trade_schema_has_provenance_fields():
    """v19.34.3 BotTrade dataclass must define `entered_by`,
    `prior_verdicts`, `prior_verdict_conflict`, `synthetic_source`."""
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus,
    )
    t = BotTrade(
        id="t1", symbol="VALE",
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        setup_type="gap_fade", timeframe="5min",
        quality_score=60, quality_grade="B",
        entry_price=16.12, current_price=15.85,
        stop_price=15.80, target_prices=[16.76],
        shares=5179, risk_amount=1657.0,
        potential_reward=3313.0, risk_reward_ratio=2.0,
    )
    # Defaults
    assert t.entered_by == "bot_fired"
    assert t.prior_verdicts == []
    assert t.prior_verdict_conflict is False
    assert t.synthetic_source is None

    # to_dict surfaces all four
    d = t.to_dict()
    assert d["entered_by"] == "bot_fired"
    assert d["prior_verdicts"] == []
    assert d["prior_verdict_conflict"] is False
    assert d["synthetic_source"] is None


def test_trade_execution_stamps_entered_by_bot_fired():
    """`trade_execution.execute_trade` must stamp `entered_by="bot_fired"`
    on every fresh fill so we can distinguish bot-originated trades from
    reconciled orphans."""
    src = (BACKEND_DIR / "services" / "trade_execution.py").read_text()
    assert "v19.34.3" in src
    assert 'trade.entered_by = "bot_fired"' in src


# ─── Phase B+C: Reconciler integrates prior verdicts + smart stop ─


def test_reconciler_imports_smart_stop_logic():
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    # Provenance stamp
    assert 'trade.entered_by = "reconciled_external"' in src
    # Prior-verdict query
    assert "sentcom_thoughts" in src
    assert '"kind": "rejection"' in src
    # Smart synthetic SL/PT
    assert "use_smart_stop" in src
    assert "synthetic_source" in src
    # Conflict warning emit
    assert "reconcile_prior_verdict_conflict_v19_34_3" in src


def test_reconciler_persists_prior_verdicts_on_trade():
    """After reconcile, the BotTrade row must include the last 5
    rejection events as `prior_verdicts` so the UI can surface them."""
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    assert "trade.prior_verdicts = prior_verdicts" in src
    assert "trade.prior_verdict_conflict" in src


def test_reconciler_smart_stop_directionality_check():
    """Smart-stop logic must only override defaults when the verdict's
    stop/target are DIRECTIONALLY CONSISTENT with the IB position
    (LONG: stop < avg_cost < target; SHORT: target < avg_cost < stop)."""
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    # LONG check
    assert "_s < avg_cost < _t" in src
    # SHORT check
    assert "_t < avg_cost < _s" in src


def test_reconciler_emits_conflict_warning_with_severity_high():
    """When ≥2 of last 3 verdicts were rejections, the reconciler
    must emit `severity: "high"` so the V5 stream UI surfaces it
    in the prominent-warning lane."""
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    assert '"severity": "high"' in src
    assert '"warning"' in src


# ─── trading_bot_service rejection emit carries full ctx ──────────


def test_rejection_emit_carries_setup_math_for_reconcile():
    """The rejection event metadata must include entry_price, stop_price,
    primary_target, and rr_ratio so the position_reconciler can later
    use them as smart-stop inputs."""
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    # The whitelist of ctx keys forwarded to metadata
    for key in (
        "rr_ratio", "min_required",
        "entry_price", "stop_price", "primary_target",
    ):
        assert f'"{key}"' in src, f"rejection metadata missing key {key!r}"


# ─── Phase D: Forensic Orphan Origin endpoint ─────────────────────


@pytest.fixture
def patch_diag_db():
    from routers import diagnostics as diag
    fake = _FakeDB()
    original = diag._db
    diag._db = fake
    yield fake
    diag._db = original


@pytest.mark.asyncio
async def test_orphan_origin_returns_full_timeline(patch_diag_db):
    """Endpoint returns bot_trades + reset_log + thoughts + shadow + verdict."""
    from routers.diagnostics import get_orphan_origin
    base_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    patch_diag_db.bot_trades.docs = [{
        "id": "bt1", "symbol": "VALE", "executed_at": base_iso,
        "status": "open", "direction": "long", "shares": 5179,
        "fill_price": 16.12, "stop_price": 15.80, "target_prices": [16.76],
        "trade_type": "paper", "entered_by": "reconciled_external",
        "synthetic_source": "default_pct", "prior_verdict_conflict": True,
        "notes": "Reconciled from IB orphan",
    }]
    patch_diag_db.sentcom_thoughts.docs = [
        {"timestamp": base_iso, "symbol": "VALE", "kind": "rejection",
         "event": "rejection_rr_below_min", "text": "...",
         "metadata": {"setup_type": "gap_fade", "rr_ratio": 1.19,
                      "min_required": 1.5, "entry_price": 16.12,
                      "stop_price": 15.80, "primary_target": 16.76}},
    ]
    patch_diag_db.shadow_decisions.docs = []
    res = await get_orphan_origin("VALE", days=7)
    assert res["success"] is True
    assert res["symbol"] == "VALE"
    assert res["bot_trades_count"] == 1
    assert res["bot_trades"][0]["entered_by"] == "reconciled_external"
    assert res["bot_trades"][0]["prior_verdict_conflict"] is True
    assert len(res["thoughts"]) == 1
    assert res["thoughts"][0]["kind"] == "rejection"
    assert res["thoughts"][0]["metadata"]["rr_ratio"] == 1.19


@pytest.mark.asyncio
async def test_orphan_origin_verdict_summary_bot_disagreed(patch_diag_db):
    """When ≥80% of evaluations were rejections AND fires=0, the verdict
    summary should be 'bot_disagreed' — that's the VALE case."""
    from routers.diagnostics import get_orphan_origin
    base_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    # 5 evals, 5 rejections, 0 fires → bot_disagreed
    rejection_thoughts = [
        {"timestamp": base_iso, "symbol": "VALE", "kind": "rejection",
         "event": "rejection_rr_below_min", "metadata": {}}
        for _ in range(5)
    ]
    eval_thoughts = [
        {"timestamp": base_iso, "symbol": "VALE", "kind": "thought",
         "event": "evaluating_setup", "metadata": {}}
        for _ in range(5)
    ]
    patch_diag_db.sentcom_thoughts.docs = rejection_thoughts + eval_thoughts
    res = await get_orphan_origin("VALE", days=7)
    summary = res["verdict_summary"]
    assert summary["rejections"] == 5
    assert summary["evaluations"] == 5
    assert summary["fires"] == 0
    assert summary["verdict"] == "bot_disagreed"


@pytest.mark.asyncio
async def test_orphan_origin_verdict_summary_no_signal(patch_diag_db):
    """When evals=0 AND fires=0, verdict is 'no_signal' — manual fill
    or carryover from outside the lookback window."""
    from routers.diagnostics import get_orphan_origin
    res = await get_orphan_origin("VALE", days=7)
    assert res["verdict_summary"]["verdict"] == "no_signal"


@pytest.mark.asyncio
async def test_orphan_origin_verdict_summary_bot_agreed(patch_diag_db):
    """When the bot fired for this symbol within the window, verdict
    is 'bot_agreed' even if it later got swept."""
    from routers.diagnostics import get_orphan_origin
    base_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    patch_diag_db.sentcom_thoughts.docs = [
        {"timestamp": base_iso, "symbol": "VALE", "kind": "fire",
         "event": "trade_executed_long", "metadata": {}},
    ]
    res = await get_orphan_origin("VALE", days=7)
    assert res["verdict_summary"]["fires"] == 1
    assert res["verdict_summary"]["verdict"] == "bot_agreed"


@pytest.mark.asyncio
async def test_orphan_origin_400_on_empty_symbol(patch_diag_db):
    from routers.diagnostics import get_orphan_origin
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_orphan_origin("   ", days=7)
    assert exc.value.status_code == 400


# ─── Frontend wiring ──────────────────────────────────────────────


def test_open_positions_renders_provenance_chip():
    """OpenPositionsV5 must render a RECONCILED chip when
    entered_by==reconciled_external, plus a ⚠ CONFLICT chip when
    prior_verdict_conflict is True."""
    f = Path("/app/frontend/src/components/sentcom/v5/OpenPositionsV5.jsx").read_text()
    assert "reconciled_external" in f
    assert "RECONCILED" in f
    assert "CONFLICT" in f
    assert "prior_verdict_conflict" in f
    # Expanded view shows last 3 verdicts.
    assert "prior_verdicts" in f
    assert "Last" in f and "verdict(s)" in f


def test_open_positions_legend_documents_provenance_chips():
    """The `?` legend popover must explain the BOT / RECONCILED /
    CONFLICT chips."""
    f = Path("/app/frontend/src/components/sentcom/v5/OpenPositionsLegend.jsx").read_text()
    assert "_PROVENANCE_ROWS" in f
    assert "RECONCILED" in f
    assert "CONFLICT" in f


def test_sentcom_service_threads_provenance_into_payload():
    """Both branches (bot-managed + IB-orphan) must surface
    entered_by + prior_verdicts + prior_verdict_conflict + synthetic_source."""
    src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()
    for token in ("entered_by", "prior_verdict_conflict",
                  "prior_verdicts", "synthetic_source"):
        # Each appears at least 2× (bot branch + orphan branch).
        assert src.count(f'"{token}"') >= 2, f"{token} missing in one of the position payload branches"
