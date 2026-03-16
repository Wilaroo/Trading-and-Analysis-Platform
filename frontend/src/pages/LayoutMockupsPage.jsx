/**
 * SentCom Layout Mockups - Visual Preview
 * Shows 4 different layout options for the Stream/Chat split
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  MessageSquare, Activity, Radio, Eye, Zap, TrendingUp, TrendingDown,
  Shield, Bell, Target, Clock, ChevronRight, Send, Layers, Layout,
  Monitor, GitBranch
} from 'lucide-react';

// Sample data for mockups
const sampleLogs = [
  { time: '10:42:15', icon: '🔍', text: 'Scanning 228 liquid symbols...' },
  { time: '10:42:18', icon: '📊', text: 'GNW @ $8.06 ▼0.08%' },
  { time: '10:42:20', icon: '⚡', text: 'Found setup: NVDA momentum_breakout' },
  { time: '10:42:22', icon: '🎯', text: 'Risk adjusted → 1.1x based on VIX' },
  { time: '10:42:25', icon: '📈', text: 'VIX down 10.7% - RISK_ON signal' },
  { time: '10:42:28', icon: '👁️', text: 'Monitoring PD stop @ $15.80' },
  { time: '10:42:30', icon: '🔄', text: 'Breadth improving: 58% > 20MA' },
  { time: '10:42:33', icon: '✅', text: 'AAPL cleared for entry zone' },
];

const sampleChat = [
  { role: 'user', text: 'What do you think about NVDA?' },
  { role: 'ai', text: 'NVDA looks strong. Momentum is building above VWAP with increasing volume. The setup score is 8.2/10. I\'d consider an entry near $142 with a stop at $138.' },
  { role: 'user', text: 'Should we add to the position?' },
  { role: 'ai', text: 'Given current risk levels (1.1x) and the RISK_ON regime, adding makes sense. I\'d suggest a half-size add to manage exposure.' },
];

// ==================== OPTION 1: NEURAL SPLIT ====================
const NeuralSplitLayout = () => (
  <div className="h-[500px] rounded-2xl overflow-hidden border border-white/10 grid grid-cols-12">
    {/* Chat Area - 65% */}
    <div className="col-span-8 bg-[#0F1419] flex flex-col">
      <div className="p-3 border-b border-white/10 flex items-center gap-2">
        <MessageSquare className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-medium text-white">Conversation</span>
      </div>
      <div className="flex-1 p-4 space-y-4 overflow-y-auto">
        {sampleChat.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] p-3 rounded-2xl ${
              msg.role === 'user' 
                ? 'bg-cyan-500/20 border border-cyan-500/30 text-cyan-100' 
                : 'bg-white/5 border border-white/10 text-zinc-300'
            }`}>
              <p className="text-sm">{msg.text}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="p-3 border-t border-white/10">
        <div className="flex items-center gap-2 bg-white/5 rounded-xl px-4 py-2">
          <input 
            type="text" 
            placeholder="Talk to the team..." 
            className="flex-1 bg-transparent text-sm text-white placeholder-zinc-500 outline-none"
          />
          <Send className="w-4 h-4 text-cyan-400" />
        </div>
      </div>
    </div>
    
    {/* Stream Area - 35% Terminal Style */}
    <div className="col-span-4 bg-[#050505] border-l border-white/10 flex flex-col">
      <div className="p-3 border-b border-white/10 flex items-center gap-2">
        <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
        <span className="text-xs font-mono text-emerald-400 uppercase tracking-wider">System Pulse</span>
      </div>
      <div className="flex-1 p-2 overflow-y-auto font-mono text-[11px]">
        {sampleLogs.map((log, i) => (
          <div key={i} className="py-1.5 border-b border-white/5 flex items-start gap-2">
            <span className="text-zinc-600">{log.time}</span>
            <span>{log.icon}</span>
            <span className="text-zinc-400">{log.text}</span>
          </div>
        ))}
      </div>
    </div>
  </div>
);

// ==================== OPTION 2: PERIPHERAL HUD ====================
const PeripheralHUDLayout = () => {
  const [alerts] = useState([
    { icon: Zap, text: 'Risk → 1.1x', color: 'amber' },
    { icon: Target, text: 'NVDA Setup', color: 'emerald' },
  ]);
  
  return (
    <div className="h-[500px] rounded-2xl overflow-hidden border border-white/10 bg-[#0F1419] relative flex flex-col">
      {/* Glowing border based on state */}
      <div className="absolute inset-0 rounded-2xl border-2 border-emerald-500/20 pointer-events-none" />
      
      {/* Main Chat Area - Center Stage */}
      <div className="flex-1 p-6 overflow-y-auto">
        <div className="max-w-2xl mx-auto space-y-4">
          {sampleChat.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] p-4 rounded-2xl ${
                msg.role === 'user' 
                  ? 'bg-cyan-500/20 border border-cyan-500/30 text-cyan-100' 
                  : 'bg-white/5 border border-white/10 text-zinc-300'
              }`}>
                <p className="text-sm leading-relaxed">{msg.text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      
      {/* Floating Alerts - Right Edge */}
      <div className="absolute right-4 bottom-24 flex flex-col gap-2 pointer-events-none">
        {alerts.map((alert, i) => (
          <motion.div
            key={i}
            initial={{ x: 100, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ delay: i * 0.2 }}
            className={`px-3 py-2 rounded-lg backdrop-blur-xl border flex items-center gap-2 ${
              alert.color === 'amber' 
                ? 'bg-amber-500/20 border-amber-500/30 text-amber-400' 
                : 'bg-emerald-500/20 border-emerald-500/30 text-emerald-400'
            }`}
          >
            <alert.icon className="w-4 h-4" />
            <span className="text-xs font-medium">{alert.text}</span>
          </motion.div>
        ))}
      </div>
      
      {/* Ticker Tape - Bottom */}
      <div className="h-8 bg-black/80 border-t border-white/10 flex items-center overflow-hidden">
        <div className="animate-marquee whitespace-nowrap font-mono text-[10px] text-cyan-500/70">
          <span className="mx-4">🔍 scanning SPY...</span>
          <span className="mx-4">📊 GNW -0.08%</span>
          <span className="mx-4">⚡ risk 1.1x</span>
          <span className="mx-4">📈 VIX ▼10.7%</span>
          <span className="mx-4">🎯 NVDA setup active</span>
          <span className="mx-4">✅ breadth improving</span>
          <span className="mx-4">🔍 scanning SPY...</span>
          <span className="mx-4">📊 GNW -0.08%</span>
        </div>
      </div>
      
      {/* Chat Input */}
      <div className="p-4 border-t border-white/10">
        <div className="max-w-2xl mx-auto flex items-center gap-2 bg-white/5 rounded-xl px-4 py-3">
          <input 
            type="text" 
            placeholder="Talk to the team..." 
            className="flex-1 bg-transparent text-sm text-white placeholder-zinc-500 outline-none"
          />
          <Send className="w-4 h-4 text-cyan-400" />
        </div>
      </div>
    </div>
  );
};

// ==================== OPTION 3: Z-AXIS STACK ====================
const ZAxisStackLayout = () => {
  const [monitorMode, setMonitorMode] = useState(false);
  
  return (
    <div className="h-[500px] rounded-2xl overflow-hidden border border-white/10 bg-black relative">
      {/* Background Stream Layer */}
      <div className={`absolute inset-0 p-6 font-mono text-xs overflow-hidden transition-opacity duration-300 ${
        monitorMode ? 'opacity-60' : 'opacity-20'
      }`}>
        <div className="space-y-2 text-zinc-600">
          {[...sampleLogs, ...sampleLogs].map((log, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="text-zinc-700">{log.time}</span>
              <span className={monitorMode ? 'text-cyan-600' : ''}>{log.text}</span>
            </div>
          ))}
        </div>
      </div>
      
      {/* Foreground Chat Layer */}
      <div className={`absolute inset-4 md:inset-8 rounded-2xl border border-white/10 flex flex-col overflow-hidden transition-all duration-300 ${
        monitorMode 
          ? 'bg-black/60 backdrop-blur-sm' 
          : 'bg-black/90 backdrop-blur-xl'
      }`}>
        <div className="p-3 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-cyan-400" />
            <span className="text-sm font-medium text-white">Conversation</span>
          </div>
          <button 
            onClick={() => setMonitorMode(!monitorMode)}
            className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
              monitorMode 
                ? 'bg-cyan-500/20 text-cyan-400' 
                : 'bg-white/5 text-zinc-400 hover:text-white'
            }`}
          >
            {monitorMode ? 'MONITOR ON' : 'MONITOR OFF'}
          </button>
        </div>
        
        <div className="flex-1 p-4 space-y-4 overflow-y-auto">
          {sampleChat.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] p-3 rounded-2xl ${
                msg.role === 'user' 
                  ? 'bg-cyan-500/20 border border-cyan-500/30 text-cyan-100' 
                  : 'bg-white/5 border border-white/10 text-zinc-300'
              }`}>
                <p className="text-sm">{msg.text}</p>
              </div>
            </div>
          ))}
        </div>
        
        <div className="p-3 border-t border-white/10">
          <div className="flex items-center gap-2 bg-white/5 rounded-xl px-4 py-2">
            <input 
              type="text" 
              placeholder="Talk to the team..." 
              className="flex-1 bg-transparent text-sm text-white placeholder-zinc-500 outline-none"
            />
            <Send className="w-4 h-4 text-cyan-400" />
          </div>
        </div>
      </div>
    </div>
  );
};

// ==================== OPTION 4: TIMELINE MERGE ====================
const TimelineMergeLayout = () => {
  const timelineItems = [
    { type: 'log', time: '10:42:15', text: 'Scanning sector...' },
    { type: 'chat', role: 'user', time: '10:42:16', text: 'What\'s the play today?' },
    { type: 'log', time: '10:42:18', text: 'Found NVDA setup' },
    { type: 'log', time: '10:42:20', text: 'Risk calc: 1.2x' },
    { type: 'chat', role: 'ai', time: '10:42:21', text: 'NVDA is looking strong for a momentum play. Setup score 8.2/10.' },
    { type: 'log', time: '10:42:25', text: 'Stop placed $145' },
    { type: 'chat', role: 'user', time: '10:42:28', text: 'Let\'s do it.' },
    { type: 'log', time: '10:42:30', text: 'Order submitted ✓' },
    { type: 'chat', role: 'ai', time: '10:42:31', text: 'Entry order placed. I\'ll monitor and adjust the stop as needed.' },
  ];
  
  return (
    <div className="h-[500px] rounded-2xl overflow-hidden border border-white/10 bg-[#0F1419] flex flex-col">
      <div className="p-3 border-b border-white/10 flex items-center justify-center gap-4">
        <span className="text-xs font-mono text-zinc-500 uppercase">System Logs</span>
        <GitBranch className="w-4 h-4 text-cyan-500" />
        <span className="text-xs font-medium text-white uppercase">Conversation</span>
      </div>
      
      <div className="flex-1 overflow-y-auto relative">
        {/* Center Timeline Axis */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gradient-to-b from-transparent via-cyan-500/30 to-transparent transform -translate-x-1/2" />
        
        <div className="p-4 space-y-3">
          {timelineItems.map((item, i) => (
            <div key={i} className="flex items-start">
              {item.type === 'log' ? (
                <>
                  {/* Log on Left */}
                  <div className="w-[45%] pr-4 text-right">
                    <div className="inline-block p-2 rounded-lg bg-black/40 border border-white/5">
                      <span className="font-mono text-[10px] text-zinc-600 block">{item.time}</span>
                      <span className="font-mono text-xs text-zinc-400">{item.text}</span>
                    </div>
                  </div>
                  {/* Timeline dot */}
                  <div className="w-[10%] flex justify-center">
                    <div className="w-2 h-2 rounded-full bg-zinc-600 mt-2" />
                  </div>
                  <div className="w-[45%]" />
                </>
              ) : (
                <>
                  <div className="w-[45%]" />
                  {/* Timeline dot */}
                  <div className="w-[10%] flex justify-center">
                    <div className={`w-2 h-2 rounded-full mt-2 ${
                      item.role === 'user' ? 'bg-cyan-500' : 'bg-emerald-500'
                    }`} />
                  </div>
                  {/* Chat on Right */}
                  <div className="w-[45%] pl-4">
                    <div className={`p-3 rounded-xl ${
                      item.role === 'user'
                        ? 'bg-cyan-500/20 border border-cyan-500/30'
                        : 'bg-white/5 border border-white/10'
                    }`}>
                      <span className="text-[10px] text-zinc-500 block mb-1">
                        {item.role === 'user' ? 'YOU' : 'SENTCOM'} • {item.time}
                      </span>
                      <p className="text-sm text-zinc-300">{item.text}</p>
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
      
      <div className="p-3 border-t border-white/10">
        <div className="flex items-center gap-2 bg-white/5 rounded-xl px-4 py-2">
          <input 
            type="text" 
            placeholder="Talk to the team..." 
            className="flex-1 bg-transparent text-sm text-white placeholder-zinc-500 outline-none"
          />
          <Send className="w-4 h-4 text-cyan-400" />
        </div>
      </div>
    </div>
  );
};

// ==================== MAIN MOCKUP PAGE ====================
const LayoutMockupsPage = () => {
  const [activeOption, setActiveOption] = useState(1);
  
  const options = [
    { id: 1, name: 'Neural Split', icon: Layout, desc: 'Side-by-side with terminal stream' },
    { id: 2, name: 'Peripheral HUD', icon: Monitor, desc: 'Ambient alerts + ticker tape' },
    { id: 3, name: 'Z-Axis Stack', icon: Layers, desc: 'Layered with toggle focus' },
    { id: 4, name: 'Timeline Merge', icon: GitBranch, desc: 'Chronological cause & effect' },
  ];
  
  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">SentCom Layout Options</h1>
        <p className="text-zinc-400 mb-8">Stream of Consciousness + Conversation Split</p>
        
        {/* Option Tabs */}
        <div className="flex gap-2 mb-8 flex-wrap">
          {options.map((opt) => (
            <button
              key={opt.id}
              onClick={() => setActiveOption(opt.id)}
              className={`px-4 py-3 rounded-xl flex items-center gap-3 transition-all ${
                activeOption === opt.id
                  ? 'bg-cyan-500/20 border border-cyan-500/30 text-cyan-400'
                  : 'bg-white/5 border border-white/10 text-zinc-400 hover:text-white hover:border-white/20'
              }`}
            >
              <opt.icon className="w-5 h-5" />
              <div className="text-left">
                <div className="font-medium text-sm">{opt.name}</div>
                <div className="text-[10px] opacity-70">{opt.desc}</div>
              </div>
            </button>
          ))}
        </div>
        
        {/* Active Mockup */}
        <div className="mb-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeOption}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
            >
              {activeOption === 1 && <NeuralSplitLayout />}
              {activeOption === 2 && <PeripheralHUDLayout />}
              {activeOption === 3 && <ZAxisStackLayout />}
              {activeOption === 4 && <TimelineMergeLayout />}
            </motion.div>
          </AnimatePresence>
        </div>
        
        {/* Option Details */}
        <div className="grid grid-cols-2 gap-6">
          <div className="p-4 rounded-xl bg-white/5 border border-white/10">
            <h3 className="font-medium text-emerald-400 mb-2">✅ Pros</h3>
            <ul className="text-sm text-zinc-400 space-y-1">
              {activeOption === 1 && (
                <>
                  <li>• Clear visual separation</li>
                  <li>• Easy to implement</li>
                  <li>• Professional terminal aesthetic</li>
                  <li>• No flickering in chat area</li>
                </>
              )}
              {activeOption === 2 && (
                <>
                  <li>• Maximum focus on conversation</li>
                  <li>• Alerts catch peripheral vision</li>
                  <li>• Clean, minimal interface</li>
                  <li>• Immersive experience</li>
                </>
              )}
              {activeOption === 3 && (
                <>
                  <li>• Compact for small screens</li>
                  <li>• Cool "Matrix" aesthetic</li>
                  <li>• Toggle between modes</li>
                  <li>• Gamified interaction</li>
                </>
              )}
              {activeOption === 4 && (
                <>
                  <li>• See cause and effect clearly</li>
                  <li>• Great for debugging</li>
                  <li>• Audit trail built-in</li>
                  <li>• Chronological context</li>
                </>
              )}
            </ul>
          </div>
          
          <div className="p-4 rounded-xl bg-white/5 border border-white/10">
            <h3 className="font-medium text-rose-400 mb-2">⚠️ Considerations</h3>
            <ul className="text-sm text-zinc-400 space-y-1">
              {activeOption === 1 && (
                <>
                  <li>• Requires more screen width</li>
                  <li>• Stream may feel separate</li>
                  <li>• Less immersive</li>
                </>
              )}
              {activeOption === 2 && (
                <>
                  <li>• May miss important logs</li>
                  <li>• Ticker can be distracting</li>
                  <li>• More complex to implement</li>
                </>
              )}
              {activeOption === 3 && (
                <>
                  <li>• Requires user to toggle</li>
                  <li>• Can feel cluttered in monitor mode</li>
                  <li>• Learning curve</li>
                </>
              )}
              {activeOption === 4 && (
                <>
                  <li>• Can get long quickly</li>
                  <li>• Mixes log noise with chat</li>
                  <li>• May need filtering</li>
                </>
              )}
            </ul>
          </div>
        </div>
      </div>
      
      {/* Marquee Animation Styles */}
      <style>{`
        @keyframes marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .animate-marquee {
          animation: marquee 20s linear infinite;
        }
      `}</style>
    </div>
  );
};

export default LayoutMockupsPage;
