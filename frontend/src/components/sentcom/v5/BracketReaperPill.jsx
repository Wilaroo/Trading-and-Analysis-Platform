/**
 * BracketReaperPill — V5 status-strip indicator that shows when the
 * v19.34.153 first-tick bracket-reaper safety net has engaged.
 *
 * Listens to the sentcom stream for two events:
 *   • `first_tick_bracket_reaper_v19_34_153` — the safety net fired,
 *     cancelling orphan brackets BEFORE they could create reverse
 *     positions.
 *   • `wrong_direction_phantom_swept` — a reverse position was
 *     DETECTED at IB (the safety net failed or fired too late).
 *
 * The pill is normally GREEN with a counter "0 reaped"; it flashes
 * AMBER for 60s after each reaper event, and turns RED with a
 * "REVERSE AT IB" badge for the rest of the session after any
 * wrong-direction event.
 *
 * 2026-02-13 v19.34.153
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react';
import api from '../../../utils/api';

const POLL_MS = 30000;

export const BracketReaperPill = ({ onStatus }) => {
  const [stats, setStats] = useState({
    reaper_events_today: 0,
    reverse_positions_today: 0,
    last_event_ts: null,
    last_event_type: null,
    last_event_symbol: null,
  });

  const refresh = useCallback(async () => {
    // Fetch recent stream events tagged with the v153 reaper or the
    // wrong-direction sweep, count them, surface the latest.
    try {
      const res = await api.get(
        '/api/sentcom/stream/history?minutes=720&limit=200&q=first_tick_bracket_reaper_v19_34_153,wrong_direction_phantom_swept'
      );
      const events = res?.data?.events || res?.data || [];
      let reaper = 0;
      let reverse = 0;
      let last = null;
      for (const e of events) {
        const ev = e.event || e.payload?.event;
        if (ev === 'first_tick_bracket_reaper_v19_34_153') reaper++;
        else if (ev === 'wrong_direction_phantom_swept') reverse++;
        if (!last || (e.timestamp || e.ts) > (last.timestamp || last.ts)) last = e;
      }
      setStats({
        reaper_events_today: reaper,
        reverse_positions_today: reverse,
        last_event_ts: last?.timestamp || last?.ts || null,
        last_event_type: last?.event || last?.payload?.event || null,
        last_event_symbol: last?.symbol || last?.payload?.symbol || null,
      });
    } catch {
      // silent — stream history endpoint may not be available; pill
      // gracefully shows zeros.
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Health state.
  const hasReverse = stats.reverse_positions_today > 0;
  const hasReaper = stats.reaper_events_today > 0;
  const isClean = !hasReverse && !hasReaper;
  useEffect(() => {
    onStatus?.(hasReverse ? 'red' : hasReaper ? 'amber' : 'green');
  }, [onStatus, hasReverse, hasReaper]);
  const palette = hasReverse
    ? 'text-rose-300 border-rose-500/40 bg-rose-900/15'
    : hasReaper
      ? 'text-amber-300 border-amber-500/40 bg-amber-900/15'
      : 'text-emerald-300 border-emerald-500/30 bg-emerald-900/10';

  const Icon = hasReverse ? ShieldAlert : hasReaper ? Shield : ShieldCheck;

  const tooltip = [
    `Bracket reaper events today: ${stats.reaper_events_today}`,
    `Reverse positions detected: ${stats.reverse_positions_today}`,
    stats.last_event_type ? `Last: ${stats.last_event_type} ${stats.last_event_symbol || ''}` : null,
  ].filter(Boolean).join('\n');

  return (
    <div
      data-testid="bracket-reaper-pill"
      className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap"
      title={tooltip}
    >
      <Icon className="w-3 h-3 opacity-70" />
      <span
        data-testid="bracket-reaper-pill-label"
        className={`px-1.5 py-0.5 rounded text-[13px] font-bold tracking-wider border ${palette}`}
      >
        {isClean
          ? 'BRACKETS OK'
          : hasReverse
            ? `🚨 ${stats.reverse_positions_today} REVERSE AT IB`
            : `${stats.reaper_events_today} REAPED`}
      </span>
      {hasReaper && !hasReverse && (
        <span className="text-zinc-500 v5-mono text-[12px]">
          last: <span className="text-zinc-200 font-bold">
            {stats.last_event_symbol || '—'}
          </span>
        </span>
      )}
    </div>
  );
};

export default BracketReaperPill;
