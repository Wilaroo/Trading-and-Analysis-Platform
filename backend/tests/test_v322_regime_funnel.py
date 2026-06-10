"""
v19.34.322 — Regime-First Funnel test suite.

Covers (no DB / no IB required):
  1. RS leadership math — weighted_rs_score + percentile_ranks (pure).
  2. Focus-list assembly — build_focus_list (pure).
  3. Gate funnel scorers — _score_sector_regime / _score_symbol_mtf /
     _score_rs_leadership (pure statics on ConfidenceGate).
  4. _compute_funnel_signals clamp + fail-open (async, mocked sub-fetches).
  5. P7 regime-conditional sample-count fix (source-level assertion —
     the old `len(X_list) < MIN_REGIME_SAMPLES` symbol-count bug is gone).
  6. Scanner wiring — LiveAlert carries rs_rating/focus_side fields;
     _get_symbols_for_cycle promotes focus symbols.
"""
import asyncio
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rs_leadership_service import (  # noqa: E402
    weighted_rs_score, percentile_ranks, has_split_artifact, RS_MIN_CLOSES,
)
from services.regime_focus_service import (  # noqa: E402
    build_focus_list, RS_FOCUS_LONG_MIN, RS_FOCUS_SHORT_MAX,
)
from services.ai_modules.confidence_gate import (  # noqa: E402
    ConfidenceGate,
    SECTOR_STRONG_BONUS, SECTOR_ROTATE_BONUS,
    SECTOR_AGAINST_PENALTY, SECTOR_ROTATE_PENALTY,
    SYMTF_ALIGNED_BONUS_MAX, SYMTF_ALIGNED_BONUS_MIN,
    SYMTF_COUNTER_PENALTY, SYMTF_COUNTER_SIZE_MULT,
    SYMTF_PULLBACK_BONUS, SYMTF_MILD_PENALTY,
    RS_STRONG_BONUS, RS_GOOD_BONUS, RS_WRONG_SIDE_PENALTY,
    FUNNEL_MAX_ABS_POINTS,
)


# ───────────────────────── 1. RS math ─────────────────────────

class TestWeightedRSScore:
    def test_thin_history_returns_none(self):
        assert weighted_rs_score([100.0] * (RS_MIN_CLOSES - 1)) is None

    def test_empty_and_zero_price(self):
        assert weighted_rs_score([]) is None
        closes = [100.0] * 70
        closes[-1] = 0.0
        assert weighted_rs_score(closes) is None

    def test_uptrend_scores_positive(self):
        # 70 closes climbing 100 → 169
        closes = [100.0 + i for i in range(70)]
        s = weighted_rs_score(closes)
        assert s is not None and s > 0

    def test_downtrend_scores_negative(self):
        closes = [200.0 - i for i in range(70)]
        s = weighted_rs_score(closes)
        assert s is not None and s < 0

    def test_only_63d_lag_used_when_history_short(self):
        # 70 closes — only the 63d lag fits; score should equal close[-1]/close[-64]-1
        closes = [100.0] * 70
        closes[-64] = 80.0
        s = weighted_rs_score(closes)
        assert s == pytest.approx(100.0 / 80.0 - 1.0)

    def test_full_history_weights_recent_quarter_double(self):
        # flat except recent quarter — 63d lag (weight 2) dominates
        closes = [100.0] * 253
        for i in range(1, 64):
            closes[-i] = 100.0 + i * 0.5  # recent ramp
        s_full = weighted_rs_score(closes)
        assert s_full is not None and s_full > 0


class TestPercentileRanks:
    def test_empty(self):
        assert percentile_ranks({}) == {}

    def test_single_symbol_gets_50(self):
        assert percentile_ranks({"AAPL": 0.1}) == {"AAPL": 50}

    def test_rank_bounds_1_to_99(self):
        scores = {f"S{i}": float(i) for i in range(200)}
        ranks = percentile_ranks(scores)
        assert min(ranks.values()) == 1
        assert max(ranks.values()) == 99
        assert ranks["S199"] == 99 and ranks["S0"] == 1

    def test_order_preserved(self):
        ranks = percentile_ranks({"LOW": -0.5, "MID": 0.0, "HIGH": 0.9})
        assert ranks["LOW"] < ranks["MID"] < ranks["HIGH"]


# ───────────────────────── 2. Focus list ─────────────────────────

def _ratings():
    A = 50_000_000  # comfortably above the $20M focus ADV floor
    return {
        "NVDA": {"rs_rating": 95, "sector": "XLK", "sector_rs_diff": 0.1, "adv": A},
        "AAPL": {"rs_rating": 85, "sector": "XLK", "sector_rs_diff": 0.02, "adv": A},
        "XOM":  {"rs_rating": 15, "sector": "XLE", "sector_rs_diff": -0.05, "adv": A},
        "CVX":  {"rs_rating": 8,  "sector": "XLE", "sector_rs_diff": -0.09, "adv": A},
        "JPM":  {"rs_rating": 90, "sector": "XLF", "sector_rs_diff": 0.04, "adv": A},  # weak sector
        "PG":   {"rs_rating": 50, "sector": "XLP", "sector_rs_diff": 0.0, "adv": A},   # mid RS
        "THIN": {"rs_rating": None, "sector": "XLK", "sector_rs_diff": None, "adv": A},
        "TINY": {"rs_rating": 99, "sector": "XLK", "sector_rs_diff": 0.2, "adv": 1_000_000},  # illiquid
    }


SECTORS = {"XLK": "strong", "XLE": "weak", "XLF": "rotating_out", "XLP": "neutral"}


class TestSplitArtifactGuard:
    def test_clean_series_passes(self):
        closes = [100.0 + i * 0.5 for i in range(100)]
        assert has_split_artifact(closes) is False

    def test_reverse_split_detected(self):
        closes = [2.0] * 50 + [120.0] * 50   # 60x jump = unadjusted 1:60 reverse split
        assert has_split_artifact(closes) is True

    def test_forward_split_detected(self):
        closes = [400.0] * 50 + [100.0] * 50  # 4:1 forward split
        assert has_split_artifact(closes) is True

    def test_big_but_legit_move_passes(self):
        closes = [100.0] * 50 + [250.0] * 50  # +150% gap < 3x threshold
        assert has_split_artifact(closes) is False


class TestBuildFocusList:
    def test_longs_require_rs_and_strong_sector(self):
        out = build_focus_list(_ratings(), SECTORS)
        long_syms = [r["symbol"] for r in out["longs"]]
        assert long_syms == ["NVDA", "AAPL"]  # JPM excluded (rotating_out sector)

    def test_shorts_require_low_rs_and_weak_sector(self):
        out = build_focus_list(_ratings(), SECTORS)
        short_syms = [r["symbol"] for r in out["shorts"]]
        assert short_syms == ["CVX", "XOM"]  # weakest first

    def test_none_rating_excluded(self):
        out = build_focus_list(_ratings(), SECTORS)
        all_syms = [r["symbol"] for r in out["longs"] + out["shorts"]]
        assert "THIN" not in all_syms and "PG" not in all_syms

    def test_illiquid_excluded_by_adv_floor(self):
        out = build_focus_list(_ratings(), SECTORS)
        assert "TINY" not in [r["symbol"] for r in out["longs"]]
        # floor disabled → TINY qualifies (RS 99, strong sector)
        out2 = build_focus_list(_ratings(), SECTORS, min_adv=0)
        assert "TINY" in [r["symbol"] for r in out2["longs"]]

    def test_unknown_sector_excluded(self):
        ratings = {"ZZZ": {"rs_rating": 99, "sector": None, "sector_rs_diff": None}}
        out = build_focus_list(ratings, SECTORS)
        assert out["longs"] == [] and out["shorts"] == []

    def test_top_n_respected(self):
        ratings = {f"L{i}": {"rs_rating": 80 + (i % 20), "sector": "XLK",
                             "sector_rs_diff": 0.0, "adv": 5e7} for i in range(100)}
        out = build_focus_list(ratings, {"XLK": "strong"}, top_n=10)
        assert len(out["longs"]) == 10

    def test_modes_and_context_passthrough(self):
        out = build_focus_list({}, {}, modes={"long": "aggressive"}, market_context="ALIGNED_UP")
        assert out["market_context"] == "ALIGNED_UP"
        assert out["modes"]["long"] == "aggressive"
        assert out["thresholds"]["rs_long_min"] == RS_FOCUS_LONG_MIN
        assert out["thresholds"]["rs_short_max"] == RS_FOCUS_SHORT_MAX


# ───────────────────────── 3. Gate scorers ─────────────────────────

def _gate():
    return ConfidenceGate(db=None)


class TestScoreSectorRegime:
    def test_long_strong_bonus(self):
        pts, rsn = ConfidenceGate._score_sector_regime("strong", "long")
        assert pts == SECTOR_STRONG_BONUS and rsn

    def test_long_rotating_in_bonus(self):
        pts, _ = ConfidenceGate._score_sector_regime("rotating_in", "long")
        assert pts == SECTOR_ROTATE_BONUS

    def test_long_weak_penalty(self):
        pts, _ = ConfidenceGate._score_sector_regime("weak", "long")
        assert pts == -SECTOR_AGAINST_PENALTY

    def test_short_weak_bonus(self):
        pts, _ = ConfidenceGate._score_sector_regime("weak", "short")
        assert pts == SECTOR_STRONG_BONUS

    def test_short_strong_penalty(self):
        pts, _ = ConfidenceGate._score_sector_regime("strong", "short")
        assert pts == -SECTOR_AGAINST_PENALTY

    def test_short_rotating_in_penalty(self):
        pts, _ = ConfidenceGate._score_sector_regime("rotating_in", "short")
        assert pts == -SECTOR_ROTATE_PENALTY

    def test_unknown_neutral_zero(self):
        for sr in ("unknown", "neutral", "", None):
            pts, rsn = ConfidenceGate._score_sector_regime(sr, "long")
            assert pts == 0 and rsn == []


def _sym_mtf(context, ratio=1.0, lanes=4):
    return {"context": context,
            "tf_alignment": {"ratio": ratio, "lanes_counted": lanes}}


class TestScoreSymbolMtf:
    def test_aligned_up_long_full_bonus(self):
        pts, mult, rsn = ConfidenceGate._score_symbol_mtf(_sym_mtf("ALIGNED_UP", 1.0), "long")
        assert pts == SYMTF_ALIGNED_BONUS_MAX and mult == 1.0 and rsn

    def test_aligned_up_long_min_floor(self):
        pts, _, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("ALIGNED_UP", 0.05), "long")
        assert pts == SYMTF_ALIGNED_BONUS_MIN

    def test_aligned_up_short_counter_penalty(self):
        pts, mult, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("ALIGNED_UP"), "short")
        assert pts == -SYMTF_COUNTER_PENALTY and mult == SYMTF_COUNTER_SIZE_MULT

    def test_aligned_down_short_bonus(self):
        pts, mult, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("ALIGNED_DOWN", 1.0), "short")
        assert pts == SYMTF_ALIGNED_BONUS_MAX and mult == 1.0

    def test_pullback_long_bonus_short_mild_penalty(self):
        pts_l, _, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("PULLBACK_IN_UPTREND"), "long")
        pts_s, _, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("PULLBACK_IN_UPTREND"), "short")
        assert pts_l == SYMTF_PULLBACK_BONUS and pts_s == -SYMTF_MILD_PENALTY

    def test_bounce_short_bonus(self):
        pts, _, _ = ConfidenceGate._score_symbol_mtf(_sym_mtf("BOUNCE_IN_DOWNTREND"), "short")
        assert pts == SYMTF_PULLBACK_BONUS

    def test_unknown_or_cold_zero(self):
        assert ConfidenceGate._score_symbol_mtf(None, "long") == (0, 1.0, [])
        assert ConfidenceGate._score_symbol_mtf(_sym_mtf("UNKNOWN"), "long")[0] == 0
        assert ConfidenceGate._score_symbol_mtf(_sym_mtf("ALIGNED_UP", 1.0, lanes=0), "long")[0] == 0


class TestScoreRSLeadership:
    def test_long_elite(self):
        pts, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 95}, "long")
        assert pts == RS_STRONG_BONUS

    def test_long_leader(self):
        pts, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 82}, "long")
        assert pts == RS_GOOD_BONUS

    def test_long_laggard_penalty(self):
        pts, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 12}, "long")
        assert pts == -RS_WRONG_SIDE_PENALTY

    def test_short_weakest_bonus(self):
        pts, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 5}, "short")
        assert pts == RS_STRONG_BONUS

    def test_short_leader_penalty(self):
        pts, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 88}, "short")
        assert pts == -RS_WRONG_SIDE_PENALTY

    def test_mid_rs_zero(self):
        assert ConfidenceGate._score_rs_leadership({"rs_rating": 55}, "long")[0] == 0
        assert ConfidenceGate._score_rs_leadership({"rs_rating": 55}, "short")[0] == 0

    def test_none_safe(self):
        assert ConfidenceGate._score_rs_leadership(None, "long") == (0, [])
        assert ConfidenceGate._score_rs_leadership({"rs_rating": None}, "long") == (0, [])


# ───────────────────────── 4. _compute_funnel_signals ─────────────────────────

class _FakeEngine:
    def __init__(self, mtf):
        self._mtf = mtf

    async def compute_symbol_multi_tf_cached(self, symbol):
        return self._mtf


class TestComputeFunnelSignals:
    def test_full_alignment_clamped(self, monkeypatch):
        """strong sector (+6) + aligned symbol (+10) + RS 95 (+6) = 22 → clamp 15."""
        g = _gate()

        async def fake_sector(self, symbol, direction, regime_engine):
            pass  # not used — we monkeypatch sub-pieces instead

        import services.ai_modules.confidence_gate as cg

        class _FakeSec:
            async def classify_for_symbol(self, symbol):
                class _L:
                    value = "strong"
                return _L()

        class _FakeRS:
            async def get_rating(self, symbol):
                return {"rs_rating": 95}

        monkeypatch.setattr(
            "services.sector_regime_classifier.get_sector_regime_classifier",
            lambda db=None: _FakeSec())
        monkeypatch.setattr(
            "services.rs_leadership_service.get_rs_leadership_service",
            lambda db=None: _FakeRS())

        engine = _FakeEngine(_sym_mtf("ALIGNED_UP", 1.0))
        out = asyncio.get_event_loop().run_until_complete(
            g._compute_funnel_signals("NVDA", "long", engine))
        assert out["points_raw"] == SECTOR_STRONG_BONUS + SYMTF_ALIGNED_BONUS_MAX + RS_STRONG_BONUS
        assert out["points"] == FUNNEL_MAX_ABS_POINTS
        assert out["sector_regime"] == "strong"
        assert out["rs_rating"] == 95
        assert out["symbol_mtf_context"] == "ALIGNED_UP"
        assert out["breakdown"] == {"sector": SECTOR_STRONG_BONUS,
                                    "symbol_mtf": SYMTF_ALIGNED_BONUS_MAX,
                                    "rs": RS_STRONG_BONUS}

    def test_fail_open_all_sources_down(self, monkeypatch):
        """Every sub-fetch raising → 0 points, mult 1.0, no crash."""
        g = _gate()

        def _boom(db=None):
            raise RuntimeError("down")

        monkeypatch.setattr(
            "services.sector_regime_classifier.get_sector_regime_classifier", _boom)
        monkeypatch.setattr(
            "services.rs_leadership_service.get_rs_leadership_service", _boom)

        out = asyncio.get_event_loop().run_until_complete(
            g._compute_funnel_signals("AAPL", "long", None))
        assert out["points"] == 0 and out["size_mult"] == 1.0
        assert out["rs_rating"] is None and out["symbol_mtf_context"] is None


# ───────────────────────── 5. P7 sample-count fix ─────────────────────────

class TestP7RegimeSampleCountFix:
    def test_symbol_count_bug_is_gone(self):
        src_path = os.path.join(os.path.dirname(__file__), "..",
                                "services", "ai_modules", "training_pipeline.py")
        with open(src_path) as f:
            src = f.read()
        assert "if len(X_list) < MIN_REGIME_SAMPLES" not in src, (
            "P7 still compares SYMBOL-CHUNK count against MIN_REGIME_SAMPLES")
        assert "n_regime_samples = int(sum(len(y) for y in y_list))" in src
        assert "n_regime_samples < MIN_REGIME_SAMPLES" in src


# ───────────────────────── 6. Scanner wiring ─────────────────────────

class TestScannerWiring:
    def test_livealert_has_funnel_fields(self):
        from services.enhanced_scanner import LiveAlert
        import dataclasses
        names = {f.name for f in dataclasses.fields(LiveAlert)}
        assert "rs_rating" in names and "focus_side" in names

    @staticmethod
    def _bare_scanner():
        from services.enhanced_scanner import EnhancedBackgroundScanner
        from datetime import datetime, timezone
        sc = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
        sc._tier_cache_time = datetime.now(timezone.utc)
        sc._tier_cache_ttl = 3600
        sc._swing_scan_frequency = 8
        # attrs needed by _classify_symbol_tier (eagerly evaluated by dict.get default)
        sc._adv_cache = {}
        sc._known_liquid_symbols = set()
        sc._known_liquid_adv = {}
        sc._known_liquid_default_adv = 0
        sc._min_adv_intraday = 500_000
        sc._min_adv_general = 100_000
        return sc

    def test_get_symbols_for_cycle_promotes_focus(self):
        sc = self._bare_scanner()
        sc._tier_cache = {"AAPL": "intraday", "SLOW": "swing", "FOCUS": "swing"}
        sc._scan_count = 1            # not a multiple of 8 → swing skipped
        sc._focus_symbols = {"FOCUS": "long"}
        out = sc._get_symbols_for_cycle(["AAPL", "SLOW", "FOCUS"])
        assert "AAPL" in out          # intraday always
        assert "FOCUS" in out         # v322 promotion
        assert "SLOW" not in out      # swing off-cycle

    def test_focus_promotion_does_not_demote(self):
        """Non-focus swing symbols still scan on their tier cadence."""
        sc = self._bare_scanner()
        sc._tier_cache = {"SLOW": "swing"}
        sc._scan_count = 8            # multiple of 8 → swing scans
        sc._focus_symbols = {}
        assert sc._get_symbols_for_cycle(["SLOW"]) == ["SLOW"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
