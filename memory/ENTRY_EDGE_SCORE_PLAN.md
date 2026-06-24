# 🧭 ENTRY EDGE SCORE — LOCKED MASTER PLAN (do not drift)

> **STATUS: ACTIVE — this is the single source of truth for the scoring rebuild.**
> Last updated 2026-06-24. Supersedes the "patch the TQS pillars" approach.
> Companion docs: `TQS_DEEPDIVE_AUDIT_2026-06.md` (why TQS is noise),
> `ARCHITECTURE_REVIEW_2026-06.md` (program/seams, P3 hinge now closed),
> `DATA_INTEGRITY_PLAN_2026-06.md` (feed sweep, Phase 0 folded in).
>
> **LIVE READ-ONLY ENDPOINTS (P3′, observe-only):**
> - `GET /api/slow-learning/entry-edge-score/report?days=120&target=mfe_r|realized_r&k_folds=5`
> - `GET /api/slow-learning/entry-edge-coverage/report?days=45`
> - Service: `backend/services/entry_edge_score.py` (fit/score/score_full) ·
>   `backend/services/entry_edge_coverage.py` · tests `backend/tests/test_entry_edge_score.py`.
> NOTE FOR OPERATOR: these require commit ≥ the P3′ build to be pushed via
> "Save to Github" before they appear on the DGX (404 = not yet pulled).

## ⛔ FUTURE AGENTS — READ THIS FIRST
1. **Do NOT try to "fix" or reweight the 5 TQS pillars.** They are proven
   statistical noise (spearman≈0 vs MFE across all 5; n=1002). The architecture
   itself is the problem. They are being REPLACED, not repaired.
2. **Do NOT treat the ML gate `confidence_score` as a trustworthy authority.**
   It is −0.029 vs MFE and INVERTED (`go` worse than `reduce`) — immature models
   on thin labels. It becomes a demoted INPUT feature, not a decision-maker.
3. **Stay on THIS plan until the Edge Score gates live and beats the champion.**
   Do not start parallel scoring experiments. Do not reopen the P3 "TQS feeds
   gate vs trust-lens" debate — it is RESOLVED (third path below).
4. **Everything ships SHADOW/OBSERVE-FIRST**, env-flagged, reversible, verified
   by curl/diag on the DGX (no automated tester on prod hardware). Push via
   "Save to GitHub" → operator pulls.

## ⭐ NORTH STAR (operator's verbatim intent)
A bot that reliably makes the **right trades at the right time in the right
stocks across all horizons**, that **learns and grows on its own**, **changes
strategy by conditions**, lets the operator **understand WHY**, is **trustworthy
with real money**, and **makes money**. The Edge Score is the engine behind 4 of
the 7 north-star attributes: reliable · self-improving · understandable · profitable.

## 🎯 THE VISION (what a score must MEAN)
A `90` on a TSLA rubberband-scalp-long and a `90` on a TSLA swing-short may read
the same, but each is derived from its OWN archetype's reasoning, weighting,
regime logic, and reliability. Each alert is scored AS ITS OWN.

## 🧱 THE SCORE OBJECT — a triple, not one number
- **EDGE** — predicted expected-MFE-R (absolute, units-ful). Drives the
  gate (trade iff conservative/lower-CI edge > threshold) and sizing (edge × confidence).
- **GRADE** — a single 0-100 number = **rolling per-archetype percentile** of the
  edge. (Operator preference: NO letter grade — just the number. Rolling cohort
  so grades adapt as regime shifts; absolute R always shown so it's never misleading.)
- **CONFIDENCE** — per-cell `eff_n` / CI width. Thin cells shrink toward parents
  and are flagged LOW. This is the "trustability" dimension TQS never had.

Gate verdict is SEPARATE from grade: a `90` (best-of-its-kind) with absolute
edge ≤ 0 → **STAND DOWN**. Grade ranks; edge decides.

## 🧬 THE ARCHETYPE CELL (conditioning key)
`setup_class × direction × style/timeframe × time_window ×
 market_regime × sector_regime × symbol_RS_regime`
Combinatorial explosion vs ~1,000 trades → **hierarchical shrinkage / partial
pooling** (empirical-Bayes / James-Stein): each cell borrows strength from its
parents up to the global prior. Per-cell CI = reliability. This is the
generalization mechanism. Reuses/generalizes the EXISTING `setup_regime_expectancy`
table (the spine P6 already reads).

## 🔄 END-TO-END PIPELINE (the structure we are building toward)
0. **TRUTH/HEALTH** — feeds verified; absence flagged, never faked.
1. **FIND** — top-down funnel: market regime → sector regime → RS leadership →
   focus list → in-play gate → ~40 setup detectors. (Phase 2+: prioritize by edge.)
2. **EVALUATE** — Entry Edge Score: build archetype cell → EDGE/GRADE/CONFIDENCE.
3. **DECIDE & SIZE** — GO iff conservative edge > threshold; size = edge × confidence,
   clamped by risk caps / exposure guard / kill-switch.
4. **TRADE** — bracket order via IB; reconcile vs IB truth; STAMP full entry context
   (archetype cell + regime layers + trigger_price).
5. **MANAGE** — trail/scale-out; thesis-invalidation exits when the reason dies.
6. **CLOSE** — realized R + MFE/MAE locked = ground truth.
7. **LEARN** — write outcome with full context → update the cell's expected-R
   (shrinkage) → retrain models (shadow→promote/rollback) → strategy autonomy
   turns rotted families OFF and back ON by regime. Feeds back into 1 & 2.

## 🗺️ PHASES (sequenced into ARC-2 of the architecture program)
- **PHASE 0 — PERSISTENCE (IN PROGRESS, observe-only, NO behavior change).**
  Stamp `sector_regime`, `rs_rating`, `symbol_rs_regime`, reliable `trigger_price`
  onto `entry_context`; ship coverage report. Time-sensitive (can't backfill).
- **P3′ — EDGE SCORE v1.** Expected-MFE-R from robust MARGINAL factors
  (time_window, direction, priority, timeframe, shrunk per-setup EV, re-signed
  regime_score, rsi, trigger_probability, tape_score). Run SHADOW via the
  existing P3 shadow-arms harness. Promote when size-weighted-R beats champion.
  - **[BUILT 2026-06-24] model + OOS lift proof** — `services/entry_edge_score.py`
    (`fit`/`score` additive shrunk-marginal model; empirical-Bayes K=20; continuous
    quantile-binned so sign-inversion is auto-captured) + read-only report
    `GET /api/slow-learning/entry-edge-score/report?days=120&target=mfe_r&k_folds=5`.
    Evaluated OUT-OF-SAMPLE via K-fold CV (reports decile lift + OOS Spearman vs
    mfe_r AND realized_R + per-factor effects). Excludes reconciled_* artifacts.
    Synthetic-data validation green (signal OOS spearman 0.74, top-decile +0.58R
    vs bottom −0.84R; noise conservative ~−0.04, no false lift) —
    `tests/test_entry_edge_score.py`.
  - **[TODO] operator runs the report on the DGX** (n≈808 real entries) to read
    REAL OOS lift vs the champion gate (which was −0.029 / inverted). Beat it → wire
    the live shadow arm (needs live alerts; market-open work).
- **P4′ — REGIME-CONDITIONAL EDGE + SHRINKAGE.** Widen to the full archetype
  cell; empirical-Bayes pooling; per-cell CI; rolling per-archetype grade.
  Optionally retrain the ML gate on the clean window.
- **PROMOTE** — Edge Score becomes the single decision authority; TQS pillars +
  gate confidence demoted to input features. UI: ring center = single number,
  TQS drawer → Edge drawer (edge-R / confidence / per-archetype why), GO/STAND-DOWN.
- **FEED FINDING** — point the scanner/focus-list prioritization at the same edge
  table so finding gets as smart as taking.

## ✅ PHASE 0 — TASK CHECKLIST & ACCEPTANCE
- [x] Stamp `sector_regime` / `rs_rating` / `symbol_rs_regime` / `trigger_price`
      in `opportunity_evaluator.build_entry_context` (observe-only).
- [x] `_classify_rs_regime` band helper (leader≥80 / strong≥60 / neutral≥41 /
      weak≥21 / laggard / unknown).
- [x] **Boundary threading (critical):** the alert never reaches build_entry_context
      as `LiveAlert.to_dict()` — THREE hand-built dicts drop fields. Threaded the
      new fields through all three: `enhanced_scanner._auto_execute_alert` trade_request
      → `scanner_integration.submit_trade_from_scanner` alert dict → and the bot
      scan-loop `trading_bot_service._get_trade_alerts` alert_dict. Uses an
      unambiguous `signal_trigger_price` key for the REAL breakout trigger (the
      auto-exec path's `trigger_price` is the ENTRY price → trigger-drift was always 0).
      build_entry_context reads `signal_trigger_price`. Verified end-to-end (stamp
      lands; legacy/empty alerts degrade to unknown/None gracefully).
- [x] Read-only coverage report: `services/entry_edge_coverage.py` +
      `GET /api/slow-learning/entry-edge-coverage/report?days=45`.
- [ ] **OPERATOR VERIFY on DGX**: after a session of live fills, run the coverage
      report. ACCEPTANCE: new fields trending up from 0 (cap ~80% — the ~20%
      `reconciled_*` artifacts have no real entry_context and are excluded from the
      model). `sector_regime` should hit ~76%+ (classifier fallback chain);
      `rs_rating` coverage = fraction of traded symbols with a cached RS doc
      (depends on the RS-leadership nightly job + universe membership).
- [ ] If `rs_rating` stays low: the cache (`rs_leadership_service.get_rating_cached`)
      is the gap, not the stamp — check the nightly RS job ran and the symbol is in
      the rated universe. If `sector_regime` low: check `sector_tag_service`/`sector_regime_classifier`.
- [ ] Once coverage is healthy and enough labeled trades accrue → start **P3′**.

## 📌 KEY FILES
- `services/opportunity_evaluator.py` — `build_entry_context` (stamps), `_classify_rs_regime`.
- `services/entry_edge_coverage.py` — Phase 0 coverage report (read-only).
- `services/entry_feature_discovery.py` / `tqs_entry_quality.py` — diagnostics proving the case.
- `services/setup_regime_expectancy*` + `strategy_autonomy.py` — the edge-table spine to generalize.
- `routers/slow_learning_router.py` — diagnostic + coverage endpoints.
