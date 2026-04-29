"""Source-level guards for the V5 shadow-decision badge wiring.

Why source-level: the JS-side normalisation logic (`_normalize`) and
the row-level chip dispatch can't run in pytest. Instead we pin the
contract via greps:

  - `useRecentShadowDecisions.js` polls the `/shadow/decisions` endpoint
  - The freshness window is 10 minutes
  - `UnifiedStreamV5` only renders the badge for `scan` / `brain` rows
    (not on fills/wins/losses where the AI vote is post-hoc noise)
  - `ShadowDecisionBadge` covers the three documented recommendations
    (`proceed` / `pass` / `reduce_size`)

Operator-flagged 2026-04-30 v11 enhancement (post-batch-finish): wire
shadow decisions to live alerts, not just aggregates.
"""

from __future__ import annotations

from pathlib import Path

HOOK_SRC = Path(
    "/app/frontend/src/components/sentcom/v5/useRecentShadowDecisions.js"
).read_text("utf-8")

BADGE_SRC = Path(
    "/app/frontend/src/components/sentcom/v5/ShadowDecisionBadge.jsx"
).read_text("utf-8")

STREAM_SRC = Path(
    "/app/frontend/src/components/sentcom/v5/UnifiedStreamV5.jsx"
).read_text("utf-8")


# ───────── Hook ─────────


def test_hook_polls_shadow_decisions_endpoint():
    assert "/api/ai-modules/shadow/decisions?limit=200" in HOOK_SRC


def test_hook_freshness_window_is_10_minutes():
    """Operator-confirmed window — pinned to fail loudly if changed."""
    assert "SHADOW_FRESHNESS_WINDOW_MS = 10 * 60 * 1000" in HOOK_SRC


def test_hook_polls_every_60s():
    assert "POLL_INTERVAL_MS = 60_000" in HOOK_SRC


def test_hook_normalizes_to_map_by_symbol():
    """`_normalize` must produce a Map keyed by upper-cased symbol so
    StreamRow can look up `sym.toUpperCase()` in O(1)."""
    assert "const out = new Map();" in HOOK_SRC
    assert "(d.symbol || '').toUpperCase()" in HOOK_SRC


def test_hook_keeps_most_recent_per_symbol():
    """When multiple decisions exist for the same symbol the highest
    `trigger_ms` must win — older entries are dropped."""
    assert "if (existing && existing.trigger_ms >= ts) continue;" in HOOK_SRC


# ───────── Badge ─────────


def test_badge_covers_three_recommendations():
    """The chip must visually represent every documented value
    `combined_recommendation` can take."""
    for rec in ("proceed", "pass", "reduce_size"):
        assert f"{rec}:" in BADGE_SRC, (
            f"ShadowDecisionBadge missing style entry for '{rec}' "
            f"recommendation — chip would render nothing for that case"
        )


def test_badge_label_palette_matches_lexicon():
    """TAKE / PASS / REDUCE — the operator's mental model."""
    assert "label: 'TAKE'" in BADGE_SRC
    assert "label: 'PASS'" in BADGE_SRC
    assert "label: 'REDUCE'" in BADGE_SRC


def test_badge_signals_executed_vs_diverged():
    """Filled circle (●) when the bot actually took the trade,
    hollow (○) when it diverged from the shadow vote."""
    assert "executed ? '●' : '○'" in BADGE_SRC


def test_badge_data_testid_per_recommendation():
    """Per-recommendation testid lets the testing agent assert
    exactly which chip variant rendered."""
    assert 'data-testid={`shadow-badge-${decision.recommendation}`}' in BADGE_SRC


def test_badge_marks_stale_signals_dimmer():
    """When ageMs > 5 minutes, the badge dims to indicate the shadow
    vote is older than the alert it's annotating."""
    assert "stale = typeof ageMs === 'number' && ageMs > 5 * 60 * 1000" in BADGE_SRC


# ───────── Stream wiring ─────────


def test_stream_imports_badge_and_hook():
    assert "from './ShadowDecisionBadge'" in STREAM_SRC
    assert "from './useRecentShadowDecisions'" in STREAM_SRC


def test_stream_only_badges_alert_like_rows():
    """Badges should ONLY render on `scan` / `brain` events (the
    alert-like ones the AI reasoned about). Rendering on fills/wins
    would be confusing post-hoc noise."""
    assert "(sev === 'scan' || sev === 'brain')" in STREAM_SRC


def test_stream_uses_freshness_window_for_age_gate():
    """Stream must use the constant from the hook — not hardcode
    a separate window — so they stay in sync if changed."""
    assert "ageMs <= SHADOW_FRESHNESS_WINDOW_MS" in STREAM_SRC


def test_stream_passes_shadow_map_to_each_row():
    assert "shadowBySymbol={shadowBySymbol}" in STREAM_SRC


def test_stream_uses_uppercase_symbol_lookup():
    """Hook keys by uppercase symbol — the lookup must match."""
    assert "shadowBySymbol.get(sym.toUpperCase())" in STREAM_SRC
