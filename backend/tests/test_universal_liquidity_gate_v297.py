"""
v19.34.297 — Audit follow-up: UNIVERSAL LIQUIDITY GATE regression tests.

Root cause (DGCB illiquid scalp): the premarket ORB/gap generator
(`_scan_premarket_setups`) calls `_process_new_alert` directly, bypassing the
per-setup intraday dollar-volume gate (`enhanced_scanner.py` ~line 3605). Its
"tight 3-day range" ORB branch requires ZERO volume proof, so a thin name with
`avg_volume` missing / rvol=0 sailed straight to execution.

Fix: a single hard avg-DOLLAR-volume floor enforced at alert emission
(`_process_new_alert`) — the funnel EVERY alert path passes through. Tier-aware
floors (intraday $50M / swing $10M / investment $2M), FAIL CLOSED on unprovable
ADV, known-liquid bypass, env kill-switch.

These tests exercise `_passes_universal_liquidity_gate` + `_liquidity_tier_floor`
in isolation (no DB / IB / event loop pollution).
"""
import asyncio
import types

from services.enhanced_scanner import EnhancedBackgroundScanner


# ─────────────────────────── helpers / fakes ───────────────────────────

def _run(coro):
    """Run on a private loop, closed explicitly. Does NOT touch the global
    event-loop policy (so sibling test files that call
    `asyncio.get_event_loop()` are unaffected — avoids the cross-file
    event-loop-pollution harness fragility)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_scanner(*, enabled=True, cache_adv=None, fetch_share_adv=0):
    """Build a bare EnhancedScanner with ONLY the attrs the gate needs."""
    s = object.__new__(EnhancedBackgroundScanner)
    s._universal_liquidity_gate_enabled = enabled
    s._known_liquid_symbols = {"AAPL", "SPY", "MSFT"}
    # Canonical tier floors (mirror get_adv_thresholds()).
    s._min_adv_intraday = 50_000_000
    s._min_adv_general = 10_000_000
    s._min_adv_investment = 2_000_000
    s.db = None

    cache_adv = cache_adv or {}

    async def _fake_cache(symbols):
        return {sym: cache_adv[sym] for sym in symbols if sym in cache_adv}

    async def _fake_fetch(symbol):
        return fetch_share_adv

    async def _fake_emit(**kwargs):
        return None

    s._get_adv_from_cache = _fake_cache
    s._fetch_single_adv = _fake_fetch
    s._emit_scanner_thought = _fake_emit
    return s


def _alert(symbol="DGCB", *, scan_tier="intraday", trade_style="intraday",
           price=10.0, setup_type="orb", direction="long", source="premarket"):
    return types.SimpleNamespace(
        symbol=symbol, scan_tier=scan_tier, trade_style=trade_style,
        current_price=price, trigger_price=price, setup_type=setup_type,
        direction=direction, source=source,
    )


# ─────────────────────────── tier-floor resolution ───────────────────────────

def test_tier_floor_from_scan_tier():
    s = _make_scanner()
    assert s._liquidity_tier_floor(_alert(scan_tier="intraday")) == ("intraday", 50_000_000)
    assert s._liquidity_tier_floor(_alert(scan_tier="swing")) == ("swing", 10_000_000)
    assert s._liquidity_tier_floor(_alert(scan_tier="investment")) == ("investment", 2_000_000)


def test_tier_floor_infers_from_trade_style_when_scan_tier_missing():
    s = _make_scanner()
    a = _alert(scan_tier="", trade_style="position")
    assert s._liquidity_tier_floor(a) == ("investment", 2_000_000)
    a = _alert(scan_tier="", trade_style="swing")
    assert s._liquidity_tier_floor(a) == ("swing", 10_000_000)
    a = _alert(scan_tier="", trade_style="scalp")
    assert s._liquidity_tier_floor(a) == ("intraday", 50_000_000)


def test_tier_floor_unknown_falls_to_strictest():
    s = _make_scanner()
    a = _alert(scan_tier="", trade_style="")
    assert s._liquidity_tier_floor(a) == ("intraday", 50_000_000)


# ─────────────────────────── pass / reject behaviour ───────────────────────────

def test_intraday_above_floor_passes():
    s = _make_scanner(cache_adv={"NVDA": 60_000_000})
    assert _run(s._passes_universal_liquidity_gate(_alert("NVDA"))) is True


def test_intraday_below_floor_rejected():
    s = _make_scanner(cache_adv={"THIN": 30_000_000})
    assert _run(s._passes_universal_liquidity_gate(_alert("THIN"))) is False


def test_dgcb_unknown_adv_fail_closed():
    """The exact bug: ORB on a name with NO proven ADV must be REJECTED."""
    s = _make_scanner(cache_adv={}, fetch_share_adv=0)
    assert _run(s._passes_universal_liquidity_gate(_alert("DGCB"))) is False


def test_swing_floor_lower_than_intraday():
    # $15M clears the $10M swing floor but would FAIL the $50M intraday floor.
    s = _make_scanner(cache_adv={"SWNG": 15_000_000})
    assert _run(s._passes_universal_liquidity_gate(
        _alert("SWNG", scan_tier="swing", trade_style="swing"))) is True
    assert _run(s._passes_universal_liquidity_gate(
        _alert("SWNG", scan_tier="intraday", trade_style="intraday"))) is False


def test_investment_floor():
    s = _make_scanner(cache_adv={"INV": 3_000_000})
    assert _run(s._passes_universal_liquidity_gate(
        _alert("INV", scan_tier="investment", trade_style="position"))) is True
    s2 = _make_scanner(cache_adv={"INV": 1_000_000})
    assert _run(s2._passes_universal_liquidity_gate(
        _alert("INV", scan_tier="investment", trade_style="position"))) is False


def test_known_liquid_bypass():
    """A transient cache miss on AAPL must not block a legit signal."""
    s = _make_scanner(cache_adv={}, fetch_share_adv=0)
    assert _run(s._passes_universal_liquidity_gate(_alert("AAPL"))) is True


def test_kill_switch_disables_gate():
    s = _make_scanner(enabled=False, cache_adv={}, fetch_share_adv=0)
    assert _run(s._passes_universal_liquidity_gate(_alert("DGCB"))) is True


def test_fallback_share_compute_passes():
    """Cache miss but ib_historical shares × price clears the floor."""
    # 2,000,000 shares × $30 = $60M ≥ $50M intraday floor.
    s = _make_scanner(cache_adv={}, fetch_share_adv=2_000_000)
    assert _run(s._passes_universal_liquidity_gate(
        _alert("FALL", price=30.0))) is True
    # Same shares but $5 price → $10M < $50M intraday → reject.
    s2 = _make_scanner(cache_adv={}, fetch_share_adv=2_000_000)
    assert _run(s2._passes_universal_liquidity_gate(
        _alert("FALL", price=5.0))) is False


def test_reject_records_trade_drop(monkeypatch):
    captured = {}

    def _fake_record(db, *, gate, symbol=None, setup_type=None,
                     direction=None, reason=None, context=None):
        captured.update(gate=gate, symbol=symbol, context=context)

    monkeypatch.setattr(
        "services.trade_drop_recorder.record_trade_drop", _fake_record)
    s = _make_scanner(cache_adv={}, fetch_share_adv=0)
    assert _run(s._passes_universal_liquidity_gate(_alert("DGCB"))) is False
    assert captured["gate"] == "universal_liquidity_gate"
    assert captured["symbol"] == "DGCB"
    assert captured["context"]["fail_closed"] is True
    assert captured["context"]["tier"] == "intraday"


def test_empty_symbol_passes_through():
    s = _make_scanner()
    assert _run(s._passes_universal_liquidity_gate(_alert(""))) is True
