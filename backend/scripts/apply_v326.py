#!/usr/bin/env python3
"""
apply_v326.py — SmartStopService unification (one stop-rule SSOT) + real-ATR audits
====================================================================================
Audit finding (2026-06-12): SmartStopService — the 1,100-line "unified"
stop system — is only reachable via manual endpoints, and BOTH of its
trading_bot consumers (`/audit-stops`, `/fix-stop/{trade_id}`) feed it a
HARDCODED atr = entry × 2%. Worse, it carries its OWN initial-stop
multiplier table (SETUP_STOP_RULES / ARCHETYPE_STOP_RULES) that diverges
from the evaluator's LIVE SETUP_MULTIPLIERS (e.g. mean_reversion: 2.5×
there vs 1.0× live; momentum: 1.0× vs 1.5× live). Every audit
suggestion was fictional twice over.

WHAT CHANGES
------------
backend/services/smart_stop_service.py
  1. ONE SOURCE OF TRUTH for initial-stop sizing: `_get_setup_rules` now
     overrides `initial_stop_atr_mult` with the evaluator's
     SETUP_MULTIPLIERS resolution (exact → normalized → horizon
     fallback) on BOTH the archetype (BRACKET_V2) and legacy paths.
     Local tables keep owning trailing/BE/scale-out/runner shape.
     Copies via dataclasses.replace — shared singletons never mutated.
     Kill switch: UNIFIED_STOP_RULES_ENABLED=0.
  2. v325 HSBG horizon parity: `calculate_intelligent_stop` gains an
     optional `trade_style` param. When passed, scalp/intraday suggested
     stops shrink by the SAME √(hold/390) fraction live entries use; the
     legacy 2% min-stop constraint is swapped for the HSBG floors so it
     can't undo the scaling; the anti-hunt buffer scales too. Trailing/
     breakeven triggers scale automatically (they derive from the same
     initial mult). Callers that omit trade_style keep old behavior.
  3. NEW module helper `resolve_daily_atr(db, symbol, ref_price)` —
     canonical daily-ATR basis (symbol_adv_cache.atr_pct, plausibility
     0.3%–20% of price, 2% last resort) shared by the endpoints below.

backend/routers/trading_bot.py
  4. `/audit-stops` + `/fix-stop/{trade_id}`: fake `atr = entry × 0.02`
     replaced with `resolve_daily_atr(...)`; `trade_style` passed through
     so suggestions match v325 live geometry.
  5. Audit "too tight" check: was a flat 0.75×(fake)ATR — which would
     flag every properly-sized v325 scalp/intraday stop as CRITICAL.
     Now: tighter than HALF the canonical v325 stop distance = too tight.
     The "suboptimal" slack comparisons scale by the horizon fraction.

Also writes backend/tests/test_v326_unified_stops.py.
SAFE TO RUN MULTIPLE TIMES (idempotent).
REQUIRES v325 ALREADY APPLIED (uses its HSBG helpers — patcher verifies).

Run from repo root:  .venv/bin/python /tmp/apply_v326.py
Then: .venv/bin/python -m pytest backend/tests/test_v326_unified_stops.py backend/tests/test_v325_hsbg.py -q
Then: git add -A && git commit -m "v326: unified stop-rule SSOT + real-ATR stop audits" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

SSS_REL = "backend/services/smart_stop_service.py"
TB_REL = "backend/routers/trading_bot.py"
EVAL_REL = "backend/services/opportunity_evaluator.py"

SSS_CHUNKS = [
    # ── SS1: module helpers (resolve_daily_atr + eval shim) ───────────
    (
        "module_helpers",
        '''# ============================================================================
# MAIN SERVICE CLASS
# ============================================================================
''',
        '''# ============================================================================
# v326 — Unified stop-rule helpers
# ============================================================================
# `resolve_daily_atr` gives every SmartStop consumer the SAME canonical
# DAILY-ATR basis the evaluator's v325 geometry uses (the /audit-stops &
# /fix-stop endpoints previously hardcoded atr = entry × 2%, making every
# suggestion fictional). Preference order:
#   1. collector's symbol_adv_cache.atr_pct × ref_price (0.3%–20% window)
#   2. caller-provided fallback_atr if plausibly daily
#   3. 2% of price (last resort, flagged)

def resolve_daily_atr(db, symbol, ref_price, fallback_atr=None):
    """Returns (daily_atr_dollars, source_str)."""
    try:
        px = float(ref_price or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        return (float(fallback_atr) if fallback_atr else 0.0, "invalid_ref_price")
    if db is not None and symbol:
        try:
            doc = db["symbol_adv_cache"].find_one(
                {"symbol": str(symbol).upper()}, {"atr_pct": 1, "_id": 0})
            if doc and doc.get("atr_pct"):
                cand = float(doc["atr_pct"]) * px
                if 0.003 * px <= cand <= 0.20 * px:
                    return cand, "symbol_adv_cache"
        except Exception:
            pass
    try:
        if fallback_atr and 0.003 * px <= float(fallback_atr) <= 0.20 * px:
            return float(fallback_atr), "caller_fallback"
    except (TypeError, ValueError):
        pass
    return px * 0.02, "fallback_2pct"


class _EvalRiskShimRP:
    base_atr_multiplier = 1.5


class _EvalRiskShimBot:
    """Minimal bot stand-in so OpportunityEvaluator._resolve_atr_multiplier
    can run its fallback paths outside the live bot context."""
    risk_params = _EvalRiskShimRP()


_EVAL_RISK_SHIM = _EvalRiskShimBot()


# ============================================================================
# MAIN SERVICE CLASS
# ============================================================================
''',
    ),
    # ── SS2a: archetype path goes through the unified mult ────────────
    (
        "archetype_unified_mult",
        '''                arch = resolve_exit_archetype(setup_type)
                if arch in ARCHETYPE_STOP_RULES:
                    return ARCHETYPE_STOP_RULES[arch]
''',
        '''                arch = resolve_exit_archetype(setup_type)
                if arch in ARCHETYPE_STOP_RULES:
                    # v326 — archetype keeps owning the EXIT shape
                    # (trailing mode, scale-out, runner); the evaluator's
                    # SETUP_MULTIPLIERS owns the INITIAL stop distance.
                    return self._with_unified_mult(ARCHETYPE_STOP_RULES[arch], setup_type)
''',
    ),
    # ── SS2b: legacy path + the unified-mult method itself ────────────
    (
        "legacy_unified_mult",
        '''        normalized = setup_type.lower().replace(" ", "_").replace("-", "_")
        if normalized in self.setup_rules:
            return self.setup_rules[normalized]
        for key in self.setup_rules:
            if key in normalized or normalized in key:
                return self.setup_rules[key]
        return self.setup_rules["default"]
''',
        '''        normalized = setup_type.lower().replace(" ", "_").replace("-", "_")
        if normalized in self.setup_rules:
            return self._with_unified_mult(self.setup_rules[normalized], setup_type)
        for key in self.setup_rules:
            if key in normalized or normalized in key:
                return self._with_unified_mult(self.setup_rules[key], setup_type)
        return self._with_unified_mult(self.setup_rules["default"], setup_type)

    def _with_unified_mult(self, rules: SetupStopRules, setup_type: str) -> SetupStopRules:
        """v326 — ONE source of truth for initial-stop sizing.

        The evaluator's SETUP_MULTIPLIERS (the LIVE, v112-tuned ~80-setup
        table that actually sizes every bot entry) overrides the local
        tables' `initial_stop_atr_mult`, so /audit-stops, /fix-stop and
        the smart-stops API can never disagree with live trade geometry
        again (pre-fix divergence: mean_reversion 2.5× here vs 1.0× live,
        momentum 1.0× vs 1.5× live). Local tables keep owning trailing /
        breakeven / scale-out / runner behavior.

        Returns a COPY via dataclasses.replace — the shared rule
        singletons are never mutated. UNIFIED_STOP_RULES_ENABLED=0
        reverts to the legacy split tables.
        """
        import os
        if str(os.environ.get("UNIFIED_STOP_RULES_ENABLED", "1")).strip().lower() in (
            "0", "false", "no", "off",
        ):
            return rules
        try:
            from dataclasses import replace
            from services.opportunity_evaluator import OpportunityEvaluator
            mult, _is_scalp, _resolution = OpportunityEvaluator._resolve_atr_multiplier(
                setup_type, _EVAL_RISK_SHIM,
            )
            if mult and float(mult) > 0 and abs(float(mult) - rules.initial_stop_atr_mult) > 1e-9:
                return replace(rules, initial_stop_atr_mult=float(mult))
        except Exception as exc:
            logger.debug("v326 unified-mult resolve failed for %s: %s", setup_type, exc)
        return rules
''',
    ),
    # ── SS3a: calculate_intelligent_stop signature ─────────────────────
    (
        "intelligent_stop_signature",
        '''        max_risk_dollars: float = None,
        max_risk_percent: float = 0.02
    ) -> SmartStopResult:
''',
        '''        max_risk_dollars: float = None,
        max_risk_percent: float = 0.02,
        trade_style: str = None
    ) -> SmartStopResult:
''',
    ),
    # ── SS3b: HSBG horizon parity ──────────────────────────────────────
    (
        "hsbg_parity",
        '''        # 1. Get setup rules
        rules = self._get_setup_rules(setup_type)
        factors.append(f"Setup: {rules.setup_type}")
''',
        '''        # 1. Get setup rules
        rules = self._get_setup_rules(setup_type)
        factors.append(f"Setup: {rules.setup_type}")

        # v326 — v325 HSBG horizon parity. When the caller passes
        # trade_style, scalp/intraday suggested stops shrink by the SAME
        # √(hold/390) fraction live entries use, and the legacy 2%
        # min-stop constraint is swapped for the HSBG floors so it can't
        # undo the scaling. Trailing/breakeven triggers scale
        # automatically (they derive from initial_stop_atr_mult).
        # Callers that omit trade_style get pre-v326 daily-basis behavior.
        hsbg_frac = 1.0
        if trade_style is not None:
            try:
                from dataclasses import replace as _dc_replace
                from services.opportunity_evaluator import OpportunityEvaluator as _OE
                _geo_style = _OE._resolve_geometry_style(
                    {"trade_style": trade_style}, setup_type)
                hsbg_frac = _OE._hsbg_horizon_frac(_geo_style)
                if hsbg_frac < 1.0:
                    rules = _dc_replace(
                        rules,
                        initial_stop_atr_mult=rules.initial_stop_atr_mult * hsbg_frac,
                        min_stop_pct=_OE._hsbg_min_stop_pct(_geo_style),
                        max_stop_pct=max(0.005, rules.max_stop_pct * hsbg_frac),
                    )
                    factors.append(f"HSBG horizon ×{hsbg_frac:.2f} ({_geo_style})")
            except Exception as _hsbg_exc:
                logger.debug("v326 HSBG parity skipped: %s", _hsbg_exc)
                hsbg_frac = 1.0
''',
    ),
    # ── SS3c: anti-hunt buffer scales with the horizon ────────────────
    (
        "anti_hunt_buffer_scaled",
        '''        if hunt_risk['level'] == 'HIGH':
            anti_hunt_buffer = atr * self.config.anti_hunt_extra_atr
''',
        '''        if hunt_risk['level'] == 'HIGH':
            # v326 — buffer scales with the horizon fraction so a daily-
            # ATR sized buffer can't dwarf a horizon-scaled scalp stop.
            anti_hunt_buffer = atr * self.config.anti_hunt_extra_atr * hsbg_frac
''',
    ),
]

TB_CHUNKS = [
    # ── TB1: /audit-stops real ATR ─────────────────────────────────────
    (
        "audit_real_atr",
        '''            # Estimate ATR as 2% of price if not available
            atr = entry_price * 0.02
''',
        '''            # v326 — REAL daily ATR (was: hardcoded 2%-of-price guess
            # that made every audit suggestion fictional). Same canonical
            # basis as the evaluator's v325 HSBG geometry.
            from services.smart_stop_service import resolve_daily_atr
            _db_v326 = getattr(_trading_bot, "_db", None)
            if _db_v326 is None:
                _db_v326 = getattr(_trading_bot, "db", None)
            atr, _atr_source = resolve_daily_atr(_db_v326, symbol, entry_price)
            trade_style = trade.get('trade_style') or ''
''',
    ),
    # ── TB2: /audit-stops passes trade_style ──────────────────────────
    (
        "audit_trade_style",
        '''                analysis = await smart_stop.calculate_intelligent_stop(
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    direction=direction,
                    setup_type=setup_type,
                    position_size=trade.get('shares', 100),
                    atr=atr
                )
''',
        '''                analysis = await smart_stop.calculate_intelligent_stop(
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    direction=direction,
                    setup_type=setup_type,
                    position_size=trade.get('shares', 100),
                    atr=atr,
                    trade_style=trade_style  # v326 — HSBG horizon parity
                )
''',
    ),
    # ── TB3: too-tight check vs the canonical v325 stop ───────────────
    (
        "audit_too_tight_canonical",
        '''                # 1. Check if stop is too tight
                stop_distance = abs(stop_price - entry_price)
                min_distance = atr * 0.75  # Minimum 0.75 ATR
''',
        '''                # 1. Check if stop is too tight — v326: measured against
                # HALF the canonical (v325 horizon-scaled) stop distance.
                # The old flat 0.75×ATR floor (on a daily ATR) would flag
                # every properly-sized scalp/intraday stop as CRITICAL.
                stop_distance = abs(stop_price - entry_price)
                from services.opportunity_evaluator import OpportunityEvaluator as _OE_v326
                from services.trading_bot_service import TradeDirection as _TD_v326
                _dir_enum = _TD_v326.LONG if str(direction).lower() == 'long' else _TD_v326.SHORT
                try:
                    _canon_stop = _OE_v326().calculate_atr_based_stop(
                        float(entry_price), _dir_enum, float(atr), setup_type,
                        _trading_bot, trade_style=trade_style,
                    )
                    _canon_dist = abs(float(entry_price) - float(_canon_stop))
                except Exception:
                    _canon_dist = atr * 0.75
                _hsbg_frac = _OE_v326._hsbg_horizon_frac(
                    _OE_v326._resolve_geometry_style(
                        {"trade_style": trade_style}, setup_type))
                min_distance = 0.5 * _canon_dist
''',
    ),
    # ── TB4: suboptimal slack scales with horizon (long + short) ──────
    (
        "audit_suboptimal_long",
        '''                if direction == 'long' and stop_price > optimal_stop + atr * 0.5:
''',
        '''                if direction == 'long' and stop_price > optimal_stop + atr * 0.5 * _hsbg_frac:
''',
    ),
    (
        "audit_suboptimal_short",
        '''                elif direction == 'short' and stop_price < optimal_stop - atr * 0.5:
''',
        '''                elif direction == 'short' and stop_price < optimal_stop - atr * 0.5 * _hsbg_frac:
''',
    ),
    # ── TB5: /fix-stop real ATR + trade_style ─────────────────────────
    (
        "fix_stop_real_atr",
        '''        # Estimate ATR as 2% of price if not available
        atr = entry_price * 0.02
        
        # Calculate intelligent stop
        analysis = await smart_stop.calculate_intelligent_stop(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            setup_type=setup_type,
            position_size=trade.shares,
            atr=atr
        )
''',
        '''        # v326 — REAL daily ATR (was: hardcoded 2%-of-price guess).
        from services.smart_stop_service import resolve_daily_atr
        _db_v326 = getattr(_trading_bot, "_db", None)
        if _db_v326 is None:
            _db_v326 = getattr(_trading_bot, "db", None)
        atr, _atr_source = resolve_daily_atr(_db_v326, symbol, entry_price)
        trade_style = getattr(trade, 'trade_style', None) or ''

        # Calculate intelligent stop (v326: horizon-aware via trade_style)
        analysis = await smart_stop.calculate_intelligent_stop(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            setup_type=setup_type,
            position_size=trade.shares,
            atr=atr,
            trade_style=trade_style
        )
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v326_unified_stops.py"

TEST_CONTENT = '''"""v326 — unified stop-rule SSOT + real-ATR audit tests."""
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
'''


def _find_repo_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / SSS_REL).exists() and (cand / TB_REL).exists():
            return cand
    print("FATAL: run from repo root (backend/ not found)")
    sys.exit(1)


def _apply(path: Path, chunks) -> None:
    text = path.read_text()
    changed = False
    for name, old, new in chunks:
        if new in text:
            print(f"  [SKIP] {name} — already applied")
            continue
        if old not in text:
            print(f"  [FAIL] {name} — anchor not found in {path.name}. ABORTING (no partial writes).")
            sys.exit(2)
        if text.count(old) != 1:
            print(f"  [FAIL] {name} — anchor not unique ({text.count(old)}). ABORTING.")
            sys.exit(2)
        text = text.replace(old, new, 1)
        changed = True
        print(f"  [OK]   {name}")
    if changed:
        path.write_text(text)


def main() -> None:
    root = _find_repo_root()

    # Pre-flight: v325 must already be applied (we use its HSBG helpers).
    eval_src = (root / EVAL_REL).read_text()
    if "_hsbg_horizon_frac" not in eval_src or "_resolve_geometry_style" not in eval_src:
        print("FATAL: v325 (HSBG) not applied yet — run apply_v325.py first.")
        sys.exit(1)

    print(f"repo root: {root}\n── {SSS_REL}")
    _apply(root / SSS_REL, SSS_CHUNKS)
    print(f"\n── {TB_REL}")
    _apply(root / TB_REL, TB_CHUNKS)

    for rel in (SSS_REL, TB_REL):
        try:
            py_compile.compile(str(root / rel), doraise=True)
            print(f"[OK]   py_compile {rel}")
        except py_compile.PyCompileError as exc:
            print(f"[FAIL] py_compile {rel}: {exc}")
            sys.exit(3)

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"[OK]   wrote {TEST_REL}")

    print("""
v326 APPLIED.

Next steps:
  1. .venv/bin/python -m pytest backend/tests/test_v326_unified_stops.py backend/tests/test_v325_hsbg.py -q
  2. git add -A && git commit -m "v326: unified stop-rule SSOT + real-ATR stop audits" && git push
  3. Restart (commit FIRST — StartTrading.bat runs `git checkout -- .`)
  4. Verify:
       curl -s http://127.0.0.1:8001/api/trading-bot/audit-stops | python3 -m json.tool | head -40
     With open positions, suggestions should now sit near the live v325
     geometry (no more 2%-of-price fantasy ATR) and properly-sized
     scalp/intraday stops should stop being flagged "too_tight".

Kill switches: UNIFIED_STOP_RULES_ENABLED=0 (rule-table merge),
               HSBG_ENABLED=0 (horizon scaling, from v325).
""")


if __name__ == "__main__":
    main()
