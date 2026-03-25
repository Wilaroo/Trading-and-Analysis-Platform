import React, { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Crosshair, TrendingUp, Zap, BarChart3, Target,
  ArrowUpDown, GitBranch, Clock, Gauge, Activity,
  ChevronDown, PlayCircle, Loader2, CheckCircle2,
  XCircle, RefreshCw, Layers, Timer
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
  '1 min': '1m',
  '5 mins': '5m',
  '1 hour': '1h',
  '1 day': '1D',
};

const ProfileBadge = ({ profile }) => {
  const label = BAR_SIZE_LABELS[profile.bar_size] || profile.bar_size;
  if (profile.trained) {
    const acc = profile.accuracy != null ? `${(profile.accuracy * 100).toFixed(1)}%` : '?';
    const accColor = profile.accuracy >= 0.55 ? 'text-green-400 bg-green-500/15 border-green-500/25'
      : profile.accuracy >= 0.50 ? 'text-yellow-400 bg-yellow-500/15 border-yellow-500/25'
      : 'text-zinc-400 bg-white/5 border-white/10';
    return (
      <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono ${accColor}`} data-testid={`profile-badge-${profile.bar_size}`}>
        <Timer className="w-2.5 h-2.5" />
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

const SetupCard = memo(({ name, data, trainingStatus, onTrain }) => {
  const [showProfiles, setShowProfiles] = useState(false);
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
          {profiles.map(p => <ProfileBadge key={p.bar_size} profile={p} />)}
        </div>

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
          className="w-full text-left text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1 mb-2"
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
                      {p.num_classes >= 3 && <span className="text-amber-500/60">3-class</span>}
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
                  </div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Train button */}
        {isAnyTraining ? (
          <div className="text-[10px] text-cyan-400/80 text-center">Training in progress...</div>
        ) : (
          <button
            onClick={() => onTrain(name)}
            className={`w-full flex items-center justify-center gap-1 px-2 py-1.5 rounded text-[10px] font-medium transition-colors ${
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

const SetupModelsPanel = memo(({ embedded = false }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [trainingAll, setTrainingAll] = useState(false);
  const [localTraining, setLocalTraining] = useState({});
  const [activeJobs, setActiveJobs] = useState({});
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
          toast.success(`${key} training complete${profiles ? ` — ${profiles} profiles` : ''}`);
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
        for (const k of Object.keys(next)) {
          if (!jobs[k]) delete next[k];
        }
        return next;
      });
      fetchStatus();
    }
  }, [activeJobs, fetchStatus]);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

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
      const res = await sendTrainCommand(
        { action: 'train_setup', setup_type: setupType },
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
      toast.error(`Error: ${err.message}`);
      setLocalTraining(prev => { const n = { ...prev }; delete n[setupType]; return n; });
    }
  }, [sendTrainCommand]);

  const handleTrainAll = useCallback(async () => {
    setTrainingAll(true);
    toast.info('Queuing all setup model training...');
    try {
      const res = await sendTrainCommand(
        { action: 'train_setup_all' },
        'setup_all'
      );
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

  const content = (
    <div data-testid="setup-models-content">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full ${trainedCount > 0 ? 'bg-green-500/20 text-green-400' : 'bg-zinc-500/20 text-zinc-500'}`}>
            {trainedCount}/{totalProfiles} profiles trained
          </span>
          <span className="text-[10px] text-zinc-500">{Object.keys(models).length} setup types</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchStatus}
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

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        {Object.entries(models).map(([name, model]) => (
          <SetupCard
            key={name}
            name={name}
            data={model}
            trainingStatus={mergedTraining}
            onTrain={handleTrainOne}
          />
        ))}
      </div>

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
