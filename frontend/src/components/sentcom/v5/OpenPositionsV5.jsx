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
import TradeTypeChip from './TradeTypeChip';
// v19.34.2 (2026-05-04) — quote-freshness chip + legend popover.
import QuoteFreshnessChip from './QuoteFreshnessChip';
import OpenPositionsLegend from './OpenPositionsLegend';
// v19.34.11 (2026-05-06) — bracket lifecycle history panel.
import BracketHistoryPanel from './BracketHistoryPanel';

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


const PositionRow = ({ position, onClick, expanded, onToggle, sourceBadge, memberCount }) => {
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
          {/* 2026-05-04 — ORPHAN/PARTIAL/STALE badge moved inline to the
              left cluster so it stops overlapping the right-aligned PnL.
              Multi-trade count rendered next to it. */}
          {memberCount > 1 && (
            <span
              data-testid={`group-multi-badge-${position.symbol}`}
              className="px-1 py-0 text-[9px] uppercase tracking-wider bg-zinc-800 text-zinc-300 border border-zinc-700 rounded"
              title={`${memberCount} bot trades aggregated`}
            >
              {memberCount}×
            </span>
          )}
          {sourceBadge && (
            <span
              data-testid={`group-source-badge-${position.symbol}`}
              className={`px-1 py-0 text-[9px] uppercase tracking-wider border rounded ${sourceBadge.color}`}
              title={sourceBadge.title}
            >
              {sourceBadge.label}
            </span>
          )}
          {/* v19.31.13 — trade origin chip (PAPER amber, LIVE red, SHADOW sky).
              v19.34.1 — render even when type is "unknown" so the operator
              never has a row without a mode tag. The pusher-account
              fallback in sentcom_service should normally fill this in. */}
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
              can currently fire stops on this position (FRESH / AMBER /
              STALE) so the operator never has to guess if a row is
              actively protected. */}
          <QuoteFreshnessChip
            state={position.quote_state}
            ageSeconds={position.quote_age_s}
            size="xs"
            testIdSuffix={`open-pos-${position.symbol}`}
          />
          {/* v19.34.3 — provenance chip. Distinguishes RECONCILED
              (orphan adoption — bot did not open this) from BOT
              (bot's own evaluation + execution). Operator-discovered
              VALE bug: synthetic SL/PT didn't reflect bot's prior
              REJECT verdicts. */}
          {position.entered_by === 'reconciled_external' && (
            <span
              data-testid={`provenance-chip-${position.symbol}`}
              className="px-1.5 py-0 text-[10px] uppercase tracking-wider rounded border bg-fuchsia-950/60 text-fuchsia-300 border-fuchsia-800 font-bold"
              title={
                position.synthetic_source === 'last_verdict'
                  ? 'RECONCILED — Bot did not open this. SL/PT pulled from bot\'s last verdict numbers.'
                  : 'RECONCILED — Bot did not open this. SL/PT are synthetic defaults (e.g. 2% from avg cost).'
              }
            >
              RECONCILED
            </span>
          )}
          {/* v19.34.3 — prior-verdict-conflict warning chip. Triggered
              when ≥2 of the bot's last 3 verdicts on this symbol/setup
              were REJECT, yet the position was reconciled anyway. */}
          {position.prior_verdict_conflict && (
            <span
              data-testid={`prior-verdict-conflict-chip-${position.symbol}`}
              className="px-1.5 py-0 text-[10px] uppercase tracking-wider rounded border bg-amber-950/70 text-amber-300 border-amber-700 font-bold animate-pulse"
              title="Bot's recent verdicts on this setup were REJECT — this position contradicts the bot's own logic. Consider closing manually or overriding SL/PT."
            >
              ⚠ CONFLICT
            </span>
          )}
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
          {/* v19.34.3 — Reconcile-conflict callout. Renders ONLY when
              entered_by=reconciled_external AND prior verdicts exist.
              Shows the bot's last verdict (REJECT / R:R / setup_type)
              so the operator never silently inherits a bad setup. */}
          {position.entered_by === 'reconciled_external' && (
            <div
              data-testid={`reconcile-callout-${position.symbol}`}
              className={`px-2 py-1.5 rounded border text-[11px] leading-snug ${
                position.prior_verdict_conflict
                  ? 'bg-amber-950/40 border-amber-800/60 text-amber-200'
                  : 'bg-fuchsia-950/30 border-fuchsia-800/40 text-fuchsia-200'
              }`}
            >
              <div className="font-bold uppercase tracking-wider text-[10px] mb-0.5">
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
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                    Last {Math.min(3, position.prior_verdicts.length)} verdict(s)
                  </div>
                  {position.prior_verdicts.slice(0, 3).map((v, i) => (
                    <div key={i} className="font-mono text-[10px] text-zinc-400">
                      {v.timestamp ? new Date(v.timestamp).toLocaleTimeString('en-US', {hour12: false}) + ' · ' : ''}
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

          {/* v19.34.11 — Bracket lifecycle history (lazy-loaded on click) */}
          <BracketHistoryPanel
            tradeId={position.trade_id || position.id}
            symbol={position.symbol}
          />
        </div>
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

const SOURCE_BADGE = {
  ib:        { label: 'ORPHAN',  color: 'bg-amber-900/40 text-amber-300 border-amber-800/60' },
  partial:   { label: 'PARTIAL', color: 'bg-orange-900/40 text-orange-300 border-orange-800/60' },
  stale_bot: { label: 'STALE',   color: 'bg-rose-900/40 text-rose-300 border-rose-800/60' },
  bot:       null,  // no badge for clean tracking
};

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
    for (const m of members) {
      const sh = Number(m.shares ?? m.remaining_shares ?? 0) || 0;
      const ent = Number(m.entry_price ?? m.fill_price ?? 0) || 0;
      totalShares += Math.abs(sh);
      totalNotional += Math.abs(sh) * ent;
      totalPnl += Number(m.unrealized_pnl ?? m.pnl ?? 0) || 0;
      if (m.source && m.source !== 'bot' && worstSource === 'bot') worstSource = m.source;
      if (m.source === 'bot') anyTracked = true;
      if (m.source === 'ib' || m.source === 'partial') {
        unclaimedShares += Math.abs(Number(m.unclaimed_shares ?? m.shares ?? 0)) || 0;
      }
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
      className="px-2 py-1.5 ml-4 my-1 border-l-2 border-zinc-800 bg-zinc-950/40 text-[11px]"
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2 v5-mono text-zinc-300">
          <span className="text-zinc-500">#{idx + 1}</span>
          <span>{Math.round(Math.abs(Number(member.shares ?? 0)))}sh</span>
          <span className="text-zinc-500">@</span>
          <span>${formatPx(member.entry_price)}</span>
          {member.smb_grade && (
            <span className="px-1 py-0 bg-zinc-800 text-zinc-400 text-[9px] uppercase rounded">
              SMB {member.smb_grade}
            </span>
          )}
          {member.setup_type && (
            <span className="text-zinc-500 truncate max-w-[120px]">
              {humanizeStyle(member.setup_type)}
            </span>
          )}
        </div>
        <span className={`v5-mono ${pnlColor}`}>
          {formatUsd(pnl)}
        </span>
      </div>
      <div className="flex items-center gap-3 mt-0.5 text-[10px] text-zinc-500">
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
    <div data-testid="v5-open-positions" data-help-id="open-positions" className="flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
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
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border transition-colors ${
                reconcileBusy
                  ? 'border-zinc-700 text-zinc-500 cursor-wait'
                  : 'border-amber-700/60 text-amber-300 hover:bg-amber-950/40'
              }`}
              title={`Reconcile ${reconcileCount} untracked position${reconcileCount > 1 ? 's' : ''}`}
            >
              {reconcileBusy ? 'Reconciling…' : `Reconcile ${reconcileCount}`}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {reconcileMsg && (
            <span
              data-testid="open-positions-reconcile-msg"
              className={`text-[11px] cursor-help ${reconcileMsg.kind === 'ok' ? 'text-emerald-300' : 'text-rose-300'}`}
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
        {loading && groups.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">Loading positions…</div>
        )}
        {!loading && groups.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">No open positions.</div>
        )}
        {groups.map(g => {
          const isExpanded = expandedKey === g._group_key;
          const sourceBadgeRaw = SOURCE_BADGE[g.source];
          const memberCount = g._members.length;
          // 2026-05-04 — sourceBadge now inlined into PositionRow's left
          // cluster (was an absolute overlay on the right that obscured
          // live PnL). Build the title/tooltip here so PositionRow stays
          // dumb about source semantics.
          const sourceBadge = sourceBadgeRaw
            ? {
                ...sourceBadgeRaw,
                title:
                  g.source === 'partial'
                    ? `Bot tracks ${(g._members.find(m => m.source === 'bot')?.shares) ?? 0}sh, IB has more — ${g._unclaimed_shares}sh untracked`
                    : g.source === 'stale_bot'
                    ? 'Bot tracks shares IB does not show — phantom shares, will auto-sweep'
                    : 'IB position with no bot tracking — click Reconcile to claim',
              }
            : null;
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
                sourceBadge={sourceBadge}
                memberCount={memberCount}
              />
              {isExpanded && memberCount > 1 && (
                <div
                  data-testid={`group-members-${g.symbol}`}
                  className="bg-zinc-950/30 pb-1"
                >
                  <div className="px-2 pt-1 text-[10px] uppercase tracking-wider text-zinc-600">
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
