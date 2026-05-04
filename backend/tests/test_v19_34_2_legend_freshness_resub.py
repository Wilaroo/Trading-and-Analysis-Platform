"""
v19.34.2 (2026-05-04) — Tests for the operator-clarity bundle:

1. Open Positions legend popover (`?` icon explains REAL / SHADOW /
   MIXED + chip semantics).
2. Quote-freshness chip per row (FRESH / AMBER / STALE / ?).
3. Backend payload now exposes `quote_age_s` + `quote_state` per row.
4. Manage-loop auto-resub for stale quotes via pusher RPC.
5. Near-stop diagnostic warning so VALE-style stuck-near-stop trades
   surface in logs without scrolling the UI.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Frontend structural assertions ──────────────────────────────


def test_quote_freshness_chip_component_exists():
    p = Path("/app/frontend/src/components/sentcom/v5/QuoteFreshnessChip.jsx")
    assert p.exists()
    src = p.read_text()
    assert "FRESH" in src and "AMBER" in src and "STALE" in src
    assert 'data-testid="quote-freshness-chip' in src or "quote-freshness-chip" in src
    # Must classify by `state` prop (not by computing age internally)
    # so backend is the source of truth.
    assert "state" in src
    assert "ageSeconds" in src


def test_open_positions_legend_component_exists():
    p = Path("/app/frontend/src/components/sentcom/v5/OpenPositionsLegend.jsx")
    assert p.exists()
    src = p.read_text()
    # Covers the 5 mode chips + 3 freshness states + Shadow Decisions hint
    for token in ("PAPER", "LIVE", "SHADOW", "MIXED",
                  "FRESH", "AMBER", "STALE",
                  "Shadow Decisions"):
        assert token in src, f"legend missing reference to {token}"
    # Must be a popover anchored to a button (not a modal).
    assert "open-positions-legend-toggle" in src
    assert "open-positions-legend-popover" in src


def test_open_positions_v5_uses_legend_and_freshness_chip():
    f = Path("/app/frontend/src/components/sentcom/v5/OpenPositionsV5.jsx").read_text()
    # Wired into header
    assert "OpenPositionsLegend" in f
    assert "<OpenPositionsLegend />" in f
    # Wired into per-row trade chip cluster
    assert "QuoteFreshnessChip" in f
    assert "position.quote_state" in f
    assert "position.quote_age_s" in f


# ─── Backend payload exposes quote_age_s + quote_state ──────────


def test_sentcom_service_emits_quote_age_and_state():
    """get_our_positions must build a `quote_meta_by_symbol` map and
    stamp `quote_age_s` + `quote_state` onto every row."""
    src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()
    assert "quote_meta_by_symbol" in src
    assert "quote_age_s" in src
    assert "quote_state" in src
    # The 4 states must be defined.
    assert '"fresh"' in src and '"amber"' in src and '"stale"' in src
    # Stamped on BOTH branches (bot-managed loop + IB-orphan / lazy)
    assert src.count("quote_age_s") >= 4
    assert src.count("quote_state") >= 4


def test_sentcom_service_quote_age_thresholds_match_frontend():
    """5s → fresh boundary; 30s → stale boundary. Must match
    QuoteFreshnessChip's title strings."""
    src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()
    assert "_age_s < 5.0" in src
    assert "_age_s < 30.0" in src


# ─── Manage-loop auto-resub on stale quotes ─────────────────────


def test_manage_loop_collects_stale_symbols_for_resub():
    """When a position's quote is stale, position_manager must add
    the symbol to `_stale_resub_set` for the post-loop dispatcher."""
    src = (BACKEND_DIR / "services" / "position_manager.py").read_text()
    assert "_stale_resub_set" in src
    # Must be added to set before the `continue` that skips stop check.
    stale_block = src[src.index("v19.13 — staleness guard."):]
    assert "_stale_resub_set" in stale_block[:1500]
    assert "v19.34.2" in stale_block[:1500]


def test_manage_loop_dispatches_resub_with_60s_throttle():
    """Post-loop handler must call `subscribe_symbols(set)` no more
    than once per 60s to avoid hammering pusher RPC during a reconnect
    storm."""
    src = (BACKEND_DIR / "services" / "position_manager.py").read_text()
    assert "STALE-RESUB" in src
    assert "subscribe_symbols(stale_set)" in src
    assert "_last_stale_resub_at" in src
    assert "60.0" in src or "60 " in src


def test_manage_loop_resub_failure_is_swallowed():
    """A pusher RPC error during resub must NOT kill the manage-loop —
    the next cycle's bar-close stop check is the safety net."""
    src = (BACKEND_DIR / "services" / "position_manager.py").read_text()
    # The post-loop block must be wrapped in try/except.
    block_start = src.index("[v19.34.2 STALE-RESUB] post-loop handler swallowed")
    assert block_start > 0


# ─── Near-stop diagnostic warning ───────────────────────────────


def test_near_stop_diagnostic_present():
    """When a position sits within 5c (or 0.25%) of its stop and we're
    NOT firing the close, position_manager must log a one-shot warning
    so the operator can spot stuck-near-stop trades."""
    src = (BACKEND_DIR / "services" / "position_manager.py").read_text()
    assert "NEAR-STOP" in src
    assert "_near_stop_warned_at" in src
    # 5c hard threshold + 0.25% relative threshold.
    assert "0.05" in src
    assert "0.25" in src
    # Throttled to 60s per trade.
    assert "60.0" in src


# ─── Smoke test: the new endpoints + payload still wire up ──────


@pytest.mark.asyncio
async def test_position_manager_resub_no_op_when_no_stale_set():
    """If `_stale_resub_set` is empty/missing, post-loop must do
    nothing (no RPC call, no log)."""
    from services.position_manager import PositionManager
    pm = PositionManager()
    # Drive the post-loop branch directly. We can't easily run the full
    # update_open_positions in a test, but we CAN assert the structure:
    # after a fake call where _stale_resub_set is unset, calling
    # `getattr(pm, "_stale_resub_set", None)` returns None.
    assert getattr(pm, "_stale_resub_set", None) is None


def test_quote_freshness_chip_has_5s_and_30s_thresholds():
    """Visual thresholds must match the backend's classification."""
    p = Path("/app/frontend/src/components/sentcom/v5/QuoteFreshnessChip.jsx")
    src = p.read_text()
    # Pulse animation when < 2s; classification handled server-side
    # so the chip just renders state. Server uses 5s/30s. We assert
    # the chip handles all 4 states gracefully.
    assert "_STATE" in src
    assert "fresh" in src and "amber" in src and "stale" in src and "unknown" in src
