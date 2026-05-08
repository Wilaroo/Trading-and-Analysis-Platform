/**
 * DriftGuardPill — v19.34.55 (Feb 2026).
 *
 * Tiny status pill in the V5 HUD top strip showing the count of
 * phantom-close events the v19.34.52 drift guard has blocked today.
 * Each "save" is a near-miss where the share-drift reconciler was
 * about to falsely close a real position because pusher's snapshot
 * lagged the actual fill state.
 *
 * Visibility rules:
 *   - Only renders when skip_count_today > 0 (zero saves = nothing
 *     to surface; the pill stays hidden to reduce HUD clutter).
 *   - Color = emerald when skip_count_today >= 1 (good — guard
 *     working). Hover tooltip lists the most recent skips.
 *
 * Polls /api/trading-bot/drift-guard-stats every 30s.
 *
 * Sits next to BootReconcilePill in the HUD top strip.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtAgo = (ts) => {
  if (!ts) return '';
  const sec = Math.max(0, Date.now() / 1000 - ts);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
};

export default function DriftGuardPill() {
  const [data, setData] = useState(null);
  const [hover, setHover] = useState(false);
  const timer = useRef(null);

  const tick = useCallback(async () => {
    try {
      const r = await fetch(
        `${BACKEND_URL}/api/trading-bot/drift-guard-stats`,
      );
      if (!r.ok) return;
      const j = await r.json();
      if (j && j.success) setData(j);
    } catch (_) { /* decorative pill — silent on transient errors */ }
  }, []);

  useEffect(() => {
    tick();
    timer.current = setInterval(tick, 30000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [tick]);

  if (!data || !data.skip_count_today || data.skip_count_today < 1) {
    return null;
  }

  const skips = data.skip_count_today;
  const ago = fmtAgo(data.last_skip_at);
  const recent = data.recent_skips || [];

  return (
    <div
      className="relative inline-flex items-center"
      data-testid="drift-guard-pill"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div
        className="px-2 py-0.5 rounded-md text-[12px] font-mono font-semibold tabular-nums whitespace-nowrap select-none cursor-help"
        style={{
          background: 'rgba(16, 185, 129, 0.18)',
          color: '#6ee7b7',
          border: '1px solid rgba(16, 185, 129, 0.45)',
        }}
        title={`v19.34.52 drift guard prevented ${skips} phantom close(s) today. Last: ${ago}.`}
      >
        🛡 GUARD · {skips}
        <span className="opacity-60 ml-1">{ago && `· ${ago}`}</span>
      </div>

      {hover && recent.length > 0 && (
        <div
          className="absolute top-full left-0 mt-1 z-50 px-3 py-2 rounded-md shadow-xl"
          style={{
            background: 'rgba(15, 23, 42, 0.97)',
            border: '1px solid rgba(16, 185, 129, 0.35)',
            minWidth: '280px',
          }}
        >
          <div className="text-[11px] font-bold text-emerald-300 mb-1 uppercase tracking-wider">
            v19.34.52 Saves Today ({skips})
          </div>
          <div className="text-[10px] text-zinc-400 mb-2">
            Phantom closes the multi-source guard prevented.
          </div>
          <div className="flex flex-col gap-1">
            {recent.slice(-8).reverse().map((s, idx) => (
              <div
                key={`${s.ts}-${idx}`}
                className="flex justify-between text-[11px] font-mono text-zinc-300"
              >
                <span className="font-bold text-emerald-200">{s.symbol}</span>
                <span className="text-zinc-500 truncate max-w-[160px]" title={s.reason}>
                  {s.reason || s.kind}
                </span>
                <span className="text-zinc-500">{fmtAgo(s.ts)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
