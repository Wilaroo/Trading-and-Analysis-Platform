/**
 * TeamBrain Mockups - Comprehensive Design Review
 * 
 * This page showcases ALL options for the Team Brain unified interface:
 * 1. Expanded Mode Options (A: Fullscreen, B: Dashboard Grid, C: Dedicated Page)
 * 2. Quick Action Placement Options (Always Visible, On Focus, Drawer)
 * 3. Analytics "Our Performance" Mockups
 * 4. Modal Changes Preview ("Our Take" vs "Bot's Take")
 * 5. Voice/Language Examples
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
  Hash, Bell, GitBranch, Circle
} from 'lucide-react';

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

const MockOrderPipeline = ({ size = 'normal' }) => {
  const textSize = size === 'large' ? 'text-sm' : 'text-[10px]';
  return (
    <div className={`flex items-center gap-2 ${textSize} font-mono bg-black/40 px-3 py-1.5 rounded-lg border border-white/5`}>
      <div className="flex items-center gap-1 text-amber-400">
        <span>2</span><span>PND</span>
      </div>
      <div className="w-px h-3 bg-white/10" />
      <div className="flex items-center gap-1 text-cyan-400 animate-pulse">
        <span>1</span><span>EXE</span>
      </div>
      <div className="w-px h-3 bg-white/10" />
      <div className="flex items-center gap-1 text-emerald-400">
        <span>5</span><span>FIL</span>
      </div>
    </div>
  );
};

const MockMessage = ({ type, content, time, isCompact = false }) => {
  if (type === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="flex items-end gap-2 max-w-[80%]">
          <div className="bg-cyan-500/10 border border-cyan-500/20 text-cyan-50 rounded-2xl rounded-br-none px-4 py-2.5">
            <p className={isCompact ? "text-xs" : "text-sm"}>{content}</p>
          </div>
          <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center flex-shrink-0">
            <User className="w-3.5 h-3.5 text-cyan-400" />
          </div>
        </div>
      </div>
    );
  }
  
  if (type === 'system') {
    const isWarning = content.includes('stop') || content.includes('Alert');
    const isFilter = content.includes('Filter') || content.includes('passing');
    return (
      <div className="flex mb-2">
        <div className={`w-full border-l-2 ${
          isFilter ? 'border-amber-500/50 bg-amber-500/5' :
          isWarning ? 'border-red-500/50 bg-red-500/5' : 
          'border-cyan-500/30 bg-cyan-500/5'
        } pl-3 py-1`}>
          <div className="flex items-center gap-2 mb-1">
            <Terminal className="w-3 h-3 text-zinc-500" />
            <span className={`text-[10px] font-mono uppercase tracking-wider ${
              isFilter ? 'text-amber-500' : isWarning ? 'text-red-400' : 'text-zinc-500'
            }`}>
              {isFilter ? 'FILTER' : isWarning ? 'ALERT' : 'SYSTEM'}
            </span>
            <span className="text-[10px] text-zinc-600">{time}</span>
          </div>
          <p className={`${isCompact ? 'text-[11px]' : 'text-xs'} font-mono text-zinc-300 leading-relaxed`}>{content}</p>
        </div>
      </div>
    );
  }
  
  return (
    <div className="flex justify-start mb-3">
      <div className="flex items-end gap-2 max-w-[85%]">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center flex-shrink-0">
          <Brain className="w-3.5 h-3.5 text-violet-400" />
        </div>
        <div className="bg-zinc-800/80 border border-white/10 text-zinc-200 rounded-2xl rounded-bl-none px-4 py-2.5">
          <p className={`${isCompact ? 'text-xs' : 'text-sm'} leading-relaxed`}>{content}</p>
        </div>
      </div>
    </div>
  );
};

const mockMessages = [
  { type: 'assistant', content: "Team Brain online. We're monitoring 3 active positions and scanning for setups.", time: '09:31' },
  { type: 'system', content: "We detected momentum building in NVDA. Volume 2.3x average.", time: '09:32' },
  { type: 'user', content: "What do we think about AAPL today?", time: '09:33' },
  { type: 'assistant', content: "We're seeing AAPL consolidate near $185 resistance. Our pullback win rate is 67% - if it dips to $182 support with volume, that's our zone.", time: '09:33' },
  { type: 'system', content: "Alert: Our TSLA stop is within 1.5% of current price. We might want to trail it.", time: '09:35' },
  { type: 'system', content: "Filter: We're passing on AMD breakout - our historical win rate is only 34% on this setup.", time: '09:36' },
];

const mockPositions = [
  { symbol: 'NVDA', pnl: '+$847', pnlPct: '+2.4%', status: 'running', entry: '$142.50' },
  { symbol: 'TSLA', pnl: '-$124', pnlPct: '-0.8%', status: 'watching', entry: '$245.00' },
  { symbol: 'META', pnl: '+$312', pnlPct: '+1.1%', status: 'trailing', entry: '$485.20' },
];

const mockSetups = [
  { symbol: 'AAPL', setup: 'Pullback', score: 82, distance: '0.8%', status: 'near' },
  { symbol: 'GOOGL', setup: 'Breakout', score: 71, distance: '2.1%', status: 'watching' },
  { symbol: 'AMZN', setup: 'Gap Fill', score: 68, distance: '1.5%', status: 'watching' },
];

const mockStrategyStats = [
  { name: 'Pullback', winRate: 67, trades: 45, avgR: 1.8, pnl: '+$4,230', trend: 'up' },
  { name: 'Breakout', winRate: 52, trades: 38, avgR: 2.1, pnl: '+$1,890', trend: 'flat' },
  { name: 'Gap & Go', winRate: 34, trades: 21, avgR: 1.2, pnl: '-$890', trend: 'down' },
  { name: 'Mean Reversion', winRate: 61, trades: 29, avgR: 1.4, pnl: '+$2,100', trend: 'up' },
  { name: 'VWAP Bounce', winRate: 58, trades: 33, avgR: 1.6, pnl: '+$1,650', trend: 'up' },
];

// ============================================================================
// OPTION A: FULLSCREEN COMMAND MODE (Cmd+K Activated)
// ============================================================================

const FullscreenCommandMode = ({ onClose }) => (
  <motion.div 
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    className="fixed inset-0 z-50 bg-black/95 backdrop-blur-xl"
  >
    <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:50px_50px]" />
    
    <div className="relative h-full flex flex-col max-w-5xl mx-auto p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/10">
            <Brain className="w-6 h-6 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">TEAM BRAIN</h1>
            <div className="flex items-center gap-3 mt-1">
              <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                ACTIVE
              </span>
              <span className="text-xs text-zinc-500">|</span>
              <span className="text-xs text-zinc-400">RISK_ON</span>
              <span className="text-xs text-zinc-500">|</span>
              <MockOrderPipeline />
            </div>
          </div>
        </div>
        
        <button 
          onClick={onClose}
          className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
        >
          <span className="text-xs bg-zinc-800 px-1.5 py-0.5 rounded">ESC</span>
          Close
        </button>
      </div>
      
      {/* Main Content */}
      <div className="flex-1 flex gap-6 min-h-0">
        <div className="flex-1 flex flex-col bg-zinc-900/50 border border-white/10 rounded-2xl overflow-hidden">
          <div className="flex-1 overflow-y-auto p-6">
            {mockMessages.map((msg, i) => (
              <MockMessage key={i} {...msg} />
            ))}
          </div>
        </div>
        
        <div className="w-80 space-y-4">
          <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Our Positions</h3>
            <div className="space-y-2">
              {mockPositions.map(pos => (
                <div key={pos.symbol} className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                  <span className="font-bold text-white">{pos.symbol}</span>
                  <span className={`font-mono text-sm ${pos.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {pos.pnlPct}
                  </span>
                </div>
              ))}
            </div>
          </div>
          
          <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Quick Commands</h3>
            <div className="space-y-2">
              {[
                { cmd: '/briefme', desc: 'Get market summary' },
                { cmd: '/scan', desc: 'Find new setups' },
                { cmd: '/performance', desc: 'View our stats' },
                { cmd: '/close [SYM]', desc: 'Close position' },
              ].map(item => (
                <div key={item.cmd} className="flex items-center justify-between text-sm">
                  <code className="text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded">{item.cmd}</code>
                  <span className="text-zinc-500 text-xs">{item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      
      {/* Input */}
      <div className="mt-6">
        <div className="relative">
          <input
            type="text"
            placeholder="Command the team... (try /briefme or ask about any ticker)"
            className="w-full bg-zinc-900/80 border-2 border-white/10 rounded-2xl pl-6 pr-14 py-5 text-lg text-white placeholder-zinc-600 focus:outline-none focus:border-cyan-500/50 transition-all"
          />
          <button className="absolute right-3 top-1/2 -translate-y-1/2 p-2 bg-cyan-500 hover:bg-cyan-400 text-black rounded-xl transition-colors">
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  </motion.div>
);

// ============================================================================
// OPTION B: DASHBOARD INTEGRATED
// ============================================================================

const DashboardIntegrated = () => (
  <div className="bg-zinc-950 border border-white/10 rounded-xl overflow-hidden h-[500px] flex flex-col">
    <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-zinc-900/50">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center">
          <Brain className="w-4 h-4 text-cyan-400" />
        </div>
        <div>
          <h2 className="text-sm font-bold text-white">TEAM BRAIN</h2>
          <span className="text-[10px] text-emerald-400">ONLINE</span>
        </div>
      </div>
      <MockOrderPipeline />
    </div>
    
    <div className="flex-1 overflow-y-auto p-4">
      {mockMessages.slice(0, 4).map((msg, i) => (
        <MockMessage key={i} {...msg} isCompact />
      ))}
    </div>
    
    <div className="p-3 bg-zinc-900 border-t border-white/10">
      <div className="relative">
        <input
          type="text"
          placeholder="Command the team..."
          className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-12 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-cyan-500/50"
        />
        <button className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-cyan-500/20 text-cyan-400 rounded-lg">
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
);

// ============================================================================
// OPTION C: DEDICATED PAGE - FULL COMMAND CENTER
// ============================================================================

const DedicatedPageMode = () => (
  <div className="bg-zinc-950 min-h-[700px] rounded-xl border border-white/10 overflow-hidden">
    {/* Top Navigation Bar */}
    <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-zinc-900/50">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/10">
            <Brain className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">TEAM BRAIN</h1>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                CONNECTED
              </span>
              <span className="text-zinc-600">•</span>
              <span className="text-[10px] text-zinc-400">RISK_ON</span>
            </div>
          </div>
        </div>
        
        {/* Mode Tabs */}
        <div className="flex items-center gap-1 ml-8 bg-zinc-900 rounded-lg p-1">
          {[
            { id: 'chat', icon: MessageSquare, label: 'Chat' },
            { id: 'monitor', icon: Monitor, label: 'Monitor' },
            { id: 'analyze', icon: BarChart3, label: 'Analyze' },
          ].map((tab, i) => (
            <button 
              key={tab.id}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                i === 0 ? 'bg-cyan-500/20 text-cyan-400' : 'text-zinc-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      
      <div className="flex items-center gap-4">
        <MockOrderPipeline size="large" />
        <button className="flex items-center gap-2 px-3 py-1.5 text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors">
          <Settings className="w-3.5 h-3.5" />
          Settings
        </button>
      </div>
    </div>
    
    {/* Main 3-Column Layout */}
    <div className="grid grid-cols-12 gap-4 p-4 h-[620px]">
      {/* Left Column - Positions & Setups */}
      <div className="col-span-3 space-y-4 overflow-y-auto">
        {/* Our Positions */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Our Positions</h3>
            <span className="text-xs text-emerald-400 font-mono">+$1,035</span>
          </div>
          <div className="space-y-2">
            {mockPositions.map(pos => (
              <div key={pos.symbol} className="p-2.5 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-colors">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold text-white">{pos.symbol}</span>
                  <span className={`font-mono text-sm ${pos.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {pos.pnl}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-zinc-500">
                  <span>Entry: {pos.entry}</span>
                  <span className={`px-1.5 py-0.5 rounded ${
                    pos.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' :
                    pos.status === 'trailing' ? 'bg-cyan-500/20 text-cyan-400' :
                    'bg-amber-500/20 text-amber-400'
                  }`}>
                    {pos.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
        
        {/* Setups We're Watching */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Setups We're Watching</h3>
            <button className="text-[10px] text-cyan-400 hover:text-cyan-300">View All</button>
          </div>
          <div className="space-y-2">
            {mockSetups.map(setup => (
              <div key={setup.symbol} className="p-2.5 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-colors">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{setup.symbol}</span>
                    <span className="text-[10px] px-1.5 py-0.5 bg-violet-500/20 text-violet-400 rounded">
                      {setup.setup}
                    </span>
                  </div>
                  <span className="text-xs font-mono text-zinc-400">{setup.score}</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-zinc-500">{setup.distance} to entry</span>
                  <span className={`${setup.status === 'near' ? 'text-amber-400' : 'text-zinc-500'}`}>
                    {setup.status === 'near' ? '⚡ Near Entry' : 'Watching'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
        
        {/* Quick Performance */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Today's Stats</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="text-center">
              <p className="text-2xl font-bold text-emerald-400">67%</p>
              <p className="text-[10px] text-zinc-500">Win Rate</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-cyan-400">1.8R</p>
              <p className="text-[10px] text-zinc-500">Avg Win</p>
            </div>
          </div>
        </div>
      </div>
      
      {/* Center Column - Chat/Stream */}
      <div className="col-span-6 flex flex-col bg-zinc-900/30 border border-white/10 rounded-xl overflow-hidden">
        {/* Stream Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            <span className="text-xs font-medium text-zinc-300">Live Stream</span>
          </div>
          <div className="flex items-center gap-2">
            <button className="text-[10px] text-zinc-500 hover:text-white px-2 py-1 rounded hover:bg-white/5">
              <Filter className="w-3 h-3" />
            </button>
            <button className="text-[10px] text-zinc-500 hover:text-white px-2 py-1 rounded hover:bg-white/5">
              Clear
            </button>
          </div>
        </div>
        
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4">
          {mockMessages.map((msg, i) => (
            <MockMessage key={i} {...msg} />
          ))}
        </div>
        
        {/* Input Area */}
        <div className="p-4 bg-zinc-900/50 border-t border-white/5">
          {/* Quick Actions */}
          <div className="flex flex-wrap gap-2 mb-3">
            {[
              { label: '/briefme', icon: Newspaper },
              { label: '/scan', icon: Search },
              { label: '/performance', icon: BarChart3 },
              { label: '/close', icon: X },
              { label: '/trail', icon: TrendingUp },
            ].map(chip => (
              <button 
                key={chip.label}
                className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg border border-white/5 transition-colors"
              >
                <chip.icon className="w-3 h-3" />
                {chip.label}
              </button>
            ))}
          </div>
          
          {/* Input */}
          <div className="relative">
            <input
              type="text"
              placeholder="Talk to the team... Ask questions, give commands, or discuss strategy"
              className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-24 py-3.5 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-cyan-500/50"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <button className="p-2 text-zinc-500 hover:text-white rounded-lg hover:bg-white/5 transition-colors">
                <Mic className="w-4 h-4" />
              </button>
              <button className="p-2 bg-cyan-500 hover:bg-cyan-400 text-black rounded-lg transition-colors">
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
      
      {/* Right Column - Intelligence & Context */}
      <div className="col-span-3 space-y-4 overflow-y-auto">
        {/* Market Regime */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Market Context</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">Regime</span>
              <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded text-xs font-medium">RISK_ON</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">SPY Trend</span>
              <span className="text-xs text-emerald-400 flex items-center gap-1">
                <ArrowUpRight className="w-3 h-3" /> Bullish
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">VIX</span>
              <span className="text-xs text-zinc-300">14.2</span>
            </div>
          </div>
        </div>
        
        {/* Recent Alerts */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Recent Alerts</h3>
            <Bell className="w-3.5 h-3.5 text-zinc-500" />
          </div>
          <div className="space-y-2">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <p className="text-[11px] text-amber-300">TSLA stop within 1.5%</p>
              <p className="text-[10px] text-zinc-500 mt-0.5">2 min ago</p>
            </div>
            <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
              <p className="text-[11px] text-cyan-300">NVDA volume spike detected</p>
              <p className="text-[10px] text-zinc-500 mt-0.5">5 min ago</p>
            </div>
            <div className="p-2 rounded-lg bg-violet-500/10 border border-violet-500/20">
              <p className="text-[11px] text-violet-300">AAPL approaching entry zone</p>
              <p className="text-[10px] text-zinc-500 mt-0.5">8 min ago</p>
            </div>
          </div>
        </div>
        
        {/* Strategy Filter Status */}
        <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Smart Filter</h3>
            <span className="text-[10px] text-emerald-400">ACTIVE</span>
          </div>
          <div className="space-y-2 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-zinc-500">Trades Filtered Today</span>
              <span className="text-amber-400">3</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-500">Est. Losses Avoided</span>
              <span className="text-emerald-400">~$450</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
);

// ============================================================================
// ANALYTICS - "OUR PERFORMANCE" MOCKUP
// ============================================================================

const OurPerformanceMockup = () => (
  <div className="bg-zinc-950 rounded-xl border border-white/10 p-6">
    <div className="flex items-center justify-between mb-6">
      <div>
        <h2 className="text-xl font-bold text-white">Our Performance</h2>
        <p className="text-sm text-zinc-500">What we've learned from trading together</p>
      </div>
      <div className="flex items-center gap-2">
        <select className="bg-zinc-800 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-300">
          <option>Last 30 Days</option>
          <option>Last 90 Days</option>
          <option>All Time</option>
        </select>
      </div>
    </div>
    
    {/* Summary Cards */}
    <div className="grid grid-cols-4 gap-4 mb-6">
      {[
        { label: 'Our Win Rate', value: '58%', change: '+3%', icon: Percent, color: 'emerald' },
        { label: 'Our Avg R', value: '1.65', change: '+0.2', icon: TrendingUp, color: 'cyan' },
        { label: 'Total P&L', value: '+$8,470', change: '+$1,200', icon: DollarSign, color: 'emerald' },
        { label: 'Best Streak', value: '7 wins', change: 'Current: 3', icon: Award, color: 'violet' },
      ].map(card => (
        <div key={card.label} className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-zinc-500">{card.label}</span>
            <card.icon className={`w-4 h-4 text-${card.color}-400`} />
          </div>
          <p className={`text-2xl font-bold text-${card.color}-400`}>{card.value}</p>
          <p className="text-[10px] text-zinc-500 mt-1">{card.change} vs last period</p>
        </div>
      ))}
    </div>
    
    {/* Strategy Breakdown */}
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
      <h3 className="text-sm font-bold text-white mb-4">Our Edge by Strategy</h3>
      <p className="text-xs text-zinc-500 mb-4">Setups where we have positive expectancy are highlighted</p>
      
      <div className="space-y-3">
        {mockStrategyStats.map(stat => (
          <div 
            key={stat.name} 
            className={`p-3 rounded-lg ${stat.winRate >= 55 ? 'bg-emerald-500/10 border border-emerald-500/20' : 'bg-zinc-800/50'}`}
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span className="font-medium text-white">{stat.name}</span>
                {stat.winRate >= 55 && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
                    OUR EDGE
                  </span>
                )}
                {stat.winRate < 40 && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
                    AVOID
                  </span>
                )}
              </div>
              <span className={`font-mono text-sm ${stat.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                {stat.pnl}
              </span>
            </div>
            
            <div className="flex items-center gap-6 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="text-zinc-500">Win Rate:</span>
                <span className={stat.winRate >= 55 ? 'text-emerald-400' : stat.winRate < 40 ? 'text-rose-400' : 'text-zinc-300'}>
                  {stat.winRate}%
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-zinc-500">Trades:</span>
                <span className="text-zinc-300">{stat.trades}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-zinc-500">Avg R:</span>
                <span className="text-zinc-300">{stat.avgR}</span>
              </div>
              <div className="flex items-center gap-1.5">
                {stat.trend === 'up' && <ArrowUpRight className="w-3 h-3 text-emerald-400" />}
                {stat.trend === 'down' && <ArrowDownRight className="w-3 h-3 text-rose-400" />}
                {stat.trend === 'flat' && <ArrowRight className="w-3 h-3 text-zinc-400" />}
                <span className="text-zinc-500">Trend</span>
              </div>
            </div>
            
            {/* Win Rate Bar */}
            <div className="mt-2 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full ${stat.winRate >= 55 ? 'bg-emerald-500' : stat.winRate < 40 ? 'bg-rose-500' : 'bg-zinc-500'}`}
                style={{ width: `${stat.winRate}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      
      {/* Insight Box */}
      <div className="mt-4 p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
        <div className="flex items-start gap-2">
          <Brain className="w-4 h-4 text-cyan-400 mt-0.5" />
          <div>
            <p className="text-sm text-cyan-300 font-medium">Team Insight</p>
            <p className="text-xs text-zinc-400 mt-1">
              We perform best on <strong className="text-white">Pullback</strong> and <strong className="text-white">Mean Reversion</strong> setups. 
              Consider focusing on these while avoiding <strong className="text-rose-400">Gap & Go</strong> trades where our win rate is below breakeven.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
);

// ============================================================================
// QUICK ACTIONS OPTIONS
// ============================================================================

const QuickActionsAlwaysVisible = () => (
  <div className="bg-zinc-950 border border-white/10 rounded-xl p-4">
    <p className="text-xs text-zinc-500 mb-3 uppercase tracking-wider">Option A: Always Visible</p>
    <div className="relative">
      <input
        type="text"
        placeholder="Command the team..."
        className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-12 py-3 text-sm text-white placeholder-zinc-600"
      />
      <button className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-cyan-500/20 text-cyan-400 rounded-lg">
        <Send className="w-4 h-4" />
      </button>
    </div>
    <div className="flex flex-wrap gap-2 mt-3">
      {[
        { label: '/briefme', icon: Newspaper },
        { label: '/scan', icon: Search },
        { label: '/performance', icon: BarChart3 },
        { label: '/positions', icon: Target },
      ].map(chip => (
        <button 
          key={chip.label}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg border border-white/5 transition-colors"
        >
          <chip.icon className="w-3 h-3" />
          {chip.label}
        </button>
      ))}
    </div>
  </div>
);

const QuickActionsOnFocus = () => {
  const [focused, setFocused] = useState(false);
  
  return (
    <div className="bg-zinc-950 border border-white/10 rounded-xl p-4">
      <p className="text-xs text-zinc-500 mb-3 uppercase tracking-wider">Option B: On Focus Only</p>
      <div className="relative">
        <input
          type="text"
          placeholder="Command the team..."
          className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-12 py-3 text-sm text-white placeholder-zinc-600 focus:border-cyan-500/50"
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 200)}
        />
        <button className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-cyan-500/20 text-cyan-400 rounded-lg">
          <Send className="w-4 h-4" />
        </button>
      </div>
      
      <AnimatePresence>
        {focused && (
          <motion.div 
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="flex flex-wrap gap-2 mt-3"
          >
            {[
              { label: '/briefme', icon: Newspaper },
              { label: '/scan', icon: Search },
              { label: '/performance', icon: BarChart3 },
              { label: '/positions', icon: Target },
            ].map(chip => (
              <button 
                key={chip.label}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 rounded-lg border border-cyan-500/20 transition-colors"
              >
                <chip.icon className="w-3 h-3" />
                {chip.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      
      {!focused && (
        <p className="text-[10px] text-zinc-600 mt-2">Click input to see quick actions</p>
      )}
    </div>
  );
};

const QuickActionsDrawer = () => {
  const [open, setOpen] = useState(false);
  
  return (
    <div className="bg-zinc-950 border border-white/10 rounded-xl p-4">
      <p className="text-xs text-zinc-500 mb-3 uppercase tracking-wider">Option C: Collapsible Drawer</p>
      
      <AnimatePresence>
        {open && (
          <motion.div 
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden mb-3"
          >
            <div className="grid grid-cols-2 gap-2 p-3 bg-zinc-900/50 rounded-xl border border-white/5">
              {[
                { label: 'Brief Me', desc: 'Get market summary', icon: Newspaper },
                { label: 'Scan', desc: 'Find new setups', icon: Search },
                { label: 'Performance', desc: 'View our stats', icon: BarChart3 },
                { label: 'Positions', desc: 'See our trades', icon: Target },
                { label: 'Close Position', desc: 'Exit a trade', icon: X },
                { label: 'Fix Stops', desc: 'Adjust risky stops', icon: Shield },
              ].map(item => (
                <button 
                  key={item.label}
                  className="flex items-start gap-2 p-2 text-left hover:bg-white/5 rounded-lg transition-colors"
                >
                  <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                    <item.icon className="w-4 h-4 text-cyan-400" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-white">{item.label}</p>
                    <p className="text-[10px] text-zinc-500">{item.desc}</p>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      <div className="relative">
        <input
          type="text"
          placeholder="Command the team..."
          className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-24 py-3 text-sm text-white placeholder-zinc-600"
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          <button 
            onClick={() => setOpen(!open)}
            className={`p-1.5 rounded-lg transition-colors ${open ? 'bg-cyan-500/20 text-cyan-400' : 'bg-zinc-800 text-zinc-400 hover:text-white'}`}
          >
            {open ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </button>
          <button className="p-1.5 bg-cyan-500/20 text-cyan-400 rounded-lg">
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// MODAL COMPARISON - "OUR TAKE" vs "BOT'S TAKE"
// ============================================================================

const ModalComparisonMockup = () => (
  <div className="grid grid-cols-2 gap-6">
    {/* Old: Bot's Take */}
    <div className="opacity-60">
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3 flex items-center gap-2">
        <X className="w-3 h-3 text-rose-400" /> Old: Bot's Take
      </p>
      <div className="bg-zinc-900 border border-white/10 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Cpu className="w-5 h-5 text-cyan-400" />
          <h3 className="font-bold text-white">Bot's Take</h3>
        </div>
        <p className="text-sm text-zinc-300 mb-3">
          "I see AAPL forming a pullback to the 20 EMA. <strong>I recommend</strong> waiting for a bounce with volume confirmation before <strong>you</strong> enter."
        </p>
        <div className="text-xs text-zinc-500">
          <p>• Entry: $182.50</p>
          <p>• Stop: $180.00</p>
          <p>• Target: $188.00</p>
        </div>
      </div>
    </div>
    
    {/* New: Our Take */}
    <div>
      <p className="text-xs text-emerald-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <CheckCircle className="w-3 h-3" /> New: Our Take
      </p>
      <div className="bg-zinc-900 border border-emerald-500/30 rounded-xl p-4 ring-1 ring-emerald-500/20">
        <div className="flex items-center gap-2 mb-3">
          <Brain className="w-5 h-5 text-violet-400" />
          <h3 className="font-bold text-white">Our Take</h3>
        </div>
        <p className="text-sm text-zinc-300 mb-3">
          "<strong>We</strong> see AAPL forming a pullback to the 20 EMA. This is <strong>our</strong> kind of setup - <strong>we're</strong> 67% on pullbacks. Let's wait for a bounce with volume confirmation before <strong>we</strong> enter."
        </p>
        <div className="text-xs text-zinc-500">
          <p>• Entry: $182.50</p>
          <p>• Stop: $180.00</p>
          <p>• Target: $188.00</p>
        </div>
        <div className="mt-3 p-2 bg-emerald-500/10 rounded-lg">
          <p className="text-[11px] text-emerald-400">
            <strong>Our Edge:</strong> 67% win rate on pullbacks (45 trades)
          </p>
        </div>
      </div>
    </div>
  </div>
);

// ============================================================================
// VOICE EXAMPLES
// ============================================================================

const VoiceExamplesMockup = () => (
  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-6">
    <h3 className="text-lg font-bold text-white mb-4">Voice & Language Examples</h3>
    <p className="text-sm text-zinc-500 mb-6">How "we" language transforms the trading experience</p>
    
    <div className="space-y-4">
      {[
        {
          category: 'Analysis',
          old: 'I see strong momentum in NVDA with volume confirmation.',
          new: "We're seeing strong momentum in NVDA with volume confirmation."
        },
        {
          category: 'Trade Entry',
          old: 'I recommend you buy AAPL here.',
          new: "This looks like our entry - let's take the AAPL pullback."
        },
        {
          category: 'Trade Exit',
          old: 'You should consider taking profits.',
          new: "We should consider taking profits here - approaching our target."
        },
        {
          category: 'Learning',
          old: 'Your win rate on breakouts is 52%.',
          new: "We've been 52% on breakouts lately - not our strongest setup."
        },
        {
          category: 'Warning',
          old: 'Your stop is too tight.',
          new: "Heads up - our stop might be too tight for this volatility."
        },
        {
          category: 'Filter',
          old: 'I am skipping this trade due to low win rate.',
          new: "We're passing on this one - our history says this isn't our edge."
        },
      ].map(example => (
        <div key={example.category} className="grid grid-cols-12 gap-4 p-3 rounded-lg bg-black/30">
          <div className="col-span-2">
            <span className="text-xs font-medium text-violet-400">{example.category}</span>
          </div>
          <div className="col-span-5">
            <p className="text-xs text-zinc-500 mb-1">Old (I/You)</p>
            <p className="text-sm text-zinc-400 line-through">{example.old}</p>
          </div>
          <div className="col-span-5">
            <p className="text-xs text-emerald-400 mb-1">New (We/Our)</p>
            <p className="text-sm text-zinc-200">{example.new}</p>
          </div>
        </div>
      ))}
    </div>
  </div>
);

// ============================================================================
// MAIN MOCKUP PAGE
// ============================================================================

const TeamBrainMockups = () => {
  const [showFullscreen, setShowFullscreen] = useState(false);
  const [activeSection, setActiveSection] = useState('expanded');
  
  const sections = [
    { id: 'expanded', label: 'Expanded Mode', icon: Layout },
    { id: 'actions', label: 'Quick Actions', icon: Zap },
    { id: 'analytics', label: 'Our Performance', icon: BarChart3 },
    { id: 'modals', label: 'Modal Changes', icon: Layers },
    { id: 'voice', label: 'Voice Examples', icon: MessageSquare },
  ];
  
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <div className="border-b border-white/10 bg-zinc-900/50 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-3">
                <Brain className="w-7 h-7 text-cyan-400" />
                Team Brain Mockups
              </h1>
              <p className="text-sm text-zinc-500">Comprehensive design review for the unified AI interface</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {sections.map(section => (
                <button
                  key={section.id}
                  onClick={() => setActiveSection(section.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    activeSection === section.id 
                      ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                      : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  <section.icon className="w-3.5 h-3.5" />
                  {section.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* EXPANDED MODE OPTIONS */}
        {activeSection === 'expanded' && (
          <div className="space-y-12">
            {/* Option A: Fullscreen */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-xl font-bold text-cyan-400 flex items-center gap-2">
                    <span className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center text-sm">A</span>
                    Fullscreen Command Mode
                  </h2>
                  <p className="text-sm text-zinc-500 mt-1">
                    Press Cmd+K to enter immersive mode. Best for focused trading sessions.
                  </p>
                </div>
                <button
                  onClick={() => setShowFullscreen(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-black rounded-lg font-medium transition-colors"
                >
                  <Maximize2 className="w-4 h-4" />
                  Try Fullscreen
                </button>
              </div>
              <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
                <p className="text-sm text-emerald-400">
                  <strong>Best for:</strong> Deep work, power users, when you want maximum focus and screen real estate.
                </p>
              </div>
            </section>
            
            {/* Option B: Dashboard Integrated */}
            <section>
              <div className="mb-4">
                <h2 className="text-xl font-bold text-violet-400 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center text-sm">B</span>
                  Dashboard Integrated
                </h2>
                <p className="text-sm text-zinc-500 mt-1">
                  Team Brain stays in the dashboard grid alongside other panels.
                </p>
              </div>
              
              <div className="grid grid-cols-12 gap-4 p-4 bg-zinc-900/30 rounded-xl border border-white/10">
                <div className="col-span-7">
                  <DashboardIntegrated />
                </div>
                <div className="col-span-5 space-y-4">
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 h-40">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Setups We're Watching</p>
                    <div className="space-y-2">
                      {mockSetups.slice(0, 2).map(s => (
                        <div key={s.symbol} className="flex justify-between items-center p-2 rounded bg-black/30">
                          <span className="font-bold text-sm">{s.symbol}</span>
                          <span className={`text-xs ${s.status === 'near' ? 'text-amber-400' : 'text-zinc-500'}`}>
                            {s.status === 'near' ? 'Near Entry' : 'Watching'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 h-32">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Our Performance Today</p>
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-bold text-emerald-400">+$847</span>
                      <span className="text-sm text-zinc-500">67% win rate</span>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="mt-4 p-4 bg-violet-500/10 border border-violet-500/20 rounded-xl">
                <p className="text-sm text-violet-400">
                  <strong>Best for:</strong> Multi-tasking, keeping an eye on multiple data sources at once.
                </p>
              </div>
            </section>
            
            {/* Option C: Dedicated Page */}
            <section>
              <div className="mb-4">
                <h2 className="text-xl font-bold text-amber-400 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center text-sm">C</span>
                  Dedicated Page / Route
                </h2>
                <p className="text-sm text-zinc-500 mt-1">
                  Full command center as its own page (/team-brain). 3-column layout with everything.
                </p>
              </div>
              
              <DedicatedPageMode />
              
              <div className="mt-4 p-4 bg-amber-500/10 border border-amber-500/20 rounded-xl">
                <p className="text-sm text-amber-400">
                  <strong>Best for:</strong> Comprehensive view, all context visible, replaces multiple tabs. This becomes the "home base" for trading.
                </p>
              </div>
            </section>
          </div>
        )}
        
        {/* QUICK ACTIONS OPTIONS */}
        {activeSection === 'actions' && (
          <div className="space-y-8">
            <div className="text-center mb-8">
              <h2 className="text-xl font-bold">Quick Action Placement Options</h2>
              <p className="text-sm text-zinc-500 mt-1">
                Where should command shortcuts (/briefme, /scan, etc.) appear?
              </p>
            </div>
            
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div>
                <QuickActionsAlwaysVisible />
                <div className="mt-3 p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
                  <p className="text-xs text-cyan-400">
                    <strong>Pros:</strong> Discoverable, always accessible<br/>
                    <strong>Cons:</strong> Takes vertical space
                  </p>
                </div>
              </div>
              
              <div>
                <QuickActionsOnFocus />
                <div className="mt-3 p-3 bg-violet-500/10 border border-violet-500/20 rounded-lg">
                  <p className="text-xs text-violet-400">
                    <strong>Pros:</strong> Clean when not typing, contextual<br/>
                    <strong>Cons:</strong> Hidden until focused
                  </p>
                </div>
              </div>
              
              <div>
                <QuickActionsDrawer />
                <div className="mt-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                  <p className="text-xs text-amber-400">
                    <strong>Pros:</strong> Rich descriptions, organized<br/>
                    <strong>Cons:</strong> Extra click to access
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
        
        {/* ANALYTICS - OUR PERFORMANCE */}
        {activeSection === 'analytics' && (
          <div className="space-y-8">
            <div className="text-center mb-8">
              <h2 className="text-xl font-bold">"Our Performance" Analytics View</h2>
              <p className="text-sm text-zinc-500 mt-1">
                What we've learned from trading together - strategy breakdown with "we" language
              </p>
            </div>
            
            <OurPerformanceMockup />
          </div>
        )}
        
        {/* MODAL CHANGES */}
        {activeSection === 'modals' && (
          <div className="space-y-8">
            <div className="text-center mb-8">
              <h2 className="text-xl font-bold">Modal Language Changes</h2>
              <p className="text-sm text-zinc-500 mt-1">
                "Bot's Take" becomes "Our Take" - same info, partnership language
              </p>
            </div>
            
            <ModalComparisonMockup />
          </div>
        )}
        
        {/* VOICE EXAMPLES */}
        {activeSection === 'voice' && (
          <div className="space-y-8">
            <div className="text-center mb-8">
              <h2 className="text-xl font-bold">Voice & Language Transformation</h2>
              <p className="text-sm text-zinc-500 mt-1">
                How changing pronouns creates a partnership feeling
              </p>
            </div>
            
            <VoiceExamplesMockup />
          </div>
        )}
      </div>
      
      {/* Fullscreen Mode Overlay */}
      <AnimatePresence>
        {showFullscreen && (
          <FullscreenCommandMode onClose={() => setShowFullscreen(false)} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default TeamBrainMockups;
