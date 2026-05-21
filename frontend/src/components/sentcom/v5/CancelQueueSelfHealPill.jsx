/**
 * CancelQueueSelfHealPill — v19.34.65c (Feb 2026).
 *
 * Tiny status pill in the V5 HUD top strip showing the count of
 * cancellation queue entries the v19.34.65 + v19.34.65b stale-drop
 * guards have promoted to `stale_dropped` this session.
 *
 * Each "self-heal" is an IB order the bot tried to cancel that IB
 * had already disposed of (Error 10147 family, or 3 pending-poll
 * serves with no result). Pre-v19.34.65 these accumulated into a
 * relentless `Error 10147` log-spam loop; the guards now contain
 * each loop to ≤3 attempts before the entry is silently terminated.
 *
 * Visibility rules:
 *   - Only renders when stale_dropped >= 1 (zero saves = nothing
 *     to surface; the pill stays hidden to reduce HUD clutter).
 *   - Color = sky-blue (informational, not an error — this is the
 *     bot succeeding at containment).
 *   - Hover tooltip lists the most recent stale-dropped orders.
 *
 * Polls /api/ib/cancellations/stats every 30s.
 *
 * Sits next to DriftGuardPill in the HUD top strip.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtAgo = (iso) => {
  if (!iso) return '';
  const ts = Date.parse(iso) / 1000;
  if (Number.isNaN(ts)) return '';
  const sec = Math.max(0, Date.now() / 1000 - ts);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
};

const REASON_LABEL = {
  fatal_ib_error: 'fatal IB error (10147/10148/200)',
  exceeded_failure_threshold: 'exceeded 3 reported failures',
  exceeded_poll_served_count_no_result: 'exceeded 3 pending-polls (silent pusher fail)',
  pusher_reported_not_found: 'pusher reported not_found',
  other: 'other',
};

export default function CancelQueueSelfHealPill() {
  const [data, setData] = useState(null);
  const [hover, setHover] = useState(false);
  const timer = useRef(null);

  const tick = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/ib/cancellations/stats`);
      if (!r.ok) return;
      const j = await r.json();
      if (j && j.success) setData(j);
    } catch (_) { /* decorative pill — silent on transient errors */ }
  }, []);

  useEffect(() => {
    tick();
    timer.current = setInterval(tick, 30000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [tick]);

  const totals = data?.totals || {};
  const staleCount = totals.stale_dropped || 0;
  if (!data || staleCount < 1) return null;

  const breakdown = data.stale_dropped_breakdown || {};
  const recent = data.recent_stale_dropped || [];
  const mostRecentAgo = recent.length > 0 ? fmtAgo(recent[0].completed_at) : '';

  return (
    <div
      className="relative inline-flex items-center"
      data-testid="cancel-queue-selfheal-pill"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div
        className="px-2 py-0.5 rounded-md text-[12px] font-mono font-semibold tabular-nums whitespace-nowrap select-none cursor-help"
        style={{
          background: 'rgba(56, 189, 248, 0.15)',
          color: '#7dd3fc',
          border: '1px solid rgba(56, 189, 248, 0.40)',
        }}
        title={`v19.34.65 cancel-queue self-heal: ${staleCount} stale IB order(s) auto-dropped this session.${mostRecentAgo ? ` Last: ${mostRecentAgo}.` : ''}`}
        data-testid="cancel-queue-selfheal-pill-summary"
      >
        SELF-HEAL · {staleCount}
        <span className="opacity-60 ml-1">{mostRecentAgo && `· ${mostRecentAgo}`}</span>
      </div>

      {hover && (
        <div
          className="absolute top-full right-0 mt-1 z-50 px-3 py-2 rounded-md shadow-xl"
          style={{
            background: 'rgba(15, 23, 42, 0.97)',
            border: '1px solid rgba(56, 189, 248, 0.35)',
            minWidth: '340px',
          }}
          data-testid="cancel-queue-selfheal-pill-tooltip"
        >
          <div className="text-[11px] font-bold text-sky-300 mb-1 uppercase tracking-wider">
            Cancel-Queue Self-Heal ({staleCount})
          </div>
          <div className="text-[10px] text-zinc-400 mb-2">
            Dead IB orders the bot stopped re-trying. Each save = one ended log-spam loop.
          </div>

          {/* Breakdown by reason */}
          <div className="mb-2 pb-2 border-b border-zinc-800">
            <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Reasons</div>
            <div className="flex flex-col gap-0.5">
              {Object.entries(breakdown)
                .filter(([, v]) => (v || 0) > 0)
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between text-[11px] font-mono text-zinc-300">
                    <span className="text-zinc-400">{REASON_LABEL[k] || k}</span>
                    <span className="text-sky-300 font-bold">{v}</span>
                  </div>
                ))}
            </div>
          </div>

          {/* Recent entries */}
          {recent.length > 0 && (
            <>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Most Recent</div>
              <div className="flex flex-col gap-1">
                {recent.slice(0, 6).map((e) => (
                  <div
                    key={e.ib_order_id}
                    className="flex justify-between gap-2 text-[11px] font-mono text-zinc-300"
                    data-testid={`cancel-queue-selfheal-pill-row-${e.ib_order_id}`}
                  >
                    <span className="font-bold text-sky-200">#{e.ib_order_id}</span>
                    <span
                      className="text-zinc-500 truncate max-w-[200px]"
                      title={e.reason || e.error || ''}
                    >
                      {e.reason || '—'}
                    </span>
                    <span className="text-zinc-500 shrink-0">{fmtAgo(e.completed_at)}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] text-zinc-600">
            Session started {fmtAgo(data.session_started_at)} · queue size {data.queue_size}
          </div>
        </div>
      )}
    </div>
  );
}
