"""
test_v322e_sector_backfill.py — contract tests for the v322e paced
deep sector backfill.

What we guard:
  1. `order_backfill_targets` is rated-first, deduped, capped.
  2. `deep_backfill_untagged` tags untagged symbols through
     `tag_symbol_async`, updates progress state, and reports a summary.
  3. Circuit breaker: consecutive misses while IB Client-11 is down
     abort the run with a clear hint (no 3,000-symbol futile crawl).
  4. The scanner router exposes the start + status endpoints.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.sector_tag_service import (  # noqa: E402
    SectorTagService,
    order_backfill_targets,
)


# ───────────────────────── fakes ─────────────────────────

class _FakeCol:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, filt=None, proj=None):
        class _Cursor:
            def __init__(self, docs):
                self._docs = docs

            def sort(self, key, direction):
                self._docs = sorted(
                    self._docs, key=lambda d: d.get(key) or 0,
                    reverse=(direction == -1))
                return self

            def __iter__(self):
                return iter([{k: v for k, v in d.items() if k != "_id"}
                             for d in self._docs])

        return _Cursor([d for d in self.docs if _match(d, filt)])

    def count_documents(self, filt=None):
        return sum(1 for d in self.docs if _match(d, filt))


def _match(doc, filt):
    if not filt:
        return True
    for k, v in filt.items():
        if isinstance(v, dict):
            for op, arg in v.items():
                dv = doc.get(k)
                if op == "$exists" and (dv is not None) != arg:
                    return False
                if op == "$in" and dv not in arg:
                    return False
                if op == "$ne" and dv == arg:
                    return False
        elif doc.get(k) != v:
            return False
    return True


class _FakeDB:
    def __init__(self, adv_docs, rs_docs):
        self._cols = {
            "symbol_adv_cache": _FakeCol(adv_docs),
            "rs_leadership": _FakeCol(rs_docs),
        }

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _FakeCol([])
        return self._cols[name]


def _svc(adv_docs, rs_docs, tag_results=None, ib_connected=True):
    """SectorTagService wired to fakes. `tag_results` maps symbol → etf|None
    for a monkeypatched tag_symbol_async."""
    svc = SectorTagService(db=_FakeDB(adv_docs, rs_docs))
    results = tag_results or {}

    async def _fake_tag(sym):
        return results.get(sym.upper())

    svc.tag_symbol_async = _fake_tag
    svc._ib_connected = lambda: ib_connected
    return svc


# ───────────────────────── tests ─────────────────────────

def test_order_backfill_targets_rated_first_deduped_capped():
    untagged = ["aaa", "BBB", "CCC", "DDD"]
    rated = ["CCC", "ZZZ", "ccc", "AAA"]  # ZZZ not untagged; ccc duplicate
    out = order_backfill_targets(untagged, rated)
    assert out[:2] == ["CCC", "AAA"], out          # rated order preserved
    assert out[2:] == ["BBB", "DDD"], out          # rest alphabetical
    assert order_backfill_targets(untagged, rated, cap=3) == ["CCC", "AAA", "BBB"]


def test_deep_backfill_tags_and_reports():
    adv = [
        {"symbol": "TAGGED", "sector": "XLK"},      # already valid → skipped
        {"symbol": "LEAD", "sector": None},          # rated leader → first
        {"symbol": "MISC", "sector": ""},            # unrated untagged
    ]
    rs = [{"symbol": "LEAD", "rs_rating": 95}]
    svc = _svc(adv, rs, tag_results={"LEAD": "XLE", "MISC": None})
    res = asyncio.run(
        svc.deep_backfill_untagged(pace_s=0, recompute_rs=False))
    assert res["success"], res
    assert res["targets"] == 2, res                  # TAGGED excluded
    assert res["tagged"] == 1 and res["untaggable"] == 1, res
    state = svc.deep_backfill_status()
    assert state["running"] is False
    assert state["processed"] == 2
    assert state["last_symbol"] in ("LEAD", "MISC")


def test_deep_backfill_circuit_breaker_when_ib_down():
    adv = [{"symbol": f"S{i:03d}", "sector": None} for i in range(120)]
    svc = _svc(adv, [], tag_results={}, ib_connected=False)  # every lookup misses
    res = asyncio.run(
        svc.deep_backfill_untagged(pace_s=0, recompute_rs=False))
    assert res["success"], res
    assert res["aborted"], "breaker did not trip with IB down"
    assert res["untaggable"] == SectorTagService.DEEP_BREAKER_STREAK, res
    assert "IB" in res["aborted"]


def test_deep_backfill_no_breaker_when_ib_up():
    adv = [{"symbol": f"S{i:03d}", "sector": None} for i in range(40)]
    svc = _svc(adv, [], tag_results={}, ib_connected=True)
    res = asyncio.run(
        svc.deep_backfill_untagged(pace_s=0, recompute_rs=False))
    assert res["aborted"] is None, res               # genuine unknowns, keep going
    assert res["untaggable"] == 40, res


def test_deep_backfill_rejects_concurrent_run():
    svc = _svc([{"symbol": "A", "sector": None}], [])
    svc._deep_state = {"running": True}
    res = asyncio.run(
        svc.deep_backfill_untagged(pace_s=0))
    assert not res["success"] and "already running" in res["error"]


def test_router_exposes_v322e_endpoints():
    src = (ROOT / "routers" / "scanner.py").read_text()
    assert '"/sector-backfill/deep"' in src
    assert '"/sector-backfill/status"' in src
    assert "deep_backfill_untagged" in src
