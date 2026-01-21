import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Search,
  BookOpen,
  Bell,
  Briefcase,
  Newspaper,
  Settings,
  TrendingUp,
  TrendingDown,
  Clock,
  Calendar,
  Target,
  Activity,
  RefreshCw,
  ChevronRight,
  Eye,
  Zap,
  BarChart3,
  LineChart,
  X,
  Plus,
  Trash2
} from 'lucide-react';
import {
  LineChart as ReLineChart,
  Line,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  AreaChart,
  Area
} from 'recharts';
import './App.css';

// Use relative URL for API calls - Kubernetes ingress routes /api to backend
const API_URL = '';

// API client
const api = axios.create({
  baseURL: API_URL,
  timeout: 30000
});

// ===================== COMPONENTS =====================

// Sidebar Navigation
const Sidebar = ({ activeTab, setActiveTab }) => {
  const navItems = [
    { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { id: 'scanner', icon: Search, label: 'Scanner' },
    { id: 'strategies', icon: BookOpen, label: 'Strategies' },
    { id: 'watchlist', icon: Eye, label: 'Watchlist' },
    { id: 'portfolio', icon: Briefcase, label: 'Portfolio' },
    { id: 'alerts', icon: Bell, label: 'Alerts' },
    { id: 'newsletter', icon: Newspaper, label: 'Newsletter' },
  ];

  return (
    <aside className="w-16 lg:w-64 bg-paper border-r border-white/5 flex flex-col fixed h-screen z-50">
      {/* Logo */}
      <div className="p-4 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
            <Activity className="w-6 h-6 text-primary" />
          </div>
          <span className="hidden lg:block font-bold text-lg tracking-tight">TradeCommand</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-2 space-y-1">
        {navItems.map((item) => (
          <button
            key={item.id}
            data-testid={`nav-${item.id}`}
            onClick={() => setActiveTab(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg transition-all duration-200 ${
              activeTab === item.id
                ? 'bg-primary/10 text-primary border border-primary/30'
                : 'text-zinc-400 hover:bg-white/5 hover:text-white border border-transparent'
            }`}
          >
            <item.icon className="w-5 h-5 flex-shrink-0" />
            <span className="hidden lg:block text-sm font-medium">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-white/5">
        <button 
          data-testid="nav-settings"
          className="w-full flex items-center gap-3 px-3 py-2 text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <Settings className="w-5 h-5" />
          <span className="hidden lg:block text-sm">Settings</span>
        </button>
      </div>
    </aside>
  );
};

// Price Display Component
const PriceDisplay = ({ value, showArrow = true, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {showArrow && !isNeutral && (
        isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />
      )}
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

// Card Component
const Card = ({ children, className = '', onClick, hover = true }) => (
  <div 
    onClick={onClick}
    className={`bg-paper rounded-lg p-4 border border-white/10 ${
      hover ? 'transition-all duration-200 hover:border-primary/30' : ''
    } ${onClick ? 'cursor-pointer' : ''} ${className}`}
  >
    {children}
  </div>
);

// Loading Skeleton
const Skeleton = ({ className = '' }) => (
  <div className={`skeleton rounded ${className}`} />
);

// Market Overview Ticker
const TickerTape = ({ indices }) => {
  if (!indices || indices.length === 0) return null;
  
  return (
    <div className="bg-paper border-b border-white/5 py-2 overflow-hidden">
      <div className="flex gap-8 ticker-tape">
        {[...indices, ...indices].map((item, idx) => (
          <div key={idx} className="flex items-center gap-3 whitespace-nowrap">
            <span className="text-zinc-400 text-sm">{item.symbol}</span>
            <span className="font-mono-data text-white">${item.price?.toFixed(2)}</span>
            <PriceDisplay value={item.change_percent} className="text-sm" />
          </div>
        ))}
      </div>
    </div>
  );
};

// Stats Card
const StatsCard = ({ icon: Icon, label, value, change, loading }) => (
  <Card className="flex items-center gap-4">
    <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
      <Icon className="w-6 h-6 text-primary" />
    </div>
    <div className="flex-1">
      <p className="text-xs text-zinc-500 uppercase tracking-wider">{label}</p>
      {loading ? (
        <Skeleton className="h-7 w-24 mt-1" />
      ) : (
        <p className="text-2xl font-bold font-mono-data">{value}</p>
      )}
    </div>
    {change !== undefined && (
      <PriceDisplay value={change} />
    )}
  </Card>
);

// Alert Item
const AlertItem = ({ alert, onDismiss }) => (
  <motion.div
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
    className="glass-card rounded-lg p-4 flex items-start gap-4"
  >
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
      alert.score >= 70 ? 'bg-green-500/20' : alert.score >= 50 ? 'bg-yellow-500/20' : 'bg-blue-500/20'
    }`}>
      <Zap className={`w-5 h-5 ${
        alert.score >= 70 ? 'text-green-400' : alert.score >= 50 ? 'text-yellow-400' : 'text-blue-400'
      }`} />
    </div>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 mb-1">
        <span className="font-bold text-primary">{alert.symbol}</span>
        <span className="badge badge-info">{alert.strategy_id}</span>
      </div>
      <p className="text-sm text-zinc-400 truncate">{alert.strategy_name}</p>
      <p className="text-xs text-zinc-500 mt-1">{new Date(alert.timestamp).toLocaleTimeString()}</p>
    </div>
    <button onClick={onDismiss} className="text-zinc-500 hover:text-white transition-colors">
      <X className="w-4 h-4" />
    </button>
  </motion.div>
);

// Strategy Card
const StrategyCard = ({ strategy, onClick }) => {
  const categoryColors = {
    intraday: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    swing: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    investment: 'bg-green-500/20 text-green-400 border-green-500/30'
  };

  return (
    <Card onClick={onClick} className="group">
      <div className="flex items-start justify-between mb-3">
        <span className={`badge ${categoryColors[strategy.category]}`}>
          {strategy.category}
        </span>
        <span className="text-xs text-zinc-500 font-mono">{strategy.id}</span>
      </div>
      <h3 className="font-semibold mb-2 group-hover:text-primary transition-colors">
        {strategy.name}
      </h3>
      <div className="flex flex-wrap gap-1 mb-3">
        {strategy.indicators?.slice(0, 3).map((ind, idx) => (
          <span key={idx} className="text-xs bg-white/5 px-2 py-0.5 rounded text-zinc-400">
            {ind}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {strategy.timeframe}
        </span>
        <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
      </div>
    </Card>
  );
};

// Watchlist Item
const WatchlistItem = ({ item, rank }) => (
  <div className="flex items-center gap-4 py-3 border-b border-white/5 last:border-0">
    <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center font-bold text-primary text-sm">
      {rank}
    </div>
    <div className="flex-1">
      <div className="flex items-center gap-2">
        <span className="font-bold">{item.symbol}</span>
        <PriceDisplay value={item.change_percent} className="text-sm" />
      </div>
      <p className="text-xs text-zinc-500">
        {item.matched_strategies?.length || 0} strategies matched
      </p>
    </div>
    <div className="text-right">
      <div className="flex items-center gap-1">
        <div className="w-16 h-2 bg-white/10 rounded-full overflow-hidden">
          <div 
            className="h-full bg-primary rounded-full transition-all"
            style={{ width: `${item.score}%` }}
          />
        </div>
        <span className="font-mono-data text-sm text-primary">{item.score}</span>
      </div>
      <p className="text-xs text-zinc-500 mt-1">
        {item.criteria_met}/{item.total_criteria} criteria
      </p>
    </div>
  </div>
);

// ===================== PAGES =====================

// Dashboard Page
const DashboardPage = ({ data, loading, onRefresh }) => {
  const { stats, overview, alerts, watchlist } = data;

  // Sample chart data
  const chartData = [
    { time: '9:30', value: 100 },
    { time: '10:00', value: 102 },
    { time: '10:30', value: 101 },
    { time: '11:00', value: 105 },
    { time: '11:30', value: 103 },
    { time: '12:00', value: 107 },
    { time: '12:30', value: 106 },
    { time: '13:00', value: 110 },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <button 
          data-testid="refresh-dashboard"
          onClick={onRefresh}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard 
          icon={Briefcase}
          label="Portfolio Value"
          value={`$${stats?.portfolio_value?.toLocaleString() || '0'}`}
          change={stats?.portfolio_change}
          loading={loading}
        />
        <StatsCard 
          icon={Bell}
          label="Unread Alerts"
          value={stats?.unread_alerts || 0}
          loading={loading}
        />
        <StatsCard 
          icon={Eye}
          label="Watchlist"
          value={stats?.watchlist_count || 0}
          loading={loading}
        />
        <StatsCard 
          icon={Target}
          label="Active Strategies"
          value={stats?.strategies_count || 50}
          loading={loading}
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Portfolio Chart */}
        <Card className="lg:col-span-2" hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Market Performance</h2>
            <div className="flex gap-2">
              <button className="tab active">1D</button>
              <button className="tab">1W</button>
              <button className="tab">1M</button>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00E5FF" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#00E5FF" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis 
                  dataKey="time" 
                  stroke="#52525B" 
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis 
                  stroke="#52525B" 
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  domain={['dataMin - 2', 'dataMax + 2']}
                />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: '#0A0A0A', 
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px'
                  }}
                />
                <Area 
                  type="monotone" 
                  dataKey="value" 
                  stroke="#00E5FF" 
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorValue)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Recent Alerts */}
        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Recent Alerts</h2>
            <span className="badge badge-info">{alerts?.length || 0}</span>
          </div>
          <div className="space-y-3 max-h-64 overflow-y-auto">
            <AnimatePresence>
              {alerts?.slice(0, 5).map((alert, idx) => (
                <AlertItem key={idx} alert={alert} />
              ))}
            </AnimatePresence>
            {(!alerts || alerts.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-8">No recent alerts</p>
            )}
          </div>
        </Card>
      </div>

      {/* Bottom Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Movers */}
        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Top Movers</h2>
            <BarChart3 className="w-5 h-5 text-zinc-500" />
          </div>
          <div className="space-y-2">
            {overview?.top_movers?.map((mover, idx) => (
              <div key={idx} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <div className="flex items-center gap-3">
                  <span className="font-bold">{mover.symbol}</span>
                  <span className="font-mono-data text-zinc-400">${mover.price?.toFixed(2)}</span>
                </div>
                <PriceDisplay value={mover.change_percent} />
              </div>
            ))}
            {(!overview?.top_movers || overview.top_movers.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-4">Loading movers...</p>
            )}
          </div>
        </Card>

        {/* Watchlist Preview */}
        <Card hover={false}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Morning Watchlist</h2>
            <Eye className="w-5 h-5 text-zinc-500" />
          </div>
          <div className="space-y-1">
            {watchlist?.slice(0, 5).map((item, idx) => (
              <WatchlistItem key={idx} item={item} rank={idx + 1} />
            ))}
            {(!watchlist || watchlist.length === 0) && (
              <p className="text-zinc-500 text-sm text-center py-4">Generate watchlist to see picks</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

// Scanner Page
const ScannerPage = ({ onScan }) => {
  const [symbols, setSymbols] = useState('AAPL, MSFT, GOOGL, NVDA, TSLA, AMD');
  const [minScore, setMinScore] = useState(40);
  const [category, setCategory] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [presets, setPresets] = useState([]);

  useEffect(() => {
    loadPresets();
  }, []);

  const loadPresets = async () => {
    try {
      const res = await api.get('/api/scanner/presets');
      setPresets(res.data.presets);
    } catch (err) {
      console.error('Failed to load presets:', err);
    }
  };

  const runScan = async () => {
    setLoading(true);
    try {
      const symbolList = symbols.split(',').map(s => s.trim().toUpperCase());
      const res = await api.post('/api/scanner/scan', symbolList, {
        params: { category: category || undefined, min_score: minScore }
      });
      setResults(res.data.results);
    } catch (err) {
      console.error('Scan failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (preset) => {
    setSymbols(preset.symbols.join(', '));
    setMinScore(preset.min_score);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategy Scanner</h1>
          <p className="text-zinc-500 text-sm mt-1">Scan stocks against strategy criteria</p>
        </div>
      </div>

      {/* Controls */}
      <Card hover={false}>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-2">
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbols</label>
            <input
              data-testid="scanner-symbols-input"
              type="text"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="AAPL, MSFT, GOOGL..."
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Category</label>
            <select
              data-testid="scanner-category-select"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white focus:border-primary/50 focus:outline-none transition-colors"
            >
              <option value="">All Strategies</option>
              <option value="intraday">Intraday</option>
              <option value="swing">Swing</option>
              <option value="investment">Investment</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Min Score: {minScore}</label>
            <input
              data-testid="scanner-min-score-input"
              type="range"
              min="0"
              max="100"
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>

        {/* Presets */}
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
          {presets.map((preset, idx) => (
            <button
              key={idx}
              onClick={() => applyPreset(preset)}
              className="text-xs bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-full text-zinc-400 hover:text-white transition-colors"
            >
              {preset.name}
            </button>
          ))}
        </div>

        <button
          data-testid="run-scanner-btn"
          onClick={runScan}
          disabled={loading}
          className="btn-primary mt-4 w-full md:w-auto flex items-center justify-center gap-2"
        >
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? 'Scanning...' : 'Run Scanner'}
        </button>
      </Card>

      {/* Results */}
      {results.length > 0 && (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Scan Results ({results.length})</h2>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Score</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>Volume</th>
                  <th>Strategies</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result, idx) => (
                  <tr key={idx} data-testid={`scan-result-${result.symbol}`}>
                    <td className="font-bold text-primary">{result.symbol}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-2 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className={`h-full rounded-full ${
                              result.score >= 70 ? 'bg-green-400' : 
                              result.score >= 50 ? 'bg-yellow-400' : 'bg-blue-400'
                            }`}
                            style={{ width: `${result.score}%` }}
                          />
                        </div>
                        <span>{result.score}</span>
                      </div>
                    </td>
                    <td>${result.quote?.price?.toFixed(2)}</td>
                    <td><PriceDisplay value={result.quote?.change_percent} /></td>
                    <td>{(result.quote?.volume / 1000000).toFixed(2)}M</td>
                    <td>
                      <div className="flex gap-1">
                        {result.matched_strategies?.slice(0, 3).map((s, i) => (
                          <span key={i} className="badge badge-info">{s}</span>
                        ))}
                        {result.matched_strategies?.length > 3 && (
                          <span className="text-xs text-zinc-500">+{result.matched_strategies.length - 3}</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};

// Strategies Page
const StrategiesPage = () => {
  const [strategies, setStrategies] = useState([]);
  const [filter, setFilter] = useState('all');
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStrategies();
  }, [filter]);

  const loadStrategies = async () => {
    setLoading(true);
    try {
      const params = filter !== 'all' ? { category: filter } : {};
      const res = await api.get('/api/strategies', { params });
      setStrategies(res.data.strategies);
    } catch (err) {
      console.error('Failed to load strategies:', err);
    } finally {
      setLoading(false);
    }
  };

  const categoryCounts = {
    intraday: strategies.filter(s => s.category === 'intraday').length,
    swing: strategies.filter(s => s.category === 'swing').length,
    investment: strategies.filter(s => s.category === 'investment').length,
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Trading Strategies</h1>
          <p className="text-zinc-500 text-sm mt-1">50 strategies across 3 categories</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {['all', 'intraday', 'swing', 'investment'].map((cat) => (
          <button
            key={cat}
            data-testid={`filter-${cat}`}
            onClick={() => setFilter(cat)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
              filter === cat
                ? 'bg-primary text-black'
                : 'bg-white/5 text-zinc-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            {cat.charAt(0).toUpperCase() + cat.slice(1)}
            {cat !== 'all' && (
              <span className="ml-2 text-xs opacity-75">
                ({categoryCounts[cat] || 0})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Strategy Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {strategies.map((strategy) => (
          <StrategyCard
            key={strategy.id}
            strategy={strategy}
            onClick={() => setSelectedStrategy(strategy)}
          />
        ))}
      </div>

      {/* Strategy Detail Modal */}
      <AnimatePresence>
        {selectedStrategy && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setSelectedStrategy(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-paper border border-white/10 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-6">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <span className={`badge mb-2 ${
                      selectedStrategy.category === 'intraday' ? 'badge-info' :
                      selectedStrategy.category === 'swing' ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' :
                      'badge-success'
                    }`}>
                      {selectedStrategy.category}
                    </span>
                    <h2 className="text-xl font-bold">{selectedStrategy.name}</h2>
                    <p className="text-zinc-500 text-sm mt-1">{selectedStrategy.id}</p>
                  </div>
                  <button 
                    onClick={() => setSelectedStrategy(null)}
                    className="text-zinc-500 hover:text-white transition-colors"
                  >
                    <X className="w-6 h-6" />
                  </button>
                </div>

                <div className="space-y-6">
                  <div>
                    <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-3">Criteria</h3>
                    <ul className="space-y-2">
                      {selectedStrategy.criteria?.map((criterion, idx) => (
                        <li key={idx} className="flex items-start gap-3">
                          <div className="w-1.5 h-1.5 rounded-full bg-primary mt-2 flex-shrink-0" />
                          <span className="text-zinc-300">{criterion}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="flex gap-6 pt-4 border-t border-white/5">
                    <div>
                      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Timeframe</p>
                      <p className="font-medium">{selectedStrategy.timeframe}</p>
                    </div>
                    <div>
                      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">Indicators</p>
                      <div className="flex flex-wrap gap-1">
                        {selectedStrategy.indicators?.map((ind, idx) => (
                          <span key={idx} className="badge badge-info">{ind}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// Watchlist Page
const WatchlistPage = () => {
  const [watchlist, setWatchlist] = useState([]);
  const [aiInsight, setAiInsight] = useState('');
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadWatchlist();
  }, []);

  const loadWatchlist = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/watchlist');
      setWatchlist(res.data.watchlist);
    } catch (err) {
      console.error('Failed to load watchlist:', err);
    } finally {
      setLoading(false);
    }
  };

  const generateWatchlist = async () => {
    setGenerating(true);
    try {
      const res = await api.post('/api/watchlist/generate');
      setWatchlist(res.data.watchlist);
      setAiInsight(res.data.ai_insight);
    } catch (err) {
      console.error('Failed to generate watchlist:', err);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Morning Watchlist</h1>
          <p className="text-zinc-500 text-sm mt-1">AI-ranked top 10 picks based on strategy criteria</p>
        </div>
        <button
          data-testid="generate-watchlist-btn"
          onClick={generateWatchlist}
          disabled={generating}
          className="btn-primary flex items-center gap-2"
        >
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          {generating ? 'Generating...' : 'Generate Watchlist'}
        </button>
      </div>

      {/* AI Insight */}
      {aiInsight && (
        <Card className="bg-gradient-to-r from-primary/5 to-transparent border-primary/20" hover={false}>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center flex-shrink-0">
              <Zap className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-primary mb-1">AI Insight</h3>
              <p className="text-zinc-300 text-sm">{aiInsight}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Watchlist Table */}
      <Card hover={false}>
        {loading ? (
          <div className="space-y-4">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : watchlist.length > 0 ? (
          <div className="space-y-1">
            {watchlist.map((item, idx) => (
              <WatchlistItem key={idx} item={item} rank={idx + 1} />
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <Eye className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No watchlist generated yet</p>
            <p className="text-zinc-600 text-sm mt-1">Click "Generate Watchlist" to get AI-ranked picks</p>
          </div>
        )}
      </Card>
    </div>
  );
};

// Portfolio Page
const PortfolioPage = () => {
  const [portfolio, setPortfolio] = useState({ positions: [], summary: {} });
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newPosition, setNewPosition] = useState({ symbol: '', shares: '', avg_cost: '' });

  useEffect(() => {
    loadPortfolio();
  }, []);

  const loadPortfolio = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/portfolio');
      setPortfolio(res.data);
    } catch (err) {
      console.error('Failed to load portfolio:', err);
    } finally {
      setLoading(false);
    }
  };

  const addPosition = async () => {
    try {
      await api.post('/api/portfolio/add', null, {
        params: {
          symbol: newPosition.symbol.toUpperCase(),
          shares: parseFloat(newPosition.shares),
          avg_cost: parseFloat(newPosition.avg_cost)
        }
      });
      setShowAddModal(false);
      setNewPosition({ symbol: '', shares: '', avg_cost: '' });
      loadPortfolio();
    } catch (err) {
      console.error('Failed to add position:', err);
    }
  };

  const removePosition = async (symbol) => {
    try {
      await api.delete(`/api/portfolio/${symbol}`);
      loadPortfolio();
    } catch (err) {
      console.error('Failed to remove position:', err);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Portfolio</h1>
          <p className="text-zinc-500 text-sm mt-1">Track your positions and performance</p>
        </div>
        <button
          data-testid="add-position-btn"
          onClick={() => setShowAddModal(true)}
          className="btn-primary flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Add Position
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard 
          icon={Briefcase}
          label="Total Value"
          value={`$${portfolio.summary?.total_value?.toLocaleString() || '0'}`}
          loading={loading}
        />
        <StatsCard 
          icon={TrendingUp}
          label="Total Cost"
          value={`$${portfolio.summary?.total_cost?.toLocaleString() || '0'}`}
          loading={loading}
        />
        <StatsCard 
          icon={Activity}
          label="Total Gain/Loss"
          value={`$${portfolio.summary?.total_gain_loss?.toLocaleString() || '0'}`}
          change={portfolio.summary?.total_gain_loss_percent}
          loading={loading}
        />
        <StatsCard 
          icon={Target}
          label="Positions"
          value={portfolio.positions?.length || 0}
          loading={loading}
        />
      </div>

      {/* Positions Table */}
      <Card hover={false}>
        <h2 className="font-semibold mb-4">Positions</h2>
        {portfolio.positions?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Shares</th>
                  <th>Avg Cost</th>
                  <th>Current</th>
                  <th>Value</th>
                  <th>Gain/Loss</th>
                  <th>Today</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {portfolio.positions.map((pos, idx) => (
                  <tr key={idx} data-testid={`position-${pos.symbol}`}>
                    <td className="font-bold text-primary">{pos.symbol}</td>
                    <td>{pos.shares}</td>
                    <td>${pos.avg_cost?.toFixed(2)}</td>
                    <td>${pos.current_price?.toFixed(2)}</td>
                    <td>${pos.market_value?.toLocaleString()}</td>
                    <td>
                      <div className="flex flex-col">
                        <PriceDisplay value={pos.gain_loss_percent} />
                        <span className={`text-xs ${pos.gain_loss >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${pos.gain_loss?.toFixed(2)}
                        </span>
                      </div>
                    </td>
                    <td><PriceDisplay value={pos.change_today} /></td>
                    <td>
                      <button
                        onClick={() => removePosition(pos.symbol)}
                        className="text-zinc-500 hover:text-red-400 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12">
            <Briefcase className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No positions yet</p>
            <p className="text-zinc-600 text-sm mt-1">Add your first position to start tracking</p>
          </div>
        )}
      </Card>

      {/* Add Position Modal */}
      <AnimatePresence>
        {showAddModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setShowAddModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-paper border border-white/10 rounded-xl max-w-md w-full p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <h2 className="text-xl font-bold mb-6">Add Position</h2>
              <div className="space-y-4">
                <div>
                  <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbol</label>
                  <input
                    data-testid="add-position-symbol"
                    type="text"
                    value={newPosition.symbol}
                    onChange={(e) => setNewPosition({ ...newPosition, symbol: e.target.value })}
                    placeholder="AAPL"
                    className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Shares</label>
                  <input
                    data-testid="add-position-shares"
                    type="number"
                    value={newPosition.shares}
                    onChange={(e) => setNewPosition({ ...newPosition, shares: e.target.value })}
                    placeholder="100"
                    className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Avg Cost</label>
                  <input
                    data-testid="add-position-cost"
                    type="number"
                    step="0.01"
                    value={newPosition.avg_cost}
                    onChange={(e) => setNewPosition({ ...newPosition, avg_cost: e.target.value })}
                    placeholder="150.00"
                    className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                  />
                </div>
              </div>
              <div className="flex gap-3 mt-6">
                <button onClick={() => setShowAddModal(false)} className="btn-secondary flex-1">
                  Cancel
                </button>
                <button 
                  data-testid="confirm-add-position"
                  onClick={addPosition} 
                  className="btn-primary flex-1"
                >
                  Add Position
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// Alerts Page
const AlertsPage = () => {
  const [alerts, setAlerts] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadAlerts();
  }, []);

  const loadAlerts = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/alerts');
      setAlerts(res.data.alerts);
      setUnreadCount(res.data.unread_count);
    } catch (err) {
      console.error('Failed to load alerts:', err);
    } finally {
      setLoading(false);
    }
  };

  const generateAlerts = async () => {
    setGenerating(true);
    try {
      await api.post('/api/alerts/generate');
      loadAlerts();
    } catch (err) {
      console.error('Failed to generate alerts:', err);
    } finally {
      setGenerating(false);
    }
  };

  const clearAlerts = async () => {
    try {
      await api.delete('/api/alerts/clear');
      setAlerts([]);
      setUnreadCount(0);
    } catch (err) {
      console.error('Failed to clear alerts:', err);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Alert Center</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {unreadCount} unread alerts
          </p>
        </div>
        <div className="flex gap-2">
          <button
            data-testid="generate-alerts-btn"
            onClick={generateAlerts}
            disabled={generating}
            className="btn-primary flex items-center gap-2"
          >
            {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />}
            Generate Alerts
          </button>
          <button
            data-testid="clear-alerts-btn"
            onClick={clearAlerts}
            className="btn-secondary"
          >
            Clear All
          </button>
        </div>
      </div>

      {/* Alerts List */}
      <Card hover={false}>
        {loading ? (
          <div className="space-y-4">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : alerts.length > 0 ? (
          <div className="space-y-3">
            <AnimatePresence>
              {alerts.map((alert, idx) => (
                <AlertItem key={idx} alert={alert} />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <div className="text-center py-12">
            <Bell className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No alerts</p>
            <p className="text-zinc-600 text-sm mt-1">Click "Generate Alerts" to scan for strategy matches</p>
          </div>
        )}
      </Card>
    </div>
  );
};

// Newsletter Page
const NewsletterPage = () => {
  const [newsletter, setNewsletter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadNewsletter();
  }, []);

  const loadNewsletter = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/newsletter/latest');
      if (res.data && res.data.title) {
        setNewsletter(res.data);
      }
    } catch (err) {
      console.error('Failed to load newsletter:', err);
    } finally {
      setLoading(false);
    }
  };

  const generateNewsletter = async () => {
    setGenerating(true);
    try {
      const res = await api.post('/api/newsletter/generate');
      setNewsletter(res.data);
    } catch (err) {
      console.error('Failed to generate newsletter:', err);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Morning Newsletter</h1>
          <p className="text-zinc-500 text-sm mt-1">AI-generated daily market briefing</p>
        </div>
        <button
          data-testid="generate-newsletter-btn"
          onClick={generateNewsletter}
          disabled={generating}
          className="btn-primary flex items-center gap-2"
        >
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Newspaper className="w-4 h-4" />}
          {generating ? 'Generating...' : 'Generate Newsletter'}
        </button>
      </div>

      {loading ? (
        <Card hover={false}>
          <Skeleton className="h-8 w-3/4 mb-4" />
          <Skeleton className="h-4 w-full mb-2" />
          <Skeleton className="h-4 w-full mb-2" />
          <Skeleton className="h-4 w-2/3" />
        </Card>
      ) : newsletter ? (
        <div className="max-w-3xl mx-auto">
          {/* Newsletter Header */}
          <Card className="bg-paper/50 border-primary/20 mb-6" hover={false}>
            <div className="text-center py-8">
              <p className="text-xs text-primary uppercase tracking-widest mb-2">TradeCommand</p>
              <h2 className="text-3xl font-editorial font-bold mb-2">{newsletter.title}</h2>
              <p className="text-zinc-500 text-sm">
                <Calendar className="w-4 h-4 inline mr-1" />
                {new Date(newsletter.created_at).toLocaleDateString('en-US', { 
                  weekday: 'long', 
                  year: 'numeric', 
                  month: 'long', 
                  day: 'numeric' 
                })}
              </p>
            </div>
          </Card>

          {/* Market Indices */}
          {newsletter.indices && newsletter.indices.length > 0 && (
            <Card className="mb-6" hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Market Overview</h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                {newsletter.indices.map((idx, i) => (
                  <div key={i} className="text-center">
                    <p className="text-xs text-zinc-500 mb-1">{idx.symbol}</p>
                    <p className="font-mono-data text-lg">${idx.price?.toFixed(2)}</p>
                    <PriceDisplay value={idx.change_percent} className="text-sm justify-center" />
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Market Summary */}
          <Card className="mb-6" hover={false}>
            <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Market Summary</h3>
            <div className="font-editorial text-zinc-300 leading-relaxed whitespace-pre-line">
              {newsletter.market_summary}
            </div>
          </Card>

          {/* Top News */}
          {newsletter.top_news && newsletter.top_news.length > 0 && (
            <Card className="mb-6" hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Top Stories</h3>
              <div className="space-y-4">
                {newsletter.top_news.map((news, idx) => (
                  <div key={idx} className="border-b border-white/5 pb-4 last:border-0 last:pb-0">
                    <h4 className="font-semibold mb-1 hover:text-primary transition-colors cursor-pointer">
                      {news.title}
                    </h4>
                    <p className="text-sm text-zinc-400 mb-2">{news.summary}</p>
                    <div className="flex items-center gap-4 text-xs text-zinc-500">
                      <span>{news.source}</span>
                      {news.related_symbols?.length > 0 && (
                        <span className="flex gap-1">
                          {news.related_symbols.slice(0, 3).map((sym, i) => (
                            <span key={i} className="badge badge-info">{sym}</span>
                          ))}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Watchlist */}
          {newsletter.watchlist && newsletter.watchlist.length > 0 && (
            <Card className="mb-6" hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Today's Watchlist</h3>
              <div className="space-y-2">
                {newsletter.watchlist.slice(0, 5).map((item, idx) => (
                  <WatchlistItem key={idx} item={item} rank={idx + 1} />
                ))}
              </div>
            </Card>
          )}

          {/* Strategy Highlights */}
          {newsletter.strategy_highlights && newsletter.strategy_highlights.length > 0 && (
            <Card hover={false}>
              <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-4">Strategy Highlights</h3>
              <ul className="space-y-2">
                {newsletter.strategy_highlights.map((highlight, idx) => (
                  <li key={idx} className="flex items-start gap-3">
                    <Target className="w-4 h-4 text-primary mt-1 flex-shrink-0" />
                    <span className="text-zinc-300">{highlight}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      ) : (
        <Card hover={false}>
          <div className="text-center py-12">
            <Newspaper className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No newsletter available</p>
            <p className="text-zinc-600 text-sm mt-1">Click "Generate Newsletter" to create today's briefing</p>
          </div>
        </Card>
      )}
    </div>
  );
};

// ===================== MAIN APP =====================
function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [dashboardData, setDashboardData] = useState({
    stats: {},
    overview: {},
    alerts: [],
    watchlist: []
  });
  const [loading, setLoading] = useState(true);

  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, overviewRes, alertsRes, watchlistRes] = await Promise.all([
        api.get('/api/dashboard/stats'),
        api.get('/api/market/overview'),
        api.get('/api/alerts', { params: { unread_only: true } }),
        api.get('/api/watchlist')
      ]);
      
      setDashboardData({
        stats: statsRes.data,
        overview: overviewRes.data,
        alerts: alertsRes.data.alerts,
        watchlist: watchlistRes.data.watchlist
      });
    } catch (err) {
      console.error('Failed to load dashboard:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  const renderPage = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardPage data={dashboardData} loading={loading} onRefresh={loadDashboardData} />;
      case 'scanner':
        return <ScannerPage />;
      case 'strategies':
        return <StrategiesPage />;
      case 'watchlist':
        return <WatchlistPage />;
      case 'portfolio':
        return <PortfolioPage />;
      case 'alerts':
        return <AlertsPage />;
      case 'newsletter':
        return <NewsletterPage />;
      default:
        return <DashboardPage data={dashboardData} loading={loading} onRefresh={loadDashboardData} />;
    }
  };

  return (
    <div className="min-h-screen bg-background bg-gradient-radial">
      {/* Sidebar */}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Main Content */}
      <main className="ml-16 lg:ml-64 min-h-screen">
        {/* Ticker Tape */}
        <TickerTape indices={dashboardData.overview?.indices} />

        {/* Page Content */}
        <div className="p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
            >
              {renderPage()}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

export default App;
