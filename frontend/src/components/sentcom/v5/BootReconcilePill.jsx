/**
 * BootReconcilePill — v19.31.14 (2026-05-04)
 *
 * Tiny status pill in the V5 HUD top strip showing the result of the
 * boot-time auto-reconcile (when AUTO_RECONCILE_AT_BOOT=true). Renders:
 *
 *   🔁 Auto-claimed 5  · 4m 12s ago   (cyan, when reconciled_count > 0)
 *   🔁 Boot OK · nothing to claim     (slate, when reconciled_count == 0)
 *
 * Auto-hides after `pill_visible_seconds` (default 600s = 10 min) so it
 * doesn't permanently clutter the strip. Polls /api/trading-bot/boot-
 * reconcile-status once on mount, then every 60s while visible.
 *
 * Rendered next to AccountModeBadge in the HUD top strip.
 */
import React, { useEffect, useState, useRef, useCallback } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtAgo = (s) => {
  if (s == null) return '';
  if (s < 60) return `${Math.floor(s)}s ago`;
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  if (m < 60) return sec ? `${m}m ${sec}s ago` : `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
};

export default function BootReconcilePill() {
  const [data, setData] = useState(null);
  const timer = useRef(null);

  const tick = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/trading-bot/boot-reconcile-status`);
      if (!r.ok) return;
      const j = await r.json();
      setData(j);
    } catch (_) { /* silent: pill is decorative only */ }
  }, []);

  useEffect(() => {
    tick();
    timer.current = setInterval(tick, 60000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [tick]);

  if (!data || !data.show_pill) return null;

  const claimed = Number(data.reconciled_count) || 0;
  const ago = fmtAgo(data.age_seconds);

  // Two distinct states:
  //   claimed > 0 → cyan "auto-claimed N"
  //   claimed == 0 → slate "boot ok · nothing to claim"
  const cls = claimed > 0
    ? 'bg-cyan-950/60 text-cyan-300 border-cyan-800 hover:border-cyan-600'
    : 'bg-slate-900/80 text-slate-400 border-slate-800 hover:border-slate-600';

  const label = claimed > 0
    ? `🔁 Auto-claimed ${claimed}`
    : '🔁 Boot OK · 0 claims';

  const tooltipLines = [
    claimed > 0
      ? `Auto-reconcile at boot claimed ${claimed} orphan position(s)`
      : 'Auto-reconcile at boot found nothing to claim',
    `Skipped: ${data.skipped_count} · Errors: ${data.errors_count}`,
    data.ran_at ? `Ran at: ${data.ran_at}` : '',
    data.symbols && data.symbols.length
      ? `Symbols: ${data.symbols.slice(0, 8).join(', ')}${data.symbols.length > 8 ? ` (+${data.symbols.length - 8} more)` : ''}`
      : '',
    `Pill auto-hides after ${data.pill_visible_seconds}s`,
  ].filter(Boolean);

  return (
    <span
      data-testid="boot-reconcile-pill"
      data-claimed={claimed}
      data-age-s={data.age_seconds}
      title={tooltipLines.join('\n')}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border ${cls} transition-colors cursor-help`}
    >
      <span data-testid="boot-reconcile-pill-label">{label}</span>
      {ago && (
        <span
          data-testid="boot-reconcile-pill-age"
          className="font-mono opacity-70 normal-case tracking-normal"
        >
          · {ago}
        </span>
      )}
    </span>
  );
}
