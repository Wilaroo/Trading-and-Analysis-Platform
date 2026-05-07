"""v19.34.39 — HUD account-chip consolidation regression tests.

The old design rendered TWO account pills side-by-side in the V5 HUD:
  • <AccountModeBadge />     (amber/yellow, /api/system/account-mode)
  • <AccountGuardChipV5 />   (green/red, /api/safety/status → account_guard)

Both displayed nearly the same fact (`PAPER · DUN615665`) which confused
operators ("why two pills with different colors saying the same thing?")
and weakened mismatch detection because the loud guard-chip alarm was
visually competing with the calmer informational badge.

v19.34.39 consolidates to ONE chip — the safety-enforcement-coupled
AccountGuardChipV5 — and ports the badge's three unique features
(SHADOW state, "next fill" mode forecast, IB-connected indicator) into
the chip's tooltip + render paths.

These tests pin the contract.
"""

from pathlib import Path

from services.account_guard import summarize_for_ui


# ─────────────────────────── backend ────────────────────────────────


def test_summarize_for_ui_includes_detected_mode():
    """The guard chip needs `detected_mode` to render the SHADOW path
    when the IB pusher is offline. Pre-v19.34.39 this only existed on
    the badge's `/api/system/account-mode` payload.
    """
    out = summarize_for_ui("DUN615665", ib_connected=True)
    assert "detected_mode" in out, "summarize_for_ui must include detected_mode"
    assert out["detected_mode"] == "paper"


def test_summarize_for_ui_includes_effective_mode():
    """The chip's tooltip shows `Next fill → LIVE/PAPER` to warn the
    operator about the mode the bot will stamp on the very next fill.
    """
    out = summarize_for_ui("U7654321", ib_connected=True)
    assert "effective_mode" in out, "summarize_for_ui must include effective_mode"
    assert out["effective_mode"] == "live"


def test_effective_mode_falls_back_to_active_when_pusher_offline():
    """When the pusher is offline (ib_connected=False) and IB has no
    snapshot to classify, effective_mode must fall back to env's
    `active_mode` so the operator's "next fill" forecast is still
    accurate even during a brief pusher outage.
    """
    # No account ID → classify_account_id returns "unknown"
    out = summarize_for_ui(None, ib_connected=False)
    # Falls back to env active_mode (paper by default)
    assert out["effective_mode"] in ("paper", "live"), (
        "effective_mode must always resolve to a concrete mode for stamping"
    )


# ─────────────────────────── frontend ───────────────────────────────


def test_account_mode_badge_removed_from_hud():
    """SentComV5View must no longer mount the deprecated AccountModeBadge."""
    src = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text("utf-8")
    # Strip JSX comments so our reasoning-comment about the removal isn't
    # mistaken for an actual mount.
    import re
    stripped = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.DOTALL)
    assert "<AccountModeBadge" not in stripped, (
        "SentComV5View still mounts the deprecated AccountModeBadge — the "
        "HUD now has duplicate account chips again."
    )
    assert "import AccountModeBadge" not in src, (
        "SentComV5View still imports the deprecated AccountModeBadge."
    )


def test_account_guard_chip_renders_shadow_state():
    """The guard chip must have a SHADOW render path for pusher-offline state."""
    src = Path("/app/frontend/src/components/sentcom/v5/SafetyV5.jsx").read_text("utf-8")
    assert "v5-chip-shadow" in src, (
        "AccountGuardChipV5 missing the v5-chip-shadow className — SHADOW "
        "state will fall through to the wrong render path."
    )
    assert "isShadow" in src, (
        "AccountGuardChipV5 missing the isShadow check derived from "
        "ib_connected + active_mode."
    )
    # The standby copy must mention the pusher being offline so the operator
    # knows WHY the bot is in standby.
    assert "Pusher offline" in src, (
        "AccountGuardChipV5 SHADOW path must explain why the bot is in standby."
    )


def test_account_guard_chip_tooltip_has_effective_mode():
    """The guard chip tooltip must include 'Next fill →' so the operator
    can spot a paper/live drift before the next trade fires.
    """
    src = Path("/app/frontend/src/components/sentcom/v5/SafetyV5.jsx").read_text("utf-8")
    assert "Next fill" in src, (
        "AccountGuardChipV5 tooltip must show 'Next fill →' (effective_mode) "
        "so operators see paper/live drift before it ruins a trade."
    )
    assert "Pusher" in src and "connected" in src and "offline" in src, (
        "AccountGuardChipV5 tooltip must show pusher connection state."
    )


def test_shadow_chip_css_present():
    """useV5Styles must define the .v5-chip-shadow class with sky coloring."""
    css = Path("/app/frontend/src/components/sentcom/v5/useV5Styles.js").read_text("utf-8")
    assert ".v5-chip-shadow" in css, (
        "useV5Styles is missing the .v5-chip-shadow CSS class."
    )
