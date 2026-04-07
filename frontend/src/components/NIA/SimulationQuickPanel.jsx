import React, { useState, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  History, ChevronDown, Settings, Zap, BarChart3,
  Loader2, FlaskConical, AlertTriangle
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../../utils/api';

const SimulationQuickPanel = memo(({ jobs, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(false);
  const [starting, setStarting] = useState(null);
  const [simBarSize, setSimBarSize] = useState('1 day');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [useMultiTimeframe, setUseMultiTimeframe] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState('default');
  const [maxSymbols, setMaxSymbols] = useState(1500);

  const strategies = [
    { value: 'default', label: 'Default (Momentum)', setup_type: 'MOMENTUM' },
    { value: 'gap_go', label: 'Gap & Go', setup_type: 'GAP_AND_GO' },
    { value: 'orb', label: 'Opening Range Breakout', setup_type: 'ORB' },
    { value: 'vwap_bounce', label: 'VWAP Bounce', setup_type: 'VWAP_BOUNCE' },
    { value: 'rvol_surge', label: 'RVOL Surge', setup_type: 'RVOL_SURGE' },
    { value: 'rubberband', label: 'Rubberband Long', setup_type: 'RUBBERBAND_LONG' }
  ];

  const simBarSizes = [
    { value: '1 min', label: '1 Min', description: 'Scalp' },
    { value: '5 mins', label: '5 Min', description: 'Intraday' },
    { value: '15 mins', label: '15 Min', description: 'Day Trade' },
    { value: '1 day', label: 'Daily', description: 'Swing' }
  ];

  const handleQuickTest = async () => {
    setStarting('quick');
    try {
      const { data } = await api.post(`/api/simulator/generate?bar_size=${encodeURIComponent(simBarSize)}`);
      if (data?.success) {
        toast.success(`Smart Test started: ${data.symbols_count} symbols on ${simBarSize} bars`);
        if (onRefresh) onRefresh();
      } else {
        toast.error('Failed to start simulation');
      }
    } catch (err) {
      toast.error('Error starting simulation');
    } finally {
      setStarting(null);
    }
  };

  const handleMarketWideBacktest = async () => {
    setStarting('market');
    try {
      const strategyConfig = strategies.find(s => s.value === selectedStrategy) || strategies[0];
      const res = await api.post('/api/backtest/market-wide', {
        strategy: {
          name: strategyConfig.label,
          setup_type: strategyConfig.setup_type,
          min_tqs_score: 60,
          stop_pct: 2.0,
          target_pct: 4.0
        },
        bar_size: simBarSize,
        use_multi_timeframe: useMultiTimeframe,
        max_symbols: maxSymbols,
        run_in_background: true
      });
      if (res.data?.success || res.data?.job_id) {
        const mtfNote = useMultiTimeframe ? ' (Multi-TF)' : '';
        toast.success(`Market-wide backtest started: ${maxSymbols} symbols, ${simBarSize}${mtfNote}`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(res.data?.error || res.data?.detail || 'Failed to start market-wide backtest');
      }
    } catch (err) {
      toast.error('Error starting market-wide backtest');
    } finally {
      setStarting(null);
    }
  };

  const recentJobs = jobs?.slice(0, 6) || [];
  const completedJobs = useMemo(() => jobs?.filter(j => j.status === 'completed') || [], [jobs]);
  const runningJobs = useMemo(() => jobs?.filter(j => j.status === 'running') || [], [jobs]);
  const totalTrades = useMemo(() => completedJobs.reduce((sum, j) => sum + (j.total_trades || 0), 0), [completedJobs]);
  const avgWinRate = useMemo(() => completedJobs.length > 0 ? completedJobs.reduce((sum, j) => sum + (j.win_rate || 0), 0) / completedJobs.length : 0, [completedJobs]);

  const formatDate = (dateStr) => {
    if (!dateStr) return '--';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="simulation-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="simulation-panel-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-violet-500/20">
            <History className="w-4 h-4 text-violet-400" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Historical Simulations</h3>
            <p className="text-xs text-zinc-400">
              {runningJobs.length > 0 ? `${runningJobs.length} running, ${completedJobs.length} completed` : `${completedJobs.length} backtests completed`}
            </p>
          </div>
        </div>
        <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
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
              {/* Settings Toggle */}
              <div className="mb-4">
                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1 mb-2"
                  data-testid="toggle-sim-settings"
                >
                  <Settings className="w-3 h-3" />
                  {showAdvanced ? 'Hide Settings' : 'Simulation Settings'}
                </button>

                <AnimatePresence>
                  {showAdvanced && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mb-3 space-y-3">
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">Timeframe</label>
                        <div className="flex gap-2">
                          {simBarSizes.map((opt) => (
                            <button
                              key={opt.value}
                              onClick={() => setSimBarSize(opt.value)}
                              className={`flex-1 px-2 py-1.5 rounded-lg border text-xs transition-all ${simBarSize === opt.value ? 'bg-violet-500/20 border-violet-500/50 text-violet-400' : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/5'}`}
                              data-testid={`sim-bar-size-${opt.value.replace(/\s+/g, '-')}`}
                            >
                              <div className="font-medium">{opt.label}</div>
                              <div className="text-[10px] text-zinc-500">{opt.description}</div>
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">Strategy</label>
                        <select
                          value={selectedStrategy}
                          onChange={(e) => setSelectedStrategy(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg bg-white/[0.02] border border-white/5 text-sm text-zinc-200 focus:outline-none focus:border-violet-500/50"
                          data-testid="strategy-select"
                        >
                          {strategies.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">Max Symbols: <span className="text-violet-400">{maxSymbols.toLocaleString()}</span></label>
                        <input type="range" min="100" max="1500" step="100" value={maxSymbols} onChange={(e) => setMaxSymbols(parseInt(e.target.value))} className="w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-violet-500" data-testid="max-symbols-slider" />
                        <div className="flex justify-between text-[10px] text-zinc-500 mt-0.5"><span>100</span><span>1,500</span></div>
                      </div>
                      <div className="flex items-center justify-between p-2 rounded-lg bg-white/[0.02] border border-white/5">
                        <div>
                          <div className="text-xs text-zinc-300">Multi-Timeframe Analysis</div>
                          <div className="text-[10px] text-zinc-500">Daily trend + {simBarSize} entries</div>
                        </div>
                        <button
                          onClick={() => setUseMultiTimeframe(!useMultiTimeframe)}
                          className={`w-10 h-5 rounded-full transition-all ${useMultiTimeframe ? 'bg-violet-500' : 'bg-zinc-700'}`}
                          data-testid="multi-timeframe-toggle"
                        >
                          <div className={`w-4 h-4 rounded-full bg-white shadow transform transition-transform ${useMultiTimeframe ? 'translate-x-5' : 'translate-x-0.5'}`} />
                        </button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-2 gap-2 mb-4">
                <button onClick={handleQuickTest} disabled={starting !== null} className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 transition-colors text-sm font-medium disabled:opacity-50" data-testid="quick-simulation-btn">
                  {starting === 'quick' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                  Smart Test <span className="text-[10px] text-violet-400/60">(30 symbols)</span>
                </button>
                <button onClick={handleMarketWideBacktest} disabled={starting !== null} className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500/20 to-violet-500/20 text-cyan-400 hover:from-cyan-500/30 hover:to-violet-500/30 transition-colors text-sm font-medium disabled:opacity-50" data-testid="market-wide-backtest-btn">
                  {starting === 'market' ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
                  Full Test <span className="text-[10px] text-cyan-400/60">({maxSymbols.toLocaleString()} symbols)</span>
                </button>
              </div>

              {/* Overall Stats */}
              {completedJobs.length > 0 && (
                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="p-2 rounded bg-white/[0.02] text-center"><div className="text-lg font-bold text-white">{completedJobs.length}</div><div className="text-[10px] text-zinc-500">Backtests</div></div>
                  <div className="p-2 rounded bg-white/[0.02] text-center"><div className={`text-lg font-bold ${avgWinRate >= 0.5 ? 'text-green-400' : 'text-yellow-400'}`}>{(avgWinRate * 100).toFixed(0)}%</div><div className="text-[10px] text-zinc-500">Avg Win Rate</div></div>
                  <div className="p-2 rounded bg-white/[0.02] text-center"><div className="text-lg font-bold text-white">{totalTrades}</div><div className="text-[10px] text-zinc-500">Total Trades</div></div>
                </div>
              )}

              {/* Job Cards */}
              {recentJobs.length > 0 ? (
                <div className="space-y-3">
                  <h4 className="text-xs text-zinc-500 uppercase">Recent Backtests</h4>
                  {recentJobs.map((job) => {
                    const isRunning = job.status === 'running';
                    const progress = job.symbols_total > 0 ? Math.round((job.symbols_processed / job.symbols_total) * 100) : 0;
                    const symbols = job.config?.custom_symbols || [];
                    const dateRange = job.config ? `${formatDate(job.config.start_date)} - ${formatDate(job.config.end_date)}` : '--';

                    return (
                      <div key={job.id || job.job_id} className={`rounded-lg border ${isRunning ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-white/5 bg-white/[0.02]'} overflow-hidden`}>
                        <div className="p-3 flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${job.status === 'completed' ? 'bg-green-400' : job.status === 'running' ? 'bg-cyan-400 animate-pulse' : job.status === 'failed' ? 'bg-red-400' : 'bg-zinc-400'}`} />
                            <div>
                              <div className="text-xs text-zinc-300 font-mono">{job.id || job.job_id}</div>
                              <div className="text-[10px] text-zinc-500">{dateRange}</div>
                            </div>
                          </div>
                          {isRunning ? (
                            <div className="text-right">
                              <div className="text-sm font-bold text-cyan-400">{progress}%</div>
                              <div className="text-[10px] text-zinc-500">{job.symbols_processed}/{job.symbols_total} symbols</div>
                            </div>
                          ) : (
                            <span className={`text-xs px-2 py-0.5 rounded ${job.status === 'completed' ? 'bg-green-500/20 text-green-400' : job.status === 'failed' ? 'bg-red-500/20 text-red-400' : 'bg-zinc-500/20 text-zinc-400'}`}>{job.status}</span>
                          )}
                        </div>
                        {isRunning && (
                          <div className="px-3 pb-2">
                            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-cyan-500 to-cyan-400 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
                            </div>
                          </div>
                        )}
                        {job.status === 'completed' && (
                          <div className="px-3 pb-3 pt-1 border-t border-white/5">
                            <div className="grid grid-cols-5 gap-2 text-center">
                              <div><div className="text-sm font-bold text-white">{job.total_trades || 0}</div><div className="text-[9px] text-zinc-500">Trades</div></div>
                              <div><div className={`text-sm font-bold ${(job.win_rate || 0) >= 0.5 ? 'text-green-400' : (job.win_rate || 0) > 0 ? 'text-yellow-400' : 'text-zinc-400'}`}>{job.total_trades > 0 ? `${(job.win_rate * 100).toFixed(0)}%` : '--'}</div><div className="text-[9px] text-zinc-500">Win Rate</div></div>
                              <div><div className={`text-sm font-bold ${(job.profit_factor || 0) >= 1 ? 'text-green-400' : (job.profit_factor || 0) > 0 ? 'text-yellow-400' : 'text-zinc-400'}`}>{job.total_trades > 0 ? (job.profit_factor || 0).toFixed(2) : '--'}</div><div className="text-[9px] text-zinc-500">PF</div></div>
                              <div><div className={`text-sm font-bold ${(job.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{job.total_trades > 0 ? `$${(job.total_pnl || 0).toFixed(0)}` : '--'}</div><div className="text-[9px] text-zinc-500">P&L</div></div>
                              <div><div className="text-sm font-bold text-white">{job.symbols_total || symbols.length || 0}</div><div className="text-[9px] text-zinc-500">Symbols</div></div>
                            </div>
                            {symbols.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {symbols.slice(0, 6).map((sym, idx) => <span key={idx} className="px-1.5 py-0.5 rounded text-[9px] bg-white/5 text-zinc-400">{sym}</span>)}
                                {symbols.length > 6 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-white/5 text-zinc-500">+{symbols.length - 6} more</span>}
                              </div>
                            )}
                            {job.total_trades === 0 && (
                              <div className="mt-2 p-2 rounded bg-yellow-500/10 border border-yellow-500/20">
                                <p className="text-[10px] text-yellow-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> No trade signals found in this period</p>
                              </div>
                            )}
                          </div>
                        )}
                        {job.status === 'failed' && job.error_message && (
                          <div className="px-3 pb-3"><div className="p-2 rounded bg-red-500/10 border border-red-500/20"><p className="text-[10px] text-red-400">{job.error_message}</p></div></div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-6">
                  <FlaskConical className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-sm text-zinc-400">No simulations yet</p>
                  <p className="text-xs text-zinc-500">Click "Quick Test" or "Market-Wide" to run a backtest</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default SimulationQuickPanel;
