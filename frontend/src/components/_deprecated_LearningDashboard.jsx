/**
 * LearningDashboard - Strategy Performance & Auto-Tuning UI
 * Shows per-strategy performance, AI recommendations, and tuning history.
 * 
 * UPDATED: Uses "We/Our" voice and unified Team Brain aesthetics.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  TrendingUp,
  Target,
  CheckCircle2,
  XCircle,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Loader2,
  Zap,
  Clock,
  BarChart3,
  Sliders,
  ShieldCheck,
  Users
} from 'lucide-react';
import api from '../utils/api';

const LearningDashboard = () => {
  const [stats, setStats] = useState({});
  const [recommendations, setRecommendations] = useState([]);
  const [tuningHistory, setTuningHistory] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, recsRes, histRes] = await Promise.all([
        api.get('/api/learning/strategy-stats'),
        api.get('/api/learning/recommendations'),
        api.get('/api/learning/tuning-history?limit=10')
      ]);
      if (statsRes.data?.success) setStats(statsRes.data.stats);
      if (recsRes.data?.success) setRecommendations(recsRes.data.recommendations);
      if (histRes.data?.success) setTuningHistory(histRes.data.history);
    } catch (err) {
      console.error('Failed to fetch learning data:', err);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const runAnalysis = async () => {
    setIsAnalyzing(true);
    try {
      const res = await api.post('/api/learning/analyze');
      if (res.data?.success) {
        setAnalysis(res.data.analysis);
        if (res.data.recommendations?.length) {
          setRecommendations(res.data.recommendations);
        }
      }
    } catch (err) {
      console.error('Analysis failed:', err);
    }
    setIsAnalyzing(false);
  };

  const handleRecommendation = async (recId, action) => {
    setActionLoading(recId);
    try {
      await api.post(`/api/learning/recommendations/${recId}`, { action });
      await fetchData();
    } catch (err) {
      console.error('Recommendation action failed:', err);
    }
    setActionLoading(null);
  };

  const strategyOrder = ['rubber_band', 'vwap_bounce', 'breakout', 'squeeze', 'trend_continuation', 'position_trade'];
  const sortedStats = Object.entries(stats).sort((a, b) => {
    const ia = strategyOrder.indexOf(a[0]);
    const ib = strategyOrder.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });

  const tfColors = {
    scalp: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
    intraday: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
    swing: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
    position: 'bg-violet-500/15 text-violet-400 border-violet-500/30'
  };

  const hasData = sortedStats.length > 0;

  return (
    <div className="space-y-6" data-testid="learning-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/5 pb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-violet-500/10 rounded-lg border border-violet-500/20">
            <Users className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white tracking-tight">Team Performance</h3>
            <p className="text-xs text-zinc-500">How we are performing across strategies</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <button
            onClick={runAnalysis}
            disabled={isAnalyzing || !hasData}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 border border-violet-500/30 disabled:opacity-50 transition-all hover:scale-[1.02]"
            data-testid="run-analysis-btn"
          >
            {isAnalyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Brain className="w-3.5 h-3.5" />}
            {isAnalyzing ? 'Analyzing...' : 'Run Team Analysis'}
          </button>
          <button onClick={fetchData} className="p-2 hover:bg-zinc-800 rounded-lg transition-colors" data-testid="refresh-learning">
            <RefreshCw className="w-4 h-4 text-zinc-400" />
          </button>
        </div>
      </div>

      {!hasData ? (
        <div className="flex flex-col items-center justify-center py-12 text-zinc-500 bg-zinc-900/30 rounded-xl border border-white/5 border-dashed">
          <BarChart3 className="w-10 h-10 mb-3 opacity-30" />
          <p className="text-sm font-medium text-zinc-400">No performance data collected yet</p>
          <p className="text-xs mt-1 opacity-60">Once we execute trades, our metrics will appear here.</p>
        </div>
      ) : (
        <>
          {/* Strategy Performance Cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {sortedStats.map(([strategy, perf]) => (
              <StrategyCard key={strategy} strategy={strategy} perf={perf} tfColors={tfColors} />
            ))}
          </div>

          {/* AI Recommendations */}
          {recommendations.length > 0 && (
            <div className="p-5 bg-gradient-to-br from-zinc-900 to-black rounded-xl border border-violet-500/20 shadow-lg" data-testid="recommendations-section">
              <div className="flex items-center gap-2 mb-4">
                <Sliders className="w-4 h-4 text-violet-400" />
                <h4 className="text-sm font-bold text-white uppercase tracking-wider">Optimization Opportunities</h4>
                <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300 border border-violet-500/30">
                  {recommendations.length} SUGGESTIONS
                </span>
              </div>
              <div className="space-y-3">
                {recommendations.map((rec) => (
                  <div
                    key={rec.id}
                    className="flex flex-col sm:flex-row sm:items-center justify-between p-4 bg-zinc-800/40 rounded-lg border border-white/5 hover:border-violet-500/30 transition-colors group"
                    data-testid={`recommendation-${rec.id}`}
                  >
                    <div className="flex-1 mb-3 sm:mb-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-xs font-bold text-white bg-zinc-700/50 px-1.5 py-0.5 rounded">
                          {rec.strategy?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono flex items-center gap-1">
                          {rec.parameter} 
                          <span className="text-zinc-600">→</span> 
                          <span className="text-violet-300">{rec.suggested_value}</span>
                        </span>
                      </div>
                      <p className="text-xs text-zinc-400 leading-relaxed group-hover:text-zinc-300 transition-colors">{rec.reasoning}</p>
                    </div>
                    <div className="flex items-center gap-2 sm:ml-4">
                      <button
                        onClick={() => handleRecommendation(rec.id, 'apply')}
                        disabled={actionLoading === rec.id}
                        className="flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-all"
                        data-testid={`apply-rec-${rec.id}`}
                      >
                        {actionLoading === rec.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                        Apply
                      </button>
                      <button
                        onClick={() => handleRecommendation(rec.id, 'dismiss')}
                        disabled={actionLoading === rec.id}
                        className="flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-zinc-800 text-zinc-400 hover:bg-zinc-700 border border-white/5 transition-colors"
                        data-testid={`dismiss-rec-${rec.id}`}
                      >
                        <XCircle className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Analysis */}
          {analysis && (
            <div className="p-5 bg-zinc-900/60 rounded-xl border border-white/10" data-testid="ai-analysis-section">
              <div className="flex items-center gap-2 mb-3">
                <ShieldCheck className="w-4 h-4 text-violet-400" />
                <h4 className="text-sm font-bold text-white uppercase tracking-wider">Strategic Analysis</h4>
              </div>
              <div className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap font-sans">
                {analysis}
              </div>
            </div>
          )}

          {/* Tuning History */}
          <div className="rounded-xl border border-white/5 bg-zinc-900/20 overflow-hidden">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="flex items-center justify-between w-full p-4 hover:bg-white/5 transition-colors"
              data-testid="toggle-tuning-history"
            >
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-zinc-500" />
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Optimization Log</span>
                <span className="px-1.5 py-0.5 rounded-full bg-zinc-800 text-[10px] text-zinc-500">{tuningHistory.length}</span>
              </div>
              {showHistory ? <ChevronDown className="w-4 h-4 text-zinc-500" /> : <ChevronRight className="w-4 h-4 text-zinc-500" />}
            </button>
            <AnimatePresence>
              {showHistory && tuningHistory.length > 0 && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-t border-white/5"
                >
                  <div className="max-h-60 overflow-y-auto">
                    {tuningHistory.map((h, i) => (
                      <div key={i} className="flex items-center justify-between px-4 py-3 border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors">
                        <div className="flex items-center gap-3">
                          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          <div className="flex flex-col">
                            <span className="text-xs font-medium text-zinc-200">
                              {h.strategy?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                            </span>
                            <span className="text-[10px] text-zinc-500 font-mono mt-0.5">
                              {h.parameter}: <span className="text-zinc-400 line-through">{h.old_value}</span> <span className="text-emerald-400">→ {h.new_value}</span>
                            </span>
                          </div>
                        </div>
                        <span className="text-[10px] text-zinc-600 font-mono">
                          {h.applied_at ? new Date(h.applied_at).toLocaleDateString() : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </>
      )}
    </div>
  );
};

// Strategy Performance Card component
const StrategyCard = ({ strategy, perf, tfColors }) => {
  const isPositive = perf.total_pnl >= 0;
  const tfStyle = tfColors[perf.timeframe] || tfColors.intraday;
  
  // Calculate stop rate
  const totalStops = (perf.close_reasons?.stop_loss || 0) + 
                     (perf.close_reasons?.stop_loss_trailing || 0) +
                     (perf.close_reasons?.stop_loss_breakeven || 0);
  const stopRate = perf.total_trades > 0 ? (totalStops / perf.total_trades * 100) : 0;
  
  return (
    <div
      className="group p-4 bg-zinc-900/60 rounded-xl border border-white/5 hover:border-violet-500/30 hover:bg-zinc-900/80 transition-all duration-300 relative overflow-hidden"
      data-testid={`strategy-card-${strategy}`}
    >
      <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-br from-violet-500/10 to-transparent rounded-bl-full -mr-8 -mt-8 pointer-events-none group-hover:from-violet-500/20 transition-colors" />
      
      {/* Header */}
      <div className="flex items-center justify-between mb-4 relative z-10">
        <div className="flex flex-col gap-1">
          <span className="text-sm font-bold text-white tracking-tight">
            {strategy.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
          </span>
          <span className={`self-start text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider ${tfStyle}`}>
            {perf.timeframe?.toUpperCase()}
          </span>
        </div>
        <div className="text-right">
          <span className={`block text-lg font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
            ${perf.total_pnl?.toFixed(0)}
          </span>
          <span className="text-[10px] text-zinc-500 font-mono">Net P&L</span>
        </div>
      </div>
      
      {/* Win/Loss Bar */}
      <div className="mb-4 relative z-10">
        <div className="flex justify-between text-[10px] text-zinc-400 mb-1.5 font-mono">
          <span>WIN RATE</span>
          <span className={perf.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400'}>{perf.win_rate?.toFixed(0)}%</span>
        </div>
        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${perf.win_rate >= 50 ? 'bg-emerald-500' : 'bg-amber-500'}`}
            style={{ width: `${perf.win_rate || 0}%` }}
          />
        </div>
      </div>
      
      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-y-3 gap-x-2 relative z-10 pt-2 border-t border-white/5">
        <StatItem label="Total Trades" value={perf.total_trades} icon={<Activity className="w-3 h-3" />} />
        <StatItem label="Win / Loss" value={`${perf.wins} / ${perf.losses}`} />
        <StatItem label="Avg Trade" value={`$${perf.avg_pnl?.toFixed(0)}`} color={perf.avg_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'} />
        <StatItem label="Profit Factor" value={perf.profit_factor?.toFixed(2) || '0.00'} color="text-zinc-200" />
      </div>
    </div>
  );
};

const StatItem = ({ label, value, color = 'text-zinc-300', icon }) => (
  <div className="flex flex-col">
    <span className="text-[10px] text-zinc-500 mb-0.5 flex items-center gap-1">
      {icon}
      {label}
    </span>
    <span className={`text-xs font-mono font-medium ${color}`}>{value}</span>
  </div>
);

export default LearningDashboard;
