/**
 * Wave 2 (#9) — DeepFeedV5: turns the right-pane "Stream · Deep Feed"
 * from a duplicate of UnifiedStream into an actual forensic tool.
 *
 *   • Time-range chips: 5m / 30m / 1h / 4h / 1d / 7d
 *   • Symbol drill-in:  type a ticker, debounced 250ms
 *   • Text search:      free-form, server-side regex on content + action_type
 *   • Reuses UnifiedStreamV5 for rendering (so collapse + cross-highlight
 *     + severity colors all "just work").
 *
 * Backed by GET /api/sentcom/stream/history (Mongo `sentcom_thoughts`,
 * TTL 7d). Polls every 30s when active to surface fresh events.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { UnifiedStreamV5 } from './UnifiedStreamV5';

const TIME_CHIPS = [
  { label: '5m',  minutes: 5 },
  { label: '30m', minutes: 30 },
  { label: '1h',  minutes: 60 },
  { label: '4h',  minutes: 240 },
  { label: '1d',  minutes: 1440 },
  { label: '7d',  minutes: 10080 },
];

const POLL_INTERVAL_MS = 30000;

// Debounce utility — local because the search field is the only debounced
// thing in this view; not worth pulling in a dep.
const useDebouncedValue = (value, delayMs) => {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
};

const buildHistoryUrl = ({ apiBase, minutes, symbol, q, limit }) => {
  const params = new URLSearchParams();
  params.set('minutes', String(minutes));
  params.set('limit', String(limit));
  if (symbol) params.set('symbol', symbol.toUpperCase());
  if (q) params.set('q', q);
  return `${apiBase}/api/sentcom/stream/history?${params.toString()}`;
};

export const DeepFeedV5 = ({
  apiBase = '',
  onSymbolClick,
  hoveredSymbol,
  onHoverSymbol,
}) => {
  const [minutes, setMinutes] = useState(60);
  const [symbol, setSymbol] = useState('');
  const [q, setQ] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [count, setCount] = useState(0);
  const [error, setError] = useState(null);

  // Debounce both filter inputs so we don't hammer the endpoint on
  // every keystroke. 250ms is fast enough to feel responsive while
  // sparing 80%+ of the requests during typing.
  const debouncedSymbol = useDebouncedValue(symbol.trim(), 250);
  const debouncedQ = useDebouncedValue(q.trim(), 250);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = buildHistoryUrl({
        apiBase,
        minutes,
        symbol: debouncedSymbol,
        q: debouncedQ,
        limit: 500,
      });
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (!data.success) throw new Error(data.error || 'fetch failed');
      setMessages(data.messages || []);
      setCount(data.count || 0);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBase, minutes, debouncedSymbol, debouncedQ]);

  // Initial + filter-change fetch
  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Background poll (only while no manual filter is being typed).
  useEffect(() => {
    const id = setInterval(fetchHistory, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchHistory]);

  const headerStats = useMemo(() => {
    if (loading) return 'loading…';
    if (error) return `error: ${error}`;
    return `${count} event${count === 1 ? '' : 's'}`;
  }, [loading, error, count]);

  return (
    <div data-testid="v5-deep-feed" className="flex flex-col h-full">
      {/* Filter bar — sticky, two rows on narrow widths. */}
      <div className="px-3 py-1.5 border-b border-zinc-900 bg-zinc-950/80 sticky top-0 z-10 flex flex-col gap-1.5">
        <div className="flex items-center gap-1 flex-wrap">
          <span className="v5-mono text-[11px] v5-dim uppercase tracking-widest mr-1">range:</span>
          {TIME_CHIPS.map((c) => (
            <button
              key={c.label}
              type="button"
              data-testid={`v5-deep-feed-range-${c.label}`}
              onClick={() => setMinutes(c.minutes)}
              className={`v5-filter-chip ${minutes === c.minutes ? 'active' : ''}`}
            >
              {c.label}
            </button>
          ))}
          <span className="ml-auto v5-mono text-[11px] v5-dim">{headerStats}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="symbol (AAPL)"
            data-testid="v5-deep-feed-symbol-input"
            className="flex-1 min-w-0 px-2 py-1 text-[12px] v5-mono bg-zinc-900 border border-zinc-800 rounded-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-cyan-700 uppercase"
            maxLength={8}
          />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='search ("WULF skip", "gate", …)'
            data-testid="v5-deep-feed-search-input"
            className="flex-[2] min-w-0 px-2 py-1 text-[12px] v5-mono bg-zinc-900 border border-zinc-800 rounded-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-cyan-700"
          />
          {(symbol || q) && (
            <button
              type="button"
              onClick={() => { setSymbol(''); setQ(''); }}
              className="v5-filter-chip"
              data-testid="v5-deep-feed-clear"
              title="Clear filters"
            >
              clear
            </button>
          )}
        </div>
      </div>

      {/* Reuse the live stream renderer — collapse + severity coloring +
          cross-highlight all work identically. */}
      <div className="flex-1 min-h-0 overflow-y-auto v5-scroll">
        <UnifiedStreamV5
          messages={messages}
          loading={loading}
          onSymbolClick={onSymbolClick}
          hoveredSymbol={hoveredSymbol}
          onHoverSymbol={onHoverSymbol}
        />
      </div>
    </div>
  );
};

export default DeepFeedV5;
