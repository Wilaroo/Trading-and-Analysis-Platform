"""
v19.34.175 — TQS / SMB unification regression tests.

Covers:
  • BotTrade carries unified_grade / tqs_grade / tqs_score and serializes them.
  • The grade multiplier table still maps A=1.0 … D=0.1 (operator choice A).
  • The backfill `unified_grade` resolution priority chain.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))


def _load_backfill():
    path = os.path.join(BACKEND, "scripts", "backfill_v19_34_175_unified_grade.py")
    spec = importlib.util.spec_from_file_location("bf_v175", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_grade_multiplier_table_choice_a():
    from services.opportunity_evaluator import _resolve_grade_multiplier
    assert _resolve_grade_multiplier("A") == (1.0, "A")
    assert _resolve_grade_multiplier("B+")[0] == 0.7  # first char collapse
    assert _resolve_grade_multiplier("C")[0] == 0.3
    assert _resolve_grade_multiplier("D")[0] == 0.1
    # Strict: missing/unknown → D (per operator Q2b).
    assert _resolve_grade_multiplier(None) == (0.1, "D")
    assert _resolve_grade_multiplier("F")[0] == 0.1  # F not in table → D scalar


def test_bottrade_has_unified_grade_fields_and_serializes():
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    t = BotTrade(
        id="abc123", symbol="NVDA", direction=TradeDirection.LONG,
        status=TradeStatus.PENDING, setup_type="gap_and_go", timeframe="intraday",
        quality_score=70, quality_grade="B", entry_price=100.0, current_price=100.0,
        stop_price=98.0, target_prices=[104.0], shares=10, risk_amount=20.0,
        potential_reward=40.0, risk_reward_ratio=2.0,
        tqs_score=82.0, tqs_grade="A", unified_grade="A", smb_grade="B",
    )
    d = t.to_dict()
    assert d["unified_grade"] == "A"
    assert d["tqs_grade"] == "A"
    assert d["tqs_score"] == 82.0
    # SMB retained for audit only.
    assert d["smb_grade"] == "B"


@pytest.mark.parametrize("doc,expected_unified,expected_tqs", [
    # 1. explicit unified grade wins
    ({"entry_context": {"tqs": {"unified_grade": "A", "post_gate_score": 90}}}, "A", "A"),
    # 2. post_gate_grade
    ({"entry_context": {"tqs": {"post_gate_grade": "B+", "post_gate_score": 78}}}, "B+", "B+"),
    # 3. grade derived from post_gate_score
    ({"entry_context": {"tqs": {"post_gate_score": 66}}}, "B", "B"),
    # 4. pre_gate score fallback
    ({"entry_context": {"tqs": {"pre_gate_score": 48}}}, "C", "C"),
    # 5. legacy quality_grade only (no tqs) → unified falls back, tqs empty
    ({"quality_grade": "B", "smb_grade": "C"}, "B", ""),
    # 6. smb_grade last resort
    ({"smb_grade": "C"}, "C", ""),
    # 7. nothing derivable
    ({}, "", ""),
])
def test_backfill_resolution_priority(doc, expected_unified, expected_tqs):
    bf = _load_backfill()
    unified, tqs_grade, _score = bf.resolve(doc)
    assert unified == expected_unified
    assert tqs_grade == expected_tqs


def test_backfill_grade_from_score_boundaries():
    bf = _load_backfill()
    assert bf.grade_from_score(85) == "A"
    assert bf.grade_from_score(75) == "B+"
    assert bf.grade_from_score(65) == "B"
    assert bf.grade_from_score(55) == "C+"
    assert bf.grade_from_score(45) == "C"
    assert bf.grade_from_score(35) == "D"
    assert bf.grade_from_score(10) == "F"
    assert bf.grade_from_score(0) == ""
    assert bf.grade_from_score(None) == ""
