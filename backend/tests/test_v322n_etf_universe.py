"""
test_v322n_etf_universe.py — regression tests for the 2026-06-11 ETF
universe audit.

Findings the changes close:
  • ~25% of the pusher's top-400-by-dollar-volume L1 universe was ETFs —
    bond/cash funds, index clones and single-stock leveraged products
    burned L1 lines and scanner cycles with no trade candidacy.
  • Leveraged products post RS 80+ MECHANICALLY in a rally (it's leverage,
    not leadership) and could crowd the Regime Focus List.

v322n:
  1. etf_classifier — static class map + policy predicates.
  2. Focus list: leveraged_inverse / bond_cash / income / index_clone are
     not focus-eligible, EXCEPT the operator carve-out TQQQ/SQQQ/SOXL/SOXS.
  3. L1 top-N ranking drops bond_cash / income / index_clone /
     single-stock leveraged (context ETF set unaffected).
  4. bot_trades rows are stamped is_etf/etf_class for per-class EV.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.etf_classifier import (  # noqa: E402
    classify_etf, is_etf, is_focus_eligible, is_l1_eligible,
)
from services.regime_focus_service import build_focus_list  # noqa: E402
from services.symbol_universe import get_pusher_l1_recommendations  # noqa: E402


# ── 1. classification ───────────────────────────────────────────────────────

def test_classify_known_classes():
    assert classify_etf("TQQQ") == "leveraged_inverse"
    assert classify_etf("NVDL") == "leveraged_inverse"   # single-stock
    assert classify_etf("SGOV") == "bond_cash"
    assert classify_etf("TLT") == "bond_cash"
    assert classify_etf("JEPI") == "income"
    assert classify_etf("VOO") == "index_clone"
    assert classify_etf("EWY") == "country_intl"
    assert classify_etf("GLD") == "commodity"
    assert classify_etf("IBIT") == "crypto"
    assert classify_etf("XLK") == "sector_thematic"
    assert classify_etf("SMH") == "sector_thematic"
    assert classify_etf("AIQ") == "sector_thematic"


def test_stocks_are_not_etfs():
    for sym in ("AAPL", "CZR", "NVDA", "UNP", "B"):
        assert classify_etf(sym) is None
        assert is_etf(sym) is False


# ── 2. focus-list eligibility ───────────────────────────────────────────────

def test_operator_carveout_focus_eligible():
    for sym in ("TQQQ", "SQQQ", "SOXL", "SOXS"):
        assert is_focus_eligible(sym) is True, sym


def test_mechanical_products_not_focus_eligible():
    for sym in ("NVDL", "TSLL", "PLTD", "VOO", "QQQM", "JEPI",
                "TLT", "SGOV", "SPXU", "TZA"):
        assert is_focus_eligible(sym) is False, sym


def test_stocks_and_thematic_focus_eligible():
    for sym in ("AAPL", "CZR", "AIQ", "SMH", "KRE", "GDX", "FXI", "IBIT"):
        assert is_focus_eligible(sym) is True, sym


def test_build_focus_list_excludes_leveraged_leader():
    """NVDL posting RS 99 in a semis rally must NOT make the focus list;
    a real stock with the same rating must."""
    ratings = {
        "NVDL": {"rs_rating": 99, "sector": "XLK", "adv": 900_000_000},
        "NVDA": {"rs_rating": 98, "sector": "XLK", "adv": 900_000_000},
        "TQQQ": {"rs_rating": 97, "sector": None, "adv": 900_000_000},
    }
    out = build_focus_list(ratings, {"XLK": "strong"}, min_adv=10_000_000)
    syms = {r["symbol"] for r in out["longs"]}
    assert "NVDA" in syms
    assert "NVDL" not in syms
    # TQQQ is carve-out eligible but has no sector tag → still excluded by
    # the sector-regime requirement (unchanged behaviour).
    assert "TQQQ" not in syms


# ── 3. L1 recommendation filtering ──────────────────────────────────────────

def test_l1_eligibility():
    for sym in ("SGOV", "BIL", "AGG", "VOO", "QQQM", "JEPI", "NVDL", "TSLL"):
        assert is_l1_eligible(sym) is False, sym
    for sym in ("AAPL", "TQQQ", "SOXL", "XLK", "SMH", "GLD", "IBIT", "EWY"):
        assert is_l1_eligible(sym) is True, sym


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *a, **k):
        return _FakeCursor(list(self._docs))

    def find_one(self, *a, **k):
        return None

    def update_one(self, *a, **k):
        return None


class _FakeDB:
    def __init__(self, adv_docs):
        self._colls = {"symbol_adv_cache": _FakeColl(adv_docs)}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeColl([]))


def test_l1_recommendations_filter_mechanical_etfs():
    docs = [
        {"symbol": "NVDA", "avg_dollar_volume": 900},
        {"symbol": "SGOV", "avg_dollar_volume": 800},   # bond_cash → out
        {"symbol": "VOO", "avg_dollar_volume": 700},    # index_clone → out
        {"symbol": "NVDL", "avg_dollar_volume": 600},   # 1-stock lev → out
        {"symbol": "TQQQ", "avg_dollar_volume": 500},   # keeps its line
        {"symbol": "AAPL", "avg_dollar_volume": 400},
        {"symbol": "JEPI", "avg_dollar_volume": 300},   # income → out
        {"symbol": "CZR", "avg_dollar_volume": 200},
    ]
    out = get_pusher_l1_recommendations(_FakeDB(docs), top_n=4, max_total=40)
    assert out["success"] is True
    top = out["top_n_by_adv"]
    assert top == ["NVDA", "TQQQ", "AAPL", "CZR"], top
    # context ETF set unaffected (SPY etc. still present in final list)
    assert "SPY" in out["symbols"]


# ── 4. bot_trades stamping ──────────────────────────────────────────────────

def test_save_trade_stamps_etf_class():
    import asyncio
    from types import SimpleNamespace
    from services.bot_persistence import BotPersistence

    saved = {}

    class _Trades:
        def replace_one(self, flt, doc, upsert=False):
            saved.update(doc)

    class _DB:
        def __getitem__(self, name):
            return _Trades()

    trade = SimpleNamespace(
        id="t1", symbol="AIQ",
        to_dict=lambda: {"id": "t1", "symbol": "AIQ",
                         "created_at": "2026-06-11T13:00:00+00:00"},
    )
    bot = SimpleNamespace(_db=_DB())
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        BotPersistence().save_trade(trade, bot))
    assert saved.get("is_etf") is True
    assert saved.get("etf_class") == "sector_thematic"
