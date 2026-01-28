import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  MessageSquare,
  Send,
  X,
  Loader2,
  Bot,
  User,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Trash2,
  Clock,
  TrendingUp,
  AlertTriangle,
  BookOpen,
  Sunrise,
  HelpCircle,
  Award,
  List,
  Search,
  RefreshCw,
  Minimize2,
  Maximize2,
  Brain,
  Calculator,
  CheckCircle2,
  Target,
  MessageCircle
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';

// Markdown components defined outside render
const markdownComponents = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-zinc-200">{children}</li>,
  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{children}</strong>,
  h1: ({ children }) => <h1 className="text-lg font-bold text-white mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-bold text-white mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
  code: ({ children }) => <code className="bg-black/30 px-1 rounded text-amber-400">{children}</code>,
};

// Format timestamp
const formatTime = (timestamp) => {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

// Message component
const ChatMessage = ({ message, isUser }) => {
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
        isUser ? 'bg-cyan-500/20' : 'bg-amber-500/20'
      }`}>
        {isUser ? (
          <User className="w-4 h-4 text-cyan-400" />
        ) : (
          <Bot className="w-4 h-4 text-amber-400" />
        )}
      </div>
      <div className={`flex-1 max-w-[85%] ${isUser ? 'text-right' : ''}`}>
        <div className={`inline-block p-3 rounded-xl ${
          isUser 
            ? 'bg-cyan-500/10 border border-cyan-500/20 text-white' 
            : 'bg-zinc-800/50 border border-white/10 text-zinc-100'
        }`}>
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="text-sm prose prose-invert prose-sm max-w-none">
              <ReactMarkdown components={markdownComponents}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {message.timestamp && (
          <p className={`text-[10px] text-zinc-500 mt-1 ${isUser ? 'text-right' : ''}`}>
            {formatTime(message.timestamp)}
          </p>
        )}
      </div>
    </div>
  );
};

// Quick Action Button
const QuickAction = ({ icon: Icon, label, onClick, loading, color = 'zinc' }) => {
  const colorClasses = {
    zinc: 'bg-zinc-800/50 border-white/10 text-zinc-300 hover:border-cyan-500/30 hover:bg-zinc-800',
    cyan: 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20',
    amber: 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20',
    emerald: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20',
    purple: 'bg-purple-500/10 border-purple-500/30 text-purple-400 hover:bg-purple-500/20',
  };

  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs transition-all disabled:opacity-50 ${colorClasses[color]}`}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Icon className="w-3.5 h-3.5" />}
      <span>{label}</span>
    </button>
  );
};

// Check My Trade Form - combines rule check and position sizing
const CheckMyTradeForm = ({ onSubmit, loading }) => {
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
    if (!entryPrice || !stopLoss) {
      toast.error('Enter entry and stop prices for full analysis');
      return;
    }
    onSubmit({
      symbol: symbol.toUpperCase(),
      action,
      entry_price: parseFloat(entryPrice),
      stop_loss: parseFloat(stopLoss)
    });
    // Clear form after submit
    setSymbol('');
    setEntryPrice('');
    setStopLoss('');
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol"
          className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="check-trade-symbol"
        />
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded text-white text-xs focus:outline-none focus:border-cyan-500/50"
        >
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </div>
      <div className="flex gap-2">
        <input
          type="number"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
          placeholder="Entry $"
          step="0.01"
          className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="check-trade-entry"
        />
        <input
          type="number"
          value={stopLoss}
          onChange={(e) => setStopLoss(e.target.value)}
          placeholder="Stop $"
          step="0.01"
          className="flex-1 px-2.5 py-1.5 bg-zinc-800/50 border border-white/10 rounded text-white text-xs placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          data-testid="check-trade-stop"
        />
        <button
          type="submit"
          disabled={loading || !symbol.trim() || !entryPrice || !stopLoss}
          className="px-4 py-1.5 bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-600 hover:to-emerald-600 disabled:from-zinc-700 disabled:to-zinc-700 text-white rounded text-xs font-medium transition-all flex items-center gap-1.5"
          data-testid="check-trade-submit"
        >
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Target className="w-3 h-3" />}
          Check
        </button>
      </div>
    </form>
  );
};


// Main AI Assistant Component
const AIAssistant = ({ isOpen, onClose, initialPrompt = null }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [status, setStatus] = useState(null);
  const [showTradeCheck, setShowTradeCheck] = useState(false);
  const [coachLoading, setCoachLoading] = useState({});
  
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current && activeMode === 'chat') {
      inputRef.current.focus();
    }
  }, [isOpen, activeMode]);

  // Initialize session and fetch status
  useEffect(() => {
    if (isOpen) {
      if (!sessionId) {
        setSessionId(`session_${Date.now()}`);
      }
      fetchStatus();
      if (initialPrompt) {
        setInput(initialPrompt);
      }
    }
  }, [isOpen, sessionId, initialPrompt]);

  const fetchStatus = async () => {
    try {
      const res = await api.get('/api/assistant/status');
      setStatus(res.data);
    } catch (err) {
      console.error('Error fetching status:', err);
    }
  };

  const fetchSessions = async () => {
    try {
      const res = await api.get('/api/assistant/sessions');
      setSessions(res.data?.sessions || []);
    } catch (err) {
      console.error('Error fetching sessions:', err);
    }
  };

  const loadSession = async (sid) => {
    try {
      const res = await api.get(`/api/assistant/history/${sid}`);
      if (res.data?.messages) {
        setMessages(res.data.messages);
        setSessionId(sid);
        setShowHistory(false);
      }
    } catch (err) {
      toast.error('Failed to load conversation');
    }
  };

  const sendMessage = useCallback(async (messageText = null) => {
    const text = messageText || input.trim();
    if (!text || isLoading) return;

    const userMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    setActiveMode('chat');

    try {
      const res = await api.post('/api/assistant/chat', {
        message: text,
        session_id: sessionId
      });

      if (res.data?.success) {
        const assistantMessage = {
          role: 'assistant',
          content: res.data.response,
          timestamp: new Date().toISOString()
        };
        setMessages(prev => [...prev, assistantMessage]);
        
        if (res.data.session_id && !sessionId) {
          setSessionId(res.data.session_id);
        }
      } else {
        throw new Error(res.data?.error || 'Failed to get response');
      }
    } catch (err) {
      toast.error('Failed to send message');
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date().toISOString()
      }]);
    } finally {
      setIsLoading(false);
    }
  }, [input, sessionId, isLoading]);

  const clearConversation = async () => {
    if (!sessionId) return;
    
    try {
      await api.delete(`/api/assistant/history/${sessionId}`);
      setMessages([]);
      setSessionId(`session_${Date.now()}`);
      toast.success('Conversation cleared');
    } catch (err) {
      toast.error('Failed to clear conversation');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Coaching quick actions
  const handleCoachAction = useCallback(async (actionType) => {
    setCoachLoading(prev => ({ ...prev, [actionType]: true }));
    try {
      let res;
      let title;
      
      switch (actionType) {
        case 'morning':
          res = await api.get('/api/assistant/coach/morning-briefing');
          title = '☀️ Morning Coaching';
          break;
        case 'reminder':
          res = await api.get('/api/assistant/coach/rule-reminder');
          title = '📋 Rule Reminder';
          break;
        case 'summary':
          res = await api.get('/api/assistant/coach/daily-summary');
          title = '📊 Daily Summary';
          break;
        default:
          return;
      }
      
      if (res.data?.coaching) {
        // Add as assistant message
        setMessages(prev => [
          ...prev,
          { role: 'user', content: title, timestamp: new Date().toISOString() },
          { role: 'assistant', content: res.data.coaching, timestamp: new Date().toISOString() }
        ]);
      }
    } catch (err) {
      toast.error(`Failed to get ${actionType}`);
    } finally {
      setCoachLoading(prev => ({ ...prev, [actionType]: false }));
    }
  }, []);

  // Rule check handler
  const handleRuleCheck = useCallback(async (data) => {
    setCoachLoading(prev => ({ ...prev, rules: true }));
    try {
      const res = await api.post('/api/assistant/coach/check-rules', data);
      if (res.data?.analysis) {
        const userMsg = `🔍 Check rules: ${data.symbol} ${data.action}${data.entry_price ? ` @ $${data.entry_price}` : ''}${data.stop_loss ? ` (stop: $${data.stop_loss})` : ''}`;
        setMessages(prev => [
          ...prev,
          { role: 'user', content: userMsg, timestamp: new Date().toISOString() },
          { role: 'assistant', content: res.data.analysis, timestamp: new Date().toISOString() }
        ]);
      }
    } catch (err) {
      toast.error('Failed to check rules');
    } finally {
      setCoachLoading(prev => ({ ...prev, rules: false }));
      setActiveMode('chat');
    }
  }, []);

  // Position sizing handler
  const handlePositionSize = useCallback(async (data) => {
    setCoachLoading(prev => ({ ...prev, sizing: true }));
    try {
      const res = await api.post('/api/assistant/coach/position-size', data);
      if (res.data?.analysis) {
        const userMsg = `📐 Position size: ${data.symbol} entry $${data.entry_price} stop $${data.stop_loss}`;
        setMessages(prev => [
          ...prev,
          { role: 'user', content: userMsg, timestamp: new Date().toISOString() },
          { role: 'assistant', content: res.data.analysis, timestamp: new Date().toISOString() }
        ]);
      }
    } catch (err) {
      toast.error('Failed to calculate size');
    } finally {
      setCoachLoading(prev => ({ ...prev, sizing: false }));
      setActiveMode('chat');
    }
  }, []);

  if (!isOpen) return null;

  if (isMinimized) {
    return (
      <div className="fixed bottom-4 right-4 z-50">
        <button
          onClick={() => setIsMinimized(false)}
          className="flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-amber-500/20 to-cyan-500/20 border border-amber-500/30 rounded-full shadow-lg hover:border-amber-500/50 transition-all"
        >
          <Bot className="w-5 h-5 text-amber-400" />
          <span className="text-white font-medium">AI Assistant</span>
          {messages.length > 0 && (
            <span className="bg-cyan-500 text-white text-xs px-2 py-0.5 rounded-full">
              {messages.length}
            </span>
          )}
          <Maximize2 className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-[85vh] mx-4 bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-amber-500/5 to-cyan-500/5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-cyan-500/20 flex items-center justify-center">
              <Bot className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h2 className="font-bold text-white flex items-center gap-2">
                AI Trading Assistant
                <Sparkles className="w-4 h-4 text-amber-400" />
              </h2>
              <p className="text-xs text-zinc-500">
                {status?.ready ? (
                  <span className="text-emerald-400">● Online</span>
                ) : (
                  <span className="text-red-400">● Offline</span>
                )}
                <span className="ml-2">Chat + Coaching</span>
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                fetchSessions();
                setShowHistory(!showHistory);
              }}
              className={`p-2 rounded-lg transition-colors ${
                showHistory ? 'bg-cyan-500/20 text-cyan-400' : 'text-zinc-400 hover:text-white hover:bg-white/5'
              }`}
              title="History"
            >
              <Clock className="w-5 h-5" />
            </button>
            <button
              onClick={clearConversation}
              className="p-2 text-zinc-400 hover:text-red-400 hover:bg-white/5 rounded-lg transition-colors"
              title="Clear"
            >
              <Trash2 className="w-5 h-5" />
            </button>
            <button
              onClick={() => setIsMinimized(true)}
              className="p-2 text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
              title="Minimize"
            >
              <Minimize2 className="w-5 h-5" />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Session History Dropdown */}
        {showHistory && sessions.length > 0 && (
          <div className="border-b border-white/10 bg-zinc-900/50 p-3 max-h-32 overflow-y-auto">
            <p className="text-xs text-zinc-500 mb-2">Recent Conversations</p>
            <div className="space-y-1">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  onClick={() => loadSession(session.session_id)}
                  className={`w-full text-left px-3 py-1.5 rounded text-xs transition-colors ${
                    session.session_id === sessionId
                      ? 'bg-cyan-500/20 text-cyan-400'
                      : 'hover:bg-white/5 text-zinc-300'
                  }`}
                >
                  <span className="truncate">{session.session_id}</span>
                  <span className="text-zinc-500 ml-2">({session.message_count})</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Quick Actions Bar */}
        <div className="p-3 border-b border-white/10 bg-zinc-900/30">
          <div className="flex items-center gap-2 flex-wrap">
            <QuickAction
              icon={Sunrise}
              label="Morning Brief"
              onClick={() => handleCoachAction('morning')}
              loading={coachLoading.morning}
              color="amber"
            />
            <QuickAction
              icon={BookOpen}
              label="Rule Reminder"
              onClick={() => handleCoachAction('reminder')}
              loading={coachLoading.reminder}
              color="cyan"
            />
            <QuickAction
              icon={TrendingUp}
              label="Daily Summary"
              onClick={() => handleCoachAction('summary')}
              loading={coachLoading.summary}
              color="purple"
            />
            <div className="h-5 w-px bg-white/10 mx-1" />
            <button
              onClick={() => setActiveMode(activeMode === 'rules' ? 'chat' : 'rules')}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs transition-all ${
                activeMode === 'rules' 
                  ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400' 
                  : 'bg-zinc-800/50 border-white/10 text-zinc-300 hover:border-cyan-500/30'
              }`}
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Rule Check
            </button>
            <button
              onClick={() => setActiveMode(activeMode === 'sizing' ? 'chat' : 'sizing')}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs transition-all ${
                activeMode === 'sizing' 
                  ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' 
                  : 'bg-zinc-800/50 border-white/10 text-zinc-300 hover:border-emerald-500/30'
              }`}
            >
              <Calculator className="w-3.5 h-3.5" />
              Position Size
            </button>
          </div>
          
          {/* Inline Forms */}
          {activeMode === 'rules' && (
            <div className="mt-3 p-3 bg-cyan-500/5 border border-cyan-500/20 rounded-lg">
              <p className="text-xs text-zinc-400 mb-2">Check trade against your rules before executing:</p>
              <RuleCheckForm onSubmit={handleRuleCheck} loading={coachLoading.rules} />
            </div>
          )}
          {activeMode === 'sizing' && (
            <div className="mt-3 p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-lg">
              <p className="text-xs text-zinc-400 mb-2">Calculate position size based on risk rules:</p>
              <PositionSizeForm onSubmit={handlePositionSize} loading={coachLoading.sizing} />
            </div>
          )}
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-amber-500/10 to-cyan-500/10 flex items-center justify-center mb-4">
                <Bot className="w-8 h-8 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-2">How can I help you trade smarter?</h3>
              <p className="text-sm text-zinc-500 mb-4 max-w-md">
                I have access to your learned strategies and rules. Ask me anything, or use the quick actions above.
              </p>
              <div className="grid grid-cols-2 gap-2 text-left max-w-sm">
                <button
                  onClick={() => sendMessage("Analyze AAPL for me")}
                  className="flex items-center gap-2 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg hover:border-cyan-500/30 text-xs text-zinc-300"
                >
                  <Search className="w-3.5 h-3.5 text-zinc-400" />
                  Analyze AAPL
                </button>
                <button
                  onClick={() => sendMessage("What are my trading rules for gaps?")}
                  className="flex items-center gap-2 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg hover:border-cyan-500/30 text-xs text-zinc-300"
                >
                  <List className="w-3.5 h-3.5 text-zinc-400" />
                  My gap rules
                </button>
                <button
                  onClick={() => sendMessage("Should I buy NVDA?")}
                  className="flex items-center gap-2 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg hover:border-cyan-500/30 text-xs text-zinc-300"
                >
                  <HelpCircle className="w-3.5 h-3.5 text-zinc-400" />
                  Should I buy?
                </button>
                <button
                  onClick={() => sendMessage("Review my recent trades")}
                  className="flex items-center gap-2 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg hover:border-cyan-500/30 text-xs text-zinc-300"
                >
                  <BookOpen className="w-3.5 h-3.5 text-zinc-400" />
                  Review trades
                </button>
              </div>
            </div>
          ) : (
            <>
              {messages.map((message, idx) => (
                <ChatMessage
                  key={idx}
                  message={message}
                  isUser={message.role === 'user'}
                />
              ))}
              
              {isLoading && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center">
                    <Bot className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="bg-zinc-800/50 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                      <span className="text-sm text-zinc-400">Thinking...</span>
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-white/10 bg-zinc-900/30">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me anything about trading..."
                className="w-full px-4 py-3 pr-12 bg-zinc-800/50 border border-white/10 rounded-xl text-white placeholder-zinc-500 resize-none focus:outline-none focus:border-cyan-500/50 transition-colors"
                rows={1}
                style={{ minHeight: '48px', maxHeight: '120px' }}
              />
              <button
                onClick={() => sendMessage()}
                disabled={!input.trim() || isLoading}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-cyan-500 hover:bg-cyan-600 disabled:bg-zinc-700 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                ) : (
                  <Send className="w-4 h-4 text-white" />
                )}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-zinc-600 mt-2 text-center">
            Enter to send • Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
};

export default AIAssistant;
