"""
Hierarchical Risk Parity + Nested Clustered Optimization.

Reference: López de Prado, "Building Diversified Portfolios that Outperform
Out of Sample" (2016); AFML Ch. 16 "HRP". Mlfinlab equivalent:
`portfolio_optimization.hierarchical_risk_parity.HierarchicalRiskParity`.

Motivation:
    Your bot fires multiple concurrent positions (e.g. AAPL long + META long
    + SPY short). Naive equal-risk sizing treats them as independent — but
    AAPL and META moves are ~85% correlated, so you'd really hold 2x tech-long
    risk instead of balanced.

HRP solves this WITHOUT inverting a covariance matrix (which is fragile when
N is small or correlations are noisy):
    1. Compute correlation distance: d_ij = sqrt(0.5 * (1 - ρ_ij))
    2. Hierarchical clustering (single-linkage) on d
    3. Recursive bisection — split portfolio into 2 sub-groups, allocate risk
       inverse-variance-weighted between groups
    4. Within each leaf cluster, use inverse-variance weights
    → Final: per-asset weights summing to 1

NCO (optional refinement):
    Within-cluster Markowitz + across-cluster HRP. Stable when clusters are
    tight (which they tend to be on financial data).

Usage (in trading_bot_service.py BEFORE placing orders):
    from services.ai_modules.hrp_allocator import hrp_weights

    candidates = [
        {"symbol": "AAPL", "direction": "long", "signal_strength": 0.7},
        {"symbol": "META", "direction": "long", "signal_strength": 0.6},
        {"symbol": "SPY",  "direction": "short", "signal_strength": 0.8},
    ]
    weights = hrp_weights(candidates, returns_matrix)  # (T, N) returns
    # weights = {"AAPL": 0.22, "META": 0.19, "SPY": 0.59}
    # Use to scale position sizes.
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def correlation_distance(corr_matrix: np.ndarray) -> np.ndarray:
    """
    López de Prado correlation distance:
        d_ij = sqrt(0.5 * (1 - ρ_ij))
    Returns condensed distance vector (scipy format).
    """
    n = corr_matrix.shape[0]
    clean = np.nan_to_num(corr_matrix, nan=0.0, posinf=1.0, neginf=-1.0)
    clean = np.clip(clean, -0.999999, 0.999999)
    dist = np.sqrt(np.clip(0.5 * (1 - clean), 0, None))
    return squareform(dist, checks=False)


def quasi_diagonal(link_matrix: np.ndarray) -> List[int]:
    """
    Reorder assets so that the most correlated pairs are adjacent.
    Follows the linkage tree and flattens it.
    """
    link = link_matrix.astype(int)
    num_items = link.shape[0] + 1
    # Start with the root cluster (last row)
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]
    while max(sort_ix) >= num_items:
        sort_ix_new = []
        for i in sort_ix:
            if i < num_items:
                sort_ix_new.append(i)
            else:
                # Cluster index — replace with its two children
                idx = i - num_items
                sort_ix_new.append(int(link[idx, 0]))
                sort_ix_new.append(int(link[idx, 1]))
        sort_ix = sort_ix_new
    return [int(i) for i in sort_ix]


def _cluster_variance(cov: np.ndarray, items: List[int]) -> float:
    """Inverse-variance weights within a cluster, then cluster variance."""
    sub = cov[np.ix_(items, items)]
    ivp = 1.0 / np.diag(sub)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


def recursive_bisection(cov: np.ndarray, sort_ix: List[int]) -> np.ndarray:
    """
    HRP recursive bisection — splits the sorted asset list in halves and
    allocates risk inversely proportional to cluster variance.
    """
    n = cov.shape[0]
    w = np.ones(n, dtype=np.float64)
    clusters = [list(sort_ix)]
    while clusters:
        new_clusters = []
        for c in clusters:
            if len(c) <= 1:
                continue
            mid = len(c) // 2
            left, right = c[:mid], c[mid:]
            var_left = _cluster_variance(cov, left)
            var_right = _cluster_variance(cov, right)
            # Inverse-variance allocation between the two sides
            alpha = 1 - var_left / (var_left + var_right + 1e-12)
            for i in left:
                w[i] *= alpha
            for i in right:
                w[i] *= (1 - alpha)
            new_clusters.append(left)
            new_clusters.append(right)
        clusters = new_clusters
    w = w / w.sum()
    return w


def hrp_weights_from_returns(
    returns: np.ndarray,
    asset_names: Optional[List[str]] = None,
) -> Dict[str, float]:
    """
    Compute HRP weights from a (T, N) returns matrix.

    Args:
        returns:     (T, N) numpy array — rows=time, cols=assets
        asset_names: optional list of N names (else indices)

    Returns:
        weights:     {asset_name: weight} summing to 1.0
    """
    if not _HAS_SCIPY:
        logger.warning("scipy missing — falling back to equal weights")
        n = returns.shape[1]
        names = asset_names or [str(i) for i in range(n)]
        return {name: 1.0 / n for name in names}

    returns = np.asarray(returns, dtype=np.float64)
    if returns.ndim != 2 or returns.shape[1] == 0:
        return {}
    n_assets = returns.shape[1]
    if asset_names is None:
        asset_names = [str(i) for i in range(n_assets)]
    if n_assets == 1:
        return {asset_names[0]: 1.0}

    # Correlation + covariance
    cov = np.cov(returns.T)
    sigma = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(sigma, sigma)
    np.fill_diagonal(corr, 1.0)

    # Single-linkage hierarchical clustering on correlation distance
    dist = correlation_distance(corr)
    link = linkage(dist, method="single")
    sort_ix = quasi_diagonal(link)

    w = recursive_bisection(cov, sort_ix)
    return {asset_names[i]: float(w[i]) for i in range(n_assets)}


def hrp_weights(
    candidates: List[dict],
    returns_matrix: np.ndarray,
    symbol_col_map: Dict[str, int],
) -> Dict[str, float]:
    """
    Convenience: allocate risk across live trade candidates.

    Args:
        candidates:     list of {"symbol": str, ...}
        returns_matrix: (T, M) matrix of recent returns for ALL tracked symbols
        symbol_col_map: {symbol: column_index} into returns_matrix

    Returns:
        weights:        {symbol: weight} normalized to sum=1 across candidates
    """
    syms = [c["symbol"] for c in candidates if c.get("symbol") in symbol_col_map]
    if len(syms) == 0:
        return {}
    if len(syms) == 1:
        return {syms[0]: 1.0}
    idx = [symbol_col_map[s] for s in syms]
    sub = returns_matrix[:, idx]
    return hrp_weights_from_returns(sub, asset_names=syms)


def nco_weights(
    returns: np.ndarray,
    asset_names: Optional[List[str]] = None,
    max_clusters: int = 5,
) -> Dict[str, float]:
    """
    Nested Clustered Optimization: within-cluster Markowitz + across-cluster HRP.
    Simplified version — clusters via linkage, within each cluster use
    inverse-variance weights, then HRP-allocate across clusters.
    """
    if not _HAS_SCIPY:
        return hrp_weights_from_returns(returns, asset_names)
    from scipy.cluster.hierarchy import fcluster

    returns = np.asarray(returns, dtype=np.float64)
    if returns.ndim != 2 or returns.shape[1] < 2:
        return hrp_weights_from_returns(returns, asset_names)

    n = returns.shape[1]
    if asset_names is None:
        asset_names = [str(i) for i in range(n)]

    cov = np.cov(returns.T)
    sigma = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(sigma, sigma)
    np.fill_diagonal(corr, 1.0)

    dist = correlation_distance(corr)
    link = linkage(dist, method="single")
    n_clusters = min(max_clusters, n)
    labels = fcluster(link, t=n_clusters, criterion="maxclust")

    # Within-cluster inverse-variance
    cluster_names = {}
    cluster_weights = {}
    for c in np.unique(labels):
        items = np.where(labels == c)[0]
        sub_cov = cov[np.ix_(items, items)]
        ivp = 1.0 / np.diag(sub_cov)
        ivp = ivp / ivp.sum()
        w_local = {int(items[i]): float(ivp[i]) for i in range(len(items))}
        cluster_weights[int(c)] = w_local
        # Cluster-level variance
        var_c = float(ivp @ sub_cov @ ivp)
        cluster_names[int(c)] = var_c

    # Across-cluster: inverse-variance
    cluster_ivp = np.array([1.0 / cluster_names[c] for c in sorted(cluster_names.keys())])
    cluster_ivp = cluster_ivp / cluster_ivp.sum()

    out = {}
    for i, c in enumerate(sorted(cluster_names.keys())):
        for asset_idx, local_w in cluster_weights[c].items():
            out[asset_names[asset_idx]] = float(cluster_ivp[i] * local_w)
    return out
