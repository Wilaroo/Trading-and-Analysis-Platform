/**
 * ConversationPanel.jsx - User Chat Interface
 * 
 * Clean chat interface for user-AI dialogue, separate from the 
 * Stream of Consciousness. This is the right side of the Neural Split layout.
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, MessageSquare, Loader, Gauge, 
  BarChart3, Newspaper, Sunrise, BookOpen, TrendingUp,
  Target, X, Sparkles
} from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// Format timestamp to relative time
const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '';
  
  const now = new Date();
  const time = new Date(timestamp);
  const diffMs = now - time;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  
  if (diffSecs < 10) return 'Just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  
  return time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
};

// Typing Indicator Component
const TypingIndicator = () => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -10 }}
    className="flex items-start gap-3"
  >
    <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center flex-shrink-0 shadow-lg">
      <Brain className="w-4 h-4 text-white" />
    </div>
    <div className="flex-1 max-w-[80%]">
      <div className="rounded-2xl rounded-tl-sm p-3 bg-gradient-to-br from-violet-500/10 to-purple-500/5 border border-violet-500/20">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[12px] font-bold uppercase tracking-wider text-violet-400">SENTCOM</span>
        </div>
        <div className="flex items-center gap-1.5">
          <motion.span
            className="w-2 h-2 rounded-full bg-violet-400"
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
          />
          <motion.span
            className="w-2 h-2 rounded-full bg-violet-400"
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: 0.2 }}
          />
          <motion.span
            className="w-2 h-2 rounded-full bg-violet-400"
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
          />
          <span className="text-xs text-violet-300/70 ml-1">thinking...</span>
        </div>
      </div>
    </div>
  </motion.div>
);

// Individual Chat Message Component
const ChatMessage = React.memo(({ message, index }) => {
  const isUser = message.metadata?.role === 'user' || message.action_type === 'user_message';
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: Math.min(index * 0.05, 0.3), type: 'spring', stiffness: 200 }}
      className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
      data-testid={`chat-message-${index}`}
    >
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg ${
        isUser 
          ? 'bg-gradient-to-br from-cyan-500 to-blue-500' 
          : 'bg-gradient-to-br from-violet-500 to-purple-600'
      }`}>
        {isUser ? (
          <MessageSquare className="w-4 h-4 text-white" />
        ) : (
          <Brain className="w-4 h-4 text-white" />
        )}
      </div>
      
      {/* Message Bubble */}
      <div className={`flex-1 min-w-0 max-w-[80%] ${isUser ? 'text-right' : ''}`}>
        <div className={`
          relative overflow-hidden rounded-2xl p-3.5
          ${isUser 
            ? 'rounded-tr-sm bg-gradient-to-br from-cyan-500/15 to-blue-500/10 border border-cyan-500/25' 
            : 'rounded-tl-sm bg-gradient-to-br from-violet-500/10 to-purple-500/5 border border-violet-500/20'
          }
        `}>
          {/* Header */}
          <div className={`flex items-center gap-2 mb-1.5 ${isUser ? 'justify-end' : ''}`}>
            <span className={`text-[12px] font-bold uppercase tracking-wider ${
              isUser ? 'text-cyan-400' : 'text-violet-400'
            }`}>
              {isUser ? 'YOU' : 'SENTCOM'}
            </span>
            <span className="text-[11px] text-zinc-500">
              {formatRelativeTime(message.timestamp)}
            </span>
          </div>
          
          {/* Content */}
          <p className={`text-sm leading-relaxed ${isUser ? 'text-cyan-100' : 'text-zinc-200'}`}>
            {message.content}
          </p>
          
          {/* Confidence indicator for AI messages */}
          {!isUser && message.confidence && (
            <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-white/10">
              <Gauge className="w-3 h-3 text-violet-400" />
              <span className="text-[12px] text-violet-400">
                Confidence: {message.confidence}%
              </span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
});

ChatMessage.displayName = 'ChatMessage';

// Quick Action Buttons
const QuickActions = ({ onAction, loading }) => {
  const actions = [
    { id: 'performance', icon: BarChart3, label: 'Performance', color: 'emerald',
      prompt: "Analyze our trading performance. What's our win rate, profit factor, and what are our strengths and weaknesses?" },
    { id: 'news', icon: Newspaper, label: 'News', color: 'cyan',
      prompt: "What's happening in the market today? Give us the key headlines and themes." },
    { id: 'morning', icon: Sunrise, label: 'Brief', color: 'amber',
      endpoint: '/api/assistant/coach/morning-briefing' },
    { id: 'rules', icon: BookOpen, label: 'Rules', color: 'violet',
      endpoint: '/api/assistant/coach/rule-reminder' },
    { id: 'summary', icon: TrendingUp, label: 'Summary', color: 'purple',
      endpoint: '/api/assistant/coach/daily-summary' },
  ];

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {actions.map((action) => {
        const Icon = action.icon;
        const isLoading = loading === action.id;
        return (
          <button
            key={action.id}
            onClick={() => onAction(action)}
            disabled={isLoading}
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[12px] font-medium transition-all border
              ${isLoading ? 'opacity-50' : 'hover:scale-105'}
              ${action.color === 'emerald' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
                action.color === 'cyan' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400' :
                action.color === 'amber' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' :
                action.color === 'violet' ? 'bg-violet-500/10 border-violet-500/30 text-violet-400' :
                'bg-purple-500/10 border-purple-500/30 text-purple-400'
              }`}
            data-testid={`quick-action-${action.id}`}
          >
            {isLoading ? <Loader className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
            {action.label}
          </button>
        );
      })}
    </div>
  );
};

// Check Trade Form
const CheckTradeForm = ({ onSubmit, loading, onClose }) => {
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState('BUY');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!symbol.trim()) {
      toast.error('Enter a symbol');
      return;
    }
    onSubmit({
      symbol: symbol.toUpperCase(),
      action,
      entry_price: parseFloat(entryPrice) || null,
      stop_loss: parseFloat(stopLoss) || null
    });
    setSymbol('');
    setEntryPrice('');
    setStopLoss('');
    onClose?.();
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="bg-black/40 rounded-xl p-3 border border-white/10 mb-3"
    >
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-medium text-white flex items-center gap-1.5">
          <Target className="w-3.5 h-3.5 text-cyan-400" />
          Check Our Trade
        </h4>
        <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
          <X className="w-3.5 h-3.5 text-zinc-400" />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="Symbol"
            className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
            data-testid="check-trade-symbol"
          />
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-xs focus:outline-none focus:border-cyan-500/50"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <div className="flex gap-2">
          <input
            type="number"
            step="0.01"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder="Entry $"
            className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
          <input
            type="number"
            step="0.01"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
            placeholder="Stop $"
            className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full px-3 py-1.5 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-lg text-white text-xs font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {loading ? 'Checking...' : 'Check This Trade'}
        </button>
      </form>
    </motion.div>
  );
};

// Main Conversation Panel Component - Memoized to prevent flickering
const ConversationPanel = React.memo(({ 
  messages = [], 
  onSendMessage, 
  onQuickAction,
  onCheckTrade,
  loading = false,
  quickActionLoading = null,
  className = '' 
}) => {
  const [inputValue, setInputValue] = useState('');
  const [showTradeForm, setShowTradeForm] = useState(false);
  const scrollRef = useRef(null);
  const prevMessagesLengthRef = useRef(messages.length);
  
  // Only auto-scroll when new messages are added, not on every render
  useEffect(() => {
    if (scrollRef.current && messages.length > prevMessagesLengthRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevMessagesLengthRef.current = messages.length;
  }, [messages.length]);
  
  // Also scroll when loading changes to true (user sent message)
  useEffect(() => {
    if (loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [loading]);
  
  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    if (!inputValue.trim() || loading) return;
    onSendMessage(inputValue);
    setInputValue('');
  }, [inputValue, loading, onSendMessage]);
  
  // Messages are already filtered by parent - use directly
  const chatMessages = messages;
  
  return (
    <div className={`flex flex-col h-full bg-[#0F1419] overflow-hidden ${className}`} data-testid="conversation-panel">
      {/* Header - 44px */}
      <div className="h-11 flex-shrink-0 flex items-center gap-2 px-4 border-b border-white/10">
        <MessageSquare className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-medium text-white" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Conversation</span>
        <span className="text-[12px] text-zinc-500 ml-auto">Chat with SentCom</span>
      </div>
      
      {/* Messages Area - Fills remaining space above input */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar min-h-0"
        data-testid="conversation-messages"
      >
        {chatMessages.length === 0 ? (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <div className="text-center">
              <Sparkles className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-sm text-zinc-400" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Start a conversation</p>
              <p className="text-xs text-zinc-500 mt-1">Ask questions or discuss strategy</p>
            </div>
          </div>
        ) : (
          <>
            {chatMessages.map((msg, i) => (
              <ChatMessage key={msg.id || `msg-${i}`} message={msg} index={i} />
            ))}
            <AnimatePresence>
              {loading && <TypingIndicator />}
            </AnimatePresence>
          </>
        )}
      </div>
      
      {/* Input Area - Always visible at bottom */}
      <div className="flex-shrink-0 p-2 border-t border-white/10 bg-[#0a0e12]">
        {/* Quick Actions - Scrollable row */}
        <div className="flex items-center gap-1.5 mb-2 overflow-x-auto custom-scrollbar">
          <QuickActions onAction={onQuickAction} loading={quickActionLoading} />
          <button
            onClick={() => setShowTradeForm(!showTradeForm)}
            className={`flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-[12px] font-medium transition-all border
              ${showTradeForm 
                ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-400' 
                : 'bg-zinc-800/50 border-white/10 text-zinc-400 hover:border-cyan-500/30'
              }`}
            data-testid="check-trade-toggle"
          >
            <Target className="w-3 h-3" />
            Trade
          </button>
        </div>
        
        {/* Check Trade Form */}
        <AnimatePresence>
          {showTradeForm && (
            <CheckTradeForm 
              onSubmit={onCheckTrade}
              loading={quickActionLoading === 'checkTrade'}
              onClose={() => setShowTradeForm(false)}
            />
          )}
        </AnimatePresence>
        
        {/* Chat Input */}
        <form onSubmit={handleSubmit} className="relative">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Talk to the team..."
            disabled={loading}
            className="w-full bg-white/5 border border-white/10 rounded-lg pl-3 pr-10 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50 focus:bg-white/10 transition-all disabled:opacity-50"
            style={{ fontFamily: "'Space Grotesk', sans-serif" }}
            data-testid="conversation-input"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || loading}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 rounded-md bg-gradient-to-r from-cyan-500 to-cyan-600 text-white shadow-lg shadow-cyan-500/30 hover:shadow-cyan-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="conversation-send-btn"
          >
            {loading ? <Loader className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>
    </div>
  );
});

export default ConversationPanel;
