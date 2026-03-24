import React, { useState, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Cpu, Brain, TrendingUp, TrendingDown, Shield,
  ChevronDown, Database, Zap, CheckCircle2, AlertTriangle, XCircle
} from 'lucide-react';

const AIModulesPanel = memo(({ data, connectors, thresholds, onRefresh, onRunCalibrations }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('performance');

  const modules = useMemo(() => [
    { name: 'Time-Series AI', accuracy: data.timeseriesAccuracy, predictions: data.timeseriesPredictions, lastTrained: data.timeseriesLastTrained, icon: Brain },
    { name: 'Bull Agent', winRate: data.bullWinRate, debates: data.bullDebates, icon: TrendingUp },
    { name: 'Bear Agent', winRate: data.bearWinRate, debates: data.bearDebates, icon: TrendingDown },
    { name: 'Risk Manager', interventions: data.riskInterventions, saved: data.riskSaved, icon: Shield }
  ], [data.timeseriesAccuracy, data.timeseriesPredictions, data.timeseriesLastTrained, data.bullWinRate, data.bullDebates, data.bearWinRate, data.bearDebates, data.riskInterventions, data.riskSaved]);

  const connectionStatus = connectors?.connections || {};

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="ai-modules-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="ai-modules-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))' }}>
            <Cpu className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">AI Modules & Connectors</h3>
            <p className="text-xs text-zinc-400">Performance, data flow & calibration</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {data.timeseriesAccuracy && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400">
              {(data.timeseriesAccuracy * 100).toFixed(1)}% acc
            </span>
          )}
          <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-white/10"
          >
            {/* Tabs */}
            <div className="flex border-b border-white/10">
              <button
                onClick={() => setActiveTab('performance')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${activeTab === 'performance' ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5' : 'text-zinc-500 hover:text-zinc-300'}`}
                data-testid="ai-tab-performance"
              >
                <Cpu className="w-3 h-3" /> Performance
              </button>
              <button
                onClick={() => setActiveTab('connectors')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${activeTab === 'connectors' ? 'text-violet-400 border-b-2 border-violet-400 bg-violet-500/5' : 'text-zinc-500 hover:text-zinc-300'}`}
                data-testid="ai-tab-connectors"
              >
                <Database className="w-3 h-3" /> Connectors
              </button>
            </div>

            {activeTab === 'performance' ? (
              <div>
                <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                  {modules.map((module) => (
                    <div key={module.name} className="p-3 rounded-lg border border-white/5 bg-white/[0.02]">
                      <div className="flex items-center gap-2 mb-2">
                        <module.icon className="w-4 h-4 text-cyan-400" />
                        <span className="text-sm font-medium text-white">{module.name}</span>
                      </div>
                      {module.accuracy !== undefined && (
                        <>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-zinc-400">Accuracy</span>
                            <span className={`font-mono ${module.accuracy >= 0.55 ? 'text-green-400' : module.accuracy >= 0.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                              {module.accuracy !== null ? `${(module.accuracy * 100).toFixed(1)}%` : '--'}
                            </span>
                          </div>
                          {module.lastTrained && (
                            <div className="flex items-center justify-between text-xs mt-1">
                              <span className="text-zinc-400">Last Trained</span>
                              <span className="text-zinc-500 font-mono text-[10px]">{new Date(module.lastTrained).toLocaleDateString()}</span>
                            </div>
                          )}
                        </>
                      )}
                      {module.winRate !== undefined && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-zinc-400">Win Rate</span>
                          <span className={`font-mono ${module.winRate >= 0.55 ? 'text-green-400' : 'text-yellow-400'}`}>
                            {module.winRate !== null ? `${(module.winRate * 100).toFixed(1)}%` : '--'}
                          </span>
                        </div>
                      )}
                      {module.predictions !== undefined && (
                        <div className="flex items-center justify-between text-xs mt-1">
                          <span className="text-zinc-400">Training Samples</span>
                          <span className="text-zinc-300 font-mono">{module.predictions?.toLocaleString() || '--'}</span>
                        </div>
                      )}
                      {module.debates !== undefined && (
                        <div className="flex items-center justify-between text-xs mt-1">
                          <span className="text-zinc-400">Debates</span>
                          <span className="text-zinc-300 font-mono">{module.debates ?? '--'}</span>
                        </div>
                      )}
                      {module.interventions !== undefined && (
                        <div className="flex items-center justify-between text-xs mt-1">
                          <span className="text-zinc-400">Interventions</span>
                          <span className="text-zinc-300 font-mono">{module.interventions ?? '--'}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {/* AI Advisor Status */}
                <div className="px-4 pb-4">
                  <div className="p-3 rounded-lg border border-cyan-500/20 bg-cyan-500/5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Brain className="w-4 h-4 text-cyan-400" />
                        <span className="text-sm text-white">AI Advisor in Debate</span>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400">
                        {data.aiAdvisorWeight ? `${(data.aiAdvisorWeight * 100).toFixed(0)}% weight` : '15% weight'}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-400 mt-1">Time-Series AI predictions now influence Bull/Bear debate outcomes</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-4">
                {/* Calibration Button */}
                <div className="flex items-center justify-between mb-4">
                  <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Connection Health</h4>
                  <button
                    onClick={onRunCalibrations}
                    className="text-xs px-2 py-1 rounded bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 transition-colors flex items-center gap-1"
                    data-testid="run-calibrations-btn"
                  >
                    <Zap className="w-3 h-3" /> Run Calibrations
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2 mb-4">
                  {Object.entries(connectionStatus).map(([name, status]) => (
                    <div key={name} className="flex items-center justify-between p-2 rounded bg-white/[0.02] border border-white/5">
                      <span className="text-xs text-zinc-400">{name.replace(/_/g, ' ')}</span>
                      <span className={`text-xs ${status.health === 'healthy' ? 'text-green-400' : status.health === 'warning' ? 'text-yellow-400' : 'text-zinc-500'}`}>
                        {status.health === 'healthy' ? <CheckCircle2 className="w-3 h-3" /> : status.health === 'warning' ? <AlertTriangle className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      </span>
                    </div>
                  ))}
                  {Object.keys(connectionStatus).length === 0 && (
                    <div className="col-span-2 text-xs text-zinc-500 text-center py-4">No connector data available</div>
                  )}
                </div>

                {/* Applied Thresholds */}
                {thresholds && Object.keys(thresholds).length > 0 && (
                  <>
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Auto-Calibrated Thresholds</h4>
                    <div className="space-y-1">
                      {Object.entries(thresholds).map(([setup, d]) => (
                        <div key={setup} className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5">
                          <span className="text-xs text-zinc-300">{setup}</span>
                          <div className="flex items-center gap-2">
                            <span className={`text-xs font-mono ${d.value > 1 ? 'text-yellow-400' : d.value < 1 ? 'text-green-400' : 'text-zinc-400'}`}>{d.value?.toFixed(2)}x</span>
                            <span className="text-[10px] text-zinc-500">{(d.win_rate_30d * 100).toFixed(0)}% WR</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default AIModulesPanel;
