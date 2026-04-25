/**
 * AuraMockupPreview — concept exploration page.
 *
 * NOT routed in the sidebar. Reachable only by appending
 * `?preview=aura` to the URL (App.js detects this and renders this
 * component instead of the normal page).
 *
 * Goal: visualize the AURA-aesthetic ideas (neon glow, AI Confidence
 * gauge, Trade Execution Timeline, Decision Feed restyle, Brain hero)
 * fused with the existing V5 dense-grid daily-driver layout — without
 * touching any production component.
 *
 * All data is static / synthetic. No API calls, no side-effects, no
 * shared state. Deletable in one rm.
 */

import React, { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// Tiny self-contained sub-components (no shared imports)
// ---------------------------------------------------------------------------

const NeonChip = ({ tone = 'cyan', children, dot = true, pulse = false }) => {
  const palette = {
    cyan: 'border-cyan-500/40 text-cyan-300 bg-cyan-500/10',
    violet: 'border-violet-500/40 text-violet-300 bg-violet-500/10',
    emerald: 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10',
    amber: 'border-amber-500/40 text-amber-300 bg-amber-500/10',
    rose: 'border-rose-500/40 text-rose-300 bg-rose-500/10',
    zinc: 'border-zinc-700 text-zinc-400 bg-zinc-900/40',
  };
  const dotPalette = {
    cyan: 'bg-cyan-400', violet: 'bg-violet-400', emerald: 'bg-emerald-400',
    amber: 'bg-amber-400', rose: 'bg-rose-400', zinc: 'bg-zinc-500',
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-mono uppercase tracking-wider ${palette[tone]}`}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${dotPalette[tone]} ${pulse ? 'animate-pulse' : ''}`} />}
      {children}
    </span>
  );
};

const GlassCard = ({ children, glow = 'cyan', className = '', title = null, action = null }) => {
  const glowMap = {
    cyan: 'shadow-[0_0_24px_-8px_rgba(34,211,238,0.45)]',
    violet: 'shadow-[0_0_24px_-8px_rgba(139,92,246,0.45)]',
    emerald: 'shadow-[0_0_24px_-8px_rgba(16,185,129,0.4)]',
    none: '',
  };
  return (
    <div className={`relative rounded-xl border border-zinc-800/80 bg-zinc-950/60 backdrop-blur-md p-3 ${glowMap[glow]} ${className}`}>
      {title && (
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[10px] font-mono uppercase tracking-[0.18em] text-zinc-500">{title}</h3>
          {action}
        </div>
      )}
      {children}
    </div>
  );
};

/** Half-circle SVG gauge — used for AI Confidence + Risk Control */
const ArcGauge = ({ value = 88, label = 'Confidence', tone = 'cyan', sublabel = null }) => {
  const r = 60;
  const c = Math.PI * r; // half-circle circumference
  const dash = (value / 100) * c;
  const stops = {
    cyan: ['#22d3ee', '#a78bfa'],
    emerald: ['#10b981', '#6ee7b7'],
    violet: ['#8b5cf6', '#22d3ee'],
  }[tone] || ['#22d3ee', '#a78bfa'];
  const gid = `g-${tone}-${label.replace(/\s+/g, '')}`;
  return (
    <div className="relative flex flex-col items-center justify-center select-none">
      <svg width="160" height="92" viewBox="0 0 160 92">
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
        </defs>
        <path d="M 20 80 A 60 60 0 0 1 140 80" fill="none" stroke="rgb(39,39,42)" strokeWidth="10" strokeLinecap="round" />
        <path
          d="M 20 80 A 60 60 0 0 1 140 80"
          fill="none"
          stroke={`url(#${gid})`}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          style={{ filter: `drop-shadow(0 0 6px ${stops[0]})` }}
        />
      </svg>
      <div className="absolute bottom-3 flex flex-col items-center">
        <div className="text-[28px] font-bold text-zinc-100 leading-none">{value}<span className="text-base text-zinc-500">%</span></div>
        <div className="text-[9px] font-mono uppercase tracking-wider text-zinc-500 mt-0.5">{sublabel || label}</div>
      </div>
    </div>
  );
};

/** Auto-scrolling decision feed — purely visual, synthetic data. */
const DecisionFeed = () => {
  const lines = [
    { t: '10:32:14', tone: 'cyan',    text: 'ANALYZING MARKET TRENDS · QQQ regime=trending' },
    { t: '10:32:09', tone: 'emerald', text: 'EXECUTING BUY ORDER · NVDA · 200 sh @ 520.40' },
    { t: '10:32:01', tone: 'violet',  text: 'SELF-LEARNING EPOCH 142 · loss=0.0231 (-3%)' },
    { t: '10:31:48', tone: 'cyan',    text: 'RISK CHECK · GREEN · daily_R=+2.4 · stop_breach=0' },
    { t: '10:31:37', tone: 'amber',   text: 'GATE FILTERED · MARA · score=58 (B-tier, half-size)' },
    { t: '10:31:21', tone: 'emerald', text: 'CLOSE · LABD · +1.8R · reason=trail_breach' },
    { t: '10:31:04', tone: 'violet',  text: 'STRATEGY UPDATE · sector_rotation=tech_leading' },
    { t: '10:30:51', tone: 'cyan',    text: 'PATTERN RECOGNIZED · AAPL · 5min ORB long' },
    { t: '10:30:33', tone: 'rose',    text: 'VETO · drift detected · INTC · model retrain queued' },
    { t: '10:30:19', tone: 'cyan',    text: 'SENTIMENT SHIFT · bullish · vol=high · sec=tech' },
  ];
  const [tick, setTick] = useState(0);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 1100); return () => clearInterval(id); }, []);
  const rotated = [...lines.slice(tick % lines.length), ...lines.slice(0, tick % lines.length)];
  const palette = { cyan: 'text-cyan-300', emerald: 'text-emerald-300', violet: 'text-violet-300', amber: 'text-amber-300', rose: 'text-rose-300' };
  return (
    <div className="font-mono text-[10px] space-y-1 overflow-hidden h-[180px]">
      {rotated.slice(0, 9).map((l, i) => (
        <div key={`${tick}-${i}`} className={`flex gap-2 ${palette[l.tone]}`} style={{ opacity: 1 - i * 0.07, transform: `translateX(${i === 0 ? -2 : 0}px)`, transition: 'opacity 800ms, transform 800ms' }}>
          <span className="text-zinc-600 shrink-0">{l.t}</span>
          <span className="truncate">{l.text}</span>
        </div>
      ))}
    </div>
  );
};

/** Trade Execution Timeline — connects events with a vertical line. */
const TradeTimeline = () => {
  const events = [
    { time: '10:31 AM', type: 'BUY',   sym: 'NVDA', px: '520.40', tone: 'emerald' },
    { time: '10:28 AM', type: 'SELL',  sym: 'AAPL', px: '185.50', tone: 'rose' },
    { time: '10:25 AM', type: 'SCAN',  sym: 'Retail Sector', px: null, tone: 'zinc' },
    { time: '10:15 AM', type: 'REBAL', sym: 'Portfolio',    px: null, tone: 'violet' },
  ];
  const dotMap = { emerald: 'bg-emerald-400 shadow-[0_0_8px_2px_rgba(16,185,129,0.6)]', rose: 'bg-rose-400 shadow-[0_0_8px_2px_rgba(244,63,94,0.6)]', zinc: 'bg-zinc-500', violet: 'bg-violet-400 shadow-[0_0_8px_2px_rgba(139,92,246,0.6)]' };
  return (
    <div className="relative pl-4">
      <div className="absolute left-1.5 top-2 bottom-2 w-px bg-gradient-to-b from-cyan-500/60 via-violet-500/40 to-zinc-700" />
      <div className="space-y-2.5">
        {events.map((e, i) => (
          <div key={i} className="relative flex items-baseline gap-2 text-[11px]">
            <span className={`absolute -left-[14px] top-1 w-2.5 h-2.5 rounded-full ${dotMap[e.tone]}`} />
            <span className={`font-mono font-bold w-12 ${e.tone === 'emerald' ? 'text-emerald-300' : e.tone === 'rose' ? 'text-rose-300' : e.tone === 'violet' ? 'text-violet-300' : 'text-zinc-400'}`}>{e.type}</span>
            <span className="text-zinc-200 truncate flex-1">{e.sym}{e.px ? ` @ ${e.px}` : ''}</span>
            <span className="font-mono text-[9px] text-zinc-500">{e.time}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

/** AURA wordmark — animated gradient text */
const AuraWordmark = ({ size = 'md' }) => {
  const sz = size === 'lg' ? 'text-3xl' : size === 'sm' ? 'text-base' : 'text-xl';
  return (
    <div className="inline-flex items-center gap-2">
      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-500 to-violet-500 flex items-center justify-center font-bold text-zinc-950 shadow-[0_0_16px_rgba(34,211,238,0.5)]">A</div>
      <div className="flex flex-col leading-none">
        <span className={`${sz} font-bold tracking-wide bg-gradient-to-r from-cyan-300 via-violet-300 to-cyan-300 bg-clip-text text-transparent`} style={{ backgroundSize: '200% auto', animation: 'auraShimmer 4s linear infinite' }}>AURA</span>
        <span className="text-[8px] font-mono text-zinc-500 uppercase tracking-[0.25em] mt-0.5">Autonomous Intelligence</span>
      </div>
    </div>
  );
};

/** Brain hero card — uses CSS-only "neural" effect (no image / no 3D dependency) */
const BrainHero = () => {
  return (
    <div className="relative aspect-[4/3] rounded-2xl border border-zinc-800/80 bg-zinc-950/40 overflow-hidden flex items-center justify-center">
      {/* Glow gradient backdrop */}
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at center, rgba(139,92,246,0.18) 0%, rgba(34,211,238,0.10) 35%, transparent 70%)' }} />
      {/* Animated SVG "neural" rays */}
      <svg className="absolute inset-0 w-full h-full opacity-40" viewBox="0 0 400 300">
        <defs>
          <radialGradient id="neuralGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="1" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
        </defs>
        {Array.from({ length: 14 }).map((_, i) => {
          const angle = (i / 14) * Math.PI * 2;
          const x = 200 + Math.cos(angle) * 180;
          const y = 150 + Math.sin(angle) * 130;
          return (
            <line
              key={i}
              x1="200" y1="150" x2={x} y2={y}
              stroke={i % 2 === 0 ? '#22d3ee' : '#a78bfa'}
              strokeWidth="0.8"
              strokeOpacity="0.5"
              style={{ animation: `neuralPulse 3s ease-in-out ${i * 0.18}s infinite alternate` }}
            />
          );
        })}
        {Array.from({ length: 30 }).map((_, i) => (
          <circle
            key={`s-${i}`}
            cx={Math.random() * 400}
            cy={Math.random() * 300}
            r={Math.random() * 1.4 + 0.4}
            fill={i % 3 === 0 ? '#a78bfa' : '#22d3ee'}
            opacity={Math.random() * 0.7 + 0.3}
            style={{ animation: `starTwinkle ${2 + Math.random() * 3}s ease-in-out ${Math.random() * 2}s infinite alternate` }}
          />
        ))}
      </svg>
      {/* Central "brain" — concentric blurred rings */}
      <div className="relative w-48 h-48">
        <div className="absolute inset-0 rounded-full bg-gradient-to-br from-cyan-500/30 via-violet-500/30 to-cyan-500/20 blur-2xl" />
        <div className="absolute inset-4 rounded-full border-2 border-cyan-400/60" style={{ animation: 'brainPulse 4s ease-in-out infinite' }} />
        <div className="absolute inset-8 rounded-full border border-violet-400/40" style={{ animation: 'brainPulse 4s ease-in-out 0.6s infinite' }} />
        <div className="absolute inset-12 rounded-full bg-gradient-to-br from-cyan-300/30 to-violet-400/30 backdrop-blur-md flex items-center justify-center">
          <div className="text-zinc-100 text-3xl font-bold">AI</div>
        </div>
      </div>
      {/* Floating thought bubbles */}
      <div className="absolute top-6 left-6"><NeonChip tone="cyan">Analyze Market Data</NeonChip></div>
      <div className="absolute top-10 right-8"><NeonChip tone="emerald">Risk Check: Green</NeonChip></div>
      <div className="absolute bottom-12 left-10"><NeonChip tone="violet">Pattern Recognized</NeonChip></div>
      <div className="absolute bottom-6 right-6"><NeonChip tone="cyan" pulse>Execute: BUY NVDA</NeonChip></div>
      <div className="absolute top-1/2 left-4"><NeonChip tone="violet">Strategy Update</NeonChip></div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Three concept tiles
// ---------------------------------------------------------------------------

const Concept1_FullAura = () => (
  <section className="space-y-3">
    <header className="flex items-center justify-between">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-zinc-500">Concept 1 · Full AURA showroom (landing / demo only)</h2>
      <NeonChip tone="amber">Showroom · not for daily use</NeonChip>
    </header>
    <div className="grid grid-cols-12 gap-3">
      <div className="col-span-3 space-y-3">
        <GlassCard glow="cyan" title="Portfolio Performance" action={<NeonChip tone="emerald" dot={false}>+1.28%</NeonChip>}>
          <div className="text-2xl font-bold text-zinc-100">$2,450,780</div>
          <svg viewBox="0 0 200 60" className="w-full mt-2"><polyline fill="none" stroke="url(#p1)" strokeWidth="2" points="0,40 20,38 40,42 60,30 80,32 100,22 120,28 140,18 160,20 180,12 200,8" /><defs><linearGradient id="p1"><stop offset="0%" stopColor="#22d3ee" /><stop offset="100%" stopColor="#a78bfa" /></linearGradient></defs></svg>
          <div className="text-[9px] font-mono text-zinc-600 mt-1 flex justify-between"><span>24M</span><span>1AM</span><span>12AM</span><span>3AM</span><span>6PM</span></div>
        </GlassCard>
        <GlassCard glow="cyan" title="Watchlist">
          {[['AAPL', '+1.1%', 'emerald'], ['NVDA', '+2.5%', 'emerald'], ['MSFT', '+0.9%', 'emerald'], ['TSLA', '-0.3%', 'rose']].map(([s, p, t]) => (
            <div key={s} className="flex justify-between text-xs py-1 border-b border-zinc-900 last:border-0"><span className="font-bold text-zinc-300">{s}</span><span className={`font-mono ${t === 'emerald' ? 'text-emerald-300' : 'text-rose-300'}`}>{p}</span></div>
          ))}
        </GlassCard>
      </div>
      <div className="col-span-6"><BrainHero /></div>
      <div className="col-span-3 space-y-3">
        <GlassCard glow="violet" title="Current Strategy">
          <div className="text-lg font-bold text-zinc-100">Alpha Growth</div>
          <div className="flex gap-1.5 mt-2"><NeonChip tone="emerald">Active</NeonChip><NeonChip tone="zinc" dot={false}>Automated</NeonChip></div>
        </GlassCard>
        <GlassCard glow="emerald" title="Risk Control"><ArcGauge value={92} tone="emerald" sublabel="Risk Level" /><div className="text-[10px] text-zinc-500 mt-1 text-center">Max Drawdown: <span className="text-emerald-300 font-mono">3.1%</span></div></GlassCard>
        <GlassCard glow="cyan" title="AI Confidence"><ArcGauge value={88} tone="cyan" sublabel="High Confidence" /></GlassCard>
      </div>
      <div className="col-span-4"><GlassCard glow="cyan" title="Trade Execution Timeline"><TradeTimeline /></GlassCard></div>
      <div className="col-span-5"><GlassCard glow="violet" title="Live Decision Feed"><DecisionFeed /></GlassCard></div>
      <div className="col-span-3"><GlassCard glow="emerald" title="System Status"><div className="space-y-1 text-[11px]">{[['AI Performance', '98%'], ['Data Sources', '16 Active'], ['Uptime', '100%']].map(([k, v]) => (<div key={k} className="flex justify-between"><span className="text-zinc-400">{k}</span><span className="font-mono text-emerald-300">{v}</span></div>))}</div></GlassCard></div>
    </div>
  </section>
);

const Concept2_HybridV5 = () => (
  <section className="space-y-3">
    <header className="flex items-center justify-between">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-zinc-500">Concept 2 · Hybrid V5 + AURA accents (recommended daily driver)</h2>
      <NeonChip tone="emerald">Production-ready · keeps density</NeonChip>
    </header>
    {/* Top bar that mimics existing PipelineHUDV5 with new gauges injected */}
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 flex items-center gap-4">
      <AuraWordmark size="sm" />
      <div className="flex-1 grid grid-cols-7 gap-3 text-[11px]">
        {[['Scan', '14', 'cyan'], ['Eval', '6', 'violet'], ['Order', '2', 'emerald'], ['Manage', '4', 'cyan'], ['Close', '11', 'zinc'], ['Latency', '1.2s', 'emerald'], ['Phase', 'RTH', 'cyan']].map(([k, v, t]) => (
          <div key={k} className="flex flex-col">
            <span className="text-[9px] font-mono text-zinc-500 uppercase tracking-wider">{k}</span>
            <span className={`font-bold text-sm ${t === 'cyan' ? 'text-cyan-300' : t === 'violet' ? 'text-violet-300' : t === 'emerald' ? 'text-emerald-300' : 'text-zinc-300'}`}>{v}</span>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <div className="text-center">
          <div className="text-[9px] font-mono text-zinc-500 uppercase">Confidence</div>
          <div className="text-cyan-300 font-bold text-lg leading-none">88<span className="text-[10px] text-zinc-500">%</span></div>
        </div>
        <div className="text-center">
          <div className="text-[9px] font-mono text-zinc-500 uppercase">Risk OK</div>
          <div className="text-emerald-300 font-bold text-lg leading-none">92<span className="text-[10px] text-zinc-500">%</span></div>
        </div>
        <NeonChip tone="emerald" pulse>LIVE · 3s</NeonChip>
        <NeonChip tone="cyan" dot={false}>⌘K</NeonChip>
      </div>
    </div>
    {/* Three-column V5 grid (scanner / chart / right rail) — keeping existing layout but with neon edges */}
    <div className="grid grid-cols-12 gap-3 h-[420px]">
      <GlassCard glow="cyan" className="col-span-3 overflow-hidden" title="Scanner · top 10">
        <div className="space-y-1.5">
          {[['AAPL', 92, 'A', '+2.1%', 'emerald'], ['NVDA', 87, 'A', '+1.4%', 'emerald'], ['META', 79, 'B', '+0.6%', 'emerald'], ['MARA', 58, 'C', '-0.3%', 'amber'], ['INTC', 41, 'D', '-1.0%', 'rose']].map(([s, sc, t, ch, tn]) => (
            <div key={s} className="flex items-center gap-2 p-1.5 rounded border border-zinc-900 bg-zinc-900/30 hover:border-cyan-500/40 transition-colors">
              <span className="font-bold text-zinc-200 text-xs w-12">{s}</span>
              <NeonChip tone={sc >= 80 ? 'emerald' : sc >= 60 ? 'cyan' : sc >= 40 ? 'amber' : 'rose'} dot={false}>{t}·{sc}</NeonChip>
              <span className={`ml-auto font-mono text-[10px] ${tn === 'emerald' ? 'text-emerald-300' : tn === 'rose' ? 'text-rose-300' : 'text-amber-300'}`}>{ch}</span>
            </div>
          ))}
        </div>
      </GlassCard>
      <GlassCard glow="cyan" className="col-span-6 flex flex-col" title="NVDA · 5min · IB">
        {/* Faux candle chart */}
        <svg viewBox="0 0 600 240" className="w-full flex-1">
          <defs>
            <linearGradient id="chartGlow" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity="0.4" /><stop offset="100%" stopColor="#22d3ee" stopOpacity="0" /></linearGradient>
          </defs>
          <path d="M0,180 L40,160 L80,170 L120,140 L160,150 L200,120 L240,130 L280,90 L320,100 L360,70 L400,80 L440,60 L480,70 L520,40 L560,50 L600,30 L600,240 L0,240 Z" fill="url(#chartGlow)" />
          <polyline fill="none" stroke="#22d3ee" strokeWidth="1.5" points="0,180 40,160 80,170 120,140 160,150 200,120 240,130 280,90 320,100 360,70 400,80 440,60 480,70 520,40 560,50 600,30" style={{ filter: 'drop-shadow(0 0 4px #22d3ee)' }} />
          {/* VWAP line */}
          <polyline fill="none" stroke="#a78bfa" strokeWidth="1" strokeDasharray="3,3" points="0,140 600,90" opacity="0.7" />
        </svg>
        <div className="flex justify-between text-[10px] font-mono text-zinc-500 mt-1"><span>09:30</span><span>10:00</span><span>10:30</span><span>11:00</span><span>11:30</span><span>12:00</span></div>
      </GlassCard>
      <div className="col-span-3 space-y-3 flex flex-col">
        <GlassCard glow="violet" className="flex-1" title="Briefings"><div className="space-y-1 text-[10px]">{[['08:30', 'Morning Prep', 'PASSED', 'zinc'], ['12:00', 'Mid-Day Recap', 'NEW', 'emerald'], ['15:00', 'Power Hour', '15:00', 'amber'], ['16:00', 'Close Recap', '16:00', 'zinc']].map(([t, n, s, tone]) => (<div key={n} className="flex items-center justify-between p-1.5 rounded border border-zinc-900"><div><div className="text-zinc-300 text-xs">{n}</div><div className="text-[9px] font-mono text-zinc-600">{t} ET</div></div><NeonChip tone={tone} dot={false}>{s}</NeonChip></div>))}</div></GlassCard>
        <GlassCard glow="cyan" title="Live Decision Feed" className="flex-1"><DecisionFeed /></GlassCard>
      </div>
    </div>
    {/* Bottom row */}
    <div className="grid grid-cols-12 gap-3">
      <GlassCard glow="emerald" className="col-span-4" title="Open Positions · 4">
        {[['NVDA', 'LONG', 200, '+2.4R', 'emerald'], ['AAPL', 'LONG', 100, '+0.6R', 'emerald'], ['LABD', 'SHORT', 300, '-0.4R', 'rose'], ['META', 'LONG', 50, '+1.1R', 'emerald']].map(([s, side, qty, r, t]) => (
          <div key={s} className="flex items-center gap-2 py-1 border-b border-zinc-900 text-[11px]">
            <span className="font-bold text-zinc-200 w-12">{s}</span><NeonChip tone={side === 'LONG' ? 'emerald' : 'rose'} dot={false}>{side}</NeonChip><span className="text-zinc-500 font-mono">{qty}</span>
            <span className={`ml-auto font-mono font-bold ${t === 'emerald' ? 'text-emerald-300' : 'text-rose-300'}`}>{r}</span>
          </div>
        ))}
      </GlassCard>
      <GlassCard glow="cyan" className="col-span-4" title="Trade Execution Timeline"><TradeTimeline /></GlassCard>
      <GlassCard glow="violet" className="col-span-4" title="Backfill Readiness">
        <div className="flex items-center gap-3 mb-2"><span className="w-3 h-3 rounded-full bg-emerald-400 shadow-[0_0_10px_2px_rgba(16,185,129,0.7)]" /><span className="text-emerald-300 font-bold text-sm uppercase tracking-wider">Ready</span></div>
        <div className="grid grid-cols-2 gap-1.5 text-[9px] font-mono">
          {['Queue Drained', 'Critical Fresh', 'Overall 98.7%', 'No Duplicates', 'Density 94%'].map((c, i) => (
            <div key={c} className={`px-1.5 py-1 rounded border ${i === 2 || i === 4 ? 'border-amber-500/30 text-amber-300 bg-amber-500/5' : 'border-emerald-500/30 text-emerald-300 bg-emerald-500/5'}`}>{c}</div>
          ))}
        </div>
      </GlassCard>
    </div>
  </section>
);

const Concept3_DropIns = () => (
  <section className="space-y-3">
    <header className="flex items-center justify-between">
      <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-zinc-500">Concept 3 · Drop-in components (steal-list shipped as widgets)</h2>
      <NeonChip tone="cyan">Standalone · zero rewrite needed</NeonChip>
    </header>
    <div className="grid grid-cols-12 gap-3">
      <GlassCard glow="cyan" className="col-span-3 flex flex-col items-center" title="AI Confidence Meter"><ArcGauge value={88} tone="cyan" sublabel="High Confidence" /><div className="text-[10px] text-zinc-500 mt-1 text-center font-mono">across 14 active models · last update 12s ago</div></GlassCard>
      <GlassCard glow="emerald" className="col-span-3 flex flex-col items-center" title="Risk Control Gauge"><ArcGauge value={92} tone="emerald" sublabel="Risk OK" /><div className="text-[10px] text-zinc-500 mt-1 text-center font-mono">DD 3.1% · daily R +2.4 · stops 0/4</div></GlassCard>
      <GlassCard glow="violet" className="col-span-3 flex flex-col items-center" title="Backfill Readiness"><ArcGauge value={97} tone="violet" sublabel="Ready" /><div className="text-[10px] text-zinc-500 mt-1 text-center font-mono">5 checks green · queue 0/0</div></GlassCard>
      <GlassCard glow="cyan" className="col-span-3" title="AURA Wordmark · header style"><div className="flex flex-col items-center justify-center h-[140px] gap-3"><AuraWordmark size="lg" /><div className="text-[9px] font-mono text-zinc-600 text-center">Could replace the simple "SentCom" mark in the top-left corner.</div></div></GlassCard>
      <GlassCard glow="cyan" className="col-span-6" title="Live Decision Feed"><DecisionFeed /></GlassCard>
      <GlassCard glow="violet" className="col-span-6" title="Trade Execution Timeline"><TradeTimeline /></GlassCard>
    </div>
  </section>
);

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

export const AuraMockupPreview = () => {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-200 p-6 space-y-8" data-testid="aura-mockup-page">
      <style>{`
        @keyframes auraShimmer { 0% { background-position: 0% center; } 100% { background-position: 200% center; } }
        @keyframes neuralPulse { from { stroke-opacity: 0.15; } to { stroke-opacity: 0.85; } }
        @keyframes starTwinkle { from { opacity: 0.3; } to { opacity: 1; } }
        @keyframes brainPulse { 0%, 100% { transform: scale(1); opacity: 0.6; } 50% { transform: scale(1.08); opacity: 1; } }
      `}</style>
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-zinc-100">SentCom · AURA Concept Preview</h1>
          <p className="text-sm text-zinc-500 mt-1">Three concept variations exploring AURA aesthetic ideas merged with our existing V5 architecture. Static mockups · zero side-effects · safely deletable.</p>
        </div>
        <div className="text-right text-[10px] font-mono text-zinc-600">
          <div>Reachable via <span className="text-cyan-300">?preview=aura</span></div>
          <div>Built with existing stack only · no new deps</div>
        </div>
      </header>
      <Concept1_FullAura />
      <hr className="border-zinc-800" />
      <Concept2_HybridV5 />
      <hr className="border-zinc-800" />
      <Concept3_DropIns />
      <footer className="pt-6 text-[10px] font-mono text-zinc-600 text-center border-t border-zinc-900">
        Mockup file: <span className="text-zinc-400">/app/frontend/src/pages/AuraMockupPreview.jsx</span> · delete the file + the App.js URL-param check to remove. No production code paths touched.
      </footer>
    </div>
  );
};

export default AuraMockupPreview;
