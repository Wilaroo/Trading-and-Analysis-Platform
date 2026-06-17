# Scalp Fidelity Investigation (SMB cheat-sheet vs code) — 2026-06 fork

Operator goal: get the system to **find / fire / trade** the SMB scalps PROPERLY
(starting with rubber_band), measured against the real cheat sheets. All work is
READ-ONLY diags delivered via paste.rs (AGENTS.md §2.2). No detector patched yet.

## Live DGX anchor
- `backend/services/enhanced_scanner.py` SHA256 (2026-06-17):
  `b631ebad524d6fc8151cd4d9f979b73c0b1997337557a680035d6a9742e1e3e3`
- Sandbox file is line-shifted ~+42 lines vs DGX → patchers MUST anchor on exact
  text + assert PRE_SHA, never line numbers.
- 1-min bars CONFIRMED available: `ib_historical_data`, `bar_size:'1 min'`, 259M docs,
  date = tz-aware ISO. → snapback double-bar-break trigger is buildable at native granularity.

## Detector locations (DGX line nums)
rubber_band 4402 · second_chance 4923 · backside 4961 · off_sides 5002 ·
fashionably_late 5044 · hitchhiker 4747 · big_dog 5882 · gap_pick_roll 6316.
Snapshot has `.open` and `.atr` (used by back_through_open etc.) → ATR-from-open computable.

## Issues CLOSED by data
- gap_pick_roll: already tape-gated HIGH (line 6343) → no-op.
- off_sides_short: shorts into strength — 70% bullish tape, 4.3% confirm, no edge → correctly
  suppressed; DO NOT promote.

## Cheat-sheet vs code fidelity (audited 6 SMB setups)
Systemic deviation: every detector fires on a STATE; every SMB scalp's edge is a
TRIGGER (aggressive 1-min range/candle break). None implement the trigger; none enforce
the daily attempt cap (2-strikes / one-and-done). Fidelity: fashionably_late 🟢 High;
backside/hitchhiker 🟡 Med; rubber_band/second_chance/big_dog 🔴 Low (second_chance is
basically a VWAP-proximity long, not a retest; big_dog has no wedge/vol-contraction/mid-day gate).

## Sanitized edge (v321b, last 14d, canonical classify_close)
- 1646 raw closed → only **66 sanitized** in 14d. Per-setup edge mostly UNMEASURABLE.
- n≥5 only: daily_breakout -0.40R(n6), trend_continuation_short -0.16R(n19),
  fashionably_late -0.09R(n7, ~breakeven).
- ELEPHANT: system alerts in the thousands, almost nothing becomes a clean trade.

## rubber_band FIND census (v321c, 14d, ext≥1%, 1-min bars)
- 919 real snapback event-days (32% of scanned cells); we alerted 55 cells / 192 alerts.
- **RECALL 3%** (we miss 97% of real snapbacks), **PRECISION 49%**, 14/55 cells over-fire (max 29/day).
- Extension calibration: p50 day = 1.09% below open; ≥2.0% = 29% of cells, ≥3.0% = 18%.
  → FIRE detector should use ext≥~2% (not 1%) + snapback trigger + RVOL + 2/day cap.

## Diags shipped this session (paste.rs, round-trip verified)
- diag_v320y_off_sides_tape.py        sha 92d3362e… (paste Dw58y)
- diag_v320z_rubber_band_truth.py     sha bc1be652… (paste sckt5)
- diag_v321a_setup_fidelity.py        sha c3c3f94d… (paste 4rLJb)  [edge col VOID — raw pnl]
- diag_v321b_sanitized_edge.py        sha 3413ee27… (paste cGdbJ)  [canonical sanitized edge]
- diag_v321c_rubber_band_replay.py    sha 71a5c7de… (paste hwSrg)  [1-min FIND census]
- diag_v321d_trade_autopsy.py         sha 67dc7414… (paste AMub7)  [alert→trade→funnel autopsy]

## Plan: find → fire → trade (rubber_band first, then apply template)
1. FIND ✅ proven (v321c: 3% recall).
2. TRADE 🔎 v321d running — find WHERE 192 alerts → 0 clean trades die (gate vs exit-mgmt vs shadow).
3. FIRE ⏭ redesign `_check_rubber_band` patcher: ext-from-open≥~2% + 1-min double-bar-break
   snapback within ~6 bars of LOD + RVOL quality + clean-trend avoid + 2/day cap.
   OPEN IMPLEMENTATION Q: how does a detector access recent 1-min bars at runtime?
   (scanner has _prime_wave_live_bars + ib_historical_data; may need snapback flag stamped
   on the snapshot during build, OR a bar fetch inside the detector). Verify before patching.
4. Generalize template to hitchhiker, second_chance, big_dog.

## ⚡ PIVOTAL FINDING (v321d + v321e playbook autopsy, 14d)
- rubber_band: 192 alerts, 60% HIGH+, **0 trades** (exec 0%) → GATE problem, not exit.
- PLAYBOOK-WIDE: alerts=43,156 → trades=710 → **sanitized=66**.
  **exec%=2%, clean-yield%=0%.**
- VERDICT rollup: GATE-no-exec=37 setups, low-sample=21, SHADOW=3, EDGE-neg=3.
  - SHADOW (execute but learning_only/paper): squeeze, gap_fade, rs_leader_break (+daily_breakout heavy).
  - EDGE-neg (n≥5 clean): trend_continuation -0.16R(n19), daily_breakout -0.40R(n6),
    fashionably_late -0.09R(n7).
- CONCLUSION: the binding constraint is the **FIRE/execution gate**, NOT detector quality.
  Even setups at 100% HIGH+ priority (daily_squeeze 6206, power_trend_stack 3395, pocket_pivot
  1559, breakdown_confirmed 2064) execute 0. Detector redesign (rubber_band etc.) is MOOT until
  alerts can execute. Many "trades" that do happen are learning_only/shadow.
- NEXT DIAG: diag_live_gate_decisions.py (reads confidence_gate_log) → is the block
  meta-labeler force-skip (p_win<0.50), low-confidence in CAUTIOUS/DEFENSIVE mode, or
  empty-log/downstream execution-risk block? Pushed paste mYx0x,
  sha 0e1c0cc8d16a7a48f4450a556bd9d064fabda31fe020378454de8e9c3523ad67.
- Diags this leg: v321d (paste AMub7 sha 67dc7414…), v321e (paste TE7r8 sha 992685c4…).
- REVISED SEQUENCING: (1) diagnose+fix FIRE gate → (2) redesign rubber_band detector
  (snapshot pre-gate + 1-min snapback via _get_intraday_bars_from_db(sym,"1 min",N) + 2/day cap)
  → (3) generalize. Do NOT patch any detector until the gate lets alerts execute.

## 🔧 CORRECTION (diag_live_gate_decisions output, 2026-06)
My "nothing executes / FIRE gate blocks everything" headline was OVERSTATED — corrected:
- confidence_gate_log: 89,508 decisions → GO=23,530 (26%), REDUCE=17,461, SKIP=48,517.
- bot_trades PLACED: total 15,167; 30d=4,035; 7d=334. The system IS trading (~334/wk).
- Dominant SKIP = meta-labeler force-skip p_win<0.50 (11,395) ≫ low-confidence (1,910).
  Mode mostly 'normal' (GO=38), regime_score median 62 → mode is NOT the blocker; the
  0.50 EV cut is. confidence_score piles at 30-39 (just under GO line).
- TWO distinct problems (not one):
  (A) FIRE SELECTION: meta-labeler 0.50 force-skip starves rubber_band/big_dog/daily_squeeze
      etc. (the GATE-no-exec setups) — an EV-calibration lever.
  (B) TRADE QUALITY: of ~710 placed in 14d, only 66 survive sanitization (~9%); rest are
      shadow/learning_only/hygiene. Downstream quality problem.
- v321e "exec 2%" was alerts÷trades across MISMATCHED funnels (live_alerts ≠ gate decisions
  ≠ trades). Real recent trade rate ≈334/7d; volume dropped ~4x vs 2-4 weeks ago.
- Reconciliation diag: diag_v321f_reconcile.py paste AcmiO
  sha 98c32ccbd936fe7c36131380397a16e15ca4bdf8b04f758487d9597da50aa80d
  (verifies status dist 15,167 vs closed 1,646 vs in-window 710 vs sanitized 66; live/shadow split).

## ✅ ROOT CAUSE CONFIRMED (v321f + v321g, 2026-06)
v321f: 15,167 bot_trades = simulated 6,632 + rejected 6,325 + closed 1,646 + vetoed 548 + open 9.
  14d=854 placed, trade_type=paper 100%, learning_only 44%. 854→204 closed→73 sanitized.
  GO→order conversion 46-70%. live_alerts 179,082 (≠ gate decisions). System is PAPER-only.
v321g cross-tab (30d, 24,544 scored decisions): GO-rate rises 0→0→1→13→73→96% with score →
  **scoring is CORRECT, not inverted.**
  - SKIP attribution: **meta_pwin<0.5 = 11,413 (86%)**, low_score 1,912 (14%), regime_supp 4 (0%).
  - GO-eligible (score≥38)=7,595; **1,793 (24%) force-SKIPPED by the meta-labeler wall.**
ROOT CAUSE = confidence_gate.py L924-929: flat `p_win < 0.50 → force_skip`. EV-blind: a 2:1
  setup is breakeven at p_win=0.33, so the 0.50 wall kills positive-EV setups. This is THE lever.
  evaluate() has entry_price+stop_price (risk) but NOT target → RR must come from per-setup
  expectancy (regime_expectancy cells / strategy_stats) or an assumed RR.
CAVEAT: sanitized edge (66 trades) is negative/thin → loosening could add negative-EV trades.
  → MUST roll out SHADOW-FIRST (log what EV-aware cut would admit; measure paper EV; then flip).
Diags: v321f paste AcmiO sha 98c32ccb…; v321g paste wfd5S sha 2302faff….
NEXT: need DGX live SHA + grep of confidence_gate.py L889-940 before building the
  EV-aware meta-labeler patcher (shadow mode first). This is the FIRST patcher of the investigation.

## 🚀 PATCHER SHIPPED: patch_v322_ev_aware_meta.py (2026-06)
- Target: confidence_gate.py L919-929 (the meta veto). DGX live SHA == sandbox (NO DRIFT):
  PRE_SHA  = 454318302b85bfd17f6e2b789221c074bfa08b30d30c4b8f28828ed9cb35193a
  POST_SHA = de14fd64b4887c15494726f0bc60a250e75a1fe01c8fb05c1ea3c7f379835709
- Rule (per operator: ACTIVE, per-setup expectancy, margin 0.05):
  floor = 1/(1+2.0)+0.05 = 0.383 (was flat 0.50). Override via setup_regime_expectancy
  weighted_mean_r: >0 → floor=min(floor,0.30); <=hard_r → floor=0.50. force_skip = p_win<floor.
- §2.2 patcher: PRE/POST SHA guards, base64 anchored chunk, --check/--apply/--rollback, backup.
  TESTED on isolated copy: check OK, apply→POST_SHA+compiles, rollback→byte-identical to PRE.
  paste.rs vVBhG, patcher sha ad120515322f45e741db213f731f8a9204eb859d557f3b4857aaee75a247cce3.
  Repo copy: backend/scripts/patch_v322_ev_aware_meta.py.
- DEPLOY: curl patcher → --check → --apply → ./start_backend.sh --force.
- POST-DEPLOY VERIFY: re-run diag_v321g (meta_pwin<0.5 SKIP share should drop, GO-eligible-vetoed
  drop, more GO/trades) + watch diag_v321b sanitized avgR of newly-admitted setups stays ≥0.
  If newly-admitted trades bleed → --rollback or raise RR_assumed/floor.

## ✅ DEPLOYED & LIVE (2026-06-17 ~10:40 ET)
- Operator ran --check (PRE_SHA OK) → --apply (hit POST_SHA de14fd64… exactly, backup
  confidence_gate.py.bak_v322) → ./start_backend.sh --force. Backend: "Application startup
  complete", mongo green, ib_gateway green/connected. No import errors. Patch is LIVE.
- Post-deploy verifier: diag_v322_verify.py paste k4cfX
  sha 76796f26716599fc28280744643dd6210a3b0c7d6c67f6c75739233a39fba4f2
  (counts new 'EV-aware ALLOW' / '< EV-floor' reasoning vs old '< 50% NO EDGE').
- PENDING (wall-clock): run diag_v322_verify (today's session) → then diag_v321g (meta_pwin
  SKIP share should drop from 86%, GO-eligible-vetoed from 24%) → then diag_v321b (newly-admitted
  setups' sanitized avgR must stay ≥0; if bleeding, --rollback).
- NEXT after gate verified: redesign _check_rubber_band detector (snapshot pre-gate +
  1-min double-bar-break snapback via _get_intraday_bars_from_db(sym,"1 min",N) + ext≥2% +
  2/day cap) so it FIRES and now EXECUTES. Then generalize to hitchhiker/second_chance/big_dog.

## 🔬 FIRE FUNNEL traced to the TOP (v322b → v323 → v324, 2026-06-17)
Post-v322 the meta-veto is no longer the binding gate. The funnel:
- v322b: EV-aware ALLOWs (16) → 0 GO; admits were low-score (squeeze 16, fashionably_late 3).
- v323 (8h, 542 dec): GO median 56 (min 50), REDUCE 35-48, SKIP median 22. Clean gap at 48→50
  ⇒ effective GO bar ≈ 50. meta_labeler now only ADDS (+10.9, 0 neg) ✓. SECTOR is a net DRAG
  (-324, -6 per "short against strong sector", fires 496×). quality_inplay doesn't discriminate.
- v324 (8h, 558 dec): 100% CAUTIOUS (GO=50), regime_state=HOLD, regime_score CONSTANT 68.
  91 score≥38 GO-eligible, 83 NOT GO — ALL carry regime_suppression. Lowering threshold ⇒ ~0× GO.
ROOT (top of funnel) = a persistent DEFENSIVE REGIME posture: HOLD→cautious raises GO to 50 AND
  activates regime_suppression. This sits ABOVE meta-veto/score/detector. NOT obviously a bug —
  it's the risk layer. RED FLAG: regime_score pinned at exactly 68 (no intraday variance) ⇒ maybe
  STUCK classifier.
- v325 regime/mode timeline (paste qnvs4 sha 3ee6eeeb…) staged to test stuck-vs-legitimate over 21d:
  few distinct regime_score values + cautious every day ⇒ stuck (upstream lever); varies ⇒ legit caution.
Diags staged: v322b (pC7MQ), v323 (daDEY), v324 (Xot41), v325 (qnvs4).
DECISION PENDING on v325: if stuck → fix regime→mode trigger (biggest GO unlock); if legit → accept
  selectivity. Sector penalty (-6) is a secondary recalibration candidate either way.

## 🔍 v326 — REGIME/MULTI-TF CONTEXT TIMELINE (fork resume, 2026-06)
ROOT-CAUSE CODE TRACE (HIGH confidence, read-only): the 100%-CAUTIOUS posture
(v324: regime_state=HOLD, composite pinned 68) is NOT decided by composite_score.
`confidence_gate._update_trading_mode` (L2090-2104) PREFERS SPY `multi_tf.context`
over the legacy 68→NORMAL map. `mode_for_direction` (multi_tf_regime.py L185-201):
  - UNKNOWN context → excluded by L2092 guard → falls to legacy → 68 → NORMAL.
  - MIXED context  → returns 'cautious' for BOTH long & short (L200-201).
So 100% cautious ⟹ SPY context is **MIXED** (not UNKNOWN). MIXED arises when the
long-anchor lane (20/50/200 SMA + structure, L109-122) lands NEUTRAL (41-59) OR the
intraday lane is missing (classify_context anchor-only fallback, L168-172). The
composite=68 (bullish) vs anchor-lane=NEUTRAL mismatch is the suspected lever.
WHY v325 was insufficient: confidence_gate_log lacks multi_tf.context + lane scores.
v326 reads `market_regime_state` (1 upserted doc/day, persists full multi_tf) → shows
per-day composite/state/context/lane scores+bias/modes + WHY-MIXED attribution.
SHIPPED: diag_v326_regime_mtf_timeline.py — paste https://paste.rs/QklXu
  sha256 1716f8c10a450a3366e28077c9fbadc149b19359a482ee4eadaa9aa74ccf28df (round-trip OK).
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v326_regime_mtf_timeline.py --days 21
DECISION PENDING on v326 output:
  - long-anchor NEUTRAL every day (composite says bullish) → recalibrate anchor lane
    OR remap MIXED→ (long:normal) when long-anchor bias≥NEUTRAL & composite≥55. Biggest GO unlock.
  - intraday lane UNKNOWN → SPY 1h/5m/1m intraday bars not backfilled → backfill fix.
  - context/scores vary day-to-day → caution legit → accept selectivity, pivot to sector(-6) recal.
DGX git HEAD at resume: 8a69292a (v19.34.320r). NO patcher yet — read-only diag only.

## ✅ v326 DGX RESULT (2026-06-17) — CLASSIFIER IS NOT STUCK; MIXED-when-anchor-UP is the lever
Per-day (DGX, last 10d): comp 48→54(ALIGNED_UP)→65(ALIGNED_UP, mode aggressive/defensive)
→ 06-15 comp68 ALIGNED_UP long91/UP intra66/UP aggressive/defensive
→ 06-16 comp68 **MIXED** long91/UP intra **43/NEUTRAL** cautious/cautious
→ 06-17 comp68 **MIXED** long91/UP intra **46/NEUTRAL** cautious/cautious.
Distinct comp scores=4, distinct long-lane=3, contexts vary (ALIGNED_UP=6, MIXED=2, PULLBACK=1).
WHY-MIXED attribution: 2/2 MIXED days = intraday lane NEUTRAL (long anchor strongly UP=91).
DIAGNOSIS (HIGH): NOT stuck. The cautious posture is ONLY the last 2 days, triggered because
classify_context (multi_tf_regime L173-181) only recognizes (UP,UP)=ALIGNED_UP and (UP,DOWN)=
PULLBACK; (UP,**NEUTRAL**) falls through to MIXED → mode_for_direction MIXED branch (L200-201)
flattens BOTH long & short to 'cautious'. This is miscalibrated: a strong daily uptrend (anchor 91)
with a merely-NEUTRAL (not opposing) intraday should keep LONGS at NORMAL (buyable consolidation)
and SHORTS defensive — not cap both to cautious. The cautious mode raises GO bar 38→50
(confidence_gate L1026-1031), starving GO.
PROPOSED LEVER (surgical, mode_for_direction MIXED branch, anchor-aware):
  MIXED + long_anchor bias UP  → long:normal,   short:cautious
  MIXED + long_anchor bias DOWN→ long:cautious,  short:normal
  MIXED + anchor NEUTRAL/UNK   → both cautious (unchanged)
Leaves classify_context, ALIGNED/PULLBACK/BOUNCE, and the UNKNOWN→legacy guard untouched.

## 🔬 v327 — MODE-FIX UNLOCK SIM + suppression-mode probe (READ-ONLY, staged)
regime_suppression is INDEPENDENT of trading_mode (per setup×dir×regime-band EV table,
confidence_gate L1041-1080; runs shadow|active). v324 attributed 83 not-GO to regime_suppression
reasoning, but those may be SHADOW notes, not ACTIVE skips. v327 reads the STRUCTURED
regime_suppression dict (.mode/.action) + simulates: of currently-NOT-GO, how many would GO at
NORMAL bar (score>=38) if not hard-blocked by an ACTIVE-SKIP. Settles whether the mode fix alone
unlocks GO (suppression shadow) or suppression is the real gate (active).
SHIPPED: diag_v327_mode_unlock_sim.py — paste https://paste.rs/xk3Iw
  sha256 16d4b476e6281ba9c02689e8c54b9fdaad97fc6e65b1733a7f366beaf9a70a96 (round-trip OK).
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v327_mode_unlock_sim.py --hours 8
PENDING operator: run v327 → confirm desired anchor-aware MIXED behavior + risk appetite (thin/neg
sanitized edge caveat) → then build the §2.2 mode_for_direction patcher (shadow not applicable; it's
a mapping change — deploy + watch newly-admitted longs' sanitized avgR ≥0, else rollback).

## ✅ v327 DGX RESULT (2026-06-17) — mode fix is THE lever; suppression is NOT the gate
8h, 623 decisions, 100% cautious. SKIP=511 REDUCE=104 GO=8.
regime_suppression: mode=active ALL 623; action NONE=565, REDUCE=58, **ACTIVE-SKIP=0**.
UNLOCK SIM (if mode=NORMAL bar 38): currently NOT-GO=615 → **WOULD-GO=85** (all 85 now cautious),
would-REDUCE=209, still-blocked-active-skip=**0**, score-too-low=321.
CONCLUSION: v324's "83 regime_suppression" was a misread — suppression has ZERO active SKIPs
(only REDUCEs 58). The cautious GO-bar(50) is the binding gate. The anchor-aware MIXED mode fix
unlocks ~10x GO (8→~85) while active-REDUCE still trims negative-EV cells (safety net intact).

## 🚀 PATCHER BUILT: patch_v328_anchor_aware_mixed_mode.py (v19.34.321) — PENDING operator --apply
Target: backend/services/multi_tf_regime.py mode_for_direction MIXED/UNKNOWN branch.
  SANDBOX PRE_SHA  = ae994e646b85e1eeac8a65a28994d5eec883dd8dc927c61b13753f030f67e1ea
  POST_SHA         = 8954243629a4d4633a0c1a1dcbbcfc54addf8f784e5a73bce142bce79999ebc1
NEW RULE: MIXED + anchor UP → long:normal, short:defensive; MIXED + anchor DOWN → long:defensive,
  short:normal; anchor NEUTRAL/UNKNOWN → both cautious (unchanged). Counter-trend side becomes MORE
  conservative (defensive=GO60) than old blanket cautious(50); with-trend unlocks (normal=GO38).
§2.2 patcher self-tested on isolated copy: --check OK, --apply→POST_SHA exact + compiles,
  --rollback→byte-identical to PRE. Logic unit-tested (10/10 cases incl. unchanged ALIGNED/PULLBACK).
  paste.rs https://paste.rs/1RHPB ; patcher sha f7f3973510fdc6cd618e8b3cc7233ba6a52ffc2491ccf23c834a46ef8424094b.
  Regression test: backend/tests/test_v328_anchor_aware_mixed.py (run post-apply on DGX).
DRIFT NOTE: PRE_SHA is the SANDBOX sha; if DGX multi_tf_regime.py drifted, --check ABORTS →
  operator uploads their copy → rebase. (--check is read-only/safe.)
DEPLOY: --check → (operator go-ahead) → --apply → pytest test_v328 → COMMIT → ./start_backend.sh --force.
POST-DEPLOY VERIFY (MIXED session): diag_v327 (GO should rise 8→~85, mode mix shows 'normal' longs),
  diag_v326 (UP-anchor MIXED days now mode(long)=normal), diag_v321b (newly-admitted LONG avgR ≥0 else rollback).

## ✅✅ v328 / v19.34.321 DEPLOYED & LIVE (2026-06-17 ~11:35 ET)
Operator: --apply → POST_SHA 8954243… exact (backup multi_tf_regime.py.bak_v328) →
pytest test_v328 4 passed → git commit f7729179 + push origin/main →
./start_backend.sh --force → "Application startup complete" (23s), health: mongo green,
ib_gateway green/connected, 0 red. Patch is LIVE. Anchor-aware MIXED mode is active.
PENDING (wall-clock): after ~20-30 min of fresh decisions under the new code, re-run
diag_v327 --hours 1 → expect trading_mode mix to show 'normal' for longs (not 100%
cautious) and GO rising from ~8 toward ~85 on MIXED-context days. Watch newly-admitted
LONG sanitized avgR (diag_v321b) ≥0 next session; if bleeding → --rollback or tighten
regime-suppression EV table. DGX git HEAD now f7729179.

## ✅ v328 LIVE-VERIFIED (2026-06-17, post .bat restart, git pull f7729179)
diag_v327 --hours 1 (179 dec): trading_mode mix now cautious=156, **normal=15, defensive=8**
(was 100% cautious pre-patch) → anchor-aware MIXED mode CONFIRMED WORKING. Counter-trend shorts
correctly benched (defensive). regime_suppression still 0 ACTIVE-SKIP (19 REDUCE) — safety net intact.
BINDING CONSTRAINT SHIFTED: mode no longer the blocker. This 1h: WOULD-GO=8 (vs 85 in prior 8h),
score<25=106, would-REDUCE=64, GO=1. Scores pile below GO line (v323 "scoring starved" resurfacing).
CAVEATS: (1) 1h window too small/low-score to judge true GO unlock — re-measure over --hours 4-6 in a
MIXED-context session. (2) Next lever is SCORE QUALITY (better detectors), NOT lowering the GO threshold
(thin/neg edge → would admit marginal trades).
NEXT FORK: (A) re-measure v327 --hours 4-6 for real GO rate; (B) rubber_band detector redesign (now
unblocked) to lift signal quality; (C) score-composition recal (sector -324 drag, quality_inplay
non-discriminating per v323). Recommend B (detector quality) as the durable lever; defer threshold changes.

## 🎯 ISSUE 2 STARTED (rubber_band redesign, now UNBLOCKED post-v328)
RUNTIME BAR-ACCESS RESOLVED: detectors reach 1-min bars via
  self.technical_service._get_intraday_bars_from_db(sym, "1 min", N)  [SYNC, reads
  ib_historical_data — same IB-only source as training; precedent at enhanced_scanner L4028]
  plus async _get_live_intraday_bars(sym,"1 min") for the freshest forming bar.
CURRENT _check_rubber_band (enhanced_scanner L4360) confirmed broken: fires on a STATE
  (dist_from_ema9<-2.5 + rsi<38 + rvol>=1.5), wrong metric (%-from-EMA9 not from-open),
  NO double-bar-break trigger (the reasoning literally claims one that the code never checks),
  no 2/day cap.
PRE-PATCH VALIDATION (verify-before-claim, respects thin-edge caveat): shipped v329 TRADE-
  outcome replay. Reuses v321c's proven snapback detector (ext-from-open + double-bar-break +
  accel + 2/day cap) and SIMULATES each event: entry=double-bar-break level, stop=LOD-0.02,
  target=9EMA(1m) w/1R floor, walk fwd maxhold bars → realized R by EXTENSION BUCKET (1-2/2-3/
  >=3%) and snapback speed. Picks the ext floor that earns edge BEFORE rewiring FIRE.
  paste https://paste.rs/4TVLB  sha 89b0d51b0b54eb28cd243ff087f1a8b01209167fa9d7674e9b5188dab8127025 (round-trip OK).
  DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v329_rubber_band_trade_replay.py --days 14 --universe 300
DECISION GATE: if a low ext bucket (e.g. 2-3%) shows avgR comfortably >0 → that's the FIRE floor;
  build the _check_rubber_band rewrite patcher (1-min double-bar-break + ext floor + RVOL + 2/day cap).
  If even >=3% is <=0 → snapback-long has no edge this regime → do NOT rewire; revisit geometry/regime first.

## 📚 TQS vs GO/REDUCE/SKIP (answered for operator, 2026-06-17)
They are TWO SEQUENTIAL LAYERS, not one weighted score (AGENTS.md Journey-1 steps 5 then 6):
  - TQS (quality_score 0-100, A+/A/B/C) computed UPSTREAM (scoring_engine/smart_filter/enhanced_scanner);
    gates in smart_filter, then passed as an INPUT to confidence_gate.evaluate(quality_score=...).
  - confidence_gate builds its OWN additive confidence_score (start 0, +layers: meta_labeler ~+11,
    sector ±6, regime, cross_model +5, rs, vae +5, quality_inplay +5, base "other"). TQS contributes
    only a SMALL bounded nudge: +10 (TQS>=80) / +5 (>=60) / 0 (>=40) / -5 (<40)  [confidence_gate L699-710].
  - GO/REDUCE/SKIP = final confidence_score vs MODE threshold (NORMAL go38/red25, CAUTIOUS go50/red35,
    AGGRESSIVE go28, DEFENSIVE go60) PLUS hard vetoes (meta force_skip, active regime-suppression SKIP).
  So GO/REDUCE/SKIP is the OUTPUT of the gate (downstream of TQS); TQS does NOT have the decision weighted
  into it. TQS's influence inside the gate is minor (max +10/-5) — dominant drivers are the model layers,
  the mode threshold, and the hard vetoes.

## ✅✅ v329 DGX RESULT (2026-06-17) — RUBBER_BAND SNAPBACK-LONG IS STRONGLY +EV
14d, univ 300: 1394 events / 898 symbol-days, 1390 tradeable.
OVERALL: win=76%, avgR=+0.268, totR=+371.9R, EV/trade +0.268R. Edge is REAL and large.
BY EXT BUCKET (all positive, flat → edge not ext-sensitive):
  1-2% n=682 win78% +0.286R | 2-3% n=284 win80% +0.239R | >=3% n=424 win72% +0.257R.
BY SNAPBACK SPEED (bars from LOD→trigger): +0bar WEAK (+0.098, 66%); +1..+4 STRONG
  (+0.279/+0.183/+0.602/+0.257); +5 weak (+0.042); +6 +0.596 (n=36 small).
  → exclude +0 (same-bar reversal) and >+4; window +1..+4 weighted avgR ≈ +0.303R (n~1081).
ext dist p25=1.4 p50=2.0 p75=3.5.
DATA-VALIDATED FIRE CONFIG for _check_rubber_band rewrite (LONG):
  ext-from-open >= 1.5% (p25=1.4; keeps high-edge upper-1-2% + all 2-3/>=3; edge +EV even at 1%)
  trigger = first GREEN 1-min bar clearing prior-2 highs, +1..+4 bars AFTER the LOD bar (TRIGGER_WINDOW=4, exclude +0)
  accel: LOD-bar range >= 1.3x median range so far
  RVOL >= 1.5 (keep existing quality gate; not in replay since RVOL not on bar doc)
  2/day cap per (symbol, day)
  entry=double-bar-break level; stop=LOD-0.02; target_1=9EMA(1m); target_2=VWAP.
SHORT SIDE: NOT validated here (replay is long-only); off_sides_short proven no-edge (shorts into
  strength). Do NOT rewire the short side blind — give it its own v329-style replay first.
NEXT: build patch_v330 _check_rubber_band LONG rewrite (1-min bar fetch via
  self.technical_service._get_intraday_bars_from_db(sym,"1 min",N); event-on-latest-bar; 2/day cap).
  Pending operator confirm: ext floor 1.5 vs 1.0, long-only scope.

## ⏭ v330 — SHORT-SIDE REPLAY shipped (operator: ext floor=1.25 for LONG; short replay first, then decide both-vs-long-only)
v330 mirrors v329 for shorts: extension ABOVE open + double-bar-break DOWN (RED bar breaks prior-2 lows);
entry=break-down level, stop=HOD+0.02, target=9EMA(1m) 1R floor. Reports by ext bucket + snapback speed,
compare to v329 long (+0.268R, 76%). paste https://paste.rs/hALOb
  sha 6644c76ab0b213c8b70c499dd4c935e907d32f53251fab294abef879eae7c079 (round-trip OK).
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v330_rubber_band_short_replay.py --days 14 --universe 300
DECISION: short +EV across buckets → build BOTH long(ext>=1.25%)+short into patch_v330; short <=0/weak →
  LONG-ONLY (ext>=1.25%, window +1..+4, accel1.3x, RVOL>=1.5, 2/day cap). LONG floor LOCKED at 1.25% per operator.

## ✅✅ v330 DGX RESULT (2026-06-17) — SHORT SIDE ALSO STRONGLY +EV → BUILD BOTH
14d univ300: 1153 events/795 sym-days, 1146 tradeable. OVERALL win=74%, avgR=+0.587,
totR=+672.4R (mean skewed by big winners; medR=+0.264 → solid +central tendency).
BY EXT: 1-2% n559 +0.281R | 2-3% n256 +1.334R | >=3% n331 +0.526R (all +EV).
BY SPEED: +0bar weak (+0.149), +1..+4 strong (+0.211/+0.329/+1.916/+0.651), +5/+6 +0.34/+0.20.
DECISION: BUILD BOTH sides into the _check_rubber_band rewrite. Symmetric config:
  LONG  ext>=1.25% (operator), SHORT ext>=1.25% (1-2% bucket +0.281R, fine); window +1..+4
  (exclude +0), accel1.3x, RVOL>=1.5, 2/day cap PER SIDE per (symbol,day).
  geometry LONG: entry=2-bar-break-up, stop=LOD-0.02, t1=9EMA, t2=VWAP.
           SHORT: entry=2-bar-break-down, stop=HOD+0.02, t1=9EMA, t2=VWAP.

## 🔧 DRIFT HANDLING for patch_v330 (enhanced_scanner.py)
sandbox enhanced_scanner.py SHA bf5cf446… != recorded DGX b631ebad… → DRIFTED. File 452KB
(> paste.rs ~384KB safe limit) → cannot whole-file round-trip. STRATEGY: anchor patcher on the
operator's EXACT _check_rubber_band bytes via function-level PRE/POST SHA (not whole-file), +
py_compile guard. Shipped _extract_rb_func.py (DGX-safe, no heredoc) to pull the live function:
  paste https://paste.rs/8h1Hv. Operator runs it → returns function-SHA + paste URL of their bytes →
  rebuild patch_v330 anchored on those exact bytes (function-granular PRE/POST sha + compile check +
  --check/--apply/--rollback + backup). Sandbox function span 4360..4480 (121 lines), sandbox func
  sha 1901bcfc… (DGX likely differs — use theirs).

## 🚀 patch_v330 BUILT — rubber_band SMB snapback rewrite (LONG+SHORT), PENDING operator --apply
DGX function == sandbox function (sha 1901bcfc… identical; only file line-positions drift).
Target: enhanced_scanner._check_rubber_band. DGX whole-file PRE = b631ebad524d… (operator-confirmed
via extractor). FUNCTION-anchored patcher (whole-file POST not precomputable for 452KB file): asserts
whole-file==b631ebad + func anchor count==1 + func PRE sha 1901bcfc… + embedded NEW sha 6721b9f8… +
py_compile guard + backup .bak_v330 + --check/--apply/--rollback.
NEW detector: ext>=1.25% from SESSION OPEN + 1-min double-bar-break within +1..+4 bars of extreme +
accel(extreme-bar range>=1.3x median) + RVOL>=1.5 + 2/day cap per (symbol,side). LONG: green clears
prior-2 highs, stop=min(LOD-0.02, support-0.25ATR), t1=9EMA. SHORT: red breaks prior-2 lows, stop=
max(HOD+0.02, resistance+0.25ATR), t1=9EMA. Bars via self.technical_service._get_intraday_bars_from_db
(sym,"1 min",60) [IB-only]. priority CRIT(tape&ext>3)/HIGH(ext>2)/MED.
VALIDATED (sandbox, exec-with-stubs): long fires(HIGH), short fires, RVOL gate blocks, no-double-break
blocks, 2/day cap works. OLD->NEW replace compiles on the real file.
ARTIFACTS: patcher paste https://paste.rs/ydNsP sha 65083ffab9b2e0623f354f097490140a07ce130562d7e348b54d6a0ff95e38b1
  test    paste https://paste.rs/S5i1t sha 2ececc53477f530fbea08dc10ffed96bebdc4aeadeca94b7998bdfe0353bf789
DEPLOY: --check (expect whole-file OK) → --apply → curl test → pytest test_v330 (5 tests) → COMMIT →
  ./start_backend.sh --force. POST-DEPLOY: watch live_alerts for setup_type rubber_band_long/short firing
  on real flushes; track their fire→GO→trade (now mode-unblocked post-v328) + sanitized avgR vs replay
  (+0.27R long / +0.59R short). NEXT: generalize this find→trade-replay→rewrite template to hitchhiker,
  second_chance, big_dog.

## ✅ patch_v330 APPLIED & LIVE (2026-06-17, commit 19dde7f5) — detector rewrite deployed
--check whole-file OK (b631ebad) → --apply → POST whole-file SHA bc674f2688e9983edc3e7cad385a3463fe04d75ebc8dd927975154018b4b37cf
(backup .bak_v330). Committed 19dde7f5 + pushed. Live detector compiles & is the new SMB snapback.
TEST BUG (test-only, NOT runtime): test_v330 imported wrong class name `EnhancedScanner`; real class is
`EnhancedBackgroundScanner` (enhanced_scanner.py L817). Fixed import + hardened _run to use a fresh
asyncio loop (py3.12). Corrected test paste https://paste.rs/tI6b2
  sha 9465d8861f9772e5fede10f243b932215555c06a0edfa3f65fae82247cd77b2b. Operator to pull + pytest (5) + re-commit.
DETECTOR VALIDATION stands (exec-with-stubs earlier: long/short fire, RVOL gate, no-break, 2/day cap).
NEW DGX whole-file baseline for enhanced_scanner.py = bc674f26… (use for any future patcher PRE_SHA).

## ✅✅ patch_v330 COMPLETE & LIVE-VERIFIED (2026-06-17, commit 07e52bc7)
test_v330 fixed (EnhancedBackgroundScanner) → pytest 5 passed → committed 07e52bc7 + push →
./start_backend.sh --force "Application startup complete", health 0 red, ib_gateway connected.
LIVE FIRE confirmed: live_alerts last 3h rubber_band_long=2 (short=0, market-dependent). New
event-based SMB snapback detector is emitting. enhanced_scanner.py DGX baseline now bc674f26… (from
v330) — note: commit 07e52bc7 only touched the test, so live enhanced_scanner.py == bc674f26 (v330 applied).
ISSUE 2 (rubber_band) CLOSED. NEXT: generalize find→trade-replay→rewrite template to hitchhiker,
second_chance, big_dog (P1). Also watch rubber_band fire→GO→trade flow + sanitized avgR vs replay
(+0.27R long / +0.59R short) over next sessions.

## 🗂 v331 — SETUP CATEGORY/STYLE/TEMPLATE AUDIT (shipped) + TIME-DECAY AUDIT (2026-06-17)
SSOT confirmed: smb_integration.SETUP_REGISTRY holds horizon default_style (scalp/intraday/multi_day/
swing/investment/position); setup_taxonomy.style_of/setup_class/strategy_family resolve behavior.
KEY (sandbox smoke): rubber_band=scalp/fade/reversion (DONE); bella_fade,off_sides=scalp/fade;
big_dog=INTRADAY/momentum/breakout; hitchhiker,second_chance=scalp/MOMENTUM/continuation.
=> REWRITE SWEEP NEEDS 2 TEMPLATES: FADE scalps reuse v329/v330 snapback; MOMENTUM scalps
(hitchhiker/second_chance/spencer/9_ema/abc/fashionably_late/gap_give_go) need a CONTINUATION replay
(entry on consolidation-break, stop below pullback low, target=measured-move/trail). big_dog is intraday.
v331 diag dumps reg_style vs ssot_style vs class/family + fires/trades + flags STYLE mismatches +
FIND-NO-TRADE + the scalp fade/momentum split. paste https://paste.rs/ (see PASTE_URL above).
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v331_setup_category_audit.py --days 30

TIME-DECAY AUDIT FINDINGS (read-only grep, services/):
- SCALP: SCALP_DECAY_MINUTES (default 60) staleness decay in opportunity_evaluator (v19.34.171 sweep). ✓
- INTRADAY: time-to-close decay (opportunity_evaluator ~L3056). ✓
- order_policy_registry per-style: scalp/intraday close_at_eod=True (DAY TIF); swing/position/investment
  GTC, close_at_eod=False, trail-on-20EMA, EOD-sweep-exempt.
- MULTI_DAY / SWING / INVESTMENT / POSITION: NO max_hold / max_days / time_stop / time_decay field anywhere.
  They exit ONLY on trail/target/stop → a dead-money higher-tier trade can be held indefinitely. GAP CONFIRMED.
RECOMMENDATION (pending operator appetite): add a per-tier TIME-STOP / max-hold review (e.g. swing: exit if
not >=+1R by N trading days; position: periodic thesis review / hard max-hold). Build a read-only "stale
higher-tier holds" diag first to size the problem, then propose env-flagged time-stops in order_policy_registry.

## ✅ v331 DGX RESULT (2026-06-17) — taxonomy clean; sweep mapped; anomalies found
STYLE MISMATCHES: NONE (registry default_style == SSOT style_of for every registered setup). Taxonomy consistent.
REGISTRY GAPS (reg_style "—", not in SETUP_REGISTRY but resolve via SSOT fallback; real+traded ones):
  accumulation_entry(swing,5011f/1327t), daily_breakout(multi_day,2320/309), daily_squeeze(multi_day,9418/276),
  trend_continuation(multi_day,5297/28), bouncy_ball(intraday,598/15), vwap_continuation(intraday,171/42),
  premarket_high_break, the_3_30_trade, gap_fill_open, day_2_continuation, base_breakout. (artifacts: reconciled_*,
  approaching_*, carry_forward_watch = pseudo-setups, should be edge-excluded). → optional registry-completeness cleanup.
SCALP SWEEP MAP (operator: generalize to all scalps):
  FADE (snapback template v329/v330, 11 to do; rubber_band DONE): backside, bella_fade, fading_bounce,
    first_move_down, first_move_up, gap_fade, mean_reversion, off_sides, time_of_day_fade, volume_capitulation, vwap_fade.
  MOMENTUM (need NEW continuation replay template, 9): 9_ema_scalp, abc_scalp, fashionably_late, gap_give_go,
    gap_pick_roll, hitchhiker, puppy_dog, second_chance, spencer_scalp.
  Volume priority — fade: vwap_fade(4982/102), gap_fade(3624/165), off_sides(3830/9=correct short suppression),
    mean_reversion(2680/88), backside(487/17). momentum: fashionably_late(1073/34), gap_give_go(818/29), second_chance(624/9).
FIND-NO-TRADE anomalies (fires>=20, 0 trades): breakdown 2470/0 (BIGGEST — triage; intraday/swing/reversal short),
  tidal_wave 335/0 (new m8 momentum detector never trades), fading_bounce 90/0 (short fade, likely suppressed),
  + swing/position/investment breakouts (vcp_breakout 568, ascending/descending_triangle, base_breakout, weekly_breakout,
  stage_1_to_2, fifty_two_week_high, two_hundred_day_*, death/golden_cross) all fire but 0 trades → likely higher tiers
  not executed by the bot OR blocked; CONFIRM whether intentional (ties into time-decay/tier-execution question).

## ⚠️ v331 DATA CAVEAT (operator flagged 2026-06-17) — re-run on SANITIZED data
v331 counted RAW bot_trades → contaminated by (a) hygiene ARTIFACTS (phantom/sweep/reconcile/
instant-unwind<120s/corrupt-PnL) and (b) ADOPTED/external positions (reconciled/IB-imported/orphan;
30d audit: 46% of closes adopted, +$181k, while bot's own edge ~breakeven). SSOT =
services/trade_outcome_hygiene.classify_close()+is_adopted_entry(). e.g. accumulation_entry "1327 trades"
was ~94% artifacts per hygiene docstring; reconciled_orphan(89)/reconciled_excess_slice(29) are pure artifacts.
=> v331's trade/FIND-NO-TRADE numbers are NOT trustworthy. STYLE-mismatch (none) + scalp FADE/MOMENTUM
split ARE trustworthy (taxonomy-only, data-independent).
SHIPPED v331b: applies classify_close + is_adopted_entry, counts GENUINE_OWN only, reports artifact/adopted
contamination + corrected FIND-NO-TRADE + field-coverage sanity + edge-excluded filtering.
  paste https://paste.rs/2pZ3Q sha 61be186a5f0df658252e42306f6f5bedbdb063cae8510e2a3e5b1fa6f9f42a28
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v331b_setup_audit_sanitized.py --days 30
PENDING: operator runs v331b → re-assess FIND-NO-TRADE (esp breakdown 2470/0, higher-tier breakouts) and
real per-setup trade yields on clean data, THEN decide sweep order + time-stop appetite. Time-decay code
findings (no max-hold/time-stop on multi_day/swing/position/investment) stand regardless.

## ✅ v331b SANITIZED RESULT (2026-06-17) — clean per-setup truth
4030 bot_trades/30d: 89% GENUINE bot-own, 4% artifact, 5% adopted (May phantom crisis is OUTSIDE 30d
window → less polluted than feared, but per-setup now trustworthy). Field coverage ok (exit_price 15% →
external-bracket reclass mostly inactive = conservative).
TIERS DO TRADE (genuine_own): swing pocket_pivot 168, three_week_tight 57; position stage_2_breakout 92;
investment rs_leader_break 399, power_trend_stack 89; multi_day daily_breakout 298, daily_squeeze 262,
accumulation_entry 1261, trend_continuation 20; intraday squeeze 275, orb 76, opening_drive 70, breakout 34.
=> TIME-DECAY GAP IS A REAL LIVE RISK (these active swing/position/investment trades have NO max-hold/time-stop).
CONFIRMED FIND-NO-TRADE (clean, 0 genuine): breakdown 2470/0 (BIGGEST anomaly), tidal_wave 334/0,
fading_bounce 90/0, vcp_breakout 568/0, descending_triangle 225/0, ascending_triangle 120/0,
weekly_breakout 213/0, base_breakout 63/0, day_2_continuation 102/0, death_cross_filtered 178/0,
golden_cross_filtered 126/0, two_hundred_day_loss 99/0, two_hundred_day_reclaim 23/0, stage_1_to_2 57/0,
fifty_two_week_high 38/0. NOTE: some peers in same tiers DO trade (pocket_pivot/stage_2/rs_leader) → it's
SPECIFIC broken/blocked detectors, NOT a blanket tier-execution gap.
SCALP SWEEP genuine conversion — FADE: gap_fade 3627f/154g, vwap_fade 4982/73, mean_reversion 2680/73,
backside 487/15, volume_capitulation 21/14, off_sides 3830/7(short-suppressed), bella_fade 8/0(ALL-CONTAMINATED),
first_move_down 12/1, fading_bounce 90/0, first_move_up/time_of_day_fade 0/0.
MOMENTUM: fashionably_late 1074/30, gap_give_go 818/29, second_chance 625/7, gap_pick_roll 87/3, hitchhiker 2/4,
puppy_dog 26/1, 9_ema/abc/spencer 0g.

## 📏 v332 — STALENESS / TIME-DECAY SIZING (shipped, operator: "measure staleness first")
Open positions live in bot_trades status open/filled/pending; created_at=entry, closed_at=exit,
risk_amount→R=realized_pnl/risk_amount. v332 (genuine bot-own via classify_close+is_adopted_entry):
  PART A closed trades per TIER x HOLD-BUCKET(<1/1-2/3-5/6-10/>10d): n/win%/avgR/medR/totR → find the
    hold-day boundary where win%/avgR craters = time-stop candidate per tier.
  PART B currently OPEN holds per tier: count + age p50/max + count over heuristic STALE_DAYS
    (intraday>1, multi_day>5, swing>15, position>40, investment>90) + top stale symbols → live dead-money size.
  paste https://paste.rs/ (PASTE_URL above) sha (see cmd output).
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v332_staleness_sizing.py --days 120
PENDING: operator runs v332 → read hold-time decay per tier + open stale holds → set per-tier time-stop
thresholds → then env-flagged time-stop patch in order_policy_registry. (Window 120d for enough higher-tier closes.)

## 🚨 v332 RESULT (2026-06-17) — TIME-DECAY NOT THE ISSUE; trade_2_hold -878R bleed found
TIME-DECAY: NOT warranted. All tiers resolve fast (hold p50 ≤0.2d); Part B 0 stale open holds (max age 2.1d).
Do NOT build time-stops — data refutes the dead-money hypothesis. (Measuring first paid off.)
DOMINANT FINDING: trade_style 'trade_2_hold' = 528/586 genuine bot-own closes, win 34%, avgR -1.66,
totR -878.8R, BUT medR only -0.05 → fat LEFT TAIL. trade_2_hold = LEGACY DEFAULT/fallback style (set when
classifier assigns none: enhanced_scanner L8928, opportunity_evaluator L1737; maps to INTRADAY/DAY-TIF).
=> TWO issues: (1) trade_style classifier mostly NOT assigning real styles → everything defaults to trade_2_hold;
(2) that bucket has a catastrophic R tail. Other tiers tiny n (~breakeven). scalp 5/+0.09 fine.
SHIPPED v333 forensic to decide REAL blown-stops (P0 risk bug) vs CORRUPT risk_amount (R artifact):
dissects $ pnl, risk_amount health, winsorized vs raw R, loss-by-close_reason, setup mix, worst-12 verbatim.
  paste https://paste.rs/qJKkg sha 572615653ca87df5b5c38a37bd60158a19e24d95c1eb554ec809e787f9f63af5
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v333_trade2hold_forensic.py --days 120
PENDING: operator runs v333 → if worst trades show exit far beyond stop w/ big $ → stops not honored (P0 fix);
if tiny-risk rows inflate R → R-artifact (fix risk_amount/exclude from edge stats). Either way revisit the
trade_style classifier default. breakdown 2470/0 triage + FADE-scalp sweep still queued.

## ✅ v333 RESULT (2026-06-17) — "-878R" is a METRIC ARTIFACT; real risk = blown stops on shorts
trade_2_hold DOLLAR P&L = NET +$56,940 (mean +$108, median -$6.3, win 34%, best +$49,590, worst -$6,426).
winsor avgR -0.27 (raw -1.66) → -878R is risk_amount artifact. 8 tiny-risk(<$5) rows = -447R alone.
risk_amount = PLANNED risk → when a stop is BLOWN, realized loss >> planned → R explodes.
REAL FAILURES (worst-12): WTI short stop2.86→exit3.21 -$6426; USO short 108.31→116.12 -$3614 (held 1434m!).
Others R≈-1.0 honored fine. SHORT-FADE bleed: vwap_fade_short -$25.4k(52t), off_sides_short -$10.6k(13t),
rubber_band_short -$1.4k. close_reason stop_loss=-$63.8k(108t) but offset by +$49.6k winner → net +.
CONCLUSIONS: (1) NOT a -878R edge bleed — good. (2) P0 RISK: stops not honored on some shorts (exit far
beyond stop); single -$6.4k tail. (3) Concentrated bleed = SHORT fades (shorting strength). (4) METRIC: R uses
planned risk → winsorize/realized-risk in edge/EV so meta-labeler isn't poisoned by -261R outliers.
SHIPPED v334 stop-overrun forensic: direction-aware overrun (exit beyond stop), honored vs BLOWN R-profile,
EXCESS-$ beyond stop by dir/setup, worst-12 overshoots. paste https://paste.rs/ (see PASTE_URL)
DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v334_stop_overrun_forensic.py --days 120
PENDING: operator runs v334 → sizes systemic stop-blowing. If blown% high/concentrated in shorts → P0 fix
(hard stop orders + short eligibility min price/liquidity). breakdown 2470/0 + FADE sweep still queued.

## 🚀 v337 + v338 — TWO P0 READ-ONLY DIAGS SHIPPED (2026-06-18, post-v336)
Both round-trip verified (cmp == local). No drift risk (NEW files, read-only; not patchers).

### v337 — breakdown FIND-NO-TRADE triage (2470 fires / 0 genuine trades)
Buckets setup_type LIKE 'breakdown%' across the WHOLE pipeline: alerts (live_alerts/alerts/
live_scanner_alerts/predictive_alerts) → confidence_gate_log (GO/REDUCE/SKIP + top SKIP reasons)
→ trade_drops (which gate killed it) → rejection_events → bot_trades (status/entered_by/genuine).
Tells real BLOCK-BUG from correct suppression.
  paste https://paste.rs/2kUMh  sha 55ac6724e48ab84ab61e37ed84d9e8c8cb15cc21a6bb0ecdf091c57db1f4dc28
  DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v337_breakdown_triage.py --days 30
  READING: alerts-high+SKIP-dominant→gate kills it; GO-but-trade_drops→post-gate BLOCK BUG;
  no-gate-rows+no-drops→never reaches gate (experimental/learning-only/dispatch-filtered).

### v338 — Part A EOD-flatten ENFORCEMENT audit (overnight-leak surface)
On GENUINE bot-own closed trades (classify_close + is_adopted_entry), flags OVERNIGHT holds
(entry ET-date != exit ET-date) and cross-references the AUTHORITATIVE policy
order_policy_registry.should_close_at_eod(trade) (v19.34.245 path; resolves trade_2_hold via the
canonical classifier). THE LEAK SURFACE = should_close_at_eod==True BUT held overnight → slipped
past Journey-3 EOD. Buckets leak by setup_type/trade_style/direction/close_reason + canonical
resolve_trade_style of leak rows (Issue-3 entanglement check: does v245 already cover trade_2_hold
or do they re-resolve to a HOLD style?). Pinpoints exactly which trades evade EOD BEFORE we touch
the safety-critical EOD path.
  paste https://paste.rs/yqjwG  sha a9636fbfccb69e8a1a92d5894b69034fbb3995d6f027a9eec6e97d435dd8183a
  DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v338_eod_flatten_audit.py --days 120
  READING: leak>0 + dominated by trade_2_hold + canonical-resolve still intraday/scalp → Issue-3
  default IS the cause AND v245 should have flattened → trace WHY check_eod_close skipped them.
  leak canonical-resolve = multi_day/swing → NOT leaks (stored style stale, correctly held).
PENDING: operator runs BOTH → paste output → decide breakdown real-bug-vs-suppression + size the
EOD leak before patching Journey-3. FADE+MOMENTUM scalp sweep queued after.

## ✅✅ v337/v338/v339 DGX RESULTS (2026-06-18) — BOTH P0s RESOLVED (no patch warranted)
DGX HEAD at run: 9ae11efc (v19.34.323).

### P0-1 breakdown 2470/0 = CORRECT SUPPRESSION (not a bug) — CLOSED
v337: live_alerts 2470 breakdown; confidence_gate_log 0; trade_drops 8322 (setup_disabled 7803 +
universal_liquidity_gate 519); bot_trades 0. `breakdown` is NOT in trading_bot_service._enabled_setups
→ every alert dies at the setup_disabled gate BEFORE the confidence gate. No execution bug. ENABLING it
is an EDGE-VALIDATION decision (replay-first, per off_sides_short/v336 short-caution), NOT a fix.
Only residual cost = wasted alert-gen overhead (P3: stop the disabled detector emitting).

### P0-2 Part A EOD-flatten = HISTORICAL residue, live path HEALTHY — STAND DOWN (no EOD patch)
v338: 590 genuine closed/120d, 41 overnight; LEAK surface (should_close_at_eod=True yet held overnight)=32,
31/32 trade_2_hold, ALL re-resolve canonical→intraday(21)/scalp(11). v339 TIMELINE settled live-vs-historical:
  entry months: Mar 23, Apr 6, May 2, Jun 1. ALL 14 dangerous stop_loss overnight-rides (WTI/USO/KRG/BP)
  entered Mar 11 or Apr 30 — BEFORE the EOD-policy stack (v245 ~6/2, v261 ~6/3, v301 ~6/8, v322s ~6/12).
  Post-stack overnight leaks = ONLY safety-net catches: May 5 zombie_cleanup, Jun 12 DKNG missed_eod_boot_flatten
  (v322s firing as designed). ZERO silent gap-stop rides after 6/2.
CONCLUSION (HIGH conf): v245/v261/v301/v322s already seal the live EOD gap; v336 blocks the dangerous
short-fade re-entry profile. Patching safety-critical Journey-3 = net-negative risk → DO NOT PATCH.
Residual P1 (analytics, not safety): trade_2_hold legacy DEFAULT style still stamped at entry — EOD now
resolves it correctly via canonical classifier, but the stored style pollutes EV/meta-labeler. Optional
entry-path fix to stamp a real resolved style (defer; ask operator).
Diags: v337 paste 2kUMh, v338 paste yqjwG, v339 paste dnzt7 (all round-trip OK).

## 🧭 FADE SWEEP STARTED — vwap_fade replay (v340), template = v329/v330 generalized to VWAP anchor
Operator ask: "evaluate every remaining scalp/intraday trade — find/calc/trade properly vs cheat sheets."
Sweep order (v331 map, by volume): FADE: vwap_fade(4982f/73g) → gap_fade(3627/154) → mean_reversion(2680/73)
→ backside(487/15). MOMENTUM (needs new continuation template): fashionably_late, gap_give_go, second_chance...
v340 = vwap_fade TRADE-OUTCOME REPLAY (READ-ONLY), generalizes v329 snapback from ext-from-OPEN to
ext-from-VWAP (the real vwap_fade thesis). BOTH sides (short=fade strength above VWAP = v336 danger profile,
measured honestly; long=fade weakness below VWAP). entry=2-bar-break, stop=extreme±0.02, target=VWAP(1R floor),
accel1.3x, 2/day cap, by ext-bucket + snapback-speed. Compare to rubber_band v329 +0.27R/v330 +0.59R.
  paste https://paste.rs/agW6R  sha 0183d003c9f1b53620d5dc88db0c50c3423c31b4dc0dfb5020f920a29c0a684e
  DGX cmd: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v340_vwap_fade_replay.py --days 14 --ext 1.0 --universe 300 --side both
DECISION GATE: lowest ext bucket with avgR comfortably >0 = FIRE floor for that side; if SHORT <=0 across
buckets → confirms no-edge-shorting-strength → keep short suppressed. THEN build patch_v341 _check_vwap_fade
rewrite (VWAP-anchored snapback) for the +EV side(s) only.
