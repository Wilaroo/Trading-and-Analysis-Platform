"""
v322t — Field-preserving rehydration + single-row persistence
==============================================================

Closes the CASY "bookkeeping rewrite" bug class for good.

Background
----------
Every BotTrade-from-Mongo path historically reconstructed the dataclass
from a hardcoded field subset. Anything NOT in the subset reset to the
dataclass default, and the next persist_trade/_save_trade rewrote Mongo
with the wiped values. Each occurrence got a one-off field patch:
  v19.34.21  dict_to_trade (remaining_shares zombies)
  v19.34.87  restore_open_trades (bracket ids / remaining_shares)
  v19.34.199 restore_open_trades (TQS grades)
  v322s      restore_open_trades (created_at="" → 675 corrupted rows)

v322t fixes the CLASS, not the instance:
  1. `hydrate_trade_from_doc` — one generic allow-list hydrator used by
     restore_open_trades, restore_closed_trades, and dict_to_trade.
     Every persisted dataclass field round-trips automatically,
     including fields added in the future.
  2. `save_trade` — was `replace_one({"_id": id}, full_doc)`:
     a) full-document REPLACE dropped Mongo-only fields (repair-audit
        markers etc.);
     b) keyed on `_id` while persist_trade keys on `id` — when
        persist_trade created the row first (auto ObjectId), save_trade
        upserted a SECOND row for the same trade. One copy then goes
        stale (`rejected`) while the other updates (`open`): the CASY
        rejected-vs-active two-row signature.
     Now `update_one({"id": id}, {"$set": ...}, upsert=True)`.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "backend")


def _doc(**overrides):
    """A realistic persisted bot_trades row with the fields that the
    pre-v322t restore path silently wiped."""
    base = {
        "id": "casy-001",
        "symbol": "CASY",
        "direction": "long",
        "status": "open",
        "setup_type": "orb_breakout",
        "timeframe": "intraday",
        "quality_score": 82,
        "quality_grade": "A",
        "entry_price": 412.50,
        "current_price": 415.10,
        "stop_price": 408.00,
        "target_prices": [418.0, 424.0, 430.0],
        "shares": 50,
        "risk_amount": 225.0,
        "potential_reward": 575.0,
        "risk_reward_ratio": 2.55,
        "fill_price": 412.55,
        # ── fields the pre-v322t subset restore WIPED ──
        "created_at": "2026-06-10T13:31:07.123456+00:00",
        "trade_style": "scalp",
        "close_at_eod": False,
        "trade_type": "paper",
        "account_id_at_fill": "DUN12345",
        "realized_pnl": 87.50,
        "total_commissions": 2.10,
        "net_pnl": 85.40,
        "tape_score": 8,
        "target_r_multiple": 2.5,
        "direction_bias": "long",
        "estimated_duration": "30min-2hr",
        "pre_submit_at": "2026-06-10T13:31:05+00:00",
        "target_ever_attached": True,
        "bracket_attach_count": 3,
        "last_bracket_attach_at": "2026-06-10T14:02:11+00:00",
        "scale_out_config": {
            "enabled": True,
            "targets_hit": [0],
            "scale_out_pcts": [0.33, 0.33, 0.34],
            "partial_exits": [{"target_idx": 0, "shares_sold": 16,
                               "price": 418.02, "pnl": 87.5}],
            "m0_legs": [
                {"idx": 0, "qty": 16, "target_px": 418.0,
                 "stop_order_id": "S1", "target_order_id": "T1",
                 "status": "filled"},
                {"idx": 1, "qty": 17, "target_px": 424.0,
                 "stop_order_id": "S2", "target_order_id": "T2",
                 "status": "working"},
                {"idx": 2, "qty": 17, "target_px": 430.0,
                 "stop_order_id": "S3", "target_order_id": "T3",
                 "status": "working"},
            ],
        },
        "remaining_shares": 34,
        "original_shares": 50,
        "entered_by": "bot_fired",
    }
    base.update(overrides)
    return base


def _restore_one_open(trade_doc):
    """Drive the REAL restore_open_trades against a mongomock DB and
    return the restored in-memory trade."""
    import asyncio
    import mongomock
    from services.bot_persistence import BotPersistence

    db = mongomock.MongoClient()["tradecommand_test"]
    db.bot_trades.insert_one(dict(trade_doc))

    bot = SimpleNamespace(_db=db, _open_trades={}, _pending_trades={})
    persistence = BotPersistence()

    async def _noop(*a, **k):
        return None

    persistence.delayed_reconciliation = _noop  # no IB in tests

    async def _run():
        await persistence.restore_open_trades(bot)

    asyncio.run(_run())
    assert len(bot._open_trades) == 1, "trade was not restored at all"
    return next(iter(bot._open_trades.values()))


# ──────────────────────────────────────────────────────────────────────
# 1. The 675-row regression: created_at must survive boot restore.
# ──────────────────────────────────────────────────────────────────────
def test_restore_preserves_created_at():
    trade = _restore_one_open(_doc())
    assert trade.created_at == "2026-06-10T13:31:07.123456+00:00", (
        "v322t regression: created_at wiped at restore — the next "
        "persist would rewrite Mongo with a fabricated timestamp "
        "(post-v322s) or '' (pre-v322s), corrupting forensics again."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. M0 ladder state: scale_out_config (m0_legs / targets_hit /
#    partial_exits) must survive boot restore.
# ──────────────────────────────────────────────────────────────────────
def test_restore_preserves_scale_out_config_and_m0_legs():
    trade = _restore_one_open(_doc())
    cfg = trade.scale_out_config
    assert cfg["targets_hit"] == [0], (
        "targets_hit wiped — restart would re-fire already-hit scale-outs"
    )
    assert len(cfg["m0_legs"]) == 3, (
        "m0_legs wiped — the bot loses all knowledge of its live OCA "
        "ladder across a restart (CASY ladder-kill class)"
    )
    assert cfg["m0_legs"][0]["status"] == "filled"
    assert len(cfg["partial_exits"]) == 1


# ──────────────────────────────────────────────────────────────────────
# 3. Risk-policy fields: close_at_eod=False (swing) must not flip back
#    to the dataclass default True.
# ──────────────────────────────────────────────────────────────────────
def test_restore_preserves_close_at_eod_false():
    trade = _restore_one_open(_doc(close_at_eod=False, trade_style="day_swing"))
    assert trade.close_at_eod is False, (
        "close_at_eod=False wiped to default True — a restored swing "
        "trade would get force-flattened at the next EOD window"
    )
    assert trade.trade_style == "day_swing"


# ──────────────────────────────────────────────────────────────────────
# 4. Audit/P&L/telemetry fields round-trip.
# ──────────────────────────────────────────────────────────────────────
def test_restore_preserves_pnl_provenance_and_bracket_telemetry():
    trade = _restore_one_open(_doc())
    assert trade.realized_pnl == 87.50
    assert trade.total_commissions == 2.10
    assert trade.net_pnl == 85.40
    assert trade.trade_type == "paper"
    assert trade.account_id_at_fill == "DUN12345"
    assert trade.target_ever_attached is True
    assert trade.bracket_attach_count == 3
    assert trade.last_bracket_attach_at == "2026-06-10T14:02:11+00:00"
    assert trade.tape_score == 8
    assert trade.estimated_duration == "30min-2hr"
    assert trade.pre_submit_at == "2026-06-10T13:31:05+00:00"


# ──────────────────────────────────────────────────────────────────────
# 5. The v87 fallbacks still refine AFTER hydration.
# ──────────────────────────────────────────────────────────────────────
def test_restore_fallbacks_still_apply_after_hydration():
    d = _doc()
    d.pop("remaining_shares")
    d.pop("original_shares")
    d["fill_price"] = None  # v19.34.27 None-coercion must still win
    trade = _restore_one_open(d)
    assert trade.remaining_shares == 50, "v87 fallback to shares broken"
    assert trade.original_shares == 50
    assert trade.fill_price == 412.50, (
        "v19.34.27 fill_price None→entry coercion must override hydration"
    )


# ──────────────────────────────────────────────────────────────────────
# 6. None-guard: a literal null container in Mongo must not replace the
#    structured default dict.
# ──────────────────────────────────────────────────────────────────────
def test_restore_null_container_keeps_structured_default():
    trade = _restore_one_open(_doc(scale_out_config=None))
    assert isinstance(trade.scale_out_config, dict)
    assert "targets_hit" in trade.scale_out_config


# ──────────────────────────────────────────────────────────────────────
# 7. Hydrator unit semantics: constructor fields and enums untouched,
#    unknown keys ignored.
# ──────────────────────────────────────────────────────────────────────
def test_hydrator_skips_constructor_fields_and_unknown_keys():
    from services.bot_persistence import hydrate_trade_from_doc
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    t = BotTrade(
        id="h-1", symbol="CASY", direction=TradeDirection("long"),
        status=TradeStatus("open"), setup_type="orb", timeframe="intraday",
        quality_score=80, quality_grade="A", entry_price=100.0,
        current_price=100.0, stop_price=98.0, target_prices=[104.0],
        shares=10, risk_amount=20.0, potential_reward=40.0,
        risk_reward_ratio=2.0,
    )
    hydrate_trade_from_doc(t, {
        "status": "rejected",         # constructor-set → must NOT clobber
        "direction": "short",         # constructor-set → must NOT clobber
        "symbol": "WRONG",            # constructor-set → must NOT clobber
        "_id": "mongo-objectid",      # not a dataclass field → ignored
        "some_random_key": 123,       # not a dataclass field → ignored
        "explanation": {"x": 1},      # explicitly excluded
        "created_at": "2026-06-01T00:00:00+00:00",
    })
    assert t.status == TradeStatus.OPEN
    assert t.direction == TradeDirection.LONG
    assert t.symbol == "CASY"
    assert not hasattr(t, "some_random_key")
    assert t.explanation is None
    assert t.created_at == "2026-06-01T00:00:00+00:00"


# ──────────────────────────────────────────────────────────────────────
# 8. Closed-trade history restore keeps created_at / trade_style.
# ──────────────────────────────────────────────────────────────────────
def test_restore_closed_trades_preserves_history_fields():
    import asyncio
    import mongomock
    from services.bot_persistence import BotPersistence

    db = mongomock.MongoClient()["tradecommand_test"]
    closed = _doc(status="closed", closed_at="2026-06-10T19:45:00+00:00",
                  exit_price=424.0, close_reason="target_2")
    db.bot_trades.insert_one(dict(closed))

    bot = SimpleNamespace(_db=db, _closed_trades=[])
    persistence = BotPersistence()

    asyncio.run(persistence.restore_closed_trades(bot))
    assert len(bot._closed_trades) == 1
    t = bot._closed_trades[0]
    assert t.created_at == "2026-06-10T13:31:07.123456+00:00"
    assert t.trade_style == "scalp"
    assert t.total_commissions == 2.10
    assert t.close_reason == "target_2"   # targeted override still wins
    assert t.exit_price == 424.0


# ──────────────────────────────────────────────────────────────────────
# 9. save_trade: $set semantics preserve Mongo-only fields.
# ──────────────────────────────────────────────────────────────────────
def _mk_trade(trade_id="casy-001"):
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    return BotTrade(
        id=trade_id, symbol="CASY", direction=TradeDirection("long"),
        status=TradeStatus("open"), setup_type="orb", timeframe="intraday",
        quality_score=80, quality_grade="A", entry_price=412.5,
        current_price=415.1, stop_price=408.0, target_prices=[418.0],
        shares=50, risk_amount=225.0, potential_reward=575.0,
        risk_reward_ratio=2.55,
    )


def test_save_trade_preserves_mongo_only_fields():
    import asyncio
    import mongomock
    from services.bot_persistence import BotPersistence

    db = mongomock.MongoClient()["tradecommand_test"]
    # Row pre-seeded with a Mongo-only audit marker (e.g. written by the
    # v322s repair script or the stale-pending pruner).
    db.bot_trades.insert_one({
        "id": "casy-001", "symbol": "CASY", "status": "open",
        "_repair_v322s_created_at_backfilled": True,
    })
    bot = SimpleNamespace(_db=db)
    trade = _mk_trade()
    trade.status = __import__(
        "services.trading_bot_service", fromlist=["TradeStatus"]
    ).TradeStatus.CLOSED

    asyncio.run(BotPersistence().save_trade(trade, bot))

    rows = list(db.bot_trades.find({"id": "casy-001"}))
    assert len(rows) == 1, "save_trade must not create a duplicate row"
    row = rows[0]
    assert row["status"] == "closed", "save_trade must update the row"
    assert row.get("_repair_v322s_created_at_backfilled") is True, (
        "v322t regression: replace_one semantics dropped a Mongo-only "
        "audit field — $set must preserve fields outside to_dict()"
    )


# ──────────────────────────────────────────────────────────────────────
# 10. save_trade + persist_trade converge on ONE row (the CASY
#     rejected-vs-active duplicate killer).
# ──────────────────────────────────────────────────────────────────────
def test_save_trade_and_persist_trade_share_one_row():
    import asyncio
    import mongomock
    from services.bot_persistence import BotPersistence

    db = mongomock.MongoClient()["tradecommand_test"]
    bot = SimpleNamespace(_db=db)
    persistence = BotPersistence()
    trade = _mk_trade("dup-1")

    # persist_trade first (creates row with auto ObjectId _id, id="dup-1")
    persistence.persist_trade(trade, bot)
    # save_trade second — pre-v322t this upserted a SECOND row keyed on
    # {"_id": "dup-1"}; one copy then went stale while the other updated.
    from services.trading_bot_service import TradeStatus
    trade.status = TradeStatus.CLOSED
    asyncio.run(persistence.save_trade(trade, bot))

    rows = list(db.bot_trades.find({"id": "dup-1"}))
    assert len(rows) == 1, (
        "v322t regression: save_trade and persist_trade wrote SEPARATE "
        "rows for the same trade id — the CASY rejected-vs-active "
        "two-row mismatch is back"
    )
    assert rows[0]["status"] == "closed"


# ──────────────────────────────────────────────────────────────────────
# 11. dict_to_trade still preserves state via the shared hydrator
#     (guards the v19.34.21 behavior through the refactor).
# ──────────────────────────────────────────────────────────────────────
def test_dict_to_trade_uses_shared_hydrator():
    from services.bot_persistence import BotPersistence
    d = _doc()
    trade = BotPersistence.dict_to_trade(d)
    assert trade is not None
    assert trade.remaining_shares == 34
    assert trade.created_at == "2026-06-10T13:31:07.123456+00:00"
    assert trade.scale_out_config["m0_legs"][1]["status"] == "working"
    assert trade.close_at_eod is False
