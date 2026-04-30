/**
 * ChartThoughtBubblesOverlay — Stage 2g (2026-05-01 v19.23).
 *
 * Floats the bot's reasoning trail as chat-bubble annotations directly
 * over the chart, mirroring the V5 Command Center mockup. Each bubble
 * carries the bot's thoughts AT the moment it had them — scanner flags,
 * macro checks, AI consensus / vision / FinBERT outputs, trigger fires,
 * order fills, target alerts.
 *
 * Plus a thin bottom timeline rail with one dot per bubble. Click a dot
 * to scroll the chart to that moment in time.
 *
 * Data source: GET /api/sentcom/stream/history?symbol=X&minutes=N
 *  - kind ∈ {scan, brain, evaluation, thought, fill, alert, skip, rejection}
 *  - content = the bot's actual narrative
 *  - timestamp = when the bot wrote it (used to anchor the bubble x-pos)
 *
 * Visual contract from the mockup:
 *  - Bubble = rounded card + colored left edge + time/title/body
 *  - Bubble color matches the kind (purple = scan, cyan = brain, gold = trigger)
 *  - Bottom rail dots match the bubble color, click to jump
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { fmtET12Sec } from '../../../utils/timeET';

// Map a sentcom_thoughts `kind` → bubble color/title prefix.
// Hand-tuned to match the mockup's visual hierarchy: scanner flags are
// muted (purple), macro/brain thoughts are cool (cyan), trigger/fills
// are warm (amber → emerald) so the eye walks the timeline naturally.
const KIND_STYLE = {
  scan:       { color: '#a855f7', label: 'Scanner' },
  brain:      { color: '#06b6d4', label: 'Brain' },
  evaluation: { color: '#06b6d4', label: 'Eval' },
  thought:    { color: '#22d3ee', label: 'Thought' },
  alert:      { color: '#fbbf24', label: 'Alert' },
  filter:     { color: '#94a3b8', label: 'Filter' },
  fill:       { color: '#10b981', label: 'Fill' },
  rejection:  { color: '#94a3b8', label: 'Rejected' },
  skip:       { color: '#94a3b8', label: 'Skip' },
  info:       { color: '#a1a1aa', label: 'Info' },
  system:     { color: '#a1a1aa', label: 'System' },
};

const fallbackStyle = { color: '#a1a1aa', label: '·' };
const styleFor = (kind) => KIND_STYLE[(kind || '').toLowerCase()] || fallbackStyle;

// Polite title from action_type if the row has it. Falls back to the
// kind label.
const titleFor = (row, style) => {
  if (row.action_type) {
    return row.action_type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return style.label;
};

const toEpochSec = (ts) => {
  if (ts == null) return null;
  if (typeof ts === 'number') return ts > 1e12 ? Math.floor(ts / 1000) : ts;
  const d = new Date(ts);
  const n = d.getTime();
  return Number.isNaN(n) ? null : Math.floor(n / 1000);
};

// Truncate body text so the bubble stays compact. Operator can click
// the bubble to surface the rest in the Unified Stream.
const truncate = (s, n = 180) => {
  if (!s) return '';
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
};


export const ChartThoughtBubblesOverlay = ({
  symbol,
  chartRef,
  visible = true,
  minutes = 240,
  onSelectThought,
}) => {
  const [thoughts, setThoughts] = useState([]);
  const [bubblePositions, setBubblePositions] = useState([]);  // { left, kind, row }
  const [hoveredId, setHoveredId] = useState(null);
  const [pinnedId, setPinnedId] = useState(null);
  const containerRef = useRef(null);

  // Fetch bot thoughts whenever the focused symbol changes (or on visibility
  // toggle). Limited to the last `minutes` so the chart doesn't drown in
  // months of history.
  useEffect(() => {
    if (!symbol || !visible) {
      setThoughts([]);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        const resp = await safeGet(
          `/api/sentcom/stream/history?symbol=${encodeURIComponent(symbol)}` +
          `&minutes=${minutes}&limit=40`,
          { timeout: 6000 },
        );
        if (cancelled) return;
        const messages = Array.isArray(resp?.messages) ? resp.messages : [];
        // 2026-05-01 v19.23.1 — operator review screenshot showed SBUX
        // had Deep-Feed events but no chart bubbles rendered. Root
        // cause: kind filter was too strict — bot writes some events
        // with kind="filter" (rejection-narrative) and kind="info"
        // (system messages with content) that ARE chart-worthy.
        // Loosened filter: drop only kinds with truly no narrative
        // (system-internal hydration / heartbeat). Anything with
        // operator-facing content stays.
        const ALLOWED_KINDS = new Set([
          'scan', 'brain', 'evaluation', 'thought', 'fill', 'alert',
          'rejection', 'skip', 'filter', 'info',
        ]);
        const filtered = messages
          .filter((m) => m && m.timestamp && (m.content || m.text))
          .filter((m) => ALLOWED_KINDS.has((m.kind || m.type || '').toLowerCase()))
          .map((m) => ({
            id: m.id || `${m.timestamp}-${(m.kind || '').slice(0, 4)}`,
            kind: (m.kind || m.type || 'thought').toLowerCase(),
            content: m.content || m.text || '',
            action_type: m.action_type,
            timestamp: m.timestamp,
            time_sec: toEpochSec(m.timestamp),
          }))
          .filter((m) => m.time_sec != null && m.content);
        // Dedup back-to-back duplicates (bot sometimes writes the same
        // line twice within milliseconds during the rejection-narrative
        // path). Keep the first occurrence of each {kind, content[:80]}
        // pair within a 30s window.
        const seen = new Map();
        const deduped = [];
        for (const t of filtered) {
          const key = `${t.kind}|${(t.content || '').slice(0, 80)}`;
          const prev = seen.get(key);
          if (prev != null && Math.abs(prev - t.time_sec) < 30) continue;
          seen.set(key, t.time_sec);
          deduped.push(t);
        }
        // Sort ascending for timeline display
        deduped.sort((a, b) => a.time_sec - b.time_sec);
        setThoughts(deduped);
      } catch (_) {
        if (!cancelled) setThoughts([]);
      }
    })();
    return () => { cancelled = true; };
  }, [symbol, visible, minutes]);

  // Recompute bubble x-coordinates whenever bars / thoughts / chart
  // visible-time-range change. The chart's timeScale is the source
  // of truth — thoughts that fall outside the visible window simply
  // don't render.
  const recompute = useCallback(() => {
    const chart = chartRef?.current;
    if (!chart || !thoughts.length) {
      setBubblePositions([]);
      return;
    }
    try {
      const ts = chart.timeScale();
      const next = thoughts
        .map((t) => {
          const x = ts.timeToCoordinate(t.time_sec);
          if (x == null) return null;
          return { left: x, ...t };
        })
        .filter(Boolean);
      setBubblePositions(next);
    } catch (_) {
      setBubblePositions([]);
    }
  }, [chartRef, thoughts]);

  useEffect(() => {
    recompute();
    const chart = chartRef?.current;
    if (!chart) return undefined;
    let unsub = null;
    try {
      const ts = chart.timeScale();
      const handler = () => recompute();
      ts.subscribeVisibleTimeRangeChange(handler);
      unsub = () => {
        try { ts.unsubscribeVisibleTimeRangeChange(handler); } catch (_) { /* noop */ }
      };
    } catch (_) { /* noop */ }
    return () => {
      if (unsub) unsub();
    };
  }, [recompute, chartRef]);

  // Click a timeline dot → scroll the chart to that moment.
  const handleJump = useCallback((time_sec) => {
    const chart = chartRef?.current;
    if (!chart) return;
    try {
      const ts = chart.timeScale();
      // Center the moment by setting visible range ±30 bars (~150 minutes
      // on 5min) around it. We don't know the bar size here, so use a
      // heuristic 90-minute window which feels right for 1m/5m/15m views.
      const span = 90 * 60;
      ts.setVisibleRange({ from: time_sec - span, to: time_sec + span });
    } catch (_) { /* noop */ }
  }, [chartRef]);

  // Lay out bubbles vertically so they don't overlap. We assign
  // alternating "lanes" (top vs bottom of the chart pane) and stack
  // within each lane in time order.
  const laidOut = useMemo(() => {
    if (!bubblePositions.length) return [];
    const TOP_LANE_Y = 14;        // px from top
    const BOTTOM_LANE_Y_FROM_BOTTOM = 80;
    return bubblePositions.map((b, i) => ({
      ...b,
      lane: i % 2 === 0 ? 'top' : 'bottom',
      top: i % 2 === 0 ? TOP_LANE_Y + Math.floor(i / 2) * 8 : null,
      bottom: i % 2 === 1 ? BOTTOM_LANE_Y_FROM_BOTTOM + Math.floor(i / 2) * 8 : null,
    }));
  }, [bubblePositions]);

  if (!visible || !symbol) return null;

  return (
    <div
      ref={containerRef}
      className="pointer-events-none absolute inset-0"
      data-testid="chart-thought-bubbles-overlay"
    >
      {/* Bubbles */}
      {laidOut.map((b) => {
        const style = styleFor(b.kind);
        const isOpen = pinnedId === b.id || hoveredId === b.id;
        return (
          <div
            key={b.id}
            className="absolute pointer-events-auto"
            style={{
              left: `${Math.max(8, Math.min(b.left - 100, (containerRef.current?.clientWidth || 800) - 280))}px`,
              top: b.lane === 'top' ? `${b.top}px` : 'auto',
              bottom: b.lane === 'bottom' ? `${b.bottom}px` : 'auto',
              maxWidth: 240,
              zIndex: isOpen ? 30 : 20,
            }}
          >
            <button
              type="button"
              data-testid={`chart-thought-bubble-${b.id}`}
              onClick={() => {
                setPinnedId((prev) => (prev === b.id ? null : b.id));
                onSelectThought?.(b);
              }}
              onMouseEnter={() => setHoveredId(b.id)}
              onMouseLeave={() => setHoveredId(null)}
              className="text-left rounded-md border bg-zinc-950/90 backdrop-blur-sm shadow-lg hover:shadow-xl transition-shadow"
              style={{
                borderColor: style.color,
                borderLeftWidth: 3,
                opacity: isOpen ? 1 : 0.85,
              }}
            >
              <div className="px-2 py-1">
                <div
                  className="flex items-baseline gap-1.5 v5-mono text-[10px] uppercase tracking-wider"
                  style={{ color: style.color }}
                >
                  <span>{fmtET12Sec(b.time_sec * 1000)}</span>
                  <span className="text-zinc-500">·</span>
                  <span className="font-semibold">{titleFor(b, style)}</span>
                </div>
                {(isOpen || b.lane === 'top') && (
                  <div className="mt-0.5 text-[11px] text-zinc-300 leading-snug">
                    {isOpen ? truncate(b.content, 240) : truncate(b.content, 70)}
                  </div>
                )}
              </div>
              {/* Pointer line down/up to the chart bar — visual cue */}
              <div
                className="absolute"
                style={{
                  left: '50%',
                  width: 1,
                  height: 18,
                  top: b.lane === 'top' ? '100%' : 'auto',
                  bottom: b.lane === 'bottom' ? '100%' : 'auto',
                  background: style.color,
                  opacity: 0.45,
                }}
              />
            </button>
          </div>
        );
      })}

      {/* Bottom timeline rail — one dot per thought, click to jump */}
      {bubblePositions.length > 0 && (
        <div
          className="absolute left-0 right-0 pointer-events-auto"
          style={{ bottom: 30, height: 14 }}
          data-testid="chart-thought-timeline-rail"
        >
          <div className="relative w-full h-full">
            {bubblePositions.map((b) => {
              const style = styleFor(b.kind);
              return (
                <button
                  type="button"
                  key={`rail-${b.id}`}
                  onClick={() => handleJump(b.time_sec)}
                  data-testid={`chart-thought-rail-dot-${b.id}`}
                  title={`${fmtET12Sec(b.time_sec * 1000)} · ${truncate(b.content, 80)}`}
                  className="absolute w-2 h-2 rounded-full hover:scale-150 transition-transform"
                  style={{
                    left: `${b.left - 4}px`,
                    top: 4,
                    background: style.color,
                    boxShadow: `0 0 6px ${style.color}88`,
                  }}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default ChartThoughtBubblesOverlay;
