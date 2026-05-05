/* eslint-disable react/no-unescaped-entities */
import React, { useState } from 'react';

/**
 * V6 Layout Preview — proposed redesign for SentCom V5 dashboard.
 *
 * Mounted via `?preview=v6` URL escape hatch. Pure static mockup with
 * dummy data so the operator can react to the spatial layout + content
 * density before any real refactoring happens.
 *
 * 4 panes + 1 status strip:
 *   • WATCHING (left)   — scanner, persistent
 *   • CHART (center top) — focused symbol
 *   • THINKING (center mid) — bot's eval cards per symbol
 *   • TIMELINE (center bottom) — merged stream w/ tabs + search
 *   • MANAGING (right)  — open positions + real-time reasoning
 *   • EXECUTION STRIP (bottom, collapsed) — order/fill/closed counts
 */

const Pill = ({ children, color = 'zinc', className = '' }) => {
  const colors = {
    zinc: 'bg-zinc-800 text-zinc-300 border-zinc-700',
    emerald: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/60',
    rose: 'bg-rose-900/40 text-rose-300 border-rose-700/60',
    amber: 'bg-amber-900/40 text-amber-300 border-amber-700/60',
    cyan: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/60',
    violet: 'bg-violet-900/40 text-violet-300 border-violet-700/60',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${colors[color]} ${className}`}>
      {children}
    </span>
  );
};

// ─── WATCHING (scanner) ──────────────────────────────────────────
const WatchingPane = () => (
  <aside className="bg-zinc-950 border-r border-zinc-800 flex flex-col overflow-hidden" style={{ width: 220 }}>
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
      <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Watching</span>
      <Pill color="cyan">12 active</Pill>
    </div>
    <div className="flex-1 overflow-y-auto">
      <div className="px-3 py-2 text-[10px] text-zinc-500 uppercase tracking-wider border-b border-zinc-800/50">⚡ TIER A · 4</div>
      {[
        { sym: 'AAPL', setup: 'squeeze', verdict: '✓', verdictColor: 'emerald', price: '145.20', chg: '+1.2%', note: 'eval queued · 4/6 gates' },
        { sym: 'UPS', setup: 'reclaim', verdict: 'R', verdictColor: 'amber', price: '97.24', chg: '-0.8%', note: 'rejected 18s · R:R 1.19' },
        { sym: 'MELI', setup: 'short', verdict: '✗', verdictColor: 'rose', price: '1810', chg: '-2.1%', note: 'R:R 1.19 < 1.5 floor' },
        { sym: 'NVDA', setup: 'breakout', verdict: '✓', verdictColor: 'emerald', price: '218.40', chg: '+3.4%', note: 'evaluating · vol 1.4×' },
      ].map(r => (
        <div key={r.sym} className="px-3 py-2 border-b border-zinc-900 hover:bg-zinc-900/50 cursor-pointer">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-zinc-100">{r.sym}</span>
            <Pill color={r.verdictColor}>{r.verdict} {r.setup}</Pill>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span className="text-xs text-zinc-400">${r.price}</span>
            <span className={`text-xs ${r.chg.startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}`}>{r.chg}</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">{r.note}</div>
        </div>
      ))}
      <div className="px-3 py-2 text-[10px] text-zinc-500 uppercase tracking-wider border-b border-zinc-800/50 mt-2">⚙ TIER B · 8</div>
      {['TSLA', 'AMD', 'COIN', 'MSTR', 'PLTR', 'SOFI'].map(s => (
        <div key={s} className="px-3 py-1.5 border-b border-zinc-900 text-xs text-zinc-300 hover:bg-zinc-900/50 cursor-pointer flex items-center justify-between">
          <span>{s}</span>
          <span className="text-[10px] text-zinc-500">scanning</span>
        </div>
      ))}
    </div>
  </aside>
);

// ─── CHART (placeholder) ─────────────────────────────────────────
const ChartPlaceholder = () => (
  <div className="bg-zinc-900/50 border-b border-zinc-800 flex flex-col" style={{ flex: '50 1 0%' }}>
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-zinc-100">AAPL</span>
        <Pill color="emerald">LONG candidate</Pill>
        <span className="text-xs text-zinc-500">Apple Inc · NASDAQ</span>
      </div>
      <div className="flex items-center gap-2">
        {['1m', '5m', '15m', '1h', '1d'].map(t => (
          <button key={t} className={`text-[11px] px-2 py-0.5 rounded ${t === '5m' ? 'bg-cyan-900/50 text-cyan-300' : 'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>
        ))}
      </div>
    </div>
    <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">
      [ ChartPanel renders here — same component as today ]
    </div>
  </div>
);

// ─── THINKING (NEW pane) ─────────────────────────────────────────
const ThinkingPane = () => (
  <div className="bg-zinc-950 border-b border-zinc-800 flex flex-col overflow-hidden" style={{ flex: '25 1 0%' }}>
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
      <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">🧠 Thinking · per-symbol evaluations</span>
      <div className="flex items-center gap-2">
        <Pill color="violet">2 active</Pill>
        <button className="text-[11px] text-zinc-500 hover:text-zinc-300">📍 pin</button>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
      {/* Active eval card */}
      <div className="bg-zinc-900/60 border border-cyan-700/40 rounded-md p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-zinc-100">AAPL</span>
            <Pill color="cyan">evaluating SQUEEZE LONG</Pill>
          </div>
          <span className="text-[10px] text-zinc-500">last update 0.3s ago</span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-[11px] mb-2">
          <div><span className="text-zinc-500">Entry</span> <span className="text-zinc-100 font-mono">$145.20</span></div>
          <div><span className="text-zinc-500">Stop</span> <span className="text-rose-300 font-mono">$144.50 (-0.5%)</span></div>
          <div><span className="text-zinc-500">Target</span> <span className="text-emerald-300 font-mono">$146.65 (R:R 2.07)</span></div>
        </div>
        <div className="text-[11px] mb-2">
          <span className="text-zinc-500">Gates: </span>
          <span className="text-emerald-400">✓ Capital</span> · <span className="text-emerald-400">✓ R:R floor</span> · <span className="text-amber-400">✗ Volume confirm (0.9× vs 1.5×)</span> · <span className="text-amber-400">✗ VWAP reclaim</span> · <span className="text-emerald-400">✓ Direction stable 38s</span> · <span className="text-emerald-400">✓ No cooldown</span>
        </div>
        <div className="text-[11px] mb-2 text-violet-300">
          <span className="text-zinc-500">Watching for: </span>
          5m volume {'>'}1.5× avg AND VWAP reclaim above $145.30
        </div>
        <div className="text-[11px] text-zinc-400 italic">
          "2 of 6 gates open — won't fire until volume confirms. If volume stays thin past 14:30, will downgrade to Tier B."
        </div>
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] text-zinc-500">
          Last 3 verdicts on AAPL/squeeze: REJECT (R:R 1.31) · REJECT (vol confirm) · <span className="text-emerald-400">PASS → +$340 @ 13:01</span>
        </div>
      </div>
      {/* Recent rejection card */}
      <div className="bg-zinc-900/40 border border-zinc-800 rounded-md p-3">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-zinc-100">UPS</span>
            <Pill color="amber">REJECTED 18s ago</Pill>
          </div>
          <span className="text-[10px] text-zinc-500">setup: reclaim long</span>
        </div>
        <div className="text-[11px] text-zinc-400">
          R:R 1.19 below 1.5 floor. Would need stop tightening from $96.50 → $96.85 to qualify.
          <span className="text-violet-300"> Watching for: stop tightening or trend acceleration above $97.50.</span>
        </div>
      </div>
    </div>
  </div>
);

// ─── TIMELINE (merged stream) ────────────────────────────────────
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
      { t: '14:23:04', sym: 'AAPL', text: 'evaluating squeeze long, 4 of 6 gates open, watching volume confirm and VWAP reclaim' },
      { t: '14:22:48', sym: 'UPS', text: 'rejected reclaim — R:R 1.19 below 1.5 floor. Need stop @ $96.85 or target @ $99.20 to qualify' },
      { t: '14:22:31', sym: 'MELI', text: 'short candidate stable 38s, qualifies for next eval cycle, awaiting volume spike confirmation' },
      { t: '14:21:55', sym: 'AAPL', text: 'prior verdict on this setup-symbol pair: PASS → +$340 closed at target 13:01' },
      { t: '14:21:12', sym: 'NVDA', text: 'breakout watch: tier A elevated to active eval, R:R math: entry $218.40 stop $216.20 target $222.80' },
    ],
    decisions: [
      { t: '13:01:22', sym: 'AAPL', text: '✅ PASS → squeeze long, 156 sh @ $145.20, R:R 3.1' },
      { t: '12:48:09', sym: 'TSLA', text: '❌ REJECT → momentum_breakout, R:R 1.42 below floor' },
      { t: '12:31:55', sym: 'COIN', text: '❌ REJECT → reclaim long, direction unstable (flipped 8s ago)' },
    ],
    trades: [
      { t: '13:01:22', sym: 'AAPL', text: '📤 placed 156 sh BUY @ market · bracket OK · trade_id=a1b2c3d4' },
      { t: '13:01:23', sym: 'AAPL', text: '✅ filled 156 sh @ $145.20 · stop OK · target OK' },
      { t: '12:15:08', sym: 'GOOG', text: '✅ closed 50 sh · target hit · +$72' },
    ],
  };
  const list = tab === 'all' ? [...messages.reasoning, ...messages.decisions, ...messages.trades].sort((a, b) => b.t.localeCompare(a.t)) : messages[tab];

  return (
    <div className="bg-zinc-950 flex flex-col overflow-hidden" style={{ flex: '25 1 0%' }}>
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
          <input
            placeholder="🔎 search messages..."
            className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-cyan-700"
          />
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300">
            <option>All symbols</option>
            <option>AAPL</option>
            <option>UPS</option>
          </select>
          <select className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300">
            <option>Live</option>
            <option>1h</option>
            <option>Today</option>
            <option>7d</option>
          </select>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.map((m, i) => (
          <div key={i} className="px-3 py-2 border-b border-zinc-900/50 hover:bg-zinc-900/30">
            <div className="flex items-baseline gap-2">
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

// ─── MANAGING (Open Positions enriched) ──────────────────────────
const ManagingPane = () => (
  <aside className="bg-zinc-950 border-l border-zinc-800 flex flex-col overflow-hidden" style={{ width: 360 }}>
    <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
      <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">🟢 Managing</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-emerald-400 font-mono">+$542.30</span>
        <Pill color="emerald">2 open</Pill>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-2">
      {/* Position 1 — expanded with full reasoning */}
      <div className="bg-zinc-900/60 border border-emerald-700/40 rounded-md">
        <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-zinc-100">AAPL</span>
            <Pill color="emerald">LONG · 156sh</Pill>
          </div>
          <span className="text-xs font-mono text-emerald-400">+$31.20</span>
        </div>
        <div className="px-3 py-2 space-y-2 text-[11px]">
          <div className="flex items-center gap-2">
            <Pill color="emerald">✓ IB synced</Pill>
            <span className="text-zinc-500">156 sh confirmed · age 4m 12s</span>
          </div>
          <div className="space-y-1">
            <div><span className="text-zinc-500">TRAIL:</span> <span className="text-zinc-200 font-mono">$144.50</span> → moves to <span className="text-emerald-300">$145.00</span> if price hits <span className="text-zinc-200">$145.80</span> <span className="text-zinc-500">(in $0.40)</span></div>
            <div><span className="text-zinc-500">SCALE:</span> <span className="text-cyan-300">1/3 @ $146.00</span> pending +$120 · <span className="text-zinc-400">1/3 @ $146.65 target</span> · <span className="text-zinc-500">runner trails</span></div>
            <div><span className="text-zinc-500">KILL:</span> <span className="text-rose-300">5m close {'<'} $144.50</span> = invalidates thesis</div>
          </div>
          <div className="bg-zinc-950/50 border border-violet-800/30 rounded p-2">
            <div className="text-violet-300 font-medium mb-1">🤔 Bot is watching:</div>
            <ul className="space-y-0.5 text-zinc-400">
              <li>• VWAP slope (currently +0.02/min — healthy)</li>
              <li>• Volume next 1m bar {'>'}800 sh</li>
              <li>• Will tighten stop to $145.00 at next higher low</li>
            </ul>
          </div>
          <div className="border-t border-zinc-800 pt-2">
            <div className="text-zinc-500 mb-1">Recent thoughts:</div>
            <div className="text-zinc-400 italic">"3m ago: holding through pullback — structure intact, VWAP support at 145"</div>
            <div className="text-zinc-500 italic">"6m ago: filled @ 145.20, bracket OK"</div>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📊 chart</button>
            <button className="text-[10px] px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded">📜 full log</button>
            <button className="text-[10px] px-2 py-1 bg-rose-900/40 hover:bg-rose-900/60 text-rose-300 rounded ml-auto">🛑 close</button>
          </div>
        </div>
      </div>
      {/* Position 2 — collapsed summary */}
      <div className="bg-zinc-900/40 border border-zinc-800 rounded-md hover:border-zinc-700 cursor-pointer">
        <div className="px-3 py-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-zinc-100">NVDA</span>
            <Pill color="emerald">LONG · 24sh</Pill>
          </div>
          <span className="text-xs font-mono text-emerald-400">+$511.10</span>
        </div>
        <div className="px-3 pb-2 text-[11px] text-zinc-500 flex items-center gap-2">
          <span>trail at $214.80</span>
          <span>·</span>
          <span className="text-violet-300">watching vol slowdown</span>
        </div>
      </div>
    </div>
  </aside>
);

// ─── EXECUTION STRIP (collapsed bottom bar) ─────────────────────
const ExecutionStrip = () => (
  <div className="bg-zinc-950 border-t border-zinc-800 px-4 py-1.5 flex items-center justify-between text-xs">
    <div className="flex items-center gap-4 text-zinc-400">
      <span className="flex items-center gap-1.5">📦 <span className="text-zinc-300 font-medium">3</span> orders pending</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5">✅ <span className="text-zinc-300 font-medium">12</span> fills today</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5">✓ <span className="text-zinc-300 font-medium">8</span> closed</span>
      <span className="text-zinc-700">·</span>
      <span className="flex items-center gap-1.5 text-emerald-400">⚠ <span className="font-medium">0</span> errors</span>
    </div>
    <button className="text-[11px] text-zinc-500 hover:text-zinc-300">click to expand ↑</button>
  </div>
);

// ─── ROOT ────────────────────────────────────────────────────────
export const V6LayoutPreview = () => (
  <div className="min-h-screen bg-zinc-900 text-zinc-100 flex flex-col">
    {/* Header strip */}
    <div className="bg-zinc-950 border-b border-zinc-800 px-4 py-2 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-sm font-bold text-cyan-300">SentCom V6 — Layout Preview</span>
        <Pill color="amber">mockup · static dummy data</Pill>
      </div>
      <div className="flex items-center gap-3 text-xs text-zinc-500">
        <span>Built per operator spec — 4 panes + status strip</span>
        <a href="?" className="text-violet-400 hover:underline">← back to V5</a>
      </div>
    </div>
    {/* Main 3-column row */}
    <div className="flex-1 flex overflow-hidden">
      <WatchingPane />
      <div className="flex-1 flex flex-col overflow-hidden">
        <ChartPlaceholder />
        <ThinkingPane />
        <TimelinePane />
      </div>
      <ManagingPane />
    </div>
    <ExecutionStrip />
  </div>
);

export default V6LayoutPreview;
