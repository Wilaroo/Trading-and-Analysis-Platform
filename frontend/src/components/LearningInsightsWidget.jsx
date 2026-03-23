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

      const newData = { ...data };

      if (statsRes.status === 'fulfilled' && statsRes.value.data?.success) {
        const stats = statsRes.value.data.stats;
        newData.winRate = stats.win_rate ? (stats.win_rate * 100).toFixed(0) : null;
        newData.todayPnl = stats.today_pnl;
        newData.avgR = stats.avg_r_multiple?.toFixed(1);
        newData.edgeScore = stats.edge_score || stats.overall_score;
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
    fetchData();
    return safePolling(fetchData, 60000, { immediate: false });
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
    return (
      <div className={`bg-slate-800/30 rounded-xl border border-slate-700/30 p-4 ${className}`}>
        <div className="flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-slate-500 animate-spin" />
          <span className="text-sm text-slate-500">Loading insights...</span>
        </div>
      </div>
    );
  }

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
