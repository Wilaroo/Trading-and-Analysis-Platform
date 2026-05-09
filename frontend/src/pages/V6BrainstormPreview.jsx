/**
 * V6BrainstormPreview.jsx — visual concepts beyond V6.2.
 *
 * Hits at ?preview=v6next. Demonstrates 7 ideas layered onto a slim
 * mock backdrop so they're all visible in one screenshot:
 *
 *  ① HEARTBEAT pulse line at very top — ambient bot tick rate
 *  ② RISK METER vertical bar on left edge — always-visible % of daily risk
 *  ③ Sparklines everywhere — cheap temporal context per metric
 *  ④ Glass-morphism + ambient signal halo on the focused panel
 *  ⑤ Symbol "vibe" tints — subtle gradient per scanner row
 *  ⑥ Animated data-flow particles through pipeline pills
 *  ⑦ Time-scrubber at bottom — rewind UI to any moment in the session
 *  ⑧ (BONUS) Decision provenance ring — radial breakdown on Verdict
 *
 * All effects are CSS / inline SVG only — no extra libs.
 */
import React, { useState, useEffect } from 'react';

// ─── ① HEARTBEAT PULSE LINE ────────────────────────────────────
const HeartbeatBar = () => (
  <div className="h-[3px] w-full bg-zinc-950 relative overflow-hidden flex-shrink-0">
    <div className="absolute inset-y-0 left-0 w-[20%] bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-80 animate-[pulse-slide_2.4s_ease-in-out_infinite]" />
    <style>{`
      @keyframes pulse-slide {
        0%   { transform: translateX(0%); opacity: 0.4; }
        50%  { opacity: 1; }
        100% { transform: translateX(500%); opacity: 0.4; }
      }
    `}</style>
  </div>
);

// ─── ② RISK METER (left edge, always visible) ──────────────────
const RiskMeter = ({ pctUsed = 42 }) => {
  const color = pctUsed < 50 ? 'emerald' : pctUsed < 80 ? 'amber' : 'rose';
  const bg = color === 'emerald' ? 'bg-emerald-500' : color === 'amber' ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div className="absolute left-0 top-0 bottom-0 w-[5px] z-30 bg-zinc-900/40 group">
      <div
        className={`absolute bottom-0 left-0 right-0 ${bg} opacity-70 transition-all duration-700`}
        style={{ height: `${pctUsed}%`, boxShadow: `0 0 10px currentColor` }}
      />
      <div className="absolute left-2 top-3 text-[9px] font-mono text-zinc-500 uppercase tracking-wider opacity-0 group-hover:opacity-100 transition">
        risk<br/>{pctUsed}%
      </div>
    </div>
  );
};

// ─── ③ TINY SPARKLINE ──────────────────────────────────────────
const Sparkline = ({ points, color = 'cyan', w = 60, h = 16 }) => {
  const max = Math.max(...points), min = Math.min(...points);
  const range = max - min || 1;
  const stroke = { cyan: '#22d3ee', emerald: '#34d399', amber: '#fbbf24', rose: '#fb7185', violet: '#c084fc' }[color];
  const d = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / range) * h}`).join(' ');
  const last = points[points.length - 1];
  const lastY = h - ((last - min) / range) * h;
  return (
    <svg width={w} height={h} className="inline-block">
      <polyline points={d} fill="none" stroke={stroke} strokeWidth="1.2" opacity="0.85" />
      <circle cx={w} cy={lastY} r="1.5" fill={stroke} />
      <circle cx={w} cy={lastY} r="3" fill={stroke} opacity="0.3" />
    </svg>
  );
};

// ─── ⑥ DATA-FLOW PARTICLE (animated dot through a pipeline pill) ─
const FlowParticle = ({ delay = 0 }) => (
  <span
    className="absolute top-1/2 -translate-y-1/2 left-0 w-1 h-1 rounded-full bg-cyan-300 pointer-events-none"
    style={{
      boxShadow: '0 0 6px #22d3ee, 0 0 12px #22d3ee',
      animation: `flow-particle 3s linear infinite ${delay}s`,
    }}
  />
);

// ─── ⑧ DECISION PROVENANCE RING ────────────────────────────────
const ProvenanceRing = ({ size = 88 }) => {
  // Slices: regime, consensus, cross-model, live, quality + a center net
  const segs = [
    { label: 'Regime',    pct: 75, color: '#34d399' },
    { label: 'Consensus', pct: 80, color: '#22d3ee' },
    { label: 'CrossMdl',  pct: 70, color: '#a78bfa' },
    { label: 'Live',      pct: 12, color: '#fb7185' },
    { label: 'Quality',   pct: 78, color: '#fbbf24' },
  ];
  const r = size / 2 - 8, c = size / 2;
  const total = segs.reduce((a, s) => a + s.pct, 0);
  let angle = -90;
  return (
    <svg width={size} height={size} className="flex-shrink-0">
      <defs><filter id="glow"><feGaussianBlur stdDeviation="1.5" result="b" /><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      <circle cx={c} cy={c} r={r} fill="none" stroke="#27272a" strokeWidth="2" />
      {segs.map((s, i) => {
        const a = (s.pct / total) * 360;
        const a1 = angle, a2 = angle + a;
        angle += a;
        const rad = (deg) => (deg * Math.PI) / 180;
        const x1 = c + r * Math.cos(rad(a1));
        const y1 = c + r * Math.sin(rad(a1));
        const x2 = c + r * Math.cos(rad(a2));
        const y2 = c + r * Math.sin(rad(a2));
        const large = a > 180 ? 1 : 0;
        const path = `M ${c} ${c} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
        return <path key={i} d={path} fill={s.color} opacity="0.55" filter="url(#glow)" />;
      })}
      <circle cx={c} cy={c} r={r * 0.55} fill="#09090b" />
      <text x={c} y={c - 2} textAnchor="middle" fontSize="11" fontWeight="700" fill="#34d399">+43</text>
      <text x={c} y={c + 10} textAnchor="middle" fontSize="7" fill="#71717a">GO</text>
    </svg>
  );
};

// ─── ⑦ TIME SCRUBBER ───────────────────────────────────────────
const TimeScrubber = ({ value, onChange }) => (
  <div className="bg-gradient-to-t from-zinc-950 to-zinc-900/80 border-t border-zinc-800 px-4 py-2 flex items-center gap-3 flex-shrink-0">
    <span className="text-[11px] text-zinc-500 uppercase tracking-wider">⏱ rewind</span>
    <span className="text-[11px] text-zinc-400 font-mono">9:30</span>
    <div className="flex-1 relative h-6">
      {/* Event ticks on the timeline */}
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 bg-zinc-800/60 rounded-full">
        {/* Significant moments */}
        {[
          { t: 8,  color: 'emerald', label: 'gap_fade fired' },
          { t: 22, color: 'rose',    label: 'EFA explosion' },
          { t: 34, color: 'amber',   label: 'manual flatten' },
          { t: 48, color: 'cyan',    label: 'orphan-GTC alert' },
          { t: 65, color: 'violet',  label: 'EOD recap' },
        ].map((m, i) => (
          <div key={i} className={`absolute top-1/2 -translate-y-1/2 w-1.5 h-3 rounded-sm ${
            { emerald: 'bg-emerald-400', rose: 'bg-rose-400', amber: 'bg-amber-400', cyan: 'bg-cyan-400', violet: 'bg-violet-400' }[m.color]
          }`} style={{ left: `${m.t}%`, boxShadow: `0 0 4px currentColor` }} title={m.label} />
        ))}
        {/* Scrub thumb */}
        <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-cyan-300 border-2 border-zinc-950" style={{ left: `${value}%`, boxShadow: '0 0 8px #22d3ee' }} />
      </div>
    </div>
    <span className="text-[11px] text-zinc-400 font-mono">15:55</span>
    <span className="bg-cyan-900/50 border border-cyan-700/60 rounded px-1.5 py-0.5 text-[11px] text-cyan-200 font-mono">
      now: <span className="font-bold">{Math.floor(9 + value / 100 * 6.5)}:{String(Math.floor((value / 100 * 6.5 % 1) * 60)).padStart(2, '0')}</span>
    </span>
    <input
      type="range" min="0" max="100" value={value}
      onChange={e => onChange(Number(e.target.value))}
      className="absolute inset-x-0 opacity-0 cursor-pointer"
      style={{ left: '110px', right: '120px', height: '24px' }}
    />
  </div>
);

// ─── ROOT BRAINSTORM VIEW ──────────────────────────────────────
export const V6BrainstormPreview = () => {
  const [scrub, setScrub] = useState(78);
  const [selected, setSelected] = useState(null);

  const concepts = [
    { id: 'heartbeat',  label: '① Heartbeat pulse line',   blurb: 'Ambient bot tick rate — speeds up when actively evaluating, slows when idle.' },
    { id: 'risk',       label: '② Risk meter (left edge)', blurb: 'Always-visible vertical bar showing % of daily risk used. Glows brighter as you approach DLP cap.' },
    { id: 'sparks',     label: '③ Sparklines everywhere',  blurb: 'Tiny inline charts next to every counter — P&L, equity, scanner hits, throttle counts. Cheap temporal context.' },
    { id: 'glass',      label: '④ Glass + ambient halo',   blurb: 'Focused panel gets a backdrop-blur + cyan/amber border-glow tied to SentCom state. Subtle awareness without being loud.' },
    { id: 'vibe',       label: '⑤ Symbol vibe tints',      blurb: 'Each scanner row has a subtle gradient based on volatility / trend / direction. Glance-readable mood.' },
    { id: 'particles',  label: '⑥ Pipeline data flow',     blurb: 'Animated dots flow through SCAN → EVAL → ORDER → MANAGE → CLOSE pills, visualizing signals working through the bot.' },
    { id: 'scrubber',   label: '⑦ Time scrubber',          blurb: 'Drag the slider to rewind the UI to ANY moment today. Chart, Thinking pane, positions, alerts — all rewind together. Killer for post-trade review.' },
    { id: 'ring',       label: '⑧ Provenance ring',        blurb: 'Hover a SentCom verdict to see a radial breakdown of every input that contributed (regime / consensus / models / live / quality).' },
  ];

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100 flex flex-col relative overflow-hidden">
      <RiskMeter pctUsed={42} />
      <HeartbeatBar />

      {/* Top bar */}
      <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-1.5 flex items-center gap-2 text-[12px] flex-shrink-0">
        <span className="text-cyan-300 font-bold text-xs">SentCom V6.next — Visual Concepts Brainstorm</span>
        <span className="bg-violet-900/30 border border-violet-700/50 rounded px-1.5 py-0.5 text-violet-300 text-[11px]">8 concepts overlaid</span>
        <a href="?preview=v6" className="ml-auto text-cyan-400 hover:underline text-[11px]">← back to V6.2 (locked)</a>
      </div>

      {/* Pipeline strip with flowing particles */}
      <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-2 flex items-center gap-2 flex-shrink-0 text-[13px]">
        <span className="text-cyan-400 font-bold tracking-wider mr-2">SENTCOM</span>
        {['SCAN 6', 'EVAL 5', 'ORDER 0', 'MANAGE 7', 'CLOSE 9'].map((label, i) => (
          <React.Fragment key={i}>
            <div className="relative overflow-hidden bg-zinc-900 border border-zinc-800 rounded px-2 py-1">
              <FlowParticle delay={i * 0.6} />
              <span className="text-zinc-300 font-mono">{label}</span>
            </div>
            {i < 4 && <span className="text-zinc-700">→</span>}
          </React.Fragment>
        ))}
        <style>{`
          @keyframes flow-particle {
            0%   { left: -10%; opacity: 0; }
            10%  { opacity: 1; }
            90%  { opacity: 1; }
            100% { left: 110%; opacity: 0; }
          }
        `}</style>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-zinc-500">
          {/* P&L with sparkline */}
          <div className="flex items-center gap-1.5">
            <span>P&amp;L</span>
            <span className="text-emerald-300 font-bold font-mono">+$4,300</span>
            <Sparkline points={[10, 12, 11, 15, 18, 17, 22, 24, 23, 28, 31, 29, 34, 38, 43]} color="emerald" />
          </div>
          <div className="flex items-center gap-1.5">
            <span>Equity</span>
            <span className="text-zinc-200 font-bold font-mono">$237.6K</span>
            <Sparkline points={[230, 231, 230, 232, 234, 233, 235, 234, 236, 237, 236, 237, 238, 237, 238]} color="cyan" />
          </div>
          <div className="flex items-center gap-1.5">
            <span>Throttle</span>
            <span className="text-amber-300 font-bold font-mono">3</span>
            <Sparkline points={[0, 0, 0, 1, 0, 1, 2, 1, 3, 2, 2, 3, 2, 3, 3]} color="amber" />
          </div>
        </div>
      </div>

      {/* Main grid */}
      <div className="flex-1 flex gap-3 p-3 overflow-hidden">
        {/* LEFT — concept palette */}
        <div className="w-[280px] flex-shrink-0 bg-zinc-950/60 backdrop-blur-md border border-zinc-800/80 rounded-lg p-3 overflow-y-auto">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">Visual Concepts · click to highlight</div>
          <div className="space-y-1">
            {concepts.map(c => (
              <button
                key={c.id}
                onClick={() => setSelected(selected === c.id ? null : c.id)}
                className={`w-full text-left p-2 rounded border transition ${
                  selected === c.id
                    ? 'bg-cyan-900/40 border-cyan-600 ring-1 ring-cyan-400/40'
                    : 'bg-zinc-900/40 border-zinc-800 hover:border-zinc-700'
                }`}
              >
                <div className={`text-[12px] font-semibold ${selected === c.id ? 'text-cyan-200' : 'text-zinc-300'}`}>{c.label}</div>
                <div className="text-[11px] text-zinc-500 mt-0.5 leading-snug">{c.blurb}</div>
              </button>
            ))}
          </div>
        </div>

        {/* CENTER — focused "Thinking" panel demo, with glass + ambient halo */}
        <div className="flex-1 relative">
          <div
            className="absolute inset-0 rounded-xl border-2 transition-all duration-500"
            style={{
              borderColor: 'rgba(34,211,238,0.45)',
              boxShadow: '0 0 80px rgba(34,211,238,0.2), inset 0 0 60px rgba(34,211,238,0.05)',
            }}
          />
          <div className="absolute inset-0 rounded-xl bg-zinc-950/70 backdrop-blur-xl border border-cyan-700/30 overflow-hidden flex flex-col">
            <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2 flex-shrink-0">
              <span className="text-[11px] text-zinc-500 uppercase tracking-wider">🧠 Thinking · ambient halo · glass-morphism</span>
              <span className="bg-cyan-900/40 border border-cyan-700 rounded px-1.5 py-0.5 text-[11px] text-cyan-200 font-mono">FDX</span>
              <span className="ml-auto text-[10px] text-zinc-600">halo color tracks SentCom state · cyan = NORMAL · amber = ELEVATED · rose = CRITICAL</span>
            </div>
            <div className="flex-1 p-4 grid grid-cols-2 gap-4 overflow-auto">
              {/* Provenance ring + bottom line */}
              <div className="space-y-3">
                <div className="text-[11px] text-zinc-500 uppercase tracking-wider">⑧ Provenance ring</div>
                <div className="flex items-center gap-3 bg-zinc-900/40 border border-zinc-800 rounded-lg p-3">
                  <ProvenanceRing size={96} />
                  <div className="text-[12px] space-y-0.5">
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#34d399'}}/><span className="text-zinc-300">Regime</span><span className="ml-auto font-mono text-emerald-300">+10</span></div>
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#22d3ee'}}/><span className="text-zinc-300">Consensus</span><span className="ml-auto font-mono text-cyan-300">+15</span></div>
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#a78bfa'}}/><span className="text-zinc-300">Cross-Mdl</span><span className="ml-auto font-mono text-violet-300">+8</span></div>
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#fb7185'}}/><span className="text-zinc-300">Live</span><span className="ml-auto font-mono text-rose-300">−2</span></div>
                    <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#fbbf24'}}/><span className="text-zinc-300">Quality</span><span className="ml-auto font-mono text-amber-300">+12</span></div>
                  </div>
                </div>
                <div className="bg-zinc-900/40 border border-zinc-800 rounded p-2 text-[12px] text-zinc-400 leading-relaxed">
                  <span className="text-cyan-300 font-semibold">Bot:</span> "Watching, not firing yet — vol confirm short by 67%, VWAP $0.12 below entry trigger."
                </div>
              </div>

              {/* Scanner with vibe tints */}
              <div className="space-y-3">
                <div className="text-[11px] text-zinc-500 uppercase tracking-wider">⑤ Symbol vibe tints</div>
                <div className="space-y-1.5">
                  {[
                    { sym: 'PWR',  vibe: 'linear-gradient(90deg, rgba(52,211,153,0.18), transparent)', mood: 'steady gainer',     spark: [40,42,41,44,46,45,48,50,52,55] },
                    { sym: 'MCHP', vibe: 'linear-gradient(90deg, rgba(251,191,36,0.18), transparent)', mood: 'choppy / amber',    spark: [42,40,44,41,43,40,42,41,43,42] },
                    { sym: 'VLO',  vibe: 'linear-gradient(90deg, rgba(34,211,238,0.18), transparent)', mood: 'fresh evaluation',  spark: [30,32,31,34,38,42,45,48,52,58] },
                    { sym: 'TNA',  vibe: 'linear-gradient(90deg, rgba(251,113,133,0.18), transparent)', mood: 'fading short',     spark: [55,52,48,45,42,40,38,34,32,30] },
                    { sym: 'VRT',  vibe: 'linear-gradient(90deg, rgba(192,132,252,0.18), transparent)', mood: 'high-vol pulsing', spark: [40,52,38,55,42,58,40,52,38,55] },
                  ].map((r, i) => (
                    <div key={i} className="rounded p-2 border border-zinc-800/60 flex items-center gap-2" style={{ background: r.vibe }}>
                      <span className="font-mono font-bold text-zinc-100 w-12">{r.sym}</span>
                      <Sparkline points={r.spark} color={['emerald','amber','cyan','rose','violet'][i]} w={48} h={14} />
                      <span className="text-[10px] text-zinc-500 italic ml-auto">{r.mood}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <TimeScrubber value={scrub} onChange={setScrub} />

      {/* Status strip with even more sparklines */}
      <div className="bg-zinc-950 border-t border-zinc-800 px-3 py-1 flex items-center gap-3 text-[10px] text-zinc-500 flex-shrink-0">
        <span>SAFETY</span>
        <Sparkline points={[0,0,0,0,0,1,0,0,0,0]} color="emerald" w={40} h={10} />
        <span className="text-zinc-700">·</span>
        <span>DRIFT</span>
        <Sparkline points={[0,0,1,0,0,0,0,0,0,0]} color="amber" w={40} h={10} />
        <span className="text-zinc-700">·</span>
        <span>ORPHAN-GTC</span>
        <Sparkline points={[0,0,0,0,0,0,0,0,0,0]} color="cyan" w={40} h={10} />
        <span className="text-zinc-700">·</span>
        <span>PUSHER</span>
        <Sparkline points={[5,6,5,7,6,5,6,7,6,5]} color="emerald" w={40} h={10} />
        <span className="text-zinc-500 ml-auto">{selected ? `selected: ${selected}` : 'click a concept on the left to highlight'}</span>
      </div>
    </div>
  );
};

export default V6BrainstormPreview;
