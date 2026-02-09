import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send,
  Search,
  X,
  Loader2,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Bell,
  Briefcase,
  Calendar,
  Eye,
  Zap,
  Clock,
  DollarSign,
  BarChart3,
  Target,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  ArrowUpRight,
  Trash2,
  RefreshCw,
  Newspaper,
  Activity,
  Play,
  Pause,
  CircleDot
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { formatPrice, formatPercent, formatVolume } from '../utils/tradingUtils';

// Markdown components
const markdownComponents = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-zinc-200">{children}</li>,
  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{children}</strong>,
  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
  code: ({ children }) => <code className="bg-black/30 px-1 rounded text-amber-400">{children}</code>,
};

// Section Header Component
const SectionHeader = ({ icon: Icon, title, count, isExpanded, onToggle, action }) => (
  <div 
    className="flex items-center justify-between py-2 px-3 bg-zinc-900/50 rounded-lg cursor-pointer hover:bg-zinc-800/50 transition-colors"
    onClick={onToggle}
  >
    <div className="flex items-center gap-2">
      <Icon className="w-4 h-4 text-cyan-400" />
      <span className="text-sm font-medium text-white">{title}</span>
      {count !== undefined && (
        <span className="text-xs text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">
          {count}
        </span>
      )}
    </div>
    <div className="flex items-center gap-2">
      {action}
      {isExpanded ? (
        <ChevronDown className="w-4 h-4 text-zinc-400" />
      ) : (
        <ChevronRight className="w-4 h-4 text-zinc-400" />
      )}
    </div>
  </div>
);

// Chat Message Component
const ChatMessage = ({ message, isUser }) => (
  <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
    <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
      isUser ? 'bg-cyan-500/20' : 'bg-amber-500/20'
    }`}>
      {isUser ? <User className="w-3 h-3 text-cyan-400" /> : <Bot className="w-3 h-3 text-amber-400" />}
    </div>
    <div className={`flex-1 max-w-[90%] ${isUser ? 'text-right' : ''}`}>
      <div className={`inline-block p-2.5 rounded-lg text-sm ${
        isUser ? 'bg-cyan-500/10 border border-cyan-500/20 text-white' : 'bg-zinc-800/50 border border-white/5 text-zinc-200'
      }`}>
        {isUser ? message.content : (
          <ReactMarkdown components={markdownComponents}>{message.content}</ReactMarkdown>
        )}
      </div>
    </div>
  </div>
);

// Quick Action Pill
const QuickPill = ({ label, onClick, loading, active }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className={`px-2.5 py-1 rounded-full text-xs transition-all ${
      active 
        ? 'bg-cyan-500 text-black font-medium' 
        : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700'
    } disabled:opacity-50`}
  >
    {label}
  </button>
);

const AICommandPanel = ({ 
  onTickerSelect,
  watchlist = [],
  alerts = [],
  opportunities = [],
  earnings = [],
  portfolio = [],
  scanResults = [],
  marketIndices = [],
  isConnected = false,
  onRefresh
}) => {
  // Chat state
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(`session_${Date.now()}`);
  
  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('recentTickerSearches') || '[]');
    } catch { return []; }
  });
  
  // Section expansion state
  const [expandedSections, setExpandedSections] = useState({
    search: true,
    portfolio: true,
    market: true,
    alerts: true,
    botTrades: true,
    opportunities: false,
    earnings: true,
    watchlist: false,
    scanner: false
  });
  
  // Bot trades state
  const [botTrades, setBotTrades] = useState({ pending: [], open: [], closed: [], daily_stats: {} });
  const [botTradesTab, setBotTradesTab] = useState('open');
  
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Toggle section
  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };
  
  // Fetch bot trades
  const fetchBotTrades = useCallback(async () => {
    try {
      const res = await api.get('/api/trading-bot/trades/all');
      if (res.data?.success) {
        setBotTrades(res.data);
      }
    } catch (err) {
      // Silent fail - bot may not be running
    }
  }, []);
  
  // Poll bot trades every 10s
  useEffect(() => {
    fetchBotTrades();
    const interval = setInterval(fetchBotTrades, 10000);
    return () => clearInterval(interval);
  }, [fetchBotTrades]);

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Send message
  const sendMessage = useCallback(async (messageText = null) => {
    const text = messageText || input.trim();
    if (!text || isLoading) return;

    const userMessage = { role: 'user', content: text, timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await api.post('/api/assistant/chat', {
        message: text,
        session_id: sessionId
      });
      
      if (response.data?.response) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date().toISOString()
        }]);
      }
    } catch (err) {
      toast.error('Failed to get response');
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date().toISOString()
      }]);
    }
    setIsLoading(false);
  }, [input, isLoading, sessionId]);

  // Handle search
  const handleSearch = (e) => {
    e.preventDefault();
    const symbol = searchQuery.trim().toUpperCase();
    if (!symbol) return;
    
    // Add to recent searches
    const updated = [symbol, ...recentSearches.filter(s => s !== symbol)].slice(0, 5);
    setRecentSearches(updated);
    localStorage.setItem('recentTickerSearches', JSON.stringify(updated));
    
    onTickerSelect?.({ symbol, quote: {} });
    setSearchQuery('');
    toast.success(`Loading ${symbol}...`);
  };

  // Quick actions
  const quickActions = [
    { label: 'Bot Status', action: () => sendMessage('What is the trading bot status? Show me all bot trades and performance.') },
    { label: 'My Performance', action: () => sendMessage('Analyze my trading performance and give me recommendations.') },
    { label: 'Market News', action: () => sendMessage("What's happening in the market today?") },
    { label: 'Rule Check', action: () => sendMessage('Remind me of my trading rules.') },
  ];

  return (
    <div className="flex flex-col h-full bg-[#0A0A0A] border border-white/10 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-white/10 bg-gradient-to-r from-cyan-900/20 to-amber-900/10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-amber-500 flex items-center justify-center">
            <Bot className="w-5 h-5 text-black" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white">AI Command Center</h2>
            <p className="text-[10px] text-zinc-500">Your trading intelligence hub</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-xs text-zinc-400">{isConnected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto">
        {/* AI Chat Section - Always Visible */}
        <div className="p-3 border-b border-white/10">
          {/* Quick Actions */}
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            {quickActions.map((qa, idx) => (
              <QuickPill key={idx} label={qa.label} onClick={qa.action} loading={isLoading} />
            ))}
          </div>
          
          {/* Messages */}
          <div className="space-y-3 max-h-[200px] overflow-y-auto mb-3">
            {messages.length === 0 ? (
              <div className="text-center py-4">
                <Sparkles className="w-6 h-6 text-amber-400 mx-auto mb-2" />
                <p className="text-xs text-zinc-500">Ask me anything about trading, markets, or your performance</p>
              </div>
            ) : (
              messages.map((msg, idx) => (
                <ChatMessage key={idx} message={msg} isUser={msg.role === 'user'} />
              ))
            )}
            {isLoading && (
              <div className="flex items-center gap-2 text-zinc-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-xs">Thinking...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          
          {/* Input */}
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder="Ask AI anything..."
              className="flex-1 px-3 py-2 bg-zinc-900 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || isLoading}
              className="px-3 py-2 bg-cyan-500 text-black rounded-lg hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Ticker Search Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Search} 
            title="Search Ticker" 
            isExpanded={expandedSections.search}
            onToggle={() => toggleSection('search')}
          />
          {expandedSections.search && (
            <div className="mt-2">
              <form onSubmit={handleSearch} className="flex gap-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value.toUpperCase())}
                  placeholder="Enter symbol (AAPL, TSLA...)"
                  className="flex-1 px-3 py-2 bg-zinc-900 border border-white/10 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
                />
                <button
                  type="submit"
                  disabled={!searchQuery}
                  className="px-4 py-2 bg-cyan-500/20 text-cyan-400 rounded-lg hover:bg-cyan-500/30 disabled:opacity-50 text-sm font-medium"
                >
                  Analyze
                </button>
              </form>
              {recentSearches.length > 0 && (
                <div className="flex gap-2 mt-2 flex-wrap">
                  <span className="text-xs text-zinc-500">Recent:</span>
                  {recentSearches.map((sym, idx) => (
                    <button
                      key={idx}
                      onClick={() => onTickerSelect?.({ symbol: sym, quote: {} })}
                      className="text-xs text-cyan-400 hover:text-cyan-300"
                    >
                      {sym}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Portfolio/Holdings Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Briefcase} 
            title="Portfolio" 
            count={portfolio.length}
            isExpanded={expandedSections.portfolio}
            onToggle={() => toggleSection('portfolio')}
          />
          {expandedSections.portfolio && (
            <div className="mt-2 space-y-1">
              {portfolio.length > 0 ? portfolio.slice(0, 5).map((pos, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: pos.symbol, quote: pos })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div>
                    <span className="text-sm font-medium text-white">{pos.symbol}</span>
                    <span className="text-xs text-zinc-500 ml-2">{pos.quantity} shares</span>
                  </div>
                  <div className="text-right">
                    <span className="text-sm text-white">${formatPrice(pos.market_value)}</span>
                    <span className={`text-xs ml-2 ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(pos.unrealized_pnl_pct)}
                    </span>
                  </div>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No positions</p>
              )}
            </div>
          )}
        </div>

        {/* Market Tracking Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Activity} 
            title="Market Indices" 
            isExpanded={expandedSections.market}
            onToggle={() => toggleSection('market')}
          />
          {expandedSections.market && (
            <div className="mt-2 grid grid-cols-3 gap-2">
              {(marketIndices.length > 0 ? marketIndices : [
                { symbol: 'SPY', price: 0, change_percent: 0 },
                { symbol: 'QQQ', price: 0, change_percent: 0 },
                { symbol: 'VIX', price: 0, change_percent: 0 }
              ]).slice(0, 6).map((idx, i) => (
                <div key={i} className="p-2 bg-zinc-900/50 rounded-lg text-center">
                  <span className="text-xs text-zinc-400 block">{idx.symbol}</span>
                  <span className={`text-sm font-mono ${idx.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {idx.price > 0 ? formatPercent(idx.change_percent) : '--'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Alerts Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Bell} 
            title="Alerts" 
            count={alerts.length}
            isExpanded={expandedSections.alerts}
            onToggle={() => toggleSection('alerts')}
          />
          {expandedSections.alerts && (
            <div className="mt-2 space-y-1 max-h-[150px] overflow-y-auto">
              {alerts.length > 0 ? alerts.slice(0, 5).map((alert, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: alert.symbol, quote: {} })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${
                      alert.type === 'price' ? 'bg-cyan-500' : 
                      alert.type === 'earnings' ? 'bg-amber-500' : 'bg-purple-500'
                    }`} />
                    <span className="text-sm font-medium text-white">{alert.symbol}</span>
                  </div>
                  <span className="text-xs text-zinc-400">{alert.message || alert.headline}</span>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No active alerts</p>
              )}
            </div>
          )}
        </div>

        {/* Opportunities Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Zap} 
            title="Opportunities" 
            count={opportunities.length}
            isExpanded={expandedSections.opportunities}
            onToggle={() => toggleSection('opportunities')}
            action={
              <button 
                onClick={(e) => { e.stopPropagation(); onRefresh?.(); }}
                className="p-1 hover:bg-zinc-700 rounded"
              >
                <RefreshCw className="w-3 h-3 text-zinc-400" />
              </button>
            }
          />
          {expandedSections.opportunities && (
            <div className="mt-2 space-y-1 max-h-[150px] overflow-y-auto">
              {opportunities.length > 0 ? opportunities.slice(0, 5).map((opp, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: opp.symbol, quote: opp })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div>
                    <span className="text-sm font-medium text-white">{opp.symbol}</span>
                    <span className={`text-xs ml-2 px-1.5 py-0.5 rounded ${
                      opp.direction === 'LONG' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>{opp.direction}</span>
                  </div>
                  <div className="text-right">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      opp.grade === 'A' ? 'bg-green-500 text-black' :
                      opp.grade === 'B' ? 'bg-cyan-500 text-black' : 'bg-yellow-500 text-black'
                    }`}>{opp.grade}</span>
                  </div>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No opportunities found</p>
              )}
            </div>
          )}
        </div>

        {/* Earnings Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Calendar} 
            title="Earnings" 
            count={earnings.length}
            isExpanded={expandedSections.earnings}
            onToggle={() => toggleSection('earnings')}
          />
          {expandedSections.earnings && (
            <div className="mt-2 space-y-1 max-h-[150px] overflow-y-auto">
              {earnings.length > 0 ? earnings.slice(0, 5).map((earn, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: earn.symbol, quote: {} })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div>
                    <span className="text-sm font-medium text-white">{earn.symbol}</span>
                    <span className="text-xs text-zinc-500 ml-2">{earn.timing || 'BMO'}</span>
                  </div>
                  <span className="text-xs text-zinc-400">{earn.date || 'Today'}</span>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No upcoming earnings</p>
              )}
            </div>
          )}
        </div>

        {/* Watchlist Section */}
        <div className="p-3 border-b border-white/10">
          <SectionHeader 
            icon={Eye} 
            title="Watchlist" 
            count={watchlist.length}
            isExpanded={expandedSections.watchlist}
            onToggle={() => toggleSection('watchlist')}
          />
          {expandedSections.watchlist && (
            <div className="mt-2 space-y-1 max-h-[150px] overflow-y-auto">
              {watchlist.length > 0 ? watchlist.slice(0, 8).map((item, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: item.symbol, quote: item })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <span className="text-sm font-medium text-white">{item.symbol}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono text-white">${formatPrice(item.price)}</span>
                    <span className={`text-xs ${item.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(item.change_percent)}
                    </span>
                  </div>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">Watchlist empty</p>
              )}
            </div>
          )}
        </div>

        {/* Scanner Results Section */}
        <div className="p-3">
          <SectionHeader 
            icon={Target} 
            title="Scanner Results" 
            count={scanResults.length}
            isExpanded={expandedSections.scanner}
            onToggle={() => toggleSection('scanner')}
          />
          {expandedSections.scanner && (
            <div className="mt-2 space-y-1 max-h-[200px] overflow-y-auto">
              {scanResults.length > 0 ? scanResults.slice(0, 10).map((result, idx) => (
                <div 
                  key={idx}
                  onClick={() => onTickerSelect?.({ symbol: result.symbol, quote: result })}
                  className="flex items-center justify-between p-2 bg-zinc-900/50 rounded-lg hover:bg-zinc-800/50 cursor-pointer"
                >
                  <div>
                    <span className="text-sm font-medium text-white">{result.symbol}</span>
                    {result.scan_type && (
                      <span className="text-xs text-zinc-500 ml-2">{result.scan_type}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono text-white">${formatPrice(result.price)}</span>
                    <span className={`text-xs ${result.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPercent(result.change_percent)}
                    </span>
                  </div>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">Run a scan to see results</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AICommandPanel;
