/**
 * PositionThoughtsInline — v19.34.26 (May 2026)
 * ----------------------------------------------
 * Auto-fetches the last N bot thoughts for a given symbol from
 * `/api/sentcom/stream/history?symbol=X&minutes=60` and renders them
 * inline inside an Open Position tile so the operator sees the bot's
 * reasoning AT a glance — no expand-toggle required.
 *
 * Operator request: "make bot thoughts auto-visible in the position
 * tile by default". Previously this lived only in the chart-bubble
 * overlay + the unified-stream panel, so the operator had to flick
 * their eyes across the screen to correlate a position with the
 * scanner's reject/skip/trigger narrative for that symbol.
 *
 * Polling cadence: 30s. The endpoint is cheap (~50ms with the
 * action_type equality fast-path) and the dedup TTL on
 * `_emit_scanner_thought` already prevents noisy duplicates.
 */
import React, { useEffect, useRef, useState } from 'react';

const KIND_STYLE = {
  // matches the scanner emit kinds: reject / skip / trigger
  reject:  { dot: '#f43f5e', label: 'REJECT'  },
  skip:    { dot: '#a16207', label: 'SKIP'    },
  trigger: { dot: '#10b981', label: 'TRIGGER' },
  thought: { dot: '#06b6d4', label: 'THOUGHT' },
  // legacy / other
  brain:   { dot: '#a855f7', label: 'BRAIN'   },
  scan:    { dot: '#0ea5e9', label: 'SCAN'    },
  win:     { dot: '#10b981', label: 'WIN'     },
  loss:    { dot: '#f43f5e', label: 'LOSS'    },
  info:    { dot: '#71717a', label: 'INFO'    },
};

const fmtClock = (iso) => {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric', minute: '2-digit', second: '2-digit',
      hour12: false,
    });
  } catch (_) { return ''; }
};

export default function PositionThoughtsInline({ symbol, limit = 5, minutes = 60 }) {
  const [thoughts, setThoughts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // Cache the last successful payload per (symbol) so a slow refetch
  // doesn't flicker the list to empty — keeps the strip visually stable
  // across the 30s poll cycle.
  const lastBySymbolRef = useRef(new Map());

  useEffect(() => {
    if (!symbol) return undefined;
    const cached = lastBySymbolRef.current.get(symbol);
    if (cached) setThoughts(cached);
    let cancelled = false;

    const fetchNow = async () => {
      setLoading(true);
      setError(null);
      try {
        const base = process.env.REACT_APP_BACKEND_URL || '';
        const url = `${base}/api/sentcom/stream/history`
          + `?symbol=${encodeURIComponent(symbol)}`
          + `&minutes=${minutes}`
          + `&limit=${limit}`;
        const res = await fetch(url, { credentials: 'omit' });
        const data = await res.json().catch(() => ({}));
        if (cancelled) return;
        if (!res.ok || data?.success === false) {
          setError(data?.error || `HTTP ${res.status}`);
          return;
        }
        // Backend returns newest-first. We render newest-first too.
        const list = Array.isArray(data?.messages) ? data.messages.slice(0, limit) : [];
        setThoughts(list);
        lastBySymbolRef.current.set(symbol, list);
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchNow();
    const id = setInterval(fetchNow, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, limit, minutes]);

  if (error) {
    return (
      <div
        data-testid={`position-thoughts-error-${symbol}`}
        className="mt-1 text-[11px] text-rose-400/80 italic"
      >
        thoughts unavailable · {error}
      </div>
    );
  }
  if (!loading && thoughts.length === 0) {
    return (
      <div
        data-testid={`position-thoughts-empty-${symbol}`}
        className="mt-1 text-[11px] text-zinc-600 italic"
      >
        no bot thoughts logged for {symbol} in the last {minutes}m
      </div>
    );
  }
  return (
    <div
      data-testid={`position-thoughts-${symbol}`}
      className="mt-1 pt-1 border-t border-zinc-900/70 space-y-0.5"
    >
      <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-zinc-600">
        <span>Bot thoughts · last {minutes}m</span>
        {loading && <span className="text-zinc-700">↻</span>}
      </div>
      {thoughts.map((t, i) => {
        const k = String(t.kind || t.type || 'info').toLowerCase();
        const style = KIND_STYLE[k] || KIND_STYLE.info;
        const txt = t.text || t.content || '';
        return (
          <div
            key={t.id || `${symbol}-${i}`}
            data-testid={`position-thought-${symbol}-${i}`}
            className="flex items-start gap-1.5 text-[12px] leading-snug"
            title={`${style.label} · ${fmtClock(t.timestamp)} ET`}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full mt-1 shrink-0"
              style={{ backgroundColor: style.dot }}
              aria-hidden
            />
            <span className="font-mono text-[10px] text-zinc-600 shrink-0 mt-px">
              {fmtClock(t.timestamp)}
            </span>
            <span className="text-zinc-300 truncate">{txt}</span>
          </div>
        );
      })}
    </div>
  );
}
