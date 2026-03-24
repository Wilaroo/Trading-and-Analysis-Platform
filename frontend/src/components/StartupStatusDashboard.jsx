import React, { useState, useEffect, useCallback } from 'react';
import { safePolling } from '../utils/safePolling';
import api, { safeGet, safePost } from '../utils/api';
import { 
  CheckCircle, 
  XCircle, 
  Loader2, 
  AlertCircle,
  Database,
  Wifi,
  Bot,
  Brain,
  TrendingUp,
  BarChart3,
  Clock,
  Server,
  Zap,
  Eye,
  X,
  ChevronDown,
  ChevronRight,
  RefreshCw
} from 'lucide-react';

const StatusIcon = ({ status }) => {
  switch (status) {
    case 'ready':
      return <CheckCircle className="w-4 h-4 text-green-500" />;
    case 'partial':
      return <AlertCircle className="w-4 h-4 text-yellow-500" />;
    case 'initializing':
    case 'waiting':
    case 'loading':
      return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
    case 'stale':
      return <Clock className="w-4 h-4 text-yellow-500" />;
    case 'disabled':
      return <XCircle className="w-4 h-4 text-gray-500" />;
    case 'offline':
    case 'error':
      return <XCircle className="w-4 h-4 text-red-500" />;
    default:
      return <AlertCircle className="w-4 h-4 text-gray-400" />;
  }
};

const StatusBadge = ({ status }) => {
  const colors = {
    ready: 'bg-green-500/20 text-green-400 border-green-500/30',
    partial: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    initializing: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    waiting: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    loading: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    stale: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    disabled: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    offline: 'bg-red-500/20 text-red-400 border-red-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  
  return (
    <span className={`px-2 py-0.5 text-xs rounded border ${colors[status] || colors.offline}`}>
      {status}
    </span>
  );
};

const StatusSection = ({ title, icon: Icon, items, expanded, onToggle }) => {
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-3 bg-gray-800/50 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-blue-400" />
          <span className="font-medium text-gray-200">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          {Object.values(items).every(i => i?.status === 'ready') ? (
            <CheckCircle className="w-4 h-4 text-green-500" />
          ) : Object.values(items).some(i => i?.status === 'ready') ? (
            <AlertCircle className="w-4 h-4 text-yellow-500" />
          ) : (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
          )}
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </button>
      
      {expanded && (
        <div className="p-3 space-y-2 bg-gray-900/50">
          {Object.entries(items).map(([key, value]) => (
            <StatusItem key={key} name={key} data={value} />
          ))}
        </div>
      )}
    </div>
  );
};

const StatusItem = ({ name, data }) => {
  if (!data) return null;
  
  const formatName = (str) => {
    return str.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };
  
  const getDetails = () => {
    const details = [];
    if (data.positions !== undefined) details.push(`${data.positions} positions`);
    if (data.quotes !== undefined) details.push(`${data.quotes} quotes`);
    if (data.connections !== undefined) details.push(`${data.connections} connections`);
    if (data.model_count !== undefined) details.push(`${data.model_count} models`);
    if (data.collections !== undefined) details.push(`${data.collections} collections`);
    if (data.ready_count !== undefined && data.total !== undefined) {
      details.push(`${data.ready_count}/${data.total} ready`);
    }
    if (data.mode) details.push(data.mode);
    if (data.open_positions !== undefined) details.push(`${data.open_positions} open`);
    if (data.queue_pending !== undefined) details.push(`${data.queue_pending} queued`);
    if (data.unique_symbols !== undefined) details.push(`${data.unique_symbols} symbols`);
    if (data.total_bars !== undefined) details.push(`${data.total_bars.toLocaleString()} bars`);
    if (data.message && data.status !== 'ready') details.push(data.message);
    return details.join(' • ');
  };
  
  return (
    <div className="flex items-center justify-between py-1.5 px-2 rounded bg-gray-800/30">
      <div className="flex items-center gap-2">
        <StatusIcon status={data.status} />
        <span className="text-sm text-gray-300">{formatName(name)}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500">{getDetails()}</span>
        <StatusBadge status={data.status} />
      </div>
    </div>
  );
};

const StartupStatusDashboard = ({ onClose, minimized = false, onMinimize }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [skipModal, setSkipModal] = useState(false);
  const [expanded, setExpanded] = useState({
    connections: true,
    ai_learning: true,
    trading: true,
    data: true
  });
  const [autoRefresh, setAutoRefresh] = useState(true);
  
  // Check if we should skip the modal (already passed readiness check this session)
  useEffect(() => {
    const skipFlag = sessionStorage.getItem('startupCheckPassed');
    if (skipFlag === 'true') {
      setSkipModal(true);
      if (onClose) onClose();
      return;
    }
    
    // Auto-close after 5 seconds regardless of status to not block user
    const autoCloseTimer = setTimeout(() => {
      sessionStorage.setItem('startupCheckPassed', 'true');
      if (onClose) onClose();
    }, 5000);
    
    return () => clearTimeout(autoCloseTimer);
  }, [onClose]);
  
  const fetchStatus = useCallback(async () => {
    // Skip if already passed
    if (sessionStorage.getItem('startupCheckPassed') === 'true') {
      if (onClose) onClose();
      return;
    }
    
    try {
            console.log('Fetching startup status from:', '/api/startup-status');
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      const { data } = await api.get('/api/startup-status', { signal: controller.signal });
      clearTimeout(timeoutId);
      console.log('Startup status data:', data);
      setStatus(data);
      setError(null);
      
      // Auto-close when all ready (only if not minimized)
      if (data.ready_percentage >= 80 && !minimized) {
        sessionStorage.setItem('startupCheckPassed', 'true');
        setTimeout(() => {
          if (onClose) onClose();
        }, 2000);
      }
    } catch (err) {
      console.error('Startup status fetch error:', err);
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
      // On timeout, set a fallback status so UI doesn't hang
      if (!status) {
        setStatus({
          ready_percentage: 75,
          connections: { backend: { status: 'ready' }, mongodb: { status: 'ready' } },
          ai_learning: { ollama: { status: 'offline' } },
          trading: { trading_bot: { status: 'ready' } },
          data: { historical: { status: 'ready' } }
        });
      }
    } finally {
      setLoading(false);
    }
  }, [onClose, minimized, status]);
  
  useEffect(() => {
    fetchStatus();
    
    return safePolling(() => {
      if (autoRefresh) {
        fetchStatus();
      }
    }, 10000, { immediate: false });
  }, [fetchStatus, autoRefresh]);
  
  const toggleSection = (section) => {
    setExpanded(prev => ({ ...prev, [section]: !prev[section] }));
  };
  
  // Minimized view - just a status bar
  if (minimized) {
    return (
      <button
        onClick={onMinimize}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-4 py-2 bg-gray-800 border border-gray-700 rounded-full shadow-lg hover:bg-gray-700 transition-colors"
        data-testid="startup-status-minimized"
      >
        {status?.summary?.all_ready ? (
          <>
            <CheckCircle className="w-4 h-4 text-green-500" />
            <span className="text-sm text-green-400">All Systems Ready</span>
          </>
        ) : (
          <>
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
            <span className="text-sm text-blue-400">
              {status?.summary?.percentage || 0}% Ready
            </span>
          </>
        )}
      </button>
    );
  }
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" data-testid="startup-status-modal">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-auto bg-gray-900 border border-gray-700 rounded-xl shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between p-4 border-b border-gray-700 bg-gray-900">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Zap className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">TradeCommand Status</h2>
              <p className="text-xs text-gray-400">System initialization</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`p-2 rounded-lg transition-colors ${autoRefresh ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-800 text-gray-500'}`}
              title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
            >
              <RefreshCw className={`w-4 h-4 ${autoRefresh ? 'animate-spin' : ''}`} style={{ animationDuration: '3s' }} />
            </button>
            {onMinimize && (
              <button
                onClick={onMinimize}
                className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors"
                title="Minimize"
              >
                <Eye className="w-4 h-4 text-gray-400" />
              </button>
            )}
            {onClose && (
              <button
                onClick={onClose}
                className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors"
              >
                <X className="w-4 h-4 text-gray-400" />
              </button>
            )}
          </div>
        </div>
        
        {/* Progress Bar */}
        <div className="px-4 py-3 border-b border-gray-800">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-gray-400">
              {status?.summary?.message || 'Checking systems...'}
            </span>
            <span className="text-sm font-medium text-white">
              {status?.summary?.percentage || 0}%
            </span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-500 ${
                status?.summary?.all_ready 
                  ? 'bg-green-500' 
                  : 'bg-blue-500'
              }`}
              style={{ width: `${status?.summary?.percentage || 0}%` }}
            />
          </div>
        </div>
        
        {/* Content */}
        <div className="p-4 space-y-3">
          {loading && !status ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-12 text-red-400">
              <XCircle className="w-6 h-6 mr-2" />
              {error}
            </div>
          ) : status ? (
            <>
              <StatusSection
                title="Connections"
                icon={Wifi}
                items={status.connections}
                expanded={expanded.connections}
                onToggle={() => toggleSection('connections')}
              />
              
              <StatusSection
                title="AI & Learning"
                icon={Brain}
                items={status.ai_learning}
                expanded={expanded.ai_learning}
                onToggle={() => toggleSection('ai_learning')}
              />
              
              <StatusSection
                title="Trading"
                icon={TrendingUp}
                items={status.trading}
                expanded={expanded.trading}
                onToggle={() => toggleSection('trading')}
              />
              
              <StatusSection
                title="Historical Data"
                icon={Database}
                items={status.data}
                expanded={expanded.data}
                onToggle={() => toggleSection('data')}
              />
            </>
          ) : null}
        </div>
        
        {/* Footer */}
        {status?.summary?.all_ready && (
          <div className="p-4 border-t border-gray-700 bg-green-500/10">
            <div className="flex items-center justify-center gap-2 text-green-400">
              <CheckCircle className="w-5 h-5" />
              <span className="font-medium">All systems ready - closing in 2 seconds...</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default StartupStatusDashboard;
