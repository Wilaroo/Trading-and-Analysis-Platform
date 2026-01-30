/**
 * LiveAlertsPanel - Real-time trade alerts via SSE
 * Connects to the background scanner and displays live trading opportunities
 * Enhanced with customizable scan intervals and watchlist editing
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
  ChevronDown,
  Info,
  Settings,
  Zap,
  Plus,
  Trash2,
  Save,
  RefreshCw,
  List,
  Timer,
  Eye,
  EyeOff
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

// Preset scan intervals
const SCAN_INTERVAL_PRESETS = [
  { value: 30, label: '30s', description: 'Aggressive - Active trading' },
  { value: 60, label: '1m', description: 'Standard - Balanced' },
  { value: 120, label: '2m', description: 'Moderate - Less frequent' },
  { value: 300, label: '5m', description: 'Conservative - Low activity' },
];

// Default watchlist symbols
const DEFAULT_SYMBOLS = [
  'NVDA', 'TSLA', 'AMD', 'META', 'AAPL', 'MSFT', 'GOOGL', 'AMZN',
  'SPY', 'QQQ', 'NFLX', 'COIN', 'SQ', 'SHOP', 'BA'
];

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
const ScannerStatusBadge = ({ status }) => {
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

// Settings Panel Component
const SettingsPanel = ({ 
  isOpen, 
  onClose, 
  status, 
  watchlist, 
  onWatchlistUpdate, 
  onIntervalUpdate,
  onSetupsUpdate 
}) => {
  const [newSymbol, setNewSymbol] = useState('');
  const [localWatchlist, setLocalWatchlist] = useState(watchlist || []);
  const [selectedInterval, setSelectedInterval] = useState(status?.scan_interval || 60);
  const [enabledSetups, setEnabledSetups] = useState(new Set(status?.enabled_setups || []));
  const [saving, setSaving] = useState(false);
  
  const allSetups = ['rubber_band', 'breakout', 'vwap_bounce', 'squeeze'];
  
  useEffect(() => {
    setLocalWatchlist(watchlist || []);
  }, [watchlist]);
  
  useEffect(() => {
    if (status) {
      setSelectedInterval(status.scan_interval || 60);
      setEnabledSetups(new Set(status.enabled_setups || []));
    }
  }, [status]);
  
  const addSymbol = () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (symbol && !localWatchlist.includes(symbol)) {
      setLocalWatchlist([...localWatchlist, symbol]);
      setNewSymbol('');
    }
  };
  
  const removeSymbol = (symbol) => {
    setLocalWatchlist(localWatchlist.filter(s => s !== symbol));
  };
  
  const toggleSetup = (setup) => {
    const newSetups = new Set(enabledSetups);
    if (newSetups.has(setup)) {
      newSetups.delete(setup);
    } else {
      newSetups.add(setup);
    }
    setEnabledSetups(newSetups);
  };
  
  const saveChanges = async () => {
    setSaving(true);
    try {
      // Update watchlist
      await onWatchlistUpdate(localWatchlist);
      
      // Update interval and setups
      await onIntervalUpdate(selectedInterval, Array.from(enabledSetups));
      
      onClose();
    } catch (err) {
      console.error('Failed to save settings:', err);
    }
    setSaving(false);
  };
  
  const resetToDefaults = () => {
    setLocalWatchlist(DEFAULT_SYMBOLS);
    setSelectedInterval(60);
    setEnabledSetups(new Set(allSetups));
  };
  
  if (!isOpen) return null;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="absolute top-full left-0 right-0 mt-2 bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl z-50 overflow-hidden"
      data-testid="scanner-settings-panel"
    >
      <div className="p-4 border-b border-zinc-700 flex items-center justify-between">
        <h4 className="font-semibold text-white flex items-center gap-2">
          <Settings className="w-4 h-4 text-cyan-400" />
          Scanner Settings
        </h4>
        <button onClick={onClose} className="p-1 hover:bg-zinc-700 rounded">
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      </div>
      
      <div className="p-4 space-y-5 max-h-[400px] overflow-y-auto">
        {/* Scan Interval */}
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-2">
            <Timer className="w-4 h-4 text-cyan-400" />
            Scan Interval
          </label>
          <div className="grid grid-cols-4 gap-2">
            {SCAN_INTERVAL_PRESETS.map(preset => (
              <button
                key={preset.value}
                onClick={() => setSelectedInterval(preset.value)}
                className={`p-2 rounded-lg border text-center transition-all ${
                  selectedInterval === preset.value
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                    : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:border-zinc-600'
                }`}
                title={preset.description}
                data-testid={`interval-${preset.value}`}
              >
                <div className="text-sm font-medium">{preset.label}</div>
                <div className="text-[10px] text-zinc-500 mt-0.5">{preset.description.split(' - ')[0]}</div>
              </button>
            ))}
          </div>
        </div>
        
        {/* Setup Types */}
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-2">
            <Target className="w-4 h-4 text-cyan-400" />
            Setup Types
          </label>
          <div className="grid grid-cols-2 gap-2">
            {allSetups.map(setup => (
              <button
                key={setup}
                onClick={() => toggleSetup(setup)}
                className={`flex items-center gap-2 p-2 rounded-lg border transition-all ${
                  enabledSetups.has(setup)
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400'
                    : 'bg-zinc-800 border-zinc-700 text-zinc-500 hover:border-zinc-600'
                }`}
                data-testid={`setup-toggle-${setup}`}
              >
                {enabledSetups.has(setup) ? (
                  <Eye className="w-4 h-4" />
                ) : (
                  <EyeOff className="w-4 h-4" />
                )}
                <span className="text-sm capitalize">{setup.replace(/_/g, ' ')}</span>
              </button>
            ))}
          </div>
        </div>
        
        {/* Watchlist */}
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-2">
            <List className="w-4 h-4 text-cyan-400" />
            Watchlist ({localWatchlist.length} symbols)
          </label>
          
          {/* Add Symbol Input */}
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && addSymbol()}
              placeholder="Add symbol..."
              className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-cyan-500"
              data-testid="add-symbol-input"
            />
            <button
              onClick={addSymbol}
              disabled={!newSymbol.trim()}
              className="px-3 py-2 bg-cyan-500/20 text-cyan-400 rounded-lg hover:bg-cyan-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="add-symbol-btn"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
          
          {/* Symbol Tags */}
          <div className="flex flex-wrap gap-2 max-h-[120px] overflow-y-auto p-2 bg-zinc-800/50 rounded-lg">
            {localWatchlist.map(symbol => (
              <div
                key={symbol}
                className="flex items-center gap-1 px-2 py-1 bg-zinc-700 rounded text-sm text-white group"
              >
                <span className="font-mono">{symbol}</span>
                <button
                  onClick={() => removeSymbol(symbol)}
                  className="p-0.5 rounded hover:bg-red-500/20 text-zinc-400 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                  data-testid={`remove-${symbol}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            {localWatchlist.length === 0 && (
              <span className="text-zinc-500 text-sm">No symbols in watchlist</span>
            )}
          </div>
        </div>
      </div>
      
      {/* Footer Actions */}
      <div className="p-4 border-t border-zinc-700 flex items-center justify-between">
        <button
          onClick={resetToDefaults}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-zinc-400 hover:text-white transition-colors"
          data-testid="reset-defaults-btn"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Reset to Defaults
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={saveChanges}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-500 text-black rounded-lg text-sm font-medium hover:bg-cyan-400 disabled:opacity-50"
            data-testid="save-settings-btn"
          >
            {saving ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save Changes
          </button>
        </div>
      </div>
    </motion.div>
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
  const [watchlist, setWatchlist] = useState([]);
  const [connected, setConnected] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
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
          if (alertsContainerRef.current) {
            alertsContainerRef.current.scrollTop = 0;
          }
        } else if (data.type === 'heartbeat') {
          // Keep-alive, do nothing
        }
      } catch (err) {
        console.error('Error parsing SSE message:', err);
      }
    };
    
    eventSource.onerror = () => {
      console.error('Live alerts SSE error');
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
  }, [notificationsEnabled]);
  
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
  
  // Fetch watchlist
  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/live-scanner/watchlist`);
      const data = await res.json();
      setWatchlist(data.watchlist || []);
    } catch (err) {
      console.error('Failed to fetch watchlist:', err);
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
  
  // Update watchlist
  const updateWatchlist = useCallback(async (symbols) => {
    try {
      await fetch(`${API_URL}/api/live-scanner/watchlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols })
      });
      setWatchlist(symbols);
      fetchStatus(); // Refresh status
    } catch (err) {
      console.error('Failed to update watchlist:', err);
      throw err;
    }
  }, [fetchStatus]);
  
  // Update scan interval and setups
  const updateConfig = useCallback(async (interval, setups) => {
    try {
      await fetch(`${API_URL}/api/live-scanner/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          scan_interval: interval,
          enabled_setups: setups
        })
      });
      fetchStatus(); // Refresh status
    } catch (err) {
      console.error('Failed to update config:', err);
      throw err;
    }
  }, [fetchStatus]);
  
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
    fetchWatchlist();
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
  }, [fetchStatus, fetchAlerts, fetchWatchlist, connectToStream]);
  
  // Group alerts by priority
  const criticalAlerts = alerts.filter(a => a.priority === 'critical');
  const highAlerts = alerts.filter(a => a.priority === 'high');
  const otherAlerts = alerts.filter(a => !['critical', 'high'].includes(a.priority));
  
  // Format interval for display
  const formatInterval = (seconds) => {
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m`;
  };
  
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
      className={`bg-zinc-900/95 backdrop-blur-sm border border-zinc-700/50 rounded-xl overflow-visible relative ${className}`}
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
          {/* Settings button */}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-lg transition-colors ${
              showSettings 
                ? 'bg-cyan-500/20 text-cyan-400' 
                : 'bg-zinc-700 text-zinc-400 hover:text-white'
            }`}
            title="Scanner Settings"
            data-testid="scanner-settings-btn"
          >
            <Settings className="w-4 h-4" />
          </button>
          
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
      
      {/* Settings Panel */}
      <AnimatePresence>
        {showSettings && (
          <SettingsPanel
            isOpen={showSettings}
            onClose={() => setShowSettings(false)}
            status={status}
            watchlist={watchlist}
            onWatchlistUpdate={updateWatchlist}
            onIntervalUpdate={updateConfig}
          />
        )}
      </AnimatePresence>
      
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
          <span className="flex items-center gap-1">
            <List className="w-3 h-3" />
            {status?.watchlist_size || watchlist.length} symbols
          </span>
          <span className="flex items-center gap-1">
            <Timer className="w-3 h-3" />
            {formatInterval(status?.scan_interval || 60)}
          </span>
          <span className="flex items-center gap-1">
            <Target className="w-3 h-3" />
            {status?.enabled_setups?.length || 0} setups
          </span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle2 className={`w-3 h-3 ${connected ? 'text-emerald-400' : 'text-zinc-500'}`} />
          <span>{connected ? 'Connected' : 'Reconnecting...'}</span>
        </div>
      </div>
    </motion.div>
  );
};

export default LiveAlertsPanel;
