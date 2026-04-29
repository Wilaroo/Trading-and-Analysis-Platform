/**
 * SmartStopSelector - Component for selecting and visualizing smart stop modes
 * 
 * Features:
 * - Compare all stop modes side-by-side
 * - Visual risk indicator (hunt risk)
 * - Personalized recommendation based on stock characteristics
 * - Layered stops visualization
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import api, { safeGet, safePost } from '../utils/api';
import { 
  Shield, ShieldAlert, ShieldCheck, Target, TrendingDown,
  Layers, Activity, ChevronDown, ChevronUp, Info, Zap,
  AlertTriangle, CheckCircle
} from 'lucide-react';

// Stop mode icons and colors
const MODE_CONFIG = {
  original: {
    icon: ShieldAlert,
    color: 'red',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    textColor: 'text-red-400'
  },
  atr_dynamic: {
    icon: Shield,
    color: 'yellow',
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-yellow-500/30',
    textColor: 'text-yellow-400'
  },
  anti_hunt: {
    icon: ShieldCheck,
    color: 'emerald',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30',
    textColor: 'text-emerald-400'
  },
  volatility_adjusted: {
    icon: Activity,
    color: 'purple',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/30',
    textColor: 'text-purple-400'
  },
  layered: {
    icon: Layers,
    color: 'cyan',
    bgColor: 'bg-cyan-500/10',
    borderColor: 'border-cyan-500/30',
    textColor: 'text-cyan-400'
  },
  chandelier: {
    icon: TrendingDown,
    color: 'orange',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-orange-500/30',
    textColor: 'text-orange-400'
  }
};

const HUNT_RISK_COLORS = {
  'HIGH': 'text-red-400 bg-red-500/20',
  'MEDIUM': 'text-yellow-400 bg-yellow-500/20',
  'LOW': 'text-emerald-400 bg-emerald-500/20',
  'LOW to MEDIUM': 'text-purple-400 bg-purple-500/20'
};

// Layered stops visualizer sub-component
const LayeredStopsVisualizer = ({ entryPrice, atr, direction }) => {
  // Calculate layered stops locally (matching backend defaults: 40%/30%/30% at 1.0/1.5/2.0 ATR)
  const layerConfig = [
    { level: 1, pct: 0.40, depth: 1.0 },
    { level: 2, pct: 0.30, depth: 1.5 },
    { level: 3, pct: 0.30, depth: 2.0 }
  ];
  
  if (!entryPrice || !atr) return null;
  
  const layers = layerConfig.map(config => {
    const buffer = atr * config.depth;
    const stopPrice = direction === 'long' 
      ? entryPrice - buffer 
      : entryPrice + buffer;
    return {
      ...config,
      stopPrice: Math.round(stopPrice * 100) / 100
    };
  });
  
  return (
    <div className="mt-3 space-y-1">
      <span className="text-xs text-zinc-500 flex items-center gap-2">
        <Layers className="w-3 h-3" />
        Layered Exit Plan:
      </span>
      {layers.map((layer) => (
        <div key={layer.level} className="flex justify-between text-xs bg-black/30 px-2 py-1.5 rounded items-center">
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${
              layer.level === 1 ? 'bg-red-400' :
              layer.level === 2 ? 'bg-orange-400' : 'bg-yellow-400'
            }`} />
            <span>Layer {layer.level}</span>
            <span className="text-zinc-500">({layer.pct * 100}%)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500">{layer.depth}× ATR</span>
            <span className="font-mono font-medium text-white">${layer.stopPrice.toFixed(2)}</span>
          </div>
        </div>
      ))}
      <p className="text-[12px] text-zinc-500 mt-2">
        Hardest to hunt - exit 40% at first stop, survive brief sweeps with remaining 60%
      </p>
    </div>
  );
};

const SmartStopSelector = ({
  symbol,
  entryPrice,
  direction = 'long',
  atr,
  support,
  resistance,
  swingLow,
  swingHigh,
  floatShares,
  avgVolume,
  volatilityRegime = 'normal',
  onModeSelect,
  selectedMode = 'atr_dynamic',
  className = ''
}) => {
  const [modes, setModes] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [recommendation, setRecommendation] = useState(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch available modes
  useEffect(() => {
    const fetchModes = async () => {
      try {
        const data = await safeGet('/api/smart-stops/modes');
        if (data?.success) {
          setModes(data.modes);
        }
      } catch (err) {
        console.error('Failed to fetch stop modes:', err);
      }
    };
    fetchModes();
  }, []);

  // Fetch comparison when parameters change
  const fetchComparison = useCallback(async () => {
    if (!entryPrice || !atr) return;
    
    setIsLoading(true);
    try {
      const params = new URLSearchParams({
        entry_price: entryPrice.toString(),
        direction,
        atr: atr.toString(),
        ...(support && { support: support.toString() }),
        ...(resistance && { resistance: resistance.toString() })
      });
      
      const data = await safeGet(`/api/smart-stops/compare?${params}`);
      if (data?.success) {
        setComparison(data.comparison);
      }
    } catch (err) {
      console.error('Failed to fetch stop comparison:', err);
    } finally {
      setIsLoading(false);
    }
  }, [entryPrice, direction, atr, support, resistance]);

  // Fetch recommendation for this symbol
  const fetchRecommendation = useCallback(async () => {
    if (!symbol) return;
    
    try {
      const params = new URLSearchParams({
        ...(floatShares && { float_shares: floatShares.toString() }),
        ...(avgVolume && { avg_volume: avgVolume.toString() }),
        volatility_regime: volatilityRegime
      });
      
      const data = await safeGet(`/api/smart-stops/recommend/${symbol}?${params}`);
      if (data?.success) {
        setRecommendation(data);
      }
    } catch (err) {
      console.error('Failed to fetch stop recommendation:', err);
    }
  }, [symbol, floatShares, avgVolume, volatilityRegime]);

  useEffect(() => {
    fetchComparison();
    fetchRecommendation();
  }, [fetchComparison, fetchRecommendation]);

  // Handle mode selection
  const handleModeSelect = (modeId) => {
    if (onModeSelect) {
      const modeData = comparison?.[modeId];
      onModeSelect(modeId, modeData);
    }
  };

  return (
    <div className={`bg-zinc-900/50 border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* Header */}
      <div 
        className="p-3 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <Shield className="w-5 h-5 text-cyan-400" />
          <div>
            <h3 className="font-semibold text-sm">Smart Stop Protection</h3>
            <p className="text-xs text-zinc-500">Anti-hunt stop loss strategies</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {recommendation && (
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              MODE_CONFIG[recommendation.recommended_mode]?.bgColor || 'bg-zinc-500/20'
            } ${MODE_CONFIG[recommendation.recommended_mode]?.textColor || 'text-zinc-400'}`}>
              Rec: {recommendation.recommended_mode.replace('_', ' ').toUpperCase()}
            </span>
          )}
          
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-zinc-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-zinc-400" />
          )}
        </div>
      </div>

      {/* Expanded Content */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/10"
          >
            <div className="p-4 space-y-4">
              {/* Recommendation Banner */}
              {recommendation && (
                <div className={`p-3 rounded-lg ${MODE_CONFIG[recommendation.recommended_mode]?.bgColor || 'bg-zinc-800'} border ${MODE_CONFIG[recommendation.recommended_mode]?.borderColor || 'border-zinc-700'}`}>
                  <div className="flex items-start gap-2">
                    <Zap className={`w-4 h-4 mt-0.5 ${MODE_CONFIG[recommendation.recommended_mode]?.textColor || 'text-zinc-400'}`} />
                    <div className="text-sm">
                      <span className="font-medium">Recommended: </span>
                      <span className={MODE_CONFIG[recommendation.recommended_mode]?.textColor || 'text-zinc-400'}>
                        {recommendation.recommended_mode.replace('_', ' ').toUpperCase()}
                      </span>
                      <p className="text-xs text-zinc-400 mt-1">{recommendation.description}</p>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {recommendation.reasons?.map((reason, i) => (
                          <span key={i} className="px-2 py-0.5 text-xs bg-black/30 rounded">
                            {reason}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Mode Comparison Grid */}
              {comparison && (
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                  {Object.entries(comparison).map(([modeId, data]) => {
                    if (data.error) return null;
                    
                    const config = MODE_CONFIG[modeId] || MODE_CONFIG.atr_dynamic;
                    const Icon = config.icon;
                    const isSelected = selectedMode === modeId;
                    const isRecommended = recommendation?.recommended_mode === modeId;
                    
                    return (
                      <div
                        key={modeId}
                        onClick={() => handleModeSelect(modeId)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all ${
                          isSelected 
                            ? `${config.bgColor} ${config.borderColor} ring-1 ring-${config.color}-500/50`
                            : 'bg-zinc-800/50 border-zinc-700/50 hover:border-zinc-600'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Icon className={`w-4 h-4 ${config.textColor}`} />
                            <span className="text-xs font-medium">
                              {modeId.replace('_', ' ').toUpperCase()}
                            </span>
                          </div>
                          {isRecommended && (
                            <CheckCircle className="w-3 h-3 text-emerald-400" />
                          )}
                        </div>
                        
                        <div className="space-y-1">
                          <div className="flex justify-between text-xs">
                            <span className="text-zinc-500">Stop:</span>
                            <span className="font-mono font-medium">${data.stop_price?.toFixed(2)}</span>
                          </div>
                          <div className="flex justify-between text-xs">
                            <span className="text-zinc-500">Risk:</span>
                            <span className={`font-mono ${data.risk_percent > 5 ? 'text-amber-400' : 'text-zinc-300'}`}>
                              {data.risk_percent?.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between text-xs">
                            <span className="text-zinc-500">Hunt Risk:</span>
                            <span className={`px-1.5 py-0.5 rounded text-[12px] font-medium ${HUNT_RISK_COLORS[data.hunt_risk] || 'text-zinc-400'}`}>
                              {data.hunt_risk}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Selected Mode Details */}
              {comparison && comparison[selectedMode] && (
                <div className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Info className="w-4 h-4 text-cyan-400" />
                    <span className="text-xs font-medium">Selected Stop Logic</span>
                  </div>
                  <p className="text-xs text-zinc-400">
                    {comparison[selectedMode].reasoning}
                  </p>
                  
                  {/* Show layered stops if applicable */}
                  {selectedMode === 'layered' && (
                    <LayeredStopsVisualizer 
                      entryPrice={entryPrice}
                      atr={atr}
                      direction={direction}
                    />
                  )}
                </div>
              )}

              {/* Loading State */}
              {isLoading && (
                <div className="flex items-center justify-center py-4">
                  <div className="animate-spin w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full" />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SmartStopSelector;
