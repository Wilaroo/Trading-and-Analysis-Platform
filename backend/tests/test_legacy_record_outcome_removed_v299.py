"""
v19.34.299 — Audit Phase 7: removal of the dishonest legacy outcome writer.

Deleted:
  - `enhanced_scanner.EnhancedBackgroundScanner.record_alert_outcome` (method)
  - `POST /stats/record-outcome` route in routers/live_scanner.py (its only caller)

The legacy writer was reachable ONLY via that manual route (no autonomous caller)
and was dishonest: non-idempotent insert, wrong base key `split("_")[0]`,
projected-R win fallback, −1R loss cap, double-EV. Honest capture lives in
`pnl_compute._record_alert_outcome_bestEffort` + `recompute_strategy_stats_for_setup`.

REGRESSION GUARD: the unrelated `POST /api/ev/record-outcome`
(routers/ev_tracking.py → ev_tracking_service) is a DIFFERENT route and MUST
remain intact.
"""
from routers.ev_tracking import router as ev_router
from routers.live_scanner import router as live_scanner_router
from services.enhanced_scanner import EnhancedBackgroundScanner


def test_legacy_method_removed_from_scanner():
    assert not hasattr(EnhancedBackgroundScanner, "record_alert_outcome"), (
        "legacy record_alert_outcome must be deleted from the scanner"
    )


def test_legacy_route_removed_from_live_scanner():
    paths = [r.path for r in live_scanner_router.routes]
    assert "/stats/record-outcome" not in paths, (
        "legacy /stats/record-outcome route must be deleted"
    )


def test_live_scanner_other_routes_intact():
    """Deletion must not collateral-damage the rest of the live_scanner router."""
    paths = [r.path for r in live_scanner_router.routes]
    # Spot-check a couple of sibling routes that share the file.
    assert any("/auto-execute/enable" in p for p in paths)
    assert any("/stats/strategies" in p for p in paths)


def test_legit_ev_tracking_route_survives():
    """The similarly-named, LEGITIMATE ev-tracking route must be untouched."""
    paths = [r.path for r in ev_router.routes]
    assert any(p.endswith("/record-outcome") for p in paths), (
        "ev_tracking /record-outcome (the real one) must remain"
    )
