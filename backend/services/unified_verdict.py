"""Unified verdict resolver — the single decision authority (P3, Seam 3).

Today TWO authorities fight: the TQS grade (quality) and the Confidence Gate
(AI conviction), each with an independent SKIP and an independent size
multiplier (they stack -> double-discount). This module collapses them into ONE
verdict {decision, size_mult, grade, reasons} under the operator-chosen policy:

  1a (TQS-anchored): quality leads, AI conviction MODULATES.
     - gate GO            -> trade FULL grade size.
     - gate non-GO/absent -> trade SMALLER (one REDUCE step), NOT killed,
                             UNLESS a hard veto (grade F / explicit force-skip)
                             or BOTH are weak (grade D + non-GO) -> SKIP.
       => unwinds the gate's silent over-veto of high-TQS setups.
  2a (single multiplier): size = grade_mult x (REDUCE_STEP if reduced else 1.0).
     No second continuous gate multiplier -> kills the double-discount.

Also exposes the A2 "gate-off" (TQS-only) policy and a champion summariser so
the shadow-arm harness can score all three arms on the same footing.

PURE FUNCTIONS — no I/O, no side effects. Safe to call in the hot scan path.
"""

GRADE_MULT = {"A": 1.0, "B": 0.7, "C": 0.3, "D": 0.1, "F": 0.0}
REDUCE_STEP = 0.6
# Position multiplier on a SOFT regime suppression — mirrors
# regime_expectancy_calibrator.REDUCE_MULT and
# confidence_gate.REGIME_SUPPRESSION_REDUCE_MULT (kept in sync).
REGIME_REDUCE_MULT = 0.4
GO, REDUCE, SKIP = "GO", "REDUCE", "SKIP"
ARMS = ("champion", "unified_1a2a", "gate_off", "regime_fit")


def _norm_grade(grade):
    g = str(grade or "").strip().upper()[:1]
    return g if g in GRADE_MULT else ""


def grade_from_score(tqs_score):
    """Static fallback band when no calibrated grade is supplied."""
    try:
        s = float(tqs_score)
    except (TypeError, ValueError):
        return "F"
    if s >= 80:
        return "A"
    if s >= 68:
        return "B"
    if s >= 55:
        return "C"
    if s >= 40:
        return "D"
    return "F"


def _resolve_grade(grade, tqs_score):
    return _norm_grade(grade) or grade_from_score(tqs_score)


def resolve_unified_verdict(grade, gate_result=None, *, tqs_score=None, hard_veto=False):
    """Arm A1 — policy 1a (TQS-anchored) + 2a (single grade-base multiplier)."""
    g = _resolve_grade(grade, tqs_score)
    base = GRADE_MULT[g]
    gate_decision = None
    if gate_result:
        gd = gate_result.get("decision")
        gate_decision = str(gd).upper() if gd else None
    reasons = [f"TQS grade {g} (quality anchor)"]

    if hard_veto or g == "F":
        reasons.append("hard veto" if hard_veto else "grade F floor")
        return {"decision": SKIP, "size_mult": 0.0, "grade": g, "reasons": reasons}

    if gate_decision == GO:
        reasons.append("AI conviction GO -> full grade size")
        return {"decision": GO, "size_mult": round(base, 3), "grade": g, "reasons": reasons}

    # Non-GO gate (REDUCE / SKIP / absent): quality-led — size down, don't kill,
    # UNLESS both are weak (grade D + non-GO).
    if g == "D":
        reasons.append(f"grade D + AI {gate_decision or 'absent'} (both weak) -> SKIP")
        return {"decision": SKIP, "size_mult": 0.0, "grade": g, "reasons": reasons}
    reasons.append(f"AI {gate_decision or 'absent'} (not GO) -> size down, not killed")
    return {"decision": REDUCE, "size_mult": round(base * REDUCE_STEP, 3), "grade": g, "reasons": reasons}


def resolve_tqs_only(grade, *, tqs_score=None):
    """Arm A2 — gate-OFF: TQS grade decides, AI conviction ignored."""
    g = _resolve_grade(grade, tqs_score)
    if g == "F":
        return {"decision": SKIP, "size_mult": 0.0, "grade": g,
                "reasons": ["gate-off: grade F -> SKIP"]}
    return {"decision": GO, "size_mult": round(GRADE_MULT[g], 3), "grade": g,
            "reasons": [f"gate-off: TQS grade {g} -> GO @ grade size"]}


def champion_verdict(champion_decision, *, grade=None, tqs_score=None, conf_mult=1.0):
    """Summarise what the LIVE dual-gate pipeline decided (baseline arm).

    Champion size reflects the stacked reality grade_mult x gate_multiplier.
    """
    d = str(champion_decision or "").upper()
    if d not in (GO, REDUCE, SKIP):
        d = SKIP
    g = _resolve_grade(grade, tqs_score)
    try:
        cm = float(conf_mult) if conf_mult is not None else 1.0
    except (TypeError, ValueError):
        cm = 1.0
    sm = 0.0 if d == SKIP else round(GRADE_MULT[g] * cm, 3)
    return {"decision": d, "size_mult": sm, "grade": g,
            "reasons": [f"live dual-gate -> {d}"]}


def resolve_regime_fit(grade, gate_result=None, *, tqs_score=None, hard_veto=False,
                       regime_suppression=None):
    """Arm A3 — the unified verdict (A1) + DIRECTIVE regime-fit abstention (P4).

    Layers the T6 data-driven per-(setup x direction x regime-band) expectancy
    verdict ON TOP of the unified verdict so we can measure, in shadow, whether
    standing down in statistically-hostile regimes improves the book:

      regime_suppression.action == SKIP   -> ABSTAIN (stand down, size 0)
                                             [hostile cell: weighted_mean_R <= hard_r]
      regime_suppression.action == REDUCE -> size down x REGIME_REDUCE_MULT,
                                             GO downgraded to REDUCE
                                             [soft-hostile: weighted_mean_R <= soft_r]
      NONE / absent / insufficient data   -> the unified verdict, UNCHANGED.

    `regime_suppression` is the dict the Confidence Gate already attaches to its
    result (`gate_result["regime_suppression"]`). PURE — no I/O.
    """
    v = resolve_unified_verdict(grade, gate_result, tqs_score=tqs_score, hard_veto=hard_veto)
    action, reason = "", ""
    if isinstance(regime_suppression, dict):
        action = str(regime_suppression.get("action") or "").upper()
        reason = str(regime_suppression.get("reason") or "")

    # Already killed upstream, or no actionable regime signal -> pass through.
    if v["decision"] == SKIP or action not in (SKIP, REDUCE):
        if action == "NONE" and reason:
            v["reasons"].append("regime-fit: regime cell OK (no abstention)")
        return v

    if action == SKIP:
        v["decision"] = SKIP
        v["size_mult"] = 0.0
        v["reasons"].append(f"regime-fit ABSTAIN — hostile regime ({reason})")
    else:  # REDUCE
        v["decision"] = REDUCE
        v["size_mult"] = round(v["size_mult"] * REGIME_REDUCE_MULT, 3)
        v["reasons"].append(f"regime-fit size-down x{REGIME_REDUCE_MULT} — soft-hostile ({reason})")
    return v
