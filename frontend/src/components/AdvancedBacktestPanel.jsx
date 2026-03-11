/**
 * Advanced Backtest Panel
 * =======================
 * UI for running multi-strategy backtests, walk-forward optimization,
 * Monte Carlo simulations, and custom date range backtesting.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { 
  Play, Loader2, CheckCircle2, XCircle, RefreshCw, ChevronDown, ChevronRight,
  BarChart3, TrendingUp, Target, Shuffle, Calendar, Clock, Settings, 
  AlertTriangle, Download, Filter, Layers, Zap, PieChart
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';

// ============================================================================
// Main Component
// ============================================================================

const AdvancedBacktestPanel = () => {
  const [activeTab, setActiveTab] = useState('quick');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [recentResults, setRecentResults] = useState([]);

  // Fetch templates on mount
  useEffect(() => {
    fetchTemplates();
    fetchRecentResults();
    fetchJobs();
    
    // Poll for job updates
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchTemplates = async () => {
    try {
      const res = await api.get('/api/backtest/strategy-templates');
      if (res.data?.success) {
        setTemplates(res.data.templates);
      }
    } catch (err) {
      console.error('Error fetching templates:', err);
    }
  };

  const fetchRecentResults = async () => {
    try {
      const res = await api.get('/api/backtest/results?limit=10');
      if (res.data?.success) {
        setRecentResults(res.data.results);
      }
    } catch (err) {
      console.error('Error fetching results:', err);
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await api.get('/api/backtest/jobs?limit=10');
      if (res.data?.success) {
        setJobs(res.data.jobs);
      }
    } catch (err) {
      // Silent error - just polling
    }
  };

  const tabs = [
    { id: 'quick', label: 'Quick Test', icon: Zap },
    { id: 'multi', label: 'Multi-Strategy', icon: Layers },
    { id: 'walkforward', label: 'Walk-Forward', icon: TrendingUp },
    { id: 'montecarlo', label: 'Monte Carlo', icon: Shuffle },
    { id: 'results', label: 'Results', icon: BarChart3 }
  ];

  return (
    <div className="space-y-4" data-testid="advanced-backtest-panel">
      {/* Tab Navigation */}
      <div className="flex items-center gap-2 bg-slate-800/30 p-1.5 rounded-lg border border-slate-700/50">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/30'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Running Jobs Banner */}
      {jobs.filter(j => j.status === 'running').length > 0 && (
        <RunningJobsBanner jobs={jobs.filter(j => j.status === 'running')} />
      )}

      {/* Tab Content */}
      {activeTab === 'quick' && (
        <QuickBacktestTab 
          templates={templates} 
          onResult={setResults}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'multi' && (
        <MultiStrategyTab 
          templates={templates}
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'walkforward' && (
        <WalkForwardTab 
          templates={templates}
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'montecarlo' && (
        <MonteCarloTab 
          recentResults={recentResults}
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'results' && (
        <ResultsTab 
          jobs={jobs}
          recentResults={recentResults}
          onRefresh={() => { fetchJobs(); fetchRecentResults(); }}
        />
      )}
    </div>
  );
};

// ============================================================================
// Running Jobs Banner
// ============================================================================

const RunningJobsBanner = ({ jobs }) => (
  <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3">
    <div className="flex items-center gap-2 text-cyan-400">
      <Loader2 className="w-4 h-4 animate-spin" />
      <span className="text-sm font-medium">
        {jobs.length} backtest{jobs.length > 1 ? 's' : ''} running in background
      </span>
    </div>
    <div className="mt-2 space-y-1">
      {jobs.map(job => (
        <div key={job.id} className="flex items-center justify-between text-xs">
          <span className="text-slate-400">{job.job_type}: {job.progress_message || 'Processing...'}</span>
          <span className="text-cyan-400">{Math.round(job.progress || 0)}%</span>
        </div>
      ))}
    </div>
  </div>
);

// ============================================================================
// Quick Backtest Tab
// ============================================================================

const QuickBacktestTab = ({ templates, onResult, setLoading, loading }) => {
  const [symbol, setSymbol] = useState('SPY');
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [customConfig, setCustomConfig] = useState({
    name: 'Custom Strategy',
    setup_type: 'ORB',
    stop_pct: 2.0,
    target_pct: 4.0,
    max_bars_to_hold: 20,
    position_size_pct: 10
  });
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [result, setResult] = useState(null);

  // Set default dates (last 1 year)
  useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setFullYear(start.getFullYear() - 1);
    setEndDate(end.toISOString().split('T')[0]);
    setStartDate(start.toISOString().split('T')[0]);
  }, []);

  const handleRun = async () => {
    setLoading(true);
    setResult(null);
    
    try {
      const strategy = selectedTemplate 
        ? { name: selectedTemplate.name, ...selectedTemplate.config, setup_type: selectedTemplate.setup_type }
        : customConfig;

      const res = await api.post('/api/backtest/quick', {
        symbol: symbol.toUpperCase(),
        strategy,
        start_date: startDate || null,
        end_date: endDate || null,
        starting_capital: 100000
      });

      if (res.data?.success) {
        setResult(res.data.result);
        onResult(res.data.result);
        toast.success('Backtest complete!');
      }
    } catch (err) {
      toast.error('Backtest failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Configuration */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <h3 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
          <Settings className="w-4 h-4 text-cyan-400" />
          Quick Backtest Configuration
        </h3>

        {/* Symbol */}
        <div className="mb-4">
          <label className="text-xs text-slate-400 block mb-1">Symbol</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            placeholder="SPY"
          />
        </div>

        {/* Date Range */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
        </div>

        {/* Strategy Templates */}
        <div className="mb-4">
          <label className="text-xs text-slate-400 block mb-2">Strategy Template</label>
          <div className="grid grid-cols-2 gap-2">
            {templates.map((t, i) => (
              <button
                key={i}
                onClick={() => setSelectedTemplate(t)}
                className={`p-2 text-left rounded-lg border text-xs transition-colors ${
                  selectedTemplate?.name === t.name
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                    : 'bg-slate-900/50 border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                <div className="font-medium text-white">{t.name}</div>
                <div className="text-slate-500">{t.setup_type}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Run Button */}
        <button
          onClick={handleRun}
          disabled={loading}
          className="w-full py-3 bg-cyan-500 hover:bg-cyan-600 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center justify-center gap-2 transition-colors"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Running Backtest...
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Run Quick Backtest
            </>
          )}
        </button>
      </div>

      {/* Results */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <h3 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-emerald-400" />
          Results
        </h3>

        {result ? (
          <QuickResultDisplay result={result} />
        ) : (
          <div className="flex flex-col items-center justify-center h-64 text-slate-500">
            <BarChart3 className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">Run a backtest to see results</p>
          </div>
        )}
      </div>
    </div>
  );
};

const QuickResultDisplay = ({ result }) => (
  <div className="space-y-3">
    <div className="grid grid-cols-2 gap-2">
      <MetricBox label="Total Trades" value={result.total_trades} />
      <MetricBox 
        label="Win Rate" 
        value={`${result.win_rate?.toFixed(1)}%`} 
        positive={result.win_rate >= 50}
      />
      <MetricBox 
        label="Total P&L" 
        value={`$${result.total_pnl?.toFixed(0)}`} 
        positive={result.total_pnl >= 0}
      />
      <MetricBox 
        label="Profit Factor" 
        value={result.profit_factor?.toFixed(2)} 
        positive={result.profit_factor >= 1.5}
      />
      <MetricBox 
        label="Sharpe Ratio" 
        value={result.sharpe_ratio?.toFixed(2)} 
        positive={result.sharpe_ratio >= 1}
      />
      <MetricBox 
        label="Max Drawdown" 
        value={`${result.max_drawdown_pct?.toFixed(1)}%`} 
        positive={result.max_drawdown_pct < 15}
      />
      <MetricBox 
        label="Avg R" 
        value={result.avg_r?.toFixed(2)} 
        positive={result.avg_r >= 1}
      />
    </div>
    
    <div className="text-xs text-slate-500 pt-2 border-t border-slate-700">
      {result.start_date} to {result.end_date}
    </div>
  </div>
);

const MetricBox = ({ label, value, positive }) => (
  <div className="bg-slate-900/50 rounded-lg p-2">
    <div className="text-xs text-slate-500">{label}</div>
    <div className={`text-lg font-semibold ${
      positive === true ? 'text-emerald-400' : 
      positive === false ? 'text-red-400' : 'text-white'
    }`}>
      {value || '--'}
    </div>
  </div>
);

// ============================================================================
// Multi-Strategy Tab
// ============================================================================

const MultiStrategyTab = ({ templates, onJobStarted, setLoading, loading }) => {
  const [symbols, setSymbols] = useState('SPY,QQQ,IWM,AAPL,MSFT');
  const [selectedTemplates, setSelectedTemplates] = useState([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setFullYear(start.getFullYear() - 1);
    setEndDate(end.toISOString().split('T')[0]);
    setStartDate(start.toISOString().split('T')[0]);
  }, []);

  const toggleTemplate = (template) => {
    setSelectedTemplates(prev => {
      const exists = prev.find(t => t.name === template.name);
      if (exists) {
        return prev.filter(t => t.name !== template.name);
      }
      return [...prev, template];
    });
  };

  const handleRun = async () => {
    if (selectedTemplates.length === 0) {
      toast.error('Select at least one strategy');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/api/backtest/multi-strategy', {
        symbols: symbols.split(',').map(s => s.trim().toUpperCase()),
        strategies: selectedTemplates.map(t => ({
          name: t.name,
          setup_type: t.setup_type,
          ...t.config
        })),
        filters: {
          start_date: startDate || null,
          end_date: endDate || null
        },
        run_in_background: true
      });

      if (res.data?.success) {
        toast.success('Multi-strategy backtest started!');
        onJobStarted();
      }
    } catch (err) {
      toast.error('Failed to start backtest');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
        <Layers className="w-4 h-4 text-purple-400" />
        Multi-Strategy Comparison
      </h3>

      <div className="space-y-4">
        {/* Symbols */}
        <div>
          <label className="text-xs text-slate-400 block mb-1">Symbols (comma-separated)</label>
          <input
            type="text"
            value={symbols}
            onChange={(e) => setSymbols(e.target.value.toUpperCase())}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            placeholder="SPY,QQQ,AAPL"
          />
        </div>

        {/* Date Range */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
        </div>

        {/* Strategy Selection */}
        <div>
          <label className="text-xs text-slate-400 block mb-2">
            Select Strategies to Compare ({selectedTemplates.length} selected)
          </label>
          <div className="grid grid-cols-3 gap-2">
            {templates.map((t, i) => (
              <button
                key={i}
                onClick={() => toggleTemplate(t)}
                className={`p-3 text-left rounded-lg border text-xs transition-colors ${
                  selectedTemplates.find(s => s.name === t.name)
                    ? 'bg-purple-500/20 border-purple-500/50 text-purple-400'
                    : 'bg-slate-900/50 border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                <div className="font-medium text-white">{t.name}</div>
                <div className="text-slate-500">{t.description}</div>
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleRun}
          disabled={loading || selectedTemplates.length === 0}
          className="w-full py-3 bg-purple-500 hover:bg-purple-600 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run Multi-Strategy Backtest
        </button>
      </div>
    </div>
  );
};

// ============================================================================
// Walk-Forward Tab
// ============================================================================

const WalkForwardTab = ({ templates, onJobStarted, setLoading, loading }) => {
  const [symbol, setSymbol] = useState('SPY');
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [config, setConfig] = useState({
    in_sample_days: 180,
    out_of_sample_days: 30,
    step_days: 30,
    total_days: 365
  });

  const handleRun = async () => {
    if (!selectedTemplate) {
      toast.error('Select a strategy');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/api/backtest/walk-forward', {
        symbol: symbol.toUpperCase(),
        strategy: {
          name: selectedTemplate.name,
          setup_type: selectedTemplate.setup_type,
          ...selectedTemplate.config
        },
        ...config,
        run_in_background: true
      });

      if (res.data?.success) {
        toast.success('Walk-forward optimization started!');
        onJobStarted();
      }
    } catch (err) {
      toast.error('Failed to start walk-forward');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
        <TrendingUp className="w-4 h-4 text-emerald-400" />
        Walk-Forward Optimization
      </h3>

      <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
        <p className="text-xs text-blue-400">
          Walk-forward tests strategy robustness by splitting data into training (in-sample) 
          and testing (out-of-sample) periods. A good efficiency ratio (&gt;70%) indicates 
          the strategy is not overfit.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Symbol</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-slate-400 block mb-1">In-Sample Days</label>
            <input
              type="number"
              value={config.in_sample_days}
              onChange={(e) => setConfig({...config, in_sample_days: parseInt(e.target.value)})}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Out-of-Sample Days</label>
            <input
              type="number"
              value={config.out_of_sample_days}
              onChange={(e) => setConfig({...config, out_of_sample_days: parseInt(e.target.value)})}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Step Days</label>
            <input
              type="number"
              value={config.step_days}
              onChange={(e) => setConfig({...config, step_days: parseInt(e.target.value)})}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Total Days</label>
            <input
              type="number"
              value={config.total_days}
              onChange={(e) => setConfig({...config, total_days: parseInt(e.target.value)})}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-2">Select Strategy</label>
          <div className="grid grid-cols-2 gap-2">
            {templates.map((t, i) => (
              <button
                key={i}
                onClick={() => setSelectedTemplate(t)}
                className={`p-2 text-left rounded-lg border text-xs ${
                  selectedTemplate?.name === t.name
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400'
                    : 'bg-slate-900/50 border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                <div className="font-medium text-white">{t.name}</div>
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={handleRun}
          disabled={loading || !selectedTemplate}
          className="w-full py-3 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run Walk-Forward Analysis
        </button>
      </div>
    </div>
  );
};

// ============================================================================
// Monte Carlo Tab
// ============================================================================

const MonteCarloTab = ({ recentResults, onJobStarted, setLoading, loading }) => {
  const [selectedBacktest, setSelectedBacktest] = useState('');
  const [config, setConfig] = useState({
    num_simulations: 10000,
    randomize_trade_order: true,
    randomize_trade_size: false
  });

  const handleRun = async () => {
    if (!selectedBacktest) {
      toast.error('Select a backtest to analyze');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/api/backtest/monte-carlo', {
        backtest_id: selectedBacktest,
        ...config,
        run_in_background: true
      });

      if (res.data?.success) {
        toast.success('Monte Carlo simulation started!');
        onJobStarted();
      }
    } catch (err) {
      toast.error('Failed to start simulation');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
        <Shuffle className="w-4 h-4 text-orange-400" />
        Monte Carlo Simulation
      </h3>

      <div className="mb-4 p-3 bg-orange-500/10 border border-orange-500/30 rounded-lg">
        <p className="text-xs text-orange-400">
          Monte Carlo shuffles your trades thousands of times to show the range of possible 
          outcomes. This helps you understand realistic drawdown expectations and risk.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-xs text-slate-400 block mb-2">Select Backtest to Analyze</label>
          <select
            value={selectedBacktest}
            onChange={(e) => setSelectedBacktest(e.target.value)}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
          >
            <option value="">-- Select a backtest --</option>
            {recentResults.filter(r => r.id?.startsWith('mbt_')).map(r => (
              <option key={r.id} value={r.id}>
                {r.name || r.id} ({r.combined_total_trades || 0} trades)
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">Number of Simulations</label>
          <input
            type="number"
            value={config.num_simulations}
            onChange={(e) => setConfig({...config, num_simulations: parseInt(e.target.value)})}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            min={1000}
            max={100000}
            step={1000}
          />
          <p className="text-xs text-slate-500 mt-1">10,000 recommended (takes ~30-60 seconds)</p>
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={config.randomize_trade_order}
              onChange={(e) => setConfig({...config, randomize_trade_order: e.target.checked})}
              className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-cyan-500"
            />
            Shuffle trade order
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={config.randomize_trade_size}
              onChange={(e) => setConfig({...config, randomize_trade_size: e.target.checked})}
              className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-cyan-500"
            />
            Vary position sizes
          </label>
        </div>

        <button
          onClick={handleRun}
          disabled={loading || !selectedBacktest}
          className="w-full py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shuffle className="w-4 h-4" />}
          Run Monte Carlo Simulation
        </button>
      </div>
    </div>
  );
};

// ============================================================================
// Results Tab
// ============================================================================

const ResultsTab = ({ jobs, recentResults, onRefresh }) => {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Backtest Results & Jobs</h3>
        <button
          onClick={onRefresh}
          className="p-2 hover:bg-slate-700/50 rounded-lg transition-colors"
        >
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Active Jobs */}
      {jobs.length > 0 && (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
          <h4 className="text-xs text-slate-400 mb-3">Active Jobs</h4>
          <div className="space-y-2">
            {jobs.map(job => (
              <JobRow key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}

      {/* Recent Results */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <h4 className="text-xs text-slate-400 mb-3">Recent Results</h4>
        {recentResults.length > 0 ? (
          <div className="space-y-2">
            {recentResults.map(result => (
              <ResultRow key={result.id} result={result} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500 text-center py-4">No results yet</p>
        )}
      </div>
    </div>
  );
};

const JobRow = ({ job }) => {
  const statusColors = {
    pending: 'text-yellow-400',
    running: 'text-cyan-400',
    completed: 'text-emerald-400',
    failed: 'text-red-400'
  };

  return (
    <div className="flex items-center justify-between p-2 bg-slate-900/50 rounded-lg">
      <div>
        <div className="text-sm text-white">{job.job_type}</div>
        <div className="text-xs text-slate-500">{job.progress_message || job.id}</div>
      </div>
      <div className="flex items-center gap-3">
        {job.status === 'running' && (
          <div className="text-xs text-cyan-400">{Math.round(job.progress || 0)}%</div>
        )}
        <span className={`text-xs ${statusColors[job.status]}`}>{job.status}</span>
      </div>
    </div>
  );
};

const ResultRow = ({ result }) => {
  const typeLabels = {
    'mbt_': { label: 'Multi-Strategy', color: 'text-purple-400' },
    'wf_': { label: 'Walk-Forward', color: 'text-emerald-400' },
    'mc_': { label: 'Monte Carlo', color: 'text-orange-400' }
  };

  const type = Object.entries(typeLabels).find(([prefix]) => result.id?.startsWith(prefix));
  
  return (
    <div className="flex items-center justify-between p-2 bg-slate-900/50 rounded-lg">
      <div>
        <div className="text-sm text-white">{result.name || result.strategy_name || result.id}</div>
        <div className="flex items-center gap-2 text-xs">
          {type && <span className={type[1].color}>{type[1].label}</span>}
          <span className="text-slate-500">{result.created_at?.split('T')[0]}</span>
        </div>
      </div>
      <ChevronRight className="w-4 h-4 text-slate-500" />
    </div>
  );
};

export default AdvancedBacktestPanel;
