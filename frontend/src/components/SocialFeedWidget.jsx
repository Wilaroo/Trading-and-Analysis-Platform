/**
 * SocialFeedWidget - TweetDeck-style Multi-Panel Twitter/X Wall for Command Center
 * 
 * Three view modes:
 *   1. Wall View (DEFAULT) - 4 embedded timelines side-by-side (TweetDeck style)
 *   2. Single Feed View - One timeline at a time with handle selector
 *   3. Ticker View - Compact grid of all handles
 * 
 * Prioritized handles: @faststocknewss, @Deltaone, @unusual_whales, @TruthTrumpPosts
 * AI Sentiment Analysis: Paste tweet text for AI-powered analysis.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, ChevronLeft, ChevronRight, Maximize2, Minimize2,
  ChevronDown, TrendingUp, TrendingDown, Minus, AlertTriangle,
  Loader, Zap, BarChart3, LayoutGrid,
  MessageSquare, ExternalLink, ArrowLeftRight, RefreshCw
} from 'lucide-react';
import { safeGet, safePost } from '../utils/api';

const REFRESH_INTERVAL_MS = 90000; // 90 seconds

const CATEGORY_COLORS = {
  news: '#3b82f6',
  'short-seller': '#ef4444',
  trading: '#10b981',
  analysis: '#8b5cf6',
  research: '#f59e0b',
  earnings: '#06b6d4',
  education: '#ec4899',
  flow: '#f97316',
  political: '#dc2626',
};

const SENTIMENT_CONFIG = {
  BULLISH: { color: 'text-emerald-400', bg: 'bg-emerald-500/15', border: 'border-emerald-500/30', icon: TrendingUp },
  BEARISH: { color: 'text-red-400', bg: 'bg-red-500/15', border: 'border-red-500/30', icon: TrendingDown },
  NEUTRAL: { color: 'text-zinc-400', bg: 'bg-zinc-500/15', border: 'border-zinc-500/30', icon: Minus },
};

const XLogo = ({ className = "w-3 h-3", style = {} }) => (
  <svg viewBox="0 0 24 24" className={`${className} fill-current`} style={style}>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

// ── Twitter Embed ──────────────────────────────────────────────
const TwitterTimeline = ({ handle, height = 450, refreshKey = 0 }) => {
  const containerRef = useRef(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setError(false);
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = '';

    const loadTimeline = () => {
      if (window.twttr?.widgets) {
        window.twttr.widgets.createTimeline(
          { sourceType: 'profile', screenName: handle },
          container,
          { height, theme: 'dark', chrome: 'noheader nofooter noborders transparent', dnt: true, tweetLimit: 10 }
        ).then((el) => {
          setLoaded(true);
          if (!el) setError(true);
        }).catch(() => setError(true));
      } else {
        setError(true);
      }
    };

    if (window.twttr?.widgets) {
      loadTimeline();
    } else {
      const existing = document.querySelector('script[src*="platform.twitter.com/widgets.js"]');
      if (existing) {
        setTimeout(loadTimeline, 500);
      } else {
        const script = document.createElement('script');
        script.src = 'https://platform.twitter.com/widgets.js';
        script.async = true;
        script.charset = 'utf-8';
        script.onload = () => setTimeout(loadTimeline, 300);
        script.onerror = () => setError(true);
        document.head.appendChild(script);
      }
    }

    return () => { if (container) container.innerHTML = ''; };
  }, [handle, height, refreshKey]);

  return (
    <div className="relative" style={{ minHeight: 200 }} data-testid={`twitter-timeline-${handle}`}>
      {!loaded && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-900/50">
          <div className="flex flex-col items-center gap-2 text-zinc-500">
            <Loader className="w-4 h-4 animate-spin" />
            <span className="text-[10px]">Loading @{handle}...</span>
          </div>
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center justify-center py-10 gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <p className="text-[10px] text-zinc-500">Timeline unavailable</p>
          <a
            href={`https://x.com/${handle}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
          >
            Open @{handle} on X <ExternalLink className="w-2.5 h-2.5" />
          </a>
        </div>
      )}
      <div ref={containerRef} />
    </div>
  );
};

// ── Panel Swap Dropdown ────────────────────────────────────────
const PanelSwapDropdown = ({ currentHandle, allHandles, wallHandles, onSwap }) => {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef(null);
  const available = allHandles.filter(h => !wallHandles.includes(h.handle) || h.handle === currentHandle);

  useEffect(() => {
    const close = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(!open)}
        className="p-0.5 rounded text-zinc-500 hover:text-white transition-colors"
        data-testid={`panel-swap-${currentHandle}`}
      >
        <ArrowLeftRight className="w-3 h-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-5 z-50 w-48 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl py-1 max-h-60 overflow-y-auto">
          {available.map(h => (
            <button
              key={h.handle}
              onClick={() => { onSwap(h.handle); setOpen(false); }}
              className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-zinc-700/50 transition-colors ${
                h.handle === currentHandle ? 'text-sky-400' : 'text-zinc-300'
              }`}
              data-testid={`swap-option-${h.handle}`}
            >
              <div className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: CATEGORY_COLORS[h.category] || '#6b7280' }}
              />
              <span className="truncate">@{h.handle}</span>
              <span className="text-[9px] text-zinc-500 ml-auto flex-shrink-0">{h.category}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Time-ago helper ────────────────────────────────────────────
const timeAgo = (ts) => {
  if (!ts) return '';
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 10) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
};

// ── Wall Panel (single column in TweetDeck) ────────────────────
const WallPanel = ({ handle, allHandles, wallHandles, onSwap, panelHeight, refreshSignal }) => {
  const info = allHandles.find(h => h.handle === handle);
  const catColor = CATEGORY_COLORS[info?.category] || '#6b7280';
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastRefresh, setLastRefresh] = useState(Date.now());
  const [isPulsing, setIsPulsing] = useState(false);
  const [timeAgoText, setTimeAgoText] = useState('just now');

  // Auto-refresh on interval
  useEffect(() => {
    const interval = setInterval(() => {
      setRefreshKey(k => k + 1);
      setLastRefresh(Date.now());
      setIsPulsing(true);
      setTimeout(() => setIsPulsing(false), 2000);
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [handle]);

  // External refresh signal (from "Refresh All")
  useEffect(() => {
    if (refreshSignal > 0) {
      setRefreshKey(k => k + 1);
      setLastRefresh(Date.now());
      setIsPulsing(true);
      setTimeout(() => setIsPulsing(false), 2000);
    }
  }, [refreshSignal]);

  // Update time-ago text every 10s
  useEffect(() => {
    const t = setInterval(() => setTimeAgoText(timeAgo(lastRefresh)), 10000);
    setTimeAgoText(timeAgo(lastRefresh));
    return () => clearInterval(t);
  }, [lastRefresh]);

  const handleManualRefresh = () => {
    setRefreshKey(k => k + 1);
    setLastRefresh(Date.now());
    setIsPulsing(true);
    setTimeout(() => setIsPulsing(false), 2000);
  };

  return (
    <div
      className={`flex flex-col bg-zinc-900/70 rounded-lg overflow-hidden transition-all duration-500 ${
        isPulsing ? 'shadow-lg' : ''
      }`}
      style={{
        border: isPulsing
          ? `1.5px solid ${catColor}`
          : '1px solid rgba(63, 63, 70, 0.5)',
        boxShadow: isPulsing ? `0 0 16px ${catColor}30, inset 0 0 8px ${catColor}08` : 'none',
      }}
      data-testid={`wall-panel-${handle}`}
    >
      {/* Panel header */}
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-zinc-800/80 bg-zinc-900">
        <div className="flex items-center gap-1.5 min-w-0">
          <div className="relative w-4 h-4 rounded flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: `${catColor}20`, border: `1px solid ${catColor}40` }}
          >
            <XLogo className="w-2.5 h-2.5" style={{ color: catColor }} />
            {/* Live dot */}
            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          </div>
          <a
            href={`https://x.com/${handle}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] font-semibold text-white hover:text-sky-400 transition-colors truncate"
          >
            @{handle}
          </a>
          <span className="text-[8px] px-1 py-0.5 rounded font-medium capitalize flex-shrink-0"
            style={{ backgroundColor: `${catColor}15`, color: catColor, border: `1px solid ${catColor}25` }}
          >
            {info?.category}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[8px] text-zinc-600 font-mono" data-testid={`refresh-time-${handle}`}>
            {timeAgoText}
          </span>
          <button
            onClick={handleManualRefresh}
            className="p-0.5 rounded text-zinc-500 hover:text-emerald-400 transition-colors"
            title="Refresh feed"
            data-testid={`panel-refresh-${handle}`}
          >
            <RefreshCw className={`w-3 h-3 ${isPulsing ? 'animate-spin text-emerald-400' : ''}`} />
          </button>
          <PanelSwapDropdown
            currentHandle={handle}
            allHandles={allHandles}
            wallHandles={wallHandles}
            onSwap={(newHandle) => onSwap(handle, newHandle)}
          />
        </div>
      </div>

      {/* Refresh pulse bar */}
      {isPulsing && (
        <div className="h-0.5 w-full overflow-hidden">
          <div className="h-full animate-pulse rounded-full" style={{ backgroundColor: catColor, opacity: 0.6 }} />
        </div>
      )}

      {/* Timeline */}
      <div className="flex-1 overflow-hidden" style={{ height: panelHeight }}>
        <TwitterTimeline handle={handle} height={panelHeight} refreshKey={refreshKey} />
      </div>
    </div>
  );
};

// ── Sentiment Analysis Card ────────────────────────────────────
const SentimentCard = ({ analysis }) => {
  if (!analysis) return null;
  const config = SENTIMENT_CONFIG[analysis.sentiment] || SENTIMENT_CONFIG.NEUTRAL;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`${config.bg} ${config.border} border rounded-lg p-3 space-y-2`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${config.color}`} />
          <span className={`text-sm font-bold ${config.color}`}>{analysis.sentiment}</span>
          <span className="text-[10px] text-zinc-500 font-mono">
            {(analysis.confidence * 100).toFixed(0)}% conf
          </span>
        </div>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
          analysis.market_impact === 'HIGH' ? 'bg-red-500/20 text-red-400' :
          analysis.market_impact === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
          'bg-zinc-500/20 text-zinc-400'
        }`}>
          {analysis.market_impact} IMPACT
        </span>
      </div>

      <p className="text-xs text-zinc-300">{analysis.summary}</p>

      {analysis.tickers?.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-zinc-500">Tickers:</span>
          {analysis.tickers.map(t => (
            <span key={t} className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[10px] font-mono">
              ${t}
            </span>
          ))}
        </div>
      )}

      {analysis.action && (
        <div className="text-[10px] text-zinc-500 flex items-center gap-1">
          <Zap className="w-3 h-3 text-amber-400" />
          {analysis.action}
        </div>
      )}
    </motion.div>
  );
};

// ── Default handles (frontend fallback) ────────────────────────
const DEFAULT_HANDLES = [
  { handle: "faststocknewss", label: "Fast Stock News", category: "news", description: "Breaking stock market news and headlines", priority: 1 },
  { handle: "Deltaone", label: "DeltaOne", category: "news", description: "Real-time macro and market-moving headlines", priority: 2 },
  { handle: "unusual_whales", label: "Unusual Whales", category: "flow", description: "Unusual options activity and dark pool flow alerts", priority: 3 },
  { handle: "TruthTrumpPosts", label: "Trump Posts", category: "political", description: "Truth Social posts from Donald Trump", priority: 4 },
  { handle: "TheShortBear", label: "The Short Bear", category: "short-seller", description: "Short-selling research and bearish analysis" },
  { handle: "OracleNYSE", label: "Oracle NYSE", category: "analysis", description: "NYSE flow analysis and trade ideas" },
  { handle: "ttvresearch", label: "TTV Research", category: "research", description: "Technical and fundamental research" },
  { handle: "TradetheMatrix1", label: "Trade the Matrix", category: "trading", description: "Active day trading and momentum plays" },
  { handle: "ResearchGrizzly", label: "Grizzly Research", category: "short-seller", description: "Short-selling investigative research" },
  { handle: "HindendburgRes", label: "Hindenburg Research", category: "short-seller", description: "Activist short-selling research reports" },
  { handle: "Qullamaggie", label: "Qullamaggie", category: "trading", description: "Swing trading momentum breakouts" },
  { handle: "CitronResearch", label: "Citron Research", category: "short-seller", description: "Activist short-selling and market commentary" },
  { handle: "eWhispers", label: "Earnings Whispers", category: "earnings", description: "Earnings expectations, whisper numbers, and calendars" },
  { handle: "PaulJSingh", label: "Paul J Singh", category: "trading", description: "Small-cap trading and stock analysis" },
  { handle: "sspencer_smb", label: "Steve Spencer (SMB)", category: "education", description: "SMB Capital partner, trading education and coaching" },
  { handle: "szaman", label: "S. Zaman", category: "trading", description: "Active trading and market analysis" },
  { handle: "alphatrends", label: "Alpha Trends", category: "analysis", description: "Technical analysis and market trends" },
  { handle: "InvestorsLive", label: "InvestorsLive", category: "trading", description: "Day trading and small-cap momentum plays" },
  { handle: "TheShortSniper", label: "The Short Sniper", category: "short-seller", description: "Short-selling focused trade ideas" },
  { handle: "TheOneLanceB", label: "Lance B", category: "trading", description: "Day trading and market commentary" },
];

const DEFAULT_WALL_HANDLES = ["faststocknewss", "Deltaone", "unusual_whales", "TruthTrumpPosts"];

// ── Handle Chip ────────────────────────────────────────────────
const HandleChip = ({ handle, isActive, onClick }) => {
  const color = CATEGORY_COLORS[handle.category] || '#6b7280';
  return (
    <button
      onClick={onClick}
      data-testid={`handle-chip-${handle.handle}`}
      className={`flex-shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all whitespace-nowrap border ${
        isActive
          ? 'bg-white/10 border-white/30 text-white shadow-lg'
          : 'bg-zinc-800/60 border-zinc-700/50 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80'
      }`}
      style={isActive ? { borderColor: color, boxShadow: `0 0 8px ${color}30` } : {}}
    >
      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
      @{handle.handle}
    </button>
  );
};

// ═══════════════════════════════════════════════════════════════
// MAIN WIDGET
// ═══════════════════════════════════════════════════════════════
const SocialFeedWidget = () => {
  const [handles, setHandles] = useState(DEFAULT_HANDLES);
  const [wallHandles, setWallHandles] = useState(DEFAULT_WALL_HANDLES);
  const [activeHandle, setActiveHandle] = useState(DEFAULT_HANDLES[0]);
  const [viewMode, setViewMode] = useState('wall'); // 'wall', 'feed', 'ticker'
  const [isExpanded, setIsExpanded] = useState(true);
  const [showAnalyzer, setShowAnalyzer] = useState(false);
  const [analyzeText, setAnalyzeText] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [sentimentResult, setSentimentResult] = useState(null);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const scrollRef = useRef(null);

  useEffect(() => {
    safeGet('/api/social-feed/handles').then(data => {
      if (data?.handles?.length > 0) {
        setHandles(data.handles);
        // Set wall handles from prioritized items
        const prioritized = data.handles.filter(h => h.priority).sort((a, b) => a.priority - b.priority);
        if (prioritized.length >= 4) {
          setWallHandles(prioritized.slice(0, 4).map(h => h.handle));
        }
        setActiveHandle(data.handles[0]);
      }
    }).catch(() => {});
  }, []);

  const scrollHandles = (dir) => {
    scrollRef.current?.scrollBy({ left: dir * 200, behavior: 'smooth' });
  };

  const handleSwapPanel = (oldHandle, newHandle) => {
    setWallHandles(prev => prev.map(h => h === oldHandle ? newHandle : h));
  };

  const handleAnalyze = async () => {
    if (!analyzeText.trim()) return;
    setAnalyzing(true);
    setSentimentResult(null);
    try {
      const data = await safePost('/api/social-feed/analyze', {
        text: analyzeText,
        handle: activeHandle?.handle || ''
      });
      if (data?.analysis) setSentimentResult(data.analysis);
    } catch (e) { /* silent */ }
    finally { setAnalyzing(false); }
  };

  const viewModes = [
    { key: 'wall', label: 'Wall', icon: LayoutGrid },
    { key: 'feed', label: 'Feed', icon: MessageSquare },
    { key: 'ticker', label: 'Ticker', icon: BarChart3 },
  ];

  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden" data-testid="social-feed-widget">
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-zinc-900/80">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-sky-500/20 flex items-center justify-center">
            <XLogo className="w-3 h-3 text-sky-400" />
          </div>
          <h3 className="text-sm font-bold text-white">Social Feed</h3>
          <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 text-[10px] font-mono">
            {handles.length} HANDLES
          </span>
          {viewMode === 'wall' && (
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono flex items-center gap-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400"></span>
              </span>
              LIVE WALL
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {/* AI Analyze */}
          <button
            onClick={() => setShowAnalyzer(!showAnalyzer)}
            data-testid="social-feed-analyze-toggle"
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all border ${
              showAnalyzer
                ? 'bg-violet-500/20 text-violet-400 border-violet-500/30'
                : 'bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 border-zinc-700/50'
            }`}
          >
            <Brain className="w-3 h-3" />
            AI Analyze
          </button>

          {/* View mode buttons */}
          <div className="flex rounded-lg overflow-hidden border border-zinc-700/50">
            {viewModes.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setViewMode(key)}
                data-testid={`social-feed-view-${key}`}
                className={`flex items-center gap-1 px-2 py-1 text-[10px] font-medium transition-all ${
                  viewMode === key
                    ? 'bg-white/10 text-white'
                    : 'bg-zinc-800/60 text-zinc-500 hover:text-zinc-300'
                }`}
              >
                <Icon className="w-3 h-3" />
                {label}
              </button>
            ))}
          </div>

          {/* Refresh All (wall mode only) */}
          {viewMode === 'wall' && (
            <button
              onClick={() => setRefreshSignal(s => s + 1)}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-zinc-800/60 text-zinc-400 hover:text-emerald-400 border border-zinc-700/50 transition-all"
              title="Refresh all panels"
              data-testid="social-feed-refresh-all"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          )}

          {/* Collapse */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800/60 transition-all"
            data-testid="social-feed-expand-toggle"
          >
            {isExpanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {/* ── AI Analyzer Panel ── */}
            <AnimatePresence>
              {showAnalyzer && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-b border-white/5 bg-violet-500/5 px-3 py-2 space-y-2"
                >
                  <div className="flex items-center gap-2">
                    <Brain className="w-3.5 h-3.5 text-violet-400" />
                    <span className="text-xs font-medium text-violet-300">Paste tweet text for AI sentiment analysis</span>
                  </div>
                  <div className="flex gap-2">
                    <textarea
                      value={analyzeText}
                      onChange={(e) => setAnalyzeText(e.target.value)}
                      placeholder="Paste tweet content here... e.g. '$AAPL breaking out above resistance on heavy volume'"
                      className="flex-1 bg-zinc-800/80 border border-zinc-700/50 rounded-lg px-3 py-2 text-xs text-white placeholder-zinc-600 resize-none focus:outline-none focus:border-violet-500/50"
                      rows={2}
                      data-testid="social-feed-analyze-input"
                    />
                    <button
                      onClick={handleAnalyze}
                      disabled={analyzing || !analyzeText.trim()}
                      data-testid="social-feed-analyze-submit"
                      className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 border border-violet-500/30 text-xs font-medium disabled:opacity-40 transition-all self-end"
                    >
                      {analyzing ? <Loader className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                      Analyze
                    </button>
                  </div>
                  {sentimentResult && <SentimentCard analysis={sentimentResult} />}
                </motion.div>
              )}
            </AnimatePresence>

            {/* ── WALL VIEW (default) ── */}
            {viewMode === 'wall' && (
              <div className="p-2" data-testid="social-feed-wall">
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2">
                  {wallHandles.map(handle => (
                    <WallPanel
                      key={handle}
                      handle={handle}
                      allHandles={handles}
                      wallHandles={wallHandles}
                      onSwap={handleSwapPanel}
                      panelHeight={420}
                      refreshSignal={refreshSignal}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* ── SINGLE FEED VIEW ── */}
            {viewMode === 'feed' && (
              <>
                {/* Handle selector bar */}
                <div className="relative flex items-center px-2 py-1.5 border-b border-white/5 bg-zinc-900/40">
                  <button onClick={() => scrollHandles(-1)} className="p-0.5 text-zinc-500 hover:text-white flex-shrink-0">
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <div
                    ref={scrollRef}
                    className="flex-1 flex gap-1.5 overflow-x-auto px-1"
                    style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                  >
                    {handles.map(h => (
                      <HandleChip
                        key={h.handle}
                        handle={h}
                        isActive={activeHandle?.handle === h.handle}
                        onClick={() => setActiveHandle(h)}
                      />
                    ))}
                  </div>
                  <button onClick={() => scrollHandles(1)} className="p-0.5 text-zinc-500 hover:text-white flex-shrink-0">
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>

                <div className="p-2" style={{ maxHeight: 500, overflowY: 'auto' }}>
                  {activeHandle && (
                    <div>
                      <div className="flex items-center justify-between mb-2 px-1">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: CATEGORY_COLORS[activeHandle.category] || '#6b7280' }}
                          />
                          <span className="text-xs font-medium text-white">@{activeHandle.handle}</span>
                          <span className="text-[10px] text-zinc-500">{activeHandle.description}</span>
                        </div>
                        <a
                          href={`https://x.com/${activeHandle.handle}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-sky-400 hover:text-sky-300 flex items-center gap-1"
                        >
                          Open on X <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      </div>
                      <TwitterTimeline handle={activeHandle.handle} height={450} />
                    </div>
                  )}
                </div>
              </>
            )}

            {/* ── TICKER VIEW ── */}
            {viewMode === 'ticker' && (
              <div className="p-2">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="social-feed-ticker-grid">
                  {handles.map(h => {
                    const catColor = CATEGORY_COLORS[h.category] || '#6b7280';
                    const isPriority = h.priority;
                    return (
                      <a
                        key={h.handle}
                        href={`https://x.com/${h.handle}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`group flex items-center gap-2 p-2 rounded-lg border transition-all ${
                          isPriority
                            ? 'bg-zinc-800/60 border-zinc-600/50 hover:border-zinc-500/60 hover:bg-zinc-700/50'
                            : 'bg-zinc-800/40 border-zinc-700/30 hover:border-zinc-600/50 hover:bg-zinc-800/60'
                        }`}
                        data-testid={`ticker-card-${h.handle}`}
                      >
                        <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: `${catColor}15`, border: `1px solid ${catColor}30` }}
                        >
                          <XLogo className="w-3.5 h-3.5" style={{ color: catColor }} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium text-white truncate flex items-center gap-1">
                            @{h.handle}
                            {isPriority && (
                              <span className="text-[8px] px-1 rounded bg-amber-500/15 text-amber-400 font-mono">P{h.priority}</span>
                            )}
                          </div>
                          <div className="text-[10px] text-zinc-500 truncate">{h.label}</div>
                        </div>
                        <ExternalLink className="w-3 h-3 text-zinc-600 group-hover:text-zinc-400 flex-shrink-0 transition-colors" />
                      </a>
                    );
                  })}
                </div>

                {/* Category legend */}
                <div className="flex flex-wrap gap-2 mt-3 px-1">
                  {Object.entries(CATEGORY_COLORS).map(([cat, color]) => {
                    const count = handles.filter(h => h.category === cat).length;
                    if (count === 0) return null;
                    return (
                      <div key={cat} className="flex items-center gap-1">
                        <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
                        <span className="text-[9px] text-zinc-500 capitalize">{cat} ({count})</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SocialFeedWidget;
