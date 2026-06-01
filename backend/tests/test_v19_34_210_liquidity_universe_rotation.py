"""v19.34.210 — Alphabetical execution-bias fix.

Proves the two pieces of the fix:

1. ``get_universe_ranked`` orders the qualified universe by
   ``avg_dollar_volume`` DESC — NOT alphabetically — and honours the
   tier threshold + ``unqualifiable`` exclusion + ``limit``.

2. ``EnhancedBackgroundScanner._next_universe_wave`` rotates a per-scan
   cursor over the FULL ranked universe so that, across
   ``ceil(N / wave)`` cycles, EVERY qualified symbol is visited exactly
   once per sweep (no A–early-B truncation, full coverage, liquidity
   order preserved).
"""
import math
from types import SimpleNamespace

import pytest

from services import symbol_universe
from services.symbol_universe import get_universe_ranked
from services.enhanced_scanner import EnhancedBackgroundScanner


# --------------------------------------------------------------------------
# Fake Mongo just rich enough for get_universe_ranked
# --------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction):
        self._docs = sorted(
            self._docs, key=lambda d: d.get(key, 0), reverse=(direction == -1)
        )
        return self

    def limit(self, n):
        self._docs = self._docs[: int(n)]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        thr = query["avg_dollar_volume"]["$gte"]
        out = [d for d in self.docs if d.get("avg_dollar_volume", 0) >= thr]
        if query.get("unqualifiable") == {"$ne": True}:
            out = [d for d in out if not d.get("unqualifiable")]
        return _FakeCursor([dict(d) for d in out])


class _FakeDB:
    def __init__(self, docs):
        self._coll = _FakeColl(docs)

    def __getitem__(self, name):
        assert name == "symbol_adv_cache", name
        return self._coll


def _make_docs():
    # Deliberately ANTI-alphabetical liquidity: late-alphabet names are the
    # MOST liquid. Old `sorted(get_universe(...))[:N]` would have surfaced
    # AAAA/BBBB first; the fix must surface ZZZZ/YYYY first.
    return [
        {"symbol": "AAAA", "avg_dollar_volume": 3_000_000},     # investment-only
        {"symbol": "BBBB", "avg_dollar_volume": 12_000_000},    # swing
        {"symbol": "MMMM", "avg_dollar_volume": 55_000_000},    # intraday
        {"symbol": "YYYY", "avg_dollar_volume": 80_000_000},    # intraday
        {"symbol": "ZZZZ", "avg_dollar_volume": 250_000_000},   # intraday (most liquid)
        {"symbol": "QQQQ", "avg_dollar_volume": 1_000_000},     # below investment floor
        {"symbol": "DEAD", "avg_dollar_volume": 90_000_000, "unqualifiable": True},
    ]


# --------------------------------------------------------------------------
# 1. get_universe_ranked
# --------------------------------------------------------------------------
def test_ranked_is_liquidity_desc_not_alphabetical():
    db = _FakeDB(_make_docs())
    ranked = get_universe_ranked(db, tier="investment")
    # ZZZZ (250M) must come first despite being last alphabetically.
    assert ranked[0] == "ZZZZ"
    # Strictly descending dollar-volume order.
    assert ranked == ["ZZZZ", "YYYY", "MMMM", "BBBB", "AAAA"]
    # If it were the OLD alphabetical bug, AAAA would be first.
    assert ranked[0] != "AAAA"


def test_ranked_respects_tier_threshold():
    db = _FakeDB(_make_docs())
    intraday = get_universe_ranked(db, tier="intraday")  # >= $50M
    assert set(intraday) == {"ZZZZ", "YYYY", "MMMM"}
    swing = get_universe_ranked(db, tier="swing")        # >= $10M
    assert "BBBB" in swing and "AAAA" not in swing
    investment = get_universe_ranked(db, tier="investment")  # >= $2M
    assert "AAAA" in investment and "QQQQ" not in investment


def test_ranked_excludes_unqualifiable_and_honours_limit():
    db = _FakeDB(_make_docs())
    ranked = get_universe_ranked(db, tier="intraday")
    assert "DEAD" not in ranked  # unqualifiable excluded by default
    assert get_universe_ranked(db, tier="investment", limit=2) == ["ZZZZ", "YYYY"]


def test_ranked_none_db_returns_empty():
    assert get_universe_ranked(None, tier="swing") == []


# --------------------------------------------------------------------------
# 2. _next_universe_wave rotation / full coverage
# --------------------------------------------------------------------------
def _bind_wave():
    """Bind the real method to a lightweight stub (avoids constructing the
    heavy scanner / DGX bindings)."""
    stub = SimpleNamespace(db=_FakeDB(_make_docs()))
    method = EnhancedBackgroundScanner._next_universe_wave.__get__(stub)
    return stub, method


def test_wave_covers_full_universe_across_cycles(monkeypatch):
    # 12 ranked names, wave of 5 => 3 cycles to full coverage.
    ranked = [f"S{i:02d}" for i in range(12)]  # already "ranked" order
    monkeypatch.setattr(
        "services.symbol_universe.get_universe_ranked",
        lambda db, tier="intraday": list(ranked),
    )
    stub, wave = _bind_wave()
    wave_size = 5
    n_cycles = math.ceil(len(ranked) / wave_size)
    seen = []
    for _ in range(n_cycles):
        seen.extend(wave("_off", "investment", wave_size))
    # Every symbol visited at least once within one full sweep.
    assert set(seen) == set(ranked)


def test_wave_advances_cursor_and_preserves_liquidity_order(monkeypatch):
    ranked = [f"S{i:02d}" for i in range(12)]
    monkeypatch.setattr(
        "services.symbol_universe.get_universe_ranked",
        lambda db, tier="intraday": list(ranked),
    )
    stub, wave = _bind_wave()
    first = wave("_off", "investment", 5)
    second = wave("_off", "investment", 5)
    assert first == ranked[0:5]          # most-liquid first
    assert second == ranked[5:10]        # cursor advanced, no overlap
    assert getattr(stub, "_off") == 10   # cursor parked at offset 10


def test_wave_wraps_around(monkeypatch):
    ranked = [f"S{i:02d}" for i in range(12)]
    monkeypatch.setattr(
        "services.symbol_universe.get_universe_ranked",
        lambda db, tier="intraday": list(ranked),
    )
    stub, wave = _bind_wave()
    stub._off = 10  # near the end
    w = wave("_off", "investment", 5)
    # 10,11 then wrap to 0,1,2
    assert w == ["S10", "S11", "S00", "S01", "S02"]


def test_wave_empty_universe_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "services.symbol_universe.get_universe_ranked",
        lambda db, tier="intraday": [],
    )
    stub, wave = _bind_wave()
    assert wave("_off", "investment", 500) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
