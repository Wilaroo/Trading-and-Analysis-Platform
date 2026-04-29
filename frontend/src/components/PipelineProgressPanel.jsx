/**
 * PipelineProgressPanel - Per-phase progress bars for the training pipeline
 * =========================================================================
 * Reads real-time training status from the WebSocket stream (trainingStatus)
 * and renders a compact progress bar for each active/completed phase.
 * 
 * Zero extra polling — purely reads from the existing WS broadcast.
 */
import React, { memo, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2, Loader2, XCircle, AlertCircle,
  Brain, Layers, TrendingDown, BarChart3, Clock,
  Globe, Gauge, GitBranch, Target, Sparkles, Shield
} from 'lucide-react';

// Phase icon mapping (matches PHASE_CONFIGS order in training_pipeline.py)
const PHASE_ICONS = {
  generic_directional: TrendingDown,
  setup_specific: Target,
  short_setup_specific: TrendingDown,
  volatility_prediction: BarChart3,
  exit_timing: Clock,
  sector_relative: Globe,
  risk_of_ruin: Shield,
  regime_conditional: GitBranch,
  ensemble_meta: Layers,
  cnn_patterns: Brain,
  auto_validation: Sparkles,
};

const PHASE_COLORS = {
  generic_directional: { bar: 'bg-cyan-500', text: 'text-cyan-400', bg: 'bg-cyan-500/10' },
  setup_specific: { bar: 'bg-green-500', text: 'text-green-400', bg: 'bg-green-500/10' },
  short_setup_specific: { bar: 'bg-red-500', text: 'text-red-400', bg: 'bg-red-500/10' },
  volatility_prediction: { bar: 'bg-amber-500', text: 'text-amber-400', bg: 'bg-amber-500/10' },
  exit_timing: { bar: 'bg-orange-500', text: 'text-orange-400', bg: 'bg-orange-500/10' },
  sector_relative: { bar: 'bg-blue-500', text: 'text-blue-400', bg: 'bg-blue-500/10' },
  risk_of_ruin: { bar: 'bg-rose-500', text: 'text-rose-400', bg: 'bg-rose-500/10' },
  regime_conditional: { bar: 'bg-violet-500', text: 'text-violet-400', bg: 'bg-violet-500/10' },
  ensemble_meta: { bar: 'bg-purple-500', text: 'text-purple-400', bg: 'bg-purple-500/10' },
  cnn_patterns: { bar: 'bg-indigo-500', text: 'text-indigo-400', bg: 'bg-indigo-500/10' },
  auto_validation: { bar: 'bg-teal-500', text: 'text-teal-400', bg: 'bg-teal-500/10' },
};

const DEFAULT_COLOR = { bar: 'bg-zinc-500', text: 'text-zinc-400', bg: 'bg-zinc-500/10' };

const PhaseRow = memo(({ phaseKey, phase, isCurrent }) => {
  const Icon = PHASE_ICONS[phaseKey] || Brain;
  const colors = PHASE_COLORS[phaseKey] || DEFAULT_COLOR;
  const trained = phase.models_trained || 0;
  const failed = phase.models_failed || 0;
  const expected = phase.expected_models || 1;
  const done = trained + failed;
  const pct = Math.min(100, (done / expected) * 100);
  const isDone = phase.status === 'done';
  const avgAcc = phase.avg_accuracy ? (phase.avg_accuracy * 100).toFixed(1) : null;
  const elapsed = phase.elapsed_seconds
    ? `${Math.floor(phase.elapsed_seconds / 60)}m ${Math.floor(phase.elapsed_seconds % 60)}s`
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
        isCurrent ? `${colors.bg} border border-white/10` : 'hover:bg-white/[0.02]'
      }`}
      data-testid={`pipeline-phase-${phaseKey}`}
    >
      {/* Icon */}
      <div className={`flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center ${colors.bg}`}>
        {isCurrent && !isDone ? (
          <Loader2 className={`w-3.5 h-3.5 ${colors.text} animate-spin`} />
        ) : isDone ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
        ) : (
          <Icon className={`w-3.5 h-3.5 ${colors.text}`} />
        )}
      </div>

      {/* Label + bar */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className={`text-xs font-medium truncate ${isDone ? 'text-zinc-300' : isCurrent ? 'text-white' : 'text-zinc-500'}`}>
            {phase.label || phaseKey}
            {phase.phase_num ? <span className="text-zinc-600 ml-1">P{phase.phase_num}</span> : null}
          </span>
          <span className="text-[12px] text-zinc-500 flex-shrink-0 ml-2 tabular-nums">
            {trained}/{expected}
            {failed > 0 && <span className="text-red-400 ml-1">({failed} err)</span>}
          </span>
        </div>
        {/* Progress bar */}
        <div className="h-1.5 bg-black/40 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            className={`h-full rounded-full ${isDone ? 'bg-green-500' : colors.bar}`}
          />
        </div>
      </div>

      {/* Accuracy badge */}
      <div className="flex-shrink-0 w-16 text-right">
        {avgAcc ? (
          <span className={`text-[12px] font-mono ${
            parseFloat(avgAcc) >= 60 ? 'text-green-400' : parseFloat(avgAcc) >= 50 ? 'text-yellow-400' : 'text-red-400'
          }`}>
            {avgAcc}%
          </span>
        ) : isDone ? (
          elapsed ? <span className="text-[12px] text-zinc-600">{elapsed}</span> : null
        ) : null}
      </div>
    </motion.div>
  );
});

const PipelineProgressPanel = memo(({ trainingStatus }) => {
  // Parse the pipeline status from the WS data
  const { phases, currentPhase, overallPct, totalTrained, totalExpected, currentModel } = useMemo(() => {
    if (!trainingStatus || !trainingStatus.phase_history) {
      return { phases: [], currentPhase: null, overallPct: 0, totalTrained: 0, totalExpected: 0, currentModel: '' };
    }

    const ph = trainingStatus.phase_history;
    const sorted = Object.entries(ph)
      .map(([key, val]) => ({ key, ...val }))
      .sort((a, b) => (a.order || 0) - (b.order || 0));

    const completed = trainingStatus.models_completed || 0;
    const total = trainingStatus.models_total || 1;
    const pct = Math.min(100, (completed / total) * 100);

    return {
      phases: sorted,
      currentPhase: trainingStatus.phase,
      overallPct: pct,
      totalTrained: completed,
      totalExpected: total,
      currentModel: trainingStatus.current_model || '',
    };
  }, [trainingStatus]);

  // Don't render if idle or no phases
  const isActive = trainingStatus && trainingStatus.phase && trainingStatus.phase !== 'idle';
  if (!isActive && phases.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25 }}
      className="mb-4 rounded-xl border border-white/10 overflow-hidden"
      style={{ background: 'linear-gradient(135deg, rgba(10,15,20,0.9), rgba(15,22,32,0.9))' }}
      data-testid="pipeline-progress-panel"
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-semibold text-white">Pipeline Progress</span>
          {currentModel && (
            <span className="text-xs text-zinc-500 truncate max-w-[200px]" title={currentModel}>
              {currentModel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-400 tabular-nums">{totalTrained}/{totalExpected} models</span>
          <span className="text-sm font-bold text-cyan-400 tabular-nums">{overallPct.toFixed(0)}%</span>
        </div>
      </div>

      {/* Overall progress bar */}
      <div className="px-4 pt-2 pb-1">
        <div className="h-2 bg-black/50 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${overallPct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
            className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-500"
          />
        </div>
      </div>

      {/* Phase rows */}
      <div className="px-2 py-2 space-y-0.5 max-h-[320px] overflow-y-auto">
        <AnimatePresence>
          {phases.map((phase) => (
            <PhaseRow
              key={phase.key}
              phaseKey={phase.key}
              phase={phase}
              isCurrent={currentPhase === phase.key}
            />
          ))}
        </AnimatePresence>
      </div>

      {/* Idle / completed footer */}
      {trainingStatus?.phase === 'completed' && (
        <div className="px-4 py-2 border-t border-white/5 flex items-center gap-2 text-xs text-green-400">
          <CheckCircle2 className="w-3.5 h-3.5" />
          Pipeline complete — {totalTrained} models trained
        </div>
      )}
    </motion.div>
  );
});

export default PipelineProgressPanel;
