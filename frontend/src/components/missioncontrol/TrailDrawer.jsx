/**
 * TrailDrawer — v19.34.184. Slide-over for the inline "click a live event →
 * see what this symbol has been doing" action. Lists the symbol's recent
 * decisions (from the Diagnostics decision API) with outcome + P&L + setup.
 */
import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtPnl = (n) => {
  const v = Number(n) || 0;
  return `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`;
};

const OUTCOME_CLS = {
  win: 'text-emerald-400', loss: 'text-rose-400', open: 'text-cyan-400',
  scratch: 'text-zinc-400',
};

export const TrailDrawer = ({ symbol, onClose }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) return undefined;
    let cancelled = false;
    setLoading(true); setError(null);
    fetch(`${BACKEND_URL}/api/diagnostics/recent-decisions?symbol=${encodeURIComponent(symbol)}&limit=10`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setRows(d?.rows || []); })
      .catch((e) => { if (!cancelled) setError(String(e?.message || e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  if (!symbol) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="mc-trail-drawer">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-[420px] max-w-[92vw] h-full bg-zinc-950 border-l border-zinc-800 flex flex-col shadow-2xl">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <div>
            <span className="font-mono text-lg text-zinc-100 font-bold">{symbol}</span>
            <span className="ml-2 text-[12px] text-zinc-500">recent decisions</span>
          </div>
          <button type="button" data-testid="mc-trail-drawer-close" onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && <div className="text-xs text-zinc-500">Loading…</div>}
          {error && <div className="text-xs text-rose-400">⚠ {error}</div>}
          {!loading && !error && rows.length === 0 && (
            <div className="text-xs text-zinc-500">No recorded decisions for {symbol} (it may have only been scanned/filtered, not evaluated).</div>
          )}
          {rows.map((r) => (
            <div key={r.identifier} data-testid={`mc-trail-decision-${r.identifier}`}
                 className="border border-zinc-800 rounded p-2 bg-zinc-900/40">
              <div className="flex items-center justify-between">
                <span className={`text-[12px] uppercase font-bold ${OUTCOME_CLS[(r.outcome || '').toLowerCase()] || 'text-zinc-400'}`}>
                  {(r.outcome || '?').toUpperCase()} · {r.has_trade ? 'trade' : 'shadow'}
                </span>
                <span className={`text-[12px] font-mono ${(r.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPnl(r.pnl)}</span>
              </div>
              <div className="text-[12px] text-zinc-500 mt-1">{r.setup || '—'}</div>
              <div className="text-[11px] text-zinc-600 mt-0.5">{(r.scanned_at || '').replace('T', ' ').slice(0, 19)}</div>
            </div>
          ))}
        </div>
        <div className="px-4 py-2 border-t border-zinc-800 text-[11px] text-zinc-600">
          Full trail (alert → AI votes → action → thoughts) lives in the Diagnostics → Trail Explorer tab.
        </div>
      </div>
    </div>
  );
};

export default TrailDrawer;
