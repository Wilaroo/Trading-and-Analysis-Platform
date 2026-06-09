"""
v314 tests — Market regime data-integrity fixes (Step 1):
  Bug B: FTD distribution-day counting must dedupe by the BAR's trading date,
         not wall-clock now(), so repeated calculate()/refresh calls don't
         re-count the same down-day (was inflating the count to 25 = CRITICAL).
  Bug C: Breadth flatlined to all-zero in the IB-only deployment because the
         quote/sector fallbacks read the module-level get_database() handle
         (returns None in this runtime) instead of the injected self.db handle
         that FTD persistence already proves valid.
"""
import asyncio

from services.market_regime_engine import FTDSignalBlock, MarketRegimeEngine


def _bar(date, close, volume):
    return {"timestamp": date, "open": close, "high": close, "low": close,
            "close": close, "volume": volume}


def _bars_with_one_distribution_day():
    # 29 flat bars then one big down-day on higher volume = 1 distribution day
    bars = [_bar(f"2026-05-{(i % 28) + 1:02d}", 100.0, 1000) for i in range(29)]
    bars.append(_bar("2026-06-05", 97.4, 1900))  # -2.6% on 1.9x volume
    return bars


def test_distribution_day_deduped_across_repeated_calls():
    blk = FTDSignalBlock()
    bars = _bars_with_one_distribution_day()
    # Simulate 10 refreshes on the SAME (stale) bars — the old bug appended each time.
    for _ in range(10):
        blk._update_ftd_state(bars)
    assert len(blk.distribution_days) == 1, \
        f"expected 1 deduped distribution day, got {len(blk.distribution_days)}"
    assert blk.distribution_days[0]["date"].startswith("2026-06-05")


def test_distribution_day_uses_bar_date_not_now():
    blk = FTDSignalBlock()
    bars = _bars_with_one_distribution_day()
    blk._update_ftd_state(bars)
    # date must come from the bar (2026-06-05), not today's wall clock
    assert blk.distribution_days[0]["date"][:10] == "2026-06-05"


def test_ftd_score_healthy_with_single_distribution_day():
    blk = FTDSignalBlock()
    bars = _bars_with_one_distribution_day()
    # Refresh several times; count must stay 1 → HEALTHY band, not CRITICAL
    for _ in range(5):
        score = asyncio.run(blk.calculate(bars, stored_state=None))
    assert blk.signals["distribution_day_count"] == 1
    assert blk.signals["distribution_status"] == "HEALTHY"
    # CORRECTION state (+15) + HEALTHY distribution (+30) + NO_RALLY (+0) = 45
    assert score == 45, f"expected 45, got {score}"


def test_new_distinct_down_day_increments_count():
    blk = FTDSignalBlock()
    bars = _bars_with_one_distribution_day()
    blk._update_ftd_state(bars)
    # Add a second, distinct distribution day
    bars.append(_bar("2026-06-08", 94.8, 2000))  # another down-day, higher vol
    blk._update_ftd_state(bars)
    days = sorted(d["date"][:10] for d in blk.distribution_days)
    assert days == ["2026-06-05", "2026-06-08"], days


def test_legacy_now_stamped_dupes_collapse_on_calculate():
    """Legacy state had ~25 same-day now()-stamped dupes → CRITICAL. The dedup
    in calculate() must collapse them to one-per-day so the count is sane."""
    blk = FTDSignalBlock()
    # 25 duplicate entries all on the SAME day (pre-fix pollution)
    blk.distribution_days = [
        {"date": f"2026-06-09T{h:02d}:{m:02d}:00+00:00", "change_pct": -2.58, "volume_ratio": 1.91}
        for h in range(13, 16) for m in range(0, 54, 6)
    ][:25]
    assert len(blk.distribution_days) == 25
    bars = _bars_with_one_distribution_day()  # contributes a distinct 2026-06-05
    score = asyncio.run(blk.calculate(bars, stored_state=None))
    # 25 same-day dupes → 1 distinct (06-09) + the 06-05 bar = 2 distinct days
    assert blk.signals["distribution_day_count"] <= 2
    assert blk.signals["distribution_status"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Bug C — Breadth must use the injected self.db handle (IB-only deployment).
# A fake DB stands in for ib_historical_data so we can prove the daily-change
# fallbacks return REAL numbers instead of the old silent zeros.
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction):
        self._docs = sorted(
            self._docs, key=lambda d: d.get(key, ""), reverse=(direction == -1)
        )
        return self

    def limit(self, n):
        return self._docs[:n]


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, flt, projection=None):
        rows = [
            d for d in self._docs
            if d.get("symbol") == flt.get("symbol")
            and d.get("bar_size") == flt.get("bar_size")
        ]
        return _FakeCursor(rows)


class _FakeDB:
    def __init__(self, docs):
        self._coll = _FakeCollection(docs)

    def __getitem__(self, name):
        return self._coll


def _two_day_docs(symbol, last_close, prev_close):
    return [
        {"symbol": symbol, "bar_size": "1 day", "date": "2026-06-05", "close": prev_close},
        {"symbol": symbol, "bar_size": "1 day", "date": "2026-06-09", "close": last_close},
    ]


def test_daily_change_from_bars_uses_injected_db():
    eng = MarketRegimeEngine(
        alpaca_service=None, ib_service=None, db=_FakeDB(_two_day_docs("SPY", 101.0, 100.0))
    )
    res = asyncio.run(eng._daily_change_from_bars("SPY"))
    assert res, "expected non-empty result from injected db (was {} via None get_database)"
    assert res["change_pct"] == 1.0
    assert res["price"] == 101.0


def test_get_quote_breadth_nonzero_ib_only():
    eng = MarketRegimeEngine(
        alpaca_service=None, ib_service=None, db=_FakeDB(_two_day_docs("SPY", 99.0, 100.0))
    )
    q = asyncio.run(eng._get_quote("SPY"))
    assert q["change_pct"] == -1.0, "breadth quote must not silently flatline to 0"


def test_get_sector_data_breadth_nonzero():
    docs = []
    for etf in ["XLK", "XLF", "XLE"]:
        docs += _two_day_docs(etf, 102.0, 100.0)  # +2% each
    eng = MarketRegimeEngine(alpaca_service=None, ib_service=None, db=_FakeDB(docs))
    sd = asyncio.run(eng._get_sector_data())
    assert sd.get("XLK", {}).get("change_pct") == 2.0
    assert any(v["change_pct"] != 0 for v in sd.values()), "sector breadth all-zero regression"
