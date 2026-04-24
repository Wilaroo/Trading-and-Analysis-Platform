"""
Contract tests for:
    - Top Movers Tile (frontend component) — source-level invariants
    - Phase 4 Alpaca retirement — env-gated init + label change
    - AI Chat snapshot injection — chat_server consumes /api/live/symbol-snapshot

No live services exercised here; source-level parsing keeps tests fast and
deterministic. HTTP behaviour is covered separately by testing_agent.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ======================== Task 1: TopMoversTile ==========================

TILE_PATH = Path("/app/frontend/src/components/sentcom/v5/TopMoversTile.jsx")
V5_VIEW_PATH = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx")


def test_top_movers_tile_exists():
    assert TILE_PATH.exists(), "TopMoversTile.jsx must be present"


def test_top_movers_tile_reads_briefing_snapshot_endpoint():
    src = TILE_PATH.read_text(encoding="utf-8")
    assert "/api/live/briefing-snapshot" in src, (
        "TopMoversTile must hit /api/live/briefing-snapshot for data"
    )
    # 30s refresh cadence matches the RTH TTL in live_bar_cache
    assert "30_000" in src or "30000" in src, (
        "TopMoversTile should refresh every ~30s to match live_bar_cache RTH TTL"
    )


def test_top_movers_tile_filters_failed_snapshots():
    """Failed snapshots must be silently filtered — no point showing noise
    when pusher RPC is down (DataFreshnessBadge signals that already)."""
    src = TILE_PATH.read_text(encoding="utf-8")
    assert "s.success" in src and "filter" in src, (
        "TopMoversTile must filter out snapshots where success=false"
    )


def test_top_movers_tile_has_testids_on_symbols():
    src = TILE_PATH.read_text(encoding="utf-8")
    assert 'data-testid={`top-movers-symbol-${snap.symbol}`}' in src or \
           'data-testid="top-movers-tile"' in src, (
        "TopMoversTile must expose data-testid for automated click tests"
    )


def test_top_movers_tile_wired_into_v5_view():
    src = V5_VIEW_PATH.read_text(encoding="utf-8")
    assert "TopMoversTile" in src, (
        "TopMoversTile must be rendered from SentComV5View"
    )
    # Must be mounted below PipelineHUDV5 (visual hierarchy)
    idx_hud = src.find("<PipelineHUDV5")
    idx_tile = src.find("<TopMoversTile")
    assert 0 < idx_hud < idx_tile, (
        "TopMoversTile must render AFTER PipelineHUDV5 (visual hierarchy)"
    )


def test_top_movers_clicks_open_ticker_modal():
    """Symbols in the tile must open the EnhancedTickerModal via the same
    handleOpenTicker callback used elsewhere in V5."""
    view = V5_VIEW_PATH.read_text(encoding="utf-8")
    tile = TILE_PATH.read_text(encoding="utf-8")
    assert "onSelectSymbol={handleOpenTicker}" in view, (
        "V5View must wire handleOpenTicker as onSelectSymbol for TopMoversTile"
    )
    assert "onSelectSymbol?.(snap.symbol)" in tile, (
        "TopMoversTile must call onSelectSymbol with the clicked snap.symbol"
    )


# ==================== Task 2: Phase 4 Alpaca retirement ==================

SERVER_PATH = Path("/app/backend/server.py")
IB_ROUTER_PATH = Path("/app/backend/routers/ib.py")


def test_server_reads_enable_alpaca_fallback_env():
    src = SERVER_PATH.read_text(encoding="utf-8")
    assert 'ENABLE_ALPACA_FALLBACK' in src, (
        "server.py must read ENABLE_ALPACA_FALLBACK env var to gate Alpaca init"
    )


def test_server_default_is_alpaca_disabled():
    """Default (env unset) must disable Alpaca per Phase 4 plan."""
    src = SERVER_PATH.read_text(encoding="utf-8")
    # Must default to "false" when env var unset
    assert '"ENABLE_ALPACA_FALLBACK", "false"' in src, (
        "Phase 4 contract: default ENABLE_ALPACA_FALLBACK is 'false' (Alpaca retired)"
    )


def test_server_skips_init_alpaca_service_when_disabled():
    src = SERVER_PATH.read_text(encoding="utf-8")
    # init_alpaca_service() must live under the enabled branch, not unconditionally
    assert "if _alpaca_enabled:" in src, (
        "server.py must guard init_alpaca_service() behind the _alpaca_enabled flag"
    )
    # The disabled branch sets alpaca_service = None
    assert "alpaca_service = None" in src, (
        "When disabled, server.py must wire alpaca_service = None so downstream "
        "consumers take the IB-only path"
    )


def test_ib_analysis_label_no_longer_hardcoded_alpaca():
    """The /api/ib/analysis/{symbol} response used to hardcode
    data_source: 'Alpaca' — Phase 4 must swap this for an env-aware label."""
    src = IB_ROUTER_PATH.read_text(encoding="utf-8")
    # The bare string "Alpaca" should no longer be assigned as the sole source
    assert '"data_source"] = "Alpaca"\n' not in src, (
        "Phase 4: hardcoded 'data_source: Alpaca' label must be removed / gated"
    )
    # The new path must branch on the env flag
    assert 'ENABLE_ALPACA_FALLBACK' in src, (
        "ib.py analysis endpoint must check ENABLE_ALPACA_FALLBACK for labeling"
    )
    assert "IB shim" in src, (
        "When Alpaca is retired, the stock_service fallback must label "
        "itself as 'IB shim' (shim delegates to IBDataProvider)"
    )


# ==================== Task 3: AI Chat snapshot injection =================

CHAT_SERVER_PATH = Path("/app/backend/chat_server.py")


def test_chat_server_injects_live_symbol_snapshot():
    src = CHAT_SERVER_PATH.read_text(encoding="utf-8")
    assert "/api/live/symbol-snapshot/" in src, (
        "chat_server.py must call /api/live/symbol-snapshot/{sym} to inject "
        "fresh prices into the AI context"
    )


def test_chat_server_snapshot_block_is_bounded():
    """To avoid DoS-ing the pusher from the chat flow, the snapshot loop
    must cap symbols (≤10)."""
    src = CHAT_SERVER_PATH.read_text(encoding="utf-8")
    assert "_live_snapshot_targets[:10]" in src, (
        "chat_server snapshot injection must cap at 10 symbols per context build"
    )


def test_chat_server_snapshot_block_is_fault_tolerant():
    """AI chat must never crash just because the live-data service is
    unreachable — each snapshot call must be individually try/except'd."""
    src = CHAT_SERVER_PATH.read_text(encoding="utf-8")
    # The block has a per-symbol try/except and a surrounding try/except
    idx_block = src.find("Live Snapshots (Phase 3")
    assert idx_block > 0, "Chat server must add a 'Live Snapshots' context section"
    window = src[max(0, idx_block - 2000): idx_block + 500]
    assert "except Exception:" in window, (
        "Snapshot block must swallow per-symbol exceptions (fault tolerance)"
    )


def test_chat_server_includes_key_indices():
    """Snapshot block must always include SPY/QQQ/IWM/VIX regardless of positions."""
    src = CHAT_SERVER_PATH.read_text(encoding="utf-8")
    for idx in ('"SPY"', '"QQQ"', '"IWM"', '"VIX"'):
        assert idx in src, f"chat_server snapshot must include {idx} as default index"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
