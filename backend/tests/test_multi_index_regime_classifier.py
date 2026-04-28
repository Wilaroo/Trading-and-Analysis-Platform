"""Tests for the MultiIndexRegimeClassifier + composite label features.

Covers:
  - MultiIndexRegimeClassifier per-label detection (risk-on / off /
    divergences / mixed) from synthetic SPY/QQQ/IWM/DIA daily bars.
  - One-hot encoding helpers (`build_setup_label_features`,
    `build_regime_label_features`, `build_label_features`).
  - `derive_regime_label_from_features` — training-time derivation
    that reuses already-loaded numerical regime features.
  - LiveAlert exposes `multi_index_regime` field.
  - Scanner integration: `_apply_setup_context` stamps
    `alert.multi_index_regime`.
  - Cache TTL hits + invalidate clears state.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Dict, List

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

from services.multi_index_regime_classifier import (  # noqa: E402
    MultiIndexRegime,
    MultiIndexRegimeClassifier,
    REGIME_LABEL_FEATURE_NAMES,
    build_regime_label_features,
    derive_regime_label_from_features,
    get_multi_index_regime_classifier,
)
from services.market_setup_classifier import MarketSetup  # noqa: E402
from services.ai_modules.composite_label_features import (  # noqa: E402
    SETUP_LABEL_FEATURE_NAMES,
    ALL_LABEL_FEATURE_NAMES,
    build_setup_label_features,
    build_label_features,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _bars(closes: List[float]) -> List[Dict]:
    out = []
    for i, c in enumerate(closes):
        out.append({
            "date": f"2026-04-{i+1:02d}",
            "open": c, "close": c,
            "high": c * 1.005, "low": c * 0.995,
            "volume": 1_000_000,
        })
    return out


# ──────────────────────────── ONE-HOT HELPERS ────────────────────────────


def test_setup_label_feature_names_excludes_neutral():
    """NEUTRAL is the all-zeros baseline, so it has NO one-hot column."""
    for name in SETUP_LABEL_FEATURE_NAMES:
        assert "neutral" not in name
    # All 7 active setups should each have a column
    assert len(SETUP_LABEL_FEATURE_NAMES) == 7


def test_regime_label_feature_names_excludes_unknown():
    """UNKNOWN is the all-zeros baseline."""
    for name in REGIME_LABEL_FEATURE_NAMES:
        assert "unknown" not in name
    # 8 active regime labels
    assert len(REGIME_LABEL_FEATURE_NAMES) == 8


def test_build_setup_label_features_one_hot():
    feats = build_setup_label_features("gap_and_go")
    assert feats["setup_label_gap_and_go"] == 1.0
    others = [v for k, v in feats.items() if k != "setup_label_gap_and_go"]
    assert all(v == 0.0 for v in others)


def test_build_setup_label_features_neutral_is_all_zeros():
    feats = build_setup_label_features(MarketSetup.NEUTRAL)
    assert all(v == 0.0 for v in feats.values())


def test_build_setup_label_features_unrecognised_returns_zeros():
    feats = build_setup_label_features("not_a_real_setup")
    assert all(v == 0.0 for v in feats.values())
    # And the keys still cover all expected one-hot slots
    assert set(feats.keys()) == set(SETUP_LABEL_FEATURE_NAMES)


def test_build_regime_label_features_one_hot():
    feats = build_regime_label_features("risk_on_broad")
    assert feats["regime_label_risk_on_broad"] == 1.0
    others = [v for k, v in feats.items() if k != "regime_label_risk_on_broad"]
    assert all(v == 0.0 for v in others)


def test_build_regime_label_features_unknown_is_all_zeros():
    feats = build_regime_label_features(MultiIndexRegime.UNKNOWN)
    assert all(v == 0.0 for v in feats.values())


def test_build_label_features_combines_both():
    feats = build_label_features(
        market_setup="gap_and_go",
        multi_index_regime="risk_on_broad",
    )
    assert feats["setup_label_gap_and_go"] == 1.0
    assert feats["regime_label_risk_on_broad"] == 1.0
    # All other slots are zero
    one_count = sum(1 for v in feats.values() if v == 1.0)
    assert one_count == 2
    assert set(feats.keys()) == set(ALL_LABEL_FEATURE_NAMES)


# ──────────────────────────── CLASSIFIER LABEL ASSIGNMENT ────────────────────────────


def _index_bar_map(spy: List[float], qqq: List[float], iwm: List[float], dia: List[float]):
    return {
        "SPY": _bars(spy), "QQQ": _bars(qqq), "IWM": _bars(iwm), "DIA": _bars(dia),
    }


def test_classifier_unknown_when_insufficient_data():
    c = MultiIndexRegimeClassifier()
    res = _run(c.classify(index_bars={"SPY": _bars([100, 101])}))
    assert res.label == MultiIndexRegime.UNKNOWN


def test_classifier_risk_on_broad_all_indices_up():
    c = MultiIndexRegimeClassifier()
    # 21 bars climbing 2% across the window (above 20SMA, breadth strong)
    spy = [100 + 0.1 * i for i in range(21)]
    qqq = [200 + 0.21 * i for i in range(21)]
    iwm = [50 + 0.05 * i for i in range(21)]  # slowest of the bunch
    dia = [300 + 0.3 * i for i in range(21)]
    res = _run(c.classify(index_bars=_index_bar_map(spy, qqq, iwm, dia)))
    assert res.label in (MultiIndexRegime.RISK_ON_BROAD, MultiIndexRegime.RISK_ON_GROWTH)
    assert res.confidence > 0.5


def test_classifier_risk_off_broad_all_indices_down():
    c = MultiIndexRegimeClassifier()
    spy = [100 - 0.15 * i for i in range(21)]
    qqq = [200 - 0.3 * i for i in range(21)]
    iwm = [50 - 0.07 * i for i in range(21)]
    dia = [300 - 0.45 * i for i in range(21)]
    res = _run(c.classify(index_bars=_index_bar_map(spy, qqq, iwm, dia)))
    assert res.label in (
        MultiIndexRegime.RISK_OFF_BROAD,
        MultiIndexRegime.RISK_OFF_DEFENSIVE,
    )


def test_classifier_bullish_divergence_iwm_leads_falling_spy():
    """SPY flat-to-down, IWM up — early small-cap risk-on signal."""
    c = MultiIndexRegimeClassifier()
    # Make SPY drift down and IWM clearly up
    spy = [100 - 0.05 * i for i in range(21)]   # mild down
    qqq = [200] * 21                              # flat
    iwm = [50 + 0.08 * i for i in range(21)]    # rising ~3.4%
    dia = [300 - 0.05 * i for i in range(21)]   # mild down
    res = _run(c.classify(index_bars=_index_bar_map(spy, qqq, iwm, dia)))
    assert res.label == MultiIndexRegime.BULLISH_DIVERGENCE


def test_classifier_bearish_divergence_iwm_falling_spy_up():
    c = MultiIndexRegimeClassifier()
    spy = [100 + 0.1 * i for i in range(21)]   # SPY up 2%
    qqq = [200 + 0.2 * i for i in range(21)]
    iwm = [50 - 0.05 * i for i in range(21)]   # IWM down 2%
    dia = [300 + 0.3 * i for i in range(21)]
    res = _run(c.classify(index_bars=_index_bar_map(spy, qqq, iwm, dia)))
    assert res.label == MultiIndexRegime.BEARISH_DIVERGENCE


def test_classifier_caches_market_wide():
    c = MultiIndexRegimeClassifier()
    bars = _index_bar_map(
        [100] * 21, [200] * 21, [50] * 21, [300] * 21,
    )
    _run(c.classify(index_bars=bars))
    assert c._cache_misses == 1 and c._cache_hits == 0
    _run(c.classify(index_bars=bars))
    # Second classify hits the cache regardless of bars argument
    assert c._cache_hits == 1


def test_classifier_invalidate_clears_cache():
    c = MultiIndexRegimeClassifier()
    bars = _index_bar_map(
        [100] * 21, [200] * 21, [50] * 21, [300] * 21,
    )
    _run(c.classify(index_bars=bars))
    c.invalidate()
    _run(c.classify(index_bars=bars))
    assert c._cache_misses == 2


def test_classifier_singleton():
    a = get_multi_index_regime_classifier()
    b = get_multi_index_regime_classifier()
    assert a is b


# ──────────────────────────── derive_regime_label_from_features ────────────────────────────


def test_derive_label_unknown_when_features_zero():
    feats = {n: 0.0 for n in (
        "regime_spy_trend", "regime_qqq_trend", "regime_iwm_trend",
        "regime_rotation_qqq_spy", "regime_rotation_iwm_spy",
    )}
    assert derive_regime_label_from_features(feats) == MultiIndexRegime.UNKNOWN


def test_derive_label_risk_on_broad():
    """Trend feature is normalized by 0.02 (so 0.5 == +1% above SMA20).
    All three at ~0.5 → all up similar magnitudes → RISK_ON_BROAD."""
    feats = {
        "regime_spy_trend": 0.5,   # ≈ +1.0% trend
        "regime_qqq_trend": 0.5,
        "regime_iwm_trend": 0.5,
        "regime_rotation_qqq_spy": 0.0,
        "regime_rotation_iwm_spy": 0.0,
    }
    assert derive_regime_label_from_features(feats) == MultiIndexRegime.RISK_ON_BROAD


def test_derive_label_bullish_divergence():
    feats = {
        "regime_spy_trend": -0.4,  # SPY -0.8%
        "regime_qqq_trend": 0.0,
        "regime_iwm_trend": 0.8,   # IWM +1.6%
        "regime_rotation_qqq_spy": 0.0,
        "regime_rotation_iwm_spy": 0.024,
    }
    assert derive_regime_label_from_features(feats) == MultiIndexRegime.BULLISH_DIVERGENCE


def test_derive_label_risk_off_broad():
    feats = {
        "regime_spy_trend": -0.7,
        "regime_qqq_trend": -0.7,
        "regime_iwm_trend": -0.7,
        "regime_rotation_qqq_spy": 0.0,
        "regime_rotation_iwm_spy": 0.0,
    }
    assert derive_regime_label_from_features(feats) == MultiIndexRegime.RISK_OFF_BROAD


# ──────────────────────────── SCANNER INTEGRATION ────────────────────────────


def test_live_alert_has_multi_index_regime_field():
    """LiveAlert must expose multi_index_regime alongside market_setup."""
    from services.enhanced_scanner import LiveAlert
    fields = LiveAlert.__dataclass_fields__
    assert "multi_index_regime" in fields, (
        "LiveAlert is missing the multi_index_regime field"
    )
    # Default is "unknown"
    assert fields["multi_index_regime"].default == "unknown"


def test_apply_setup_context_stamps_multi_index_regime():
    """`_apply_setup_context` populates `alert.multi_index_regime` from
    the cached MultiIndexRegimeClassifier result."""
    from services.enhanced_scanner import (
        EnhancedBackgroundScanner, AlertPriority,
    )
    from services.multi_index_regime_classifier import (
        get_multi_index_regime_classifier, RegimeResult, MultiIndexRegime,
    )
    import datetime as dt

    s = EnhancedBackgroundScanner(db=None)
    regime_classifier = get_multi_index_regime_classifier()
    regime_classifier.invalidate()
    # Inject a fixed regime result into the cache
    regime_classifier._cached_result = RegimeResult(
        label=MultiIndexRegime.BULLISH_DIVERGENCE,
        confidence=0.9,
        reasoning=["test"],
    )
    regime_classifier._cached_at = dt.datetime.now(dt.timezone.utc)

    class _Alert:
        setup_type = "9_ema_scalp"
        priority = AlertPriority.HIGH
        market_setup = "neutral"
        is_countertrend = False
        out_of_context_warning = False
        experimental = False
        multi_index_regime = "unknown"
        reasoning: list = []

    alert = _Alert()

    async def _run_test():
        await s._apply_setup_context(alert, "TEST", None)

    _run(_run_test())
    assert alert.multi_index_regime == "bullish_divergence"


# ──────────────────────────── TIMESERIES INTEGRATION (lightweight) ────────────────────────────


def test_combined_feature_names_in_training_path_includes_labels():
    """The training entrypoint references ALL_LABEL_FEATURE_NAMES so the
    feature vector grows on the next retrain. Source-level guard."""
    from pathlib import Path
    src = Path("/app/backend/services/ai_modules/timeseries_service.py").read_text("utf-8")
    assert "ALL_LABEL_FEATURE_NAMES" in src
    assert "build_label_features" in src
    assert "label_feat_names" in src


def test_predict_path_uses_label_features_when_model_expects_them():
    """predict_for_setup gate-checks the model's _feature_names for
    ALL_LABEL_FEATURE_NAMES before computing the label features."""
    from pathlib import Path
    src = Path("/app/backend/services/ai_modules/timeseries_service.py").read_text("utf-8")
    # Look for the prediction-side block
    assert "model_expects_labels" in src
    assert "build_label_features" in src


# ──────────────────────────── BRIEFINGS NARRATIVE INTEGRATION ────────────────────────────


def test_setup_landscape_snapshot_exposes_multi_index_regime():
    """LandscapeSnapshot dataclass must expose `multi_index_regime`."""
    from services.setup_landscape_service import LandscapeSnapshot
    fields = LandscapeSnapshot.__dataclass_fields__
    assert "multi_index_regime" in fields
    assert "regime_confidence" in fields
    assert "regime_reasoning" in fields


def test_landscape_narrative_includes_regime_line_when_known():
    """When the multi-index regime is set, the briefing narrative
    leads with a 1st-person regime line."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    narrative, headline = svc._render_narrative(
        groups, sample_n=200, context="morning",
        regime_label="bullish_divergence",
        regime_reasoning=["IWM: +1.5% vs 20SMA", "SPY: -0.2% vs 20SMA"],
    )
    assert "bullish small-cap divergence" in narrative
    assert "Heading into the open" in narrative
    # First-person voice still preserved
    assert "I'm" in narrative


def test_landscape_narrative_silent_when_regime_unknown():
    """unknown regime should NOT inject any regime line — preserves the
    pre-regime narrative shape for backward compat with tests."""
    from services.setup_landscape_service import (
        SetupLandscapeService, SetupGroup,
    )
    svc = SetupLandscapeService(db=None)
    groups = [SetupGroup(setup="gap_and_go", count=12, examples=[("AAPL", 0.9)])]
    narrative, _ = svc._render_narrative(
        groups, sample_n=200, context="morning", regime_label="unknown",
    )
    # Should not contain any regime preface
    for phrase in (
        "risk-on", "risk-off", "divergence", "Multi-index regime",
    ):
        assert phrase not in narrative


def test_landscape_regime_line_renders_for_all_known_labels():
    """Every active MultiIndexRegime label must yield a non-empty regime
    line so the AI briefing surface never sees a stripped string."""
    from services.setup_landscape_service import SetupLandscapeService
    for label in (
        "risk_on_broad", "risk_on_growth", "risk_on_smallcap",
        "risk_off_broad", "risk_off_defensive",
        "bullish_divergence", "bearish_divergence", "mixed",
    ):
        line = SetupLandscapeService._regime_line(
            label, reasoning=["SPY: +1.0% vs 20SMA"], context="morning",
        )
        assert line, f"empty regime line for {label!r}"
        assert "Heading into the open" in line
