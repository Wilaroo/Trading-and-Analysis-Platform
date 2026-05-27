"""v19.34.164 — record_rejection() must persist to `trade_drops`.

Operator-discovered May 2026:
  - 251 `9_ema_scalp` alerts emitted by scanner in 30d → 0 trades, 0 drops.
  - Root cause: `record_rejection()` only wrote to in-memory UI buffer
    + sentcom_thoughts stream — never to the `trade_drops` MongoDB
    collection that drives the Diagnostics tab.
  - Effect: ~90% of trade rejections were invisible to operators.

This suite verifies:
  1. record_rejection() persists one row to trade_drops per (rejected) call.
  2. Schema matches the Diagnostics tab's expectations
     (gate, symbol, setup_type, direction, reason, context, ts_epoch_ms).
  3. The 120s in-memory dedup window prevents duplicate inserts for the
     same (symbol, setup_type, reason_code) tuple — so a noisy
     scanner re-emitting the same alert every 30s does NOT pollute
     trade_drops.
  4. KNOWN_GATES contains every reason_code the bot emits today.
  5. REASON_MAP in rejection_analytics_router knows about each new gate.
  6. Persistence failures (Mongo down) do not crash the hot path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make sure /app/backend is on sys.path for `services.*` / `routers.*`.
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────
class _FakeCollection:
    """Minimal Mongo collection stand-in capturing every insert_one."""

    def __init__(self):
        self.inserted: list[dict] = []
        self.created_indexes: list = []

    def insert_one(self, doc: dict):
        # Mimic Mongo's mutation of the passed dict (it adds _id),
        # but only after we've captured the original payload.
        self.inserted.append(dict(doc))
        doc["_id"] = f"oid_{len(self.inserted)}"
        return MagicMock(inserted_id=doc["_id"])

    def create_index(self, *args, **kwargs):
        self.created_indexes.append((args, kwargs))

    def find(self, *_, **__):
        return iter([])


class _FakeDB:
    def __init__(self):
        self._cols: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCollection())


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture(autouse=True)
def _reset_recorder_state():
    """Reset the trade_drop_recorder's in-memory buffer + index flag
    between tests so each test starts clean."""
    from services import trade_drop_recorder as tdr
    tdr.reset_memory_buffer_for_tests()
    # Force re-creation of indexes per fake db so each test sees fresh
    # index calls.
    tdr._indexes_ready = False
    yield
    tdr.reset_memory_buffer_for_tests()
    tdr._indexes_ready = False


@pytest.fixture
def stub_bot(fake_db):
    """Return a minimal stand-in for TradingBotService that exposes the
    real `record_rejection` method bound onto it."""
    from services.trading_bot_service import TradingBotService

    # Create an instance attribute holder without running __init__
    # (which spawns IB/Alpaca/etc.).
    bot = TradingBotService.__new__(TradingBotService)
    bot._db = fake_db
    # Minimal stand-ins required by record_rejection's helpers.
    bot._smart_filter = MagicMock()
    bot._smart_filter.add_thought = MagicMock()
    bot._smart_filter.get_thoughts = MagicMock(return_value=[])
    bot._strategy_filter_thoughts = []
    bot._max_filter_thoughts = 50
    bot._last_evaluator_rejection_recorded = False
    return bot


# ─────────────────────────────────────────────────────────────────────
# 1. Basic persistence — one row per record_rejection() call
# ─────────────────────────────────────────────────────────────────────
def test_record_rejection_persists_to_trade_drops(stub_bot, fake_db):
    narrative = stub_bot.record_rejection(
        symbol="AAPL",
        setup_type="9_ema_scalp",
        direction="long",
        reason_code="rr_below_min",
        context={"rr_ratio": 1.42, "min_required": 2.0},
    )
    assert isinstance(narrative, str) and len(narrative) > 0

    inserted = fake_db["trade_drops"].inserted
    assert len(inserted) == 1, (
        f"expected exactly 1 trade_drops insert; got {len(inserted)}"
    )

    row = inserted[0]
    assert row["gate"] == "rr_below_min"
    assert row["symbol"] == "AAPL"
    assert row["setup_type"] == "9_ema_scalp"
    assert row["direction"] == "long"
    assert "ts_epoch_ms" in row and isinstance(row["ts_epoch_ms"], int)
    assert "ts" in row and isinstance(row["ts"], str)  # ISO string
    # Context must carry the original kwargs PLUS the synthesized
    # narrative so operators reading trade_drops directly see the
    # full "why I passed" line.
    assert row["context"]["rr_ratio"] == 1.42
    assert row["context"]["min_required"] == 2.0
    assert "narrative" in row["context"]
    assert "AAPL" in row["context"]["narrative"] or len(row["context"]["narrative"]) > 0


# ─────────────────────────────────────────────────────────────────────
# 2. Dedup — repeated rejections within 120s window stay single-write
# ─────────────────────────────────────────────────────────────────────
def test_record_rejection_dedup_suppresses_dup_db_writes(stub_bot, fake_db):
    common = dict(
        symbol="TSLA",
        setup_type="9_ema_scalp",
        direction="long",
        reason_code="gate_skip",
        context={"confidence_score": 42},
    )
    # First call: writes.
    stub_bot.record_rejection(**common)
    # 5 follow-up calls in quick succession: all suppressed by 120s dedup.
    for _ in range(5):
        stub_bot.record_rejection(**common)

    inserted = fake_db["trade_drops"].inserted
    assert len(inserted) == 1, (
        f"dedup should suppress follow-ups; got {len(inserted)} writes"
    )
    assert inserted[0]["gate"] == "gate_skip"


def test_record_rejection_dedup_isolated_per_tuple(stub_bot, fake_db):
    """Different (symbol, setup, reason) tuples must NOT block each other."""
    stub_bot.record_rejection(
        symbol="AAPL", setup_type="breakout", direction="long",
        reason_code="rr_below_min",
        context={"rr_ratio": 1.2, "min_required": 2.0},
    )
    stub_bot.record_rejection(
        symbol="TSLA", setup_type="breakout", direction="long",
        reason_code="rr_below_min",
        context={"rr_ratio": 1.3, "min_required": 2.0},
    )
    stub_bot.record_rejection(
        symbol="AAPL", setup_type="breakout", direction="long",
        reason_code="gate_skip",
        context={"confidence_score": 31, "why": "regime flip"},
    )
    assert len(fake_db["trade_drops"].inserted) == 3


# ─────────────────────────────────────────────────────────────────────
# 3. KNOWN_GATES must include every reason_code the bot actually emits
# ─────────────────────────────────────────────────────────────────────
# These are the reason_codes grepped from trading_bot_service.py and
# opportunity_evaluator.py — must be kept in sync.
EMITTED_REASON_CODES = {
    "stale_alert_ttl",
    "post_stop_cooldown",
    "symbol_direction_open_cap_v123",
    "eod_no_new_entries",
    "no_price",
    "smart_filter_skip",
    "gate_skip",
    "symbol_exposure_saturated",
    "position_size_zero",
    "rr_below_min",
    "ai_consultation_block",
    "ai_verdict_reject",
    "evaluator_exception",
    "evaluator_veto_unknown",
    "max_open_positions",
    "dedup_cooldown",
    "dedup_open_position",
    "position_exists",
    "pending_trade_exists",
    "setup_disabled",
    "watchlist_only_skip",
}


def test_known_gates_covers_all_emitted_reason_codes():
    from services.trade_drop_recorder import KNOWN_GATES
    missing = EMITTED_REASON_CODES - set(KNOWN_GATES)
    assert not missing, (
        f"KNOWN_GATES is missing emitted reason_codes: {sorted(missing)}. "
        "Add them to trade_drop_recorder.KNOWN_GATES."
    )


def test_reason_map_covers_all_emitted_reason_codes():
    from routers.rejection_analytics_router import REASON_MAP
    missing = EMITTED_REASON_CODES - set(REASON_MAP)
    assert not missing, (
        f"REASON_MAP is missing emitted reason_codes: {sorted(missing)}. "
        "Add labels in rejection_analytics_router.REASON_MAP."
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Persistence never crashes the hot path (Mongo down / db=None)
# ─────────────────────────────────────────────────────────────────────
def test_record_rejection_survives_db_none(stub_bot):
    stub_bot._db = None
    # Must not raise even with no db.
    out = stub_bot.record_rejection(
        symbol="NVDA", setup_type="breakout", direction="long",
        reason_code="no_price", context={"why": "feed down"},
    )
    assert isinstance(out, str)


def test_record_rejection_survives_db_insert_exception(stub_bot, fake_db):
    """Mongo flap mid-write must not crash the evaluator."""
    bad = fake_db["trade_drops"]

    def _boom(_doc):
        raise RuntimeError("simulated mongo flap")

    bad.insert_one = _boom  # type: ignore

    # Must still return narrative; failure is swallowed at debug level.
    out = stub_bot.record_rejection(
        symbol="META", setup_type="breakdown", direction="short",
        reason_code="ai_consultation_block",
        context={"why": "regime flip mid-bar"},
    )
    assert isinstance(out, str) and len(out) > 0


# ─────────────────────────────────────────────────────────────────────
# 5. The schema written must satisfy the Diagnostics aggregator
# ─────────────────────────────────────────────────────────────────────
def test_inserted_row_passes_rejection_analytics_aggregator(stub_bot, fake_db):
    """The diagnostic endpoint reads trade_drops via ts_epoch_ms range
    and the analytics router normalises by `gate`/`reason`. Make sure the
    schema we write actually matches what those readers expect."""
    stub_bot.record_rejection(
        symbol="AMD",
        setup_type="vwap_fade",
        direction="long",
        reason_code="post_stop_cooldown",
        context={"cooldown_remaining_seconds": 412.0},
    )
    row = fake_db["trade_drops"].inserted[0]
    # Required fields the diagnostics aggregator queries.
    for k in ("ts_epoch_ms", "gate", "symbol", "setup_type", "direction", "reason"):
        assert k in row, f"diagnostics aggregator needs `{k}` but it was missing"
    # gate must round-trip through the analytics normaliser without
    # collapsing to "other".
    from routers.rejection_analytics_router import _normalise_reason, REASON_MAP
    key = _normalise_reason(row["gate"])
    assert key in REASON_MAP, (
        f"normalised gate `{key}` (from `{row['gate']}`) not in REASON_MAP"
    )
