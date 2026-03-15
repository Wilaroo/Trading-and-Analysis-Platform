/**
 * NIA - Neural Intelligence Agency
 * =================================
 * The intelligence arm of SentCom. Gathers insights, analyzes AI performance,
 * tracks learning progress, and monitors strategy lifecycle.
 * 
 * Sections:
 * 1. Intel Overview - Key metrics at a glance
 * 2. AI Performance - Time-Series AI accuracy, module comparison
 * 3. Strategy Lifecycle - SIMULATION → PAPER → LIVE progression
 * 4. Learning Connectors - Data flow health and calibration
 */

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Activity,
  TrendingUp,
  TrendingDown,
  Target,
  Shield,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  Loader2,
  BarChart3,
  Layers,
  GitBranch,
  Play,
  Pause,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  Database,
  Cpu,
  Eye,
  FlaskConical,
  Rocket
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';

// ==================== SECTION COMPONENTS ====================

const IntelOverview = ({ data, loading }) => {
  const metrics = [
    {
      label: 'AI Accuracy',
      value: data.aiAccuracy ? `${(data.aiAccuracy * 100).toFixed(1)}%` : '--',
      trend: data.aiAccuracyTrend,
      icon: Brain,
      color: 'cyan'
    },
    {
      label: 'Strategies Live',
      value: data.liveStrategies || 0,
      subtext: `${data.paperStrategies || 0} in paper`,
      icon: Rocket,
      color: 'green'
    },
    {
      label: 'Learning Health',
      value: data.learningHealth || '--',
      icon: Activity,
      color: data.learningHealth === 'Healthy' ? 'green' : data.learningHealth === 'Warning' ? 'yellow' : 'red'
    },
    {
      label: 'Calibrations Today',
      value: data.calibrationsToday || 0,
      icon: Zap,
      color: 'violet'
    }
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
      {metrics.map((metric, idx) => (
        <motion.div
          key={metric.label}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.1 }}
          className="relative p-4 rounded-xl border border-white/10 overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.9), rgba(30, 41, 59, 0.8))'
          }}
        >
          {/* Glow effect */}
          <div 
            className="absolute inset-0 opacity-20"
            style={{
              background: `radial-gradient(circle at top right, var(--${metric.color === 'cyan' ? 'primary' : metric.color === 'green' ? 'success' : metric.color === 'violet' ? 'secondary' : 'warning'}-main), transparent 70%)`
            }}
          />
          
          <div className="relative">
            <div className="flex items-center justify-between mb-2">
              <metric.icon className={`w-4 h-4 text-${metric.color}-400`} />
              {metric.trend !== undefined && (
                <span className={`text-xs flex items-center gap-0.5 ${metric.trend >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {metric.trend >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                  {Math.abs(metric.trend).toFixed(1)}%
                </span>
              )}
            </div>
            <div className="text-2xl font-bold text-white mb-0.5">
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : metric.value}
            </div>
            <div className="text-xs text-zinc-400">{metric.label}</div>
            {metric.subtext && (
              <div className="text-[10px] text-zinc-500 mt-1">{metric.subtext}</div>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  );
};

const AIPerformancePanel = ({ data, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  
  const modules = [
    { name: 'Time-Series AI', accuracy: data.timeseriesAccuracy, predictions: data.timeseriesPredictions, icon: Brain },
    { name: 'Bull Agent', winRate: data.bullWinRate, debates: data.bullDebates, icon: TrendingUp },
    { name: 'Bear Agent', winRate: data.bearWinRate, debates: data.bearDebates, icon: TrendingDown },
    { name: 'Risk Manager', interventions: data.riskInterventions, saved: data.riskSaved, icon: Shield }
  ];

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))' }}>
            <Cpu className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">AI Module Performance</h3>
            <p className="text-xs text-zinc-400">How each AI component is performing</p>
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
            <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
              {modules.map((module, idx) => (
                <div
                  key={module.name}
                  className="p-3 rounded-lg border border-white/5 bg-white/[0.02]"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <module.icon className="w-4 h-4 text-cyan-400" />
                    <span className="text-sm font-medium text-white">{module.name}</span>
                  </div>
                  
                  {module.accuracy !== undefined && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">Accuracy</span>
                      <span className={`font-mono ${module.accuracy >= 0.55 ? 'text-green-400' : module.accuracy >= 0.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {loading ? '--' : `${(module.accuracy * 100).toFixed(1)}%`}
                      </span>
                    </div>
                  )}
                  
                  {module.winRate !== undefined && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">Win Rate</span>
                      <span className={`font-mono ${module.winRate >= 0.55 ? 'text-green-400' : 'text-yellow-400'}`}>
                        {loading ? '--' : `${(module.winRate * 100).toFixed(1)}%`}
                      </span>
                    </div>
                  )}
                  
                  {module.predictions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Predictions</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.predictions.toLocaleString()}</span>
                    </div>
                  )}
                  
                  {module.debates !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Debates</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.debates}</span>
                    </div>
                  )}
                  
                  {module.interventions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Interventions</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.interventions}</span>
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
                <p className="text-xs text-zinc-400 mt-1">
                  Time-Series AI predictions now influence Bull/Bear debate outcomes
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const StrategyLifecyclePanel = ({ phases, candidates, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(true);
  
  const phaseColors = {
    simulation: 'text-blue-400 bg-blue-500/20',
    paper: 'text-yellow-400 bg-yellow-500/20',
    live: 'text-green-400 bg-green-500/20',
    demoted: 'text-red-400 bg-red-500/20',
    disabled: 'text-zinc-400 bg-zinc-500/20'
  };
  
  const phaseIcons = {
    simulation: FlaskConical,
    paper: Eye,
    live: Rocket,
    demoted: TrendingDown,
    disabled: Pause
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}>
            <GitBranch className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Strategy Lifecycle</h3>
            <p className="text-xs text-zinc-400">SIMULATION → PAPER → LIVE progression</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {candidates?.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 animate-pulse">
              {candidates.length} ready to promote
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
            {/* Phase Pipeline Visual */}
            <div className="p-4">
              <div className="flex items-center justify-between mb-4">
                {['simulation', 'paper', 'live'].map((phase, idx) => {
                  const Icon = phaseIcons[phase];
                  const count = phases?.by_phase?.[phase]?.length || 0;
                  return (
                    <React.Fragment key={phase}>
                      <div className="flex flex-col items-center">
                        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${phaseColors[phase]}`}>
                          <Icon className="w-5 h-5" />
                        </div>
                        <span className="text-xs text-zinc-400 mt-1 capitalize">{phase}</span>
                        <span className="text-lg font-bold text-white">{loading ? '-' : count}</span>
                      </div>
                      {idx < 2 && (
                        <div className="flex-1 h-0.5 bg-gradient-to-r from-white/20 to-white/20 mx-2 relative">
                          <ChevronRight className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                        </div>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
            
            {/* Promotion Candidates */}
            {candidates && candidates.length > 0 && (
              <div className="px-4 pb-4">
                <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                  Ready for Promotion
                </h4>
                <div className="space-y-2">
                  {candidates.slice(0, 5).map((candidate) => (
                    <div
                      key={candidate.strategy_name}
                      className="flex items-center justify-between p-2 rounded-lg bg-white/[0.02] border border-white/5"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${phaseColors[candidate.current_phase]}`}>
                          {candidate.current_phase}
                        </span>
                        <span className="text-sm text-white">{candidate.strategy_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {candidate.meets_requirements ? (
                          <>
                            <span className="text-xs text-green-400">
                              {(candidate.performance?.win_rate * 100).toFixed(0)}% WR
                            </span>
                            <button
                              onClick={() => onPromote(candidate.strategy_name, candidate.target_phase)}
                              className="text-xs px-2 py-1 rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors"
                            >
                              Promote → {candidate.target_phase}
                            </button>
                          </>
                        ) : (
                          <span className="text-xs text-zinc-500">
                            {candidate.issues?.[0] || 'Not ready'}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {/* All Strategies by Phase */}
            <div className="px-4 pb-4">
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                All Strategies
              </h4>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {phases?.phases && Object.entries(phases.phases).map(([name, phase]) => {
                  const Icon = phaseIcons[phase] || FlaskConical;
                  return (
                    <div
                      key={name}
                      className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/5"
                    >
                      <div className="flex items-center gap-2">
                        <Icon className={`w-3 h-3 ${phaseColors[phase]?.split(' ')[0] || 'text-zinc-400'}`} />
                        <span className="text-xs text-zinc-300">{name}</span>
                      </div>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${phaseColors[phase]}`}>
                        {phase}
                      </span>
                    </div>
                  );
                })}
                {(!phases?.phases || Object.keys(phases.phases).length === 0) && (
                  <div className="text-xs text-zinc-500 text-center py-4">
                    No strategies tracked yet. Run simulations to populate.
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const LearningConnectorsPanel = ({ connectors, thresholds, loading, onRunCalibrations }) => {
  const [expanded, setExpanded] = useState(false);
  
  const connectionStatus = connectors?.connections || {};
  
  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #8b5cf6, #6366f1)' }}>
            <Database className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Learning Connectors</h3>
            <p className="text-xs text-zinc-400">Data flow and calibration status</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onRunCalibrations(); }}
            className="text-xs px-2 py-1 rounded bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 transition-colors flex items-center gap-1"
          >
            <Zap className="w-3 h-3" />
            Run Calibrations
          </button>
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
            <div className="p-4">
              {/* Connection Status */}
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                Connection Health
              </h4>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {Object.entries(connectionStatus).map(([name, status]) => (
                  <div
                    key={name}
                    className="flex items-center justify-between p-2 rounded bg-white/[0.02] border border-white/5"
                  >
                    <span className="text-xs text-zinc-400">{name.replace(/_/g, ' ')}</span>
                    <span className={`text-xs ${status.health === 'healthy' ? 'text-green-400' : status.health === 'warning' ? 'text-yellow-400' : 'text-zinc-500'}`}>
                      {status.health === 'healthy' ? (
                        <CheckCircle2 className="w-3 h-3" />
                      ) : status.health === 'warning' ? (
                        <AlertTriangle className="w-3 h-3" />
                      ) : (
                        <XCircle className="w-3 h-3" />
                      )}
                    </span>
                  </div>
                ))}
              </div>
              
              {/* Applied Thresholds */}
              {thresholds && Object.keys(thresholds).length > 0 && (
                <>
                  <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                    Auto-Calibrated Thresholds
                  </h4>
                  <div className="space-y-1">
                    {Object.entries(thresholds).map(([setup, data]) => (
                      <div
                        key={setup}
                        className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5"
                      >
                        <span className="text-xs text-zinc-300">{setup}</span>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-mono ${data.value > 1 ? 'text-yellow-400' : data.value < 1 ? 'text-green-400' : 'text-zinc-400'}`}>
                            {data.value?.toFixed(2)}x
                          </span>
                          <span className="text-[10px] text-zinc-500">
                            {(data.win_rate_30d * 100).toFixed(0)}% WR
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const ReportCardPanel = ({ reportCard, loading }) => {
  const [expanded, setExpanded] = useState(true);
  
  const getWinRateColor = (wr) => {
    if (wr >= 0.55) return 'text-green-400';
    if (wr >= 0.5) return 'text-yellow-400';
    return 'text-red-400';
  };
  
  const getWinRateBg = (wr) => {
    if (wr >= 0.55) return 'bg-green-500/20';
    if (wr >= 0.5) return 'bg-yellow-500/20';
    return 'bg-red-500/20';
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
            <BarChart3 className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Your Trading Report Card</h3>
            <p className="text-xs text-zinc-400">Personal performance insights</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {reportCard?.overall_stats?.total_trades > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
              {reportCard.overall_stats.total_trades} trades
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
            <div className="p-4">
              {!reportCard?.has_data ? (
                <div className="text-center py-6">
                  <BarChart3 className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-sm text-zinc-400">No trading data yet</p>
                  <p className="text-xs text-zinc-500 mt-1">Complete some trades to see your report card</p>
                </div>
              ) : (
                <>
                  {/* Overall Stats */}
                  <div className="grid grid-cols-4 gap-2 mb-4">
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className="text-lg font-bold text-white">
                        {reportCard.overall_stats?.total_trades || 0}
                      </div>
                      <div className="text-[10px] text-zinc-500">Total Trades</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className={`text-lg font-bold ${getWinRateColor(reportCard.overall_stats?.win_rate || 0)}`}>
                        {((reportCard.overall_stats?.win_rate || 0) * 100).toFixed(0)}%
                      </div>
                      <div className="text-[10px] text-zinc-500">Win Rate</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className={`text-lg font-bold ${(reportCard.overall_stats?.avg_r_multiple || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {(reportCard.overall_stats?.avg_r_multiple || 0).toFixed(2)}R
                      </div>
                      <div className="text-[10px] text-zinc-500">Avg R</div>
                    </div>
                    <div className="p-2 rounded-lg bg-white/[0.03] text-center">
                      <div className="text-lg font-bold text-cyan-400">
                        {reportCard.overall_stats?.winning_trades || 0}
                      </div>
                      <div className="text-[10px] text-zinc-500">Winners</div>
                    </div>
                  </div>
                  
                  {/* By Symbol and By Setup side by side */}
                  <div className="grid grid-cols-2 gap-4">
                    {/* By Symbol */}
                    <div>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                        <Target className="w-3 h-3" />
                        By Symbol
                      </h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {reportCard.by_symbol?.map((sym) => (
                          <div
                            key={sym.symbol}
                            className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5"
                          >
                            <span className="text-xs text-zinc-300 font-mono">{sym.symbol}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${getWinRateBg(sym.win_rate)} ${getWinRateColor(sym.win_rate)}`}>
                                {(sym.win_rate * 100).toFixed(0)}%
                              </span>
                              <span className="text-[10px] text-zinc-500">
                                ({sym.total_trades})
                              </span>
                            </div>
                          </div>
                        ))}
                        {(!reportCard.by_symbol || reportCard.by_symbol.length === 0) && (
                          <div className="text-xs text-zinc-500 text-center py-2">No symbol data</div>
                        )}
                      </div>
                    </div>
                    
                    {/* By Setup */}
                    <div>
                      <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                        <Layers className="w-3 h-3" />
                        By Setup Type
                      </h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {reportCard.by_setup?.map((setup) => (
                          <div
                            key={setup.setup_type}
                            className="flex items-center justify-between py-1 px-2 rounded hover:bg-white/5"
                          >
                            <span className="text-xs text-zinc-300">{setup.setup_type}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${getWinRateBg(setup.win_rate)} ${getWinRateColor(setup.win_rate)}`}>
                                {(setup.win_rate * 100).toFixed(0)}%
                              </span>
                              <span className="text-[10px] text-zinc-500">
                                ({setup.traded_count})
                              </span>
                            </div>
                          </div>
                        ))}
                        {(!reportCard.by_setup || reportCard.by_setup.length === 0) && (
                          <div className="text-xs text-zinc-500 text-center py-2">No setup data</div>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  {/* Insights */}
                  {reportCard.insights && reportCard.insights.length > 0 && (
                    <div className="mt-4 p-3 rounded-lg border border-amber-500/20 bg-amber-500/5">
                      <h4 className="text-xs font-semibold text-amber-400 mb-2 flex items-center gap-1">
                        <Zap className="w-3 h-3" />
                        Insights
                      </h4>
                      <ul className="space-y-1">
                        {reportCard.insights.map((insight, idx) => (
                          <li key={idx} className="text-xs text-zinc-300 flex items-start gap-2">
                            <span className="text-amber-500 mt-0.5">•</span>
                            {insight}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// ==================== MAIN COMPONENT ====================

const NIA = () => {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [data, setData] = useState({
    // Overview metrics
    aiAccuracy: null,
    aiAccuracyTrend: null,
    liveStrategies: 0,
    paperStrategies: 0,
    learningHealth: null,
    calibrationsToday: 0,
    
    // AI Performance
    timeseriesAccuracy: null,
    timeseriesPredictions: 0,
    bullWinRate: null,
    bullDebates: 0,
    bearWinRate: null,
    bearDebates: 0,
    riskInterventions: 0,
    riskSaved: 0,
    aiAdvisorWeight: 0.15,
    
    // Strategy Lifecycle
    phases: null,
    candidates: [],
    
    // Learning Connectors
    connectors: null,
    thresholds: {},
    
    // Report Card (NEW)
    reportCard: null
  });

  const fetchAllData = useCallback(async (showToast = false) => {
    try {
      if (showToast) setRefreshing(true);
      else setLoading(true);

      // Fetch all data in parallel
      const [
        phasesRes,
        candidatesRes,
        connectorsRes,
        thresholdsRes,
        timeseriesRes,
        aiAdvisorRes,
        shadowStatsRes,
        reportCardRes
      ] = await Promise.allSettled([
        api.get('/api/strategy-promotion/phases'),
        api.get('/api/strategy-promotion/candidates'),
        api.get('/api/learning-connectors/status'),
        api.get('/api/learning-connectors/thresholds'),
        api.get('/api/ai-modules/timeseries/status'),
        api.get('/api/ai-modules/debate/ai-advisor-status'),
        api.get('/api/ai-modules/shadow/stats'),
        api.get('/api/ai-modules/report-card')
      ]);

      const newData = { ...data };

      // Process phases
      if (phasesRes.status === 'fulfilled' && phasesRes.value.data?.success) {
        const phases = phasesRes.value.data;
        newData.phases = phases;
        newData.liveStrategies = phases.by_phase?.live?.length || 0;
        newData.paperStrategies = phases.by_phase?.paper?.length || 0;
      }

      // Process candidates
      if (candidatesRes.status === 'fulfilled' && candidatesRes.value.data?.success) {
        newData.candidates = candidatesRes.value.data.ready_for_promotion || [];
      }

      // Process connectors
      if (connectorsRes.status === 'fulfilled' && connectorsRes.value.data?.success) {
        newData.connectors = connectorsRes.value.data;
        // Determine overall health
        const connections = connectorsRes.value.data.connections || {};
        const healthyCount = Object.values(connections).filter(c => c.health === 'healthy').length;
        const totalCount = Object.keys(connections).length;
        newData.learningHealth = totalCount === 0 ? 'Unknown' : 
          healthyCount === totalCount ? 'Healthy' :
          healthyCount >= totalCount / 2 ? 'Warning' : 'Critical';
      }

      // Process thresholds
      if (thresholdsRes.status === 'fulfilled' && thresholdsRes.value.data?.success) {
        newData.thresholds = thresholdsRes.value.data.thresholds || {};
        newData.calibrationsToday = Object.keys(newData.thresholds).length;
      }

      // Process timeseries status
      if (timeseriesRes.status === 'fulfilled' && timeseriesRes.value.data?.success) {
        const ts = timeseriesRes.value.data.status;
        newData.timeseriesAccuracy = ts?.metrics?.test_accuracy || null;
        newData.timeseriesPredictions = ts?.metrics?.total_predictions || 0;
        newData.aiAccuracy = ts?.metrics?.test_accuracy || null;
      }

      // Process AI advisor
      if (aiAdvisorRes.status === 'fulfilled' && aiAdvisorRes.value.data?.success) {
        newData.aiAdvisorWeight = aiAdvisorRes.value.data.ai_advisor?.current_weight || 0.15;
      }

      // Process shadow stats
      if (shadowStatsRes.status === 'fulfilled' && shadowStatsRes.value.data?.success) {
        const stats = shadowStatsRes.value.data.stats;
        newData.bullDebates = stats?.total_logged || 0;
        newData.bearDebates = stats?.total_logged || 0;
      }

      // Process report card
      if (reportCardRes.status === 'fulfilled' && reportCardRes.value.data?.success) {
        newData.reportCard = reportCardRes.value.data;
      }

      setData(newData);

      if (showToast) {
        toast.success('NIA intel refreshed');
      }
    } catch (err) {
      console.error('Error fetching NIA data:', err);
      if (showToast) {
        toast.error('Failed to refresh intel');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAllData();
    // Refresh every 60 seconds
    const interval = setInterval(() => fetchAllData(), 60000);
    return () => clearInterval(interval);
  }, [fetchAllData]);

  const handlePromote = async (strategyName, targetPhase) => {
    try {
      const res = await api.post('/api/strategy-promotion/promote', {
        strategy_name: strategyName,
        target_phase: targetPhase,
        approved_by: 'user'
      });
      if (res.data?.success) {
        toast.success(`${strategyName} promoted to ${targetPhase}`);
        fetchAllData();
      } else {
        toast.error(res.data?.error || 'Promotion failed');
      }
    } catch (err) {
      toast.error('Failed to promote strategy');
    }
  };

  const handleRunCalibrations = async () => {
    try {
      toast.info('Running all calibrations...');
      const res = await api.post('/api/learning-connectors/sync/run-all-calibrations');
      if (res.data?.success) {
        toast.success(`Calibrations complete. ${res.data.applied_calibrations || 0} applied.`);
        fetchAllData();
      } else {
        toast.warning('Some calibrations had issues');
      }
    } catch (err) {
      toast.error('Failed to run calibrations');
    }
  };

  return (
    <div className="h-full overflow-auto p-4" style={{ background: 'var(--bg-primary)' }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div 
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ 
              background: 'linear-gradient(135deg, #0ea5e9, #8b5cf6)',
              boxShadow: '0 4px 20px rgba(14, 165, 233, 0.3)'
            }}
          >
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              NIA
              <span className="text-xs font-normal text-zinc-400">Neural Intelligence Agency</span>
            </h1>
            <p className="text-xs text-zinc-500">AI performance, strategy lifecycle, and learning health</p>
          </div>
        </div>
        
        <button
          onClick={() => fetchAllData(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-sm text-zinc-300 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing...' : 'Refresh Intel'}
        </button>
      </div>

      {/* Intel Overview */}
      <IntelOverview data={data} loading={loading} />

      {/* AI Performance Panel */}
      <AIPerformancePanel 
        data={data} 
        loading={loading}
        onRefresh={() => fetchAllData(true)}
      />

      {/* Strategy Lifecycle Panel */}
      <StrategyLifecyclePanel
        phases={data.phases}
        candidates={data.candidates}
        loading={loading}
        onPromote={handlePromote}
        onDemote={() => {}}
      />

      {/* Learning Connectors Panel */}
      <LearningConnectorsPanel
        connectors={data.connectors}
        thresholds={data.thresholds}
        loading={loading}
        onRunCalibrations={handleRunCalibrations}
      />

      {/* Trading Report Card Panel */}
      <ReportCardPanel
        reportCard={data.reportCard}
        loading={loading}
      />

      {/* Footer */}
      <div className="text-center text-xs text-zinc-600 mt-6">
        <span className="font-mono">NIA v1.0</span> • Neural Intelligence Agency • Part of <span className="text-cyan-500">SentCom</span>
      </div>
    </div>
  );
};

export default NIA;
