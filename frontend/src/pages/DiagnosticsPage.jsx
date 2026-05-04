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
  { id: 'day_tape', label: 'Day Tape' },
  { id: 'forensics', label: 'Trade Forensics' },
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

// ─────────────────────────────────────────────────────────────────
// Sub-tab: Day Tape (v19.31.9)
// 5/30-day toggle + sortable table + CSV export. Powered by
// /api/diagnostics/day-tape and /day-tape.csv.
// ─────────────────────────────────────────────────────────────────

const DAY_TAPE_RANGES = [
  { id: 1,  label: 'Today' },
  { id: 5,  label: '5d' },
  { id: 30, label: '30d' },
];

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch { return '—'; }
};

const DayTapeView = () => {
  const [days, setDays] = useState(1);
  const [direction, setDirection] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sortKey, setSortKey] = useState('closed_at');
  const [sortDir, setSortDir] = useState('desc');

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ days });
      if (direction) params.append('direction', direction);
      const r = await fetch(`${BACKEND_URL}/api/diagnostics/day-tape?${params}`);
      const j = await r.json();
      if (!j.success) throw new Error('day-tape failed');
      setData(j);
    } catch (e) {
      setError(e?.message || 'failed to load day tape');
    } finally {
      setLoading(false);
    }
  }, [days, direction]);

  useEffect(() => { load(); }, [load]);

  const sorted = useMemo(() => {
    const rows = data?.rows || [];
    return [...rows].sort((a, b) => {
      const av = a?.[sortKey];
      const bv = b?.[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const isNum = typeof av === 'number' || typeof bv === 'number';
      const cmp = isNum ? Number(av) - Number(bv) : String(av).localeCompare(String(bv));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  const sortBy = (k) => {
    if (sortKey === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(k); setSortDir('desc'); }
  };

  const handleCsv = () => {
    const params = new URLSearchParams({ days });
    if (direction) params.append('direction', direction);
    window.open(`${BACKEND_URL}/api/diagnostics/day-tape.csv?${params}`, '_blank');
  };

  const summary = data?.summary || {};

  return (
    <div data-testid="day-tape-view" className="h-full flex flex-col bg-zinc-950 text-zinc-200">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-300">Day Tape</span>
          <div className="flex items-center gap-1 ml-2">
            {DAY_TAPE_RANGES.map(r => (
              <button
                key={r.id}
                type="button"
                data-testid={`day-tape-range-${r.id}`}
                onClick={() => setDays(r.id)}
                className={`px-2.5 py-1 text-[11px] uppercase tracking-wider rounded border ${
                  days === r.id
                    ? 'bg-zinc-100 text-zinc-950 border-zinc-100'
                    : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:text-zinc-200'
                }`}
              >{r.label}</button>
            ))}
          </div>
          <div className="flex items-center gap-1 ml-2">
            {[null, 'long', 'short'].map(d => (
              <button
                key={String(d)}
                type="button"
                data-testid={`day-tape-direction-${d || 'all'}`}
                onClick={() => setDirection(d)}
                className={`px-2 py-1 text-[10px] uppercase tracking-wider rounded border ${
                  direction === d
                    ? 'bg-zinc-100 text-zinc-950 border-zinc-100'
                    : 'bg-zinc-900 text-zinc-500 border-zinc-800 hover:text-zinc-200'
                }`}
              >{d || 'all'}</button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="day-tape-refresh"
            onClick={load}
            className="px-2 py-1 text-[11px] text-zinc-400 hover:text-zinc-200 border border-zinc-800 rounded inline-flex items-center gap-1"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          <button
            type="button"
            data-testid="day-tape-csv"
            onClick={handleCsv}
            className="px-2 py-1 text-[11px] text-emerald-300 hover:text-emerald-200 border border-emerald-900/60 rounded"
          >
            Download CSV
          </button>
        </div>
      </div>

      {/* Summary chips */}
      <div className="px-4 py-2 border-b border-zinc-800 flex items-baseline gap-4 flex-wrap text-[11px] v5-mono">
        <span data-testid="day-tape-summary-count" className="text-zinc-500">
          <span className="text-zinc-200 font-semibold">{summary.count ?? 0}</span> trades
        </span>
        <span data-testid="day-tape-summary-wr" className="text-zinc-500">
          WR <span className="text-zinc-200 font-semibold">{summary.win_rate != null ? `${summary.win_rate}%` : '—'}</span>
          {' · '}<span className="text-emerald-400">{summary.wins ?? 0}W</span>
          {' / '}<span className="text-rose-400">{summary.losses ?? 0}L</span>
          {summary.scratches > 0 && <> {' / '}<span className="text-zinc-400">{summary.scratches} scratch</span></>}
        </span>
        <span data-testid="day-tape-summary-pnl" className={(summary.gross_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
          Gross {formatPnl(summary.gross_pnl ?? 0)}
        </span>
        <span data-testid="day-tape-summary-avg-r" className="text-zinc-500">
          avg R <span className={(summary.avg_r ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
            {summary.avg_r != null ? Number(summary.avg_r).toFixed(2) : '—'}
          </span>
        </span>
        {summary.biggest_winner && (
          <span data-testid="day-tape-summary-biggest-win" className="text-emerald-400">
            Best: {summary.biggest_winner.symbol} {formatPnl(summary.biggest_winner.realized_pnl)}
          </span>
        )}
        {summary.biggest_loser && (
          <span data-testid="day-tape-summary-biggest-loss" className="text-rose-400">
            Worst: {summary.biggest_loser.symbol} {formatPnl(summary.biggest_loser.realized_pnl)}
          </span>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {error && <div className="px-4 py-3 text-rose-400">{error}</div>}
        {!error && sorted.length === 0 && !loading && (
          <div data-testid="day-tape-empty" className="px-4 py-12 text-center text-zinc-500 text-sm">
            No closed trades in this window.
          </div>
        )}
        {sorted.length > 0 && (
          <table className="w-full text-[11px] v5-mono">
            <thead className="sticky top-0 bg-zinc-950 border-b border-zinc-800">
              <tr>
                {[
                  ['closed_at',    'Closed',   'right'],
                  ['symbol',       'Sym',      'left'],
                  ['direction',    'Dir',      'left'],
                  ['shares',       'Sh',       'right'],
                  ['entry_price',  'Entry',    'right'],
                  ['exit_price',   'Exit',     'right'],
                  ['realized_pnl', '$',        'right'],
                  ['r_multiple',   'R',        'right'],
                  ['close_reason', 'Reason',   'left'],
                  ['setup_type',   'Setup',    'left'],
                ].map(([k, l, a]) => (
                  <th
                    key={k}
                    onClick={() => sortBy(k)}
                    data-testid={`day-tape-col-${k}`}
                    className={`px-2 py-2 cursor-pointer select-none uppercase text-[10px] tracking-wider text-zinc-500 hover:text-zinc-300 text-${a}`}
                  >
                    {l}{sortKey === k ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const dollars = Number(r.realized_pnl) || 0;
                const rMul = Number(r.r_multiple) || 0;
                const isShort = (r.direction || '').toLowerCase() === 'short';
                return (
                  <tr key={r.trade_id || `${r.symbol}-${r.closed_at}`}
                      data-testid={`day-tape-row-${r.symbol}`}
                      className="border-b border-zinc-900 hover:bg-white/5">
                    <td className="px-2 py-1 text-right text-zinc-500">{fmtTime(r.closed_at || r.executed_at)}</td>
                    <td className="px-2 py-1 font-bold text-zinc-100">{r.symbol}</td>
                    <td className={`px-2 py-1 ${isShort ? 'text-rose-400' : 'text-emerald-400'}`}>{isShort ? 'S' : 'L'}</td>
                    <td className="px-2 py-1 text-right text-zinc-300">{r.shares ?? '—'}</td>
                    <td className="px-2 py-1 text-right text-zinc-400">{r.entry_price != null ? Number(r.entry_price).toFixed(2) : '—'}</td>
                    <td className="px-2 py-1 text-right text-zinc-400">{r.exit_price != null ? Number(r.exit_price).toFixed(2) : '—'}</td>
                    <td className={`px-2 py-1 text-right font-semibold ${dollars >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{formatPnl(dollars)}</td>
                    <td className={`px-2 py-1 text-right font-semibold ${rMul >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.r_multiple != null ? `${rMul >= 0 ? '+' : ''}${rMul.toFixed(2)}R` : '—'}
                    </td>
                    <td className="px-2 py-1 text-zinc-500 truncate" title={r.close_reason || ''}>{r.close_reason || '—'}</td>
                    <td className="px-2 py-1 text-zinc-500 truncate" title={r.setup_type || ''}>{r.setup_type || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Setup breakdown footer */}
      {summary.by_setup && Object.keys(summary.by_setup).length > 0 && (
        <div data-testid="day-tape-by-setup" className="px-4 py-2 border-t border-zinc-800 text-[10px] flex flex-wrap gap-3">
          <span className="text-zinc-500 uppercase tracking-wider">By setup:</span>
          {Object.entries(summary.by_setup)
            .sort(([, a], [, b]) => (b.gross_pnl ?? 0) - (a.gross_pnl ?? 0))
            .slice(0, 8)
            .map(([s, b]) => (
              <span key={s} className="text-zinc-400">
                {s} <span className="text-zinc-500">{b.count}</span>{' '}
                <span className={(b.gross_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {formatPnl(b.gross_pnl)}
                </span>
                {b.win_rate != null && (
                  <span className="text-zinc-600"> ({b.win_rate}%)</span>
                )}
              </span>
            ))}
        </div>
      )}
    </div>
  );
};



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

// ─────────────────────────────────────────────────────────────────
// Sub-tab: Trade Forensics (v19.31.11)
// Per-symbol verdict join across bot_trades + IB snapshot +
// sweep events + reconcile events. Powers the operator's
// "what was real vs phantom today" forensic question.
// ─────────────────────────────────────────────────────────────────

const FORENSICS_RANGES = [
  { id: 1, label: 'Today' },
  { id: 3, label: '3d' },
  { id: 7, label: '7d' },
];

const VERDICT_META = {
  clean:              { color: 'text-emerald-400', bg: 'bg-emerald-950/40',  border: 'border-emerald-900/60', icon: '✓', label: 'Clean' },
  phantom_v27:        { color: 'text-amber-300',   bg: 'bg-amber-950/40',    border: 'border-amber-900/60',   icon: '◇', label: 'Phantom v27' },
  phantom_v31:        { color: 'text-amber-300',   bg: 'bg-amber-950/40',    border: 'border-amber-900/60',   icon: '◇', label: 'Phantom v31' },
  reset_orphaned:     { color: 'text-orange-300',  bg: 'bg-orange-950/40',   border: 'border-orange-900/60',  icon: '!', label: 'Reset orphaned' },
  auto_reconciled:    { color: 'text-sky-300',     bg: 'bg-sky-950/40',      border: 'border-sky-900/60',     icon: '↻', label: 'Auto-reconciled' },
  manual_or_external: { color: 'text-slate-300',   bg: 'bg-slate-900/60',    border: 'border-slate-700',      icon: '?', label: 'Manual / external' },
  unexplained_drift:  { color: 'text-rose-300',    bg: 'bg-rose-950/40',     border: 'border-rose-900/60',    icon: '✕', label: 'Unexplained drift' },
};

const VERDICT_PRIORITY = {
  unexplained_drift: 0,
  reset_orphaned:    1,
  manual_or_external: 2,
  phantom_v31:       3,
  phantom_v27:       4,
  auto_reconciled:   5,
  clean:             6,
};

const fmtForensicsTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
  } catch { return '—'; }
};

const TradeForensicsView = () => {
  const [days, setDays] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [verdictFilter, setVerdictFilter] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/api/diagnostics/trade-forensics?days=${days}`);
      const j = await r.json();
      if (!j.success) throw new Error('forensics failed');
      setData(j);
    } catch (e) {
      setError(e?.message || 'failed to load forensics');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const symbols = data?.symbols || [];
  const summary = data?.summary || {};
  const byVerdict = summary.by_verdict || {};

  const sorted = useMemo(() => {
    const filtered = verdictFilter
      ? symbols.filter(s => s.verdict === verdictFilter)
      : symbols;
    return [...filtered].sort((a, b) => {
      const ap = VERDICT_PRIORITY[a.verdict] ?? 99;
      const bp = VERDICT_PRIORITY[b.verdict] ?? 99;
      if (ap !== bp) return ap - bp;
      return String(a.symbol).localeCompare(String(b.symbol));
    });
  }, [symbols, verdictFilter]);

  return (
    <div data-testid="trade-forensics-view" className="h-full flex flex-col bg-zinc-950 text-zinc-200">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-300">Trade Forensics</span>
          <span className="text-[11px] text-zinc-500 ml-1">real vs phantom · ledger drift</span>
          <div className="flex items-center gap-1 ml-3">
            {FORENSICS_RANGES.map(r => (
              <button
                key={r.id}
                type="button"
                data-testid={`forensics-range-${r.id}`}
                onClick={() => setDays(r.id)}
                className={`px-2.5 py-1 text-[11px] uppercase tracking-wider rounded border ${
                  days === r.id
                    ? 'bg-zinc-100 text-zinc-950 border-zinc-100'
                    : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:text-zinc-200'
                }`}
              >{r.label}</button>
            ))}
          </div>
        </div>
        <button
          type="button"
          data-testid="forensics-refresh"
          onClick={load}
          className="px-2 py-1 text-[11px] text-zinc-400 hover:text-zinc-200 border border-zinc-800 rounded inline-flex items-center gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Verdict filter chips — show counts */}
      <div className="px-4 py-2 border-b border-zinc-800 flex items-center gap-1 flex-wrap text-[11px]">
        <button
          type="button"
          data-testid="forensics-filter-all"
          onClick={() => setVerdictFilter(null)}
          className={`px-2 py-0.5 rounded border ${
            verdictFilter === null
              ? 'bg-zinc-100 text-zinc-950 border-zinc-100'
              : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:text-zinc-200'
          }`}
        >
          All <span className="opacity-70">{symbols.length}</span>
        </button>
        {Object.entries(byVerdict).map(([v, count]) => {
          const m = VERDICT_META[v] || { color: 'text-zinc-300', bg: 'bg-zinc-900', border: 'border-zinc-800', label: v };
          const active = verdictFilter === v;
          return (
            <button
              key={v}
              type="button"
              data-testid={`forensics-filter-${v}`}
              onClick={() => setVerdictFilter(active ? null : v)}
              className={`px-2 py-0.5 rounded border ${
                active
                  ? `${m.bg} ${m.color} ${m.border} font-semibold`
                  : `bg-zinc-900 ${m.color} border-zinc-800 hover:border-zinc-600`
              }`}
            >
              {m.icon} {m.label} <span className="opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {error && <div className="px-4 py-3 text-rose-400 text-sm">{error}</div>}
        {!error && sorted.length === 0 && !loading && (
          <div data-testid="forensics-empty" className="px-4 py-12 text-center text-zinc-500 text-sm">
            {verdictFilter
              ? 'No symbols match this verdict.'
              : 'No trade activity in this window.'}
          </div>
        )}
        {sorted.length > 0 && (
          <div className="divide-y divide-zinc-900">
            {sorted.map((row) => {
              const m = VERDICT_META[row.verdict] || VERDICT_META.clean;
              const isExpanded = expanded === row.symbol;
              const driftClass = Math.abs(row.drift_usd || 0) > 5 ? 'text-rose-400' : 'text-zinc-500';
              return (
                <div
                  key={row.symbol}
                  data-testid={`forensics-row-${row.symbol}`}
                  className={`${m.bg} hover:bg-white/5 transition-colors`}
                >
                  <div
                    className="px-4 py-2 flex items-center gap-4 cursor-pointer"
                    onClick={() => setExpanded(isExpanded ? null : row.symbol)}
                  >
                    {/* Verdict badge */}
                    <span
                      data-testid={`forensics-row-${row.symbol}-verdict`}
                      className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${m.color} ${m.border} ${m.bg} font-bold`}
                    >
                      {m.icon} {m.label}
                    </span>
                    {/* Symbol */}
                    <span className="v5-mono font-bold text-sm text-zinc-100 w-16 shrink-0">{row.symbol}</span>
                    {/* Bot ledger */}
                    <span className="text-[11px] v5-mono text-zinc-500 w-44 shrink-0">
                      Bot: <span className="text-zinc-300">{row.bot.trade_count}t</span>
                      {' '}({row.bot.open_count}o · {row.bot.closed_count}c){' '}
                      <span className={(row.bot.total_realized_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        {(row.bot.total_realized_pnl ?? 0) >= 0 ? '+' : ''}${Math.abs(row.bot.total_realized_pnl ?? 0).toFixed(2)}
                      </span>
                    </span>
                    {/* IB ledger */}
                    <span className="text-[11px] v5-mono text-zinc-500 w-44 shrink-0">
                      IB: <span className="text-zinc-300">{row.ib.current_position}sh</span>
                      {' · realized '}
                      <span className={(row.ib.realized_pnl_today ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        {(row.ib.realized_pnl_today ?? 0) >= 0 ? '+' : ''}${Math.abs(row.ib.realized_pnl_today ?? 0).toFixed(2)}
                      </span>
                    </span>
                    {/* Drift */}
                    <span className={`text-[11px] v5-mono ${driftClass} w-24 shrink-0`}>
                      Δ {(row.drift_usd ?? 0) >= 0 ? '+' : ''}${Math.abs(row.drift_usd ?? 0).toFixed(2)}
                    </span>
                    {/* Explanation */}
                    <span className="text-[11px] text-zinc-400 flex-1 truncate" title={row.explanation}>
                      {row.explanation}
                    </span>
                    <span className="text-[10px] text-zinc-600 shrink-0">
                      {isExpanded ? '▼' : '▶'} timeline
                    </span>
                  </div>

                  {isExpanded && (
                    <div
                      data-testid={`forensics-timeline-${row.symbol}`}
                      className="bg-zinc-950/50 px-4 py-2 border-t border-zinc-900"
                    >
                      {row.timeline?.length ? (
                        <table className="w-full text-[11px] v5-mono">
                          <thead>
                            <tr className="text-zinc-600 uppercase text-[10px] tracking-wider">
                              <th className="text-left pb-1 w-20">Time</th>
                              <th className="text-left pb-1 w-48">Event</th>
                              <th className="text-left pb-1">Detail</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row.timeline.map((e, i) => {
                              const isPhantom = String(e.kind || '').toLowerCase().includes('phantom');
                              const isReconcile = String(e.kind || '').toLowerCase().includes('reconcile');
                              const kindClass = isPhantom
                                ? 'text-amber-300'
                                : isReconcile
                                ? 'text-sky-300'
                                : 'text-zinc-400';
                              return (
                                <tr key={i} className="border-t border-zinc-900">
                                  <td className="py-1 text-zinc-500">{fmtForensicsTime(e.time)}</td>
                                  <td className={`py-1 ${kindClass}`}>{e.kind}</td>
                                  <td className="py-1 text-zinc-400 truncate" title={e.detail}>{e.detail}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      ) : (
                        <div className="text-zinc-600 text-[11px]">No timeline events.</div>
                      )}
                      {row.reset_touched && (
                        <div className="mt-1.5 text-[10px] text-orange-400">
                          ⚠ This row was touched by the morning reset script.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="px-4 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600">
        Sorted by verdict severity (drift / orphaned / phantom / clean). Click any row to expand timeline. v19.31.11
      </div>
    </div>
  );
};


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
        {tab === 'day_tape' && <DayTapeView />}
        {tab === 'forensics' && <TradeForensicsView />}
        {tab === 'export' && <ExportReport />}
      </main>
    </div>
  );
}
