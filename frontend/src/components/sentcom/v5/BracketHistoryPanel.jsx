/**
 * BracketHistoryPanel — v19.34.11 (2026-05-06)
 *
 * Lazy-loaded inner panel for `OpenPositionsV5.jsx` expanded row.
 * Shows the full bracket lifecycle for a trade: original bracket →
 * scale-out trim → re-issue → exit, with `reason` chips per event.
 *
 * Backend: `GET /api/trading-bot/bracket-history?trade_id=X`
 * Backend writer: `services/bracket_reissue_service._persist_lifecycle_event`
 */
import React, { useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const REASON_CHIP_CLS = {
  scale_out_t1: 'bg-emerald-950/40 text-emerald-300 border-emerald-800',
  scale_out_t2: 'bg-emerald-950/40 text-emerald-300 border-emerald-800',
  scale_out:    'bg-emerald-950/40 text-emerald-300 border-emerald-800',
  scale_in:     'bg-cyan-950/40 text-cyan-300 border-cyan-800',
  tif_promotion:'bg-violet-950/40 text-violet-300 border-violet-800',
  manual:       'bg-zinc-800 text-zinc-300 border-zinc-700',
};

const reasonChipClass = (reason) => {
  const r = String(reason || '').toLowerCase();
  return REASON_CHIP_CLS[r] || 'bg-zinc-800 text-zinc-300 border-zinc-700';
};

const phaseChip = (phase, success) => {
  const cls = success
    ? 'bg-emerald-950/40 text-emerald-300 border-emerald-800'
    : 'bg-rose-950/40 text-rose-300 border-rose-800';
  return (
    <span className={`px-1.5 py-0.5 rounded border text-[9px] uppercase tracking-wider ${cls}`}>
      {success ? 'OK' : (phase || 'fail')}
    </span>
  );
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return iso;
  }
};

const fmtPx = (n) => {
  if (n == null || isNaN(Number(n))) return '—';
  return `$${Number(n).toFixed(2)}`;
};

const EventRow = ({ event }) => {
  const plan = event.plan || {};
  const targets = Array.isArray(plan.target_price_levels)
    ? plan.target_price_levels.map((p, i) => ({ p, q: (plan.target_qtys || [])[i] }))
    : [];
  return (
    <div
      className="border-l-2 border-zinc-700 pl-2 ml-1 py-1 space-y-0.5"
      data-testid={`bracket-history-event-${event.trade_id || 'unknown'}-${event.created_at_iso || event.created_at}`}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[10px] text-zinc-500 v5-mono">
          {fmtTime(event.created_at_iso || event.created_at)}
        </span>
        <span
          className={`px-1.5 py-0.5 rounded border text-[9px] uppercase tracking-wider ${reasonChipClass(event.reason)}`}
          data-testid={`reason-chip-${event.reason}`}
        >
          {event.reason || 'unknown'}
        </span>
        {phaseChip(event.phase, event.success)}
        {event.error && (
          <span className="text-[10px] text-rose-300 truncate max-w-[180px]" title={event.error}>
            {event.error}
          </span>
        )}
      </div>
      {(plan.new_stop_price != null || targets.length > 0) && (
        <div className="text-[10px] text-zinc-500 v5-mono pl-3">
          {plan.remaining_shares != null && (
            <span>{plan.remaining_shares}sh </span>
          )}
          {plan.new_stop_price != null && (
            <span>· stop {fmtPx(plan.new_stop_price)}</span>
          )}
          {targets.length > 0 && (
            <span> · targets {targets.map((t) => `${fmtPx(t.p)}×${t.q}`).join(', ')}</span>
          )}
          {plan.new_tif && (
            <span> · TIF {plan.new_tif}</span>
          )}
        </div>
      )}
    </div>
  );
};

export default function BracketHistoryPanel({ tradeId, symbol }) {
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (!tradeId && !symbol) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (tradeId) params.set('trade_id', tradeId);
        else if (symbol) params.set('symbol', symbol);
        params.set('days', '7');
        params.set('limit', '50');
        const res = await fetch(
          `${BACKEND_URL}/api/trading-bot/bracket-history?${params.toString()}`,
        );
        const json = await res.json();
        if (cancelled) return;
        if (json.success) {
          setEvents(json.events || []);
          setSummary(json.summary || null);
        } else {
          setError(json.error || 'fetch_failed');
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [open, tradeId, symbol]);

  const toggle = (e) => {
    e?.stopPropagation?.();
    setOpen((v) => !v);
  };

  return (
    <div className="mt-2 pt-2 border-t border-zinc-800/40" data-testid="bracket-history-panel">
      <button
        type="button"
        onClick={toggle}
        data-testid="bracket-history-toggle"
        className="text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-1.5"
      >
        <span>📜</span>
        <span>Bracket History</span>
        {summary && summary.total > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-[9px]">
            {summary.total}
          </span>
        )}
        <span className="text-zinc-700">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div
          className="mt-1.5 space-y-0.5 pl-2"
          data-testid="bracket-history-events"
        >
          {loading && (
            <div className="text-[11px] text-zinc-500 italic">Loading…</div>
          )}
          {error && (
            <div className="text-[11px] text-rose-400" data-testid="bracket-history-error">
              {error}
            </div>
          )}
          {!loading && !error && events.length === 0 && (
            <div className="text-[11px] text-zinc-600 italic" data-testid="bracket-history-empty">
              No bracket re-issue events yet for this trade.
            </div>
          )}
          {events.map((ev, i) => (
            <EventRow key={ev.created_at_iso || ev.started_at || i} event={ev} />
          ))}
          {summary && summary.total > 0 && (
            <div
              className="text-[10px] text-zinc-600 v5-mono mt-1 pt-1 border-t border-zinc-800/40"
              data-testid="bracket-history-summary"
            >
              {summary.total} event(s) · {summary.success_count} ok · {summary.failure_count} failed
            </div>
          )}
        </div>
      )}
    </div>
  );
}
