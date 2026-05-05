/* eslint-disable react/no-unescaped-entities */
import React, { useState } from 'react';

/**
 * V6 Layout Preview — 3 selectable variants with rich content.
 *
 * URL switches:
 *   ?preview=v6              → variant A (default — THINKING-dominant)
 *   ?preview=v6&variant=B    → SYMBOL DEEP-DIVE layout
 *   ?preview=v6&variant=C    → MISSION-TABBED layout
 *
 * All 3 variants share the same WATCHING / MANAGING / STATUS STRIP shells;
 * they differ in how the center column organizes CHART / THINKING / TIMELINE.
 */

// ─── shared atoms ─────────────────────────────────────────────────
const Pill = ({ children, color = 'zinc', className = '' }) => {
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
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${colors[color]} ${className}`}>
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
  <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
    <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">{title}</span>
    {right}
  </div>
);

// ─── WATCHING (left, all variants) ────────────────────────────────
const WatchingPane = ({ width = 220 }) => (
  <aside className="bg-zinc-950 border-r border-zinc-800 flex flex-col overflow-hidden flex-shrink-0" style={{ width }}>
    <SectionHeader title="Watching" right={<Pill color="cyan">12 active</Pill>} />
    <div className="flex-1 overflow-y-auto">
      <div className="px-3 py-1.5 text-[10px] text-zinc-500 uppercase tracking-wider">⚡ Tier A · 4 evaluating</div>
      {[
        { sym: 'AAPL', setup: 'squeeze', verdict: '✓', verdictColor: 'emerald', price: '145.20', chg: '+1.2%', conf: 78, note: '4/6 gates · vol 0.9×' },
        { sym: 'UPS', setup: 'reclaim', verdict: 'R', verdictColor: 'amber', price: '97.24', chg: '-0.8%', conf: 32, note: 'reject 18s · R:R 1.19' },
        { sym: 'MELI', setup: 'short', verdict: '✗', verdictColor: 'rose', price: '1810', chg: '-2.1%', conf: 24, note: 'R:R below floor' },
        { sym: 'NVDA', setup: 'breakout', verdict: '✓', verdictColor: 'emerald', price: '218.40', chg: '+3.4%', conf: 82, note: 'vol 1.4× · momentum' },
      ].map(r => (
        <div key={r.sym} className="px-3 py-2 border-b border-zinc-900 hover:bg-zinc-900/50 cursor-pointer">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-bold text-zinc-100">{r.sym}</span>
            <Pill color={r.verdictColor}>{r.verdict} {r.setup}</Pill>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-zinc-400 font-mono">${r.price}</span>
            <span className={r.chg.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}>{r.chg}</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <Bar pct={r.conf} color={r.verdictColor === 'emerald' ? 'emerald' : r.verdictColor === 'amber' ? 'amber' : 'rose'} />
            <span className="text-[10px] text-zinc-500 font-mono">{r.conf}%</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-1">{r.note}</div>
        </div>
      ))}
      <div className="px-3 py-1.5 text-[10px] text-zinc-500 uppercase tracking-wider mt-1">⚙ Tier B · 8 scanning</div>
      {[['TSLA', '+0.4%'], ['AMD', '-1.2%'], ['COIN', '+2.8%'], ['MSTR', '+1.1%'], ['PLTR', '-0.3%'], ['SOFI', '+0.7%']].map(([s, c]) => (
        <div key={s} className="px-3 py-1.5 border-b border-zinc-900 text-xs text-zinc-300 hover:bg-zinc-900/50 cursor-pointer flex items-center justify-between">
          <span>{s}</span>
          <span className={`text-[10px] font-mono ${c.startsWith('+') ? 'text-emerald-500/70' : 'text-rose-500/70'}`}>{c}</span>
        </div>
      ))}
    </div>
  </aside>
);

// ─── THINKING content (rich, reused) ─────────────────────────────
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
      <div className="bg-zinc-950/60 rounded px-2 py-1">
        <div className="text-zinc-500 text-[10px]">Entry</div>
        <div className="text-zinc-100 font-mono">$145.20</div>
      </div>
      <div className="bg-zinc-950/60 rounded px-2 py-1">
        <div className="text-zinc-500 text-[10px]">Stop</div>
        <div className="text-rose-300 font-mono">$144.50 <span className="text-[10px] text-zinc-500">−0.5%</span></div>
      </div>
      <div className="bg-zinc-950/60 rounded px-2 py-1">
        <div className="text-zinc-500 text-[10px]">Target</div>
        <div className="text-emerald-300 font-mono">$146.65 <span className="text-[10px] text-zinc-500">R:R 2.07</span></div>
      </div>
      <div className="bg-zinc-950/60 rounded px-2 py-1">
        <div className="text-zinc-500 text-[10px]">Size</div>
        <div className="text-zinc-100 font-mono">156 sh · $109 risk</div>
      </div>
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
      <div className="bg-zinc-950/40 rounded p-2">
        <div className="text-[10px] text-zinc-500 mb-1">Bull case · 65%</div>
        <div className="text-emerald-300">Target hit · +$226 gross</div>
        <div className="text-[10px] text-zinc-500 mt-1">Volume confirms, breakout holds</div>
      </div>
      <div className="bg-zinc-950/40 rounded p-2">
        <div className="text-[10px] text-zinc-500 mb-1">Base · 25%</div>
        <div className="text-zinc-300">Scratch · ±$0–40</div>
        <div className="text-[10px] text-zinc-500 mt-1">Chops at VWAP, scales out partial</div>
      </div>
      <div className="bg-zinc-950/40 rounded p-2">
        <div className="text-[10px] text-zinc-500 mb-1">Bear · 10%</div>
        <div className="text-rose-300">Stop hit · −$109</div>
        <div className="text-[10px] text-zinc-500 mt-1">Failed breakout, breaks $144.50</div>
      </div>
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

const ThinkingCardCompact = ({ sym, setup, ts, detail, watching }) => (
  <div className="bg-zinc-900/40 border border-zinc-800 rounded-md p-2">
    <div className="flex items-center justify-between mb-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-zinc-100">{sym}</span>
        <Pill color="amber">{setup}</Pill>
      </div>
      <span className="text-[10px] text-zinc-500">{ts}</span>
    </div>
    <div className="text-[11px] text-zinc-400">{detail}</div>
    <div className="text-[11px] text-violet-300 mt-1">🎯 {watching}</div>
  </div>
);

const ThinkingPane = ({ flexBasis = '25 1 0%' }) => (
  <div className="bg-zinc-950 border-b border-zinc-800 flex flex-col overflow-hidden" style={{ flex: flexBasis }}>
    <SectionHeader
      title="🧠 Thinking · per-symbol evaluations"
      right={
        <div className="flex items-center gap-2">
          <Pill color="violet">2 active</Pill>
          <button className="text-[11px] text-zinc-500 hover:text-zinc-300">📍 unpin</button>
        </div>
      }
    />
    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
      <ThinkingCardRich />
      <ThinkingCardCompact
        sym="UPS" setup="REJECTED 18s ago" ts="reclaim long"
        detail="R:R 1.19 below 1.5 floor. Considered tighter stop @ $96.85 (would qualify R:R 2.05) but stop sits below recent swing low — invalidates structure."
        watching="trend acceleration above $97.50 OR target widening to $99.20"
      />
      <ThinkingCardCompact
        sym="NVDA" setup="EVALUATING BREAKOUT LONG" ts="0.8s ago"
        detail="Vol 1.4× avg · momentum strong · all 6 gates open. About to fire — final check: position sizing vs $5k notional cap, current portfolio heat 38%."
        watching="auto-fire imminent (next eval cycle in 2.1s)"
      />
    </div>
  </div>
);

// ─── TIMELINE (merged stream, reused) ────────────────────────────
const TimelinePane = ({ flexBasis = '25 1 0%' }) => {
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
      { t: '14:22:31', sym: 'MELI', sev: 'info', text: 'short candidate stable 38s, qualifies for next eval cycle, awaiting volume spike confirmation' },
      { t: '14:21:55', sym: 'AAPL', sev: 'info', text: 'prior verdict on this setup-symbol pair: PASS → +$340 closed at target 13:01' },
      { t: '14:21:12', sym: 'NVDA', sev: 'info', text: 'breakout watch: tier A elevated to active eval, R:R math: entry $218.40 stop $216.20 target $222.80' },
    ],
    decisions: [
      { t: '13:01:22', sym: 'AAPL', sev: 'pass', text: '✅ PASS → squeeze long, 156 sh @ $145.20, R:R 3.1, ML conf 0.81' },
      { t: '12:48:09', sym: 'TSLA', sev: 'reject', text: '❌ REJECT → momentum_breakout, R:R 1.42 below floor 1.5' },
      { t: '12:31:55', sym: 'COIN', sev: 'reject', text: '❌ REJECT → reclaim long, direction unstable (flipped 8s ago)' },
    ],
    trades: [
      { t: '13:01:22', sym: 'AAPL', sev: 'info', text: '📤 placed 156 sh BUY @ market · bracket OK · trade_id=a1b2c3d4' },
      { t: '13:01:23', sym: 'AAPL', sev: 'info', text: '✅ filled 156 sh @ $145.20 · stop OK · target OK' },
      { t: '12:15:08', sym: 'GOOG', sev: 'info', text: '✅ closed 50 sh · target hit · +$72' },
    ],
  };
  const list = tab === 'all' ? [...messages.reasoning, ...messages.decisions, ...messages.trades].sort((a, b) => b.t.localeCompare(a.t)) : messages[tab];
  const sevDot = { info: 'bg-cyan-400', warn: 'bg-amber-400', pass: 'bg-emerald-400', reject: 'bg-rose-400' };

  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden" style={{ flex: flexBasis }}>
      <div className="border-b border-zinc-800">
        <div className="flex items-center px-1">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                tab === t.id ? 'text-cyan-300 border-cyan-500' : 'text-zinc-500 border-transparent hover:text-zinc-300'
              }`}
            >
              {t.label} <span className="text-[10px] text-zinc-600 ml-1">{t.count}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 border-t border-zinc-800/50">
          <input placeholder="🔎 search messages..." className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-cyan-700" />
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300">
            <option>All symbols</option>
          </select>
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300">
            <option>Live</option><option>1h</option><option>Today</option>
          </select>
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

// ─── MANAGING — RICH (reused) ────────────────────────────────────
const ManagingPositionRich = () => (
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
      {/* Live numbers grid */}
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

      {/* Bracket plan */}
      <div className="space-y-1 bg-zinc-950/40 rounded p-2">
        <div className="text-[10px] text-zinc-500 uppercase mb-1">Bracket plan</div>
        <div className="flex items-center gap-2">
          <Pill color="rose">TRAIL</Pill>
          <span className="text-zinc-300">$144.50</span>
          <span className="text-zinc-500">→ moves to</span>
          <span className="text-emerald-300">$145.00</span>
          <span className="text-zinc-500">if price hits $145.80 (in $0.40)</span>
        </div>
        <div className="flex items-center gap-2">
          <Pill color="cyan">SCALE 1/3</Pill>
          <span className="text-zinc-300">@ $146.00</span>
          <span className="text-zinc-500">pending +$120 · order ID o-7842</span>
        </div>
        <div className="flex items-center gap-2">
          <Pill color="cyan">SCALE 1/3</Pill>
          <span className="text-zinc-300">@ $146.65</span>
          <span className="text-zinc-500">target · order ID o-7843</span>
        </div>
        <div className="flex items-center gap-2">
          <Pill color="violet">RUNNER</Pill>
          <span className="text-zinc-500">52sh trails ATR-based stop after both partials</span>
        </div>
        <div className="flex items-center gap-2 pt-1 border-t border-zinc-800/50">
          <Pill color="rose">KILL</Pill>
          <span className="text-zinc-300">5m close {'<'} $144.50</span>
          <span className="text-zinc-500">= invalidates thesis</span>
        </div>
      </div>

      {/* Bot watching */}
      <div className="bg-zinc-950/40 border border-violet-800/30 rounded p-2">
        <div className="text-violet-300 font-medium mb-1 flex items-center justify-between">
          <span>🤔 Bot is watching</span>
          <span className="text-[10px] text-zinc-500">refreshed 1.2s ago</span>
        </div>
        <ul className="space-y-1 text-[11px] text-zinc-300">
          <li className="flex items-start gap-1.5"><span className="text-emerald-400">✓</span> VWAP slope (+0.02/min — healthy uptrend)</li>
          <li className="flex items-start gap-1.5"><span className="text-amber-400">⏳</span> Volume next 1m bar {'>'}800sh (currently 423sh, 67% of bar)</li>
          <li className="flex items-start gap-1.5"><span className="text-amber-400">⏳</span> Will tighten stop to $145.00 at next higher low</li>
          <li className="flex items-start gap-1.5"><span className="text-rose-400">⚠</span> NVDA correlation 0.74 — concentration alert if both red</li>
          <li className="flex items-start gap-1.5"><span className="text-zinc-500">○</span> Watching for VWAP slope flip flat → would tighten stop to BE</li>
        </ul>
      </div>

      {/* What changed since entry */}
      <div className="text-[11px]">
        <div className="text-[10px] text-zinc-500 uppercase mb-1">What's changed since entry</div>
        <div className="space-y-0.5 text-zinc-400">
          <div>• Volatility regime: <span className="text-zinc-300">stable</span> (ATR 1.82 → 1.84)</div>
          <div>• Sector strength: <span className="text-emerald-300">improving</span> (XLK +1.4%, was +0.9%)</div>
          <div>• Risk:remaining-reward: <span className="text-amber-300">degraded</span> (2.07 → 1.39)</div>
          <div>• Stop tightenings: <span className="text-zinc-300">0 of 3 planned</span></div>
        </div>
      </div>

      {/* Reasoning log */}
      <div className="border-t border-zinc-800 pt-2">
        <div className="text-[10px] text-zinc-500 uppercase mb-1">Reasoning timeline</div>
        <div className="space-y-1 text-[11px]">
          <div className="text-zinc-400 italic">
            <span className="text-zinc-500 font-mono mr-1">14:21</span>
            "3m ago: holding through pullback — structure intact, VWAP support at 145"
          </div>
          <div className="text-zinc-500 italic">
            <span className="text-zinc-600 font-mono mr-1">14:18</span>
            "6m ago: filled 156sh @ $145.20, bracket OK, scale-out plan armed"
          </div>
          <div className="text-zinc-500 italic">
            <span className="text-zinc-600 font-mono mr-1">14:17</span>
            "fired squeeze long: 5/6 gates passed, vol 1.5× avg confirmed, VWAP reclaimed"
          </div>
        </div>
      </div>

      {/* Action */}
      <div className="flex items-center gap-2 pt-1">
        <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📊 chart</button>
        <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜 full log</button>
        <button className="text-[10px] px-2 py-1 bg-cyan-900/30 hover:bg-cyan-900/50 text-cyan-300 rounded">⚙ override</button>
        <button className="text-[10px] px-2 py-1 bg-rose-900/40 hover:bg-rose-900/60 text-rose-300 rounded ml-auto">🛑 close</button>
      </div>
    </div>
  </div>
);

const ManagingPositionCompact = ({ sym, dir, sh, pnl, pnlClass, note }) => (
  <div className="bg-zinc-900/40 border border-zinc-800 rounded-md hover:border-zinc-700 cursor-pointer">
    <div className="px-3 py-2 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-zinc-100">{sym}</span>
        <Pill color={dir === 'LONG' ? 'emerald' : 'rose'}>{dir} · {sh}sh</Pill>
      </div>
      <span className={`text-xs font-mono ${pnlClass}`}>{pnl}</span>
    </div>
    <div className="px-3 pb-2 text-[11px] text-zinc-500 flex items-center gap-2 flex-wrap">
      {note}
    </div>
  </div>
);

const ManagingPane = ({ width = 380 }) => (
  <aside className="bg-zinc-950 border-l border-zinc-800 flex flex-col overflow-hidden flex-shrink-0" style={{ width }}>
    <SectionHeader
      title="🟢 Managing"
      right={
        <div className="flex items-center gap-2">
          <span className="text-xs text-emerald-400 font-mono">+$542.30</span>
          <Pill color="emerald">2 open</Pill>
        </div>
      }
    />
    <div className="px-3 py-1.5 border-b border-zinc-800/50 flex items-center gap-2 text-[10px]">
      <span className="text-zinc-500">Heat:</span>
      <Bar pct={38} color="amber" />
      <span className="text-amber-400 font-mono">38%</span>
      <span className="text-zinc-700 mx-1">·</span>
      <span className="text-zinc-500">Day P/L:</span>
      <span className="text-emerald-400 font-mono">+$1,247</span>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-2">
      <ManagingPositionRich />
      <ManagingPositionCompact
        sym="NVDA" dir="LONG" sh={24} pnl="+$511.10" pnlClass="text-emerald-400"
        note={<><span>trail $214.80</span><span>·</span><span className="text-violet-300">watching vol slowdown</span><span>·</span><span>+5.2% from entry</span></>}
      />
    </div>
  </aside>
);

// ─── EXECUTION STRIP (reused) ────────────────────────────────────
const ExecutionStrip = () => (
  <div className="bg-zinc-950 border-t border-zinc-800 px-4 py-1.5 flex items-center justify-between text-xs flex-shrink-0">
    <div className="flex items-center gap-4 text-zinc-400">
      <span className="flex items-center gap-1.5">📦 <span className="text-zinc-300 font-medium">3</span> orders pending</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5">✅ <span className="text-zinc-300 font-medium">12</span> fills today</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5">✓ <span className="text-zinc-300 font-medium">8</span> closed (+$1,247)</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5 text-emerald-400">⚠ <span className="font-medium">0</span> errors</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5">🔁 <span className="text-zinc-300">drift loop</span> healed <span className="text-zinc-300">0</span> today</span>
    </div>
    <button className="text-[11px] text-zinc-500 hover:text-zinc-300">click to expand ↑</button>
  </div>
);

// ─── CHART PLACEHOLDER ───────────────────────────────────────────
const ChartPlaceholder = ({ flexBasis = '50 1 0%', label = 'AAPL · LONG candidate' }) => (
  <div className="bg-zinc-900/50 border-b border-zinc-800 flex flex-col" style={{ flex: flexBasis }}>
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-zinc-100">{label.split(' · ')[0]}</span>
        <Pill color="emerald">{label.split(' · ')[1]}</Pill>
      </div>
      <div className="flex items-center gap-2">
        {['1m', '5m', '15m', '1h', '1d'].map(t => (
          <button key={t} className={`text-[11px] px-2 py-0.5 rounded ${t === '5m' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>
        ))}
      </div>
    </div>
    <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">[ ChartPanel renders here — same component as today ]</div>
  </div>
);

// ─── VARIANT A — THINKING-DOMINANT (reduced chart) ───────────────
const VariantA = () => (
  <div className="flex-1 flex overflow-hidden">
    <WatchingPane />
    <div className="flex-1 flex flex-col overflow-hidden">
      <ChartPlaceholder flexBasis="35 1 0%" />
      <ThinkingPane flexBasis="40 1 0%" />
      <TimelinePane flexBasis="25 1 0%" />
    </div>
    <ManagingPane />
  </div>
);

// ─── VARIANT B — SYMBOL DEEP-DIVE (chart + thinking SIDE-BY-SIDE) ─
const VariantB = () => (
  <div className="flex-1 flex overflow-hidden">
    <WatchingPane />
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex flex-1 overflow-hidden border-b border-zinc-800" style={{ flex: '70 1 0%' }}>
        <div className="flex-1 flex flex-col overflow-hidden border-r border-zinc-800">
          <ChartPlaceholder flexBasis="100 1 0%" />
        </div>
        <div className="bg-zinc-950 flex flex-col overflow-hidden" style={{ width: 460 }}>
          <SectionHeader title="🧠 AAPL · live reasoning" right={<Pill color="cyan">eval cycle #14</Pill>} />
          <div className="flex-1 overflow-y-auto p-2"><ThinkingCardRich /></div>
        </div>
      </div>
      <TimelinePane flexBasis="30 1 0%" />
    </div>
    <ManagingPane />
  </div>
);

// ─── VARIANT C — MISSION-TABBED CENTER ───────────────────────────
const VariantC = () => {
  const [tab, setTab] = useState('think');
  return (
    <div className="flex-1 flex overflow-hidden">
      <WatchingPane />
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="bg-zinc-950 border-b border-zinc-800 px-3 py-2 flex items-center gap-1">
          {[
            { id: 'chart', label: '📊 Chart' },
            { id: 'think', label: '🧠 Thinking' },
            { id: 'timeline', label: '📜 Timeline' },
            { id: 'split', label: '⊞ Split (chart + think)' },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                tab === t.id ? 'bg-cyan-900/50 text-cyan-300 border border-cyan-700' : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
              }`}
            >
              {t.label}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[10px] text-zinc-500">Focused:</span>
            <Pill color="cyan">AAPL</Pill>
          </div>
        </div>
        <div className="flex-1 flex overflow-hidden">
          {tab === 'chart' && <ChartPlaceholder flexBasis="100 1 0%" />}
          {tab === 'think' && <div className="flex-1 overflow-y-auto p-3 space-y-3 bg-zinc-950">
            <ThinkingCardRich />
            <ThinkingCardCompact sym="UPS" setup="REJECTED 18s ago" ts="reclaim long" detail="R:R 1.19 below 1.5 floor." watching="trend acceleration" />
            <ThinkingCardCompact sym="NVDA" setup="EVALUATING BREAKOUT" ts="0.8s ago" detail="All 6 gates open · auto-fire imminent." watching="position sizing check" />
          </div>}
          {tab === 'timeline' && <TimelinePane flexBasis="100 1 0%" />}
          {tab === 'split' && (
            <>
              <ChartPlaceholder flexBasis="50 1 0%" />
              <div className="bg-zinc-950 flex flex-col overflow-hidden border-l border-zinc-800" style={{ flex: '50 1 0%' }}>
                <div className="flex-1 overflow-y-auto p-2"><ThinkingCardRich /></div>
              </div>
            </>
          )}
        </div>
      </div>
      <ManagingPane />
    </div>
  );
};

// ─── ROOT ────────────────────────────────────────────────────────
export const V6LayoutPreview = () => {
  const variant = typeof window !== 'undefined'
    ? (new URLSearchParams(window.location.search).get('variant') || 'A').toUpperCase()
    : 'A';

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100 flex flex-col">
      <div className="bg-zinc-950 border-b border-zinc-800 px-4 py-2 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-cyan-300">SentCom V6 — Layout Preview</span>
          <Pill color="amber">mockup · static dummy data · variant {variant}</Pill>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-zinc-500 mr-2">switch variant:</span>
          {['A', 'B', 'C'].map(v => (
            <a
              key={v}
              href={`?preview=v6&variant=${v}`}
              className={`text-[11px] px-2 py-0.5 rounded border ${
                variant === v ? 'bg-cyan-900/40 text-cyan-300 border-cyan-700' : 'text-zinc-400 border-zinc-700 hover:bg-zinc-900'
              }`}
            >
              {v === 'A' ? 'A · Thinking-dominant' : v === 'B' ? 'B · Symbol deep-dive' : 'C · Mission-tabbed'}
            </a>
          ))}
          <span className="text-zinc-700 mx-2">·</span>
          <a href="?" className="text-[11px] text-violet-400 hover:underline">← back to V5</a>
        </div>
      </div>
      {variant === 'B' ? <VariantB /> : variant === 'C' ? <VariantC /> : <VariantA />}
      <ExecutionStrip />
    </div>
  );
};

export default V6LayoutPreview;
