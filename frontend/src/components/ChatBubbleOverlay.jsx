/**
 * ChatBubbleOverlay.jsx - Floating Chat Bubble over SOC
 * 
 * A floating chat interface that overlays the Stream of Consciousness.
 * Minimizes to a small bubble in the bottom-right corner.
 * Shows unread badge when AI responds while minimized.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  MessageSquare, Send, X, Brain, Loader, Gauge, 
  Minimize2, ChevronDown, Sparkles, Target,
  BarChart3, Newspaper, Sunrise, BookOpen, TrendingUp
} from 'lucide-react';
import { toast } from 'sonner';

const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '';
  const now = new Date();
  const time = new Date(timestamp);
  const diffSecs = Math.floor((now - time) / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  if (diffSecs < 10) return 'Just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  return time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
};

// Chat message bubble
const ChatMessage = ({ msg }) => {
  const isUser = msg.type === 'chat' || msg.action_type === 'user_message';

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex items-start gap-2 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      <div className={`w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 ${
        isUser 
          ? 'bg-gradient-to-br from-cyan-500 to-blue-500' 
          : 'bg-gradient-to-br from-violet-500 to-purple-600'
      }`}>
        {isUser 
          ? <MessageSquare className="w-3 h-3 text-white" /> 
          : <Brain className="w-3 h-3 text-white" />}
      </div>
      <div className={`flex-1 min-w-0 max-w-[85%] ${isUser ? 'text-right' : ''}`}>
        <div className={`rounded-xl p-2.5 text-xs leading-relaxed ${
          isUser
            ? 'bg-cyan-500/15 border border-cyan-500/20 text-cyan-100 rounded-tr-sm'
            : 'bg-violet-500/10 border border-violet-500/20 text-zinc-200 rounded-tl-sm'
        }`}>
          <span className={`text-[9px] font-bold uppercase tracking-wider block mb-1 ${
            isUser ? 'text-cyan-400' : 'text-violet-400'
          }`}>
            {isUser ? 'YOU' : 'SENTCOM'}
          </span>
          <p className="whitespace-pre-wrap">{msg.content}</p>
          {msg.confidence && (
            <div className="flex items-center gap-1 mt-1.5 pt-1.5 border-t border-white/10">
              <Gauge className="w-2.5 h-2.5 text-violet-400" />
              <span className="text-[9px] text-violet-400">Confidence: {msg.confidence}%</span>
            </div>
          )}
        </div>
        <span className="text-[9px] text-zinc-600 mt-0.5 block">{formatRelativeTime(msg.timestamp)}</span>
      </div>
    </motion.div>
  );
};

// Quick action pills for the chat
const QuickActions = ({ onAction, loading }) => {
  const actions = [
    { id: 'performance', icon: BarChart3, label: 'Performance', prompt: "Analyze our trading performance. What's our win rate, profit factor, and what are our strengths and weaknesses?" },
    { id: 'news', icon: Newspaper, label: 'News', prompt: "What's happening in the market today? Key headlines and themes." },
    { id: 'morning', icon: Sunrise, label: 'Brief', endpoint: '/api/assistant/coach/morning-briefing' },
    { id: 'rules', icon: BookOpen, label: 'Rules', endpoint: '/api/assistant/coach/rule-reminder' },
    { id: 'summary', icon: TrendingUp, label: 'Summary', endpoint: '/api/assistant/coach/daily-summary' },
  ];

  return (
    <div className="flex items-center gap-1 flex-wrap px-1">
      {actions.map(a => {
        const Icon = a.icon;
        return (
          <button
            key={a.id}
            onClick={() => onAction(a)}
            disabled={loading === a.id}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-white/5 border border-white/10 text-zinc-400 hover:text-white hover:bg-white/10 transition-all"
            data-testid={`chat-quick-${a.id}`}
          >
            {loading === a.id ? <Loader className="w-2.5 h-2.5 animate-spin" /> : <Icon className="w-2.5 h-2.5" />}
            {a.label}
          </button>
        );
      })}
    </div>
  );
};

const ChatBubbleOverlay = ({ 
  messages = [], 
  onSendMessage, 
  onQuickAction,
  onCheckTrade,
  loading = false,
  quickActionLoading = null 
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [unreadCount, setUnreadCount] = useState(0);
  const scrollRef = useRef(null);
  const prevMsgCountRef = useRef(messages.length);
  const inputRef = useRef(null);

  // Track unread messages when minimized
  useEffect(() => {
    if (!isOpen && messages.length > prevMsgCountRef.current) {
      const newMsgs = messages.slice(prevMsgCountRef.current);
      const aiResponses = newMsgs.filter(m => m.action_type === 'chat_response');
      if (aiResponses.length > 0) {
        setUnreadCount(prev => prev + aiResponses.length);
      }
    }
    prevMsgCountRef.current = messages.length;
  }, [messages, isOpen]);

  // Clear unread when opening
  useEffect(() => {
    if (isOpen) {
      setUnreadCount(0);
      // Focus input when opened
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (isOpen && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  const handleSend = useCallback(() => {
    if (!input.trim() || loading) return;
    onSendMessage(input.trim());
    setInput('');
  }, [input, loading, onSendMessage]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Floating Chat Bubble */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            onClick={() => setIsOpen(true)}
            className="absolute bottom-4 right-4 z-30 w-12 h-12 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 shadow-lg shadow-violet-500/30 flex items-center justify-center hover:shadow-violet-500/50 hover:scale-105 transition-all cursor-pointer"
            data-testid="chat-bubble-btn"
          >
            <MessageSquare className="w-5 h-5 text-white" />
            {unreadCount > 0 && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center shadow-lg"
                data-testid="chat-unread-badge"
              >
                {unreadCount > 9 ? '9+' : unreadCount}
              </motion.span>
            )}
          </motion.button>
        )}
      </AnimatePresence>

      {/* Expanded Chat Window */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.9 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="absolute bottom-4 right-4 z-30 w-[360px] rounded-2xl overflow-hidden border border-white/15 shadow-2xl shadow-black/50"
            style={{ height: '420px' }}
            data-testid="chat-overlay-window"
          >
            {/* Glass background */}
            <div className="absolute inset-0 bg-zinc-900/95 backdrop-blur-xl" />
            
            <div className="relative flex flex-col h-full">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-gradient-to-r from-violet-500/10 to-purple-500/5">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                    <Brain className="w-3.5 h-3.5 text-white" />
                  </div>
                  <div>
                    <h3 className="text-xs font-bold text-white">SentCom Chat</h3>
                    <span className="text-[9px] text-zinc-500">Ask anything about your trades</span>
                  </div>
                </div>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
                  data-testid="chat-minimize-btn"
                >
                  <Minimize2 className="w-4 h-4 text-zinc-400" />
                </button>
              </div>

              {/* Quick Actions */}
              <div className="py-2 border-b border-white/5">
                <QuickActions onAction={onQuickAction} loading={quickActionLoading} />
              </div>

              {/* Messages */}
              <div 
                ref={scrollRef}
                className="flex-1 overflow-y-auto px-3 py-3 space-y-3 scrollbar-thin scrollbar-thumb-white/10"
              >
                {messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center py-8">
                    <Sparkles className="w-8 h-8 text-violet-400/40 mb-3" />
                    <p className="text-xs text-zinc-500">No conversations yet</p>
                    <p className="text-[10px] text-zinc-600 mt-1">Ask SentCom about your trades, strategies, or market conditions</p>
                  </div>
                ) : (
                  messages.map((msg, i) => (
                    <ChatMessage key={msg.id || i} msg={msg} />
                  ))
                )}
                {loading && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex items-center gap-2 pl-8"
                  >
                    <div className="flex items-center gap-1">
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-violet-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0 }} />
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-violet-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0.2 }} />
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-violet-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0.4 }} />
                    </div>
                    <span className="text-[10px] text-violet-300/50">thinking...</span>
                  </motion.div>
                )}
              </div>

              {/* Input */}
              <div className="p-3 border-t border-white/10 bg-black/30">
                <div className="flex items-center gap-2">
                  <input
                    ref={inputRef}
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask SentCom..."
                    className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-violet-500/40 transition-colors"
                    data-testid="chat-overlay-input"
                  />
                  <button
                    onClick={handleSend}
                    disabled={!input.trim() || loading}
                    className="p-2 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 text-white disabled:opacity-30 hover:shadow-lg hover:shadow-violet-500/20 transition-all"
                    data-testid="chat-overlay-send"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

export default ChatBubbleOverlay;
