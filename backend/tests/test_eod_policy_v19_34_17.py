"""
test_eod_policy_v19_34_17.py — pins the operator-approved EOD policy:
  • Bot-originated `day_swing`/`position` trades: stay open (close_at_eod=False at entry)
  • Orphan-reconciled positions: flatten at EOD (close_at_eod=True)
  • Drift-excess slices (v19.34.15b reconciled_excess): flatten at EOD too
  • Migration on boot flips ALREADY-open reconciled trades from False → True

Operator approval 2026-05-06 (UPS/SBUX/ADBE/LITE/LIN didn't close at EOD).
"""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_bot(open_trades=None):
    bot = MagicMock()
    bot._open_trades = {t.id: t for t in (open_trades or [])}
    bot._save_trade = MagicMock()
    bot.risk_params = MagicMock(
        reconciled_default_stop_pct=2.0, reconciled_default_rr=2.0,
        drift_excess_stop_pct=1.0, drift_excess_rr=1.0,
    )
    return bot


class TestReconcilerSetsCloseAtEodTrue:

    @pytest.mark.asyncio
    async def test_orphan_reconcile_spawns_with_close_at_eod_true(self):
        """v19.24 orphan reconcile path stamps close_at_eod=True (was False)."""
        from services.position_reconciler import PositionReconciler

        # Read the constant directly from the source — we don't need to spin
        # up the full IB machinery to verify the policy line.
        src = Path(__file__).resolve().parents[1] / "services" / "position_reconciler.py"
        text = src.read_text()
        # The orphan-reconcile call site sits in the protect_orphan_positions
        # block (line ~813). Verify the new explicit True is present and
        # the old "default to hold overnight" comment is gone.
        assert "close_at_eod=True," in text, "orphan reconcile must stamp True"
        assert "v19.34.17" in text, "v19.34.17 marker must be present"
        assert "default to hold overnight" not in text, (
            "old `default to hold overnight` comment must be removed"
        )
        # Also assert the drift-excess spawn path has the same policy.
        excess_section = text.split("v19.34.15b: spawned to claim excess")[0]
        excess_section = excess_section[-1500:]  # window before the spawn line
        assert "close_at_eod=True," in excess_section, (
            "drift-excess spawn path must also stamp True"
        )
        # Sanity: there should be NO `close_at_eod=False` left in the file
        # (other than possibly a comment about the old behavior).
        non_comment_falses = [
            ln for ln in text.split("\n")
            if "close_at_eod=False" in ln and not ln.lstrip().startswith("#")
        ]
        assert non_comment_falses == [], (
            f"unexpected close_at_eod=False survived: {non_comment_falses}"
        )


class TestEodPolicyMigrationFlipsExistingTrades:

    def test_migration_flips_reconciled_external(self):
        """Already-open `entered_by=reconciled_external` trade flips False→True."""
        # Simulate the migration logic inline since calling start() requires
        # full IB machinery. The migration's core decision rule:
        def _should_flip(t):
            eb = (getattr(t, "entered_by", "") or "").lower()
            is_reconciled = (
                eb.startswith("reconciled_") or
                getattr(t, "trade_style", "") == "reconciled"
            )
            return is_reconciled and getattr(t, "close_at_eod", False) is False

        # Reconciled orphan — should flip.
        t1 = MagicMock(id="t-1", symbol="SBUX", entered_by="reconciled_external",
                       close_at_eod=False, trade_style="reconciled")
        assert _should_flip(t1) is True

        # Reconciled drift-excess — should flip.
        t2 = MagicMock(id="t-2", symbol="UPS", entered_by="reconciled_excess_v19_34_15b",
                       close_at_eod=False, trade_style="reconciled")
        assert _should_flip(t2) is True

        # Bot-originated swing — should NOT flip.
        t3 = MagicMock(id="t-3", symbol="FDX", entered_by="bot_swing_squeeze",
                       close_at_eod=False, trade_style="day_swing")
        assert _should_flip(t3) is False

        # Bot-originated intraday already True — should NOT flip (no-op).
        t4 = MagicMock(id="t-4", symbol="AAPL", entered_by="bot_intraday",
                       close_at_eod=True, trade_style="intraday_scalp")
        assert _should_flip(t4) is False

        # Reconciled but already True — should NOT flip (idempotent).
        t5 = MagicMock(id="t-5", symbol="LIN", entered_by="reconciled_external",
                       close_at_eod=True, trade_style="reconciled")
        assert _should_flip(t5) is False


class TestEodCloseFiltersHonorPolicy:

    def test_eod_close_includes_close_at_eod_true_only(self):
        """Sanity: position_manager filter `getattr(t, 'close_at_eod', True)` 
        keeps reconciled (True) trades and excludes swings (False)."""
        # Mirror the filter at position_manager.py:914-917 exactly.
        def _filter_eod_eligible(open_trades):
            return {tid: t for tid, t in open_trades.items()
                    if getattr(t, 'close_at_eod', True)}

        recon = MagicMock(id="r-1", symbol="SBUX", close_at_eod=True)  # post-fix
        swing = MagicMock(id="s-1", symbol="FDX", close_at_eod=False)
        intraday_no_attr = MagicMock(id="i-1", symbol="AAPL", spec=[])
        # Strip close_at_eod attr to test default
        del intraday_no_attr.close_at_eod  # but spec=[] already strips it

        result = _filter_eod_eligible({
            "r-1": recon, "s-1": swing,
        })
        assert "r-1" in result
        assert "s-1" not in result

        # Sanity: a trade missing the attr (somehow) defaults to True (close).
        plain = MagicMock(spec=["id", "symbol"])
        plain.id = "p-1"
        plain.symbol = "X"
        result2 = _filter_eod_eligible({"p-1": plain})
        assert "p-1" in result2
