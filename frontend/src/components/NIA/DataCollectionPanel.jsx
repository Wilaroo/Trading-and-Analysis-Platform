import React, { useState, useEffect, useRef, memo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Database, Download, Zap, TrendingUp, Layers,
  ChevronUp, ChevronDown, Globe, Loader, RefreshCw,
  AlertTriangle, CheckCircle, Clock, Play, Square,
  Calendar, BarChart3, XCircle
} from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../../utils/api';
import { useWsData } from '../../contexts/WebSocketDataContext';

const TIER_META = {
  intraday: { icon: Zap, label: 'Intraday', adv: '500K+ ADV', borderClass: 'border-cyan-500/10', bgClass: 'bg-cyan-500/[0.02]', iconClass: 'text-cyan-400', barClass: 'bg-cyan-500' },
  swing: { icon: TrendingUp, label: 'Swing', adv: '100K-500K ADV', borderClass: 'border-violet-500/10', bgClass: 'bg-violet-500/[0.02]', iconClass: 'text-violet-400', barClass: 'bg-violet-500' },
  investment: { icon: Layers, label: 'Investment', adv: '50K-100K ADV', borderClass: 'border-amber-500/10', bgClass: 'bg-amber-500/[0.02]', iconClass: 'text-amber-400', barClass: 'bg-amber-500' },
};

const formatBars = (n) => {
  if (!n) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
};

const formatDate = (d) => {
  if (!d) return '--';
  try {
    const date = new Date(d);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    const mo = date.toLocaleString('en', { month: 'short' });
    const yr = date.getFullYear();
    if (yr === now.getFullYear()) return `${mo} ${date.getDate()}`;
    return `${mo} ${yr}`;
  } catch { return d?.slice(0, 10) || '--'; }
};

const DataCollectionPanel = memo(({ onRefresh, embedded = false }) => {
  const [expanded, setExpanded] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [dataCoverage, setDataCoverage] = useState(null);
  const [loadingCoverage, setLoadingCoverage] = useState(true);
  const [collectionMode, setCollectionMode] = useState(null);
  const [priorityCollection, setPriorityCollection] = useState(false);
  const [pendingRequests, setPendingRequests] = useState(0);
  const [detailedProgress, setDetailedProgress] = useState({ by_bar_size: [], active_collections: [] });
  const lastDataRef = useRef(null);

  const { dataCollection: wsDataCollection } = useWsData();

  useEffect(() => {
    let isMounted = true;
    const fetchData = async () => {
      if (!isMounted) return;
      try {
        const [progressRes, coverageRes, collectionModeRes] = await Promise.allSettled([
          api.get('/api/ib-collector/queue-progress-detailed'),
          api.get('/api/ib-collector/data-coverage'),
          api.get('/api/ib/collection-mode/status')
        ]);
        if (!isMounted) return;

        if (progressRes.status === 'fulfilled' && progressRes.value.data?.success) {
          const data = progressRes.value.data;
          setDetailedProgress({
            by_bar_size: data.by_bar_size || [],
            active_collections: data.active_collections || [],
            overall: data.overall || {}
          });
        }
        if (coverageRes.status === 'fulfilled' && coverageRes.value.data?.success) {
          setDataCoverage(coverageRes.value.data);
        }
        if (collectionModeRes.status === 'fulfilled') {
          setCollectionMode(collectionModeRes.value.data);
        }
        try {
          const priorityRes = await api.get('/api/ib/priority-collection/status');
          if (priorityRes.data) {
            setPriorityCollection(priorityRes.data.priority_collection || false);
            setPendingRequests(priorityRes.data.queue?.pending || 0);
          }
        } catch {}
      } catch (err) {
        console.error('Error fetching collection data:', err);
      } finally {
        if (isMounted) setLoadingCoverage(false);
      }
    };
    fetchData();
    return () => { isMounted = false; };
  }, []);

  useEffect(() => {
    if (!wsDataCollection) return;
    if (wsDataCollection.progress) {
      const p = wsDataCollection.progress;
      setDetailedProgress({
        by_bar_size: p.by_bar_size || [],
        active_collections: p.active_collections || [],
        overall: p.overall || {}
      });
    }
    if (wsDataCollection.coverage) {
      setDataCoverage(prev => ({ ...prev, ...wsDataCollection.coverage }));
    }
    setLoadingCoverage(false);
  }, [wsDataCollection]);

  const hasActiveCollections = detailedProgress.active_collections?.length > 0;
  const queueActive = collectionMode?.queue?.pending > 0;
  const isRunning = hasActiveCollections || queueActive;

  // "Collect Data" — single super-button that runs smart_backfill:
  //   • Reads symbol_adv_cache (dollar-volume tiers)
  //   • For every (symbol, bar_size) required by the tier:
  //       - skip if newest bar is within freshness_days
  //       - otherwise chain requests walking back in time to max IB lookback
  //   • Dedupes against currently pending/claimed queue items
  // Replaces the old fill-gaps + incremental-update dual-button pattern.
  const handleCollectData = useCallback(async () => {
    setCollecting(true);
    toast.info('Scanning tier-aware gaps & chaining lookbacks... this can take a minute.');
    try {
      const params = new URLSearchParams({ dry_run: 'false', freshness_days: '2' });
      const res = await api.post(`/api/ib-collector/smart-backfill?${params}`, null, { timeout: 600000 });
      if (res.data?.success) {
        const queued = res.data.queued ?? 0;
        const skippedFresh = res.data.skipped_fresh ?? 0;
        const skippedQueued = res.data.skipped_already_queued ?? 0;
        if (queued === 0) {
          toast.success(`Everything is fresh — ${skippedFresh} combos already up-to-date, ${skippedQueued} already queued.`);
        } else {
          const tierSum = res.data.tier_counts
            ? Object.entries(res.data.tier_counts).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`).join(' · ')
            : '';
          toast.success(`Queued ${queued} chained requests · ${tierSum} · skipped ${skippedFresh} fresh / ${skippedQueued} already queued`);
          setPriorityCollection(true);
        }
        if (onRefresh) onRefresh();
      } else {
        toast.error(res.data?.error || 'Smart backfill failed');
      }
    } catch (err) {
      if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
        toast.info('Smart backfill is still running in the background. Collectors will pick up work as it queues.');
      } else {
        toast.error('Error running smart backfill: ' + (err?.response?.data?.detail || err.message));
      }
    } finally {
      setCollecting(false);
    }
  }, [onRefresh]);

  const handleCancel = useCallback(async () => {
    setCancelling(true);
    try {
      const res = await api.post('/api/ib-collector/cancel-all-pending');
      if (res.data?.success) {
        toast.info(`Cancelled ${res.data.cancelled} pending requests`);
        if (onRefresh) onRefresh();
      }
    } catch {
      toast.error('Error cancelling');
    } finally {
      setCancelling(false);
    }
  }, [onRefresh]);

  const totalBars = dataCoverage?.by_timeframe?.reduce((s, t) => s + (t.total_bars || 0), 0) || 0;
  const totalSymbols = dataCoverage?.adv_cache?.total_symbols || 0;
  const totalGaps = dataCoverage?.total_gaps || 0;
  const queue = collectionMode?.queue;

  const content = (
    <>
      {/* Header Row: Action button + stats */}
      <div className="flex items-center gap-3 flex-wrap" data-testid="collection-header">
        <button
          onClick={handleCollectData}
          disabled={collecting || hasActiveCollections}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all flex items-center gap-2
            ${collecting || hasActiveCollections
              ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
              : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400 shadow-lg shadow-cyan-500/20'
            }`}
          data-testid="collect-data-btn"
          title="Smart Backfill: tier-aware, gap-aware, chained lookback. Queues only what's missing or stale, walking back to IB's max lookback per bar size."
        >
          {collecting ? <><Loader className="w-4 h-4 animate-spin" /> Starting...</> : <><Play className="w-4 h-4" /> Collect Data</>}
        </button>

        {isRunning && (
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="px-3 py-2.5 rounded-lg text-sm font-medium bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20 transition-colors flex items-center gap-1.5 disabled:opacity-50"
            data-testid="cancel-collection-btn"
          >
            {cancelling ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
            Stop
          </button>
        )}

        <div className="flex items-center gap-4 ml-auto text-xs">
          <span className="text-zinc-500">{totalSymbols.toLocaleString()} symbols</span>
          <span className="text-zinc-500">{formatBars(totalBars)} bars</span>
          {totalGaps > 0 && (
            <span className="text-amber-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {totalGaps} gaps</span>
          )}
          {totalGaps === 0 && totalSymbols > 0 && (
            <span className="text-emerald-400 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Complete</span>
          )}
          <button onClick={onRefresh} className="p-1.5 rounded hover:bg-white/5 text-zinc-500 hover:text-zinc-300 transition-colors" data-testid="refresh-coverage-btn">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Collection Progress (when active) */}
      {isRunning && queue && (
        <CollectionProgress queue={queue} collectionMode={collectionMode} detailedProgress={detailedProgress} priorityCollection={priorityCollection} />
      )}

      {/* Loading state */}
      {loadingCoverage && (
        <div className="flex items-center justify-center py-8"><Loader className="w-5 h-5 text-cyan-400 animate-spin" /></div>
      )}

      {/* Tier Breakdown */}
      {!loadingCoverage && dataCoverage?.by_tier && (
        <div className="space-y-3" data-testid="tier-breakdown">
          {dataCoverage.by_tier.map((tier) => (
            <TierSection key={tier.tier} tier={tier} progressByBarSize={detailedProgress.by_bar_size} />
          ))}
        </div>
      )}

      {/* No data state */}
      {!loadingCoverage && totalSymbols === 0 && (
        <div className="text-center py-6 text-zinc-500 text-sm">
          <Database className="w-8 h-8 mx-auto mb-2 text-zinc-700" />
          No symbols in ADV cache. Click <span className="text-cyan-400">Collect Data</span> to start.
        </div>
      )}
    </>
  );

  if (embedded) return <div className="space-y-4 mt-3">{content}</div>;

  return (
    <div className="bg-gradient-to-br from-zinc-900/80 to-black/60 rounded-2xl border border-white/10 overflow-hidden mb-4" data-testid="data-collection-panel">
      <div
        className="flex items-center justify-between px-4 py-3 border-b border-white/10 cursor-pointer hover:bg-white/5 transition-colors"
        onClick={() => setExpanded(!expanded)}
        data-testid="data-collection-panel-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 flex items-center justify-center border border-blue-500/30">
            <Database className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Historical Data Collection</h3>
            <p className="text-[10px] text-zinc-500">Smart gap-fill with max IB lookback &bull; Per-stock chaining</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isRunning && <span className="px-2 py-1 rounded-full bg-cyan-500/20 text-cyan-400 text-[10px] font-medium animate-pulse">COLLECTING</span>}
          {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
        </div>
      </div>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="p-4 space-y-4"
          >
            {content}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

/* ===== Collection Progress Bar ===== */
const CollectionProgress = memo(({ queue, collectionMode, detailedProgress, priorityCollection }) => {
  const pct = queue.progress_pct || 0;
  const rate = collectionMode?.collection_mode?.rate_per_hour || 0;
  const pending = queue.pending || 0;
  const completed = queue.completed || 0;
  const total = queue.total || 0;
  const eta = rate > 0 ? Math.round(pending / rate) : null;

  return (
    <div className="p-3 rounded-xl bg-gradient-to-r from-cyan-500/5 to-blue-500/5 border border-cyan-500/20" data-testid="collection-progress">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Download className="w-4 h-4 text-cyan-400 animate-pulse" />
          <span className="text-xs font-medium text-cyan-400">
            {collectionMode?.collection_mode?.active ? 'Collecting' : 'Script Processing'}
          </span>
          {priorityCollection && <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-[9px] text-amber-400 font-medium">PRIORITY</span>}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-zinc-400">
          {rate > 0 && <span>{Math.round(rate)}/hr</span>}
          {eta !== null && <span>ETA: ~{eta < 1 ? '<1' : eta}h</span>}
          <span className="text-cyan-400 font-mono">{pct}%</span>
        </div>
      </div>
      <div className="h-2 bg-black/50 rounded-full overflow-hidden">
        <div className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex items-center justify-between mt-1.5 text-[10px] text-zinc-500">
        <span>{completed.toLocaleString()} / {total.toLocaleString()} requests</span>
        <span>{pending.toLocaleString()} remaining</span>
      </div>

      {/* Per-timeframe mini progress */}
      {detailedProgress.by_bar_size?.length > 0 && (
        <div className="mt-3 pt-2 border-t border-white/5 grid grid-cols-2 md:grid-cols-4 gap-2">
          {detailedProgress.by_bar_size.map((bs, i) => {
            const bsPct = bs.progress_pct || 0;
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="text-[10px] text-zinc-500 w-12 truncate">{bs.bar_size}</span>
                <div className="flex-1 h-1 bg-black/40 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all ${bsPct >= 90 ? 'bg-emerald-500' : bsPct >= 50 ? 'bg-cyan-500' : 'bg-amber-500'}`} style={{ width: `${bsPct}%` }} />
                </div>
                <span className={`text-[9px] font-mono ${bsPct >= 90 ? 'text-emerald-400' : 'text-zinc-500'}`}>{bsPct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

/* ===== Tier Section ===== */
const TierSection = memo(({ tier, progressByBarSize }) => {
  const meta = TIER_META[tier.tier] || { icon: Globe, label: tier.tier, adv: '', borderClass: 'border-zinc-500/10', bgClass: 'bg-zinc-500/[0.02]', iconClass: 'text-zinc-400', barClass: 'bg-zinc-500' };
  const Icon = meta.icon;
  const tierBars = tier.timeframes.reduce((s, tf) => s + (tf.total_bars || 0), 0);
  const allCovered = tier.timeframes.every(tf => tf.coverage_pct >= 100);

  // Build progress lookup
  const progressLookup = {};
  (progressByBarSize || []).forEach(p => { progressLookup[p.bar_size] = p; });

  return (
    <div className={`rounded-xl border ${meta.borderClass} ${meta.bgClass} overflow-hidden`} data-testid={`tier-${tier.tier}`}>
      {/* Tier Header */}
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <Icon className={`w-4 h-4 ${meta.iconClass}`} />
          <span className="text-sm font-semibold text-white">{meta.label}</span>
          <span className="text-[10px] text-zinc-500">{meta.adv}</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-zinc-400">{tier.total_symbols} symbols</span>
          <span className="text-zinc-500">{formatBars(tierBars)} bars</span>
          {allCovered && <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />}
        </div>
      </div>

      {/* Timeframe Rows */}
      <div className="border-t border-white/5">
        {tier.timeframes.map((tf) => (
          <TimeframeRow key={tf.timeframe} tf={tf} barColorClass={meta.barClass} progress={progressLookup[tf.timeframe]} />
        ))}
      </div>
    </div>
  );
});

/* ===== Timeframe Row ===== */
const TimeframeRow = memo(({ tf, barColorClass, progress }) => {
  const pct = tf.coverage_pct || 0;
  const isComplete = pct >= 100;
  const isCollecting = progress?.is_active;
  const barColor = isComplete ? 'bg-emerald-500' : pct >= 75 ? barColorClass : pct >= 25 ? 'bg-amber-500' : 'bg-rose-500';

  return (
    <div className={`flex items-center gap-3 px-4 py-2 border-b border-white/[0.03] last:border-b-0 hover:bg-white/[0.02] transition-colors ${isCollecting ? 'bg-cyan-500/[0.03]' : ''}`} data-testid={`tf-row-${tf.timeframe.replace(/\s/g, '-')}`}>
      {/* Timeframe label */}
      <div className="w-16 flex-shrink-0">
        <span className="text-xs font-mono text-white">{tf.timeframe}</span>
        {isCollecting && <span className="ml-1 w-1.5 h-1.5 rounded-full bg-cyan-400 inline-block animate-pulse" />}
      </div>

      {/* Progress bar */}
      <div className="flex-1 max-w-[200px]">
        <div className="h-2 bg-black/40 rounded-full overflow-hidden">
          <div className={`h-full ${barColor} transition-all duration-500 rounded-full`} style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      </div>

      {/* Coverage fraction */}
      <div className="w-20 text-right flex-shrink-0">
        <span className={`text-xs font-mono ${isComplete ? 'text-emerald-400' : 'text-zinc-300'}`}>
          {tf.symbols_with_data}/{tf.symbols_needed}
        </span>
      </div>

      {/* Bars */}
      <div className="w-16 text-right flex-shrink-0">
        <span className="text-[10px] text-zinc-500 font-mono">{formatBars(tf.total_bars)}</span>
      </div>

      {/* Date range */}
      <div className="w-36 flex-shrink-0 text-right">
        {tf.earliest_date ? (
          <span className="text-[10px] text-zinc-500">
            <Calendar className="w-2.5 h-2.5 inline mr-0.5 opacity-50" />
            {formatDate(tf.earliest_date)} <span className="text-zinc-600 mx-0.5">&rarr;</span> {formatDate(tf.latest_date)}
          </span>
        ) : (
          <span className="text-[10px] text-zinc-600">No data</span>
        )}
      </div>

      {/* Collection progress for this timeframe */}
      {progress && progress.pending > 0 && (
        <div className="w-16 flex-shrink-0 text-right">
          <span className="text-[9px] text-cyan-400 font-mono">{progress.progress_pct || 0}%</span>
        </div>
      )}
    </div>
  );
});

export default DataCollectionPanel;
