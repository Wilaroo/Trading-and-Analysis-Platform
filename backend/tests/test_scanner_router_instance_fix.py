"""
Regression test for the scanner-router instance mismatch fix shipped
2026-04-29 (afternoon-15).

Background:
- Operator's `/api/scanner/detector-stats` returned `running: false,
  scan_count: 0` even AFTER `POST /api/live-scanner/start` confirmed
  the live scanner was running with `scan_count: 32, alerts_generated:
  7`. Two endpoints, two different scanner instances.
- Root cause: `routers/scanner.py:_scanner_service` was wired to the
  *predictive* scanner (via `init_scanner_router(predictive_scanner)`
  in server.py:443), but `_detector_evals`, `_detector_hits`,
  `_running`, `_scan_count` are attributes of the *enhanced* (live)
  scanner. So the diagnostic always reported the wrong scanner.

Fix: `detector-stats` now reads from `get_enhanced_scanner()`
directly so it reflects the scanner that actually emits alerts.
"""

from __future__ import annotations

from pathlib import Path

ROUTER_PATH = Path("/app/backend/routers/scanner.py")


def test_detector_stats_reads_enhanced_scanner_directly():
    """`/api/scanner/detector-stats` MUST import and call
    `get_enhanced_scanner()` rather than relying on the
    `_scanner_service` injected via `init_scanner_router` (which is
    the predictive scanner, not the live one).
    """
    src = ROUTER_PATH.read_text(encoding="utf-8")
    # Locate the detector-stats handler by its decorator.
    start = src.index('@router.get("/detector-stats")')
    # Bound by the next @router decorator OR end of file.
    end_candidates = [
        i for i in (
            src.find('@router.', start + 1),
            len(src),
        ) if i > start
    ]
    end = min(end_candidates)
    body = src[start:end]
    assert "from services.enhanced_scanner import get_enhanced_scanner" in body, (
        "detector-stats must import get_enhanced_scanner so it reads "
        "the scanner that owns the _detector_evals counters"
    )
    assert "live_scanner = get_enhanced_scanner()" in body, (
        "detector-stats must use a local `live_scanner` variable from "
        "get_enhanced_scanner() (NOT the global `_scanner_service` which "
        "is the predictive scanner)"
    )
    # All telemetry reads must reference live_scanner, never the
    # global _scanner_service.
    for attr in ("_detector_evals", "_detector_hits", "_running",
                 "_scan_count", "_symbols_scanned_last"):
        ref = f'getattr(live_scanner, "{attr}"'
        assert ref in body, f"detector-stats must read `{attr}` from live_scanner"
        bad = f'getattr(_scanner_service, "{attr}"'
        assert bad not in body, (
            f"detector-stats still reads `{attr}` from _scanner_service "
            f"(predictive scanner) — that's the regression"
        )
