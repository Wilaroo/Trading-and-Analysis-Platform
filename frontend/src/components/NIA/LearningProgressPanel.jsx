import React, { useState, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, ChevronDown, CheckCircle2 } from 'lucide-react';

const LearningProgressPanel = memo(({ data }) => {
  const [expanded, setExpanded] = useState(true);

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
    <div className="rounded-xl border border-white/10 overflow-hidden mb-4" style={{ background: 'rgba(21, 28, 36, 0.8)' }} data-testid="learning-progress-panel">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
        data-testid="learning-progress-toggle"
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
            <div className="text-[12px] text-zinc-500">Overall</div>
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
                    <span className="text-[12px] text-zinc-500">{item.detail}</span>
                    {item.ready && (
                      <span className="text-[12px] text-green-400 flex items-center gap-1">
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

export default LearningProgressPanel;
