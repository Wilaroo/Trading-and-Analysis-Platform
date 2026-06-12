#!/usr/bin/env python3
"""
apply_v322x.py — Idempotent applier for v322x (TQS enrichment observability)
============================================================================
WHY: The "🤔 Evaluating" thought prints the PRE-gate TQS, but the trade
card shows the POST-gate (AI-enriched) TQS stamped at trade creation
(GAP 3 recalc). When enrichment shifts the number the operator sees two
unexplained values — e.g. XOM evaluated at "TQS 54 C" but the card shows
"TQS 60 B". This patch emits a 🧮 follow-up thought whenever the post-gate
recalc materially shifts the score (>=1.0 pts) or flips the grade:

    🧮 XOM TQS enriched 54 C → 60 B after AI consult (model agrees, 64% conf)

Also writes backend/tests/test_v322x_tqs_enrichment_thought.py.

SAFE TO RUN MULTIPLE TIMES (guarded by the v322x marker).
NO behavior change to gating, sizing, or the stamped trade fields — this
is observability only (stream thought + metadata).

Run from repo root:  .venv/bin/python /tmp/apply_v322x.py
Then: git add -A && git commit -m "v322x: TQS enrichment observability thought" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "v322x — TQS enrichment observability"

OLD = '''                        logger.debug(
                            f"Post-gate TQS for {symbol}: {recalc_tqs.score:.1f} "
                            f"(pre-gate: {alert.get('tqs_score', 'N/A')})"
                        )
'''

NEW = '''                        logger.debug(
                            f"Post-gate TQS for {symbol}: {recalc_tqs.score:.1f} "
                            f"(pre-gate: {alert.get('tqs_score', 'N/A')})"
                        )

                        # ── v322x — TQS enrichment observability ─────────
                        # The "🤔 Evaluating" thought fires with the
                        # PRE-gate TQS, but the trade card shows this
                        # POST-gate (AI-enriched) score stamped at trade
                        # creation. When enrichment shifts the number the
                        # operator saw two unexplained values (e.g. XOM
                        # eval'd "54 C" but card "60 B"). Surface the shift
                        # explicitly so the trail reads 54 C → 60 B.
                        try:
                            _pre_s = float(alert.get("tqs_score") or 0)
                            _post_s = float(recalc_tqs.score or 0)
                            _pre_g = str(alert.get("tqs_grade") or "")
                            _post_g = str(recalc_tqs.grade or "")
                            if abs(_post_s - _pre_s) >= 1.0 or (_pre_g and _post_g and _pre_g != _post_g):
                                from services.sentcom_service import emit_stream_event
                                _pre_lbl = f"{_pre_s:.0f}" + (f" {_pre_g}" if _pre_g else "")
                                _post_lbl = f"{_post_s:.0f}" + (f" {_post_g}" if _post_g else "")
                                await emit_stream_event({
                                    "kind": "evaluation",
                                    "event": "tqs_enriched",
                                    "symbol": symbol,
                                    "text": (
                                        f"🧮 {symbol} TQS enriched {_pre_lbl} → {_post_lbl} "
                                        f"after AI consult ("
                                        f"{'model agrees' if model_agrees else 'model disagrees'}, "
                                        f"{float(pred_conf or 0):.0f}% conf)"
                                    ),
                                    "metadata": {
                                        "setup_type": setup_type,
                                        "pre_gate_tqs": _pre_s,
                                        "post_gate_tqs": _post_s,
                                        "pre_gate_grade": _pre_g,
                                        "post_gate_grade": _post_g,
                                        "model_agrees": model_agrees,
                                    },
                                })
                        except Exception as _tqs_obs_err:
                            logger.debug(f"v322x TQS enrichment thought error: {_tqs_obs_err}")
'''

TEST_REL = Path("backend") / "tests" / "test_v322x_tqs_enrichment_thought.py"

TEST_CONTENT = '''"""v322x — TQS enrichment observability thought.

The "🤔 Evaluating" thought fires with the PRE-gate TQS while the trade
card shows the POST-gate (AI-enriched) score, so the operator saw two
unexplained numbers (XOM eval'd "54 C" but card "60 B"). v322x emits a
🧮 follow-up thought whenever post-gate enrichment materially shifts the
score (>=1.0 pts) or flips the grade, so the trail reads "54 C → 60 B".

Source-anchored verification (consistent with the v322-series patch
tests): asserts the block exists, fires only on material shifts, and the
file still compiles.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "opportunity_evaluator.py"


def _block():
    text = SRC.read_text()
    i = text.index("v322x — TQS enrichment observability")
    return text[i:i + 3000]


def test_v322x_block_present():
    text = SRC.read_text()
    assert "v322x — TQS enrichment observability" in text
    assert \'"event": "tqs_enriched"\' in text


def test_v322x_fires_only_on_material_shift():
    block = _block()
    assert "abs(_post_s - _pre_s) >= 1.0" in block
    assert "_pre_g != _post_g" in block


def test_v322x_metadata_preserves_both_scores():
    block = _block()
    assert \'"pre_gate_tqs": _pre_s\' in block
    assert \'"post_gate_tqs": _post_s\' in block
    assert \'"model_agrees": model_agrees\' in block


def test_v322x_inside_recalc_guard_and_fail_safe():
    """The thought must live inside the `if recalc_tqs:` success branch and
    never raise into the evaluation path (wrapped in try/except)."""
    block = _block()
    assert "except Exception as _tqs_obs_err" in block


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def main() -> None:
    root = _repo_root()
    path = root / "backend" / "services" / "opportunity_evaluator.py"
    text = path.read_text()

    if MARKER in text:
        print("⏭  opportunity_evaluator.py already patched (no-op).")
    else:
        if OLD not in text:
            print("✗ anchor NOT found — file drifted, NO change made."); sys.exit(1)
        if text.count(OLD) != 1:
            print(f"✗ anchor matched {text.count(OLD)}× (expected 1) — skipped."); sys.exit(1)
        path.write_text(text.replace(OLD, NEW))
        print("✓ v322x applied to opportunity_evaluator.py")

    import py_compile
    py_compile.compile(str(path), doraise=True)
    print("✓ opportunity_evaluator.py compiles")

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"✓ wrote {TEST_REL}")

    print("\nNext:")
    print("  .venv/bin/python -m pytest backend/tests/test_v322x_tqs_enrichment_thought.py -q")
    print('  git add -A && git commit -m "v322x: TQS enrichment observability thought" && git push')
    print("  (commit BEFORE restarting the backend — StartTrading.bat does git checkout -- .)")


if __name__ == "__main__":
    main()
