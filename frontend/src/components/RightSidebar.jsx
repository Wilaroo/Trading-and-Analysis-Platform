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
  ChevronLeft,
  ChevronRight,
  Star,
  Target,
  Clock,
  Plus,
  X,
  Sun,
  Moon,
  LineChart
} from 'lucide-react';
import MarketIntelPanel from './MarketIntelPanel';
import api from '../utils/api';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// ===================== CALENDAR-STYLE EARNINGS WIDGET =====================
const EarningsWidget = ({ onTickerSelect }) => {
  const [calendarData, setCalendarData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [selectedDate, setSelectedDate] = useState(null);
  const [weekOffset, setWeekOffset] = useState(0);

  const fetchEarnings = useCallback(async () => {
    setLoading(true);
    try {
      // Calculate date range based on week offset
      const startDate = new Date();
      startDate.setDate(startDate.getDate() + (weekOffset * 7));
      const endDate = new Date(startDate);
      endDate.setDate(endDate.getDate() + 13); // 2 weeks
      
      const res = await api.get('/api/earnings/calendar', {
        params: {
          start_date: startDate.toISOString().split('T')[0],
          end_date: endDate.toISOString().split('T')[0]
        }
      });
      setCalendarData(res.data);
      
      // Auto-select today if in range
      const today = new Date().toISOString().split('T')[0];
      const hasToday = res.data?.grouped_by_date?.some(g => g.date === today);
      if (hasToday && !selectedDate) {
        setSelectedDate(today);
      }
    } catch (err) {
      console.error('Failed to load earnings:', err);
    } finally {
      setLoading(false);
    }
  }, [weekOffset, selectedDate]);

  useEffect(() => {
    fetchEarnings();
  }, [fetchEarnings]);

  const getWeekDays = () => {
    const days = [];
    const startDate = new Date();
    startDate.setDate(startDate.getDate() + (weekOffset * 7));
    
    // Get Monday of the week
    const day = startDate.getDay();
    const diff = startDate.getDate() - day + (day === 0 ? -6 : 1);
    startDate.setDate(diff);
    
    for (let i = 0; i < 5; i++) { // Mon-Fri
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      days.push({
        date: d.toISOString().split('T')[0],
        dayName: d.toLocaleDateString('en-US', { weekday: 'short' }),
        dayNum: d.getDate(),
        isToday: d.toISOString().split('T')[0] === new Date().toISOString().split('T')[0]
      });
    }
    return days;
  };

  const getEarningsForDate = (date) => {
    if (!calendarData?.grouped_by_date) return null;
    return calendarData.grouped_by_date.find(g => g.date === date);
  };

  const selectedDayData = selectedDate ? getEarningsForDate(selectedDate) : null;
  const weekDays = getWeekDays();

  return (
    <div className="bg-zinc-900/60 rounded-lg border border-zinc-700/50" data-testid="earnings-widget">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-medium text-zinc-200">Earnings Calendar</span>
          <span className="text-xs text-zinc-500">({calendarData?.total_count || 0})</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
      </button>
      
      {expanded && (
        <div className="px-3 pb-3">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
            </div>
          ) : (
            <>
              {/* Week Navigation */}
              <div className="flex items-center justify-between mb-2">
                <button 
                  onClick={() => setWeekOffset(prev => prev - 1)}
                  className="p-1 hover:bg-zinc-800 rounded"
                >
                  <ChevronLeft className="w-4 h-4 text-zinc-400" />
                </button>
                <span className="text-xs text-zinc-400">
                  {weekOffset === 0 ? 'This Week' : weekOffset > 0 ? `+${weekOffset} weeks` : `${weekOffset} weeks`}
                </span>
                <button 
                  onClick={() => setWeekOffset(prev => prev + 1)}
                  className="p-1 hover:bg-zinc-800 rounded"
                >
                  <ChevronRight className="w-4 h-4 text-zinc-400" />
                </button>
              </div>

              {/* Calendar Days */}
              <div className="grid grid-cols-5 gap-1 mb-3">
                {weekDays.map((day) => {
                  const dayData = getEarningsForDate(day.date);
                  const hasEarnings = dayData && dayData.count > 0;
                  const isSelected = selectedDate === day.date;
                  
                  return (
                    <button
                      key={day.date}
                      onClick={() => setSelectedDate(day.date)}
                      className={`p-1.5 rounded text-center transition-all ${
                        isSelected 
                          ? 'bg-amber-500/20 border border-amber-500/50' 
                          : day.isToday 
                            ? 'bg-cyan-500/10 border border-cyan-500/30'
                            : 'bg-zinc-800/50 border border-transparent hover:border-zinc-600'
                      }`}
                    >
                      <div className="text-[9px] text-zinc-500">{day.dayName}</div>
                      <div className={`text-sm font-bold ${isSelected ? 'text-amber-400' : day.isToday ? 'text-cyan-400' : 'text-white'}`}>
                        {day.dayNum}
                      </div>
                      {hasEarnings && (
                        <div className="flex justify-center gap-0.5 mt-0.5">
                          <div className="w-1.5 h-1.5 rounded-full bg-amber-500" title={`${dayData.count} earnings`} />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Selected Day Earnings */}
              {selectedDate && (
                <div className="space-y-1.5 max-h-32 overflow-y-auto">
                  {!selectedDayData || selectedDayData.count === 0 ? (
                    <p className="text-xs text-zinc-500 text-center py-2">No earnings on this day</p>
                  ) : (
                    <>
                      {/* Before Open */}
                      {selectedDayData.before_open?.length > 0 && (
                        <div className="space-y-1">
                          <div className="flex items-center gap-1 text-[10px] text-amber-400">
                            <Sun className="w-3 h-3" />
                            Before Open
                          </div>
                          {selectedDayData.before_open.map((item, idx) => (
                            <EarningsItem key={idx} item={item} onTickerSelect={onTickerSelect} />
                          ))}
                        </div>
                      )}
                      {/* After Close */}
                      {selectedDayData.after_close?.length > 0 && (
                        <div className="space-y-1">
                          <div className="flex items-center gap-1 text-[10px] text-violet-400">
                            <Moon className="w-3 h-3" />
                            After Close
                          </div>
                          {selectedDayData.after_close.map((item, idx) => (
                            <EarningsItem key={idx} item={item} onTickerSelect={onTickerSelect} />
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

const EarningsItem = ({ item, onTickerSelect }) => (
  <div
    onClick={() => onTickerSelect?.(item.symbol)}
    className="flex items-center justify-between p-1.5 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors"
  >
    <div className="flex items-center gap-2">
      <span className="text-xs font-bold text-white">{item.symbol}</span>
      <span className="text-[10px] text-zinc-500 truncate max-w-[80px]">{item.company_name}</span>
    </div>
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-zinc-400">{item.expected_move?.percent?.toFixed(1)}%</span>
    </div>
  </div>
);

// ===================== SMART WATCHLIST WIDGET =====================
const WatchlistWidget = ({ onTickerSelect, onViewChart, wsWatchlist = [] }) => {
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

  // Sync from WebSocket data when available
  useEffect(() => {
    if (wsWatchlist && wsWatchlist.length >= 0) {
      setWatchlist(wsWatchlist);
      setLoading(false);
    }
  }, [wsWatchlist]);

  // Initial fetch only (WebSocket handles updates)
  useEffect(() => {
    if (!wsWatchlist || wsWatchlist.length === 0) {
      fetchWatchlist();
    }
    // No polling - WebSocket handles real-time updates
  }, []); // Only on mount

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
                    {/* Chart button */}
                    <button
                      onClick={(e) => { e.stopPropagation(); onViewChart?.(item.symbol); }}
                      className="p-0.5 opacity-0 group-hover:opacity-100 hover:bg-cyan-500/20 rounded transition-all"
                      title="View Chart"
                    >
                      <LineChart className="w-3 h-3 text-zinc-500 hover:text-cyan-400" />
                    </button>
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
const ScannerResultsWidget = ({ onTickerSelect, onViewChart, wsAlerts = [], wsStatus = null }) => {
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

  // Sync from WebSocket data when available
  useEffect(() => {
    if (wsAlerts && wsAlerts.length >= 0) {
      setAlerts(wsAlerts);
      setLoading(false);
    }
  }, [wsAlerts]);
  
  useEffect(() => {
    if (wsStatus) {
      setStats(wsStatus);
    }
  }, [wsStatus]);

  // Initial fetch only (WebSocket handles updates)
  useEffect(() => {
    if (!wsAlerts || wsAlerts.length === 0) {
      fetchAlerts();
    }
    // No polling - WebSocket handles real-time updates
  }, []); // Only on mount

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
                className="p-2 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors group"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    {getDirectionIcon(alert.direction)}
                    <span className="text-xs font-bold text-white">{alert.symbol}</span>
                    <span className={`text-[9px] px-1 py-0.5 rounded border ${getPriorityColor(alert.priority)}`}>
                      {alert.priority?.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    {alert.tape_confirmation && (
                      <span className="text-[9px] text-emerald-400">✓ TAPE</span>
                    )}
                    {/* Chart button */}
                    <button
                      onClick={(e) => { e.stopPropagation(); onViewChart?.(alert.symbol); }}
                      className="p-0.5 opacity-0 group-hover:opacity-100 hover:bg-cyan-500/20 rounded transition-all"
                      title="View Chart"
                    >
                      <LineChart className="w-3 h-3 text-zinc-500 hover:text-cyan-400" />
                    </button>
                  </div>
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
const RightSidebar = ({ 
  onTickerSelect, 
  onViewChart,
  // WebSocket-pushed data
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = []
}) => {
  return (
    <div className="space-y-3" data-testid="right-sidebar">
      {/* Market Intelligence Panel */}
      <MarketIntelPanel onTickerSelect={onTickerSelect} onViewChart={onViewChart} />
      
      {/* Scanner Results */}
      <ScannerResultsWidget 
        onTickerSelect={onTickerSelect} 
        onViewChart={onViewChart}
        wsAlerts={wsScannerAlerts}
        wsStatus={wsScannerStatus}
      />
      
      {/* Earnings Widget */}
      <EarningsWidget onTickerSelect={onTickerSelect} onViewChart={onViewChart} />
      
      {/* Watchlist Widget */}
      <WatchlistWidget 
        onTickerSelect={onTickerSelect} 
        onViewChart={onViewChart}
        wsWatchlist={wsSmartWatchlist}
      />
    </div>
  );
};

export default RightSidebar;
