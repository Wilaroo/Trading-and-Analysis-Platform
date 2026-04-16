import React, { useState, useEffect, useCallback, memo } from 'react';
import { Activity, Cpu, Database, Wifi, Clock, ChevronDown } from 'lucide-react';
import api from '../../utils/api';

const ServerHealthWidget = memo(() => {
  const [data, setData] = useState(null);
  const [pingMs, setPingMs] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState(false);

  const fetchHealth = useCallback(async () => {
    try {
      const t0 = performance.now();
      const res = await api.get('/api/cache-status');
      const latency = Math.round(performance.now() - t0);
      setPingMs(latency);
      if (res.data) {
        setData(res.data);
        setError(false);
      }
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 15000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  const formatUptime = (s) => {
    if (!s) return '--';
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  };

  const getLatencyColor = (ms) => {
    if (!ms) return 'text-zinc-500';
    if (ms < 500) return 'text-emerald-400';
    if (ms < 2000) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getStatusDot = () => {
    if (error) return 'bg-red-500';
    if (!data) return 'bg-zinc-500';
    if (pingMs < 1000) return 'bg-emerald-500';
    return 'bg-yellow-500';
  };

  return (
    <div className="rounded-lg border border-white/[0.06] overflow-hidden" style={{ background: 'rgba(16, 20, 26, 0.9)' }} data-testid="server-health-widget">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/[0.03] transition-colors"
        data-testid="server-health-toggle"
      >
        <div className="flex items-center gap-2">
          <div className="relative">
            <Activity className="w-3.5 h-3.5 text-zinc-400" />
            <div className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${getStatusDot()}`} />
          </div>
          <span className="text-xs font-medium text-zinc-300">Server</span>
          {pingMs !== null && (
            <span className={`text-[10px] font-mono ${getLatencyColor(pingMs)}`}>{pingMs}ms</span>
          )}
          {data?.threads && (
            <span className="text-[10px] font-mono text-zinc-500">{data.threads}T</span>
          )}
          {data?.loop === 'uvloop' && (
            <span className="text-[10px] px-1 rounded bg-cyan-500/10 text-cyan-400 font-medium">uv</span>
          )}
        </div>
        <ChevronDown className={`w-3 h-3 text-zinc-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-white/[0.04] pt-2 space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <MetricRow icon={Clock} label="Uptime" value={formatUptime(data?.uptime_seconds)} />
            <MetricRow icon={Cpu} label="Threads" value={data?.threads ?? '--'} warn={data?.threads > 80} />
            <MetricRow icon={Database} label="Memory" value={data?.memory_mb ? `${data.memory_mb} MB` : '--'} />
            <MetricRow icon={Wifi} label="WS Clients" value={data?.ws_connections ?? '--'} />
            <MetricRow icon={Activity} label="Latency" value={pingMs !== null ? `${pingMs}ms` : '--'} color={getLatencyColor(pingMs)} />
            <MetricRow icon={Database} label="Cache" value={data ? `${data.keys_populated}/${data.keys_total}` : '--'} />
          </div>

          {data?.last_refresh && (
            <div className="text-[10px] text-zinc-600 text-right">
              Cache: {new Date(data.last_refresh).toLocaleTimeString()}
              {data?.loop && ` | Loop: ${data.loop}`}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

const MetricRow = ({ icon: Icon, label, value, warn, color }) => (
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-1.5">
      <Icon className="w-3 h-3 text-zinc-500" />
      <span className="text-[11px] text-zinc-500">{label}</span>
    </div>
    <span className={`text-[11px] font-mono ${color || (warn ? 'text-yellow-400' : 'text-zinc-300')}`}>
      {value}
    </span>
  </div>
);

export default ServerHealthWidget;
