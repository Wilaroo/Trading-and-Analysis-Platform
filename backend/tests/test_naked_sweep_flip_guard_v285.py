"""
test_naked_sweep_flip_guard_v285.py — guards the CRM overnight-naked-flip fix.

The naked-sweep reissues a protective EXIT bracket (SELL for a long / BUY for a
short). The v235 magnitude clamp is direction-BLIND, so an overnight desync where
IB is flat/opposite must HALT the reissue (else the exit flips the position naked).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.trading_bot_service import _naked_sweep_flip_decision as decide  # noqa: E402


class TestFlipGuardHalts:
    def test_long_but_ib_flat_halts(self):
        # bot thinks long 100, IB holds 0 → SELL would create naked short
        assert decide("long", 100, 0, True) == "halt_flat_or_opposite"

    def test_long_but_ib_short_halts(self):
        # bot thinks long 100, IB actually short 100 (flipped overnight)
        assert decide("long", 100, -100, True) == "halt_flat_or_opposite"

    def test_short_but_ib_flat_halts(self):
        assert decide("short", 50, 0, True) == "halt_flat_or_opposite"

    def test_short_but_ib_long_halts(self):
        assert decide("short", 50, 80, True) == "halt_flat_or_opposite"

    def test_symbol_absent_from_snapshot_halts(self):
        # present snapshot but symbol missing → ib_signed=None → flat → halt
        assert decide("long", 100, None, True) == "halt_flat_or_opposite"


class TestFlipGuardProceeds:
    def test_long_ib_long_full_proceeds(self):
        assert decide("long", 100, 100, True) == "proceed"

    def test_long_ib_long_more_proceeds(self):
        assert decide("long", 100, 250, True) == "proceed"

    def test_long_ib_long_partial_proceeds(self):
        # 0 < held < rs → proceed; v235 magnitude clamp shrinks the order
        assert decide("long", 100, 60, True) == "proceed"

    def test_short_ib_short_proceeds(self):
        assert decide("short", 50, -50, True) == "proceed"

    def test_short_ib_short_partial_proceeds(self):
        assert decide("short", 50, -20, True) == "proceed"


class TestFlipGuardUnverifiable:
    def test_positions_unavailable_skips(self):
        assert decide("long", 100, None, False) == "skip_unverifiable"

    def test_positions_unavailable_skips_even_with_qty(self):
        # availability flag wins regardless of any stale qty
        assert decide("short", 50, -50, False) == "skip_unverifiable"
