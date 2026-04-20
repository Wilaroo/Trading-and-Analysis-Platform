"""
Deflated Sharpe Ratio (DSR) — Bailey & López de Prado (2014).

Reference: AFML Ch. 14. Mlfinlab equivalent: `backtest_statistics.stats.deflated_sharpe_ratio`.
Hand-rolled to avoid dependency.

Motivation:
    With N random trials, the expected MAXIMUM Sharpe ratio is > 0 even when
    the true Sharpe is 0. Raw Sharpe over-states significance when multiple
    models/configs have been evaluated.

    DSR adjusts for:
        - number of independent trials N
        - variance of the trials' Sharpe ratios
        - skewness and kurtosis of the strategy returns
        - sample length

    Returns the PROBABILITY that the observed Sharpe is genuinely > 0 given
    everything we've tried.

Usage:
    dsr, p_value = deflated_sharpe_ratio(
        sharpe_observed=sr,
        num_trials=k,
        trial_variance=sr_std**2,
        sample_length=t_obs,
        skewness=ret_skew,
        kurtosis=ret_kurt,
    )
    # if p_value >= 0.95 → statistically significant
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats


# Euler-Mascheroni constant
_EULER = 0.5772156649015329


def expected_max_sharpe(num_trials: int, trial_variance: float) -> float:
    """
    Expected max Sharpe under N random independent trials (Bailey & LdP 2014, eq. 8).
    E[max(SR)] ≈ sqrt(V[SR]) * ((1 - γ) * Z_inv(1 - 1/N) + γ * Z_inv(1 - 1/(N*e)))
    where γ = Euler-Mascheroni, Z_inv is the inverse standard normal CDF.
    """
    if num_trials <= 1:
        return 0.0
    if trial_variance < 0:
        trial_variance = 0.0
    sigma = math.sqrt(trial_variance)
    z1 = stats.norm.ppf(1.0 - 1.0 / num_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (num_trials * math.e))
    return sigma * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(
    sharpe_observed: float,
    num_trials: int,
    trial_variance: float,
    sample_length: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> dict:
    """
    Compute the Deflated Sharpe Ratio.

    Args:
        sharpe_observed: The Sharpe we're testing (non-annualized or annualized —
                         just be consistent with sample_length).
        num_trials:      K (count of strategy variants tested).
        trial_variance:  Var(SR across trials).
        sample_length:   T (number of return observations).
        skewness:        3rd moment of returns.
        kurtosis:        4th moment (use 3 for normal).

    Returns:
        dict with:
            deflated_sharpe: Standardized score (Bailey & LdP eq. 9).
            p_value:         Pr(true Sharpe > 0 | everything tried).
            expected_max:    E[max SR] under null.
            is_significant:  p_value >= 0.95
    """
    if sample_length <= 1:
        return {
            "deflated_sharpe": 0.0, "p_value": 0.5, "expected_max": 0.0,
            "is_significant": False, "reason": "sample_length too small",
        }

    sr0 = expected_max_sharpe(num_trials, trial_variance)

    # Variance of the Sharpe estimator (Mertens 2002, Bailey & LdP eq. 9)
    # For non-normal returns: 1 + 0.5*SR^2 - skew*SR + ((kurt-3)/4)*SR^2
    sr = float(sharpe_observed)
    var_sr = 1.0 - skewness * sr + ((kurtosis - 3.0) / 4.0) * (sr ** 2) + 0.5 * (sr ** 2)
    var_sr = max(var_sr, 1e-8)
    denom = math.sqrt(var_sr / (sample_length - 1.0))

    numerator = (sr - sr0) * math.sqrt(sample_length - 1.0)
    # Equivalently: z = (sr - sr0) / denom
    z = (sr - sr0) / denom if denom > 0 else 0.0
    p_value = float(stats.norm.cdf(z))

    return {
        "deflated_sharpe": float(z),
        "p_value": float(p_value),
        "expected_max": float(sr0),
        "is_significant": bool(p_value >= 0.95),
        "num_trials": int(num_trials),
        "sample_length": int(sample_length),
    }


def sharpe_with_moments(returns: np.ndarray, annualization: float = 252.0) -> dict:
    """Convenience: compute Sharpe + skew + kurtosis + sample length from a returns series."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return {"sharpe": 0.0, "skew": 0.0, "kurt": 3.0, "n": len(r)}
    mu = float(r.mean())
    sigma = float(r.std(ddof=1))
    sr_raw = mu / sigma if sigma > 0 else 0.0
    sr = sr_raw * math.sqrt(annualization)
    return {
        "sharpe": sr,
        "sharpe_raw": sr_raw,
        "skew": float(stats.skew(r)) if len(r) > 2 else 0.0,
        "kurt": float(stats.kurtosis(r, fisher=False)) if len(r) > 3 else 3.0,
        "n": int(len(r)),
    }
