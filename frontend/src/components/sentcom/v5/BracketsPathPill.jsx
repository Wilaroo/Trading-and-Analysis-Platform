/**
 * BracketsPathPill — v19.34.28 L4b
 * HUD pill showing active bracket order path (ib-direct vs pusher).
 * Reads /api/system/health → ib_gateway.metrics. No extra endpoint.
 */
import React, { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 20_000;

const VARIANTS = {
  direct_ok:   { label: 'ib-direct',   cls: 'text-emerald-400 border-emerald-400/30 bg-emerald-500/10', dot: 'bg-emerald-400' },
  direct_down: { label: 'ib-direct ⚠', cls: 'text-amber-400 border-amber-400/30 bg-amber-500/10',       dot: 'bg-amber-400 animate-pulse' },
  pusher:      { label: 'pusher',      cls: 'text-zinc-300 border-zinc-700 bg-zinc-900',                dot: 'bg-zinc-500' },
  unknown:     { label: '—',           cls: 'text-zinc-500 border-zinc-800 bg-zinc-950',                dot: 'bg-zinc-700' },
};

export const BracketsPathPill = () => {
  const [variantKey, setVariantKey] = useState('unknown');
  const [detail, setDetail] = useState('');

  const fetchHealth = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/system/health`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const ib = (data?.subsystems || []).find((s) => s.name === 'ib_gateway');
      const m = ib?.metrics || {};
      if (m.via_ib_direct === true) setVariantKey('direct_ok');
      else if (m.via_ib_direct === false && ib?.detail?.toLowerCase().includes('ib-direct')) setVariantKey('direct_down');
      else if (m.via_pusher === true) setVariantKey('pusher');
      else setVariantKey('unknown');
      setDetail(ib?.detail || '');
    } catch (e) {
      setVariantKey('unknown');
      setDetail(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const t = setInterval(fetchHealth, POLL_MS);
    return () => clearInterval(t);
  }, [fetchHealth]);

  const v = VARIANTS[variantKey];
  return (
    <span
      data-testid="brackets-path-pill"
      data-help-id="brackets-path-pill"
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[12px] v5-mono uppercase tracking-wider ${v.cls}`}
      title={detail || `Active bracket order path: ${v.label}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${v.dot}`} />
      <span className="opacity-80">brackets</span>
      <span>·</span>
      <span>{v.label}</span>
    </span>
  );
};

export default BracketsPathPill;
