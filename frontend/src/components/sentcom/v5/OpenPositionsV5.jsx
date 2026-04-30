/**
 * V5 OpenPositions — compact-by-default, expandable-on-click rows that
 * match the operator's V5 mockup. Each row shows symbol + tier chip +
 * sparkline + PnL/R + a thin "model trail / why" line. Clicking the row
 * expands to reveal full Plan A / management state, scale-out targets,
 * trailing-stop mode, AI reasoning bullets, and risk math.
 *
 * Data contract — `position` keys consumed (all optional, soft-fall-back):
 *   symbol, direction, side, setup_type, trade_style, scan_tier, timeframe,
 *   entry_price, current_price, stop_price, target_prices[], target_price,
 *   pnl, unrealized_pnl, pnl_percent, pnl_r, r_multiple, unrealized_r,
 *   shares, remaining_shares, original_shares,
 *   risk_amount, risk_reward_ratio, potential_reward,
 *   reasoning[], exit_rule, trading_approach, smb_grade, quality_grade,
 *   scale_out_state{ enabled, targets_hit, partial_exits },
 *   trailing_stop_state{ enabled, mode, current_stop, high_water_mark },
 *   p_win, pnl_series[]
 */
import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { LiveDataChip } from './LiveDataChip';

const formatR = (r) => {
  if (r == null || Number.isNaN(Number(r))) return '';
  const n = Number(r);
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}R`;
};

const formatUsd = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '';
  const n = Number(v);
  return `${n >= 0 ? '+$' : '−$'}${Math.abs(n).toFixed(0)}`;
};

const formatPx = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Number(v).toFixed(2);
};

// 2026-05-01 v19.23.1 — humanize known multi-word setup/style names so
// the tier chip reads cleanly (operator review: "TRADE 2 HOLD long" was
// verbose). Maps strict identifier → tighter display label. Unknown
// names get a generic underscore-strip + 12-char truncation.
const STYLE_HUMAN_MAP = {
  trade_2_hold:               'DAY 2',
  trade_2_continuation:       'DAY 2',
  day_2_continuation:         'DAY 2',
  day_2_failure:              'DAY 2 FAIL',
  relative_strength_position: 'RS POS',
  relative_strength:          'RS',
  base_breakout:              'BREAKOUT',
  accumulation_entry:         'ACCUM',
  earnings_momentum:          'EARN MOM',
  sector_rotation:            'ROTATION',
  opening_range_break:        'ORB',
  opening_drive:              'ORD',
  the_3_30_trade:             '3:30',
  '9_ema_scalp':              '9-EMA',
  vwap_continuation:          'VWAP',
  vwap_bounce:                'VWAP',
  premarket_high_break:       'PMH',
  bouncy_ball:                'BOUNCY',
  bella_fade:                 'FADE',
  off_sides_short:            'OFF SIDES',
  off_sides:                  'OFF SIDES',
  back_through_open:          'BACK THRU',
  up_through_open:            'UP THRU',
  gap_pick_roll:              'PICK ROLL',
  gap_fade:                   'GAP FADE',
};

const humanizeStyle = (raw) => {
  if (!raw) return '';
  const key = String(raw).toLowerCase();
  if (STYLE_HUMAN_MAP[key]) return STYLE_HUMAN_MAP[key];
  // Fallback: drop underscores, uppercase, truncate to 12 chars
  return key.replace(/_/g, ' ').toUpperCase().slice(0, 12);
};

// Derive the visible "tier chip" text from the position. Mirrors the
// mockup: SCALP long, SHORT_REV, DAY long, SWING short, etc.
const tierLabel = (pos) => {
  const dir = (pos.direction || pos.side || '').toLowerCase();
  const dirText = dir === 'short' ? 'short' : 'long';
  // trade_style is set by the bot when a setup is taken (e.g. "scalp",
  // "swing", "day", "position"). scan_tier is the universe-level tier
  // (intraday/swing/position/investment). Prefer trade_style; fall back
  // to scan_tier; finally, timeframe.
  const style = humanizeStyle(pos.trade_style)
    || humanizeStyle(pos.scan_tier)
    || humanizeStyle(pos.timeframe);
  if (!style) return dirText.toUpperCase();
  return `${style} ${dirText}`;
};

// Synthesize a "model trail / why" sub-line from whatever the bot wrote
// onto the trade. Mirrors the mockup line:
//   "TFT trails SL → $166.40 · PT $172 · CNN-LSTM 72% bull"
const modelTrailLine = (pos) => {
  const parts = [];
  // 2026-05-01 v19.23.1 — operator wants share size visible on every
  // row at-a-glance. Lead with `Nsh` so the position size is the first
  // thing the eye picks up after the symbol+pnl.
  const sh = pos.shares ?? pos.quantity;
  if (sh != null) parts.push(`${Math.round(Math.abs(Number(sh)))}sh`);
  const trail = pos.trailing_stop_state || {};
  if (trail.enabled && trail.current_stop) {
    const mode = (trail.mode || 'trail').toUpperCase();
    parts.push(`${mode} SL → $${Number(trail.current_stop).toFixed(2)}`);
  } else if (pos.stop_price != null) {
    parts.push(`SL ${formatPx(pos.stop_price)}`);
  }
  const pt = pos.target_price
    ?? (Array.isArray(pos.target_prices) ? pos.target_prices[0] : null);
  if (pt != null) parts.push(`PT $${formatPx(pt)}`);
  // Reasoning first bullet (often the model that fired the trade)
  const reasoning = Array.isArray(pos.reasoning) ? pos.reasoning : [];
  if (reasoning.length > 0) {
    const first = String(reasoning[0]).slice(0, 60);
    parts.push(first);
  } else if (pos.smb_grade) {
    parts.push(`SMB ${pos.smb_grade}`);
  }
  return parts.join(' · ');
};


const Sparkline = ({ points, color }) => {
  if (!Array.isArray(points) || points.length < 2) return null;
  const slice = points.slice(-30);
  const min = Math.min(...slice);
  const max = Math.max(...slice);
  const range = Math.max(1e-6, max - min);
  const path = slice.map((v, i) => {
    const x = (i / (slice.length - 1)) * 180;
    const y = 24 - ((v - min) / range) * 22;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg viewBox="0 0 180 24" className="w-full h-6 mt-1" preserveAspectRatio="none">
      <polyline points={path} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
};


const PositionRow = ({ position, onClick, expanded, onToggle }) => {
  const dir = (position.direction || position.side || '').toLowerCase();
  const isShort = dir === 'short';
  const pnlUsd = position.unrealized_pnl ?? position.pnl ?? 0;
  const pnlR = position.pnl_r ?? position.r_multiple ?? position.unrealized_r;
  const chipClass = isShort ? 'v5-chip-veto' : 'v5-chip-manage';
  const pnlColor = Number(pnlUsd) >= 0 ? 'v5-up' : 'v5-down';
  const sparkColor = Number(pnlUsd) >= 0 ? '#22c55e' : '#ef4444';
  const tier = tierLabel(position);
  const trailLine = modelTrailLine(position);

  const reasoning = Array.isArray(position.reasoning) ? position.reasoning : [];
  const scaleOut = position.scale_out_state || {};
  const trail = position.trailing_stop_state || {};
  const targets = Array.isArray(position.target_prices) && position.target_prices.length > 0
    ? position.target_prices
    : (position.target_price != null ? [position.target_price] : []);

  return (
    <div
      data-testid={`v5-open-position-${position.symbol}`}
      className={`px-3 py-2 border-b border-zinc-900 transition-colors ${
        expanded ? 'bg-white/5' : 'hover:bg-white/5'
      }`}
    >
      {/* Row 1 — symbol / tier chip / pnl */}
      <div
        className="flex items-baseline justify-between cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2 min-w-0">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
            data-testid={`open-position-expand-${position.symbol}`}
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded
              ? <ChevronDown className="w-3 h-3" />
              : <ChevronRight className="w-3 h-3" />}
          </button>
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors cursor-pointer"
            data-testid={`open-position-symbol-${position.symbol}`}
            onClick={(e) => { e.stopPropagation(); onClick?.(); }}
          >
            {position.symbol}
          </span>
          <span className={`v5-chip ${chipClass}`}>{tier}</span>
        </div>
        <span className={`v5-mono text-xs font-semibold ${pnlColor}`}>
          {formatUsd(pnlUsd)}{pnlR != null ? ` · ${formatR(pnlR)}` : ''}
        </span>
      </div>

      {/* Sparkline */}
      <Sparkline points={position.pnl_series} color={sparkColor} />

      {/* Row 2 — model trail / why */}
      {trailLine && (
        <div
          className="v5-why-dim mt-1 truncate"
          data-testid={`open-position-trail-${position.symbol}`}
        >
          {trailLine}
        </div>
      )}

      {/* Expanded panel */}
      {expanded && (
        <div
          className="mt-2 pt-2 border-t border-zinc-800/60 space-y-2 text-[12px] text-zinc-400"
          data-testid={`open-position-details-${position.symbol}`}
        >
          {/* Price grid: Entry / Current / SL / PT */}
          <div className="grid grid-cols-4 gap-1 v5-mono text-[12px]">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">Entry</div>
              <div className="text-zinc-200">{formatPx(position.entry_price)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">Last</div>
              <div className="text-zinc-200">{formatPx(position.current_price)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">Stop</div>
              <div className="text-rose-300">{formatPx(position.stop_price)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">
                {targets.length > 1 ? 'PT1' : 'Target'}
              </div>
              <div className="text-emerald-300">
                {targets.length > 0 ? formatPx(targets[0]) : '—'}
              </div>
            </div>
          </div>

          {/* Risk / shares row */}
          <div className="flex items-center gap-3 flex-wrap text-[11px] text-zinc-400">
            {position.risk_reward_ratio != null && (
              <span>
                <span className="text-zinc-500">R:R</span>{' '}
                <span className="text-zinc-200 font-semibold">
                  {Number(position.risk_reward_ratio).toFixed(2)}
                </span>
              </span>
            )}
            {position.risk_amount != null && (
              <span>
                <span className="text-zinc-500">Risk</span>{' '}
                <span className="text-rose-300 font-semibold">
                  ${Math.abs(Number(position.risk_amount)).toFixed(0)}
                </span>
              </span>
            )}
            {position.potential_reward != null && (
              <span>
                <span className="text-zinc-500">Reward</span>{' '}
                <span className="text-emerald-300 font-semibold">
                  ${Math.abs(Number(position.potential_reward)).toFixed(0)}
                </span>
              </span>
            )}
            {position.remaining_shares != null && position.original_shares != null && (
              <span>
                <span className="text-zinc-500">Shares</span>{' '}
                <span className="text-zinc-200 font-semibold v5-mono">
                  {position.remaining_shares}/{position.original_shares}
                </span>
              </span>
            )}
            {position.p_win != null && (() => {
              const n = Number(position.p_win);
              const pct = Math.abs(n) > 1 ? n : n * 100;
              return (
                <span>
                  <span className="text-zinc-500">P(win)</span>{' '}
                  <span className="text-zinc-200 font-semibold">
                    {Math.round(pct)}%
                  </span>
                </span>
              );
            })()}
          </div>

          {/* Trail-state line */}
          {trail.enabled && (
            <div
              className="text-[11px] text-zinc-500"
              data-testid={`open-position-trail-state-${position.symbol}`}
            >
              <span className="text-cyan-400 font-semibold uppercase">{trail.mode || 'trail'}</span>
              {' '}— stop ${formatPx(trail.current_stop)}
              {trail.high_water_mark
                ? ` · HWM ${formatPx(trail.high_water_mark)}`
                : ''}
            </div>
          )}

          {/* Scale-out targets hit */}
          {scaleOut.enabled && Array.isArray(scaleOut.targets_hit) && scaleOut.targets_hit.length > 0 && (
            <div
              className="text-[11px] text-emerald-400/80"
              data-testid={`open-position-scaleout-${position.symbol}`}
            >
              Scale-out: {scaleOut.targets_hit.length} target(s) hit
            </div>
          )}

          {/* Plan / exit rule */}
          {position.exit_rule && (
            <div
              className="text-[11px] text-zinc-500"
              data-testid={`open-position-exit-rule-${position.symbol}`}
            >
              <span className="text-zinc-600">Plan:</span> {position.exit_rule}
            </div>
          )}

          {/* AI reasoning bullets */}
          {reasoning.length > 0 && (
            <div
              className="text-[11px] text-zinc-400 space-y-0.5"
              data-testid={`open-position-reasoning-${position.symbol}`}
            >
              {reasoning.slice(0, 4).map((line, i) => (
                <div key={i} className="leading-snug">
                  <span className="text-zinc-600 mr-1">·</span>{String(line).slice(0, 200)}
                </div>
              ))}
            </div>
          )}

          {/* Setup + grade footer */}
          <div className="flex items-center gap-2 flex-wrap text-[10px] uppercase tracking-wider text-zinc-600">
            {position.setup_type && (
              <span>setup {position.setup_type}</span>
            )}
            {position.smb_grade && (
              <span>· grade {position.smb_grade}</span>
            )}
            {position.market_regime && (
              <span>· regime {position.market_regime}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};


export const OpenPositionsV5 = ({ positions, totalPnl, loading, onSelectPosition }) => {
  const open = useMemo(
    () => (positions || []).filter(p => p && p.status !== 'closed'),
    [positions],
  );
  const [expandedSymbol, setExpandedSymbol] = useState(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);
  const [reconcileMsg, setReconcileMsg] = useState(null);

  const handleToggle = (sym) => {
    setExpandedSymbol((prev) => (prev === sym ? null : sym));
  };

  // 2026-05-01 v19.24 — Orphan = IB-side position with no matching
  // `bot_trades` row in `_open_trades`. `sentcom_service.get_our_positions`
  // stamps `source: 'ib'` on these (vs `source: 'bot'` for trades the bot
  // originated). Show "Reconcile" button when ≥1 orphan is present — lets
  // the operator hand these positions over to the bot for active
  // management (trail stops, scale-out, EOD close).
  const orphans = useMemo(
    () => open.filter(p => p && p.source === 'ib'),
    [open],
  );

  const handleReconcile = async () => {
    if (reconcileBusy) return;
    const symbols = orphans.map(p => p.symbol).filter(Boolean);
    if (symbols.length === 0) return;
    const ok = typeof window !== 'undefined'
      ? window.confirm(
          `Reconcile ${symbols.length} orphan position${symbols.length > 1 ? 's' : ''} (${symbols.join(', ')})?\n\n` +
          `The bot will materialize trade records with default 2.0% stop + 2.0 R:R ` +
          `and begin actively managing them (trail stops, scale-out, EOD).`
        )
      : true;
    if (!ok) return;

    setReconcileBusy(true);
    setReconcileMsg(null);
    try {
      const base = process.env.REACT_APP_BACKEND_URL || '';
      const res = await fetch(`${base}/api/trading-bot/reconcile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.success === false) {
        setReconcileMsg({
          kind: 'error',
          text: data?.detail || data?.error || `Reconcile failed (${res.status})`,
        });
      } else {
        const nRec = (data.reconciled || []).length;
        const nSkip = (data.skipped || []).length;
        setReconcileMsg({
          kind: 'ok',
          text: `Reconciled ${nRec}${nSkip > 0 ? `, skipped ${nSkip}` : ''}`,
        });
      }
    } catch (err) {
      setReconcileMsg({ kind: 'error', text: String(err?.message || err) });
    } finally {
      setReconcileBusy(false);
      setTimeout(() => setReconcileMsg(null), 6000);
    }
  };

  return (
    <div data-testid="v5-open-positions" data-help-id="open-positions" className="flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="v5-panel-title">Open ({open.length})</div>
          <LiveDataChip compact />
          {orphans.length > 0 && (
            <button
              type="button"
              onClick={handleReconcile}
              disabled={reconcileBusy}
              data-testid="open-positions-reconcile-btn"
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border transition-colors ${
                reconcileBusy
                  ? 'border-zinc-700 text-zinc-500 cursor-wait'
                  : 'border-amber-700/60 text-amber-300 hover:bg-amber-950/40'
              }`}
              title={`Reconcile ${orphans.length} orphan IB position${orphans.length > 1 ? 's' : ''}`}
            >
              {reconcileBusy ? 'Reconciling…' : `Reconcile ${orphans.length}`}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {reconcileMsg && (
            <span
              data-testid="open-positions-reconcile-msg"
              className={`text-[11px] ${reconcileMsg.kind === 'ok' ? 'text-emerald-300' : 'text-rose-300'}`}
            >
              {reconcileMsg.text}
            </span>
          )}
          <div className={`v5-mono text-[12px] ${Number(totalPnl) >= 0 ? 'v5-up' : 'v5-down'}`}>
            {totalPnl != null ? formatUsd(totalPnl) : ''}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto v5-scroll">
        {loading && open.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">Loading positions…</div>
        )}
        {!loading && open.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">No open positions.</div>
        )}
        {open.map(p => (
          <PositionRow
            key={p.id || p._id || p.trade_id || p.symbol}
            position={p}
            expanded={expandedSymbol === p.symbol}
            onToggle={() => handleToggle(p.symbol)}
            onClick={() => onSelectPosition?.(p)}
          />
        ))}
      </div>
    </div>
  );
};

export default OpenPositionsV5;
