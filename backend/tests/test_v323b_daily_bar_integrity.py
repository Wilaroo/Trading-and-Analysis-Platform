"""v323b — never persist today's in-progress daily bar.

A morning catch-up collection wrote partial today-bars (OXY 06-11
vol=589,273 collected 9:50 ET) which the scanner's F7 guard treated as
complete prior days → RVOL 0.09x → every setup blocked all session.
Verifies the guard helper exists and protects ALL THREE bar-write sites.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "ib_historical_collector.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "ib_historical_collector.py"
TEXT = SRC.read_text()


def test_guard_helper_exists():
    assert "def _is_inprogress_daily_bar(bar_size: str, bar_date) -> bool:" in TEXT
    assert '"day" not in str(bar_size).lower()' in TEXT
    assert "(16, 15)" in TEXT  # only complete after 16:15 ET


def test_all_three_write_sites_guarded():
    # 1 def + 3 call sites
    assert TEXT.count("_is_inprogress_daily_bar(") == 4
    # every update_one on the bar collection is preceded by the guard
    assert TEXT.count("# v323b — never persist today's in-progress daily bar") == 3


def test_intraday_bars_not_affected():
    # the guard short-circuits on bar_size: only '1 day' style sizes match
    i = TEXT.index("def _is_inprogress_daily_bar")
    block = TEXT[i:i + 1600]
    assert "return False" in block.split("ZoneInfo")[0]


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
