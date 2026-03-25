import React, { useState, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, ChevronDown, Cpu, TrendingUp, TrendingDown,
  Shield, Database, Zap, CheckCircle2, AlertTriangle, XCircle
} from 'lucide-react';
import SetupModelsPanel from './SetupModelsPanel';

const AICommandCenter = memo(({ aiData, connectors, thresholds, onRefresh, onRunCalibrations }) => {
  const [expanded, setExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState('models');

  const modules = [
    { name: 'Bull Agent', winRate: aiData.bullWinRate, debates: aiData.bullDebates, icon: TrendingUp },
    { name: 'Bear Agent', winRate: aiData.bearWinRate, debates: aiData.bearDebates, icon: TrendingDown },
    { name: 'Risk Manager', interventions: aiData.riskInterventions, saved: aiData.riskSaved, icon: Shield }
  ];

  const rawConnections = connectors?.connections || [];
  const connectionStatus = Array.isArray(rawConnections)
    ? rawConnections.reduce((acc, c) => { acc[c.name || c.source || 'unknown'] = c; return acc; }, {})
    : rawConnections;

  const tabs = [
    { id: 'models', label: 'Setup Models', icon: Brain, color: 'cyan' },
    { id: 'performance', label: 'Live Performance', icon: Cpu, color: 'violet' },
  ];

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="ai-command-center">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="ai-command-center-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #0ea5e9, #8b5cf6)' }}>
            <Brain className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">AI Command Center</h3>
            <p className="text-xs text-zinc-400">Models, performance & connectors</p>
          </div>
        </div>
        <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-white/10"
          >
            <div className="flex border-b border-white/10">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
                    activeTab === tab.id
                      ? `text-${tab.color}-400 border-b-2 border-${tab.color}-400 bg-${tab.color}-500/5`
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                  data-testid={`ai-tab-${tab.id}`}
                >
                  <tab.icon className="w-3 h-3" /> {tab.label}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'models' && <SetupModelsPanel embedded />}

              {activeTab === 'performance' && (
                <div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                    {modules.map(module => (
                      <div key={module.name} className="p-3 rounded-lg border border-white/5 bg-white/[0.02]">
                        <div className="flex items-center gap-2 mb-2">
                          <module.icon className="w-4 h-4 text-cyan-400" />
                          <span className="text-sm font-medium text-white">{module.name}</span>
                        </div>
                        {module.winRate !== undefined && (
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-zinc-400">Win Rate</span>
                            <span className={`font-mono ${module.winRate >= 0.55 ? 'text-green-400' : 'text-yellow-400'}`}>
                              {module.winRate != null ? `${(module.winRate * 100).toFixed(1)}%` : '--'}
                            </span>
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

                  {/* AI Advisor */}
                  <div className="p-3 rounded-lg border border-cyan-500/20 bg-cyan-500/5 mb-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Brain className="w-4 h-4 text-cyan-400" />
                        <span className="text-sm text-white">AI Advisor Weight</span>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400">
                        {aiData.aiAdvisorWeight ? `${(aiData.aiAdvisorWeight * 100).toFixed(0)}%` : '15%'}
                      </span>
                    </div>
                  </div>

                  {/* Connectors */}
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Connectors</h4>
                    <button onClick={onRunCalibrations} className="text-xs px-2 py-1 rounded bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 flex items-center gap-1" data-testid="run-calibrations-btn">
                      <Zap className="w-3 h-3" /> Calibrate
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mb-4">
                    {Object.entries(connectionStatus).map(([name, st]) => (
                      <div key={name} className="flex items-center justify-between p-2 rounded bg-white/[0.02] border border-white/5">
                        <span className="text-xs text-zinc-400">{name.replace(/_/g, ' ')}</span>
                        {st.health === 'healthy' ? <CheckCircle2 className="w-3 h-3 text-green-400" /> :
                         st.health === 'warning' ? <AlertTriangle className="w-3 h-3 text-yellow-400" /> :
                         <XCircle className="w-3 h-3 text-zinc-500" />}
                      </div>
                    ))}
                    {Object.keys(connectionStatus).length === 0 && (
                      <div className="col-span-2 text-xs text-zinc-500 text-center py-4">No connector data</div>
                    )}
                  </div>

                  {/* Thresholds */}
                  {thresholds && Object.keys(thresholds).length > 0 && (
                    <>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Auto-Calibrated Thresholds</h4>
                      <div className="space-y-1">
                        {Object.entries(thresholds).map(([setup, d]) => (
                          <div key={setup} className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5">
                            <span className="text-xs text-zinc-300">{setup}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs font-mono ${d.value > 1 ? 'text-yellow-400' : 'text-green-400'}`}>{d.value?.toFixed(2)}x</span>
                              <span className="text-[10px] text-zinc-500">{(d.win_rate_30d * 100).toFixed(0)}% WR</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default AICommandCenter;
