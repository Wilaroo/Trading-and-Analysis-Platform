/**
 * NewDashboard - Bot-centric dashboard layout matching the approved V2 design
 * 
 * Layout:
 * - Header: Bot status, compact info (Session/Regime/Brief Me), Account data, Risk Status, P&L
 * - Bot Performance Chart (always visible)
 * - Main Grid:
 *   - Left (8 cols): SentCom (Unified AI with Order Pipeline + Chat), Active Positions, Setups We're Watching
 *   - Right (4 cols): Learning Insights, Market Regime
 * - Scanner Alerts strip at bottom
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { 
  Wifi, WifiOff, Brain, Sparkles, Activity, Target, Eye, 
  Bell, ChevronRight, Clock, TrendingUp, TrendingDown,
  Pause, Play, Zap, RefreshCw, Shield, DollarSign, Wallet,
  ArrowRight, AlertTriangle
} from 'lucide-react';

// Import new components
import BotPerformanceChart from './BotPerformanceChart';
import SentCom from './SentCom';
import { useTickerModal } from '../hooks/useTickerModal';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';
const DASHBOARD_REFRESH_INTERVAL = 15000; // 15 seconds for dashboard data
const ACCOUNT_REFRESH_INTERVAL = 5000; // 5 seconds for account data

// Header component with compact info, account data, and P&L
// Bot status and controls are now in the unified SentCom header below
const DashboardHeader = ({ 
  botStatus, 
  regime, 
  todayPnl, 
  openPnl,
  accountData,
  riskStatus,
  onBriefMe,
}) => {
  // Fetch market session from API
  const [marketSession, setMarketSession] = useState({ name: 'LOADING', is_open: false });
  
  useEffect(() => {
    const fetchSession = async () => {
      try {
        const res = await fetch(`${API_URL}/api/market-context/session/status`);
        const data = await res.json();
        if (data.success && data.session) {
          setMarketSession(data.session);
        }
      } catch (err) {
        console.error('Error fetching market session:', err);
      }
    };
    
    fetchSession();
    const interval = setInterval(fetchSession, 30000); // Update every 30 seconds
    return () => clearInterval(interval);
  }, []);
  // Risk status calculations
  const dailyLossLimit = riskStatus?.daily_loss_limit || 10000;
  const dailyLossUsed = Math.abs(Math.min(todayPnl || 0, 0));
  const dailyLossPct = (dailyLossUsed / dailyLossLimit) * 100;
  const positionCount = riskStatus?.position_count || 0;
  const maxPositions = riskStatus?.max_positions || 10;
  const exposurePct = (positionCount / maxPositions) * 100;
  
  return (
    <div className="bg-gradient-to-r from-zinc-900/80 to-zinc-900/60 backdrop-blur-xl border border-white/10 rounded-xl p-2 mb-3">
      {/* Single Row: Session Info | Account Data | P&L - Removed redundant Command Center branding */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          {/* Compact Info Row: AI Credits | Session */}
          <div className="flex items-center gap-2">
            {/* AI Credits indicator */}
            <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-violet-500/10 border border-violet-500/20">
              <Sparkles className="w-3 h-3 text-violet-400" />
              <span className="text-[9px] text-zinc-400">AI</span>
              <div className="w-12 h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-violet-500 to-cyan-500 rounded-full" style={{ width: '70%' }} />
              </div>
              <span className="text-[10px] text-violet-400 font-mono">281</span>
            </div>
            
            <div className="w-px h-5 bg-white/10" />
            
            <div className={`px-2 py-0.5 rounded-lg border ${
              marketSession.is_open 
                ? marketSession.name === 'MARKET OPEN'
                  ? 'bg-emerald-500/10 border-emerald-500/20'
                  : 'bg-amber-500/10 border-amber-500/20'
                : 'bg-white/5 border-white/5'
            }`}>
              <span className={`text-[10px] font-medium ${
                marketSession.is_open 
                  ? marketSession.name === 'MARKET OPEN'
                    ? 'text-emerald-400'
                    : 'text-amber-400'
                  : 'text-zinc-400'
              }`}>{marketSession.name || 'CLOSED'}</span>
            </div>
          </div>
        </div>
        
        {/* Right Side: Account + P&L - More compact */}
        <div className="flex items-center gap-3">
          {/* Partial/Live Mode Toggle */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/5 border border-white/5">
            <span className="text-[9px] text-zinc-500">Partial</span>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[10px] text-emerald-400 font-medium">LIVE</span>
            </div>
          </div>
          
          {/* Account Value */}
          <div className="text-right">
            <div className="text-[9px] text-zinc-500 uppercase">Account</div>
            <div className="font-mono text-sm text-white">
              ${accountData?.net_liquidation?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || '0'}
            </div>
          </div>
          
          {/* Buying Power */}
          <div className="text-right">
            <div className="text-[9px] text-zinc-500 uppercase">BP</div>
            <div className="font-mono text-sm text-white">
              ${accountData?.buying_power?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || '0'}
            </div>
          </div>
          
          {/* Today P&L */}
          <div className="text-right">
            <div className="text-[9px] text-zinc-500 uppercase">Today</div>
            <div className={`font-mono text-sm ${todayPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {todayPnl >= 0 ? '+' : ''}${todayPnl?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || '0'}
            </div>
          </div>
          
          {/* Open P&L */}
          <div className="text-right">
            <div className="text-[9px] text-zinc-500 uppercase">Open</div>
            <div className={`font-mono text-sm ${openPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {openPnl >= 0 ? '+' : ''}${openPnl?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || '0'}
            </div>
          </div>
          
          {/* Time */}
          <div className="text-right pl-2 border-l border-white/10">
            <div className="font-mono text-sm text-zinc-300">
              {new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// Active Positions Card
const ActivePositionsCard = ({ positions = [], onPositionClick }) => {
  const { openTickerModal } = useTickerModal();
  
  const handlePositionClick = (symbol) => {
    openTickerModal(symbol);
  };
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-3">
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="font-bold text-sm">ACTIVE POSITIONS</h2>
          <span className="px-1.5 py-0.5 rounded bg-zinc-700 text-[10px] font-mono">
            {positions.length} OPEN
          </span>
        </div>
      </div>
      
      {positions.length === 0 ? (
        <div className="text-center py-4 text-zinc-500">
          <Target className="w-5 h-5 mx-auto mb-1 opacity-50" />
          <p className="text-xs">No open positions</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {positions.map((pos, i) => {
            const pnl = pos.unrealized_pnl || pos.pnl || 0;
            const pnlPct = pos.pnl_percent || (pos.current_price && pos.entry_price 
              ? ((pos.current_price - pos.entry_price) / pos.entry_price * 100) 
              : 0);
            const isPositive = pnl >= 0;
            
            return (
              <button
                key={pos.id || pos.symbol}
                onClick={() => handlePositionClick(pos.symbol)}
                data-testid={`position-card-${pos.symbol}`}
                className={`w-full text-left p-2 rounded-lg bg-zinc-800/50 border cursor-pointer transition-all hover:scale-[1.005] hover:bg-zinc-800/70 ${
                  isPositive ? 'border-emerald-500/20 hover:border-emerald-500/40' : 'border-red-500/20 hover:border-red-500/40'
                }`}
              >
                {/* Compact Single Row Layout */}
                <div className="flex items-center justify-between gap-2">
                  {/* Symbol + Direction */}
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`font-bold text-sm ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {pos.symbol}
                    </span>
                    <span className={`px-1 py-0.5 rounded text-[10px] ${
                      pos.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {pos.direction?.toUpperCase() || 'L'}
                    </span>
                  </div>
                  
                  {/* Compact Stats */}
                  <div className="flex items-center gap-3 text-[10px]">
                    <div className="text-zinc-500">
                      <span className="font-mono">{pos.shares || pos.quantity}</span> @ <span className="font-mono">${pos.entry_price?.toFixed(2)}</span>
                    </div>
                    <div className="text-zinc-500">
                      <span className="text-red-400 font-mono">${pos.stop_price?.toFixed(2) || '--'}</span>
                      <span className="mx-1">→</span>
                      <span className="text-emerald-400 font-mono">${pos.target_prices?.[0]?.toFixed(2) || pos.target_price?.toFixed(2) || '--'}</span>
                    </div>
                  </div>
                  
                  {/* P&L */}
                  <div className="text-right flex-shrink-0">
                    <div className={`font-mono text-sm font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}${pnl.toFixed(0)}
                    </div>
                    <div className={`text-[10px] ${isPositive ? 'text-emerald-400/70' : 'text-red-400/70'}`}>
                      {isPositive ? '+' : ''}{pnlPct.toFixed(1)}%
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Setups We're Watching Card
const WatchingSetupsCard = ({ setups = [] }) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-3">
          <Eye className="w-5 h-5 text-purple-400" />
          <h2 className="font-bold text-lg">SETUPS WE'RE WATCHING</h2>
          <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-400 text-xs font-mono">
            {setups.length} PENDING
          </span>
        </div>
      </div>
      
      {setups.length === 0 ? (
        <div className="text-center py-6 text-zinc-500">
          <Eye className="w-6 h-6 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No setups being watched</p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {setups.slice(0, 3).map((setup, i) => {
            const probability = setup.probability || setup.confidence || Math.floor(Math.random() * 40 + 30);
            
            return (
              <motion.div
                key={setup.symbol || i}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.05 }}
                onClick={() => openTickerModal(setup.symbol)}
                className="p-3 rounded-xl bg-purple-500/10 border border-purple-500/30 hover:border-purple-500/50 transition-colors cursor-pointer"
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="font-bold text-lg">{setup.symbol}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    setup.setup_type?.includes('BREAKOUT') ? 'bg-cyan-500/20 text-cyan-400' :
                    setup.setup_type?.includes('VWAP') ? 'bg-amber-500/20 text-amber-400' :
                    setup.direction === 'short' ? 'bg-red-500/20 text-red-400' :
                    'bg-emerald-500/20 text-emerald-400'
                  }`}>
                    {setup.setup_type || 'SETUP'}
                  </span>
                </div>
                
                <div className="text-xs text-zinc-400 mb-2">
                  Entry: <span className="font-mono text-white">${setup.trigger_price?.toFixed(2) || '--'}</span>
                  {' | '}
                  R:R: <span className="font-mono text-emerald-400">{setup.risk_reward?.toFixed(1) || '--'}:1</span>
                </div>
                
                <div className="border-l-[3px] border-cyan-400 bg-gradient-to-r from-cyan-400/10 to-transparent p-2 rounded-r text-xs">
                  <span className="text-cyan-400">
                    "{setup.reasoning || `I'll enter if price breaks $${setup.trigger_price?.toFixed(2) || '--'}`}"
                  </span>
                </div>
                
                {/* Probability Bar */}
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-black/40 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-gradient-to-r from-purple-500 to-cyan-400 rounded-full transition-all"
                      style={{ width: `${probability}%` }}
                    />
                  </div>
                  <span className={`text-xs ${probability >= 60 ? 'text-cyan-400' : 'text-purple-400'}`}>
                    {probability}%
                  </span>
                </div>
                <div className="text-[10px] text-zinc-500 mt-1">Probability to trigger</div>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Scanner Alerts Strip
const ScannerAlertsStrip = ({ alerts = [], onViewAll }) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 mt-4">
      <div className="flex justify-between items-center mb-3">
        <div className="flex items-center gap-3">
          <Bell className="w-5 h-5 text-amber-400" />
          <h2 className="font-bold text-lg">LIVE SCANNER ALERTS</h2>
          <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-xs font-mono animate-pulse">
            {alerts.length} NEW
          </span>
        </div>
        {onViewAll && (
          <button 
            onClick={onViewAll}
            className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
          >
            View All
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>
      
      <div className="flex gap-3 overflow-x-auto pb-2">
        {alerts.slice(0, 5).map((alert, i) => {
          const isHQ = alert.tqs >= 70 || alert.quality === 'high';
          const isLong = alert.direction === 'long' || alert.direction === 'LONG';
          
          return (
            <motion.div
              key={alert.id || `${alert.symbol}-${i}`}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => openTickerModal(alert.symbol)}
              className={`flex-shrink-0 w-52 p-3 rounded-xl cursor-pointer transition-all hover:scale-[1.02] ${
                isHQ 
                  ? 'bg-emerald-500/10 border-2 border-emerald-500/50' 
                  : 'bg-black/30 border border-zinc-700'
              }`}
              style={isHQ ? { boxShadow: '0 0 15px rgba(0, 255, 148, 0.2)' } : {}}
            >
              <div className="flex justify-between items-start mb-2">
                <div>
                  <span className="font-bold text-lg">{alert.symbol}</span>
                  {isHQ && (
                    <span className="ml-1 px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-xs">HQ</span>
                  )}
                </div>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {isLong ? 'LONG' : 'SHORT'}
                </span>
              </div>
              
              <div className={`text-xs mb-1 ${
                alert.setup_type?.includes('ORB') ? 'text-cyan-400' :
                alert.setup_type?.includes('VWAP') ? 'text-amber-400' :
                'text-purple-400'
              }`}>
                {alert.setup_type || alert.strategy || 'Trade Setup'}
              </div>
              
              <div className="text-xs mb-1">
                <span className="text-zinc-500">R:R:</span>
                <span className={`font-mono ml-1 ${alert.risk_reward >= 2.5 ? 'text-emerald-400' : 'text-zinc-300'}`}>
                  {alert.risk_reward?.toFixed(1) || '--'}:1
                </span>
              </div>
              
              <div className={`text-xs ${isHQ ? 'text-emerald-400' : 'text-zinc-500'}`}>
                TQS: {alert.tqs?.toFixed(0) || '--'} ({alert.grade || '--'})
              </div>
            </motion.div>
          );
        })}
        
        {alerts.length === 0 && (
          <div className="flex-1 text-center py-4 text-zinc-500">
            <Bell className="w-6 h-6 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No alerts yet</p>
          </div>
        )}
      </div>
    </div>
  );
};

// Main Dashboard Component
const NewDashboard = ({
  // Bot data (optional - can be fetched from API)
  botStatus = null,
  botTrades = [],
  watchingSetups = [],
  scannerAlerts = [],
  
  // Market data
  marketSession = null,
  regime = null,
  
  // P&L (optional - can be fetched from API)
  todayPnl = 0,
  openPnl = 0,
  
  // Callbacks
  onBriefMe,
  onViewAnalytics,
  onViewHistory,
  onViewAllAlerts,
  onNavigateToTab,
  
  // Children (for AI Assistant panel on right)
  children,
}) => {
  // Local state for API data
  const [dashboardData, setDashboardData] = useState(null);
  const [accountData, setAccountData] = useState(null);
  const [orderQueue, setOrderQueue] = useState({ pending: 0, executing: 0, completed: 0 });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Fetch dashboard data from API
  const fetchDashboardData = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/trading-bot/dashboard-data`);
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setDashboardData(data);
          setError(null);
        }
      }
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
      setError('Failed to load dashboard data');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch account data from IB
  const fetchAccountData = useCallback(async () => {
    try {
      const [accountRes, ibDataRes] = await Promise.all([
        fetch(`${API_URL}/api/ib/account/summary`),
        fetch(`${API_URL}/api/ib/pushed-data`)
      ]);
      
      if (accountRes.ok) {
        const data = await accountRes.json();
        if (data.success) {
          setAccountData(prev => ({
            ...prev,
            net_liquidation: data.net_liquidation,
            buying_power: data.buying_power,
            available_funds: data.available_funds,
            daily_pnl: data.daily_pnl,
            realized_pnl: data.realized_pnl,
            unrealized_pnl: data.unrealized_pnl,
          }));
        }
      }
      
      if (ibDataRes.ok) {
        const ibData = await ibDataRes.json();
        setAccountData(prev => ({
          ...prev,
          ib_connected: ibData.connected || false,
        }));
      }
    } catch (err) {
      console.error('Failed to fetch account data:', err);
    }
  }, []);

  // Fetch order queue status
  const fetchOrderQueue = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/ib/orders/queue/status`);
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setOrderQueue({
            pending: data.counts?.pending || data.pending?.length || 0,
            executing: data.counts?.executing || data.executing?.length || 0,
            completed: data.counts?.completed || data.completed?.length || 0,
            recent_orders: data.completed?.slice(0, 5) || [],
          });
        }
      }
    } catch (err) {
      console.error('Failed to fetch order queue:', err);
    }
  }, []);
  
  // Initial fetch and auto-refresh
  useEffect(() => {
    fetchDashboardData();
    fetchAccountData();
    fetchOrderQueue();
    
    const dashboardInterval = setInterval(fetchDashboardData, DASHBOARD_REFRESH_INTERVAL);
    const accountInterval = setInterval(fetchAccountData, ACCOUNT_REFRESH_INTERVAL);
    const orderQueueInterval = setInterval(fetchOrderQueue, 3000); // 3 seconds for order queue
    
    return () => {
      clearInterval(dashboardInterval);
      clearInterval(accountInterval);
      clearInterval(orderQueueInterval);
    };
  }, [fetchDashboardData, fetchAccountData, fetchOrderQueue]);
  
  // Merge prop data with API data (props take precedence if provided)
  const effectiveBotStatus = botStatus || dashboardData?.bot_status;
  const effectiveTodayPnl = todayPnl || dashboardData?.today_pnl || 0;
  const effectiveOpenPnl = openPnl || dashboardData?.open_pnl || 0;
  
  // For open trades, check if prop has data first, then use API data
  const propsOpenTrades = botTrades.filter(t => t.status === 'open' || t.status === undefined);
  const effectiveOpenTrades = propsOpenTrades.length > 0 
    ? propsOpenTrades
    : dashboardData?.open_trades || [];
    
  // For watching setups, also check pending trades from API
  const effectiveWatchingSetups = watchingSetups.length > 0 
    ? watchingSetups 
    : dashboardData?.watching_setups || [];
  const closedTrades = botTrades.filter(t => t.status === 'closed');

  // Build risk status
  const riskStatus = {
    daily_loss_limit: dashboardData?.bot_status?.daily_loss_limit || 10000,
    position_count: effectiveOpenTrades.length,
    max_positions: 10,
    daily_limit_hit: dashboardData?.bot_status?.daily_limit_hit || false,
  };
  
  return (
    <div className="space-y-3">
      {/* Header - Compact */}
      <DashboardHeader
        botStatus={effectiveBotStatus}
        marketSession={marketSession}
        regime={regime}
        todayPnl={effectiveTodayPnl}
        openPnl={effectiveOpenPnl}
        accountData={accountData}
        riskStatus={riskStatus}
        onBriefMe={onBriefMe}
      />
      
      {/* Main Grid - SentCom is Primary */}
      <div className="grid grid-cols-12 gap-3">
        {/* Left Column (8 cols) - SentCom takes full width */}
        <div className="col-span-8">
          {/* SentCom Embedded (Unified AI Command Center) */}
          {/* Now includes Positions + Setups panels - no duplicates below */}
          <SentCom embedded={true} />
        </div>
        
        {/* Right Column (4 cols) - Learning Insights + Market Regime */}
        <div className="col-span-4 space-y-3">
          {children}
        </div>
      </div>
      
      {/* Bot Performance Chart - Moved below main grid */}
      <BotPerformanceChart
        trades={closedTrades}
        todayPnl={effectiveTodayPnl}
        onViewFullAnalytics={onViewAnalytics}
        autoRefresh={true}
      />
      
      {/* Scanner Alerts Strip */}
      <ScannerAlertsStrip 
        alerts={scannerAlerts}
        onViewAll={onViewAllAlerts}
      />
    </div>
  );
};

export default NewDashboard;
