"""v324 — infinite chart history scrolling + timeframe availability.

Static assertions that both halves of the patch are present and the
backend router still compiles. The /chart-history endpoint itself needs
the DGX Mongo (ib_historical_data) to return rows — covered by the
operator's manual curl after restart.
"""
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


def test_chart_history_endpoint_present():
    assert '@router.get("/chart-history")' in BE
    assert "_HISTORY_WARMUP_BARS" in BE
    assert "next_before" in BE
    # Must NOT route through get_bars (staleness fallback poisons prepends)
    history_section = BE.split('@router.get("/chart-history")')[1].split("@router.get")[0]
    assert "get_bars(" not in history_section


def test_available_timeframes_endpoint_present():
    assert '@router.get("/chart/available-timeframes")' in BE


def test_tail_default_days_aligned():
    assert '"1min": 7, "5min": 14, "15min": 30, "1hour": 60, "1day": 365' in BE


def test_frontend_days_doubling_removed():
    assert "daysLoaded" not in FE
    assert "MAX_DAYS_BACK" not in FE


def test_frontend_infinite_scroll_present():
    assert "fetchOlderHistory" in FE
    assert "chart-history?symbol=" in FE
    assert "hasMoreHistoryRef" in FE
    assert "historyCursorRef" in FE


def test_frontend_tf_availability_present():
    assert "available-timeframes" in FE
    assert "isTfAvailable" in FE
    assert "chart-history-loading" in FE
