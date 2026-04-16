import React, { useState, useEffect, useCallback, memo } from 'react';
import ReactDOM from 'react-dom';
import { Activity } from 'lucide-react';
import api from '../utils/api';

/**
 * Compact inline server health badge for the SENTCOM header.
 * Shows: ping latency + thread count + status dot.
 * Click to toggle details panel.
 */
const ServerHealthBadge = memo(() => {
  const [data, setData] = useState(null);
  const [pingMs, setPingMs] = useState(null);
  const [showDetails, setShowDetails] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const fetchHealth = useCallback(async () => {
    try {
      const t0 = performance.now();
      const res = await api.get('/api/cache-status');
      const latency = Math.round(performance.now() - t0);
      setPingMs(latency);
      if (res.data) setData(res.data);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 20000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  // Close on outside click
  useEffect(() => {
    if (!showDetails) return;
    const handler = () => setShowDetails(false);
    const timer = setTimeout(() => document.addEventListener('click', handler), 50);
    return () => { clearTimeout(timer); document.removeEventListener('click', handler); };
  }, [showDetails]);

  const handleClick = useCallback((e) => {
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    setPos({
      top: rect.bottom + 6,
      left: Math.min(rect.left, window.innerWidth - 220),
    });
    setShowDetails(prev => !prev);
  }, []);

  const dotColor = !data ? 'bg-zinc-500' : pingMs < 1000 ? 'bg-emerald-500' : pingMs < 3000 ? 'bg-yellow-500' : 'bg-red-500';
  const textColor = !data ? 'text-zinc-500' : pingMs < 1000 ? 'text-emerald-400' : pingMs < 3000 ? 'text-yellow-400' : 'text-red-400';

  return (
    <>
      <button
        onClick={handleClick}
        className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-white/5 bg-black/30 hover:bg-white/5 transition-colors"
        data-testid="server-health-badge"
      >
        <div className="relative">
          <Activity className="w-3 h-3 text-zinc-500" />
          <div className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${dotColor}`} />
        </div>
        {pingMs !== null && (
          <span className={`text-[9px] font-mono font-bold ${textColor}`}>{pingMs}ms</span>
        )}
      </button>

      {showDetails && ReactDOM.createPortal(
        <div
          className="w-52 p-3 rounded-lg border border-white/10 bg-zinc-900 shadow-2xl"
          style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 99999 }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">Server Health</div>
          <div className="space-y-1.5">
            <Row label="Latency" value={pingMs !== null ? `${pingMs}ms` : '--'} color={textColor} />
            <Row label="Threads" value={data?.threads ?? '--'} warn={(data?.threads || 0) > 80} />
            <Row label="Memory" value={data?.memory_mb ? `${data.memory_mb} MB` : '--'} />
            <Row label="WS Clients" value={data?.ws_connections ?? '--'} />
            <Row label="Cache" value={data ? `${data.keys_populated}/${data.keys_total}` : '--'} />
            <Row label="Uptime" value={formatUptime(data?.uptime_seconds)} />
          </div>
          {data?.last_refresh && (
            <div className="text-[9px] text-zinc-600 mt-2 pt-2 border-t border-white/5">
              Cache: {new Date(data.last_refresh).toLocaleTimeString()}
            </div>
          )}
        </div>,
        document.body
      )}
    </>
  );
});

const Row = ({ label, value, color, warn }) => (
  <div className="flex items-center justify-between">
    <span className="text-[10px] text-zinc-500">{label}</span>
    <span className={`text-[10px] font-mono ${color || (warn ? 'text-yellow-400' : 'text-zinc-300')}`}>{value}</span>
  </div>
);

const formatUptime = (s) => {
  if (!s) return '--';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

export default ServerHealthBadge;
