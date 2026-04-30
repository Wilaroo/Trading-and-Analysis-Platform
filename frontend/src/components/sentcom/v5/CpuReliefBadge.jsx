/**
 * CpuReliefBadge — tiny UI chip that shows whether CPU-relief mode is
 * active. When ON, renders a yellow "RELIEF ON" pill with tooltip
 * showing how many calls were deferred + auto-disable time.
 *
 * Shipped 2026-05-01 (v19.21). Backed by `GET /api/ib/cpu-relief` which
 * the badge polls every 15s. Click toggles enable/disable.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Zap, ZapOff } from 'lucide-react';
import api from '../../../utils/api';

const CpuReliefBadge = ({ pollMs = 15_000 }) => {
  const [state, setState] = useState({ active: false });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get('/api/ib/cpu-relief', { timeout: 5_000 });
      setState(res?.data || { active: false });
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [refresh, pollMs]);

  const toggle = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = !state.active;
      await api.post(`/api/ib/cpu-relief?enable=${next}`);
      await refresh();
    } catch {
      // best-effort
    } finally {
      setBusy(false);
    }
  };

  const active = !!state.active;
  const Icon = active ? Zap : ZapOff;
  const tooltip = active
    ? `Relief ON · ${state.deferred_count || 0} calls deferred${
        state.until ? ` · auto-off ${new Date(state.until).toLocaleTimeString()}` : ''
      }`
    : 'CPU relief off — click to enable';

  return (
    <button
      type="button"
      data-testid="cpu-relief-badge"
      onClick={toggle}
      disabled={busy}
      title={tooltip}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md v5-mono text-[10px] uppercase tracking-widest border transition-colors ${
        active
          ? 'bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25'
          : 'bg-zinc-900 text-zinc-500 border-zinc-800 hover:text-zinc-300'
      } ${busy ? 'opacity-60' : ''}`}
    >
      <Icon className="w-3 h-3" />
      {active ? 'Relief on' : 'Relief'}
    </button>
  );
};

export default CpuReliefBadge;
