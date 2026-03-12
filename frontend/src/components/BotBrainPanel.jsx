/**
 * BotBrainPanel - Shows the bot's internal thoughts in first person
 * 
 * Features:
 * - Real-time thought stream: "I detected...", "I'm monitoring..."
 * - Timestamped entries with confidence badges
 * - Clickable ticker mentions
 * - "View History" to see full reasoning log
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Cpu, ChevronRight, Clock, Zap, Target, Eye, AlertCircle } from 'lucide-react';
import { useTickerModal } from '../hooks/useTickerModal';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

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
      {/* Header */}
      <div className="p-4 border-b border-white/5 flex justify-between items-center">
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
      
      {/* Thoughts Stream */}
      <div className="p-4 space-y-3 max-h-[220px] overflow-y-auto">
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
          <div className="text-center py-8 text-zinc-500">
            <Brain className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">Bot is idle. Start trading to see thoughts.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default BotBrainPanel;
