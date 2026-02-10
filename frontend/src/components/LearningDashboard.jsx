/**
 * LearningDashboard - Strategy Performance & Auto-Tuning UI
 * Shows per-strategy performance, AI recommendations, and tuning history.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  TrendingUp,
  TrendingDown,
  Target,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Loader2,
  Zap,
  Clock,
  BarChart3,
  Sliders
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
    <div className="space-y-4" data-testid="learning-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-violet-400" />
          <h3 className="text-base font-semibold text-white">Learning Loop</h3>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400 border border-violet-500/30">
            AI-Powered
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runAnalysis}
            disabled={isAnalyzing || !hasData}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 border border-violet-500/30 disabled:opacity-50 transition-colors"
            data-testid="run-analysis-btn"
          >
            {isAnalyzing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            {isAnalyzing ? 'Analyzing...' : 'Run AI Analysis'}
          </button>
          <button onClick={fetchData} className="p-1.5 hover:bg-zinc-700 rounded" data-testid="refresh-learning">
            <RefreshCw className="w-3.5 h-3.5 text-zinc-400" />
          </button>
        </div>
      </div>

      {!hasData ? (
        <div className="text-center py-8 text-zinc-500">
          <BarChart3 className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No performance data yet</p>
          <p className="text-xs mt-1">Close some trades and the learning loop will start tracking</p>
        </div>
      ) : (
        <>
          {/* Strategy Performance Cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
            {sortedStats.map(([strategy, perf]) => (
              <StrategyCard key={strategy} strategy={strategy} perf={perf} tfColors={tfColors} />
            ))}
          </div>

          {/* AI Recommendations */}
          {recommendations.length > 0 && (
            <div className="p-4 bg-zinc-900/60 rounded-xl border border-violet-500/20" data-testid="recommendations-section">
              <div className="flex items-center gap-2 mb-3">
                <Sliders className="w-4 h-4 text-violet-400" />
                <h4 className="text-sm font-semibold text-white">AI Tuning Recommendations</h4>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
                  {recommendations.length} pending
                </span>
              </div>
              <div className="space-y-2">
                {recommendations.map((rec) => (
                  <div
                    key={rec.id}
                    className="flex items-center justify-between p-3 bg-zinc-800/60 rounded-lg border border-zinc-700/40"
                    data-testid={`recommendation-${rec.id}`}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-semibold text-white">
                          {rec.strategy?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          {rec.parameter}: {rec.current_value} &rarr; {rec.suggested_value}
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-400 leading-relaxed">{rec.reasoning}</p>
                    </div>
                    <div className="flex items-center gap-1.5 ml-3">
                      <button
                        onClick={() => handleRecommendation(rec.id, 'apply')}
                        disabled={actionLoading === rec.id}
                        className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30 transition-colors"
                        data-testid={`apply-rec-${rec.id}`}
                      >
                        {actionLoading === rec.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                        Apply
                      </button>
                      <button
                        onClick={() => handleRecommendation(rec.id, 'dismiss')}
                        disabled={actionLoading === rec.id}
                        className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-zinc-600/30 text-zinc-400 hover:bg-zinc-600/50 border border-zinc-600/30 transition-colors"
                        data-testid={`dismiss-rec-${rec.id}`}
                      >
                        <XCircle className="w-3 h-3" />
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Analysis */}
          {analysis && (
            <div className="p-4 bg-zinc-900/60 rounded-xl border border-zinc-700/30" data-testid="ai-analysis-section">
              <div className="flex items-center gap-2 mb-3">
                <Brain className="w-4 h-4 text-violet-400" />
                <h4 className="text-sm font-semibold text-white">AI Performance Analysis</h4>
              </div>
              <div className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto pr-2">
                {analysis}
              </div>
            </div>
          )}

          {/* Tuning History */}
          <div className="p-3 bg-zinc-900/40 rounded-xl border border-zinc-700/20">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="flex items-center gap-2 w-full text-left"
              data-testid="toggle-tuning-history"
            >
              {showHistory ? <ChevronDown className="w-4 h-4 text-zinc-400" /> : <ChevronRight className="w-4 h-4 text-zinc-400" />}
              <Clock className="w-4 h-4 text-zinc-500" />
              <span className="text-xs font-medium text-zinc-400">Tuning History ({tuningHistory.length})</span>
            </button>
            <AnimatePresence>
              {showHistory && tuningHistory.length > 0 && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-2 space-y-1 overflow-hidden"
                >
                  {tuningHistory.map((h, i) => (
                    <div key={i} className="flex items-center justify-between p-2 bg-zinc-800/40 rounded text-[11px]">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        <span className="text-zinc-300 font-medium">
                          {h.strategy?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                        </span>
                        <span className="text-zinc-500 font-mono">
                          {h.parameter}: {h.old_value} &rarr; {h.new_value}
                        </span>
                      </div>
                      <span className="text-zinc-600 text-[10px]">
                        {h.applied_at ? new Date(h.applied_at).toLocaleDateString() : ''}
                      </span>
                    </div>
                  ))}
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
      className="p-3 bg-zinc-900/60 rounded-xl border border-zinc-700/30 hover:border-zinc-600/50 transition-colors"
      data-testid={`strategy-card-${strategy}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">
            {strategy.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
          </span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${tfStyle}`}>
            {perf.timeframe?.toUpperCase()}
          </span>
        </div>
        <span className={`text-sm font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          ${perf.total_pnl?.toFixed(0)}
        </span>
      </div>
      
      {/* Win/Loss Bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-full"
            style={{ width: `${perf.win_rate || 0}%` }}
          />
        </div>
        <span className="text-[11px] font-mono text-zinc-300 w-12 text-right">
          {perf.win_rate?.toFixed(0)}% W
        </span>
      </div>
      
      {/* Stats Grid */}
      <div className="grid grid-cols-3 gap-2">
        <StatItem label="Trades" value={perf.total_trades} />
        <StatItem label="W / L" value={`${perf.wins}/${perf.losses}`} />
        <StatItem label="Avg P&L" value={`$${perf.avg_pnl?.toFixed(0)}`} color={perf.avg_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
        <StatItem label="Best" value={`$${perf.best_trade?.toFixed(0)}`} color="text-emerald-400" />
        <StatItem label="Worst" value={`$${perf.worst_trade?.toFixed(0)}`} color="text-red-400" />
        <StatItem label="Stop %" value={`${stopRate.toFixed(0)}%`} color={stopRate > 50 ? 'text-amber-400' : 'text-zinc-300'} />
      </div>
    </div>
  );
};

const StatItem = ({ label, value, color = 'text-zinc-200' }) => (
  <div>
    <span className="text-[9px] text-zinc-500 block">{label}</span>
    <span className={`text-[11px] font-mono font-medium ${color}`}>{value}</span>
  </div>
);

export default LearningDashboard;
