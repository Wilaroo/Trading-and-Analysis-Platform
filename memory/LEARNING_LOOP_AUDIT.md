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

## 5. Candidate fixes (pending live numbers to prioritize)
- F1: route `close_trade_custom` outcomes into the same 3 sinks (shared helper, not a
  fork of the safety-critical close). **High value if §2 shows a real leak.**
- F2: pass `catalyst_tag`/`gap_pct` (+ entry context) from the trade into
  `record_trade_outcome`.
- F3: wrap the create_task body in a guarded coroutine that logs + writes a
  `learning_write_failures` breadcrumb on exception.
- F4: converge the 3 EV stores (or make one canonical + others derived) to kill divergence.
- F5: weighted-avg entry + realized R from fills for accurate actual_r.
