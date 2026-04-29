/**
 * LastRunsTimeline — sparkline-style strip of the last 5 archived training
 * runs. Each dot encodes:
 *   - height/bar = `models_trained_count` (relative to the run with the
 *     highest count in the visible window — quick "did the latest run train
 *     fewer models than last time?" sanity check).
 *   - colour = trophy (emerald) vs non-trophy (rose).
 *   - tooltip = trained / failed counts + elapsed.
 *
 * Reads `/api/ai-training/recent-runs?limit=5`. Now that the trophy
 * archive write actually fires (2026-02 fix), this becomes a useful
 * regression-spotter without hunting through MongoDB.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Trophy, AlertTriangle } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export const LastRunsTimeline = ({ refreshToken = 0, limit = 5 }) => {
  const [runs, setRuns] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const resp = await fetch(
        `${BACKEND_URL}/api/ai-training/recent-runs?limit=${limit}`
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      if (body?.success) {
        setRuns(body.runs || []);
      } else {
        setErr(body?.error || 'Backend returned no runs');
      }
    } catch (e) {
      setErr(e?.message || 'Fetch failed');
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { reload(); }, [reload, refreshToken]);

  // Reverse the array so OLDEST is on the left, NEWEST on the right —
  // matches how operators read sparklines.
  const ordered = useMemo(() => {
    if (!Array.isArray(runs)) return [];
    return [...runs].reverse();
  }, [runs]);

  const maxCount = useMemo(
    () => ordered.reduce((m, r) => Math.max(m, r.models_trained_count || 0), 1),
    [ordered]
  );

  const latest = ordered.length ? ordered[ordered.length - 1] : null;

  return (
    <section data-testid="last-runs-timeline" className="rounded-md border border-zinc-800 bg-zinc-950/80">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Trophy className="w-3.5 h-3.5 text-amber-400" />
          <span className="v5-mono text-[12px] text-zinc-400 uppercase tracking-wider font-bold">
            Last {limit} Runs
          </span>
        </div>
        {latest && (
          <span
            data-testid="last-runs-latest-summary"
            className="v5-mono text-[11px] text-zinc-500 uppercase tracking-wider"
          >
            latest · {latest.models_trained_count} models · {latest.elapsed_human}
          </span>
        )}
      </div>

      <div className="p-3">
        {err && (
          <div
            data-testid="last-runs-error"
            className="flex items-center gap-2 text-rose-400 v5-mono text-[12px]"
          >
            <AlertTriangle className="w-3 h-3" />
            <span>{err}</span>
          </div>
        )}
        {!err && loading && !ordered.length && (
          <div className="v5-mono text-[12px] text-zinc-600">loading…</div>
        )}
        {!err && !loading && !ordered.length && (
          <div
            data-testid="last-runs-empty"
            className="v5-mono text-[12px] text-zinc-600"
          >
            No archived runs yet — kick off `Train All` to start the timeline.
          </div>
        )}
        {!err && ordered.length > 0 && (
          <div className="flex items-end gap-2 h-16" data-testid="last-runs-bars">
            {ordered.map((r, i) => {
              const pct = maxCount > 0
                ? Math.max(8, Math.round((r.models_trained_count / maxCount) * 100))
                : 8;
              const trophy = r.is_trophy && r.models_failed_count === 0;
              const bgClass = trophy
                ? 'bg-emerald-500/70 hover:bg-emerald-400'
                : 'bg-rose-500/70 hover:bg-rose-400';
              const ringClass = i === ordered.length - 1
                ? 'ring-1 ring-zinc-300/40'
                : '';
              const label = `${r.models_trained_count} trained · ${r.models_failed_count} failed · ${r.elapsed_human}` +
                            (r.completed_at ? ` · ${String(r.completed_at).slice(0, 16).replace('T', ' ')}` : '');
              return (
                <div
                  key={r.started_at || i}
                  data-testid={`last-runs-bar-${i}`}
                  title={label}
                  className="flex-1 flex flex-col items-center justify-end gap-1 min-w-0"
                >
                  <div className="v5-mono text-[11px] text-zinc-400 tabular-nums truncate w-full text-center">
                    {r.models_trained_count}
                  </div>
                  <div
                    className={`w-full rounded-sm transition-all ${bgClass} ${ringClass}`}
                    style={{ height: `${pct}%` }}
                  />
                  <div className="v5-mono text-[8px] text-zinc-600 tabular-nums">
                    {trophy ? '★' : '×'}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};

export default LastRunsTimeline;
