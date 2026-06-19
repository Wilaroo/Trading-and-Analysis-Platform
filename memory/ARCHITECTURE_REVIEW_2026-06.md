# Architecture Review — 2026-06 — "Trust → Adapt → Autonomy"

> Durable spec we execute against. Two independent derivations (top-down
> 7/8-layer matrix vs bottom-up 6-step pipeline) converged on the **same
> seams** — that convergence is the signal the diagnosis is real, not
> pattern-matching. This memo locks the consolidated program: **6 seams,
> 3 arcs, 6 phases**, diagnostic-first, reversible, env-flagged, shipped
> via paste.rs patchers, verified by curl/diag + operator eyes (NO
> automated tester on DGX hardware).

## Original operator intent (verbatim anchor)
"I need Trade Command and SentCom to be fully reliable to make the right
trades at the right time in the right stocks across all time horizons, and
learn and grow on its own as it does it, make adjustments on its own, and
ultimately change strategies based on current market and/or stock
conditions. And most importantly I need to be able to understand why it's
doing what it's doing... reliable and trustworthy to trade my actual money
... and most important for it to make me lots of money as it trades."

---

## Part A — Blueprint → reality gap matrix

| Layer | Ideal asks for | What exists today | Verdict |
|---|---|---|---|
| **L0 Truth & Health** | Point-in-time data, fail-loud on stale, data-confidence/symbol | `/api/system/health` (8 subsystems), FAIL-CLOSED on unknown ADV, `backfill_readiness_service`, pusher heartbeat, IB boot-probe hard-block, leakage audit, point-in-time sector provider, v399 scheduler catch-up | ✅ Strong |
| **L1 Context/Regime** | Regime as a *directive* prior | `MultiIndexRegimeClassifier`, `SectorRegimeClassifier`, 24 numeric regime features, `vae_regime`, `regime_conditional_model`, `regime_confidence` — but **soft (ML features, not gates) by deliberate 2026-04-29 decision** | 🟡 Partial — deliberately soft |
| **L2 Universe/In-Play** | Liquidity gates size/feasibility | `in_play_service` (RVOL/Gap/ATR/Spread/Catalyst), ADV≥$2M floor, RVOL≥0.8, ADRP, tier cadences, `rs_leadership` | ✅ Strong |
| **L3 Signal/Setup** | Detectors per horizon; **style = pattern** | ~40+ detectors, m1–m9 canonical taxonomy, time-window gating, `TRADE_SETUP_MATRIX` | ✅ Strong — but **style resolves off liquidity-tier, not pattern (42% drift)** |
| **L4 Edge/ML** | Calibrated prob, purged CV, meta-labeling, abstention, edge-decay | `purged_cpcv`, `triple_barrier_labeler`, `composite_label_features`, `deflated_sharpe`, `frozen_holdout`, `fractional_diff`, `cusum_filter`, `temporal_fusion_transformer`, `cnn_lstm`, `ensemble_model`, `model_drift_service`, `edge_decay_check` | ✅✅ Best-in-class — exceeds blueprint |
| **L5 Decision & Sizing** | ONE explainable verdict + risk-budgeted sizing | 3 hard gates (Time/In-Play/Confidence predicted_R+win_prob), `position_sizer`, `dynamic_risk_engine`, `risk_caps_service` (min-of), `risk_of_ruin_model`, `hrp_allocator`, `portfolio_exposure_guard` | 🟡 Partial — **TQS & ML gate are two parallel authorities** |
| **L6 Execution** | Smart orders, broker-truth reconcile, horizon brackets | `trade_execution`, `order_intent_dedup`, `order_policy_registry`, `position_reconciler`, `orphan_gtc_reconciler`, bracket governor/reissue/TIF, `execution_tracker` | ✅ Strong — bracket geometry not yet horizon-scaled |
| **L7 Stewardship** | Trailing/time/scale + **thesis-invalidation** exits | `exit_archetype_service`, `trail_anchor_service`, `bracket_tif`, EOD-flatten, `catalyst_classifier`, `account_guard`, `kill_switch_gate` | 🟡 Partial — **regime-change exit not wired** |
| **Learning** | Retrain→OOS→shadow→promote→rollback | `training_pipeline`, `post_training_validator`, `preflight_validator`, `frozen_holdout`, `shadow_tracker`, `model_scorecard`, `trial_registry`, `gate_calibrator` (resurrected v399) | ✅ Strong |
| **Governance** | Hard un-overridable limits, kill switches, ramp | max_daily_loss 1%/2%, max_positions 5, exposure caps, `kill_switch_gate`, `safety_guardrails`, `morning_check.sh` | ✅ Strong |
| **Explainability** | One "why" per trade *and* non-trade | `decision_trail`, `ai_decision_audit_service`, TQS descriptors (v391), Data Schedule (v399b), `trade_audit_service` | 🟡 Partial — **not stitched into one narrative** |

**Headline:** ~90% of the hard machinery exists. The gap is **connective
tissue + 3 unmade architectural decisions** — not capability.

---

## Part B — The 6 seams (consolidated, prioritized)

| # | Seam | Layer / Step | Effort | Why it matters |
|---|---|---|---|---|
| 1 | **Style = Pattern, Liquidity = Feasibility** | L3/L5 · Steps 3–4 | Small | Closes the 42% drift; makes TQS trustworthy per-setup (root cause of the original thread) |
| 2 | **Unified "Why" Trace** (per trade AND non-trade) | Explainability · Step 5/6 | Medium | The thing needed to trust real money |
| 3 | **Unify TQS ↔ Confidence Gate** → one authority + verdict | L5 · Step 5 | Medium | One answer to "why did it trade" |
| 4 | **Regime-Fit Abstention** at decision | L1→L5 · Steps 1–3 | Small–Med | Stops trading into hostile/OOD regimes |
| 5 | **Thesis-Invalidation Exits** | L7 · Step 6 | Medium | Protects winners→losers when the world changes mid-trade |
| 6 | **Autonomous Strategy On/Off by Regime** | L1+Learning · Step 3+learn | Larger (capstone) | The "change strategies on its own" goal |

---

## Part C — Plan of action: 3 arcs, 6 phases

Each phase: **diagnostic-first → reversible env-flagged patch → verify
before next.** Independently shippable. One phase fully verified before
the next; no half-built seams.

### ARC 1 — TRUST (every score/decision honest & explainable)

**P1 · Style = Pattern, Liquidity = Feasibility** 🔴 Small — *NEXT BUILD*
- Flip resolution so the **pattern** (`setup_taxonomy.style_of()`) sets the
  TQS weighting lens; liquidity becomes a separate feasibility/size signal
  (penalty/flag, never a silent relabel). Persist `weights_used` on
  `tqs_breakdown`.
- Depends on: nothing. Verify: `diag_style_integrity` drift → ~0;
  `diag_tqs_coverage` unchanged or better. Flag: `TQS_STYLE_FROM_PATTERN`.

**P2 · Unified "Why" Trace** 🟡 Medium
- Stitch `decision_trail` + TQS (with `weights_used`) + ML gate inputs +
  regime + in-play + exit reason into ONE per-trade and per-*non*-trade
  narrative, surfaced in the decision/Diagnostics UI.
- Depends on: P1. Verify: 10 trades + 10 skips read as a coherent story.

### ARC 2 — DECISION (one authority, regime-aware)

**P3 · Resolve TQS ↔ Confidence-Gate** 🟡 Medium
- Decide: TQS **feeds** the gate (fused, calibrated input) OR is branded the
  human trust/quality lens with the ML gate as sole decider. Wire ONE
  verdict. **(Operator decision pending — the hinge of Arc 2.)**
- Depends on: P2. Verify: shadow-compare old vs unified verdict on N alerts
  before flipping live.

**P4 · Regime-Fit Abstention** 🟡 Small–Med
- Keep regime soft for ML features (preserve training flow) but add a thin
  decision-time check: low `regime_confidence` / OOD → stand down or
  size-down. Makes regime directive without starving data.
- Depends on: P3. Verify: count would-be trades abstained in hostile
  regimes (shadow first).

### ARC 3 — ADAPT & AUTONOMY (earned last)

**P5 · Thesis-Invalidation Exits** 🟡 Medium
- Close/trim when the *reason* dies: regime flip against the position,
  negative catalyst mid-trade, setup premise broken. Uses existing
  `catalyst_classifier` + regime stream.
- Depends on: P4. Verify: backtest/shadow triggers vs mechanical-only.

**P6 · Autonomous Strategy On/Off by Regime** 🟠 Larger — capstone
- Extend `regime_demotion_service` into strategy-family enable/disable
  driven by live edge-decay × regime. **Bounded autonomy** (toggles known
  strategies; never invents/hot-tunes in prod), staged via shadow +
  capital-ramp.
- Depends on: P1–P5. Verify: paper-shadow on/off decisions for a probation
  window before live.

---

## Part D — Backlog slotting (nothing lost)
- 🟢 RSI clamp / min-bars guard → L3/Step 3 quality fix; opportunistic with P1.
- 🟡 EV `strategy_ev_r` stamping (Setup 43% no-data) → L4/Step 4; pairs with P1.
- 🟡 `adrp_20d` warm-fill → L2 data-coverage; runs via v399 catch-up loop.
- 🟠 Entry-Tendency plumbing (execution_tracker → trade_outcomes) → L7/Learning;
  do alongside P5. **Do NOT band-aid by scheduling `run_daily_analysis`** —
  resurrects the v391 false-positive.
- 🔴 Live Tape feed → L3; large, schedule after Arc 1.
- 🟡 Horizon-scaled bracket geometry → L6/Step 6; pairs with P5.
- 🟢 `server.py` monolith breakup → incremental between phases, never big-bang.
- 🔴 Atlas password rotation → governance hygiene; independent, anytime.

---

## Part E — Execution discipline (non-negotiable)
- **Diagnostic-first** every phase: read-only audit → see live damage →
  patch → re-run diag to prove the fix.
- **Reversible & env-flagged**: each behavioral change ships behind a flag
  (pattern of `SHORT_FADE_GATE_POLICY=observe`, `PWIRE_MULTI_TF_SHADOW`).
- **paste.rs patchers**: SHA-guarded, `.bak` backups, idempotent,
  `--check/--apply/--rollback`. No large code in chat.
- **No automated tester on DGX hardware** — verify via curl + diag + eyes.
- One phase shipped & verified before the next.

---

## Part F — UI program (parallel track, surfaces the seams)
Design spec locked in `/app/design_guidelines.json` ("Control Room
Data-Dense", dark glassmorphism, cyan/amber/rose semantic states, NO
purple). Two tracks delivered as mockups (saved in repo):
- **Track A — incremental v5**: Why-Trace expandable + modal, Regime Weather
  badge, Provenance Ring on Verdict + scanner mini-arcs, Style-Lens chip,
  Strategy Autonomy panel.
- **Track B — V6 single-page cockpit**: heartbeat pulse bar, risk-meter rail,
  Regime Weather header + time scrubber, **center Why-Trace funnel (hero)**,
  right consoles (Position Health / Safety Activity / Setup Grade),
  ⌘K AI drawer, Decision Provenance verdict, Strategy Autonomy console.
Seam→UI map: S1→Style-Lens chip + weights on ring · S2→Decision Authority
verdict · S3→Why-Trace (hero) · S4→STAND-DOWN abstention state ·
S5→thesis-invalidation tag in exit · S6→Strategy Autonomy console.

---

## Open operator decision (locks P3)
Should **TQS become an input the ML gate consumes** (one fused decision) or
**stay the human trust/quality lens** with the ML gate as sole fire-decision?
Not needed until Arc 2, but it is the hinge of P3.

_Last updated: 2026-06-19._
