import React, { useState } from 'react';
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
  Search
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
}) => {
  const [showCreditModal, setShowCreditModal] = useState(false);

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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Target className="w-7 h-7 text-cyan-400" />
              Command Center
            </h1>
            <p className="text-zinc-500 text-sm">Real-time trading intelligence hub</p>
          </div>
          
          {/* Compact System Monitor */}
          {systemHealth && systemHealth.services && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900/50 rounded-lg border border-zinc-800" data-testid="system-health-indicator">
              <Monitor className="w-4 h-4 text-zinc-400" />
              <div className="flex items-center gap-1.5">
                {(systemHealth.services || []).slice(0, 5).map((service, idx) => {
                  const statusColor = service.status === 'healthy' ? 'bg-green-500' :
                                     service.status === 'warning' ? 'bg-yellow-500' :
                                     service.status === 'disconnected' ? 'bg-orange-500' :
                                     'bg-red-500';
                  return (
                    <div
                      key={idx}
                      className={`w-2 h-2 rounded-full ${statusColor}`}
                      title={`${service.name}: ${service.details}`}
                    />
                  );
                })}
              </div>
              <span className={`text-xs font-medium ${
                systemHealth.overall_status === 'healthy' ? 'text-green-400' :
                systemHealth.overall_status === 'partial' ? 'text-yellow-400' :
                'text-red-400'
              }`}>
                {systemHealth.summary.healthy}/{systemHealth.summary.total}
              </span>
            </div>
          )}
          
          {/* Credit Budget Indicator - Now Clickable */}
          {creditBudget && (
            <button
              onClick={() => setShowCreditModal(true)}
              className={`flex items-center gap-2 px-3 py-1.5 bg-zinc-900/50 rounded-lg border transition-all hover:bg-zinc-800/70 ${
                creditConfig.color === 'red' ? 'border-red-500/50 hover:border-red-500/70' :
                creditConfig.color === 'orange' ? 'border-orange-500/50 hover:border-orange-500/70' :
                creditConfig.color === 'yellow' ? 'border-yellow-500/50 hover:border-yellow-500/70' :
                creditConfig.color === 'green' ? 'border-green-500/30 hover:border-green-500/50' :
                'border-zinc-800 hover:border-zinc-700'
              } ${creditConfig.pulse ? 'animate-pulse' : ''}`}
              title="Click to view detailed credit usage"
              data-testid="credit-budget-indicator"
            >
              <span className={`${
                creditConfig.color === 'red' ? 'text-red-400' :
                creditConfig.color === 'orange' ? 'text-orange-400' :
                creditConfig.color === 'yellow' ? 'text-yellow-400' :
                creditConfig.color === 'green' ? 'text-green-400' :
                'text-zinc-400'
              }`}>
                {creditConfig.icon}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400">AI Credits</span>
                <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all ${
                      creditConfig.color === 'red' ? 'bg-red-500' :
                      creditConfig.color === 'orange' ? 'bg-orange-500' :
                      creditConfig.color === 'yellow' ? 'bg-yellow-500' :
                      creditConfig.color === 'green' ? 'bg-green-500' :
                      'bg-cyan-500'
                    }`}
                    style={{ width: `${Math.min(creditBudget.usage_percent, 100)}%` }}
                  />
                </div>
                <span className={`text-xs font-medium ${
                  creditConfig.color === 'red' ? 'text-red-400' :
                  creditConfig.color === 'orange' ? 'text-orange-400' :
                  creditConfig.color === 'yellow' ? 'text-yellow-400' :
                  creditConfig.color === 'green' ? 'text-green-400' :
                  'text-zinc-300'
                }`}>
                  {creditBudget.credits_remaining}
                </span>
              </div>
            </button>
          )}
        </div>
        
        {/* Ticker Search Bar removed - integrated into AI Command Center */}
        
        <div className="flex items-center gap-3">
          {/* Dual Connection Status Indicator */}
          <div className="flex items-center gap-2">
            {/* WebSocket Status */}
            <div 
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${
                wsConnected 
                  ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' 
                  : 'bg-orange-500/10 text-orange-400 border-orange-500/30 animate-pulse'
              }`}
              title={wsConnected 
                ? `Quotes streaming active${wsLastUpdate ? ` (Last: ${new Date(wsLastUpdate).toLocaleTimeString()})` : ''}`
                : 'Quotes streaming reconnecting...'
              }
              data-testid="ws-status"
            >
              {wsConnected ? (
                <>
                  <Activity className="w-3 h-3" />
                  <span className="hidden md:inline">Quotes</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                </>
              ) : (
                <>
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  <span className="hidden md:inline">Reconnecting</span>
                </>
              )}
            </div>
            
            {/* IB Gateway Status */}
            <div 
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${
                !connectionChecked ? 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30' :
                isConnected ? 'bg-green-500/10 text-green-400 border-green-500/30' : 
                'bg-red-500/10 text-red-400 border-red-500/30'
              }`}
              title={
                !connectionChecked ? 'Checking IB Gateway connection...' :
                isConnected ? 'IB Gateway connected - Trading & scanners available' : 
                'IB Gateway disconnected - Connect to enable trading'
              }
              data-testid="ib-status"
            >
              {!connectionChecked ? (
                <>
                  <div className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin" />
                  <span className="hidden md:inline">Checking</span>
                </>
              ) : isConnected ? (
                <>
                  <Database className="w-3 h-3" />
                  <span className="hidden md:inline">IB Gateway</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  <span className="hidden md:inline">IB Gateway</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                </>
              )}
            </div>
            
            {/* Connect/Disconnect Button - Shows "Reconnect" since auto-connect is enabled */}
            {connectionChecked && !isConnected && (
              <button
                onClick={handleConnectToIB}
                disabled={connecting}
                className="px-3 py-1.5 rounded font-medium text-xs transition-colors bg-cyan-500 text-black hover:bg-cyan-400 disabled:opacity-50"
                data-testid="reconnect-btn"
              >
                {connecting ? 'Connecting...' : 'Reconnect'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Credit Budget Modal */}
      <CreditBudgetModal 
        isOpen={showCreditModal} 
        onClose={() => setShowCreditModal(false)} 
        creditBudget={creditBudget}
      />
    </>
  );
};

export default HeaderBar;
