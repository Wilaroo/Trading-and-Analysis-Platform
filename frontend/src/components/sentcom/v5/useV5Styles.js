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

/* Panel + text utilities */
.v5-panel-title { font-size:10px; font-weight:700; letter-spacing:.15em; text-transform:uppercase; color:#71717a; }
.v5-why { font-size:11px; color:#d4d4d8; line-height:1.5; font-style:italic; }
.v5-why-dim { font-size:10px; color:#71717a; line-height:1.4; }
.v5-dim { color:#52525b; }
.v5-bot-tag { font-style:normal; font-weight:600; }

/* Stage chips */
.v5-chip { display:inline-block; font-size:9px; font-family:'JetBrains Mono', ui-monospace, monospace; padding:1px 5px; border-radius:2px; border:1px solid; white-space:nowrap; }
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
.v5-stream-item.sev-info  { border-left-color:#334155; }

/* Briefings */
.v5-briefing-card { padding:10px 12px; border-bottom:1px solid #18181b; cursor:pointer; transition:all .15s; position:relative; }
.v5-briefing-card:hover { background:#141416; }
.v5-briefing-new { background:linear-gradient(90deg, rgba(234,179,8,.10) 0%, transparent 70%); border-left:2px solid #eab308; padding-left:10px; }
.v5-briefing-pending { opacity:.4; cursor:default; }
.v5-briefing-pending:hover { background:transparent; }

/* NEW / LIVE pulse for recent briefings */
.v5-new-badge { display:inline-flex; align-items:center; font-size:9px; font-weight:700; padding:1px 4px; border-radius:2px; background:#eab308; color:#000; letter-spacing:.1em; animation:v5-pulse 2s infinite; }
@keyframes v5-pulse { 0%,100% { opacity:1; } 50% { opacity:.5; } }

/* Stream filter chips */
.v5-filter-chip { display:inline-block; font-size:9px; font-family:'JetBrains Mono', ui-monospace, monospace; padding:2px 6px; border-radius:2px; border:1px solid #27272a; background:#0a0a0a; color:#71717a; cursor:pointer; transition:all .12s; text-transform:uppercase; letter-spacing:.08em; }
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

/* Hover popover (used by AccountGuardChipV5 and others). Pure CSS, no JS. */
.v5-hover-wrap { position:relative; display:inline-block; }
.v5-hover-wrap > .v5-hover-panel {
  position:absolute; top:calc(100% + 6px); right:0; z-index:80;
  min-width:240px; max-width:340px;
  background:#0a0a0a; border:1px solid #27272a; border-radius:4px;
  padding:10px 12px; box-shadow:0 10px 30px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.02);
  font-family:'JetBrains Mono', ui-monospace, monospace;
  font-size:10px; line-height:1.5; color:#d4d4d8;
  opacity:0; pointer-events:none; transform:translateY(-4px);
  transition:opacity .12s ease, transform .12s ease;
}
.v5-hover-wrap:hover > .v5-hover-panel,
.v5-hover-wrap:focus-within > .v5-hover-panel {
  opacity:1; pointer-events:auto; transform:translateY(0);
}
.v5-hover-panel .row { display:flex; gap:8px; padding:3px 0; align-items:flex-start; }
.v5-hover-panel .k { color:#71717a; min-width:76px; font-size:9px; text-transform:uppercase; letter-spacing:.1em; padding-top:1px; }
.v5-hover-panel .v { color:#e4e4e7; flex:1; word-break:break-all; }
.v5-hover-panel .v.match { color:#22c55e; }
.v5-hover-panel .v.miss  { color:#f87171; }
.v5-hover-panel .v .alias { display:inline-block; padding:1px 5px; margin:1px 3px 1px 0; border-radius:2px; background:#18181b; border:1px solid #27272a; font-size:9.5px; }
.v5-hover-panel .v .alias.active { background:rgba(34,197,94,.12); border-color:#14532d; color:#86efac; }
.v5-hover-panel hr { border:none; border-top:1px solid #18181b; margin:6px 0; }
.v5-hover-panel .reason { color:#a1a1aa; font-style:italic; font-size:9.5px; }
.v5-hover-panel .hint { color:#71717a; font-size:9px; margin-top:6px; }
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
