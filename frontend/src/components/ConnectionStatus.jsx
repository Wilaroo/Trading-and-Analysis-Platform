/**
 * ConnectionStatus - Visual indicator for connection health
 * ==========================================================
 * 
 * Shows a minimal indicator when connections are healthy,
 * and expands to show details when there are issues.
 */

import React, { useState } from 'react';
import { Wifi, WifiOff, Database, Activity, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { useConnectionManager } from '../contexts/ConnectionManagerContext';
import { useAppState } from '../contexts/AppStateContext';

const ConnectionStatus = () => {
  const { wsConnected, ibConnected, backendConnected, reconnectAll } = useConnectionManager();
  const { hasConnectionIssue } = useAppState();
  const [expanded, setExpanded] = useState(false);
  
  const allHealthy = wsConnected && ibConnected && backendConnected;
  const hasIssue = hasConnectionIssue() || !allHealthy;
  
  // Minimal indicator when all healthy
  if (allHealthy && !expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="fixed bottom-4 left-4 z-40 flex items-center gap-1.5 px-2 py-1 
                   bg-green-500/20 border border-green-500/30 rounded-full
                   text-green-400 text-xs hover:bg-green-500/30 transition-colors"
        title="All connections healthy"
        data-testid="connection-status-healthy"
      >
        <Wifi className="w-3 h-3" />
        <span className="hidden sm:inline">Connected</span>
      </button>
    );
  }
  
  // Expanded view or when there are issues
  return (
    <div 
      className={`fixed bottom-4 left-4 z-40 rounded-lg border transition-all
        ${hasIssue 
          ? 'bg-red-500/10 border-red-500/30' 
          : 'bg-zinc-800/90 border-zinc-700'
        }`}
      data-testid="connection-status-panel"
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-2 w-full text-left"
      >
        {hasIssue ? (
          <WifiOff className="w-4 h-4 text-red-400 animate-pulse" />
        ) : (
          <Wifi className="w-4 h-4 text-green-400" />
        )}
        <span className={`text-sm font-medium ${hasIssue ? 'text-red-400' : 'text-zinc-300'}`}>
          {hasIssue ? 'Connection Issues' : 'Connections'}
        </span>
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-500 ml-auto" />
        ) : (
          <ChevronUp className="w-4 h-4 text-zinc-500 ml-auto" />
        )}
      </button>
      
      {/* Details */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-zinc-700/50 pt-2">
          {/* WebSocket */}
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <Activity className={`w-3 h-3 ${wsConnected ? 'text-green-400' : 'text-red-400'}`} />
              <span className="text-zinc-400">Real-time Data</span>
            </div>
            <span className={wsConnected ? 'text-green-400' : 'text-red-400'}>
              {wsConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          
          {/* IB Gateway */}
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <Activity className={`w-3 h-3 ${ibConnected ? 'text-green-400' : 'text-yellow-400'}`} />
              <span className="text-zinc-400">IB Gateway</span>
            </div>
            <span className={ibConnected ? 'text-green-400' : 'text-yellow-400'}>
              {ibConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          
          {/* Backend */}
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <Database className={`w-3 h-3 ${backendConnected ? 'text-green-400' : 'text-red-400'}`} />
              <span className="text-zinc-400">Backend</span>
            </div>
            <span className={backendConnected ? 'text-green-400' : 'text-red-400'}>
              {backendConnected ? 'Healthy' : 'Unreachable'}
            </span>
          </div>
          
          {/* Reconnect button */}
          {hasIssue && (
            <button
              onClick={reconnectAll}
              className="flex items-center justify-center gap-2 w-full mt-2 px-3 py-1.5
                       bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30
                       rounded text-blue-400 text-xs transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              Reconnect All
            </button>
          )}
          
          {/* Close button when healthy */}
          {!hasIssue && (
            <button
              onClick={() => setExpanded(false)}
              className="text-xs text-zinc-500 hover:text-zinc-400 w-full text-center pt-1"
            >
              Close
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default ConnectionStatus;
