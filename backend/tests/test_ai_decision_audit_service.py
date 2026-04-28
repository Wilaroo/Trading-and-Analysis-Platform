"""
Tests for the AI Decision Audit service.

Locks in:
- Verdict normalisation across the rich strings the consultation
  pipeline emits (PROCEED_HIGH_CONFIDENCE, REJECT, BULLISH_FLOW, etc).
- Outcome-alignment math: bullish + win = aligned, bearish + loss =
  aligned, neutral/abstain = never aligned.
- End-to-end aggregation against a mocked `bot_trades` collection.
"""

from typing import List

import mongomock
import pytest

from services.ai_decision_audit_service import (
    _normalise_verdict,
    _compute_alignment,
    _extract_module_verdict,
    _is_winning_trade,
    compute_ai_decision_audit,
)


# ────────────────────── Verdict normalisation ──────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("PROCEED",                        "bullish"),
    ("PROCEED_HIGH_CONFIDENCE",        "bullish"),
    ("approve_long",                   "bullish"),
    ("BUY",                            "bullish"),
    ("bullish_flow",                   "bullish"),
    ("UP",                             "bullish"),
    ("PASS",                           "bearish"),
    ("REJECT",                         "bearish"),
    ("BLOCK_RISK_TOO_HIGH",            "bearish"),
    ("no_trade",                       "bearish"),  # contains "trade" but pass takes precedence
    ("BEARISH",                        "bearish"),
    ("DOWN",                           "bearish"),
    ("NEUTRAL",                        "neutral"),
    ("hold",                           "neutral"),
    ("LOW_CONFIDENCE",                 "neutral"),
    ("",                               "abstain"),
    (None,                             "abstain"),
    ("UNKNOWN_GIBBERISH",              "abstain"),
])
def test_normalise_verdict(raw, expected):
    assert _normalise_verdict(raw) == expected


# ────────────────────── Alignment math ─────────────────────────────────


@pytest.mark.parametrize("verdict,win,expected", [
    ("bullish", True,  True),    # said go, trade won → aligned
    ("bullish", False, False),   # said go, trade lost → wrong
    ("bearish", True,  False),   # said skip, trade won → wrong (would have made money)
    ("bearish", False, True),    # said skip, trade lost → aligned (would have saved money)
    ("neutral", True,  False),   # no opinion, never aligned
    ("neutral", False, False),
    ("abstain", True,  False),
    ("abstain", False, False),
])
def test_compute_alignment(verdict, win, expected):
    assert _compute_alignment(verdict, win) is expected


# ────────────────────── Verdict extraction ─────────────────────────────


def test_extract_verdict_walks_priority_order():
    """Should pick `final_recommendation` over `recommendation` over
    `winner` (debate uses all three depending on how it returned)."""
    debate = {
        "final_recommendation": "PROCEED",
        "recommendation": "approve",  # Lower priority
        "winner": "bull",
    }
    assert _extract_module_verdict(debate) == "PROCEED"


def test_extract_verdict_falls_through_to_nested_forecast():
    """Time-series sometimes nests `direction` inside `forecast`."""
    ts = {"forecast": {"direction": "up", "confidence": 0.65}}
    assert _extract_module_verdict(ts) == "up"


def test_extract_verdict_none_when_module_missing():
    assert _extract_module_verdict(None) == ""
    assert _extract_module_verdict({}) == ""


# ────────────────────── Win detection ──────────────────────────────────


def test_is_winning_trade_uses_net_pnl_first():
    """`net_pnl` (after commissions) is the operator-meaningful P&L —
    take precedence over realized_pnl."""
    assert _is_winning_trade({"net_pnl": 50.0, "realized_pnl": 100}) is True
    assert _is_winning_trade({"net_pnl": -10.0, "realized_pnl": 100}) is False
    # Falls back to realized_pnl when net_pnl missing.
    assert _is_winning_trade({"realized_pnl": 50.0}) is True
    assert _is_winning_trade({"realized_pnl": -50.0}) is False
    # Empty trade returns False (no signal of a win).
    assert _is_winning_trade({}) is False


# ────────────────────── End-to-end aggregation ─────────────────────────


def _make_trade(idx: int, win: bool, modules: dict) -> dict:
    """Build a synthetic closed trade doc with optional ai_modules."""
    return {
        "id": f"t_{idx:04d}",
        "symbol": "AAPL",
        "setup_type": "BREAKOUT",
        "direction": "long",
        "status": "closed",
        "executed_at": f"2026-04-29T13:{idx:02d}:00+00:00",
        "closed_at": f"2026-04-29T15:{idx:02d}:00+00:00",
        "net_pnl": 50.0 if win else -25.0,
        "realized_pnl": 50.0 if win else -25.0,
        "pnl_pct": 1.5 if win else -0.8,
        "close_reason": "target_2" if win else "stop_loss",
        "entry_context": {"ai_modules": modules},
    }


@pytest.fixture
def db():
    """In-memory Mongo with a synthetic bot_trades collection."""
    client = mongomock.MongoClient()
    return client["test_audit"]


def test_compute_audit_returns_empty_when_no_trades(db):
    """No closed trades → clean empty payload (no exception)."""
    out = compute_ai_decision_audit(db, limit=30)
    assert out == {"trades": [], "summary": {"total_trades": 0, "win_rate": 0,
                                              "per_module": {}}}


def test_compute_audit_returns_safe_payload_when_db_none():
    """`db=None` returns the same shape as no-data — never raises."""
    out = compute_ai_decision_audit(None, limit=30)
    assert out["trades"] == []
    assert out["summary"]["total_trades"] == 0


def test_compute_audit_extracts_per_module_verdicts(db):
    """End-to-end: insert a trade with all 4 module verdicts, verify
    extraction + alignment math."""
    db.bot_trades.insert_one(_make_trade(
        1, win=True,
        modules={
            "consulted": True,
            "debate":             {"final_recommendation": "PROCEED", "winner": "bull"},
            "risk_manager":       {"recommendation": "APPROVE"},
            "institutional_flow": {"flow_direction": "BULLISH"},
            "time_series":        {"forecast": {"direction": "up", "confidence": 0.72}},
        },
    ))

    out = compute_ai_decision_audit(db, limit=30)

    assert out["summary"]["total_trades"] == 1
    assert out["summary"]["win_rate"] == 1.0

    row = out["trades"][0]
    assert row["symbol"] == "AAPL"
    assert row["win"] is True
    assert row["consulted_count"] == 4
    assert row["aligned_count"] == 4  # All 4 modules said bullish, trade won
    # Per-module verdicts normalised correctly
    assert row["modules"]["debate"]["verdict"] == "bullish"
    assert row["modules"]["debate"]["aligned"] is True
    assert row["modules"]["risk_manager"]["verdict"] == "bullish"
    assert row["modules"]["institutional"]["verdict"] == "bullish"
    assert row["modules"]["time_series"]["verdict"] == "bullish"
    # TS confidence preserved
    assert row["modules"]["time_series"]["confidence"] == 0.72


def test_compute_audit_credits_dissenting_modules_on_losses(db):
    """When a trade loses but a module said PASS/REJECT, that module's
    verdict was correct (it saved the operator from being even more
    wrong) → marked as aligned."""
    db.bot_trades.insert_one(_make_trade(
        1, win=False,
        modules={
            "debate":             {"final_recommendation": "PROCEED"},  # Wrong: bullish + loss
            "risk_manager":       {"recommendation": "REJECT"},          # Right: bearish + loss
            "institutional_flow": {"flow_direction": "BULLISH"},         # Wrong
            "time_series":        {"forecast": {"direction": "DOWN"}},   # Right
        },
    ))

    out = compute_ai_decision_audit(db, limit=30)
    row = out["trades"][0]

    assert row["aligned_count"] == 2  # Risk + TS
    assert row["modules"]["debate"]["aligned"] is False
    assert row["modules"]["risk_manager"]["aligned"] is True
    assert row["modules"]["institutional"]["aligned"] is False
    assert row["modules"]["time_series"]["aligned"] is True


def test_compute_audit_summary_aggregates_alignment_rates(db):
    """Across multiple trades, `summary.per_module.alignment_rate`
    should be `aligned_count / consulted_count` (NOT
    aligned_count/total — abstaining shouldn't penalize a module)."""
    # Trade 1: win, all bullish — debate aligned, others aligned
    db.bot_trades.insert_one(_make_trade(
        1, win=True,
        modules={
            "debate":             {"final_recommendation": "PROCEED"},
            "risk_manager":       {"recommendation": "APPROVE"},
        },
    ))
    # Trade 2: loss, mixed — debate misaligned, risk dissented (correct)
    db.bot_trades.insert_one(_make_trade(
        2, win=False,
        modules={
            "debate":             {"final_recommendation": "PROCEED"},
            "risk_manager":       {"recommendation": "REJECT"},
        },
    ))

    out = compute_ai_decision_audit(db, limit=30)

    debate_summary = out["summary"]["per_module"]["debate"]
    assert debate_summary["consulted"] == 2
    assert debate_summary["aligned"] == 1  # only trade 1
    assert debate_summary["alignment_rate"] == 0.5

    risk_summary = out["summary"]["per_module"]["risk_manager"]
    assert risk_summary["consulted"] == 2
    assert risk_summary["aligned"] == 2  # bullish+win on T1, bearish+loss on T2
    assert risk_summary["alignment_rate"] == 1.0


def test_compute_audit_handles_missing_ai_modules_gracefully(db):
    """A trade without `entry_context.ai_modules` (legacy or
    consultation-skipped) should still appear in the audit list with
    every module marked as `abstain` / not aligned."""
    db.bot_trades.insert_one({
        "id": "t_legacy",
        "symbol": "GLD",
        "setup_type": "VWAP",
        "direction": "long",
        "status": "closed",
        "closed_at": "2026-04-29T15:00:00+00:00",
        "net_pnl": 100.0,
        "entry_context": {},  # No ai_modules key
    })

    out = compute_ai_decision_audit(db, limit=30)
    assert out["summary"]["total_trades"] == 1
    row = out["trades"][0]
    assert row["consulted_count"] == 0
    assert row["aligned_count"] == 0
    for mod_name in ("debate", "risk_manager", "institutional", "time_series"):
        assert row["modules"][mod_name]["verdict"] == "abstain"
        assert row["modules"][mod_name]["aligned"] is False


def test_compute_audit_respects_limit_and_sorts_newest_first(db):
    """`limit=N` returns at most N trades, sorted by `closed_at` DESC
    (most recent first)."""
    for i in range(5):
        db.bot_trades.insert_one(_make_trade(
            i, win=True, modules={"debate": {"final_recommendation": "PROCEED"}}
        ))

    out = compute_ai_decision_audit(db, limit=3)
    assert len(out["trades"]) == 3
    # Newest first — t_0004 has the highest closed_at suffix
    assert out["trades"][0]["trade_id"] == "t_0004"
    assert out["trades"][1]["trade_id"] == "t_0003"
    assert out["trades"][2]["trade_id"] == "t_0002"
