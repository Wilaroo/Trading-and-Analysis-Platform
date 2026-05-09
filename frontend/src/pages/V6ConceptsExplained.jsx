/**
 * V6ConceptsExplained.jsx — every concept demonstrated in isolation
 * with a plain-English explanation and a before/after comparison.
 *
 * Hits at ?preview=v6concepts.
 */
import React, { useState, useEffect } from 'react';

const Sparkline = ({ points, color = 'emerald', w = 80, h = 22 }) => {
  const max = Math.max(...points), min = Math.min(...points);
  const range = max - min || 1;
  const stroke = { cyan: '#22d3ee', emerald: '#34d399', amber: '#fbbf24', rose: '#fb7185', violet: '#c084fc' }[color];
  const d = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / range) * h}`).join(' ');
  const last = points[points.length - 1];
  const lastY = h - ((last - min) / range) * h;
  return (
    <svg width={w} height={h} className="inline-block align-middle">
      <polyline points={d} fill="none" stroke={stroke} strokeWidth="1.5" opacity="0.9" />
      <circle cx={w} cy={lastY} r="2" fill={stroke} />
    </svg>
  );
};

const ProvenanceRing = ({ size = 120 }) => {
  const segs = [
    { label: 'Regime',    pct: 75, color: '#34d399' },
    { label: 'Consensus', pct: 80, color: '#22d3ee' },
    { label: 'Cross-Mdl', pct: 70, color: '#a78bfa' },
    { label: 'Live',      pct: 12, color: '#fb7185' },
    { label: 'Quality',   pct: 78, color: '#fbbf24' },
  ];
  const r = size / 2 - 10, c = size / 2;
  const total = segs.reduce((a, s) => a + s.pct, 0);
  let angle = -90;
  return (
    <svg width={size} height={size} className="flex-shrink-0">
      <circle cx={c} cy={c} r={r} fill="none" stroke="#27272a" strokeWidth="3" />
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
        return <path key={i} d={`M ${c} ${c} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`} fill={s.color} opacity="0.7" />;
      })}
      <circle cx={c} cy={c} r={r * 0.55} fill="#09090b" />
      <text x={c} y={c - 4} textAnchor="middle" fontSize="16" fontWeight="700" fill="#34d399">+43</text>
      <text x={c} y={c + 14} textAnchor="middle" fontSize="10" fill="#71717a">GO</text>
    </svg>
  );
};

// ─── A "concept card" — left side BEFORE, right side AFTER ───
const ConceptCard = ({ n, title, plain, before, after, accent = 'cyan' }) => {
  const accentMap = {
    cyan:    'border-cyan-700/60 from-cyan-900/20',
    emerald: 'border-emerald-700/60 from-emerald-900/20',
    amber:   'border-amber-700/60 from-amber-900/20',
    violet:  'border-violet-700/60 from-violet-900/20',
    rose:    'border-rose-700/60 from-rose-900/20',
  };
  return (
    <div className={`bg-gradient-to-br ${accentMap[accent]} to-zinc-950/40 border ${accentMap[accent].split(' ')[0]} rounded-xl p-4 mb-3`}>
      <div className="flex items-start gap-3 mb-3">
        <span className="text-[28px] font-mono text-zinc-600 leading-none">{n}</span>
        <div className="flex-1">
          <h3 className="text-base font-bold text-zinc-100">{title}</h3>
          <p className="text-[13px] text-zinc-400 leading-relaxed mt-0.5">{plain}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 mt-3">
        <div className="bg-zinc-950/60 border border-zinc-800 rounded p-3 min-h-[110px] flex flex-col">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">BEFORE — what V5 has today</div>
          <div className="flex-1 flex items-center justify-center">{before}</div>
        </div>
        <div className="bg-zinc-950/60 border border-cyan-700/30 rounded p-3 min-h-[110px] flex flex-col" style={{ boxShadow: 'inset 0 0 30px rgba(34,211,238,0.06)' }}>
          <div className="text-[11px] text-cyan-400 uppercase tracking-wider mb-2">AFTER — with this concept</div>
          <div className="flex-1 flex items-center justify-center">{after}</div>
        </div>
      </div>
    </div>
  );
};

export const V6ConceptsExplained = () => {
  const [riskPct, setRiskPct] = useState(42);
  const [scrub, setScrub] = useState(78);
  // Animate the risk meter to show what it does
  useEffect(() => {
    const id = setInterval(() => setRiskPct(p => (p < 85 ? p + 1 : 30)), 150);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100 p-6">
      <div className="max-w-[1200px] mx-auto">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-bold text-cyan-300">V6.next — Each Concept Explained</h1>
            <p className="text-[13px] text-zinc-400 mt-0.5">Plain English + side-by-side: today vs with the concept added.</p>
          </div>
          <a href="?preview=v6next" className="text-[12px] text-violet-400 hover:underline">← back to combined brainstorm</a>
        </div>

        {/* ① HEARTBEAT */}
        <ConceptCard n="①" title="Heartbeat pulse line" accent="cyan"
          plain="A thin cyan line at the very top of the app that pulses right-to-left like a heart monitor. Speeds up when the bot is busy evaluating, slows down when idle. You stop noticing it consciously — but you'd instantly notice if it stopped, which means the bot froze."
          before={<div className="text-[12px] text-zinc-500 italic text-center">No visual indicator. You don't know if the bot is actively thinking or stuck — you have to check logs.</div>}
          after={
            <div className="w-full">
              <div className="h-[5px] w-full bg-zinc-950 relative overflow-hidden rounded">
                <div className="absolute inset-y-0 left-0 w-[25%] bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-90" style={{ animation: 'pulse-slide 2s ease-in-out infinite' }} />
              </div>
              <div className="text-[11px] text-zinc-400 mt-2 italic text-center">↑ live pulse. fast = bot busy. slow = bot idle. stopped = something's wrong.</div>
              <style>{`@keyframes pulse-slide { 0% { transform: translateX(0%); } 100% { transform: translateX(400%); } }`}</style>
            </div>
          }
        />

        {/* ② RISK METER */}
        <ConceptCard n="②" title="Risk meter (left edge)" accent="emerald"
          plain="A skinny vertical bar that lives on the very left edge of the entire app. It fills from the bottom upward as you use more of your daily-loss-protection (DLP) budget. Green up to 50%, amber 50-80%, red above. Hover to see the exact number."
          before={<div className="text-[12px] text-zinc-500 italic text-center">Your daily risk used is buried in a stat box somewhere. You have to look for it.</div>}
          after={
            <div className="flex items-center gap-4 w-full">
              <div className="relative w-3 h-24 bg-zinc-900 rounded-sm flex-shrink-0">
                <div className={`absolute bottom-0 left-0 right-0 rounded-sm transition-all ${riskPct < 50 ? 'bg-emerald-500' : riskPct < 80 ? 'bg-amber-500' : 'bg-rose-500'}`}
                  style={{ height: `${riskPct}%`, boxShadow: `0 0 12px currentColor` }} />
              </div>
              <div className="text-[12px] text-zinc-300">
                <div>currently: <span className={`font-mono font-bold ${riskPct < 50 ? 'text-emerald-300' : riskPct < 80 ? 'text-amber-300' : 'text-rose-300'}`}>{riskPct}%</span> of daily risk used</div>
                <div className="text-zinc-500 text-[11px] mt-1">animated demo · grows then resets · in real life it tracks live DLP</div>
              </div>
            </div>
          }
        />

        {/* ③ SPARKLINES */}
        <ConceptCard n="③" title="Sparklines next to every counter" accent="emerald"
          plain="Tiny inline charts (15 ticks of history) printed right next to every number in the UI. Tells you not just what the number IS but whether it's trending up or down or jumping around. Costs almost no horizontal space."
          before={
            <div className="text-center text-[14px] font-mono text-zinc-300">
              <div>P&amp;L <span className="text-emerald-300">+$4,300</span></div>
              <div className="text-[11px] text-zinc-500 italic mt-2">single number · no temporal context · is it climbing? plateau? roller-coaster?</div>
            </div>
          }
          after={
            <div className="text-center text-[14px] font-mono text-zinc-300">
              <div className="flex items-center gap-2 justify-center">
                <span>P&amp;L</span>
                <span className="text-emerald-300">+$4,300</span>
                <Sparkline points={[10, 12, 11, 15, 18, 17, 22, 24, 23, 28, 31, 29, 34, 38, 43]} color="emerald" />
              </div>
              <div className="text-[11px] text-zinc-500 italic mt-2">↑ climbing steadily — shape tells the story instantly</div>
              <div className="flex items-center gap-2 justify-center mt-3">
                <span>Throttle</span>
                <span className="text-amber-300">3</span>
                <Sparkline points={[0, 0, 0, 1, 0, 1, 2, 1, 3, 2, 2, 3, 2, 3, 3]} color="amber" />
              </div>
              <div className="text-[11px] text-zinc-500 italic mt-1">↑ stair-stepping up — bot is hitting throttle more often, possibly a problem</div>
            </div>
          }
        />

        {/* ④ GLASS + HALO */}
        <ConceptCard n="④" title="Glass-morphism + ambient halo" accent="cyan"
          plain="The currently-focused panel (Thinking pane usually) gets a frosted-glass surface and a colored glow border around it. The glow's color tells you the bot's emotional state at a glance: cyan = NORMAL, amber = ELEVATED concern, rose = CRITICAL."
          before={
            <div className="bg-zinc-900 border border-zinc-700 rounded p-3 w-full text-center">
              <div className="text-[12px] text-zinc-300">FDX · evaluating</div>
              <div className="text-[11px] text-zinc-500 italic mt-2">flat panel · no signal about bot's state</div>
            </div>
          }
          after={
            <div className="rounded p-3 w-full text-center" style={{ background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(8px)', border: '1px solid rgba(34,211,238,0.45)', boxShadow: '0 0 30px rgba(34,211,238,0.25), inset 0 0 25px rgba(34,211,238,0.05)' }}>
              <div className="text-[12px] text-cyan-200">FDX · evaluating</div>
              <div className="text-[11px] text-cyan-400 italic mt-2">↑ cyan halo = bot is calm/normal. would turn amber if concerned, rose if critical.</div>
            </div>
          }
        />

        {/* ⑤ VIBE TINTS */}
        <ConceptCard n="⑤" title="Symbol vibe tints" accent="violet"
          plain="Each scanner row gets a subtle color-gradient background based on the symbol's mood: green for steady up-trend, amber for choppy, cyan for fresh evaluation, rose for fading, violet for high-volatility. You can scan the list and read mood from color alone."
          before={
            <div className="space-y-1 w-full">
              {[['PWR', '+1.2%'], ['MCHP', '+0.3%'], ['VLO', '+2.1%'], ['TNA', '-1.8%']].map(([s, p]) => (
                <div key={s} className="flex justify-between bg-zinc-900 border border-zinc-800 rounded px-2 py-1">
                  <span className="font-mono font-bold text-zinc-100">{s}</span>
                  <span className="text-[12px] text-zinc-400 font-mono">{p}</span>
                </div>
              ))}
              <div className="text-[11px] text-zinc-500 italic mt-1 text-center">all rows look the same · you have to read each price</div>
            </div>
          }
          after={
            <div className="space-y-1 w-full">
              {[
                { sym: 'PWR',  bg: 'linear-gradient(90deg, rgba(52,211,153,0.18), transparent)', spark: [40,42,41,44,46,45,48,50,52,55], color: 'emerald', mood: 'steady up' },
                { sym: 'MCHP', bg: 'linear-gradient(90deg, rgba(251,191,36,0.18), transparent)', spark: [42,40,44,41,43,40,42,41,43,42], color: 'amber',   mood: 'choppy' },
                { sym: 'VLO',  bg: 'linear-gradient(90deg, rgba(34,211,238,0.18), transparent)', spark: [30,32,31,34,38,42,45,48,52,58], color: 'cyan',    mood: 'fresh breakout' },
                { sym: 'TNA',  bg: 'linear-gradient(90deg, rgba(251,113,133,0.18), transparent)', spark: [55,52,48,45,42,40,38,34,32,30], color: 'rose',    mood: 'fading' },
              ].map(r => (
                <div key={r.sym} className="flex items-center gap-2 border border-zinc-800/60 rounded px-2 py-1" style={{ background: r.bg }}>
                  <span className="font-mono font-bold text-zinc-100 w-12">{r.sym}</span>
                  <Sparkline points={r.spark} color={r.color} w={50} h={14} />
                  <span className="text-[10px] text-zinc-500 italic ml-auto">{r.mood}</span>
                </div>
              ))}
              <div className="text-[11px] text-cyan-400 italic mt-1 text-center">↑ color tells the mood. emerald=up, amber=chop, cyan=fresh, rose=fade.</div>
            </div>
          }
        />

        {/* ⑥ PIPELINE PARTICLES */}
        <ConceptCard n="⑥" title="Pipeline data-flow particles" accent="cyan"
          plain="Tiny glowing dots travel left-to-right INSIDE each pipeline pill (SCAN → EVAL → ORDER → MANAGE → CLOSE). It's eye-candy that signals 'the bot is working' but it's also the most distracting concept — most people watching a chart find it pulls peripheral attention."
          before={
            <div className="flex items-center gap-1 w-full justify-center">
              {['SCAN 6', 'EVAL 5', 'ORDER 0'].map(l => (
                <span key={l} className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-[12px] text-zinc-300 font-mono">{l}</span>
              ))}
              <div className="text-[11px] text-zinc-500 italic ml-3">static · no motion</div>
            </div>
          }
          after={
            <div className="flex items-center gap-1 w-full justify-center">
              {['SCAN 6', 'EVAL 5', 'ORDER 0'].map((l, i) => (
                <span key={l} className="relative overflow-hidden bg-zinc-900 border border-cyan-700/40 rounded px-2 py-1 text-[12px] text-zinc-300 font-mono">
                  {l}
                  <span className="absolute top-1/2 -translate-y-1/2 w-1 h-1 rounded-full bg-cyan-300" style={{ boxShadow: '0 0 6px #22d3ee, 0 0 12px #22d3ee', animation: `flow-particle 2.5s linear infinite ${i * 0.5}s` }} />
                </span>
              ))}
              <style>{`@keyframes flow-particle { 0% { left: -10%; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { left: 110%; opacity: 0; } }`}</style>
              <div className="text-[11px] text-cyan-400 italic ml-3">↑ dots travel through · cool, but distracting in peripheral vision</div>
            </div>
          }
        />

        {/* ⑦ TIME SCRUBBER */}
        <ConceptCard n="⑦" title="Time scrubber (rewind the day)" accent="amber"
          plain="A slider at the bottom of the app showing every moment from 9:30 to 15:55. Drag the thumb to any time → the entire UI rewinds: chart, Thinking pane, positions, alerts, P&L all show their state at THAT moment. Colored dots mark the day's significant events. This is the most powerful concept here — it's a time machine for post-trade review."
          before={<div className="text-[12px] text-zinc-500 italic text-center w-full">To review what happened at 11:42 AM you have to dig through logs, scroll the chart back, and reconstruct the bot's state from memory.</div>}
          after={
            <div className="w-full">
              <div className="px-2 py-2 bg-zinc-900 border border-zinc-800 rounded flex items-center gap-2">
                <span className="text-[10px] text-zinc-500 font-mono">9:30</span>
                <div className="flex-1 relative h-5">
                  <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 bg-zinc-800 rounded-full">
                    {[
                      { t: 8,  color: '#34d399', label: 'gap_fade fired' },
                      { t: 22, color: '#fb7185', label: 'EFA explosion' },
                      { t: 34, color: '#fbbf24', label: 'manual flatten' },
                      { t: 48, color: '#22d3ee', label: 'orphan-GTC alert' },
                      { t: 65, color: '#c084fc', label: 'EOD recap' },
                    ].map((m, i) => (
                      <div key={i} className="absolute top-1/2 -translate-y-1/2 w-1.5 h-3 rounded-sm" style={{ left: `${m.t}%`, background: m.color, boxShadow: `0 0 4px ${m.color}` }} title={m.label} />
                    ))}
                    <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-cyan-300 border-2 border-zinc-950" style={{ left: `${scrub}%`, boxShadow: '0 0 8px #22d3ee' }} />
                  </div>
                </div>
                <span className="text-[10px] text-zinc-500 font-mono">15:55</span>
                <span className="bg-cyan-900/50 border border-cyan-700 rounded px-1.5 py-0.5 text-[10px] text-cyan-200 font-mono">now: 14:04</span>
              </div>
              <input type="range" min="0" max="100" value={scrub} onChange={e => setScrub(Number(e.target.value))} className="w-full mt-2 accent-cyan-400" />
              <div className="text-[11px] text-cyan-400 italic mt-1 text-center">↑ try dragging it. colored dots = events of the day. drag to any moment → whole UI rewinds.</div>
            </div>
          }
        />

        {/* ⑧ PROVENANCE RING */}
        <ConceptCard n="⑧" title="Provenance ring (decision donut)" accent="violet"
          plain="When the bot says 'GO' or 'SKIP' on a trade, you usually see a wall of bars showing each input's contribution. Replace that wall with a single donut chart: each slice is one input (regime, model consensus, etc), slice size = how much it mattered, center number = the final score. One glance tells you what drove the decision."
          before={
            <div className="space-y-1 w-full text-[11px]">
              <div className="flex items-center gap-2"><span className="w-16 text-zinc-500">Regime</span><div className="flex-1 h-2 bg-zinc-800 rounded"><div className="h-full bg-emerald-500 rounded" style={{ width: '75%' }} /></div><span className="font-mono text-emerald-400">+10</span></div>
              <div className="flex items-center gap-2"><span className="w-16 text-zinc-500">Consensus</span><div className="flex-1 h-2 bg-zinc-800 rounded"><div className="h-full bg-cyan-500 rounded" style={{ width: '80%' }} /></div><span className="font-mono text-cyan-400">+15</span></div>
              <div className="flex items-center gap-2"><span className="w-16 text-zinc-500">Cross-Mdl</span><div className="flex-1 h-2 bg-zinc-800 rounded"><div className="h-full bg-violet-500 rounded" style={{ width: '70%' }} /></div><span className="font-mono text-violet-400">+8</span></div>
              <div className="flex items-center gap-2"><span className="w-16 text-zinc-500">Live</span><div className="flex-1 h-2 bg-zinc-800 rounded"><div className="h-full bg-rose-500 rounded" style={{ width: '12%' }} /></div><span className="font-mono text-rose-400">−2</span></div>
              <div className="flex items-center gap-2"><span className="w-16 text-zinc-500">Quality</span><div className="flex-1 h-2 bg-zinc-800 rounded"><div className="h-full bg-amber-500 rounded" style={{ width: '78%' }} /></div><span className="font-mono text-amber-400">+12</span></div>
              <div className="text-[11px] text-zinc-500 italic mt-2 text-center">5 separate bars · 5 numbers to read</div>
            </div>
          }
          after={
            <div className="flex items-center gap-3 w-full">
              <ProvenanceRing size={120} />
              <div className="flex-1 text-[11px] space-y-0.5">
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#34d399'}}/><span className="text-zinc-300 flex-1">Regime</span><span className="font-mono text-emerald-300">+10</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#22d3ee'}}/><span className="text-zinc-300 flex-1">Consensus</span><span className="font-mono text-cyan-300">+15</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#a78bfa'}}/><span className="text-zinc-300 flex-1">Cross-Mdl</span><span className="font-mono text-violet-300">+8</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#fb7185'}}/><span className="text-zinc-300 flex-1">Live</span><span className="font-mono text-rose-300">−2</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{background:'#fbbf24'}}/><span className="text-zinc-300 flex-1">Quality</span><span className="font-mono text-amber-300">+12</span></div>
                <div className="text-[11px] text-cyan-400 italic mt-2">↑ donut at a glance: green+cyan dominate → strong GO</div>
              </div>
            </div>
          }
        />

        <div className="mt-6 bg-zinc-900/40 border border-zinc-800 rounded-xl p-4 text-[13px] text-zinc-300">
          <div className="font-bold text-cyan-300 mb-2">After reading these — vote per concept</div>
          <p className="text-zinc-400 mb-2">For each of ① through ⑧, tell me:</p>
          <ul className="list-disc pl-5 space-y-1 text-[12px]">
            <li><span className="text-emerald-300">Ship</span> — include in V6.2 tomorrow</li>
            <li><span className="text-amber-300">Toggle</span> — build it but default-off (operator opts in via settings)</li>
            <li><span className="text-violet-300">Defer</span> — queue for V6.3 follow-up</li>
            <li><span className="text-rose-300">Skip</span> — not interested</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default V6ConceptsExplained;
