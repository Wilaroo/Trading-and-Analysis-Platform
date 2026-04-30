/**
 * DiagnosticsPage.jsx — v19.28 (2026-05-01)
 *
 * Operator's new "Diagnostics" tab. Three sub-tabs:
 *   1. Trail Explorer  — recent decisions list ↔ per-decision drilldown
 *   2. Module Scorecard — per-AI-module accuracy / P&L / weight / kill flag
 *   3. Export Report   — one-click markdown dump for tuning suggestions
 *
 * Style is intentionally close to V5: dark zinc, mono numbers, tight
 * spacing, single-pixel borders. Lots of data, little chrome.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Microscope, TrendingUp, TrendingDown, Copy, RefreshCw, Filter } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const SUB_TABS = [
  { id: 'trail', label: 'Trail Explorer' },
  { id: 'scorecard', label: 'Module Scorecard' },
  { id: 'funnel', label: 'Pipeline Funnel' },
  { id: 'export', label: 'Export Report' },
];

const formatPnl = (n) => {
  const v = Number(n) || 0;
  const sign = v >= 0 ? '+' : '';
  return `${sign}$${v.toFixed(2)}`;
};

const fmtPct = (n) => {
  if (n == null || isNaN(n)) return '—';
  return `${Number(n).toFixed(1)}%`;
};

const outcomeBadge = (outcome) => {
  const o = (outcome || '').toLowerCase();
  if (o === 'win')             return { label: 'WIN',     cls: 'bg-emerald-900/40 text-emerald-300 border-emerald-800' };
  if (o === 'loss')            return { label: 'LOSS',    cls: 'bg-rose-900/40 text-rose-300 border-rose-800' };
  if (o === 'scratch')         return { label: 'SCRATCH', cls: 'bg-zinc-800 text-zinc-300 border-zinc-700' };
  if (o === 'open')            return { label: 'OPEN',    cls: 'bg-cyan-900/40 text-cyan-300 border-cyan-800' };
  if (o === 'shadow_win')      return { label: 'S-WIN',   cls: 'bg-emerald-950/40 text-emerald-400 border-emerald-900' };
  if (o === 'shadow_loss')     return { label: 'S-LOSS',  cls: 'bg-rose-950/40 text-rose-400 border-rose-900' };
  if (o === 'shadow_pending')  return { label: 'S-WAIT',  cls: 'bg-zinc-900 text-zinc-500 border-zinc-800' };
  return { label: o.toUpperCase() || '?', cls: 'bg-zinc-900 text-zinc-500 border-zinc-800' };
};

// ─────────────────────────────────────────────────────────────────
// Sub-tab 1: Trail Explorer
// ─────────────────────────────────────────────────────────────────

const TrailRow = ({ row, active, onClick }) => {
  const o = outcomeBadge(row.outcome);
  return (
    <button
      type="button"
      data-testid={`trail-row-${row.identifier}`}
      onClick={onClick}
      className={`w-full text-left px-3 py-2 border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors ${
        active ? 'bg-zinc-900' : ''
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-sm text-zinc-200">{row.symbol || '?'}</span>
          <span className={`px-1 py-0 text-[9px] uppercase tracking-wider border rounded ${o.cls}`}>
            {o.label}
          </span>
          {row.has_trade ? (
            <span className="text-[9px] text-zinc-500 uppercase">trade</span>
          ) : (
            <span className="text-[9px] text-zinc-600 uppercase">shadow</span>
          )}
        </div>
        <span className={`font-mono text-xs ${
          (row.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
        }`}>
          {formatPnl(row.pnl)}
        </span>
      </div>
      <div className="flex items-baseline justify-between mt-1">
        <span className="text-[11px] text-zinc-500 truncate max-w-[60%]">
          {row.setup || '—'}
        </span>
        <span className="text-[10px] text-zinc-600">
          {(row.scanned_at || '').replace('T', ' ').slice(0, 19)}
        </span>
      </div>
    </button>
  );
};

const TrailDetailPane = ({ identifier }) => {
  const [trail, setTrail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!identifier) {
      setTrail(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${BACKEND_URL}/api/diagnostics/decision-trail/${encodeURIComponent(identifier)}`)
      .then(r => r.json())
      .then(data => {
        if (cancelled) return;
        if (data?.success) {
          setTrail(data.trail);
        } else {
          setError(data?.detail || 'Trail load failed');
          setTrail(null);
        }
      })
      .catch(err => {
        if (!cancelled) setError(String(err?.message || err));
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [identifier]);

  if (!identifier) {
    return (
      <div data-testid="trail-detail-empty" className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
        ← Pick a decision to see its full trail
      </div>
    );
  }

  if (loading) {
    return <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">Loading…</div>;
  }
  if (error) {
    return <div className="flex-1 p-4 text-rose-400 text-sm">⚠ {error}</div>;
  }
  if (!trail) return null;

  const outcome = outcomeBadge(trail.meta?.outcome);

  return (
    <div data-testid="trail-detail" className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-baseline justify-between border-b border-zinc-800 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-lg text-zinc-100">{trail.alert?.symbol || '?'}</span>
            <span className={`px-2 py-0.5 text-[10px] uppercase tracking-wider border rounded ${outcome.cls}`}>
              {outcome.label}
            </span>
            <span className="text-[10px] text-zinc-500 font-mono">
              {trail.identifier_type}: {trail.identifier}
            </span>
          </div>
          <div className="text-xs text-zinc-500 mt-1">
            {trail.alert?.setup_type || '—'}
            {trail.alert?.smb_grade ? ` · SMB ${trail.alert.smb_grade}` : ''}
            {trail.alert?.quality_score ? ` · Q${trail.alert.quality_score}` : ''}
          </div>
        </div>
        {trail.meta?.time_to_decision_s != null && (
          <div className="text-[11px] text-zinc-500">
            decided in {trail.meta.time_to_decision_s.toFixed(1)}s
          </div>
        )}
      </div>

      {/* Section 1 — Scanner alert */}
      <section data-testid="trail-section-alert">
        <h4 className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">1. Scanner Alert</h4>
        {trail.alert ? (
          <div className="bg-zinc-900/50 border border-zinc-800 rounded p-2 text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-zinc-400">Setup</span>
              <span className="font-mono text-zinc-200">{trail.alert.setup_type || '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Quality / Tier</span>
              <span className="font-mono text-zinc-200">
                {trail.alert.quality_score ?? '—'} {trail.alert.scan_tier ? `· ${trail.alert.scan_tier}` : ''}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Scanned</span>
              <span className="font-mono text-zinc-200">{(trail.alert.scanned_at || '').slice(0, 19)}</span>
            </div>
            {trail.alert.exit_rule && (
              <div className="text-[11px] text-zinc-500 pt-1 border-t border-zinc-800">
                <span className="text-zinc-400">Exit rule:</span> {trail.alert.exit_rule}
              </div>
            )}
            {Array.isArray(trail.alert.reasoning) && trail.alert.reasoning.length > 0 && (
              <ul className="text-[11px] text-zinc-400 pt-1 space-y-0.5 list-disc pl-4">
                {trail.alert.reasoning.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
          </div>
        ) : (
          <div className="text-xs text-zinc-600 italic">No scanner alert recorded.</div>
        )}
      </section>

      {/* Section 2 — AI module votes */}
      <section data-testid="trail-section-modules">
        <h4 className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">2. AI Module Votes</h4>
        {Array.isArray(trail.module_votes) && trail.module_votes.length > 0 ? (
          <div className="space-y-1">
            {trail.module_votes.map((v, i) => (
              <div key={`${v.module}-${i}`} className="bg-zinc-900/50 border border-zinc-800 rounded p-2 text-xs">
                <div className="flex justify-between items-baseline mb-0.5">
                  <span className="font-mono text-zinc-200 uppercase text-[11px]">{v.module}</span>
                  <span className="font-mono text-zinc-300">
                    {v.recommendation || '—'}
                    {v.confidence != null && (
                      <span className="text-zinc-500 ml-2">{Number(v.confidence).toFixed(0)}%</span>
                    )}
                  </span>
                </div>
                {v.reasoning && (
                  <div className="text-[11px] text-zinc-500 mt-1">{v.reasoning}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-zinc-600 italic">No AI module votes recorded.</div>
        )}
      </section>

      {/* Section 3 — Bot action */}
      <section data-testid="trail-section-action">
        <h4 className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">3. Bot Decision</h4>
        {trail.trade ? (
          <div className="bg-zinc-900/50 border border-zinc-800 rounded p-2 text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-zinc-400">Action</span>
              <span className="font-mono text-emerald-300">
                FIRED · {(trail.trade.direction || '').toUpperCase()} {trail.trade.shares}sh
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Entry / Stop / Target</span>
              <span className="font-mono text-zinc-200">
                ${Number(trail.trade.entry_price || 0).toFixed(2)} /
                ${Number(trail.trade.stop_price || 0).toFixed(2)} /
                ${Number((trail.trade.target_prices || [])[0] || 0).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Status</span>
              <span className="font-mono text-zinc-200">{trail.trade.status}</span>
            </div>
            {trail.trade.realized_pnl != null && (
              <div className="flex justify-between">
                <span className="text-zinc-400">Realized P&L</span>
                <span className={`font-mono ${
                  (trail.trade.realized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}>
                  {formatPnl(trail.trade.realized_pnl)}
                </span>
              </div>
            )}
            {trail.trade.close_reason && (
              <div className="flex justify-between text-[11px] text-zinc-500">
                <span>Closed by</span>
                <span className="font-mono">{trail.trade.close_reason}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="bg-zinc-900/50 border border-zinc-800 rounded p-2 text-xs">
            <div className="flex justify-between">
              <span className="text-zinc-400">Action</span>
              <span className="font-mono text-amber-300">PASSED (shadow only)</span>
            </div>
            {trail.shadow?.combined_recommendation && (
              <div className="flex justify-between mt-0.5">
                <span className="text-zinc-400">Combined recommendation</span>
                <span className="font-mono text-zinc-200">{trail.shadow.combined_recommendation}</span>
              </div>
            )}
            {trail.shadow?.confidence_score != null && (
              <div className="flex justify-between mt-0.5">
                <span className="text-zinc-400">Confidence</span>
                <span className="font-mono text-zinc-200">{Number(trail.shadow.confidence_score).toFixed(0)}%</span>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Section 4 — Bot thoughts in window */}
      {Array.isArray(trail.thoughts) && trail.thoughts.length > 0 && (
        <section data-testid="trail-section-thoughts">
          <h4 className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">
            4. Bot Thoughts ({trail.thoughts.length})
          </h4>
          <div className="bg-zinc-900/30 border border-zinc-800 rounded p-2 max-h-72 overflow-y-auto space-y-1">
            {trail.thoughts.map((t, i) => (
              <div key={i} className="text-[11px] flex gap-2 border-b border-zinc-900 pb-1">
                <span className="text-zinc-600 font-mono">{(t.timestamp || '').slice(11, 19)}</span>
                <span className="text-zinc-400 truncate">{t.text || t.reasoning || '—'}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

const TrailExplorer = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [filterSymbol, setFilterSymbol] = useState('');
  const [onlyDisagreements, setOnlyDisagreements] = useState(false);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('limit', '50');
      if (filterSymbol) params.set('symbol', filterSymbol.toUpperCase());
      if (onlyDisagreements) params.set('only_disagreements', 'true');
      const res = await fetch(`${BACKEND_URL}/api/diagnostics/recent-decisions?${params.toString()}`);
      const data = await res.json();
      if (!res.ok || data?.success === false) {
        setError(data?.detail || `Load failed (${res.status})`);
        setRows([]);
      } else {
        setRows(data.rows || []);
        if (!selected && (data.rows || []).length > 0) {
          setSelected(data.rows[0].identifier);
        }
      }
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSymbol, onlyDisagreements]);

  useEffect(() => { refetch(); }, [refetch]);

  return (
    <div className="flex h-full" data-testid="diagnostics-trail-explorer">
      {/* Left: list */}
      <div className="w-[360px] border-r border-zinc-800 flex flex-col">
        <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2">
          <Filter size={12} className="text-zinc-500" />
          <input
            value={filterSymbol}
            onChange={e => setFilterSymbol(e.target.value)}
            placeholder="Symbol"
            data-testid="trail-filter-symbol"
            className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-zinc-600"
          />
          <button
            type="button"
            onClick={() => setOnlyDisagreements(v => !v)}
            data-testid="trail-toggle-disagreements"
            className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${
              onlyDisagreements
                ? 'bg-amber-900/40 text-amber-300 border-amber-800/60'
                : 'border-zinc-700 text-zinc-500 hover:text-zinc-300'
            }`}
            title="Show only decisions where AI modules disagreed"
          >
            disagreements
          </button>
          <button
            type="button"
            onClick={refetch}
            data-testid="trail-refetch"
            className="text-zinc-500 hover:text-zinc-300"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading && rows.length === 0 && (
            <div className="px-3 py-4 text-xs text-zinc-500">Loading…</div>
          )}
          {error && <div className="px-3 py-4 text-xs text-rose-400">⚠ {error}</div>}
          {!loading && !error && rows.length === 0 && (
            <div className="px-3 py-4 text-xs text-zinc-500">No decisions match.</div>
          )}
          {rows.map(r => (
            <TrailRow
              key={r.identifier}
              row={r}
              active={selected === r.identifier}
              onClick={() => setSelected(r.identifier)}
            />
          ))}
        </div>
      </div>
      {/* Right: drilldown */}
      <TrailDetailPane identifier={selected} />
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Sub-tab 2: Module Scorecard
// ─────────────────────────────────────────────────────────────────

const ModuleScorecard = () => {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/diagnostics/module-scorecard?days=${days}`);
      const j = await res.json();
      if (!res.ok || j?.success === false) {
        setError(j?.detail || `Load failed (${res.status})`);
      } else {
        setData(j);
      }
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { refetch(); }, [refetch]);

  return (
    <div className="p-4" data-testid="diagnostics-module-scorecard">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm text-zinc-200 uppercase tracking-wider">Module Scorecard</h3>
        <div className="flex items-center gap-2">
          {[1, 7, 30].map(d => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              data-testid={`scorecard-days-${d}`}
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${
                days === d
                  ? 'bg-zinc-800 text-zinc-100 border-zinc-700'
                  : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {d}d
            </button>
          ))}
          <button type="button" onClick={refetch} className="text-zinc-500 hover:text-zinc-300" title="Refresh">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      {loading && <div className="text-xs text-zinc-500">Loading…</div>}
      {error && <div className="text-xs text-rose-400">⚠ {error}</div>}
      {data && (
        <div className="border border-zinc-800 rounded overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-zinc-900 text-zinc-500 uppercase tracking-wider text-[10px]">
              <tr>
                <th className="px-3 py-2 text-left">Module</th>
                <th className="px-3 py-2 text-right">Decisions</th>
                <th className="px-3 py-2 text-right">Accuracy</th>
                <th className="px-3 py-2 text-right">P&L (followed)</th>
                <th className="px-3 py-2 text-right">P&L (ignored)</th>
                <th className="px-3 py-2 text-right">Weight</th>
                <th className="px-3 py-2 text-center">Kill?</th>
              </tr>
            </thead>
            <tbody>
              {(data.modules || []).map((m) => (
                <tr
                  key={m.module}
                  data-testid={`scorecard-row-${m.module}`}
                  className={`border-t border-zinc-900 ${
                    m.kill_candidate ? 'bg-rose-950/20' : ''
                  }`}
                >
                  <td className="px-3 py-2 font-mono text-zinc-200">{m.module}</td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-300">{m.total_decisions.toLocaleString()}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    <span className={
                      m.accuracy_rate >= 60 ? 'text-emerald-400'
                      : m.accuracy_rate >= 50 ? 'text-zinc-300'
                      : 'text-rose-400'
                    }>{fmtPct(m.accuracy_rate)}</span>
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${
                    m.avg_pnl_when_followed >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>{formatPnl(m.avg_pnl_when_followed)}</td>
                  <td className={`px-3 py-2 text-right font-mono ${
                    m.avg_pnl_when_ignored >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>{formatPnl(m.avg_pnl_when_ignored)}</td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-300">{m.current_weight}</td>
                  <td className="px-3 py-2 text-center">
                    {m.kill_candidate ? (
                      <span className="text-rose-400" title="Kill candidate: accuracy < 50% AND followed P&L < ignored P&L">🔴</span>
                    ) : (
                      <span className="text-zinc-700">·</span>
                    )}
                  </td>
                </tr>
              ))}
              {(data.modules || []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-zinc-500 text-xs">
                    No module performance data in the selected window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 text-[10px] text-zinc-600">
        🔴 = Kill candidate — accuracy &lt; 50% AND followed-P&L worse than ignored-P&L. Consider retiring or downweighting.
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Sub-tab 3: Pipeline Funnel
// ─────────────────────────────────────────────────────────────────

const PipelineFunnel = () => {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/diagnostics/funnel?days=${days}`);
      const j = await res.json();
      if (!res.ok || j?.success === false) {
        setError(j?.detail || `Load failed (${res.status})`);
      } else {
        setData(j);
      }
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, [days]);
  useEffect(() => { refetch(); }, [refetch]);

  const maxCount = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, ...((data.stages || []).map(s => Number(s.count) || 0)));
  }, [data]);

  return (
    <div className="p-4" data-testid="diagnostics-funnel">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm text-zinc-200 uppercase tracking-wider">Pipeline Funnel</h3>
        <div className="flex items-center gap-2">
          {[1, 7, 30].map(d => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${
                days === d
                  ? 'bg-zinc-800 text-zinc-100 border-zinc-700'
                  : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {d}d
            </button>
          ))}
          <button type="button" onClick={refetch} className="text-zinc-500 hover:text-zinc-300">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      {loading && <div className="text-xs text-zinc-500">Loading…</div>}
      {error && <div className="text-xs text-rose-400">⚠ {error}</div>}
      {data && (
        <div className="space-y-2">
          {(data.stages || []).map((s, i) => {
            const pct = (Number(s.count) || 0) / maxCount * 100;
            const conv = s.conversion_pct;
            const lowConv = conv != null && conv < 30 && i > 0;
            return (
              <div key={s.stage} data-testid={`funnel-stage-${s.stage}`} className="flex items-center gap-3">
                <div className="w-32 text-xs text-zinc-400 text-right">{s.label}</div>
                <div className="flex-1 relative h-7 bg-zinc-900 border border-zinc-800 rounded overflow-hidden">
                  <div
                    className={`absolute inset-y-0 left-0 ${
                      lowConv ? 'bg-rose-900/40' : 'bg-cyan-900/40'
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                  <div className="absolute inset-0 flex items-center px-2 font-mono text-xs text-zinc-200">
                    {Number(s.count).toLocaleString()}
                  </div>
                </div>
                <div className={`w-20 text-right font-mono text-xs ${
                  lowConv ? 'text-rose-400' : 'text-zinc-500'
                }`}>
                  {conv != null ? `${conv}%` : '—'}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-3 text-[10px] text-zinc-600">
        Conversion % shown vs the previous stage. <span className="text-rose-400">Red</span> = abnormal drop (&lt;30%). Drill into specific decisions via Trail Explorer.
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Sub-tab 4: Export Report
// ─────────────────────────────────────────────────────────────────

const ExportReport = () => {
  const [days, setDays] = useState(1);
  const [report, setReport] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCopied(false);
    try {
      const res = await fetch(`${BACKEND_URL}/api/diagnostics/export-report?days=${days}`);
      if (!res.ok) {
        setError(`Export failed (${res.status})`);
      } else {
        setReport(await res.text());
      }
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { refetch(); }, [refetch]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      setError(String(err?.message || err));
    }
  };

  return (
    <div className="p-4 flex flex-col h-full" data-testid="diagnostics-export-report">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm text-zinc-200 uppercase tracking-wider">Export Report</h3>
        <div className="flex items-center gap-2">
          {[1, 7, 30].map(d => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${
                days === d
                  ? 'bg-zinc-800 text-zinc-100 border-zinc-700'
                  : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {d}d
            </button>
          ))}
          <button
            type="button"
            onClick={handleCopy}
            data-testid="export-copy-btn"
            disabled={!report}
            className="px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border border-cyan-800 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
          >
            <Copy size={10} /> {copied ? 'Copied!' : 'Copy markdown'}
          </button>
        </div>
      </div>
      <div className="text-[11px] text-zinc-500 mb-2">
        Paste this into the chat with Emergent for tuning suggestions.
      </div>
      {loading && <div className="text-xs text-zinc-500">Building report…</div>}
      {error && <div className="text-xs text-rose-400">⚠ {error}</div>}
      <pre
        data-testid="export-report-text"
        className="flex-1 overflow-auto bg-zinc-950 border border-zinc-800 rounded p-3 font-mono text-[11px] text-zinc-300 whitespace-pre-wrap"
      >
        {report || (loading ? '' : '(empty)')}
      </pre>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Top-level page
// ─────────────────────────────────────────────────────────────────

export default function DiagnosticsPage() {
  const [tab, setTab] = useState('trail');

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-zinc-200" data-testid="diagnostics-page">
      <header className="flex items-center justify-between px-4 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Microscope size={16} className="text-cyan-400" />
          <span className="text-sm uppercase tracking-wider">Diagnostics</span>
          <span className="text-[10px] text-zinc-600 uppercase">v19.28</span>
        </div>
        <nav className="flex items-center gap-1">
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              data-testid={`diag-subtab-${t.id}`}
              className={`px-3 py-1 text-[11px] uppercase tracking-wider rounded transition-colors ${
                tab === t.id
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="flex-1 overflow-hidden">
        {tab === 'trail' && <TrailExplorer />}
        {tab === 'scorecard' && <ModuleScorecard />}
        {tab === 'funnel' && <PipelineFunnel />}
        {tab === 'export' && <ExportReport />}
      </main>
    </div>
  );
}
