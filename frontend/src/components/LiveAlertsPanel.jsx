/**
 * LiveAlertsPanel - Real-time trade alerts via SSE
 * Connects to the background scanner and displays live trading opportunities
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Radio, 
  X, 
  Bell, 
  BellOff, 
  Maximize2, 
  Minimize2,
  Target,
  TrendingUp,
  TrendingDown,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Play,
  Pause,
  ChevronRight,
  Info,
  Volume2,
  Settings,
  Zap
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

// Priority colors and icons
const PRIORITY_CONFIG = {
  critical: { 
    color: 'text-red-400', 
    bg: 'bg-red-500/20', 
    border: 'border-red-500/40',
    icon: AlertTriangle,
    label: 'CRITICAL'
  },
  high: { 
    color: 'text-orange-400', 
    bg: 'bg-orange-500/15', 
    border: 'border-orange-500/30',
    icon: Zap,
    label: 'HIGH'
  },
  medium: { 
    color: 'text-yellow-400', 
    bg: 'bg-yellow-500/10', 
    border: 'border-yellow-500/20',
    icon: Clock,
    label: 'MEDIUM'
  },
  low: { 
    color: 'text-zinc-400', 
    bg: 'bg-zinc-500/10', 
    border: 'border-zinc-500/20',
    icon: Info,
    label: 'LOW'
  }
};

// Direction config
const DIRECTION_CONFIG = {
  long: { icon: TrendingUp, color: 'text-emerald-400', label: 'LONG' },
  short: { icon: TrendingDown, color: 'text-red-400', label: 'SHORT' }
};

// Single Alert Card
const AlertCard = ({ alert, onDismiss, onSelect }) => {
  const priority = PRIORITY_CONFIG[alert.priority] || PRIORITY_CONFIG.medium;
  const direction = DIRECTION_CONFIG[alert.direction] || DIRECTION_CONFIG.long;
  const PriorityIcon = priority.icon;
  const DirectionIcon = direction.icon;
  
  const formatTime = (minutes) => {
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className={`p-3 rounded-lg ${priority.bg} border ${priority.border} mb-2 cursor-pointer hover:scale-[1.01] transition-transform`}
      onClick={() => onSelect?.(alert)}
      data-testid={`alert-card-${alert.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* Header: Symbol + Direction */}
          <div className="flex items-center gap-2 mb-1">
            <span className="font-bold text-white text-lg">{alert.symbol}</span>
            <span className={`flex items-center gap-1 text-xs font-medium ${direction.color}`}>
              <DirectionIcon className="w-3 h-3" />
              {direction.label}
            </span>
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${priority.bg} ${priority.color}`}>
              {priority.label}
            </span>
          </div>
          
          {/* Setup Type */}
          <div className="text-sm text-zinc-300 mb-1 truncate">
            {alert.setup_type?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
          </div>
          
          {/* Headline */}
          <div className="text-xs text-zinc-400 line-clamp-2">
            {alert.headline}
          </div>
          
          {/* Key Stats */}
          <div className="flex items-center gap-3 mt-2 text-xs">
            <div className="flex items-center gap-1">
              <span className="text-zinc-500">Price:</span>
              <span className="text-white font-medium">${alert.current_price?.toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-zinc-500">Trigger:</span>
              <span className="text-primary font-medium">${alert.trigger_price?.toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-zinc-500">R:R</span>
              <span className="text-emerald-400 font-medium">{alert.risk_reward?.toFixed(1)}:1</span>
            </div>
          </div>
          
          {/* Timing */}
          <div className="flex items-center gap-2 mt-2">
            <Clock className="w-3 h-3 text-zinc-500" />
            <span className="text-xs text-zinc-400">
              ~{formatTime(alert.minutes_to_trigger)} to trigger
            </span>
            <span className="text-xs text-zinc-500">|</span>
            <span className="text-xs text-emerald-400">
              {Math.round(alert.trigger_probability * 100)}% prob
            </span>
          </div>
        </div>
        
        {/* Dismiss button */}
        <button 
          onClick={(e) => { e.stopPropagation(); onDismiss?.(alert.id); }}
          className="p-1 rounded hover:bg-white/10 text-zinc-500 hover:text-white"
          data-testid={`dismiss-alert-${alert.id}`}
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
};

// Scanner Status Badge
const ScannerStatusBadge = ({ status, lastScan }) => {
  const isRunning = status?.running;
  
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className={`flex items-center gap-1 px-2 py-1 rounded-full ${
        isRunning ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'
      }`}>
        <Radio className={`w-3 h-3 ${isRunning ? 'animate-pulse' : ''}`} />
        <span>{isRunning ? 'Live' : 'Paused'}</span>
      </div>
      {status?.scan_count > 0 && (
        <span className="text-zinc-500">
          {status.scan_count} scans | {status.alerts_generated} alerts
        </span>
      )}
    </div>
  );
};

// Main Component
const LiveAlertsPanel = ({ 
  isExpanded = false, 
  onToggleExpand,
  onAlertSelect,
  className = '' 
}) => {
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const eventSourceRef = useRef(null);
  const alertsContainerRef = useRef(null);
  
  // Connect to SSE stream
  const connectToStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    
    const eventSource = new EventSource(`${API_URL}/api/live-scanner/stream`);
    eventSourceRef.current = eventSource;
    
    eventSource.onopen = () => {
      console.log('Live alerts SSE connected');
      setConnected(true);
    };
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'connected') {
          console.log('Live scanner connected:', data.timestamp);
          setConnected(true);
        } else if (data.type === 'alert') {
          const newAlert = data.alert;
          setAlerts(prev => {
            // Check if alert already exists
            const exists = prev.some(a => a.id === newAlert.id);
            if (exists) return prev;
            
            // Add new alert at the top
            const updated = [newAlert, ...prev].slice(0, 50); // Keep max 50
            
            // Play notification sound if enabled
            if (notificationsEnabled && newAlert.priority === 'critical') {
              playNotificationSound();
            }
            
            return updated;
          });
          
          // Auto-scroll to top
          if (autoScroll && alertsContainerRef.current) {
            alertsContainerRef.current.scrollTop = 0;
          }
        } else if (data.type === 'heartbeat') {
          // Keep-alive, do nothing
        }
      } catch (err) {
        console.error('Error parsing SSE message:', err);
      }
    };
    
    eventSource.onerror = (err) => {
      console.error('Live alerts SSE error:', err);
      setConnected(false);
      
      // Reconnect after 5 seconds
      setTimeout(() => {
        if (eventSourceRef.current === eventSource) {
          connectToStream();
        }
      }, 5000);
    };
    
    return () => {
      eventSource.close();
    };
  }, [notificationsEnabled, autoScroll]);
  
  // Fetch scanner status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/live-scanner/status`);
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      console.error('Failed to fetch scanner status:', err);
    }
  }, []);
  
  // Fetch existing alerts
  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/live-scanner/alerts`);
      const data = await res.json();
      if (data.alerts) {
        setAlerts(data.alerts);
      }
    } catch (err) {
      console.error('Failed to fetch alerts:', err);
    }
  }, []);
  
  // Dismiss alert
  const dismissAlert = useCallback(async (alertId) => {
    try {
      await fetch(`${API_URL}/api/live-scanner/alerts/${alertId}/dismiss`, {
        method: 'POST'
      });
      setAlerts(prev => prev.filter(a => a.id !== alertId));
    } catch (err) {
      console.error('Failed to dismiss alert:', err);
      // Still remove from UI
      setAlerts(prev => prev.filter(a => a.id !== alertId));
    }
  }, []);
  
  // Toggle scanner (start/stop)
  const toggleScanner = useCallback(async () => {
    try {
      const endpoint = status?.running ? 'stop' : 'start';
      await fetch(`${API_URL}/api/live-scanner/${endpoint}`, { method: 'POST' });
      fetchStatus();
    } catch (err) {
      console.error('Failed to toggle scanner:', err);
    }
  }, [status?.running, fetchStatus]);
  
  // Play notification sound
  const playNotificationSound = () => {
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const oscillator = audioContext.createOscillator();
      const gainNode = audioContext.createGain();
      
      oscillator.connect(gainNode);
      gainNode.connect(audioContext.destination);
      
      oscillator.frequency.value = 880;
      oscillator.type = 'sine';
      gainNode.gain.value = 0.1;
      
      oscillator.start();
      
      setTimeout(() => {
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1);
        setTimeout(() => oscillator.stop(), 100);
      }, 100);
    } catch (err) {
      // Ignore audio errors
    }
  };
  
  // Initialize
  useEffect(() => {
    fetchStatus();
    fetchAlerts();
    const cleanup = connectToStream();
    
    // Periodic status refresh
    const statusInterval = setInterval(fetchStatus, 30000);
    
    return () => {
      cleanup?.();
      clearInterval(statusInterval);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [fetchStatus, fetchAlerts, connectToStream]);
  
  // Group alerts by priority
  const criticalAlerts = alerts.filter(a => a.priority === 'critical');
  const highAlerts = alerts.filter(a => a.priority === 'high');
  const otherAlerts = alerts.filter(a => !['critical', 'high'].includes(a.priority));
  
  if (!isExpanded) {
    // Collapsed view - just show badge
    return (
      <button
        onClick={onToggleExpand}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700/50 hover:border-primary/30 transition-all ${className}`}
        data-testid="live-alerts-toggle"
      >
        <Radio className={`w-4 h-4 ${connected ? 'text-emerald-400 animate-pulse' : 'text-zinc-500'}`} />
        <span className="text-sm text-white font-medium">Live Alerts</span>
        {alerts.length > 0 && (
          <span className="px-1.5 py-0.5 text-xs font-bold bg-primary/20 text-primary rounded">
            {alerts.length}
          </span>
        )}
        {criticalAlerts.length > 0 && (
          <span className="px-1.5 py-0.5 text-xs font-bold bg-red-500/20 text-red-400 rounded animate-pulse">
            {criticalAlerts.length} critical
          </span>
        )}
        <Maximize2 className="w-4 h-4 text-zinc-500" />
      </button>
    );
  }
  
  // Expanded panel
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className={`bg-zinc-900/95 backdrop-blur-sm border border-zinc-700/50 rounded-xl overflow-hidden ${className}`}
      data-testid="live-alerts-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-zinc-700/50">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Radio className={`w-5 h-5 ${connected ? 'text-emerald-400 animate-pulse' : 'text-zinc-500'}`} />
            <h3 className="font-semibold text-white">Live Trade Alerts</h3>
          </div>
          <ScannerStatusBadge status={status} />
        </div>
        
        <div className="flex items-center gap-2">
          {/* Toggle scanner */}
          <button
            onClick={toggleScanner}
            className={`p-2 rounded-lg transition-colors ${
              status?.running 
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' 
                : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
            }`}
            title={status?.running ? 'Pause scanner' : 'Start scanner'}
            data-testid="toggle-scanner-btn"
          >
            {status?.running ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
          
          {/* Notifications toggle */}
          <button
            onClick={() => setNotificationsEnabled(!notificationsEnabled)}
            className={`p-2 rounded-lg transition-colors ${
              notificationsEnabled 
                ? 'bg-primary/20 text-primary' 
                : 'bg-zinc-700 text-zinc-400'
            }`}
            title={notificationsEnabled ? 'Disable sounds' : 'Enable sounds'}
            data-testid="toggle-notifications-btn"
          >
            {notificationsEnabled ? <Bell className="w-4 h-4" /> : <BellOff className="w-4 h-4" />}
          </button>
          
          {/* Collapse */}
          <button
            onClick={onToggleExpand}
            className="p-2 rounded-lg bg-zinc-700 text-zinc-400 hover:text-white transition-colors"
            data-testid="collapse-alerts-btn"
          >
            <Minimize2 className="w-4 h-4" />
          </button>
        </div>
      </div>
      
      {/* Alerts List */}
      <div 
        ref={alertsContainerRef}
        className="max-h-[400px] overflow-y-auto p-4 space-y-1"
      >
        {alerts.length === 0 ? (
          <div className="text-center py-8 text-zinc-500">
            <Target className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No active alerts</p>
            <p className="text-xs mt-1">The scanner is analyzing the market...</p>
          </div>
        ) : (
          <>
            {/* Critical Alerts */}
            {criticalAlerts.length > 0 && (
              <div className="mb-3">
                <div className="flex items-center gap-2 mb-2 text-xs font-medium text-red-400">
                  <AlertTriangle className="w-3 h-3" />
                  CRITICAL - ACT NOW
                </div>
                <AnimatePresence>
                  {criticalAlerts.map(alert => (
                    <AlertCard 
                      key={alert.id} 
                      alert={alert} 
                      onDismiss={dismissAlert}
                      onSelect={onAlertSelect}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}
            
            {/* High Priority */}
            {highAlerts.length > 0 && (
              <div className="mb-3">
                <div className="flex items-center gap-2 mb-2 text-xs font-medium text-orange-400">
                  <Zap className="w-3 h-3" />
                  HIGH PRIORITY
                </div>
                <AnimatePresence>
                  {highAlerts.map(alert => (
                    <AlertCard 
                      key={alert.id} 
                      alert={alert} 
                      onDismiss={dismissAlert}
                      onSelect={onAlertSelect}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}
            
            {/* Other Alerts */}
            {otherAlerts.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2 text-xs font-medium text-zinc-400">
                  <Clock className="w-3 h-3" />
                  ON WATCH
                </div>
                <AnimatePresence>
                  {otherAlerts.map(alert => (
                    <AlertCard 
                      key={alert.id} 
                      alert={alert} 
                      onDismiss={dismissAlert}
                      onSelect={onAlertSelect}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}
          </>
        )}
      </div>
      
      {/* Footer - quick stats */}
      <div className="px-4 py-2 border-t border-zinc-700/50 bg-zinc-800/30 text-xs text-zinc-500 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span>Watchlist: {status?.watchlist_size || 0} symbols</span>
          <span>Interval: {status?.scan_interval || 60}s</span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          <span>Connected</span>
        </div>
      </div>
    </motion.div>
  );
};

export default LiveAlertsPanel;
