/**
 * TqsCoveragePanel.jsx — v399b
 *
 * Live "TQS Data Coverage" gauge: real-vs-default % per pillar and sub-score,
 * over recently scored alerts. The tell is the v391 descriptor verdict
 * "No data". Lets the operator watch coverage climb after backfills /
 * fundamentals warm-fills instead of running diag scripts by hand.
 *
 * Backed by GET /api/tqs/coverage?days=N.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const tone = (pct) => (pct >= 80 ? 'emerald' : pct >= 50 ? 'amber' : 'rose');
const barCls = { emerald: 'bg-emerald-500/70', amber: 'bg-amber-500/70', rose: 'bg-rose-500/70' };
const txtCls = { emerald: 'text-emerald-300', amber: 'text-amber-300', rose: 'text-rose-300' };

const Gauge = ({ pct, width = 'w-40' }) => {
  const t = tone(pct);
  return (
    <div className={`relative h-3 ${width} rounded bg-zinc-800 overflow-hidden border border-zinc-700`}>
      <div className={`absolute inset-y-0 left-0 ${barCls[t]}`} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
};

const TqsCoveragePanel = () => {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/api/tqs/coverage?days=${days}`);
      const j = await r.json();
      if (!r.ok || j?.success === false) throw new Error(j?.detail || `HTTP ${r.status}`);
      setData(j);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const overall = data?.overall_coverage_pct ?? 0;

  return (
    <div data-testid="tqs-coverage-panel" className="h-full overflow-y-auto bg-zinc-950 text-zinc-200 p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-200 uppercase tracking-wider">TQS Data Coverage</span>
          <span className="text-[13px] text-zinc-500">real vs "No data" default</span>
        </div>
        <div className="flex items-center gap-2">
          {[7, 30, 90].map((d) => (
            <button key={d} type="button" data-testid={`tqs-cov-days-${d}`} onClick={() => setDays(d)}
              className={`px-2 py-0.5 text-[13px] uppercase tracking-wider rounded border ${
                days === d ? 'bg-zinc-800 text-zinc-100 border-zinc-700'
                  : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'}`}>{d}d</button>
          ))}
          <button type="button" data-testid="tqs-cov-refresh" onClick={load}
            className="text-zinc-500 hover:text-zinc-300" title="Refresh">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {error && <div className="text-rose-400 text-sm py-3" data-testid="tqs-cov-error">⚠ {error}</div>}
      {loading && !data && <div className="text-zinc-500 text-sm py-3">Loading…</div>}

      {data && (
        <>
          <div className="border border-zinc-800 rounded p-3 mb-4 bg-zinc-900/40 flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <span className={`text-2xl font-bold v5-mono ${txtCls[tone(overall)]}`} data-testid="tqs-cov-overall">
                {overall}%
              </span>
              <Gauge pct={overall} width="w-56" />
            </div>
            <div className="text-[13px] text-zinc-500">
              {data.real_subscores}/{data.total_subscores} sub-scores real ·{' '}
              <span className="text-zinc-400">{data.with_display}</span> alerts w/ descriptors ·{' '}
              <span className="text-zinc-600">{data.legacy_no_display} legacy</span> ·{' '}
              window {data.window_days}d
            </div>
          </div>

          <div className="space-y-3">
            {(data.pillars || []).map((p) => (
              <div key={p.pillar} data-testid={`tqs-cov-pillar-${p.pillar}`}
                className="border border-zinc-800 rounded overflow-hidden">
                <div className="px-3 py-2 bg-zinc-900/50 flex items-center gap-3">
                  <span className="text-xs uppercase tracking-wider text-zinc-300 w-28">{p.pillar}</span>
                  <Gauge pct={p.coverage_pct} />
                  <span className={`v5-mono text-sm ${txtCls[tone(p.coverage_pct)]}`}>{p.coverage_pct}%</span>
                </div>
                <div className="divide-y divide-zinc-900">
                  {(p.components || []).map((c) => (
                    <div key={c.key} data-testid={`tqs-cov-comp-${p.pillar}-${c.key}`}
                      className="px-3 py-1.5 flex items-center gap-3 text-[13px]">
                      <span className="text-zinc-400 w-40 truncate">{c.label}</span>
                      <Gauge pct={c.real_pct} width="w-28" />
                      <span className={`v5-mono w-12 text-right ${txtCls[tone(c.real_pct)]}`}>{c.real_pct}%</span>
                      <span className="v5-mono text-zinc-600 w-24 text-right">{c.samples} samples</span>
                      {c.no_data_pct > 0 && (
                        <span className="v5-mono text-zinc-500">{c.no_data_pct}% no-data</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="text-[12px] text-zinc-600 mt-3">
            real% = data-backed sub-scores; no-data% = scored from absent data (descriptor verdict "No data").
            🟢 ≥80 · 🟡 ≥50 · 🔴 &lt;50. Computed over alerts carrying v391 descriptor blocks.
          </div>
        </>
      )}
    </div>
  );
};

export default TqsCoveragePanel;
