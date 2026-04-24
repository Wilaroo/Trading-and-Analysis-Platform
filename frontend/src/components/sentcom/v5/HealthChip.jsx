/**
 * HealthChip — V5 HUD indicator polling /api/system/health every 20s.
 * Tiny colored dot + overall label; click → opens FreshnessInspector modal.
 */

import React, { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 20_000;

const STATUS_COLORS = {
  green: { bg: 'bg-emerald-500', text: 'text-emerald-400' },
  yellow: { bg: 'bg-amber-400', text: 'text-amber-400' },
  red: { bg: 'bg-rose-500', text: 'text-rose-400' },
};

export const HealthChip = ({ onOpenInspector }) => {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const fetchHealth = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/system/health`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setHealth(data);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const t = setInterval(fetchHealth, POLL_MS);
    return () => clearInterval(t);
  }, [fetchHealth]);

  const status = error ? 'red' : health?.overall || 'yellow';
  const colors = STATUS_COLORS[status];
  const counts = health?.counts || { green: 0, yellow: 0, red: 0 };

  const label = error
    ? 'health offline'
    : counts.red > 0
      ? `${counts.red} critical`
      : counts.yellow > 0
        ? `${counts.yellow} warn`
        : 'all systems';

  return (
    <button
      type="button"
      data-testid="health-chip"
      onClick={() => onOpenInspector?.()}
      title={error || `${status.toUpperCase()} — click for details`}
      className={`flex items-center gap-1.5 px-2 py-1 rounded hover:bg-zinc-900 transition-colors v5-mono text-[10px] ${colors.text}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${colors.bg} ${status === 'green' ? '' : 'animate-pulse'}`} />
      <span className="uppercase tracking-wide">{label}</span>
    </button>
  );
};

export default HealthChip;
