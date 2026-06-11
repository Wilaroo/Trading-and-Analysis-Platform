"""
test_v322r_leveraged_scalp_exclusion.py — regression tests for the 2026-06-12
EXT_SL stop-slippage autopsy fix.

Findings the fix closes:
  1. Stop slippage across the full population is BETTER than design
     (avg -0.80R); the entire excess tail is ~5 GAP-through events
     concentrated in geared daily products — ARMG (Leverage Shares 2X Long
     ARM) three times in the worst-12, -3.93R in a 6-minute hold. Geared
     ETPs gap through stops by construction → the fix is ENTRY-side.
     → v322r: scalp/intraday alerts refuse leveraged/inverse ETPs.
  2. ARMG was NOT in the static etf_classifier universe — single-stock 2x
     products list monthly, so a static set always lags.
     → v322r: IB contract longName/stockType heuristic as the safety net
       (`name_looks_leveraged`), fail-OPEN for common stocks.
  3. TQQQ/UVXY-class symbols live in `_known_liquid_symbols` and bypassed
     the universal gate entirely.
     → v322r: the exclusion runs BEFORE the known-liquid bypass; operator
       carve-outs via SCALP_LEVERAGED_ALLOW (default TQQQ,SQQQ,SOXL,SOXS).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.enhanced_scanner import EnhancedBackgroundScanner as EnhancedScanner  # noqa: E402
from services.etf_classifier import (  # noqa: E402
    classify_etf, is_known_leveraged, name_looks_leveraged,
)


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _fake_scanner(leveraged=False, lev_src="static_classifier",
                  block=True, allow=()):
    """Duck-typed `self` for the unbound gate methods — no heavy __init__."""
    fs = SimpleNamespace(
        _universal_liquidity_gate_enabled=True,
        _known_liquid_symbols=set(),
        _min_adv_intraday=50_000_000,
        _min_adv_general=10_000_000,
        _min_adv_investment=2_000_000,
        _scalp_min_rvol=1.0,
        _scalp_min_share_adv=3_000_000,
        _scalp_block_leveraged=block,
        _scalp_leveraged_allow=set(allow),
        _leverage_probe_cache={},
        db=None,
        drops=[],
    )

    async def _get_adv_from_cache(symbols):
        return {s: 200_000_000 for s in symbols}

    async def _fetch_single_adv(symbol):
        return 8_000_000

    async def _get_share_adv_for_gate(symbol):
        return 8_000_000

    async def _emit_scanner_thought(**kw):
        fs.drops.append(kw)

    async def _is_leveraged_instrument(symbol):
        return leveraged, lev_src

    fs._get_adv_from_cache = _get_adv_from_cache
    fs._fetch_single_adv = _fetch_single_adv
    fs._get_share_adv_for_gate = _get_share_adv_for_gate
    fs._emit_scanner_thought = _emit_scanner_thought
    fs._is_leveraged_instrument = _is_leveraged_instrument
    fs._liquidity_tier_floor = (
        lambda alert: EnhancedScanner._liquidity_tier_floor(fs, alert))
    return fs


def _alert(symbol="ARMG", trade_style="scalp", rvol=1.5,
           setup_type="orb", scan_tier="intraday"):
    return SimpleNamespace(
        symbol=symbol, scan_tier=scan_tier, trade_style=trade_style,
        rvol=rvol, setup_type=setup_type, direction="long",
        current_price=30.0, trigger_price=30.0, source=None,
    )


def _gate(fs, alert):
    return _run(EnhancedScanner._passes_universal_liquidity_gate(fs, alert))


# ── 1. static classifier coverage ───────────────────────────────────────────

def test_armg_now_classified_leveraged():
    """The autopsy instrument itself must be in the static universe."""
    assert classify_etf("ARMG") == "leveraged_inverse"
    assert is_known_leveraged("ARMG") is True


def test_other_v322r_additions_classified():
    for sym in ("AAPB", "FBL", "NVDX", "NVDQ", "TSLT", "BRKU"):
        assert classify_etf(sym) == "leveraged_inverse", sym


def test_common_stock_not_leveraged():
    assert classify_etf("AAPL") is None
    assert is_known_leveraged("ACMR") is False


# ── 2. longName/stockType heuristic (new-launch safety net) ─────────────────

def test_name_heuristic_catches_armg_long_name():
    assert name_looks_leveraged(
        "Leverage Shares 2X Long ARM Daily ETF", "ETF") is True


def test_name_heuristic_catches_direxion_bull():
    assert name_looks_leveraged(
        "Direxion Daily AAPL Bull 2X Shares", "ETF") is True


def test_name_heuristic_catches_proshares_ultrapro():
    assert name_looks_leveraged("ProShares UltraPro QQQ", "ETF") is True


def test_name_heuristic_catches_etn_inverse():
    assert name_looks_leveraged(
        "MicroSectors FANG+ Index -3X Inverse Leveraged ETN", "ETN") is True


def test_name_heuristic_never_tags_common_stock():
    """Ultra Clean Holdings / Ultragenyx are COMMON stocks — the heuristic
    must fail OPEN for non-fund stockTypes regardless of name."""
    assert name_looks_leveraged("Ultra Clean Holdings Inc", "COMMON") is False
    assert name_looks_leveraged(
        "Ultragenyx Pharmaceutical Inc", "COMMON") is False
    assert name_looks_leveraged("Direxion Bull Industries", "COMMON") is False


def test_name_heuristic_unknown_stock_type_fails_open():
    assert name_looks_leveraged("Some 2X Mystery Product", "") is False
    assert name_looks_leveraged("Some 2X Mystery Product", None) is False


def test_name_heuristic_plain_etf_passes():
    assert name_looks_leveraged("Invesco QQQ Trust Series 1", "ETF") is False
    assert name_looks_leveraged("iShares Russell 2000 ETF", "ETF") is False
    assert name_looks_leveraged("SPDR Gold Shares", "ETF") is False


# ── 3. gate behaviour ───────────────────────────────────────────────────────

def test_scalp_leveraged_blocked():
    """The ARMG incident state: a scalp alert on a geared product → REJECT."""
    fs = _fake_scanner(leveraged=True)
    assert _gate(fs, _alert(trade_style="scalp")) is False


def test_intraday_style_leveraged_blocked():
    fs = _fake_scanner(leveraged=True)
    assert _gate(fs, _alert(trade_style="intraday")) is False


def test_swing_leveraged_not_blocked_by_v322r():
    """Exclusion is scalp/intraday-scoped; swing entries pass this check
    (and continue to the regular dollar-floor checks)."""
    fs = _fake_scanner(leveraged=True)
    assert _gate(fs, _alert(trade_style="swing", scan_tier="swing")) is True


def test_scalp_non_leveraged_passes():
    fs = _fake_scanner(leveraged=False)
    assert _gate(fs, _alert(symbol="ACMR")) is True


def test_allow_list_carve_out_passes():
    """Operator carve-out (default TQQQ/SQQQ/SOXL/SOXS) skips the exclusion."""
    fs = _fake_scanner(leveraged=True, allow=("TQQQ",))
    assert _gate(fs, _alert(symbol="TQQQ")) is True


def test_block_disabled_by_env_passes():
    fs = _fake_scanner(leveraged=True, block=False)
    assert _gate(fs, _alert()) is True


def test_exclusion_beats_known_liquid_bypass():
    """THE ordering bug this guards against: UVXY-class symbols live in
    _known_liquid_symbols which returns True before any other check — the
    leveraged exclusion must fire FIRST."""
    fs = _fake_scanner(leveraged=True)
    fs._known_liquid_symbols = {"UVXY"}
    assert _gate(fs, _alert(symbol="UVXY")) is False


def test_known_liquid_bypass_intact_for_normal_stock():
    fs = _fake_scanner(leveraged=False)
    fs._known_liquid_symbols = {"SPY"}
    assert _gate(fs, _alert(symbol="SPY", trade_style="swing",
                            rvol=0.0)) is True


def test_drop_recorded_with_gate_name():
    fs = _fake_scanner(leveraged=True)
    _gate(fs, _alert())
    assert any(
        kw.get("filter") == "scalp_leveraged_exclusion" for kw in fs.drops)


# ── 4. _is_leveraged_instrument (real method) ───────────────────────────────

def _method_self():
    return SimpleNamespace(_leverage_probe_cache={})


def test_method_static_path_no_ib_needed():
    ok, src = _run(
        EnhancedScanner._is_leveraged_instrument(_method_self(), "ARMG"))
    assert ok is True and src == "static_classifier"


def test_method_fail_open_when_ib_unavailable(monkeypatch):
    import services.ib_direct_service as ibd
    monkeypatch.setattr(
        ibd, "get_ib_direct_service",
        lambda: SimpleNamespace(_connected=False))
    ok, src = _run(
        EnhancedScanner._is_leveraged_instrument(_method_self(), "ZZZT"))
    assert ok is False and src == "ib_unavailable"


def test_method_probe_path_detects_and_caches(monkeypatch):
    import services.ib_direct_service as ibd

    async def get_contract_profile(sym):
        return {"long_name": "Leverage Shares 2X Long ZZZT Daily ETF",
                "stock_type": "ETF"}

    fake_svc = SimpleNamespace(
        _connected=True, get_contract_profile=get_contract_profile)
    monkeypatch.setattr(ibd, "get_ib_direct_service", lambda: fake_svc)
    me = _method_self()
    ok, src = _run(EnhancedScanner._is_leveraged_instrument(me, "ZZZT"))
    assert ok is True and src == "ib_long_name"
    assert me._leverage_probe_cache["ZZZT"] is True
    # second call comes from cache (no IB roundtrip)
    ok2, src2 = _run(EnhancedScanner._is_leveraged_instrument(me, "ZZZT"))
    assert ok2 is True and src2 == "probe_cache"


def test_method_probe_path_common_stock_negative(monkeypatch):
    import services.ib_direct_service as ibd

    async def get_contract_profile(sym):
        return {"long_name": "Ultra Clean Holdings Inc",
                "stock_type": "COMMON"}

    fake_svc = SimpleNamespace(
        _connected=True, get_contract_profile=get_contract_profile)
    monkeypatch.setattr(ibd, "get_ib_direct_service", lambda: fake_svc)
    ok, src = _run(
        EnhancedScanner._is_leveraged_instrument(_method_self(), "UCTT"))
    assert ok is False and src == "ib_long_name"
