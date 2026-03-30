"""
Trade Snapshot Service - Generates annotated chart snapshots for trades.
Auto-captures the life of each trade with AI decision annotations.
"""
import io
import base64
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from bson import ObjectId

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import mplfinance as mpf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class TradeSnapshotService:
    """Generates and stores annotated chart snapshots for trades."""

    def __init__(self, db):
        self.db = db
        self.snapshots_col = db["trade_snapshots"]
        self.bot_trades_col = db["bot_trades"]
        self.manual_trades_col = db["trades"]
        self.bars_col = db["historical_bars"]
        self.gate_log_col = db["confidence_gate_log"]

    async def generate_snapshot(self, trade_id: str, source: str = "bot") -> Dict:
        """Async wrapper for generate_snapshot_sync (for use in async close hooks)."""
        return self.generate_snapshot_sync(trade_id, source)

    def generate_snapshot_sync(self, trade_id: str, source: str = "bot") -> Dict:
        """
        Generate a chart snapshot for a closed trade.
        
        Args:
            trade_id: The trade ID
            source: 'bot' or 'manual'
        
        Returns:
            Snapshot document with chart_image (base64), annotations, metadata
        """
        # 1. Fetch trade data
        trade = self._get_trade(trade_id, source)
        if not trade:
            return {"success": False, "error": "Trade not found"}

        if trade.get("status") != "closed":
            return {"success": False, "error": "Trade must be closed to generate snapshot"}

        # 2. Determine time range for chart
        entry_time, exit_time = self._parse_trade_times(trade)
        if not entry_time or not exit_time:
            return {"success": False, "error": "Could not determine trade entry/exit times"}

        # 3. Build annotations from trade data
        annotations = self._build_annotations(trade, source)

        # 4. Fetch OHLCV bars for the chart
        symbol = trade.get("symbol", "")
        timeframe = self._select_chart_timeframe(trade, entry_time, exit_time)
        bars = self._fetch_bars(symbol, timeframe, entry_time, exit_time)

        # 5. Generate chart image
        chart_base64 = self._render_chart(
            bars=bars,
            symbol=symbol,
            trade=trade,
            annotations=annotations,
            entry_time=entry_time,
            exit_time=exit_time,
            timeframe=timeframe,
            source=source
        )

        # 6. Build snapshot document
        snapshot = {
            "trade_id": trade_id,
            "source": source,
            "symbol": symbol,
            "direction": trade.get("direction", "long"),
            "setup_type": trade.get("setup_type") or trade.get("strategy_id", ""),
            "entry_price": trade.get("fill_price") or trade.get("entry_price", 0),
            "exit_price": trade.get("exit_price", 0),
            "pnl": trade.get("realized_pnl") or trade.get("pnl", 0),
            "pnl_percent": trade.get("pnl_pct") or trade.get("pnl_percent", 0),
            "close_reason": trade.get("close_reason", ""),
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "timeframe": timeframe,
            "chart_image": chart_base64,
            "annotations": annotations,
            "bars_count": len(bars) if bars is not None and not bars.empty else 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 7. Upsert to MongoDB
        self.snapshots_col.update_one(
            {"trade_id": trade_id, "source": source},
            {"$set": snapshot},
            upsert=True
        )

        logger.info(f"Snapshot generated for {source} trade {trade_id} ({symbol})")
        return {"success": True, "snapshot": {k: v for k, v in snapshot.items() if k != "chart_image"},
                "has_chart": bool(chart_base64)}

    def get_snapshot(self, trade_id: str, source: str = "bot") -> Optional[Dict]:
        """Retrieve an existing snapshot."""
        snap = self.snapshots_col.find_one(
            {"trade_id": trade_id, "source": source},
            {"_id": 0}
        )
        return snap

    async def batch_generate(self, limit: int = 50) -> Dict:
        """Async wrapper for batch_generate_sync."""
        return self.batch_generate_sync(limit)

    def batch_generate_sync(self, limit: int = 50) -> Dict:
        """Generate snapshots for closed trades that don't have one yet."""
        generated = 0
        errors = 0

        # Bot trades
        existing_bot = set(
            doc["trade_id"] for doc in self.snapshots_col.find({"source": "bot"}, {"trade_id": 1, "_id": 0})
        )
        bot_trades = list(self.bot_trades_col.find(
            {"status": "closed"},
            {"_id": 0, "id": 1}
        ).limit(limit * 2))

        for bt in bot_trades:
            tid = bt.get("id", "")
            if tid and tid not in existing_bot:
                try:
                    result = self.generate_snapshot_sync(tid, "bot")
                    if result.get("success"):
                        generated += 1
                    else:
                        errors += 1
                except Exception as e:
                    logger.warning(f"Snapshot generation failed for bot trade {tid}: {e}")
                    errors += 1
                if generated >= limit:
                    break

        # Manual trades
        if generated < limit:
            existing_manual = set(
                doc["trade_id"] for doc in self.snapshots_col.find({"source": "manual"}, {"trade_id": 1, "_id": 0})
            )
            manual_trades = list(self.manual_trades_col.find(
                {"status": "closed"},
                {"_id": 1}
            ).limit(limit * 2))

            for mt in manual_trades:
                tid = str(mt["_id"])
                if tid not in existing_manual:
                    try:
                        result = self.generate_snapshot_sync(tid, "manual")
                        if result.get("success"):
                            generated += 1
                        else:
                            errors += 1
                    except Exception as e:
                        logger.warning(f"Snapshot generation failed for manual trade {tid}: {e}")
                        errors += 1
                    if generated >= limit:
                        break

        return {"generated": generated, "errors": errors}

    # ─── Private Methods ─────────────────────────────────────────────

    def _get_trade(self, trade_id: str, source: str) -> Optional[Dict]:
        """Fetch trade document from the appropriate collection."""
        if source == "bot":
            trade = self.bot_trades_col.find_one({"id": trade_id}, {"_id": 0})
            return trade
        else:
            try:
                trade = self.manual_trades_col.find_one({"_id": ObjectId(trade_id)})
                if trade:
                    trade["id"] = str(trade.pop("_id"))
                return trade
            except Exception:
                return None

    def _parse_trade_times(self, trade: Dict):
        """Extract entry and exit datetimes from trade."""
        entry_str = trade.get("created_at") or trade.get("executed_at") or trade.get("entry_date")
        exit_str = trade.get("closed_at") or trade.get("exit_date")

        entry_time = self._parse_datetime(entry_str) if entry_str else None
        exit_time = self._parse_datetime(exit_str) if exit_str else None
        return entry_time, exit_time

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse various datetime string formats."""
        if not dt_str:
            return None
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                dt = datetime.strptime(dt_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    def _select_chart_timeframe(self, trade: Dict, entry_time: datetime, exit_time: datetime) -> str:
        """Select appropriate bar timeframe based on trade duration."""
        duration = exit_time - entry_time
        minutes = duration.total_seconds() / 60

        if minutes < 30:
            return "1 min"
        elif minutes < 120:
            return "5 mins"
        elif minutes < 480:
            return "15 mins"
        elif minutes < 1440:
            return "30 mins"
        elif minutes < 4320:  # 3 days
            return "1 hour"
        else:
            return "1 day"

    def _fetch_bars(self, symbol: str, timeframe: str, entry_time: datetime, exit_time: datetime) -> Optional[pd.DataFrame]:
        """Fetch OHLCV bars from MongoDB for the chart timeframe."""
        # Add padding: 20% before entry and 10% after exit for context
        duration = exit_time - entry_time
        padding_before = max(duration * 0.3, timedelta(minutes=15))
        padding_after = max(duration * 0.15, timedelta(minutes=5))

        start = entry_time - padding_before
        end = exit_time + padding_after

        bars = list(self.bars_col.find(
            {
                "symbol": symbol,
                "bar_size": timeframe,
                "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}
            },
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        ).sort("date", 1))

        if not bars:
            # Try alternate date field names
            bars = list(self.bars_col.find(
                {
                    "symbol": symbol,
                    "bar_size": timeframe,
                    "timestamp": {"$gte": start.isoformat(), "$lte": end.isoformat()}
                },
                {"_id": 0, "timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            ).sort("timestamp", 1))
            # Rename timestamp to date
            for b in bars:
                if "timestamp" in b and "date" not in b:
                    b["date"] = b.pop("timestamp")

        if not bars:
            return None

        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df.dropna()
        return df

    def _build_annotations(self, trade: Dict, source: str) -> List[Dict]:
        """Build structured annotations from trade data and AI decisions."""
        annotations = []
        entry_price = trade.get("fill_price") or trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        direction = trade.get("direction", "long")

        # ── Entry annotation ──
        entry_time = trade.get("created_at") or trade.get("executed_at") or trade.get("entry_date", "")
        entry_reasons = []

        entry_ctx = trade.get("entry_context", {})
        if entry_ctx:
            # Confidence Gate decision
            gate = entry_ctx.get("confidence_gate", {})
            if gate:
                decision = gate.get("decision", "")
                conf = gate.get("confidence_score", 0)
                mode = gate.get("trading_mode", "")
                entry_reasons.append(f"Gate: {decision} ({conf}% conf, {mode} mode)")
                reasoning = gate.get("reasoning", [])
                for r in reasoning[:3]:
                    entry_reasons.append(f"  {r}")

                # Live prediction
                pred = gate.get("live_prediction", {})
                if pred:
                    entry_reasons.append(f"AI Model: {pred.get('direction', '?')} ({pred.get('confidence', 0)}% conf)")

            # Market regime
            regime = entry_ctx.get("market_regime", "")
            regime_score = entry_ctx.get("regime_score", 0)
            if regime:
                entry_reasons.append(f"Regime: {regime} (score {regime_score})")

            # Smart filter
            filter_action = entry_ctx.get("filter_action", "")
            filter_wr = entry_ctx.get("filter_win_rate", 0)
            if filter_action:
                entry_reasons.append(f"Smart Filter: {filter_action} ({filter_wr:.0f}% WR)")

            # TQS
            tqs = entry_ctx.get("tqs", {})
            if isinstance(tqs, dict) and tqs.get("post_gate_score"):
                entry_reasons.append(f"TQS: {tqs['post_gate_score']:.0f}")

            # Technicals
            tech = entry_ctx.get("technicals", {})
            if tech:
                parts = []
                if tech.get("trend"):
                    parts.append(f"Trend: {tech['trend']}")
                if tech.get("rsi"):
                    parts.append(f"RSI: {tech['rsi']}")
                if tech.get("vwap_relation"):
                    parts.append(f"VWAP: {tech['vwap_relation']}")
                if parts:
                    entry_reasons.append(" | ".join(parts))
        else:
            entry_reasons.append(f"{'Long' if direction == 'long' else 'Short'} entry at ${entry_price:.2f}")

        annotations.append({
            "type": "entry",
            "time": entry_time,
            "price": entry_price,
            "label": "ENTRY",
            "reasons": entry_reasons,
            "color": "#00e676" if direction == "long" else "#ff5252"
        })

        # ── Scale-out annotations ──
        scale_config = trade.get("scale_out_config", {})
        partial_exits = scale_config.get("partial_exits", [])
        for i, pe in enumerate(partial_exits):
            pe_price = pe.get("price", 0)
            pe_shares = pe.get("shares_sold", 0)
            pe_pnl = pe.get("pnl", 0)
            pe_time = pe.get("timestamp", "")
            target_idx = pe.get("target_idx", i)

            annotations.append({
                "type": "scale_out",
                "time": pe_time,
                "price": pe_price,
                "label": f"T{target_idx + 1}",
                "reasons": [
                    f"Scale-out: {pe_shares} shares @ ${pe_price:.2f}",
                    f"Partial P&L: ${pe_pnl:.2f}"
                ],
                "color": "#ffab00"
            })

        # ── Stop adjustment annotations ──
        trail_config = trade.get("trailing_stop_config", {})
        stop_adjustments = trail_config.get("stop_adjustments", [])
        for sa in stop_adjustments:
            sa_time = sa.get("timestamp") or sa.get("time", "")
            sa_price = sa.get("new_stop") or sa.get("price", 0)
            sa_reason = sa.get("reason", "adjustment")

            annotations.append({
                "type": "stop_adjust",
                "time": sa_time,
                "price": sa_price,
                "label": "STOP",
                "reasons": [f"Stop moved: ${sa_price:.2f} ({sa_reason})"],
                "color": "#ff6e40"
            })

        # ── Exit annotation ──
        exit_time = trade.get("closed_at") or trade.get("exit_date", "")
        pnl = trade.get("realized_pnl") or trade.get("pnl", 0)
        net_pnl = trade.get("net_pnl", pnl)
        close_reason = trade.get("close_reason", "manual")
        commissions = trade.get("total_commissions", 0)

        exit_reasons = [
            f"Close: {close_reason.replace('_', ' ')}",
            f"P&L: ${pnl:+.2f}" + (f" (net ${net_pnl:+.2f} after ${commissions:.2f} comm)" if commissions else ""),
        ]

        # MFE/MAE context
        mfe_pct = trade.get("mfe_pct", 0)
        mae_pct = trade.get("mae_pct", 0)
        if mfe_pct or mae_pct:
            exit_reasons.append(f"MFE: {mfe_pct:+.2f}% | MAE: {mae_pct:.2f}%")

        # Add AI reflection for exit
        if pnl > 0:
            if mfe_pct > 0 and trade.get("pnl_pct", 0) < mfe_pct * 0.5:
                exit_reasons.append("Note: Captured <50% of MFE - exit may have been early")
        else:
            if mae_pct < -2:
                exit_reasons.append("Note: Deep MAE suggests stop was too wide or entry timing was off")

        is_profitable = pnl > 0
        annotations.append({
            "type": "exit",
            "time": exit_time,
            "price": exit_price,
            "label": "EXIT",
            "reasons": exit_reasons,
            "color": "#00e676" if is_profitable else "#ff5252"
        })

        # ── Confidence Gate log entries (if any) ──
        symbol = trade.get("symbol", "")
        if symbol and entry_time:
            entry_dt = self._parse_datetime(entry_time) if isinstance(entry_time, str) else None
            if entry_dt:
                gate_logs = list(self.gate_log_col.find(
                    {
                        "symbol": symbol,
                        "timestamp": {
                            "$gte": (entry_dt - timedelta(minutes=5)).isoformat(),
                            "$lte": (entry_dt + timedelta(minutes=5)).isoformat()
                        }
                    },
                    {"_id": 0}
                ).limit(3))

                for gl in gate_logs:
                    annotations.append({
                        "type": "gate_decision",
                        "time": gl.get("timestamp", ""),
                        "price": entry_price,
                        "label": f"GATE: {gl.get('decision', '?')}",
                        "reasons": gl.get("reasoning", [])[:3],
                        "color": "#7c4dff"
                    })

        return annotations

    def _render_chart(
        self,
        bars: Optional[pd.DataFrame],
        symbol: str,
        trade: Dict,
        annotations: List[Dict],
        entry_time: datetime,
        exit_time: datetime,
        timeframe: str,
        source: str
    ) -> str:
        """Render the annotated candlestick chart and return base64 PNG."""
        entry_price = trade.get("fill_price") or trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        direction = trade.get("direction", "long")
        pnl = trade.get("realized_pnl") or trade.get("pnl", 0)
        setup_type = trade.get("setup_type") or trade.get("strategy_id", "unknown")

        # Dark theme style
        mc = mpf.make_marketcolors(
            up='#00e676', down='#ff5252',
            edge={'up': '#00e676', 'down': '#ff5252'},
            wick={'up': '#00e676', 'down': '#ff5252'},
            volume={'up': '#00e67640', 'down': '#ff525240'},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style='nightclouds',
            facecolor='#0a0a0a',
            edgecolor='#1a1a2e',
            figcolor='#0a0a0a',
            gridcolor='#1a1a2e',
            gridstyle='--',
            gridaxis='both',
            y_on_right=True,
            rc={
                'font.size': 8,
                'axes.labelsize': 8,
                'axes.titlesize': 10,
                'xtick.labelsize': 7,
                'ytick.labelsize': 8,
            }
        )

        if bars is not None and not bars.empty and len(bars) >= 2:
            # Real candlestick chart
            fig, axes = mpf.plot(
                bars,
                type='candle',
                style=style,
                volume=True,
                figsize=(14, 8),
                returnfig=True,
                panel_ratios=(4, 1),
                tight_layout=True,
            )
            ax = axes[0]
        else:
            # Fallback: simple line chart with just entry/exit
            fig, ax = plt.subplots(figsize=(14, 8), facecolor='#0a0a0a')
            ax.set_facecolor('#0a0a0a')

            # Draw a simple price line between entry and exit
            times = [entry_time, exit_time]
            prices = [entry_price, exit_price]
            color = '#00e676' if pnl >= 0 else '#ff5252'
            ax.plot(times, prices, color=color, linewidth=2, alpha=0.8)
            ax.scatter(times, prices, color=color, s=80, zorder=5)

            ax.tick_params(colors='#888888')
            ax.spines['bottom'].set_color('#1a1a2e')
            ax.spines['left'].set_color('#1a1a2e')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            for label in ax.get_xticklabels():
                label.set_color('#888888')
            for label in ax.get_yticklabels():
                label.set_color('#888888')

        # ── Draw trade markers and annotations ──
        self._draw_trade_markers(ax, bars, trade, annotations, entry_time, exit_time, entry_price, exit_price, direction)

        # ── Title ──
        pnl_str = f"${pnl:+.2f}"
        outcome_label = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "B/E"
        outcome_color = '#00e676' if pnl > 0 else '#ff5252' if pnl < 0 else '#888888'
        title = f"{symbol} | {setup_type.upper()} | {direction.upper()} | {outcome_label} {pnl_str}"
        ax.set_title(title, color=outcome_color, fontsize=12, fontweight='bold', pad=15, loc='left')

        # Subtitle with timeframe and dates
        subtitle = f"{timeframe} | {entry_time.strftime('%b %d %H:%M')} → {exit_time.strftime('%b %d %H:%M')} | Source: {source}"
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes, fontsize=8,
                color='#666666', ha='right', va='bottom')

        # ── Annotation panel on the right side ──
        self._draw_annotation_panel(fig, annotations)

        # Render to base64
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                    facecolor='#0a0a0a', edgecolor='none', pad_inches=0.3)
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode('utf-8')

    def _draw_trade_markers(self, ax, bars, trade, annotations, entry_time, exit_time, entry_price, exit_price, direction):
        """Draw entry/exit/scale-out markers on the chart."""
        has_bars = bars is not None and not bars.empty

        # Entry marker
        if has_bars:
            entry_y = entry_price
            # Find closest bar index for x position
            try:
                entry_idx = bars.index.get_indexer([entry_time], method='nearest')[0]
                entry_x = bars.index[entry_idx]
            except Exception:
                entry_x = entry_time
        else:
            entry_x = entry_time
            entry_y = entry_price

        entry_color = '#00e676' if direction == 'long' else '#ff5252'
        ax.annotate(
            f'ENTRY ${entry_price:.2f}',
            xy=(entry_x, entry_y),
            xytext=(0, -35 if direction == 'long' else 35),
            textcoords='offset points',
            fontsize=8, fontweight='bold', color=entry_color,
            arrowprops=dict(arrowstyle='->', color=entry_color, lw=1.5),
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#0a0a0a', edgecolor=entry_color, alpha=0.9),
            ha='center', va='top' if direction == 'long' else 'bottom',
            zorder=10
        )

        # Horizontal entry price line
        ax.axhline(y=entry_price, color=entry_color, linestyle='--', alpha=0.3, linewidth=0.8)

        # Exit marker
        if has_bars:
            try:
                exit_idx = bars.index.get_indexer([exit_time], method='nearest')[0]
                exit_x = bars.index[exit_idx]
            except Exception:
                exit_x = exit_time
        else:
            exit_x = exit_time

        pnl = trade.get("realized_pnl") or trade.get("pnl") or 0
        exit_color = '#00e676' if pnl >= 0 else '#ff5252'
        
        # Handle None exit_price - use entry_price as fallback
        safe_exit_price = exit_price if exit_price is not None else entry_price
        ax.annotate(
            f'EXIT ${safe_exit_price:.2f}\n${pnl:+.2f}',
            xy=(exit_x, safe_exit_price),
            xytext=(0, 35 if pnl >= 0 else -35),
            textcoords='offset points',
            fontsize=8, fontweight='bold', color=exit_color,
            arrowprops=dict(arrowstyle='->', color=exit_color, lw=1.5),
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#0a0a0a', edgecolor=exit_color, alpha=0.9),
            ha='center', va='bottom' if pnl >= 0 else 'top',
            zorder=10
        )

        # Horizontal exit price line
        if safe_exit_price:
            ax.axhline(y=safe_exit_price, color=exit_color, linestyle='--', alpha=0.3, linewidth=0.8)

        # Stop price line
        stop_price = trade.get("stop_price", 0)
        if stop_price and stop_price > 0:
            ax.axhline(y=stop_price, color='#ff6e40', linestyle=':', alpha=0.5, linewidth=1)
            ax.text(ax.get_xlim()[0], stop_price, f' STOP ${stop_price:.2f}',
                    fontsize=7, color='#ff6e40', va='bottom', alpha=0.7)

        # Target price lines
        targets = trade.get("target_prices", [])
        for i, tp in enumerate(targets[:3]):
            if tp and tp > 0:
                ax.axhline(y=tp, color='#69f0ae', linestyle=':', alpha=0.3, linewidth=0.8)
                ax.text(ax.get_xlim()[1], tp, f'T{i+1} ${tp:.2f} ',
                        fontsize=7, color='#69f0ae', va='bottom', ha='right', alpha=0.7)

        # Scale-out markers
        for ann in annotations:
            if ann["type"] == "scale_out" and ann.get("price"):
                try:
                    so_time = self._parse_datetime(ann["time"])
                    if has_bars and so_time:
                        so_idx = bars.index.get_indexer([so_time], method='nearest')[0]
                        so_x = bars.index[so_idx]
                    else:
                        so_x = so_time or exit_x
                except Exception:
                    so_x = exit_x

                ax.annotate(
                    ann["label"],
                    xy=(so_x, ann["price"]),
                    xytext=(0, -20),
                    textcoords='offset points',
                    fontsize=7, fontweight='bold', color='#ffab00',
                    arrowprops=dict(arrowstyle='->', color='#ffab00', lw=1),
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#0a0a0a', edgecolor='#ffab00', alpha=0.9),
                    ha='center',
                    zorder=9
                )

        # Fill between entry and exit (P&L zone)
        if has_bars:
            try:
                mask = (bars.index >= entry_time - timedelta(seconds=30)) & (bars.index <= exit_time + timedelta(seconds=30))
                if mask.any():
                    ax.fill_between(
                        bars.index[mask],
                        entry_price,
                        bars['close'][mask],
                        alpha=0.1,
                        color='#00e676' if pnl >= 0 else '#ff5252'
                    )
            except Exception:
                pass

    def _draw_annotation_panel(self, fig, annotations: List[Dict]):
        """Draw the AI decision panel on the right margin of the figure."""
        # Add a text box with AI reasoning
        text_lines = []
        for ann in annotations:
            marker = {
                "entry": ">>>",
                "exit": "<<<",
                "scale_out": "~~~",
                "stop_adjust": "---",
                "gate_decision": "***"
            }.get(ann["type"], "   ")

            text_lines.append(f"{marker} {ann['label']}")
            for reason in ann.get("reasons", [])[:4]:
                text_lines.append(f"    {reason}")
            text_lines.append("")

        if text_lines:
            panel_text = "\n".join(text_lines[:30])  # Cap at 30 lines
            fig.text(
                0.98, 0.5, panel_text,
                fontsize=6.5,
                fontfamily='monospace',
                color='#aaaaaa',
                verticalalignment='center',
                horizontalalignment='right',
                transform=fig.transFigure,
                bbox=dict(
                    boxstyle='round,pad=0.5',
                    facecolor='#111111',
                    edgecolor='#333333',
                    alpha=0.95
                )
            )
