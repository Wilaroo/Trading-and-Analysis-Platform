/**
 * StreamRow — v19.34.184. A single pipeline event line in a Mission Control
 * lane. Severity-coloured left border (matches V5). Click → opens the symbol's
 * decision drawer.
 */
import React from 'react';

const SEV_BORDER = {
  alarm: 'border-l-rose-500',
  warn: 'border-l-amber-500',
  success: 'border-l-emerald-500',
  info: 'border-l-cyan-700',
};
const SEV_DOT = {
  alarm: 'bg-rose-500',
  warn: 'bg-amber-500',
  success: 'bg-emerald-500',
  info: 'bg-cyan-600',
};

const fmtClock = (iso) => {
  if (!iso) return '--:--:--';
  try { return new Date(iso).toLocaleTimeString('en-US', { hour12: false }); }
  catch { return '--:--:--'; }
};

export const StreamRow = ({ ev, onSymbolClick }) => {
  const sev = ev.severity || 'info';
  const sym = ev.symbol;
  return (
    <button
      type="button"
      data-testid={`mc-row-${ev.lane}-${ev.id || ev.timestamp}`}
      onClick={() => sym && onSymbolClick?.(sym)}
      className={`w-full text-left pl-2 pr-2 py-1 border-l-2 ${SEV_BORDER[sev] || SEV_BORDER.info}
        border-b border-zinc-900/80 hover:bg-zinc-800/40 transition-colors`}
    >
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${SEV_DOT[sev] || SEV_DOT.info}`} />
        <span className="text-[11px] text-zinc-600 font-mono shrink-0">{fmtClock(ev.timestamp)}</span>
        {sym && (
          <span className="text-[12px] font-mono font-bold text-zinc-100 shrink-0 hover:text-cyan-400">
            {sym}
          </span>
        )}
      </div>
      <div className="text-[12px] text-zinc-400 leading-snug mt-0.5 break-words">{ev.text}</div>
    </button>
  );
};

export default StreamRow;
