import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, TrendingDown, AlertTriangle, X, Volume2, VolumeX, Settings } from 'lucide-react';

export const PriceAlertNotification = ({ alerts, onDismiss, audioEnabled, setAudioEnabled }) => {
  if (alerts.length === 0) return null;
  
  return (
    <div className="fixed top-20 right-4 z-50 space-y-2 max-h-[60vh] overflow-y-auto">
      <AnimatePresence>
        {alerts.slice(0, 5).map((alert) => (
          <motion.div
            key={alert.id}
            initial={{ opacity: 0, x: 100, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.9 }}
            className={`glass-card rounded-lg p-4 min-w-[280px] border-l-4 ${
              alert.type === 'bullish' 
                ? 'border-l-green-500 bg-green-500/10' 
                : alert.type === 'bearish'
                ? 'border-l-red-500 bg-red-500/10'
                : 'border-l-blue-500 bg-blue-500/10'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                {alert.type === 'bullish' ? (
                  <TrendingUp className="w-5 h-5 text-green-400" />
                ) : alert.type === 'bearish' ? (
                  <TrendingDown className="w-5 h-5 text-red-400" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-yellow-400" />
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{alert.symbol}</span>
                    <span className={`font-mono text-sm ${
                      alert.changePercent > 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {alert.changePercent > 0 ? '+' : ''}{alert.changePercent?.toFixed(2)}%
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400">{alert.message}</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    ${alert.price?.toFixed(2)} • {new Date(alert.timestamp).toLocaleTimeString()}
                  </p>
                </div>
              </div>
              <button
                onClick={() => onDismiss(alert.id)}
                className="text-zinc-500 hover:text-white transition-colors"
                data-testid={`dismiss-alert-${alert.symbol}`}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

// Alert Settings Panel
export const AlertSettingsPanel = ({ 
  audioEnabled, 
  setAudioEnabled, 
  alertThreshold, 
  setAlertThreshold,
  isOpen,
  onClose 
}) => {
  if (!isOpen) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      className="fixed bottom-20 right-4 z-50 bg-paper border border-white/10 rounded-xl p-4 w-72 shadow-xl"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold flex items-center gap-2">
          <Settings className="w-4 h-4" />
          Alert Settings
        </h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-white">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Audio Toggle */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-400">Audio Alerts</span>
          <button
            onClick={() => setAudioEnabled(!audioEnabled)}
            className={`p-2 rounded-lg transition-all ${
              audioEnabled 
                ? 'bg-primary/20 text-primary' 
                : 'bg-zinc-800 text-zinc-500'
            }`}
          >
            {audioEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          </button>
        </div>

        {/* Threshold Slider */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-zinc-400">Alert Threshold</span>
            <span className="text-sm font-mono text-primary">±{alertThreshold}%</span>
          </div>
          <input
            type="range"
            min="0.5"
            max="10"
            step="0.5"
            value={alertThreshold}
            onChange={(e) => setAlertThreshold(parseFloat(e.target.value))}
            className="w-full accent-primary"
            data-testid="alert-threshold-slider"
          />
          <div className="flex justify-between text-xs text-zinc-500 mt-1">
            <span>0.5%</span>
            <span>5%</span>
            <span>10%</span>
          </div>
        </div>

        <p className="text-xs text-zinc-500">
          Alerts trigger when price moves ≥ {alertThreshold}% from the daily open.
        </p>
      </div>
    </motion.div>
  );
};

export default PriceAlertNotification;
