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
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { LiveDataChip } from './LiveDataChip';
import TradeTypeChip from './TradeTypeChip';
// v19.34.99 (2026-05-12) — trade-style + horizon chip (scalp/intraday/
// swing/investment/position) so the operator sees what kind of trade
// every open position is at a glance.
import TradeStyleChip from './TradeStyleChip';
// v19.34.2 (2026-05-04) — quote-freshness chip + legend popover.
import QuoteFreshnessChip from './QuoteFreshnessChip';
import OpenPositionsLegend from './OpenPositionsLegend';
// v19.34.11 (2026-05-06) — bracket lifecycle history panel.
import BracketHistoryPanel from './BracketHistoryPanel';
// v19.34.154 (2026-02-13) — P2 scale-out tiles: shows
// original/closed/remaining + per-target partial PnL when a winner
// has scaled out. Renders nothing for un-scaled positions.
import { ScaleOutBadge, ScaleOutDetails } from './ScaleOutBadge';
// v19.34.26 (May 2026) — Auto-visible bot-thoughts strip per Open
// Position. Pulls the last N reject/skip/trigger emissions for the
// position's symbol so the operator can see what the scanner is
// thinking without having to expand the row.
import PositionThoughtsInline from './PositionThoughtsInline';
// v19.34.160 — single source of truth for "is this a scalp?"
import { isScalpStyle } from '../../../utils/tradeStyleMeta';
// v19.34.72 — Operator Close panel (Market/Limit + percentage).
import CloseTradeModal from './CloseTradeModal';
// v19.34.258 — single trusted TQS score on the face + shared drill-down.
import TqsBadge from './TqsBadge';
import { openTqsDrawer } from './tqsDrawerBus';

// v19.34.175 — Resolve the canonical (unified) grade for a position.
// TQS is the single source of truth; fall back through the legacy
// quality grade so older fills still render a grade.
const unifiedGrade = (pos) => {
  if (!pos) return '';
  return (
    pos.unified_grade
    || pos.tqs_grade
    || (pos.entry_context && pos.entry_context.tqs && pos.entry_context.tqs.unified_grade)
    || pos.quality_grade
    || ''
  );
};
// Standalone grade chips are SUPPRESSED for F / missing grades — an
// isolated "F" badge confused operators (it read as a hard reject when
// it's just a low composite). The full reasoning still lives in the
// expandable TQS drill-down.
const showGradeChip = (g) => !!g && String(g).toUpperCase() !== 'F';

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
//
// 2026-02 v19.34.67 — IMPORTANT: do NOT map SMB style classifications
// (`trade_2_hold`, `trade_2_continuation`, `move_2_move`, `a_plus`) into
// the visible tier label. They are SMB style classes (see
// `services/tqs/tqs_engine.py:194` where `trade_2_hold` = "Intraday
// Swing 1-6h"), NOT day-counter markers. Pre-v19.34.67 the map had
// `trade_2_hold: 'DAY 2'` which made every position read as "DAY 2 long"
// regardless of actual hold duration. The fall-through chain in
// `tierLabel` below now suppresses these generic style classes and
// prefers the setup-derived label. `day_2_continuation` and
// `day_2_failure` remain mapped — those ARE Linda Raschke "Day 2"
// pattern names and are valid as a tier label.
const STYLE_HUMAN_MAP = {
  // SMB style classes intentionally NOT mapped — they are demoted by
  // `GENERIC_TRADE_STYLE_KEYS` below and never appear as tier labels.
  day_2_continuation:         'DAY 2',
  day_2_failure:              'DAY 2 FAIL',
  relative_strength_position: 'RS POS',
  relative_strength:          'RS',
  base_breakout:              'BREAKOUT',
  accumulation_entry:         'ACCUM',
  mean_reversion_long:        'MEAN REV',
  mean_reversion_short:       'MEAN REV',
  mean_reversion:             'MEAN REV',
  earnings_momentum:          'EARN MOM',
  sector_rotation:            'ROTATION',
  opening_range_break:        'ORB',
  opening_drive:              'ORD',
  the_3_30_trade:             '3:30',
  '9_ema_scalp':              '9-EMA',
  vwap_continuation:          'VWAP',
  vwap_bounce:                'VWAP',
  vwap_fade_long:             'VWAP FADE',
  vwap_fade_short:            'VWAP FADE',
  premarket_high_break:       'PMH',
  bouncy_ball:                'BOUNCY',
  bella_fade:                 'FADE',
  off_sides_short:            'OFF SIDES',
  off_sides:                  'OFF SIDES',
  back_through_open:          'BACK THRU',
  up_through_open:            'UP THRU',
  gap_pick_roll:              'PICK ROLL',
  gap_fade:                   'GAP FADE',
  // v19.34.67 — reconciled orphans (positions adopted by the bot from
  // an IB-side open position with no matching BotTrade) deserve a
  // distinct, non-generic label so the operator can tell them apart at
  // a glance. Without this they fell through to scan_tier='reconciled'
  // → 'RECONCILED' (truncated to 12 chars) or worse, the now-removed
  // 'trade_2_hold: DAY 2' mapping. Both were noise.
  reconciled_orphan:          'ADOPTED',
  reconciled:                 'ADOPTED',
};

const humanizeStyle = (raw) => {
  if (!raw) return '';
  const key = String(raw).toLowerCase();
  if (STYLE_HUMAN_MAP[key]) return STYLE_HUMAN_MAP[key];
  // Fallback: drop underscores, uppercase, truncate to 12 chars
  return key.replace(/_/g, ' ').toUpperCase().slice(0, 12);
};

// v19.34.67 — SMB style classifications that the bot defaults onto every
// BotTrade. They describe the *trade style* (how long to hold) NOT the
// setup that fired. When `trade_style` carries one of these, the tier
// chip must fall through to `setup_variant` / `setup_type` / `scan_tier`
// / `timeframe` to surface the actually-meaningful label. See
// `services/tqs/tqs_engine.py:194` for the canonical SMB style list:
//   - move_2_move = scalp (minutes)
//   - trade_2_hold = intraday swing (1-6h)
//   - a_plus      = day+ hold
const GENERIC_TRADE_STYLE_KEYS = new Set([
  'trade_2_hold', 'trade_2_continuation', 'move_2_move', 'a_plus',
]);

// Derive the visible "tier chip" text from the position. Mirrors the
// mockup: SCALP long, SHORT_REV, DAY long, SWING short, etc.
//
// v19.34.67 — Fix "every position labeled DAY 2" bug. Pre-fix, every
// position with the bot's default `trade_style='trade_2_hold'` (SMB
// "intraday swing" classification) rendered as "DAY 2 <dir>", regardless
// of the actual setup. Operator caught it Feb 2026 with 21/21 positions
// mislabeled. The new fall-through chain prefers the setup-derived
// label whenever `trade_style` is a generic SMB style class. For
// reconciled-orphan positions where `setup_type='reconciled_orphan'`,
// the chip now reads "ADOPTED <dir>" (e.g. "ADOPTED short" for the
// adopted CF position) — which is operationally meaningful and
// distinguishes orphan-adoptions from bot-originated trades.
const tierLabel = (pos) => {
  const dir = (pos.direction || pos.side || '').toLowerCase();
  const dirText = dir === 'short' ? 'short' : 'long';
  const rawTs = String(pos.trade_style || '').trim().toLowerCase();
  const isGenericTs = GENERIC_TRADE_STYLE_KEYS.has(rawTs);
  // When trade_style is a generic SMB class, prefer the setup-derived
  // label (granular variant first, then broader type, then scan_tier,
  // finally timeframe). humanizeStyle returns '' for empty/null/undef
  // which `||` falls past correctly.
  const style = (!isGenericTs && humanizeStyle(pos.trade_style))
    || humanizeStyle(pos.setup_variant)
    || humanizeStyle(pos.setup_type)
    || humanizeStyle(pos.scan_tier)
    || humanizeStyle(pos.timeframe);
  if (!style) return dirText.toUpperCase();
  return `${style} ${dirText}`;
};

// v19.34.85 — Scalp positions should never carry an "SMB" grade chip.
// SMB grading rubric (size·setup·conviction) is calibrated for
// intraday-swing horizons (1-6h holds); applying it to a 5-30 minute
// scalp produces garbage signal (a clean scalp at +0.4R can score
// "SMB B" even though the trade had zero of the intraday traits the
// grade measures). Suppress the chip when the position is a scalp.
//
// v19.34.160 — Unified detection. Pre-fix this file maintained its own
// hardcoded SCALP_SETUPS list (14 setups) that drifted from the
// canonical SETUP_TO_STYLE scalp bucket (23 setups) in
// tradeStyleMeta.js. A `vwap_fade_long` / `mean_reversion_long`
// position passed isScalpPosition() as FALSE (suffix mismatch) but the
// TradeStyleChip resolved it as "scalp" via the new suffix-stripping
// SETUP_TO_STYLE lookup. Now both consult the single source of truth
// `isScalpStyle()`, which also picks up `timeframe='scalp'` (already
// stamped by the bot on USO etc.) and any `_long`/`_short` directional
// variants automatically.
const isScalpPosition = (pos) => !!pos && isScalpStyle(pos);

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
  } else if (!isScalpPosition(pos)) {
    // v19.34.175 — show the unified TQS grade (single source of truth),
    // not the standalone SMB grade. Suppressed for F/missing (scalps too).
    const g = unifiedGrade(pos);
    if (showGradeChip(g)) parts.push(`TQS ${g}`);
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


const PositionRow = ({ position, onClick, expanded, onToggle, memberCount }) => {
  const dir = (position.direction || position.side || '').toLowerCase();
  const isShort = dir === 'short';
  const pnlUsd = position.unrealized_pnl ?? position.pnl ?? 0;
  const pnlR = position.pnl_r ?? position.r_multiple ?? position.unrealized_r;
  const chipClass = isShort ? 'v5-chip-veto' : 'v5-chip-manage';
  const pnlColor = Number(pnlUsd) >= 0 ? 'v5-up' : 'v5-down';
  const sparkColor = Number(pnlUsd) >= 0 ? '#22c55e' : '#ef4444';
  const tier = tierLabel(position);
  const trailLine = modelTrailLine(position);
  // v19.34.72 — Close panel state.
  const [closeOpen, setCloseOpen] = useState(false);

  const reasoning = Array.isArray(position.reasoning) ? position.reasoning : [];
  // v19.34.154 — Backend dataclass field is `scale_out_config`, not
  // `scale_out_state` (latent rename mismatch that hid the entire
  // scale-out UI for months). Read both for forward-compat with any
  // future renames, but the canonical name is now config.
  const scaleOut = position.scale_out_config || position.scale_out_state || {};
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
          {/* v19.34.99 — trade-style + time-horizon chip. Always present
              even when trade_style is missing (falls back to setup-derived
              style via SETUP_TO_STYLE). Hover for full horizon text. */}
          <TradeStyleChip
            row={position}
            compact={true}
            showSetup={false}
            size="xs"
            testIdSuffix={`open-pos-${position.symbol}`}
          />
          {/* v19.34.258 — single trusted TQS score on the position face;
              click opens the consolidated drill-down drawer. Replaces the
              standalone SetupGradeChip / SMB display. */}
          <TqsBadge
            symbol={position.symbol}
            score={position.tqs_score}
            gradeFallback={unifiedGrade(position)}
            source="position"
            testIdSuffix={`open-pos-${position.symbol}`}
          />
          {/* 2026-05-04 — ORPHAN/PARTIAL/STALE badge moved inline to the
              left cluster so it stops overlapping the right-aligned PnL.
              Multi-trade count rendered next to it. */}
          {memberCount > 1 && (
            <span
              data-testid={`group-multi-badge-${position.symbol}`}
              className="px-1 py-0 text-[12px] uppercase tracking-wider bg-zinc-800 text-zinc-300 border border-zinc-700 rounded"
              title={`${memberCount} bot trades aggregated`}
            >
              {memberCount}×
            </span>
          )}
          {/* v19.34.23 (2026-02-XX) — Per-row ORPHAN / PARTIAL / STALE-bot
              source badges and the RECONCILED provenance chip removed.
              Operator feedback: now that the bot auto-heals all of these
              within the same tick (Orphan Reconciler + drift watchdog),
              the badges contradicted themselves on every row
              ("ORPHAN ... RECONCILED") and added cognitive load with
              no operator action attached. The aggregate count is now
              surfaced ONCE in the panel header as a subtle
              "auto-healed: N" pill (see AutoHealHeaderPill below). The
              full provenance is still preserved in the row's expanded
              detail callout. */}
          {/* v19.31.13 — trade origin chip (PAPER amber, LIVE red, SHADOW sky).
              v19.34.1 — render even when type is "unknown" so the operator
              never has a row without a mode tag. */}
          <TradeTypeChip
            type={position.trade_type}
            size="xs"
            testIdSuffix={`open-pos-${position.symbol}`}
            title={
              position.account_id_at_fill
                ? `Filled on ${position.account_id_at_fill}`
                : 'No account context — see /api/system/account-mode'
            }
          />
          {/* v19.34.2 — quote freshness chip. Shows whether the bot
              can currently fire stops on this position. v19.34.23 —
              hide when state is FRESH (the healthy default). The chip
              now renders ONLY when the operator should care
              (amber / stale / unknown). */}
          {position.quote_state && String(position.quote_state).toLowerCase() !== 'fresh' && (
            <QuoteFreshnessChip
              state={position.quote_state}
              ageSeconds={position.quote_age_s}
              size="xs"
              testIdSuffix={`open-pos-${position.symbol}`}
            />
          )}
          {/* v19.34.3 — prior-verdict-conflict warning chip. Triggered
              when ≥2 of the bot's last 3 verdicts on this symbol/setup
              were REJECT, yet the position was reconciled anyway. */}
          {position.prior_verdict_conflict && (
            <span
              data-testid={`prior-verdict-conflict-chip-${position.symbol}`}
              className="px-1.5 py-0 text-[13px] uppercase tracking-wider rounded border bg-amber-950/70 text-amber-300 border-amber-700 font-bold animate-pulse"
              title="Bot's recent verdicts on this setup were REJECT — this position contradicts the bot's own logic. Consider closing manually or overriding SL/PT."
            >
              ⚠ CONFLICT
            </span>
          )}
          {/* v19.34.154 — Scale-out progress badge. Always-visible chip
              that surfaces partial-exit progress in the compact view
              so the operator sees "this winner is half-out" without
              expanding. Renders nothing for un-scaled positions. */}
          <ScaleOutBadge position={position} />
        </div>
        <div className="flex items-center gap-2">
          <span className={`v5-mono text-xs font-semibold ${pnlColor}`}>
            {formatUsd(pnlUsd)}{pnlR != null ? ` · ${formatR(pnlR)}` : ''}
          </span>
          {/* v19.34.72 — Operator close button. Stops row toggle propagation
              so clicking does not expand/collapse the row. */}
          <button
            type="button"
            data-testid={`open-position-close-btn-${position.symbol}`}
            onClick={(e) => { e.stopPropagation(); setCloseOpen(true); }}
            className="px-1.5 py-0 text-[12px] uppercase tracking-wider rounded border border-rose-800 bg-rose-950/60 text-rose-300 hover:bg-rose-900 hover:text-rose-100 transition-colors font-semibold"
            title="Close this position via IB (Market or Limit, partial supported)"
          >
            Close
          </button>
        </div>
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

      {/* v19.34.26 — Auto-visible bot-thoughts strip (last 5 thoughts in
          the last 60m). Renders directly inside the compact row so the
          operator never has to expand to see the scanner's reasoning. */}
      <PositionThoughtsInline symbol={position.symbol} limit={5} minutes={60} />

      {/* Expanded panel */}
      {expanded && (
        <div
          className="mt-2 pt-2 border-t border-zinc-800/60 space-y-2 text-[12px] text-zinc-400"
          data-testid={`open-position-details-${position.symbol}`}
        >
          {/* v19.34.3 — Reconcile-conflict callout. Renders ONLY when
              entered_by=reconciled_external AND prior verdicts exist.
              Shows the bot's last verdict (REJECT / R:R / setup_type)
              so the operator never silently inherits a bad setup. */}
          {position.entered_by === 'reconciled_external' && (
            <div
              data-testid={`reconcile-callout-${position.symbol}`}
              className={`px-2 py-1.5 rounded border text-[14px] leading-snug ${
                position.prior_verdict_conflict
                  ? 'bg-amber-950/40 border-amber-800/60 text-amber-200'
                  : 'bg-fuchsia-950/30 border-fuchsia-800/40 text-fuchsia-200'
              }`}
            >
              <div className="font-bold uppercase tracking-wider text-[13px] mb-0.5">
                {position.prior_verdict_conflict
                  ? '⚠ Reconcile conflict — bot disagreed with this setup'
                  : 'Reconciled from IB orphan'}
              </div>
              <div className="text-zinc-300">
                Bot did not open this. SL/PT pulled from{' '}
                <span className="font-mono text-zinc-100">
                  {position.synthetic_source === 'last_verdict'
                    ? "bot's last computed verdict"
                    : 'synthetic defaults (e.g. 2% from avg cost)'}
                </span>
                .
              </div>
              {Array.isArray(position.prior_verdicts) && position.prior_verdicts.length > 0 && (
                <div
                  data-testid={`prior-verdicts-${position.symbol}`}
                  className="mt-1 pt-1 border-t border-zinc-700/40 space-y-0.5"
                >
                  <div className="text-[13px] uppercase tracking-wider text-zinc-500">
                    Last {Math.min(3, position.prior_verdicts.length)} verdict(s)
                  </div>
                  {position.prior_verdicts.slice(0, 3).map((v, i) => (
                    <div key={i} className="font-mono text-[13px] text-zinc-400">
                      {v.timestamp ? new Date(v.timestamp).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour12: false}) + ' ET · ' : ''}
                      <span className="uppercase font-bold text-rose-300">REJECT</span>
                      {v.reason_code && <> · {v.reason_code}</>}
                      {v.rr_ratio != null && (
                        <> · R:R <span className="text-zinc-200">{Number(v.rr_ratio).toFixed(2)}</span>
                          {v.min_required != null && <> &lt; min <span className="text-zinc-200">{Number(v.min_required).toFixed(2)}</span></>}
                        </>
                      )}
                      {v.setup_type && <> · {v.setup_type}</>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Price grid: Entry / Current / SL / PT */}
          <div className="grid grid-cols-4 gap-1 v5-mono text-[12px]">
            <div>
              <div className="text-[13px] uppercase tracking-wider text-zinc-600">Entry</div>
              <div className="text-zinc-200">{formatPx(position.entry_price)}</div>
            </div>
            <div>
              <div className="text-[13px] uppercase tracking-wider text-zinc-600">Last</div>
              <div className="text-zinc-200">{formatPx(position.current_price)}</div>
            </div>
            <div>
              <div className="text-[13px] uppercase tracking-wider text-zinc-600">Stop</div>
              <div className="text-rose-300">{formatPx(position.stop_price)}</div>
            </div>
            <div>
              <div className="text-[13px] uppercase tracking-wider text-zinc-600">
                {targets.length > 1 ? 'PT1' : 'Target'}
              </div>
              <div className="text-emerald-300">
                {targets.length > 0 ? formatPx(targets[0]) : '—'}
              </div>
            </div>
          </div>

          {/* Risk / shares row */}
          <div className="flex items-center gap-3 flex-wrap text-[14px] text-zinc-400">
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
              className="text-[14px] text-zinc-500"
              data-testid={`open-position-trail-state-${position.symbol}`}
            >
              <span className="text-cyan-400 font-semibold uppercase">{trail.mode || 'trail'}</span>
              {' '}— stop ${formatPx(trail.current_stop)}
              {trail.high_water_mark
                ? ` · HWM ${formatPx(trail.high_water_mark)}`
                : ''}
            </div>
          )}

          {/* v19.34.154 — Rich scale-out details (original/closed/
              remaining + progress bar + per-target rows with partial
              PnL). Replaces the prior single-line "Scale-out: N
              target(s) hit" summary. Component returns null when no
              partial exits have fired. */}
          <ScaleOutDetails position={position} />

          {/* Plan / exit rule */}
          {position.exit_rule && (
            <div
              className="text-[14px] text-zinc-500"
              data-testid={`open-position-exit-rule-${position.symbol}`}
            >
              <span className="text-zinc-600">Plan:</span> {position.exit_rule}
            </div>
          )}

          {/* AI reasoning bullets */}
          {reasoning.length > 0 && (
            <div
              className="text-[14px] text-zinc-400 space-y-0.5"
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
          <div className="flex items-center gap-2 flex-wrap text-[13px] uppercase tracking-wider text-zinc-600">
            {(position.setup_variant || position.setup_type) && (
              <span>setup {humanizeStyle(position.setup_variant || position.setup_type)}</span>
            )}
            {/* v19.34.175 — unified TQS grade (suppressed for F/missing). */}
            {showGradeChip(unifiedGrade(position)) && (
              <span>· grade {unifiedGrade(position)}</span>
            )}
            {position.market_regime && (
              <span>· regime {position.market_regime}</span>
            )}
          </div>

          {/* v19.34.258 — TQS pillars + sizing rationale now live in the
              shared drill-down drawer (single source of truth). Open it
              from the expand too. */}
          <button
            type="button"
            data-testid={`open-position-tqs-drilldown-${position.symbol}`}
            onClick={(e) => { e.stopPropagation(); openTqsDrawer({ symbol: position.symbol, source: 'position' }); }}
            className="w-full text-left px-3 py-1.5 rounded-md border border-zinc-800 bg-zinc-950/60 text-[12px] text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200 transition-colors"
          >
            View full TQS breakdown · 5 pillars + context →
          </button>

          {/* v19.34.11 — Bracket lifecycle history (lazy-loaded on click) */}
          <BracketHistoryPanel
            tradeId={position.trade_id || position.id}
            symbol={position.symbol}
          />
        </div>
      )}
      {/* v19.34.72 — Operator Close panel */}
      {closeOpen && (
        <CloseTradeModal
          position={position}
          onClose={() => setCloseOpen(false)}
          onSubmitted={() => { /* parent polls open-positions, modal stays open until Done */ }}
        />
      )}
    </div>
  );
};


// ───────────────────────────────────────────────────────────────────────
// v19.27 — Symbol-level grouping. Multiple bot trades for the same
// symbol+direction collapse to ONE aggregate row that's expandable to
// reveal the underlying trades. Rationale: bot fires HOOD twice
// (B-grade scan, then later A-grade) → 2 separate BotTrade records,
// each with its own OCA bracket. IB nets them into one position.
// Pre-v19.27 V5 panel rendered both rows independently which was
// confusing — operator couldn't tell "is this 1 IB position or 2?"
// ───────────────────────────────────────────────────────────────────────

// v19.34.23 (2026-02-XX) — Per-row ORPHAN / PARTIAL / STALE-bot source
// badges removed (operator feedback: contradictory + redundant once the
// reconciler auto-heals these within the same tick). Aggregate counts
// are surfaced via the panel-header pill (now `driftFailureCounts` —
// only renders on unresolved zombies, v19.34.24). The
// `g.source` value is still used by the `Reconcile N` button to find
// orphan + partial groups that need user action.

const groupBySymbolDirection = (open) => {
  const buckets = new Map();  // key: `${symbol}|${direction}` → { symbol, direction, members: [...] }
  for (const p of open) {
    if (!p || !p.symbol) continue;
    const dir = (p.direction || p.side || 'long').toLowerCase();
    const key = `${p.symbol.toUpperCase()}|${dir}`;
    if (!buckets.has(key)) {
      buckets.set(key, { symbol: p.symbol, direction: dir, key, members: [] });
    }
    buckets.get(key).members.push(p);
  }

  // Build aggregate row per bucket
  return Array.from(buckets.values()).map(bucket => {
    const members = bucket.members;
    const single = members.length === 1;

    // Sum/aggregate fields. For weighted entry, use cost-basis math.
    let totalShares = 0;
    let totalNotional = 0;   // Σ shares × entry
    let totalPnl = 0;
    let worstSource = 'bot'; // any non-bot source dominates
    let anyTracked = false;
    let unclaimedShares = 0; // for partial rows
    // v19.34.59 (2026-02-XX) — Zombie awareness. Pre-fix the aggregator
    // summed `m.shares ?? m.remaining_shares`, so a BotTrade that had
    // been silently drained (`remaining_shares=0`, `status=OPEN`) still
    // contributed its `original_shares` count to the panel total —
    // operator saw `1252sh COIN (2×)` while the bot actually believed
    // it had 0sh. Flipped the precedence: prefer `remaining_shares`
    // so zombies render as 0sh; fall back to `shares` only when
    // `remaining_shares` is null/undefined (e.g. IB-orphan rows that
    // haven't been reconciled yet). `?? ` (nullish coalescing) keeps
    // the literal `0` value instead of falling through to `shares`.
    let zombieMembers = 0;
    for (const m of members) {
      const sh = Number(m.remaining_shares ?? m.shares ?? 0) || 0;
      const ent = Number(m.entry_price ?? m.fill_price ?? 0) || 0;
      totalShares += Math.abs(sh);
      totalNotional += Math.abs(sh) * ent;
      totalPnl += Number(m.unrealized_pnl ?? m.pnl ?? 0) || 0;
      if (m.source && m.source !== 'bot' && worstSource === 'bot') worstSource = m.source;
      if (m.source === 'bot') anyTracked = true;
      if (m.source === 'ib' || m.source === 'partial') {
        unclaimedShares += Math.abs(Number(m.unclaimed_shares ?? m.shares ?? 0)) || 0;
      }
      // Zombie = status=OPEN but remaining_shares=0 with non-zero original.
      const origSh = Number(m.original_shares ?? m.shares ?? 0) || 0;
      const remSh = Number(m.remaining_shares ?? 0) || 0;
      if (origSh > 0 && remSh === 0) zombieMembers += 1;
    }
    const avgEntry = totalShares > 0 ? totalNotional / totalShares : 0;

    // Pick a representative for fields shared across the group
    // (current_price, target_prices, stop_price, trail state, etc.).
    // We sort so the bot-tracked, freshest record comes first.
    const sorted = [...members].sort((a, b) => {
      const aBot = a.source === 'bot' ? 1 : 0;
      const bBot = b.source === 'bot' ? 1 : 0;
      if (aBot !== bBot) return bBot - aBot;
      const aTime = new Date(a.entry_time || a.executed_at || 0).getTime();
      const bTime = new Date(b.entry_time || b.executed_at || 0).getTime();
      return bTime - aTime;
    });
    const rep = sorted[0];

    return {
      ...rep,
      symbol: bucket.symbol,
      direction: bucket.direction,
      shares: totalShares,
      entry_price: avgEntry,
      pnl: totalPnl,
      unrealized_pnl: totalPnl,
      source: worstSource,
      _group_key: bucket.key,
      _members: members,
      _is_single: single,
      _has_tracked_partner: anyTracked,
      _unclaimed_shares: unclaimedShares,
      _zombie_members: zombieMembers,
    };
  });
};

// Inline mini-row used inside an expanded group to show each underlying
// bot trade. Compact — just enough so operator can tell which bracket
// is which (SMB grade, fill price, current SL, share size).
const GroupMemberRow = ({ member, idx }) => {
  const dir = (member.direction || '').toLowerCase();
  const pnl = Number(member.unrealized_pnl ?? member.pnl ?? 0) || 0;
  const pnlColor = pnl >= 0 ? 'v5-up' : 'v5-down';
  const stop = (member.trailing_stop_state?.current_stop) || member.stop_price;
  const targets = Array.isArray(member.target_prices) && member.target_prices.length > 0
    ? member.target_prices
    : (member.target_price != null ? [member.target_price] : []);
  return (
    <div
      data-testid={`group-member-${member.symbol}-${idx}`}
      className="px-2 py-1.5 ml-4 my-1 border-l-2 border-zinc-800 bg-zinc-950/40 text-[14px]"
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2 v5-mono text-zinc-300">
          <span className="text-zinc-500">#{idx + 1}</span>
          <span>{Math.round(Math.abs(Number(member.shares ?? 0)))}sh</span>
          <span className="text-zinc-500">@</span>
          <span>${formatPx(member.entry_price)}</span>
          {showGradeChip(unifiedGrade(member)) && !isScalpPosition(member) && (
            <span className="px-1 py-0 bg-zinc-800 text-zinc-400 text-[12px] uppercase rounded">
              TQS {unifiedGrade(member)}
            </span>
          )}
          {(member.setup_variant || member.setup_type) && (
            <span className="text-zinc-500 truncate max-w-[120px]">
              {humanizeStyle(member.setup_variant || member.setup_type)}
            </span>
          )}
        </div>
        <span className={`v5-mono ${pnlColor}`}>
          {formatUsd(pnl)}
        </span>
      </div>
      <div className="flex items-center gap-3 mt-0.5 text-[13px] text-zinc-500">
        {stop != null && <span>SL ${formatPx(stop)}</span>}
        {targets.length > 0 && <span>PT ${formatPx(targets[0])}</span>}
        {member.risk_reward_ratio != null && (
          <span>R:R {Number(member.risk_reward_ratio).toFixed(1)}</span>
        )}
      </div>
    </div>
  );
};


export const OpenPositionsV5 = ({ positions, totalPnl, loading, onSelectPosition }) => {
  const open = useMemo(
    () => (positions || []).filter(p => p && p.status !== 'closed'),
    [positions],
  );
  // v19.27 — group by (symbol, direction) and surface aggregate rows.
  const groups = useMemo(() => groupBySymbolDirection(open), [open]);
  const [expandedKey, setExpandedKey] = useState(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);
  const [reconcileMsg, setReconcileMsg] = useState(null);

  // v19.34.56 (2026-02-XX) — Loading-state grace timeout. Operator
  // feedback: panel was getting stuck on "Loading positions…" when
  // the parent feed produced an empty positions array but never
  // flipped its `positionsLoading` flag (e.g. pre-market when the
  // backend has nothing to send). The component now self-defuses
  // the loading state after `LOADING_GRACE_MS` so the operator sees
  // a clean "No open positions" instead of a phantom spinner.
  // The grace timer also resets the moment we see ANY non-empty
  // positions arrive, so a slow first load doesn't get cut short.
  const LOADING_GRACE_MS = 3000;
  const [loadingTimedOut, setLoadingTimedOut] = useState(false);
  const mountedAtRef = useRef(Date.now());
  useEffect(() => {
    if (!loading) {
      // Parent already says "done" — clear any prior timeout state.
      setLoadingTimedOut(false);
      return undefined;
    }
    if (groups.length > 0) {
      // We have data; ignore loading flag from parent regardless.
      setLoadingTimedOut(false);
      return undefined;
    }
    // loading=true AND empty — start the grace timer.
    const elapsed = Date.now() - mountedAtRef.current;
    const remaining = Math.max(0, LOADING_GRACE_MS - elapsed);
    const id = setTimeout(() => setLoadingTimedOut(true), remaining);
    return () => clearTimeout(id);
  }, [loading, groups.length]);
  const showLoading = loading && !loadingTimedOut && groups.length === 0;
  const showEmpty = !showLoading && groups.length === 0;

  const handleToggle = (key) => {
    setExpandedKey((prev) => (prev === key ? null : key));
  };

  // v19.27 — Reconcile target = ORPHANS (`source: 'ib'`) + PARTIAL
  // unclaimed remainders. Both render as orphan-style rows with
  // amber/orange badges and need bot management.
  const reconcileTargets = useMemo(
    () => groups.filter(g => g.source === 'ib' || g.source === 'partial'),
    [groups],
  );
  const reconcileCount = reconcileTargets.length;

  // v19.34.23 (2026-02-XX) — Aggregate auto-heal count surfaced ONCE in
  // the panel header (replaces per-row ORPHAN / STALE / RECONCILED
  // badges).
  //
  // v19.34.24 (May 2026) — Operator feedback: even the subtle "auto-heal · N"
  // pill was visual noise because it lit up on EVERY routine heal (the bot
  // adopts orphans + sweeps stale-bot phantoms within a single tick, so the
  // pill was effectively a fixture). The pill now renders ONLY when an
  // auto-heal has FAILED or remained UNRESOLVED — defined as one or more
  // bot_trade "zombies" persisting across groups (status=OPEN but
  // remaining_shares=0 → the bot thought it had shares, they're gone, and
  // the reconciler couldn't close the gap on its own). That is the rare
  // case where the operator genuinely needs to look. Routine adoptions
  // (entered_by=reconciled_external) and in-flight stale-bot heals are
  // intentionally NOT counted here — they have their own dedicated
  // surfaces: prior_verdict_conflict CONFLICT chip + the expanded
  // "Reconciled from IB orphan" callout for the former, and the
  // Reconcile N button for orphan/partial groups that need user action.
  const driftFailureCounts = useMemo(() => {
    let zombies = 0;          // failed heals — bot has OPEN trade, 0 shares
    let zombieSymbols = [];
    for (const g of groups) {
      const z = Number(g._zombie_members || 0);
      if (z > 0) {
        zombies += z;
        zombieSymbols.push(`${g.symbol} (${z})`);
      }
    }
    return { zombies, zombieSymbols, total: zombies };
  }, [groups]);

  const handleReconcile = async () => {
    if (reconcileBusy) return;
    const symbols = reconcileTargets.map(g => g.symbol).filter(Boolean);
    if (symbols.length === 0) return;
    const ok = typeof window !== 'undefined'
      ? window.confirm(
          `Reconcile ${symbols.length} position${symbols.length > 1 ? 's' : ''} (${symbols.join(', ')})?\n\n` +
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
        const skipped = data.skipped || [];
        const nSkip = skipped.length;
        // 2026-05-04 v19.31.6 — surface per-symbol skip reasons. The
        // backend always returns `skipped: [{symbol, reason}, ...]`
        // (see services/position_reconciler.py:594). Pre-fix we threw
        // it away; operator could only see "skipped 1" with no clue
        // why. Now: build a compact inline list + a full tooltip.
        const REASON_LABELS = {
          already_tracked: 'already tracked',
          no_ib_position: 'no IB position',
          invalid_avg_cost: 'invalid avg cost',
          direction_unstable: 'direction unstable',
          stop_already_breached: 'stop already breached',
          closed_outside_bot: 'closed outside bot',
          direction_changed: 'direction changed',
        };
        const formatSkip = (s) => {
          const reason = REASON_LABELS[s.reason] || s.reason || 'unknown';
          return `${s.symbol} (${reason})`;
        };
        const skipDetail = nSkip > 0
          ? `Reconciled ${nRec}, skipped ${nSkip}: ${skipped.map(formatSkip).join(', ')}`
          : `Reconciled ${nRec}`;
        setReconcileMsg({
          kind: 'ok',
          text: skipDetail.length > 90 ? `${skipDetail.slice(0, 87)}…` : skipDetail,
          tooltip: skipDetail,
        });
      }
    } catch (err) {
      setReconcileMsg({ kind: 'error', text: String(err?.message || err) });
    } finally {
      setReconcileBusy(false);
      // 2026-05-04 v19.31.6 — bumped 6s → 30s so operator can actually
      // read the skip-reason breakdown (was disappearing too fast).
      setTimeout(() => setReconcileMsg(null), 30000);
    }
  };

  return (
    <div data-testid="v5-open-positions" data-help-id="open-positions" className="flex flex-col flex-1 min-h-0 h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="v5-panel-title">Open ({groups.length})</div>
          {/* v19.34.2 — `?` legend popover explaining REAL/SHADOW/MIXED
              + quote freshness chip semantics. Anchored next to the
              panel title so the operator's "what is what?" answer is
              one click away. */}
          <OpenPositionsLegend />
          <LiveDataChip compact />
          {reconcileCount > 0 && (
            <button
              type="button"
              onClick={handleReconcile}
              disabled={reconcileBusy}
              data-testid="open-positions-reconcile-btn"
              className={`px-2 py-0.5 text-[13px] uppercase tracking-wider rounded border transition-colors ${
                reconcileBusy
                  ? 'border-zinc-700 text-zinc-500 cursor-wait'
                  : 'border-amber-700/60 text-amber-300 hover:bg-amber-950/40'
              }`}
              title={`Reconcile ${reconcileCount} untracked position${reconcileCount > 1 ? 's' : ''}`}
            >
              {reconcileBusy ? 'Reconciling…' : `Reconcile ${reconcileCount}`}
            </button>
          )}
          {/* v19.34.23 (2026-02-XX) — Subtle auto-heal pill that replaced
              the loud per-row ORPHAN / STALE / RECONCILED badges.
              v19.34.24 (May 2026) — Operator follow-up: the pill was still
              firing on every routine heal (basically all the time). It now
              renders ONLY when an auto-heal has FAILED — i.e. a bot_trade
              zombie persists (status=OPEN, remaining_shares=0). Routine
              healing is now silent; this pill is loud (amber + pulse)
              because if it shows up, something the reconciler couldn't fix
              on its own is sitting on the book. */}
          {driftFailureCounts.total > 0 && (
            <span
              data-testid="open-positions-drift-failure-pill"
              data-zombies={driftFailureCounts.zombies}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[13px] uppercase tracking-wider rounded border border-amber-700/70 bg-amber-950/40 text-amber-300 font-semibold animate-pulse cursor-help"
              title={[
                '⚠ Auto-heal FAILED — reconciler could not close the gap on its own.',
                `· ${driftFailureCounts.zombies} zombie bot_trade(s) (status=OPEN, remaining_shares=0)`,
                driftFailureCounts.zombieSymbols.length > 0 && `· Symbols: ${driftFailureCounts.zombieSymbols.join(', ')}`,
                '',
                'Operator action: review the affected rows, close manually in TWS, or use Reconcile to materialize fresh state.',
              ].filter(Boolean).join('\n')}
            >
              <span aria-hidden className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
              drift · {driftFailureCounts.total}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {reconcileMsg && (
            <span
              data-testid="open-positions-reconcile-msg"
              className={`text-[14px] cursor-help ${reconcileMsg.kind === 'ok' ? 'text-emerald-300' : 'text-rose-300'}`}
              title={reconcileMsg.tooltip || reconcileMsg.text}
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
        {showLoading && (
          <div className="px-3 py-4 text-[13px] text-zinc-500" data-testid="open-positions-loading">Loading positions…</div>
        )}
        {showEmpty && (
          <div className="px-3 py-4 text-[13px] text-zinc-500" data-testid="open-positions-empty">No open positions.</div>
        )}
        {groups.map(g => {
          const isExpanded = expandedKey === g._group_key;
          const memberCount = g._members.length;
          return (
            <div
              key={g._group_key}
              data-testid={`v5-open-group-${g.symbol}-${g.direction}`}
            >
              <PositionRow
                position={g}
                expanded={isExpanded}
                onToggle={() => handleToggle(g._group_key)}
                onClick={() => onSelectPosition?.(g)}
                memberCount={memberCount}
              />
              {isExpanded && memberCount > 1 && (
                <div
                  data-testid={`group-members-${g.symbol}`}
                  className="bg-zinc-950/30 pb-1"
                >
                  <div className="px-2 pt-1 text-[13px] uppercase tracking-wider text-zinc-600">
                    {memberCount} underlying bot trades
                  </div>
                  {g._members.map((m, idx) => (
                    <GroupMemberRow key={m.trade_id || m.id || idx} member={m} idx={idx} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default OpenPositionsV5;
