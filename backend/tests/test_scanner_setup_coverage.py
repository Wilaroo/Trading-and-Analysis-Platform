"""
Regression test for the `/api/scanner/setup-coverage` diagnostic
shipped 2026-04-29 (afternoon-15).

Background:
- Operator's `/api/scanner/detector-stats` showed only 14 of the 35
  setups in `_enabled_setups` were being evaluated, and 12 of those
  14 had 0 cumulative hits across 101 evaluations each. We needed a
  single curl that distinguishes:
    * orphan names (enabled but no registered checker)
    * silent detectors (registered + 0 hits)
    * active detectors (registered + ≥1 hit)
    * unenabled-with-checkers (code exists, bot won't ask for it)

- Before this endpoint, identifying the orphan names required
  grepping `enhanced_scanner.py` for the `checkers = {...}` dict and
  diffing against `_enabled_setups`. Now it's one curl.
"""

from __future__ import annotations

from pathlib import Path

ROUTER_PATH = Path("/app/backend/routers/scanner.py")


def test_setup_coverage_endpoint_registered():
    """`@router.get("/setup-coverage")` MUST be registered and read
    from `get_enhanced_scanner()` (not the legacy `_scanner_service`).
    """
    src = ROUTER_PATH.read_text(encoding="utf-8")
    assert '@router.get("/setup-coverage")' in src, (
        "setup-coverage endpoint not registered"
    )
    handler_idx = src.index("def get_setup_coverage")
    body = src[handler_idx:src.index("\n\n", handler_idx + 50)]
    # Must read from the live scanner.
    assert "from services.enhanced_scanner import get_enhanced_scanner" in src[handler_idx:handler_idx + 4000]
    # Must NOT read from the wrong (predictive) scanner singleton.
    assert "_scanner_service" not in src[handler_idx:src.index('@router.get("/summary")')]


def test_scanner_router_imports_dict_and_any():
    """Regression: the `setup-coverage` endpoint uses `Dict[...]` and
    `Any` type hints; they must be imported at module top. Otherwise
    every call returns `500: NameError: name 'Dict' is not defined`
    (afternoon-15b ran into this on DGX deploy).
    """
    src = ROUTER_PATH.read_text(encoding="utf-8")
    # Module-level typing imports.
    typing_imports = next(
        line for line in src.splitlines() if line.startswith("from typing import")
    )
    assert "Dict" in typing_imports, "scanner.py must `from typing import ..., Dict`"
    assert "Any" in typing_imports, "scanner.py must `from typing import ..., Any`"


def test_scanner_router_module_imports_cleanly():
    """Smoke: the router module must import without raising. Catches
    any future missing-import regressions immediately, vs only
    surfacing as 500 errors at runtime.
    """
    import importlib
    import sys
    sys.path.insert(0, "/app/backend")
    try:
        # Reimport to bypass cached state.
        if "routers.scanner" in sys.modules:
            importlib.reload(sys.modules["routers.scanner"])
        else:
            importlib.import_module("routers.scanner")
    finally:
        sys.path.pop(0)


def test_setup_coverage_partitions_match_contract():
    """The four partition lists in the response MUST be present and
    have intuitive contracts:

      orphan_enabled_setups   → enabled - registered
      silent_detectors        → enabled ∩ registered, hits == 0
      active_detectors        → enabled ∩ registered, hits > 0
      unenabled_with_checkers → registered - enabled
    """
    src = ROUTER_PATH.read_text(encoding="utf-8")
    handler_idx = src.index("def get_setup_coverage")
    body = src[handler_idx:src.index('@router.get("/summary")', handler_idx)]
    # Partition keys
    for key in (
        "orphan_enabled_setups",
        "silent_detectors",
        "active_detectors",
        "unenabled_with_checkers",
    ):
        assert f'"{key}"' in body, f"Missing partition `{key}` in response shape"
    # Set-algebra contracts
    assert "enabled - registered" in body
    assert "registered - enabled" in body
    assert "cum_hits.get(s, 0) == 0" in body
    assert "cum_hits.get(s, 0) > 0" in body
