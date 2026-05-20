"""Regression: v19.34.55 — broker_rejected sub-triage.

Before: every broker rejection that wasn't `min_tick`, `error_202`, or
`bracket_submission_timeout` fell through to the umbrella
"broker_rejected" / "other" buckets in the analytics UI. Common IB
rejection causes (parent cancelled on bracket OCA, margin shortage,
pacing violation, connection loss) were invisible at a glance.

After: 6 new sub-categories covering the most common IB rejection
patterns. Each maps a raw error string fragment → a canonical key
the UI can color-bucket.
"""

import pytest

from routers.rejection_analytics_router import (
    _normalise_reason,
    _reason_meta,
    REASON_MAP,
    CAT_BROKER,
)


# ── parent_cancelled ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Parent order 12345 was cancelled",
    "rejected_parent_cancelled",
    "Bracket parent cancelled before child filled",
])
def test_parent_cancelled_triage(raw):
    assert _normalise_reason(raw) == "parent_cancelled"


# ── margin_insufficient ───────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Error 201: Order rejected - reason: margin",
    "Insufficient buying power",
    "Order rejected - reason: insufficient funds",
    "BUYING POWER ABOVE LIMIT",
])
def test_margin_insufficient_triage(raw):
    assert _normalise_reason(raw) == "margin_insufficient"


# ── pacing_violation ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Error 162: Historical Market Data Service error message:Historical data request pacing violation",
    "pacing violation",
    "PACING_VIOLATION_SEEN",
])
def test_pacing_violation_triage(raw):
    assert _normalise_reason(raw) == "pacing_violation"


# ── no_security_def ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Error 200: No security definition has been found for the request",
    "no security definition",
    "no_security_def",
])
def test_no_security_def_triage(raw):
    assert _normalise_reason(raw) == "no_security_def"


# ── connection_lost ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Error 1100: Connectivity between IB and Trader Workstation has been lost",
    "Error 1101: Connectivity between IB and Trader Workstation has been restored",
    "connection_lost",
    "connectivity issue",
])
def test_connection_lost_triage(raw):
    assert _normalise_reason(raw) == "connection_lost"


# ── duplicate_order ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "Error 322: Error processing request - Duplicate order id",
    "duplicate order",
    "DUPLICATE_ORDER",
])
def test_duplicate_order_triage(raw):
    assert _normalise_reason(raw) == "duplicate_order"


# ── existing categorizations still work (regression guard) ────────────
def test_existing_categorizations_unchanged():
    assert _normalise_reason("Error 110: minimum price variation") == "min_tick"
    assert _normalise_reason("Error 202: Order cancelled by IB") == "error_202"
    assert _normalise_reason("stale_alert") == "stale_alert"
    assert _normalise_reason("rejection_cooldown") == "rejection_cooldown"
    # bracket_submission_timeout — must still match (came AFTER the
    # parent_cancelled rule, both contain "cancel"/"timeout").
    assert _normalise_reason("bracket submission timeout") == "bracket_submission_timeout"


# ── all 6 new keys land in CAT_BROKER ─────────────────────────────────
def test_all_new_triage_keys_are_broker_category():
    for k in ("parent_cancelled", "margin_insufficient", "pacing_violation",
             "no_security_def", "connection_lost", "duplicate_order"):
        assert k in REASON_MAP, f"missing REASON_MAP entry for {k}"
        assert REASON_MAP[k]["category"] == CAT_BROKER
        # _reason_meta must round-trip cleanly (UI-facing label/category).
        meta = _reason_meta(k)
        assert meta["category"] == CAT_BROKER
        assert meta["label"] and meta["label"] != k.replace("_", " ").title()


# ── unknown text still falls through to "other" ──────────────────────
def test_unknown_falls_through_to_other():
    assert _normalise_reason("some weird new error type nobody has seen") == "other"
    assert _normalise_reason("") == "other"
    assert _normalise_reason(None) == "other"


# ── patch shape lock ──────────────────────────────────────────────────
def test_patch_text_present_in_router():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "rejection_analytics_router.py")
    text = src.read_text()
    assert "v19.34.55" in text
    assert "parent_cancelled" in text
    assert "margin_insufficient" in text
    assert "pacing_violation" in text
    assert "no_security_def" in text
    assert "connection_lost" in text
    assert "duplicate_order" in text


# ── ordering invariant: more-specific rules fire BEFORE generic ones ──
def test_specific_rules_beat_generic():
    # Phrase contains "rejected" + "margin" — must hit margin_insufficient,
    # NOT the umbrella broker_rejected.
    assert _normalise_reason("Order rejected - reason: margin") == "margin_insufficient"
    # "Error 201" contains "201" not in any other rule's trigger words.
    assert _normalise_reason("Error 201") == "margin_insufficient"
