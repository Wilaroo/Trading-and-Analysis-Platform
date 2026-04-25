/**
 * ModelHealthScorecard — per-setup model health badges with one-click retrain.
 *
 * Polls GET /api/sentcom/model-health every 60s and renders a compact
 * colour-coded grid of (setup × timeframe) tiles. Click a tile to open the
 * detail panel (full metrics + promoted_at + Retrain button).
 *
 * Retrain flow:
 *   1. User clicks "Retrain" in the detail panel.
 *   2. POST /api/sentcom/retrain-model with { setup_type, bar_size }.
 *   3. Backend enqueues either a `setup_training` or `training` job via
 *      `job_queue_manager` and returns { success, job_id, target }.
 *   4. We poll GET /api/jobs/{job_id} every 5s until the job terminates
 *      (status ∈ completed|failed|cancelled).
 *   5. On completion we refetch model-health so the tile's MODE flips.
 *
 * MODE legend:
 *   HEALTHY   — both UP and DOWN recall ≥ 0.10  (green)
 *   MODE_C    — one class usable, other collapsed (amber)
 *   MODE_B    — both classes collapsed (red)
 *   MISSING   — no model in DB (grey)
 *
 * Part of the Command Center V5 scaffold (Stage 2f + 2f.1).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ShieldCheck, AlertTriangle, Zap, HelpCircle, RefreshCw, PlayCircle, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { safeGet, safePost } from '../../../utils/api';

const MODE_META = {
  HEALTHY: {
    label: 'HEALTHY',
    dot:    'bg-emerald-400',
    ring:   'ring-emerald-500/30',
    bg:     'bg-emerald-500/10',
    text:   'text-emerald-300',
    icon:   ShieldCheck,
  },
  MODE_C: {
    label: 'MODE C',
    dot:    'bg-amber-400',
    ring:   'ring-amber-500/30',
    bg:     'bg-amber-500/10',
    text:   'text-amber-300',
    icon:   Zap,
  },
  MODE_B: {
    label: 'MODE B',
    dot:    'bg-rose-500',
    ring:   'ring-rose-500/30',
    bg:     'bg-rose-500/10',
    text:   'text-rose-300',
    icon:   AlertTriangle,
  },
  MISSING: {
    label: 'MISSING',
    dot:    'bg-zinc-500',
    ring:   'ring-zinc-500/20',
    bg:     'bg-zinc-500/10',
    text:   'text-zinc-400',
    icon:   HelpCircle,
  },
};

// Any non-terminal job status we should keep polling on.
const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed', 'cancelled', 'error']);

const formatPct = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : `${(Number(v) * 100).toFixed(1)}%`;
const formatTime = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric' }); }
  catch { return '—'; }
};

const keyFor = (row) => `${row.setup_type}|${row.bar_size}`;

const HealthTile = ({ row, active, retraining, onClick }) => {
  const meta = MODE_META[row.mode] ?? MODE_META.MISSING;
  const label = row.setup_type === '__GENERIC__' ? 'GEN' : row.setup_type.replace('_', ' ');
  return (
    <button
      data-testid={`model-health-tile-${row.setup_type}-${row.bar_size.replace(/\s+/g, '')}`}
      onClick={onClick}
      className={`group relative text-left px-2 py-1.5 rounded-lg ring-1 transition-all hover:scale-[1.02] ${meta.bg} ${meta.ring} ${active ? 'ring-2 ring-white/40' : ''}`}
      title={`${row.setup_type} · ${row.bar_size} · ${meta.label}${retraining ? ' · retraining' : ''}`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-300 truncate max-w-[72px]">
          {label}
        </span>
        {retraining ? (
          <Loader2 className="w-2.5 h-2.5 text-sky-300 animate-spin" />
        ) : (
          <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
        )}
      </div>
      <div className="flex items-center justify-between gap-1 mt-0.5">
        <span className="text-[9px] text-zinc-500">{row.bar_size.replace(' mins', 'm').replace(' min', 'm').replace(' hour', 'h').replace(' day', 'd')}</span>
        <span className={`text-[9px] font-medium ${meta.text}`}>{retraining ? 'TRAIN…' : meta.label}</span>
      </div>
    </button>
  );
};

const RetrainButton = ({ row, jobState, onRetrain }) => {
  const status = jobState?.status;
  const progress = jobState?.progress;
  const isRunning = jobState && !TERMINAL_JOB_STATUSES.has(status);
  const isDone = status === 'completed';
  const isFailed = status === 'failed' || status === 'error' || status === 'cancelled';

  let body;
  let Icon = PlayCircle;
  let testid = `model-health-retrain-btn-${row.setup_type}-${row.bar_size.replace(/\s+/g, '')}`;
  let className = 'bg-sky-500/15 text-sky-200 hover:bg-sky-500/25 ring-sky-500/40';

  if (jobState?.state === 'queuing') {
    body = 'Queuing…'; Icon = Loader2; className = 'bg-zinc-700/30 text-zinc-300 ring-zinc-500/30';
  } else if (jobState?.state === 'error') {
    body = jobState?.error ? `Failed: ${jobState.error}` : 'Failed to queue'; Icon = XCircle; className = 'bg-rose-500/15 text-rose-300 ring-rose-500/40';
  } else if (isRunning) {
    const pctLabel = (typeof progress === 'number' && progress > 0) ? ` ${Math.round(progress)}%` : '';
    body = `Training${pctLabel}`; Icon = Loader2; className = 'bg-sky-500/15 text-sky-200 ring-sky-500/40 cursor-not-allowed';
  } else if (isDone) {
    body = 'Retrain complete — refreshed'; Icon = CheckCircle2; className = 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40';
  } else if (isFailed) {
    body = `Retrain ${status}`; Icon = XCircle; className = 'bg-rose-500/15 text-rose-300 ring-rose-500/40';
  } else {
    body = 'Retrain this model';
  }

  const spin = (Icon === Loader2);
  return (
    <button
      data-testid={testid}
      onClick={isRunning ? undefined : onRetrain}
      disabled={isRunning}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold tracking-wider uppercase ring-1 transition-colors ${className}`}
    >
      <Icon className={`w-3 h-3 ${spin ? 'animate-spin' : ''}`} />
      <span>{body}</span>
    </button>
  );
};

const ModeDetail = ({ row, jobState, onRetrain }) => {
  if (!row) return null;
  const meta = MODE_META[row.mode] ?? MODE_META.MISSING;
  const Icon = meta.icon;
  return (
    <div
      data-testid="model-health-detail"
      className="mt-2 flex items-start gap-3 px-3 py-2 rounded-lg bg-zinc-950/60 border border-white/5"
    >
      <Icon className={`w-4 h-4 mt-0.5 ${meta.text}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-xs font-semibold text-zinc-100">
            {row.setup_type === '__GENERIC__' ? 'Generic directional' : row.setup_type} · {row.bar_size}
          </span>
          <span className={`text-[10px] font-semibold uppercase tracking-wider ${meta.text}`}>
            {meta.label}
          </span>
          {row.version && (
            <span className="text-[10px] text-zinc-500 font-mono">{row.version}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-zinc-400 mt-0.5 flex-wrap">
          <span>Acc {formatPct(row.metrics?.accuracy)}</span>
          <span>R↑ {formatPct(row.metrics?.recall_up)}</span>
          <span>R↓ {formatPct(row.metrics?.recall_down)}</span>
          {row.metrics?.macro_f1 != null && (
            <span>F1 {formatPct(row.metrics.macro_f1)}</span>
          )}
          {row.promoted_at && (
            <span>· promoted {formatTime(row.promoted_at)}</span>
          )}
        </div>
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <RetrainButton row={row} jobState={jobState} onRetrain={onRetrain} />
          {jobState?.job_id && (
            <span data-testid="model-health-job-id" className="text-[10px] text-zinc-500 font-mono">job {jobState.job_id.slice(0, 8)}</span>
          )}
        </div>
      </div>
    </div>
  );
};

export const ModelHealthScorecard = ({
  pollIntervalMs = 60_000,
  className = '',
  defaultExpanded = false,
}) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [selectedKey, setSelectedKey] = useState(null);
  const [expanded, setExpanded] = useState(defaultExpanded);
  // jobStateByKey: { [rowKey]: { state, job_id, status, progress, error } }
  const [jobStateByKey, setJobStateByKey] = useState({});
  const pollTimersRef = useRef({});

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await safeGet('/api/sentcom/model-health');
      if (!resp) { setError('fetch failed'); return; }
      if (resp.success === false) { setError(resp.error || 'backend error'); return; }
      setData(resp);
    } catch (err) {
      setError(err?.message || 'Failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHealth(); }, [fetchHealth]);
  useEffect(() => {
    if (!pollIntervalMs) return undefined;
    const id = setInterval(fetchHealth, pollIntervalMs);
    return () => clearInterval(id);
  }, [fetchHealth, pollIntervalMs]);

  // Cleanup any in-flight job polls on unmount.
  useEffect(() => {
    const timers = pollTimersRef.current;
    return () => {
      Object.values(timers).forEach((t) => { if (t) clearInterval(t); });
    };
  }, []);

  const rows = data?.models ?? [];
  const counts = data?.counts ?? { HEALTHY: 0, MODE_C: 0, MODE_B: 0, MISSING: 0 };

  const selected = useMemo(() => {
    if (!selectedKey) return null;
    return rows.find(r => keyFor(r) === selectedKey) ?? null;
  }, [rows, selectedKey]);

  const pollJob = useCallback((rowKey, jobId) => {
    // Clear any existing poller for this key first.
    if (pollTimersRef.current[rowKey]) {
      clearInterval(pollTimersRef.current[rowKey]);
    }

    const tick = async () => {
      const resp = await safeGet(`/api/jobs/${jobId}`);
      if (!resp) return;  // transient fetch failure, next tick will retry
      const job = resp.job || resp;
      const status = (job.status || '').toLowerCase();
      const progress = typeof job.progress === 'number'
        ? job.progress
        : (typeof job.progress_pct === 'number' ? job.progress_pct : undefined);

      setJobStateByKey((prev) => ({
        ...prev,
        [rowKey]: { ...(prev[rowKey] || {}), state: 'polling', job_id: jobId, status, progress },
      }));

      if (TERMINAL_JOB_STATUSES.has(status)) {
        clearInterval(pollTimersRef.current[rowKey]);
        delete pollTimersRef.current[rowKey];
        // Refetch health so the tile flips to its new mode.
        fetchHealth();
      }
    };

    tick();  // fire once immediately
    pollTimersRef.current[rowKey] = setInterval(tick, 5000);
  }, [fetchHealth]);

  const handleRetrain = useCallback(async (row) => {
    const rowKey = keyFor(row);
    setJobStateByKey((prev) => ({ ...prev, [rowKey]: { state: 'queuing' } }));

    const resp = await safePost('/api/sentcom/retrain-model', {
      setup_type: row.setup_type,
      bar_size: row.bar_size,
    });

    if (!resp || resp.success === false) {
      const errMsg = resp?.error || 'queue failed';
      setJobStateByKey((prev) => ({ ...prev, [rowKey]: { state: 'error', error: errMsg } }));
      return;
    }

    const jobId = resp.job_id;
    setJobStateByKey((prev) => ({
      ...prev,
      [rowKey]: { state: 'polling', job_id: jobId, status: 'queued' },
    }));

    if (jobId) {
      pollJob(rowKey, jobId);
    }
  }, [pollJob]);

  return (
    <div
      data-testid="model-health-scorecard"
      data-help-id="gate-score"
      className={`relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-zinc-950/90 via-zinc-950/80 to-zinc-900/80 backdrop-blur-xl ${className}`}
    >
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
        <div className="flex items-center gap-3 flex-wrap">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span className="text-sm font-semibold text-zinc-100 tracking-tight">Model Health</span>
          <span className="text-[10px] text-zinc-500">· {rows.length} models</span>

          <div className="flex items-center gap-2 ml-2">
            {Object.entries(counts).map(([mode, n]) => {
              if (!n) return null;
              const meta = MODE_META[mode] ?? MODE_META.MISSING;
              return (
                <span
                  key={mode}
                  data-testid={`model-health-count-${mode}`}
                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium ${meta.bg} ${meta.text}`}
                >
                  <span className={`w-1 h-1 rounded-full ${meta.dot}`} />
                  {n} {meta.label}
                </span>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            data-testid="model-health-toggle"
            onClick={() => setExpanded(v => !v)}
            className="px-2 py-0.5 text-[11px] rounded-md text-zinc-400 hover:text-zinc-200 hover:bg-white/5 transition-colors"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          <button
            data-testid="model-health-refresh"
            onClick={fetchHealth}
            className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
            aria-label="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div data-testid="model-health-error" className="px-4 py-2 text-xs text-rose-400">
          {error}
        </div>
      )}

      {expanded && (
        <div className="p-3 space-y-3">
          <div
            data-testid="model-health-grid"
            className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-1.5"
          >
            {rows.map(r => {
              const rk = keyFor(r);
              const js = jobStateByKey[rk];
              const retraining = !!js && (js.state === 'queuing' || js.state === 'polling') && !TERMINAL_JOB_STATUSES.has(js.status);
              return (
                <HealthTile
                  key={rk}
                  row={r}
                  active={selectedKey === rk}
                  retraining={retraining}
                  onClick={() => setSelectedKey(selectedKey === rk ? null : rk)}
                />
              );
            })}
            {rows.length === 0 && !loading && (
              <div className="col-span-full text-xs text-zinc-500 text-center py-4">
                No models reported.
              </div>
            )}
          </div>

          <ModeDetail
            row={selected}
            jobState={selected ? jobStateByKey[keyFor(selected)] : null}
            onRetrain={() => selected && handleRetrain(selected)}
          />
        </div>
      )}
    </div>
  );
};

export default ModelHealthScorecard;
