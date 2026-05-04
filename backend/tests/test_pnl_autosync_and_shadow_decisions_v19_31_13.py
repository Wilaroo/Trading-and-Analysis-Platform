"""
v19.31.13 (2026-05-04) — tests for the realized-PnL auto-sync background
task + the new shadow-decisions endpoint + trade_type field surfacing
across day-tape / forensics / sentcom positions / closed_today.

Operator's "I shouldn't have to click ↻ Recalc per row" feedback after
v19.31.12 shipped the manual button. The 30s background loop scans for
status=closed AND closed_at within last 24h AND realized_pnl in (0, null,
missing), dedupes by symbol, and calls the same helper. Idempotent so a
healthy system pays nothing.

Plus the new /api/diagnostics/shadow-decisions endpoint that reads from
the existing shadow_decisions Mongo collection so the operator can see
"what would have happened on the trades I passed on" in the V5 UI.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Lightweight fake collection (mirrors the v19.31.12 pattern) ──


class _FakeColl:
    def __init__(self, docs: List[dict] | None = None):
        self.docs = list(docs or [])
        self.updates: List[Dict[str, Any]] = []

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
            actual = doc.get(k)
            if isinstance(v, dict):
                if "$gte" in v and not (actual is not None and actual >= v["$gte"]):
                    return False
                if "$lt" in v and not (actual is not None and actual < v["$lt"]):
                    return False
                if "$exists" in v:
                    has = k in doc
                    if has != v["$exists"]:
                        return False
                if "$in" in v and actual not in v["$in"]:
                    return False
                if "$nin" in v and actual in v["$nin"]:
                    return False
                if "$regex" in v:
                    import re as _re
                    flags = _re.IGNORECASE if v.get("$options", "").lower() == "i" else 0
                    if actual is None or not _re.search(v["$regex"], str(actual), flags):
                        return False
            elif v is None:
                if actual is not None:
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
        # Coerce limit when called via FastAPI Query default during direct
        # invocation in tests (Query objects aren't ints).
        if limit is not None and isinstance(limit, int):
            rows = rows[:limit]
        return iter(rows)

    def find_one(self, query=None, projection=None, sort=None):
        rows = list(self.find(query, projection, sort=sort))
        return rows[0] if rows else None

    def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                for k, v in update.get("$set", {}).items():
                    d[k] = v
                self.updates.append({"query": query, "update": update})
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})

    def count_documents(self, query=None):
        return sum(1 for _ in self.find(query or {}))


class _FakeDB:
    def __init__(self):
        self.bot_trades = _FakeColl()
        self.ib_live_snapshot = _FakeColl()
        self.shadow_decisions = _FakeColl()
        self.sentcom_thoughts = _FakeColl()
        self.bot_trades_reset_log = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


def _trade(id_, symbol, shares=100, realized_pnl=0, status="closed",
           hours_ago=2, **extra):
    base = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    out = {
        "id": id_,
        "symbol": symbol,
        "direction": "long",
        "shares": shares,
        "status": status,
        "executed_at": base,
        "closed_at": base if status == "closed" else None,
        "realized_pnl": realized_pnl,
    }
    out.update(extra)
    return out


def _shadow(id_, symbol, rec="proceed", was_executed=False,
            hours_ago=2, conf=72.0, would_pnl=0, **extra):
    base = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    out = {
        "id": id_,
        "symbol": symbol,
        "trigger_type": "trade_opportunity",
        "trigger_time": base,
        "combined_recommendation": rec,
        "confidence_score": conf,
        "was_executed": was_executed,
        "would_have_pnl": would_pnl,
        "debate_result": {"winner": "bull", "bull_score": 7, "bear_score": 3},
        "risk_assessment": {"recommendation": "PROCEED", "risk_score": 30},
        "timeseries_forecast": {"direction": "up", "probability": 0.62},
        "modules_used": ["debate", "risk", "timeseries"],
    }
    out.update(extra)
    return out


@pytest.fixture
def patch_db():
    from routers import diagnostics as diag
    fake = _FakeDB()
    original = diag._db
    diag._db = fake
    yield fake
    diag._db = original


# ─── Auto-recalc background loop wiring tests ─────────────────────


def test_autosync_loop_helper_is_extracted():
    """v19.31.13 — the recalc helper must be importable from
    routers.diagnostics so the trading_bot_service background task
    can call it without going through the FastAPI route layer."""
    from routers.diagnostics import _recalc_realized_pnl_for_symbol
    import asyncio
    assert asyncio.iscoroutinefunction(_recalc_realized_pnl_for_symbol)


def test_autosync_loop_wired_into_bot_start():
    """v19.31.13 — TradingBotService.start() must schedule the
    realized-PnL auto-sync background task."""
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    assert "_realized_pnl_autosync_loop" in src, (
        "auto-sync loop helper must exist in trading_bot_service.py"
    )
    assert "_pnl_autosync_task" in src, (
        "task must be stored on self for cancellation in stop()"
    )
    assert "REALIZED_PNL_AUTOSYNC_ENABLED" in src, (
        "env-var toggle must be respected so operator can opt out"
    )
    assert "_recalc_realized_pnl_for_symbol" in src, (
        "loop must call the extracted helper from routers.diagnostics"
    )


def test_autosync_loop_cancelled_on_stop():
    """v19.31.13 — auto-sync task must be cancelled when bot.stop() runs
    so it doesn't leak across hot-reloads."""
    src = (BACKEND_DIR / "services" / "trading_bot_service.py").read_text()
    # Assert the cancellation path exists in stop()
    assert (
        '_pnl_autosync_task' in src and
        'task.cancel()' in src
    ), "stop() must cancel the auto-sync task"


# ─── Shadow Decisions endpoint tests ──────────────────────────────


@pytest.mark.asyncio
async def test_shadow_decisions_returns_recent_rows(patch_db):
    """Endpoint returns shadow rows in the window with summary."""
    from routers.diagnostics import get_shadow_decisions
    patch_db.shadow_decisions.docs = [
        _shadow("s1", "AAPL", rec="proceed", was_executed=True),
        _shadow("s2", "MSFT", rec="pass", would_pnl=120.0),
        _shadow("s3", "TSLA", rec="reduce_size", was_executed=True),
        # Out-of-window — must be filtered.
        _shadow("s4", "OLD", hours_ago=72),
    ]
    res = await get_shadow_decisions(
        days=1, symbol=None, only_executed=False, only_passed=False, limit=500,
    )
    assert res["success"]
    syms = {r["symbol"] for r in res["rows"]}
    assert syms == {"AAPL", "MSFT", "TSLA"}
    assert res["summary"]["total"] == 3
    assert res["summary"]["executed_count"] == 2
    assert res["summary"]["not_executed_count"] == 1
    assert res["summary"]["by_recommendation"]["proceed"] == 1
    assert res["summary"]["by_recommendation"]["pass"] == 1
    assert res["summary"]["by_recommendation"]["reduce_size"] == 1


@pytest.mark.asyncio
async def test_shadow_decisions_symbol_filter(patch_db):
    from routers.diagnostics import get_shadow_decisions
    patch_db.shadow_decisions.docs = [
        _shadow("s1", "AAPL"),
        _shadow("s2", "MSFT"),
    ]
    res = await get_shadow_decisions(
        days=1, symbol="aapl", only_executed=False, only_passed=False, limit=500,
    )
    assert {r["symbol"] for r in res["rows"]} == {"AAPL"}


@pytest.mark.asyncio
async def test_shadow_decisions_only_executed_filter(patch_db):
    from routers.diagnostics import get_shadow_decisions
    patch_db.shadow_decisions.docs = [
        _shadow("s1", "AAPL", was_executed=True),
        _shadow("s2", "MSFT", was_executed=False),
    ]
    res = await get_shadow_decisions(
        days=1, symbol=None, only_executed=True, only_passed=False, limit=500,
    )
    assert len(res["rows"]) == 1
    assert res["rows"][0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_shadow_decisions_only_passed_filter(patch_db):
    from routers.diagnostics import get_shadow_decisions
    patch_db.shadow_decisions.docs = [
        _shadow("s1", "AAPL", rec="proceed"),
        _shadow("s2", "MSFT", rec="pass"),
        _shadow("s3", "TSLA", rec="reduce_size"),
    ]
    res = await get_shadow_decisions(
        days=1, symbol=None, only_executed=False, only_passed=True, limit=500,
    )
    syms = {r["symbol"] for r in res["rows"]}
    assert syms == {"AAPL"}, "only_passed=true must match combined_recommendation in (proceed|PROCEED|Proceed)"


@pytest.mark.asyncio
async def test_shadow_decisions_divergence_signal(patch_db):
    """When passed-trade would-have-pnl > $250 → ai_too_conservative."""
    from routers.diagnostics import get_shadow_decisions
    patch_db.shadow_decisions.docs = [
        _shadow("s1", "X", rec="pass", was_executed=False, would_pnl=300.0),
    ]
    res = await get_shadow_decisions(
        days=1, symbol=None, only_executed=False, only_passed=False, limit=500,
    )
    assert res["summary"]["divergence_signal"] == "ai_too_conservative"


@pytest.mark.asyncio
async def test_shadow_decisions_csv_pinned_columns(patch_db):
    """Operator's CSV scripts pin column ordering — must not drift."""
    from routers.diagnostics import get_shadow_decisions_csv
    patch_db.shadow_decisions.docs = [_shadow("s1", "AAPL")]
    csv = await get_shadow_decisions_csv(
        days=1, symbol=None, only_executed=False, only_passed=False,
    )
    header = csv.splitlines()[0]
    expected = (
        "trigger_time,symbol,combined_recommendation,confidence_score,"
        "was_executed,trade_id,would_have_pnl,would_have_r,actual_outcome,"
        "debate_winner,risk_recommendation,ts_direction,price_at_decision,"
        "market_regime,execution_reason,id"
    )
    assert header == expected, f"Header drift: {header}"


# ─── trade_type surfaces in day-tape / forensics / closed_today ───


@pytest.mark.asyncio
async def test_day_tape_surfaces_trade_type(patch_db):
    """Day Tape rows must surface trade_type so the V5 UI can chip it."""
    from routers.diagnostics import get_day_tape
    patch_db.bot_trades.docs = [
        _trade("t1", "AAPL", trade_type="paper",
               account_id_at_fill="DUN615665"),
        _trade("t2", "MSFT", trade_type="live",
               account_id_at_fill="U7654321"),
    ]
    res = await get_day_tape(days=1, direction=None, setup=None)
    by_sym = {r["symbol"]: r for r in res["rows"]}
    assert by_sym["AAPL"]["trade_type"] == "paper"
    assert by_sym["AAPL"]["account_id_at_fill"] == "DUN615665"
    assert by_sym["MSFT"]["trade_type"] == "live"


@pytest.mark.asyncio
async def test_day_tape_legacy_row_falls_back_to_unknown(patch_db):
    """Legacy rows without trade_type must default to 'unknown'."""
    from routers.diagnostics import get_day_tape
    patch_db.bot_trades.docs = [_trade("t1", "OLD")]
    res = await get_day_tape(days=1, direction=None, setup=None)
    assert res["rows"][0]["trade_type"] == "unknown"


@pytest.mark.asyncio
async def test_day_tape_csv_includes_trade_type_columns(patch_db):
    from routers.diagnostics import get_day_tape_csv
    patch_db.bot_trades.docs = [_trade("t1", "X", trade_type="live")]
    csv = await get_day_tape_csv(days=1, direction=None, setup=None)
    header = csv.splitlines()[0]
    assert "trade_type" in header.split(","), \
        "CSV header must include trade_type per v19.31.13"
    assert "account_id_at_fill" in header.split(",")


@pytest.mark.asyncio
async def test_forensics_dominant_trade_type_unanimous(patch_db):
    """All rows for a symbol same trade_type → that's the dominant."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("t1", "AAPL", trade_type="paper"),
        _trade("t2", "AAPL", trade_type="paper"),
    ]
    res = await get_trade_forensics(days=1)
    by_sym = {r["symbol"]: r for r in res["symbols"]}
    assert by_sym["AAPL"]["trade_type"] == "paper"


@pytest.mark.asyncio
async def test_forensics_dominant_trade_type_mixed(patch_db):
    """Symbol with rows of multiple concrete types → 'mixed'."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("t1", "AAPL", trade_type="paper"),
        _trade("t2", "AAPL", trade_type="live"),
    ]
    res = await get_trade_forensics(days=1)
    by_sym = {r["symbol"]: r for r in res["symbols"]}
    assert by_sym["AAPL"]["trade_type"] == "mixed"


@pytest.mark.asyncio
async def test_forensics_dominant_trade_type_filters_unknown(patch_db):
    """Mix of paper + unknown → 'paper' (unknown is ignored)."""
    from routers.diagnostics import get_trade_forensics
    patch_db.bot_trades.docs = [
        _trade("t1", "AAPL", trade_type="paper"),
        _trade("t2", "AAPL", trade_type="unknown"),
    ]
    res = await get_trade_forensics(days=1)
    by_sym = {r["symbol"]: r for r in res["symbols"]}
    assert by_sym["AAPL"]["trade_type"] == "paper"


# ─── BotTrade.to_dict carries trade_type ──────────────────────────


def test_bot_trade_to_dict_includes_trade_type():
    """v19.31.13 — every persisted/serialized bot_trade must carry the
    trade_type field so downstream consumers (sentcom_service, forensics)
    can read it."""
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    t = BotTrade(
        id="t1", symbol="X",
        direction=TradeDirection.LONG,
        status=TradeStatus.CLOSED,
        setup_type="momentum_breakout", timeframe="5min",
        quality_score=8, quality_grade="A",
        entry_price=100.0, current_price=101.0,
        stop_price=99.0, target_prices=[102.0],
        shares=100, risk_amount=100.0,
        potential_reward=200.0, risk_reward_ratio=2.0,
    )
    t.trade_type = "live"
    t.account_id_at_fill = "U1234567"
    d = t.to_dict()
    assert d["trade_type"] == "live"
    assert d["account_id_at_fill"] == "U1234567"


# ─── account_guard.classify_account_id paper/live detection ───────


def test_classify_du_prefix_is_paper():
    from services.account_guard import classify_account_id
    assert classify_account_id("DUN615665") == "paper"
    assert classify_account_id("dun615665") == "paper"
    assert classify_account_id("DU1234567") == "paper"


def test_classify_u_prefix_is_live():
    from services.account_guard import classify_account_id
    assert classify_account_id("U7654321") == "live"


def test_classify_paper_prefix_is_paper():
    from services.account_guard import classify_account_id
    assert classify_account_id("paperesw100000") == "paper"


def test_classify_empty_is_unknown():
    from services.account_guard import classify_account_id
    assert classify_account_id("") == "unknown"
    assert classify_account_id(None) == "unknown"
    assert classify_account_id("   ") == "unknown"


def test_account_mode_snapshot_shape():
    from services.account_guard import get_account_mode_snapshot
    snap = get_account_mode_snapshot("DU111", ib_connected=True)
    assert snap["detected_mode"] == "paper"
    assert snap["effective_mode"] == "paper"
    assert snap["current_account_id"] == "DU111"
    assert snap["ib_connected"] is True
