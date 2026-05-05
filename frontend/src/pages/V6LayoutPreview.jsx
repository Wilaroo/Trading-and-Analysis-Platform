/* eslint-disable react/no-unescaped-entities */
import React, { useState, useRef, useEffect, useCallback } from 'react';

/**
 * V6 Layout Preview — Variant B (Symbol Deep-Dive) with operator-requested upgrades:
 *   • Drag-resizable splits everywhere (vertical + horizontal)
 *   • Scanner pipeline-stage filter pills at top
 *   • Rich expandable scanner cards (full reason / score / triggers)
 *   • THINKING pane Auto-rotate ↔ Pinned toggle
 *   • Same content density at every pipeline stage (scan → eval → manage)
 *
 * URL: ?preview=v6
 */

// ─── shared atoms ─────────────────────────────────────────────────
const Pill = ({ children, color = 'zinc', className = '', onClick }) => {
  const colors = {
    zinc: 'bg-zinc-800 text-zinc-300 border-zinc-700',
    emerald: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/60',
    rose: 'bg-rose-900/40 text-rose-300 border-rose-700/60',
    amber: 'bg-amber-900/40 text-amber-300 border-amber-700/60',
    cyan: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/60',
    violet: 'bg-violet-900/40 text-violet-300 border-violet-700/60',
    sky: 'bg-sky-900/40 text-sky-300 border-sky-700/60',
  };
  return (
    <span onClick={onClick} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${colors[color]} ${onClick ? 'cursor-pointer hover:brightness-125' : ''} ${className}`}>
      {children}
    </span>
  );
};

const Bar = ({ pct, color = 'cyan' }) => {
  const colors = { cyan: 'bg-cyan-500', emerald: 'bg-emerald-500', amber: 'bg-amber-500', rose: 'bg-rose-500', violet: 'bg-violet-500' };
  return (
    <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden flex-1">
      <div className={`h-full ${colors[color]}`} style={{ width: `${pct}%` }} />
    </div>
  );
};

const SectionHeader = ({ title, right }) => (
  <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
    <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">{title}</span>
    {right}
  </div>
);

// ─── resizable split handle ──────────────────────────────────────
const VSplit = ({ leftPct, onChange, containerRef }) => {
  const dragging = useRef(false);
  const onDown = (e) => { dragging.current = true; e.preventDefault(); };
  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = ((e.clientX - rect.left) / rect.width) * 100;
      onChange(Math.max(10, Math.min(85, next)));
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [containerRef, onChange]);
  return (
    <div
      onMouseDown={onDown}
      className="w-[5px] cursor-col-resize bg-zinc-800 hover:bg-cyan-700 transition-colors flex-shrink-0 relative group"
      title={`drag to resize · currently ${leftPct.toFixed(0)}%`}
    >
      <div className="absolute inset-y-0 -left-0.5 -right-0.5 group-hover:bg-cyan-500/20" />
    </div>
  );
};

const HSplit = ({ topPct, onChange, containerRef }) => {
  const dragging = useRef(false);
  const onDown = (e) => { dragging.current = true; e.preventDefault(); };
  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = ((e.clientY - rect.top) / rect.height) * 100;
      onChange(Math.max(15, Math.min(85, next)));
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [containerRef, onChange]);
  return (
    <div
      onMouseDown={onDown}
      className="h-[5px] cursor-row-resize bg-zinc-800 hover:bg-cyan-700 transition-colors flex-shrink-0 relative group"
      title={`drag to resize · currently ${topPct.toFixed(0)}%`}
    >
      <div className="absolute inset-x-0 -top-0.5 -bottom-0.5 group-hover:bg-cyan-500/20" />
    </div>
  );
};

// ─── WATCHING data + components ──────────────────────────────────
// Pipeline stages: scanning → evaluating → managing → closed
const ALL_SYMBOLS = [
  { sym: 'AAPL', stage: 'evaluating', setup: 'squeeze', verdict: '✓', verdictColor: 'emerald', price: '145.20', chg: '+1.2%', conf: 78,
    reasons: ['BB squeeze 8d → release', 'vol 0.9× rising', 'VWAP $0.12 below — potential reclaim', 'XLK +1.4%', 'gates 4/6'],
    triggers: ['vol > 1.5×', 'VWAP reclaim'], tier: 'A',
    score: { trend: 78, vol: 62, momentum: 71, rs: 84 } },
  { sym: 'NVDA', stage: 'evaluating', setup: 'breakout', verdict: '✓', verdictColor: 'emerald', price: '218.40', chg: '+3.4%', conf: 82,
    reasons: ['52w high break', 'vol 1.4× confirmed', 'all 6 gates open', 'sector +2.1%'],
    triggers: ['auto-fire imminent'], tier: 'A',
    score: { trend: 92, vol: 88, momentum: 84, rs: 95 } },
  { sym: 'UPS', stage: 'evaluating', setup: 'reclaim', verdict: 'R', verdictColor: 'amber', price: '97.24', chg: '-0.8%', conf: 32,
    reasons: ['VWAP reclaim attempt', 'oversold RSI 28', 'level $97 historical support', 'failed prior session'],
    triggers: ['stop tighten OR target widen'], tier: 'A',
    score: { trend: 22, vol: 41, momentum: 28, rs: 35 } },
  { sym: 'MELI', stage: 'evaluating', setup: 'short', verdict: '✗', verdictColor: 'rose', price: '1810', chg: '-2.1%', conf: 24,
    reasons: ['relative weakness vs XLY', 'broke 50EMA', 'gap fill failed'],
    triggers: ['none — R:R below floor'], tier: 'A',
    score: { trend: 18, vol: 34, momentum: 22, rs: 12 } },

  { sym: 'AAPLm', stage: 'managing', setup: 'squeeze', verdict: 'M', verdictColor: 'cyan', price: '145.40', chg: '+0.14%',
    reasons: ['filled 14:17 @ $145.20', 'bracket OK', 'trail armed', 'scale 1/3 pending @ $146'],
    triggers: ['VWAP slope flip', 'stop tighten at next HL'], tier: 'POS', conf: 88, isPosition: true,
    score: { trend: 88, vol: 72, momentum: 81, rs: 86 } },
  { sym: 'NVDAm', stage: 'managing', setup: 'breakout', verdict: 'M', verdictColor: 'cyan', price: '218.40', chg: '+5.2%',
    reasons: ['filled 13:32 @ $207.60', 'trail $214.80', 'all targets pending'],
    triggers: ['vol slowdown', 'sector rotation'], tier: 'POS', conf: 95, isPosition: true,
    score: { trend: 92, vol: 88, momentum: 84, rs: 95 } },

  { sym: 'TSLA', stage: 'scanning', setup: 'momentum', verdict: '·', verdictColor: 'zinc', price: '248.40', chg: '+0.4%', conf: 51,
    reasons: ['HOD attempt', 'vol building', 'sector neutral'],
    triggers: ['needs vol confirm'], tier: 'B',
    score: { trend: 51, vol: 48, momentum: 55, rs: 49 } },
  { sym: 'AMD', stage: 'scanning', setup: 'reversal', verdict: '·', verdictColor: 'zinc', price: '142.10', chg: '-1.2%', conf: 38,
    reasons: ['oversold + bullish div', 'gap fill at $144.20'],
    triggers: ['needs higher low'], tier: 'B',
    score: { trend: 32, vol: 41, momentum: 38, rs: 44 } },
  { sym: 'COIN', stage: 'scanning', setup: 'momentum', verdict: '·', verdictColor: 'zinc', price: '286.00', chg: '+2.8%', conf: 64,
    reasons: ['BTC strength carry', 'breakout from consolidation'],
    triggers: ['vol confirm'], tier: 'B',
    score: { trend: 64, vol: 58, momentum: 71, rs: 62 } },
  { sym: 'MSTR', stage: 'scanning', setup: 'momentum', verdict: '·', verdictColor: 'zinc', price: '422', chg: '+1.1%', conf: 42, reasons: ['BTC proxy lag'], triggers: [], tier: 'B', score: { trend: 42, vol: 36, momentum: 48, rs: 51 } },

  { sym: 'GOOG', stage: 'closed', setup: 'squeeze', verdict: '+', verdictColor: 'emerald', price: '178.20', chg: '+0.8%', conf: 0,
    reasons: ['target hit 12:15 · +$72', 'closed 50sh', 'cooldown 4h'],
    triggers: [], tier: 'CLOSED',
    score: { trend: 65, vol: 58, momentum: 72, rs: 70 } },
  { sym: 'F', stage: 'closed', setup: 'reclaim', verdict: '−', verdictColor: 'rose', price: '11.20', chg: '-1.4%', conf: 0,
    reasons: ['stop hit 10:42 · −$48', 'failed reclaim', 'cooldown 4h'],
    triggers: [], tier: 'CLOSED',
    score: { trend: 22, vol: 31, momentum: 28, rs: 24 } },
];

const STAGE_META = {
  scanning: { label: 'Scanning', color: 'zinc', icon: '🔭' },
  evaluating: { label: 'Evaluating', color: 'cyan', icon: '🧠' },
  managing: { label: 'Managing', color: 'emerald', icon: '🟢' },
  closed: { label: 'Closed', color: 'violet', icon: '✓' },
};

const ScannerCard = ({ row, expanded, onToggle, onFocus }) => (
  <div className="border-b border-zinc-900">
    <div
      className="px-3 py-2 hover:bg-zinc-900/50 cursor-pointer"
      onClick={() => onFocus(row.sym)}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-100">{row.sym.replace(/m$/, '')}</span>
          {row.isPosition && <span className="text-[9px] text-emerald-400">POS</span>}
        </div>
        <Pill color={row.verdictColor}>{row.verdict} {row.setup}</Pill>
      </div>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="text-zinc-400 font-mono">${row.price}</span>
        <span className={row.chg.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}>{row.chg}</span>
      </div>
      <div className="flex items-center gap-2 mb-1">
        <Bar pct={row.conf} color={row.verdictColor === 'emerald' ? 'emerald' : row.verdictColor === 'amber' ? 'amber' : row.verdictColor === 'cyan' ? 'cyan' : 'rose'} />
        <span className="text-[10px] text-zinc-500 font-mono w-8 text-right">{row.conf}%</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-zinc-500 truncate flex-1">{row.reasons[0]}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(row.sym); }}
          className="text-[10px] text-zinc-500 hover:text-cyan-300 ml-2"
        >
          {expanded ? '▲ less' : '▼ more'}
        </button>
      </div>
    </div>
    {expanded && (
      <div className="px-3 pb-2 bg-zinc-950/40 border-t border-zinc-900/50 space-y-2">
        <div>
          <div className="text-[10px] text-zinc-500 uppercase mt-2 mb-1">Why scanner picked it</div>
          <ul className="space-y-0.5 text-[11px] text-zinc-300">
            {row.reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-1"><span className="text-cyan-500 mt-0.5">·</span><span>{r}</span></li>
            ))}
          </ul>
        </div>
        {row.triggers.length > 0 && (
          <div>
            <div className="text-[10px] text-zinc-500 uppercase mb-1">Will trigger when</div>
            <ul className="space-y-0.5 text-[11px] text-violet-300">
              {row.triggers.map((t, i) => (
                <li key={i} className="flex items-start gap-1"><span>🎯</span><span>{t}</span></li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <div className="text-[10px] text-zinc-500 uppercase mb-1">Score breakdown</div>
          <div className="grid grid-cols-2 gap-1 text-[10px]">
            {Object.entries(row.score).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2">
                <span className="text-zinc-500 w-12 capitalize">{k}</span>
                <Bar pct={v} color={v > 60 ? 'emerald' : v > 40 ? 'amber' : 'rose'} />
                <span className="text-zinc-400 font-mono w-7 text-right">{v}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <button className="text-[10px] px-2 py-1 bg-cyan-900/40 hover:bg-cyan-900/60 text-cyan-300 rounded">📊 chart</button>
          <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">🧠 think</button>
          <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜 history</button>
        </div>
      </div>
    )}
  </div>
);

const WatchingPane = ({ onFocus }) => {
  const [stage, setStage] = useState('all');
  const [expanded, setExpanded] = useState(new Set(['AAPL']));
  const stages = [
    { id: 'all', label: 'All', count: ALL_SYMBOLS.length },
    { id: 'scanning', label: '🔭 Scan', count: ALL_SYMBOLS.filter(s => s.stage === 'scanning').length },
    { id: 'evaluating', label: '🧠 Eval', count: ALL_SYMBOLS.filter(s => s.stage === 'evaluating').length },
    { id: 'managing', label: '🟢 Pos', count: ALL_SYMBOLS.filter(s => s.stage === 'managing').length },
    { id: 'closed', label: '✓ Done', count: ALL_SYMBOLS.filter(s => s.stage === 'closed').length },
  ];
  const filtered = stage === 'all' ? ALL_SYMBOLS : ALL_SYMBOLS.filter(s => s.stage === stage);
  const toggle = (sym) => setExpanded(prev => {
    const next = new Set(prev);
    if (next.has(sym)) next.delete(sym); else next.add(sym);
    return next;
  });

  // Group by stage when showing All
  const grouped = stage === 'all'
    ? ['evaluating', 'managing', 'scanning', 'closed'].map(s => ({ stage: s, rows: filtered.filter(r => r.stage === s) })).filter(g => g.rows.length)
    : [{ stage, rows: filtered }];

  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <SectionHeader title="Watching" right={<Pill color="cyan">{filtered.length}</Pill>} />
      <div className="px-2 py-1.5 border-b border-zinc-800/50 flex flex-wrap items-center gap-1">
        {stages.map(s => (
          <button
            key={s.id}
            onClick={() => setStage(s.id)}
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              stage === s.id ? 'bg-cyan-900/40 text-cyan-300 border-cyan-700' : 'text-zinc-400 border-zinc-800 hover:bg-zinc-900'
            }`}
          >
            {s.label} <span className="text-[9px] text-zinc-500 ml-0.5">{s.count}</span>
          </button>
        ))}
      </div>
      <div className="px-2 py-1 border-b border-zinc-800/50 flex items-center gap-1">
        <input placeholder="🔎 filter symbol..." className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-0.5 text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-cyan-700" />
        <select className="bg-zinc-900 border border-zinc-800 rounded px-1 py-0.5 text-[10px] text-zinc-300">
          <option>conf ↓</option>
          <option>chg ↓</option>
          <option>recent</option>
          <option>tier</option>
        </select>
      </div>
      <div className="flex-1 overflow-y-auto">
        {grouped.map(g => (
          <div key={g.stage}>
            <div className="px-3 py-1 text-[10px] text-zinc-500 uppercase tracking-wider bg-zinc-900/30 border-b border-zinc-800/40">
              {STAGE_META[g.stage].icon} {STAGE_META[g.stage].label} · {g.rows.length}
            </div>
            {g.rows.map(row => (
              <ScannerCard
                key={row.sym}
                row={row}
                expanded={expanded.has(row.sym)}
                onToggle={toggle}
                onFocus={onFocus}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── THINKING content (rich) ─────────────────────────────────────
const ThinkingCardRich = () => (
  <div className="bg-zinc-900/60 border border-cyan-700/40 rounded-md p-3">
    <div className="flex items-center justify-between mb-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-base font-bold text-zinc-100">AAPL</span>
        <Pill color="cyan">EVALUATING SQUEEZE LONG</Pill>
        <Pill color="violet">Quality A+</Pill>
        <Pill color="emerald">ML conf 78%</Pill>
      </div>
      <span className="text-[10px] text-zinc-500">last update 0.3s · eval cycle #14</span>
    </div>

    <div className="grid grid-cols-4 gap-2 mb-2 text-[11px]">
      <div className="bg-zinc-950/60 rounded px-2 py-1"><div className="text-zinc-500 text-[10px]">Entry</div><div className="text-zinc-100 font-mono">$145.20</div></div>
      <div className="bg-zinc-950/60 rounded px-2 py-1"><div className="text-zinc-500 text-[10px]">Stop</div><div className="text-rose-300 font-mono">$144.50 <span className="text-[10px] text-zinc-500">−0.5%</span></div></div>
      <div className="bg-zinc-950/60 rounded px-2 py-1"><div className="text-zinc-500 text-[10px]">Target</div><div className="text-emerald-300 font-mono">$146.65 <span className="text-[10px] text-zinc-500">R:R 2.07</span></div></div>
      <div className="bg-zinc-950/60 rounded px-2 py-1"><div className="text-zinc-500 text-[10px]">Size</div><div className="text-zinc-100 font-mono">156 sh · $109 risk</div></div>
    </div>

    <div className="mb-2">
      <div className="text-[10px] text-zinc-500 uppercase mb-1">Gates · 4 of 6 open</div>
      <div className="grid grid-cols-2 gap-1 text-[11px]">
        <div className="text-emerald-400">✓ Capital available ($24k free)</div>
        <div className="text-emerald-400">✓ R:R floor (2.07 ≥ 1.5)</div>
        <div className="text-emerald-400">✓ Direction stable 38s</div>
        <div className="text-emerald-400">✓ No cooldown (last reject 4h ago)</div>
        <div className="text-amber-400">✗ Volume confirm (0.9× vs 1.5× target)</div>
        <div className="text-amber-400">✗ VWAP reclaim (price $145.20, VWAP $145.32)</div>
      </div>
    </div>

    <div className="mb-2 bg-zinc-950/40 border border-violet-800/30 rounded p-2">
      <div className="text-violet-300 font-medium text-[11px] mb-1">🎯 Watching for trigger:</div>
      <ul className="space-y-0.5 text-[11px] text-zinc-300">
        <li>• 5m volume {'>'} 1.5× avg (currently 0.9× → need +67%)</li>
        <li>• AND VWAP reclaim above $145.32 (currently $0.12 below)</li>
        <li>• Auto-fires when both conditions hold for 8 consecutive seconds</li>
      </ul>
    </div>

    <div className="mb-2 grid grid-cols-3 gap-2 text-[11px]">
      <div className="bg-zinc-950/40 rounded p-2"><div className="text-[10px] text-zinc-500 mb-1">Bull · 65%</div><div className="text-emerald-300">Target hit · +$226</div><div className="text-[10px] text-zinc-500 mt-1">Volume confirms, breakout holds</div></div>
      <div className="bg-zinc-950/40 rounded p-2"><div className="text-[10px] text-zinc-500 mb-1">Base · 25%</div><div className="text-zinc-300">Scratch · ±$0–40</div><div className="text-[10px] text-zinc-500 mt-1">Chops at VWAP, scales out partial</div></div>
      <div className="bg-zinc-950/40 rounded p-2"><div className="text-[10px] text-zinc-500 mb-1">Bear · 10%</div><div className="text-rose-300">Stop hit · −$109</div><div className="text-[10px] text-zinc-500 mt-1">Failed breakout, breaks $144.50</div></div>
    </div>

    <div className="mb-2 text-[11px]">
      <div className="text-[10px] text-zinc-500 uppercase mb-1">Context</div>
      <div className="grid grid-cols-2 gap-1 text-zinc-400">
        <div>📊 ATR(14): $1.82 · expected move ±1.3%</div>
        <div>💧 Liquidity: 8.4M avg vol · spread $0.01</div>
        <div>🌐 Sector: XLK +1.4% (relative strength +0.3)</div>
        <div>📰 No catalyst flags · earnings 12d out</div>
        <div>🔗 Correlation: NVDA position +0.74 (concentration risk)</div>
        <div>🎲 Setup-symbol historic: 18 PASS / 6 FAIL · 75% win rate</div>
      </div>
    </div>

    <div className="mb-2 text-[11px] text-zinc-400 italic bg-zinc-950/40 p-2 rounded">
      "2 of 6 gates open — won't fire until volume confirms. Considered momentum_breakout instead but R:R was 1.42, below floor. If volume stays thin past 14:30, will downgrade to Tier B and stop watching this cycle."
    </div>

    <div className="border-t border-zinc-800 pt-2">
      <div className="text-[10px] text-zinc-500 uppercase mb-1">Last 5 verdicts on AAPL · squeeze</div>
      <div className="space-y-0.5 text-[10px]">
        <div className="flex justify-between"><span className="text-rose-300">REJECT 14:22</span><span className="text-zinc-500">R:R 1.31 below floor</span></div>
        <div className="flex justify-between"><span className="text-rose-300">REJECT 13:48</span><span className="text-zinc-500">vol confirm failed</span></div>
        <div className="flex justify-between"><span className="text-emerald-300">PASS 13:01 → +$340</span><span className="text-zinc-500">target hit 28m later</span></div>
        <div className="flex justify-between"><span className="text-rose-300">REJECT 12:18</span><span className="text-zinc-500">direction unstable</span></div>
        <div className="flex justify-between"><span className="text-emerald-300">PASS 11:42 → +$118</span><span className="text-zinc-500">scratch on partial</span></div>
      </div>
    </div>

    <div className="flex items-center gap-2 mt-2 pt-2 border-t border-zinc-800">
      <button className="text-[10px] px-2 py-1 bg-cyan-900/40 hover:bg-cyan-900/60 text-cyan-300 rounded">📍 pin to top</button>
      <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📊 chart focus</button>
      <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜 full reasoning log</button>
      <button className="text-[10px] px-2 py-1 bg-amber-900/30 hover:bg-amber-900/50 text-amber-300 rounded ml-auto">🚫 mute 1h</button>
    </div>
  </div>
);

const ThinkingPane = ({ focused }) => {
  const [mode, setMode] = useState('pinned'); // 'pinned' | 'rotate'
  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">🧠 Thinking</span>
          <Pill color="cyan">{focused}</Pill>
          <span className="text-[10px] text-zinc-500">eval cycle #14</span>
        </div>
        <div className="flex items-center gap-1 bg-zinc-900 rounded p-0.5">
          <button
            onClick={() => setMode('pinned')}
            className={`text-[10px] px-2 py-0.5 rounded ${mode === 'pinned' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}
          >📍 Pinned</button>
          <button
            onClick={() => setMode('rotate')}
            className={`text-[10px] px-2 py-0.5 rounded ${mode === 'rotate' ? 'bg-violet-900/50 text-violet-300' : 'text-zinc-500 hover:text-zinc-300'}`}
          >🔄 Rotate 8s</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <ThinkingCardRich />
        {mode === 'rotate' && (
          <div className="mt-2 text-[10px] text-zinc-500 text-center">
            ⏱ rotates to NVDA · UPS · MELI every 8s · click any symbol to pin
          </div>
        )}
      </div>
    </div>
  );
};

// ─── TIMELINE ────────────────────────────────────────────────────
const TimelinePane = () => {
  const [tab, setTab] = useState('reasoning');
  const tabs = [
    { id: 'reasoning', label: '🧠 Reasoning', count: 47 },
    { id: 'decisions', label: '📊 Decisions', count: 12 },
    { id: 'trades', label: '📦 Trades', count: 8 },
    { id: 'all', label: '🔍 All', count: 67 },
  ];
  const messages = {
    reasoning: [
      { t: '14:23:04', sym: 'AAPL', sev: 'info', text: 'evaluating squeeze long, 4 of 6 gates open, watching volume confirm and VWAP reclaim' },
      { t: '14:22:48', sym: 'UPS', sev: 'warn', text: 'rejected reclaim — R:R 1.19 below 1.5 floor. Need stop @ $96.85 or target @ $99.20 to qualify' },
      { t: '14:22:31', sym: 'MELI', sev: 'info', text: 'short candidate stable 38s, qualifies for next eval cycle' },
      { t: '14:21:55', sym: 'AAPL', sev: 'info', text: 'prior verdict on this setup-symbol pair: PASS → +$340 closed at target 13:01' },
    ],
    decisions: [
      { t: '13:01:22', sym: 'AAPL', sev: 'pass', text: '✅ PASS → squeeze long, 156 sh @ $145.20, R:R 3.1' },
      { t: '12:48:09', sym: 'TSLA', sev: 'reject', text: '❌ REJECT → momentum_breakout, R:R 1.42 below floor' },
    ],
    trades: [
      { t: '13:01:22', sym: 'AAPL', sev: 'info', text: '📤 placed 156 sh BUY @ market · bracket OK' },
      { t: '13:01:23', sym: 'AAPL', sev: 'info', text: '✅ filled 156 sh @ $145.20' },
    ],
  };
  const list = tab === 'all' ? [...messages.reasoning, ...messages.decisions, ...messages.trades].sort((a, b) => b.t.localeCompare(a.t)) : messages[tab];
  const sevDot = { info: 'bg-cyan-400', warn: 'bg-amber-400', pass: 'bg-emerald-400', reject: 'bg-rose-400' };
  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
      <div className="border-b border-zinc-800 flex-shrink-0">
        <div className="flex items-center px-1">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${tab === t.id ? 'text-cyan-300 border-cyan-500' : 'text-zinc-500 border-transparent hover:text-zinc-300'}`}
            >
              {t.label} <span className="text-[10px] text-zinc-600 ml-1">{t.count}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 border-t border-zinc-800/50">
          <input placeholder="🔎 search messages..." className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-cyan-700" />
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300"><option>All symbols</option></select>
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300"><option>Live</option><option>1h</option><option>Today</option></select>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.map((m, i) => (
          <div key={i} className="px-3 py-2 border-b border-zinc-900/50 hover:bg-zinc-900/30">
            <div className="flex items-baseline gap-2">
              <span className={`w-1.5 h-1.5 rounded-full mt-1.5 ${sevDot[m.sev]}`} />
              <span className="text-[10px] text-zinc-600 font-mono">{m.t}</span>
              <span className="text-xs font-bold text-cyan-400">{m.sym}</span>
              <span className="text-xs text-zinc-300 flex-1">{m.text}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── MANAGING (rich, same as before) ─────────────────────────────
const ManagingPane = () => (
  <div className="bg-zinc-950 flex flex-col overflow-hidden h-full">
    <SectionHeader title="🟢 Managing" right={<div className="flex items-center gap-2"><span className="text-xs text-emerald-400 font-mono">+$542.30</span><Pill color="emerald">2 open</Pill></div>} />
    <div className="px-3 py-1.5 border-b border-zinc-800/50 flex items-center gap-2 text-[10px] flex-shrink-0">
      <span className="text-zinc-500">Heat:</span>
      <Bar pct={38} color="amber" />
      <span className="text-amber-400 font-mono">38%</span>
      <span className="text-zinc-700 mx-1">·</span>
      <span className="text-zinc-500">Day P/L:</span>
      <span className="text-emerald-400 font-mono">+$1,247</span>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-2">
      <div className="bg-zinc-900/60 border border-emerald-700/40 rounded-md">
        <div className="px-3 py-2 border-b border-zinc-800">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-bold text-zinc-100">AAPL</span>
              <Pill color="emerald">LONG · 156sh</Pill>
              <Pill color="cyan">A+ setup</Pill>
            </div>
            <div className="text-right">
              <div className="text-sm font-mono text-emerald-400">+$31.20</div>
              <div className="text-[10px] text-zinc-500">+0.14% · age 4m 12s</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Pill color="emerald">✓ IB synced 156sh</Pill>
            <Pill color="violet">trail armed</Pill>
            <Pill color="cyan">scale 1/3 pending</Pill>
          </div>
        </div>
        <div className="px-3 py-2 space-y-2 text-[11px]">
          <div className="grid grid-cols-4 gap-1 text-[10px]">
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">Entry</div><div className="text-zinc-100 font-mono">$145.20</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">Now</div><div className="text-emerald-300 font-mono">$145.40</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">Peak</div><div className="text-zinc-300 font-mono">$145.62</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">DD</div><div className="text-rose-400 font-mono">−$0.22</div></div>
          </div>
          <div className="grid grid-cols-3 gap-1 text-[10px]">
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">To stop</div><div className="text-rose-300 font-mono">−$0.90 / −0.62%</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">To target</div><div className="text-emerald-300 font-mono">+$1.25 / +0.86%</div></div>
            <div className="bg-zinc-950/60 rounded px-1.5 py-1"><div className="text-zinc-500">RR live</div><div className="text-cyan-300 font-mono">1.39 (was 2.07)</div></div>
          </div>
          <div className="space-y-1 bg-zinc-950/40 rounded p-2">
            <div className="text-[10px] text-zinc-500 uppercase mb-1">Bracket plan</div>
            <div className="flex items-center gap-2"><Pill color="rose">TRAIL</Pill><span className="text-zinc-300">$144.50</span><span className="text-zinc-500">→ moves to</span><span className="text-emerald-300">$145.00</span><span className="text-zinc-500">if price hits $145.80</span></div>
            <div className="flex items-center gap-2"><Pill color="cyan">SCALE 1/3</Pill><span className="text-zinc-300">@ $146.00</span><span className="text-zinc-500">pending +$120</span></div>
            <div className="flex items-center gap-2"><Pill color="cyan">SCALE 1/3</Pill><span className="text-zinc-300">@ $146.65</span><span className="text-zinc-500">target</span></div>
            <div className="flex items-center gap-2"><Pill color="violet">RUNNER</Pill><span className="text-zinc-500">52sh trails ATR-based stop</span></div>
            <div className="flex items-center gap-2 pt-1 border-t border-zinc-800/50"><Pill color="rose">KILL</Pill><span className="text-zinc-300">5m close {'<'} $144.50</span><span className="text-zinc-500">= invalidates thesis</span></div>
          </div>
          <div className="bg-zinc-950/40 border border-violet-800/30 rounded p-2">
            <div className="text-violet-300 font-medium mb-1 flex items-center justify-between"><span>🤔 Bot is watching</span><span className="text-[10px] text-zinc-500">refreshed 1.2s ago</span></div>
            <ul className="space-y-1 text-[11px] text-zinc-300">
              <li className="flex items-start gap-1.5"><span className="text-emerald-400">✓</span> VWAP slope (+0.02/min — healthy)</li>
              <li className="flex items-start gap-1.5"><span className="text-amber-400">⏳</span> Volume next 1m bar {'>'}800sh (currently 423sh, 67% of bar)</li>
              <li className="flex items-start gap-1.5"><span className="text-amber-400">⏳</span> Will tighten stop to $145.00 at next higher low</li>
              <li className="flex items-start gap-1.5"><span className="text-rose-400">⚠</span> NVDA correlation 0.74 — concentration alert if both red</li>
              <li className="flex items-start gap-1.5"><span className="text-zinc-500">○</span> VWAP slope flip → tighten to BE</li>
            </ul>
          </div>
          <div className="text-[11px]">
            <div className="text-[10px] text-zinc-500 uppercase mb-1">What's changed since entry</div>
            <div className="space-y-0.5 text-zinc-400">
              <div>• Volatility regime: <span className="text-zinc-300">stable</span> (ATR 1.82 → 1.84)</div>
              <div>• Sector strength: <span className="text-emerald-300">improving</span> (XLK +1.4%, was +0.9%)</div>
              <div>• Risk:remaining-reward: <span className="text-amber-300">degraded</span> (2.07 → 1.39)</div>
              <div>• Stop tightenings: <span className="text-zinc-300">0 of 3 planned</span></div>
            </div>
          </div>
          <div className="border-t border-zinc-800 pt-2">
            <div className="text-[10px] text-zinc-500 uppercase mb-1">Reasoning timeline</div>
            <div className="space-y-1 text-[11px]">
              <div className="text-zinc-400 italic"><span className="text-zinc-500 font-mono mr-1">14:21</span>"holding through pullback — structure intact, VWAP support at 145"</div>
              <div className="text-zinc-500 italic"><span className="text-zinc-600 font-mono mr-1">14:18</span>"filled 156sh @ $145.20, bracket OK"</div>
              <div className="text-zinc-500 italic"><span className="text-zinc-600 font-mono mr-1">14:17</span>"fired squeeze long: 5/6 gates passed"</div>
            </div>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📊 chart</button>
            <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜 full log</button>
            <button className="text-[10px] px-2 py-1 bg-cyan-900/30 hover:bg-cyan-900/50 text-cyan-300 rounded">⚙ override</button>
            <button className="text-[10px] px-2 py-1 bg-rose-900/40 hover:bg-rose-900/60 text-rose-300 rounded ml-auto">🛑 close</button>
          </div>
        </div>
      </div>
      <div className="bg-zinc-900/40 border border-zinc-800 rounded-md hover:border-zinc-700 cursor-pointer">
        <div className="px-3 py-2 flex items-center justify-between">
          <div className="flex items-center gap-2"><span className="text-sm font-bold text-zinc-100">NVDA</span><Pill color="emerald">LONG · 24sh</Pill></div>
          <span className="text-xs font-mono text-emerald-400">+$511.10</span>
        </div>
        <div className="px-3 pb-2 text-[11px] text-zinc-500 flex items-center gap-2 flex-wrap">
          <span>trail $214.80</span><span>·</span><span className="text-violet-300">watching vol slowdown</span><span>·</span><span>+5.2% from entry</span>
        </div>
      </div>
    </div>
  </div>
);

// ─── CHART ───────────────────────────────────────────────────────
const ChartPlaceholder = ({ focused }) => (
  <div className="bg-zinc-900/50 flex flex-col h-full">
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between flex-shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-zinc-100">{focused}</span>
        <Pill color="emerald">LONG candidate</Pill>
        <span className="text-xs text-zinc-500">Apple Inc · NASDAQ</span>
      </div>
      <div className="flex items-center gap-2">
        {['1m', '5m', '15m', '1h', '1d'].map(t => (
          <button key={t} className={`text-[11px] px-2 py-0.5 rounded ${t === '5m' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>
        ))}
      </div>
    </div>
    <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">[ ChartPanel renders here ]</div>
  </div>
);

// ─── EXECUTION STRIP ─────────────────────────────────────────────
const ExecutionStrip = () => (
  <div className="bg-zinc-950 border-t border-zinc-800 px-4 py-1.5 flex items-center justify-between text-xs flex-shrink-0">
    <div className="flex items-center gap-4 text-zinc-400">
      <span>📦 <span className="text-zinc-300 font-medium">3</span> orders pending</span>
      <span className="text-zinc-700">·</span>
      <span>✅ <span className="text-zinc-300 font-medium">12</span> fills today</span>
      <span className="text-zinc-700">·</span>
      <span>✓ <span className="text-zinc-300 font-medium">8</span> closed (+$1,247)</span>
      <span className="text-zinc-700">·</span>
      <span className="text-emerald-400">⚠ <span className="font-medium">0</span> errors</span>
      <span className="text-zinc-700">·</span>
      <span>🔁 drift loop healed <span className="text-zinc-300">0</span> today</span>
    </div>
    <button className="text-[11px] text-zinc-500 hover:text-zinc-300">click to expand ↑</button>
  </div>
);

// ─── ROOT — fully resizable layout ───────────────────────────────
export const V6LayoutPreview = () => {
  const [focused, setFocused] = useState('AAPL');
  // Outer 3-col: WATCHING | CENTER | MANAGING
  const [leftPct, setLeftPct] = useState(15);
  const [rightPct, setRightPct] = useState(22);
  // Center is split horizontally: top (chart+thinking) / bottom (timeline)
  const [centerTopPct, setCenterTopPct] = useState(70);
  // Top is split vertically: chart / thinking
  const [chartPct, setChartPct] = useState(55);

  const outerRef = useRef(null);
  const centerRef = useRef(null);
  const topRef = useRef(null);

  const onFocusSym = useCallback((s) => setFocused(s.replace(/m$/, '')), []);

  // Compute widths from pct
  const centerPct = 100 - leftPct - rightPct;

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100 flex flex-col">
      <div className="bg-zinc-950 border-b border-zinc-800 px-4 py-2 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-cyan-300">SentCom V6 — Layout Preview v2</span>
          <Pill color="amber">mockup · drag any divider · ?preview=v6</Pill>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-zinc-500">Variant B · all panels resizable</span>
          <button
            onClick={() => { setLeftPct(15); setRightPct(22); setCenterTopPct(70); setChartPct(55); }}
            className="text-[11px] px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:bg-zinc-900"
          >reset layout</button>
          <a href="?" className="text-violet-400 hover:underline">← back to V5</a>
        </div>
      </div>

      <div ref={outerRef} className="flex-1 flex overflow-hidden">
        <div style={{ width: `${leftPct}%` }} className="flex-shrink-0 overflow-hidden">
          <WatchingPane onFocus={onFocusSym} />
        </div>
        <VSplit leftPct={leftPct} onChange={setLeftPct} containerRef={outerRef} />

        <div style={{ width: `${centerPct}%` }} className="flex flex-col overflow-hidden flex-shrink-0" ref={centerRef}>
          <div style={{ height: `${centerTopPct}%` }} className="flex overflow-hidden flex-shrink-0" ref={topRef}>
            <div style={{ width: `${chartPct}%` }} className="overflow-hidden flex-shrink-0">
              <ChartPlaceholder focused={focused} />
            </div>
            <VSplit leftPct={chartPct} onChange={setChartPct} containerRef={topRef} />
            <div style={{ width: `${100 - chartPct}%` }} className="overflow-hidden flex-shrink-0 border-l border-zinc-800">
              <ThinkingPane focused={focused} />
            </div>
          </div>
          <HSplit topPct={centerTopPct} onChange={setCenterTopPct} containerRef={centerRef} />
          <div style={{ height: `${100 - centerTopPct}%` }} className="overflow-hidden flex-shrink-0 border-t border-zinc-800">
            <TimelinePane />
          </div>
        </div>

        <VSplit leftPct={100 - rightPct} onChange={(p) => setRightPct(100 - p)} containerRef={outerRef} />
        <div style={{ width: `${rightPct}%` }} className="flex-shrink-0 overflow-hidden border-l border-zinc-800">
          <ManagingPane />
        </div>
      </div>

      <ExecutionStrip />
    </div>
  );
};

export default V6LayoutPreview;
