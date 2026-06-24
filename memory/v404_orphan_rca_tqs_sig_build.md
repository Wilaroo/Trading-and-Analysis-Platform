# v404 — reconciled_orphan leak RCA endpoint + tqs_integrity n-aware gate (2026-06-24)

## 1) Orphan leak RCA — read-only ENDPOINT (DGX-run via curl)
> NOTE: delivered as an endpoint, NOT a `diag_*.py` script — `.gitignore` line 3559
> (`diag_*.py`) ignores all diag scripts, so they can't ship via Save-to-GitHub.
> Matches the recent v402 pattern (setup-ev / horizon-funnel / tqs-integrity reports).

`services/orphan_leak_rca.py` + `GET /api/slow-learning/orphan-leak/report?days=120&gap_min=120`
— proves/refutes the leak chain WITHOUT writing.

**Hypothesis under test:** a bot-originated trade with a REAL `entry_context`
(regime / TQS / original stop) loses that state on a backend restart or IB
reconnect, resurfaces as an IB-only orphan, and `reconcile_orphan_positions`
(position_reconciler.py:1655+) materializes a brand-new `reconciled_orphan`
BotTrade with a SYNTHETIC default stop (`synthetic_source="default_pct"`, ~2%)
+ thesis-less `entry_context` (regime UNKNOWN) + a fresh OCA. That tight stop
then rides to a loss via `oca_closed_externally_v19_31` (position_manager.py:422).

**Report fields:**
- `population`: n closed orphans + total leak R/$ + negative-R count.
- `close_reasons`: what books the loss.
- `synthetic_source`: default_pct (thesis-less 2%) vs last_verdict smart-stop.
- `predecessor_linkage`: most-recent NON-artifact trade on same (symbol,dir)
  before the orphan — `recoverable_context`, `orphan_stop_tighter_than_predecessor`,
  gap p10/p50/p90, gaps_within_window, predecessor close_reason mix.
- `readopt_loop`: pred closed externally/stop AND re-adopted ≤ `gap_min` → the
  fixable $ leak core + samples.

**Run on DGX:**
```
curl -s "http://localhost:8001/api/slow-learning/orphan-leak/report?days=120&gap_min=120" | python3 -m json.tool
```
Smoke-tested in preview (empty DB → clean run). Unit-tested: `tests/test_orphan_leak_rca.py` (5/5, fake-DB).

**Decision routing after the run:**
- If `recoverable_context` high AND `orphan_stop_tighter_than_predecessor` high →
  FIX = re-link original entry_context + preserve the original stop on re-adopt
  (don't stamp a fresh 2%).
- If `readopt_loop` dominates → FIX = refuse to attach a fresh OCA to a thesis-less
  re-adopt within the window / flatten instead of riding.
- Fix to be env-gated (observe→fix) per DGX workflow.

## 2) tqs_integrity n-aware significance gate — SHIPPED
`backend/services/tqs_integrity.py` `_pillar_predictiveness` flagged
`anti_predictive` purely on |corr| < -0.05, ignoring sample size → false alarms
on noise (scalp pillars n~123, |corr|<0.09 << 2/√n ≈ 0.18). Added pure helpers
`_sig_threshold` (2/√n), `_is_significant`, `_anti_predictive`; the flag now
requires the negative corr to ALSO clear the noise floor. Report rows gain
`sig_threshold` + `significant`. Tests: `backend/tests/test_tqs_integrity_significance.py` (6/6).
