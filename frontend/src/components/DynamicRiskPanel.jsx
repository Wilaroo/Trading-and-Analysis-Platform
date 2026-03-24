/**
 * DynamicRiskPanel - Dynamic Risk Management Controls
 * 
 * Displays current risk multiplier and allows quick adjustments.
 * Shows factor breakdown and provides override controls.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Shield, TrendingUp, TrendingDown, Activity, 
  AlertTriangle, ChevronDown, ChevronUp, RefreshCw,
  Zap, Target, BarChart3, Clock, Settings
} from 'lucide-react';
import { toast } from 'sonner';
import { useDataCache } from '../contexts';
import api, { safeGet, safePost, safeDelete } from '../utils/api';

// Risk level colors
const RISK_COLORS = {
  minimal: { bg: 'rgba(239, 68, 68, 0.2)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.4)' },
  reduced: { bg: 'rgba(249, 115, 22, 0.2)', text: '#f97316', border: 'rgba(249, 115, 22, 0.4)' },
  normal: { bg: 'rgba(34, 197, 94, 0.2)', text: '#22c55e', border: 'rgba(34, 197, 94, 0.4)' },
  elevated: { bg: 'rgba(59, 130, 246, 0.2)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.4)' },
  maximum: { bg: 'rgba(168, 85, 247, 0.2)', text: '#a855f7', border: 'rgba(168, 85, 247, 0.4)' },
};

const RISK_LABELS = {
  minimal: 'Minimal Risk',
  reduced: 'Reduced',
  normal: 'Normal',
  elevated: 'Elevated',
  maximum: 'Maximum',
};

// Hook for dynamic risk data
const useDynamicRisk = (pollInterval = 30000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  const cachedRisk = getCached('dynamicRiskStatus');
  const [status, setStatus] = useState(cachedRisk?.data || null);
  const [loading, setLoading] = useState(!cachedRisk?.data);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/dynamic-risk/status');
      if (data.success) {
        setStatus(data);
        setCached('dynamicRiskStatus', data, 30000);
      }
    } catch (err) {
      console.error('Error fetching dynamic risk:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    const cached = getCached('dynamicRiskStatus');
    if (cached?.data && isFirstMount.current) {
      setStatus(cached.data);
      setLoading(false);
      if (cached.isStale) fetchStatus();
    } else {
      fetchStatus();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval, getCached]);

  return { status, loading, refresh: fetchStatus };
};

// Compact version for Command Center header
export const DynamicRiskBadge = ({ onClick }) => {
  const { status, loading } = useDynamicRisk();
  
  if (loading || !status) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/5">
        <Activity className="w-3.5 h-3.5 text-gray-400 animate-pulse" />
        <span className="text-xs text-gray-400">Risk...</span>
      </div>
    );
  }
  
  const riskLevel = status.current_risk_level || 'normal';
  const multiplier = status.current_multiplier || 1.0;
  const colors = RISK_COLORS[riskLevel] || RISK_COLORS.normal;
  
  return (
    <motion.button
      onClick={onClick}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all hover:scale-105"
      style={{ 
        background: colors.bg, 
        border: `1px solid ${colors.border}` 
      }}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
    >
      <Shield className="w-3.5 h-3.5" style={{ color: colors.text }} />
      <span className="text-xs font-medium" style={{ color: colors.text }}>
        {multiplier.toFixed(1)}x
      </span>
      {status.override?.active && (
        <span className="text-[10px] px-1 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
          OVR
        </span>
      )}
    </motion.button>
  );
};

// Full panel version for detailed view
export const DynamicRiskPanel = ({ expanded = false, onToggleExpand }) => {
  const { status, loading, refresh } = useDynamicRisk(5000);
  const [showOverride, setShowOverride] = useState(false);
  const [overrideValue, setOverrideValue] = useState(1.0);
  const [overrideDuration, setOverrideDuration] = useState(60);
  const [overrideReason, setOverrideReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  
  const handleToggle = async () => {
    setActionLoading(true);
    try {
      const res = await api.post('/api/dynamic-risk/toggle');
      const data = await res.json();
      if (data.success) {
        toast.success(data.enabled ? 'Dynamic risk enabled' : 'Dynamic risk disabled');
        refresh();
      }
    } catch (err) {
      toast.error('Failed to toggle dynamic risk');
    }
    setActionLoading(false);
  };
  
  const handleSetOverride = async () => {
    setActionLoading(true);
    try {
      const { data: data } = await api.post('/api/dynamic-risk/override', {
          multiplier: overrideValue,
          duration_minutes: overrideDuration,
          reason: overrideReason
        });
      if (data.success) {
        toast.success(`Override set: ${overrideValue}x for ${overrideDuration} mins`);
        setShowOverride(false);
        refresh();
      }
    } catch (err) {
      toast.error('Failed to set override');
    }
    setActionLoading(false);
  };
  
  const handleClearOverride = async () => {
    setActionLoading(true);
    try {
      const data = await safeDelete('/api/dynamic-risk/override');
      if (data.success) {
        toast.success('Override cleared');
        refresh();
      }
    } catch (err) {
      toast.error('Failed to clear override');
    }
    setActionLoading(false);
  };
  
  if (loading || !status) {
    return (
      <div className="p-4 rounded-xl bg-white/5 backdrop-blur-sm border border-white/10">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-gray-400 animate-pulse" />
          <span className="text-sm text-gray-400">Loading risk data...</span>
        </div>
      </div>
    );
  }
  
  const riskLevel = status.current_risk_level || 'normal';
  const multiplier = status.current_multiplier || 1.0;
  const colors = RISK_COLORS[riskLevel] || RISK_COLORS.normal;
  const assessment = status.last_assessment;
  
  return (
    <div className="rounded-xl bg-white/5 backdrop-blur-sm border border-white/10 overflow-hidden">
      {/* Header */}
      <div 
        className="p-3 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-colors"
        onClick={onToggleExpand}
      >
        <div className="flex items-center gap-3">
          <div 
            className="p-2 rounded-lg"
            style={{ background: colors.bg }}
          >
            <Shield className="w-5 h-5" style={{ color: colors.text }} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white">Dynamic Risk</span>
              {!status.enabled && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-500/30 text-gray-400">
                  OFF
                </span>
              )}
              {status.override?.active && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
                  OVERRIDE
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400">
              {RISK_LABELS[riskLevel]} - {multiplier.toFixed(2)}x sizing
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <span 
            className="text-lg font-bold"
            style={{ color: colors.text }}
          >
            ${status.effective_position_size?.toLocaleString() || '1,000'}
          </span>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          )}
        </div>
      </div>
      
      {/* Expanded Content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/10"
          >
            <div className="p-4 space-y-4">
              {/* Multiplier Visualization */}
              <div className="relative h-8 bg-white/5 rounded-full overflow-hidden">
                <div 
                  className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
                  style={{ 
                    width: `${Math.min(100, (multiplier / 2) * 100)}%`,
                    background: `linear-gradient(90deg, ${colors.bg}, ${colors.text}40)`
                  }}
                />
                <div className="absolute inset-0 flex items-center justify-between px-3">
                  <span className="text-xs text-gray-400">0.25x</span>
                  <span className="text-sm font-bold" style={{ color: colors.text }}>
                    {multiplier.toFixed(2)}x
                  </span>
                  <span className="text-xs text-gray-400">2.0x</span>
                </div>
              </div>
              
              {/* Factor Breakdown */}
              {assessment?.factors && assessment.factors.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs text-gray-400 font-medium">Factor Breakdown</div>
                  <div className="grid grid-cols-2 gap-2">
                    {assessment.factors.map((factor, idx) => (
                      <div 
                        key={idx}
                        className="p-2 rounded-lg bg-white/5 border border-white/5"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs text-gray-400">{factor.name}</span>
                          <span className={`text-xs font-medium ${
                            factor.score >= 0.6 ? 'text-green-400' : 
                            factor.score <= 0.4 ? 'text-red-400' : 'text-gray-400'
                          }`}>
                            {(factor.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className="h-full rounded-full transition-all"
                            style={{ 
                              width: `${factor.score * 100}%`,
                              background: factor.score >= 0.6 ? '#22c55e' : 
                                         factor.score <= 0.4 ? '#ef4444' : '#6b7280'
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Explanation */}
              {assessment?.explanation && (
                <div className="p-3 rounded-lg bg-white/5 border border-white/5">
                  <p className="text-xs text-gray-300">{assessment.explanation}</p>
                </div>
              )}
              
              {/* Controls */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleToggle}
                  disabled={actionLoading}
                  className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                    status.enabled 
                      ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' 
                      : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                  }`}
                >
                  {status.enabled ? 'Disable' : 'Enable'}
                </button>
                
                {status.override?.active ? (
                  <button
                    onClick={handleClearOverride}
                    disabled={actionLoading}
                    className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 transition-all"
                  >
                    Clear Override
                  </button>
                ) : (
                  <button
                    onClick={() => setShowOverride(!showOverride)}
                    className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-white/10 text-gray-300 hover:bg-white/20 transition-all"
                  >
                    Set Override
                  </button>
                )}
                
                <button
                  onClick={refresh}
                  disabled={actionLoading}
                  className="p-2 rounded-lg bg-white/10 text-gray-400 hover:bg-white/20 transition-all"
                >
                  <RefreshCw className={`w-4 h-4 ${actionLoading ? 'animate-spin' : ''}`} />
                </button>
              </div>
              
              {/* Override Panel */}
              <AnimatePresence>
                {showOverride && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="p-3 rounded-lg bg-white/5 border border-white/10 space-y-3"
                  >
                    <div className="text-xs text-gray-400 font-medium">Set Manual Override</div>
                    
                    <div className="space-y-2">
                      <label className="text-xs text-gray-500">Multiplier: {overrideValue.toFixed(1)}x</label>
                      <input
                        type="range"
                        min="0.25"
                        max="2.0"
                        step="0.05"
                        value={overrideValue}
                        onChange={(e) => setOverrideValue(parseFloat(e.target.value))}
                        className="w-full"
                      />
                    </div>
                    
                    <div className="space-y-2">
                      <label className="text-xs text-gray-500">Duration: {overrideDuration} mins</label>
                      <input
                        type="range"
                        min="15"
                        max="480"
                        step="15"
                        value={overrideDuration}
                        onChange={(e) => setOverrideDuration(parseInt(e.target.value))}
                        className="w-full"
                      />
                    </div>
                    
                    <input
                      type="text"
                      placeholder="Reason (optional)"
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white placeholder-gray-500"
                    />
                    
                    <button
                      onClick={handleSetOverride}
                      disabled={actionLoading}
                      className="w-full px-3 py-2 rounded-lg text-xs font-medium bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-all"
                    >
                      Apply Override
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default DynamicRiskPanel;
