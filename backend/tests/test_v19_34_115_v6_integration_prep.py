"""
Tests for v19.34.115 — V6 integration prep.

Promotes v111's `_bracket_attach_cooldown_skips` int counter to a
recent-skips deque on `PositionReconciler`, exposed via the public
`get_attach_cooldown_skips()` method. The V6 Safety Activity Stream
spec (`/app/memory/V6_SAFETY_ACTIVITY_STREAM_SPEC.md §10`) depends
on this surface to render per-event detail rows.

This is integration plumbing — the LOC change is small but the
contract matters for the future V6 panel work.

Also locks the integration index file existence so a future agent
doesn't accidentally orphan the V6 integration plan.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class TestBracketAttachCooldownDeque:
    """The deque + helper that the V6 Safety Activity Stream
    aggregator will read."""

    def setup_method(self):
        from services.position_reconciler import PositionReconciler
        self.r = PositionReconciler(db=MagicMock())

    def test_deque_initialized_empty(self):
        assert hasattr(self.r, "_bracket_attach_recent_skips")
        assert list(self.r._bracket_attach_recent_skips) == []
        # Public read returns empty list.
        assert self.r.get_attach_cooldown_skips() == []

    def test_record_appends_to_deque_and_bumps_counter(self):
        """Single record call MUST: (1) append a structured entry to
        the deque, (2) increment the legacy int counter. Both are
        production-readable; the V6 panel reads the deque, legacy
        consumers (test cases, diagnostic logs) read the counter."""
        baseline_int = self.r._bracket_attach_cooldown_skips
        self.r._record_bracket_attach_skip("tr-A", 12.3, symbol="SBUX")
        assert self.r._bracket_attach_cooldown_skips == baseline_int + 1
        skips = self.r.get_attach_cooldown_skips()
        assert len(skips) == 1
        evt = skips[0]
        assert evt["trade_id"] == "tr-A"
        assert evt["symbol"] == "SBUX"
        assert evt["cooldown_remaining_s"] == 12.3
        # Cooldown window default = 60s (or env override; doesn't
        # matter here — must be a float and match the configured
        # window).
        assert isinstance(evt["cooldown_window_s"], float)
        assert evt["cooldown_window_s"] > 0
        assert "ts" in evt and isinstance(evt["ts"], str)

    def test_deque_capped_at_200_entries(self):
        """The deque is bounded so a long-running reconciler can't
        leak memory. v115 default = 200 (matches drift-guard ledger)."""
        for i in range(300):
            self.r._record_bracket_attach_skip(f"tr-{i}", 1.0, symbol="X")
        # All 300 increments hit the int counter
        assert self.r._bracket_attach_cooldown_skips >= 300
        # But the deque is capped at 200 most-recent
        snapshot = self.r.get_attach_cooldown_skips()
        assert len(snapshot) == 200
        # And it's the RECENT 200, not the first 200
        assert snapshot[-1]["trade_id"] == "tr-299"
        assert snapshot[0]["trade_id"] == "tr-100"

    def test_public_read_returns_copy_not_live_deque(self):
        """A panel consumer MUST NOT be able to mutate the
        reconciler's internal state by mutating the returned list."""
        self.r._record_bracket_attach_skip("tr-A", 5.0)
        snap = self.r.get_attach_cooldown_skips()
        snap.clear()
        # Internal deque is untouched.
        assert len(self.r.get_attach_cooldown_skips()) == 1

    def test_falsy_trade_id_record_is_safe(self):
        """Defensive: even though production paths only call
        `_record_bracket_attach_skip` when there's a real
        cooldown-remaining (which implies a real trade_id), a
        misconfigured call site must not crash the reconciler."""
        # No raise.
        self.r._record_bracket_attach_skip("", 5.0)
        self.r._record_bracket_attach_skip(None, 5.0)
        # Both still recorded (counter bumps, deque gets the entry)
        assert self.r._bracket_attach_cooldown_skips >= 2


class TestProductionCallsitesUseRecordHelper:
    """Source-level: all three production cooldown-skip call sites
    MUST use `_record_bracket_attach_skip` rather than directly
    bumping the legacy counter. Without this, the V6 Safety
    Activity Stream feed will be empty even though the counter ticks."""

    @pytest.fixture
    def reconciler_src(self):
        return (BACKEND_DIR / "services" / "position_reconciler.py").read_text()

    def test_no_direct_counter_bumps_remain_in_production_paths(self, reconciler_src):
        """Any `_bracket_attach_cooldown_skips += 1` outside the
        `_record_bracket_attach_skip` helper means a call site is
        leaking past the deque. We expect to see exactly one direct
        write — inside the helper itself."""
        bump_count = reconciler_src.count("self._bracket_attach_cooldown_skips += 1")
        assert bump_count == 1, (
            f"Expected ONE direct counter bump (inside "
            f"_record_bracket_attach_skip); found {bump_count}. "
            f"Production call sites must call the helper so the V6 "
            f"panel feed stays in sync with the counter."
        )

    def test_three_calls_to_record_helper(self, reconciler_src):
        """One per cooldown-detect site: orphan-adoption,
        grow-existing-excess-slice, spawn-excess-slice."""
        call_count = reconciler_src.count("self._record_bracket_attach_skip(trade.id")
        assert call_count == 3, (
            f"Expected 3 _record_bracket_attach_skip(trade.id, ...) "
            f"call sites; found {call_count}. A missing call site = "
            f"a silent cooldown skip that the V6 panel will never see."
        )


class TestV6IntegrationDocs:
    """Cross-doc: a future agent must not orphan the V6 integration
    spec when shipping V6 phase work. Lock the index + spec append
    sections at the source level."""

    def test_integration_index_exists(self):
        idx_path = APP_DIR / "memory" / "V6_INTEGRATION_v110_v114.md"
        assert idx_path.exists(), (
            "V6_INTEGRATION_v110_v114.md missing — the V6 panel "
            "extraction work depends on the integration contracts "
            "in that file. Do not remove without replacing."
        )
        text = idx_path.read_text()
        # Every version must have a section
        for version in ("v110", "v111", "v112", "v113", "v114"):
            assert f"## {version}" in text, f"Section for {version} missing from integration index"

    def test_locked_spec_has_integration_section(self):
        spec_path = APP_DIR / "memory" / "V6_NEXT_LOCKED_SPEC.md"
        text = spec_path.read_text()
        assert "v110–v114 Integration" in text, (
            "V6_NEXT_LOCKED_SPEC.md is missing the integration "
            "cross-reference section. Plan A migration must consume "
            "the integration contract."
        )

    def test_position_health_spec_has_v112_v113_sections(self):
        spec_path = APP_DIR / "memory" / "V6_POSITION_HEALTH_CONSOLE_SPEC.md"
        text = spec_path.read_text()
        assert "STOP-WIDE-FOR-STYLE" in text, "v112 row-state contract missing from spec"
        assert "GRADE column" in text, "v113 grade column contract missing from spec"

    def test_safety_stream_spec_has_v111_section(self):
        spec_path = APP_DIR / "memory" / "V6_SAFETY_ACTIVITY_STREAM_SPEC.md"
        text = spec_path.read_text()
        assert "bracket_attach_cooldown" in text, (
            "v111 cooldown event-kind contract missing from spec"
        )
        assert "get_attach_cooldown_skips" in text, (
            "The aggregator's source method must be referenced in "
            "the spec — otherwise the V6 panel implementer won't "
            "know which API to call."
        )


class TestV111LegacyTestsStillPass:
    """Sanity check: the v111 cooldown tests still pass with the
    deque + helper plumbing in place. (Already covered by the
    cumulative regression — this is an explicit assertion that the
    v115 change is backward-compatible.)"""

    def test_v111_skip_counter_still_works(self):
        from services.position_reconciler import PositionReconciler
        r = PositionReconciler(db=MagicMock())
        r._stamp_bracket_attach("TR-COUNT-001")
        baseline = r._bracket_attach_cooldown_skips
        # Simulate three attach attempts hitting cooldown via the
        # production helper.
        for _ in range(3):
            cd = r._bracket_attach_in_cooldown("TR-COUNT-001")
            if cd is not None:
                r._record_bracket_attach_skip("TR-COUNT-001", cd, symbol="X")
        assert r._bracket_attach_cooldown_skips == baseline + 3
        assert len(r.get_attach_cooldown_skips()) == 3
