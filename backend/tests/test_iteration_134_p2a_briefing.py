"""
Iteration 134 — P2-A Morning Briefing rich-UI refactor.

Validates:
  • GET /api/live/briefing-watchlist  (shape, cap at 12, core indices always present)
  • GET /api/live/briefing-top-movers (shape, default + ?bar_size=5+mins, ranked by |change_pct|)
  • GET /api/live/overnight-sentiment (shape, threshold=0.3, notable_count integrity,
                                      explicit ?symbols=... bypass + 12-cap)
  • Phase 1/2/3 regressions: /api/live/subscriptions, /api/live/symbol-snapshot/SPY,
                             /api/live/briefing-snapshot, /api/live/ttl-plan,
                             /api/live/pusher-rpc-health
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
CORE_INDICES = {"SPY", "QQQ", "IWM", "DIA", "VIX"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- briefing-watchlist ----------
class TestBriefingWatchlist:
    def test_shape_and_cap(self, api):
        r = api.get(f"{BASE_URL}/api/live/briefing-watchlist", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["symbols"], list)
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["symbols"])
        assert data["count"] <= 12, "watchlist must be capped at 12"
        sources = data["sources"]
        assert "positions" in sources
        assert "scanner_top_10" in sources
        assert isinstance(sources["core_indices"], list)

    def test_core_indices_always_present(self, api):
        r = api.get(f"{BASE_URL}/api/live/briefing-watchlist", timeout=15)
        symbols = set(r.json()["symbols"])
        assert CORE_INDICES.issubset(symbols), (
            f"core indices missing from watchlist: {CORE_INDICES - symbols}"
        )


# ---------- briefing-top-movers ----------
class TestBriefingTopMovers:
    def test_default_shape(self, api):
        r = api.get(f"{BASE_URL}/api/live/briefing-top-movers", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert isinstance(d["watchlist"], list)
        assert d["count"] == len(d["watchlist"])
        assert d["market_state"] in ("rth", "premarket", "afterhours", "closed")
        assert "bar_size" in d
        assert isinstance(d["snapshots"], list)
        assert len(d["snapshots"]) == d["count"]
        # per-snapshot shape
        for s in d["snapshots"]:
            for k in ("success", "symbol", "bar_size", "latest_price",
                      "change_pct", "market_state", "source", "fetched_at"):
                assert k in s, f"snapshot missing key {k}"

    def test_explicit_bar_size(self, api):
        r = api.get(f"{BASE_URL}/api/live/briefing-top-movers",
                    params={"bar_size": "5 mins"}, timeout=20)
        assert r.status_code == 200
        assert r.json()["bar_size"] == "5 mins"

    def test_snapshots_ranked_by_abs_change_pct(self, api):
        r = api.get(f"{BASE_URL}/api/live/briefing-top-movers", timeout=20)
        snaps = r.json()["snapshots"]
        # pick only snapshots with numeric change_pct
        prior = None
        for s in snaps:
            cp = s.get("change_pct")
            if cp is None:
                continue
            if prior is not None:
                assert abs(cp) <= abs(prior) + 1e-9, "snapshots must be sorted by |change_pct| desc"
            prior = cp


# ---------- overnight-sentiment ----------
class TestOvernightSentiment:
    def test_default_shape_and_threshold(self, api):
        r = api.get(f"{BASE_URL}/api/live/overnight-sentiment", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert d["swing_threshold"] == 0.3, "swing_threshold must equal 0.3 exactly"
        assert isinstance(d["watchlist"], list)
        assert d["count"] == len(d["watchlist"])
        assert isinstance(d["results"], list)
        for row in d["results"]:
            for k in ("symbol", "swing", "swing_direction", "notable",
                      "sentiment_yesterday_close", "sentiment_premarket",
                      "news_count_yesterday_close", "news_count_premarket",
                      "news_count_overnight", "top_headline", "top_headline_ts",
                      "window"):
                assert k in row, f"result missing key {k}"
            assert row["swing_direction"] in ("up", "down", "flat")
            assert isinstance(row["notable"], bool)
            assert "yesterday_close" in row["window"]
            assert "premarket" in row["window"]

    def test_notable_count_matches_threshold(self, api):
        r = api.get(f"{BASE_URL}/api/live/overnight-sentiment", timeout=30)
        d = r.json()
        expected = sum(1 for row in d["results"] if abs(row["swing"]) >= 0.30)
        assert d["notable_count"] == expected, (
            f"notable_count={d['notable_count']} but |swing|>=0.30 count={expected}"
        )
        # notable flag consistency with swing threshold
        for row in d["results"]:
            assert row["notable"] == (abs(row["swing"]) >= 0.30)

    def test_explicit_symbols_bypass(self, api):
        r = api.get(f"{BASE_URL}/api/live/overnight-sentiment",
                    params={"symbols": "AAPL,MSFT,SPY"}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["watchlist"] == ["AAPL", "MSFT", "SPY"]
        assert d["count"] == 3
        assert len(d["results"]) == 3
        assert {row["symbol"] for row in d["results"]} == {"AAPL", "MSFT", "SPY"}

    def test_explicit_symbols_capped_at_12(self, api):
        # 15 symbols -> only first 12 honored
        syms = ",".join(["AAPL", "MSFT", "GOOG", "AMZN", "META", "TSLA",
                         "NVDA", "NFLX", "AMD", "INTC", "CRM", "ORCL",
                         "IBM", "CSCO", "ADBE"])
        r = api.get(f"{BASE_URL}/api/live/overnight-sentiment",
                    params={"symbols": syms}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] <= 12, f"explicit list must be capped at 12, got {d['count']}"


# ---------- regressions: existing live endpoints ----------
class TestPhase123Regressions:
    @pytest.mark.parametrize("path", [
        "/api/live/subscriptions",
        "/api/live/symbol-snapshot/SPY",
        "/api/live/briefing-snapshot",
        "/api/live/ttl-plan",
        "/api/live/pusher-rpc-health",
    ])
    def test_endpoint_alive(self, api, path):
        r = api.get(f"{BASE_URL}{path}", timeout=20)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        # must be valid JSON
        assert r.json() is not None
