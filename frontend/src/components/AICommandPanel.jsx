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
  LineChart
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { formatPrice, formatPercent } from '../utils/tradingUtils';

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
        <div className="text-[10px] text-zinc-600 mt-1">
          {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
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

// ===================== AI-CURATED OPPORTUNITIES WIDGET =====================

const CuratedOpportunityCard = ({ opportunity, rank, onExecute, onPass, onTickerClick, onViewChart, executing }) => {
  const verdictConfig = {
    'TAKE': { bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', text: 'text-emerald-400', icon: Check },
    'WAIT': { bg: 'bg-amber-500/20', border: 'border-amber-500/40', text: 'text-amber-400', icon: Clock },
    'PASS': { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-400', icon: X }
  };
  
  const config = verdictConfig[opportunity.verdict] || verdictConfig.WAIT;
  const VerdictIcon = config.icon;
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: rank * 0.1 }}
      className={`relative p-3 rounded-xl ${config.bg} border ${config.border} hover:scale-[1.02] transition-transform cursor-pointer`}
      data-testid={`curated-opportunity-${rank}`}
    >
      {/* Rank Badge */}
      <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-zinc-900 border-2 border-cyan-500 flex items-center justify-center">
        <span className="text-xs font-bold text-cyan-400">#{rank}</span>
      </div>
      
      {/* Header */}
      <div className="flex items-center justify-between mb-2 ml-4">
        <div className="flex items-center gap-2">
          <button 
            onClick={() => onTickerClick(opportunity.symbol)}
            className="text-lg font-bold text-white hover:text-cyan-400 transition-colors"
            title={`View ${opportunity.symbol} details`}
          >
            {opportunity.symbol}
          </button>
          {onViewChart && (
            <button
              onClick={() => onViewChart(opportunity.symbol)}
              className="p-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors"
              title={`View ${opportunity.symbol} chart`}
            >
              <LineChart className="w-3 h-3 text-amber-400" />
            </button>
          )}
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
            opportunity.direction === 'long' ? 'bg-emerald-500/30 text-emerald-400' : 'bg-red-500/30 text-red-400'
          }`}>
            {opportunity.direction?.toUpperCase()}
          </span>
        </div>
        <div className={`flex items-center gap-1 px-2 py-1 rounded-lg ${config.bg} ${config.text}`}>
          <VerdictIcon className="w-3 h-3" />
          <span className="text-xs font-bold">{opportunity.verdict}</span>
        </div>
      </div>
      
      {/* Setup & Stats */}
      <div className="flex items-center gap-3 text-[11px] text-zinc-400 mb-2 ml-4">
        <span>{opportunity.setup_type?.replace(/_/g, ' ')}</span>
        {opportunity.alert_data?.win_rate > 0 && (
          <span className="text-zinc-500">WR: {(opportunity.alert_data.win_rate * 100).toFixed(0)}%</span>
        )}
        {opportunity.alert_data?.risk_reward > 0 && (
          <span className="text-zinc-500">R:R {opportunity.alert_data.risk_reward.toFixed(1)}:1</span>
        )}
      </div>
      
      {/* AI Summary */}
      <p className="text-xs text-zinc-300 mb-3 ml-4 line-clamp-2">
        {opportunity.summary || opportunity.coaching?.slice(0, 100)}
      </p>
      
      {/* Quick Actions */}
      <div className="flex items-center gap-2 ml-4">
        {opportunity.verdict === 'TAKE' && (
          <button
            onClick={() => onExecute(opportunity)}
            disabled={executing}
            className="flex items-center gap-1 px-3 py-1.5 bg-emerald-500 text-black rounded-lg text-xs font-semibold hover:bg-emerald-400 transition-colors disabled:opacity-50"
          >
            {executing ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />}
            Execute
          </button>
        )}
        {opportunity.verdict === 'WAIT' && (
          <button
            onClick={() => onExecute(opportunity)}
            disabled={executing}
            className="flex items-center gap-1 px-3 py-1.5 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-lg text-xs font-medium hover:bg-amber-500/30 transition-colors disabled:opacity-50"
          >
            Execute Anyway
          </button>
        )}
        <button
          onClick={() => onPass(opportunity)}
          className="px-3 py-1.5 bg-zinc-700/50 text-zinc-400 rounded-lg text-xs hover:bg-zinc-700 transition-colors"
        >
          Pass
        </button>
      </div>
    </motion.div>
  );
};

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
          <CuratedOpportunityCard
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
  
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" data-testid="trade-confirmation-dialog">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-zinc-900 border border-white/10 rounded-xl p-5 max-w-md w-full mx-4"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
            <Target className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-white">Confirm Trade</h3>
            <p className="text-xs text-zinc-500">Review before executing</p>
          </div>
        </div>
        
        <div className="bg-zinc-800/50 rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xl font-bold text-white">{trade.symbol}</span>
            <span className={`px-2 py-1 rounded text-sm font-medium ${
              trade.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
            }`}>
              {trade.direction?.toUpperCase()}
            </span>
          </div>
          
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-zinc-500">Setup</span>
              <p className="text-white">{trade.setup_type?.replace(/_/g, ' ')}</p>
            </div>
            <div>
              <span className="text-zinc-500">Size</span>
              <p className="text-white">{trade.halfSize ? 'Half Position' : 'Full Position'}</p>
            </div>
            <div>
              <span className="text-zinc-500">Entry</span>
              <p className="text-white font-mono">${trade.alert_data?.trigger_price?.toFixed(2) || 'Market'}</p>
            </div>
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
            className="flex-1 py-2.5 bg-cyan-500 text-black font-semibold rounded-lg hover:bg-cyan-400 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Confirm Trade
          </button>
        </div>
      </motion.div>
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
      {/* Top Row: Account Stats */}
      <div className="flex items-center justify-between px-4 py-2.5" style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}>
        {/* Left: Net Liq + P&L + Positions */}
        <div className="flex items-center gap-6">
          {/* Net Liquidation */}
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
                 style={{
                   background: 'linear-gradient(135deg, var(--primary-main), var(--accent-main))',
                   boxShadow: '0 2px 15px var(--primary-glow)'
                 }}>
              <DollarSign className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-[9px] text-zinc-500 uppercase">Net Liq</p>
              <p className="text-sm font-bold font-mono text-white" data-testid="net-liquidation">
                {formatCurrency(netLiq)}
              </p>
            </div>
          </div>
          
          {/* Divider */}
          <div className="w-px h-8" style={{ background: 'linear-gradient(180deg, transparent, rgba(255, 255, 255, 0.15), transparent)' }} />
          
          {/* Today's P&L */}
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
                 style={{
                   background: totalPnl >= 0 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                   boxShadow: totalPnl >= 0 ? '0 2px 15px var(--success-glow)' : '0 2px 15px var(--error-glow)'
                 }}>
              {totalPnl >= 0 ? <TrendingUp className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_8px_rgba(16,185,129,0.6)]" /> : <TrendingDown className="w-4 h-4 text-red-400 drop-shadow-[0_0_8px_rgba(239,68,68,0.6)]" />}
            </div>
            <div>
              <p className="text-[9px] text-zinc-500 uppercase">Today P&L</p>
              <p className={`text-sm font-bold font-mono ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`} data-testid="todays-pnl">
                {totalPnl >= 0 ? '+' : ''}{formatCurrency(totalPnl)}
              </p>
            </div>
          </div>
          
          {/* Divider */}
          <div className="w-px h-8 bg-white/10" />
          
          {/* Positions */}
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Briefcase className="w-4 h-4 text-purple-400" />
            </div>
            <div>
              <p className="text-[9px] text-zinc-500 uppercase">Positions</p>
              <p className="text-sm font-bold font-mono text-white" data-testid="positions-count">
                {positions?.length || 0}
              </p>
            </div>
          </div>
        </div>
        
        {/* Right: Market Regime */}
        <div className="flex items-center gap-2">
          <div className={`w-7 h-7 rounded-lg ${regimeStyle.bg} flex items-center justify-center`}>
            <Activity className={`w-4 h-4 ${regimeStyle.color}`} />
          </div>
          <div>
            <p className="text-[9px] text-zinc-500 uppercase">Market</p>
            <p className={`text-sm font-semibold ${regimeStyle.color}`} data-testid="market-regime">
              {regime.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
            </p>
          </div>
        </div>
      </div>
      
      {/* Bottom Row: Bot Controls */}
      <div className="flex items-center justify-between px-4 py-1.5">
        {/* Left: Bot Status */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggle}
            disabled={loading}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
              isRunning 
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30' 
                : 'bg-zinc-700 text-zinc-300 border border-zinc-600 hover:bg-zinc-600'
            }`}
            data-testid="bot-toggle"
          >
            {loading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : isRunning ? (
              <Activity className="w-3 h-3" />
            ) : (
              <Power className="w-3 h-3" />
            )}
            Bot {isRunning ? 'ON' : 'OFF'}
          </button>
          
          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <span className={`font-mono font-semibold ${botPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {botPnl >= 0 ? '+' : ''}${botPnl.toFixed(0)}
            </span>
            <span>•</span>
            <span>{openCount} open</span>
            {pendingCount > 0 && (
              <>
                <span>•</span>
                <span className="text-amber-400">{pendingCount} pending</span>
              </>
            )}
          </div>
        </div>
        
        {/* Right: Mode Selector */}
        <div className="flex items-center gap-1">
          {['confirmation', 'autonomous', 'paused'].map(m => {
            const icons = { confirmation: Shield, autonomous: Zap, paused: Pause };
            const Icon = icons[m];
            const isActive = mode === m;
            const labels = { confirmation: 'Confirm', autonomous: 'Auto', paused: 'Paused' };
            return (
              <button
                key={m}
                onClick={() => onModeChange(m)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${
                  isActive
                    ? m === 'autonomous' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                      : m === 'confirmation' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                      : 'bg-zinc-600 text-zinc-300 border border-zinc-500'
                    : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
                }`}
                data-testid={`mode-${m}`}
              >
                <Icon className="w-3 h-3" />
                {labels[m]}
              </button>
            );
          })}
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
  // WebSocket-pushed data (replaces polling)
  wsBotStatus = null,
  wsBotTrades = [],
  wsCoachingNotifications = []
}) => {
  // Chat state
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(`session_${Date.now()}`);
  
  // Section expansion state - collapsed by default for more chat space
  const [expandedSections, setExpandedSections] = useState({
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
  }, [input, isLoading, sessionId, botTrades, botStatus, coachingAlerts]);

  const handleTickerClick = useCallback((symbol) => {
    onTickerSelect?.({ symbol, quote: {}, fromSearch: true });
  }, [onTickerSelect]);

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
        <div className="flex items-center gap-1.5">
          <span className={`neon-dot${isConnected ? '-success' : '-error'}`} style={{width: '6px', height: '6px'}} />
          <span className="text-[10px] text-zinc-500 font-medium">{isConnected ? 'Live' : 'Offline'}</span>
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
        {/* LEFT: Chat Area (Expanded) */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Chat Messages - Above Input (Standard Chat Layout) */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4" data-testid="chat-messages">
            {messages.length === 0 && !isLoading ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-8">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-500/20 to-amber-500/20 flex items-center justify-center mb-4">
                  <Sparkles className="w-8 h-8 text-amber-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Ready to assist</h3>
                <p className="text-sm text-zinc-500 max-w-xs">
                  Ask me anything about the market, analyze a ticker, or trade directly with commands like "take NVDA"
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
        </div>

        {/* RIGHT: AI-Curated Opportunities + Collapsible Sections */}
        <div className="w-80 border-l border-white/5 bg-black/20 overflow-y-auto">
          {/* AI-Curated Opportunities Widget */}
          <div className="p-3">
            <AICuratedWidget
              opportunities={activeCoachingAlerts}
              onExecute={(a) => executeFromAlert(a, false)}
              onPass={passOnAlert}
              onTickerClick={handleTickerClick}
              onViewChart={onViewChart}
              executing={executing}
              onRefresh={fetchCoachingAlerts}
              loading={coachingLoading}
            />
          </div>
          
          {/* Bot Trades Section */}
          <div className="p-3 pt-0">
            <SectionHeader 
              icon={Bot} 
              title="Bot Trades" 
              count={(botTrades.pending?.length || 0) + (botTrades.open?.length || 0)}
              isExpanded={expandedSections.botTrades}
              onToggle={() => toggleSection('botTrades')}
              compact
            />
            <AnimatePresence>
              {expandedSections.botTrades && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden"
                >
                  <div className="mt-2 space-y-1">
                    <div className="flex gap-1 mb-2">
                      {['pending', 'open', 'closed'].map(tab => (
                        <button
                          key={tab}
                          onClick={() => setBotTradesTab(tab)}
                          className={`flex-1 py-1 px-2 rounded text-[10px] font-medium ${
                            botTradesTab === tab
                              ? 'bg-cyan-500/20 text-cyan-400'
                              : 'text-zinc-500 hover:text-zinc-300'
                          }`}
                        >
                          {tab.charAt(0).toUpperCase() + tab.slice(1)} ({botTrades[tab]?.length || 0})
                        </button>
                      ))}
                    </div>
                    <div className="space-y-1 max-h-[150px] overflow-y-auto">
                      {(botTrades[botTradesTab] || []).slice(0, 5).map((trade, idx) => (
                        <div 
                          key={trade.id || idx}
                          className="flex items-center justify-between p-2 bg-zinc-800/50 rounded-lg hover:bg-zinc-800 cursor-pointer text-xs"
                          onClick={() => handleTickerClick(trade.symbol)}
                        >
                          <div>
                            <span className="font-medium text-white">{trade.symbol}</span>
                            <span className={`ml-1 text-[9px] ${trade.direction === 'long' ? 'text-emerald-400' : 'text-red-400'}`}>
                              {trade.direction?.toUpperCase()}
                            </span>
                          </div>
                          <span className={`font-mono ${(trade.realized_pnl || trade.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            ${(trade.realized_pnl || trade.unrealized_pnl || 0).toFixed(2)}
                          </span>
                        </div>
                      ))}
                      {(botTrades[botTradesTab] || []).length === 0 && (
                        <p className="text-[10px] text-zinc-600 text-center py-2">No {botTradesTab} trades</p>
                      )}
                    </div>
                  </div>
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
