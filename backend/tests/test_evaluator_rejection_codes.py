"""
Regression tests for the evaluator rejection-reason split shipped
2026-04-29 (afternoon-14).

Background:
- Operator's diagnostic curl on `/api/trading-bot/rejection-analytics`
  showed `evaluator_veto: 18 rejections` with no breakdown of which
  gate actually dropped the trade. Backend log grep revealed two real
  bugs hidden behind the generic label:
    1. Python NameError: `cannot access local variable
       'ai_consultation_result' where it is not associated with a
       value` — INTC backside hit this every cycle.
    2. R:R rejections at 1.95 / 1.99 / 2.0 because risk_params
       `min_risk_reward = 2.5` was too tight.

- Fix: initialise `ai_consultation_result = None` early, and split
  `evaluator_veto` into specific reason codes
  (`no_price`, `smart_filter_skip`, `gate_skip`,
   `position_size_zero`, `rr_below_min`, `ai_consultation_block`,
   `evaluator_exception`, `evaluator_veto_unknown`) so the dashboard
  shows precisely why each trade was dropped.

Tests assert the contracts via direct source inspection — full
end-to-end coverage requires the bot service + IB pusher running.
"""

from __future__ import annotations

import re
from pathlib import Path

EVALUATOR_PATH = Path("/app/backend/services/opportunity_evaluator.py")
BOT_PATH = Path("/app/backend/services/trading_bot_service.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ai_consultation_result_initialised_before_use():
    """`ai_consultation_result` MUST be initialised in the function
    scope BEFORE `build_entry_context` references it. Without the
    early init, every evaluation that reaches `build_entry_context`
    raises `UnboundLocalError`.
    """
    src = _read(EVALUATOR_PATH)
    # Find init position
    init_pos = src.find("ai_consultation_result: Optional[Dict[str, Any]] = None")
    assert init_pos > 0, "Early init of ai_consultation_result missing"
    # Find first read position
    first_use = src.find("ai_consultation_result=ai_consultation_result")
    assert first_use > 0, "build_entry_context call missing"
    assert init_pos < first_use, (
        "Init must come BEFORE the first read in build_entry_context"
    )


def test_evaluator_records_specific_reasons():
    """Each `return None` path in `evaluate_opportunity` MUST call
    `bot.record_rejection(...)` with a specific `reason_code`. The
    catch-all `evaluator_veto_unknown` is reserved for paths that
    haven't been mapped yet (regression-detection for new code).
    """
    src = _read(EVALUATOR_PATH)
    expected_codes = [
        '"no_price"',
        '"smart_filter_skip"',
        '"gate_skip"',
        '"position_size_zero"',
        '"rr_below_min"',
        '"ai_consultation_block"',
        '"evaluator_exception"',
    ]
    for code in expected_codes:
        assert code in src, f"Missing rejection reason_code {code}"


def test_record_rejection_sets_evaluator_flag():
    """`TradingBotService.record_rejection` MUST set
    `self._last_evaluator_rejection_recorded = True` so the catch-all
    in `_scan_for_setups` knows whether a specific reason was already
    captured. Without this, every specific rejection would also fire
    `evaluator_veto_unknown`, double-counting in the analytics.
    """
    src = _read(BOT_PATH)
    rec_def_idx = src.find("def record_rejection(")
    assert rec_def_idx > 0
    # Find the next `def ` to bound the function body.
    body_end = src.find("\n    def ", rec_def_idx + 10)
    body = src[rec_def_idx:body_end]
    assert "self._last_evaluator_rejection_recorded = True" in body, (
        "record_rejection must set the flag so catch-all doesn't double-count"
    )


def test_scan_for_setups_resets_and_checks_flag():
    """The scan loop in `_scan_for_setups` MUST:
    1. Reset `_last_evaluator_rejection_recorded = False` BEFORE
       calling `_evaluate_opportunity`.
    2. Only fire `evaluator_veto_unknown` if the flag is still False
       after evaluation.
    """
    src = _read(BOT_PATH)
    # Find the section between `mark_fired` and the catch-all.
    mark_fired_idx = src.find("_dedup.mark_fired(symbol, setup, direction)")
    assert mark_fired_idx > 0
    catchall_idx = src.find('reason_code="evaluator_veto_unknown"', mark_fired_idx)
    assert catchall_idx > 0, "Catch-all evaluator_veto_unknown missing"
    section = src[mark_fired_idx:catchall_idx]
    assert "self._last_evaluator_rejection_recorded = False" in section, (
        "Flag must be reset before _evaluate_opportunity"
    )
    # The catch-all must be guarded by `if not getattr(...)`.
    catchall_guard = src[max(0, catchall_idx - 800):catchall_idx]
    assert 'getattr(self, "_last_evaluator_rejection_recorded"' in catchall_guard, (
        "Catch-all must be guarded by the flag check"
    )


def test_compose_rejection_narrative_handles_new_codes():
    """Each new reason_code MUST have a narrative branch in
    `_compose_rejection_narrative`. Otherwise the bot's V5 panel falls
    back to the generic "Passing on X — Y. Reason code: Z." template.
    """
    src = _read(BOT_PATH)
    new_codes = [
        '"no_price"',
        '"smart_filter_skip"',
        '"gate_skip"',
        '"position_size_zero"',
        '"rr_below_min"',
        '"ai_consultation_block"',
        '"evaluator_exception"',
        '"evaluator_veto_unknown"',
    ]
    for code in new_codes:
        assert f"reason_code == {code}" in src, (
            f"Missing narrative branch for {code} in _compose_rejection_narrative"
        )
