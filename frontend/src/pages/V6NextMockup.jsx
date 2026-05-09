/* eslint-disable react/no-unescaped-entities */
/**
 * V6.next Mockup — V6.2 layout fused with approved concepts:
 *   ① Heartbeat pulse line (top edge)
 *   ② Risk meter (left edge rail)
 *   ③ Sparklines on every counter
 *   ④ Glass-morphism + ambient halo on Thinking pane (state-driven)
 *   ⑤ Symbol vibe tints in scanner
 *   ⑦ Time scrubber (bottom strip)
 *   ⑧ Provenance ring on the verdict block
 *
 * Hits at ?preview=v6mock
 */
import React, { useState, useEffect } from 'react';

// ─── tiny atoms ───────────────────────────────────────────────────
const Sparkline = ({ points, color = 'emerald', w = 60, h = 16 }) => {
  const max = Math.max(...points), min = Math.min(...points), range = max - min || 1;
  const stroke = { cyan:'#22d3ee', emerald:'#34d399', amber:'#fbbf24', rose:'#fb7185', violet:'#c084fc', zinc:'#a1a1aa' }[color];
  const d = points.map((p,i) => `${(i/(points.length-1))*w},${h-((p-min)/range)*h}`).join(' ');
  const lastY = h-((points[points.length-1]-min)/range)*h;
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

// ─── ① HEARTBEAT PULSE BAR (top edge) ─────────────────────────────
const Heartbeat = ({ state }) => {
  // state-driven speed: cyan=2s, amber=1.2s, rose=0.7s
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

// ─── ② RISK METER RAIL (left edge) ────────────────────────────────
const RiskRail = ({ pct = 22 }) => {
  const color = pct < 50 ? 'bg-emerald-500' : pct < 80 ? 'bg-amber-500' : 'bg-rose-500';
  const text  = pct < 50 ? 'text-emerald-300' : pct < 80 ? 'text-amber-300' : 'text-rose-300';
  return (
    <div className="w-[22px] bg-zinc-950 border-r border-zinc-800/60 flex flex-col items-center py-2 flex-shrink-0 group relative">
      <div className="text-[8px] text-zinc-600 font-mono leading-tight rotate-180 mb-1" style={{writingMode:'vertical-rl'}}>DLP</div>
      <div className="relative w-2 flex-1 bg-zinc-900 rounded-sm overflow-hidden">
        <div className={`absolute bottom-0 left-0 right-0 ${color} transition-all`} style={{ height: `${pct}%`, boxShadow: `0 0 8px currentColor` }} />
      </div>
      <div className={`text-[9px] font-mono ${text} font-bold mt-1`}>{pct}%</div>
      {/* hover tooltip */}
      <div className="absolute left-full top-2 ml-1 hidden group-hover:block bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-[11px] z-50 whitespace-nowrap">
        DLP budget: <span className="font-mono text-emerald-300">$2,000 / day</span> · used <span className={`font-mono ${text}`}>${(pct*20).toFixed(0)}</span>
      </div>
    </div>
  );
};

// ─── ⑧ PROVENANCE RING ────────────────────────────────────────────
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
      <text x={c} y={c-2} textAnchor="middle" fontSize="13" fontWeight="700" fill="#34d399">+{score}</text>
      <text x={c} y={c+10} textAnchor="middle" fontSize="8" fill="#71717a">GO</text>
    </svg>
  );
};

// ─── ⑤ Vibe-tinted scanner row ────────────────────────────────────
const VibeRow = ({ sym, mood, conf, spark, reason }) => {
  const tints = {
    'steady up':  { bg:'linear-gradient(90deg, rgba(52,211,153,0.13), transparent 70%)', dot:'#34d399', label:'text-emerald-400', moodColor:'emerald' },
    'choppy':     { bg:'linear-gradient(90deg, rgba(251,191,36,0.13), transparent 70%)', dot:'#fbbf24', label:'text-amber-400',   moodColor:'amber' },
    'fresh':      { bg:'linear-gradient(90deg, rgba(34,211,238,0.13), transparent 70%)', dot:'#22d3ee', label:'text-cyan-400',    moodColor:'cyan' },
    'fading':     { bg:'linear-gradient(90deg, rgba(251,113,133,0.13), transparent 70%)', dot:'#fb7185', label:'text-rose-400',   moodColor:'rose' },
    'high-vol':   { bg:'linear-gradient(90deg, rgba(192,132,252,0.13), transparent 70%)', dot:'#c084fc', label:'text-violet-400', moodColor:'violet' },
  };
  const t = tints[mood];
  return (
    <div className="border-b border-zinc-900/60 px-2 py-1.5 hover:brightness-125 cursor-pointer" style={{ background: t.bg }}>
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: t.dot, boxShadow:`0 0 4px ${t.dot}` }} />
        <span className="font-mono font-bold text-zinc-100 w-10 text-[12px]">{sym}</span>
        <Sparkline points={spark} color={t.moodColor} w={42} h={12} />
        <span className={`text-[9px] uppercase tracking-wider ${t.label} ml-auto italic`}>{mood}</span>
        <span className="font-mono text-[11px] text-zinc-300 w-9 text-right">{conf}%</span>
      </div>
      <div className="text-[10px] text-zinc-500 ml-3.5 italic mt-0.5 truncate">{reason}</div>
    </div>
  );
};

// ─── ④ GLASS HALO PANE (the heart of the demo) ────────────────────
const GlassHaloPane = ({ state, children, label }) => {
  const palette = {
    cyan:    { color:'#22d3ee', name:'NORMAL',   border:'rgba(34,211,238,0.85)',  glow:'rgba(34,211,238,0.55)',  inner:'rgba(34,211,238,0.10)', accent:'text-cyan-300' },
    amber:   { color:'#fbbf24', name:'ELEVATED', border:'rgba(251,191,36,0.90)',  glow:'rgba(251,191,36,0.65)',  inner:'rgba(251,191,36,0.12)', accent:'text-amber-300' },
    rose:    { color:'#fb7185', name:'CRITICAL', border:'rgba(251,113,133,0.95)', glow:'rgba(251,113,133,0.75)', inner:'rgba(251,113,133,0.14)', accent:'text-rose-300' },
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
        <span className={`text-[10px] uppercase tracking-widest font-bold ${p.accent}`} style={{ textShadow: `0 0 8px ${p.color}` }}>● {p.name}</span>
      </div>
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  );
};

// ─── ⑦ TIME SCRUBBER (bottom strip) ───────────────────────────────
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
  // map % → time string between 9:30 and 15:55
  const startMin = 9*60+30, endMin = 15*60+55;
  const m = startMin + (endMin-startMin)*(scrub/100);
  const tStr = `${String(Math.floor(m/60)).padStart(2,'0')}:${String(Math.floor(m%60)).padStart(2,'0')}`;
  return (
    <div className="bg-zinc-950 border-t border-zinc-800/60 px-3 py-2 flex items-center gap-3 flex-shrink-0">
      <span className="text-[10px] text-zinc-500 font-mono">9:30</span>
      <div className="flex-1 relative h-5">
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 bg-zinc-800 rounded-full" />
        {events.map((e,i) => (
          <div key={i} className="absolute top-1/2 -translate-y-1/2 w-1.5 h-3 rounded-sm cursor-pointer group"
            style={{ left: `${e.t}%`, background: e.color, boxShadow: `0 0 4px ${e.color}` }}>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[10px] whitespace-nowrap z-50">{e.label}</div>
          </div>
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

// ─── KPI ribbon with sparklines (③) ───────────────────────────────
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
        <Sparkline points={[235,236,235,237,238,237,238,237,237,238,237,237,237,237,237]} color="zinc" w={50} h={16} />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">peak <span className="font-mono">$238,012</span></div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Open Risk</div>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-[20px] font-bold leading-none ${state==='rose'?'text-rose-300':state==='amber'?'text-amber-300':'text-amber-300'}`}>$2,512</span>
        <Sparkline points={state==='rose'?[1,2,2,3,3,4,5,5,6,6,7,8,8,9,10]:[2,2,2,2,2,3,2,2,3,3,2,3,3,2,2]} color={state==='rose'?'rose':'amber'} w={50} h={16} />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">6 pos · max <span className="font-mono">$2.5K</span></div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Throttle / 5min</div>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-[20px] font-bold leading-none ${state==='cyan'?'text-zinc-300':state==='amber'?'text-amber-300':'text-rose-300'}`}>{state==='cyan'?0:state==='amber'?2:5}</span>
        <Sparkline points={state==='cyan'?[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]:state==='amber'?[0,0,0,1,0,1,2,1,2,2,2,2,1,2,2]:[0,1,1,2,2,3,3,4,4,5,4,5,5,5,5]} color={state==='cyan'?'zinc':state==='amber'?'amber':'rose'} w={50} h={16} />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">order-router cooldowns</div>
    </div>
    <div className="w-px bg-zinc-800" />
    <div className="flex flex-col">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Pusher RPC</div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[20px] font-bold text-cyan-300 leading-none">3ms</span>
        <Sparkline points={[3,2,3,3,2,3,4,3,3,2,3,3,4,3,3]} color="cyan" w={50} h={16} />
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">321 quotes · 6/min</div>
    </div>
  </div>
);

// ─── Top strip (pipeline pills + system health) ───────────────────
const TopStrip = ({ state, setState }) => {
  const stateMap = {
    cyan:  { label:'ALL SYSTEMS',  color:'emerald', detail:'0 drift · 0 thr · 0 orph' },
    amber: { label:'1 WARNING',    color:'amber',   detail:'2 thr · 1 drift (auto)' },
    rose:  { label:'KILL TRIPPED', color:'rose',    detail:'1 orph-GTC · pusher 480ms' },
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
        {/* state cycler — demonstrates ④ */}
        <div className="flex items-center gap-1 bg-zinc-900 rounded p-0.5 border border-zinc-800">
          <span className="text-[10px] text-zinc-500 px-1">halo demo:</span>
          {['cyan','amber','rose'].map(s => (
            <button key={s} onClick={() => setState(s)}
              className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded transition ${state===s ? (s==='cyan'?'bg-cyan-700/60 text-cyan-100':s==='amber'?'bg-amber-700/60 text-amber-100':'bg-rose-700/60 text-rose-100') : 'text-zinc-500 hover:text-zinc-300'}`}>
              {s}
            </button>
          ))}
        </div>
        <Pill color="amber">PAPER · DUN615665</Pill>
        <Pill color={s.color}>● {s.label} <span className="text-zinc-500 font-mono ml-1 text-[10px]">{s.detail}</span></Pill>
        <Pill color="cyan">🤖 AI <span className="text-zinc-500 font-mono ml-1 text-[10px]">⌘K</span></Pill>
      </div>
    </div>
  );
};

// ─── MAIN ─────────────────────────────────────────────────────────
export const V6NextMockup = () => {
  const [state, setState] = useState('cyan'); // ④ halo state
  const [scrub, setScrub] = useState(72);     // ⑦ time scrubber
  const [riskPct, setRiskPct] = useState(22); // ② risk rail

  // animate risk rail upward over the 3 states
  useEffect(() => {
    const target = state==='cyan'?22 : state==='amber'?54 : 88;
    const id = setInterval(() => setRiskPct(p => p < target ? Math.min(target, p+1) : p > target ? Math.max(target, p-1) : p), 30);
    return () => clearInterval(id);
  }, [state]);

  const verdictSegs = state==='cyan'
    ? [{label:'Regime',pct:75,color:'#34d399'},{label:'Consensus',pct:80,color:'#22d3ee'},{label:'Cross-Mdl',pct:70,color:'#a78bfa'},{label:'Live',pct:12,color:'#fb7185'},{label:'Quality',pct:78,color:'#fbbf24'}]
    : state==='amber'
    ? [{label:'Regime',pct:55,color:'#34d399'},{label:'Consensus',pct:48,color:'#22d3ee'},{label:'Cross-Mdl',pct:50,color:'#a78bfa'},{label:'Live',pct:35,color:'#fb7185'},{label:'Quality',pct:60,color:'#fbbf24'}]
    : [{label:'Regime',pct:25,color:'#34d399'},{label:'Consensus',pct:30,color:'#22d3ee'},{label:'Cross-Mdl',pct:30,color:'#a78bfa'},{label:'Live',pct:75,color:'#fb7185'},{label:'Quality',pct:35,color:'#fbbf24'}];
  const score = state==='cyan' ? 43 : state==='amber' ? 18 : -22;

  return (
    <div className="h-screen w-screen bg-zinc-900 text-zinc-100 flex flex-col overflow-hidden font-sans">
      {/* ① heartbeat top edge */}
      <Heartbeat state={state} />

      {/* top strip + KPI ribbon */}
      <TopStrip state={state} setState={setState} />
      <KpiRibbon state={state} />

      {/* main row: risk rail | scanner | chart+verdict | thinking | positions */}
      <div className="flex-1 flex overflow-hidden">
        {/* ② RISK METER LEFT EDGE */}
        <RiskRail pct={riskPct} />

        {/* SCANNER (⑤ vibe tints + sparklines) */}
        <div className="w-[210px] bg-zinc-950 border-r border-zinc-800 flex flex-col flex-shrink-0">
          <div className="px-2 py-1.5 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] text-zinc-400 uppercase tracking-wider font-bold">Scanner · Live</span>
            <Pill color="cyan" className="text-[10px]">12 hits</Pill>
          </div>
          <div className="flex-1 overflow-auto">
            <VibeRow sym="PWR"  mood="steady up" conf={62} spark={[40,42,41,44,46,45,48,50,52,55]} reason="off sides short flagged · ATR-tight" />
            <VibeRow sym="MCHP" mood="choppy"    conf={56} spark={[42,40,44,41,43,40,42,41,43,42]} reason="VWAP whipsaw · waiting on regime" />
            <VibeRow sym="VLO"  mood="fresh"     conf={71} spark={[30,32,31,34,38,42,45,48,52,58]} reason="gap_fade primary · PASS 14/16" />
            <VibeRow sym="TNA"  mood="fading"    conf={48} spark={[55,52,48,45,42,40,38,34,32,30]} reason="momentum_breakout failing · vol thin" />
            <VibeRow sym="VRT"  mood="high-vol"  conf={68} spark={[20,28,22,32,26,38,30,42,34,46]} reason="wedge break · vol >2× avg" />
            <VibeRow sym="FDX"  mood="fresh"     conf={78} spark={[28,30,29,32,34,36,38,40,42,44]} reason="EVALUATING gap_fade · ML 78%" />
            <VibeRow sym="UPS"  mood="steady up" conf={64} spark={[38,40,39,42,44,43,46,48,50,52]} reason="DAY 2 long · partial fill" />
            <VibeRow sym="SBUX" mood="fading"    conf={40} spark={[50,48,46,44,42,40,38,36,34,32]} reason="short setup degrading" />
          </div>
        </div>

        {/* CHART + VERDICT */}
        <div className="flex-1 flex flex-col bg-zinc-900 min-w-0">
          {/* chart placeholder */}
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

          {/* VERDICT row with ⑧ provenance ring */}
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
            <div className="text-[10px] text-zinc-500 italic max-w-[200px] text-right">↑ donut at a glance · slice size = how much each input mattered · center = final score</div>
          </div>
        </div>

        {/* THINKING PANE — ④ glass + halo (THE STAR) */}
        <div className="w-[340px] p-2 flex-shrink-0">
          <GlassHaloPane state={state} label="THINKING · FDX">
            <div className="p-3 space-y-2">
              <div className="flex items-center gap-2">
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
              <div className="border-t border-zinc-800 pt-2 text-[12px]">
                <div className="font-bold text-cyan-300 mb-1">Watching for trigger</div>
                <ul className="space-y-1 text-zinc-300 text-[11px] pl-3 list-disc">
                  <li>5m vol &gt; 1.5× avg <span className="text-zinc-500">(need +67%)</span></li>
                  <li>VWAP reclaim above $362.95</li>
                  <li>Auto-fires when both held 8s</li>
                </ul>
              </div>
              {state !== 'cyan' && (
                <div className={`border-t border-zinc-800 pt-2 text-[11px] ${state==='amber'?'text-amber-300':'text-rose-300'} font-medium`}>
                  {state==='amber' ? (
                    <>⚠ <b>2 throttle hits in last 5min</b> on UPS — bracket reissue cooldown active. share_drift on FDX auto-reconciled 18s ago.</>
                  ) : (
                    <>🛑 <b>KILL SWITCH TRIPPED</b> · 1 orph-GTC detected at IB · pusher RPC 480ms · auto-cancel running.</>
                  )}
                </div>
              )}
              <div className="border-t border-zinc-800 pt-2 text-[10px] text-zinc-500 italic">
                "Considered momentum_breakout but R:R 1.42 below floor. Will downgrade to Tier B if vol stays thin past 14:30."
              </div>
            </div>
          </GlassHaloPane>
        </div>

        {/* OPEN POSITIONS (③ sparklines on every counter) */}
        <div className="w-[260px] bg-zinc-950 border-l border-zinc-800 flex flex-col flex-shrink-0">
          <div className="px-2 py-1.5 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] text-zinc-400 uppercase tracking-wider font-bold">Open · 6</span>
            <span className="text-[11px] text-emerald-400 font-mono">+$657</span>
          </div>
          <div className="flex-1 overflow-auto divide-y divide-zinc-900">
            {[
              { sym:'FDX',  side:'DAY 2 long', pnl:'+$648', pos:true,  spark:[28,30,29,32,34,36,38,40,42,44], color:'emerald' },
              { sym:'UPS',  side:'DAY 2 long', pnl:'-$124', pos:false, spark:[40,42,40,38,36,34,32,30,28,30], color:'rose' },
              { sym:'SBUX', side:'SHORT',      pnl:'+$258', pos:true,  spark:[20,22,24,26,28,30,32,34,36,38], color:'emerald' },
              { sym:'ADBE', side:'SHORT',      pnl:'-$2',   pos:false, spark:[34,32,33,34,33,34,33,34,33,33], color:'zinc' },
              { sym:'LITE', side:'LONG',       pnl:'-$121', pos:false, spark:[40,38,36,34,32,30,32,30,28,28], color:'rose' },
              { sym:'LIN',  side:'SHORT',      pnl:'+$5',   pos:true,  spark:[30,30,31,30,31,31,31,32,31,31], color:'zinc' },
            ].map(p => (
              <div key={p.sym} className="px-2 py-1.5 hover:bg-zinc-900/50 cursor-pointer">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-zinc-100 w-12 text-[12px]">{p.sym}</span>
                  <Pill color={p.side.includes('SHORT')?'rose':p.side.includes('DAY 2')?'cyan':'emerald'} className="text-[9px]">{p.side}</Pill>
                  <span className={`font-mono text-[12px] ml-auto ${p.color==='emerald'?'text-emerald-300':p.color==='rose'?'text-rose-300':'text-zinc-400'}`}>{p.pnl}</span>
                </div>
                <div className="flex items-center gap-2 mt-1 ml-1">
                  <Sparkline points={p.spark} color={p.color} w={120} h={14} />
                  <span className="text-[9px] text-zinc-600 italic ml-auto">{p.pos?'partial':'full'}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="px-2 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600 italic">
            ↑ each row: position P&amp;L sparkline last 20 ticks
          </div>
        </div>
      </div>

      {/* ⑦ TIME SCRUBBER */}
      <TimeScrubber scrub={scrub} setScrub={setScrub} />

      {/* tiny footer credit */}
      <div className="bg-zinc-950 border-t border-zinc-900 px-3 py-1 flex items-center justify-between text-[10px] text-zinc-600 flex-shrink-0">
        <span>V6.next mockup · concepts ①②③④⑤⑦⑧ active · ⑥ skipped</span>
        <a href="?preview=v6concepts" className="text-violet-400 hover:underline">← back to concept explainers</a>
      </div>
    </div>
  );
};

export default V6NextMockup;
