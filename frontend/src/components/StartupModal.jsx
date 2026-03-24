/**
 * StartupModal - REAL Service Health Verification
 * 
 * Two behaviors:
 * - REFRESH (backend already up): Backend probe succeeds → all services checked in parallel
 *   with short 2s timeouts → completes in ~1 check round.
 * - COLD START (backend booting): Sequential checks with 10s timeouts, 750ms between each.
 *   Shows real progress as each service comes online. Completes in 1-2 rounds once backend is up.
 * 
 * Green checkmark = service actually responded successfully.
 * "Get Started" enabled when all required services verified AND all services checked once.
 */

import React, { useState, useEffect, useRef } from 'react';
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

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Service definitions with their health check endpoints
const SERVICES = [
  {
    id: 'backend',
    label: 'Backend API',
    icon: Cpu,
    endpoint: '/api/health',
    required: true,
    category: 'core'
  },
  {
    id: 'websocket',
    label: 'WebSocket',
    icon: Wifi,
    checkType: 'websocket',
    required: true,
    category: 'core'
  },
  {
    id: 'database',
    label: 'Database',
    icon: Database,
    endpoint: '/api/health',
    required: true,
    category: 'core'
  },
  {
    id: 'ib',
    label: 'IB Gateway',
    icon: TrendingUp,
    endpoint: '/api/ib/status',
    responseCheck: (data) => data?.connected === true,
    required: false,
    category: 'trading'
  },
  {
    id: 'scanner',
    label: 'Live Scanner',
    icon: Activity,
    endpoint: '/api/sentcom/status',
    required: false,
    category: 'trading'
  },
  {
    id: 'ollama',
    label: 'AI Assistant',
    icon: Bot,
    endpoint: '/api/assistant/check-ollama',
    responseCheck: (data) => data?.available === true || data?.ollama_available === true,
    required: false,
    category: 'ai'
  },
  {
    id: 'timeseries',
    label: 'AI Predictions',
    icon: Brain,
    endpoint: '/api/ai-modules/timeseries/status',
    required: false,
    category: 'ai'
  },
  {
    id: 'learning',
    label: 'Learning Engine',
    icon: LineChart,
    endpoint: '/api/learning-connectors/status',
    required: false,
    category: 'analytics'
  }
];

const CATEGORIES = {
  core: { label: 'Core Systems', color: 'cyan', required: true },
  trading: { label: 'Trading', color: 'blue', required: false },
  ai: { label: 'AI Systems', color: 'purple', required: false },
  analytics: { label: 'Analytics', color: 'amber', required: false }
};

// Helper: check a single HTTP service
async function checkOneService(service, timeout) {
  const directFetch = window.__originalFetch || window.fetch;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    const response = await directFetch(`${API_URL}${service.endpoint}`, {
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (!response.ok) return 'error';

    const data = await response.json().catch(() => ({}));
    if (service.responseCheck) {
      return service.responseCheck(data) ? 'success' : 'warning';
    }
    return 'success';
  } catch (e) {
    return e.name === 'AbortError' ? 'timeout' : 'error';
  }
}

const StartupModal = ({ onComplete }) => {
  const [visible, setVisible] = useState(true);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [serviceStatus, setServiceStatus] = useState({});
  const [isChecking, setIsChecking] = useState(true);
  const [checkCount, setCheckCount] = useState(0);
  const [checkMode, setCheckMode] = useState(null); // 'fast' or 'cold'
  const wsRef = useRef(null);
  const mountedRef = useRef(true);
  const statusRef = useRef({});

  // Check if user has opted out
  useEffect(() => {
    const skipStartup = localStorage.getItem('tradecommand_skip_startup');
    if (skipStartup === 'true') {
      setVisible(false);
      onComplete?.();
    }
  }, [onComplete]);

  // Helper to update a single service status
  const updateStatus = (id, status) => {
    statusRef.current = { ...statusRef.current, [id]: status };
    setServiceStatus(prev => ({ ...prev, [id]: status }));
  };

  // WebSocket check — runs independently, updates status via ref
  useEffect(() => {
    if (!visible) return;
    const wsUrl = API_URL.replace('http', 'ws') + '/api/ws/quotes';

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => updateStatus('websocket', 'success');
      ws.onerror = () => updateStatus('websocket', 'error');
      ws.onclose = () => {}; // Don't update — might close after dismiss
    } catch (e) {
      updateStatus('websocket', 'error');
    }

    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [visible]);

  // Main check loop — NO callback dependencies, uses refs to avoid restarts
  useEffect(() => {
    if (!visible) return;
    mountedRef.current = true;
    let timerRef = null;

    const run = async () => {
      // Step 1: Probe — is backend already running?
      let backendUp = false;
      try {
        const directFetch = window.__originalFetch || window.fetch;
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 3000);
        const res = await directFetch(`${API_URL}/api/health`, { signal: ctrl.signal });
        clearTimeout(tid);
        if (res.ok) backendUp = true;
      } catch (e) { /* not ready */ }

      const mode = backendUp ? 'fast' : 'cold';
      setCheckMode(mode);

      if (backendUp) {
        // Mark backend + database immediately
        updateStatus('backend', 'success');
        updateStatus('database', 'success');
      }

      // Step 2: Check loop
      const doRound = async () => {
        if (!mountedRef.current) return;
        setIsChecking(true);
        setCheckCount(prev => prev + 1);

        const currentMode = statusRef.current['backend'] === 'success' ? 'fast' : 'cold';
        if (currentMode === 'fast') setCheckMode('fast');

        // Get services that still need checking (skip websocket, skip already-passed)
        const toCheck = SERVICES.filter(s => {
          if (s.checkType === 'websocket') return false;
          if (statusRef.current[s.id] === 'success') return false;
          if (s.id === 'database' && statusRef.current['backend'] === 'success') {
            updateStatus('database', 'success');
            return false;
          }
          return true;
        });

        if (currentMode === 'fast') {
          // FAST MODE: parallel checks, short timeout
          const results = await Promise.allSettled(
            toCheck.map(async (s) => {
              const status = await checkOneService(s, 2000);
              return { id: s.id, status };
            })
          );
          for (const r of results) {
            if (r.status === 'fulfilled') {
              updateStatus(r.value.id, r.value.status);
            }
          }
        } else {
          // COLD MODE: sequential checks, long timeout, gaps between each
          // This is the original behavior that worked reliably
          for (const service of toCheck) {
            if (!mountedRef.current) return;
            const status = await checkOneService(service, 10000);
            updateStatus(service.id, status);
            // If backend just came up, switch to fast for remaining services
            if (service.id === 'backend' && status === 'success') {
              updateStatus('database', 'success');
              setCheckMode('fast');
              // Remaining services in parallel with short timeout
              const remaining = toCheck.filter(s => 
                s.id !== 'backend' && s.id !== 'database' && statusRef.current[s.id] !== 'success'
              );
              const results = await Promise.allSettled(
                remaining.map(async (s) => {
                  const st = await checkOneService(s, 2000);
                  return { id: s.id, status: st };
                })
              );
              for (const r of results) {
                if (r.status === 'fulfilled') {
                  updateStatus(r.value.id, r.value.status);
                }
              }
              break; // Done with sequential loop
            }
            // 750ms between each check in cold mode
            await new Promise(resolve => setTimeout(resolve, 750));
          }
        }

        setIsChecking(false);

        // Check if we should stop
        const allChecked = Object.keys(statusRef.current).length >= SERVICES.length;
        const reqReady = SERVICES.filter(s => s.required).every(s => statusRef.current[s.id] === 'success');

        if (allChecked && reqReady) {
          return; // Done — don't schedule next round
        }

        // Schedule next round
        if (mountedRef.current) {
          const interval = statusRef.current['backend'] === 'success' ? 500 : 3000;
          timerRef = setTimeout(doRound, interval);
        }
      };

      // Start first round
      if (mountedRef.current) {
        timerRef = setTimeout(doRound, backendUp ? 50 : 500);
      }
    };

    run();

    return () => {
      mountedRef.current = false;
      if (timerRef) clearTimeout(timerRef);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]); // Only depend on visible — all state access via refs

  // Calculate readiness
  const requiredServices = SERVICES.filter(s => s.required);
  const requiredReady = requiredServices.every(s => serviceStatus[s.id] === 'success');
  const allServicesChecked = Object.keys(serviceStatus).length >= SERVICES.length;
  const isReady = requiredReady && allServicesChecked;
  const canForceStart = checkCount >= 5;

  const successCount = Object.values(serviceStatus).filter(s => s === 'success').length;
  const progress = Math.round((successCount / SERVICES.length) * 100);

  const handleGetStarted = () => {
    if (dontShowAgain) {
      localStorage.setItem('tradecommand_skip_startup', 'true');
    }
    mountedRef.current = false;
    if (wsRef.current) wsRef.current.close();
    setVisible(false);
    onComplete?.();
  };

  const handleRetry = () => {
    statusRef.current = {};
    setServiceStatus({});
    setCheckCount(0);
    setCheckMode(null);
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'loading':
      case undefined:
      case 'timeout':
        return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
      case 'warning':
        return <AlertCircle className="w-4 h-4 text-yellow-400" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Loader2 className="w-4 h-4 text-zinc-500 animate-spin" />;
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'success': return 'Ready';
      case 'loading': return 'Connecting...';
      case 'warning': return 'Limited';
      case 'error': return 'Offline';
      case 'timeout': return 'Starting...';
      default: return 'Waiting...';
    }
  };

  if (!visible) return null;

  const servicesByCategory = {};
  SERVICES.forEach(service => {
    if (!servicesByCategory[service.category]) {
      servicesByCategory[service.category] = [];
    }
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
                    {isReady
                      ? 'All systems ready!'
                      : checkMode === 'fast'
                        ? 'Verifying services...'
                        : 'Waiting for services to start...'}
                  </p>
                </div>
              </div>
              
              <div className="text-right">
                <div className={`text-2xl font-bold ${isReady ? 'text-green-400' : 'text-cyan-400'}`}>
                  {progress}%
                </div>
                <div className="text-[10px] text-zinc-500">
                  {successCount}/{SERVICES.length} services
                </div>
              </div>
            </div>
            
            <div className="mt-3 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <motion.div
                className={`h-full ${isReady ? 'bg-green-500' : 'bg-gradient-to-r from-cyan-500 to-purple-500'}`}
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
              const categoryStarting = services.some(s => serviceStatus[s.id] === 'timeout');
              
              return (
                <div
                  key={categoryId}
                  className={`rounded-lg border p-3 transition-all ${
                    categoryReady 
                      ? 'bg-green-500/10 border-green-500/30' 
                      : categoryHasError
                        ? 'bg-red-500/10 border-red-500/30'
                        : categoryStarting
                          ? 'bg-amber-500/5 border-amber-500/20'
                          : 'bg-zinc-800/50 border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-xs font-semibold ${
                      categoryReady ? 'text-green-400' : 'text-white'
                    }`}>
                      {category.label}
                      {category.required && <span className="text-red-400 ml-1">*</span>}
                    </span>
                    {categoryReady && (
                      <span className="text-[10px] text-green-400 px-1.5 py-0.5 bg-green-500/20 rounded">
                        READY
                      </span>
                    )}
                  </div>
                  
                  <div className="space-y-1.5">
                    {services.map((service) => {
                      const status = serviceStatus[service.id];
                      const Icon = service.icon;
                      
                      return (
                        <div
                          key={service.id}
                          className="flex items-center justify-between"
                          data-testid={`startup-service-${service.id}`}
                        >
                          <div className="flex items-center gap-2">
                            <Icon className={`w-3.5 h-3.5 ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'timeout' ? 'text-amber-400' :
                              'text-zinc-500'
                            }`} />
                            <span className={`text-sm ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'timeout' ? 'text-amber-400' :
                              'text-zinc-400'
                            }`}>
                              {service.label}
                              {service.required && <span className="text-red-400 ml-0.5 text-[10px]">*</span>}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[10px] ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
                              status === 'timeout' ? 'text-amber-400' :
                              'text-zinc-500'
                            }`}>
                              {getStatusText(status)}
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
            <div className="flex items-center justify-center gap-4 text-[10px] text-zinc-500">
              <span><span className="text-red-400">*</span> Required for startup</span>
              <span>•</span>
              <span>Check #{checkCount}</span>
              {checkMode === 'fast' && <span className="text-cyan-400">FAST</span>}
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
                  Waiting for services...
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
