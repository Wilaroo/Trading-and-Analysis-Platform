/**
 * DataHeatmap — Visual coverage grid
 * Rows = Tiers (Intraday/Swing/Investment)
 * Columns = Bar sizes
 * Cells = Gradient color-coded by coverage %
 */
import React, { useState, memo, useMemo } from 'react';
import { Zap, TrendingUp, Layers, Clock, AlertTriangle } from 'lucide-react';

const TIER_META = {
  intraday: { icon: Zap, color: 'text-yellow-400', accent: '#eab308' },
  swing: { icon: TrendingUp, color: 'text-cyan-400', accent: '#06b6d4' },
  investment: { icon: Layers, color: 'text-violet-400', accent: '#8b5cf6' },
};

const ALL_TIMEFRAMES = ['1 min', '5 mins', '15 mins', '30 mins', '1 hour', '1 day', '1 week'];
const TF_SHORT = { '1 min': '1m', '5 mins': '5m', '15 mins': '15m', '30 mins': '30m', '1 hour': '1h', '1 day': '1D', '1 week': '1W' };

function getCellColor(pct) {
  if (pct >= 98) return 'bg-emerald-500/50 border-emerald-500/40';
  if (pct >= 90) return 'bg-emerald-500/30 border-emerald-500/25';
  if (pct >= 75) return 'bg-teal-500/25 border-teal-500/20';
  if (pct >= 50) return 'bg-amber-500/20 border-amber-500/20';
  if (pct >= 25) return 'bg-orange-500/20 border-orange-500/20';
  if (pct > 0) return 'bg-rose-500/15 border-rose-500/20';
  return 'bg-zinc-800/30 border-zinc-700/20';
}

function getCellTextColor(pct) {
  if (pct >= 90) return 'text-emerald-300';
  if (pct >= 75) return 'text-teal-300';
  if (pct >= 50) return 'text-amber-300';
  if (pct >= 25) return 'text-orange-300';
  if (pct > 0) return 'text-rose-300';
  return 'text-zinc-600';
}

function formatBars(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

const HeatmapCell = memo(({ tf, queuePending }) => {
  const [hovered, setHovered] = useState(false);
  const pct = tf?.coverage_pct ?? -1;
  const isNA = pct === -1;

  if (isNA) {
    return (
      <div className="flex items-center justify-center rounded-md bg-zinc-900/40 border border-zinc-800/30 min-h-[52px]">
        <span className="text-[11px] text-zinc-700">--</span>
      </div>
    );
  }

  return (
    <div
      className={`relative rounded-md border transition-all duration-200 min-h-[52px] flex flex-col items-center justify-center cursor-default
        ${getCellColor(pct)} ${hovered ? 'scale-105 z-10 shadow-lg shadow-black/40' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      data-testid={`heatmap-cell-${tf.timeframe}`}
    >
      {/* Coverage % */}
      <span className={`text-sm font-bold leading-none ${getCellTextColor(pct)}`}>
        {pct}%
      </span>

      {/* Bar count */}
      <span className="text-[8px] text-zinc-500 mt-0.5">
        {formatBars(tf.total_bars)} bars
      </span>

      {/* Pending badge */}
      {queuePending > 0 && (
        <span className="absolute -top-1.5 -right-1.5 px-1 py-0.5 rounded-full bg-amber-500/90 text-[7px] text-black font-bold leading-none">
          {queuePending > 999 ? `${(queuePending / 1000).toFixed(0)}K` : queuePending}
        </span>
      )}

      {/* Hover tooltip */}
      {hovered && (
        <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 px-2.5 py-1.5 rounded-lg bg-zinc-900 border border-zinc-700 shadow-xl z-20 whitespace-nowrap">
          <p className="text-[12px] text-white font-medium">{tf.symbols_with_data}/{tf.symbols_needed} symbols</p>
          <p className="text-[11px] text-zinc-400">{tf.total_bars?.toLocaleString()} total bars</p>
          {queuePending > 0 && <p className="text-[11px] text-amber-400">{queuePending.toLocaleString()} pending in queue</p>}
        </div>
      )}
    </div>
  );
});

const DataHeatmap = memo(({ dataCoverage, queueProgress }) => {
  // Build heatmap matrix: tier → timeframe → cell data
  const matrix = useMemo(() => {
    if (!dataCoverage?.by_tier) return [];
    return dataCoverage.by_tier.map(tier => {
      const tfMap = {};
      (tier.timeframes || []).forEach(tf => { tfMap[tf.timeframe] = tf; });
      return {
        tier: tier.tier,
        description: tier.description,
        totalSymbols: tier.total_symbols,
        cells: ALL_TIMEFRAMES.map(tf => tfMap[tf] || null),
      };
    });
  }, [dataCoverage]);

  // Queue pending per bar_size
  const pendingMap = useMemo(() => {
    const m = {};
    (queueProgress?.by_bar_size || []).forEach(bs => { m[bs.bar_size] = bs.pending || 0; });
    return m;
  }, [queueProgress]);

  // Aggregate stats
  const totalBars = dataCoverage?.by_timeframe?.reduce((s, t) => s + (t.total_bars || 0), 0) || 0;
  const totalGaps = dataCoverage?.total_gaps || 0;
  const totalSymbols = dataCoverage?.adv_cache?.total_symbols || 0;

  if (!dataCoverage?.by_tier) return null;

  return (
    <div data-testid="data-heatmap">
      {/* Summary strip */}
      <div className="flex items-center gap-4 mb-3 text-[12px]">
        <span className="text-zinc-400">{totalSymbols.toLocaleString()} symbols</span>
        <span className="text-zinc-600">&bull;</span>
        <span className="text-zinc-400">{formatBars(totalBars)} bars</span>
        <span className="text-zinc-600">&bull;</span>
        <span className={totalGaps > 0 ? 'text-amber-400' : 'text-emerald-400'}>
          {totalGaps > 0 ? `${totalGaps} gaps` : 'No gaps'}
        </span>
      </div>

      {/* Heatmap Grid */}
      <div className="rounded-xl border border-white/5 bg-black/30 overflow-hidden">
        {/* Column headers */}
        <div className="grid gap-1 px-3 pt-3 pb-1" style={{ gridTemplateColumns: '100px repeat(7, 1fr)' }}>
          <div /> {/* Empty corner */}
          {ALL_TIMEFRAMES.map(tf => (
            <div key={tf} className="text-center">
              <span className="text-[12px] font-medium text-zinc-400">{TF_SHORT[tf]}</span>
            </div>
          ))}
        </div>

        {/* Tier rows */}
        {matrix.map((row, i) => {
          const meta = TIER_META[row.tier] || TIER_META.intraday;
          const Icon = meta.icon;
          const overallPct = row.cells.reduce((sum, c) => sum + (c?.coverage_pct || 0), 0) / row.cells.filter(c => c).length || 0;

          return (
            <div
              key={row.tier}
              className={`grid gap-1 px-3 py-2 ${i < matrix.length - 1 ? 'border-b border-white/5' : ''}`}
              style={{ gridTemplateColumns: '100px repeat(7, 1fr)' }}
              data-testid={`heatmap-row-${row.tier}`}
            >
              {/* Row header */}
              <div className="flex items-center gap-1.5 pr-2">
                <Icon className={`w-3.5 h-3.5 ${meta.color} flex-shrink-0`} />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-white capitalize truncate">{row.tier}</p>
                  <p className="text-[8px] text-zinc-600">{row.totalSymbols?.toLocaleString()} sym</p>
                </div>
              </div>

              {/* Cells */}
              {row.cells.map((cell, j) => (
                <HeatmapCell
                  key={ALL_TIMEFRAMES[j]}
                  tf={cell}
                  queuePending={pendingMap[ALL_TIMEFRAMES[j]] || 0}
                />
              ))}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-1 mt-2">
        {[
          { label: '0%', cls: 'bg-zinc-800/30' },
          { label: '25%', cls: 'bg-orange-500/20' },
          { label: '50%', cls: 'bg-amber-500/20' },
          { label: '75%', cls: 'bg-teal-500/25' },
          { label: '90%', cls: 'bg-emerald-500/30' },
          { label: '100%', cls: 'bg-emerald-500/50' },
        ].map((item, i) => (
          <div key={i} className="flex items-center gap-1">
            <div className={`w-3 h-3 rounded-sm ${item.cls}`} />
            <span className="text-[8px] text-zinc-600">{item.label}</span>
          </div>
        ))}
      </div>

      {/* Gaps warning */}
      {totalGaps > 0 && dataCoverage.missing?.length > 0 && (
        <div className="mt-3 p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/15">
          <div className="flex items-center gap-1.5 mb-1">
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            <span className="text-[12px] font-medium text-amber-400">{totalGaps} Data Gaps</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {dataCoverage.missing.slice(0, 8).map((gap, i) => (
              <span key={i} className="px-1.5 py-0.5 rounded bg-amber-500/10 text-[8px] text-amber-300">
                {gap.tier} {TF_SHORT[gap.timeframe] || gap.timeframe}: {gap.missing_symbols} missing
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

export default DataHeatmap;
