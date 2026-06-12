"""v323c — tiered sentcom_thoughts retention.

Noise kinds (scan/skip/filter/info) expire at 7d via per-doc expires_at +
TTL(0) index; signal kinds (evaluation/fill/rejection/thought/alert/
system/brain) keep the full 190d created_at TTL.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "sentcom_service.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "sentcom_service.py"
TEXT = SRC.read_text()


def test_noise_tiers_defined():
    assert '_SCAN_NOISE_KINDS = {"scan", "skip", "filter", "info"}' in TEXT
    assert "_NOISE_TTL_DAYS = 7" in TEXT
    assert "_THOUGHTS_TTL_DAYS = 190" in TEXT


def test_expires_at_index_created():
    assert 'col.create_index("expires_at", expireAfterSeconds=0, name="expires_at_ttl")' in TEXT


def test_persist_sets_expiry_only_for_noise():
    i = TEXT.index('"expires_at": _now + timedelta(days=_NOISE_TTL_DAYS)')
    block = TEXT[i - 200:i + 200]
    assert "_doc_kind in _SCAN_NOISE_KINDS" in block


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
