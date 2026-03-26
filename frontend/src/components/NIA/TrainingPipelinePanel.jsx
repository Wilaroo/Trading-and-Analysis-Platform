/**
 * Training Pipeline Panel
 * Shows model inventory, training controls, regime status, and data readiness
 */
import React, { useState, useEffect, useCallback, memo } from 'react';
import {
  Brain, Play, Square, RefreshCw, TrendingUp, TrendingDown,
  Activity, Shield, Clock, Target, BarChart3, Layers, AlertTriangle,
  CheckCircle2, Circle, ChevronDown, ChevronRight, Zap
} from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../../utils/api';

const REGIME_COLORS = {
  bull_trend: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', label: 'BULL' },
  bear_trend: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', label: 'BEAR' },
  range_bound: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', label: 'RANGE' },
  high_vol: { bg: 'bg-violet-500/10', border: 'border-violet-500/30', text: 'text-violet-400', label: 'HIGH VOL' },
  unknown: { bg: 'bg-zinc-500/10', border: 'border-zinc-500/30', text: 'text-zinc-400', label: 'UNKNOWN' },
};

const CATEGORY_ICONS = {
  generic_directional: TrendingUp,
  setup_specific: Target,
  volatility: Activity,
  exit_timing: Clock,
  sector_relative: BarChart3,
  gap_fill: Zap,
  risk_of_ruin: Shield,
  ensemble: Layers,
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
};

const MetricBar = memo(({ value, max = 1, color = 'bg-cyan-500' }) => {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 bg-white/5 rounded-full overflow-hidden w-full" data-testid="metric-bar">
      <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
});

const IndexCard = memo(({ name, data: idx }) => {
  if (!idx || !idx.price) return null;
  const trendColor = idx.trend > 0.1 ? 'text-emerald-400' : idx.trend < -0.1 ? 'text-red-400' : 'text-amber-400';
  const rsiNorm = ((idx.rsi + 1) / 2) * 100;

  return (
    <div className="p-3 rounded-lg border border-white/5 bg-white/[0.02]" data-testid={`index-card-${name}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-bold text-white">{name}</span>
        <span className="text-xs font-mono text-zinc-300">${idx.price?.toFixed(2)}</span>
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500">Trend</span>
          <span className={`font-mono ${trendColor}`}>{idx.trend > 0 ? '+' : ''}{(idx.trend * 100).toFixed(0)}%</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500">RSI</span>
          <span className="font-mono text-zinc-300">{rsiNorm.toFixed(0)}</span>
        </div>
        <MetricBar value={rsiNorm} max={100} color={rsiNorm > 70 ? 'bg-red-500' : rsiNorm < 30 ? 'bg-emerald-500' : 'bg-cyan-500'} />
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500">Mom</span>
          <span className={`font-mono ${idx.momentum > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {idx.momentum > 0 ? '+' : ''}{(idx.momentum * 100).toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500">Vol</span>
          <span className="font-mono text-zinc-300">{(idx.volatility * 100).toFixed(2)}%</span>
        </div>
      </div>
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
  const avgAccuracy = models.filter(m => m.accuracy).reduce((sum, m) => sum + m.accuracy, 0) / (trainedCount || 1);

  return (
    <div className="border border-white/5 rounded-lg overflow-hidden" data-testid={`category-${categoryKey}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-white/[0.02] transition-colors"
        data-testid={`category-toggle-${categoryKey}`}
      >
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${color}`} />
          <span className="text-sm font-medium text-white">{category.label}</span>
          <span className="text-xs text-zinc-500">({totalCount})</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            {trainedCount > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                {trainedCount}/{totalCount}
              </span>
            )}
            {trainedCount === 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-500/10 text-zinc-500 font-mono">
                untrained
              </span>
            )}
            {avgAccuracy > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 font-mono">
                {(avgAccuracy * 100).toFixed(1)}%
              </span>
            )}
          </div>
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-zinc-500" /> : <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />}
        </div>
      </button>
      {expanded && (
        <div className="border-t border-white/5 p-2 space-y-1 max-h-60 overflow-auto">
          <p className="text-xs text-zinc-500 px-2 mb-1">{category.description}</p>
          {models.map((m) => (
            <div key={m.name} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-white/[0.02]" data-testid={`model-row-${m.name}`}>
              <div className="flex items-center gap-2">
                {m.trained ? (
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                ) : (
                  <Circle className="w-3 h-3 text-zinc-600" />
                )}
                <span className="text-xs text-zinc-300 font-mono">{m.name}</span>
              </div>
              <div className="flex items-center gap-2">
                {m.accuracy > 0 && (
                  <span className={`text-xs font-mono ${m.accuracy > 0.6 ? 'text-emerald-400' : m.accuracy > 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                    {(m.accuracy * 100).toFixed(1)}%
                  </span>
                )}
                {m.training_samples > 0 && (
                  <span className="text-[10px] text-zinc-600">{m.training_samples.toLocaleString()} samples</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

const TrainingPipelinePanel = memo(({ onRefresh, wsTrainingStatus, wsMarketRegime }) => {
  const [regime, setRegime] = useState(null);
  const [inventory, setInventory] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  // Use WebSocket data when available
  useEffect(() => {
    if (wsTrainingStatus) setPipelineStatus({ task_status: wsTrainingStatus.status, ...wsTrainingStatus });
  }, [wsTrainingStatus]);

  useEffect(() => {
    if (wsMarketRegime) setRegime(prev => ({ ...prev, ...wsMarketRegime }));
  }, [wsMarketRegime]);

  const fetchData = useCallback(async () => {
    try {
      const [regimeRes, inventoryRes, statusRes] = await Promise.allSettled([
        api.get('/api/ai-training/regime-live'),
        api.get('/api/ai-training/model-inventory'),
        api.get('/api/ai-training/status'),
      ]);

      if (regimeRes.status === 'fulfilled' && regimeRes.value.data?.success) {
        setRegime(regimeRes.value.data);
      }
      if (inventoryRes.status === 'fulfilled' && inventoryRes.value.data?.success) {
        setInventory(inventoryRes.value.data);
      }
      if (statusRes.status === 'fulfilled' && statusRes.value.data?.success) {
        setPipelineStatus(statusRes.value.data);
      }
    } catch (err) {
      console.error('Training panel fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial REST fetch only (WebSocket handles subsequent updates for regime + status)
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleStartTraining = useCallback(async () => {
    try {
      setStarting(true);
      const res = await api.post('/api/ai-training/start', {});
      if (res.data?.success) {
        toast.success('Training pipeline started');
        fetchData();
      } else {
        toast.error(res.data?.error || 'Failed to start training');
      }
    } catch (err) {
      toast.error('Failed to start training pipeline');
    } finally {
      setStarting(false);
    }
  }, [fetchData]);

  const handleStopTraining = useCallback(async () => {
    try {
      const res = await api.post('/api/ai-training/stop');
      if (res.data?.success) {
        toast.success('Training stopped');
        fetchData();
      }
    } catch (err) {
      toast.error('Failed to stop training');
    }
  }, [fetchData]);

  const regimeStyle = REGIME_COLORS[regime?.regime] || REGIME_COLORS.unknown;
  const isTraining = pipelineStatus?.task_status === 'running';
  const pipelinePhase = pipelineStatus?.pipeline_status?.phase;

  return (
    <div className="mt-6" data-testid="training-pipeline-panel">
      {/* Section Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-cyan-400" />
          <h2 className="text-base font-semibold text-white">AI Training Pipeline</h2>
        </div>
        <div className="flex items-center gap-2">
          {isTraining ? (
            <button
              onClick={handleStopTraining}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-xs text-red-400 transition-colors"
              data-testid="stop-training-btn"
            >
              <Square className="w-3 h-3" /> Stop Training
            </button>
          ) : (
            <button
              onClick={handleStartTraining}
              disabled={starting}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-xs text-emerald-400 transition-colors"
              data-testid="start-training-btn"
            >
              <Play className="w-3 h-3" /> {starting ? 'Starting...' : 'Start Training'}
            </button>
          )}
          <button
            onClick={fetchData}
            className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-400 transition-colors"
            data-testid="refresh-training-btn"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Training Status Banner */}
      {isTraining && pipelinePhase && (
        <div className="mb-4 p-3 rounded-lg border border-cyan-500/20 bg-cyan-500/5 flex items-center gap-3" data-testid="training-status-banner">
          <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
          <div>
            <span className="text-sm text-white">Training in progress</span>
            <span className="text-xs text-zinc-400 ml-2">Phase: {pipelinePhase}</span>
            {pipelineStatus?.pipeline_status?.current_model && (
              <span className="text-xs text-cyan-400 ml-2 font-mono">{pipelineStatus.pipeline_status.current_model}</span>
            )}
          </div>
          <div className="ml-auto text-xs text-zinc-400">
            {pipelineStatus?.pipeline_status?.models_completed || 0}/{pipelineStatus?.pipeline_status?.models_total || '?'} models
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left Column: Live Regime */}
        <div className="lg:col-span-1 space-y-3">
          {/* Regime Badge */}
          <div className={`p-4 rounded-lg border ${regimeStyle.border} ${regimeStyle.bg}`} data-testid="regime-badge">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-zinc-400 uppercase tracking-wider">Market Regime</span>
              <span className={`text-sm font-bold ${regimeStyle.text}`}>
                {regimeStyle.label}
              </span>
            </div>
            {regime?.regime === 'bull_trend' && <TrendingUp className={`w-8 h-8 ${regimeStyle.text} opacity-30 absolute top-2 right-2`} />}
            {regime?.regime === 'bear_trend' && <TrendingDown className={`w-8 h-8 ${regimeStyle.text} opacity-30 absolute top-2 right-2`} />}

            {/* Index Cards */}
            <div className="space-y-2">
              {regime?.indexes && Object.entries(regime.indexes).map(([name, data]) => (
                <IndexCard key={name} name={name} data={data} />
              ))}
            </div>

            {/* Cross-Correlations */}
            {regime?.cross && (
              <div className="mt-3 pt-3 border-t border-white/5 space-y-1.5">
                <span className="text-xs text-zinc-500 uppercase tracking-wider">Correlations & Rotation</span>
                <div className="grid grid-cols-2 gap-1.5 mt-1">
                  {[
                    { label: 'SPY-QQQ', value: regime.cross.spy_qqq_corr },
                    { label: 'SPY-IWM', value: regime.cross.spy_iwm_corr },
                    { label: 'QQQ-IWM', value: regime.cross.qqq_iwm_corr },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-white/[0.02]">
                      <span className="text-zinc-500">{label}</span>
                      <span className={`font-mono ${value > 0.7 ? 'text-emerald-400' : value < 0.3 ? 'text-red-400' : 'text-amber-400'}`}>
                        {value?.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="space-y-1 mt-2">
                  {[
                    { label: 'Growth vs Market', key: 'rotation_qqq_spy', desc: 'QQQ-SPY' },
                    { label: 'Small vs Large', key: 'rotation_iwm_spy', desc: 'IWM-SPY' },
                    { label: 'Growth vs Value', key: 'rotation_qqq_iwm', desc: 'QQQ-IWM' },
                  ].map(({ label, key, desc }) => {
                    const val = regime.cross[key] || 0;
                    return (
                      <div key={key} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-white/[0.02]">
                        <span className="text-zinc-500">{label}</span>
                        <span className={`font-mono ${val > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {val > 0 ? '+' : ''}{(val * 100).toFixed(2)}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Model Inventory */}
        <div className="lg:col-span-2 space-y-3">
          {/* Summary Bar */}
          {inventory && (
            <div className="flex items-center gap-4 p-3 rounded-lg border border-white/5 bg-white/[0.02]" data-testid="model-summary">
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-zinc-400">Models Trained</span>
                  <span className="text-sm font-mono text-white">{inventory.total_trained} / {inventory.total_defined}</span>
                </div>
                <MetricBar value={inventory.total_trained} max={inventory.total_defined} color="bg-emerald-500" />
              </div>
              {inventory.total_trained === 0 && (
                <div className="flex items-center gap-1.5 text-xs text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>No models trained yet</span>
                </div>
              )}
            </div>
          )}

          {/* Category List */}
          <div className="space-y-2" data-testid="model-categories">
            {inventory?.categories && Object.entries(inventory.categories).map(([key, cat]) => (
              <CategoryRow key={key} categoryKey={key} category={cat} />
            ))}
          </div>

          {/* Recent Training Results */}
          {pipelineStatus?.last_result && (
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
    </div>
  );
});

export default TrainingPipelinePanel;
