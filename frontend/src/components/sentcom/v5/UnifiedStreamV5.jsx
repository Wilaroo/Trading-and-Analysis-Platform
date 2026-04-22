/**
 * V5 UnifiedStream — stream panel with severity-coloured left borders matching
 * option-1-v5-command-center.html. Each item gets a colour by event kind:
 *
 *   order  → yellow   (bracket queued / order sent)
 *   fill   → blue     (filled / stop trailed)
 *   win    → green    (PT hit / closed W)
 *   loss   → red      (SL hit / closed L)
 *   skip   → zinc     (gate veto / SKIP)
 *   brain  → violet   (gate decision / AI thought)
 *   info   → slate    (fallback)
 */
import React, { useCallback, useMemo, useState } from 'react';

const TIME_COLOR_BY_SEV = {
  order: 'text-yellow-400',
  fill:  'text-blue-400',
  win:   'text-emerald-400',
  loss:  'text-rose-400',
  skip:  'text-zinc-400',
  brain: 'text-violet-400',
  info:  'text-slate-400',
};

const BOT_TAG_COLOR_BY_SEV = {
  order: 'text-yellow-400',
  fill:  'text-blue-400',
  win:   'text-emerald-400',
  loss:  'text-rose-400',
  skip:  'text-zinc-500',
  brain: 'text-violet-400',
  info:  'text-slate-400',
};

const classifyMessage = (msg) => {
  const kind = (msg.event || msg.kind || msg.type || msg.severity || '').toLowerCase();
  const text = (msg.text || msg.message || msg.summary || '').toLowerCase();
  if (kind.includes('order') || kind.includes('queued') || kind.includes('bracket')) return 'order';
  if (kind.includes('fill') || kind.includes('trail') || kind.includes('stop_moved')) return 'fill';
  if (kind.includes('win') || (kind.includes('close') && (text.includes('pt') || text.includes('+$') || text.includes('+r')))) return 'win';
  if (kind.includes('loss') || (kind.includes('close') && (text.includes('sl') || text.includes('-$') || text.includes('stopped')))) return 'loss';
  if (kind.includes('skip') || kind.includes('veto') || kind.includes('block')) return 'skip';
  if (kind.includes('gate') || kind.includes('brain') || kind.includes('ai_') || kind.includes('decision')) return 'brain';
  if (text.includes('skip')) return 'skip';
  if (text.includes('gate') || text.includes('consensus')) return 'brain';
  return 'info';
};

const formatTimestamp = (iso) => {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
};

const formatHeadline = (msg) => {
  const sym = msg.symbol || msg.ticker;
  const event = msg.event || msg.kind || msg.type || '';
  if (sym && event) return `${sym} · ${event.replace(/_/g, ' ').toLowerCase()}`;
  return msg.headline || msg.title || event || 'event';
};

const formatRight = (msg, sev) => {
  if (msg.r_multiple != null) {
    const r = Number(msg.r_multiple);
    return { text: `${r >= 0 ? '+' : ''}${r.toFixed(2)}R`, color: r >= 0 ? 'v5-up' : 'v5-down' };
  }
  if (msg.realized_pnl != null) {
    const p = Number(msg.realized_pnl);
    return { text: `${p >= 0 ? '+$' : '−$'}${Math.abs(p).toFixed(0)}`, color: p >= 0 ? 'v5-up' : 'v5-down' };
  }
  if (msg.gate_score != null) {
    return { text: `${msg.gate_score >= 60 ? 'GO' : 'HOLD'} ${msg.gate_score}`, color: sev === 'brain' ? 'v5-up font-bold' : '' };
  }
  if (msg.price != null) {
    return { text: `@ ${Number(msg.price).toFixed(2)}`, color: 'v5-mono' };
  }
  return null;
};


const StreamRow = ({ msg }) => {
  const sev = classifyMessage(msg);
  const time = formatTimestamp(msg.timestamp || msg.created_at || msg.time);
  const headline = formatHeadline(msg);
  const right = formatRight(msg, sev);
  const body = msg.summary || msg.text || msg.message || msg.note || '';

  return (
    <div className={`v5-stream-item sev-${sev}`} data-testid={`v5-stream-item-${sev}`}>
      <div className="flex items-center justify-between gap-2 text-[10px] v5-mono">
        <span className="min-w-0 truncate">
          {time && <span className={TIME_COLOR_BY_SEV[sev]}>{time}</span>}
          {' '}
          <b className="text-zinc-200">{headline}</b>
        </span>
        {right && <span className={`shrink-0 v5-mono ${right.color || ''}`}>{right.text}</span>}
      </div>
      {body && (
        <div className="v5-why mt-0.5">
          <span className={`${BOT_TAG_COLOR_BY_SEV[sev]} font-semibold`}>Bot:</span>{' '}
          <span className="text-zinc-400">{body}</span>
        </div>
      )}
    </div>
  );
};


export const UnifiedStreamV5 = ({ messages, loading }) => {
  // Stage 2d-C — filter chips matching the mockup. Multi-select: unlocked
  // defaults to "all". Clicking a chip toggles it.
  const [filters, setFilters] = useState(() => new Set());
  const toggle = useCallback((k) => {
    setFilters(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  }, []);

  const filtered = useMemo(() => {
    if (!messages || filters.size === 0) return messages || [];
    return messages.filter(m => filters.has(classifyMessage(m)));
  }, [messages, filters]);

  const filterOptions = [
    { key: 'scan',  label: 'scan' },
    { key: 'brain', label: 'eval' },   // brain = gate / ai decision
    { key: 'order', label: 'order' },
    { key: 'fill',  label: 'fill' },
    { key: 'win',   label: 'win' },
    { key: 'loss',  label: 'loss' },
    { key: 'skip',  label: 'skip' },
  ];

  if (loading && (!messages || messages.length === 0)) {
    return (
      <div className="px-3 py-6 text-center text-[11px] text-zinc-500">Loading stream…</div>
    );
  }
  if (!messages || messages.length === 0) {
    return (
      <div className="flex flex-col">
        <StreamFilterBar filters={filters} toggle={toggle} options={filterOptions} />
        <div className="px-3 py-6 text-center text-[11px] text-zinc-500">
          <div className="v5-mono">No stream events yet.</div>
          <div className="mt-1 v5-why-dim">Scanner · gate decisions · fills · closes will flow here in real time.</div>
        </div>
      </div>
    );
  }
  return (
    <div data-testid="v5-unified-stream" className="flex flex-col">
      <StreamFilterBar filters={filters} toggle={toggle} options={filterOptions} />
      {filtered.map((m, i) => (
        <StreamRow key={m.id || m._id || `${m.timestamp || i}-${i}`} msg={m} />
      ))}
      {filtered.length === 0 && filters.size > 0 && (
        <div className="px-3 py-4 text-center text-[11px] text-zinc-500 v5-why-dim">
          No events match the selected filter{filters.size > 1 ? 's' : ''}.
        </div>
      )}
    </div>
  );
};


const StreamFilterBar = ({ filters, toggle, options }) => (
  <div className="flex items-center gap-1 px-3 py-1.5 border-b border-zinc-900 bg-zinc-950/80 sticky top-0 z-10">
    <span className="v5-mono text-[9px] v5-dim uppercase tracking-widest mr-1">filter:</span>
    {options.map(o => (
      <button
        key={o.key}
        data-testid={`v5-stream-filter-${o.label}`}
        onClick={() => toggle(o.key)}
        className={`v5-filter-chip ${filters.has(o.key) ? 'active' : ''}`}
      >
        {o.label}
      </button>
    ))}
  </div>
);

export default UnifiedStreamV5;
