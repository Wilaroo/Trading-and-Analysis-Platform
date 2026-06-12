"""v333 — System Integrity briefing infrastructure.

Backend: routers/integrity_router.py
  GET /api/integrity/morning-report — session scorecard (scalps, data
      uptime, ingest freshness, daily-bar leak v328, backfill gate,
      M0 ladder, regime + demotions v332, integrity-event severities)
  GET /api/integrity/feed — state_integrity_events merged with per-trade
      regime-demotion stop moves (old → new stop, auditable)

Frontend: Integrity button in BriefingsCompactStrip → deep-dive modal
  (briefingKey="integrity") renders IntegrityBody at the top of the
  scroll area; IntegrityCardV5 also added to the BriefingsV5 panel.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "routers" / "integrity_router.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
ROUTER = (ROOT / "backend" / "routers" / "integrity_router.py").read_text()
SERVER = (ROOT / "backend" / "server.py").read_text()
STRIP = (ROOT / "frontend" / "src" / "components" / "sentcom" / "v5" /
         "BriefingsCompactStrip.jsx").read_text()
MODAL = (ROOT / "frontend" / "src" / "components" /
         "MorningBriefingModal.jsx").read_text()
CARD = (ROOT / "frontend" / "src" / "components" / "sentcom" / "v5" /
        "IntegrityCardV5.jsx").read_text()


def test_router_compiles_and_has_endpoints():
    py_compile.compile(str(ROOT / "backend" / "routers" / "integrity_router.py"),
                       doraise=True)
    assert '@router.get("/morning-report")' in ROUTER
    assert '@router.get("/feed")' in ROUTER
    assert 'prefix="/api/integrity"' in ROUTER


def test_router_checks_cover_week_fixes():
    for check in ("scalps_fired", "data_uptime", "ingest_freshness",
                  "daily_bar_leak", "backfill_gate", "m0_ladder",
                  "regime", "integrity_events"):
        assert f'"{check}"' in ROUTER, check


def test_feed_includes_regime_demotion_stop_moves():
    assert "regime_demotion_stop_move" in ROUTER
    assert "stop_adjustments" in ROUTER
    assert "old_stop" in ROUTER and "new_stop" in ROUTER


def test_server_registers_router():
    assert "from routers.integrity_router import" in SERVER
    assert "init_integrity_router(db)" in SERVER


def test_strip_has_integrity_button():
    assert '"integrity"' in STRIP or "'integrity'" in STRIP
    assert "ShieldCheck" in STRIP
    assert "windowStart == null" in STRIP or "windowStart === null" in STRIP \
        or "def.windowStart == null" in STRIP


def test_modal_has_integrity_variant_and_body():
    assert "integrity: {" in MODAL
    assert "IntegrityBody" in MODAL
    assert "briefingKey === 'integrity'" in MODAL


def test_card_exports():
    assert "export const useIntegrityReport" in CARD
    assert "export const IntegrityBody" in CARD
    assert "export const IntegrityCardV5" in CARD
    assert "data-testid=\"integrity-feed\"" in CARD
