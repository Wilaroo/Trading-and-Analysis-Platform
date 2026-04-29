import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BarChart3, ChevronDown, Target, Layers, Zap } from 'lucide-react';

const ReportCardPanel = memo(({ reportCard, loading }) => {
  const [expanded, setExpanded] = useState(true);

  const getWinRateColor = (wr) => {
    if (wr >= 0.55) return 'text-green-400';
    if (wr >= 0.5) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getWinRateBg = (wr) => {
    if (wr >= 0.55) return 'bg-green-500/20';
    if (wr >= 0.5) return 'bg-yellow-500/20';
    return 'bg-red-500/20';
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="report-card-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="report-card-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
            <BarChart3 className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Your Trading Report Card</h3>
            <p className="text-xs text-zinc-400">Personal performance insights</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {reportCard?.overall_stats?.total_trades > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
              {reportCard.overall_stats.total_trades} trades
            </span>
          )}
          <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-white/10"
          >
            <div className="p-4">
              {!reportCard?.has_data ? (
                <div className="text-center py-6">
                  <BarChart3 className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-sm text-zinc-400">No trading data yet</p>
                  <p className="text-xs text-zinc-500 mt-1">Complete some trades to see your report card</p>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-4 gap-2 mb-4">
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className="text-lg font-bold text-white">{reportCard.overall_stats?.total_trades || 0}</div>
                      <div className="text-[12px] text-zinc-500">Total Trades</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className={`text-lg font-bold ${getWinRateColor(reportCard.overall_stats?.win_rate || 0)}`}>
                        {((reportCard.overall_stats?.win_rate || 0) * 100).toFixed(0)}%
                      </div>
                      <div className="text-[12px] text-zinc-500">Win Rate</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className={`text-lg font-bold ${(reportCard.overall_stats?.avg_r_multiple || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {(reportCard.overall_stats?.avg_r_multiple || 0).toFixed(2)}R
                      </div>
                      <div className="text-[12px] text-zinc-500">Avg R</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className="text-lg font-bold text-cyan-400">{reportCard.overall_stats?.winning_trades || 0}</div>
                      <div className="text-[12px] text-zinc-500">Winners</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                        <Target className="w-3 h-3" /> By Symbol
                      </h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {reportCard.by_symbol?.map((sym) => (
                          <div key={sym.symbol} className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5">
                            <span className="text-xs text-zinc-300 font-mono">{sym.symbol}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${getWinRateBg(sym.win_rate)} ${getWinRateColor(sym.win_rate)}`}>
                                {(sym.win_rate * 100).toFixed(0)}%
                              </span>
                              <span className="text-[12px] text-zinc-500">({sym.total_trades})</span>
                            </div>
                          </div>
                        ))}
                        {(!reportCard.by_symbol || reportCard.by_symbol.length === 0) && (
                          <div className="text-xs text-zinc-500 text-center py-2">No symbol data</div>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                        <Layers className="w-3 h-3" /> By Setup Type
                      </h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {reportCard.by_setup?.map((setup) => (
                          <div key={setup.setup_type} className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5">
                            <span className="text-xs text-zinc-300">{setup.setup_type}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${getWinRateBg(setup.win_rate)} ${getWinRateColor(setup.win_rate)}`}>
                                {(setup.win_rate * 100).toFixed(0)}%
                              </span>
                              <span className="text-[12px] text-zinc-500">({setup.traded_count})</span>
                            </div>
                          </div>
                        ))}
                        {(!reportCard.by_setup || reportCard.by_setup.length === 0) && (
                          <div className="text-xs text-zinc-500 text-center py-2">No setup data</div>
                        )}
                      </div>
                    </div>
                  </div>

                  {reportCard.insights && reportCard.insights.length > 0 && (
                    <div className="mt-4 p-3 rounded-lg border border-amber-500/20 bg-amber-500/5">
                      <h4 className="text-xs font-semibold text-amber-400 mb-2 flex items-center gap-1">
                        <Zap className="w-3 h-3" /> Insights
                      </h4>
                      <ul className="space-y-1">
                        {reportCard.insights.map((insight, idx) => (
                          <li key={idx} className="text-xs text-zinc-300 flex items-start gap-2">
                            <span className="text-amber-500 mt-0.5">•</span>
                            {insight}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default ReportCardPanel;
