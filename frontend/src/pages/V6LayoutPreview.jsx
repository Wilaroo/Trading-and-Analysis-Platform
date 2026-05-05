/* eslint-disable react/no-unescaped-entities */
import React, { useState, useRef, useEffect, useCallback } from 'react';

/**
 * V6 Layout Preview v3 — production-faithful mockup
 *
 * Preserves the FULL density of the live V5 dashboard:
 *   • Top KPI ribbon (SCAN / EVALUATE / ORDER / MANAGE / CLOSE TODAY / PAPER / SAFETY)
 *   • Pusher health strip (top movers + push rate + RPC latency + quotes/pos)
 *   • Morning Prep / Mid-Day Recap / Power Hour / EOD Recap rotation
 *   • ML Feature Audit
 *   • SentCom Intelligence (NORMAL/CRITICAL state + per-setup cards with model bars)
 *   • Scanner cards with full Bot: quote + R-score + color bars
 *   • OPEN positions list with DAY/PARTIAL/AMBER/ORPHAN/RECONCILED tags
 *   • Stream Deep Feed search/filter
 *   • EOD ALARM banner
 *   • Strategy mix · Shadow vs Real
 *
 * STRUCTURAL CHANGES PROPOSED:
 *   ① Drag-resizable splits between every pane
 *   ② Pipeline-stage filter pills in the scanner (Scan / Eval / Pos / Done)
 *   ③ Expandable scanner cards (full reasons + score breakdown)
 *   ④ NEW THINKING pane between chart and timeline (rich per-symbol eval cards)
 *   ⑤ Pin ↔ Auto-rotate toggle in THINKING
 *   ⑥ UnifiedStream + Stream Deep Feed merged into ONE Timeline (4 tabs)
 *   ⑦ EOD ALARM as floating toast (instead of stuck above stream)
 *   ⑧ Status strip at bottom (replaces current bottom drawer entirely)
 */

// ─── shared atoms ─────────────────────────────────────────────────
const Pill = ({ children, color = 'zinc', className = '', onClick }) => {
  const c = {
    zinc: 'bg-zinc-800 text-zinc-300 border-zinc-700',
    emerald: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/60',
    rose: 'bg-rose-900/40 text-rose-300 border-rose-700/60',
    amber: 'bg-amber-900/40 text-amber-300 border-amber-700/60',
    cyan: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/60',
    violet: 'bg-violet-900/40 text-violet-300 border-violet-700/60',
    sky: 'bg-sky-900/40 text-sky-300 border-sky-700/60',
    orange: 'bg-orange-900/40 text-orange-300 border-orange-700/60',
  };
  return <span onClick={onClick} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${c[color]} ${onClick ? 'cursor-pointer hover:brightness-125' : ''} ${className}`}>{children}</span>;
};

const Bar = ({ pct, color = 'cyan' }) => {
  const c = { cyan: 'bg-cyan-500', emerald: 'bg-emerald-500', amber: 'bg-amber-500', rose: 'bg-rose-500', violet: 'bg-violet-500', purple: 'bg-purple-500' };
  return <div className="h-1 bg-zinc-800 rounded-full overflow-hidden flex-1"><div className={`h-full ${c[color]}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
};

const ColorBars = ({ score, segs = ['violet', 'cyan', 'amber', 'emerald'] }) => (
  <div className="flex gap-0.5 h-1">
    {segs.map((color, i) => <div key={i} className={`flex-1 ${score > i * 25 ? `bg-${color}-500` : 'bg-zinc-800'}`} />)}
  </div>
);

// ─── resizable splits ─────────────────────────────────────────────
const useSplit = (containerRef, axis, onChange) => {
  const dragging = useRef(false);
  const onDown = (e) => { dragging.current = true; e.preventDefault(); };
  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = axis === 'x' ? ((e.clientX - rect.left) / rect.width) * 100 : ((e.clientY - rect.top) / rect.height) * 100;
      onChange(Math.max(8, Math.min(92, next)));
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [containerRef, axis, onChange]);
  return onDown;
};
const VSplit = ({ leftPct, onChange, containerRef }) => {
  const onDown = useSplit(containerRef, 'x', onChange);
  return <div onMouseDown={onDown} title={`${leftPct.toFixed(0)}% — drag`} className="w-[4px] cursor-col-resize bg-zinc-800/50 hover:bg-cyan-700 transition-colors flex-shrink-0" />;
};
const HSplit = ({ topPct, onChange, containerRef }) => {
  const onDown = useSplit(containerRef, 'y', onChange);
  return <div onMouseDown={onDown} title={`${topPct.toFixed(0)}% — drag`} className="h-[4px] cursor-row-resize bg-zinc-800/50 hover:bg-cyan-700 transition-colors flex-shrink-0" />;
};

// ─── ① TOP KPI RIBBON (preserved from production) ─────────────
const KpiRibbon = () => (
  <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-2 flex items-center gap-2 flex-shrink-0 text-xs">
    <div className="text-cyan-400 font-bold mr-1">SENTCOM</div>
    <div className="bg-zinc-900 rounded border border-zinc-800 px-2 py-1 flex items-center gap-2">
      <span className="text-zinc-500 text-[10px] uppercase">Scan</span>
      <span className="font-mono text-zinc-100 font-bold">6</span>
      <span className="text-zinc-600 text-[10px]">multi · 1234 symbols</span>
    </div>
    <span className="text-zinc-700">→</span>
    <div className="bg-zinc-900 rounded border border-zinc-800 px-2 py-1 flex items-center gap-2">
      <span className="text-zinc-500 text-[10px] uppercase">Evaluate</span>
      <span className="font-mono text-cyan-300 font-bold">5</span>
      <span className="text-zinc-600 text-[10px]">5 alerts</span>
    </div>
    <span className="text-zinc-700">→</span>
    <div className="bg-zinc-900 rounded border border-zinc-800 px-2 py-1 flex items-center gap-2">
      <span className="text-zinc-500 text-[10px] uppercase">Order</span>
      <span className="font-mono text-zinc-100 font-bold">0</span>
      <span className="text-zinc-600 text-[10px]">0 filled · 0 pending</span>
    </div>
    <span className="text-zinc-700">→</span>
    <div className="bg-zinc-900 rounded border border-emerald-700/40 px-2 py-1 flex items-center gap-2">
      <span className="text-zinc-500 text-[10px] uppercase">Manage</span>
      <span className="font-mono text-emerald-300 font-bold">+0.3R</span>
      <span className="font-mono text-zinc-100">7</span>
      <span className="text-zinc-600 text-[10px]">FDX · UPS · FDX · no stops breached</span>
    </div>
    <span className="text-zinc-700">→</span>
    <div className="bg-zinc-900 rounded border border-emerald-700/40 px-2 py-1 flex items-center gap-2">
      <span className="text-zinc-500 text-[10px] uppercase">Close Today</span>
      <span className="font-mono text-emerald-300 font-bold">+0.0R</span>
      <span className="font-mono text-zinc-100">9</span>
      <span className="text-zinc-600 text-[10px]">WR 44% · worst 0.0R</span>
    </div>
    <button className="ml-auto bg-zinc-900 border border-zinc-800 hover:border-cyan-700 rounded px-2 py-1 text-[10px] text-zinc-300">⚙ SEARCH</button>
    <Pill color="emerald">ALL SYSTEMS</Pill>
    <Pill color="emerald">↯ Wires</Pill>
    <button className="bg-amber-900/30 border border-amber-700/60 rounded px-2 py-1 text-[10px] text-amber-300 font-bold">FLATTEN ALL</button>
    <Pill color="amber">PAPER · DUN615665</Pill>
    <Pill color="emerald">Safety ARMED</Pill>
    <div className="bg-zinc-900 rounded border border-emerald-700/40 px-2 py-1">
      <div className="text-[9px] text-zinc-500 uppercase">P&amp;L</div>
      <div className="font-mono text-emerald-300 font-bold text-xs">+$4,300.78</div>
      <div className="text-[9px] text-zinc-500">+$3,643.91 +$656.79</div>
    </div>
    <div className="bg-zinc-900 rounded border border-zinc-800 px-2 py-1">
      <div className="text-[9px] text-zinc-500 uppercase">Equity</div>
      <div className="font-mono text-zinc-100 font-bold text-xs">$237,654</div>
    </div>
    <div className="bg-zinc-900 rounded border border-zinc-800 px-2 py-1">
      <div className="text-[9px] text-zinc-500 uppercase">Buying Pwr</div>
      <div className="font-mono text-zinc-300 text-xs">$—</div>
    </div>
    <Pill color="orange">PHASE · AFTER-HOURS</Pill>
  </div>
);

// ─── ② PUSHER HEALTH STRIP ────────────────────────────────────
const PusherStrip = () => (
  <div className="bg-zinc-950/60 border-b border-zinc-800/50 px-3 py-1 flex items-center gap-3 flex-shrink-0 text-[11px]">
    <span className="text-zinc-500 uppercase text-[10px]">Top Movers · Extended</span>
    <span className="font-mono text-zinc-300">INWM <span className="text-zinc-500">$282.88</span> <span className="text-rose-400">-0.06%</span></span>
    <span className="font-mono text-zinc-300">QQQ <span className="text-zinc-500">$683.86</span> <span className="text-emerald-400">+0.02%</span></span>
    <span className="font-mono text-zinc-300">DIA <span className="text-zinc-500">$492.47</span> <span className="text-rose-400">-0.01%</span></span>
    <span className="font-mono text-zinc-300">SPY <span className="text-zinc-500">$724.97</span> <span className="text-emerald-400">+0.00%</span></span>
    <span className="font-mono text-zinc-300">VIX <span className="text-zinc-500">$17.38</span> <span className="text-emerald-400">+0.00%</span></span>
    <span className="text-zinc-700">·</span>
    <Pill color="emerald">PUSHER GREEN</Pill>
    <span className="text-zinc-500">last push 6s ago</span>
    <span className="text-zinc-700">·</span>
    <span className="text-zinc-500">push rate <span className="text-zinc-300 font-mono">6/min</span></span>
    <span className="text-zinc-700">·</span>
    <span className="text-zinc-500">RPC <span className="text-emerald-300 font-mono">3ms</span></span>
    <span className="text-zinc-500">last p95 <span className="font-mono">449ms</span> avg <span className="font-mono">119ms</span> (n=50)</span>
    <span className="text-zinc-700">·</span>
    <span className="text-zinc-500">total <span className="text-zinc-300 font-mono">736</span></span>
    <span className="text-zinc-500">tracking <span className="text-cyan-300 font-mono">321</span> quotes · <span className="font-mono">21</span> pos</span>
  </div>
);

// ─── SCANNER CARD (production-faithful + expandable) ────────────
const SCANNER = [
  { sym: 'FDX', stage: 'managing', tag: 'OPEN', sh: '20sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '20sh · Holding FDX @ 362.29 · SL 350.32 · PT 393.67.', r: '0.02', pnl: '+$5', conf: 78,
    reasons: ['BB squeeze 8d → release attempt at $362', 'vol 1.2× rising', 'XLI sector +0.4%', 'gap-fill plus structure intact'],
    triggers: ['target hit at $393.67', 'stop run below $350.32'],
    tier: 'A', score: { trend: 78, vol: 65, momentum: 71, rs: 84 } },
  { sym: 'UPS', stage: 'managing', tag: 'OPEN', sh: '885sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '885sh · Holding UPS @ 98.08 · SL 94.98 · PT 107.57.', r: '-0.04', pnl: '-$124', conf: 64,
    reasons: ['multi-day base reclaim', 'transports rotation', 'institutional buy flow detected'],
    triggers: ['target $107.57 = +9.7% from cost', 'cut at $94.98 = -3.1%'],
    tier: 'A', score: { trend: 58, vol: 42, momentum: 54, rs: 71 } },
  { sym: 'SBUX', stage: 'managing', tag: 'OPEN', sh: '273sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '273sh · Holding SBUX @ 105.67.', r: null, pnl: '+$258', conf: 72,
    reasons: ['oversold bounce', 'consumer rotation'], triggers: ['scale 1/3 @ $108'], tier: 'A', score: { trend: 62, vol: 55, momentum: 68, rs: 64 } },
  { sym: 'ADBE', stage: 'managing', tag: 'OPEN', sh: '15sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '15sh · Holding ADBE @ 255.03.', r: null, pnl: '-$2', conf: 45,
    reasons: ['squeeze release', 'tech relative strength'], triggers: ['BE stop arm at $258'], tier: 'A', score: { trend: 51, vol: 48, momentum: 55, rs: 49 } },
  { sym: 'LITE', stage: 'managing', tag: 'OPEN', sh: '8sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '8sh · Holding LITE @ 1010.13.', r: null, pnl: '-$121', conf: 38,
    reasons: ['HOD attempt'], triggers: ['needs vol confirm'], tier: 'A', score: { trend: 38, vol: 41, momentum: 35, rs: 32 } },
  { sym: 'LIN', stage: 'managing', tag: 'OPEN', sh: '6sh', stops: ['violet', 'cyan', 'amber', 'emerald'], note: '6sh · Holding LIN @ 500.48.', r: null, pnl: '+$5', conf: 51,
    reasons: ['quiet trend'], triggers: ['stop tighten'], tier: 'A', score: { trend: 51, vol: 44, momentum: 48, rs: 53 } },
  { sym: 'PWR', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 57,
    reasons: ['off_sides_short flagged · conf 57%', 'industrial sector lag', 'price/vol divergence'],
    triggers: ['fires when R:R ≥ 1.5'], tier: 'A', score: { trend: 41, vol: 57, momentum: 38, rs: 35 } },
  { sym: 'MCHP', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 56,
    reasons: ['off_sides_short flagged · conf 56%'], triggers: ['needs vol spike'], tier: 'A', score: { trend: 45, vol: 56, momentum: 42, rs: 38 } },
  { sym: 'VLO', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 58,
    reasons: ['off_sides_short flagged · conf 58%', 'energy weakness'], triggers: ['vol confirm'], tier: 'A', score: { trend: 42, vol: 58, momentum: 44, rs: 41 } },
  { sym: 'TNA', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 58,
    reasons: ['off_sides_short flagged · conf 58%'], triggers: [], tier: 'A', score: { trend: 41, vol: 58, momentum: 39, rs: 36 } },
  { sym: 'VRT', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 58,
    reasons: ['off_sides_short flagged · conf 58%'], triggers: [], tier: 'A', score: { trend: 44, vol: 58, momentum: 41, rs: 39 } },
  { sym: 'GILD', stage: 'evaluating', tag: 'EVAL', flag: 'off sides short', conf: 57,
    reasons: ['off_sides_short flagged · conf 57%'], triggers: [], tier: 'A', score: { trend: 38, vol: 57, momentum: 36, rs: 33 } },
];

const STAGE_META = {
  scanning: { label: 'Scan', icon: '🔭', color: 'zinc' },
  evaluating: { label: 'Eval', icon: '🧠', color: 'cyan' },
  managing: { label: 'Pos', icon: '🟢', color: 'emerald' },
  closed: { label: 'Done', icon: '✓', color: 'violet' },
  cooldown: { label: 'Cool', icon: '⏸', color: 'amber' },
  muted: { label: 'Muted', icon: '🚫', color: 'rose' },
};

const ScannerCard = ({ row, expanded, onToggle, onFocus, isFocused }) => (
  <div className={`border-b border-zinc-900 ${isFocused ? 'bg-cyan-950/20 border-cyan-800/40' : ''}`}>
    <div className="px-3 py-2 hover:bg-zinc-900/40 cursor-pointer" onClick={() => onFocus(row.sym)}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-bold text-zinc-100 font-mono">{row.sym}</span>
          {row.tag && <Pill color={row.tag === 'OPEN' ? 'violet' : 'cyan'}>{row.tag}</Pill>}
          {row.sh && <span className="text-[10px] text-zinc-500 font-mono">{row.sh}</span>}
        </div>
        {row.r !== null && row.r !== undefined && <span className={`text-[10px] font-mono ${parseFloat(row.r) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>R {row.r}</span>}
      </div>
      {row.stops && (
        <div className="flex gap-0.5 h-1.5 mb-1.5">
          {row.stops.map((c, i) => (<div key={i} className={`flex-1 rounded-sm ${{violet:'bg-violet-500',cyan:'bg-cyan-500',amber:'bg-amber-500',emerald:'bg-emerald-500'}[c]}`} />))}
        </div>
      )}
      {row.flag && <Pill color="violet" className="mb-1">{row.flag}</Pill>}
      {row.conf !== undefined && (
        <div className="flex items-center gap-2 mb-1">
          <Bar pct={row.conf} color={row.conf > 60 ? 'emerald' : row.conf > 40 ? 'amber' : 'rose'} />
          <span className="text-[10px] text-zinc-500 font-mono w-6 text-right">{row.conf}%</span>
        </div>
      )}
      {row.note && <div className="text-[10px] text-zinc-400 italic">Bot: <span className="text-zinc-300">"{row.note}"</span></div>}
      {row.flag && !row.note && <div className="text-[10px] text-zinc-400 italic">Bot: <span className="text-zinc-300">"{row.flag} flagged · conf {row.conf}%."</span></div>}
      <div className="flex items-center justify-between mt-1">
        {row.pnl && <span className={`text-[10px] font-mono ${row.pnl.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>{row.pnl}</span>}
        <button onClick={(e) => { e.stopPropagation(); onToggle(row.sym); }} className="text-[10px] text-zinc-500 hover:text-cyan-300 ml-auto">{expanded ? '▲' : '▼'}</button>
      </div>
    </div>
    {expanded && (
      <div className="px-3 pb-2 bg-zinc-950/60 border-t border-zinc-900/50 space-y-1.5">
        <div className="pt-2"><div className="text-[9px] text-zinc-500 uppercase mb-1">Why scanner picked it</div>
          <ul className="space-y-0.5 text-[10px] text-zinc-300">{row.reasons.map((r, i) => <li key={i}>· {r}</li>)}</ul>
        </div>
        {row.triggers.length > 0 && (<div><div className="text-[9px] text-zinc-500 uppercase mb-1">Watching for</div>
          <ul className="space-y-0.5 text-[10px] text-violet-300">{row.triggers.map((t, i) => <li key={i}>🎯 {t}</li>)}</ul>
        </div>)}
        <div><div className="text-[9px] text-zinc-500 uppercase mb-1">Score</div>
          <div className="grid grid-cols-2 gap-1 text-[9px]">
            {Object.entries(row.score).map(([k, v]) => (
              <div key={k} className="flex items-center gap-1">
                <span className="text-zinc-500 w-9 capitalize">{k}</span>
                <Bar pct={v} color={v > 60 ? 'emerald' : v > 40 ? 'amber' : 'rose'} />
                <span className="text-zinc-400 font-mono w-5 text-right">{v}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1 pt-1">
          <button className="text-[9px] px-1.5 py-0.5 bg-cyan-900/40 hover:bg-cyan-900/60 text-cyan-300 rounded">📊</button>
          <button className="text-[9px] px-1.5 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">🧠</button>
          <button className="text-[9px] px-1.5 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜</button>
          <button className="text-[9px] px-1.5 py-0.5 bg-amber-900/30 hover:bg-amber-900/50 text-amber-300 rounded ml-auto">🚫</button>
        </div>
      </div>
    )}
  </div>
);

const ScannerPane = ({ focused, onFocus }) => {
  const [stage, setStage] = useState('all');
  const [expanded, setExpanded] = useState(new Set());
  const stages = [
    { id: 'all', label: 'All', count: SCANNER.length },
    { id: 'scanning', label: '🔭 Scan', count: 0 },
    { id: 'evaluating', label: '🧠 Eval', count: SCANNER.filter(s => s.stage === 'evaluating').length },
    { id: 'managing', label: '🟢 Pos', count: SCANNER.filter(s => s.stage === 'managing').length },
    { id: 'closed', label: '✓ Done', count: 0 },
    { id: 'cooldown', label: '⏸ Cool', count: 0 },
  ];
  const filtered = stage === 'all' ? SCANNER : SCANNER.filter(s => s.stage === stage);
  const toggle = (sym) => setExpanded(p => { const n = new Set(p); n.has(sym) ? n.delete(sym) : n.add(sym); return n; });
  const grouped = stage === 'all' ? ['evaluating', 'managing'].map(s => ({ stage: s, rows: filtered.filter(r => r.stage === s) })).filter(g => g.rows.length) : [{ stage, rows: filtered }];

  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2"><span className="text-xs font-semibold text-zinc-400 uppercase">Scanner · Live</span><Pill color="emerald">● 6s</Pill></div>
        <div className="flex items-center gap-2"><span className="text-[10px] text-zinc-500 font-mono">↑↓ {filtered.length}/12 hits</span><button className="text-[10px] px-1.5 py-0.5 bg-zinc-900 border border-zinc-800 rounded text-zinc-400">FLAT</button></div>
      </div>
      <div className="px-2 py-1 border-b border-zinc-800/50 flex flex-wrap items-center gap-1 flex-shrink-0">
        {stages.map(s => (
          <button key={s.id} onClick={() => setStage(s.id)} className={`text-[9px] px-1.5 py-0.5 rounded border ${stage === s.id ? 'bg-cyan-900/40 text-cyan-300 border-cyan-700' : 'text-zinc-400 border-zinc-800 hover:bg-zinc-900'}`}>
            {s.label} <span className="text-[8px] text-zinc-500 ml-0.5">{s.count}</span>
          </button>
        ))}
      </div>
      <div className="px-2 py-1 border-b border-zinc-800/50 flex items-center gap-1 flex-shrink-0">
        <input placeholder="🔎 filter..." className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[10px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-cyan-700" />
        <select className="bg-zinc-900 border border-zinc-800 rounded px-1 py-0.5 text-[9px] text-zinc-300"><option>conf↓</option><option>chg↓</option><option>tier</option></select>
      </div>
      <div className="flex-1 overflow-y-auto">
        {grouped.map(g => (
          <div key={g.stage}>
            <div className="px-3 py-1 text-[9px] text-zinc-500 uppercase tracking-wider bg-zinc-900/40 border-b border-zinc-800/40 flex items-center justify-between">
              <span>{STAGE_META[g.stage].icon} {STAGE_META[g.stage].label} · {g.rows.length}</span>
            </div>
            {g.rows.map(row => <ScannerCard key={row.sym} row={row} expanded={expanded.has(row.sym)} onToggle={toggle} onFocus={onFocus} isFocused={focused === row.sym} />)}
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── ④ THINKING PANE ────────────────────────────────────────────
const ThinkingPane = ({ focused }) => {
  const [mode, setMode] = useState('pinned');
  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-zinc-400 uppercase">🧠 Thinking</span>
          <Pill color="cyan">{focused}</Pill>
          <span className="text-[10px] text-zinc-500">eval cycle #14 · 0.3s ago</span>
        </div>
        <div className="flex items-center gap-1 bg-zinc-900 rounded p-0.5">
          <button onClick={() => setMode('pinned')} className={`text-[10px] px-2 py-0.5 rounded ${mode === 'pinned' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500'}`}>📍 Pin</button>
          <button onClick={() => setMode('rotate')} className={`text-[10px] px-2 py-0.5 rounded ${mode === 'rotate' ? 'bg-violet-900/50 text-violet-300' : 'text-zinc-500'}`}>🔄 Rotate</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <div className="bg-zinc-900/60 border border-cyan-700/40 rounded p-2 text-[11px]">
          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
            <span className="text-base font-bold">{focused}</span>
            <Pill color="cyan">EVALUATING gap_fade LONG</Pill>
            <Pill color="violet">TQS 80</Pill>
            <Pill color="emerald">A+</Pill>
            <Pill color="emerald">ML 78%</Pill>
          </div>
          <div className="grid grid-cols-4 gap-1 mb-2 text-[10px]">
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">Entry</div><div className="font-mono">$368.04</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">SL</div><div className="text-rose-300 font-mono">$352.84</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">PT</div><div className="text-emerald-300 font-mono">$374.44</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">R:R</div><div className="font-mono">2.8 · 256sh</div></div>
          </div>
          <div className="mb-2"><div className="text-[9px] text-zinc-500 uppercase mb-0.5">Gates · 4 of 6 open</div>
            <div className="grid grid-cols-2 gap-0.5 text-[10px]">
              <div className="text-emerald-400">✓ Capital ($24k free)</div>
              <div className="text-emerald-400">✓ R:R floor (2.8 ≥ 1.5)</div>
              <div className="text-emerald-400">✓ Direction stable 38s</div>
              <div className="text-emerald-400">✓ No cooldown</div>
              <div className="text-amber-400">✗ Vol confirm (0.9× vs 1.5×)</div>
              <div className="text-amber-400">✗ VWAP reclaim ($0.12 below)</div>
            </div>
          </div>
          <div className="mb-2 bg-zinc-950/40 border border-violet-800/30 rounded p-1.5">
            <div className="text-violet-300 font-medium text-[10px] mb-0.5">🎯 Watching for trigger</div>
            <ul className="space-y-0.5 text-[10px] text-zinc-300">
              <li>• 5m vol {'>'} 1.5× avg (need +67%)</li>
              <li>• AND VWAP reclaim above $362.95</li>
              <li>• Auto-fires both holding 8s</li>
            </ul>
          </div>
          <div className="grid grid-cols-3 gap-1 mb-2 text-[10px]">
            <div className="bg-zinc-950/40 rounded p-1.5"><div className="text-[9px] text-zinc-500">Bull · 65%</div><div className="text-emerald-300">+$226</div></div>
            <div className="bg-zinc-950/40 rounded p-1.5"><div className="text-[9px] text-zinc-500">Base · 25%</div><div className="text-zinc-300">±$0–40</div></div>
            <div className="bg-zinc-950/40 rounded p-1.5"><div className="text-[9px] text-zinc-500">Bear · 10%</div><div className="text-rose-300">−$109</div></div>
          </div>
          <div className="mb-2"><div className="text-[9px] text-zinc-500 uppercase mb-0.5">Context</div>
            <div className="grid grid-cols-2 gap-0.5 text-[10px] text-zinc-400">
              <div>📊 ATR(14) $1.82 · ±1.3%</div>
              <div>💧 8.4M avg vol · spread $0.01</div>
              <div>🌐 XLI +1.4% · RS +0.3</div>
              <div>📰 No catalysts · earnings 12d</div>
              <div>🔗 NVDA corr +0.74 ⚠</div>
              <div>🎲 18 PASS / 6 FAIL · 75% WR</div>
            </div>
          </div>
          <div className="text-[10px] text-zinc-400 italic bg-zinc-950/40 p-1.5 rounded mb-2">
            "Considered momentum_breakout but R:R 1.42 below floor. Will downgrade to Tier B if vol stays thin past 14:30."
          </div>
          <div className="border-t border-zinc-800 pt-1.5">
            <div className="text-[9px] text-zinc-500 uppercase mb-0.5">Last 5 verdicts</div>
            <div className="space-y-0 text-[9px]">
              <div className="flex justify-between"><span className="text-rose-300">REJECT 14:22</span><span className="text-zinc-500">R:R 1.31</span></div>
              <div className="flex justify-between"><span className="text-rose-300">REJECT 13:48</span><span className="text-zinc-500">vol fail</span></div>
              <div className="flex justify-between"><span className="text-emerald-300">PASS 13:01 +$340</span><span className="text-zinc-500">target hit</span></div>
              <div className="flex justify-between"><span className="text-rose-300">REJECT 12:18</span><span className="text-zinc-500">unstable</span></div>
              <div className="flex justify-between"><span className="text-emerald-300">PASS 11:42 +$118</span><span className="text-zinc-500">scratch</span></div>
            </div>
          </div>
          <div className="flex items-center gap-1 mt-2 pt-1.5 border-t border-zinc-800">
            <button className="text-[9px] px-1.5 py-0.5 bg-cyan-900/40 text-cyan-300 rounded">📍 pin</button>
            <button className="text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-300 rounded">📊 chart</button>
            <button className="text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-300 rounded">📜 log</button>
            <button className="text-[9px] px-1.5 py-0.5 bg-amber-900/30 text-amber-300 rounded ml-auto">🚫 mute</button>
          </div>
        </div>
        {mode === 'rotate' && <div className="mt-2 text-[9px] text-zinc-500 text-center">⏱ rotates to UPS · MELI · NVDA every 8s</div>}
      </div>
    </div>
  );
};

// ─── CHART (production-faithful: same overlays + status header) ─
const ChartPane = ({ focused }) => (
  <div className="bg-zinc-900/30 flex flex-col h-full">
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2 flex-shrink-0 text-xs flex-wrap">
      <span className="text-base font-bold text-zinc-100 font-mono">{focused}</span>
      <input placeholder="TYPE TICKER" className="bg-zinc-900 border border-zinc-800 rounded px-2 py-0.5 text-[10px] text-zinc-300 placeholder:text-zinc-600 w-24" />
      <Pill color="emerald">● LIVE · 6s</Pill>
      <Pill color="violet">OPEN · 5h</Pill>
      <span className="text-zinc-500">$362.55 <span className="text-emerald-400">+8.7%</span></span>
      <span className="text-zinc-700">·</span>
      <span className="text-zinc-500">Entry <span className="text-zinc-300 font-mono">368.04</span></span>
      <span className="text-zinc-500">SL <span className="text-rose-300 font-mono">352.84</span></span>
      <span className="text-zinc-500">PT <span className="text-emerald-300 font-mono">374.44</span></span>
      <span className="text-zinc-500">R:R <span className="text-zinc-300 font-mono">2.8</span></span>
      <span className="text-zinc-500 font-mono">256sh</span>
    </div>
    <div className="px-3 py-1.5 border-b border-zinc-800/50 flex items-center gap-1.5 flex-wrap text-[10px] flex-shrink-0">
      <span className="text-zinc-400">📈 5m bars · updated 4:39:53 PM ET <Pill color="emerald" className="ml-1">● LIVE</Pill></span>
      <span className="ml-auto"><Pill color="amber">🟡 PARTIAL · 55% COVERAGE</Pill></span>
    </div>
    <div className="px-3 py-1 border-b border-zinc-800/50 flex items-center gap-1 flex-wrap flex-shrink-0">
      {[['🟡', 'VWAP'], ['🟢', 'EMA 20'], ['🟠', 'EMA 50'], ['🔴', 'EMA 200'], ['🟣', 'BB↑'], ['🟣', 'BB-'], ['🟣', 'BB↓'], ['🟢', 'S/R'], ['🟣', 'VP'], ['🟢', 'SR+'], ['🟢', 'Bot']].map(([dot, l], i) => (
        <Pill key={i} color="zinc" className="text-[9px]">{dot} {l}</Pill>
      ))}
      <div className="ml-auto flex items-center gap-1">
        {['1m', '5m', '15m', '1h', '1d'].map(t => <button key={t} className={`text-[10px] px-1.5 py-0.5 rounded ${t === '5m' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>)}
      </div>
    </div>
    <div className="flex-1 flex items-center justify-center text-zinc-700 text-xs bg-zinc-950/30">[ ChartPanel — same TradingView component as today ]</div>
  </div>
);

// ─── ⑥ TIMELINE (merged Unified Stream + Stream Deep Feed) ─────
const TimelinePane = () => {
  const [tab, setTab] = useState('reasoning');
  const tabs = [
    { id: 'reasoning', label: '🧠 Reasoning', count: 1228 },
    { id: 'decisions', label: '📊 Decisions', count: 170 },
    { id: 'trades', label: '📦 Trades', count: 162 },
    { id: 'orders', label: '📤 Orders', count: 1232 },
    { id: 'all', label: '🔍 All', count: 462 },
  ];
  const messages = [
    { t: '4:48:07 PM', sym: 'STM', sev: 'reject', text: 'rejection eod no new entries · Passing on STM Off Sides Short — did not meet criteria. Reason: eod_no_new_entries.' },
    { t: '4:48:07 PM', sym: 'STM', sev: 'warn', text: 'eod no new entries hard · Passing on STM off_sides_short — past 3:55pm ET, EOD flatten window owns the last 5 minutes.' },
    { t: '4:35:06 PM', sym: 'CPNG', sev: 'reject', text: 'rejection eod no new entries · Passing on CPNG Off Sides Short — did not meet criteria. Reason: eod_no_new_entries.' },
    { t: '4:35:06 PM', sym: 'DAL', sev: 'reject', text: 'rejection eod no new entries · Passing on DAL Off Sides Short — did not meet criteria. Reason: eod_no_new_entries.' },
    { t: '4:35:06 PM', sym: 'DAL', sev: 'warn', text: 'eod no new entries hard · Passing on DAL off_sides_short — past 3:55pm ET, EOD flatten window owns the last 5 minutes.' },
    { t: '4:35:06 PM', sym: 'GLDM', sev: 'reject', text: 'rejection eod no new entries · Passing on GLDM Off Sides Short — did not meet criteria.' },
    { t: '3:48:00 PM', sym: 'FDX', sev: 'info', text: 'EVALUATING SETUP · Evaluating FDX gap_fade LONG (TQS 80)' },
  ];
  const sevDot = { info: 'bg-cyan-400', warn: 'bg-amber-400', pass: 'bg-emerald-400', reject: 'bg-rose-400' };
  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <div className="border-b border-zinc-800 flex-shrink-0">
        <div className="flex items-center px-1 overflow-x-auto">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} className={`px-3 py-1.5 text-xs font-medium border-b-2 whitespace-nowrap ${tab === t.id ? 'text-cyan-300 border-cyan-500' : 'text-zinc-500 border-transparent hover:text-zinc-300'}`}>
              {t.label} <span className="text-[9px] text-zinc-600 ml-1">{t.count}</span>
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2 px-2">
            <Pill color="emerald">● live</Pill>
            <span className="text-[10px] text-zinc-500">today: alerts <span className="text-zinc-300">1228</span> · high <span className="text-zinc-300">170</span> · eligible <span className="text-zinc-300">162</span> · orders <span className="text-zinc-300">1232</span></span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-2 py-1 border-t border-zinc-800/50 flex-wrap">
          <span className="text-[9px] text-zinc-500 uppercase">Range:</span>
          {['5M', '30M', '1H', '4H', '1D', '7D'].map(r => <button key={r} className={`text-[9px] px-1.5 py-0.5 rounded ${r === '1H' ? 'bg-cyan-900/40 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}>{r}</button>)}
          <input placeholder="Symbol (AAPL)" className="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[10px] w-24 ml-1" />
          <input placeholder="🔎 search ('WULF skip', 'gate', ...)" className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[10px] min-w-32" />
          <span className="text-[9px] text-zinc-500 uppercase ml-1">Filter:</span>
          {['SCAN', 'EVAL', 'ORDER', 'FILL', 'WIN', 'LOSS', 'SKIP'].map(f => <button key={f} className="text-[9px] px-1.5 py-0.5 rounded text-zinc-400 border border-zinc-800 hover:bg-zinc-900">{f}</button>)}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {messages.map((m, i) => (
          <div key={i} className="px-3 py-1.5 border-b border-zinc-900/50 hover:bg-zinc-900/30 text-[11px]">
            <div className="flex items-baseline gap-2">
              <span className={`w-1.5 h-1.5 rounded-full mt-1 ${sevDot[m.sev]}`} />
              <span className="text-[9px] text-zinc-600 font-mono whitespace-nowrap">{m.t}</span>
              <span className="text-xs font-bold text-cyan-400 font-mono">{m.sym}</span>
              <span className="text-zinc-300 flex-1">{m.text}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-zinc-800 px-2 py-1.5 flex items-center gap-2 flex-shrink-0">
        <input placeholder="Ask SentCom anything..." className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs" />
        <button className="bg-cyan-900/40 text-cyan-300 px-2 py-1 rounded">▶</button>
      </div>
    </div>
  );
};

// ─── RIGHT SIDEBAR (Briefings rotation + ML Audit + Open + SentCom Intel) ─
const Briefings = () => {
  const [tab, setTab] = useState('eod');
  return (
    <div className="border-b border-zinc-800 flex-shrink-0">
      <div className="px-2 py-1.5 flex items-center gap-1 flex-wrap">
        {[['morning', '☀️ Morning Prep'], ['midday', '🌤 Mid-Day Recap'], ['power', '⚡ Power Hour'], ['eod', '🌙 EOD Recap']].map(([id, l]) => (
          <button key={id} onClick={() => setTab(id)} className={`text-[10px] px-2 py-0.5 rounded border ${tab === id ? 'bg-cyan-900/40 text-cyan-300 border-cyan-700' : 'text-zinc-400 border-zinc-800 hover:bg-zinc-900'}`}>{l}</button>
        ))}
        <button className="ml-auto text-[10px] text-zinc-500 hover:text-zinc-300">🔄 RELIEF</button>
      </div>
      <div className="px-3 py-1.5 text-[10px] text-zinc-500 italic">Strategy mix · waiting for first alerts</div>
    </div>
  );
};

const ShadowVsReal = () => (
  <div className="px-3 py-2 border-b border-zinc-800 flex-shrink-0">
    <div className="flex items-center justify-between mb-1.5">
      <span className="text-[10px] text-zinc-500 uppercase">⚖ Shadow vs Real</span>
      <span className="text-[10px] text-emerald-400 font-mono">↗ +32pp · shadow ahead</span>
    </div>
    <div className="grid grid-cols-2 gap-2">
      <div className="bg-zinc-900 border border-violet-700/40 rounded p-2">
        <div className="text-[9px] text-zinc-500">SHADOW</div>
        <div className="text-violet-300 font-bold text-base">66%</div>
        <div className="text-[9px] text-zinc-500">10.7k graded · 11.0k logged</div>
        <div className="text-[9px] text-zinc-500">10.9k exec · 1? watch-only</div>
      </div>
      <div className="bg-zinc-900 border border-emerald-700/40 rounded p-2">
        <div className="text-[9px] text-zinc-500">REAL</div>
        <div className="text-emerald-300 font-bold text-base">33%</div>
        <div className="text-[9px] text-zinc-500">105 closed</div>
        <div className="text-[9px] text-emerald-400">+$73,903</div>
      </div>
    </div>
  </div>
);

const MLFeatureAudit = () => (
  <div className="px-3 py-2 border-b border-zinc-800 flex-shrink-0">
    <div className="flex items-center justify-between mb-1.5">
      <span className="text-[10px] text-zinc-500 uppercase flex items-center gap-1">📊 ML Feature Audit</span>
      <button className="text-[10px] text-zinc-500 hover:text-cyan-300">⟳</button>
    </div>
    <div className="flex gap-1 mb-1.5">
      <input placeholder="🔎 Symbol (e.g. NVDA)" className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-[10px]" />
      <button className="bg-zinc-900 border border-zinc-800 hover:border-cyan-700 rounded px-2 py-0.5 text-[10px] text-zinc-300">AUDIT</button>
    </div>
    <div className="text-[9px] text-zinc-500">Type a symbol or click any $TICKER elsewhere to audit which ML label-features fire on it right now.</div>
  </div>
);

const OpenPositions = () => {
  const positions = [
    { sym: 'FDX', dir: 'DAY 2 long', mult: '2x', tag: 'PARTIAL', age: 'AMBER · 8s old', pnl: '+$648 · +0.0R', sl: '$350.32', pt: '$393.67', sh: '276', smb: 'B' },
    { sym: 'UPS', dir: 'DAY 2 long', tag: 'PARTIAL', age: 'AMBER · 8s old', pnl: '-$124 · -0.0R', sl: '$94.98', pt: '$107.57', sh: '885', smb: 'B' },
    { sym: 'SBUX', dir: 'SHORT', tag: 'ORPHAN ?', age: 'AMBER · 8s old', extra: 'RECONCILED', pnl: '+$258', sh: '273' },
    { sym: 'ADBE', dir: 'SHORT', tag: 'ORPHAN ?', age: 'AMBER · 8s old', extra: 'RECONCILED', pnl: '-$2', sh: '15' },
    { sym: 'LITE', dir: 'LONG', tag: 'ORPHAN ?', age: 'AMBER · 8s old', extra: 'RECONCILED', pnl: '-$121', sh: '8' },
    { sym: 'LIN', dir: 'SHORT', tag: 'ORPHAN ?', age: 'AMBER · 8s old', extra: 'RECONCILED', pnl: '+$5', sh: '6' },
  ];
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
        <span className="text-[10px] text-zinc-500 uppercase flex items-center gap-1">OPEN (6) <Pill color="emerald">● 6s</Pill> <button className="bg-cyan-900/40 text-cyan-300 px-1.5 py-0.5 rounded text-[9px]">RECONCILE 6</button></span>
        <span className="text-[10px] text-emerald-400 font-mono">+$657</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {positions.map((p, i) => (
          <div key={i} className="px-3 py-2 border-b border-zinc-900/50 hover:bg-zinc-900/30">
            <div className="flex items-center gap-1 mb-1 flex-wrap">
              <span className="text-sm font-bold font-mono text-zinc-100">{p.sym}</span>
              <Pill color={p.dir.includes('LONG') ? 'emerald' : p.dir.includes('SHORT') ? 'rose' : 'cyan'}>{p.dir}</Pill>
              {p.mult && <Pill color="violet">{p.mult}</Pill>}
              <Pill color="amber">{p.tag}</Pill>
              <Pill color="amber">● {p.age}</Pill>
              {p.extra && <Pill color="violet">{p.extra}</Pill>}
              <span className={`ml-auto text-[10px] font-mono ${p.pnl.includes('+') ? 'text-emerald-400' : 'text-rose-400'}`}>{p.pnl}</span>
            </div>
            <div className="text-[9px] text-zinc-500 font-mono pl-1">{p.sh}sh{p.sl ? ` · ORIGINAL SL → ${p.sl} · PT ${p.pt}` : ''}{p.smb ? ` · SMB ${p.smb}` : ''}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const SentComIntel = () => (
  <div className="border-t border-zinc-800 flex-shrink-0">
    <div className="px-3 py-1.5 flex items-center justify-between border-b border-zinc-800/50">
      <span className="text-[10px] text-zinc-500 uppercase flex items-center gap-1">🧠 SentCom Intelligence</span>
      <button className="text-[10px] text-zinc-500 hover:text-cyan-300">⟳</button>
    </div>
    <div className="px-3 py-1.5 flex items-center gap-2 border-b border-zinc-800/50 text-[10px]">
      <Pill color="emerald">↗ NORMAL</Pill>
      <span className="font-mono text-zinc-300">5421</span><span className="text-zinc-500">eval</span>
      <span className="font-mono text-zinc-300">1838</span><span className="text-zinc-500">taken</span>
      <span className="font-mono text-zinc-300">2999</span><span className="text-zinc-500">skip</span>
      <span className="font-mono text-emerald-300 ml-auto">34%</span>
    </div>
    <div className="max-h-44 overflow-y-auto px-2 py-1.5 space-y-1.5">
      {[
        { sym: 'KMI', setup: 'squeeze', verdict: 'SKIP', verdictColor: 'rose', pts: '38 pts', t: '03:54 PM',
          notes: ['Regime leans bullish (score 64.0) — moderate alignment (+10)', 'Model consensus STRONG (100% of 14 models, avg acc 57%) (+15)', 'Live general sees NO EDGE (flat, 98% conf) (-2)'],
          bars: [['Regime', 75, 'emerald'], ['Consensus', 80, 'emerald'], ['Live Model', 12, 'rose'], ['Quality', 78, 'emerald'], ['VAE Regime', 25, 'amber']] },
        { sym: 'XLU', setup: 'squeeze', verdict: 'GO', verdictColor: 'emerald', pts: '43 pts', t: '03:54 PM',
          notes: ['Regime leans bullish (score 64.0) — moderate alignment (+10)', 'Model consensus STRONG (100% of 14 models, avg acc 57%) (+15)', 'Live general sees NO EDGE (flat, 94% conf) (-2)'],
          bars: [['Regime', 75, 'emerald'], ['Consensus', 80, 'emerald'], ['Live Model', 0, 'rose']] }
      ].map((c, i) => (
        <div key={i} className="bg-zinc-900/40 border border-zinc-800 rounded p-2 text-[10px]">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5">
              <span className="font-bold font-mono">{c.sym}</span>
              <span className="text-zinc-400">{c.setup}</span>
              <Pill color={c.verdictColor}>{c.verdict}</Pill>
            </div>
            <div className="flex items-center gap-2 text-[9px]"><span className="text-amber-400 font-mono">{c.pts}</span><span className="text-zinc-500">{c.t}</span></div>
          </div>
          {c.notes.map((n, j) => <div key={j} className="text-[10px] text-zinc-400 mb-0.5">{n}</div>)}
          <div className="space-y-0.5 mt-1">
            {c.bars.map(([l, v, color], j) => (
              <div key={j} className="flex items-center gap-1.5">
                <span className="text-[9px] text-zinc-500 w-16">{l}</span>
                <Bar pct={v} color={color} />
                <span className="text-[9px] font-mono text-zinc-400 w-6 text-right">{v > 50 ? '+' : ''}{v - 50}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  </div>
);

const RightSidebar = () => (
  <div className="bg-zinc-950 flex flex-col overflow-hidden h-full border-l border-zinc-800">
    <Briefings />
    <ShadowVsReal />
    <MLFeatureAudit />
    <OpenPositions />
    <SentComIntel />
  </div>
);

// ─── EOD ALARM (floating toast — replaces stuck banner) ──────────
const EodAlarm = () => (
  <div className="absolute top-2 left-1/2 -translate-x-1/2 z-50 bg-rose-950/95 border border-rose-700 rounded-md px-3 py-2 flex items-center gap-3 shadow-2xl backdrop-blur">
    <span className="text-rose-300">⚠</span>
    <span className="text-[11px] text-rose-100">EOD ALARM <span className="font-bold">3</span> positions still OPEN past market close — verify IB-side state</span>
    <button className="bg-rose-700 hover:bg-rose-600 text-rose-100 text-[10px] font-bold px-2 py-0.5 rounded">CLOSE ALL NOW</button>
    <button className="text-rose-400 hover:text-rose-200 text-[10px]">✕</button>
  </div>
);

// ─── STATUS STRIP ────────────────────────────────────────────────
const StatusStrip = () => (
  <div className="bg-zinc-950 border-t border-zinc-800 px-3 py-1 flex items-center justify-between flex-shrink-0 text-[10px]">
    <div className="flex items-center gap-3 text-zinc-400">
      <span>📦 <span className="text-zinc-300 font-medium">3</span> orders</span>
      <span className="text-zinc-700">·</span>
      <span>✅ <span className="text-zinc-300 font-medium">12</span> fills today</span>
      <span className="text-zinc-700">·</span>
      <span>✓ <span className="text-zinc-300 font-medium">8</span> closed +$1,247</span>
      <span className="text-zinc-700">·</span>
      <span className="text-emerald-400">⚠ <span className="font-medium">0</span> errors</span>
      <span className="text-zinc-700">·</span>
      <span>🔁 drift loop healed <span className="text-zinc-300">0</span> today</span>
      <span className="text-zinc-700">·</span>
      <span>🚨 short-leak alerts <span className="text-zinc-300">0</span></span>
    </div>
    <div className="flex items-center gap-2 text-zinc-500">
      <button className="hover:text-zinc-300">⊞ panels</button>
      <button className="hover:text-zinc-300">↑ expand</button>
    </div>
  </div>
);

// ─── ROOT ────────────────────────────────────────────────────────
export const V6LayoutPreview = () => {
  const [focused, setFocused] = useState('FDX');
  const [leftPct, setLeftPct] = useState(15);
  const [rightPct, setRightPct] = useState(20);
  const [centerTopPct, setCenterTopPct] = useState(70);
  const [chartPct, setChartPct] = useState(58);

  const outerRef = useRef(null);
  const centerRef = useRef(null);
  const topRef = useRef(null);
  const onFocusSym = useCallback((s) => setFocused(s), []);
  const centerPct = 100 - leftPct - rightPct;

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100 flex flex-col relative">
      <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-1.5 flex items-center justify-between flex-shrink-0 text-[10px]">
        <div className="flex items-center gap-2">
          <span className="text-cyan-300 font-bold text-xs">SentCom V6 — Layout Preview v3 (production-faithful)</span>
          <Pill color="amber">drag any divider · ?preview=v6</Pill>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { setLeftPct(15); setRightPct(20); setCenterTopPct(70); setChartPct(58); }} className="px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:bg-zinc-900">reset layout</button>
          <a href="?" className="text-violet-400 hover:underline">← back to V5</a>
        </div>
      </div>
      <KpiRibbon />
      <PusherStrip />

      <div ref={outerRef} className="flex-1 flex overflow-hidden relative">
        <EodAlarm />
        <div style={{ width: `${leftPct}%` }} className="flex-shrink-0 overflow-hidden"><ScannerPane focused={focused} onFocus={onFocusSym} /></div>
        <VSplit leftPct={leftPct} onChange={setLeftPct} containerRef={outerRef} />
        <div style={{ width: `${centerPct}%` }} className="flex flex-col overflow-hidden flex-shrink-0" ref={centerRef}>
          <div style={{ height: `${centerTopPct}%` }} className="flex overflow-hidden flex-shrink-0" ref={topRef}>
            <div style={{ width: `${chartPct}%` }} className="overflow-hidden flex-shrink-0"><ChartPane focused={focused} /></div>
            <VSplit leftPct={chartPct} onChange={setChartPct} containerRef={topRef} />
            <div style={{ width: `${100 - chartPct}%` }} className="overflow-hidden flex-shrink-0 border-l border-zinc-800"><ThinkingPane focused={focused} /></div>
          </div>
          <HSplit topPct={centerTopPct} onChange={setCenterTopPct} containerRef={centerRef} />
          <div style={{ height: `${100 - centerTopPct}%` }} className="overflow-hidden flex-shrink-0 border-t border-zinc-800"><TimelinePane /></div>
        </div>
        <VSplit leftPct={100 - rightPct} onChange={(p) => setRightPct(100 - p)} containerRef={outerRef} />
        <div style={{ width: `${rightPct}%` }} className="flex-shrink-0 overflow-hidden"><RightSidebar /></div>
      </div>
      <StatusStrip />
    </div>
  );
};

export default V6LayoutPreview;
