/**
 * SystemStatusBar - Unified System Status Display
 * ================================================
 * 
 * Single, consolidated status display for all services.
 * Shows in the header area, visible across all tabs.
 * 
 * Features:
 * - Compact view: Just overall health indicator
 * - Expanded view: All service details
 * - One-click reconnect actions
 * - Auto-updates every 30 seconds
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Wifi, WifiOff, Database, Activity, Server, Brain, 
  ChevronDown, ChevronUp, RefreshCw, CheckCircle2, XCircle, 
  AlertCircle, Loader2
} from 'lucide-react';
import { useSystemStatus } from '../contexts/SystemStatusContext';
import StatusDot from './StatusDot';

// Service icons
const SERVICE_ICONS = {
  quotesStream: Activity,
  ibGateway: Wifi,
  ibDataPusher: Server,
  ollama: Brain,
  backend: Server,
  mongodb: Database,
};

const SystemStatusBar = ({ compact = false }) => {
  const [expanded, setExpanded] = useState(false);
  const { statuses, SERVICES, STATUS, checkAllServices, getOverallHealth } = useSystemStatus();
  const [refreshing, setRefreshing] = useState(false);
  
  const overallHealth = getOverallHealth();
  
  // Count connected services
  const connectedCount = Object.values(statuses).filter(s => s.status === STATUS.CONNECTED).length;
  const totalCount = Object.keys(SERVICES).length;
  
  // Overall status display
  const healthConfig = {
    healthy: { label: 'All Systems', color: 'text-green-400', bg: 'bg-green-500/20', border: 'border-green-500/30', icon: CheckCircle2 },
    degraded: { label: 'Partial', color: 'text-yellow-400', bg: 'bg-yellow-500/20', border: 'border-yellow-500/30', icon: AlertCircle },
    connecting: { label: 'Connecting', color: 'text-blue-400', bg: 'bg-blue-500/20', border: 'border-blue-500/30', icon: Loader2 },
    unknown: { label: 'Checking', color: 'text-zinc-400', bg: 'bg-zinc-500/20', border: 'border-zinc-500/30', icon: Loader2 },
  };
  
  const health = healthConfig[overallHealth] || healthConfig.unknown;
  const HealthIcon = health.icon;
  
  const handleRefresh = async () => {
    setRefreshing(true);
    await checkAllServices();
    setTimeout(() => setRefreshing(false), 500);
  };
  
  // Compact mode - just a small indicator
  if (compact) {
    return (
      <button
        onClick={() => setExpanded(!expanded)}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-lg ${health.bg} ${health.border} border transition-colors hover:opacity-80`}
        title={`System Status: ${health.label} (${connectedCount}/${totalCount} services)`}
      >
        <StatusDot status={overallHealth === 'healthy' ? 'connected' : 'disconnected'} size="sm" />
        <span className={`text-xs font-medium ${health.color}`}>{connectedCount}/{totalCount}</span>
      </button>
    );
  }
  
  return (
    <div className="relative">
      {/* Trigger Button */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${health.bg} ${health.border} border transition-all hover:opacity-90`}
        data-testid="system-status-trigger"
      >
        <HealthIcon className={`w-4 h-4 ${health.color} ${overallHealth === 'connecting' || overallHealth === 'unknown' ? 'animate-spin' : ''}`} />
        <span className={`text-sm font-medium ${health.color}`}>{health.label}</span>
        <span className="text-xs text-zinc-500">({connectedCount}/{totalCount})</span>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-zinc-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-zinc-500" />
        )}
      </button>
      
      {/* Expanded Panel */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full right-0 mt-2 w-72 bg-zinc-900/95 backdrop-blur-sm border border-zinc-700 rounded-lg shadow-xl z-50"
            data-testid="system-status-panel"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/50">
              <span className="text-sm font-medium text-zinc-200">System Status</span>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="p-1.5 rounded hover:bg-zinc-700/50 text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-50"
                title="Refresh all statuses"
              >
                <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>
            
            {/* Services List */}
            <div className="p-2 space-y-1">
              {Object.entries(SERVICES).map(([serviceId, service]) => {
                const status = statuses[serviceId] || { status: STATUS.UNKNOWN };
                const isConnected = status.status === STATUS.CONNECTED;
                const Icon = SERVICE_ICONS[serviceId] || Server;
                
                return (
                  <div
                    key={serviceId}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg transition-colors
                      ${isConnected ? 'bg-green-500/5' : 'bg-red-500/5'}`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon className={`w-4 h-4 ${isConnected ? 'text-green-400' : 'text-red-400'}`} />
                      <div>
                        <div className={`text-sm ${isConnected ? 'text-zinc-200' : 'text-zinc-400'}`}>
                          {service.name}
                        </div>
                        {status.message && (
                          <div className="text-xs text-zinc-500">{status.message}</div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isConnected ? (
                        <CheckCircle2 className="w-4 h-4 text-green-400" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-400" />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            
            {/* Footer */}
            <div className="px-4 py-2 border-t border-zinc-700/50 text-xs text-zinc-500">
              Last checked: {new Date().toLocaleTimeString()}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SystemStatusBar;
