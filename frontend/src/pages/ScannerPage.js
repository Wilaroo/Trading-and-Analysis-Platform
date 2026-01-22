import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Search, 
  RefreshCw, 
  ChevronRight, 
  X,
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  BarChart3
} from 'lucide-react';
import api from '../utils/api';

// ===================== COMPONENTS =====================
const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

const PriceDisplay = ({ value, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

// Context Badge Component
const ContextBadge = ({ context, size = 'sm' }) => {
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
    CONSOLIDATION: 'Range',
    MEAN_REVERSION: 'Reversion'
  };
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${styles[context] || 'bg-zinc-500/20 text-zinc-400'}`}>
      {icons[context]}
      {labels[context] || context}
    </span>
  );
};

// ===================== SCANNER PAGE =====================
const ScannerPage = () => {
  const [symbols, setSymbols] = useState('AAPL, MSFT, GOOGL, NVDA, TSLA, AMD, BA, META, AMZN, NFLX');
  const [minScore, setMinScore] = useState(30);
  const [category, setCategory] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [presets, setPresets] = useState([]);
  const [selectedResult, setSelectedResult] = useState(null);
  const [marketContexts, setMarketContexts] = useState({});
  const [analyzeContext, setAnalyzeContext] = useState(true);

  useEffect(() => { loadPresets(); }, []);

  const loadPresets = async () => {
    try {
      const res = await api.get('/api/scanner/presets');
      setPresets(res.data.presets);
    } catch (err) { console.error('Failed to load presets:', err); }
  };

  const runScan = async () => {
    setLoading(true);
    setMarketContexts({});
    try {
      const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
      
      // Run scan and market context analysis in parallel if enabled
      const scanPromise = api.post('/api/scanner/scan', symbolList, {
        params: { category: category || undefined, min_score: minScore }
      });
      
      const contextPromise = analyzeContext 
        ? api.post('/api/market-context/batch', { symbols: symbolList })
        : Promise.resolve(null);
      
      const [scanRes, contextRes] = await Promise.all([scanPromise, contextPromise]);
      
      setResults(scanRes.data.results);
      
      if (contextRes?.data?.results) {
        setMarketContexts(contextRes.data.results);
      }
    } catch (err) { console.error('Scan failed:', err); }
    finally { setLoading(false); }
  };

  // Get recommended strategies based on market context
  const getContextStrategies = (context) => {
    const strategies = {
      TRENDING: ['INT-01', 'INT-02', 'INT-05', 'INT-14', 'INT-15'],
      CONSOLIDATION: ['INT-09', 'INT-13', 'INT-17'],
      MEAN_REVERSION: ['INT-07', 'INT-08', 'INT-11']
    };
    return strategies[context] || [];
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="scanner-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strategy Scanner</h1>
          <p className="text-zinc-500 text-sm mt-1">Scan stocks against 50 detailed strategy criteria with market context</p>
        </div>
      </div>

      <Card hover={false}>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-2">
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Symbols</label>
            <input
              data-testid="scanner-symbols-input"
              type="text"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="AAPL, MSFT, GOOGL..."
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Category</label>
            <select
              data-testid="scanner-category-select"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white focus:border-primary/50 focus:outline-none"
            >
              <option value="">All Strategies (50)</option>
              <option value="intraday">Intraday (20)</option>
              <option value="swing">Swing (15)</option>
              <option value="investment">Investment (15)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-2">Min Score: {minScore}</label>
            <input type="range" min="0" max="100" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="w-full" />
          </div>
        </div>
        
        {/* Market Context Toggle */}
        <div className="mt-4 pt-4 border-t border-white/5">
          <label className="flex items-center gap-3 cursor-pointer">
            <input 
              type="checkbox" 
              checked={analyzeContext} 
              onChange={(e) => setAnalyzeContext(e.target.checked)}
              className="w-4 h-4 rounded bg-white/10 border-white/20 text-primary focus:ring-primary"
            />
            <span className="flex items-center gap-2 text-sm">
              <BarChart3 className="w-4 h-4 text-primary" />
              Auto-classify market context (Trending/Consolidation/Mean Reversion)
            </span>
          </label>
        </div>
        
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
          {presets.map((preset, idx) => (
            <button key={idx} onClick={() => { setSymbols(preset.symbols.join(', ')); setMinScore(preset.min_score); }}
              className="text-xs bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-full text-zinc-400 hover:text-white transition-colors">
              {preset.name}
            </button>
          ))}
        </div>
        <button data-testid="run-scanner-btn" onClick={runScan} disabled={loading} className="btn-primary mt-4 flex items-center gap-2">
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? 'Scanning against 50 strategies...' : 'Run Scanner'}
        </button>
      </Card>

      {results.length > 0 && (
        <Card hover={false}>
          <h2 className="font-semibold mb-4">Scan Results ({results.length})</h2>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  {analyzeContext && <th>Context</th>}
                  <th>Score</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>RVOL</th>
                  <th>Gap%</th>
                  <th>Strategies Matched</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {results.map((result, idx) => {
                  const context = marketContexts[result.symbol];
                  const contextStrategies = context ? getContextStrategies(context.market_context) : [];
                  
                  return (
                    <tr key={idx} className="cursor-pointer hover:bg-white/5" onClick={() => setSelectedResult({ ...result, context })}>
                      <td className="font-bold text-primary">{result.symbol}</td>
                      {analyzeContext && (
                        <td>
                          {context ? (
                            <div className="flex flex-col gap-1">
                              <ContextBadge context={context.market_context} />
                              <span className="text-xs text-zinc-500">{context.confidence}% conf</span>
                            </div>
                          ) : (
                            <span className="text-zinc-500 text-xs">-</span>
                          )}
                        </td>
                      )}
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-2 bg-white/10 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all ${
                              result.score >= 70 ? 'bg-green-400' : 
                              result.score >= 50 ? 'bg-yellow-400' : 
                              result.score >= 30 ? 'bg-blue-400' : 'bg-zinc-500'
                            }`} style={{ width: `${result.score}%` }} />
                          </div>
                          <span className="font-mono text-sm">{result.score}</span>
                        </div>
                      </td>
                      <td className="font-mono">${result.quote?.price?.toFixed(2)}</td>
                      <td><PriceDisplay value={result.quote?.change_percent} /></td>
                      <td className={`font-mono text-sm ${result.rvol >= 2 ? 'text-yellow-400' : result.rvol >= 1.5 ? 'text-blue-400' : 'text-zinc-400'}`}>
                        {result.rvol?.toFixed(1)}x
                      </td>
                      <td className={`font-mono text-sm ${Math.abs(result.gap_percent || 0) >= 3 ? 'text-yellow-400' : 'text-zinc-400'}`}>
                        {result.gap_percent > 0 ? '+' : ''}{result.gap_percent?.toFixed(1)}%
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1 max-w-[200px]">
                          {result.matched_strategies?.slice(0, 4).map((s, i) => {
                            const isContextMatch = contextStrategies.includes(s);
                            return (
                              <span key={i} className={`badge text-xs ${
                                isContextMatch ? 'bg-primary/30 text-primary border-primary/50 ring-1 ring-primary/30' :
                                s.startsWith('INT') ? 'badge-info' : 
                                s.startsWith('SWG') ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' : 
                                'bg-green-500/20 text-green-400 border-green-500/30'
                              }`} title={isContextMatch ? 'Matches market context!' : ''}>
                                {s}{isContextMatch && ' ★'}
                              </span>
                            );
                          })}
                          {result.matched_strategies?.length > 4 && (
                            <span className="badge bg-white/10 text-zinc-400">+{result.matched_strategies.length - 4}</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <ChevronRight className="w-4 h-4 text-zinc-500" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Strategy Details Modal */}
      <AnimatePresence>
        {selectedResult && (
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4" 
            onClick={() => setSelectedResult(null)}
          >
            <motion.div 
              initial={{ scale: 0.95 }} 
              animate={{ scale: 1 }} 
              exit={{ scale: 0.95 }}
              className="bg-paper border border-white/10 rounded-xl max-w-2xl w-full p-6 max-h-[80vh] overflow-y-auto" 
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <h2 className="text-2xl font-bold text-primary">{selectedResult.symbol}</h2>
                    <span className="text-2xl font-mono">${selectedResult.quote?.price?.toFixed(2)}</span>
                    <PriceDisplay value={selectedResult.quote?.change_percent} className="text-lg" />
                    {selectedResult.context && (
                      <ContextBadge context={selectedResult.context.market_context} size="md" />
                    )}
                  </div>
                  <p className="text-zinc-500 text-sm mt-1">
                    Score: {selectedResult.score} | {selectedResult.matched_strategies?.length || 0} strategies matched
                  </p>
                </div>
                <button onClick={() => setSelectedResult(null)} className="text-zinc-500 hover:text-white">
                  <X className="w-6 h-6" />
                </button>
              </div>

              {/* Market Context Section */}
              {selectedResult.context && (
                <div className="mb-6 p-4 rounded-lg bg-gradient-to-r from-primary/10 to-transparent border border-primary/20">
                  <h3 className="text-sm font-medium flex items-center gap-2 mb-3">
                    <BarChart3 className="w-4 h-4 text-primary" />
                    Market Context Analysis
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div>
                      <p className="text-xs text-zinc-500">Context</p>
                      <p className="font-medium">{selectedResult.context.market_context?.replace('_', ' ')}</p>
                    </div>
                    <div>
                      <p className="text-xs text-zinc-500">Confidence</p>
                      <p className="font-medium">{selectedResult.context.confidence}%</p>
                    </div>
                    <div>
                      <p className="text-xs text-zinc-500">ATR Trend</p>
                      <p className={`font-medium ${
                        selectedResult.context.metrics?.atr?.atr_trend === 'DECLINING' ? 'text-yellow-400' :
                        selectedResult.context.metrics?.atr?.atr_trend === 'RISING' ? 'text-green-400' : ''
                      }`}>
                        {selectedResult.context.metrics?.atr?.atr_trend || 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-zinc-500">Trend</p>
                      <p className={`font-medium ${
                        selectedResult.context.metrics?.trend?.trend_direction === 'BULLISH' ? 'text-green-400' :
                        selectedResult.context.metrics?.trend?.trend_direction === 'BEARISH' ? 'text-red-400' : ''
                      }`}>
                        {selectedResult.context.metrics?.trend?.trend_direction || 'N/A'}
                      </p>
                    </div>
                  </div>
                  
                  {selectedResult.context.recommended_styles?.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-white/10">
                      <p className="text-xs text-zinc-500 mb-2">Recommended Trade Styles:</p>
                      <div className="flex flex-wrap gap-2">
                        {selectedResult.context.recommended_styles.map((style, i) => (
                          <span key={i} className="text-xs bg-primary/20 text-primary px-2 py-1 rounded">
                            {style.style}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Key Metrics */}
              <div className="grid grid-cols-4 gap-3 mb-6">
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500 uppercase">RVOL</p>
                  <p className={`text-lg font-mono ${selectedResult.rvol >= 2 ? 'text-yellow-400' : 'text-white'}`}>
                    {selectedResult.rvol?.toFixed(1)}x
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500 uppercase">Gap</p>
                  <p className="text-lg font-mono">{selectedResult.gap_percent?.toFixed(1)}%</p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500 uppercase">Range</p>
                  <p className="text-lg font-mono">{selectedResult.daily_range?.toFixed(1)}%</p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500 uppercase">VWAP</p>
                  <p className={`text-lg ${selectedResult.above_vwap ? 'text-green-400' : 'text-red-400'}`}>
                    {selectedResult.above_vwap ? 'Above' : 'Below'}
                  </p>
                </div>
              </div>

              {/* Matched Strategies Details */}
              <div>
                <h3 className="text-sm text-zinc-500 uppercase tracking-wider mb-3">Matched Strategy Details</h3>
                <div className="space-y-2">
                  {selectedResult.strategy_details?.map((detail, idx) => {
                    const contextStrategies = selectedResult.context 
                      ? getContextStrategies(selectedResult.context.market_context) 
                      : [];
                    const isContextMatch = contextStrategies.includes(detail.id);
                    
                    return (
                      <div key={idx} className={`rounded-lg p-3 ${isContextMatch ? 'bg-primary/10 border border-primary/30' : 'bg-white/5'}`}>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className={`badge ${
                              detail.id.startsWith('INT') ? 'badge-info' : 
                              detail.id.startsWith('SWG') ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' : 
                              'bg-green-500/20 text-green-400 border-green-500/30'
                            }`}>{detail.id}</span>
                            <span className="font-medium">{detail.name}</span>
                            {isContextMatch && (
                              <span className="text-xs bg-primary/30 text-primary px-2 py-0.5 rounded-full">
                                ★ Context Match
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 bg-white/10 rounded-full overflow-hidden">
                              <div 
                                className={`h-full rounded-full ${detail.confidence >= 75 ? 'bg-green-400' : detail.confidence >= 50 ? 'bg-yellow-400' : 'bg-blue-400'}`}
                                style={{ width: `${detail.confidence}%` }}
                              />
                            </div>
                            <span className="text-xs text-zinc-400">{detail.criteria_met}/{detail.total}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  {(!selectedResult.strategy_details || selectedResult.strategy_details.length === 0) && (
                    <p className="text-zinc-500 text-sm text-center py-4">No detailed strategy matches available</p>
                  )}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScannerPage;
