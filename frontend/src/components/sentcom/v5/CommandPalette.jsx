/**
 * CommandPalette — ⌘K / Ctrl+K global fuzzy-search overlay.
 * Searches over:
 *   - Open positions (from ib_live_snapshot)
 *   - Scanner top candidates
 *   - Active live subscriptions
 *   - Core indices (SPY / QQQ / IWM / DIA / VIX)
 *
 * When the input is empty and the user has previously picked symbols, we
 * show the most recent 5 (persisted to localStorage) so re-opening the
 * palette to jump back to a symbol is a single keystroke.
 *
 * Enter → opens the EnhancedTickerModal for the selected symbol via the
 * `onSelectSymbol` callback (already wired by the V5 page).
 *
 * Minimal fuzzy match: starts-with + substring. Not importing fuse.js —
 * keeps bundle light; the corpus is tiny (<100 symbols typically).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import glossaryData from '../../../data/glossaryData';
import { openGlossary } from '../../GlossaryDrawer';
import { tours, startTour } from '../../../data/tours';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const CORE = ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX'];
const RECENT_KEY = 'sentcom.cmd-palette.recent';
const RECENT_MAX = 5;

function _loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((s) => typeof s === 'string').slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function _saveRecent(symbol) {
  try {
    const prev = _loadRecent().filter((s) => s !== symbol);
    const next = [symbol, ...prev].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore storage quota / disabled */
  }
}

/** Search the glossary for terms matching the post-`?` query. */
function _searchGlossary(q) {
  if (!q) return glossaryData.entries.slice(0, 8);
  const needle = q.toLowerCase();
  return glossaryData.entries
    .filter((e) =>
      e.term.toLowerCase().includes(needle) ||
      e.id.includes(needle) ||
      e.shortDef.toLowerCase().includes(needle) ||
      (e.tags || []).some((t) => t.toLowerCase().includes(needle))
    )
    .slice(0, 8);
}

/** Build the ">command" mode result list. Currently: tours. */
function _searchCommands(q) {
  const needle = (q || '').toLowerCase();
  const all = Object.values(tours).map((t) => ({
    type: 'tour',
    id: t.id,
    label: `tour ${t.id}`,
    description: t.description,
  }));
  if (!needle) return all;
  return all.filter(
    (c) => c.label.toLowerCase().includes(needle) || c.description.toLowerCase().includes(needle)
  );
}

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
  const [recent, setRecent] = useState(_loadRecent());
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);

  // Global ⌘K / Ctrl+K listener — mount ONCE. Also respond to a custom
  // `sentcom:open-command-palette` window event so the ⌘K hint chip (or any
  // other UI) can programmatically open the palette without tight coupling.
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
    const onOpenEvt = () => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener('sentcom:open-command-palette', onOpenEvt);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('sentcom:open-command-palette', onOpenEvt);
    };
  }, [open]);

  // Load corpus when opened
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setSelectedIdx(0);
    setRecent(_loadRecent());
    _buildCorpus().then(setCorpus);
    // Focus input
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const results = corpus
    .map((s) => ({ symbol: s, score: _score(query, s) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);

  // Help mode: query starts with `?` → switch corpus to glossary entries.
  const helpMode = query.startsWith('?');
  const helpResults = helpMode ? _searchGlossary(query.slice(1).trim()) : [];

  // Command mode: query starts with `>` → run-an-action mode (currently tours).
  const cmdMode = query.startsWith('>');
  const cmdResults = cmdMode ? _searchCommands(query.slice(1).trim()) : [];

  // When the query is empty, show recent picks instead of the full corpus so
  // re-opening the palette to jump back to a symbol is a single keystroke.
  const showRecent = !query && recent.length > 0;
  const visibleItems = helpMode
    ? helpResults.map((g) => ({ symbol: g.term, glossary: g, score: 0 }))
    : cmdMode
      ? cmdResults.map((c) => ({ symbol: c.label, command: c, score: 0 }))
      : showRecent
        ? recent.map((symbol) => ({ symbol, score: 0, isRecent: true }))
        : results;

  const activate = useCallback(
    (item) => {
      setOpen(false);
      // `item` may be a string (back-compat) or an object {symbol, glossary, command, ...}
      const sym = typeof item === 'string' ? item : item?.symbol;
      const glossary = typeof item === 'object' ? item?.glossary : null;
      const command = typeof item === 'object' ? item?.command : null;
      if (glossary) {
        setTimeout(() => openGlossary(glossary.id), 50);
        return;
      }
      if (command) {
        if (command.type === 'tour') {
          setTimeout(() => startTour(command.id), 50);
        }
        return;
      }
      if (sym) {
        _saveRecent(sym);
        onSelectSymbol?.(sym);
      }
    },
    [onSelectSymbol]
  );

  const onInputKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, visibleItems.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = visibleItems[selectedIdx] || (helpMode || cmdMode ? null : query.toUpperCase().trim());
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
          <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide">⌘K</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIdx(0);
            }}
            onKeyDown={onInputKey}
            placeholder="Symbol… · ? for glossary · > for tours"
            data-testid="command-palette-input"
            className="flex-1 bg-transparent outline-none text-zinc-100 v5-mono text-xs placeholder:text-zinc-600"
          />
          <span className="v5-mono text-[11px] text-zinc-600">esc</span>
        </div>
        <div className="max-h-[50vh] overflow-y-auto v5-scroll">
          {helpMode && (
            <div
              data-testid="command-palette-help-header"
              className="v5-mono text-[11px] text-cyan-400 uppercase tracking-wide px-3 py-1.5 border-b border-zinc-900 bg-cyan-500/5"
            >
              Glossary · {visibleItems.length} match{visibleItems.length === 1 ? '' : 'es'}
            </div>
          )}
          {cmdMode && (
            <div
              data-testid="command-palette-cmd-header"
              className="v5-mono text-[11px] text-violet-400 uppercase tracking-wide px-3 py-1.5 border-b border-zinc-900 bg-violet-500/5"
            >
              Commands · {visibleItems.length} available
            </div>
          )}
          {!helpMode && !cmdMode && showRecent && (
            <div
              data-testid="command-palette-recent-header"
              className="v5-mono text-[11px] text-zinc-600 uppercase tracking-wide px-3 py-1.5 border-b border-zinc-900"
            >
              Recent
            </div>
          )}
          {visibleItems.length === 0 && (
            <div className="v5-mono text-[12px] text-zinc-600 px-3 py-4 text-center">
              {helpMode
                ? `No glossary match for "${query.slice(1)}"`
                : cmdMode
                  ? `No command matches "${query.slice(1)}"`
                  : query
                    ? `No match for "${query}" — press Enter to open ${query.toUpperCase()}`
                    : 'Type to search…'}
            </div>
          )}
          {visibleItems.map((r, i) => (
            <button
              key={r.glossary ? `g-${r.glossary.id}` : r.command ? `c-${r.command.id}` : r.symbol}
              type="button"
              data-testid={
                r.glossary
                  ? `command-palette-glossary-${r.glossary.id}`
                  : r.command
                    ? `command-palette-cmd-${r.command.id}`
                    : `command-palette-item-${r.symbol}`
              }
              onMouseEnter={() => setSelectedIdx(i)}
              onClick={() => activate(r)}
              className={`w-full flex items-start gap-2 px-3 py-1.5 v5-mono text-[13px] text-left hover:bg-zinc-900 ${i === selectedIdx ? 'bg-zinc-900 text-violet-300' : 'text-zinc-200'}`}
            >
              {r.glossary ? (
                <>
                  <span className="text-cyan-400 mt-0.5">?</span>
                  <span className="flex-1 min-w-0">
                    <span className="font-bold text-zinc-100 block truncate">{r.glossary.term}</span>
                    <span className="text-[12px] text-zinc-500 line-clamp-1 leading-tight block">
                      {r.glossary.shortDef}
                    </span>
                  </span>
                  {i === selectedIdx && <span className="text-[11px] text-zinc-500 mt-0.5">enter ↵</span>}
                </>
              ) : r.command ? (
                <>
                  <span className="text-violet-400 mt-0.5">›</span>
                  <span className="flex-1 min-w-0">
                    <span className="font-bold text-zinc-100 block truncate">{r.command.label}</span>
                    <span className="text-[12px] text-zinc-500 line-clamp-1 leading-tight block">
                      {r.command.description}
                    </span>
                  </span>
                  {i === selectedIdx && <span className="text-[11px] text-zinc-500 mt-0.5">run ↵</span>}
                </>
              ) : (
                <>
                  <span className="font-bold w-14">{r.symbol}</span>
                  {r.isRecent && (
                    <span className="text-[11px] text-zinc-600 uppercase tracking-wide">recent</span>
                  )}
                  {i === selectedIdx && <span className="ml-auto text-[11px] text-zinc-500">enter ↵</span>}
                </>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;
