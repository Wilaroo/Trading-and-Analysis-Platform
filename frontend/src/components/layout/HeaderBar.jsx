import React, { useState, useRef, useEffect } from 'react';
import {
  Target,
  Activity,
  RefreshCw,
  Database,
  WifiOff,
  Monitor,
  Zap,
  AlertTriangle,
  X,
  TrendingUp,
  TrendingDown,
  Clock,
  Calendar,
  BarChart3,
  Search,
  ChevronDown,
  CheckCircle2,
  XCircle,
  Loader2,
  Server,
  Upload
} from 'lucide-react';

// Credit Budget Detail Modal Component
const CreditBudgetModal = ({ isOpen, onClose, creditBudget }) => {
  if (!isOpen || !creditBudget) return null;

  const {
    month,
    credits_used,
    credits_remaining,
    monthly_limit,
    usage_percent,
    status_level,
    session_credits,
    daily_average,
    projected_monthly_usage,
    on_track,
    recent_usage,
    credits_saved = 0,
    cache_hit_rate = 'N/A',
    savings_percent = 0
  } = creditBudget;

  const getStatusColor = (level) => {
    switch (level) {
      case 'critical': return 'text-red-400 bg-red-500/10 border-red-500/30';
      case 'high': return 'text-orange-400 bg-orange-500/10 border-orange-500/30';
      case 'medium': return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30';
      case 'low': return 'text-blue-400 bg-blue-500/10 border-blue-500/30';
      default: return 'text-green-400 bg-green-500/10 border-green-500/30';
    }
  };

  const getProgressColor = (level) => {
    switch (level) {
      case 'critical': return 'bg-red-500';
      case 'high': return 'bg-orange-500';
      case 'medium': return 'bg-yellow-500';
      case 'low': return 'bg-blue-500';
      default: return 'bg-green-500';
    }
  };

  const formatTime = (isoString) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  // Calculate days remaining in month
  const now = new Date();
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const daysRemaining = lastDay.getDate() - now.getDate();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-700">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${getStatusColor(status_level)}`}>
              <Zap className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">AI Research Credits</h2>
              <p className="text-xs text-zinc-400">Tavily API Usage for {month}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Main Stats */}
        <div className="p-4 space-y-4">
          {/* Big Progress Ring */}
          <div className="flex items-center gap-6">
            <div className="relative w-24 h-24">
              <svg className="w-24 h-24 transform -rotate-90">
                <circle
                  cx="48"
                  cy="48"
                  r="40"
                  stroke="currentColor"
                  strokeWidth="8"
                  fill="none"
                  className="text-zinc-800"
                />
                <circle
                  cx="48"
                  cy="48"
                  r="40"
                  stroke="currentColor"
                  strokeWidth="8"
                  fill="none"
                  strokeLinecap="round"
                  className={getProgressColor(status_level).replace('bg-', 'text-')}
                  strokeDasharray={`${usage_percent * 2.51} 251`}
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-white">{Math.round(usage_percent)}%</span>
                <span className="text-xs text-zinc-400">used</span>
              </div>
            </div>
            
            <div className="flex-1 space-y-2">
              <div className="flex justify-between">
                <span className="text-zinc-400 text-sm">Used</span>
                <span className="text-white font-medium">{credits_used} credits</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 text-sm">Remaining</span>
                <span className="text-green-400 font-medium">{credits_remaining} credits</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400 text-sm">Monthly Limit</span>
                <span className="text-zinc-300 font-medium">{monthly_limit} credits</span>
              </div>
            </div>
          </div>

          {/* Status Badge */}
          <div className={`flex items-center justify-center gap-2 py-2 px-4 rounded-lg border ${getStatusColor(status_level)}`}>
            {status_level === 'critical' || status_level === 'high' ? (
              <AlertTriangle className="w-4 h-4" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
            <span className="text-sm font-medium capitalize">
              {status_level === 'ok' ? 'Healthy' : status_level} Status
            </span>
          </div>

          {/* Credits Saved Banner - Only show if there are savings */}
          {credits_saved > 0 && (
            <div className="bg-gradient-to-r from-emerald-500/10 via-emerald-500/5 to-transparent border border-emerald-500/20 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-500/20 rounded-lg">
                    <TrendingDown className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-emerald-400">Credits Saved by Caching</div>
                    <div className="text-xs text-zinc-400">Smart caching reduced your API calls</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-emerald-400">+{credits_saved}</div>
                  <div className="text-xs text-zinc-500">{savings_percent}% savings</div>
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                <span className="px-1.5 py-0.5 bg-zinc-800 rounded">Hit Rate: {cache_hit_rate}</span>
                <span>•</span>
                <span>Would have used {credits_used + credits_saved} credits without caching</span>
              </div>
            </div>
          )}

          {/* Stats Grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
              <div className="flex items-center gap-2 text-zinc-400 text-xs mb-1">
                <BarChart3 className="w-3 h-3" />
                Daily Average
              </div>
              <div className="text-lg font-semibold text-white">{daily_average}</div>
              <div className="text-xs text-zinc-500">credits/day</div>
            </div>
            
            <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
              <div className="flex items-center gap-2 text-zinc-400 text-xs mb-1">
                <TrendingUp className="w-3 h-3" />
                Projected
              </div>
              <div className={`text-lg font-semibold ${on_track ? 'text-green-400' : 'text-orange-400'}`}>
                {projected_monthly_usage}
              </div>
              <div className="text-xs text-zinc-500">by month end</div>
            </div>
            
            <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
              <div className="flex items-center gap-2 text-zinc-400 text-xs mb-1">
                <Clock className="w-3 h-3" />
                This Session
              </div>
              <div className="text-lg font-semibold text-cyan-400">{session_credits}</div>
              <div className="text-xs text-zinc-500">credits used</div>
            </div>
            
            <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
              <div className="flex items-center gap-2 text-zinc-400 text-xs mb-1">
                <Calendar className="w-3 h-3" />
                Days Left
              </div>
              <div className="text-lg font-semibold text-white">{daysRemaining}</div>
              <div className="text-xs text-zinc-500">until reset</div>
            </div>
          </div>

          {/* On Track Indicator */}
          <div className={`flex items-center gap-2 p-3 rounded-lg border ${
            on_track 
              ? 'bg-green-500/5 border-green-500/20 text-green-400'
              : 'bg-orange-500/5 border-orange-500/20 text-orange-400'
          }`}>
            {on_track ? (
              <>
                <TrendingDown className="w-4 h-4" />
                <span className="text-sm">You're on track to stay within budget this month</span>
              </>
            ) : (
              <>
                <TrendingUp className="w-4 h-4" />
                <span className="text-sm">At current pace, you may exceed the monthly limit</span>
              </>
            )}
          </div>

          {/* Recent Usage */}
          {recent_usage && recent_usage.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-zinc-300 mb-2 flex items-center gap-2">
                <Search className="w-4 h-4" />
                Recent Queries
              </h3>
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {recent_usage.slice().reverse().map((usage, idx) => (
                  <div 
                    key={idx}
                    className="flex items-center justify-between py-1.5 px-2 bg-zinc-800/30 rounded text-xs"
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className="text-zinc-500">{formatTime(usage.timestamp)}</span>
                      <span className="text-zinc-400 truncate">{usage.query}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-500 text-xs">{usage.source}</span>
                      <span className="text-cyan-400 font-medium">-{usage.credits}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-700 bg-zinc-800/30">
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span>Free tier: 1,000 credits/month</span>
            <a 
              href="https://tavily.com" 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-cyan-400 hover:text-cyan-300 transition-colors"
            >
              Upgrade for more →
            </a>
          </div>
        </div>
      </div>
    </div>
  );
};

// Ollama Usage Modal Component
const OllamaUsageModal = ({ isOpen, onClose, ollamaUsage }) => {
  if (!isOpen || !ollamaUsage) return null;

  const { session, weekly, daily, models_used, subscription } = ollamaUsage;

  const getStatusColor = (percent) => {
    if (percent >= 90) return 'text-red-400 bg-red-500/10 border-red-500/30';
    if (percent >= 70) return 'text-orange-400 bg-orange-500/10 border-orange-500/30';
    if (percent >= 50) return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30';
    return 'text-green-400 bg-green-500/10 border-green-500/30';
  };

  const getProgressColor = (percent) => {
    if (percent >= 90) return 'bg-red-500';
    if (percent >= 70) return 'bg-orange-500';
    if (percent >= 50) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 p-6 rounded-2xl"
           style={{
             background: 'linear-gradient(145deg, rgba(24, 32, 42, 0.98), rgba(16, 20, 28, 0.98))',
             border: '1px solid rgba(255, 255, 255, 0.08)',
             boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)'
           }}>
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/20">
              <Zap className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">Ollama {subscription}</h3>
              <p className="text-xs text-zinc-500">Cloud AI Usage</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-800/50 rounded-lg transition-colors">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Session Usage */}
        <div className={`mb-4 p-4 rounded-xl border ${getStatusColor(session?.used_percent || 0)}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Session Usage</span>
            <span className="text-xs text-zinc-400">Resets in {session?.reset_hours || '?'}h</span>
          </div>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex-1 h-2 rounded-full bg-black/40 overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all ${getProgressColor(session?.used_percent || 0)}`}
                style={{ width: `${Math.min(session?.used_percent || 0, 100)}%` }}
              />
            </div>
            <span className="text-sm font-mono">{session?.used_percent || 0}%</span>
          </div>
          <div className="text-xs text-zinc-400">
            {session?.requests || 0} / ~{session?.limit || 150} requests
          </div>
        </div>

        {/* Weekly Usage */}
        <div className={`mb-4 p-4 rounded-xl border ${getStatusColor(weekly?.used_percent || 0)}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Weekly Usage</span>
            <span className="text-xs text-zinc-400">Resets in {weekly?.reset_days || '?'} days</span>
          </div>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex-1 h-2 rounded-full bg-black/40 overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all ${getProgressColor(weekly?.used_percent || 0)}`}
                style={{ width: `${Math.min(weekly?.used_percent || 0, 100)}%` }}
              />
            </div>
            <span className="text-sm font-mono">{weekly?.used_percent || 0}%</span>
          </div>
          <div className="text-xs text-zinc-400">
            {weekly?.requests || 0} / ~{weekly?.limit || 750} requests
          </div>
        </div>

        {/* Today's Stats */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
            <div className="text-xs text-zinc-400 mb-1">Today</div>
            <div className="text-lg font-semibold text-white">{daily?.requests || 0}</div>
            <div className="text-xs text-zinc-500">requests</div>
          </div>
          <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
            <div className="text-xs text-zinc-400 mb-1">Primary Model</div>
            <div className="text-sm font-semibold text-purple-400 truncate">
              {Object.keys(models_used || {})[0] || 'N/A'}
            </div>
            <div className="text-xs text-zinc-500">
              {Object.values(models_used || {})[0] || 0} uses
            </div>
          </div>
        </div>

        {/* Models Used */}
        {models_used && Object.keys(models_used).length > 0 && (
          <div className="p-3 rounded-xl bg-zinc-800/30 border border-zinc-700/30">
            <div className="text-xs text-zinc-400 mb-2">Models Used</div>
            <div className="space-y-1">
              {Object.entries(models_used).map(([model, count]) => (
                <div key={model} className="flex items-center justify-between text-sm">
                  <span className="text-zinc-300 truncate">{model}</span>
                  <span className="text-zinc-500">{count} requests</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// System Status Popover Component
const SystemStatusPopover = ({ 
  wsConnected, 
  wsLastUpdate, 
  connectionChecked, 
  isConnected, 
  connecting,
  handleConnectToIB,
  ollamaStatus,
  ibPusherStatus
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const popoverRef = useRef(null);
  
  // Close popover when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  // Calculate overall system status
  const getOverallStatus = () => {
    const quotesOk = wsConnected;
    const ibOk = isConnected || (ibPusherStatus?.connected);
    const anyServiceOk = quotesOk || ibOk;
    
    // If quotes stream OR IB is connected, we're at least partially operational
    if (quotesOk && ibOk) return { status: 'online', label: 'All Systems Online', color: 'emerald' };
    // If any service is up, show partial (not offline)
    if (anyServiceOk) return { status: 'partial', label: 'Partial', color: 'amber' };
    // Only show offline if truly nothing is connected
    return { status: 'offline', label: 'Connecting...', color: 'amber' };
  };
  
  const overall = getOverallStatus();
  
  const services = [
    {
      name: 'Quotes Stream',
      description: 'Real-time market data via WebSocket',
      connected: wsConnected,
      lastUpdate: wsLastUpdate,
      icon: Activity
    },
    {
      name: 'IB Gateway',
      description: 'Direct trading & historical data',
      connected: isConnected && (!ibPusherStatus || !ibPusherStatus.connected),
      checking: !connectionChecked,
      icon: Database,
      action: !isConnected && connectionChecked ? {
        label: connecting ? 'Connecting...' : 'Reconnect',
        onClick: handleConnectToIB,
        disabled: connecting
      } : null
    },
    {
      name: 'IB Data Pusher',
      description: ibPusherStatus?.connected 
        ? `${ibPusherStatus.positions_count || 0} positions, ${ibPusherStatus.quotes_count || 0} quotes` 
        : 'Local script pushes IB data to cloud',
      connected: ibPusherStatus?.connected || false,
      checking: false,
      icon: Upload,
      stale: ibPusherStatus?.stale || false
    },
    {
      name: 'Ollama AI',
      description: ollamaStatus === 'online' ? 'Cloud AI (gpt-oss:120b)' : 'AI (offline)',
      connected: ollamaStatus === 'online',
      checking: ollamaStatus === 'checking',
      icon: Zap
    }
  ];
  
  return (
    <div className="relative" ref={popoverRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all hover:scale-[1.02] ${
          overall.color === 'emerald' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
          overall.color === 'amber' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' :
          'bg-red-500/10 border-red-500/30 text-red-400'
        } border`}
        data-testid="system-status-trigger"
      >
        <Server className="w-4 h-4" />
        <span className="text-xs font-medium hidden md:inline">{overall.label}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      
      {/* Popover Content */}
      {isOpen && (
        <div 
          className="absolute right-0 top-full mt-2 w-72 rounded-xl overflow-hidden z-[100]"
          style={{
            background: 'rgba(21, 28, 36, 0.95)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)'
          }}
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-white/10">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Server className="w-4 h-4 text-cyan-400" />
              System Status
            </h3>
            <p className="text-[10px] text-zinc-500 mt-0.5">Connection status for all services</p>
          </div>
          
          {/* Service List */}
          <div className="p-2 space-y-1">
            {services.map((service) => {
              const Icon = service.icon;
              return (
                <div 
                  key={service.name}
                  className="flex items-center justify-between p-2.5 rounded-lg hover:bg-white/5 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      service.connected ? 'bg-emerald-500/20' : 
                      service.stale ? 'bg-amber-500/20' :
                      service.checking ? 'bg-amber-500/20' : 'bg-red-500/20'
                    }`}>
                      <Icon className={`w-4 h-4 ${
                        service.connected ? 'text-emerald-400' : 
                        service.stale ? 'text-amber-400' :
                        service.checking ? 'text-amber-400' : 'text-red-400'
                      }`} />
                    </div>
                    <div>
                      <p className="text-xs font-medium text-white">{service.name}</p>
                      <p className="text-[10px] text-zinc-500">
                        {service.stale ? 'Data stale — reconnect pusher' : service.description}
                      </p>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {service.action ? (
                      <button
                        onClick={service.action.onClick}
                        disabled={service.action.disabled}
                        className="px-2 py-1 text-[10px] font-medium rounded bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-colors disabled:opacity-50"
                      >
                        {service.action.label}
                      </button>
                    ) : service.checking ? (
                      <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />
                    ) : service.connected ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    ) : service.stale ? (
                      <AlertTriangle className="w-4 h-4 text-amber-400" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-400" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          
          {/* Footer with last update */}
          {wsLastUpdate && (
            <div className="px-4 py-2 border-t border-white/5 text-[10px] text-zinc-500 flex items-center gap-1.5">
              <Clock className="w-3 h-3" />
              Last quote: {new Date(wsLastUpdate).toLocaleTimeString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const HeaderBar = ({
  systemHealth,
  wsConnected,
  wsLastUpdate,
  connectionChecked,
  isConnected,
  connecting,
  handleConnectToIB,
  handleDisconnectFromIB,
  creditBudget,
  ollamaStatus = 'unknown',
  ollamaUsage = null,
  ibPusherStatus = null
}) => {
  const [showCreditModal, setShowCreditModal] = useState(false);
  const [showOllamaModal, setShowOllamaModal] = useState(false);

  // Credit budget status color and icon
  const getCreditStatusConfig = () => {
    if (!creditBudget) return { color: 'zinc', icon: null, pulse: false };
    
    const { status_level } = creditBudget;
    
    switch (status_level) {
      case 'critical':
        return { color: 'red', icon: <AlertTriangle className="w-3 h-3" />, pulse: true };
      case 'high':
        return { color: 'orange', icon: <AlertTriangle className="w-3 h-3" />, pulse: true };
      case 'medium':
        return { color: 'yellow', icon: <Zap className="w-3 h-3" />, pulse: false };
      case 'low':
        return { color: 'blue', icon: <Zap className="w-3 h-3" />, pulse: false };
      default:
        return { color: 'green', icon: <Zap className="w-3 h-3" />, pulse: false };
    }
  };

  const creditConfig = getCreditStatusConfig();

  return (
    <>
      <div className="flex items-center justify-between p-3 rounded-xl"
           style={{
             background: 'rgba(21, 28, 36, 0.9)',
             backdropFilter: 'blur(24px)',
             WebkitBackdropFilter: 'blur(24px)',
             border: '1px solid rgba(255, 255, 255, 0.1)',
             boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
             position: 'relative',
             zIndex: 100
           }}>
        {/* Animated gradient border */}
        <div 
          className="absolute inset-0 rounded-xl pointer-events-none"
          style={{
            padding: '1px',
            background: 'linear-gradient(var(--gradient-angle, 135deg), var(--primary-main), var(--secondary-main), var(--accent-main), var(--primary-main))',
            WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            WebkitMaskComposite: 'xor',
            maskComposite: 'exclude',
            opacity: 0.5,
            animation: 'gradient-rotate 6s linear infinite'
          }}
        />
        
        <div className="flex items-center gap-4">
          {/* Logo and Title */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                 style={{
                   background: 'linear-gradient(135deg, var(--primary-main), var(--secondary-main))',
                   boxShadow: '0 2px 12px var(--primary-glow-strong)'
                 }}>
              <Target className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-white">
                Command <span className="neon-text">Center</span>
              </h1>
              <p className="text-zinc-500 text-[10px] tracking-wide">Real-time trading intelligence hub</p>
            </div>
          </div>
          
          {/* Credit Budget Indicator - COMPACT */}
          {creditBudget && (
            <button
              onClick={() => setShowCreditModal(true)}
              className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-all hover:scale-[1.02] ${
                creditConfig.pulse ? 'animate-pulse' : ''
              }`}
              style={{
                background: 'rgba(21, 28, 36, 0.9)',
                backdropFilter: 'blur(16px)',
                WebkitBackdropFilter: 'blur(16px)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                boxShadow: '0 2px 12px rgba(0, 0, 0, 0.2)'
              }}
              title="Click to view detailed credit usage"
              data-testid="credit-budget-indicator"
            >
              <Zap className={`w-4 h-4 ${
                creditConfig.color === 'red' ? 'text-red-400' :
                creditConfig.color === 'orange' ? 'text-orange-400' :
                creditConfig.color === 'yellow' ? 'text-yellow-400' :
                creditConfig.color === 'green' ? 'text-green-400' :
                'text-cyan-400'
              }`} />
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-400 font-medium">AI Credits</span>
                <div className="w-20 h-1.5 rounded-full overflow-hidden"
                     style={{
                       background: 'rgba(0, 0, 0, 0.4)',
                       border: '1px solid rgba(255, 255, 255, 0.1)'
                     }}>
                  <div 
                    className={`h-full rounded-full transition-all ${
                      creditConfig.color === 'red' ? 'bg-red-500 shadow-[0_0_10px_rgba(255,46,46,0.5)]' :
                      creditConfig.color === 'orange' ? 'bg-orange-500 shadow-[0_0_10px_rgba(255,165,0,0.5)]' :
                      creditConfig.color === 'yellow' ? 'bg-yellow-500 shadow-[0_0_10px_rgba(255,214,0,0.5)]' :
                      creditConfig.color === 'green' ? 'bg-green-500 shadow-[0_0_10px_rgba(0,255,148,0.5)]' :
                      'bg-cyan-400 shadow-[0_0_10px_rgba(0,229,255,0.5)]'
                    }`}
                    style={{ width: `${Math.min(creditBudget.usage_percent, 100)}%` }}
                  />
                </div>
                <span className="text-xs font-mono font-medium text-zinc-300">
                  {creditBudget.credits_remaining}
                </span>
              </div>
            </button>
          )}
          
          {/* Ollama Usage Indicator - COMPACT */}
          {ollamaUsage && ollamaStatus === 'online' && (
            <button
              onClick={() => setShowOllamaModal(true)}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-all hover:scale-[1.02]"
              style={{
                background: 'rgba(21, 28, 36, 0.9)',
                backdropFilter: 'blur(16px)',
                WebkitBackdropFilter: 'blur(16px)',
                border: '1px solid rgba(139, 92, 246, 0.3)',
                boxShadow: '0 2px 12px rgba(139, 92, 246, 0.1)'
              }}
              title="Click to view Ollama Pro usage"
              data-testid="ollama-usage-indicator"
            >
              <Zap className="w-4 h-4 text-purple-400" />
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-400 font-medium">Ollama Pro</span>
                <div className="w-16 h-1.5 rounded-full overflow-hidden"
                     style={{
                       background: 'rgba(0, 0, 0, 0.4)',
                       border: '1px solid rgba(255, 255, 255, 0.1)'
                     }}>
                  <div 
                    className={`h-full rounded-full transition-all ${
                      (ollamaUsage.session?.used_percent || 0) >= 70 ? 'bg-orange-500' :
                      (ollamaUsage.session?.used_percent || 0) >= 50 ? 'bg-yellow-500' :
                      'bg-purple-500 shadow-[0_0_10px_rgba(139,92,246,0.5)]'
                    }`}
                    style={{ width: `${Math.min(ollamaUsage.session?.used_percent || 0, 100)}%` }}
                  />
                </div>
                <span className="text-xs font-mono font-medium text-zinc-300">
                  {ollamaUsage.session?.requests || 0}
                </span>
              </div>
            </button>
          )}
        </div>
        
        {/* Right Side - Status Indicators */}
        <div className="flex items-center gap-3">
          {/* Consolidated System Status Popover */}
          <SystemStatusPopover
            wsConnected={wsConnected}
            wsLastUpdate={wsLastUpdate}
            connectionChecked={connectionChecked}
            isConnected={isConnected}
            connecting={connecting}
            handleConnectToIB={handleConnectToIB}
            ollamaStatus={ollamaStatus}
            ibPusherStatus={ibPusherStatus}
          />
          
          {/* Live Time Indicator */}
          <div className="hidden lg:flex items-center gap-2 text-zinc-400 text-xs font-mono">
            <div className="neon-dot" style={{width: '6px', height: '6px'}} />
            <span className="text-cyan-400 font-medium">LIVE</span>
            <span>{new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span>
          </div>
        </div>
      </div>

      {/* Credit Budget Modal */}
      <CreditBudgetModal 
        isOpen={showCreditModal} 
        onClose={() => setShowCreditModal(false)} 
        creditBudget={creditBudget}
      />
      
      {/* Ollama Usage Modal */}
      <OllamaUsageModal 
        isOpen={showOllamaModal} 
        onClose={() => setShowOllamaModal(false)} 
        ollamaUsage={ollamaUsage}
      />
    </>
  );
};

export default HeaderBar;
