"""
test_v322m_scalp_liquidity.py — regression tests for the 2026-06-11 AIQ/CZR
liquidity audit.

Findings the fixes close:
  1. CZR ORB *scalps* were emitted by the investment-tier scan with
     scan_tier=investment → the universal liquidity gate judged them
     against the $2M investment floor instead of the $50M intraday floor.
     → v322m: floor = STRICTEST-OF(scan_tier floor, trade_style floor).
  2. The same alerts carried rvol=0.0 (premarket, unmeasured) and nothing
     rejected the missing volume proof.
     → v322m: scalp/intraday-style alerts must prove rvol ≥ SCALP_MIN_RVOL
       (default 1.0); rvol <= 0 is FAIL-CLOSED.
  3. Dollar ADV alone can't see thin books on high-priced names/ETFs.
     → v322m: scalp/intraday-style alerts must also clear
       SCALP_MIN_SHARE_ADV (default 3M sh/day); unprovable → FAIL-CLOSED.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.enhanced_scanner import EnhancedBackgroundScanner as EnhancedScanner  # noqa: E402

FLOORS = dict(intraday=50_000_000, swing=10_000_000, investment=2_000_000)


def _fake_scanner(adv_dollar=200_000_000, share_adv=8_000_000,
                  min_rvol=1.0, min_share_adv=3_000_000):
    """Duck-typed `self` for the unbound gate methods — no heavy __init__."""
    fs = SimpleNamespace(
        _universal_liquidity_gate_enabled=True,
        _known_liquid_symbols=set(),
        _min_adv_intraday=FLOORS["intraday"],
        _min_adv_general=FLOORS["swing"],
        _min_adv_investment=FLOORS["investment"],
        _scalp_min_rvol=min_rvol,
        _scalp_min_share_adv=min_share_adv,
        db=None,
        drops=[],
    )

    async def _get_adv_from_cache(symbols):
        return {s: adv_dollar for s in symbols}

    async def _fetch_single_adv(symbol):
        return share_adv

    async def _get_share_adv_for_gate(symbol):
        return share_adv

    async def _emit_scanner_thought(**kw):
        fs.drops.append(kw)

    fs._get_adv_from_cache = _get_adv_from_cache
    fs._fetch_single_adv = _fetch_single_adv
    fs._get_share_adv_for_gate = _get_share_adv_for_gate
    fs._emit_scanner_thought = _emit_scanner_thought
    fs._liquidity_tier_floor = (
        lambda alert: EnhancedScanner._liquidity_tier_floor(fs, alert))
    return fs


def _alert(symbol="CZR", scan_tier="investment", trade_style="scalp",
           rvol=0.0, setup_type="orb"):
    return SimpleNamespace(
        symbol=symbol, scan_tier=scan_tier, trade_style=trade_style,
        rvol=rvol, setup_type=setup_type, direction="long",
        current_price=29.2, trigger_price=29.2, source=None,
    )


def _gate(fs, alert):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        EnhancedScanner._passes_universal_liquidity_gate(fs, alert))


# ── 1. strictest-of floor keying ────────────────────────────────────────────

def test_floor_scalp_style_beats_investment_tier():
    """The CZR hole: scan_tier=investment + trade_style=scalp must be judged
    against the INTRADAY $50M floor, not investment $2M."""
    fs = _fake_scanner()
    tier, floor = EnhancedScanner._liquidity_tier_floor(
        fs, _alert(scan_tier="investment", trade_style="scalp"))
    assert tier == "intraday" and floor == FLOORS["intraday"]


def test_floor_intraday_tier_beats_position_style():
    fs = _fake_scanner()
    tier, floor = EnhancedScanner._liquidity_tier_floor(
        fs, _alert(scan_tier="intraday", trade_style="position"))
    assert tier == "intraday" and floor == FLOORS["intraday"]


def test_floor_swing_pair_stays_swing():
    fs = _fake_scanner()
    tier, floor = EnhancedScanner._liquidity_tier_floor(
        fs, _alert(scan_tier="swing", trade_style="swing"))
    assert tier == "swing" and floor == FLOORS["swing"]


def test_floor_unknown_both_fails_strict():
    fs = _fake_scanner()
    tier, floor = EnhancedScanner._liquidity_tier_floor(
        fs, _alert(scan_tier="", trade_style=""))
    assert tier == "intraday" and floor == FLOORS["intraday"]


def test_floor_investment_only_keeps_investment():
    """A genuine investment-horizon alert keeps the $2M floor."""
    fs = _fake_scanner()
    tier, floor = EnhancedScanner._liquidity_tier_floor(
        fs, _alert(scan_tier="investment", trade_style="position"))
    assert tier == "investment" and floor == FLOORS["investment"]


# ── 2. RVOL proof for scalps ────────────────────────────────────────────────

def test_scalp_rvol_zero_fail_closed():
    """The CZR incident state: rvol=0.0 scalp must be REJECTED."""
    fs = _fake_scanner()
    assert _gate(fs, _alert(rvol=0.0)) is False


def test_scalp_rvol_below_floor_rejected():
    fs = _fake_scanner()
    assert _gate(fs, _alert(rvol=0.4)) is False


def test_scalp_rvol_proven_passes():
    fs = _fake_scanner()
    assert _gate(fs, _alert(rvol=1.68)) is True


def test_swing_style_ignores_rvol():
    """RVOL proof applies to scalp/intraday styles only."""
    fs = _fake_scanner()
    assert _gate(fs, _alert(scan_tier="swing", trade_style="swing",
                            rvol=0.0)) is True


def test_rvol_check_disabled_by_env_zero():
    fs = _fake_scanner(min_rvol=0)
    assert _gate(fs, _alert(rvol=0.0)) is True


# ── 3. share-ADV floor for scalps ───────────────────────────────────────────

def test_scalp_thin_share_adv_rejected():
    """$144M dollar ADV but only 2.2M sh/day (the AIQ shape) → REJECTED
    below the 3M share floor."""
    fs = _fake_scanner(adv_dollar=144_000_000, share_adv=2_200_000)
    assert _gate(fs, _alert(symbol="AIQ", scan_tier="intraday",
                            trade_style="intraday", rvol=1.68)) is False


def test_scalp_deep_share_adv_passes():
    fs = _fake_scanner(adv_dollar=218_000_000, share_adv=7_500_000)
    assert _gate(fs, _alert(symbol="CZR", scan_tier="intraday",
                            trade_style="scalp", rvol=1.5)) is True


def test_scalp_share_adv_unprovable_fail_closed():
    fs = _fake_scanner(share_adv=0)
    assert _gate(fs, _alert(rvol=1.5)) is False


def test_swing_style_ignores_share_adv():
    fs = _fake_scanner(adv_dollar=20_000_000, share_adv=500_000)
    assert _gate(fs, _alert(scan_tier="swing", trade_style="swing",
                            rvol=0.0)) is True


def test_share_adv_check_disabled_by_env_zero():
    fs = _fake_scanner(share_adv=100, min_share_adv=0)
    assert _gate(fs, _alert(rvol=1.5)) is True


# ── 4. dollar floor unchanged ───────────────────────────────────────────────

def test_dollar_floor_still_rejects():
    fs = _fake_scanner(adv_dollar=4_000_000, share_adv=9_000_000)
    assert _gate(fs, _alert(rvol=1.5)) is False


def test_known_liquid_bypass_unchanged():
    fs = _fake_scanner(adv_dollar=0, share_adv=0)
    fs._known_liquid_symbols = {"SPY"}
    assert _gate(fs, _alert(symbol="SPY", rvol=0.0)) is True
