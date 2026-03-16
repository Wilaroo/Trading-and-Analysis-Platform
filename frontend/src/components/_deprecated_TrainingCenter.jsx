/**
 * TrainingCenter.jsx - Unified AI Training & Learning Hub
 * 
 * A comprehensive section for making the entire SentCom system smarter:
 * 1. Historical Simulations - Run backtests, view results
 * 2. Time-Series Model - Training status, accuracy, retraining
 * 3. Prediction Tracking - Track forecast accuracy over time
 * 4. Learning Analytics - System learning insights & improvements
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, Zap, Target, TrendingUp, Activity, BarChart3,
  Play, Pause, RefreshCw, Loader, ChevronRight, Calendar,
  Clock, CheckCircle, XCircle, AlertCircle, Settings,
  Database, Cpu, LineChart, ArrowUpRight, ArrowDownRight,
  Sparkles, BookOpen, History, FlaskConical, Layers,
  Link2, Unlink, GitBranch, ArrowRight, HardDrive, 
  Download, StopCircle, BarChart2, Info
} from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

const GlassCard = ({ children, className = '', gradient = false, glow = false }) => (
  <div className={`
    relative overflow-hidden rounded-2xl
    bg-gradient-to-br from-white/[0.08] to-white/[0.02]
    border border-white/10
    backdrop-blur-xl
    ${glow ? 'shadow-lg shadow-cyan-500/10' : ''}
    ${className}
  `}>
    {gradient && (
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-violet-500/5 pointer-events-none" />
    )}
    <div className="relative">{children}</div>
  </div>
);

const StatCard = ({ label, value, subValue, icon: Icon, color = 'cyan', trend = null }) => (
  <div className="p-4 rounded-xl bg-black/30 border border-white/5">
    <div className="flex items-center justify-between mb-2">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}</span>
      {Icon && <Icon className={`w-4 h-4 text-${color}-400`} />}
    </div>
    <div className="flex items-end gap-2">
      <span className={`text-2xl font-bold text-${color}-400`}>{value}</span>
      {trend !== null && (
        <span className={`text-xs ${trend >= 0 ? 'text-emerald-400' : 'text-rose-400'} flex items-center`}>
          {trend >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
          {Math.abs(trend).toFixed(1)}%
        </span>
      )}
    </div>
    {subValue && <p className="text-xs text-zinc-500 mt-1">{subValue}</p>}
  </div>
);

const StatusBadge = ({ status }) => {
  const statusConfig = {
    completed: { color: 'emerald', icon: CheckCircle, label: 'Completed' },
    running: { color: 'cyan', icon: Loader, label: 'Running', animate: true },
    pending: { color: 'amber', icon: Clock, label: 'Pending' },
    failed: { color: 'rose', icon: XCircle, label: 'Failed' },
    cancelled: { color: 'zinc', icon: XCircle, label: 'Cancelled' }
  };
  
  const config = statusConfig[status] || statusConfig.pending;
  const Icon = config.icon;
  
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-${config.color}-500/20 text-${config.color}-400 border border-${config.color}-500/30`}>
      <Icon className={`w-3 h-3 ${config.animate ? 'animate-spin' : ''}`} />
      {config.label}
    </span>
  );
};

// ============================================================================
// HOOKS
// ============================================================================

const useSimulationJobs = () => {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/simulation/jobs?limit=10`);
      const data = await res.json();
      if (data.success) {
        setJobs(data.jobs || []);
      }
    } catch (err) {
      console.error('Error fetching simulation jobs:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 10000); // Poll every 10s for running jobs
    return () => clearInterval(interval);
  }, [fetchJobs]);

  return { jobs, loading, refresh: fetchJobs };
};

const useTimeseriesStatus = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/timeseries/status`);
      const data = await res.json();
      if (data.success) {
        setStatus(data.status);
      }
    } catch (err) {
      console.error('Error fetching timeseries status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return { status, loading, refresh: fetchStatus };
};

const usePredictionAccuracy = () => {
  const [accuracy, setAccuracy] = useState(null);
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [accuracyRes, predictionsRes] = await Promise.all([
        fetch(`${API_BASE}/api/ai-modules/timeseries/prediction-accuracy?days=30`),
        fetch(`${API_BASE}/api/ai-modules/timeseries/predictions?limit=20`)
      ]);
      
      const [accuracyData, predictionsData] = await Promise.all([
        accuracyRes.json(),
        predictionsRes.json()
      ]);
      
      if (accuracyData.success) setAccuracy(accuracyData.accuracy);
      if (predictionsData.success) setPredictions(predictionsData.predictions || []);
    } catch (err) {
      console.error('Error fetching prediction data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { accuracy, predictions, loading, refresh: fetchData };
};

// Hook for Learning Connections
const useLearningConnections = () => {
  const [connections, setConnections] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [weights, setWeights] = useState({});
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [connRes, metricsRes, weightsRes] = await Promise.all([
        fetch(`${API_BASE}/api/learning-connectors/connections`),
        fetch(`${API_BASE}/api/learning-connectors/metrics`),
        fetch(`${API_BASE}/api/learning-connectors/weights`)
      ]);
      
      const [connData, metricsData, weightsData] = await Promise.all([
        connRes.json(),
        metricsRes.json(),
        weightsRes.json()
      ]);
      
      if (connData.success) setConnections(connData.connections || []);
      if (metricsData.success) setMetrics(metricsData.metrics);
      if (weightsData.success) setWeights(weightsData.weights || {});
    } catch (err) {
      console.error('Error fetching learning connections:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { connections, metrics, weights, loading, refresh: fetchData };
};

// Hook for IB Data Collection
const useIBCollection = () => {
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [queueProgress, setQueueProgress] = useState(null);
  const [defaultSymbolCount, setDefaultSymbolCount] = useState(51);
  const [fullMarketCount, setFullMarketCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, statsRes, symbolsRes, marketRes] = await Promise.all([
        fetch(`${API_BASE}/api/ib-collector/status`),
        fetch(`${API_BASE}/api/ib-collector/stats`),
        fetch(`${API_BASE}/api/ib-collector/default-symbols`),
        fetch(`${API_BASE}/api/ib-collector/full-market-symbols`)
      ]);
      
      const [statusData, statsData, symbolsData, marketData] = await Promise.all([
        statusRes.json(),
        statsRes.json(),
        symbolsRes.json(),
        marketRes.json()
      ]);
      
      if (statusData.success) {
        setStatus(statusData.job);
        
        // If there's an active job, fetch queue progress for real-time updates
        // Use overall queue stats (no job_id filter) to capture all pending work
        if (statusData.job?.status === 'running') {
          try {
            const queueRes = await fetch(`${API_BASE}/api/ib-collector/queue-progress`);
            const queueData = await queueRes.json();
            if (queueData.success) {
              setQueueProgress(queueData);
            }
          } catch (err) {
            console.error('Error fetching queue progress:', err);
          }
        } else {
          setQueueProgress(null);
        }
      }
      if (statsData.success) setStats(statsData.stats);
      if (symbolsData.success) setDefaultSymbolCount(symbolsData.count);
      if (marketData.success) setFullMarketCount(marketData.count);
    } catch (err) {
      console.error('Error fetching IB collection data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Poll every 3 seconds for more responsive progress updates
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return { status, stats, queueProgress, defaultSymbolCount, fullMarketCount, loading, refresh: fetchData };
};

// Hook for Data Storage Stats
const useDataStorage = () => {
  const [stats, setStats] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, summaryRes] = await Promise.all([
        fetch(`${API_BASE}/api/data-storage/stats`),
        fetch(`${API_BASE}/api/data-storage/learning-summary`)
      ]);
      
      const [statsData, summaryData] = await Promise.all([
        statsRes.json(),
        summaryRes.json()
      ]);
      
      if (statsData.success) setStats(statsData);
      if (summaryData.success) setSummary(summaryData);
    } catch (err) {
      console.error('Error fetching data storage stats:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { stats, summary, loading, refresh: fetchData };
};

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

// Historical Simulation Panel
const SimulationPanel = ({ jobs, loading, onRefresh, onStartSimulation }) => {
  const [showConfig, setShowConfig] = useState(false);
  const [config, setConfig] = useState({
    start_date: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    end_date: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    universe: 'custom',
    custom_symbols: 'AAPL,NVDA,MSFT,TSLA,GOOGL,AMD,META,AMZN',
    starting_capital: 100000,
    use_ai_agents: true
  });
  const [starting, setStarting] = useState(false);

  const handleStart = async () => {
    setStarting(true);
    try {
      const res = await fetch(`${API_BASE}/api/simulation/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...config,
          custom_symbols: config.custom_symbols.split(',').map(s => s.trim().toUpperCase())
        })
      });
      const data = await res.json();
      if (data.success) {
        toast.success(`Simulation started: ${data.job_id}`);
        setShowConfig(false);
        onRefresh();
      } else {
        toast.error('Failed to start simulation: ' + (data.detail || 'Unknown error'));
      }
    } catch (err) {
      toast.error('Error starting simulation');
    } finally {
      setStarting(false);
    }
  };

  const handleQuickTest = async () => {
    setStarting(true);
    try {
      const res = await fetch(`${API_BASE}/api/simulation/quick-test`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.success) {
        toast.success(`Quick test started: ${data.job_id}`);
        onRefresh();
      } else {
        toast.error('Failed to start quick test');
      }
    } catch (err) {
      toast.error('Error starting quick test');
    } finally {
      setStarting(false);
    }
  };

  // Calculate summary stats from jobs
  const completedJobs = jobs.filter(j => j.status === 'completed');
  const totalTrades = completedJobs.reduce((sum, j) => sum + (j.total_trades || 0), 0);
  const avgWinRate = completedJobs.length > 0 
    ? completedJobs.reduce((sum, j) => sum + (j.win_rate || 0), 0) / completedJobs.length 
    : 0;

  return (
    <GlassCard className="p-5" gradient>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/20 flex items-center justify-center">
            <History className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Historical Simulations</h3>
            <p className="text-[10px] text-zinc-500">Backtest trading strategies on historical data</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleQuickTest}
            disabled={starting}
            className="px-3 py-1.5 rounded-lg bg-violet-500/20 border border-violet-500/30 text-violet-400 text-xs font-medium hover:bg-violet-500/30 transition-all disabled:opacity-50 flex items-center gap-1.5"
            data-testid="quick-test-btn"
          >
            {starting ? <Loader className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            Quick Test
          </button>
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="px-3 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs font-medium hover:bg-cyan-500/30 transition-all flex items-center gap-1.5"
            data-testid="new-simulation-btn"
          >
            <Play className="w-3 h-3" />
            New Simulation
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <StatCard label="Total Jobs" value={jobs.length} icon={Database} color="violet" />
        <StatCard label="Completed" value={completedJobs.length} icon={CheckCircle} color="emerald" />
        <StatCard label="Total Trades" value={totalTrades} icon={Activity} color="cyan" />
        <StatCard label="Avg Win Rate" value={`${avgWinRate.toFixed(1)}%`} icon={Target} color="amber" />
      </div>

      {/* Config Panel */}
      <AnimatePresence>
        {showConfig && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-4 p-4 rounded-xl bg-black/40 border border-white/10"
          >
            <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
              <Settings className="w-4 h-4 text-cyan-400" />
              Simulation Configuration
            </h4>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-zinc-500 uppercase">Start Date</label>
                <input
                  type="date"
                  value={config.start_date}
                  onChange={(e) => setConfig({ ...config, start_date: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-800/50 border border-white/10 text-white text-sm"
                  data-testid="sim-start-date"
                />
              </div>
              <div>
                <label className="text-[10px] text-zinc-500 uppercase">End Date</label>
                <input
                  type="date"
                  value={config.end_date}
                  onChange={(e) => setConfig({ ...config, end_date: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-800/50 border border-white/10 text-white text-sm"
                  data-testid="sim-end-date"
                />
              </div>
              <div className="col-span-2">
                <label className="text-[10px] text-zinc-500 uppercase">Symbols (comma-separated)</label>
                <input
                  type="text"
                  value={config.custom_symbols}
                  onChange={(e) => setConfig({ ...config, custom_symbols: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-800/50 border border-white/10 text-white text-sm"
                  placeholder="AAPL, NVDA, MSFT..."
                  data-testid="sim-symbols"
                />
              </div>
              <div>
                <label className="text-[10px] text-zinc-500 uppercase">Starting Capital</label>
                <input
                  type="number"
                  value={config.starting_capital}
                  onChange={(e) => setConfig({ ...config, starting_capital: parseFloat(e.target.value) })}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-800/50 border border-white/10 text-white text-sm"
                  data-testid="sim-capital"
                />
              </div>
              <div className="flex items-center gap-3">
                <label className="text-xs text-zinc-400">Use AI Agents</label>
                <button
                  onClick={() => setConfig({ ...config, use_ai_agents: !config.use_ai_agents })}
                  className={`w-10 h-5 rounded-full transition-all ${config.use_ai_agents ? 'bg-cyan-500' : 'bg-zinc-700'}`}
                  data-testid="sim-ai-toggle"
                >
                  <div className={`w-4 h-4 rounded-full bg-white transition-all ${config.use_ai_agents ? 'ml-5' : 'ml-0.5'}`} />
                </button>
              </div>
            </div>
            <button
              onClick={handleStart}
              disabled={starting}
              className="mt-4 w-full px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center justify-center gap-2"
              data-testid="start-simulation-btn"
            >
              {starting ? <Loader className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Start Simulation
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Jobs List */}
      <div className="space-y-2 max-h-[300px] overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader className="w-6 h-6 text-violet-400 animate-spin" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-8">
            <History className="w-10 h-10 text-zinc-600 mx-auto mb-2" />
            <p className="text-zinc-500 text-sm">No simulations yet</p>
            <p className="text-zinc-600 text-xs mt-1">Start a quick test to see results</p>
          </div>
        ) : (
          jobs.map((job) => (
            <SimulationJobRow key={job.id} job={job} />
          ))
        )}
      </div>
    </GlassCard>
  );
};

const SimulationJobRow = ({ job }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl bg-black/30 border border-white/5 overflow-hidden" data-testid={`job-${job.id}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-3 flex items-center justify-between hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <StatusBadge status={job.status} />
          <div className="text-left">
            <p className="text-sm font-medium text-white">{job.id}</p>
            <p className="text-[10px] text-zinc-500">
              {job.config?.start_date} → {job.config?.end_date}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className={`text-sm font-bold ${job.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {job.total_pnl >= 0 ? '+' : ''}${job.total_pnl?.toFixed(2) || '0.00'}
            </p>
            <p className="text-[10px] text-zinc-500">{job.total_trades || 0} trades</p>
          </div>
          <ChevronRight className={`w-4 h-4 text-zinc-500 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </button>
      
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-white/5"
          >
            <div className="p-4 grid grid-cols-4 gap-3">
              <div className="text-center">
                <p className="text-lg font-bold text-emerald-400">{job.winning_trades || 0}</p>
                <p className="text-[9px] text-zinc-500">Wins</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-rose-400">{job.losing_trades || 0}</p>
                <p className="text-[9px] text-zinc-500">Losses</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-cyan-400">{job.win_rate?.toFixed(1) || 0}%</p>
                <p className="text-[9px] text-zinc-500">Win Rate</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-amber-400">{job.profit_factor?.toFixed(2) || 0}</p>
                <p className="text-[9px] text-zinc-500">Profit Factor</p>
              </div>
            </div>
            {job.config?.custom_symbols && (
              <div className="px-4 pb-4">
                <p className="text-[10px] text-zinc-500 mb-1">Symbols:</p>
                <div className="flex flex-wrap gap-1">
                  {(job.config.custom_symbols || []).map((s, i) => (
                    <span key={i} className="px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 text-[10px]">
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// Time-Series Model Panel
const TimeSeriesPanel = ({ status, loading, onRefresh }) => {
  const [training, setTraining] = useState(false);

  const handleTrain = async () => {
    setTraining(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/timeseries/train`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.success) {
        toast.success('Model training started');
        setTimeout(onRefresh, 2000);
      } else {
        toast.error('Training failed: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      toast.error('Error starting training');
    } finally {
      setTraining(false);
    }
  };

  const model = status?.model || {};
  const metrics = model.metrics || {};

  return (
    <GlassCard className="p-5" gradient>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 flex items-center justify-center">
            <Cpu className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Time-Series AI Model</h3>
            <p className="text-[10px] text-zinc-500">LightGBM price direction forecasting</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
            model.trained 
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
          }`}>
            {model.trained ? 'TRAINED' : 'UNTRAINED'}
          </span>
          <button
            onClick={handleTrain}
            disabled={training}
            className="px-3 py-1.5 rounded-lg bg-amber-500/20 border border-amber-500/30 text-amber-400 text-xs font-medium hover:bg-amber-500/30 transition-all disabled:opacity-50 flex items-center gap-1.5"
            data-testid="train-model-btn"
          >
            {training ? <Loader className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            Retrain
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-amber-400 animate-spin" />
        </div>
      ) : (
        <>
          {/* Model Stats */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <StatCard 
              label="Version" 
              value={model.version || 'N/A'} 
              icon={Layers} 
              color="amber" 
            />
            <StatCard 
              label="Accuracy" 
              value={`${((metrics.accuracy || 0) * 100).toFixed(1)}%`} 
              icon={Target} 
              color="cyan" 
            />
            <StatCard 
              label="Features" 
              value={model.feature_count || 0} 
              icon={Database} 
              color="violet" 
            />
            <StatCard 
              label="Training Samples" 
              value={metrics.training_samples?.toLocaleString() || '0'} 
              icon={BarChart3} 
              color="emerald" 
            />
          </div>

          {/* Precision/Recall Stats */}
          {metrics.precision_up !== undefined && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5 mb-4">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Model Performance (UP Predictions)</h4>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p className="text-lg font-bold text-emerald-400">{((metrics.precision_up || 0) * 100).toFixed(1)}%</p>
                  <p className="text-[9px] text-zinc-500">Precision</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-cyan-400">{((metrics.recall_up || 0) * 100).toFixed(1)}%</p>
                  <p className="text-[9px] text-zinc-500">Recall</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-amber-400">{((metrics.f1_up || 0) * 100).toFixed(1)}%</p>
                  <p className="text-[9px] text-zinc-500">F1 Score</p>
                </div>
              </div>
            </div>
          )}

          {/* Top Features */}
          {metrics.top_features && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Top Predictive Features</h4>
              <div className="flex flex-wrap gap-1.5">
                {metrics.top_features.slice(0, 8).map((f, i) => (
                  <span key={i} className="px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px]">
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </GlassCard>
  );
};

// Prediction Tracking Panel
const PredictionTrackingPanel = ({ accuracy, predictions, loading, onRefresh }) => {
  const [verifying, setVerifying] = useState(false);

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/timeseries/verify-predictions`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.success) {
        toast.success(`Verified ${data.result?.verified || 0} predictions`);
        onRefresh();
      }
    } catch (err) {
      toast.error('Verification failed');
    } finally {
      setVerifying(false);
    }
  };

  return (
    <GlassCard className="p-5" gradient>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/20 flex items-center justify-center">
            <Target className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Prediction Tracking</h3>
            <p className="text-[10px] text-zinc-500">Track forecast accuracy over time</p>
          </div>
        </div>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="px-3 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs font-medium hover:bg-cyan-500/30 transition-all disabled:opacity-50 flex items-center gap-1.5"
          data-testid="verify-btn"
        >
          {verifying ? <Loader className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
          Verify Outcomes
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      ) : (
        <>
          {/* Accuracy Summary */}
          {accuracy && (
            <div className="grid grid-cols-4 gap-3 mb-4">
              <StatCard 
                label="Total Predictions" 
                value={accuracy.total_predictions || 0} 
                icon={Activity} 
                color="cyan" 
              />
              <StatCard 
                label="Correct" 
                value={accuracy.correct_predictions || 0} 
                icon={CheckCircle} 
                color="emerald" 
              />
              <StatCard 
                label="Accuracy" 
                value={`${((accuracy.accuracy || 0) * 100).toFixed(1)}%`} 
                icon={Target} 
                color="amber" 
              />
              <StatCard 
                label="Avg Return (Correct)" 
                value={`${((accuracy.avg_return_when_correct || 0) * 100).toFixed(2)}%`} 
                icon={TrendingUp} 
                color="violet" 
              />
            </div>
          )}

          {/* Accuracy by Direction */}
          {accuracy?.by_direction && Object.keys(accuracy.by_direction).length > 0 && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5 mb-4">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Accuracy by Direction</h4>
              <div className="flex gap-3">
                {Object.entries(accuracy.by_direction).map(([dir, stats]) => (
                  <div key={dir} className="flex-1 p-2 rounded-lg bg-black/30 text-center">
                    <span className={`text-xs font-bold ${
                      dir === 'up' ? 'text-emerald-400' : dir === 'down' ? 'text-rose-400' : 'text-zinc-400'
                    }`}>
                      {dir.toUpperCase()}
                    </span>
                    <p className="text-lg font-bold text-white mt-1">{((stats.accuracy || 0) * 100).toFixed(0)}%</p>
                    <p className="text-[8px] text-zinc-500">{stats.correct}/{stats.total}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recent Predictions */}
          <div>
            <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Recent Predictions</h4>
            <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
              {predictions.length === 0 ? (
                <p className="text-center text-zinc-500 text-xs py-4">No predictions yet</p>
              ) : (
                predictions.slice(0, 10).map((pred, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-black/30" data-testid={`prediction-${i}`}>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-white">{pred.symbol}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        pred.prediction?.direction === 'up' ? 'bg-emerald-500/20 text-emerald-400'
                        : pred.prediction?.direction === 'down' ? 'bg-rose-500/20 text-rose-400'
                        : 'bg-zinc-500/20 text-zinc-400'
                      }`}>
                        {pred.prediction?.direction?.toUpperCase() || 'FLAT'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {pred.outcome_verified ? (
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          pred.prediction_correct ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                        }`}>
                          {pred.prediction_correct ? 'CORRECT' : 'WRONG'}
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400">
                          PENDING
                        </span>
                      )}
                      <span className="text-[10px] text-zinc-500">
                        {new Date(pred.timestamp).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </GlassCard>
  );
};

// Learning Insights Panel
const LearningInsightsPanel = () => {
  const [insights, setInsights] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchInsights = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sentcom/learning/insights`);
        const data = await res.json();
        if (data.success) {
          setInsights(data);
        }
      } catch (err) {
        console.error('Error fetching learning insights:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchInsights();
  }, []);

  return (
    <GlassCard className="p-5" gradient>
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-emerald-400" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-white">Learning Insights</h3>
          <p className="text-[10px] text-zinc-500">System learning progress & patterns</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-emerald-400 animate-spin" />
        </div>
      ) : insights ? (
        <div className="space-y-4">
          {/* Trader Profile */}
          {insights.trader_profile && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Trader Profile</h4>
              {insights.trader_profile.strengths?.length > 0 && (
                <div className="mb-2">
                  <p className="text-[10px] text-emerald-400 mb-1">Strengths:</p>
                  <div className="flex flex-wrap gap-1">
                    {insights.trader_profile.strengths.map((s, i) => (
                      <span key={i} className="px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px]">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {insights.trader_profile.weaknesses?.length > 0 && (
                <div>
                  <p className="text-[10px] text-rose-400 mb-1">Areas to Improve:</p>
                  <div className="flex flex-wrap gap-1">
                    {insights.trader_profile.weaknesses.map((w, i) => (
                      <span key={i} className="px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[10px]">
                        {w}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Recommendations */}
          {insights.recommendations?.length > 0 && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">AI Recommendations</h4>
              <ul className="space-y-1.5">
                {insights.recommendations.slice(0, 3).map((rec, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                    <ChevronRight className="w-3 h-3 text-cyan-400 mt-0.5 flex-shrink-0" />
                    {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center py-8">
          <Sparkles className="w-10 h-10 text-zinc-600 mx-auto mb-2" />
          <p className="text-zinc-500 text-sm">No learning insights yet</p>
          <p className="text-zinc-600 text-xs mt-1">Trade more to generate insights</p>
        </div>
      )}
    </GlassCard>
  );
};

// Learning Connections Panel - Shows data flow status
const LearningConnectionsPanel = ({ connections, metrics, weights, loading, onRefresh, onSync }) => {
  const [syncing, setSyncing] = useState(false);
  const [syncType, setSyncType] = useState(null);

  const handleSync = async (type) => {
    setSyncing(true);
    setSyncType(type);
    try {
      const endpoint = type === 'all' 
        ? `${API_BASE}/api/learning-connectors/sync/all`
        : `${API_BASE}/api/learning-connectors/sync/${type}`;
      
      const res = await fetch(endpoint, { method: 'POST' });
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Sync completed: ${type}`);
        onRefresh();
      } else {
        toast.error(data.error || 'Sync failed');
      }
    } catch (err) {
      toast.error('Sync error');
    } finally {
      setSyncing(false);
      setSyncType(null);
    }
  };

  const getHealthColor = (health) => {
    switch (health) {
      case 'healthy': return 'emerald';
      case 'pending': return 'amber';
      case 'degraded': return 'orange';
      case 'disconnected': return 'rose';
      default: return 'zinc';
    }
  };

  const getHealthIcon = (health) => {
    switch (health) {
      case 'healthy': return CheckCircle;
      case 'pending': return Clock;
      case 'degraded': return AlertCircle;
      case 'disconnected': return Unlink;
      default: return Clock;
    }
  };

  // Calculate summary
  const summary = connections.reduce((acc, conn) => {
    acc[conn.health] = (acc[conn.health] || 0) + 1;
    return acc;
  }, {});

  return (
    <GlassCard className="p-5" gradient glow>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-indigo-500/20 flex items-center justify-center">
            <GitBranch className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Learning Connections</h3>
            <p className="text-[10px] text-zinc-500">Data flow between systems • <span className="text-emerald-400">Auto-sync: 5pm ET daily</span></p>
          </div>
        </div>
        <button
          onClick={() => handleSync('all')}
          disabled={syncing}
          className="px-3 py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-400 text-xs font-medium hover:bg-blue-500/30 transition-all disabled:opacity-50 flex items-center gap-1.5"
          data-testid="sync-all-btn"
        >
          {syncing && syncType === 'all' ? <Loader className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          Sync All
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <StatCard 
              label="Total Data" 
              value={metrics?.total_data_points?.toLocaleString() || '0'} 
              icon={Database} 
              color="blue" 
            />
            <StatCard 
              label="Used for Training" 
              value={metrics?.data_points_used_for_training?.toLocaleString() || '0'} 
              icon={Brain} 
              color="violet" 
            />
            <StatCard 
              label="Calibrations" 
              value={metrics?.calibrations_applied || 0} 
              icon={Settings} 
              color="amber" 
            />
            <StatCard 
              label="Model Versions" 
              value={metrics?.model_versions_created || 0} 
              icon={Layers} 
              color="cyan" 
            />
          </div>

          {/* Connection Health Summary */}
          <div className="flex gap-2 mb-4">
            {['healthy', 'pending', 'disconnected'].map(status => (
              <div key={status} className={`flex items-center gap-1.5 px-2 py-1 rounded-lg bg-${getHealthColor(status)}-500/10 border border-${getHealthColor(status)}-500/20`}>
                {React.createElement(getHealthIcon(status), { className: `w-3 h-3 text-${getHealthColor(status)}-400` })}
                <span className={`text-[10px] font-medium text-${getHealthColor(status)}-400`}>
                  {summary[status] || 0} {status}
                </span>
              </div>
            ))}
          </div>

          {/* Connections List */}
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {connections.map((conn, i) => {
              const HealthIcon = getHealthIcon(conn.health);
              const color = getHealthColor(conn.health);
              
              return (
                <div 
                  key={i} 
                  className="p-3 rounded-xl bg-black/30 border border-white/5 flex items-center justify-between"
                  data-testid={`connection-${conn.name}`}
                >
                  <div className="flex items-center gap-3">
                    <HealthIcon className={`w-4 h-4 text-${color}-400`} />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-white">{conn.source}</span>
                        <ArrowRight className="w-3 h-3 text-zinc-500" />
                        <span className="text-xs font-medium text-white">{conn.destination}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded bg-${color}-500/20 text-${color}-400`}>
                          {conn.health.toUpperCase()}
                        </span>
                        <span className="text-[9px] text-zinc-500">
                          {conn.sync_frequency} • {conn.records_synced} synced
                        </span>
                      </div>
                    </div>
                  </div>
                  {conn.is_connected && (
                    <button
                      onClick={() => handleSync(conn.name.replace(/_/g, '-'))}
                      disabled={syncing}
                      className="px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-zinc-400 hover:text-white text-[10px] hover:bg-white/10 transition-all disabled:opacity-50"
                    >
                      {syncing && syncType === conn.name.replace(/_/g, '-') ? (
                        <Loader className="w-3 h-3 animate-spin" />
                      ) : (
                        'Sync'
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* Module Weights */}
          {Object.keys(weights).length > 0 && (
            <div className="mt-4 p-3 rounded-xl bg-black/30 border border-white/5">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">AI Module Weights (Auto-Calibrated)</h4>
              <div className="flex flex-wrap gap-2">
                {Object.entries(weights).map(([module, weight]) => (
                  <div key={module} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-violet-500/10 border border-violet-500/20">
                    <span className="text-[10px] text-zinc-400">{module.replace(/_/g, ' ')}</span>
                    <span className={`text-[10px] font-bold ${weight > 1 ? 'text-emerald-400' : weight < 1 ? 'text-amber-400' : 'text-zinc-400'}`}>
                      {weight.toFixed(2)}x
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </GlassCard>
  );
};

// IB Data Collection Panel
const IBDataCollectionPanel = ({ status, stats, queueProgress, defaultSymbolCount = 51, fullMarketCount = 0, loading, onRefresh }) => {
  const [collecting, setCollecting] = useState(false);
  const [collectionType, setCollectionType] = useState(null);
  const [smartPlan, setSmartPlan] = useState(null);
  const [showSmartPlan, setShowSmartPlan] = useState(false);

  // Fetch smart collection plan on mount
  useEffect(() => {
    const fetchSmartPlan = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/ib-collector/smart-collection-plan`);
        const data = await res.json();
        if (data.success) {
          setSmartPlan(data);
        }
      } catch (err) {
        console.error('Error fetching smart plan:', err);
      }
    };
    fetchSmartPlan();
  }, []);

  const handleStartCollection = async (type) => {
    setCollecting(true);
    setCollectionType(type);
    try {
      let endpoint;
      switch (type) {
        case 'quick':
          endpoint = `${API_BASE}/api/ib-collector/quick-collect`;
          break;
        case 'full':
          endpoint = `${API_BASE}/api/ib-collector/full-collection?days=30`;
          break;
        case 'market':
          endpoint = `${API_BASE}/api/ib-collector/full-market-collection?days=30&bar_size=1%20day`;
          break;
        case 'smart':
          endpoint = `${API_BASE}/api/ib-collector/smart-collection-run?days=30`;
          break;
        default:
          endpoint = `${API_BASE}/api/ib-collector/quick-collect`;
      }
      
      const res = await fetch(endpoint, { method: 'POST' });
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Started ${type} collection: ${data.job_id || 'smart-tiered'}`);
        onRefresh();
      } else {
        toast.error(data.error || 'Failed to start collection');
      }
    } catch (err) {
      toast.error('Error starting collection');
    } finally {
      setCollecting(false);
      setCollectionType(null);
    }
  };

  const handleCancel = async () => {
    try {
      // Use the new queue-cancel endpoint if we have a job_id
      const endpoint = status?.id 
        ? `${API_BASE}/api/ib-collector/queue-cancel?job_id=${status.id}`
        : `${API_BASE}/api/ib-collector/cancel`;
      
      const res = await fetch(endpoint, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(`Collection cancelled (${data.cancelled || 0} pending requests cleared)`);
        onRefresh();
      }
    } catch (err) {
      toast.error('Error cancelling collection');
    }
  };

  const isRunning = status?.status === 'running';
  const totalBars = stats?.total_bars || 0;
  const uniqueSymbols = stats?.unique_symbols || 0;
  
  // Use queue progress for more accurate real-time stats
  // Calculate progress_pct from overall queue stats
  const rawQueueProgress = queueProgress || {};
  const queueTotal = (rawQueueProgress.pending || 0) + (rawQueueProgress.claimed || 0) + 
                     (rawQueueProgress.completed || 0) + (rawQueueProgress.failed || 0);
  const queueDone = (rawQueueProgress.completed || 0) + (rawQueueProgress.failed || 0);
  
  const progressData = {
    total: queueTotal || status?.symbols?.length || 0,
    completed: rawQueueProgress.completed || status?.symbols_completed || 0,
    failed: rawQueueProgress.failed || status?.symbols_failed || 0,
    pending: rawQueueProgress.pending || 0,
    processing: rawQueueProgress.claimed || 0,
    progress_pct: queueTotal > 0 ? (queueDone / queueTotal * 100) : (status?.progress_pct || 0)
  };

  return (
    <GlassCard className="p-5" gradient>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500/20 to-red-500/20 flex items-center justify-center">
            <HardDrive className="w-5 h-5 text-orange-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">IB Data Collection</h3>
            <p className="text-[10px] text-zinc-500">Historical OHLCV from IB Gateway</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isRunning ? (
            <button
              onClick={handleCancel}
              className="px-3 py-1.5 rounded-lg bg-rose-500/20 border border-rose-500/30 text-rose-400 text-xs font-medium hover:bg-rose-500/30 transition-all flex items-center gap-1.5"
              data-testid="cancel-collection-btn"
            >
              <StopCircle className="w-3 h-3" />
              Cancel
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleStartCollection('quick')}
                disabled={collecting}
                className="px-2.5 py-1.5 rounded-lg bg-zinc-500/20 border border-zinc-500/30 text-zinc-400 text-[10px] font-medium hover:bg-zinc-500/30 transition-all disabled:opacity-50 flex items-center gap-1"
                data-testid="quick-collect-btn"
                title="Quick test with 8 high-volume symbols"
              >
                {collecting && collectionType === 'quick' ? <Loader className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                Quick (8)
              </button>
              <button
                onClick={() => handleStartCollection('full')}
                disabled={collecting}
                className="px-2.5 py-1.5 rounded-lg bg-orange-500/20 border border-orange-500/30 text-orange-400 text-[10px] font-medium hover:bg-orange-500/30 transition-all disabled:opacity-50 flex items-center gap-1"
                data-testid="full-collect-btn"
                title={`Collect ${defaultSymbolCount} curated symbols`}
              >
                {collecting && collectionType === 'full' ? <Loader className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                Curated ({defaultSymbolCount})
              </button>
              <button
                onClick={() => handleStartCollection('market')}
                disabled={collecting}
                className="px-2.5 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 text-[10px] font-medium hover:bg-emerald-500/30 transition-all disabled:opacity-50 flex items-center gap-1"
                data-testid="market-collect-btn"
                title={`Collect ALL ${fullMarketCount.toLocaleString()} US stocks - runs overnight`}
              >
                {collecting && collectionType === 'market' ? <Loader className="w-3 h-3 animate-spin" /> : <Database className="w-3 h-3" />}
                Full Market ({fullMarketCount.toLocaleString() || '8000+'})
              </button>
              <button
                onClick={() => handleStartCollection('smart')}
                disabled={collecting}
                className="px-2.5 py-1.5 rounded-lg bg-purple-500/20 border border-purple-500/30 text-purple-400 text-[10px] font-medium hover:bg-purple-500/30 transition-all disabled:opacity-50 flex items-center gap-1"
                data-testid="smart-collect-btn"
                title="Smart collection: Only stocks matching your ADV filters (~2-4K symbols, ~3hrs)"
              >
                {collecting && collectionType === 'smart' ? <Loader className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                Smart
              </button>
              <button
                onClick={() => setShowSmartPlan(!showSmartPlan)}
                className="px-1.5 py-1.5 rounded-lg bg-zinc-700/50 border border-zinc-600/30 text-zinc-400 text-[10px] hover:bg-zinc-600/50 transition-all"
                data-testid="smart-info-btn"
                title="View Smart Collection plan details"
              >
                <Info className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Smart Collection Plan Info */}
      {showSmartPlan && smartPlan && (
        <div className="mb-4 p-4 rounded-xl bg-purple-500/10 border border-purple-500/30">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-bold text-purple-400">Smart Collection Plan</h4>
            <span className="text-xs text-zinc-400">~{smartPlan.total_estimated_hours} hrs total</span>
          </div>
          <p className="text-[10px] text-zinc-400 mb-3">
            Only collects data for stocks matching your bot's ADV filters. Much faster than Full Market.
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div className="p-2 rounded-lg bg-black/30">
              <div className="text-[10px] text-cyan-400 font-medium mb-1">Intraday (1min, 5min)</div>
              <div className="text-lg font-bold text-white">{smartPlan.plan?.intraday?.symbol_count?.toLocaleString() || 0}</div>
              <div className="text-[9px] text-zinc-500">ADV ≥ 500K</div>
              <div className="text-[9px] text-zinc-500">~{smartPlan.plan?.intraday?.estimated_hours?.toFixed(1)}h</div>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <div className="text-[10px] text-amber-400 font-medium mb-1">Swing (15min, 1hr)</div>
              <div className="text-lg font-bold text-white">{smartPlan.plan?.swing?.symbol_count?.toLocaleString() || 0}</div>
              <div className="text-[9px] text-zinc-500">ADV ≥ 100K</div>
              <div className="text-[9px] text-zinc-500">~{smartPlan.plan?.swing?.estimated_hours?.toFixed(1)}h</div>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <div className="text-[10px] text-emerald-400 font-medium mb-1">Investment (1day)</div>
              <div className="text-lg font-bold text-white">{smartPlan.plan?.investment?.symbol_count?.toLocaleString() || 0}</div>
              <div className="text-[9px] text-zinc-500">ADV ≥ 50K</div>
              <div className="text-[9px] text-zinc-500">~{smartPlan.plan?.investment?.estimated_hours?.toFixed(1)}h</div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader className="w-6 h-6 text-orange-400 animate-spin" />
        </div>
      ) : (
        <>
          {/* Running Job Status */}
          {isRunning && status && (
            <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/30">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Loader className="w-4 h-4 text-orange-400 animate-spin" />
                  <span className="text-sm font-medium text-white">Collection Running</span>
                </div>
                <span className="text-xs text-orange-400">{progressData.progress_pct?.toFixed(1)}%</span>
              </div>
              
              {/* Progress Bar */}
              <div className="w-full h-2 bg-black/30 rounded-full overflow-hidden mb-2">
                <div 
                  className="h-full bg-gradient-to-r from-orange-500 to-amber-500 transition-all duration-500"
                  style={{ width: `${progressData.progress_pct || 0}%` }}
                />
              </div>
              
              {/* Queue Status - Real-time from IB Data Pusher */}
              <div className="grid grid-cols-4 gap-2 mb-3">
                <div className="p-2 rounded-lg bg-black/30 text-center">
                  <div className="text-lg font-bold text-amber-400">{progressData.pending || 0}</div>
                  <div className="text-[9px] text-zinc-500 uppercase">Pending</div>
                </div>
                <div className="p-2 rounded-lg bg-black/30 text-center">
                  <div className="text-lg font-bold text-cyan-400">{progressData.processing || 0}</div>
                  <div className="text-[9px] text-zinc-500 uppercase">Processing</div>
                </div>
                <div className="p-2 rounded-lg bg-black/30 text-center">
                  <div className="text-lg font-bold text-emerald-400">{progressData.completed || 0}</div>
                  <div className="text-[9px] text-zinc-500 uppercase">Completed</div>
                </div>
                <div className="p-2 rounded-lg bg-black/30 text-center">
                  <div className="text-lg font-bold text-rose-400">{progressData.failed || 0}</div>
                  <div className="text-[9px] text-zinc-500 uppercase">Failed</div>
                </div>
              </div>
              
              <div className="flex items-center justify-between text-[10px] text-zinc-400">
                <span>Total: <span className="text-white">{progressData.total || status.symbols?.length || 0} symbols</span></span>
                <span className="text-emerald-400">{status.total_bars_collected?.toLocaleString() || 0} bars collected</span>
              </div>
              
              {/* Recent Errors */}
              {queueProgress?.recent_errors?.length > 0 && (
                <div className="mt-3 p-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
                  <div className="text-[10px] text-rose-400 font-medium mb-1">Recent Errors:</div>
                  <div className="space-y-0.5">
                    {queueProgress.recent_errors.slice(0, 3).map((err, i) => (
                      <div key={i} className="text-[9px] text-zinc-400 truncate">
                        {err.symbol}: {err.error?.substring(0, 50) || 'Unknown error'}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Pusher Status Hint */}
              {progressData.pending > 0 && progressData.processing === 0 && (
                <div className="mt-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                  <div className="text-[10px] text-amber-400 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    Waiting for IB Data Pusher - make sure it's running on your local machine
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <StatCard 
              label="Total Bars" 
              value={totalBars.toLocaleString()} 
              icon={BarChart2} 
              color="orange" 
            />
            <StatCard 
              label="Symbols" 
              value={uniqueSymbols} 
              icon={Database} 
              color="cyan" 
            />
            <StatCard 
              label="Bar Sizes" 
              value={Object.keys(stats?.by_bar_size || {}).length || 0} 
              icon={Layers} 
              color="violet" 
            />
            <StatCard 
              label="Status" 
              value={isRunning ? 'Running' : totalBars > 0 ? 'Ready' : 'Empty'} 
              icon={isRunning ? Loader : CheckCircle} 
              color={isRunning ? 'amber' : totalBars > 0 ? 'emerald' : 'zinc'} 
            />
          </div>

          {/* Bar Size Breakdown */}
          {stats?.by_bar_size && Object.keys(stats.by_bar_size).length > 0 && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5 mb-4">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Data by Bar Size</h4>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(stats.by_bar_size).map(([size, data]) => (
                  <div key={size} className="p-2 rounded-lg bg-black/30 text-center">
                    <p className="text-xs font-bold text-white">{size}</p>
                    <p className="text-[10px] text-orange-400">{data.bars?.toLocaleString() || 0} bars</p>
                    <p className="text-[9px] text-zinc-500">{data.symbols || 0} symbols</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Symbols List */}
          {stats?.symbols_list?.length > 0 && (
            <div className="p-3 rounded-xl bg-black/30 border border-white/5">
              <h4 className="text-[10px] text-zinc-500 uppercase mb-2">Collected Symbols ({uniqueSymbols})</h4>
              <div className="flex flex-wrap gap-1">
                {stats.symbols_list.slice(0, 20).map((symbol) => (
                  <span key={symbol} className="px-2 py-0.5 rounded-full bg-orange-500/10 border border-orange-500/20 text-orange-400 text-[10px]">
                    {symbol}
                  </span>
                ))}
                {stats.symbols_list.length > 20 && (
                  <span className="px-2 py-0.5 rounded-full bg-zinc-500/10 text-zinc-400 text-[10px]">
                    +{stats.symbols_list.length - 20} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Empty State */}
          {totalBars === 0 && !isRunning && (
            <div className="text-center py-6">
              <HardDrive className="w-10 h-10 text-zinc-600 mx-auto mb-2" />
              <p className="text-zinc-500 text-sm">No historical data collected yet</p>
              <p className="text-zinc-600 text-xs mt-1">Start your local system and click "Full Collection" to begin</p>
            </div>
          )}
        </>
      )}
    </GlassCard>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const TrainingCenter = () => {
  const { jobs, loading: jobsLoading, refresh: refreshJobs } = useSimulationJobs();
  const { status: tsStatus, loading: tsLoading, refresh: refreshTs } = useTimeseriesStatus();
  const { accuracy, predictions, loading: predLoading, refresh: refreshPred } = usePredictionAccuracy();
  const { connections, metrics, weights, loading: connLoading, refresh: refreshConn } = useLearningConnections();
  const { status: ibStatus, stats: ibStats, queueProgress: ibQueueProgress, defaultSymbolCount, fullMarketCount, loading: ibLoading, refresh: refreshIB } = useIBCollection();
  const { summary: storageSummary, loading: storageLoading, refresh: refreshStorage } = useDataStorage();

  return (
    <div className="space-y-6" data-testid="training-center">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 flex items-center justify-center">
            <FlaskConical className="w-6 h-6 text-violet-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Training Center</h1>
            <p className="text-sm text-zinc-400">Make the entire system smarter through simulation and learning</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Total Learning Samples Badge */}
          {storageSummary && (
            <div className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <span className="text-xs text-emerald-400 font-medium">
                {storageSummary.total_learning_samples?.toLocaleString() || 0} total samples
              </span>
            </div>
          )}
          <button
            onClick={() => {
              refreshJobs();
              refreshTs();
              refreshPred();
              refreshConn();
              refreshIB();
              refreshStorage();
              toast.success('Refreshed all data');
            }}
            className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-zinc-400 hover:text-white hover:bg-white/10 transition-all flex items-center gap-2"
            data-testid="refresh-all-btn"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh All
          </button>
        </div>
      </div>

      {/* Top Row - Learning Connections & IB Data Collection */}
      <div className="grid grid-cols-2 gap-6">
        <LearningConnectionsPanel 
          connections={connections}
          metrics={metrics}
          weights={weights}
          loading={connLoading}
          onRefresh={refreshConn}
        />
        <IBDataCollectionPanel
          status={ibStatus}
          stats={ibStats}
          queueProgress={ibQueueProgress}
          defaultSymbolCount={defaultSymbolCount}
          fullMarketCount={fullMarketCount}
          loading={ibLoading}
          onRefresh={refreshIB}
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-2 gap-6">
        {/* Left Column */}
        <div className="space-y-6">
          <SimulationPanel 
            jobs={jobs} 
            loading={jobsLoading} 
            onRefresh={refreshJobs} 
          />
          <LearningInsightsPanel />
        </div>
        
        {/* Right Column */}
        <div className="space-y-6">
          <TimeSeriesPanel 
            status={tsStatus} 
            loading={tsLoading} 
            onRefresh={refreshTs} 
          />
          <PredictionTrackingPanel 
            accuracy={accuracy} 
            predictions={predictions} 
            loading={predLoading} 
            onRefresh={refreshPred} 
          />
        </div>
      </div>
    </div>
  );
};

export default TrainingCenter;
