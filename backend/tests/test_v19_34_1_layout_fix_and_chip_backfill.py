"""
v19.34.1 (2026-05-04) — Tests for the layout fix + reconciled trade_type
backfill.

Operator pain-points addressed:
  1. Chart container stretched vertically as Unified Stream messages
     accumulated. Root cause: `overflow-y-auto` on the V5 root + a
     `min-h-[1120px]` (no upper bound, no shrink) on the main-row.
     Fix: clamp root to viewport with `overflow-hidden`; switch the
     main-row to `flex-1 min-h-0` so it grows to remaining viewport
     height and no further. Inner panels scroll internally.

  2. Reconciled-from-IB-orphan rows had no PAPER/LIVE chip in Open
     Positions. Root cause: position_reconciler created bot_trades
     without stamping `trade_type` (orphans don't carry account
     context per-fill). Plus pre-existing legacy bot_trades had no
     stamp.
     Fix:
       - Stamp `trade_type` + `account_id_at_fill` on new reconciled
         rows from the current pusher account (via account_guard).
       - In sentcom_service.get_our_positions, fall back to the same
         current-pusher-account classification for any row whose
         stamp is missing or "unknown" — presentational only, no DB
         rewrite.
       - Render the chip on Open Positions even when type is
         "unknown" (drop `hideUnknown`) so every row has a mode tag.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Layout fix structural assertions ──────────────────────────────


def test_v5_root_uses_overflow_hidden_not_auto():
    """The V5 root must be `overflow-hidden`, not `overflow-y-auto`,
    so accumulating Unified Stream messages can't drag the chart
    container taller via outer-page scroll."""
    f = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text()
    # Locate the className attribute on the root element by data-testid.
    root_idx = f.index('data-testid="sentcom-v5-root"')
    # Walk forward to find `className="..."` after this attribute.
    cls_start = f.index('className="', root_idx)
    cls_end = f.index('"', cls_start + len('className="'))
    cls_val = f[cls_start + len('className="'): cls_end]
    assert "overflow-hidden" in cls_val
    assert "overflow-y-auto" not in cls_val


def test_main_row_uses_flex1_min_h_0_not_min_h_1120():
    """The main-row must use `flex-1 min-h-0` so it claims remaining
    viewport height (and no more), instead of `flex-shrink-0 min-h-[1120px]`
    which let the row grow with content."""
    f = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text()
    main_idx = f.index('data-testid="sentcom-v5-main-row"')
    cls_start = f.index('className="', main_idx)
    cls_end = f.index('"', cls_start + len('className="'))
    cls_val = f[cls_start + len('className="'): cls_end]
    assert "flex-1" in cls_val and "min-h-0" in cls_val
    assert "min-h-[1120px]" not in cls_val
    assert "flex-shrink-0" not in cls_val


def test_grid_uses_flex1_min_h_0_not_min_h_800():
    """The chart+sidebar grid must use `flex-1 min-h-0` so it claims
    remaining column height (no more), instead of `flex-shrink-0
    min-h-[800px]`."""
    f = Path("/app/frontend/src/components/sentcom/SentComV5View.jsx").read_text()
    grid_idx = f.index('data-testid="sentcom-v5-grid"')
    cls_start = f.index('className="', grid_idx)
    cls_end = f.index('"', cls_start + len('className="'))
    cls_val = f[cls_start + len('className="'): cls_end]
    assert "flex-1" in cls_val and "min-h-0" in cls_val
    assert "min-h-[800px]" not in cls_val
    assert "flex-shrink-0" not in cls_val


# ─── Reconciler stamps trade_type from current pusher account ──────


def test_reconciler_imports_classify_account_id():
    """position_reconciler must import `classify_account_id` and
    `get_account_snapshot` so it can stamp trade_type on new
    reconciled rows."""
    src = (BACKEND_DIR / "services" / "position_reconciler.py").read_text()
    assert "classify_account_id" in src
    assert "get_account_snapshot" in src
    # Stamps must land on the new BotTrade.
    assert "trade.trade_type" in src
    assert "trade.account_id_at_fill" in src


# ─── sentcom_service legacy fallback ───────────────────────────────


def test_sentcom_service_has_legacy_account_fallback():
    """get_our_positions must compute a `_legacy_trade_type` from the
    current pusher account at function start so BOTH the bot-managed
    branch AND the IB-orphan branch can fall back to it."""
    src = (BACKEND_DIR / "services" / "sentcom_service.py").read_text()
    assert "_legacy_trade_type" in src
    assert "_legacy_account_id" in src
    # Used in BOTH branches (count >= 4: defined twice + used twice
    # in the row payloads).
    assert src.count("_legacy_trade_type") >= 4
    # Bot branch
    assert 'trade.get("trade_type") and trade.get("trade_type") != "unknown"' in src
    # Orphan branch
    assert "(enrich_trade or {}).get(\"trade_type\")" in src


# ─── Frontend chip renders when type is unknown ────────────────────


def test_open_positions_chip_no_longer_hides_unknown():
    """OpenPositionsV5 must render the TradeTypeChip even when the
    type is 'unknown' so reconciled-orphan rows still get a mode tag.
    Pusher-account fallback in sentcom_service should normally fill
    this in with paper/live."""
    f = Path("/app/frontend/src/components/sentcom/v5/OpenPositionsV5.jsx").read_text()
    # The OPEN-POSITIONS chip block uses testIdSuffix=`open-pos-...`
    # (backtick template literal). Locate that block by the chip's
    # marker comment.
    marker = 'v19.34.1 — render even when type is'
    assert marker in f, "v19.34.1 chip-render comment must be present"
    chip_block_idx = f.index(marker)
    # 600 chars after the marker should cover the whole <TradeTypeChip>
    # element. Check that hideUnknown is NOT in that range.
    chip_block = f[chip_block_idx: chip_block_idx + 600]
    assert "hideUnknown" not in chip_block


# ─── routers/sentcom closed_today legacy fallback ─────────────────


def test_closed_today_has_legacy_account_fallback():
    src = (BACKEND_DIR / "routers" / "sentcom.py").read_text()
    assert "_legacy_trade_type" in src
    assert "_legacy_account_id" in src
    # Row builder uses the fallback.
    assert "row_trade_type" in src
