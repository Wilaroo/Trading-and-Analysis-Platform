import React, { useState, useEffect, useCallback, memo } from 'react';
import { ShieldCheck, ShieldAlert, RefreshCw, TrendingUp, Clock, AlertTriangle, Trophy } from 'lucide-react';
import api from '../../utils/api';

/**
 * Compact dashboard card that surfaces model validation quality at a glance.
 *
 * Data source: GET /api/ai-modules/validation/summary
 *
 * What it shows:
 *   - Promote/Reject counts across 24h, 7d, 30d, all-time windows
 *   - Promotion rate trend (big visual number for the most recent window)
 *   - Top 5 promoted models ranked by win_rate * sharpe
 *   - Top rejection reason buckets (helps spot systemic issues)
 */
const BUCKET_LABELS = {
  insufficient_trades: 'Insufficient trades (n<30)',
  low_win_rate: 'Win rate below 50%',
  low_sharpe: 'Sharpe below threshold',
  monte_carlo_broken: 'Monte Carlo failed',
  weak_walk_forward: 'Weak out-of-sample',
  no_ai_edge: 'No AI edge over setup',
  regression: 'Regression vs baseline',
  validator_bug: 'Legacy validator bug',
  other: 'Other',
};

const ValidationSummaryCard = memo(() => {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [activeWindow, setActiveWindow] = useState('last_7d');

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.get('/api/ai-modules/validation/summary');
      if (res.data?.success) {
        setSummary(res.data);
      } else {
        setErr('Failed to load summary');
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || 'Network error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
    const id = setInterval(fetchSummary, 60_000); // refresh every minute
    return () => clearInterval(id);
  }, [fetchSummary]);

  if (loading && !summary) {
    return (
      <div
        className="rounded-xl border border-white/5 bg-white/[0.02] p-4"
        data-testid="validation-summary-loading"
      >
        <div className="flex items-center gap-2 text-zinc-400 text-sm">
          <RefreshCw className="w-4 h-4 animate-spin" /> Loading validation summary…
        </div>
      </div>
    );
  }

  if (err) {
    return (
      <div
        className="rounded-xl border border-red-500/20 bg-red-500/5 p-4"
        data-testid="validation-summary-error"
      >
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4" /> {err}
        </div>
      </div>
    );
  }

  const windows = summary?.windows || {};
  const current = windows[activeWindow] || { total: 0, promoted: 0, rejected: 0, promotion_rate_pct: 0 };
  const topPromoted = summary?.top_promoted || [];
  const rejections = summary?.rejection_summary || [];

  // Promotion rate color: >=20% green, 5-20% amber, <5% red (rejecting too aggressively OR too few runs)
  const rateColor =
    current.promotion_rate_pct >= 20 ? 'text-emerald-400' :
    current.promotion_rate_pct >= 5  ? 'text-amber-400'   :
    'text-red-400';

  const totalRejections = rejections.reduce((a, b) => a + b.count, 0);

  return (
    <div
      className="rounded-xl border border-white/5 bg-white/[0.02] p-4 space-y-4"
      data-testid="validation-summary-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-medium text-white">Validation Quality Dashboard</h3>
        </div>
        <button
          onClick={fetchSummary}
          className="text-zinc-500 hover:text-white transition-colors"
          aria-label="Refresh validation summary"
          data-testid="validation-summary-refresh"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Window tabs */}
      <div className="flex items-center gap-1" data-testid="validation-summary-windows">
        {[
          ['last_24h', '24h'],
          ['last_7d', '7d'],
          ['last_30d', '30d'],
          ['all_time', 'All'],
        ].map(([key, label]) => {
          const w = windows[key] || {};
          const isActive = activeWindow === key;
          return (
            <button
              key={key}
              onClick={() => setActiveWindow(key)}
              className={`flex-1 px-2 py-1.5 rounded-md text-[10px] uppercase tracking-wide border transition-colors ${
                isActive
                  ? 'bg-white/10 border-white/20 text-white'
                  : 'bg-transparent border-white/5 text-zinc-500 hover:text-zinc-300 hover:border-white/10'
              }`}
              data-testid={`window-tab-${key}`}
            >
              {label}
              {w.total > 0 && (
                <span className="ml-1 text-zinc-500">({w.total})</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Headline row */}
      <div className="grid grid-cols-3 gap-2" data-testid="validation-summary-metrics">
        <div className="p-3 rounded-lg bg-white/[0.03] border border-white/5 text-center">
          <div className="text-2xl font-bold text-white" data-testid="metric-total">{current.total}</div>
          <div className="text-[10px] text-zinc-500 uppercase mt-0.5">Evaluated</div>
        </div>
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-center">
          <div className="text-2xl font-bold text-emerald-400" data-testid="metric-promoted">{current.promoted}</div>
          <div className="text-[10px] text-emerald-500 uppercase mt-0.5">Promoted</div>
        </div>
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-center">
          <div className="text-2xl font-bold text-red-400" data-testid="metric-rejected">{current.rejected}</div>
          <div className="text-[10px] text-red-500 uppercase mt-0.5">Rejected</div>
        </div>
      </div>

      {/* Promotion rate */}
      {current.total > 0 && (
        <div
          className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/[0.02] border border-white/5"
          data-testid="promotion-rate-row"
        >
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>Promotion rate</span>
          </div>
          <div className={`text-lg font-bold ${rateColor}`} data-testid="promotion-rate-value">
            {current.promotion_rate_pct.toFixed(1)}%
          </div>
        </div>
      )}

      {/* Top promoted */}
      {topPromoted.length > 0 && (
        <div data-testid="top-promoted-section">
          <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wide text-zinc-500">
            <Trophy className="w-3 h-3 text-amber-400" /> Top Performers
          </div>
          <div className="space-y-1">
            {topPromoted.map((m, idx) => (
              <div
                key={`${m.setup_type}-${m.bar_size}-${idx}`}
                className="flex items-center justify-between px-2 py-1.5 rounded-md bg-white/[0.02] hover:bg-white/[0.05] transition-colors text-xs"
                data-testid={`top-promoted-${idx}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-zinc-500 font-mono w-4">{idx + 1}.</span>
                  <span className="text-zinc-200 font-mono truncate">{m.setup_type}</span>
                  <span className="text-zinc-500 text-[10px]">{m.bar_size}</span>
                </div>
                <div className="flex items-center gap-3 text-[11px] flex-shrink-0">
                  <span className="text-emerald-400">WR {m.win_rate}%</span>
                  <span className="text-blue-400">Sh {m.sharpe}</span>
                  <span className="text-zinc-500">n={m.trades}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Rejection buckets */}
      {rejections.length > 0 && (
        <div data-testid="rejection-reasons-section">
          <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wide text-zinc-500">
            <ShieldAlert className="w-3 h-3 text-red-400" /> Why Models Got Rejected
          </div>
          <div className="space-y-1">
            {rejections.map((r, idx) => {
              const pct = totalRejections > 0 ? (r.count / totalRejections) * 100 : 0;
              return (
                <div
                  key={r.bucket}
                  className="px-2 py-1.5 rounded-md bg-white/[0.02] text-xs"
                  data-testid={`rejection-bucket-${r.bucket}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-zinc-300">{BUCKET_LABELS[r.bucket] || r.bucket}</span>
                    <span className="text-zinc-500 font-mono text-[10px]">
                      {r.count} <span className="text-zinc-600">({pct.toFixed(0)}%)</span>
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-white/5 overflow-hidden">
                    <div
                      className="h-full bg-red-400/60"
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Empty state */}
      {current.total === 0 && topPromoted.length === 0 && rejections.length === 0 && (
        <div
          className="text-center py-6 text-zinc-500 text-xs"
          data-testid="validation-summary-empty"
        >
          <Clock className="w-6 h-6 mx-auto mb-2 text-zinc-700" />
          No validation activity in this window yet. Run the training pipeline — Phase 13 will auto-validate.
        </div>
      )}

      {/* Footer */}
      {summary?.generated_at && (
        <div
          className="text-[10px] text-zinc-600 text-right pt-1 border-t border-white/5"
          data-testid="validation-summary-timestamp"
        >
          Updated {new Date(summary.generated_at).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
});

ValidationSummaryCard.displayName = 'ValidationSummaryCard';

export default ValidationSummaryCard;
