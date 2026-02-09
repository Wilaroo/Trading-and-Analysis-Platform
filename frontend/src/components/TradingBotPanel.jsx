/**
 * TradingBotPanel - Autonomous Trading Bot Control & Display
 * Displays bot status, pending/open trades, trade explanations, and P&L
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  Play,
  Pause,
  Settings,
  X,
  Check,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  Shield,
  Clock,
  Activity,
  ChevronDown,
  ChevronUp,
  Info,
  Zap,
  RefreshCw,
  ExternalLink,
  BarChart3,
  Eye,
  Sliders,
  Power,
  Ban
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Trade status colors
const STATUS_CONFIG = {
  pending: { color: 'text-yellow-400', bg: 'bg-yellow-500/20', label: 'AWAITING CONFIRMATION' },
  open: { color: 'text-emerald-400', bg: 'bg-emerald-500/20', label: 'OPEN' },
  closed: { color: 'text-zinc-400', bg: 'bg-zinc-500/20', label: 'CLOSED' },
  rejected: { color: 'text-red-400', bg: 'bg-red-500/20', label: 'REJECTED' },
  cancelled: { color: 'text-orange-400', bg: 'bg-orange-500/20', label: 'CANCELLED' }
};

// Direction indicator
const DirectionBadge = ({ direction }) => {
  const isLong = direction === 'long';
  return (
    <span className={`flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
      isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
    }`}>
      {isLong ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {isLong ? 'LONG' : 'SHORT'}
    </span>
  );
};

// P&L display component
const PnLDisplay = ({ pnl, pnlPct, size = 'sm' }) => {
  const isPositive = pnl >= 0;
  const textSize = size === 'lg' ? 'text-lg' : 'text-sm';
  
  return (
    <div className={`flex items-center gap-1 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
      <span className={`font-mono font-bold ${textSize}`}>
        {isPositive ? '+' : ''}{pnl?.toFixed(2) || '0.00'}
      </span>
      <span className="text-xs opacity-70">
        ({isPositive ? '+' : ''}{pnlPct?.toFixed(2) || '0.00'}%)
      </span>
    </div>
  );
};

// Trade Card Component
const TradeCard = ({ trade, onConfirm, onReject, onClose, onTickerClick, showCloseReason = false }) => {
  const [expanded, setExpanded] = useState(false);
  const status = STATUS_CONFIG[trade.status] || STATUS_CONFIG.pending;
  const isPending = trade.status === 'pending';
  const isOpen = trade.status === 'open';
  const isClosed = trade.status === 'closed';
  
  // Close reason display
  const closeReasonLabel = {
    'manual': 'Manually Closed',
    'stop_loss': 'Stop Loss Hit',
    'target_hit': 'Target Hit',
    'rejected': 'Rejected'
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className={`rounded-lg border ${status.bg} ${status.color.replace('text-', 'border-')}/30 overflow-hidden`}
      data-testid={`trade-card-${trade.id}`}
    >
      {/* Header */}
      <div className="p-3">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <button 
              onClick={() => onTickerClick?.(trade.symbol)}
              className="text-lg font-bold text-white hover:text-cyan-400 transition-colors cursor-pointer"
              title={`View ${trade.symbol} details`}
              data-testid={`ticker-click-${trade.symbol}`}
            >
              {trade.symbol}
            </button>
            <DirectionBadge direction={trade.direction} />
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${status.bg} ${status.color}`}>
              {trade.quality_grade}
            </span>
            {isClosed && trade.close_reason && (
              <span className={`text-xs px-1.5 py-0.5 rounded ${
                trade.close_reason === 'stop_loss' ? 'bg-red-500/20 text-red-400' : 
                trade.close_reason === 'target_hit' ? 'bg-emerald-500/20 text-emerald-400' : 
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {closeReasonLabel[trade.close_reason] || trade.close_reason}
              </span>
            )}
          </div>
          
          {isOpen && (
            <PnLDisplay pnl={trade.unrealized_pnl} pnlPct={trade.pnl_pct} />
          )}
          {isClosed && (
            <PnLDisplay pnl={trade.realized_pnl} pnlPct={(trade.realized_pnl / (trade.fill_price * trade.shares) * 100)} />
          )}
        </div>
        
        {/* Setup info */}
        <div className="text-sm text-zinc-300 mb-2">
          {trade.setup_type?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
        </div>
        
        {/* Key metrics */}
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div>
            <span className="text-zinc-500">Shares</span>
            <p className="text-white font-mono">{trade.shares}</p>
          </div>
          <div>
            <span className="text-zinc-500">{isClosed ? 'Fill' : 'Entry'}</span>
            <p className="text-white font-mono">${(trade.fill_price || trade.entry_price)?.toFixed(2)}</p>
          </div>
          {isClosed ? (
            <div>
              <span className="text-zinc-500">Exit</span>
              <p className="text-white font-mono">${trade.exit_price?.toFixed(2)}</p>
            </div>
          ) : (
            <div>
              <span className="text-zinc-500">Stop</span>
              <p className="text-red-400 font-mono">${trade.stop_price?.toFixed(2)}</p>
            </div>
          )}
          <div>
            <span className="text-zinc-500">{isClosed ? 'P&L' : 'Target'}</span>
            {isClosed ? (
              <p className={`font-mono ${trade.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {trade.realized_pnl >= 0 ? '+' : ''}${trade.realized_pnl?.toFixed(2)}
              </p>
            ) : (
              <p className="text-emerald-400 font-mono">${trade.target_prices?.[0]?.toFixed(2)}</p>
            )}
          </div>
        </div>
        
        {/* Risk metrics */}
        <div className="flex items-center gap-4 mt-2 text-xs">
          <div className="flex items-center gap-1">
            <Shield className="w-3 h-3 text-orange-400" />
            <span className="text-zinc-400">Risk:</span>
            <span className="text-orange-400 font-mono">${trade.risk_amount?.toFixed(0)}</span>
          </div>
          <div className="flex items-center gap-1">
            <Target className="w-3 h-3 text-emerald-400" />
            <span className="text-zinc-400">R:R</span>
            <span className="text-emerald-400 font-mono">{trade.risk_reward_ratio?.toFixed(1)}:1</span>
          </div>
          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3 text-zinc-400" />
            <span className="text-zinc-400">{trade.estimated_duration}</span>
          </div>
        </div>
      </div>
      
      {/* Expandable explanation */}
      {trade.explanation && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full px-3 py-2 flex items-center justify-between text-xs text-cyan-400 hover:bg-white/5 border-t border-zinc-700/50"
          >
            <span className="flex items-center gap-1">
              <Info className="w-3 h-3" />
              Trade Explanation
            </span>
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          
          <AnimatePresence>
            {expanded && (
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: 'auto' }}
                exit={{ height: 0 }}
                className="overflow-hidden"
              >
                <div className="p-3 bg-zinc-800/50 text-xs space-y-2">
                  <p className="text-zinc-300">{trade.explanation.summary}</p>
                  
                  <div>
                    <span className="text-zinc-500">Entry Logic: </span>
                    <span className="text-zinc-300">{trade.explanation.entry_logic}</span>
                  </div>
                  
                  <div>
                    <span className="text-zinc-500">Exit Logic: </span>
                    <span className="text-zinc-300">{trade.explanation.exit_logic}</span>
                  </div>
                  
                  <div>
                    <span className="text-zinc-500">Position Sizing: </span>
                    <span className="text-zinc-300">{trade.explanation.position_sizing_logic}</span>
                  </div>
                  
                  {trade.explanation.warnings?.length > 0 && (
                    <div className="mt-2 p-2 bg-yellow-500/10 rounded border border-yellow-500/20">
                      <span className="text-yellow-400 flex items-center gap-1 mb-1">
                        <AlertTriangle className="w-3 h-3" />
                        Warnings
                      </span>
                      <ul className="text-yellow-300 list-disc list-inside">
                        {trade.explanation.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
      
      {/* Action buttons */}
      {isPending && (
        <div className="flex border-t border-zinc-700/50">
          <button
            onClick={() => onConfirm(trade.id)}
            className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/10"
            data-testid={`confirm-trade-${trade.id}`}
          >
            <Check className="w-4 h-4" />
            Execute Trade
          </button>
          <button
            onClick={() => onReject(trade.id)}
            className="flex-1 flex items-center justify-center gap-2 py-2 text-sm font-medium text-red-400 hover:bg-red-500/10 border-l border-zinc-700/50"
            data-testid={`reject-trade-${trade.id}`}
          >
            <X className="w-4 h-4" />
            Reject
          </button>
        </div>
      )}
      
      {isOpen && (
        <div className="border-t border-zinc-700/50">
          <button
            onClick={() => onClose(trade.id)}
            className="w-full flex items-center justify-center gap-2 py-2 text-sm font-medium text-orange-400 hover:bg-orange-500/10"
            data-testid={`close-trade-${trade.id}`}
          >
            <Ban className="w-4 h-4" />
            Close Position
          </button>
        </div>
      )}
    </motion.div>
  );
};

// Mode Selector Component
const ModeSelector = ({ currentMode, onModeChange }) => {
  const modes = [
    { value: 'autonomous', label: 'Autonomous', icon: Zap, color: 'text-emerald-400', desc: 'Auto-execute trades' },
    { value: 'confirmation', label: 'Confirmation', icon: Eye, color: 'text-cyan-400', desc: 'Require approval' },
    { value: 'paused', label: 'Paused', icon: Pause, color: 'text-zinc-400', desc: 'No scanning' }
  ];
  
  return (
    <div className="grid grid-cols-3 gap-2">
      {modes.map(mode => {
        const Icon = mode.icon;
        const isActive = currentMode === mode.value;
        return (
          <button
            key={mode.value}
            onClick={() => onModeChange(mode.value)}
            className={`p-2 rounded-lg border text-center transition-all ${
              isActive 
                ? `${mode.color} bg-white/10 border-current` 
                : 'text-zinc-400 border-zinc-700 hover:border-zinc-600'
            }`}
            data-testid={`mode-${mode.value}`}
          >
            <Icon className="w-4 h-4 mx-auto mb-1" />
            <div className="text-xs font-medium">{mode.label}</div>
          </button>
        );
      })}
    </div>
  );
};

// Daily Stats Summary
const DailyStatsSummary = ({ stats }) => {
  const netPnl = stats?.net_pnl || 0;
  const isPositive = netPnl >= 0;
  
  return (
    <div className={`p-3 rounded-lg ${isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10'} border ${isPositive ? 'border-emerald-500/30' : 'border-red-500/30'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-zinc-400">Today's P&L</span>
        <span className={`text-lg font-bold font-mono ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {isPositive ? '+' : ''}${netPnl.toFixed(2)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-zinc-500">Trades</span>
          <p className="text-white font-mono">{stats?.trades_executed || 0}</p>
        </div>
        <div>
          <span className="text-zinc-500">Win Rate</span>
          <p className={`font-mono ${stats?.win_rate > 50 ? 'text-emerald-400' : 'text-zinc-300'}`}>
            {stats?.win_rate?.toFixed(0) || 0}%
          </p>
        </div>
        <div>
          <span className="text-zinc-500">W/L</span>
          <p className="text-white font-mono">{stats?.trades_won || 0}/{stats?.trades_lost || 0}</p>
        </div>
      </div>
      
      {stats?.daily_limit_hit && (
        <div className="mt-2 p-2 bg-red-500/20 rounded text-xs text-red-400 flex items-center gap-1">
          <AlertTriangle className="w-3 h-3" />
          Daily loss limit reached - Bot paused
        </div>
      )}
    </div>
  );
};

// Main Component
const TradingBotPanel = ({ className = '' }) => {
  const [status, setStatus] = useState(null);
  const [pendingTrades, setPendingTrades] = useState([]);
  const [openTrades, setOpenTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [activeTab, setActiveTab] = useState('pending');
  
  const eventSourceRef = useRef(null);
  
  // Fetch bot status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/status`);
      const data = await res.json();
      if (data.success) {
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch bot status:', err);
    }
  }, []);
  
  // Fetch trades
  const fetchTrades = useCallback(async () => {
    try {
      const [pendingRes, openRes] = await Promise.all([
        fetch(`${API_URL}/api/trading-bot/trades/pending`),
        fetch(`${API_URL}/api/trading-bot/trades/open`)
      ]);
      
      const pendingData = await pendingRes.json();
      const openData = await openRes.json();
      
      if (pendingData.success) setPendingTrades(pendingData.trades || []);
      if (openData.success) setOpenTrades(openData.trades || []);
      
    } catch (err) {
      console.error('Failed to fetch trades:', err);
    }
    setLoading(false);
  }, []);
  
  // Start/Stop bot
  const toggleBot = async () => {
    setActionLoading('toggle');
    try {
      const endpoint = status?.running ? 'stop' : 'start';
      await fetch(`${API_URL}/api/trading-bot/${endpoint}`, { method: 'POST' });
      await fetchStatus();
    } catch (err) {
      console.error('Failed to toggle bot:', err);
    }
    setActionLoading(null);
  };
  
  // Change mode
  const changeMode = async (mode) => {
    setActionLoading('mode');
    try {
      await fetch(`${API_URL}/api/trading-bot/mode/${mode}`, { method: 'POST' });
      await fetchStatus();
    } catch (err) {
      console.error('Failed to change mode:', err);
    }
    setActionLoading(null);
  };
  
  // Confirm trade
  const confirmTrade = async (tradeId) => {
    setActionLoading(tradeId);
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/trades/${tradeId}/confirm`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        await fetchTrades();
        await fetchStatus();
      }
    } catch (err) {
      console.error('Failed to confirm trade:', err);
    }
    setActionLoading(null);
  };
  
  // Reject trade
  const rejectTrade = async (tradeId) => {
    setActionLoading(tradeId);
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/trades/${tradeId}/reject`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        await fetchTrades();
      }
    } catch (err) {
      console.error('Failed to reject trade:', err);
    }
    setActionLoading(null);
  };
  
  // Close trade
  const closeTrade = async (tradeId) => {
    if (!window.confirm('Are you sure you want to close this position?')) return;
    
    setActionLoading(tradeId);
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/trades/${tradeId}/close`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        await fetchTrades();
        await fetchStatus();
      }
    } catch (err) {
      console.error('Failed to close trade:', err);
    }
    setActionLoading(null);
  };
  
  // Connect to SSE stream
  useEffect(() => {
    const connectStream = () => {
      const eventSource = new EventSource(`${API_URL}/api/trading-bot/stream`);
      eventSourceRef.current = eventSource;
      
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pending' || data.type === 'executed' || data.type === 'closed' || data.type === 'updated') {
            fetchTrades();
            fetchStatus();
          }
        } catch (err) {
          // Ignore parse errors
        }
      };
      
      eventSource.onerror = () => {
        setTimeout(connectStream, 5000);
      };
    };
    
    connectStream();
    
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [fetchTrades, fetchStatus]);
  
  // Initial load
  useEffect(() => {
    fetchStatus();
    fetchTrades();
    
    const interval = setInterval(() => {
      fetchStatus();
      fetchTrades();
    }, 10000);
    
    return () => clearInterval(interval);
  }, [fetchStatus, fetchTrades]);
  
  const isRunning = status?.running;
  const mode = status?.mode || 'confirmation';
  const dailyStats = status?.daily_stats;
  const account = status?.account;
  
  return (
    <div className={`bg-zinc-900/95 backdrop-blur-sm border border-zinc-700/50 rounded-xl overflow-hidden ${className}`} data-testid="trading-bot-panel">
      {/* Header */}
      <div className="p-4 border-b border-zinc-700/50">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Bot className={`w-5 h-5 ${isRunning ? 'text-emerald-400' : 'text-zinc-500'}`} />
            <h3 className="font-semibold text-white">Trading Bot</h3>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              isRunning ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'
            }`}>
              {isRunning ? 'ACTIVE' : 'STOPPED'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={`p-2 rounded-lg transition-colors ${
                showSettings ? 'bg-cyan-500/20 text-cyan-400' : 'bg-zinc-700 text-zinc-400 hover:text-white'
              }`}
              data-testid="bot-settings-btn"
            >
              <Sliders className="w-4 h-4" />
            </button>
            
            <button
              onClick={toggleBot}
              disabled={actionLoading === 'toggle'}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg font-medium text-sm transition-colors ${
                isRunning 
                  ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' 
                  : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
              }`}
              data-testid="toggle-bot-btn"
            >
              {actionLoading === 'toggle' ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : isRunning ? (
                <Pause className="w-4 h-4" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              {isRunning ? 'Stop' : 'Start'}
            </button>
          </div>
        </div>
        
        {/* Mode selector */}
        <ModeSelector currentMode={mode} onModeChange={changeMode} />
      </div>
      
      {/* Settings Panel */}
      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden border-b border-zinc-700/50"
          >
            <div className="p-4 bg-zinc-800/50 space-y-3">
              <h4 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                <Shield className="w-4 h-4 text-cyan-400" />
                Risk Parameters
              </h4>
              
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-2 bg-zinc-700/50 rounded">
                  <span className="text-zinc-500">Max Risk/Trade</span>
                  <p className="text-white font-mono">${status?.risk_params?.max_risk_per_trade?.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-zinc-700/50 rounded">
                  <span className="text-zinc-500">Max Daily Loss</span>
                  <p className="text-white font-mono">${status?.risk_params?.max_daily_loss?.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-zinc-700/50 rounded">
                  <span className="text-zinc-500">Capital</span>
                  <p className="text-white font-mono">${status?.risk_params?.starting_capital?.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-zinc-700/50 rounded">
                  <span className="text-zinc-500">Min R:R</span>
                  <p className="text-white font-mono">{status?.risk_params?.min_risk_reward}:1</p>
                </div>
              </div>
              
              {account && (
                <div className="mt-3 p-2 bg-zinc-700/30 rounded">
                  <span className="text-xs text-zinc-500">Alpaca Account (Paper)</span>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-sm text-white">${account.equity?.toLocaleString()}</span>
                    <span className="text-xs text-emerald-400">Buying Power: ${account.buying_power?.toLocaleString()}</span>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* Daily Stats */}
      <div className="p-4 border-b border-zinc-700/50">
        <DailyStatsSummary stats={dailyStats} />
      </div>
      
      {/* Tabs */}
      <div className="flex border-b border-zinc-700/50">
        <button
          onClick={() => setActiveTab('pending')}
          className={`flex-1 py-2 text-sm font-medium ${
            activeTab === 'pending' ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-zinc-400'
          }`}
        >
          Pending ({pendingTrades.length})
        </button>
        <button
          onClick={() => setActiveTab('open')}
          className={`flex-1 py-2 text-sm font-medium ${
            activeTab === 'open' ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-zinc-400'
          }`}
        >
          Open ({openTrades.length})
        </button>
      </div>
      
      {/* Trade Lists */}
      <div className="p-4 max-h-[400px] overflow-y-auto space-y-3">
        {loading ? (
          <div className="text-center py-8 text-zinc-500">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" />
            Loading trades...
          </div>
        ) : activeTab === 'pending' ? (
          pendingTrades.length === 0 ? (
            <div className="text-center py-8 text-zinc-500">
              <Bot className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No pending trades</p>
              <p className="text-xs mt-1">Bot is scanning for opportunities...</p>
            </div>
          ) : (
            <AnimatePresence>
              {pendingTrades.map(trade => (
                <TradeCard
                  key={trade.id}
                  trade={trade}
                  onConfirm={confirmTrade}
                  onReject={rejectTrade}
                  onClose={closeTrade}
                />
              ))}
            </AnimatePresence>
          )
        ) : (
          openTrades.length === 0 ? (
            <div className="text-center py-8 text-zinc-500">
              <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No open positions</p>
            </div>
          ) : (
            <AnimatePresence>
              {openTrades.map(trade => (
                <TradeCard
                  key={trade.id}
                  trade={trade}
                  onConfirm={confirmTrade}
                  onReject={rejectTrade}
                  onClose={closeTrade}
                />
              ))}
            </AnimatePresence>
          )
        )}
      </div>
    </div>
  );
};

export default TradingBotPanel;
