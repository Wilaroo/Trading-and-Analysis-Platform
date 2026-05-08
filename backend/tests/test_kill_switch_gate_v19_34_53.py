"""
test_kill_switch_gate_v19_34_53.py — pins the v19.34.53 hardening of
the kill-switch chokepoint detection.

Bug discovered 2026-05-08 mid-session: with kill switch tripped, the
`bracket_reissue_service` could not attach OCA stop+target legs to
6 IB positions because its orders carry trade_id of shape
`REISSUE-STOP-{tid}` / `REISSUE-TGT-{tid}` — which do NOT match the
v19.34.48 startswith() allow-list (`STOP-`, `TGT-`, …). Result: every
reissue-bracket call returned `ks-refused-*` order_ids → 6 positions
sat NAKED at IB until the operator temp-reset the kill switch to
re-attach. This is the precise opposite of what the chokepoint was
designed to do.

The v19.34.53 fix hardens the chokepoint with defense-in-depth:
  1. Explicit `intent` field — preferred
  2. `oca_group` non-empty → protective (every bracket leg has it)
  3. `order_type` ∈ {STP, STP_LMT, TRAIL, TRAIL_LMT} → never an entry
  4. `trade_id` substring scan for STOP/TGT/TARGET/OCA/REISSUE/ADOPT/
     CLOSE/PARTIAL/CANCEL → catches nested prefixes
  5. Legacy startswith() compat list → preserved

Plus the producer-side fix in `bracket_reissue_service` adds explicit
`intent: "protective"` to both stop and target leg payloads.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _patched_guard_active():
    """Patch safety_guardrails to behave as if kill switch is ON."""
    fake_state = MagicMock()
    fake_state.kill_switch_active = True
    fake_state.kill_switch_reason = "test trip"
    fake_guard = MagicMock()
    fake_guard.state = fake_state
    return patch(
        "services.safety_guardrails.get_safety_guardrails",
        return_value=fake_guard,
    )


def _patched_guard_inactive():
    fake_state = MagicMock()
    fake_state.kill_switch_active = False
    fake_state.kill_switch_reason = None
    fake_guard = MagicMock()
    fake_guard.state = fake_state
    return patch(
        "services.safety_guardrails.get_safety_guardrails",
        return_value=fake_guard,
    )


def _refused_id_from(result):
    """_kill_switch_gate returns the refusal id (str) or None."""
    return result if isinstance(result, str) else None


class TestKillSwitchGateHardening:
    # ── Regressions: existing behaviour must not break ───────────────

    def test_off_passes_everything(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_inactive():
            assert _kill_switch_gate({"trade_id": "abc", "intent": "entry"}) is None
            assert _kill_switch_gate({}) is None

    def test_explicit_intent_protective_allowed(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            for intent in ("close", "protective", "stop", "target", "cancel", "exit"):
                assert _kill_switch_gate({"intent": intent}) is None, \
                    f"intent={intent} should be allowed"

    def test_legacy_prefix_close_allowed(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            for prefix in ("CLOSE-", "PARTIAL-", "STOP-", "ADOPT-STOP-",
                           "ADOPT-TGT-", "TARGET-", "OCA-", "TGT-"):
                tid = f"{prefix}xyz123"
                assert _kill_switch_gate({"trade_id": tid}) is None, \
                    f"legacy prefix {prefix} should still pass"

    def test_pure_entry_still_refused(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "AAPL-entry-abc",
                "symbol": "AAPL",
                "action": "BUY",
                "quantity": 100,
                "order_type": "MKT",
                "intent": "entry",
            })
            assert isinstance(r, str)
            assert r.startswith("ks-refused-")

    def test_bare_uuid_trade_id_refused(self):
        """A regular trade_id with no recognizable keywords → entry."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "0cf1d40f",
                "symbol": "EBAY",
                "order_type": "MKT",
                "action": "BUY",
                "quantity": 1,
            })
            assert isinstance(r, str)
            assert r.startswith("ks-refused-")

    # ── v19.34.53 NEW: nested prefix patterns must pass ──────────────

    def test_reissue_stop_trade_id_passes(self):
        """The exact bug class — REISSUE-STOP-* used to be blocked."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "REISSUE-STOP-1a922c45",
                "symbol": "ADBE",
                "order_type": "STP",
                "action": "SELL",
                "quantity": 54,
                "stop_price": 241.65,
                "oca_group": "REISSUE-1a922c45-20260508T135305Z-1147c1",
            })
            assert r is None, f"REISSUE-STOP-* must pass but got {r}"

    def test_reissue_tgt_trade_id_passes(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "REISSUE-TGT-1a922c45",
                "symbol": "ADBE",
                "order_type": "LMT",
                "action": "SELL",
                "quantity": 54,
                "limit_price": 275.36,
                "oca_group": "REISSUE-1a922c45-20260508T135305Z-1147c1",
            })
            assert r is None

    # ── v19.34.53 NEW: structural shape detection ────────────────────

    def test_oca_group_set_alone_passes(self):
        """No keyword in trade_id, but oca_group set → bracket leg."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "some-future-bracket-format-xyz",
                "symbol": "AAPL",
                "order_type": "STP",
                "action": "SELL",
                "quantity": 10,
                "stop_price": 100.0,
                "oca_group": "some-oca-group-id",
            })
            assert r is None

    def test_stp_order_type_alone_passes(self):
        """No oca_group, no keyword in trade_id, but order_type=STP."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "manual-stop-xyz",
                "symbol": "GOOG",
                "order_type": "STP",
                "action": "SELL",
                "quantity": 10,
                "stop_price": 100.0,
            })
            assert r is None

    def test_stp_lmt_order_type_passes(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            for ot in ("STP_LMT", "STP LMT", "TRAIL", "TRAIL LMT", "TRAIL_LMT"):
                r = _kill_switch_gate({
                    "trade_id": "trail-xyz",
                    "symbol": "X",
                    "order_type": ot,
                    "action": "SELL",
                    "quantity": 1,
                })
                assert r is None, f"order_type={ot} should pass"

    # ── v19.34.53 NEW: substring scan in trade_id ────────────────────

    def test_trade_id_substring_keywords_pass(self):
        """Future producers using nested prefixes auto-allowed."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            for tid in (
                "BACKFILL-STOP-xyz",
                "MIGRATION-OCA-xyz",
                "v2-REISSUE-STOP-xyz",
                "auto-CLOSE-resync-xyz",
                "x-PARTIAL-y",
                "FLATTEN-emergency-xyz",
                "SOMETHING-TARGET-xyz",
                "x-CANCEL-y",
                "EXIT-trade-xyz",
            ):
                r = _kill_switch_gate({"trade_id": tid})
                assert r is None, f"substring keyword in {tid} should pass"

    # ── Negative: market entry with no protective hint must still fail ─

    def test_mkt_with_innocent_trade_id_still_refused(self):
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "scanner-pick-7c8d",
                "symbol": "TSLA",
                "order_type": "MKT",
                "action": "BUY",
                "quantity": 5,
            })
            assert isinstance(r, str)
            assert r.startswith("ks-refused-")

    def test_lmt_entry_without_oca_or_keywords_refused(self):
        """An entry LMT (no oca_group, no protective keyword) must
        still be blocked. LMT alone is NOT a protective signal."""
        from routers.ib import _kill_switch_gate
        with _patched_guard_active():
            r = _kill_switch_gate({
                "trade_id": "entry-1234",
                "symbol": "MSFT",
                "order_type": "LMT",
                "action": "BUY",
                "quantity": 100,
                "limit_price": 400.0,
            })
            assert isinstance(r, str), \
                "naked LMT entry without bracket signals must be refused"


class TestBracketReissueProducerTagsIntent:
    """v19.34.53 — producer side: bracket_reissue_service must tag both
    stop and target legs with explicit `intent: 'protective'`."""

    def test_reissue_stop_payload_has_intent(self):
        from services.bracket_reissue_service import submit_oca_pair
        captured = []

        def fake_queue(payload):
            captured.append(payload)
            return f"oid-{len(captured)}"

        plan = MagicMock()
        plan.symbol = "ADBE"
        plan.direction = "long"
        plan.remaining_shares = 54
        plan.new_stop_price = 241.65
        plan.target_price_levels = [275.36]
        plan.target_qtys = [54]
        plan.new_tif = "DAY"
        plan.new_outside_rth = False
        plan.oca_group = "REISSUE-1a922c45-test"
        plan.trade_id = "1a922c45"

        result = submit_oca_pair(plan=plan, queue_order_fn=fake_queue)
        assert result["success"] is True
        # Both legs captured
        assert len(captured) == 2
        for payload in captured:
            assert payload.get("intent") == "protective", \
                f"every reissue leg must carry intent=protective: {payload}"
            assert payload.get("oca_group") == "REISSUE-1a922c45-test"
