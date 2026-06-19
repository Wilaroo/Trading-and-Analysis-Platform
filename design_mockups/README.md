# SentCom / TradeCommand — UI Design Mockups (2026-06)

Trust-first redesign options surfacing the 6-seam architecture
(`/app/memory/ARCHITECTURE_REVIEW_2026-06.md`). Spec:
`/app/design_guidelines.json`. Aesthetic: dark "Control Room"
glassmorphism, cyan/amber/rose semantic states, NO purple.
All images carry a banner stamp: TRACK A (cyan) / TRACK B (amber) /
PROPOSED IA (emerald).

## Track A — Incremental within current v5 (low-risk, no rewrite)
- `A1_mission_control.png` — Mission Control + Regime Weather badge,
  scanner rows w/ mini provenance-rings + Style-Lens chips + inline Trade-Trace.
- `A2_whytrace_modal.png` — full vertical Why-Trace modal (7 plain-language stages).

## Track B — V6 single-page cockpit redesign (the vision)
- `B1_cockpit_hero.png` — heartbeat bar + risk rail + Regime header + time
  scrubber + center Why-Trace funnel (hero) + right consoles.
- `B2_provenance_verdict.png` — Provenance Ring (5 pillars + weights) + unified
  Decision Authority verdict + STAND-DOWN abstention state.
- `B3_strategy_autonomy.png` — Strategy Autonomy console (family × regime-fit ×
  edge-decay × ON/OFF).

## Proposed IA (navigation + interaction)
- `IA1_proposed_nav_ai_drawer.png` — consolidated 6-item left nav
  (Command · Decision · Brain · Journal · Charts · Diagnostics) + slide-in
  ⌘K NIA AI chat drawer (where you talk to the bot).
- `IA2_chart_clickthrough.png` — clicking a scanner row / Why-Trace node opens
  the chart with bot thought-bubble overlays + a mini Why-Trace breadcrumb.

## Seam → UI map
S1 Style=Pattern → Style-Lens chip + weights on ring · S2 Unify TQS↔Gate →
Decision Authority verdict · S3 Why-Trace → hero funnel/modal · S4 Regime-Fit
Abstention → STAND-DOWN state · S5 Thesis-Invalidation → exit tag ·
S6 Autonomy → Strategy Autonomy console.

> Mockups are AI-rendered concept art (labels illustrative). They lock
> direction; final pixels come from the shadcn/lucide/framer-motion build.
