# Data & Connections Integrity Plan — 2026-06

> Goal: prove **every feed flows** and **every calculation is honest** before
> we trust the cockpit (and the bot) with real money. Diagnostic-first,
> reversible, env-flagged, paste.rs patchers, verified by curl+diag+eyes.
> The UI surfaces that prove it: **Data & Connections** (deck 02),
> **Data Confidence** (deck 16), **Autopilot Go/No-Go** (deck 17),
> **TQS Coverage** + **TQS 5-pillar drawer**.

## A. Feed/connection inventory (source → calc → display → probe)
| # | Source | Feeds calc | Display | Verify (read-only) | State |
|---|---|---|---|---|---|
| 1 | IB Gateway (Win) | everything live | Data&Conn tile, Go/No-Go | `/api/ib/status`, boot-probe | ✅ wired |
| 2 | IB Pusher (client 15) | quotes/positions | pusher heartbeat, push-age | `/api/ib/pusher-health` (push_age, pushed_at v19.34.13) | ✅ wired |
| 3 | Turbo Collectors 16-19 | `ib_historical_data` | collectors tile | diag ingest continuity | 🟡 verify gaps |
| 4 | MongoDB | all persistence | Mongo tile | conn ping, snapshot age | ✅ |
| 5 | Scheduler crons | gate-calib, fundamentals, eod | Data Schedule punchlist | `/api/diagnostics/data-schedule` (v399b) | ✅ built |
| 6 | Live **volume** | **RVOL** math | in-play score, Data Confidence | RVOL measured vs UNMEASURED (rvol==0 = unmeasured outside top-400) | 🔴 missing feed |
| 7 | Live **Tape** | Setup→Tape pillar | TQS coverage (Tape 0%) | `/api/tqs/coverage` | 🔴 NOT wired |
| 8 | Regime classifiers | context pillar, regime-fit | Regime Weather, confidence | daily-bar freshness per index/ETF | ✅ (soft) |
| 9 | Fundamentals warm-fill | Fundamental pillar | TQS coverage | nightly 18:30 cron + backfill | 🟡 ~33%→>80% draining |
| 10 | `strategy_ev_r` | Setup EV sub-score | TQS coverage (EV 43% no-data) | stamp on alert | 🟡 unstamped |
| 11 | `adrp_20d` | In-Play / liquidity proof | Data Confidence | collector warm-fill | 🟡 partial |
| 12 | execution_tracker → `trade_outcomes` | Execution pillar (Entry-Tendency) | TQS coverage (0%) | only ~2% carry real entry_slippage | 🟡 plumbing |
| 13 | P&L accounting | positions, journal, EOD | Positions, Journal | net_pnl finalize (v320h), realized autosync | ✅ mostly |
| 14 | **sector_regime** (computed, DROPPED) | Edge Score archetype cell | Provenance/Edge drawer | `build_entry_context` does NOT persist it | 🔴 **NEW gap (Phase 0)** |
| 15 | **rs_rating / symbol-RS regime** | Edge Score archetype cell | Edge drawer | computed for focus list, not on the trade | 🔴 **NEW gap (Phase 0)** |
| 16 | **trigger_price** (reliable) | trigger_drift / chase % (scalp entry-quality) | Edge drawer "why" | only best-effort persisted today | 🟡 **NEW gap (Phase 0)** |

## B. Calculation-correctness fixes (honest math)
- 🔴 **P1 Style = Pattern** (`tqs_engine` weights off `setup_taxonomy.style_of()`,
  liquidity→feasibility only; persist `weights_used`). Verify: `diag_style_integrity`
  drift → ~0. Flag `TQS_STYLE_FROM_PATTERN`. **FIRST.**
- 🟡 **EV stamping** — write `strategy_ev_r` on alerts (closes Setup 43% no-data).
- 🟡 **Entry-Tendency plumbing** — land execution_tracker slippage on `trade_outcomes`
  (do NOT schedule `run_daily_analysis` — resurrects v391 false-positive).
- 🟢 **RSI clamp / min-bars guard** on the Technical snapshot fallback.

## C. Phased sweep (each shippable + reversible)
0. **🔴 PHASE 0 — Entry Edge Score persistence (added 2026-06-24, observe-only, NO behavior change):**
   stamp `sector_regime` + `rs_rating`/symbol-RS regime + reliable `trigger_price`
   onto `entry_context` at fill, and ship a read-only coverage report so we can
   see how dark each field is on real DGX data. **Time-sensitive** — every day
   without these logged is training data the regime-conditional Edge Score
   (P4′) can never condition on retroactively.
1. **Read-only audit sweep** — run `diag_tqs_coverage`, `diag_style_integrity`,
   data-schedule, ingest-continuity → snapshot today's true state into the
   Data Confidence page. (no behavior change)
2. **P1 Style=Pattern** patch → re-run `diag_style_integrity` (drift→~0).
3. **EV stamping + adrp warm-fill** → coverage gauge lifts.
4. **Entry-Tendency plumbing** → Execution pillar real.
5. **Live-volume (RVOL) source** → in-play accuracy (bigger feed work).
6. **Live Tape feed** → Setup→Tape pillar (biggest feed work; schedule after Arc 1).
7. **Wire the 3 monitor pages** (Data & Connections, Data Confidence, Autopilot
   Go/No-Go) so the system self-reports integrity live and gates autopilot.

## D. North-star scorecard (cross-check)
Target: *fully autonomous · self-improving · reliable · understandable ·
visually appealing · safe · consistently profitable.*

| Attribute | Today | After this plan + UI | Driver |
|---|---|---|---|
| Fully autonomous | 🟡 partial | 🟡→🟢 | S6 Autonomy console + regime-fit abstention (P4/P6) |
| Self-improving | ✅ strong | ✅ | Brain lifecycle; closes once Entry-Tendency + EV data flow |
| Reliable | 🟡 | 🟢 | L0 truth: scheduler catch-up + Data Confidence + RVOL/Tape feeds + Go/No-Go gate |
| Understandable | 🟡 | 🟢 | Why-Trace + NIA narration + TQS drawer |
| Visually appealing | 🟡 | 🟢 | the glass deck |
| Safe | ✅ strong | ✅ | Risk&Safety page, kill-switch, caps, type-to-confirm, EOD-flatten |
| Consistently profitable | 🟡 | 🟡→🟢 | honest TQS (P1) + thesis-invalidation exits + autonomy; *earned, not designed* |

**Critical-path blockers to "all data flowing & correct":** P1 (calc) →
RVOL live-volume + Live Tape (feeds) → Entry-Tendency + EV (learning). Profit
is the *output* of getting these right + the decision unification (P3) — we
build the machine that makes it likely, then let edge-decay/autonomy protect it.

_Last updated: 2026-06-19._
