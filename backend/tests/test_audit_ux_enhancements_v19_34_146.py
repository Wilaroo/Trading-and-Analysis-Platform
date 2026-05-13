"""v19.34.146 — Audit UX enhancements: partial-close info, drift
clustering by pnl_source, quote-age passthrough.

Building on v19.34.142e (`ledger_fragments`) + v19.34.145 (live PnL
math). These changes are non-behavioral additions to the audit
response that make it self-explaining:

  • partial_close_detected — attached when bot row carries
    shares != remaining_shares. Marks the row as a scaled-out
    winner so the operator doesn't confuse it with phantom shares.

  • pnl_source_breakdown_drift / _all — buckets every row by
    pnl_source so a SIVR-style "7 rows all stale" pattern jumps
    out without manual counting.

  • quote_age_s passthrough — propagates the existing per-row
    quote freshness signal from sentcom_service into the audit
    response.

  • Action lines: "ℹ N drift row(s) cluster on pnl_source=..." +
    "ℹ N position(s) have partial scale-outs already fired".
"""

import sys
import pytest


class _DB:
    def __getitem__(self, name):
        class _C:
            def find_one(self, *a, **kw):
                return None
        return _C()


def _patch(monkeypatch, ib_positions, bot_rows):
    fake_ib = type(sys)("routers.ib")
    fake_ib._pushed_ib_data = {"positions": ib_positions, "quotes": {}}
    monkeypatch.setitem(sys.modules, "routers.ib", fake_ib)

    class _FakeSvc:
        async def get_our_positions(self):
            return bot_rows
    fake_svc_mod = type(sys)("services.sentcom_service")
    fake_svc_mod.get_sentcom_service = lambda: _FakeSvc()
    monkeypatch.setitem(sys.modules, "services.sentcom_service",
                        fake_svc_mod)
    from routers import diagnostic_router as dr
    monkeypatch.setattr(dr, "_get_db", lambda: _DB())


# ────────────────────────────────────────────────────────────────────
# 1. partial_close_detected
# ────────────────────────────────────────────────────────────────────

class TestPartialCloseDetected:

    @pytest.mark.asyncio
    async def test_attached_when_shares_differ(self, monkeypatch):
        """KMB original=144, remaining=55 → block attached with
        closed=89, pct_remaining=38.2%."""
        _patch(monkeypatch, [
            {"symbol": "KMB", "position": 55, "avgCost": 135.0,
             "marketPrice": 137.5, "unrealizedPNL": 137.5},
        ], [
            {"symbol": "KMB", "shares": 144, "remaining_shares": 55,
             "direction": "long", "pnl": 137.5,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        pc = row.get("partial_close_detected")
        assert pc is not None
        assert pc["original_shares"] == 144
        assert pc["remaining_shares"] == 55
        assert pc["closed_shares"] == 89
        assert pc["pct_remaining"] == pytest.approx(38.2, abs=0.1)
        # Sanity: verdict is still OK (the v19.34.145 fix is also live).
        assert row["verdict"] == "OK"

    @pytest.mark.asyncio
    async def test_not_attached_when_no_partial(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "AAPL", "position": 100, "avgCost": 200.0,
             "marketPrice": 201.0, "unrealizedPNL": 100.0},
        ], [
            {"symbol": "AAPL", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert row.get("partial_close_detected") is None

    @pytest.mark.asyncio
    async def test_not_attached_when_remaining_field_missing(
        self, monkeypatch
    ):
        """Legacy rows without remaining_shares must not emit a
        partial_close block (avoid pretending a partial fired)."""
        _patch(monkeypatch, [
            {"symbol": "OLD", "position": 50, "avgCost": 10.0,
             "marketPrice": 11.0, "unrealizedPNL": 50.0},
        ], [
            {"symbol": "OLD", "shares": 50, "direction": "long",
             "pnl": 50.0, "pnl_source": "ib_unrealized", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert row.get("partial_close_detected") is None

    @pytest.mark.asyncio
    async def test_summary_partial_close_count(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "A", "position": 10, "avgCost": 100.0,
             "marketPrice": 100.5, "unrealizedPNL": 5.0},
            {"symbol": "B", "position": 20, "avgCost": 200.0,
             "marketPrice": 200.5, "unrealizedPNL": 10.0},
            {"symbol": "C", "position": 30, "avgCost": 50.0,
             "marketPrice": 50.5, "unrealizedPNL": 15.0},
        ], [
            {"symbol": "A", "shares": 25, "remaining_shares": 10,
             "direction": "long", "pnl": 5.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
            {"symbol": "B", "shares": 50, "remaining_shares": 20,
             "direction": "long", "pnl": 10.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
            {"symbol": "C", "shares": 30, "remaining_shares": 30,
             "direction": "long", "pnl": 15.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        # A and B are partial closes; C is full position.
        assert resp["summary"]["partial_close_count"] == 2

    @pytest.mark.asyncio
    async def test_action_line_friendly(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "KMB", "position": 55, "avgCost": 135.0,
             "marketPrice": 137.5, "unrealizedPNL": 137.5},
        ], [
            {"symbol": "KMB", "shares": 144, "remaining_shares": 55,
             "direction": "long", "pnl": 137.5,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "partial scale-outs" in joined.lower()
        assert "KMB" in joined
        assert "89" in joined  # closed_shares
        assert "scaled-out winners" in joined.lower()
        assert "NOT phantom shares" in joined


# ────────────────────────────────────────────────────────────────────
# 2. pnl_source clustering (D)
# ────────────────────────────────────────────────────────────────────

class TestPnLSourceBreakdown:

    @pytest.mark.asyncio
    async def test_dominant_cluster_triggers_actionable_hint(
        self, monkeypatch
    ):
        """5/7 drift rows share pnl_source=trade_current_price_stale →
        the action line names the source and gives the
        manage-tick remediation hint."""
        ib_pos, bot_rows = [], []
        # 5 stale + 2 other drift rows
        for i, src in enumerate(
            ["trade_current_price_stale"] * 5 + ["ib_unrealized", "quote_close"]
        ):
            sym = f"S{i:02d}"
            ib_pos.append({
                "symbol": sym, "position": 100, "avgCost": 100.0,
                "marketPrice": 102.0, "unrealizedPNL": 200.0,
            })
            # Bot says 100 instead → $100 drift (DRIFT_ABS).
            bot_rows.append({
                "symbol": sym, "shares": 100, "remaining_shares": 100,
                "direction": "long", "pnl": 100.0,
                "pnl_source": src, "source": "bot",
            })
        _patch(monkeypatch, ib_pos, bot_rows)
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "cluster" in joined.lower()
        assert "trade_current_price_stale" in joined
        assert "manage" in joined.lower() or "manage_loop" in joined.lower()
        # Breakdown numbers present.
        assert "trade_current_price_stale=5" in joined

    @pytest.mark.asyncio
    async def test_scattered_drift_emits_informational_only(
        self, monkeypatch
    ):
        """No source has ≥60% share → emit a soft 'scattered' note,
        NOT a remediation hint."""
        ib_pos, bot_rows = [], []
        for i, src in enumerate(
            ["ib_unrealized", "trade_current_price_stale",
             "quote_close", "quote_last"]
        ):
            sym = f"X{i:02d}"
            ib_pos.append({
                "symbol": sym, "position": 100, "avgCost": 100.0,
                "marketPrice": 102.0, "unrealizedPNL": 200.0,
            })
            bot_rows.append({
                "symbol": sym, "shares": 100, "remaining_shares": 100,
                "direction": "long", "pnl": 100.0,
                "pnl_source": src, "source": "bot",
            })
        _patch(monkeypatch, ib_pos, bot_rows)
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "scattered" in joined.lower() or "no dominant" in joined.lower()
        assert "noise" in joined.lower()
        # No manage-tick remediation hint when scattered.
        assert "manage tick" not in joined.lower() or \
               "restart the manage loop" not in joined.lower()

    @pytest.mark.asyncio
    async def test_summary_breakdowns_emitted(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "OK1", "position": 100, "avgCost": 100.0,
             "marketPrice": 100.0, "unrealizedPNL": 0.0},
            {"symbol": "DR1", "position": 100, "avgCost": 100.0,
             "marketPrice": 102.0, "unrealizedPNL": 200.0},
        ], [
            {"symbol": "OK1", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 0.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
            {"symbol": "DR1", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "pnl_source": "trade_current_price_stale", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        s = resp["summary"]
        # `_all` covers OK rows too.
        assert s["pnl_source_breakdown_all"]["ib_unrealized"] == 1
        assert s["pnl_source_breakdown_all"]["trade_current_price_stale"] == 1
        # `_drift` only covers drift rows.
        assert s["pnl_source_breakdown_drift"]["trade_current_price_stale"] == 1
        assert "ib_unrealized" not in s["pnl_source_breakdown_drift"]

    @pytest.mark.asyncio
    async def test_single_drift_does_not_emit_breakdown_action(
        self, monkeypatch
    ):
        """One drift row isn't a cluster — the breakdown action line
        is suppressed (only the standard 'worst drift' line fires)."""
        _patch(monkeypatch, [
            {"symbol": "X", "position": 100, "avgCost": 100.0,
             "marketPrice": 102.0, "unrealizedPNL": 200.0},
        ], [
            {"symbol": "X", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "pnl_source": "trade_current_price_stale", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        # `cluster` action line not present for single drift.
        assert "cluster" not in joined.lower()


    @pytest.mark.asyncio
    async def test_quote_last_cluster_explains_timing_skew(self, monkeypatch):
        """v19.34.146 follow-up: when all drift rows cluster on
        `quote_last`, the hint must call it "timing skew between bot
        quote_last and IB marketPrice" rather than the generic
        "investigate the cluster". This matches the operator's live
        DGX audit where 10/10 drifts shared quote_last."""
        ib_pos, bot_rows = [], []
        for i in range(10):
            sym = f"Q{i:02d}"
            ib_pos.append({
                "symbol": sym, "position": 100, "avgCost": 100.0,
                "marketPrice": 102.0, "unrealizedPNL": 200.0,
            })
            bot_rows.append({
                "symbol": sym, "shares": 100, "remaining_shares": 100,
                "direction": "long", "pnl": 100.0,
                "pnl_source": "quote_last", "source": "bot",
            })
        _patch(monkeypatch, ib_pos, bot_rows)
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "quote_last" in joined
        assert ("timing skew" in joined.lower()
                or "different price feeds" in joined.lower())
        # The remediation note explicitly says "normal noise" unless
        # delta > $100 per row.
        assert "normal noise" in joined.lower() or "100" in joined


# ────────────────────────────────────────────────────────────────────
# 3. quote-age passthrough (C)
# ────────────────────────────────────────────────────────────────────


class TestQuoteAgePassthrough:

    @pytest.mark.asyncio
    async def test_quote_age_propagated_to_row(self, monkeypatch):
        """If sentcom_service emits quote_age_s on a bot row, the
        audit response must surface it so the operator can see
        'SIVR's L1 quote is 240s old' without a second request."""
        _patch(monkeypatch, [
            {"symbol": "SIVR", "position": 100, "avgCost": 25.0,
             "marketPrice": 26.0, "unrealizedPNL": 100.0},
        ], [
            {"symbol": "SIVR", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "pnl_source": "trade_current_price_stale", "source": "bot",
             "quote_age_s": 240, "quote_state": "stale"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert row.get("quote_age_s") == 240
        assert row.get("quote_state") == "stale"

    @pytest.mark.asyncio
    async def test_stale_quote_count_thresholds_at_120s(self, monkeypatch):
        """Only rows with quote_age_s >= 120 count as stale in the
        summary aggregate."""
        _patch(monkeypatch, [
            {"symbol": "A", "position": 100, "avgCost": 100.0,
             "marketPrice": 100.0, "unrealizedPNL": 0.0},
            {"symbol": "B", "position": 100, "avgCost": 100.0,
             "marketPrice": 100.0, "unrealizedPNL": 0.0},
            {"symbol": "C", "position": 100, "avgCost": 100.0,
             "marketPrice": 100.0, "unrealizedPNL": 0.0},
        ], [
            {"symbol": "A", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 0.0,
             "pnl_source": "quote_last", "source": "bot",
             "quote_age_s": 30},
            {"symbol": "B", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 0.0,
             "pnl_source": "quote_last", "source": "bot",
             "quote_age_s": 150},
            {"symbol": "C", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 0.0,
             "pnl_source": "quote_last", "source": "bot",
             "quote_age_s": 600},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        assert resp["summary"]["stale_quote_count"] == 2

    @pytest.mark.asyncio
    async def test_quote_age_absent_when_not_provided(self, monkeypatch):
        """If the row didn't carry quote_age_s, the audit row must
        NOT invent one (don't pretend the quote is fresh OR stale)."""
        _patch(monkeypatch, [
            {"symbol": "NOAGE", "position": 100, "avgCost": 100.0,
             "marketPrice": 100.0, "unrealizedPNL": 0.0},
        ], [
            {"symbol": "NOAGE", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 0.0,
             "pnl_source": "ib_unrealized", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert "quote_age_s" not in row
        assert resp["summary"]["stale_quote_count"] == 0


# ────────────────────────────────────────────────────────────────────
# 4. avg_cost drift (v19.34.147)
# ────────────────────────────────────────────────────────────────────

class TestAvgCostDriftDetection:
    """v19.34.147 — when a drift row's PnL gap is mostly explained by
    bot.entry_price diverging from ib.avgCost (commissions, borrow
    fees, ETF distributions, corp actions), the audit must surface
    that diagnosis inline instead of just reporting the PnL gap."""

    @pytest.mark.asyncio
    async def test_icln_avg_cost_drift_explains_most_of_pnl_gap(
        self, monkeypatch
    ):
        """Live ICLN scenario: bot's entry_price = $28.50 but IB's
        avgCost = $28.95 (after ETF distribution adjustment).
        100 shares * $0.45/sh = $45 PnL gap from avg_cost alone."""
        _patch(monkeypatch, [
            {"symbol": "ICLN", "position": 100, "avgCost": 28.95,
             "marketPrice": 29.00, "unrealizedPNL": 5.0},
        ], [
            {"symbol": "ICLN", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 50.0,
             "entry_price": 28.50,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert row["verdict"] in ("DRIFT_ABS", "DRIFT_PCT")
        assert row["bot_entry_price"] == pytest.approx(28.50, abs=0.01)
        assert row["ib_avg_cost"] == pytest.approx(28.95, abs=0.01)
        assert row["avg_cost_drift_per_share"] == pytest.approx(0.45, abs=0.01)
        assert row.get("avg_cost_drift_explains_pct", 0) >= 99.0

    @pytest.mark.asyncio
    async def test_clean_match_zero_avg_cost_drift(self, monkeypatch):
        """When bot.entry_price == ib.avgCost, no
        avg_cost_drift_explains_pct field is attached."""
        _patch(monkeypatch, [
            {"symbol": "OK", "position": 100, "avgCost": 100.0,
             "marketPrice": 101.0, "unrealizedPNL": 100.0},
        ], [
            {"symbol": "OK", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "entry_price": 100.0,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert row.get("avg_cost_drift_per_share", 0) == 0
        assert "avg_cost_drift_explains_pct" not in row

    @pytest.mark.asyncio
    async def test_timing_skew_does_not_fire_avg_cost_action(
        self, monkeypatch
    ):
        """KMB-style timing skew: bot.entry == ib.avgCost — the
        avg_cost action line must NOT fire."""
        _patch(monkeypatch, [
            {"symbol": "KMB", "position": 100, "avgCost": 135.0,
             "marketPrice": 137.5, "unrealizedPNL": 250.0},
        ], [
            {"symbol": "KMB", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 245.0,
             "entry_price": 135.0,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "avg_cost mismatch" not in joined.lower()

    @pytest.mark.asyncio
    async def test_summary_avg_cost_drift_rows_count(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "ICLN", "position": 100, "avgCost": 28.95,
             "marketPrice": 29.00, "unrealizedPNL": 5.0},
            {"symbol": "EWZ", "position": 50, "avgCost": 30.40,
             "marketPrice": 30.50, "unrealizedPNL": 5.0},
            {"symbol": "CLEAN", "position": 100, "avgCost": 50.0,
             "marketPrice": 50.50, "unrealizedPNL": 50.0},
        ], [
            {"symbol": "ICLN", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 50.0, "entry_price": 28.50,
             "pnl_source": "quote_last", "source": "bot"},
            {"symbol": "EWZ", "shares": 50, "remaining_shares": 50,
             "direction": "long", "pnl": 30.0, "entry_price": 30.00,
             "pnl_source": "quote_last", "source": "bot"},
            {"symbol": "CLEAN", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 50.0, "entry_price": 50.0,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        assert resp["summary"]["avg_cost_drift_rows"] == 2

    @pytest.mark.asyncio
    async def test_action_line_names_worst_offender(self, monkeypatch):
        _patch(monkeypatch, [
            {"symbol": "ICLN", "position": 100, "avgCost": 28.95,
             "marketPrice": 29.00, "unrealizedPNL": 5.0},
        ], [
            {"symbol": "ICLN", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 50.0,
             "entry_price": 28.50,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        joined = " | ".join(resp["actions"])
        assert "ICLN" in joined
        assert "avg_cost" in joined.lower()
        assert ("commission" in joined.lower()
                or "etf distribution" in joined.lower()
                or "corp-action" in joined.lower())
        assert ("reconcile-share-drift" in joined.lower()
                or "tws" in joined.lower())

    @pytest.mark.asyncio
    async def test_missing_entry_price_skips_block(self, monkeypatch):
        """Legacy bot row without entry_price must not crash; block
        is simply absent."""
        _patch(monkeypatch, [
            {"symbol": "LEG", "position": 100, "avgCost": 50.0,
             "marketPrice": 51.0, "unrealizedPNL": 100.0},
        ], [
            {"symbol": "LEG", "shares": 100, "remaining_shares": 100,
             "direction": "long", "pnl": 100.0,
             "pnl_source": "quote_last", "source": "bot"},
        ])
        from routers.diagnostic_router import position_pnl_audit
        resp = await position_pnl_audit()
        row = resp["rows"][0]
        assert "avg_cost_drift_per_share" not in row
        assert "bot_entry_price" not in row

