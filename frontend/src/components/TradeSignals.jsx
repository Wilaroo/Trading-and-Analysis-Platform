/**
 * TradeSignals - Compact unified trade signal feed
 * Replaces LiveAlertsPanel - connects to SSE background scanner
 * Shows real-time signals in a compact horizontal strip
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Radio, Zap, TrendingUp, TrendingDown, Settings, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import api from '../utils/api';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

const SETUP_COLORS = {
  rubber_band: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  vwap_bounce: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  breakout: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  squeeze: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  trend_continuation: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
};

const TradeSignals = ({ onSignalSelect, isExpanded = false, onToggleExpand }) => {
  const [signals, setSignals] = useState([]);
  const [connected, setConnected] = useState(false);
  const [scanCount, setScanCount] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState(null);
  const eventSourceRef = useRef(null);

  // Connect to SSE stream
  const connectToStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const eventSource = new EventSource(`${API_URL}/api/live-scanner/stream-alerts`);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => setConnected(true);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'scan_complete') {
          setScanCount(prev => prev + 1);
        } else if (data.type === 'alert') {
          const newSignal = {
            id: `${data.symbol}_${Date.now()}`,
            symbol: data.symbol,
            setup: data.setup_type || data.pattern || 'unknown',
            direction: data.direction || 'LONG',
            price: data.current_price || data.price || 0,
            score: data.quality_score || data.score || 0,
            grade: data.quality_grade || data.grade || '',
            message: data.message || data.explanation || '',
            timestamp: data.timestamp || new Date().toISOString(),
            priority: data.priority || 'medium'
          };
          setSignals(prev => [newSignal, ...prev].slice(0, 30));
        }
      } catch (err) {
        // ignore parse errors
      }
    };

    eventSource.onerror = () => {
      setConnected(false);
      setTimeout(() => {
        if (eventSourceRef.current === eventSource) {
          connectToStream();
        }
      }, 5000);
    };

    return () => eventSource.close();
  }, []);

  useEffect(() => {
    const cleanup = connectToStream();
    // Fetch existing alerts
    api.get('/api/live-scanner/alerts').then(res => {
      if (res.data?.alerts) setSignals(res.data.alerts.slice(0, 30));
    }).catch(() => {});
    // Fetch status
    api.get('/api/live-scanner/status').then(res => {
      if (res.data) setStatus(res.data);
    }).catch(() => {});
    return cleanup;
  }, [connectToStream]);

  const signalCount = signals.length;

  return (
    <div className="bg-[#0d0d0d] border border-white/10 rounded-xl" data-testid="trade-signals">
      {/* Compact Header */}
      <div
        className="flex items-center justify-between px-4 py-2.5 cursor-pointer"
        onClick={onToggleExpand}
        data-testid="trade-signals-header"
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Radio className={`w-4 h-4 ${connected ? 'text-emerald-400' : 'text-zinc-600'}`} />
            <span className="text-sm font-semibold text-white">Trade Signals</span>
          </div>
          {connected && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              Live
            </span>
          )}
          <span className="text-[10px] text-zinc-500">
            {scanCount} scans | {signalCount} signals
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Scrolling signal ticker when collapsed */}
          {!isExpanded && signalCount > 0 && (
            <div className="flex items-center gap-2 overflow-hidden max-w-[500px]">
              {signals.slice(0, 5).map((s, i) => (
                <button
                  key={s.id || i}
                  onClick={(e) => { e.stopPropagation(); onSignalSelect?.(s); }}
                  className="flex items-center gap-1.5 px-2 py-1 rounded bg-zinc-800/80 hover:bg-zinc-700/80 transition-colors shrink-0"
                  data-testid={`signal-chip-${s.symbol}`}
                >
                  <span className="text-xs font-bold text-white">{s.symbol}</span>
                  <span className={`text-[10px] ${s.direction === 'LONG' || s.direction === 'long' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {s.direction === 'LONG' || s.direction === 'long' ? '▲' : '▼'}
                  </span>
                  <span className={`text-[9px] px-1 py-0.5 rounded ${SETUP_COLORS[s.setup] || 'bg-zinc-700 text-zinc-300'}`}>
                    {s.setup?.replace(/_/g, ' ').split(' ').map(w => w[0]?.toUpperCase()).join('')}
                  </span>
                </button>
              ))}
            </div>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); setShowSettings(!showSettings); }}
            className="p-1 hover:bg-zinc-700 rounded"
          >
            <Settings className="w-3.5 h-3.5 text-zinc-500" />
          </button>
          {isExpanded ? <ChevronDown className="w-4 h-4 text-zinc-500" /> : <ChevronRight className="w-4 h-4 text-zinc-500" />}
        </div>
      </div>

      {/* Scanner Settings (collapsible) */}
      {showSettings && (
        <div className="px-4 py-2 border-t border-white/5 flex items-center gap-3 text-[11px] text-zinc-400">
          <span>Watchlist: {status?.watchlist_size || 15} symbols</span>
          <span>Interval: {status?.scan_interval || 90}s</span>
          <span>Setups: {status?.setup_count || 4}</span>
          {connected && <span className="text-emerald-400">Connected</span>}
        </div>
      )}

      {/* Expanded Signal List */}
      {isExpanded && (
        <div className="border-t border-white/5 max-h-[280px] overflow-y-auto">
          {signalCount > 0 ? signals.slice(0, 15).map((signal, idx) => (
            <div
              key={signal.id || idx}
              className="flex items-center justify-between px-4 py-2 hover:bg-zinc-800/50 cursor-pointer border-b border-white/5 last:border-0"
              onClick={() => onSignalSelect?.(signal)}
              data-testid={`signal-row-${signal.symbol}`}
            >
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  {signal.direction === 'LONG' || signal.direction === 'long'
                    ? <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                    : <TrendingDown className="w-3.5 h-3.5 text-red-400" />
                  }
                  <span className="text-sm font-bold text-white">{signal.symbol}</span>
                </div>
                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${SETUP_COLORS[signal.setup] || 'bg-zinc-700 text-zinc-300 border-zinc-600'}`}>
                  {signal.setup?.replace(/_/g, ' ')}
                </span>
                {signal.grade && (
                  <span className={`text-[10px] px-1 py-0.5 rounded font-semibold ${
                    signal.grade?.startsWith('A') ? 'bg-emerald-500/20 text-emerald-400' :
                    signal.grade?.startsWith('B') ? 'bg-cyan-500/20 text-cyan-400' :
                    'bg-zinc-600/30 text-zinc-400'
                  }`}>{signal.grade}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {signal.price > 0 && (
                  <span className="text-xs font-mono text-zinc-300">${signal.price.toFixed(2)}</span>
                )}
                <span className="text-[10px] text-zinc-600">
                  {signal.timestamp ? new Date(signal.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                </span>
              </div>
            </div>
          )) : (
            <div className="text-center py-6 text-zinc-500">
              <Zap className="w-6 h-6 mx-auto mb-1.5 opacity-40" />
              <p className="text-xs">No signals yet</p>
              <p className="text-[10px] mt-0.5">Scanner is analyzing the market...</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default TradeSignals;
