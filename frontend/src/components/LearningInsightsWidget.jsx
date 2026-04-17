/**
 * Learning Insights Widget
 * ========================
 * Compact widget showing key learning metrics for the AI Coach tab.
 * Click to expand or navigate to full Learning Intelligence Hub.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { safePolling } from '../utils/safePolling';
import { 
  Brain, AlertTriangle, CheckCircle2, ChevronRight, 
  TrendingUp, TrendingDown, RefreshCw
} from 'lucide-react';
import api from '../utils/api';

const LearningInsightsWidget = ({ onNavigateToHub, className = '' }) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({
    winRate: null,
    todayPnl: null,
    avgR: null,
    edgeScore: null,
    alerts: []
  });

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, alertsRes] = await Promise.allSettled([
        api.get('/api/learning/strategy-stats'),
        api.get('/api/medium-learning/edge-decay/alerts')
      ]);

      const newData = { winRate: null, todayPnl: null, avgR: null, edgeScore: null, alerts: [] };

      if (statsRes.status === 'fulfilled' && statsRes.value.data?.success) {
        const strategies = statsRes.value.data.stats;
        
        // Aggregate across all strategies (exclude imported_from_ib which is manual trades)
        let totalTrades = 0;
        let totalWins = 0;
        let totalPnl = 0;
        let totalRR = 0;
        let rrCount = 0;
        
        Object.entries(strategies || {}).forEach(([name, s]) => {
          if (name === 'imported_from_ib') return; // Skip manual imports
          const trades = s.total_trades || 0;
          const wins = s.wins || 0;
          totalTrades += trades;
          totalWins += wins;
          totalPnl += s.total_pnl || 0;
          if (s.avg_rr_achieved && trades > 0) {
            totalRR += s.avg_rr_achieved * trades;
            rrCount += trades;
          }
        });
        
        if (totalTrades > 0) {
          newData.winRate = ((totalWins / totalTrades) * 100).toFixed(0);
          newData.todayPnl = totalPnl;
          newData.avgR = rrCount > 0 ? (totalRR / rrCount).toFixed(1) : null;
        }
        
        // Edge score from best-performing strategy with enough trades
        const viableStrategies = Object.entries(strategies || {})
          .filter(([name, s]) => name !== 'imported_from_ib' && (s.total_trades || 0) >= 3)
          .sort((a, b) => (b[1].win_rate || 0) - (a[1].win_rate || 0));
        
        if (viableStrategies.length > 0) {
          // Weighted edge: average win rate of viable strategies
          const avgWinRate = viableStrategies.reduce((sum, [, s]) => sum + (s.win_rate || 0), 0) / viableStrategies.length;
          newData.edgeScore = Math.round(avgWinRate);
        }
      }

      if (alertsRes.status === 'fulfilled' && alertsRes.value.data?.success) {
        newData.alerts = alertsRes.value.data.alerts || [];
      }

      setData(newData);
    } catch (err) {
      console.error('Error fetching learning insights:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Delay initial fetch to reduce startup burst
    const timer = setTimeout(() => fetchData(), 8000);
    const cleanup = safePolling(fetchData, 60000, { immediate: false });
    return () => { clearTimeout(timer); cleanup(); };
  }, [fetchData]);

  // Get top alerts (1 warning, 1 success)
  const warningAlert = data.alerts.find(a => 
    a.severity === 'warning' || a.severity === 'critical' || a.decay_percentage > 10
  );
  const successSetup = data.alerts.length === 0 ? null : 
    data.alerts.find(a => a.improvement_percentage > 5);

  const handleClick = () => {
    if (onNavigateToHub) {
      onNavigateToHub();
    }
  };

  if (loading) {
    return null; // Don't show loading state — appear only when data exists
  }

  // Hide entirely when there's no meaningful data
  const hasData = data.winRate !== null || data.todayPnl !== null || data.alerts.length > 0;
  if (!hasData) return null;

  return (
    <div 
      className={`bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-xl border border-purple-500/30 p-4 cursor-pointer hover:border-purple-500/50 transition-colors ${className}`}
      onClick={handleClick}
      data-testid="learning-insights-widget"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-medium text-white">Learning Insights</span>
        </div>
        <button 
          className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
          onClick={(e) => {
            e.stopPropagation();
            handleClick();
          }}
        >
          View Details <ChevronRight className="w-3 h-3" />
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <MiniStat 
          label="Win Rate" 
          value={data.winRate ? `${data.winRate}%` : '--'} 
          trend={data.winRate >= 55 ? 'up' : data.winRate < 50 ? 'down' : 'neutral'} 
        />
        <MiniStat 
          label="Today P&L" 
          value={data.todayPnl !== null && !isNaN(data.todayPnl) ? `${data.todayPnl >= 0 ? '+' : ''}$${Math.abs(data.todayPnl).toFixed(0)}` : '--'} 
          trend={data.todayPnl > 0 ? 'up' : data.todayPnl < 0 ? 'down' : 'neutral'} 
        />
        <MiniStat 
          label="Avg R" 
          value={data.avgR || '--'} 
          trend={parseFloat(data.avgR) >= 1.5 ? 'up' : 'neutral'} 
        />
        <MiniStat 
          label="Edge" 
          value={data.edgeScore || '--'} 
          trend={data.edgeScore >= 70 ? 'up' : data.edgeScore < 50 ? 'down' : 'neutral'} 
        />
      </div>

      {/* Alert Row */}
      <div className="flex items-center gap-3 text-xs flex-wrap">
        {warningAlert && (
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3 h-3 text-yellow-400" />
            <span className="text-yellow-400">
              {warningAlert.setup_type || warningAlert.strategy} edge degrading
            </span>
          </div>
        )}
        
        {successSetup && (
          <>
            {warningAlert && <span className="text-slate-600">•</span>}
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3 h-3 text-emerald-400" />
              <span className="text-emerald-400">
                {successSetup.setup_type || successSetup.strategy} performing well
              </span>
            </div>
          </>
        )}

        {!warningAlert && !successSetup && data.alerts.length === 0 && (
          <span className="text-slate-500">All edges healthy</span>
        )}
      </div>
    </div>
  );
};

const MiniStat = ({ label, value, trend }) => (
  <div className="text-center">
    <div className="text-xs text-slate-500">{label}</div>
    <div className={`text-sm font-bold ${
      trend === 'up' ? 'text-emerald-400' :
      trend === 'down' ? 'text-red-400' : 'text-white'
    }`}>
      {value}
    </div>
  </div>
);

export default LearningInsightsWidget;
