/**
 * LastTrophyRunCard — permanent SLA badge showing the most recent
 * SUCCESSFUL training pipeline run (0 failures, 0 errors). Survives
 * starting a new run because it reads from `training_runs_archive`,
 * not the live status. Use in the FreshnessInspector underneath the
 * LastTrainingRunCard so operators always have a green/amber/red
 * "is the AI brain healthy?" indicator at a glance.
 *
 * Endpoint: GET /api/ai-training/last-trophy-run
 *   - returns {found: false} when no archived run exists
 *   - returns full breakdown including phase_recurrence_watch_ok (P5/P8)
 *     and headline_accuracies for the standout models.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtAge = (iso) => {
  if (!iso) return '—';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return 'just now';
    if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
    if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
    if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
    return `${Math.round(ms / 86_400_000)}d ago`;
  } catch {
    return '—';
  }
};

const TONE = {
  emerald: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
  amber:   'bg-amber-900/30 text-amber-200 border-amber-800',
  rose:    'bg-rose-900/30 text-rose-200 border-rose-800',
  zinc:    'bg-zinc-900/40 text-zinc-300 border-zinc-800',
  cyan:    'bg-cyan-900/30 text-cyan-200 border-cyan-800',
};

const accTone = (acc) => {
  if (acc == null || isNaN(acc)) return 'zinc';
  if (acc >= 0.70) return 'emerald';
  if (acc >= 0.55) return 'emerald';
  if (acc >= 0.50) return 'amber';
  return 'rose';
};

const Pill = ({ label, value, tone = 'zinc', testid }) => (
  <div data-testid={testid}
       className={`px-2 py-1 rounded border v5-mono text-[12px] ${TONE[tone] || TONE.zinc}`}>
    <span className="opacity-60 mr-1">{label}</span>
    <span className="font-bold">{value}</span>
  </div>
);

export const LastTrophyRunCard = ({ refreshToken = 0 }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/ai-training/last-trophy-run`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshToken]);

  // Header tone — overall verdict
  const verdict = useMemo(() => {
    if (!data || !data.found) return 'zinc';
    if (!data.is_trophy) return 'amber';
    if (!data.phase_recurrence_watch_ok) return 'amber';
    return 'emerald';
  }, [data]);

  const verdictLabel = verdict === 'emerald' ? 'TROPHY ✓'
                     : verdict === 'amber'   ? 'PARTIAL'
                     : '—';

  return (
    <section data-testid="last-trophy-run-card"
             data-help-id="last-trophy-run"
             data-verdict={verdict}
             className="space-y-2">
      <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide flex items-center gap-2">
        Last successful trophy run
        {loading && (
          <span data-testid="trophy-loading" className="text-zinc-600">· loading…</span>
        )}
        <span className="ml-auto text-zinc-600 normal-case tracking-normal text-[11px]">
          last completed pipeline · 0-failure SLA
        </span>
      </div>

      {/* Verdict pill */}
      <div className={`flex items-start gap-3 p-3 rounded border ${TONE[verdict]}`}
           data-testid="trophy-verdict-pill">
        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2.5 h-2.5 rounded-full ${
            verdict === 'emerald' ? 'bg-emerald-400'
            : verdict === 'amber' ? 'bg-amber-400'
            : 'bg-zinc-500'}`} />
          <span className="v5-mono font-bold text-sm uppercase tracking-wider">
            {verdictLabel}
          </span>
        </div>
        <div className="flex-1 min-w-0 v5-mono text-[13px] leading-tight pt-0.5">
          {error && !data ? (
            <span className="text-rose-400" data-testid="trophy-error">
              /api/ai-training/last-trophy-run unreachable — {error}
            </span>
          ) : !data?.found ? (
            <span className="text-zinc-400">
              No completed training run on file. Click <span className="text-cyan-300">Train All</span> in the NIA panel.
            </span>
          ) : (
            <span className="opacity-90">
              {data.models_trained_count} models · {data.models_failed_count} failed · {data.errors} errors · {data.elapsed_human} · {fmtAge(data.completed_at)}
            </span>
          )}
        </div>
      </div>

      {/* Top-line numbers */}
      {data?.found && (
        <div className="flex flex-wrap gap-1.5" data-testid="trophy-totals">
          <Pill testid="trophy-total-trained" label="trained"
                value={data.models_trained_count}
                tone={data.models_trained_count >= 100 ? 'emerald' : 'amber'} />
          <Pill testid="trophy-total-failed" label="failed"
                value={data.models_failed_count}
                tone={data.models_failed_count === 0 ? 'emerald' : 'amber'} />
          <Pill testid="trophy-total-errors" label="errors"
                value={data.errors}
                tone={data.errors === 0 ? 'emerald' : 'rose'} />
          <Pill testid="trophy-elapsed" label="elapsed"
                value={data.elapsed_human} tone="cyan" />
          <Pill testid="trophy-recurrence-ok" label="P5/P8 ok"
                value={data.phase_recurrence_watch_ok ? '✓' : '✗'}
                tone={data.phase_recurrence_watch_ok ? 'emerald' : 'rose'} />
        </div>
      )}

      {/* Phase health strip — recurrence-watch phases highlighted */}
      {data?.found && data.phase_health?.length > 0 && (
        <div data-testid="trophy-phase-health"
             className="grid grid-cols-2 sm:grid-cols-4 gap-1">
          {data.phase_health.map((p) => {
            const tone = !p.ok ? 'rose'
                       : p.is_recurrence_watch ? 'emerald'
                       : 'zinc';
            return (
              <div key={p.phase}
                   data-testid={`trophy-phase-${p.phase}`}
                   data-recurrence-watch={p.is_recurrence_watch}
                   data-ok={p.ok}
                   className={`px-2 py-1 rounded border v5-mono text-[9.5px] ${TONE[tone]}
                              ${p.is_recurrence_watch ? 'ring-1 ring-emerald-500/30' : ''}`}>
                <div className="flex items-center gap-1">
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    p.ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                  <span className="font-bold">{p.phase}</span>
                  {p.is_recurrence_watch && (
                    <span className="text-emerald-300 text-[8px] ml-auto">★</span>
                  )}
                </div>
                <div className="opacity-75 truncate">{p.label}</div>
                <div className="opacity-90 tabular-nums">
                  {p.models}/{p.total || '?'}
                  {typeof p.acc === 'number' && (
                    <span className="ml-1 opacity-70">· {(p.acc * 100).toFixed(0)}%</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Headline accuracies — top performers from this run */}
      {data?.found && data.headline_accuracies?.length > 0 && (
        <div data-testid="trophy-headline-accuracies" className="space-y-0.5">
          <div className="v5-mono text-[11px] uppercase text-zinc-500 tracking-wide">
            Top accuracies this run
          </div>
          {data.headline_accuracies.slice(0, 5).map((m, i) => {
            const tone = accTone(m.accuracy);
            return (
              <div key={i}
                   data-testid={`trophy-headline-${i}`}
                   className="flex items-center gap-2 v5-mono text-[12px]">
                <span className={`w-1.5 h-1.5 rounded-full ${
                  tone === 'emerald' ? 'bg-emerald-400'
                  : tone === 'amber' ? 'bg-amber-400'
                  : 'bg-rose-400'}`} />
                <span className="truncate flex-1">{m.model}</span>
                <span className={`tabular-nums ${
                  tone === 'emerald' ? 'text-emerald-300'
                  : tone === 'amber' ? 'text-amber-300'
                  : 'text-rose-300'}`}>
                  {(m.accuracy * 100).toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Footer note when synthesized from live status (pre-archive runs) */}
      {data?.found && data._synthesized_from_live && (
        <div className="v5-mono text-[11px] text-zinc-500">
          (Synthesized from live status — future runs will be archived
          automatically.)
        </div>
      )}
    </section>
  );
};

export default LastTrophyRunCard;
