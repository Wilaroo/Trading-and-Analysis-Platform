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
 * 
 * Performance Optimization:
 * - Uses DataCacheContext for persistent data across tab switches
 * - Stale-while-revalidate pattern for instant display
 * - Memoized child components to prevent unnecessary re-renders
 */

import React, { useState, useEffect, useCallback, useRef, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Activity,
  TrendingUp,
  TrendingDown,
  Target,
  Shield,
  Zap,
  CheckCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Loader,
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
  Rocket,
  HardDrive,
  Download,
  PlayCircle,
  History,
  Sparkles,
  Settings,
  Info,
  StopCircle,
  Globe,
  Search,
  Shuffle
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';
import { useDataCache } from '../contexts';
import MarketScannerPanel from './MarketScannerPanel';
import AdvancedBacktestPanel from './AdvancedBacktestPanel';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// ==================== TRAIN ALL PANEL ====================

const TrainAllPanel = memo(({ onTrainComplete }) => {
  const [isTraining, setIsTraining] = useState(false);
  const [currentStep, setCurrentStep] = useState(null);
  const [trainingStatus, setTrainingStatus] = useState(null);
  const [autoTrainEnabled, setAutoTrainEnabled] = useState(false);
  const [autoTrainAfterCollection, setAutoTrainAfterCollection] = useState(false);
  const [progress, setProgress] = useState({
    timeseries: { status: 'pending', message: '' },
    connectors: { status: 'pending', message: '' },
    calibration: { status: 'pending', message: '' },
    simulations: { status: 'pending', message: '' }
  });

  // Fetch training status on mount
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await api.get('/api/ai-modules/training-status');
        if (res.data?.success) {
          setTrainingStatus(res.data);
          setAutoTrainEnabled(res.data.auto_training?.enabled || false);
          setAutoTrainAfterCollection(res.data.auto_training?.after_collection || false);
        }
      } catch (e) {
        console.log('Training status fetch error:', e);
      }
    };
    fetchStatus();
  }, []);

  // Update auto-training settings
  const handleAutoTrainToggle = async (setting, value) => {
    try {
      const params = new URLSearchParams({
        auto_train_enabled: setting === 'enabled' ? value : autoTrainEnabled,
        train_after_collection: setting === 'after_collection' ? value : autoTrainAfterCollection
      });
      
      await api.post(`/api/ai-modules/training-settings?${params}`);
      
      if (setting === 'enabled') {
        setAutoTrainEnabled(value);
        toast.success(value ? 'Auto-training enabled' : 'Auto-training disabled');
      } else {
        setAutoTrainAfterCollection(value);
        toast.success(value ? 'Will train after data collection' : 'Training after collection disabled');
      }
    } catch (e) {
      toast.error('Failed to update settings');
    }
  };

  const trainingSteps = [
    { key: 'timeseries', label: 'Train Time-Series AI', icon: Brain, description: 'Learning price patterns from historical data' },
    { key: 'connectors', label: 'Sync Learning Connectors', icon: GitBranch, description: 'Connecting data pipelines' },
    { key: 'calibration', label: 'Calibrate Scanner', icon: Target, description: 'Optimizing alert thresholds' },
    { key: 'simulations', label: 'Update Strategy Scores', icon: BarChart3, description: 'Evaluating strategy performance' }
  ];

  const handleTrainAll = async () => {
    setIsTraining(true);
    const newProgress = { ...progress };

    try {
      // Step 1: Train Time-Series AI
      setCurrentStep('timeseries');
      newProgress.timeseries = { status: 'running', message: 'Training model...' };
      setProgress({ ...newProgress });
      
      try {
        const tsRes = await api.post('/api/ai-modules/timeseries/train');
        if (tsRes.data?.success) {
          newProgress.timeseries = { status: 'completed', message: 'Model trained successfully' };
        } else {
          newProgress.timeseries = { status: 'warning', message: 'Training skipped - check data' };
        }
      } catch (e) {
        newProgress.timeseries = { status: 'warning', message: 'No training data yet' };
      }
      setProgress({ ...newProgress });

      // Step 2: Sync Learning Connectors
      setCurrentStep('connectors');
      newProgress.connectors = { status: 'running', message: 'Syncing data flows...' };
      setProgress({ ...newProgress });
      
      try {
        await api.post('/api/learning-connectors/sync/all');
        newProgress.connectors = { status: 'completed', message: 'All connectors synced' };
      } catch (e) {
        newProgress.connectors = { status: 'warning', message: 'Some connectors skipped' };
      }
      setProgress({ ...newProgress });

      // Step 3: Run Calibrations
      setCurrentStep('calibration');
      newProgress.calibration = { status: 'running', message: 'Calibrating thresholds...' };
      setProgress({ ...newProgress });
      
      try {
        await api.post('/api/learning-connectors/sync/run-all-calibrations');
        newProgress.calibration = { status: 'completed', message: 'Scanner optimized' };
      } catch (e) {
        newProgress.calibration = { status: 'warning', message: 'Calibration needs more data' };
      }
      setProgress({ ...newProgress });

      // Step 4: Update Strategy Scores
      setCurrentStep('simulations');
      newProgress.simulations = { status: 'running', message: 'Calculating scores...' };
      setProgress({ ...newProgress });
      
      try {
        await api.post('/api/strategy-promotion/evaluate-all');
        newProgress.simulations = { status: 'completed', message: 'Scores updated' };
      } catch (e) {
        newProgress.simulations = { status: 'completed', message: 'Using existing scores' };
      }
      setProgress({ ...newProgress });

      setCurrentStep(null);
      toast.success('Training complete! System is now smarter.');
      if (onTrainComplete) onTrainComplete();

    } catch (err) {
      console.error('Training error:', err);
      toast.error('Training interrupted');
    } finally {
      setIsTraining(false);
      setCurrentStep(null);
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'running': return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
      case 'warning': return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
      case 'failed': return <XCircle className="w-4 h-4 text-red-400" />;
      default: return <Clock className="w-4 h-4 text-zinc-500" />;
    }
  };

  const completedCount = Object.values(progress).filter(p => p.status === 'completed').length;
  
  // Format last trained time
  const formatLastTrained = (isoDate) => {
    if (!isoDate) return 'Never';
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.9), rgba(30, 40, 55, 0.9))' }}>
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #06b6d4, #8b5cf6)' }}>
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Train Everything</h3>
              <p className="text-xs text-zinc-400">
                {trainingStatus?.model?.is_trained 
                  ? `Last trained: ${formatLastTrained(trainingStatus.model.last_trained)}`
                  : 'Model not yet trained'}
              </p>
            </div>
          </div>
          
          <button
            onClick={handleTrainAll}
            disabled={isTraining}
            className={`
              px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-all
              ${isTraining 
                ? 'bg-cyan-500/20 text-cyan-400 cursor-not-allowed' 
                : 'bg-gradient-to-r from-cyan-500 to-violet-500 text-white hover:from-cyan-400 hover:to-violet-400 shadow-lg shadow-cyan-500/25'
              }
            `}
            data-testid="train-all-btn"
          >
            {isTraining ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Training... ({completedCount}/4)
              </>
            ) : (
              <>
                <PlayCircle className="w-4 h-4" />
                Train All
              </>
            )}
          </button>
        </div>

        {/* Model Status Bar */}
        {trainingStatus?.model && (
          <div className="flex items-center gap-4 mb-4 p-2 rounded-lg bg-white/5 border border-white/10">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${trainingStatus.model.is_trained ? 'bg-green-400' : 'bg-amber-400'}`} />
              <span className="text-xs text-zinc-400">
                {trainingStatus.model.is_trained ? `${trainingStatus.model.version}` : 'Untrained'}
              </span>
            </div>
            {trainingStatus.model.accuracy && (
              <div className="text-xs text-zinc-400">
                Accuracy: <span className="text-cyan-400">{(trainingStatus.model.accuracy * 100).toFixed(1)}%</span>
              </div>
            )}
            {trainingStatus.model.samples_trained > 0 && (
              <div className="text-xs text-zinc-400">
                Samples: <span className="text-zinc-300">{trainingStatus.model.samples_trained.toLocaleString()}</span>
              </div>
            )}
          </div>
        )}

        {/* Auto-Training Settings */}
        <div className="flex items-center gap-4 mb-4 p-2 rounded-lg bg-white/5 border border-white/10">
          <Settings className="w-4 h-4 text-zinc-500" />
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={autoTrainAfterCollection}
              onChange={(e) => handleAutoTrainToggle('after_collection', e.target.checked)}
              className="w-3 h-3 rounded border-zinc-600 bg-zinc-800 text-cyan-500 focus:ring-cyan-500/50"
            />
            <span className="text-xs text-zinc-400">Auto-train after data collection</span>
          </label>
        </div>

        {/* Training Steps */}
        <div className="space-y-2">
          {trainingSteps.map((step, idx) => {
            const stepProgress = progress[step.key];
            const isActive = currentStep === step.key;
            const Icon = step.icon;
            
            return (
              <div
                key={step.key}
                className={`
                  flex items-center justify-between p-3 rounded-lg transition-all
                  ${isActive ? 'bg-cyan-500/10 border border-cyan-500/30' : 'bg-white/[0.02] border border-white/5'}
                `}
              >
                <div className="flex items-center gap-3">
                  <div className={`
                    w-8 h-8 rounded-lg flex items-center justify-center
                    ${stepProgress.status === 'completed' ? 'bg-green-500/20' : 
                      isActive ? 'bg-cyan-500/20' : 'bg-white/5'}
                  `}>
                    <Icon className={`w-4 h-4 ${
                      stepProgress.status === 'completed' ? 'text-green-400' :
                      isActive ? 'text-cyan-400' : 'text-zinc-500'
                    }`} />
                  </div>
                  <div>
                    <div className="text-sm text-white">{step.label}</div>
                    <div className="text-xs text-zinc-500">
                      {stepProgress.message || step.description}
                    </div>
                  </div>
                </div>
                {getStatusIcon(stepProgress.status)}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});

// ==================== LEARNING PROGRESS PANEL ====================

const LearningProgressPanel = memo(({ data }) => {
  const [expanded, setExpanded] = useState(true);

  // Memoize calculated values to prevent recalculation on each render
  const progressData = useMemo(() => {
    const aiTrainingProgress = data.modelTrained ? 100 : (data.historicalBars > 0 ? 50 : 0);
    const scannerCalibrationProgress = data.calibrationsApplied > 0 ? Math.min(100, data.calibrationsApplied * 20) : 0;
    const predictionTrackingProgress = data.predictionsTracked > 0 ? Math.min(100, (data.predictionsTracked / 1000) * 100) : 0;
    const strategySimProgress = data.simulationsRun > 0 ? Math.min(100, data.simulationsRun * 25) : 0;

    const aiTrainingDetail = data.modelTrained 
      ? `Model trained${data.timeseriesAccuracy ? ` (${(data.timeseriesAccuracy * 100).toFixed(1)}% accuracy)` : ''}`
      : `${data.historicalBars?.toLocaleString() || 0} bars available`;

    const progressItems = [
      {
        label: 'AI Model Training',
        progress: aiTrainingProgress,
        detail: aiTrainingDetail,
        color: 'cyan',
        ready: data.modelTrained || data.historicalBars > 1000
      },
      {
        label: 'Scanner Calibration',
        progress: scannerCalibrationProgress,
        detail: `${data.calibrationsApplied || 0} thresholds optimized`,
        color: 'violet',
        ready: data.alertsAnalyzed > 10
      },
      {
        label: 'Prediction Tracking',
        progress: predictionTrackingProgress,
        detail: `${data.predictionsTracked || 0} predictions verified`,
        color: 'amber',
        ready: data.predictionsTracked > 0
      },
      {
        label: 'Strategy Simulations',
        progress: strategySimProgress,
        detail: `${data.simulationsRun || 0} backtests completed`,
        color: 'emerald',
        ready: data.simulationsRun > 0
      }
    ];

    const overallProgress = Math.round(
      (aiTrainingProgress + scannerCalibrationProgress + predictionTrackingProgress + strategySimProgress) / 4
    );

    return { progressItems, overallProgress };
  }, [data.modelTrained, data.historicalBars, data.calibrationsApplied, data.predictionsTracked, data.simulationsRun, data.alertsAnalyzed, data.timeseriesAccuracy]);

  const { progressItems, overallProgress } = progressData;

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #10b981, #06b6d4)' }}>
            <TrendingUp className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Learning Progress</h3>
            <p className="text-xs text-zinc-400">How smart is the system?</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-lg font-bold text-white">{overallProgress}%</div>
            <div className="text-[10px] text-zinc-500">Overall</div>
          </div>
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
            <div className="p-4 space-y-4">
              {progressItems.map((item) => (
                <div key={item.label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-zinc-300">{item.label}</span>
                    <span className="text-xs text-zinc-500">{item.progress}%</span>
                  </div>
                  <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${item.progress}%` }}
                      transition={{ duration: 0.5, ease: 'easeOut' }}
                      className={`h-full rounded-full bg-gradient-to-r ${
                        item.color === 'cyan' ? 'from-cyan-500 to-cyan-400' :
                        item.color === 'violet' ? 'from-violet-500 to-violet-400' :
                        item.color === 'amber' ? 'from-amber-500 to-amber-400' :
                        'from-emerald-500 to-emerald-400'
                      }`}
                    />
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] text-zinc-500">{item.detail}</span>
                    {item.ready && (
                      <span className="text-[10px] text-green-400 flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> Ready
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ==================== DATA COLLECTION PANEL (UNIFIED) ====================

const DataCollectionPanel = memo(({ collectionData, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  const [lookbackDays, setLookbackDays] = useState(30);
  const [tier, setTier] = useState('all'); // 'all', 'intraday', 'swing', 'investment'
  const [skipRecent, setSkipRecent] = useState(true);
  const [recentThreshold, setRecentThreshold] = useState(7);
  const [maxSymbols, setMaxSymbols] = useState(null);
  const [collecting, setCollecting] = useState(false);
  const [activeTab, setActiveTab] = useState('coverage'); // 'coverage', 'collect', or 'progress'
  
  // Progress state
  const [detailedProgress, setDetailedProgress] = useState({ by_bar_size: [], active_collections: [] });
  const [cancelling, setCancelling] = useState(false);
  
  // Data coverage state
  const [dataCoverage, setDataCoverage] = useState(null);
  const [loadingCoverage, setLoadingCoverage] = useState(true);
  const [lastDataChange, setLastDataChange] = useState(null); // Track when data actually changed
  
  // Collection mode state (dedicated collector running)
  const [collectionMode, setCollectionMode] = useState(null);
  
  // Fill gaps state
  const [fillingGaps, setFillingGaps] = useState(false);
  
  // Use refs to track data changes without causing re-renders
  const lastDataRef = useRef(null);
  const lastFetchTimeRef = useRef(null);
  const pollingActiveRef = useRef(true);

  // ADV Tier options - determines which symbols AND which timeframes
  const tierOptions = [
    { 
      value: 'all', 
      label: 'All Tiers', 
      description: 'Intraday + Swing + Investment stocks',
      icon: Globe,
      adv: '50K+ shares/day',
      timeframes: 'All applicable per stock'
    },
    { 
      value: 'intraday', 
      label: 'Intraday', 
      description: 'High volume day trading stocks',
      icon: Zap,
      adv: '500K+ shares/day',
      timeframes: '1min, 5min, 15min, 1hr, 1day'
    },
    { 
      value: 'swing', 
      label: 'Swing', 
      description: 'Medium volume swing stocks',
      icon: TrendingUp,
      adv: '100K+ shares/day',
      timeframes: '5min, 30min, 1hr, 1day'
    },
    { 
      value: 'investment', 
      label: 'Investment', 
      description: 'Lower volume position stocks',
      icon: Layers,
      adv: '50K+ shares/day',
      timeframes: '1hr, 1day, 1week'
    }
  ];

  // Lookback presets
  const lookbackPresets = [
    { value: 5, label: '5 Days', description: 'Quick refresh' },
    { value: 30, label: '30 Days', description: 'Standard (recommended)' },
    { value: 90, label: '90 Days', description: '3 months' },
    { value: 180, label: '6 Months', description: 'Extended history' },
    { value: 365, label: '1 Year', description: 'Full year' }
  ];

  // Fetch progress data - with smart comparison to avoid unnecessary re-renders
  useEffect(() => {
    let isMounted = true;
    
    const fetchData = async () => {
      if (!isMounted) return;
      
      try {
        const [progressRes, coverageRes, collectionModeRes] = await Promise.allSettled([
          fetch(`${API_BASE}/api/ib-collector/queue-progress-detailed`),
          fetch(`${API_BASE}/api/ib-collector/data-coverage`),
          fetch(`${API_BASE}/api/ib/collection-mode/status`)
        ]);
        
        if (!isMounted) return;
        
        if (progressRes.status === 'fulfilled' && progressRes.value.ok) {
          const data = await progressRes.value.json();
          if (data.success) {
            const newProgress = {
              by_bar_size: data.by_bar_size || [],
              active_collections: data.active_collections || [],
              overall: data.overall || {}
            };
            // Only update if data actually changed
            const newProgressStr = JSON.stringify(newProgress);
            if (lastDataRef.current?.progress !== newProgressStr) {
              lastDataRef.current = { ...lastDataRef.current, progress: newProgressStr };
              setDetailedProgress(newProgress);
            }
          }
        }
        
        if (coverageRes.status === 'fulfilled' && coverageRes.value.ok) {
          const data = await coverageRes.value.json();
          if (data.success) {
            // Track fetch time via ref (no re-render)
            lastFetchTimeRef.current = new Date();
            
            // Only update coverage state if data actually changed
            const newCoverageStr = JSON.stringify(data);
            if (lastDataRef.current?.coverage !== newCoverageStr) {
              console.log('[Coverage] Data changed, updating UI');
              lastDataRef.current = { ...lastDataRef.current, coverage: newCoverageStr };
              setDataCoverage(data);
              setLastDataChange(new Date()); // Mark when data actually changed
            }
          }
        }
        
        // Fetch collection mode status
        if (collectionModeRes.status === 'fulfilled' && collectionModeRes.value.ok) {
          const data = await collectionModeRes.value.json();
          setCollectionMode(data);
        }
      } catch (err) {
        console.error('Error fetching collection data:', err);
      } finally {
        if (isMounted) {
          setLoadingCoverage(false);
        }
      }
    };
    
    fetchData();
    // Poll every 15 seconds to better align with 30-second backend cache
    const interval = setInterval(fetchData, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const hasActiveCollections = detailedProgress.active_collections?.length > 0;

  const startCollection = async () => {
    setCollecting(true);
    try {
      // Build query params
      const params = new URLSearchParams({
        lookback_days: lookbackDays.toString(),
        skip_recent: skipRecent.toString(),
        recent_days_threshold: recentThreshold.toString()
      });
      
      if (maxSymbols) {
        params.append('max_symbols', maxSymbols.toString());
      }
      
      // Use per-stock collection endpoint
      const res = await fetch(`${API_BASE}/api/ib-collector/per-stock-collection?${params}`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Collection started: ${data.symbols} symbols, ${data.total_requests} requests queued`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || 'Failed to start collection');
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
      const res = await fetch(`${API_BASE}/api/ib-collector/cancel-all-pending`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.info(`Cancelled ${data.cancelled} pending requests`);
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      toast.error('Error cancelling');
    } finally {
      setCancelling(false);
    }
  };

  // Fill gaps - automatically collect only missing data with MAX lookback
  const handleFillGaps = async () => {
    setFillingGaps(true);
    try {
      const params = new URLSearchParams({
        use_max_lookback: 'true'  // Get maximum history per timeframe
      });
      
      // Add tier filter if not 'all'
      if (tier !== 'all') {
        params.append('tier_filter', tier);
      }
      
      const res = await fetch(`${API_BASE}/api/ib-collector/fill-gaps?${params}`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        if (data.gaps_found === 0) {
          toast.success('No gaps found! Your data coverage is complete.');
        } else {
          toast.success(`Started filling ${data.gaps_found} gaps across ${data.total_unique_symbols} symbols`);
          // Switch to Progress tab to show status
          setActiveTab('progress');
        }
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || 'Failed to start gap fill');
      }
    } catch (err) {
      toast.error('Error starting gap fill');
      console.error(err);
    } finally {
      setFillingGaps(false);
    }
  };

  // Calculate estimated time
  const estimatedTime = () => {
    // Rough estimate: 3 seconds per request
    const requestsPerSymbol = tier === 'intraday' ? 5 : tier === 'swing' ? 4 : tier === 'investment' ? 3 : 4;
    const symbolCount = maxSymbols || 500; // Assume 500 if not limited
    const totalRequests = symbolCount * requestsPerSymbol;
    const hours = (totalRequests * 3) / 3600;
    return hours < 1 ? `~${Math.round(hours * 60)} mins` : `~${hours.toFixed(1)} hours`;
  };

  return (
    <div className="bg-gradient-to-br from-zinc-900/80 to-black/60 rounded-2xl border border-white/10 overflow-hidden" data-testid="data-collection-panel">
      {/* Header */}
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
            <p className="text-[10px] text-zinc-500">Per-stock multi-timeframe • Smart ADV filtering</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hasActiveCollections && (
            <span className="px-2 py-1 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-medium animate-pulse">
              COLLECTING
            </span>
          )}
          {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
        </div>
      </div>

      {/* Content */}
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
                      <span className="text-xs font-bold text-amber-400">DATA COLLECTION MODE ACTIVE</span>
                      <span className="px-1.5 py-0.5 rounded bg-amber-500/30 text-[9px] text-amber-300 font-medium">
                        LIVE TRADING PAUSED
                      </span>
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
                          <div 
                            className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all duration-500"
                            style={{ width: `${collectionMode.queue.progress_pct || 0}%` }}
                          />
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
            
            {/* Tab Navigation */}
            <div className="flex border-b border-white/10">
              <button
                onClick={() => setActiveTab('coverage')}
                className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${
                  activeTab === 'coverage' 
                    ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5' 
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                Coverage
              </button>
              <button
                onClick={() => setActiveTab('collect')}
                className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${
                  activeTab === 'collect' 
                    ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5' 
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                Collect
              </button>
              <button
                onClick={() => setActiveTab('progress')}
                className={`flex-1 px-4 py-2 text-xs font-medium transition-colors ${
                  activeTab === 'progress' 
                    ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/5' 
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                Progress {hasActiveCollections && <span className="ml-1 w-2 h-2 bg-amber-400 rounded-full inline-block animate-pulse" />}
              </button>
            </div>

            <div className="p-4">
              {activeTab === 'coverage' ? (
                /* Data Coverage View */
                <div className="space-y-4">
                  {loadingCoverage ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
                    </div>
                  ) : dataCoverage ? (
                    <>
                      {/* ADV Cache Status */}
                      <div className={`p-3 rounded-xl border ${
                        dataCoverage.adv_cache?.status === 'ready' 
                          ? 'bg-emerald-500/5 border-emerald-500/20' 
                          : 'bg-amber-500/5 border-amber-500/20'
                      }`}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Database className={`w-4 h-4 ${
                              dataCoverage.adv_cache?.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'
                            }`} />
                            <span className="text-xs font-medium text-white">ADV Cache</span>
                            {/* Subtle polling indicator - green dot pulses to show active polling */}
                            <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" title="Auto-refreshing every 15s" />
                          </div>
                          <div className="flex items-center gap-3">
                            {lastDataChange && (
                              <span className="text-[9px] text-zinc-500" title="When coverage data last changed">
                                Updated: {lastDataChange.toLocaleTimeString()}
                              </span>
                            )}
                            <span className={`text-sm font-bold ${
                              dataCoverage.adv_cache?.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'
                            }`}>
                              {dataCoverage.adv_cache?.total_symbols?.toLocaleString() || 0} symbols
                            </span>
                          </div>
                        </div>
                        {/* Show total bars collected for quick reference */}
                        <div className="flex items-center gap-4 mt-2 text-[10px] text-zinc-500">
                          <span>Total bars: {dataCoverage.by_timeframe?.reduce((sum, tf) => sum + (tf.total_bars || 0), 0).toLocaleString()}</span>
                          <span>•</span>
                          <span>Gaps: {dataCoverage.total_gaps || 0}</span>
                        </div>
                      </div>
                      
                      {/* Per-Tier Coverage */}
                      <div>
                        <p className="text-xs font-medium text-zinc-400 mb-2">Coverage by Tier</p>
                        <div className="space-y-3">
                          {dataCoverage.by_tier?.map((tierData, i) => {
                            // Calculate overall tier completion
                            const totalPossible = tierData.timeframes?.reduce((sum, tf) => sum + (tf.symbols_needed || 0), 0) || 1;
                            const totalCovered = tierData.timeframes?.reduce((sum, tf) => sum + (tf.symbols_with_data || 0), 0) || 0;
                            const overallPct = Math.round((totalCovered / totalPossible) * 100);
                            
                            return (
                              <div key={i} className="p-3 rounded-xl bg-black/40 border border-white/10">
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    {tierData.tier === 'intraday' && <Zap className="w-4 h-4 text-yellow-400" />}
                                    {tierData.tier === 'swing' && <TrendingUp className="w-4 h-4 text-cyan-400" />}
                                    {tierData.tier === 'investment' && <Layers className="w-4 h-4 text-violet-400" />}
                                    <span className="text-sm font-bold text-white capitalize">{tierData.tier}</span>
                                    <span className="text-[10px] text-zinc-500">({tierData.description})</span>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs text-zinc-400">{tierData.total_symbols?.toLocaleString()} symbols</span>
                                    <span className={`text-xs font-bold ${overallPct >= 90 ? 'text-emerald-400' : overallPct >= 50 ? 'text-amber-400' : 'text-rose-400'}`}>
                                      {overallPct}%
                                    </span>
                                  </div>
                                </div>
                                
                                {/* Overall progress bar */}
                                <div className="h-1.5 bg-black/50 rounded-full mb-3 overflow-hidden">
                                  <div 
                                    className={`h-full rounded-full transition-all duration-500 ${
                                      overallPct >= 90 ? 'bg-emerald-500' : 
                                      overallPct >= 50 ? 'bg-amber-500' : 'bg-rose-500'
                                    }`}
                                    style={{ width: `${overallPct}%` }}
                                  />
                                </div>
                                
                                {/* Timeframe breakdown for this tier */}
                                <div className="grid grid-cols-5 gap-1.5">
                                  {tierData.timeframes?.map((tf, j) => {
                                    // Use static classes to ensure Tailwind JIT compiles them
                                    const isHigh = tf.coverage_pct >= 90;
                                    const isMedium = tf.coverage_pct >= 50 && tf.coverage_pct < 90;
                                    const isLow = tf.coverage_pct < 50;
                                    
                                    return (
                                      <div 
                                        key={j} 
                                        className={`p-2 rounded-lg bg-black/30 border transition-all ${
                                          isHigh ? 'border-emerald-500/30' : 
                                          isMedium ? 'border-amber-500/30' : 'border-rose-500/30'
                                        }`}
                                        title={`${tf.symbols_with_data}/${tf.symbols_needed} symbols, ${tf.total_bars?.toLocaleString()} bars`}
                                      >
                                        <p className="text-[9px] text-zinc-500 truncate">{tf.timeframe}</p>
                                        <p className={`text-xs font-bold ${
                                          isHigh ? 'text-emerald-400' : 
                                          isMedium ? 'text-amber-400' : 'text-rose-400'
                                        }`}>
                                          {tf.coverage_pct}%
                                        </p>
                                        <p className="text-[8px] text-zinc-600">
                                          {tf.symbols_with_data}/{tf.symbols_needed}
                                        </p>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      
                      {/* Per-Timeframe Summary */}
                      <div>
                        <p className="text-xs font-medium text-zinc-400 mb-2">All Timeframes</p>
                        <div className="grid grid-cols-7 gap-2">
                          {dataCoverage.by_timeframe?.map((tf, i) => (
                            <div key={i} className="p-2 rounded-lg bg-black/30 border border-white/10 text-center">
                              <p className="text-[9px] text-zinc-500 mb-1">{tf.timeframe}</p>
                              <p className="text-sm font-bold text-white">{tf.symbols}</p>
                              <p className="text-[8px] text-zinc-600">{(tf.total_bars / 1000).toFixed(0)}K bars</p>
                            </div>
                          ))}
                        </div>
                      </div>
                      
                      {/* Missing Data */}
                      {dataCoverage.missing?.length > 0 && (
                        <div>
                          <p className="text-xs font-medium text-zinc-400 mb-2">
                            Data Gaps ({dataCoverage.total_gaps} total)
                          </p>
                          <div className="space-y-1">
                            {dataCoverage.missing.slice(0, 5).map((gap, i) => (
                              <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-rose-500/5 border border-rose-500/20">
                                <div className="flex items-center gap-2">
                                  <AlertTriangle className="w-3 h-3 text-rose-400" />
                                  <span className="text-xs text-white capitalize">{gap.tier}</span>
                                  <span className="text-[10px] text-zinc-500">{gap.timeframe}</span>
                                </div>
                                <span className="text-xs text-rose-400">{gap.missing_symbols} missing</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      
                      {/* Action Buttons */}
                      <div className="flex gap-2">
                        {/* Fill Gaps Button - Primary action when gaps exist */}
                        {dataCoverage.total_gaps > 0 && (
                          <button
                            onClick={handleFillGaps}
                            disabled={fillingGaps || hasActiveCollections}
                            className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 text-emerald-400 text-xs font-medium hover:from-emerald-500/30 hover:to-cyan-500/30 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                            data-testid="fill-gaps-btn"
                          >
                            {fillingGaps ? (
                              <>
                                <Loader className="w-3 h-3 animate-spin" />
                                Starting...
                              </>
                            ) : (
                              <>
                                <Zap className="w-3 h-3" />
                                Fill Gaps ({dataCoverage.total_gaps})
                              </>
                            )}
                          </button>
                        )}
                        
                        {/* Refresh Button */}
                        <button
                          onClick={onRefresh}
                          className={`${dataCoverage.total_gaps > 0 ? 'flex-1' : 'w-full'} py-2 rounded-lg bg-white/5 border border-white/10 text-zinc-400 text-xs font-medium hover:bg-white/10 transition-colors flex items-center justify-center gap-2`}
                        >
                          <RefreshCw className="w-3 h-3" />
                          Refresh
                        </button>
                      </div>
                      
                      {/* Status Messages */}
                      {dataCoverage.total_gaps === 0 && dataCoverage.adv_cache?.total_symbols > 0 && (
                        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-center">
                          <CheckCircle className="w-6 h-6 text-emerald-400 mx-auto mb-2" />
                          <p className="text-xs text-emerald-400 font-medium">Data coverage complete!</p>
                          <p className="text-[10px] text-zinc-500 mt-1">All tiers and timeframes have data</p>
                        </div>
                      )}
                      
                      {/* No ADV Cache - Need initial collection */}
                      {dataCoverage.adv_cache?.total_symbols === 0 && (
                        <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-center">
                          <Database className="w-6 h-6 text-amber-400 mx-auto mb-2" />
                          <p className="text-xs text-amber-400 font-medium">No symbols in ADV cache</p>
                          <p className="text-[10px] text-zinc-500 mt-1">Run a data collection from the "Collect" tab to populate the cache</p>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-center py-8">
                      <AlertCircle className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
                      <p className="text-zinc-500 text-sm">Could not load coverage data</p>
                      <p className="text-zinc-600 text-xs mt-1">Make sure the backend is running</p>
                    </div>
                  )}
                </div>
              ) : activeTab === 'progress' ? (
                /* Progress Overview - CONSOLIDATED VIEW */
                <div className="space-y-4">
                  {/* Queue Status Summary */}
                  <div className="p-3 rounded-xl bg-gradient-to-r from-zinc-900 to-black border border-white/10">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-zinc-400">Collection Queue Status</span>
                      {collectionMode?.collection_mode?.active && (
                        <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-medium animate-pulse">
                          COLLECTING
                        </span>
                      )}
                    </div>
                    
                    {collectionMode?.queue && (
                      <>
                        <div className="grid grid-cols-4 gap-2 mb-3">
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <p className="text-lg font-bold text-emerald-400">{collectionMode.queue.completed?.toLocaleString()}</p>
                            <p className="text-[9px] text-zinc-500">Completed</p>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <p className="text-lg font-bold text-amber-400">{collectionMode.queue.pending?.toLocaleString()}</p>
                            <p className="text-[9px] text-zinc-500">Pending</p>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <p className="text-lg font-bold text-rose-400">{collectionMode.queue.failed || 0}</p>
                            <p className="text-[9px] text-zinc-500">Failed</p>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-black/40">
                            <p className="text-lg font-bold text-cyan-400">{collectionMode.queue.progress_pct}%</p>
                            <p className="text-[9px] text-zinc-500">Complete</p>
                          </div>
                        </div>
                        
                        {/* Overall Progress Bar */}
                        <div className="h-2 bg-black/50 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all duration-500"
                            style={{ width: `${collectionMode.queue.progress_pct || 0}%` }}
                          />
                        </div>
                        
                        {/* ETA if collecting */}
                        {collectionMode?.collection_mode?.active && collectionMode.collection_mode.rate_per_hour > 0 && (
                          <div className="flex items-center justify-between mt-2 text-[10px] text-zinc-500">
                            <span>Rate: {Math.round(collectionMode.collection_mode.rate_per_hour)}/hour</span>
                            <span>ETA: ~{Math.round(collectionMode.queue.pending / collectionMode.collection_mode.rate_per_hour)} hours</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  
                  {/* Progress by Bar Size / Timeframe */}
                  {detailedProgress.by_bar_size?.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-zinc-400 mb-2">Progress by Timeframe</p>
                      <div className="space-y-2">
                        {detailedProgress.by_bar_size.map((bs, i) => {
                          const pct = bs.progress_pct || 0;
                          const isActive = bs.is_active;
                          
                          return (
                            <div key={i} className={`p-2 rounded-lg border ${
                              isActive ? 'bg-black/40 border-cyan-500/20' : 'bg-black/20 border-white/5'
                            }`}>
                              <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-medium text-white">{bs.bar_size}</span>
                                  {isActive && (
                                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                                  )}
                                </div>
                                <div className="flex items-center gap-3 text-[10px]">
                                  <span className="text-emerald-400">{bs.completed?.toLocaleString()} done</span>
                                  {bs.pending > 0 && <span className="text-amber-400">{bs.pending?.toLocaleString()} pending</span>}
                                  {bs.failed > 0 && <span className="text-rose-400">{bs.failed} failed</span>}
                                  <span className={`font-medium ${pct >= 90 ? 'text-emerald-400' : pct >= 50 ? 'text-cyan-400' : 'text-amber-400'}`}>
                                    {pct}%
                                  </span>
                                </div>
                              </div>
                              <div className="h-1.5 bg-black/50 rounded-full overflow-hidden">
                                <div 
                                  className={`h-full transition-all duration-300 ${
                                    pct >= 90 ? 'bg-emerald-500' : 
                                    pct >= 50 ? 'bg-cyan-500' : 'bg-amber-500'
                                  }`}
                                  style={{ width: `${pct}%` }}
                                />
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
                  
                  {/* Active Collection Details */}
                  {hasActiveCollections && (
                    <>
                      <div>
                        <p className="text-xs font-medium text-zinc-400 mb-2">Active Collections</p>
                        {detailedProgress.active_collections.map((col, i) => (
                          <div key={i} className="p-3 rounded-xl bg-black/40 border border-cyan-500/20 mb-2">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-sm font-bold text-white">{col.bar_size}</span>
                              <span className="text-xs text-cyan-400">{col.progress}%</span>
                            </div>
                            <div className="w-full h-2 bg-zinc-800 rounded-full overflow-hidden mb-2">
                              <div 
                                className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all"
                                style={{ width: `${col.progress}%` }}
                              />
                            </div>
                            <div className="flex justify-between text-[10px] text-zinc-500">
                              <span>{col.completed}/{col.total} symbols</span>
                              <span>ETA: {col.eta || 'Calculating...'}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                      <button
                        onClick={handleCancelAll}
                        disabled={cancelling}
                        className="w-full py-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-medium hover:bg-rose-500/20 transition-colors disabled:opacity-50"
                      >
                        {cancelling ? 'Cancelling...' : 'Cancel All Collections'}
                      </button>
                    </>
                  )}
                  
                  {/* No Active Collections */}
                  {!hasActiveCollections && !collectionMode?.collection_mode?.active && (
                    <div className="text-center py-6">
                      <CheckCircle className="w-8 h-8 text-emerald-500/50 mx-auto mb-2" />
                      <p className="text-zinc-500 text-sm">No active collections</p>
                      <p className="text-zinc-600 text-xs mt-1">Start a collection from the "Collect" tab</p>
                      <p className="text-zinc-600 text-xs">or run <code className="bg-black/40 px-1 rounded">StartCollection.bat</code> for full-speed mode</p>
                    </div>
                  )}
                </div>
              ) : (
                /* Collection Settings */
                <div className="space-y-4">
                  {/* Lookback Selection */}
                  <div>
                    <label className="text-xs font-medium text-zinc-400 mb-2 block">Lookback Period</label>
                    <div className="grid grid-cols-5 gap-2">
                      {lookbackPresets.map(preset => (
                        <button
                          key={preset.value}
                          onClick={() => setLookbackDays(preset.value)}
                          className={`p-2 rounded-lg border text-center transition-all ${
                            lookbackDays === preset.value
                              ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                              : 'bg-black/30 border-white/10 text-zinc-400 hover:border-white/20'
                          }`}
                        >
                          <p className="text-xs font-bold">{preset.label}</p>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Tier Selection */}
                  <div>
                    <label className="text-xs font-medium text-zinc-400 mb-2 block">Symbol Filter (ADV Tier)</label>
                    <div className="grid grid-cols-2 gap-2">
                      {tierOptions.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => setTier(opt.value)}
                          className={`p-3 rounded-xl border text-left transition-all ${
                            tier === opt.value
                              ? 'bg-cyan-500/10 border-cyan-500/50'
                              : 'bg-black/30 border-white/10 hover:border-white/20'
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <opt.icon className={`w-4 h-4 ${tier === opt.value ? 'text-cyan-400' : 'text-zinc-500'}`} />
                            <span className={`text-sm font-bold ${tier === opt.value ? 'text-cyan-400' : 'text-white'}`}>
                              {opt.label}
                            </span>
                          </div>
                          <p className="text-[10px] text-zinc-500">{opt.adv}</p>
                          <p className="text-[9px] text-zinc-600 mt-1">{opt.timeframes}</p>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Smart Options */}
                  <div className="p-3 rounded-xl bg-black/20 border border-white/5 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-medium text-white">Skip Recent Data</p>
                        <p className="text-[10px] text-zinc-500">Don't re-fetch symbols collected within threshold</p>
                      </div>
                      <button
                        onClick={() => setSkipRecent(!skipRecent)}
                        className={`w-10 h-5 rounded-full transition-colors ${
                          skipRecent ? 'bg-cyan-500' : 'bg-zinc-700'
                        }`}
                      >
                        <div className={`w-4 h-4 rounded-full bg-white transition-transform ${
                          skipRecent ? 'translate-x-5' : 'translate-x-0.5'
                        }`} />
                      </button>
                    </div>
                    
                    {skipRecent && (
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-zinc-500">Threshold:</span>
                        <select
                          value={recentThreshold}
                          onChange={(e) => setRecentThreshold(parseInt(e.target.value))}
                          className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs text-white"
                        >
                          <option value={1}>1 day</option>
                          <option value={3}>3 days</option>
                          <option value={7}>7 days</option>
                          <option value={14}>14 days</option>
                          <option value={30}>30 days</option>
                        </select>
                      </div>
                    )}
                    
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-zinc-500">Max symbols:</span>
                      <select
                        value={maxSymbols || 'all'}
                        onChange={(e) => setMaxSymbols(e.target.value === 'all' ? null : parseInt(e.target.value))}
                        className="bg-black/40 border border-white/10 rounded px-2 py-1 text-xs text-white"
                      >
                        <option value="all">All</option>
                        <option value={50}>50</option>
                        <option value={100}>100</option>
                        <option value={250}>250</option>
                        <option value={500}>500</option>
                        <option value={1000}>1000</option>
                      </select>
                    </div>
                  </div>

                  {/* Estimated Time */}
                  <div className="flex items-center justify-between p-3 rounded-xl bg-blue-500/5 border border-blue-500/20">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-blue-400" />
                      <span className="text-xs text-blue-400">Estimated time:</span>
                    </div>
                    <span className="text-sm font-bold text-blue-400">{estimatedTime()}</span>
                  </div>

                  {/* Start Button */}
                  <button
                    onClick={startCollection}
                    disabled={collecting || hasActiveCollections}
                    className={`w-full py-3 rounded-xl font-medium text-sm transition-all ${
                      collecting || hasActiveCollections
                        ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
                        : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400 shadow-lg shadow-cyan-500/20'
                    }`}
                    data-testid="start-collection-btn"
                  >
                    {collecting ? (
                      <span className="flex items-center justify-center gap-2">
                        <Loader className="w-4 h-4 animate-spin" />
                        Starting...
                      </span>
                    ) : hasActiveCollections ? (
                      'Collection in progress...'
                    ) : (
                      <span className="flex items-center justify-center gap-2">
                        <Play className="w-4 h-4" />
                        Start Per-Stock Collection
                      </span>
                    )}
                  </button>

                  {/* Info Box */}
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
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ==================== SIMULATION PANEL (NEW) ====================

const SimulationQuickPanel = memo(({ jobs, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  const [starting, setStarting] = useState(null); // null, 'quick', or 'market'
  const [simBarSize, setSimBarSize] = useState('1 day');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [useMultiTimeframe, setUseMultiTimeframe] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState('default');
  const [maxSymbols, setMaxSymbols] = useState(1500);

  // Predefined strategies from the system
  const strategies = [
    { value: 'default', label: 'Default (Momentum)', setup_type: 'MOMENTUM' },
    { value: 'gap_go', label: 'Gap & Go', setup_type: 'GAP_AND_GO' },
    { value: 'orb', label: 'Opening Range Breakout', setup_type: 'ORB' },
    { value: 'vwap_bounce', label: 'VWAP Bounce', setup_type: 'VWAP_BOUNCE' },
    { value: 'rvol_surge', label: 'RVOL Surge', setup_type: 'RVOL_SURGE' },
    { value: 'rubberband', label: 'Rubberband Long', setup_type: 'RUBBERBAND_LONG' }
  ];

  // Bar size options for simulation
  const simBarSizes = [
    { value: '1 min', label: '1 Min', description: 'Scalp' },
    { value: '5 mins', label: '5 Min', description: 'Intraday' },
    { value: '15 mins', label: '15 Min', description: 'Day Trade' },
    { value: '1 day', label: 'Daily', description: 'Swing' }
  ];

  const handleQuickTest = async () => {
    setStarting('quick');
    try {
      const res = await fetch(`${API_BASE}/api/simulation/quick-test?bar_size=${encodeURIComponent(simBarSize)}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(`Smart Test started: ${data.symbols_count} symbols on ${simBarSize} bars`);
        if (onRefresh) onRefresh();
      } else {
        toast.error('Failed to start simulation');
      }
    } catch (err) {
      toast.error('Error starting simulation');
    } finally {
      setStarting(null);
    }
  };

  const handleMarketWideBacktest = async () => {
    setStarting('market');
    try {
      const strategyConfig = strategies.find(s => s.value === selectedStrategy) || strategies[0];
      
      const res = await fetch(`${API_BASE}/api/backtest/market-wide`, { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy: {
            name: strategyConfig.label,
            setup_type: strategyConfig.setup_type,
            min_tqs_score: 60,
            stop_pct: 2.0,
            target_pct: 4.0
          },
          bar_size: simBarSize,
          use_multi_timeframe: useMultiTimeframe,
          max_symbols: maxSymbols,
          run_in_background: true
        })
      });
      const data = await res.json();
      if (data.success || data.job_id) {
        const mtfNote = useMultiTimeframe ? ' (Multi-TF)' : '';
        toast.success(`Market-wide backtest started: ${maxSymbols} symbols, ${simBarSize}${mtfNote}`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || data.detail || 'Failed to start market-wide backtest');
      }
    } catch (err) {
      toast.error('Error starting market-wide backtest');
    } finally {
      setStarting(null);
    }
  };

  const recentJobs = jobs?.slice(0, 6) || [];
  const completedJobs = jobs?.filter(j => j.status === 'completed') || [];
  const runningJobs = jobs?.filter(j => j.status === 'running') || [];
  
  // Calculate overall stats from completed jobs
  const totalTrades = completedJobs.reduce((sum, j) => sum + (j.total_trades || 0), 0);
  const avgWinRate = completedJobs.length > 0
    ? completedJobs.reduce((sum, j) => sum + (j.win_rate || 0), 0) / completedJobs.length
    : 0;

  // Format date nicely
  const formatDate = (dateStr) => {
    if (!dateStr) return '--';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-violet-500/20">
            <History className="w-4 h-4 text-violet-400" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Historical Simulations</h3>
            <p className="text-xs text-zinc-400">
              {runningJobs.length > 0 
                ? `${runningJobs.length} running, ${completedJobs.length} completed`
                : `${completedJobs.length} backtests completed`
              }
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
              {/* Bar Size Selector for Simulations */}
              <div className="mb-4">
                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1 mb-2"
                  data-testid="toggle-sim-settings"
                >
                  <Settings className="w-3 h-3" />
                  {showAdvanced ? 'Hide Settings' : 'Simulation Settings'}
                </button>
                
                <AnimatePresence>
                  {showAdvanced && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="mb-3 space-y-3"
                    >
                      {/* Bar Size Selection */}
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">Timeframe</label>
                        <div className="flex gap-2">
                          {simBarSizes.map((opt) => {
                            const isSelected = simBarSize === opt.value;
                            return (
                              <button
                                key={opt.value}
                                onClick={() => setSimBarSize(opt.value)}
                                className={`flex-1 px-2 py-1.5 rounded-lg border text-xs transition-all ${
                                  isSelected
                                    ? 'bg-violet-500/20 border-violet-500/50 text-violet-400'
                                    : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/5'
                                }`}
                                data-testid={`sim-bar-size-${opt.value.replace(/\s+/g, '-')}`}
                              >
                                <div className="font-medium">{opt.label}</div>
                                <div className="text-[10px] text-zinc-500">{opt.description}</div>
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Strategy Selection */}
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">Strategy</label>
                        <select
                          value={selectedStrategy}
                          onChange={(e) => setSelectedStrategy(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg bg-white/[0.02] border border-white/5 text-sm text-zinc-200 focus:outline-none focus:border-violet-500/50"
                          data-testid="strategy-select"
                        >
                          {strategies.map((s) => (
                            <option key={s.value} value={s.value}>{s.label}</option>
                          ))}
                        </select>
                      </div>

                      {/* Max Symbols Slider */}
                      <div>
                        <label className="block text-xs text-zinc-400 mb-1.5">
                          Max Symbols: <span className="text-violet-400">{maxSymbols.toLocaleString()}</span>
                        </label>
                        <input
                          type="range"
                          min="100"
                          max="1500"
                          step="100"
                          value={maxSymbols}
                          onChange={(e) => setMaxSymbols(parseInt(e.target.value))}
                          className="w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-violet-500"
                          data-testid="max-symbols-slider"
                        />
                        <div className="flex justify-between text-[10px] text-zinc-500 mt-0.5">
                          <span>100</span>
                          <span>1,500</span>
                        </div>
                      </div>

                      {/* Multi-Timeframe Toggle */}
                      <div className="flex items-center justify-between p-2 rounded-lg bg-white/[0.02] border border-white/5">
                        <div>
                          <div className="text-xs text-zinc-300">Multi-Timeframe Analysis</div>
                          <div className="text-[10px] text-zinc-500">
                            Daily trend + {simBarSize} entries
                          </div>
                        </div>
                        <button
                          onClick={() => setUseMultiTimeframe(!useMultiTimeframe)}
                          className={`w-10 h-5 rounded-full transition-all ${
                            useMultiTimeframe 
                              ? 'bg-violet-500' 
                              : 'bg-zinc-700'
                          }`}
                          data-testid="multi-timeframe-toggle"
                        >
                          <div className={`w-4 h-4 rounded-full bg-white shadow transform transition-transform ${
                            useMultiTimeframe ? 'translate-x-5' : 'translate-x-0.5'
                          }`} />
                        </button>
                      </div>

                      <p className="text-[10px] text-zinc-500">
                        {useMultiTimeframe 
                          ? 'Only takes trades aligned with daily trend direction'
                          : 'Intraday simulations require collected intraday data'
                        }
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-2 gap-2 mb-4">
                <button
                  onClick={handleQuickTest}
                  disabled={starting !== null}
                  className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 transition-colors text-sm font-medium disabled:opacity-50"
                  data-testid="quick-simulation-btn"
                >
                  {starting === 'quick' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Zap className="w-4 h-4" />
                  )}
                  Smart Test
                  <span className="text-[10px] text-violet-400/60">(30 symbols)</span>
                </button>
                <button
                  onClick={handleMarketWideBacktest}
                  disabled={starting !== null}
                  className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500/20 to-violet-500/20 text-cyan-400 hover:from-cyan-500/30 hover:to-violet-500/30 transition-colors text-sm font-medium disabled:opacity-50"
                  data-testid="market-wide-backtest-btn"
                >
                  {starting === 'market' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <BarChart3 className="w-4 h-4" />
                  )}
                  Full Test
                  <span className="text-[10px] text-cyan-400/60">({maxSymbols.toLocaleString()} symbols)</span>
                </button>
              </div>

              {/* Overall Stats */}
              {completedJobs.length > 0 && (
                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="p-2 rounded bg-white/[0.02] text-center">
                    <div className="text-lg font-bold text-white">{completedJobs.length}</div>
                    <div className="text-[10px] text-zinc-500">Backtests</div>
                  </div>
                  <div className="p-2 rounded bg-white/[0.02] text-center">
                    <div className={`text-lg font-bold ${avgWinRate >= 0.5 ? 'text-green-400' : 'text-yellow-400'}`}>
                      {(avgWinRate * 100).toFixed(0)}%
                    </div>
                    <div className="text-[10px] text-zinc-500">Avg Win Rate</div>
                  </div>
                  <div className="p-2 rounded bg-white/[0.02] text-center">
                    <div className="text-lg font-bold text-white">{totalTrades}</div>
                    <div className="text-[10px] text-zinc-500">Total Trades</div>
                  </div>
                </div>
              )}

              {/* Job Cards with Inline Details */}
              {recentJobs.length > 0 ? (
                <div className="space-y-3">
                  <h4 className="text-xs text-zinc-500 uppercase">Recent Backtests</h4>
                  {recentJobs.map((job) => {
                    const isRunning = job.status === 'running';
                    const progress = job.symbols_total > 0 
                      ? Math.round((job.symbols_processed / job.symbols_total) * 100) 
                      : 0;
                    const symbols = job.config?.custom_symbols || [];
                    const dateRange = job.config 
                      ? `${formatDate(job.config.start_date)} - ${formatDate(job.config.end_date)}`
                      : '--';
                    
                    return (
                      <div
                        key={job.id || job.job_id}
                        className={`rounded-lg border ${
                          isRunning ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-white/5 bg-white/[0.02]'
                        } overflow-hidden`}
                      >
                        {/* Header Row */}
                        <div className="p-3 flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                              job.status === 'completed' ? 'bg-green-400' :
                              job.status === 'running' ? 'bg-cyan-400 animate-pulse' :
                              job.status === 'failed' ? 'bg-red-400' : 'bg-zinc-400'
                            }`} />
                            <div>
                              <div className="text-xs text-zinc-300 font-mono">{job.id || job.job_id}</div>
                              <div className="text-[10px] text-zinc-500">{dateRange}</div>
                            </div>
                          </div>
                          
                          {/* Status / Progress */}
                          {isRunning ? (
                            <div className="text-right">
                              <div className="text-sm font-bold text-cyan-400">{progress}%</div>
                              <div className="text-[10px] text-zinc-500">
                                {job.symbols_processed}/{job.symbols_total} symbols
                              </div>
                            </div>
                          ) : (
                            <span className={`text-xs px-2 py-0.5 rounded ${
                              job.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                              job.status === 'failed' ? 'bg-red-500/20 text-red-400' : 
                              'bg-zinc-500/20 text-zinc-400'
                            }`}>
                              {job.status}
                            </span>
                          )}
                        </div>

                        {/* Progress Bar for Running Jobs */}
                        {isRunning && (
                          <div className="px-3 pb-2">
                            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                              <div 
                                className="h-full bg-gradient-to-r from-cyan-500 to-cyan-400 rounded-full transition-all duration-500"
                                style={{ width: `${progress}%` }}
                              />
                            </div>
                          </div>
                        )}

                        {/* Results Grid for Completed Jobs */}
                        {job.status === 'completed' && (
                          <div className="px-3 pb-3 pt-1 border-t border-white/5">
                            <div className="grid grid-cols-5 gap-2 text-center">
                              <div>
                                <div className="text-sm font-bold text-white">{job.total_trades || 0}</div>
                                <div className="text-[9px] text-zinc-500">Trades</div>
                              </div>
                              <div>
                                <div className={`text-sm font-bold ${
                                  (job.win_rate || 0) >= 0.5 ? 'text-green-400' : 
                                  (job.win_rate || 0) > 0 ? 'text-yellow-400' : 'text-zinc-400'
                                }`}>
                                  {job.total_trades > 0 ? `${(job.win_rate * 100).toFixed(0)}%` : '--'}
                                </div>
                                <div className="text-[9px] text-zinc-500">Win Rate</div>
                              </div>
                              <div>
                                <div className={`text-sm font-bold ${
                                  (job.profit_factor || 0) >= 1 ? 'text-green-400' : 
                                  (job.profit_factor || 0) > 0 ? 'text-yellow-400' : 'text-zinc-400'
                                }`}>
                                  {job.total_trades > 0 ? (job.profit_factor || 0).toFixed(2) : '--'}
                                </div>
                                <div className="text-[9px] text-zinc-500">PF</div>
                              </div>
                              <div>
                                <div className={`text-sm font-bold ${
                                  (job.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'
                                }`}>
                                  {job.total_trades > 0 ? `$${(job.total_pnl || 0).toFixed(0)}` : '--'}
                                </div>
                                <div className="text-[9px] text-zinc-500">P&L</div>
                              </div>
                              <div>
                                <div className="text-sm font-bold text-white">
                                  {job.symbols_total || symbols.length || 0}
                                </div>
                                <div className="text-[9px] text-zinc-500">Symbols</div>
                              </div>
                            </div>
                            
                            {/* Symbols Tested */}
                            {symbols.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {symbols.slice(0, 6).map((sym, idx) => (
                                  <span key={idx} className="px-1.5 py-0.5 rounded text-[9px] bg-white/5 text-zinc-400">
                                    {sym}
                                  </span>
                                ))}
                                {symbols.length > 6 && (
                                  <span className="px-1.5 py-0.5 rounded text-[9px] bg-white/5 text-zinc-500">
                                    +{symbols.length - 6} more
                                  </span>
                                )}
                              </div>
                            )}
                            
                            {/* No Trades Warning */}
                            {job.total_trades === 0 && (
                              <div className="mt-2 p-2 rounded bg-yellow-500/10 border border-yellow-500/20">
                                <p className="text-[10px] text-yellow-400 flex items-center gap-1">
                                  <AlertTriangle className="w-3 h-3" />
                                  No trade signals found in this period
                                </p>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Error Message for Failed Jobs */}
                        {job.status === 'failed' && job.error_message && (
                          <div className="px-3 pb-3">
                            <div className="p-2 rounded bg-red-500/10 border border-red-500/20">
                              <p className="text-[10px] text-red-400">{job.error_message}</p>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-6">
                  <FlaskConical className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                  <p className="text-sm text-zinc-400">No simulations yet</p>
                  <p className="text-xs text-zinc-500">Click "Quick Test" or "Market-Wide" to run a backtest</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ==================== SECTION COMPONENTS ====================

const IntelOverview = memo(({ data }) => {
  // Memoize metrics to prevent re-creating array on each render
  const metrics = useMemo(() => [
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
  ], [data.aiAccuracy, data.aiAccuracyTrend, data.liveStrategies, data.paperStrategies, data.learningHealth, data.calibrationsToday]);

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
      {metrics.map((metric, idx) => (
        <div
          key={metric.label}
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
              {metric.value}
            </div>
            <div className="text-xs text-zinc-400">{metric.label}</div>
            {metric.subtext && (
              <div className="text-[10px] text-zinc-500 mt-1">{metric.subtext}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
});

// ==================== MARKET SCANNER WRAPPER ====================
const MarketScannerWrapper = memo(() => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="market-scanner-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-emerald-500/20">
            <Search className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Market Scanner</h3>
            <p className="text-xs text-zinc-400">Find trading opportunities across the market</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
              <MarketScannerPanel />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

// ==================== ADVANCED TESTING WRAPPER ====================
const AdvancedTestingWrapper = memo(() => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="advanced-testing-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-amber-500/20">
            <Shuffle className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-white">Advanced Testing</h3>
            <p className="text-xs text-zinc-400">Multi-Strategy, Walk-Forward, Monte Carlo</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
              <AdvancedBacktestPanel />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

const AIPerformancePanel = memo(({ data, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  
  // Memoize modules to prevent recreation on each render
  const modules = useMemo(() => [
    { name: 'Time-Series AI', accuracy: data.timeseriesAccuracy, predictions: data.timeseriesPredictions, icon: Brain },
    { name: 'Bull Agent', winRate: data.bullWinRate, debates: data.bullDebates, icon: TrendingUp },
    { name: 'Bear Agent', winRate: data.bearWinRate, debates: data.bearDebates, icon: TrendingDown },
    { name: 'Risk Manager', interventions: data.riskInterventions, saved: data.riskSaved, icon: Shield }
  ], [data.timeseriesAccuracy, data.timeseriesPredictions, data.bullWinRate, data.bullDebates, data.bearWinRate, data.bearDebates, data.riskInterventions, data.riskSaved]);

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
                        {module.accuracy !== null ? `${(module.accuracy * 100).toFixed(1)}%` : '--'}
                      </span>
                    </div>
                  )}
                  
                  {module.winRate !== undefined && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">Win Rate</span>
                      <span className={`font-mono ${module.winRate >= 0.55 ? 'text-green-400' : 'text-yellow-400'}`}>
                        {module.winRate !== null ? `${(module.winRate * 100).toFixed(1)}%` : '--'}
                      </span>
                    </div>
                  )}
                  
                  {module.predictions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Predictions</span>
                      <span className="text-zinc-300 font-mono">{module.predictions?.toLocaleString() || '--'}</span>
                    </div>
                  )}
                  
                  {module.debates !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Debates</span>
                      <span className="text-zinc-300 font-mono">{module.debates ?? '--'}</span>
                    </div>
                  )}
                  
                  {module.interventions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Interventions</span>
                      <span className="text-zinc-300 font-mono">{module.interventions ?? '--'}</span>
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
});

const StrategyLifecyclePanel = memo(({ phases, candidates, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(true);
  
  // Memoize static objects to prevent recreation
  const phaseColors = useMemo(() => ({
    simulation: 'text-blue-400 bg-blue-500/20',
    paper: 'text-yellow-400 bg-yellow-500/20',
    live: 'text-green-400 bg-green-500/20',
    demoted: 'text-red-400 bg-red-500/20',
    disabled: 'text-zinc-400 bg-zinc-500/20'
  }), []);
  
  const phaseIcons = useMemo(() => ({
    simulation: FlaskConical,
    paper: Eye,
    live: Rocket,
    demoted: TrendingDown,
    disabled: Pause
  }), []);

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
                        <span className="text-lg font-bold text-white">{count ?? '-'}</span>
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
});

const PromotionWizardPanel = memo(({ candidates, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(true);
  const [promotingStrategy, setPromotingStrategy] = useState(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  
  const phaseColors = {
    simulation: 'text-blue-400 bg-blue-500/20 border-blue-500/30',
    paper: 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30',
    live: 'text-green-400 bg-green-500/20 border-green-500/30',
  };
  
  const phaseIcons = {
    simulation: FlaskConical,
    paper: Eye,
    live: Rocket,
  };
  
  const readyCandidates = candidates?.filter(c => c.meets_requirements) || [];
  const pendingCandidates = candidates?.filter(c => !c.meets_requirements) || [];
  
  const handlePromoteClick = (candidate) => {
    if (candidate.target_phase === 'live') {
      // LIVE promotion requires confirmation
      setSelectedCandidate(candidate);
      setShowConfirmModal(true);
    } else {
      // PAPER promotion can proceed directly
      handleConfirmPromotion(candidate);
    }
  };
  
  const handleConfirmPromotion = async (candidate) => {
    setPromotingStrategy(candidate.strategy_name);
    setShowConfirmModal(false);
    
    try {
      await onPromote(candidate.strategy_name, candidate.target_phase);
    } finally {
      setPromotingStrategy(null);
      setSelectedCandidate(null);
    }
  };

  if (!candidates || candidates.length === 0) {
    return null; // Don't show panel if no candidates
  }

  return (
    <>
      <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #f59e0b, #10b981)' }}>
              <ArrowUpRight className="w-4 h-4 text-white" />
            </div>
            <div className="text-left">
              <h3 className="text-sm font-semibold text-white">Strategy Promotion Wizard</h3>
              <p className="text-xs text-zinc-400">Review and approve strategy promotions</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {readyCandidates.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 animate-pulse">
                {readyCandidates.length} ready
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
                {/* Ready for Promotion */}
                {readyCandidates.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                      <CheckCircle2 className="w-3 h-3" />
                      Ready for Promotion ({readyCandidates.length})
                    </h4>
                    <div className="space-y-3">
                      {readyCandidates.map((candidate) => {
                        const CurrentIcon = phaseIcons[candidate.current_phase] || FlaskConical;
                        const TargetIcon = phaseIcons[candidate.target_phase] || Rocket;
                        const isPromoting = promotingStrategy === candidate.strategy_name;
                        const perf = candidate.performance || {};
                        
                        return (
                          <div
                            key={candidate.strategy_name}
                            className="p-3 rounded-lg border border-green-500/20 bg-green-500/5"
                          >
                            {/* Header */}
                            <div className="flex items-center justify-between mb-3">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold text-white">{candidate.strategy_name}</span>
                                <div className="flex items-center gap-1 text-xs text-zinc-400">
                                  <span className={`px-1.5 py-0.5 rounded ${phaseColors[candidate.current_phase]}`}>
                                    {candidate.current_phase}
                                  </span>
                                  <ChevronRight className="w-3 h-3" />
                                  <span className={`px-1.5 py-0.5 rounded ${phaseColors[candidate.target_phase]}`}>
                                    {candidate.target_phase}
                                  </span>
                                </div>
                              </div>
                              <button
                                onClick={() => handlePromoteClick(candidate)}
                                disabled={isPromoting}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors text-xs font-medium disabled:opacity-50"
                              >
                                {isPromoting ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                  <Rocket className="w-3 h-3" />
                                )}
                                {isPromoting ? 'Promoting...' : `Promote to ${candidate.target_phase.toUpperCase()}`}
                              </button>
                            </div>
                            
                            {/* Performance Stats */}
                            <div className="grid grid-cols-4 gap-2 text-xs">
                              <div className="p-2 rounded bg-white/[0.03]">
                                <div className="text-zinc-500">Trades</div>
                                <div className="text-white font-mono">{perf.total_trades || 0}</div>
                              </div>
                              <div className="p-2 rounded bg-white/[0.03]">
                                <div className="text-zinc-500">Win Rate</div>
                                <div className={`font-mono ${(perf.win_rate || 0) >= 0.5 ? 'text-green-400' : 'text-yellow-400'}`}>
                                  {((perf.win_rate || 0) * 100).toFixed(0)}%
                                </div>
                              </div>
                              <div className="p-2 rounded bg-white/[0.03]">
                                <div className="text-zinc-500">Avg R</div>
                                <div className={`font-mono ${(perf.avg_r_multiple || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  {(perf.avg_r_multiple || 0).toFixed(2)}R
                                </div>
                              </div>
                              <div className="p-2 rounded bg-white/[0.03]">
                                <div className="text-zinc-500">Days</div>
                                <div className="text-white font-mono">{perf.days_in_phase || 0}</div>
                              </div>
                            </div>
                            
                            {/* Warning for LIVE promotion */}
                            {candidate.target_phase === 'live' && (
                              <div className="mt-2 p-2 rounded bg-yellow-500/10 border border-yellow-500/20 text-xs text-yellow-400 flex items-start gap-2">
                                <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                <span>This will enable REAL money trading for this strategy</span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                
                {/* Not Yet Ready */}
                {pendingCandidates.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Clock className="w-3 h-3" />
                      Not Yet Ready ({pendingCandidates.length})
                    </h4>
                    <div className="space-y-2">
                      {pendingCandidates.slice(0, 5).map((candidate) => {
                        const perf = candidate.performance || {};
                        
                        return (
                          <div
                            key={candidate.strategy_name}
                            className="p-3 rounded-lg border border-white/5 bg-white/[0.02]"
                          >
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-zinc-300">{candidate.strategy_name}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${phaseColors[candidate.current_phase]}`}>
                                  {candidate.current_phase}
                                </span>
                              </div>
                              <span className="text-xs text-zinc-500">
                                → {candidate.target_phase}
                              </span>
                            </div>
                            
                            {/* Quick stats */}
                            <div className="flex items-center gap-4 text-xs text-zinc-500">
                              <span>{perf.total_trades || 0} trades</span>
                              <span>{((perf.win_rate || 0) * 100).toFixed(0)}% WR</span>
                              <span>{(perf.avg_r_multiple || 0).toFixed(2)}R</span>
                            </div>
                            
                            {/* Issues */}
                            {candidate.issues && candidate.issues.length > 0 && (
                              <div className="mt-2 text-xs text-red-400/80">
                                <span className="text-zinc-500">Missing: </span>
                                {candidate.issues.slice(0, 2).join(' • ')}
                                {candidate.issues.length > 2 && ` +${candidate.issues.length - 2} more`}
                              </div>
                            )}
                          </div>
                        );
                      })}
                      {pendingCandidates.length > 5 && (
                        <div className="text-xs text-zinc-500 text-center py-2">
                          +{pendingCandidates.length - 5} more strategies in progress
                        </div>
                      )}
                    </div>
                  </div>
                )}
                
                {/* Empty state */}
                {candidates.length === 0 && (
                  <div className="text-center py-6">
                    <FlaskConical className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                    <p className="text-sm text-zinc-400">No promotion candidates</p>
                    <p className="text-xs text-zinc-500 mt-1">Run simulations and paper trades to see candidates here</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      
      {/* Confirmation Modal for LIVE promotions */}
      <AnimatePresence>
        {showConfirmModal && selectedCandidate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0, 0, 0, 0.8)' }}
            onClick={() => setShowConfirmModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-md rounded-xl border border-white/10 p-6"
              style={{ background: 'rgba(21, 28, 36, 0.98)' }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-yellow-500/20 flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-yellow-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Confirm LIVE Promotion</h3>
                  <p className="text-sm text-zinc-400">This action enables real money trading</p>
                </div>
              </div>
              
              <div className="p-4 rounded-lg bg-yellow-500/10 border border-yellow-500/20 mb-4">
                <p className="text-sm text-yellow-400 mb-2">
                  You are about to promote <strong>{selectedCandidate.strategy_name}</strong> to LIVE status.
                </p>
                <ul className="text-xs text-zinc-400 space-y-1">
                  <li>• Real trades will be executed when this strategy triggers</li>
                  <li>• Actual money will be at risk</li>
                  <li>• Make sure you've reviewed the performance metrics</li>
                </ul>
              </div>
              
              {/* Performance summary */}
              <div className="grid grid-cols-3 gap-2 mb-4">
                <div className="p-2 rounded bg-white/[0.03] text-center">
                  <div className="text-lg font-bold text-white">{selectedCandidate.performance?.total_trades || 0}</div>
                  <div className="text-[10px] text-zinc-500">Paper Trades</div>
                </div>
                <div className="p-2 rounded bg-white/[0.03] text-center">
                  <div className={`text-lg font-bold ${(selectedCandidate.performance?.win_rate || 0) >= 0.52 ? 'text-green-400' : 'text-yellow-400'}`}>
                    {((selectedCandidate.performance?.win_rate || 0) * 100).toFixed(0)}%
                  </div>
                  <div className="text-[10px] text-zinc-500">Win Rate</div>
                </div>
                <div className="p-2 rounded bg-white/[0.03] text-center">
                  <div className={`text-lg font-bold ${(selectedCandidate.performance?.avg_r_multiple || 0) >= 0.4 ? 'text-green-400' : 'text-yellow-400'}`}>
                    {(selectedCandidate.performance?.avg_r_multiple || 0).toFixed(2)}R
                  </div>
                  <div className="text-[10px] text-zinc-500">Avg R</div>
                </div>
              </div>
              
              <div className="flex gap-3">
                <button
                  onClick={() => setShowConfirmModal(false)}
                  className="flex-1 px-4 py-2 rounded-lg border border-white/10 text-zinc-400 hover:bg-white/5 transition-colors text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleConfirmPromotion(selectedCandidate)}
                  className="flex-1 px-4 py-2 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors text-sm font-medium flex items-center justify-center gap-2"
                >
                  <Rocket className="w-4 h-4" />
                  Confirm & Go LIVE
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
});

const LearningConnectorsPanel = memo(({ connectors, thresholds, loading, onRunCalibrations }) => {
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
});

const ReportCardPanel = memo(({ reportCard, loading }) => {
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
});

// ==================== MAIN COMPONENT ====================

const NIA = () => {
  // Data cache for persistent data across tab switches
  const { getCached, setCached, shouldRefresh } = useDataCache();
  const isFirstMount = useRef(true);
  
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  
  // Track if initial load has completed - after this, hide loading spinners
  // to prevent flickering on background refreshes
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  
  // Only show loading on first load, not on background refreshes
  const stableLoading = loading && !initialLoadDone;
  
  // Initialize data from cache if available
  const cachedData = getCached('niaData');
  const [data, setData] = useState(() => {
    // If we have cached data, use it immediately
    if (cachedData?.data) {
      return cachedData.data;
    }
    // Default initial state
    return {
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
    };
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
        reportCardRes,
        // New: Collection and Simulation data
        collectionStatsRes,
        collectionQueueRes,
        simulationJobsRes
      ] = await Promise.allSettled([
        api.get('/api/strategy-promotion/phases'),
        api.get('/api/strategy-promotion/candidates'),
        api.get('/api/learning-connectors/status'),
        api.get('/api/learning-connectors/thresholds'),
        api.get('/api/ai-modules/timeseries/status'),
        api.get('/api/ai-modules/debate/ai-advisor-status'),
        api.get('/api/ai-modules/shadow/stats'),
        api.get('/api/ai-modules/report-card'),
        // New: Collection and Simulation endpoints
        api.get('/api/ib-collector/stats'),
        api.get('/api/ib-collector/queue-progress'),
        api.get('/api/simulation/jobs?limit=10')
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
        // Check model.metrics.accuracy (not test_accuracy)
        newData.timeseriesAccuracy = ts?.model?.metrics?.accuracy || null;
        // Check model.trained flag directly
        newData.timeseriesTrained = ts?.model?.trained || false;
        newData.timeseriesPredictions = ts?.model?.metrics?.training_samples || 0;
        newData.aiAccuracy = ts?.model?.metrics?.accuracy || null;
        newData.timeseriesLastTrained = ts?.model?.metrics?.last_trained || null;
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

      // Process collection stats
      if (collectionStatsRes.status === 'fulfilled' && collectionStatsRes.value.data?.success) {
        newData.collectionStats = collectionStatsRes.value.data.stats;
        newData.historicalBars = collectionStatsRes.value.data.stats?.total_bars || 0;
      }

      // Process collection queue progress
      if (collectionQueueRes.status === 'fulfilled' && collectionQueueRes.value.data?.success) {
        newData.collectionQueue = collectionQueueRes.value.data;
      }

      // Process simulation jobs
      if (simulationJobsRes.status === 'fulfilled' && simulationJobsRes.value.data?.success) {
        newData.simulationJobs = simulationJobsRes.value.data.jobs || [];
        newData.simulationsRun = (simulationJobsRes.value.data.jobs || []).filter(j => j.status === 'completed').length;
      }

      // Calculate learning progress data
      // Use timeseriesTrained flag OR accuracy to determine if model is trained
      newData.modelTrained = newData.timeseriesTrained || newData.timeseriesAccuracy !== null;
      newData.calibrationsApplied = newData.calibrationsToday || 0;
      newData.predictionsTracked = newData.timeseriesPredictions || 0;
      newData.alertsAnalyzed = newData.calibrationsApplied * 5; // Estimate

      // Only update state if data actually changed to prevent flickering
      setData(prevData => {
        const prevStr = JSON.stringify(prevData);
        const newStr = JSON.stringify(newData);
        if (prevStr === newStr) {
          return prevData; // Return same reference if unchanged
        }
        return newData;
      });
      
      // Save to cache for instant display on tab switches (60 second TTL)
      setCached('niaData', newData, 60000);

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
      setInitialLoadDone(true); // Mark initial load complete - hide spinners from now on
    }
  }, [setCached]);

  useEffect(() => {
    // If we have cached data, show it immediately and refresh in background
    const cached = getCached('niaData');
    if (cached?.data && isFirstMount.current) {
      setData(cached.data);
      setLoading(false);
      // Background refresh if cache is stale
      if (cached.isStale) {
        fetchAllData();
      }
    } else {
      fetchAllData();
    }
    isFirstMount.current = false;
    
    // Refresh every 60 seconds
    const interval = setInterval(() => fetchAllData(), 60000);
    return () => clearInterval(interval);
  }, [fetchAllData, getCached]);

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

  // Memoized callbacks to prevent child re-renders
  const handleRefresh = useCallback(() => fetchAllData(), [fetchAllData]);
  const handleRefreshWithToast = useCallback(() => fetchAllData(true), [fetchAllData]);
  const noopCallback = useCallback(() => {}, []);
  const handleTrainComplete = useCallback(() => fetchAllData(true), [fetchAllData]);
  
  // Memoized data objects to prevent unnecessary re-renders
  const collectionData = useMemo(() => ({
    queueProgress: data.collectionQueue,
    stats: data.collectionStats
  }), [data.collectionQueue, data.collectionStats]);

  // Memoized data slices for each component to prevent re-renders
  const intelOverviewData = useMemo(() => ({
    aiAccuracy: data.aiAccuracy,
    aiAccuracyTrend: data.aiAccuracyTrend,
    liveStrategies: data.liveStrategies,
    paperStrategies: data.paperStrategies,
    learningHealth: data.learningHealth,
    calibrationsToday: data.calibrationsToday
  }), [data.aiAccuracy, data.aiAccuracyTrend, data.liveStrategies, data.paperStrategies, data.learningHealth, data.calibrationsToday]);

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
    timeseriesPredictions: data.timeseriesPredictions,
    bullWinRate: data.bullWinRate,
    bullDebates: data.bullDebates,
    bearWinRate: data.bearWinRate,
    bearDebates: data.bearDebates,
    riskInterventions: data.riskInterventions,
    riskSaved: data.riskSaved,
    aiAdvisorWeight: data.aiAdvisorWeight
  }), [data.timeseriesAccuracy, data.timeseriesPredictions, data.bullWinRate, data.bullDebates, data.bearWinRate, data.bearDebates, data.riskInterventions, data.riskSaved, data.aiAdvisorWeight]);

  // Memoize phases and candidates to prevent Strategy panels from flickering
  const memoizedPhases = useMemo(() => data.phases, [data.phases]);
  const memoizedCandidates = useMemo(() => data.candidates, [data.candidates]);
  const memoizedSimulationJobs = useMemo(() => data.simulationJobs, [data.simulationJobs]);
  const memoizedReportCard = useMemo(() => data.reportCard, [data.reportCard]);

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

      {/* TRAIN ALL - Top Priority Action */}
      <TrainAllPanel onTrainComplete={handleTrainComplete} />

      {/* Intel Overview - doesn't need loading prop, will show data or placeholder */}
      <IntelOverview data={intelOverviewData} />

      {/* Learning Progress - Clear view of system intelligence */}
      <LearningProgressPanel data={learningProgressData} />

      {/* Data Collection - Unified panel for all timeframes */}
      <DataCollectionPanel 
        collectionData={collectionData}
        loading={stableLoading}
        onRefresh={handleRefresh}
      />

      {/* Historical Simulations */}
      <SimulationQuickPanel
        jobs={memoizedSimulationJobs}
        loading={stableLoading}
        onRefresh={handleRefresh}
      />

      {/* Market Scanner Panel */}
      <MarketScannerWrapper />

      {/* Advanced Testing Panel */}
      <AdvancedTestingWrapper />

      {/* AI Performance Panel */}
      <AIPerformancePanel 
        data={aiPerformanceData} 
        onRefresh={handleRefreshWithToast}
      />

      {/* Strategy Lifecycle Panel */}
      <StrategyLifecyclePanel
        phases={memoizedPhases}
        candidates={memoizedCandidates}
        loading={stableLoading}
        onPromote={handlePromote}
        onDemote={noopCallback}
      />

      {/* Strategy Promotion Wizard */}
      <PromotionWizardPanel
        candidates={memoizedCandidates}
        loading={stableLoading}
        onPromote={handlePromote}
        onDemote={noopCallback}
      />

      {/* Trading Report Card Panel */}
      <ReportCardPanel
        reportCard={memoizedReportCard}
        loading={stableLoading}
      />

      {/* Footer */}
      <div className="text-center text-xs text-zinc-600 mt-6">
        <span className="font-mono">NIA v2.0</span> • Neural Intelligence Agency • Part of <span className="text-cyan-500">SentCom</span>
      </div>
    </div>
  );
};

export default NIA;
