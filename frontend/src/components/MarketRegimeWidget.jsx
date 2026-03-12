/**
 * Market Regime Widget
 * ====================
 * Displays the current market regime (Fear & Greed style) with signal blocks.
 * 
 * TO DEPLOY:
 * ----------
 * 1. Import this component in your dashboard:
 *    import MarketRegimeWidget from '../components/MarketRegimeWidget';
 * 
 * 2. Add to your layout:
 *    <MarketRegimeWidget />
 * 
 * 3. Ensure the backend endpoint is available:
 *    GET /api/market-regime/summary
 */

import React, { useState, useEffect, useCallback } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  RefreshCw, 
  ChevronDown, 
  ChevronUp,
  AlertCircle,
  Activity,
  BarChart3,
  Gauge,
  Zap
} from 'lucide-react';
import { toast } from 'sonner';
import { Tip, TipIcon, CustomTip } from './shared/Tooltip';

// Update interval: 30 minutes
const UPDATE_INTERVAL = 30 * 60 * 1000;

const MarketRegimeWidget = ({ className = '', onStateChange = null }) => {
  const [regime, setRegime] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [lastState, setLastState] = useState(null);

  const API_URL = process.env.REACT_APP_BACKEND_URL || '';

  const fetchRegime = useCallback(async (showToast = false) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/api/market-regime/summary`);
      
      if (!response.ok) {
        throw new Error('Failed to fetch market regime');
      }
      
      const data = await response.json();
      setRegime(data);
      setError(null);
      
      // Check for state change and show toast
      if (lastState && lastState !== data.state) {
        const stateDisplay = getStateConfig(data.state);
        toast.info(`Market Regime Changed: ${stateDisplay.label}`, {
          description: data.recommendation,
          duration: 8000,
          icon: stateDisplay.icon
        });
        
        // Callback for parent components
        if (onStateChange) {
          onStateChange(data.state, lastState);
        }
      }
      
      setLastState(data.state);
      
      if (showToast) {
        toast.success('Market regime updated');
      }
    } catch (err) {
      console.error('Error fetching market regime:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [API_URL, lastState, onStateChange]);

  // Initial fetch and interval
  useEffect(() => {
    fetchRegime();
    
    const interval = setInterval(() => {
      fetchRegime();
    }, UPDATE_INTERVAL);
    
    return () => clearInterval(interval);
  }, [fetchRegime]);

  const handleRefresh = () => {
    fetchRegime(true);
  };

  const getStateConfig = (state) => {
    const configs = {
      CONFIRMED_UP: {
        label: 'Confirmed Up',
        color: 'emerald',
        bgClass: 'bg-emerald-500/10 border-emerald-500/30',
        textClass: 'text-emerald-400',
        glowClass: 'shadow-emerald-500/20',
        icon: <TrendingUp className="w-6 h-6" />,
        gradient: 'from-emerald-500/20 to-emerald-600/5'
      },
      HOLD: {
        label: 'Hold / Neutral',
        color: 'yellow',
        bgClass: 'bg-yellow-500/10 border-yellow-500/30',
        textClass: 'text-yellow-400',
        glowClass: 'shadow-yellow-500/20',
        icon: <Minus className="w-6 h-6" />,
        gradient: 'from-yellow-500/20 to-yellow-600/5'
      },
      CONFIRMED_DOWN: {
        label: 'Confirmed Down',
        color: 'red',
        bgClass: 'bg-red-500/10 border-red-500/30',
        textClass: 'text-red-400',
        glowClass: 'shadow-red-500/20',
        icon: <TrendingDown className="w-6 h-6" />,
        gradient: 'from-red-500/20 to-red-600/5'
      }
    };
    return configs[state] || configs.HOLD;
  };

  const getScoreColor = (score) => {
    if (score >= 70) return 'text-emerald-400';
    if (score >= 50) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getScoreBgColor = (score) => {
    if (score >= 70) return 'bg-emerald-500/20';
    if (score >= 50) return 'bg-yellow-500/20';
    return 'bg-red-500/20';
  };

  const getRiskBarColor = (risk) => {
    if (risk <= 30) return 'bg-emerald-500';
    if (risk <= 60) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  const formatTime = (isoString) => {
    if (!isoString) return '--:--';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit',
      hour12: false 
    });
  };

  // Loading state
  if (loading && !regime) {
    return (
      <div className={`bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 ${className}`}>
        <div className="flex items-center justify-center h-24">
          <RefreshCw className="w-6 h-6 text-slate-400 animate-spin" />
          <span className="ml-2 text-slate-400">Loading market regime...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error && !regime) {
    return (
      <div className={`bg-slate-800/50 rounded-xl border border-red-500/30 p-4 ${className}`}>
        <div className="flex items-center justify-center h-24">
          <AlertCircle className="w-6 h-6 text-red-400" />
          <span className="ml-2 text-red-400">Failed to load market regime</span>
          <button 
            onClick={handleRefresh}
            className="ml-4 px-3 py-1 bg-red-500/20 rounded text-red-400 hover:bg-red-500/30"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const stateConfig = getStateConfig(regime?.state);
  const signalScores = regime?.signal_scores || {};

  return (
    <div 
      className={`
        bg-gradient-to-br ${stateConfig.gradient} 
        rounded-xl border ${stateConfig.bgClass} 
        shadow-lg ${stateConfig.glowClass}
        transition-all duration-300
        ${className}
      `}
      data-testid="market-regime-widget"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/30">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-slate-400" />
          <CustomTip 
            label="Market Regime" 
            description="Overall market condition based on SPY/QQQ breadth, VIX, sector rotation, and volume analysis. Determines position sizing and strategy selection."
          >
            <span className="text-sm font-medium text-slate-300">MARKET REGIME</span>
          </CustomTip>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">
            {formatTime(regime?.last_updated)}
          </span>
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="p-1 hover:bg-slate-700/50 rounded transition-colors"
            data-testid="regime-refresh-btn"
            title="Refresh market regime data"
          >
            <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main State Display */}
      <div className="px-4 py-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${stateConfig.bgClass} ${stateConfig.textClass}`}>
            {stateConfig.icon}
          </div>
          <div>
            <h3 className={`text-xl font-bold ${stateConfig.textClass}`} data-testid="regime-state">
              {stateConfig.label}
            </h3>
            <div className="flex items-center gap-3 text-sm">
              <CustomTip label="Composite Score" description="Overall market health score (0-100). >60 = bullish conditions, <40 = bearish conditions, 40-60 = neutral/mixed.">
                <span className="text-slate-400">
                  Score: <span className={getScoreColor(regime?.composite_score || 0)}>
                    {regime?.composite_score || 0}
                  </span>/100
                </span>
              </CustomTip>
              <CustomTip label="Confidence" description="How reliable this assessment is based on data quality and signal agreement. Higher = more trustworthy.">
                <span className="text-slate-400">
                  Confidence: <span className="text-slate-300">{regime?.confidence || 0}%</span>
                </span>
              </CustomTip>
            </div>
          </div>
        </div>

        {/* Signal Block Scores */}
        <div className="grid grid-cols-4 gap-2 mb-4">
          {[
            { key: 'trend', label: 'TREND', icon: TrendingUp, tip: 'SPY & QQQ price trend relative to key moving averages (20, 50, 200 EMA). >50 = uptrending.' },
            { key: 'breadth', label: 'BREADTH', icon: BarChart3, tip: 'Market breadth: how many stocks/sectors are participating in the move. Confirms or warns of divergence.' },
            { key: 'ftd', label: 'FTD', icon: Zap, tip: 'Follow-Through Day status. Tracks rally attempts and distribution days to identify trend changes.' },
            { key: 'volume_vix', label: 'VOL/VIX', icon: Gauge, tip: 'VIX fear gauge + volume analysis. Low VIX + healthy volume = bullish, high VIX = caution.' }
          ].map(({ key, label, icon: Icon, tip }) => (
            <CustomTip key={key} label={label} description={tip}>
              <div 
                className={`
                  text-center p-2 rounded-lg w-full
                  ${getScoreBgColor(signalScores[key] || 0)}
                  border border-slate-700/30
                `}
                data-testid={`signal-block-${key}`}
              >
                <Icon className="w-4 h-4 mx-auto mb-1 text-slate-400" />
                <div className="text-xs text-slate-500 mb-1">{label}</div>
                <div className={`text-lg font-bold ${getScoreColor(signalScores[key] || 0)}`}>
                  {signalScores[key] || 0}
                </div>
              </div>
            </CustomTip>
          ))}
        </div>

        {/* Risk Level Bar */}
        <div className="mb-3">
          <div className="flex items-center justify-between text-xs mb-1">
            <CustomTip label="Risk Level" description="Inverse of regime score. Higher = more caution needed. Used to automatically adjust position sizes. >60% = reduce exposure.">
              <span className="text-slate-400">Risk Level</span>
            </CustomTip>
            <span className={`font-medium ${
              (regime?.risk_level || 0) <= 30 ? 'text-emerald-400' :
              (regime?.risk_level || 0) <= 60 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {regime?.risk_level || 0}%
            </span>
          </div>
          <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden">
            <div 
              className={`h-full ${getRiskBarColor(regime?.risk_level || 0)} transition-all duration-500`}
              style={{ width: `${regime?.risk_level || 0}%` }}
            />
          </div>
        </div>

        {/* Recommendation */}
        <div className="flex items-start gap-2 p-2 bg-slate-900/30 rounded-lg">
          <span className="text-lg">💡</span>
          <p className="text-sm text-slate-300 leading-relaxed">
            {regime?.recommendation || 'Loading recommendation...'}
          </p>
        </div>
      </div>

      {/* Expandable Details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-center gap-1 py-2 border-t border-slate-700/30 
                   text-xs text-slate-400 hover:text-slate-300 hover:bg-slate-800/30 transition-colors"
        data-testid="regime-expand-btn"
      >
        {expanded ? (
          <>
            <ChevronUp className="w-4 h-4" /> Hide Details
          </>
        ) : (
          <>
            <ChevronDown className="w-4 h-4" /> Show Details
          </>
        )}
      </button>

      {/* Expanded Details Panel */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-700/30">
          <div className="mt-3 space-y-3">
            {/* Trading Implications */}
            <div>
              <h4 className="text-xs font-semibold text-slate-400 mb-2">TRADING IMPLICATIONS</h4>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 bg-slate-900/30 rounded">
                  <span className="text-slate-500">Position Sizing:</span>
                  <span className="ml-1 text-slate-300">
                    {regime?.state === 'CONFIRMED_UP' ? 'Normal to Aggressive' :
                     regime?.state === 'CONFIRMED_DOWN' ? 'Minimal (25-50%)' : 'Reduced (50-75%)'}
                  </span>
                </div>
                <div className="p-2 bg-slate-900/30 rounded">
                  <span className="text-slate-500">Risk Tolerance:</span>
                  <span className="ml-1 text-slate-300">
                    {regime?.state === 'CONFIRMED_UP' ? 'Higher' :
                     regime?.state === 'CONFIRMED_DOWN' ? 'Very Low' : 'Lower'}
                  </span>
                </div>
              </div>
            </div>

            {/* Favored Strategies */}
            <div>
              <h4 className="text-xs font-semibold text-emerald-400 mb-1">FAVORED STRATEGIES</h4>
              <p className="text-xs text-slate-300">
                {regime?.state === 'CONFIRMED_UP' 
                  ? 'Momentum breakouts, Pullback entries, Trend continuation'
                  : regime?.state === 'CONFIRMED_DOWN'
                  ? 'Short selling rallies, Put options, Inverse ETFs'
                  : 'Selective high-quality setups, Quick scalps'}
              </p>
            </div>

            {/* Strategies to Avoid */}
            <div>
              <h4 className="text-xs font-semibold text-red-400 mb-1">AVOID</h4>
              <p className="text-xs text-slate-300">
                {regime?.state === 'CONFIRMED_UP' 
                  ? 'Counter-trend shorts, Mean reversion fades'
                  : regime?.state === 'CONFIRMED_DOWN'
                  ? 'Buying dips, Averaging down'
                  : 'Swing trades, Overnight holds'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MarketRegimeWidget;
