/**
 * Advanced Backtest Panel
 * =======================
 * UI for running multi-strategy backtests, walk-forward optimization,
 * Monte Carlo simulations, and custom date range backtesting.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Play, Loader2, CheckCircle2, XCircle, RefreshCw, ChevronDown, ChevronRight,
  BarChart3, TrendingUp, Target, Shuffle, Calendar, Clock, Settings, 
  AlertTriangle, Download, Filter, Layers, Zap, PieChart, Globe, Search, Brain
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';
import { Tip, TipIcon, CustomTip } from './shared/Tooltip';
import { useTrainingMode } from '../contexts';

// ============================================================================
// Main Component
// ============================================================================

const AdvancedBacktestPanel = () => {
  const [activeTab, setActiveTab] = useState('quick');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [allStrategies, setAllStrategies] = useState([]);
  const [recentResults, setRecentResults] = useState([]);
  const [selectedResult, setSelectedResult] = useState(null);
  
  const { getPollingInterval, isTrainingActive } = useTrainingMode();
  const isVisibleRef = useRef(document.visibilityState === 'visible');

  // Track visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      isVisibleRef.current = document.visibilityState === 'visible';
      if (isVisibleRef.current) fetchJobs();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Fetch templates and strategies on mount
  useEffect(() => {
    fetchTemplates();
    fetchAllStrategies();
    fetchRecentResults();
    fetchJobs();
    
    // Poll for job updates - visibility aware and training mode aware
    const interval = getPollingInterval(5000, false);
    const timer = setInterval(() => {
      if (isVisibleRef.current && !isTrainingActive) {
        fetchJobs();
      }
    }, interval);
    return () => clearInterval(timer);
  }, [getPollingInterval, isTrainingActive]);

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

  const fetchAllStrategies = async () => {
    try {
      const res = await api.get('/api/backtest/strategies');
      if (res.data?.success) {
        setAllStrategies(res.data.strategies || []);
      }
    } catch (err) {
      console.error('Error fetching strategies:', err);
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
    { id: 'quick', label: 'Quick Test', icon: Zap, tip: 'Fast single-strategy test on one symbol. Great for validating ideas.' },
    { id: 'ai', label: 'AI Comparison', icon: Target, tip: 'Compare setup-only vs AI+setup vs AI-only. Does your AI model actually improve results?' },
    { id: 'fullsim', label: 'Full AI Sim', icon: Brain, tip: 'Run the complete SentCom AI pipeline on historical data. Tests all agents: Debate, Risk, Institutional, Time-Series.' },
    { id: 'market', label: 'Market-Wide', icon: Globe, tip: 'Scan entire US market with a strategy. Find all historical setups across thousands of stocks.' },
    { id: 'multi', label: 'Multi-Strategy', icon: Layers, tip: 'Test multiple strategies simultaneously to compare performance.' },
    { id: 'walkforward', label: 'Walk-Forward', icon: TrendingUp, tip: 'Advanced optimization: train on one period, test on next. Validates robustness.' },
    { id: 'montecarlo', label: 'Monte Carlo', icon: Shuffle, tip: 'Run thousands of random simulations to understand risk and drawdown distribution.' },
    { id: 'results', label: 'Results', icon: BarChart3, tip: 'View and compare all your past backtest results.' }
  ];

  return (
    <div className="space-y-4" data-testid="advanced-backtest-panel">
      {/* Tab Navigation */}
      <div className="flex items-center gap-2 bg-slate-800/30 p-1.5 rounded-lg border border-slate-700/50">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <CustomTip key={tab.id} label={tab.label} description={tab.tip}>
              <button
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
            </CustomTip>
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
      
      {activeTab === 'ai' && (
        <AIComparisonTab 
          allStrategies={allStrategies}
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}

      {activeTab === 'fullsim' && (
        <FullAISimTab 
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'market' && (
        <MarketWideBacktestTab 
          allStrategies={allStrategies}
          onJobStarted={fetchJobs}
          setLoading={setLoading}
          loading={loading}
        />
      )}
      
      {activeTab === 'multi' && (
        <MultiStrategyTab 
          templates={templates}
          allStrategies={allStrategies}
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
          onSelectResult={setSelectedResult}
        />
      )}

      {/* Result Detail Modal */}
      {selectedResult && (
        <ResultDetailModal 
          result={selectedResult} 
          onClose={() => setSelectedResult(null)} 
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
// Market-Wide Backtest Tab
// ============================================================================

const MarketWideBacktestTab = ({ allStrategies, onJobStarted, setLoading, loading }) => {
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [tradeStyle, setTradeStyle] = useState('swing');
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [maxSymbols, setMaxSymbols] = useState(200);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [result, setResult] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);

  const tradeStyles = [
    { id: 'intraday', label: 'Intraday', desc: 'Fast-moving, 500K min volume' },
    { id: 'swing', label: 'Swing', desc: 'Multi-day, 100K min volume' },
    { id: 'investment', label: 'Investment', desc: 'Long-term, 50K min volume' }
  ];

  const filteredStrategies = allStrategies.filter(s => {
    const matchesCategory = categoryFilter === 'all' || s.category === categoryFilter;
    const matchesSearch = !searchTerm || 
      s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.id.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const runMarketWideBacktest = async () => {
    if (!selectedStrategy) {
      toast.error('Please select a strategy');
      return;
    }

    setLoading(true);
    setResult(null);
    setJobStatus({ status: 'running', progress: 0 });

    try {
      const res = await api.post('/api/backtest/market-wide', {
        strategy: {
          name: selectedStrategy.name,
          setup_type: selectedStrategy.id.startsWith('INT-') ? 'MOMENTUM' : 
                      selectedStrategy.id.startsWith('SWG-') ? 'SWING' : 'BREAKOUT',
          min_tqs_score: 55,
          stop_pct: 3.0,
          target_pct: 6.0,
          use_trailing_stop: true,
          trailing_stop_pct: 2.0,
          max_bars_to_hold: tradeStyle === 'intraday' ? 5 : tradeStyle === 'swing' ? 15 : 30,
          position_size_pct: 10.0
        },
        trade_style: tradeStyle,
        start_date: startDate,
        end_date: endDate,
        max_symbols: maxSymbols,
        run_in_background: false
      });

      if (res.data?.success) {
        setResult(res.data.result);
        setJobStatus({ status: 'completed' });
        toast.success(`Found ${res.data.result?.summary?.total_trades || 0} trades across ${res.data.result?.symbols_with_signals || 0} symbols`);
        onJobStarted?.();
      }
    } catch (err) {
      console.error('Market-wide backtest error:', err);
      toast.error('Backtest failed: ' + (err.response?.data?.detail || err.message));
      setJobStatus({ status: 'failed' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-cyan-500/10 to-purple-500/10 rounded-lg p-4 border border-cyan-500/20">
        <div className="flex items-center gap-2 mb-2">
          <Globe className="w-5 h-5 text-cyan-400" />
          <h3 className="text-lg font-semibold text-white">Market-Wide Strategy Backtest</h3>
        </div>
        <p className="text-sm text-slate-400">
          Run a strategy against the entire US market to see what trades it would have taken.
          Find which stocks triggered your strategy and analyze the results.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left Column - Strategy Selection */}
        <div className="lg:col-span-2 space-y-4">
          {/* Strategy Filter */}
          <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <Search className="w-4 h-4" />
              Select Strategy ({filteredStrategies.length} available)
            </h4>
            
            <div className="flex gap-2 mb-3">
              <input
                type="text"
                placeholder="Search strategies..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="flex-1 bg-slate-900/50 border border-slate-700 rounded px-3 py-2 text-sm text-white"
              />
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="bg-slate-900/50 border border-slate-700 rounded px-3 py-2 text-sm text-white"
              >
                <option value="all">All Categories</option>
                <option value="intraday">Intraday</option>
                <option value="swing">Swing</option>
                <option value="investment">Investment</option>
              </select>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-64 overflow-y-auto">
              {filteredStrategies.map(strategy => (
                <button
                  key={strategy.id}
                  onClick={() => setSelectedStrategy(strategy)}
                  className={`p-2 rounded text-left text-sm transition-all ${
                    selectedStrategy?.id === strategy.id
                      ? 'bg-cyan-500/20 border-cyan-500/50 border'
                      : 'bg-slate-900/30 border border-transparent hover:border-slate-600'
                  }`}
                >
                  <div className="font-medium text-white truncate">{strategy.name}</div>
                  <div className="text-xs text-slate-500">{strategy.id}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Selected Strategy Config */}
          {selectedStrategy && (
            <div className="bg-emerald-500/10 rounded-lg p-4 border border-emerald-500/20">
              <h4 className="text-sm font-medium text-emerald-400 mb-2">Selected Strategy</h4>
              <div className="text-lg font-semibold text-white">{selectedStrategy.name}</div>
              <div className="text-sm text-slate-400 mt-1">{selectedStrategy.id} • {selectedStrategy.category}</div>
            </div>
          )}
        </div>

        {/* Right Column - Parameters */}
        <div className="space-y-4">
          {/* Trade Style */}
          <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3">Trade Style Filter</h4>
            <div className="space-y-2">
              {tradeStyles.map(style => (
                <button
                  key={style.id}
                  onClick={() => setTradeStyle(style.id)}
                  className={`w-full p-3 rounded text-left transition-all ${
                    tradeStyle === style.id
                      ? 'bg-cyan-500/20 border-cyan-500/50 border'
                      : 'bg-slate-900/30 border border-transparent hover:border-slate-600'
                  }`}
                >
                  <div className="font-medium text-white">{style.label}</div>
                  <div className="text-xs text-slate-500">{style.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Date Range */}
          <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <Calendar className="w-4 h-4" />
              Date Range
            </h4>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-slate-400">Start Date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-slate-900/50 border border-slate-700 rounded px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400">End Date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-slate-900/50 border border-slate-700 rounded px-3 py-2 text-sm text-white"
                />
              </div>
            </div>
          </div>

          {/* Max Symbols */}
          <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3">Symbols to Scan</h4>
            <select
              value={maxSymbols}
              onChange={(e) => setMaxSymbols(parseInt(e.target.value))}
              className="w-full bg-slate-900/50 border border-slate-700 rounded px-3 py-2 text-sm text-white"
            >
              <option value={50}>50 (Quick ~10s)</option>
              <option value={100}>100 (Fast ~20s)</option>
              <option value={200}>200 (Standard ~40s)</option>
              <option value={500}>500 (Extended ~2min)</option>
              <option value={1000}>1000 (Full ~5min)</option>
            </select>
          </div>

          {/* Run Button */}
          <button
            onClick={runMarketWideBacktest}
            disabled={loading || !selectedStrategy}
            className={`w-full py-3 rounded-lg font-medium flex items-center justify-center gap-2 transition-all ${
              loading || !selectedStrategy
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-cyan-500 to-purple-500 text-white hover:opacity-90'
            }`}
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Scanning Market...
              </>
            ) : (
              <>
                <Globe className="w-5 h-5" />
                Run Market-Wide Backtest
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results Section */}
      {result && (
        <MarketWideResultsDisplay result={result} />
      )}
    </div>
  );
};

// Market-Wide Results Display Component
const MarketWideResultsDisplay = ({ result }) => {
  const summary = result.summary || {};
  const topTrades = result.top_trades || [];
  const worstTrades = result.worst_trades || [];
  const mostActive = result.most_active_symbols || [];
  const symbolsTraded = result.symbols_traded || [];

  return (
    <div className="space-y-4 mt-6">
      {/* Summary Header */}
      <div className="bg-gradient-to-r from-slate-800/50 to-slate-900/50 rounded-lg p-4 border border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">{result.strategy_name}</h3>
            <p className="text-sm text-slate-400">
              {result.filters?.start_date} to {result.filters?.end_date} • {result.duration_seconds?.toFixed(1)}s
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-cyan-400">
              {result.symbols_with_signals} / {result.total_symbols_scanned}
            </div>
            <div className="text-xs text-slate-400">Symbols with signals</div>
          </div>
        </div>

        {/* Performance Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Total Trades</div>
            <div className="text-xl font-bold text-white">{summary.total_trades || 0}</div>
          </div>
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Win Rate</div>
            <div className={`text-xl font-bold ${summary.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
              {summary.win_rate || 0}%
            </div>
          </div>
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Total P&L</div>
            <div className={`text-xl font-bold ${summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              ${summary.total_pnl?.toLocaleString() || 0}
            </div>
          </div>
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Profit Factor</div>
            <div className={`text-xl font-bold ${summary.profit_factor >= 1 ? 'text-emerald-400' : 'text-amber-400'}`}>
              {summary.profit_factor?.toFixed(2) || 0}
            </div>
          </div>
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Avg Win</div>
            <div className="text-xl font-bold text-emerald-400">${summary.avg_win?.toFixed(0) || 0}</div>
          </div>
          <div className="bg-slate-800/50 rounded p-3 text-center">
            <div className="text-xs text-slate-400">Expectancy</div>
            <div className={`text-xl font-bold ${summary.expectancy >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              ${summary.expectancy?.toFixed(0) || 0}
            </div>
          </div>
        </div>
      </div>

      {/* Top & Worst Trades */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top Trades */}
        <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
          <h4 className="text-sm font-medium text-emerald-400 mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />
            Top Winning Trades
          </h4>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {topTrades.slice(0, 10).map((trade, idx) => (
              <div key={idx} className="flex items-center justify-between bg-slate-900/30 rounded p-2">
                <div>
                  <span className="font-mono text-cyan-400">{trade.symbol}</span>
                  <span className="text-xs text-slate-500 ml-2">{trade.entry_date}</span>
                </div>
                <div className="text-emerald-400 font-medium">
                  +${trade.pnl?.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Most Active Symbols */}
        <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
          <h4 className="text-sm font-medium text-purple-400 mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Most Active Symbols
          </h4>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {mostActive.slice(0, 10).map(([symbol, count], idx) => (
              <div key={idx} className="flex items-center justify-between bg-slate-900/30 rounded p-2">
                <span className="font-mono text-cyan-400">{symbol}</span>
                <div className="flex items-center gap-2">
                  <div className="w-20 bg-slate-700 rounded-full h-2">
                    <div 
                      className="bg-purple-500 h-2 rounded-full"
                      style={{ width: `${Math.min(100, (count / (mostActive[0]?.[1] || 1)) * 100)}%` }}
                    />
                  </div>
                  <span className="text-slate-400 text-sm w-8">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* All Symbols with Trades */}
      <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
        <h4 className="text-sm font-medium text-slate-300 mb-3">
          Symbols with Trades ({symbolsTraded.length})
        </h4>
        <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
          {symbolsTraded.map(symbol => (
            <span key={symbol} className="px-2 py-1 bg-slate-900/50 rounded text-xs font-mono text-cyan-400">
              {symbol}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// Multi-Strategy Tab
// ============================================================================

const MultiStrategyTab = ({ templates, allStrategies, onJobStarted, setLoading, loading }) => {
  const [symbols, setSymbols] = useState('SPY,QQQ,IWM,AAPL,MSFT');
  const [selectedStrategies, setSelectedStrategies] = useState([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setFullYear(start.getFullYear() - 1);
    setEndDate(end.toISOString().split('T')[0]);
    setStartDate(start.toISOString().split('T')[0]);
  }, []);

  const toggleStrategy = (strategy) => {
    setSelectedStrategies(prev => {
      const exists = prev.find(s => s.id === strategy.id || s.name === strategy.name);
      if (exists) {
        return prev.filter(s => s.id !== strategy.id && s.name !== strategy.name);
      }
      return [...prev, strategy];
    });
  };

  // Filter strategies
  const filteredStrategies = allStrategies.filter(s => {
    const matchesCategory = categoryFilter === 'all' || s.category === categoryFilter;
    const matchesSearch = !searchTerm || 
      s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.setup_type?.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const handleRun = async () => {
    if (selectedStrategies.length === 0) {
      toast.error('Select at least one strategy');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/api/backtest/multi-strategy', {
        symbols: symbols.split(',').map(s => s.trim().toUpperCase()),
        strategies: selectedStrategies.map(s => ({
          name: s.name,
          setup_type: s.setup_type,
          ...(s.config || {})
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
        Multi-Strategy Comparison ({allStrategies.length} strategies available)
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

        {/* Strategy Filters */}
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-slate-400 block mb-1">Search Strategies</label>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
              placeholder="Search by name..."
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Category</label>
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm"
            >
              <option value="all">All ({allStrategies.length})</option>
              <option value="intraday">Intraday ({allStrategies.filter(s => s.category === 'intraday').length})</option>
              <option value="swing">Swing ({allStrategies.filter(s => s.category === 'swing').length})</option>
              <option value="investment">Investment ({allStrategies.filter(s => s.category === 'investment').length})</option>
            </select>
          </div>
        </div>

        {/* Strategy Selection */}
        <div>
          <label className="text-xs text-slate-400 block mb-2">
            Select Strategies to Compare ({selectedStrategies.length} selected)
          </label>
          <div className="max-h-64 overflow-y-auto border border-slate-700/50 rounded-lg p-2 space-y-1">
            {filteredStrategies.map((s, i) => (
              <button
                key={s.id || i}
                onClick={() => toggleStrategy(s)}
                className={`w-full p-2 text-left rounded-lg border text-xs transition-colors flex items-center justify-between ${
                  selectedStrategies.find(sel => sel.id === s.id || sel.name === s.name)
                    ? 'bg-purple-500/20 border-purple-500/50 text-purple-400'
                    : 'bg-slate-900/50 border-slate-700/50 text-slate-400 hover:border-slate-600'
                }`}
              >
                <div>
                  <div className="font-medium text-white">{s.name}</div>
                  <div className="text-slate-500">{s.setup_type} • {s.category}</div>
                </div>
                <div className="text-slate-600">{s.timeframe}</div>
              </button>
            ))}
            {filteredStrategies.length === 0 && (
              <div className="text-center py-4 text-slate-500">No strategies match your filters</div>
            )}
          </div>
        </div>

        {/* Selected Summary */}
        {selectedStrategies.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {selectedStrategies.map((s, i) => (
              <span 
                key={i} 
                className="px-2 py-1 bg-purple-500/20 text-purple-400 text-xs rounded-full flex items-center gap-1"
              >
                {s.name}
                <button 
                  onClick={() => toggleStrategy(s)}
                  className="hover:text-white"
                >×</button>
              </span>
            ))}
          </div>
        )}

        <button
          onClick={handleRun}
          disabled={loading || selectedStrategies.length === 0}
          className="w-full py-3 bg-purple-500 hover:bg-purple-600 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run Multi-Strategy Backtest ({selectedStrategies.length} strategies)
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
// AI Comparison Tab
// ============================================================================

const AIComparisonTab = ({ allStrategies, onJobStarted, setLoading, loading }) => {
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA, GOOGL, AMZN');
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.0);
  const [lookbackBars, setLookbackBars] = useState(50);
  const [startingCapital, setStartingCapital] = useState(100000);
  const [aiStatus, setAiStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    fetchAiStatus();
  }, []);

  const fetchAiStatus = async () => {
    try {
      const res = await api.get('/api/backtest/ai-comparison/status');
      setAiStatus(res.data);
    } catch { setAiStatus(null); }
  };

  const runComparison = async () => {
    const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    if (!symbolList.length) return toast.error('Enter at least one symbol');
    
    const strategy = selectedStrategy || {
      name: 'Default ORB',
      setup_type: 'orb',
      stop_pct: 2.0,
      target_pct: 4.0,
      max_bars_to_hold: 20,
      position_size_pct: 10.0,
      min_tqs_score: 0,
      use_trailing_stop: false,
      trailing_stop_pct: 1.0
    };

    setRunning(true);
    setResult(null);
    try {
      const res = await api.post('/api/backtest/ai-comparison', {
        symbols: symbolList,
        strategy,
        start_date: startDate,
        end_date: endDate,
        starting_capital: startingCapital,
        ai_confidence_threshold: confidenceThreshold,
        ai_lookback_bars: lookbackBars,
        run_in_background: false
      });
      if (res.data?.result) {
        setResult(res.data.result);
        toast.success('AI comparison complete');
      } else if (res.data?.job_id) {
        toast.success('Backtest started in background');
        onJobStarted?.();
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Backtest failed');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="ai-comparison-tab">
      {/* AI Status Banner */}
      <div className={`p-3 rounded-lg border ${aiStatus?.ai_available 
        ? 'bg-emerald-500/10 border-emerald-500/30' 
        : 'bg-amber-500/10 border-amber-500/30'}`}>
        <div className="flex items-center gap-2 text-sm">
          {aiStatus?.ai_available ? (
            <>
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-emerald-300">AI Model Ready</span>
              <span className="text-slate-400 ml-2">
                {aiStatus.model_version} &middot; {(aiStatus.model_accuracy * 100).toFixed(1)}% accuracy &middot; {aiStatus.feature_count} features
              </span>
            </>
          ) : (
            <>
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span className="text-amber-300">No AI model trained. Train the time-series model first.</span>
            </>
          )}
        </div>
      </div>

      {/* Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Symbols (comma-separated)</label>
            <input
              data-testid="ai-comparison-symbols"
              value={symbols}
              onChange={e => setSymbols(e.target.value)}
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
              placeholder="AAPL, MSFT, NVDA..."
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Start Date</label>
              <input
                data-testid="ai-comparison-start-date"
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">End Date</label>
              <input
                data-testid="ai-comparison-end-date"
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Strategy</label>
            <select
              data-testid="ai-comparison-strategy"
              onChange={e => {
                const s = allStrategies.find(s => s.name === e.target.value);
                if (s) setSelectedStrategy({
                  name: s.name,
                  setup_type: s.setup_type || 'orb',
                  stop_pct: s.default_stop || 2.0,
                  target_pct: s.default_target || 4.0,
                  max_bars_to_hold: 20,
                  position_size_pct: 10.0,
                  min_tqs_score: 0,
                  use_trailing_stop: false,
                  trailing_stop_pct: 1.0
                });
              }}
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
            >
              <option value="">Default (ORB, 2% stop / 4% target)</option>
              {allStrategies.map(s => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>
        
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">
              AI Confidence Threshold: {confidenceThreshold.toFixed(2)}
            </label>
            <input
              data-testid="ai-comparison-threshold"
              type="range"
              min="0"
              max="0.5"
              step="0.01"
              value={confidenceThreshold}
              onChange={e => setConfidenceThreshold(parseFloat(e.target.value))}
              className="w-full accent-cyan-500"
            />
            <div className="flex justify-between text-[10px] text-slate-500">
              <span>0.0 (any "up")</span>
              <span>0.5 (high conf.)</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Lookback Bars</label>
              <input
                data-testid="ai-comparison-lookback"
                type="number"
                value={lookbackBars}
                onChange={e => setLookbackBars(parseInt(e.target.value) || 50)}
                min={20}
                max={200}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Starting Capital</label>
              <input
                data-testid="ai-comparison-capital"
                type="number"
                value={startingCapital}
                onChange={e => setStartingCapital(parseInt(e.target.value) || 100000)}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
          </div>
          <button
            data-testid="run-ai-comparison-btn"
            onClick={runComparison}
            disabled={running || !aiStatus?.ai_available}
            className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm
              bg-gradient-to-r from-cyan-600 to-blue-600 text-white hover:from-cyan-500 hover:to-blue-500
              disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {running ? 'Running AI Comparison...' : 'Run AI vs Setup Comparison'}
          </button>
        </div>
      </div>

      {/* Results */}
      {result && <AIComparisonResults result={result} />}
    </div>
  );
};


// ============================================================================
// AI Comparison Results Display
// ============================================================================

const MetricCard = ({ label, value, subtext, positive, testId }) => (
  <div className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/40" data-testid={testId}>
    <div className="text-[11px] text-slate-400 mb-1">{label}</div>
    <div className={`text-lg font-bold ${
      positive === true ? 'text-emerald-400' : positive === false ? 'text-red-400' : 'text-white'
    }`}>
      {value}
    </div>
    {subtext && <div className="text-[10px] text-slate-500 mt-0.5">{subtext}</div>}
  </div>
);

const ModeColumn = ({ title, color, data, testId }) => {
  if (!data || !data.total_trades) return (
    <div className={`flex-1 p-4 rounded-lg border border-${color}-500/20 bg-${color}-500/5`} data-testid={testId}>
      <h4 className={`text-sm font-semibold text-${color}-400 mb-3`}>{title}</h4>
      <div className="text-xs text-slate-500">No trades generated</div>
    </div>
  );
  
  return (
    <div className={`flex-1 p-4 rounded-lg border`} style={{
      borderColor: `var(--color-${color}, rgba(100,150,200,0.2))`,
      background: `rgba(100,150,200,0.03)`
    }} data-testid={testId}>
      <h4 className="text-sm font-semibold mb-3" style={{color: color === 'slate' ? '#94a3b8' : color === 'cyan' ? '#22d3ee' : '#a78bfa'}}>{title}</h4>
      <div className="space-y-2 text-xs">
        <div className="flex justify-between"><span className="text-slate-400">Trades</span><span className="text-white font-mono">{data.total_trades}</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Win Rate</span><span className={data.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}>{data.win_rate}%</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Total P&L</span><span className={data.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>${data.total_pnl?.toLocaleString()}</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Avg P&L</span><span className="text-white font-mono">${data.avg_pnl?.toFixed(2)}</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Profit Factor</span><span className="text-white font-mono">{data.profit_factor}</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Sharpe</span><span className="text-white font-mono">{data.sharpe_ratio}</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Max DD</span><span className="text-red-400">{data.max_drawdown_pct}%</span></div>
        <div className="flex justify-between"><span className="text-slate-400">Avg R</span><span className="text-white font-mono">{data.avg_r}</span></div>
      </div>
    </div>
  );
};

const AIComparisonResults = ({ result }) => {
  const [showSymbols, setShowSymbols] = useState(false);
  
  const improvement = result.ai_win_rate_improvement;
  const isPositive = improvement > 0;

  return (
    <div className="space-y-4" data-testid="ai-comparison-results">
      {/* Headline */}
      <div className={`p-4 rounded-lg border ${isPositive ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
        <div className="flex items-start gap-3">
          {isPositive ? (
            <TrendingUp className="w-5 h-5 text-emerald-400 mt-0.5 flex-shrink-0" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" />
          )}
          <div>
            <p className={`text-sm font-medium ${isPositive ? 'text-emerald-300' : 'text-amber-300'}`}>
              {result.recommendation}
            </p>
            <p className="text-xs text-slate-400 mt-1">
              {result.symbols?.length} symbols &middot; {result.strategy_name} &middot; {result.date_range} &middot; {result.duration_seconds?.toFixed(1)}s
            </p>
          </div>
        </div>
      </div>

      {/* Key Comparison Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard 
          testId="metric-win-rate-delta"
          label="Win Rate Delta"
          value={`${improvement > 0 ? '+' : ''}${improvement?.toFixed(1)}%`}
          subtext="AI+Setup vs Setup-only"
          positive={improvement > 0}
        />
        <MetricCard
          testId="metric-pnl-delta"
          label="P&L Impact"
          value={`${result.ai_pnl_improvement > 0 ? '+' : ''}$${result.ai_pnl_improvement?.toLocaleString()}`}
          subtext="Additional profit from AI"
          positive={result.ai_pnl_improvement > 0}
        />
        <MetricCard
          testId="metric-filter-rate"
          label="AI Filter Rate"
          value={`${result.ai_filter_rate}%`}
          subtext={`${result.ai_trades_filtered} trades blocked`}
        />
        <MetricCard
          testId="metric-sharpe-delta"
          label="Sharpe Delta"
          value={`${result.ai_sharpe_improvement > 0 ? '+' : ''}${result.ai_sharpe_improvement?.toFixed(3)}`}
          subtext="Risk-adjusted improvement"
          positive={result.ai_sharpe_improvement > 0}
        />
      </div>

      {/* Three-way Comparison */}
      <div className="flex flex-col md:flex-row gap-3">
        <ModeColumn title="Setup-Only" color="slate" data={result.setup_only} testId="mode-setup-only" />
        <ModeColumn title="AI + Setup" color="cyan" data={result.ai_filtered} testId="mode-ai-filtered" />
        <ModeColumn title="AI-Only" color="violet" data={result.ai_only} testId="mode-ai-only" />
      </div>

      {/* Per-Symbol Breakdown */}
      {result.symbol_results?.length > 0 && (
        <div>
          <button
            data-testid="toggle-symbol-breakdown"
            onClick={() => setShowSymbols(!showSymbols)}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            {showSymbols ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            Per-Symbol Breakdown ({result.symbol_results.length} symbols)
          </button>
          
          {showSymbols && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-xs" data-testid="symbol-breakdown-table">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-700/50">
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-right py-2 px-2" colSpan="3">Setup-Only</th>
                    <th className="text-right py-2 px-2" colSpan="3">AI+Setup</th>
                    <th className="text-right py-2 px-2" colSpan="3">AI-Only</th>
                  </tr>
                  <tr className="text-[10px] text-slate-500 border-b border-slate-700/30">
                    <th></th>
                    <th className="text-right px-2">Trades</th><th className="text-right px-2">WR</th><th className="text-right px-2">P&L</th>
                    <th className="text-right px-2">Trades</th><th className="text-right px-2">WR</th><th className="text-right px-2">P&L</th>
                    <th className="text-right px-2">Trades</th><th className="text-right px-2">WR</th><th className="text-right px-2">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.symbol_results.map(s => (
                    <tr key={s.symbol} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                      <td className="py-1.5 px-2 text-white font-mono font-medium">{s.symbol}</td>
                      <td className="text-right px-2 text-slate-300">{s.setup_only?.trades}</td>
                      <td className="text-right px-2">{s.setup_only?.win_rate}%</td>
                      <td className={`text-right px-2 ${s.setup_only?.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${s.setup_only?.pnl}</td>
                      <td className="text-right px-2 text-slate-300">{s.ai_filtered?.trades}</td>
                      <td className="text-right px-2">{s.ai_filtered?.win_rate}%</td>
                      <td className={`text-right px-2 ${s.ai_filtered?.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${s.ai_filtered?.pnl}</td>
                      <td className="text-right px-2 text-slate-300">{s.ai_only?.trades}</td>
                      <td className="text-right px-2">{s.ai_only?.win_rate}%</td>
                      <td className={`text-right px-2 ${s.ai_only?.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${s.ai_only?.pnl}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// Results Tab
// ============================================================================

const ResultsTab = ({ jobs, recentResults, onRefresh, onSelectResult }) => {
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
              <JobRow key={job.id} job={job} onSelect={job.status === 'completed' ? () => onSelectResult(job.result) : undefined} />
            ))}
          </div>
        </div>
      )}

      {/* Recent Results */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <h4 className="text-xs text-slate-400 mb-3">Recent Results (Click to view details)</h4>
        {recentResults.length > 0 ? (
          <div className="space-y-2">
            {recentResults.map(result => (
              <ResultRow key={result.id} result={result} onClick={() => onSelectResult(result)} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500 text-center py-4">No results yet. Run a backtest to see results here.</p>
        )}
      </div>
    </div>
  );
};

const JobRow = ({ job, onSelect }) => {
  const statusColors = {
    pending: 'text-yellow-400',
    running: 'text-cyan-400',
    completed: 'text-emerald-400',
    failed: 'text-red-400'
  };

  return (
    <div 
      className={`flex items-center justify-between p-2 bg-slate-900/50 rounded-lg ${onSelect ? 'cursor-pointer hover:bg-slate-800/50' : ''}`}
      onClick={onSelect}
    >
      <div>
        <div className="text-sm text-white">{job.job_type}</div>
        <div className="text-xs text-slate-500">{job.progress_message || job.id}</div>
      </div>
      <div className="flex items-center gap-3">
        {job.status === 'running' && (
          <div className="text-xs text-cyan-400">{Math.round(job.progress || 0)}%</div>
        )}
        <span className={`text-xs ${statusColors[job.status]}`}>{job.status}</span>
        {onSelect && <ChevronRight className="w-4 h-4 text-slate-500" />}
      </div>
    </div>
  );
};

const ResultRow = ({ result, onClick }) => {
  const typeLabels = {
    'mbt_': { label: 'Multi-Strategy', color: 'text-purple-400', bg: 'bg-purple-500/20' },
    'wf_': { label: 'Walk-Forward', color: 'text-emerald-400', bg: 'bg-emerald-500/20' },
    'mc_': { label: 'Monte Carlo', color: 'text-orange-400', bg: 'bg-orange-500/20' }
  };

  const type = Object.entries(typeLabels).find(([prefix]) => result.id?.startsWith(prefix));
  
  return (
    <div 
      className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg cursor-pointer hover:bg-slate-800/50 transition-colors"
      onClick={onClick}
    >
      <div className="flex-1">
        <div className="text-sm text-white font-medium">{result.name || result.strategy_name || result.id}</div>
        <div className="flex items-center gap-2 text-xs mt-1">
          {type && <span className={`${type[1].color} ${type[1].bg} px-2 py-0.5 rounded`}>{type[1].label}</span>}
          <span className="text-slate-500">{result.created_at?.split('T')[0]}</span>
          {result.combined_total_trades && (
            <span className="text-slate-400">{result.combined_total_trades} trades</span>
          )}
          {result.combined_win_rate && (
            <span className={result.combined_win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}>
              {result.combined_win_rate.toFixed(1)}% win
            </span>
          )}
        </div>
      </div>
      <ChevronRight className="w-5 h-5 text-slate-500" />
    </div>
  );
};

// ============================================================================
// Result Detail Modal
// ============================================================================

const ResultDetailModal = ({ result, onClose }) => {
  if (!result) return null;

  const isMultiStrategy = result.id?.startsWith('mbt_');
  const isWalkForward = result.id?.startsWith('wf_');
  const isMonteCarlo = result.id?.startsWith('mc_');

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div 
        className="bg-slate-900 rounded-xl border border-slate-700 max-w-4xl w-full max-h-[90vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-white">{result.name || result.strategy_name || 'Backtest Result'}</h2>
            <p className="text-xs text-slate-400">{result.id} • {result.created_at?.split('T')[0]}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-800 rounded-lg">
            <XCircle className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {isMultiStrategy && <MultiStrategyResultDetail result={result} />}
          {isWalkForward && <WalkForwardResultDetail result={result} />}
          {isMonteCarlo && <MonteCarloResultDetail result={result} />}
          {!isMultiStrategy && !isWalkForward && !isMonteCarlo && <GenericResultDetail result={result} />}
        </div>
      </div>
    </div>
  );
};

const MultiStrategyResultDetail = ({ result }) => (
  <div className="space-y-4">
    {/* Combined Metrics */}
    <div className="grid grid-cols-4 gap-3">
      <MetricBox label="Total Trades" value={result.combined_total_trades} />
      <MetricBox label="Win Rate" value={`${result.combined_win_rate?.toFixed(1)}%`} positive={result.combined_win_rate >= 50} />
      <MetricBox label="Total P&L" value={`$${result.combined_total_pnl?.toFixed(0)}`} positive={result.combined_total_pnl >= 0} />
      <MetricBox label="Profit Factor" value={result.combined_profit_factor?.toFixed(2)} positive={result.combined_profit_factor >= 1.5} />
    </div>

    {/* Per-Strategy Results */}
    {result.strategy_results?.length > 0 && (
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-2">Strategy Comparison</h4>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700">
                <th className="text-left py-2 px-2">Strategy</th>
                <th className="text-right py-2 px-2">Trades</th>
                <th className="text-right py-2 px-2">Win Rate</th>
                <th className="text-right py-2 px-2">P&L</th>
                <th className="text-right py-2 px-2">PF</th>
                <th className="text-right py-2 px-2">Sharpe</th>
                <th className="text-right py-2 px-2">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {result.strategy_results.map((sr, i) => (
                <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/30">
                  <td className="py-2 px-2 text-white">{sr.strategy_name}</td>
                  <td className="py-2 px-2 text-right text-slate-300">{sr.total_trades}</td>
                  <td className={`py-2 px-2 text-right ${sr.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {sr.win_rate?.toFixed(1)}%
                  </td>
                  <td className={`py-2 px-2 text-right ${sr.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    ${sr.total_pnl?.toFixed(0)}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300">{sr.profit_factor?.toFixed(2)}</td>
                  <td className="py-2 px-2 text-right text-slate-300">{sr.sharpe_ratio?.toFixed(2)}</td>
                  <td className="py-2 px-2 text-right text-red-400">{sr.max_drawdown_pct?.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )}

    {/* Correlation Matrix */}
    {result.correlation_matrix && Object.keys(result.correlation_matrix).length > 0 && (
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-2">Strategy Correlations</h4>
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(result.correlation_matrix).map(([pair, corr]) => (
            <div key={pair} className="flex items-center justify-between p-2 bg-slate-800/50 rounded">
              <span className="text-xs text-slate-400">{pair.replace('_vs_', ' vs ')}</span>
              <span className={`text-xs font-medium ${
                Math.abs(corr) > 0.7 ? 'text-red-400' : 
                Math.abs(corr) > 0.4 ? 'text-yellow-400' : 'text-emerald-400'
              }`}>
                {corr.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500 mt-1">Low correlation between strategies = better diversification</p>
      </div>
    )}
  </div>
);

const WalkForwardResultDetail = ({ result }) => (
  <div className="space-y-4">
    {/* Efficiency Summary */}
    <div className={`p-4 rounded-lg border ${
      result.is_robust ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'
    }`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-lg font-semibold text-white">
            Efficiency Ratio: {result.efficiency_ratio?.toFixed(1)}%
          </div>
          <div className={`text-sm ${result.is_robust ? 'text-emerald-400' : 'text-red-400'}`}>
            {result.is_robust ? 'Strategy is Robust' : 'Strategy May Be Overfit'}
          </div>
        </div>
        {result.is_robust ? (
          <CheckCircle2 className="w-8 h-8 text-emerald-400" />
        ) : (
          <AlertTriangle className="w-8 h-8 text-red-400" />
        )}
      </div>
      <p className="text-xs text-slate-400 mt-2">{result.recommendation}</p>
    </div>

    {/* Metrics Comparison */}
    <div className="grid grid-cols-2 gap-4">
      <div className="bg-slate-800/50 rounded-lg p-3">
        <h4 className="text-xs text-slate-400 mb-2">In-Sample (Training)</h4>
        <div className="text-xl font-bold text-white">{result.in_sample_win_rate?.toFixed(1)}%</div>
        <div className="text-xs text-slate-500">Win Rate</div>
      </div>
      <div className="bg-slate-800/50 rounded-lg p-3">
        <h4 className="text-xs text-slate-400 mb-2">Out-of-Sample (Testing)</h4>
        <div className="text-xl font-bold text-white">{result.out_of_sample_win_rate?.toFixed(1)}%</div>
        <div className="text-xs text-slate-500">Win Rate</div>
      </div>
    </div>

    {/* Period Details */}
    {result.periods?.length > 0 && (
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-2">Period Details ({result.total_periods} periods)</h4>
        <div className="max-h-48 overflow-y-auto space-y-1">
          {result.periods.map((p, i) => (
            <div key={i} className="flex items-center justify-between p-2 bg-slate-800/30 rounded text-xs">
              <span className="text-slate-400">Period {p.period}</span>
              <span className="text-slate-500">{p.in_sample_trades} → {p.out_sample_trades} trades</span>
              <span className={p.out_sample_win_rate >= p.in_sample_win_rate * 0.7 ? 'text-emerald-400' : 'text-red-400'}>
                {p.in_sample_win_rate}% → {p.out_sample_win_rate}%
              </span>
            </div>
          ))}
        </div>
      </div>
    )}
  </div>
);

const MonteCarloResultDetail = ({ result }) => (
  <div className="space-y-4">
    {/* Risk Assessment */}
    <div className={`p-4 rounded-lg border ${
      result.risk_assessment === 'LOW' ? 'bg-emerald-500/10 border-emerald-500/30' :
      result.risk_assessment === 'MEDIUM' ? 'bg-yellow-500/10 border-yellow-500/30' :
      result.risk_assessment === 'HIGH' ? 'bg-orange-500/10 border-orange-500/30' :
      'bg-red-500/10 border-red-500/30'
    }`}>
      <div className="text-lg font-semibold text-white">
        Risk Assessment: {result.risk_assessment}
      </div>
      <p className="text-xs text-slate-400 mt-1">{result.recommendation}</p>
    </div>

    {/* Key Metrics */}
    <div className="grid grid-cols-3 gap-3">
      <MetricBox label="Prob. of Profit" value={`${result.probability_of_profit?.toFixed(1)}%`} positive={result.probability_of_profit >= 70} />
      <MetricBox label="Prob. of Ruin" value={`${result.probability_of_ruin?.toFixed(1)}%`} positive={result.probability_of_ruin < 5} />
      <MetricBox label="Expected Max DD" value={`${result.expected_max_drawdown?.toFixed(1)}%`} positive={result.expected_max_drawdown < 20} />
    </div>

    {/* Distributions */}
    <div className="grid grid-cols-2 gap-4">
      <div className="bg-slate-800/50 rounded-lg p-3">
        <h4 className="text-xs text-slate-400 mb-2">P&L Distribution</h4>
        {result.pnl_distribution && Object.entries(result.pnl_distribution).map(([pct, val]) => (
          <div key={pct} className="flex justify-between text-xs py-1">
            <span className="text-slate-500">{pct}th percentile</span>
            <span className={val >= 0 ? 'text-emerald-400' : 'text-red-400'}>${val?.toFixed(0)}</span>
          </div>
        ))}
      </div>
      <div className="bg-slate-800/50 rounded-lg p-3">
        <h4 className="text-xs text-slate-400 mb-2">Drawdown Distribution</h4>
        {result.drawdown_distribution && Object.entries(result.drawdown_distribution).map(([pct, val]) => (
          <div key={pct} className="flex justify-between text-xs py-1">
            <span className="text-slate-500">{pct}th percentile</span>
            <span className="text-red-400">{val?.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>

    {/* Original vs Simulated */}
    <div className="bg-slate-800/50 rounded-lg p-3">
      <h4 className="text-xs text-slate-400 mb-2">Original Backtest vs Monte Carlo</h4>
      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <span className="text-slate-500">Original P&L</span>
          <div className={`font-medium ${result.original_total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            ${result.original_total_pnl?.toFixed(0)}
          </div>
        </div>
        <div>
          <span className="text-slate-500">Original Max DD</span>
          <div className="font-medium text-red-400">{result.original_max_drawdown?.toFixed(1)}%</div>
        </div>
        <div>
          <span className="text-slate-500">Worst Case DD (95th)</span>
          <div className="font-medium text-red-400">{result.worst_case_drawdown?.toFixed(1)}%</div>
        </div>
      </div>
    </div>
  </div>
);

const GenericResultDetail = ({ result }) => (
  <div>
    <pre className="text-xs text-slate-400 bg-slate-800/50 p-4 rounded-lg overflow-auto max-h-96">
      {JSON.stringify(result, null, 2)}
    </pre>
  </div>
);

export default AdvancedBacktestPanel;

// ============================================================================
// Full AI Simulation Tab
// ============================================================================

const FullAISimTab = ({ onJobStarted, setLoading, loading }) => {
  const [config, setConfig] = useState({
    universe: 'sp500',
    custom_symbols: '',
    starting_capital: 100000,
    max_position_pct: 10,
    max_open_positions: 5,
    use_ai_agents: true,
    bar_size: '1 day',
    start_date: '',
    end_date: '',
    min_adv: 100000,
    min_price: 5,
    max_price: 500,
  });
  const [simJobs, setSimJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [jobDetail, setJobDetail] = useState(null);
  const [pollInterval, setPollInterval] = useState(null);
  const [detailView, setDetailView] = useState('summary'); // summary | trades | decisions
  const [trades, setTrades] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Fetch existing simulation jobs
  const fetchSimJobs = useCallback(async () => {
    try {
      const { data } = await api.get('/api/backtest/full-ai-simulation/jobs?limit=20');
      if (data.success) {
        setSimJobs(data.jobs || []);
      }
    } catch (err) {
      // silent
    }
  }, []);

  useEffect(() => {
    fetchSimJobs();
  }, [fetchSimJobs]);

  // Poll running job status
  useEffect(() => {
    if (!pollInterval) return;
    const timer = setInterval(async () => {
      if (selectedJob) {
        try {
          const { data } = await api.get(`/api/backtest/full-ai-simulation/status/${selectedJob}`);
          if (data.success) {
            setJobDetail(data.job);
            if (data.job.status === 'completed' || data.job.status === 'failed') {
              clearInterval(timer);
              setPollInterval(null);
              fetchSimJobs();
              if (data.job.status === 'completed') fetchDetailData(selectedJob);
            }
          }
        } catch (err) {
          // silent
        }
      }
    }, pollInterval);
    return () => clearInterval(timer);
  }, [pollInterval, selectedJob, fetchSimJobs]);

  const fetchDetailData = async (jobId) => {
    setLoadingDetail(true);
    try {
      const [summaryRes, tradesRes, decisionsRes] = await Promise.all([
        api.get(`/api/backtest/full-ai-simulation/summary/${jobId}`),
        api.get(`/api/backtest/full-ai-simulation/trades/${jobId}?limit=100`),
        api.get(`/api/backtest/full-ai-simulation/decisions/${jobId}?limit=100`),
      ]);
      if (summaryRes.data?.success) setSummary(summaryRes.data.summary);
      if (tradesRes.data?.success) setTrades(tradesRes.data.trades || []);
      if (decisionsRes.data?.success) setDecisions(decisionsRes.data.decisions || []);
    } catch (err) {
      console.error('Failed to load detail data:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const startSimulation = async () => {
    setLoading(true);
    try {
      const payload = {
        ...config,
        custom_symbols: config.universe === 'custom' 
          ? config.custom_symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) 
          : [],
      };
      if (!payload.start_date) delete payload.start_date;
      if (!payload.end_date) delete payload.end_date;
      
      const { data } = await api.post('/api/backtest/full-ai-simulation', payload);
      if (data.success) {
        toast.success(`Full AI simulation started! Job: ${data.job_id}`);
        setSelectedJob(data.job_id);
        setJobDetail({ status: 'running', ...data.config });
        setPollInterval(3000);
        setSummary(null); setTrades([]); setDecisions([]);
        onJobStarted?.();
        fetchSimJobs();
      } else {
        toast.error(data.message || 'Failed to start simulation');
      }
    } catch (err) {
      toast.error('Failed to start simulation: ' + (err?.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  const viewJobDetail = async (jobId) => {
    setSelectedJob(jobId);
    setSummary(null); setTrades([]); setDecisions([]);
    setDetailView('summary');
    try {
      const { data } = await api.get(`/api/backtest/full-ai-simulation/status/${jobId}`);
      if (data.success) {
        setJobDetail(data.job);
        if (data.job.status === 'running') {
          setPollInterval(3000);
        } else if (data.job.status === 'completed') {
          fetchDetailData(jobId);
        }
      }
    } catch (err) {
      toast.error('Failed to load job status');
    }
  };

  const winRate = jobDetail ? (jobDetail.win_rate > 1 ? jobDetail.win_rate : (jobDetail.win_rate || 0) * 100) : 0;

  return (
    <div className="space-y-4" data-testid="full-ai-sim-tab">
      {/* Config Panel */}
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-3 mb-2">
          <Brain className="w-5 h-5 text-purple-400" />
          <h3 className="text-lg font-semibold text-slate-100">Full AI Pipeline Simulation</h3>
        </div>
        <p className="text-sm text-slate-400 leading-relaxed">
          Replays the complete SentCom bot on historical data. Uses all AI agents (Debate, Risk, Institutional, Time-Series) 
          to make trade decisions on each bar. More realistic than strategy backtests but compute-intensive.
        </p>

        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Stock Universe</label>
            <select 
              data-testid="sim-universe-select"
              value={config.universe}
              onChange={e => setConfig(p => ({ ...p, universe: e.target.value }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            >
              <option value="sp500">S&P 500</option>
              <option value="nasdaq100">NASDAQ 100</option>
              <option value="all">All US Stocks</option>
              <option value="custom">Custom List</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Starting Capital</label>
            <input 
              data-testid="sim-capital-input"
              type="number" 
              value={config.starting_capital}
              onChange={e => setConfig(p => ({ ...p, starting_capital: Number(e.target.value) }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Max Position %</label>
            <input 
              data-testid="sim-max-position-input"
              type="number" 
              value={config.max_position_pct}
              onChange={e => setConfig(p => ({ ...p, max_position_pct: Number(e.target.value) }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Max Open Positions</label>
            <input 
              data-testid="sim-max-positions-input"
              type="number" 
              value={config.max_open_positions}
              onChange={e => setConfig(p => ({ ...p, max_open_positions: Number(e.target.value) }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Bar Size</label>
            <select 
              data-testid="sim-bar-size-select"
              value={config.bar_size}
              onChange={e => setConfig(p => ({ ...p, bar_size: e.target.value }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            >
              <option value="1 day">Daily</option>
              <option value="1 hour">Hourly</option>
              <option value="15 mins">15 Minutes</option>
              <option value="5 mins">5 Minutes</option>
              <option value="1 min">1 Minute</option>
            </select>
          </div>
          <div className="flex items-center gap-3 pt-5">
            <label className="relative inline-flex items-center cursor-pointer">
              <input 
                data-testid="sim-ai-agents-toggle"
                type="checkbox" 
                checked={config.use_ai_agents}
                onChange={e => setConfig(p => ({ ...p, use_ai_agents: e.target.checked }))}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-500"></div>
              <span className="ml-2 text-xs text-slate-300">AI Agents</span>
            </label>
          </div>
        </div>

        {config.universe === 'custom' && (
          <div>
            <label className="block text-xs text-slate-400 mb-1">Custom Symbols (comma-separated)</label>
            <input 
              data-testid="sim-custom-symbols-input"
              type="text" 
              value={config.custom_symbols}
              onChange={e => setConfig(p => ({ ...p, custom_symbols: e.target.value }))}
              placeholder="AAPL, MSFT, GOOGL, NVDA, TSLA"
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Start Date (optional, default: 6mo ago)</label>
            <input 
              data-testid="sim-start-date-input"
              type="date" 
              value={config.start_date}
              onChange={e => setConfig(p => ({ ...p, start_date: e.target.value }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">End Date (optional, default: yesterday)</label>
            <input 
              data-testid="sim-end-date-input"
              type="date" 
              value={config.end_date}
              onChange={e => setConfig(p => ({ ...p, end_date: e.target.value }))}
              className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
            />
          </div>
        </div>

        <details className="group">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1">
            <Settings className="w-3 h-3" />
            <span>Advanced Filters</span>
            <ChevronDown className="w-3 h-3 group-open:rotate-180 transition-transform" />
          </summary>
          <div className="grid grid-cols-3 gap-4 mt-3 pt-3 border-t border-slate-700/30">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Min ADV</label>
              <input type="number" value={config.min_adv}
                onChange={e => setConfig(p => ({ ...p, min_adv: Number(e.target.value) }))}
                className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Min Price</label>
              <input type="number" value={config.min_price}
                onChange={e => setConfig(p => ({ ...p, min_price: Number(e.target.value) }))}
                className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Max Price</label>
              <input type="number" value={config.max_price}
                onChange={e => setConfig(p => ({ ...p, max_price: Number(e.target.value) }))}
                className="w-full bg-slate-900/60 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200"
              />
            </div>
          </div>
        </details>

        <button
          data-testid="start-full-sim-button"
          onClick={startSimulation}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 bg-purple-600/80 hover:bg-purple-600 text-white py-3 rounded-lg font-medium transition-all disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Start Full AI Simulation
        </button>
      </div>

      {/* Job Status & Results */}
      {jobDetail && (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium text-slate-200">
              Simulation: {selectedJob?.substring(0, 16)}...
            </h4>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              jobDetail.status === 'running' ? 'bg-cyan-500/20 text-cyan-400' :
              jobDetail.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' :
              jobDetail.status === 'failed' ? 'bg-red-500/20 text-red-400' :
              'bg-slate-500/20 text-slate-400'
            }`}>
              {jobDetail.status}
            </span>
          </div>

          {/* Progress bar for running jobs */}
          {jobDetail.status === 'running' && (
            <div>
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Progress: {jobDetail.symbols_processed || 0}/{jobDetail.symbols_total || jobDetail.total_symbols || '?'} symbols</span>
                <span>{jobDetail.current_date || ''}</span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-2">
                <div 
                  className="bg-purple-500 h-2 rounded-full transition-all" 
                  style={{ width: `${Math.min(100, (jobDetail.progress || (jobDetail.symbols_total ? (jobDetail.symbols_processed / jobDetail.symbols_total * 100) : 0)))}%` }}
                />
              </div>
            </div>
          )}

          {/* Summary Stats Row */}
          {(jobDetail.status === 'completed' || jobDetail.total_trades > 0) && (
            <div className="grid grid-cols-4 gap-3 text-center">
              <div className="bg-slate-900/40 rounded-lg p-2">
                <div className="text-xs text-slate-500">Trades</div>
                <div className="font-medium text-slate-200">{jobDetail.total_trades || 0}</div>
              </div>
              <div className="bg-slate-900/40 rounded-lg p-2">
                <div className="text-xs text-slate-500">Win Rate</div>
                <div className={`font-medium ${winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {winRate.toFixed(1)}%
                </div>
              </div>
              <div className="bg-slate-900/40 rounded-lg p-2">
                <div className="text-xs text-slate-500">P&L</div>
                <div className={`font-medium ${(jobDetail.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  ${(jobDetail.total_pnl || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>
              <div className="bg-slate-900/40 rounded-lg p-2">
                <div className="text-xs text-slate-500">Max DD</div>
                <div className="font-medium text-red-400">
                  {(jobDetail.max_drawdown || 0).toFixed(1)}%
                </div>
              </div>
            </div>
          )}

          {jobDetail.error_message && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-300">
              {jobDetail.error_message}
            </div>
          )}

          {/* Detail Tabs for completed jobs */}
          {jobDetail.status === 'completed' && (
            <>
              <div className="flex items-center gap-1 border-b border-slate-700/50 pb-0">
                {[
                  { id: 'summary', label: 'Summary', icon: PieChart },
                  { id: 'trades', label: `Trades (${trades.length})`, icon: TrendingUp },
                  { id: 'decisions', label: `AI Decisions (${decisions.length})`, icon: Brain },
                ].map(t => (
                  <button
                    key={t.id}
                    data-testid={`sim-detail-tab-${t.id}`}
                    onClick={() => setDetailView(t.id)}
                    className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-all ${
                      detailView === t.id
                        ? 'border-purple-400 text-purple-300'
                        : 'border-transparent text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    <t.icon className="w-3.5 h-3.5" />
                    {t.label}
                  </button>
                ))}
                {loadingDetail && <Loader2 className="w-3.5 h-3.5 text-purple-400 animate-spin ml-auto" />}
              </div>

              {/* Summary View */}
              {detailView === 'summary' && summary && (
                <div className="space-y-4" data-testid="sim-summary-view">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatCard label="Winners" value={summary.winners} color="emerald" />
                    <StatCard label="Losers" value={summary.losers} color="red" />
                    <StatCard label="Avg Win" value={`$${(summary.avg_win || 0).toFixed(0)}`} color="emerald" />
                    <StatCard label="Avg Loss" value={`$${(summary.avg_loss || 0).toFixed(0)}`} color="red" />
                    <StatCard label="Profit Factor" value={(summary.profit_factor || 0).toFixed(2)} color={summary.profit_factor >= 1 ? 'emerald' : 'red'} />
                    <StatCard label="Total Decisions" value={summary.total_decisions} color="purple" />
                  </div>

                  {/* Symbols Breakdown */}
                  {summary.symbols_breakdown && Object.keys(summary.symbols_breakdown).length > 0 && (
                    <div>
                      <h5 className="text-xs font-medium text-slate-400 mb-2">Per-Symbol Breakdown</h5>
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-slate-500 border-b border-slate-700/50">
                              <th className="text-left py-1.5 px-2">Symbol</th>
                              <th className="text-right py-1.5 px-2">Trades</th>
                              <th className="text-right py-1.5 px-2">Wins</th>
                              <th className="text-right py-1.5 px-2">Win Rate</th>
                              <th className="text-right py-1.5 px-2">P&L</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(summary.symbols_breakdown)
                              .sort((a, b) => b[1].pnl - a[1].pnl)
                              .map(([sym, d]) => (
                                <tr key={sym} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                  <td className="py-1.5 px-2 font-mono text-slate-200">{sym}</td>
                                  <td className="py-1.5 px-2 text-right text-slate-300">{d.trades}</td>
                                  <td className="py-1.5 px-2 text-right text-slate-300">{d.wins}</td>
                                  <td className="py-1.5 px-2 text-right text-slate-300">
                                    {d.trades ? (d.wins / d.trades * 100).toFixed(0) : 0}%
                                  </td>
                                  <td className={`py-1.5 px-2 text-right font-medium ${d.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    ${d.pnl.toFixed(0)}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Trades View */}
              {detailView === 'trades' && (
                <div className="space-y-2" data-testid="sim-trades-view">
                  {trades.length === 0 && !loadingDetail && (
                    <p className="text-xs text-slate-500 text-center py-4">No trades recorded</p>
                  )}
                  <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-slate-800">
                        <tr className="text-slate-500 border-b border-slate-700/50">
                          <th className="text-left py-1.5 px-2">Symbol</th>
                          <th className="text-left py-1.5 px-2">Dir</th>
                          <th className="text-left py-1.5 px-2">Setup</th>
                          <th className="text-right py-1.5 px-2">Entry</th>
                          <th className="text-right py-1.5 px-2">Exit</th>
                          <th className="text-right py-1.5 px-2">Shares</th>
                          <th className="text-right py-1.5 px-2">P&L</th>
                          <th className="text-right py-1.5 px-2">P&L %</th>
                          <th className="text-left py-1.5 px-2">Exit Reason</th>
                          <th className="text-left py-1.5 px-2">AI Rec</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map((t, i) => (
                          <tr key={t.id || i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td className="py-1.5 px-2 font-mono text-slate-200">{t.symbol}</td>
                            <td className="py-1.5 px-2">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                t.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                              }`}>{t.direction}</span>
                            </td>
                            <td className="py-1.5 px-2 text-slate-400">{t.setup_type}</td>
                            <td className="py-1.5 px-2 text-right text-slate-300">${(t.entry_price || 0).toFixed(2)}</td>
                            <td className="py-1.5 px-2 text-right text-slate-300">${(t.exit_price || 0).toFixed(2)}</td>
                            <td className="py-1.5 px-2 text-right text-slate-300">{t.shares}</td>
                            <td className={`py-1.5 px-2 text-right font-medium ${(t.realized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              ${(t.realized_pnl || 0).toFixed(2)}
                            </td>
                            <td className={`py-1.5 px-2 text-right ${(t.realized_pnl_pct || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {(t.realized_pnl_pct || 0).toFixed(2)}%
                            </td>
                            <td className="py-1.5 px-2 text-slate-500 max-w-[100px] truncate">{t.exit_reason}</td>
                            <td className="py-1.5 px-2">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                t.ai_consultation?.recommendation === 'proceed' ? 'bg-emerald-500/20 text-emerald-400' :
                                t.ai_consultation?.recommendation === 'skip' ? 'bg-amber-500/20 text-amber-400' :
                                'bg-slate-500/20 text-slate-400'
                              }`}>{t.ai_consultation?.recommendation || '-'}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Decisions View */}
              {detailView === 'decisions' && (
                <div className="space-y-2" data-testid="sim-decisions-view">
                  {decisions.length === 0 && !loadingDetail && (
                    <p className="text-xs text-slate-500 text-center py-4">No AI decisions recorded</p>
                  )}
                  <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-slate-800">
                        <tr className="text-slate-500 border-b border-slate-700/50">
                          <th className="text-left py-1.5 px-2">Date</th>
                          <th className="text-left py-1.5 px-2">Symbol</th>
                          <th className="text-left py-1.5 px-2">Signal</th>
                          <th className="text-left py-1.5 px-2">Dir</th>
                          <th className="text-right py-1.5 px-2">Strength</th>
                          <th className="text-left py-1.5 px-2">AI Rec</th>
                          <th className="text-right py-1.5 px-2">Conf</th>
                          <th className="text-left py-1.5 px-2">TS Dir</th>
                          <th className="text-right py-1.5 px-2">P(up)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {decisions.map((d, i) => {
                          const ts = d.ai_decision?.agents?.timeseries;
                          return (
                            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                              <td className="py-1.5 px-2 text-slate-400">{d.date ? new Date(d.date).toLocaleDateString() : '-'}</td>
                              <td className="py-1.5 px-2 font-mono text-slate-200">{d.symbol}</td>
                              <td className="py-1.5 px-2 text-slate-300">{d.signal?.type}</td>
                              <td className="py-1.5 px-2">
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                  d.signal?.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                                }`}>{d.signal?.direction}</span>
                              </td>
                              <td className="py-1.5 px-2 text-right text-slate-300">{d.signal?.strength || '-'}</td>
                              <td className="py-1.5 px-2">
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                  d.ai_decision?.recommendation === 'proceed' ? 'bg-emerald-500/20 text-emerald-400' :
                                  d.ai_decision?.recommendation === 'skip' ? 'bg-amber-500/20 text-amber-400' :
                                  'bg-slate-500/20 text-slate-400'
                                }`}>{d.ai_decision?.recommendation || '-'}</span>
                              </td>
                              <td className="py-1.5 px-2 text-right text-slate-300">{(d.ai_decision?.confidence || 0).toFixed(2)}</td>
                              <td className="py-1.5 px-2 text-slate-300">{ts?.direction || '-'}</td>
                              <td className="py-1.5 px-2 text-right text-slate-300">{ts ? (ts.probability_up * 100).toFixed(1) + '%' : '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Past Jobs */}
      {simJobs.length > 0 && (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-3">
          <h4 className="text-sm font-medium text-slate-200 flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            Past Simulations
          </h4>
          <div className="space-y-2">
            {simJobs.map(job => {
              const jid = job.id || job.job_id;
              const jWinRate = job.win_rate > 1 ? job.win_rate : (job.win_rate || 0) * 100;
              return (
                <button
                  key={jid}
                  data-testid={`sim-job-${jid}`}
                  onClick={() => viewJobDetail(jid)}
                  className={`w-full text-left p-3 rounded-lg border transition-all ${
                    selectedJob === jid
                      ? 'bg-purple-500/10 border-purple-500/30'
                      : 'bg-slate-900/30 border-slate-700/30 hover:border-slate-600/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-300 font-mono">{jid?.substring(0, 20)}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      job.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' :
                      job.status === 'running' ? 'bg-cyan-500/20 text-cyan-400' :
                      job.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {job.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 mt-1 text-[11px] text-slate-500">
                    <span>{job.config?.universe || job.universe || 'sp500'}</span>
                    <span>{job.total_trades || 0} trades</span>
                    {jWinRate > 0 && <span className={jWinRate >= 50 ? 'text-emerald-500' : 'text-red-500'}>{jWinRate.toFixed(0)}% WR</span>}
                    {job.total_pnl != null && (
                      <span className={job.total_pnl >= 0 ? 'text-emerald-500' : 'text-red-500'}>
                        ${job.total_pnl.toFixed(0)}
                      </span>
                    )}
                    {job.started_at && <span>{new Date(job.started_at).toLocaleDateString()}</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// Small stat card helper for Full AI Sim summary
const StatCard = ({ label, value, color = 'slate' }) => (
  <div className="bg-slate-900/40 rounded-lg p-2 text-center">
    <div className="text-xs text-slate-500">{label}</div>
    <div className={`font-medium text-${color}-400`}>{value}</div>
  </div>
);
