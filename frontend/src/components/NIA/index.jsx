/**
 * NIA - Neural Intelligence Agency
 * =================================
 * The intelligence arm of SentCom. Gathers insights, analyzes AI performance,
 * tracks learning progress, and monitors strategy lifecycle.
 *
 * Refactored into modular components:
 * - IntelOverview: Key metrics at a glance (with connector health dots)
 * - LearningProgressPanel: System intelligence progress bars
 * - ReportCardPanel: Personal trading performance (moved up for visibility)
 * - DataCollectionPanel: Historical data collection with coverage/collect/progress tabs
 * - SimulationQuickPanel: Backtesting and simulations
 * - TestingToolsPanel: Market Scanner + Advanced Testing (merged, tabbed)
 * - AIModulesPanel: AI Performance + Learning Connectors (merged, tabbed)
 * - StrategyPipelinePanel: Lifecycle + Promotions (merged, tabbed, deduplicated)
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Brain, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../utils/api';
import { useDataCache, useTrainingMode } from '../../contexts';
import UnifiedAITraining from '../UnifiedAITraining';

import QuickStatsBar from './QuickStatsBar';
import IntelOverview from './IntelOverview';
import LearningProgressPanel from './LearningProgressPanel';
import ReportCardPanel from './ReportCardPanel';
import DataCollectionPanel from './DataCollectionPanel';
import SimulationQuickPanel from './SimulationQuickPanel';
import TestingToolsPanel from './TestingToolsPanel';
import AIModulesPanel from './AIModulesPanel';
import StrategyPipelinePanel from './StrategyPipelinePanel';
import SetupModelsPanel from './SetupModelsPanel';

const DEFAULT_DATA = {
  aiAccuracy: null,
  aiAccuracyTrend: null,
  liveStrategies: 0,
  paperStrategies: 0,
  learningHealth: null,
  calibrationsToday: 0,
  timeseriesAccuracy: null,
  timeseriesLastTrained: null,
  timeseriesPredictions: 0,
  bullWinRate: null,
  bullDebates: 0,
  bearWinRate: null,
  bearDebates: 0,
  riskInterventions: 0,
  riskSaved: 0,
  aiAdvisorWeight: 0.15,
  phases: null,
  candidates: [],
  connectors: null,
  thresholds: {},
  reportCard: null,
  connectorSummary: null
};

const NIA = () => {
  const { getCached, setCached } = useDataCache();
  const { getPollingInterval, isTrainingActive } = useTrainingMode();
  const isFirstMount = useRef(true);
  const isVisibleRef = useRef(document.visibilityState === 'visible');

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const stableLoading = loading && !initialLoadDone;

  const cachedData = getCached('niaData');
  const [data, setData] = useState(() => cachedData?.data || DEFAULT_DATA);

  // Helper: merge new fields into state, only update if changed
  const mergeData = useCallback((updates) => {
    setData(prev => {
      const merged = { ...prev, ...updates };
      merged.modelTrained = merged.timeseriesTrained || merged.timeseriesAccuracy !== null;
      merged.calibrationsApplied = merged.calibrationsToday || 0;
      merged.predictionsTracked = merged.timeseriesPredictions || 0;
      merged.alertsAnalyzed = merged.calibrationsApplied * 5;
      return JSON.stringify(prev) === JSON.stringify(merged) ? prev : merged;
    });
  }, []);

  const fetchAllData = useCallback(async (showToast = false) => {
    try {
      if (showToast) setRefreshing(true);
      else setLoading(true);

      // Phase 1: Fast endpoints (respond within 2-5s) → update state immediately
      const fastResults = await Promise.allSettled([
        api.get('/api/strategy-promotion/phases'),
        api.get('/api/strategy-promotion/candidates'),
        api.get('/api/learning-connectors/status'),
        api.get('/api/learning-connectors/thresholds'),
        api.get('/api/ai-modules/timeseries/status'),
        api.get('/api/ai-modules/debate/ai-advisor-status'),
        api.get('/api/ai-modules/shadow/stats'),
        api.get('/api/ai-modules/report-card')
      ]);

      const [phasesRes, candidatesRes, connectorsRes, thresholdsRes,
             timeseriesRes, aiAdvisorRes, shadowStatsRes, reportCardRes] = fastResults;

      const fastUpdates = {};

      if (phasesRes.status === 'fulfilled' && phasesRes.value.data?.success) {
        const phases = phasesRes.value.data;
        fastUpdates.phases = phases;
        fastUpdates.liveStrategies = phases.by_phase?.live?.length || 0;
        fastUpdates.paperStrategies = phases.by_phase?.paper?.length || 0;
      }

      if (candidatesRes.status === 'fulfilled' && candidatesRes.value.data?.success) {
        fastUpdates.candidates = candidatesRes.value.data.ready_for_promotion || [];
      }

      if (connectorsRes.status === 'fulfilled' && connectorsRes.value.data?.success) {
        fastUpdates.connectors = connectorsRes.value.data;
        const connections = connectorsRes.value.data.connections || {};
        const healthyCount = Object.values(connections).filter(c => c.health === 'healthy').length;
        const totalCount = Object.keys(connections).length;
        fastUpdates.learningHealth = totalCount === 0 ? 'Unknown' :
          healthyCount === totalCount ? 'Healthy' :
          healthyCount >= totalCount / 2 ? 'Warning' : 'Critical';
        fastUpdates.connectorSummary = { healthy: healthyCount, total: totalCount };
      }

      if (thresholdsRes.status === 'fulfilled' && thresholdsRes.value.data?.success) {
        fastUpdates.thresholds = thresholdsRes.value.data.thresholds || {};
        fastUpdates.calibrationsToday = Object.keys(fastUpdates.thresholds).length;
      }

      if (timeseriesRes.status === 'fulfilled' && timeseriesRes.value.data?.success) {
        const ts = timeseriesRes.value.data.status;
        fastUpdates.timeseriesAccuracy = ts?.model?.metrics?.accuracy || null;
        fastUpdates.timeseriesTrained = ts?.model?.trained || false;
        fastUpdates.timeseriesPredictions = ts?.model?.metrics?.training_samples || 0;
        fastUpdates.aiAccuracy = ts?.model?.metrics?.accuracy || null;
        fastUpdates.timeseriesLastTrained = ts?.model?.metrics?.last_trained || null;
      }

      if (aiAdvisorRes.status === 'fulfilled' && aiAdvisorRes.value.data?.success) {
        fastUpdates.aiAdvisorWeight = aiAdvisorRes.value.data.ai_advisor?.current_weight || 0.15;
      }

      if (shadowStatsRes.status === 'fulfilled' && shadowStatsRes.value.data?.success) {
        const stats = shadowStatsRes.value.data.stats;
        fastUpdates.bullDebates = stats?.total_logged || 0;
        fastUpdates.bearDebates = stats?.total_logged || 0;
      }

      if (reportCardRes.status === 'fulfilled' && reportCardRes.value.data?.success) {
        fastUpdates.reportCard = reportCardRes.value.data;
      }

      // Apply fast data immediately so UI updates within seconds
      if (Object.keys(fastUpdates).length > 0) {
        mergeData(fastUpdates);
        setLoading(false);
        setInitialLoadDone(true);
      }

      // Phase 2: Slow endpoints (may take 10-30s) → update state when ready
      // Use per-request timeout to prevent indefinite waits
      const withTimeout = (promise, ms) => Promise.race([
        promise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('NIA fetch timeout')), ms))
      ]);

      const slowResults = await Promise.allSettled([
        withTimeout(api.get('/api/ib-collector/stats'), 10000),
        withTimeout(api.get('/api/ib-collector/queue-progress'), 10000),
        withTimeout(api.get('/api/simulation/jobs?limit=10'), 10000)
      ]);

      const [collectionStatsRes, collectionQueueRes, simulationJobsRes] = slowResults;
      const slowUpdates = {};

      if (collectionStatsRes.status === 'fulfilled' && collectionStatsRes.value.data?.success) {
        slowUpdates.collectionStats = collectionStatsRes.value.data.stats;
        slowUpdates.historicalBars = collectionStatsRes.value.data.stats?.total_bars || 0;
      }

      if (collectionQueueRes.status === 'fulfilled' && collectionQueueRes.value.data?.success) {
        slowUpdates.collectionQueue = collectionQueueRes.value.data;
      }

      if (simulationJobsRes.status === 'fulfilled' && simulationJobsRes.value.data?.success) {
        slowUpdates.simulationJobs = simulationJobsRes.value.data.jobs || [];
        slowUpdates.simulationsRun = (simulationJobsRes.value.data.jobs || []).filter(j => j.status === 'completed').length;
      }

      // Apply slow data and cache the full dataset
      if (Object.keys(slowUpdates).length > 0) {
        mergeData(slowUpdates);
      }

      setData(current => {
        setCached('niaData', current, 60000);
        return current;
      });

      if (showToast) toast.success('NIA intel refreshed');
    } catch (err) {
      console.error('Error fetching NIA data:', err);
      if (showToast) toast.error('Failed to refresh intel');
    } finally {
      setLoading(false);
      setRefreshing(false);
      setInitialLoadDone(true);
    }
  }, [setCached, mergeData]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      const wasHidden = !isVisibleRef.current;
      isVisibleRef.current = document.visibilityState === 'visible';
      if (isVisibleRef.current && wasHidden) fetchAllData();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [fetchAllData]);

  useEffect(() => {
    const cached = getCached('niaData');
    if (cached?.data && isFirstMount.current) {
      setData(cached.data);
      setLoading(false);
      if (cached.isStale) fetchAllData();
    } else {
      fetchAllData();
    }
    isFirstMount.current = false;

    const pollInterval = getPollingInterval(60000, false);
    const interval = setInterval(() => {
      if (isVisibleRef.current) fetchAllData();
    }, pollInterval);

    return () => clearInterval(interval);
  }, [fetchAllData, getCached, getPollingInterval, isTrainingActive]);

  const handlePromote = useCallback(async (strategyName, targetPhase) => {
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
  }, [fetchAllData]);

  const handleRunCalibrations = useCallback(async () => {
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
  }, [fetchAllData]);

  const handleRefresh = useCallback(() => fetchAllData(), [fetchAllData]);
  const handleTrainComplete = useCallback(() => fetchAllData(true), [fetchAllData]);
  const noopCallback = useCallback(() => {}, []);

  // Memoized data slices for each panel
  const intelOverviewData = useMemo(() => ({
    aiAccuracy: data.aiAccuracy,
    aiAccuracyTrend: data.aiAccuracyTrend,
    liveStrategies: data.liveStrategies,
    paperStrategies: data.paperStrategies,
    learningHealth: data.learningHealth,
    calibrationsToday: data.calibrationsToday,
    connectorSummary: data.connectorSummary
  }), [data.aiAccuracy, data.aiAccuracyTrend, data.liveStrategies, data.paperStrategies, data.learningHealth, data.calibrationsToday, data.connectorSummary]);

  const learningProgressData = useMemo(() => ({
    modelTrained: data.modelTrained,
    historicalBars: data.historicalBars,
    calibrationsApplied: data.calibrationsApplied,
    predictionsTracked: data.predictionsTracked,
    simulationsRun: data.simulationsRun,
    alertsAnalyzed: data.alertsAnalyzed,
    timeseriesAccuracy: data.timeseriesAccuracy
  }), [data.modelTrained, data.historicalBars, data.calibrationsApplied, data.predictionsTracked, data.simulationsRun, data.alertsAnalyzed, data.timeseriesAccuracy]);

  const aiPerformanceData = useMemo(() => ({
    timeseriesAccuracy: data.timeseriesAccuracy,
    timeseriesLastTrained: data.timeseriesLastTrained,
    timeseriesPredictions: data.timeseriesPredictions,
    bullWinRate: data.bullWinRate,
    bullDebates: data.bullDebates,
    bearWinRate: data.bearWinRate,
    bearDebates: data.bearDebates,
    riskInterventions: data.riskInterventions,
    riskSaved: data.riskSaved,
    aiAdvisorWeight: data.aiAdvisorWeight
  }), [data.timeseriesAccuracy, data.timeseriesLastTrained, data.timeseriesPredictions, data.bullWinRate, data.bullDebates, data.bearWinRate, data.bearDebates, data.riskInterventions, data.riskSaved, data.aiAdvisorWeight]);

  const quickStatsData = useMemo(() => ({
    simulationJobs: data.simulationJobs,
    collectionQueue: data.collectionQueue,
    candidates: data.candidates,
    historicalBars: data.historicalBars,
    modelTrained: data.modelTrained,
    aiAccuracy: data.aiAccuracy,
    connectorSummary: data.connectorSummary
  }), [data.simulationJobs, data.collectionQueue, data.candidates, data.historicalBars, data.modelTrained, data.aiAccuracy, data.connectorSummary]);

  const memoizedPhases = useMemo(() => data.phases, [data.phases]);
  const memoizedCandidates = useMemo(() => data.candidates, [data.candidates]);
  const memoizedSimulationJobs = useMemo(() => data.simulationJobs, [data.simulationJobs]);
  const memoizedReportCard = useMemo(() => data.reportCard, [data.reportCard]);
  const memoizedConnectors = useMemo(() => data.connectors, [data.connectors]);
  const memoizedThresholds = useMemo(() => data.thresholds, [data.thresholds]);

  return (
    <div className="h-full overflow-auto p-4" style={{ background: 'var(--bg-primary)' }} data-testid="nia-page">
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
            <h1 className="text-xl font-bold text-white flex items-center gap-2" data-testid="nia-title">
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
          data-testid="nia-refresh-btn"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing...' : 'Refresh Intel'}
        </button>
      </div>

      {/* 0. Quick Stats Bar - Real-time action items at a glance */}
      <QuickStatsBar data={quickStatsData} />

      {/* 1. Unified AI Training & Calibration */}
      <UnifiedAITraining onTrainComplete={handleTrainComplete} />

      {/* 1.5 Setup-Specific AI Models */}
      <SetupModelsPanel />

      {/* 2. Intel Overview - Key metrics with connector health */}
      <IntelOverview data={intelOverviewData} />

      {/* 3. Report Card - Moved up for visibility */}
      <ReportCardPanel reportCard={memoizedReportCard} loading={stableLoading} />

      {/* 4. Learning Progress */}
      <LearningProgressPanel data={learningProgressData} />

      {/* 5. Data Collection */}
      <DataCollectionPanel onRefresh={handleRefresh} />

      {/* 6. Historical Simulations */}
      <SimulationQuickPanel jobs={memoizedSimulationJobs} loading={stableLoading} onRefresh={handleRefresh} />

      {/* 7. Testing & Scanning (merged) */}
      <TestingToolsPanel />

      {/* 8. AI Modules & Connectors (merged) */}
      <AIModulesPanel
        data={aiPerformanceData}
        connectors={memoizedConnectors}
        thresholds={memoizedThresholds}
        onRefresh={() => fetchAllData(true)}
        onRunCalibrations={handleRunCalibrations}
      />

      {/* 9. Strategy Pipeline (lifecycle + promotions merged) */}
      <StrategyPipelinePanel
        phases={memoizedPhases}
        candidates={memoizedCandidates}
        loading={stableLoading}
        onPromote={handlePromote}
        onDemote={noopCallback}
      />

      {/* Footer */}
      <div className="text-center text-xs text-zinc-600 mt-6">
        <span className="font-mono">NIA v3.0</span> &bull; Neural Intelligence Agency &bull; Part of <span className="text-cyan-500">SentCom</span>
      </div>
    </div>
  );
};

export default NIA;
