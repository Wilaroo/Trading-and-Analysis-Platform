/**
 * Trading Dashboard Page - Option D Implementation
 * Full-screen dedicated trading view with:
 * - Open Positions with live P&L
 * - Order Pipeline visualization
 * - In-Trade Guidance alerts
 * - Performance stats + Risk status
 * - Integrated TradingView chart
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  TrendingUp, TrendingDown, AlertTriangle, Activity, 
  Target, Clock, Zap, Eye, Bot, ChevronDown, ChevronUp,
  ArrowRight, CheckCircle, XCircle, Loader, BarChart3, 
  Wallet, Shield, RefreshCw, X, Maximize2, Minimize2,
  DollarSign, Percent, TrendingUp as TrendUp
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Map common symbols to their exchange prefix for real-time data
const getFullSymbol = (ticker) => {
  if (!ticker) return 'AMEX:SPY';
  
  // Already has exchange prefix
  if (ticker.includes(':')) return ticker;
  
  const upper = ticker.toUpperCase();
  
  // ETFs on AMEX/ARCA
  const etfs = ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX', 'GLD', 'SLV', 'TLT', 'XLF', 'XLK', 'XLE', 'XLV', 'XLI', 'XLC', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB', 'VXX', 'UVXY', 'SQQQ', 'TQQQ', 'ARKK'];
  if (etfs.includes(upper)) return `AMEX:${upper}`;
  
  // Major NASDAQ stocks
  const nasdaq = ['AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'INTC', 'NFLX', 'COST', 'PYPL', 'ADBE', 'CMCSA', 'PEP', 'CSCO', 'AVGO', 'TXN', 'QCOM'];
  if (nasdaq.includes(upper)) return `NASDAQ:${upper}`;
  
  // Default to NYSE for unknown symbols
  return `NYSE:${upper}`;
};

// ==================== TRADINGVIEW CHART COMPONENT ====================
const TradingViewChart = ({ symbol = 'SPY', height = 400 }) => {
  const containerRef = useRef(null);
  const widgetRef = useRef(null);
  
  // Get proper exchange-prefixed symbol
  const fullSymbol = getFullSymbol(symbol);
  
  useEffect(() => {
    if (!containerRef.current) return;
    
    // Clear previous widget
    if (widgetRef.current) {
      containerRef.current.innerHTML = '';
    }
    
    // Create new widget
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: fullSymbol,
      interval: "5",
      timezone: "America/New_York",
      theme: "dark",
      style: "1",
      locale: "en",
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      hide_volume: false,
      support_host: "https://www.tradingview.com"
    });
    
    const container = document.createElement('div');
    container.className = 'tradingview-widget-container__widget';
    container.style.height = '100%';
    container.style.width = '100%';
    
    containerRef.current.appendChild(container);
    container.appendChild(script);
    
    widgetRef.current = container;
    
    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [fullSymbol]);
  
  return (
    <div 
      ref={containerRef} 
      className="tradingview-widget-container"
      style={{ height: `${height}px`, width: '100%' }}
    />
  );
};

// ==================== POSITION CARD COMPONENT ====================
const PositionCard = ({ position, onSelect, isSelected, guidance }) => {
  const pnl = position.unrealized_pnl || position.pnl || 0;
  const pnlPct = position.pnl_pct || ((pnl / (position.avg_cost * position.qty)) * 100) || 0;
  const isPositive = pnl >= 0;
  
  const positionGuidance = guidance?.find(g => g.symbol === position.symbol);
  
  return (
    <div 
      onClick={() => onSelect(position.symbol)}
      className={`p-4 rounded-lg border transition-all cursor-pointer ${
        isSelected 
          ? 'bg-cyan-500/10 border-cyan-500/50' 
          : 'bg-zinc-800/50 border-zinc-700/50 hover:border-zinc-600'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            isPositive ? 'bg-emerald-500/20' : 'bg-red-500/20'
          }`}>
            {isPositive ? (
              <TrendingUp className="w-5 h-5 text-emerald-400" />
            ) : (
              <TrendingDown className="w-5 h-5 text-red-400" />
            )}
          </div>
          <div>
            <div className="font-semibold text-white text-lg">{position.symbol}</div>
            <div className="text-xs text-zinc-500">
              {Math.abs(position.qty || position.shares || 0).toLocaleString()} shares @ ${(position.avg_cost || 0).toFixed(2)}
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className={`text-xl font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className={`text-sm ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}{pnlPct.toFixed(2)}%
          </div>
        </div>
      </div>
      
      {/* Price Bar */}
      <div className="mt-3 p-2 bg-zinc-900/50 rounded-lg">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="text-red-400">Stop: ${(position.stop_price || position.avg_cost * 0.95).toFixed(2)}</span>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <span className="text-white">Now: ${(position.current_price || position.avg_cost).toFixed(2)}</span>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <span className="text-emerald-400">T1: ${(position.target_price || position.avg_cost * 1.05).toFixed(2)}</span>
          </div>
        </div>
      </div>
      
      {/* Inline Guidance */}
      {positionGuidance && (
        <div className={`mt-2 p-2 rounded border ${
          positionGuidance.priority === 'high' ? 'bg-red-500/10 border-red-500/30' :
          positionGuidance.priority === 'medium' ? 'bg-yellow-500/10 border-yellow-500/30' :
          'bg-cyan-500/10 border-cyan-500/30'
        }`}>
          <div className="flex items-start gap-2">
            <AlertTriangle className={`w-3 h-3 mt-0.5 flex-shrink-0 ${
              positionGuidance.priority === 'high' ? 'text-red-400' :
              positionGuidance.priority === 'medium' ? 'text-yellow-400' : 'text-cyan-400'
            }`} />
            <span className="text-xs text-zinc-300">{positionGuidance.message}</span>
          </div>
        </div>
      )}
    </div>
  );
};

// ==================== ORDER PIPELINE COMPONENT ====================
const OrderPipeline = ({ queue, recentOrders }) => {
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
      <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-cyan-400" />
          <span className="font-semibold text-white">Order Pipeline</span>
        </div>
        <span className={`px-2 py-0.5 text-xs rounded ${
          queue.pusher_active ? 'bg-cyan-500/20 text-cyan-400' : 'bg-zinc-600/30 text-zinc-500'
        }`}>
          {queue.pusher_active ? 'IB LIVE' : 'OFFLINE'}
        </span>
      </div>
      
      <div className="p-4">
        {/* Pipeline Visualization */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex-1 text-center">
            <div className={`w-16 h-16 mx-auto rounded-full border-2 flex items-center justify-center mb-2 ${
              queue.pending > 0 ? 'bg-yellow-500/20 border-yellow-500/50' : 'bg-zinc-800 border-zinc-700'
            }`}>
              <span className={`text-2xl font-bold ${queue.pending > 0 ? 'text-yellow-400' : 'text-zinc-500'}`}>
                {queue.pending}
              </span>
            </div>
            <span className="text-xs text-zinc-400">Pending</span>
          </div>
          <ArrowRight className="w-6 h-6 text-zinc-600" />
          <div className="flex-1 text-center">
            <div className={`w-16 h-16 mx-auto rounded-full border-2 flex items-center justify-center mb-2 ${
              queue.executing > 0 ? 'bg-cyan-500/20 border-cyan-500/50 animate-pulse' : 'bg-zinc-800 border-zinc-700'
            }`}>
              <span className={`text-2xl font-bold ${queue.executing > 0 ? 'text-cyan-400' : 'text-zinc-500'}`}>
                {queue.executing}
              </span>
            </div>
            <span className="text-xs text-zinc-400">Executing</span>
          </div>
          <ArrowRight className="w-6 h-6 text-zinc-600" />
          <div className="flex-1 text-center">
            <div className="w-16 h-16 mx-auto rounded-full bg-emerald-500/20 border-2 border-emerald-500/50 flex items-center justify-center mb-2">
              <span className="text-2xl font-bold text-emerald-400">{queue.completed}</span>
            </div>
            <span className="text-xs text-zinc-400">Filled</span>
          </div>
        </div>
        
        {/* Recent Orders */}
        {recentOrders.length > 0 && (
          <>
            <div className="text-xs text-zinc-500 mb-2">Recent Executions</div>
            <div className="space-y-1 max-h-32 overflow-auto">
              {recentOrders.slice(0, 5).map((order, i) => (
                <div key={i} className="flex items-center justify-between p-2 bg-zinc-800/50 rounded text-xs">
                  <div className="flex items-center gap-2">
                    {order.status === 'filled' ? (
                      <CheckCircle className="w-4 h-4 text-emerald-400" />
                    ) : order.status === 'cancelled' ? (
                      <XCircle className="w-4 h-4 text-red-400" />
                    ) : (
                      <Loader className="w-4 h-4 text-cyan-400 animate-spin" />
                    )}
                    <span className={`font-medium ${order.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {order.action}
                    </span>
                    <span className="text-white">{order.symbol}</span>
                    <span className="text-zinc-500">x{order.quantity}</span>
                  </div>
                  <div className="text-right">
                    {order.fill_price && (
                      <span className="text-white font-mono">${order.fill_price}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        
        {recentOrders.length === 0 && (
          <div className="text-center text-zinc-500 text-sm py-4">
            No recent orders
          </div>
        )}
      </div>
    </div>
  );
};

// ==================== IN-TRADE GUIDANCE COMPONENT ====================
const InTradeGuidance = ({ guidance, onAskAI }) => {
  const highPriorityCount = guidance.filter(g => g.priority === 'high').length;
  
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
      <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-yellow-400" />
          <span className="font-semibold text-white">In-Trade Guidance</span>
        </div>
        {highPriorityCount > 0 && (
          <span className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 rounded">
            {highPriorityCount} alerts
          </span>
        )}
      </div>
      
      <div className="p-3 space-y-2 max-h-64 overflow-auto">
        {guidance.length === 0 ? (
          <div className="text-center text-zinc-500 text-sm py-4">
            No active guidance - positions look healthy
          </div>
        ) : (
          guidance.map((g, i) => (
            <div key={i} className={`p-3 rounded-lg border ${
              g.priority === 'high' ? 'bg-red-500/10 border-red-500/30' :
              g.priority === 'medium' ? 'bg-yellow-500/10 border-yellow-500/30' :
              'bg-zinc-800/50 border-zinc-700'
            }`}>
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-white">{g.symbol}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  g.priority === 'high' ? 'bg-red-500/20 text-red-400' :
                  g.priority === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                  'bg-zinc-700 text-zinc-400'
                }`}>
                  {g.priority}
                </span>
              </div>
              <p className="text-sm text-zinc-300 mb-2">{g.message}</p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-cyan-400">→ {g.action}</span>
                <button 
                  onClick={() => onAskAI(g)}
                  className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded text-white transition-colors"
                >
                  Ask AI
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ==================== PERFORMANCE STATS COMPONENT ====================
const PerformanceStats = ({ stats }) => {
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
      <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
        <BarChart3 className="w-5 h-5 text-cyan-400" />
        <span className="font-semibold text-white">Today's Performance</span>
      </div>
      
      <div className="p-4 space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-zinc-400">Trades</span>
          <span className="font-mono text-white">{stats.trades_executed || 0}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-zinc-400">Win Rate</span>
          <span className={`font-mono ${(stats.win_rate || 0) >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
            {(stats.win_rate || 0).toFixed(1)}%
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-zinc-400">Winners</span>
          <span className="font-mono text-emerald-400">{stats.trades_won || 0}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-zinc-400">Losers</span>
          <span className="font-mono text-red-400">{stats.trades_lost || 0}</span>
        </div>
        <div className="pt-3 border-t border-zinc-700">
          <div className="flex justify-between items-center">
            <span className="text-zinc-400">Realized P&L</span>
            <span className={`font-mono ${(stats.realized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(stats.realized_pnl || 0) >= 0 ? '+' : ''}${(stats.realized_pnl || 0).toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between items-center mt-1">
            <span className="text-zinc-400">Unrealized P&L</span>
            <span className={`font-mono ${(stats.net_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(stats.net_pnl || 0) >= 0 ? '+' : ''}${(stats.net_pnl || 0).toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

// ==================== RISK STATUS COMPONENT ====================
const RiskStatus = ({ stats, positions }) => {
  const dailyLossLimit = 10000; // Could be from settings
  const dailyLossUsed = Math.abs(Math.min(stats.net_pnl || 0, 0));
  const dailyLossPct = (dailyLossUsed / dailyLossLimit) * 100;
  
  // Calculate sector exposure
  const totalValue = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
  const exposurePct = totalValue > 0 ? 100 : 0; // Simplified
  
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
      <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
        <Shield className="w-5 h-5 text-yellow-400" />
        <span className="font-semibold text-white">Risk Status</span>
      </div>
      
      <div className="p-4 space-y-3">
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-zinc-400">Daily Loss Limit</span>
            <span className={dailyLossPct > 75 ? 'text-red-400' : dailyLossPct > 50 ? 'text-yellow-400' : 'text-emerald-400'}>
              {dailyLossPct.toFixed(0)}% used
            </span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
            <div 
              className={`h-full rounded-full transition-all ${
                dailyLossPct > 75 ? 'bg-red-500' : dailyLossPct > 50 ? 'bg-yellow-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min(dailyLossPct, 100)}%` }}
            />
          </div>
        </div>
        
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-zinc-400">Position Exposure</span>
            <span className={exposurePct > 80 ? 'text-red-400' : 'text-emerald-400'}>
              {positions.length} positions
            </span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
            <div 
              className={`h-full rounded-full ${exposurePct > 80 ? 'bg-red-500' : 'bg-emerald-500'}`}
              style={{ width: `${Math.min(exposurePct, 100)}%` }}
            />
          </div>
        </div>
        
        {stats.daily_limit_hit && (
          <div className="p-2 bg-red-500/10 rounded border border-red-500/30">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              <span className="text-xs text-red-200">Daily loss limit reached - trading paused</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// ==================== MAIN TRADING DASHBOARD PAGE ====================
const TradingDashboardPage = () => {
  // State
  const [positions, setPositions] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [orderQueue, setOrderQueue] = useState({ pending: 0, executing: 0, completed: 0, pusher_active: false });
  const [recentOrders, setRecentOrders] = useState([]);
  const [guidance, setGuidance] = useState([]);
  const [botStats, setBotStats] = useState({});
  const [accountData, setAccountData] = useState({});
  const [loading, setLoading] = useState(true);
  const [chartExpanded, setChartExpanded] = useState(false);
  
  // Fetch positions from IB
  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/ib/pushed-data`);
      const data = await res.json();
      
      if (data.connected && data.positions?.length > 0) {
        const formattedPositions = data.positions.map(p => ({
          symbol: p.symbol,
          qty: p.position || p.qty,
          avg_cost: p.avgCost || p.avg_cost || 0,
          current_price: data.quotes?.[p.symbol]?.last || p.avgCost || 0,
          market_value: p.marketValue || p.market_value || 0,
          unrealized_pnl: p.unrealizedPNL || p.unrealized_pnl || 0,
          pnl_pct: p.avgCost ? ((p.unrealizedPNL || 0) / (p.avgCost * (p.position || 1))) * 100 : 0
        }));
        setPositions(formattedPositions);
        
        // Select first position if none selected
        if (!selectedSymbol && formattedPositions.length > 0) {
          setSelectedSymbol(formattedPositions[0].symbol);
        }
      }
      
      // Also get account data
      if (data.account) {
        setAccountData({
          equity: data.account.NetLiquidation || data.account['NetLiquidation-S'] || 0,
          buying_power: data.account.BuyingPower || data.account['BuyingPower-S'] || 0,
          day_pnl: data.account.UnrealizedPnL || 0
        });
      }
    } catch (err) {
      console.error('Failed to fetch positions:', err);
    }
  }, [selectedSymbol]);
  
  // Fetch order queue status
  const fetchOrderQueue = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/ib/orders/queue/status`);
      const data = await res.json();
      if (data.success) {
        setOrderQueue({
          pending: data.pending_count || 0,
          executing: data.executing_count || 0,
          completed: data.completed_count || 0,
          pusher_active: data.pusher_active || false
        });
      }
    } catch (err) {
      console.error('Failed to fetch order queue:', err);
    }
  }, []);
  
  // Fetch bot stats
  const fetchBotStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/status`);
      const data = await res.json();
      if (data.success) {
        setBotStats(data.daily_stats || {});
      }
    } catch (err) {
      console.error('Failed to fetch bot stats:', err);
    }
  }, []);
  
  // Generate guidance based on positions
  const generateGuidance = useCallback((positions) => {
    const newGuidance = [];
    
    positions.forEach(pos => {
      const pnlPct = pos.pnl_pct || 0;
      
      // High priority: Large loss
      if (pnlPct < -5) {
        newGuidance.push({
          symbol: pos.symbol,
          priority: 'high',
          message: `Position down ${Math.abs(pnlPct).toFixed(1)}% - approaching stop loss territory`,
          action: 'Consider tightening stop or reducing size'
        });
      }
      // Medium priority: Near target
      else if (pnlPct > 3 && pnlPct < 10) {
        newGuidance.push({
          symbol: pos.symbol,
          priority: 'medium',
          message: `Position up ${pnlPct.toFixed(1)}% - approaching first target`,
          action: 'Consider scaling out 50% at target'
        });
      }
      // Low priority: Let winners run
      else if (pnlPct > 10) {
        newGuidance.push({
          symbol: pos.symbol,
          priority: 'low',
          message: `Strong winner up ${pnlPct.toFixed(1)}%`,
          action: 'Move stop to breakeven, let it run'
        });
      }
    });
    
    setGuidance(newGuidance);
  }, []);
  
  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([
        fetchPositions(),
        fetchOrderQueue(),
        fetchBotStats()
      ]);
      setLoading(false);
    };
    
    loadData();
    
    // Polling intervals
    const positionsInterval = setInterval(fetchPositions, 5000);
    const queueInterval = setInterval(fetchOrderQueue, 3000);
    const statsInterval = setInterval(fetchBotStats, 10000);
    
    return () => {
      clearInterval(positionsInterval);
      clearInterval(queueInterval);
      clearInterval(statsInterval);
    };
  }, [fetchPositions, fetchOrderQueue, fetchBotStats]);
  
  // Generate guidance when positions change
  useEffect(() => {
    generateGuidance(positions);
  }, [positions, generateGuidance]);
  
  // Calculate totals
  const totalPnl = positions.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
  const totalValue = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
  
  // Handle ask AI
  const handleAskAI = (guidanceItem) => {
    // Could open AI chat with pre-filled question
    console.log('Ask AI about:', guidanceItem);
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-zinc-950">
        <div className="text-center">
          <Loader className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-2" />
          <span className="text-zinc-400">Loading trading dashboard...</span>
        </div>
      </div>
    );
  }
  
  return (
    <div className="min-h-screen bg-zinc-950 p-4">
      {/* Top Stats Bar */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Wallet className="w-6 h-6 text-cyan-400" />
          <h1 className="text-xl font-bold text-white">Trading Dashboard</h1>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="px-4 py-2 bg-zinc-900 rounded-lg border border-zinc-700">
            <span className="text-xs text-zinc-500">Account Value</span>
            <p className="font-mono text-white text-lg">
              ${(accountData.equity || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="px-4 py-2 bg-zinc-900 rounded-lg border border-zinc-700">
            <span className="text-xs text-zinc-500">Day P&L</span>
            <p className={`font-mono text-lg ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className={`px-4 py-2 rounded-lg border ${
            orderQueue.pusher_active 
              ? 'bg-cyan-500/10 border-cyan-500/30' 
              : 'bg-zinc-900 border-zinc-700'
          }`}>
            <span className="text-xs text-zinc-500">IB Status</span>
            <p className={`text-sm font-medium ${orderQueue.pusher_active ? 'text-cyan-400' : 'text-zinc-500'}`}>
              {orderQueue.pusher_active ? 'Connected' : 'Offline'}
            </p>
          </div>
        </div>
      </div>
      
      {/* Main Grid */}
      <div className="grid grid-cols-12 gap-4">
        {/* LEFT COLUMN - Positions */}
        <div className="col-span-3 space-y-4">
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-cyan-400" />
                <span className="font-semibold text-white">Open Positions</span>
              </div>
              <span className="px-2 py-0.5 text-xs bg-zinc-700 text-zinc-300 rounded">
                {positions.length} active
              </span>
            </div>
            
            <div className="p-3 space-y-2 max-h-[600px] overflow-auto">
              {positions.length === 0 ? (
                <div className="text-center text-zinc-500 py-8">
                  <Wallet className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>No open positions</p>
                </div>
              ) : (
                positions.map(pos => (
                  <PositionCard
                    key={pos.symbol}
                    position={pos}
                    onSelect={setSelectedSymbol}
                    isSelected={selectedSymbol === pos.symbol}
                    guidance={guidance}
                  />
                ))
              )}
            </div>
          </div>
        </div>
        
        {/* CENTER COLUMN - Chart + Orders */}
        <div className="col-span-6 space-y-4">
          {/* Chart */}
          <div className={`bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden transition-all ${
            chartExpanded ? 'fixed inset-4 z-50' : ''
          }`}>
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-cyan-400" />
                <span className="font-semibold text-white">
                  {selectedSymbol || 'SPY'} Chart
                </span>
              </div>
              <button 
                onClick={() => setChartExpanded(!chartExpanded)}
                className="p-1 hover:bg-zinc-700 rounded transition-colors"
              >
                {chartExpanded ? (
                  <Minimize2 className="w-4 h-4 text-zinc-400" />
                ) : (
                  <Maximize2 className="w-4 h-4 text-zinc-400" />
                )}
              </button>
            </div>
            <TradingViewChart 
              symbol={selectedSymbol || 'SPY'} 
              height={chartExpanded ? window.innerHeight - 150 : 350}
            />
          </div>
          
          {/* Order Pipeline + Guidance */}
          <div className="grid grid-cols-2 gap-4">
            <OrderPipeline queue={orderQueue} recentOrders={recentOrders} />
            <InTradeGuidance guidance={guidance} onAskAI={handleAskAI} />
          </div>
        </div>
        
        {/* RIGHT COLUMN - Stats */}
        <div className="col-span-3 space-y-4">
          <PerformanceStats stats={botStats} />
          <RiskStatus stats={botStats} positions={positions} />
        </div>
      </div>
    </div>
  );
};

export default TradingDashboardPage;
