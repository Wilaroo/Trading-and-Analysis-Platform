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
 */

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Activity,
  TrendingUp,
  TrendingDown,
  Target,
  Shield,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
  ChevronRight,
  ChevronDown,
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
  StopCircle
} from 'lucide-react';
import { toast } from 'sonner';
import api from '../utils/api';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// ==================== TRAIN ALL PANEL ====================

const TrainAllPanel = ({ onTrainComplete }) => {
  const [isTraining, setIsTraining] = useState(false);
  const [currentStep, setCurrentStep] = useState(null);
  const [progress, setProgress] = useState({
    timeseries: { status: 'pending', message: '' },
    connectors: { status: 'pending', message: '' },
    calibration: { status: 'pending', message: '' },
    simulations: { status: 'pending', message: '' }
  });

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
              <p className="text-xs text-zinc-400">One-click system improvement</p>
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
};

// ==================== LEARNING PROGRESS PANEL ====================

const LearningProgressPanel = ({ data, loading }) => {
  const [expanded, setExpanded] = useState(true);

  // Calculate progress percentages
  const aiTrainingProgress = data.modelTrained ? 100 : (data.historicalBars > 0 ? 50 : 0);
  const scannerCalibrationProgress = data.calibrationsApplied > 0 ? Math.min(100, data.calibrationsApplied * 20) : 0;
  const predictionTrackingProgress = data.predictionsTracked > 0 ? Math.min(100, (data.predictionsTracked / 1000) * 100) : 0;
  const strategySimProgress = data.simulationsRun > 0 ? Math.min(100, data.simulationsRun * 25) : 0;

  // Build AI training detail message
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
};

// ==================== DATA COLLECTION PANEL (UNIFIED) ====================

const DataCollectionPanel = ({ collectionData, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  const [barSize, setBarSize] = useState('5 mins');
  const [lookback, setLookback] = useState('1_week');
  const [collectionType, setCollectionType] = useState('smart');
  const [collecting, setCollecting] = useState(false);
  const [showPresets, setShowPresets] = useState(false);
  const [presets, setPresets] = useState([]);
  const [timeframeStats, setTimeframeStats] = useState([]);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' or 'collect'
  
  // New state for detailed progress and modal
  const [detailedProgress, setDetailedProgress] = useState({ by_bar_size: [], active_collections: [] });
  const [showCollectionModal, setShowCollectionModal] = useState(false);
  const [pendingCollection, setPendingCollection] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  // Bar size options (prioritized for user's preference: 1min, 5min)
  const barSizeOptions = [
    { value: '1 min', label: '1 Min', icon: Zap, description: 'Scalping' },
    { value: '5 mins', label: '5 Min', icon: Activity, description: 'Day Trading' },
    { value: '15 mins', label: '15 Min', icon: Clock, description: 'Swing Entry' },
    { value: '1 hour', label: '1 Hour', icon: TrendingUp, description: 'Swing' },
    { value: '1 day', label: '1 Day', icon: BarChart3, description: 'Position' },
    { value: '1 week', label: '1 Week', icon: Layers, description: 'Investment' }
  ];

  // Lookback options
  const lookbackOptions = [
    { value: '1_day', label: '1 Day' },
    { value: '1_week', label: '1 Week' },
    { value: '30_days', label: '30 Days' },
    { value: '6_months', label: '6 Months' },
    { value: '1_year', label: '1 Year' },
    { value: '2_years', label: '2 Years' },
    { value: '5_years', label: '5 Years' }
  ];

  // Collection type options
  const collectionTypeOptions = [
    { value: 'smart', label: 'Smart', description: 'ADV-matched (recommended)' },
    { value: 'liquid', label: 'Liquid', description: 'ADV >= 100K' },
    { value: 'full_market', label: 'Full', description: 'All stocks (slow)' }
  ];

  // Fetch presets, timeframe stats, and detailed progress
  useEffect(() => {
    const fetchData = async () => {
      setLoadingPresets(true);
      try {
        const [presetsRes, statsRes, progressRes] = await Promise.allSettled([
          fetch(`${API_BASE}/api/ib-collector/collection-presets`),
          fetch(`${API_BASE}/api/ib-collector/timeframe-stats`),
          fetch(`${API_BASE}/api/ib-collector/queue-progress-detailed`)
        ]);
        
        if (presetsRes.status === 'fulfilled') {
          const data = await presetsRes.value.json();
          if (data.success) setPresets(data.presets || []);
        }
        
        if (statsRes.status === 'fulfilled') {
          const data = await statsRes.value.json();
          if (data.success) setTimeframeStats(data.by_timeframe || []);
        }
        
        if (progressRes.status === 'fulfilled') {
          const data = await progressRes.value.json();
          if (data.success) {
            setDetailedProgress({
              by_bar_size: data.by_bar_size || [],
              active_collections: data.active_collections || [],
              overall: data.overall || {}
            });
          }
        }
      } catch (err) {
        console.error('Error fetching collection data:', err);
      } finally {
        setLoadingPresets(false);
      }
    };
    fetchData();
    
    // Poll for progress updates every 5 seconds
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Check if there are active collections
  const hasActiveCollections = detailedProgress.active_collections?.length > 0;

  const handleStartCollectionClick = () => {
    if (hasActiveCollections) {
      // Show modal to ask user what to do
      setPendingCollection({ barSize, lookback, collectionType });
      setShowCollectionModal(true);
    } else {
      // No active collections, start directly
      startCollection(barSize, lookback, collectionType);
    }
  };

  const startCollection = async (bs, lb, ct) => {
    setCollecting(true);
    setShowCollectionModal(false);
    try {
      const res = await fetch(`${API_BASE}/api/ib-collector/multi-timeframe-collection?bar_size=${encodeURIComponent(bs)}&lookback=${lb}&collection_type=${ct}`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        toast.success(`Collection started: ${bs} bars, ${lb.replace('_', ' ')} lookback`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || 'Failed to start collection');
      }
    } catch (err) {
      toast.error('Error starting collection');
    } finally {
      setCollecting(false);
      setPendingCollection(null);
    }
  };

  const handleCancelAndStart = async () => {
    setCancelling(true);
    try {
      // Cancel all pending collections
      const res = await fetch(`${API_BASE}/api/ib-collector/cancel-all-pending`, { method: 'POST' });
      const data = await res.json();
      
      if (data.success) {
        toast.info(`Cancelled ${data.cancelled} pending requests`);
        // Now start the new collection
        if (pendingCollection) {
          await startCollection(pendingCollection.barSize, pendingCollection.lookback, pendingCollection.collectionType);
        }
      } else {
        toast.error('Failed to cancel current collections');
      }
    } catch (err) {
      toast.error('Error cancelling collections');
    } finally {
      setCancelling(false);
    }
  };

  const handleQueueNewCollection = () => {
    // Just start the new collection (it will queue behind existing)
    if (pendingCollection) {
      startCollection(pendingCollection.barSize, pendingCollection.lookback, pendingCollection.collectionType);
    }
  };

  const handleCancelBarSize = async (barSizeToCancel) => {
    setCancelling(true);
    try {
      const res = await fetch(`${API_BASE}/api/ib-collector/cancel-by-barsize?bar_size=${encodeURIComponent(barSizeToCancel)}`, { method: 'POST' });
      const data = await res.json();
      
      if (data.success) {
        toast.success(data.message || `Cancelled. ${data.saved || 0} symbols saved.`);
        if (onRefresh) onRefresh();
      } else {
        toast.error('Failed to cancel');
      }
    } catch (err) {
      toast.error('Error cancelling');
    } finally {
      setCancelling(false);
    }
  };

  const handleResumeCollection = async (barSizeToResume) => {
    setCollecting(true);
    try {
      const res = await fetch(`${API_BASE}/api/ib-collector/resume-collection?bar_size=${encodeURIComponent(barSizeToResume)}&retry_failed=true&collection_type=smart`, { 
        method: 'POST' 
      });
      const data = await res.json();
      
      if (data.success) {
        if (data.new_to_collect === 0) {
          toast.info(data.message || 'All symbols already collected');
        } else {
          toast.success(`Resumed: ${data.new_to_collect} symbols to collect (${data.already_completed} already done)`);
        }
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || 'Failed to resume');
      }
    } catch (err) {
      toast.error('Error resuming collection');
    } finally {
      setCollecting(false);
    }
  };

  const handleApplyPreset = (preset) => {
    setBarSize(preset.bar_size);
    setLookback(preset.lookback);
    setCollectionType(preset.collection_type);
    setShowPresets(false);
    setActiveTab('collect');
    toast.info(`Applied "${preset.name}" preset`);
  };

  const { queueProgress, stats } = collectionData || {};
  const totalSymbols = stats?.unique_symbols || 0;
  const totalBars = stats?.total_bars || 0;

  // Calculate total from timeframe stats
  const totalTimeframeSymbols = timeframeStats.reduce((sum, s) => sum + (s.unique_symbols || 0), 0);
  const totalTimeframeBars = timeframeStats.reduce((sum, s) => sum + (s.total_bars || 0), 0);
  const displaySymbols = totalSymbols || totalTimeframeSymbols;
  const displayBars = totalBars || totalTimeframeBars;

  return (
    <>
      {/* Collection Conflict Modal */}
      <AnimatePresence>
        {showCollectionModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={() => setShowCollectionModal(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-zinc-900 border border-white/10 rounded-xl p-6 max-w-md w-full shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                  <AlertCircle className="w-5 h-5 text-amber-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Collection In Progress</h3>
                  <p className="text-sm text-zinc-400">
                    {detailedProgress.active_collections?.length} active collection(s) running
                  </p>
                </div>
              </div>

              {/* Show active collections */}
              <div className="mb-4 p-3 rounded-lg bg-white/5 border border-white/10">
                <div className="text-xs text-zinc-400 mb-2">Currently collecting:</div>
                <div className="space-y-2">
                  {detailedProgress.active_collections?.map((col) => (
                    <div key={col.bar_size} className="flex items-center justify-between">
                      <span className="text-sm font-medium text-white">{col.bar_size}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-cyan-500 rounded-full" 
                            style={{ width: `${col.progress_pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-zinc-400">{col.progress_pct}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <p className="text-sm text-zinc-300 mb-4">
                You're about to start a new <span className="text-cyan-400 font-medium">{pendingCollection?.barSize}</span> collection. 
                What would you like to do?
              </p>

              <div className="space-y-2">
                <button
                  onClick={handleCancelAndStart}
                  disabled={cancelling}
                  className="w-full py-2.5 px-4 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400 text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {cancelling ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <XCircle className="w-4 h-4" />
                  )}
                  Cancel Current & Start New
                </button>
                
                <button
                  onClick={handleQueueNewCollection}
                  disabled={collecting}
                  className="w-full py-2.5 px-4 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/30 text-cyan-400 text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  <PlayCircle className="w-4 h-4" />
                  Add to Queue (Run After Current)
                </button>
                
                <button
                  onClick={() => setShowCollectionModal(false)}
                  className="w-full py-2.5 px-4 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 text-sm font-medium transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Panel */}
      <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }}>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
          data-testid="data-collection-panel-toggle"
        >
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${hasActiveCollections ? 'bg-orange-500/20' : 'bg-emerald-500/20'}`}>
              {hasActiveCollections ? (
                <Download className="w-4 h-4 text-orange-400 animate-pulse" />
              ) : (
                <Database className="w-4 h-4 text-emerald-400" />
              )}
            </div>
            <div className="text-left">
              <h3 className="text-sm font-semibold text-white">Data Collection</h3>
              <p className="text-xs text-zinc-400">
                {hasActiveCollections 
                  ? `${detailedProgress.active_collections?.length} collection(s) running` 
                  : displaySymbols > 0 
                    ? `${displaySymbols.toLocaleString()} symbols • ${displayBars.toLocaleString()} bars`
                    : 'No data collected yet'
                }
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {hasActiveCollections && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-400 animate-pulse">
                Active
              </span>
            )}
            {timeframeStats.length > 0 && !hasActiveCollections && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400">
                {timeframeStats.length} timeframe{timeframeStats.length !== 1 ? 's' : ''}
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
                {/* Active Collections Progress (when running) */}
                {hasActiveCollections && (
                  <div className="mb-4 p-3 rounded-lg bg-orange-500/10 border border-orange-500/20">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-orange-400">Active Collections</span>
                    </div>
                    <div className="space-y-3">
                      {detailedProgress.active_collections?.map((col) => (
                        <div key={col.bar_size} className="pb-3 border-b border-white/5 last:border-0 last:pb-0">
                          <div className="flex justify-between items-center text-xs mb-1">
                            <div className="flex items-center gap-2">
                              <span className="text-white font-medium">{col.bar_size}</span>
                              {col.eta_display && (
                                <span className="text-[10px] text-cyan-400 flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  ~{col.eta_display} left
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-zinc-400">
                                {col.completed}/{col.total} ({col.progress_pct}%)
                              </span>
                              <button
                                onClick={() => handleCancelBarSize(col.bar_size)}
                                disabled={cancelling}
                                className="text-[10px] text-amber-400 hover:text-amber-300 flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 transition-colors"
                                title="Cancel and save already collected data"
                              >
                                {cancelling ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                  <StopCircle className="w-3 h-3" />
                                )}
                                Cancel & Save
                              </button>
                            </div>
                          </div>
                          <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-gradient-to-r from-orange-500 to-amber-400 rounded-full transition-all"
                              style={{ width: `${col.progress_pct}%` }}
                            />
                          </div>
                          <div className="flex justify-between mt-1 text-[10px] text-zinc-500">
                            <span className="text-emerald-400">{col.completed} saved</span>
                            <span className="text-orange-400">{col.pending} pending</span>
                            {col.failed > 0 && <span className="text-red-400">{col.failed} failed</span>}
                            {col.symbols_per_minute && (
                              <span className="text-zinc-400">{col.symbols_per_minute} sym/min</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Resumable Collections (paused/cancelled that can be continued) */}
                {!hasActiveCollections && detailedProgress.by_bar_size?.some(col => 
                  col.completed > 0 && col.progress_pct < 100 && !col.is_active
                ) && (
                  <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-cyan-400">Resumable Collections</span>
                    </div>
                    <div className="space-y-2">
                      {detailedProgress.by_bar_size?.filter(col => 
                        col.completed > 0 && col.progress_pct < 100 && !col.is_active
                      ).map((col) => (
                        <div key={col.bar_size} className="flex items-center justify-between p-2 rounded bg-white/[0.02]">
                          <div>
                            <span className="text-xs font-medium text-white">{col.bar_size}</span>
                            <span className="text-[10px] text-zinc-500 ml-2">
                              {col.completed}/{col.total} ({col.progress_pct}%)
                            </span>
                          </div>
                          <button
                            onClick={() => handleResumeCollection(col.bar_size)}
                            disabled={collecting}
                            className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1 px-2 py-1 rounded bg-cyan-500/10 hover:bg-cyan-500/20 transition-colors"
                          >
                            {collecting ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <PlayCircle className="w-3 h-3" />
                            )}
                            Resume
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Tab Switcher */}
                <div className="flex gap-1 p-1 rounded-lg bg-white/5 mb-4">
                  <button
                    onClick={() => setActiveTab('overview')}
                    className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      activeTab === 'overview'
                        ? 'bg-white/10 text-white'
                        : 'text-zinc-400 hover:text-white'
                    }`}
                  >
                    Overview
                  </button>
                  <button
                    onClick={() => setActiveTab('collect')}
                    className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      activeTab === 'collect'
                        ? 'bg-white/10 text-white'
                        : 'text-zinc-400 hover:text-white'
                    }`}
                  >
                    + Collect New
                  </button>
                </div>

                {/* Overview Tab */}
                {activeTab === 'overview' && (
                  <div className="space-y-4">
                    {/* Summary Stats */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                        <div className="text-2xl font-bold text-white">{displaySymbols.toLocaleString()}</div>
                        <div className="text-xs text-zinc-500">Unique Symbols</div>
                      </div>
                      <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                        <div className="text-2xl font-bold text-white">{(displayBars / 1000).toFixed(0)}K</div>
                        <div className="text-xs text-zinc-500">Total Bars</div>
                      </div>
                    </div>

                    {/* Timeframe Breakdown */}
                    {timeframeStats.length > 0 ? (
                      <div>
                        <div className="text-xs text-zinc-400 mb-2">Data by Timeframe</div>
                        <div className="space-y-2">
                          {timeframeStats.map((stat) => (
                            <div 
                              key={stat.bar_size} 
                              className="flex items-center justify-between p-2 rounded-lg bg-white/[0.02] border border-white/5"
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-medium text-white">{stat.bar_size}</span>
                                <span className="text-[10px] text-zinc-500">
                                  {stat.date_range?.start && stat.date_range?.end 
                                    ? `${stat.date_range.start.slice(5)} → ${stat.date_range.end.slice(5)}`
                                    : ''
                                  }
                                </span>
                              </div>
                              <div className="flex items-center gap-3 text-xs">
                                <span className="text-emerald-400">{stat.unique_symbols?.toLocaleString()} sym</span>
                                <span className="text-zinc-400">{(stat.total_bars / 1000).toFixed(0)}K bars</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-4">
                        <HardDrive className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
                        <p className="text-sm text-zinc-400">No data collected yet</p>
                        <button
                          onClick={() => setActiveTab('collect')}
                          className="mt-2 text-xs text-cyan-400 hover:text-cyan-300"
                        >
                          Start collecting →
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* Collect New Tab */}
                {activeTab === 'collect' && (
                  <div className="space-y-4">
                    {/* Quick Presets */}
                    <div>
                      <button
                        onClick={() => setShowPresets(!showPresets)}
                        className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mb-2"
                        data-testid="show-presets-btn"
                      >
                        <Sparkles className="w-3 h-3" />
                        {showPresets ? 'Hide Presets' : 'Quick Presets'}
                      </button>
                      
                      <AnimatePresence>
                        {showPresets && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="grid grid-cols-2 gap-2 pb-3 border-b border-white/5"
                          >
                            {presets.slice(0, 6).map((preset) => (
                              <button
                                key={preset.name}
                                onClick={() => handleApplyPreset(preset)}
                                className="p-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/5 text-left transition-colors"
                                data-testid={`preset-${preset.name.toLowerCase().replace(/\s+/g, '-')}`}
                              >
                                <div className="text-xs font-medium text-white">{preset.name}</div>
                                <div className="text-[10px] text-zinc-500">{preset.bar_size} • {preset.lookback.replace('_', ' ')}</div>
                              </button>
                            ))}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>

                    {/* Bar Size Selector */}
                    <div>
                      <label className="block text-xs text-zinc-400 mb-2">Bar Size</label>
                      <div className="grid grid-cols-6 gap-1">
                        {barSizeOptions.map((opt) => {
                          const isSelected = barSize === opt.value;
                          return (
                            <button
                              key={opt.value}
                              onClick={() => setBarSize(opt.value)}
                              className={`p-2 rounded-lg border text-center transition-all ${
                                isSelected
                                  ? 'bg-amber-500/20 border-amber-500/50 text-amber-400'
                                  : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/5'
                              }`}
                              data-testid={`bar-size-${opt.value.replace(/\s+/g, '-')}`}
                            >
                              <div className="text-[10px] font-medium">{opt.label}</div>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Lookback Period */}
                    <div>
                      <label className="block text-xs text-zinc-400 mb-2">Lookback Period</label>
                      <div className="flex flex-wrap gap-1">
                        {lookbackOptions.map((opt) => {
                          const isSelected = lookback === opt.value;
                          return (
                            <button
                              key={opt.value}
                              onClick={() => setLookback(opt.value)}
                              className={`px-2 py-1 rounded text-[10px] border transition-all ${
                                isSelected
                                  ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                                  : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/5'
                              }`}
                              data-testid={`lookback-${opt.value}`}
                            >
                              {opt.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Collection Type */}
                    <div>
                      <label className="block text-xs text-zinc-400 mb-2">Collection Scope</label>
                      <div className="grid grid-cols-3 gap-2">
                        {collectionTypeOptions.map((opt) => {
                          const isSelected = collectionType === opt.value;
                          return (
                            <button
                              key={opt.value}
                              onClick={() => setCollectionType(opt.value)}
                              className={`p-2 rounded-lg border text-center transition-all ${
                                isSelected
                                  ? 'bg-violet-500/20 border-violet-500/50 text-violet-400'
                                  : 'bg-white/[0.02] border-white/5 text-zinc-400 hover:bg-white/5'
                              }`}
                              data-testid={`collection-type-${opt.value}`}
                            >
                              <div className="text-xs font-medium">{opt.label}</div>
                              <div className="text-[10px] text-zinc-500">{opt.description}</div>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Start Button */}
                    <button
                      onClick={handleStartCollectionClick}
                      disabled={collecting}
                      className="w-full flex items-center justify-center gap-2 py-3 rounded-lg font-medium text-sm transition-all"
                      style={{
                        background: collecting ? 'rgba(255,255,255,0.05)' : 'linear-gradient(135deg, #10b981, #06b6d4)',
                        color: collecting ? 'rgba(255,255,255,0.5)' : 'white'
                      }}
                      data-testid="start-collection-btn"
                    >
                      {collecting ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Starting...
                        </>
                      ) : (
                        <>
                          <PlayCircle className="w-4 h-4" />
                          Start Collection
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
};

// ==================== SIMULATION PANEL (NEW) ====================

const SimulationQuickPanel = ({ jobs, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  const [starting, setStarting] = useState(null); // null, 'quick', or 'market'
  const [simBarSize, setSimBarSize] = useState('1 day');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Bar size options for simulation
  const simBarSizes = [
    { value: '1 min', label: '1 Min', description: 'Scalp' },
    { value: '5 mins', label: '5 Min', description: 'Intraday' },
    { value: '1 day', label: 'Daily', description: 'Swing' }
  ];

  const handleQuickTest = async () => {
    setStarting('quick');
    try {
      const res = await fetch(`${API_BASE}/api/simulation/quick-test?bar_size=${encodeURIComponent(simBarSize)}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(`Quick test started: ${simBarSize} bars`);
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
      const res = await fetch(`${API_BASE}/api/backtest/market-wide`, { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          days_back: 30,
          strategies: ['all'],
          max_symbols: 1000,
          bar_size: simBarSize
        })
      });
      const data = await res.json();
      if (data.success || data.job_id) {
        toast.success(`Market-wide backtest started (${simBarSize} bars)`);
        if (onRefresh) onRefresh();
      } else {
        toast.error(data.error || 'Failed to start market-wide backtest');
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
                      className="mb-3"
                    >
                      <label className="block text-xs text-zinc-400 mb-1.5">Bar Size for Backtest</label>
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
                      <p className="text-[10px] text-zinc-500 mt-1.5">
                        Note: Intraday simulations require collected intraday data
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
                  Quick Test
                  <span className="text-[10px] text-violet-400/60">(10 symbols)</span>
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
                  Market-Wide
                  <span className="text-[10px] text-cyan-400/60">(1000 symbols)</span>
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
};

// ==================== SECTION COMPONENTS ====================

const IntelOverview = ({ data, loading }) => {
  const metrics = [
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
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
      {metrics.map((metric, idx) => (
        <motion.div
          key={metric.label}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.1 }}
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
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : metric.value}
            </div>
            <div className="text-xs text-zinc-400">{metric.label}</div>
            {metric.subtext && (
              <div className="text-[10px] text-zinc-500 mt-1">{metric.subtext}</div>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  );
};

const AIPerformancePanel = ({ data, loading, onRefresh }) => {
  const [expanded, setExpanded] = useState(true);
  
  const modules = [
    { name: 'Time-Series AI', accuracy: data.timeseriesAccuracy, predictions: data.timeseriesPredictions, icon: Brain },
    { name: 'Bull Agent', winRate: data.bullWinRate, debates: data.bullDebates, icon: TrendingUp },
    { name: 'Bear Agent', winRate: data.bearWinRate, debates: data.bearDebates, icon: TrendingDown },
    { name: 'Risk Manager', interventions: data.riskInterventions, saved: data.riskSaved, icon: Shield }
  ];

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
                        {loading ? '--' : `${(module.accuracy * 100).toFixed(1)}%`}
                      </span>
                    </div>
                  )}
                  
                  {module.winRate !== undefined && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">Win Rate</span>
                      <span className={`font-mono ${module.winRate >= 0.55 ? 'text-green-400' : 'text-yellow-400'}`}>
                        {loading ? '--' : `${(module.winRate * 100).toFixed(1)}%`}
                      </span>
                    </div>
                  )}
                  
                  {module.predictions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Predictions</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.predictions.toLocaleString()}</span>
                    </div>
                  )}
                  
                  {module.debates !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Debates</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.debates}</span>
                    </div>
                  )}
                  
                  {module.interventions !== undefined && (
                    <div className="flex items-center justify-between text-xs mt-1">
                      <span className="text-zinc-400">Interventions</span>
                      <span className="text-zinc-300 font-mono">{loading ? '--' : module.interventions}</span>
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
};

const StrategyLifecyclePanel = ({ phases, candidates, loading, onPromote, onDemote }) => {
  const [expanded, setExpanded] = useState(true);
  
  const phaseColors = {
    simulation: 'text-blue-400 bg-blue-500/20',
    paper: 'text-yellow-400 bg-yellow-500/20',
    live: 'text-green-400 bg-green-500/20',
    demoted: 'text-red-400 bg-red-500/20',
    disabled: 'text-zinc-400 bg-zinc-500/20'
  };
  
  const phaseIcons = {
    simulation: FlaskConical,
    paper: Eye,
    live: Rocket,
    demoted: TrendingDown,
    disabled: Pause
  };

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
                        <span className="text-lg font-bold text-white">{loading ? '-' : count}</span>
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
};

const PromotionWizardPanel = ({ candidates, loading, onPromote, onDemote }) => {
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
};

const LearningConnectorsPanel = ({ connectors, thresholds, loading, onRunCalibrations }) => {
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
};

const ReportCardPanel = ({ reportCard, loading }) => {
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
};

// ==================== MAIN COMPONENT ====================

const NIA = () => {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [data, setData] = useState({
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

      setData(newData);

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
    }
  }, []);

  useEffect(() => {
    fetchAllData();
    // Refresh every 60 seconds
    const interval = setInterval(() => fetchAllData(), 60000);
    return () => clearInterval(interval);
  }, [fetchAllData]);

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

  const handleRunCalibrations = async () => {
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
  };

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
      <TrainAllPanel onTrainComplete={() => fetchAllData(true)} />

      {/* Intel Overview */}
      <IntelOverview data={data} loading={loading} />

      {/* Learning Progress - Clear view of system intelligence */}
      <LearningProgressPanel data={data} loading={loading} />

      {/* Data Collection - Unified panel for all timeframes */}
      <DataCollectionPanel 
        collectionData={{
          queueProgress: data.collectionQueue,
          stats: data.collectionStats
        }}
        loading={loading}
        onRefresh={() => fetchAllData()}
      />

      {/* Historical Simulations */}
      <SimulationQuickPanel
        jobs={data.simulationJobs}
        loading={loading}
        onRefresh={() => fetchAllData()}
      />

      {/* AI Performance Panel */}
      <AIPerformancePanel 
        data={data} 
        loading={loading}
        onRefresh={() => fetchAllData(true)}
      />

      {/* Strategy Lifecycle Panel */}
      <StrategyLifecyclePanel
        phases={data.phases}
        candidates={data.candidates}
        loading={loading}
        onPromote={handlePromote}
        onDemote={() => {}}
      />

      {/* Strategy Promotion Wizard */}
      <PromotionWizardPanel
        candidates={data.candidates}
        loading={loading}
        onPromote={handlePromote}
        onDemote={() => {}}
      />

      {/* Trading Report Card Panel */}
      <ReportCardPanel
        reportCard={data.reportCard}
        loading={loading}
      />

      {/* Footer */}
      <div className="text-center text-xs text-zinc-600 mt-6">
        <span className="font-mono">NIA v2.0</span> • Neural Intelligence Agency • Part of <span className="text-cyan-500">SentCom</span>
      </div>
    </div>
  );
};

export default NIA;
