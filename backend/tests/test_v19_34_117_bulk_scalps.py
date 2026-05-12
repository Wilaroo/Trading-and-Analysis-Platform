"""
Tests for v19.34.117 — POST /api/trading-bot/retune-stop/bulk-scalps.

Walks `_open_trades`, finds every scalp where
`abs(entry - stop) / atr > atr_threshold` (default 1.0), and either
previews or applies the v112-correct stop retune. Default
`dry_run=true` for safety — operator must explicitly opt-in to live
fire.

Tests assert:
  1. Default dry-run safety (no attach calls without explicit opt-in)
  2. Filter logic (only scalps with stop_distance > threshold match)
  3. Per-trade isolation (one failure doesn't abort the batch)
  4. Atomic safety re-uses (v111 cooldown, idempotency, ATR fallback)
  5. Response shape — scanned/matched/skipped/results/totals
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _mk_trade(*, trade_id, symbol, style="scalp", setup="nine_ema_scalp",
              entry=100.0, stop=97.0, direction=None):
    from services.trading_bot_service import TradeDirection
    return SimpleNamespace(
        id=trade_id,
        symbol=symbol,
        setup_type=setup,
        trade_style=style,
        direction=direction or TradeDirection.LONG,
        entry_price=entry,
        stop_price=stop,
        target_prices=[entry * 1.03],
        stop_order_id=f"legacy-stp-{trade_id}",
        target_order_id=f"legacy-tgt-{trade_id}",
    )


@pytest.fixture
def harness(monkeypatch):
    """Bot with a mixed book: legacy-wide scalp, fresh-tight scalp,
    intraday breakout, scalp w/o ATR data."""
    import routers.trading_bot as tb_router_module

    bot = MagicMock()
    # ATR per symbol (5m cache):
    bot._latest_atr_5m = {
        "SBUX": 2.0,   # → legacy-wide scalp (stop_distance 3.0 = 1.5×)
        "AAPL": 1.0,   # → fresh tight scalp (stop_distance 0.5 = 0.5×)
        "TSLA": 5.0,   # → intraday breakout (NOT a scalp — must be skipped)
        # NVDA intentionally missing → atr_unavailable skip path
    }
    bot._scanner = None
    bot.risk_params = SimpleNamespace(
        base_atr_multiplier=1.5, min_atr_multiplier=1.0, max_atr_multiplier=3.0,
    )
    bot._persist_trade = MagicMock(return_value=None)

    trades = {
        # WIDE legacy scalp — stop_distance / atr = 3.0/2.0 = 1.5× → match
        "SBUX": _mk_trade(trade_id="tr-wide-scalp", symbol="SBUX",
                          entry=100.0, stop=97.0),
        # Already-tight scalp — 0.5/1.0 = 0.5× → NO match
        "AAPL": _mk_trade(trade_id="tr-tight-scalp", symbol="AAPL",
                          entry=200.0, stop=199.5),
        # Intraday breakout (different style) → NO match regardless of width
        "TSLA": _mk_trade(trade_id="tr-intraday", symbol="TSLA",
                          style="intraday", setup="breakout",
                          entry=500.0, stop=490.0),
        # WIDE scalp on NVDA but ATR unavailable → skipped[]
        "NVDA": _mk_trade(trade_id="tr-no-atr", symbol="NVDA",
                          entry=400.0, stop=390.0),
    }
    bot._open_trades = trades

    executor = MagicMock()
    executor.attach_oca_stop_target = AsyncMock(return_value={
        "success": True,
        "stop_order_id": "new-stp",
        "target_order_id": "new-tgt",
        "oca_group": "OCA-X",
    })

    monkeypatch.setattr(tb_router_module, "_trading_bot", bot, raising=False)
    monkeypatch.setattr(tb_router_module, "_trade_executor", executor, raising=False)

    return {
        "bot": bot, "executor": executor, "trades": trades,
        "bulk": tb_router_module.retune_stop_bulk_scalps,
    }


def _call(fn, **payload):
    return asyncio.run(fn(payload or None))


# ---------------------------------------------------------------------------
# Default dry-run safety
# ---------------------------------------------------------------------------

class TestBulkSafetyDefaults:

    def test_default_is_dry_run(self, harness):
        """No explicit `dry_run` → endpoint MUST default to dry_run=True.
        Inverse of the single-endpoint default; the bulk surface
        warrants extra friction."""
        body = _call(harness["bulk"])
        assert body["dry_run"] is True
        # Attach NOT called on dry-run.
        harness["executor"].attach_oca_stop_target.assert_not_called()

    def test_empty_payload_treated_as_default(self, harness):
        """`None` / `{}` payload must not raise — empty body = default
        params + dry-run."""
        body = _call(harness["bulk"])
        assert body["success"] is True
        assert body["dry_run"] is True

    def test_explicit_dry_run_false_actually_fires(self, harness):
        body = _call(harness["bulk"], dry_run=False)
        assert body["dry_run"] is False
        # ONE attach call for the single wide scalp (SBUX).
        # The fresh-tight scalp and intraday don't match; NVDA is
        # skipped pre-attach for ATR.
        assert harness["executor"].attach_oca_stop_target.call_count == 1


# ---------------------------------------------------------------------------
# Filter logic — wide-scalp detection
# ---------------------------------------------------------------------------

class TestBulkFilterLogic:

    def test_matches_only_wide_scalps(self, harness):
        body = _call(harness["bulk"])
        assert body["scanned"] == 4
        # Only SBUX matches the wide-scalp filter.
        assert body["matched"] == 1
        assert len(body["results"]) == 1
        result = body["results"][0]
        assert result["trade_id"] == "tr-wide-scalp"
        assert result["symbol"] == "SBUX"
        # Wide-detection metadata included for V6 panel rendering.
        assert "current_multiplier" in result
        assert abs(result["current_multiplier"] - 1.5) < 1e-4
        assert "wide_by_x" in result
        assert abs(result["wide_by_x"] - 0.5) < 1e-4

    def test_intraday_trades_excluded_by_default(self, harness):
        """Default `trade_styles=['scalp']` MUST exclude non-scalps
        even when their stops are objectively wide."""
        body = _call(harness["bulk"])
        intraday_in_results = any(r.get("trade_id") == "tr-intraday" for r in body["results"])
        intraday_in_skipped = any(s.get("trade_id") == "tr-intraday" for s in body["skipped"])
        assert not intraday_in_results
        assert not intraday_in_skipped  # not even mentioned — not a match candidate

    def test_tight_scalp_silently_skipped(self, harness):
        """Already-tight scalps are NOT errors — they're just
        nothing-to-do. Must NOT appear in `skipped[]` (which is for
        operator-actionable failures only)."""
        body = _call(harness["bulk"])
        tight_in_skipped = any(s.get("trade_id") == "tr-tight-scalp" for s in body["skipped"])
        assert not tight_in_skipped

    def test_atr_unavailable_lands_in_skipped(self, harness):
        body = _call(harness["bulk"])
        atr_skip = [s for s in body["skipped"] if s.get("reason") == "atr_unavailable"]
        assert len(atr_skip) == 1
        assert atr_skip[0]["trade_id"] == "tr-no-atr"

    def test_custom_atr_threshold_loosens_filter(self, harness):
        """Lower threshold (e.g. 0.6×) catches the fresh-tight scalp
        too. Useful for an over-eager retune campaign."""
        body = _call(harness["bulk"], atr_threshold=0.4)
        matched_ids = {r["trade_id"] for r in body["results"]}
        # 0.5× tight scalp at AAPL > 0.4 threshold → now matches
        assert "tr-tight-scalp" in matched_ids
        assert "tr-wide-scalp" in matched_ids

    def test_custom_trade_styles_includes_intraday(self, harness):
        """Explicit `trade_styles=['scalp','intraday']` includes the
        intraday breakout even though it's not a scalp."""
        body = _call(harness["bulk"], trade_styles=["scalp", "intraday"])
        matched_ids = {r["trade_id"] for r in body["results"]}
        # Intraday breakout has stop_distance 10 / atr 5 = 2.0× → matches
        assert "tr-intraday" in matched_ids


# ---------------------------------------------------------------------------
# Per-trade isolation
# ---------------------------------------------------------------------------

class TestBulkPerTradeIsolation:

    def test_one_attach_exception_does_not_abort_batch(self, harness):
        """If `attach_oca_stop_target` raises on one trade, the rest
        of the matched trades MUST still process."""
        # Force a second wide-scalp candidate.
        from services.trading_bot_service import TradeDirection
        harness["bot"]._open_trades["MSFT"] = _mk_trade(
            trade_id="tr-also-wide", symbol="MSFT", entry=300.0, stop=290.0,
        )
        harness["bot"]._latest_atr_5m["MSFT"] = 4.0  # 10/4 = 2.5× → wide
        # First call raises, second succeeds.
        harness["executor"].attach_oca_stop_target.side_effect = [
            RuntimeError("IB connection dropped"),
            {"success": True, "stop_order_id": "ok", "target_order_id": "ok"},
        ]
        body = _call(harness["bulk"], dry_run=False)
        assert body["matched"] == 2
        # One success, one with attach_result.error
        successes = [r for r in body["results"] if r.get("success")]
        failures = [r for r in body["results"] if not r.get("success")]
        assert len(successes) == 1
        assert len(failures) == 1
        assert "IB connection dropped" in failures[0]["attach_result"]["error"]


# ---------------------------------------------------------------------------
# v111 cooldown integration
# ---------------------------------------------------------------------------

class TestBulkCooldownIntegration:

    def test_cooldown_skip_counted_as_success(self, harness):
        """v111 cooldown skip is a 'system working correctly' signal —
        must be counted as `tightened` (operator intent honored), not
        `failed`."""
        harness["executor"].attach_oca_stop_target.return_value = {
            "skipped": "bracket_attach_cooldown",
            "cooldown_remaining_s": 12.0,
        }
        body = _call(harness["bulk"], dry_run=False)
        assert body["totals"]["tightened"] == 1
        assert body["totals"]["failed"] == 0


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestBulkResponseShape:

    def test_top_level_keys_present(self, harness):
        body = _call(harness["bulk"])
        required = {"success", "dry_run", "scanned", "matched",
                    "skipped", "results", "totals", "params"}
        assert required.issubset(set(body.keys()))

    def test_totals_match_arrays(self, harness):
        body = _call(harness["bulk"])
        # Dry-run on the wide scalp → 1 tightened, 1 skipped (no-atr)
        assert body["totals"]["tightened"] + body["totals"]["failed"] == len(body["results"])
        assert body["totals"]["skipped"] == len(body["skipped"])

    def test_params_echo_back(self, harness):
        body = _call(harness["bulk"], atr_threshold=0.8, trade_styles=["scalp", "intraday"])
        assert body["params"]["atr_threshold"] == 0.8
        assert "intraday" in body["params"]["trade_styles"]


# ---------------------------------------------------------------------------
# Source-level wiring
# ---------------------------------------------------------------------------

class TestBulkRoutingContract:

    def test_endpoint_registered(self):
        src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
        assert '@router.post("/retune-stop/bulk-scalps")' in src

    def test_shares_helper_with_single_endpoint(self):
        """The bulk endpoint MUST delegate to `_retune_stop_core` so
        math + side-effects stay in sync with the single endpoint."""
        src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
        idx = src.find("async def retune_stop_bulk_scalps")
        window = src[idx:idx + 6000]
        assert "_retune_stop_core(trade" in window, (
            "Bulk endpoint MUST call `_retune_stop_core(trade, ...)` — "
            "otherwise it can drift from the single endpoint's math."
        )

    def test_default_dry_run_default_in_signature(self):
        """Source-grep that the bulk endpoint defaults to dry_run=True.
        Locks the safety invariant — a future refactor flipping the
        default would silently turn bulk-fire into live-fire."""
        src = (BACKEND_DIR / "routers" / "trading_bot.py").read_text()
        idx = src.find("async def retune_stop_bulk_scalps")
        window = src[idx:idx + 3000]
        assert 'payload.get("dry_run", True)' in window, (
            "bulk-scalps endpoint MUST default to dry_run=True — "
            "this is the operator-safety floor."
        )
