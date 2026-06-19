# SentCom / TradeCommand — UI Design Mockups (2026-06)

Trust-first redesign options surfacing the 6-seam architecture
(see `/app/memory/ARCHITECTURE_REVIEW_2026-06.md`). Spec:
`/app/design_guidelines.json`. Aesthetic: dark "Control Room"
glassmorphism, cyan/amber/rose semantic states, NO purple.

## Track A — Incremental within current v5 (low-risk, no rewrite)
- `trackA_mission_control.png` — Mission Control + Regime Weather badge,
  scanner rows with mini provenance-rings, Style-Lens chips, an expanded
  inline Trade-Trace breadcrumb.
- `trackA_whytrace_modal.png` — full vertical Why-Trace modal (7 stages,
  plain-language) for one alert, incl. non-trade note.

## Track B — V6 single-page cockpit redesign (the vision)
- `trackB_cockpit_hero.png` — heartbeat bar, risk rail, Regime Weather
  header + time scrubber, **center Why-Trace funnel (hero)**, right consoles.
- `trackB_provenance_verdict.png` — Provenance Ring (donut, 5 pillars +
  weights) + unified Decision Authority verdict + STAND-DOWN abstention state.
- `trackB_strategy_autonomy.png` — Strategy Autonomy console (family ×
  regime-fit × edge-decay × ON/OFF, bounded autonomy).

## Seam → UI map
S1 Style=Pattern → Style-Lens chip + weights on ring · S2 Unify TQS↔Gate →
Decision Authority verdict · S3 Why-Trace → hero funnel/modal · S4 Regime-Fit
Abstention → STAND-DOWN state · S5 Thesis-Invalidation → exit tag ·
S6 Autonomy → Strategy Autonomy console.

> Mockups are AI-rendered concept art (illustrative text/labels). They lock
> direction; final pixels come from the shadcn/lucide/framer-motion build.
