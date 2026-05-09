/* eslint-disable react/no-unescaped-entities */
/**
 * V6.next++ Mockup — V6.2 layout fused with concepts ①②③④⑤⑦⑧
 * AND enhancements A–J:
 *   A. Trigger-progress micro-bars in Thinking pane
 *   B. SL→Entry→PT proximity strip on each position row
 *   C. Scanner mini-provenance arc next to confidence
 *   D. Sticky CRITICAL-state action bar (rose only)
 *   E. Day-narrative strip above scrubber
 *   F. Contextual AI chat drawer (⌘K open/close)
 *   G. Aggregate Open P&L sparkline at top of positions panel
 *   H. "Recent change" amber-outline marker on rows
 *   I. Conditional sparklines (hide if dead-flat)
 *   J. Colorblind icon redundancy on state pills (✓/⚠/✕)
 *
 * Hits at ?preview=v6mock
 */
import React, { useState, useEffect, useMemo } from 'react';

// ─── tiny atoms ───────────────────────────────────────────────────
const Sparkline = ({ points, color = 'emerald', w = 60, h = 16, hideIfFlat = false, threshold = 0.5 }) => {
  const max = Math.max(...points), min = Math.min(...points), range = max - min;
  // CONCEPT I — hide if dead-flat
  if (hideIfFlat && range < threshold) {
    return <span className="text-[9px] text-zinc-700 italic">stable</span>;
  }
  const stroke = { cyan:'#22d3ee', emerald:'#34d399', amber:'#fbbf24', rose:'#fb7185', violet:'#c084fc', zinc:'#a1a1aa' }[color];
  const r = range || 1;
  const d = points.map((p,i) => `${(i/(points.length-1))*w},${h-((p-min)/r)*h}`).join(' ');
  const lastY = h-((points[points.length-1]-min)/r)*h;
  return (
    <svg width={w} height={h} className="inline-block align-middle flex-shrink-0">
      <polyline points={d} fill="none" stroke={stroke} strokeWidth="1.4" opacity="0.95" />
      <circle cx={w} cy={lastY} r="1.8" fill={stroke} />
    </svg>
  );
};

const Pill = ({ children, color = 'zinc', className = '' }) => {
  const c = {
    zinc:'bg-zinc-900 text-zinc-300 border-zinc-700',
    emerald:'bg-emerald-900/40 text-emerald-300 border-emerald-700/60',
    rose:'bg-rose-900/40 text-rose-300 border-rose-700/60',
    amber:'bg-amber-900/40 text-amber-300 border-amber-700/60',
    cyan:'bg-cyan-900/40 text-cyan-300 border-cyan-700/60',
    violet:'bg-violet-900/40 text-violet-300 border-violet-700/60',
    orange:'bg-orange-900/40 text-orange-300 border-orange-700/60',
  };
  return <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[12px] font-medium border ${c[color]} ${className}`}>{children}</span>;
};

// ─── CONCEPT C: mini-arc (12-14px, single-segment proxy for full ring) ─
const MiniArc = ({ score, size = 16 }) => {
  // score 0-100 — sweep arc length
  const r = size/2 - 2, c = size/2;
  const sweep = Math.max(5, Math.min(95, score)) / 100 * 360;
  const color = score >= 70 ? '#34d399' : score >= 50 ? '#22d3ee' : score >= 35 ? '#fbbf24' : '#fb7185';
  const rad = d => d*Math.PI/180;
  const startA = -90, endA = -90 + sweep;
  const x1 = c + r*Math.cos(rad(startA)), y1 = c + r*Math.sin(rad(startA));
  const x2 = c + r*Math.cos(rad(endA)),   y2 = c + r*Math.sin(rad(endA));
  const large = sweep > 180 ? 1 : 0;
  return (
    <svg width={size} height={size} className="flex-shrink-0">
      <circle cx={c} cy={c} r={r} fill="none" stroke="#27272a" strokeWidth="1.5" />
      <path d={`M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`} stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" style={{filter:`drop-shadow(0 0 2px ${color})`}}/>
    </svg>
  );
};

// ─── CONCEPT A: trigger condition progress bar ─────────────────────
const TriggerLine = ({ label, pct, suffix }) => {
  const filled = Math.min(100, pct);
  const ready = filled >= 100;
  const color = ready ? '#34d399' : pct >= 70 ? '#22d3ee' : '#71717a';
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className={`flex-shrink-0 ${ready ? 'text-emerald-300' : 'text-zinc-300'}`}>{ready ? '✓' : '○'}</span>
      <span className="flex-1 truncate">{label}</span>
      <div className="w-20 h-1 bg-zinc-800 rounded-full overflow-hidden flex-shrink-0">
        <div className="h-full transition-all" style={{ width: `${filled}%`, background: color, boxShadow: ready ? `0 0 4px ${color}` : 'none' }} />
      </div>
      <span className="font-mono text-[10px] text-zinc-500 w-8 text-right">{suffix}</span>
    </div>
  );
};

// ─── CONCEPT B: SL→Entry→PT proximity bar ──────────────────────────
const ProximityBar = ({ sl, entry, pt, current }) => {
  // current can be between sl and pt; calc its % position
  const min = Math.min(sl, pt), max = Math.max(sl, pt);
  const pos = ((current - min) / (max - min)) * 100;
  const entryPos = ((entry - min) / (max - min)) * 100;
  const isLong = pt > sl;
  // dot color by proximity
  const slDist = Math.abs((current - sl) / (entry - sl));
  const ptDist = Math.abs((current - pt) / (entry - pt));
  const dotColor = slDist < 0.3 ? '#fb7185' : ptDist < 0.3 ? '#34d399' : '#22d3ee';
  return (
    <div className="relative w-full h-2 mt-1">
      {/* base bar with gradient SL → PT */}
      <div className="absolute inset-0 rounded-sm overflow-hidden"
        style={{ background: isLong
          ? 'linear-gradient(90deg, rgba(251,113,133,0.55) 0%, rgba(63,63,70,0.45) 50%, rgba(52,211,153,0.55) 100%)'
          : 'linear-gradient(90deg, rgba(52,211,153,0.55) 0%, rgba(63,63,70,0.45) 50%, rgba(251,113,133,0.55) 100%)' }} />
      {/* entry tick */}
      <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-zinc-400" style={{ left: `${entryPos}%` }} />
      {/* current price dot */}
      <div className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full border border-zinc-950"
        style={{ left: `calc(${Math.max(2, Math.min(98, pos))}% - 4px)`, background: dotColor, boxShadow: `0 0 5px ${dotColor}` }} />
      {/* labels */}
      <div className="absolute -bottom-3 left-0 text-[8px] text-rose-400 font-mono">SL</div>
      <div className="absolute -bottom-3 right-0 text-[8px] text-emerald-400 font-mono">PT</div>
    </div>
  );
};

// ─── ① HEARTBEAT PULSE BAR ─────────────────────────────────────────
const Heartbeat = ({ state }) => {
  const speed = state==='rose' ? '0.7s' : state==='amber' ? '1.2s' : '2s';
  const color = state==='rose' ? '#fb7185' : state==='amber' ? '#fbbf24' : '#22d3ee';
  return (
    <>
      <div className="h-[5px] w-full bg-zinc-950 relative overflow-hidden flex-shrink-0 border-b border-zinc-900">
        <div className="absolute inset-y-0 left-0 w-[25%] opacity-95"
          style={{ background: `linear-gradient(90deg, transparent, ${color}, ${color}, transparent)`, filter: `drop-shadow(0 0 4px ${color})`, animation: `pulse-slide ${speed} ease-in-out infinite` }} />
      </div>
      <style>{`@keyframes pulse-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(500%); } }`}</style>
    </>
  );
};

// ─── ② RISK RAIL ──────────────────────────────────────────────────
const RiskRail = ({ pct = 22 }) => {
  const color = pct < 50 ? 'bg-emerald-500' : pct < 80 ? 'bg-amber-500' : 'bg-rose-500';
  const text  = pct < 50 ? 'text-emerald-300' : pct < 80 ? 'text-amber-300' : 'text-rose-300';
  return (
    <div className="w-[22px] bg-zinc-950 border-r border-zinc-800/60 flex flex-col items-center py-2 flex-shrink-0">
      <div className="text-[8px] text-zinc-600 font-mono leading-tight rotate-180 mb-1" style={{writingMode:'vertical-rl'}}>DLP</div>
      <div className="relative w-2 flex-1 bg-zinc-900 rounded-sm overflow-hidden">
        <div className={`absolute bottom-0 left-0 right-0 ${color} transition-all`} style={{ height: `${pct}%`, boxShadow: `0 0 8px currentColor` }} />
      </div>
      <div className={`text-[9px] font-mono ${text} font-bold mt-1`}>{pct}%</div>
    </div>
  );
};

// ─── ⑧ PROVENANCE RING (full) ─────────────────────────────────────
const ProvenanceRing = ({ size = 88, score = 43, segs }) => {
  const r = size/2 - 7, c = size/2;
  const total = segs.reduce((a,s) => a+s.pct, 0);
  let angle = -90;
  return (
    <svg width={size} height={size} className="flex-shrink-0">
      <circle cx={c} cy={c} r={r} fill="none" stroke="#27272a" strokeWidth="2" />
      {segs.map((s,i) => {
        const a = (s.pct/total)*360, a1=angle, a2=angle+a; angle+=a;
        const rad = d => d*Math.PI/180;
        const x1=c+r*Math.cos(rad(a1)), y1=c+r*Math.sin(rad(a1));
        const x2=c+r*Math.cos(rad(a2)), y2=c+r*Math.sin(rad(a2));
        const large = a > 180 ? 1 : 0;
        return <path key={i} d={`M ${c} ${c} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`} fill={s.color} opacity="0.75" />;
      })}
      <circle cx={c} cy={c} r={r*0.55} fill="#09090b" />
      <text x={c} y={c-2} textAnchor="middle" fontSize="13" fontWeight="700" fill={score >= 0 ? '#34d399' : '#fb7185'}>{score >= 0 ? '+' : ''}{score}</text>
      <text x={c} y={c+10} textAnchor="middle" fontSize="8" fill="#71717a">{score >= 25 ? 'GO' : score >= 0 ? 'WAIT' : 'SKIP'}</text>
    </svg>
  );
};

// ─── ⑤ Vibe-tinted scanner row + CONCEPT C mini-arc + H recent ─────
const VibeRow = ({ sym, mood, conf, spark, reason, recent = false }) => {
  const tints = {
    'steady up':  { bg:'linear-gradient(90deg, rgba(52,211,153,0.13), transparent 70%)', dot:'#34d399', label:'text-emerald-400', moodColor:'emerald' },
    'choppy':     { bg:'linear-gradient(90deg, rgba(251,191,36,0.13), transparent 70%)', dot:'#fbbf24', label:'text-amber-400',   moodColor:'amber' },
    'fresh':      { bg:'linear-gradient(90deg, rgba(34,211,238,0.13), transparent 70%)', dot:'#22d3ee', label:'text-cyan-400',    moodColor:'cyan' },
    'fading':     { bg:'linear-gradient(90deg, rgba(251,113,133,0.13), transparent 70%)', dot:'#fb7185', label:'text-rose-400',   moodColor:'rose' },
    'high-vol':   { bg:'linear-gradient(90deg, rgba(192,132,252,0.13), transparent 70%)', dot:'#c084fc', label:'text-violet-400', moodColor:'violet' },
  };
  const t = tints[mood];
  return (
    <div
      className={`border-b border-zinc-900/60 px-2 py-1.5 hover:brightness-125 cursor-pointer relative ${recent ? 'ring-1 ring-amber-500/60' : ''}`}
      style={{ background: t.bg }}>
      {recent && <span className="absolute top-1 right-1 text-[8px] uppercase tracking-wider text-amber-300 font-bold animate-pulse">NEW</span>}
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: t.dot, boxShadow:`0 0 4px ${t.dot}` }} />
        <span className="font-mono font-bold text-zinc-100 w-10 text-[12px]">{sym}</span>
        <Sparkline points={spark} color={t.moodColor} w={36} h={12} />
        <span className={`text-[9px] uppercase tracking-wider ${t.label} ml-auto italic`}>{mood}</span>
        {/* CONCEPT C — mini provenance arc */}
        <MiniArc score={conf} size={14} />
        <span className="font-mono text-[11px] text-zinc-300 w-7 text-right">{conf}%</span>
      </div>
      <div className="text-[10px] text-zinc-500 ml-3.5 italic mt-0.5 truncate">{reason}</div>
    </div>
  );
};

// ─── ④ GLASS HALO PANE ────────────────────────────────────────────
const GlassHaloPane = ({ state, children, label }) => {
  const palette = {
    cyan:    { color:'#22d3ee', name:'NORMAL',   icon:'✓', border:'rgba(34,211,238,0.85)',  glow:'rgba(34,211,238,0.55)',  inner:'rgba(34,211,238,0.10)', accent:'text-cyan-300' },
    amber:   { color:'#fbbf24', name:'ELEVATED', icon:'⚠', border:'rgba(251,191,36,0.90)',  glow:'rgba(251,191,36,0.65)',  inner:'rgba(251,191,36,0.12)', accent:'text-amber-300' },
    rose:    { color:'#fb7185', name:'CRITICAL', icon:'✕', border:'rgba(251,113,133,0.95)', glow:'rgba(251,113,133,0.75)', inner:'rgba(251,113,133,0.14)', accent:'text-rose-300' },
  };
  const p = palette[state];
  return (
    <div className="rounded-lg overflow-hidden flex flex-col"
      style={{
        background: 'rgba(15,23,42,0.55)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        border: `2px solid ${p.border}`,
        boxShadow: `0 0 60px ${p.glow}, 0 0 30px ${p.glow}, inset 0 0 40px ${p.inner}`,
        transition: 'border-color 0.6s, box-shadow 0.6s',
      }}>
      <div className="flex items-center justify-between px-3 py-1.5 border-b" style={{ borderColor: p.border, background: `linear-gradient(180deg, ${p.inner}, transparent)` }}>
        <span className="text-[12px] font-bold tracking-wider text-zinc-100">{label}</span>
        {/* J — colorblind icon + text */}
        <span className={`text-[10px] uppercase tracking-widest font-bold ${p.accent} flex items-center gap-1`} style={{ textShadow: `0 0 8px ${p.color}` }}>
          <span>{p.icon}</span><span>{p.name}</span>
        </span>
      </div>
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  );
};

// ─── E. DAY NARRATIVE STRIP ───────────────────────────────────────
const NarrativeStrip = ({ onJump }) => {
  const phrases = [
    { t: 8,  text: 'Calm open',                            color:'text-zinc-400' },
    { t: 14, text: '10:14 PWR triggered (+$120)',          color:'text-emerald-400' },
    { t: 22, text: 'EFA explosion · sat out',              color:'text-rose-400' },
    { t: 34, text: '11:32 manual flatten · TNA',           color:'text-amber-400' },
    { t: 48, text: 'orphan-GTC alert · auto-cancelled',    color:'text-cyan-400' },
    { t: 62, text: '13:05 throttle event · self-recovered', color:'text-violet-400' },
    { t: 78, text: 'now · stable',                         color:'text-emerald-300' },
  ];
  return (
    <div className="bg-zinc-950/80 border-t border-zinc-800/60 px-3 py-1 flex items-center gap-2 text-[10px] flex-shrink-0 overflow-hidden whitespace-nowrap">
      <span className="text-zinc-600 uppercase tracking-wider font-bold flex-shrink-0">Day so far</span>
      {phrases.map((p,i) => (
        <React.Fragment key={i}>
          <button onClick={() => onJump(p.t)} className={`${p.color} hover:underline italic`} title="jump scrubber here">{p.text}</button>
          {i < phrases.length-1 && <span className="text-zinc-700">·</span>}
        </React.Fragment>
      ))}
    </div>
  );
};

// ─── ⑦ TIME SCRUBBER ──────────────────────────────────────────────
const TimeScrubber = ({ scrub, setScrub }) => {
  const events = [
    { t: 8,  color:'#34d399', label:'gap_fade fired' },
    { t: 22, color:'#fb7185', label:'EFA explosion' },
    { t: 34, color:'#fbbf24', label:'manual flatten · TNA' },
    { t: 48, color:'#22d3ee', label:'orphan-GTC alert (auto-cancelled)' },
    { t: 62, color:'#c084fc', label:'bracket reissue throttled · UPS' },
    { t: 78, color:'#34d399', label:'now · live' },
    { t: 90, color:'#fbbf24', label:'EOD recap window' },
  ];
  const startMin = 9*60+30, endMin = 15*60+55;
  const m = startMin + (endMin-startMin)*(scrub/100);
  const tStr = `${String(Math.floor(m/60)).padStart(2,'0')}:${String(Math.floor(m%60)).padStart(2,'0')}`;
  return (
    <div className="bg-zinc-950 border-t border-zinc-800/60 px-3 py-2 flex items-center gap-3 flex-shrink-0">
      <span className="text-[10px] text-zinc-500 font-mono">9:30</span>
      <div className="flex-1 relative h-5">
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 bg-zinc-800 rounded-full" />
        {events.map((e,i) => (
          <div key={i} className="absolute top-1/2 -translate-y-1/2 w-1.5 h-3 rounded-sm cursor-pointer"
            style={{ left: `${e.t}%`, background: e.color, boxShadow: `0 0 4px ${e.color}` }} title={e.label} />
        ))}
        <input type="range" min="0" max="100" step="0.5" value={scrub} onChange={e => setScrub(Number(e.target.value))}
          className="absolute inset-0 w-full opacity-0 cursor-pointer" />
        <div className="absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border-2 border-zinc-950 pointer-events-none transition-all"
          style={{ left: `calc(${scrub}% - 7px)`, background:'#22d3ee', boxShadow:'0 0 10px #22d3ee' }} />
      </div>
      <span className="text-[10px] text-zinc-500 font-mono">15:55</span>
      <Pill color="cyan" className="font-mono">at: {tStr}</Pill>
      <span className="text-[10px] text-zinc-600 italic">drag thumb · UI rewinds</span>
    </div>
  );
};

// ─── KPI ribbon — CONCEPT I conditional sparklines ────────────────
const KpiRibbon = ({ state }) => (
  <div className="bg-gradient-to-b from-zinc-900/80 to-zinc-950 border-b border-zinc-800 px-4 py-2 flex items-stretch gap-5 flex-shrink-0">
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Daily P&amp;L</div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[22px] font-bold text-emerald-300 leading-none">+$4,300</span>
        <Sparkline points={[10,12,11,15,18,17,22,24,23,28,31,29,34,38,43]} color="emerald" w={56} h={18} />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">realized <span className="text-zinc-300 font-mono">+$3,643</span> · unreal <span className="text-emerald-400 font-mono">+$657</span></div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Equity</div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[20px] font-bold text-zinc-100 leading-none">$237,654</span>
        {/* I — equity is dead-flat → suppressed */}
        <Sparkline points={[237,237,237,237,237,237,237,237,237,237,237,237,237,237,237]} color="zinc" w={50} h={16} hideIfFlat />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">peak <span className="font-mono">$238,012</span></div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Open Risk</div>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-[20px] font-bold leading-none ${state==='rose'?'text-rose-300':'text-amber-300'}`}>$2,512</span>
        <Sparkline points={state==='rose'?[1,2,2,3,3,4,5,5,6,6,7,8,8,9,10]:[2,2,2,2,2,3,2,2,3,3,2,3,3,2,2]} color={state==='rose'?'rose':'amber'} w={50} h={16} hideIfFlat threshold={0.6}/>
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">6 pos · max <span className="font-mono">$2.5K</span></div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Throttle / 5min</div>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-[20px] font-bold leading-none ${state==='cyan'?'text-zinc-300':state==='amber'?'text-amber-300':'text-rose-300'}`}>{state==='cyan'?0:state==='amber'?2:5}</span>
        {/* I — throttle is 0 in normal → suppressed */}
        <Sparkline points={state==='cyan'?[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]:state==='amber'?[0,0,0,1,0,1,2,1,2,2,2,2,1,2,2]:[0,1,1,2,2,3,3,4,4,5,4,5,5,5,5]}
          color={state==='cyan'?'zinc':state==='amber'?'amber':'rose'} w={50} h={16} hideIfFlat />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">order-router cooldowns</div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Pusher RPC</div>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-[20px] font-bold leading-none ${state==='rose'?'text-rose-300':'text-cyan-300'}`}>{state==='rose'?'480ms':'3ms'}</span>
        {/* I — RPC dead-flat in normal → suppressed; bursting in critical */}
        <Sparkline points={state==='rose'?[5,8,15,40,120,250,380,440,480,470,480,485,475,480,480]:[3,3,3,3,3,3,3,3,3,3,3,3,3,3,3]}
          color={state==='rose'?'rose':'cyan'} w={50} h={16} hideIfFlat threshold={1}/>
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">321 quotes · 6/min</div>
    </div>
  </div>
);

// ─── J. Top strip — colorblind icons on state pill ────────────────
const TopStrip = ({ state, setState, onToggleChat, chatOpen }) => {
  const stateMap = {
    cyan:  { label:'ALL SYSTEMS',  color:'emerald', icon:'✓', detail:'0 drift · 0 thr · 0 orph' },
    amber: { label:'1 WARNING',    color:'amber',   icon:'⚠', detail:'2 thr · 1 drift (auto)' },
    rose:  { label:'KILL TRIPPED', color:'rose',    icon:'✕', detail:'1 orph-GTC · pusher 480ms' },
  };
  const s = stateMap[state];
  return (
    <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-1.5 flex items-center gap-2 flex-shrink-0 text-[12px]">
      <span className="text-cyan-400 font-bold tracking-wider">SENTCOM</span>
      <div className="flex items-center gap-0.5 ml-2">
        <Pill color="zinc"><span className="text-zinc-500">SCAN</span> <span className="font-mono font-bold text-zinc-100">6</span></Pill>
        <span className="text-zinc-700 mx-0.5">→</span>
        <Pill color="cyan"><span className="text-zinc-500">EVAL</span> <span className="font-mono font-bold">5</span></Pill>
        <span className="text-zinc-700 mx-0.5">→</span>
        <Pill color="zinc"><span className="text-zinc-500">ORDER</span> <span className="font-mono font-bold text-zinc-100">0</span></Pill>
        <span className="text-zinc-700 mx-0.5">→</span>
        <Pill color="emerald"><span className="text-zinc-500">MANAGE</span> <span className="font-mono font-bold">7</span> <span className="text-emerald-400 font-mono">+0.3R</span></Pill>
        <span className="text-zinc-700 mx-0.5">→</span>
        <Pill color="emerald"><span className="text-zinc-500">CLOSE</span> <span className="font-mono font-bold">9</span></Pill>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <div className="flex items-center gap-1 bg-zinc-900 rounded p-0.5 border border-zinc-800">
          <span className="text-[10px] text-zinc-500 px-1">halo demo:</span>
          {['cyan','amber','rose'].map(opt => (
            <button key={opt} onClick={() => setState(opt)}
              className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded transition ${state===opt ? (opt==='cyan'?'bg-cyan-700/60 text-cyan-100':opt==='amber'?'bg-amber-700/60 text-amber-100':'bg-rose-700/60 text-rose-100') : 'text-zinc-500 hover:text-zinc-300'}`}>
              {opt}
            </button>
          ))}
        </div>
        <Pill color="amber">PAPER · DUN615665</Pill>
        <Pill color={s.color}><span className="font-bold">{s.icon}</span> {s.label} <span className="text-zinc-500 font-mono ml-1 text-[10px]">{s.detail}</span></Pill>
        <button onClick={onToggleChat}
          className={`flex items-center gap-1 px-2 py-0.5 rounded border transition ${chatOpen ? 'bg-cyan-700/60 border-cyan-400 text-cyan-50' : 'bg-cyan-900/30 border-cyan-700/60 text-cyan-300 hover:bg-cyan-900/60'}`}>
          <span>🤖</span><span className="text-[12px] font-medium">AI</span>
          <span className="text-zinc-500 font-mono text-[10px]">⌘K</span>
        </button>
      </div>
    </div>
  );
};

// ─── D. CRITICAL ACTION BAR (rose only) ───────────────────────────
const ActionBar = ({ onDismiss }) => (
  <div className="bg-rose-950/80 border-b-2 border-rose-500/70 px-4 py-2 flex items-center gap-3 flex-shrink-0 animate-pulse-bar"
    style={{ boxShadow: '0 4px 30px rgba(251,113,133,0.4), inset 0 0 30px rgba(251,113,133,0.15)' }}>
    <span className="text-rose-200 text-[14px] font-bold tracking-wider flex items-center gap-2">
      <span className="text-[18px]">🛑</span>
      ACTION REQUIRED
    </span>
    <span className="text-rose-300 text-[12px]">— Kill switch tripped at 14:07 · 1 orphan-GTC at IB · pusher 480ms</span>
    <div className="ml-auto flex items-center gap-2">
      <button className="bg-rose-600 hover:bg-rose-500 text-white text-[12px] font-bold px-3 py-1 rounded shadow-lg shadow-rose-900">
        🛑 FLATTEN ALL
      </button>
      <button className="bg-amber-600 hover:bg-amber-500 text-zinc-900 text-[12px] font-bold px-3 py-1 rounded">
        ✕ CANCEL ORPH-GTC
      </button>
      <button className="bg-cyan-600 hover:bg-cyan-500 text-white text-[12px] font-bold px-3 py-1 rounded">
        🔄 RECONNECT PUSHER
      </button>
      <button onClick={onDismiss} className="text-rose-300 hover:text-rose-100 text-[12px] underline">dismiss</button>
    </div>
    <style>{`@keyframes pulse-bar { 0%,100% { box-shadow: 0 4px 30px rgba(251,113,133,0.4), inset 0 0 30px rgba(251,113,133,0.15); } 50% { box-shadow: 0 4px 50px rgba(251,113,133,0.7), inset 0 0 50px rgba(251,113,133,0.25); } } .animate-pulse-bar { animation: pulse-bar 1.6s ease-in-out infinite; }`}</style>
  </div>
);

// ─── F. AI CHAT DRAWER ────────────────────────────────────────────
const ChatDrawer = ({ open, onClose, ctx }) => (
  <div
    className="fixed top-0 right-0 h-full w-[360px] bg-zinc-950 border-l border-cyan-700/40 z-40 transition-transform"
    style={{ transform: open ? 'translateX(0)' : 'translateX(100%)', boxShadow: '-10px 0 40px rgba(34,211,238,0.15)' }}>
    <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 bg-gradient-to-r from-cyan-900/40 to-zinc-950">
      <div className="flex items-center gap-2">
        <span className="text-cyan-300 font-bold text-[13px]">🤖 SentCom AI</span>
        <Pill color="cyan" className="text-[10px]">{ctx}</Pill>
      </div>
      <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100 text-[14px]">✕</button>
    </div>
    <div className="p-3 space-y-3 overflow-auto h-[calc(100vh-110px)]">
      <div className="text-[11px] text-zinc-500 italic">Context-bound to <span className="text-cyan-400">FDX · Thinking pane</span>. I see what you see.</div>

      {/* sample ai exchange */}
      <div className="bg-zinc-900/60 border border-zinc-800 rounded p-2 text-[12px]">
        <div className="text-zinc-500 text-[10px] mb-1">you · 14:03</div>
        <div className="text-zinc-200">Why are we evaluating gap_fade and not momentum_breakout on FDX?</div>
      </div>
      <div className="bg-cyan-950/30 border border-cyan-800/50 rounded p-2 text-[12px]">
        <div className="text-cyan-400 text-[10px] mb-1">SentCom · 14:03</div>
        <div className="text-zinc-200 leading-relaxed">
          I considered <b>momentum_breakout</b> first but its R:R landed at <span className="font-mono text-amber-300">1.42</span> against your floor of <span className="font-mono">1.8</span>. <b>gap_fade</b> came in at <span className="font-mono text-emerald-300">2.8</span> with VWAP reclaim setup intact, so I downgraded MB to a watch-only candidate.
          <div className="mt-2 text-[11px] text-zinc-400 italic">Decided 6s ago · 18/24 ML pass · Tier A regime.</div>
        </div>
      </div>
      <div className="bg-zinc-900/60 border border-zinc-800 rounded p-2 text-[12px]">
        <div className="text-zinc-500 text-[10px] mb-1">you · 14:04</div>
        <div className="text-zinc-200">Show the gates that failed for momentum_breakout.</div>
      </div>
      <div className="bg-cyan-950/30 border border-cyan-800/50 rounded p-2 text-[12px]">
        <div className="text-cyan-400 text-[10px] mb-1">SentCom · 14:04</div>
        <div className="text-zinc-200 leading-relaxed mb-2">3 gates blocked it on FDX:</div>
        <ul className="space-y-1 text-[11px]">
          <li className="flex items-center gap-2"><span className="text-rose-400">✕</span><span className="flex-1 text-zinc-300">R:R floor</span><span className="font-mono text-rose-400">1.42 / 1.8</span></li>
          <li className="flex items-center gap-2"><span className="text-rose-400">✕</span><span className="flex-1 text-zinc-300">vol consistency</span><span className="font-mono text-rose-400">0.6× / 1.2×</span></li>
          <li className="flex items-center gap-2"><span className="text-amber-400">⚠</span><span className="flex-1 text-zinc-300">trend persistence</span><span className="font-mono text-amber-400">borderline</span></li>
        </ul>
      </div>
      <div className="text-[10px] text-zinc-600 italic text-center pt-2">Try: "what changed?" · "show me the bracket OCA" · "explain orph-GTC" · ⌘K to close</div>
    </div>
    <div className="absolute bottom-0 inset-x-0 p-2 border-t border-zinc-800 bg-zinc-950">
      <input className="w-full bg-zinc-900 border border-zinc-800 focus:border-cyan-700 rounded px-2 py-1.5 text-[12px] text-zinc-100 outline-none" placeholder="ask anything about FDX or system state…" />
    </div>
  </div>
);

// ─── MAIN ─────────────────────────────────────────────────────────
export const V6NextMockup = () => {
  const [state, setState] = useState('cyan');
  const [scrub, setScrub] = useState(72);
  const [riskPct, setRiskPct] = useState(22);
  const [chatOpen, setChatOpen] = useState(false);
  const [actionBarDismissed, setActionBarDismissed] = useState(false);

  // animate risk rail toward state target
  useEffect(() => {
    const target = state==='cyan'?22 : state==='amber'?54 : 88;
    const id = setInterval(() => setRiskPct(p => p < target ? Math.min(target, p+1) : p > target ? Math.max(target, p-1) : p), 30);
    return () => clearInterval(id);
  }, [state]);

  // re-show action bar when re-entering rose
  useEffect(() => {
    if (state === 'rose') setActionBarDismissed(false);
  }, [state]);

  // ⌘K toggles chat
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setChatOpen(o => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const verdictSegs = useMemo(() => state==='cyan'
    ? [{label:'Regime',pct:75,color:'#34d399'},{label:'Consensus',pct:80,color:'#22d3ee'},{label:'Cross-Mdl',pct:70,color:'#a78bfa'},{label:'Live',pct:12,color:'#fb7185'},{label:'Quality',pct:78,color:'#fbbf24'}]
    : state==='amber'
    ? [{label:'Regime',pct:55,color:'#34d399'},{label:'Consensus',pct:48,color:'#22d3ee'},{label:'Cross-Mdl',pct:50,color:'#a78bfa'},{label:'Live',pct:35,color:'#fb7185'},{label:'Quality',pct:60,color:'#fbbf24'}]
    : [{label:'Regime',pct:25,color:'#34d399'},{label:'Consensus',pct:30,color:'#22d3ee'},{label:'Cross-Mdl',pct:30,color:'#a78bfa'},{label:'Live',pct:75,color:'#fb7185'},{label:'Quality',pct:35,color:'#fbbf24'}]
  , [state]);
  const score = state==='cyan' ? 43 : state==='amber' ? 18 : -22;

  // CONCEPT A — trigger condition progress (state-aware)
  const triggers = state==='rose'
    ? [{label:'5m vol > 1.5× avg', pct:100, suffix:'+92%'}, {label:'VWAP reclaim above $362.95', pct:100, suffix:'held 12s'}, {label:'Both held 8s', pct:100, suffix:'READY'}]
    : state==='amber'
    ? [{label:'5m vol > 1.5× avg', pct:78, suffix:'+33%'}, {label:'VWAP reclaim above $362.95', pct:55, suffix:'partial'}, {label:'Both held 8s', pct:35, suffix:'4s/8s'}]
    : [{label:'5m vol > 1.5× avg', pct:42, suffix:'+12%'}, {label:'VWAP reclaim above $362.95', pct:18, suffix:'below'}, {label:'Both held 8s', pct:0, suffix:'0s/8s'}];

  // positions (CONCEPT B + G + H)
  const positions = [
    { sym:'FDX',  side:'DAY 2 long', pnl:'+$648', sl:354.20, entry:368.04, pt:374.44, current:371.10, color:'emerald', recent:false },
    { sym:'UPS',  side:'DAY 2 long', pnl:'-$124', sl:142.50, entry:148.30, pt:153.80, current:144.20, color:'rose',    recent:state!=='cyan' },
    { sym:'SBUX', side:'SHORT',      pnl:'+$258', sl:88.50,  entry:84.20,  pt:79.10,  current:81.30,  color:'emerald', recent:false },
    { sym:'ADBE', side:'SHORT',      pnl:'-$2',   sl:512.0,  entry:498.5,  pt:481.0,  current:498.6,  color:'zinc',    recent:false },
    { sym:'LITE', side:'LONG',       pnl:'-$121', sl:55.40,  entry:58.20,  pt:62.50,  current:56.10,  color:'rose',    recent:state==='rose' },
    { sym:'LIN',  side:'SHORT',      pnl:'+$5',   sl:445.0,  entry:438.5,  pt:425.0,  current:438.0,  color:'zinc',    recent:false },
  ];
  // aggregate P&L sparkline (G)
  const aggregatePnl = state==='rose' ? [600,620,610,630,650,640,620,580,520,480,440,400,360,320,280] : [400,420,450,470,490,510,520,540,560,590,610,620,640,650,657];

  return (
    <div className="h-screen w-screen bg-zinc-900 text-zinc-100 flex flex-col overflow-hidden font-sans relative">
      <Heartbeat state={state} />
      <TopStrip state={state} setState={setState} onToggleChat={() => setChatOpen(o => !o)} chatOpen={chatOpen} />
      <KpiRibbon state={state} />

      {/* D — sticky action bar in rose */}
      {state==='rose' && !actionBarDismissed && <ActionBar onDismiss={() => setActionBarDismissed(true)} />}

      <div className="flex-1 flex overflow-hidden">
        <RiskRail pct={riskPct} />

        {/* SCANNER */}
        <div className="w-[230px] bg-zinc-950 border-r border-zinc-800 flex flex-col flex-shrink-0">
          <div className="px-2 py-1.5 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] text-zinc-400 uppercase tracking-wider font-bold">Scanner · Live</span>
            <Pill color="cyan" className="text-[10px]">12 hits</Pill>
          </div>
          <div className="flex-1 overflow-auto">
            <VibeRow sym="FDX"  mood="fresh"     conf={78} spark={[28,30,29,32,34,36,38,40,42,44]} reason="EVALUATING gap_fade · ML 78%" recent={state!=='cyan'}/>
            <VibeRow sym="VLO"  mood="fresh"     conf={71} spark={[30,32,31,34,38,42,45,48,52,58]} reason="gap_fade primary · PASS 14/16" />
            <VibeRow sym="VRT"  mood="high-vol"  conf={68} spark={[20,28,22,32,26,38,30,42,34,46]} reason="wedge break · vol >2× avg" />
            <VibeRow sym="UPS"  mood="steady up" conf={64} spark={[38,40,39,42,44,43,46,48,50,52]} reason="DAY 2 long · partial fill" />
            <VibeRow sym="PWR"  mood="steady up" conf={62} spark={[40,42,41,44,46,45,48,50,52,55]} reason="off sides short flagged · ATR-tight" />
            <VibeRow sym="MCHP" mood="choppy"    conf={56} spark={[42,40,44,41,43,40,42,41,43,42]} reason="VWAP whipsaw · waiting on regime" />
            <VibeRow sym="TNA"  mood="fading"    conf={48} spark={[55,52,48,45,42,40,38,34,32,30]} reason="momentum_breakout failing · vol thin" />
            <VibeRow sym="SBUX" mood="fading"    conf={40} spark={[50,48,46,44,42,40,38,36,34,32]} reason="short setup degrading" />
          </div>
        </div>

        {/* CHART + VERDICT */}
        <div className="flex-1 flex flex-col bg-zinc-900 min-w-0">
          <div className="flex-1 bg-gradient-to-b from-zinc-900 to-zinc-950 border-b border-zinc-800 flex items-center justify-center relative">
            <div className="absolute top-2 left-3 flex items-center gap-2">
              <span className="font-mono text-[18px] font-bold text-zinc-100">FDX</span>
              <Pill color="cyan">EVAL · 6s</Pill>
              <Pill color="emerald">OPEN · 5h</Pill>
              <span className="text-[11px] text-zinc-400 ml-2">R:R 2.8 · 256sh</span>
            </div>
            <div className="absolute top-2 right-3 flex items-center gap-1">
              {['1m','5m','15m','1h','1d'].map(t => <Pill key={t} color={t==='5m'?'cyan':'zinc'} className="text-[10px]">{t}</Pill>)}
            </div>
            <div className="text-[12px] text-zinc-700 italic">[ TradingView chart — same component as today ]</div>
          </div>

          <div className="bg-zinc-950 border-t border-zinc-800 p-3 flex items-center gap-4 flex-shrink-0">
            <ProvenanceRing size={88} score={score} segs={verdictSegs} />
            <div className="flex-1 grid grid-cols-5 gap-x-4 gap-y-1 text-[11px]">
              {verdictSegs.map((s,i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{background:s.color}} />
                  <span className="text-zinc-400 flex-1">{s.label}</span>
                  <span className="font-mono" style={{color:s.color}}>{s.pct >= 50 ? '+' : ''}{Math.round((s.pct-50)/3)}</span>
                </div>
              ))}
            </div>
            <div className="text-[10px] text-zinc-500 italic max-w-[180px] text-right">↑ slice size = how much each input mattered · center = final score</div>
          </div>
        </div>

        {/* THINKING PANE — glass+halo + concept A trigger progress */}
        <div className="w-[340px] p-2 flex-shrink-0">
          <GlassHaloPane state={state} label="THINKING · FDX">
            <div className="p-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <Pill color="cyan">EVALUATING gap_fade LONG</Pill>
                <Pill color="amber">TQS 80</Pill>
                <Pill color="emerald">A+</Pill>
                <Pill color="violet">ML 78%</Pill>
              </div>
              <div className="grid grid-cols-3 gap-2 text-[11px]">
                <div><div className="text-zinc-500">Entry</div><div className="font-mono text-zinc-200">$368.04</div></div>
                <div><div className="text-zinc-500">SL</div><div className="font-mono text-rose-300">$352.84</div></div>
                <div><div className="text-zinc-500">PT</div><div className="font-mono text-emerald-300">$374.44</div></div>
              </div>

              {/* CONCEPT A — trigger progress */}
              <div className="border-t border-zinc-800 pt-2">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="font-bold text-cyan-300 text-[12px]">Watching for trigger</div>
                  <span className="text-[10px] text-zinc-500 font-mono">next eval 2.3s</span>
                </div>
                <div className="space-y-1.5">
                  {triggers.map((t,i) => <TriggerLine key={i} {...t} />)}
                </div>
                {triggers.every(t => t.pct >= 100) && (
                  <div className="mt-2 text-center text-[11px] font-bold text-emerald-300 bg-emerald-950/40 border border-emerald-700/50 rounded py-1 animate-pulse">
                    ⚡ ALL CONDITIONS MET — ORDER FIRING
                  </div>
                )}
              </div>

              {state !== 'cyan' && (
                <div className={`border-t border-zinc-800 pt-2 text-[11px] ${state==='amber'?'text-amber-300':'text-rose-300'} font-medium flex items-start gap-1.5`}>
                  <span className="text-[14px] leading-none">{state==='amber'?'⚠':'🛑'}</span>
                  <span>
                    {state==='amber'
                      ? <><b>2 throttle hits in last 5min</b> on UPS — bracket reissue cooldown active. share_drift on FDX auto-reconciled 18s ago.</>
                      : <><b>KILL SWITCH TRIPPED</b> · 1 orph-GTC detected at IB · pusher RPC 480ms · auto-cancel running.</>}
                  </span>
                </div>
              )}
              <div className="border-t border-zinc-800 pt-2 text-[10px] text-zinc-500 italic">
                "Considered momentum_breakout but R:R 1.42 below floor. Will downgrade to Tier B if vol stays thin past 14:30."
              </div>
            </div>
          </GlassHaloPane>
        </div>

        {/* OPEN POSITIONS — G aggregate sparkline + B proximity bars + H recent */}
        <div className="w-[280px] bg-zinc-950 border-l border-zinc-800 flex flex-col flex-shrink-0">
          {/* G — aggregate header with sparkline */}
          <div className="px-2 py-1.5 border-b border-zinc-800">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-zinc-400 uppercase tracking-wider font-bold">Open · 6</span>
              <span className={`text-[13px] font-mono font-bold ${state==='rose'?'text-rose-300':'text-emerald-400'}`}>{state==='rose'?'-$340':'+$657'}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-zinc-600 uppercase">P&amp;L · last hour</span>
              <Sparkline points={aggregatePnl} color={state==='rose'?'rose':'emerald'} w={170} h={20} />
            </div>
          </div>
          <div className="flex-1 overflow-auto divide-y divide-zinc-900">
            {positions.map(p => (
              <div key={p.sym} className={`px-2 py-2 hover:bg-zinc-900/50 cursor-pointer relative ${p.recent ? 'ring-1 ring-amber-500/50 bg-amber-950/10' : ''}`}>
                {p.recent && <span className="absolute top-1 right-1 text-[8px] uppercase tracking-wider text-amber-300 font-bold animate-pulse">CHANGED</span>}
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-zinc-100 w-12 text-[12px]">{p.sym}</span>
                  <Pill color={p.side.includes('SHORT')?'rose':p.side.includes('DAY 2')?'cyan':'emerald'} className="text-[9px]">{p.side}</Pill>
                  <span className={`font-mono text-[12px] ml-auto ${p.color==='emerald'?'text-emerald-300':p.color==='rose'?'text-rose-300':'text-zinc-400'}`}>{p.pnl}</span>
                </div>
                {/* B — proximity bar replaces per-row sparkline */}
                <ProximityBar sl={p.sl} entry={p.entry} pt={p.pt} current={p.current} />
                <div className="flex items-center justify-between mt-3 ml-0 text-[9px] text-zinc-600 font-mono">
                  <span>SL <span className="text-rose-400">{p.sl}</span></span>
                  <span>now <span className="text-zinc-300">{p.current}</span></span>
                  <span>PT <span className="text-emerald-400">{p.pt}</span></span>
                </div>
              </div>
            ))}
          </div>
          <div className="px-2 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600 italic">
            ↑ each row: SL→PT proximity · dot = current
          </div>
        </div>
      </div>

      {/* E — narrative strip */}
      <NarrativeStrip onJump={(t) => setScrub(t)} />
      <TimeScrubber scrub={scrub} setScrub={setScrub} />

      {/* F — chat drawer overlay */}
      <ChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} ctx="FDX · Thinking" />

      <div className="bg-zinc-950 border-t border-zinc-900 px-3 py-1 flex items-center justify-between text-[10px] text-zinc-600 flex-shrink-0">
        <span>V6.next++ · concepts ①②③④⑤⑦⑧ + enhancements A–J active</span>
        <a href="?preview=v6concepts" className="text-violet-400 hover:underline">← back to concept explainers</a>
      </div>
    </div>
  );
};

export default V6NextMockup;
