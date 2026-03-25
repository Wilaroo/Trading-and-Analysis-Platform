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
  LineChart,
  FlaskConical,
  MessageSquare
} from 'lucide-react';
import MarketIntelPanel from './MarketIntelPanel';
import QuickActionsMenu from './QuickActionsMenu';
import SimulatorControl from './SimulatorControl';
import api, { safeGet } from '../utils/api';

// ===================== CALENDAR-STYLE EARNINGS WIDGET =====================
const EarningsWidget = ({ onTickerSelect }) => {
  const [calendarData, setCalendarData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [weekOffset, setWeekOffset] = useState(0);

  const fetchEarnings = useCallback(async () => {
    setLoading(true);
    try {
      const startDate = new Date();
      startDate.setDate(startDate.getDate() + (weekOffset * 7));
      const endDate = new Date(startDate);
      endDate.setDate(endDate.getDate() + 6);
      
      const res = await api.get('/api/earnings/calendar', {
        params: {
          start_date: startDate.toISOString().split('T')[0],
          end_date: endDate.toISOString().split('T')[0]
        }
      });
      setCalendarData(res.data);
    } catch (err) {
      console.error('Failed to load earnings:', err);
    } finally {
      setLoading(false);
    }
  }, [weekOffset]);

  useEffect(() => {
    fetchEarnings();
  }, [fetchEarnings]);

  const getWeekDays = () => {
    const days = [];
    const startDate = new Date();
    startDate.setDate(startDate.getDate() + (weekOffset * 7));
    const day = startDate.getDay();
    const diff = startDate.getDate() - day + (day === 0 ? -6 : 1);
    startDate.setDate(diff);
    for (let i = 0; i < 5; i++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      days.push({
        date: d.toISOString().split('T')[0],
        dayName: d.toLocaleDateString('en-US', { weekday: 'short' }),
        dayNum: d.getDate(),
        month: d.toLocaleDateString('en-US', { month: 'short' }),
        isToday: d.toISOString().split('T')[0] === new Date().toISOString().split('T')[0]
      });
    }
    return days;
  };

  const getEarningsForDate = (date) => {
    if (!calendarData?.grouped_by_date) return null;
    return calendarData.grouped_by_date.find(g => g.date === date);
  };

  const weekDays = getWeekDays();

  // Find max count across the week for heat scaling
  const maxCount = weekDays.reduce((max, day) => {
    const d = getEarningsForDate(day.date);
    return Math.max(max, d?.count || 0);
  }, 0);

  // Heat color based on density — returns inline styles for gradient columns
  const getHeatStyle = (count) => {
    if (!count || count === 0) return { bg: 'rgba(39,39,42,0.2)', border: 'rgba(63,63,70,0.3)', text: 'text-zinc-600' };
    const ratio = maxCount > 0 ? count / maxCount : 0;
    if (ratio >= 0.8) return { bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.4)', text: 'text-red-400', grad: 'from-red-500/15 to-red-900/5' };
    if (ratio >= 0.5) return { bg: 'rgba(249,115,22,0.10)', border: 'rgba(249,115,22,0.35)', text: 'text-orange-400', grad: 'from-orange-500/12 to-orange-900/5' };
    if (ratio >= 0.25) return { bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.25)', text: 'text-amber-400', grad: 'from-amber-500/10 to-amber-900/5' };
    return { bg: 'rgba(16,185,129,0.06)', border: 'rgba(16,185,129,0.2)', text: 'text-emerald-400', grad: 'from-emerald-500/8 to-emerald-900/5' };
  };

  // Score badge color
  const getScoreColor = (label) => {
    if (label === 'A+' || label === 'A') return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
    if (label === 'B+') return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30';
    if (label === 'B') return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    if (label === 'C') return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    if (label === 'D' || label === 'F') return 'bg-red-500/20 text-red-400 border-red-500/30';
    return 'bg-zinc-700/30 text-zinc-500 border-zinc-600/30';
  };

  return (
    <div className="glass-card" data-testid="earnings-widget">
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
        <div className="px-2 pb-3">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
            </div>
          ) : (
            <>
              {/* Week Navigation */}
              <div className="flex items-center justify-between mb-2 px-1">
                <button 
                  onClick={() => setWeekOffset(prev => prev - 1)}
                  className="p-1 hover:bg-zinc-800 rounded transition-colors"
                  data-testid="earnings-prev-week"
                >
                  <ChevronLeft className="w-3.5 h-3.5 text-zinc-400" />
                </button>
                <span className="text-xs text-zinc-400 font-medium">
                  {weekOffset === 0 ? 'This Week' : weekOffset > 0 ? `+${weekOffset} Week${weekOffset > 1 ? 's' : ''}` : `${weekOffset} Week${weekOffset < -1 ? 's' : ''}`}
                </span>
                <button 
                  onClick={() => setWeekOffset(prev => prev + 1)}
                  className="p-1 hover:bg-zinc-800 rounded transition-colors"
                  data-testid="earnings-next-week"
                >
                  <ChevronRight className="w-3.5 h-3.5 text-zinc-400" />
                </button>
              </div>

              {/* Heat Legend */}
              <div className="flex items-center justify-center gap-1.5 mb-2 px-1">
                <span className="text-[9px] text-zinc-500">Light</span>
                <div className="w-3 h-2 rounded-sm bg-emerald-500/30" />
                <div className="w-3 h-2 rounded-sm bg-amber-500/30" />
                <div className="w-3 h-2 rounded-sm bg-orange-500/30" />
                <div className="w-3 h-2 rounded-sm bg-red-500/30" />
                <span className="text-[9px] text-zinc-500">Heavy</span>
              </div>

              {/* Column Layout: Day headers + companies underneath */}
              <div className="grid grid-cols-5 gap-1" data-testid="earnings-columns">
                {weekDays.map((day) => {
                  const dayData = getEarningsForDate(day.date);
                  const count = dayData?.count || 0;
                  const heat = getHeatStyle(count);
                  const allItems = [...(dayData?.before_open || []), ...(dayData?.after_close || [])];
                  
                  return (
                    <div 
                      key={day.date} 
                      className={`flex flex-col rounded-lg overflow-hidden ${count > 0 ? `bg-gradient-to-b ${heat.grad}` : ''}`}
                      style={{ 
                        border: `1px solid ${heat.border}`,
                        background: count === 0 ? heat.bg : undefined
                      }}
                      data-testid={`earnings-col-${day.date}`}
                    >
                      {/* Day Header */}
                      <div className="p-1.5 text-center" style={{ backgroundColor: heat.bg }}>
                        <div className="text-[9px] text-zinc-500 leading-none">{day.dayName}</div>
                        <div className={`text-sm font-bold leading-tight ${day.isToday ? 'text-cyan-400' : 'text-white'}`}>
                          {day.dayNum}
                        </div>
                        {count > 0 && (
                          <div className={`text-[9px] font-semibold leading-none mt-0.5 ${heat.text}`}>
                            {count} report{count !== 1 ? 's' : ''}
                          </div>
                        )}
                      </div>
                      
                      {/* Company list */}
                      <div className="flex-1 px-0.5 pb-1 max-h-48 overflow-y-auto scrollbar-thin space-y-0.5">
                        {allItems.length === 0 ? (
                          <div className="text-[9px] text-zinc-600 text-center py-2">—</div>
                        ) : (
                          allItems.map((item, idx) => (
                            <button
                              key={idx}
                              onClick={() => onTickerSelect?.(item.symbol)}
                              className="w-full text-left px-1 py-1 rounded hover:bg-white/5 transition-colors group"
                              title={`${item.company_name} — ${item.time}\nExp Move: ${item.expected_move?.percent?.toFixed(1)}% / $${item.expected_move?.dollar?.toFixed(2)}\nScore: ${item.earnings_score?.label} (${item.earnings_score?.type})`}
                              data-testid={`earnings-item-${item.symbol}`}
                            >
                              {/* Symbol + timing icon */}
                              <div className="flex items-center gap-0.5">
                                {item.time === 'Before Open' 
                                  ? <Sun className="w-2.5 h-2.5 text-amber-500/70 flex-shrink-0" /> 
                                  : <Moon className="w-2.5 h-2.5 text-violet-400/70 flex-shrink-0" />
                                }
                                <span className="text-[10px] font-bold text-zinc-200 group-hover:text-cyan-400 transition-colors truncate">
                                  {item.symbol}
                                </span>
                              </div>
                              {/* Expected Move */}
                              <div className="flex items-center justify-between mt-0.5">
                                <span className="text-[8px] text-zinc-500">Exp</span>
                                <span className="text-[8px] text-zinc-400">
                                  {item.expected_move?.percent?.toFixed(1)}% <span className="text-zinc-500">${item.expected_move?.dollar?.toFixed(2)}</span>
                                </span>
                              </div>
                              {/* Earnings Score */}
                              <div className="flex items-center justify-between mt-0.5">
                                <span className="text-[8px] text-zinc-500">
                                  {item.has_reported ? 'Result' : 'Proj'}
                                </span>
                                <span className={`text-[8px] font-bold px-1 rounded border ${getScoreColor(item.earnings_score?.label)}`}>
                                  {item.earnings_score?.label || '—'}
                                </span>
                              </div>
                              {/* EPS surprise if reported */}
                              {item.has_reported && item.eps_surprise && (
                                <div className="flex items-center justify-between mt-0.5">
                                  <span className="text-[8px] text-zinc-500">EPS</span>
                                  <span className={`text-[8px] font-medium ${item.eps_surprise.percent >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {item.eps_surprise.percent >= 0 ? '+' : ''}{item.eps_surprise.percent?.toFixed(1)}%
                                  </span>
                                </div>
                              )}
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

// ===================== SMART WATCHLIST WIDGET =====================
const WatchlistWidget = ({ onTickerSelect, onViewChart, wsWatchlist = [] }) => {
  const [watchlist, setWatchlist] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(true);
  const [initialLoadComplete, setInitialLoadComplete] = useState(false); // Prevents "(0)" flicker
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
      setInitialLoadComplete(true); // Mark initial load as complete
      
      // Fetch quotes for symbols
      if (items.length > 0) {
        const symbols = items.map(w => w.symbol);
        try {
          const quotesRes = await api.post('/api/quotes/batch', symbols);
          const quotesMap = {};
          quotesRes.data.quotes?.forEach(q => { quotesMap[q.symbol] = q; });
          setQuotes(quotesMap);
        } catch (e) {
          // Quote fetch failed - continue without quotes
        }
      }
    } catch (err) {
      console.error('Failed to load smart watchlist:', err);
      setInitialLoadComplete(true); // Mark as complete even on error
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
      setInitialLoadComplete(true); // WebSocket data marks initial load complete
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
    <div className="glass-card" data-testid="watchlist-widget">
      <button 
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-zinc-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-medium text-zinc-200">Smart Watchlist</span>
          {/* Only show count after initial load to prevent "(0)" flicker */}
          {initialLoadComplete && (
            <span className="text-xs text-zinc-500">
              ({watchlist.length}/{stats?.max_size || 50})
            </span>
          )}
          {!initialLoadComplete && loading && (
            <RefreshCw className="w-3 h-3 text-zinc-500 animate-spin" />
          )}
        </div>
        <div className="flex items-center gap-2">
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => { e.stopPropagation(); setShowAddInput(!showAddInput); }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setShowAddInput(!showAddInput); } }}
            className="p-1 hover:bg-zinc-700 rounded transition-colors cursor-pointer"
            title="Add symbol"
          >
            <Plus className="w-3 h-3 text-zinc-400" />
          </span>
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
                    {/* Quick Actions */}
                    <QuickActionsMenu 
                      symbol={item.symbol} 
                      currentPrice={quote?.price}
                      variant="compact"
                    />
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
        safeGet('/api/live-scanner/alerts').then(r => r.json()),
        safeGet('/api/live-scanner/status').then(r => r.json())
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
    <div className="glass-card" data-testid="scanner-results-widget">
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
        <div className="px-3 pb-3 space-y-1.5 max-h-80 overflow-y-auto">
          {/* Market Simulator Control */}
          <SimulatorControl 
            className="mb-3"
            onAlertGenerated={(alert) => {
              // Single alert generated on demand
              setAlerts(prev => [alert, ...prev.filter(a => a.id !== alert.id)].slice(0, 20));
            }}
            onAlertsUpdated={(simAlerts) => {
              // Batch update from simulator - merge with existing alerts
              setAlerts(prev => {
                // Get non-simulated alerts
                const realAlerts = prev.filter(a => !a.simulated);
                // Combine simulated alerts (newest first) with real alerts
                const combined = [...simAlerts, ...realAlerts];
                // Remove duplicates by id
                const unique = combined.filter((alert, idx, self) => 
                  idx === self.findIndex(a => a.id === alert.id)
                );
                return unique.slice(0, 20);
              });
            }}
          />
          
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
            alerts.slice(0, 10).map((alert, idx) => {
              // Determine if approaching vs confirmed
              const isApproaching = alert.setup_type?.includes('approaching') || 
                                    alert.headline?.toLowerCase().includes('approaching') ||
                                    alert.headline?.toLowerCase().includes('watch for');
              const isConfirmed = alert.headline?.toLowerCase().includes('confirmed') ||
                                  (alert.headline?.toLowerCase().includes('breakout') && !isApproaching);
              
              // Format timestamp
              const formatTime = (isoString) => {
                if (!isoString) return '';
                const date = new Date(isoString);
                return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
              };
              
              // SMB Integration: Get trade style display
              const getTradeStyleBadge = (style) => {
                if (!style) return null;
                const styles = {
                  'move_2_move': { label: 'M2M', color: 'bg-blue-500/20 text-blue-400', title: 'Move2Move - Quick scalp (1R target)' },
                  'trade_2_hold': { label: 'T2H', color: 'bg-purple-500/20 text-purple-400', title: 'Trade2Hold - Hold for target (3R+)' },
                  'a_plus': { label: 'A+', color: 'bg-amber-500/20 text-amber-400', title: 'A+ Setup - Max conviction' }
                };
                const s = styles[style];
                if (!s) return null;
                return (
                  <span className={`text-[8px] px-1 py-0.5 rounded font-bold ${s.color}`} title={s.title}>
                    {s.label}
                  </span>
                );
              };
              
              // SMB Integration: Get SMB grade color
              const getSmbGradeColor = (grade) => {
                if (!grade) return 'text-zinc-500';
                if (grade === 'A+' || grade === 'A') return 'text-emerald-400';
                if (grade === 'B+' || grade === 'B') return 'text-cyan-400';
                if (grade === 'C') return 'text-yellow-400';
                return 'text-red-400';
              };
              
              // SMB Integration: Get tape score indicator
              const getTapeIndicator = (score) => {
                if (!score && score !== 0) return null;
                // Format to 1 decimal place
                const formattedScore = typeof score === 'number' ? score.toFixed(1) : score;
                const numScore = parseFloat(score);
                const color = numScore >= 7 ? 'text-emerald-400' : numScore >= 5 ? 'text-yellow-400' : 'text-red-400';
                const label = numScore >= 7 ? 'STRONG' : numScore >= 5 ? 'OK' : 'WEAK';
                return (
                  <span className={`text-[8px] ${color}`} title={`Tape Score: ${formattedScore}/10`}>
                    T:{formattedScore}
                  </span>
                );
              };
              
              // SMB Integration: Get direction bias indicator
              const getDirectionBiasBadge = (bias, direction) => {
                if (!bias || bias === 'both') return null;
                // Show warning if trade direction doesn't match setup's primary direction
                if (bias !== direction) {
                  return (
                    <span className="text-[8px] px-1 py-0.5 rounded bg-red-500/30 text-red-400" title={`Setup is primarily ${bias}, but this is ${direction}`}>
                      !{bias.toUpperCase()}
                    </span>
                  );
                }
                return null;
              };
              
              return (
                <div
                  key={idx}
                  onClick={() => onTickerSelect?.(alert.symbol)}
                  className="p-2 bg-zinc-800/40 rounded hover:bg-zinc-800/70 cursor-pointer transition-colors group"
                >
                  {/* Timestamp row */}
                  <div className="flex items-center gap-2 mb-1 text-[9px] text-zinc-500">
                    <Clock className="w-2.5 h-2.5" />
                    <span>{formatTime(alert.created_at)}</span>
                    {alert.simulated && (
                      <span className="flex items-center gap-0.5 px-1 py-0.5 rounded bg-purple-500/20 text-purple-400 font-medium">
                        <FlaskConical className="w-2.5 h-2.5" />
                        SIM
                      </span>
                    )}
                    {isApproaching && (
                      <span className="px-1 py-0.5 rounded bg-yellow-500/20 text-yellow-400 font-medium">WATCH</span>
                    )}
                    {isConfirmed && (
                      <span className="px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-medium">CONFIRMED</span>
                    )}
                  </div>
                  
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      {getDirectionIcon(alert.direction)}
                      <span className="text-xs font-bold text-white">{alert.symbol}</span>
                      <span className={`text-[9px] px-1 py-0.5 rounded border ${getPriorityColor(alert.priority)}`}>
                        {alert.priority?.toUpperCase()}
                      </span>
                      {/* SMB Integration: Trade Style Badge */}
                      {getTradeStyleBadge(alert.trade_style)}
                      {/* SMB Integration: Direction bias warning */}
                      {getDirectionBiasBadge(alert.direction_bias, alert.direction)}
                    </div>
                    <div className="flex items-center gap-1">
                      {/* SMB Integration: SMB Grade */}
                      {(alert.smb_grade || alert.trade_grade) && (
                        <span className={`text-[9px] font-bold ${getSmbGradeColor(alert.smb_grade || alert.trade_grade)}`} title="SMB Grade">
                          {alert.smb_grade || alert.trade_grade}
                        </span>
                      )}
                      {/* SMB Integration: Tape Score */}
                      {getTapeIndicator(alert.tape_score)}
                      {alert.tape_confirmation && !alert.tape_score && (
                        <span className="text-[9px] text-emerald-400">TAPE</span>
                      )}
                      {/* Quick Actions */}
                      <QuickActionsMenu 
                        symbol={alert.symbol} 
                        currentPrice={alert.current_price}
                        variant="compact"
                      />
                      {/* Explain Alert button */}
                      <button
                        onClick={(e) => { 
                          e.stopPropagation(); 
                          // Dispatch custom event for AI to explain this alert
                          window.dispatchEvent(new CustomEvent('explainAlert', { 
                            detail: { symbol: alert.symbol, alert } 
                          }));
                        }}
                        className="p-0.5 opacity-0 group-hover:opacity-100 hover:bg-purple-500/20 rounded transition-all"
                        title="Ask AI to explain this alert"
                        data-testid={`explain-alert-${alert.symbol}`}
                      >
                        <MessageSquare className="w-3 h-3 text-zinc-500 hover:text-purple-400" />
                      </button>
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
                  {/* SMB Integration: Enhanced stats row */}
                  <div className="flex items-center gap-3 mt-1 text-[9px] text-zinc-500">
                    {alert.strategy_win_rate > 0 && (
                      <span>WR: <span className="text-zinc-300">{(alert.strategy_win_rate * 100).toFixed(0)}%</span></span>
                    )}
                    {alert.target_r_multiple > 0 && (
                      <span>Target: <span className="text-cyan-400">{alert.target_r_multiple.toFixed(1)}R</span></span>
                    )}
                    {alert.risk_reward > 0 && !alert.target_r_multiple && (
                      <span>R:R <span className="text-cyan-400">{alert.risk_reward.toFixed(1)}:1</span></span>
                    )}
                    {alert.setup_category && (
                      <span className="text-zinc-600">{alert.setup_category.replace(/_/g, ' ')}</span>
                    )}
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

// ===================== MAIN RIGHT SIDEBAR COMPONENT =====================
const RightSidebar = ({ 
  onTickerSelect, 
  onViewChart,
  // WebSocket-pushed data
  wsScannerAlerts = [],
  wsScannerStatus = null,
  wsSmartWatchlist = [],
  // Layout options
  compact = false  // When true, only show Scanner + Watchlist (skip MarketIntel and Earnings)
}) => {
  return (
    <div className="space-y-3" data-testid="right-sidebar">
      {/* Market Intelligence Panel - Hidden in compact mode */}
      {!compact && (
        <MarketIntelPanel onTickerSelect={onTickerSelect} onViewChart={onViewChart} />
      )}
      
      {/* Scanner Results */}
      <ScannerResultsWidget 
        onTickerSelect={onTickerSelect} 
        onViewChart={onViewChart}
        wsAlerts={wsScannerAlerts}
        wsStatus={wsScannerStatus}
      />
      
      {/* Earnings Widget - Hidden in compact mode */}
      {!compact && (
        <EarningsWidget onTickerSelect={onTickerSelect} onViewChart={onViewChart} />
      )}
      
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
