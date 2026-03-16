/**
 * SentCom.jsx - Sentient Command
 * 
 * Production component for the unified AI command center.
 * Wired to real /api/sentcom/* endpoints.
 * Uses "we" voice throughout for team partnership feeling.
 * 
 * Updated with glassy mockup styling and unified Trading Bot header controls.
 * 
 * Performance Optimization:
 * - Uses DataCacheContext for persistent data across tab switches
 * - Stale-while-revalidate pattern for instant display
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Clock, Zap, Target, AlertCircle, ArrowRight, 
  CheckCircle, Loader, X, TrendingUp, Activity, ChevronUp, 
  ChevronDown, DollarSign, Gauge, Wifi, Eye, Crosshair,
  MessageSquare, RefreshCw, Bell, Circle, Flame, Radio,
  BarChart3, Newspaper, Sunrise, BookOpen, Sparkles, ChevronRight,
  Play, Pause, Settings, Bot, Sliders, WifiOff, Star, Search
} from 'lucide-react';
import { toast } from 'sonner';
import EnhancedTickerModal from './EnhancedTickerModal';
import { useDataCache } from '../contexts';
import { DynamicRiskBadge, DynamicRiskPanel } from './DynamicRiskPanel';
import StreamOfConsciousness from './StreamOfConsciousness';
import ConversationPanel from './ConversationPanel';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

// Format timestamp to relative time (e.g., "2 mins ago", "Just now")
const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '';
  
  const now = new Date();
  const time = new Date(timestamp);
  const diffMs = now - time;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 10) return 'Just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return time.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

// Format timestamp to full time (e.g., "2:05:36 PM")
const formatFullTime = (timestamp) => {
  if (!timestamp) return '';
  const time = new Date(timestamp);
  return time.toLocaleTimeString('en-US', { 
    hour: 'numeric', 
    minute: '2-digit',
    second: '2-digit',
    hour12: true 
  });
};

// ============================================================================
// TYPING INDICATOR COMPONENT
// ============================================================================

const TypingIndicator = ({ agentName = 'SENTCOM' }) => (
  <motion.div
    initial={{ opacity: 0, y: 10, scale: 0.98 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    exit={{ opacity: 0, y: -10, scale: 0.98 }}
    className="flex items-start gap-3"
  >
    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center flex-shrink-0 shadow-lg">
      <Brain className="w-4 h-4 text-white" />
    </div>
    <div className="flex-1 min-w-0 max-w-[85%]">
      <div className="relative overflow-hidden rounded-2xl rounded-tl-sm p-4 bg-gradient-to-br from-violet-500/10 via-purple-500/5 to-transparent border border-violet-500/20 backdrop-blur-xl bg-white/[0.02] shadow-lg shadow-black/5">
        <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />
        <div className="relative flex items-center gap-2 mb-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-violet-400">
            {agentName}
          </span>
        </div>
        <div className="relative flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
            />
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0.2 }}
            />
            <motion.span
              className="w-2 h-2 rounded-full bg-violet-400"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
            />
          </div>
          <span className="text-xs text-violet-300/70 ml-1">thinking...</span>
        </div>
      </div>
    </div>
  </motion.div>
);

// ============================================================================
// HOVER TIMESTAMP COMPONENT
// ============================================================================

const HoverTimestamp = ({ timestamp, children, position = 'left' }) => {
  const [showFull, setShowFull] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  
  return (
    <div 
      className="relative group"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => { setIsHovered(false); setShowFull(false); }}
    >
      {children}
      
      <AnimatePresence>
        {isHovered && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className={`absolute ${position === 'right' ? 'right-0' : 'left-0'} -top-6 z-50`}
          >
            <button
              onClick={() => setShowFull(!showFull)}
              className="px-2 py-0.5 rounded bg-zinc-800/95 border border-white/10 text-[10px] text-zinc-400 hover:text-zinc-300 whitespace-nowrap shadow-lg backdrop-blur-sm transition-colors"
            >
              {showFull ? formatFullTime(timestamp) : formatRelativeTime(timestamp)}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// ============================================================================
// MEMOIZED STREAM MESSAGE COMPONENT (prevents flickering)
// ============================================================================

const StreamMessage = React.memo(({ msg, index }) => {
  const isUser = msg.metadata?.role === 'user';
  
  // Determine message type for styling
  const getMessageType = () => {
    if (isUser) return 'user';
    if (msg.action_type === 'chat_response') return 'sentcom';
    if (msg.action_type === 'scanning' || msg.type === 'thought') return 'scanner';
    if (msg.type === 'alert' || msg.action_type === 'stop_warning') return 'alert';
    if (msg.type === 'filter') return 'filter';
    if (msg.action_type === 'monitoring') return 'monitor';
    return 'system';
  };
  
  const messageType = getMessageType();
  
  // Color schemes for different message types - more transparent/glass-like
  const colorSchemes = {
    user: {
      gradient: 'from-cyan-500/10 via-blue-500/5 to-transparent',
      border: 'border-cyan-500/20',
      icon: 'from-cyan-500 to-blue-500',
      iconColor: 'text-white',
      label: 'text-cyan-400',
      text: 'text-cyan-100',
      badge: 'bg-cyan-500/15 text-cyan-300'
    },
    sentcom: {
      gradient: 'from-violet-500/10 via-purple-500/5 to-transparent',
      border: 'border-violet-500/20',
      icon: 'from-violet-500 to-purple-600',
      iconColor: 'text-white',
      label: 'text-violet-400',
      text: 'text-zinc-200',
      badge: 'bg-violet-500/15 text-violet-300'
    },
    scanner: {
      gradient: 'from-emerald-500/10 via-teal-500/5 to-transparent',
      border: 'border-emerald-500/20',
      icon: 'from-emerald-500 to-teal-500',
      iconColor: 'text-white',
      label: 'text-emerald-400',
      text: 'text-zinc-200',
      badge: 'bg-emerald-500/15 text-emerald-300'
    },
    alert: {
      gradient: 'from-amber-500/10 via-orange-500/5 to-transparent',
      border: 'border-amber-500/20',
      icon: 'from-amber-500 to-orange-500',
      iconColor: 'text-white',
      label: 'text-amber-400',
      text: 'text-zinc-200',
      badge: 'bg-amber-500/15 text-amber-300'
    },
    filter: {
      gradient: 'from-pink-500/10 via-rose-500/5 to-transparent',
      border: 'border-pink-500/20',
      icon: 'from-pink-500 to-rose-500',
      iconColor: 'text-white',
      label: 'text-pink-400',
      text: 'text-zinc-200',
      badge: 'bg-pink-500/15 text-pink-300'
    },
    monitor: {
      gradient: 'from-blue-500/10 via-indigo-500/5 to-transparent',
      border: 'border-blue-500/20',
      icon: 'from-blue-500 to-indigo-500',
      iconColor: 'text-white',
      label: 'text-blue-400',
      text: 'text-zinc-200',
      badge: 'bg-blue-500/15 text-blue-300'
    },
    system: {
      gradient: 'from-zinc-500/10 via-zinc-600/5 to-transparent',
      border: 'border-zinc-500/20',
      icon: 'from-zinc-500 to-zinc-600',
      iconColor: 'text-white',
      label: 'text-zinc-400',
      text: 'text-zinc-300',
      badge: 'bg-zinc-500/15 text-zinc-300'
    }
  };
  
  const colors = colorSchemes[messageType];
  
  // Get icon based on message type
  const getIcon = () => {
    switch (messageType) {
      case 'user': return <MessageSquare className="w-4 h-4" />;
      case 'sentcom': return <Brain className="w-4 h-4" />;
      case 'scanner': return <Search className="w-4 h-4" />;
      case 'alert': return <AlertCircle className="w-4 h-4" />;
      case 'filter': return <Target className="w-4 h-4" />;
      case 'monitor': return <Activity className="w-4 h-4" />;
      default: return <Radio className="w-4 h-4" />;
    }
  };
  
  // Get label based on message type
  const getLabel = () => {
    switch (messageType) {
      case 'user': return 'YOU';
      case 'sentcom': return 'SENTCOM';
      case 'scanner': return 'SCANNER';
      case 'alert': return 'ALERT';
      case 'filter': return 'SMART FILTER';
      case 'monitor': return 'MONITOR';
      default: return 'SYSTEM';
    }
  };
  
  return (
    <HoverTimestamp 
      timestamp={msg.timestamp}
      position={isUser ? 'right' : 'left'}
    >
      <motion.div
        initial={{ opacity: 0, y: 10, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ delay: Math.min(index * 0.05, 0.3), type: 'spring', stiffness: 200 }}
        className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
      >
        {/* Icon with gradient background */}
        <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${colors.icon} flex items-center justify-center flex-shrink-0 shadow-lg ${colors.iconColor}`}>
          {getIcon()}
        </div>
        
        {/* Message bubble with glassmorphism */}
        <div className={`flex-1 min-w-0 max-w-[85%] ${isUser ? 'text-right' : ''}`}>
          <div 
            className={`
              relative overflow-hidden rounded-2xl p-4
              bg-gradient-to-br ${colors.gradient}
              border ${colors.border}
              backdrop-blur-xl bg-white/[0.02]
              shadow-lg shadow-black/5
              ${isUser ? 'rounded-tr-sm' : 'rounded-tl-sm'}
            `}
          >
            {/* Subtle glass reflection */}
            <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />
            
            {/* Header with label and symbol */}
            <div className={`relative flex items-center gap-2 mb-2 ${isUser ? 'justify-end' : ''}`}>
              <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.label}`}>
                {getLabel()}
              </span>
              {msg.symbol && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${colors.badge} font-medium`}>
                  {msg.symbol}
                </span>
              )}
            </div>
            
            {/* Message content */}
            <p className={`relative text-sm leading-relaxed ${colors.text}`}>
              {msg.content}
            </p>
            
            {/* Confidence indicator */}
            {msg.confidence && (
              <div className={`relative flex items-center gap-1.5 mt-3 pt-2 border-t border-white/10 ${isUser ? 'justify-end' : ''}`}>
                <Gauge className={`w-3 h-3 ${colors.label}`} />
                <span className={`text-[10px] ${colors.label}`}>
                  Confidence: {msg.confidence}%
                </span>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </HoverTimestamp>
  );
}, (prevProps, nextProps) => {
  // Custom comparison - only re-render if ID or content changed
  return prevProps.msg.id === nextProps.msg.id && 
         prevProps.msg.content === nextProps.msg.content;
});

StreamMessage.displayName = 'StreamMessage';

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

const Sparkline = ({ data = [], color = 'cyan', height = 24 }) => {
  if (!data || data.length < 2) return null;
  
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  
  // Add padding to prevent clipping at edges
  const padding = 5;
  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * (100 - padding * 2);
    const y = padding + (100 - padding * 2) - ((val - min) / range) * (100 - padding * 2);
    return `${x},${y}`;
  }).join(' ');
  
  const strokeColor = color === 'emerald' ? '#10b981' : color === 'rose' ? '#f43f5e' : '#06b6d4';
  
  return (
    <svg 
      viewBox="0 0 100 100" 
      className="w-full h-full" 
      preserveAspectRatio="none"
      style={{ display: 'block' }}
    >
      <polyline
        points={points}
        fill="none"
        stroke={strokeColor}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

// Generate sparkline data based on P&L direction and percentage
const generateSparklineData = (pnl, pnlPercent = 0) => {
  const isPositive = pnl >= 0;
  const magnitude = Math.min(Math.abs(pnlPercent || 0), 10); // Cap at 10% for visual scaling
  const baseValue = 50;
  const points = 8;
  const data = [];
  
  for (let i = 0; i < points; i++) {
    // Create a trend line with some variation
    const progress = i / (points - 1);
    const trend = isPositive 
      ? baseValue + (magnitude * progress * 3) // Upward trend
      : baseValue - (magnitude * progress * 3); // Downward trend
    
    // Add some natural variation (smaller as we approach current price)
    const variation = (Math.random() - 0.5) * (2 - progress) * 2;
    data.push(Math.max(0, trend + variation));
  }
  
  return data;
};

const GlassCard = ({ children, className = '', gradient = false, glow = false }) => (
  <div className={`
    relative overflow-hidden rounded-2xl
    bg-gradient-to-br from-white/[0.08] to-white/[0.02]
    border border-white/10
    backdrop-blur-xl
    ${glow ? 'shadow-lg shadow-cyan-500/10' : ''}
    ${className}
  `}>
    {gradient && (
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-violet-500/5 pointer-events-none" />
    )}
    <div className="relative">{children}</div>
  </div>
);

const PulsingDot = ({ color = 'emerald' }) => (
  <span className="relative flex h-2 w-2">
    <span className={`animate-ping absolute inline-flex h-full w-full rounded-full bg-${color}-400 opacity-75`}></span>
    <span className={`relative inline-flex rounded-full h-2 w-2 bg-${color}-500`}></span>
  </span>
);

// Check My Trade Form
const CheckMyTradeForm = ({ onSubmit, loading, onClose }) => {
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState('BUY');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!symbol.trim()) {
      toast.error('Enter a symbol');
      return;
    }
    if (!entryPrice || !stopLoss) {
      toast.error('Enter entry and stop prices for full analysis');
      return;
    }
    onSubmit({
      symbol: symbol.toUpperCase(),
      action,
      entry_price: parseFloat(entryPrice),
      stop_loss: parseFloat(stopLoss)
    });
    // Clear form after submit
    setSymbol('');
    setEntryPrice('');
    setStopLoss('');
    onClose?.();
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="bg-black/40 rounded-xl p-4 border border-white/10 mb-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium text-white flex items-center gap-2">
          <Target className="w-4 h-4 text-cyan-400" />
          Check Our Trade
        </h4>
        <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="Symbol"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
            data-testid="check-trade-symbol"
          />
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <div className="flex gap-2">
          <input
            type="number"
            step="0.01"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder="Entry $"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
          <input
            type="number"
            step="0.01"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
            placeholder="Stop $"
            className="flex-1 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full px-4 py-2 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-lg text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {loading ? 'Checking...' : 'Check This Trade'}
        </button>
      </form>
    </motion.div>
  );
};

// Inline Quick Actions - Always visible above chat input
const QuickActionsInline = ({ onAction, onCheckTrade, loading, showTradeForm, setShowTradeForm }) => {
  const quickActions = [
    { id: 'performance', icon: BarChart3, label: 'Performance', color: 'emerald', 
      prompt: "Analyze our trading performance. What's our win rate, profit factor, and what are our strengths and weaknesses? Give us actionable recommendations." },
    { id: 'news', icon: Newspaper, label: 'News', color: 'cyan',
      prompt: "What's happening in the market today? Give us the key headlines and themes affecting our watchlist." },
    { id: 'morning', icon: Sunrise, label: 'Brief', color: 'amber',
      endpoint: '/api/assistant/coach/morning-briefing' },
    { id: 'rules', icon: BookOpen, label: 'Rules', color: 'violet',
      endpoint: '/api/assistant/coach/rule-reminder' },
    { id: 'summary', icon: TrendingUp, label: 'Summary', color: 'purple',
      endpoint: '/api/assistant/coach/daily-summary' },
  ];

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {quickActions.map((action) => {
        const Icon = action.icon;
        const isLoading = loading === action.id;
        return (
          <button
            key={action.id}
            onClick={() => onAction(action)}
            disabled={isLoading}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all border
              ${isLoading ? 'opacity-50' : 'hover:scale-105'}
              ${action.color === 'emerald' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20' :
                action.color === 'cyan' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20' :
                action.color === 'amber' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20' :
                action.color === 'violet' ? 'bg-violet-500/10 border-violet-500/30 text-violet-400 hover:bg-violet-500/20' :
                'bg-purple-500/10 border-purple-500/30 text-purple-400 hover:bg-purple-500/20'
              }`}
            data-testid={`quick-action-${action.id}`}
          >
            {isLoading ? <Loader className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
            {action.label}
          </button>
        );
      })}
      <button
        onClick={() => setShowTradeForm(!showTradeForm)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all border
          ${showTradeForm 
            ? 'bg-gradient-to-r from-cyan-500/20 to-emerald-500/20 border-cyan-500/50 text-cyan-400' 
            : 'bg-zinc-800/50 border-white/10 text-zinc-300 hover:border-cyan-500/30 hover:bg-zinc-800'
          }`}
        data-testid="check-trade-btn"
      >
        <Target className="w-3 h-3" />
        Check Trade
      </button>
    </div>
  );
};

// Stop Fix Actions Component - Shows button when there are risky stops
const StopFixPanel = ({ thoughts = [], onRefresh }) => {
  const [isFixing, setIsFixing] = useState(false);
  const [fixResult, setFixResult] = useState(null);
  
  // Check if there are any stop warnings in thoughts
  const stopWarnings = thoughts.filter(t => 
    t.action_type === 'stop_warning' && 
    (t.metadata?.severity === 'critical' || t.metadata?.severity === 'warning')
  );
  
  if (stopWarnings.length === 0) return null;
  
  const handleFixAllStops = async () => {
    setIsFixing(true);
    setFixResult(null);
    
    try {
      const response = await fetch(`${API_BASE}/api/trading-bot/fix-all-risky-stops`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      const data = await response.json();
      
      if (data.success) {
        setFixResult({
          success: true,
          message: data.message || `Fixed ${data.fixes_applied} stops`,
          fixes: data.fixes || []
        });
        
        if (onRefresh) {
          setTimeout(onRefresh, 1000);
        }
        toast.success(`Fixed ${data.fixes_applied || 0} risky stops`);
      } else {
        setFixResult({ success: false, message: data.error || "Couldn't fix stops" });
        toast.error("Couldn't fix stops: " + (data.error || "Unknown error"));
      }
    } catch (err) {
      console.error('Stop fix error:', err);
      setFixResult({ success: false, message: "Connection error" });
      toast.error("Connection error while fixing stops");
    } finally {
      setIsFixing(false);
    }
  };
  
  return (
    <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 mb-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-400" />
          <span className="text-sm font-medium text-rose-400">
            {stopWarnings.length} Risky Stop{stopWarnings.length > 1 ? 's' : ''} Detected
          </span>
        </div>
        <button
          onClick={handleFixAllStops}
          disabled={isFixing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 border border-rose-500/40 text-rose-400 text-xs font-medium hover:bg-rose-500/30 transition-all disabled:opacity-50"
        >
          {isFixing ? <Loader className="w-3 h-3 animate-spin" /> : <Crosshair className="w-3 h-3" />}
          Fix All Stops
        </button>
      </div>
      {fixResult && (
        <div className={`mt-2 text-xs ${fixResult.success ? 'text-emerald-400' : 'text-rose-400'}`}>
          {fixResult.message}
        </div>
      )}
    </div>
  );
};

// Risk Parameters Control Panel with Profile Presets
const RiskControlsPanel = ({ botStatus, onUpdateRisk, loading }) => {
  const riskParams = botStatus?.risk_params || {};
  const [localParams, setLocalParams] = useState({
    max_risk_per_trade: riskParams.max_risk_per_trade || 1.0,
    max_daily_loss: riskParams.max_daily_loss || 500,
    max_open_positions: riskParams.max_open_positions || 5,
    max_position_pct: riskParams.max_position_pct || 5.0,
    min_risk_reward: riskParams.min_risk_reward || 2.0
  });
  const [hasChanges, setHasChanges] = useState(false);
  const [activePreset, setActivePreset] = useState(null);

  // Risk Profile Presets
  const riskPresets = {
    conservative: {
      label: 'Conservative',
      description: 'Lower risk, fewer positions',
      icon: '🛡️',
      color: 'emerald',
      params: {
        max_risk_per_trade: 0.5,
        max_daily_loss: 250,
        max_open_positions: 3,
        min_risk_reward: 3.0
      }
    },
    moderate: {
      label: 'Moderate',
      description: 'Balanced risk/reward',
      icon: '⚖️',
      color: 'cyan',
      params: {
        max_risk_per_trade: 1.0,
        max_daily_loss: 500,
        max_open_positions: 5,
        min_risk_reward: 2.0
      }
    },
    aggressive: {
      label: 'Aggressive',
      description: 'Higher risk, more positions',
      icon: '🔥',
      color: 'amber',
      params: {
        max_risk_per_trade: 2.0,
        max_daily_loss: 1000,
        max_open_positions: 8,
        min_risk_reward: 1.5
      }
    }
  };

  // Detect which preset matches current params (if any)
  const detectActivePreset = (params) => {
    for (const [key, preset] of Object.entries(riskPresets)) {
      const p = preset.params;
      if (
        params.max_risk_per_trade === p.max_risk_per_trade &&
        params.max_daily_loss === p.max_daily_loss &&
        params.max_open_positions === p.max_open_positions &&
        params.min_risk_reward === p.min_risk_reward
      ) {
        return key;
      }
    }
    return null;
  };

  // Update local params when bot status changes
  useEffect(() => {
    if (riskParams) {
      const newParams = {
        max_risk_per_trade: riskParams.max_risk_per_trade || 1.0,
        max_daily_loss: riskParams.max_daily_loss || 500,
        max_open_positions: riskParams.max_open_positions || 5,
        max_position_pct: riskParams.max_position_pct || 5.0,
        min_risk_reward: riskParams.min_risk_reward || 2.0
      };
      setLocalParams(newParams);
      setActivePreset(detectActivePreset(newParams));
      setHasChanges(false);
    }
  }, [riskParams]);

  const handleChange = (field, value) => {
    const newParams = { ...localParams, [field]: parseFloat(value) || 0 };
    setLocalParams(newParams);
    setActivePreset(detectActivePreset(newParams));
    setHasChanges(true);
  };

  const applyPreset = (presetKey) => {
    const preset = riskPresets[presetKey];
    if (preset) {
      setLocalParams(prev => ({ ...prev, ...preset.params }));
      setActivePreset(presetKey);
      setHasChanges(true);
      toast.success(`Applied ${preset.label} risk profile`);
    }
  };

  const handleSave = async () => {
    const success = await onUpdateRisk(localParams);
    if (success) setHasChanges(false);
  };

  return (
    <div className="space-y-4">
      {/* Risk Profile Presets */}
      <div>
        <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Quick Profiles</h4>
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(riskPresets).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => applyPreset(key)}
              className={`p-3 rounded-xl border text-center transition-all ${
                activePreset === key
                  ? preset.color === 'emerald' 
                    ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                    : preset.color === 'cyan'
                    ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-400'
                    : 'bg-amber-500/20 border-amber-500/40 text-amber-400'
                  : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
              }`}
              data-testid={`risk-preset-${key}`}
            >
              <span className="text-lg">{preset.icon}</span>
              <div className="text-xs font-medium mt-1">{preset.label}</div>
              <div className="text-[9px] text-zinc-500 mt-0.5">{preset.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-white/5" />

      {/* Custom Parameters */}
      <div>
        <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">
          Custom Parameters {activePreset && <span className="text-cyan-400 font-normal">({riskPresets[activePreset].label})</span>}
        </h4>
        
        <div className="grid grid-cols-2 gap-3">
          {/* Max Risk Per Trade */}
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase">Risk/Trade (%)</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5"
              value={localParams.max_risk_per_trade}
              onChange={(e) => handleChange('max_risk_per_trade', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="risk-per-trade-input"
            />
          </div>

          {/* Max Daily Loss */}
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase">Max Daily Loss ($)</label>
            <input
              type="number"
              step="50"
              min="100"
              value={localParams.max_daily_loss}
              onChange={(e) => handleChange('max_daily_loss', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="max-daily-loss-input"
            />
          </div>

          {/* Max Open Positions */}
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase">Max Positions</label>
            <input
              type="number"
              step="1"
              min="1"
              max="20"
              value={localParams.max_open_positions}
              onChange={(e) => handleChange('max_open_positions', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="max-positions-input"
            />
          </div>

          {/* Min Risk:Reward */}
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase">Min R:R Ratio</label>
            <input
              type="number"
              step="0.5"
              min="1"
              max="10"
              value={localParams.min_risk_reward}
              onChange={(e) => handleChange('min_risk_reward', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="min-rr-input"
            />
          </div>
        </div>
      </div>

      {/* Save Button */}
      {hasChanges && (
        <motion.button
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleSave}
          disabled={loading}
          className="w-full px-4 py-2 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-lg text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
          data-testid="save-risk-params-btn"
        >
          {loading ? 'Saving...' : 'Save Risk Parameters'}
        </motion.button>
      )}
    </div>
  );
};

// AI Modules Control Panel
const AIModulesPanel = ({ aiStatus, onToggleModule, onSetShadowMode, actionLoading }) => {
  const modules = [
    {
      key: 'debate_agents',
      name: 'Bull/Bear Debate',
      description: 'AI agents debate trades from opposing viewpoints',
      icon: '⚖️',
      color: 'violet',
      enabled: aiStatus?.debate_enabled
    },
    {
      key: 'ai_risk_manager',
      name: 'AI Risk Manager',
      description: 'Multi-factor pre-trade risk assessment',
      icon: '🛡️',
      color: 'cyan',
      enabled: aiStatus?.risk_manager_enabled
    },
    {
      key: 'institutional_flow',
      name: 'Institutional Flow',
      description: '13F tracking, volume anomalies, rebalances',
      icon: '🏦',
      color: 'emerald',
      enabled: aiStatus?.institutional_enabled
    },
    {
      key: 'timeseries_ai',
      name: 'Time Series AI',
      description: 'ML-based price direction forecasting',
      icon: '📈',
      color: 'amber',
      enabled: aiStatus?.timeseries_enabled
    }
  ];

  const shadowMode = aiStatus?.shadow_mode ?? true;
  const activeModules = aiStatus?.active_modules || 0;

  return (
    <div className="space-y-4">
      {/* Shadow Mode Toggle */}
      <div className="p-3 rounded-xl bg-gradient-to-br from-violet-500/10 to-purple-500/5 border border-violet-500/20">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-xl">👻</div>
            <div>
              <h4 className="text-sm font-bold text-white">Shadow Mode</h4>
              <p className="text-[10px] text-zinc-400">AI makes decisions but doesn't execute trades</p>
            </div>
          </div>
          <button
            onClick={() => onSetShadowMode(!shadowMode)}
            disabled={actionLoading === 'shadow'}
            className={`relative w-12 h-6 rounded-full transition-all ${
              shadowMode 
                ? 'bg-violet-500' 
                : 'bg-zinc-700'
            }`}
            data-testid="shadow-mode-toggle"
          >
            <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${
              shadowMode ? 'left-7' : 'left-1'
            }`} />
          </button>
        </div>
        {shadowMode && (
          <div className="mt-2 text-[10px] text-violet-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
            All AI decisions are logged without execution for learning
          </div>
        )}
      </div>

      {/* Active Modules Count */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-zinc-400">Active Modules</span>
        <span className="text-xs font-bold text-cyan-400">{activeModules} / {modules.length}</span>
      </div>

      {/* Module Toggles */}
      <div className="space-y-2">
        {modules.map((module) => {
          const isLoading = actionLoading === module.key;
          const colorClasses = {
            violet: 'border-violet-500/30 bg-violet-500/10',
            cyan: 'border-cyan-500/30 bg-cyan-500/10',
            emerald: 'border-emerald-500/30 bg-emerald-500/10',
            amber: 'border-amber-500/30 bg-amber-500/10'
          };
          const activeClass = module.enabled ? colorClasses[module.color] : 'border-white/5 bg-black/30';
          
          return (
            <div
              key={module.key}
              className={`p-3 rounded-xl border transition-all ${activeClass}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xl">{module.icon}</span>
                  <div>
                    <h5 className="text-sm font-medium text-white">{module.name}</h5>
                    <p className="text-[10px] text-zinc-400">{module.description}</p>
                  </div>
                </div>
                <button
                  onClick={() => onToggleModule(module.key, !module.enabled)}
                  disabled={isLoading}
                  className={`relative w-10 h-5 rounded-full transition-all ${
                    module.enabled 
                      ? module.color === 'violet' ? 'bg-violet-500' 
                        : module.color === 'cyan' ? 'bg-cyan-500'
                        : module.color === 'emerald' ? 'bg-emerald-500'
                        : 'bg-amber-500'
                      : 'bg-zinc-700'
                  } ${isLoading ? 'opacity-50' : ''}`}
                  data-testid={`toggle-${module.key}`}
                >
                  {isLoading ? (
                    <Loader className="w-3 h-3 absolute top-1 left-1 text-white animate-spin" />
                  ) : (
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${
                      module.enabled ? 'left-5' : 'left-0.5'
                    }`} />
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Shadow Stats */}
      {aiStatus?.shadow_stats && (
        <div className="p-3 rounded-xl bg-black/30 border border-white/5">
          <h5 className="text-[10px] font-bold text-zinc-400 uppercase mb-2">Shadow Tracking Stats</h5>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-bold text-white">{aiStatus.shadow_stats.total_decisions}</p>
              <p className="text-[9px] text-zinc-500">Decisions</p>
            </div>
            <div>
              <p className="text-lg font-bold text-cyan-400">{aiStatus.shadow_stats.executed_decisions}</p>
              <p className="text-[9px] text-zinc-500">Executed</p>
            </div>
            <div>
              <p className="text-lg font-bold text-amber-400">{aiStatus.shadow_stats.pending_outcomes}</p>
              <p className="text-[9px] text-zinc-500">Pending</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// AI INSIGHTS DASHBOARD - Phase 4 Implementation
// ============================================================================

// Hook for AI Insights data
const useAIInsights = (pollInterval = 15000) => {
  const [shadowDecisions, setShadowDecisions] = useState([]);
  const [shadowPerformance, setShadowPerformance] = useState(null);
  const [timeseriesStatus, setTimeseriesStatus] = useState(null);
  const [predictionAccuracy, setPredictionAccuracy] = useState(null);
  const [recentPredictions, setRecentPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchInsights = useCallback(async () => {
    try {
      const [decisionsRes, performanceRes, timeseriesRes, accuracyRes, predictionsRes] = await Promise.all([
        fetch(`${API_BASE}/api/ai-modules/shadow/decisions?limit=10`),
        fetch(`${API_BASE}/api/ai-modules/shadow/performance?days=7`),
        fetch(`${API_BASE}/api/ai-modules/timeseries/status`),
        fetch(`${API_BASE}/api/ai-modules/timeseries/prediction-accuracy?days=30`),
        fetch(`${API_BASE}/api/ai-modules/timeseries/predictions?limit=10`)
      ]);

      const [decisionsData, performanceData, timeseriesData, accuracyData, predictionsData] = await Promise.all([
        decisionsRes.json(),
        performanceRes.json(),
        timeseriesRes.json(),
        accuracyRes.json(),
        predictionsRes.json()
      ]);

      if (decisionsData.success) setShadowDecisions(decisionsData.decisions || []);
      if (performanceData.success) setShadowPerformance(performanceData.performance || null);
      if (timeseriesData.success) setTimeseriesStatus(timeseriesData.status || null);
      if (accuracyData.success) setPredictionAccuracy(accuracyData.accuracy || null);
      if (predictionsData.success) setRecentPredictions(predictionsData.predictions || []);
    } catch (err) {
      console.error('Error fetching AI insights:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInsights();
    const interval = setInterval(fetchInsights, pollInterval);
    return () => clearInterval(interval);
  }, [fetchInsights, pollInterval]);

  return { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh: fetchInsights };
};

// AI Insights Dashboard Panel
const AIInsightsDashboard = ({ onClose }) => {
  console.log('AIInsightsDashboard component mounted');
  const { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh } = useAIInsights();
  const [activeTab, setActiveTab] = useState('decisions');
  const [forecastSymbol, setForecastSymbol] = useState('');
  const [forecastResult, setForecastResult] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const runForecast = async () => {
    if (!forecastSymbol.trim()) return;
    setForecastLoading(true);
    try {
      // Call forecast API - it will fetch bars from MongoDB if not provided
      const forecastRes = await fetch(`${API_BASE}/api/ai-modules/timeseries/forecast`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: forecastSymbol.toUpperCase() })
      });
      const forecastData = await forecastRes.json();
      
      if (forecastData.success) {
        setForecastResult(forecastData.forecast);
      } else {
        toast.error('Forecast failed: ' + (forecastData.error || forecastData.forecast?.signal || 'Unknown error'));
      }
    } catch (err) {
      console.error('Forecast error:', err);
      toast.error('Failed to run forecast');
    } finally {
      setForecastLoading(false);
    }
  };

  // Use portal to render modal at document root
  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      data-testid="ai-insights-modal-backdrop"
    >
      <div
        className="relative w-full max-w-4xl max-h-[85vh] overflow-hidden rounded-2xl bg-gradient-to-br from-zinc-900 to-black border border-white/10"
        onClick={e => e.stopPropagation()}
        data-testid="ai-insights-modal"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 flex items-center justify-center">
              <Brain className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">AI Insights Dashboard</h2>
              <p className="text-xs text-zinc-400">View AI decisions, forecasts, and performance</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex gap-2 p-4 border-b border-white/5">
          {[
            { id: 'decisions', label: 'Shadow Decisions', icon: '👻' },
            { id: 'forecast', label: 'Time-Series Forecast', icon: '📈' },
            { id: 'predictions', label: 'Prediction Tracking', icon: '🎯' },
            { id: 'performance', label: 'Module Performance', icon: '📊' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                activeTab === tab.id
                  ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
                  : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
              }`}
              data-testid={`ai-insights-tab-${tab.id}`}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="p-4 overflow-y-auto max-h-[calc(85vh-160px)]">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader className="w-8 h-8 text-violet-400 animate-spin" />
            </div>
          ) : activeTab === 'decisions' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-white">Recent AI Decisions</h3>
                <button
                  onClick={refresh}
                  className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                  data-testid="refresh-decisions"
                >
                  <RefreshCw className="w-4 h-4 text-zinc-400" />
                </button>
              </div>
              
              {shadowDecisions.length === 0 ? (
                <div className="text-center py-8" data-testid="no-decisions">
                  <div className="text-4xl mb-2">👻</div>
                  <p className="text-zinc-400">No shadow decisions yet</p>
                  <p className="text-xs text-zinc-500 mt-1">AI decisions will appear here when Shadow Mode is active</p>
                </div>
              ) : (
                shadowDecisions.map((decision, i) => (
                  <div
                    key={decision.id || i}
                    className="p-4 rounded-xl bg-black/40 border border-white/5 hover:border-white/10 transition-all"
                    data-testid={`decision-${i}`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold text-white">{decision.symbol}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          decision.combined_recommendation === 'proceed' 
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : decision.combined_recommendation === 'reduce_size'
                            ? 'bg-amber-500/20 text-amber-400'
                            : 'bg-rose-500/20 text-rose-400'
                        }`}>
                          {decision.combined_recommendation?.toUpperCase() || 'UNKNOWN'}
                        </span>
                        {decision.was_executed && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400">
                            EXECUTED
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-zinc-500">
                        {new Date(decision.timestamp).toLocaleString()}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4 mb-3">
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Price</p>
                        <p className="text-sm font-medium text-white">
                          ${decision.price_at_decision?.toFixed(2) || 'N/A'}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Confidence</p>
                        <p className="text-sm font-medium text-cyan-400">
                          {((decision.confidence_score || 0) * 100).toFixed(0)}%
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase">Regime</p>
                        <p className="text-sm font-medium text-violet-400">
                          {decision.market_regime || 'N/A'}
                        </p>
                      </div>
                    </div>
                    
                    {decision.reasoning && (
                      <p className="text-xs text-zinc-400 border-t border-white/5 pt-2 mt-2">
                        {decision.reasoning}
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : activeTab === 'forecast' ? (
            <div className="space-y-4">
              {/* Time-Series Model Status */}
              <div className="p-4 rounded-xl bg-gradient-to-br from-amber-500/10 to-orange-500/5 border border-amber-500/20">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span>📈</span> Time-Series AI Model
                  </h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    timeseriesStatus?.model?.trained
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-amber-500/20 text-amber-400'
                  }`} data-testid="model-status">
                    {timeseriesStatus?.model?.trained ? 'TRAINED' : 'UNTRAINED'}
                  </span>
                </div>
                
                {timeseriesStatus?.model && (
                  <div className="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-lg font-bold text-white">{timeseriesStatus.model.version}</p>
                      <p className="text-[9px] text-zinc-500">Version</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-cyan-400" data-testid="model-accuracy">
                        {((timeseriesStatus.model.metrics?.accuracy || 0) * 100).toFixed(1)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Accuracy</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-amber-400">{timeseriesStatus.model.feature_count}</p>
                      <p className="text-[9px] text-zinc-500">Features</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-violet-400">
                        {(timeseriesStatus.model.metrics?.training_samples || 0).toLocaleString()}
                      </p>
                      <p className="text-[9px] text-zinc-500">Samples</p>
                    </div>
                  </div>
                )}
                
                {timeseriesStatus?.model?.metrics?.top_features && (
                  <div className="mt-3 pt-3 border-t border-white/5">
                    <p className="text-[10px] text-zinc-500 uppercase mb-2">Top Features</p>
                    <div className="flex flex-wrap gap-1">
                      {timeseriesStatus.model.metrics.top_features.slice(0, 6).map((f, i) => (
                        <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-black/40 text-zinc-400">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Run Forecast */}
              <div className="p-4 rounded-xl bg-black/40 border border-white/5">
                <h3 className="text-sm font-bold text-white mb-3">Run Price Forecast</h3>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={forecastSymbol}
                    onChange={(e) => setForecastSymbol(e.target.value.toUpperCase())}
                    placeholder="Enter symbol (e.g., AAPL)"
                    className="flex-1 px-3 py-2 rounded-lg bg-black/60 border border-white/10 text-white text-sm focus:border-cyan-500/50 focus:outline-none"
                    onKeyPress={(e) => e.key === 'Enter' && runForecast()}
                    data-testid="forecast-symbol-input"
                  />
                  <button
                    onClick={runForecast}
                    disabled={forecastLoading || !forecastSymbol.trim()}
                    className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2"
                    data-testid="run-forecast-btn"
                  >
                    {forecastLoading ? (
                      <Loader className="w-4 h-4 animate-spin" />
                    ) : (
                      <>
                        <Zap className="w-4 h-4" />
                        Forecast
                      </>
                    )}
                  </button>
                </div>
                
                {forecastResult && (
                  <div className="mt-4 p-4 rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10" data-testid="forecast-result">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-lg font-bold text-white">{forecastResult.symbol}</span>
                      <span className={`text-sm font-bold px-3 py-1 rounded-full ${
                        forecastResult.direction === 'up'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : forecastResult.direction === 'down'
                          ? 'bg-rose-500/20 text-rose-400'
                          : 'bg-zinc-500/20 text-zinc-400'
                      }`} data-testid="forecast-direction">
                        {forecastResult.direction?.toUpperCase() || 'FLAT'}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-3 gap-4 text-center mb-3">
                      <div>
                        <p className="text-2xl font-bold text-emerald-400">
                          {(forecastResult.probability_up * 100).toFixed(1)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Prob. UP</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-rose-400">
                          {(forecastResult.probability_down * 100).toFixed(1)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Prob. DOWN</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-cyan-400">
                          {(forecastResult.confidence * 100).toFixed(0)}%
                        </p>
                        <p className="text-[10px] text-zinc-500">Confidence</p>
                      </div>
                    </div>
                    
                    <p className="text-sm text-zinc-300 text-center border-t border-white/5 pt-3">
                      {forecastResult.signal}
                    </p>
                    
                    <p className="text-[10px] text-zinc-500 text-center mt-2">
                      Model: {forecastResult.model_version} | {forecastResult.usable ? '✅ Usable' : '⚠️ Low confidence'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : activeTab === 'predictions' ? (
            /* Predictions Tracking Tab */
            <div className="space-y-4">
              {/* Prediction Accuracy Summary */}
              <div className="p-4 rounded-xl bg-gradient-to-br from-cyan-500/10 to-violet-500/5 border border-cyan-500/20">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span>🎯</span> Prediction Accuracy (30 Days)
                  </h3>
                  <button
                    onClick={async () => {
                      setVerifying(true);
                      try {
                        const res = await fetch(`${API_BASE}/api/ai-modules/timeseries/verify-predictions`, {
                          method: 'POST'
                        });
                        const data = await res.json();
                        if (data.success) {
                          toast.success(`Verified ${data.result.verified} predictions`);
                          refresh();
                        }
                      } catch (e) {
                        toast.error('Verification failed');
                      } finally {
                        setVerifying(false);
                      }
                    }}
                    disabled={verifying}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-400 text-xs font-medium hover:bg-cyan-500/30 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    data-testid="verify-predictions-btn"
                  >
                    {verifying ? <Loader className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    Verify Outcomes
                  </button>
                </div>
                
                {predictionAccuracy ? (
                  <div className="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-2xl font-bold text-white">{predictionAccuracy.total_predictions}</p>
                      <p className="text-[9px] text-zinc-500">Total Predictions</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-emerald-400">{predictionAccuracy.correct_predictions || 0}</p>
                      <p className="text-[9px] text-zinc-500">Correct</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-cyan-400">
                        {(predictionAccuracy.accuracy * 100).toFixed(1)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Accuracy</p>
                    </div>
                    <div>
                      <p className={`text-2xl font-bold ${(predictionAccuracy.avg_return_when_correct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {((predictionAccuracy.avg_return_when_correct || 0) * 100).toFixed(2)}%
                      </p>
                      <p className="text-[9px] text-zinc-500">Avg Return (Correct)</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-zinc-400 text-center py-4">No accuracy data available yet</p>
                )}
                
                {/* Accuracy by Direction */}
                {predictionAccuracy?.by_direction && Object.keys(predictionAccuracy.by_direction).length > 0 && (
                  <div className="mt-4 pt-4 border-t border-white/5">
                    <p className="text-[10px] text-zinc-500 uppercase mb-2">Accuracy by Direction</p>
                    <div className="flex gap-3">
                      {Object.entries(predictionAccuracy.by_direction).map(([dir, stats]) => (
                        <div key={dir} className="flex-1 p-2 rounded-lg bg-black/30 text-center">
                          <span className={`text-xs font-bold ${
                            dir === 'up' ? 'text-emerald-400' : dir === 'down' ? 'text-rose-400' : 'text-zinc-400'
                          }`}>
                            {dir.toUpperCase()}
                          </span>
                          <p className="text-lg font-bold text-white mt-1">{(stats.accuracy * 100).toFixed(0)}%</p>
                          <p className="text-[8px] text-zinc-500">{stats.correct}/{stats.total}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              
              {/* Recent Predictions List */}
              <div>
                <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                  <span>📋</span> Recent Predictions
                </h3>
                
                {recentPredictions.length === 0 ? (
                  <div className="text-center py-8">
                    <div className="text-4xl mb-2">🎯</div>
                    <p className="text-zinc-400">No predictions yet</p>
                    <p className="text-xs text-zinc-500 mt-1">Run forecasts to track prediction accuracy</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {recentPredictions.map((pred, i) => (
                      <div 
                        key={i}
                        className="p-3 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between"
                        data-testid={`prediction-${i}`}
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-bold text-white">{pred.symbol}</span>
                          <span className={`text-xs px-2 py-0.5 rounded-full ${
                            pred.prediction?.direction === 'up' ? 'bg-emerald-500/20 text-emerald-400'
                            : pred.prediction?.direction === 'down' ? 'bg-rose-500/20 text-rose-400'
                            : 'bg-zinc-500/20 text-zinc-400'
                          }`}>
                            {pred.prediction?.direction?.toUpperCase() || 'FLAT'}
                          </span>
                          <span className="text-xs text-zinc-500">
                            {(pred.prediction?.probability_up * 100).toFixed(1)}% UP
                          </span>
                        </div>
                        
                        <div className="flex items-center gap-3">
                          {pred.price_at_prediction && (
                            <span className="text-xs text-zinc-400">${pred.price_at_prediction.toFixed(2)}</span>
                          )}
                          
                          {pred.outcome_verified ? (
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              pred.prediction_correct ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                            }`}>
                              {pred.prediction_correct ? '✓ CORRECT' : '✗ WRONG'}
                            </span>
                          ) : (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
                              PENDING
                            </span>
                          )}
                          
                          <span className="text-[10px] text-zinc-500">
                            {new Date(pred.timestamp).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* Performance Tab */
            <div className="space-y-4">
              <h3 className="text-sm font-bold text-white mb-4">Module Performance (7 Days)</h3>
              
              {!shadowPerformance || Object.keys(shadowPerformance).length === 0 ? (
                <div className="text-center py-8" data-testid="no-performance">
                  <div className="text-4xl mb-2">📊</div>
                  <p className="text-zinc-400">No performance data yet</p>
                  <p className="text-xs text-zinc-500 mt-1">Performance metrics will appear after AI modules make decisions</p>
                </div>
              ) : (
                Object.entries(shadowPerformance).map(([moduleName, perf]) => (
                  <div
                    key={moduleName}
                    className="p-4 rounded-xl bg-black/40 border border-white/5"
                    data-testid={`performance-${moduleName}`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-sm font-bold text-white capitalize">
                        {moduleName.replace(/_/g, ' ')}
                      </h4>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        perf.accuracy > 0.6 ? 'bg-emerald-500/20 text-emerald-400'
                        : perf.accuracy > 0.4 ? 'bg-amber-500/20 text-amber-400'
                        : 'bg-rose-500/20 text-rose-400'
                      }`}>
                        {(perf.accuracy * 100).toFixed(0)}% Accuracy
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-4 gap-4 text-center">
                      <div>
                        <p className="text-lg font-bold text-white">{perf.total_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Total</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-emerald-400">{perf.correct_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Correct</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-rose-400">{perf.incorrect_decisions}</p>
                        <p className="text-[9px] text-zinc-500">Incorrect</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold text-amber-400">{perf.pending_outcomes}</p>
                        <p className="text-[9px] text-zinc-500">Pending</p>
                      </div>
                    </div>
                    
                    {perf.avg_pnl_correct !== undefined && (
                      <div className="grid grid-cols-2 gap-4 text-center mt-3 pt-3 border-t border-white/5">
                        <div>
                          <p className={`text-sm font-bold ${perf.avg_pnl_correct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {perf.avg_pnl_correct >= 0 ? '+' : ''}{perf.avg_pnl_correct?.toFixed(2) || 0}%
                          </p>
                          <p className="text-[9px] text-zinc-500">Avg P&L (Correct)</p>
                        </div>
                        <div>
                          <p className={`text-sm font-bold ${perf.avg_pnl_incorrect >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {perf.avg_pnl_incorrect >= 0 ? '+' : ''}{perf.avg_pnl_incorrect?.toFixed(2) || 0}%
                          </p>
                          <p className="text-[9px] text-zinc-500">Avg P&L (Incorrect)</p>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};

// ============================================================================
// HOOKS
// ============================================================================

// Hook for Market Session status
const useMarketSession = (pollInterval = 30000) => {
  const [session, setSession] = useState({ name: 'LOADING', is_open: false });
  const [loading, setLoading] = useState(true);

  const fetchSession = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/market-context/session/status`);
      const data = await res.json();
      if (data.success && data.session) {
        setSession(data.session);
      }
    } catch (err) {
      console.error('Error fetching market session:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSession();
    const interval = setInterval(fetchSession, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSession, pollInterval]);

  return { session, loading, refresh: fetchSession };
};

const useSentComStatus = (pollInterval = 5000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedStatus = getCached('sentcomStatus');
  const [status, setStatus] = useState(cachedStatus?.data || null);
  const [loading, setLoading] = useState(!cachedStatus?.data);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/status`);
      const data = await res.json();
      if (data.success) {
        setStatus(data.status);
        setCached('sentcomStatus', data.status, 30000); // 30 second TTL
      }
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomStatus');
    if (cached?.data && isFirstMount.current) {
      setStatus(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchStatus();
      }
    } else {
      fetchStatus();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval, getCached]);

  return { status, loading, error, refresh: fetchStatus };
};

const useSentComStream = (pollInterval = 8000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedStream = getCached('sentcomStream');
  const [messages, setMessages] = useState(cachedStream?.data || []);
  const [loading, setLoading] = useState(!cachedStream?.data);
  const lastFetchRef = useRef({ ids: '', chatCount: 0 });

  const fetchStream = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/stream?limit=20`);
      const data = await res.json();
      if (data.success && data.messages) {
        // Separate chat messages from status/system messages
        const chatMessages = data.messages.filter(m => 
          m.type === 'chat' || m.action_type === 'chat_response' || m.action_type === 'user_message'
        );
        const statusMessages = data.messages.filter(m => 
          m.type !== 'chat' && m.action_type !== 'chat_response' && m.action_type !== 'user_message'
        );
        
        // Only update if chat messages changed (ignore status message content changes)
        const chatIds = chatMessages.map(m => m.id || m.timestamp).join(',');
        const hasNewChat = chatIds !== lastFetchRef.current.ids || 
                          chatMessages.length !== lastFetchRef.current.chatCount;
        
        if (hasNewChat || messages.length === 0) {
          lastFetchRef.current = { ids: chatIds, chatCount: chatMessages.length };
          // Keep status messages stable - only take the 2 most recent
          const stableStatus = statusMessages.slice(0, 2);
          const newMessages = [...stableStatus, ...chatMessages];
          setMessages(newMessages);
          setCached('sentcomStream', newMessages, 30000); // 30 second TTL
        }
      }
    } catch (err) {
      console.error('Error fetching stream:', err);
    } finally {
      setLoading(false);
    }
  }, [messages.length, setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomStream');
    if (cached?.data && isFirstMount.current) {
      setMessages(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchStream();
      }
    } else {
      fetchStream();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchStream, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStream, pollInterval, getCached]);

  return { messages, loading, refresh: fetchStream };
};

const useSentComPositions = (pollInterval = 5000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedPositions = getCached('sentcomPositions');
  const [positions, setPositions] = useState(cachedPositions?.data?.positions || []);
  const [totalPnl, setTotalPnl] = useState(cachedPositions?.data?.totalPnl || 0);
  const [loading, setLoading] = useState(!cachedPositions?.data);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/positions`);
      const data = await res.json();
      if (data.success) {
        setPositions(data.positions || []);
        setTotalPnl(data.total_pnl || 0);
        setCached('sentcomPositions', { positions: data.positions || [], totalPnl: data.total_pnl || 0 }, 15000); // 15 second TTL (positions update more frequently)
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomPositions');
    if (cached?.data && isFirstMount.current) {
      setPositions(cached.data.positions || []);
      setTotalPnl(cached.data.totalPnl || 0);
      setLoading(false);
      if (cached.isStale) {
        fetchPositions();
      }
    } else {
      fetchPositions();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval, getCached]);

  return { positions, totalPnl, loading, refresh: fetchPositions };
};

const useSentComSetups = (pollInterval = 10000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedSetups = getCached('sentcomSetups');
  const [setups, setSetups] = useState(cachedSetups?.data || []);
  const [loading, setLoading] = useState(!cachedSetups?.data);

  const fetchSetups = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/setups`);
      const data = await res.json();
      if (data.success) {
        setSetups(data.setups || []);
        setCached('sentcomSetups', data.setups || [], 30000); // 30 second TTL
      }
    } catch (err) {
      console.error('Error fetching setups:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomSetups');
    if (cached?.data && isFirstMount.current) {
      setSetups(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchSetups();
      }
    } else {
      fetchSetups();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchSetups, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSetups, pollInterval, getCached]);

  return { setups, loading, refresh: fetchSetups };
};

const useSentComContext = (pollInterval = 30000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedContext = getCached('sentcomContext');
  const [context, setContext] = useState(cachedContext?.data || null);
  const [loading, setLoading] = useState(!cachedContext?.data);

  const fetchContext = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/context`);
      const data = await res.json();
      if (data.success) {
        setContext(data.context);
        setCached('sentcomContext', data.context, 60000); // 60 second TTL (context changes slowly)
      }
    } catch (err) {
      console.error('Error fetching context:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomContext');
    if (cached?.data && isFirstMount.current) {
      setContext(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchContext();
      }
    } else {
      fetchContext();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchContext, pollInterval);
    return () => clearInterval(interval);
  }, [fetchContext, pollInterval, getCached]);

  return { context, loading, refresh: fetchContext };
};

const useSentComAlerts = (pollInterval = 5000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedAlerts = getCached('sentcomAlerts');
  const [alerts, setAlerts] = useState(cachedAlerts?.data || []);
  const [loading, setLoading] = useState(!cachedAlerts?.data);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/alerts?limit=5`);
      const data = await res.json();
      if (data.success) {
        setAlerts(data.alerts || []);
        setCached('sentcomAlerts', data.alerts || [], 15000); // 15 second TTL (alerts update frequently)
      }
    } catch (err) {
      console.error('Error fetching alerts:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('sentcomAlerts');
    if (cached?.data && isFirstMount.current) {
      setAlerts(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchAlerts();
      }
    } else {
      fetchAlerts();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchAlerts, pollInterval);
    return () => clearInterval(interval);
  }, [fetchAlerts, pollInterval, getCached]);

  return { alerts, loading, refresh: fetchAlerts };
};

// Hook for persisted chat history
const useChatHistory = () => {
  const [chatHistory, setChatHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);

  const fetchChatHistory = useCallback(async () => {
    if (loaded) return; // Only load once
    
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/chat/history?limit=50`);
      const data = await res.json();
      if (data.success && data.messages) {
        // Convert to local message format and reverse for newest-first display
        const formattedMessages = data.messages.map((msg, idx) => ({
          id: `history_${idx}_${Date.now()}`,
          type: 'chat',
          content: msg.content,
          timestamp: msg.timestamp,
          action_type: msg.role === 'user' ? 'user_message' : 'chat_response',
          metadata: { role: msg.role }
        })).reverse();
        
        setChatHistory(formattedMessages);
        setLoaded(true);
      }
    } catch (err) {
      console.error('Error fetching chat history:', err);
    } finally {
      setLoading(false);
    }
  }, [loaded]);

  useEffect(() => {
    fetchChatHistory();
  }, [fetchChatHistory]);

  return { chatHistory, loading, refresh: fetchChatHistory };
};

// Hook for Trading Bot status and controls
const useTradingBotControl = (pollInterval = 5000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedBotStatus = getCached('botStatus');
  const [botStatus, setBotStatus] = useState(cachedBotStatus?.data || null);
  const [loading, setLoading] = useState(!cachedBotStatus?.data);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchBotStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/trading-bot/status`);
      const data = await res.json();
      if (data.success) {
        setBotStatus(data);
        setCached('botStatus', data, 15000); // 15 second TTL
      }
    } catch (err) {
      console.error('Error fetching bot status:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  const toggleBot = useCallback(async () => {
    setActionLoading('toggle');
    try {
      const endpoint = botStatus?.running ? 'stop' : 'start';
      await fetch(`${API_BASE}/api/trading-bot/${endpoint}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(botStatus?.running ? 'Bot stopped' : 'Bot started');
    } catch (err) {
      console.error('Failed to toggle bot:', err);
      toast.error('Failed to toggle bot');
    }
    setActionLoading(null);
  }, [botStatus?.running, fetchBotStatus]);

  const changeMode = useCallback(async (mode) => {
    setActionLoading('mode');
    try {
      await fetch(`${API_BASE}/api/trading-bot/mode/${mode}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(`Mode changed to ${mode}`);
    } catch (err) {
      console.error('Failed to change mode:', err);
      toast.error('Failed to change mode');
    }
    setActionLoading(null);
  }, [fetchBotStatus]);

  const updateRiskParams = useCallback(async (params) => {
    setActionLoading('risk');
    try {
      const res = await fetch(`${API_BASE}/api/trading-bot/risk-params`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      });
      const data = await res.json();
      if (data.success) {
        await fetchBotStatus();
        toast.success('Risk parameters updated');
        return true;
      } else {
        toast.error(data.error || 'Failed to update risk params');
        return false;
      }
    } catch (err) {
      console.error('Failed to update risk params:', err);
      toast.error('Failed to update risk parameters');
      return false;
    } finally {
      setActionLoading(null);
    }
  }, [fetchBotStatus]);

  useEffect(() => {
    // If we have cached data on first mount, use it immediately
    const cached = getCached('botStatus');
    if (cached?.data && isFirstMount.current) {
      setBotStatus(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchBotStatus();
      }
    } else {
      fetchBotStatus();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchBotStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchBotStatus, pollInterval, getCached]);

  return { botStatus, loading, actionLoading, toggleBot, changeMode, updateRiskParams, refresh: fetchBotStatus };
};

// Hook for IB Connection status
const useIBConnectionStatus = (pollInterval = 3000) => {
  const [ibConnected, setIbConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ib/pushed-data`);
      const data = await res.json();
      setIbConnected(data.connected || false);
    } catch (err) {
      setIbConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { ibConnected, loading };
};

// Hook for AI Modules status and control
const useAIModules = (pollInterval = 10000) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/status`);
      const data = await res.json();
      if (data.success) {
        setStatus(data.status);
      }
    } catch (err) {
      console.error('Error fetching AI modules status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleModule = useCallback(async (moduleName, enabled) => {
    setActionLoading(moduleName);
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/toggle/${moduleName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      });
      const data = await res.json();
      if (data.success) {
        await fetchStatus();
        toast.success(`${moduleName.replace('_', ' ')} ${enabled ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error toggling module:', err);
      toast.error('Failed to toggle module');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  const setGlobalShadowMode = useCallback(async (shadowMode) => {
    setActionLoading('shadow');
    try {
      const res = await fetch(`${API_BASE}/api/ai-modules/shadow-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shadow_mode: shadowMode })
      });
      const data = await res.json();
      if (data.success) {
        await fetchStatus();
        toast.success(`Shadow mode ${shadowMode ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error setting shadow mode:', err);
      toast.error('Failed to set shadow mode');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { status, loading, actionLoading, toggleModule, setGlobalShadowMode, refresh: fetchStatus };
};

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

const OrderPipeline = ({ status }) => {
  const pipeline = status?.order_pipeline || { pending: 0, executing: 0, filled: 0 };
  
  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-black/40 border border-white/5">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <Clock className="w-4 h-4 text-amber-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-amber-400">{pipeline.pending}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Pending</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
          <Zap className="w-4 h-4 text-cyan-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-cyan-400">{pipeline.executing}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Executing</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-emerald-400">{pipeline.filled}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Filled</p>
        </div>
      </div>
    </div>
  );
};

const StatusHeader = ({ status, context }) => {
  const connected = status?.connected || false;
  const state = status?.state || 'offline';
  const regime = context?.regime || status?.regime || 'UNKNOWN';
  
  return (
    <div className="flex items-center justify-between p-4 border-b border-white/5">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Brain className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">SENTCOM</h1>
          <div className="flex items-center gap-3 mt-1">
            <div className="flex items-center gap-1.5">
              {connected ? (
                <PulsingDot color="emerald" />
              ) : (
                <Circle className="w-2 h-2 text-zinc-500" />
              )}
              <span className={`text-xs font-medium ${connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {connected ? 'CONNECTED' : 'OFFLINE'}
              </span>
            </div>
            {regime !== 'UNKNOWN' && (
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {regime}
              </span>
            )}
          </div>
        </div>
      </div>
      
      <OrderPipeline status={status} />
    </div>
  );
};

const PositionsPanel = ({ positions, totalPnl, loading, onSelectPosition }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-32">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <DollarSign className="w-3 h-3 text-emerald-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Our Positions</span>
        </div>
        <span className={`text-lg font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
        </span>
      </div>
      
      {positions.length === 0 ? (
        <div className="text-center py-8">
          <Eye className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
          <p className="text-sm text-zinc-500">No open positions</p>
          <p className="text-xs text-zinc-600 mt-1">We're scanning for setups...</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos, i) => (
            <div 
              key={pos.symbol || i}
              onClick={() => onSelectPosition?.(pos)}
              className="flex items-center justify-between p-3 rounded-xl bg-black/30 border border-white/5 hover:border-cyan-500/30 cursor-pointer transition-all"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-white">{pos.symbol}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  pos.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' :
                  pos.status === 'watching' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-cyan-500/20 text-cyan-400'
                }`}>
                  {pos.status || 'open'}
                </span>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="w-16 h-6 overflow-hidden rounded">
                  <Sparkline 
                    data={pos.sparkline_data || generateSparklineData(pos.pnl, pos.pnl_percent)} 
                    color={pos.pnl >= 0 ? 'emerald' : 'rose'} 
                  />
                </div>
                <span className={`text-sm font-bold ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) || '$0'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const StreamPanel = ({ messages, loading }) => {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [messages]);

  if (loading && messages.length === 0) {
    return (
      <GlassCard className="p-4 h-full">
        <div className="flex items-center justify-center h-full">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  const getMessageIcon = (type, actionType) => {
    if (type === 'thought' || actionType === 'scanning') return <Brain className="w-4 h-4 text-violet-400" />;
    if (type === 'alert') return <AlertCircle className="w-4 h-4 text-amber-400" />;
    if (type === 'filter') return <Target className="w-4 h-4 text-cyan-400" />;
    if (actionType === 'monitoring') return <Activity className="w-4 h-4 text-emerald-400" />;
    return <Radio className="w-4 h-4 text-zinc-400" />;
  };

  const getMessageLabel = (type, actionType) => {
    if (actionType === 'scanning') return 'SCANNER';
    if (actionType === 'monitoring') return 'MONITOR';
    if (type === 'filter') return 'FILTER';
    if (type === 'alert') return 'ALERT';
    if (type === 'chat') return 'CHAT';
    return 'SENTCOM';
  };

  return (
    <GlassCard gradient className="p-4 h-full flex flex-col">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Flame className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Live Stream</span>
      </div>
      
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
        {messages.length === 0 ? (
          <div className="text-center py-8">
            <Radio className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
            <p className="text-sm text-zinc-500">Waiting for activity...</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <motion.div
              key={msg.id || i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="relative"
            >
              <div className="flex items-start gap-3 p-3 rounded-xl bg-black/30 border border-white/5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500/30 to-purple-600/30 flex items-center justify-center flex-shrink-0">
                  {getMessageIcon(msg.type, msg.action_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-medium text-violet-400 uppercase">
                      {getMessageLabel(msg.type, msg.action_type)}
                    </span>
                    {msg.symbol && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-400">
                        {msg.symbol}
                      </span>
                    )}
                    <span className="text-[10px] text-zinc-600">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
                  {msg.confidence && (
                    <div className="flex items-center gap-1 mt-2">
                      <Gauge className="w-3 h-3 text-violet-400" />
                      <span className="text-[10px] text-violet-400">Confidence: {msg.confidence}%</span>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          ))
        )}
      </div>
    </GlassCard>
  );
};

const ContextPanel = ({ context, loading }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center">
          <Wifi className="w-3 h-3 text-cyan-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Market Context</span>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Regime</span>
          <span className={`text-xs font-bold ${
            context?.regime === 'RISK_ON' ? 'text-emerald-400' :
            context?.regime === 'RISK_OFF' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.regime || 'UNKNOWN'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">SPY Trend</span>
          <span className={`text-xs font-bold ${
            context?.spy_trend === 'Bullish' ? 'text-emerald-400' :
            context?.spy_trend === 'Bearish' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.spy_trend || '--'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">VIX</span>
          <span className="text-xs font-bold text-zinc-300">{context?.vix || '--'}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Market</span>
          <span className={`text-xs font-bold ${context?.market_open ? 'text-emerald-400' : 'text-zinc-500'}`}>
            {context?.market_open ? 'OPEN' : 'CLOSED'}
          </span>
        </div>
      </div>
    </GlassCard>
  );
};

// Combined Market Intelligence Panel - Market Regime + Setups + Alerts
const MarketIntelPanel = ({ context, setups, alerts, contextLoading, setupsLoading, alertsLoading }) => {
  return (
    <div className="space-y-4">
      {/* Market Regime Section */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center">
            <Activity className="w-3 h-3 text-cyan-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Market Regime</span>
        </div>
        
        {contextLoading ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">Regime</span>
              <span className={`text-sm font-bold ${
                context?.regime === 'RISK_ON' ? 'text-emerald-400' :
                context?.regime === 'RISK_OFF' ? 'text-rose-400' :
                'text-zinc-400'
              }`}>
                {context?.regime || 'UNKNOWN'}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">SPY</span>
              <span className={`text-sm font-bold ${
                context?.spy_trend === 'Bullish' ? 'text-emerald-400' :
                context?.spy_trend === 'Bearish' ? 'text-rose-400' :
                'text-zinc-400'
              }`}>
                {context?.spy_trend || '--'}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">VIX</span>
              <span className="text-sm font-bold text-zinc-300">{context?.vix || '--'}</span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">Market</span>
              <span className={`text-sm font-bold ${context?.market_open ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {context?.market_open ? 'OPEN' : 'CLOSED'}
              </span>
            </div>
          </div>
        )}
      </GlassCard>

      {/* Setups We're Watching */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
            <Eye className="w-3 h-3 text-violet-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Setups We're Watching</span>
          {setups.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-500/20 text-violet-400">
              {setups.length}
            </span>
          )}
        </div>
        
        {setupsLoading && setups.length === 0 ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-violet-400 animate-spin" />
          </div>
        ) : setups.length === 0 ? (
          <div className="text-center py-3">
            <Crosshair className="w-4 h-4 text-zinc-600 mx-auto mb-1" />
            <p className="text-[10px] text-zinc-500">No setups currently</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {setups.slice(0, 5).map((setup, i) => (
              <div 
                key={i}
                className="p-2 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white text-sm">{setup.symbol}</span>
                    <span className="text-[9px] px-1.5 py-0.5 bg-violet-500/20 text-violet-400 rounded-full">
                      {setup.setup_type || setup.type}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Star className="w-3 h-3 text-amber-400" />
                    <span className="text-xs font-bold text-white">{setup.score || setup.confidence || '--'}</span>
                  </div>
                </div>
                {setup.trigger_price && (
                  <div className="text-[10px] text-zinc-500 mt-1">
                    Entry: ${setup.trigger_price?.toFixed(2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {/* Live Scanner Alerts */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Bell className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Live Scanner Alerts</span>
          {alerts.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
              {alerts.length}
            </span>
          )}
        </div>
        
        {alertsLoading && alerts.length === 0 ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-amber-400 animate-spin" />
          </div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-3">
            <Radio className="w-4 h-4 text-zinc-600 mx-auto mb-1" />
            <p className="text-[10px] text-zinc-500">Scanning for opportunities...</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {alerts.slice(0, 5).map((alert, i) => (
              <div 
                key={i}
                className="p-2 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white text-sm">{alert.symbol}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
                      alert.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' :
                      alert.direction === 'SHORT' ? 'bg-rose-500/20 text-rose-400' :
                      'bg-zinc-500/20 text-zinc-400'
                    }`}>
                      {alert.direction || alert.setup_type}
                    </span>
                  </div>
                  <span className="text-xs text-zinc-400">${alert.price?.toFixed(2) || '--'}</span>
                </div>
                <div className="text-[10px] text-zinc-500 mt-1">
                  {alert.setup_type} • {alert.score ? `Score: ${alert.score}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
};

const AlertsPanel = ({ alerts, loading }) => {
  if (loading && alerts.length === 0) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-amber-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Bell className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Recent Alerts</span>
        </div>
        {alerts.length > 0 && (
          <span className="text-xs text-amber-400">{alerts.length} new</span>
        )}
      </div>
      
      {alerts.length === 0 ? (
        <p className="text-xs text-zinc-500 text-center py-4">No alerts</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert, i) => (
            <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-black/20">
              <AlertCircle className={`w-3 h-3 ${
                alert.type === 'warning' ? 'text-amber-400' :
                alert.type === 'info' ? 'text-cyan-400' :
                'text-zinc-400'
              }`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-zinc-300 truncate">{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const SetupsPanel = ({ setups, loading }) => {
  if (loading && setups.length === 0) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Crosshair className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Setups We're Watching</span>
      </div>
      
      {setups.length === 0 ? (
        <div className="text-center py-4">
          <Crosshair className="w-6 h-6 text-zinc-600 mx-auto mb-2" />
          <p className="text-xs text-zinc-500">No setups currently</p>
        </div>
      ) : (
        <div className="space-y-2">
          {setups.map((setup, i) => (
            <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-black/20">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-white">{setup.symbol}</span>
                <span className="text-[10px] text-zinc-500">{setup.setup_type}</span>
              </div>
              {setup.trigger_price && (
                <span className="text-xs text-cyan-400">${setup.trigger_price?.toFixed(2)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const ChatInput = ({ onSend, disabled }) => {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim() || sending) return;
    
    setSending(true);
    await onSend?.(message);
    setMessage('');
    setSending(false);
  };

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-white/5">
      <div className="flex gap-2">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask SentCom anything..."
          disabled={disabled || sending}
          className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
        />
        <button
          type="submit"
          disabled={!message.trim() || sending || disabled}
          className="px-4 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
        >
          {sending ? <Loader className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
        </button>
      </div>
    </form>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const SentCom = ({ compact = false, embedded = false }) => {
  const { status, loading: statusLoading } = useSentComStatus();
  const { messages, loading: streamLoading, refresh: refreshStream } = useSentComStream();
  const { positions, totalPnl, loading: positionsLoading } = useSentComPositions();
  const { setups, loading: setupsLoading } = useSentComSetups();
  const { context, loading: contextLoading } = useSentComContext();
  const { alerts, loading: alertsLoading } = useSentComAlerts();
  const { botStatus, actionLoading, toggleBot, changeMode, updateRiskParams } = useTradingBotControl();
  const { ibConnected } = useIBConnectionStatus();
  const { session: marketSession } = useMarketSession();
  const { chatHistory, loading: historyLoading } = useChatHistory();
  const { 
    status: aiModulesStatus, 
    actionLoading: aiActionLoading, 
    toggleModule: toggleAIModule, 
    setGlobalShadowMode 
  } = useAIModules();
  
  const [selectedPosition, setSelectedPosition] = useState(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [localMessages, setLocalMessages] = useState([]);
  const [quickActionLoading, setQuickActionLoading] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState('mode'); // 'mode', 'risk', or 'ai'
  const [showAIInsights, setShowAIInsights] = useState(false);
  const [showRiskPanel, setShowRiskPanel] = useState(false);
  const conversationRef = useRef(null);
  
  // Initialize local messages with chat history when it loads
  useEffect(() => {
    if (chatHistory.length > 0 && localMessages.length === 0) {
      setLocalMessages(chatHistory);
    }
  }, [chatHistory, localMessages.length]);

  // Auto-scroll handled by ConversationPanel component now
  useEffect(() => {
    if (conversationRef.current) {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
    }
  }, [localMessages]);

  const handleChat = async (message) => {
    if (!message.trim() || chatLoading) return;
    
    setChatLoading(true);
    const userTimestamp = new Date().toISOString();
    
    // Add user message to local messages immediately
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: message,
      timestamp: userTimestamp,
      action_type: 'user_message',
      metadata: { role: 'user' }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
      });
      const data = await res.json();
      
      // Add assistant response AFTER user message (slightly later timestamp)
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: data.response || "We're processing your request...",
        timestamp: new Date().toISOString(), // Will be after userTimestamp
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: data.source }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
      // DON'T refresh stream here - it causes duplicate/reordering issues
      // The chat messages are already in localMessages
      return data;
    } catch (err) {
      console.error('Chat error:', err);
      // Add error message
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: "We're having trouble processing that right now. We'll keep trying.",
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setChatLoading(false);
    }
  };

  // Handle quick action clicks
  const handleQuickAction = async (action) => {
    setQuickActionLoading(action.id);
    
    // Add user message showing which action was triggered
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: action.prompt ? action.prompt : `Requesting ${action.label}...`,
      timestamp: new Date().toISOString(),
      action_type: 'user_message',
      metadata: { role: 'user', quickAction: action.id }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      let response;
      
      if (action.endpoint) {
        // Call specific coaching endpoint
        const res = await fetch(`${API_BASE}${action.endpoint}`);
        const data = await res.json();
        response = data.coaching || data.response || "We'll have that ready for you soon.";
      } else if (action.prompt) {
        // Send as chat message
        const res = await fetch(`${API_BASE}/api/sentcom/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: action.prompt })
        });
        const data = await res.json();
        response = data.response || "We're working on that analysis.";
      }
      
      // Add assistant response
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: response,
        timestamp: new Date().toISOString(),
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: action.id }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
    } catch (err) {
      console.error('Quick action error:', err);
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: `We couldn't complete that action right now. We'll try again shortly.`,
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setQuickActionLoading(null);
    }
  };

  // Handle Check My Trade form submission
  const handleCheckTrade = async (data) => {
    setQuickActionLoading('checkTrade');
    
    const userMsg = {
      id: `user_${Date.now()}`,
      type: 'chat',
      content: `Check Our Trade: ${data.action} ${data.symbol} @ $${data.entry_price} (stop: $${data.stop_loss})`,
      timestamp: new Date().toISOString(),
      action_type: 'user_message',
      metadata: { role: 'user', tradeCheck: data }
    };
    setLocalMessages(prev => [...prev, userMsg]);
    
    try {
      // Call both endpoints in parallel
      const [rulesRes, sizingRes] = await Promise.all([
        fetch(`${API_BASE}/api/assistant/coach/check-rules`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }).then(r => r.json()).catch(() => ({})),
        fetch(`${API_BASE}/api/assistant/coach/position-size`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }).then(r => r.json()).catch(() => ({}))
      ]);
      
      // Combine the responses
      let combinedResponse = '';
      
      if (rulesRes?.analysis) {
        combinedResponse += '## Rule Check\n\n' + rulesRes.analysis;
      }
      
      if (sizingRes?.analysis) {
        combinedResponse += '\n\n---\n\n## Position Sizing\n\n' + sizingRes.analysis;
      }
      
      if (!combinedResponse) {
        combinedResponse = "We're analyzing this trade setup. Make sure our systems are fully connected for complete analysis.";
      }
      
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        type: 'chat',
        content: combinedResponse,
        timestamp: new Date().toISOString(),
        action_type: 'chat_response',
        metadata: { role: 'assistant', source: 'trade_check' }
      };
      setLocalMessages(prev => [...prev, assistantMsg]);
      
    } catch (err) {
      console.error('Trade check error:', err);
      const errorMsg = {
        id: `error_${Date.now()}`,
        type: 'system',
        content: "We couldn't analyze that trade right now. Let's try again.",
        timestamp: new Date().toISOString(),
        action_type: 'error',
        metadata: { role: 'assistant' }
      };
      setLocalMessages(prev => [...prev, errorMsg]);
    } finally {
      setQuickActionLoading(null);
      setShowTradeForm(false);
    }
  };

  // Combine API messages with local chat messages, deduplicating by ID
  // Sort oldest to newest (chronological order for chat display)
  const allMessages = React.useMemo(() => {
    const combined = [...localMessages, ...messages];
    // Deduplicate by ID
    const seen = new Set();
    const unique = combined.filter(msg => {
      if (seen.has(msg.id)) return false;
      seen.add(msg.id);
      return true;
    });
    // Sort by timestamp ascending (oldest first) - chat messages should flow naturally
    return unique.sort((a, b) => 
      new Date(a.timestamp) - new Date(b.timestamp)
    ).slice(-30); // Keep last 30 messages
  }, [localMessages, messages]);

  // =========================================================================
  // EMBEDDED MODE - For Command Center (full-featured but fits in dashboard)
  // With glassy mockup styling and unified Trading Bot controls
  // =========================================================================
  if (embedded) {
    const isRunning = botStatus?.running;
    const mode = botStatus?.mode || 'confirmation';
    const regime = context?.regime || status?.regime || 'UNKNOWN';
    const connected = status?.connected || false;
    
    return (
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-white/[0.08] to-white/[0.02] border border-white/10 backdrop-blur-xl" data-testid="sentcom-embedded">
        {/* Ambient Background Effects */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-32 -right-32 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl" />
          <div className="absolute -bottom-32 -left-32 w-64 h-64 bg-violet-500/10 rounded-full blur-3xl" />
        </div>
        
        {/* Unified Header - Bot Controls + Status + Order Pipeline */}
        <div className="relative flex items-center justify-between px-4 py-3 border-b border-white/10 bg-black/40 backdrop-blur-xl">
          <div className="flex items-center gap-4">
            {/* Logo & Status */}
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 to-violet-500 blur-lg opacity-40" />
                <div className="relative w-11 h-11 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/20 shadow-lg shadow-cyan-500/20">
                  <Brain className="w-5 h-5 text-cyan-400" />
                </div>
              </div>
              <div>
                <h2 className="text-lg font-bold text-white tracking-tight">SENTCOM</h2>
                <div className="flex items-center gap-2 mt-0.5">
                  <div className="flex items-center gap-1.5">
                    {connected ? (
                      <PulsingDot color="emerald" />
                    ) : (
                      <Circle className="w-2 h-2 text-zinc-500" />
                    )}
                    <span className={`text-[10px] font-medium ${connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                      {connected ? 'CONNECTED' : 'OFFLINE'}
                    </span>
                  </div>
                  <span className="text-zinc-600">•</span>
                  {/* Market Session Badge */}
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                    marketSession.is_open 
                      ? marketSession.name === 'MARKET OPEN' 
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-amber-500/20 text-amber-400'
                      : 'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {marketSession.name || 'LOADING'}
                  </span>
                  {regime !== 'UNKNOWN' && (
                    <>
                      <span className="text-zinc-600">•</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                        regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                        regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                        'bg-zinc-500/20 text-zinc-400'
                      }`}>
                        {regime}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
            
            {/* Bot Status Badge */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${
              isRunning 
                ? 'bg-emerald-500/10 border-emerald-500/30' 
                : 'bg-zinc-500/10 border-zinc-500/30'
            }`}>
              <Bot className={`w-4 h-4 ${isRunning ? 'text-emerald-400' : 'text-zinc-500'}`} />
              <span className={`text-xs font-bold ${isRunning ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {isRunning ? 'ACTIVE' : 'STOPPED'}
              </span>
            </div>
            
            {/* Mode Indicator */}
            <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border ${
              mode === 'autonomous' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
              mode === 'confirmation' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400' :
              'bg-amber-500/10 border-amber-500/30 text-amber-400'
            }`}>
              {mode === 'autonomous' ? <Zap className="w-3.5 h-3.5" /> :
               mode === 'confirmation' ? <Eye className="w-3.5 h-3.5" /> :
               <Pause className="w-3.5 h-3.5" />}
              <span className="text-[10px] font-bold uppercase">{mode}</span>
            </div>
            
            {/* Dynamic Risk Badge */}
            <DynamicRiskBadge onClick={() => setShowRiskPanel(!showRiskPanel)} />
            
            {/* IB Connection */}
            <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border ${
              ibConnected 
                ? 'bg-cyan-500/10 border-cyan-500/30' 
                : 'bg-zinc-700/30 border-zinc-600/30'
            }`}>
              {ibConnected ? (
                <Wifi className="w-3.5 h-3.5 text-cyan-400" />
              ) : (
                <WifiOff className="w-3.5 h-3.5 text-zinc-500" />
              )}
              <span className={`text-[10px] font-bold ${ibConnected ? 'text-cyan-400' : 'text-zinc-500'}`}>
                {ibConnected ? 'IB LIVE' : 'OFFLINE'}
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            {/* Order Pipeline */}
            <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-black/40 border border-white/5">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-amber-500/20 flex items-center justify-center">
                  <Clock className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div>
                  <p className="text-base font-bold text-amber-400">{status?.order_pipeline?.pending || 0}</p>
                  <p className="text-[8px] text-zinc-500 uppercase">Pending</p>
                </div>
              </div>
              
              <ArrowRight className="w-3 h-3 text-zinc-600" />
              
              <div className="flex items-center gap-2">
                <div className={`w-7 h-7 rounded-lg bg-cyan-500/20 flex items-center justify-center ${(status?.order_pipeline?.executing || 0) > 0 ? 'animate-pulse' : ''}`}>
                  <Zap className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div>
                  <p className="text-base font-bold text-cyan-400">{status?.order_pipeline?.executing || 0}</p>
                  <p className="text-[8px] text-zinc-500 uppercase">Executing</p>
                </div>
              </div>
              
              <ArrowRight className="w-3 h-3 text-zinc-600" />
              
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div>
                  <p className="text-base font-bold text-emerald-400">{status?.order_pipeline?.filled || 0}</p>
                  <p className="text-[8px] text-zinc-500 uppercase">Filled</p>
                </div>
              </div>
            </div>
            
            {/* Bot Controls */}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={`p-2.5 rounded-xl transition-all border ${
                showSettings 
                  ? 'bg-cyan-500/20 border-cyan-500/30 text-cyan-400' 
                  : 'bg-white/5 border-white/5 text-zinc-400 hover:text-white hover:bg-white/10'
              }`}
              data-testid="sentcom-settings-btn"
            >
              <Settings className="w-4 h-4" />
            </button>
            
            <button
              onClick={toggleBot}
              disabled={actionLoading === 'toggle'}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm transition-all shadow-lg ${
                isRunning 
                  ? 'bg-gradient-to-r from-rose-500/20 to-rose-600/10 border border-rose-500/30 text-rose-400 hover:from-rose-500/30 shadow-rose-500/10' 
                  : 'bg-gradient-to-r from-emerald-500/20 to-emerald-600/10 border border-emerald-500/30 text-emerald-400 hover:from-emerald-500/30 shadow-emerald-500/10'
              }`}
              data-testid="sentcom-toggle-bot"
            >
              {actionLoading === 'toggle' ? (
                <Loader className="w-4 h-4 animate-spin" />
              ) : isRunning ? (
                <Pause className="w-4 h-4" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              {isRunning ? 'Stop' : 'Start'}
            </button>
          </div>
        </div>
        
        {/* Settings Panel (Mode Selector + Risk Controls) */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-b border-white/5"
            >
              <div className="relative p-4 bg-black/40">
                {/* Tab Navigation */}
                <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => setSettingsTab('mode')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'mode' 
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                  >
                    Trading Mode
                  </button>
                  <button
                    onClick={() => setSettingsTab('risk')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'risk' 
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                  >
                    Risk Controls
                  </button>
                  <button
                    onClick={() => setSettingsTab('ai')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      settingsTab === 'ai' 
                        ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30' 
                        : 'bg-zinc-800/50 text-zinc-400 border border-white/5 hover:border-white/10'
                    }`}
                    data-testid="settings-tab-ai"
                  >
                    AI Modules
                    {aiModulesStatus?.active_modules > 0 && (
                      <span className="ml-1.5 px-1.5 py-0.5 text-[9px] bg-violet-500/30 text-violet-300 rounded-full">
                        {aiModulesStatus.active_modules}
                      </span>
                    )}
                  </button>
                  <button
                    onClick={() => { console.log('AI Insights clicked, setting to true'); setShowAIInsights(true); }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all bg-gradient-to-r from-cyan-500/20 to-violet-500/20 text-cyan-400 border border-cyan-500/30 hover:border-cyan-500/50 flex items-center gap-1.5"
                    data-testid="open-ai-insights"
                  >
                    <BarChart3 className="w-3 h-3" />
                    AI Insights
                  </button>
                </div>

                {/* Tab Content */}
                {settingsTab === 'mode' ? (
                  <>
                    <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Trading Mode</h4>
                    <div className="grid grid-cols-3 gap-3">
                      {/* Autonomous Mode */}
                      <button
                        onClick={() => changeMode('autonomous')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'autonomous' 
                            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-autonomous"
                      >
                        <Zap className={`w-5 h-5 mx-auto mb-2 ${mode === 'autonomous' ? 'text-emerald-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Autonomous</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">Auto-execute trades</div>
                      </button>
                      
                      {/* Confirmation Mode */}
                      <button
                        onClick={() => changeMode('confirmation')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'confirmation' 
                            ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-confirmation"
                      >
                        <Eye className={`w-5 h-5 mx-auto mb-2 ${mode === 'confirmation' ? 'text-cyan-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Confirmation</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">Require approval</div>
                      </button>
                      
                      {/* Paused Mode */}
                      <button
                        onClick={() => changeMode('paused')}
                        className={`p-3 rounded-xl border text-center transition-all ${
                          mode === 'paused' 
                            ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' 
                            : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
                        }`}
                        data-testid="sentcom-mode-paused"
                      >
                        <Pause className={`w-5 h-5 mx-auto mb-2 ${mode === 'paused' ? 'text-amber-400' : 'text-zinc-500'}`} />
                        <div className="text-sm font-medium">Paused</div>
                        <div className="text-[10px] text-zinc-500 mt-0.5">No scanning</div>
                      </button>
                    </div>
                  </>
                ) : settingsTab === 'risk' ? (
                  <RiskControlsPanel 
                    botStatus={botStatus} 
                    onUpdateRisk={updateRiskParams}
                    loading={actionLoading === 'risk'}
                  />
                ) : (
                  <AIModulesPanel
                    aiStatus={aiModulesStatus}
                    onToggleModule={toggleAIModule}
                    onSetShadowMode={setGlobalShadowMode}
                    actionLoading={aiActionLoading}
                  />
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Dynamic Risk Panel - Slide-out */}
        <AnimatePresence>
          {showRiskPanel && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-b border-white/10 bg-black/40 backdrop-blur-xl overflow-hidden"
            >
              <div className="p-4 max-w-2xl mx-auto">
                <DynamicRiskPanel expanded={true} onToggleExpand={() => setShowRiskPanel(false)} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Main Content - Full Width Neural Split */}
        <div className="relative p-4 space-y-4">
          {/* Top Row - Positions Summary (Compact Horizontal) */}
          <div className="relative overflow-hidden rounded-xl bg-gradient-to-br from-white/[0.06] to-white/[0.02] border border-white/10 p-3">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-transparent pointer-events-none" />
            <div className="relative">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 flex items-center justify-center">
                    <Target className="w-3 h-3 text-emerald-400" />
                  </div>
                  <span className="text-sm font-bold text-white">Our Positions</span>
                  <span className="text-xs text-zinc-500">({positions.length} open)</span>
                </div>
                <span className={`text-base font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                </span>
              </div>
              
              {positionsLoading && positions.length === 0 ? (
                <div className="flex items-center justify-center py-4">
                  <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
                </div>
              ) : positions.length === 0 ? (
                <div className="flex items-center justify-center py-3 gap-2">
                  <Eye className="w-4 h-4 text-zinc-600" />
                  <p className="text-xs text-zinc-500">No open positions - scanning for setups...</p>
                </div>
              ) : (
                <div className="flex items-center gap-2 overflow-x-auto pb-1 custom-scrollbar">
                  {positions.slice(0, 8).map((pos, i) => (
                    <div 
                      key={pos.symbol || i}
                      onClick={() => setSelectedPosition(pos)}
                      className="flex-shrink-0 p-2.5 rounded-xl bg-black/40 border border-white/5 hover:border-white/20 cursor-pointer transition-all min-w-[140px]"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-white text-sm">{pos.symbol}</span>
                        <span className={`text-xs font-bold ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {pos.pnl >= 0 ? '+' : ''}{pos.pnl_percent?.toFixed(1) || '0'}%
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="text-zinc-400">${pos.current_price?.toFixed(2) || '—'}</span>
                        <span className={`font-medium ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) || '$0'}
                        </span>
                      </div>
                      {pos.stop_price && (
                        <div className="text-[9px] text-zinc-500 mt-1">
                          Stop: <span className="text-rose-400">${pos.stop_price?.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  ))}
                  {positions.length > 8 && (
                    <div className="flex-shrink-0 p-2.5 rounded-xl bg-black/20 border border-white/5 min-w-[80px] flex items-center justify-center">
                      <span className="text-xs text-zinc-500">+{positions.length - 8} more</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Full Width Neural Split: S.O.C. + Conversation */}
          <div className="grid grid-cols-12 gap-0 rounded-2xl overflow-hidden border border-white/10 h-[520px]" data-testid="neural-split-container">
            {/* Left: SentCom S.O.C. (Stream of Consciousness) - 40% */}
            <div className="col-span-5 h-full">
              <StreamOfConsciousness />
            </div>
            
            {/* Right: Conversation Panel - 60% */}
            <div className="col-span-7 h-full border-l border-white/10">
              <ConversationPanel
                messages={allMessages}
                onSendMessage={handleChat}
                onQuickAction={handleQuickAction}
                onCheckTrade={handleCheckTrade}
                loading={chatLoading}
                quickActionLoading={quickActionLoading}
              />
            </div>
          </div>
          
          {/* Stop Fix Panel - Shows when risky stops detected */}
          <StopFixPanel 
            thoughts={allMessages.filter(m => m.type === 'thought' || m.action_type === 'stop_warning')}
            onRefresh={refreshStream}
          />
        </div>

        {/* Position Detail Modal - Enhanced */}
        <AnimatePresence>
        {/* Position Detail Modal - Using EnhancedTickerModal for full chart view */}
        {selectedPosition && (
          <EnhancedTickerModal
            ticker={{ 
              symbol: selectedPosition.symbol,
              name: selectedPosition.symbol
            }}
            onClose={() => setSelectedPosition(null)}
            botPosition={selectedPosition}
            initialTab="overview"
          />
        )}
        </AnimatePresence>

        {/* AI Insights Dashboard Modal - Rendered inside embedded mode */}
        {showAIInsights && (
          <AIInsightsDashboard 
            key="ai-insights-dashboard-embedded"
            onClose={() => setShowAIInsights(false)} 
          />
        )}
      </div>
    );
  }

  // =========================================================================
  // COMPACT MODE - Small box (kept for reference but not used currently)
  // =========================================================================
  if (compact) {
    return (
      <div className="bg-zinc-900/50 backdrop-blur-xl rounded-2xl border border-white/10 overflow-hidden" data-testid="sentcom-compact">
        {/* Compact Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Brain className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">SENTCOM</h2>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {status?.connected ? (
                    <PulsingDot color="emerald" />
                  ) : (
                    <Circle className="w-2 h-2 text-zinc-500" />
                  )}
                  <span className={`text-[10px] font-medium ${status?.connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                    {status?.connected ? 'CONNECTED' : 'OFFLINE'}
                  </span>
                </div>
                {context?.regime && context.regime !== 'UNKNOWN' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                    context.regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                    context.regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                    'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {context.regime}
                  </span>
                )}
              </div>
            </div>
          </div>
          
          {/* Compact Order Pipeline */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/30">
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-amber-400" />
              <span className="text-sm font-bold text-amber-400">{status?.order_pipeline?.pending || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-cyan-400" />
              <span className="text-sm font-bold text-cyan-400">{status?.order_pipeline?.executing || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-emerald-400" />
              <span className="text-sm font-bold text-emerald-400">{status?.order_pipeline?.filled || 0}</span>
            </div>
          </div>
        </div>

        {/* Thought Label */}
        <div className="px-4 pt-3 pb-1">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">What we're thinking right now</p>
        </div>
        
        {/* Live Stream - compact height */}
        <div className="h-[280px] overflow-hidden">
          <StreamPanel messages={messages} loading={streamLoading} />
        </div>
        
        {/* Chat Input */}
        <ChatInput onSend={handleChat} disabled={!status?.connected} />
      </div>
    );
  }

  // Full page version
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-7xl mx-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <GlassCard gradient glow className="p-0">
            <StatusHeader status={status} context={context} />
          </GlassCard>
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left Column - Positions only */}
          <div className="col-span-3 space-y-6">
            <PositionsPanel 
              positions={positions} 
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={setSelectedPosition}
            />
          </div>

          {/* Center - Live Stream */}
          <div className="col-span-5">
            <div className="h-[600px] flex flex-col">
              <StreamPanel messages={messages} loading={streamLoading} />
              <ChatInput onSend={handleChat} disabled={!status?.connected} />
            </div>
          </div>

          {/* Right Column - Market Intel (Regime + Setups + Alerts) */}
          <div className="col-span-4">
            <MarketIntelPanel 
              context={context}
              setups={setups}
              alerts={alerts}
              contextLoading={contextLoading}
              setupsLoading={setupsLoading}
              alertsLoading={alertsLoading}
            />
          </div>
        </div>
      </div>

      {/* Position Detail Modal */}
      <AnimatePresence>
        {selectedPosition && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-8"
            onClick={() => setSelectedPosition(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-2xl"
              onClick={e => e.stopPropagation()}
            >
              <GlassCard glow className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-2xl font-bold text-white">Our {selectedPosition.symbol} Position</h2>
                    <p className="text-sm text-zinc-400">Entry: ${selectedPosition.entry_price?.toFixed(2)}</p>
                  </div>
                  <button
                    onClick={() => setSelectedPosition(null)}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-4 mb-6">
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">P&L</p>
                    <p className={`text-xl font-bold ${selectedPosition.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {selectedPosition.pnl >= 0 ? '+' : ''}{selectedPosition.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Stop</p>
                    <p className="text-xl font-bold text-rose-400">
                      ${selectedPosition.stop_price?.toFixed(2) || '--'}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Target</p>
                    <p className="text-xl font-bold text-emerald-400">
                      ${selectedPosition.target_prices?.[0]?.toFixed(2) || '--'}
                    </p>
                  </div>
                </div>

                <p className="text-sm text-zinc-400">
                  Shares: {selectedPosition.shares} • 
                  Entry: ${selectedPosition.entry_price?.toFixed(2)} • 
                  Current: ${selectedPosition.current_price?.toFixed(2)}
                </p>
              </GlassCard>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* AI Insights Dashboard Modal */}
      {showAIInsights && (
        <AIInsightsDashboard 
          key="ai-insights-dashboard"
          onClose={() => setShowAIInsights(false)} 
        />
      )}
    </div>
  );
};

export default SentCom;
