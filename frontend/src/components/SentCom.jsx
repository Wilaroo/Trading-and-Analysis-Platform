/**
 * SentCom.jsx - Sentient Command
 * 
 * Production component for the unified AI command center.
 * Wired to real /api/sentcom/* endpoints.
 * Uses "we" voice throughout for team partnership feeling.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Brain, Clock, Zap, Target, AlertCircle, ArrowRight, 
  CheckCircle, Loader, X, TrendingUp, Activity, ChevronUp, 
  ChevronDown, DollarSign, Gauge, Wifi, Eye, Crosshair,
  MessageSquare, RefreshCw, Bell, Circle, Flame, Radio
} from 'lucide-react';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

const Sparkline = ({ data = [], color = 'cyan', height = 24 }) => {
  if (!data || data.length < 2) return null;
  
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  
  const points = data.map((val, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = 100 - ((val - min) / range) * 100;
    return `${x},${y}`;
  }).join(' ');
  
  const strokeColor = color === 'emerald' ? '#10b981' : color === 'rose' ? '#f43f5e' : '#06b6d4';
  
  return (
    <svg viewBox="0 0 100 100" className={`w-full h-${height}`} preserveAspectRatio="none">
      <polyline
        points={points}
        fill="none"
        stroke={strokeColor}
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

const GlassCard = ({ children, className = '', gradient = false, glow = false }) => (
  <div className={`
    relative overflow-hidden rounded-2xl
    bg-gradient-to-br from-white/[0.08] to-white/[0.02]
    border border-white/10
    backdrop-blur-xl
    ${glow ? 'shadow-lg shadow-cyan-500/10' : ''}
    ${className}
  `}>
    {gradient && (
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-violet-500/5 pointer-events-none" />
    )}
    <div className="relative">{children}</div>
  </div>
);

const PulsingDot = ({ color = 'emerald' }) => (
  <span className="relative flex h-2 w-2">
    <span className={`animate-ping absolute inline-flex h-full w-full rounded-full bg-${color}-400 opacity-75`}></span>
    <span className={`relative inline-flex rounded-full h-2 w-2 bg-${color}-500`}></span>
  </span>
);

// ============================================================================
// HOOKS
// ============================================================================

const useSentComStatus = (pollInterval = 5000) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/status`);
      const data = await res.json();
      if (data.success) {
        setStatus(data.status);
      }
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { status, loading, error, refresh: fetchStatus };
};

const useSentComStream = (pollInterval = 3000) => {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchStream = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/stream?limit=20`);
      const data = await res.json();
      if (data.success) {
        setMessages(data.messages || []);
      }
    } catch (err) {
      console.error('Error fetching stream:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStream();
    const interval = setInterval(fetchStream, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStream, pollInterval]);

  return { messages, loading, refresh: fetchStream };
};

const useSentComPositions = (pollInterval = 5000) => {
  const [positions, setPositions] = useState([]);
  const [totalPnl, setTotalPnl] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/positions`);
      const data = await res.json();
      if (data.success) {
        setPositions(data.positions || []);
        setTotalPnl(data.total_pnl || 0);
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval]);

  return { positions, totalPnl, loading, refresh: fetchPositions };
};

const useSentComSetups = (pollInterval = 10000) => {
  const [setups, setSetups] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchSetups = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/setups`);
      const data = await res.json();
      if (data.success) {
        setSetups(data.setups || []);
      }
    } catch (err) {
      console.error('Error fetching setups:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSetups();
    const interval = setInterval(fetchSetups, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSetups, pollInterval]);

  return { setups, loading, refresh: fetchSetups };
};

const useSentComContext = (pollInterval = 30000) => {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchContext = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/context`);
      const data = await res.json();
      if (data.success) {
        setContext(data.context);
      }
    } catch (err) {
      console.error('Error fetching context:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchContext();
    const interval = setInterval(fetchContext, pollInterval);
    return () => clearInterval(interval);
  }, [fetchContext, pollInterval]);

  return { context, loading, refresh: fetchContext };
};

const useSentComAlerts = (pollInterval = 5000) => {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/alerts?limit=5`);
      const data = await res.json();
      if (data.success) {
        setAlerts(data.alerts || []);
      }
    } catch (err) {
      console.error('Error fetching alerts:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, pollInterval);
    return () => clearInterval(interval);
  }, [fetchAlerts, pollInterval]);

  return { alerts, loading, refresh: fetchAlerts };
};

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

const OrderPipeline = ({ status }) => {
  const pipeline = status?.order_pipeline || { pending: 0, executing: 0, filled: 0 };
  
  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-black/40 border border-white/5">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <Clock className="w-4 h-4 text-amber-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-amber-400">{pipeline.pending}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Pending</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
          <Zap className="w-4 h-4 text-cyan-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-cyan-400">{pipeline.executing}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Executing</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-emerald-400">{pipeline.filled}</p>
          <p className="text-[9px] text-zinc-500 uppercase">Filled</p>
        </div>
      </div>
    </div>
  );
};

const StatusHeader = ({ status, context }) => {
  const connected = status?.connected || false;
  const state = status?.state || 'offline';
  const regime = context?.regime || status?.regime || 'UNKNOWN';
  
  return (
    <div className="flex items-center justify-between p-4 border-b border-white/5">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Brain className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">SENTCOM</h1>
          <div className="flex items-center gap-3 mt-1">
            <div className="flex items-center gap-1.5">
              {connected ? (
                <PulsingDot color="emerald" />
              ) : (
                <Circle className="w-2 h-2 text-zinc-500" />
              )}
              <span className={`text-xs font-medium ${connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {connected ? 'CONNECTED' : 'OFFLINE'}
              </span>
            </div>
            {regime !== 'UNKNOWN' && (
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {regime}
              </span>
            )}
          </div>
        </div>
      </div>
      
      <OrderPipeline status={status} />
    </div>
  );
};

const PositionsPanel = ({ positions, totalPnl, loading, onSelectPosition }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-32">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <DollarSign className="w-3 h-3 text-emerald-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Our Positions</span>
        </div>
        <span className={`text-lg font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
        </span>
      </div>
      
      {positions.length === 0 ? (
        <div className="text-center py-8">
          <Eye className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
          <p className="text-sm text-zinc-500">No open positions</p>
          <p className="text-xs text-zinc-600 mt-1">We're scanning for setups...</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos, i) => (
            <div 
              key={pos.symbol || i}
              onClick={() => onSelectPosition?.(pos)}
              className="flex items-center justify-between p-3 rounded-xl bg-black/30 border border-white/5 hover:border-cyan-500/30 cursor-pointer transition-all"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-white">{pos.symbol}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  pos.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' :
                  pos.status === 'watching' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-cyan-500/20 text-cyan-400'
                }`}>
                  {pos.status || 'open'}
                </span>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="w-16 h-6">
                  <Sparkline 
                    data={pos.sparkline_data || [50, 52, 48, 55, 53, 58, 56, 60]} 
                    color={pos.pnl >= 0 ? 'emerald' : 'rose'} 
                  />
                </div>
                <span className={`text-sm font-bold ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) || '$0'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const StreamPanel = ({ messages, loading }) => {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [messages]);

  if (loading && messages.length === 0) {
    return (
      <GlassCard className="p-4 h-full">
        <div className="flex items-center justify-center h-full">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  const getMessageIcon = (type, actionType) => {
    if (type === 'thought' || actionType === 'scanning') return <Brain className="w-4 h-4 text-violet-400" />;
    if (type === 'alert') return <AlertCircle className="w-4 h-4 text-amber-400" />;
    if (type === 'filter') return <Target className="w-4 h-4 text-cyan-400" />;
    if (actionType === 'monitoring') return <Activity className="w-4 h-4 text-emerald-400" />;
    return <Radio className="w-4 h-4 text-zinc-400" />;
  };

  const getMessageLabel = (type, actionType) => {
    if (actionType === 'scanning') return 'SCANNER';
    if (actionType === 'monitoring') return 'MONITOR';
    if (type === 'filter') return 'FILTER';
    if (type === 'alert') return 'ALERT';
    if (type === 'chat') return 'CHAT';
    return 'SENTCOM';
  };

  return (
    <GlassCard gradient className="p-4 h-full flex flex-col">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Flame className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Live Stream</span>
      </div>
      
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
        {messages.length === 0 ? (
          <div className="text-center py-8">
            <Radio className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
            <p className="text-sm text-zinc-500">Waiting for activity...</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <motion.div
              key={msg.id || i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="relative"
            >
              <div className="flex items-start gap-3 p-3 rounded-xl bg-black/30 border border-white/5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500/30 to-purple-600/30 flex items-center justify-center flex-shrink-0">
                  {getMessageIcon(msg.type, msg.action_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-medium text-violet-400 uppercase">
                      {getMessageLabel(msg.type, msg.action_type)}
                    </span>
                    {msg.symbol && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-400">
                        {msg.symbol}
                      </span>
                    )}
                    <span className="text-[10px] text-zinc-600">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
                  {msg.confidence && (
                    <div className="flex items-center gap-1 mt-2">
                      <Gauge className="w-3 h-3 text-violet-400" />
                      <span className="text-[10px] text-violet-400">Confidence: {msg.confidence}%</span>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          ))
        )}
      </div>
    </GlassCard>
  );
};

const ContextPanel = ({ context, loading }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center">
          <Wifi className="w-3 h-3 text-cyan-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Market Context</span>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Regime</span>
          <span className={`text-xs font-bold ${
            context?.regime === 'RISK_ON' ? 'text-emerald-400' :
            context?.regime === 'RISK_OFF' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.regime || 'UNKNOWN'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">SPY Trend</span>
          <span className={`text-xs font-bold ${
            context?.spy_trend === 'Bullish' ? 'text-emerald-400' :
            context?.spy_trend === 'Bearish' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.spy_trend || '--'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">VIX</span>
          <span className="text-xs font-bold text-zinc-300">{context?.vix || '--'}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Market</span>
          <span className={`text-xs font-bold ${context?.market_open ? 'text-emerald-400' : 'text-zinc-500'}`}>
            {context?.market_open ? 'OPEN' : 'CLOSED'}
          </span>
        </div>
      </div>
    </GlassCard>
  );
};

const AlertsPanel = ({ alerts, loading }) => {
  if (loading && alerts.length === 0) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-amber-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Bell className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Recent Alerts</span>
        </div>
        {alerts.length > 0 && (
          <span className="text-xs text-amber-400">{alerts.length} new</span>
        )}
      </div>
      
      {alerts.length === 0 ? (
        <p className="text-xs text-zinc-500 text-center py-4">No alerts</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert, i) => (
            <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-black/20">
              <AlertCircle className={`w-3 h-3 ${
                alert.type === 'warning' ? 'text-amber-400' :
                alert.type === 'info' ? 'text-cyan-400' :
                'text-zinc-400'
              }`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-zinc-300 truncate">{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const SetupsPanel = ({ setups, loading }) => {
  if (loading && setups.length === 0) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Crosshair className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Setups We're Watching</span>
      </div>
      
      {setups.length === 0 ? (
        <div className="text-center py-4">
          <Crosshair className="w-6 h-6 text-zinc-600 mx-auto mb-2" />
          <p className="text-xs text-zinc-500">No setups currently</p>
        </div>
      ) : (
        <div className="space-y-2">
          {setups.map((setup, i) => (
            <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-black/20">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-white">{setup.symbol}</span>
                <span className="text-[10px] text-zinc-500">{setup.setup_type}</span>
              </div>
              {setup.trigger_price && (
                <span className="text-xs text-cyan-400">${setup.trigger_price?.toFixed(2)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};

const ChatInput = ({ onSend, disabled }) => {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim() || sending) return;
    
    setSending(true);
    await onSend?.(message);
    setMessage('');
    setSending(false);
  };

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-white/5">
      <div className="flex gap-2">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask SentCom anything..."
          disabled={disabled || sending}
          className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
        />
        <button
          type="submit"
          disabled={!message.trim() || sending || disabled}
          className="px-4 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
        >
          {sending ? <Loader className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
        </button>
      </div>
    </form>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const SentCom = ({ compact = false }) => {
  const { status, loading: statusLoading } = useSentComStatus();
  const { messages, loading: streamLoading, refresh: refreshStream } = useSentComStream();
  const { positions, totalPnl, loading: positionsLoading } = useSentComPositions();
  const { setups, loading: setupsLoading } = useSentComSetups();
  const { context, loading: contextLoading } = useSentComContext();
  const { alerts, loading: alertsLoading } = useSentComAlerts();
  
  const [selectedPosition, setSelectedPosition] = useState(null);

  const handleChat = async (message) => {
    try {
      const res = await fetch(`${API_BASE}/api/sentcom/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
      });
      const data = await res.json();
      // Refresh stream to show new message
      setTimeout(refreshStream, 500);
      return data;
    } catch (err) {
      console.error('Chat error:', err);
    }
  };

  if (compact) {
    // Compact version for embedding in Command Center dashboard
    // Replaces BotBrainPanel + AI Assistant with unified SentCom
    return (
      <div className="bg-zinc-900/50 backdrop-blur-xl rounded-2xl border border-white/10 overflow-hidden" data-testid="sentcom-compact">
        {/* Compact Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Brain className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">SENTCOM</h2>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {status?.connected ? (
                    <PulsingDot color="emerald" />
                  ) : (
                    <Circle className="w-2 h-2 text-zinc-500" />
                  )}
                  <span className={`text-[10px] font-medium ${status?.connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                    {status?.connected ? 'CONNECTED' : 'OFFLINE'}
                  </span>
                </div>
                {context?.regime && context.regime !== 'UNKNOWN' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                    context.regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                    context.regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                    'bg-zinc-500/20 text-zinc-400'
                  }`}>
                    {context.regime}
                  </span>
                )}
              </div>
            </div>
          </div>
          
          {/* Compact Order Pipeline */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/30">
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-amber-400" />
              <span className="text-sm font-bold text-amber-400">{status?.order_pipeline?.pending || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-cyan-400" />
              <span className="text-sm font-bold text-cyan-400">{status?.order_pipeline?.executing || 0}</span>
            </div>
            <ArrowRight className="w-3 h-3 text-zinc-600" />
            <div className="flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-emerald-400" />
              <span className="text-sm font-bold text-emerald-400">{status?.order_pipeline?.filled || 0}</span>
            </div>
          </div>
        </div>

        {/* Thought Label */}
        <div className="px-4 pt-3 pb-1">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">What we're thinking right now</p>
        </div>
        
        {/* Live Stream - compact height */}
        <div className="h-[280px] overflow-hidden">
          <StreamPanel messages={messages} loading={streamLoading} />
        </div>
        
        {/* Chat Input */}
        <ChatInput onSend={handleChat} disabled={!status?.connected} />
      </div>
    );
  }

  // Full page version
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-7xl mx-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <GlassCard gradient glow className="p-0">
            <StatusHeader status={status} context={context} />
          </GlassCard>
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left Column - Positions & Setups */}
          <div className="col-span-3 space-y-6">
            <PositionsPanel 
              positions={positions} 
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={setSelectedPosition}
            />
            <SetupsPanel setups={setups} loading={setupsLoading} />
          </div>

          {/* Center - Live Stream */}
          <div className="col-span-6">
            <div className="h-[600px] flex flex-col">
              <StreamPanel messages={messages} loading={streamLoading} />
              <ChatInput onSend={handleChat} disabled={!status?.connected} />
            </div>
          </div>

          {/* Right Column - Context & Alerts */}
          <div className="col-span-3 space-y-6">
            <ContextPanel context={context} loading={contextLoading} />
            <AlertsPanel alerts={alerts} loading={alertsLoading} />
          </div>
        </div>
      </div>

      {/* Position Detail Modal */}
      <AnimatePresence>
        {selectedPosition && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-8"
            onClick={() => setSelectedPosition(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-2xl"
              onClick={e => e.stopPropagation()}
            >
              <GlassCard glow className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-2xl font-bold text-white">Our {selectedPosition.symbol} Position</h2>
                    <p className="text-sm text-zinc-400">Entry: ${selectedPosition.entry_price?.toFixed(2)}</p>
                  </div>
                  <button
                    onClick={() => setSelectedPosition(null)}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-4 mb-6">
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">P&L</p>
                    <p className={`text-xl font-bold ${selectedPosition.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {selectedPosition.pnl >= 0 ? '+' : ''}{selectedPosition.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Stop</p>
                    <p className="text-xl font-bold text-rose-400">
                      ${selectedPosition.stop_price?.toFixed(2) || '--'}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-black/30 text-center">
                    <p className="text-xs text-zinc-500 mb-1">Target</p>
                    <p className="text-xl font-bold text-emerald-400">
                      ${selectedPosition.target_prices?.[0]?.toFixed(2) || '--'}
                    </p>
                  </div>
                </div>

                <p className="text-sm text-zinc-400">
                  Shares: {selectedPosition.shares} • 
                  Entry: ${selectedPosition.entry_price?.toFixed(2)} • 
                  Current: ${selectedPosition.current_price?.toFixed(2)}
                </p>
              </GlassCard>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SentCom;
