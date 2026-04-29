import React, { useState, useEffect, useCallback, memo } from 'react';
import { Activity } from 'lucide-react';
import api from '../utils/api';

/**
 * Compact inline server health badge — always shows key metrics, no click needed.
 */
const ServerHealthBadge = memo(() => {
  const [data, setData] = useState(null);
  const [pingMs, setPingMs] = useState(null);

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

  const dotColor = !data ? 'bg-zinc-500' : (data.status === 'healthy') ? 'bg-emerald-500' : 'bg-yellow-500';
  const latencyColor = !pingMs ? 'text-zinc-500' : pingMs < 500 ? 'text-emerald-400' : pingMs < 2000 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-white/5 bg-black/30"
      data-testid="server-health-badge"
      title={data ? `Threads: ${data.threads} | Mem: ${data.memory_mb}MB | Cache: ${data.keys_populated}/${data.keys_total} | WS: ${data.ws_connections}` : 'Loading...'}
    >
      <div className="relative">
        <Activity className="w-3 h-3 text-zinc-500" />
        <div className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${dotColor}`} />
      </div>
      {pingMs !== null && (
        <span className={`text-[11px] font-mono font-bold ${latencyColor}`}>{pingMs}ms</span>
      )}
      {data?.threads && (
        <span className={`text-[11px] font-mono ${data.threads > 80 ? 'text-yellow-400' : 'text-zinc-500'}`}>{data.threads}T</span>
      )}
      {data?.memory_mb && (
        <span className="text-[11px] font-mono text-zinc-600">{data.memory_mb > 1024 ? `${(data.memory_mb/1024).toFixed(1)}G` : `${Math.round(data.memory_mb)}M`}</span>
      )}
    </div>
  );
});

export default ServerHealthBadge;
