/**
 * ScannerCoverageAuditPanel — V5 surface for the v19.34.138 backend
 * coverage audit endpoint.
 *
 * Calls `GET /api/diagnostic/symbol-coverage?include_mega_cap=true` on
 * mount and on manual refresh. Renders a compact chip with the
 * worst-case verdict (red/amber/green) and a hover/click-to-expand
 * drawer showing per-symbol state for the full MEGA_CAP_WATCHLIST.
 *
 * Bulk-rescue is one click: when any symbols are flagged
 * `UNQUALIFIABLE_FLAGGED`, a button POSTs `/clear-unqualifiable`
 * with their list and re-fetches.
 *
 * Operator's recurring question — "why isn't TSLA / NVDA / SNDK
 * popping?" — gets answered at a glance: each name shows its verdict
 * badge (OK / UNQUALIFIABLE_FLAGGED / MISSING_FROM_CACHE /
 * BELOW_TIER2_THRESHOLD / STALE_BARS) plus the always-on `MEGA_CAP`
 * pin pill so they can see we're scanning it regardless of cache state.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, RefreshCw, Search, X, Zap,
} from 'lucide-react';
import api from '../../../utils/api';

const VERDICT_META = {
  OK: {
    label: 'OK', color: 'text-emerald-300', dot: 'bg-emerald-400',
    ring: 'ring-emerald-500/30', tone: 'ok',
  },
  STALE_BARS: {
    label: 'STALE BARS', color: 'text-amber-300', dot: 'bg-amber-400',
    ring: 'ring-amber-500/30', tone: 'warn',
  },
  BELOW_TIER2_THRESHOLD: {
    label: 'BELOW TIER 2', color: 'text-sky-300', dot: 'bg-sky-400',
    ring: 'ring-sky-500/30', tone: 'info',
  },
  UNQUALIFIABLE_FLAGGED: {
    label: 'UNQUALIFIABLE', color: 'text-rose-300', dot: 'bg-rose-500',
    ring: 'ring-rose-500/40', tone: 'fail',
  },
  MISSING_FROM_CACHE: {
    label: 'MISSING', color: 'text-rose-300', dot: 'bg-rose-500',
    ring: 'ring-rose-500/40', tone: 'fail',
  },
};

const TONE_PRIORITY = { fail: 3, warn: 2, info: 1, ok: 0 };

const fmtUsdB = (v) => {
  if (!v || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toFixed(0)}`;
};

const fmtStale = (sec) => {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86400)}d`;
};

export const ScannerCoverageAuditPanel = () => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rescuing, setRescuing] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const fetchCoverage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: payload } = await api.get(
        '/api/diagnostic/symbol-coverage?include_mega_cap=true',
      );
      if (!payload?.success) {
        setError(payload?.error || 'backend returned no success flag');
      } else {
        setData(payload);
      }
    } catch (e) {
      setError(e?.message || 'fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchCoverage(); }, [fetchCoverage]);

  const rescueUnqualifiable = useCallback(async () => {
    const flagged = data?.summary?.unqualifiable_flagged || [];
    if (flagged.length === 0) return;
    setRescuing(true);
    try {
      await api.post('/api/diagnostic/clear-unqualifiable', {
        symbols: flagged,
        reason: 'v19.34.138 audit panel rescue',
      });
      await fetchCoverage();
    } catch (e) {
      setError(`rescue failed: ${e?.message || e}`);
    } finally {
      setRescuing(false);
    }
  }, [data, fetchCoverage]);

  // Roll up the worst tone for the chip color.
  const worstTone = useMemo(() => {
    const coverage = data?.coverage || [];
    let worst = 'ok';
    for (const c of coverage) {
      const meta = VERDICT_META[c.verdict] || VERDICT_META.OK;
      if (TONE_PRIORITY[meta.tone] > TONE_PRIORITY[worst]) worst = meta.tone;
    }
    return worst;
  }, [data]);

  const summary = data?.summary || {};
  const chipColor = ({
    fail: 'border-rose-500/40 text-rose-200 bg-rose-500/10',
    warn: 'border-amber-500/40 text-amber-200 bg-amber-500/10',
    info: 'border-sky-500/40 text-sky-200 bg-sky-500/10',
    ok: 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10',
  })[worstTone];

  return (
    <>
      <button
        data-testid="scanner-coverage-audit-chip"
        onClick={() => setOpen(true)}
        title="Open Scanner Coverage Audit"
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[12px] font-semibold uppercase tracking-wide transition-colors ${chipColor} hover:brightness-125`}
      >
        <Search className="w-3 h-3" />
        <span>Coverage</span>
        {worstTone !== 'ok' && (
          <span className="text-[11px] opacity-80">
            {(summary.unqualifiable_flagged?.length || 0)
              + (summary.missing_from_canonical?.length || 0)
              + (summary.stale_bars_over_5min?.length || 0)}
          </span>
        )}
      </button>

      {open && (
        <div
          data-testid="scanner-coverage-audit-drawer"
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-5xl max-h-[88vh] overflow-hidden rounded-2xl bg-gradient-to-br from-zinc-950 to-black border border-white/10 shadow-2xl"
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/10">
              <div className="flex items-center gap-3">
                <Search className="w-4 h-4 text-violet-400" />
                <h2 className="text-sm font-bold text-white tracking-tight">
                  Scanner Coverage Audit
                </h2>
                <span className="text-[12px] text-zinc-500 v5-mono">
                  v19.34.138 · {data?.audited_symbols?.length ?? 0} symbols audited
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  data-testid="scanner-coverage-refresh"
                  onClick={fetchCoverage}
                  disabled={loading}
                  className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-white/5 transition-colors"
                  title="Refresh"
                >
                  <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
                <button
                  data-testid="scanner-coverage-close"
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-white/5 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </header>

            <div className="px-4 py-3 overflow-y-auto max-h-[calc(88vh-58px)]">
              {error && (
                <div
                  data-testid="scanner-coverage-error"
                  className="px-3 py-2 mb-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-200 text-[13px]"
                >
                  {error}
                </div>
              )}

              {/* Summary tiles */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
                <SummaryTile
                  label="Healthy"
                  count={(data?.coverage || []).filter(c => c.verdict === 'OK').length}
                  total={data?.summary?.total_audited || 0}
                  tone="ok"
                />
                <SummaryTile
                  label="Unqualifiable"
                  count={summary.unqualifiable_flagged?.length || 0}
                  tone="fail"
                  testid="summary-unqualifiable"
                />
                <SummaryTile
                  label="Missing"
                  count={summary.missing_from_canonical?.length || 0}
                  tone="fail"
                  testid="summary-missing"
                />
                <SummaryTile
                  label="Stale bars"
                  count={summary.stale_bars_over_5min?.length || 0}
                  tone="warn"
                  testid="summary-stale"
                />
              </div>

              {/* Rescue action */}
              {(summary.unqualifiable_flagged?.length || 0) > 0 && (
                <div className="mb-3 flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-rose-500/10 border border-rose-500/30">
                  <div className="flex items-center gap-2 text-[13px] text-rose-200">
                    <AlertTriangle className="w-4 h-4" />
                    <span>
                      {summary.unqualifiable_flagged.length} name(s) are
                      flagged unqualifiable —{' '}
                      <span className="font-mono">
                        {summary.unqualifiable_flagged.slice(0, 5).join(', ')}
                        {summary.unqualifiable_flagged.length > 5 ? '…' : ''}
                      </span>
                    </span>
                  </div>
                  <button
                    data-testid="scanner-coverage-rescue-btn"
                    onClick={rescueUnqualifiable}
                    disabled={rescuing}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-rose-500/20 text-rose-100 hover:bg-rose-500/30 text-[12px] font-semibold ring-1 ring-rose-500/40 transition-colors disabled:opacity-60"
                  >
                    <Zap className={`w-3 h-3 ${rescuing ? 'animate-pulse' : ''}`} />
                    {rescuing ? 'Clearing…' : 'Clear all'}
                  </button>
                </div>
              )}

              {/* Action recommendations */}
              {(data?.actions || []).length > 0 && (
                <ul className="mb-3 space-y-1 text-[12px] text-zinc-400 leading-relaxed">
                  {(data.actions || []).map((a, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <span className="text-zinc-600 mt-0.5">›</span>
                      <span>{a}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* Per-symbol table */}
              <div className="overflow-x-auto rounded-lg border border-white/5">
                <table className="w-full text-[12px]">
                  <thead className="bg-white/5 text-zinc-400 uppercase tracking-wider">
                    <tr>
                      <th className="px-2 py-1.5 text-left">Symbol</th>
                      <th className="px-2 py-1.5 text-left">Verdict</th>
                      <th className="px-2 py-1.5 text-right">ADV</th>
                      <th className="px-2 py-1.5 text-right">Tier-2 rank</th>
                      <th className="px-2 py-1.5 text-right">Bars age</th>
                      <th className="px-2 py-1.5 text-left">Mega-cap</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {(data?.coverage || []).map((c) => {
                      const meta = VERDICT_META[c.verdict] || VERDICT_META.OK;
                      return (
                        <tr
                          key={c.symbol}
                          data-testid={`coverage-row-${c.symbol}`}
                          className="hover:bg-white/[0.02] transition-colors"
                        >
                          <td className="px-2 py-1 v5-mono text-zinc-100">{c.symbol}</td>
                          <td className="px-2 py-1">
                            <span className={`inline-flex items-center gap-1 ${meta.color}`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                              {meta.label}
                            </span>
                          </td>
                          <td className="px-2 py-1 text-right v5-mono text-zinc-300">
                            {fmtUsdB(c.avg_dollar_volume)}
                          </td>
                          <td className="px-2 py-1 text-right v5-mono text-zinc-400">
                            {c.in_tier2_top_n ? `#${c.in_tier2_top_n}` : '—'}
                          </td>
                          <td className="px-2 py-1 text-right v5-mono text-zinc-400">
                            {fmtStale(c.staleness_sec)}
                          </td>
                          <td className="px-2 py-1">
                            {c.in_mega_cap ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 font-semibold tracking-wider">
                                PIN
                              </span>
                            ) : (
                              <span className="text-zinc-700">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {(data?.coverage || []).length === 0 && !loading && (
                      <tr>
                        <td colSpan={6} className="px-2 py-4 text-center text-zinc-500">
                          No data — backend may be offline or DB not seeded.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <footer className="mt-3 text-[11px] text-zinc-600 v5-mono">
                Generated {data?.generated_at || '—'}
              </footer>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const SummaryTile = ({ label, count, total, tone = 'ok', testid }) => {
  const palette = {
    ok: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
    warn: 'bg-amber-500/10 border-amber-500/30 text-amber-300',
    fail: 'bg-rose-500/10 border-rose-500/30 text-rose-300',
    info: 'bg-sky-500/10 border-sky-500/30 text-sky-300',
  }[tone];
  return (
    <div
      data-testid={testid}
      className={`flex items-center justify-between px-3 py-2 rounded-lg border ${palette}`}
    >
      <span className="text-[12px] uppercase tracking-wider opacity-80">{label}</span>
      <span className="text-lg font-bold v5-mono">
        {count}
        {total != null && (
          <span className="text-[11px] opacity-60"> / {total}</span>
        )}
      </span>
    </div>
  );
};

export default ScannerCoverageAuditPanel;
