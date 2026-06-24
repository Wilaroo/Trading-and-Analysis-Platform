# v407 — orphan CREATION-CAUSE taxonomy (read-only) — 2026-06-24

## Why
MFE/MAE repair (v406) is applied on the DGX (29/29 corrupt rows healed). Operator
directive: stop band-aiding orphan stops — **prevent orphans at the source**
("stitch the cut so it heals fully"). v404/v405 measured the $ leak and built the
reaped-pending relink (observe). This step answers the upstream question — *why
are orphans created at all?* — by classifying every closed `reconciled_orphan` by
HOW it lost tracking, so each path can be sealed in code.

## What shipped (additive, read-only)
- NEW `services/orphan_taxonomy.py` — `generate_report(db, days=120,
  near_window_min=240, foreign_lookback_days=30)`. Reuses orphan_leak_rca helpers
  (`_clean_r/_entry_ts/_close_ts/ARTIFACT_SETUPS`). Writes NOTHING.
- NEW endpoint `GET /api/slow-learning/orphan-taxonomy/report`.
- Tests `tests/test_orphan_taxonomy.py` (8) — one per class + population/verdict +
  empty-db. Green. Endpoint 200 on preview (n=0; no orphan data off-DGX).

## Creation-cause classes (priority order, first match wins)
1. **reaped_pending_filled** — `synthetic_source=relinked_reaped_pending` /
   `entry_context.relinked_from_reaped_pending`, OR a `stale_pending_*`
   predecessor on (sym,dir) closed ≤near_window before the orphan (qty 0.4–2.5×).
   FIX: pending-fill attribution + reaper pusher-fallback; v405 relink seals it.
2. **exit_overfill_residual** — a normal-exit predecessor (target_/oca_closed/
   eod_auto/trailing/scale/stop_loss/phantom) on the symbol closed ≤near_window
   before, with orphan qty a residual fraction (ratio ≤0.75) of the closed size.
   FIX: close/scale-out fill verification + residual sweep.
3. **share_drift_excess** — `synthetic_source=share_drift_excess` OR a
   concurrently-OPEN non-artifact trade overlapped the orphan (bot already
   tracked the symbol). FIX: share-drift reconciler GROWS the slice, never spawns.
4. **restart_orphan** — `auto_reconcile_at_boot` event ≤10m before the orphan
   (best-effort; sentcom_thoughts is TTL-7d so only recent ones resolve).
   FIX: durable open-trade hydration on boot (rehydrate, don't re-adopt).
5. **true_foreign** — no predecessor on (sym,dir) within foreign_lookback_days.
   FIX: flatten, don't adopt.
6. **unclassified** — predecessor exists but matched no class (manual review).

## Report shape
`population` (n / total_leak_r / total_leak_usd / mean_r) · `taxonomy[]`
(per class: n, pct, leak_r, leak_usd, n_losers, mean_r, markers, **fix_site**,
samples w/ evidence) sorted worst-leak-first · `monthly_by_class` (tapering vs
live) · `relink_coverage` (reaped_pending orphans, already_relinked_fix,
would_relink_observe_marker, + state_integrity_events counts for
`orphan_relink_observe`/`orphan_relinked_reaped_pending`) · `verdict`.

## RUN ON DGX (read-only)
```
curl -s "http://localhost:8001/api/slow-learning/orphan-taxonomy/report?days=120" | python3 -m json.tool
```
Relink observe-mode check (answers "did observe fire?"):
```
curl -s "http://localhost:8001/api/slow-learning/orphan-taxonomy/report?days=120" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['report']['relink_coverage'])"
```

## NEXT
Operator pastes the report → I patch the dominant class's `fix_site` first
(env-gated observe→fix, zero touch to order/close/kill-switch). Then pivot to
the system-wide ENTRY-quality problem (−0.306R/trade) per "do A then B".

---

## v407.1 (same day) — first DGX run + refinement

**First DGX run (120 closed orphans, −19.73R / −$5,714):** the R-ranking was
distorted by tiny-risk residuals (`exit_overfill_residual` showed −13.9R but only
−$229 — 19-share residuals with microscopic risk_amount inflate R). 47% of the
DOLLARS sat in an opaque `unclassified` bucket (−$2,674). `relink_coverage` showed
`orphan_relink_observe=0` — expected: all 8 reaped_pending orphans predate the
v405 deploy.

**By dollars (first run):** unclassified −$2,674 (47%) · true_foreign −$1,872
(33%) · reaped_pending_filled −$603 · share_drift_excess −$336 · exit_overfill
−$229. `share_drift_excess` was the biggest by COUNT (44, 36.7%) — the reconciler
spawns a separate orphan while a real trade on the same symbol is open (the
v19.34.22 db_tracked guard has a gap).

**Refinement shipped:**
- NEW class `readopt_loop` — a full-size position closed externally (OCA/phantom/
  emergency-flatten) then RE-ADOPTED at full qty. Splits the bulk of the old
  `unclassified` $ out into an actionable class. Detector: external-marker
  predecessor (real trade OR prior orphan) within `readopt_window_min` (480) with
  qty ratio >0.75.
- `reaped_pending` window widened: separate `stale_window_min` (1440) so a
  stale_pending predecessor beyond the 240m near-window still classifies
  (GLD/BE/GLW/SNOW were mislabeled unclassified on run 1).
- `taxonomy_by_usd` + `taxonomy_by_r` both returned; `tiny_risk_r_inflated` flag
  per class so the ranking can't be misread; verdict now ranks by $.
- `share_drift_excess` evidence tags `concurrent_dir` (same/opp).
Tests now 9 (added readopt_loop). New endpoint params: `stale_window_min`,
`readopt_window_min`.

