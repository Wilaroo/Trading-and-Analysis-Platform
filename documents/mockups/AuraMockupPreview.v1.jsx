/**
 * AuraMockupPreview — unified concept page.
 *
 * Single cohesive showcase combining the steal-list elements from the
 * three earlier concept tiles into ONE mockup with no overlap:
 *
 *   1. Top HUD strip (from old Concept 2) — AURA wordmark replacing the
 *      simple SentCom mark, full Pipeline HUD metrics, AI Confidence
 *      and Risk Control inline readouts, ⌘K hint.
 *
 *   2. Center hero — anatomically-recognizable brain SVG (two
 *      hemispheres with longitudinal fissure, gyri/sulci ridges,
 *      brain stem), ringed with floating thought bubbles. Neural
 *      firing pulses traverse the cortex.
 *
 *   3. Production-ready grid (from old Concept 2) — Scanner top-10
 *      with gate tiers · neon chart with VWAP · Briefings + Live
 *      Decision Feed in the right rail · Open Positions with
 *      R-multiples · Trade Execution Timeline · Backfill Readiness
 *      card with all 5 sub-checks.
 *
 * NOT routed in the sidebar. Reachable only via `?preview=aura`.
 * All data is static / synthetic. Zero side-effects. Deletable in one rm.
 */

import React, { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// Self-contained sub-components (no shared imports outside React)
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

/** Half-circle SVG gauge — used for AI Confidence + Risk Control + Readiness */
const ArcGauge = ({ value = 88, label = 'Confidence', tone = 'cyan', sublabel = null, size = 'md' }) => {
  const dims = size === 'sm'
    ? { w: 110, h: 64, cx: 55, cy: 55, r: 42, sw: 7, fontTop: '20px', fontBottom: '8px', bottom: 6 }
    : { w: 160, h: 92, cx: 80, cy: 80, r: 60, sw: 10, fontTop: '28px', fontBottom: '9px', bottom: 12 };
  const c = Math.PI * dims.r;
  const dash = (value / 100) * c;
  const stops = {
    cyan: ['#22d3ee', '#a78bfa'],
    emerald: ['#10b981', '#6ee7b7'],
    violet: ['#8b5cf6', '#22d3ee'],
  }[tone] || ['#22d3ee', '#a78bfa'];
  const gid = `g-${tone}-${label.replace(/\s+/g, '')}-${size}`;
  const arc = `M ${dims.cx - dims.r} ${dims.cy} A ${dims.r} ${dims.r} 0 0 1 ${dims.cx + dims.r} ${dims.cy}`;
  return (
    <div className="relative flex flex-col items-center justify-center select-none">
      <svg width={dims.w} height={dims.h} viewBox={`0 0 ${dims.w} ${dims.h}`}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
        </defs>
        <path d={arc} fill="none" stroke="rgb(39,39,42)" strokeWidth={dims.sw} strokeLinecap="round" />
        <path
          d={arc}
          fill="none"
          stroke={`url(#${gid})`}
          strokeWidth={dims.sw}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          style={{ filter: `drop-shadow(0 0 6px ${stops[0]})` }}
        />
      </svg>
      <div className="absolute flex flex-col items-center" style={{ bottom: dims.bottom }}>
        <div className="font-bold text-zinc-100 leading-none" style={{ fontSize: dims.fontTop }}>{value}<span className="text-base text-zinc-500">%</span></div>
        <div className="font-mono uppercase tracking-wider text-zinc-500 mt-0.5" style={{ fontSize: dims.fontBottom }}>{sublabel || label}</div>
      </div>
    </div>
  );
};

/** Auto-scrolling decision feed — synthetic data. */
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
    <div className="font-mono text-[10px] space-y-1 overflow-hidden h-[200px]">
      {rotated.slice(0, 10).map((l, i) => (
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

/**
 * AnatomicalBrain — recognizable two-hemisphere brain SVG.
 *
 * Built from organic SVG paths (no GLTF, no three.js — purely native).
 * Layers (back → front):
 *   1. Outer glow halo (radial gradient)
 *   2. Whole-brain fill with subtle gradient mimicking cortex
 *   3. Multiple gyri (the curved cortex ridges) using bezier paths
 *   4. Longitudinal fissure (vertical separation between hemispheres)
 *   5. Brain stem nub at bottom
 *   6. Animated neural firing pulses traversing random gyri
 *   7. Pulsing core dots simulating active brain regions
 *
 * Anatomically inspired (not medically accurate) — looks like a brain
 * at a glance while staying lightweight (~6KB SVG).
 */
const AnatomicalBrain = () => {
  // Pre-defined gyri paths (cortex ridges). Drawn by hand to suggest
  // the bumpy brain surface across the two hemispheres.
  const leftGyri = [
    'M 95,90 Q 130,80 165,95',
    'M 80,120 Q 120,108 165,125',
    'M 70,155 Q 115,145 165,160',
    'M 70,190 Q 115,180 165,195',
    'M 80,225 Q 120,215 160,230',
    'M 100,255 Q 130,250 160,260',
  ];
  const rightGyri = [
    'M 235,95 Q 270,80 305,90',
    'M 235,125 Q 280,108 320,120',
    'M 235,160 Q 285,145 330,155',
    'M 235,195 Q 285,180 330,190',
    'M 240,230 Q 280,215 320,225',
    'M 240,260 Q 270,250 300,255',
  ];
  // Active firing nodes — pulse at staggered intervals
  const firingNodes = [
    { cx: 130, cy: 105 }, { cx: 270, cy: 105 },
    { cx: 105, cy: 165 }, { cx: 295, cy: 165 },
    { cx: 145, cy: 215 }, { cx: 255, cy: 215 },
    { cx: 200, cy: 145 }, { cx: 200, cy: 200 },
  ];

  return (
    <svg viewBox="0 0 400 320" className="w-full h-full">
      <defs>
        {/* Outer halo */}
        <radialGradient id="brainHalo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#a78bfa" stopOpacity="0.35" />
          <stop offset="40%" stopColor="#22d3ee" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
        </radialGradient>
        {/* Cortex fill — pinkish-violet with cyan rim */}
        <radialGradient id="cortexFill" cx="50%" cy="40%" r="65%">
          <stop offset="0%" stopColor="#581c87" stopOpacity="0.95" />
          <stop offset="50%" stopColor="#312e81" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#0c4a6e" stopOpacity="0.9" />
        </radialGradient>
        {/* Gyri stroke gradient */}
        <linearGradient id="gyriStroke" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#22d3ee" />
          <stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>
        {/* Glow filter */}
        <filter id="brainGlow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* (1) Halo */}
      <rect x="0" y="0" width="400" height="320" fill="url(#brainHalo)" />

      {/* Stars / particles in background */}
      {Array.from({ length: 25 }).map((_, i) => (
        <circle
          key={`s-${i}`}
          cx={Math.random() * 400}
          cy={Math.random() * 320}
          r={Math.random() * 1.2 + 0.3}
          fill={i % 3 === 0 ? '#a78bfa' : '#22d3ee'}
          opacity={Math.random() * 0.5 + 0.3}
          style={{ animation: `starTwinkle ${2 + Math.random() * 3}s ease-in-out ${Math.random() * 2}s infinite alternate` }}
        />
      ))}

      {/* (2) Whole-brain fill — two overlapping hemispherical paths.
            Anatomical references: frontal lobe (top-front), temporal lobe
            (lower bulge), parietal (top-back), occipital (back). */}
      <g filter="url(#brainGlow)">
        {/* Left hemisphere */}
        <path
          d="M 200,55
             C 165,50 125,55 95,75
             C 65,95 55,135 60,175
             C 60,215 75,250 110,275
             C 145,295 180,290 200,280
             L 200,55 Z"
          fill="url(#cortexFill)"
          stroke="#22d3ee"
          strokeWidth="1.5"
          strokeOpacity="0.85"
        />
        {/* Right hemisphere */}
        <path
          d="M 200,55
             C 235,50 275,55 305,75
             C 335,95 345,135 340,175
             C 340,215 325,250 290,275
             C 255,295 220,290 200,280
             L 200,55 Z"
          fill="url(#cortexFill)"
          stroke="#22d3ee"
          strokeWidth="1.5"
          strokeOpacity="0.85"
        />
        {/* Brain stem nub at bottom */}
        <path
          d="M 175,278
             C 180,295 220,295 225,278
             L 220,265
             L 180,265 Z"
          fill="url(#cortexFill)"
          stroke="#22d3ee"
          strokeWidth="1.2"
          strokeOpacity="0.8"
        />
      </g>

      {/* (3) Gyri ridges — curve lines suggesting cortex folds */}
      <g style={{ animation: 'gyriShimmer 5s ease-in-out infinite' }}>
        {leftGyri.map((d, i) => (
          <path
            key={`lg-${i}`}
            d={d}
            fill="none"
            stroke="url(#gyriStroke)"
            strokeWidth="1"
            strokeOpacity="0.55"
            strokeLinecap="round"
          />
        ))}
        {rightGyri.map((d, i) => (
          <path
            key={`rg-${i}`}
            d={d}
            fill="none"
            stroke="url(#gyriStroke)"
            strokeWidth="1"
            strokeOpacity="0.55"
            strokeLinecap="round"
          />
        ))}
      </g>

      {/* (4) Longitudinal fissure (vertical line dividing hemispheres) */}
      <path
        d="M 200,55 Q 198,170 200,280"
        fill="none"
        stroke="#0c4a6e"
        strokeWidth="2.5"
        strokeOpacity="0.9"
      />
      <path
        d="M 200,55 Q 198,170 200,280"
        fill="none"
        stroke="#22d3ee"
        strokeWidth="0.6"
        strokeOpacity="0.8"
      />

      {/* (5) Animated neural firing dots — pulse at staggered times */}
      {firingNodes.map((n, i) => (
        <g key={`fn-${i}`}>
          <circle
            cx={n.cx}
            cy={n.cy}
            r="3"
            fill="#22d3ee"
            style={{
              filter: 'drop-shadow(0 0 4px #22d3ee)',
              animation: `firingPulse 2s ease-in-out ${i * 0.25}s infinite`,
            }}
          />
        </g>
      ))}

      {/* (6) Animated neural pathway: traveling dot along a curve to suggest
            signal propagation. */}
      <circle r="2.5" fill="#a78bfa" style={{ filter: 'drop-shadow(0 0 4px #a78bfa)' }}>
        <animateMotion dur="4s" repeatCount="indefinite" path="M 130,105 Q 200,140 270,105 Q 295,165 270,215 Q 200,245 130,215 Q 105,165 130,105 Z" />
      </circle>
      <circle r="2.5" fill="#22d3ee" style={{ filter: 'drop-shadow(0 0 4px #22d3ee)' }}>
        <animateMotion dur="5s" repeatCount="indefinite" begin="1s" path="M 105,165 Q 200,200 295,165 Q 200,250 105,165 Z" />
      </circle>

      {/* (7) Tiny sparking dots clustered around active areas */}
      {Array.from({ length: 12 }).map((_, i) => {
        const angle = (i / 12) * Math.PI * 2;
        const cx = 200 + Math.cos(angle) * (80 + Math.random() * 25);
        const cy = 167 + Math.sin(angle) * (60 + Math.random() * 25);
        return (
          <circle
            key={`sp-${i}`}
            cx={cx}
            cy={cy}
            r="0.8"
            fill="#67e8f9"
            opacity="0.9"
            style={{ animation: `firingPulse 2.5s ease-in-out ${i * 0.2}s infinite` }}
          />
        );
      })}
    </svg>
  );
};

/** Brain hero card with anatomical brain + thought bubbles around it */
const BrainHero = () => {
  return (
    <div className="relative aspect-[4/3] rounded-2xl border border-zinc-800/80 bg-zinc-950/40 overflow-hidden">
      {/* Soft inner backdrop */}
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at center, rgba(139,92,246,0.12) 0%, rgba(34,211,238,0.06) 35%, transparent 70%)' }} />

      {/* Brain SVG fills the card */}
      <div className="absolute inset-0">
        <AnatomicalBrain />
      </div>

      {/* Floating thought bubbles — anchored to brain regions.
          Position values (top/left/etc.) chosen so the dot of each chip
          visually points to a specific cortical area. */}
      <div className="absolute top-4 left-6"><NeonChip tone="cyan">Analyze Market Data</NeonChip></div>
      <div className="absolute top-8 right-8"><NeonChip tone="emerald">Risk Check: Green</NeonChip></div>
      <div className="absolute top-1/2 -translate-y-1/2 left-3"><NeonChip tone="violet">Strategy Update</NeonChip></div>
      <div className="absolute top-1/2 -translate-y-1/2 right-3"><NeonChip tone="cyan">Pattern Recognized</NeonChip></div>
      <div className="absolute bottom-12 left-10"><NeonChip tone="violet">Sentiment Shift</NeonChip></div>
      <div className="absolute bottom-4 right-6"><NeonChip tone="cyan" pulse>Execute: BUY NVDA</NeonChip></div>

      {/* Center label — tiny "ACTIVE" badge below brain stem */}
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2">
        <NeonChip tone="emerald" pulse>Active · 14 models</NeonChip>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Page composition
// ---------------------------------------------------------------------------

export const AuraMockupPreview = () => {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-200 p-6 space-y-6" data-testid="aura-mockup-page">
      <style>{`
        @keyframes auraShimmer { 0% { background-position: 0% center; } 100% { background-position: 200% center; } }
        @keyframes starTwinkle { from { opacity: 0.3; } to { opacity: 1; } }
        @keyframes firingPulse { 0%, 100% { transform: scale(1); opacity: 0.55; } 50% { transform: scale(1.6); opacity: 1; } }
        @keyframes gyriShimmer { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }
      `}</style>

      {/* Page header */}
      <header className="flex items-end justify-between border-b border-zinc-900 pb-4">
        <div>
          <h1 className="text-3xl font-bold text-zinc-100">SentCom · AURA Concept Preview</h1>
          <p className="text-sm text-zinc-500 mt-1">Unified mockup combining the production HUD, anatomical brain hero, and steal-list components into one cohesive showcase.</p>
        </div>
        <div className="text-right text-[10px] font-mono text-zinc-600">
          <div>Reachable via <span className="text-cyan-300">?preview=aura</span></div>
          <div>Built with existing stack only · zero side-effects</div>
          <div className="mt-1"><NeonChip tone="emerald">All concepts merged · no overlap</NeonChip></div>
        </div>
      </header>

      {/* ── Top HUD strip ────────────────────────────────────────────── */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 flex items-center gap-4 shadow-[0_0_24px_-12px_rgba(34,211,238,0.4)]">
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

      {/* ── Hero row — Brain + flanking summary cards ─────────────── */}
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-3 space-y-3">
          <GlassCard glow="cyan" title="Portfolio Performance" action={<NeonChip tone="emerald" dot={false}>+1.28%</NeonChip>}>
            <div className="text-2xl font-bold text-zinc-100">$2,450,780</div>
            <svg viewBox="0 0 200 60" className="w-full mt-2"><polyline fill="none" stroke="url(#pp1)" strokeWidth="2" points="0,40 20,38 40,42 60,30 80,32 100,22 120,28 140,18 160,20 180,12 200,8" /><defs><linearGradient id="pp1"><stop offset="0%" stopColor="#22d3ee" /><stop offset="100%" stopColor="#a78bfa" /></linearGradient></defs></svg>
            <div className="text-[9px] font-mono text-zinc-600 mt-1 flex justify-between"><span>24H</span><span>1AM</span><span>12PM</span><span>3PM</span><span>6PM</span></div>
          </GlassCard>
          <GlassCard glow="cyan" title="Watchlist">
            {[['AAPL', '+1.1%', 'emerald'], ['NVDA', '+2.5%', 'emerald'], ['MSFT', '+0.9%', 'emerald'], ['TSLA', '-0.3%', 'rose']].map(([s, p, t]) => (
              <div key={s} className="flex justify-between text-xs py-1 border-b border-zinc-900 last:border-0"><span className="font-bold text-zinc-300">{s}</span><span className={`font-mono ${t === 'emerald' ? 'text-emerald-300' : 'text-rose-300'}`}>{p}</span></div>
            ))}
          </GlassCard>
        </div>

        {/* Brain hero in the center — the real centerpiece */}
        <div className="col-span-6"><BrainHero /></div>

        <div className="col-span-3 space-y-3">
          <GlassCard glow="violet" title="Current Strategy">
            <div className="text-lg font-bold text-zinc-100">Alpha Growth</div>
            <div className="flex gap-1.5 mt-2"><NeonChip tone="emerald">Active</NeonChip><NeonChip tone="zinc" dot={false}>Automated</NeonChip></div>
          </GlassCard>
          <GlassCard glow="emerald" title="Risk Control">
            <ArcGauge value={92} tone="emerald" sublabel="Risk Level" size="sm" />
            <div className="text-[10px] text-zinc-500 mt-1 text-center">Max Drawdown: <span className="text-emerald-300 font-mono">3.1%</span></div>
          </GlassCard>
          <GlassCard glow="cyan" title="AI Confidence">
            <ArcGauge value={88} tone="cyan" sublabel="High Confidence" size="sm" />
          </GlassCard>
        </div>
      </div>

      {/* ── Production grid — Scanner + Chart + Right rail ────────── */}
      <div className="grid grid-cols-12 gap-3 h-[420px]">
        <GlassCard glow="cyan" className="col-span-3 overflow-hidden" title="Scanner · top 10">
          <div className="space-y-1.5">
            {[['AAPL', 92, 'A', '+2.1%', 'emerald'], ['NVDA', 87, 'A', '+1.4%', 'emerald'], ['META', 79, 'B', '+0.6%', 'emerald'], ['MSFT', 74, 'B', '+0.4%', 'emerald'], ['MARA', 58, 'C', '-0.3%', 'amber'], ['INTC', 41, 'D', '-1.0%', 'rose']].map(([s, sc, t, ch, tn]) => (
              <div key={s} className="flex items-center gap-2 p-1.5 rounded border border-zinc-900 bg-zinc-900/30 hover:border-cyan-500/40 transition-colors">
                <span className="font-bold text-zinc-200 text-xs w-12">{s}</span>
                <NeonChip tone={sc >= 80 ? 'emerald' : sc >= 60 ? 'cyan' : sc >= 40 ? 'amber' : 'rose'} dot={false}>{t}·{sc}</NeonChip>
                <span className={`ml-auto font-mono text-[10px] ${tn === 'emerald' ? 'text-emerald-300' : tn === 'rose' ? 'text-rose-300' : 'text-amber-300'}`}>{ch}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard glow="cyan" className="col-span-6 flex flex-col" title="NVDA · 5min · IB">
          <svg viewBox="0 0 600 240" className="w-full flex-1">
            <defs>
              <linearGradient id="chartGlow" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity="0.4" /><stop offset="100%" stopColor="#22d3ee" stopOpacity="0" /></linearGradient>
            </defs>
            <path d="M0,180 L40,160 L80,170 L120,140 L160,150 L200,120 L240,130 L280,90 L320,100 L360,70 L400,80 L440,60 L480,70 L520,40 L560,50 L600,30 L600,240 L0,240 Z" fill="url(#chartGlow)" />
            <polyline fill="none" stroke="#22d3ee" strokeWidth="1.5" points="0,180 40,160 80,170 120,140 160,150 200,120 240,130 280,90 320,100 360,70 400,80 440,60 480,70 520,40 560,50 600,30" style={{ filter: 'drop-shadow(0 0 4px #22d3ee)' }} />
            <polyline fill="none" stroke="#a78bfa" strokeWidth="1" strokeDasharray="3,3" points="0,140 600,90" opacity="0.7" />
          </svg>
          <div className="flex justify-between text-[10px] font-mono text-zinc-500 mt-1"><span>09:30</span><span>10:00</span><span>10:30</span><span>11:00</span><span>11:30</span><span>12:00</span></div>
        </GlassCard>

        <div className="col-span-3 flex flex-col gap-3">
          <GlassCard glow="violet" title="Briefings" className="flex-shrink-0">
            <div className="space-y-1 text-[10px]">
              {[['08:30', 'Morning Prep', 'PASSED', 'zinc'], ['12:00', 'Mid-Day Recap', 'NEW', 'emerald'], ['15:00', 'Power Hour', '15:00', 'amber'], ['16:00', 'Close Recap', '16:00', 'zinc']].map(([t, n, s, tone]) => (
                <div key={n} className="flex items-center justify-between p-1.5 rounded border border-zinc-900">
                  <div><div className="text-zinc-300 text-xs">{n}</div><div className="text-[9px] font-mono text-zinc-600">{t} ET</div></div>
                  <NeonChip tone={tone} dot={false}>{s}</NeonChip>
                </div>
              ))}
            </div>
          </GlassCard>
          <GlassCard glow="cyan" title="Live Decision Feed" className="flex-1 overflow-hidden"><DecisionFeed /></GlassCard>
        </div>
      </div>

      {/* ── Bottom row — Positions + Timeline + Backfill Readiness ── */}
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
          <div className="flex items-center gap-2 mb-2">
            <ArcGauge value={97} tone="violet" sublabel="Ready" size="sm" />
            <div className="flex-1 grid grid-cols-1 gap-1 text-[9px] font-mono">
              {[['Queue Drained', 'emerald'], ['Critical Fresh', 'emerald'], ['Overall 98.7%', 'emerald'], ['No Duplicates', 'emerald'], ['Density 94%', 'amber']].map(([c, tone]) => (
                <div key={c} className={`px-1.5 py-0.5 rounded border flex items-center gap-1 ${tone === 'amber' ? 'border-amber-500/30 text-amber-300 bg-amber-500/5' : 'border-emerald-500/30 text-emerald-300 bg-emerald-500/5'}`}>
                  <span className={`w-1 h-1 rounded-full ${tone === 'amber' ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                  <span className="truncate">{c}</span>
                </div>
              ))}
            </div>
          </div>
        </GlassCard>
      </div>

      <footer className="pt-6 text-[10px] font-mono text-zinc-600 text-center border-t border-zinc-900">
        Mockup file: <span className="text-zinc-400">/app/frontend/src/pages/AuraMockupPreview.jsx</span> · delete the file + the App.js URL-param check to remove. No production code paths touched.
      </footer>
    </div>
  );
};

export default AuraMockupPreview;
