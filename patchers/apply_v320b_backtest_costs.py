#!/usr/bin/env python3
"""
apply_v320b_backtest_costs.py — Tier 1b: execution-cost modeling in the backtest
=================================================================================

WHAT THIS DOES (v320b) in services/slow_learning/advanced_backtest_engine.py:
  1. NEXT-BAR-OPEN FILLS — a signal that fires on bar i now fills at bar i+1's
     OPEN (you cannot trade a close you only know after the bar closes).
  2. SLIPPAGE — adverse slippage (bps) on every MARKET order: entry fills,
     stop exits, time exits, end-of-data exits. Target (limit) exits get no
     slippage but DO honor favorable gaps.
  3. GAP-THROUGH STOPS — if a bar OPENS beyond the stop, the fill is the open
     (worse), not the stop price.
  4. COMMISSION — IBKR-style per-share with per-order minimum, charged on both
     sides, subtracted from trade PnL (stored in BacktestTrade.commission).

  All three simulation loops are covered: _simulate_strategy_with_ai,
  _simulate_strategy_with_gate, _simulate_strategy.

ENV KNOBS:
  BT_COSTS=0                 -> legacy frictionless behaviour (A/B comparison)
  BT_SLIPPAGE_BPS            -> default 2.0 (0.02% per market order)
  BT_COMMISSION_PER_SHARE    -> default 0.005
  BT_COMMISSION_MIN          -> default 1.00
  BT_NEXT_BAR_FILLS=0        -> fill on signal-bar close (legacy timing)

USAGE (from the repo's backend/ directory, or pass --backend):
  python apply_v320b_backtest_costs.py            # dry-run
  python apply_v320b_backtest_costs.py --commit   # apply

Safety: string-anchored (line-number agnostic), idempotent, py_compile before
write, all-or-nothing.
"""
import argparse
import os
import py_compile
import sys
import tempfile

COST_HELPERS = '''import os

# ════════════════════════════════════════════════════════════════════════════
# v320b Tier-1b — Execution-cost model (slippage, commission, next-bar-open
# fills, gap-through stop fills). Env knobs:
#   BT_COSTS=0                 -> legacy frictionless behaviour (A/B compare)
#   BT_SLIPPAGE_BPS            -> adverse market-order slippage (default 2.0)
#   BT_COMMISSION_PER_SHARE    -> per-share, per-side (default 0.005, IBKR-like)
#   BT_COMMISSION_MIN          -> per-order minimum (default 1.00)
#   BT_NEXT_BAR_FILLS=0        -> fill on signal-bar close (legacy timing)
# ════════════════════════════════════════════════════════════════════════════


def _bt_cost_cfg() -> Dict[str, Any]:
    """Execution-cost knobs, read once per simulation call."""
    def _off(name, default="1"):
        return str(os.environ.get(name, default)).strip().lower() in ("0", "false", "off", "no")

    def _f(name, default):
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    enabled = not _off("BT_COSTS")
    return {
        "enabled": enabled,
        "slippage_bps": _f("BT_SLIPPAGE_BPS", 2.0) if enabled else 0.0,
        "commission_per_share": _f("BT_COMMISSION_PER_SHARE", 0.005) if enabled else 0.0,
        "commission_min": _f("BT_COMMISSION_MIN", 1.0) if enabled else 0.0,
        "next_bar_fills": enabled and not _off("BT_NEXT_BAR_FILLS"),
    }


def _slip(price: float, is_buy: bool, bps: float) -> float:
    """Market-order fill with ADVERSE slippage: buys fill higher, sells lower."""
    if price <= 0 or bps <= 0:
        return price
    return price * (1 + bps / 10000.0) if is_buy else price * (1 - bps / 10000.0)


def _commission(shares: int, cfg: Dict[str, Any]) -> float:
    """One SIDE of IBKR-style per-share commission with a per-order minimum."""
    if shares <= 0 or cfg["commission_per_share"] <= 0:
        return 0.0
    return max(cfg["commission_min"], shares * cfg["commission_per_share"])


def _stop_fill(stop_price: float, bar_open: float, is_short: bool) -> float:
    """Stop fill honoring gaps: if the bar OPENS through the stop you get the
    open (worse), never the stop price."""
    if bar_open <= 0:
        return stop_price
    if is_short:
        return max(stop_price, bar_open)   # short stop = BUY above entry
    return min(stop_price, bar_open)       # long stop = SELL below entry


def _target_fill(target_price: float, bar_open: float, is_short: bool) -> float:
    """Limit-order target fill: a gap THROUGH the target fills at the open
    (better than the limit). Otherwise the exact limit price."""
    if bar_open <= 0:
        return target_price
    if is_short:
        return min(target_price, bar_open)  # short target = BUY below entry
    return max(target_price, bar_open)      # long target = SELL above entry


def _fill_pending_entry(pending, bar_open, timestamp, symbol, strategy, exec_cfg):
    """v320b — construct a BacktestTrade filled at the CURRENT bar's open
    (i.e. the bar AFTER the signal bar) with adverse slippage applied.
    Stops/targets are computed from the ACTUAL fill price. Returns None when
    the open is unusable or the position rounds to zero shares."""
    is_short = pending["direction"] == "short"
    fill = _slip(bar_open, is_buy=not is_short, bps=exec_cfg["slippage_bps"])
    if fill <= 0:
        return None
    shares = int(pending["position_value"] / fill)
    if shares <= 0:
        return None
    if is_short:
        stop_price = fill * (1 + strategy.stop_pct / 100)
        target_price = fill * (1 - strategy.target_pct / 100)
    else:
        stop_price = fill * (1 - strategy.stop_pct / 100)
        target_price = fill * (1 + strategy.target_pct / 100)
    return BacktestTrade(
        id=f"t_{uuid.uuid4().hex[:8]}",
        symbol=symbol,
        strategy_name=strategy.name,
        setup_type=strategy.setup_type,
        direction=pending["direction"],
        entry_date=timestamp[:10],
        entry_time=timestamp[11:19] if len(timestamp) > 10 else "",
        entry_price=fill,
        shares=shares,
        stop_price=stop_price,
        target_price=target_price,
        bars_held=0,
        slippage_cost=abs(fill - bar_open) * shares,
    )


'''

PENDING_FILL_SNIPPET = """            bar_open = bar.get("open", bar.get("o", current_price))
            # gap_open <= 0 disables gap-aware fills (legacy exact stop/target under BT_COSTS=0)
            gap_open = bar_open if exec_cfg["enabled"] else 0.0

            # v320b: fill any PENDING entry at THIS bar's open (+ adverse slippage)
            if pending_entry is not None and not in_position:
                current_trade = _fill_pending_entry(
                    pending_entry, bar_open, timestamp, symbol, strategy, exec_cfg
                )
                if current_trade is not None:
                    in_position = True
                pending_entry = None
"""

COMMISSION_SNIPPET = """
                    # v320b: round-trip commission (entry + exit)
                    _comm = _commission(current_trade.shares, exec_cfg) * 2.0
                    if _comm > 0:
                        current_trade.commission = _comm
                        current_trade.pnl -= _comm"""

EDITS = [
    {
        "name": "B0: cost-model helpers (module level)",
        "marker": "def _bt_cost_cfg() ->",
        "old": """# ============================================================================
# Data Classes
# ============================================================================""",
        "new": COST_HELPERS + """# ============================================================================
# Data Classes
# ============================================================================""",
    },
    {
        "name": "B1: BacktestTrade cost fields",
        "marker": "slippage_cost: float = 0.0",
        "old": """    tqs_score: float = 0.0
    market_regime: str = ""
""",
        "new": """    tqs_score: float = 0.0
    market_regime: str = ""
    # v320b execution costs (0.0 under BT_COSTS=0 / legacy docs)
    commission: float = 0.0
    slippage_cost: float = 0.0
""",
    },
    # ── _simulate_strategy_with_ai ──
    {
        "name": "B2: with_ai init (exec_cfg + pending_entry)",
        "marker": "exec_cfg = _bt_cost_cfg()\n        pending_entry = None\n\n        # Determine strategy direction ONCE",
        "old": """        # Determine strategy direction ONCE (all trades in this call share it)""",
        "new": """        exec_cfg = _bt_cost_cfg()
        pending_entry = None

        # Determine strategy direction ONCE (all trades in this call share it)""",
    },
    {
        "name": "B3: with_ai pending fill at bar open",
        "marker": "# v320b: fill any PENDING entry at THIS bar's open (+ adverse slippage)\n            if pending_entry is not None and not in_position:\n                current_trade = _fill_pending_entry(\n                    pending_entry, bar_open, timestamp, symbol, strategy, exec_cfg\n                )\n                if current_trade is not None:\n                    in_position = True\n                pending_entry = None\n\n            # Track equity — P&L direction-aware",
        "old": """            low = bar.get("low", bar.get("l", current_price))

            # Track equity — P&L direction-aware""",
        "new": """            low = bar.get("low", bar.get("l", current_price))
""" + PENDING_FILL_SNIPPET + """
            # Track equity — P&L direction-aware""",
    },
    {
        "name": "B4: with_ai gap-aware exits + slippage",
        "marker": "_stop_fill(current_trade.stop_price, gap_open, True),",
        "old": """                if is_short:
                    # Short: stop is ABOVE entry, target is BELOW entry
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = current_price
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = current_price
                        exit_reason = "end_of_data"
                else:
                    # Long: stop is BELOW entry, target is ABOVE entry
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = current_price
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = current_price
                        exit_reason = "end_of_data"
""",
        "new": """                if is_short:
                    # Short: stop is ABOVE entry, target is BELOW entry
                    # v320b: gap-aware stop fills + market-order slippage
                    if high >= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, True),
                            is_buy=True, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, True)
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = _slip(current_price, is_buy=True, bps=exec_cfg["slippage_bps"])
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = _slip(current_price, is_buy=True, bps=exec_cfg["slippage_bps"])
                        exit_reason = "end_of_data"
                else:
                    # Long: stop is BELOW entry, target is ABOVE entry
                    # v320b: gap-aware stop fills + market-order slippage
                    if low <= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, False),
                            is_buy=False, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, False)
                        exit_reason = "target"
                    elif current_trade.bars_held >= strategy.max_bars_to_hold:
                        exit_price = _slip(current_price, is_buy=False, bps=exec_cfg["slippage_bps"])
                        exit_reason = "time"
                    elif i == len(bars) - 1:
                        exit_price = _slip(current_price, is_buy=False, bps=exec_cfg["slippage_bps"])
                        exit_reason = "end_of_data"
""",
    },
    {
        "name": "B5: with_ai commission",
        "marker": "# v320b: round-trip commission (entry + exit)\n                    _comm = _commission(current_trade.shares, exec_cfg) * 2.0\n                    if _comm > 0:\n                        current_trade.commission = _comm\n                        current_trade.pnl -= _comm\n\n                    if risk > 0:",
        "old": """                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100
                        risk = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100
                        risk = current_trade.entry_price - current_trade.stop_price
""",
        "new": """                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100
                        risk = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100
                        risk = current_trade.entry_price - current_trade.stop_price
""" + COMMISSION_SNIPPET + "\n",
    },
    {
        "name": "B6: with_ai next-bar entry queue",
        "marker": "# v320b: signal fires on THIS bar — queue fill at NEXT bar's open\n                        pending_entry = {\"direction\": trade_direction, \"position_value\": position_value}\n                        continue\n                    shares = int(position_value / current_price)",
        "old": """                if enter:
                    position_value = capital * (strategy.position_size_pct / 100)
                    shares = int(position_value / current_price)""",
        "new": """                if enter:
                    position_value = capital * (strategy.position_size_pct / 100)
                    if exec_cfg["next_bar_fills"]:
                        # v320b: signal fires on THIS bar — queue fill at NEXT bar's open
                        pending_entry = {"direction": trade_direction, "position_value": position_value}
                        continue
                    shares = int(position_value / current_price)""",
    },
    # ── _simulate_strategy_with_gate ──
    {
        "name": "B7: with_gate init",
        "marker": "gate_stats = {\"evaluated\": 0, \"go\": 0, \"reduce\": 0, \"skip\": 0}\n        exec_cfg = _bt_cost_cfg()",
        "old": """        gate_stats = {"evaluated": 0, "go": 0, "reduce": 0, "skip": 0}""",
        "new": """        gate_stats = {"evaluated": 0, "go": 0, "reduce": 0, "skip": 0}
        exec_cfg = _bt_cost_cfg()
        pending_entry = None""",
    },
    {
        "name": "B8: with_gate pending fill at bar open",
        "marker": "pending_entry = None\n\n            # Track equity — direction-aware unrealized P&L",
        "old": """            low = bar.get("low", bar.get("l", current_price))

            # Track equity — direction-aware unrealized P&L""",
        "new": """            low = bar.get("low", bar.get("l", current_price))
""" + PENDING_FILL_SNIPPET + """
            # Track equity — direction-aware unrealized P&L""",
    },
    {
        "name": "B9a: with_gate gap-aware stop/target exits",
        "marker": "_stop_fill(current_trade.stop_price, gap_open, True),\n                            is_buy=True, bps=exec_cfg[\"slippage_bps\"])\n                        exit_reason = \"stop\"\n                    elif low <= current_trade.target_price:\n                        exit_price = _target_fill(current_trade.target_price, gap_open, True)\n                        exit_reason = \"target\"\n                else:\n                    # LONG",
        "old": """                if is_short:
                    # SHORT: stop ABOVE entry (hit when high rises), target BELOW (hit when low falls)
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                else:
                    # LONG: stop BELOW entry (hit when low falls), target ABOVE (hit when high rises)
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
""",
        "new": """                if is_short:
                    # SHORT: stop ABOVE entry (hit when high rises), target BELOW (hit when low falls)
                    # v320b: gap-aware stop fills + market-order slippage
                    if high >= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, True),
                            is_buy=True, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, True)
                        exit_reason = "target"
                else:
                    # LONG: stop BELOW entry (hit when low falls), target ABOVE (hit when high rises)
                    # v320b: gap-aware stop fills + market-order slippage
                    if low <= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, False),
                            is_buy=False, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, False)
                        exit_reason = "target"
""",
    },
    {
        "name": "B9b: with_gate time/eod slippage",
        "marker": "exit_price = _slip(current_price, is_buy=is_short, bps=exec_cfg[\"slippage_bps\"])\n                    exit_reason = \"time\"",
        "old": """                # Time / end-of-data exits apply to both directions
                if exit_price is None and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = current_price
                    exit_reason = "time"
                elif exit_price is None and i == len(bars) - 1:
                    exit_price = current_price
                    exit_reason = "end_of_data"
""",
        "new": """                # Time / end-of-data exits apply to both directions (v320b: market-order slippage)
                if exit_price is None and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = _slip(current_price, is_buy=is_short, bps=exec_cfg["slippage_bps"])
                    exit_reason = "time"
                elif exit_price is None and i == len(bars) - 1:
                    exit_price = _slip(current_price, is_buy=is_short, bps=exec_cfg["slippage_bps"])
                    exit_reason = "end_of_data"
""",
    },
    {
        "name": "B10: with_gate commission",
        "marker": "_comm = _commission(current_trade.shares, exec_cfg) * 2.0\n                    if _comm > 0:\n                        current_trade.commission = _comm\n                        current_trade.pnl -= _comm\n\n                    if risk_per_share > 0:",
        "old": """                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.entry_price - current_trade.stop_price
""",
        "new": """                    if is_short:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (1 - exit_price / current_trade.entry_price) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.stop_price - current_trade.entry_price
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0
                        risk_per_share = current_trade.entry_price - current_trade.stop_price
""" + COMMISSION_SNIPPET + "\n",
    },
    {
        "name": "B11: with_gate next-bar entry queue",
        "marker": "# v320b: fill at NEXT bar's open\n                                pending_entry = {\"direction\": trade_direction, \"position_value\": position_value}\n                                continue",
        "old": """                            position_value = capital * (strategy.position_size_pct / 100) * position_multiplier
                            shares = int(position_value / current_price)""",
        "new": """                            position_value = capital * (strategy.position_size_pct / 100) * position_multiplier
                            if exec_cfg["next_bar_fills"]:
                                # v320b: fill at NEXT bar's open
                                pending_entry = {"direction": trade_direction, "position_value": position_value}
                                continue
                            shares = int(position_value / current_price)""",
    },
    # ── _simulate_strategy (plain) ──
    {
        "name": "B12: plain init",
        "marker": "equity_curve: List[Dict] = []\n        exec_cfg = _bt_cost_cfg()",
        "old": """            htf_trend: Higher timeframe trend ('bullish', 'bearish', 'neutral') for MTF analysis
        \"\"\"
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []""",
        "new": """            htf_trend: Higher timeframe trend ('bullish', 'bearish', 'neutral') for MTF analysis
        \"\"\"
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict] = []
        exec_cfg = _bt_cost_cfg()
        pending_entry = None""",
    },
    {
        "name": "B13: plain pending fill at bar open",
        "marker": "pending_entry = None\n            \n            # Track equity",
        "old": """            low = bar.get("low", bar.get("l", current_price))
            
            # Track equity""",
        "new": """            low = bar.get("low", bar.get("l", current_price))
""" + PENDING_FILL_SNIPPET + """            
            # Track equity""",
    },
    {
        "name": "B14: plain gap-aware stop/target exits",
        "marker": "_stop_fill(current_trade.stop_price, gap_open, True),\n                            is_buy=True, bps=exec_cfg[\"slippage_bps\"])\n                        exit_reason = \"stop\"\n                    elif low <= current_trade.target_price:\n                        exit_price = _target_fill(current_trade.target_price, gap_open, True)\n                        exit_reason = \"target\"\n                else:\n                    # Long trade",
        "old": """                if is_short_trade:
                    # Short trade: stop hit when price goes UP, target hit when DOWN
                    if high >= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
                else:
                    # Long trade: stop hit when price goes DOWN, target hit when UP
                    if low <= current_trade.stop_price:
                        exit_price = current_trade.stop_price
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = current_trade.target_price
                        exit_reason = "target"
""",
        "new": """                if is_short_trade:
                    # Short trade: stop hit when price goes UP, target hit when DOWN
                    # v320b: gap-aware stop fills + market-order slippage
                    if high >= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, True),
                            is_buy=True, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif low <= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, True)
                        exit_reason = "target"
                else:
                    # Long trade: stop hit when price goes DOWN, target hit when UP
                    # v320b: gap-aware stop fills + market-order slippage
                    if low <= current_trade.stop_price:
                        exit_price = _slip(
                            _stop_fill(current_trade.stop_price, gap_open, False),
                            is_buy=False, bps=exec_cfg["slippage_bps"])
                        exit_reason = "stop"
                    elif high >= current_trade.target_price:
                        exit_price = _target_fill(current_trade.target_price, gap_open, False)
                        exit_reason = "target"
""",
    },
    {
        "name": "B15a: plain time-exit slippage",
        "marker": "exit_price = _slip(current_price, is_buy=is_short_trade, bps=exec_cfg[\"slippage_bps\"])\n                    exit_reason = \"time\"",
        "old": """                # Time-based exit
                if not exit_price and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = current_price
                    exit_reason = "time"
""",
        "new": """                # Time-based exit (v320b: market-order slippage)
                if not exit_price and current_trade.bars_held >= strategy.max_bars_to_hold:
                    exit_price = _slip(current_price, is_buy=is_short_trade, bps=exec_cfg["slippage_bps"])
                    exit_reason = "time"
""",
    },
    {
        "name": "B15b: plain end-of-data slippage",
        "marker": "exit_price = _slip(current_price, is_buy=is_short_trade, bps=exec_cfg[\"slippage_bps\"])\n                    exit_reason = \"end_of_data\"",
        "old": """                # End of data
                if not exit_price and i == len(bars) - 1:
                    exit_price = current_price
                    exit_reason = "end_of_data"
""",
        "new": """                # End of data (v320b: market-order slippage)
                if not exit_price and i == len(bars) - 1:
                    exit_price = _slip(current_price, is_buy=is_short_trade, bps=exec_cfg["slippage_bps"])
                    exit_reason = "end_of_data"
""",
    },
    {
        "name": "B16: plain commission",
        "marker": "_comm = _commission(current_trade.shares, exec_cfg) * 2.0\n                    if _comm > 0:\n                        current_trade.commission = _comm\n                        current_trade.pnl -= _comm\n                    \n                    risk = abs(",
        "old": """                    if is_short_trade:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (current_trade.entry_price / exit_price - 1) * 100 if exit_price > 0 else 0
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0
                    
                    risk = abs(""",
        "new": """                    if is_short_trade:
                        current_trade.pnl = (current_trade.entry_price - exit_price) * current_trade.shares
                        current_trade.pnl_percent = (current_trade.entry_price / exit_price - 1) * 100 if exit_price > 0 else 0
                    else:
                        current_trade.pnl = (exit_price - current_trade.entry_price) * current_trade.shares
                        current_trade.pnl_percent = (exit_price / current_trade.entry_price - 1) * 100 if current_trade.entry_price > 0 else 0

                    # v320b: round-trip commission (entry + exit)
                    _comm = _commission(current_trade.shares, exec_cfg) * 2.0
                    if _comm > 0:
                        current_trade.commission = _comm
                        current_trade.pnl -= _comm
                    
                    risk = abs(""",
    },
    {
        "name": "B17: plain next-bar entry queue",
        "marker": "pending_entry = {\"direction\": direction, \"position_value\": position_value}\n                        continue",
        "old": """                    # Calculate position size
                    position_value = capital * (strategy.position_size_pct / 100)
                    shares = int(position_value / current_price)""",
        "new": """                    # Calculate position size
                    position_value = capital * (strategy.position_size_pct / 100)
                    if exec_cfg["next_bar_fills"]:
                        # v320b: fill at NEXT bar's open
                        pending_entry = {"direction": direction, "position_value": position_value}
                        continue
                    shares = int(position_value / current_price)""",
    },
    {
        "name": "B18: legacy-mode fixture for direction-stop regression tests",
        "file": "tests/test_backtest_direction_stops.py",
        "marker": "_legacy_frictionless_mode",
        "old": """# ---------- Helpers ----------""",
        "new": """@pytest.fixture(autouse=True)
def _legacy_frictionless_mode(monkeypatch):
    \"\"\"v320b adds execution costs (slippage / commission / next-bar-open fills)
    ON BY DEFAULT. These tests pin the DIRECTION/STOP logic, not the cost
    model, so they run in legacy frictionless mode.\"\"\"
    monkeypatch.setenv("BT_COSTS", "0")


# ---------- Helpers ----------""",
    },
]

TARGET_FILE = "services/slow_learning/advanced_backtest_engine.py"


def find_backend(cli_backend):
    if cli_backend:
        return os.path.abspath(cli_backend)
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "services", "slow_learning")):
        return cwd
    if os.path.isdir(os.path.join(cwd, "backend", "services", "slow_learning")):
        return os.path.join(cwd, "backend")
    print("✗ Could not locate backend dir. Run from repo root or backend/, or pass --backend PATH")
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--backend", default=None, help="path to backend/ directory")
    args = ap.parse_args()

    backend = find_backend(args.backend)
    print(f"Backend dir : {backend}")
    print(f"Mode        : {'COMMIT' if args.commit else 'DRY-RUN (no writes)'}")
    print("-" * 72)

    by_file = {}
    for e in EDITS:
        by_file.setdefault(e.get("file", TARGET_FILE), []).append(e)

    all_ok = True
    for rel, edits in by_file.items():
        path = os.path.join(backend, rel)
        if not os.path.exists(path):
            print(f"✗ MISSING FILE: {path}")
            all_ok = False
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        orig = content
        file_ok = True
        applied = 0
        for e in edits:
            if e["marker"] in content:
                print(f"  = skip (already applied): {e['name']}")
                continue
            cnt = content.count(e["old"])
            if cnt != 1:
                print(f"  ✗ anchor found x{cnt} (need exactly 1): {e['name']}")
                file_ok = False
                continue
            content = content.replace(e["old"], e["new"])
            applied += 1
            print(f"  ✓ patched: {e['name']}")

        if not file_ok:
            print(f"✗ {rel}: anchor failure — NOT writing this file")
            all_ok = False
            continue
        if content == orig:
            print(f"= {rel}: nothing to do")
            continue

        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        try:
            py_compile.compile(tmp.name, doraise=True)
        except py_compile.PyCompileError as err:
            print(f"✗ {rel}: COMPILE FAILED after patch — NOT writing\n{err}")
            all_ok = False
            continue
        finally:
            os.unlink(tmp.name)

        if args.commit:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"→ WROTE {rel} ({applied} edits)")
        else:
            print(f"→ DRY-RUN OK for {rel} ({applied} edits would be applied)")

    print("-" * 72)
    if all_ok:
        print("ALL OK." + ("" if args.commit else " Re-run with --commit to apply."))
        sys.exit(0)
    print("FAILURES — see above. Nothing partially written per-file.")
    sys.exit(1)


if __name__ == "__main__":
    main()
