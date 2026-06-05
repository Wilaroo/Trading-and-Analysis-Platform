"""
Regression tests for the 2026-06 work items:

  B) Horizon-aware daily-bar lookback in MarketSetupClassifier
     (30d intraday → 120d multiday → 252d swing → 504d position).
  A) INTRADAY_BRACKET_V2 archetype → bracket geometry resolution
     used by probe_bracket_reconcile.py (tidal_wave=momentum=runner,
     fading_bounce=reversion-scalp=target/no-runner).
  C) Enhanced scanner in-play-health snapshot shape (wave / rvol /
     qualify) used by probe_inplay_health.py.

Pure-logic / source-level — no live IB or running services required,
so this runs green inside CI and inside the container.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# ─────────────────────────── B: horizon lookback ───────────────────────────

def test_history_days_for_style_mapping():
    from services.market_setup_classifier import MarketSetupClassifier
    c = MarketSetupClassifier(db=None)
    assert c._history_days_for_style("intraday") == 30
    assert c._history_days_for_style("scalp") == 30
    assert c._history_days_for_style("multi_day") == 120
    assert c._history_days_for_style("swing") == 252
    assert c._history_days_for_style("investment") == 504
    assert c._history_days_for_style("position") == 504
    # Unknown / missing → cheap default.
    assert c._history_days_for_style(None) == 30
    assert c._history_days_for_style("garbage") == 30
    # Alias resolves via trade_style_classifier SSOT.
    assert c._history_days_for_style("longterm") == 504   # → position


def test_load_daily_bars_uses_horizon_depth():
    """`_load_daily_bars` must limit the mongo query by the requested
    horizon depth (+5 buffer), not the fixed 30."""
    from services.market_setup_classifier import MarketSetupClassifier

    captured = {}

    class _Cursor:
        def sort(self, *a, **k):
            return self

        def limit(self, n):
            captured["limit"] = n
            return self

        def __iter__(self):
            return iter([])

    class _Coll:
        def find(self, *a, **k):
            return _Cursor()

    class _DB:
        def __getitem__(self, name):
            return _Coll()

    c = MarketSetupClassifier(db=_DB())
    asyncio.get_event_loop().run_until_complete(
        c._load_daily_bars("AAPL", history_days=252)
    )
    assert captured["limit"] == 252 + 5
    asyncio.get_event_loop().run_until_complete(c._load_daily_bars("AAPL"))
    assert captured["limit"] == 30 + 5  # default


def test_cache_superset_reuse():
    """A cached deep-window result is reused for a shallower request, but
    a shallow cache must NOT satisfy a deeper request."""
    from services.market_setup_classifier import (
        MarketSetupClassifier, MarketSetup,
    )
    c = MarketSetupClassifier(db=None)
    result = c._make_result(MarketSetup.NEUTRAL, 0.0, ["x"])
    # Seed a 30-day cache entry.
    c._cache["AAA"] = (result, datetime.now(timezone.utc), 30)
    # Shallow request (intraday=30) → cache hit.
    out = asyncio.get_event_loop().run_until_complete(
        c.classify("AAA", trade_style="intraday")
    )
    assert out is result
    hits_after_shallow = c._cache_hits
    # Deep request (swing=252) must miss (recompute) since cached depth < 252.
    asyncio.get_event_loop().run_until_complete(
        c.classify("AAA", trade_style="swing")
    )
    assert c._cache_hits == hits_after_shallow  # no new hit; it recomputed


# ─────────────────────── A: archetype → bracket geometry ───────────────────

def test_tidal_wave_is_runner_momentum():
    from services.setup_taxonomy import exit_archetype_prior
    # tidal_wave (m8) is true momentum → must get a RUNNER bracket.
    assert exit_archetype_prior("tidal_wave") == "runner"


def test_fading_bounce_is_target_no_runner():
    from services.setup_taxonomy import exit_archetype_prior
    # fading_bounce (m8) is a reversion scalp → fixed target, no runner.
    assert exit_archetype_prior("fading_bounce") == "target"


def test_resolve_geometry_runner_reserves_runner_shares():
    sys.path.insert(0, str(_BACKEND / "scripts"))
    from probe_bracket_reconcile import resolve_geometry

    arch, rules, plan, desc = resolve_geometry("tidal_wave", entry=100.0, atr=2.0,
                                               shares=400, direction="long")
    assert arch == "runner"
    assert getattr(rules, "leave_runner_pct", 0.0) > 0
    # The plan must contain a runner leg and the leg shares must not exceed total.
    runner_legs = [p for p in plan if p.get("runner")]
    assert len(runner_legs) == 1
    assert sum(p["shares"] for p in plan) <= 400
    assert runner_legs[0]["shares"] > 0


def test_resolve_geometry_target_has_no_runner():
    sys.path.insert(0, str(_BACKEND / "scripts"))
    from probe_bracket_reconcile import resolve_geometry

    arch, rules, plan, desc = resolve_geometry("fading_bounce", entry=50.0, atr=1.0,
                                               shares=200, direction="short")
    assert arch == "target"
    assert getattr(rules, "leave_runner_pct", 0.0) == 0
    assert not any(p.get("runner") for p in plan)


# ─────────────────────────── C: in-play health shape ───────────────────────

def test_in_play_health_snapshot_shape():
    from services.enhanced_scanner import EnhancedBackgroundScanner

    now = datetime.now(timezone.utc)
    fake = SimpleNamespace(
        _running=True,
        _last_wave_batch={
            "tier1_watchlist": ["SPY", "QQQ"],
            "tier2_high_rvol": ["NVDA", "TSLA", "AMD"],
            "tier3_wave": ["AAA", "BBB", "CCC", "DDD"],
            "universe_progress": {"current_wave": 2, "total_waves": 5, "progress_pct": 40},
        },
        _last_wave_batch_at=now - timedelta(seconds=10),
        _rvol_cache={
            "NVDA": (3.2, now - timedelta(seconds=30)),
            "AMD": (0.5, now - timedelta(seconds=400)),  # stale + below gate
        },
        _rvol_cache_ttl=300,
        _min_rvol_filter=0.8,
        _detector_evals_total={"tidal_wave": 100, "fading_bounce": 50},
        _detector_hits_total={"tidal_wave": 7, "fading_bounce": 1},
        _detector_evals={"tidal_wave": 10},
        _detector_hits={"tidal_wave": 1},
        _last_scan_time=now - timedelta(seconds=5),
        _scan_count=42,
        _symbols_scanned_last=120,
        _symbols_skipped_rvol=15,
        _symbols_skipped_adv=3,
        _symbols_skipped_in_play=8,
    )
    health = EnhancedBackgroundScanner.get_in_play_health(fake, sample=2)

    assert health["running"] is True
    w = health["wave"]
    assert w["tier1_count"] == 2 and w["tier2_count"] == 3 and w["tier3_count"] == 4
    assert w["unique_count"] == 9
    assert len(w["tier3_sample"]) == 2  # sample cap
    r = health["rvol"]
    assert r["cache_size"] == 2
    assert r["fresh_count"] == 1          # AMD is stale (>300s)
    assert r["passing_gate_count"] == 1   # AMD below 0.8 gate
    q = health["qualify"]
    assert q["cumulative_evals"] == 150 and q["cumulative_hits"] == 8
    assert round(q["cumulative_qualify_rate_pct"], 2) == round((8 / 150) * 100, 2)
    assert q["scan_count"] == 42
