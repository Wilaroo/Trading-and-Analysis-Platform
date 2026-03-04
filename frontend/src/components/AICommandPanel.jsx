import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send,
  X,
  Loader2,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Calendar,
  Eye,
  Zap,
  Target,
  Sparkles,
  ArrowUpRight,
  RefreshCw,
  Activity,
  Pause,
  Power,
  Shield,
  Check,
  Star,
  ArrowRight,
  Clock,
  DollarSign,
  Briefcase,
  LineChart,
  Plus,
  Minus,
  Bell,
  MoreHorizontal,
  Trash2
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { formatPrice, formatPercent } from '../utils/tradingUtils';
import TradingViewWidget from './charts/TradingViewWidget';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// ===================== TICKER UTILITIES =====================

const TickerLink = ({ symbol, onClick, onViewChart, showBrackets = false }) => (
  <span className="inline-flex items-center gap-0.5">
    <button
      onClick={() => onClick(symbol)}
      className="inline-flex items-center gap-0.5 px-1 py-0.5 bg-cyan-500/10 border border-cyan-500/20 rounded-l text-cyan-400 font-mono font-semibold text-xs hover:bg-cyan-500/20 hover:border-cyan-500/40 transition-colors cursor-pointer"
      data-testid={`ticker-link-${symbol}`}
      title={`View ${symbol} details`}
    >
      {showBrackets ? `(${symbol})` : symbol}
      <ArrowUpRight className="w-3 h-3" />
    </button>
    {onViewChart && (
      <button
        onClick={() => onViewChart(symbol)}
        className="inline-flex items-center px-1 py-0.5 bg-amber-500/10 border border-amber-500/20 border-l-0 rounded-r text-amber-400 text-xs hover:bg-amber-500/20 hover:border-amber-500/40 transition-colors cursor-pointer"
        data-testid={`ticker-chart-${symbol}`}
        title={`View ${symbol} chart`}
      >
        <LineChart className="w-3 h-3" />
      </button>
    )}
  </span>
);

const TickerAwareText = ({ text, onTickerClick, onViewChart }) => {
  if (!text || typeof text !== 'string') return text;
  
  const knownTickers = new Set([
    'AAPL','MSFT','NVDA','TSLA','AMD','META','GOOGL','AMZN','GOOG','NFLX',
    'SPY','QQQ','IWM','DIA','VIX','SOFI','PLTR','RIVN','INTC','UBER',
    'COST','WMT','TGT','JPM','BAC','GS','V','MA','PYPL','SQ','SHOP',
    'CRM','ORCL','ADBE','NOW','SNOW','NET','CRWD','ZS','DDOG','MDB',
    'COIN','HOOD','RBLX','ROKU','SNAP','PINS','SPOT','SE','MELI',
    'BA','LMT','GE','CAT','DE','HON','MMM','UNH','JNJ','PFE','MRNA',
    'LLY','ABBV','BMY','GILD','AMGN','XOM','CVX','COP','SLB','OXY',
    'AVGO','QCOM','MU','AMAT','LRCX','KLAC','TXN','MRVL','ARM',
    'F','GM','TM','NIO','XPEV','LI','LCID','FSR','DIS','CMCSA','WBD',
    'T','VZ','TMUS','KO','PEP','MCD','SBUX','NKE','LULU','CROX','SIEGY'
  ]);
  
  // Map company names to ticker symbols
  const companyToTicker = {
    'Apple': 'AAPL', 'Microsoft': 'MSFT', 'Nvidia': 'NVDA', 'NVIDIA': 'NVDA',
    'Tesla': 'TSLA', 'Amazon': 'AMZN', 'Google': 'GOOGL', 'Alphabet': 'GOOGL',
    'Meta': 'META', 'Facebook': 'META', 'Netflix': 'NFLX', 'Intel': 'INTC',
    'AMD': 'AMD', 'Uber': 'UBER', 'Costco': 'COST', 'Walmart': 'WMT',
    'Target': 'TGT', 'JPMorgan': 'JPM', 'Goldman': 'GS', 'Goldman Sachs': 'GS',
    'Visa': 'V', 'Mastercard': 'MA', 'PayPal': 'PYPL', 'Shopify': 'SHOP',
    'Salesforce': 'CRM', 'Oracle': 'ORCL', 'Adobe': 'ADBE', 'Snowflake': 'SNOW',
    'Cloudflare': 'NET', 'CrowdStrike': 'CRWD', 'Datadog': 'DDOG', 'MongoDB': 'MDB',
    'Coinbase': 'COIN', 'Robinhood': 'HOOD', 'Roblox': 'RBLX', 'Roku': 'ROKU',
    'Snap': 'SNAP', 'Snapchat': 'SNAP', 'Pinterest': 'PINS', 'Spotify': 'SPOT',
    'Boeing': 'BA', 'Lockheed': 'LMT', 'Lockheed Martin': 'LMT', 'GE': 'GE',
    'General Electric': 'GE', 'Caterpillar': 'CAT', 'Deere': 'DE', 'John Deere': 'DE',
    'Honeywell': 'HON', '3M': 'MMM', 'UnitedHealth': 'UNH', 'Johnson': 'JNJ',
    'Pfizer': 'PFE', 'Moderna': 'MRNA', 'Lilly': 'LLY', 'Eli Lilly': 'LLY',
    'AbbVie': 'ABBV', 'Bristol': 'BMY', 'Bristol-Myers': 'BMY', 'Gilead': 'GILD',
    'Amgen': 'AMGN', 'Exxon': 'XOM', 'ExxonMobil': 'XOM', 'Chevron': 'CVX',
    'ConocoPhillips': 'COP', 'Schlumberger': 'SLB', 'Occidental': 'OXY',
    'Broadcom': 'AVGO', 'Qualcomm': 'QCOM', 'Micron': 'MU', 'Ford': 'F',
    'GM': 'GM', 'General Motors': 'GM', 'Toyota': 'TM', 'NIO': 'NIO',
    'Disney': 'DIS', 'Comcast': 'CMCSA', 'AT&T': 'T', 'Verizon': 'VZ',
    'Coca-Cola': 'KO', 'Coke': 'KO', 'Pepsi': 'PEP', 'PepsiCo': 'PEP',
    'McDonald': 'MCD', "McDonald's": 'MCD', 'Starbucks': 'SBUX', 'Nike': 'NKE',
    'Lululemon': 'LULU', 'Palantir': 'PLTR', 'Rivian': 'RIVN', 'SoFi': 'SOFI',
    'Crocs': 'CROX', "Crocs's": 'CROX', 'Siemens': 'SIEGY', "Siemens's": 'SIEGY',
    'Square': 'SQ', 'Block': 'SQ', 'Arm': 'ARM', 'ARM': 'ARM', 'Marvell': 'MRVL'
  };
  
  // First, replace company names with placeholders
  let processedText = text;
  const replacements = [];
  
  // Sort by length descending to match longer names first
  const sortedCompanies = Object.keys(companyToTicker).sort((a, b) => b.length - a.length);
  
  for (const company of sortedCompanies) {
    // Match company name with word boundaries (case insensitive)
    const regex = new RegExp(`\\b${company.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:'s)?\\b`, 'gi');
    processedText = processedText.replace(regex, (match) => {
      const ticker = companyToTicker[company];
      const placeholder = `__COMPANY_${replacements.length}__`;
      replacements.push({ match, ticker });
      return placeholder;
    });
  }
  
  // Now split by tickers
  const parts = processedText.split(/(\$?[A-Z]{1,5}(?=[\s,.:;!?)}\]"]|$)|__COMPANY_\d+__)/g);
  
  return parts.map((part, i) => {
    // Check if it's a company placeholder
    const companyMatch = part.match(/__COMPANY_(\d+)__/);
    if (companyMatch) {
      const idx = parseInt(companyMatch[1]);
      const { match, ticker } = replacements[idx];
      return (
        <span key={i}>
          <span className="text-zinc-300">{match}</span>
          {' '}
          <TickerLink symbol={ticker} onClick={onTickerClick} onViewChart={onViewChart} showBrackets />
        </span>
      );
    }
    
    // Check if it's a ticker
    const clean = part.replace('$', '');
    if (knownTickers.has(clean) && part.length >= 2) {
      return <TickerLink key={i} symbol={clean} onClick={onTickerClick} onViewChart={onViewChart} />;
    }
    
    return part;
  });
};

const createMarkdownComponents = (onTickerClick, onViewChart) => ({
  p: ({ children }) => <p className="mb-2 last:mb-0">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} onViewChart={onViewChart} /> : children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-zinc-200">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} onViewChart={onViewChart} /> : children}</li>,
  strong: ({ children }) => <strong className="text-cyan-400 font-semibold">{typeof children === 'string' ? <TickerAwareText text={children} onTickerClick={onTickerClick} onViewChart={onViewChart} /> : children}</strong>,
  h3: ({ children }) => <h3 className="text-sm font-bold text-white mb-1">{children}</h3>,
  code: ({ children }) => <code className="bg-black/30 px-1 rounded text-amber-400">{children}</code>,
});

// ===================== UI COMPONENTS =====================

const SectionHeader = ({ icon: Icon, title, count, isExpanded, onToggle, action, compact = false }) => (
  <div 
    className={`flex items-center justify-between ${compact ? 'py-1.5 px-2' : 'py-2 px-3'} bg-zinc-900/50 rounded-lg cursor-pointer hover:bg-zinc-800/50 transition-colors`}
    onClick={onToggle}
  >
    <div className="flex items-center gap-2">
      <Icon className={`${compact ? 'w-3 h-3' : 'w-4 h-4'} text-cyan-400`} />
      <span className={`${compact ? 'text-xs' : 'text-sm'} font-medium text-white`}>{title}</span>
      {count !== undefined && (
        <span className="text-[10px] text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">{count}</span>
      )}
    </div>
    <div className="flex items-center gap-2">
      {action}
      {isExpanded ? <ChevronDown className="w-3 h-3 text-zinc-400" /> : <ChevronRight className="w-3 h-3 text-zinc-400" />}
    </div>
  </div>
);

const ChatMessage = ({ message, isUser, onTickerClick, onViewChart }) => {
  const mdComponents = createMarkdownComponents(onTickerClick, onViewChart);
  const validation = message.validation;
  
  // Determine confidence color
  const getConfidenceColor = (confidence) => {
    if (!confidence) return 'text-zinc-500';
    if (confidence >= 0.8) return 'text-emerald-400';
    if (confidence >= 0.6) return 'text-amber-400';
    return 'text-red-400';
  };
  
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
        isUser ? 'bg-cyan-500/20' : 'bg-gradient-to-br from-amber-500/30 to-cyan-500/30'
      }`}>
        {isUser ? <User className="w-4 h-4 text-cyan-400" /> : <Bot className="w-4 h-4 text-amber-400" />}
      </div>
      <div className={`flex-1 max-w-[85%] ${isUser ? 'text-right' : ''}`}>
        <div className={`inline-block p-3 rounded-xl text-sm ${
          isUser ? 'bg-cyan-500/10 border border-cyan-500/20 text-white' : 'bg-zinc-800/70 border border-white/5 text-zinc-200'
        }`}>
          {isUser ? message.content : (
            <ReactMarkdown components={mdComponents}>{message.content}</ReactMarkdown>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10px] text-zinc-600">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          {/* Validation confidence indicator for AI messages */}
          {!isUser && validation && (
            <span className={`text-[9px] flex items-center gap-0.5 ${getConfidenceColor(validation.confidence)}`}
                  title={validation.validated ? 'Response validated successfully' : `${validation.issue_count || 0} issues found`}>
              <Shield className="w-2.5 h-2.5" />
              {Math.round((validation.confidence || 0) * 100)}%
              {validation.regeneration_count > 0 && (
                <span className="text-cyan-400 ml-1">↻{validation.regeneration_count}</span>
              )}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

const QuickPill = ({ label, onClick, loading, icon: Icon }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700 transition-all disabled:opacity-50"
  >
    {Icon && <Icon className="w-3 h-3" />}
    {label}
  </button>
);

// ===================== POSITION CARD WITH QUICK ACTIONS =====================

const PositionCard = ({ position, onTickerClick, onViewChart, onClosePosition, onAddPosition, onSetAlert }) => {
  const [showActions, setShowActions] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  
  const pos = position;
  const qty = pos.qty || pos.quantity || 0;
  const pnl = pos.unrealized_pnl || pos.unrealized_pl || 0;
  const pnlPercent = (pos.unrealized_plpc || pos.unrealized_pnl_percent || 0) * 100;
  const avgCost = pos.avg_entry_price || pos.avg_cost || 0;
  const currentPrice = pos.current_price || 0;
  const isLong = qty > 0;
  
  const handleAction = async (action, e) => {
    e.stopPropagation();
    setActionLoading(action);
    
    try {
      switch (action) {
        case 'close':
          await onClosePosition(pos);
          break;
        case 'add':
          await onAddPosition(pos);
          break;
        case 'alert':
          await onSetAlert(pos);
          break;
        default:
          break;
      }
    } catch (err) {
      // Error handled by parent
    }
    
    setActionLoading(null);
    setShowActions(false);
  };
  
  return (
    <div 
      className="relative group rounded-lg transition-all border border-white/5 hover:border-cyan-500/30"
      style={{ background: 'rgba(21, 28, 36, 0.6)' }}
      data-testid={`position-${pos.symbol}`}
    >
      {/* Main Position Info */}
      <div 
        className="flex items-center justify-between p-2 cursor-pointer hover:bg-cyan-500/10 rounded-lg transition-colors"
        onClick={() => onTickerClick(pos.symbol)}
      >
        <div className="flex items-center gap-2">
          <div className={`w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold ${
            isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
          }`}>
            {isLong ? 'L' : 'S'}
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-white text-xs">{pos.symbol}</span>
              <ArrowUpRight className="w-2.5 h-2.5 text-cyan-400" />
            </div>
            <span className="text-[9px] text-zinc-500">
              {Math.abs(qty)} shares @ ${avgCost.toFixed(2)}
            </span>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <div className="text-right">
            <p className={`text-xs font-bold font-mono ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
            </p>
            <p className="text-[9px] text-zinc-500">
              {pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
            </p>
          </div>
          
          {/* Quick Actions Toggle */}
          <button
            onClick={(e) => { e.stopPropagation(); setShowActions(!showActions); }}
            className="p-1 rounded hover:bg-white/10 transition-colors opacity-0 group-hover:opacity-100"
            data-testid={`position-actions-toggle-${pos.symbol}`}
          >
            <MoreHorizontal className="w-3.5 h-3.5 text-zinc-400" />
          </button>
        </div>
      </div>
      
      {/* Quick Actions Panel */}
      <AnimatePresence>
        {showActions && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="flex items-center gap-1.5 px-2 pb-2 pt-1 border-t border-white/5">
              {/* Close Position */}
              <button
                onClick={(e) => handleAction('close', e)}
                disabled={actionLoading === 'close'}
                className="flex items-center gap-1 px-2 py-1 rounded bg-red-500/20 text-red-400 text-[10px] font-medium hover:bg-red-500/30 transition-colors disabled:opacity-50"
                data-testid={`close-position-${pos.symbol}`}
              >
                {actionLoading === 'close' ? (
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                ) : (
                  <Minus className="w-2.5 h-2.5" />
                )}
                Close
              </button>
              
              {/* Add to Position */}
              <button
                onClick={(e) => handleAction('add', e)}
                disabled={actionLoading === 'add'}
                className="flex items-center gap-1 px-2 py-1 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-medium hover:bg-emerald-500/30 transition-colors disabled:opacity-50"
                data-testid={`add-position-${pos.symbol}`}
              >
                {actionLoading === 'add' ? (
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                ) : (
                  <Plus className="w-2.5 h-2.5" />
                )}
                Add
              </button>
              
              {/* Set Price Alert */}
              <button
                onClick={(e) => handleAction('alert', e)}
                disabled={actionLoading === 'alert'}
                className="flex items-center gap-1 px-2 py-1 rounded bg-amber-500/20 text-amber-400 text-[10px] font-medium hover:bg-amber-500/30 transition-colors disabled:opacity-50"
                data-testid={`set-alert-${pos.symbol}`}
              >
                {actionLoading === 'alert' ? (
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                ) : (
                  <Bell className="w-2.5 h-2.5" />
                )}
                Alert
              </button>
              
              {/* View Chart */}
              {onViewChart && (
                <button
                  onClick={(e) => { e.stopPropagation(); onViewChart(pos.symbol); setShowActions(false); }}
                  className="flex items-center gap-1 px-2 py-1 rounded bg-cyan-500/20 text-cyan-400 text-[10px] font-medium hover:bg-cyan-500/30 transition-colors"
                  data-testid={`view-chart-${pos.symbol}`}
                >
                  <LineChart className="w-2.5 h-2.5" />
                  Chart
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// ===================== PORTFOLIO INSIGHTS WIDGET =====================

const PortfolioInsightsWidget = ({ onTickerClick, onViewChart }) => {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);
  
  const fetchSuggestions = async () => {
    setLoading(true);
    try {
      const response = await api.post('/api/portfolio-awareness/analyze');
      if (response.data.success) {
        setSuggestions(response.data.suggestions || []);
        setLastUpdate(new Date());
      }
    } catch (error) {
      console.error('Error fetching portfolio suggestions:', error);
    } finally {
      setLoading(false);
    }
  };
  
  const dismissSuggestion = async (suggestionId) => {
    try {
      await api.post('/api/portfolio-awareness/dismiss', { suggestion_id: suggestionId });
      setSuggestions(prev => prev.filter(s => s.id !== suggestionId));
    } catch (error) {
      console.error('Error dismissing suggestion:', error);
    }
  };
  
  useEffect(() => {
    fetchSuggestions();
    // Refresh every 2 minutes
    const interval = setInterval(fetchSuggestions, 120000);
    return () => clearInterval(interval);
  }, []);
  
  const getPriorityConfig = (priority) => {
    const configs = {
      critical: { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-400', icon: '🚨' },
      high: { bg: 'bg-amber-500/20', border: 'border-amber-500/40', text: 'text-amber-400', icon: '⚠️' },
      medium: { bg: 'bg-blue-500/20', border: 'border-blue-500/40', text: 'text-blue-400', icon: '💡' },
      low: { bg: 'bg-zinc-500/20', border: 'border-zinc-500/40', text: 'text-zinc-400', icon: '📝' }
    };
    return configs[priority] || configs.medium;
  };
  
  const formatTime = (isoString) => {
    if (!isoString) return '';
    return new Date(isoString).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  };

  if (suggestions.length === 0 && !loading) {
    return null; // Don't show widget if no suggestions
  }

  return (
    <div className="glass-panel p-3 mb-3" data-testid="portfolio-insights-widget">
      <div 
        className="flex items-center justify-between mb-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-white">Portfolio Insights</h3>
          {suggestions.length > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-purple-500/30 text-purple-300 rounded">
              {suggestions.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button 
            onClick={(e) => { e.stopPropagation(); fetchSuggestions(); }}
            className="p-1 hover:bg-zinc-700 rounded transition-colors"
            disabled={loading}
          >
            <RefreshCw className={`w-3 h-3 text-zinc-500 ${loading ? 'animate-spin' : ''}`} />
          </button>
          {expanded ? <ChevronDown className="w-4 h-4 text-zinc-500" /> : <ChevronRight className="w-4 h-4 text-zinc-500" />}
        </div>
      </div>
      
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="space-y-2 overflow-hidden"
          >
            {loading && suggestions.length === 0 ? (
              <div className="flex items-center justify-center py-3">
                <Loader2 className="w-4 h-4 text-zinc-500 animate-spin" />
              </div>
            ) : suggestions.length === 0 ? (
              <p className="text-xs text-zinc-500 text-center py-2">No suggestions - portfolio looks good!</p>
            ) : (
              suggestions.slice(0, 5).map((suggestion, idx) => {
                const config = getPriorityConfig(suggestion.priority);
                return (
                  <motion.div
                    key={suggestion.id || idx}
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: 20 }}
                    className={`p-2.5 rounded-lg ${config.bg} border ${config.border}`}
                  >
                    {/* Timestamp */}
                    <div className="flex items-center gap-2 mb-1 text-[9px] text-zinc-500">
                      <Clock className="w-2.5 h-2.5" />
                      <span>{formatTime(suggestion.created_at)}</span>
                      <span className={`px-1 py-0.5 rounded ${config.bg} ${config.text} font-medium uppercase`}>
                        {suggestion.priority}
                      </span>
                    </div>
                    
                    {/* Title */}
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div className="flex-1">
                        <span className="text-xs font-semibold text-white">
                          {suggestion.title}
                        </span>
                      </div>
                      <button
                        onClick={() => dismissSuggestion(suggestion.id)}
                        className="p-0.5 hover:bg-zinc-600 rounded opacity-50 hover:opacity-100 transition-opacity"
                        title="Dismiss"
                      >
                        <X className="w-3 h-3 text-zinc-400" />
                      </button>
                    </div>
                    
                    {/* Message */}
                    <p className="text-[10px] text-zinc-400 mb-1.5 line-clamp-2">
                      {suggestion.message}
                    </p>
                    
                    {/* Reasoning bullets */}
                    {suggestion.reasoning && suggestion.reasoning.length > 0 && (
                      <div className="text-[9px] text-zinc-500 space-y-0.5 mb-1.5">
                        {suggestion.reasoning.slice(0, 2).map((reason, i) => (
                          <div key={i} className="flex items-start gap-1">
                            <span className="text-zinc-600">•</span>
                            <span>{reason}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    
                    {/* Action row */}
                    <div className="flex items-center justify-between">
                      {suggestion.symbol && (
                        <button
                          onClick={() => onTickerClick?.(suggestion.symbol)}
                          className="flex items-center gap-1 px-1.5 py-0.5 bg-cyan-500/20 text-cyan-400 rounded text-[10px] font-medium hover:bg-cyan-500/30 transition-colors"
                        >
                          {suggestion.symbol}
                          <LineChart className="w-2.5 h-2.5" />
                        </button>
                      )}
                      {suggestion.suggested_action && (
                        <span className="text-[9px] text-zinc-500 italic truncate max-w-[60%]">
                          {suggestion.suggested_action}
                        </span>
                      )}
                    </div>
                  </motion.div>
                );
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// ===================== UNIFIED TRADE PIPELINE WIDGET =====================

const TradePipelineWidget = ({ 
  opportunities, 
  botTrades,
  onExecute, 
  onPass, 
  onTickerClick, 
  onViewChart, 
  executing, 
  onRefresh, 
  loading,
  onConfirmTrade,
  onRejectTrade,
  onCloseTrade
}) => {
  const [activeTab, setActiveTab] = useState('opportunities');
  
  const tabs = [
    { id: 'opportunities', label: 'New', count: opportunities?.length || 0, color: 'text-amber-400' },
    { id: 'pending', label: 'Pending', count: botTrades?.pending?.length || 0, color: 'text-cyan-400' },
    { id: 'open', label: 'Open', count: botTrades?.open?.length || 0, color: 'text-emerald-400' },
    { id: 'closed', label: 'Closed', count: botTrades?.closed?.length || 0, color: 'text-zinc-400' }
  ];

  const topOpportunities = (opportunities || [])
    .filter(o => o.verdict === 'TAKE' || o.verdict === 'WAIT')
    .slice(0, 5);

  return (
    <div className="p-2 rounded-lg relative"
         style={{
           background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95) 0%, rgba(26, 35, 50, 0.9) 100%)',
           backdropFilter: 'blur(16px)',
           WebkitBackdropFilter: 'blur(16px)',
           border: '1px solid rgba(0, 212, 255, 0.25)',
           boxShadow: '0 2px 15px rgba(0, 0, 0, 0.3), 0 0 20px var(--primary-glow)'
         }}>
      {/* Animated gradient border */}
      <div 
        className="absolute inset-0 rounded-lg pointer-events-none"
        style={{
          padding: '1px',
          background: 'linear-gradient(var(--gradient-angle, 135deg), var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
          WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
          opacity: 0.6,
          animation: 'gradient-rotate 6s linear infinite'
        }}
      />
      
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-5 rounded flex items-center justify-center"
               style={{
                 background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))',
                 boxShadow: '0 2px 8px var(--primary-glow)'
               }}>
            <Zap className="w-2.5 h-2.5 text-white" />
          </div>
          <span className="text-xs font-semibold text-white">Trade <span className="neon-text">Pipeline</span></span>
        </div>
        <button onClick={onRefresh} className="p-1 hover:bg-white/10 rounded transition-colors">
          <RefreshCw className={`w-2.5 h-2.5 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-0.5 mb-2 p-0.5 bg-black/30 rounded-lg">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-1.5 px-1 rounded-md text-[10px] font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-cyan-500/20 text-cyan-400 shadow-sm'
                : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/5'
            }`}
            data-testid={`pipeline-tab-${tab.id}`}
          >
            <span>{tab.label}</span>
            {tab.count > 0 && (
              <span className={`ml-1 ${activeTab === tab.id ? tab.color : 'text-zinc-500'}`}>
                ({tab.count})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[120px] max-h-[280px] overflow-y-auto">
        <AnimatePresence mode="wait">
          {/* New Opportunities Tab */}
          {activeTab === 'opportunities' && (
            <motion.div
              key="opportunities"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              className="space-y-2"
            >
              {topOpportunities.length === 0 ? (
                <div className="text-center py-6">
                  <Target className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-xs text-zinc-500">No new opportunities</p>
                  <p className="text-[10px] text-zinc-600 mt-1">Scanner is analyzing...</p>
                </div>
              ) : (
                topOpportunities.map((opp, idx) => (
                  <PipelineOpportunityCard
                    key={opp.timestamp || idx}
                    opportunity={opp}
                    rank={idx + 1}
                    onExecute={onExecute}
                    onPass={onPass}
                    onTickerClick={onTickerClick}
                    onViewChart={onViewChart}
                    executing={executing}
                  />
                ))
              )}
            </motion.div>
          )}

          {/* Pending Trades Tab */}
          {activeTab === 'pending' && (
            <motion.div
              key="pending"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              className="space-y-2"
            >
              {(botTrades?.pending || []).length === 0 ? (
                <div className="text-center py-6">
                  <Clock className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-xs text-zinc-500">No pending trades</p>
                  <p className="text-[10px] text-zinc-600 mt-1">Execute an opportunity to see it here</p>
                </div>
              ) : (
                (botTrades?.pending || []).map((trade, idx) => (
                  <PendingTradeCard
                    key={trade.id || idx}
                    trade={trade}
                    onConfirm={onConfirmTrade}
                    onReject={onRejectTrade}
                    onTickerClick={onTickerClick}
                  />
                ))
              )}
            </motion.div>
          )}

          {/* Open Trades Tab */}
          {activeTab === 'open' && (
            <motion.div
              key="open"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              className="space-y-2"
            >
              {(botTrades?.open || []).length === 0 ? (
                <div className="text-center py-6">
                  <Activity className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-xs text-zinc-500">No open trades</p>
                  <p className="text-[10px] text-zinc-600 mt-1">Active positions will appear here</p>
                </div>
              ) : (
                (botTrades?.open || []).map((trade, idx) => (
                  <OpenTradeCard
                    key={trade.id || idx}
                    trade={trade}
                    onClose={onCloseTrade}
                    onTickerClick={onTickerClick}
                  />
                ))
              )}
            </motion.div>
          )}

          {/* Closed Trades Tab */}
          {activeTab === 'closed' && (
            <motion.div
              key="closed"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              className="space-y-2"
            >
              {(botTrades?.closed || []).length === 0 ? (
                <div className="text-center py-6">
                  <DollarSign className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-xs text-zinc-500">No closed trades</p>
                  <p className="text-[10px] text-zinc-600 mt-1">Trade history will appear here</p>
                </div>
              ) : (
                (botTrades?.closed || []).slice(0, 10).map((trade, idx) => (
                  <ClosedTradeCard
                    key={trade.id || idx}
                    trade={trade}
                    onTickerClick={onTickerClick}
                  />
                ))
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

// Pipeline Opportunity Card (for New tab)
const PipelineOpportunityCard = ({ opportunity, rank, onExecute, onPass, onTickerClick, onViewChart, executing }) => {
  const verdictConfig = {
    'TAKE': { bg: 'bg-emerald-500/20', border: 'border-emerald-500/30', text: 'text-emerald-400', icon: Check },
    'WAIT': { bg: 'bg-amber-500/20', border: 'border-amber-500/30', text: 'text-amber-400', icon: Clock },
    'PASS': { bg: 'bg-red-500/20', border: 'border-red-500/30', text: 'text-red-400', icon: X }
  };
  
  const config = verdictConfig[opportunity.verdict] || verdictConfig.WAIT;
  const VerdictIcon = config.icon;
  
  // Format timestamp
  const formatTimestamp = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  };
  
  // Determine approaching vs confirmed
  const isApproaching = opportunity.setup_type?.includes('approaching') || 
                        opportunity.alert_data?.headline?.toLowerCase().includes('approaching') ||
                        opportunity.alert_data?.headline?.toLowerCase().includes('watch for');
  const isConfirmed = opportunity.alert_data?.headline?.toLowerCase().includes('confirmed') ||
                      (opportunity.alert_data?.headline?.toLowerCase().includes('breakout') && !isApproaching);
  
  return (
    <div 
      className={`relative p-2.5 rounded-lg ${config.bg} border ${config.border} hover:scale-[1.01] transition-transform`}
      data-testid={`pipeline-opportunity-${rank}`}
    >
      {/* Timestamp Row */}
      <div className="flex items-center gap-2 mb-1 text-[9px] text-zinc-500">
        <Clock className="w-2.5 h-2.5" />
        <span>{formatTimestamp(opportunity.alert_data?.created_at || opportunity.created_at)}</span>
        {isApproaching && (
          <span className="px-1 py-0.5 rounded bg-yellow-500/20 text-yellow-400 font-medium">WATCH</span>
        )}
        {isConfirmed && (
          <span className="px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-medium">CONFIRMED</span>
        )}
      </div>
      
      {/* Header Row */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-zinc-900/80 border border-cyan-500/50 flex items-center justify-center text-[10px] font-bold text-cyan-400">
            {rank}
          </span>
          <button 
            onClick={() => onTickerClick(opportunity.symbol)}
            className="text-sm font-bold text-white hover:text-cyan-400 transition-colors"
          >
            {opportunity.symbol}
          </button>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
            opportunity.direction === 'long' ? 'bg-emerald-500/30 text-emerald-400' : 'bg-red-500/30 text-red-400'
          }`}>
            {opportunity.direction?.toUpperCase()}
          </span>
        </div>
        <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded ${config.bg} ${config.text}`}>
          <VerdictIcon className="w-2.5 h-2.5" />
          <span className="text-[10px] font-bold">{opportunity.verdict}</span>
        </div>
      </div>
      
      {/* Setup Type & Stats */}
      <div className="flex items-center gap-2 text-[10px] text-zinc-400 mb-1.5">
        <span>{opportunity.setup_type?.replace(/_/g, ' ')}</span>
        {opportunity.alert_data?.risk_reward > 0 && (
          <span className="text-zinc-500">R:R {opportunity.alert_data.risk_reward.toFixed(1)}:1</span>
        )}
      </div>
      
      {/* AI Summary */}
      <p className="text-[10px] text-zinc-300 mb-2 line-clamp-2">
        {opportunity.summary || opportunity.coaching?.slice(0, 80)}
      </p>
      
      {/* Actions */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onExecute(opportunity)}
          disabled={executing}
          className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold transition-colors disabled:opacity-50 ${
            opportunity.verdict === 'TAKE' 
              ? 'bg-emerald-500 text-black hover:bg-emerald-400' 
              : 'bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30'
          }`}
        >
          {executing ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <ArrowRight className="w-2.5 h-2.5" />}
          Take
        </button>
        <button
          onClick={() => onPass(opportunity)}
          className="px-2.5 py-1 bg-zinc-700/50 text-zinc-400 rounded text-[10px] hover:bg-zinc-700 transition-colors"
        >
          Pass
        </button>
        {onViewChart && (
          <button
            onClick={() => onViewChart(opportunity.symbol)}
            className="p-1 rounded bg-zinc-700/50 hover:bg-zinc-700 transition-colors ml-auto"
            title="View chart"
          >
            <LineChart className="w-3 h-3 text-zinc-400" />
          </button>
        )}
      </div>
    </div>
  );
};

// Pending Trade Card
const PendingTradeCard = ({ trade, onConfirm, onReject, onTickerClick }) => (
  <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30">
    <div className="flex items-center justify-between mb-1.5">
      <div className="flex items-center gap-2">
        <button 
          onClick={() => onTickerClick(trade.symbol)}
          className="text-sm font-bold text-white hover:text-cyan-400 transition-colors"
        >
          {trade.symbol}
        </button>
        <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
          trade.direction === 'long' ? 'bg-emerald-500/30 text-emerald-400' : 'bg-red-500/30 text-red-400'
        }`}>
          {trade.direction?.toUpperCase()}
        </span>
      </div>
      <span className="text-[10px] text-cyan-400 font-medium">
        ${trade.entry_price?.toFixed(2)}
      </span>
    </div>
    <p className="text-[10px] text-zinc-400 mb-2">
      {trade.setup_type?.replace(/_/g, ' ')} • {trade.shares} shares
    </p>
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => onConfirm(trade.id)}
        className="flex items-center gap-1 px-2.5 py-1 bg-emerald-500 text-black rounded text-[10px] font-semibold hover:bg-emerald-400 transition-colors"
      >
        <Check className="w-2.5 h-2.5" />
        Confirm
      </button>
      <button
        onClick={() => onReject(trade.id)}
        className="px-2.5 py-1 bg-red-500/20 text-red-400 border border-red-500/30 rounded text-[10px] hover:bg-red-500/30 transition-colors"
      >
        Reject
      </button>
    </div>
  </div>
);

// Open Trade Card
const OpenTradeCard = ({ trade, onClose, onTickerClick }) => {
  const pnl = trade.unrealized_pnl || 0;
  const pnlPercent = trade.unrealized_pnl_pct || 0;
  const isProfit = pnl >= 0;
  
  return (
    <div className={`p-2.5 rounded-lg ${isProfit ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'} border`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <button 
            onClick={() => onTickerClick(trade.symbol)}
            className="text-sm font-bold text-white hover:text-cyan-400 transition-colors"
          >
            {trade.symbol}
          </button>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
            trade.direction === 'long' ? 'bg-emerald-500/30 text-emerald-400' : 'bg-red-500/30 text-red-400'
          }`}>
            {trade.direction?.toUpperCase()}
          </span>
        </div>
        <div className="text-right">
          <span className={`text-xs font-mono font-bold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
            {isProfit ? '+' : ''}{pnl.toFixed(2)}
          </span>
          <span className={`text-[9px] ml-1 ${isProfit ? 'text-emerald-400/70' : 'text-red-400/70'}`}>
            ({isProfit ? '+' : ''}{pnlPercent.toFixed(1)}%)
          </span>
        </div>
      </div>
      <div className="flex items-center justify-between text-[10px] text-zinc-400">
        <span>{trade.shares} @ ${trade.entry_price?.toFixed(2)}</span>
        <button
          onClick={() => onClose(trade.id)}
          className="px-2 py-0.5 bg-zinc-700/50 text-zinc-300 rounded hover:bg-zinc-700 transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
};

// Closed Trade Card
const ClosedTradeCard = ({ trade, onTickerClick }) => {
  const pnl = trade.realized_pnl || 0;
  const isProfit = pnl >= 0;
  
  return (
    <div 
      className="p-2 rounded-lg bg-zinc-800/50 hover:bg-zinc-800 cursor-pointer transition-colors"
      onClick={() => onTickerClick(trade.symbol)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-white">{trade.symbol}</span>
          <span className={`text-[9px] ${trade.direction === 'long' ? 'text-emerald-400' : 'text-red-400'}`}>
            {trade.direction?.toUpperCase()}
          </span>
        </div>
        <span className={`text-xs font-mono font-bold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}${pnl.toFixed(2)}
        </span>
      </div>
      <div className="text-[9px] text-zinc-500 mt-0.5">
        {new Date(trade.closed_at || trade.exit_time).toLocaleDateString()}
      </div>
    </div>
  );
};

// Keep old AICuratedWidget for backwards compatibility but mark as deprecated
const AICuratedWidget = ({ opportunities, onExecute, onPass, onTickerClick, onViewChart, executing, onRefresh, loading }) => {
  const topOpportunities = opportunities
    .filter(o => o.verdict === 'TAKE' || o.verdict === 'WAIT')
    .slice(0, 5);
  
  if (topOpportunities.length === 0) {
    return (
      <div className="p-4 bg-zinc-900/50 rounded-xl border border-white/5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Star className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-white">AI-Curated Opportunities</span>
          </div>
          <button onClick={onRefresh} className="p-1.5 hover:bg-zinc-700 rounded-lg transition-colors">
            <RefreshCw className={`w-3 h-3 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="text-center py-6">
          <Target className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
          <p className="text-xs text-zinc-500">No high-quality setups detected</p>
          <p className="text-[10px] text-zinc-600 mt-1">Scanner is analyzing the market...</p>
        </div>
      </div>
    );
  }
  
  return (
    <div className="p-2 rounded-lg relative"
         style={{
           background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95) 0%, rgba(26, 35, 50, 0.9) 100%)',
           backdropFilter: 'blur(16px)',
           WebkitBackdropFilter: 'blur(16px)',
           border: '1px solid rgba(0, 212, 255, 0.25)',
           boxShadow: '0 2px 15px rgba(0, 0, 0, 0.3), 0 0 20px var(--primary-glow)'
         }}>
      {/* Animated gradient border */}
      <div 
        className="absolute inset-0 rounded-lg pointer-events-none"
        style={{
          padding: '1px',
          background: 'linear-gradient(var(--gradient-angle, 135deg), var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
          WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
          opacity: 0.6,
          animation: 'gradient-rotate 6s linear infinite'
        }}
      />
      
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-5 rounded flex items-center justify-center"
               style={{
                 background: 'linear-gradient(135deg, var(--warning), var(--secondary-main))',
                 boxShadow: '0 2px 8px var(--warning-glow)'
               }}>
            <Star className="w-2.5 h-2.5 text-white" />
          </div>
          <div>
            <span className="text-xs font-semibold text-white">AI-Curated <span className="neon-text">Opportunities</span></span>
            <span className="text-[9px] text-zinc-500 ml-1.5">Top {topOpportunities.length}</span>
          </div>
        </div>
        <button onClick={onRefresh} className="p-1 hover:bg-white/10 rounded transition-colors">
          <RefreshCw className={`w-2.5 h-2.5 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      
      <div className="space-y-2">
        {topOpportunities.map((opp, idx) => (
          <PipelineOpportunityCard
            key={opp.timestamp || idx}
            opportunity={opp}
            rank={idx + 1}
            onExecute={onExecute}
            onPass={onPass}
            onTickerClick={onTickerClick}
            onViewChart={onViewChart}
            executing={executing}
          />
        ))}
      </div>
    </div>
  );
};

// ===================== CONFIRMATION DIALOG =====================

const ConfirmationDialog = ({ isOpen, trade, onConfirm, onCancel, loading }) => {
  if (!isOpen || !trade) return null;
  
  const isCloseAction = trade.isClose;
  const isAddAction = trade.isAdd;
  const actionLabel = isCloseAction ? 'Close Position' : isAddAction ? 'Add to Position' : 'Confirm Trade';
  const actionIcon = isCloseAction ? Minus : isAddAction ? Plus : Check;
  const ActionIcon = actionIcon;
  const iconBg = isCloseAction ? 'bg-red-500/20' : isAddAction ? 'bg-emerald-500/20' : 'bg-cyan-500/20';
  const iconColor = isCloseAction ? 'text-red-400' : isAddAction ? 'text-emerald-400' : 'text-cyan-400';
  const buttonBg = isCloseAction ? 'bg-red-500 hover:bg-red-400' : isAddAction ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-cyan-500 hover:bg-cyan-400';
  
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" data-testid="trade-confirmation-dialog">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-zinc-900 border border-white/10 rounded-xl p-5 max-w-md w-full mx-4"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className={`w-10 h-10 rounded-lg ${iconBg} flex items-center justify-center`}>
            <ActionIcon className={`w-5 h-5 ${iconColor}`} />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white">{actionLabel}</h3>
            <p className="text-xs text-zinc-500">
              {isCloseAction ? 'This will close your entire position' : isAddAction ? 'Add shares to existing position' : 'Review before executing'}
            </p>
          </div>
        </div>
        
        <div className="bg-zinc-800/50 rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xl font-bold text-white">{trade.symbol}</span>
            <span className={`px-2 py-1 rounded text-sm font-medium ${
              trade.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
            }`}>
              {isCloseAction ? 'CLOSE' : trade.direction?.toUpperCase()}
            </span>
          </div>
          
          <div className="grid grid-cols-2 gap-3 text-sm">
            {!isCloseAction && (
              <>
                <div>
                  <span className="text-zinc-500">Action</span>
                  <p className="text-white">{isAddAction ? 'Add to Position' : trade.setup_type?.replace(/_/g, ' ')}</p>
                </div>
                <div>
                  <span className="text-zinc-500">Size</span>
                  <p className="text-white">{trade.halfSize ? 'Half Position' : 'Full Position'}</p>
                </div>
              </>
            )}
            {isCloseAction && trade.shares && (
              <div className="col-span-2">
                <span className="text-zinc-500">Closing</span>
                <p className="text-white">{trade.shares} shares at market</p>
              </div>
            )}
            <div>
              <span className="text-zinc-500">{isCloseAction ? 'Market Price' : 'Entry'}</span>
              <p className="text-white font-mono">${trade.alert_data?.trigger_price?.toFixed(2) || 'Market'}</p>
            </div>
            {!isCloseAction && (
              <>
                <div>
                  <span className="text-zinc-500">Stop</span>
                  <p className="text-red-400 font-mono">${trade.alert_data?.stop_loss?.toFixed(2) || '--'}</p>
                </div>
                <div>
                  <span className="text-zinc-500">Target</span>
                  <p className="text-emerald-400 font-mono">${trade.alert_data?.target?.toFixed(2) || '--'}</p>
                </div>
                <div>
                  <span className="text-zinc-500">R:R</span>
                  <p className="text-white">{trade.alert_data?.risk_reward?.toFixed(1) || '--'}:1</p>
                </div>
              </>
            )}
          </div>
        </div>
        
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 bg-zinc-700 text-white rounded-lg hover:bg-zinc-600 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`flex-1 py-2.5 ${buttonBg} text-black font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2`}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ActionIcon className="w-4 h-4" />}
            {isCloseAction ? 'Close Position' : isAddAction ? 'Add Position' : 'Confirm Trade'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// ===================== BOT MODE DROPDOWN =====================

const BotModeDropdown = ({ mode, isRunning, onModeChange, onToggle, loading, botPnl, openCount, pendingCount }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [showTooltip, setShowTooltip] = useState(null);
  const dropdownRef = useRef(null);
  
  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
        setShowTooltip(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  const modes = [
    { 
      id: 'autonomous', 
      label: 'Auto', 
      icon: Zap, 
      color: 'amber',
      tooltip: 'Autonomous Mode: Bot executes trades automatically based on scanner signals. Best for active market hours with confirmed setups.'
    },
    { 
      id: 'confirmation', 
      label: 'Confirm', 
      icon: Shield, 
      color: 'cyan',
      tooltip: 'Confirmation Mode: Bot identifies opportunities but waits for your approval before executing. Recommended for learning.'
    },
    { 
      id: 'paused', 
      label: 'Paused', 
      icon: Pause, 
      color: 'zinc',
      tooltip: 'Paused Mode: Bot is completely stopped. No scanning or trading. Use during low-volume periods or when away.'
    }
  ];
  
  const currentMode = modes.find(m => m.id === mode) || modes[1];
  const CurrentIcon = currentMode.icon;
  
  const getButtonStyles = () => {
    if (!isRunning) {
      return 'bg-zinc-700/80 text-zinc-400 border-zinc-600';
    }
    switch (mode) {
      case 'autonomous':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/40';
      case 'confirmation':
        return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40';
      case 'paused':
        return 'bg-zinc-600 text-zinc-300 border-zinc-500';
      default:
        return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40';
    }
  };
  
  const handleModeSelect = (modeId) => {
    if (modeId === 'paused' && isRunning) {
      onToggle(); // Stop the bot
    } else if (!isRunning && modeId !== 'paused') {
      onModeChange(modeId);
      onToggle(); // Start the bot
    } else {
      onModeChange(modeId);
    }
    setIsOpen(false);
  };
  
  return (
    <div className="relative" ref={dropdownRef}>
      {/* Main Dropdown Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={loading}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${getButtonStyles()} hover:brightness-110`}
        data-testid="bot-mode-dropdown"
      >
        {loading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <CurrentIcon className="w-3.5 h-3.5" />
        )}
        <span>{isRunning ? currentMode.label : 'Bot Off'}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      
      {/* Stats Badge */}
      <div className="absolute -bottom-4 left-0 right-0 flex items-center justify-center gap-1.5 text-[9px] text-zinc-500 whitespace-nowrap">
        <span className={`font-mono font-semibold ${botPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {botPnl >= 0 ? '+' : ''}${botPnl.toFixed(0)}
        </span>
        <span>•</span>
        <span>{openCount} open</span>
        {pendingCount > 0 && (
          <>
            <span>•</span>
            <span className="text-amber-400">{pendingCount} pend</span>
          </>
        )}
      </div>
      
      {/* Dropdown Menu */}
      {isOpen && (
        <div 
          className="absolute left-0 top-full mt-2 w-52 rounded-xl overflow-hidden z-50"
          style={{
            background: 'rgba(21, 28, 36, 0.95)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)'
          }}
        >
          <div className="p-1.5 space-y-0.5">
            {modes.map((m) => {
              const Icon = m.icon;
              const isActive = mode === m.id;
              const isCurrentlyRunning = isRunning && mode === m.id;
              
              return (
                <div key={m.id} className="relative">
                  <button
                    onClick={() => handleModeSelect(m.id)}
                    onMouseEnter={() => setShowTooltip(m.id)}
                    onMouseLeave={() => setShowTooltip(null)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                      isActive 
                        ? m.color === 'amber' ? 'bg-amber-500/20 text-amber-400'
                          : m.color === 'cyan' ? 'bg-cyan-500/20 text-cyan-400'
                          : 'bg-zinc-600 text-zinc-300'
                        : 'text-zinc-400 hover:text-white hover:bg-white/5'
                    }`}
                    data-testid={`bot-mode-option-${m.id}`}
                  >
                    <Icon className="w-4 h-4" />
                    <span className="flex-1 text-left">{m.label}</span>
                    {isCurrentlyRunning && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    )}
                    {isActive && !isCurrentlyRunning && (
                      <Check className="w-3.5 h-3.5 text-current opacity-60" />
                    )}
                  </button>
                  
                  {/* Tooltip */}
                  {showTooltip === m.id && (
                    <div 
                      className="absolute left-full top-0 ml-2 w-56 p-3 rounded-lg text-[10px] text-zinc-300 z-50"
                      style={{
                        background: 'rgba(10, 10, 10, 0.95)',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.4)'
                      }}
                    >
                      <div className="flex items-center gap-1.5 mb-1.5 font-semibold text-white">
                        <Icon className={`w-3 h-3 ${
                          m.color === 'amber' ? 'text-amber-400' :
                          m.color === 'cyan' ? 'text-cyan-400' : 'text-zinc-400'
                        }`} />
                        {m.label} Mode
                      </div>
                      <p className="leading-relaxed">{m.tooltip}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          
          {/* Power Toggle at Bottom */}
          <div className="border-t border-white/10 p-2">
            <button
              onClick={() => { onToggle(); setIsOpen(false); }}
              disabled={loading}
              className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                isRunning 
                  ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' 
                  : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
              }`}
              data-testid="bot-power-toggle"
            >
              <Power className="w-3.5 h-3.5" />
              {isRunning ? 'Stop Bot' : 'Start Bot'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ===================== COMPREHENSIVE STATS HEADER =====================

const StatsHeader = ({ status, account, marketContext, positions, onToggle, onModeChange, loading }) => {
  const isRunning = status?.running;
  const mode = status?.mode || 'confirmation';
  const botPnl = status?.daily_stats?.net_pnl || 0;
  const openCount = status?.open_trades_count || 0;
  const pendingCount = status?.pending_trades_count || 0;
  
  // Account data
  const netLiq = account?.net_liquidation || 0;
  const accountPnl = account?.unrealized_pnl || 0;
  const totalPnl = botPnl + accountPnl;
  
  // Market regime colors
  const regimeConfig = {
    'Trending Up': { color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
    'Trending Down': { color: 'text-red-400', bg: 'bg-red-500/10' },
    'Consolidation': { color: 'text-amber-400', bg: 'bg-amber-500/10' },
    'High Volatility': { color: 'text-orange-400', bg: 'bg-orange-500/10' },
    'range_bound': { color: 'text-amber-400', bg: 'bg-amber-500/10' },
    'strong_uptrend': { color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
    'strong_downtrend': { color: 'text-red-400', bg: 'bg-red-500/10' },
    'volatile': { color: 'text-orange-400', bg: 'bg-orange-500/10' },
  };
  
  const regime = marketContext?.regime || 'Loading...';
  const regimeStyle = regimeConfig[regime] || { color: 'text-zinc-400', bg: 'bg-zinc-500/10' };
  
  const formatCurrency = (val) => {
    if (val === undefined || val === null) return '$--';
    return val >= 0 ? `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` 
                    : `-$${Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };
  
  return (
    <div style={{
      background: 'rgba(21, 28, 36, 0.85)',
      borderBottom: '1px solid rgba(255, 255, 255, 0.08)'
    }}>
      {/* Single Row: Account Stats + Bot Control */}
      <div className="flex items-center justify-between px-3 py-2">
        {/* Left: Net Liq + P&L + Positions */}
        <div className="flex items-center gap-4">
          {/* Net Liquidation */}
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-5 rounded flex items-center justify-center"
                 style={{
                   background: 'linear-gradient(135deg, var(--primary-main), var(--accent-main))',
                   boxShadow: '0 2px 8px var(--primary-glow)'
                 }}>
              <DollarSign className="w-3 h-3 text-white" />
            </div>
            <div>
              <p className="text-[8px] text-zinc-500 uppercase leading-none">Net Liq</p>
              <p className="text-xs font-bold font-mono text-white leading-tight" data-testid="net-liquidation">
                {formatCurrency(netLiq)}
              </p>
            </div>
          </div>
          
          {/* Divider */}
          <div className="w-px h-6" style={{ background: 'linear-gradient(180deg, transparent, rgba(255, 255, 255, 0.12), transparent)' }} />
          
          {/* Today's P&L */}
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-5 rounded flex items-center justify-center"
                 style={{
                   background: totalPnl >= 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                   boxShadow: totalPnl >= 0 ? '0 2px 8px var(--success-glow)' : '0 2px 8px var(--error-glow)'
                 }}>
              {totalPnl >= 0 ? <TrendingUp className="w-3 h-3 text-emerald-400" /> : <TrendingDown className="w-3 h-3 text-red-400" />}
            </div>
            <div>
              <p className="text-[9px] text-zinc-500 uppercase">Today P&L</p>
              <p className={`text-sm font-bold font-mono ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`} data-testid="todays-pnl">
                {totalPnl >= 0 ? '+' : ''}{formatCurrency(totalPnl)}
              </p>
            </div>
          </div>
          
          {/* Divider */}
          <div className="w-px h-6 bg-white/10" />
          
          {/* Positions */}
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-5 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Briefcase className="w-3 h-3 text-purple-400" />
            </div>
            <div>
              <p className="text-[8px] text-zinc-500 uppercase">Positions</p>
              <p className="text-xs font-bold font-mono text-white" data-testid="positions-count">
                {positions?.length || 0}
              </p>
            </div>
          </div>
          
          {/* Divider */}
          <div className="w-px h-6 bg-white/10" />
          
          {/* Market Regime */}
          <div className="flex items-center gap-1.5">
            <div className={`w-5 h-5 rounded-lg ${regimeStyle.bg} flex items-center justify-center`}>
              <Activity className={`w-3 h-3 ${regimeStyle.color}`} />
            </div>
            <div>
              <p className="text-[8px] text-zinc-500 uppercase">Market</p>
              <p className={`text-xs font-semibold ${regimeStyle.color}`} data-testid="market-regime">
                {regime.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
              </p>
            </div>
          </div>
        </div>
        
        {/* Right: Bot Mode Dropdown */}
        <div className="pb-3">
          <BotModeDropdown
            mode={mode}
            isRunning={isRunning}
            onModeChange={onModeChange}
            onToggle={onToggle}
            loading={loading}
            botPnl={botPnl}
            openCount={openCount}
            pendingCount={pendingCount}
          />
        </div>
      </div>
    </div>
  );
};

// ===================== MAIN COMPONENT =====================

const AICommandPanel = ({ 
  onTickerSelect,
  onViewChart,
  watchlist = [],
  alerts = [],
  opportunities = [],
  earnings = [],
  scanResults = [],
  isConnected = false,
  onRefresh,
  account = {},
  marketContext = {},
  positions = [],
  chartSymbol = 'SPY',
  setChartSymbol,
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsCoachingNotifications = []
}) => {
  // Chat state - persist to localStorage
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem('tradecommand_chat_history');
      if (saved) {
        const parsed = JSON.parse(saved);
        // Only restore messages from last 24 hours
        const dayAgo = Date.now() - (24 * 60 * 60 * 1000);
        return parsed.filter(msg => {
          if (!msg.timestamp) return false;
          const msgTime = new Date(msg.timestamp).getTime();
          return msgTime > dayAgo;
        });
      }
    } catch (e) {
      console.warn('Could not restore chat history:', e);
    }
    return [];
  });
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(() => {
    // Persist session ID too so AI has context
    const saved = localStorage.getItem('tradecommand_session_id');
    if (saved) return saved;
    const newId = `session_${Date.now()}`;
    localStorage.setItem('tradecommand_session_id', newId);
    return newId;
  });
  
  // Save messages to localStorage whenever they change
  useEffect(() => {
    try {
      if (messages.length > 0) {
        // Keep only last 50 messages to avoid storage bloat
        const toSave = messages.slice(-50);
        localStorage.setItem('tradecommand_chat_history', JSON.stringify(toSave));
      }
    } catch (e) {
      console.warn('Could not save chat history:', e);
    }
  }, [messages]);
  
  // Section expansion state - collapsed by default for more chat space
  const [expandedSections, setExpandedSections] = useState({
    positions: true,  // Show positions by default
    botTrades: false,
    earnings: false,
    watchlist: false
  });
  
  // Bot state
  const [botStatus, setBotStatus] = useState(null);
  const [botTrades, setBotTrades] = useState({ pending: [], open: [], closed: [], daily_stats: {} });
  const [botTradesTab, setBotTradesTab] = useState('open');
  const [botLoading, setBotLoading] = useState(false);
  
  // Coaching alerts state (for AI-Curated Widget)
  const [coachingAlerts, setCoachingAlerts] = useState([]);
  const [dismissedAlerts, setDismissedAlerts] = useState(new Set());
  const [lastCoachingFetch, setLastCoachingFetch] = useState(null);
  const [coachingLoading, setCoachingLoading] = useState(false);
  
  // AI Accuracy Stats state
  const [accuracyStats, setAccuracyStats] = useState(null);
  const [showAccuracyPopover, setShowAccuracyPopover] = useState(false);
  
  // Confirmation dialog
  const [confirmDialog, setConfirmDialog] = useState({ isOpen: false, trade: null });
  const [executing, setExecuting] = useState(false);
  
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Toggle section
  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };
  
  // ===================== BOT API CALLS =====================
  
  const fetchBotStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/trading-bot/status`);
      const data = await res.json();
      if (data.success) {
        setBotStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch bot status:', err);
    }
  }, []);
  
  const fetchBotTrades = useCallback(async () => {
    try {
      const res = await api.get('/api/trading-bot/trades/all');
      if (res.data?.success) {
        setBotTrades(res.data);
      }
    } catch (err) {
      // Silent fail
    }
  }, []);
  
  // Fetch AI Accuracy Stats
  const fetchAccuracyStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/assistant/accuracy-stats?days=7`);
      const data = await res.json();
      if (data.available) {
        setAccuracyStats(data);
      }
    } catch (err) {
      console.debug('Accuracy stats fetch failed:', err);
    }
  }, []);
  
  const toggleBot = async () => {
    setBotLoading(true);
    try {
      const endpoint = botStatus?.running ? 'stop' : 'start';
      await fetch(`${API_URL}/api/trading-bot/${endpoint}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(botStatus?.running ? 'Bot stopped' : 'Bot started');
    } catch (err) {
      toast.error('Failed to toggle bot');
    }
    setBotLoading(false);
  };
  
  const changeMode = async (mode) => {
    try {
      await fetch(`${API_URL}/api/trading-bot/mode/${mode}`, { method: 'POST' });
      await fetchBotStatus();
      toast.success(`Mode changed to ${mode}`);
    } catch (err) {
      toast.error('Failed to change mode');
    }
  };
  
  // ===================== COACHING ALERTS =====================
  
  const fetchCoachingAlerts = useCallback(async () => {
    setCoachingLoading(true);
    try {
      const params = lastCoachingFetch ? `?since=${lastCoachingFetch}` : '';
      const res = await fetch(`${API_URL}/api/assistant/coach/scanner-notifications${params}`);
      const data = await res.json();
      
      if (data.success && data.notifications?.length > 0) {
        const newAlerts = data.notifications.filter(a => !dismissedAlerts.has(a.timestamp));
        
        if (newAlerts.length > 0) {
          setCoachingAlerts(prev => {
            const existing = new Set(prev.map(a => a.timestamp));
            const unique = newAlerts.filter(a => !existing.has(a.timestamp));
            if (unique.length > 0) {
              // Show toast for new TAKE alerts only
              unique.filter(a => a.verdict === 'TAKE').forEach(alert => {
                toast.success(
                  `🎯 ${alert.symbol}: ${alert.verdict} - ${alert.summary?.slice(0, 40)}...`,
                  { duration: 6000 }
                );
              });
            }
            return [...prev, ...unique].slice(-15);
          });
        }
      }
      
      setLastCoachingFetch(data.timestamp);
    } catch (err) {
      console.error('Failed to fetch coaching alerts:', err);
    }
    setCoachingLoading(false);
  }, [lastCoachingFetch, dismissedAlerts]);
  
  // ===================== TRADE EXECUTION =====================
  
  const executeFromAlert = async (alert, halfSize = false) => {
    setConfirmDialog({
      isOpen: true,
      trade: { ...alert, halfSize }
    });
  };
  
  const confirmTrade = async () => {
    const trade = confirmDialog.trade;
    if (!trade) return;
    
    setExecuting(true);
    try {
      const payload = {
        symbol: trade.symbol,
        direction: trade.direction || 'long',
        setup_type: trade.setup_type,
        entry_price: trade.alert_data?.trigger_price || trade.alert_data?.current_price,
        stop_price: trade.alert_data?.stop_loss,
        target_prices: [trade.alert_data?.target],
        half_size: trade.halfSize,
        source: 'ai_coaching'
      };
      
      const res = await fetch(`${API_URL}/api/trading-bot/trades/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Trade submitted: ${trade.symbol} ${trade.direction?.toUpperCase()}`);
        
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `✅ **Trade Submitted**: ${trade.symbol} ${trade.direction?.toUpperCase()}\n\n` +
            `• Entry: $${payload.entry_price?.toFixed(2) || 'Market'}\n` +
            `• Stop: $${payload.stop_price?.toFixed(2)}\n` +
            `• Target: $${payload.target_prices[0]?.toFixed(2)}\n` +
            `• Size: ${trade.halfSize ? 'Half' : 'Full'}\n\n` +
            `Trade pending confirmation.`,
          timestamp: new Date().toISOString()
        }]);
        
        setDismissedAlerts(prev => new Set([...prev, trade.timestamp]));
        setCoachingAlerts(prev => prev.filter(a => a.timestamp !== trade.timestamp));
        
        await fetchBotTrades();
      } else {
        toast.error(data.detail || 'Failed to submit trade');
      }
    } catch (err) {
      toast.error('Failed to execute trade');
    }
    
    setExecuting(false);
    setConfirmDialog({ isOpen: false, trade: null });
  };
  
  const passOnAlert = (alert) => {
    setDismissedAlerts(prev => new Set([...prev, alert.timestamp]));
    setCoachingAlerts(prev => prev.filter(a => a.timestamp !== alert.timestamp));
    toast.info(`Passed on ${alert.symbol}`);
  };
  
  // ===================== TRADE COMMANDS =====================
  
  const parseTradeCommand = (text) => {
    const lowerText = text.toLowerCase();
    
    const takeMatch = lowerText.match(/(?:take|execute|buy|go long)\s+(?:the\s+)?(\w+)/);
    if (takeMatch) {
      const symbol = takeMatch[1].toUpperCase();
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) return { type: 'execute', alert };
    }
    
    const passMatch = lowerText.match(/(?:pass|skip|ignore)\s+(?:on\s+)?(\w+)/);
    if (passMatch) {
      const symbol = passMatch[1].toUpperCase();
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) return { type: 'pass', alert };
    }
    
    const halfMatch = lowerText.match(/(?:half\s+(?:size|position)?)\s*(\w+)?/);
    if (halfMatch) {
      const symbolInText = text.match(/\b([A-Z]{1,5})\b/);
      const symbol = halfMatch[1]?.toUpperCase() || symbolInText?.[1];
      const alert = coachingAlerts.find(a => a.symbol === symbol);
      if (alert) return { type: 'half', alert };
    }
    
    if (/(?:show|list|what are|my)\s*(?:open\s+)?trades/.test(lowerText)) {
      return { type: 'show_trades' };
    }
    
    if (/(?:stop|pause)\s+(?:the\s+)?bot/.test(lowerText)) {
      return { type: 'stop_bot' };
    }
    
    if (/(?:start|resume)\s+(?:the\s+)?bot/.test(lowerText)) {
      return { type: 'start_bot' };
    }
    
    return null;
  };

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Send message
  const sendMessage = useCallback(async (messageText = null) => {
    let text = (messageText || input.trim());
    if (!text || isLoading) return;

    const command = parseTradeCommand(text);
    if (command) {
      setInput('');
      
      switch (command.type) {
        case 'execute':
          executeFromAlert(command.alert, false);
          return;
        case 'half':
          executeFromAlert(command.alert, true);
          return;
        case 'pass':
          passOnAlert(command.alert);
          return;
        case 'show_trades':
          const tradesText = botTrades.open?.length > 0
            ? botTrades.open.map(t => 
                `• **${t.symbol}** ${t.direction?.toUpperCase()}: ${t.shares} sh @ $${t.entry_price?.toFixed(2)} | P&L: $${(t.unrealized_pnl || 0).toFixed(2)}`
              ).join('\n')
            : 'No open trades';
          setMessages(prev => [...prev, 
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: `📊 **Open Trades (${botTrades.open?.length || 0})**\n\n${tradesText}`, timestamp: new Date().toISOString() }
          ]);
          return;
        case 'stop_bot':
          if (botStatus?.running) await toggleBot();
          setMessages(prev => [...prev,
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: '🛑 Bot stopped.', timestamp: new Date().toISOString() }
          ]);
          return;
        case 'start_bot':
          if (!botStatus?.running) await toggleBot();
          setMessages(prev => [...prev,
            { role: 'user', content: text, timestamp: new Date().toISOString() },
            { role: 'assistant', content: '▶️ Bot started.', timestamp: new Date().toISOString() }
          ]);
          return;
        default:
          break;
      }
    }

    const tickerMatch = text.match(/^(\$?[A-Z]{1,5})$/);
    if (tickerMatch) {
      const sym = tickerMatch[1].replace('$', '');
      text = `Give me a full analysis on ${sym}. Include current outlook, key levels, any recent news, strategy fit, and a trade recommendation.`;
    }

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
          timestamp: new Date().toISOString(),
          validation: response.data.validation
        }]);
        // Refresh accuracy stats after each response
        fetchAccuracyStats();
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
  }, [input, isLoading, sessionId, botTrades, botStatus, coachingAlerts]);

  const handleTickerClick = useCallback((symbol) => {
    // Update chart to show clicked ticker
    if (setChartSymbol) {
      setChartSymbol(symbol);
    }
    onTickerSelect?.({ symbol, quote: {}, fromSearch: true });
  }, [onTickerSelect, setChartSymbol]);

  // ===================== POSITION QUICK ACTIONS =====================
  
  const handleClosePosition = useCallback(async (position) => {
    const { symbol, qty, quantity, side } = position;
    const shares = Math.abs(qty || quantity || 0);
    const direction = (qty || quantity || 0) > 0 ? 'long' : 'short';
    
    // Show confirmation dialog for close
    setConfirmDialog({
      isOpen: true,
      trade: {
        symbol,
        direction: direction === 'long' ? 'short' : 'long', // Opposite to close
        setup_type: 'position_close',
        shares,
        halfSize: false,
        alert_data: {
          trigger_price: position.current_price,
          stop_loss: null,
          target: null,
        },
        isClose: true
      }
    });
  }, []);
  
  const handleAddToPosition = useCallback(async (position) => {
    const { symbol, qty, quantity } = position;
    const direction = (qty || quantity || 0) > 0 ? 'long' : 'short';
    
    // Open trade modal for adding to position
    setConfirmDialog({
      isOpen: true,
      trade: {
        symbol,
        direction,
        setup_type: 'position_add',
        halfSize: true, // Default to half size for adds
        alert_data: {
          trigger_price: position.current_price,
          stop_loss: position.avg_entry_price * (direction === 'long' ? 0.95 : 1.05), // 5% stop
          target: position.current_price * (direction === 'long' ? 1.05 : 0.95), // 5% target
        },
        isAdd: true
      }
    });
  }, []);
  
  const handleSetPriceAlert = useCallback(async (position) => {
    const { symbol, current_price, avg_entry_price } = position;
    
    try {
      // Set a price alert at 5% above and below current price
      const abovePrice = current_price * 1.05;
      const belowPrice = current_price * 0.95;
      
      await api.post('/api/ib/alerts/price/set', {
        symbol,
        target_price: abovePrice,
        direction: 'above'
      });
      
      await api.post('/api/ib/alerts/price/set', {
        symbol,
        target_price: belowPrice,
        direction: 'below'
      });
      
      toast.success(`Price alerts set for ${symbol}`, {
        description: `Alert above $${abovePrice.toFixed(2)} and below $${belowPrice.toFixed(2)}`
      });
      
      // Add confirmation message to chat
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `🔔 **Price Alerts Set for ${symbol}**\n\n` +
          `• Alert when price goes **above** $${abovePrice.toFixed(2)} (+5%)\n` +
          `• Alert when price goes **below** $${belowPrice.toFixed(2)} (-5%)\n\n` +
          `Current price: $${current_price.toFixed(2)} | Avg cost: $${avg_entry_price.toFixed(2)}`,
        timestamp: new Date().toISOString()
      }]);
    } catch (err) {
      toast.error('Failed to set price alert');
    }
  }, []);

  // ===================== TRADE PIPELINE HANDLERS =====================
  
  const handleConfirmPendingTrade = useCallback(async (tradeId) => {
    try {
      const response = await api.post(`/api/trading-bot/trades/${tradeId}/confirm`);
      if (response.data?.success) {
        toast.success('Trade confirmed and executed');
        // Refresh bot trades
        const tradesRes = await api.get('/api/trading-bot/trades');
        if (tradesRes.data) {
          setBotTrades(tradesRes.data);
        }
      }
    } catch (err) {
      toast.error('Failed to confirm trade');
    }
  }, []);

  const handleRejectPendingTrade = useCallback(async (tradeId) => {
    try {
      const response = await api.post(`/api/trading-bot/trades/${tradeId}/reject`);
      if (response.data?.success) {
        toast.success('Trade rejected');
        // Refresh bot trades
        const tradesRes = await api.get('/api/trading-bot/trades');
        if (tradesRes.data) {
          setBotTrades(tradesRes.data);
        }
      }
    } catch (err) {
      toast.error('Failed to reject trade');
    }
  }, []);

  const handleCloseBotTrade = useCallback(async (tradeId) => {
    try {
      const response = await api.post(`/api/trading-bot/trades/${tradeId}/close`);
      if (response.data?.success) {
        toast.success('Trade closed');
        // Refresh bot trades
        const tradesRes = await api.get('/api/trading-bot/trades');
        if (tradesRes.data) {
          setBotTrades(tradesRes.data);
        }
      }
    } catch (err) {
      toast.error('Failed to close trade');
    }
  }, []);

  // ===================== SYNC WEBSOCKET DATA =====================
  // Use WebSocket-pushed data when available, with fallback to API fetch
  
  useEffect(() => {
    // Sync bot status from WebSocket
    if (wsBotStatus) {
      setBotStatus({
        success: true,
        running: wsBotStatus.state === 'running',
        ...wsBotStatus
      });
    }
  }, [wsBotStatus]);
  
  useEffect(() => {
    // Sync bot trades from WebSocket
    if (wsBotTrades && wsBotTrades.length >= 0) {
      // Group trades by status
      const pending = wsBotTrades.filter(t => t.status === 'pending');
      const open = wsBotTrades.filter(t => t.status === 'open' || t.status === 'filled');
      const closed = wsBotTrades.filter(t => t.status === 'closed' || t.status === 'exited');
      
      setBotTrades({
        success: true,
        pending,
        open,
        closed,
        all: wsBotTrades,
        daily_stats: botTrades.daily_stats || {}
      });
    }
  }, [wsBotTrades]);
  
  useEffect(() => {
    // Sync coaching notifications from WebSocket
    if (wsCoachingNotifications && wsCoachingNotifications.length > 0) {
      setCoachingAlerts(prev => {
        // Merge new notifications, avoiding duplicates
        const existingIds = new Set(prev.map(n => n.id || n.timestamp));
        const newNotifications = wsCoachingNotifications.filter(n => !existingIds.has(n.id || n.timestamp));
        if (newNotifications.length > 0) {
          return [...newNotifications, ...prev].slice(0, 50);
        }
        return prev;
      });
    }
  }, [wsCoachingNotifications]);

  // Initial data fetch only (WebSocket handles subsequent updates)
  useEffect(() => {
    // Only fetch if no WebSocket data available
    if (!wsBotStatus) {
      fetchBotStatus();
    }
    if (!wsBotTrades || wsBotTrades.length === 0) {
      fetchBotTrades();
    }
    if (!wsCoachingNotifications || wsCoachingNotifications.length === 0) {
      fetchCoachingAlerts();
    }
    // Fetch accuracy stats on mount
    fetchAccuracyStats();
    // No polling intervals - WebSocket handles real-time updates
  }, []); // Only on mount

  const quickActions = [
    { label: 'My Trades', action: () => sendMessage('Show my open trades'), icon: Target },
    { label: 'Performance', action: () => sendMessage('Analyze my trading performance today.'), icon: TrendingUp },
    { label: 'Market', action: () => sendMessage("What's happening in the market today?"), icon: Activity },
    { label: 'Rules', action: () => sendMessage('Remind me of my key trading rules.'), icon: Shield },
  ];

  // Filter active coaching alerts
  const activeCoachingAlerts = coachingAlerts.filter(a => !dismissedAlerts.has(a.timestamp));

  return (
    <div className="flex flex-col h-full overflow-hidden rounded-xl relative" 
         style={{
           background: 'rgba(21, 28, 36, 0.9)',
           backdropFilter: 'blur(24px)',
           WebkitBackdropFilter: 'blur(24px)',
           border: '1px solid rgba(255, 255, 255, 0.1)',
           boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)'
         }}
         data-testid="ai-command-panel">
      {/* Animated gradient border */}
      <div 
        className="absolute inset-0 rounded-xl pointer-events-none"
        style={{
          padding: '1px',
          background: 'linear-gradient(var(--gradient-angle, 135deg), var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
          WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
          opacity: 0.5,
          animation: 'gradient-rotate 6s linear infinite'
        }}
      />
      
      {/* Confirmation Dialog */}
      <ConfirmationDialog
        isOpen={confirmDialog.isOpen}
        trade={confirmDialog.trade}
        onConfirm={confirmTrade}
        onCancel={() => setConfirmDialog({ isOpen: false, trade: null })}
        loading={executing}
      />
      
      {/* Header - COMPACT */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.08]"
           style={{
             background: 'linear-gradient(135deg, rgba(0, 212, 255, 0.08) 0%, transparent 50%, rgba(255, 46, 147, 0.04) 100%)'
           }}>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center"
               style={{
                 background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))',
                 boxShadow: '0 2px 12px var(--primary-glow-strong)'
               }}>
            <Bot className="w-3.5 h-3.5 text-white" />
          </div>
          <div>
            <h2 className="text-xs font-bold text-white">AI Trading <span className="neon-text">Assistant</span></h2>
            <p className="text-[9px] text-zinc-500 tracking-wide">Scanner • AI • Bot</p>
          </div>
        </div>
        
        {/* AI Accuracy Indicator */}
        <div className="relative">
          <button 
            onClick={() => {
              fetchAccuracyStats();
              setShowAccuracyPopover(!showAccuracyPopover);
            }}
            className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] transition-all hover:bg-white/5"
            style={{
              background: accuracyStats?.summary?.validation_rate >= 70 
                ? 'rgba(16, 185, 129, 0.15)' 
                : accuracyStats?.summary?.validation_rate >= 50
                  ? 'rgba(251, 191, 36, 0.15)'
                  : 'rgba(239, 68, 68, 0.15)',
              border: '1px solid',
              borderColor: accuracyStats?.summary?.validation_rate >= 70
                ? 'rgba(16, 185, 129, 0.3)'
                : accuracyStats?.summary?.validation_rate >= 50
                  ? 'rgba(251, 191, 36, 0.3)'
                  : 'rgba(239, 68, 68, 0.3)'
            }}
            data-testid="accuracy-indicator"
          >
            <Shield className="w-3 h-3" style={{
              color: accuracyStats?.summary?.validation_rate >= 70
                ? '#10b981'
                : accuracyStats?.summary?.validation_rate >= 50
                  ? '#fbbf24'
                  : '#ef4444'
            }} />
            <span style={{
              color: accuracyStats?.summary?.validation_rate >= 70
                ? '#10b981'
                : accuracyStats?.summary?.validation_rate >= 50
                  ? '#fbbf24'
                  : '#ef4444'
            }}>
              {accuracyStats?.summary?.validation_rate 
                ? `${accuracyStats.summary.validation_rate}%`
                : '--'}
            </span>
            <span className="text-zinc-500">accuracy</span>
          </button>
          
          {/* Accuracy Popover */}
          <AnimatePresence>
            {showAccuracyPopover && accuracyStats && (
              <motion.div
                initial={{ opacity: 0, y: -10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.95 }}
                transition={{ duration: 0.15 }}
                className="absolute right-0 top-full mt-2 w-72 rounded-lg shadow-2xl overflow-hidden z-50"
                style={{
                  background: 'rgba(21, 28, 36, 0.98)',
                  backdropFilter: 'blur(24px)',
                  border: '1px solid rgba(255, 255, 255, 0.1)'
                }}
              >
                <div className="p-3 border-b border-white/10">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Shield className="w-3.5 h-3.5 text-cyan-400" />
                      AI Accuracy Stats
                    </h3>
                    <span className="text-[9px] text-zinc-500">Last 7 days</span>
                  </div>
                  
                  {/* Main Stats */}
                  <div className="grid grid-cols-3 gap-2 mb-3">
                    <div className="text-center p-2 rounded-lg bg-white/5">
                      <div className="text-lg font-bold" style={{
                        color: accuracyStats.summary?.validation_rate >= 70 ? '#10b981' 
                             : accuracyStats.summary?.validation_rate >= 50 ? '#fbbf24' : '#ef4444'
                      }}>
                        {accuracyStats.summary?.validation_rate || 0}%
                      </div>
                      <div className="text-[9px] text-zinc-500">Accuracy</div>
                    </div>
                    <div className="text-center p-2 rounded-lg bg-white/5">
                      <div className="text-lg font-bold text-white">
                        {accuracyStats.summary?.total_queries || 0}
                      </div>
                      <div className="text-[9px] text-zinc-500">Queries</div>
                    </div>
                    <div className="text-center p-2 rounded-lg bg-white/5">
                      <div className="text-lg font-bold text-cyan-400">
                        {(accuracyStats.summary?.average_confidence * 100 || 0).toFixed(0)}%
                      </div>
                      <div className="text-[9px] text-zinc-500">Confidence</div>
                    </div>
                  </div>
                  
                  {/* By Intent */}
                  {accuracyStats.by_intent && Object.keys(accuracyStats.by_intent).length > 0 && (
                    <div className="mb-2">
                      <div className="text-[9px] text-zinc-500 uppercase tracking-wider mb-1">By Query Type</div>
                      <div className="space-y-1">
                        {Object.entries(accuracyStats.by_intent).slice(0, 4).map(([intent, stats]) => (
                          <div key={intent} className="flex items-center justify-between text-[10px]">
                            <span className="text-zinc-400 capitalize">{intent.replace('_', ' ')}</span>
                            <span className={stats.accuracy_rate >= 70 ? 'text-emerald-400' : stats.accuracy_rate >= 50 ? 'text-amber-400' : 'text-red-400'}>
                              {stats.accuracy_rate}% ({stats.total})
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Issue Breakdown */}
                  {accuracyStats.issue_breakdown && Object.keys(accuracyStats.issue_breakdown).length > 0 && (
                    <div>
                      <div className="text-[9px] text-zinc-500 uppercase tracking-wider mb-1">Common Issues</div>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(accuracyStats.issue_breakdown).slice(0, 3).map(([type, count]) => (
                          <span key={type} className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 text-[9px]">
                            {type.replace('_', ' ')}: {count}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                
                <div className="px-3 py-2 bg-black/20 text-[9px] text-zinc-500 flex items-center justify-between">
                  <span>Auto-validated responses</span>
                  <button 
                    onClick={() => setShowAccuracyPopover(false)}
                    className="text-zinc-400 hover:text-white"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
      
      {/* Comprehensive Stats Header */}
      <StatsHeader
        status={botStatus}
        account={account}
        marketContext={marketContext}
        positions={positions}
        onToggle={toggleBot}
        onModeChange={changeMode}
        loading={botLoading}
      />

      {/* Main Content - Two Column Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT: Chat Area (Compact - 40%) */}
        <div className="w-[40%] flex flex-col min-w-0 border-r border-white/5">
          {/* Chat Header with Clear Button */}
          {messages.length > 0 && (
            <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/5 bg-black/20">
              <span className="text-[10px] text-zinc-500">{messages.length} messages</span>
              <button
                onClick={() => {
                  setMessages([]);
                  localStorage.removeItem('tradecommand_chat_history');
                  localStorage.removeItem('tradecommand_session_id');
                }}
                className="text-[10px] text-zinc-500 hover:text-red-400 transition-colors flex items-center gap-1"
                data-testid="clear-chat-btn"
              >
                <Trash2 className="w-3 h-3" />
                Clear
              </button>
            </div>
          )}
          {/* Chat Messages - Above Input (Standard Chat Layout) */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3" data-testid="chat-messages">
            {messages.length === 0 && !isLoading ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-4">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-amber-500/20 flex items-center justify-center mb-3">
                  <Sparkles className="w-6 h-6 text-amber-400" />
                </div>
                <h3 className="text-sm font-semibold text-white mb-1">Ready to assist</h3>
                <p className="text-xs text-zinc-500 max-w-[200px]">
                  Ask about tickers or type "take NVDA"
                </p>
              </div>
            ) : (
              <>
                {messages.map((msg, idx) => (
                  <ChatMessage key={idx} message={msg} isUser={msg.role === 'user'} onTickerClick={handleTickerClick} onViewChart={onViewChart} />
                ))}
                {isLoading && (
                  <div className="flex items-center gap-3 text-zinc-400">
                    <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center">
                      <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                    </div>
                    <span className="text-sm">Analyzing...</span>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Chat Input at Bottom */}
          <div className="p-3 border-t border-white/5 bg-black/30">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              {quickActions.map((qa, idx) => (
                <QuickPill key={idx} label={qa.label} onClick={qa.action} loading={isLoading} icon={qa.icon} />
              ))}
            </div>
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder="Ask anything, type ticker, or 'take NVDA'..."
                className="input-glass flex-1"
                data-testid="ai-chat-input"
              />
              <button
                onClick={() => sendMessage()}
                disabled={!input.trim() || isLoading}
                className="btn-primary px-4 py-2.5 rounded-xl"
                data-testid="ai-chat-send"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
          
          {/* Live Chart - Below Chat */}
          <div className="border-t border-white/5" data-testid="inline-chart">
            <div className="flex items-center justify-between px-3 py-2 bg-black/40">
              <div className="flex items-center gap-2">
                <LineChart className="w-4 h-4 text-cyan-400" />
                <span className="text-xs font-semibold text-white">{chartSymbol || 'SPY'}</span>
                <span className="text-[10px] text-zinc-500">• Click any ticker to view</span>
              </div>
              <div className="flex items-center gap-1">
                {['SPY', 'QQQ', 'NVDA'].map(sym => (
                  <button
                    key={sym}
                    onClick={() => setChartSymbol(sym)}
                    className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                      chartSymbol === sym 
                        ? 'bg-cyan-500/20 text-cyan-400' 
                        : 'text-zinc-500 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    {sym}
                  </button>
                ))}
              </div>
            </div>
            <div className="h-[280px]">
              <TradingViewWidget symbol={chartSymbol || 'SPY'} />
            </div>
          </div>
        </div>

        {/* RIGHT: Trade Pipeline + Collapsible Sections (60%) */}
        <div className="w-[60%] bg-black/20 overflow-y-auto">
          {/* Unified Trade Pipeline Widget */}
          <div className="p-3">
            <TradePipelineWidget
              opportunities={activeCoachingAlerts}
              botTrades={botTrades}
              onExecute={(a) => executeFromAlert(a, false)}
              onPass={passOnAlert}
              onTickerClick={handleTickerClick}
              onViewChart={onViewChart}
              executing={executing}
              onRefresh={fetchCoachingAlerts}
              loading={coachingLoading}
              onConfirmTrade={handleConfirmPendingTrade}
              onRejectTrade={handleRejectPendingTrade}
              onCloseTrade={handleCloseBotTrade}
            />
            
            {/* Portfolio Insights Widget */}
            <PortfolioInsightsWidget 
              onTickerClick={handleTickerClick}
              onViewChart={onViewChart}
            />
          </div>
          
          {/* My Positions Section */}
          <div className="p-3 pt-0">
            <SectionHeader 
              icon={Briefcase} 
              title="My Positions" 
              count={positions?.length || 0}
              isExpanded={expandedSections.positions}
              onToggle={() => toggleSection('positions')}
              compact
            />
            <AnimatePresence>
              {expandedSections.positions && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 space-y-1.5 max-h-[250px] overflow-y-auto">
                    {positions && positions.length > 0 ? (
                      positions.map((pos, idx) => (
                        <PositionCard
                          key={pos.symbol || idx}
                          position={pos}
                          onTickerClick={handleTickerClick}
                          onViewChart={onViewChart}
                          onClosePosition={handleClosePosition}
                          onAddPosition={handleAddToPosition}
                          onSetAlert={handleSetPriceAlert}
                        />
                      ))
                    ) : (
                      <div className="text-center py-4">
                        <Briefcase className="w-6 h-6 text-zinc-600 mx-auto mb-1.5" />
                        <p className="text-[10px] text-zinc-500">No open positions</p>
                        <p className="text-[9px] text-zinc-600 mt-1">Execute trades to see them here</p>
                      </div>
                    )}
                  </div>
                  {positions && positions.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-white/5">
                      <div className="flex justify-between text-[10px]">
                        <span className="text-zinc-500">Total Unrealized P&L</span>
                        <span className={`font-bold font-mono ${
                          positions.reduce((sum, p) => sum + (p.unrealized_pnl || p.unrealized_pl || 0), 0) >= 0 
                            ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {positions.reduce((sum, p) => sum + (p.unrealized_pnl || p.unrealized_pl || 0), 0) >= 0 ? '+' : ''}
                          ${positions.reduce((sum, p) => sum + (p.unrealized_pnl || p.unrealized_pl || 0), 0).toFixed(2)}
                        </span>
                      </div>
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Earnings Section */}
          <div className="p-3 pt-0">
            <SectionHeader 
              icon={Calendar} 
              title="Earnings" 
              count={earnings.length}
              isExpanded={expandedSections.earnings}
              onToggle={() => toggleSection('earnings')}
              compact
            />
            <AnimatePresence>
              {expandedSections.earnings && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 space-y-1 max-h-[100px] overflow-y-auto">
                    {earnings.slice(0, 5).map((earn, idx) => (
                      <div 
                        key={idx}
                        onClick={() => onTickerSelect?.({ symbol: earn.symbol, quote: {} })}
                        className="flex items-center justify-between p-2 bg-zinc-800/50 rounded-lg hover:bg-zinc-800 cursor-pointer text-xs"
                      >
                        <span className="font-medium text-white">{earn.symbol}</span>
                        <span className="text-zinc-500">{earn.timing || 'BMO'}</span>
                      </div>
                    ))}
                    {earnings.length === 0 && (
                      <p className="text-[10px] text-zinc-600 text-center py-2">No upcoming earnings</p>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Watchlist Section */}
          <div className="p-3 pt-0">
            <SectionHeader 
              icon={Eye} 
              title="Watchlist" 
              count={watchlist.length}
              isExpanded={expandedSections.watchlist}
              onToggle={() => toggleSection('watchlist')}
              compact
            />
            <AnimatePresence>
              {expandedSections.watchlist && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 space-y-1 max-h-[100px] overflow-y-auto">
                    {watchlist.slice(0, 6).map((item, idx) => (
                      <div 
                        key={idx}
                        onClick={() => onTickerSelect?.({ symbol: item.symbol, quote: item })}
                        className="flex items-center justify-between p-2 bg-zinc-800/50 rounded-lg hover:bg-zinc-800 cursor-pointer text-xs"
                      >
                        <span className="font-medium text-white">{item.symbol}</span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-white">${formatPrice(item.price)}</span>
                          <span className={item.change_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                            {formatPercent(item.change_percent)}
                          </span>
                        </div>
                      </div>
                    ))}
                    {watchlist.length === 0 && (
                      <p className="text-[10px] text-zinc-600 text-center py-2">Watchlist empty</p>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AICommandPanel;
