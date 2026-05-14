"""v19.34.30 Patch A regression tests."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILES_TO_SCAN = [
    REPO / "backend/services/position_reconciler.py",
    REPO / "backend/services/trading_bot_service.py",
    REPO / "backend/services/bracket_reissue_service.py",
]


def test_no_target_order_ids_append_anywhere():
    offenders = []
    pat = re.compile(r"\.target_order_ids\s*\.\s*append\s*\(")
    for f in FILES_TO_SCAN:
        if not f.exists():
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, (
        "Patch A regression — `.target_order_ids.append(...)` still present:\n  "
        + "\n  ".join(offenders)
    )


def test_patch_a_comment_marker_present():
    f = REPO / "backend/services/position_reconciler.py"
    assert f.exists(), f"missing: {f}"
    assert "v19.34.30 Patch A" in f.read_text(), (
        "Patch A marker missing from position_reconciler.py"
    )
