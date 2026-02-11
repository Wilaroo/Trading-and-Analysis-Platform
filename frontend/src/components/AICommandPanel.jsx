import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send,
  X,
  Loader2,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Bell,
  Calendar,
  Eye,
  Zap,
  DollarSign,
  BarChart3,
  Target,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  ArrowUpRight,
  RefreshCw,
  Activity,
  Play,
  Pause,
  Power,
  Shield,
  Settings,
  Check
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { formatPrice, formatPercent } from '../utils/tradingUtils';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// ===================== TICKER UTILITIES =====================

const TickerLink = ({ symbol, onClick }) => (
  <button
    onClick={() => onClick(symbol)}
    className="inline-flex items-center gap-0.5 px-1 py-0.5 bg-cyan-500/10 border border-cyan-500/20 rounded text-cyan-400 font-mono font-semibold text-xs hover:bg-cyan-500/20 hover:border-cyan-500/40 transition-colors cursor-pointer"
    data-testid={`ticker-link-${symbol}`}
  >
    {symbol}
    <ArrowUpRight className="w-3 h-3" />
  </button>
);

const TickerAwareText = ({ text, onTickerClick }) => {
  if (!text || typeof text !== 'string') return text;
  const parts = text.split(/(\$?[A-Z]{1,5}(?=[\s,.:;!?)}\]"]|$))/g);
  const knownTickers = new Set([
    'AAPL','MSFT','NVDA','TSLA','AMD','META','GOOGL','AMZN','GOOG','NFLX',
    'SPY','QQQ','IWM','DIA','VIX','SOFI','PLTR','RIVN','INTC','UBER',
    'COST','WMT','TGT','JPM','BAC','GS','V','MA','PYPL','SQ','SHOP',
    'CRM','ORCL','ADBE','NOW','SNOW','NET','CRWD','ZS','DDOG','MDB',
    'COIN','HOOD','RBLX','ROKU','SNAP','PINS','SPOT','SE','MELI',
    'BA','LMT','GE','CAT','DE','HON','MMM','UNH','JNJ','PFE','MRNA',
    'LLY','ABBV','BMY','GILD','AMGN','XOM','CVX','COP','SLB','OXY',
    'AVGO','QCOM','MU','AMAT','LRCX','KLAC','TXN','MRVL','ARM',
    'F','GM','TM','NIO','XPEV','LI','LCID','FSR','DIS','CMCSA','WBD',
    'T','VZ','TMUS','KO','PEP','MCD','SBUX','NKE','LULU'
  ]);
  
  return parts.map((part, i) => {
    const clean = part.replace('$', '');
    if (knownTickers.has(clean) && part.length >= 2) {
      return <TickerLink key={i} symbol={clean} onClick={onTickerClick} />;
    }
    return part;
  });
};

const createMarkdownComponents = (onTickerClick) => ({
  p: ({ children }) => <p className="mb-2 last:mb-0">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} /> : children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-zinc-200">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} /> : children}</li>,
  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} /> : children}</strong>,
  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
  code: ({ children }) => <code className="bg-black/30 px-1 rounded text-amber-400">{children}</code>,
});

// ===================== UI COMPONENTS =====================

const SectionHeader = ({ icon: Icon, title, count, isExpanded, onToggle, action }) => (
  <div 
    className="flex items-center justify-between py-2 px-3 bg-zinc-900/50 rounded-lg cursor-pointer hover:bg-zinc-800/50 transition-colors"
    onClick={onToggle}
  >
    <div className="flex items-center gap-2">
      <Icon className="w-4 h-4 text-cyan-400" />
      <span className="text-sm font-medium text-white">{title}</span>
      {count !== undefined && (
        <span className="text-xs text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">{count}</span>
      )}
    </div>
    <div className="flex items-center gap-2">
      {action}
      {isExpanded ? <ChevronDown className="w-4 h-4 text-zinc-400" /> : <ChevronRight className="w-4 h-4 text-zinc-400" />}
    </div>
  </div>
);

const ChatMessage = ({ message, isUser, onTickerClick }) => {
  const mdComponents = createMarkdownComponents(onTickerClick);
  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
        isUser ? 'bg-cyan-500/20' : 'bg-amber-500/20'
      }`}>
        {isUser ? <User className="w-3 h-3 text-cyan-400" /> : <Bot className="w-3 h-3 text-amber-400" />}
      </div>
      <div className={`flex-1 max-w-[90%] ${isUser ? 'text-right' : ''}`}>
        <div className={`inline-block p-2.5 rounded-lg text-sm ${
          isUser ? 'bg-cyan-500/10 border border-cyan-500/20 text-white' : 'bg-zinc-800/50 border border-white/5 text-zinc-200'
        }`}>
          {isUser ? message.content : (
            <ReactMarkdown components={mdComponents}>{message.content}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
};

const QuickPill = ({ label, onClick, loading, active }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className={`px-2.5 py-1 rounded-full text-xs transition-all ${
      active 
        ? 'bg-cyan-500 text-black font-medium' 
        : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700'
    } disabled:opacity-50`}
  >
    {label}
  </button>
);

// ===================== COACHING ALERT MESSAGE =====================

const CoachingAlertMessage = ({ alert, onExecute, onPass, onHalfSize, onTickerClick, executing }) => {
  const verdictColors = {
    'TAKE': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    'WAIT': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    'PASS': 'bg-red-500/20 text-red-400 border-red-500/30'
  };
  
  const priorityColors = {
    'critical': 'bg-red-500',
    'high': 'bg-amber-500',
    'medium': 'bg-blue-500',
    'low': 'bg-zinc-500'
  };

  return (
    <div className="flex gap-2">
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gradient-to-br from-cyan-500 to-amber-500 flex items-center justify-center">
        <Zap className="w-3 h-3 text-black" />
      </div>
      <div className="flex-1">
        <div className="bg-gradient-to-r from-cyan-900/20 to-amber-900/10 border border-cyan-500/20 rounded-lg p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${priorityColors[alert.priority] || priorityColors.medium}`} />
              <button 
                onClick={() => onTickerClick(alert.symbol)}
                className="text-lg font-bold text-white hover:text-cyan-400 transition-colors"
              >
                {alert.symbol}
              </button>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                alert.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
              }`}>
                {alert.direction?.toUpperCase()}
              </span>
            </div>
            <span className={`text-xs px-2 py-1 rounded border ${verdictColors[alert.verdict] || verdictColors.WAIT}`}>
              {alert.verdict}
            </span>
          </div>
          
          {/* Setup Info */}
          <div className="text-xs text-zinc-400 mb-2">
            {alert.setup_type?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
            {alert.alert_data?.win_rate > 0 && (
              <span className="ml-2 text-zinc-500">
                WR: {(alert.alert_data.win_rate * 100).toFixed(0)}%
              </span>
            )}
            {alert.alert_data?.risk_reward > 0 && (
              <span className="ml-2 text-zinc-500">
                R:R {alert.alert_data.risk_reward.toFixed(1)}:1
              </span>
            )}
          </div>
          
          {/* AI Coaching */}
          <div className="text-sm text-zinc-200 mb-3">
            {alert.coaching || alert.summary}
          </div>
          
          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => onExecute(alert)}
              disabled={executing}
              className="flex items-center gap-1 px-3 py-1.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-medium hover:bg-emerald-500/30 transition-colors disabled:opacity-50"
              data-testid={`execute-alert-${alert.symbol}`}
            >
              {executing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              Execute
            </button>
            <button
              onClick={() => onHalfSize(alert)}
              disabled={executing}
              className="flex items-center gap-1 px-3 py-1.5 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-lg text-xs font-medium hover:bg-amber-500/30 transition-colors disabled:opacity-50"
              data-testid={`half-size-alert-${alert.symbol}`}
            >
              Half Size
            </button>
            <button
              onClick={() => onPass(alert)}
              className="flex items-center gap-1 px-3 py-1.5 bg-zinc-500/20 text-zinc-400 border border-zinc-500/30 rounded-lg text-xs font-medium hover:bg-zinc-500/30 transition-colors"
              data-testid={`pass-alert-${alert.symbol}`}
            >
              <X className="w-3 h-3" />
              Pass
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ===================== CONFIRMATION DIALOG =====================

const ConfirmationDialog = ({ isOpen, trade, onConfirm, onCancel, loading }) => {
  if (!isOpen || !trade) return null;
  
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" data-testid="trade-confirmation-dialog">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-zinc-900 border border-white/10 rounded-xl p-5 max-w-md w-full mx-4"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
            <Target className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white">Confirm Trade</h3>
            <p className="text-xs text-zinc-500">Review before executing</p>
          </div>
        </div>
        
        <div className="bg-zinc-800/50 rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xl font-bold text-white">{trade.symbol}</span>
            <span className={`px-2 py-1 rounded text-sm font-medium ${
              trade.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
            }`}>
              {trade.direction?.toUpperCase()}
            </span>
          </div>
          
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-zinc-500">Setup</span>
              <p className="text-white">{trade.setup_type?.replace(/_/g, ' ')}</p>
            </div>
            <div>
              <span className="text-zinc-500">Size</span>
              <p className="text-white">{trade.halfSize ? 'Half Position' : 'Full Position'}</p>
            </div>
            <div>
              <span className="text-zinc-500">Entry</span>
              <p className="text-white font-mono">${trade.alert_data?.trigger_price?.toFixed(2) || 'Market'}</p>
            </div>
            <div>
              <span className="text-zinc-500">Stop</span>
              <p className="text-red-400 font-mono">${trade.alert_data?.stop_loss?.toFixed(2) || '--'}</p>
            </div>
            <div>
              <span className="text-zinc-500">Target</span>
              <p className="text-emerald-400 font-mono">${trade.alert_data?.target?.toFixed(2) || '--'}</p>
            </div>
            <div>
              <span className="text-zinc-500">R:R</span>
              <p className="text-white">{trade.alert_data?.risk_reward?.toFixed(1) || '--'}:1</p>
            </div>
          </div>
        </div>
        
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 py-2 bg-zinc-700 text-white rounded-lg hover:bg-zinc-600 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 py-2 bg-cyan-500 text-black font-medium rounded-lg hover:bg-cyan-400 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Confirm Trade
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// ===================== BOT STATUS HEADER =====================

const BotStatusHeader = ({ status, onToggle, onModeChange, loading }) => {
  const isRunning = status?.running;
  const mode = status?.mode || 'confirmation';
  const pnl = status?.daily_stats?.net_pnl || 0;
  const openCount = status?.open_trades_count || 0;
  const pendingCount = status?.pending_trades_count || 0;
  
  return (
    <div className="flex items-center justify-between p-2 bg-zinc-900/70 border-b border-white/10">
      {/* Left: Bot Status & P&L */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          disabled={loading}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
            isRunning 
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30' 
              : 'bg-zinc-700 text-zinc-300 border border-zinc-600 hover:bg-zinc-600'
          }`}
          data-testid="bot-toggle"
        >
          {loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : isRunning ? (
            <Activity className="w-3 h-3" />
          ) : (
            <Power className="w-3 h-3" />
          )}
          {isRunning ? 'RUNNING' : 'STOPPED'}
        </button>
        
        <div className="flex items-center gap-2 text-xs">
          <span className={`font-mono font-semibold ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
          </span>
          <span className="text-zinc-500">|</span>
          <span className="text-zinc-400">
            {openCount} open
          </span>
          {pendingCount > 0 && (
            <>
              <span className="text-zinc-500">|</span>
              <span className="text-amber-400">{pendingCount} pending</span>
            </>
          )}
        </div>
      </div>
      
      {/* Right: Mode Selector */}
      <div className="flex items-center gap-1">
        {['confirmation', 'auto', 'paused'].map(m => {
          const icons = { confirmation: Shield, auto: Zap, paused: Pause };
          const Icon = icons[m];
          const isActive = mode === m;
          return (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${
                isActive
                  ? m === 'auto' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : m === 'confirmation' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                    : 'bg-zinc-600 text-zinc-300 border border-zinc-500'
                  : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
              }`}
              data-testid={`mode-${m}`}
            >
              <Icon className="w-3 h-3" />
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          );
        })}
      </div>
    </div>
  );
};

// ===================== MAIN COMPONENT =====================

const AICommandPanel = ({ 
  onTickerSelect,
  watchlist = [],
  alerts = [],
  opportunities = [],
  earnings = [],
  scanResults = [],
  isConnected = false,
  onRefresh
}) => {
  // Chat state
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(`session_${Date.now()}`);
  
  // Section expansion state
  const [expandedSections, setExpandedSections] = useState({
    botTrades: true,
    earnings: false,
    watchlist: false,
    scanner: false
  });
  
  // Bot state
  const [botStatus, setBotStatus] = useState(null);
  const [botTrades, setBotTrades] = useState({ pending: [], open: [], closed: [], daily_stats: {} });
  const [botTradesTab, setBotTradesTab] = useState('open');
  const [botLoading, setBotLoading] = useState(false);
  
  // Coaching alerts state
  const [coachingAlerts, setCoachingAlerts] = useState([]);
  const [dismissedAlerts, setDismissedAlerts] = useState(new Set());
  const [lastCoachingFetch, setLastCoachingFetch] = useState(null);
  
  // Confirmation dialog
  const [confirmDialog, setConfirmDialog] = useState({ isOpen: false, trade: null });
  const [executing, setExecuting] = useState(false);
  
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Toggle section
  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };
  
  // ===================== BOT API CALLS =====================
  
  const fetchBotStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/status`);
      const data = await res.json();
      if (data.success) {
        setBotStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch bot status:', err);
    }
  }, []);
  
  const fetchBotTrades = useCallback(async () => {
    try {
      const res = await api.get('/api/trading-bot/trades/all');
      if (res.data?.success) {
        setBotTrades(res.data);
      }
    } catch (err) {
      // Silent fail
    }
  }, []);
  
  const toggleBot = async () => {
    setBotLoading(true);
    try {
      const endpoint = botStatus?.running ? 'stop' : 'start';
      await fetch(`${API_URL}/api/trading-bot/${endpoint}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(botStatus?.running ? 'Bot stopped' : 'Bot started');
    } catch (err) {
      toast.error('Failed to toggle bot');
    }
    setBotLoading(false);
  };
  
  const changeMode = async (mode) => {
    try {
      await fetch(`${API_URL}/api/trading-bot/mode/${mode}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(`Mode changed to ${mode}`);
    } catch (err) {
      toast.error('Failed to change mode');
    }
  };
  
  // ===================== COACHING ALERTS =====================
  
  const fetchCoachingAlerts = useCallback(async () => {
    try {
      const params = lastCoachingFetch ? `?since=${lastCoachingFetch}` : '';
      const res = await fetch(`${API_URL}/api/assistant/coach/scanner-notifications${params}`);
      const data = await res.json();
      
      if (data.success && data.notifications?.length > 0) {
        const newAlerts = data.notifications.filter(a => !dismissedAlerts.has(a.timestamp));
        
        if (newAlerts.length > 0) {
          setCoachingAlerts(prev => {
            const existing = new Set(prev.map(a => a.timestamp));
            const unique = newAlerts.filter(a => !existing.has(a.timestamp));
            return [...prev, ...unique].slice(-10); // Keep last 10
          });
          
          // Show toast for new alerts
          newAlerts.forEach(alert => {
            toast.info(
              `🎯 ${alert.symbol}: ${alert.verdict} - ${alert.summary?.slice(0, 50)}...`,
              { duration: 8000 }
            );
          });
        }
      }
      
      setLastCoachingFetch(data.timestamp);
    } catch (err) {
      console.error('Failed to fetch coaching alerts:', err);
    }
  }, [lastCoachingFetch, dismissedAlerts]);
  
  // ===================== TRADE EXECUTION =====================
  
  const executeFromAlert = async (alert, halfSize = false) => {
    // Show confirmation dialog
    setConfirmDialog({
      isOpen: true,
      trade: { ...alert, halfSize }
    });
  };
  
  const confirmTrade = async () => {
    const trade = confirmDialog.trade;
    if (!trade) return;
    
    setExecuting(true);
    try {
      // Submit trade to bot
      const payload = {
        symbol: trade.symbol,
        direction: trade.direction || 'long',
        setup_type: trade.setup_type,
        entry_price: trade.alert_data?.trigger_price || trade.alert_data?.current_price,
        stop_price: trade.alert_data?.stop_loss,
        target_prices: [trade.alert_data?.target],
        half_size: trade.halfSize,
        source: 'ai_coaching'
      };
      
      const res = await fetch(`${API_URL}/api/trading-bot/trades/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Trade submitted: ${trade.symbol} ${trade.direction?.toUpperCase()}`);
        
        // Add confirmation to chat
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `✅ **Trade Submitted**: ${trade.symbol} ${trade.direction?.toUpperCase()}\n\n` +
            `- Entry: $${payload.entry_price?.toFixed(2) || 'Market'}\n` +
            `- Stop: $${payload.stop_price?.toFixed(2)}\n` +
            `- Target: $${payload.target_prices[0]?.toFixed(2)}\n` +
            `- Size: ${trade.halfSize ? 'Half Position' : 'Full Position'}\n\n` +
            `Trade is now pending confirmation.`,
          timestamp: new Date().toISOString()
        }]);
        
        // Dismiss the alert
        setDismissedAlerts(prev => new Set([...prev, trade.timestamp]));
        setCoachingAlerts(prev => prev.filter(a => a.timestamp !== trade.timestamp));
        
        // Refresh trades
        await fetchBotTrades();
      } else {
        toast.error(data.detail || 'Failed to submit trade');
      }
    } catch (err) {
      toast.error('Failed to execute trade');
    }
    
    setExecuting(false);
    setConfirmDialog({ isOpen: false, trade: null });
  };
  
  const passOnAlert = (alert) => {
    setDismissedAlerts(prev => new Set([...prev, alert.timestamp]));
    setCoachingAlerts(prev => prev.filter(a => a.timestamp !== alert.timestamp));
    
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: `⏭️ Passed on ${alert.symbol} ${alert.setup_type?.replace(/_/g, ' ')}`,
      timestamp: new Date().toISOString()
    }]);
  };
  
  // ===================== TRADE COMMANDS =====================
  
  const parseTradeCommand = (text) => {
    const lowerText = text.toLowerCase();
    
    // "take the NVDA trade" / "execute NVDA"
    const takeMatch = lowerText.match(/(?:take|execute|buy|go long)\s+(?:the\s+)?(\w+)/);
    if (takeMatch) {
      const symbol = takeMatch[1].toUpperCase();
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) {
        return { type: 'execute', alert };
      }
    }
    
    // "pass on AMD" / "skip AMD"
    const passMatch = lowerText.match(/(?:pass|skip|ignore)\s+(?:on\s+)?(\w+)/);
    if (passMatch) {
      const symbol = passMatch[1].toUpperCase();
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) {
        return { type: 'pass', alert };
      }
    }
    
    // "half size NVDA" / "take NVDA with half"
    const halfMatch = lowerText.match(/(?:half\s+(?:size|position)?|take\s+\w+\s+(?:with\s+)?half)\s*(\w+)?/);
    if (halfMatch) {
      const symbolFromMatch = halfMatch[1]?.toUpperCase();
      // Also check if symbol is mentioned elsewhere
      const symbolInText = text.match(/\b([A-Z]{1,5})\b/);
      const symbol = symbolFromMatch || symbolInText?.[1];
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) {
        return { type: 'half', alert };
      }
    }
    
    // "show trades" / "my trades"
    if (/(?:show|list|what are|my)\s*(?:open\s+)?trades/.test(lowerText)) {
      return { type: 'show_trades' };
    }
    
    // "stop the bot" / "pause bot"
    if (/(?:stop|pause)\s+(?:the\s+)?bot/.test(lowerText)) {
      return { type: 'stop_bot' };
    }
    
    // "start the bot"
    if (/(?:start|resume)\s+(?:the\s+)?bot/.test(lowerText)) {
      return { type: 'start_bot' };
    }
    
    return null;
  };

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, coachingAlerts]);

  // Send message
  const sendMessage = useCallback(async (messageText = null) => {
    let text = (messageText || input.trim());
    if (!text || isLoading) return;

    // Check for trade commands first
    const command = parseTradeCommand(text);
    if (command) {
      setInput('');
      
      switch (command.type) {
        case 'execute':
          executeFromAlert(command.alert, false);
          return;
        case 'half':
          executeFromAlert(command.alert, true);
          return;
        case 'pass':
          passOnAlert(command.alert);
          return;
        case 'show_trades':
          const tradesText = botTrades.open?.length > 0
            ? botTrades.open.map(t => 
                `• ${t.symbol} ${t.direction?.toUpperCase()}: ${t.shares} sh @ $${t.entry_price?.toFixed(2)} | P&L: $${(t.unrealized_pnl || 0).toFixed(2)}`
              ).join('\n')
            : 'No open trades';
          setMessages(prev => [...prev, 
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: `📊 **Open Trades (${botTrades.open?.length || 0})**\n\n${tradesText}`, timestamp: new Date().toISOString() }
          ]);
          return;
        case 'stop_bot':
          if (botStatus?.running) {
            await toggleBot();
          }
          setMessages(prev => [...prev,
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: '🛑 Bot stopped.', timestamp: new Date().toISOString() }
          ]);
          return;
        case 'start_bot':
          if (!botStatus?.running) {
            await toggleBot();
          }
          setMessages(prev => [...prev,
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: '▶️ Bot started.', timestamp: new Date().toISOString() }
          ]);
          return;
        default:
          break;
      }
    }

    // Auto-detect bare ticker symbol
    const tickerMatch = text.match(/^(\$?[A-Z]{1,5})$/);
    if (tickerMatch) {
      const sym = tickerMatch[1].replace('$', '');
      text = `Give me a full analysis on ${sym}. Include current outlook, key levels, any recent news, strategy fit, and a trade recommendation.`;
    }

    const userMessage = { role: 'user', content: text, timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await api.post('/api/assistant/chat', {
        message: text,
        session_id: sessionId
      });
      
      if (response.data?.response) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date().toISOString()
        }]);
      }
    } catch (err) {
      toast.error('Failed to get response');
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date().toISOString()
      }]);
    }
    setIsLoading(false);
  }, [input, isLoading, sessionId, botTrades, botStatus, coachingAlerts]);

  // Handle ticker click
  const handleTickerClick = useCallback((symbol) => {
    onTickerSelect?.({ symbol, quote: {}, fromSearch: true });
  }, [onTickerSelect]);

  // Poll data
  useEffect(() => {
    fetchBotStatus();
    fetchBotTrades();
    fetchCoachingAlerts();
    
    const statusInterval = setInterval(fetchBotStatus, 10000);
    const tradesInterval = setInterval(fetchBotTrades, 15000);
    const coachingInterval = setInterval(fetchCoachingAlerts, 10000);
    
    return () => {
      clearInterval(statusInterval);
      clearInterval(tradesInterval);
      clearInterval(coachingInterval);
    };
  }, [fetchBotStatus, fetchBotTrades, fetchCoachingAlerts]);

  // Quick actions
  const quickActions = [
    { label: 'My Trades', action: () => sendMessage('Show my open trades') },
    { label: 'Performance', action: () => sendMessage('Analyze my trading performance today.') },
    { label: 'Market', action: () => sendMessage("What's happening in the market today?") },
    { label: 'Rules', action: () => sendMessage('Remind me of my key trading rules.') },
  ];

  return (
    <div className="flex flex-col h-full bg-[#0A0A0A] border border-white/10 rounded-xl overflow-hidden" data-testid="ai-command-panel">
      {/* Confirmation Dialog */}
      <ConfirmationDialog
        isOpen={confirmDialog.isOpen}
        trade={confirmDialog.trade}
        onConfirm={confirmTrade}
        onCancel={() => setConfirmDialog({ isOpen: false, trade: null })}
        loading={executing}
      />
      
      {/* Header with Bot Status */}
      <div className="flex items-center justify-between p-3 border-b border-white/10 bg-gradient-to-r from-cyan-900/20 to-amber-900/10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-amber-500 flex items-center justify-center">
            <Bot className="w-5 h-5 text-black" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white">AI Trading Assistant</h2>
            <p className="text-[10px] text-zinc-500">Scanner + AI + Bot integrated</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-xs text-zinc-400">{isConnected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>
      
      {/* Bot Status Header */}
      <BotStatusHeader
        status={botStatus}
        onToggle={toggleBot}
        onModeChange={changeMode}
        loading={botLoading}
      />

      {/* Chat Input */}
      <div className="p-3 border-b border-white/10">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          {quickActions.map((qa, idx) => (
            <QuickPill key={idx} label={qa.label} onClick={qa.action} loading={isLoading} />
          ))}
        </div>
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="Ask AI, type ticker, or 'take NVDA'..."
            className="flex-1 px-3 py-2 bg-zinc-900 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
            data-testid="ai-chat-input"
          />
          <button
            onClick={() => sendMessage()}
            disabled={!input.trim() || isLoading}
            className="px-3 py-2 bg-cyan-500 text-black rounded-lg hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="ai-chat-send"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto">
        {/* Coaching Alerts (Actionable) */}
        {coachingAlerts.filter(a => !dismissedAlerts.has(a.timestamp)).length > 0 && (
          <div className="p-3 border-b border-white/10 bg-gradient-to-r from-cyan-900/5 to-amber-900/5">
            <div className="flex items-center gap-2 mb-2">
              <Zap className="w-4 h-4 text-amber-400" />
              <span className="text-sm font-medium text-white">AI Coaching Alerts</span>
              <span className="text-xs text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">
                {coachingAlerts.filter(a => !dismissedAlerts.has(a.timestamp)).length}
              </span>
            </div>
            <div className="space-y-3">
              {coachingAlerts.filter(a => !dismissedAlerts.has(a.timestamp)).map((alert, idx) => (
                <CoachingAlertMessage
                  key={alert.timestamp || idx}
                  alert={alert}
                  onExecute={(a) => executeFromAlert(a, false)}
                  onHalfSize={(a) => executeFromAlert(a, true)}
                  onPass={passOnAlert}
                  onTickerClick={handleTickerClick}
                  executing={executing}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Chat Messages */}
        {(messages.length > 0 || isLoading) ? (
          <div className="p-3 border-b border-white/10">
            <div className="space-y-3" data-testid="chat-messages">
              {messages.map((msg, idx) => (
                <ChatMessage key={idx} message={msg} isUser={msg.role === 'user'} onTickerClick={handleTickerClick} />
              ))}
              {isLoading && (
                <div className="flex items-center gap-2 text-zinc-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-xs">Thinking...</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>
        ) : (
          <div className="p-3 border-b border-white/10 text-center py-6">
            <Sparkles className="w-6 h-6 text-amber-400 mx-auto mb-2" />
            <p className="text-xs text-zinc-500">Ask anything, type a ticker, or say "take NVDA" to trade</p>
          </div>
        )}

        {/* Bot Trades Section */}
        <div className="p-3 border-b border-white/10" data-testid="bot-trades-section">
          <SectionHeader 
            icon={Bot} 
            title="Bot Trades" 
            count={(botTrades.pending?.length || 0) + (botTrades.open?.length || 0)}
            isExpanded={expandedSections.botTrades}
            onToggle={() => toggleSection('botTrades')}
            action={
              <button 
                onClick={(e) => { e.stopPropagation(); fetchBotTrades(); }}
                className="p-1 hover:bg-zinc-700 rounded"
              >
                <RefreshCw className="w-3 h-3 text-zinc-400" />
              </button>
            }
          />
          {expandedSections.botTrades && (
            <div className="mt-2">
              {/* Tabs */}
              <div className="flex gap-1 mb-2">
                {['pending', 'open', 'closed'].map(tab => {
                  const count = botTrades[tab]?.length || 0;
                  return (
                    <button
                      key={tab}
                      onClick={() => setBotTradesTab(tab)}
                      className={`flex-1 py-1 px-2 rounded text-[11px] font-medium transition-colors ${
                        botTradesTab === tab
                          ? tab === 'open' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                            : tab === 'pending' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                            : 'bg-zinc-500/20 text-zinc-300 border border-zinc-500/30'
                          : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
                      }`}
                    >
                      {tab.charAt(0).toUpperCase() + tab.slice(1)} ({count})
                    </button>
                  );
                })}
              </div>
              
              {/* Trade List */}
              <div className="space-y-1 max-h-[180px] overflow-y-auto">
                {(botTrades[botTradesTab] || []).length > 0 ? (
                  (botTrades[botTradesTab] || []).slice(0, 8).map((trade, idx) => {
                    const pnl = trade.realized_pnl || trade.unrealized_pnl || 0;
                    const isProfit = pnl >= 0;
                    
                    return (
                      <div 
                        key={trade.id || idx}
                        className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer group"
                        onClick={() => handleTickerClick(trade.symbol)}
                      >
                        <div className="flex items-center gap-2">
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-medium text-white">{trade.symbol}</span>
                              <span className={`text-[9px] px-1 py-0.5 rounded ${
                                trade.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                              }`}>
                                {trade.direction?.toUpperCase()}
                              </span>
                            </div>
                            <span className="text-[10px] text-zinc-500">
                              {trade.setup_type?.replace(/_/g, ' ')} | {trade.shares} sh
                            </span>
                          </div>
                        </div>
                        <span className={`text-xs font-mono font-semibold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
                          ${pnl.toFixed(2)}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-xs text-zinc-500 text-center py-3">
                    {botTradesTab === 'pending' ? 'No pending trades' : 
                     botTradesTab === 'open' ? 'No open positions' : 'No closed trades'}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Earnings Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Calendar} 
            title="Earnings" 
            count={earnings.length}
            isExpanded={expandedSections.earnings}
            onToggle={() => toggleSection('earnings')}
          />
          {expandedSections.earnings && (
            <div className="mt-2 space-y-1 max-h-[120px] overflow-y-auto">
              {earnings.length > 0 ? earnings.slice(0, 5).map((earn, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: earn.symbol, quote: {} })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <span className="text-sm font-medium text-white">{earn.symbol}</span>
                  <span className="text-xs text-zinc-400">{earn.timing || 'BMO'}</span>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No upcoming earnings</p>
              )}
            </div>
          )}
        </div>

        {/* Watchlist Section */}
        <div className="p-3">
          <SectionHeader 
            icon={Eye} 
            title="Watchlist" 
            count={watchlist.length}
            isExpanded={expandedSections.watchlist}
            onToggle={() => toggleSection('watchlist')}
          />
          {expandedSections.watchlist && (
            <div className="mt-2 space-y-1 max-h-[120px] overflow-y-auto">
              {watchlist.length > 0 ? watchlist.slice(0, 8).map((item, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: item.symbol, quote: item })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <span className="text-sm font-medium text-white">{item.symbol}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono text-white">${formatPrice(item.price)}</span>
                    <span className={`text-xs ${item.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(item.change_percent)}
                    </span>
                  </div>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">Watchlist empty</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AICommandPanel;
