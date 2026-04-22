"""
Tests for the P0 safety guardrails (services/safety_guardrails.py).

Verifies each of the five gates triggers cleanly and independently, plus
the kill-switch latch and config hot-patch. No FastAPI TestClient — we
call the SafetyGuardrails methods directly (httpx mismatch in this venv).
"""
from __future__ import annotations

import pytest

from services.safety_guardrails import (
    SafetyConfig, SafetyGuardrails, reset_for_tests, get_safety_guardrails,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    yield
    reset_for_tests()


# ─── factories ─────────────────────────────────────────────────────────────

def _guard(**cfg_overrides) -> SafetyGuardrails:
    cfg = SafetyConfig(
        max_daily_loss_usd=500,
        max_daily_loss_pct=2.0,
        max_positions=5,
        max_symbol_exposure_usd=10_000,
        max_total_exposure_pct=50.0,
        max_quote_age_seconds=10.0,
        enabled=True,
    )
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return SafetyGuardrails(cfg)


def _healthy_entry(**overrides):
    base = dict(
        symbol="SPY",
        side="long",
        notional_usd=1_000,
        account_equity=100_000,
        daily_realized_pnl=0,
        daily_unrealized_pnl=0,
        open_positions=[],
        last_quote_age_seconds=1.0,
    )
    base.update(overrides)
    return base


# ─── happy path ────────────────────────────────────────────────────────────

def test_healthy_entry_passes_all_gates():
    g = _guard()
    r = g.check_can_enter(**_healthy_entry())
    assert r.allowed is True
    assert r.check == "ok"
    assert r.details["open_count"] == 0


def test_safety_disabled_short_circuits_all_checks():
    """SAFETY_ENABLED=false → the guardrail is a no-op. Useful for tests /
    emergencies where the operator explicitly wants manual control."""
    g = _guard(enabled=False)
    r = g.check_can_enter(**_healthy_entry(daily_realized_pnl=-100_000))
    assert r.allowed is True
    assert r.check == "disabled"


# ─── gate 1: daily loss ────────────────────────────────────────────────────

def test_daily_loss_usd_limit_blocks_and_trips_kill_switch():
    g = _guard(max_daily_loss_usd=500, max_daily_loss_pct=99)  # usd is stricter
    r = g.check_can_enter(**_healthy_entry(daily_realized_pnl=-600))
    assert r.allowed is False
    assert r.check == "daily_loss"
    assert g.state.kill_switch_active is True
    assert "daily loss" in g.state.kill_switch_reason.lower()


def test_daily_loss_pct_limit_uses_stricter_of_usd_vs_pct():
    """On a $10k account, 2% = $200. That's stricter than a $500 USD cap,
    so a $250 loss should block even though $500 cap isn't hit."""
    g = _guard(max_daily_loss_usd=500, max_daily_loss_pct=2.0)
    r = g.check_can_enter(**_healthy_entry(
        account_equity=10_000,
        daily_realized_pnl=-250,  # breaches 2% ($200) even though not $500
    ))
    assert r.allowed is False
    assert r.check == "daily_loss"


def test_daily_loss_counts_unrealized_too():
    """If a position is underwater enough to trip the daily loss, the
    kill-switch fires BEFORE the position closes — critical for protecting
    paper-mode overnight holds."""
    g = _guard(max_daily_loss_usd=300, max_daily_loss_pct=99)
    r = g.check_can_enter(**_healthy_entry(
        daily_realized_pnl=0,
        daily_unrealized_pnl=-350,
    ))
    assert r.allowed is False
    assert r.check == "daily_loss"


# ─── gate 2: kill-switch latch ─────────────────────────────────────────────

def test_kill_switch_blocks_all_entries_after_trip():
    g = _guard()
    g.trip_kill_switch(reason="test trip")
    r = g.check_can_enter(**_healthy_entry())
    assert r.allowed is False
    assert r.check == "kill_switch"


def test_kill_switch_reset_unlocks_entries():
    g = _guard()
    g.trip_kill_switch("test")
    g.reset_kill_switch()
    r = g.check_can_enter(**_healthy_entry())
    assert r.allowed is True


def test_kill_switch_is_idempotent():
    """Tripping twice in a row must not move `tripped_at` or overwrite reason
    (so we don't lose the ORIGINAL reason after a secondary fire)."""
    g = _guard()
    g.trip_kill_switch("first cause")
    t1 = g.state.kill_switch_tripped_at
    g.trip_kill_switch("second cause")
    assert g.state.kill_switch_reason == "first cause"
    assert g.state.kill_switch_tripped_at == t1


# ─── gate 3: stale quote ───────────────────────────────────────────────────

def test_stale_quote_blocks_entry():
    g = _guard(max_quote_age_seconds=10.0)
    r = g.check_can_enter(**_healthy_entry(last_quote_age_seconds=15.0))
    assert r.allowed is False
    assert r.check == "stale_quote"
    assert r.details["age_seconds"] == 15.0


def test_missing_quote_age_is_allowed():
    """When the quote-age helper isn't installed in this deploy, the gate
    is bypassed (fail-open) — the caller passes `None`. Logged elsewhere."""
    g = _guard()
    r = g.check_can_enter(**_healthy_entry(last_quote_age_seconds=None))
    assert r.allowed is True


# ─── gate 4: max positions ─────────────────────────────────────────────────

def test_max_positions_cap_blocks():
    g = _guard(max_positions=3)
    positions = [
        {"symbol": f"S{i}", "notional_usd": 1000, "side": "long"} for i in range(3)
    ]
    r = g.check_can_enter(**_healthy_entry(open_positions=positions))
    assert r.allowed is False
    assert r.check == "max_positions"
    assert r.details["open_count"] == 3


# ─── gate 5: per-symbol exposure ───────────────────────────────────────────

def test_per_symbol_exposure_cap_blocks_stacking_same_symbol():
    g = _guard(max_symbol_exposure_usd=5_000)
    existing = [{"symbol": "NVDA", "notional_usd": 4_000, "side": "long"}]
    r = g.check_can_enter(**_healthy_entry(
        symbol="NVDA",
        notional_usd=2_000,    # 4k + 2k = 6k > 5k cap
        open_positions=existing,
    ))
    assert r.allowed is False
    assert r.check == "symbol_exposure"
    assert r.details["symbol"] == "NVDA"


def test_per_symbol_exposure_unaffected_by_other_symbols():
    g = _guard(max_symbol_exposure_usd=5_000)
    existing = [{"symbol": "AAPL", "notional_usd": 4_500, "side": "long"}]
    r = g.check_can_enter(**_healthy_entry(
        symbol="NVDA",
        notional_usd=2_000,
        open_positions=existing,
    ))
    assert r.allowed is True


# ─── gate 6: total exposure ────────────────────────────────────────────────

def test_total_exposure_pct_cap_blocks():
    g = _guard(max_total_exposure_pct=50.0)
    existing = [
        {"symbol": "AAPL", "notional_usd": 30_000, "side": "long"},
        {"symbol": "MSFT", "notional_usd": 15_000, "side": "long"},
    ]
    r = g.check_can_enter(**_healthy_entry(
        account_equity=100_000,
        notional_usd=10_000,   # 30 + 15 + 10 = 55k = 55% > 50%
        open_positions=existing,
    ))
    assert r.allowed is False
    assert r.check == "total_exposure"


# ─── config hot-patch ──────────────────────────────────────────────────────

def test_update_config_partial_patch_keeps_other_fields():
    g = _guard(max_positions=5, max_daily_loss_usd=500)
    effective = g.update_config({"max_positions": 3})
    assert effective["max_positions"] == 3
    assert effective["max_daily_loss_usd"] == 500.0


def test_update_config_ignores_unknown_keys():
    g = _guard()
    effective = g.update_config({"bogus_field": 42, "max_positions": 9})
    assert "bogus_field" not in effective
    assert effective["max_positions"] == 9


# ─── recent-checks ring buffer ─────────────────────────────────────────────

def test_recent_checks_ring_buffer_caps_at_20():
    g = _guard()
    for _ in range(30):
        g.check_can_enter(**_healthy_entry())
    assert len(g.state.last_checks) == 20
