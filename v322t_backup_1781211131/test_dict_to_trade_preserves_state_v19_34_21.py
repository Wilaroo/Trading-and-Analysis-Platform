"""
v19.34.21 — Verify `dict_to_trade` preserves ALL persisted BotTrade fields.

Pre-fix bug: `bot_persistence.py:dict_to_trade` only passed ~25 of
~50 BotTrade fields to the constructor. Critical missing fields
included `remaining_shares`, `original_shares`, `scale_out_config`,
`trailing_stop_config`, `mfe_*`, `mae_*`, `entered_by`,
`prior_verdicts`, etc.

The biggest impact was `remaining_shares` being silently reset to 0
on every bot restart, turning every open BotTrade into a zombie. The
manage-loop self-heal at `position_manager.py:494` was only saving
positions that got a fresh quote within ~30s of restart.

Operator-discovered 2026-05-06: a821575c (the v19.34.19 heal trade
itself) had `rs=369` post-spawn but `rs=0` in DB by the next periodic
save — because it was loaded from DB with rs=0 (default) on restart.
"""
import os
import sys

import pytest


def test_dict_to_trade_preserves_remaining_shares_v19_34_21():
    """The smoking gun: rs must round-trip through serialize → deserialize."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "ROUNDTRIP-1",
        "symbol": "FDX",
        "direction": "long",
        "status": "open",
        "setup_type": "reconciled_excess_slice",
        "timeframe": "intraday",
        "quality_score": 50,
        "quality_grade": "R",
        "entry_price": 367.52,
        "current_price": 367.52,
        "stop_price": 363.84,
        "target_prices": [371.20],
        "shares": 369,
        "risk_amount": 1357.32,
        "potential_reward": 1357.32,
        "risk_reward_ratio": 1.0,
        # Critical fields that were silently dropped pre-fix:
        "remaining_shares": 369,
        "original_shares": 369,
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.id == "ROUNDTRIP-1"
    assert trade.shares == 369
    assert trade.remaining_shares == 369, (
        "v19.34.21 regression: remaining_shares not preserved on reload — "
        "every restart would silently zombify this trade."
    )
    assert trade.original_shares == 369


def test_dict_to_trade_preserves_scale_out_config_v19_34_21():
    """Scale-out tracking must round-trip — pre-fix every restart wiped
    `targets_hit=[]` and re-fired already-completed scale-outs."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "SCALE-1",
        "symbol": "FDX",
        "direction": "long",
        "status": "open",
        "setup_type": "gap_fade",
        "timeframe": "intraday",
        "quality_score": 80,
        "quality_grade": "A",
        "entry_price": 100.0,
        "current_price": 100.0,
        "stop_price": 95.0,
        "target_prices": [110.0, 120.0, 130.0],
        "shares": 300,
        "risk_amount": 1500,
        "potential_reward": 3000,
        "risk_reward_ratio": 2.0,
        "scale_out_config": {
            "enabled": True,
            "targets_hit": [0, 1],  # Two targets already hit!
            "scale_out_pcts": [0.33, 0.33, 0.34],
            "partial_exits": [
                {"target_idx": 1, "shares_sold": 100},
                {"target_idx": 2, "shares_sold": 100},
            ],
        },
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.scale_out_config["targets_hit"] == [0, 1], (
        "v19.34.21 regression: scale_out_config not preserved — "
        "restart would re-fire already-hit scale-outs."
    )
    assert len(trade.scale_out_config["partial_exits"]) == 2


def test_dict_to_trade_preserves_trailing_stop_config_v19_34_21():
    """Trailing-stop history must round-trip."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "TRAIL-1",
        "symbol": "FDX",
        "direction": "long",
        "status": "open",
        "setup_type": "scalp",
        "timeframe": "scalp",
        "quality_score": 70,
        "quality_grade": "B",
        "entry_price": 100.0,
        "current_price": 105.0,
        "stop_price": 102.0,  # Already trailed up
        "target_prices": [110.0],
        "shares": 100,
        "risk_amount": 500,
        "potential_reward": 1000,
        "risk_reward_ratio": 2.0,
        "trailing_stop_config": {
            "enabled": True,
            "mode": "breakeven",  # Was advanced past "original"
            "original_stop": 98.0,
            "current_stop": 102.0,
            "trail_pct": 0.02,
            "trail_atr_mult": 1.5,
            "high_water_mark": 106.0,
            "low_water_mark": 0.0,
            "stop_adjustments": [
                {"from": 98.0, "to": 100.0, "reason": "T1"},
                {"from": 100.0, "to": 102.0, "reason": "trail"},
            ],
        },
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.trailing_stop_config["mode"] == "breakeven", (
        "v19.34.21 regression: trailing_stop_config not preserved — "
        "restart would reset stop to 'original' mode and lose history."
    )
    assert trade.trailing_stop_config["high_water_mark"] == 106.0
    assert len(trade.trailing_stop_config["stop_adjustments"]) == 2


def test_dict_to_trade_preserves_provenance_fields_v19_34_21():
    """`entered_by`, `prior_verdicts`, `synthetic_source`, `pre_submit_at`,
    `account_id_at_fill`, `trade_type` — all v19.34.x audit fields."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "PROV-1",
        "symbol": "VALE",
        "direction": "short",
        "status": "open",
        "setup_type": "reconciled_orphan",
        "timeframe": "intraday",
        "quality_score": 50,
        "quality_grade": "R",
        "entry_price": 12.0,
        "current_price": 12.0,
        "stop_price": 12.5,
        "target_prices": [11.0],
        "shares": 100,
        "risk_amount": 50,
        "potential_reward": 100,
        "risk_reward_ratio": 2.0,
        "entered_by": "reconciled_external",
        "prior_verdicts": [
            {"timestamp": "2026-05-04T15:00Z", "reason_code": "rr_too_low"}
        ],
        "prior_verdict_conflict": True,
        "synthetic_source": "default_pct",
        "pre_submit_at": "2026-05-05T15:25:00Z",
        "account_id_at_fill": "DUN615665",
        "trade_type": "paper",
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.entered_by == "reconciled_external"
    assert trade.prior_verdict_conflict is True
    assert len(trade.prior_verdicts) == 1
    assert trade.synthetic_source == "default_pct"
    assert trade.pre_submit_at == "2026-05-05T15:25:00Z"
    assert trade.account_id_at_fill == "DUN615665"
    assert trade.trade_type == "paper"


def test_dict_to_trade_preserves_mfe_mae_state_v19_34_21():
    """R-multiple tracking must survive restart."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "MFE-1",
        "symbol": "FDX",
        "direction": "long",
        "status": "open",
        "setup_type": "scalp",
        "timeframe": "scalp",
        "quality_score": 70,
        "quality_grade": "B",
        "entry_price": 100.0,
        "current_price": 102.0,
        "stop_price": 98.0,
        "target_prices": [104.0],
        "shares": 100,
        "risk_amount": 200,
        "potential_reward": 400,
        "risk_reward_ratio": 2.0,
        "mfe_price": 103.5,
        "mfe_pct": 3.5,
        "mfe_r": 1.75,
        "mae_price": 99.2,
        "mae_pct": -0.8,
        "mae_r": -0.4,
        "total_commissions": 1.5,
        "net_pnl": 198.5,
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.mfe_price == 103.5
    assert trade.mfe_r == 1.75
    assert trade.mae_price == 99.2
    assert trade.total_commissions == 1.5
    assert trade.net_pnl == 198.5


def test_dict_to_trade_unknown_keys_ignored_v19_34_21():
    """Unknown fields in the persisted dict (e.g. `_id`, future
    fields) should be ignored, not crash deserialization."""
    from services.bot_persistence import BotPersistence
    persisted = {
        "id": "UNKNOWN-FIELDS-1",
        "symbol": "FDX",
        "direction": "long",
        "status": "open",
        "setup_type": "scalp",
        "timeframe": "intraday",
        "quality_score": 70,
        "quality_grade": "B",
        "entry_price": 100.0,
        "current_price": 100.0,
        "stop_price": 95.0,
        "target_prices": [110.0],
        "shares": 100,
        "risk_amount": 500,
        "potential_reward": 1000,
        "risk_reward_ratio": 2.0,
        "remaining_shares": 100,
        # Unknown / future keys — must be silently skipped:
        "_id": "abc123",
        "v19_99_99_brand_new_field": "future-value",
        "explanation": {"some": "nested"},  # Excluded by design.
    }
    trade = BotPersistence.dict_to_trade(persisted)
    assert trade is not None
    assert trade.remaining_shares == 100
    assert not hasattr(trade, "_id")
    assert not hasattr(trade, "v19_99_99_brand_new_field")


def test_dict_to_trade_handles_default_status_v19_34_21():
    """Required-field defaults still work for malformed docs."""
    from services.bot_persistence import BotPersistence
    minimal = {"id": "MIN", "symbol": "X"}
    trade = BotPersistence.dict_to_trade(minimal)
    assert trade is not None
    assert trade.id == "MIN"
    assert trade.symbol == "X"


def test_source_marks_v19_34_21_v19_34_21():
    """Static guard: the patch must remain in place."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "bot_persistence.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()
    assert "v19.34.21" in src, "v19.34.21 marker missing — patch reverted?"
    assert "_dc_fields(BotTrade)" in src, (
        "v19.34.21 dataclass-fields hydration missing — patch reverted?"
    )
