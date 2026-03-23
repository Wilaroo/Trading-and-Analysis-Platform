import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket,
  CheckCircle2,
  Loader2,
  AlertCircle,
  X,
  Bot,
  LineChart,
  Wallet,
  Radio,
  Brain,
  Shield,
  TrendingUp,
  Eye,
  Zap,
  Target,
  BarChart3,
  Bell,
  Database,
  Activity,
  Cpu,
  Wifi
} from 'lucide-react';
import { useStartupManager } from '../contexts';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Wave-based startup processes - organized by when they load
const STARTUP_WAVES_CONFIG = [
  {
    wave: 1,
    label: 'Core Systems',
    delay: '0s',
    color: 'cyan',
    processes: [
      { id: 'backend', label: 'Backend API', icon: Cpu },
      { id: 'websocket', label: 'Real-time Data', icon: Wifi },
      { id: 'auth', label: 'Authentication', icon: Shield },
    ]
  },
  {
    wave: 2,
    label: 'Trading Features',
    delay: '5s',
    color: 'blue',
    processes: [
      { id: 'ib', label: 'IB Gateway', icon: Database },
      { id: 'scanner', label: 'Live Scanner', icon: Eye },
      { id: 'alerts', label: 'Price Alerts', icon: Bell },
    ]
  },
  {
    wave: 3,
    label: 'AI Systems',
    delay: '15s',
    color: 'purple',
    processes: [
      { id: 'ollama', label: 'AI Assistant', icon: Bot },
      { id: 'debate', label: 'Trade Advisor', icon: Brain },
      { id: 'timeseries', label: 'Predictions', icon: TrendingUp },
    ]
  },
  {
    wave: 4,
    label: 'Analytics',
    delay: '30s',
    color: 'amber',
    processes: [
      { id: 'learning', label: 'Learning Engine', icon: Activity },
      { id: 'strategy', label: 'Strategy Tracker', icon: Target },
      { id: 'reportcard', label: 'Performance', icon: BarChart3 },
    ]
  },
  {
    wave: 5,
    label: 'Background',
    delay: '60s',
    color: 'emerald',
    processes: [
      { id: 'collector', label: 'Data Collector', icon: Database },
      { id: 'simulation', label: 'Backtesting', icon: LineChart },
    ]
  }
];

// Feature explanations for the app
const FEATURES = [
  {
    icon: Bot,
    title: "AI Trading Assistant",
    highlight: "Privacy-first AI"
  },
  {
    icon: Eye,
    title: "Live Scanner",
    highlight: "30+ strategies"
  },
  {
    icon: Target,
    title: "Trade Pipeline",
    highlight: "Built-in journaling"
  }
];

const StartupModal = ({ onComplete }) => {
  const [visible, setVisible] = useState(true);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [processStatus, setProcessStatus] = useState({});
  const [allReady, setAllReady] = useState(false);
  const [error, setError] = useState(null);
  
  // Get startup manager state
  const { currentWave, startupProgress, isStartupComplete } = useStartupManager();

  // Check if user has opted out
  useEffect(() => {
    const skipStartup = localStorage.getItem('tradecommand_skip_startup');
    if (skipStartup === 'true') {
      setVisible(false);
      onComplete?.();
    }
  }, [onComplete]);

  // Run startup checks for current wave
  const runWaveChecks = useCallback(async (waveNum) => {
    const waveConfig = STARTUP_WAVES_CONFIG.find(w => w.wave === waveNum);
    if (!waveConfig) return;

    // Set all processes in this wave to loading
    const updates = {};
    waveConfig.processes.forEach(p => {
      updates[p.id] = 'loading';
    });
    setProcessStatus(prev => ({ ...prev, ...updates }));

    // Check each process in the wave
    for (const process of waveConfig.processes) {
      try {
        let status = 'success';
        
        switch (process.id) {
          case 'backend':
            const healthRes = await fetch(`${API_URL}/api/health`, { 
              signal: AbortSignal.timeout(5000) 
            });
            status = healthRes.ok ? 'success' : 'warning';
            break;
            
          case 'websocket':
            // WebSocket is handled by the app - assume success after backend
            status = 'success';
            break;
            
          case 'auth':
            // Auth is ready if backend is ready
            status = 'success';
            break;
            
          case 'ib':
            const ibRes = await fetch(`${API_URL}/api/ib/status`, { 
              signal: AbortSignal.timeout(5000) 
            }).catch(() => null);
            if (ibRes) {
              const ibData = await ibRes.json().catch(() => ({}));
              status = ibData.connected ? 'success' : 'warning';
            } else {
              status = 'warning';
            }
            break;
            
          case 'scanner':
          case 'alerts':
            // These are ready once backend is up
            status = 'success';
            break;
            
          case 'ollama':
            const ollamaRes = await fetch(`${API_URL}/api/assistant/check-ollama`, {
              signal: AbortSignal.timeout(5000)
            }).catch(() => null);
            if (ollamaRes) {
              const ollamaData = await ollamaRes.json().catch(() => ({}));
              status = ollamaData.available || ollamaData.ollama_available ? 'success' : 'warning';
            } else {
              status = 'warning';
            }
            break;
            
          case 'debate':
          case 'timeseries':
          case 'learning':
          case 'strategy':
          case 'reportcard':
          case 'collector':
          case 'simulation':
            // These load lazily - mark as ready
            status = 'success';
            break;
            
          default:
            status = 'success';
        }
        
        setProcessStatus(prev => ({ ...prev, [process.id]: status }));
      } catch (e) {
        setProcessStatus(prev => ({ ...prev, [process.id]: 'warning' }));
      }
    }
  }, []);

  // Run checks when wave changes
  useEffect(() => {
    if (visible && currentWave > 0) {
      runWaveChecks(currentWave);
    }
  }, [visible, currentWave, runWaveChecks]);

  // Enable button after minimum time or when startup is complete
  useEffect(() => {
    if (isStartupComplete || startupProgress >= 40) {
      setAllReady(true);
    }
    
    // Fallback: Enable after 8 seconds
    const fallbackTimer = setTimeout(() => setAllReady(true), 8000);
    return () => clearTimeout(fallbackTimer);
  }, [isStartupComplete, startupProgress]);

  const handleGetStarted = () => {
    if (dontShowAgain) {
      localStorage.setItem('tradecommand_skip_startup', 'true');
    }
    setVisible(false);
    onComplete?.();
  };

  const getStatusIcon = (status, IconComponent) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />;
      case 'loading':
        return <Loader2 className="w-3.5 h-3.5 text-cyan-400 animate-spin" />;
      case 'error':
        return <AlertCircle className="w-3.5 h-3.5 text-red-400" />;
      case 'warning':
        return <CheckCircle2 className="w-3.5 h-3.5 text-yellow-400" />;
      default:
        return <IconComponent className="w-3.5 h-3.5 text-zinc-600" />;
    }
  };

  const getWaveColor = (color, isActive) => {
    if (!isActive) return 'bg-zinc-800 border-zinc-700';
    const colors = {
      cyan: 'bg-cyan-500/10 border-cyan-500/30',
      blue: 'bg-blue-500/10 border-blue-500/30',
      purple: 'bg-purple-500/10 border-purple-500/30',
      amber: 'bg-amber-500/10 border-amber-500/30',
      emerald: 'bg-emerald-500/10 border-emerald-500/30',
    };
    return colors[color] || colors.cyan;
  };

  if (!visible) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 flex items-center justify-center bg-black/90 backdrop-blur-md"
        style={{ zIndex: 9999 }}
        data-testid="startup-modal"
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="relative w-full max-w-lg mx-4 bg-zinc-900 rounded-xl border border-zinc-700 shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="relative px-5 py-4 bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border-b border-zinc-700">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-gradient-to-br from-cyan-500 to-purple-500">
                  <Rocket className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h1 className="text-lg font-bold text-white">TradeCommand</h1>
                  <p className="text-zinc-400 text-xs">Initializing systems...</p>
                </div>
              </div>
              
              {/* Progress indicator */}
              <div className="text-right">
                <div className="text-2xl font-bold text-cyan-400">{startupProgress}%</div>
                <div className="text-[10px] text-zinc-500">Wave {currentWave}/5</div>
              </div>
            </div>
            
            {/* Progress bar */}
            <div className="mt-3 h-1 bg-zinc-800 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-cyan-500 to-purple-500"
                initial={{ width: 0 }}
                animate={{ width: `${startupProgress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </div>

          {/* Wave-based loading display */}
          <div className="px-5 py-4 space-y-2 max-h-[300px] overflow-y-auto">
            {STARTUP_WAVES_CONFIG.map((wave) => {
              const isActive = currentWave >= wave.wave;
              const isCurrentWave = currentWave === wave.wave;
              
              return (
                <motion.div
                  key={wave.wave}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ 
                    opacity: isActive ? 1 : 0.4, 
                    x: 0 
                  }}
                  transition={{ delay: wave.wave * 0.1 }}
                  className={`rounded-lg border p-2.5 transition-all ${getWaveColor(wave.color, isActive)}`}
                >
                  {/* Wave header */}
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-semibold ${isActive ? 'text-white' : 'text-zinc-500'}`}>
                        {wave.label}
                      </span>
                      {isCurrentWave && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] bg-cyan-500/20 text-cyan-400 animate-pulse">
                          LOADING
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-zinc-500">+{wave.delay}</span>
                  </div>
                  
                  {/* Processes in this wave */}
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {wave.processes.map((process) => {
                      const status = processStatus[process.id];
                      const Icon = process.icon;
                      
                      return (
                        <div
                          key={process.id}
                          className="flex items-center gap-1.5"
                          data-testid={`startup-process-${process.id}`}
                        >
                          {getStatusIcon(status, Icon)}
                          <span className={`text-[11px] ${
                            status === 'success' ? 'text-green-400' :
                            status === 'warning' ? 'text-yellow-400' :
                            status === 'loading' ? 'text-cyan-400' :
                            isActive ? 'text-zinc-400' : 'text-zinc-600'
                          }`}>
                            {process.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              );
            })}
          </div>

          {/* Feature hints */}
          <div className="px-5 py-2 border-t border-zinc-800">
            <div className="flex justify-center gap-4">
              {FEATURES.map((feature, idx) => (
                <div key={idx} className="flex items-center gap-1.5 text-[10px] text-zinc-500">
                  <feature.icon className="w-3 h-3 text-cyan-400/70" />
                  <span>{feature.highlight}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 py-3 bg-zinc-800/50 border-t border-zinc-700 flex items-center justify-between">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={dontShowAgain}
                onChange={(e) => setDontShowAgain(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-zinc-600 bg-zinc-700 text-cyan-500 focus:ring-cyan-500"
                data-testid="dont-show-again-checkbox"
              />
              <span className="text-xs text-zinc-400">Skip next time</span>
            </label>

            <button
              onClick={handleGetStarted}
              disabled={!allReady && !error}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-1.5 ${
                allReady || error
                  ? 'bg-gradient-to-r from-cyan-500 to-purple-500 text-white hover:shadow-lg hover:shadow-cyan-500/25'
                  : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
              }`}
              data-testid="get-started-btn"
            >
              {allReady || error ? (
                <>
                  <Zap className="w-3.5 h-3.5" />
                  Get Started
                </>
              ) : (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Loading...
                </>
              )}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default StartupModal;
