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


def classify_close(
    close_reason: Optional[str],
    entered_by: str = "",
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    net_pnl: Optional[float] = None,
    hold_seconds: Optional[float] = None,
    setup_type: str = "",
) -> Tuple[bool, str]:
    """Return (is_genuine, tag).

    is_genuine=False means the close is an execution/reconciliation artifact and
    must NOT count toward setup EV / win-rate / edge scoreboards. `tag` records
    WHY (audit breadcrumb), e.g. 'instant_external_unwind'.
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
# the diagnostics agree on one definition.
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
