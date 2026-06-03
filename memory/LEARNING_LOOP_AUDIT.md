# Learning / Feedback-Loop Audit — v19.34.248 (2026-06-03)

Read-only deep audit of how SentCom learns from its own trades. Pairs with
the diagnostic `backend/scripts/diag_learning_loop_audit_v19_34_248.py`
(run on DGX for live ground-truth).

---

## 1. How the loop is SUPPOSED to work (3-speed architecture)

```
Scanner alert ─► capture_alert_context()           [FAST] context stored in _pending_contexts
   │
Trade fires ──► start_execution_tracking()         [FAST] execution_tracker
   │
Trade CLOSES (close_trade) ─┬─► record_trade_outcome() ──► trade_outcomes ──► learning_stats
   │                        │        └─► confidence_gate.record_trade_outcome() ──► confidence_gate_log
   │                        │        └─► _update_tilt_state() ──► trader_profile (tilt/consecutive losses)
   │                        ├─► _record_alert_outcome_bestEffort() ──► alert_outcomes ──► strategy_stats
   │                        │                                          (the TQS *setup* pillar EV feed, v216)
   │                        ├─► _perf_service.record_trade()
   │                        └─► _log_trade_to_regime_performance() ──► regime_performance
   │
EOD 16:00 ──► run_daily_analysis()                 [MEDIUM] aggregates today's trade_outcomes,
   │                                                         updates learning_stats, edge-decay,
   │                                                         calibration recommendations
EOD 17:30 ──► rebuild_learning_stats_from_all_outcomes() [MEDIUM] full idempotent rebuild (v200)
Fri 16:30 ──► weekly_report                        [SLOW] weekly_intelligence_reports
Every 5m  ──► shadow_update                         shadow_decisions outcomes
```

### Who reads the learned data
- **TQS *setup* pillar** → `strategy_stats` (EV-R + real win-rate, base_setup keyed). v216.
- **TQS *execution* pillar** → reads `trade_outcomes` DIRECTLY via pymongo (v217-219),
  because `learning_loop.get_recent_outcomes()` returns EMPTY in the TQS-engine
  context (deferred init).
- **get_contextual_win_rate** → `learning_stats`.
- **Phase-D gameplan edge ranker** → `trade_outcomes` bucketed by setup+catalyst+gap+regime.
- **confidence gate** → `confidence_gate_log` (calibrates allow/block thresholds).
- **medium_learning/** (calibration, context_performance, confirmation_validator,
  playbook_performance, edge_decay) + **ev_tracking** (separate EV store).

---

## 2. THREE parallel outcome/EV stores (fragmentation risk)

| Store | Writer | Keying | Consumed by |
|---|---|---|---|
| `trade_outcomes` + `learning_stats` | `record_trade_outcome` (create_task from close_trade) | bot_trade_id / context_key(base_setup) | execution pillar, get_contextual_win_rate, edge ranker |
| `alert_outcomes` + `strategy_stats` | `_record_alert_outcome_bestEffort` (close_trade) | trade_id / base_setup | **TQS setup pillar EV** |
| `ev_tracking` | `EVTrackingService.record_trade_outcome` | setup_type | EV dashboard / ideas |

These can disagree on the SAME trades (different formulas, different keying,
different write paths). Section 4 of the audit recomputes win_rate/EV from
`trade_outcomes` and diffs vs `strategy_stats`/`learning_stats`.

---

## 3. Code-level gaps found (before live data)

1. **🔴 HIGH — operator-close leak.** `close_trade_custom` (the operator manual-close
   / v196 force-flatten path) does NOT call `record_trade_outcome`,
   `_record_alert_outcome_bestEffort`, or `_perf_service.record_trade`. ALL of those
   writes live only inside `close_trade`. → every operator-initiated close is invisible
   to all three EV stores AND the tilt/profile. (Audit §2 quantifies it.)
2. **🟠 MED — Phase-D fields dropped at the source.** The `record_trade_outcome` call in
   `close_trade` (position_manager.py ~3306) omits `catalyst_tag` and `gap_pct` (added to
   the model in v233), so they default to `""`/`0.0`. The Phase-D edge ranker buckets by
   catalyst+gap → those buckets are effectively blank. (Audit §3 measures populate-%.)
3. **🟠 MED — fire-and-forget silent failures.** `record_trade_outcome` is launched via
   `asyncio.create_task(...)` with no await/error sink. If the coroutine throws (bad
   field, context recapture, etc.) the outcome is silently lost — no log, no retry.
4. **🟠 MED — entry/target approximations.** `entry_price=trade.fill_price` and
   `target_price=trade.target_prices[0] or fill*1.02`; for scaled/partially-filled trades
   the stored `actual_r` may not match a price recompute. (Audit §5 spot-checks.)
5. **🟡 watch — `created_at` window semantics.** `run_daily_analysis` filters
   `created_at >= today_start AND reviewed:False`; EOD close now fires 15:45 and analysis
   runs 16:00, so same-day closes are caught — but anything that closes after 16:00
   (late retries, overnight swing exits) is only swept by the 17:30 full rebuild, not the
   incremental path.

---

## 4. What the live audit (§ in the script) reports
1. Sink inventory & freshness (count + latest-age per collection).
2. Close-path coverage — closed bot_trades vs trade_outcomes / alert_outcomes (the leak %).
3. trade_outcomes field completeness (catalyst/gap/regime/time/actual_r/execution).
4. Cross-system EV consistency (recomputed vs strategy_stats vs learning_stats).
5. actual_r accuracy spot-check (recompute from prices).
6. Shadow vs Real win-% divergence (ties to the 18-pt-gap investigation).
7. Scheduler liveness (is each nightly/weekly job actually writing?).
8. Prioritized gap summary.

Run: `.venv/bin/python backend/scripts/diag_learning_loop_audit_v19_34_248.py --days 14`

---

## 6. VERIFICATION PASS (v248b, 2026-06-03) — confirmed-real vs audit artifacts

After the first live run, every finding was re-checked against the actual code +
schemas. Result: **4 findings were audit artifacts** (wrong field/collection names in
the v248 script), **4 are confirmed real**.

### ✅ CONFIRMED REAL (verified in code, not just the audit)
1. **Coverage leak (trade_outcomes ~18%).** The OCA-external sweep
   (`position_manager.py` ~357-378) sets `status/close_reason/realized_pnl` inline and
   calls `_persist_trade` — it does NOT call `apply_close_pnl`, `record_trade_outcome`,
   or the regime log. `record_trade_outcome` lives ONLY in `close_trade` (L3306). No
   script backfills `bot_trades → trade_outcomes` (`backfill_learning_stats.py` only
   rebuilds `learning_stats` FROM `trade_outcomes`). → 186 OCA-external + EOD/reconciler
   closes never reach `trade_outcomes`.
2. **trade_outcomes (18%) < alert_outcomes (28%) — explained precisely.** `alert_outcomes`
   has a 2nd feeder: `apply_close_pnl` → `_record_alert_outcome_bestEffort` (v124), called
   from EOD (`position_manager:2876`) + reconciler paths. `trade_outcomes` has no such
   secondary feeder. The OCA-external sweep bypasses BOTH.
3. **strategy_stats EV is structurally inconsistent.** `win_rate = alerts_won /
   alerts_triggered` uses MONOTONIC all-time counters, but `EV = wr*avg_win_r −
   (1−wr)*avg_loss_r` draws `avg_win_r/avg_loss_r` from a LAST-100-capped `r_outcomes`
   series — mismatched denominators + a different R-series/sample than `trade_outcomes`'
   realized `actual_r`. This is why accumulation_entry shows +0.62R (SS) vs −0.43R
   (realized) and daily_breakout +2.61R vs −1.00R. Real, and it directly misleads the TQS
   setup pillar.
4. **catalyst_tag / gap_pct 100% empty** — `close_trade`'s `record_trade_outcome` call
   omits them.

### ❌ AUDIT ARTIFACTS (v248 script bugs — NOT real problems)
- **shadow executed=0**: real fields are `was_executed` / `outcome_tracked` /
  `actual_outcome` / `would_have_pnl` / `would_have_r` (v248 queried executed/outcome/
  would_pnl → all None). Re-checked in v248b.
- **calibration_log empty "never runs"**: calibration persists to **`calibration_history`**
  (n=132, rich: parameter/recommended_value/applied/impact_after_applied) +
  `calibration_config`. It IS running.
- **regime_performance stale/low**: it's an AGGREGATE (per strategy×regime); per-trade is
  `regime_trade_log`; ts field differs.
- **setup_grade_records / weekly "last —"**: wrong ts field — they use `computed_at` /
  `generated_at`.

### Still to confirm on live data (v248b run)
shadow `outcome_tracked` %, calibration_history freshness, regime_trade_log per-trade
count, the EV-decomp numbers, and the keying-artifact guard proving the 18% is a true
leak (not an ID-format mismatch).

Verification script: `backend/scripts/diag_learning_loop_audit_v19_34_248b.py`

