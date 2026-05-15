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
from datetime import datetime, timezone
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
    pusher_first_seen_at: Optional[datetime] = None,
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

    `pusher_first_seen_at` (v19.34.25 Patch I) — when the pusher just
    connected, the IB Gateway `reqAccountSummary` call typically lands
    AFTER the first positions/orders push. During that window the
    account_id is legitimately unknown even though `ib_connected=True`.
    Pre-I we tripped the guard immediately, which (combined with the
    Patch G race) left a stampede of 7 entries naked when the guard
    finally fired. Now: if the caller passes the timestamp of the
    pusher's first POST AND less than ACCOUNT_GUARD_WARMUP_SECONDS
    (default 60s) have elapsed, treat missing account_id as
    'pending — warming up' (same OK semantics as the offline case).
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
        # v19.34.25 Patch I — warmup window for fresh pusher
        # connections. The pusher pushes positions/orders before
        # reqAccountSummary lands; without this grace, the bot would
        # trip the kill switch on a healthy pusher that just hadn't
        # finished its initial account snapshot yet.
        if pusher_first_seen_at is not None:
            import os as _os_pi
            warmup_seconds = float(_os_pi.environ.get(
                "ACCOUNT_GUARD_WARMUP_SECONDS", "60",
            ))
            if warmup_seconds > 0:
                elapsed = (
                    datetime.now(timezone.utc) - pusher_first_seen_at
                ).total_seconds()
                if elapsed < warmup_seconds:
                    return True, (
                        f"pending — pusher account snapshot warming up "
                        f"({elapsed:.0f}s / {warmup_seconds:.0f}s, expected "
                        f"{'/'.join(exp.expected_aliases)} ({exp.active_mode}))"
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

    v19.34.39 (2026-05-07) — also surfaces `detected_mode` and
    `effective_mode` so the chip can render a SHADOW state when the
    pusher is offline + show "next fill will be tagged X" without
    needing a second endpoint. Replaces the standalone
    `/api/system/account-mode` consumer (`AccountModeBadge`) which has
    been removed in favor of a single, defensive guard chip.
    """
    exp = load_account_expectation()
    ok, reason = check_account_match(current_account_id, exp, ib_connected=ib_connected)
    classified = classify_account_id(current_account_id)
    effective_mode = (
        classified if classified in ("paper", "live")
        else exp.active_mode
    )
    return {
        "active_mode": exp.active_mode,
        "detected_mode": classified,            # what IB actually reports
        "effective_mode": effective_mode,       # what bot will stamp on next fill
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



# ── v19.31.13 — public helpers for trade_type stamping ──────────────


def classify_account_id(account_id: Optional[str]) -> str:
    """Map an IB account id string to its mode label.

    Detection rules (in priority order):
      1. Exact-match against IB_ACCOUNT_PAPER aliases → "paper".
      2. Exact-match against IB_ACCOUNT_LIVE aliases  → "live".
      3. Falls back to ID-prefix heuristics:
         - `DU*` (paper account ID prefix per IB convention) → "paper".
         - `paper*` (login alias) → "paper".
         - Anything else with at least 4 chars → "live" (conservative
           default: IB live account IDs typically start with `U`).
      4. Empty / None → "unknown".

    Used at order-execution time to stamp `trade_type` onto bot_trades
    so historical rows preserve their original mode even after the
    operator switches IB_ACCOUNT_ACTIVE.
    """
    if not account_id:
        return "unknown"
    norm = account_id.strip().lower()
    if not norm:
        return "unknown"

    exp = load_account_expectation()
    if norm in exp.paper_aliases:
        return "paper"
    if norm in exp.live_aliases:
        return "live"

    # Heuristic fallback for unconfigured installs.
    if norm.startswith("du") or norm.startswith("paper"):
        return "paper"
    if len(norm) >= 4:
        return "live"
    return "unknown"


def get_account_mode_snapshot(
    current_account_id: Optional[str],
    ib_connected: Optional[bool] = None,
) -> dict:
    """Compact summary for `/api/system/account-mode`. Distinct from
    `summarize_for_ui` (which is geared at the existing safety chip) —
    this one focuses on "what trade_type should I stamp right now?"
    plus the operator-friendly badge fields.
    """
    classified = classify_account_id(current_account_id)
    exp = load_account_expectation()
    ok, reason = check_account_match(current_account_id, exp, ib_connected=ib_connected)
    # The trade_type the bot SHOULD stamp on a fresh fill right now.
    # Prefer the IB-pusher-detected mode when present (it's the truth);
    # fall back to env-configured active_mode when pusher is offline.
    effective_mode = (
        classified if classified in ("paper", "live")
        else exp.active_mode
    )
    return {
        "active_mode": exp.active_mode,        # what env says we should be
        "detected_mode": classified,            # what IB actually reports
        "effective_mode": effective_mode,       # what we'll stamp on fills
        "current_account_id": current_account_id,
        "expected_aliases": list(exp.expected_aliases),
        "match": ok,
        "reason": reason,
        "ib_connected": ib_connected,
    }
