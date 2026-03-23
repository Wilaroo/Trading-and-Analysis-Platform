/**
 * Unified AI Training & Calibration Panel
 * ========================================
 * Single source of truth for all AI training operations.
 * Combines multi-timeframe model training with calibration workflow.
 * 
 * Features:
 * - Multi-timeframe model training (7 models from 39M+ bars)
 * - Quick Train: Daily model + calibration (daily refresh)
 * - Full Train: All 7 timeframe models
 * - Calibration: Scanner thresholds, module weights
 * - Training history with accuracy tracking
 */

import React, { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  Clock,
  TrendingUp,
  Zap,
  Target,
  Calendar,
  PlayCircle,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Database,
  BarChart3,
  RefreshCw,
  Layers,
  History,
  Settings,
  GitBranch,
  Gauge,
  Sparkles,
  AlertCircle,
  Globe
} from 'lucide-react';
import { toast } from 'sonner';
import api, { apiLongRunning } from '../utils/api';
import { useTrainingMode } from '../contexts';

// Timeframe configurations
const TIMEFRAME_CONFIG = {
  '1 min': { 
    icon: Zap, 
    label: '1 Minute', 
    shortLabel: '1m',
    description: 'Ultra-short scalping',
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
    borderColor: 'border-red-500/30'
  },
  '5 mins': { 
    icon: TrendingUp, 
    label: '5 Minutes',
    shortLabel: '5m',
    description: 'Intraday scalping',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/20',
    borderColor: 'border-orange-500/30'
  },
  '15 mins': { 
    icon: Clock, 
    label: '15 Minutes',
    shortLabel: '15m',
    description: 'Short-term swings',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/20',
    borderColor: 'border-amber-500/30'
  },
  '30 mins': { 
    icon: Target, 
    label: '30 Minutes',
    shortLabel: '30m',
    description: 'Intraday swings',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20',
    borderColor: 'border-yellow-500/30'
  },
  '1 hour': { 
    icon: BarChart3, 
    label: '1 Hour',
    shortLabel: '1h',
    description: 'Swing trading',
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    borderColor: 'border-green-500/30'
  },
  '1 day': { 
    icon: Calendar, 
    label: 'Daily',
    shortLabel: '1D',
    description: 'Position trades',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/20',
    borderColor: 'border-cyan-500/30'
  },
  '1 week': { 
    icon: Layers, 
    label: 'Weekly',
    shortLabel: '1W',
    description: 'Long-term trends',
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/20',
    borderColor: 'border-violet-500/30'
  }
};

const formatNumber = (num) => {
  if (!num) return '0';
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toLocaleString();
};

// Individual timeframe card component
const TimeframeCard = memo(({ 
  timeframe, 
  data, 
  modelStatus, 
  onTrain, 
  isTraining,
  isCurrentlyTraining 
}) => {
  const config = TIMEFRAME_CONFIG[timeframe] || TIMEFRAME_CONFIG['1 day'];
  const Icon = config.icon;
  const status = modelStatus?.[timeframe];
  
  const getStatusBadge = () => {
    if (isCurrentlyTraining) {
      return (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-xs">
          <Loader2 className="w-3 h-3 animate-spin" />
          Training
        </span>
      );
    }
    if (status?.status === 'completed') {
      return (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 text-xs">
          <CheckCircle2 className="w-3 h-3" />
          Trained
        </span>
      );
    }
    if (status?.status === 'error') {
      return (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 text-xs">
          <XCircle className="w-3 h-3" />
          Error
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-500/20 text-zinc-400 text-xs">
        <Clock className="w-3 h-3" />
        Ready
      </span>
    );
  };

  return (
    <div className={`p-3 rounded-lg border ${config.borderColor} ${config.bgColor} transition-all hover:border-opacity-60`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${config.color}`} />
          <span className="text-sm font-medium text-white">{config.label}</span>
        </div>
        {getStatusBadge()}
      </div>
      
      <div className="grid grid-cols-2 gap-2 mb-2 text-xs">
        <div className="bg-black/20 rounded p-1.5">
          <div className="text-zinc-500">Bars</div>
          <div className="text-white font-medium">{formatNumber(data?.bar_count)}</div>
        </div>
        <div className="bg-black/20 rounded p-1.5">
          <div className="text-zinc-500">Symbols</div>
          <div className="text-white font-medium">{formatNumber(data?.symbol_count)}</div>
        </div>
      </div>

      {status?.message && (
        <div className="text-xs text-zinc-400 mb-2 truncate" title={status.message}>
          {status.message}
        </div>
      )}

      <button
        onClick={() => onTrain(timeframe)}
        disabled={isTraining || !data?.bar_count}
        className={`
          w-full py-1.5 px-2 rounded text-xs font-medium flex items-center justify-center gap-1.5 transition-all
          ${isTraining || !data?.bar_count
            ? 'bg-zinc-700/50 text-zinc-500 cursor-not-allowed'
            : `${config.bgColor} ${config.color} hover:bg-opacity-40 border ${config.borderColor}`
          }
        `}
        data-testid={`train-${timeframe.replace(/\s/g, '-')}-btn`}
      >
        {isCurrentlyTraining ? (
          <><Loader2 className="w-3 h-3 animate-spin" /> Training...</>
        ) : (
          <><PlayCircle className="w-3 h-3" /> Train</>
        )}
      </button>
    </div>
  );
});

// Training Progress Panel - shows detailed progress during training
const TrainingProgressPanel = memo(({ progress, timeframe, isVisible }) => {
  if (!isVisible) return null;
  
  const config = TIMEFRAME_CONFIG[timeframe] || TIMEFRAME_CONFIG['1 day'];
  const Icon = config.icon;
  
  // Format time as MM:SS
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };
  
  // Calculate progress percentage
  const progressPercent = Math.min(100, (progress.currentStep / progress.totalSteps) * 100);
  
  // Training phases with descriptions
  const phases = [
    { key: 'init', label: 'Initializing', step: 1 },
    { key: 'loading', label: 'Loading Data', step: 2 },
    { key: 'training', label: 'Training Model', step: 3 },
    { key: 'saving', label: 'Saving Model', step: 4 },
    { key: 'complete', label: 'Complete', step: 5 }
  ];
  
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mb-4 p-4 rounded-xl bg-gradient-to-br from-cyan-500/10 via-blue-500/5 to-purple-500/10 border border-cyan-500/30"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${config.bgColor}`}>
            <Icon className={`w-5 h-5 ${config.color}`} />
          </div>
          <div>
            <div className="text-sm font-semibold text-white">
              Training {config.label} Model
            </div>
            <div className="text-xs text-zinc-400">
              {progress.message || 'Processing...'}
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-cyan-400">
            {progressPercent.toFixed(0)}%
          </div>
          <div className="text-xs text-zinc-500">
            {formatTime(progress.elapsedTime)} elapsed
          </div>
        </div>
      </div>
      
      {/* Main Progress Bar */}
      <div className="relative h-3 bg-black/40 rounded-full overflow-hidden mb-4">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${progressPercent}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="absolute h-full bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-500 rounded-full"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 animate-pulse" />
      </div>
      
      {/* Phase Steps */}
      <div className="flex justify-between">
        {phases.map((phase, idx) => {
          const isComplete = progress.currentStep > phase.step;
          const isCurrent = progress.currentStep === phase.step;
          const isError = progress.phase === 'error' && isCurrent;
          
          return (
            <div key={phase.key} className="flex flex-col items-center">
              <div className={`
                w-8 h-8 rounded-full flex items-center justify-center mb-1 transition-all
                ${isError ? 'bg-red-500/30 border-2 border-red-500' :
                  isComplete ? 'bg-green-500/30 border-2 border-green-500' : 
                  isCurrent ? 'bg-cyan-500/30 border-2 border-cyan-500 animate-pulse' : 
                  'bg-zinc-700/50 border border-zinc-600'}
              `}>
                {isError ? (
                  <XCircle className="w-4 h-4 text-red-400" />
                ) : isComplete ? (
                  <CheckCircle2 className="w-4 h-4 text-green-400" />
                ) : isCurrent ? (
                  <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
                ) : (
                  <span className="text-xs text-zinc-500">{phase.step}</span>
                )}
              </div>
              <span className={`text-xs ${
                isError ? 'text-red-400' :
                isComplete ? 'text-green-400' : 
                isCurrent ? 'text-cyan-400' : 
                'text-zinc-500'
              }`}>
                {phase.label}
              </span>
            </div>
          );
        })}
      </div>
      
      {/* Stats Row */}
      {progress.symbolsLoaded > 0 && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <div className="bg-black/30 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-white">{formatNumber(progress.symbolsLoaded)}</div>
            <div className="text-xs text-zinc-500">Symbols</div>
          </div>
          <div className="bg-black/30 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-white">{formatNumber(progress.barsLoaded)}</div>
            <div className="text-xs text-zinc-500">Bars</div>
          </div>
          <div className="bg-black/30 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-white">{formatTime(progress.elapsedTime)}</div>
            <div className="text-xs text-zinc-500">Time</div>
          </div>
        </div>
      )}
    </motion.div>
  );
});

// Calibration step component
const CalibrationStep = memo(({ step, status, isActive }) => {
  const Icon = step.icon;
  
  return (
    <div className={`
      flex items-center gap-3 p-3 rounded-lg transition-all
      ${isActive ? 'bg-cyan-500/10 border border-cyan-500/30' : 'bg-white/[0.02]'}
    `}>
      <div className={`
        w-8 h-8 rounded-lg flex items-center justify-center
        ${status === 'completed' ? 'bg-green-500/20' : 
          status === 'running' ? 'bg-cyan-500/20' : 
          status === 'error' ? 'bg-red-500/20' : 'bg-white/5'}
      `}>
        {status === 'running' ? (
          <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
        ) : status === 'completed' ? (
          <CheckCircle2 className="w-4 h-4 text-green-400" />
        ) : status === 'error' ? (
          <XCircle className="w-4 h-4 text-red-400" />
        ) : (
          <Icon className="w-4 h-4 text-zinc-400" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-white font-medium">{step.label}</div>
        <div className="text-xs text-zinc-400 truncate">{step.description}</div>
      </div>
      {status === 'completed' && step.result && (
        <div className="text-xs text-green-400">{step.result}</div>
      )}
    </div>
  );
});

// Main unified component
const UnifiedAITraining = memo(({ onTrainComplete }) => {
  const [expanded, setExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState('models'); // 'models' | 'calibration' | 'history'
  
  // Training mode context - notifies other components to reduce polling
  const { startTraining: notifyTrainingStart, endTraining: notifyTrainingEnd, updateProgress: notifyProgress } = useTrainingMode();
  
  // Data states
  const [availableData, setAvailableData] = useState(null);
  const [modelStatus, setModelStatus] = useState({});
  const [trainingHistory, setTrainingHistory] = useState([]);
  const [calibrationConfig, setCalibrationConfig] = useState(null);
  
  // Training states
  const [isTraining, setIsTraining] = useState(false);
  const [currentTimeframe, setCurrentTimeframe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  
  // Enhanced training progress state
  const [trainingProgress, setTrainingProgress] = useState({
    phase: '', // 'loading' | 'training' | 'saving' | 'complete'
    currentStep: 0,
    totalSteps: 5,
    symbolsLoaded: 0,
    totalSymbols: 0,
    barsLoaded: 0,
    elapsedTime: 0,
    estimatedTimeRemaining: null,
    message: ''
  });
  const [trainingStartTime, setTrainingStartTime] = useState(null);
  
  // Calibration workflow state
  const [calibrationProgress, setCalibrationProgress] = useState({
    connectors: { status: 'pending', message: '' },
    scanner: { status: 'pending', message: '' },
    weights: { status: 'pending', message: '' }
  });
  const [isCalibrating, setIsCalibrating] = useState(false);

  // Auto-train settings
  const [autoTrainEnabled, setAutoTrainEnabled] = useState(false);
  const [autoTrainAfterCollection, setAutoTrainAfterCollection] = useState(false);
  
  // Timer for elapsed time during training
  useEffect(() => {
    let interval;
    if (isTraining && trainingStartTime) {
      interval = setInterval(() => {
        setTrainingProgress(prev => ({
          ...prev,
          elapsedTime: Math.floor((Date.now() - trainingStartTime) / 1000)
        }));
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isTraining, trainingStartTime]);

  // LocalStorage keys for persistence
  const STORAGE_KEYS = {
    availableData: 'nia_available_data',
    modelStatus: 'nia_model_status',
    trainingHistory: 'nia_training_history'
  };

  // Load cached data from localStorage on mount
  useEffect(() => {
    try {
      const cachedData = localStorage.getItem(STORAGE_KEYS.availableData);
      const cachedStatus = localStorage.getItem(STORAGE_KEYS.modelStatus);
      const cachedHistory = localStorage.getItem(STORAGE_KEYS.trainingHistory);
      
      if (cachedData) {
        const parsed = JSON.parse(cachedData);
        setAvailableData(parsed);
        console.log('[NIA] Loaded cached available data:', parsed.total_bars, 'bars');
      }
      if (cachedStatus) {
        setModelStatus(JSON.parse(cachedStatus));
      }
      if (cachedHistory) {
        setTrainingHistory(JSON.parse(cachedHistory));
      }
    } catch (e) {
      console.warn('[NIA] Error loading cached data:', e);
    }
  }, []);

  // Fetch all data
  const fetchData = useCallback(async () => {
    setLoadError(null); // Reset error state
    try {
      const [dataRes, statusRes, historyRes, configRes, trainingStatusRes] = await Promise.all([
        api.get('/api/ai-modules/timeseries/available-data').catch((e) => ({ data: null, error: e })),
        api.get('/api/ai-modules/timeseries/training-status').catch((e) => ({ data: null, error: e })),
        api.get('/api/ai-modules/timeseries/training-history?limit=20').catch((e) => ({ data: null, error: e })),
        api.get('/api/medium-learning/calibration/config').catch((e) => ({ data: null, error: e })),
        api.get('/api/ai-modules/training-status').catch((e) => ({ data: null, error: e }))
      ]);
      
      if (dataRes.data?.success) {
        setAvailableData(dataRes.data);
        // Cache to localStorage for persistence
        localStorage.setItem(STORAGE_KEYS.availableData, JSON.stringify(dataRes.data));
        console.log('[NIA] Cached available data:', dataRes.data.total_bars, 'bars');
      } else if (!availableData) {
        // Only set error if we don't have cached data
        setLoadError('Unable to load training data. Please try refreshing.');
      }
      if (statusRes.data?.success) {
        const status = statusRes.data.status?.timeframe_status || {};
        setModelStatus(status);
        localStorage.setItem(STORAGE_KEYS.modelStatus, JSON.stringify(status));
      }
      if (historyRes.data?.success) {
        const history = historyRes.data.history || [];
        setTrainingHistory(history);
        localStorage.setItem(STORAGE_KEYS.trainingHistory, JSON.stringify(history));
      }
      if (configRes.data?.success) {
        setCalibrationConfig(configRes.data.config);
      }
      if (trainingStatusRes.data?.success) {
        setAutoTrainEnabled(trainingStatusRes.data.auto_training?.enabled || false);
        setAutoTrainAfterCollection(trainingStatusRes.data.auto_training?.after_collection || false);
      }
    } catch (e) {
      console.error('Error fetching AI training data:', e);
      if (!availableData) {
        setLoadError('Failed to connect to the server. Please check your connection.');
      }
    } finally {
      setLoading(false);
    }
  }, [availableData]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Train single timeframe
  const handleTrainTimeframe = async (timeframe) => {
    setIsTraining(true);
    setCurrentTimeframe(timeframe);
    setTrainingStartTime(Date.now());
    // Notify all components to reduce polling during training
    notifyTrainingStart('single-timeframe');
    
    // Initialize training progress
    setTrainingProgress({
      phase: 'loading',
      currentStep: 1,
      totalSteps: 5,
      symbolsLoaded: 0,
      totalSymbols: 500,
      barsLoaded: 0,
      elapsedTime: 0,
      estimatedTimeRemaining: null,
      message: 'Initializing training...'
    });
    
    setModelStatus(prev => ({
      ...prev,
      [timeframe]: { status: 'running', message: 'Loading data...' }
    }));

    try {
      toast.info(`Training ${TIMEFRAME_CONFIG[timeframe]?.label || timeframe} model...`);
      
      // Update progress phases
      setTrainingProgress(prev => ({
        ...prev,
        phase: 'loading',
        currentStep: 2,
        message: 'Loading symbols from database...'
      }));

      console.log('[NIA] Sending training request for:', timeframe);
      console.log('[NIA] API URL:', apiLongRunning.defaults.baseURL || 'relative (proxy)');
      
      const res = await apiLongRunning.post('/api/ai-modules/timeseries/train', {
        bar_size: timeframe
      });
      
      console.log('[NIA] Training response received:', res.data);

      if (res.data?.success && res.data?.result?.success) {
        const result = res.data.result;
        const accuracy = result.metrics?.accuracy ? (result.metrics.accuracy * 100).toFixed(1) : '?';
        
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'complete',
          currentStep: 5,
          message: `Training complete! ${accuracy}% accuracy`
        }));
        
        setModelStatus(prev => ({
          ...prev,
          [timeframe]: { 
            status: 'completed', 
            message: `${accuracy}% accuracy, ${formatNumber(result.training_samples)} samples` 
          }
        }));
        
        toast.success(`${TIMEFRAME_CONFIG[timeframe]?.label} trained! ${accuracy}% accuracy`);
        fetchData(); // Refresh history
      } else if (res.data?.ml_not_available) {
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'error',
          message: 'ML libraries not installed locally'
        }));
        setModelStatus(prev => ({
          ...prev,
          [timeframe]: { status: 'error', message: 'ML not installed locally' }
        }));
        toast.error('ML libraries not installed. Run: pip install lightgbm');
      } else {
        const errorMsg = res.data?.result?.error || 'Training failed';
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'error',
          message: errorMsg
        }));
        setModelStatus(prev => ({
          ...prev,
          [timeframe]: { status: 'error', message: errorMsg }
        }));
        toast.error(`Training failed: ${errorMsg}`);
      }
    } catch (e) {
      console.error('[NIA] Training error:', e);
      console.error('[NIA] Error details:', e.response?.data || e.message);
      setTrainingProgress(prev => ({
        ...prev,
        phase: 'error',
        message: e.response?.data?.detail || e.message
      }));
      setModelStatus(prev => ({
        ...prev,
        [timeframe]: { status: 'error', message: e.response?.data?.detail || e.message }
      }));
      toast.error(`Training error: ${e.response?.data?.detail || e.message}`);
    } finally {
      setIsTraining(false);
      setCurrentTimeframe(null);
      setTrainingStartTime(null);
      notifyTrainingEnd();
      if (onTrainComplete) onTrainComplete();
    }
  };

  // FULL UNIVERSE training - uses ALL data
  const handleFullUniverseTrain = async () => {
    console.log('[NIA] Full Universe button clicked!');
    
    // Confirm with user since this takes a long time
    const confirmed = window.confirm(
      `🌐 Full Universe Training\n\n` +
      `This will train on ALL ${formatNumber(totalBars)} bars across ALL symbols.\n\n` +
      `⏱️ Expected time: 1-3 hours\n` +
      `📊 Uses chunked loading to prevent crashes\n` +
      `📈 Progress will show in the terminal\n\n` +
      `Continue?`
    );
    
    if (!confirmed) {
      console.log('[NIA] Full Universe: User cancelled');
      return;
    }
    
    console.log('[NIA] Full Universe: User confirmed, starting request...');
    
    setIsTraining(true);
    setTrainingStartTime(Date.now());
    setTrainingProgress({
      phase: 'full_universe',
      currentStep: 1,
      totalSteps: 5,
      symbolsLoaded: 0,
      totalSymbols: 0,
      barsLoaded: 0,
      elapsedTime: 0,
      message: 'Starting full universe training...'
    });
    
    // Notify all components to reduce polling during training
    notifyTrainingStart('full-universe');
    
    toast.info('🌐 Starting Full Universe training - check backend terminal for progress', {
      duration: 10000
    });
    
    try {
      console.log('[NIA] Full Universe: Sending POST request to /api/ai-modules/timeseries/train-full-universe-all');
      
      // Log the full URL being called
      const fullUrl = (apiLongRunning.defaults.baseURL || '') + '/api/ai-modules/timeseries/train-full-universe-all';
      console.log('[NIA] Full URL:', fullUrl);
      console.log('[NIA] Timeout setting:', apiLongRunning.defaults.timeout);
      
      const res = await apiLongRunning.post('/api/ai-modules/timeseries/train-full-universe-all', {
        symbol_batch_size: 50,   // Reduced for stability
        max_bars_per_symbol: 1000  // Reduced for stability
      });
      console.log('[NIA] Full Universe: Response received:', res.data);
      
      if (res.data?.success) {
        // Training started in background
        toast.success(
          `🚀 Full Universe training started! Watch the backend terminal for progress.`,
          { duration: 10000 }
        );
        
        // If we get immediate results (unlikely for full universe), handle them
        if (res.data.result) {
          const result = res.data.result;
          const trainedCount = result.timeframes_trained || 0;
          const totalTime = result.total_elapsed_seconds || 0;
          
          toast.success(
            `🎉 Full Universe complete! ${trainedCount}/${result.total_timeframes} models trained in ${(totalTime/60).toFixed(0)} minutes`,
            { duration: 15000 }
          );
          
          // Update status for all timeframes
          const newStatus = {};
          for (const [tf, tfResult] of Object.entries(result.results || {})) {
            if (tfResult.success) {
              const accuracy = tfResult.accuracy ? (tfResult.accuracy * 100).toFixed(1) : '?';
              newStatus[tf] = { status: 'completed', message: `${accuracy}% accuracy (full universe)` };
            } else {
              newStatus[tf] = { status: 'error', message: tfResult.error || 'Failed' };
            }
          }
          setModelStatus(newStatus);
          localStorage.setItem(STORAGE_KEYS.modelStatus, JSON.stringify(newStatus));
        }
        
        fetchData();
      } else if (res.data?.ml_not_available) {
        toast.error('ML libraries not installed. Run: pip install lightgbm scikit-learn');
      } else {
        toast.error('Full universe training failed: ' + (res.data?.result?.error || 'Unknown error'));
      }
    } catch (e) {
      console.error('[NIA] Full universe error:', e);
      console.error('[NIA] Error details:', {
        message: e.message,
        code: e.code,
        response: e.response?.data,
        status: e.response?.status
      });
      if (e.message?.includes('timeout')) {
        toast.warning('Request timed out but training may still be running. Check backend terminal.', {
          duration: 10000
        });
      } else if (e.message?.includes('Network Error')) {
        toast.error('Network Error - Backend may be down or not responding. Check backend terminal.', {
          duration: 10000
        });
      } else {
        toast.error(`Full universe error: ${e.message}`);
      }
    } finally {
      setIsTraining(false);
      setTrainingProgress({
        phase: '',
        currentStep: 0,
        totalSteps: 5,
        symbolsLoaded: 0,
        totalSymbols: 0,
        barsLoaded: 0,
        elapsedTime: 0,
        message: ''
      });
      // Notify components that training ended - they can resume normal polling
      notifyTrainingEnd();
      if (onTrainComplete) onTrainComplete();
    }
  };

  // Train ALL timeframes
  const handleTrainAll = async () => {
    setIsTraining(true);
    // Notify all components to reduce polling during training
    notifyTrainingStart('train-all');
    const timeframes = Object.keys(availableData?.timeframes || {});
    
    toast.info(`Training ${timeframes.length} timeframe models...`);

    try {
      const res = await apiLongRunning.post('/api/ai-modules/timeseries/train-all');

      if (res.data?.success) {
        const result = res.data.result;
        
        // Update status for all timeframes
        const newStatus = {};
        for (const [tf, tfResult] of Object.entries(result.results || {})) {
          if (tfResult.success) {
            const accuracy = tfResult.metrics?.accuracy ? (tfResult.metrics.accuracy * 100).toFixed(1) : '?';
            newStatus[tf] = { status: 'completed', message: `${accuracy}% accuracy` };
          } else {
            newStatus[tf] = { status: 'error', message: tfResult.error || 'Failed' };
          }
        }
        setModelStatus(newStatus);
        
        toast.success(`Trained ${result.timeframes_trained}/${result.total_timeframes} models!`);
        fetchData();
      } else if (res.data?.ml_not_available) {
        toast.error('ML libraries not installed. Run: pip install lightgbm');
      } else {
        toast.error('Training failed');
      }
    } catch (e) {
      console.error('Train-all error:', e);
      toast.error(`Training error: ${e.message}`);
    } finally {
      setIsTraining(false);
      notifyTrainingEnd();
      if (onTrainComplete) onTrainComplete();
    }
  };

  // Quick Train: Daily model + calibration
  const handleQuickTrain = async () => {
    setIsTraining(true);
    setIsCalibrating(true);
    setTrainingStartTime(Date.now());
    // Notify all components to reduce polling during training
    notifyTrainingStart('quick-train');
    
    // Initialize training progress
    setTrainingProgress({
      phase: 'loading',
      currentStep: 1,
      totalSteps: 5,
      symbolsLoaded: 0,
      totalSymbols: 500,
      barsLoaded: 0,
      elapsedTime: 0,
      estimatedTimeRemaining: null,
      message: 'Starting Quick Train...'
    });
    
    // Reset calibration progress
    setCalibrationProgress({
      connectors: { status: 'pending', message: '' },
      scanner: { status: 'pending', message: '' },
      weights: { status: 'pending', message: '' }
    });

    try {
      // Step 1: Train Daily model
      setCurrentTimeframe('1 day');
      setTrainingProgress(prev => ({
        ...prev,
        phase: 'loading',
        currentStep: 2,
        message: 'Loading Daily timeframe data from database...'
      }));
      setModelStatus(prev => ({
        ...prev,
        '1 day': { status: 'running', message: 'Training Daily model...' }
      }));
      
      toast.info('Quick Train: Training Daily model...');
      
      // Simulate progress update
      setTimeout(() => {
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'training',
          currentStep: 3,
          message: 'Training LightGBM model on ~1M bars...',
          symbolsLoaded: 500,
          barsLoaded: 1000000
        }));
      }, 2000);
      
      const trainRes = await apiLongRunning.post('/api/ai-modules/timeseries/train', {
        bar_size: '1 day'
      });

      if (trainRes.data?.success && trainRes.data?.result?.success) {
        const result = trainRes.data.result;
        const accuracy = result.metrics?.accuracy ? 
          (result.metrics.accuracy * 100).toFixed(1) : '?';
        const samples = result.training_samples || 0;
        
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'saving',
          currentStep: 4,
          message: `Saving model... ${accuracy}% accuracy achieved!`,
          barsLoaded: samples
        }));
        
        setModelStatus(prev => ({
          ...prev,
          '1 day': { status: 'completed', message: `${accuracy}% accuracy, ${formatNumber(samples)} samples` }
        }));
      } else if (trainRes.data?.ml_not_available) {
        setTrainingProgress(prev => ({
          ...prev,
          phase: 'error',
          message: 'ML libraries not installed locally'
        }));
        setModelStatus(prev => ({
          ...prev,
          '1 day': { status: 'error', message: 'ML not installed' }
        }));
      }

      setCurrentTimeframe(null);

      // Step 2: Run calibrations
      setTrainingProgress(prev => ({
        ...prev,
        phase: 'complete',
        currentStep: 5,
        message: 'Running calibrations...'
      }));
      
      setCalibrationProgress(prev => ({
        ...prev,
        connectors: { status: 'running', message: 'Syncing...' }
      }));

      toast.info('Quick Train: Running calibrations...');

      const calRes = await apiLongRunning.post('/api/learning-connectors/sync/run-all-calibrations');
      
      if (calRes.data?.success || calRes.data?.results) {
        const results = calRes.data.results || {};
        
        setCalibrationProgress({
          connectors: { 
            status: results.shadow_to_weights?.success ? 'completed' : 'error',
            message: results.shadow_to_weights?.success ? 'Synced' : 'No data yet'
          },
          scanner: { 
            status: results.outcomes_to_scanner?.success ? 'completed' : 'error',
            message: results.outcomes_to_scanner?.applied_count ? 
              `${results.outcomes_to_scanner.applied_count} thresholds` : 'No outcomes yet'
          },
          weights: { 
            status: results.predictions_verification?.success ? 'completed' : 'error',
            message: results.predictions_verification?.verified_count ?
              `${results.predictions_verification.verified_count} verified` : 'No predictions yet'
          }
        });

        toast.success(`Quick Train complete! ${calRes.data.applied_calibrations || 0} calibrations applied`);
      } else {
        setCalibrationProgress({
          connectors: { status: 'error', message: 'Failed' },
          scanner: { status: 'error', message: 'Failed' },
          weights: { status: 'error', message: 'Failed' }
        });
      }

      fetchData();
    } catch (e) {
      console.error('Quick train error:', e);
      setTrainingProgress(prev => ({
        ...prev,
        phase: 'error',
        message: e.message
      }));
      toast.error(`Quick train error: ${e.message}`);
    } finally {
      setIsTraining(false);
      setIsCalibrating(false);
      setCurrentTimeframe(null);
      setTrainingStartTime(null);
      // Notify components that training ended - they can resume normal polling
      notifyTrainingEnd();
      // Clear training progress after a delay to show final status
      setTimeout(() => {
        setTrainingProgress({
          phase: '',
          currentStep: 0,
          totalSteps: 5,
          symbolsLoaded: 0,
          totalSymbols: 0,
          barsLoaded: 0,
          elapsedTime: 0,
          estimatedTimeRemaining: null,
          message: ''
        });
      }, 3000);
      if (onTrainComplete) onTrainComplete();
    }
  };

  // Toggle auto-train settings
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
        toast.success(value ? 'Will train after data collection' : 'Disabled');
      }
    } catch (e) {
      toast.error('Failed to update settings');
    }
  };

  const totalBars = availableData?.total_bars || 0;
  const timeframes = availableData?.timeframes || {};
  const timeframeCount = Object.keys(timeframes).length;
  const trainedCount = Object.values(modelStatus).filter(s => s?.status === 'completed').length;

  // Calibration steps config
  const calibrationSteps = [
    { key: 'connectors', label: 'Sync Learning Connectors', icon: GitBranch, description: 'Update data pipelines' },
    { key: 'scanner', label: 'Calibrate Scanner', icon: Target, description: 'Optimize alert thresholds' },
    { key: 'weights', label: 'Update Module Weights', icon: Gauge, description: 'Adjust AI module influence' }
  ];

  if (loading && !availableData) {
    return (
      <div className="rounded-xl border border-white/10 p-6 mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95), rgba(30, 40, 55, 0.95))' }}>
        <div className="flex items-center justify-center gap-3 text-zinc-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading AI training data...
        </div>
      </div>
    );
  }

  // Show error state with retry button
  if (!loading && !availableData && loadError) {
    return (
      <div className="rounded-xl border border-red-500/30 p-6 mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95), rgba(30, 40, 55, 0.95))' }}>
        <div className="flex flex-col items-center justify-center gap-3">
          <div className="flex items-center gap-2 text-red-400">
            <AlertCircle className="w-5 h-5" />
            {loadError}
          </div>
          <button
            onClick={() => { setLoading(true); fetchData(); }}
            className="px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-colors flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Show minimal fallback if no data but also no error (shouldn't happen often)
  if (!availableData) {
    return (
      <div className="rounded-xl border border-white/10 p-6 mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95), rgba(30, 40, 55, 0.95))' }}>
        <div className="flex flex-col items-center justify-center gap-3">
          <div className="flex items-center gap-2 text-zinc-400">
            <Database className="w-5 h-5" />
            No training data available
          </div>
          <button
            onClick={() => { setLoading(true); fetchData(); }}
            className="px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-colors flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95), rgba(30, 40, 55, 0.95))' }}>
      {/* Header */}
      <div 
        className="p-4 flex items-center justify-between cursor-pointer hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #06b6d4, #8b5cf6)' }}>
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              AI Training & Calibration
              <span className="px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-xs font-normal">
                {formatNumber(totalBars)} bars
              </span>
            </h3>
            <p className="text-xs text-zinc-400">
              {trainedCount}/{timeframeCount} models trained
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); fetchData(); }}
            className="p-2 rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          {expanded ? <ChevronUp className="w-5 h-5 text-zinc-400" /> : <ChevronDown className="w-5 h-5 text-zinc-400" />}
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
            <div className="px-4 pb-4">
              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  onClick={handleQuickTrain}
                  disabled={isTraining}
                  className={`
                    flex-1 min-w-[140px] py-2.5 px-4 rounded-lg font-medium text-sm flex items-center justify-center gap-2 transition-all
                    ${isTraining
                      ? 'bg-zinc-700/50 text-zinc-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:from-cyan-400 hover:to-blue-400 shadow-lg shadow-cyan-500/25'
                    }
                  `}
                  data-testid="quick-train-btn"
                >
                  {isTraining && currentTimeframe === '1 day' ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Training...</>
                  ) : (
                    <><Sparkles className="w-4 h-4" /> Quick Train</>
                  )}
                </button>
                
                <button
                  onClick={handleTrainAll}
                  disabled={isTraining || timeframeCount === 0}
                  className={`
                    flex-1 min-w-[140px] py-2.5 px-4 rounded-lg font-medium text-sm flex items-center justify-center gap-2 transition-all
                    ${isTraining || timeframeCount === 0
                      ? 'bg-zinc-700/50 text-zinc-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-violet-500 to-purple-500 text-white hover:from-violet-400 hover:to-purple-400 shadow-lg shadow-violet-500/25'
                    }
                  `}
                  data-testid="train-all-btn"
                >
                  {isTraining && !currentTimeframe ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Training All...</>
                  ) : (
                    <><Database className="w-4 h-4" /> Full Train ({timeframeCount})</>
                  )}
                </button>
                
                <button
                  onClick={handleFullUniverseTrain}
                  disabled={isTraining || timeframeCount === 0}
                  className={`
                    flex-1 min-w-[140px] py-2.5 px-4 rounded-lg font-medium text-sm flex items-center justify-center gap-2 transition-all
                    ${isTraining || timeframeCount === 0
                      ? 'bg-zinc-700/50 text-zinc-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-amber-500 to-orange-500 text-white hover:from-amber-400 hover:to-orange-400 shadow-lg shadow-amber-500/25'
                    }
                  `}
                  data-testid="full-universe-btn"
                  title="Train on ALL symbols across ALL timeframes (1-3 hours)"
                >
                  {isTraining && trainingProgress.phase === 'full_universe' ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Full Universe...</>
                  ) : (
                    <><Globe className="w-4 h-4" /> Full Universe</>
                  )}
                </button>
              </div>

              {/* Quick description */}
              <div className="text-xs text-zinc-500 mb-4 flex flex-col gap-1">
                <div className="flex items-center gap-4">
                  <span><strong>Quick Train:</strong> Daily model + calibration (~1-2 min)</span>
                  <span><strong>Full Train:</strong> All {timeframeCount} timeframes, sampled symbols (~5-10 min)</span>
                </div>
                <div>
                  <span className="text-amber-400"><strong>Full Universe:</strong> ALL {formatNumber(totalBars)} bars, ALL symbols, ALL timeframes (1-3 hours)</span>
                </div>
              </div>

              {/* Training Progress Panel - Shows during active training */}
              <AnimatePresence>
                {isTraining && currentTimeframe && (
                  <TrainingProgressPanel 
                    progress={trainingProgress}
                    timeframe={currentTimeframe}
                    isVisible={true}
                  />
                )}
              </AnimatePresence>

              {/* Tab Navigation */}
              <div className="flex gap-1 mb-4 bg-black/20 p-1 rounded-lg">
                {[
                  { id: 'models', label: 'Timeframe Models', icon: Brain },
                  { id: 'calibration', label: 'Calibration', icon: Settings },
                  { id: 'history', label: 'History', icon: History }
                ].map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`
                      flex-1 py-2 px-3 rounded-md text-xs font-medium flex items-center justify-center gap-1.5 transition-all
                      ${activeTab === tab.id 
                        ? 'bg-white/10 text-white' 
                        : 'text-zinc-400 hover:text-white hover:bg-white/5'
                      }
                    `}
                  >
                    <tab.icon className="w-3.5 h-3.5" />
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Tab Content */}
              {activeTab === 'models' && (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2">
                  {Object.entries(timeframes)
                    .sort((a, b) => {
                      const order = ['1 min', '5 mins', '15 mins', '30 mins', '1 hour', '1 day', '1 week'];
                      return order.indexOf(a[0]) - order.indexOf(b[0]);
                    })
                    .map(([timeframe, data]) => (
                      <TimeframeCard
                        key={timeframe}
                        timeframe={timeframe}
                        data={data}
                        modelStatus={modelStatus}
                        onTrain={handleTrainTimeframe}
                        isTraining={isTraining}
                        isCurrentlyTraining={currentTimeframe === timeframe}
                      />
                    ))}
                </div>
              )}

              {activeTab === 'calibration' && (
                <div className="space-y-3">
                  {/* Auto-train settings */}
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Settings className="w-4 h-4 text-zinc-400" />
                        <span className="text-sm text-white">Auto-train after data collection</span>
                      </div>
                      <button
                        onClick={() => handleAutoTrainToggle('after_collection', !autoTrainAfterCollection)}
                        className={`
                          w-10 h-5 rounded-full transition-colors relative
                          ${autoTrainAfterCollection ? 'bg-cyan-500' : 'bg-zinc-600'}
                        `}
                      >
                        <div className={`
                          absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform
                          ${autoTrainAfterCollection ? 'left-5' : 'left-0.5'}
                        `} />
                      </button>
                    </div>
                  </div>

                  {/* Calibration steps */}
                  <div className="space-y-2">
                    {calibrationSteps.map(step => (
                      <CalibrationStep
                        key={step.key}
                        step={step}
                        status={calibrationProgress[step.key]?.status}
                        isActive={isCalibrating}
                      />
                    ))}
                  </div>

                  {/* Calibration config preview */}
                  {calibrationConfig && (
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <div className="text-xs text-zinc-400 mb-2">Current TQS Thresholds</div>
                      <div className="grid grid-cols-4 gap-2 text-xs">
                        <div className="text-center">
                          <div className="text-green-400 font-medium">{calibrationConfig.tqs_strong_buy_threshold}+</div>
                          <div className="text-zinc-500">Strong Buy</div>
                        </div>
                        <div className="text-center">
                          <div className="text-cyan-400 font-medium">{calibrationConfig.tqs_buy_threshold}+</div>
                          <div className="text-zinc-500">Buy</div>
                        </div>
                        <div className="text-center">
                          <div className="text-yellow-400 font-medium">{calibrationConfig.tqs_hold_threshold}+</div>
                          <div className="text-zinc-500">Hold</div>
                        </div>
                        <div className="text-center">
                          <div className="text-red-400 font-medium">&lt;{calibrationConfig.tqs_avoid_threshold}</div>
                          <div className="text-zinc-500">Avoid</div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'history' && (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {trainingHistory.length === 0 ? (
                    <div className="text-center py-8 text-zinc-400">
                      <History className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <div className="text-sm">No training history yet</div>
                      <div className="text-xs">Train a model to see results here</div>
                    </div>
                  ) : (
                    trainingHistory.map((record, idx) => {
                      const config = TIMEFRAME_CONFIG[record.bar_size] || TIMEFRAME_CONFIG['1 day'];
                      const accuracy = record.accuracy ? (record.accuracy * 100).toFixed(1) : '?';
                      const timestamp = record.timestamp ? new Date(record.timestamp).toLocaleString() : 'Unknown';
                      
                      return (
                        <div 
                          key={idx}
                          className={`p-3 rounded-lg bg-black/20 border ${config.borderColor} flex items-center justify-between`}
                        >
                          <div className="flex items-center gap-3">
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${config.bgColor}`}>
                              <config.icon className={`w-4 h-4 ${config.color}`} />
                            </div>
                            <div>
                              <div className="text-sm text-white font-medium">{config.label}</div>
                              <div className="text-xs text-zinc-500">{timestamp}</div>
                            </div>
                          </div>
                          <div className="text-right">
                            <div className={`text-sm font-semibold ${
                              record.accuracy >= 0.6 ? 'text-green-400' : 
                              record.accuracy >= 0.5 ? 'text-yellow-400' : 'text-red-400'
                            }`}>
                              {accuracy}%
                            </div>
                            <div className="text-xs text-zinc-500">
                              {formatNumber(record.training_samples)} samples
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              )}

              {/* No data warning */}
              {timeframeCount === 0 && (
                <div className="text-center py-6 text-zinc-400">
                  <AlertCircle className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <div className="text-sm">No historical data available</div>
                  <div className="text-xs mt-1">Run the IB data collector to gather training data</div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default UnifiedAITraining;
