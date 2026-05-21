"""v19.34.68 — Adopted-orphan ATR-aware stop sizing tests.

Pre-fix bug: `reconcile_orphan_positions` hardcoded stop_distance to
`avg_cost * 2%`. On high-vol names (ARM @ $280, daily ATR ~$8), that's
a $5.60 stop — well inside one tick of price noise. ARM was stopped
out for -$1398 the same session on this tight stop.

Post-fix: stop_distance = max(pct_floor, atr_mult × ATR). The pct floor
keeps low-vol names (e.g. utility ETFs) from getting absurdly wide
stops; the ATR multiplier widens stops on volatile names. Operator can
tune via `atr_mult` arg or `bot.risk_params.reconciled_default_atr_mult`
(default 1.5).

This test isolates the stop-distance formula so we get coverage without
importing the heavy position_reconciler module (which has the full
Mongo + IB + executor dependency graph).
"""


def compute_stop_distance(avg_cost: float, default_stop_pct: float,
                          atr: float, atr_mult: float) -> tuple:
    """Mirror of the v19.34.68 logic. Returns (stop_distance, basis)."""
    pct_distance = avg_cost * (default_stop_pct / 100.0)
    atr_distance = (atr_mult * atr) if atr > 0 else 0.0
    stop_distance = max(pct_distance, atr_distance)
    basis = "atr" if atr_distance > pct_distance and atr_distance > 0 else "pct"
    return stop_distance, basis


# ───── the regression: ARM at $280 with ATR=$8 ─────
def test_arm_high_vol_gets_atr_widened_stop():
    """ARM avg $280, ATR $8 — pre-fix would have set stop $5.60 wide.
    Post-fix should be 1.5 × $8 = $12 (atr basis)."""
    dist, basis = compute_stop_distance(
        avg_cost=280.0, default_stop_pct=2.0, atr=8.0, atr_mult=1.5,
    )
    assert basis == "atr"
    assert dist == 12.0
    # Sanity: post-fix stop is comfortably wider than pre-fix.
    assert dist > 280.0 * 0.02  # pre-fix was $5.60


# ───── low-vol names: pct floor wins ─────
def test_low_vol_utility_keeps_pct_floor():
    """AEP avg $129, ATR $1.50 — pct floor ($2.58) > ATR widen ($2.25),
    so the pct floor kicks in (basis=pct)."""
    dist, basis = compute_stop_distance(
        avg_cost=129.0, default_stop_pct=2.0, atr=1.50, atr_mult=1.5,
    )
    assert basis == "pct"
    assert dist == 129.0 * 0.02
    # Sanity: never tighter than pct floor.
    assert dist >= 129.0 * 0.02


def test_dia_etf_keeps_pct_floor():
    """DIA avg $499, ATR $4 — pct ($9.98) > ATR ($6.00), pct wins."""
    dist, basis = compute_stop_distance(
        avg_cost=499.0, default_stop_pct=2.0, atr=4.0, atr_mult=1.5,
    )
    assert basis == "pct"
    assert abs(dist - 9.98) < 0.01


# ───── missing ATR data: graceful fallback to pct ─────
def test_zero_atr_falls_back_to_pct():
    dist, basis = compute_stop_distance(
        avg_cost=100.0, default_stop_pct=2.0, atr=0.0, atr_mult=1.5,
    )
    assert basis == "pct"
    assert dist == 2.0


def test_negative_atr_treated_as_missing():
    """Defensive: pusher snapshot occasionally serves negative ATR
    after a contract switch. Treat as missing."""
    # Note the prod compute uses `if atr > 0`, so any non-positive
    # number safely falls through to pct.
    dist, basis = compute_stop_distance(
        avg_cost=100.0, default_stop_pct=2.0, atr=-5.0, atr_mult=1.5,
    )
    assert basis == "pct"
    assert dist == 2.0


# ───── operator tuning ─────
def test_higher_atr_mult_widens_more():
    """A more conservative operator (atr_mult=2.5) gets a wider stop."""
    dist_15, _ = compute_stop_distance(280.0, 2.0, 8.0, 1.5)
    dist_25, _ = compute_stop_distance(280.0, 2.0, 8.0, 2.5)
    assert dist_25 > dist_15
    assert dist_25 == 20.0  # 2.5 × $8


def test_zero_atr_mult_disables_atr_widening():
    """atr_mult=0 means "always pct" — the pre-fix behavior, preserved
    as an opt-out for operators who explicitly want it back."""
    dist, basis = compute_stop_distance(
        avg_cost=280.0, default_stop_pct=2.0, atr=8.0, atr_mult=0.0,
    )
    assert basis == "pct"
    assert abs(dist - 5.60) < 1e-9  # exactly the pre-fix value


# ───── boundary: ATR exactly equals pct ─────
def test_tie_goes_to_pct():
    """When atr_distance == pct_distance, basis is 'pct' (since the
    `atr > pct` check is strict)."""
    # avg=100, pct=2% → 2.0 // atr=2.0, mult=1.0 → 2.0
    dist, basis = compute_stop_distance(
        avg_cost=100.0, default_stop_pct=2.0, atr=2.0, atr_mult=1.0,
    )
    assert basis == "pct"
    assert dist == 2.0


# ───── never returns < pct floor ─────
def test_invariant_never_tighter_than_pct_floor():
    """For arbitrary inputs, stop_distance >= pct_distance."""
    for avg in (50, 100, 280, 500):
        for atr in (0, 0.1, 1.0, 5.0, 10.0, 50.0):
            for mult in (0.0, 1.0, 1.5, 2.5):
                dist, _ = compute_stop_distance(avg, 2.0, atr, mult)
                assert dist >= avg * 0.02, (
                    f"stop tighter than pct floor: avg={avg} atr={atr} "
                    f"mult={mult} → dist={dist}"
                )
