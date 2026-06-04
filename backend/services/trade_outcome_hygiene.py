"""
v19.34.240 — trade-outcome hygiene.

Single source of truth for distinguishing a GENUINE strategy close (the bot
fired a setup, held it, and it exited on a stop / target / trail / EOD) from an
EXECUTION / RECONCILIATION ARTIFACT (phantom sweep, sub-minute external OCA
unwind, operator flatten, drift reconcile, corrupt entry==exit P&L attribution).

Why this exists: the `diag_accum_oca_drill` investigation found that the
`accumulation_entry` "performance" scoreboard was ~94% artifacts from the
2026-05-19→26 phantom/drift crisis (1-minute external closes, phantom sweeps,
operator flattens with ±$20k P&L on entry==exit rows). Those rows were
polluting the `strategy_stats` EV feed (TQS Setup pillar) and any setup-edge /
shadow-vs-real analysis. This module lets every consumer apply ONE consistent
genuineness test.

Pure + dependency-free so it is trivially unit-testable.
"""
from typing import Optional, Tuple

# close_reason substrings that ALWAYS denote a non-strategy artifact close.
_ARTIFACT_REASON_SUBSTRINGS = (
    "phantom",          # wrong_direction_phantom_swept_*, phantom_sibling_purge_*
    "sweep",
    "purge",
    "reconcile",        # reconciled_* close paths
    "external_flatten", # operator_external_flatten
    "operator_external",
)

# entered_by prefixes/substrings that denote a non-bot-fired entry (these were
# never genuine strategy entries, so their closes shouldn't grade the setup).
_ARTIFACT_ENTERED_BY_SUBSTRINGS = (
    "reconcil",   # reconciled_external, reconciled_excess_*
    "phantom",
)

# setup_type substrings that are themselves reconciliation/import artifacts —
# NOT real strategy setups (v19.34.241). e.g. reconciled_excess_slice,
# reconciled_orphan, imported_from_ib. These reached bot_trades as a setup_type
# but never came from a strategy detector, so they must not grade any setup.
_ARTIFACT_SETUP_SUBSTRINGS = (
    "reconciled",
    "imported",
    "phantom",
)

# An `oca_closed_externally` close held shorter than this is an immediate
# bracket unwind (drift/phantom era), not a real managed exit.
INSTANT_UNWIND_MAX_HOLD_S = 120.0

# entry==exit yet |net_pnl| exceeds this => corrupt P&L attribution row.
CORRUPT_PNL_ABS_FLOOR = 5.0
PRICE_EPS = 1e-6

# ── v19.34.263 — External-exit reclassification ──────────────────────────────
# Realized-R magnitude beyond which an external close is corrupt P&L
# attribution, not a real bracket fill (a 30d audit showed genuine external
# scalp/intraday closes sit in a sane -1R..+1R band; only drift/phantom-era
# rows blow past this).
RECLASS_MAX_ABS_R = 6.0
# How close (as a fraction of per-share risk) the reconstructed exit must come
# to a bracket level to count as having "reached" it. 0.05R ≈ tick-level slop.
RECLASS_LEVEL_TOL_R = 0.05


def _is_external_bracket_reason(close_reason: str) -> bool:
    """True for broker-side/OCA bracket closes we can decode into target/stop.

    Deliberately EXCLUDES operator/manual flattens (`operator_external_flatten`)
    and reconcile-driven external closes — those are not bracket fills and are
    already gated as artifacts upstream."""
    r = str(close_reason or "").lower()
    if "operator" in r or "manual" in r or "flatten" in r or "reconcil" in r:
        return False
    return ("oca_closed_externally" in r) or ("external_close" in r)


def reclassify_external_exit(
    close_reason: Optional[str],
    direction: Optional[str] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_prices=None,
    realized_pnl: Optional[float] = None,
    shares: Optional[float] = None,
) -> Tuple[Optional[str], str, Optional[float], Optional[float]]:
    """Decode an external/OCA bracket close into its TRUE exit kind.

    The 30d audit proved `exit_price` is persisted on <5% of external scalp/
    intraday closes, but `stop_price`+`target_prices` are present on 100% and
    `realized_pnl`+`shares` reconstruct the exit on ~90%. We therefore
    reconstruct the implied exit and band it against the ACTUAL bracket levels
    (NOT pnl-sign — 45-56% of these land mid-range as scratches/partials and a
    naive sign rule would over-claim targets).

    Returns (effective_reason, method, recon_exit, realized_r):
      effective_reason ∈ {"target", "stop_loss", "external_partial", None}
      method           ∈ {"price", "pnl_reconstructed", "not_external",
                           "unresolved", "corrupt_r"}
    """
    if not _is_external_bracket_reason(close_reason):
        return None, "not_external", None, None

    def _ff(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    entry = _ff(entry_price)
    stop = _ff(stop_price)
    tps = target_prices or []
    if isinstance(tps, (int, float)):
        tps = [tps]
    tgt = _ff(tps[0]) if tps else None
    d = str(getattr(direction, "value", direction) or "long").lower()
    is_long = d != "short"

    if not (entry and entry > 0) or not (stop and stop > 0) or not (tgt and tgt > 0):
        return None, "unresolved", None, None

    # Resolve exit: real persisted value first, else reconstruct from pnl/shares.
    xp = _ff(exit_price)
    method = "price"
    if not (xp and xp > 0):
        realized = _ff(realized_pnl)
        sh = _ff(shares)
        if realized is None or not (sh and sh > 0):
            return None, "unresolved", None, None
        pps = realized / sh
        xp = entry + pps if is_long else entry - pps
        method = "pnl_reconstructed"

    risk = abs(entry - stop)
    if risk <= 0:
        return None, "unresolved", xp, None
    move = (xp - entry) if is_long else (entry - xp)
    realized_r = round(move / risk, 4)

    if abs(realized_r) > RECLASS_MAX_ABS_R:
        return None, "corrupt_r", xp, realized_r

    tol_px = RECLASS_LEVEL_TOL_R * risk
    if is_long:
        reached_target = xp >= (tgt - tol_px)
        hit_stop = xp <= (stop + tol_px)
    else:
        reached_target = xp <= (tgt + tol_px)
        hit_stop = xp >= (stop - tol_px)

    if reached_target:
        return "target", method, xp, realized_r
    if hit_stop:
        return "stop_loss", method, xp, realized_r
    return "external_partial", method, xp, realized_r


def classify_close(
    close_reason: Optional[str],
    entered_by: str = "",
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    net_pnl: Optional[float] = None,
    hold_seconds: Optional[float] = None,
    setup_type: str = "",
    *,
    direction: Optional[str] = None,
    stop_price: Optional[float] = None,
    target_prices=None,
    realized_pnl: Optional[float] = None,
    shares: Optional[float] = None,
) -> Tuple[bool, str]:
    """Return (is_genuine, tag).

    is_genuine=False means the close is an execution/reconciliation artifact and
    must NOT count toward setup EV / win-rate / edge scoreboards. `tag` records
    WHY (audit breadcrumb), e.g. 'instant_external_unwind'.

    v19.34.263: when the optional bracket context (direction/stop/target/
    realized_pnl/shares) is supplied, a non-operator external/OCA close that
    decodes to a confident bracket outcome (target / stop / sane mid-range
    partial) is treated as GENUINE — these are real scalp bracket fills the
    learning loop was blind to because the blanket <120s instant-unwind guard
    discarded them. Corrupt-R external rows stay non-genuine. When the context
    is absent the legacy behavior is preserved verbatim (backward compatible).
    """
    r = str(close_reason or "").lower()
    eb = str(entered_by or "").lower()
    st = str(setup_type or "").lower()

    for sub in _ARTIFACT_SETUP_SUBSTRINGS:
        if sub in st:
            return False, f"artifact_setup:{st[:24]}"

    for sub in _ARTIFACT_REASON_SUBSTRINGS:
        if sub in r:
            return False, f"artifact_reason:{sub}"

    for sub in _ARTIFACT_ENTERED_BY_SUBSTRINGS:
        if sub in eb:
            return False, f"non_bot_entry:{eb[:24]}"

    # v19.34.263 — price-confirmed external bracket reclassification. Only when
    # the caller supplied enough context to decode the exit; otherwise fall
    # through to the legacy instant-unwind guard so old call sites are untouched.
    eff, method, _recon, _rr = reclassify_external_exit(
        close_reason=r, direction=direction, entry_price=entry_price,
        exit_price=exit_price, stop_price=stop_price, target_prices=target_prices,
        realized_pnl=realized_pnl if realized_pnl is not None else net_pnl,
        shares=shares,
    )
    if eff in ("target", "stop_loss", "external_partial"):
        return True, f"external_{eff}:{method}"
    if method == "corrupt_r":
        return False, "external_corrupt_r"

    if "oca_closed_externally" in r and hold_seconds is not None and hold_seconds < INSTANT_UNWIND_MAX_HOLD_S:
        return False, "instant_external_unwind"

    try:
        ep = float(entry_price) if entry_price is not None else None
        xp = float(exit_price) if exit_price is not None else None
        np_ = float(net_pnl) if net_pnl is not None else 0.0
    except (TypeError, ValueError):
        ep = xp = None
        np_ = 0.0
    if ep and xp and abs(ep - xp) < PRICE_EPS and abs(np_) > CORRUPT_PNL_ABS_FLOOR:
        return False, "corrupt_pnl_attribution"

    return True, "genuine"


def is_genuine_close(close_reason, entered_by="", entry_price=None,
                     exit_price=None, net_pnl=None, hold_seconds=None) -> bool:
    """Boolean convenience wrapper around classify_close."""
    return classify_close(
        close_reason, entered_by, entry_price, exit_price, net_pnl, hold_seconds
    )[0]


# v19.34.262 — BOT-EDGE ATTRIBUTION ------------------------------------------
# Shared definition of an ADOPTED/external position (a reconciled IB holding
# or operator-managed fill the bot merely attributed) vs the bot's OWN entry.
# Used by the Mission Control P&L split AND the offline audit so the HUD and
# the diagnostics agree on one definition. A 30d audit found 46% of closes
# were adopted (+$181k) while the bot's own edge was ~break-even — blending
# the two made the bot look far more profitable than it actually is.
_ADOPTED_ENTRY_HINTS = (
    "reconcil", "external", "excess", "adopt", "orphan",
    "ib_only", "ib-only", "imported",
)


def is_adopted_entry(entered_by="", source="", close_reason="") -> bool:
    """True if a trade row represents an ADOPTED/external position rather than
    the bot's own entry. Bot-originated rows are stamped entered_by='bot_fired';
    adopted rows carry entered_by='reconciled_*'/'external*' (or a reconciler
    source / external close_reason)."""
    blob = (
        str(entered_by or "") + " " + str(source or "") + " " + str(close_reason or "")
    ).lower()
    return any(h in blob for h in _ADOPTED_ENTRY_HINTS)


def excursion_floor(direction, entry_price, exit_price, stop_price) -> Tuple[float, float]:
    """v19.34.240 (Part B) — realized entry->exit excursion in R, used as a
    FLOOR for mfe_r / mae_r when the manage loop never populated them (a trade
    that closed before any manage tick had mfe_r==mae_r==0). Returns
    (mfe_r_floor, mae_r_floor). The floor never overwrites a larger real
    manage-loop peak — callers only apply it when the stored value is 0.

    mfe_r_floor = max(0, realized_r)  (at least the favorable part realized)
    mae_r_floor = min(0, realized_r)  (at least the adverse part realized)
    """
    try:
        entry = float(entry_price or 0)
        ex = float(exit_price or 0)
        stop = float(stop_price or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if entry <= 0 or ex <= 0:
        return 0.0, 0.0
    rps = abs(entry - stop) if stop > 0 else entry * 0.02
    if rps <= 0:
        rps = entry * 0.02
    d = str(getattr(direction, "value", direction) or "long").lower()
    move = (ex - entry) if d == "long" else (entry - ex)
    r = move / rps
    return max(0.0, r), min(0.0, r)
