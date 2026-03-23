/**
 * SimulatorControl - UI control for the Market Hours Simulator
 * Allows testing scanner alerts when markets are closed
 */
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Play, 
  Square, 
  FlaskConical, 
  ChevronDown,
  RefreshCw,
  Clock,
  Zap,
  TrendingUp,
  TrendingDown,
  Activity,
  AlertTriangle,
  Settings2,
  CheckCircle2,
  XCircle
} from 'lucide-react';
import { useTrainingMode } from '../contexts';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Scenario configurations with icons and colors
const SCENARIO_CONFIG = {
  bullish_momentum: {
    icon: TrendingUp,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/20',
    border: 'border-emerald-500/40',
    label: 'Bullish Momentum',
    description: 'Strong uptrend day - momentum setups'
  },
  bearish_reversal: {
    icon: TrendingDown,
    color: 'text-red-400',
    bg: 'bg-red-500/20',
    border: 'border-red-500/40',
    label: 'Bearish Reversal',
    description: 'Market weakness - reversal setups'
  },
  range_bound: {
    icon: Activity,
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/20',
    border: 'border-yellow-500/40',
    label: 'Range Bound',
    description: 'Choppy market - mean reversion'
  },
  high_volatility: {
    icon: AlertTriangle,
    color: 'text-orange-400',
    bg: 'bg-orange-500/20',
    border: 'border-orange-500/40',
    label: 'High Volatility',
    description: 'High VIX environment - squeeze plays'
  }
};

// Interval presets
const INTERVAL_PRESETS = [
  { value: 10, label: '10s', description: 'Very Fast' },
  { value: 30, label: '30s', description: 'Fast' },
  { value: 60, label: '1m', description: 'Normal' },
  { value: 120, label: '2m', description: 'Slow' }
];

const SimulatorControl = ({ onAlertGenerated, onAlertsUpdated, className = '' }) => {
  const [status, setStatus] = useState({
    running: false,
    scenario: 'range_bound',
    alert_interval: 30,
    alerts_generated: 0
  });
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState('range_bound');
  const [selectedInterval, setSelectedInterval] = useState(30);
  const [error, setError] = useState(null);
  const [lastAlertCount, setLastAlertCount] = useState(0);

  // Fetch simulator status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/simulator/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setSelectedScenario(data.scenario || 'range_bound');
        setSelectedInterval(data.alert_interval || 30);
        setError(null);
      }
    } catch (err) {
      console.error('Failed to fetch simulator status:', err);
    }
  }, []);

  // Fetch simulator alerts and update parent
  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/simulator/alerts`);
      if (res.ok) {
        const data = await res.json();
        const alerts = data.alerts || [];
        // Notify parent of all simulated alerts
        if (onAlertsUpdated && alerts.length > 0) {
          onAlertsUpdated(alerts);
        }
        setLastAlertCount(alerts.length);
      }
    } catch (err) {
      console.error('Failed to fetch simulator alerts:', err);
    }
  }, [onAlertsUpdated]);

  // Start simulator
  const startSimulator = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_URL}/api/simulator/start?scenario=${selectedScenario}&interval=${selectedInterval}`,
        { method: 'POST' }
      );
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setShowSettings(false);
      } else {
        const err = await res.json();
        setError(err.detail || 'Failed to start simulator');
      }
    } catch (err) {
      setError('Failed to connect to simulator');
      console.error('Failed to start simulator:', err);
    }
    setLoading(false);
  };

  // Stop simulator
  const stopSimulator = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/simulator/stop`, { method: 'POST' });
      if (res.ok) {
        await fetchStatus();
      }
    } catch (err) {
      console.error('Failed to stop simulator:', err);
    }
    setLoading(false);
  };

  // Generate single alert on demand
  const generateAlert = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/simulator/generate`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.success && data.alert) {
          onAlertGenerated?.(data.alert);
        }
        await fetchStatus();
      }
    } catch (err) {
      console.error('Failed to generate alert:', err);
    }
    setLoading(false);
  };

  // Poll status and alerts when running
  // Reduce polling frequency during AI training to prevent resource exhaustion
  const { getPollingInterval, isTrainingActive } = useTrainingMode();
  
  useEffect(() => {
    fetchStatus();
    
    let statusInterval;
    let alertsInterval;
    
    if (status.running) {
      // Get adjusted intervals - slower during training
      const statusPollInterval = getPollingInterval(5000, false); // Non-essential
      const alertsPollInterval = getPollingInterval(3000, false); // Non-essential
      
      // Poll status 
      statusInterval = setInterval(fetchStatus, statusPollInterval);
      // Poll alerts
      fetchAlerts(); // Initial fetch
      alertsInterval = setInterval(fetchAlerts, alertsPollInterval);
      
      if (isTrainingActive) {
        console.log(`[SimulatorControl] Training active - polling slowed to ${statusPollInterval}ms / ${alertsPollInterval}ms`);
      }
    }
    
    return () => {
      if (statusInterval) clearInterval(statusInterval);
      if (alertsInterval) clearInterval(alertsInterval);
    };
  }, [status.running, fetchStatus, fetchAlerts, getPollingInterval, isTrainingActive]);

  const currentScenario = SCENARIO_CONFIG[status.scenario] || SCENARIO_CONFIG.range_bound;
  const ScenarioIcon = currentScenario.icon;

  return (
    <div className={`relative ${className}`}>
      {/* Main Control Bar */}
      <div 
        className={`flex items-center gap-2 p-2 rounded-lg border transition-all ${
          status.running 
            ? 'bg-purple-500/10 border-purple-500/40' 
            : 'bg-zinc-800/50 border-zinc-700/50'
        }`}
        data-testid="simulator-control"
      >
        {/* Simulator Label */}
        <div className="flex items-center gap-2">
          <FlaskConical className={`w-4 h-4 ${status.running ? 'text-purple-400' : 'text-zinc-500'}`} />
          <span className={`text-xs font-medium ${status.running ? 'text-purple-400' : 'text-zinc-400'}`}>
            Simulator
          </span>
        </div>

        {/* Status Badge */}
        {status.running && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 text-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
            Running
          </div>
        )}

        {/* Current Scenario (when running) */}
        {status.running && (
          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded ${currentScenario.bg} ${currentScenario.color} text-xs`}>
            <ScenarioIcon className="w-3 h-3" />
            {currentScenario.label}
          </div>
        )}

        {/* Alerts Count */}
        {status.alerts_generated > 0 && (
          <span className="text-xs text-zinc-500">
            {status.alerts_generated} alerts
          </span>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Settings Toggle */}
        <button
          onClick={() => setShowSettings(!showSettings)}
          className={`p-1.5 rounded transition-colors ${
            showSettings 
              ? 'bg-cyan-500/20 text-cyan-400' 
              : 'hover:bg-white/10 text-zinc-400 hover:text-white'
          }`}
          title="Simulator Settings"
          data-testid="simulator-settings-btn"
        >
          <Settings2 className="w-4 h-4" />
        </button>

        {/* Generate Single Alert Button */}
        <button
          onClick={generateAlert}
          disabled={loading}
          className="p-1.5 rounded bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-colors disabled:opacity-50"
          title="Generate one alert now"
          data-testid="simulator-generate-btn"
        >
          <Zap className="w-4 h-4" />
        </button>

        {/* Start/Stop Button */}
        {status.running ? (
          <button
            onClick={stopSimulator}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50"
            data-testid="simulator-stop-btn"
          >
            {loading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Square className="w-4 h-4" />
            )}
            <span className="text-xs font-medium">Stop</span>
          </button>
        ) : (
          <button
            onClick={startSimulator}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-colors disabled:opacity-50"
            data-testid="simulator-start-btn"
          >
            {loading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            <span className="text-xs font-medium">Start</span>
          </button>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div className="mt-2 px-3 py-2 rounded bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
          <XCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Settings Panel */}
      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ opacity: 0, y: -10, height: 0 }}
            animate={{ opacity: 1, y: 0, height: 'auto' }}
            exit={{ opacity: 0, y: -10, height: 0 }}
            className="mt-2 p-4 rounded-lg bg-zinc-900 border border-zinc-700 overflow-hidden"
            data-testid="simulator-settings-panel"
          >
            <h4 className="text-sm font-medium text-white mb-4 flex items-center gap-2">
              <FlaskConical className="w-4 h-4 text-purple-400" />
              Simulator Configuration
            </h4>

            {/* Scenario Selection */}
            <div className="mb-4">
              <label className="text-xs text-zinc-500 uppercase tracking-wider mb-2 block">
                Market Scenario
              </label>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(SCENARIO_CONFIG).map(([key, config]) => {
                  const Icon = config.icon;
                  return (
                    <button
                      key={key}
                      onClick={() => setSelectedScenario(key)}
                      className={`p-3 rounded-lg border text-left transition-all ${
                        selectedScenario === key
                          ? `${config.bg} ${config.border} ${config.color}`
                          : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-600'
                      }`}
                      data-testid={`scenario-${key}`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Icon className="w-4 h-4" />
                        <span className="text-sm font-medium">{config.label}</span>
                      </div>
                      <p className="text-xs text-zinc-500">{config.description}</p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Interval Selection */}
            <div className="mb-4">
              <label className="text-xs text-zinc-500 uppercase tracking-wider mb-2 block flex items-center gap-2">
                <Clock className="w-3 h-3" />
                Alert Interval
              </label>
              <div className="flex gap-2">
                {INTERVAL_PRESETS.map(preset => (
                  <button
                    key={preset.value}
                    onClick={() => setSelectedInterval(preset.value)}
                    className={`flex-1 p-2 rounded-lg border text-center transition-all ${
                      selectedInterval === preset.value
                        ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                        : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-600'
                    }`}
                    data-testid={`interval-${preset.value}`}
                  >
                    <div className="text-sm font-medium">{preset.label}</div>
                    <div className="text-[10px] text-zinc-500">{preset.description}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Apply Button */}
            <div className="flex items-center justify-between pt-3 border-t border-zinc-700">
              <p className="text-xs text-zinc-500">
                {status.running 
                  ? 'Changes will apply when you restart the simulator' 
                  : 'Configure settings and click Start to begin'}
              </p>
              {!status.running && (
                <button
                  onClick={startSimulator}
                  disabled={loading}
                  className="flex items-center gap-2 px-4 py-2 bg-emerald-500 text-black rounded-lg text-sm font-medium hover:bg-emerald-400 disabled:opacity-50"
                  data-testid="apply-start-btn"
                >
                  {loading ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4" />
                  )}
                  Start Simulator
                </button>
              )}
            </div>

            {/* Info Note */}
            <div className="mt-4 p-3 rounded-lg bg-purple-500/10 border border-purple-500/20 text-xs text-purple-300">
              <p className="flex items-start gap-2">
                <FlaskConical className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>
                  The simulator generates realistic scanner alerts for testing when markets are closed. 
                  Simulated alerts are marked with a special badge and won't trigger real trading actions.
                </span>
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SimulatorControl;
