/**
 * ChatBubbleOverlay.jsx - Floating Chat over SOC
 * 
 * Trading partner chat interface. Minimizes to bubble in bottom-right.
 * Shows unread badge when AI responds while minimized.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  MessageSquare, Send, X, Brain, Loader, Gauge, 
  Minimize2, Maximize2, Sparkles, Copy, Check,
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

// Simple markdown-ish rendering for bot responses
const RenderContent = ({ text, isUser }) => {
  if (isUser || !text) return <p className="whitespace-pre-wrap">{text}</p>;
  
  // Split into paragraphs, handle **bold**, bullet points
  const lines = text.split('\n');
  return (
    <div className="space-y-1.5">
      {lines.map((line, i) => {
        if (!line.trim()) return null;
        
        // Bold text
        const processed = line.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>');
        
        // Bullet points
        if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
          return (
            <div key={i} className="flex items-start gap-1.5 pl-1">
              <span className="text-emerald-400 mt-0.5 text-[10px]">&#9679;</span>
              <span dangerouslySetInnerHTML={{ __html: processed.replace(/^[\s]*[-*]\s/, '') }} />
            </div>
          );
        }
        
        // Numbered items
        if (/^\d+\.\s/.test(line.trim())) {
          return (
            <div key={i} className="flex items-start gap-1.5 pl-1">
              <span className="text-cyan-400 font-mono text-[10px] mt-0.5 min-w-[14px]">{line.trim().match(/^(\d+)/)[1]}.</span>
              <span dangerouslySetInnerHTML={{ __html: processed.replace(/^\d+\.\s/, '') }} />
            </div>
          );
        }
        
        return <p key={i} dangerouslySetInnerHTML={{ __html: processed }} />;
      })}
    </div>
  );
};

// Chat message bubble — user right, bot left, distinct colors
const ChatMessage = ({ msg }) => {
  const isUser = msg.type === 'chat' || msg.action_type === 'user_message';
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex items-start gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}
      data-testid={`chat-msg-${isUser ? 'user' : 'bot'}`}
    >
      {/* Avatar */}
      <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
        isUser 
          ? 'bg-gradient-to-br from-cyan-500 to-blue-600' 
          : 'bg-gradient-to-br from-emerald-500 to-teal-600'
      }`}>
        {isUser 
          ? <MessageSquare className="w-3.5 h-3.5 text-white" /> 
          : <Brain className="w-3.5 h-3.5 text-white" />}
      </div>

      {/* Message */}
      <div className={`flex-1 min-w-0 ${isUser ? 'max-w-[75%]' : 'max-w-[85%]'}`}>
        <div className={`rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed relative group ${
          isUser
            ? 'bg-cyan-500/15 border border-cyan-500/25 text-cyan-50 rounded-tr-sm ml-auto'
            : 'bg-zinc-800/80 border border-zinc-700/50 text-zinc-200 rounded-tl-sm'
        }`}>
          {/* Label */}
          <span className={`text-[9px] font-bold uppercase tracking-wider block mb-1 ${
            isUser ? 'text-cyan-400/70' : 'text-emerald-400/70'
          }`}>
            {isUser ? 'YOU' : 'SENTCOM'}
          </span>
          
          <RenderContent text={msg.content} isUser={isUser} />
          
          {/* Copy button for bot messages */}
          {!isUser && msg.content && (
            <button
              onClick={handleCopy}
              className="absolute top-2 right-2 p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-white/10 transition-all"
              data-testid="chat-copy-btn"
            >
              {copied 
                ? <Check className="w-3 h-3 text-emerald-400" /> 
                : <Copy className="w-3 h-3 text-zinc-500" />}
            </button>
          )}
        </div>
        <span className={`text-[9px] text-zinc-600 mt-0.5 block ${isUser ? 'text-right' : ''}`}>
          {formatRelativeTime(msg.timestamp)}
        </span>
      </div>
    </motion.div>
  );
};

// Quick action pills
const QuickActions = ({ onAction, loading }) => {
  const actions = [
    { id: 'performance', icon: BarChart3, label: 'Performance', prompt: "How's our trading performance looking? Win rate, P&L, what's working and what's not?" },
    { id: 'news', icon: Newspaper, label: 'News', prompt: "What's the market doing today? Key themes and how they affect our positions." },
    { id: 'morning', icon: Sunrise, label: 'Brief', endpoint: '/api/assistant/coach/morning-briefing' },
    { id: 'rules', icon: BookOpen, label: 'Rules', endpoint: '/api/assistant/coach/rule-reminder' },
    { id: 'summary', icon: TrendingUp, label: 'Summary', endpoint: '/api/assistant/coach/daily-summary' },
  ];

  return (
    <div className="flex items-center gap-1.5 flex-wrap px-2">
      {actions.map(a => {
        const Icon = a.icon;
        return (
          <button
            key={a.id}
            onClick={() => onAction(a)}
            disabled={loading === a.id}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium bg-white/5 border border-white/10 text-zinc-400 hover:text-white hover:bg-white/10 hover:border-white/20 transition-all"
            data-testid={`chat-quick-${a.id}`}
          >
            {loading === a.id ? <Loader className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
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
  const [isExpanded, setIsExpanded] = useState(false);
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
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (isOpen && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  // Keyboard shortcut: Ctrl+K to toggle
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

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

  // Auto-resize textarea
  const handleInputChange = (e) => {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 100) + 'px';
  };

  // Size classes
  const sizeClasses = isExpanded
    ? 'w-[800px] max-w-[90vw]'
    : 'w-[600px] max-w-[85vw]';
  const heightStyle = isExpanded ? 'calc(100vh - 120px)' : '560px';

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
            className="absolute bottom-4 right-4 z-30 w-12 h-12 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 shadow-lg shadow-emerald-500/30 flex items-center justify-center hover:shadow-emerald-500/50 hover:scale-105 transition-all cursor-pointer"
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
            className={`absolute bottom-4 right-4 z-30 ${sizeClasses} rounded-2xl overflow-hidden border border-white/15 shadow-2xl shadow-black/60`}
            style={{ height: heightStyle, maxHeight: 'calc(100vh - 40px)' }}
            data-testid="chat-overlay-window"
          >
            {/* Glass background */}
            <div className="absolute inset-0 bg-zinc-900/97 backdrop-blur-xl" />
            
            <div className="relative flex flex-col h-full">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-gradient-to-r from-emerald-500/10 to-teal-500/5">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
                    <Brain className="w-4 h-4 text-white" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">SentCom</h3>
                    <span className="text-[10px] text-zinc-500">Your trading partner &middot; Ctrl+K</span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
                    data-testid="chat-expand-btn"
                    title={isExpanded ? 'Reduce' : 'Expand'}
                  >
                    <Maximize2 className="w-4 h-4 text-zinc-400" />
                  </button>
                  <button
                    onClick={() => setIsOpen(false)}
                    className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
                    data-testid="chat-minimize-btn"
                  >
                    <Minimize2 className="w-4 h-4 text-zinc-400" />
                  </button>
                </div>
              </div>

              {/* Quick Actions */}
              <div className="py-2 border-b border-white/5">
                <QuickActions onAction={onQuickAction} loading={quickActionLoading} />
              </div>

              {/* Messages */}
              <div 
                ref={scrollRef}
                className="flex-1 overflow-y-auto px-4 py-4 space-y-4 scrollbar-thin scrollbar-thumb-white/10"
              >
                {messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center py-8">
                    <Sparkles className="w-10 h-10 text-emerald-400/30 mb-3" />
                    <p className="text-sm text-zinc-500 font-medium">Hey, what's on your mind?</p>
                    <p className="text-xs text-zinc-600 mt-1 max-w-xs">Ask me about our positions, market conditions, or tell me to execute a trade.</p>
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
                    className="flex items-center gap-2.5 pl-10"
                  >
                    <div className="flex items-center gap-1">
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-emerald-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0 }} />
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-emerald-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0.2 }} />
                      <motion.span className="w-1.5 h-1.5 rounded-full bg-emerald-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: 0.4 }} />
                    </div>
                    <span className="text-[11px] text-emerald-300/50">thinking...</span>
                  </motion.div>
                )}
              </div>

              {/* Input */}
              <div className="p-3 border-t border-white/10 bg-black/30">
                <div className="flex items-end gap-2">
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    placeholder="Talk to SentCom..."
                    rows={1}
                    className="flex-1 px-3.5 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-emerald-500/40 transition-colors resize-none overflow-hidden"
                    style={{ minHeight: '40px', maxHeight: '100px' }}
                    data-testid="chat-overlay-input"
                  />
                  <button
                    onClick={handleSend}
                    disabled={!input.trim() || loading}
                    className="p-2.5 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white disabled:opacity-30 hover:shadow-lg hover:shadow-emerald-500/20 transition-all flex-shrink-0"
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
