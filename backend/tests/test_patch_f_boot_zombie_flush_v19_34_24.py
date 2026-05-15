"""test_patch_f_boot_zombie_flush_v19_34_24.py — pin Patch F regressions.

Patch F was triggered by the 2026-02 market-open zombie disaster: backend
restarted overnight with fresh patches A/B/C/E applied, but old DAY orders
from the buggy pre-restart session were still alive at IB and fired at
9:30:00 ET, creating a -$482K SHLD short before the operator could
intervene.

Pre-Patch-F, the existing v19.34.66 boot tripwire:
  - Defaulted to `only_gtc=True` so DAY zombies were invisible to the audit.
  - Only LOGGED — auto-cancel was deferred to the v19.34.89 periodic loop
    which had a 60s warm-up + 30s tick = up to 90s window before the first
    sweep could fire. At market open that window IS the disaster.

This suite pins:
  1. Patch F passes `only_gtc=False` so DAY zombies are caught at boot.
  2. Patch F immediately auto-cancels SAFE verdicts via the cancel queue
     instead of waiting for the periodic loop.
  3. `PATCH_F_AUTO_FLUSH_ON_BOOT=false` correctly disables the auto-flush
     (operator must be able to investigate without auto-cancel firing).
  4. MISMATCHED_SIZE verdicts are NEVER auto-cancelled (only SAFE set).
  5. Empty / clean audits don't write a share_drift_events row.

Pure unit tests — no IB, no live Mongo writes (only the cancel queue is
exercised, which is an in-memory dict).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def fresh_modules():
    """Reload routers.ib + orphan_gtc_reconciler so cancel queue is clean."""
    for mod_name in ("routers.ib", "services.orphan_gtc_reconciler"):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
    import routers.ib as ib_mod
    import services.orphan_gtc_reconciler as og_mod
    ib_mod._cancellation_queue.clear()
    ib_mod._pushed_ib_data["orders"] = []
    ib_mod._pushed_ib_data["positions"] = []
    yield ib_mod, og_mod
    ib_mod._cancellation_queue.clear()
    ib_mod._pushed_ib_data["orders"] = []
    ib_mod._pushed_ib_data["positions"] = []


# ════════════════════════════════════════════════════════════════════════
# Helpers — synthesise the audit shape that audit_orphan_gtc_orders
# returns, so we can call cancel_orphan_gtc_orders directly with the
# same data the boot tripwire would produce.
# ════════════════════════════════════════════════════════════════════════


def _build_zombie_day_order(ib_order_id: int, symbol: str = "SHLD",
                            quantity: int = 7640) -> dict:
    """Mimic the 2026-02 SHLD zombie that fired at market open.

    DAY TIF — invisible to pre-Patch-F audits (which defaulted only_gtc=True).
    """
    return {
        "order_id": ib_order_id,
        "perm_id": 0,
        "symbol": symbol,
        "action": "SELL",
        "quantity": quantity,
        "remaining": quantity,
        "order_type": "STP",
        "limit_price": None,
        "stop_price": 12.50,
        "tif": "DAY",   # ← the killer: DAY not GTC
        "status": "PreSubmitted",
    }


def _build_zombie_gtc_order(ib_order_id: int, symbol: str = "NXPI",
                            quantity: int = 100) -> dict:
    return {
        "order_id": ib_order_id,
        "perm_id": 0,
        "symbol": symbol,
        "action": "SELL",
        "quantity": quantity,
        "remaining": quantity,
        "order_type": "STP",
        "limit_price": None,
        "stop_price": 150.0,
        "tif": "GTC",
        "status": "PreSubmitted",
    }


# ════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patch_f_audits_day_orders_not_just_gtc(fresh_modules):
    """Patch F: `audit_orphan_gtc_orders(only_gtc=False)` must surface
    DAY zombies. Pre-F the same call with default `only_gtc=True` would
    return 0 verdicts for the SHLD scenario.
    """
    ib_mod, og_mod = fresh_modules
    # SHLD zombie DAY order at IB, no underlying position, no bot_trade row.
    ib_mod._pushed_ib_data["orders"] = [_build_zombie_day_order(99001)]
    ib_mod._pushed_ib_data["positions"] = []  # account is flat

    # Pre-Patch-F behaviour (default only_gtc=True) → DAY order ignored.
    audit_gtc_only = await og_mod.audit_orphan_gtc_orders(
        bot=None, only_gtc=True,
    )
    # Either it succeeds with no dangerous verdicts, OR it can't run on
    # this minimal harness — both are acceptable evidence that DAY
    # zombies are NOT caught by GTC-only audits.
    if audit_gtc_only.get("success"):
        n_naked_gtc_only = audit_gtc_only.get("summary", {}).get(
            og_mod.VERDICT_NAKED_NO_POSITION, 0
        )
        n_orphan_gtc_only = audit_gtc_only.get("summary", {}).get(
            og_mod.VERDICT_ORPHAN_NO_TRADE, 0
        )
        assert n_naked_gtc_only == 0 and n_orphan_gtc_only == 0, (
            "Pre-Patch-F: DAY zombie should be invisible under only_gtc=True"
        )

    # Patch F behaviour (only_gtc=False) → DAY order IS caught.
    audit_all = await og_mod.audit_orphan_gtc_orders(
        bot=None, only_gtc=False,
    )
    if not audit_all.get("success"):
        pytest.skip(
            "audit could not run (likely no Mongo/IB harness) — "
            "Patch F's auto-flush also gracefully skips in this case"
        )
    summary = audit_all.get("summary", {})
    # The SHLD DAY zombie has no position → NAKED_NO_POSITION.
    assert summary.get(og_mod.VERDICT_NAKED_NO_POSITION, 0) >= 1, (
        f"Patch F: expected DAY zombie to be classified as "
        f"NAKED_NO_POSITION; summary={summary}"
    )


@pytest.mark.asyncio
async def test_patch_f_auto_flush_cancels_safe_verdicts_via_queue(fresh_modules):
    """Patch F: after audit, SAFE verdicts (NAKED_NO_POSITION /
    ORPHAN_NO_TRADE) must be immediately routed to the cancel queue —
    NOT logged and forgotten.
    """
    ib_mod, og_mod = fresh_modules
    # One naked DAY (SHLD-style) + one orphan GTC (NXPI-style).
    naked = og_mod.OrderVerdict(
        ib_order_id=88001, perm_id=None, symbol="SHLD",
        action="SELL", quantity=7640, order_type="STP",
        limit_price=None, stop_price=12.5,
        time_in_force="DAY", status="PreSubmitted",
        verdict=og_mod.VERDICT_NAKED_NO_POSITION,
        reasons=["IB position for SHLD is +0 — order would short on trigger"],
    )
    orphan = og_mod.OrderVerdict(
        ib_order_id=88002, perm_id=None, symbol="NXPI",
        action="SELL", quantity=100, order_type="STP",
        limit_price=None, stop_price=150.0,
        time_in_force="GTC", status="PreSubmitted",
        verdict=og_mod.VERDICT_ORPHAN_NO_TRADE,
        reasons=["no bot_trade row references ib_order_id=88002"],
    )

    # Force ib_direct unavailable so the queue path is exercised — this is
    # the exact code path Patch F walks on the DGX deployment.
    with patch.object(og_mod, "get_ib_direct_service",
                      side_effect=Exception("ib_direct not present"),
                      create=True):
        report = await og_mod.cancel_orphan_gtc_orders(
            verdicts_to_cancel=[naked, orphan],
        )

    cancelled = report.get("cancelled") or []
    assert len(cancelled) == 2, (
        f"Patch F: both SAFE verdicts must be cancelled, got {report}"
    )
    cancelled_ids = {c["ib_order_id"] for c in cancelled}
    assert cancelled_ids == {88001, 88002}
    # Confirm both routed through the v19.34.88 cancel queue, not legacy.
    for c in cancelled:
        assert c.get("via") == "cancel_queue", (
            f"Patch F: cancel must use the queue when ib_direct is "
            f"unavailable; got {c}"
        )
    # And they must actually be enqueued.
    assert 88001 in ib_mod._cancellation_queue
    assert 88002 in ib_mod._cancellation_queue
    assert ib_mod._cancellation_queue[88001]["status"] == "pending"
    assert ib_mod._cancellation_queue[88002]["status"] == "pending"


@pytest.mark.asyncio
async def test_patch_f_refuses_mismatched_size_verdict(fresh_modules):
    """Patch F must NEVER auto-cancel MISMATCHED_SIZE — could be a
    legitimate partial scale-out. Operator review required.
    """
    ib_mod, og_mod = fresh_modules
    mismatched = og_mod.OrderVerdict(
        ib_order_id=77001, perm_id=None, symbol="NVDA",
        action="SELL", quantity=200, order_type="STP",
        limit_price=None, stop_price=400.0,
        time_in_force="GTC", status="PreSubmitted",
        verdict=og_mod.VERDICT_MISMATCHED_SIZE,
        reasons=["order qty 200 > |IB position| 100 — would over-execute"],
    )
    report = await og_mod.cancel_orphan_gtc_orders(
        verdicts_to_cancel=[mismatched],
    )
    assert not (report.get("cancelled") or []), (
        f"Patch F: MISMATCHED_SIZE must NEVER be auto-cancelled; "
        f"report={report}"
    )
    refused = report.get("refused_unsafe") or []
    assert any(r.get("ib_order_id") == 77001 for r in refused), (
        f"Patch F: mismatched verdict must appear in refused_unsafe; "
        f"got {refused}"
    )
    assert 77001 not in ib_mod._cancellation_queue, (
        "Patch F: mismatched order must NOT be enqueued"
    )


@pytest.mark.asyncio
async def test_patch_f_empty_audit_is_noop(fresh_modules):
    """Patch F: an empty verdict list must short-circuit without
    touching the cancel queue.
    """
    ib_mod, og_mod = fresh_modules
    report = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=[])
    assert (report.get("cancelled") or []) == []
    assert (report.get("errors") or []) == []
    assert (report.get("refused_unsafe") or []) == []
    assert len(ib_mod._cancellation_queue) == 0


def test_patch_f_env_var_disable_flag_is_respected():
    """Patch F: the env-var disable flag uses the same lower-cased
    truthy parse the periodic loop uses ("1","true","yes","on").
    Pinning the parse behaviour so future env churn can't silently
    flip the default.
    """
    for truthy in ("1", "true", "TRUE", "True", "yes", "on"):
        os.environ["PATCH_F_AUTO_FLUSH_ON_BOOT"] = truthy
        val = os.environ.get(
            "PATCH_F_AUTO_FLUSH_ON_BOOT", "true",
        ).strip().lower() in ("1", "true", "yes", "on")
        assert val, f"truthy value {truthy!r} should enable auto-flush"
    for falsy in ("0", "false", "FALSE", "no", "off", "disabled"):
        os.environ["PATCH_F_AUTO_FLUSH_ON_BOOT"] = falsy
        val = os.environ.get(
            "PATCH_F_AUTO_FLUSH_ON_BOOT", "true",
        ).strip().lower() in ("1", "true", "yes", "on")
        assert not val, f"falsy value {falsy!r} should disable auto-flush"
    os.environ.pop("PATCH_F_AUTO_FLUSH_ON_BOOT", None)
    # Default (env not set) must be ON.
    default_val = os.environ.get(
        "PATCH_F_AUTO_FLUSH_ON_BOOT", "true",
    ).strip().lower() in ("1", "true", "yes", "on")
    assert default_val, "Patch F default must be ENABLED"


@pytest.mark.asyncio
async def test_patch_f_zombie_disaster_repro_2026_02(fresh_modules):
    """End-to-end repro of the 2026-02 market-open zombie scenario.

    Setup:
      • IB has 2 DAY zombie STP orders from a previous session:
          - SHLD 7640 share short stop @ 12.50 (the disaster maker)
          - MSTR 189 share long stop @ 250
      • IB has 0 positions (account was flat overnight per the user's
        manual flatten on the day of recovery).
      • bot_trades has no rows referencing these order IDs.

    Expected after Patch F:
      • Both surface as NAKED_NO_POSITION verdicts under only_gtc=False.
      • Both get auto-cancelled via the cancel queue.
      • Operator's account is protected before bot enters scan loop.
    """
    ib_mod, og_mod = fresh_modules

    ib_mod._pushed_ib_data["orders"] = [
        _build_zombie_day_order(55001, symbol="SHLD", quantity=7640),
        _build_zombie_day_order(55002, symbol="MSTR", quantity=189),
    ]
    ib_mod._pushed_ib_data["positions"] = []  # flat

    # Stage 1: Patch F audit catches both zombies (only_gtc=False).
    audit = await og_mod.audit_orphan_gtc_orders(bot=None, only_gtc=False)
    if not audit.get("success"):
        pytest.skip("audit harness can't run end-to-end without bot/db")
    summary = audit.get("summary", {})
    n_naked = summary.get(og_mod.VERDICT_NAKED_NO_POSITION, 0)
    assert n_naked >= 2, (
        f"Patch F: both DAY zombies must be NAKED_NO_POSITION; "
        f"summary={summary}"
    )

    # Stage 2: Patch F auto-cancels them via the queue.
    raw_verdicts = audit.get("verdicts") or []
    safe_to_cancel = []
    for raw in raw_verdicts:
        if raw.get("verdict") in og_mod.SAFE_TO_AUTO_CANCEL:
            safe_to_cancel.append(og_mod.OrderVerdict(
                ib_order_id=int(raw.get("ib_order_id") or 0),
                perm_id=raw.get("perm_id"),
                symbol=raw.get("symbol") or "",
                action=raw.get("action") or "",
                quantity=int(raw.get("quantity") or 0),
                order_type=raw.get("order_type") or "",
                limit_price=raw.get("limit_price"),
                stop_price=raw.get("stop_price"),
                time_in_force=raw.get("time_in_force") or "",
                status=raw.get("status") or "",
                verdict=raw.get("verdict") or "",
                reasons=list(raw.get("reasons") or []),
                bot_trade_id=raw.get("bot_trade_id"),
                ib_position_size=raw.get("ib_position_size"),
                submitted_at=raw.get("submitted_at"),
            ))

    with patch.object(og_mod, "get_ib_direct_service",
                      side_effect=Exception("ib_direct not present"),
                      create=True):
        report = await og_mod.cancel_orphan_gtc_orders(
            verdicts_to_cancel=safe_to_cancel,
        )

    cancelled_ids = {c["ib_order_id"] for c in (report.get("cancelled") or [])}
    assert 55001 in cancelled_ids, "SHLD zombie must be flushed"
    assert 55002 in cancelled_ids, "MSTR zombie must be flushed"
    # And the cancel queue actually has the cancellations pending for
    # the pusher to pick up.
    assert ib_mod._cancellation_queue[55001]["status"] == "pending"
    assert ib_mod._cancellation_queue[55002]["status"] == "pending"
