/**
 * V5 ScannerCards — unified live feed of setups / alerts / open positions /
 * recently closed trades, styled to match option-1-v5-command-center.html.
 *
 * Each card shows:
 *   - Symbol + stage chip
 *   - Mini 5-stage pipeline bar (scan → eval → order → manage → close)
 *   - Bot narrative (if any)
 *   - Gate score / P(win) / Sharpe metrics
 *
 * This component is purely presentational — it takes the setups / alerts /
 * positions / messages arrays that the existing SentCom hooks already
 * produce and folds them into a single ranked list.
 */
import React, { useMemo } from 'react';

const STAGE_ORDER = ['scan', 'eval', 'order', 'manage', 'close'];
const STAGE_CLASS = {
  scan:   'v5-chip-scan',
  eval:   'v5-chip-eval',
  order:  'v5-chip-order',
  manage: 'v5-chip-manage',
  close:  'v5-chip-close',
  veto:   'v5-chip-veto',
};

const BOT_TEXT_COLOR = {
  scan: 'text-violet-400',
  eval: 'text-blue-400',
  order: 'text-yellow-400',
  manage: 'text-emerald-400',
  close: 'text-slate-400',
  veto: 'text-red-400',
};

const Mini5Stage = ({ stage, closedOutcome }) => {
  const idx = STAGE_ORDER.indexOf(stage);
  const isVeto = stage === 'veto';
  return (
    <div className="v5-mini-5stage">
      {STAGE_ORDER.map((s, i) => {
        if (isVeto && (s === 'eval' || s === 'scan')) return <span key={s} className={`on-${s}`} />;
        if (isVeto && i >= 2) return <span key={s} className="on-veto" />;
        if (i <= idx) {
          // On CLOSE, colour the final block red/green to encode win/loss
          if (s === 'close' && closedOutcome) {
            return <span key={s} className={closedOutcome === 'win' ? 'on-manage' : 'on-veto'} />;
          }
          return <span key={s} className={`on-${s}`} />;
        }
        return <span key={s} />;
      })}
    </div>
  );
};

const formatPct = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : `${(Number(v) * 100).toFixed(0)}%`;
const formatNum = (v, d = 2) => (v == null || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(d);
const formatPriceChange = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

/**
 * Reduce the raw hook arrays into an ordered list of display cards.
 * Later stages outrank earlier: close > manage > order > eval > scan.
 * Within same stage, most recent first.
 */
const buildCards = ({ setups, alerts, positions, messages }) => {
  const bySymbol = new Map();

  // 1. Scanner setups — stage=scan (or eval if has confidence_score)
  (setups || []).forEach((s) => {
    const sym = (s.symbol || s.ticker || '').toUpperCase();
    if (!sym) return;
    const stage = s.gate_score != null || s.confidence != null ? 'eval' : 'scan';
    const existing = bySymbol.get(sym);
    const card = {
      symbol: sym,
      stage,
      stage_note: s.setup_type || s.type || 'setup',
      change_pct: s.change_pct ?? s.relative_change ?? null,
      bot_text: s.bot_note || s.narrative || `${s.setup_type || 'setup'} flagged${s.confidence ? ` · conf ${formatPct(s.confidence)}` : ''}${s.relative_volume ? ` · RVol ${formatNum(s.relative_volume, 1)}×` : ''}.`,
      metrics: {
        gate: s.gate_score,
        p_win: s.p_win ?? s.confidence,
        sharpe: s.sharpe,
      },
      timestamp: s.timestamp || s.detected_at || s.created_at,
    };
    if (!existing || STAGE_ORDER.indexOf(card.stage) >= STAGE_ORDER.indexOf(existing.stage)) {
      bySymbol.set(sym, card);
    }
  });

  // 2. Alerts — stage=eval (or veto if blocked)
  (alerts || []).forEach((a) => {
    const sym = (a.symbol || a.ticker || '').toUpperCase();
    if (!sym) return;
    const blocked = a.blocked || a.vetoed;
    const stage = blocked ? 'veto' : (a.gate_score ? 'eval' : 'scan');
    const existing = bySymbol.get(sym);
    const card = {
      symbol: sym,
      stage,
      stage_note: a.alert_type || a.setup_type || 'alert',
      change_pct: a.change_pct ?? null,
      bot_text: a.reason || a.note || `${a.setup_type || 'alert'} · ${a.direction || ''}${a.gate_score ? ` · gate ${a.gate_score}` : ''}`,
      metrics: {
        gate: a.gate_score,
        p_win: a.p_win,
        sharpe: a.sharpe,
      },
      timestamp: a.timestamp || a.created_at,
    };
    if (!existing || STAGE_ORDER.indexOf(card.stage) >= STAGE_ORDER.indexOf(existing.stage) || blocked) {
      bySymbol.set(sym, card);
    }
  });

  // 3. Open positions — stage=manage (overrides earlier stages)
  (positions || []).forEach((p) => {
    const sym = (p.symbol || p.ticker || '').toUpperCase();
    if (!sym) return;
    const dir = (p.direction || p.side || '').toLowerCase();
    const pnlR = p.pnl_r ?? p.r_multiple ?? p.unrealized_r;
    const pnlUsd = p.unrealized_pnl ?? p.pnl ?? p.pnl_usd;
    // Backend may return `target_prices` (array, one per scale-out) OR
    // `target_price` (legacy scalar). Pick the first usable value.
    const pt = p.target_price ?? (Array.isArray(p.target_prices) ? p.target_prices[0] : null);
    bySymbol.set(sym, {
      symbol: sym,
      stage: 'manage',
      stage_note: `${dir === 'short' ? 'SHORT' : 'LONG'}${p.setup_type ? ' ' + p.setup_type : ''}`,
      change_pct: p.change_pct ?? null,
      bot_text:
        p.bot_note ||
        `Holding ${sym}${p.entry_price ? ` @ ${formatNum(p.entry_price, 2)}` : ''}` +
        `${p.stop_price ? ` · SL ${formatNum(p.stop_price, 2)}` : ''}` +
        `${pt ? ` · PT ${formatNum(pt, 2)}` : ''}.`,
      metrics: {
        gate: p.gate_score,
        p_win: p.p_win,
        sharpe: p.sharpe,
        r: pnlR,
        pnl: pnlUsd,
      },
      timestamp: p.opened_at || p.entry_time,
    });
  });

  // 4. Recently closed trades from messages — stage=close
  (messages || []).slice(0, 50).forEach((m) => {
    const sym = (m.symbol || m.ticker || '').toUpperCase();
    if (!sym) return;
    const kind = (m.event || m.kind || m.type || '').toLowerCase();
    if (!kind.includes('close') && !kind.includes('win') && !kind.includes('loss') && !kind.includes('exit')) return;
    const existing = bySymbol.get(sym);
    // Don't clobber an open position card with a closed message
    if (existing && existing.stage === 'manage') return;
    const outcome = kind.includes('win') || Number(m.realized_pnl) > 0 || Number(m.r_multiple) > 0 ? 'win'
                  : kind.includes('loss') || Number(m.realized_pnl) < 0 || Number(m.r_multiple) < 0 ? 'loss'
                  : null;
    bySymbol.set(sym, {
      symbol: sym,
      stage: 'close',
      stage_note: outcome === 'win' ? 'W' : outcome === 'loss' ? 'L' : '',
      closed_outcome: outcome,
      change_pct: null,
      bot_text: m.summary || m.text || m.message || 'Trade closed.',
      metrics: {
        r: m.r_multiple,
        pnl: m.realized_pnl,
      },
      timestamp: m.timestamp || m.created_at,
    });
  });

  // Rank: later stages first, then by timestamp desc
  return Array.from(bySymbol.values()).sort((a, b) => {
    const da = STAGE_ORDER.indexOf(a.stage);
    const db = STAGE_ORDER.indexOf(b.stage);
    if (da !== db) return db - da;
    return (new Date(b.timestamp || 0)) - (new Date(a.timestamp || 0));
  });
};


const relativeAge = (ts) => {
  if (!ts) return '';
  try {
    const diffS = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
    if (diffS < 60) return `${diffS}s`;
    if (diffS < 3600) return `${Math.floor(diffS / 60)}m`;
    return `${Math.floor(diffS / 3600)}h`;
  } catch { return ''; }
};


const ScannerCard = ({ card, active, onClick }) => {
  const chipClass = STAGE_CLASS[card.stage] || STAGE_CLASS.scan;
  const botColor = BOT_TEXT_COLOR[card.stage] || 'text-zinc-400';
  const hasMetrics = card.metrics && (
    card.metrics.gate != null || card.metrics.p_win != null
    || card.metrics.sharpe != null || card.metrics.r != null
  );
  const change = formatPriceChange(card.change_pct);
  const age = relativeAge(card.timestamp);

  // Stage chip label — mockup shows: "ORDER · 8s", "OPEN", "CLOSED W", "SKIP", "SCAN"
  let chipLabel;
  if (card.stage === 'veto') chipLabel = 'SKIP';
  else if (card.stage === 'manage') chipLabel = 'OPEN';
  else if (card.stage === 'close') chipLabel = card.closed_outcome === 'win' ? 'CLOSED W' : card.closed_outcome === 'loss' ? 'CLOSED L' : 'CLOSED';
  else chipLabel = card.stage.toUpperCase();

  return (
    <div
      data-testid={`v5-scanner-card-${card.symbol}`}
      onClick={onClick}
      className={`v5-scanner-card ${active ? 'active' : ''}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors"
            data-testid={`scanner-card-symbol-${card.symbol}`}
          >
            {card.symbol}
          </span>
          <span className={`v5-chip ${chipClass}`}>
            {chipLabel}{age && card.stage === 'order' ? ` · ${age}` : ''}
          </span>
        </div>
        {change && (
          <span className={`v5-mono text-[11px] font-bold ${Number(card.change_pct) >= 0 ? 'v5-up' : 'v5-down'}`}>
            {card.stage === 'close' && card.metrics?.r != null
              ? `${Number(card.metrics.r) >= 0 ? '+' : ''}${Number(card.metrics.r).toFixed(1)}R`
              : change
            }
          </span>
        )}
      </div>

      <Mini5Stage stage={card.stage} closedOutcome={card.closed_outcome} />

      {card.bot_text && (
        <div className="v5-why mt-2">
          <span className={`${botColor} v5-bot-tag`}>Bot:</span>{' '}
          <span className="text-zinc-200">"{card.bot_text}"</span>
        </div>
      )}

      {hasMetrics && (
        <div className="flex items-center gap-3 mt-2 text-[10px] v5-mono">
          {card.metrics.gate != null && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">gate</span>
              <span className={`font-bold ${card.metrics.gate >= 60 ? 'v5-up' : card.metrics.gate >= 45 ? 'v5-warn' : 'v5-down'}`}>
                {Math.round(card.metrics.gate)}
              </span>
            </div>
          )}
          {card.metrics.p_win != null && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">P(win)</span>
              <span className={`font-bold ${Number(card.metrics.p_win) >= 0.55 ? 'v5-up' : 'v5-down'}`}>
                {formatPct(card.metrics.p_win)}
              </span>
            </div>
          )}
          {card.metrics.sharpe != null && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">Sharpe</span>
              <span className="font-bold text-zinc-200">{formatNum(card.metrics.sharpe, 2)}</span>
            </div>
          )}
          {card.metrics.r != null && card.stage !== 'close' && (
            <div className="flex items-center gap-1">
              <span className="v5-dim">R</span>
              <span className={`font-bold ${Number(card.metrics.r) >= 0 ? 'v5-up' : 'v5-down'}`}>
                {formatNum(card.metrics.r, 2)}
              </span>
            </div>
          )}
          {card.metrics.pnl != null && Math.abs(card.metrics.pnl) > 0 && (
            <span className={`ml-auto font-bold ${Number(card.metrics.pnl) >= 0 ? 'v5-up' : 'v5-down'}`}>
              {Number(card.metrics.pnl) >= 0 ? '+$' : '−$'}{Math.abs(Number(card.metrics.pnl)).toFixed(0)}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export const ScannerCardsV5 = ({
  setups,
  alerts,
  positions,
  messages,
  selectedSymbol,
  onSelectSymbol,
}) => {
  const cards = useMemo(
    () => buildCards({ setups, alerts, positions, messages }),
    [setups, alerts, positions, messages]
  );

  if (cards.length === 0) {
    return (
      <div className="px-3 py-6 text-center text-[11px] text-zinc-500">
        <div className="v5-mono">Scanner idle.</div>
        <div className="mt-1 v5-why-dim">No setups, alerts, or open positions yet.</div>
      </div>
    );
  }

  return (
    <div data-testid="v5-scanner-cards-list" className="flex flex-col">
      {cards.map((c) => (
        <ScannerCard
          key={c.symbol + c.stage}
          card={c}
          active={selectedSymbol === c.symbol}
          onClick={() => onSelectSymbol?.(c.symbol)}
        />
      ))}
    </div>
  );
};

export default ScannerCardsV5;
