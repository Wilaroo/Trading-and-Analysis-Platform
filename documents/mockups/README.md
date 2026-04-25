# SentCom / AURA — UI Concept Archive

Snapshots of one-off UI/brand concept work that is **not** part of the
production V5 dashboard. Kept here so future-us can pick the bits we
liked without having to rebuild from scratch.

---

## `AuraMockupPreview.v1.jsx`  *(2026-04-25)*

Unified single-page concept that merged three earlier tile-style
concepts (Concepts 1 / 2 / 3) into one cohesive layout. Lives in
production at `/app/frontend/src/pages/AuraMockupPreview.jsx` and is
reachable only via the hidden URL `/?preview=aura` — never linked from
the sidebar, no side-effects, all data is synthetic.

### What's in it (steal-list for production V5 grid)

1. **Top HUD strip**
   - **AURA wordmark** — animated gradient text (`auraShimmer` keyframes),
     with subtitle "Autonomous Intelligence". Drop-in replacement for the
     existing SentCom mark.
   - Inline Pipeline HUD metrics + ⌘K hint chip.
   - Inline `ArcGauge` readouts for **AI Confidence** and **Risk Control**
     so risk + confidence are always visible above the fold.

2. **Center hero — `AnatomicalBrain` SVG**
   - Two hemispheres with longitudinal fissure, brain-stem nub.
   - 12 hand-drawn gyri ridges (6 per hemisphere) with shimmer animation.
   - 8 firing-node circles with staggered `nodePulse` pulses.
   - Halo + 25 twinkling particles for depth (no three.js, ~6 KB SVG).
   - Pure CSS keyframes, no extra deps.

3. **Production-ready grid (lower 2/3)**
   - Scanner top-10 with gate-tier neon chips.
   - Neon chart with VWAP overlay (synthetic data).
   - Right rail: Briefings + **Live Decision Feed** ticker
     (`DecisionFeed` component) — auto-rotating recent decisions.
   - **Open Positions** rows with R-multiple badges.
   - **Trade Execution Timeline** (`TradeTimeline`) — vertical glowing
     spine with BUY/SELL/SCAN/REBAL events.
   - **Backfill Readiness** card with all 5 sub-checks rendered as
     Arc-style mini gauges.

### Reusable sub-components defined inline

| Component | Purpose |
|-----------|---------|
| `NeonChip` | small pill with tone-keyed glow + optional pulse dot |
| `GlassCard` | translucent panel with backdrop blur + tone-keyed glow |
| `AuraWordmark` | animated AURA logo (lg / md / sm sizes) |
| `ArcGauge` | half-circle SVG gauge — used for confidence / risk / readiness |
| `DecisionFeed` | rotating live decision ticker |
| `TradeTimeline` | vertical-spine event log |
| `AnatomicalBrain` | the centerpiece brain SVG |

All components are **self-contained** — they import only from React, no
external UI lib calls, so they can be lifted into V5 one at a time.

### Notes for future integration into production V5

- Replace `SentComLogo` → `AuraWordmark` first (cheapest visual win).
- `ArcGauge` is small enough to slot into the `MorningBriefing` header
  or a new `RiskControlPanel` without touching existing density.
- `AnatomicalBrain` is purely decorative — only ship it on a "splash" /
  "boot" / "thinking" screen, never on the trading dashboard itself
  (would steal too much focus during live sessions).
- Keep `?preview=aura` as the staging ground for further iterations.

### How to delete cleanly when retired

```
rm /app/frontend/src/pages/AuraMockupPreview.jsx
# then remove the import + the `?preview=aura` short-circuit in
# /app/frontend/src/App.js (around line 108, 455-459).
```
