import React from 'react';
import {
  Target,
  Activity,
  RefreshCw,
  Database,
  WifiOff,
  Monitor,
  Sparkles
} from 'lucide-react';

const HeaderBar = ({
  systemHealth,
  onNavigateToCoach,
  wsConnected,
  wsLastUpdate,
  connectionChecked,
  isConnected,
  connecting,
  handleConnectToIB,
  handleDisconnectFromIB,
}) => {

  return (
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
        {systemHealth && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900/50 rounded-lg border border-zinc-800" data-testid="system-health-indicator">
            <Monitor className="w-4 h-4 text-zinc-400" />
            <div className="flex items-center gap-1.5">
              {systemHealth.services.slice(0, 5).map((service, idx) => {
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
          
          {/* Connect/Disconnect Button */}
          {connectionChecked && (
            <button
              onClick={isConnected ? handleDisconnectFromIB : handleConnectToIB}
              disabled={connecting}
              className={`px-3 py-1.5 rounded font-medium text-xs transition-colors ${
                isConnected 
                  ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30' 
                  : 'bg-cyan-500 text-black hover:bg-cyan-400'
              } disabled:opacity-50`}
              data-testid="connect-btn"
            >
              {connecting ? '...' : isConnected ? 'Disconnect' : 'Connect'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default HeaderBar;
