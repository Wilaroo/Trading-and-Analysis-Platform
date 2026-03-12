/**
 * NewDashboard - Bot-centric dashboard layout matching the approved V2 design
 * 
 * Layout:
 * - Header: Bot status, Session, Regime, "Brief Me" button, P&L
 * - Bot Performance Chart (always visible)
 * - Main Grid:
 *   - Left (8 cols): Bot's Brain, Active Positions, Setups I'm Watching
 *   - Right (4 cols): AI Assistant, Market Regime, Quick Stats
 * - Scanner Alerts strip at bottom
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { 
  Wifi, WifiOff, Brain, Sparkles, Activity, Target, Eye, 
  Bell, ChevronRight, Clock, TrendingUp, TrendingDown,
  Pause, Play, Zap, RefreshCw
} from 'lucide-react';

// Import new components
import BotPerformanceChart from './BotPerformanceChart';
import BotBrainPanel from './BotBrainPanel';
import { useTickerModal } from '../hooks/useTickerModal';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';
const DASHBOARD_REFRESH_INTERVAL = 15000; // 15 seconds for dashboard data

// Header component with bot status, session, regime, Brief Me button
const DashboardHeader = ({ 
  botStatus, 
  marketSession, 
  regime, 
  todayPnl, 
  openPnl,
  onBriefMe,
  onToggleBot 
}) => {
  const isHunting = botStatus?.running || botStatus?.state === 'hunting' || botStatus?.state === 'active';
  const lastAction = botStatus?.last_action || null;
  
  // Determine the display state
  const getDisplayState = () => {
    if (!botStatus) return 'LOADING';
    if (botStatus.running === false) return 'PAUSED';
    if (botStatus.state === 'hunting') return 'HUNTING';
    if (botStatus.state === 'active') return 'ACTIVE';
    if (botStatus.running === true) return 'RUNNING';
    return botStatus.state?.toUpperCase() || 'OFFLINE';
  };
  
  const displayState = getDisplayState();
  const stateColors = {
    'HUNTING': 'bg-emerald-500/20 text-emerald-400',
    'ACTIVE': 'bg-emerald-500/20 text-emerald-400',
    'RUNNING': 'bg-emerald-500/20 text-emerald-400',
    'PAUSED': 'bg-amber-500/20 text-amber-400',
    'LOADING': 'bg-blue-500/20 text-blue-400 animate-pulse',
    'OFFLINE': 'bg-zinc-500/20 text-zinc-400'
  };
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-3 mb-4 flex justify-between items-center">
      <div className="flex items-center gap-6">
        {/* Bot Status Hero */}
        <div className="flex items-center gap-4">
          <div className="relative">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 p-0.5">
              <div className="w-full h-full rounded-full bg-zinc-900 flex items-center justify-center">
                <span className="font-bold text-lg text-cyan-400">TC</span>
              </div>
            </div>
            <div className={`absolute -bottom-1 -right-1 w-4 h-4 rounded-full border-2 border-zinc-900 ${
              isHunting ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'
            }`} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-xl">TRADING BOT</span>
              <span className={`px-2 py-0.5 rounded-full text-xs font-mono ${stateColors[displayState] || stateColors['OFFLINE']}`}>
                {displayState}
              </span>
            </div>
            <div className="text-xs text-zinc-500">
              {lastAction 
                ? `Last: ${lastAction.type} ${lastAction.symbol || ''} (${lastAction.time || 'recently'})`
                : 'No recent actions'
              }
            </div>
          </div>
        </div>
        
        {/* Session Badge */}
        <div className="px-4 py-2 rounded-lg bg-cyan-400/10 border border-cyan-400/30">
          <div className="text-xs text-zinc-400">SESSION</div>
          <div className="font-bold text-cyan-400">{marketSession || 'MARKET CLOSED'}</div>
        </div>
        
        {/* Regime Badge */}
        <div className="px-4 py-2 rounded-lg bg-purple-500/10 border border-purple-500/30 cursor-pointer hover:bg-purple-500/20 transition-colors">
          <div className="text-xs text-zinc-400">REGIME</div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-purple-400">{regime?.name || 'HOLD'}</span>
            <span className="font-mono text-xs text-zinc-500">{regime?.score?.toFixed(0) || '--'}</span>
          </div>
        </div>
        
        {/* Brief Me Button */}
        <button 
          onClick={onBriefMe}
          className="px-5 py-3 rounded-xl bg-gradient-to-r from-pink-500/20 to-purple-500/20 border border-pink-500/50 hover:border-pink-500 transition-all group"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-pink-400 group-hover:scale-110 transition-transform" />
            <span className="font-bold text-pink-400">BRIEF ME</span>
          </div>
          <div className="text-xs text-zinc-400">AI Market Report</div>
        </button>
      </div>
      
      {/* Right Side: P&L + Time */}
      <div className="flex items-center gap-6">
        <div className="text-right">
          <div className="text-xs text-zinc-400">TODAY'S P&L</div>
          <div className={`font-mono text-2xl ${todayPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {todayPnl >= 0 ? '+' : ''}${todayPnl?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-zinc-400">OPEN P&L</div>
          <div className={`font-mono text-lg ${openPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {openPnl >= 0 ? '+' : ''}${openPnl?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'}
          </div>
        </div>
        <div className="h-10 w-px bg-zinc-700" />
        <div className="font-mono text-xl text-zinc-400">
          {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      </div>
    </div>
  );
};

// Active Positions Card
const ActivePositionsCard = ({ positions = [], onPositionClick }) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="font-bold text-lg">MY ACTIVE POSITIONS</h2>
          <span className="px-2 py-0.5 rounded bg-zinc-700 text-xs font-mono">
            {positions.length} OPEN
          </span>
        </div>
      </div>
      
      {positions.length === 0 ? (
        <div className="text-center py-8 text-zinc-500">
          <Target className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No open positions</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos, i) => {
            const pnl = pos.unrealized_pnl || pos.pnl || 0;
            const pnlPct = pos.pnl_percent || (pos.current_price && pos.entry_price 
              ? ((pos.current_price - pos.entry_price) / pos.entry_price * 100) 
              : 0);
            const isPositive = pnl >= 0;
            
            return (
              <motion.div
                key={pos.id || pos.symbol}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                onClick={() => openTickerModal(pos.symbol)}
                className={`p-4 rounded-xl bg-zinc-800/50 border cursor-pointer transition-all hover:scale-[1.01] ${
                  isPositive ? 'border-emerald-500/30 hover:border-emerald-500/50' : 'border-red-500/30 hover:border-red-500/50'
                }`}
                style={{ boxShadow: isPositive ? '0 0 15px rgba(0, 255, 148, 0.1)' : '0 0 15px rgba(255, 46, 46, 0.1)' }}
              >
                <div className="flex justify-between items-start mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${
                      isPositive ? 'bg-emerald-500/20' : 'bg-red-500/20'
                    }`}>
                      <span className={`font-bold text-lg ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.symbol}
                      </span>
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold">{pos.symbol}</span>
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          pos.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {pos.direction?.toUpperCase() || 'LONG'}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400 text-xs">
                          {pos.timeframe || 'INTRADAY'}
                        </span>
                      </div>
                      <div className="text-xs text-zinc-400">Click to view chart with bot annotations</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={`font-mono text-2xl ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}${pnl.toFixed(2)}
                    </div>
                    <div className={`text-sm ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}{pnlPct.toFixed(2)}%
                    </div>
                  </div>
                </div>
                
                {/* Quick Stats */}
                <div className="grid grid-cols-5 gap-2 text-xs">
                  <div className="p-2 rounded bg-black/30 text-center">
                    <div className="text-zinc-500">Shares</div>
                    <div className="font-mono font-bold">{pos.shares || pos.quantity || '--'}</div>
                  </div>
                  <div className="p-2 rounded bg-black/30 text-center">
                    <div className="text-zinc-500">Entry</div>
                    <div className="font-mono font-bold">${pos.entry_price?.toFixed(2) || '--'}</div>
                  </div>
                  <div className="p-2 rounded bg-black/30 text-center">
                    <div className="text-zinc-500">Current</div>
                    <div className={`font-mono font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      ${pos.current_price?.toFixed(2) || '--'}
                    </div>
                  </div>
                  <div className="p-2 rounded bg-black/30 text-center border border-red-500/30">
                    <div className="text-red-400">Stop</div>
                    <div className="font-mono font-bold text-red-400">${pos.stop_price?.toFixed(2) || '--'}</div>
                  </div>
                  <div className="p-2 rounded bg-black/30 text-center border border-emerald-500/30">
                    <div className="text-emerald-400">Target</div>
                    <div className="font-mono font-bold text-emerald-400">
                      ${pos.target_prices?.[0]?.toFixed(2) || pos.target_price?.toFixed(2) || '--'}
                    </div>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Setups I'm Watching Card
const WatchingSetupsCard = ({ setups = [] }) => {
  const { openTickerModal } = useTickerModal();
  
  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-3">
          <Eye className="w-5 h-5 text-purple-400" />
          <h2 className="font-bold text-lg">SETUPS I'M WATCHING</h2>
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
  
  // Initial fetch and auto-refresh
  useEffect(() => {
    fetchDashboardData();
    
    const interval = setInterval(fetchDashboardData, DASHBOARD_REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchDashboardData]);
  
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
  
  return (
    <div className="space-y-4">
      {/* Header */}
      <DashboardHeader
        botStatus={effectiveBotStatus}
        marketSession={marketSession}
        regime={regime}
        todayPnl={effectiveTodayPnl}
        openPnl={effectiveOpenPnl}
        onBriefMe={onBriefMe}
      />
      
      {/* Bot Performance Chart - Always Visible */}
      <BotPerformanceChart
        trades={closedTrades}
        todayPnl={effectiveTodayPnl}
        onViewFullAnalytics={onViewAnalytics}
        autoRefresh={true}
      />
      
      {/* Main Grid */}
      <div className="grid grid-cols-12 gap-4">
        {/* Left Column (8 cols) */}
        <div className="col-span-8 space-y-4">
          {/* Bot's Brain Panel */}
          <BotBrainPanel
            botStatus={effectiveBotStatus}
            openTrades={effectiveOpenTrades}
            watchingSetups={effectiveWatchingSetups}
            onViewHistory={onViewHistory}
            autoRefresh={true}
          />
          
          {/* Active Positions */}
          <ActivePositionsCard positions={effectiveOpenTrades} />
          
          {/* Setups I'm Watching */}
          <WatchingSetupsCard setups={effectiveWatchingSetups} />
        </div>
        
        {/* Right Column (4 cols) - AI Assistant + other widgets */}
        <div className="col-span-4 space-y-4">
          {children}
        </div>
      </div>
      
      {/* Scanner Alerts Strip */}
      <ScannerAlertsStrip 
        alerts={scannerAlerts}
        onViewAll={onViewAllAlerts}
      />
    </div>
  );
};

export default NewDashboard;
