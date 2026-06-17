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
