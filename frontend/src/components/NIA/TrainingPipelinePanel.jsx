/**
 * Training Pipeline Panel
 * Unified AI training hub: Train All models, view inventory by group, regime status
 */
import React, { useState, useEffect, useCallback, useRef, memo } from 'react';
import {
  Brain, Play, Square, RefreshCw, TrendingUp,
  Activity, Shield, Clock, Target, BarChart3, Layers, AlertTriangle,
  CheckCircle2, Circle, ChevronDown, ChevronRight, Zap, Eye, Cpu, Monitor, GitBranch,
  Crosshair, Wrench
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../../utils/api';
import { useConnectionManager } from '../../contexts/ConnectionManagerContext';
import { useTrainReadiness } from '../../hooks/useTrainReadiness';
import { isOverrideClick } from '../TrainReadinessGate';

const CATEGORY_ICONS = {
  generic_directional: TrendingUp,
  setup_specific: Target,
  volatility: Activity,
  exit_timing: Clock,
  sector_relative: BarChart3,
  gap_fill: Zap,
  risk_of_ruin: Shield,
  ensemble: Layers,
  regime_conditional: GitBranch,
  cnn_visual: Eye,
};

const CATEGORY_COLORS = {
  generic_directional: 'text-cyan-400',
  setup_specific: 'text-violet-400',
  volatility: 'text-amber-400',
  exit_timing: 'text-emerald-400',
  sector_relative: 'text-blue-400',
  gap_fill: 'text-orange-400',
  risk_of_ruin: 'text-red-400',
  ensemble: 'text-pink-400',
  regime_conditional: 'text-teal-400',
  cnn_visual: 'text-fuchsia-400',
};

// All training phases in execution order
const ALL_PHASES = [
  { key: 'generic_directional', label: 'Generic Directional', num: '1', expected: 7 },
  { key: 'setup_specific', label: 'Setup-Specific (Long)', num: '2', expected: 17 },
  { key: 'short_setup_specific', label: 'Setup-Specific (Short)', num: '2.5', expected: 17 },
  { key: 'volatility_prediction', label: 'Volatility Prediction', num: '3', expected: 7 },
  { key: 'exit_timing', label: 'Exit Timing', num: '4', expected: 10 },
  { key: 'sector_relative', label: 'Sector-Relative', num: '5', expected: 3 },
  { key: 'gap_fill', label: 'Gap Fill Probability', num: '5.5', expected: 3 },
  { key: 'risk_of_ruin', label: 'Risk-of-Ruin', num: '6', expected: 6 },
  { key: 'regime_conditional', label: 'Regime-Conditional', num: '7', expected: 28 },
  { key: 'ensemble_meta', label: 'Ensemble Meta-Learner', num: '8', expected: 10 },
  { key: 'cnn_patterns', label: 'CNN Chart Patterns', num: '9', expected: 34 },
  { key: 'deep_learning', label: 'Deep Learning (VAE/TFT/CNN-LSTM)', num: '11', expected: 3 },
  { key: 'finbert_sentiment', label: 'FinBERT Sentiment', num: '12', expected: 1 },
  { key: 'auto_validation', label: 'Auto-Validation', num: '13', expected: 34 },
];

const formatDuration = (seconds) => {
  if (!seconds || seconds <= 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

const PhaseRow = memo(({ phase, phaseData, isActive, currentModel, phaseProgress }) => {
  const status = phaseData?.status || 'pending';
  const trained = phaseData?.models_trained || 0;
  const _failed = phaseData?.models_failed || 0; // eslint-disable-line no-unused-vars
  const skipped = phaseData?.models_skipped || 0;
  const expected = phaseData?.expected_models || phase.expected;
  const avgAcc = phaseData?.avg_accuracy || 0;
  const elapsed = phaseData?.elapsed_seconds || 0;

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-300 ${
        isActive ? 'bg-cyan-500/5 border border-cyan-500/20' : 'border border-transparent'
      }`}
      data-testid={`phase-row-${phase.key}`}
    >
      <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
        {status === 'done' ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        ) : isActive ? (
          <div className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
        ) : (
          <Circle className="w-3.5 h-3.5 text-zinc-700" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-1 py-0.5 rounded ${
            isActive ? 'bg-cyan-500/15 text-cyan-400' : status === 'done' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-zinc-800 text-zinc-600'
          }`}>{phase.num}</span>
          <span className={`text-xs ${isActive ? 'text-white font-medium' : status === 'done' ? 'text-zinc-300' : 'text-zinc-600'}`}>
            {phase.label}
          </span>
        </div>
        {isActive && currentModel && (
          <div className="text-[10px] text-cyan-400/70 font-mono mt-0.5 truncate pl-6">{currentModel}</div>
        )}
        {isActive && phaseProgress > 0 && (
          <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden mt-1 ml-6">
            <div className="h-full bg-cyan-500/60 rounded-full transition-all duration-700" style={{ width: `${Math.min(100, phaseProgress)}%` }} />
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {(status === 'done' || isActive) && (
          <>
            <span className={`text-[10px] font-mono ${isActive ? 'text-cyan-400' : 'text-zinc-400'}`}>{trained}/{expected}</span>
            {skipped > 0 && (
              <span className="text-[9px] font-mono text-zinc-600" title="Skipped (already trained)">({skipped} cached)</span>
            )}
            {avgAcc > 0 && (
              <span className={`text-[10px] font-mono ${avgAcc > 0.6 ? 'text-emerald-400' : avgAcc > 0.5 ? 'text-amber-400' : 'text-zinc-500'}`}>
                {(avgAcc * 100).toFixed(1)}%
              </span>
            )}
            {status === 'done' && elapsed > 0 && (
              <span className="text-[10px] text-zinc-600 font-mono">{formatDuration(elapsed)}</span>
            )}
          </>
        )}
        {isActive && trained > 0 && (
          <div className="w-12 h-1 bg-white/5 rounded-full overflow-hidden">
            <div className="h-full bg-cyan-500 rounded-full transition-all duration-500" style={{ width: `${Math.min(100, (trained / expected) * 100)}%` }} />
          </div>
        )}
      </div>
    </div>
  );
});

const PhaseTracker = memo(({ pipelineStatus, isTraining }) => {
  const phaseHistory = pipelineStatus?.pipeline_status?.phase_history || {};
  const currentPhase = pipelineStatus?.pipeline_status?.phase;
  const currentModel = pipelineStatus?.pipeline_status?.current_model;
  const startedAt = pipelineStatus?.pipeline_status?.started_at;

  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isTraining || !startedAt) { setElapsed(0); return; }
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed((Date.now() - start) / 1000);
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [isTraining, startedAt]);

  const completedPhases = Object.values(phaseHistory).filter(p => p.status === 'done');
  const totalElapsedPhases = completedPhases.reduce((s, p) => s + (p.elapsed_seconds || 0), 0);
  const completedModelsInPhases = completedPhases.reduce((s, p) => s + (p.models_trained || 0), 0);
  const totalExpectedModels = ALL_PHASES.reduce((s, p) => s + p.expected, 0);
  const modelsCompleted = pipelineStatus?.pipeline_status?.models_completed || completedModelsInPhases;
  const remainingModels = totalExpectedModels - modelsCompleted;

  // ETA calculation with fallback for first model
  let eta = 0;
  let etaSource = '';
  if (modelsCompleted > 0 && remainingModels > 0) {
    // Use actual average time per model
    const avgTimePerModel = elapsed / modelsCompleted;
    eta = avgTimePerModel * remainingModels;
    etaSource = 'measured';
  } else if (elapsed > 60 && remainingModels > 0) {
    // First model still training - estimate based on typical training times
    // Assume first model takes ~8-12 min, use elapsed as baseline for remaining
    const estimatedFirstModelTime = Math.max(elapsed * 1.2, 480); // at least 8 min estimate
    const avgEstimate = estimatedFirstModelTime * 0.8; // subsequent models often faster
    eta = estimatedFirstModelTime - elapsed + (avgEstimate * (remainingModels - 1));
    etaSource = 'estimated';
  }

  if (!isTraining && completedPhases.length === 0) return null;

  return (
    <div className="mb-4 rounded-lg border border-white/5 bg-white/[0.02] overflow-hidden" data-testid="phase-tracker">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/[0.01]">
        <div className="flex items-center gap-2">
          {isTraining ? <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" /> : <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          <span className="text-sm font-medium text-white">{isTraining ? 'Training in progress' : 'Training complete'}</span>
        </div>
        <div className="flex items-center gap-4">
          {elapsed > 0 && (
            <div className="flex items-center gap-1.5">
              <Clock className="w-3 h-3 text-zinc-500" />
              <span className="text-xs font-mono text-zinc-300">{formatDuration(elapsed)}</span>
            </div>
          )}
          {isTraining && eta > 0 && (
            <div className="flex items-center gap-1.5" title={etaSource === 'estimated' ? 'Rough estimate until first model completes' : 'Based on actual training speed'}>
              <span className="text-[10px] text-zinc-500 uppercase">ETA</span>
              <span className={`text-xs font-mono ${etaSource === 'estimated' ? 'text-amber-400/70' : 'text-amber-400'}`}>
                ~{formatDuration(eta)}
                {etaSource === 'estimated' && <span className="text-[9px] text-zinc-600 ml-1">*</span>}
              </span>
            </div>
          )}
          {isTraining && modelsCompleted > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-zinc-500">AVG</span>
              <span className="text-xs font-mono text-cyan-400">{formatDuration(elapsed / modelsCompleted)}/model</span>
            </div>
          )}
          {isTraining && eta > 3600 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-zinc-500">DONE</span>
              <span className="text-xs font-mono text-emerald-400/80">
                ~{new Date(Date.now() + eta * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="px-4 py-2 border-b border-white/5">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-zinc-500">Overall Progress</span>
          <span className="text-[10px] font-mono text-zinc-400">
            {pipelineStatus?.pipeline_status?.models_completed || 0} / {pipelineStatus?.pipeline_status?.models_total || totalExpectedModels} models
          </span>
        </div>
        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-cyan-500 to-emerald-500 rounded-full transition-all duration-700"
            style={{ width: `${Math.min(100, ((pipelineStatus?.pipeline_status?.models_completed || 0) / (pipelineStatus?.pipeline_status?.models_total || totalExpectedModels)) * 100)}%` }}
          />
        </div>
      </div>
      <div className="px-1 py-1 space-y-0.5 max-h-[340px] overflow-auto">
        {ALL_PHASES.map((phase) => (
          <PhaseRow
            key={phase.key}
            phase={phase}
            phaseData={phaseHistory[phase.key]}
            isActive={isTraining && currentPhase === phase.key}
            currentModel={currentPhase === phase.key ? currentModel : null}
            phaseProgress={currentPhase === phase.key ? (pipelineStatus?.pipeline_status?.current_phase_progress || 0) : 0}
          />
        ))}
      </div>
      {!isTraining && completedPhases.length > 0 && (
        <div className="px-4 py-2.5 border-t border-white/5 bg-emerald-500/[0.03]">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-sm font-bold text-emerald-400">{completedModelsInPhases}</div>
              <div className="text-[10px] text-zinc-500">Trained</div>
            </div>
            <div>
              <div className="text-sm font-bold text-red-400">{completedPhases.reduce((s, p) => s + (p.models_failed || 0), 0)}</div>
              <div className="text-[10px] text-zinc-500">Failed</div>
            </div>
            <div>
              <div className="text-sm font-bold text-zinc-300">{formatDuration(totalElapsedPhases)}</div>
              <div className="text-[10px] text-zinc-500">Total Time</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

const MetricBar = memo(({ value, max = 1, color = 'bg-cyan-500' }) => {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 bg-white/5 rounded-full overflow-hidden w-full" data-testid="metric-bar">
      <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
});

const CategoryRow = memo(({ categoryKey, category }) => {
  const [expanded, setExpanded] = useState(false);
  const Icon = CATEGORY_ICONS[categoryKey] || Brain;
  const color = CATEGORY_COLORS[categoryKey] || 'text-zinc-400';
  const models = category.models || [];
  const trainedCount = models.filter(m => m.trained).length;
  const totalCount = models.length;
  const trainedModels = models.filter(m => m.accuracy);
  const avgAccuracy = trainedModels.length > 0 ? trainedModels.reduce((sum, m) => sum + m.accuracy, 0) / trainedModels.length : 0;
  const validation = category.validation;

  return (
    <div className="border border-white/5 rounded-lg overflow-hidden" data-testid={`category-${categoryKey}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-2.5 hover:bg-white/[0.02] transition-colors"
        data-testid={`category-toggle-${categoryKey}`}
      >
        <div className="flex items-center gap-2">
          <Icon className={`w-3.5 h-3.5 ${color}`} />
          <span className="text-xs font-medium text-white">{category.label}</span>
          {validation && validation.total_validated > 0 && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
              validation.promoted === validation.total_validated ? 'bg-emerald-500/15 text-emerald-400' :
              validation.promoted > 0 ? 'bg-amber-500/15 text-amber-400' : 'bg-red-500/15 text-red-400'
            }`} data-testid={`validation-badge-${categoryKey}`}>
              {validation.promoted}/{validation.total_validated} validated
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="w-20 h-1 bg-white/5 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${trainedCount === totalCount && totalCount > 0 ? 'bg-emerald-500' : trainedCount > 0 ? 'bg-cyan-500' : 'bg-zinc-700'}`} style={{ width: `${totalCount > 0 ? (trainedCount / totalCount) * 100 : 0}%` }} />
          </div>
          <span className={`text-[10px] font-mono w-10 text-right ${trainedCount === totalCount && totalCount > 0 ? 'text-emerald-400' : trainedCount > 0 ? 'text-zinc-300' : 'text-zinc-600'}`}>
            {trainedCount}/{totalCount}
          </span>
          {avgAccuracy > 0 && (
            <span className={`text-[10px] font-mono w-12 text-right ${avgAccuracy > 0.6 ? 'text-emerald-400' : avgAccuracy > 0.5 ? 'text-amber-400' : 'text-zinc-500'}`}>
              {(avgAccuracy * 100).toFixed(1)}%
            </span>
          )}
          {expanded ? <ChevronDown className="w-3 h-3 text-zinc-500" /> : <ChevronRight className="w-3 h-3 text-zinc-500" />}
        </div>
      </button>
      {expanded && (
        <div className="border-t border-white/5 p-2 space-y-0.5 max-h-60 overflow-auto">
          <p className="text-[10px] text-zinc-500 px-2 mb-1">{category.description}</p>
          {models.map((m) => {
            const valStatus = validation?.per_setup?.[m.setup_type || m.name];
            return (
              <div key={m.name} className="flex items-center justify-between px-2 py-1 rounded hover:bg-white/[0.02]" data-testid={`model-row-${m.name}`}>
                <div className="flex items-center gap-1.5">
                  {m.trained ? <CheckCircle2 className="w-3 h-3 text-emerald-400" /> : <Circle className="w-3 h-3 text-zinc-700" />}
                  <span className="text-[10px] text-zinc-300 font-mono">{m.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  {m.accuracy > 0 && (
                    <span className={`text-[10px] font-mono ${m.accuracy > 0.6 ? 'text-emerald-400' : m.accuracy > 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                      {(m.accuracy * 100).toFixed(1)}%
                    </span>
                  )}
                  {m.training_samples > 0 && (
                    <span className="text-[9px] text-zinc-600">{m.training_samples.toLocaleString()}</span>
                  )}
                  {valStatus && (
                    <span className={`text-[9px] font-mono px-1 py-0.5 rounded ${
                      valStatus.status === 'promoted' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                    }`}>{valStatus.phases_passed}/3</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

const TrainingReadinessCard = memo(({ readiness, preflight, onRunPreflight, onTestMode, runningPreflight, starting, isTraining }) => {
  const barSizes = readiness?.by_bar_size || [];
  const readyCount = readiness?.bar_sizes_ready ?? 0;
  const totalCount = readiness?.bar_sizes_total ?? barSizes.length;
  const dataOK = readiness?.all_bar_sizes_ready;
  const dataAnyOK = readyCount > 0;

  const preflightOK = preflight?.ok === true;
  const preflightFailed = preflight && preflight.ok === false;
  const preflightChecked = Array.isArray(preflight?.checked_phases) ? preflight.checked_phases.length : 0;

  // Overall readiness: data present + preflight passed (or not yet run)
  const overallReady = dataAnyOK && (preflightOK || !preflight);
  const blocked = preflightFailed;

  return (
    <div
      className="mb-4 p-3 rounded-lg border border-white/5 bg-gradient-to-br from-zinc-900/60 to-black/40"
      data-testid="training-readiness-card"
    >
      <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-semibold text-white uppercase tracking-wider">Training Readiness</span>
          {blocked ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/20" data-testid="readiness-verdict">Blocked</span>
          ) : overallReady ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20" data-testid="readiness-verdict">Ready</span>
          ) : dataAnyOK ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20" data-testid="readiness-verdict">Partial</span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-500/15 text-zinc-400 border border-zinc-500/20" data-testid="readiness-verdict">Awaiting data</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onRunPreflight}
            disabled={runningPreflight}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] text-zinc-300 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="run-preflight-btn"
            data-help-id="preflight"
            title="Synthetic-bar shape validator (~2s). Catches feature-list drift before launching a multi-hour run."
          >
            {runningPreflight ? <Loader2Spinner /> : <CheckCircle2 className="w-3 h-3" />}
            Pre-flight
          </button>
          <button
            onClick={onTestMode}
            disabled={starting || isTraining || blocked}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/30 text-[11px] text-violet-300 hover:text-violet-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="test-mode-start-btn"
            data-help-id="test-mode"
            title="Run a small-universe quick training to validate the pipeline end-to-end before the full overnight run."
          >
            <Zap className="w-3 h-3" />
            Test mode
          </button>
        </div>
      </div>

      {/* Data sufficiency grid */}
      <div className="grid grid-cols-7 gap-1 mb-2" data-testid="readiness-bar-grid">
        {barSizes.length > 0 ? barSizes.map((bs) => (
          <div
            key={bs.bar_size}
            className={`flex flex-col items-center justify-center px-1 py-1.5 rounded border ${
              bs.ready
                ? 'border-emerald-500/20 bg-emerald-500/[0.04]'
                : 'border-zinc-700/40 bg-white/[0.01]'
            }`}
            title={`${bs.bar_size} — ${bs.symbol_count} symbols (target ${bs.target_symbols}, min ${bs.min_bars_per_symbol} bars each)`}
            data-testid={`readiness-bar-${bs.bar_size.replace(/\s+/g, '-')}`}
          >
            <span className={`text-[9px] font-mono ${bs.ready ? 'text-emerald-400' : 'text-zinc-500'}`}>
              {bs.bar_size}
            </span>
            <span className={`text-[11px] font-mono font-semibold ${bs.ready ? 'text-emerald-300' : 'text-zinc-600'}`}>
              {bs.symbol_count}
            </span>
          </div>
        )) : (
          <div className="col-span-7 text-center py-2 text-[11px] text-zinc-500">Loading readiness…</div>
        )}
      </div>

      {/* Status line + preflight detail */}
      <div className="flex items-center justify-between text-[11px] flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="text-zinc-400">
            Data: <span className={dataOK ? 'text-emerald-400' : dataAnyOK ? 'text-amber-400' : 'text-zinc-500'}>{readyCount}/{totalCount}</span> bar sizes
          </span>
          <span className="text-zinc-700">·</span>
          <span className="text-zinc-400">
            Pre-flight:{' '}
            {!preflight ? (
              <span className="text-zinc-500">not run</span>
            ) : preflightOK ? (
              <span className="text-emerald-400">✓ {preflightChecked} phases clean ({preflight.duration_s}s)</span>
            ) : (
              <span className="text-red-400">✗ {preflight.failures?.length || 0} mismatches</span>
            )}
          </span>
        </div>
        {readiness?.recommendation && (
          <span className="text-[10px] text-zinc-500 italic">{readiness.recommendation}</span>
        )}
      </div>

      {/* Failure details when pre-flight fails */}
      {preflightFailed && preflight.failures?.length > 0 && (
        <div className="mt-2 p-2 rounded border border-red-500/20 bg-red-500/[0.04]" data-testid="preflight-failure-details">
          <div className="text-[10px] font-semibold text-red-400 uppercase mb-1">Shape mismatches — fix before training:</div>
          <ul className="space-y-0.5 max-h-24 overflow-auto">
            {preflight.failures.slice(0, 6).map((f, i) => (
              <li key={i} className="text-[10px] text-red-300 font-mono">
                • {f.phase || f.worker || 'phase'}: expected {f.expected_cols ?? f.expected}, got {f.actual_cols ?? f.actual}
                {f.note ? ` — ${f.note}` : ''}
              </li>
            ))}
            {preflight.failures.length > 6 && (
              <li className="text-[10px] text-red-500/70 italic">… and {preflight.failures.length - 6} more</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
});
TrainingReadinessCard.displayName = 'TrainingReadinessCard';

// Tiny inline spinner that avoids pulling another icon into the bundle
const Loader2Spinner = () => (
  <div className="w-3 h-3 rounded-full border-[1.5px] border-zinc-500 border-t-transparent animate-spin" />
);

const TrainingPipelinePanel = memo(({ onRefresh, wsTrainingStatus }) => {
  const [inventory, setInventory] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [cnnModels, setCnnModels] = useState([]);
  const [gpuInfo, setGpuInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [dataReadiness, setDataReadiness] = useState(null);
  const [preflight, setPreflight] = useState(null);
  const [runningPreflight, setRunningPreflight] = useState(false);
  const optimisticUntilRef = useRef(0); // timestamp until which we ignore "idle" WS updates

  // Pre-train safety interlock (2026-04-24): the pipeline's Start Training
  // button now polls /api/backfill/readiness. Blocks training launch when
  // critical symbols are stale, the historical queue is still draining, or
  // duplicate bars have been detected. Shift+click to override.
  const trainReadiness = useTrainReadiness();

  useEffect(() => {
    console.log('[TrainingPanel] wsTrainingStatus changed:', wsTrainingStatus);
    if (wsTrainingStatus) {
      const phase = wsTrainingStatus.phase || 'idle';
      const isActive = phase !== 'idle' && phase !== 'completed' && phase !== 'cancelled' && phase !== 'error';
      // If we recently did an optimistic start, ignore stale "idle" broadcasts
      // that arrive before the subprocess has written to MongoDB
      if (!isActive && Date.now() < optimisticUntilRef.current) {
        console.log('[TrainingPanel] Ignoring stale idle broadcast (optimistic grace period)');
        return;
      }
      console.log('[TrainingPanel] Setting pipeline status, phase:', phase, 'isActive:', isActive);
      setPipelineStatus(prev => ({
        ...prev,
        task_status: isActive ? 'running' : (phase === 'completed' ? 'completed' : 'idle'),
        pipeline_status: wsTrainingStatus,
      }));
    }
  }, [wsTrainingStatus]);

  const fetchData = useCallback(async () => {
    try {
      const [inventoryRes, statusRes, cnnRes, gpuRes, readinessRes] = await Promise.allSettled([
        api.get('/api/ai-training/model-inventory'),
        api.get('/api/ai-training/status'),
        api.get('/api/ai-training/cnn/models'),
        api.get('/api/ai-training/gpu-status'),
        api.get('/api/ai-training/data-readiness'),
      ]);
      
      // Debug logging
      console.log('[TrainingPanel] inventoryRes:', inventoryRes);
      
      if (inventoryRes.status === 'fulfilled' && inventoryRes.value.data?.success) {
        console.log('[TrainingPanel] Setting inventory:', inventoryRes.value.data);
        setInventory(inventoryRes.value.data);
      } else {
        console.warn('[TrainingPanel] Inventory fetch failed or returned unsuccessful:', inventoryRes);
      }
      if (statusRes.status === 'fulfilled' && statusRes.value.data?.success) {
        // Don't overwrite optimistic "running" state with a stale HTTP response
        if (Date.now() < optimisticUntilRef.current && statusRes.value.data?.task_status !== 'running') {
          console.log('[TrainingPanel] Ignoring stale HTTP status (optimistic grace period)');
        } else {
          setPipelineStatus(statusRes.value.data);
        }
      }
      if (cnnRes.status === 'fulfilled' && cnnRes.value.data?.success) setCnnModels(cnnRes.value.data.models || []);
      if (gpuRes.status === 'fulfilled' && gpuRes.value.data?.success) setGpuInfo(gpuRes.value.data.gpu);
      if (readinessRes.status === 'fulfilled' && readinessRes.value.data?.success) setDataReadiness(readinessRes.value.data);
    } catch (err) {
      console.error('Training panel fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const isTraining = pipelineStatus?.task_status === 'running';

  useEffect(() => {
    if (!isTraining) return;
    // During training, rely on WebSocket for status updates (wsTrainingStatus).
    // HTTP polling is just a fallback — extended to 120s to save backend CPU.
    const interval = setInterval(fetchData, 120000);
    return () => clearInterval(interval);
  }, [isTraining, fetchData]);

  // WebSocket-based training control — bypasses the browser's 6-connection
  // HTTP limit entirely. No new connections needed.
  const { sendWsMessage } = useConnectionManager();
  const startCallbackRef = useRef(null);
  const stopCallbackRef = useRef(null);

  // Listen for WebSocket responses to training commands
  useEffect(() => {
    const handleWsMessage = (event) => {
      const msg = event.detail;
      // Debug: log all WS messages that come through
      if (msg?.type?.includes('pipeline')) {
        console.log('[TrainingPanel] Received WS message:', msg);
      }
      if (msg?.type === 'pipeline_start_result') {
        console.log('[TrainingPanel] Processing pipeline_start_result:', msg);
        setStarting(false);
        if (msg.success) {
          toast.success('Training pipeline started');
          // Optimistic UI update — flip to "running" immediately so button shows "Stop Training"
          // Set grace period to ignore stale "idle" broadcasts for 15 seconds
          optimisticUntilRef.current = Date.now() + 15000;
          setPipelineStatus(prev => ({
            ...prev,
            task_status: 'running',
            pipeline_status: { ...(prev?.pipeline_status || {}), phase: 'starting' },
          }));
        } else {
          toast.error(msg.error || 'Failed to start training');
        }
        if (startCallbackRef.current) {
          clearTimeout(startCallbackRef.current);
          startCallbackRef.current = null;
        }
      } else if (msg?.type === 'pipeline_stop_result') {
        if (msg.success) {
          toast.success(msg.message || 'Training stopped');
          // Optimistic UI update — flip back to idle immediately
          setPipelineStatus(prev => ({
            ...prev,
            task_status: 'idle',
            pipeline_status: { ...(prev?.pipeline_status || {}), phase: 'cancelled' },
          }));
        } else {
          toast.error(msg.error || 'Failed to stop training');
        }
        if (stopCallbackRef.current) {
          clearTimeout(stopCallbackRef.current);
          stopCallbackRef.current = null;
        }
      }
    };
    window.addEventListener('ws-message', handleWsMessage);
    return () => window.removeEventListener('ws-message', handleWsMessage);
  }, []);

  const handleStartTraining = useCallback(async (event) => {
    // Pre-train interlock — block if backfill not green (unless shift+click override).
    if (!trainReadiness.ready && !isOverrideClick(event)) {
      const reason = trainReadiness.blockers[0]
        || trainReadiness.readiness?.summary
        || 'backfill not ready';
      toast.error(`Training start blocked — ${reason}`);
      toast.info('Shift+click Start Training to override the readiness gate.');
      return;
    }
    if (!trainReadiness.ready && isOverrideClick(event)) {
      toast.warning('Override: starting pipeline on a non-green dataset.');
    }
    setStarting(true);
    const sent = sendWsMessage({ action: 'start_pipeline' });
    if (!sent) {
      setStarting(false);
      toast.error('WebSocket not connected — cannot start training');
      return;
    }
    // Quick WS response timeout — if no WS ack in 5s, poll REST as fallback
    startCallbackRef.current = setTimeout(async () => {
      try {
        const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
        const res = await fetch(`${backendUrl}/api/ai-training/status`);
        const status = await res.json();
        const phase = status?.pipeline_status?.phase || status?.phase;
        if (phase && phase !== 'idle' && phase !== 'completed' && phase !== 'error') {
          // Training IS running — WS just missed the ack
          toast.success('Training pipeline started');
          optimisticUntilRef.current = Date.now() + 15000;
          setPipelineStatus(prev => ({
            ...prev,
            task_status: 'running',
            pipeline_status: status?.pipeline_status || { phase: 'starting' },
          }));
        } else {
          toast.error('Training start timed out — check backend terminal');
        }
      } catch {
        toast.error('Training start timed out — check backend terminal');
      }
      setStarting(false);
      startCallbackRef.current = null;
    }, 5000);
  }, [sendWsMessage, trainReadiness]);

  const handleStopTraining = useCallback(() => {
    const sent = sendWsMessage({ action: 'stop_pipeline' });
    if (!sent) {
      toast.error('WebSocket not connected — cannot stop training');
      return;
    }
    stopCallbackRef.current = setTimeout(() => {
      toast.error('Training stop timed out');
    }, 15000);
  }, [sendWsMessage]);

  // Run the pre-flight shape validator on demand. This is the <5s synthetic-bar
  // check that catches the feature/name-list drift bug that killed the
  // 2026-04-21 run 12 minutes into Phase 1. Runs entirely on synthetic bars
  // so it has zero DB dependency (safe to call during heavy data collection).
  const handleRunPreflight = useCallback(async () => {
    setRunningPreflight(true);
    try {
      const res = await api.get('/api/ai-training/preflight');
      if (res.data?.success) {
        setPreflight(res.data);
        if (res.data.ok) {
          toast.success(`Pre-flight PASSED (${res.data.duration_s}s, ${res.data.checked_phases?.length || 0} phases)`);
        } else {
          toast.error(`Pre-flight FAILED — ${res.data.failures?.length || 0} shape mismatches. Fix before training.`);
        }
      } else {
        toast.error('Pre-flight errored: ' + (res.data?.error || 'unknown'));
      }
    } catch (err) {
      toast.error('Pre-flight request failed: ' + (err?.response?.data?.detail || err.message));
    } finally {
      setRunningPreflight(false);
    }
  }, []);

  // Test-mode training: cap to tiny universe and short-circuit expensive phases,
  // validating the pipeline end-to-end against the current data before committing
  // to the full overnight run. Uses the same /start endpoint with test_mode=true.
  const handleTestModeStart = useCallback(async () => {
    if (!window.confirm('Run a quick test-mode training (small universe, ~minutes)? This validates the pipeline end-to-end before the full run.')) return;
    setStarting(true);
    try {
      const res = await api.post('/api/ai-training/start', {
        test_mode: true,
        force_retrain: false,
      }, { timeout: 30000 });
      if (res.data?.success) {
        toast.success('Test-mode training started');
        optimisticUntilRef.current = Date.now() + 15000;
        setPipelineStatus(prev => ({
          ...prev,
          task_status: 'running',
          pipeline_status: { ...(prev?.pipeline_status || {}), phase: 'starting' },
        }));
      } else if (res.data?.status === 'preflight_failed') {
        setPreflight({ success: true, ok: false, failures: res.data.preflight?.failures || [], checked_phases: res.data.preflight?.checked_phases || [] });
        toast.error('Pre-flight FAILED — see the readiness card for details');
      } else {
        toast.error(res.data?.error || 'Test-mode start failed');
      }
    } catch (err) {
      toast.error('Test-mode start errored: ' + (err?.response?.data?.detail || err.message));
    } finally {
      setStarting(false);
    }
  }, []);

  // Split categories into Trade Signal Generators vs Support Models
  const signalCategories = [];
  const supportCategories = [];
  if (inventory?.categories) {
    Object.entries(inventory.categories).forEach(([key, cat]) => {
      if (cat.group === 'signal') signalCategories.push([key, cat]);
      else supportCategories.push([key, cat]);
    });
  }

  const totalModels = (inventory?.total_defined || 0) + 20; // +20 CNN (loaded separately)
  const totalTrained = (inventory?.total_trained || 0) + cnnModels.length;

  return (
    <div className="mt-6" data-testid="training-pipeline-panel" data-help-id="training-pipeline-phases">
      {/* Section Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-cyan-400" />
          <h2 className="text-base font-semibold text-white">AI Training Pipeline</h2>
          <span className="text-[10px] text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded font-mono">{totalTrained}/{totalModels} trained</span>
        </div>
        <div className="flex items-center gap-2">
          {isTraining ? (
            <button onClick={handleStopTraining} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-xs text-red-400 transition-colors" data-testid="stop-training-btn">
              <Square className="w-3 h-3" /> Stop Training
            </button>
          ) : (
            <button
              onClick={handleStartTraining}
              disabled={starting}
              title={
                trainReadiness.ready
                  ? 'Launch the AI training pipeline.'
                  : `Training blocked — ${(trainReadiness.blockers[0] || trainReadiness.readiness?.summary || 'backfill not ready')}\n\nShift+click to override.`
              }
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-colors ${
                trainReadiness.ready
                  ? 'bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/30 text-emerald-400'
                  : 'bg-zinc-800/60 hover:bg-zinc-800 border-zinc-700 text-zinc-500 cursor-help'
              }`}
              data-testid="start-training-btn"
              data-help-id="pre-train-interlock"
              data-train-readiness={trainReadiness.verdict}
            >
              <Play className="w-3 h-3" /> {starting ? 'Starting...' : 'Start Training'}
              {!trainReadiness.ready && !starting && (
                <span
                  className={`w-1.5 h-1.5 rounded-full ml-0.5 ${trainReadiness.verdict === 'yellow' ? 'bg-amber-400' : 'bg-rose-400 animate-pulse'}`}
                />
              )}
            </button>
          )}
          <button onClick={fetchData} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-400 transition-colors" data-testid="refresh-training-btn">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Phase-by-Phase Progress Tracker */}
      {(isTraining || pipelineStatus?.pipeline_status?.phase_history) && (
        <PhaseTracker pipelineStatus={pipelineStatus} isTraining={isTraining} />
      )}

      {/* Training Readiness — data sufficiency + pre-flight verdict + test-mode shortcut */}
      <TrainingReadinessCard
        readiness={dataReadiness}
        preflight={preflight}
        onRunPreflight={handleRunPreflight}
        onTestMode={handleTestModeStart}
        runningPreflight={runningPreflight}
        starting={starting}
        isTraining={isTraining}
      />

      {/* GPU + Overall Progress */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {gpuInfo && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-white/5 bg-white/[0.02]" data-testid="gpu-status-bar">
            <div className="w-5 h-5 rounded-md bg-fuchsia-500/15 flex items-center justify-center flex-shrink-0">
              {gpuInfo.cuda ? <Monitor className="w-3 h-3 text-fuchsia-400" /> : <Cpu className="w-3 h-3 text-zinc-500" />}
            </div>
            <span className="text-xs text-white truncate">{gpuInfo.cuda ? gpuInfo.gpu : 'CPU'}</span>
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono ${gpuInfo.cuda ? 'bg-emerald-500/15 text-emerald-400' : 'bg-zinc-500/15 text-zinc-500'}`}>
              {gpuInfo.cuda ? 'CUDA' : 'NO GPU'}
            </span>
            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-cyan-500/15 text-cyan-400" data-testid="engine-label">
              XGBoost
            </span>
          </div>
        )}
        {inventory && (
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-white/5 bg-white/[0.02] flex-1" data-testid="model-summary">
            <span className="text-xs text-zinc-400">Models</span>
            <span className="text-sm font-mono text-white">{totalTrained} / {totalModels}</span>
            <div className="flex-1 max-w-xs">
              <MetricBar value={totalTrained} max={totalModels} color="bg-emerald-500" />
            </div>
            {totalTrained === 0 && <span className="text-xs text-amber-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Untrained</span>}
          </div>
        )}
      </div>

      {/* Model Inventory */}
      <div className="space-y-4">
          {/* Trade Signal Generators */}
          <div data-testid="signal-generators-group">
            <div className="flex items-center gap-2 mb-2">
              <Crosshair className="w-3.5 h-3.5 text-violet-400" />
              <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">Trade Signal Generators</span>
              <span className="text-[10px] text-zinc-600">Directly produce trade decisions</span>
            </div>
            <div className="space-y-1.5">
              {signalCategories.map(([key, cat]) => (
                <CategoryRow key={key} categoryKey={key} category={cat} />
              ))}
              {/* CNN as signal-adjacent (visual confirmation) */}
              <div className="border border-white/5 rounded-lg overflow-hidden" data-testid="cnn-category-row">
                <div className="flex items-center justify-between p-2.5">
                  <div className="flex items-center gap-2">
                    <Eye className="w-3.5 h-3.5 text-fuchsia-400" />
                    <span className="text-xs font-medium text-white">CNN Visual Patterns</span>
                    <span className="text-[10px] text-zinc-600">ResNet-18</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-20 h-1 bg-white/5 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${cnnModels.length > 0 ? 'bg-fuchsia-500' : 'bg-zinc-700'}`} style={{ width: `${Math.min((cnnModels.length / 34) * 100, 100)}%` }} />
                    </div>
                    <span className={`text-[10px] font-mono w-10 text-right ${cnnModels.length > 0 ? 'text-fuchsia-400' : 'text-zinc-600'}`}>{cnnModels.length}/34</span>
                    {cnnModels.length > 0 && (
                      <span className="text-[10px] font-mono text-zinc-500 w-12 text-right">
                        {(cnnModels.reduce((s, m) => s + (m.metrics?.win_auc || m.win_auc || 0), 0) / cnnModels.length * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Support Models */}
          <div data-testid="support-models-group">
            <div className="flex items-center gap-2 mb-2">
              <Wrench className="w-3.5 h-3.5 text-zinc-500" />
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Support Models</span>
              <span className="text-[10px] text-zinc-600">Context, sizing, risk & regime inputs</span>
            </div>
            <div className="space-y-1.5">
              {supportCategories.map(([key, cat]) => (
                <CategoryRow key={key} categoryKey={key} category={cat} />
              ))}
            </div>
          </div>

          {/* Last Training Results (when not in phase tracker mode) */}
          {pipelineStatus?.last_result && !pipelineStatus?.pipeline_status?.phase_history && (
            <div className="p-3 rounded-lg border border-white/5 bg-white/[0.02]" data-testid="training-results">
              <h4 className="text-xs text-zinc-400 uppercase tracking-wider mb-2">Last Training Run</h4>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-lg font-bold text-emerald-400">{pipelineStatus.last_result.summary?.models_trained || 0}</div>
                  <div className="text-xs text-zinc-500">Trained</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-red-400">{pipelineStatus.last_result.summary?.models_failed || 0}</div>
                  <div className="text-xs text-zinc-500">Failed</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-cyan-400">{(pipelineStatus.last_result.summary?.total_samples || 0).toLocaleString()}</div>
                  <div className="text-xs text-zinc-500">Samples</div>
                </div>
              </div>
            </div>
          )}
      </div>
    </div>
  );
});

export default TrainingPipelinePanel;
