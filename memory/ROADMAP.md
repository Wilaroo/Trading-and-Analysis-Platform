# TradeCommand / SentCom — Roadmap & Backlog

Open priorities, deferred ideas, and backlog. Move items to
`CHANGELOG.md` once shipped; promote/demote priority by reordering.

## ✅ RESOLVED 2026-06-18 (this session — v365/v366/v367)
- ✅ **P0 "suppressed setups firing live"** = FALSE ALARM. diag_v365_leak_recency proved stale
  pre-deploy residue (every fire predates its suppression commit). No leak, no patch.
- ✅ **P1 scaled measured-move exits** = EVALUATED → KEEP flat-2R. diag_v365_scaled_exit_eval:
  flat_2R ties scaled_123 on mean EV (robust across winsor); trail/m2m lose. No EV gain to justify
  the position-mgmt build. (Re-open only if a kill-switch losing-streak problem appears live —
  deferred option B: drawdown/streak sim.)
- ✅ **P1 multi-bar-size shadow logging (P1-MULTI-TF)** = SHIPPED (v367, committed e325857c). Shadow
  now logs 1/5/15min. Env-reversible PWIRE_MULTI_TF_SHADOW=0.
- ✅ **Regime "91% high_vol" / threshold recalibration** = RE-CONFIRMED misdiagnosis (matches
  2026-06-16 diag_v320x). classify_regime threshold LEFT UNCHANGED. Do NOT recalibrate 1.3.

## 🔴 NEXT SESSION (after 2026-06-18)
- ✅ **P1 — v379 (smart_filter grade-gate) — LIVE-VERIFIED** (post-restart 18:43 UTC): 0 borderline
  "TQS (X)…threshold(75)" skips; only legit low-win-rate skips remain. Full-RTH re-confirm next session
  (plain `diag_v379 --days 1`); tune live with SMART_FILTER_BORDERLINE_MIN_GRADE=C|B|A if needed.
- ✅ **P1 — Issue 4 / v381 (dedup mark_fired post-trade) — LIVE-VERIFIED** (post-restart): dedup_cooldown
  drops = 0 (BLOCKED_NO_TRADE_DAY collapsed 92.9%→0). Full-RTH re-confirm next session.
- 🟡 **P1 — Path B: de-compress the TQS scale itself** (the deeper root cause behind v379) — **ACTIVE**.
  Read-only probe `diag_v382_tqs_pillar_compression.py` SHIPPED (paste.rs/Aw9pa). NEXT: run on DGX
  (`--days 5`), read per-pillar stdev + absent-fundamental-50 pinning %, THEN scope the math:
- **P1 — VERIFY v367 in the wild:** after RTH, `diag_v366_pwire_readiness.py --days 1` → bar_size
  distribution should show 1min/15min (not 100% 5min). Confirms multi-TF accrual.
- **P1 — P-WIRE Phase 2 edge eval:** still data-gated (RESOLVED 92/200). Run `pwire_shadow_eval.py`
  once RESOLVED≥200. NOTE: dominant 5min_high_vol variant is QUARANTINED (PBO=1.00) → 77% of records
  have no comparison model; multi-TF widens the trainable cells. Re-run readiness in ~2 weeks.
- 🔴 **Rotate Atlas MongoDB password** (old creds in git history) — still pending operator action.
- **P2 backlog:** `GET /api/scanner/setup-ev-audit` + V5 tile; OCA-finalize-health endpoint + tile;
  horizon-scaled bracket geometry; break up `server.py` monolith.


## ✅ RESOLVED 2026-06-18 (was NEXT SESSION P0s)
- ✅ P0 Part A EOD-flatten: HISTORICAL residue; live stack (v245/v261/v301/v322s) already seals it. No patch. (v338/v339)
- ✅ P0 breakdown 2470/0: correct suppression (disabled setup), not a bug. (v337)
- ✅ vwap_fade rewrite LIVE (patch_v341/v19.34.324); replay-validated both sides.

## 🔴 NEXT SESSION (added 2026-06-17, after v336 short-fade gate shipped)
- **P0 — Part A: EOD-flatten ENFORCEMENT for intraday short fades.** v334 catastrophic
  tail (WTI/USO) = intraday short fades that rode ~20-24h OVERNIGHT, then a gap blew the
  GTC market-stop far past trigger. v336 prevents ENTRY of the danger profile; Part A must
  ensure any intraday/short-fade that DOES open is reliably EOD-flattened so it never holds
  overnight. ENTANGLED with Issue-3 (`trade_2_hold` classifier gap — diag_v333 showed 528/586
  genuine trades fell to this default bucket → may resolve to a non-EOD policy). Build a
  read-only diag first (which genuine intraday/fade closed trades had hold_seconds spanning a
  session boundary + their resolved trade_style/close_at_eod policy), THEN patch. Touches
  Journey-3 EOD path (safety-critical) — fork via siblings, validate at 15:55 ET.
- **P0 — `breakdown` anomaly (2470 fires / 0 genuine trades):** diagnose whether it's a real
  block bug or correct suppression. Read-only audit of the breakdown detector → execution path.
- **P1 — verify v336 in the wild:** after next RTH, grep `🚫 [v19.34.323 short-fade]` and
  confirm it catches vwap_fade_short on sub-$5 / tight-stop names (run with
  SHORT_FADE_GATE_POLICY=observe first if you want to watch before blocking).
- Then: FADE scalp sweep (gap_fade/vwap_fade/mean_reversion/backside), MOMENTUM scalp sweep,
  P-WIRE Phase 2 (~200 resolved shadow decisions). 🔴 Rotate Atlas MongoDB password (still pending).



## ✅ RESOLVED (2026-06-16, diag_v320x) — "91% high_vol" debunked; regime classifier is ACCURATE; DO NOT recalibrate the 1.3 threshold
diag_v320x_regime_validation.py (paste.rs/lWcsD) backtested the PRODUCTION classify_regime
on 175 clean SPY daily bars (last ~180td). True distribution: range_bound 37%, bull_trend
37%, high_vol 14%, bear_trend 13% — NOT 91% high_vol. The 91% in the P-WIRE shadow log is a
SAMPLING ARTIFACT: shadow records are per-decision (~900/day), logging ran over a short,
genuinely-volatile window, and each high_vol day was amplified ~900×. The classifier is fed
correct SPY daily bars at every live site (confidence_gate._get_ai_regime,
timeseries.classify_current_regime — 5-min cached). The 1.3 vol_expansion (atr5/atr20)
threshold is well-calibrated: high_vol=14% of days and those days are PREDICTIVE (largest
forward |moves|, +1.17% fwd5; bear→negative; range→quiet). Threshold sensitivity 1.3→14%,
1.5→3%. ⇒ The 1.3→1.5 recalibration is RETRACTED PERMANENTLY (not a miscalibration).
MTF directional panel (TrendSignalBlock._score_index): correct directional TILT (SPY BULL
61% positive vs BEAR 45%) but weak magnitude predictiveness + bouncy BEAR bucket over a
180d uptrend — sound as a cautious context FILTER (its actual use), not a return predictor.
PHASE 2 implication: the "GENERIC HOLDS / keep regime dead" verdict rests on only n≈9
resolved regime records from the skewed high_vol window — NOT trustworthy. A real Phase-2
test needs a REPRESENTATIVE shadow sample across all 4 regimes → re-enable
PWIRE_SHADOW_ENABLED and accumulate across normal/trend/vol days, THEN re-run
pwire_shadow_eval. Until then Phase 2 stays parked (not on bad evidence, just on no evidence).


## 🟢 P3 (added 2026-06-16, DATA-RESOLVED — no behavioral fix) — Timeframe-aware style resolution
RESOLVED by diag_v320v (paste.rs/K7urU) on live data: of 21 trend_continuation trades
(open + 7d), RISK METRIC = 0/21 (0%) — NONE rely on the static `multi_day` fallback;
every row carries a style-resolvable `timeframe` (intraday ×19, swing ×2). 0 fragile.
So the latent "missing-context → unsafe multi_day carry" risk is NOT materializing; the
entry path reliably stamps a real style-timeframe (not raw bar sizes). Options (a)/(b)/(c)
are therefore UNNECESSARY as a behavioral change. The GLD/MSTR/TSLA/META/NOK "split" is
correct timeframe-aware stamping; the v320s INTRA→CARRY flag is a pure style_of-static
artifact.
REMAINING (low-value, optional):
  • Defensive: a startup assert / unit test that trend_continuation alerts always carry a
    style-resolvable timeframe (so the 0% never regresses).
  • Cosmetic: GLD/MSTR are stamped multi_day while timeframe=swing (carry-vs-carry; both
    hold overnight, different trail/target policy) — could normalize to swing.
  • Diag polish: feed timeframe/trade_style into style_of inside diag_v320s so its
    INTRA→CARRY flag stops false-positiving on multi-timeframe setups.
Re-run diag_v320v with a 2nd arg (e.g. `daily_breakout`) to spot-check other no-config
setups if ever concerned.


## 🟡 P1 ACTION ITEM (added 2026-06-16; diag DELIVERED 2026-06-17) — Intraday HIGH-priority gate audit
✅ DIAG DELIVERED: `diag_v320q_priority_attribution.py` (paste.rs/5WwmW, read-only,
smoke-tested). AWAITING operator DGX run (`--days 5`, post-v320p sample). The diag
decomposes the non-HIGH intraday population into ceiling_medium (structural — detector
has no HIGH branch) vs tape_gate_miss (failed tape_confirmation) vs residual, per
INTRADAY/CARRY group, with scorer-input means. NEXT after run: choose the lever —
add a tape/in-play/RR-gated HIGH branch to medium-capped intraday detectors, OR
recalibrate the tape gate. NOT a sizing change. Verify lever: v320o INTRADAY HIGH%
should rise toward CARRY%.

--- original note (context) ---
After v320p (A+ horizon-hijack fix, commit 7011ab04) is confirmed via RTH diag rerun,
investigate the SECONDARY intraday-frequency lever: the HIGH-priority gate itself.
v320o data: CARRY alerts reach HIGH priority 55% of the time vs INTRADAY only 20% —
and HIGH priority is the auto-fire threshold (`_auto_execute_min_priority = HIGH`).
So even with the A+ fix, intraday alerts under-reach the auto-fire bar.
TASK: build a read-only diag (`diag_v320q_priority_attribution.py`) that, per
trade_style, breaks down WHY intraday alerts under-reach HIGH priority — decompose
the priority scorer inputs (catalyst weighting, SMB big-picture/regime skew, TQS,
in-play score). Goal: find whether the priority formula structurally penalizes
intraday context, then propose a calibration (NOT a sizing change). Gate this work
on confirming v320p's rebalance first (don't stack two intraday changes blind).
Verify lever: v320o GROUP ROLLUP INTRADAY HIGH% should rise toward CARRY%.



## Session Summary - 2026-06-12 (sanitization probes + v322x observability; calibration PARKED)

### v323b — RVOL ROOT CAUSE SOLVED (no-scalps incident)
Probe r2 convicted: morning catch-up IB collection (DGX boots after missed nightly run)
persisted TODAY'S IN-PROGRESS daily bar as complete — OXY 06-11 vol=589,273 collected
9:50 ET (full day ~6-8M). Scanner F7 guard treats prior-day bar as complete (tf=1.0) →
RVOL = 0.09x → ALL setups blocked all session; scalps die first (stricter floor).
SPY 06-09 row (collected 12:24 ET) same poison; nightly daily collection also erratic
(SPY 3 days stale). FIX (patcher nfOTu): `_is_inprogress_daily_bar()` guard on ALL 3
bar-write sites (daily bar dated today only persisted >= 16:15 ET) + repair scan that
DELETES existing partial rows (collected same-ET-day before 16:15). Morning catch-ups
now safe. Follow-up idea (backlog): live today-RVOL from pusher quote day_volume.
Charts: intraday 1m/5m collection proven healthy (900 bars/day, 6m max gaps) — ADBE
chart issue is in the chart data path/rendering, NOT collection; EEM entered universe
mid-day. Chart investigation still open.

### v323c — thought retention tiering (operator-approved)
sentcom_thoughts: noise kinds (scan/skip/filter/info ≈ bulk of 371K rows/week) now get
per-doc expires_at +7d (TTL(0) index `expires_at_ttl`); signal kinds (thought/alert/
evaluation/fill/rejection/system/brain) live full 190d via created_at TTL backstop.
Patcher fCGQH migrates existing noise rows. bot_trades/bracket_lifecycle_events
untouched (permanent).

### v323a r2 — long-memory chat recall (APPLIED on DGX, commit 3d524dfa)
TTL 7d→190d collMod'd live (371,019 rows ≈ 7d volume). Deep per-symbol thought recall
beyond 24h + "Symbol Trade Memory" from bot_trades — r2 SANITIZED inline (mirrors
sanitize_v2 funnel: artifact close-reasons/setups, learning_only, [SIMULATED], shadow,
no-exit-price all excluded; artifact count disclosed in-context so the LLM can't
hallucinate a fake track record). Operator hallucination concern addressed pre-deploy.

| Version | Topic | Status |
|---|---|---|
| v323a r2 | long-memory sanitized chat recall | APPLIED + COMMITTED (3d524dfa) |
| v323b | daily-bar integrity / RVOL fix + repair | APPLIED + COMMITTED (bebd9f35) — 3,590 partial rows deleted of 13.75M scanned |
| v323c | thought retention tiering | APPLIED + COMMITTED (6baec970) — only 2,504 noise rows stamped of 376K (kind-mix check pending) |

### PT-REACHABILITY PROBE RESULTS (DGX run 14:26Z) — exits are NOT the only problem
On the 102 clean trades: trade_2_hold median stop = 1.75 "ATR" / 3.46% of entry;
median PT1 = 2.54R = ~4.85 ATR units; top offenders PT1 = 15-42 ATR (entry_context.atr
units are heterogeneous — some rows clearly store intraday ATR — treat ATR columns as
directional, R columns as exact). MFE: median 0.00R, only 6% ever reached +0.5R;
PT1 touched by 0/101 trades. Clock closes (73): only 21% were ever ≥+0.25R; avg R left
on table just +0.17R. COUNTERFACTUAL SWEEP: no PT placement (0.5-2.0R) flips avgR
positive (baseline -0.066). CONCLUSION: brackets are so wide that ALL price action is
noise within them — the R-DENOMINATOR is mis-scaled (stop from DAILY ATR ~1.3-2.5x on
intraday holds → shares collapse → P&L ±$20). v322p decay-deferral alone won't fix this;
the evidence-backed fix is HORIZON-SCALED BRACKET GEOMETRY (intraday stop ≈ fraction of
daily ATR / k× intraday ATR, PT within expected hold-window range) → queued as the next
major trading patch after v322z.

### v322z — chat data-trust fixes (audit of SNDK conversation)
Full chat_server.py audit: 16 context sections inventoried. GAPS FOUND+FIXED (patcher
Hk2wg, 11 anchored chunks, test_v322z_chat_context.py 7 tests):
1. Cold-symbol hydration: 2s timeout + SILENT skip → "I don't have a quote on SNDK".
   Fixed: 6s budget for user-mentioned tickers (snapshot+technicals) + explicit
   "LIVE QUOTE FETCH FAILED for: X" context line.
2. Stale hardcoded "Risk Parameters: $2,500/1.5:1/10 positions" (line 687) → now LIVE
   from /api/trading-bot/status risk_params; prompt risk-cap rule defers to live figure.
3. NO decision-trail recall ("why did you pass on ADBE?" unanswerable) → new section
   10.7 injects sentcom_thoughts: 1h global (12) + 24h per-mentioned-symbol (8).
4. Lowercase mentions ("thoughts on sndk?") missed by uppercase-only regex → lowercase
   rescue pass, gated on no-uppercase-found + stopword list + known-symbol cache
   (ib_historical_data.distinct, 1h TTL).
Minor: closed-trades context sorts by closed_at; bot-trade lines carry TQS grade+style.
NOTE: chat server is a SEPARATE process (port 8002) — needs its own restart after apply.

| Version | Topic | Status |
|---|---|---|
| sanitize_v1 probe | `diag_sanitized_closed_trades.py` (paste.rs F88ca) — 9-stage exclusion funnel | RUN on DGX 13:55Z |
| sanitize_v2 probe | same script upgraded: + `classify_close()` hygiene layer, legacy_orphan, emergency_flatten | RUN on DGX 14:09Z |
| v322x | TQS enrichment observability thought (🧮 pre→post TQS shift in stream) | APPLIED + COMMITTED (12d4dffb), 5/5 tests pass |

### sanitize_v2 RESULTS (DGX run 2026-06-12 14:09Z) — TRUE clean core = 102 trades (6.4% of raw)
hygiene_artifact cut 241 more than v1: 118 phantom-reason, 65 external_flatten,
52 artifact setup_types (reconciled_orphan/excess_slice/imported_from_ib), 4 corrupt-R.
legacy_orphan 70. Scored core = 94.
- TQS rescale: A n=12, B n=14 — INSUFFICIENT (unchanged verdict).
- Meta-labeling: `squeeze` collapsed 82 → **14** (!) — most squeeze closes were
  phantom/flatten artifacts. NOTHING is near the 100 threshold. accumulation_entry=6.
- Clean accrual rate: June n=58 in 12 days ≈ 4.8/day (win 48.3%, avgR -0.02,
  trending up from May 35.3%/-0.04). A/B≥30 unblock est. mid-July+; squeeze≥100
  unblock is MONTHS out at current mix.
- ⚠ FINDING — exit mix of the 102 genuine trades: eod_auto_close 40, scalp_time_decay 17,
  manual_eod 15, operator panel 15, stop_loss 13, **target_hit = 0**. ZERO target closes
  among genuine trades; bot edge ≈ breakeven (avgR ≈ 0). Suggests PTs are placed too far /
  time-based exits truncate winners → makes v322p decay-timer rework (defer decay when
  green + right side of VWAP) directly evidence-backed.
- ⚠ HOUSEKEEPING: commit 12d4dffb accidentally pushed patcher backup dirs
  (v322t/u/v/w_backup_*/, ~13 files). Suggest `git rm -r --cached` + .gitignore `v*_backup_*/`.
| MICRO_SETUPS | orphan applier `apply_v19_34_266.py` deleted (sandbox-only; never on DGX) | DONE — drift closed |

### sanitize_v1 RESULTS (DGX run 2026-06-12 13:55Z) — raw counts were GARBAGE-INFLATED
Raw 1594 closed → **257 survivors (16.1%)**. Exclusions: 645 no_exit_price (legacy
"validator fail-open era" cleanups), 206 simulated, 199 provenance, 107 admin_close,
91 learning_only, 55 sub-10s holds, 23 |R|>10.
- **TQS rescale verdict: NO-GO ❌** — sanitized A n=13, B n=15 (needed ≥30 each).
  The v322w probe's "A/B >30" was phantom-era debris.
- **Meta-labeling verdict: NO-GO ❌** — `accumulation_entry` collapsed 102 → **9**
  (May 19–26 phantom/drift crisis artifacts, exactly as `trade_outcome_hygiene.py`
  documents). `squeeze` 490 → 82 (borderline).
- v1 was still too lenient: 70 `orphaned_position_cleanup` (legacy reason, no current
  code produces it), 47 `wrong_direction_phantom_swept`, 10 phantom_recovery rows
  survived → sanitize_v2 layers canonical `classify_close()`; true core est. ~130-145.
- Era trend healthy: May n=110 win36.4%/avgR+0.10 → June n=62 win46.8%/avgR-0.01.
- `/tmp/sanitized_trade_ids.json` written on DGX — future calibration reuses this filter.

### TQS card-vs-eval audit (SOLVED — by design, surfacing fixed by v322x)
"🤔 Evaluating XOM (TQS 54 C)" vs card "TQS 60 B" = PRE-gate TQS (scanner, used as
confidence-gate quality input, `opportunity_evaluator.py:705`) vs POST-gate AI-enriched
recalc (GAP 3, line ~798) which is what gets STAMPED on the trade (line ~1453). Both
preserved in `entry_context.tqs` with delta. v322x emits a 🧮 thought on material shift
(≥1.0 pt or grade flip) so the trail reads "54 C → 60 B (model agrees, NN% conf)".

### 🔵 PARKED (user-approved 2026-06-12) — data-sufficiency gated
- **Tier 2a per-model probability calibration + TQS outcome-based recalibration/rescale**
  — wait until SANITIZED A≥30 and B≥30 (est. ~6-8 weeks at current clean-data accrual).
  Re-run `diag_sanitized_closed_trades.py` to check. Design notes: isotonic fit of
  expected R / win-prob on tqs_score, rescale to outcome percentile (cosmetic 0-100
  spread alone would NOT fix discrimination).
- **v322y meta-labeling (take/skip layer)** — re-check when sanitized `squeeze` ≥100
  (~82 at sanitize_v1; v2 will lower it). `accumulation_entry` OUT (n=9 clean).

### Still pending (carried)
- M0 ladder live validation — first SCALP fill (06-12 fills were opening_drive
  INTRADAY/M-DAY only, ladder not exercised yet).
- 🔴 SECURITY (user action): rotate Atlas MongoDB password.
- IGV "Range Break" false trigger (INT-21 guard), ELF→XLE `_industry_to_etf` audit,
  v322p decay-timer rework, chart-slow diagnosis, quarantine "MISSING"→"QUARANTINED"
  label, EOD flatten modal / regime strip (v322q), Tier 3a drift-monitor UI tile.

## Session Summary - 2026-06-11 (v322f/g/e shipped + RETRAIN DONE + Tier 3b ENFORCED)

| Version | Topic | Status |
|---|---|---|
| v19.34.322f | Tier 3 (Investment) afternoon scan 3:45 → 3:30 PM ET | shipped + committed (7352bf4d) |
| v19.34.322g | EOD auto-chain: 16:35 daily-bar top-up (`bar_size_filter`), 17:10 ADV rebuild, fix 2:15 AM resume ImportError | shipped (7352bf4d); first run queued 3,240 daily bars 06-10 16:35 ET |
| v19.34.322e | Paced full-chain deep sector backfill (IB reqContractDetails, rated-first) + endpoints | shipped (e9c810f9), LIVE-VERIFIED: rated 774→1,463 |
| v19.34.322h | Tier 3b: PBO calibration audit script + `TB_PBO_GATE=enforce` flipped | DONE (82065684; enforce live in backend/.env) |
| v19.34.322i | PBO quarantine sweep: flag-based, ALL load paths, auto-lift on healthy promotion | DONE + VERIFIED (922a8ced + r2 d6687642); 12 toxic models quarantined |
| v19.34.322j | T6 verification + flip tooling + quarantine-aware boot diagnostic + gate-summary runtime probe | DONE (27a01d7e + r2); T6 CONFIRMED ACTIVE |

### v322j — T6 status (2026-06-11)
**T6 was ALREADY active** (flipped in an earlier session; roadmap entry was stale).
Runtime-verified via new probe: `GET /api/ai-training/confidence-gate/summary` →
`regime_suppression: {mode: active, table_loaded: true, cell_count: 111}`.
Table: 16 actionable cells → 0 SKIP, 7 REDUCE (all counter-trend-in-BULL:
vwap_fade, vwap_bounce, squeeze|short etc.). Shadow replay empty (no decision has
landed in a suppressible cell since logging began) — expected, recent regime NEUT/PULLBACK.
`scripts/t6_flip.py` = standing audit tool (--flip/--shadow --apply to toggle).
KNOWN QUIRK (benign): early-startup INFO logs from gate loaders (calibrated thresholds,
regime expectancy) are swallowed by logging-config timing — use the summary endpoint, not greps.

### v322i — Quarantine sweep (2026-06-11)
12 negative-edge gate failers flagged via `scripts/quarantine_pbo_sweep.py --apply`:
exit_timing {breakout,momentum,reversal,trend}, dp_5min_{high_vol,bear_trend},
{range,mean_reversion,reversal,trend_continuation}_5min_predictor, dp_1min_bear_trend,
scalp_1min_predictor. Flag honored at: GBM `_load_model` (exact + fallbacks),
timeseries_service reloaders ×2, LEGACY `setup_type_models` loader (r2 — gap found
post-apply: legacy collection copies bypassed the flag), ensemble meta-labeler,
confidence-gate scoring query. predict() degrades to neutral flat/0-confidence.
Promotion `$unset`s the flag (auto-rehab). Reverse: `--undo --apply`. Spared (positive
edge, fail PBO only): short_scalp_1min, dp_1min_range_bound/high_vol, gap_fill_1min —
use `--strict` to flag those too.
VERIFIED on DGX: consistency diagnostic shows 29/34 reachable, MISSING = exactly the
5 quarantined setup-family models; none of the 12 loaded at startup.
COSMETIC (backlog): consistency diagnostic lists quarantined models as "MISSING" —
could label them "QUARANTINED (intentional)" instead.

### FULL RETRAIN COMPLETE (2026-06-10 20:08 → 06-11 ~05:45 UTC, 997m, GPU)
162 models, 0 failures. **P7 Regime-Conditional 28/28 @ 56.7% — sample-count fix verified.**
P3 Vol 76.7%, P9 CNN 74.1%, P8 Ensemble 65.0%, P1 Generic 52.7%.
CPCV corpus: 79 models, median PBO 0.00, median edge +0.043. Gate calibration: defaults
(0.20/0.0) block 16/79 (20%) — exactly the overfit tail (exit_timing breakout/momentum/
reversal/trend @ PBO 0.93-1.00 negative edge, 5min setup quartet @ 0.64, marginal regime
variants). 15 shadow_blocks logged during the run. ENFORCE NOW LIVE for future promotions.
⚠ Known: several PBO-1.00 models (exit_timing family) were promoted in shadow mode and
remain ACTIVE — optional "quarantine sweep" (demote active gate-failers) on the backlog.

GPU note: XGBoost CUDA IS working on the GB10 (subprocess preflight confirmed
"AVAILABLE and WORKING"; per-model `trained on device=cuda`). The P2 "GPU-torch swap"
backlog item applies to TORCH only (torch is +cpu build) — XGBoost wheel has CUDA built in.

### Next session priorities (in order)
- 🟡 **P1**: M0 laddered server-side scale-out (multi-leg OCA) — biggest live-P&L lever.
- 🟡 **P1**: Tier 3a drift-monitor UI tile; Tier 2a per-model probability calibration.
- 🟢 **P2**: `_industry_to_etf` oddball audit (ELF mis-tagged XLE); sector-coverage UI chip.
- 🔴 SECURITY (user action): rotate Atlas MongoDB password (still pending).

## Session Summary - 2026-06-04 (chart depth + bad-tick guard shipped)

| Version | Topic | Status |
|---|---|---|
| v19.34.265 | Chart depth bump (1m=7d/5m=14d/15m=30d/1h=60d) + transient bad-tick sanitization (`_sanitize_intraday_bars` + VP lo/hi clip) | shipped + operator-verified |

Measure-first probe (`diag_chart_perf_depth.py`) proved storage (86-107d 1min,
600d+ coarser) + backend cold-load (130-521ms) already supported deep charts —
fix was purely the frontend's hardcoded shallow lookbacks. Backend optimization
+ backfill from the original plan DROPPED as unnecessary. Operator confirmed
charts "much better and faster".

### Backlog reconciliation — 2026-06-05 (verified against code, not docs)

**✅ Shipped since these were written (removed from open backlog):**
- EV Leaderboard on Mission Control — `EVLeaderboard.jsx` rendered at `MissionControlPage.jsx:231`.
- Adopted-position unrealized P&L split (backend) — `routers/sentcom.py:817` `adopted_pnl_today`.
- `hold_seconds` stamped on `bot_trades` at close — `trading_bot_service.py:1015`.
- EOD close honors trade-style — `opportunity_evaluator.py` v245 derives `close_at_eod` from style policy.

**🟡 P1 — genuinely open (verified):**
- Bot-Vitals header on Mission Control (live strip off `/api/scanner/in-play-health`) — backend exists, **no frontend consumer**.
- Mission Control sticky per-symbol search/filter across all 5 lanes — only *severity* filters exist today.
- Squeeze intraday-vs-swing `trade_style` split (handoff Issue 2) — verify-then-fix.
- ML: freshness retrain of family primaries (models ~39d stale, probe=GO); extend `retrain_readiness.py` with realized-outcome trainability budget.

**🟢 P2 — open:**
- L2 depth probe (`probe_l2_depth.py`) — script does NOT exist yet (DGX-run).
- "Why this didn't auto-trade" EV chip on MC cards (reads v294 `ev_below`/`strategy_outcomes`).
- Adopted-position P&L split **frontend chip** (backend already returns it); Gameplan prioritization-boost surfacing.
- EOD close popup modal; scanner feed group/display; regime-classifier tolerance patch; EOD operator-override toggle.
- GPU-torch swap (CUDA torch+torchvision for Spark GB10) — isolated task w/ CPU-build backup.
- Trade Journey Sparkline + Scale-Out Grade modal (~6–9h, spec below); Adoption Review UI; PnL data-drift telemetry (60s).

**🟢 P3 — open:**
- Break up `server.py` monolith; refresh AGENTS.md for SSOT architecture.
- Minors: pusher `reqAccountUpdates` 10s timeout log cleanup; APScheduler nightly auto-smart_backfill; `--reload` in start script; one-shot `ib_historical_data {bar_size:null}` junk-row delete.

**🔵 Gated (not actionable yet):**
- Realized-outcome meta-labeling layer — sample-gated (tidal_wave=0, fading_bounce=2); park until ~50–100 closed trades/canonical setup.


## Session Summary - 2026-05-22 (3 behavioral patches shipped — last $$ risks closed)

| Version | Topic | Status |
|---|---|---|
| v19.34.79 | Bracket-stacking auto-cancel endpoint + 120s ride-along on `_periodic_bracket_state_reconcile` | shipped |
| v19.34.80 | Quote-resub watchdog — verifies pusher RPC actually landed at IB, force-cycles on mismatch, escalates after 3 cycles | shipped |
| v19.34.81 | Log visibility polish — bumped watchdog ENABLED log from `logger.info` → `logger.warning` (matches AUTO-SWEEP pattern, operator log config filters services.* INFO silently) | shipped |

Backend restarted clean post-deploy. Both features verified: bracket-cancel endpoint responsive, watchdog ENABLED log appears at boot. Live-fire validation pending tomorrow's market open. Last two real-$$ risk vectors (GM/LIN-style stacking + 4.9h stale-quote bug) now have automated heal paths.

### Next session priorities
- 🟡 **P2**: Validate live-fire behavior of v79/v80 during tomorrow's market session (watch `bracket-cancel auto` and `quote-resub-watchdog NOT subscribed` log lines).
- 🐛 5-min cleanup: fix `position_reconciler.py:1197` MagicMock comparison in `test_orphan_reconciler_skips_excess_slice_v19_34_22`.
- 🟡 **P2**: UI bug cluster (Top Movers / Scanner % / Strategy Mix / Scalp SMB grade timeframe-awareness). Now armed with `quote_resub_watchdog_events` collection data to inform diagnosis.
- 🟡 **P2**: Adoption Review UI (orphan accept/reject).
- 🟡 **P2**: PnL data drift telemetry (60s catcher).

## Session Summary - 2026-05-22 (5 patches shipped — AGENTS.md context layer)

| Version | Topic | Status |
|---|---|---|
| v19.34.74 | AGENTS.md §12-17 context pack (.bat flow, glossary, DB schema, workers, taxonomy, page map) | shipped |
| v19.34.75 | AGENTS.md §6.5 user journeys + §11.5 edit checklist + CLAUDE.md pointer | shipped |
| v19.34.76 | AGENTS.md §6.5 "Why this exists" institutional-memory blurbs per journey | shipped |
| v19.34.77 | AGENTS.md §0 TL;DR (5 critical rules) + `.cursorrules` + `.github/copilot-instructions.md` | shipped |
| v19.34.78 | PRD.md cross-reference to AGENTS.md (Emergent E1 auto-load) | shipped |

AGENTS.md: 362 → 1,084 lines. Auto-loaded by 5 tools (Emergent E1, Claude Code, Cursor, Copilot, vendor-neutral). Single source of truth = `AGENTS.md`. Consolidated patch: `paste.rs/HVpaq`.

### Next session priorities (P0/P1)
- 🔴 **P0**: Bracket-stacking auto-cancel endpoint (`POST /api/trading-bot/bracket-stacking-cancel`) — GM/LIN excess-leg real $$ risk. Tie to `_periodic_bracket_state_reconcile`.
- 🔴 **P1**: Quote-resubscribe watchdog real recovery (4.9h stale quote bug — diagnose Windows pusher handler, not just RPC trigger).
- 🐛 5-min cleanup: fix `position_reconciler.py:1197` MagicMock comparison in `test_orphan_reconciler_skips_excess_slice_v19_34_22`.

## Session Summary - 2026-05-21 (6 commits shipped)

| Version | Topic | Status |
|---|---|---|
| v19.34.52  | Bar-Pipeline Phase A: pusher L1_HARD_CAP 80->500 | shipped |
| v19.34.52b | Bar-Pipeline Phase A: backend recommender 100->600 | shipped |
| v19.34.53  | env-fallback trade_type stamp on bot-fired path | shipped |
| v19.34.54  | daily_squeeze ATR-floored stop | shipped |
| v19.34.55  | broker_rejected 6-cause sub-triage | shipped |
| v19.34.56  | STALE CACHE chart banner: small pill -> full overlay | shipped |

Phase A live verification: 74 -> 402 quotes streaming post-restart.

### Pending (user action)
- Click "Collect Data" after market close (overnight). Drains 30m/1d/1w gap + 2,532 long-tail 1m/5m gap. Resolves Phase B + C together.
- Phase D verification after the drain (re-run Q2/Q4 diagnostic).

### New backlog (added this session)
- P3: reqAccountUpdates 10s timeout cleanup in pusher (log noise).
- P3: APScheduler nightly auto-smart_backfill (kills manual chore).
- P3: Backend --reload flag in spark_start.sh.
- P1 (earmarked, post-go-live): PnL Data Drift Alert (60s telemetry).

### Backlog RETIRED this session (after investigation)
- trade_2_homerun ladder dispatch register: identifier doesn't exist anywhere. Existing 6-style ladder (scalp/intraday/multi_day/swing/investment/position) already covers home-run patterns via multi_day 34%@10R, investment 40%@12R, position 50%@15R runner rungs.
- DuplicateKeyError upsert fix: both bot_trades write paths in bot_persistence.py already use upsert=True. Fix shipped earlier.

### Orphaned data-quality finding (low priority)
- 1 row in ib_historical_data with bar_size: None. Junk row from a long-ago insertion bug. One-shot cleanup: db.ib_historical_data.deleteOne({bar_size: null}).

---

## ✅ SHIPPED 2026-05-14 — Patches A (v19.34.30) + B/C/E (v19.34.31)

All four order-management cascade-prevention patches are live. See
`CHANGELOG.md` for the full v19.34.30 + v19.34.31 entries. Live state at
the end of the session:
- Services restarted clean, bot autonomous, 0 open trades, 0 IB orders
- 17 zombie DB rows swept to `closed_zombie_v30`
- 4-of-4 pytests passing across both versions
- Unique index `id_unique_v19_34_30` on `bot_trades.id` in place

### ⚠️ Live-trading observation window before next account flip

The first **live trading day after these patches** is the regression-watch
window. Run `scripts/audit_brackets.py` (committed in v19.34.30) at:
- End of session day 1
- End of session day 2

Expected:
- `Total stacked target IDs across book` ≤ open_positions
- Audit `stops` and `tgts` per symbol both ≤ 1
- DB `bot_trades.target_order_ids` max length = 1 (forever)

If any of these creep above the threshold, the next bug is hiding in a
THIRD attach-without-cancel path we haven't audited yet (candidates:
`bracket_reissue_service._reissue`, scale-out flows, EOD-close
`phantom_swept` paths in `routers/trading_bot.py`).

---



## 🟢 P2 — Trade Journey Sparkline + Scale-Out Grade (planned 2026-02-13, post v19.34.154)

Sequel to v19.34.154 scale-out tiles. Visualizes price journey through targets
and grades how well the scale-out timing captured the move.

**Locked operator preferences (2026-02-13):**
- **Grade rubric:** all three, picked via toggle in V5 settings
  - `hod_lod` — `realised / (HOD-entry × original_shares)` (penalizes leaving profit on the table)
  - `target_hit` — `targets_hit / targets_planned` (pure execution score)
  - `drawdown_adjusted` — blends HOD capture with max-drawdown-after-exit (rewards selling near peak)
- **Render trigger:** on click → full modal (Recharts) with deeper detail
- **Refresh cadence:** backend caches journey response for 30s; frontend refreshes when stale
- **Scope:** **CLOSED TRADES ONLY** — no live-update plumbing needed

**Backend (new):** `GET /api/trading-bot/trades/{trade_id}/journey`
Response includes: bars (5-min granularity), entry/stop/target levels, partial-exit markers, HOD/LOD-during-trade, all three pre-computed grades + reasoning text. Reads bars from Mongo cache only — no live IB calls per render. Server-side 30s cache keyed by trade_id.

**Frontend (new):** `<TradeJourneyModal tradeId={...} />`
Opens on click of `<ScaleOutBadge />` (existing v19.34.154 component gains a click handler + grade letter chip 🅐🅑🅒🅓). Recharts `<LineChart>` with:
- Bars as the price line
- `<ReferenceLine>` for entry + stop + each target
- `<ReferenceDot>` for each partial exit (color-coded green/amber by partial PnL sign)
- Tooltip on hover: time/price/exit detail
- Toggle (top-right): switch grade rubric live; all three grades displayed below the chart

**Effort estimate (reduced from 8-11h due to scope cuts):**
| Phase | Effort |
|---|---|
| Backend endpoint + 3 grade computations | 2-3 hrs |
| Frontend modal + Recharts wiring | 3-4 hrs |
| Edge cases (multi-day trades, stale bars, missing data) + tests | 1-2 hrs |
| **Total** | **6-9 hrs** |

**Open concerns to address during build:**
1. Bar-time vs exit-time precision mismatch (5-min bars vs sub-second exit fills) → snap markers to nearest bar
2. Multi-day swing trades → auto-collapse to 30-min or daily bars when trade spans >1 session
3. Stale-bar fallback → if Mongo cache for symbol is >5min old, render grade-only (no sparkline) with "stale bars" hint
4. After-hours bars → exclude (or gray) to keep visual clean

**Pre-existing assets to leverage:**
- `realtime_technical_service._get_intraday_bars_from_db` — 5-min bar reader
- V5 `Sparkline` primitive (`OpenPositionsV5.jsx:145`) — basic shape; will likely use Recharts for the modal
- v19.34.154 `<ScaleOutBadge />` — extension point for click handler + grade chip

**Dependencies:** none (Recharts already in package.json).

**When to build:** after the V6 UI Position Health Console / Safety Activity Stream items, OR when the operator wants post-session review tooling (CHANGELOG entry will probably bunch this with related post-mortem features).

---


## 🟢 P2 — Audit `partial_close_detected` info line (saved 2026-02-13, post v19.34.145)

After v19.34.145 fixed the false-positive KMB / ONON `QTY_MAGNITUDE_MISMATCH`,
operator asked: "can we tell from the audit at a glance whether a row is a
scaled-out winner vs phantom shares?" Yes — and it should be a *positive*
signal in the audit response (not an alarm).

### Scope
For every bot row where `shares != remaining_shares` (i.e. a partial close
has already fired), surface a soft info field in the audit row:

```json
{
  "verdict": "OK",
  "partial_close_detected": {
    "original_shares": 144,
    "remaining_shares": 55,
    "closed_shares": 89,
    "pct_remaining": 38.2
  }
}
```

And add a non-alarm action line that summarises the session's peel activity:
"5 position(s) have partial scale-outs already fired this session: KMB
(89/144 closed), ONON (176/235 closed), …".

### Implementation hint
Read `r.get("shares")` AND `r.get("remaining_shares")` in
`routers/diagnostic_router.py::position_pnl_audit` (the audit endpoint
already has both — see the bot-row branch). When they differ, attach
the `partial_close_detected` block to the corresponding row in
`rows[]`. Tests: extend
`tests/test_position_pnl_audit_v19_34_142.py::TestPartialCloseQtyResolution`
with a `test_partial_close_detected_attached_when_shares_differ` case.

### Why P2 and not P0/P1
The actual bug (false NAKED alarm + overstated PnL) is fixed in v19.34.145.
This is a UX polish that makes the audit *easier to read* but doesn't
change behavior. Pick it up when V6 UI work calls for a "partial
scale-out" badge or chip — likely the same diff.

---



## 🟢 NEXT — Root-cause the KMB fragment double-book (saved 2026-02-13, post v19.34.143)

`v19.34.142e` now surfaces `ledger_fragments[]` on every magnitude
mismatch, so the **next live audit run will tell us** which slices
combined to overshoot IB (e.g. entry-slice `t-abc` 55sh +
`reconciled_excess_v19_34_15b` slice `t-xyz` 89sh = 144sh ledger
vs 55sh at IB). Once observed, decide between:

1. **Auto-collapse** — when audit detects same-direction siblings
   summing to more than IB qty, fire `_consolidate_one_group`
   targeting **`min(sum, ib_qty)`** instead of `sum`. Currently
   `position_consolidator.py:273` uses `g["proposed_total_shares"]`
   = sum of fragment `remaining_shares`. If that sum exceeds the
   real IB qty, we're double-booking; clamping to IB qty + reflowing
   the smallest fragment's `remaining_shares` to zero is the fix.
2. **Block the merge** — refuse to consolidate when sum > IB qty
   and require operator to flatten or reconcile share-drift first.

### Next debug step (when operator next runs the live audit)
Capture the `ledger_fragments[]` for the offending symbol →
identify the older fragment whose `remaining_shares` never decremented
on a partial-close → patch the close path in `position_manager.py`
that mutates `remaining_shares -= shares_to_sell` (line ~1374) to also
zero out drained fragments before the consolidator next runs.

---




## ✅ 2026-02-12 — v19.34.127 SHIPPED — Naked-position sweep + consolidator audit trail

**The actual -$25k bug is now fixed.** Yesterday's diagnostic proved IB independently cancelled 100+ of our stops at 11:21 and 15:29; our code had no detection path for IB-initiated cancellations. New `_naked_position_sweep` runs every 60s inside the already-alive kill-switch monitor: pulls IB's live order book, cross-references against every `trade.stop_order_id` in `_open_trades`, emergency-reissues any missing stop via `attach_oca_stop_target`, and writes `phase: "naked_sweep_reissue"` to `bracket_lifecycle_events`. Consolidator merges now also persist `phase: "consolidator_merge_reissue"`. 11 new pytest cases + 67 regression tests pass.

After this ships, an IB-cancelled stop is detected within 60 seconds, a fresh OCA is queued, and the event is audit-logged. Yesterday's silent-naked failure mode is closed.

---



## ✅ 2026-02-12 — v19.34.125 SHIPPED — Bracket-lifecycle diagnostic schema fix + kill-switch heartbeat

Operator restarted after v19.34.124, ran the verification runbook, and reported all three diagnostic outputs were empty/silent on the -$25k incident day. Root-caused and patched:

- **`/api/diagnostic/bracket-lifecycle`** queried a non-existent `ts` string field while the writer stamps `created_at` (BSON datetime). Result: every query silently returned `0 events`. Endpoint rewritten to match the actual writer schema (see CHANGELOG for full classification map). New `naked_positions` array surfaces the catastrophic cancel-OK-submit-FAIL state. Response now includes `collection_total_docs` + `collection_latest_event` for fast triage.
- **Kill-switch monitor invisible to `grep`**: added a periodic INFO heartbeat (every ~4 min) so the operator can confirm the background task is alive on quiet days.
- **`/setup-winrate-breakdown`** empty is expected — the v124 `alert_outcomes` writer was wired the same day and needs 1-3 sessions to accumulate. Documented; no code change.

5 new pytest cases + 58 regression tests pass. **Next**: P0 — Bracket re-issue on consolidator merge (Issue #3 from v121 post-mortem still pending).

---


## 🟢 P2 — Symbol life-cycle drift detector (saved 2026-02-13)

Now that `v19.34.140` makes mega-cap names immune to unqualifiable
promotion, the strike counter on **non**-mega-cap names becomes a
clean signal for genuine symbol life-cycle events — delisting,
ticker renames, mergers, halts. Currently we silently nuke at the
threshold and only find out weeks later when the bot stops scanning
the symbol.

### Scope
- New service path inside `services/symbol_universe.py::mark_unqualifiable`:
  on every `$inc unqualifiable_failure_count`, emit a soft alert
  (chat-channel / push notification) once the count crosses
  `STRIKE_NUDGE_THRESHOLD` (e.g. ceil(effective_threshold * 0.6)).
- Format: `📉 {SYMBOL} accumulating unqualifiable strikes:
  {count}/{effective_threshold} — reason="{last_reason}". Likely
  delisted / renamed / halted. Review before next session.`
- De-dupe via a `last_nudge_at` field on the cache doc — fire ONCE
  per symbol per (calendar day OR pre-promotion event), whichever
  comes first.
- Skip nudges entirely for mega-cap (immunity catches those).

### Why
- Catches life-cycle events 1–4 sessions BEFORE the symbol gets
  silently promoted to unqualifiable. Operator has time to verify
  on IB / news / earnings calendar and decide:
  - Real life-cycle event → confirm + remove from any custom
    watchlist; relax (the system will eventually drop it).
  - Transient IB issue → run `/clear-unqualifiable` proactively
    BEFORE it gets promoted, so there's never a coverage gap.
- Cleanly separates "transient IB error" from "real corporate
  action" without requiring an EDGAR / news-feed integration.
- Zero false-positive risk: nudge is informational; doesn't change
  any system behavior.

### Acceptance
- One nudge per symbol per day max.
- Mega-cap names produce ZERO nudges.
- Non-mega-cap names produce a nudge at `60%` of effective threshold.
- Test: hammer a non-mega-cap name with `floor(0.6 × effective) - 1`
  strikes → no nudge. One more strike → exactly one nudge fires.
  Hammer 20 more strikes same day → no additional nudges.

### Channel
- Pipe through the existing `live_alerts` push pipe used by the
  scanner-coverage UI panel. No new integration needed.

---


## 🟢 P2 — Session-color background tints on trade timestamps (saved 2026-02-13)

Now that every operator-facing timestamp renders with a ` ET` suffix
(v19.34.137), layer **session-context color tints** behind each rendered
time so a quick visual scan instantly tells you which session the event
occurred in:

- `04:00 – 09:30 ET` → pre-market (blue tint, e.g. `bg-sky-500/8`)
- `09:30 – 16:00 ET` → RTH (gold tint, e.g. `bg-amber-500/8`)
- `16:00 – 20:00 ET` → after-hours (gray tint, e.g. `bg-zinc-500/12`)
- `20:00 – 04:00 ET` → overnight (deep violet tint, e.g. `bg-violet-500/8`)

### Scope
- Primary site: `components/sentcom/v5/pipelineStageColumns.jsx`
  (the audit / open-positions / drill-down row time column).
- Secondary: `BracketHistoryPanel.jsx`, `UnifiedStreamV5.jsx` time column.
- Reuse a tiny helper `sessionForET(date) → 'pre'|'rth'|'ah'|'on'` from
  `utils/timeET.js` keyed off the same ET formatter we already use.

### Why
- Operator scanning the audit log for "did this fill happen in RTH or
  AH?" gets the answer at a glance — no parsing of HH:MM required.
- Solves a recurring forensic question without adding a new column.
- 30-line CSS-only add; zero backend change; bundle impact ~< 200 B.

### Acceptance
- Helper in `utils/timeET.js`; one tailwind class lookup per time cell.
- Pre-market / RTH / AH / overnight tints distinguishable on the dark
  theme (4-stop palette, low-saturation so the time text stays readable).
- Pure date-only labels stay un-tinted.

---



## 🟢 P2 — Proactive teammate-voice notifications for cap downsizing (saved 2026-05-12)

When a trade gets auto-downsized by the 30% / 55% exposure caps, emit a chat-style nudge into the V5 activity feed (not just a passive log entry). Uses the existing `exposure_cap_warnings` array attached to BotTrade. Example: "Hey, our 55% long-horizon cap is tight — I downsized AAPL from 200 → 80 shares. Want me to scale out NVDA position trade to free room for full size?"
- Estimated effort: ~30 min frontend + ~15 min backend to push to the activity stream
- Engagement bump: turns silent risk decisions into conversational teamwork moments



## 🟢 P2 — Trade-style click-filter on V5/V6 surfaces (saved 2026-05-12)

Now that v19.34.99 stamped every row with a `data-trade-style` attribute via `TradeStyleChip`, build a one-click filter:
- Clicking the chip in any panel (LiveAlertsPanel / OpenPositionsV5 / ScannerCardsV5) filters that panel to rows of the same style.
- Shift-click toggles multiple styles (e.g. "swing + position" only).
- Filter state persists in URL hash so links into the dashboard preserve the view.
- Estimated effort: ~15 min frontend, zero backend changes (chip attribute already in place).
- Compounding benefit: when 8+ live trades across horizons, operator can isolate "only my multi-month bets" instantly.



## ✅ 2026-05-12 — v19.34.81 / .82 SHIPPED — Singular-target detection + force-reconcile-down

**v19.34.81** — `attach-brackets-to-unprotected` was producing false-positive "unprotected" rows for every trade brackeded via `attach_oca_stop_target` (which writes the **singular** `target_order_id`), because the v19.34.76 logic only checked the plural `target_order_ids` list. Patched to recognize both. Without this fix, applying the dry-run output would have stacked duplicate target legs — recreating the exact problem v19.34.79 sealed. Regression test: `test_singular_target_order_id_is_recognized_as_bracketed`.

**v19.34.82** — `POST /api/trading-bot/force-reconcile-down` — operator escape hatch for the OPPOSITE side of state divergence: bot over-tracks vs IB (PEP 2266 bot vs 971 IB after kill-switch carryover). Existing reconcilers only resolved "IB > bot"; this is the missing "bot > IB" half. Walks `_open_trades` FIFO and shrinks `shares`/`remaining_shares` until total = `target_qty`. Optional `target_qty` falls back to `|IB pushed qty|`. NEVER sends a broker order. Persists touched trades. Emits one `share_drift_events` audit row per call (`event=force_reconcile_down_v19_34_82`). 8 pytest cases incl. broker-never-called assertion.

Endpoint smoke-tested live against `/openapi.json`. **User: Save to Github → `git pull` on DGX → restart backend.** Then run the runbook below to clean up PEP / ADBE / any other over-tracked symbol.

### Runbook (paste into terminal after deploying)

```bash
# 1) Set DGX target (skip if already set).
export DGX="http://localhost:8001"

# 2) DRY-RUN: see what attach-brackets-to-unprotected would do now that
#    the singular-target false positives are gone.
curl -s -X POST "$DGX/api/trading-bot/attach-brackets-to-unprotected" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}' | python3 -m json.tool

# 3) DRY-RUN force-reconcile-down for each over-tracked symbol. Omit
#    target_qty to let the endpoint query IB pushed positions live.
curl -s -X POST "$DGX/api/trading-bot/force-reconcile-down" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "PEP", "dry_run": true, "reason": "post-kill-switch carryover"}' \
  | python3 -m json.tool

curl -s -X POST "$DGX/api/trading-bot/force-reconcile-down" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "ADBE", "dry_run": true, "reason": "post-kill-switch carryover"}' \
  | python3 -m json.tool

# 4) APPLY (flip dry_run to false) once the plans look correct.
curl -s -X POST "$DGX/api/trading-bot/force-reconcile-down" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "PEP", "dry_run": false, "reason": "post-kill-switch carryover"}' \
  | python3 -m json.tool

curl -s -X POST "$DGX/api/trading-bot/force-reconcile-down" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "ADBE", "dry_run": false, "reason": "post-kill-switch carryover"}' \
  | python3 -m json.tool

# 5) APPLY attach-brackets-to-unprotected (now safe — singular-target
#    false positives are gone).
curl -s -X POST "$DGX/api/trading-bot/attach-brackets-to-unprotected" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}' | python3 -m json.tool
```




## ✅ 2026-05-12 — v19.34.80 SHIPPED — Cancel-excess-bracket-legs endpoint

Operator-triggered companion to v19.34.77 audit (read-only) and v19.34.79 sibling-sweep (seals the leak going forward). `POST /api/trading-bot/cancel-excess-bracket-legs` picks ONE bracket pair to keep per symbol and cancels the rest via the same `cancel_order` primitive used by `_grow_existing_excess_slice` and `cancel-all-pending-orders`. Decision strategy: keep_oca_group > keep_order_ids > canonical_slice > newest fallback. Dry-run default. 10 pytest cases including pusher-only graceful failure. Full 165-test safety suite green. **User: Save to Github → `git pull` on DGX → restart backend.**



## ✅ 2026-05-12 — v19.34.78 / .79 SHIPPED — Zombie pending cleanup + bracket-stacking ROOT CAUSE fix

**v19.34.78** — Stale-PENDING zombies (NBIS/MU/COIN-style "pending trade exists" 7+ min apart) traced to v19.34.6 pre-submit save → boot reload cycle. Boot-time filter in `bot_persistence.py` prunes PENDINGs older than `STALE_PENDING_TTL_S` (default 30 min); operator escape-hatch `POST /api/trading-bot/clear-stale-pending-trades` for live cleanup without restart. 7 pytest cases.

**v19.34.79** — Bracket-stacking ROOT CAUSE identified and fixed in `_grow_existing_excess_slice`: was only cancelling canonical slice's bracket, leaving sibling BotTrades' brackets alive at IB (ADBE 4x stacking, GM 12x stacking on 2026-05-12). Now sweeps siblings for the same (symbol, direction) and cancels their brackets too. 6 pytest cases incl. opposing-direction safety, different-symbol isolation, exception-resilience.

Full 155-test safety suite green. **User: Save to Github → `git pull` on DGX → restart backend.** After restart: run audit, then clear-stale-pending, then attach-brackets-to-unprotected.



## ✅ 2026-05-12 — v19.34.76 / .77 SHIPPED — Retroactive bracket attach + stacking audit

Forensic audit of TWS this morning revealed BMNR (658sh, $15k) carrying naked at IB (no stop) AND systemic bracket-stacking on every scale-in (ADBE 80sh long had 320sh of pending stops; EFA 963sh long had 2,888sh; GM 109sh long had 1,282sh).

**v19.34.76** — `POST /api/trading-bot/attach-brackets-to-unprotected` retroactively attaches OCA stop+target to any unbracketed open trade. Dry-run by default. 9 pytest cases.

**v19.34.77** — `GET /api/trading-bot/bracket-stacking-audit` read-only diagnostic surfacing symbols with `pending_stop_qty > position_qty`. Auto-cancel of excess legs deferred to v19.34.78 pending operator-verified diagnosis.

Full 142-test safety suite green. **User: Save to Github → `git pull` on DGX → restart backend; then run the runbook in CHANGELOG.md to safely re-arm BMNR.**

### 🔴 P0 — v19.34.78 follow-up needed

The bracket-stacking ROOT CAUSE is unidentified — the audit endpoint surfaces the symptom, but we don't yet know which code path is emitting redundant stops on each scale-in. Top suspects: (a) `bracket_reissue_service` not cancelling old legs before posting new; (b) `position_reconciler.attach_oca_stop_target` being re-fired for the same trade across scans; (c) scale-in code creating a fresh BotTrade per fill instead of resizing existing. Needs forensic deep-dive against the TWS order log before writing the auto-cancel endpoint.



## 🔥 OPEN BACKLOG — pinned 2026-05-11 (refreshed)

All P0 + the 3 P1 items pinned earlier are now SHIPPED — see v19.34.71/.72/.73/.74/.75 below.

### 🟢 P2 — Live cooldown HUD chip (operator-suggested 2026-05-11)

Surface active rejection cooldowns as small chips in the V6 status strip — e.g., `🧊 NBIS cooldown 3:42`. Source: `GET /api/trading-bot/rejection-cooldowns`. Would have caught today's NBIS thrashing within 30s instead of 70+ minutes. Pair with `🛑 NBIS operator-flatten` chips sourced from `GET /api/safety/operator-flatten-suppression` (v19.34.72) so the operator sees BOTH gate types at a glance. Cheap to add once V6 Plan A panel extraction begins.

### 🟢 P2 — Unified Safety Activity Stream panel (operator-suggested 2026-05-11)

Full spec: **`/app/memory/V6_SAFETY_ACTIVITY_STREAM_SPEC.md`** (queued behind V6 Plan A panel extraction).

Three independent safety ledgers now exist: rejection cooldowns, operator-flatten suppression, drift-guard skips — plus kill-switch-gate refusals and safety_guardrail vetoes. Operator currently has to fuse three streams to answer "why didn't the bot trade NBIS just now?" Unified panel = one feed, chronological, with metadata + one-click clear actions. Backend aggregator (~50 LOC) + V6 right-sidebar component (~200 LOC). Three-phase rollout. Subsumes the simpler "cooldown HUD chip" item above — pick one or the other.

### 🟢 P2 — Position Health Console panel (operator-suggested 2026-05-12)

Full spec: **`/app/memory/V6_POSITION_HEALTH_CONSOLE_SPEC.md`** (queued alongside Safety Activity Stream).

Single V6 right-sidebar panel that polls `bracket-stacking-audit` every 30s, shows one row per tracked symbol with traffic-light state (CLEAN, UNPROTECTED, STACKED, STACKED-HIGH, ZOMBIE PENDING, drift variants), and exposes inline buttons for each remediation. Reuses 100% of today's shipped endpoints (`audit`, `cancel-excess-bracket-legs`, `attach-brackets-to-unprotected`, `clear-stale-pending-trades`) — **zero new backend code**, ~250 LOC frontend.

Operator value: answers "Am I safe right now?" in one glance. Today's full unwind sequence (audit → cancel-excess on 3 symbols → attach-brackets on BMNR) collapses to four clicks. Would catch this whole class of issues live instead of as a post-mortem.

**Build order recommendation in the spec**: ship Position Health Console first (Phase 1+2 = 1.5 days), then Safety Activity Stream (3 days). Position Health is more frequently consulted and reuses more existing code.

### 🟡 P1 — V6 UI migration (Plan A)

V6 spec is locked at `/app/memory/V6_NEXT_LOCKED_SPEC.md`. Unblocked now that the P0/P1 backend fires are extinguished. Three phases:
- Phase A — Extract V5 panels into pure reusable components (no behavior change)
- Phase B — V6 shell + 5-column grid + new positions + thinking panes wired to live data
- Phase C — Migrate remainder + chat drawer + retire V5 (1-week parallel run)

### 🟢 P2/P3 — Original backlog (carried forward)
- Tick-level Stop Run Probability ML module
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics service
- Liquidity-aware trail in `stop_manager.py`
- Chart bubble click → fire focus symbol
- SEC EDGAR 8-K integration


## ✅ 2026-05-11 — v19.34.71 / .72 / .73 / .74 / .75 SHIPPED — Drift gates, operator-flatten, panel truth-source

Five tightly-coupled patches closing out the P0 + 3×P1 list pinned this morning:

**v19.34.71** — Two-tick external-close confirmation. Single-tick races (NBIS phantom -$326) no longer trip the reconciler's `external_close` accounting event. Wired into both zero and partial drift cases. 7 pytest cases.

**v19.34.72** — Operator-flatten detector + per-session re-entry suppression. New module `services/operator_flatten_suppression.py` + endpoints `GET/POST /api/safety/(clear-)operator-flatten-suppression`. Trades tagged `close_reason="operator_external_flatten"`; subsequent entries on the symbol skipped with `close_reason="operator_flatten_suppression"`. 9 pytest cases.

**v19.34.73** — Health-monitor pusher-aware IB-gateway probe. `/api/risk/health/quick-status` no longer reports false "IB Gateway not connected" on DGX pusher-only deploys. 5 pytest cases.

**v19.34.74** — `max_position_pct` truth-source reconciliation. `/api/trading-bot/status` now overlays the canonical value from `PositionSizerService.config` (default 10%) over the legacy `TradingRiskParams` default (50%). Original value preserved as `max_position_pct_legacy` for forensics.

**v19.34.75** — Strategy-mix unconditional fallback. `GET /api/scanner/strategy-mix` now tries DB + enhanced_scanner in-memory alerts even when the legacy predictive `_scanner_service` is None. Fixes "waiting for first alerts" stuck-state.

**21 new pytest cases**, full 133-test safety/cooldown/drift suite green. **User must Save to Github → `git pull` on DGX → restart backend.**


- Break up `server.py` monolith (extract `bracket_router.py`)



## ✅ 2026-05-11 — v19.34.70 SHIPPED — NBIS symbol-exposure-saturated cooldown

Operator-observed 2026-05-11: bot fragmented NBIS into many small fills, hitting per-symbol exposure cap, retrying with smaller sizes, looping every ~30-60s. Sizer's cap-saturated branch was producing `shares=0` with reason `position_size_zero` — which is NOT structural, so rejection cooldown never engaged.

Fix: new distinct reason code `symbol_exposure_saturated`. Sizer tags the branch via `multipliers_out`; caller emits the new reason code and directly calls `rejection_cooldown.mark_rejection(...)`. Reason added to `STRUCTURAL_REJECTION_REASONS` (default cooldown 5 min, extends on repeat). New narrative branch emits "🧊 Cooling off on NBIS breakout — exposure $14,800 hit $15,000 cap" so Bot's Brain panel isn't silent.

5 new pytest cases in `tests/test_v19_34_70_symbol_exposure_saturated_cooldown.py`. Full 112-test safety/cooldown suite green. **User must Save to Github → pull on DGX → restart backend.**



## ✅ 2026-05-11 — v19.34.69 SHIPPED — BMNR P-1 kill-switch bypass sealed

Operator manually tripped kill switch at 2026-05-11 14:14:34 UTC; bot still opened BMNR. Forensic audit found `agents/trade_executor_agent.py::_execute_order` was importing `services.order_queue_service` directly and calling `.queue_order(...)` on the service, bypassing the only chokepoint (`routers/ib._kill_switch_gate`).

Fix: pushed the gate decision into `services/kill_switch_gate.py` (shared module) and wired it into `OrderQueueService.queue_order()` itself. Every present and future order producer is now gated at the absolute lowest layer. Routers-level gate retained for redundancy + observability.

6 new pytest regressions in `tests/test_v19_34_69_service_layer_kill_switch_gate.py` (incl. exact BMNR-shaped agent payload). All 107 kill-switch tests across 8 files pass. **User must Save to Github → pull on DGX → restart backend.**



## 🔒 2026-02-09 — V6.next++ UI SPEC LOCKED

User approved final mockup at `?preview=v6mock`. Spec frozen at `/app/memory/V6_NEXT_LOCKED_SPEC.md`.

**Locked concepts:** ①②③④⑤⑦⑧ (heartbeat, risk rail, sparklines, glass+halo, vibe tints, time scrubber, provenance ring). **Skipped:** ⑥ pipeline particles.

**Locked enhancements A–J:** trigger progress, SL→PT proximity, mini-arc, action bar, narrative strip, AI chat drawer, aggregate P&L sparkline, change-detector, conditional sparklines, colorblind icons.

**Migration plan: 3 phases (Plan A)**
- Phase A — Extract V5 panels into pure reusable components (no behavior change)
- Phase B — V6 shell + 5-column grid + new positions + thinking panes wired to live data
- Phase C — Migrate remainder + chat drawer + retire V5 (1-week parallel run)

**New backend endpoints required** for state machine, proximity, aggregate P&L, trigger progress, narrative — listed in spec §7.

Next action: kick off Phase A (panel extraction) once user gives green light.



## ✅ 2026-02-09 — v19.34.66 SHIPPED — Boot-time orphan-GTC reconciler (3 layers)

The long-missing audit pass. Triggered by tonight's discovery that the operator had 10 GTC sell-side bracket legs from 5/4 sitting at IB after multiple bot restarts — bot had completely lost track. Every prior reconciler started from the bot's view of the world; none ever asked "what does IB still have that the bot has forgotten about?".

Three layers, one classifier, one fail-closed cancellation gate:
- Boot tripwire — `_startup_orphan_gtc_audit()` at +25s after start
- Periodic reconciler — `_periodic_orphan_gtc_audit()` every 120s
- Operator dashboard — `GET /api/safety/orphan-gtc-orders` + `POST /api/safety/cancel-orphan-gtc`

Verdicts: `tracked`, `naked_no_position` ✓, `orphan_no_trade` ✓, `mismatched_size`, `awaiting_data`. Only the two ✓ verdicts are auto-cancellable; the others demand operator review.

15 new pytest cases including full forensic replay of 2026-05-04 event (NXPI, VALE×2, NCLH, ELV — all 10 classified `naked_no_position`). Live smoke test against running backend confirmed all three guards (audit failure envelope, wrong-confirm 400, IB-offline 503).

Companion audit document at `/app/memory/CHANGELOG_v19_34_66_audit.md` confirms no overlap or staleness in existing reconcilers; identifies fill-tape reconciliation as the only remaining (P2) blind spot.

**Pending operator review** — kill switch still under operator manual control.



## ✅ 2026-02-09 — v19.34.65 SHIPPED — Order-router idempotency + bracket-reissue throttle

Shipped Fix A (broad symbol-level entry cooldown, 60s, ignores side/qty/price) + Fix B (bracket re-issue throttle, 1 per (symbol, 5min) + hard remaining_shares > 0 guard) in a single patch. Targets the four bug patterns surfaced in the 2026-02-08 IB trade-log forensic: ADBE 18-buy ramp, DDOG/SQQQ wash cycles, EWY re-entry into manual flatten, EFA fragmented re-entry churn.

The 11:42 EFA 892+67 venue split was assessed as normal IB Smart Order Router behaviour (not a bug); Fix C (chunk dedup) was dropped from this patch as YAGNI.

15 new pytest cases + 32 updated bracket-reissue cases all green (101/101 affected suites pass). Kill switch under operator manual control throughout.

**Pending operator review** before tackling Issue 3 (operator-flatten detector).



## ✅ 2026-02-09 — v19.34.59 SHIPPED — Zombie sweep + boot tripwire + diagnostic endpoint

After 9 zombie BotTrades surfaced post-restart (status=OPEN, remaining_shares=0, IB still had real shares), three fixes shipped:
- Frontend: `OpenPositionsV5` aggregator now prefers `remaining_shares` so zombies render as 0sh (no more `1252sh COIN (2×)` while bot tracking 0).
- Backend: `[v19.34.59 ZOMBIE-LOAD]` ERROR log on boot for every zombie loaded; instance tagged with `_loaded_as_zombie_v19_34_59` for traceability.
- Operator surface: new `GET /api/trading-bot/zombie-trades` + `scripts/zombie_sweep_v19_34_59.sh` (one-shot heal via existing reconcile endpoint, no env-flag flip + restart needed).

84/84 reconciler/safety/boot pytests passing. Open question for next session: still need to find the upstream code path that created these zombies in the first place. The boot tripwire's grep hint will produce evidence in the logs.



## ✅ 2026-02-09 — v19.34.56 + v19.34.57 + v19.34.58 SHIPPED — UX polish + boot stability + flap detection

- **v19.34.56**: `OpenPositionsV5` self-defuses the loading state after 3s when the parent feed is empty (no more pre-market "Loading positions…" stuck banners).
- **v19.34.57**: Pusher rotation service waits 2s before its first cycle and retries once on `pusher_unreachable` — eliminates noisy `subscribe_symbols socket-read timeout` boot tracebacks.
- **v19.34.58**: IB-direct (clientId=11) heartbeat ping every 30s with 5s deadline. Detects half-open / silently broken sockets that `disconnectedEvent` cannot. Heartbeat metrics surfaced in `/api/system/ib-direct/status` → `stability`. New `scripts/analyze_ib_direct_flap_v19_34_58.sh` mines logs for drop intervals + groups reasons + flags bursty (<60s) flap windows. Bracket-attach audit script extended with verdict line.

**Cumulative reconciler/safety/boot suite: 78/78 pytests passing.**



## ✅ 2026-02-XX — v19.34.54 + v19.34.55 SHIPPED — Stabilization & Observability

- **v19.34.54**: IB-direct (clientId=11) watchdog with auto-reconnect + drop/reconnect counters. Eliminates the recurring manual reconnect dance. 6 new pytests.
- **v19.34.55**: Drift-guard saves status pill in V5 HUD. Surfaces v19.34.52's prevented phantom-closes for at-a-glance observability. New `/api/trading-bot/drift-guard-stats` endpoint + `DriftGuardPill.jsx` with hover tooltip showing last 8 saves.

59/59 reconciler/safety pytests passing. UI build clean.

## 🟡 (P1) Weekly Safety-Net Dashboard (idea logged 2026-02-XX after v19.34.55)

Now that we capture rich save-event data (`recent_skips` per day, `recent_resolves`, `stability` block on IB-direct), feed that into a weekly dashboard quantifying invisible safety work:
- **Drift saves vs total drift events** — % of "would-have-been phantom-close" prevented
- **Bracket reissue success rate** — entry-time vs reissue, broken out by kill-switch state
- **IB-direct uptime %** + drop/reconnect counts
- **Money-saved estimate per phantom-close blocked** — using avg position size × avg same-day price-to-stop distance × commission round-trip
- Roll up over week / month with a sparkline
- Endpoint: `GET /api/trading-bot/safety-net-weekly`
- UI: a small sub-panel (collapsible) under the SentCom HUD or as a dedicated tab; stable footer line "🛡 Saved $X this week (Y events)" as the persistent hook
- Eventually: alert if save rate drops AND bug rate rises (would indicate a regression masking new bugs)

Why it matters: turns the guardrail layer from invisible cost-center into a quantified ROI story. Useful when reviewing whether to keep complex safety code in 6 months.

## ✅ 2026-02-XX — v19.34.52 + v19.34.53 SHIPPED — Mid-Session Crisis Fix Pack

Two interlocking P0 bugs fixed live during the 2026-05-08 open incident:
- **v19.34.52**: drift reconciler phantom-close (mirrors v19.34.49 in `position_reconciler` instead of `position_manager`). Multi-source confirmation guard prevents Case 2/3 from acting on stale pusher data.
- **v19.34.53**: kill-switch chokepoint was refusing legitimate `REISSUE-*` brackets. Hardened detection (oca_group, order_type, substring scan) + producer-side intent tagging.

54/54 reconciler/safety pytests passing. See CHANGELOG.md for full timeline.

**Outstanding from incident — operator follow-ups (no code change needed):**
- Investigate WHY entry-time `attach_oca_stop_target` didn't attach brackets in the first place for ADBE/BKNG/LIN. Suspect: original entries fired during pre-open window when kill-switch was off → bracket attach succeeded → but something orphaned them. Hunt: `grep "attach_oca\|place_bracket" /tmp/backend.log` after market close + correlate timestamps with the seven `external_close_v19_34_15b` events that tore them off.

## ✅ 2026-02-XX — v19.34.50 SHIPPED — `bot_q` zero-side detection blind-spot

Drift reconciler now detects the `(bot_q ≈ 0, zombies == 0, ib_q ≥ 1)` corner case (paired hedges; tracked-but-zero edges) and routes to `_spawn_excess_slice` so unmanaged IB shares get bracketed. 7 new pytest cases (cumulative reconciler/safety suite 31/31 passing). See CHANGELOG.md.

## ✅ 2026-02-XX — BUGS 2 & 3 SHIPPED (v19.34.48 + v19.34.49) — Bot Cleared for Re-Enable

Both P0s fixed and pinned by 13 new pytest cases (39 cumulative passing across the session). See CHANGELOG.md for full detail. Smoke-test checklist included there for the operator before re-arming the bot.

## 🟡 2026-02-XX — REMAINING BACKLOG (post-BMNR session)



**Where:** `services/position_manager.py::close_trade` → `_clamp_shares_to_ib_position` (added in v19.34.27 to handle PG-style leftover sweeps).

**Symptom:** "FLATTEN COMPLETE 20/20" modal even though IB pusher logs show every close MKT was rejected with `IB Error 201`. 0 actual fills. Operator believed they were flat, BMNR + PG were still real at IB.

**Root cause hypothesis:** When the clamp's IB-direct `get_positions()` returns `[]` (empty — could be: IB direct just connected, no position events yet, or a clientId-segregation artifact), the clamp returns 0 → `close_trade` enters the phantom-recovery path → marks the trade CLOSED locally with reason `*_phantom_recovery_v19_34_27` and returns True without ever calling `executor.close_position()`. Real IB position untouched.

**Right fix:** Phantom recovery must require POSITIVE multi-source agreement that the position is empty:
- Direct IB `get_positions()` returns 0 for this symbol AND snapshot age < 5s (track via timestamp on cache write), AND
- Pusher's `_pushed_ib_data["positions"]` agrees (cross-check), OR pusher is dead and operator explicitly opted into phantom-recovery via a flag

If unable to confirm with at least one fresh source → fall back to bot-tracked count and submit the close MKT for real (current pre-v19.34.27 behavior).

**Test plan:**
- Mock direct IB returning `[]` while bot tracks 100 sh BMNR → close_trade must NOT phantom-recover; must call executor.
- Mock direct IB returning `[{symbol: "BMNR", position: 0}]` with snapshot fresh → SHOULD phantom-recover (position confirmed gone).
- Mock direct IB returning stale snapshot (>5s old) showing 0 → must NOT phantom-recover.

**Files of reference:**
- `/app/backend/services/position_manager.py:1290-1396` — `_clamp_shares_to_ib_position`
- `/app/backend/services/position_manager.py:1463-1481` — phantom recovery branch
- `/app/backend/services/ib_direct_service.py:250-270` — `get_positions` (need to add staleness tracking)

---

### 🔴 P0 — Bug 3: Kill switch is leaking — bot enters trades while tripped

**Where:** Unknown — probably the proactive coach loop, scanner re-trigger path, or a side-effect of drift reconciliation.

**Symptom:** Operator tripped kill switch at ~1:00 PM on 2026-05-07. IB order log shows the bot then bought:
- 1:32 PM: 293 sh PG @ 147.22
- 1:34 PM: 167 sh PG @ 147.29
- 1:34 PM: NEW Sell 460 PG OCA bracket submitted (Limit 154.72 + Stop 144.22)
- 2:02 PM: 95 sh PG @ 146.61

That's 555 sh of PG entered AND a fresh bracket placed UNDER A TRIPPED KILL SWITCH. The bot believed it was halted; IB shows otherwise.

**Investigation steps:**
1. `git log --oneline services/safety_guardrails.py services/proactive_coach_service.py services/sentcom_service.py` — look for entry paths that don't check `kill_switch_active`.
2. `grep -rn "place_bracket\|enter_trade\|queue_order" /app/backend/services/` — find every entry codepath.
3. Cross-reference: which of these check `safety_guardrails.kill_switch_active` BEFORE submitting?
4. Likely suspects: (a) proactive coach auto-suggest → user-action handler doesn't gate on kill switch, OR (b) drift reconciler's `_spawn_excess_slice` placing OCA brackets via `attach_oca_stop_target` even when kill is active (but this would only affect symbols that already exist at IB, not net-new PG buys), OR (c) scanner's auto-trigger setup re-firing because the SQUEEZE setup eligibility check doesn't include kill-switch.

**Right fix:** A SINGLE `_can_enter()` gate in `trade_executor_service.py::place_bracket_order` (or wherever the lowest-common-denominator entry primitive is) that checks `safety_guardrails.kill_switch_active` and refuses with a logged + streamed warning. Every entry path must funnel through this gate; no shortcuts.

**Test plan:**
- With `safety_guardrails.kill_switch_active=True`, simulate a SQUEEZE signal firing → assert `place_bracket_order` returns failure + the order is NEVER queued.
- Same for the proactive coach's auto-trade path (if it has one).
- Regression: running the drift reconciler with kill switch active should NOT place new OCA brackets on excess slices; it should just log the drift and wait for operator.

**Files of reference:**
- `/app/backend/services/safety_guardrails.py` — kill switch state
- `/app/backend/services/trade_executor_service.py:129` — `_kill_switch_refusal` (only used in one path; needs to be in all)
- `/app/backend/services/proactive_coach_service.py` — newly added; may have unguarded entry path
- `/app/backend/services/sentcom_service.py` — scanner trigger path

---

## ✅ 2026-02-XX — v19.34.43–47 SHIPPED — Flatten Hardening Marathon

Five-patch session resolving the cascade of issues that surfaced during BMNR cleanup:
- **v19.34.43**: parallel close loop (`asyncio.gather` + Semaphore(8)), 90s FE timeout, error-surfacing modal.
- **v19.34.44**: group flatten by (symbol, direction); pre-cancel zombie working orders via direct IB.
- **v19.34.45**: nuclear `POST /api/safety/emergency-flatten-ib` — bypasses bot books, closes whatever IB shows.
- **v19.34.46**: `cancel_all_open_orders_for_symbol` now calls `reqAllOpenOrders()` first to see ALL clients' working orders (was a no-op before — pusher's clientId=15 zombies were invisible to direct's clientId=11).
- **v19.34.47**: `POST /api/trading-bot/sync-books-to-ib-direct` — operator escape hatch when pusher dies and bot's `_open_trades` ≠ IB reality. Operator-verified 2026-05-07 with empty IB + empty bot books in agreement.

13 cumulative tests passing across all flatten/grouping/consolidator suites.



## 🚨 2026-02-XX — v19.34.42 SHIPPED — Position Consolidator (BMNR fragmentation P0 fix)

Operator caught BMNR/LIN/DDOG with 19/3/2 bot_trades respectively, each owning colliding OCA brackets at IB. Root cause: `_spawn_excess_slice` was non-idempotent. Three-layer fix shipped:
1. **Idempotent excess spawn** — grow existing `reconciled_excess_*` slice instead of inserting a new one.
2. **Consolidator service** + dry-run/apply endpoints.
3. **Auto-consolidate in drift loop** with safety rail (kill-switch ON or fragments ≤2).

8/8 new pytest cases passing. Operator action: kill-switch ON → `GET /consolidate-positions/dry-run` → `POST /consolidate-positions/apply` per symbol.

### 🟡 Pending follow-ups from v19.34.42

- **🟡 P1 — Pre-trade entry dedup.** BMNR's 13 SQUEEZE-typed fragments were the SAME setup re-firing 13× against an already-open position. Block setup entry when a same-direction trade is already open for the symbol. Tracked separately from the drift-side fix.
- **🟢 P3 — Plumb IB executionId through pusher → drift reconciler** for true execution-level idempotency on close events (currently using snapshot-seq dedup which is sufficient but not exec-grade).



## 🟢 2026-05-06 night — Pusher RPC wired + V5 badge cleanup verified

**v19.34.35** (operator-side config, no code changes) — "Pusher in partial state" banner resolved. `IB_PUSHER_RPC_URL=http://192.168.50.1:8765` added to DGX `backend/.env`; pusher restarted on Windows to activate RPC server (fastapi+uvicorn already installed). Full `yarn build` + clean `spark_stop/start.sh` cycle. Verified `/api/live/pusher-rpc-health` returns `reachable:true, consecutive_failures:0`; 3ms RPC latency over direct-wire ethernet. V5 OpenPositions badge cleanup (v19.34.23) confirmed live in production bundle — zero per-row ORPHAN/STALE/RECONCILED badges; single subtle `⬤ auto-heal · N` header pill only.

### 🟡 Next up
- **🟡 P1 — V6 UI Refactor Phase A (panel extraction).** Queued but not started. Extract shared frontend panels from `SentComV5View.jsx` into independent components to prep for the 4-pane V6 layout. Zero visual change in this phase — purely modularization.

### 🟢 P3 — Minor polish parked from this session
- **Boot `subscribe_symbols` socket-read timeout:** `pusher_rotation_service.py` fires its first `subscribe_symbols` burst before the `IBPusherRPC` socket has warmed → one traceback in `/tmp/backend.log` on every fresh DGX start. Self-heals on next rotation tick, no user impact. Add a ~2-3s startup-grace delay (and/or a retry with 1s backoff on the first `_request` call only).
- **`OpenPositionsV5` "Loading positions…" stuck state:** when `groups.length === 0` and initial fetch hasn't resolved, the panel holds on "Loading positions…" instead of flipping to "No open positions." Add a fetch-ack flag (or 3s timeout) so the empty-state text is correct.
- **`IB-DOWN` chip clarity:** the red `IB-DOWN` HUD chip refers to the *direct-IB* (shadow mode) link, not the pusher. Rename or tooltip to `DIRECT-IB: OFF` to stop confusing operators who see `PUSHER GREEN` and `IB-DOWN` simultaneously and assume there's a bug.


## 🚨 P0 — TOP OF NEXT SESSION (the GTC zombie bug — classification-aware fix)

**v19.34.5 SHIPPED 2026-05-05 AM** — see CHANGELOG eighty-seventh commit. The critical path (bracket TIF classification) is in. **All NEW orders from today onward get correct DAY TIF on intraday, GTC on swing/position.** Old GTC zombies on disk were manually cancelled by operator via TC2000 last night.

**v19.34.6 SHIPPED 2026-05-05 PM** — see CHANGELOG eighty-eighth commit. Six follow-on safety/UX hardening items. 62 new tests, all passing.

**v19.34.15b SHIPPED 2026-05-06** — see CHANGELOG ninety-seventh commit. Share-count drift reconciler with 24/7 background loop, LIFO partial-shrink, 1%/1R excess-slice defaults. 10/10 tests passing.

**v19.34.17 SHIPPED 2026-05-06** — see CHANGELOG ninety-ninth commit. EOD policy fix: ORPHAN-reconciled positions + v19.34.15b drift-excess slices now flatten at EOD (was: hold overnight). One-shot migration on bot start flips already-open reconciled trades' `close_at_eod` False→True. Bot-originated `day_swing`/`position` trades unaffected. 5/5 tests passing.

**v19.34.16 SHIPPED 2026-05-06** — see CHANGELOG ninety-eighth commit. P1 trifecta: UPS 31s forensic audit script + report, unmatched Sell Short / Buy to Cover detector (service + endpoint + audit-script section), boot zombie-sweep lifecycle persistence (per-trade rows on findings). 98/98 cumulative tests passing.

**v19.34.18 + v19.34.19 SHIPPED 2026-05-06** — Drift loop diagnostic endpoint + zombie-trade blind-spot detector. v19.34.19 dry-run found 1592sh of unmanaged IB shares (369 FDX + 1223 UPS) corresponding to 3 zombie BotTrades. 112/112 cumulative tests passing.

**v19.34.20 + v19.34.20b SHIPPED 2026-05-06** — see CHANGELOG one-hundred-second commit. Upstream zombie-creation prevention. **20:** TIMEOUT path in `trade_execution.py` now initializes `remaining_shares`/`original_shares` (was leaving them at dataclass-default 0 → instant zombie; affected 905sh across 2 of 3 active zombies). **20b:** `_shrink_drift_trades` LIFO peel now closes fully-peeled slices (status flip + pop from `_open_trades` + stop-manager release) instead of leaving rs=0 with status=OPEN — latent leak that would activate on the first auto_resolve Case-2 run. Forensics: `/app/memory/forensics/zombie_root_cause_v19_34_19.md`. 26 tests pass (7 new + 19 prior on adjacent paths). Operator-side healing of 3 existing zombies = `auto_resolve:true` heal call (separate from the prevention fix).

**v19.34.21 SHIPPED 2026-05-06** — see CHANGELOG one-hundred-third commit. **THE BIG ONE.** Operator forensics found a third upstream zombie-maker far more impactful than 20/20b: `bot_persistence.py:dict_to_trade` (the boot-time DB→memory deserializer) was passing only ~25 of `BotTrade`'s ~50 fields to the constructor, so on EVERY restart, ~25 fields silently reset to dataclass defaults — including `remaining_shares=0`, `original_shares=0`, `scale_out_config={targets_hit:[]}`, `trailing_stop_config={mode:original}`, `entered_by="bot_fired"`, all MFE/MAE state, all provenance fields, all commissions/net-pnl. This explains why `a821575c` zombified 11 minutes after the heal (loaded with rs=0 on restart, periodic save persisted rs=0). **The bot was effectively losing half its open-trade state on every reboot.** Plus a smaller-but-correlated fix to `position_reconciler.reconcile_share_drift` zombie-cleanup loop: replaced silent `try: _save_trade except: pass` swallow with logged warning + Mongo-direct `update_one` fallback (operator caught `b4d27b31` reported as closed by heal but staying `status=open` in DB — silent save failure). 31 tests pass (11 new + 20 prior). Files: `bot_persistence.py:dict_to_trade`, `position_reconciler.py:reconcile_share_drift`.

**v19.34.22 SHIPPED 2026-05-07** — see CHANGELOG one-hundred-fifth commit. Orphan-reconciler duplicate-spawn fix discovered during v19.34.19 zombie-cleanup forensics. `reconcile_orphan_positions` previously built `bot_tracked` from `bot._open_trades` only; if a `reconciled_excess_v19_34_15b` / `reconciled_excess_v19_34_19` slice (or v19.24 `reconciled_external` orphan) was persisted to `bot_trades` (`status==open`) but not yet hydrated into `_open_trades`, the reconciler treated the symbol as untracked and spawned a duplicate. Fix unions the in-memory tracked set with the DB's open-row symbol set; new `db_already_tracked` skip reason distinguishes the new code path. 6/6 new tests passing; cumulative reconciler-suite still 44/44 green.

### 🟡 Backlog from v19.34.21 forensic session
- **UI panel `shares` vs `remaining_shares` confusion**: ✅ partially addressed in v19.34.15a (shares column now colorized red/green by direction). Still TODO: surface `remaining_shares` as the live count in expanded rows (currently shows `shares` only).
- **Audit `dict_to_trade` regression coverage**: write a roundtrip property-test that `dict_to_trade(to_dict(trade)) == trade` for every field — would have caught this bug pre-shipped.
- **Investigate why `_save_trade` silently failed for `b4d27b31`** — the v19.34.21 fallback handles this generically, but root cause is unknown. Likely candidates: serialization of `entry_time` (a dynamic datetime attr), or a Mongo-side conflict.

### 🔴 v19.34.15a NEXT (Naked-position safety net) — plan + investigate before code

Operator request: investigate carefully before committing. Two-part fix:

1. **In `trade_executor_service.py`**: treat `status: unknown` from pusher as `timeout` (not hard reject). Mark trade `OPEN [TIMEOUT-NEEDS-SYNC]` so the new v19.34.15b drift loop can pick up any silent fill within 30s.
2. **In `trade_execution.py`**: add a post-rejection IB poll-back task that polls every 1s for 15s after any rejection. If a fill is detected, emit `unbracketed_fill_detected_v19_34_15` stream event and let v19.34.15b auto-spawn the excess slice.

Why this order matters: with v19.34.15b shipped, the drift loop catches the same naked-share class within 30s anyway. v19.34.15a accelerates detection from 30s → ~1s and adds the explicit `unbracketed_fill_detected` event for clearer forensics. **Operator wants to verify v19.34.15b runs cleanly for a few sessions before we touch the broker rejection path.**


### ✅ v19.34.5 shipped (premarket emergency)

- `services/bracket_tif.py` — single-source-of-truth helper.
- 3 call sites patched: `trade_executor_service.py`, `ib_service.py`, `position_reconciler.py`.
- `tests/test_bracket_tif_v19_34_5.py` — 23 tests, all passing.
- 96/96 cumulative v19.34.x tests passing. Zero regressions.

### ✅ v19.34.6 shipped (operator-driven safety/UX hardening)

1. **Open Positions watchlist filter** — suppresses `carry_forward_watch` / `day_2_continuation` / `approaching_*` rows from V5 panel unless IB confirms. (Item b from session plan.)
2. **Pre-execution Mongo-first sanity gate** — `bot_trades` row written with `status=PENDING` BEFORE broker call. (Item d.)
3. **`GET /api/ib/orders`** — Mongo `order_queue`-backed visibility endpoint, replaces dead direct-IB `/orders/open`. (Item e.)
4. **Carry-forward gameplan persistence** — `_persist_carry_forward_alert` + hydrate on `start()` so morning prep workflow survives backend restart. (Item c.)
5. **`GET /api/trading-bot/effective-limits`** — single canonical AND across all guard layers. (Item h.)
6. **`POST /api/trading-bot/eod-validate-overnight-orders`** — runtime sweep of GTC/`outside_rth=true` orphans + wrong-TIF rows; two-step confirm. (Item g.)
7. **`POST /api/trading-bot/cancel-orders-for-symbol`** — EOD pre-cancel guard for one-symbol flatten race. (Item f.)

### ✅ v19.34.8 shipped (rejection cooldown — kills the 110-bracket loop class of bug)

1. **`services/rejection_cooldown_service.py`** — per-`(symbol, setup_type)` cooldown after structural rejections (capital, kill-switch, exposure caps, buying-power). Default 5 min, configurable via `REJECTION_COOLDOWN_SECONDS`. 40 new tests.
2. **`trade_execution.execute_trade`** — gate at top + mark on rejection + mark on guardrail veto. Three integration points cover broker-side AND bot-side rejection paths.
3. **Operator endpoints** — `GET /api/trading-bot/rejection-cooldowns`, `POST /api/trading-bot/clear-rejection-cooldown`.

### ✅ v19.34.10 shipped (state-integrity drift watchdog — 2026-05-06)

1. **`services/state_integrity_service.py`** — 60s background loop comparing in-memory `risk_params` to persisted `bot_state.risk_params`. Field-policy auto-resolve: capital/limit fields → Mongo wins; `setup_min_rr` → memory wins. Forensic events to `state_integrity_events` (TTL 7d). CRITICAL stream event on drift. 21 new tests.
2. **`GET /api/trading-bot/integrity-status`** + **`POST /api/trading-bot/force-resync`** — operator inspection + on-demand check (with `dry_run` mode).
3. **Wired into `TradingBotService.start()` + `stop()`** — survives backend restart, 30s grace period, cancelled cleanly on shutdown.
4. **Default ON**: `STATE_INTEGRITY_CHECK_ENABLED=true`, interval 60s, auto-resolve true. Operator can flip to detect-only via env.

### ✅ v19.34.11 + v19.34.12 shipped (Bracket History panel + Rejection Heatmap sub-tab — 2026-05-06)

1. **v19.34.11 — Bracket History**: `services/bracket_reissue_service._persist_lifecycle_event` writes every reissue path to Mongo `bracket_lifecycle_events` (TTL 7d). `GET /api/trading-bot/bracket-history?trade_id|symbol&days&limit` returns events + summary aggregations. V5 `<BracketHistoryPanel />` is a lazy-loaded expandable inner panel inside `OpenPositionsV5.jsx` expanded row with reason chips (color-coded by reason: scale_out=emerald, scale_in=cyan, tif_promotion=violet, manual=zinc) + phase chips + per-event detail. 9 new tests.
2. **v19.34.12 — Rejection Heatmap**: `services/rejection_cooldown_service._persist_rejection_event` writes every structural rejection to Mongo `rejection_events` (TTL 7d) with TTL + compound (symbol, setup_type, created_at) indexes. `GET /api/trading-bot/rejection-events?symbol&setup_type&days&limit` returns events + heatmap aggregation (rows by Symbol × Setup, by_reason maps, top reasons, max_rejections). V5 `<RejectionHeatmap />` is a new Diagnostics sub-tab at id `rejections` rendering the (Symbol × Setup) grid with 4-tier heat colors + hover tooltips per cell + raw-events table toggle + days selector + auto-refresh 30s. 13 new tests.

### ✅ v19.34.14 shipped (CRITICAL hotfix: drift watchdog policy flip + loop detector — 2026-05-06)

Operator caught the v19.34.10 watchdog snapping live IB capital ($236,344.65) DOWN to mock default ($100,000) — exactly the v19.34.9 catastrophic skew, but caused BY the watchdog. Root cause: v19.34.10 `mongo_wins` policy was wrong-by-design; in v19.34.9 RCA, memory had the correct value (from live IB) and Mongo was the lagging side.

1. **Policy flip**: Moved `starting_capital`, `max_daily_loss`, `max_notional_per_trade`, `max_risk_per_trade` to `MEMORY_WINS_FIELDS`. Kept `max_open_positions`, `max_position_pct`, `min_risk_reward`, `max_daily_loss_pct`, `reconciled_default_*` as `MONGO_WINS_FIELDS` (operator-tuned via /risk-params PUT).
2. **Drift-loop detector**: same field flips ≥3 times in 600s → demoted to detect-only for process lifetime. Prevents watchdog oscillation.
3. **`POST /force-resync {rearm_demoted: true}`** — operator re-arm path after manual fix.
4. **`GET /integrity-status`** now exposes `demoted_fields[]` + `loop_detector` constants.
5. 11 new tests + 4 v19.34.10 tests migrated to `max_open_positions` as canonical mongo_wins example. 55/55 passing across v19.34.10-14 suites.
6. Operator action on Spark after pull: `curl -X POST "$API/trading-bot/refresh-account"` to restore live capital.

### ✅ v19.34.13 shipped (STALE chip fix + redundant pusher chip removed + boot-reconcile retry pass — 2026-05-06)

1. **STALE 240m chip fix**: `routers/ib.receive_pushed_ib_data` now stamps `pushed_at` on every quote dict at merge time using top-level `last_update`. `services/sentcom_service.get_our_positions` adds defensive fallback to top-level `last_update` for synthesized quotes. Fixes V5 freshness chip that was rendering "STALE 240m" on every Open Position even when pusher was LIVE 1s.
2. **Redundant `<PusherHealthChip />` removed** from `SentComV5View.jsx` HUD top strip — `<PusherHeartbeatTile />` panel below is the single source of truth.
3. **Boot auto-reconcile retry pass + skip-reason exposure**: `_startup_auto_reconcile` refactored into reusable `_do_pass()` helper. After the initial 20s pass, if orphans were skipped (typically `direction_unstable` due to 30s observation gate not yet filled at boot), schedule a retry pass at 90s total (60s after first). Persists `skipped[]` + `retry_pass` flag to `bot_state.last_auto_reconcile_at_boot`. `GET /api/trading-bot/boot-reconcile-status` surfaces these. V5 `<BootReconcilePill />` gets 3 new amber states (`Claimed N · K left`, `Boot · K skipped`, `(retry)` suffix) + per-orphan skip-detail tooltip. 8 new tests.

### 🟡 Remaining v19.34.10 / next pickup

1. **UPS `oca_closed_externally_v19_31` 31-sec close investigation** — deferred from v19.34.8/9; forensic-only. Needs operator's diagnostic script output for the 13:35:36 trade.
2. **Extend `audit_ib_fill_tape.py`** to flag unmatched `Sell Short` / `Buy to Cover` IB transactions — needs sample TWS tape with these exact rows to safely tune the regex.
3. **Wire bracket-lifecycle event persistence into the boot zombie sweeper** — v19.34.11 only persists events from `reissue_bracket_for_trade`. The boot-time `eod_validate_overnight_orders` dry-run sweep should also stamp events so operator history shows "boot detected N orphans, sweep dry-run only".
4. **Rejection Heatmap per-cell hour-of-day sparkline** (proposed 2026-05-06 after v19.34.12). Add a tiny 24-bar histogram of rejections by hour inside each `(symbol, setup_type)` cell so operator can spot time-of-day clustering ("ORB-on-XLU rejections cluster 14:30-15:00 ET") without leaving the heatmap. Implementation: extend `GET /api/trading-bot/rejection-events` heatmap aggregation to include `by_hour: int[24]` per row (single extra Mongo aggregation pipeline grouping `created_at.hour`); render in `<RejectionHeatmap />` as inline SVG sparklines beneath the count number. Same TTL data — no new collection.
5. **Drift-loop detector knobs as `risk_params`** (proposed 2026-05-06 after v19.34.14 hotfix). Currently `LOOP_DEMOTE_FLIPS=3` and `LOOP_DEMOTE_WINDOW_S=600` are module-level constants in `services/state_integrity_service.py`. Promote them to `RiskParameters` fields (`drift_loop_demote_flips: int = 3`, `drift_loop_demote_window_s: int = 600`) so operator can hot-tune via `PUT /api/trading-bot/risk-params` without a code deploy. Tighter envelope for live trading vs paper, looser for noisy dev environments. Read them in `_record_flip_and_check_demote` from `bot.risk_params.*` instead of the module constants. Same Mongo persistence path (`_save_state()`), no new endpoint, no schema migration. Bonus: include them in the v19.34.10 `MONGO_WINS_FIELDS` so they're operator-controlled like the other limit knobs. Tiny lift, big operational flexibility — the kind of self-tunable safety knob that ages well as the system matures.

### ✅ v19.34.7 shipped (operator-driven bracket lifecycle architecture)

1. **Bracket re-issue service** (`services/bracket_reissue_service.py`) — unified cancel-old + recompute + submit-new OCA pair. Auto-wired into scale-out path. Operator endpoint `POST /api/trading-bot/reissue-bracket` for manual + future scale-in. 19 + 8 = 27 new tests.
2. **Boot zombie sweeper** — wired into `TradingBotService.start()`. Dry-run sweep at startup + operator stream warning. Manual cancel via `eod-validate-overnight-orders` with confirm token.

### 🟡 Remaining v19.34.7 / future items

1. **V5 dashboard "Bracket History" tab on each open position** — surface the bracket-reissue rich event trail (cancel_result + submit_result + plan + rationale[]) per trade. Operator sees full lifecycle: original bracket → scale-out trim → re-issue → eventual exit, with the WHY for each re-issue (`reason: scale_out_t1`, `tif_promotion`, etc.). Audit-grade trail for the V5 bot-thought bubbles. Backend already emits the events; needs a Mongo `bracket_lifecycle_events` collection writer in `bracket_reissue_service.py` + `GET /api/trading-bot/bracket-history?trade_id=X` + `<BracketHistoryTab />` React component.
2. **Scale-IN code path** — bot doesn't have an explicit scale-in feature today. When added, call `reissue_bracket_for_trade(trade, reason="scale_in", new_total_shares=N+added, new_avg_entry=weighted_avg)`. Service is ready.
3. **Bracket TIF promotion (intraday → swing)** — same service, `reason="tif_promotion"`.
4. **Investigate XLU 6-bracket pattern from 2026-05-05 AM** — pending operator's diagnostic script output. Likely intent-dedup miss OR legit re-entries; bracket re-issue service now contains the damage either way.
5. **Extend `audit_ib_fill_tape.py`** to flag unmatched `Sell Short`/`Buy to Cover` IB transactions — deferred (existing `INVERSION_SHORT_COVER` verdict already captures the semantics; explicit subtype detection needs sample TWS tape with the new wording).

### 🟡 Remaining v19.34.6 items

1. **Selective boot zombie sweeper** — on startup, enumerate IB open orders. For each: cancel if no matching `bot_trades` parent OR parent is `status=closed`; KEEP if parent is `status=open` AND swing/position style. Lower priority now since operator did a one-time manual flush + (g) endpoint provides on-demand sweep.
2. **Bracket re-issue on classification promotion** — if operator/bot promotes intraday→swing, set `bracket_tif_dirty=true`, cancel DAY legs, re-issue as GTC on next manage-loop tick.
3. **Extend `audit_ib_fill_tape.py`** — flag any `Sell Short`/`Buy to Cover` IB tx without matching `order_queue` entry.
4. **Wire `cancel-orders-for-symbol` into the EOD close path automatically** — currently it's an operator-callable endpoint. The EOD market-close runner should invoke it on each symbol it's about to flatten, before submitting the close order, to neutralize OCA legs proactively.
5. **Pin watchlist-only setup list as single-source-of-truth** — currently duplicated between `services.sentcom_service._WATCHLIST_ONLY_SETUPS` and `TradingBotService._watchlist_only_setups`. Move to a shared module (`services/setup_classification.py`) so a future setup type addition can't drift.

### Operator actions completed

- ✅ Cancelled ALL open IB orders manually via TC2000 (kills the entire zombie pile that had accumulated). 2026-05-04 PM.
- ✅ Set market BUY 17 STX order for 2026-05-05 open to cover the unwanted short.
- ✅ v19.34.5 shipped 2026-05-05 AM premarket — bracket TIF classification active for all new orders.
- ✅ v19.34.6 shipped 2026-05-05 PM — six safety/UX hardening items (62 new tests).

### Verification step — first bracket of the day (still pending operator action)

```bash
cd ~/Trading-and-Analysis-Platform/backend && \
source ~/Trading-and-Analysis-Platform/.venv/bin/activate && \
set -a && source .env && set +a && \
python -c "
import os
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
c = MongoClient(os.environ['MONGO_URL'])
db = c[os.environ['DB_NAME']]
today_iso = datetime.now(timezone.utc).strftime('%Y-%m-%d')
q = {'order_type': 'bracket',
     '\$or': [{'queued_at': {'\$gte': today_iso}},
              {'queued_at': {'\$gte': datetime.now(timezone.utc) - timedelta(hours=12)}}]}
rows = list(db.order_queue.find(q).sort('queued_at', -1).limit(20))
print(f'Found {len(rows)} bracket orders today')
for r in rows:
    sym = r.get('symbol','?'); qa = r.get('queued_at','?')
    p, s, t = r.get('parent') or {}, r.get('stop') or {}, r.get('target') or {}
    print(f'{sym} {qa}')
    print(f'  parent: TIF={p.get(\"time_in_force\")} outside_rth={p.get(\"outside_rth\")}')
    print(f'  stop:   TIF={s.get(\"time_in_force\")} outside_rth={s.get(\"outside_rth\")}')
    print(f'  target: TIF={t.get(\"time_in_force\")} outside_rth={t.get(\"outside_rth\")}')
"
```

Expected for an intraday trade: `stop.TIF=DAY`, `target.TIF=DAY`, `outside_rth=False`. **If you see GTC or outside_rth=True on an intraday row → fix didn't deploy correctly, restart backend.**


## 🔴 Now / Near-term (other carry-over)

### 🎯 Just shipped 2026-05-04 v19.34.4 — see CHANGELOG (eighty-fifth commit)
**IB fill-tape auditor + Spark Mongo cross-check + 2026-05-04 audit run.**

- ✅ `backend/scripts/audit_ib_fill_tape.py` — TWS-paste parser + FIFO PnL + verdict classifier (`CARRYOVER_FLATTENED` / `OPEN_POSITION_LONG` / `MULTI_LEG_*` / `INVERSION_SHORT_COVER` / `CLEAN_ROUND_TRIP`).
- ✅ `backend/scripts/export_bot_trades_for_audit.py` — Spark Mongo export with ISO-string + datetime hybrid query, `--status` flag (default closed,open) for filtering rejected/vetoed evaluation noise.
- ✅ `memory/runbooks/audit_ib_fill_tape.md` — 5-phase operator runbook.
- ✅ 2026-05-04 audit complete: **328 fills / 21 symbols / -$14,560 net** PAPER day. Single residual `STX -17sh` flagged as carryover — now traced to GTC zombie order bug above.
- ✅ **15/15 new pytests passing**, **256/256 cumulative across all v19.x suites**.

### 🔴 P0 — MID_BAR_TICK_EVAL activation (carry-over from v19.34)
Per `/app/memory/runbooks/midbar_tick_eval_activation.md`. Defer until GTC fix lands; no point activating mid-bar fires while zombie orders are still in play.

### 🔴 P0 — Carry-over verifications (still pending operator confirmation)

- (v19.31.13) AccountModeBadge correctness on paper vs live accounts.
- (v19.31.13) Realized PnL auto-syncs within 30s without operator clicks.
- (v19.31.13) Diagnostics → Shadow Decisions tab loads cleanly.
- (v19.31.13) PAPER/LIVE chips render on Open Positions / Day Tape / Forensics.
- (v19.31.14) Pre-Market banner appears 7:00-9:30 ET in scanner panel.
- (v19.31.14) `/api/ib-collector/throttle-policy` returns `max_concurrent_workers=1` during RTH.
- (v19.31.14) BootReconcilePill appears in HUD after backend restart, fades after 10 min.
- (v19.31.14) Module Vote Breakdown panel renders below Module Scorecard.
- (v19.31.14) Funnel `⚠ Shadow drift` chip appears when shadow ≠ trades.
- (v19.32) Chart click on a recently-visible scanner symbol lands in <50ms (was ~400ms cold).
- (v19.33) Chart header shows cyan **"live"** pip when on a focused intraday chart during RTH.
- (v19.34.3) RECONCILED + ⚠ CONFLICT chips render on V5 Open Positions row when applicable.

### 🟡 P1 — Persist carry_forward_watch gameplan cards across refresh (v19.34.5 candidate)

**Operator-reported 2026-05-04 EVE.** The SCANNER · LIVE panel showed 4 rich `carry_forward_watch` cards (SBUX, IAU, MA, SYK) with full bot reasoning during/after RTH (graded B/C+, "viable Day-2 play if X opens above today's close"). On hard refresh of the app outside RTH, those cards disappeared and only STX (today's actual position) remained.

**Why this matters:** The cards ARE the morning prep gameplan. Losing them at refresh breaks the premarket workflow.

**Likely causes (investigate):**
1. Scanner live API returns only a short rolling window (e.g. last 15 min) — carry-forwards > 15 min old drop off.
2. Default feed filters out `carry_forward_watch` event_kind and only includes `setup_fired` / `breakout`.
3. Frontend hook keeps cards in component state that gets blown away on hard refresh; no backfill on mount.

**Investigation steps (~30 min):**
```bash
# 1. Find the panel's data hook and endpoint
grep -rn "carry_forward\|scanner.live\|live-alerts" \
    ~/Trading-and-Analysis-Platform/frontend/src/components/sentcom/v5/ScannerCardsV5.jsx \
    ~/Trading-and-Analysis-Platform/frontend/src/components/sentcom/hooks/

# 2. Confirm carry_forward_watch events are in Mongo (sentcom_thoughts is the 7d TTL stream)
db.sentcom_thoughts.countDocuments({kind:/carry_forward/i, created_at:{$gte:"<today>"}})

# 3. Check the API response shape for the panel's endpoint
curl ${BACKEND_URL}/api/scanner/live-alerts?limit=20 | jq '.alerts[].kind' | sort -u
```

**Fix scope:**
- If API filters out carry_forwards → add `kind` flag (e.g. `?include_carry_forwards=true`) and have ScannerCardsV5 always request it.
- If TTL/window is too short → bump scanner-live API window to "today's session" (since 4 AM ET) instead of last 15 min.
- If frontend state is the problem → hook should `useEffect` fetch on mount, not rely on websocket-only delta updates.
- Add a "Pinned for tomorrow" pill on each carry_forward card so operator can see at a glance which symbols the bot will watch at the open.

**Tests required:**
- `test_v19_34_5_carry_forward_persists_across_session.py` — write 4 carry_forwards to `sentcom_thoughts`, hard-refresh equivalent (call API fresh), assert all 4 returned.
- `test_v19_34_5_scanner_live_api_includes_carry_forwards.py` — curl the live-alerts endpoint, assert kind=carry_forward_watch entries are present.

### 🟡 P1 (operator-facing improvements, carried forward)
- Frontend L1 tick rendering with RAF-coalescing on `/ws/quote-ticks` (deferred from v19.33).
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over). **NOTE: would have caught the STX -17 today.**
- Pusher honors `max_concurrent_workers` from `/api/ib-collector/throttle-policy`.

### 🟢 P2 / P3 (future evolution paths now unlocked by v19.34)
- **Stop-distance journal → ML training data** (operator-suggested 2026-05-04: pipe `tick_evaluated` annotations on every mid-bar eval, train classifier on `(distance, volatility, time-of-day, regime)` → `P(stop hit within next N seconds)`).
- **Sub-bar trailing stops** — once mid-bar is proven safe.
- **Mid-bar entry eval** — selectively front-run entries on high-conviction signals.
- **L1 → L2 escalation** — request L2 depth via the tick bus for actively-evaluated symbols.
- **Audit Pass 1**: lint sweep + dead-code (370 ruff fixes).
- **Audit Pass 3**: break up 4 monoliths.
- v19.32 evolution — predictive warmer that pre-fetches the chart for the symbol an alert is about to fire on.
- v19.33 evolution — WS pushes per-tick L1 quote updates.
- Setup-landscape EOD self-grading tracker.
- Mean-reversion metrics service (per-symbol Hurst exponent + Ornstein-Uhlenbeck half-life).
- Liquidity-aware trail in `stop_manager.py`.
- IB Gateway auto-login resilience.
- Safely retire Alpaca fallback.

---

## 🔴 Now / Near-term (next session pickup — 2026-05-04 v19.34)

### 🎯 Just shipped 2026-05-04 v19.34 — see CHANGELOG (eighty-first commit)
**L1 tick bus + mid-bar stop eval. Three phases. Bus + bridge always on; manage-loop consumer defaulted OFF for explicit operator opt-in.**

- ✅ **Phase 1 — `services/quote_tick_bus.py`** — in-memory pub/sub with latest-N drop, per-subscriber `asyncio.Queue(8)`, drop counters, `bus.stream()` async-generator helper.
- ✅ **Phase 2 — Pusher → bus bridge** — `routers/ib.py:receive_pushed_ib_data` publishes every quote update. New `GET /api/ib/quote-tick-bus/health` for monitoring.
- ✅ **Phase 3 — Mid-bar stop eval** — `PositionManager.evaluate_single_trade_against_quote` mirrors bid/ask-aware stop-trigger logic but per-trade per-tick (~50ms cadence). Lifecycle reaper in `TradingBotService.start()` walks `_open_trades` every 2s and reconciles subscribers. Close reason stamped `stop_loss_mid_bar_v19_34`. Defaulted OFF via `MID_BAR_TICK_EVAL_ENABLED`.
- ✅ **Operator playbook** — `memory/runbooks/midbar_tick_eval_activation.md` with pre-flight checklist (30min bus health on RTH), activation steps, verification, rollback (single env-var flip), and red-flag monitoring.
- ✅ **208/208 v19.31.x + v19.23.x + v19.32 + v19.33 + v19.34 pytests passing.**

### 🔴 P0 — Top of next session (operator-driven activation path)

**Step 1 (today, RTH window) — Validate bus health:**
1. `curl ${BACKEND_URL}/api/ib/quote-tick-bus/health` — confirm `enabled=true`, `publish_total > 0` and growing, `drop_total ≈ 0`, `active_symbols=0` (no consumers yet).
2. Re-check after 30min of RTH. Drop rate should still be 0.

**Step 2 (after Step 1 passes) — Flip Phase 3 ON:**
1. `echo "MID_BAR_TICK_EVAL_ENABLED=true" >> /app/backend/.env && sudo supervisorctl restart backend`.
2. Within 5s of an open trade, look for `[v19.34 MID-BAR TICK] +sub trade_id=...` in logs.
3. Health endpoint should now show `active_symbols ≥ #(open trades)`.
4. On any stop-hit during the session, look for `[v19.34 MID-BAR STOP]` warning + a `mid_bar_v19_34` close reason in Day Tape / Forensics.

**Step 3 — Verification of saved latency:**
- Compare Day Tape `mid_bar_v19_34` rows vs equivalent bar-close stops on prior days. Mid-bar fires should land within ~0-2s of the trigger crossing; bar-close fires were typically 5-30s.

**ROLLBACK if anything goes wrong:**
- `sed -i 's/MID_BAR_TICK_EVAL_ENABLED=true/MID_BAR_TICK_EVAL_ENABLED=false/' /app/backend/.env && sudo supervisorctl restart backend`. Bot reverts to v19.33 behavior immediately.

**ALSO verify existing v19.31.13 + v19.31.14 + v19.32 + v19.33 features** (12-point checklist preserved below).

### 🔴 P0 — Verification carry-over from prior sessions

- (v19.31.13) AccountModeBadge correctness on paper vs live accounts.
- (v19.31.13) Realized PnL auto-syncs within 30s without operator clicks.
- (v19.31.13) Diagnostics → Shadow Decisions tab loads cleanly.
- (v19.31.13) PAPER/LIVE chips render on Open Positions / Day Tape / Forensics.
- (v19.31.14) Pre-Market banner appears 7:00-9:30 ET in scanner panel.
- (v19.31.14) `/api/ib-collector/throttle-policy` returns `max_concurrent_workers=1` during RTH.
- (v19.31.14) BootReconcilePill appears in HUD after backend restart, fades after 10 min.
- (v19.31.14) Module Vote Breakdown panel renders below Module Scorecard.
- (v19.31.14) Funnel `⚠ Shadow drift` chip appears when shadow ≠ trades.
- (v19.32) Chart click on a recently-visible scanner symbol lands in <50ms (was ~400ms cold).
- (v19.33) Chart header shows cyan **"live"** pip when on a focused intraday chart during RTH.
- (v19.33) Auto-fallback test: temporarily set `CHART_WS_ENABLED=false` → confirm chart switches to "poll" pip + still updates via REST.

### 🟡 P1 (operator-facing improvements, carried forward)
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over).
- **Pusher honors `max_concurrent_workers`** — current Windows pusher reads `/api/ib-collector/throttle-policy` and parks N-1 of its 4 workers.

### 🟢 P2 / P3 (future evolution paths now unlocked by v19.34)
- **Stop-distance journal → ML training data** *(operator-suggested 2026-05-04, captured from v19.34 finish summary)* — pipe a tiny `tick_evaluated` annotation into `sentcom_thoughts` on every mid-bar eval, e.g. `"AAPL: bid 148.42 vs stop 148.50 (-8c safety margin) at 09:33:14"`. After a week, you'd have a microsecond-resolution journal of every stop's distance-to-fire across every open trade — perfect training data for an AI module that learns to predict stop-run probability **before** the wick actually fires. Implementation notes:
  - Throttle the writer (1 sample/sec/trade max) so we don't drown `sentcom_thoughts` — the existing TTL=7d is fine.
  - Add a new `kind: "stop_distance_sample"` so it's filterable from the operator-facing thought stream.
  - Stamp `bid/ask/last/effective_stop/distance_pct/seconds_until_fire` so the trainer has both the live state and (computed at fire-time, in a later batch job) the eventual outcome label.
  - Train a small classifier (XGBoost or a 2-layer MLP) on `(distance, recent volatility, time-of-day, regime)` → `P(stop hit within next N seconds)`. Wire prediction back into the AI council's "should we tighten the stop?" decision.
- **Sub-bar trailing stops** — once mid-bar stop eval is proven safe, extend to per-tick trailing recalc. Needs careful smoothing to avoid noise-driven exits.
- **Mid-bar entry eval** — currently entries wait for bar-close to avoid wicks. Could selectively front-run entries on high-conviction signals using the same tick bus.
- **L1 → L2 escalation** — for actively-evaluated symbols, request L2 depth via the tick bus to spot stop-runs before they fire.
- v19.32 evolution — predictive warmer that pre-fetches the chart for the symbol an alert is about to fire on.
- v19.33 evolution — WS pushes per-tick L1 quote updates, not just per-bar updates. Latency floor would drop to ~50ms but needs server-side dedup tuning.
- Setup-landscape EOD self-grading tracker.
- Mean-reversion metrics service (per-symbol Hurst exponent + Ornstein-Uhlenbeck half-life).
- Liquidity-aware trail in `stop_manager.py`.
- IB Gateway auto-login resilience
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths

### 🎯 Just shipped 2026-05-04 v19.31.3 — see CHANGELOG (sixty-ninth commit)
**System banner thin strip + smarter `historical_queue` thresholds. Operator's "banner is huge" feedback.**

- ✅ `HIST_QUEUE_*` thresholds rebalanced: yellow 5K→50K pending, failures-first escalation (≥25 failed → yellow). Deep queue with 0 failures now stays green.
- ✅ New `level: "info"` banner state (slate-blue) for deep-queue-no-failures, with `metrics.deep_queue_no_failures` flag from the health service.
- ✅ `SystemBanner.jsx` collapsed from ~200px to ~28px single-strip layout. 3-color scheme (red/amber/slate). Inline detail+since+action. Full detail in title tooltip.
- ✅ **12/12 new pytests** + **51/51 v19.31 total** across 6 suites.

### 🎯 v19.31.0–v19.31.3 cumulative — operator pain-points resolved this session

1. ✅ Unified Stream `.slice(0,2)` cap removed; fetch limit 20→200.
2. ✅ ORPHAN/PARTIAL/STALE badge no longer obscures live PnL.
3. ✅ `/api/system/banner` `NameError: pusher_red` fixed.
4. ✅ External-close phantom sweep (`oca_closed_externally_v19_31`) catches LITE-style cases.
5. ✅ Reset script `--force` flag + IB-survival guard prevents orphaning real positions.
6. ✅ MANAGE +0.0R aggregator fixed via `pnl_r` field on every position.
7. ✅ Auto-reconcile-at-boot (`AUTO_RECONCILE_AT_BOOT=true`) — no more morning click ritual.
8. ✅ Historical-queue threshold rebalance + info-level banner + thin strip — backfill no longer alarms.

### 🎯 Just shipped 2026-05-04 v19.31.2 — see CHANGELOG (sixty-eighth commit)
**Auto-reconcile-at-boot toggle — kills the morning RECONCILE-N click ritual.**

- ✅ `AUTO_RECONCILE_AT_BOOT=true` env flag wired into `TradingBotService.start()`. Runs 20s after start (after emergency stops), claims every IB-only carryover via `reconcile_orphan_positions(all_orphans=True)`. Default OFF for safety.
- ✅ Stream event `auto_reconcile_at_boot` emitted on success with first 8 symbols + overflow tag.
- ✅ Wrapped in try/except so reconcile failure never crashes `start()`.
- ✅ **17/17 pytests** including 6 truthy variants + 7 falsy variants + exception-safe test.
- ✅ Combined with v19.31.1 reset-survival guard, operator literally never sees "RECONCILE 13" in the morning anymore.

### 🎯 Just shipped 2026-05-04 v19.31.1 — see CHANGELOG (sixty-seventh commit)
**Three live-RTH bugs from operator screenshot at 9:36 AM ET RTH.**

- ✅ **External-close phantom sweep** in `position_manager.py` — catches the LITE-style case where IB's OCA bracket closed the position but bot's `_open_trades` still tracks it. Marks CLOSED with `oca_closed_externally_v19_31` reason. 6 new pytests.
- ✅ **Reset script IB-survival guard** in `reset_bot_open_trades.py` — refuses to close `bot_trades` rows where IB still holds matching `(symbol, direction)`. New `--force` to bypass; fail-closed when snapshot missing. 7 new pytests.
- ✅ **MANAGE +0.0R aggregator fix** — `sentcom_service.get_our_positions` now emits `pnl_r` + `unrealized_r` for both bot-tracked and orphan/lazy-reconciled paths (was silently 0 because the fields were never populated). 6 new pytests including LITE +12.5R math validation.
- ✅ **22/22 v19.31 pytests passing** across 4 suites. Backend syntax + ESLint clean.

### 🎯 Just shipped 2026-05-04 v19.31.0 — see CHANGELOG (sixty-sixth commit)
**Live-RTH HUD paper-cuts: stream cap + ORPHAN badge overlap + banner NameError.**

- ✅ Unified Stream `.slice(0, 2)` cap removed (HTTP + WS); fetch limit 20 → 200.
- ✅ ORPHAN/PARTIAL/STALE badge moved inline next to tier chip — no longer obscures live PnL.
- ✅ `/api/system/banner` `NameError: pusher_red` fixed. 3 regression pytests.

### 🔴 P0 — Top of next session
- **Verify v19.31.1 fixes live during next RTH session**:
  1. After pull + restart, confirm the LITE-style phantom sweeps within 30-60s of OCA closure.
  2. Check `MANAGE +XR` HUD aggregator now reflects realized R per open position.
  3. Try a dry-run reset script with the new `--dry-run` to see the IB-survival report.
- **Diagnostics Data Quality Pack** — fix Pipeline Funnel `ai_passed`/`bot_fired` consistency + Module Scorecard `shadow_module_performance` per-vote breakdown (carry-over).
- **Bot Thoughts content capture** — Trail Explorer empty `content` field for fired trades (carry-over).

### 🟡 P1 (operator-facing improvements)
- **Auto-reconcile-at-boot** — if `_restore_open_trades` finds 0 rows but IB still has positions, auto-fire a `POST /api/trading-bot/reconcile {all: true}` so the operator doesn't have to click RECONCILE every morning. Likely best gated behind an env flag (`AUTO_RECONCILE_AT_BOOT=true`).
- **Stale-snapshot warning on reset** — if `ib_live_snapshot.current.as_of` is more than ~30s old when the reset script runs, print a warning before partitioning. Defends against a freshly-restarted backend with no pusher data yet.
- `.bat` health screen probes pusher actually (carry-over).
- Pusher auto-restart on Windows (carry-over).
- Shadow-vs-Real gap drilldown (carry-over).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares (carry-over).
- Async-pymongo audit follow-up — 51 remaining sync-mongo-in-async sites.

### 🟢 P2 / P3
- v19.32 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.33 Chart WebSockets (Tier 3 — kill remaining 5s polling latency)
- IB Gateway auto-login resilience
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths

---


## 🔴 Now / Near-term (next session pickup — 2026-05-01 v19.30.12 + Windows network fix)

### 🟢 Today fully resolved — all data channels healthy
- ✅ v19.30.11 — Pusher RPC throttle/circuit-breaker/dedup + skip-restart-if-healthy + system banner
- ✅ v19.30.12 — Distinguish push-channel vs RPC-channel pusher health (4-quadrant severity matrix)
- ✅ Windows network classification fix — 10GbE adapter set to Private (was Public), so `IB Pusher RPC 8765` allow rule is now honored. Spark→Windows on :8765 succeeds. SystemBanner clears, RPC chip green.

### 🔴 P0 — Top of next session
- **Diagnostics Data Quality Pack** — fix Pipeline Funnel `ai_passed`/`bot_fired` consistency + Module Scorecard `shadow_module_performance` per-vote breakdown
- **Verify v19.24 Reconcile endpoint live on Spark** on SBUX/SOFI/OKLO orphans
- **Bot Thoughts content capture** — Trail Explorer empty `content` field for fired trades

### 🟡 P1 (operator-facing improvements)
- **`.bat` health screen probes pusher actually**: replace `WINDOWTITLE eq [IB PUSHER]` check with `curl -s -f -m 3 http://localhost:8765/rpc/health` so operator sees real status, not "window open = OK"
- **Pusher auto-restart on Windows**: wrap CMD launch in `pusher_watchdog.bat` loop that re-spawns on crash
- **Shadow-vs-Real gap drilldown** (71% shadow vs 32% real)
- **Drift detector** — CRITICAL stream when bot tracks <80% of IB shares
- **Async-pymongo audit follow-up** — 51 remaining sync-mongo-in-async sites (was 53)

### 🟢 P2 / P3
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (Tier 3 — kill remaining 5s polling latency)
- IB Gateway auto-login resilience (more robust SendKeys + foreground verification)
- Setup-landscape EOD self-grading tracker
- Audit Pass 1: lint sweep + dead-code (370 ruff fixes)
- Break up 4 monoliths (ib.py 6349, server.py 4643, enhanced_scanner.py 7090, training_pipeline.py 3869)
- Safely retire Alpaca fallback (32 reference sites)

---

## 🔴 Now / Near-term (next session pickup — 2026-05-01 v19.30.11 fork)

### 🎯 Just shipped 2026-05-01 v19.30.11 — see CHANGELOG (sixty-third commit)
**Pusher overload protection + skip-restart-if-healthy + system banner.**

Three coordinated fixes after operator hit a real outage:
- ✅ **Pusher RPC throttle**: bounded `Semaphore(4)` + circuit breaker (5 failures/10s → open 30s → half-open test → close) + per-method dedup on idempotent reads. Caps Spark→pusher concurrency below IB's 6-concurrent reqHistoricalData limit. Surface metrics in `/api/ib/pusher-health`.
- ✅ **Skip-restart-if-healthy guard** on both `start_backend.sh` and `scripts/spark_start.sh`. `--force` flag for genuine restarts. Cold-boot wait bumped 60s → 120s. Closes the "killed my own healthy backend" footgun.
- ✅ **`GET /api/system/banner`** + V5 SystemBanner.jsx — giant red strip when pusher_rpc red ≥30s OR mongo red ≥10s. Includes explicit "Do NOT restart Spark backend" action copy. Dismissable for 60s; reappears if persistent.
- ✅ 20 new pytests, **60/60 across v19.30 stack**. Live-validated in container.

### 🎯 Just shipped 2026-05-01 v19.30.10 — see CHANGELOG (sixty-second commit)
**Drop the "degraded mode" theatre — pusher-only with Mongo fallback.**

### 🎯 Just shipped 2026-05-01 v19.30.9 — see CHANGELOG (sixty-first commit)
**Degraded-mode UI fixes + cancel-all-pending-orders.**

3 surface bugs operator filed after the v19.30.8 wedge-immunity deploy:

- ✅ `/api/ib/account/positions` no longer 503's in degraded mode —
  falls back to `_pushed_ib_data["positions"]` with explicit
  `degraded:true` + `source:"pusher"|"pusher_stale"` flags. Same
  treatment applied to the alt `/account/summary` async handler.
- ✅ "Bar fetch failed" on V5 chart → root cause was sync pymongo
  `find().sort()` in `hybrid_data_service._get_from_cache` blocking
  the loop long enough for the 30s axios timeout. Both window
  query + stale fallback now `asyncio.to_thread`-wrapped. Same
  treatment applied to `_cache_bars` per-bar upsert loop.
- ✅ NEW `POST /api/trading-bot/cancel-all-pending-orders` —
  pre-open safety endpoint. Drains Mongo `order_queue` of
  pending+claimed rows + cancels direct IB-side open orders when
  reachable (graceful degradation). Requires `confirm:"CANCEL_ALL_PENDING"`
  token. Optional `symbols=[...]` scope + `dry_run:true` preview.
- ✅ 14 new pytests, **39/39 across v19.30 stack** (25 prior + 14
  new). 2 source-level pins so a future refactor can't silently
  re-introduce sync-mongo-in-async to the cache helpers.

Operator action:
```bash
cd ~/Trading-and-Analysis-Platform && git pull && ./start_backend.sh
```

### 🔴 P0 — Now unblocked by v19.30.9
1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency; fix Module Scorecard
   plumbing for `shadow_module_performance` per-vote breakdown.
2. **Bot Thoughts content capture** — Trail Explorer empty `content`.
3. **Verify v19.24 Reconcile endpoint live on Spark** — already
   shipped per PRD but never confirmed in production. Click
   "Reconcile N" in V5 Open Positions header on SBUX/SOFI/OKLO
   and verify they switch from `source:ib` to bot-managed payload.

### 🟡 P1 (unchanged from v19.30.8)
- Shadow-vs-Real gap drilldown (71% shadow vs 32% real).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares.
- **Async-pymongo audit follow-up** — 51 remaining sync-mongo-in-async
  sites (was 53; v19.30.9 closed 2 in `hybrid_data_service`).
- "PUSHER RED" while pusher is actually pushing (is_connected stale).
- `monitor_training.sh:149: [: 0: integer expression expected` bash
  arithmetic bug.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback (32 reference sites)
- **Audit Pass 1** — lint sweep + dead-code (370 ruff auto-fixes,
  61 bare excepts, 6 orphaned services, 3 dup function names in ib.py)
- **Audit Pass 3** — break up 4 monoliths (ib.py 6331, server.py
  4643, enhanced_scanner.py 7090, training_pipeline.py 3869)

---

## 🔴 Now / Near-term (next session pickup — 2026-05-02 v19.30.2 fork)

### 🎯 Just shipped 2026-05-02 v19.30.2 — see CHANGELOG (fifty-fourth commit)
**Bar-poll degraded-mode wedge fix.**

After v19.30.1 verified working live on Spark (200 OKs), a SECOND
wedge surfaced when the Windows IB pusher was OFF. `py-spy dump`
nailed it:

```
MainThread BLOCKED in:
  ib_pusher_rpc.py:124    _request          ← sync HTTP, 8s timeout
  ib_pusher_rpc.py:202    subscriptions
  bar_poll_service.py:229 _build_symbol_pools  ← sync def
  bar_poll_service.py:291 poll_pool_once       ← async caller!
```

What shipped:
- ✅ `poll_pool_once` now calls `_build_symbol_pools` via
  `asyncio.to_thread` — sync HTTP RPC + 3 sync mongo cursor iterations
  now run in a thread, loop stays responsive.
- ✅ Pusher RPC `subscriptions()` timeout dropped 8s → 3s
  (defense-in-depth bound).
- ✅ NEW `start_backend.sh` launcher at project root — handles venv
  activation, server kill, restart, 60s startup wait, health check,
  backpressure observability print. Operator no longer fights the
  venv dance every restart.
- ✅ 5 new pytests in `test_bar_poll_wedge_fix_v19_30_2.py`.
  **125/125 across v19 stack** including v19.30.1 + v19.30.2.

Operator action:
```bash
cd ~/Trading-and-Analysis-Platform && git pull && ./start_backend.sh
```

### 🟡 P1 — Bar-poll wedge fix follow-ups
- **Async-wrap the entire `_PusherRPCClient`** — add `async def
  subscriptions_async(self)`, etc., that own the `to_thread`
  internally. Prevents future async callers from re-introducing the
  same wedge.
- **Negative cache** — after 3 consecutive pusher RPC failures, skip
  the RPC for 60s (then 120s, 300s — exponential backoff). Today's
  fix bounds the per-call wedge at 3s but a fully-OFF pusher still
  costs 3s every 30s forever.
- Boot-time one-shot phantom sweep regardless of RTH.
- IB Gateway reconnect-on-timeout with exponential backoff.

### 🔴 P0 — Now unblocked by v19.30.1 + v19.30.2
The loop stays responsive in BOTH push-storm AND degraded-IB scenarios.
The rest of the v19.30 P0 stack is buildable:

1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency; fix Module Scorecard
   plumbing for `shadow_module_performance` per-vote breakdown.
2. **`POST /api/trading-bot/cancel-all-pending-orders`** — nuke
   pending GTC brackets at IB before market open.
3. **Bot Thoughts content capture** — Trail Explorer empty `content`.

### 🟡 Other P1 (unchanged from v19.30.1 fork)
- Shadow-vs-Real gap drilldown (71% shadow vs 32% real).
- Drift detector — CRITICAL stream when bot tracks <80% of IB shares.
- **(Deeper async-pymongo audit follow-up — Audit Pass 2a)** — the
  audit flagged 11 sync `def` handlers in hot routers and 54 inline
  sync mongo calls in async routes. The 2 wedge-causing ones (push-data
  + bar-poll) are fixed. Convert the remaining 53 incrementally as
  they surface as bottlenecks.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback (32 reference sites)
- **Audit Pass 1** — lint sweep + dead-code (370 ruff auto-fixes,
  61 bare excepts, 6 orphaned services, 3 dup function names in ib.py)
- **Audit Pass 3** — break up the 4 monoliths (ib.py 6242, server.py
  4643, enhanced_scanner.py 7090, training_pipeline.py 3869)

---

## 🔴 Now / Near-term (previous fork pickup — 2026-05-02 v19.30.1)

### 🎯 Just shipped 2026-05-02 v19.30.1 — see CHANGELOG (fifty-third commit)
**FastAPI event-loop wedge fix + push-data backpressure.**

The backend was wedging AFTER startup — `/api/health` would TCP-accept
but never return a byte. Three stacked bugs:

1. `/api/ib/push-data` was a sync `def` doing inline sync mongo
   `update_one` to `ib_live_snapshot`.
2. `tick_to_bar_persister.on_push()` ran inline inside that sync
   handler, holding a global lock + per-bar sync upserts.
3. `/api/health` was also sync `def` so it shared the saturated anyio
   thread pool — hence the 0-byte timeouts.

What shipped:
- ✅ `/api/health` `def` → `async def` (now event-loop-protected).
- ✅ `/api/ib/push-data` `def` → `async def` + `asyncio.to_thread`
  for snapshot upsert + tick_to_bar offload.
- ✅ NEW: 503 Retry-After:5 backpressure when ≥4 pushes in flight.
  Pusher backs off cleanly instead of timing out 120s.
- ✅ `/api/ib/status` + `/api/ib/pushed-data` `def` → `async def`.
- ✅ Bonus: fixed pre-existing `from database import get_db` typo
  (real symbol is `get_database`) — `ib_live_snapshot` writes from
  push-data finally work.
- ✅ `BriefMeAgent` injector switched to use `_pushed_ib_data` dict
  directly to avoid the now-async route handler shadow.
- ✅ 7 new pytests in `test_event_loop_wedge_fix_v19_30_1.py`.
  **120/120 combined across v19 stack.**
- ✅ Live verified locally: 30 parallel pushes + 5 health checks
  completed in 36ms total, all health 200, max latency 21ms.

Operator action — Spark deploy:
```bash
cd ~/Trading-and-Analysis-Platform
git pull
pkill -f "python server.py"
cd backend && nohup python server.py > /tmp/backend.log 2>&1 &
sleep 8
curl -s -m 5 localhost:8001/api/health  # MUST return instantly
```

### 🔴 P0 — Now unblocked by v19.30.1
Now that the loop stays responsive, the rest of the v19.30 P0 stack is
buildable:

1. **Diagnostics Data Quality Pack** — fix Pipeline Funnel
   `ai_passed`/`bot_fired` mutual consistency (currently shows 0% AI
   pass while SentCom Intelligence shows 60%); fix Module Scorecard
   plumbing so `shadow_module_performance` surfaces per-vote breakdown.
2. **`POST /api/trading-bot/cancel-all-pending-orders`** — nuke all
   pending GTC brackets at IB before market open to prevent naked
   shorts if positions are manually flattened.
3. **Bot Thoughts content capture** — Trail Explorer shows empty
   `content` field for fired trades.

### 🟡 P1
- Shadow-vs-Real gap drilldown — endpoint + UI panel showing why
  shadow win rate is 71% but real is 32% (which stop hit early?).
- Drift detector — CRITICAL Unified Stream event when bot tracks
  <80% of IB shares for any symbol.
- Boot-time one-shot phantom sweep regardless of RTH (so phantoms
  don't survive backend restarts).
- IB Gateway reconnect-on-timeout with exponential backoff.
- **(Deeper async-pymongo audit follow-up)** — the v19.30.1 audit
  flagged 11 sync `def` handlers in hot paths and 56 inline sync
  mongo calls in async handlers. The wedge-causing minority are
  fixed. The remaining ones are in low-frequency endpoints
  (`/api/ib/orders/*`, `/system-health`, `/training-status`,
  `/regime-live`, etc.) — convert to async incrementally as they
  surface as bottlenecks.

### 🟢 P2 / P3 (unchanged)
- v19.31 Pre-Aggregated Bar Pipeline (cold chart 400ms→30ms)
- v19.32 Chart WebSockets (live bar push, ~50ms vs 5s tail-poll)
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback
- Break up monolithic `server.py`

---

## 🔴 Now / Near-term (previous fork pickup — 2026-05-01 v19.29-validation-2)

### 🎯 Just shipped 2026-05-01 v19.29-validation-2 — see CHANGELOG (fifty-second commit)
**Morning Play A — clean slate reset for 2026-05-02 open.**
- ✅ `backend/scripts/reset_bot_open_trades.py` — one-shot Mongo
  cleanup script with --dry-run / --confirm RESET safety guard,
  symbol whitelist, 30d audit log to `bot_trades_reset_log`.
- ✅ `memory/MORNING_2026-05-02_PLAY_A.md` — paste-and-follow morning
  runbook (8:30 AM verification → 9:20 TWS flatten → 9:25 reset →
  9:27 restart → 9:30 watch).
- ✅ 16 new pytests + lint clean. 52/52 across reset + verify_v19_29
  harness + v19.29 hardening suites.
- ✅ Live diagnostics revealed Spark backend booted at 21:19 in
  degraded mode (IB Gateway TimeoutError at startup) — pusher works
  but direct IB connection failed; manage loop is RTH-gated so the
  v19.29 phantom sweep won't auto-fire until 9:30 AM ET. Hence the
  manual reset path tomorrow.

### 🔴 P0 — v19.30 Boot Hygiene Pack (~3-4h, scoped 2026-05-01 evening)
After tomorrow's clean-open observation, the right next-feature is a
3-piece pack that prevents tonight's diagnostic dance from recurring:

1. **Boot-time one-shot phantom sweep** — runs once at backend init
   regardless of RTH so phantoms don't survive backend restarts.
   Currently the manage loop is RTH-gated (correct for trail-stop
   ticks but wrong for phantom housekeeping).
2. **IB Gateway reconnect-on-timeout** — replace the silent
   `API connection failed: TimeoutError() → degraded paper mode
   forever` path with exponential-backoff retry (1s → 2s → 4s → 8s,
   max 30s, give up after 5min and surface CRITICAL alarm).
3. **Drift detector** — emit CRITICAL Unified Stream event when bot
   tracks <80% of IB shares for any symbol. Tonight we found BP at
   33%, CB at 50%, HOOD at 37%, SOFI catastrophic — all silent.
   Operator should see drift BEFORE it compounds.

### 🔴 P0 — Choose ONE for the session AFTER v19.30 Boot Hygiene
Both pre-scoped in this doc, ~6h each, pair beautifully:
- **v19.31 — Pre-Aggregated Bar Pipeline** (cold chart load 400ms→30ms)
- **v19.32 — Chart WebSockets** (live bar push, ~50ms vs 5s tail-poll)

Operator picks based on which feels more painful after using v19.28
Diagnostics + v19.30 Boot Hygiene for a few sessions.

### 🎯 Just shipped 2026-05-01 v19.29-validation — see CHANGELOG (fifty-first commit)
**RTH validation harness for v19.29.**
- ✅ `backend/scripts/verify_v19_29.py` — 6 read-only checks with
  colored output / JSON export / watch mode / optional active
  reconcile probe.
- ✅ `memory/V19_29_VALIDATION.md` — operator runbook with curl
  one-liners + post-pull workflow + failure-mode remediation.
- ✅ 21 new pytests; no production code touched.
- ✅ Smoke verified on preview backend: F=PASS / A,D=PENDING_RTH /
  B,C,E=NO_DATA (off-hours).

**Operator action — Spark side**:
1. `python -m backend.scripts.verify_v19_29` after pull + restart.
2. `--watch` mode during opening 30 min of RTH and again at
   3:40-4:00pm to validate gates D + E.
3. Once green sweep observed in production, pick v19.30 or v19.31.

### 🔴 P0 — pick after v19.29 RTH validation
- **v19.30 — Chart WebSockets** (~6-8h, fully scoped below)
- **v19.31 — Pre-Aggregated Bar Pipeline** (~6h, fully scoped below)
- These pair beautifully — v19.31's `on_bucket_close` hook becomes
  v19.30's WS publisher trigger. Operator picks based on which
  hurts more after using v19.28 Diagnostics for a few sessions.

### 🎯 Just shipped 2026-05-01 v19.26 — see CHANGELOG (forty-seventh commit)
**AI chat assistant data plumbing** — operator caught two same-session
bugs (SOFI stop missing, SQQQ no live quote) both rooted in
`chat_server._get_portfolio_context` reading from incomplete sources.
- ✅ **Bug 1 (SOFI stop)**: lazy-reconcile lookup in chat context
  surfaces `bot_trades.stop_price` + `target_prices` for IB orphans
  the bot doesn't track in `_open_trades`. Mirrors v19.23.1 V5 UI fix
  on the chat side.
- ✅ **Bug 2 (SQQQ no quote)**: ticker extraction from user message
  with trading-jargon denylist + live-snapshot + technicals fetched
  for up to 5 mentioned symbols, not just held positions and
  hardcoded indices.
- ✅ 12 new pytests (56/56 combined). Real `timedelta` shadow bug
  caught and fixed by ruff during this commit.

### 🎯 Just shipped 2026-05-01 v19.25 — see CHANGELOG (forty-sixth commit)
**Chart performance hardening — Tier 1 (cache) + Tier 2 (tail refresh).**
Closes operator's "very very delayed chart loading across the app"
complaint without WebSocket complexity.
- ✅ **`services/chart_response_cache.py`** — Mongo-backed TTL cache
  (30s intraday / 180s daily) on `/api/sentcom/chart`. Survives
  backend restarts via Mongo TTL index. ~0.003ms hit time vs full
  compute (~hundreds of ms - several seconds). Schema-versioned.
- ✅ **`/api/sentcom/chart-tail`** — incremental refresh endpoint.
  Returns only bars + indicator points + markers newer than `since`.
  Capped at 50 bars by default. Reads through the same cache.
- ✅ **`ChartPanel.jsx` stale-while-revalidate** — in-component cache
  hydrates state immediately on symbol/tf change, no spinner on
  refetch. Symbol-switch feels instant on previously-visited
  symbols.
- ✅ **Smart polling** — 5s `/chart-tail` polls during RTH on the
  focused chart, 30s outside RTH, paused entirely when tab hidden.
  Replaces the legacy 30s blanket polling that re-shipped 5,000
  bars every cycle.
- ✅ **Cache invalidation on fills** — `trade_execution.execute_trade`
  drops chart cache for the filled symbol so the new entry marker
  shows on the next render without waiting for TTL.
- ✅ 17 new pytests (44/44 combined with v19.23+v19.24). Ruff +
  ESLint clean. Live curl shows cache HIT in ~0.003ms.

### 🟡 Next session priorities

#### 🎯 Just shipped 2026-05-01 v19.29 — see CHANGELOG (fiftieth commit)
**Critical Trade Pipeline Hardening** — operator caught 5 stacked
bugs from EOD screenshot 2026-05-01:
- ✅ **Order intent dedup** — kills the 300+ duplicate cancelled
  orders pattern (BP/SOFI/BKNG/V/HOOD/MA spam)
- ✅ **Direction-safe reconcile** — 30s stability gate prevents
  catastrophic SOFI-SHORT-while-LONG bug from recurring
- ✅ **Wrong-direction phantom sweep** — auto-cleans the existing
  SOFI catastrophe at startup, no IB action fired
- ✅ **EOD no-new-entries gate** — soft cut 3:45pm / hard cut 3:55pm
- ✅ **EOD flatten escalation alarm** — CRITICAL Unified Stream
  event with minutes-to-close severity tier when flatten fails
- ✅ 15 new pytests (105/105 combined). Ruff clean on new code.

#### 🟡 Next session menu (unchanged from v19.28 — pick what helps tuning most):

#### 🎯 Just shipped 2026-05-01 v19.28 — see CHANGELOG (forty-ninth commit)
**Diagnostics tab MVP** — new top-level side-nav tab unifying shadow
trades / actual trades / scans / AI reasoning into one drilldown
+ aggregate views. 5 read-only endpoints powering 4 sub-tabs:
- ✅ **Trail Explorer**: pick any decision → see scanner alert / AI
  module votes / bot decision / bot thoughts as a vertical timeline
- ✅ **Module Scorecard**: per-AI-module accuracy / P&L (followed vs
  ignored) / weight / 🔴 kill-candidate flag
- ✅ **Pipeline Funnel**: emitted → AI-passed → risk-passed → fired
  → winners with conversion %, abnormal drops highlighted
- ✅ **Export Report**: one-click markdown for paste-to-Emergent
  tuning conversations
- ✅ 16 new pytests (90/90 combined). Live verified — all 5 endpoints
  HTTP 200, frontend renders cleanly.

#### 🟡 Next session menu — pick what helps tuning most:

**Option A (most leverage)**: v19.29 — **EOD Insight Stream + Inline drilldowns** (~6h)
- New "Insights" sub-tab on Diagnostics: LLM auto-generates 3-7
  bullets each EOD ("Debate's bear vote was right 80% on momentum
  but you ignored it 70% — consider weighting Bear higher on
  momentum-class setups"). Uses chat_server stack.
- Inline drilldown drawer: click any row in V5 Open Positions /
  Scanner Cards / Unified Stream → trail opens in a side drawer.
  Eliminates the "open Diagnostics, search, find it" friction.

**Option B**: v19.29 — **Tier 3 chart WebSocket** (~6-8h)
- Push new bars to charts within ~50ms (replaces 5s polling).
- Operator approved earlier; full design spec below.

**Option C**: v19.29 — **Pre-aggregated bar pipeline** (~6h, scoped 2026-05-01)
- Eliminates on-the-fly bar aggregation. When a 1-min bar lands
  in Mongo, write the corresponding 5m/15m/1h bars at the same
  time. Chart cold-load drops from ~400-1200ms to ~30-60ms.
- Backfill strategy: **lazy + warm pool on startup** — the 30
  most-recently-viewed symbols × last 30 days get pre-aggregated
  in the background (~10min total); all other symbols use
  fallback path until first viewed, then self-warm. Self-
  optimizing — frequently-used symbols stay fast forever.
- Skip 1day timeframe (180s v19.25 cache already covers it).
- Pairs perfectly with WebSocket (Option B): the aggregator's
  `on_bucket_close(symbol, tf, bar)` hook is exactly what the
  WS publisher needs to push new 5m/15m/1h bars.
- Full spec section below.

**Option D**: v19.29 — **Cohort Comparator + Counterfactual Playground** (~12h)
- "Pick 2 cohorts (e.g. all SOFI long where Debate=BUY but bot
  passed) and compare R-distributions side-by-side"
- "If I'd raised setup_min_rr on momentum from 1.7 → 2.0 last 30d,
  here's what would've happened"
- Heaviest piece, but the prize for closed-loop calibration.

**Option E**: Operator chooses based on first-day Diagnostics use.

#### 🔴 (P0 — verify on Spark)
- **v19.28**: Pull + open Diagnostics tab → Trail Explorer / Module
  Scorecard / Funnel / Export should all populate with real data.
- **v19.27**: Smart source detection on positions panel — partial
  drift rendered correctly, OKLO 0sh phantom auto-swept.
- **v19.26**: Chat assistant — SOFI stop, SQQQ live quote.
- **v19.25**: Chart cache + tail polling latency.
- **MultiIndexRegime live curl during RTH.**

#### 🟡 P1 backlog
- HOOD chart wrong-prices `useEffect` — likely resolved by v19.25
- Per-setup R:R operator overrides → `RiskParameters.setup_min_rr` defaults
- `cpu_relief_manager.is_active()` into deferable paths + RPC-latency auto-trigger
- `SectorRegimeClassifier` end-to-end verification

#### 🟢 P2 / P3 backlog
- Setup-landscape EOD self-grading tracker
- Mean-reversion metrics (Hurst + OU half-life)
- Liquidity-aware trail in `stop_manager.py`
- Scanner card "Proven / Maturing / Cold-start" badge
- Chart bubble click → `sentcom:focus-symbol`
- SEC EDGAR 8-K integration
- Safely retire Alpaca fallback
- Break up monolithic `server.py`

#### 🔴 (P0 conditional — only ship if v19.25 not enough) v19.30 — Tier 3 chart WebSocket layer
**Goal**: Push new bars to the chart within ~50ms of IB delivering them,
replacing the 5s polling cycle entirely. T1 (cache) + T2 (tail) already
killed ~95% of the perceived slowness; Tier 3 closes the last 5%
poll-cycle latency for fast-tape moments.

#### 🔴 (P0 — fully scoped 2026-05-01) v19.31 — Pre-Aggregated Bar Pipeline
**Goal**: Eliminate on-the-fly bar aggregation. When a 1-min bar lands
in Mongo, immediately write the corresponding 5m / 15m / 1h bars at
the same time. Chart cold-load drops from ~400-1200ms to ~30-60ms
(no aggregation compute, just a key lookup). This is the single
remaining architectural gap between SentCom and the consumer
charting platforms (TradingView, TC2000, Finviz) — they all
pre-aggregate on ingest, never on read.

**Cost**: $0 — all work runs on existing DGX CPU + disk you own.
3-5× storage growth on `ib_historical_data` (1m + 5m + 15m + 1h
rows per symbol-bucket) is free disk.

**Skip 1day** — the v19.25 180s cache already makes daily charts
feel instant. Adding daily pre-aggregation = complexity for no win.

**Backfill strategy: lazy + warm pool**
1. **On startup**, read `chart_response_cache` history → identify
   the 30 most-recently-viewed symbols.
2. Background-aggregate those 30 symbols × last 30 days
   (~10 min total). Non-blocking, gated by
   `cpu_relief_manager.is_active()` so it backs off if RTH is busy.
3. **On every chart load**, if no pre-aggregated bars exist for
   the requested window:
   - Serve via the existing on-the-fly fallback (~400-1200ms,
     same as today)
   - Trigger a background aggregation of THAT symbol's full history
   - Next load is instant
4. Self-optimizing: symbols you actively chart get fast and stay
   fast; symbols you never look at never waste compute.

**Storage shape (extends current schema, no new collections)**
```
ib_historical_data {
  symbol, timeframe, time, open, high, low, close, volume, vwap,
  source, partial?
  // existing rows: timeframe = "1min"
  // v19.31 adds rows where timeframe ∈ {"5min", "15min", "1hour"}
}
```
Existing compound index `(symbol, timeframe, time)` already covers
the new query path. No schema migration needed.

**Aggregation engine** (`services/bar_aggregator.py`, new)
```
On every 1-min bar write:
  bucket_5m  = align(bar.time, 5min)   # 09:30, 09:35, 09:40...
  bucket_15m = align(bar.time, 15min)
  bucket_1h  = align(bar.time, 60min)
  for each higher_tf:
    upsert ib_historical_data {symbol, tf, time: bucket_start}:
      open  = first 1m bar in bucket
      high  = max(high) across bars
      low   = min(low) across bars
      close = latest 1m bar
      volume = Σ(volume)
      vwap   = Σ(typical_price × volume) / Σ(volume)
      partial = true if bucket isn't full (last bar of session)
```

**Boundary alignment**
- Anchored to session open (RTH = 9:30 ET, premarket = 4:00 ET)
- Last 5m of RTH may be a 4-min "partial" bar at 15:56-16:00 ET —
  flagged with `partial: true` so the chart can render correctly
- Out-of-order 1m arrival re-computes the affected higher-TF
  bucket atomically via `findAndModify` upsert

**Integration points**
| Component | Change |
|---|---|
| `bar_poll_service` | After persisting a 1-min bar, call `bar_aggregator.on_new_bar(symbol, bar)` |
| `routers/ib._pushed_ib_data` writer | Same hook — when ticks assemble into a partial bar, the in-memory partial is broadcast at every TF boundary |
| `hybrid_data_service.get_bars` | Reads pre-aggregated rows directly via `find({symbol, timeframe})`. Fallback to on-the-fly if zero docs found. |
| `sentcom_chart` router | Unchanged |
| `chart_response_cache` (v19.25) | Unchanged — but each cache miss is now ~50ms instead of ~500ms |
| `chart_ws` (v19.30 when shipped) | Aggregator's `on_bucket_close(symbol, tf, bar)` hook becomes the WS publisher trigger |
| `bot_state.aggregator_cursors` | New persisted dict `{symbol: last_aggregated_iso}` so backfill resumes after restart |

**Expected numbers**
| Metric | Today | After v19.31 |
|---|---|---|
| Cold chart load (5m, 5d) | ~400-1200ms | **~30-60ms** |
| Hot chart load (v19.25 cached) | ~5ms | ~3ms |
| Storage `ib_historical_data` per symbol/yr | ~120MB at 1m | ~150MB (5m=20%, 15m=7%, 1h=2%) |
| Aggregation CPU per new 1m bar | 0 | ~30-80ms (fits in 5s scanner cycle) |
| WebSocket publish latency (when v19.30 ships) | N/A | ~50ms IB tick → frontend candle update |

**Risk + safety**
- Backfill during RTH: gated by `cpu_relief_manager.is_active()`
  to cap at ~5% CPU
- Out-of-order arrivals: atomic upsert re-computes affected bucket
- Bug-corrupted higher-TF rows: `--rebuild` flag drops + re-
  aggregates all higher-TF for a symbol, ~1min per year of data
- Storage sprawl: per-symbol `pre_aggregated_storage_kb` stat in
  Diagnostics > Funnel sub-tab; alert if total >10GB

**Tests** (`test_bar_aggregator_v19_31.py`)
- 5m alignment: 9:30, 9:35, 9:40 (not 9:31, 9:36)
- High/low/volume math correctness on a known 5-bar set
- Partial last-bar flag when bucket isn't full
- Idempotent re-run produces identical output
- Out-of-order 1m arrival re-computes affected buckets
- Backfill cursor resumes correctly after restart
- `cpu_relief_manager` gate skips aggregation when CPU pressure high
- Falls back to on-the-fly when pre-aggregated row missing
- Lazy backfill triggers on first chart-load miss
- Warm pool seeds 30 most-recently-viewed symbols on startup

**Effort**: ~6 hours. Best paired with v19.30 WebSocket since the
aggregator's `on_bucket_close` hook is exactly what the WS publisher
needs. Can ship before or after — operator decides after using
v19.28 Diagnostics for a few sessions.

**Design (locked-in spec — ship as-is unless operator overrides)**:

**Backend** — new `routers/chart_ws.py`
```
WS endpoint: /api/ws/chart/{symbol}/{timeframe}
  - On connect:
      1. server.send_json({"type": "hydrate", ...full /chart payload})
         — sourced from chart_response_cache for instant hydration
         (zero compute, ~0.003ms cache hit + ~5ms wire time)
      2. server enrolls (symbol, tf) in pub-sub registry
  - On every new bar from the pusher:
      server.send_json({"type": "bar", "bar": {...}, "indicators_tail": {...}})
  - On bot fill for symbol:
      server.send_json({"type": "marker", "marker": {...}})
  - On disconnect:
      Remove from pub-sub registry. No reconnect logic on backend
      (frontend handles exponential backoff).
```

**Backend pub-sub** — new `services/chart_ws_broker.py`
- Process-wide singleton `ChartWSBroker`
- `subscribe(ws, symbol, tf)` / `unsubscribe(ws)` 
- `await broker.publish_bar(symbol, tf, bar_dict)` — fanout to all WS
  clients subscribed to (symbol, tf). Best-effort: dropped clients
  cleaned up silently.
- Hook publish_bar into TWO places that already see fresh bars:
  1. `services/bar_poll_service.py` — when a new bar lands in
     `ib_historical_data`, publish.
  2. `routers/ib.py` `_pushed_ib_data["quotes"]` update path — when
     a new tick assembles into a partial bar, publish.
- Hook `publish_marker` into `services/trade_execution.py` right
  next to the existing `chart_response_cache.invalidate(...)` call.

**Frontend** — new hook `frontend/src/hooks/useChartLiveStream.js`
```js
useChartLiveStream(symbol, timeframe, {
  onBar:    (bar)    => candleSeries.update(bar),
  onMarker: (marker) => setMarkers(prev => [...prev, marker]),
  onHydrate:(payload)=> setBars(payload.bars), // first-paint fallback
})
- Auto-connects on mount, reconnects with exponential backoff
  (1s, 2s, 4s, 8s, max 30s) on disconnect
- Pauses when document.visibilityState !== 'visible' (same rule as
  the smart-polling loop)
- Clean unmount on symbol/tf change
- Returns {connected: bool, lastBarTs: number} for the
  ChartHeader status chip
```

**Wire into `ChartPanel.jsx`**:
- Add `useChartLiveStream(symbol, active.value, {...callbacks})`
- Keep `/api/sentcom/chart` cold-load fetch (still needed for
  cacheKey-driven hydration on cold cache)
- KEEP smart-polling 5s `/chart-tail` as a FALLBACK when WS is
  disconnected — don't rip it out, just gate it on
  `wsConnected === false`. Belt-and-braces.

**Backend integration with existing pusher pipeline**:
- The pusher already pushes ticks via `POST /api/ib/push-data` →
  `_pushed_ib_data["quotes"]`. The bar assembly happens in
  `bar_poll_service.py`. So the WS broker just needs to be called
  from the existing assembly path — no new RPC/IB integration.

**Estimated effort**: 6-8 hours
- Backend broker + ws router: 3h
- Frontend hook + ChartPanel wire: 2h
- Pub-sub hooks into bar_poll_service + trade_execution: 1h
- Tests (mock WS connections via httpx-ws or starlette TestClient
  with WS support): 2h

**Tests to ship with it**:
- `test_chart_ws_broker.py` — subscribe/unsubscribe/publish/cleanup
- `test_chart_ws_router.py` — connect → hydrate → bar push → disconnect
- `test_useChartLiveStream.js` — exponential backoff, visibility pause
- Source-level pin asserting `chart_ws_broker.publish_bar` is called
  from `bar_poll_service` (regression guard for v18 architecture)

**Operator-facing surfaces**:
- `GET /api/diagnostic/chart-ws-status` — connected client count,
  per-symbol subscription count, p95 publish latency
- V5 ChartHeader chip showing `LIVE` (WS connected) / `POLL` (WS
  fallback to /chart-tail) so operator sees the state

**Risk / things to watch**:
- WS connection limits — Spark is single-process, but FastAPI/
  Uvicorn handles ~10K concurrent WS by default. Operator unlikely
  to ever hit this. Document the ceiling for future scale.
- Backpressure — if a client falls behind (slow network), don't
  block the publish path. Use `asyncio.wait_for(send, timeout=0.5)`
  and drop the client on timeout.
- Hot-reload safety — broker MUST survive uvicorn reload during dev.
  Singleton pattern + module-level registration handles this.

**Why NOT do this now**:
- T1 + T2 already eliminate ~95% of the perceived slowness without
  the complexity of WS reconnect logic, backpressure handling, and
  pub-sub state.
- Operator wants to verify T1 + T2 on Spark first. If they're
  satisfied, T3 becomes optional polish. If they still feel lag,
  T3 is the fix and the design above is ready to ship.

#### Other priorities (after Tier 3 ships)
- **(P0 — operator verification on Spark — v19.25)** After pull + restart:
  1. Check `cache: 'hit'` field appears on `/api/sentcom/chart`
     responses in the network tab on the second+ load.
  2. Confirm `/api/sentcom/chart-tail?since=<ts>` polls every 5s
     during RTH, paused outside RTH, paused when tab hidden.
  3. Symbol-switch on a previously-visited symbol should feel
     instant (no spinner, chart re-paints sub-100ms).
  4. After a real trade fills, the new entry marker should appear
     on the chart within 5s (next tail poll), not 30s+.
- **(P0 — reconcile UX verification — v19.24)** — operator action item:
  click **Reconcile N** on SBUX/SOFI/OKLO once IB pusher is live,
  confirm bot picks them up.
- **(P0 verify)** MultiIndexRegime live curl on Spark during RTH.
- **(P1) HOOD chart wrong-prices `useEffect` chain** — likely
  resolved as a side-effect of v19.25 cacheKey-driven hydration but
  worth confirming with the operator.
- **(P1) Per-setup R:R overrides as code defaults.**
- **(P1) `cpu_relief_manager.is_active()` into deferable paths.**
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P1) `SectorRegimeClassifier` end-to-end verification.**
- **(P2) Setup-landscape EOD self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" badge.**
- **(P3) Chart bubble click → `sentcom:focus-symbol`.**
- **(P3) SEC EDGAR 8-K integration.**
- **(P3) Safely retire Alpaca fallback.**
- **(P3) Break up monolithic `server.py`.**

### 🎯 Just shipped 2026-05-01 v19.24 — see CHANGELOG (forty-fifth commit)
**P0 proper reconcile + MultiIndexRegime source-level pins.**
- ✅ **`POST /api/trading-bot/reconcile`** — write-through
  counterpart to v19.23.1 lazy-reconcile. Materializes real
  BotTrade records for IB-only orphans (SBUX/SOFI/OKLO) so the bot's
  manage loop can actively trail stops, scale-out, and EOD-close
  them. Modes: `{symbols: [...]}` (explicit) or `{all: true,
  confirm: "RECONCILE_ALL"}` (sweep). Per-request `stop_pct`/`rr`
  overrides.
- ✅ **`RiskParameters.reconciled_default_stop_pct=2.0`** +
  `reconciled_default_rr=2.0`. Persisted through
  `bot_state.risk_params`, surfaced in `/api/trading-bot/status`.
- ✅ **Safety guards** — stop-already-breached skip (never insta-stop
  trades), already-tracked skip (idempotent), no-ib-position skip,
  pusher-disconnected fail-closed, `all=true` requires confirm token.
- ✅ **`OpenPositionsV5` Reconcile N button** — appears in panel
  header only when ≥1 orphan (`source === 'ib'`) is present.
  `window.confirm` → POST → toast with counts.
- ✅ **MultiIndexRegime source-level pins** — `_apply_setup_context`
  + `LiveAlert` + `_refresh_cycle_context` contracts pinned at
  pytest time so a future refactor can't silently drop the
  `multi_index_regime` stamping path.
- ✅ **21/21 new pytests**, **27/27 combined w/ v19.23 suite.**
  ESLint clean.

### 🟡 Next session priorities
- **(P0 — user verification on Spark)** After pulling v19.24:
  1. Restart backend.
  2. Confirm `reconciled_default_stop_pct=2.0` / `reconciled_default_rr=2.0`
     via `curl localhost:8001/api/trading-bot/risk-params`.
  3. Click **Reconcile 3** button in V5 Open Positions header on
     SBUX/SOFI/OKLO and verify the 3 positions switch from
     `source:ib` to the full bot-managed payload + begin appearing in
     manage-loop actions (trail stop ticks, scale-out on PT hit, etc.)
  4. **MultiIndexRegime live check**:
     `curl localhost:8001/api/scanner/live-alerts?limit=5 |
      jq '.alerts[].multi_index_regime'` — should print real labels
     (`risk_on_broad`, etc.), not `"unknown"`. If `"unknown"`,
     investigate `_refresh_cycle_context` cache hookup.
- **(P1) HOOD chart wrong-prices `useEffect` chain** investigation in
  `ChartPanel.jsx`.
- **(P1) Per-setup R:R overrides as code defaults** — operator
  curled 7 overrides in this session. Promote into `RiskParameters.
  setup_min_rr` defaults so fresh deploys pick them up without
  curl-merge.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency**.
- **(P1) `SectorRegimeClassifier` end-to-end verification** — same
  pattern as MultiIndexRegime: pin in pytest + curl on Spark.
- **(P2) Setup-landscape EOD self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.
- **(P3) Chart bubble click → fire `sentcom:focus-symbol` event so
  operator can chat-coach any moment in the day with one click.**
- **(P3) SEC EDGAR 8-K integration for material events.**
- **(P3) Safely retire Alpaca fallback.**
- **(P3) Break up monolithic `server.py`** (Wait until pipeline is
  100% stable).

### 🎯 Just shipped 2026-05-01 v19.23.1 — see CHANGELOG (forty-fourth commit)
**Operator screenshot review on v19.23 deploy → 4 follow-ups in one commit.**
- ✅ **Lazy-reconcile SL/TP for IB-only positions.** `get_our_positions`
  scans Mongo `bot_trades` for matching symbols and stamps stop/target +
  rich entry context onto IB-side positions. SBUX/SOFI/OKLO now show
  red SL + green PT lines on the chart and real values in the OPEN
  panel grid. Status normalized `ib_position` → `open`.
- ✅ **Tier chip humanization.** 22-name `STYLE_HUMAN_MAP` so
  `trade_2_hold` → `DAY 2`, `opening_range_break` → `ORB`,
  `9_ema_scalp` → `9-EMA`, etc. Unknowns fall back to underscore-strip
  + 12-char truncate.
- ✅ **Share size visible everywhere.** `Nsh` is now the lead element
  on the OpenPositionsV5 model-trail subtitle, a chip on
  ScannerCardsV5 manage-stage cards, the lead in the bot narrative
  line, and the right-edge of the V5ChartHeader chip strip.
- ✅ **Chart bubble kind filter loosened.** Allows `filter` and `info`
  events with non-empty `content`. Operator's SBUX deep-feed events
  should now render as bubbles.
- ✅ 6/6 backend pytests passing (added
  `test_lazy_reconcile_enriches_ib_position_with_bot_trade_levels`).
  ESLint clean.

### 🟡 Next session priorities

- **(P0) `POST /api/trading-bot/reconcile`** (proper, heavier).
  Lazy-reconcile is read-only — it doesn't materialize bot_trade rows
  for orphaned IB positions, so the bot can't actively manage them
  (trail stop, scale-out, EOD-close). Build proper endpoint that
  POSTs `{symbols: [...]}` and creates real bot_trades, applies
  default stop/target overlays, and starts RTH management.
- **(P0) MultiIndexRegimeClassifier** verification curl on Spark.
- **(P1) HOOD chart wrong-prices `useEffect` chain** investigation.
- **(P1) Per-setup R:R overrides as code defaults.**
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P2) Setup-landscape EOD self-grading.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.
- **(P3) Chart bubble click → fire `sentcom:focus-symbol` event so
  operator can chat-coach any moment in the day with one click.**

### 🎯 Just shipped 2026-05-01 v19.23 — see CHANGELOG (forty-third commit)
**V5 mockup compliance pass — operator surfaced 4 paper-cuts after the
v19.22.x bracket save, all addressed in one commit.**
- ✅ **Issue #1 — Open Positions $0 PnL + missing detail.** Frontend
  `OpenPositionsV5.jsx` now renders the v19.22.3 backend payload:
  compact rows with sparkline + tier chip + 1-line model trail; click
  chevron to expand into Entry/Last/Stop/PT grid + R:R/Risk/Reward/Shares
  + trailing-stop state + scale-out targets + AI reasoning bullets +
  setup/grade footer.
- ✅ **Issue #3 — Chart annotations.** New
  `ChartThoughtBubblesOverlay.jsx` paints chat-bubble annotations from
  `sentcom_thoughts` over the chart, color-coded by kind, anchored to
  bar timestamps via `timeScale.timeToCoordinate`. Bottom timeline rail
  with click-to-jump. New `Bot` toggle in chart header. Existing E/SL/PT
  price lines + entry/exit markers preserved.
- ✅ **Issue #3 sub — V5 chart header strip.** Mirrors the mockup:
  Symbol · STATUS·age · $price · ±change% · Entry · SL · PT · R:R · Nsh.
  Live current_price + direction-aware change%. Status chip reads
  `position.status` and shows age relative to `entry_time`. R:R now
  uses correct `risk_reward_ratio` field with legacy fallback.
- ✅ **Issue #2 — Pipeline HUD width.** Stages basis-2/3 → 3/5 with
  shrink allowance; right cluster basis-1/3 → 2/5 with shrink-0 so
  7-figure margin balances + 6 inline chips never clip. Stage
  internals tightened (px-2 py-1.5, text-xl) without losing legibility.
- ✅ **Issue #4 — Scanner card tier + setup + reasoning.**
  `ScannerCardsV5` renders tier chip (INTRADAY/SWING/POSITION) +
  setup-type chip (Bellafiore Trade name, humanized) inline alongside
  the stage chip. Alert `bot_text` fallback now joins first 2
  `reasoning[]` entries so chain-of-thought rides the headline.
- ✅ 5 new pytests in `tests/test_open_positions_payload_v19_23.py`
  pinning the position payload contract. **5/5 passing.** ESLint clean.

### 🟡 Next session priorities

- **(P0) MultiIndexRegimeClassifier** verification curl on Spark — was
  shipped 2026-04-30 per CHANGELOG but operator hasn't confirmed
  `LiveAlert.multi_index_regime` is firing on live alerts. Run:
  `curl -s http://localhost:8001/api/scanner/live-alerts?limit=5 |
  jq '.alerts[].multi_index_regime'`. If null, investigate
  `_apply_setup_context` per-cycle cache hookup.
- **(P1) `/api/trading-bot/reconcile`** — let the bot claim untracked
  IB positions (NVDA/TSLA/GOOGL — operator pinned). New endpoint posts
  `{symbols: [...]}` + uses pusher's account snapshot to materialize
  bot trades + apply default stop/target overlays + start RTH
  management.
- **(P1) HOOD chart wrong-prices UI bug** — operator hard-refresh fix;
  investigate `useEffect`/symbol-prop chain in `ChartPanel.jsx` to make
  re-fetch deterministic on symbol change.
- **(P1) Per-setup R:R overrides as code (not curl)** — operator
  curled in 7 extras this session. Add to `RiskParameters.setup_min_rr`
  dict default in `trading_bot_service.py` so a fresh deploy picks
  them up without curl-merge.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P2) Setup-landscape self-grading tracker EOD wiring.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**
- **(P3) Scanner card "Proven / Maturing / Cold-start" confidence
  badge** based on `strategy_stats.r_outcomes` length.

### 🎯 Just shipped 2026-05-01 v19.22.1 + v19.22.2 — see CHANGELOG (forty-second commit)
**Live RTH save: HOOD GO 52pts → fill in 60s of deploy.**
- ✅ **v19.22.1** Bracket order handler in Windows pusher — was rejecting
  ~63% of orders with "Unknown order type: bracket". Now constructs
  proper IB 3-leg parent + stop + target with linked parentId/transmit
  chain. Live proof: 14 fills in 15 min post-deploy.
- ✅ **v19.22.1** Dropped `outsideRth=True` on STP leg (IB ignores +
  warns). TP leg keeps it.
- ✅ **v19.22.2** `/reset-rr-defaults` async fix — handler now `async
  def` and awaits Mongo save, returns `persisted_to_mongo` flag.
  Previously fire-and-forget create_task() lost the write across
  restarts.
- ✅ Operator applied via curl: global `min_risk_reward=1.7`,
  added 7 mean-reversion setup overrides (`off_sides`, `volume_
  capitulation`, `backside`, `bella_fade`=1.5, `fashionably_late`=2.0).
- ✅ 24 / 24 pytests pass across v19.20 + v19.21 + v19.22.x.

### 🟡 Next session priorities
- **(P1) HOOD chart wrong-prices UI bug** — backend returns correct
  $73 bars, frontend renders $265-$280 (likely stale symbol state).
  Operator hard-refresh fixed it ad-hoc; investigate the
  `useEffect`/symbol-prop chain in `ChartPanel.jsx` to make the
  re-fetch deterministic on symbol change.
- **(P1) Apply per-setup R:R overrides as code (not curl)** — operator
  curled in 7 extras this session. Add them to the
  `RiskParameters.setup_min_rr` dict default in
  `trading_bot_service.py` so a fresh deploy picks them up without
  needing the curl-merge dance.
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable
  paths** (EVAL historical, daily collect, periodic backfill).
- **(P1) Auto-trigger relief based on RPC latency.**
- **(P1) Setup-landscape self-grading tracker.**
- **(P2) Mean-reversion metrics (Hurst + OU half-life).**
- **(P2) Liquidity-aware trail in `stop_manager.py`.**

### 🎯 Just shipped 2026-05-01 v19.22 — see CHANGELOG (forty-first commit)
News pruning + ML Feature Audit panel:
- ✅ `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN` env — filters live IB list
  without touching Gateway settings. Override env still wins absolutely.
- ✅ Trimmed default fallback `[BZ, DJ, BRFG]` (was 5-vendor).
- ✅ `MLFeatureAuditPanel.jsx` mounted in V5 right column —
  click any $TICKER → instant audit of which label-features fire
  (market_setup + multi_index_regime + sector_regime).
- ✅ `CpuReliefBadge` mounted next to it — manual throttle toggle.
- ✅ 6 new pytests, 147/147 pass across full v19 stack.

**Operator action needed on DGX**: add `IB_NEWS_PROVIDER_EXCLUDE=FLY,BRFUPDN`
to `/app/backend/.env` and `sudo supervisorctl restart backend` — the
filter only takes effect on next backend boot.

### 🎯 Just shipped 2026-05-01 v19.21 — see CHANGELOG (fortieth commit)
HOOD R:R fix + verification surfaces + briefing widgets + CPU relief:
- ✅ Per-setup R:R floors (mean-reversion=1.5, breakout/trend=2.0,
  global=1.7). Gap_fade @ 2.05 R:R now passes; HOOD regression closed.
- ✅ `RiskParameters.effective_min_rr()` resolver with suffix stripping
  (`_long`/`_short`/`_confirmed`).
- ✅ `update_risk_params(setup_min_rr={...})` merges, doesn't replace.
- ✅ Persistence round-trip is lossless for `setup_min_rr`.
- ✅ New endpoints: `GET /api/trading-bot/risk-params` (live + resolved),
  `POST /api/trading-bot/reset-rr-defaults` (one-curl rescue),
  `GET /api/scanner/ml-feature-preview/{symbol}` (verifies all 3 ML
  label-feature layers fire).
- ✅ Premarket Gap-Scanner widget — live scrollable list of gappers
  in last N min, mounted in `MorningBriefingModal`.
- ✅ `sentcom:focus-symbol` global event wired into `SentCom.jsx` chat —
  any `$TICKER` click auto-fires "walk me through $SYM right now".
- ✅ CPU-relief toggle (`/api/ib/cpu-relief`) with `until=HH:MM` window,
  deferred-call counter, UI badge. Smart-backfill respects it.
- ✅ `IB_NEWS_PROVIDER_OVERRIDE` env so operator can clamp news vendors.
- ✅ 17 new pytest cases. 141/141 pass across the v19 stack.

### 🟡 Next session priorities
- **(P1) Wire `cpu_relief_manager.is_active()` into more deferable paths**
  (eval-time historical pulls, daily collect, periodic backfill loops).
  Right now only `smart_backfill` defers. The infrastructure is in
  place — each new caller is a one-line check.
- **(P1) Auto-trigger relief based on RPC latency** — watch
  `/api/ib/pusher-health` avg latency. If >2s sustained 60s, flip on;
  reset when latency drops <800ms 60s. (Operator chose manual+timed
  this round; auto is a future enhancement.)
- **(P1) Setup-landscape self-grading tracker** — record briefing
  predictions, grade EOD, feed AI training pipeline.
- **(P2) Mean-reversion metrics service** — Hurst exponent +
  Ornstein-Uhlenbeck half-life per symbol.
- **(P2) Realtime stop-guard re-check** — liquidity-aware trail in
  `stop_manager.py`.
- **(P3) Break up monolithic `server.py`.**

### 🎯 Just shipped 2026-05-01 v19.20 — see CHANGELOG (thirty-ninth commit)
Deep Feed noise cleanup (Phase 1) + Morning Briefing depth (Phase 2):
- ✅ Enabled 11 real playbook setups that were silently sitting in
  `setup_disabled` limbo (`bouncy_ball`, `the_3_30_trade`,
  `vwap_continuation`, `premarket_high_break`, `trend_continuation`,
  `base_breakout`, `accumulation_entry`, `back_through_open`,
  `up_through_open`, `daily_breakout`, `daily_squeeze`).
- ✅ Base-setup splitter now also strips `_confirmed` so
  `range_break_confirmed` / `breakout_confirmed` / `breakdown_confirmed`
  resolve to their enabled base setups.
- ✅ Watchlist-only setups (`day_2_continuation`, `carry_forward_watch`,
  `gap_fill_open`, `approaching_*`) bypass the bot evaluator silently.
- ✅ Sizer now clamps to SafetyGuardrails `max_symbol_exposure_usd`
  so sizes never exceed the safety cap → killed the
  `symbol_exposure $49,986 > $15,000` rejection cascade.
- ✅ Squeeze stop clamped to `max(bb_lower, current - atr*1.0)`
  — R:R holds above 1.5 on mega-caps now.
- ✅ Rejection dedup — 2-min TTL cache by `(symbol, setup, reason)`
  kills duplicate feed spam.
- ✅ New `gameplan_narrative_service.py` + `/api/journal/gameplan/narrative/{symbol}`
  endpoint — returns bullets, levels grid, and an Ollama GPT-OSS 120B
  2-3 sentence trader narrative with `$TICKER` clickable chips.
- ✅ New `GamePlanStockCard.jsx` wired into `MorningBriefingModal.jsx`
  — per-stock expandable cards with levels, triggers, targets,
  invalidation, and AI read.
- ✅ 13 new pytest cases (`test_feed_noise_fixes_v19_20.py`,
  `test_gameplan_narrative_v19_20.py`). 122/122 pass across v19
  + market-setup + landscape suites.

### 🟡 P0/P1 — Next session priorities
- **(P0) Build `MultiIndexRegimeClassifier`** — read SPY/QQQ/IWM/DIA
  daily+intraday, compute breadth + divergence, emit a composite
  regime label plumbed into `LiveAlert` as a soft-gate ML feature.
- **(P1) Build `POST /api/trading-bot/reconcile`** — let the bot
  explicitly claim the 3 untracked IB positions (NVDA, TSLA, GOOGL)
  into `_open_trades` so they get RTH management + EOD handling.
- **(P1) Close the ML learning loop** — plumb `market_setup` +
  `multi_index_regime` into the per-Trade ML feature vector.
- **(P1) Premarket Gap-Scanner UI widget** — scrollable list of
  what gapped in the last 8 mins.
- **(P1) SectorRegimeClassifier** — per-sector ETF regime tags
  feeding `LiveAlert.sector_regime`.

### 🎯 Just shipped 2026-04-30 v19.19 — see CHANGELOG (thirty-eighth commit)
Premarket scan cadence + heartbeat fixes:
- ✅ Premarket cadence tightened `% 10` → `% 2` (20 min → 4 min real
  scans). 37 refreshes over 7:00-9:30 AM ET instead of 7.
- ✅ `_last_scan_time` stamped in premarket + after-hours branches
  (was only RTH). Morning-readiness shows real scanner age now.
- ✅ Fixed v19.18 typo — `_last_scan_at` → `_last_scan_time`.
- ✅ 5 new source-level pins in `test_premarket_cadence_v19_19.py`.

### 🎯 Just shipped 2026-04-30 v19.18 — see CHANGELOG (thirty-seventh commit)
Morning Readiness aggregator (pre-RTH go/no-go check):
- ✅ New `GET /api/system/morning-readiness` endpoint — 5 checks
  (backfill_data_fresh / ib_pipeline_alive / trading_bot_configured
  / scanner_running / open_positions_clean) → single verdict.
- ✅ New `scripts/morning_check.sh` — colour-coded CLI breakdown
  with exit codes (0 green / 1 yellow / 2 red) for cron + chained
  shell automation.
- ✅ Closes the autopilot loop: morning-readiness on day N+1
  verifies that v19.14 EOD on day N flattened the book.
- ✅ 16 new pytest. **140/140 across all v19 backend suites.**

### Operator's automation pipeline (now end-to-end clean)

| Stage | Subsystem | Time |
|---|---|---|
| 1. Pre-RTH go/no-go | v19.18 morning-readiness | 8:30 AM ET |
| 2. Data freshness | v19.17 freshness gate + Collect Data button | as needed |
| 3. Scanner running | v19.15/v19.16 EVAL hot path | RTH |
| 4. Trade management | v19.13 manage stage | RTH |
| 5. EOD flat | v19.14 close stage + v19.14b banner | 3:55 PM ET |

### 🎯 Just shipped 2026-04-30 v19.17 — see CHANGELOG (thirty-sixth commit)
Bar-size-aware smart_backfill freshness gate:
- ✅ New `_expected_latest_session_date(bar_size, now_dt)` helper —
  daily bars require today's session post-4pm ET; intraday require
  today during RTH; weekly require most recent Friday.
- ✅ Replaced `days_behind <= freshness_days` gate with `last_session
  >= expected_session`. Daily bars no longer get silently skipped
  when they're 1-2 days behind.
- ✅ Diagnosed via operator's NVDA chart screenshot showing Apr 27
  as latest bar despite two backfill runs.
- ✅ 23 new pytest including direct pin of the Apr 28 NVDA scenario.

### 🟡 P1 — Next session priorities

- **Nightly auto-backfill schedule** (parked here from v19.17):
  Add a systemd timer (or APScheduler job in `server.py`) on Spark
  that runs `smart_backfill` at 17:30 ET nightly. With the v19.17
  freshness gate now correct, the only remaining gap is the
  manual-trigger requirement. ~15 min of work; mostly a Spark-side
  systemd unit. Sample unit:
  ```ini
  # /etc/systemd/system/smart-backfill.service
  [Unit]
  Description=SentCom nightly smart_backfill
  [Service]
  Type=oneshot
  ExecStart=/usr/bin/curl -fsS -X POST http://localhost:8001/api/ib-collector/smart-backfill
  ```
  Plus a `.timer` unit firing at `OnCalendar=Mon..Fri 17:30 America/New_York`.

- **Detector confidence tier badge on V5 Scanner cards** (parked
  2026-04-30 v19.16). With the EVAL hot path now lean post-v19.15/16,
  the next quality lever is making per-detector evidence visibility
  on the alert UI. Badge spec:
    - 🟢 **Proven** — detector has ≥30 graded R-outcomes
      (`strategy_stats.r_outcomes` length ≥ 30)
    - 🟡 **Maturing** — 5-29 graded R-outcomes
    - ⚪ **Cold-start** — <5 graded R-outcomes
  Plus a tooltip on hover showing `N trades · win-rate% · avg-R · last-fired`.
  Implementation: small badge component on `<ScannerCardV5/>`,
  reads from existing `strategy_stats` field already plumbed onto
  the alert. No new endpoint needed. ~30 min of work.

- **Divergence drill-in panel (Shadow vs Real)**: every shadow-vs-real
  disagreement becomes a labelled training sample. ~2-3h.
- **Setup-landscape self-grading EOD tracker**: record briefing
  predictions, grade EOD against `alert_outcomes`, surface as
  receipts in next morning's briefing.
- **Tier-tag backfill for symbol_adv_cache**: GICS-aligned tags
  on symbols beyond the static map (Finnhub fallback already
  shipped, just needs a one-shot CLI to flush the universe).

### 🎯 Just shipped 2026-04-30 v19.16 — see CHANGELOG (thirty-fifth commit)
Tier-aware detector dispatch:
- ✅ New `_intraday_only_setups` SUPERSET of `_intraday_setups` —
  pin-listed 28 detectors that have explicit sub-5min timing or
  playbook "intraday only" specs.
- ✅ Dispatch loop early-skip BEFORE `_check_setup` when the
  symbol's tier is non-intraday and the detector is in the
  intraday-only set.
- ✅ Conservative inclusion — ambiguous detectors (`squeeze`,
  `breakout`, `chart_pattern`, `mean_reversion`, etc.) explicitly
  pinned as MUST-be-OFF the list to defend against silent
  suppression of swing/position alerts.
- ✅ ~40% reduction in detector dispatch volume on 2,000-symbol
  universe + cleaner AI training data (no more stale-snapshot
  9-EMA scalp signals on swing-tier symbols).
- ✅ 7 new pytest. Fixed pre-existing stale canary test.

### 🎯 Just shipped 2026-04-30 v19.15 — see CHANGELOG (thirty-fourth commit)
Per-cycle context cache:
- ✅ New `_refresh_cycle_context()` runs ONCE per scan cycle —
  prefetches multi-index regime + sector regime market-wide.
- ✅ `_apply_setup_context` reads from the cache; falls back to
  per-alert classifier when cache stale/missing.
- ✅ ~15s/session of EVAL latency reclaimed at 1,500 alerts/day.
  Compounds with v19's parallel gate.
- ✅ Defensive `getattr` so test scaffolding (`__new__`-bypass
  pattern in detector_stats / scanner_canary) keeps working.
- ✅ 10 new pytest. **101/101 across all v19 backend suites + 221/222
  across full scanner-adjacent suite (1 pre-existing unrelated failure).**

### 🎯 Just shipped 2026-04-30 v19.14b — see CHANGELOG (thirty-third commit)
V5 EOD Countdown Banner — 5-min lookahead + CLOSE ALL NOW button.

### 🎯 Just shipped 2026-04-30 v19.14 — see CHANGELOG (thirty-second commit)
EOD close-stage hardening — 6 fixes + 3:55 PM ET default + 15 tests.

### 🟡 P1 — Next session priorities

- **Detector confidence tier badge on V5 Scanner cards** (parked
  2026-04-30 v19.16). With the EVAL hot path now lean post-v19.15/16,
  the next quality lever is making per-detector evidence visibility
  on the alert UI. Badge spec:
    - 🟢 **Proven** — detector has ≥30 graded R-outcomes
      (`strategy_stats.r_outcomes` length ≥ 30)
    - 🟡 **Maturing** — 5-29 graded R-outcomes
    - ⚪ **Cold-start** — <5 graded R-outcomes
  Plus a tooltip on hover showing `N trades · win-rate% · avg-R · last-fired`.
  Gives the operator an at-a-glance signal of which alerts are
  riding on real evidence vs which are still gathering data —
  particularly relevant for the v16-introduced setups
  (`the_3_30_trade`, `bouncy_ball`, `premarket_high_break`) that
  have few graded outcomes yet.
  Implementation: small badge component on `<ScannerCardV5/>`,
  reads from existing `strategy_stats` field already plumbed onto
  the alert. No new endpoint needed. ~30 min of work.

- **Divergence drill-in panel (Shadow vs Real)**: every shadow-vs-real
  disagreement becomes a labelled training sample. ~2-3h.
- **Setup-landscape self-grading EOD tracker**: record briefing
  predictions, grade EOD against `alert_outcomes`, surface as
  receipts in next morning's briefing.
- **Tier-tag backfill for symbol_adv_cache**: GICS-aligned tags
  on symbols beyond the static map (Finnhub fallback already
  shipped, just needs a one-shot CLI to flush the universe).

### 🎯 Just shipped 2026-04-30 v19.14b — see CHANGELOG (thirty-third commit)
V5 EOD Countdown Banner:

- ✅ New `GET /api/trading-bot/eod-status` lookahead endpoint —
  countdown + intraday vs swing position counts + state-machine
  (idle/imminent/closing/complete/alarm).
- ✅ New `EodCountdownBannerV5.jsx` mounted above `DayRollupBannerV5`
  in the Unified Stream container. 5-min countdown, position list,
  CLOSE ALL NOW override button (2-tap confirm), auto-hides on
  completion, alarm state past 4:00 PM ET.
- ✅ Drive-by fix: `/api/trading-bot/eod-close-now` had the same
  bool/dict bug we just killed in `check_eod_close` (v19.14 P0 #1).
  Now treats `close_trade` return as bool. Operator's "CLOSE ALL NOW"
  button actually works.
- ✅ 8 new pytest covering all 5 banner states + shape pin. **23/23
  in test_eod_close_v19_14.py.**

### 🎯 Just shipped 2026-04-30 v19.14 — see CHANGELOG (thirty-second commit)
EOD close-stage hardening — full audit + 6 fixes:

- ✅ **Default close window 3:57 → 3:55 PM ET** per operator request
  (extra 2-min cushion before the 4:00 PM bell). Updated the live
  default + the bot_persistence restore default so the change
  survives restarts and fresh-DB starts.
- ✅ **P0 #1**: `close_trade` returns a bool, not a dict — was raising
  silent AttributeError on every close attempt. Now treated as bool.
- ✅ **P0 #2**: closes run in PARALLEL via `asyncio.gather` (was
  serial; risked spilling past 4:00 PM with 25 open positions).
- ✅ **P0 #3**: `_eod_close_executed_today` only flips True on full
  success; partial failure leaves the flag False so the manage-loop
  tick retries the failed close before the bell.
- ✅ **P0 #4**: After-close alarm — if positions are still locally
  open at/after 4:00 PM, log loud ERROR + broadcast
  `eod_after_close_alarm` event so the V5 HUD can render a banner.
- ✅ **P1 #5**: Half-trading-day detection — `EOD_HALF_DAY_TODAY=true`
  flips the window to 12:55 PM ET (5 min before 1:00 PM close).
- ✅ **P1 #6**: WS-broadcast `eod_close_started` + `eod_close_completed`
  events for V5 HUD visibility.
- ✅ **Intraday-only**: explicit pin via `close_at_eod=True` filter —
  swing/position trades are NEVER auto-closed.

**Tests**: 15 new pytest in `test_eod_close_v19_14.py`. **76/76 across
v19.2 + v19.3 + v19.4 + v19.5 + v19.8 + v19.12 + v19.13 + v19.14 backend
test suites.**

### 🎯 Just shipped 2026-04-30 v19.8 — see CHANGELOG (twenty-seventh commit)
All 4 stream-improvement waves shipped together:

- ✅ **Wave 1** — perception layer:
  - Repeat-event collapser (5× effective stream capacity on busy windows)
  - Cross-panel hover highlight (Scanner ⇄ Stream ⇄ Deep Feed)
  - Counter-trend striping on Scanner cards (surfaces v17 soft-gate decisions)
- ✅ **Wave 2** — Deep Feed → real forensic tool:
  - `GET /api/sentcom/stream/history` over `sentcom_thoughts` (TTL 7d)
  - Time-range chips (5m / 30m / 1h / 4h / 1d / 7d) + symbol drill-in + free-form search
  - Right pane stops being a duplicate of Unified Stream
- ✅ **Wave 3** — context layer:
  - Scanner groupable by Market Setup (operator-toggleable, persisted)
  - Day-rollup banner pinned to top of Unified Stream — names the
    funnel's first dead stage in 1 line so operator stops curling
    `/api/diagnostic/trade-funnel`
- ✅ **Wave 4** — RLHF labels:
  - `POST /api/sentcom/stream/label` (👍/👎/clear, idempotent toggle)
  - New `sentcom_labels` Mongo collection (TTL 90d)
  - Training-pipeline export endpoint joins labels with stored events
  - Closes the self-improving loop alongside realised P&L

**Tests**: 10 new pytest + 9 frontend collapser tests = **122/122 v12-v19.8 + 9/9 collapser**.
ESLint & ruff clean.

### 🎯 Just shipped 2026-04-30 v19.7 — V5 HUD layout 2/3 ⇄ 1/3 split (CHANGELOG: twenty-sixth commit)

### 🎯 Just shipped 2026-04-30 v19.6 — see CHANGELOG (twenty-fifth commit)
- ✅ **V5 HUD: Buying Power replaces Latency** in the top-bar metrics
  cluster. More actionable on a margin account — shows real-time
  margin headroom alongside equity. Color-coded (emerald when
  `BP > equity × 0.5`; amber when running close to maintenance).
- ✅ Backend already collected `BuyingPower` from IB account snapshot
  (line 235 of trading_bot.py); v19.6 surfaces it at top-level of
  `/api/trading-bot/status` so the V5 HUD can read it without an
  extra round-trip.
- ✅ Latency still visible on the Pusher Heartbeat tile (avg/p95/last);
  we just freed the prime HUD slot for buying power.

### 🎯 Just shipped 2026-04-30 v19.5 — see CHANGELOG (twenty-fourth commit)
- ✅ **Safety config Pydantic ceiling raised** for margin accounts —
  `max_total_exposure_pct` validator was `le=100`, rejecting the
  v19.4 unblock curl with HTTP 422 (`Input should be less than or
  equal to 100`, input=320). Bumped to `le=1000` (still rejects
  typos but allows realistic Reg-T margin operation).
- ✅ Cash operators unaffected; only impacts margin-account operators
  who legitimately need >100% of equity in aggregate exposure.
- ✅ 4 new validator tests. **112/112 across v12-v19.5 suites.**

### 🎯 Just shipped 2026-04-30 v19.4 — see CHANGELOG (twenty-third commit)
- ✅ **Position-sizer absolute-notional clamp** — new
  `RiskParameters.max_notional_per_trade` field (default $100,000),
  applied as a third `min()` clamp in `calculate_position_size`
  alongside the existing risk + capital clamps. Decouples per-trade
  size from equity so the sizer can never silently fatten as the
  paper account compounds.
- ✅ Operator's diagnostic curl finally named `safety_guardrail`
  with `symbol_exposure: $267k exceeds cap $15k` — the two-curl
  unblock raised the safety cap to $100k, but the structural fix
  is the sizer clamp itself.
- ✅ Persisted to Mongo; surfaced via `POST /api/trading-bot/risk-params`.
- ✅ 7 new regression tests (clamp wins / risk clamp still wins /
  zero disables / source-level guards / persistence + API round-trip).
- ✅ **108/108 across v12-v19.4 suites.**

### 🎯 Just shipped 2026-04-30 v19.3 — see CHANGELOG (twenty-second commit)
- ✅ **HOT-FIX**: live-tick scanner ALSO bombing pusher RPC.
  Operator's post-v19.2 restart logs reproduced the same cascade
  v19.1 was supposed to kill, plus 120s push-to-DGX timeouts +
  equity `$-` + frozen unified stream.
- ✅ Root cause: `_scan_symbol_all_setups` was the OTHER caller
  hitting `_get_live_intraday_bars` for every scanned symbol —
  ~480 calls/cycle blow IB's pacing limit within 2-3 cycles.
- ✅ One-line fix: pass `mongo_only=True` in the live-tick scanner's
  hot path. Live quote still flows through `_pushed_ib_data`; Mongo
  bars are <60s lagged so 5-min/15-min detectors are unaffected.
- ✅ 4 new regression guards (1 source-level pin on the call site,
  1 v19.1 bar-poll re-pin, 2 signature pins on `get_technical_snapshot`
  / `get_batch_snapshots`). **101/101 across v12-v19.3 suites.**

### 🎯 Just shipped 2026-04-30 v19.2 — see CHANGELOG (twenty-first commit)
- ✅ **DLQ purge endpoint** — `POST /api/diagnostic/dlq-purge` finally
  closes the third corner of the historical-data DLQ tooling (alongside
  `/retry-failed` and `/failed-items`). Safe-by-default: `permanent_only`
  allowlist of known-terminal IB errors (no security definition, contract
  not found, no_data, etc.); `permanent_only=False` requires explicit
  `force=true`; `dry_run=true` previews without deleting.
- ✅ Optional `older_than_hours` and `bar_size` filters; combines
  `$and` with the permanent regex when both active.
- ✅ Audit trail to new `dlq_purge_log` collection (30d TTL).
- ✅ 13 new regression tests; **97/97 across v12-v19.2 suites**.
- **Operator usage**: dry-run first, then drop. The V5 HUD's `N DLQ`
  badge clears as the queue thins.

### 🎯 Just shipped 2026-04-30 v19.1 — see CHANGELOG (twentieth commit)
- ✅ **Hot-fix**: bar poll bombarding pusher RPC. Operator's
  post-v19 logs showed `[RPC] latest-bars X failed` cascade + 120s
  push-to-DGX timeouts. Root cause: v17 expanded subscriptions,
  triggering live-bar overlay in the snapshot service for hundreds
  of symbols every bar-poll cycle.
- ✅ Added `mongo_only=True` flag on `realtime_technical_service`,
  threaded through `bar_poll_service`. Bar poll now reads ONLY from
  Mongo; live-tick scanner unaffected (still uses the live-bar
  overlay for the ~480 streamed symbols).
- ✅ Defence in depth: bar poll cadence/batch dialed down (30s→60s,
  50→25 symbols).
- ✅ Regression guard added — `mongo_only=True` is mandatory.

### 🎯 Just shipped 2026-04-30 v19 — see CHANGELOG (nineteenth commit)
- ✅ **Confidence Gate Parallelism (3-5× EVAL speedup)** — 8
  independent model awaits now fan out via `asyncio.gather()` with
  per-coroutine timeouts and exception isolation. Phase 1 regime
  calls also parallelised.
- ✅ **Source-level regression guard** — 8 parametrized tests assert
  no inline model awaits remain in `evaluate()`. A future contributor
  can't silently undo the speedup.
- ✅ Test suite total: **90/90** across v12-v19.
- **Real-world impact**: at 1,500 alerts/session, gate latency drops
  from ~33 min to ~6 min. Eliminates ~5-10× of the gate-induced
  slippage on fast-tape stocks (where prior 2s per-alert delay caused
  bracket fills past intended entry).

### 🟡 P1 — Next session priorities
- **Per-cycle context cache** — regime/sector/multi-index regime
  recomputed per-alert today; cache once per scan cycle for ~30%
  free additional EVAL speedup. Most of the wiring already done in
  v19 (the gather pattern is established).
- **Tier-aware detector dispatch** — skip impossible detector/tier
  combinations. Quality > speed. Needs operator's tier-mapping
  judgment for ambiguous detectors.

### 🎯 Just shipped 2026-04-30 v18 — see CHANGELOG (eighteenth commit)
- ✅ **Bar Poll Service** — pure DGX-side service that runs bar-based
  detectors on the universe-minus-pusher pool by reading
  ``ib_historical_data`` Mongo (no IB calls, no rate limits). Three
  pools: intraday-noncore (30s), swing (60s), investment (2h).
- ✅ **`LiveAlert.data_source`** field — alerts stamped `live_tick`
  vs `bar_poll_5m` so AI gate / shadow tracker / V5 UI can
  distinguish.
- ✅ **Server-side IB bracket exits** — discovered already shipped
  in Phase 3 (2026-04-22). Added 4 regression guards so a future
  contributor can't silently revert to legacy two-step entry+stop.
- ✅ **`/api/diagnostic/bar-poll-status`** + manual trigger endpoint.
- 11 new tests (76/76 across all instrumentation suites).
- **Universe coverage now ~80%** of the 2,532 qualified universe,
  up from 2.8% pre-v17.

### 🟡 P1 — Next session priorities
- **Confidence gate parallelism** (the 3-5× EVAL speedup) —
  `asyncio.gather()` the independent model consultations.
- **Per-cycle context cache** — regime/sector/multi-index regime are
  recomputed per-alert today; cache once per scan cycle for ~30%
  free EVAL speedup.
- **Tier-aware detector dispatch** — skip impossible
  detector/symbol-tier combinations (e.g. don't run `9_ema_scalp` on
  swing-tier names).

### 🎯 Just shipped 2026-04-30 v17 — see CHANGELOG (seventeenth commit)
- ✅ **Pusher Rotation Service** — DGX-side service that manages
  the new 500-line IB Quote Booster budget. Goes live ~60s after
  bot startup. Pre-v17: 72 hardcoded symbols. Post-v17: ~480
  symbols dynamically rotated by time-of-day profile.
- ✅ **Hard safety guard**: open positions + pending orders
  AUTO-PINNED, can NEVER be unsubscribed by rotation. 30/30 tests
  pass including 4 dedicated safety canaries.
- ✅ **`/api/diagnostic/pusher-rotation-status`** with optional
  dry-run preview, plus `POST /api/diagnostic/pusher-rotation-
  rotate-now` operator escape hatch.
- ✅ Live-tick coverage jumps from **0.76% → ~19%** of qualified
  universe. Phase 2 (bar-poll service) will close to ~76%+.

### 🟠 P1 — Phase 2 (next session): Bar Poll Service
- Build `services/bar_poll_service.py` — IB historical-bar polling
  for the 1,495 swing/investment + ~590 non-subscribed intraday
  symbols. Bar-based detectors (`squeeze`, `mean_reversion`,
  `chart_pattern`, `breakout`, etc.) run on this expanded pool.
- Build multi-client IB session manager — needed to clear the
  60 reqs/10min historical-data rate limit (6 clients = 360/10min).
- Stamp `data_source: bar_poll_5m` on alerts; AI gate can downweight
  if needed.
- Result: total scanner reach jumps from ~480 (v17) to ~2,000+ of
  2,532 qualified symbols.

### 🎯 Just shipped 2026-04-30 v16 — see CHANGELOG (sixteenth commit)
- ✅ **`relative_strength` detector OFF** — operator-flagged: no
  concrete entry trigger, was dominating breadth. Detector method
  preserved for future re-wiring as ML feature on other alerts.
- ✅ **Alert caps lifted 50 → 500 end-to-end** — scanner internal,
  REST endpoint ceiling, frontend REST + WS slice. Operator can now
  see every detected setup/idea to tweak/grow the scanner faster.
- ✅ 4 new regression guards (35/35 across instrumentation + hydration
  + v16 suites).

### 🎯 Just shipped 2026-04-30 v15 — see CHANGELOG (fifteenth commit)
- ✅ **SentCom Intelligence 50-eval cap** removed — confidence_gate
  hydration now counts today via Mongo `$group` aggregation (not the
  50-doc deque), so "today_evaluated" reflects the real daily total.
- ✅ **Alerts panel 5-cap** lifted — `useSentComAlerts.js` 5 → 20 on
  both REST limit and WS slice.
- ✅ **SCAN=0 vs EVAL=5 mismatch** fixed — `derivePipelineCounts` now
  falls back to `alerts.length` when `setups` (predictive_scanner) is
  empty.
- ✅ **`/api/diagnostic/account-snapshot`** — walks the equity
  resolution chain and returns operator-friendly verdict
  (`pusher_disconnected` / `pushed_account_empty` / `net_liq_zero` /
  `ok`).
- ✅ **`/api/diagnostic/scanner-coverage?hours=N`** — surfaces RS-share,
  pusher_sub_count vs. universe_size, and starved detectors so the
  operator can prove the IB-subscription bottleneck without log diving.
- 31/31 tests passing (2 new hydration regression guards).

### 🎯 Just shipped 2026-04-30 v14 — see CHANGELOG (fourteenth commit)
- ✅ **`exc_info=True` / `logger.exception` sweep across the trade
  chain** (15 sites in 4 files). Every critical except now surfaces
  the exception type AND traceback line number in the log, so future
  typo-class regressions like the v13 `BotTrade.quantity` bug surface
  within the first failed trade attempt instead of needing a 13-day
  forensic investigation.
- ✅ 6 new regression canaries (29/29 total in
  `test_trade_drop_instrumentation.py`).

### 🎯 Just shipped 2026-04-30 v13 — see CHANGELOG (thirteenth commit)
- ✅ **13-DAY SILENT REGRESSION FIXED**. The v12 instrumentation
  caught the bug within minutes of going live: `BotTrade` exposes
  `shares` not `quantity`, but `_execute_trade` had two
  `trade.quantity` typos. Every autonomous trade for 13 days hit
  `AttributeError`, silently fail-CLOSED through the
  `safety_guardrail_crash` path, and never reached the broker.
- ✅ Two-line fix in `trading_bot_service.py` lines 2259 + 2264.
- ✅ Two new source-level regression guards in
  `tests/test_trade_drop_instrumentation.py` (23/23 passing).
- ✅ Operator's first curl after pull — confirm `bot_trades` count
  starts climbing again during RTH.

### 🎯 Just shipped 2026-04-30 v12 — see CHANGELOG (twelfth commit)
- ✅ **Trade-drop forensic instrumentation** — new
  `services/trade_drop_recorder.py` + 9 instrumented gates between
  the AI confidence gate and `bot_trades.insert_one()`. Every silent
  exit now writes to `trade_drops` Mongo collection (TTL 7d) AND emits
  a `[TRADE_DROP] gate=… symbol=… reason=…` WARN log.
- ✅ **Broker-reject + exception paths now persist** —
  `trade_execution.execute_trade` was orphaning REJECTED trades in
  memory (no `bot._save_trade(trade)` call). **THIS IS THE LIKELIEST
  ROOT CAUSE** of the April 16 → April 29 silent regression. Fixed.
- ✅ **New endpoint `/api/diagnostic/trade-drops?minutes=N&gate=X`** —
  aggregates drops by gate, names `first_killing_gate`, lists last 25
  with full context. Companion to `/trade-funnel`.
- 21 new tests (44/44 across instrumentation + adjacent suites).

### 🟠 P0 — User-verification pending after Spark pull + restart
**MUST RUN AFTER OPERATOR PULLS AND RESTARTS:**
1. After 5-10 min of RTH scanning:
   `curl -s http://localhost:8001/api/diagnostic/trade-drops?minutes=60 | jq .`
2. Read `first_killing_gate` — that names the suspect.
3. If `account_guard` (highest-confidence suspect for the April 16
   regression): inspect `IB_ACCOUNT_PAPER` in backend/.env and
   ensure it includes the pusher's reported `DUM61566S` alias.
4. If `broker_rejected`: read the `recent[]` array's `reason` field
   for the IB-side error (margin, no-buying-power, etc).
5. Verify REJECTED trades now appear in `bot_trades` (the
   instrumentation also fixed the orphan-in-memory bug).

### 🎯 Just shipped 2026-04-30 v11 — see CHANGELOG
- ✅ **Realtime stop-guard re-check** — 60s per-trade throttle, ratchet-only,
  re-snaps to fresher HVN levels in breakeven + trailing modes.
- ✅ **Sector fallback chain** — `tag_symbol_async` adds Mongo cache +
  Finnhub `stock/profile2` industry mapping with `_PRIORITY_OVERRIDES`
  (Biotech > Tech, REIT > Industrial) + `_EXPLICIT_NONE` blocklist.
  Persists Finnhub hits back to `symbol_adv_cache.sector`.
- ✅ **Daily-Setup landscape pre-warm** — runs in `_scan_loop` CLOSED +
  PREMARKET branches; Saturday 12:00 ET cron job for weekend-context
  rollup. First morning briefing now O(1) instead of paying 200×classify
  latency.
- ✅ **V5 Shadow vs Real tile** — side-by-side win-rate comparison
  with divergence signal (shadow ahead / behind / in sync). Wired
  into the V5 status strip.
- 40 new tests (12 + 20 + 8). 224/224 across related suites.

### 🟠 P1 — Divergence drill-in (operator-saved 2026-04-30 v11)

The shadow-decision badges shipped this commit (●/○ on V5 stream
rows) make divergence VISIBLE but not yet DIAGNOSTIC. Goal: make
every shadow-vs-real disagreement a labeled training sample.

**Behaviour spec**:
  - Click a `○` (bot diverged) badge → side panel opens
  - Panel shows the full shadow decision context:
      • What modules contributed (debate/risk/institutional/timeseries)
      • The reasoning string from `ShadowDecision.reasoning`
      • Why the bot diverged (look up the matching `live_alert` and
        show which gate killed it: `tape_confirmation=false` /
        `auto_execute_eligible=false` / `priority<HIGH` / etc)
      • Outcome: `would_have_pnl` and `would_have_r` (already tracked)
      • A "label" button (good_skip / bad_skip / unsure) that writes
        to a new `divergence_labels` collection
  - Click a `●` (bot agreed) badge → simpler panel showing both
    decisions converged + actual trade outcome if closed

**Implementation surface**:
  - New endpoint `GET /api/ai-modules/shadow/decisions/{id}/divergence`
    — joins shadow decision + matching `live_alert` + `bot_trade` row.
  - New endpoint `POST /api/ai-modules/shadow/decisions/{id}/label`
    — operator-supplied label for training data.
  - New component `frontend/src/components/sentcom/v5/DivergenceDrillInPanel.jsx`.
  - Wire badge `onClick` in `ShadowDecisionBadge.jsx`.

**Why this matters**: closes the learning loop on the bot's gate
calibration. Every time the operator marks a divergence as "bad_skip"
the gate weights get a labeled signal — without that, divergence
data sits unused. ~2-3h since `would_have_pnl` is already tracked on
`ShadowDecision` and the join keys (symbol + trigger_time) align
with `live_alerts`.

### 🟠 P2 — Predictive scanner deprecation (parked from this commit)
The legacy `predictive_scanner` (forming-setup phases — early_formation /
developing / nearly_ready / trigger_imminent) is still wired to:
  - `POST /api/scanner/scan` (used by `ScannerPage.js`)
  - `services/ai_assistant_service.py:1852` (AI assistant context query)
  - 7 GET endpoints (`/setups`, `/alerts`, `/status`, `/summary`,
    `/ai-context`, `/setup-types`, `/alerts/history`) — none of which
    are referenced in V5.

Plan to retire (~2-3h):
  1. Migrate `ScannerPage.js` to `enhanced_scanner` output (likely
     `/api/live-scanner/*` + a small server-side adapter for the
     "scan these symbols now" trigger).
  2. Re-point `ai_assistant_service.get_predictive_scanner()` calls
     to `get_enhanced_scanner()` — both expose the same shape for the
     specific data the assistant reads.
  3. Drop the 7 unused GET endpoints from `routers/scanner.py`.
  4. Delete `services/predictive_scanner.py` + its 1.1k LOC.

Rationale: `enhanced_scanner` is the live source of truth for V5 +
diagnostics + matrix-driven gating. Keeping `predictive_scanner`
around adds confusion (two scanner singletons, one feeds telemetry,
the other doesn't) and dead code surface. Confirmed no V5 frontend
component references `predictive_scanner` data — safe to migrate.

### 🎯 NEXT-SESSION PLAN — Regime → Setup → Trade pipeline (6-item rollout — STATUS UPDATE)

This is the agreed plan after the operator's architectural question
about the pipeline `Market Regime (SPY/QQQ/IWM/DIA) → Sector Regime →
Setup → Time / In-play → Trade`. The decision was: **the hierarchy is
the right human mental model but the wrong runtime architecture for
hard gates** (compounding rejection rate would starve the ML pipeline).
Instead, hard-gate only in 3 places (Time, In-Play, Confidence) and
encode every other layer as a feature into the per-Trade ML models.

| # | Item | Effort | Impact | Status |
|---|---|---|---|---|
| 1 | **`MultiIndexRegimeClassifier`** — read SPY+QQQ+IWM+DIA, return richer regime tags (incl. divergence/breadth). Stamp on alert metadata. | ~3h | **High** | ✅ **SHIPPED 2026-04-30** |
| 2 | **Plumb `market_setup` + new `multi_index_regime` into per-Trade ML feature vector** so the models actually train on them | ~2h | **High** | ✅ **SHIPPED 2026-04-30** |
| 3 | **Backfill sector tags** onto `symbol_adv_cache` (one-time job, GICS via IB or static map) | ~2h | Medium | ✅ **SHIPPED 2026-04-30** |
| 4 | **`SectorRegimeClassifier`** — read sector ETFs (XLK/XLE/XLF/XLV/XLY/XLP/XLI/XLB/XLRE/XLU/XLC), tag each ticker's sector regime | ~3h | **High** (after #3) | ✅ **SHIPPED 2026-04-30** |
| 5 | **Setup-landscape self-grading tracker** — `landscape_predictions` Mongo collection, EOD compare to realized R per Setup family, briefings get receipts | ~3h | Medium-high | ✅ **SHIPPED 2026-04-30** |
| 6 | **Drop the "regime as hard gate" idea** that earlier-fork ROADMAP suggested (`STRATEGY_REGIME_PREFERENCES` enforcement). Replace with feature-based learning per items #1-2. Document the decision. | ~30min | (cleanup) | ✅ **SHIPPED 2026-04-30** |

**Recommended commit ordering**: ~~#1 → #2 ship together~~ ✅ done.
~~Next: #5 as quick parallel win~~ ✅ done. ~~Next: #3 → #4 ship together~~
✅ done. **All 6 items SHIPPED 2026-04-30.** The agreed Regime → Sector
→ Setup → Time → Trade pipeline is fully implemented with soft-gate
ML feature plumbing. Next session: pick up from the P1 backlog.

**Hard gates after this work:**
1. **Time-window** (`_is_setup_valid_now`) — opening_drive can't fire midday
2. **In-Play / Universe** (ADV ≥$2M/day floor + RVOL ≥0.8 floor + tier-based scan frequency, optional STRICT in-play gate) — see `services/in_play_service.py`
3. **Confidence gate** (already exists — predicted_R + win_prob threshold)

Everything else (regime, sector, setup, intraday tape) → features.

### 🧪 What to verify after the next retrain on Spark
After items #1 + #2 shipped (2026-04-30), the next full retrain on the
DGX should produce setup-specific models whose feature vector grew
from N → N+15 (7 setup-label one-hots + 8 regime-label one-hots). Run
the verification suite on Spark:
```
PYTHONPATH=backend python -m pytest tests/test_multi_index_regime_classifier.py -v
```
Live-side spot checks:
- `db.timeseries_models.findOne({setup_type:"9_ema_scalp"}).meta.label_features`
  → should list the 15 new feature names.
- LiveAlert payloads include both `market_setup` and
  `multi_index_regime` (curl `/api/scanner/live-alerts`).
- Morning briefing narrative leads with a 1st-person regime line
  like "Heading into the open, I'm reading the tape as risk-on broad…"
  via `GET /api/scanner/setup-landscape?context=morning` →
  `narrative` field.

### 🟢 Just shipped 2026-04-30 — see CHANGELOG
- ✅ **Item #1**: `MultiIndexRegimeClassifier` (SPY/QQQ/IWM/DIA → 8
  regime labels) + 5-min market-wide cache. Stamps
  `LiveAlert.multi_index_regime`.
- ✅ **Item #2**: `composite_label_features` module + plumbing into
  `_train_single_setup_profile` AND `predict_for_setup`. 15 new
  one-hot features (`setup_label_*`, `regime_label_*`).
- ✅ **Item #6**: `STRATEGY_REGIME_PREFERENCES` re-documented as
  metadata-only (not an active hard gate). Architecture notes locked
  into PRD.md "Pipeline architecture" section.
- ✅ **Item #5** (second commit, same day): Setup-landscape
  self-grading tracker. New `landscape_predictions` collection +
  `LandscapeGradingService` (record / grade / get_recent_grades),
  EOD cron job at 16:50 ET, two new endpoints
  (`/api/scanner/landscape-receipts`, `/api/scanner/landscape-grade`),
  morning narrative now cites yesterday's grade via "Quick receipt"
  / "Owning yesterday's miss" 1st-person line.
- 51 new tests; 116/116 across the related suites still green.

### 🟢 Just shipped 2026-04-29 evening (3 commits) — see CHANGELOG
- ✅ **v1**: 9 new detector functions (6 orphans + 3 playbook setups)
- ✅ **v2**: Bellafiore Setup × Trade matrix system (`MarketSetupClassifier`,
  21-trade × 7-setup matrix, soft-gate, `_check_the_3_30_trade`,
  `/api/scanner/setup-trade-matrix`)
- ✅ **v3**: Setup-landscape briefings + 1st-person voice enforcement
  (`SetupLandscapeService`, 4 narrative voices, `/api/scanner/setup-
  landscape` + EOD/weekend coaching endpoints, voice-rule regression
  tests). Q2 architectural gap (Regime → Setup → Trade) audited;
  decision: handle via features not hard gates (see plan above).
- 61/61 tests passing across the full Setup-related suite.

### 🟠 Still-open items from earlier in session (not part of next-session plan)
- 🟡 **P1** UI heat-grid rendering for the Setup × Trade matrix in the Scanner panel
- 🟡 **P1** Auto-generate `SETUPS_AND_TRADES.md` from classifier constants on commit (currently hand-edited — drift risk)
- 🟡 **P2** Threshold-tune `the_3_30_trade` after first session of live data
- 🟡 **P2** Threshold-proximity sampler tuning for `bella_fade`, `bouncy_ball`, `vwap_continuation` (instrumented; needs live data + tuning)
- 🟢 **Backlog** Define `breaking_news` + `time_of_day_fade` checkers (the 2 remaining orphans)

### 🟠 Operator-prioritized follow-ups (parked)
- **Detector backtest harness** (saved 2026-04-29 evening) — replay last
  30d of `ib_historical_data` against each detector, compute per-setup
  hit-rate + simulated R. Persist into `strategy_stats.r_outcomes`.
- **Tighten Tier 2/3 freshness via smarter collector dispatch**.
- **Mean-reversion timing metric** (Hurst + OU half-life cached on
  `symbol_adv_cache`).
- Realtime stop-guard re-check, EOD Rejection Summary, Chart Pulse.

### 🟢 Earlier this session (2026-04-29 afternoon-12 → afternoon-15) — see CHANGELOG
- Scanner-router instance fix + `setup-coverage` diagnostic.
- Threshold-proximity audit for 12 silent detectors.
- Bucket disambiguation (orphans vs time-filtered).
- Operator-driven strategy time-window reclassification (22 setups).
- Pusher push-loop hang fix (account_data $— → live equity).
- Pusher subscription gate (RPC noise elimination).
- Evaluator-veto specific reason codes + NameError fix.
- Risk caps unified at `max_positions=25` and `min_risk_reward=1.5`.

### 🟢 Just shipped earlier (2026-04-29 afternoon-3) — see CHANGELOG
- ✅ **Bellafiore Setup × Trade matrix system**: new `MarketSetup` enum
  (7 setups), `MarketSetupClassifier` service with daily-bar-driven
  detectors, `TRADE_SETUP_MATRIX` (21 Trades × 7 Setups), 4 new
  `LiveAlert` fields, soft-gate logic in `_apply_setup_context`, new
  `_check_the_3_30_trade` checker, new `/api/scanner/setup-trade-matrix`
  endpoint, canonical `SETUPS_AND_TRADES.md` doc. 48/48 tests passing.
  Trade aliases dedupe: `puppy_dog`→`big_dog`, `tidal_wave`→`bouncy_ball`,
  `vwap_bounce`→`first_vwap_pullback`.

### 🟢 Just shipped earlier this session (2026-04-29 evening, v1) — see CHANGELOG
- ✅ **9 new detector functions**: 6 orphans (`first_move_up`,
  `first_move_down`, `back_through_open`, `up_through_open`,
  `gap_pick_roll`, `bella_fade`) + 3 playbook setups
  (`vwap_continuation`, `premarket_high_break`, `bouncy_ball`).
  Orphan count dropped 8→2 (only `breaking_news` and
  `time_of_day_fade` remain, operator deferred). 17 regression tests
  passing; 37/37 across related suites.

### 🟠 P1 — Outstanding orphans (operator deferred)
- `breaking_news` — operator wants to define rules separately later.
- `time_of_day_fade` — operator explicitly skipping for now.

### 🟠 Operator-prioritized follow-ups (next session candidates)
- **🟢 Detector backtest harness (saved 2026-04-29 evening)** —
  replay last 30d of `ib_historical_data` against each detector
  (especially the 9 new ones) to compute per-setup hit-rate +
  simulated R-multiples. Persist into `strategy_stats` so the SMB
  A/B/C grade + `expected_value_r` fields populate within hours
  instead of waiting weeks for live alerts to accumulate. Sketch:
  `services/scanner_backtest_harness.py` walks each symbol's bars
  forward in 5-min steps, builds a `TechnicalSnapshot` per step,
  calls each `_check_*` detector, then simulates entry/stop/target
  through subsequent bars to measure realized R. Endpoint
  `POST /api/scanner/backtest-detectors?days=30&setups=...` triggers
  the run; results land in `strategy_stats.r_outcomes` so the
  existing EV machinery picks them up automatically.
- **Tighten Tier 2/3 freshness via smarter collector dispatch**: have
  the 4 turbo collectors lazily refresh the most recently scanned
  symbols on cache miss, instead of relying on the nightly batch job.
- **Mean-reversion timing metric (Q2)** (~2-3 hours)
  No half-life / Hurst exponent calculation anywhere today. The bot
  detects "mean_reversion" as a setup type but can't answer "this
  symbol typically reverts in X bars". Plan: new
  `services/mean_reversion_metrics_service.py` computes per-symbol
  Hurst exponent + Ornstein-Uhlenbeck half-life nightly from daily
  bars and caches `mean_reversion_stats` on `symbol_adv_cache`.
  Evaluator can then prefer/avoid mean-revert setups based on the
  symbol's intrinsic reversion speed. ~2-3 hours, real differentiator
  vs typical setup scanners.
- **Realtime stop-guard re-check** in `stop_manager.py` (liquidity-aware trail).
- **EOD Rejection Summary** narrative line.
- **Chart Pulse** (live cache freshness tick).

### 🟢 Earlier this session (2026-04-29 afternoon-12 → afternoon-15) — see CHANGELOG
- Scanner-router instance fix + `setup-coverage` diagnostic.
- Threshold-proximity audit for 12 silent detectors.
- Bucket disambiguation (orphans vs time-filtered).
- Operator-driven strategy time-window reclassification (22 setups).
- Pusher push-loop hang fix (account_data $— → live equity).
- Pusher subscription gate (RPC noise elimination).
- Evaluator-veto specific reason codes + NameError fix.
- Risk caps unified at `max_positions=25` and `min_risk_reward=1.5`.

### 🟢 Just shipped earlier (2026-04-29 afternoon-3) — see CHANGELOG
- ✅ **Round 1 backend fixes** — `/api/trading-bot/status` now reads IB
  pushed account (was `$—`), `/api/scanner/strategy-mix` falls back to
  in-memory alerts when Mongo empty (was `total: 0`), SPY change_pct now
  uses daily-close anchor when only 1 intraday bar exists.
- ✅ **`emit_stream_event` shipped** — module-level helper in
  `services/sentcom_service.py`. Was imported but never defined → trade
  fills + safety blocks + order dead-letters silently dropped from V5
  Unified Stream for weeks. Wired into trade fills.
- ✅ **Per-detector firing telemetry** — `_check_setup` counts
  evaluations + hits per setup_type; `/api/scanner/detector-stats`
  endpoint exposes per-cycle + cumulative views so operator can finally
  diagnose "why is the scanner only emitting RS hits?".

### 🟢 Just shipped this session (2026-04-29) — see CHANGELOG
- ✅ **Shadow tracker drain mode** — `?drain=true` clears 6,715-deep
  backlog in one curl; yields to event loop between batches; stats
  cache busted on drain.
- ✅ **Mongo historical price fallback** for shadow tracker — drain
  now actually updates outcomes for symbols not in the IB pusher
  subscription. Operator's 6,715 backlog cleared 100%.
- ✅ **Per-module accuracy fix** — PnL-based correctness +
  recommendation keyword matching. Modules now show real 70-73%
  accuracy instead of perpetual 0%.
- ✅ **Liquidity-aware realtime stop trail (Q1)** — new
  `compute_trailing_stop_snap` + `StopManager.set_db()` so Target 1
  / Target 2 / trail ticks all anchor to HVN clusters when available
  (clean fallback to legacy ATR/% trail otherwise). 11 regression tests.
- ✅ **Mongo compound indexes** — `bar_size_1_date_-1` and
  `symbol_1_bar_size_1_date_-1` shipped on DGX. `rebuild-adv-from-ib`
  dropped from 5+ min → 44s.
- ✅ **Unqualifiable strike-counter rescue** — historical collector
  now POSTs to `/api/ib/historical-data/skip-symbol` on Error 200,
  and threshold lowered 3 → 1. Should drop overnight backfill time
  ~3-5×. 9 regression tests.
- ✅ **timeseries_ai shadow-tracking gap** — sentinel payload built
  for unusable / debate-consumed forecasts so the module finally
  gets credit in shadow stats. 5 regression tests.
- ✅ **AI Decision Audit Card (V5 dashboard)** — new
  `/api/trading-bot/ai-decision-audit` endpoint + AIDecisionAuditCard
  rendering per-trade module verdicts + outcome alignment. 15
  regression tests.
- ✅ **Risk-caps unification (Option B — read-only)** — new
  `/api/safety/effective-risk-caps` surfaces the actual binding
  cap across 6 conflicting sources + human-readable conflict
  diagnostics. 12 regression tests.

### 🟠 Backlog (next session candidates)
- **Risk-caps unification — Option A (full refactor, ~2-3 hours)**:
  Make `RiskParameters` (Mongo `bot_state.risk_params`) the single
  source of truth. `SafetyGuardrailConfig.from_env()` becomes
  `from_bot_state(db)`. PositionSizer + DynamicRiskEngine + gameplan +
  debate all read the same config. One UI panel to edit → all
  subsystems update. Touches 6 files. Worth doing once the
  intermediate Option B has been live for a session and proven the
  effective-cap resolution logic is sound.

### 🔴 P0 OPTIMIZATION — DEFERRED (was 2026-04-29 morning's top item, now shipped above)
**Pre-flight contract validation in `ib_historical_collector.py`**
- **Symptom**: During the 2026-04-29 overnight backfill, 3 of 4
  collectors burned their entire 60-req/10-min IB pacing quota on
  bad symbols (PSTG, HOLX, CHAC, AL, GLDD, DAWN…). Each bad symbol
  consumes 9 IB requests (one per bar_size) before being pruned.
  ~1,000-1,500 bad symbols in the queue = ~9,000-13,500 wasted IB
  requests across the run, slowing total backfill ~3-5×.
- **Fix**:
  1. In `ib_historical_collector.py` (Windows PC), before queuing 9
     bar_sizes for a symbol, do **one** `reqContractDetails()` call.
     If it errors with "No security definition", **immediately**
     mark the symbol unqualifiable and skip all 9 bar_size tasks.
  2. Lower the strike threshold for "No security definition" from
     3 → 1 in `services/symbol_universe.py::mark_unqualifiable`. The
     error is deterministic, not transient — no point waiting for
     more failures.
- **Expected impact**: ~75% reduction in IB quota burn during backfills.
  Overnight runs that currently take 6-10 hours should drop to 2-4 hours.
- **Effort**: ~30 min code change, no risk to existing logic.
- **Test plan**: Pick 3 known-bad symbols (PSTG, HOLX, CHAC), trigger
  smart-backfill, verify each consumes only 1 IB request and
  immediately gets `unqualifiable: true`.

### 🟠 Operator-prioritized follow-ups (next session candidates)
- **Mean-reversion timing metric (Q2)** (~2-3 hours)
  No half-life / Hurst exponent calculation anywhere today. The bot
  detects "mean_reversion" as a setup type but can't answer "this
  symbol typically reverts in X bars". Plan: new
  `services/mean_reversion_metrics_service.py` computes per-symbol
  Hurst exponent + Ornstein-Uhlenbeck half-life nightly from daily
  bars and caches `mean_reversion_stats` on `symbol_adv_cache`.
  Evaluator can then prefer/avoid mean-revert setups based on the
  symbol's intrinsic reversion speed. ~2-3 hours, real differentiator
  vs typical setup scanners.

### 🟣 Saved improvements (operator pinned 2026-04-28)

- **Trade-chain log watcher / first-occurrence pager** (operator
  pinned 2026-04-30 v14). Now that every critical except in the
  trade chain emits a full traceback (`logger.exception(...)`) and
  every silent drop writes to `trade_drops`, wire a tiny watcher
  that pages on FIRST occurrence of `[TRADE_DROP] gate=…` /
  `safety_guardrail_crash` / new `AttributeError`/`TypeError`/
  `KeyError` in the trade chain. Two flavours:

  • **Light (~30min)**: cron-style `journalctl -k --since "5 min ago"
    | grep -E "[TRADE_DROP]|guardrail check crashed|execute_trade
    error"` piped to a `mail`/`curl webhook` if non-empty. Lives in
    a small `scripts/trade_chain_log_watcher.sh` on Spark, runs every
    5 min via cron. Stores last-seen line hash in `/tmp` to avoid
    spamming on the same recurring bug.

  • **Heavy (~3h)**: real Loki/Promtail/Vector setup with structured
    log labels (`gate`, `symbol`, `setup_type`) → Grafana alert rule
    that fires on `count_over_time({app="sentcom"} |~ "TRADE_DROP"
    [10m]) > 5`. Better long-term but adds infra.

  Recommended start: light flavor. Heavy version when we have ≥2 more
  silent regressions worth justifying the infra weight.

  **Why this matters**: the 13-day v13 regression cost real trading
  days. With the v12 instrumentation + v14 logging the next typo will
  surface in the first failed trade attempt, but only if someone is
  watching. A 30-min watcher closes that loop.

- **Live cache freshness pulse on chart x-axis** — turn the most
  recent x-axis tick green when its bar was written by
  `source="live_tick"` within the last 60s. Visual confirmation the
  symbol is "self-healing" on live ticks (no PARTIAL coverage anxiety).
  ~30 min of work; touches `ChartPanel.jsx` + a new tiny
  `/api/ib/tick-persister-symbol-freshness?symbol=X` endpoint.
- **EOD narrative rejection summary** — at 16:00 ET, compose a
  single end-of-day summary line from the rejection-narrative buffer:
  *"Today I passed on 47 alerts: 18 setup_disabled (most: bella_fade),
  12 dedup_cooldown, 9 regime_mismatch, 5 tqs_too_low,
  3 max_open_positions."* Tells operator at a glance whether filters
  are too tight or scanner's spamming. ~20 min of work; group by
  reason_code in a new `/api/trading-bot/eod-rejection-summary`
  endpoint, render as the Close Recap card subtitle.
- **Multiplier-threshold optimizer v2 — held-out validation slice**
  (sketched 2026-04-28e at `services/multiplier_threshold_optimizer_v2.py`,
  not yet wired). Splits the trade window 80/20 train/holdout and
  only persists threshold changes whose direction is confirmed on
  the held-out slice. Defends against the v1 optimizer chasing a
  lucky 30-day regime window. Activate by:
  (a) swapping `from .multiplier_threshold_optimizer import run_optimization`
      → `from .multiplier_threshold_optimizer_v2 import run_optimization_v2`
      in `eod_generation_service.py` and `routers/trading_bot.py`,
  (b) bumping `_MIN_COHORT_N_V2` (default 25) once cohort sizes stabilize,
  (c) running v1 + v2 in dry-run alongside each other for ~2 weeks
      to compare proposal stability before flipping.
- **Catalyst-aware carry-forward ranker**
  (sketched 2026-04-28e at `services/catalyst_aware_carry_forward.py`,
  not yet wired). Filters today's intraday alerts by overnight news /
  EPS catalyst presence before the carry-forward TQS gate, so a
  B-grade setup on a stock with a fresh 8-K filing or post-market
  earnings beats the same setup on a quiet stock. Components
  scored: 8-K (+35), earnings within 5d (+25), material news within
  24h (+20), analyst action within 48h (+10), overnight gap >2%
  (+25). Activate by calling `enrich_with_catalyst(alert, db)` in
  `enhanced_scanner._rank_carry_forward_setups_for_tomorrow` and
  sorting by `(catalyst_score, tqs_score)` so news-driven candidates
  surface first. Pairs naturally with the SEC EDGAR 8-K integration
  (also on the roadmap as P2).
- **Live health monitor — go-live trip wire**
  (sketched 2026-04-28e at `services/live_health_monitor.py`,
  not yet wired). Async daemon polling every 30s; trips
  `bot.kill_switch_latch()` on any of: pusher offline >60s, account-
  guard mismatch, RPC p99 >5s over a 2-min window, ≥5 consecutive
  order rejects, bot loop heartbeat >90s stale. 10/10 tests
  passing (`test_live_health_monitor.py`). Activate alongside the
  first LIVE flip by:
  (a) instantiating `LiveHealthMonitor(self).start()` in
      `TradingBotService.start_bot`,
  (b) adding a `/api/trading-bot/live-health` GET endpoint that
      returns `monitor.snapshot()` for the operator dashboard,
  (c) recording RPC latencies via `monitor.record_rpc_latency_ms`
      in `routers/ib.py` after each pusher RPC call.

### Operator user-noted issues at end of session
- **Paper account shows $100,000** instead of operator's expected balance
  → Not a code bug. Operator is logged into IB paper account `DUN615665`.
  Resolution: in TWS → Edit → Global Configuration → API →
  Reset Paper Trading Account → set custom starting balance. One-time
  TWS-side action, no code change needed.
- **Scanner still mostly RS hits** — partly explained by the small
  pusher subscription set (14 symbols). Live-tick-driven detectors
  (RVOL, EMA9 distance) are starved on symbols not in the pusher's
  subscription. Resolved long-term by item below ("Live tick → Mongo
  bar persistence") — see ROADMAP.

### P0 — Pusher cleanup ✅ SHIPPED 2026-04-28 (see CHANGELOG)
- ~~Lower L2 sub limit 5 → 3~~ ✅ Done.
- ~~Backend: skip `/rpc/latest-bars` for symbols not in pusher's
  subscription~~ ✅ Done — new `subscriptions()` cache + gate in
  `services/ib_pusher_rpc.py` + 7 regression tests.

### P1 — L2 dynamic routing for top-3 EVAL alerts ✅ SHIPPED 2026-04-28 (Path B)
- Pusher: `/rpc/subscribe-l2`, `/rpc/unsubscribe-l2`, `/rpc/l2-subscriptions`.
- Backend: `services/l2_router.py` (15s tick, top-3 EVAL diff routing).
- Path B chosen — startup index L2 disabled (set
  `IB_PUSHER_STARTUP_L2=true` to revert). One IB clientId, no second
  session needed.
- Disable globally with `ENABLE_L2_DYNAMIC_ROUTING=false`.
- Status endpoint: `GET /api/ib/l2-router-status`.
- See CHANGELOG 2026-04-28 entry #2 for full details.

### P1 — ⭐ Live tick → Mongo bar persistence ✅ SHIPPED 2026-04-28
- New `services/tick_to_bar_persister.py` builds 1m/5m/15m/1h bars
  from `/api/ib/push-data` quote stream and upserts to
  `ib_historical_data` with `source="live_tick"`.
- Status endpoint: `GET /api/ib/tick-persister-stats`.
- See CHANGELOG 2026-04-28 entry #1 for full details.

### P0 — Pusher RPC latency partially recovered
- After backend restart at ~3:06 PM ET, RPC latency dropped from 350s
  to 546ms (last sample). Avg/p95 still skewed high (11.4s / 17.9s,
  n=50) but normalising as good samples accumulate. Tentatively
  resolved by the restart.
- If it spikes again, investigate: IB pacing, DGX RPC handler
  profile (synchronous Mongo writes?), network Windows ↔ DGX.

### P0 — Wave-scanner background loop never started ✅ FIXED 2026-04-28
- `/api/wave-scanner/stats` now reports real `total_scans` /
  `last_full_scan` / `last_scan_duration`. Root cause was that
  `enhanced_scanner._scan_loop` produced wave batches but never called
  `wave_scanner.record_scan_complete()` to roll the counters forward.
  Fix wires the callback after every successful scan cycle.

### P1 — Briefings content gaps ✅ SHIPPED 2026-04-28 (frontend + backend)
- Backend: `_auto_populate_game_plan` now fetches MarketRegimeEngine
  state + recommendation; surfaces `regime` / `bias` / `thesis` at
  top-level of the gameplan doc.
- Frontend: Morning Prep / Mid-Day Recap / Power Hour cards all read
  the new shape with fallbacks (no more "No game plan filed" silence;
  empty-state recap + power hour show regime + scanner hits + watchlist).
- See CHANGELOG 2026-04-28 entry #3.

### P1 — Setup-found bot text (operator flagged 2026-04-27)
- Operator says "RS LEADER NVDA +6.8% vs SPY - Outperforming market —
  TQS 51 (C)" copy is wrong but didn't specify how. **Action:** ask
  operator what the copy *should* say, then fix the server-side
  bot-narrative template.

### P1 — `/api/scanner/daily-alerts` returns 0 ❌ NOT A BUG (closed 2026-04-28)
- Diagnosed: endpoint reads `_live_alerts.values()` in-memory and
  filters by `setup_type ∈ DAILY_SETUPS`. No Mongo `timestamp` filter
  exists. Returns 0 simply because no daily setups have fired this
  session. No code change required.

### P1 — Mongo aggregation index for `rebuild-adv-from-ib` ✅ SCRIPT SHIPPED 2026-04-28
- Operator-side script: `backend/scripts/create_ib_historical_indexes.py`.
  Idempotent. Creates `{bar_size: 1, date: -1}` and
  `{symbol: 1, bar_size: 1, date: -1}` if missing.
- Run on DGX:
  ```
  PYTHONPATH=backend /home/spark-1a60/venv/bin/python \\
      backend/scripts/create_ib_historical_indexes.py
  ```

### P1 — Live Data Phase 4: retire Alpaca fallback
- Set `ENABLE_ALPACA_FALLBACK=false`, run smoke for 1 trading day,
  then remove the Alpaca client + fixtures entirely.

### P1 — User-verification pending
- Visually confirm new ET 12-hour formatting on DGX after frontend
  hot-reload (chart x-axis, alerts row, S.O.C., briefings).
- Confirm chart x-axis now shows "Apr 27" labels at day boundaries
  instead of looping `9:30 AM → 1:00 PM → 4:00 AM`.
- Confirm Pusher RPC tile headline now reads `last 335ms` instead of
  the misleading `avg 1117ms`.

### P2 — SEC EDGAR 8-K integration
- Material-events feed for the Briefings panel.

### P3 — Quick wins
- ⌘K palette: `>flatten all`, `>purge stale gaps`, `>reload glossary`.
- "Dismissible forever" tooltip option on Help System.
- Retry the 222 historical `qualify_failed` items via
  `/api/ib-collector/retry-failed` (click the red `222 DLQ` badge).
- Auto-strategy-weighting (parked — see CHANGELOG `2026-02 — DEFERRED`).
- Refactor monolithic `server.py` → routers/, models/, tests/ (defer
  until pipeline is 100% stable).
- Build the Agent Brain memory system (Option C scope agreed
  2026-04-27 — see chat history; user pinned for later).
- ~~Add a "scanner-health canary" pytest~~ ✅ SHIPPED 2026-04-28 —
  `tests/test_scanner_canary.py` (10 tests). See CHANGELOG batch #2
  entry #2.

### P0 — Wave-scanner: ✅ SHIPPED — see CHANGELOG 2026-04-28.

### P1 — Briefings: ✅ shipped — see CHANGELOG 2026-04-28 entry #3.

### P1 — Setup-found bot text ✅ SHIPPED 2026-04-28
- Operator preference: wordy / conversational. Now renders 2-3
  sentences (saw + quality call + plan) instead of one terse line.
- See CHANGELOG 2026-04-28 batch #2 entry #1.

### P1 — Phase 4 Alpaca retirement ✅ LOCKED 2026-04-28
- `ENABLE_ALPACA_FALLBACK=false` is the default. Canary tests
  prevent silent rollback. See CHANGELOG 2026-04-28 batch #2 entry #3.

### P1 — `/api/scanner/daily-alerts`: ❌ closed (not a bug) — see CHANGELOG 2026-04-28.

### P1 — Mongo index: ✅ script shipped — see CHANGELOG 2026-04-28 entry #4.

### P1 — Live Data Phase 4: retire Alpaca fallback
- Set `ENABLE_ALPACA_FALLBACK=false`, run smoke for 1 trading day, then
  remove the Alpaca client + fixtures entirely.

### P1 — User-verification pending
- Visually confirm new ET 12-hour formatting on DGX after frontend
  hot-reload (chart x-axis, alerts row, S.O.C., briefings — see
  CHANGELOG `2026-04-27 — App-wide ET 12-Hour Time Format`).
- Confirm chart x-axis now shows "Apr 27" labels at day boundaries
  instead of looping `9:30 AM → 1:00 PM → 4:00 AM`.
- Confirm Pusher RPC tile headline now reads `last 335ms` instead of
  the misleading `avg 1117ms`.
- After scanner-regression fix is pulled to DGX, verify alert volume
  recovers to ~1,000/day with multiple setup types.

### P2 — SEC EDGAR 8-K integration
- Material-events feed for the Briefings panel.

### P3 — Quick wins
- ⌘K palette: `>flatten all`, `>purge stale gaps`, `>reload glossary`.
- "Dismissible forever" tooltip option on Help System.
- Retry the 222 historical `qualify_failed` items via `/api/ib-collector/retry-failed`
  (click the red `222 DLQ` badge in the V5 header → opens NIA panel).
- Auto-strategy-weighting (parked — see CHANGELOG `2026-02 — DEFERRED`).
- Refactor monolithic `server.py` → routers/, models/, tests/ (defer
  until pipeline is 100% stable).
- Build the Agent Brain memory system (Option A/C, scoped 2026-04-27 —
  see chat history "Brain memory pinned for later").

---

## Backlog — DataFreshnessBadge → Command Palette evolution (P2, post-Phase-3)

**Concrete spec** for when the live-data foundation is in place:

Turn the passive `DataFreshnessBadge` chip into an active control surface.
Clicking the badge opens a slide-down inspector panel (or `⌘K` modal on
desktop) showing:

  1. **Global pipes** — one row each:
     - Pusher push age + health (from `/api/ib/pusher-health`)
     - Historical-queue freshness (from `/api/ib-collector/universe-freshness-health`)
     - Live-bar cache stats (from Phase 1's `live_bar_cache` collection)
     - IB Gateway connection (derived from pusher health)

  2. **Per active-view symbol** (the ones user is currently looking at):
     - Symbol · last bar time · cache TTL remaining · "Refresh now" button
     - Example: `MRVL · closed 16:00 ET · 42m until refresh · [Refresh now]`
     - Uses Phase 2's subscription manager to know which symbols are "hot".

  3. **One-click actions**:
     - `Refresh all now` — bypass cache TTL, force pusher RPC fetch for all hot symbols
     - `Pause live subs` — emergency lever when IB pacing is tight
     - `Open pusher-health endpoint` — for deep debugging
     - `⌘K` fuzzy symbol search — this is also BL-01 (command palette), merges here

  4. **Discovery affordance**: a small pulsing chevron on the chip on first
     visit per browser session hints that the chip is clickable.

**Why this is the right move:**
- Current chip is read-only — tells you the state, not how to fix it.
- Inspector collapses multiple diagnostic endpoints into one pane.
- BL-01 (⌘K command palette) was listed as P3 separately but naturally
  shares the surface — wiring them together saves a code path AND gives
  users a consistent "everything starts from the badge" muscle memory.
- Directly addresses the 5-week-stale-data RCA: *"nothing in the UI
  shouted that data was frozen."* Now not only does it shout, it offers
  the fix button right there.

**Effort estimate:** ~3–4h once Phases 1–3 are in. Do not attempt before —
it depends on `live_bar_cache` and subscription state that don't exist yet.

**File plan:**
  - `frontend/src/components/DataFreshnessInspector.jsx` — slide-down panel
  - `frontend/src/hooks/useActiveViewSymbols.js` — tracks hot symbols
    across ChartPanel, EnhancedTickerModal, SentComV5View
  - Extend `DataFreshnessBadge.jsx` — `onClick` opens the inspector
  - Backend: `GET /api/live/freshness-snapshot` — aggregates the 3 pipes
    + hot-symbol cache TTL into one response




## 🗂️ Backlog — UX Power-User Layer (not started, user approved for later)

### [BL-01] Keyboard Shortcuts + Symbol Command Palette
- **`⌘K` / `Ctrl+K`** → opens centered fuzzy-match symbol picker. Tiers: (1) open positions, (2) today's setups/alerts, (3) watchlist, (4) recent stream symbols, (5) full 264K universe from `ib_historical_data` (lazy, cached in localStorage daily).
- **`/`** → focus the V5 chat input.
- **`Esc`** → close active modal/palette. **`?`** → shortcut cheatsheet overlay.
- New files: `CommandPaletteV5.jsx`, `useKeyboardShortcuts.js`. New backend (optional): `GET /api/ib-collector/symbol-universe` (distinct symbols).
- Reuses existing `handleOpenTicker` + 3-min modal cache. ~1 hour effort.

### [BL-02] Hover Tooltips Everywhere
- Add explanatory hover tooltips to virtually every data point and UI feature in V5 (and across the app): HUD metrics, scorecard values, gate scores, R multiples, DRC states, pipeline stage chips, chart header abbreviations (E/SL/PT/R:R), briefing timings, scanner metric abbreviations (RVol, Sharpe, P(win)), etc.
- Goal: user never has to guess what a number means. Teach the platform through discovery.
- Suggested approach: shadcn `Tooltip` component, centralized `/utils/fieldDefinitions.js` as single source of truth (label + short explanation + optional formula), reusable `<FieldTooltip field="gate_score">…</FieldTooltip>` wrapper.

### [BL-03] Training Integrity Card on V5 HUD
- Small card showing per-phase health of the last training run: `models_trained_this_run / expected_models` as a color-coded bar, red when 0% of a phase completed, yellow when partial, green when 100%.
- Would have caught 2026-04-23's silent-zero P3/P5/P7 phases in seconds instead of the hours of mongo detective work we did today.
- Source: `/api/ai-training/status.pipeline_status.phase_history[].models_trained` vs configured `expected_models`. Data already exists; just needs a card.
- Bonus: add a "Last Full Retrain" timestamp + 3 avg accuracy bands (`< 50%` red, `50-55%` yellow, `> 55%` green) so the user always knows at a glance whether the models are trustworthy.
- ~30 min effort.




## TODO (user note 2026-04-22)
- 🟡 Revisit `MorningBriefingModal.jsx` to look like the user's "newer more in-depth briefing modal" (screenshot they shared). Current V5-restyled modal is a minimal summary; they want richer detail. Revisit after Stage 2d polish.



## Backlog — P1 / P2 ideas captured but not yet scheduled

### Regime-Aware Strategy Phase Auto-Throttle (captured 2026-04-22)
**Idea:** In `trading_bot_service.py`, track rolling 30-day per-side Sharpe (LONG vs SHORT aggregated across all paper/live setups). When one side outperforms the other by >1.0 Sharpe, auto-tilt position sizing (e.g. 60/40 short-heavy when shorts dominate, back to 50/50 when parity returns). Also works as an early-warning: if BOTH sides' rolling Sharpe drop below 0.5 at the same time, auto-pause new entries and flag for review (likely regime shift the models haven't caught up to).

**Why it matters:** current state has 3 shorts paper-promoted and longs still recovering — hardcoded sizing doesn't reflect where the measurable edge actually lives. Auto-throttle lets the bot compound on its proven side without manual tuning every week, and gives us a principled way to exit a bad regime before it costs too much.

**Implementation sketch:**
- Query `bot_trades` for last 30d, compute per-side Sharpe + expectancy by setup-type.
- Add `position_multiplier_by_side` to `opportunity_evaluator.calculate_position_size` (default 1.0 for both).
- Persist the current tilt + reasoning to a new `strategy_tilt_snapshots` Mongo collection (audit trail).
- Expose via `GET /api/trading-bot/strategy-tilt` for the dashboard.
- Unit tests for Sharpe crossover, parity, dual-collapse pause.

**Status:** NOT STARTED · P1 · deferred until post-Phase-13-v3 (need LONG side producing real data first so tilt math isn't lopsided by definition).

### CRITICAL FIX #2 — Model Protection gate was class-collapse-blind (2026-04-22, post first retrain)

**Finding:** After shipping CRITICAL FIX #1, the Phase 1 retrain ran successfully and produced a class-balanced `direction_predictor_5min` v20260422_162431 with accuracy 43.5%, UP recall ~0.30, macro-F1 0.36. BUT the Model Protection gate rejected it because `0.4346 < 0.5351` (old model's accuracy). Problem: the old collapsed model "wins" accuracy precisely BY collapsing — predicting the DOWN majority class on every bar gives high aggregate accuracy in bearish training windows while yielding zero tradeable LONG signals. Classic Goodhart's law — we were measuring the wrong thing.

**Fix (`services/ai_modules/timeseries_gbm.py` L461–L540, `_save_model`):**
- Replaced `new.accuracy > old.accuracy` with a multi-metric gate driven by per-class recall and macro-F1.
- **Escape hatch**: if active is class-collapsed (`recall_up < 0.05`), promote ANY new model whose UP recall beats active AND DOWN recall ≥ 10%. This unblocks the specific situation we're in right now.
- **Normal path** (once active is healthy): require new UP recall ≥ 10% AND DOWN recall ≥ 10% AND new macro-F1 ≥ 0.92 × active macro-F1. The 8% macro-F1 slack allows for noise while preventing outright regression.
- Logs much richer: both accuracy AND macro-F1 AND per-class recall for active vs new.

**Regression tests — `tests/test_model_protection_class_collapse.py` (8 new, all passing):**
- `test_promote_when_active_is_collapsed_and_new_improves_up_recall` — reproduces the EXACT Phase 13 v2 situation; asserts the fix now promotes.
- Escape hatch must still reject if new's DOWN recall is broken.
- Normal path rejects any model with UP recall < 10%, DOWN recall < 10%, or macro-F1 below the 92% floor.
- Legacy active models without recall fields → treated as collapsed → new promotes.

**Force-promote command (one-shot unblock for current archived model):**
```bash
# on Spark, outside Python:
mongo tradecommand --eval '
  const a = db.timeseries_models_archive.findOne(
    {name:"direction_predictor_5min", version:"v20260422_162431"},
    {_id:0}
  );
  if (!a) { print("archived model not found"); quit(1); }
  a.updated_at = new Date();
  a.promoted_at = new Date();
  db.timeseries_models.updateOne({name:"direction_predictor_5min"}, {$set: a}, {upsert:true});
  print("PROMOTED direction_predictor_5min v20260422_162431");
'
```

Or future retrains will auto-promote once the protection fix is pulled + backend restarted.



### CRITICAL FIX #1 — Generic direction_predictor class-balance (2026-04-22, Phase 13 v2 post-mortem)

**Finding:** Phase 13 v2 revalidation showed 10/10 LONG setups with `trades=0` in Phase 1 (shorts promoted cleanly: SHORT_SCALP 1.52 Sharpe, SHORT_VWAP 1.76, SHORT_REVERSAL 1.94). Root cause found via code review: `revalidate_all.py` loads ONE model for AI filtering — `direction_predictor_5min` — and that model is trained by `TimeSeriesAIService.train_full_universe` in `services/ai_modules/timeseries_service.py`. That path builds `xgb.DMatrix(...)` without `weight=` and calls `xgb.train()` directly, **completely bypassing** `TimeSeriesGBM.train_from_features()` where the 2026-04-20 class-balance fix was applied. Net effect: the generic directional model never gets per-class sample weights, collapses to the bearish-majority class (DOWN/FLAT), argmax never resolves to UP, and every LONG setup Phase 1 backtest records `trades=0`.

**Fix (`services/ai_modules/timeseries_service.py` L1111–L1141):**
- Compute `compute_per_sample_class_weights(y_train, num_classes=3, clip_ratio=5.0)` via the existing `services.ai_modules.dl_training_utils` helpers (same math used by `train_from_features` for setup-specific models).
- Pass as `weight=` to `xgb.DMatrix` for `dtrain`. Validation DMatrix left uniform (weights are a training-signal concern only).
- Log line `[FULL UNIVERSE] class_balanced sample weights applied (per-class weights=[…], sample_w_mean=1.000)` — mirrors the log pattern the user greps on Spark.
- Non-fatal: wrapped in `try/except` falling back to uniform with a warning so an 8-hour retrain never dies on a class-balance edge case.

**Diagnostic script — `backend/scripts/diagnose_long_model_collapse.py`:**
- Probes `direction_predictor_5min` + every LONG setup-specific 5m/1m model across 20 liquid symbols, ~120 rolling predictions each.
- Classifies each into MODE A (2-class regression), MODE B (3-class UP never wins argmax), MODE C (argmax UP but below threshold), MODE D (code-level miss), HEALTHY, or MODEL MISSING.
- Dumps `/tmp/long_model_collapse_report.md` + `.json`.
- Runs on Spark: `PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/diagnose_long_model_collapse.py`.

**Regression tests (17 new, all passing):**
- `tests/test_diagnose_long_model_collapse.py` (11): tally math on empty/all-UP/all-FLAT/mixed, classifier covers every MODE branch + missing-model + no-data, `LONG_ONLY_SETUPS` excludes shorts.
- `tests/test_train_full_universe_class_balance.py` (6): class-weight math proportional to Phase 13 v2 skew, `clip_ratio=5` respected, **source-level guards** that train_full_universe (a) passes `weight=` to DMatrix, (b) logs `[FULL UNIVERSE] class_balanced`, (c) imports the class-balance helpers, (d) wraps the block in a non-fatal try/except. These guards prevent a silent regression back to uniform weights.

**Full session suite: 63/63 passing** in diag + class-balance + dl_utils + xgb_balance + resolver + smb_profiles scopes.

**User verification on Spark after git pull + restart + retrain:**
```bash
# 1. After retrain, confirm the NEW log line appears for direction_predictor training:
grep "\[FULL UNIVERSE\] class_balanced" /home/spark-1a60/Trading-and-Analysis-Platform/backend/training_subprocess.log

# 2. Run the forensic diagnostic (quick — ~2-3 min):
cd ~/Trading-and-Analysis-Platform
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/diagnose_long_model_collapse.py
cat /tmp/long_model_collapse_report.md

# 3. Rerun Phase 13 v2:
/home/spark-1a60/venv/bin/python backend/scripts/revalidate_all.py 2>&1 | tee /tmp/phase13_v3.log
```
Expected: LONG setups show non-zero Phase 1 trade counts (100s like the SHORTs) and at least some LONG models promote.

### Option A — SMB Profiles + Resolver Ordering (2026-04-22)
**Finding:** Phase 13 v2 coverage-trace confirmed 3/12 scanner names had no training profile: `opening_drive`, `second_chance`, `big_dog`. These are distinct SMB patterns (not family variants of SCALP/VWAP/REVERSAL), so pure routing can't help — each needs a dedicated model. Also confirmed: XGBoost class-balance + DL purged-split fixes from prior session BOTH ACTIVE in the 8.8hr retrain.

**Changes in `setup_training_config.py`:**
  - `"OPENING_DRIVE"` — 2 profiles (5 mins / 1 min, forecast_horizon 12 / 30). Intraday opening continuation, same feature class as ORB.
  - `"SECOND_CHANCE"` — 1 profile (5 mins, forecast_horizon 12). Breakout re-try on 5-min bars.
  - `"BIG_DOG"` — 2 profiles (5 mins / 1 day). The 1-day profile has forecast_horizon=3 for multi-day holds, scale_pos_weight=1.1 for the bullish trend bias big-dog plays carry.
  - All use `num_classes=3` (triple-barrier) so they pick up the class-weighted CE + uniqueness weights automatically on next retrain.

**Changes in `timeseries_service._resolve_setup_model_key`:**
  - Added `OPENING_DRIVE / SECOND_CHANCE / BIG_DOG` to the family-substring match tuple so scanner variants like `big_dog_rvol` or `second_chance_breakout` route correctly.
  - **Ordering fix**: compound SMB keys go FIRST in the tuple. Without this, `SECOND_CHANCE_BREAKOUT` was matching BREAKOUT (substring hit earlier in iteration) instead of SECOND_CHANCE.

**Regression coverage** — `backend/tests/test_smb_profiles.py` (9 tests): each profile declared correctly, required fields present, generated model names match loader expectations, exact-name routing, family-substring routing (including the ordering bug regression), SMB short fallback to base, no-models-loaded fallback. All pass.

**Full session suite: 79/79 passing** (added 9 SMB tests to the previous 70).

**User impact after Save+Pull+Next-Retrain:**
- Coverage rate: 75% → ~100% for the 12-name scanner sample
- 5 new models: `opening_drive_5min_predictor`, `opening_drive_1min_predictor`, `second_chance_5min_predictor`, `big_dog_5min_predictor`, `big_dog_1day_predictor`
- Existing retrain already added `class_balanced` + `Purged split` to all models → these will too
- Live trading: scanner alerts for `opening_drive`, `second_chance`, `big_dog` (all 3 already in `_enabled_setups`) will hit a dedicated model instead of the general direction_predictor

### Paper-Mode Enablement for the 3 Promoted Shorts (2026-04-24)
**Change:** Added REVERSAL-family and VWAP-family scanner base names to `trading_bot_service._enabled_setups`:
  - `reversal`, `halfback_reversal`, `halfback` — so scanner alerts for REVERSAL-style setups (e.g. `halfback_reversal_short`) pass the enabled-setups filter and reach `predict_for_setup` → `SHORT_REVERSAL` model (Sharpe 1.94, +7.6pp edge).
  - `rubber_band_scalp` — was a gap; scanner emits `rubber_band_scalp_short` which strips to `rubber_band_scalp` (NOT `rubber_band`), which wasn't enabled.
  - `vwap_reclaim`, `vwap_rejection` — additional scanner variants that route to `SHORT_VWAP` (Sharpe 1.76).
  
Comments inline document why each base was added — so the next person understands the filter chain.

**User promotion commands (run on Spark after pull + restart):**
```
# Promote each of the 3 proven shorts to PAPER phase
for STRAT in short_scalp short_vwap short_reversal; do
  curl -s -X POST "http://localhost:8001/api/strategy-promotion/promote" \
    -H "Content-Type: application/json" \
    -d "{\"strategy_name\":\"$STRAT\",\"target_phase\":\"paper\",\"approved_by\":\"user\",\"force\":false}" \
    | python3 -m json.tool
done

# Verify they're now in PAPER
curl -s http://localhost:8001/api/strategy-promotion/phases | python3 -m json.tool | grep -iE "short_(scalp|vwap|reversal)|paper"
```

If the first promotion call fails with "not found" or "not registered", the strategy may need to be registered first — paste the error and we handle it.

### Startup Model-Load Consistency Diagnostic SHIPPED (2026-04-24)
**Rationale:** The latent bug above (17 trained, 0 loaded) went undetected for weeks because nothing cross-checked `timeseries_models` vs `_setup_models`. This is the safety net.

**Fix:**
- New `TimeSeriesAIService.diagnose_model_load_consistency()` — scans `timeseries_models` collection, compares against in-memory `_setup_models` keyed by `model_name`, produces a report with `trained_in_db_count` / `loaded_count` / `missing_count` / `missing_models` + per-profile `by_setup` rows with `status: loaded|missing_in_memory|not_trained`.
- Auto-runs at end of `_load_setup_models_from_db()` — **logs a WARNING on boot if anything is missing in memory**. Would have caught the 2026-04-24 bug at the first startup after the XGBoost migration.
- Exposed at `GET /api/ai-training/model-load-diagnostic` for on-demand inspection.
- Handles `_db=None` gracefully (structured error, no exception).

**Regression coverage** — `backend/tests/test_model_load_diagnostic.py` (9 tests): detects missing, clean-state, partial load, ignores failed-deserialize GBMs, by_setup coverage + status values, `_db=None` safe, endpoint wrapper + 500 error path. All pass.

**Full session suite: 70/70 passing.**

**User check on Spark after pull + restart (next boot will run the diagnostic automatically):**
```
# 1. Look for the consistency line in backend.log
grep -E "Model load consistency" /tmp/backend.log

# 2. On-demand check anytime
curl -s "http://localhost:8001/api/ai-training/model-load-diagnostic" | python3 -m json.tool | head -40
```
If you see `Model load consistency: 17/17 trained models reachable` on boot, the fix worked. If you see `MISSING:` followed by names, the loader still isn't finding them and we dig deeper.

### CRITICAL BUG FIX — setup models never loaded at startup (2026-04-24)
**Finding:** After shipping the resolver, live test on Spark showed `loaded_models_count: 0` from resolver-trace — but `/api/ai-modules/timeseries/setups/status` reported 17 trained models. Investigation:
  - Training writes to `timeseries_models` collection (xgboost_json_zlib format)
  - Startup loader `_load_setup_models_from_db()` only scanned `setup_type_models` collection (legacy xgboost_json format, effectively empty)
  - `predict_for_setup` does a pure in-memory `_setup_models.get()` lookup, no DB fallback
  - **Net effect: every `predict_for_setup` call was silently falling through to the general direction_predictor, including calls that should have used the 3 promoted SHORT_* models.** Option A routing was academically correct but had nothing to route to. Latent bug present since the XGBoost migration.

**Fix:** Extended `_load_setup_models_from_db()`. After the legacy loop, it iterates every declared profile in `SETUP_TRAINING_PROFILES`, computes `get_model_name(setup, bar)`, and looks it up in `timeseries_models`. Uses the existing `TimeSeriesGBM.set_db() → _load_model()` path which already handles xgboost_json_zlib deserialization, feature_names restore, num_classes restore. Skips dups; skips models that fail deserialization.

**Regression coverage** — `backend/tests/test_setup_models_load_from_timeseries.py` (5 tests): primary load path, empty DB safe, failed-deserialize not cached, legacy not overwritten, `_db=None` early-exit.

**Full session suite: 61/61 passing.**

**User verification on Spark after pull + restart:**
```
curl -s "http://localhost:8001/api/ai-training/setup-resolver-trace?batch=SHORT_SCALP,SHORT_VWAP,SHORT_REVERSAL,rubber_band_scalp_short,vwap_reclaim_short" | python3 -m json.tool
```
`loaded_models_count` should now report ≥17 and all shorts should show `resolved_loaded: true`.


## Active P0 Blockers
### 🟢 Pusher double-execution bug — FIXED (pending verification on Windows)
- **Root cause**: TWS mid-session auto-upgrade caused the pusher's IB client connection (fixed clientId=15) to reconnect with stale session state. Previously-submitted MKT orders got replayed by TWS as if new, causing 2×-3× execution for each flatten order.
- **Fixes applied (2026-04-20)**:
  1. `ib_data_pusher.py` — `_recently_submitted` in-memory cache stamps each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10-min window.
  2. `StartTradeCommand.bat` — pusher clientId now randomized 20–69 each startup (`set /a IB_PUSHER_CLIENT_ID=%RANDOM% %% 50 + 20`). TWS can't replay a clientId it's never seen.
  3. `routers/portfolio.py` flatten endpoint — refuses to fire if pusher snapshot > 30s old (prevents flattening against stale positions).
  4. Pre-flight cancel of prior `flatten_*` orders (already done in first pass).
- **Verification plan for next session**: re-enable TWS API, restart pusher with new fixes, queue a single test order, confirm IB shows exactly one fill.

### 🚨 Security — paper password was committed to git
- `StartTradeCommand.bat` had `set IB_PASSWORD=Socr1025!@!?` hardcoded (line 30, pre-fix).
- **Fixed**: password moved to local `.ib_secret` file loaded via `call "%REPO_DIR%\.ib_secret"`. `.gitignore` updated to cover `*.secret`. `documents/scripts/README_SECRETS.md` explains setup.
- **User action required**: rotate the paper password in IB Account Management, then create `.ib_secret` on the Windows PC with the new password.


## P1 Outstanding
- Phase 13 revalidation: `backend/scripts/revalidate_all.py` against the fixed fail-closed validator (was next after Morning Briefing)
- Phase 6 Distributed PC Worker: offload CNN/DL training to Windows PC over LAN
- Rebuild TFT / CNN-LSTM with triple-barrier targets (binary up/down → majority-class collapse)
- Wire FinBERT into confidence gate as Layer 12
- Wire confidence gate into live validation


## Model Inventory & Deprecation Status (2026-04-21)

| Layer | Model family | Count | Status | Notes |
|---|---|---|---|---|
| **Sub-models** | XGBoost `setup_specific_<setup>_<bs>` | 17 long + 17 short = 34 | ✅ Keep (retraining now) | Tabular direction predictor, uses FFD+CUSUM+TB |
| | XGBoost `direction_predictor_<bs>`, `vol_<bs>`, `exit_*`, `risk_*`, `regime_*`, `sector_*`, `gap_*` | ~65 | ✅ Keep | Generic + specialist tabular models |
| | DL `cnn_lstm_chart` | 1 | ✅ Keep | 1D CNN+LSTM on OHLCV sequences; feeds Phase 2E tabular arm |
| | DL `tft_<bs>`, `vae_<bs>` | 2 | ✅ Keep | Temporal fusion + regime encoder |
| | FinBERT sentiment | 1 | ✅ Keep | Layer 12 of confidence gate (pending wire-in) |
| | Legacy `cnn_<setup>_<bs>` | 34 | 🗑 **Deprecate post-Phase 2E** | Strict subset of Phase 2E; no unique value |
| **Meta-labelers** | XGBoost `ensemble_<setup>` (Phase 8) | 10 | ✅ Keep | Tabular meta-labeler, P(win). **Phase 2C equivalent.** Just redesigned 2026-04-21 |
| | Phase 2E `phase2e_<setup>` (visual+tabular) | 0 | 🔨 **Build** | Hybrid multimodal meta-labeler; will supersede legacy CNN |
| **Fusion** | `P(win)_final = w_tab·P_tab + w_vis·P_vis` | 0 | 🔮 Future | After both meta-labelers prove individual edge |

**Net reduction once Phase 2E ships**: 34 legacy CNN models → ~10 Phase 2E models. Phase 9 removed from training pipeline. Full-retrain time drops from ~7h to ~5h.


## Post-Retrain Roadmap (proper sequencing)

The order below is intentional — each step depends on artifacts from the prior step.

### Step 1 — [USER] Full retrain with all flags
- `TB_USE_CUSUM=1 TB_USE_FFD_FEATURES=1`
- Populates `timeseries_models.scorecard` with 15-metric grades across all current setups.
- Produces the first deflated-Sharpe-validated, uniqueness-weighted, CUSUM+FFD-featured model set.

### Step 1.5 — Setup Coverage Audit (run immediately after retrain)
Run `PYTHONPATH=backend python backend/scripts/audit_setup_coverage.py`.

Writes `/tmp/setup_coverage_audit.md` summarising, per taxonomy code:
- # of tagged trades across `trades` / `bot_trades` / `trade_snapshots` / `live_alerts`
- Win rate + avg R-multiple
- Verdict: `trainable` / `thin` / `negative_edge` / `too_few` / `unknown_outcome`
- Highlighted Phase 2E Tier-1 candidates (visual-pattern setups with enough data).

This is the critical bridge: TRADING_TAXONOMY.md defines ~35 SMB setups but the
XGBoost pipeline only trains 10 long + 10 short generic families. The audit tells
us which of the 35 have the journal coverage to warrant dedicated (setup, bar_size)
XGBoost + CNN model pairs in Step 5/Step 6.

Inputs to Step 2 (scorecard triage): A-grade generic model + strong audit
coverage  →  split into dedicated setup-specific model.

### Step 2 — Scorecard triage
- Sort all models by composite grade (A-F).
- **Delete** setups grading D/F that can't be salvaged (REVERSAL/5min almost certainly in this bucket — see `/app/memory/notes_sweep_observations.md`).
- **Widen PT/SL sweep grid** on daily setups (all converged to pt=1.5/sl=1.5/max_bars=5 — suspicious).
- Free up training budget for new setups in Step 5.

### Step 3 — Phase 2C: XGBoost Tabular Meta-Labeler ✅ COMPLETED 2026-04-21
**Consolidated into Phase 8 Ensemble** (see "Phase 8 Ensemble — REDESIGNED as Meta-Labeler" above).
Each `ensemble_<setup>` now IS the Phase 2C tabular bet-sizer: P(win | setup_direction, meta_features).

### Step 3.5 — Wire bet-sizer into `trading_bot_service.py` (NEXT)
- `confidence_gate.py` → add `_get_meta_label_signal(setup_type, features)` reading `ensemble_<setup>`
- Expose `meta_label_p_win` in confidence gate result
- `opportunity_evaluator.calculate_position_size()` → new `meta_multiplier` (capped [0.3, 1.5]) alongside volatility + regime multipliers
- Skip trade if `P(win) < 0.50` (meta-labeler says "no edge")
- Log `meta_label_p_win` + `meta_multiplier` in `trade.entry_context` for backtest uplift tracking
- Fallback: absent `ensemble_<setup>` → unchanged sizing (safe)

### Step 4 — Phase 6: Distributed PC Worker infrastructure
- Training coordinator on Spark offloads CNN/DL jobs to Windows PC over LAN.
- REST endpoint contract + job queue + heartbeat + result sync.
- Enables Step 5 (CNN visual meta-labeler would otherwise bottleneck Spark's GB10).

### Step 5 — Phase 2E: Setup-Specific Visual CNN Meta-Labeler ⭐ (high conviction)
Scalp setups (especially SMB-style) are visually defined. Tabular features flatten the chart into 46 numbers; a CNN trained on the actual chart image sees the shape.

**Architecture:** Hybrid multimodal — chart-image CNN + tabular MLP → concat → classifier.

**Pipeline:**
1. **Chart rendering** — OHLCV window → 96×96 or 128×128 PNG with candlesticks, volume bars, and setup-relevant overlays (9EMA/21EMA/VWAP). No axis labels; pure visual signal.
2. **Shared backbone** — train one CNN (EfficientNet-Small or similar) on ALL setups' charts with triple-barrier labels. Self-supervised contrastive pre-training optional.
3. **Per-setup fine-tune heads** — each setup gets a lightweight fine-tuning head on ~5-10k labeled examples.
4. **Tabular fusion** — concat MLP features (46 base + setup + regime + VIX + sub-model probs from cnn_lstm/TFT) with backbone visual features before the classifier head.
5. **Inference** — López de Prado meta-labeling, visual edition: XGBoost says "rubberband scalp candidate" → multimodal CNN sees the chart + context → returns `P(win)`. Combined into bet size.
6. **Explainability** — Grad-CAM activation overlay surfaced to NIA UI so user can verify the CNN is learning real patterns (exhaustion wick, volume climax) vs spurious noise.

**Distribution (requires Step 4):** Spark GB10 trains the shared backbone once a week; Windows PC fine-tunes per-setup heads overnight.

### Step 5.5 — DEPRECATE legacy `cnn_<setup>_<bs>` (34 models) — post-Phase 2E
The current 34 per-setup CNN models in `cnn_models` collection are a **strict subset** of what Phase 2E does:
- Image-only input (no tabular fusion)
- Isolated per-setup training (~2K samples each, no shared backbone transfer learning)
- 17-class pattern head is tautologically 100% (every sample has same setup_type); only the win-AUC head carries signal

**Cutover plan:**
1. Phase 2E models go live + validated on scorecard (≥2 weeks shadow mode)
2. Switch `confidence_gate.py` to read `phase2e_<setup>` instead of `cnn_<setup>`
3. **Remove Phase 9 from the training pipeline** (shaves ~1h 51min off every full retrain — from ~7h to ~5h)
4. Archive `cnn_models` collection (30-day backup), then drop
5. Remove `chart_pattern_cnn.py` + per-setup loop in `cnn_training_pipeline.py`
6. Scorecard: replace 34 `cnn_<setup>` rows with ~10 `phase2e_<setup>` rows

**Keep** `cnn_lstm_chart` (DL model) — different modality (1D CNN+LSTM on OHLCV sequences, not images). Its output feeds into Phase 2E's tabular arm as a stacking feature.

### Step 6 — Add SMB-specific setups (tiered)
Only after visual CNN infrastructure exists, and only for setups the CNN/scorecard analysis justifies.

**Tier 1 — Scalp/Intraday (5-min and 1-min):**
- `RUBBERBAND_SCALP` (long + short) — 2+ ATR stretch from 9EMA/VWAP → reversion scalp
- `EMA9_PULLBACK` (long + short) — trending stock pulls to 9EMA on lower volume → continuation
- `FIRST_RED_CANDLE` / `FIRST_GREEN_CANDLE` — first reversal candle after parabolic move

**Tier 2 — Day-structure:**
- `OPENING_DRIVE_REVERSAL` (5 min) — exhausted opening drive fade
- `HALFBACK_REVERSION` — 50% morning-range retrace
- `INSIDE_DAY_BREAKOUT` (1 day)

**Tier 3 — Cross-instrument (needs SPY sync in training data):**
- `RS_VS_SPY_LONG` / `RW_VS_SPY_SHORT` — relative strength divergence vs SPY

Each new setup needs: detector in `setup_pattern_detector.py`, feature extractor in `setup_features.py`/`short_setup_features.py`, PT/SL sweep entry, and (if visual) chart-render config.


## P2 / Backlog
- Motor async MongoDB driver migration (replace sync PyMongo in hot paths)
- Per-signal weight optimizer for gate auto-tuning
- Earnings calendar + news feed in Chat
- Sparkline (12-wk promotion rate) on ValidationSummaryCard
- `server.py` breakup → `routers/` + `models/` + `tests/`



---

## Completed 2026-05-11 (v19.34.88)
- ✅ Pusher-routed cancellation queue end-to-end (backend + pusher).
- ✅ 31 orphan stops cleared across 7 symbols (ADBE, BMNR, CCL, EBAY, EFA, MDT, NCLH).
- ✅ MDT short-bracket cleanup via `keep_oca_group` operator override.
- ✅ Audit shows 0 symbols with stacking.

## Newly-Surfaced (post-2026-05-11 cleanup)
- 🟡 (P1) **Auto-orphan-sweep on position close**. After today's session we found ~31 orphan stops left dangling because some target legs weren't OCA'd to their stops. When a position transitions `>0 → 0` (target fill, manual close, EOD), the bot should auto-queue cancels for any remaining pending stops/targets on that symbol. Add as post-close hook in `position_reconciler.py` or as a watcher in `bot_persistence.py`.
- 🟡 (P1) **Sizing-aware bracket pick** in `cancel-excess-bracket-legs`. Current logic picks the *newest* bracket pair regardless of qty. LIN example: a 21sh "newest" bracket would have been kept while a 47sh OCA bracket was cancelled, leaving 47 shares unprotected. Should prefer the bracket whose qty matches `|bot_position|` most closely (then OCA-grouped > non-OCA > newest as tiebreakers).
- 🟢 (P2) **Mass-cancel endpoint** `/api/trading-bot/sweep-all-orphans` — single-shot version of today's python loop. Cancels every pending leg on every symbol where `|bot_position|==0`.
- 🟢 (P2) Cancel-queue TTL + reaper for stale `pending` entries (>5min unclaimed → log + auto-mark `expired`).

## Completed 2026-05-11 evening (v19.34.89 + v19.34.90)
- ✅ Auto-orphan-sweep periodic loop (30s cadence, only_gtc=False, env-gated).
- ✅ Tier 3 fallback in `_fetch_ib_open_orders` (pusher-only deploys).
- ✅ Queue fallback in `cancel_orphan_gtc_orders` when ib_direct down.
- ✅ Immediate post-EOD sweep wired into `check_eod_close`.
- ✅ 15/15 pytest passing across v88 + v89 suites.

## Order-Pipeline Hardening — Remaining (was P1, still applies)
- 🟡 (P1) **v19.34.91 — Sizing-aware bracket pick** in `cancel-excess-bracket-legs`. Prefer the bracket whose qty matches `|bot_position|` most closely. Eliminates the LIN under-protection trap.
- 🟡 (P1) **v19.34.92 — OCA-enforcement audit + fix**. Find code paths placing stops/targets without OCA grouping (likely scale-in handler). Force every bracket placement to use an OCA group so target-fill auto-kills the paired stop at IB-level — prevents orphans from forming to begin with.
- 🟡 (P1) **v19.34.93 — Resize-bracket-to-ib-truth** one-shot endpoint (atomic cancel+re-attach).

## Completed 2026-05-11 evening pt 2 (v19.34.91 + v19.34.92)
- ✅ Sizing-aware `cancel-excess-bracket-legs` (greedy fill to match `|bot_position|`).
- ✅ OCA enforcement at placement time (cloud queue + pusher both propagate `oca_group`).
- ✅ 37/37 pytest passing across full order-pipeline suite.

## Order-Pipeline Hardening — Remaining
- 🟡 (P1) **v19.34.93 — `resize-bracket-to-ib-truth`** atomic cancel+re-attach endpoint. Single operator call to fix any size drift.
- 🟢 (P2) **Cancel-queue TTL/reaper** for stale `pending` entries (>5min unclaimed → log + auto-mark `expired`).
- 🟢 (P2) **Mass-cancel endpoint** `/sweep-all-orphans` (single-shot version of today's python loop) — though v89 auto-sweep makes this lower priority.

## Completed 2026-05-11 late evening (v19.34.93 + v19.34.94 + data audit)
- ✅ `resize-bracket-to-ib-truth` atomic cancel+re-attach endpoint.
- ✅ Cancel-queue TTL/reaper (auto-expire >10min pending, revert >5min claimed).
- ✅ 49/49 pytest passing across full order-pipeline + reaper suite.
- ✅ Confirmed Collect Data button is the correct training-data refresh entry point.
- ✅ Confirmed TrainingPipelinePanel "Start Training" button is the correct trophy-run entry point.

## Order-Pipeline Hardening — COMPLETE
All P1 hardening shipped (v88, v89, v90, v91, v92, v93, v94). Pipeline is self-healing end-to-end.

## Active TODO for User (low-effort)
- 🟢 Click NIA → DataCollectionPanel "Collect Data" to top up 6-day backfill gap.
- 🟢 After collection drains, click NIA → TrainingPipelinePanel "Start Training" to refresh the 15-day-stale trophy run.

## Next Feature Work — Pick Whichever
- 🟡 V6 UI refactor (Variant C, 4-pane layout).
- 🟢 Position Health Console (`/app/memory/V6_POSITION_HEALTH_CONSOLE_SPEC.md`).
- 🟢 Safety Activity Stream (`/app/memory/V6_SAFETY_ACTIVITY_STREAM_SPEC.md`).
- 🟢 (P2) Tick-level Stop Run Probability ML Module.
- 🟢 (P2) Setup-landscape EOD self-grading tracker.
- 🟢 (P2) Mean-reversion metrics service.
- 🟢 (P2) Liquidity-aware trail in `stop_manager.py`.
- 🟢 (P3) Chart bubble click → fire focus symbol.
- 🟢 (P3) SEC EDGAR 8-K integration.
- 🟢 (P3) Break up `server.py` and `trading_bot.py` monoliths.

## 2026-06-10 — Model-family fix roadmap (post-audit; prioritized)
Audit: /app/memory/AUDIT_model_families_2026-06-10.md  (110 models: 59 dead, 46 collapsed)
- 🟡 P-LIVE-1 (ensemble): VERIFY FIRST — argmax-recall "collapse" is likely the wrong
  lens for the gate's graded p_win meta-labeler (gate force-skips p_win<0.5 yet
  take-rate is 33% → p_win spans 0.5). Run scripts/diag_ensemble_pwin_live.py.
  If p_win discriminates → false alarm (do NOT class-weight, breaks 0.5/0.75 thresholds).
  If squashed → rebuild meta-label target + recalibrate thresholds.
- 🔴 P-LIVE-2: 2/7 base direction_predictor collapsed → P0 gate auto-rejects on next
  retrain; optional one-time quarantine of currently-promoted collapsed ones.
- 🟢 P-WIRE: regime-conditional model SELECTION. ~18 healthy two-sided regime models
  (acc 0.56–0.78) are DEAD — live layer loads only base direction_predictor_{tf}
  (+ regime FEATURES + heuristic adjust). MUST be earned by an apples-to-apples
  OFFLINE backtest (generic vs regime-specialized on the SAME recent bars; training
  accuracies are on different regime subsets, not comparable). Build: additive
  model_name_override on predict_for_setup → offline compare harness → if it wins,
  wire regime→model selection via gate's classify_regime (shadow-gated).
- 🟡 P-TARGET(gap): session-gap redesign — only day-open gap ≥0.5%, fill within EARLY
  window (first ~30m) vs gap-and-go. RETIRE daily/weekly gap_fill (not meaningful).
- 🟡 P-RETIRE/fix: risk_of_ruin (6/6 collapsed), sector_relative (3/3), exit_timing (0.455 dead).
- Separation discipline CONFIRMED: training pipeline (clean historical CV) must NOT
  ingest live trade PnL; learning loop adapts posture via SHADOW mode only.

## 2026-06-12 — v324 chart infinite history (SHIPPED, user-apply pending)
- ✅ Issue "Chart historical lazy-loading/scrolling" → apply_v324.py @ https://paste.rs/peUbU
  (md5 a77306d517c25cc540de613f1e673a69). Removes daysLoaded doubling; /chart-history
  cursor pagination + per-symbol timeframe graying + auto-hop. Sandbox e2e PASSED.
- NEXT UP: Deep TP/SL + Trade Management audit & unification (PT geometry off daily
  ATR = unreachable; SmartStopService/BRACKET_V2 disconnected from evaluator).
- Then: M0 OCA ladder validation (needs live scalp fill post-restart), INT-21 IGV
  range-break guards, ELF→XLE _industry_to_etf mapping fix, thought-noise content
  filter (v323c r2).

## 2026-06-12 — v325 + v325b TP/SL geometry fix (SHIPPED, user-apply pending)
- ✅ "Deep TP/SL audit & unification" root-cause phase → apply_v325.py @
  https://paste.rs/SgWMB (md5 c41035a81d0dfe1a567fe9290db3432c). Horizon-scaled
  stops + canonical daily-ATR basis + detector-stop cap + reach gate (block >1.5×).
- ✅ Bracket geometry chart overlay → apply_v325b.py @ https://paste.rs/sQEqc
  (md5 ef4ba7e6ed26cd19fc90cfd728df3b3b). Reach cone + PT reach badges + clock line.
- VALIDATION PLAN: after a few sessions re-run diag_pt_reachability.py — PT1
  touch-rate must move off 0%; entry_context.multipliers.hsbg stamps enable
  before/after cohort compare. Watch stream for ✂️ horizon-cap / ⚠️ borderline /
  🚫 reach-block events.
- v326 (NEXT in TP/SL track): SmartStopService unification — merge SETUP_STOP_RULES
  with evaluator SETUP_MULTIPLIERS into one source of truth; optionally wire
  structure-snapping (S/R, hunt zones) into entry path; fix /audit-stops +
  /fix-stop fake atr=2% inputs.
- Still open: M0 OCA ladder live validation, INT-21 IGV guards, ELF→XLE mapping,
  thought-noise content filter (v323c r2), Atlas password rotation (user).

## 2026-06-12 — v326 SmartStop unification (SHIPPED, user-apply pending)
- ✅ One SSOT for initial-stop sizing (evaluator SETUP_MULTIPLIERS), real daily ATR
  in /audit-stops + /fix-stop, HSBG horizon parity in calculate_intelligent_stop.
  apply_v326.py @ https://paste.rs/tM454 (md5 7844fa6c6a1286adddee49284e1ff12c).
- TP/SL track remaining (later): optional structure-snapping into evaluator entry
  path (S/R + hunt zones at trade creation); trailing-mode unification with
  StopManager (smart_stop trailing modes still independent of stop_manager.py).

## 2026-06-17 — NEW BACKLOG (operator-approved this session)
- [P1] DETECTOR EDGE SCORECARD (saved idea): nightly read-only diag that replays each LIVE
  detector's last-N-day realized R (entry/stop/target sim like v329/v330) → at-a-glance ranking of
  which setups actually earn vs which to fix next. Build after the scalp generalization sweep.
- [P1] SCALP GENERALIZATION SWEEP: apply find→trade-replay→rewrite to ALL scalps (not just
  hitchhiker/second_chance/big_dog). PRE-STEP: setup-category audit — verify each "scalp" is tagged
  correctly vs "intraday"/swing/etc.; recategorize mis-tagged setups.
- [P1] TIME-DECAY AUDIT (NEW): investigate whether Multi-day / Swing / Position / Investment tier
  trades have any time-decay / max-hold / time-stop exit triggers; decide if we should add time-based
  exit limits per tier. Read-only audit first, then propose.
