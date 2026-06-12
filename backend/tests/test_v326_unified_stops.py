"""v326 — unified stop-rule SSOT + real-ATR audit tests."""
import asyncio
import sys
import py_compile
from pathlib import Path

import pytest


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "smart_stop_service.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services.smart_stop_service import SmartStopService, resolve_daily_atr  # noqa: E402
from services.opportunity_evaluator import OpportunityEvaluator  # noqa: E402

TB_SRC = (ROOT / "backend" / "routers" / "trading_bot.py").read_text()
SSS_SRC = (ROOT / "backend" / "services" / "smart_stop_service.py").read_text()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("UNIFIED_STOP_RULES_ENABLED", "INTRADAY_BRACKET_V2_ENABLED",
              "HSBG_ENABLED", "HSBG_SCALP_FRAC", "HSBG_INTRADAY_FRAC"):
        monkeypatch.delenv(k, raising=False)


# ── one source of truth for initial-stop multipliers ─────────────────

def test_unified_mult_matches_evaluator_table():
    svc = SmartStopService()
    for setup in ("momentum", "mean_reversion", "breakout", "gap_and_go", "scalp"):
        rules = svc._get_setup_rules(setup)
        expected = OpportunityEvaluator.SETUP_MULTIPLIERS.get(setup)
        if expected is not None:
            assert abs(rules.initial_stop_atr_mult - expected) < 1e-9, (
                f"{setup}: SmartStop {rules.initial_stop_atr_mult} != evaluator {expected}")


def test_divergence_fixed_mean_reversion(monkeypatch):
    # Legacy table said 2.5×; the LIVE evaluator table says 1.0×.
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "0")
    svc = SmartStopService()
    assert abs(svc._get_setup_rules("mean_reversion").initial_stop_atr_mult - 1.0) < 1e-9


def test_kill_switch_restores_legacy_table(monkeypatch):
    monkeypatch.setenv("INTRADAY_BRACKET_V2_ENABLED", "0")
    monkeypatch.setenv("UNIFIED_STOP_RULES_ENABLED", "0")
    svc = SmartStopService()
    assert abs(svc._get_setup_rules("mean_reversion").initial_stop_atr_mult - 2.5) < 1e-9


def test_shared_singletons_not_mutated():
    from services.smart_stop_service import SETUP_STOP_RULES
    before = SETUP_STOP_RULES["mean_reversion"].initial_stop_atr_mult
    svc = SmartStopService()
    svc._get_setup_rules("mean_reversion")
    assert SETUP_STOP_RULES["mean_reversion"].initial_stop_atr_mult == before


# ── HSBG horizon parity in calculate_intelligent_stop ────────────────

def _calc(svc, **kw):
    # entry deliberately NOT near a round number ($100 etc.) — the anti-
    # hunt logic correctly buffers stops near obvious levels, which would
    # cloud the pure geometry assertions below.
    defaults = dict(
        symbol="TESTX", entry_price=103.37, current_price=103.37,
        direction="long", setup_type="scalp", position_size=100, atr=3.0,
    )
    defaults.update(kw)
    return asyncio.run(svc.calculate_intelligent_stop(**defaults))


def test_scalp_suggestion_matches_live_geometry():
    # evaluator live geometry: 0.5 mult × 3.0 ATR × 0.39 frac = Δ0.585
    svc = SmartStopService()
    res = _calc(svc, trade_style="scalp")
    assert 102.70 <= res.stop_price <= 102.87, res.stop_price


def test_style_tightens_vs_no_style():
    svc = SmartStopService()
    with_style = _calc(svc, trade_style="scalp")
    without = _calc(svc)
    assert with_style.stop_price > without.stop_price  # tighter for long


def test_intraday_parity():
    # vwap_continuation: 1.25 mult × 3.0 × 0.35 = Δ1.3125
    svc = SmartStopService()
    res = _calc(svc, setup_type="vwap_continuation", trade_style="intraday")
    assert 101.95 <= res.stop_price <= 102.15, res.stop_price


def test_multiday_style_unscaled():
    svc = SmartStopService()
    res = _calc(svc, setup_type="breakout", trade_style="swing")
    # 1.5 × 3.0 = Δ4.5 → ~98.87 (round-number avoidance may nudge slightly)
    assert 98.50 <= res.stop_price <= 99.20, res.stop_price


# ── resolve_daily_atr ─────────────────────────────────────────────────

class _StubColl:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, *a, **k):
        return self._doc


class _StubDb:
    def __init__(self, doc):
        self._doc = doc

    def __getitem__(self, name):
        return _StubColl(self._doc)


def test_resolve_daily_atr_from_cache():
    atr, src = resolve_daily_atr(_StubDb({"atr_pct": 0.03}), "ABC", 100.0)
    assert abs(atr - 3.0) < 1e-9 and src == "symbol_adv_cache"


def test_resolve_daily_atr_implausible_cache_falls_back():
    atr, src = resolve_daily_atr(_StubDb({"atr_pct": 0.45}), "ABC", 100.0)
    assert abs(atr - 2.0) < 1e-9 and src == "fallback_2pct"


def test_resolve_daily_atr_no_db():
    atr, src = resolve_daily_atr(None, "ABC", 50.0)
    assert abs(atr - 1.0) < 1e-9 and src == "fallback_2pct"


# ── static assertions ─────────────────────────────────────────────────

def test_sources_compile():
    py_compile.compile(str(ROOT / "backend" / "services" / "smart_stop_service.py"), doraise=True)
    py_compile.compile(str(ROOT / "backend" / "routers" / "trading_bot.py"), doraise=True)


def test_fake_atr_eradicated_from_endpoints():
    assert "atr = entry_price * 0.02" not in TB_SRC
    assert TB_SRC.count("resolve_daily_atr(") >= 2


def test_audit_passes_trade_style():
    assert "trade_style=trade_style  # v326" in TB_SRC


def test_unified_mult_present():
    assert "_with_unified_mult" in SSS_SRC
    assert "UNIFIED_STOP_RULES_ENABLED" in SSS_SRC
