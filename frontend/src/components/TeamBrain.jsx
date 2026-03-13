import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Cpu, User, Sparkles, Clock, Zap, Target, 
  AlertCircle, ArrowRight, CheckCircle, Loader, Shield, 
  Maximize2, Minimize2, MessageSquare, Terminal, Activity
} from 'lucide-react';
import { toast } from 'sonner';

// --- Sub-components for Team Brain ---

const UnifiedStreamItem = ({ item, index }) => {
  const isUser = item.role === 'user';
  const isSystem = item.role === 'system' || item.type === 'thought';
  const isAssistant = item.role === 'assistant';

  // Base animation
  const variants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0 }
  };

  if (isUser) {
    return (
      <motion.div 
        variants={variants}
        initial="hidden"
        animate="visible"
        className="flex justify-end mb-4"
      >
        <div className="flex items-end gap-2 max-w-[80%]">
          <div className="bg-cyan-500/10 border border-cyan-500/20 text-cyan-50 rounded-2xl rounded-br-none px-4 py-2.5">
            <p className="text-sm">{item.content}</p>
          </div>
          <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center flex-shrink-0">
            <User className="w-3.5 h-3.5 text-cyan-400" />
          </div>
        </div>
      </motion.div>
    );
  }

  if (isSystem) {
    // Styling for thoughts/alerts/system logs
    const getTypeStyles = () => {
      switch (item.action_type) {
        case 'stop_warning': return 'border-red-500/50 bg-red-500/5';
        case 'entry': return 'border-emerald-500/50 bg-emerald-500/5';
        case 'exit': return 'border-amber-500/50 bg-amber-500/5';
        case 'scanning': return 'border-cyan-500/30 bg-cyan-500/5';
        default: return 'border-white/10 bg-zinc-900/50';
      }
    };

    return (
      <motion.div 
        variants={variants}
        initial="hidden"
        animate="visible"
        className="flex mb-3"
      >
        <div className={`w-full border-l-2 ${getTypeStyles()} pl-3 py-1`}>
          <div className="flex items-center gap-2 mb-1">
            <Terminal className="w-3 h-3 text-zinc-500" />
            <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">
              {item.action_type || 'SYSTEM'}
            </span>
            <span className="text-[10px] text-zinc-600">
              {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          </div>
          <p className="text-xs font-mono text-zinc-300 leading-relaxed">
            {item.content || item.text}
          </p>
        </div>
      </motion.div>
    );
  }

  // Assistant (The "Team" Voice)
  return (
    <motion.div 
      variants={variants}
      initial="hidden"
      animate="visible"
      className="flex justify-start mb-4"
    >
      <div className="flex items-end gap-2 max-w-[85%]">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center flex-shrink-0">
          <Brain className="w-3.5 h-3.5 text-violet-400" />
        </div>
        <div className="bg-zinc-800/80 border border-white/10 text-zinc-200 rounded-2xl rounded-bl-none px-4 py-2.5">
           <p className="text-sm leading-relaxed">{item.content}</p>
        </div>
      </div>
    </motion.div>
  );
};

const OrderPipelineCompact = ({ orderQueue }) => {
  const pending = orderQueue?.pending || 0;
  const executing = orderQueue?.executing || 0;
  const completed = orderQueue?.completed || 0;

  return (
    <div className="flex items-center gap-2 text-[10px] font-mono bg-black/40 px-2 py-1 rounded-lg border border-white/5">
      <div className={`flex items-center gap-1 ${pending > 0 ? 'text-amber-400' : 'text-zinc-600'}`}>
        <span>{pending}</span>
        <span>PND</span>
      </div>
      <div className="w-px h-3 bg-white/10" />
      <div className={`flex items-center gap-1 ${executing > 0 ? 'text-cyan-400 animate-pulse' : 'text-zinc-600'}`}>
        <span>{executing}</span>
        <span>EXE</span>
      </div>
      <div className="w-px h-3 bg-white/10" />
      <div className={`flex items-center gap-1 ${completed > 0 ? 'text-emerald-400' : 'text-zinc-600'}`}>
        <span>{completed}</span>
        <span>FIL</span>
      </div>
    </div>
  );
};

// --- Main Component ---

const TeamBrain = ({ 
  className = '', 
  initialMode = 'compact', // 'compact' | 'expanded'
  botStatus, 
  orderQueue,
  activeTrades = [],
  onTickerClick
}) => {
  const [mode, setMode] = useState(initialMode);
  const [input, setInput] = useState('');
  const [stream, setStream] = useState([]); // Unified stream of thoughts + chat
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef(null);

  // Mock initial data load (Replace with actual API hooks)
  useEffect(() => {
    // Add initial welcome message
    setStream([
      {
        id: 'welcome',
        role: 'assistant',
        content: "Team Brain online. We are monitoring the market and ready for orders.",
        timestamp: new Date().toISOString()
      }
    ]);

    // Simulate incoming bot thoughts (Polling mock)
    const interval = setInterval(() => {
      const randomThought = Math.random() > 0.7;
      if (randomThought) {
        const thoughtTypes = ['scanning', 'monitoring', 'stop_warning'];
        const type = thoughtTypes[Math.floor(Math.random() * thoughtTypes.length)];
        
        const newThought = {
          id: Date.now(),
          role: 'system',
          type: 'thought',
          action_type: type,
          content: type === 'scanning' ? "Scanning: Volatility spike in tech sector detected." : 
                   type === 'monitoring' ? "Monitoring: NVDA approaching key resistance level." :
                   "Alert: Stop loss distance on TSLA tightened due to low volatility.",
          timestamp: new Date().toISOString()
        };
        
        setStream(prev => [...prev, newThought]);
      }
    }, 8000);

    return () => clearInterval(interval);
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [stream]);

  const handleSend = async () => {
    if (!input.trim()) return;

    // Add User Message
    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: input,
      timestamp: new Date().toISOString()
    };
    setStream(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    // Simulate AI Processing
    setTimeout(() => {
      setIsTyping(false);
      const aiMsg = {
        id: Date.now() + 1,
        role: 'assistant',
        content: "Understood. We're analyzing that ticker now. Our models suggest a bullish divergence on the 15m timeframe.",
        timestamp: new Date().toISOString()
      };
      setStream(prev => [...prev, aiMsg]);
    }, 1500);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div 
      className={`flex flex-col bg-zinc-950 border border-white/10 rounded-xl overflow-hidden shadow-2xl ${className} ${mode === 'expanded' ? 'fixed inset-4 z-50' : 'h-[600px]'}`}
      data-testid="team-brain-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-zinc-900/50 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-violet-500/20 flex items-center justify-center border border-white/5">
            <Brain className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">TEAM BRAIN</h2>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[10px] text-zinc-500">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                ONLINE
              </span>
              <span className="text-[10px] text-zinc-600">|</span>
              <span className="text-[10px] text-zinc-500 uppercase">{botStatus?.regime || 'NEUTRAL'}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <OrderPipelineCompact orderQueue={orderQueue} />
          
          <button 
            onClick={() => setMode(mode === 'compact' ? 'expanded' : 'compact')}
            className="p-1.5 text-zinc-500 hover:text-white hover:bg-white/5 rounded-md transition-colors"
          >
            {mode === 'compact' ? <Maximize2 className="w-4 h-4" /> : <Minimize2 className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Stream Area */}
      <div 
        className="flex-1 overflow-y-auto p-4 space-y-2 bg-gradient-to-b from-transparent to-black/20"
        ref={scrollRef}
      >
        <AnimatePresence initial={false}>
          {stream.map((item, index) => (
            <UnifiedStreamItem key={item.id || index} item={item} index={index} />
          ))}
        </AnimatePresence>
        
        {isTyping && (
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 text-xs text-zinc-500 ml-2"
          >
            <Loader className="w-3 h-3 animate-spin" />
            <span>Team is analyzing...</span>
          </motion.div>
        )}
      </div>

      {/* Active Alerts / Proactive Context (Sticky Bottom of Stream) */}
      {activeTrades.length > 0 && (
        <div className="px-4 py-2 bg-zinc-900/80 border-t border-white/5 backdrop-blur-sm">
           <div className="flex items-center gap-2 overflow-x-auto no-scrollbar py-1">
              {activeTrades.map(trade => (
                <button 
                  key={trade.symbol}
                  onClick={() => onTickerClick?.(trade.symbol)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-800 border border-white/5 hover:border-cyan-500/30 transition-colors flex-shrink-0"
                >
                   <span className="text-xs font-bold text-white">{trade.symbol}</span>
                   <span className={`text-[10px] font-mono ${trade.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                     {trade.pnl >= 0 ? '+' : ''}{trade.pnl}%
                   </span>
                </button>
              ))}
           </div>
        </div>
      )}

      {/* Input Area */}
      <div className="p-3 bg-zinc-900 border-t border-white/10">
        <div className="relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Command the team..."
            className="w-full bg-black/50 border border-white/10 rounded-xl pl-4 pr-12 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 transition-all font-medium"
          />
          <button 
            onClick={handleSend}
            disabled={!input.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="flex justify-between items-center mt-2 px-1">
           <div className="flex gap-2">
             <button className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors">
               /scan
             </button>
             <button className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors">
               /performance
             </button>
           </div>
           <span className="text-[10px] text-zinc-600">Press Enter to send</span>
        </div>
      </div>
    </div>
  );
};

export default TeamBrain;
