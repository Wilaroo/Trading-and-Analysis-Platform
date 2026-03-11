/**
 * Learning Intelligence Hub
 * =========================
 * Unified dashboard for all learning insights, replacing the old Analytics tab structure.
 * Combines trader profile, edge health, performance metrics, and AI recommendations.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { 
  Brain, TrendingUp, TrendingDown, Target, AlertTriangle, CheckCircle2,
  BarChart3, Activity, Zap, Clock, Calendar, ChevronRight, ChevronDown,
  Lightbulb, Shield, TestTubes, Layers, RefreshCw, Settings,
  ArrowUpRight, ArrowDownRight, Loader2, XCircle
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';

const LearningIntelligenceHub = () => {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [data, setData] = useState({
    profile: null,
    metrics: null,
    edgeHealth: [],
    recommendations: [],
    weeklyStats: [],
    calibration: null
  });
  const [expandedSections, setExpandedSections] = useState({
    backtest: false,
    shadow: false
  });

  const fetchAllData = useCallback(async (showToast = false) => {
    try {
      if (showToast) setRefreshing(true);
      else setLoading(true);

      // Fetch all learning data in parallel
      const [
        statsRes,
        recsRes,
        profileRes,
        edgeRes,
        calibrationRes
      ] = await Promise.allSettled([
        api.get('/api/learning/strategy-stats'),
        api.get('/api/learning/recommendations'),
        api.get('/api/learning/loop/profile'),
        api.get('/api/medium-learning/edge-decay/alerts'),
        api.get('/api/medium-learning/calibration/current')
      ]);

      const newData = { ...data };

      // Process strategy stats
      if (statsRes.status === 'fulfilled' && statsRes.value.data?.success) {
        newData.metrics = statsRes.value.data.stats;
      }

      // Process recommendations
      if (recsRes.status === 'fulfilled' && recsRes.value.data?.success) {
        newData.recommendations = recsRes.value.data.recommendations || [];
      }

      // Process trader profile
      if (profileRes.status === 'fulfilled' && profileRes.value.data?.success) {
        newData.profile = profileRes.value.data.profile;
      }

      // Process edge decay alerts
      if (edgeRes.status === 'fulfilled' && edgeRes.value.data?.success) {
        newData.edgeHealth = edgeRes.value.data.alerts || [];
      }

      // Process calibration
      if (calibrationRes.status === 'fulfilled' && calibrationRes.value.data?.success) {
        newData.calibration = calibrationRes.value.data.calibration;
      }

      // Generate weekly stats from metrics if available
      if (newData.metrics?.daily_stats) {
        newData.weeklyStats = newData.metrics.daily_stats.slice(-5);
      }

      setData(newData);

      if (showToast) {
        toast.success('Learning data refreshed');
      }
    } catch (err) {
      console.error('Error fetching learning data:', err);
      if (showToast) {
        toast.error('Failed to refresh data');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAllData();
    // Refresh every 5 minutes
    const interval = setInterval(() => fetchAllData(), 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchAllData]);

  const handleRefresh = () => {
    fetchAllData(true);
  };

  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 text-purple-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading learning intelligence...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="learning-intelligence-hub">
      {/* Header with Trader Profile */}
      <TraderProfileHeader 
        profile={data.profile} 
        onRefresh={handleRefresh}
        refreshing={refreshing}
      />

      {/* Main Three-Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left Column - Metrics */}
        <div className="space-y-4">
          <PerformanceMetricsCard metrics={data.metrics} />
          <WeeklyCalendarCard stats={data.weeklyStats} />
        </div>

        {/* Center Column - Edge Health */}
        <EdgeHealthCard 
          alerts={data.edgeHealth} 
          metrics={data.metrics}
        />

        {/* Right Column - Recommendations */}
        <RecommendationsCard 
          recommendations={data.recommendations}
          calibration={data.calibration}
        />
      </div>

      {/* Bottom Row - Collapsible Sections */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CollapsibleSection
          title="Backtest Results"
          icon={TestTubes}
          expanded={expandedSections.backtest}
          onToggle={() => toggleSection('backtest')}
        >
          <BacktestSummary />
        </CollapsibleSection>

        <CollapsibleSection
          title="Shadow Mode"
          icon={Layers}
          expanded={expandedSections.shadow}
          onToggle={() => toggleSection('shadow')}
        >
          <ShadowModeSummary />
        </CollapsibleSection>
      </div>
    </div>
  );
};

// ============================================================================
// Sub-Components
// ============================================================================

const TraderProfileHeader = ({ profile, onRefresh, refreshing }) => {
  // Default values if no profile
  const defaultProfile = {
    total_trades: 0,
    best_time: 'N/A',
    best_setup: 'N/A',
    best_regime: 'N/A',
    avg_hold_time: 'N/A',
    trading_since: null
  };

  const p = profile || defaultProfile;
  const tradingDays = p.trading_since 
    ? Math.floor((Date.now() - new Date(p.trading_since).getTime()) / (1000 * 60 * 60 * 24))
    : 0;

  return (
    <div className="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-xl border border-purple-500/20 p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-full bg-purple-500/20 flex items-center justify-center">
            <Brain className="w-7 h-7 text-purple-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Trader Profile</h2>
            <p className="text-slate-400 text-sm">
              {p.total_trades > 0 
                ? `Based on ${p.total_trades} trades${tradingDays > 0 ? ` over ${tradingDays} days` : ''}`
                : 'Start trading to build your profile'
              }
            </p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <ProfileStat label="Best Time" value={p.best_time || 'N/A'} />
          <ProfileStat label="Best Setup" value={p.best_setup || 'N/A'} />
          <ProfileStat label="Best Regime" value={p.best_regime || 'N/A'} />
          <ProfileStat label="Avg Hold" value={p.avg_hold_time || 'N/A'} />
          
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors"
            data-testid="hub-refresh-btn"
          >
            <RefreshCw className={`w-5 h-5 text-slate-400 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
    </div>
  );
};

const ProfileStat = ({ label, value }) => (
  <div className="text-center">
    <div className="text-xs text-slate-500">{label}</div>
    <div className="text-sm font-medium text-white">{value}</div>
  </div>
);

const PerformanceMetricsCard = ({ metrics }) => {
  const m = metrics || {};
  
  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
        <Activity className="w-4 h-4 text-purple-400" />
        Performance Metrics
      </h3>
      <div className="space-y-3">
        <MetricRow 
          label="Win Rate" 
          value={m.win_rate ? `${(m.win_rate * 100).toFixed(1)}%` : '--'} 
          badge={m.win_rate_change ? `${m.win_rate_change > 0 ? '+' : ''}${(m.win_rate_change * 100).toFixed(1)}%` : null}
          positive={m.win_rate_change > 0}
        />
        <MetricRow 
          label="Profit Factor" 
          value={m.profit_factor?.toFixed(2) || '--'} 
          badge={m.profit_factor >= 2 ? 'Good' : m.profit_factor >= 1.5 ? 'OK' : 'Low'}
          positive={m.profit_factor >= 2}
          neutral={m.profit_factor >= 1.5 && m.profit_factor < 2}
        />
        <MetricRow 
          label="Avg Winner" 
          value={m.avg_winner ? `$${m.avg_winner.toFixed(0)}` : '--'} 
          badge={m.avg_winner_change ? `${m.avg_winner_change > 0 ? '+' : ''}$${m.avg_winner_change.toFixed(0)}` : null}
          positive={m.avg_winner_change > 0}
        />
        <MetricRow 
          label="Avg Loser" 
          value={m.avg_loser ? `$${Math.abs(m.avg_loser).toFixed(0)}` : '--'} 
          badge={m.avg_loser_change ? `${m.avg_loser_change < 0 ? '' : '+'}$${m.avg_loser_change.toFixed(0)}` : null}
          positive={m.avg_loser_change < 0}
        />
        <MetricRow 
          label="Expectancy" 
          value={m.expectancy ? `$${m.expectancy.toFixed(0)}/trade` : '--'} 
          badge={m.expectancy_change ? `${m.expectancy_change > 0 ? '+' : ''}$${m.expectancy_change.toFixed(0)}` : null}
          positive={m.expectancy_change > 0}
        />
      </div>
    </div>
  );
};

const MetricRow = ({ label, value, badge, positive, negative, neutral }) => (
  <div className="flex items-center justify-between">
    <span className="text-sm text-slate-400">{label}</span>
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-white">{value}</span>
      {badge && (
        <span className={`text-xs px-1.5 py-0.5 rounded ${
          positive ? 'bg-emerald-500/20 text-emerald-400' :
          negative ? 'bg-red-500/20 text-red-400' : 
          neutral ? 'bg-yellow-500/20 text-yellow-400' :
          'bg-slate-600/50 text-slate-400'
        }`}>
          {badge}
        </span>
      )}
    </div>
  </div>
);

const WeeklyCalendarCard = ({ stats }) => {
  const days = ['M', 'T', 'W', 'T', 'F'];
  
  // Use provided stats or create empty array
  const weekData = stats?.length > 0 ? stats : Array(5).fill(null);

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
        <Calendar className="w-4 h-4 text-blue-400" />
        This Week
      </h3>
      <div className="grid grid-cols-5 gap-2">
        {days.map((day, i) => {
          const dayData = weekData[i];
          const pnl = dayData?.pnl || 0;
          const hasData = dayData !== null && dayData !== undefined;
          
          return (
            <div key={`${day}-${i}`} className="text-center">
              <div className="text-xs text-slate-500 mb-1">{day}</div>
              <div className={`py-2 px-1 rounded-lg text-xs font-medium ${
                !hasData ? 'bg-slate-700/30 text-slate-600' :
                pnl > 0 ? 'bg-emerald-500/20 text-emerald-400' :
                pnl < 0 ? 'bg-red-500/20 text-red-400' :
                'bg-slate-700/50 text-slate-400'
              }`}>
                {hasData ? (pnl >= 0 ? '+' : '') + '$' + Math.abs(pnl).toFixed(0) : '--'}
              </div>
            </div>
          );
        })}
      </div>
      
      {/* Week Total */}
      <div className="mt-3 pt-3 border-t border-slate-700/50 flex justify-between items-center">
        <span className="text-xs text-slate-500">Week Total</span>
        <span className={`text-sm font-semibold ${
          (stats?.reduce((sum, d) => sum + (d?.pnl || 0), 0) || 0) >= 0 
            ? 'text-emerald-400' : 'text-red-400'
        }`}>
          {stats?.length > 0 
            ? `${stats.reduce((sum, d) => sum + (d?.pnl || 0), 0) >= 0 ? '+' : ''}$${Math.abs(stats.reduce((sum, d) => sum + (d?.pnl || 0), 0)).toFixed(0)}`
            : '--'
          }
        </span>
      </div>
    </div>
  );
};

const EdgeHealthCard = ({ alerts, metrics }) => {
  // Combine edge alerts with strategy stats
  const strategies = metrics?.strategies || [];
  
  // Map alerts to strategies for status
  const getEdgeStatus = (strategyName) => {
    const alert = alerts?.find(a => 
      a.setup_type?.toLowerCase() === strategyName?.toLowerCase() ||
      a.strategy?.toLowerCase() === strategyName?.toLowerCase()
    );
    
    if (!alert) return 'healthy';
    if (alert.severity === 'critical' || alert.decay_percentage > 20) return 'critical';
    if (alert.severity === 'warning' || alert.decay_percentage > 10) return 'warning';
    return 'healthy';
  };

  const hasDecay = (strategyName) => {
    const alert = alerts?.find(a => 
      a.setup_type?.toLowerCase() === strategyName?.toLowerCase() ||
      a.strategy?.toLowerCase() === strategyName?.toLowerCase()
    );
    return alert?.decay_percentage > 0;
  };

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
        <Shield className="w-4 h-4 text-cyan-400" />
        Edge Health Monitor
      </h3>
      
      {strategies.length > 0 ? (
        <div className="space-y-2">
          {strategies.slice(0, 6).map((strategy, i) => (
            <EdgeRow
              key={strategy.name || i}
              setup={strategy.name || strategy.setup_type || 'Unknown'}
              status={getEdgeStatus(strategy.name || strategy.setup_type)}
              winRate={`${((strategy.win_rate || 0) * 100).toFixed(0)}%`}
              trades={strategy.total_trades || 0}
              decay={hasDecay(strategy.name || strategy.setup_type)}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-slate-500">
          <Shield className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No strategy data yet</p>
          <p className="text-xs mt-1">Complete more trades to see edge health</p>
        </div>
      )}

      {strategies.length > 6 && (
        <button className="w-full mt-3 py-2 text-xs text-purple-400 hover:text-purple-300 border border-purple-500/30 rounded-lg hover:bg-purple-500/10 transition-colors">
          View All Setups ({strategies.length}) →
        </button>
      )}
    </div>
  );
};

const EdgeRow = ({ setup, status, winRate, trades, decay }) => (
  <div className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-700/30 transition-colors">
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${
        status === 'healthy' ? 'bg-emerald-400' :
        status === 'warning' ? 'bg-yellow-400' : 'bg-red-400'
      }`} />
      <span className="text-sm text-slate-300">{setup}</span>
      {decay && <TrendingDown className="w-3 h-3 text-red-400" />}
    </div>
    <div className="flex items-center gap-4 text-xs">
      <span className="text-slate-500">{trades} trades</span>
      <span className={`font-medium min-w-[40px] text-right ${
        parseInt(winRate) >= 60 ? 'text-emerald-400' :
        parseInt(winRate) >= 50 ? 'text-yellow-400' : 'text-red-400'
      }`}>{winRate}</span>
    </div>
  </div>
);

const RecommendationsCard = ({ recommendations, calibration }) => {
  const allRecs = [...(recommendations || [])];
  
  // Add calibration as recommendation if present
  if (calibration?.pending_change) {
    allRecs.unshift({
      id: 'calibration',
      type: 'calibrate',
      text: calibration.recommendation || `TQS threshold adjustment: ${calibration.current} → ${calibration.recommended}`,
      action: 'Apply change'
    });
  }

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
        <Lightbulb className="w-4 h-4 text-yellow-400" />
        AI Recommendations
      </h3>
      
      {allRecs.length > 0 ? (
        <div className="space-y-3">
          {allRecs.slice(0, 4).map((rec, i) => (
            <RecommendationItem
              key={rec.id || i}
              type={rec.type || 'optimize'}
              text={rec.text || rec.message || rec.recommendation}
              action={rec.action || 'View'}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-slate-500">
          <Lightbulb className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No recommendations yet</p>
          <p className="text-xs mt-1">Keep trading to receive AI insights</p>
        </div>
      )}
    </div>
  );
};

const RecommendationItem = ({ type, text, action }) => {
  const icons = {
    optimize: <Zap className="w-4 h-4 text-blue-400 flex-shrink-0" />,
    warning: <AlertTriangle className="w-4 h-4 text-yellow-400 flex-shrink-0" />,
    opportunity: <Target className="w-4 h-4 text-emerald-400 flex-shrink-0" />,
    calibrate: <Settings className="w-4 h-4 text-purple-400 flex-shrink-0" />,
    success: <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />,
    danger: <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
  };

  return (
    <div className="flex items-start gap-2 p-2 bg-slate-900/30 rounded-lg">
      {icons[type] || icons.optimize}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-300 leading-relaxed">{text}</p>
        <button className="text-xs text-purple-400 hover:text-purple-300 mt-1 transition-colors">
          {action} →
        </button>
      </div>
    </div>
  );
};

const CollapsibleSection = ({ title, icon: Icon, expanded, onToggle, children }) => (
  <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">
    <button
      onClick={onToggle}
      className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-700/20 transition-colors"
      data-testid={`collapse-${title.toLowerCase().replace(/\s/g, '-')}`}
    >
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-medium text-slate-300">{title}</span>
      </div>
      {expanded 
        ? <ChevronDown className="w-4 h-4 text-slate-400" /> 
        : <ChevronRight className="w-4 h-4 text-slate-400" />
      }
    </button>
    {expanded && (
      <div className="px-4 pb-4 border-t border-slate-700/30">
        {children}
      </div>
    )}
  </div>
);

const BacktestSummary = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchBacktest = async () => {
      try {
        const res = await api.get('/api/slow-learning/backtest/results?limit=1');
        if (res.data?.success && res.data.results?.length > 0) {
          setData(res.data.results[0]);
        }
      } catch (err) {
        console.error('Error fetching backtest:', err);
      }
      setLoading(false);
    };
    fetchBacktest();
  }, []);

  if (loading) {
    return <div className="py-4 text-center text-slate-500 text-sm">Loading...</div>;
  }

  if (!data) {
    return (
      <div className="py-4 text-center text-slate-500">
        <p className="text-sm">No backtest results yet</p>
        <button className="mt-2 text-xs text-purple-400 hover:text-purple-300">
          Run a backtest →
        </button>
      </div>
    );
  }

  return (
    <div className="pt-3 space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Last Backtest</span>
        <span className={`font-medium ${data.total_return >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {data.total_return >= 0 ? '+' : ''}{(data.total_return * 100).toFixed(1)}%
        </span>
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Period</span>
        <span className="text-slate-300">{data.period || '3 months'}</span>
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Trades</span>
        <span className="text-slate-300">{data.total_trades || 0}</span>
      </div>
      <button className="w-full mt-2 py-1.5 text-xs text-purple-400 hover:text-purple-300 border border-purple-500/30 rounded hover:bg-purple-500/10 transition-colors">
        View Full Results →
      </button>
    </div>
  );
};

const ShadowModeSummary = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchShadow = async () => {
      try {
        const res = await api.get('/api/slow-learning/shadow/status');
        if (res.data?.success) {
          setData(res.data);
        }
      } catch (err) {
        console.error('Error fetching shadow mode:', err);
      }
      setLoading(false);
    };
    fetchShadow();
  }, []);

  if (loading) {
    return <div className="py-4 text-center text-slate-500 text-sm">Loading...</div>;
  }

  if (!data) {
    return (
      <div className="py-4 text-center text-slate-500">
        <p className="text-sm">Shadow mode not configured</p>
        <button className="mt-2 text-xs text-purple-400 hover:text-purple-300">
          Set up shadow mode →
        </button>
      </div>
    );
  }

  return (
    <div className="pt-3 space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Active Filters</span>
        <span className="text-slate-300">{data.active_filters || 0}</span>
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Pending Validation</span>
        <span className="text-yellow-400">{data.pending_validation || 0}</span>
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Shadow Trades</span>
        <span className="text-slate-300">{data.shadow_trades || 0}</span>
      </div>
      <button className="w-full mt-2 py-1.5 text-xs text-purple-400 hover:text-purple-300 border border-purple-500/30 rounded hover:bg-purple-500/10 transition-colors">
        Manage Filters →
      </button>
    </div>
  );
};

export default LearningIntelligenceHub;
