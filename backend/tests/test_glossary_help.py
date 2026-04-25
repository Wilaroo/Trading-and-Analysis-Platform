"""
Contract tests for the help router + glossary service.

These confirm:
  - The frontend's glossaryData.js parses cleanly.
  - The compact chat block stays under the LLM context budget.
  - GET /api/help/terms returns the expected shape.
  - GET /api/help/terms/{id} round-trips a known term.
  - find_terms() honours the search query.

HTTP tests hit the live supervisor-running backend (same pattern as
test_system_health_and_testclient.py) to avoid the starlette/httpx
TestClient version incompatibility in this env.
"""
import pytest
import requests

from services.glossary_service import (
    find_terms,
    get_term,
    glossary_for_chat,
    load_glossary,
)


BASE = "http://localhost:8001"


def _up() -> bool:
    try:
        requests.get(f"{BASE}/api/health", timeout=2)
        return True
    except Exception:
        return False


# Known stable IDs the frontend depends on
KNOWN_IDS = {
    "backfill-readiness",
    "pre-train-interlock",
    "data-freshness-badge",
    "ib-pusher",
    "cmd-k",
    "gate-score",
}


# ---------------------------------------------------------------------------
# Service-level tests — run regardless of backend state
# ---------------------------------------------------------------------------

def test_glossary_parses_cleanly():
    data = load_glossary()
    assert isinstance(data, dict)
    cats = data.get("categories", [])
    entries = data.get("entries", [])
    assert len(cats) >= 5, f"expected ≥5 categories, got {len(cats)}"
    assert len(entries) >= 60, f"expected ≥60 entries (we shipped 77+), got {len(entries)}"
    for e in entries:
        assert e.get("id"), f"entry missing id: {e}"
        assert e.get("term"), f"entry missing term: {e}"
        assert e.get("shortDef"), f"entry missing shortDef: {e}"


def test_known_ids_present():
    found = {e.get("id") for e in load_glossary().get("entries", [])}
    missing = KNOWN_IDS - found
    assert not missing, f"missing critical glossary terms: {missing}"


def test_get_term_round_trip():
    e = get_term("backfill-readiness")
    assert e is not None
    assert e["term"] == "Backfill Readiness"
    assert "GREEN" in e["shortDef"]
    assert "queue_drained" in e.get("fullDef", ""), "fullDef should mention all 5 sub-checks"


def test_find_terms_query():
    results = find_terms("gate", limit=10)
    ids = {r.get("id") for r in results}
    assert "gate-score" in ids, f"gate-score should match 'gate' query, got {ids}"


def test_chat_block_full_fits():
    """With the production cap the full glossary should fit, so every
    critical term the model might be asked about is present."""
    block = glossary_for_chat(max_chars=10000)
    assert len(block) <= 10000
    assert "APP GLOSSARY" in block
    for needle in ("Backfill Readiness", "Pre-Train Interlock", "⌘K", "Gate Score"):
        assert needle in block, f"{needle!r} missing from chat glossary block"


def test_chat_block_truncation():
    """With a small cap the block must truncate cleanly."""
    block = glossary_for_chat(max_chars=300)
    assert len(block) <= 300
    assert block.endswith("...")


# ---------------------------------------------------------------------------
# HTTP tests — need live backend
# ---------------------------------------------------------------------------

pytestmark_http = pytest.mark.skipif(not _up(), reason="backend not running")


@pytestmark_http
def test_endpoint_list_terms():
    resp = requests.get(f"{BASE}/api/help/terms", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["categories"], list)
    assert isinstance(data["entries"], list)
    assert data["total"] >= 60


@pytestmark_http
def test_endpoint_search_query():
    resp = requests.get(f"{BASE}/api/help/terms", params={"q": "interlock"}, timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["query"] == "interlock"
    ids = {e.get("id") for e in data["entries"]}
    assert "pre-train-interlock" in ids


@pytestmark_http
def test_endpoint_fetch_known_term():
    resp = requests.get(f"{BASE}/api/help/terms/gate-score", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["entry"]["id"] == "gate-score"


@pytestmark_http
def test_endpoint_fetch_unknown_term():
    resp = requests.get(f"{BASE}/api/help/terms/this-id-does-not-exist", timeout=5)
    assert resp.status_code == 404
