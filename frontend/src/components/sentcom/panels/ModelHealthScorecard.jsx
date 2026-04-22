/**
 * ModelHealthScorecard — per-setup model health badges.
 *
 * Polls GET /api/sentcom/model-health every 60s and renders a compact
 * colour-coded grid of (setup × timeframe) tiles. Click a tile to surface
 * the full metrics tooltip (accuracy / recall / f1 / promoted_at).
 *
 * MODE legend:
 *   HEALTHY   — both UP and DOWN recall ≥ 0.10  (green)
 *   MODE_C    — one class usable, other collapsed (amber)
 *   MODE_B    — both classes collapsed (red)
 *   MISSING   — no model in DB (grey)
 *
 * Part of the Command Center V5 scaffold (Stage 2f).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ShieldCheck, AlertTriangle, Zap, HelpCircle, RefreshCw } from 'lucide-react';
import { safeGet } from '../../../utils/api';

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

const formatPct = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : `${(Number(v) * 100).toFixed(1)}%`;
const formatTime = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric' }); }
  catch (_) { return '—'; }
};

const HealthTile = ({ row, active, onClick }) => {
  const meta = MODE_META[row.mode] ?? MODE_META.MISSING;
  const label = row.setup_type === '__GENERIC__' ? 'GEN' : row.setup_type.replace('_', ' ');
  return (
    <button
      data-testid={`model-health-tile-${row.setup_type}-${row.bar_size.replace(/\s+/g, '')}`}
      onClick={onClick}
      className={`group relative text-left px-2 py-1.5 rounded-lg ring-1 transition-all hover:scale-[1.02] ${meta.bg} ${meta.ring} ${active ? 'ring-2 ring-white/40' : ''}`}
      title={`${row.setup_type} · ${row.bar_size} · ${meta.label}`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-zinc-300 truncate max-w-[72px]">
          {label}
        </span>
        <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      </div>
      <div className="flex items-center justify-between gap-1 mt-0.5">
        <span className="text-[9px] text-zinc-500">{row.bar_size.replace(' mins', 'm').replace(' min', 'm').replace(' hour', 'h').replace(' day', 'd')}</span>
        <span className={`text-[9px] font-medium ${meta.text}`}>{meta.label}</span>
      </div>
    </button>
  );
};

const ModeDetail = ({ row }) => {
  if (!row) return null;
  const meta = MODE_META[row.mode] ?? MODE_META.MISSING;
  const Icon = meta.icon;
  return (
    <div
      data-testid="model-health-detail"
      className="mt-2 flex items-center gap-3 px-3 py-2 rounded-lg bg-zinc-950/60 border border-white/5"
    >
      <Icon className={`w-4 h-4 ${meta.text}`} />
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

  const rows = data?.models ?? [];
  const counts = data?.counts ?? { HEALTHY: 0, MODE_C: 0, MODE_B: 0, MISSING: 0 };

  const selected = useMemo(() => {
    if (!selectedKey) return null;
    return rows.find(r => `${r.setup_type}|${r.bar_size}` === selectedKey) ?? null;
  }, [rows, selectedKey]);

  return (
    <div
      data-testid="model-health-scorecard"
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
              const key = `${r.setup_type}|${r.bar_size}`;
              return (
                <HealthTile
                  key={key}
                  row={r}
                  active={selectedKey === key}
                  onClick={() => setSelectedKey(selectedKey === key ? null : key)}
                />
              );
            })}
            {rows.length === 0 && !loading && (
              <div className="col-span-full text-xs text-zinc-500 text-center py-4">
                No models reported.
              </div>
            )}
          </div>

          <ModeDetail row={selected} />
        </div>
      )}
    </div>
  );
};

export default ModelHealthScorecard;
