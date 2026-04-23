"""
Two-account guard — keep LIVE and PAPER IB accounts configured
side-by-side, but only ever authorize one at a time.

Env vars (backend/.env)
-----------------------
IB_ACCOUNT_LIVE    — the user's real live trading account id, e.g. esw100000
IB_ACCOUNT_PAPER   — the paper account id, e.g. paperesw100000
IB_ACCOUNT_ACTIVE  — one of {"paper", "live"}. THE ONLY one authorized to
                     place orders. Defaults to "paper" when unset so the
                     safe mode is always the fallback.

At every trade + every safety scan we compare `ib_pusher.account_id`
against the resolved expected id. Mismatch → kill-switch auto-trip.

This preserves the user's workflow: keep the live account configured
in the system (so it's ready to flip on) without ever accidentally
trading against it during paper testing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountExpectation:
    active_mode: str           # "paper" | "live"
    expected_account_id: Optional[str]
    live_account_id: Optional[str]
    paper_account_id: Optional[str]


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

    live = (os.environ.get("IB_ACCOUNT_LIVE") or "").strip() or None
    paper = (os.environ.get("IB_ACCOUNT_PAPER") or "").strip() or None
    expected = live if mode == "live" else paper
    return AccountExpectation(
        active_mode=mode,
        expected_account_id=expected,
        live_account_id=live,
        paper_account_id=paper,
    )


def check_account_match(
    current_account_id: Optional[str],
    expectation: Optional[AccountExpectation] = None,
) -> Tuple[bool, str]:
    """Compare the pusher's current account_id to the expected one.

    Returns (ok: bool, reason: str). When no expectation is configured
    (both env vars blank) we return (True, 'unconfigured') — the guard is
    opt-in so existing installations keep working unchanged.
    """
    exp = expectation or load_account_expectation()

    if not exp.expected_account_id:
        return True, "unconfigured"
    if not current_account_id:
        return False, (
            f"no account reported by pusher; expected "
            f"{exp.expected_account_id} ({exp.active_mode})"
        )
    if current_account_id.strip().lower() != exp.expected_account_id.strip().lower():
        return False, (
            f"account drift: expected {exp.expected_account_id} "
            f"({exp.active_mode}), got {current_account_id}"
        )
    return True, f"ok ({exp.active_mode})"


def summarize_for_ui(current_account_id: Optional[str]) -> dict:
    """Payload consumed by the V5 header chip."""
    exp = load_account_expectation()
    ok, reason = check_account_match(current_account_id, exp)
    return {
        "active_mode": exp.active_mode,
        "expected_account_id": exp.expected_account_id,
        "current_account_id": current_account_id,
        "live_account_id": exp.live_account_id,
        "paper_account_id": exp.paper_account_id,
        "match": ok,
        "reason": reason,
    }
