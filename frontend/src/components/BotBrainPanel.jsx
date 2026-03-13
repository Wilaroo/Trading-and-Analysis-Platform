/**
 * BotBrainPanel - Shows the bot's internal thoughts in first person
 * 
 * Features:
 * - Order Pipeline: Visual order flow (Pending → Executing → Filled)
 * - Real-time thought stream: "I detected...", "I'm monitoring..."
 * - Proactive Intelligence: Setup triggers, profit-taking suggestions, market alerts
 * - In-Trade Guidance: Position-specific alerts and recommendations
 * - Timestamped entries with confidence badges
 * - Clickable ticker mentions
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Cpu, ChevronRight, Clock, Zap, Target, Eye, AlertCircle, ArrowRight, CheckCircle, Loader, TrendingUp, Bell, Sparkles } from 'lucide-react';
import { useTickerModal } from '../hooks/useTickerModal';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Order Pipeline Mini Component
const OrderPipeline = ({ orderQueue }) => {
  const pending = orderQueue?.pending || 0;
  const executing = orderQueue?.executing || 0;
  const completed = orderQueue?.completed || 0;
  
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/30 border border-white/5">
      <span className="text-[10px] text-zinc-500 uppercase font-medium">Orders:</span>
      
      {/* Pending */}
      <div className={`flex items-center gap-1 px-2 py-0.5 rounded ${
        pending > 0 ? 'bg-yellow-500/20' : 'bg-zinc-800/50'
      }`}>
        <span className={`text-xs font-mono ${pending > 0 ? 'text-yellow-400' : 'text-zinc-500'}`}>
          {pending}
        </span>
        <span className="text-[10px] text-zinc-500">pending</span>
      </div>
      
      <ArrowRight className="w-3 h-3 text-zinc-600" />
      
      {/* Executing */}
      <div className={`flex items-center gap-1 px-2 py-0.5 rounded ${
        executing > 0 ? 'bg-cyan-500/20 animate-pulse' : 'bg-zinc-800/50'
      }`}>
        {executing > 0 && <Loader className="w-3 h-3 text-cyan-400 animate-spin" />}
        <span className={`text-xs font-mono ${executing > 0 ? 'text-cyan-400' : 'text-zinc-500'}`}>
          {executing}
        </span>
        <span className="text-[10px] text-zinc-500">executing</span>
      </div>
      
      <ArrowRight className="w-3 h-3 text-zinc-600" />
      
      {/* Completed */}
      <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10">
        <CheckCircle className="w-3 h-3 text-emerald-400" />
        <span className="text-xs font-mono text-emerald-400">{completed}</span>
        <span className="text-[10px] text-zinc-500">filled</span>
      </div>
    </div>
  );
};

// In-Trade Guidance Component - Shows position-specific alerts and recommendations
const InTradeGuidance = ({ openTrades = [], onTickerClick }) => {
  // Generate guidance based on position states
  const guidanceAlerts = useMemo(() => {
    const alerts = [];
    
    openTrades.forEach(trade => {
      const currentPrice = trade.current_price || 0;
      const entryPrice = trade.entry_price || 0;
      const stopPrice = trade.stop_price || 0;
      const targetPrice = trade.target_prices?.[0] || trade.target_price || 0;
      
      // Calculate percentages
      const pnlPct = entryPrice > 0 ? ((currentPrice - entryPrice) / entryPrice * 100) : 0;
      const distanceToStop = stopPrice > 0 ? ((currentPrice - stopPrice) / stopPrice * 100) : 100;
      const distanceToTarget = targetPrice > 0 ? ((targetPrice - currentPrice) / currentPrice * 100) : 100;
      
      // ALERT: Near Stop Loss (within 2%)
      if (stopPrice > 0 && Math.abs(distanceToStop) <= 2) {
        alerts.push({
          symbol: trade.symbol,
          type: 'danger',
          icon: '🛑',
          title: 'STOP WARNING',
          message: `${trade.symbol} is ${distanceToStop.toFixed(1)}% from stop loss. Consider tightening or exiting.`,
          priority: 1,
        });
      }
      
      // ALERT: Approaching Target (within 3%)
      else if (targetPrice > 0 && distanceToTarget <= 3 && distanceToTarget > 0) {
        alerts.push({
          symbol: trade.symbol,
          type: 'success',
          icon: '🎯',
          title: 'TARGET ZONE',
          message: `${trade.symbol} is ${distanceToTarget.toFixed(1)}% from target. Consider scaling out.`,
          priority: 2,
        });
      }
      
      // ALERT: Big Winner (up > 5%)
      else if (pnlPct >= 5) {
        alerts.push({
          symbol: trade.symbol,
          type: 'info',
          icon: '🚀',
          title: 'RUNNING',
          message: `${trade.symbol} up ${pnlPct.toFixed(1)}%. Consider trailing stop to lock gains.`,
          priority: 3,
        });
      }
      
      // ALERT: Underwater position (down > 3%)
      else if (pnlPct <= -3) {
        alerts.push({
          symbol: trade.symbol,
          type: 'warning',
          icon: '⚠️',
          title: 'UNDERWATER',
          message: `${trade.symbol} down ${Math.abs(pnlPct).toFixed(1)}%. Review thesis or cut if invalidated.`,
          priority: 2,
        });
      }
    });
    
    // Sort by priority (lower = more urgent)
    return alerts.sort((a, b) => a.priority - b.priority);
  }, [openTrades]);
  
  if (guidanceAlerts.length === 0) return null;
  
  const typeColors = {
    danger: 'border-red-500/50 bg-red-500/10',
    warning: 'border-yellow-500/50 bg-yellow-500/10',
    success: 'border-emerald-500/50 bg-emerald-500/10',
    info: 'border-cyan-500/50 bg-cyan-500/10',
  };
  
  const textColors = {
    danger: 'text-red-400',
    warning: 'text-yellow-400',
    success: 'text-emerald-400',
    info: 'text-cyan-400',
  };
  
  return (
    <div className="space-y-2 mt-3 pt-3 border-t border-white/5">
      <div className="flex items-center gap-2">
        <AlertCircle className="w-4 h-4 text-yellow-400" />
        <span className="text-xs text-zinc-400 font-medium uppercase">In-Trade Guidance</span>
      </div>
      
      {guidanceAlerts.slice(0, 3).map((alert, i) => (
        <motion.div
          key={`${alert.symbol}-${alert.type}-${i}`}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          className={`p-2 rounded-lg border cursor-pointer transition-all hover:scale-[1.01] ${typeColors[alert.type]}`}
          onClick={() => onTickerClick?.(alert.symbol)}
        >
          <div className="flex items-start gap-2">
            <span className="text-sm">{alert.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-bold ${textColors[alert.type]}`}>{alert.title}</span>
                <span className="text-xs font-mono text-white">{alert.symbol}</span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">{alert.message}</p>
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );
};

// Proactive Intelligence Component - Shows upcoming triggers, profit suggestions, market alerts
const ProactiveIntelligence = ({ watchingSetups = [], openTrades = [], botStatus, onTickerClick }) => {
  const [proactiveAlerts, setProactiveAlerts] = useState([]);
  
  // Generate proactive alerts based on current data
  useEffect(() => {
    const alerts = [];
    
    // 1. Setup Trigger Alerts - Setups approaching trigger price
    watchingSetups.forEach(setup => {
      if (!setup.trigger_price || !setup.current_price) return;
      
      const distanceToTrigger = ((setup.trigger_price - setup.current_price) / setup.current_price * 100);
      const isNearTrigger = Math.abs(distanceToTrigger) <= 2; // Within 2%
      
      if (isNearTrigger) {
        alerts.push({
          type: 'trigger',
          icon: '🎯',
          title: 'SETUP NEAR TRIGGER',
          symbol: setup.symbol,
          message: `${setup.symbol} is ${Math.abs(distanceToTrigger).toFixed(1)}% from trigger ($${setup.trigger_price?.toFixed(2)}). ${setup.setup_type || 'Entry'} setup ready.`,
          priority: 1,
          color: 'cyan'
        });
      }
    });
    
    // 2. Profit-Taking Suggestions - Positions with good gains
    openTrades.forEach(trade => {
      const pnlPct = trade.pnl_percent || (trade.current_price && trade.entry_price 
        ? ((trade.current_price - trade.entry_price) / trade.entry_price * 100) 
        : 0);
      
      // Suggest profit-taking at 1R (roughly 3-5%)
      if (pnlPct >= 3 && pnlPct < 5) {
        alerts.push({
          type: 'profit',
          icon: '💰',
          title: 'CONSIDER PARTIAL',
          symbol: trade.symbol,
          message: `${trade.symbol} is up ${pnlPct.toFixed(1)}%. Consider taking 25-50% off and moving stop to breakeven.`,
          priority: 2,
          color: 'emerald'
        });
      }
      
      // Strong runner - suggest trailing
      if (pnlPct >= 5) {
        alerts.push({
          type: 'runner',
          icon: '🚀',
          title: 'STRONG RUNNER',
          symbol: trade.symbol,
          message: `${trade.symbol} running +${pnlPct.toFixed(1)}%! Trail stop to lock gains. Consider scaling out at extended moves.`,
          priority: 2,
          color: 'purple'
        });
      }
    });
    
    // 3. Market Regime Alerts
    if (botStatus?.regime === 'RISK_OFF' && openTrades.length > 0) {
      alerts.push({
        type: 'regime',
        icon: '⚠️',
        title: 'RISK-OFF MARKET',
        symbol: null,
        message: 'Market in RISK-OFF mode. Consider tightening stops and reducing exposure.',
        priority: 3,
        color: 'amber'
      });
    }
    
    // 4. Session-based alerts
    const now = new Date();
    const hour = now.getHours();
    const minute = now.getMinutes();
    
    // Power hour alert (3-4 PM)
    if (hour === 15 && minute < 15) {
      alerts.push({
        type: 'session',
        icon: '⚡',
        title: 'POWER HOUR',
        symbol: null,
        message: 'Power Hour starting! Expect increased volatility. Good for momentum plays.',
        priority: 4,
        color: 'purple'
      });
    }
    
    // EOD warning (15 min before close)
    if (hour === 15 && minute >= 45) {
      alerts.push({
        type: 'session',
        icon: '🔔',
        title: 'MARKET CLOSING',
        symbol: null,
        message: 'Market closing soon. Review open positions and pending orders.',
        priority: 1,
        color: 'amber'
      });
    }
    
    // Sort by priority
    alerts.sort((a, b) => a.priority - b.priority);
    setProactiveAlerts(alerts.slice(0, 4));
  }, [watchingSetups, openTrades, botStatus]);
  
  if (proactiveAlerts.length === 0) return null;
  
  const colorMap = {
    cyan: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-400',
    emerald: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400',
    purple: 'border-purple-500/50 bg-purple-500/10 text-purple-400',
    amber: 'border-amber-500/50 bg-amber-500/10 text-amber-400',
    red: 'border-red-500/50 bg-red-500/10 text-red-400',
  };
  
  return (
    <div className="px-4 pb-3 border-t border-white/5">
      <div className="flex items-center gap-2 py-2">
        <Sparkles className="w-4 h-4 text-purple-400" />
        <span className="text-xs text-zinc-400 font-medium uppercase">Proactive Intelligence</span>
        <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 text-[10px] font-mono">
          {proactiveAlerts.length} ALERTS
        </span>
      </div>
      
      <div className="space-y-1.5">
        {proactiveAlerts.map((alert, i) => (
          <motion.div
            key={`${alert.type}-${alert.symbol || i}`}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.05 }}
            className={`p-2 rounded-lg border cursor-pointer transition-all hover:scale-[1.01] ${colorMap[alert.color]}`}
            onClick={() => alert.symbol && onTickerClick?.(alert.symbol)}
          >
            <div className="flex items-start gap-2">
              <span className="text-sm">{alert.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold">{alert.title}</span>
                  {alert.symbol && (
                    <span className="text-xs font-mono text-white">{alert.symbol}</span>
                  )}
                </div>
                <p className="text-[10px] text-zinc-400 mt-0.5 leading-relaxed">{alert.message}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
};

// Confidence badge colors
const getConfidenceBadge = (confidence, actionType = '') => {
  // Special handling for stop warnings
  if (actionType === 'stop_warning') {
    if (confidence >= 90) return { text: 'CRITICAL', bg: 'bg-red-500/30', color: 'text-red-400' };
    if (confidence >= 70) return { text: 'WARNING', bg: 'bg-amber-500/30', color: 'text-amber-400' };
    return { text: 'HEADS UP', bg: 'bg-blue-500/20', color: 'text-blue-400' };
  }
  
  if (confidence >= 80) return { text: 'HIGH CONFIDENCE', bg: 'bg-emerald-500/20', color: 'text-emerald-400' };
  if (confidence >= 60) return { text: 'MONITORING', bg: 'bg-purple-500/20', color: 'text-purple-400' };
  if (confidence >= 40) return { text: 'WATCHING', bg: 'bg-amber-500/20', color: 'text-amber-400' };
  return { text: 'ANALYZING', bg: 'bg-zinc-500/20', color: 'text-zinc-400' };
};

// Action type icons
const ActionIcon = ({ type, severity }) => {
  switch (type) {
    case 'stop_warning':
      return severity === 'critical' 
        ? <AlertCircle className="w-4 h-4 text-red-400 animate-pulse" />
        : <AlertCircle className="w-4 h-4 text-amber-400" />;
    case 'entry':
    case 'buy':
      return <Zap className="w-4 h-4 text-emerald-400" />;
    case 'exit':
    case 'sell':
      return <Target className="w-4 h-4 text-red-400" />;
    case 'watching':
      return <Eye className="w-4 h-4 text-purple-400" />;
    case 'alert':
      return <AlertCircle className="w-4 h-4 text-amber-400" />;
    default:
      return <Brain className="w-4 h-4 text-cyan-400" />;
  }
};

// Parse thought text and make tickers clickable
const ThoughtText = ({ text, onTickerClick }) => {
  if (!text) return null;
  
  // Regex to find ticker symbols (uppercase 1-5 letters, often preceded by space or start)
  const tickerRegex = /\b([A-Z]{1,5})\b(?=\s|$|[.,!?])/g;
  const commonTickers = ['AAPL', 'NVDA', 'AMD', 'TSLA', 'META', 'GOOGL', 'MSFT', 'AMZN', 'SPY', 'QQQ', 'LABD', 'SQQQ', 'TQQQ'];
  
  const parts = [];
  let lastIndex = 0;
  let match;
  
  while ((match = tickerRegex.exec(text)) !== null) {
    const ticker = match[1];
    // Only make it clickable if it looks like a real ticker
    if (commonTickers.includes(ticker) || ticker.length >= 2) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }
      parts.push(
        <button
          key={match.index}
          onClick={(e) => {
            e.stopPropagation();
            onTickerClick?.(ticker);
          }}
          className="px-1.5 py-0.5 rounded bg-cyan-400/20 text-cyan-400 text-xs font-mono hover:bg-cyan-400/30 transition-colors mx-0.5"
        >
          {ticker}
        </button>
      );
      lastIndex = match.index + match[0].length;
    }
  }
  
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  
  return <>{parts.length > 0 ? parts : text}</>;
};

// Single thought entry
const ThoughtEntry = ({ thought, index, onTickerClick }) => {
  const confidence = thought.confidence || 50;
  const actionType = thought.action_type || '';
  const severity = thought.severity || '';
  const badge = getConfidenceBadge(confidence, actionType);
  const timestamp = thought.timestamp 
    ? new Date(thought.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null;
  
  // Special styling for stop warnings
  const isStopWarning = actionType === 'stop_warning';
  const borderColor = isStopWarning 
    ? (severity === 'critical' ? 'border-red-500' : severity === 'warning' ? 'border-amber-500' : 'border-blue-400')
    : 'border-cyan-400';
  const bgGradient = isStopWarning
    ? (severity === 'critical' ? 'from-red-500/20' : severity === 'warning' ? 'from-amber-500/15' : 'from-blue-400/10')
    : 'from-cyan-400/10';
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.05 }}
      className={`border-l-[3px] ${borderColor} bg-gradient-to-r ${bgGradient} to-transparent p-3 rounded-r-lg ${
        index > 0 ? 'opacity-80' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
          isStopWarning 
            ? (severity === 'critical' ? 'bg-red-500/30' : 'bg-amber-500/30')
            : (index === 0 ? 'bg-cyan-400/30' : 'bg-cyan-400/20')
        }`}>
          {isStopWarning ? (
            <ActionIcon type={actionType} severity={severity} />
          ) : (
            <span className="text-xs text-cyan-400">{index + 1}</span>
          )}
        </div>
        
        <div className="flex-1 min-w-0">
          <p className={`text-sm leading-relaxed ${isStopWarning ? 'text-zinc-100' : 'text-zinc-200'}`}>
            <ThoughtText text={thought.text} onTickerClick={onTickerClick} />
          </p>
          
          <div className="flex items-center gap-4 mt-2 text-xs">
            {timestamp && (
              <span className="text-zinc-500 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {timestamp}
              </span>
            )}
            <span className={`px-2 py-0.5 rounded ${badge.bg} ${badge.color}`}>
              {badge.text}
            </span>
            {thought.action_type && !isStopWarning && (
              <span className="flex items-center gap-1 text-zinc-400">
                <ActionIcon type={thought.action_type} />
                {thought.action_type}
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const BotBrainPanel = ({ 
  botStatus = null,
  openTrades = [],
  watchingSetups = [],
  orderQueue = null,
  className = '',
  onViewHistory,
  maxThoughts = 3,
  autoRefresh = true
}) => {
  const [thoughts, setThoughts] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { openTickerModal } = useTickerModal();
  
  // Fetch thoughts from API
  const fetchThoughts = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/trading-bot/thoughts?limit=${maxThoughts + 2}`);
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.thoughts) {
          setThoughts(data.thoughts.slice(0, maxThoughts));
          // Check if bot is actively processing based on thought types
          const hasActiveThoughts = data.thoughts.some(t => 
            t.action_type === 'scanning' || t.action_type === 'entry' || 
            t.action_type === 'monitoring' || t.action_type === 'stop_warning'
          );
          setIsProcessing(hasActiveThoughts);
        }
      }
    } catch (err) {
      console.error('Failed to fetch bot thoughts:', err);
      // Fall back to generating from props
      generateThoughtsFromProps();
    } finally {
      setIsLoading(false);
    }
  }, [maxThoughts]);
  
  // Generate thoughts from props as fallback
  const generateThoughtsFromProps = useCallback(() => {
    const newThoughts = [];
    
    // Add thoughts about setups being watched
    if (watchingSetups && watchingSetups.length > 0) {
      const topSetup = watchingSetups[0];
      newThoughts.push({
        text: `"I detected a ${topSetup.setup_type || 'potential setup'} forming on ${topSetup.symbol}. ${
          topSetup.trigger_price ? `Entry trigger at $${topSetup.trigger_price.toFixed(2)}.` : ''
        } ${topSetup.risk_reward ? `R:R is ${topSetup.risk_reward.toFixed(1)}:1.` : ''} I'm preparing to enter if conditions confirm."`,
        timestamp: topSetup.timestamp || new Date().toISOString(),
        confidence: topSetup.confidence || 75,
        action_type: 'watching',
        symbol: topSetup.symbol,
      });
    }
    
    // Add thoughts about open positions
    if (openTrades && openTrades.length > 0) {
      openTrades.slice(0, 2).forEach(trade => {
        const pnlPct = trade.pnl_percent || (trade.current_price && trade.entry_price 
          ? ((trade.current_price - trade.entry_price) / trade.entry_price * 100) 
          : 0);
        const direction = pnlPct >= 0 ? 'up' : 'down';
        
        newThoughts.push({
          text: `"I'm monitoring my ${trade.symbol} position. Currently ${direction} ${Math.abs(pnlPct).toFixed(1)}%. ${
            trade.stop_price ? `Stop is safe at $${trade.stop_price.toFixed(2)}.` : ''
          } ${
            trade.target_prices?.[0] && pnlPct > 0 
              ? `I'll consider taking profits near $${trade.target_prices[0].toFixed(2)}.` 
              : ''
          }"`,
          timestamp: trade.last_update || trade.entry_time || new Date().toISOString(),
          confidence: 60,
          action_type: 'monitoring',
          symbol: trade.symbol,
        });
      });
    }
    
    // Add general market awareness thought
    if (botStatus?.state === 'hunting' || botStatus?.state === 'active') {
      newThoughts.push({
        text: `"I'm actively scanning for opportunities. ${
          botStatus.regime ? `Market regime is ${botStatus.regime}, so I'm ${
            botStatus.regime === 'RISK_ON' ? 'looking for aggressive setups.' :
            botStatus.regime === 'RISK_OFF' ? 'being cautious with entries.' :
            'using standard position sizing.'
          }` : ''
        }"`,
        timestamp: new Date().toISOString(),
        confidence: 50,
        action_type: 'scanning',
      });
    }
    
    // If no real data, show demo thoughts
    if (newThoughts.length === 0) {
      newThoughts.push(
        {
          text: `"I'm monitoring market conditions and scanning for setups that match my criteria. Looking for high R:R opportunities with clear entry triggers."`,
          timestamp: new Date().toISOString(),
          confidence: 50,
          action_type: 'scanning',
        }
      );
    }
    
    setThoughts(newThoughts.slice(0, maxThoughts));
    setIsProcessing(botStatus?.state === 'hunting' || botStatus?.state === 'active');
  }, [botStatus, openTrades, watchingSetups, maxThoughts]);
  
  // Initial fetch
  useEffect(() => {
    fetchThoughts();
  }, [fetchThoughts]);
  
  // Auto-refresh every 30 seconds
  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(fetchThoughts, 30000);
      return () => clearInterval(interval);
    }
  }, [fetchThoughts, autoRefresh]);
  
  // Also update from props changes
  useEffect(() => {
    // If we have prop data but no API thoughts, use props
    if (thoughts.length === 0) {
      generateThoughtsFromProps();
    }
  }, [botStatus, openTrades, watchingSetups, thoughts.length, generateThoughtsFromProps]);

  return (
    <div className={`bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* Header with Order Pipeline */}
      <div className="p-4 border-b border-white/5">
        <div className="flex justify-between items-center mb-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-400/20 flex items-center justify-center">
              <Cpu className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="font-bold text-lg text-cyan-400">BOT'S BRAIN</h2>
              <p className="text-xs text-zinc-500">What I'm thinking right now</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            {/* Processing indicator */}
            {isProcessing && (
              <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-400/10">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-xs text-cyan-400">Processing</span>
              </div>
            )}
            
            {onViewHistory && (
              <button 
                onClick={onViewHistory}
                className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
              >
                View History
                <ChevronRight className="w-3 h-3" />
              </button>
            )}
          </div>
        </div>
        
        {/* Order Pipeline */}
        {orderQueue && (
          <OrderPipeline orderQueue={orderQueue} />
        )}
      </div>
      
      {/* Thoughts Stream */}
      <div className="p-4 space-y-3 max-h-[300px] overflow-y-auto">
        <AnimatePresence mode="popLayout">
          {thoughts.map((thought, index) => (
            <ThoughtEntry
              key={`${thought.timestamp}-${index}`}
              thought={thought}
              index={index}
              onTickerClick={openTickerModal}
            />
          ))}
        </AnimatePresence>
        
        {thoughts.length === 0 && (
          <div className="text-center py-4 text-zinc-500">
            <Brain className="w-6 h-6 mx-auto mb-1 opacity-50" />
            <p className="text-xs">Bot is idle. Start trading to see thoughts.</p>
          </div>
        )}
      </div>
      
      {/* Proactive Intelligence Alerts */}
      <ProactiveIntelligence 
        watchingSetups={watchingSetups}
        openTrades={openTrades}
        botStatus={botStatus}
        onTickerClick={openTickerModal}
      />
      
      {/* In-Trade Guidance Alerts */}
      {openTrades && openTrades.length > 0 && (
        <div className="px-4 pb-4">
          <InTradeGuidance 
            openTrades={openTrades} 
            onTickerClick={openTickerModal}
          />
        </div>
      )}
    </div>
  );
};

export default BotBrainPanel;
