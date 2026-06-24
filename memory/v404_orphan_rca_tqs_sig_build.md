# v404 — reconciled_orphan leak RCA diagnostic + tqs_integrity n-aware gate (2026-06-24)

## 1) Orphan leak RCA — read-only diagnostic (DGX-run)
`backend/scripts/diag_orphan_leak_rca.py` — proves/refutes the leak chain WITHOUT writing.

**Hypothesis under test:** a bot-originated trade with a REAL `entry_context`
(regime / TQS / original stop) loses that state on a backend restart or IB
reconnect, resurfaces as an IB-only orphan, and `reconcile_orphan_positions`
(position_reconciler.py:1655+) materializes a brand-new `reconciled_orphan`
BotTrade with a SYNTHETIC default stop (`synthetic_source="default_pct"`, ~2%)
+ thesis-less `entry_context` (regime UNKNOWN) + a fresh OCA. That tight stop
then rides to a loss via `oca_closed_externally_v19_31` (position_manager.py:422).

**What it measures per closed orphan:**
- A: population + total leak R/$ + negative-R count.
- B: close-reason breakdown (what books the loss).
- C: synthetic_source split (default_pct = thesis-less 2% vs last_verdict smart-stop).
- D: predecessor linkage — most-recent NON-artifact bot_trade on same (symbol,dir)
  before the orphan: did it carry REAL recoverable context? was the orphan's stop
  TIGHTER? gap pred.closed→orphan.entry distribution; predecessor close_reason mix.
- E: re-adopt-loop core (pred closed externally/stop AND re-adopted ≤ GAP_MIN) and
  its attributable $ leak = the fixable portion.

**Run on DGX:**
```
cd ~/Trading-and-Analysis-Platform
PYTHONPATH=backend .venv/bin/python backend/scripts/diag_orphan_leak_rca.py --days 120
# optional: --gap-min 120  (re-adopt window minutes)
```
Smoke-tested in preview (empty DB → clean run, exit 0).

**Decision routing after the run:**
- If `recoverable_ctx` high AND `tighter_stop` high → FIX = re-link original
  entry_context + preserve the original stop on re-adopt (don't stamp a fresh 2%).
- If re-adopt-loop core dominates → FIX = refuse to attach a fresh OCA to a
  thesis-less re-adopt within the window / flatten instead of riding.
- Fix to be env-gated (observe→fix) per DGX workflow.

## 2) tqs_integrity n-aware significance gate — SHIPPED
`backend/services/tqs_integrity.py` `_pillar_predictiveness` flagged
`anti_predictive` purely on |corr| < -0.05, ignoring sample size → false alarms
on noise (scalp pillars n~123, |corr|<0.09 << 2/√n ≈ 0.18). Added pure helpers
`_sig_threshold` (2/√n), `_is_significant`, `_anti_predictive`; the flag now
requires the negative corr to ALSO clear the noise floor. Report rows gain
`sig_threshold` + `significant`. Tests: `backend/tests/test_tqs_integrity_significance.py` (6/6).
