/**
 * TeamBrain Mockups - All Variations
 * 
 * This page showcases different options for the Team Brain unified interface:
 * 1. Expanded Mode Options (Fullscreen Command vs Dashboard Grid)
 * 2. Quick Action Placement Options (Always Visible, On Focus, Drawer)
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Cpu, User, Sparkles, Clock, Zap, Target, 
  AlertCircle, ArrowRight, CheckCircle, Loader, Shield, 
  Maximize2, Minimize2, MessageSquare, Terminal, Activity,
  ChevronUp, ChevronDown, Command, Keyboard, X, TrendingUp,
  BarChart3, Search, Newspaper, Play, Pause
} from 'lucide-react';

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

const MockOrderPipeline = () => (
  <div className="flex items-center gap-2 text-[10px] font-mono bg-black/40 px-2 py-1 rounded-lg border border-white/5">
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

const MockMessage = ({ type, content, time }) => {
  if (type === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="flex items-end gap-2 max-w-[80%]">
          <div className="bg-cyan-500/10 border border-cyan-500/20 text-cyan-50 rounded-2xl rounded-br-none px-4 py-2.5">
            <p className="text-sm">{content}</p>
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
    return (
      <div className="flex mb-2">
        <div className={`w-full border-l-2 ${isWarning ? 'border-amber-500/50 bg-amber-500/5' : 'border-cyan-500/30 bg-cyan-500/5'} pl-3 py-1`}>
          <div className="flex items-center gap-2 mb-1">
            <Terminal className="w-3 h-3 text-zinc-500" />
            <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">
              {isWarning ? 'ALERT' : 'SYSTEM'}
            </span>
            <span className="text-[10px] text-zinc-600">{time}</span>
          </div>
          <p className="text-xs font-mono text-zinc-300 leading-relaxed">{content}</p>
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
          <p className="text-sm leading-relaxed">{content}</p>
        </div>
      </div>
    </div>
  );
};

const mockMessages = [
  { type: 'assistant', content: "Team Brain online. We're monitoring 3 active positions and scanning for setups.", time: '09:31' },
  { type: 'system', content: "Scanning: We detected momentum building in NVDA. Volume 2.3x average.", time: '09:32' },
  { type: 'user', content: "What do we think about AAPL today?", time: '09:33' },
  { type: 'assistant', content: "We're seeing AAPL consolidate near $185 resistance. Our pullback win rate is 67% - if it dips to $182 support with volume, that's our zone.", time: '09:33' },
  { type: 'system', content: "Alert: Our TSLA stop is within 1.5% of current price. We might want to trail it.", time: '09:35' },
  { type: 'system', content: "Filter: We're passing on AMD breakout - our historical win rate is only 34% on this setup.", time: '09:36' },
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
    {/* Background Grid */}
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
      
      {/* Main Content - Split View */}
      <div className="flex-1 flex gap-6 min-h-0">
        {/* Stream */}
        <div className="flex-1 flex flex-col bg-zinc-900/50 border border-white/10 rounded-2xl overflow-hidden">
          <div className="flex-1 overflow-y-auto p-6">
            {mockMessages.map((msg, i) => (
              <MockMessage key={i} {...msg} />
            ))}
          </div>
        </div>
        
        {/* Side Panel - Quick Context */}
        <div className="w-80 space-y-4">
          <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
            <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Our Positions</h3>
            <div className="space-y-2">
              {[
                { symbol: 'NVDA', pnl: '+2.4%', status: 'running' },
                { symbol: 'TSLA', pnl: '-0.8%', status: 'watching' },
                { symbol: 'META', pnl: '+1.1%', status: 'trailing' },
              ].map(pos => (
                <div key={pos.symbol} className="flex items-center justify-between p-2 rounded-lg bg-black/30">
                  <span className="font-bold text-white">{pos.symbol}</span>
                  <span className={`font-mono text-sm ${pos.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {pos.pnl}
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
      
      {/* Input - Prominent at Bottom */}
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
// OPTION B: DASHBOARD INTEGRATED (Always in Grid)
// ============================================================================

const DashboardIntegrated = () => (
  <div className="bg-zinc-950 border border-white/10 rounded-xl overflow-hidden h-[500px] flex flex-col">
    {/* Compact Header */}
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
    
    {/* Stream */}
    <div className="flex-1 overflow-y-auto p-4">
      {mockMessages.slice(0, 4).map((msg, i) => (
        <MockMessage key={i} {...msg} />
      ))}
    </div>
    
    {/* Input */}
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
// QUICK ACTIONS OPTIONS
// ============================================================================

// Option A: Always Visible
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
    {/* Always visible chips */}
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

// Option B: On Focus Only
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

// Option C: Collapsible Drawer
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
// MAIN MOCKUP PAGE
// ============================================================================

const TeamBrainMockups = () => {
  const [showFullscreen, setShowFullscreen] = useState(false);
  const [activeSection, setActiveSection] = useState('expanded');
  
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <div className="border-b border-white/10 bg-zinc-900/50 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">Team Brain Mockups</h1>
              <p className="text-sm text-zinc-500">Design options for the unified AI interface</p>
            </div>
            <div className="flex gap-2">
              {['expanded', 'actions'].map(section => (
                <button
                  key={section}
                  onClick={() => setActiveSection(section)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    activeSection === section 
                      ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                      : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {section === 'expanded' ? 'Expanded Mode Options' : 'Quick Action Options'}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      
      <div className="max-w-7xl mx-auto px-6 py-8">
        {activeSection === 'expanded' && (
          <div className="space-y-12">
            {/* Option A: Fullscreen Command Mode */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-xl font-bold text-cyan-400">Option A: Fullscreen Command Mode</h2>
                  <p className="text-sm text-zinc-500 mt-1">
                    Press Cmd+K to enter immersive command mode. ESC to close.
                    Best for focused trading sessions.
                  </p>
                </div>
                <button
                  onClick={() => setShowFullscreen(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-black rounded-lg font-medium transition-colors"
                >
                  <Maximize2 className="w-4 h-4" />
                  Try Fullscreen Mode
                </button>
              </div>
              
              {/* Preview */}
              <div className="relative rounded-xl border border-white/10 overflow-hidden bg-black/50 p-1">
                <img 
                  src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1200' height='600' viewBox='0 0 1200 600'%3E%3Crect fill='%23050505' width='1200' height='600'/%3E%3Ctext x='600' y='300' text-anchor='middle' fill='%23333' font-size='24'%3EFullscreen Preview - Click button above to try%3C/text%3E%3C/svg%3E"
                  alt="Fullscreen preview"
                  className="w-full rounded-lg opacity-50"
                />
                <div className="absolute inset-0 flex items-center justify-center">
                  <button
                    onClick={() => setShowFullscreen(true)}
                    className="flex items-center gap-2 px-6 py-3 bg-white/10 hover:bg-white/20 backdrop-blur-md rounded-xl text-white font-medium transition-colors border border-white/20"
                  >
                    <Play className="w-5 h-5" />
                    Launch Fullscreen Demo
                  </button>
                </div>
              </div>
              
              <div className="mt-4 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
                <p className="text-sm text-emerald-400">
                  <strong>Best for:</strong> Focused trading sessions, power users, when you need maximum screen real estate for the conversation.
                </p>
              </div>
            </section>
            
            {/* Option B: Dashboard Integrated */}
            <section>
              <div className="mb-4">
                <h2 className="text-xl font-bold text-violet-400">Option B: Dashboard Integrated</h2>
                <p className="text-sm text-zinc-500 mt-1">
                  Team Brain stays in the dashboard grid. Always visible alongside other panels.
                  More context at a glance.
                </p>
              </div>
              
              {/* Mock Dashboard Layout */}
              <div className="grid grid-cols-12 gap-4 p-4 bg-zinc-900/30 rounded-xl border border-white/10">
                <div className="col-span-7">
                  <DashboardIntegrated />
                </div>
                <div className="col-span-5 space-y-4">
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 h-40">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Setups We're Watching</p>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center p-2 rounded bg-black/30">
                        <span className="font-bold">AAPL</span>
                        <span className="text-xs text-amber-400">Near Entry</span>
                      </div>
                      <div className="flex justify-between items-center p-2 rounded bg-black/30">
                        <span className="font-bold">GOOGL</span>
                        <span className="text-xs text-zinc-500">Watching</span>
                      </div>
                    </div>
                  </div>
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 h-40">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Our Performance Today</p>
                    <div className="flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-emerald-400">+$847</span>
                      <span className="text-sm text-zinc-500">67% win rate</span>
                    </div>
                  </div>
                  <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4 h-24">
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Market Regime</p>
                    <span className="px-3 py-1 bg-emerald-500/20 text-emerald-400 rounded-full text-sm font-medium">RISK_ON</span>
                  </div>
                </div>
              </div>
              
              <div className="mt-4 p-4 bg-violet-500/10 border border-violet-500/20 rounded-xl">
                <p className="text-sm text-violet-400">
                  <strong>Best for:</strong> Multi-tasking traders, keeping an eye on multiple data sources, quick glances between charts.
                </p>
              </div>
            </section>
          </div>
        )}
        
        {activeSection === 'actions' && (
          <div className="space-y-8">
            <div className="text-center mb-8">
              <h2 className="text-xl font-bold">Quick Action Placement Options</h2>
              <p className="text-sm text-zinc-500 mt-1">
                Where should command shortcuts (/briefme, /scan, etc.) appear?
              </p>
            </div>
            
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Option A */}
              <div>
                <QuickActionsAlwaysVisible />
                <div className="mt-3 p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
                  <p className="text-xs text-cyan-400">
                    <strong>Pros:</strong> Discoverable, always accessible<br/>
                    <strong>Cons:</strong> Takes vertical space
                  </p>
                </div>
              </div>
              
              {/* Option B */}
              <div>
                <QuickActionsOnFocus />
                <div className="mt-3 p-3 bg-violet-500/10 border border-violet-500/20 rounded-lg">
                  <p className="text-xs text-violet-400">
                    <strong>Pros:</strong> Clean when not typing, contextual<br/>
                    <strong>Cons:</strong> Hidden until focused
                  </p>
                </div>
              </div>
              
              {/* Option C */}
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
