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
.v5-why { font-size:10px; color:#a1a1aa; line-height:1.45; }
.v5-why-dim { font-size:10px; color:#71717a; line-height:1.4; }
.v5-dim { color:#52525b; }

/* Stage chips */
.v5-chip { display:inline-block; font-size:9px; font-family:'JetBrains Mono', ui-monospace, monospace; padding:1px 5px; border-radius:2px; border:1px solid; white-space:nowrap; }
.v5-chip-scan   { color:#a78bfa; border-color:#5b21b6; background:rgba(139,92,246,.08) }
.v5-chip-eval   { color:#60a5fa; border-color:#1e3a8a; background:rgba(59,130,246,.08) }
.v5-chip-order  { color:#facc15; border-color:#713f12; background:rgba(234,179,8,.08) }
.v5-chip-manage { color:#22c55e; border-color:#14532d; background:rgba(34,197,94,.08) }
.v5-chip-close  { color:#94a3b8; border-color:#334155; background:rgba(148,163,184,.08) }
.v5-chip-veto   { color:#f87171; border-color:#7f1d1d; background:rgba(239,68,68,.08) }

/* Mini-5-stage bar */
.v5-mini-5stage { display:grid; grid-template-columns:repeat(5,1fr); gap:1px; }
.v5-mini-5stage span { height:3px; border-radius:1px; background:#27272a; }
.v5-mini-5stage span.on-scan   { background:#8b5cf6; }
.v5-mini-5stage span.on-eval   { background:#3b82f6; }
.v5-mini-5stage span.on-order  { background:#eab308; }
.v5-mini-5stage span.on-manage { background:#22c55e; }
.v5-mini-5stage span.on-close  { background:#64748b; }

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
.v5-briefing-card { padding:8px 10px; border-bottom:1px solid #18181b; cursor:pointer; transition:all .15s; }
.v5-briefing-card:hover { background:#141416; }
.v5-briefing-new { background:linear-gradient(90deg, rgba(234,179,8,.08) 0%, transparent 100%); }
.v5-briefing-pending { opacity:.4; cursor:default; }
.v5-briefing-pending:hover { background:transparent; }

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
