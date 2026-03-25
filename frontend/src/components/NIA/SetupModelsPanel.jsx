import React, { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Crosshair, TrendingUp, Zap, BarChart3, Target,
  ArrowUpDown, GitBranch, Clock, Gauge, Activity,
  ChevronDown, PlayCircle, Loader2, CheckCircle2,
  XCircle, RefreshCw, Layers
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

const SetupCard = memo(({ name, model, training, onTrain }) => {
  const cfg = SETUP_CONFIG[name] || SETUP_CONFIG.MOMENTUM;
  const Icon = cfg.icon;
  const isTraining = training?.status === 'running';
  const isTrained = model?.trained;

  return (
    <div
      className={`p-3 rounded-lg border ${cfg.border} ${cfg.bg} transition-all hover:brightness-110`}
      data-testid={`setup-card-${name}`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className={`w-4 h-4 flex-shrink-0 ${cfg.color}`} />
          <span className="text-xs font-semibold text-white truncate">{name.replace(/_/g, ' ')}</span>
        </div>
        {isTraining ? (
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-[10px] flex-shrink-0">
            <Loader2 className="w-2.5 h-2.5 animate-spin" /> Training
          </span>
        ) : isTrained ? (
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-green-500/20 text-green-400 text-[10px] flex-shrink-0">
            <CheckCircle2 className="w-2.5 h-2.5" /> Trained
          </span>
        ) : (
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-zinc-500/20 text-zinc-500 text-[10px] flex-shrink-0">
            <XCircle className="w-2.5 h-2.5" /> Untrained
          </span>
        )}
      </div>

      <p className="text-[10px] text-zinc-500 mb-2 leading-tight">{model?.description || ''}</p>

      {/* Training config */}
      {model?.training_config && (
        <div className="flex gap-2 mb-2 flex-wrap">
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-500 font-mono">
            {model.training_config.forecast_horizon}d horizon
          </span>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-500 font-mono">
            {(model.training_config.noise_threshold * 100).toFixed(1)}% threshold
          </span>
          {model.training_config.num_classes >= 3 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400/80 font-mono">
              3-class
            </span>
          )}
        </div>
      )}

      {isTrained && (
        <div className="space-y-1 mb-2">
          <div className="flex justify-between text-[10px]">
            <span className="text-zinc-500">Accuracy</span>
            <span className={`font-mono ${model.accuracy >= 0.55 ? 'text-green-400' : model.accuracy >= 0.50 ? 'text-yellow-400' : 'text-zinc-400'}`}>
              {model.accuracy != null ? `${(model.accuracy * 100).toFixed(1)}%` : '--'}
            </span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-zinc-500">Samples</span>
            <span className="text-zinc-400 font-mono">{(model.training_samples || 0).toLocaleString()}</span>
          </div>
          {model.version && (
            <div className="flex justify-between text-[10px]">
              <span className="text-zinc-500">Version</span>
              <span className="text-zinc-500 font-mono">{model.version}</span>
            </div>
          )}
        </div>
      )}

      {isTraining ? (
        <div className="space-y-1">
          {training?.percent > 0 && (
            <div className="w-full h-1 rounded-full bg-white/10 overflow-hidden">
              <div
                className="h-full rounded-full bg-cyan-400 transition-all duration-500"
                style={{ width: `${Math.min(training.percent, 100)}%` }}
              />
            </div>
          )}
          <div className="text-[10px] text-cyan-400/80 truncate">{training?.message || 'Training...'}</div>
        </div>
      ) : (
        <button
          onClick={() => onTrain(name)}
          className={`w-full flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${
            isTrained
              ? 'bg-white/5 hover:bg-white/10 text-zinc-400 border border-white/5'
              : 'bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/30'
          }`}
          data-testid={`train-${name}-btn`}
        >
          <PlayCircle className="w-3 h-3" />
          {isTrained ? 'Retrain' : 'Train'}
        </button>
      )}
    </div>
  );
});

const SetupModelsPanel = memo(() => {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [trainingAll, setTrainingAll] = useState(false);
  const [localTraining, setLocalTraining] = useState({});  // track per-type training locally

  const [activeJobs, setActiveJobs] = useState({});  // { setupType: job_id }
  const sendTrainCommand = useTrainCommand();

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get('/api/ai-modules/timeseries/setups/status');
      if (res.data?.success) {
        setStatus(res.data);
      }
    } catch (err) {
      console.error('Error fetching setup models status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll active jobs for progress
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
          const acc = job.result?.accuracy || job.result?.details?.metrics?.accuracy;
          toast.success(`${key} trained${acc ? ` — ${(acc * 100).toFixed(1)}%` : ''}!`);
          delete jobs[key];
          changed = true;
        } else if (job.status === 'failed') {
          toast.error(`${key} failed: ${job.error || 'Unknown error'}`);
          delete jobs[key];
          changed = true;
        } else {
          // Still running — update local training message
          setLocalTraining(prev => ({
            ...prev,
            [key]: { status: 'running', message: progress.message || 'Processing...', percent: progress.percent || 0 }
          }));
        }
      } catch {
        // ignore polling errors
      }
    }

    if (changed) {
      setActiveJobs(jobs);
      // Clear finished local training entries
      setLocalTraining(prev => {
        const next = { ...prev };
        for (const k of Object.keys(next)) {
          if (!jobs[k]) delete next[k];
        }
        return next;
      });
      fetchStatus();
    }
  }, [activeJobs, fetchStatus]);

  // Fetch on mount so header badge shows correct count
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Re-fetch when expanded if stale
  useEffect(() => {
    if (expanded) fetchStatus();
  }, [expanded, fetchStatus]);

  // Poll while any jobs are active
  const hasActiveJobs = Object.keys(activeJobs).length > 0;

  useEffect(() => {
    if (!expanded || !hasActiveJobs) return;
    const interval = setInterval(pollJobs, 2500);
    return () => clearInterval(interval);
  }, [expanded, hasActiveJobs, pollJobs]);

  const handleTrainOne = useCallback(async (setupType) => {
    setLocalTraining(prev => ({ ...prev, [setupType]: { status: 'running', message: 'Queuing job...' } }));
    toast.info(`Training ${setupType.replace(/_/g, ' ')} model...`);

    try {
      // Send training command via WebSocket (bypasses HTTP connection pool)
      const res = await sendTrainCommand(
        { action: 'train_setup', setup_type: setupType, bar_size: '1 day' },
        setupType
      );
      if (res.success && res.job_id) {
        setActiveJobs(prev => ({ ...prev, [setupType]: res.job_id }));
        setLocalTraining(prev => ({ ...prev, [setupType]: { status: 'running', message: 'Waiting for worker...' } }));
      } else {
        toast.error(res.error || `Failed to queue ${setupType}`);
        setLocalTraining(prev => { const n = { ...prev }; delete n[setupType]; return n; });
      }
    } catch (err) {
      // Fallback: check if a job is already running for this setup type
      try {
        const check = await api.get('/api/jobs/running');
        const running = check?.data?.jobs || [];
        const match = running.find(j => j.params?.setup_type === setupType);
        if (match) {
          setActiveJobs(prev => ({ ...prev, [setupType]: match.job_id }));
          setLocalTraining(prev => ({ ...prev, [setupType]: { status: 'running', message: 'Training in progress...' } }));
          toast.success(`${setupType.replace(/_/g, ' ')} training is running`);
          return;
        }
      } catch { /* fallback check failed */ }
      toast.error(`Error: ${err.message}`);
      setLocalTraining(prev => { const n = { ...prev }; delete n[setupType]; return n; });
    }
  }, [sendTrainCommand]);

  const handleTrainAll = useCallback(async () => {
    try {
      setTrainingAll(true);
      toast.info('Queuing all setup model training...');
      const res = await sendTrainCommand(
        { action: 'train_setup_all', bar_size: '1 day' },
        'setup_all'
      );
      if (res.success && res.job_id) {
        toast.success('All setup models training queued');
        setActiveJobs(prev => ({ ...prev, _ALL: res.job_id }));
        setLocalTraining(prev => ({ ...prev, _ALL: { status: 'running', message: 'Waiting for worker...' } }));
      } else {
        toast.error(res.error || 'Failed to queue training');
        setTrainingAll(false);
      }
    } catch (err) {
      // Fallback: check for running jobs
      try {
        const check = await api.get('/api/jobs/running');
        const running = check?.data?.jobs || [];
        const match = running.find(j => j.job_type === 'setup_training');
        if (match) {
          setActiveJobs(prev => ({ ...prev, _ALL: match.job_id }));
          setLocalTraining(prev => ({ ...prev, _ALL: { status: 'running', message: 'Training in progress...' } }));
          toast.success('Setup training is running');
          return;
        }
      } catch { /* check failed */ }
      toast.error(`Error: ${err.message}`);
      setTrainingAll(false);
    }
  }, [sendTrainCommand]);

  const models = status?.models || {};
  const trainedCount = status?.models_trained || 0;
  const totalCount = status?.total_setup_types || 10;
  const serverTrainingStatus = status?.training_status || {};

  // Merge local training state with server training status
  const mergedTrainingStatus = { ...serverTrainingStatus };
  for (const [key, val] of Object.entries(localTraining)) {
    const serverKey = `setup_${key}`;
    if (!mergedTrainingStatus[serverKey] || mergedTrainingStatus[serverKey].status !== 'running') {
      mergedTrainingStatus[serverKey] = val;
    }
  }

  // Check if any are currently training
  const anyTraining = hasActiveJobs || Object.keys(localTraining).length > 0;

  // Stop train-all state when its job completes
  useEffect(() => {
    if (trainingAll && !activeJobs._ALL) {
      setTrainingAll(false);
    }
  }, [trainingAll, activeJobs]);

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="setup-models-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="setup-models-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #06b6d4, #8b5cf6)' }}>
            <Layers className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Setup-Specific AI Models</h3>
            <p className="text-xs text-zinc-400">Specialized models per trading setup type</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full ${trainedCount > 0 ? 'bg-green-500/20 text-green-400' : 'bg-zinc-500/20 text-zinc-500'}`}>
            {trainedCount}/{totalCount} trained
          </span>
          <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/10"
          >
            <div className="p-4">
              {/* Header actions */}
              <div className="flex items-center justify-between mb-4">
                <p className="text-xs text-zinc-500">
                  One model per setup type, shared across all timeframes (intraday, swing, investment).
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={fetchStatus}
                    disabled={loading}
                    className="p-1.5 rounded bg-white/5 hover:bg-white/10 border border-white/5 text-zinc-400 transition-colors"
                    data-testid="refresh-setup-status-btn"
                  >
                    <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
                  </button>
                  <button
                    onClick={handleTrainAll}
                    disabled={anyTraining || trainingAll}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
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

              {/* Setup model grid */}
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
                {Object.entries(models).map(([name, model]) => (
                  <SetupCard
                    key={name}
                    name={name}
                    model={model}
                    training={mergedTrainingStatus[`setup_${name}`]}
                    onTrain={handleTrainOne}
                  />
                ))}
              </div>

              {/* Empty state */}
              {Object.keys(models).length === 0 && !loading && (
                <div className="text-center py-8 text-zinc-500 text-sm">
                  No setup model data available. Click refresh to load.
                </div>
              )}

              {/* Loading state */}
              {loading && Object.keys(models).length === 0 && (
                <div className="flex items-center justify-center py-8 gap-2 text-zinc-500 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" /> Loading setup models...
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default SetupModelsPanel;
