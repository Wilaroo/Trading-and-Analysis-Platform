/**
 * SocialFeedWidget - Twitter/X Social Feed for Command Center
 * 
 * Displays embedded Twitter timelines for followed market handles.
 * Two view modes:
 *   1. Feed View - Vertical embedded timelines with handle selector
 *   2. Ticker View - Compact horizontal scrolling strip
 * 
 * AI Sentiment Analysis: Users can paste tweet text for AI-powered analysis.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Twitter, Brain, ChevronLeft, ChevronRight, Maximize2, Minimize2,
  Plus, X, Send, TrendingUp, TrendingDown, Minus, AlertTriangle,
  Loader, RefreshCw, Zap, BarChart3, Eye, EyeOff, Settings,
  MessageSquare, ExternalLink
} from 'lucide-react';
import api, { safeGet, safePost } from '../utils/api';

// Category colors matching the backend
const CATEGORY_COLORS = {
  news: '#3b82f6',
  'short-seller': '#ef4444',
  trading: '#10b981',
  analysis: '#8b5cf6',
  research: '#f59e0b',
  earnings: '#06b6d4',
  education: '#ec4899',
  flow: '#f97316',
};

const SENTIMENT_CONFIG = {
  BULLISH: { color: 'text-emerald-400', bg: 'bg-emerald-500/15', border: 'border-emerald-500/30', icon: TrendingUp },
  BEARISH: { color: 'text-red-400', bg: 'bg-red-500/15', border: 'border-red-500/30', icon: TrendingDown },
  NEUTRAL: { color: 'text-zinc-400', bg: 'bg-zinc-500/15', border: 'border-zinc-500/30', icon: Minus },
};

// Twitter Embed component
const TwitterTimeline = ({ handle, height = 500 }) => {
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
      if (window.twttr && window.twttr.widgets) {
        window.twttr.widgets.createTimeline(
          { sourceType: 'profile', screenName: handle },
          container,
          {
            height,
            theme: 'dark',
            chrome: 'noheader nofooter noborders transparent',
            dnt: true,
            tweetLimit: 10,
          }
        ).then((el) => {
          setLoaded(true);
          if (!el) setError(true);
        }).catch(() => setError(true));
      } else {
        setError(true);
      }
    };

    // Check if Twitter widget script is already loaded
    if (window.twttr && window.twttr.widgets) {
      loadTimeline();
    } else {
      // Load Twitter widget script
      const script = document.createElement('script');
      script.src = 'https://platform.twitter.com/widgets.js';
      script.async = true;
      script.charset = 'utf-8';
      script.onload = () => {
        // twttr.widgets.load may need a brief delay
        setTimeout(loadTimeline, 300);
      };
      script.onerror = () => setError(true);
      document.head.appendChild(script);
    }

    return () => {
      if (container) container.innerHTML = '';
    };
  }, [handle, height]);

  return (
    <div className="relative min-h-[200px]" data-testid={`twitter-timeline-${handle}`}>
      {!loaded && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-900/50">
          <div className="flex items-center gap-2 text-zinc-500">
            <Loader className="w-4 h-4 animate-spin" />
            <span className="text-xs">Loading @{handle}...</span>
          </div>
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <p className="text-xs text-zinc-500">Could not load timeline for @{handle}</p>
          <a
            href={`https://x.com/${handle}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
          >
            Open on X <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      )}
      <div ref={containerRef} className="twitter-timeline-container" />
    </div>
  );
};

// Handle chip/pill component
const HandleChip = ({ handle, isActive, onClick, category }) => {
  const color = CATEGORY_COLORS[category] || '#6b7280';
  return (
    <button
      onClick={onClick}
      data-testid={`handle-chip-${handle.handle}`}
      className={`flex-shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all whitespace-nowrap ${
        isActive
          ? 'bg-white/10 border-white/30 text-white shadow-lg'
          : 'bg-zinc-800/60 border-zinc-700/50 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80'
      } border`}
      style={isActive ? { borderColor: color, boxShadow: `0 0 8px ${color}30` } : {}}
    >
      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
      @{handle.handle}
    </button>
  );
};

// Sentiment Analysis Card
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

// Default handles (used as fallback when API is slow/unavailable)
const DEFAULT_HANDLES = [
  { handle: "faststocknewss", label: "Fast Stock News", category: "news", description: "Breaking stock market news and headlines" },
  { handle: "Deltaone", label: "DeltaOne", category: "news", description: "Real-time macro and market-moving headlines" },
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
  { handle: "unusual_whales", label: "Unusual Whales", category: "flow", description: "Unusual options activity and dark pool flow alerts" },
];

// Main Widget
const SocialFeedWidget = ({ compact = false }) => {
  const [handles, setHandles] = useState(DEFAULT_HANDLES);
  const [activeHandle, setActiveHandle] = useState(DEFAULT_HANDLES[0]);
  const [viewMode, setViewMode] = useState('feed'); // 'feed' or 'ticker'
  const [isExpanded, setIsExpanded] = useState(true);
  const [showAnalyzer, setShowAnalyzer] = useState(false);
  const [analyzeText, setAnalyzeText] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [sentimentResult, setSentimentResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  // Fetch handles on mount (merge with API if available)
  useEffect(() => {
    const fetchHandles = async () => {
      try {
        const data = await safeGet('/api/social-feed/handles');
        if (data?.handles?.length > 0) {
          setHandles(data.handles);
          setActiveHandle(data.handles[0]);
        }
      } catch (e) {
        // Use defaults already set
      }
    };
    fetchHandles();
  }, []);

  // Scroll handles left/right
  const scrollHandles = (direction) => {
    if (scrollRef.current) {
      scrollRef.current.scrollBy({ left: direction * 200, behavior: 'smooth' });
    }
  };

  // Analyze tweet text
  const handleAnalyze = async () => {
    if (!analyzeText.trim()) return;
    setAnalyzing(true);
    setSentimentResult(null);
    try {
      const data = await safePost('/api/social-feed/analyze', {
        text: analyzeText,
        handle: activeHandle?.handle || ''
      });
      if (data?.analysis) {
        setSentimentResult(data.analysis);
      }
    } catch (e) {
      console.error('Sentiment analysis failed:', e);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading || handles.length === 0) {
    return (
      <div className="bg-zinc-900/50 border border-white/10 rounded-xl p-4">
        <div className="flex items-center gap-2 text-zinc-500">
          <Loader className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading social feeds...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden" data-testid="social-feed-widget">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-zinc-900/80">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-md bg-sky-500/20 flex items-center justify-center">
            <svg viewBox="0 0 24 24" className="w-3 h-3 text-sky-400 fill-current">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </div>
          <h3 className="text-sm font-bold text-white">Social Feed</h3>
          <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 text-[10px] font-mono">
            {handles.length} HANDLES
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {/* AI Analyze toggle */}
          <button
            onClick={() => setShowAnalyzer(!showAnalyzer)}
            data-testid="social-feed-analyze-toggle"
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
              showAnalyzer
                ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
                : 'bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 border border-zinc-700/50'
            }`}
          >
            <Brain className="w-3 h-3" />
            AI Analyze
          </button>

          {/* View mode toggles */}
          <button
            onClick={() => setViewMode(viewMode === 'feed' ? 'ticker' : 'feed')}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-zinc-800/60 text-zinc-400 hover:text-zinc-200 border border-zinc-700/50 transition-all"
            data-testid="social-feed-view-toggle"
          >
            {viewMode === 'feed' ? (
              <><BarChart3 className="w-3 h-3" /> Ticker</>
            ) : (
              <><MessageSquare className="w-3 h-3" /> Feed</>
            )}
          </button>

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
            {/* Handle selector bar */}
            <div className="relative flex items-center px-2 py-1.5 border-b border-white/5 bg-zinc-900/40">
              <button
                onClick={() => scrollHandles(-1)}
                className="p-0.5 text-zinc-500 hover:text-white flex-shrink-0"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>

              <div
                ref={scrollRef}
                className="flex-1 flex gap-1.5 overflow-x-auto scrollbar-hide px-1"
                style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
              >
                {handles.map((h) => (
                  <HandleChip
                    key={h.handle}
                    handle={h}
                    isActive={activeHandle?.handle === h.handle}
                    onClick={() => setActiveHandle(h)}
                    category={h.category}
                  />
                ))}
              </div>

              <button
                onClick={() => scrollHandles(1)}
                className="p-0.5 text-zinc-500 hover:text-white flex-shrink-0"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            {/* AI Sentiment Analyzer Panel */}
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
                      placeholder="Paste tweet content here... e.g. '$AAPL breaking out above resistance on heavy volume, bullish engulfing candle forming'"
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

            {/* Main Content */}
            {viewMode === 'feed' ? (
              /* FEED VIEW - Embedded Twitter timeline */
              <div className="p-2" style={{ maxHeight: compact ? 350 : 500, overflowY: 'auto' }}>
                {activeHandle ? (
                  <div>
                    {/* Active handle info bar */}
                    <div className="flex items-center justify-between mb-2 px-1">
                      <div className="flex items-center gap-2">
                        <div
                          className="w-2 h-2 rounded-full"
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

                    {/* Embedded Timeline */}
                    <TwitterTimeline
                      handle={activeHandle.handle}
                      height={compact ? 300 : 450}
                    />
                  </div>
                ) : (
                  <div className="text-center py-8 text-zinc-500 text-sm">
                    Select a handle to view their feed
                  </div>
                )}
              </div>
            ) : (
              /* TICKER VIEW - Compact horizontal cards for all handles */
              <div className="p-2">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="social-feed-ticker-grid">
                  {handles.map((h) => {
                    const catColor = CATEGORY_COLORS[h.category] || '#6b7280';
                    return (
                      <a
                        key={h.handle}
                        href={`https://x.com/${h.handle}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group flex items-center gap-2 p-2 rounded-lg bg-zinc-800/40 border border-zinc-700/30 hover:border-zinc-600/50 hover:bg-zinc-800/60 transition-all"
                        data-testid={`ticker-card-${h.handle}`}
                      >
                        <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: `${catColor}15`, border: `1px solid ${catColor}30` }}
                        >
                          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 fill-current" style={{ color: catColor }}>
                            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                          </svg>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium text-white truncate">@{h.handle}</div>
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
