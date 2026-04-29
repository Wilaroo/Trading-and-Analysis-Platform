/**
 * LastTrainingRunCard — sibling tile to BackfillReadinessCard, surfaces
 * "what happened on the most recent training run?" without dropping
 * into terminal logs. Renders inside FreshnessInspector right under the
 * readiness card.
 *
 * Polls `GET /api/ai-training/status` on mount + whenever `refreshToken`
 * changes. While a training run is in progress the card flips to a
 * "running" mode showing live phase / progress / ETA.
 *
 * Each per-phase tile is click-to-expand (same UX as the readiness
 * tiles) and shows the actual model list + accuracies for that phase.
 * Special highlighting on P5 (Sector-Relative) and P8 (Ensemble) — the
 * two phases that were recurring failures across prior sessions.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const STATUS_STYLE = {
  idle: {
    pill:  'bg-zinc-900/40 text-zinc-300 border-zinc-700',
    dot:   'bg-zinc-500',
    label: 'IDLE',
  },
  running: {
    pill:  'bg-cyan-900/40 text-cyan-200 border-cyan-700',
    dot:   'bg-cyan-400 animate-pulse',
    label: 'RUNNING',
  },
  completed: {
    pill:  'bg-emerald-900/40 text-emerald-200 border-emerald-700',
    dot:   'bg-emerald-400',
    label: 'COMPLETED',
  },
  cancelled: {
    pill:  'bg-amber-900/40 text-amber-200 border-amber-700',
    dot:   'bg-amber-400',
    label: 'CANCELLED',
  },
  error: {
    pill:  'bg-rose-900/40 text-rose-200 border-rose-700',
    dot:   'bg-rose-400 animate-pulse',
    label: 'ERROR',
  },
  unknown: {
    pill:  'bg-zinc-900/40 text-zinc-400 border-zinc-800',
    dot:   'bg-zinc-500',
    label: '—',
  },
};

// Map raw pipeline.phase values → human label + key for per-phase breakdown.
const PHASE_LABELS = {
  P1: 'P1 · Generic Directional',
  P2: 'P2 · Probability',
  P3: 'P3 · Volatility',
  P4: 'P4 · Hierarchical',
  P5: 'P5 · Sector-Relative',
  P6: 'P6 · Deep Learning',
  P7: 'P7 · Reinforcement',
  P8: 'P8 · Ensemble',
};

// The two phases known to have failed in prior sessions — get a
// dedicated visual treatment so the user can spot them immediately.
const RECURRING_FAILURE_PHASES = new Set(['P5', 'P8']);

const fmtDuration = (seconds) => {
  if (seconds == null || isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h${m > 0 ? ` ${m}m` : ''}`;
};

const fmtAge = (iso) => {
  if (!iso) return '—';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return 'just now';
    if (ms < 60_000)        return `${Math.round(ms / 1000)}s ago`;
    if (ms < 3_600_000)     return `${Math.round(ms / 60_000)}m ago`;
    if (ms < 86_400_000)    return `${Math.round(ms / 3_600_000)}h ago`;
    return `${Math.round(ms / 86_400_000)}d ago`;
  } catch {
    return '—';
  }
};

const phaseKeyFromBreakdownKey = (k) => {
  // Backend phase keys may be "P1" / "p1" / "1" / "generic_directional" etc.
  if (!k) return null;
  const upper = String(k).toUpperCase();
  const direct = upper.match(/^P(\d+)$/);
  if (direct) return `P${direct[1]}`;
  const num = upper.match(/^(\d+)$/);
  if (num) return `P${num[1]}`;
  return null;
};

const phaseStatusTone = (phase) => {
  if (!phase) return 'zinc';
  const total = phase.total ?? phase.target ?? 0;
  const done  = phase.models ?? phase.completed ?? 0;
  const failed = phase.failed ?? 0;
  if (failed > 0) return 'amber';
  if (total === 0) return 'zinc';
  if (done === 0)            return 'rose';
  if (done < total)          return 'amber';
  return 'emerald';
};

const PHASE_TONE_STYLES = {
  zinc:    'bg-zinc-900/40 text-zinc-300 border-zinc-800',
  emerald: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
  amber:   'bg-amber-900/30 text-amber-200 border-amber-800',
  rose:    'bg-rose-900/30 text-rose-200 border-rose-800',
  cyan:    'bg-cyan-900/30 text-cyan-200 border-cyan-800',
};

const NumPill = ({ label, value, tone = 'zinc', testid }) => (
  <div data-testid={testid}
       className={`px-2 py-1 rounded border v5-mono text-[12px] ${PHASE_TONE_STYLES[tone] || PHASE_TONE_STYLES.zinc}`}>
    <span className="opacity-60 mr-1">{label}</span>
    <span className="font-bold">{value}</span>
  </div>
);

const PhaseDrawer = ({ phaseKey, phase, recentlyCompleted = [] }) => {
  // Pick out models from recently_completed that belong to this phase.
  // Backend's recently_completed shape: [{name, accuracy, phase, ...}]
  const ours = useMemo(
    () => recentlyCompleted.filter((m) => {
      const k = phaseKeyFromBreakdownKey(m.phase) || phaseKeyFromBreakdownKey(m.phase_id);
      return k === phaseKey;
    }),
    [recentlyCompleted, phaseKey]
  );

  return (
    <div data-testid={`training-drawer-${phaseKey}`} className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <NumPill testid={`${phaseKey}-models`} label="models" value={`${phase.models ?? 0}/${phase.total ?? '?'}`}
                 tone={phaseStatusTone(phase)} />
        <NumPill testid={`${phaseKey}-failed`} label="failed" value={phase.failed ?? 0}
                 tone={(phase.failed ?? 0) > 0 ? 'amber' : 'emerald'} />
        {phase.acc != null && phase.acc !== '-' && (
          <NumPill testid={`${phaseKey}-acc`} label="avg_acc"
                   value={typeof phase.acc === 'number' ? `${(phase.acc * 100).toFixed(1)}%` : phase.acc}
                   tone={typeof phase.acc === 'number' && phase.acc >= 0.55 ? 'emerald'
                       : typeof phase.acc === 'number' && phase.acc >= 0.52 ? 'amber' : 'rose'} />
        )}
        {phase.eta && phase.eta !== 'running' && (
          <NumPill testid={`${phaseKey}-eta`} label="eta" value={phase.eta} tone="cyan" />
        )}
      </div>

      {RECURRING_FAILURE_PHASES.has(phaseKey) && (phase.models ?? 0) === 0 && (
        <div data-testid={`${phaseKey}-warning`}
             className="v5-mono text-[12px] text-rose-200 bg-rose-900/20 border border-rose-800/50 rounded p-1.5">
          ⚠ This phase failed in 2 prior sessions ({phaseKey === 'P5'
            ? 'Sector-Relative trained 0 models'
            : 'P8 _1day_predictor UnboundLocalError'}). If it stays at 0/?, re-check after current run finishes.
        </div>
      )}

      {ours.length > 0 ? (
        <div className="space-y-0.5">
          <div className="v5-mono text-[11px] uppercase text-zinc-500 tracking-wide">
            Recently completed
          </div>
          {ours.slice(0, 12).map((m, i) => {
            const acc = typeof m.accuracy === 'number' ? m.accuracy : null;
            const tone = acc != null
              ? (acc >= 0.55 ? 'emerald' : acc >= 0.52 ? 'amber' : 'rose')
              : 'zinc';
            return (
              <div key={i} data-testid={`${phaseKey}-model-${i}`}
                   className="flex items-center gap-2 v5-mono text-[12px]">
                <span className={`w-1.5 h-1.5 rounded-full ${
                  tone === 'emerald' ? 'bg-emerald-400'
                  : tone === 'amber' ? 'bg-amber-400'
                  : tone === 'rose'  ? 'bg-rose-400'
                  : 'bg-zinc-500'}`} />
                <span className="truncate flex-1">{m.name || m.model || `model_${i}`}</span>
                {acc != null && (
                  <span className={`tabular-nums ${
                    tone === 'emerald' ? 'text-emerald-300'
                    : tone === 'amber' ? 'text-amber-300'
                    : 'text-rose-300'}`}>
                    {(acc * 100).toFixed(1)}%
                  </span>
                )}
              </div>
            );
          })}
          {ours.length > 12 && (
            <div className="v5-mono text-[11px] text-zinc-500">+{ours.length - 12} more</div>
          )}
        </div>
      ) : (phase.models ?? 0) === 0 ? (
        <div className="v5-mono text-[12px] text-zinc-500">
          No models trained for this phase yet.
        </div>
      ) : null}
    </div>
  );
};

export const LastTrainingRunCard = ({ refreshToken = 0 }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/ai-training/status`);
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

  useEffect(() => {
    load();
  }, [load, refreshToken]);

  // Auto-poll every 30s when training is running so the live phase/ETA
  // stays current without the user manually refreshing.
  const isRunning = data?.task_status === 'running';
  useEffect(() => {
    if (!isRunning) return undefined;
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [isRunning, load]);

  const status = data?.task_status || 'unknown';
  const style = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  const pipeline = data?.pipeline_status || {};
  const breakdown = pipeline.phase_breakdown || {};
  const recentlyCompleted = pipeline.recently_completed || [];

  const totalDone = Object.values(breakdown).reduce((s, p) => s + (p.models ?? 0), 0);
  const totalTarget = Object.values(breakdown).reduce((s, p) => s + (p.total ?? 0), 0);
  const totalFailed = Object.values(breakdown).reduce((s, p) => s + (p.failed ?? 0), 0);

  const summary = isRunning
    ? `Running ${pipeline.phase || '—'} · model ${pipeline.current_model || '—'} · ${totalDone}/${totalTarget || '?'} done · ETA ${pipeline.eta_human || pipeline.eta || '—'}`
    : status === 'completed'
      ? `Last run completed ${fmtAge(pipeline.completed_at || pipeline.last_finished_at)} · ${totalDone}/${totalTarget || '?'} models · ${totalFailed} failed`
      : status === 'idle'
        ? (totalDone > 0
            ? `Last run finished ${fmtAge(pipeline.completed_at || pipeline.last_finished_at)} · ${totalDone}/${totalTarget || '?'} models · ${totalFailed} failed`
            : 'No training runs yet. Click Train All in the NIA panel.')
        : `Status: ${status}`;

  return (
    <section data-testid="last-training-run-card" data-help-id="last-training-run" className="space-y-2">
      <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide flex items-center gap-2">
        Last training run
        {loading && (
          <span data-testid="training-loading" className="text-zinc-600">· loading…</span>
        )}
        <span className="ml-auto text-zinc-600 normal-case tracking-normal text-[11px]">
          tip: click a phase tile to drill in
        </span>
      </div>

      <div
        className={`flex items-start gap-3 p-3 rounded border ${style.pill}`}
        data-testid="training-status-pill"
        data-status={status}
      >
        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
          <span className="v5-mono font-bold text-sm uppercase tracking-wider">
            {style.label}
          </span>
        </div>
        <div className="flex-1 min-w-0 v5-mono text-[13px] leading-tight pt-0.5 break-words">
          {error && !data ? (
            <span className="text-rose-400" data-testid="training-error">
              /api/ai-training/status unreachable — {error}
            </span>
          ) : (
            <span className="opacity-90">{summary}</span>
          )}
        </div>
      </div>

      {/* Top-line numbers — shown when we have any breakdown at all */}
      {Object.keys(breakdown).length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="training-totals">
          <NumPill testid="train-total-done" label="models"
                   value={`${totalDone}/${totalTarget || '?'}`}
                   tone={totalDone === 0 ? 'rose'
                       : totalDone < totalTarget ? 'amber' : 'emerald'} />
          <NumPill testid="train-total-failed" label="failed" value={totalFailed}
                   tone={totalFailed > 0 ? 'amber' : 'emerald'} />
          {pipeline.elapsed_seconds != null && (
            <NumPill testid="train-elapsed" label="elapsed"
                     value={fmtDuration(pipeline.elapsed_seconds)} tone="cyan" />
          )}
          {pipeline.errors != null && pipeline.errors > 0 && (
            <NumPill testid="train-errors" label="errors" value={pipeline.errors} tone="rose" />
          )}
        </div>
      )}

      {/* Per-phase grid — clickable tiles */}
      {Object.keys(breakdown).length > 0 && (
        <div data-testid="training-phases-grid"
             className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'].map((pk) => {
            const phase = breakdown[pk];
            if (!phase) return null;
            const tone = phaseStatusTone(phase);
            const isOpen = expanded === pk;
            const recurring = RECURRING_FAILURE_PHASES.has(pk);
            const tileClass = `${PHASE_TONE_STYLES[tone] || PHASE_TONE_STYLES.zinc}` +
                              ` ${recurring && (phase.models ?? 0) === 0 ? 'ring-1 ring-rose-500/40' : ''}` +
                              ` ${isOpen ? 'sm:col-span-2 ring-1 ring-cyan-500/30' : ''}`;
            return (
              <div
                role="button"
                tabIndex={0}
                key={pk}
                data-testid={`training-phase-${pk}`}
                data-status={tone}
                data-expanded={isOpen}
                onClick={() => setExpanded(isOpen ? null : pk)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setExpanded(isOpen ? null : pk);
                  }
                }}
                className={`cursor-pointer text-left px-2 py-1.5 rounded border hover:brightness-110 transition focus:outline-none focus:ring-1 focus:ring-cyan-500/40 ${tileClass}`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    tone === 'emerald' ? 'bg-emerald-400'
                    : tone === 'amber' ? 'bg-amber-400'
                    : tone === 'rose'  ? 'bg-rose-400'
                    : 'bg-zinc-500'}`} />
                  <span className="v5-mono text-[12px] font-bold">
                    {PHASE_LABELS[pk] || pk}
                  </span>
                  <span className="v5-mono text-[12px] tabular-nums opacity-80 ml-auto">
                    {phase.models ?? 0}/{phase.total ?? '?'}
                  </span>
                  <span className="v5-mono text-[12px] opacity-60 ml-1" aria-hidden>
                    {isOpen ? '▾' : '▸'}
                  </span>
                </div>
                {phase.acc != null && phase.acc !== '-' && (
                  <div className="v5-mono text-[11px] opacity-75 mt-0.5">
                    avg acc {typeof phase.acc === 'number' ? `${(phase.acc * 100).toFixed(1)}%` : phase.acc}
                    {phase.failed > 0 ? ` · ${phase.failed} failed` : ''}
                  </div>
                )}
                {isOpen && (
                  <div
                    data-testid={`training-phase-drawer-${pk}`}
                    className="mt-2 pt-2 border-t border-current/20"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <PhaseDrawer phaseKey={pk} phase={phase}
                                 recentlyCompleted={recentlyCompleted} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* No breakdown at all — empty state */}
      {Object.keys(breakdown).length === 0 && status === 'idle' && (
        <div data-testid="training-empty-state"
             className="v5-mono text-[12px] text-zinc-500 px-2 py-3 rounded border border-zinc-800 bg-zinc-900/30">
          No training runs recorded. Trigger one from the NIA panel — Train All
          (regular) or Shift-click to bypass the Backfill Readiness gate.
        </div>
      )}
    </section>
  );
};

export default LastTrainingRunCard;
