/**
 * LaneColumn — v19.34.184. One pipeline lane (header + live scrolling rows).
 * Scanner lane also renders a live scan-pulse summary strip at the top.
 */
import React from 'react';
import { LANE_META } from '../../lib/laneClassify';
import StreamRow from './StreamRow';

const ScanPulse = ({ pulse }) => {
  if (!pulse) return null;
  return (
    <div
      data-testid="mc-scan-pulse"
      className="px-2 py-1.5 border-b border-zinc-800 bg-zinc-900/60 text-[11px] font-mono flex items-center gap-3"
    >
      <span className="text-emerald-400">▲ {pulse.triggers || 0} trig</span>
      <span className="text-zinc-500">{pulse.skips || 0} skip</span>
      <span className="text-amber-500">{pulse.rejects || 0} rej</span>
      <span className="text-zinc-600 ml-auto">/{pulse.window_s || 3}s</span>
    </div>
  );
};

export const LaneColumn = ({ lane, events, pulse, onSymbolClick }) => {
  const meta = LANE_META[lane] || { label: lane, hint: '' };
  return (
    <div
      data-testid={`mc-lane-${lane}`}
      className="flex flex-col min-w-0 border border-zinc-800 rounded bg-zinc-950 overflow-hidden"
    >
      <div className="px-2 py-1.5 border-b border-zinc-800 bg-zinc-900/40 flex items-baseline justify-between">
        <span className="text-[12px] uppercase tracking-wider text-zinc-200 font-bold">{meta.label}</span>
        <span className="text-[10px] text-zinc-600">{events.length}</span>
      </div>
      <div className="px-2 py-0.5 text-[10px] text-zinc-600 border-b border-zinc-900">{meta.hint}</div>
      {lane === 'scanner' && <ScanPulse pulse={pulse} />}
      <div className="flex-1 overflow-y-auto v5-scroll min-h-0">
        {events.length === 0 ? (
          <div className="px-2 py-6 text-center text-[11px] text-zinc-600">waiting for events…</div>
        ) : (
          events.map((ev) => <StreamRow key={ev.id || `${ev.timestamp}-${ev.text?.slice(0, 12)}`} ev={ev} onSymbolClick={onSymbolClick} />)
        )}
      </div>
    </div>
  );
};

export default LaneColumn;
