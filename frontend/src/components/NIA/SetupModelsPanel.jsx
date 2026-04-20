import React, { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Crosshair, TrendingUp, Zap, BarChart3, Target,
  ArrowUpDown, GitBranch, Clock, Gauge, Activity,
  ChevronDown, PlayCircle, Loader2, CheckCircle2,
  XCircle, RefreshCw, Layers, Timer, Shield, ShieldCheck,
  ShieldAlert, ShieldX, FlaskConical, Shuffle, LineChart,
  Globe, BarChart2, ChevronRight, AlertTriangle, Info
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../../utils/api';
import { useTrainCommand } from '../../contexts';

const SETUP_CONFIG = {
  MOMENTUM:           { icon: TrendingUp, color: 'text-cyan-400',   bg: 'bg-cyan-500/15',   border: 'border-cyan-500/25' },
  SCALP:              { icon: Zap,        color: 'text-amber-400',  bg: 'bg-amber-500/15',  border: 'border-amber-500/25' },
  BREAKOUT:           { icon: Crosshair,  color: 'text-green-400',  bg: 'bg-green-500/15',  border: 'border-green-500/25' },
  GAP_AND_GO:         { icon: Activity,   color: 'text-orange-400', bg: 'bg-orange-500/15', border: 'border-orange-500/25' },
  RANGE:              { icon: ArrowUpDown, color: 'text-violet-400', bg: 'bg-violet-500/15', border: 'border-violet-500/25' },
  REVERSAL:           { icon: GitBranch,  color: 'text-rose-400',   bg: 'bg-rose-500/15',   border: 'border-rose-500/25' },
  TREND_CONTINUATION: { icon: BarChart3,  color: 'text-teal-400',   bg: 'bg-teal-500/15',   border: 'border-teal-500/25' },
  ORB:                { icon: Clock,      color: 'text-yellow-400', bg: 'bg-yellow-500/15', border: 'border-yellow-500/25' },
  VWAP:               { icon: Gauge,      color: 'text-indigo-400', bg: 'bg-indigo-500/15', border: 'border-indigo-500/25' },
  MEAN_REVERSION:     { icon: Target,     color: 'text-pink-400',   bg: 'bg-pink-500/15',   border: 'border-pink-500/25' },
};

const BAR_SIZE_LABELS = {
  '1 min': '1m', '5 mins': '5m', '1 hour': '1h', '1 day': '1D',
};

// ─── Risk badge colors ────────────────────
const RISK_COLORS = {
  LOW: 'text-green-400 bg-green-500/15',
  MEDIUM: 'text-yellow-400 bg-yellow-500/15',
  HIGH: 'text-orange-400 bg-orange-500/15',
  EXTREME: 'text-red-400 bg-red-500/15',
  UNKNOWN: 'text-zinc-400 bg-zinc-500/15',
};

// ─── Small stat component ─────────────────
const Stat = ({ label, value, color = 'text-zinc-300' }) => (
  <div className="flex justify-between text-[9px]">
    <span className="text-zinc-500">{label}</span>
    <span className={`font-mono ${color}`}>{value}</span>
  </div>
);

// ─── Validation Phase Badge ───────────────
const PhaseBadge = ({ phase, label, icon: Icon, status }) => {
  const ok = status === 'pass';
  const fail = status === 'fail';
  const skip = status === 'skip';
  return (
    <div
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium border ${
        ok ? 'text-green-400 bg-green-500/10 border-green-500/20'
        : fail ? 'text-red-400 bg-red-500/10 border-red-500/20'
        : skip ? 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20'
        : 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20'
      }`}
      title={label}
      data-testid={`phase-badge-${phase}`}
    >
      <Icon className="w-2.5 h-2.5" />
      <span>{phase}</span>
    </div>
  );
};

// ─── Validation Summary Row (inside profile detail) ──────────
const ValidationSummary = memo(({ validation }) => {
  if (!validation) return null;
  const v = validation;
  const ai = v.ai_comparison || {};
  const mc = v.monte_carlo || {};
  const wf = v.walk_forward || {};

  const statusColor = v.status === 'promoted'
    ? 'text-green-400 bg-green-500/10 border-green-500/20'
    : v.status === 'rejected'
    ? 'text-red-400 bg-red-500/10 border-red-500/20'
    : 'text-zinc-400 bg-zinc-500/10 border-zinc-500/20';

  // Phase statuses
  const aiStatus = ai.error ? 'fail' : (ai.ai_filtered_trades > 0 ? 'pass' : 'skip');
  const mcStatus = mc.error ? 'fail' : mc.skipped ? 'skip' : (mc.risk_assessment !== 'EXTREME' ? 'pass' : 'fail');
  const wfStatus = wf.error ? 'fail' : wf.skipped ? 'skip' : ((wf.avg_efficiency_ratio || 0) >= 50 ? 'pass' : 'fail');

  return (
    <div className="mt-1.5 p-2 rounded bg-black/30 border border-white/5 space-y-1.5" data-testid={`validation-summary-${v.setup_type}-${v.bar_size}`}>
      {/* Status + phases */}
      <div className="flex items-center justify-between">
        <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${statusColor}`}>
          {v.status?.toUpperCase()} ({v.phases_passed || 0}/{v.phases_total || 3})
        </span>
        <div className="flex gap-1">
          <PhaseBadge phase="AI" label="AI Comparison" icon={FlaskConical} status={aiStatus} />
          <PhaseBadge phase="MC" label="Monte Carlo" icon={Shuffle} status={mcStatus} />
          <PhaseBadge phase="WF" label="Walk-Forward" icon={LineChart} status={wfStatus} />
        </div>
      </div>

      {/* Quick metrics row */}
      <div className="grid grid-cols-3 gap-1">
        {/* AI Comparison */}
        <div className="space-y-0.5">
          <div className="text-[8px] text-zinc-500 uppercase tracking-wider">AI Edge</div>
          {ai.error ? (
            <div className="text-[9px] text-red-400">Error</div>
          ) : (
            <>
              <Stat label="WR" value={`${ai.ai_edge_win_rate > 0 ? '+' : ''}${(ai.ai_edge_win_rate || 0).toFixed(1)}%`}
                color={ai.ai_edge_win_rate > 0 ? 'text-green-400' : ai.ai_edge_win_rate < -3 ? 'text-red-400' : 'text-zinc-400'} />
              <Stat label="Sharpe" value={`${ai.ai_edge_sharpe > 0 ? '+' : ''}${(ai.ai_edge_sharpe || 0).toFixed(2)}`}
                color={ai.ai_edge_sharpe > 0 ? 'text-green-400' : 'text-zinc-400'} />
              <Stat label="Trades" value={`${ai.ai_filtered_trades || 0}`} />
            </>
          )}
        </div>

        {/* Monte Carlo */}
        <div className="space-y-0.5">
          <div className="text-[8px] text-zinc-500 uppercase tracking-wider">Risk</div>
          {mc.error ? (
            <div className="text-[9px] text-red-400">Error</div>
          ) : mc.skipped ? (
            <div className="text-[9px] text-zinc-500">Skipped</div>
          ) : (
            <>
              <Stat label="P(profit)" value={`${(mc.probability_of_profit || 0).toFixed(0)}%`}
                color={mc.probability_of_profit > 60 ? 'text-green-400' : 'text-yellow-400'} />
              <Stat label="Risk" value={mc.risk_assessment || '?'}
                color={RISK_COLORS[mc.risk_assessment]?.split(' ')[0] || 'text-zinc-400'} />
              <Stat label="Max DD" value={`${(mc.worst_case_drawdown || 0).toFixed(1)}%`}
                color={mc.worst_case_drawdown < 20 ? 'text-green-400' : mc.worst_case_drawdown < 35 ? 'text-yellow-400' : 'text-red-400'} />
            </>
          )}
        </div>

        {/* Walk-Forward */}
        <div className="space-y-0.5">
          <div className="text-[8px] text-zinc-500 uppercase tracking-wider">Robust</div>
          {wf.error ? (
            <div className="text-[9px] text-red-400">Error</div>
          ) : wf.skipped ? (
            <div className="text-[9px] text-zinc-500">Skipped</div>
          ) : (
            <>
              <Stat label="Efficiency" value={`${(wf.avg_efficiency_ratio || 0).toFixed(0)}%`}
                color={wf.avg_efficiency_ratio >= 70 ? 'text-green-400' : wf.avg_efficiency_ratio >= 50 ? 'text-yellow-400' : 'text-red-400'} />
              <Stat label="IS WR" value={`${(wf.avg_in_sample_win_rate || 0).toFixed(1)}%`} />
              <Stat label="OOS WR" value={`${(wf.avg_out_of_sample_win_rate || 0).toFixed(1)}%`} />
            </>
          )}
        </div>
      </div>

      {/* Reason */}
      {v.reason && (
        <div className="text-[8px] text-zinc-500 leading-relaxed truncate" title={v.reason}>
          {v.reason}
        </div>
      )}

      {/* Duration */}
      <div className="text-[8px] text-zinc-600 text-right">
        {(v.total_duration_seconds || 0) > 60
          ? `${(v.total_duration_seconds / 60).toFixed(1)}min`
          : `${(v.total_duration_seconds || 0).toFixed(0)}s`}
      </div>
    </div>
  );
});

// ─── Profile Badge ────────────────────────
const ProfileBadge = ({ profile, validation }) => {
  const label = BAR_SIZE_LABELS[profile.bar_size] || profile.bar_size;
  const hasValidation = !!validation;
  const vStatus = validation?.status;

  if (profile.trained) {
    const acc = profile.accuracy != null ? `${(profile.accuracy * 100).toFixed(1)}%` : '?';
    let accColor = profile.accuracy >= 0.55 ? 'text-green-400 bg-green-500/15 border-green-500/25'
      : profile.accuracy >= 0.50 ? 'text-yellow-400 bg-yellow-500/15 border-yellow-500/25'
      : 'text-zinc-400 bg-white/5 border-white/10';

    // Override with validation status color
    if (hasValidation) {
      if (vStatus === 'promoted') accColor = 'text-green-400 bg-green-500/15 border-green-500/25';
      else if (vStatus === 'rejected') accColor = 'text-red-400 bg-red-500/15 border-red-500/25';
    }

    return (
      <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono ${accColor}`} data-testid={`profile-badge-${profile.bar_size}`}>
        {hasValidation && vStatus === 'promoted' && <ShieldCheck className="w-2.5 h-2.5" />}
        {hasValidation && vStatus === 'rejected' && <ShieldX className="w-2.5 h-2.5" />}
        {!hasValidation && <Timer className="w-2.5 h-2.5" />}
        <span className="font-semibold">{label}</span>
        <span>{acc}</span>
      </div>
    );
  }
  return (
    <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.02] text-[10px] text-zinc-500 font-mono" data-testid={`profile-badge-${profile.bar_size}`}>
      <Timer className="w-2.5 h-2.5" />
      <span>{label}</span>
      <span>--</span>
    </div>
  );
};

// ─── Setup Card ───────────────────────────
const SetupCard = memo(({ name, data, trainingStatus, onTrain, validations, batchData }) => {
  const [showProfiles, setShowProfiles] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const cfg = SETUP_CONFIG[name] || SETUP_CONFIG.MOMENTUM;
  const Icon = cfg.icon;

  const profiles = data?.profiles || [];
  const trainedCount = data?.profiles_trained || 0;
  const totalCount = data?.profiles_total || profiles.length;
  const isAnyTraining = Object.keys(trainingStatus).some(k => k.startsWith(`setup_${name}`) && trainingStatus[k]?.status === 'running');

  const bestProfile = profiles.reduce((best, p) => {
    if (!p.trained) return best;
    if (!best || (p.accuracy || 0) > (best.accuracy || 0)) return p;
    return best;
  }, null);

  // Get validations for this setup's profiles
  const profileValidations = {};
  profiles.forEach(p => {
    const key = `${name}/${p.bar_size}`;
    if (validations[key]) profileValidations[p.bar_size] = validations[key];
  });
  const hasValidations = Object.keys(profileValidations).length > 0;
  const promotedCount = Object.values(profileValidations).filter(v => v.status === 'promoted').length;
  const rejectedCount = Object.values(profileValidations).filter(v => v.status === 'rejected').length;

  // Batch data for this setup (market-wide)
  const mwData = batchData?.market_wide?.find(m => m.setup_type === name);
  const msData = batchData?.multi_strategy;

  return (
    <div
      className={`rounded-lg border ${cfg.border} ${cfg.bg} transition-all hover:brightness-110`}
      data-testid={`setup-card-${name}`}
    >
      <div className="p-3">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <Icon className={`w-4 h-4 flex-shrink-0 ${cfg.color}`} />
            <span className="text-xs font-semibold text-white truncate">{name.replace(/_/g, ' ')}</span>
          </div>
          {isAnyTraining ? (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-[10px] flex-shrink-0">
              <Loader2 className="w-2.5 h-2.5 animate-spin" /> Training
            </span>
          ) : trainedCount === totalCount && totalCount > 0 ? (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-green-500/20 text-green-400 text-[10px] flex-shrink-0">
              <CheckCircle2 className="w-2.5 h-2.5" /> {trainedCount}/{totalCount}
            </span>
          ) : trainedCount > 0 ? (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400 text-[10px] flex-shrink-0">
              {trainedCount}/{totalCount}
            </span>
          ) : (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-zinc-500/20 text-zinc-500 text-[10px] flex-shrink-0">
              <XCircle className="w-2.5 h-2.5" /> 0/{totalCount}
            </span>
          )}
        </div>

        <p className="text-[10px] text-zinc-500 mb-2">{data?.description || ''}</p>

        {/* Profile badges row */}
        <div className="flex flex-wrap gap-1 mb-2">
          {profiles.map(p => (
            <ProfileBadge key={p.bar_size} profile={p} validation={profileValidations[p.bar_size]} />
          ))}
        </div>

        {/* Validation status summary line */}
        {hasValidations && (
          <div className="flex items-center gap-2 mb-1.5 text-[9px]">
            <Shield className="w-3 h-3 text-zinc-500" />
            {promotedCount > 0 && (
              <span className="text-green-400">{promotedCount} promoted</span>
            )}
            {rejectedCount > 0 && (
              <span className="text-red-400">{rejectedCount} rejected</span>
            )}
            {/* Best AI edge across profiles */}
            {(() => {
              const edges = Object.values(profileValidations)
                .map(v => v.ai_comparison?.ai_edge_win_rate || 0)
                .filter(e => e !== 0);
              if (edges.length > 0) {
                const bestEdge = Math.max(...edges);
                return (
                  <span className={bestEdge > 0 ? 'text-green-400' : 'text-red-400'}>
                    AI {bestEdge > 0 ? '+' : ''}{bestEdge.toFixed(1)}%
                  </span>
                );
              }
              return null;
            })()}
            {/* Best MC risk */}
            {(() => {
              const risks = Object.values(profileValidations)
                .map(v => v.monte_carlo?.risk_assessment)
                .filter(Boolean);
              if (risks.length > 0) {
                const riskOrder = ['LOW', 'MEDIUM', 'HIGH', 'EXTREME'];
                const worst = risks.reduce((w, r) => riskOrder.indexOf(r) > riskOrder.indexOf(w) ? r : w, 'LOW');
                return (
                  <span className={RISK_COLORS[worst]?.split(' ')[0] || 'text-zinc-400'}>
                    {worst}
                  </span>
                );
              }
              return null;
            })()}
          </div>
        )}

        {/* Market-wide signal density (from batch) */}
        {mwData && !mwData.error && (
          <div className="flex items-center gap-2 mb-1.5 text-[9px]">
            <Globe className="w-3 h-3 text-zinc-500" />
            <span className="text-zinc-400">
              {mwData.symbols_with_signals}/{mwData.symbols_scanned} symbols
            </span>
            <span className="text-zinc-400">{mwData.total_trades} trades</span>
            <span className={mwData.win_rate > 50 ? 'text-green-400' : 'text-yellow-400'}>
              {mwData.win_rate?.toFixed(1)}% WR
            </span>
          </div>
        )}

        {/* Best accuracy highlight */}
        {bestProfile && (
          <div className="flex justify-between text-[10px] mb-1">
            <span className="text-zinc-500">Best</span>
            <span className="text-green-400 font-mono">
              {(bestProfile.accuracy * 100).toFixed(1)}% ({BAR_SIZE_LABELS[bestProfile.bar_size] || bestProfile.bar_size})
            </span>
          </div>
        )}

        {/* Expandable profile details */}
        <button
          onClick={() => setShowProfiles(!showProfiles)}
          className="w-full text-left text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1 mb-1"
          data-testid={`toggle-profiles-${name}`}
        >
          <ChevronDown className={`w-3 h-3 transition-transform ${showProfiles ? 'rotate-180' : ''}`} />
          {showProfiles ? 'Hide profiles' : `${totalCount} profile${totalCount > 1 ? 's' : ''}`}
        </button>

        <AnimatePresence>
          {showProfiles && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="space-y-1.5 mb-2 overflow-hidden"
            >
              {profiles.map(p => {
                const statusKey = `setup_${name}_${p.bar_size}`;
                const pTraining = trainingStatus[statusKey];
                const pVal = profileValidations[p.bar_size];
                return (
                  <div key={p.bar_size} className="p-2 rounded bg-black/20 border border-white/5" data-testid={`profile-detail-${name}-${p.bar_size}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono text-zinc-300">{BAR_SIZE_LABELS[p.bar_size] || p.bar_size}</span>
                      {p.trained ? (
                        <span className="text-[10px] text-green-400 font-mono">{(p.accuracy * 100).toFixed(1)}%</span>
                      ) : pTraining?.status === 'running' ? (
                        <span className="text-[10px] text-cyan-400 flex items-center gap-1"><Loader2 className="w-2 h-2 animate-spin" /> Training</span>
                      ) : (
                        <span className="text-[10px] text-zinc-500">Not trained</span>
                      )}
                    </div>
                    <div className="text-[9px] text-zinc-500">{p.description}</div>
                    <div className="flex gap-2 mt-1 text-[9px]">
                      <span className="text-zinc-600">h={p.forecast_horizon}</span>
                      <span className="text-zinc-600">thr={((p.noise_threshold || 0) * 100).toFixed(2)}%</span>
                      {p.label_scheme === "triple_barrier_3class" && (
                        <span className="text-emerald-400/80" data-testid={`label-scheme-${name}-${p.bar_size}`}>Triple-Barrier</span>
                      )}
                      {p.label_scheme === "binary" && (
                        <span className="text-rose-400/80" title="Legacy binary model — retrain recommended" data-testid={`label-scheme-${name}-${p.bar_size}`}>Legacy binary</span>
                      )}
                      {p.num_classes >= 3 && !p.label_scheme && <span className="text-amber-500/60">3-class</span>}
                    </div>
                    {p.trained && (
                      <div className="flex gap-3 mt-1 text-[9px]">
                        <span className="text-zinc-500">{(p.training_samples || 0).toLocaleString()} samples</span>
                        {p.version && <span className="text-zinc-600">{p.version}</span>}
                      </div>
                    )}
                    {pTraining?.status === 'running' && pTraining.message && (
                      <div className="text-[9px] text-cyan-400/70 mt-1 truncate">{pTraining.message}</div>
                    )}

                    {/* Per-profile validation detail */}
                    {pVal && <ValidationSummary validation={pVal} />}
                  </div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Validation history toggle */}
        {hasValidations && !showProfiles && (
          <button
            onClick={() => setShowValidation(!showValidation)}
            className="w-full text-left text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1 mb-1"
            data-testid={`toggle-validation-${name}`}
          >
            <Shield className={`w-3 h-3 transition-transform`} />
            {showValidation ? 'Hide validation' : 'View validation'}
          </button>
        )}

        <AnimatePresence>
          {showValidation && !showProfiles && hasValidations && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="space-y-1.5 mb-2 overflow-hidden"
            >
              {Object.entries(profileValidations).map(([barSize, val]) => (
                <div key={barSize}>
                  <div className="text-[9px] text-zinc-400 font-mono mb-0.5">{BAR_SIZE_LABELS[barSize] || barSize}</div>
                  <ValidationSummary validation={val} />
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Train button */}
        {isAnyTraining ? (
          <div className="text-[10px] text-cyan-400/80 text-center mt-1">Training in progress...</div>
        ) : (
          <button
            onClick={() => onTrain(name)}
            className={`w-full flex items-center justify-center gap-1 px-2 py-1.5 rounded text-[10px] font-medium transition-colors mt-1 ${
              trainedCount === totalCount && totalCount > 0
                ? 'bg-white/5 hover:bg-white/10 text-zinc-400 border border-white/5'
                : 'bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/30'
            }`}
            data-testid={`train-${name}-btn`}
          >
            <PlayCircle className="w-3 h-3" />
            {trainedCount === totalCount && totalCount > 0 ? 'Retrain All Profiles' : `Train ${totalCount} Profile${totalCount > 1 ? 's' : ''}`}
          </button>
        )}
      </div>
    </div>
  );
});

// ─── Batch Validation Panel (Multi-Strategy + Market-Wide) ────
const BatchValidationPanel = memo(({ batchData }) => {
  const [expanded, setExpanded] = useState(false);
  if (!batchData) return null;

  const ms = batchData.multi_strategy;
  const mw = batchData.market_wide || [];

  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.02] p-3" data-testid="batch-validation-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between text-xs text-zinc-300"
        data-testid="toggle-batch-validation"
      >
        <div className="flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-semibold">Batch Validation</span>
          {ms && !ms.error && (
            <span className="text-[10px] text-zinc-500">
              {ms.strategies_compared} strategies compared
            </span>
          )}
        </div>
        <ChevronDown className={`w-3.5 h-3.5 text-zinc-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden mt-3 space-y-3"
          >
            {/* Phase 4: Multi-Strategy */}
            {ms && !ms.error && (
              <div className="p-2 rounded bg-black/20 border border-white/5" data-testid="multi-strategy-results">
                <div className="flex items-center gap-1.5 mb-2 text-[10px] text-zinc-300 font-semibold">
                  <BarChart2 className="w-3 h-3 text-cyan-400" />
                  Phase 4: Multi-Strategy Comparison
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2 text-[9px]">
                  <Stat label="Combined WR" value={`${(ms.combined_win_rate || 0).toFixed(1)}%`}
                    color={ms.combined_win_rate > 50 ? 'text-green-400' : 'text-yellow-400'} />
                  <Stat label="Combined Sharpe" value={`${(ms.combined_sharpe || 0).toFixed(2)}`}
                    color={ms.combined_sharpe > 0.5 ? 'text-green-400' : 'text-zinc-400'} />
                  <Stat label="Best" value={ms.best_strategy?.replace(/_/g, ' ') || '?'} color="text-cyan-400" />
                </div>
                {/* Per-strategy table */}
                <div className="space-y-0.5">
                  {(ms.strategy_summaries || []).map(s => (
                    <div key={s.setup_type} className="flex items-center justify-between text-[9px] py-0.5 border-b border-white/5 last:border-0">
                      <span className="text-zinc-400">{(s.setup_type || '').replace(/_/g, ' ')}</span>
                      <div className="flex gap-3">
                        <span className={s.win_rate > 50 ? 'text-green-400' : 'text-zinc-400'}>{s.win_rate?.toFixed(1)}%</span>
                        <span className="text-zinc-500">{s.total_trades}t</span>
                        <span className={s.sharpe_ratio > 0 ? 'text-green-400' : 'text-red-400'}>{s.sharpe_ratio?.toFixed(2)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Phase 5: Market-Wide */}
            {mw.length > 0 && (
              <div className="p-2 rounded bg-black/20 border border-white/5" data-testid="market-wide-results">
                <div className="flex items-center gap-1.5 mb-2 text-[10px] text-zinc-300 font-semibold">
                  <Globe className="w-3 h-3 text-cyan-400" />
                  Phase 5: Market-Wide Scan
                </div>
                <div className="space-y-0.5">
                  {mw.filter(m => !m.error).map(m => (
                    <div key={m.setup_type} className="flex items-center justify-between text-[9px] py-0.5 border-b border-white/5 last:border-0">
                      <span className="text-zinc-400">{(m.setup_type || '').replace(/_/g, ' ')}</span>
                      <div className="flex gap-3">
                        <span className="text-zinc-500">{m.symbols_with_signals}/{m.symbols_scanned}</span>
                        <span className="text-zinc-400">{m.total_trades}t</span>
                        <span className={m.win_rate > 50 ? 'text-green-400' : 'text-yellow-400'}>{m.win_rate?.toFixed(1)}%</span>
                        <span className={m.profit_factor > 1 ? 'text-green-400' : 'text-red-400'}>PF {m.profit_factor?.toFixed(2)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Duration */}
            {batchData.total_duration_seconds && (
              <div className="text-[9px] text-zinc-600 text-right">
                Total: {(batchData.total_duration_seconds / 60).toFixed(1)} min
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ─── Main Panel ───────────────────────────
const SetupModelsPanel = memo(({ embedded = false }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [trainingAll, setTrainingAll] = useState(false);
  const [localTraining, setLocalTraining] = useState({});
  const [activeJobs, setActiveJobs] = useState({});
  const [validations, setValidations] = useState({});
  const [batchData, setBatchData] = useState(null);
  const sendTrainCommand = useTrainCommand();

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get('/api/ai-modules/timeseries/setups/status');
      if (res.data?.success) setStatus(res.data);
    } catch (err) {
      console.error('Error fetching setup models status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchValidations = useCallback(async () => {
    try {
      const [latestRes, batchRes] = await Promise.all([
        api.get('/api/ai-modules/validation/latest'),
        api.get('/api/ai-modules/validation/batch-history?limit=1'),
      ]);
      if (latestRes.data?.success) setValidations(latestRes.data.validations || {});
      if (batchRes.data?.success && batchRes.data.records?.length > 0) {
        setBatchData(batchRes.data.records[0]);
      }
    } catch (err) {
      console.error('Error fetching validations:', err);
    }
  }, []);

  const pollJobs = useCallback(async () => {
    const jobs = { ...activeJobs };
    let changed = false;
    for (const [key, jobId] of Object.entries(jobs)) {
      try {
        const res = await api.get(`/api/jobs/${jobId}`);
        const job = res.data?.job;
        if (!job) continue;
        const progress = job.progress || {};
        if (job.status === 'completed') {
          const profiles = job.result?.details?.profiles_trained || job.result?.profiles_trained;
          const valStatus = job.result?.validation?.status;
          let msg = `${key} training complete${profiles ? ` — ${profiles} profiles` : ''}`;
          if (valStatus) msg += ` (${valStatus})`;
          toast.success(msg);
          delete jobs[key];
          changed = true;
        } else if (job.status === 'failed') {
          toast.error(`${key} failed: ${job.error || 'Unknown error'}`);
          delete jobs[key];
          changed = true;
        } else {
          setLocalTraining(prev => ({
            ...prev,
            [key]: { status: 'running', message: progress.message || 'Processing...', percent: progress.percent || 0 }
          }));
        }
      } catch { /* ignore */ }
    }
    if (changed) {
      setActiveJobs(jobs);
      setLocalTraining(prev => {
        const next = { ...prev };
        for (const k of Object.keys(next)) { if (!jobs[k]) delete next[k]; }
        return next;
      });
      fetchStatus();
      fetchValidations();
    }
  }, [activeJobs, fetchStatus, fetchValidations]);

  useEffect(() => { fetchStatus(); fetchValidations(); }, [fetchStatus, fetchValidations]);

  const hasActiveJobs = Object.keys(activeJobs).length > 0;
  useEffect(() => {
    if (!hasActiveJobs) return;
    const interval = setInterval(pollJobs, 3000);
    return () => clearInterval(interval);
  }, [hasActiveJobs, pollJobs]);

  const handleTrainOne = useCallback(async (setupType) => {
    setLocalTraining(prev => ({ ...prev, [setupType]: { status: 'running', message: 'Queuing...' } }));
    toast.info(`Training all ${setupType.replace(/_/g, ' ')} profiles...`);
    try {
      const res = await sendTrainCommand({ action: 'train_setup', setup_type: setupType }, setupType);
      if (res.success && res.job_id) {
        setActiveJobs(prev => ({ ...prev, [setupType]: res.job_id }));
        setLocalTraining(prev => ({ ...prev, [setupType]: { status: 'running', message: 'Waiting for worker...' } }));
      } else {
        toast.error(res.error || `Failed to queue ${setupType}`);
        setLocalTraining(prev => { const n = { ...prev }; delete n[setupType]; return n; });
      }
    } catch (err) {
      toast.error(`Error: ${err.message}`);
      setLocalTraining(prev => { const n = { ...prev }; delete n[setupType]; return n; });
    }
  }, [sendTrainCommand]);

  const handleTrainAll = useCallback(async () => {
    setTrainingAll(true);
    toast.info('Queuing all setup model training...');
    try {
      const res = await sendTrainCommand({ action: 'train_setup_all' }, 'setup_all');
      if (res.success && res.job_id) {
        toast.success('All setup model training queued');
        setActiveJobs(prev => ({ ...prev, _ALL: res.job_id }));
      } else {
        toast.error(res.error || 'Failed to queue training');
        setTrainingAll(false);
      }
    } catch (err) {
      toast.error(`Error: ${err.message}`);
      setTrainingAll(false);
    }
  }, [sendTrainCommand]);

  const models = status?.models || {};
  const trainedCount = status?.models_trained || 0;
  const totalProfiles = status?.total_profiles || 17;
  const serverTraining = status?.training_status || {};

  const mergedTraining = { ...serverTraining };
  for (const [key, val] of Object.entries(localTraining)) {
    const serverKey = `setup_${key}`;
    if (!mergedTraining[serverKey] || mergedTraining[serverKey].status !== 'running') {
      mergedTraining[serverKey] = val;
    }
  }

  const anyTraining = hasActiveJobs || Object.keys(localTraining).length > 0;

  useEffect(() => {
    if (trainingAll && !activeJobs._ALL) setTrainingAll(false);
  }, [trainingAll, activeJobs]);

  // Count total validations
  const totalValidated = Object.keys(validations).length;
  const totalPromoted = Object.values(validations).filter(v => v.status === 'promoted').length;

  const content = (
    <div data-testid="setup-models-content">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`text-xs px-2 py-0.5 rounded-full ${trainedCount > 0 ? 'bg-green-500/20 text-green-400' : 'bg-zinc-500/20 text-zinc-500'}`}>
            {trainedCount}/{totalProfiles} profiles trained
          </span>
          {totalValidated > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 flex items-center gap-1">
              <Shield className="w-3 h-3" />
              {totalPromoted}/{totalValidated} promoted
            </span>
          )}
          <span className="text-[10px] text-zinc-500">{Object.keys(models).length} setup types</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { fetchStatus(); fetchValidations(); }}
            disabled={loading}
            className="p-1.5 rounded bg-white/5 hover:bg-white/10 border border-white/5 text-zinc-400"
            data-testid="refresh-setup-status-btn"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={handleTrainAll}
            disabled={anyTraining || trainingAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/30 disabled:opacity-40"
            data-testid="train-all-setups-btn"
          >
            {anyTraining || trainingAll ? (
              <><Loader2 className="w-3 h-3 animate-spin" /> Training...</>
            ) : (
              <><PlayCircle className="w-3 h-3" /> Train All</>
            )}
          </button>
        </div>
      </div>

      {/* Pipeline info badge */}
      <div className="flex items-center gap-2 mb-3 px-2 py-1.5 rounded bg-cyan-500/5 border border-cyan-500/10 text-[10px] text-cyan-400/70" data-testid="pipeline-info">
        <Info className="w-3 h-3 flex-shrink-0" />
        <span>5-Phase Auto-Validation: AI Comparison &rarr; Monte Carlo &rarr; Walk-Forward &rarr; Multi-Strategy &rarr; Market-Wide</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        {Object.entries(models).map(([name, model]) => (
          <SetupCard
            key={name}
            name={name}
            data={model}
            trainingStatus={mergedTraining}
            onTrain={handleTrainOne}
            validations={validations}
            batchData={batchData}
          />
        ))}
      </div>

      {/* Batch Validation Panel */}
      <BatchValidationPanel batchData={batchData} />

      {Object.keys(models).length === 0 && !loading && (
        <div className="text-center py-8 text-zinc-500 text-sm">No setup model data. Click refresh to load.</div>
      )}
      {loading && Object.keys(models).length === 0 && (
        <div className="flex items-center justify-center py-8 gap-2 text-zinc-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading...
        </div>
      )}
    </div>
  );

  if (embedded) return content;

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="setup-models-panel">
      <div className="p-4">{content}</div>
    </div>
  );
});

export default SetupModelsPanel;
