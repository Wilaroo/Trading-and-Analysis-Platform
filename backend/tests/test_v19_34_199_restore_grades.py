"""
v19.34.199 — restore_open_trades grade hydration.

Bug: `restore_open_trades` constructed BotTrade with a hardcoded field
subset that omitted unified_grade/tqs_grade/tqs_score, so multi-day swing
trades came back with EMPTY grades on every boot and the next persist
overwrote the DB (incl. the v175 backfill). The UI then fell back to the
legacy quality_grade and mislabeled it "TQS".

These tests pin `resolve_restore_grades` — the pure resolver the restore
path now calls.
"""
from services.bot_persistence import resolve_restore_grades


def test_prefers_top_level_unified_when_present():
    doc = {"unified_grade": "A", "tqs_grade": "A", "tqs_score": 90,
           "quality_grade": "B"}
    ug, tg, ts, smb = resolve_restore_grades(doc, {})
    assert ug == "A"
    assert tg == "A"
    assert ts == 90.0


def test_swing_trade_derives_real_tqs_from_context():
    # The exact live failure: empty top-level grades, quality=B, but the
    # captured TQS context says C+. unified MUST be C+ (honest), NOT B.
    doc = {"unified_grade": "", "tqs_grade": "", "tqs_score": 0,
           "quality_grade": "B", "smb_grade": "B"}
    ec = {"tqs": {"unified_grade": "C+", "post_gate_grade": "C+", "score": 56}}
    ug, tg, ts, smb = resolve_restore_grades(doc, ec)
    assert ug == "C+"          # real TQS, not the legacy B
    assert tg == "C+"
    assert ts == 56.0
    assert smb == "B"


def test_post_gate_grade_fallback():
    doc = {"quality_grade": "B"}
    ec = {"tqs": {"post_gate_grade": "B+", "post_gate_score": 78}}
    ug, tg, ts, _ = resolve_restore_grades(doc, ec)
    assert ug == "B+"
    assert tg == "B+"
    assert ts == 78.0


def test_no_tqs_context_falls_back_to_quality_for_unified_only():
    # Reconciled / legacy trade with no TQS context: unified uses the
    # legacy/quality grade (matches the v175 backfill), but tqs_grade
    # stays EMPTY (TQS-specific — no legacy contamination).
    doc = {"quality_grade": "R", "smb_grade": "R"}
    ug, tg, ts, smb = resolve_restore_grades(doc, {})
    assert ug == "R"
    assert tg == ""            # no fake TQS grade for non-TQS trades
    assert ts == 0.0
    assert smb == "R"


def test_empty_everything():
    ug, tg, ts, smb = resolve_restore_grades({}, None)
    assert ug == ""
    assert tg == ""
    assert ts == 0.0
    assert smb == ""


def test_bad_tqs_score_coerces_to_zero():
    doc = {"unified_grade": "C", "tqs_score": "not-a-number"}
    ug, tg, ts, _ = resolve_restore_grades(doc, {})
    assert ug == "C"
    assert ts == 0.0
