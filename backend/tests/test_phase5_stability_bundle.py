"""
Phase 5 — stability + ops bundle source-level contracts.
Covers:
  - PanelErrorBoundary class + reset handler
  - HealthChip polling + status colors
  - FreshnessInspector modal sections
  - CommandPalette global ⌘K handler
  - SentComV5View wiring (chip + inspector + palette + boundaries)
"""
from __future__ import annotations

from pathlib import Path

import pytest


BOUNDARY_SRC = Path("/app/frontend/src/components/sentcom/v5/PanelErrorBoundary.jsx").read_text(encoding="utf-8")
CHIP_SRC = Path("/app/frontend/src/components/sentcom/v5/HealthChip.jsx").read_text(encoding="utf-8")
INSPECTOR_SRC = Path("/app/frontend/src/components/sentcom/v5/FreshnessInspector.jsx").read_text(encoding="utf-8")
PALETTE_SRC = Path("/app/frontend/src/components/sentcom/v5/CommandPalette.jsx").read_text(encoding="utf-8")
V5_VIEW_SRC = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text(encoding="utf-8")


# -------------------- PanelErrorBoundary --------------------------------

def test_error_boundary_has_required_lifecycle_hooks():
    assert "class PanelErrorBoundary" in BOUNDARY_SRC
    assert "static getDerivedStateFromError" in BOUNDARY_SRC
    assert "componentDidCatch" in BOUNDARY_SRC
    # Reset handler resets state so child can re-mount fresh
    assert "reset = () =>" in BOUNDARY_SRC or "reset() {" in BOUNDARY_SRC
    assert 'data-testid={`panel-error-${label}`}' in BOUNDARY_SRC
    assert 'data-testid={`panel-error-reset-${label}`}' in BOUNDARY_SRC


# -------------------- HealthChip ----------------------------------------

def test_health_chip_polls_every_20s():
    assert "/api/system/health" in CHIP_SRC
    assert "POLL_MS = 20_000" in CHIP_SRC or "20_000" in CHIP_SRC


def test_health_chip_has_status_colors():
    for st in ("green", "yellow", "red"):
        assert f"'{st}'" in CHIP_SRC or f'"{st}"' in CHIP_SRC


def test_health_chip_has_testid():
    assert 'data-testid="health-chip"' in CHIP_SRC


def test_health_chip_opens_inspector_on_click():
    assert "onOpenInspector" in CHIP_SRC


# -------------------- FreshnessInspector --------------------------------

def test_inspector_aggregates_four_feeds():
    for path in (
        "/api/system/health",
        "/api/live/subscriptions",
        "/api/live/ttl-plan",
        "/api/live/pusher-rpc-health",
    ):
        assert path in INSPECTOR_SRC, f"Inspector must consume {path}"


def test_inspector_has_all_subsystems_section():
    for sec in (
        '"inspector-subsystems"',
        '"inspector-subs"',
        '"inspector-ttl"',
        '"inspector-rpc"',
    ):
        assert f'testid={sec}' in INSPECTOR_SRC, f"Missing inspector section: {sec}"


def test_inspector_parallel_fetch():
    """All four feeds must fetch via Promise.all to avoid waterfall latency."""
    assert "Promise.all" in INSPECTOR_SRC


def test_inspector_polls_when_open_and_stops_when_closed():
    assert "POLL_MS = 15_000" in INSPECTOR_SRC or "15_000" in INSPECTOR_SRC
    # Cleanup timer on close via return () => clearInterval
    assert "clearInterval" in INSPECTOR_SRC


# -------------------- CommandPalette ------------------------------------

def test_palette_has_mod_k_handler():
    assert "metaKey" in PALETTE_SRC and "ctrlKey" in PALETTE_SRC
    assert "'k'" in PALETTE_SRC and "'K'" in PALETTE_SRC


def test_palette_has_escape_handler():
    assert "'Escape'" in PALETTE_SRC


def test_palette_builds_corpus_from_subscriptions_and_watchlist():
    assert "/api/live/subscriptions" in PALETTE_SRC
    assert "/api/live/briefing-watchlist" in PALETTE_SRC


def test_palette_has_arrow_keys_and_enter():
    for key in ("'ArrowDown'", "'ArrowUp'", "'Enter'"):
        assert key in PALETTE_SRC


def test_palette_has_testids():
    assert 'data-testid="command-palette"' in PALETTE_SRC
    assert 'data-testid="command-palette-input"' in PALETTE_SRC


# -------------------- SentComV5View wiring ------------------------------

def test_v5_view_mounts_health_chip_in_hud():
    assert "HealthChip" in V5_VIEW_SRC
    # Must be inside rightExtra (HUD right side), not a free-floating component
    idx_right = V5_VIEW_SRC.find("rightExtra=")
    idx_chip = V5_VIEW_SRC.find("<HealthChip")
    assert 0 < idx_right < idx_chip, "HealthChip must be inside PipelineHUDV5 rightExtra"


def test_v5_view_mounts_command_palette():
    assert "<CommandPalette" in V5_VIEW_SRC
    assert "onSelectSymbol={handleOpenTicker}" in V5_VIEW_SRC


def test_v5_view_mounts_freshness_inspector_with_state():
    assert "inspectorOpen" in V5_VIEW_SRC
    assert "setInspectorOpen" in V5_VIEW_SRC
    assert "<FreshnessInspector" in V5_VIEW_SRC


def test_v5_view_wraps_panels_in_error_boundaries():
    """Each major V5 panel must be wrapped in PanelErrorBoundary so a
    crash in one can't take down the whole Command Center."""
    assert 'label="top-movers"' in V5_VIEW_SRC
    assert 'label="scanner"' in V5_VIEW_SRC
    assert 'label="chart"' in V5_VIEW_SRC
    assert 'label="briefings"' in V5_VIEW_SRC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
