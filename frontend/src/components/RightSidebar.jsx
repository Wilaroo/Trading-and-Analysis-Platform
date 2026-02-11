/**
 * RightSidebar - Contains Market Intel, Earnings, Watchlist, and Scanner Results
 * Displayed on the right side of the Command Center
 */
import React, { useState, useEffect, useCallback } from 'react';
import { 
  Calendar, 
  Eye, 
  Zap, 
  TrendingUp, 
  TrendingDown, 
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Star,
  Target,
  Clock,
  Plus,
  X
} from 'lucide-react';
import MarketIntelPanel from './MarketIntelPanel';
import api from '../utils/api';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// ===================== COMPACT EARNINGS WIDGET =====================
const EarningsWidget = ({ onTickerSelect }) => {
  const [earnings, setEarnings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);

  const fetchEarnings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/earnings/today');
      setEarnings(res.data.earnings || []);
    } catch (err) {
      console.error('Failed to load earnings:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEarnings();
    const interval = setInterval(fetchEarnings, 300000); // Refresh every 5 minutes
    return () => clearInterval(interval);
  }, [fetchEarnings]);

  const getRatingColor = (rating) => {
    if (!rating) return 'text-zinc-500';
    if (rating.startsWith('A')) return 'text-emerald-400';
    if (rating.startsWith('B')) return 'text-cyan-400';
    if (rating.startsWith('C')) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <div className="bg-zinc-900/60 rounded-lg border border-zinc-700/50" data-testid="earnings-widget">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-medium text-zinc-200">Earnings Today</span>
          <span className="text-xs text-zinc-500">({earnings.length})</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
      </button>
      
      {expanded && (
        <div className="px-3 pb-3 space-y-1.5 max-h-48 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
            </div>
          ) : earnings.length === 0 ? (
            <p className="text-xs text-zinc-500 text-center py-2">No earnings today</p>
          ) : (
            earnings.slice(0, 8).map((item, idx) => (
              <div
                key={idx}
                onClick={() => onTickerSelect?.(item.symbol)}
                className="flex items-center justify-between p-2 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-white">{item.symbol}</span>
                  <span className={`text-[10px] px-1 py-0.5 rounded ${
                    item.timing === 'BMO' ? 'bg-amber-500/20 text-amber-400' : 'bg-violet-500/20 text-violet-400'
                  }`}>
                    {item.timing || 'TBD'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {item.catalyst_score && (
                    <span className={`text-[10px] font-medium ${getRatingColor(item.rating)}`}>
                      {item.rating}
                    </span>
                  )}
                  <Clock className="w-3 h-3 text-zinc-500" />
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

// ===================== SMART WATCHLIST WIDGET =====================
const WatchlistWidget = ({ onTickerSelect }) => {
  const [watchlist, setWatchlist] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [stats, setStats] = useState(null);
  const [newSymbol, setNewSymbol] = useState('');
  const [showAddInput, setShowAddInput] = useState(false);

  const fetchWatchlist = useCallback(async () => {
    setLoading(true);
    try {
      // Use smart watchlist API
      const res = await api.get('/api/smart-watchlist');
      const items = res.data.watchlist || [];
      setWatchlist(items);
      setStats(res.data.stats);
      
      // Fetch quotes for symbols
      if (items.length > 0) {
        const symbols = items.map(w => w.symbol);
        try {
          const quotesRes = await api.post('/api/quotes/batch', symbols);
          const quotesMap = {};
          quotesRes.data.quotes?.forEach(q => { quotesMap[q.symbol] = q; });
          setQuotes(quotesMap);
        } catch (e) {
          console.log('Quote fetch failed, continuing without quotes');
        }
      }
    } catch (err) {
      console.error('Failed to load smart watchlist:', err);
      // Fallback to old watchlist
      try {
        const res = await api.get('/api/watchlist');
        const items = res.data.watchlist || [];
        setWatchlist(items.map(w => ({ ...w, source: 'legacy' })));
      } catch (e) {
        console.error('Fallback also failed:', e);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
    const interval = setInterval(fetchWatchlist, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, [fetchWatchlist]);

  const handleAddSymbol = async () => {
    if (!newSymbol.trim()) return;
    try {
      await api.post('/api/smart-watchlist/add', { symbol: newSymbol.toUpperCase() });
      setNewSymbol('');
      setShowAddInput(false);
      fetchWatchlist();
    } catch (err) {
      console.error('Failed to add symbol:', err);
    }
  };

  const handleRemoveSymbol = async (symbol, e) => {
    e.stopPropagation();
    try {
      await api.delete(`/api/smart-watchlist/${symbol}`);
      fetchWatchlist();
    } catch (err) {
      console.error('Failed to remove symbol:', err);
    }
  };

  const getSourceBadge = (item) => {
    if (item.is_sticky || item.source === 'manual') {
      return <span className="text-[9px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-400">PIN</span>;
    }
    if (item.source === 'scanner') {
      return <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-400">SCAN</span>;
    }
    return null;
  };

  const getTimeframeBadge = (tf) => {
    const colors = {
      scalp: 'bg-purple-500/20 text-purple-400',
      intraday: 'bg-cyan-500/20 text-cyan-400',
      swing: 'bg-emerald-500/20 text-emerald-400',
      position: 'bg-blue-500/20 text-blue-400'
    };
    return <span className={`text-[9px] px-1 py-0.5 rounded ${colors[tf] || 'bg-zinc-500/20 text-zinc-400'}`}>
      {tf?.toUpperCase() || 'DAY'}
    </span>;
  };

  return (
    <div className="bg-zinc-900/60 rounded-lg border border-zinc-700/50" data-testid="watchlist-widget">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-medium text-zinc-200">Smart Watchlist</span>
          <span className="text-xs text-zinc-500">
            ({watchlist.length}/{stats?.max_size || 50})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); setShowAddInput(!showAddInput); }}
            className="p-1 hover:bg-zinc-700 rounded transition-colors"
            title="Add symbol"
          >
            <Plus className="w-3 h-3 text-zinc-400" />
          </button>
          {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
        </div>
      </button>
      
      {/* Quick stats bar */}
      {expanded && stats && (
        <div className="px-3 pb-2 flex items-center gap-2 text-[10px] text-zinc-500">
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400"></span>
            {stats.manual} pinned
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            {stats.scanner} scanner
          </span>
        </div>
      )}

      {/* Add symbol input */}
      {showAddInput && (
        <div className="px-3 pb-2 flex items-center gap-2">
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleAddSymbol()}
            placeholder="SYMBOL"
            className="flex-1 px-2 py-1 text-xs bg-zinc-800 border border-zinc-700 rounded text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500"
            autoFocus
          />
          <button
            onClick={handleAddSymbol}
            className="px-2 py-1 text-xs bg-cyan-600 hover:bg-cyan-500 rounded text-white transition-colors"
          >
            Add
          </button>
        </div>
      )}
      
      {expanded && (
        <div className="px-3 pb-3 space-y-1.5 max-h-64 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
            </div>
          ) : watchlist.length === 0 ? (
            <p className="text-xs text-zinc-500 text-center py-2">No symbols - scanner will auto-populate</p>
          ) : (
            watchlist.slice(0, 20).map((item, idx) => {
              const quote = quotes[item.symbol];
              const changePercent = quote?.change_percent || 0;
              const isPositive = changePercent >= 0;
              
              return (
                <div
                  key={idx}
                  onClick={() => onTickerSelect?.(item.symbol)}
                  className="flex items-center justify-between p-2 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors group"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-white">{item.symbol}</span>
                    {getSourceBadge(item)}
                    {item.timeframe && getTimeframeBadge(item.timeframe)}
                    {quote?.price && (
                      <span className="text-[10px] text-zinc-400 font-mono">${quote.price.toFixed(2)}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {item.signal_count > 1 && (
                      <span className="text-[9px] text-zinc-500">{item.signal_count}x</span>
                    )}
                    <div className={`flex items-center gap-1 text-[10px] font-mono ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                      {isPositive ? '+' : ''}{changePercent.toFixed(2)}%
                    </div>
                    <button
                      onClick={(e) => handleRemoveSymbol(item.symbol, e)}
                      className="p-0.5 opacity-0 group-hover:opacity-100 hover:bg-zinc-700 rounded transition-all"
                      title="Remove"
                    >
                      <X className="w-3 h-3 text-zinc-500 hover:text-red-400" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};

// ===================== COMPACT SCANNER RESULTS WIDGET =====================
const ScannerResultsWidget = ({ onTickerSelect }) => {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [stats, setStats] = useState(null);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const [alertsRes, statusRes] = await Promise.all([
        fetch(`${API_URL}/api/live-scanner/alerts`).then(r => r.json()),
        fetch(`${API_URL}/api/live-scanner/status`).then(r => r.json())
      ]);
      setAlerts(alertsRes.alerts || []);
      setStats(statusRes);
    } catch (err) {
      console.error('Failed to load scanner results:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  const getPriorityColor = (priority) => {
    switch (priority) {
      case 'critical': return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'high': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'medium': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      default: return 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30';
    }
  };

  const getDirectionIcon = (direction) => {
    return direction === 'long' ? (
      <TrendingUp className="w-3 h-3 text-emerald-400" />
    ) : (
      <TrendingDown className="w-3 h-3 text-red-400" />
    );
  };

  return (
    <div className="bg-zinc-900/60 rounded-lg border border-zinc-700/50" data-testid="scanner-results-widget">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-emerald-400" />
          <span className="text-sm font-medium text-zinc-200">Scanner Alerts</span>
          <span className="text-xs text-zinc-500">({alerts.length})</span>
          {stats?.running && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
      </button>
      
      {expanded && (
        <div className="px-3 pb-3 space-y-1.5 max-h-64 overflow-y-auto">
          {/* Scanner Stats */}
          {stats && (
            <div className="flex items-center justify-between text-[10px] text-zinc-500 pb-2 border-b border-zinc-700/50 mb-2">
              <span>Scans: {stats.scan_count}</span>
              <span>Symbols: {stats.watchlist_size}</span>
              <span className={`px-1.5 py-0.5 rounded ${
                stats.market_regime === 'strong_uptrend' ? 'bg-emerald-500/20 text-emerald-400' :
                stats.market_regime === 'strong_downtrend' ? 'bg-red-500/20 text-red-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {stats.market_regime?.replace(/_/g, ' ')}
              </span>
            </div>
          )}
          
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
            </div>
          ) : alerts.length === 0 ? (
            <p className="text-xs text-zinc-500 text-center py-2">
              {stats?.time_window === 'closed' ? 'Market closed' : 'No alerts yet'}
            </p>
          ) : (
            alerts.slice(0, 10).map((alert, idx) => (
              <div
                key={idx}
                onClick={() => onTickerSelect?.(alert.symbol)}
                className="p-2 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    {getDirectionIcon(alert.direction)}
                    <span className="text-xs font-bold text-white">{alert.symbol}</span>
                    <span className={`text-[9px] px-1 py-0.5 rounded border ${getPriorityColor(alert.priority)}`}>
                      {alert.priority?.toUpperCase()}
                    </span>
                  </div>
                  {alert.tape_confirmation && (
                    <span className="text-[9px] text-emerald-400">✓ TAPE</span>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-zinc-400 truncate max-w-[70%]">
                    {alert.setup_type?.replace(/_/g, ' ')}
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">
                    ${alert.current_price?.toFixed(2)}
                  </span>
                </div>
                {alert.strategy_win_rate > 0 && (
                  <div className="text-[9px] text-zinc-500 mt-1">
                    Win Rate: <span className="text-zinc-300">{(alert.strategy_win_rate * 100).toFixed(0)}%</span>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

// ===================== MAIN RIGHT SIDEBAR COMPONENT =====================
const RightSidebar = ({ onTickerSelect }) => {
  return (
    <div className="space-y-3" data-testid="right-sidebar">
      {/* Market Intelligence Panel */}
      <MarketIntelPanel onTickerSelect={onTickerSelect} />
      
      {/* Scanner Results */}
      <ScannerResultsWidget onTickerSelect={onTickerSelect} />
      
      {/* Earnings Widget */}
      <EarningsWidget onTickerSelect={onTickerSelect} />
      
      {/* Watchlist Widget */}
      <WatchlistWidget onTickerSelect={onTickerSelect} />
    </div>
  );
};

export default RightSidebar;
