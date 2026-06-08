# SentCom Investigation — June 2026 (fork session)

Read-only diagnostics only (hardware-bound DGX; patches via paste.rs, no testing_agent).
All findings verified against the operator's live Mongo by the operator running scripts.

## HANDOFF PREMISES THAT WERE DISPROVEN
1. "DL models collapsed (~47%)" — FALSE. TFT 46.8% vs a 45.5% 3-class majority
   baseline = +1.3pp real edge. The "47%=broken" came from comparing against a
   wrong 50% binary baseline. Meta-labelers score 0.55-0.67 (strong).
2. "Bot takes ~zero trades / frozen" — FALSE. 1,522 real closed trades; 662 in
   last 7d. Gate produces plenty of GO. 59.5% of setups clear meta p_win>=0.50.
3. "meta-labeler p_win>0.50 freezes it" — FALSE as a freeze; it's a sizing gate
   and the meta-labeler uses BALANCED class weights so p_win is a RANKING signal,
   not a calibrated probability.

## DATA-SOURCE CORRECTION (operator caught this)
- confidence_gate_log (83k rows) = the gate scoring EVERY shadow/candidate setup,
  NOT real trades. Its outcome-tracking matched only 91 rows (broken values).
- SOURCE OF TRUTH = bot_trades (status=closed, realized_pnl, risk_amount) +
  alert_outcomes (won/lost/scratch, r_multiple).
- Early trades were larger-size / orphaned / overnight / pre-pipeline noise →
  discount legacy period.

## REAL PROBLEM (verified): REGIME MISMATCH, not broken models
Clean R = realized_pnl / risk_amount (the stored r_multiple is sparse/corrupt:
only 211/1522, median 0, mean -2.35 from outliers — do NOT trust it).

Portfolio: total +$241k (size-driven, concentrated) but mean clean_R NEGATIVE
(-0.28), median ~0 → a tail of catastrophic losers (led by vwap_fade_short).

Regime-conditioned (regime_score bands), using the SYSTEM taxonomy strategy_family:
  family         BEAR<=45    NEUT      BULL>60
  breakout       +0.227      -1.052    -0.089 (n=546; dominated by squeeze)
  continuation   -           -0.338    -0.052 (n=251; mixed)
  reversal       -0.873      -0.847    -0.158 (n=32)
  reversion      +0.299      -0.591    -0.236 (n=189)  <- clean regime mismatch
setup_class:
  swing          -           -0.132    +0.303 (n=147)  <- HTF with-trend WINS
  momentum       +0.227      -0.746    -0.176 (n=603)  <- intraday, dragged by squeeze
  fade           -0.009      -0.643    -0.231 (n=199)

KEY: family-level gating is TOO COARSE. squeeze (478 trades, -0.184 in BULL) hides
inside "breakout" alongside daily_breakout (+1.552). Suppressing a family would
kill winners. => Fix must be DATA-DRIVEN PER-SETUP x REGIME suppression.

Market context (operator + SPY/QQQ dailies): relentless grind-up since early April
2026 → counter-trend fades steamrolled; HTF/with-trend setups thrive. Correct.

Biggest single leak: vwap_fade_short (mean -2.444R, median -0.851R, n=95, -$82.5k)
— systematically broken in this regime, not outlier-driven.
Best performers: daily_breakout (+1.552R), accumulation_entry (+0.104R, n=100),
gap_fade (+0.119R IN BULL — regime-ROBUST, must NOT be suppressed despite being
a 'reversion' family member).

## RECENT CLASSIFIER CHANGE (June 5, commit d8c6d862) — NOT the cause
It was a tidal_wave->fading_bounce rename + a new momentum 'tidal_wave' detector.
Did NOT change classification of any bleeding setup. Root cause predates it.

## TAXONOMY-ALIGNMENT AUDIT (services/setup_taxonomy.py is the SSOT)
Pass 1 findings (diag_taxonomy_coverage.py):
- 🔴 _scalp canonicalization bug: class sets store full 'spencer_scalp/abc_scalp/
  9_ema_scalp' but canonicalize() strips '_scalp' -> 'spencer/abc/9_ema' which are
  NOT in any set -> setup_class='unknown' -> ai_feature_family default 'MOMENTUM'.
  abc_scalp: 199 real trades + 451 alerts misrouted; spencer_scalp 9+488; 9_ema_scalp 254.
- 🔴 relative_strength_long/short/leader/laggard UNMAPPED (29k+ scanner alerts) ->
  MOMENTUM default. Distinct from rs_leader_break. Need taxonomy entries/aliases.
- 🟡 multi-suffix: orb_long_confirmed -> strips only _confirmed -> 'orb_long' -> unknown
  (should be 'orb'). Single-pass _strip_suffix misses stacked suffixes.
- ✅ ensemble-key coverage complete; CNN uses separate family/style vocabulary (by design).

Remaining audit passes (planned):
  2. Legacy-map drift (enhanced_scanner._enabled_setups, smb_integration.SETUP_REGISTRY,
     market_setup_classifier.TRADE_ALIASES, trade_style_classifier.SETUP_TO_STYLE,
     frontend tradeStyleMeta.js) — independent category logic that can diverge?
  3. AI-routing consistency (confidence_gate inline setup->family map line ~1033).
  4. Classification review (vwap_bounce/vwap_continuation as 'continuation' but bleed;
     squeeze as breakout but #1 leak).
  5. Frontend alignment (UI reading /api/sentcom/taxonomy vs stale copy).
  6. Grading/EV consistency (canonicalize + is_edge_excluded everywhere).

## PENDING / INDEPENDENT WINS (ready)
- 🔴 P0 SECURITY: Atlas creds removed from LOCAL_TRAINING_README.md (patch
  https://paste.rs/s23S6). OPERATOR MUST ROTATE the Atlas password (in git history).
- 🟢 TFT baseline-persistence fix: _save_model() drops majority_baseline/edge/
  num_classes (train() computes them) — that's why dl_models showed None. Low-risk patch.

## DESIGN DECISION FOR THE FIX
Regime gate = DATA-DRIVEN per-setup x regime_band expectancy suppression
(auto-refreshable table from bot_trades), NOT a coarse family rule. Matches the
"self-improving system" goal. gap_fade needs a data-backed positive-in-BULL exception.
Sequencing agreed direction: fix taxonomy coverage/routing FIRST (so p_win signals
are correct), THEN build the regime gate.

## DIAGNOSTIC SCRIPTS CREATED (backend/scripts/)
diag_tft_real_baseline.py, diag_meta_labeler_freeze.py, diag_live_gate_decisions.py,
diag_bot_trades_truth.py, diag_expectancy_clean.py, diag_setup_recency.py,
diag_setup_x_regime.py, diag_family_x_regime.py, diag_taxonomy_coverage.py

## TAXONOMY AUDIT PASSES 2-6 (static code analysis, complete)
DELEGATE TO SSOT (good): trade_style_classifier (canonicalize), enhanced_scanner
alerts (canonicalize+strategy_family), tqs/setup_quality, ev_tracking_service,
learning_loop_service, setup_grading_service (canonicalize + is_edge_excluded).
=> Pass 6 grading/EV is clean.

DRIFT / PARALLEL TAXONOMIES:
1. 🔴 confidence_gate.SETUP_TO_MODEL (line ~1017): hand map, NOT from ai_feature_family.
   ACCUMULATION_ENTRY -> [REVERSAL, MEAN_REVERSION] but SSOT=TREND_CONTINUATION
   (accumulation_entry is the +0.104R/100 WINNER -> scored by reversal model in
   _get_model_consensus, line 1057). Also own ad-hoc base_setup via .replace("_LONG"...).
   Scalps -> [SCALP] here vs MOMENTUM in SSOT (canonicalization-bug divergence).
2. 🔴 smb_integration.SETUP_REGISTRY (68 setups) + SMB_SETUP_ALIASES: independent
   registry w/ own category/direction/aliases; does NOT delegate to SSOT canonicalize.
3. 🔴 market_setup_classifier.TRADE_ALIASES/TRADE_SETUP_MATRIX: own alias map.
4. 🟡 frontend tradeStyleMeta.js: static mirror, does NOT fetch /api/sentcom/taxonomy.

REMEDIATION PRIORITY (proposed):
  P0 security (Atlas) + rotate.
  T1 fix SSOT coverage bugs (scalp canon, relative_strength_*, multi-suffix) + unit test.
  T2 make confidence_gate.SETUP_TO_MODEL derive from ai_feature_family (fixes
     accumulation_entry mis-route) — highest signal-quality win.
  T3 smb_integration + market_setup_classifier delegate aliasing to SSOT canonicalize.
  T4 frontend reads /api/sentcom/taxonomy (or generate tradeStyleMeta.js from it).
  T5 TFT baseline-persistence fix.
  T6 data-driven per-setup x regime suppression gate (the bleeding fix).


## SHIP LOG (fork 2026-06)
- T0 security (Atlas creds removed) — patch s23S6. DONE (operator must still ROTATE pwd).
- T1 SSOT coverage (scalp canon, relative_strength_* exclude, stacked suffix) — V7Sfd. DONE.
- T5 TFT baseline persistence — hioYs. DONE.
- T2 confidence_gate routing → SSOT (_SETUP_TO_MODEL canonical-keyed + ai_feature_family
  fallback; accumulation_entry→REVERSAL; specialized VWAP/SCALP/ORB/GAP/RANGE kept) —
  patch W... (pushed by operator, 4d73a2a9). DONE.
- T3 alias delegation — patch W4lzg. DONE. SMB_SETUP_ALIASES now sourced from SSOT
  ALIASES (no 2nd copy); market_setup_classifier.lookup_trade_context canonicalizes
  trade first (fixes vwap_fade_short silently → NOT_APPLIC) w/ monotonic experimental
  check (raw OR canonical). test_t3_alias_delegation.py.
- T6 data-driven per-setup×regime suppression — patch abISD. DONE (SHADOW mode default).
  New services/ai_modules/regime_expectancy_calibrator.py: clean_R per
  (canonical_setup × direction × band BULL>60/NEUT46-60/BEAR<=45), EXP recency weight
  half-life 60d, 180d cap. decide_suppression: weighted_mean_R<=-0.50 & eff_n>=25 →SKIP;
  <=-0.10 →REDUCE(x0.4); else NONE (gap_fade/daily_breakout safe by data, no hardcode).
  Stored setup_regime_expectancy(_id=current); mode in (_id=config) default shadow.
  Gate loads via _load_regime_expectancy(), enforces in evaluate() (shadow=record only,
  active=force SKIP / soft REDUCE). Daily refresh hook in trading_scheduler (16:35 ET).
  Script: scripts/refresh_regime_expectancy.py (--preview-only / --set-mode active|shadow).
  short(30d)/mid(90d)/all-time means stored DISPLAY-ONLY (diag) for edge-decay eyeballing.
  Tunables signed off by operator: HARD=-0.50, SOFT=-0.10, MIN_EFF_N=25, half-life 60d.
  (SOFT later raised to -0.12 per operator after reviewing the live 1,522-trade table —
   protects breakeven rs_leader_break/squeeze|long at ~-0.10; enforced set = 4 REDUCE,
   0 SKIP. patch UbtCz.)

- T4 frontend SSOT alignment — patch ag41A. DONE. tradeStyleMeta.js already fetched
  /api/sentcom/taxonomy (initTaxonomyStyles → _dynamicStyleMap wins over static
  SETUP_TO_STYLE). T4 hardened it: (1) fixed real static drift vs SSOT (tidal_wave
  scalp→intraday, breakdown_confirmed multi_day→intraday, added fading_bounce→scalp);
  (2) made hydration observable (subscribeTaxonomy/getTaxonomyVersion + React hook
  utils/useTaxonomy.js) and wired TradeStyleChip + OpenPositionsV5 so views re-render
  the instant the SSOT map arrives (kills cold-start static-fallback staleness);
  (3) committed taxonomy_ssot.snapshot.json + taxonomy_ssot_sync.smoke.js drift-guard
  (static must agree with SSOT for all 68 overlapping setups). webpack compiled clean;
  node smoke: 68/68 drift-guard + 38/38 resolveTradeStyle regression.
  static SETUP_TO_STYLE intentionally kept as offline fallback (now drift-guarded).

ALL TAXONOMY-UNIFICATION TASKS (T1-T6) COMPLETE. No parallel taxonomies remain.

REMAINING / user-side: rotate Atlas pwd; apply v304 tape-momentum patch (paste.rs/nq4TJ);
  after a few days of T6 shadow logs look clean → flip to active (--set-mode active).
