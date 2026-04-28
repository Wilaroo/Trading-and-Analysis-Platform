"""
Categorical-label features for the per-Trade ML model.
=======================================================

The per-Trade XGBoost models already train on the granular regime
features (trend, RSI, momentum per index — see `regime_features.py`)
and the per-bar setup features (`setup_features.py`). Those are
*numerical*. What this module adds is the *categorical* layer:

  - The 7 Bellafiore daily Setups (`MarketSetup` enum) one-hot encoded
    so a model can learn "9_ema_scalp wins on Gap & Go but not on
    Overextension" without the operator having to hand-code the matrix.

  - The 8 multi-index regime labels (`MultiIndexRegime` enum) one-hot
    encoded so the model can carve along "small-cap divergence" vs
    "broad risk-on" buckets the human brain already thinks in.

These are SOFT-gate features — the matrix in
`market_setup_classifier.TRADE_SETUP_MATRIX` still applies for live
alerts, but it's the operator's heuristic. Letting the model also see
the labels lets the model *disagree* with the operator over time on
specific setup × regime cells.

Usage:
    from services.ai_modules.composite_label_features import (
        SETUP_LABEL_FEATURE_NAMES, REGIME_LABEL_FEATURE_NAMES,
        build_setup_label_features, build_regime_label_features,
        ALL_LABEL_FEATURE_NAMES, build_label_features,
    )

    feats = build_label_features(
        market_setup="gap_and_go",
        multi_index_regime="risk_on_broad",
    )
    # feats == {
    #   "setup_label_gap_and_go": 1.0,  ... (other setups 0.0)
    #   "regime_label_risk_on_broad": 1.0,  ... (other regimes 0.0)
    # }
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from services.market_setup_classifier import MarketSetup
from services.multi_index_regime_classifier import (
    MultiIndexRegime,
    REGIME_LABEL_FEATURE_NAMES,
    build_regime_label_features,
)
from services.sector_regime_classifier import (
    SectorRegime,
    SECTOR_LABEL_FEATURE_NAMES,
    build_sector_label_features,
)


# ──────────────────────────── SETUP-LABEL FEATURES ────────────────────────────

# All MarketSetup values *except* NEUTRAL (NEUTRAL = no positive signal,
# represented as all-zeros across the one-hot vector).
SETUP_LABEL_FEATURE_NAMES: List[str] = [
    f"setup_label_{s.value}"
    for s in MarketSetup
    if s != MarketSetup.NEUTRAL
]


def build_setup_label_features(
    market_setup: Union[MarketSetup, str, None],
) -> Dict[str, float]:
    """Return a {feature_name: 0.0/1.0} dict for the given Setup label.

    NEUTRAL/None/unrecognised labels yield an all-zeros dict.
    """
    feats = {name: 0.0 for name in SETUP_LABEL_FEATURE_NAMES}
    if market_setup is None:
        return feats
    if isinstance(market_setup, str):
        try:
            market_setup = MarketSetup(market_setup)
        except ValueError:
            return feats
    if market_setup == MarketSetup.NEUTRAL:
        return feats
    feats[f"setup_label_{market_setup.value}"] = 1.0
    return feats


# ──────────────────────────── COMBINED ────────────────────────────

ALL_LABEL_FEATURE_NAMES: List[str] = (
    SETUP_LABEL_FEATURE_NAMES + REGIME_LABEL_FEATURE_NAMES + SECTOR_LABEL_FEATURE_NAMES
)


def build_label_features(
    market_setup: Union[MarketSetup, str, None] = None,
    multi_index_regime: Union[MultiIndexRegime, str, None] = None,
    sector_regime: Union[SectorRegime, str, None] = None,
) -> Dict[str, float]:
    """Return the combined setup_label_* + regime_label_* + sector_label_*
    one-hot dict.

    Each layer's UNKNOWN/None case maps to its all-zeros baseline so the
    feature vector is always the same length regardless of which
    classifiers fired.
    """
    feats: Dict[str, float] = {}
    feats.update(build_setup_label_features(market_setup))
    feats.update(build_regime_label_features(
        multi_index_regime if multi_index_regime is not None else MultiIndexRegime.UNKNOWN
    ))
    feats.update(build_sector_label_features(sector_regime))
    return feats


__all__ = [
    "SETUP_LABEL_FEATURE_NAMES",
    "REGIME_LABEL_FEATURE_NAMES",
    "SECTOR_LABEL_FEATURE_NAMES",
    "ALL_LABEL_FEATURE_NAMES",
    "build_setup_label_features",
    "build_regime_label_features",
    "build_sector_label_features",
    "build_label_features",
]
