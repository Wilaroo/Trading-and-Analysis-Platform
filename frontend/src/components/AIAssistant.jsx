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
  Maximize2
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';

// Icon mapping for suggestions
const suggestionIcons = {
  'sunrise': Sunrise,
  'search': Search,
  'help-circle': HelpCircle,
  'award': Award,
  'book': BookOpen,
  'list': List
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
              <ReactMarkdown
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="text-zinc-200">{children}</li>,
                  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{children}</strong>,
                  h1: ({ children }) => <h1 className="text-lg font-bold text-white mb-2">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-bold text-white mb-2">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
                  code: ({ children }) => <code className="bg-black/30 px-1 rounded text-amber-400">{children}</code>,
                }}
              >
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

// Suggestion chip component
const SuggestionChip = ({ suggestion, onClick }) => {
  const IconComponent = suggestionIcons[suggestion.icon] || HelpCircle;
  
  return (
    <button
      onClick={() => onClick(suggestion.text)}
      className="flex items-center gap-2 px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg hover:border-cyan-500/30 hover:bg-zinc-800 transition-all text-left group"
    >
      <IconComponent className="w-4 h-4 text-zinc-400 group-hover:text-cyan-400" />
      <span className="text-xs text-zinc-300 group-hover:text-white">{suggestion.text}</span>
    </button>
  );
};

// Main AI Assistant Component
const AIAssistant = ({ isOpen, onClose, initialPrompt = null }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [isMinimized, setIsMinimized] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [status, setStatus] = useState(null);
  
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
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Initialize session and fetch suggestions
  useEffect(() => {
    if (isOpen) {
      // Generate new session ID if none exists
      if (!sessionId) {
        setSessionId(`session_${Date.now()}`);
      }
      
      // Fetch suggestions
      fetchSuggestions();
      
      // Fetch status
      fetchStatus();
      
      // Handle initial prompt
      if (initialPrompt) {
        setInput(initialPrompt);
      }
    }
  }, [isOpen, sessionId, initialPrompt]);

  const fetchSuggestions = async () => {
    try {
      const res = await api.get('/api/assistant/suggestions');
      setSuggestions(res.data?.suggestions || []);
    } catch (err) {
      console.error('Error fetching suggestions:', err);
    }
  };

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

    // Add user message immediately
    const userMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

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
        
        // Update session ID if returned
        if (res.data.session_id && !sessionId) {
          setSessionId(res.data.session_id);
        }
      } else {
        throw new Error(res.data?.error || 'Failed to get response');
      }
    } catch (err) {
      toast.error('Failed to send message');
      console.error('Chat error:', err);
      
      // Add error message
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

  const handleSuggestionClick = (text) => {
    setInput(text);
    inputRef.current?.focus();
  };

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
      <div className="w-full max-w-2xl h-[80vh] mx-4 bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10 bg-gradient-to-r from-amber-500/5 to-cyan-500/5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-cyan-500/20 flex items-center justify-center">
              <Bot className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h2 className="font-bold text-white flex items-center gap-2">
                Trading Assistant
                <Sparkles className="w-4 h-4 text-amber-400" />
              </h2>
              <p className="text-xs text-zinc-500">
                {status?.ready ? (
                  <span className="text-emerald-400">● Online</span>
                ) : (
                  <span className="text-red-400">● Offline</span>
                )}
                {status?.current_provider && (
                  <span className="ml-2 text-zinc-500">via {status.current_provider}</span>
                )}
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
              title="Conversation history"
            >
              <Clock className="w-5 h-5" />
            </button>
            <button
              onClick={clearConversation}
              className="p-2 text-zinc-400 hover:text-red-400 hover:bg-white/5 rounded-lg transition-colors"
              title="Clear conversation"
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
          <div className="border-b border-white/10 bg-zinc-900/50 p-3 max-h-40 overflow-y-auto">
            <p className="text-xs text-zinc-500 mb-2">Recent Conversations</p>
            <div className="space-y-1">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  onClick={() => loadSession(session.session_id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    session.session_id === sessionId
                      ? 'bg-cyan-500/20 text-cyan-400'
                      : 'hover:bg-white/5 text-zinc-300'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="truncate">{session.session_id}</span>
                    <span className="text-xs text-zinc-500">{session.message_count} msgs</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-amber-500/10 to-cyan-500/10 flex items-center justify-center mb-4">
                <Bot className="w-8 h-8 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-2">How can I help you trade smarter?</h3>
              <p className="text-sm text-zinc-500 mb-6 max-w-md">
                I have access to your {status?.knowledge_count || 108}+ learned strategies and rules. 
                I'll help analyze trades, enforce your rules, and spot patterns in your behavior.
              </p>
              
              {/* Suggestions */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
                {suggestions.slice(0, 6).map((suggestion, idx) => (
                  <SuggestionChip
                    key={idx}
                    suggestion={suggestion}
                    onClick={handleSuggestionClick}
                  />
                ))}
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
                      <span className="text-sm text-zinc-400">Analyzing...</span>
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Quick Actions (when conversation active) */}
        {messages.length > 0 && (
          <div className="px-4 py-2 border-t border-white/5 flex gap-2 overflow-x-auto">
            {[
              { text: "Analyze my last trade", icon: TrendingUp },
              { text: "Check my rules", icon: List },
              { text: "Any warnings?", icon: AlertTriangle },
            ].map((action, idx) => (
              <button
                key={idx}
                onClick={() => sendMessage(action.text)}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-zinc-800/50 border border-white/10 rounded-full hover:border-cyan-500/30 whitespace-nowrap transition-colors disabled:opacity-50"
              >
                <action.icon className="w-3 h-3 text-zinc-400" />
                <span className="text-zinc-300">{action.text}</span>
              </button>
            ))}
          </div>
        )}

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
            Press Enter to send • Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
};

export default AIAssistant;
