/**
 * ScannerQualityPanel -- v19.34.41 (Feb 2026)
 *
 * Compact V5 panel showing today's Scanner Quality Score plus the
 * top rejection reasons. Sits next to PortfolioHealthPill in the V5
 * status-strip row.
 *
 * Data source: GET /api/system/rejection-analytics
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Gauge } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const BUCKET_COLOR = {
  excellent: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  good:      'bg-sky-500/15 text-sky-300 border-sky-500/30',
  fair:      'bg-amber-500/15 text-amber-300 border-amber-500/30',
  poor:      'bg-rose-500/15 text-rose-300 border-rose-500/30',
};

const CATEGORY_COLOR = {
  scanner_quality: 'text-amber-300',
  broker:          'text-rose-300',
  policy:          'text-sky-300',
  other:           'text-zinc-400',
};

const CATEGORY_LABEL = {
  scanner_quality: 'Scanner',
  broker:          'Broker',
  policy:          'Policy',
  other:           'Other',
};

const formatPct = (n) => {
  if (typeof n !== 'number' || Number.isNaN(n)) return '--';
  return `${Math.round(n)}%`;
};

export const ScannerQualityPanel = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/system/rejection-analytics`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message || 'fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [refresh]);

  const bucket = data?.score_bucket || 'excellent';
  const scorePct = data?.scanner_quality_score_pct ?? 100;
  const totals = data?.totals || { accepted: 0, rejected: 0, scanner_signals: 0 };
  const byReason = data?.by_reason || [];
  const byCategory = data?.by_category || {};

  const topReasons = useMemo(() => byReason.slice(0, 3), [byReason]);

  const pillClass = BUCKET_COLOR[bucket] || BUCKET_COLOR.excellent;

  const tooltip = useMemo(() => {
    const lines = [
      `Trading date: ${data?.trading_date_et || '--'}`,
      `Accepted: ${totals.accepted}  Rejected: ${totals.rejected}  Signals: ${totals.scanner_signals}`,
      '--',
      `Scanner-quality rejections: ${byCategory.scanner_quality ?? 0}`,
      `Broker rejections:          ${byCategory.broker ?? 0}`,
      `Policy rejections:          ${byCategory.policy ?? 0}`,
      ...(byReason.length > 0 ? ['--', ...byReason.slice(0, 8).map(r => `${r.label}: ${r.count}`)] : []),
    ];
    return lines.join('\n');
  }, [data, totals, byCategory, byReason]);

  if (error) {
    return (
      <div
        data-testid="scanner-quality-panel-error"
        className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap border border-rose-500/30 text-rose-300"
        title={`Scanner-quality fetch failed: ${error}`}
      >
        <Gauge className="w-3 h-3" />
        <span>SCANNER ?</span>
      </div>
    );
  }

  if (!data && loading) {
    return (
      <div
        data-testid="scanner-quality-panel-loading"
        className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap border border-zinc-700/50 text-zinc-500"
      >
        <Gauge className="w-3 h-3 animate-pulse" />
        <span>SCANNER ...</span>
      </div>
    );
  }

  return (
    <div
      data-testid="scanner-quality-panel"
      className="relative bg-zinc-950/60 text-[14px] leading-none"
      title={tooltip}
    >
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        data-testid="scanner-quality-panel-toggle"
        className={`flex items-center gap-2 px-3 py-1 border whitespace-nowrap ${pillClass} hover:brightness-110 transition`}
      >
        <Gauge className="w-3 h-3" />
        <span
          data-testid="scanner-quality-panel-label"
          className="font-semibold uppercase tracking-wide"
        >
          SCANNER {formatPct(scorePct)}
        </span>
        <span className="text-zinc-400 v5-mono">
          {totals.accepted}/{totals.scanner_signals}
        </span>
        {topReasons.length > 0 && (
          <span className="text-zinc-500 truncate max-w-[180px]" data-testid="scanner-quality-panel-toplabel">
            top: {topReasons[0].label} ({topReasons[0].count})
          </span>
        )}
      </button>

      {expanded && (
        <div
          data-testid="scanner-quality-panel-drawer"
          className="absolute z-50 left-0 top-full mt-1 w-[420px] bg-zinc-950 border border-zinc-700 shadow-2xl p-3 text-[13px]"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-zinc-500 uppercase tracking-wider text-[12px]">
              Today's rejection breakdown -- {data?.trading_date_et}
            </span>
            <button
              type="button"
              data-testid="scanner-quality-panel-refresh"
              onClick={(e) => { e.stopPropagation(); refresh(); }}
              className="text-zinc-500 hover:text-zinc-200 text-[12px]"
              title="Refresh now"
            >
              refresh
            </button>
          </div>

          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[11px] text-zinc-500">Accepted</div>
              <div className="v5-mono text-emerald-300">{totals.accepted}</div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[11px] text-zinc-500">Rejected</div>
              <div className="v5-mono text-rose-300">{totals.rejected}</div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[11px] text-zinc-500">Signals</div>
              <div className="v5-mono text-zinc-200">{totals.scanner_signals}</div>
            </div>
          </div>

          <div className="flex gap-2 mb-3 flex-wrap">
            {Object.entries(byCategory).map(([cat, count]) => (
              <div
                key={cat}
                data-testid={`scanner-quality-panel-cat-${cat}`}
                className={`px-2 py-0.5 bg-zinc-900 border border-zinc-800 ${CATEGORY_COLOR[cat] || 'text-zinc-400'}`}
              >
                {CATEGORY_LABEL[cat] || cat}: <span className="v5-mono">{count}</span>
              </div>
            ))}
          </div>

          {byReason.length === 0 ? (
            <div className="text-zinc-500 italic">No rejections today.</div>
          ) : (
            <div data-testid="scanner-quality-panel-reasons" className="space-y-1">
              <div className="text-zinc-500 uppercase tracking-wider text-[11px] mb-1">
                Top reasons
              </div>
              {byReason.slice(0, 8).map(r => (
                <div
                  key={r.reason_key}
                  data-testid={`scanner-quality-panel-reason-${r.reason_key}`}
                  className="flex items-center justify-between gap-2 px-2 py-1 bg-zinc-900/60 border border-zinc-800"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`w-2 h-2 rounded-full ${
                      r.category === 'scanner_quality' ? 'bg-amber-400' :
                      r.category === 'broker' ? 'bg-rose-400' :
                      r.category === 'policy' ? 'bg-sky-400' : 'bg-zinc-500'
                    }`} />
                    <span className="truncate text-zinc-200">{r.label}</span>
                    <span className={`text-[10px] uppercase tracking-wider ${CATEGORY_COLOR[r.category]}`}>
                      {CATEGORY_LABEL[r.category] || r.category}
                    </span>
                  </div>
                  <span className="v5-mono text-zinc-300 ml-2">{r.count}</span>
                </div>
              ))}
            </div>
          )}

          <div className="mt-2 text-[11px] text-zinc-600 italic">
            Score formula: accepted / (accepted + scanner-quality rejections).
            Broker/Policy rejections shown but don't penalise the score.
          </div>
        </div>
      )}
    </div>
  );
};

export default ScannerQualityPanel;
