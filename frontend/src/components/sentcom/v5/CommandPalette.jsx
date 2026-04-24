/**
 * CommandPalette — ⌘K / Ctrl+K global fuzzy-search overlay.
 * Searches over:
 *   - Open positions (from ib_live_snapshot)
 *   - Scanner top candidates
 *   - Active live subscriptions
 *   - Core indices (SPY / QQQ / IWM / DIA / VIX)
 *
 * Enter → opens the EnhancedTickerModal for the selected symbol via the
 * `onSelectSymbol` callback (already wired by the V5 page).
 *
 * Minimal fuzzy match: starts-with + substring. Not importing fuse.js —
 * keeps bundle light; the corpus is tiny (<100 symbols typically).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const CORE = ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX'];

async function _get(path) {
  try {
    const r = await fetch(`${BACKEND_URL}${path}`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

async function _buildCorpus() {
  // Pull subscriptions + positions + scanner watchlist in parallel
  const [subs, wl] = await Promise.all([
    _get('/api/live/subscriptions'),
    _get('/api/live/briefing-watchlist'),
  ]);
  const set = new Set();
  (subs?.subscriptions || []).forEach((s) => set.add(s.symbol));
  (wl?.symbols || []).forEach((s) => set.add(s));
  CORE.forEach((s) => set.add(s));
  return Array.from(set).sort();
}

function _score(query, symbol) {
  if (!query) return 100;
  const q = query.toUpperCase();
  const s = symbol.toUpperCase();
  if (s === q) return 1000;
  if (s.startsWith(q)) return 500 + (10 - Math.abs(s.length - q.length));
  if (s.includes(q)) return 200;
  return 0;
}

export const CommandPalette = ({ onSelectSymbol }) => {
  const [open, setOpen] = useState(false);
  const [corpus, setCorpus] = useState([]);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);

  // Global ⌘K / Ctrl+K listener — mount ONCE
  useEffect(() => {
    const onKey = (e) => {
      const isModK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      if (isModK) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Load corpus when opened
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setSelectedIdx(0);
    _buildCorpus().then(setCorpus);
    // Focus input
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const results = corpus
    .map((s) => ({ symbol: s, score: _score(query, s) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);

  const activate = useCallback(
    (sym) => {
      setOpen(false);
      if (sym) onSelectSymbol?.(sym);
    },
    [onSelectSymbol]
  );

  const onInputKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = results[selectedIdx]?.symbol || query.toUpperCase().trim();
      if (pick) activate(pick);
    }
  };

  if (!open) return null;

  return (
    <div
      data-testid="command-palette"
      className="fixed inset-0 bg-black/80 z-[70] flex items-start justify-center pt-[12vh] p-4"
      onClick={() => setOpen(false)}
    >
      <div
        className="bg-zinc-950 border border-zinc-800 rounded-lg w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800">
          <span className="v5-mono text-[10px] text-zinc-500 uppercase tracking-wide">⌘K</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIdx(0);
            }}
            onKeyDown={onInputKey}
            placeholder="Type a symbol…"
            data-testid="command-palette-input"
            className="flex-1 bg-transparent outline-none text-zinc-100 v5-mono text-xs placeholder:text-zinc-600"
          />
          <span className="v5-mono text-[9px] text-zinc-600">esc</span>
        </div>
        <div className="max-h-[50vh] overflow-y-auto v5-scroll">
          {results.length === 0 && (
            <div className="v5-mono text-[10px] text-zinc-600 px-3 py-4 text-center">
              {query ? `No match for "${query}" — press Enter to open ${query.toUpperCase()}` : 'Type to search…'}
            </div>
          )}
          {results.map((r, i) => (
            <button
              key={r.symbol}
              type="button"
              data-testid={`command-palette-item-${r.symbol}`}
              onMouseEnter={() => setSelectedIdx(i)}
              onClick={() => activate(r.symbol)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 v5-mono text-[11px] text-left hover:bg-zinc-900 ${i === selectedIdx ? 'bg-zinc-900 text-violet-300' : 'text-zinc-200'}`}
            >
              <span className="font-bold w-14">{r.symbol}</span>
              {i === selectedIdx && <span className="ml-auto text-[9px] text-zinc-500">enter ↵</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;
