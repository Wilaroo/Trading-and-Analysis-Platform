/**
 * StartupModal - Fast Service Health Verification
 * 
 * Uses a SINGLE /api/startup-check endpoint that returns all service
 * statuses from in-memory state. This avoids the event loop blocking
 * problem where individual endpoints can take 10-50s to respond.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket,
  CheckCircle2,
  Loader2,
  AlertCircle,
  XCircle,
  Bot,
  LineChart,
  Brain,
  TrendingUp,
  Zap,
  Database,
  Activity,
  Cpu,
  Wifi,
  RefreshCw
} from 'lucide-react';
import { useConnectionManager as useConnection } from '../contexts/ConnectionManagerContext';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// XHR-based fetch — completely bypasses fetch throttler/patching
function xhrGet(url, timeout) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.timeout = timeout;
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve({ ok: true, data: JSON.parse(xhr.responseText) });
        } catch {
          resolve({ ok: true, data: {} });
        }
      } else {
        resolve({ ok: false, status: xhr.status });
      }
    };
    xhr.ontimeout = () => resolve({ ok: false, timedOut: true });
    xhr.onerror = () => resolve({ ok: false, errored: true });
    xhr.open('GET', url);
    xhr.send();
  });
}

// Service definitions — visual only, checks come from consolidated endpoint
const SERVICES = [
  { id: 'backend',    label: 'Backend API',     icon: Cpu,         required: true,  category: 'core' },
  { id: 'websocket',  label: 'WebSocket',       icon: Wifi,        required: false, category: 'core' },
  { id: 'database',   label: 'Database',        icon: Database,    required: true,  category: 'core' },
  { id: 'ib',         label: 'IB Gateway',      icon: TrendingUp,  required: false, category: 'trading' },
  { id: 'scanner',    label: 'Live Scanner',    icon: Activity,    required: false, category: 'trading' },
  { id: 'ollama',     label: 'AI Assistant',    icon: Bot,         required: false, category: 'ai' },
  { id: 'timeseries', label: 'AI Predictions',  icon: Brain,       required: false, category: 'ai' },
  { id: 'learning',   label: 'Learning Engine', icon: LineChart,   required: false, category: 'analytics' },
];

const CATEGORIES = {
  core:      { label: 'Core Systems', required: true },
  trading:   { label: 'Trading',      required: false },
  ai:        { label: 'AI Systems',   required: false },
  analytics: { label: 'Analytics',    required: false },
};

const StartupModal = ({ onComplete }) => {
  const [visible, setVisible] = useState(true);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [serviceStatus, setServiceStatus] = useState({});
  const [lastResponseData, setLastResponseData] = useState(null);
  const [isChecking, setIsChecking] = useState(true);
  const [checkCount, setCheckCount] = useState(0);
  const mountedRef = useRef(true);
  const timerRef = useRef(null);
  
  // Frontend WS connection state — supplements backend's report
  const { wsConnected: frontendWsConnected } = useConnection();

  // Check if user has opted out
  useEffect(() => {
    const skipStartup = localStorage.getItem('tradecommand_skip_startup');
    if (skipStartup === 'true') {
      setVisible(false);
      onComplete?.();
    }
  }, [onComplete]);

  // Single consolidated check — one XHR call returns everything
  const runCheck = useCallback(async () => {
    if (!mountedRef.current) return;
    setIsChecking(true);
    setCheckCount(prev => prev + 1);

    const url = `${API_URL}/api/startup-check`;
    const result = await xhrGet(url, 8000); // 8s timeout for slower networks

    if (!mountedRef.current) return;

    if (result.ok && result.data) {
      const d = result.data;
      const newStatus = {};
      
      // Map backend response to service statuses
      newStatus.backend   = d.backend   ? 'success' : 'error';
      newStatus.database  = d.database  ? 'success' : 'error';
      // WebSocket: green if both backend WS server has connections AND frontend is connected
      newStatus.websocket = (d.websocket || frontendWsConnected) ? 'success' : (d.backend ? 'warning' : 'error');
      // IB Gateway: green only if connected AND data flowing (farms active)
      // Yellow if socket connected but farms not sending data
      newStatus.ib        = d.ib        ? 'success' : d.ib_connected ? 'warning' : 'warning';
      newStatus.scanner   = d.scanner   ? 'success' : 'warning';
      // AI Assistant: green if Ollama connected, yellow if only Emergent fallback
      newStatus.ollama    = d.ollama    ? 'success' : d.ai_fallback_only ? 'warning' : 'warning';
      newStatus.timeseries = d.timeseries ? 'success' : 'warning';
      newStatus.learning  = d.learning  ? 'success' : 'warning';

      console.log(`[StartupModal] Check #${checkCount + 1}: backend=${d.backend} db=${d.database} ws=${d.websocket}(${d.ws_connections || 0} conns, fe=${frontendWsConnected}) ib=${d.ib} ib_connected=${d.ib_connected} ib_data=${d.ib_data_flowing} ollama=${d.ollama} ai_fallback=${d.ai_fallback_only} scanner=${d.scanner}`);
      setServiceStatus(newStatus);
      setLastResponseData(d);
    } else {
      // Backend not reachable yet — all services loading
      console.log(`[StartupModal] Check #${checkCount + 1}: Backend not reachable (timeout=${result.timedOut})`);
    }

    setIsChecking(false);
  }, [checkCount]);

  // Polling loop using recursive setTimeout (no overlap)
  useEffect(() => {
    if (!visible) return;
    mountedRef.current = true;

    const loop = async () => {
      if (!mountedRef.current) return;
      await runCheck();
      if (mountedRef.current) {
        timerRef.current = setTimeout(loop, 1500); // Re-check every 1.5s
      }
    };

    // Start after a tiny delay
    timerRef.current = setTimeout(loop, 200);

    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  // Calculate readiness
  const requiredServices = SERVICES.filter(s => s.required);
  const requiredReady = requiredServices.every(s => serviceStatus[s.id] === 'success');
  const allChecked = Object.keys(serviceStatus).length >= SERVICES.length;
  const allGreen = SERVICES.every(s => serviceStatus[s.id] === 'success' || serviceStatus[s.id] === 'warning');
  const isReady = requiredReady && allChecked;
  const canForceStart = checkCount >= 2;

  // Stop polling when all done
  useEffect(() => {
    if (allGreen && timerRef.current) {
      clearTimeout(timerRef.current);
      mountedRef.current = false;
      timerRef.current = null;
    }
  }, [allGreen]);

  // Progress
  const successCount = Object.values(serviceStatus).filter(s => s === 'success').length;
  const progress = Math.round((successCount / SERVICES.length) * 100);

  const handleGetStarted = () => {
    if (dontShowAgain) {
      localStorage.setItem('tradecommand_skip_startup', 'true');
    }
    setVisible(false);
    onComplete?.();
  };

  const handleRetry = () => {
    setServiceStatus({});
    setCheckCount(0);
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'warning':
        return <AlertCircle className="w-4 h-4 text-yellow-400" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
    }
  };

  const getStatusText = (status, serviceId, data) => {
    if (serviceId === 'ollama' && status === 'warning' && data?.ai_fallback_only) {
      return 'Fallback Only';
    }
    if (serviceId === 'ib' && status === 'warning' && data?.ib_connected) {
      return 'No Data';
    }
    if (serviceId === 'websocket' && status === 'success' && data?.ws_connections > 0) {
      return `Live (${data.ws_connections} conn${data.ws_connections > 1 ? 's' : ''})`;
    }
    if (serviceId === 'websocket' && status === 'warning') {
      return 'Connecting...';
    }
    switch (status) {
      case 'success': return 'Ready';
      case 'warning': return 'Unavailable';
      case 'error':   return 'Offline';
      default:        return 'Checking...';
    }
  };

  if (!visible) return null;

  // Group services by category
  const servicesByCategory = {};
  SERVICES.forEach(service => {
    if (!servicesByCategory[service.category]) servicesByCategory[service.category] = [];
    servicesByCategory[service.category].push(service);
  });

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
                  <p className="text-zinc-400 text-xs">
                    {allGreen ? 'All systems ready!' : isReady ? 'Core ready — optional services loading...' : 'Verifying systems...'}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <div className={`text-2xl font-bold ${allGreen ? 'text-green-400' : isReady ? 'text-emerald-400' : 'text-cyan-400'}`}>
                  {progress}%
                </div>
                <div className="text-[12px] text-zinc-500">
                  {successCount}/{SERVICES.length} services
                </div>
              </div>
            </div>
            <div className="mt-3 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <motion.div
                className={`h-full ${allGreen ? 'bg-green-500' : 'bg-gradient-to-r from-cyan-500 to-purple-500'}`}
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </div>

          {/* Services by Category */}
          <div className="px-5 py-4 space-y-3">
            {Object.entries(servicesByCategory).map(([categoryId, services]) => {
              const category = CATEGORIES[categoryId];
              const categoryReady = services.every(s => serviceStatus[s.id] === 'success');
              const categoryHasError = services.some(s => serviceStatus[s.id] === 'error');

              return (
                <div
                  key={categoryId}
                  className={`rounded-lg border p-3 transition-all ${
                    categoryReady
                      ? 'bg-green-500/10 border-green-500/30'
                      : categoryHasError
                        ? 'bg-red-500/10 border-red-500/30'
                        : 'bg-zinc-800/50 border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-xs font-semibold ${categoryReady ? 'text-green-400' : 'text-white'}`}>
                      {category.label}
                      {category.required && <span className="text-red-400 ml-1">*</span>}
                    </span>
                    {categoryReady && (
                      <span className="text-[12px] text-green-400 px-1.5 py-0.5 bg-green-500/20 rounded">
                        READY
                      </span>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    {services.map((service) => {
                      const status = serviceStatus[service.id];
                      const Icon = service.icon;
                      return (
                        <div key={service.id} className="flex items-center justify-between" data-testid={`startup-service-${service.id}`}>
                          <div className="flex items-center gap-2">
                            <Icon className={`w-3.5 h-3.5 ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'warning' ? 'text-yellow-400' :
                              'text-zinc-500'
                            }`} />
                            <span className={`text-sm ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'warning' ? 'text-yellow-400' :
                              'text-zinc-400'
                            }`}>
                              {service.label}
                              {service.required && <span className="text-red-400 ml-0.5 text-[12px]">*</span>}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[12px] ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'warning' ? 'text-yellow-400' :
                              'text-zinc-500'
                            }`}>
                              {getStatusText(status, service.id, lastResponseData)}
                            </span>
                            {getStatusIcon(status)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legend */}
          <div className="px-5 py-2 border-t border-zinc-800 bg-zinc-900/50">
            <div className="flex items-center justify-center gap-4 text-[12px] text-zinc-500">
              <span><span className="text-red-400">*</span> Required for startup</span>
              <span>Check #{checkCount}</span>
              {isChecking && <Loader2 className="w-3 h-3 animate-spin text-cyan-400" />}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 py-3 bg-zinc-800/50 border-t border-zinc-700 flex items-center justify-between">
            <div className="flex items-center gap-3">
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
                onClick={handleRetry}
                disabled={isChecking}
                className="p-1.5 rounded hover:bg-zinc-700 transition-colors disabled:opacity-50"
                title="Retry checks"
                data-testid="retry-checks-btn"
              >
                <RefreshCw className={`w-4 h-4 text-zinc-400 ${isChecking ? 'animate-spin' : ''}`} />
              </button>
            </div>

            <button
              onClick={handleGetStarted}
              disabled={!isReady && !canForceStart}
              className={`px-5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                isReady
                  ? 'bg-gradient-to-r from-green-500 to-emerald-500 text-white hover:shadow-lg hover:shadow-green-500/25'
                  : canForceStart
                    ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white hover:shadow-lg hover:shadow-amber-500/25'
                    : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
              }`}
              data-testid="get-started-btn"
            >
              {isReady ? (
                <>
                  <Zap className="w-4 h-4" />
                  Get Started
                </>
              ) : canForceStart ? (
                <>
                  <Zap className="w-4 h-4" />
                  Start Anyway
                </>
              ) : (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Checking services...
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
