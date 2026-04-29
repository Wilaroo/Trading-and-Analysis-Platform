/**
 * V5 Global Style Injector — mounts the mockup's CSS utility classes into the
 * document head on first render.
 *
 * All classes are prefixed `v5-` so they don't collide with Tailwind or the
 * existing v4 layout. Matches `public/mockups/option-1-v5-command-center.html`.
 */
import { useEffect } from 'react';

const CSS = `
.v5-root { font-family:'IBM Plex Sans',system-ui; }
.v5-mono { font-family:'JetBrains Mono', ui-monospace, monospace; }

/* Panel + text utilities — 2026-04-29: bumped +2px across the board.
   Operator feedback: "fonts are too small, increase by 1-3pt". The
   v5 design uses px (not pt); +2px maps to ~1.5pt — middle of the
   range — so the smallest text is now 11px (readable) instead of
   9px (squinty). */
.v5-panel-title { font-size:12px; font-weight:700; letter-spacing:.15em; text-transform:uppercase; color:#71717a; }
.v5-why { font-size:13px; color:#d4d4d8; line-height:1.5; font-style:italic; }
.v5-why-dim { font-size:12px; color:#71717a; line-height:1.4; }
.v5-dim { color:#52525b; }
.v5-bot-tag { font-style:normal; font-weight:600; }

/* Stage chips — bumped 9→11px */
.v5-chip { display:inline-block; font-size:11px; font-family:'JetBrains Mono', ui-monospace, monospace; padding:1px 5px; border-radius:2px; border:1px solid; white-space:nowrap; }
.v5-chip-scan   { color:#a78bfa; border-color:#5b21b6; background:rgba(139,92,246,.08) }
.v5-chip-eval   { color:#60a5fa; border-color:#1e3a8a; background:rgba(59,130,246,.08) }
.v5-chip-order  { color:#facc15; border-color:#713f12; background:rgba(234,179,8,.08) }
.v5-chip-manage { color:#22c55e; border-color:#14532d; background:rgba(34,197,94,.08) }
.v5-chip-close  { color:#94a3b8; border-color:#334155; background:rgba(148,163,184,.08) }
.v5-chip-veto   { color:#f87171; border-color:#7f1d1d; background:rgba(239,68,68,.08) }

/* Mini-5-stage bar — chunky variant matching the mockup */
.v5-mini-5stage { display:grid; grid-template-columns:repeat(5,1fr); gap:2px; margin-top:6px; }
.v5-mini-5stage span { height:6px; border-radius:1px; background:#18181b; transition:background .2s; }
.v5-mini-5stage span.on-scan   { background:#8b5cf6; box-shadow:0 0 6px rgba(139,92,246,.4); }
.v5-mini-5stage span.on-eval   { background:#3b82f6; box-shadow:0 0 6px rgba(59,130,246,.4); }
.v5-mini-5stage span.on-order  { background:#eab308; box-shadow:0 0 6px rgba(234,179,8,.4); }
.v5-mini-5stage span.on-manage { background:#22c55e; box-shadow:0 0 6px rgba(34,197,94,.4); }
.v5-mini-5stage span.on-close  { background:#64748b; }
.v5-mini-5stage span.on-veto   { background:#ef4444; box-shadow:0 0 6px rgba(239,68,68,.4); }

/* Scanner card */
.v5-scanner-card { border-bottom:1px solid #18181b; padding:8px 10px; transition:all .15s; cursor:pointer; }
.v5-scanner-card:hover { background:#141416; }
.v5-scanner-card.active { background:#1e1b4b; border-left:2px solid #8b5cf6; padding-left:8px; }

/* Stream items */
.v5-stream-item { border-left:2px solid transparent; padding:6px 8px; border-bottom:1px solid #18181b; cursor:pointer; transition:all .15s; }
.v5-stream-item:hover { background:#141416; }
.v5-stream-item.sev-order { border-left-color:#eab308; }
.v5-stream-item.sev-fill  { border-left-color:#3b82f6; }
.v5-stream-item.sev-win   { border-left-color:#22c55e; }
.v5-stream-item.sev-loss  { border-left-color:#ef4444; }
.v5-stream-item.sev-skip  { border-left-color:#71717a; }
.v5-stream-item.sev-brain { border-left-color:#a855f7; }
.v5-stream-item.sev-scan  { border-left-color:#a78bfa; }
.v5-stream-item.sev-info  { border-left-color:#334155; }

/* Wave-1 (#5) — collapsed run row. Slightly lighter background +
   subtle dotted bottom border so it stands out from individual rows
   without being loud. */
.v5-stream-collapsed { background:rgba(63,63,70,.18); border-bottom:1px dashed #27272a; }
.v5-stream-collapsed:hover { background:rgba(63,63,70,.30); }

/* Wave-1 (#11) — cross-panel hover highlight. When a row in either
   stream is hovered, the matching Scanner card pulses with a cyan
   ring (and vice versa). The animation is intentionally short (220ms)
   so it doesn't strobe during fast mouse moves. */
@keyframes v5-cross-pulse {
  0%   { box-shadow:0 0 0 0 rgba(34,211,238,.55) inset; }
  100% { box-shadow:0 0 0 2px rgba(34,211,238,.55) inset; }
}
.v5-row-hover-cross { background:rgba(34,211,238,.06); }
.v5-card-hover-cross {
  background:rgba(34,211,238,.05) !important;
  animation:v5-cross-pulse .22s ease-out forwards;
}

/* Wave-1 (#2) — counter-trend warning. Diagonal-stripe left border
   + amber "CT" chip alongside the stage chip. Surfaces the v17
   soft-gate matrix decision so the operator can spot trades fired
   AGAINST the daily Setup at a glance. */
.v5-card-counter-trend {
  border-left:3px solid transparent;
  background-image:
    linear-gradient(transparent, transparent),
    repeating-linear-gradient(45deg, #eab308 0 6px, transparent 6px 12px);
  background-origin:border-box;
  background-clip:padding-box, border-box;
}
.v5-chip-counter-trend {
  color:#fde047;
  border-color:#a16207;
  background:rgba(234,179,8,.12);
  font-weight:700;
}

/* Wave-4 (#8) — operator RLHF reaction buttons. Hidden until row hover
   to keep the stream clean; visible permanently once labelled. */
.v5-reactions { opacity:0; transition:opacity .15s ease-in-out; pointer-events:none; }
.v5-stream-item:hover .v5-reactions,
.v5-reactions:has(.active) { opacity:1; pointer-events:auto; }
.v5-reaction-btn {
  font-size:11px; line-height:1; padding:1px 4px; border-radius:3px;
  background:transparent; border:1px solid transparent;
  cursor:pointer; transition:background .12s, border-color .12s, transform .12s;
  filter:saturate(.4) brightness(.9);
}
.v5-reaction-btn:hover { background:rgba(63,63,70,.6); filter:saturate(1) brightness(1); transform:scale(1.15); }
.v5-reaction-btn.active.up   { background:rgba(34,197,94,.18); border-color:rgba(34,197,94,.5); filter:saturate(1) brightness(1.1); }
.v5-reaction-btn.active.down { background:rgba(244,63,94,.18); border-color:rgba(244,63,94,.5); filter:saturate(1) brightness(1.1); }

/* Briefings */
.v5-briefing-card { padding:10px 12px; border-bottom:1px solid #18181b; cursor:pointer; transition:all .15s; position:relative; }
.v5-briefing-card:hover { background:#141416; }
.v5-briefing-new { background:linear-gradient(90deg, rgba(234,179,8,.10) 0%, transparent 70%); border-left:2px solid #eab308; padding-left:10px; }
.v5-briefing-pending { opacity:.4; cursor:default; }
.v5-briefing-pending:hover { background:transparent; }

/* NEW / LIVE pulse for recent briefings — bumped 9→11px */
.v5-new-badge { display:inline-flex; align-items:center; font-size:11px; font-weight:700; padding:1px 4px; border-radius:2px; background:#eab308; color:#000; letter-spacing:.1em; animation:v5-pulse 2s infinite; }
@keyframes v5-pulse { 0%,100% { opacity:1; } 50% { opacity:.5; } }

/* Stream filter chips — bumped 9→11px */
.v5-filter-chip { display:inline-block; font-size:11px; font-family:'JetBrains Mono', ui-monospace, monospace; padding:2px 6px; border-radius:2px; border:1px solid #27272a; background:#0a0a0a; color:#71717a; cursor:pointer; transition:all .12s; text-transform:uppercase; letter-spacing:.08em; }
.v5-filter-chip:hover { color:#d4d4d8; border-color:#3f3f46; }
.v5-filter-chip.active { background:#18181b; color:#e4e4e7; border-color:#52525b; }

/* HUD block */
.v5-hud-block { transition:all .15s; cursor:pointer; }
.v5-hud-block:hover { background:#27272a; border-color:#52525b; }

/* Hide TradingView attribution in embedded charts */
.v5-root a[href*="tradingview.com"] { display:none !important; }

.v5-up { color:#22c55e; }
.v5-down { color:#ef4444; }
.v5-warn { color:#eab308; }

/* Thin scrollbars */
.v5-scroll::-webkit-scrollbar { width:4px; height:4px; }
.v5-scroll::-webkit-scrollbar-thumb { background:#27272a; border-radius:2px; }
.v5-scroll::-webkit-scrollbar-track { background:transparent; }

/* Hover popover (used by AccountGuardChipV5 and others). Pure CSS, no JS.
   2026-04-29 font bump: 10/9/9.5px → 12/11/11.5px so hover tooltips
   are actually readable. */
.v5-hover-wrap { position:relative; display:inline-block; }
.v5-hover-wrap > .v5-hover-panel {
  position:absolute; top:calc(100% + 6px); right:0; z-index:80;
  min-width:240px; max-width:340px;
  background:#0a0a0a; border:1px solid #27272a; border-radius:4px;
  padding:10px 12px; box-shadow:0 10px 30px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.02);
  font-family:'JetBrains Mono', ui-monospace, monospace;
  font-size:12px; line-height:1.5; color:#d4d4d8;
  opacity:0; pointer-events:none; transform:translateY(-4px);
  transition:opacity .12s ease, transform .12s ease;
}
.v5-hover-wrap:hover > .v5-hover-panel,
.v5-hover-wrap:focus-within > .v5-hover-panel {
  opacity:1; pointer-events:auto; transform:translateY(0);
}
.v5-hover-panel .row { display:flex; gap:8px; padding:3px 0; align-items:flex-start; }
.v5-hover-panel .k { color:#71717a; min-width:76px; font-size:11px; text-transform:uppercase; letter-spacing:.1em; padding-top:1px; }
.v5-hover-panel .v { color:#e4e4e7; flex:1; word-break:break-all; }
.v5-hover-panel .v.match { color:#22c55e; }
.v5-hover-panel .v.miss  { color:#f87171; }
.v5-hover-panel .v .alias { display:inline-block; padding:1px 5px; margin:1px 3px 1px 0; border-radius:2px; background:#18181b; border:1px solid #27272a; font-size:11.5px; }
.v5-hover-panel .v .alias.active { background:rgba(34,197,94,.12); border-color:#14532d; color:#86efac; }
.v5-hover-panel hr { border:none; border-top:1px solid #18181b; margin:6px 0; }
.v5-hover-panel .reason { color:#a1a1aa; font-style:italic; font-size:11.5px; }
.v5-hover-panel .hint { color:#71717a; font-size:11px; margin-top:6px; }
`;

const STYLE_ID = 'v5-command-center-styles';

export const useV5Styles = () => {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (document.getElementById(STYLE_ID)) return;
    const tag = document.createElement('style');
    tag.id = STYLE_ID;
    tag.textContent = CSS;
    document.head.appendChild(tag);
  }, []);
};

export default useV5Styles;
