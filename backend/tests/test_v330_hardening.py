"""v330 — INT-21 range-break hardening + sector word-start matching +
content-based thought TTL tiering.

1. enhanced_scanner._check_range_break gains four guards: ≥60min session
   age, HOD-LOD ≥ 0.6×ATR, RVOL sanity band (0.2-50), snapshot ≤5min old.
2. sector_tag_service._industry_to_etf matches keys only at word starts:
   "Cosmetics & Toiletries" no longer hits "oil" (was XLE), "Aerospace &
   Defense" no longer hits the "spac" blocklist (was None).
3. sentcom_service kind="thought" rows with generic skipped/passing text
   join the 7d noise TTL tier (signal thoughts keep 190d).
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "sentcom_service.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
SCANNER = (ROOT / "backend" / "services" / "enhanced_scanner.py").read_text()
SECTOR = (ROOT / "backend" / "services" / "sector_tag_service.py").read_text()
SENTCOM = (ROOT / "backend" / "services" / "sentcom_service.py").read_text()


# ── 1. range-break hardening (source assertions) ────────────────────────

def test_range_break_session_age_gate():
    i = SCANNER.index("async def _check_range_break")
    block = SCANNER[i:i + 2500]
    assert "mins_since_open" in block and "< 60" in block


def test_range_break_min_range_vs_atr():
    i = SCANNER.index("async def _check_range_break")
    block = SCANNER[i:i + 2500]
    assert "rng < 0.6 * _atr" in block


def test_range_break_rvol_sanity_band():
    i = SCANNER.index("async def _check_range_break")
    block = SCANNER[i:i + 2500]
    assert "0.2 <= float(snapshot.rvol or 0) <= 50.0" in block


def test_range_break_snapshot_freshness():
    i = SCANNER.index("async def _check_range_break")
    block = SCANNER[i:i + 2500]
    assert "total_seconds() > 300" in block


# ── 2. sector word-start matching (functional) ──────────────────────────

def test_sector_wordstart_matching():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from services.sector_tag_service import _industry_to_etf
    assert _industry_to_etf("Cosmetics & Toiletries") == "XLP"
    assert _industry_to_etf("Aerospace & Defense") == "XLI"
    assert _industry_to_etf("Oil & Gas Exploration") == "XLE"
    assert _industry_to_etf("Gasoline Distribution") == "XLE"
    assert _industry_to_etf("Railroads") == "XLI"
    assert _industry_to_etf("Biotechnology") == "XLV"
    assert _industry_to_etf("REIT - Industrial") == "XLRE"
    assert _industry_to_etf("SPAC") is None
    assert _industry_to_etf("Personal Products") == "XLP"


# ── 3. content-based thought TTL tier ───────────────────────────────────

def test_noise_content_regex_defined():
    assert "_NOISE_CONTENT_RE" in SENTCOM
    assert 'snapshot unavailable' in SENTCOM


def test_persist_applies_content_tier_to_thought_kind():
    i = SENTCOM.index('_doc_kind == "thought"')
    block = SENTCOM[i - 300:i + 300]
    assert "_NOISE_CONTENT_RE.search" in block
    assert "expires_at" in block


def test_noise_regex_classification():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from services.sentcom_service import _NOISE_CONTENT_RE
    assert _NOISE_CONTENT_RE.search("IGV skipped — no intraday bars (snapshot unavailable)")
    assert _NOISE_CONTENT_RE.search("Passing on NVDA — RVOL 0.8x below floor")
    assert not _NOISE_CONTENT_RE.search("ENTERED IGV long 3 legs OCA — scalp")
    assert not _NOISE_CONTENT_RE.search("PT1 filled +0.8R, trailing stop moved to BE")


def test_files_compile():
    for rel in ("enhanced_scanner.py", "sector_tag_service.py", "sentcom_service.py"):
        py_compile.compile(str(ROOT / "backend" / "services" / rel), doraise=True)
