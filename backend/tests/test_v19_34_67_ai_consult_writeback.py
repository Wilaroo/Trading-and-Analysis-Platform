"""
Regression test for v19.34.67 — AI consult result must land in
`entry_context.ai_modules` so the ai_decision_audit_service reports
consulted_count > 0.

Bug history
-----------
On 2026-05-11 a live trading session produced an audit log where every
single trade showed:
    "consulted_count": 0,
    "aligned_count":   0,
    "modules": { all four → { "verdict": "abstain", "raw": "" } }

Root cause: in OpportunityEvaluator.evaluate_opportunity, the call to
self.build_entry_context() runs at trade-construction time but the AI
consultation block (which populates ai_consultation_result) runs
~40 lines later. A 2026-04-29 defensive `ai_consultation_result = None`
silenced an UnboundLocalError but ALSO meant build_entry_context
received None and wrote an empty ai_modules dict.

This test exercises the surgical fix — a write-back path that mutates
trade.entry_context["ai_modules"] AFTER the consultation completes —
by directly invoking the helper used at both sites.
"""
from services.opportunity_evaluator import OpportunityEvaluator


def test_ai_modules_ctx_returns_none_when_consultation_was_skipped():
    """The helper must return None for None / empty / non-dict input so
    callers can safely guard `if ai_ctx is not None`."""
    assert OpportunityEvaluator._build_ai_modules_ctx(None) is None
    assert OpportunityEvaluator._build_ai_modules_ctx({}) is None       # noqa: false-positive — dict({}) is falsy
    assert OpportunityEvaluator._build_ai_modules_ctx("not a dict") is None
    assert OpportunityEvaluator._build_ai_modules_ctx(42) is None


def test_ai_modules_ctx_populates_all_four_modules_when_consult_returned_them():
    """The canonical successful-consult case. consulted_count downstream
    should land at 4."""
    consult = {
        "proceed": True,
        "size_adjustment": 1.0,
        "summary": "all 4 modules aligned bullish, proceed at full size",
        "debate":          {"final_recommendation": "bullish", "confidence": 0.72, "winner": "bull"},
        "risk_assessment": {"recommendation": "approve", "confidence": 0.68},
        "institutional":   {"flow_direction": "buying",  "recommendation": "follow_flow"},
        "time_series":     {"forecast": {"direction": "up", "confidence": 0.61}},
    }
    ctx = OpportunityEvaluator._build_ai_modules_ctx(consult)
    assert ctx is not None
    assert ctx["consulted"] is True
    assert ctx["proceed"] is True
    assert ctx["size_adjustment"] == 1.0
    # The 4 canonical entry_context keys the audit service reads
    assert "debate" in ctx
    assert "risk_manager" in ctx           # mapped from risk_assessment
    assert "institutional_flow" in ctx     # mapped from institutional
    assert "time_series" in ctx
    assert ctx["debate"]["final_recommendation"] == "bullish"
    assert ctx["risk_manager"]["recommendation"] == "approve"
    assert ctx["institutional_flow"]["flow_direction"] == "buying"
    assert ctx["time_series"]["forecast"]["direction"] == "up"


def test_ai_modules_ctx_handles_partial_consult():
    """Real-world consults often skip a module (e.g. time_series down).
    The helper must include the modules that ARE present without
    fabricating empty entries for the missing ones — the audit service
    treats missing == abstain."""
    consult = {
        "proceed": False,
        "size_adjustment": 0.5,
        "summary": "risk manager blocked, debate split",
        "debate":          {"final_recommendation": "neutral"},
        "risk_assessment": {"recommendation": "block"},
        # institutional and time_series absent
    }
    ctx = OpportunityEvaluator._build_ai_modules_ctx(consult)
    assert ctx is not None
    assert ctx["consulted"] is True
    assert ctx["proceed"] is False
    assert ctx["size_adjustment"] == 0.5
    assert "debate" in ctx
    assert "risk_manager" in ctx
    assert "institutional_flow" not in ctx    # not fabricated
    assert "time_series" not in ctx           # not fabricated


def test_ai_modules_ctx_proceed_defaults_to_true_when_consult_lacks_field():
    """If consult result is missing the `proceed` field, default to True
    (don't accidentally veto)."""
    ctx = OpportunityEvaluator._build_ai_modules_ctx({"summary": "hi"})
    assert ctx is not None
    assert ctx["proceed"] is True


def test_audit_consulted_count_reflects_real_modules_after_writeback():
    """End-to-end check using the real ai_decision_audit_service:
    construct a fake trade with the entry_context shape our fix
    produces, run it through the audit row builder, and assert
    consulted_count matches the number of populated modules.
    """
    from services.ai_decision_audit_service import _build_audit_row

    consult = {
        "proceed": True,
        "size_adjustment": 1.0,
        "summary": "fixture",
        "debate":          {"final_recommendation": "bullish"},
        "risk_assessment": {"recommendation": "approve"},
        "institutional":   {"flow_direction": "buying"},
        "time_series":     {"forecast": {"direction": "up"}},
    }
    ai_modules_ctx = OpportunityEvaluator._build_ai_modules_ctx(consult)
    assert ai_modules_ctx is not None

    fake_trade = {
        "id":           "test-trade-123",
        "symbol":       "AAPL",
        "setup_type":   "vwap_fade_long",
        "direction":    "long",
        "executed_at":  "2026-05-11T13:30:00+00:00",
        "closed_at":    "2026-05-11T14:00:00+00:00",
        "net_pnl":      150.0,
        "close_reason": "target_hit",
        "entry_context": {
            "ai_modules": ai_modules_ctx,
        },
    }
    row = _build_audit_row(fake_trade)
    assert row["consulted_count"] == 4, f"expected 4, got {row['consulted_count']}"
    # All 4 modules said bullish-equivalent, trade won → all aligned
    assert row["aligned_count"] == 4, f"expected 4, got {row['aligned_count']}"


def test_audit_consulted_count_is_zero_for_empty_ai_modules_bug_repro():
    """Locks in the buggy-pre-fix behavior so we can never regress.
    Before v19.34.67, EVERY trade looked like this."""
    from services.ai_decision_audit_service import _build_audit_row

    fake_trade_pre_fix = {
        "id":           "test-trade-pre-fix",
        "symbol":       "NBIS",
        "setup_type":   "mean_reversion_short",
        "direction":    "short",
        "executed_at":  "2026-05-11T13:46:41+00:00",
        "closed_at":    "2026-05-11T13:46:52+00:00",
        "net_pnl":      -112.62,
        "close_reason": "external_close_v19_34_15b",
        "entry_context": {
            "ai_modules": {},   # ← what every trade had pre-fix
        },
    }
    row = _build_audit_row(fake_trade_pre_fix)
    # If consulted_count is non-zero here, the audit service spec
    # changed and this test (and the bug definition) needs updating.
    assert row["consulted_count"] == 0
    assert row["aligned_count"] == 0
