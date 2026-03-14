/**
 * SentCom Mockups V2 - Enhanced Visual Design
 * 
 * SentCom = Sentient Command - Unified AI Command Center
 * 
 * Improvements:
 * - More visually appealing Option C with glass effects and gradients
 * - Richer modal details (R:R, confidence, chart preview)
 * - More dynamic analytics with sparklines
 * - Simplified/clarified navigation
 * - Quick Actions Option C (Collapsible Drawer)
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Cpu, User, Sparkles, Clock, Zap, Target, 
  AlertCircle, ArrowRight, CheckCircle, Loader, Shield, 
  Maximize2, Minimize2, MessageSquare, Terminal, Activity,
  ChevronUp, ChevronDown, Command, Keyboard, X, TrendingUp,
  BarChart3, Search, Newspaper, Play, Pause, Eye, Crosshair,
  DollarSign, Percent, Award, Calendar, Filter, LineChart,
  PieChart, ArrowUpRight, ArrowDownRight, Users, Volume2,
  Mic, Layers, Layout, Monitor, Smartphone, Settings,
  RefreshCw, BookOpen, ExternalLink, ChevronLeft, ChevronRight,
  Hash, Bell, GitBranch, Circle, Flame, Star, Trophy,
  Gauge, Radio, Wifi, Signal, Moon, Sun, Compass
} from 'lucide-react';

// ============================================================================
// ENHANCED SHARED COMPONENTS
// ============================================================================

// Mini sparkline component
const Sparkline = ({ data, color = 'cyan', height = 24 }) => {
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

// Generate sparkline data based on P&L direction
const generateSparklineData = (pnl, pnlPercent = 0) => {
  const isPositive = pnl >= 0;
  const magnitude = Math.min(Math.abs(pnlPercent || 0), 10);
  const baseValue = 50;
  const points = 8;
  const data = [];
  
  for (let i = 0; i < points; i++) {
    const progress = i / (points - 1);
    const trend = isPositive 
      ? baseValue + (magnitude * progress * 3)
      : baseValue - (magnitude * progress * 3);
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

const MockOrderPipelineEnhanced = () => (
  <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-black/40 border border-white/5">
    <div className="flex items-center gap-2">
      <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
        <Clock className="w-4 h-4 text-amber-400" />
      </div>
      <div>
        <p className="text-lg font-bold text-amber-400">2</p>
        <p className="text-[9px] text-zinc-500 uppercase">Pending</p>
      </div>
    </div>
    
    <ArrowRight className="w-4 h-4 text-zinc-600" />
    
    <div className="flex items-center gap-2">
      <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center animate-pulse">
        <Zap className="w-4 h-4 text-cyan-400" />
      </div>
      <div>
        <p className="text-lg font-bold text-cyan-400">1</p>
        <p className="text-[9px] text-zinc-500 uppercase">Executing</p>
      </div>
    </div>
    
    <ArrowRight className="w-4 h-4 text-zinc-600" />
    
    <div className="flex items-center gap-2">
      <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
        <CheckCircle className="w-4 h-4 text-emerald-400" />
      </div>
      <div>
        <p className="text-lg font-bold text-emerald-400">5</p>
        <p className="text-[9px] text-zinc-500 uppercase">Filled</p>
      </div>
    </div>
  </div>
);

// Enhanced message component with better styling
const EnhancedMessage = ({ type, content, time, confidence, symbol }) => {
  if (type === 'user') {
    return (
      <motion.div 
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        className="flex justify-end mb-4"
      >
        <div className="flex items-end gap-2 max-w-[75%]">
          <div className="relative">
            <div className="absolute inset-0 bg-cyan-500/20 blur-xl rounded-2xl" />
            <div className="relative bg-gradient-to-br from-cyan-500/20 to-cyan-600/10 border border-cyan-500/30 text-cyan-50 rounded-2xl rounded-br-sm px-4 py-3">
              <p className="text-sm">{content}</p>
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-400 to-cyan-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-cyan-500/30">
            <User className="w-4 h-4 text-white" />
          </div>
        </div>
      </motion.div>
    );
  }
  
  if (type === 'system') {
    const isWarning = content.includes('stop') || content.includes('Alert');
    const isFilter = content.includes('Filter') || content.includes('passing');
    const isSuccess = content.includes('detected') || content.includes('momentum');
    
    let borderColor = 'border-l-cyan-500';
    let bgColor = 'from-cyan-500/10';
    let icon = <Activity className="w-4 h-4 text-cyan-400" />;
    let label = 'SYSTEM';
    
    if (isFilter) {
      borderColor = 'border-l-amber-500';
      bgColor = 'from-amber-500/10';
      icon = <Filter className="w-4 h-4 text-amber-400" />;
      label = 'SMART FILTER';
    } else if (isWarning) {
      borderColor = 'border-l-rose-500';
      bgColor = 'from-rose-500/10';
      icon = <AlertCircle className="w-4 h-4 text-rose-400" />;
      label = 'ALERT';
    } else if (isSuccess) {
      borderColor = 'border-l-emerald-500';
      bgColor = 'from-emerald-500/10';
      icon = <TrendingUp className="w-4 h-4 text-emerald-400" />;
      label = 'SCANNER';
    }
    
    return (
      <motion.div 
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-3"
      >
        <div className={`border-l-2 ${borderColor} bg-gradient-to-r ${bgColor} to-transparent rounded-r-xl p-3`}>
          <div className="flex items-center gap-2 mb-1.5">
            <div className="w-5 h-5 rounded-md bg-black/30 flex items-center justify-center">
              {icon}
            </div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">{label}</span>
            <span className="text-[10px] text-zinc-600">{time}</span>
          </div>
          <p className="text-xs text-zinc-200 leading-relaxed pl-7">{content}</p>
        </div>
      </motion.div>
    );
  }
  
  // Assistant message
  return (
    <motion.div 
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex justify-start mb-4"
    >
      <div className="flex items-end gap-2 max-w-[80%]">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-violet-500/30">
          <Brain className="w-4 h-4 text-white" />
        </div>
        <div className="relative">
          <div className="absolute inset-0 bg-violet-500/10 blur-xl rounded-2xl" />
          <div className="relative bg-gradient-to-br from-zinc-800/90 to-zinc-900/90 border border-white/10 text-zinc-100 rounded-2xl rounded-bl-sm px-4 py-3">
            <p className="text-sm leading-relaxed">{content}</p>
            {confidence && (
              <div className="flex items-center gap-2 mt-2 pt-2 border-t border-white/5">
                <Gauge className="w-3 h-3 text-violet-400" />
                <span className="text-[10px] text-violet-400">Confidence: {confidence}%</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const mockMessages = [
  { type: 'assistant', content: "SentCom online. We're monitoring 3 active positions and scanning for setups. Market regime is RISK_ON - conditions favor momentum plays.", time: '09:31', confidence: 85 },
  { type: 'system', content: "We detected momentum building in NVDA. Volume 2.3x average with price holding above VWAP.", time: '09:32' },
  { type: 'user', content: "What do we think about AAPL today?", time: '09:33' },
  { type: 'assistant', content: "We're seeing AAPL consolidate near $185 resistance. Our pullback win rate is 67% - if it dips to $182 support with volume, that's our zone. Risk/reward would be 2.4:1.", time: '09:33', confidence: 78 },
  { type: 'system', content: "Alert: Our TSLA stop is within 1.5% of current price. Consider trailing to lock in gains.", time: '09:35' },
  { type: 'system', content: "Filter: We're passing on AMD breakout - our historical win rate is only 34% on this setup type.", time: '09:36' },
];

const mockPositions = [
  { symbol: 'NVDA', pnl: '+$847', pnlPct: '+2.4%', status: 'running', entry: '$142.50', rr: '2.1R', data: [40, 45, 42, 48, 55, 52, 60, 58, 65, 68] },
  { symbol: 'TSLA', pnl: '-$124', pnlPct: '-0.8%', status: 'watching', entry: '$245.00', rr: '-0.3R', data: [50, 48, 52, 45, 42, 44, 40, 38, 42, 40] },
  { symbol: 'META', pnl: '+$312', pnlPct: '+1.1%', status: 'trailing', entry: '$485.20', rr: '1.2R', data: [30, 35, 38, 42, 40, 45, 50, 48, 52, 55] },
];

const mockSetups = [
  { symbol: 'AAPL', setup: 'Pullback', score: 82, distance: '0.8%', status: 'near', ourWinRate: 67 },
  { symbol: 'GOOGL', setup: 'Breakout', score: 71, distance: '2.1%', status: 'watching', ourWinRate: 52 },
  { symbol: 'AMZN', setup: 'Mean Rev', score: 68, distance: '1.5%', status: 'watching', ourWinRate: 61 },
];

// ============================================================================
// OPTION C V2: ENHANCED DEDICATED PAGE
// ============================================================================

const DedicatedPageV2 = () => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedTicker, setSelectedTicker] = useState(null);
  
  return (
    <div className="bg-zinc-950 min-h-[750px] rounded-2xl border border-white/10 overflow-hidden relative">
      {/* Ticker Detail Modal */}
      <AnimatePresence>
        {selectedTicker && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-8"
            onClick={() => setSelectedTicker(null)}
          >
            <motion.div 
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-3xl"
              onClick={e => e.stopPropagation()}
            >
              <GlassCard glow className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center">
                      <span className="text-xl font-bold text-white">{selectedTicker.symbol}</span>
                    </div>
                    <div>
                      <h2 className="text-2xl font-bold text-white">Our {selectedTicker.symbol} Position</h2>
                      <p className="text-sm text-zinc-400">Detailed view • Click sparkline to open</p>
                    </div>
                  </div>
                  <button 
                    onClick={() => setSelectedTicker(null)}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
                
                {/* Mock Chart Area */}
                <div className="h-48 rounded-xl bg-black/40 border border-white/10 mb-6 flex items-center justify-center">
                  <div className="text-center">
                    <LineChart className="w-12 h-12 text-cyan-400/50 mx-auto mb-2" />
                    <p className="text-sm text-zinc-500">Full Interactive Chart</p>
                    <p className="text-xs text-zinc-600">Price action, indicators, entries/exits</p>
                  </div>
                </div>
                
                {/* Position Stats */}
                <div className="grid grid-cols-4 gap-4 mb-6">
                  <div className="p-3 rounded-xl bg-black/40 text-center">
                    <p className="text-[10px] text-zinc-500 uppercase">Entry</p>
                    <p className="text-lg font-bold text-white">{selectedTicker.entry}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-black/40 text-center">
                    <p className="text-[10px] text-zinc-500 uppercase">Current P&L</p>
                    <p className={`text-lg font-bold ${selectedTicker.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {selectedTicker.pnl}
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-black/40 text-center">
                    <p className="text-[10px] text-zinc-500 uppercase">R-Multiple</p>
                    <p className="text-lg font-bold text-cyan-400">{selectedTicker.rr}</p>
                  </div>
                  <div className="p-3 rounded-xl bg-black/40 text-center">
                    <p className="text-[10px] text-zinc-500 uppercase">Status</p>
                    <p className="text-lg font-bold text-violet-400 capitalize">{selectedTicker.status}</p>
                  </div>
                </div>
                
                {/* Our Take Section */}
                <div className="p-4 rounded-xl bg-gradient-to-r from-violet-500/10 to-transparent border border-violet-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <Brain className="w-5 h-5 text-violet-400" />
                    <span className="font-bold text-white">Our Take</span>
                  </div>
                  <p className="text-sm text-zinc-300">
                    "We're {selectedTicker.pnl.startsWith('+') ? 'running nicely on' : 'underwater on'} {selectedTicker.symbol}. 
                    {selectedTicker.status === 'trailing' ? " We've moved our stop to breakeven and are trailing for more." : 
                     selectedTicker.status === 'watching' ? " We're watching for a bounce or considering cutting." :
                     " Momentum is with us - letting it run."}
                  </p>
                </div>
              </GlassCard>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      {/* Ambient Background Effects */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-0 right-1/4 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-1/4 w-96 h-96 bg-violet-500/10 rounded-full blur-3xl" />
      </div>
      
      {/* Top Bar */}
      <div className="relative flex items-center justify-between px-6 py-4 border-b border-white/10 bg-black/40 backdrop-blur-xl">
        <div className="flex items-center gap-6">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 to-violet-500 blur-lg opacity-50" />
              <div className="relative w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/20">
                <Brain className="w-6 h-6 text-cyan-400" />
              </div>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white tracking-tight">SENTCOM</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <PulsingDot color="emerald" />
                <span className="text-[11px] text-emerald-400 font-medium">CONNECTED</span>
                <span className="text-zinc-600">•</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">RISK_ON</span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <MockOrderPipelineEnhanced />
          
          <button className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors border border-white/5">
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </div>
      
      {/* Main 3-Column Layout */}
      <div className="relative grid grid-cols-12 gap-4 p-4 h-[680px]">
        {/* Left Column - Positions & Setups */}
        <div className="col-span-3 space-y-4 overflow-y-auto pr-2">
          {/* Our Positions */}
          <GlassCard gradient glow className="p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 flex items-center justify-center">
                  <Target className="w-4 h-4 text-emerald-400" />
                </div>
                <h3 className="text-sm font-bold text-white">Our Positions</h3>
              </div>
              <span className="text-lg font-bold text-emerald-400">+$1,035</span>
            </div>
            
            <div className="space-y-3">
              {mockPositions.map(pos => (
                <div 
                  key={pos.symbol} 
                  className="relative p-3 rounded-xl bg-black/40 border border-white/5 hover:border-white/10 cursor-pointer transition-all group"
                  onClick={() => setSelectedTicker(pos)}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{pos.symbol}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                        pos.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' :
                        pos.status === 'trailing' ? 'bg-cyan-500/20 text-cyan-400' :
                        'bg-amber-500/20 text-amber-400'
                      }`}>
                        {pos.status}
                      </span>
                    </div>
                    <div className="text-right">
                      <p className={`font-bold ${pos.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {pos.pnl}
                      </p>
                      <p className="text-[10px] text-zinc-500">{pos.rr}</p>
                    </div>
                  </div>
                  
                  {/* Mini Chart - Clickable */}
                  <div className="h-8 mt-2 overflow-hidden rounded opacity-60 group-hover:opacity-100 transition-opacity relative">
                    <Sparkline data={pos.data} color={pos.pnl.startsWith('+') ? 'emerald' : 'rose'} />
                    {/* Hover hint */}
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 rounded">
                      <span className="text-[9px] text-cyan-400 flex items-center gap-1">
                        <ExternalLink className="w-3 h-3" /> Click for details
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
          
          {/* Setups We're Watching */}
          <GlassCard className="p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/20 to-violet-600/10 flex items-center justify-center">
                  <Eye className="w-4 h-4 text-violet-400" />
                </div>
                <h3 className="text-sm font-bold text-white">Setups We're Watching</h3>
              </div>
            </div>
            
            <div className="space-y-2">
              {mockSetups.map(setup => (
                <div 
                  key={setup.symbol}
                  className="p-3 rounded-xl bg-black/30 hover:bg-black/50 cursor-pointer transition-all border border-transparent hover:border-white/5"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{setup.symbol}</span>
                      <span className="text-[10px] px-1.5 py-0.5 bg-violet-500/20 text-violet-400 rounded-full">
                        {setup.setup}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Star className="w-3 h-3 text-amber-400" />
                      <span className="text-xs font-bold text-white">{setup.score}</span>
                    </div>
                  </div>
                  
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-zinc-500">{setup.distance} to entry</span>
                    <span className={`flex items-center gap-1 ${setup.ourWinRate >= 60 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                      {setup.ourWinRate >= 60 && <Flame className="w-3 h-3" />}
                      Our WR: {setup.ourWinRate}%
                    </span>
                  </div>
                  
                  {setup.status === 'near' && (
                    <div className="mt-2 flex items-center gap-1 text-amber-400">
                      <Zap className="w-3 h-3" />
                      <span className="text-[10px] font-medium">Near Entry Zone</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </GlassCard>
          
          {/* Quick Stats */}
          <GlassCard className="p-4">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Today's Performance</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="text-center p-3 rounded-xl bg-black/30">
                <p className="text-2xl font-bold text-emerald-400">67%</p>
                <p className="text-[10px] text-zinc-500">Win Rate</p>
              </div>
              <div className="text-center p-3 rounded-xl bg-black/30">
                <p className="text-2xl font-bold text-cyan-400">1.8R</p>
                <p className="text-[10px] text-zinc-500">Avg Win</p>
              </div>
            </div>
            
            {/* Win streak indicator */}
            <div className="mt-3 flex items-center justify-center gap-1">
              {[1,2,3].map(i => (
                <div key={i} className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center">
                  <CheckCircle className="w-3 h-3 text-emerald-400" />
                </div>
              ))}
              <span className="text-[10px] text-zinc-500 ml-2">3 win streak</span>
            </div>
          </GlassCard>
        </div>
        
        {/* Center Column - Unified Stream */}
        <div className="col-span-6 flex flex-col">
          <GlassCard glow className="flex-1 flex flex-col overflow-hidden">
            {/* Stream Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <Activity className="w-4 h-4 text-cyan-400" />
                <span className="text-sm font-medium text-white">Live Team Stream</span>
              </div>
              <div className="flex items-center gap-2">
                <button className="text-[10px] px-2 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors">
                  <Filter className="w-3 h-3" />
                </button>
              </div>
            </div>
            
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4">
              {mockMessages.map((msg, i) => (
                <EnhancedMessage key={i} {...msg} />
              ))}
            </div>
            
            {/* Quick Actions Drawer */}
            <AnimatePresence>
              {drawerOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-t border-white/5 overflow-hidden"
                >
                  <div className="p-3 bg-black/40">
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: 'Brief Me', desc: 'Market summary', icon: Newspaper, color: 'cyan' },
                        { label: 'Scan', desc: 'Find setups', icon: Search, color: 'violet' },
                        { label: 'Performance', desc: 'Our stats', icon: BarChart3, color: 'emerald' },
                        { label: 'Trail Stops', desc: 'Adjust stops', icon: TrendingUp, color: 'amber' },
                        { label: 'Close Position', desc: 'Exit trade', icon: X, color: 'rose' },
                        { label: 'Fix Stops', desc: 'Auto-adjust', icon: Shield, color: 'cyan' },
                      ].map(item => (
                        <button 
                          key={item.label}
                          className="flex items-center gap-2 p-2.5 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-left group"
                        >
                          <div className={`w-9 h-9 rounded-lg bg-${item.color}-500/20 flex items-center justify-center`}>
                            <item.icon className={`w-4 h-4 text-${item.color}-400`} />
                          </div>
                          <div>
                            <p className="text-sm font-medium text-white">{item.label}</p>
                            <p className="text-[10px] text-zinc-500">{item.desc}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            
            {/* Input Area */}
            <div className="p-4 bg-black/40 border-t border-white/5">
              <div className="relative">
                <input
                  type="text"
                  placeholder="Talk to the team... Ask questions, give commands, or discuss strategy"
                  className="w-full bg-white/5 border border-white/10 rounded-xl pl-4 pr-28 py-4 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50 focus:bg-white/10 transition-all"
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <button 
                    onClick={() => setDrawerOpen(!drawerOpen)}
                    className={`p-2.5 rounded-xl transition-all ${
                      drawerOpen 
                        ? 'bg-cyan-500/20 text-cyan-400' 
                        : 'bg-white/5 text-zinc-400 hover:text-white hover:bg-white/10'
                    }`}
                  >
                    <Command className="w-4 h-4" />
                  </button>
                  <button className="p-2.5 rounded-xl bg-white/5 text-zinc-400 hover:text-white hover:bg-white/10 transition-all">
                    <Mic className="w-4 h-4" />
                  </button>
                  <button className="p-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-cyan-600 text-white shadow-lg shadow-cyan-500/30 hover:shadow-cyan-500/50 transition-all">
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </GlassCard>
        </div>
        
        {/* Right Column - Intelligence */}
        <div className="col-span-3 space-y-4 overflow-y-auto pl-2">
          {/* Market Context */}
          <GlassCard className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/10 flex items-center justify-center">
                <Compass className="w-4 h-4 text-cyan-400" />
              </div>
              <h3 className="text-sm font-bold text-white">Market Context</h3>
            </div>
            
            <div className="space-y-3">
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">Regime</span>
                <span className="px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded-lg text-xs font-bold">RISK_ON</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">SPY Trend</span>
                <span className="text-xs text-emerald-400 flex items-center gap-1 font-medium">
                  <ArrowUpRight className="w-3 h-3" /> Bullish
                </span>
              </div>
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">VIX</span>
                <span className="text-xs text-zinc-200 font-mono">14.2</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">Sector Flow</span>
                <span className="text-xs text-cyan-400">Tech +1.2%</span>
              </div>
            </div>
          </GlassCard>
          
          {/* Recent Alerts */}
          <GlassCard className="p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/20 to-amber-600/10 flex items-center justify-center">
                  <Bell className="w-4 h-4 text-amber-400" />
                </div>
                <h3 className="text-sm font-bold text-white">Recent Alerts</h3>
              </div>
              <span className="text-xs text-zinc-500">3 new</span>
            </div>
            
            <div className="space-y-2">
              <div className="p-2.5 rounded-xl bg-gradient-to-r from-amber-500/10 to-transparent border-l-2 border-amber-500">
                <div className="flex items-center gap-2">
                  <AlertCircle className="w-3 h-3 text-amber-400" />
                  <p className="text-[11px] text-amber-300 font-medium">TSLA stop within 1.5%</p>
                </div>
                <p className="text-[10px] text-zinc-500 mt-0.5 ml-5">2 min ago</p>
              </div>
              <div className="p-2.5 rounded-xl bg-gradient-to-r from-emerald-500/10 to-transparent border-l-2 border-emerald-500">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-3 h-3 text-emerald-400" />
                  <p className="text-[11px] text-emerald-300 font-medium">NVDA momentum confirmed</p>
                </div>
                <p className="text-[10px] text-zinc-500 mt-0.5 ml-5">5 min ago</p>
              </div>
              <div className="p-2.5 rounded-xl bg-gradient-to-r from-violet-500/10 to-transparent border-l-2 border-violet-500">
                <div className="flex items-center gap-2">
                  <Crosshair className="w-3 h-3 text-violet-400" />
                  <p className="text-[11px] text-violet-300 font-medium">AAPL approaching entry</p>
                </div>
                <p className="text-[10px] text-zinc-500 mt-0.5 ml-5">8 min ago</p>
              </div>
            </div>
          </GlassCard>
          
          {/* Smart Filter Status */}
          <GlassCard gradient className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/20 to-violet-600/10 flex items-center justify-center">
                  <Shield className="w-4 h-4 text-violet-400" />
                </div>
                <h3 className="text-sm font-bold text-white">Smart Filter</h3>
              </div>
              <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded-full text-[10px] font-bold">ACTIVE</span>
            </div>
            
            <div className="space-y-2">
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">Trades Filtered Today</span>
                <span className="text-sm font-bold text-amber-400">3</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                <span className="text-xs text-zinc-400">Est. Losses Avoided</span>
                <span className="text-sm font-bold text-emerald-400">~$450</span>
              </div>
            </div>
            
            <div className="mt-3 p-2 rounded-lg bg-violet-500/10 border border-violet-500/20">
              <p className="text-[10px] text-violet-300">
                <strong>Latest:</strong> Passed on AMD breakout (34% win rate)
              </p>
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// ENHANCED "OUR TAKE" MODAL
// ============================================================================

const EnhancedOurTakeModal = () => (
  <div className="grid grid-cols-2 gap-6">
    {/* Old Version */}
    <div className="opacity-50">
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3 flex items-center gap-2">
        <X className="w-3 h-3 text-rose-400" /> Old: Basic Info
      </p>
      <div className="bg-zinc-900 border border-white/10 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Cpu className="w-5 h-5 text-zinc-400" />
          <h3 className="font-bold text-white">Bot's Take</h3>
        </div>
        <p className="text-sm text-zinc-400 mb-3">
          "I see AAPL forming a pullback. I recommend entry at $182.50."
        </p>
        <div className="text-xs text-zinc-500 space-y-1">
          <p>• Entry: $182.50</p>
          <p>• Stop: $180.00</p>
          <p>• Target: $188.00</p>
        </div>
      </div>
    </div>
    
    {/* New Enhanced Version */}
    <div>
      <p className="text-xs text-emerald-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <CheckCircle className="w-3 h-3" /> New: Rich Details
      </p>
      <GlassCard glow className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/30 to-purple-600/30 flex items-center justify-center">
              <Brain className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h3 className="font-bold text-white">Our Take on AAPL</h3>
              <span className="text-[10px] text-violet-400">Pullback Setup</span>
            </div>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-emerald-500/20">
            <Gauge className="w-3 h-3 text-emerald-400" />
            <span className="text-xs font-bold text-emerald-400">78%</span>
          </div>
        </div>
        
        <p className="text-sm text-zinc-200 mb-4 leading-relaxed">
          "We see AAPL forming a pullback to the 20 EMA. This is <strong className="text-cyan-400">our kind of setup</strong> - we're 67% on pullbacks. The risk/reward is favorable at 2.4:1."
        </p>
        
        {/* Trade Parameters */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          <div className="p-2 rounded-lg bg-black/40 text-center">
            <p className="text-[10px] text-zinc-500">Entry</p>
            <p className="text-sm font-bold text-white">$182.50</p>
          </div>
          <div className="p-2 rounded-lg bg-black/40 text-center">
            <p className="text-[10px] text-zinc-500">Stop</p>
            <p className="text-sm font-bold text-rose-400">$180.00</p>
          </div>
          <div className="p-2 rounded-lg bg-black/40 text-center">
            <p className="text-[10px] text-zinc-500">Target</p>
            <p className="text-sm font-bold text-emerald-400">$188.00</p>
          </div>
        </div>
        
        {/* Additional Metrics */}
        <div className="flex items-center justify-between p-2 rounded-lg bg-black/40 mb-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1">
              <TrendingUp className="w-3 h-3 text-cyan-400" />
              <span className="text-xs text-zinc-400">R:R</span>
              <span className="text-xs font-bold text-cyan-400">2.4:1</span>
            </div>
            <div className="flex items-center gap-1">
              <DollarSign className="w-3 h-3 text-emerald-400" />
              <span className="text-xs text-zinc-400">Risk</span>
              <span className="text-xs font-bold text-white">$125</span>
            </div>
            <div className="flex items-center gap-1">
              <Target className="w-3 h-3 text-violet-400" />
              <span className="text-xs text-zinc-400">Reward</span>
              <span className="text-xs font-bold text-emerald-400">$300</span>
            </div>
          </div>
        </div>
        
        {/* Our Edge Callout */}
        <div className="p-3 rounded-xl bg-gradient-to-r from-emerald-500/10 to-transparent border border-emerald-500/20">
          <div className="flex items-center gap-2 mb-1">
            <Trophy className="w-4 h-4 text-emerald-400" />
            <span className="text-xs font-bold text-emerald-400">OUR EDGE</span>
          </div>
          <p className="text-xs text-zinc-300">
            <strong>67%</strong> win rate on pullbacks • <strong>45</strong> trades • <strong>+$4,230</strong> total P&L
          </p>
        </div>
        
        {/* Mini Chart Placeholder */}
        <div className="mt-3 h-16 rounded-lg bg-black/40 flex items-center justify-center border border-white/5">
          <span className="text-[10px] text-zinc-600">[ Price Chart Preview ]</span>
        </div>
      </GlassCard>
    </div>
  </div>
);

// ============================================================================
// ENHANCED ANALYTICS
// ============================================================================

const EnhancedAnalytics = () => {
  const strategyData = [
    { name: 'Pullback', winRate: 67, trades: 45, avgR: 1.8, pnl: 4230, data: [20, 35, 45, 55, 60, 58, 65, 67] },
    { name: 'Breakout', winRate: 52, trades: 38, avgR: 2.1, pnl: 1890, data: [45, 50, 48, 52, 55, 50, 52, 52] },
    { name: 'Gap & Go', winRate: 34, trades: 21, avgR: 1.2, pnl: -890, data: [50, 45, 40, 38, 35, 30, 32, 34] },
    { name: 'Mean Rev', winRate: 61, trades: 29, avgR: 1.4, pnl: 2100, data: [40, 48, 52, 55, 58, 60, 62, 61] },
    { name: 'VWAP', winRate: 58, trades: 33, avgR: 1.6, pnl: 1650, data: [45, 50, 52, 55, 58, 56, 58, 58] },
  ];
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-cyan-400" />
            </div>
            Our Performance
          </h2>
          <p className="text-sm text-zinc-500 mt-1">What we've learned from trading together</p>
        </div>
        <select className="bg-zinc-800/50 border border-white/10 rounded-xl px-4 py-2 text-sm text-zinc-300 focus:outline-none focus:border-cyan-500/50">
          <option>Last 30 Days</option>
          <option>Last 90 Days</option>
          <option>All Time</option>
        </select>
      </div>
      
      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Our Win Rate', value: '58%', change: '+3%', icon: Percent, color: 'emerald', data: [50, 52, 55, 54, 56, 58, 57, 58] },
          { label: 'Our Avg R', value: '1.65', change: '+0.2', icon: TrendingUp, color: 'cyan', data: [1.2, 1.3, 1.4, 1.5, 1.6, 1.55, 1.6, 1.65] },
          { label: 'Total P&L', value: '+$8,470', change: '+$1.2k', icon: DollarSign, color: 'emerald', data: [5000, 5500, 6200, 6800, 7200, 7800, 8100, 8470] },
          { label: 'Best Streak', value: '7 wins', change: 'Current: 3', icon: Flame, color: 'amber', data: [2, 3, 5, 4, 7, 6, 5, 7] },
        ].map(card => (
          <GlassCard key={card.label} gradient className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-zinc-500">{card.label}</span>
              <div className={`w-8 h-8 rounded-lg bg-${card.color}-500/20 flex items-center justify-center`}>
                <card.icon className={`w-4 h-4 text-${card.color}-400`} />
              </div>
            </div>
            <p className={`text-3xl font-bold text-${card.color}-400`}>{card.value}</p>
            <div className="flex items-center justify-between mt-2">
              <span className="text-[10px] text-zinc-500">{card.change} vs last period</span>
            </div>
            <div className="h-8 mt-2 overflow-hidden rounded">
              <Sparkline data={card.data} color={card.color} />
            </div>
          </GlassCard>
        ))}
      </div>
      
      {/* Strategy Breakdown */}
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-bold text-white">Our Edge by Strategy</h3>
            <p className="text-xs text-zinc-500 mt-1">Setups where we have positive expectancy are highlighted</p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-emerald-500/30 border border-emerald-500" />
              <span className="text-zinc-400">Our Edge (55%+)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-rose-500/30 border border-rose-500" />
              <span className="text-zinc-400">Avoid (&lt;40%)</span>
            </div>
          </div>
        </div>
        
        <div className="space-y-4">
          {strategyData.map(stat => {
            const isEdge = stat.winRate >= 55;
            const isAvoid = stat.winRate < 40;
            
            return (
              <div 
                key={stat.name}
                className={`p-4 rounded-xl transition-all ${
                  isEdge ? 'bg-gradient-to-r from-emerald-500/10 to-transparent border border-emerald-500/20' :
                  isAvoid ? 'bg-gradient-to-r from-rose-500/5 to-transparent border border-rose-500/10' :
                  'bg-black/30 border border-white/5'
                }`}
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold text-white">{stat.name}</span>
                    {isEdge && (
                      <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded-full font-bold">
                        <Trophy className="w-3 h-3" /> OUR EDGE
                      </span>
                    )}
                    {isAvoid && (
                      <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 bg-rose-500/20 text-rose-400 rounded-full font-bold">
                        <AlertCircle className="w-3 h-3" /> AVOID
                      </span>
                    )}
                  </div>
                  <span className={`text-xl font-bold ${stat.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {stat.pnl >= 0 ? '+' : ''}${Math.abs(stat.pnl).toLocaleString()}
                  </span>
                </div>
                
                <div className="grid grid-cols-12 gap-4 items-center">
                  <div className="col-span-8">
                    <div className="flex items-center gap-6 text-sm mb-2">
                      <div>
                        <span className="text-zinc-500">Win Rate: </span>
                        <span className={`font-bold ${isEdge ? 'text-emerald-400' : isAvoid ? 'text-rose-400' : 'text-white'}`}>
                          {stat.winRate}%
                        </span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Trades: </span>
                        <span className="font-medium text-white">{stat.trades}</span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Avg R: </span>
                        <span className="font-medium text-cyan-400">{stat.avgR}</span>
                      </div>
                    </div>
                    
                    {/* Win Rate Bar */}
                    <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all ${
                          isEdge ? 'bg-gradient-to-r from-emerald-500 to-emerald-400' :
                          isAvoid ? 'bg-gradient-to-r from-rose-500 to-rose-400' :
                          'bg-gradient-to-r from-zinc-500 to-zinc-400'
                        }`}
                        style={{ width: `${stat.winRate}%` }}
                      />
                    </div>
                  </div>
                  
                  <div className="col-span-4 h-12 overflow-hidden rounded">
                    <Sparkline 
                      data={stat.data} 
                      color={isEdge ? 'emerald' : isAvoid ? 'rose' : 'cyan'} 
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        
        {/* Team Insight */}
        <div className="mt-6 p-4 rounded-xl bg-gradient-to-r from-cyan-500/10 via-violet-500/5 to-transparent border border-cyan-500/20">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center flex-shrink-0">
              <Brain className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-sm font-bold text-cyan-400 mb-1">Team Insight</p>
              <p className="text-sm text-zinc-300 leading-relaxed">
                We perform best on <strong className="text-emerald-400">Pullback</strong> and <strong className="text-emerald-400">Mean Reversion</strong> setups. 
                Consider focusing on these while avoiding <strong className="text-rose-400">Gap & Go</strong> trades where our win rate is below breakeven.
                Our average R on winning edge setups is <strong className="text-cyan-400">1.6R</strong>.
              </p>
            </div>
          </div>
        </div>
      </GlassCard>
    </div>
  );
};

// ============================================================================
// MAIN PAGE
// ============================================================================

const TeamBrainMockupsV2 = () => {
  const [activeSection, setActiveSection] = useState('optionc');
  
  const sections = [
    { id: 'optionc', label: 'Option C Enhanced', icon: Layout },
    { id: 'analytics', label: 'Our Performance', icon: BarChart3 },
    { id: 'modal', label: 'Our Take Modal', icon: Layers },
  ];
  
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <div className="border-b border-white/10 bg-black/40 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center">
                <Brain className="w-5 h-5 text-cyan-400" />
              </div>
              <div>
                <h1 className="text-xl font-bold">SentCom Mockups <span className="text-cyan-400">V2</span></h1>
                <p className="text-xs text-zinc-500">Sentient Command - Enhanced visual design based on your feedback</p>
              </div>
            </div>
            <div className="flex gap-2">
              {sections.map(section => (
                <button
                  key={section.id}
                  onClick={() => setActiveSection(section.id)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                    activeSection === section.id 
                      ? 'bg-gradient-to-r from-cyan-500/20 to-violet-500/20 text-white border border-cyan-500/30' 
                      : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  <section.icon className="w-4 h-4" />
                  {section.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      
      <div className="max-w-7xl mx-auto px-6 py-8">
        {activeSection === 'optionc' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                  <span className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center text-amber-400 font-bold">C</span>
                  Dedicated Page - Enhanced
                </h2>
                <p className="text-sm text-zinc-500 mt-1">
                  Full command center with glass effects, gradients, and visual polish
                </p>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-amber-500/20 text-amber-400 text-xs font-medium">
                Quick Actions: Drawer Style (Option C)
              </div>
            </div>
            
            <DedicatedPageV2 />
            
            <div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-xl">
              <p className="text-sm text-amber-400">
                <strong>Improvements:</strong> Glass morphism cards, ambient background effects, sparkline charts in positions, enhanced message styling with confidence scores, collapsible command drawer (your preferred Option C).
              </p>
            </div>
          </div>
        )}
        
        {activeSection === 'analytics' && (
          <EnhancedAnalytics />
        )}
        
        {activeSection === 'modal' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold text-white">"Our Take" Modal - Enhanced</h2>
              <p className="text-sm text-zinc-500 mt-1">
                Richer details: R:R ratio, risk/reward amounts, confidence score, our edge callout
              </p>
            </div>
            
            <EnhancedOurTakeModal />
            
            <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
              <p className="text-sm text-emerald-400">
                <strong>New details added:</strong> Confidence gauge, R:R ratio, dollar risk/reward, "Our Edge" callout with historical stats, mini chart preview placeholder.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TeamBrainMockupsV2;
