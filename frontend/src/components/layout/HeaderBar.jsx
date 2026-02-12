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
      <div className="flex items-center justify-between p-3 rounded-xl"
           style={{
             background: 'rgba(21, 28, 36, 0.9)',
             backdropFilter: 'blur(24px)',
             WebkitBackdropFilter: 'blur(24px)',
             border: '1px solid rgba(255, 255, 255, 0.1)',
             boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
             position: 'relative',
             overflow: 'hidden'
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
          
          {/* Credit Budget Indicator - Dark Glass Style */}
          {creditBudget && (
            <button
              onClick={() => setShowCreditModal(true)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all hover:scale-[1.02] ${
                creditConfig.pulse ? 'animate-pulse' : ''
              }`}
              style={{
                background: 'rgba(21, 28, 36, 0.9)',
                backdropFilter: 'blur(16px)',
                WebkitBackdropFilter: 'blur(16px)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)'
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
                <div className="w-24 h-2 rounded-full overflow-hidden"
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
        </div>
        
        {/* Right Side - Status Indicators */}
        <div className="flex items-center gap-3">
          {/* WebSocket Status - Neon Style */}
          <div 
            className={`status-indicator ${wsConnected ? 'online' : 'connecting'}`}
            title={wsConnected 
              ? `Quotes streaming active${wsLastUpdate ? ` (Last: ${new Date(wsLastUpdate).toLocaleTimeString()})` : ''}`
              : 'Quotes streaming reconnecting...'
            }
            data-testid="ws-status"
          >
            {wsConnected ? (
              <>
                <Activity className="w-3.5 h-3.5" />
                <span className="hidden md:inline font-medium">Quotes</span>
                <span className="neon-dot-success" style={{width: '6px', height: '6px'}} />
              </>
            ) : (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span className="hidden md:inline font-medium">Reconnecting</span>
              </>
            )}
          </div>
          
          {/* IB Gateway Status - Neon Style */}
          <div 
            className={`status-indicator ${
              !connectionChecked ? '' :
              isConnected ? 'online' : 'offline'
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
                <div className="w-3.5 h-3.5 border-2 border-zinc-400 border-t-transparent rounded-full animate-spin" />
                <span className="hidden md:inline font-medium">Checking</span>
              </>
            ) : isConnected ? (
              <>
                <Database className="w-3.5 h-3.5" />
                <span className="hidden md:inline font-medium">IB Gateway</span>
                <span className="neon-dot-success" style={{width: '6px', height: '6px'}} />
              </>
            ) : (
              <>
                <WifiOff className="w-3.5 h-3.5" />
                <span className="hidden md:inline font-medium">IB Gateway</span>
                <span className="neon-dot-error" style={{width: '6px', height: '6px'}} />
              </>
            )}
          </div>
          
          {/* Reconnect Button - Neon Style */}
          {connectionChecked && !isConnected && (
            <button
              onClick={handleConnectToIB}
              disabled={connecting}
              className="btn-primary text-xs py-1.5 px-4"
              data-testid="reconnect-btn"
            >
              {connecting ? 'Connecting...' : 'Reconnect'}
            </button>
          )}
          
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
    </>
  );
};

export default HeaderBar;
