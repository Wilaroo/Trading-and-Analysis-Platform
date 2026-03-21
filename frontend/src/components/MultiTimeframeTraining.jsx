/**
 * Multi-Timeframe Training Panel
 * ==============================
 * Allows training AI models on different timeframes from the 39M+ bar dataset.
 * Each timeframe gets its own specialized model for different trading styles.
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
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Database,
  BarChart3,
  RefreshCw,
  Layers,
  History
} from 'lucide-react';
import { toast } from 'sonner';
import api, { apiLongRunning } from '../utils/api';

// Timeframe configurations with icons and descriptions
const TIMEFRAME_CONFIG = {
  '1 min': { 
    icon: Zap, 
    label: '1 Minute', 
    description: 'Ultra-short scalping',
    color: 'red',
    bgGradient: 'from-red-500/20 to-orange-500/20',
    borderColor: 'border-red-500/30'
  },
  '5 mins': { 
    icon: TrendingUp, 
    label: '5 Minutes', 
    description: 'Intraday scalping',
    color: 'orange',
    bgGradient: 'from-orange-500/20 to-amber-500/20',
    borderColor: 'border-orange-500/30'
  },
  '15 mins': { 
    icon: Clock, 
    label: '15 Minutes', 
    description: 'Short-term swings',
    color: 'amber',
    bgGradient: 'from-amber-500/20 to-yellow-500/20',
    borderColor: 'border-amber-500/30'
  },
  '30 mins': { 
    icon: Target, 
    label: '30 Minutes', 
    description: 'Intraday swings',
    color: 'yellow',
    bgGradient: 'from-yellow-500/20 to-lime-500/20',
    borderColor: 'border-yellow-500/30'
  },
  '1 hour': { 
    icon: BarChart3, 
    label: '1 Hour', 
    description: 'Swing trading',
    color: 'green',
    bgGradient: 'from-green-500/20 to-emerald-500/20',
    borderColor: 'border-green-500/30'
  },
  '1 day': { 
    icon: Calendar, 
    label: 'Daily', 
    description: 'Position trades',
    color: 'cyan',
    bgGradient: 'from-cyan-500/20 to-blue-500/20',
    borderColor: 'border-cyan-500/30'
  },
  '1 week': { 
    icon: Layers, 
    label: 'Weekly', 
    description: 'Long-term trends',
    color: 'violet',
    bgGradient: 'from-violet-500/20 to-purple-500/20',
    borderColor: 'border-violet-500/30'
  }
};

const formatNumber = (num) => {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num?.toLocaleString() || '0';
};

const TimeframeCard = memo(({ 
  timeframe, 
  data, 
  trainingStatus, 
  onTrain, 
  isTraining,
  isCurrentlyTraining 
}) => {
  const config = TIMEFRAME_CONFIG[timeframe] || TIMEFRAME_CONFIG['1 day'];
  const Icon = config.icon;
  const status = trainingStatus?.[timeframe];
  
  const getStatusBadge = () => {
    if (isCurrentlyTraining) {
      return (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-xs">
          <Loader2 className="w-3 h-3 animate-spin" />
          Training...
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
        Not trained
      </span>
    );
  };

  return (
    <div 
      className={`
        relative p-4 rounded-xl border transition-all duration-300
        bg-gradient-to-br ${config.bgGradient} ${config.borderColor}
        hover:border-opacity-50
      `}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center bg-${config.color}-500/20`}>
            <Icon className={`w-4 h-4 text-${config.color}-400`} />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-white">{config.label}</h4>
            <p className="text-xs text-zinc-400">{config.description}</p>
          </div>
        </div>
        {getStatusBadge()}
      </div>

      {/* Data Stats */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="p-2 rounded-lg bg-black/20">
          <div className="text-xs text-zinc-500">Bars</div>
          <div className="text-sm font-semibold text-white">
            {formatNumber(data?.bar_count)}
          </div>
        </div>
        <div className="p-2 rounded-lg bg-black/20">
          <div className="text-xs text-zinc-500">Symbols</div>
          <div className="text-sm font-semibold text-white">
            {formatNumber(data?.symbol_count)}
          </div>
        </div>
      </div>

      {/* Status Message */}
      {status?.message && (
        <div className="text-xs text-zinc-400 mb-3 truncate" title={status.message}>
          {status.message}
        </div>
      )}

      {/* Train Button */}
      <button
        onClick={() => onTrain(timeframe)}
        disabled={isTraining || !data?.bar_count}
        className={`
          w-full py-2 px-3 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-all
          ${isTraining || !data?.bar_count
            ? 'bg-zinc-700/50 text-zinc-500 cursor-not-allowed'
            : `bg-${config.color}-500/20 text-${config.color}-400 hover:bg-${config.color}-500/30 border border-${config.color}-500/30`
          }
        `}
        data-testid={`train-${timeframe.replace(' ', '-')}-btn`}
      >
        {isCurrentlyTraining ? (
          <>
            <Loader2 className="w-3 h-3 animate-spin" />
            Training...
          </>
        ) : (
          <>
            <PlayCircle className="w-3 h-3" />
            Train Model
          </>
        )}
      </button>
    </div>
  );
});

const MultiTimeframeTraining = memo(({ onTrainComplete }) => {
  const [expanded, setExpanded] = useState(true);
  const [availableData, setAvailableData] = useState(null);
  const [trainingStatus, setTrainingStatus] = useState({});
  const [trainingHistory, setTrainingHistory] = useState([]);
  const [isTraining, setIsTraining] = useState(false);
  const [currentTimeframe, setCurrentTimeframe] = useState(null);
  const [isTrainingAll, setIsTrainingAll] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showHistory, setShowHistory] = useState(false);

  // Fetch available data on mount
  const fetchData = useCallback(async () => {
    try {
      const [dataRes, statusRes, historyRes] = await Promise.all([
        api.get('/api/ai-modules/timeseries/available-data'),
        api.get('/api/ai-modules/timeseries/training-status'),
        api.get('/api/ai-modules/timeseries/training-history?limit=30')
      ]);
      
      if (dataRes.data?.success) {
        setAvailableData(dataRes.data);
      }
      if (statusRes.data?.success) {
        setTrainingStatus(statusRes.data.status?.timeframe_status || {});
      }
      if (historyRes.data?.success) {
        setTrainingHistory(historyRes.data.history || []);
      }
    } catch (e) {
      console.error('Error fetching timeframe data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Train a single timeframe
  const handleTrainTimeframe = async (timeframe) => {
    setIsTraining(true);
    setCurrentTimeframe(timeframe);
    
    // Update local status
    setTrainingStatus(prev => ({
      ...prev,
      [timeframe]: { status: 'running', message: 'Loading data...' }
    }));

    try {
      toast.info(`Training ${TIMEFRAME_CONFIG[timeframe]?.label || timeframe} model...`, {
        duration: 3000
      });

      const res = await apiLongRunning.post('/api/ai-modules/timeseries/train', {
        bar_size: timeframe,
        max_symbols: 1000,
        max_bars_per_symbol: 10000
      });

      if (res.data?.success && res.data?.result?.success) {
        const result = res.data.result;
        const accuracy = result.metrics?.accuracy ? (result.metrics.accuracy * 100).toFixed(1) : '?';
        const samples = result.training_samples || 0;
        
        setTrainingStatus(prev => ({
          ...prev,
          [timeframe]: { 
            status: 'completed', 
            message: `${accuracy}% accuracy, ${formatNumber(samples)} samples` 
          }
        }));
        
        toast.success(
          `${TIMEFRAME_CONFIG[timeframe]?.label} model trained! ${accuracy}% accuracy on ${formatNumber(result.symbols_used)} symbols`,
          { duration: 5000 }
        );
      } else {
        const errorMsg = res.data?.result?.error || 'Training failed';
        setTrainingStatus(prev => ({
          ...prev,
          [timeframe]: { status: 'error', message: errorMsg }
        }));
        toast.error(`Training failed: ${errorMsg}`);
      }
    } catch (e) {
      console.error('Training error:', e);
      const errorMsg = e.response?.data?.detail || e.message || 'Training failed';
      setTrainingStatus(prev => ({
        ...prev,
        [timeframe]: { status: 'error', message: errorMsg }
      }));
      toast.error(`Training error: ${errorMsg}`);
    } finally {
      setIsTraining(false);
      setCurrentTimeframe(null);
      if (onTrainComplete) onTrainComplete();
    }
  };

  // Train all timeframes sequentially
  const handleTrainAll = async () => {
    const timeframes = Object.keys(availableData?.timeframes || {});
    if (timeframes.length === 0) {
      toast.error('No timeframe data available');
      return;
    }

    setIsTrainingAll(true);
    setIsTraining(true);
    
    toast.info(`Starting training for ${timeframes.length} timeframes...`, { duration: 5000 });

    try {
      const res = await apiLongRunning.post('/api/ai-modules/timeseries/train-all', {
        max_symbols: 1000,
        max_bars_per_symbol: 10000
      });

      if (res.data?.success) {
        const result = res.data.result;
        
        // Update status for all timeframes
        const newStatus = {};
        for (const [tf, tfResult] of Object.entries(result.results || {})) {
          if (tfResult.success) {
            const accuracy = tfResult.metrics?.accuracy ? (tfResult.metrics.accuracy * 100).toFixed(1) : '?';
            newStatus[tf] = { 
              status: 'completed', 
              message: `${accuracy}% accuracy` 
            };
          } else {
            newStatus[tf] = { 
              status: 'error', 
              message: tfResult.error || 'Failed' 
            };
          }
        }
        setTrainingStatus(newStatus);
        
        toast.success(
          `Trained ${result.timeframes_trained}/${result.total_timeframes} models! ${formatNumber(result.total_samples)} total samples`,
          { duration: 8000 }
        );
      } else {
        toast.error('Train-all failed');
      }
    } catch (e) {
      console.error('Train-all error:', e);
      toast.error(`Training error: ${e.response?.data?.detail || e.message}`);
    } finally {
      setIsTrainingAll(false);
      setIsTraining(false);
      setCurrentTimeframe(null);
      if (onTrainComplete) onTrainComplete();
    }
  };

  const totalBars = availableData?.total_bars || 0;
  const timeframes = availableData?.timeframes || {};
  const timeframeCount = Object.keys(timeframes).length;
  const trainedCount = Object.values(trainingStatus).filter(s => s?.status === 'completed').length;

  if (loading) {
    return (
      <div className="rounded-xl border border-white/10 p-6 mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.9), rgba(30, 40, 55, 0.9))' }}>
        <div className="flex items-center justify-center gap-3 text-zinc-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading timeframe data...
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.9), rgba(30, 40, 55, 0.9))' }}>
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
              Multi-Timeframe AI Training
              <span className="px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 text-xs font-normal">
                {formatNumber(totalBars)} bars
              </span>
            </h3>
            <p className="text-xs text-zinc-400">
              {trainedCount}/{timeframeCount} models trained
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={(e) => {
              e.stopPropagation();
              fetchData();
            }}
            className="p-2 rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition-colors"
            title="Refresh data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          {expanded ? (
            <ChevronUp className="w-5 h-5 text-zinc-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-zinc-400" />
          )}
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
              {/* Train All Button */}
              <div className="flex items-center justify-between p-3 rounded-lg bg-white/5 border border-white/10 mb-4">
                <div className="flex items-center gap-3">
                  <Database className="w-5 h-5 text-cyan-400" />
                  <div>
                    <div className="text-sm text-white font-medium">Train All Timeframes</div>
                    <div className="text-xs text-zinc-400">
                      Sequential training on {formatNumber(totalBars)} bars across {timeframeCount} timeframes
                    </div>
                  </div>
                </div>
                <button
                  onClick={handleTrainAll}
                  disabled={isTraining || timeframeCount === 0}
                  className={`
                    px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-all
                    ${isTraining
                      ? 'bg-cyan-500/20 text-cyan-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-cyan-500 to-violet-500 text-white hover:from-cyan-400 hover:to-violet-400 shadow-lg shadow-cyan-500/25'
                    }
                  `}
                  data-testid="train-all-timeframes-btn"
                >
                  {isTrainingAll ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Training All...
                    </>
                  ) : (
                    <>
                      <PlayCircle className="w-4 h-4" />
                      Train All ({timeframeCount})
                    </>
                  )}
                </button>
              </div>

              {/* Timeframe Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
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
                      trainingStatus={trainingStatus}
                      onTrain={handleTrainTimeframe}
                      isTraining={isTraining}
                      isCurrentlyTraining={currentTimeframe === timeframe}
                    />
                  ))}
              </div>

              {/* No Data Message */}
              {timeframeCount === 0 && (
                <div className="text-center py-8 text-zinc-400">
                  <Database className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p className="text-sm">No historical data available for training.</p>
                  <p className="text-xs mt-1">Run the data collector to gather training data.</p>
                </div>
              )}

              {/* Training History Section */}
              {trainingHistory.length > 0 && (
                <div className="mt-4 border-t border-white/10 pt-4">
                  <button
                    onClick={() => setShowHistory(!showHistory)}
                    className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors mb-3"
                  >
                    <History className="w-4 h-4" />
                    Training History ({trainingHistory.length} runs)
                    {showHistory ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                  
                  <AnimatePresence>
                    {showHistory && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="space-y-2 max-h-64 overflow-y-auto">
                          {trainingHistory.map((record, idx) => {
                            const config = TIMEFRAME_CONFIG[record.bar_size] || TIMEFRAME_CONFIG['1 day'];
                            const accuracy = record.accuracy ? (record.accuracy * 100).toFixed(1) : '?';
                            const timestamp = record.timestamp ? new Date(record.timestamp).toLocaleString() : 'Unknown';
                            
                            return (
                              <div 
                                key={idx}
                                className={`p-3 rounded-lg bg-black/20 border ${config.borderColor} flex items-center justify-between`}
                              >
                                <div className="flex items-center gap-3">
                                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center bg-${config.color}-500/20`}>
                                    <config.icon className={`w-4 h-4 text-${config.color}-400`} />
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
                                    {accuracy}% accuracy
                                  </div>
                                  <div className="text-xs text-zinc-500">
                                    {formatNumber(record.training_samples)} samples
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default MultiTimeframeTraining;
