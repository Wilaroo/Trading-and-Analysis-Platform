/**
 * SafetyRow — v19.34.186. A System/Safety strip line with inline actions:
 *   • alarm rows get an "Ack + Unlock" button → POST /api/safety/reset-kill-switch
 *     (the real operator acknowledgement that re-arms trading)
 *   • any row can be dismissed (muted) locally
 */
import React, { useState } from 'react';
import { ShieldCheck, X } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtClock = (iso) => {
  if (!iso) return '--:--:--';
  try { return new Date(iso).toLocaleTimeString('en-US', { hour12: false }); }
  catch { return '--:--:--'; }
};

export const SafetyRow = ({ ev, onDismiss }) => {
  const [acking, setAcking] = useState(false);
  const [acked, setAcked] = useState(false);
  const [err, setErr] = useState(null);
  const isAlarm = ev.severity === 'alarm';

  const ack = async () => {
    setAcking(true); setErr(null);
    try {
      const r = await fetch(`${BACKEND_URL}/api/safety/reset-kill-switch`, { method: 'POST' });
      const d = await r.json();
      if (d?.success) setAcked(true); else setErr('failed');
    } catch (e) { setErr('error'); } finally { setAcking(false); }
  };

  return (
    <div
      data-testid={`mc-safety-row-${ev.id || ev.timestamp}`}
      className="px-3 py-1.5 border-b border-zinc-900 flex items-center gap-2 hover:bg-zinc-900/30"
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isAlarm ? 'bg-rose-500 animate-pulse' : 'bg-cyan-600'}`} />
      <span className="text-[11px] text-zinc-600 font-mono shrink-0">{fmtClock(ev.timestamp)}</span>
      {ev.symbol && <span className="text-[12px] font-mono font-bold text-zinc-100 shrink-0">{ev.symbol}</span>}
      <span className="text-[12px] text-zinc-400 flex-1 break-words min-w-0">{ev.text}</span>
      {isAlarm && !acked && (
        <button
          type="button"
          data-testid="mc-safety-ack"
          onClick={ack}
          disabled={acking}
          className="shrink-0 px-2 py-0.5 text-[11px] rounded border border-rose-700 text-rose-300 hover:bg-rose-900/40 disabled:opacity-50 flex items-center gap-1"
        >
          <ShieldCheck size={11} /> {acking ? 'Unlocking…' : 'Ack + Unlock'}
        </button>
      )}
      {acked && <span className="text-[11px] text-emerald-400 shrink-0">✓ acknowledged</span>}
      {err && <span className="text-[11px] text-rose-400 shrink-0">⚠ {err}</span>}
      <button
        type="button"
        data-testid="mc-safety-dismiss"
        onClick={() => onDismiss?.(ev)}
        className="shrink-0 text-zinc-600 hover:text-zinc-300"
        title="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
};

export default SafetyRow;
