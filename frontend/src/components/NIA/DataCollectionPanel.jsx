import React, { useState, useEffect, useRef, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Database, Download, Zap, TrendingUp, Layers,
  ChevronUp, ChevronDown, Globe, Loader, RefreshCw,
  AlertTriangle, AlertCircle, CheckCircle, Clock, Play
} from 'lucide-react';
import { toast } from 'sonner';
import DataHeatmap from './DataHeatmap';
import api from '../../utils/api';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

const DataCollectionPanel = memo(({ onRefresh, embedded = false }) => {
  const [expanded, setExpanded] = useState(true);
  const [lookbackDays, setLookbackDays] = useState(30);
  const [tier, setTier] = useState('all');
  const [skipRecent, setSkipRecent] = useState(true);
  const [recentThreshold, setRecentThreshold] = useState(7);
  const [maxSymbols, setMaxSymbols] = useState(null);
  const [collecting, setCollecting] = useState(false);
  const [activeTab, setActiveTab] = useState('coverage');

  const [detailedProgress, setDetailedProgress] = useState({ by_bar_size: [], active_collections: [] });
  const [cancelling, setCancelling] = useState(false);
  const [dataCoverage, setDataCoverage] = useState(null);
  const [loadingCoverage, setLoadingCoverage] = useState(true);
  const [lastDataChange, setLastDataChange] = useState(null);
  const [collectionMode, setCollectionMode] = useState(null);
  const [priorityCollection, setPriorityCollection] = useState(false);
  const [pendingRequests, setPendingRequests] = useState(0);
  const [fillingGaps, setFillingGaps] = useState(false);

  const lastDataRef = useRef(null);

  const tierOptions = [
    { value: 'all', label: 'All Tiers', description: 'Intraday + Swing + Investment stocks', icon: Globe, adv: '50K+ shares/day', timeframes: 'All applicable per stock' },
    { value: 'intraday', label: 'Intraday', description: 'High volume day trading stocks', icon: Zap, adv: '500K+ shares/day', timeframes: '1min, 5min, 15min, 1hr, 1day' },
    { value: 'swing', label: 'Swing', description: 'Medium volume swing stocks', icon: TrendingUp, adv: '100K+ shares/day', timeframes: '5min, 30min, 1hr, 1day' },
    { value: 'investment', label: 'Investment', description: 'Lower volume position stocks', icon: Layers, adv: '50K+ shares/day', timeframes: '1hr, 1day, 1week' }
  ];

  const lookbackPresets = [
    { value: 5, label: '5 Days' },
    { value: 30, label: '30 Days' },
    { value: 90, label: '90 Days' },
    { value: 180, label: '6 Months' },
    { value: 365, label: '1 Year' }
  ];

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
          const newProgress = {
            by_bar_size: data.by_bar_size || [],
            active_collections: data.active_collections || [],
            overall: data.overall || {}
          };
          const newProgressStr = JSON.stringify(newProgress);
          if (lastDataRef.current?.progress !== newProgressStr) {
            lastDataRef.current = { ...lastDataRef.current, progress: newProgressStr };
            setDetailedProgress(newProgress);
          }
        }

        if (coverageRes.status === 'fulfilled' && coverageRes.value.data?.success) {
          const data = coverageRes.value.data;
          const newCoverageStr = JSON.stringify(data);
          if (lastDataRef.current?.coverage !== newCoverageStr) {
            lastDataRef.current = { ...lastDataRef.current, coverage: newCoverageStr };
            setDataCoverage(data);
            setLastDataChange(new Date());
          }
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
        } catch (err) {
          console.debug('Could not fetch priority status:', err);
        }
      } catch (err) {
        console.error('Error fetching collection data:', err);
      } finally {
        if (isMounted) setLoadingCoverage(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => { isMounted = false; clearInterval(interval); };
  }, []);

  const hasActiveCollections = detailedProgress.active_collections?.length > 0;

  const startCollection = async () => {
    setCollecting(true);
    try {
      const params = new URLSearchParams({
        lookback_days: lookbackDays.toString(),
        skip_recent: skipRecent.toString(),
        recent_days_threshold: recentThreshold.toString()
      });
      if (maxSymbols) params.append('max_symbols', maxSymbols.toString());

      const res = await api.post(`/api/ib-collector/per-stock-collection?${params}`);
      if (res.data?.success) {
        toast.success(`Collection started: ${res.data.symbols} symbols, ${res.data.total_requests} requests queued`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(res.data?.error || 'Failed to start collection');
      }
    } catch (err) {
      toast.error('Error starting collection');
    } finally {
      setCollecting(false);
    }
  };

  const handleCancelAll = async () => {
    setCancelling(true);
    try {
      const res = await api.post('/api/ib-collector/cancel-all-pending');
      if (res.data?.success) {
        toast.info(`Cancelled ${res.data.cancelled} pending requests`);
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      toast.error('Error cancelling');
    } finally {
      setCancelling(false);
    }
  };

  const handleFillGaps = async () => {
    setFillingGaps(true);
    try {
      const params = new URLSearchParams({ use_max_lookback: 'true', enable_priority: 'true' });
      if (tier !== 'all') params.append('tier_filter', tier);

      const res = await api.post(`/api/ib-collector/fill-gaps?${params}`);
      if (res.data?.success) {
        if (res.data.gaps_found === 0) {
          toast.success('No gaps found! Your data coverage is complete.');
        } else {
          const priorityMsg = res.data.priority_collection ? ' Priority mode enabled for faster collection.' : '';
          toast.success(`Started filling ${res.data.gaps_found} gaps across ${res.data.total_unique_symbols} symbols.${priorityMsg}`);
          if (res.data.priority_collection) setPriorityCollection(true);
          setActiveTab('progress');
        }
        if (onRefresh) onRefresh();
      } else {
        toast.error(res.data?.error || 'Failed to start gap fill');
      }
    } catch (err) {
      toast.error('Error starting gap fill');
    } finally {
      setFillingGaps(false);
    }
  };

  const handleTogglePriority = async () => {
    try {
      const endpoint = priorityCollection
        ? '/api/ib/priority-collection/disable'
        : '/api/ib/priority-collection/enable';
      const res = await api.post(endpoint);
      if (res.data?.success) {
        setPriorityCollection(res.data.priority_collection);
        toast.success(res.data.message);
      } else {
        toast.error('Failed to toggle priority collection');
      }
    } catch (err) {
      toast.error('Error toggling priority');
    }
  };

  const estimatedTime = () => {
    const requestsPerSymbol = tier === 'intraday' ? 5 : tier === 'swing' ? 4 : tier === 'investment' ? 3 : 4;
    const symbolCount = maxSymbols || 500;
    const totalRequests = symbolCount * requestsPerSymbol;
    const hours = (totalRequests * 3) / 3600;
    return hours < 1 ? `~${Math.round(hours * 60)} mins` : `~${hours.toFixed(1)} hours`;
  };

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
            <p className="text-[10px] text-zinc-500">Per-stock multi-timeframe &bull; Smart ADV filtering</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hasActiveCollections && (
            <span className="px-2 py-1 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-medium animate-pulse">WEB COLLECTING</span>
          )}
          {!hasActiveCollections && collectionMode?.queue?.pending > 0 && (
            <span className="px-2 py-1 rounded-full bg-cyan-500/20 text-cyan-400 text-[10px] font-medium animate-pulse">SCRIPT ACTIVE</span>
          )}
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
          >
            {/* Collection Mode Banner */}
            {collectionMode?.collection_mode?.active && (
              <div className="mx-3 mt-3 p-3 rounded-xl bg-gradient-to-r from-amber-500/20 to-orange-500/20 border border-amber-500/30">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/30 flex items-center justify-center animate-pulse">
                    <Download className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-amber-400">DATA COLLECTION ACTIVE</span>
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/30 text-[9px] text-emerald-300 font-medium">TRADING CONTINUES</span>
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-[10px] text-zinc-400">
                      <span>Completed: <span className="text-emerald-400 font-medium">{collectionMode.collection_mode.completed?.toLocaleString() || 0}</span></span>
                      <span>Rate: <span className="text-cyan-400 font-medium">{Math.round(collectionMode.collection_mode.rate_per_hour || 0)}/hr</span></span>
                      <span>Running: <span className="text-zinc-300">{Math.round(collectionMode.collection_mode.elapsed_minutes || 0)} min</span></span>
                    </div>
                    {collectionMode.queue && (
                      <div className="mt-2">
                        <div className="flex items-center justify-between text-[10px] mb-1">
                          <span className="text-zinc-500">Progress</span>
                          <span className="text-zinc-400">{collectionMode.queue.progress_pct}%</span>
                        </div>
                        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                          <div className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all duration-500" style={{ width: `${collectionMode.queue.progress_pct || 0}%` }} />
                        </div>
                        <div className="flex items-center justify-between text-[9px] text-zinc-500 mt-1">
                          <span>{collectionMode.queue.completed?.toLocaleString()} / {collectionMode.queue.total?.toLocaleString()}</span>
                          <span>{collectionMode.queue.pending?.toLocaleString()} remaining</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Priority Collection Status */}
            <div className="mx-3 mt-3 p-3 rounded-xl bg-gradient-to-r from-zinc-900/80 to-black/80 border border-white/10">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${priorityCollection ? 'bg-amber-500/20 border border-amber-500/30' : 'bg-emerald-500/20 border border-emerald-500/30'}`}>
                    {priorityCollection ? <Download className="w-4 h-4 text-amber-400" /> : <Zap className="w-4 h-4 text-emerald-400" />}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-white">{priorityCollection ? 'Priority Collection' : 'Normal Trading'}</span>
                      {priorityCollection && (
                        <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-[9px] text-amber-400 font-medium animate-pulse">FAST MODE</span>
                      )}
                    </div>
                    <p className="text-[10px] text-zinc-500">
                      {priorityCollection
                        ? `Prioritizing historical data \u2022 ${pendingRequests.toLocaleString()} pending \u2022 Auto-disables when done`
                        : 'Live quotes active \u2022 Background collection at low priority'}
                    </p>
                  </div>
                </div>
                {pendingRequests > 0 && (
                  <button
                    onClick={handleTogglePriority}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-medium transition-all ${priorityCollection ? 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 border border-zinc-700' : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 border border-amber-500/30'}`}
                  >
                    {priorityCollection ? 'Slow Down' : 'Speed Up'}
                  </button>
                )}
              </div>
            </div>

            {/* Tab Navigation */}
            <div className="flex border-b border-white/10 mt-1">
              {['coverage', 'collect', 'progress'].map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${activeTab === tab ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5' : 'text-zinc-500 hover:text-zinc-300'}`}
                  data-testid={`collection-tab-${tab}`}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  {tab === 'progress' && hasActiveCollections && <span className="ml-1 w-2 h-2 bg-amber-400 rounded-full inline-block animate-pulse" />}
                </button>
              ))}
            </div>

            <div className="p-4">
              {activeTab === 'coverage' ? (
                <CoverageTab
                  loadingCoverage={loadingCoverage}
                  dataCoverage={dataCoverage}
                  lastDataChange={lastDataChange}
                  detailedProgress={detailedProgress}
                  fillingGaps={fillingGaps}
                  hasActiveCollections={hasActiveCollections}
                  onFillGaps={handleFillGaps}
                  onRefresh={onRefresh}
                />
              ) : activeTab === 'progress' ? (
                <ProgressTab
                  collectionMode={collectionMode}
                  detailedProgress={detailedProgress}
                  hasActiveCollections={hasActiveCollections}
                  cancelling={cancelling}
                  onCancelAll={handleCancelAll}
                />
              ) : (
                <CollectTab
                  lookbackDays={lookbackDays}
                  setLookbackDays={setLookbackDays}
                  lookbackPresets={lookbackPresets}
                  tier={tier}
                  setTier={setTier}
                  tierOptions={tierOptions}
                  skipRecent={skipRecent}
                  setSkipRecent={setSkipRecent}
                  recentThreshold={recentThreshold}
                  setRecentThreshold={setRecentThreshold}
                  maxSymbols={maxSymbols}
                  setMaxSymbols={setMaxSymbols}
                  estimatedTime={estimatedTime}
                  collecting={collecting}
                  hasActiveCollections={hasActiveCollections}
                  onStartCollection={startCollection}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

/* ===== Coverage Sub-Tab ===== */
const CoverageTab = memo(({ loadingCoverage, dataCoverage, lastDataChange, detailedProgress, fillingGaps, hasActiveCollections, onFillGaps, onRefresh }) => {
  if (loadingCoverage) {
    return <div className="flex items-center justify-center py-8"><Loader className="w-6 h-6 text-cyan-400 animate-spin" /></div>;
  }
  if (!dataCoverage) {
    return (
      <div className="text-center py-8">
        <AlertCircle className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
        <p className="text-zinc-500 text-sm">Could not load coverage data</p>
        <p className="text-zinc-600 text-xs mt-1">Make sure the backend is running</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Heatmap Visual */}
      <DataHeatmap dataCoverage={dataCoverage} queueProgress={{ by_bar_size: detailedProgress.by_bar_size }} />

      {/* Action Buttons */}
      <div className="flex gap-2">
        {dataCoverage.total_gaps > 0 && (
          <button
            onClick={onFillGaps}
            disabled={fillingGaps || hasActiveCollections}
            className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 text-emerald-400 text-xs font-medium hover:from-emerald-500/30 hover:to-cyan-500/30 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            data-testid="fill-gaps-btn"
          >
            {fillingGaps ? <><Loader className="w-3 h-3 animate-spin" /> Starting...</> : <><Zap className="w-3 h-3" /> Fill Gaps ({dataCoverage.total_gaps})</>}
          </button>
        )}
        <button
          onClick={onRefresh}
          className={`${dataCoverage.total_gaps > 0 ? 'flex-1' : 'w-full'} py-2 rounded-lg bg-white/5 border border-white/10 text-zinc-400 text-xs font-medium hover:bg-white/10 transition-colors flex items-center justify-center gap-2`}
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      {dataCoverage.total_gaps === 0 && dataCoverage.adv_cache?.total_symbols > 0 && (
        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-center">
          <CheckCircle className="w-6 h-6 text-emerald-400 mx-auto mb-2" />
          <p className="text-xs text-emerald-400 font-medium">Data coverage complete!</p>
          <p className="text-[10px] text-zinc-500 mt-1">All tiers and timeframes have data</p>
        </div>
      )}

      {dataCoverage.adv_cache?.total_symbols === 0 && (
        <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-center">
          <Database className="w-6 h-6 text-amber-400 mx-auto mb-2" />
          <p className="text-xs text-amber-400 font-medium">No symbols in ADV cache</p>
          <p className="text-[10px] text-zinc-500 mt-1">Run a data collection from the "Collect" tab to populate the cache</p>
        </div>
      )}
    </div>
  );
});

/* ===== Progress Sub-Tab ===== */
const ProgressTab = memo(({ collectionMode, detailedProgress, hasActiveCollections, cancelling, onCancelAll }) => (
  <div className="space-y-4">
    <div className="p-3 rounded-xl bg-gradient-to-r from-zinc-900 to-black border border-white/10">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-zinc-400">Collection Queue Status</span>
        <div className="flex items-center gap-2">
          {collectionMode?.queue?.pending > 0 && !collectionMode?.collection_mode?.active && (
            <span className="px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-[10px] font-medium animate-pulse">SCRIPT COLLECTING</span>
          )}
          {collectionMode?.collection_mode?.active && (
            <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-medium animate-pulse">WEB COLLECTING</span>
          )}
        </div>
      </div>
      {collectionMode?.queue && (
        <>
          <div className="grid grid-cols-4 gap-2 mb-3">
            {[
              { val: collectionMode.queue.completed, label: 'Completed', color: 'text-emerald-400' },
              { val: collectionMode.queue.pending, label: 'Pending', color: 'text-amber-400' },
              { val: collectionMode.queue.failed || 0, label: 'Failed', color: 'text-rose-400' },
              { val: `${collectionMode.queue.progress_pct}%`, label: 'Complete', color: 'text-cyan-400' },
            ].map((s) => (
              <div key={s.label} className="text-center p-2 rounded-lg bg-black/40">
                <p className={`text-lg font-bold ${s.color}`}>{typeof s.val === 'number' ? s.val?.toLocaleString() : s.val}</p>
                <p className="text-[9px] text-zinc-500">{s.label}</p>
              </div>
            ))}
          </div>
          <div className="h-2 bg-black/50 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all duration-500" style={{ width: `${collectionMode.queue.progress_pct || 0}%` }} />
          </div>
          {collectionMode?.queue?.pending > 0 && (
            <div className="flex items-center justify-between mt-2 text-[10px] text-zinc-500">
              {collectionMode?.collection_mode?.active && collectionMode.collection_mode.rate_per_hour > 0 ? (
                <>
                  <span>Rate: {Math.round(collectionMode.collection_mode.rate_per_hour)}/hour</span>
                  <span>ETA: ~{Math.round(collectionMode.queue.pending / collectionMode.collection_mode.rate_per_hour)} hours</span>
                </>
              ) : (
                <>
                  <span className="text-cyan-400">Script collection active</span>
                  <span>~{Math.round(collectionMode.queue.pending / 360)} hours @ ~6/min</span>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>

    {detailedProgress.by_bar_size?.length > 0 && (
      <div>
        <p className="text-xs font-medium text-zinc-400 mb-2">Progress by Timeframe</p>
        <div className="space-y-2">
          {detailedProgress.by_bar_size.map((bs, i) => {
            const pct = bs.progress_pct || 0;
            const isActive = bs.is_active;
            return (
              <div key={i} className={`p-2 rounded-lg border ${isActive ? 'bg-black/40 border-cyan-500/20' : 'bg-black/20 border-white/5'}`}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-white">{bs.bar_size}</span>
                    {isActive && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />}
                  </div>
                  <div className="flex items-center gap-3 text-[10px]">
                    <span className="text-emerald-400">{bs.completed?.toLocaleString()} done</span>
                    {bs.pending > 0 && <span className="text-amber-400">{bs.pending?.toLocaleString()} pending</span>}
                    {bs.failed > 0 && <span className="text-rose-400">{bs.failed} failed</span>}
                    <span className={`font-medium ${pct >= 90 ? 'text-emerald-400' : pct >= 50 ? 'text-cyan-400' : 'text-amber-400'}`}>{pct}%</span>
                  </div>
                </div>
                <div className="h-1.5 bg-black/50 rounded-full overflow-hidden">
                  <div className={`h-full transition-all duration-300 ${pct >= 90 ? 'bg-emerald-500' : pct >= 50 ? 'bg-cyan-500' : 'bg-amber-500'}`} style={{ width: `${pct}%` }} />
                </div>
                {isActive && bs.eta_display && (
                  <div className="flex items-center justify-between mt-1 text-[9px] text-zinc-500">
                    <span>{bs.symbols_per_minute?.toFixed(1)} symbols/min</span>
                    <span>ETA: {bs.eta_display}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    )}

    {hasActiveCollections && (
      <button
        onClick={onCancelAll}
        disabled={cancelling}
        className="w-full py-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-medium hover:bg-rose-500/20 transition-colors disabled:opacity-50"
      >
        {cancelling ? 'Cancelling...' : 'Cancel Web Collections'}
      </button>
    )}

    {!collectionMode?.queue?.total && !detailedProgress.by_bar_size?.length && (
      <div className="text-center py-6">
        <CheckCircle className="w-8 h-8 text-emerald-500/50 mx-auto mb-2" />
        <p className="text-zinc-500 text-sm">No data collection queued</p>
        <p className="text-zinc-600 text-xs mt-1">Queue data from the "Collect" tab</p>
        <p className="text-zinc-600 text-xs">or run <code className="bg-black/40 px-1 rounded">StartCollection.bat</code> for full-speed mode</p>
      </div>
    )}
  </div>
));

/* ===== Collect Sub-Tab ===== */
const CollectTab = memo(({ lookbackDays, setLookbackDays, lookbackPresets, tier, setTier, tierOptions, skipRecent, setSkipRecent, recentThreshold, setRecentThreshold, maxSymbols, setMaxSymbols, estimatedTime, collecting, hasActiveCollections, onStartCollection }) => (
  <div className="space-y-4">
    <div>
      <label className="text-xs font-medium text-zinc-400 mb-2 block">Lookback Period</label>
      <div className="grid grid-cols-5 gap-2">
        {lookbackPresets.map(preset => (
          <button
            key={preset.value}
            onClick={() => setLookbackDays(preset.value)}
            className={`p-2 rounded-lg border text-center transition-all ${lookbackDays === preset.value ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400' : 'bg-black/30 border-white/10 text-zinc-400 hover:border-white/20'}`}
          >
            <p className="text-xs font-bold">{preset.label}</p>
          </button>
        ))}
      </div>
    </div>

    <div>
      <label className="text-xs font-medium text-zinc-400 mb-2 block">Symbol Filter (ADV Tier)</label>
      <div className="grid grid-cols-2 gap-2">
        {tierOptions.map(opt => (
          <button
            key={opt.value}
            onClick={() => setTier(opt.value)}
            className={`p-3 rounded-xl border text-left transition-all ${tier === opt.value ? 'bg-cyan-500/10 border-cyan-500/50' : 'bg-black/30 border-white/10 hover:border-white/20'}`}
          >
            <div className="flex items-center gap-2 mb-1">
              <opt.icon className={`w-4 h-4 ${tier === opt.value ? 'text-cyan-400' : 'text-zinc-500'}`} />
              <span className={`text-sm font-bold ${tier === opt.value ? 'text-cyan-400' : 'text-white'}`}>{opt.label}</span>
            </div>
            <p className="text-[10px] text-zinc-500">{opt.adv}</p>
            <p className="text-[9px] text-zinc-600 mt-1">{opt.timeframes}</p>
          </button>
        ))}
      </div>
    </div>

    <div className="p-3 rounded-xl bg-black/20 border border-white/5 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-white">Skip Recent Data</p>
          <p className="text-[10px] text-zinc-500">Don't re-fetch symbols collected within threshold</p>
        </div>
        <button
          onClick={() => setSkipRecent(!skipRecent)}
          className={`w-10 h-5 rounded-full transition-colors ${skipRecent ? 'bg-cyan-500' : 'bg-zinc-700'}`}
        >
          <div className={`w-4 h-4 rounded-full bg-white transition-transform ${skipRecent ? 'translate-x-5' : 'translate-x-0.5'}`} />
        </button>
      </div>
      {skipRecent && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-500">Threshold:</span>
          <select value={recentThreshold} onChange={(e) => setRecentThreshold(parseInt(e.target.value))} className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs text-white">
            <option value={1}>1 day</option><option value={3}>3 days</option><option value={7}>7 days</option><option value={14}>14 days</option><option value={30}>30 days</option>
          </select>
        </div>
      )}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-zinc-500">Max symbols:</span>
        <select value={maxSymbols || 'all'} onChange={(e) => setMaxSymbols(e.target.value === 'all' ? null : parseInt(e.target.value))} className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs text-white">
          <option value="all">All</option><option value={50}>50</option><option value={100}>100</option><option value={250}>250</option><option value={500}>500</option><option value={1000}>1000</option>
        </select>
      </div>
    </div>

    <div className="flex items-center justify-between p-3 rounded-xl bg-blue-500/5 border border-blue-500/20">
      <div className="flex items-center gap-2"><Clock className="w-4 h-4 text-blue-400" /><span className="text-xs text-blue-400">Estimated time:</span></div>
      <span className="text-sm font-bold text-blue-400">{estimatedTime()}</span>
    </div>

    <button
      onClick={onStartCollection}
      disabled={collecting || hasActiveCollections}
      className={`w-full py-3 rounded-xl font-medium text-sm transition-all ${collecting || hasActiveCollections ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed' : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400 shadow-lg shadow-cyan-500/20'}`}
      data-testid="start-collection-btn"
    >
      {collecting ? (
        <span className="flex items-center justify-center gap-2"><Loader className="w-4 h-4 animate-spin" /> Starting...</span>
      ) : hasActiveCollections ? (
        'Collection in progress...'
      ) : (
        <span className="flex items-center justify-center gap-2"><Play className="w-4 h-4" /> Start Per-Stock Collection</span>
      )}
    </button>

    <div className="p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
      <div className="flex items-start gap-2">
        <CheckCircle className="w-4 h-4 text-emerald-400 mt-0.5" />
        <div className="text-[10px] text-emerald-400/80">
          <p className="font-medium mb-1">Per-Stock Collection</p>
          <p>Each stock gets ALL its applicable timeframes collected before moving to the next. This ensures complete data for each symbol.</p>
        </div>
      </div>
    </div>
  </div>
));

export default DataCollectionPanel;
