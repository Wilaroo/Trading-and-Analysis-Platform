import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';

// Risk Parameters Control Panel with Profile Presets
export const RiskControlsPanel = ({ botStatus, onUpdateRisk, loading }) => {
  const riskParams = botStatus?.risk_params || {};
  const [localParams, setLocalParams] = useState({
    max_risk_per_trade: riskParams.max_risk_per_trade || 1.0,
    max_daily_loss: riskParams.max_daily_loss || 500,
    max_open_positions: riskParams.max_open_positions || 5,
    max_position_pct: riskParams.max_position_pct || 5.0,
    min_risk_reward: riskParams.min_risk_reward || 2.0
  });
  const [hasChanges, setHasChanges] = useState(false);
  const [activePreset, setActivePreset] = useState(null);

  // Risk Profile Presets
  const riskPresets = {
    conservative: {
      label: 'Conservative',
      description: 'Lower risk, fewer positions',
      icon: '🛡️',
      color: 'emerald',
      params: {
        max_risk_per_trade: 0.5,
        max_daily_loss: 250,
        max_open_positions: 3,
        min_risk_reward: 3.0
      }
    },
    moderate: {
      label: 'Moderate',
      description: 'Balanced risk/reward',
      icon: '⚖️',
      color: 'cyan',
      params: {
        max_risk_per_trade: 1.0,
        max_daily_loss: 500,
        max_open_positions: 5,
        min_risk_reward: 2.0
      }
    },
    aggressive: {
      label: 'Aggressive',
      description: 'Higher risk, more positions',
      icon: '🔥',
      color: 'amber',
      params: {
        max_risk_per_trade: 2.0,
        max_daily_loss: 1000,
        max_open_positions: 8,
        min_risk_reward: 1.5
      }
    }
  };

  // Detect which preset matches current params (if any)
  const detectActivePreset = (params) => {
    for (const [key, preset] of Object.entries(riskPresets)) {
      const p = preset.params;
      if (
        params.max_risk_per_trade === p.max_risk_per_trade &&
        params.max_daily_loss === p.max_daily_loss &&
        params.max_open_positions === p.max_open_positions &&
        params.min_risk_reward === p.min_risk_reward
      ) {
        return key;
      }
    }
    return null;
  };

  // Update local params when bot status changes
  useEffect(() => {
    if (riskParams) {
      const newParams = {
        max_risk_per_trade: riskParams.max_risk_per_trade || 1.0,
        max_daily_loss: riskParams.max_daily_loss || 500,
        max_open_positions: riskParams.max_open_positions || 5,
        max_position_pct: riskParams.max_position_pct || 5.0,
        min_risk_reward: riskParams.min_risk_reward || 2.0
      };
      setLocalParams(newParams);
      setActivePreset(detectActivePreset(newParams));
      setHasChanges(false);
    }
  }, [riskParams]);

  const handleChange = (field, value) => {
    const newParams = { ...localParams, [field]: parseFloat(value) || 0 };
    setLocalParams(newParams);
    setActivePreset(detectActivePreset(newParams));
    setHasChanges(true);
  };

  const applyPreset = (presetKey) => {
    const preset = riskPresets[presetKey];
    if (preset) {
      setLocalParams(prev => ({ ...prev, ...preset.params }));
      setActivePreset(presetKey);
      setHasChanges(true);
      toast.success(`Applied ${preset.label} risk profile`);
    }
  };

  const handleSave = async () => {
    const success = await onUpdateRisk(localParams);
    if (success) setHasChanges(false);
  };

  return (
    <div className="space-y-4">
      {/* Risk Profile Presets */}
      <div>
        <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Quick Profiles</h4>
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(riskPresets).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => applyPreset(key)}
              className={`p-3 rounded-xl border text-center transition-all ${
                activePreset === key
                  ? preset.color === 'emerald' 
                    ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                    : preset.color === 'cyan'
                    ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-400'
                    : 'bg-amber-500/20 border-amber-500/40 text-amber-400'
                  : 'bg-black/30 border-white/5 text-zinc-400 hover:border-white/10 hover:bg-black/40'
              }`}
              data-testid={`risk-preset-${key}`}
            >
              <span className="text-lg">{preset.icon}</span>
              <div className="text-xs font-medium mt-1">{preset.label}</div>
              <div className="text-[11px] text-zinc-500 mt-0.5">{preset.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-white/5" />

      {/* Custom Parameters */}
      <div>
        <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">
          Custom Parameters {activePreset && <span className="text-cyan-400 font-normal">({riskPresets[activePreset].label})</span>}
        </h4>
        
        <div className="grid grid-cols-2 gap-3">
          {/* Max Risk Per Trade */}
          <div className="space-y-1">
            <label className="text-[12px] text-zinc-500 uppercase">Risk/Trade (%)</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5"
              value={localParams.max_risk_per_trade}
              onChange={(e) => handleChange('max_risk_per_trade', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="risk-per-trade-input"
            />
          </div>

          {/* Max Daily Loss */}
          <div className="space-y-1">
            <label className="text-[12px] text-zinc-500 uppercase">Max Daily Loss ($)</label>
            <input
              type="number"
              step="50"
              min="100"
              value={localParams.max_daily_loss}
              onChange={(e) => handleChange('max_daily_loss', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="max-daily-loss-input"
            />
          </div>

          {/* Max Open Positions */}
          <div className="space-y-1">
            <label className="text-[12px] text-zinc-500 uppercase">Max Positions</label>
            <input
              type="number"
              step="1"
              min="1"
              max="20"
              value={localParams.max_open_positions}
              onChange={(e) => handleChange('max_open_positions', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="max-positions-input"
            />
          </div>

          {/* Min Risk:Reward */}
          <div className="space-y-1">
            <label className="text-[12px] text-zinc-500 uppercase">Min R:R Ratio</label>
            <input
              type="number"
              step="0.5"
              min="1"
              max="10"
              value={localParams.min_risk_reward}
              onChange={(e) => handleChange('min_risk_reward', e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
              data-testid="min-rr-input"
            />
          </div>
        </div>
      </div>

      {/* Save Button */}
      {hasChanges && (
        <motion.button
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleSave}
          disabled={loading}
          className="w-full px-4 py-2 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-lg text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
          data-testid="save-risk-params-btn"
        >
          {loading ? 'Saving...' : 'Save Risk Parameters'}
        </motion.button>
      )}
    </div>
  );
};
