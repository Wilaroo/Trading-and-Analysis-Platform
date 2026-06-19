/**
 * DataSchedulePanel.jsx — v399b
 *
 * Live punchlist of every scheduled job (DAILY_SCHEDULE.md, productized).
 * Grouped by category (Overnight / Pre-market / Post-close cascade / Weekend).
 * Per row: last run, last *success*, next scheduled fire, output freshness,
 * and an issue flag. A "failing" flag = job fires but never succeeds — the
 * exact signal that would have surfaced the 35-day-dead gate_calibration.
 *
 * Backed by GET /api/diagnostics/data-schedule.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, AlertTriangle, CheckCircle2, Clock, XCircle } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const ISSUE_META = {
  ok:        { label: 'OK',      cls: 'text-emerald-300 border-emerald-800 bg-emerald-950/30', Icon: CheckCircle2 },
  stale:     { label: 'STALE',   cls: 'text-amber-300 border-amber-800 bg-amber-950/30',       Icon: Clock },
  failing:   { label: 'FAILING', cls: 'text-rose-300 border-rose-800 bg-rose-950/40',          Icon: XCircle },
  never_run: { label: 'NEVER',   cls: 'text-zinc-400 border-zinc-700 bg-zinc-900',             Icon: AlertTriangle },
};

const fmtAge = (s) => {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
};

const fmtNext = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-US', {
      timeZone: 'America/New_York', weekday: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }) + ' ET';
  } catch { return '—'; }
};

const Cell = ({ children, cls = '' }) => (
  <td className={`px-2 py-1.5 v5-mono text-[13px] ${cls}`}>{children}</td>
);

const DataSchedulePanel = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/api/diagnostics/data-schedule`);
      const j = await r.json();
      if (!r.ok || j?.success === false) throw new Error(j?.detail || `HTTP ${r.status}`);
      setData(j);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const grouped = useMemo(() => {
    const out = {};
    (data?.rows || []).forEach((row) => {
      (out[row.category] = out[row.category] || []).push(row);
    });
    return out;
  }, [data]);

  const cats = data?.categories || Object.keys(grouped);
  const counts = data?.counts || {};

  return (
    <div data-testid="data-schedule-panel" className="h-full overflow-y-auto bg-zinc-950 text-zinc-200 p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-200 uppercase tracking-wider">Data Schedule</span>
          <span className="text-[13px] text-zinc-500">last run · last success · next fire · freshness</span>
        </div>
        <div className="flex items-center gap-2">
          {Object.entries(counts).map(([k, v]) => {
            const m = ISSUE_META[k] || ISSUE_META.ok;
            return (
              <span key={k} data-testid={`schedule-count-${k}`}
                className={`px-2 py-0.5 text-[13px] uppercase tracking-wider rounded border ${m.cls}`}>
                {m.label} {v}
              </span>
            );
          })}
          <button type="button" data-testid="data-schedule-refresh" onClick={load}
            className="text-zinc-500 hover:text-zinc-300" title="Refresh">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {error && <div className="text-rose-400 text-sm py-3" data-testid="data-schedule-error">⚠ {error}</div>}
      {loading && !data && <div className="text-zinc-500 text-sm py-3">Loading…</div>}

      {data?.catchup && (
        <div data-testid="data-schedule-catchup"
          className="mb-4 border border-zinc-800 rounded p-2 bg-zinc-900/40 text-[13px]">
          <span className="text-zinc-400 uppercase tracking-wider mr-2">Last boot catch-up</span>
          <span className="text-zinc-300">{data.catchup.summary || '—'}</span>
          <span className="text-zinc-600 ml-2">({String(data.catchup.at).slice(0, 19)})</span>
          {(data.catchup.scheduled || []).length > 0 && (
            <span className="text-cyan-300 ml-2">
              re-ran: {data.catchup.scheduled.map((s) => s.job).join(', ')}
            </span>
          )}
        </div>
      )}

      {cats.map((cat) => (
        <div key={cat} className="mb-4" data-testid={`schedule-cat-${cat}`}>
          <div className="text-[13px] uppercase tracking-wider text-zinc-500 mb-1">{cat}</div>
          <div className="border border-zinc-800 rounded overflow-hidden">
            <table className="w-full">
              <thead className="bg-zinc-900 text-zinc-500 uppercase tracking-wider text-[12px]">
                <tr>
                  <th className="px-2 py-1.5 text-left">Job</th>
                  <th className="px-2 py-1.5 text-left">Status</th>
                  <th className="px-2 py-1.5 text-right">Last run</th>
                  <th className="px-2 py-1.5 text-right">Last success</th>
                  <th className="px-2 py-1.5 text-right">Output age</th>
                  <th className="px-2 py-1.5 text-right">Next fire</th>
                  <th className="px-2 py-1.5 text-left">Summary</th>
                </tr>
              </thead>
              <tbody>
                {(grouped[cat] || []).map((row) => {
                  const m = ISSUE_META[row.issue || 'ok'] || ISSUE_META.ok;
                  const Icon = m.Icon;
                  return (
                    <tr key={row.key} data-testid={`schedule-row-${row.key}`}
                      className={`border-t border-zinc-900 ${row.issue && row.issue !== 'ok' ? 'bg-rose-950/10' : ''}`}>
                      <Cell cls="text-zinc-200">{row.label}</Cell>
                      <td className="px-2 py-1.5">
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[12px] uppercase tracking-wider rounded border ${m.cls}`}>
                          <Icon size={11} /> {m.label}
                        </span>
                      </td>
                      <Cell cls="text-right text-zinc-400">{fmtAge(row.last_run_age_s)}</Cell>
                      <Cell cls={`text-right ${row.issue === 'failing' ? 'text-rose-400 font-bold' : 'text-zinc-400'}`}>
                        {fmtAge(row.last_success_age_s)}
                      </Cell>
                      <Cell cls="text-right text-zinc-500">{fmtAge(row.output_fresh_age_s)}</Cell>
                      <Cell cls="text-right text-zinc-500">{fmtNext(row.next_run)}</Cell>
                      <Cell cls="text-zinc-500 max-w-[280px] truncate" >
                        <span title={row.summary}>{row.summary || '—'}</span>
                      </Cell>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <div className="text-[12px] text-zinc-600 mt-2">
        <span className="text-rose-400">FAILING</span> = job fires but its last success is far older than its last run
        (the gate-calibration failure mode). <span className="text-amber-400">STALE</span> = output older than cadence.
        Output age = independent freshness of the job's data product.
      </div>
    </div>
  );
};

export default DataSchedulePanel;
