/**
 * StreamOfConsciousness.jsx - SentCom S.O.C. Panel
 * 
 * Rich terminal-style panel with Space Grotesk font, gradient accent bars,
 * glassmorphism effects, and prominent hover glow.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import api, { safeGet, safePost } from '../utils/api';
import { useWsData } from '../contexts/WebSocketDataContext';
import { 
  Search, TrendingUp, TrendingDown, AlertTriangle, Activity, 
  Target, Eye, Zap, Brain, RefreshCw, Filter, CheckCircle,
  XCircle, Clock, Gauge, Radio, ChevronDown, ChevronUp,
  DollarSign, ArrowUpRight, ArrowDownRight, Shield, Crosshair,
  BarChart2, PieChart, Percent, Hash, AlertCircle, Play, 
  StopCircle, ShoppingCart, Ban, ThumbsUp, ThumbsDown
} from 'lucide-react';

// Format timestamp
const formatTime = (timestamp) => {
  if (!timestamp) return '--:--';
  const time = new Date(timestamp);
  return time.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit',
    hour12: false 
  });
};

// Hook for fetching S.O.C. stream data — uses WebSocket with initial fetch fallback
export const useSOCStream = () => {
  const [thoughts, setThoughts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const lastDataRef = useRef('');

  // Import WS data
  const wsData = useWsData();

  const fetchThoughts = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/stream?limit=30');
      
      if (data?.success && data.messages) {
        const socMessages = data.messages.filter(m => 
          m.type !== 'chat' && 
          m.action_type !== 'chat_response' && 
          m.action_type !== 'user_message'
        );
        
        const newDataStr = JSON.stringify(socMessages.map(m => m.id || m.timestamp));
        if (newDataStr !== lastDataRef.current) {
          lastDataRef.current = newDataStr;
          setThoughts(socMessages);
        }
        
        setIsConnected(true);
        setLastUpdate(new Date());
      }
    } catch (err) {
      console.error('Error fetching S.O.C. stream:', err);
      setIsConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch + periodic refresh (30s fallback since WS doesn't carry stream data)
  useEffect(() => {
    fetchThoughts();
    const interval = setInterval(fetchThoughts, 30000);
    return () => clearInterval(interval);
  }, [fetchThoughts]);

  // Subscribe to WS updates
  useEffect(() => {
    if (!wsData?.sentcomData?.stream) return;
    const stream = wsData.sentcomData.stream;
    if (!Array.isArray(stream) || stream.length === 0) return; // Don't overwrite HTTP data with empty WS
    const socMessages = stream.filter(m => 
      m.type !== 'chat' && 
      m.action_type !== 'chat_response' && 
      m.action_type !== 'user_message'
    );
    if (socMessages.length === 0) return; // Don't clear existing data
    const newDataStr = JSON.stringify(socMessages.map(m => m.id || m.timestamp));
    if (newDataStr !== lastDataRef.current) {
      lastDataRef.current = newDataStr;
      setThoughts(socMessages);
      setIsConnected(true);
      setLastUpdate(new Date());
      setLoading(false);
    }
  }, [wsData?.sentcomData]);

  return { thoughts, loading, isConnected, lastUpdate, refresh: fetchThoughts };
};

// Get styling config based on entry type
const getEntryStyle = (entry) => {
  const type = entry.type;
  const actionType = entry.action_type;
  
  // Trade executed
  if (actionType === 'trade_executed' || actionType === 'order_filled') {
    const side = entry.metadata?.side || entry.metadata?.action || '';
    const isSell = side.toLowerCase() === 'sell' || side.toLowerCase() === 'short';
    return {
      icon: isSell ? <ArrowDownRight className="w-4 h-4" /> : <ArrowUpRight className="w-4 h-4" />,
      label: 'TRADE',
      gradient: isSell ? 'from-rose-500 to-orange-500' : 'from-emerald-500 to-cyan-500',
      glowColor: isSell ? 'rgba(244,63,94,0.4)' : 'rgba(16,185,129,0.4)',
      textColor: isSell ? 'text-rose-400' : 'text-emerald-400',
      bgColor: isSell ? 'bg-rose-500/20' : 'bg-emerald-500/20',
    };
  }
  
  // Trade decision
  if (actionType === 'trade_decision' || type === 'decision') {
    const decision = entry.metadata?.decision || '';
    const isApproved = decision.toLowerCase().includes('approved') || decision.toLowerCase().includes('take');
    return {
      icon: isApproved ? <ThumbsUp className="w-4 h-4" /> : <ThumbsDown className="w-4 h-4" />,
      label: 'DECISION',
      gradient: isApproved ? 'from-emerald-500 to-teal-500' : 'from-amber-500 to-orange-500',
      glowColor: isApproved ? 'rgba(16,185,129,0.4)' : 'rgba(245,158,11,0.4)',
      textColor: isApproved ? 'text-emerald-400' : 'text-amber-400',
      bgColor: isApproved ? 'bg-emerald-500/20' : 'bg-amber-500/20',
    };
  }
  
  // Setup found — color-code by timeframe (swing/position vs intraday)
  if (actionType === 'setup_found' || type === 'setup' || type === 'alert') {
    const tradeType = (entry.metadata?.trade_type || '').toLowerCase();
    const isSwing = tradeType === 'swing';
    const isPosition = tradeType === 'position';
    
    if (isPosition) {
      return {
        icon: <TrendingUp className="w-4 h-4" />,
        label: 'POSITION',
        gradient: 'from-amber-500 to-orange-500',
        glowColor: 'rgba(245,158,11,0.4)',
        textColor: 'text-amber-400',
        bgColor: 'bg-amber-500/20',
      };
    }
    if (isSwing) {
      return {
        icon: <Target className="w-4 h-4" />,
        label: 'SWING',
        gradient: 'from-purple-500 to-violet-500',
        glowColor: 'rgba(168,85,247,0.4)',
        textColor: 'text-purple-400',
        bgColor: 'bg-purple-500/20',
      };
    }
    return {
      icon: <Target className="w-4 h-4" />,
      label: 'SETUP',
      gradient: 'from-cyan-500 to-blue-500',
      glowColor: 'rgba(34,211,238,0.4)',
      textColor: 'text-cyan-400',
      bgColor: 'bg-cyan-500/20',
    };
  }
  
  // Risk updates
  if (actionType === 'risk_update' || type === 'risk') {
    return {
      icon: <Shield className="w-4 h-4" />,
      label: 'RISK',
      gradient: 'from-rose-500 to-pink-500',
      glowColor: 'rgba(244,63,94,0.4)',
      textColor: 'text-rose-400',
      bgColor: 'bg-rose-500/20',
    };
  }
  
  // Market regime
  if (actionType === 'regime_update' || actionType === 'breadth_update' || type === 'market') {
    const isRiskOn = entry.content?.toLowerCase().includes('risk_on') || entry.content?.toLowerCase().includes('risk on');
    return {
      icon: <BarChart2 className="w-4 h-4" />,
      label: 'MARKET',
      gradient: isRiskOn ? 'from-emerald-500 to-green-500' : 'from-amber-500 to-yellow-500',
      glowColor: isRiskOn ? 'rgba(16,185,129,0.4)' : 'rgba(245,158,11,0.4)',
      textColor: isRiskOn ? 'text-emerald-400' : 'text-amber-400',
      bgColor: isRiskOn ? 'bg-emerald-500/20' : 'bg-amber-500/20',
    };
  }
  
  // Position monitoring
  if (actionType === 'monitoring' || type === 'monitor') {
    return {
      icon: <Eye className="w-4 h-4" />,
      label: 'WATCH',
      gradient: 'from-violet-500 to-purple-500',
      glowColor: 'rgba(139,92,246,0.4)',
      textColor: 'text-violet-400',
      bgColor: 'bg-violet-500/20',
    };
  }
  
  // Price updates
  if (actionType === 'price_update' || type === 'position') {
    const pnl = entry.metadata?.pnl_percent || 0;
    return {
      icon: pnl >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />,
      label: 'POS',
      gradient: pnl >= 0 ? 'from-emerald-500 to-teal-500' : 'from-rose-500 to-red-500',
      glowColor: pnl >= 0 ? 'rgba(16,185,129,0.35)' : 'rgba(244,63,94,0.35)',
      textColor: pnl >= 0 ? 'text-emerald-400' : 'text-rose-400',
      bgColor: pnl >= 0 ? 'bg-emerald-500/20' : 'bg-rose-500/20',
    };
  }
  
  // Entry zone
  if (actionType === 'entry_zone') {
    return {
      icon: <Crosshair className="w-4 h-4" />,
      label: 'ENTRY',
      gradient: 'from-emerald-500 to-cyan-500',
      glowColor: 'rgba(16,185,129,0.4)',
      textColor: 'text-emerald-400',
      bgColor: 'bg-emerald-500/20',
    };
  }
  
  // Stop warnings
  if (actionType === 'stop_warning') {
    return {
      icon: <AlertTriangle className="w-4 h-4" />,
      label: 'STOP',
      gradient: 'from-amber-500 to-red-500',
      glowColor: 'rgba(245,158,11,0.4)',
      textColor: 'text-amber-400',
      bgColor: 'bg-amber-500/20',
    };
  }
  
  // Filter decisions
  if (type === 'filter' || actionType === 'filter') {
    const content = entry.content || '';
    const decision = entry.metadata?.decision || entry.action_type || '';
    const isSkip = content.includes('SKIP') || decision.toLowerCase().includes('skip');
    const isReduce = content.includes('REDUCE') || decision.toLowerCase().includes('reduce');
    const isPassed = decision.toLowerCase().includes('pass') || decision.toLowerCase().includes('approved') || 
                     content.includes(' GO ') || decision.toLowerCase().includes('go');
    
    if (isSkip) {
      return {
        icon: <XCircle className="w-4 h-4" />,
        label: 'FILTER',
        gradient: 'from-rose-500 to-red-500',
        glowColor: 'rgba(244,63,94,0.3)',
        textColor: 'text-rose-400',
        bgColor: 'bg-rose-500/20',
      };
    } else if (isReduce) {
      return {
        icon: <AlertTriangle className="w-4 h-4" />,
        label: 'FILTER',
        gradient: 'from-amber-500 to-orange-500',
        glowColor: 'rgba(245,158,11,0.3)',
        textColor: 'text-amber-400',
        bgColor: 'bg-amber-500/20',
      };
    } else if (isPassed) {
      return {
        icon: <CheckCircle className="w-4 h-4" />,
        label: 'FILTER',
        gradient: 'from-emerald-500 to-green-500',
        glowColor: 'rgba(16,185,129,0.3)',
        textColor: 'text-emerald-400',
        bgColor: 'bg-emerald-500/20',
      };
    }
    return {
      icon: <Filter className="w-4 h-4" />,
      label: 'FILTER',
      gradient: 'from-zinc-500 to-gray-500',
      glowColor: 'rgba(113,113,122,0.3)',
      textColor: 'text-zinc-400',
      bgColor: 'bg-zinc-500/20',
    };
  }
  
  // Scanning
  if (actionType === 'scanning' || type === 'thought') {
    return {
      icon: <Search className="w-4 h-4" />,
      label: 'SCAN',
      gradient: 'from-violet-500 to-indigo-500',
      glowColor: 'rgba(139,92,246,0.3)',
      textColor: 'text-violet-400',
      bgColor: 'bg-violet-500/20',
    };
  }
  
  // Default
  return {
    icon: <Radio className="w-4 h-4" />,
    label: 'SYS',
    gradient: 'from-zinc-500 to-gray-500',
    glowColor: 'rgba(113,113,122,0.3)',
    textColor: 'text-zinc-400',
    bgColor: 'bg-zinc-500/20',
  };
};

// Build data chips based on entry type and metadata
const buildDataChips = (entry) => {
  const chips = [];
  const meta = entry.metadata || {};
  const actionType = entry.action_type;
  
  // Trade type / timeframe
  if (meta.trade_type || meta.timeframe || meta.setup_type) {
    const tradeType = meta.trade_type || meta.setup_type?.replace(/_/g, ' ') || '';
    const timeframe = meta.timeframe || '';
    if (tradeType || timeframe) {
      chips.push({ 
        label: [tradeType, timeframe].filter(Boolean).join(' • '), 
        color: 'text-violet-400', 
        bg: 'bg-violet-500/10 border-violet-500/30' 
      });
    }
  }
  
  // Entry price
  if (meta.entry_price) {
    chips.push({ 
      icon: <DollarSign className="w-3 h-3" />,
      label: `Entry $${parseFloat(meta.entry_price).toFixed(2)}`, 
      color: 'text-cyan-400', 
      bg: 'bg-cyan-500/10 border-cyan-500/30' 
    });
  }
  
  // Exit price
  if (meta.exit_price) {
    chips.push({ 
      icon: <DollarSign className="w-3 h-3" />,
      label: `Exit $${parseFloat(meta.exit_price).toFixed(2)}`, 
      color: 'text-cyan-400', 
      bg: 'bg-cyan-500/10 border-cyan-500/30' 
    });
  }
  
  // Current price (for positions)
  if (meta.current_price && !meta.exit_price) {
    chips.push({ 
      icon: <DollarSign className="w-3 h-3" />,
      label: `$${parseFloat(meta.current_price).toFixed(2)}`, 
      color: 'text-white', 
      bg: 'bg-white/10 border-white/20' 
    });
  }
  
  // Stop price
  if (meta.stop_price) {
    chips.push({ 
      icon: <StopCircle className="w-3 h-3" />,
      label: `Stop $${parseFloat(meta.stop_price).toFixed(2)}`, 
      color: 'text-rose-400', 
      bg: 'bg-rose-500/10 border-rose-500/30' 
    });
  }
  
  // R-multiple (for closed trades)
  if (meta.r_multiple !== undefined && meta.r_multiple !== null) {
    const r = parseFloat(meta.r_multiple);
    const sign = r >= 0 ? '+' : '';
    chips.push({
      icon: <Hash className="w-3 h-3" />,
      label: `${sign}${r.toFixed(1)}R`,
      color: r >= 0 ? 'text-emerald-400' : 'text-rose-400',
      bg: r >= 0 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30'
    });
  }
  
  // P&L
  if (meta.pnl !== undefined && meta.pnl !== null) {
    const pnl = parseFloat(meta.pnl);
    const pnlPct = meta.pnl_percent ? parseFloat(meta.pnl_percent) : null;
    const sign = pnl >= 0 ? '+' : '';
    let label = `${sign}$${Math.abs(pnl).toFixed(0)}`;
    if (pnlPct !== null) {
      label += ` (${sign}${pnlPct.toFixed(1)}%)`;
    }
    chips.push({ 
      icon: pnl >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />,
      label, 
      color: pnl >= 0 ? 'text-emerald-400' : 'text-rose-400', 
      bg: pnl >= 0 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30' 
    });
  } else if (meta.pnl_percent !== undefined) {
    const pnlPct = parseFloat(meta.pnl_percent);
    const sign = pnlPct >= 0 ? '+' : '';
    chips.push({ 
      icon: pnlPct >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />,
      label: `${sign}${pnlPct.toFixed(1)}%`, 
      color: pnlPct >= 0 ? 'text-emerald-400' : 'text-rose-400', 
      bg: pnlPct >= 0 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30' 
    });
  }
  
  // VIX
  if (meta.vix !== undefined) {
    const vixChange = meta.vix_change;
    chips.push({ 
      icon: <Activity className="w-3 h-3" />,
      label: `VIX ${parseFloat(meta.vix).toFixed(1)}${vixChange ? ` (${vixChange > 0 ? '+' : ''}${vixChange.toFixed(1)}%)` : ''}`, 
      color: 'text-amber-400', 
      bg: 'bg-amber-500/10 border-amber-500/30' 
    });
  }
  
  // Risk multiplier
  if (meta.multiplier !== undefined) {
    chips.push({ 
      icon: <Gauge className="w-3 h-3" />,
      label: `${parseFloat(meta.multiplier).toFixed(1)}x Risk`, 
      color: 'text-rose-400', 
      bg: 'bg-rose-500/10 border-rose-500/30' 
    });
  }
  
  // Score
  if (meta.score !== undefined && meta.score > 0) {
    const grade = meta.tqs_grade || '';
    chips.push({ 
      icon: <BarChart2 className="w-3 h-3" />,
      label: `TQS ${parseFloat(meta.score).toFixed(0)}${grade ? ` (${grade})` : ''}`, 
      color: meta.score >= 70 ? 'text-emerald-400' : meta.score >= 40 ? 'text-cyan-400' : 'text-amber-400', 
      bg: meta.score >= 70 ? 'bg-emerald-500/10 border-emerald-500/30' : meta.score >= 40 ? 'bg-cyan-500/10 border-cyan-500/30' : 'bg-amber-500/10 border-amber-500/30'
    });
  }
  
  // Direction
  if (meta.direction) {
    const isLong = meta.direction.toLowerCase() === 'long';
    chips.push({
      icon: isLong ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />,
      label: meta.direction.toUpperCase(),
      color: isLong ? 'text-emerald-400' : 'text-rose-400',
      bg: isLong ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30'
    });
  }
  
  // Risk/Reward
  if (meta.risk_reward && meta.risk_reward > 0) {
    chips.push({
      icon: <Target className="w-3 h-3" />,
      label: `R:R ${parseFloat(meta.risk_reward).toFixed(1)}:1`,
      color: meta.risk_reward >= 2 ? 'text-emerald-400' : 'text-amber-400',
      bg: meta.risk_reward >= 2 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-amber-500/10 border-amber-500/30'
    });
  }
  
  // Win rate
  if (meta.win_rate && meta.win_rate > 0) {
    chips.push({
      icon: <Percent className="w-3 h-3" />,
      label: `${parseFloat(meta.win_rate).toFixed(0)}% Win`,
      color: meta.win_rate >= 50 ? 'text-emerald-400' : 'text-rose-400',
      bg: meta.win_rate >= 50 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/30'
    });
  }
  
  // Tape score
  if (meta.tape_score && meta.tape_score > 0) {
    chips.push({
      icon: <Activity className="w-3 h-3" />,
      label: `Tape ${parseFloat(meta.tape_score).toFixed(0)}`,
      color: meta.tape_score >= 60 ? 'text-emerald-400' : 'text-zinc-400',
      bg: meta.tape_score >= 60 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-zinc-500/10 border-zinc-500/30'
    });
  }
  
  // Regime
  if (meta.regime) {
    const isOn = meta.regime.toLowerCase().includes('on');
    chips.push({ 
      icon: <Shield className="w-3 h-3" />,
      label: meta.regime.replace('_', ' '), 
      color: isOn ? 'text-emerald-400' : 'text-amber-400', 
      bg: isOn ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-amber-500/10 border-amber-500/30' 
    });
  }
  
  // Breadth
  if (meta.breadth !== undefined) {
    chips.push({ 
      icon: <PieChart className="w-3 h-3" />,
      label: `${meta.breadth}% Breadth`, 
      color: 'text-cyan-400', 
      bg: 'bg-cyan-500/10 border-cyan-500/30' 
    });
  }
  
  return chips;
};

// S.O.C. Entry Component - Memoized to prevent re-renders
const SOCEntry = React.memo(({ entry, index, isNew = false }) => {
  const [expanded, setExpanded] = useState(false);
  const style = getEntryStyle(entry);
  const chips = buildDataChips(entry);
  const reasoning = entry.metadata?.reasoning || entry.reasoning;
  
  return (
    <div
      onClick={() => reasoning && setExpanded(!expanded)}
      className="group relative mb-3 cursor-pointer"
      data-testid={`soc-entry-${index}`}
    >
      {/* Glassmorphism Card with Gradient Border */}
      <div 
        className="relative overflow-hidden rounded-xl transition-all duration-300"
        style={{
          background: 'rgba(255,255,255,0.03)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.08)',
          boxShadow: `0 4px 20px rgba(0,0,0,0.3)`,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.boxShadow = `0 8px 40px ${style.glowColor}, 0 4px 20px rgba(0,0,0,0.4)`;
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.15)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.3)';
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
        }}
      >
        {/* Gradient Left Border */}
        <div className={`absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b ${style.gradient}`} />
        
        {/* Content */}
        <div className="pl-4 pr-4 py-3">
          {/* Header Row */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              {/* Icon */}
              <div className={`w-8 h-8 rounded-lg ${style.bgColor} border border-white/10 flex items-center justify-center ${style.textColor}`}>
                {style.icon}
              </div>
              
              {/* Label Badge */}
              <span 
                className={`text-[10px] font-bold tracking-wider px-2 py-1 rounded-md ${style.bgColor} ${style.textColor}`}
                style={{ fontFamily: "'Space Grotesk', sans-serif" }}
              >
                {style.label}
              </span>
              
              {/* Symbol */}
              {entry.symbol && (
                <span 
                  className="text-sm font-bold text-white bg-white/10 px-2 py-0.5 rounded-md"
                  style={{ fontFamily: "'Space Grotesk', sans-serif" }}
                >
                  {entry.symbol}
                </span>
              )}
            </div>
            
            {/* Timestamp + Expand */}
            <div className="flex items-center gap-2">
              <span 
                className="text-[10px] text-zinc-500"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {formatTime(entry.timestamp)}
              </span>
              {reasoning && (
                <motion.div 
                  animate={{ rotate: expanded ? 180 : 0 }}
                  className="text-zinc-500"
                >
                  <ChevronDown className="w-4 h-4" />
                </motion.div>
              )}
            </div>
          </div>
          
          {/* Content Text */}
          <p 
            className="text-[13px] text-zinc-200 leading-relaxed mb-3"
            style={{ fontFamily: "'Space Grotesk', sans-serif" }}
          >
            {entry.content}
          </p>
          
          {/* Data Chips */}
          {chips.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              {chips.map((chip, i) => (
                <div 
                  key={i}
                  className={`flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded-lg border ${chip.color} ${chip.bg}`}
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  {chip.icon}
                  <span>{chip.label}</span>
                </div>
              ))}
            </div>
          )}
          
          {/* Confidence Bar */}
          {entry.confidence && (
            <div className="flex items-center gap-2 mt-3">
              <div className="h-1 flex-1 max-w-[100px] bg-zinc-800 rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${entry.confidence}%` }}
                  transition={{ duration: 0.5 }}
                  className={`h-full bg-gradient-to-r ${style.gradient}`}
                />
              </div>
              <span 
                className="text-[9px] text-zinc-500"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {entry.confidence}%
              </span>
            </div>
          )}
          
          {/* Expanded Reasoning */}
          <AnimatePresence>
            {expanded && reasoning && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-3 pt-3 border-t border-white/10"
              >
                <div className="flex items-start gap-2">
                  <Brain className="w-4 h-4 text-violet-400 mt-0.5 flex-shrink-0" />
                  <p 
                    className="text-xs text-zinc-400 leading-relaxed"
                    style={{ fontFamily: "'Space Grotesk', sans-serif" }}
                  >
                    {reasoning}
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
});

SOCEntry.displayName = 'SOCEntry';

// Main S.O.C. Panel
const StreamOfConsciousness = ({ className = '' }) => {
  const { thoughts, loading, isConnected, lastUpdate, refresh } = useSOCStream();
  const scrollRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const prevThoughtsLengthRef = useRef(thoughts.length);
  
  // Only auto-scroll when NEW entries are added, not on every render
  useEffect(() => {
    if (autoScroll && scrollRef.current && thoughts.length > prevThoughtsLengthRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevThoughtsLengthRef.current = thoughts.length;
  }, [thoughts.length, autoScroll]);
  
  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };
  
  const highPriorityCount = thoughts.filter(t => 
    ['trade_executed', 'trade_decision', 'setup_found', 'entry_zone', 'stop_warning'].includes(t.action_type) ||
    ['setup', 'alert', 'decision', 'trade'].includes(t.type)
  ).length;
  
  // Format last update time
  const lastUpdateStr = lastUpdate ? lastUpdate.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit',
    hour12: false 
  }) : '--:--:--';
  
  return (
    <div 
      className={`flex flex-col h-full ${className}`} 
      style={{ 
        background: 'linear-gradient(180deg, #0a0a0f 0%, #050508 100%)',
        fontFamily: "'Space Grotesk', sans-serif"
      }}
      data-testid="soc-panel"
    >
      {/* Header */}
      <div 
        className="flex items-center justify-between px-4 py-3 border-b border-white/10"
        style={{ background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(10px)' }}
      >
        <div className="flex items-center gap-3">
          {/* Live indicator - subtle pulsing dot when connected */}
          <div className="relative" title={isConnected ? `Live - Last: ${lastUpdateStr}` : 'Connecting...'}>
            <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
            {isConnected && (
              <div className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping opacity-40" />
            )}
          </div>
          <div>
            <span className="text-sm font-bold text-emerald-400 tracking-wide">
              SentCom S.O.C.
            </span>
            <p className="text-[9px] text-zinc-500 tracking-wider">STREAM OF CONSCIOUSNESS</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Connection status indicator */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-black/30" title={`Last update: ${lastUpdateStr}`}>
            <Radio className={`w-3 h-3 ${isConnected ? 'text-emerald-400' : 'text-zinc-600'}`} />
            <span className={`text-[9px] font-mono ${isConnected ? 'text-emerald-400' : 'text-zinc-500'}`}>
              {isConnected ? 'LIVE' : 'SYNC'}
            </span>
          </div>
          
          {highPriorityCount > 0 && (
            <span 
              className="text-[10px] px-2.5 py-1 rounded-full bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 font-semibold"
            >
              {highPriorityCount}
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
      
      {/* Content - No layout shift during updates */}
      <div 
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 custom-scrollbar"
        style={{ minHeight: 0 }} /* Prevents flex child from overflowing */
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
              <Brain className="w-10 h-10 text-zinc-700 mx-auto mb-3" />
              <p className="text-sm text-zinc-500">Waiting for activity...</p>
              <p className="text-[10px] text-zinc-600 mt-1">Trade decisions and alerts will appear here</p>
            </div>
          </div>
        ) : (
          <>
            {thoughts.map((thought, i) => (
              <SOCEntry key={thought.id || `thought-${i}`} entry={thought} index={i} />
            ))}
          </>
        )}
      </div>
      
      {/* Footer */}
      <div 
        className="px-4 py-2 border-t border-white/10 flex items-center justify-between"
        style={{ background: 'rgba(0,0,0,0.5)' }}
      >
        <div className="flex items-center gap-3">
          <span 
            className="text-[10px] text-zinc-600"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {thoughts.length} entries
          </span>
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
          <span 
            className="text-[10px] text-zinc-600"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {autoScroll ? 'LIVE' : 'PAUSED'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default StreamOfConsciousness;
