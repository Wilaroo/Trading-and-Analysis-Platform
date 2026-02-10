import React, { useState, useRef } from 'react';
import {
  Target,
  Search,
  X,
  Clock,
  ArrowUpRight,
  Loader2,
  Trash2,
  Activity,
  RefreshCw,
  Database,
  WifiOff,
  Monitor,
  Sparkles
} from 'lucide-react';
import { toast } from 'sonner';

const HeaderBar = ({
  systemHealth,
  tickerSearchQuery,
  setTickerSearchQuery,
  handleTickerSearch,
  isSearching,
  recentSearches,
  clearRecentSearches,
  showAssistant,
  setShowAssistant,
  wsConnected,
  wsLastUpdate,
  connectionChecked,
  isConnected,
  connecting,
  handleConnectToIB,
  handleDisconnectFromIB,
  searchInputRef,
}) => {
  const [showRecentSearches, setShowRecentSearches] = useState(false);

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
      
      {/* Ticker Search Bar with Recent Searches */}
      <form onSubmit={handleTickerSearch} className="flex-1 max-w-md mx-4 relative">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            ref={searchInputRef}
            type="text"
            value={tickerSearchQuery}
            onChange={(e) => setTickerSearchQuery(e.target.value.toUpperCase())}
            onFocus={() => setShowRecentSearches(true)}
            onBlur={() => setTimeout(() => setShowRecentSearches(false), 200)}
            placeholder="Search any ticker (e.g., AAPL, TSLA)..."
            className="w-full pl-10 pr-4 py-2 bg-zinc-900/80 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 text-sm"
            data-testid="ticker-search-input"
          />
          {tickerSearchQuery && (
            <button
              type="button"
              onClick={() => setTickerSearchQuery('')}
              className="absolute right-10 top-1/2 -translate-y-1/2 p-1 text-zinc-500 hover:text-white"
            >
              <X className="w-3 h-3" />
            </button>
          )}
          <button
            type="submit"
            disabled={!tickerSearchQuery || isSearching}
            className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-cyan-500/20 text-cyan-400 rounded text-xs font-medium hover:bg-cyan-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="ticker-search-btn"
          >
            {isSearching ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Go'}
          </button>
        </div>
        
        {/* Recent Searches Dropdown */}
        {showRecentSearches && recentSearches.length > 0 && !tickerSearchQuery && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <span className="text-xs text-zinc-500 flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                Recent Searches
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  clearRecentSearches();
                }}
                className="text-xs text-zinc-500 hover:text-red-400 flex items-center gap-1"
              >
                <Trash2 className="w-3 h-3" />
                Clear
              </button>
            </div>
            <div className="py-1">
              {recentSearches.map((symbol, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    handleTickerSearch(null, symbol);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-white hover:bg-cyan-500/10 flex items-center gap-2 transition-colors"
                  data-testid={`recent-search-${symbol}`}
                >
                  <Search className="w-3 h-3 text-zinc-500" />
                  <span className="font-mono font-medium">{symbol}</span>
                  <ArrowUpRight className="w-3 h-3 text-zinc-600 ml-auto" />
                </button>
              ))}
            </div>
          </div>
        )}
      </form>
      
      <div className="flex items-center gap-3">
        {/* AI Assistant Button */}
        <button
          onClick={() => setShowAssistant(true)}
          className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-amber-500/20 to-cyan-500/20 text-amber-400 rounded text-sm hover:from-amber-500/30 hover:to-cyan-500/30 border border-amber-500/30"
          title="AI Trading Assistant & Coach"
          data-testid="ai-assistant-btn"
        >
          <Sparkles className="w-4 h-4" />
          <span className="hidden sm:inline">AI Assistant</span>
        </button>
        
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
