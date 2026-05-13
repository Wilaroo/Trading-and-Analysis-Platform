"""
v19.34.142 — Position PnL audit + orphan-PnL fallback chain.
============================================================

Operator-visible bug: 5 reconciled orphans (TE/EGO/KTOS/SSNC/CHWY) all
showed `+$0` PnL even though IB had real unrealized values for them
(TE alone was −$1,082). Root cause: `updatePortfolio()` hasn't fired
for freshly-reconciled positions, so the pusher sends qty + avgCost
with `unrealizedPNL=0` and `marketPrice=0`. The bot's IB-orphan row
emitter computed `(market_price - avg_cost) * shares = 0`.

This file covers:
  - Orphan row falls back to L1 quote mark when `unrealizedPNL=0`.
  - Orphan row falls back to `live_bar_cache` close when neither
    IB unrealized nor a live quote is available.
  - When all fallbacks fail, `pnl_source = "unknown_no_mark"` so the
    UI can show a warning instead of pretending $0 is the truth.
  - The new `/api/diagnostic/position-pnl-audit` correctly diffs
    bot vs IB on every position and classifies each row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest


# =============================================================================
# Lightweight mocks
# =============================================================================

class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, proj=None, sort=None):
        out = [d for d in self.docs if all(
            d.get(k) == v for k, v in query.items()
            if not isinstance(v, dict)
        )]
        if sort:
            key, direction = sort[0]
            out.sort(key=lambda d: d.get(key) or 0, reverse=(direction < 0))
        return dict(out[0]) if out else None


class _DB:
    def __init__(self):
        self.live_bar_cache = _Coll()

    def __getitem__(self, name):
        if name == "live_bar_cache":
            return self.live_bar_cache
        return _Coll()


# =============================================================================
# Orphan-PnL fallback chain (in-line replication of the production code)
# =============================================================================
#
# We can't easily spin up the full SentcomService here. Instead, lift the
# fallback logic into a tiny pure function and assert it behaves correctly
# under each scenario. The production code follows the same logic exactly.

def _compute_orphan_pnl(*, ib_quotes, db, symbol, avg_cost, shares,
                       ib_unrealized=0, ib_market_price=0):
    """Mirror of the v19.34.142 fallback chain in
    services/sentcom_service.py::get_our_positions (IB orphan branch)."""
    unrealized = float(ib_unrealized or 0)
    market_price = float(ib_market_price or 0)
    if unrealized == 0 and market_price and avg_cost and shares:
        unrealized = (market_price - avg_cost) * shares
    pnl_source = "ib_unrealized"
    if unrealized == 0 and avg_cost and shares:
        fallback_mark = 0.0
        q = ib_quotes.get(symbol) or ib_quotes.get(symbol.upper())
        if isinstance(q, dict):
            for k in ("last", "mid", "close", "bid", "ask"):
                v = q.get(k)
                try:
                    if v and float(v) > 0:
                        fallback_mark = float(v)
                        pnl_source = f"quote_{k}"
                        break
                except (TypeError, ValueError):
                    continue
        if fallback_mark == 0.0:
            bar = db["live_bar_cache"].find_one(
                {"symbol": symbol},
                {"_id": 0, "close": 1, "c": 1, "price": 1},
                sort=[("ts", -1)],
            )
            if bar:
                for k in ("close", "c", "price"):
                    v = bar.get(k)
                    try:
                        if v and float(v) > 0:
                            fallback_mark = float(v)
                            pnl_source = f"live_bar_{k}"
                            break
                    except (TypeError, ValueError):
                        continue
        if fallback_mark > 0:
            unrealized = (fallback_mark - float(avg_cost)) * float(shares)
        else:
            pnl_source = "unknown_no_mark"
    return round(unrealized, 2), pnl_source


class TestOrphanPnLFallback:
    def test_uses_ib_unrealized_when_present(self):
        """Happy path — IB has a real unrealized number; we use it."""
        pnl, src = _compute_orphan_pnl(
            ib_quotes={}, db=_DB(),
            symbol="MSFT", avg_cost=400.0, shares=100,
            ib_unrealized=500.0, ib_market_price=405.0,
        )
        assert pnl == 500.0
        assert src == "ib_unrealized"

    def test_falls_back_to_quote_last_when_ib_unrealized_zero(self):
        """The TE/EGO/KTOS scenario — IB unrealized is 0 (updatePortfolio
        hasn't fired) but a live L1 quote exists. Use it."""
        ib_quotes = {"TE": {"last": 5.55, "bid": 5.54, "ask": 5.56}}
        pnl, src = _compute_orphan_pnl(
            ib_quotes=ib_quotes, db=_DB(),
            symbol="TE", avg_cost=5.40, shares=-7204,
            ib_unrealized=0, ib_market_price=0,
        )
        # (5.55 - 5.40) * -7204 = -1080.6
        assert pnl == pytest.approx(-1080.6, abs=0.01)
        assert src == "quote_last"

    def test_falls_back_to_bid_then_ask_when_last_missing(self):
        ib_quotes = {"TE": {"bid": 5.54, "ask": 5.56}}
        pnl, src = _compute_orphan_pnl(
            ib_quotes=ib_quotes, db=_DB(),
            symbol="TE", avg_cost=5.40, shares=-7204,
        )
        # bid first → (5.54 - 5.40) * -7204
        assert pnl == pytest.approx(-1008.56, abs=0.01)
        assert src == "quote_bid"

    def test_falls_back_to_live_bar_cache_when_no_quote(self):
        db = _DB()
        db.live_bar_cache.docs.append({
            "symbol": "EGO", "close": 36.20, "ts": "now",
        })
        pnl, src = _compute_orphan_pnl(
            ib_quotes={}, db=db,
            symbol="EGO", avg_cost=35.69, shares=-2046,
        )
        # (36.20 - 35.69) * -2046 = -1043.46
        assert pnl == pytest.approx(-1043.46, abs=0.01)
        assert src == "live_bar_close"

    def test_returns_unknown_no_mark_when_all_fallbacks_fail(self):
        """No IB unrealized, no L1 quote, no cached bar → pnl_source
        must be 'unknown_no_mark' so the UI can flag the row instead
        of pretending it's $0."""
        pnl, src = _compute_orphan_pnl(
            ib_quotes={}, db=_DB(),
            symbol="OBSCURE", avg_cost=10.0, shares=100,
        )
        assert pnl == 0.0
        assert src == "unknown_no_mark"


# =============================================================================
# /api/diagnostic/position-pnl-audit endpoint
# =============================================================================

class TestPositionPnLAuditEndpoint:
    @pytest.fixture
    def patched(self, monkeypatch):
        # 1) Patch IB pusher cache.
        import sys
        fake_ib = type(sys)("routers.ib")
        fake_ib._pushed_ib_data = {
            "positions": [
                {"symbol": "TSLA", "position": 100,
                 "avgCost": 400.0, "marketPrice": 410.0,
                 "unrealizedPNL": 1000.0},
                {"symbol": "TE", "position": -7204,
                 "avgCost": 5.40, "marketPrice": 0,
                 "unrealizedPNL": -1082.83},
                {"symbol": "NVDA", "position": 50,
                 "avgCost": 900.0, "marketPrice": 905.0,
                 "unrealizedPNL": 250.0},
                # MISSING_IN_BOT case — IB has CW, bot won't render it.
                {"symbol": "CW", "position": 24,
                 "avgCost": 746.0, "marketPrice": 750.0,
                 "unrealizedPNL": 96.0},
            ],
            "quotes": {},
        }
        monkeypatch.setitem(sys.modules, "routers.ib", fake_ib)

        # 2) Patch sentcom service to return a controlled bot panel.
        class _FakeSvc:
            async def get_our_positions(self):
                return [
                    # TSLA — clean match (long 100).
                    {"symbol": "TSLA", "shares": 100, "direction": "long",
                     "pnl": 1000.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                    # TE — bot still showing $0 even after orphan fix
                    # somehow (simulate worst-case for the audit). Short.
                    {"symbol": "TE", "shares": 7204, "direction": "short",
                     "pnl": 0.0,
                     "pnl_source": "unknown_no_mark", "source": "ib"},
                    # NVDA — minor drift ($30). Long.
                    {"symbol": "NVDA", "shares": 50, "direction": "long",
                     "pnl": 220.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                    # PHANTOM_IN_BOT — bot tracks but IB doesn't have it.
                    {"symbol": "ZOMBIE", "shares": 1000, "direction": "long",
                     "pnl": -50.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                    # CW is absent here → MISSING_IN_BOT scenario.
                ]
        fake_svc_mod = type(sys)("services.sentcom_service")
        fake_svc_mod.get_sentcom_service = lambda: _FakeSvc()
        monkeypatch.setitem(sys.modules, "services.sentcom_service",
                            fake_svc_mod)

        # 3) Patch _get_db so the endpoint passes the None check.
        from routers import diagnostic_router as dr
        monkeypatch.setattr(dr, "_get_db", lambda: object())
        return None

    @pytest.mark.asyncio
    async def test_endpoint_classifies_each_row_correctly(self, patched):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        by_sym = {r["symbol"]: r for r in resp["rows"]}

        assert by_sym["TSLA"]["verdict"] == "OK"
        # TE — Δ $1083 > $20 → DRIFT_ABS
        assert by_sym["TE"]["verdict"] == "DRIFT_ABS"
        assert by_sym["TE"]["pnl_source"] == "unknown_no_mark"
        # NVDA — Δ $30 > $20 → DRIFT_ABS (even though % is small)
        assert by_sym["NVDA"]["verdict"] == "DRIFT_ABS"
        # ZOMBIE in bot but not in IB
        assert by_sym["ZOMBIE"]["verdict"] == "PHANTOM_IN_BOT"
        # CW in IB but not in bot
        assert by_sym["CW"]["verdict"] == "MISSING_IN_BOT"

    @pytest.mark.asyncio
    async def test_endpoint_summary_aggregates_correctly(self, patched):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        s = resp["summary"]
        assert s["ok"] == 1               # TSLA only
        assert s["drift_abs"] == 2        # TE + NVDA
        assert s["missing_in_bot"] == 1   # CW
        assert s["phantom_in_bot"] == 1   # ZOMBIE
        # IB total = 1000 - 1082.83 + 250 + 96 = 263.17
        assert s["totals"]["ib_unrealized"] == pytest.approx(263.17, abs=0.01)
        # Bot total = 1000 + 0 + 220 + (-50) = 1170
        assert s["totals"]["bot_unrealized"] == 1170.0
        assert s["totals"]["delta"] == pytest.approx(-906.83, abs=0.01)

    @pytest.mark.asyncio
    async def test_endpoint_recommends_actions(self, patched):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "missing from the bot panel" in joined.lower()
        assert ("absent from IB" in joined.lower() or "PHANTOM" in joined.upper()
                or "absent" in joined.lower() or "phantom" in joined.lower())
        # Worst drift mentions TE specifically.
        assert "TE" in joined

    @pytest.mark.asyncio
    async def test_threshold_overrides_relax_classification(self, patched):
        """With a $2000 drift threshold, TE's $1083 drift no longer counts."""
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit(drift_abs_threshold=2000.0,
                                        drift_pct_threshold=1000.0)
        by_sym = {r["symbol"]: r for r in resp["rows"]}
        assert by_sym["TE"]["verdict"] == "OK"
        assert by_sym["NVDA"]["verdict"] == "OK"


class TestQtySignReconstruction:
    """v19.34.142c — the bot's `shares` field is unsigned; the audit
    must reconstruct signed qty from `direction`/`side` so it aligns
    with IB. When signs ACTUALLY disagree (post-reconstruction), it's
    a real data-integrity bug and must surface as QTY_SIGN_MISMATCH."""

    @pytest.fixture
    def patched_signs(self, monkeypatch):
        import sys
        fake_ib = type(sys)("routers.ib")
        fake_ib._pushed_ib_data = {
            "positions": [
                # IB is SHORT 100 shares; bot tracks 100 as short.
                # After sign-reconstruction these must agree.
                {"symbol": "MATCH_SHORT", "position": -100,
                 "avgCost": 50.0, "marketPrice": 49.0,
                 "unrealizedPNL": 100.0},
                # IB is LONG 100; bot tracks 100 as long. Matches.
                {"symbol": "MATCH_LONG", "position": 100,
                 "avgCost": 50.0, "marketPrice": 51.0,
                 "unrealizedPNL": 100.0},
                # IB is SHORT 200; bot tracks 200 as LONG → real bug.
                {"symbol": "REAL_BUG", "position": -200,
                 "avgCost": 10.0, "marketPrice": 11.0,
                 "unrealizedPNL": -200.0},
            ],
            "quotes": {},
        }
        monkeypatch.setitem(sys.modules, "routers.ib", fake_ib)

        class _FakeSvc:
            async def get_our_positions(self):
                return [
                    {"symbol": "MATCH_SHORT", "shares": 100,
                     "direction": "short", "pnl": 100.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                    {"symbol": "MATCH_LONG", "shares": 100,
                     "direction": "long", "pnl": 100.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                    # Bot says LONG, IB says SHORT.
                    {"symbol": "REAL_BUG", "shares": 200,
                     "direction": "long", "pnl": 200.0,
                     "pnl_source": "ib_unrealized", "source": "bot"},
                ]
        fake_svc_mod = type(sys)("services.sentcom_service")
        fake_svc_mod.get_sentcom_service = lambda: _FakeSvc()
        monkeypatch.setitem(sys.modules, "services.sentcom_service",
                            fake_svc_mod)
        from routers import diagnostic_router as dr
        monkeypatch.setattr(dr, "_get_db", lambda: _DB())
        return None

    @pytest.mark.asyncio
    async def test_sign_reconstructed_matches_dont_false_flag(
        self, patched_signs
    ):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        by_sym = {r["symbol"]: r for r in resp["rows"]}
        assert by_sym["MATCH_SHORT"]["bot_qty"] == -100
        assert by_sym["MATCH_SHORT"]["verdict"] == "OK"
        assert by_sym["MATCH_LONG"]["bot_qty"] == 100
        assert by_sym["MATCH_LONG"]["verdict"] == "OK"

    @pytest.mark.asyncio
    async def test_real_sign_mismatch_surfaces_as_qty_sign_mismatch(
        self, patched_signs
    ):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        by_sym = {r["symbol"]: r for r in resp["rows"]}
        assert by_sym["REAL_BUG"]["verdict"] == "QTY_SIGN_MISMATCH"
        assert resp["summary"]["qty_sign_mismatch"] == 1
        joined = " | ".join(resp["actions"])
        assert "OPPOSITE direction" in joined or "qty_sign" in joined.lower()


class TestPusherStalenessFallback:
    """When the IB pusher's updatePortfolio() lags, unrealizedPNL=0 for
    every position. The audit must NOT report `ib_unrealized=$0` —
    it must fall back to L1 quote + live_bar_cache for the IB side
    too, and surface the staleness in the actions list."""

    @pytest.fixture
    def patched_stale(self, monkeypatch):
        import sys
        # All IB positions arrive with unrealizedPNL=0 and marketPrice=0
        # — the worst-case "pusher portfolio_update never fired" scenario.
        # But L1 quotes ARE flowing for TSLA.
        fake_ib = type(sys)("routers.ib")
        fake_ib._pushed_ib_data = {
            "positions": [
                {"symbol": "TSLA", "position": 100,
                 "avgCost": 400.0, "marketPrice": 0,
                 "unrealizedPNL": 0},
                {"symbol": "OBSCURE", "position": -50,
                 "avgCost": 10.0, "marketPrice": 0,
                 "unrealizedPNL": 0},
            ],
            "quotes": {
                "TSLA": {"last": 410.0, "bid": 409.5, "ask": 410.5},
                # OBSCURE has no quote.
            },
        }
        monkeypatch.setitem(sys.modules, "routers.ib", fake_ib)

        class _FakeSvc:
            async def get_our_positions(self):
                return [
                    {"symbol": "TSLA", "shares": 100,
                     "pnl": 1000.0, "pnl_source": "quote_last",
                     "source": "ib"},
                    {"symbol": "OBSCURE", "shares": -50,
                     "pnl": 0.0, "pnl_source": "unknown_no_mark",
                     "source": "ib"},
                ]
        fake_svc_mod = type(sys)("services.sentcom_service")
        fake_svc_mod.get_sentcom_service = lambda: _FakeSvc()
        monkeypatch.setitem(sys.modules, "services.sentcom_service",
                            fake_svc_mod)
        from routers import diagnostic_router as dr
        monkeypatch.setattr(dr, "_get_db", lambda: _DB())
        return None

    @pytest.mark.asyncio
    async def test_ib_side_falls_back_to_quote_when_pusher_unrealized_is_zero(
        self, patched_stale
    ):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        by_sym = {r["symbol"]: r for r in resp["rows"]}
        # TSLA — IB raw was 0, but quote_last gives (410-400)*100 = 1000.
        # Bot also has 1000 → OK.
        assert by_sym["TSLA"]["ib_unrealized"] == 1000.0
        assert by_sym["TSLA"]["ib_pnl_source"] == "quote_last"
        assert by_sym["TSLA"]["verdict"] == "OK"
        # OBSCURE — no quote, no bar → ib_pnl_source = unknown_no_mark.
        assert by_sym["OBSCURE"]["ib_pnl_source"] == "unknown_no_mark"
        assert by_sym["OBSCURE"]["ib_unrealized"] == 0.0

    @pytest.mark.asyncio
    async def test_summary_surfaces_pusher_staleness_count(
        self, patched_stale
    ):
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        # 2/2 positions had unrealizedPNL=0 in the pusher cache.
        assert resp["summary"]["pusher_unrealized_missing"] == 2
        joined = " | ".join(resp["actions"])
        assert "pusher cache" in joined.lower() or "updatePortfolio" in joined
