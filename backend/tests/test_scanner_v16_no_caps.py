"""
v16 — operator-driven scanner tweaks (2026-04-30):
  1. `relative_strength` detector REMOVED from `_enabled_setups` —
     RS leader/laggard alerts have no concrete entry trigger and
     were dominating breadth.
  2. Alert caps lifted (50 → 500) end-to-end so every setup/idea is
     visible to the operator (no artificial throttle).

Both are source-level guards so a future contributor can't silently
re-introduce the limits.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNER = (ROOT / "services" / "enhanced_scanner.py").read_text()
SENTCOM_ROUTER = (ROOT / "routers" / "sentcom.py").read_text()


# --------------------------------------------------------------------------
# 1. relative_strength is OUT of _enabled_setups
# --------------------------------------------------------------------------

def test_relative_strength_not_in_enabled_setups():
    """The `_enabled_setups: Set[str] = { ... }` literal must not
    contain `"relative_strength"` at the top level (it's still
    referenced in carry-forward / persistence logic, which is fine)."""
    # Locate the _enabled_setups initializer block.
    match = re.search(
        r"self\._enabled_setups: Set\[str\] = \{(.*?)\}",
        SCANNER,
        re.DOTALL,
    )
    assert match, "Could not locate _enabled_setups block in enhanced_scanner.py"
    block = match.group(1)
    # The detector key in the dispatcher map is `"relative_strength"`
    # (singular). The leader/laggard variants are *output setup_types*,
    # not registered detectors — they only flow if the dispatcher fires.
    has_rs_detector = re.search(r'(?<![_a-z])"relative_strength"', block)
    assert has_rs_detector is None, (
        "Found `relative_strength` in `_enabled_setups`. The detector "
        "was disabled by operator request 2026-04-30 v16 (no concrete "
        "entry trigger; was dominating breadth). To re-enable, also "
        "remove this regression guard with explicit operator approval."
    )


def test_check_relative_strength_method_still_present():
    """The detector METHOD is preserved — only the dispatcher
    registration was removed. This lets us re-enable per-strategy via
    the promotion service (or wire RS as an ML feature) without
    rebuilding the detector. Guard against accidental over-deletion."""
    assert "_check_relative_strength" in SCANNER, (
        "_check_relative_strength method should remain in source even "
        "though it's no longer dispatched. v16 only removed the "
        "_enabled_setups registration. If you actually deleted the "
        "method, also remove this guard."
    )


# --------------------------------------------------------------------------
# 2. Alert caps lifted end-to-end
# --------------------------------------------------------------------------

def test_scanner_max_alerts_is_500():
    """`enhanced_scanner._max_alerts` must be 500 (or higher).

    Was 50 prior to v16; the upstream throttle silently capped every
    consumer (REST endpoint, WebSocket broadcast, V5 panel) regardless
    of any limit they advertised."""
    match = re.search(r"self\._max_alerts\s*=\s*(\d+)", SCANNER)
    assert match, "Could not locate _max_alerts assignment"
    cap = int(match.group(1))
    assert cap >= 500, (
        f"_max_alerts={cap} (must be >= 500). Operator pinned 2026-04-30 "
        "v16: every setup/idea must be visible. If you lowered this, the "
        '"only ever 5 alerts" complaint will return.'
    )


def test_sentcom_alerts_endpoint_default_and_ceiling_lifted():
    """`/api/sentcom/alerts` Query default must be 200, ceiling 500.

    Pre-v16 was `Query(10, ge=1, le=50)` — the 50 ceiling was the
    bottleneck even after the frontend bump."""
    pattern = re.compile(
        r'def get_alerts\(limit: int = Query\((\d+),\s*ge=(\d+),\s*le=(\d+)\)\)',
    )
    match = pattern.search(SENTCOM_ROUTER)
    assert match, (
        "Could not locate `get_alerts(limit: int = Query(...))` in "
        "routers/sentcom.py — the signature may have changed."
    )
    default, ge, le = (int(g) for g in match.groups())
    assert default == 200, f"default limit should be 200 (was {default})"
    assert le >= 500, (
        f"limit ceiling should be >= 500 (was {le}). Operator pinned "
        "v16 — lowering this brings back the 'only ever N alerts' bug."
    )
    assert ge == 1, f"ge should be 1 (was {ge})"
