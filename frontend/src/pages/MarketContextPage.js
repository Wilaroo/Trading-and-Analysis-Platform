import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  BarChart3, 
  RefreshCw,
  Target,
  Zap,
  ArrowRight,
  Info,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// Context Badge Component
const ContextBadge = ({ context, size = 'md' }) => {
  const styles = {
    TRENDING: 'bg-green-500/20 text-green-400 border-green-500/30',
    CONSOLIDATION: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    MEAN_REVERSION: 'bg-purple-500/20 text-purple-400 border-purple-500/30'
  };
  
  const icons = {
    TRENDING: <TrendingUp className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
    CONSOLIDATION: <Activity className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
    MEAN_REVERSION: <Target className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />
  };
  
  const labels = {
    TRENDING: 'Trending',
    CONSOLIDATION: 'Consolidation',
    MEAN_REVERSION: 'Mean Reversion'
  };
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full border text-xs font-medium ${styles[context] || 'bg-zinc-500/20 text-zinc-400'}`}>
      {icons[context]}
      {labels[context] || context}
    </span>
  );
};

// Context Summary Card
const ContextSummaryCard = ({ title, count, percent, symbols, context, onClick }) => {
  const bgColors = {
    TRENDING: 'from-green-500/20 to-green-500/5',
    CONSOLIDATION: 'from-yellow-500/20 to-yellow-500/5',
    MEAN_REVERSION: 'from-purple-500/20 to-purple-500/5'
  };
  
  const textColors = {
    TRENDING: 'text-green-400',
    CONSOLIDATION: 'text-yellow-400',
    MEAN_REVERSION: 'text-purple-400'
  };
  
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      onClick={onClick}
      className={`bg-gradient-to-br ${bgColors[context]} rounded-xl p-5 border border-white/10 cursor-pointer`}
    >
      <div className="flex items-center justify-between mb-3">
        <ContextBadge context={context} />
        <span className={`text-2xl font-bold ${textColors[context]}`}>{count}</span>
      </div>
      <p className="text-sm text-zinc-400 mb-2">{percent}% of analyzed</p>
      {symbols && symbols.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {symbols.slice(0, 5).map(s => (
            <span key={s} className="text-xs bg-white/10 px-2 py-0.5 rounded">{s}</span>
          ))}
          {symbols.length > 5 && (
            <span className="text-xs text-zinc-500">+{symbols.length - 5} more</span>
          )}
        </div>
      )}
    </motion.div>
  );
};

// Individual Stock Context Card
const StockContextCard = ({ data, expanded, onToggle }) => {
  const { symbol, market_context, sub_type, confidence, metrics, recommended_styles, current_price } = data;
  
  const getConfidenceColor = (conf) => {
    if (conf >= 70) return 'text-green-400';
    if (conf >= 50) return 'text-yellow-400';
    return 'text-red-400';
  };
  
  return (
    <Card className="overflow-hidden" hover={false}>
      <div 
        className="flex items-center justify-between cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-primary/20 rounded-lg flex items-center justify-center">
            <span className="font-bold text-primary">{symbol?.charAt(0)}</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg">{symbol}</span>
              <ContextBadge context={market_context} size="sm" />
              {sub_type && (
                <span className="text-xs bg-white/10 px-2 py-0.5 rounded">{sub_type}</span>
              )}
            </div>
            <p className="text-sm text-zinc-400">
              ${current_price?.toFixed(2)} • Confidence: <span className={getConfidenceColor(confidence)}>{confidence}%</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {metrics?.rvol && (
            <div className="text-right">
              <p className="text-xs text-zinc-500">RVOL</p>
              <p className={`font-mono font-bold ${metrics.rvol >= 1.5 ? 'text-green-400' : metrics.rvol < 0.8 ? 'text-red-400' : 'text-zinc-300'}`}>
                {metrics.rvol.toFixed(2)}x
              </p>
            </div>
          )}
          {expanded ? <ChevronUp className="w-5 h-5 text-zinc-500" /> : <ChevronDown className="w-5 h-5 text-zinc-500" />}
        </div>
      </div>
      
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="pt-4 mt-4 border-t border-white/10">
              {/* Metrics Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                {/* ATR */}
                {metrics?.atr && (
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-xs text-zinc-500 uppercase">ATR Trend</p>
                    <p className={`font-bold ${
                      metrics.atr.atr_trend === 'DECLINING' ? 'text-yellow-400' :
                      metrics.atr.atr_trend === 'RISING' ? 'text-green-400' : 'text-zinc-300'
                    }`}>
                      {metrics.atr.atr_trend}
                    </p>
                    <p className="text-xs text-zinc-500">{metrics.atr.atr_change_percent?.toFixed(1)}% change</p>
                  </div>
                )}
                
                {/* Range */}
                {metrics?.range && (
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-xs text-zinc-500 uppercase">Range</p>
                    <p className="font-bold">
                      {metrics.range.range_percent?.toFixed(1)}%
                    </p>
                    <p className="text-xs text-zinc-500">
                      {metrics.range.is_tight_range ? 'Tight' : 'Wide'} range
                    </p>
                  </div>
                )}
                
                {/* Trend */}
                {metrics?.trend && (
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-xs text-zinc-500 uppercase">Trend</p>
                    <p className={`font-bold ${
                      metrics.trend.trend_direction === 'BULLISH' ? 'text-green-400' :
                      metrics.trend.trend_direction === 'BEARISH' ? 'text-red-400' : 'text-zinc-300'
                    }`}>
                      {metrics.trend.trend_direction}
                    </p>
                    <p className="text-xs text-zinc-500">Strength: {metrics.trend.trend_strength?.toFixed(0)}%</p>
                  </div>
                )}
                
                {/* Mean Reversion */}
                {metrics?.mean_reversion && (
                  <div className="bg-white/5 rounded-lg p-3">
                    <p className="text-xs text-zinc-500 uppercase">Extension</p>
                    <p className={`font-bold ${
                      metrics.mean_reversion.is_overextended ? 'text-purple-400' : 'text-zinc-300'
                    }`}>
                      {metrics.mean_reversion.extension_percent?.toFixed(1)}%
                    </p>
                    <p className="text-xs text-zinc-500">
                      Z-Score: {metrics.mean_reversion.z_score?.toFixed(2)}
                    </p>
                  </div>
                )}
              </div>
              
              {/* Recommended Styles */}
              {recommended_styles && recommended_styles.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2 flex items-center gap-2">
                    <Zap className="w-4 h-4 text-primary" />
                    Recommended Trade Styles
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {recommended_styles.map((style, idx) => (
                      <div key={idx} className="bg-primary/10 border border-primary/20 rounded-lg px-3 py-2">
                        <p className="text-sm font-medium text-primary">{style.style}</p>
                        <p className="text-xs text-zinc-400">{style.strategies?.join(', ')}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
};

// Context Info Panel
const ContextInfoPanel = ({ context }) => {
  const info = {
    TRENDING: {
      title: 'Trending Market',
      behavior: 'Clear and persistent directional movement',
      identification: ['High RVOL (≥1.5)', 'Rising ATR', 'Clear price direction'],
      styles: ['Breakout Confirmation', 'Pullback Continuation', 'Momentum Trading'],
      color: 'green'
    },
    CONSOLIDATION: {
      title: 'Consolidation (Range)',
      behavior: 'Prices within defined range, no clear trend',
      identification: ['Low volume (RVOL <1)', 'Declining ATR', 'Clear S/R levels', 'False breakouts common'],
      styles: ['Range Trading', 'Scalping', 'Rubber Band Setup'],
      color: 'yellow'
    },
    MEAN_REVERSION: {
      title: 'Mean Reversion',
      behavior: 'Overextended price returning to balance point',
      identification: ['Price >2 std devs from mean', 'Gap failures', 'High volume exhaustion'],
      styles: ['VWAP Reversion', 'Exhaustion Reversal', 'Key Level Reversal'],
      color: 'purple'
    }
  };
  
  const data = info[context];
  if (!data) return null;
  
  const colorClasses = {
    green: 'border-green-500/30 bg-green-500/5',
    yellow: 'border-yellow-500/30 bg-yellow-500/5',
    purple: 'border-purple-500/30 bg-purple-500/5'
  };
  
  return (
    <div className={`rounded-lg border p-4 ${colorClasses[data.color]}`}>
      <h3 className="font-bold mb-2 flex items-center gap-2">
        <Info className="w-4 h-4" />
        {data.title}
      </h3>
      <p className="text-sm text-zinc-400 mb-3">{data.behavior}</p>
      
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-zinc-500 uppercase mb-1">Identification</p>
          <ul className="text-sm space-y-1">
            {data.identification.map((item, i) => (
              <li key={i} className="flex items-center gap-1">
                <span className="w-1 h-1 bg-zinc-500 rounded-full" />
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-xs text-zinc-500 uppercase mb-1">Trade Styles</p>
          <ul className="text-sm space-y-1">
            {data.styles.map((style, i) => (
              <li key={i} className="flex items-center gap-1">
                <ArrowRight className="w-3 h-3 text-primary" />
                {style}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

// ===================== MARKET CONTEXT PAGE =====================
const MarketContextPage = () => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [expandedSymbol, setExpandedSymbol] = useState(null);
  const [selectedContext, setSelectedContext] = useState(null);
  const [customSymbol, setCustomSymbol] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/market-context/watchlist/analysis');
      setData(res.data);
    } catch (err) {
      console.error('Failed to load market context:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const analyzeCustomSymbol = async () => {
    if (!customSymbol.trim()) return;
    
    try {
      const res = await api.get(`/api/market-context/${customSymbol.toUpperCase()}`);
      
      // Add to results
      setData(prev => {
        if (!prev) return prev;
        const newResults = { ...prev.results, [customSymbol.toUpperCase()]: res.data };
        const symbols = Object.keys(newResults);
        return {
          ...prev,
          results: newResults,
          symbols_analyzed: symbols,
          summary: {
            ...prev.summary,
            total_analyzed: symbols.length
          }
        };
      });
      
      setExpandedSymbol(customSymbol.toUpperCase());
      setCustomSymbol('');
    } catch (err) {
      console.error('Failed to analyze symbol:', err);
    }
  };

  const filteredResults = data?.results ? Object.entries(data.results).filter(([symbol, ctx]) => {
    if (!selectedContext) return true;
    return ctx.market_context === selectedContext;
  }) : [];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="market-context-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-primary" />
            Market Context Dashboard
          </h1>
          <p className="text-zinc-500 text-sm">Classify stocks: Trending, Consolidation, or Mean Reversion</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Custom Symbol Input */}
      <Card hover={false}>
        <div className="flex gap-4">
          <input
            type="text"
            value={customSymbol}
            onChange={(e) => setCustomSymbol(e.target.value.toUpperCase())}
            onKeyPress={(e) => e.key === 'Enter' && analyzeCustomSymbol()}
            placeholder="Analyze any symbol..."
            className="flex-1 bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
            data-testid="context-symbol-input"
          />
          <button 
            onClick={analyzeCustomSymbol}
            className="btn-primary flex items-center gap-2"
            data-testid="analyze-context-btn"
          >
            <Activity className="w-4 h-4" />
            Analyze
          </button>
        </div>
      </Card>

      {/* Summary Cards */}
      {data?.summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ContextSummaryCard
            title="Trending"
            count={data.summary.trending?.count || 0}
            percent={data.summary.trending?.percent || 0}
            symbols={data.summary.trending?.symbols || []}
            context="TRENDING"
            onClick={() => setSelectedContext(selectedContext === 'TRENDING' ? null : 'TRENDING')}
          />
          <ContextSummaryCard
            title="Consolidation"
            count={data.summary.consolidation?.count || 0}
            percent={data.summary.consolidation?.percent || 0}
            symbols={data.summary.consolidation?.symbols || []}
            context="CONSOLIDATION"
            onClick={() => setSelectedContext(selectedContext === 'CONSOLIDATION' ? null : 'CONSOLIDATION')}
          />
          <ContextSummaryCard
            title="Mean Reversion"
            count={data.summary.mean_reversion?.count || 0}
            percent={data.summary.mean_reversion?.percent || 0}
            symbols={data.summary.mean_reversion?.symbols || []}
            context="MEAN_REVERSION"
            onClick={() => setSelectedContext(selectedContext === 'MEAN_REVERSION' ? null : 'MEAN_REVERSION')}
          />
        </div>
      )}

      {/* Context Info Panel */}
      {selectedContext && (
        <ContextInfoPanel context={selectedContext} />
      )}

      {/* Results List */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">
            {selectedContext ? (
              <>Filtered: {selectedContext.replace('_', ' ')} ({filteredResults.length})</>
            ) : (
              <>All Stocks ({data?.summary?.total_analyzed || 0})</>
            )}
          </h2>
          {selectedContext && (
            <button 
              onClick={() => setSelectedContext(null)}
              className="text-sm text-primary hover:underline"
            >
              Clear filter
            </button>
          )}
        </div>

        {loading ? (
          <div className="space-y-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-24 bg-white/5 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {filteredResults.map(([symbol, ctx]) => (
              <StockContextCard
                key={symbol}
                data={ctx}
                expanded={expandedSymbol === symbol}
                onToggle={() => setExpandedSymbol(expandedSymbol === symbol ? null : symbol)}
              />
            ))}
            
            {filteredResults.length === 0 && (
              <div className="text-center py-12">
                <Activity className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                <p className="text-zinc-500">No stocks match the selected filter</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default MarketContextPage;
