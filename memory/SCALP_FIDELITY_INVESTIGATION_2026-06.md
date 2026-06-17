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
