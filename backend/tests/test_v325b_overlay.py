"""v325b — bracket geometry overlay static checks."""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "routers" / "sentcom_chart.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
BE = (ROOT / "backend" / "routers" / "sentcom_chart.py").read_text()
FE = (ROOT / "frontend" / "src" / "components" / "sentcom" / "panels" / "ChartPanel.jsx").read_text()


def test_backend_compiles():
    py_compile.compile(str(ROOT / "backend" / "routers" / "sentcom_chart.py"), doraise=True)


def test_reach_meta_endpoint_present():
    assert '@router.get("/chart/reach-meta")' in BE
    assert "symbol_adv_cache" in BE
    assert "daily_bars" in BE


def test_overlay_component_present():
    assert "ChartBracketGeometryOverlay" in FE
    assert "chart-bracket-geometry" in FE
    assert "reach-meta" in FE
    # Hold-window math mirrors backend _hsbg_hold_minutes
    assert "GEO_STYLE_HOLD_DAYS" in FE
    assert "Math.sqrt(holdMin / 390)" in FE
    # Same thresholds as the v325 reach gate
    assert "0.85" in FE and "1.5" in FE


def test_overlay_wired_into_chart():
    assert FE.count("<ChartBracketGeometryOverlay") == 1
    assert "reachMeta={reachMeta}" in FE
