"""
Two-account guard — keep LIVE and PAPER IB accounts configured
side-by-side, but only ever authorize one at a time.

Env vars (backend/.env)
-----------------------
IB_ACCOUNT_LIVE    — real live trading account id(s). Comma or pipe
                     separated if IB reports multiple identifiers for the
                     same account (e.g. `esw100000,U1234567`).
IB_ACCOUNT_PAPER   — paper account id(s), e.g. `paperesw100000,DUN615665`.
                     IB's AccountValue stream reports the account NUMBER
                     (DUN…/U…), while the login username is something like
                     `paperesw100000`. Both refer to the same account but
                     are different strings, so we accept a list of aliases
                     and match on any.
IB_ACCOUNT_ACTIVE  — one of {"paper", "live"}. THE ONLY mode authorized to
                     place orders. Defaults to "paper" when unset so the
                     safe mode is always the fallback.

At every trade + every safety scan we compare `ib_pusher.account_id`
against the authorised alias set. Mismatch → kill-switch auto-trip.

This preserves the user's workflow: keep the live account configured
in the system (so it's ready to flip on) without ever accidentally
trading against it during paper testing.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# Aliases may be separated by comma, pipe, or whitespace.
_ALIAS_SPLIT = re.compile(r"[,|\s]+")


def _parse_aliases(raw: Optional[str]) -> List[str]:
    """Split a raw env string into a clean alias list (lowercased, deduped)."""
    if not raw:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for token in _ALIAS_SPLIT.split(raw):
        t = token.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


@dataclass(frozen=True)
class AccountExpectation:
    active_mode: str                          # "paper" | "live"
    expected_aliases: List[str] = field(default_factory=list)
    live_aliases:     List[str] = field(default_factory=list)
    paper_aliases:    List[str] = field(default_factory=list)

    # Back-compat convenience — the first alias in each list, for UI display.
    @property
    def expected_account_id(self) -> Optional[str]:
        return self.expected_aliases[0] if self.expected_aliases else None

    @property
    def live_account_id(self) -> Optional[str]:
        return self.live_aliases[0] if self.live_aliases else None

    @property
    def paper_account_id(self) -> Optional[str]:
        return self.paper_aliases[0] if self.paper_aliases else None


def load_account_expectation() -> AccountExpectation:
    """Read env vars and resolve which account should be active right now.

    Safe defaults: unset `IB_ACCOUNT_ACTIVE` → paper mode.
    """
    mode = (os.environ.get("IB_ACCOUNT_ACTIVE") or "paper").strip().lower()
    if mode not in ("paper", "live"):
        logger.warning(
            "[AccountGuard] IB_ACCOUNT_ACTIVE='%s' invalid — forcing 'paper'",
            mode,
        )
        mode = "paper"

    live = _parse_aliases(os.environ.get("IB_ACCOUNT_LIVE"))
    paper = _parse_aliases(os.environ.get("IB_ACCOUNT_PAPER"))
    expected = live if mode == "live" else paper

    return AccountExpectation(
        active_mode=mode,
        expected_aliases=expected,
        live_aliases=live,
        paper_aliases=paper,
    )


def check_account_match(
    current_account_id: Optional[str],
    expectation: Optional[AccountExpectation] = None,
    ib_connected: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Compare the pusher's current account_id against any authorised alias.

    Returns (ok: bool, reason: str). When no expectation is configured
    (env var blank for the active mode) we return (True, 'unconfigured') —
    the guard is opt-in so existing installations keep working unchanged.

    `ib_connected` is an *optional* hint. When IB Gateway is offline (weekends,
    overnight before Gateway boots) the pusher has no fresh account snapshot
    to push, so `current_account_id` is None — treating that as a MISMATCH
    is wrong because it's just an absence of data, not a drift. When the
    caller passes `ib_connected=False`, we soften the verdict to a neutral
    'pending' state so the UI chip doesn't go red while the market is closed.
    """
    exp = expectation or load_account_expectation()

    if not exp.expected_aliases:
        return True, "unconfigured"

    if not current_account_id:
        if ib_connected is False:
            return True, (
                f"pending — IB Gateway disconnected, no account snapshot from pusher "
                f"(expected {'/'.join(exp.expected_aliases)} once IB connects)"
            )
        return False, (
            f"no account reported by pusher; expected "
            f"{'/'.join(exp.expected_aliases)} ({exp.active_mode})"
        )

    current_norm = current_account_id.strip().lower()
    if current_norm in exp.expected_aliases:
        # Log which alias matched (helps the audit trail).
        return True, f"ok ({exp.active_mode}: matched '{current_norm}')"

    # Special-case: the pusher is reporting an account that belongs to the
    # OTHER mode. Surface that explicitly — it's the most dangerous drift.
    other_aliases = (
        exp.live_aliases if exp.active_mode == "paper" else exp.paper_aliases
    )
    if current_norm in other_aliases:
        wrong_mode = "live" if exp.active_mode == "paper" else "paper"
        return False, (
            f"account drift: expected {'/'.join(exp.expected_aliases)} "
            f"({exp.active_mode}), got {current_account_id} "
            f"(belongs to {wrong_mode} mode)"
        )

    return False, (
        f"account drift: expected {'/'.join(exp.expected_aliases)} "
        f"({exp.active_mode}), got {current_account_id}"
    )


def summarize_for_ui(
    current_account_id: Optional[str],
    ib_connected: Optional[bool] = None,
) -> dict:
    """Payload consumed by the V5 header chip.

    `ib_connected` is forwarded to `check_account_match` so weekend/offline
    states show 'pending' instead of 'mismatch'.
    """
    exp = load_account_expectation()
    ok, reason = check_account_match(current_account_id, exp, ib_connected=ib_connected)
    return {
        "active_mode": exp.active_mode,
        "expected_account_id": exp.expected_account_id,
        "expected_aliases": list(exp.expected_aliases),
        "current_account_id": current_account_id,
        "live_account_id": exp.live_account_id,
        "live_aliases": list(exp.live_aliases),
        "paper_account_id": exp.paper_account_id,
        "paper_aliases": list(exp.paper_aliases),
        "match": ok,
        "reason": reason,
        "ib_connected": ib_connected,
    }
