/**
 * StreamOfConsciousness.jsx - SentCom S.O.C. Panel
 * 
 * Terminal-style panel showing the bot's background activity, thoughts, 
 * status updates, and reasoning. This is separate from the user conversation.
 * 
 * Designed with the "Neural Split" layout in mind.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Search, TrendingUp, TrendingDown, AlertTriangle, Activity, 
  Target, Eye, Zap, Brain, RefreshCw, Filter, CheckCircle,
  XCircle, Clock, Gauge, Radio, ChevronDown, ChevronUp
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

// Individual S.O.C. entry component
const SOCEntry = React.memo(({ entry, index }) => {
  const [expanded, setExpanded] = useState(false);
  
  // Determine entry type and styling
  const getEntryConfig = () => {
    const type = entry.type;
    const actionType = entry.action_type;
    
    if (actionType === 'scanning' || type === 'thought') {
      return {
        icon: <Search className="w-3.5 h-3.5" />,
        color: 'text-violet-400',
        bgColor: 'bg-violet-500/10',
        borderColor: 'border-violet-500/20',
        label: 'SCAN'
      };
    }
    if (actionType === 'stop_warning' || type === 'alert') {
      return {
        icon: <AlertTriangle className="w-3.5 h-3.5" />,
        color: 'text-amber-400',
        bgColor: 'bg-amber-500/10',
        borderColor: 'border-amber-500/20',
        label: 'ALERT'
      };
    }
    if (actionType === 'setup_found' || type === 'setup') {
      return {
        icon: <Target className="w-3.5 h-3.5" />,
        color: 'text-emerald-400',
        bgColor: 'bg-emerald-500/10',
        borderColor: 'border-emerald-500/20',
        label: 'SETUP'
      };
    }
    if (actionType === 'monitoring' || type === 'monitor') {
      return {
        icon: <Eye className="w-3.5 h-3.5" />,
        color: 'text-cyan-400',
        bgColor: 'bg-cyan-500/10',
        borderColor: 'border-cyan-500/20',
        label: 'WATCH'
      };
    }
    if (actionType === 'risk_update' || type === 'risk') {
      return {
        icon: <Gauge className="w-3.5 h-3.5" />,
        color: 'text-rose-400',
        bgColor: 'bg-rose-500/10',
        borderColor: 'border-rose-500/20',
        label: 'RISK'
      };
    }
    if (type === 'filter') {
      return {
        icon: <Filter className="w-3.5 h-3.5" />,
        color: 'text-pink-400',
        bgColor: 'bg-pink-500/10',
        borderColor: 'border-pink-500/20',
        label: 'FILTER'
      };
    }
    if (actionType === 'trade_executed' || type === 'trade') {
      return {
        icon: <Zap className="w-3.5 h-3.5" />,
        color: 'text-yellow-400',
        bgColor: 'bg-yellow-500/10',
        borderColor: 'border-yellow-500/20',
        label: 'TRADE'
      };
    }
    
    // Default - system/info
    return {
      icon: <Radio className="w-3.5 h-3.5" />,
      color: 'text-zinc-400',
      bgColor: 'bg-zinc-500/10',
      borderColor: 'border-zinc-500/20',
      label: 'SYS'
    };
  };
  
  const config = getEntryConfig();
  const hasReasoning = entry.reasoning || entry.metadata?.reasoning || entry.metadata?.details;
  const reasoning = entry.reasoning || entry.metadata?.reasoning || entry.metadata?.details;
  
  // Generate contextual reasoning if none provided
  const getContextualReasoning = () => {
    if (reasoning) return reasoning;
    
    // Generate reasoning based on entry type and content
    const type = entry.type;
    const actionType = entry.action_type;
    const content = entry.content || '';
    
    if (actionType === 'scanning' || type === 'thought') {
      if (content.includes('potential setups')) {
        return 'Analyzing price action, volume patterns, and technical indicators to identify high-probability trade opportunities.';
      }
      return 'Scanning market data for patterns matching our trading criteria.';
    }
    if (actionType === 'stop_warning' || type === 'alert') {
      return 'Risk threshold triggered. Evaluating position safety and potential adjustments.';
    }
    if (actionType === 'setup_found' || type === 'setup') {
      return 'Pattern matches historical winning setups. Confluence of multiple technical factors detected.';
    }
    if (actionType === 'monitoring' || type === 'monitor') {
      return 'Tracking price relative to key levels. Watching for entry/exit signals.';
    }
    if (actionType === 'risk_update' || type === 'risk') {
      return 'Adjusting risk parameters based on current market volatility and portfolio exposure.';
    }
    return null;
  };
  
  const contextualReasoning = getContextualReasoning();
  const hasAnyReasoning = hasReasoning || contextualReasoning;
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.2) }}
      className={`group border-b border-white/5 py-2.5 px-2 hover:${config.bgColor} transition-colors cursor-pointer`}
      onClick={() => hasAnyReasoning && setExpanded(!expanded)}
      data-testid={`soc-entry-${index}`}
    >
      <div className="flex items-start gap-2">
        {/* Timestamp */}
        <span className="text-[10px] font-mono text-zinc-600 w-[58px] flex-shrink-0 pt-0.5">
          {formatTerminalTime(entry.timestamp)}
        </span>
        
        {/* Icon & Label */}
        <div className={`flex items-center gap-1.5 w-[52px] flex-shrink-0 ${config.color}`}>
          {config.icon}
          <span className="text-[9px] font-bold tracking-wider">{config.label}</span>
        </div>
        
        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1">
              <p className={`text-xs leading-relaxed ${config.color === 'text-zinc-400' ? 'text-zinc-300' : config.color}`}>
                {/* Symbol badge if present */}
                {entry.symbol && (
                  <span className="inline-flex items-center mr-1.5 px-1.5 py-0.5 rounded bg-white/10 text-[10px] font-bold text-white">
                    {entry.symbol}
                  </span>
                )}
                {entry.content}
              </p>
              
              {/* Always show brief reasoning preview (not expanded) */}
              {contextualReasoning && !expanded && (
                <p className="text-[10px] text-zinc-500 mt-1 line-clamp-1 italic">
                  {contextualReasoning.slice(0, 80)}{contextualReasoning.length > 80 ? '...' : ''}
                </p>
              )}
            </div>
            
            {/* Expand indicator if has reasoning */}
            {hasAnyReasoning && (
              <motion.div
                animate={{ rotate: expanded ? 180 : 0 }}
                className="text-zinc-600 flex-shrink-0"
              >
                <ChevronDown className="w-3 h-3" />
              </motion.div>
            )}
          </div>
          
          {/* Confidence indicator if present */}
          {entry.confidence && (
            <div className="flex items-center gap-1 mt-1.5">
              <div className="h-1 w-16 bg-zinc-800 rounded-full overflow-hidden">
                <div 
                  className={`h-full ${config.bgColor.replace('/10', '/60')}`}
                  style={{ width: `${entry.confidence}%` }}
                />
              </div>
              <span className="text-[9px] text-zinc-500">{entry.confidence}%</span>
            </div>
          )}
          
          {/* Expanded full reasoning section */}
          <AnimatePresence>
            {expanded && hasAnyReasoning && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-2 pt-2 border-t border-white/5"
              >
                <div className="flex items-start gap-1.5">
                  <Brain className="w-3 h-3 text-violet-400 mt-0.5 flex-shrink-0" />
                  <p className="text-[11px] text-zinc-400 leading-relaxed">
                    {typeof (reasoning || contextualReasoning) === 'string' 
                      ? (reasoning || contextualReasoning) 
                      : JSON.stringify(reasoning || contextualReasoning, null, 2)}
                  </p>
                </div>
                
                {/* Additional metadata if present */}
                {entry.metadata?.score && (
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-[9px] text-zinc-500">Score:</span>
                    <span className="text-[10px] font-bold text-cyan-400">{entry.metadata.score}</span>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}, (prevProps, nextProps) => {
  return prevProps.entry.id === nextProps.entry.id && 
         prevProps.entry.content === nextProps.entry.content;
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
  
  return (
    <div className={`flex flex-col h-full bg-[#050505] ${className}`} data-testid="soc-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-white/10 bg-black/40">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-mono text-emerald-400 uppercase tracking-wider font-bold">
            SentCom S.O.C.
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-zinc-500 font-mono">Stream of Consciousness</span>
          <button
            onClick={refresh}
            className="p-1 hover:bg-white/10 rounded transition-colors"
            title="Refresh"
            data-testid="soc-refresh-btn"
          >
            <RefreshCw className="w-3 h-3 text-zinc-500 hover:text-zinc-300" />
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
              <Activity className="w-6 h-6 text-zinc-600 mx-auto mb-2 animate-pulse" />
              <p className="text-xs text-zinc-500">Initializing...</p>
            </div>
          </div>
        ) : thoughts.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Brain className="w-6 h-6 text-zinc-600 mx-auto mb-2" />
              <p className="text-xs text-zinc-500">Waiting for activity...</p>
              <p className="text-[10px] text-zinc-600 mt-1">Bot thoughts will appear here</p>
            </div>
          </div>
        ) : (
          <div className="py-1">
            {thoughts.map((thought, i) => (
              <SOCEntry key={thought.id || `thought-${i}`} entry={thought} index={i} />
            ))}
          </div>
        )}
      </div>
      
      {/* Footer status bar */}
      <div className="px-3 py-1.5 border-t border-white/10 bg-black/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-zinc-600">{thoughts.length} entries</span>
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true);
                if (scrollRef.current) {
                  scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                }
              }}
              className="text-[9px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
            >
              <ChevronDown className="w-3 h-3" />
              Resume auto-scroll
            </button>
          )}
        </div>
        <span className="text-[9px] text-zinc-600 font-mono">
          {autoScroll ? 'LIVE' : 'PAUSED'}
        </span>
      </div>
    </div>
  );
};

export default StreamOfConsciousness;
