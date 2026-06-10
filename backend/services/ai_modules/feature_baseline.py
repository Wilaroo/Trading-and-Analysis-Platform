"""
v321 Tier-3a-lite — per-feature TRAINING distribution baselines.

Captured at train time (cheap: subsampled quantile stats) and persisted inside
the model document. Consumed later by the drift monitor: comparing live
feature distributions against these baselines (PSI / KS) tells us when the
market no longer looks like what a model trained on.

Env:
  TB_FEATURE_BASELINE=0   disables capture (default on).
"""
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np


def _safe_key(name: str) -> str:
    """Mongo keys may not contain '.' or start with '$'."""
    k = str(name).replace(".", "_").replace("$", "_")
    return k or "_"


def compute_feature_baseline(
    X,
    feature_names: List[str],
    max_rows: int = 50000,
    n_bins: int = 10,
) -> Optional[Dict]:
    """Per-feature stats + decile bin edges/fractions for future PSI checks.

    Returns None (never raises) when disabled, inputs are unusable, or any
    unexpected error occurs — baseline capture must never break training.
    """
    if str(os.environ.get("TB_FEATURE_BASELINE", "1")).strip().lower() in ("0", "false", "off", "no"):
        return None
    try:
        n = len(X)
        if n == 0 or not feature_names:
            return None
        Xa = np.asarray(X, dtype=np.float64)
        if Xa.ndim != 2 or Xa.shape[1] != len(feature_names):
            return None
        if n > max_rows:
            rng = np.random.default_rng(7)
            Xa = Xa[np.sort(rng.choice(n, size=max_rows, replace=False))]

        qs = np.linspace(0.0, 1.0, n_bins + 1)
        feats = {}
        for j, name in enumerate(feature_names):
            col = Xa[:, j]
            col = col[np.isfinite(col)]
            if len(col) == 0:
                continue
            edges = np.quantile(col, qs)
            uniq_edges = np.unique(edges)
            if len(uniq_edges) > 1:
                counts, _ = np.histogram(col, bins=uniq_edges)
            else:  # constant feature
                counts = np.array([len(col)])
            total = max(1, int(counts.sum()))
            feats[_safe_key(name)] = {
                "mean": float(col.mean()),
                "std": float(col.std()),
                "min": float(col.min()),
                "max": float(col.max()),
                "bin_edges": [float(e) for e in edges],
                "bin_fracs": [float(c) / float(total) for c in counts],
            }
        if not feats:
            return None
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "n_samples_total": int(n),
            "n_samples_used": int(len(Xa)),
            "n_bins": int(n_bins),
            "features": feats,
        }
    except Exception:
        return None
