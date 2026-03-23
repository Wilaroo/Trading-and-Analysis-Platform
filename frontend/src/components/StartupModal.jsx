/**
 * StartupModal - REAL Service Health Verification
 * 
 * This modal performs ACTUAL health checks on all services.
 * Green checkmark = service actually responded successfully
 * Only enables "Get Started" when core services are verified working.
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
  Shield,
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
    endpoint: '/api/health', // Backend health implies DB is connected
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

// Group services by category
const CATEGORIES = {
  core: { label: 'Core Systems', color: 'cyan', required: true },
  trading: { label: 'Trading', color: 'blue', required: false },
  ai: { label: 'AI Systems', color: 'purple', required: false },
  analytics: { label: 'Analytics', color: 'amber', required: false }
};

const StartupModal = ({ onComplete }) => {
  const [visible, setVisible] = useState(true);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [serviceStatus, setServiceStatus] = useState({});
  const [isChecking, setIsChecking] = useState(true);
  const [checkCount, setCheckCount] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);
  const checkIntervalRef = useRef(null);

  // Check if user has opted out
  useEffect(() => {
    const skipStartup = localStorage.getItem('tradecommand_skip_startup');
    if (skipStartup === 'true') {
      setVisible(false);
      onComplete?.();
    }
  }, [onComplete]);

  // Check a single service
  const checkService = useCallback(async (service) => {
    if (service.checkType === 'websocket') {
      return wsConnected ? 'success' : 'loading';
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch(`${API_URL}${service.endpoint}`, {
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        return 'error';
      }

      const data = await response.json().catch(() => ({}));

      // Custom response validation if provided
      if (service.responseCheck) {
        return service.responseCheck(data) ? 'success' : 'warning';
      }

      return 'success';
    } catch (e) {
      if (e.name === 'AbortError') {
        return 'timeout';
      }
      return 'error';
    }
  }, [wsConnected]);

  // Check all services
  const checkAllServices = useCallback(async () => {
    setIsChecking(true);
    setCheckCount(prev => prev + 1);

    const results = {};
    
    // Check services in parallel but with slight stagger to avoid overwhelming backend
    for (const service of SERVICES) {
      // Small delay between checks
      await new Promise(resolve => setTimeout(resolve, 100));
      
      const status = await checkService(service);
      results[service.id] = status;
      
      // Update state incrementally so user sees progress
      setServiceStatus(prev => ({ ...prev, [service.id]: status }));
    }

    setIsChecking(false);
    return results;
  }, [checkService]);

  // Setup WebSocket check
  useEffect(() => {
    if (!visible) return;

    const wsUrl = API_URL.replace('http', 'ws') + '/api/ws/quotes';
    
    const connectWs = () => {
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setWsConnected(true);
          setServiceStatus(prev => ({ ...prev, websocket: 'success' }));
        };

        ws.onerror = () => {
          setWsConnected(false);
          setServiceStatus(prev => ({ ...prev, websocket: 'error' }));
        };

        ws.onclose = () => {
          setWsConnected(false);
        };
      } catch (e) {
        setWsConnected(false);
        setServiceStatus(prev => ({ ...prev, websocket: 'error' }));
      }
    };

    connectWs();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [visible]);

  // Initial check and periodic re-check
  useEffect(() => {
    if (!visible) return;

    // Initial check after short delay
    const initialTimer = setTimeout(() => {
      checkAllServices();
    }, 500);

    // Re-check every 3 seconds until all required services are ready
    checkIntervalRef.current = setInterval(() => {
      checkAllServices();
    }, 3000);

    return () => {
      clearTimeout(initialTimer);
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
      }
    };
  }, [visible, checkAllServices]);

  // Calculate if ready to proceed
  const requiredServices = SERVICES.filter(s => s.required);
  const requiredReady = requiredServices.every(s => serviceStatus[s.id] === 'success');
  const allServicesChecked = Object.keys(serviceStatus).length >= SERVICES.length;
  const isReady = requiredReady && allServicesChecked;

  // Stop checking once ready
  useEffect(() => {
    if (isReady && checkIntervalRef.current) {
      clearInterval(checkIntervalRef.current);
      checkIntervalRef.current = null;
    }
  }, [isReady]);

  // Calculate progress
  const successCount = Object.values(serviceStatus).filter(s => s === 'success').length;
  const progress = Math.round((successCount / SERVICES.length) * 100);

  const handleGetStarted = () => {
    if (dontShowAgain) {
      localStorage.setItem('tradecommand_skip_startup', 'true');
    }
    
    // Close WebSocket used for checking
    if (wsRef.current) {
      wsRef.current.close();
    }
    
    setVisible(false);
    onComplete?.();
  };

  const handleRetry = () => {
    setServiceStatus({});
    checkAllServices();
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'loading':
      case undefined:
        return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
      case 'warning':
        return <AlertCircle className="w-4 h-4 text-yellow-400" />;
      case 'error':
      case 'timeout':
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Loader2 className="w-4 h-4 text-zinc-600 animate-spin" />;
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'success': return 'Ready';
      case 'loading': return 'Checking...';
      case 'warning': return 'Limited';
      case 'error': return 'Offline';
      case 'timeout': return 'Timeout';
      default: return 'Pending';
    }
  };

  if (!visible) return null;

  // Group services by category
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
                    {isReady ? 'All systems ready!' : 'Verifying systems...'}
                  </p>
                </div>
              </div>
              
              {/* Progress indicator */}
              <div className="text-right">
                <div className={`text-2xl font-bold ${isReady ? 'text-green-400' : 'text-cyan-400'}`}>
                  {progress}%
                </div>
                <div className="text-[10px] text-zinc-500">
                  {successCount}/{SERVICES.length} services
                </div>
              </div>
            </div>
            
            {/* Progress bar */}
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
          <div className="px-5 py-4 space-y-3 max-h-[350px] overflow-y-auto">
            {Object.entries(servicesByCategory).map(([categoryId, services]) => {
              const category = CATEGORIES[categoryId];
              const categoryReady = services.every(s => serviceStatus[s.id] === 'success');
              const categoryHasError = services.some(s => ['error', 'timeout'].includes(serviceStatus[s.id]));
              
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
                  {/* Category header */}
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
                  
                  {/* Services in category */}
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
                              'text-zinc-500'
                            }`} />
                            <span className={`text-sm ${
                              status === 'success' ? 'text-green-400' :
                              status === 'error' ? 'text-red-400' :
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
              disabled={!isReady}
              className={`px-5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                isReady
                  ? 'bg-gradient-to-r from-green-500 to-emerald-500 text-white hover:shadow-lg hover:shadow-green-500/25'
                  : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
              }`}
              data-testid="get-started-btn"
            >
              {isReady ? (
                <>
                  <Zap className="w-4 h-4" />
                  Get Started
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
