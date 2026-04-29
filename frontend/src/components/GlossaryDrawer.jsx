/**
 * GlossaryDrawer — slide-in side panel that shows the full glossary
 * without making the user leave their current tab.
 *
 * Open via:
 *   - Floating ❓ button (rendered globally in App.js)
 *   - window.dispatchEvent(new CustomEvent('sentcom:open-glossary', {detail: {termId}}))
 *   - Press-? overlay click on any glossary-aware element
 *   - ⌘K → ?<term> → Enter
 *   - Inline tooltips' "→ Learn more" link
 *
 * Single source of truth: `data/glossaryData.js`. The drawer reads
 * categories + entries from there and builds:
 *   - Search box (matches term, shortDef, tags)
 *   - Category chips for filtering
 *   - Selected entry's full markdown rendering
 *   - Related terms quick-jump
 *
 * Read-only — no editing here. The dedicated /glossary page handles
 * knowledge-base CRUD; this is the lookup-fast surface.
 */

import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Search, BookOpen, ArrowLeft } from 'lucide-react';
import glossaryData from '../data/glossaryData';

const ALL_CATEGORY_ID = '__all__';

function _matches(entry, q) {
  if (!q) return true;
  const needle = q.toLowerCase();
  if (entry.term?.toLowerCase().includes(needle)) return true;
  if (entry.id?.toLowerCase().includes(needle)) return true;
  if (entry.shortDef?.toLowerCase().includes(needle)) return true;
  if (entry.tags?.some((t) => t.toLowerCase().includes(needle))) return true;
  return false;
}

/** Tiny markdown renderer — handles **bold**, `code`, lists, and line breaks.
 *  Avoids importing a markdown library for ~50 lines of replacement. */
function _renderMarkdown(text) {
  if (!text) return null;
  // Split into blocks separated by blank lines
  const blocks = text.split(/\n\n+/);
  return blocks.map((block, bi) => {
    const lines = block.split('\n');
    const isList = lines.every((l) => /^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l));
    if (isList) {
      return (
        <ul key={bi} className="list-disc pl-5 space-y-0.5 mb-2 text-zinc-300">
          {lines.map((l, i) => (
            <li key={i}>{_renderInline(l.replace(/^\s*[-*]\s+/, '').replace(/^\s*\d+\.\s+/, ''))}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={bi} className="mb-2 leading-relaxed text-zinc-300">
        {lines.map((l, i) => (
          <React.Fragment key={i}>
            {_renderInline(l)}
            {i < lines.length - 1 && <br />}
          </React.Fragment>
        ))}
      </p>
    );
  });
}

function _renderInline(text) {
  // Replace **bold** then `code`. Order matters.
  const parts = [];
  let remaining = text;
  let key = 0;
  // Match **bold** | `code`
  const re = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  let m;
  while ((m = re.exec(remaining)) !== null) {
    if (m.index > last) parts.push(remaining.slice(last, m.index));
    if (m[1] !== undefined) {
      parts.push(<strong key={`b${key++}`} className="text-zinc-100">{m[1]}</strong>);
    } else if (m[2] !== undefined) {
      parts.push(<code key={`c${key++}`} className="font-mono text-cyan-300 bg-zinc-900 px-1 rounded">{m[2]}</code>);
    }
    last = re.lastIndex;
  }
  if (last < remaining.length) parts.push(remaining.slice(last));
  return parts;
}

export const GlossaryDrawer = () => {
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORY_ID);

  // Listen for global "open" events
  useEffect(() => {
    const onOpen = (e) => {
      setOpen(true);
      const termId = e?.detail?.termId;
      if (termId) {
        setSelectedId(termId);
        setQuery('');
      }
    };
    const onClose = () => setOpen(false);
    window.addEventListener('sentcom:open-glossary', onOpen);
    window.addEventListener('sentcom:close-glossary', onClose);
    return () => {
      window.removeEventListener('sentcom:open-glossary', onOpen);
      window.removeEventListener('sentcom:close-glossary', onClose);
    };
  }, []);

  // Esc to close
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const entries = glossaryData.entries;
  const categories = glossaryData.categories;

  const filteredEntries = useMemo(() => {
    return entries.filter((e) => {
      if (categoryFilter !== ALL_CATEGORY_ID && e.category !== categoryFilter) return false;
      if (!_matches(e, query)) return false;
      return true;
    });
  }, [entries, categoryFilter, query]);

  const selected = useMemo(
    () => entries.find((e) => e.id === selectedId) || null,
    [entries, selectedId]
  );

  const openTerm = useCallback((termId) => setSelectedId(termId), []);

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/60 z-[80] flex justify-end"
        data-testid="glossary-drawer"
        onClick={() => setOpen(false)}
      >
        <motion.aside
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'tween', duration: 0.25 }}
          className="bg-zinc-950 border-l border-zinc-800 w-full max-w-md h-full flex flex-col shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
            <div className="flex items-center gap-2">
              {selected ? (
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  className="p-1 hover:bg-zinc-800 rounded transition-colors"
                  data-testid="glossary-drawer-back"
                  title="Back to list"
                >
                  <ArrowLeft className="w-4 h-4 text-zinc-400" />
                </button>
              ) : (
                <BookOpen className="w-4 h-4 text-cyan-400" />
              )}
              <span className="font-semibold text-sm text-zinc-100">
                {selected ? selected.term : 'Glossary'}
              </span>
              {!selected && (
                <span className="text-[12px] text-zinc-500 font-mono">
                  {filteredEntries.length}/{entries.length}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="p-1.5 hover:bg-zinc-800 rounded transition-colors"
              data-testid="glossary-drawer-close"
              title="Close (Esc)"
            >
              <X className="w-4 h-4 text-zinc-400" />
            </button>
          </div>

          {/* Body — list view OR detail view */}
          {selected ? (
            <div className="flex-1 overflow-y-auto p-4">
              <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">
                {categories.find((c) => c.id === selected.category)?.name || selected.category}
              </div>
              <div className="text-cyan-300 text-sm font-medium mb-3">
                {selected.shortDef}
              </div>
              <div className="text-sm text-zinc-300">
                {_renderMarkdown(selected.fullDef)}
              </div>
              {selected.relatedTerms?.length > 0 && (
                <div className="mt-4 pt-3 border-t border-zinc-800">
                  <div className="text-[12px] text-zinc-500 uppercase tracking-wide mb-1.5">
                    Related
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {selected.relatedTerms.map((rid) => {
                      const rel = entries.find((e) => e.id === rid);
                      if (!rel) return null;
                      return (
                        <button
                          key={rid}
                          type="button"
                          onClick={() => openTerm(rid)}
                          data-testid={`glossary-related-${rid}`}
                          className="text-[13px] px-2 py-0.5 rounded border border-zinc-700 hover:border-cyan-500 text-zinc-300 hover:text-cyan-300 transition-colors"
                        >
                          {rel.term}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {selected.tags?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {selected.tags.map((t) => (
                    <span key={t} className="text-[11px] px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-500 uppercase tracking-wide">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              {/* Search */}
              <div className="px-3 py-2 border-b border-zinc-900 flex items-center gap-2">
                <Search className="w-3.5 h-3.5 text-zinc-500" />
                <input
                  autoFocus
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search terms, tags, or definitions…"
                  data-testid="glossary-drawer-search"
                  className="flex-1 bg-transparent outline-none text-sm text-zinc-100 placeholder:text-zinc-600"
                />
              </div>

              {/* Category chips */}
              <div className="px-3 py-2 border-b border-zinc-900 flex flex-wrap gap-1 overflow-x-auto">
                <button
                  type="button"
                  onClick={() => setCategoryFilter(ALL_CATEGORY_ID)}
                  className={`text-[12px] px-2 py-0.5 rounded uppercase tracking-wide transition-colors ${
                    categoryFilter === ALL_CATEGORY_ID
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                      : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:border-zinc-700'
                  }`}
                >
                  All
                </button>
                {categories.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setCategoryFilter(c.id)}
                    data-testid={`glossary-cat-${c.id}`}
                    className={`text-[12px] px-2 py-0.5 rounded uppercase tracking-wide transition-colors ${
                      categoryFilter === c.id
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                        : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:border-zinc-700'
                    }`}
                  >
                    {c.name}
                  </button>
                ))}
              </div>

              {/* List */}
              <div className="flex-1 overflow-y-auto">
                {filteredEntries.length === 0 ? (
                  <div className="p-6 text-center text-sm text-zinc-500">
                    No matches for &quot;{query}&quot;
                  </div>
                ) : (
                  filteredEntries.map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => openTerm(e.id)}
                      data-testid={`glossary-entry-${e.id}`}
                      className="w-full text-left px-3 py-2 border-b border-zinc-900 hover:bg-zinc-900 transition-colors"
                    >
                      <div className="text-sm font-medium text-zinc-100 mb-0.5">
                        {e.term}
                      </div>
                      <div className="text-[13px] text-zinc-500 line-clamp-2 leading-snug">
                        {e.shortDef}
                      </div>
                      <div className="text-[11px] text-zinc-600 uppercase tracking-wide mt-1">
                        {categories.find((c) => c.id === e.category)?.name || e.category}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </>
          )}

          {/* Footer hint */}
          <div className="px-3 py-2 border-t border-zinc-900 text-[12px] text-zinc-600 flex items-center justify-between">
            <span>Press <kbd className="px-1 py-0.5 bg-zinc-900 rounded">?</kbd> on the page to highlight every helpable element</span>
            <span>Esc to close</span>
          </div>
        </motion.aside>
      </motion.div>
    </AnimatePresence>
  );
};

/**
 * Programmatic helper — call from anywhere to open the drawer at a
 * specific term. Caller doesn't need a ref or context.
 */
export function openGlossary(termId = null) {
  window.dispatchEvent(
    new CustomEvent('sentcom:open-glossary', { detail: { termId } })
  );
}

export default GlossaryDrawer;
