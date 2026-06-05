/**
 * EVLeaderboard — v19.34.274
 *
 * Expected-Value scoreboard for Mission Control. Surfaces, per canonical
 * setup, the realized edge that actually pays: EV(R), win-rate, EV gate
 * (A/B/C/D/F), rolling letter grade, profit-factor, sample size, and a
 * compact EV-trend sparkline. Sorted by expected value descending so the
 * operator sees at a glance which setups to lean into and which to cut.
 *
 * Fed by `GET /api/scanner/ev-leaderboard?days=30` which merges
 * `ev_tracking_service.get_ev_report()` + `setup_grading_service
 * .get_all_rolling_grades()`. Read-only; polls on an interval while open.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { TrendingUp, RefreshCw, Trophy } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const GATE_STYLE = {
  A_TRADE: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  B_TRADE: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/30',
  C_TRADE: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
  D_TRADE: 'text-orange-300 bg-orange-500/10 border-orange-500/30',
  F_TRADE: 'text-rose-300 bg-rose-500/10 border-rose-500/30',
};

const GRADE_STYLE = (g) => {
  const u = String(g || '').toUpperCase();
  if (u.startsWith('A')) return 'text-emerald-300';
  if (u.startsWith('B')) return 'text-cyan-300';
  if (u === 'C') return 'text-amber-300';
  if (u === 'F') return 'text-rose-300';
  return 'text-zinc-400';
};

const prettySetup = (s) =>
  String(s || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

const fmtR = (v) =>
  v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v).toFixed(2)}R`;
const fmtPct = (v) =>
  v == null || Number.isNaN(Number(v)) ? '—' : `${(Number(v) * 100).toFixed(0)}%`;

const Sparkline = ({ data }) => {
  if (!Array.isArray(data) || data.length < 2) return <span className="text-zinc-700">—</span>;
  const w = 56;
  const h = 16;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / span) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={pts}
        fill="none"
        stroke={up ? '#34d399' : '#fb7185'}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
};

const EVLeaderboard = ({ days = 30 }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    fetch(`${BACKEND_URL}/api/scanner/ev-leaderboard?days=${days}`)
      .then((r) => r.json())
      .then((d) => {
        if (!d?.success) throw new Error('Bad payload');
        setRows(d.leaderboard || []);
        setError(null);
        setUpdatedAt(Date.now());
      })
      .catch((e) => setError(e?.message || 'Failed to load EV leaderboard'))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const ageS = useMemo(
    () => (updatedAt ? Math.round((Date.now() - updatedAt) / 1000) : null),
    [updatedAt],
  );

  return (
    <div data-testid="ev-leaderboard" className="flex flex-col h-full bg-zinc-950 text-zinc-200">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2">
        <Trophy size={14} className="text-amber-400" />
        <span className="text-[12px] font-bold uppercase tracking-wider text-zinc-100">
          EV Leaderboard
        </span>
        <span className="text-[10px] text-zinc-600">· {days}d</span>
        <button
          type="button"
          data-testid="ev-leaderboard-refresh"
          onClick={load}
          className="ml-auto p-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto v5-scroll">
        {error && (
          <div data-testid="ev-leaderboard-error" className="px-3 py-3 text-[11px] text-rose-400/80">
            {error}
          </div>
        )}
        {!error && rows.length === 0 && !loading && (
          <div data-testid="ev-leaderboard-empty" className="px-3 py-4 text-[11px] text-zinc-600">
            No EV data yet — needs closed trades per setup to populate.
          </div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-zinc-900/90 backdrop-blur text-zinc-500 uppercase tracking-wider">
              <tr>
                <th className="text-left font-medium px-2 py-1.5">Setup</th>
                <th className="text-right font-medium px-2 py-1.5">EV</th>
                <th className="text-right font-medium px-2 py-1.5">Win</th>
                <th className="text-center font-medium px-2 py-1.5">Gate</th>
                <th className="text-center font-medium px-2 py-1.5">Grade</th>
                <th className="text-right font-medium px-2 py-1.5 hidden sm:table-cell">PF</th>
                <th className="text-right font-medium px-2 py-1.5">n</th>
                <th className="text-center font-medium px-2 py-1.5 hidden md:table-cell">Trend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const ev = r.expected_value_r;
                const evPos = ev != null && Number(ev) >= 0;
                const sample = (r.ev_trades || 0) || (r.grade_trades || 0);
                return (
                  <tr
                    key={r.setup_type || i}
                    data-testid={`ev-row-${r.setup_type}`}
                    title={r.recommendation || ''}
                    className="border-t border-zinc-900 hover:bg-zinc-900/40"
                  >
                    <td className="px-2 py-1.5 v5-mono text-zinc-200 truncate max-w-[140px]">
                      <span className="text-zinc-600 mr-1">{i + 1}</span>
                      {prettySetup(r.setup_type)}
                      {r.ev_improving && (
                        <TrendingUp size={10} className="inline ml-1 text-emerald-400" />
                      )}
                    </td>
                    <td className={`px-2 py-1.5 text-right v5-mono font-bold ${
                      ev == null ? 'text-zinc-600' : evPos ? 'text-emerald-300' : 'text-rose-300'
                    }`}>
                      {fmtR(ev)}
                    </td>
                    <td className="px-2 py-1.5 text-right v5-mono text-zinc-300">
                      {fmtPct(r.win_rate)}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {r.ev_gate ? (
                        <span className={`v5-mono text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                          GATE_STYLE[r.ev_gate] || 'text-zinc-400 bg-zinc-800/40 border-zinc-700'
                        }`}>
                          {String(r.ev_gate).replace('_TRADE', '')}
                        </span>
                      ) : (
                        <span className="text-zinc-700">—</span>
                      )}
                    </td>
                    <td className={`px-2 py-1.5 text-center v5-mono font-bold ${GRADE_STYLE(r.grade)}`}>
                      {r.grade || '—'}
                    </td>
                    <td className="px-2 py-1.5 text-right v5-mono text-zinc-400 hidden sm:table-cell">
                      {r.profit_factor != null ? Number(r.profit_factor).toFixed(2) : '—'}
                    </td>
                    <td className={`px-2 py-1.5 text-right v5-mono ${
                      r.min_sample_reached ? 'text-zinc-300' : 'text-zinc-600'
                    }`}>
                      {sample}
                    </td>
                    <td className="px-2 py-1.5 text-center hidden md:table-cell">
                      <Sparkline data={r.ev_trend} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {ageS != null && (
        <div className="px-3 py-1 border-t border-zinc-800 text-[10px] text-zinc-600">
          Updated {ageS}s ago · sorted by EV
        </div>
      )}
    </div>
  );
};

export default EVLeaderboard;
