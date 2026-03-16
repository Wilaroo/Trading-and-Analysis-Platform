/**
 * StreamOfConsciousness.jsx - SentCom S.O.C. Panel
 * 
 * Rich, terminal-style panel showing the bot's background activity with
 * detailed information per entry including icons, data, and reasoning.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Search, TrendingUp, TrendingDown, AlertTriangle, Activity, 
  Target, Eye, Zap, Brain, RefreshCw, Filter, CheckCircle,
  XCircle, Clock, Gauge, Radio, ChevronDown, ChevronUp,
  DollarSign, ArrowUpRight, ArrowDownRight, Shield, Crosshair,
  BarChart2, PieChart, Percent, Hash, AlertCircle, Play, 
  StopCircle, ShoppingCart, Ban, ThumbsUp, ThumbsDown
} from 'lucide-react';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// Format timestamp for terminal style display
const formatTerminalTime = (timestamp) => {
  if (!timestamp) return '--:--:--';
  const time = new Date(timestamp);
  return time.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit',
    hour12: false 
  });
};

// Hook for fetching S.O.C. stream data
export const useSOCStream = (pollInterval = 3000) => {
  const [thoughts, setThoughts] = useState([]);
  const [loading, setLoading] = useState(true);
  const lastDataRef = useRef('');

  const fetchThoughts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/stream?limit=30`);
      const data = await res.json();
      
      if (data.success && data.messages) {
        // Filter for non-chat messages (thoughts, scans, alerts, status)
        const socMessages = data.messages.filter(m => 
          m.type !== 'chat' && 
          m.action_type !== 'chat_response' && 
          m.action_type !== 'user_message'
        );
        
        // Only update if data actually changed
        const newDataStr = JSON.stringify(socMessages.map(m => m.id || m.timestamp));
        if (newDataStr !== lastDataRef.current) {
          lastDataRef.current = newDataStr;
          setThoughts(socMessages);
        }
      }
    } catch (err) {
      console.error('Error fetching S.O.C. stream:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchThoughts();
    const interval = setInterval(fetchThoughts, pollInterval);
    return () => clearInterval(interval);
  }, [fetchThoughts, pollInterval]);

  return { thoughts, loading, refresh: fetchThoughts };
};

// Rich S.O.C. Entry Component with detailed data display
const SOCEntry = React.memo(({ entry, index }) => {
  const [expanded, setExpanded] = useState(false);
  
  // Get entry configuration based on type
  const getEntryConfig = () => {
    const type = entry.type;
    const actionType = entry.action_type;
    
    // Trade executed
    if (actionType === 'trade_executed' || actionType === 'order_filled') {
      const side = entry.metadata?.side || entry.metadata?.action || '';
      return {
        icon: side.toLowerCase() === 'sell' ? <ArrowDownRight className="w-4 h-4" /> : <ArrowUpRight className="w-4 h-4" />,
        color: side.toLowerCase() === 'sell' ? 'text-rose-400' : 'text-emerald-400',
        bgColor: side.toLowerCase() === 'sell' ? 'bg-rose-500/10' : 'bg-emerald-500/10',
        borderColor: side.toLowerCase() === 'sell' ? 'border-rose-500/30' : 'border-emerald-500/30',
        label: 'TRADE',
        priority: 'high'
      };
    }
    
    // Trade decision / Smart filter
    if (actionType === 'trade_decision' || type === 'decision') {
      const decision = entry.metadata?.decision || '';
      const isApproved = decision.toLowerCase().includes('approved') || decision.toLowerCase().includes('take');
      return {
        icon: isApproved ? <ThumbsUp className="w-4 h-4" /> : <ThumbsDown className="w-4 h-4" />,
        color: isApproved ? 'text-emerald-400' : 'text-amber-400',
        bgColor: isApproved ? 'bg-emerald-500/10' : 'bg-amber-500/10',
        borderColor: isApproved ? 'border-emerald-500/30' : 'border-amber-500/30',
        label: 'DECISION',
        priority: 'high'
      };
    }
    
    // Setup found
    if (actionType === 'setup_found' || type === 'setup' || type === 'alert') {
      return {
        icon: <Target className="w-4 h-4" />,
        color: 'text-cyan-400',
        bgColor: 'bg-cyan-500/10',
        borderColor: 'border-cyan-500/30',
        label: 'SETUP',
        priority: 'high'
      };
    }
    
    // Risk updates
    if (actionType === 'risk_update' || type === 'risk') {
      return {
        icon: <Shield className="w-4 h-4" />,
        color: 'text-rose-400',
        bgColor: 'bg-rose-500/10',
        borderColor: 'border-rose-500/30',
        label: 'RISK',
        priority: 'medium'
      };
    }
    
    // Market regime / VIX
    if (actionType === 'regime_update' || actionType === 'breadth_update' || type === 'market') {
      const isRiskOn = entry.content?.toLowerCase().includes('risk_on') || entry.content?.toLowerCase().includes('risk on');
      return {
        icon: <BarChart2 className="w-4 h-4" />,
        color: isRiskOn ? 'text-emerald-400' : 'text-amber-400',
        bgColor: isRiskOn ? 'bg-emerald-500/10' : 'bg-amber-500/10',
        borderColor: isRiskOn ? 'border-emerald-500/30' : 'border-amber-500/30',
        label: 'MARKET',
        priority: 'medium'
      };
    }
    
    // Position monitoring
    if (actionType === 'monitoring' || type === 'monitor') {
      return {
        icon: <Eye className="w-4 h-4" />,
        color: 'text-blue-400',
        bgColor: 'bg-blue-500/10',
        borderColor: 'border-blue-500/30',
        label: 'WATCH',
        priority: 'medium'
      };
    }
    
    // Price updates
    if (actionType === 'price_update' || type === 'position') {
      const pnl = entry.metadata?.pnl_percent || 0;
      return {
        icon: pnl >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />,
        color: pnl >= 0 ? 'text-emerald-400' : 'text-rose-400',
        bgColor: pnl >= 0 ? 'bg-emerald-500/10' : 'bg-rose-500/10',
        borderColor: pnl >= 0 ? 'border-emerald-500/30' : 'border-rose-500/30',
        label: 'POS',
        priority: 'low'
      };
    }
    
    // Entry zone
    if (actionType === 'entry_zone') {
      return {
        icon: <Crosshair className="w-4 h-4" />,
        color: 'text-emerald-400',
        bgColor: 'bg-emerald-500/10',
        borderColor: 'border-emerald-500/30',
        label: 'ENTRY',
        priority: 'high'
      };
    }
    
    // Stop warnings
    if (actionType === 'stop_warning') {
      return {
        icon: <AlertTriangle className="w-4 h-4" />,
        color: 'text-amber-400',
        bgColor: 'bg-amber-500/10',
        borderColor: 'border-amber-500/30',
        label: 'STOP',
        priority: 'high'
      };
    }
    
    // Filter decisions
    if (type === 'filter' || actionType === 'filter') {
      const decision = entry.metadata?.decision || entry.action_type || '';
      const isPassed = decision.toLowerCase().includes('pass') || decision.toLowerCase().includes('approved');
      return {
        icon: isPassed ? <CheckCircle className="w-4 h-4" /> : <Ban className="w-4 h-4" />,
        color: isPassed ? 'text-emerald-400' : 'text-zinc-400',
        bgColor: isPassed ? 'bg-emerald-500/10' : 'bg-zinc-500/10',
        borderColor: isPassed ? 'border-emerald-500/30' : 'border-zinc-500/30',
        label: 'FILTER',
        priority: 'low'
      };
    }
    
    // Scanning
    if (actionType === 'scanning' || type === 'thought') {
      return {
        icon: <Search className="w-4 h-4" />,
        color: 'text-violet-400',
        bgColor: 'bg-violet-500/10',
        borderColor: 'border-violet-500/30',
        label: 'SCAN',
        priority: 'low'
      };
    }
    
    // Default
    return {
      icon: <Radio className="w-4 h-4" />,
      color: 'text-zinc-400',
      bgColor: 'bg-zinc-500/10',
      borderColor: 'border-zinc-500/30',
      label: 'SYS',
      priority: 'low'
    };
  };
  
  const config = getEntryConfig();
  const metadata = entry.metadata || {};
  const reasoning = metadata.reasoning || entry.reasoning;
  
  // Extract key data points for display
  const getDataPoints = () => {
    const points = [];
    
    // Symbol
    if (entry.symbol) {
      points.push({ icon: <Hash className="w-3 h-3" />, label: entry.symbol, color: 'text-white font-bold' });
    }
    
    // Price
    if (metadata.price || metadata.entry_price || metadata.current_price) {
      const price = metadata.price || metadata.entry_price || metadata.current_price;
      points.push({ icon: <DollarSign className="w-3 h-3" />, label: `$${parseFloat(price).toFixed(2)}`, color: 'text-cyan-400' });
    }
    
    // Stop price
    if (metadata.stop_price) {
      points.push({ icon: <StopCircle className="w-3 h-3" />, label: `Stop $${parseFloat(metadata.stop_price).toFixed(2)}`, color: 'text-rose-400' });
    }
    
    // P&L
    if (metadata.pnl_percent !== undefined) {
      const pnl = parseFloat(metadata.pnl_percent);
      points.push({ 
        icon: pnl >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />, 
        label: `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%`, 
        color: pnl >= 0 ? 'text-emerald-400' : 'text-rose-400' 
      });
    }
    
    // VIX
    if (metadata.vix !== undefined) {
      points.push({ icon: <Activity className="w-3 h-3" />, label: `VIX ${parseFloat(metadata.vix).toFixed(1)}`, color: 'text-amber-400' });
    }
    
    // Risk multiplier
    if (metadata.multiplier !== undefined) {
      points.push({ icon: <Gauge className="w-3 h-3" />, label: `${parseFloat(metadata.multiplier).toFixed(1)}x`, color: 'text-rose-400' });
    }
    
    // Score
    if (metadata.score !== undefined) {
      points.push({ icon: <BarChart2 className="w-3 h-3" />, label: `Score ${parseFloat(metadata.score).toFixed(1)}`, color: 'text-cyan-400' });
    }
    
    // Setup type
    if (metadata.setup_type) {
      points.push({ icon: <Target className="w-3 h-3" />, label: metadata.setup_type.replace(/_/g, ' '), color: 'text-violet-400' });
    }
    
    // Regime
    if (metadata.regime) {
      const isRiskOn = metadata.regime.toLowerCase().includes('on');
      points.push({ 
        icon: <Shield className="w-3 h-3" />, 
        label: metadata.regime.replace('_', ' '), 
        color: isRiskOn ? 'text-emerald-400' : 'text-amber-400' 
      });
    }
    
    // Breadth
    if (metadata.breadth !== undefined) {
      points.push({ icon: <PieChart className="w-3 h-3" />, label: `${metadata.breadth}% breadth`, color: 'text-cyan-400' });
    }
    
    return points;
  };
  
  const dataPoints = getDataPoints();
  const isPriority = config.priority === 'high';
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: Math.min(index * 0.02, 0.15) }}
      className={`group border-b border-white/5 py-2.5 px-3 hover:bg-white/[0.02] transition-colors cursor-pointer ${isPriority ? 'bg-white/[0.01]' : ''}`}
      onClick={() => reasoning && setExpanded(!expanded)}
      data-testid={`soc-entry-${index}`}
    >
      {/* Main Row */}
      <div className="flex items-start gap-3">
        {/* Timestamp + Icon Column */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[10px] font-mono text-zinc-600 w-[52px]">
            {formatTerminalTime(entry.timestamp)}
          </span>
          <div className={`w-7 h-7 rounded-lg ${config.bgColor} border ${config.borderColor} flex items-center justify-center`}>
            <span className={config.color}>{config.icon}</span>
          </div>
        </div>
        
        {/* Content Column */}
        <div className="flex-1 min-w-0">
          {/* Label + Content */}
          <div className="flex items-start gap-2">
            <span className={`text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded ${config.bgColor} ${config.color} flex-shrink-0`}>
              {config.label}
            </span>
            <p className="text-sm text-zinc-200 leading-relaxed flex-1">
              {entry.content}
            </p>
            {reasoning && (
              <motion.div animate={{ rotate: expanded ? 180 : 0 }} className="text-zinc-600 flex-shrink-0 mt-0.5">
                <ChevronDown className="w-3.5 h-3.5" />
              </motion.div>
            )}
          </div>
          
          {/* Data Points Row */}
          {dataPoints.length > 0 && (
            <div className="flex items-center gap-3 mt-2 flex-wrap">
              {dataPoints.map((point, i) => (
                <div key={i} className={`flex items-center gap-1 text-[10px] ${point.color}`}>
                  {point.icon}
                  <span>{point.label}</span>
                </div>
              ))}
            </div>
          )}
          
          {/* Confidence Bar */}
          {entry.confidence && (
            <div className="flex items-center gap-2 mt-2">
              <div className="h-1.5 w-24 bg-zinc-800 rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${entry.confidence}%` }}
                  className={`h-full ${config.bgColor.replace('/10', '/60')}`}
                />
              </div>
              <span className="text-[9px] text-zinc-500">{entry.confidence}% conf</span>
            </div>
          )}
          
          {/* Expanded Reasoning */}
          <AnimatePresence>
            {expanded && reasoning && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-3 pt-2 border-t border-white/5"
              >
                <div className="flex items-start gap-2">
                  <Brain className="w-3.5 h-3.5 text-violet-400 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    {reasoning}
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
});

SOCEntry.displayName = 'SOCEntry';

// Main S.O.C. Panel Component
const StreamOfConsciousness = ({ className = '' }) => {
  const { thoughts, loading, refresh } = useSOCStream();
  const scrollRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);
  
  // Auto-scroll to bottom when new thoughts arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [thoughts, autoScroll]);
  
  // Detect manual scroll to pause auto-scroll
  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };
  
  // Count by priority
  const highPriorityCount = thoughts.filter(t => 
    ['trade_executed', 'trade_decision', 'setup_found', 'entry_zone', 'stop_warning'].includes(t.action_type) ||
    ['setup', 'alert', 'decision'].includes(t.type)
  ).length;
  
  return (
    <div className={`flex flex-col h-full bg-[#050505] ${className}`} data-testid="soc-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-black/40">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
            <div className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping opacity-50" />
          </div>
          <div>
            <span className="text-sm font-bold text-emerald-400 uppercase tracking-wider">
              SentCom S.O.C.
            </span>
            <p className="text-[9px] text-zinc-500">Stream of Consciousness</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {highPriorityCount > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
              {highPriorityCount} alerts
            </span>
          )}
          <button
            onClick={refresh}
            className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
            title="Refresh"
            data-testid="soc-refresh-btn"
          >
            <RefreshCw className="w-3.5 h-3.5 text-zinc-500 hover:text-zinc-300" />
          </button>
        </div>
      </div>
      
      {/* Content */}
      <div 
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono custom-scrollbar"
        data-testid="soc-content"
      >
        {loading && thoughts.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Activity className="w-8 h-8 text-zinc-600 mx-auto mb-3 animate-pulse" />
              <p className="text-sm text-zinc-500">Initializing...</p>
            </div>
          </div>
        ) : thoughts.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Brain className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
              <p className="text-sm text-zinc-500">Waiting for activity...</p>
              <p className="text-[10px] text-zinc-600 mt-1">Bot thoughts and trade decisions will appear here</p>
            </div>
          </div>
        ) : (
          <div>
            {thoughts.map((thought, i) => (
              <SOCEntry key={thought.id || `thought-${i}`} entry={thought} index={i} />
            ))}
          </div>
        )}
      </div>
      
      {/* Footer status bar */}
      <div className="px-4 py-2 border-t border-white/10 bg-black/60 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-zinc-600">{thoughts.length} entries</span>
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true);
                if (scrollRef.current) {
                  scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                }
              }}
              className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
            >
              <ChevronDown className="w-3 h-3" />
              Resume live
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-1.5 h-1.5 rounded-full ${autoScroll ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          <span className="text-[10px] text-zinc-600 font-mono">
            {autoScroll ? 'LIVE' : 'PAUSED'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default StreamOfConsciousness;
