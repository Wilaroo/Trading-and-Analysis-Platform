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
  Upload,
  Copy,
  Terminal,
  RefreshCw,
  ExternalLink
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Feature explanations for the app - detailed with what makes each special
const FEATURES = [
  {
    icon: Bot,
    title: "AI Trading Assistant",
    description: "Your personal market analyst powered by local Ollama AI.",
    details: "Unlike cloud-only AI, your data stays private. The assistant understands 30+ trading strategies, analyzes your portfolio in real-time, and provides actionable insights—not generic advice.",
    highlight: "Privacy-first AI"
  },
  {
    icon: LineChart,
    title: "Real-Time Charts",
    description: "Professional TradingView charts with auto-detected levels.",
    details: "Support/resistance levels are calculated using multiple algorithms (pivot points, volume profile, price action). The chart automatically highlights key zones where price is likely to react.",
    highlight: "Auto S/R detection"
  },
  {
    icon: Eye,
    title: "Smart Watchlist",
    description: "Self-curating watchlist that learns your trading style.",
    details: "Not just a list of tickers—it tracks momentum, relative strength, and upcoming catalysts. Stocks are auto-added when scanner alerts fire and auto-removed after 7 days of inactivity.",
    highlight: "Auto-curated"
  },
  {
    icon: Zap,
    title: "Live Scanner",
    description: "Real-time pattern detection across 1,000+ stocks.",
    details: "Scans for breakouts, squeezes, VWAP plays, gap fills, and more. Each alert includes entry/exit zones, risk/reward ratios, and historical win rates for that specific pattern.",
    highlight: "30+ strategies"
  },
  {
    icon: Target,
    title: "Trade Pipeline",
    description: "From idea to execution with full accountability.",
    details: "Every trade flows through stages: Discovery → Research → Planning → Execution → Review. Built-in journaling captures your reasoning, so you learn from both wins and losses.",
    highlight: "Built-in journaling"
  },
  {
    icon: Shield,
    title: "AI Validation Engine",
    description: "Every AI response is fact-checked against live data.",
    details: "The validation layer catches hallucinations before you see them. If the AI says 'NVDA is up 5%' but it's actually down, the system auto-corrects or flags the discrepancy. You see the confidence score on each message.",
    highlight: "Anti-hallucination"
  }
];

// Startup processes to track
const STARTUP_PROCESSES = [
  { id: 'backend', label: 'Connecting to backend...', successLabel: 'Backend connected' },
  { id: 'alpaca', label: 'Connecting to Alpaca for real-time data...', successLabel: 'Alpaca connected' },
  { id: 'ollama', label: 'Connecting to AI Trading Assistant...', successLabel: 'AI Assistant ready' },
  { id: 'ibpusher', label: 'Checking IB Gateway connection...', successLabel: 'IB Gateway data available' },
  { id: 'market', label: 'Fetching market status...', successLabel: 'Market data loaded' },
  { id: 'portfolio', label: 'Loading portfolio...', successLabel: 'Portfolio loaded' },
  { id: 'watchlist', label: 'Loading smart watchlist...', successLabel: 'Watchlist ready' }
];

const StartupModal = ({ onComplete, ibPusherStatus, checkIbConnection }) => {
  const [visible, setVisible] = useState(true);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [processes, setProcesses] = useState(
    STARTUP_PROCESSES.reduce((acc, p) => ({ ...acc, [p.id]: 'pending' }), {})
  );
  const [allReady, setAllReady] = useState(false);
  const [error, setError] = useState(null);
  const [ibSetupData, setIbSetupData] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [ibChecking, setIbChecking] = useState(false);

  // Check if user has opted out
  useEffect(() => {
    const skipStartup = localStorage.getItem('tradecommand_skip_startup');
    if (skipStartup === 'true') {
      setVisible(false);
      onComplete?.();
    }
  }, [onComplete]);

  // Run startup checks
  const runStartupChecks = useCallback(async () => {
    // Fetch IB pusher setup info
    try {
      const setupRes = await fetch(`${API_URL}/api/ib/pusher-setup`);
      if (setupRes.ok) {
        const setupData = await setupRes.json();
        setIbSetupData(setupData);
      }
    } catch { /* non-blocking */ }

    // Check backend with proper timeout
    setProcesses(prev => ({ ...prev, backend: 'loading' }));
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      const res = await fetch(`${API_URL}/api/health`, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        setProcesses(prev => ({ ...prev, backend: 'success' }));
      } else {
        throw new Error('Backend not responding');
      }
    } catch (e) {
      setProcesses(prev => ({ ...prev, backend: e.name === 'AbortError' ? 'warning' : 'error' }));
      if (e.name !== 'AbortError') {
        setError('Unable to connect to backend');
      }
    }

    // Check Alpaca (parallel with others)
    setProcesses(prev => ({ ...prev, alpaca: 'loading' }));
    fetch(`${API_URL}/api/alpaca/status`)
      .then(res => res.json())
      .then(data => {
        setProcesses(prev => ({ ...prev, alpaca: data.success ? 'success' : 'warning' }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, alpaca: 'warning' }));
      });

    // Check Ollama/AI
    setProcesses(prev => ({ ...prev, ollama: 'loading' }));
    fetch(`${API_URL}/api/assistant/check-ollama`)
      .then(res => res.json())
      .then(data => {
        setProcesses(prev => ({ 
          ...prev, 
          ollama: data.available || data.ollama_available ? 'success' : 'warning' 
        }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, ollama: 'warning' }));
      });

    // Check IB Gateway via Pusher
    setProcesses(prev => ({ ...prev, ibpusher: 'loading' }));
    fetch(`${API_URL}/api/ib/pushed-data`)
      .then(res => res.json())
      .then(data => {
        // Check if pusher is connected and has recent data
        const isConnected = data.connected === true;
        const hasPositions = data.positions && data.positions.length > 0;
        setProcesses(prev => ({ 
          ...prev, 
          ibpusher: isConnected || hasPositions ? 'success' : 'warning' 
        }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, ibpusher: 'warning' }));
      });

    // Fetch market status
    setProcesses(prev => ({ ...prev, market: 'loading' }));
    fetch(`${API_URL}/api/market-intel/early-morning-report`)
      .then(res => res.json())
      .then(() => {
        setProcesses(prev => ({ ...prev, market: 'success' }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, market: 'warning' }));
      });

    // Load portfolio
    setProcesses(prev => ({ ...prev, portfolio: 'loading' }));
    fetch(`${API_URL}/api/portfolio`)
      .then(res => res.json())
      .then(() => {
        setProcesses(prev => ({ ...prev, portfolio: 'success' }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, portfolio: 'warning' }));
      });

    // Load watchlist
    setProcesses(prev => ({ ...prev, watchlist: 'loading' }));
    fetch(`${API_URL}/api/smart-watchlist`)
      .then(res => res.json())
      .then(() => {
        setProcesses(prev => ({ ...prev, watchlist: 'success' }));
      })
      .catch(() => {
        setProcesses(prev => ({ ...prev, watchlist: 'warning' }));
      });
  }, []);

  useEffect(() => {
    if (visible) {
      runStartupChecks();
      // Fallback: Enable button after 10 seconds even if some checks haven't completed
      const fallbackTimer = setTimeout(() => {
        setAllReady(true);
      }, 10000);
      return () => clearTimeout(fallbackTimer);
    }
  }, [visible, runStartupChecks]);

  // Check if all processes are done
  useEffect(() => {
    const statuses = Object.values(processes);
    const allDone = statuses.every(s => s !== 'pending' && s !== 'loading');
    const hasSuccess = statuses.some(s => s === 'success');
    
    if (allDone && hasSuccess) {
      setTimeout(() => setAllReady(true), 500);
    }
  }, [processes]);

  const handleCopy = (text, field) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    });
  };

  const handleRecheckIB = async () => {
    setIbChecking(true);
    setProcesses(prev => ({ ...prev, ibpusher: 'loading' }));
    try {
      if (checkIbConnection) await checkIbConnection();
      const res = await fetch(`${API_URL}/api/ib/pushed-data`);
      const data = await res.json();
      const isConnected = data.connected === true;
      setProcesses(prev => ({ ...prev, ibpusher: isConnected ? 'success' : 'warning' }));
      // Refresh setup data too
      const setupRes = await fetch(`${API_URL}/api/ib/pusher-setup`);
      if (setupRes.ok) setIbSetupData(await setupRes.json());
    } catch {
      setProcesses(prev => ({ ...prev, ibpusher: 'warning' }));
    } finally {
      setIbChecking(false);
    }
  };

  const handleGetStarted = () => {
    if (dontShowAgain) {
      localStorage.setItem('tradecommand_skip_startup', 'true');
    }
    setVisible(false);
    onComplete?.();
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'loading':
        return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-400" />;
      case 'warning':
        return <CheckCircle2 className="w-4 h-4 text-yellow-400" />;
      default:
        return <div className="w-4 h-4 rounded-full bg-zinc-600" />;
    }
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
          className="relative w-full max-w-3xl mx-4 bg-zinc-900 rounded-2xl border border-zinc-700 shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="relative px-8 pt-8 pb-6 bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border-b border-zinc-700">
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-xl bg-gradient-to-br from-cyan-500 to-purple-500">
                <Rocket className="w-8 h-8 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">Welcome to TradeCommand</h1>
                <p className="text-zinc-400 text-sm mt-1">Your AI-powered trading intelligence hub</p>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="px-8 py-6 max-h-[60vh] overflow-y-auto">
            {/* Features Grid */}
            <div className="mb-8">
              <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide mb-4">
                Key Features
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {FEATURES.map((feature, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700/50 hover:border-cyan-500/30 transition-all hover:bg-zinc-800/80 group"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <feature.icon className="w-5 h-5 text-cyan-400" />
                      {feature.highlight && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-400 font-medium">
                          {feature.highlight}
                        </span>
                      )}
                    </div>
                    <h3 className="text-sm font-semibold text-white mb-1">{feature.title}</h3>
                    <p className="text-xs text-zinc-400 leading-relaxed mb-2">{feature.description}</p>
                    <p className="text-[10px] text-zinc-500 leading-relaxed group-hover:text-zinc-400 transition-colors">
                      {feature.details}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Startup Status */}
            <div className="mb-6">
              <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide mb-4">
                System Status
              </h2>
              <div className="space-y-2 bg-zinc-800/30 rounded-lg p-4 border border-zinc-700/50">
                {STARTUP_PROCESSES.map((process) => {
                  const status = processes[process.id];
                  return (
                    <div
                      key={process.id}
                      className="flex items-center gap-3"
                      data-testid={`startup-process-${process.id}`}
                    >
                      {getStatusIcon(status)}
                      <span className={`text-sm ${
                        status === 'success' ? 'text-green-400' :
                        status === 'warning' ? 'text-yellow-400' :
                        status === 'error' ? 'text-red-400' :
                        status === 'loading' ? 'text-cyan-400' :
                        'text-zinc-500'
                      }`}>
                        {status === 'success' || status === 'warning' 
                          ? process.successLabel 
                          : process.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              {error && (
                <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                  <p className="text-sm text-red-400">{error}</p>
                </div>
              )}
            </div>

            {/* IB Data Pusher Setup */}
            <div data-testid="ib-setup-section">
              <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide mb-4 flex items-center gap-2">
                <Upload className="w-4 h-4" />
                IB Data Pusher Setup
              </h2>
              
              {/* Connection Status Banner */}
              <div className={`p-3 rounded-lg border mb-4 flex items-center justify-between ${
                ibPusherStatus?.connected || ibSetupData?.pusher_connected
                  ? 'bg-emerald-500/10 border-emerald-500/30'
                  : 'bg-amber-500/10 border-amber-500/30'
              }`}>
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full ${
                    ibPusherStatus?.connected || ibSetupData?.pusher_connected
                      ? 'bg-emerald-400 animate-pulse' 
                      : 'bg-amber-400'
                  }`} />
                  <div>
                    <p className={`text-sm font-medium ${
                      ibPusherStatus?.connected || ibSetupData?.pusher_connected
                        ? 'text-emerald-400' : 'text-amber-400'
                    }`}>
                      {ibPusherStatus?.connected || ibSetupData?.pusher_connected
                        ? `IB Data Pusher Connected`
                        : 'IB Data Pusher Not Connected'}
                    </p>
                    {(ibPusherStatus?.connected || ibSetupData?.pusher_connected) && (
                      <p className="text-[11px] text-zinc-400">
                        {ibSetupData?.positions_count || ibPusherStatus?.positions_count || 0} positions, {ibSetupData?.quotes_count || ibPusherStatus?.quotes_count || 0} quotes streaming
                      </p>
                    )}
                  </div>
                </div>
                <button
                  onClick={handleRecheckIB}
                  disabled={ibChecking}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-white/5 hover:bg-white/10 text-zinc-300 transition-colors disabled:opacity-50"
                  data-testid="ib-recheck-btn"
                >
                  <RefreshCw className={`w-3 h-3 ${ibChecking ? 'animate-spin' : ''}`} />
                  {ibChecking ? 'Checking...' : 'Re-check'}
                </button>
              </div>

              {/* Setup Instructions */}
              {!(ibPusherStatus?.connected || ibSetupData?.pusher_connected) && (
                <div className="space-y-3 bg-zinc-800/30 rounded-lg p-4 border border-zinc-700/50">
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    The IB Data Pusher is a lightweight script that runs on your local machine alongside IB Gateway/TWS. 
                    It pushes real-time positions, account data, and quotes to your cloud dashboard.
                  </p>

                  {/* Cloud URL */}
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Cloud URL (for script config)</label>
                    <div className="flex items-center gap-2 mt-1">
                      <code className="flex-1 text-xs bg-black/40 text-cyan-400 px-3 py-2 rounded font-mono border border-zinc-700/50 truncate" data-testid="ib-cloud-url">
                        {API_URL}
                      </code>
                      <button
                        onClick={() => handleCopy(API_URL, 'url')}
                        className="p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                        title="Copy URL"
                        data-testid="ib-copy-url"
                      >
                        {copiedField === 'url' 
                          ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          : <Copy className="w-3.5 h-3.5 text-zinc-400" />
                        }
                      </button>
                    </div>
                  </div>

                  {/* Quick Start Steps */}
                  <div>
                    <label className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Quick Start</label>
                    <div className="mt-1.5 space-y-1.5">
                      {[
                        { step: '1', text: 'Install deps:', cmd: 'pip install ib_insync aiohttp' },
                        { step: '2', text: 'Start IB Gateway or TWS (port 4002)' },
                        { step: '3', text: 'Set CLOUD_URL in ib_data_pusher.py' },
                        { step: '4', text: 'Run:', cmd: 'python ib_data_pusher.py' },
                      ].map((item) => (
                        <div key={item.step} className="flex items-start gap-2">
                          <span className="text-[10px] w-4 h-4 rounded bg-cyan-500/20 text-cyan-400 flex items-center justify-center flex-shrink-0 mt-0.5 font-bold">
                            {item.step}
                          </span>
                          <div className="flex-1 min-w-0">
                            <span className="text-xs text-zinc-300">{item.text}</span>
                            {item.cmd && (
                              <div className="flex items-center gap-1 mt-0.5">
                                <code className="text-[10px] bg-black/40 text-amber-400 px-2 py-0.5 rounded font-mono border border-zinc-700/50">
                                  {item.cmd}
                                </code>
                                <button
                                  onClick={() => handleCopy(item.cmd, `cmd-${item.step}`)}
                                  className="p-0.5 hover:bg-white/10 rounded transition-colors"
                                >
                                  {copiedField === `cmd-${item.step}`
                                    ? <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                                    : <Copy className="w-3 h-3 text-zinc-500" />
                                  }
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <p className="text-[10px] text-zinc-500 flex items-center gap-1">
                    <Terminal className="w-3 h-3" />
                    The script is in your project: <code className="text-cyan-400/80">documents/ib_data_pusher.py</code>
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-8 py-4 bg-zinc-800/50 border-t border-zinc-700 flex items-center justify-between">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={dontShowAgain}
                onChange={(e) => setDontShowAgain(e.target.checked)}
                className="w-4 h-4 rounded border-zinc-600 bg-zinc-700 text-cyan-500 focus:ring-cyan-500"
                data-testid="dont-show-again-checkbox"
              />
              <span className="text-sm text-zinc-400">Don't show this again</span>
            </label>

            <button
              onClick={handleGetStarted}
              disabled={!allReady && !error}
              className={`px-6 py-2.5 rounded-lg font-medium transition-all flex items-center gap-2 ${
                allReady || error
                  ? 'bg-gradient-to-r from-cyan-500 to-purple-500 text-white hover:shadow-lg hover:shadow-cyan-500/25'
                  : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
              }`}
              data-testid="get-started-btn"
            >
              {allReady || error ? (
                <>
                  <Zap className="w-4 h-4" />
                  Get Started
                </>
              ) : (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Starting up...
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
