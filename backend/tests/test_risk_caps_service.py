"""
Tests for the risk-caps service — Option B from 2026-04-29 risk-param
unification. Locks in:

- Effective cap resolution (most-restrictive wins across sources).
- Human-readable conflict diagnostics for the UI.
- Edge cases: missing bot config, disabled kill switch, zero/None
  values that should be treated as "unset" rather than "0 cap".
"""

import os

import mongomock
import pytest

from services.risk_caps_service import compute_effective_risk_caps


@pytest.fixture
def db():
    """Fresh in-memory Mongo per test."""
    client = mongomock.MongoClient()
    return client["test_caps"]


@pytest.fixture(autouse=True)
def _reset_safety_env(monkeypatch):
    """Stamp deterministic safety-env defaults for every test so we
    don't accidentally pick up the operator's local env overrides."""
    monkeypatch.setenv("SAFETY_MAX_DAILY_LOSS_USD",     "500")
    monkeypatch.setenv("SAFETY_MAX_DAILY_LOSS_PCT",     "2.0")
    monkeypatch.setenv("SAFETY_MAX_POSITIONS",          "5")
    monkeypatch.setenv("SAFETY_MAX_SYMBOL_EXPOSURE_USD", "15000")
    monkeypatch.setenv("SAFETY_MAX_TOTAL_EXPOSURE_PCT", "60")
    monkeypatch.setenv("SAFETY_MAX_QUOTE_AGE_SEC",      "10")
    monkeypatch.setenv("SAFETY_ENABLED",                "true")


def _seed_bot_state(db, **risk_params):
    """Insert a synthetic bot_state doc with the given risk params."""
    db.bot_state.insert_one({"risk_params": risk_params})


# ────────────────────────── Sources surface ─────────────────────────


def test_sources_surface_all_three_categories(db):
    """The `sources` block should expose bot, safety, and sizer
    regardless of whether the bot has any config in Mongo."""
    out = compute_effective_risk_caps(db)
    assert "bot" in out["sources"]
    assert "safety" in out["sources"]
    assert "sizer" in out["sources"]
    assert "dynamic_risk" in out["sources"]


def test_sources_returns_safe_payload_when_db_none():
    """`db=None` shouldn't raise — the env-driven safety config still
    applies, the bot block is just empty."""
    out = compute_effective_risk_caps(None)
    assert out["effective"]["max_open_positions"] == 5  # safety only
    assert all(v is None for v in out["sources"]["bot"].values())


# ────────────────────────── Position cap resolution ─────────────────


def test_max_open_positions_safety_wins_when_stricter(db):
    """Operator's exact 2026-04-29 conflict: bot=7, safety=5 → 5 wins."""
    _seed_bot_state(db, max_open_positions=7, starting_capital=100000)
    out = compute_effective_risk_caps(db)
    assert out["effective"]["max_open_positions"] == 5
    assert any(
        "max_open_positions: bot=7 vs safety=5 → 5 wins" in c
        for c in out["conflicts"]
    )


def test_max_open_positions_bot_wins_when_stricter(db):
    """If bot is the stricter cap, bot wins (and no conflict diagnostic
    fires — the operator clearly intended the lower cap)."""
    _seed_bot_state(db, max_open_positions=3)
    out = compute_effective_risk_caps(db)
    assert out["effective"]["max_open_positions"] == 3
    # 3 vs safety 5 → bot wins. Conflict diagnostic still fires
    # because they're different (operator should know).
    assert any("max_open_positions" in c for c in out["conflicts"])


def test_max_open_positions_unset_falls_back_to_safety(db):
    """No bot config at all → safety cap is the binding cap."""
    out = compute_effective_risk_caps(db)
    assert out["effective"]["max_open_positions"] == 5


# ────────────────────────── Position pct resolution ─────────────────


def test_max_position_pct_sizer_wins_when_bot_aggressive(db):
    """Operator's 2026-04-29 conflict: bot=50%, sizer=10% → 10% wins."""
    _seed_bot_state(db, max_position_pct=50.0)
    out = compute_effective_risk_caps(db)
    assert out["effective"]["max_position_pct"] == 10.0
    assert any(
        "max_position_pct: bot=50.0% vs position_sizer=10.0%" in c
        for c in out["conflicts"]
    )


# ────────────────────────── Daily loss USD resolution ───────────────


def test_daily_loss_uses_bot_pct_when_set(db):
    """Bot can express daily-loss as %; service resolves it to USD via
    starting_capital."""
    _seed_bot_state(db, max_daily_loss_pct=1.0, starting_capital=100000)
    out = compute_effective_risk_caps(db)
    # bot computed = 1% × 100k = $1,000; safety = $500 → safety wins
    assert out["effective"]["max_daily_loss_usd"] == 500.0


def test_daily_loss_unset_emits_diagnostic(db):
    """When bot has neither absolute nor pct daily loss, conflict
    diagnostic flags it — the kill switch is the only failsafe."""
    _seed_bot_state(db, max_open_positions=5)  # no daily_loss fields
    out = compute_effective_risk_caps(db)
    assert any(
        "max_daily_loss is UNSET in bot config" in c
        for c in out["conflicts"]
    )


def test_daily_loss_zero_treated_as_unset(db):
    """Operator's 2026-04-29 config: max_daily_loss=0 — that should
    fall through to "unset", NOT bind anyone to a $0 cap."""
    _seed_bot_state(db, max_daily_loss=0, max_daily_loss_pct=0,
                    starting_capital=100000)
    out = compute_effective_risk_caps(db)
    assert any(
        "max_daily_loss is UNSET" in c for c in out["conflicts"]
    )
    # Effective USD cap falls through to safety only ($500).
    assert out["effective"]["max_daily_loss_usd"] == 500.0


def test_daily_loss_pct_picks_strictest_across_three_sources(db):
    """bot=1%, safety=2%, dynamic_risk=3% → 1% wins (bot is strictest)."""
    _seed_bot_state(db, max_daily_loss_pct=1.0, starting_capital=100000)
    out = compute_effective_risk_caps(db)
    assert out["effective"]["max_daily_loss_pct"] == 1.0
    assert any(
        "max_daily_loss_pct" in c and "bot=1.0%" in c
        for c in out["conflicts"]
    )


# ────────────────────────── Kill switch disabled ────────────────────


def test_kill_switch_disabled_emits_warning(db, monkeypatch):
    """When safety is fully disabled, the operator should see a clear
    ⚠️ in the conflicts list — bot caps are the only protection."""
    monkeypatch.setenv("SAFETY_ENABLED", "false")
    _seed_bot_state(db, max_open_positions=5, max_position_pct=10.0)
    out = compute_effective_risk_caps(db)
    assert any("kill switch is DISABLED" in c for c in out["conflicts"])


# ────────────────────────── End-to-end on operator's 2026-04-29 config ─


def test_operators_2026_04_29_config_reproduces_freshness_inspector_warns(db):
    """Replays the exact scenario the freshness inspector flagged this
    morning. The conflicts list should mirror the WARN strings the
    operator saw in the UI."""
    _seed_bot_state(
        db,
        max_risk_per_trade=2500.0,
        max_daily_loss=0.0,
        max_daily_loss_pct=1.0,
        max_open_positions=7,
        max_position_pct=50.0,
        min_risk_reward=2.5,
        starting_capital=100000.0,
    )
    out = compute_effective_risk_caps(db)

    # Effective caps the system actually enforces:
    assert out["effective"]["max_open_positions"] == 5
    assert out["effective"]["max_position_pct"] == 10.0
    assert out["effective"]["max_daily_loss_pct"] == 1.0
    # bot pct = 1% × 100k = $1,000 vs safety $500 → $500 wins
    assert out["effective"]["max_daily_loss_usd"] == 500.0
    # Bot-only caps pass through:
    assert out["effective"]["max_risk_per_trade"] == 2500.0
    assert out["effective"]["min_risk_reward"] == 2.5

    # Three conflict diagnostics expected, all matching the freshness
    # inspector's WARN message wording.
    conflicts_str = " ".join(out["conflicts"])
    assert "max_open_positions" in conflicts_str
    assert "max_position_pct" in conflicts_str
    # max_daily_loss_pct conflict expected (bot=1%, safety=2%, dynamic=3%)
    assert "max_daily_loss_pct" in conflicts_str
