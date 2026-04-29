import React from 'react';
import { Loader } from 'lucide-react';

// AI Modules Control Panel
export const AIModulesPanel = ({ aiStatus, onToggleModule, onSetShadowMode, actionLoading }) => {
  const modules = [
    {
      key: 'debate_agents',
      name: 'Bull/Bear Debate',
      description: 'AI agents debate trades from opposing viewpoints',
      icon: '⚖️',
      color: 'violet',
      enabled: aiStatus?.debate_enabled
    },
    {
      key: 'ai_risk_manager',
      name: 'AI Risk Manager',
      description: 'Multi-factor pre-trade risk assessment',
      icon: '🛡️',
      color: 'cyan',
      enabled: aiStatus?.risk_manager_enabled
    },
    {
      key: 'institutional_flow',
      name: 'Institutional Flow',
      description: '13F tracking, volume anomalies, rebalances',
      icon: '🏦',
      color: 'emerald',
      enabled: aiStatus?.institutional_enabled
    },
    {
      key: 'timeseries_ai',
      name: 'Time Series AI',
      description: 'ML-based price direction forecasting',
      icon: '📈',
      color: 'amber',
      enabled: aiStatus?.timeseries_enabled
    }
  ];

  const shadowMode = aiStatus?.shadow_mode ?? true;
  const activeModules = aiStatus?.active_modules || 0;

  return (
    <div className="space-y-4">
      {/* Shadow Mode Toggle */}
      <div className="p-3 rounded-xl bg-gradient-to-br from-violet-500/10 to-purple-500/5 border border-violet-500/20">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-xl">👻</div>
            <div>
              <h4 className="text-sm font-bold text-white">Shadow Mode</h4>
              <p className="text-[12px] text-zinc-400">AI makes decisions but doesn't execute trades</p>
            </div>
          </div>
          <button
            onClick={() => onSetShadowMode(!shadowMode)}
            disabled={actionLoading === 'shadow'}
            className={`relative w-12 h-6 rounded-full transition-all ${
              shadowMode 
                ? 'bg-violet-500' 
                : 'bg-zinc-700'
            }`}
            data-testid="shadow-mode-toggle"
          >
            <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${
              shadowMode ? 'left-7' : 'left-1'
            }`} />
          </button>
        </div>
        {shadowMode && (
          <div className="mt-2 text-[12px] text-violet-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
            All AI decisions are logged without execution for learning
          </div>
        )}
      </div>

      {/* Active Modules Count */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-zinc-400">Active Modules</span>
        <span className="text-xs font-bold text-cyan-400">{activeModules} / {modules.length}</span>
      </div>

      {/* Module Toggles */}
      <div className="space-y-2">
        {modules.map((module) => {
          const isLoading = actionLoading === module.key;
          const colorClasses = {
            violet: 'border-violet-500/30 bg-violet-500/10',
            cyan: 'border-cyan-500/30 bg-cyan-500/10',
            emerald: 'border-emerald-500/30 bg-emerald-500/10',
            amber: 'border-amber-500/30 bg-amber-500/10'
          };
          const activeClass = module.enabled ? colorClasses[module.color] : 'border-white/5 bg-black/30';
          
          return (
            <div
              key={module.key}
              className={`p-3 rounded-xl border transition-all ${activeClass}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xl">{module.icon}</span>
                  <div>
                    <h5 className="text-sm font-medium text-white">{module.name}</h5>
                    <p className="text-[12px] text-zinc-400">{module.description}</p>
                  </div>
                </div>
                <button
                  onClick={() => onToggleModule(module.key, !module.enabled)}
                  disabled={isLoading}
                  className={`relative w-10 h-5 rounded-full transition-all ${
                    module.enabled 
                      ? module.color === 'violet' ? 'bg-violet-500' 
                        : module.color === 'cyan' ? 'bg-cyan-500'
                        : module.color === 'emerald' ? 'bg-emerald-500'
                        : 'bg-amber-500'
                      : 'bg-zinc-700'
                  } ${isLoading ? 'opacity-50' : ''}`}
                  data-testid={`toggle-${module.key}`}
                >
                  {isLoading ? (
                    <Loader className="w-3 h-3 absolute top-1 left-1 text-white animate-spin" />
                  ) : (
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${
                      module.enabled ? 'left-5' : 'left-0.5'
                    }`} />
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Shadow Stats */}
      {aiStatus?.shadow_stats && (
        <div className="p-3 rounded-xl bg-black/30 border border-white/5">
          <h5 className="text-[12px] font-bold text-zinc-400 uppercase mb-2">Shadow Tracking Stats</h5>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-bold text-white">{aiStatus.shadow_stats.total_decisions?.toLocaleString()}</p>
              <p className="text-[11px] text-zinc-500">Decisions</p>
            </div>
            <div>
              <p className="text-lg font-bold text-emerald-400">{aiStatus.shadow_stats.executed_decisions?.toLocaleString()}</p>
              <p className="text-[11px] text-zinc-500">Executed</p>
            </div>
            <div>
              <p className="text-lg font-bold text-violet-400">{aiStatus.shadow_stats.shadow_only?.toLocaleString()}</p>
              <p className="text-[11px] text-zinc-500">Shadow Only</p>
            </div>
          </div>
          {(aiStatus.shadow_stats.outcomes_tracked > 0 || aiStatus.shadow_stats.avg_confidence > 0) && (
            <div className="mt-2 pt-2 border-t border-white/5 grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-sm font-bold text-cyan-400">{aiStatus.shadow_stats.outcomes_tracked?.toLocaleString()}</p>
                <p className="text-[11px] text-zinc-500">Tracked</p>
              </div>
              <div>
                <p className={`text-sm font-bold ${(aiStatus.shadow_stats.win_rate || 0) >= 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {aiStatus.shadow_stats.win_rate || 0}%
                </p>
                <p className="text-[11px] text-zinc-500">Win Rate</p>
              </div>
              <div>
                <p className="text-sm font-bold text-amber-400">{((aiStatus.shadow_stats.avg_confidence || 0) * 100).toFixed(0)}%</p>
                <p className="text-[11px] text-zinc-500">Avg Confidence</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
