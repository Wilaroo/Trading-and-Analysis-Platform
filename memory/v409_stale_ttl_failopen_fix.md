# v409 — stale-alert TTL fail-OPEN fix (P0 live: bot took 0 trades) — 2026-06-24

## Symptom (operator-reported, live)
Bot took 0 trades and SentCom intelligence showed zeros. Funnel proved the bot
was healthy (running, autonomous, 8/25 positions, daily-loss NOT hit) but
`confidence-gate/summary.today.evaluated = 0` and the last gate decision was
`2026-06-23T15:00:06Z` (= 2026-06-23 11:00 AM ET). So the gate had evaluated
NOTHING for ~28h.

## Root cause
`rejection_daily_counts` for the day was dominated by **`stale_alert_ttl`**:
swing 3415 + position 1880 + intraday 1146 + scalp 426 ≈ **6.9k** rejections —
every alert died at the stale-TTL gate BEFORE reaching `confidence_gate.evaluate()`.

The v402 change made `services/opportunity_evaluator.py`'s stale-TTL gate
**fail-CLOSED** on a missing alert timestamp: when `triggered_at_unix` /
`triggered_at` was absent and `STALE_ALERT_POLICY` defaulted to `block`, it
synthesised `now - (ttl+1)` → forced the alert STALE → `return None`.

But the production execution paths NEVER thread a timestamp into the alert dict:
- `services/scanner_integration.py::submit_trade_from_scanner` builds the alert
  dict from the LiveAlert with NO `triggered_at*` field (auto-exec path).
- the bot scan-loop alert dict also has none.
Only the `enhanced_alerts.py` dict format carries `triggered_at_unix`.
⇒ 100% of execution-path alerts were synthesised stale and dropped.

The pre-existing regression test `test_missing_ts_fail_open` (which asserts a
missing timestamp must fail-OPEN) was silently RED after v402 — direct proof of
the regression.

## Fix (one gate, env-reversible)
`services/opportunity_evaluator.py` — missing/unparseable timestamp now
**fail-OPEN** by default (logs a warning, does NOT synthesise stale). The
aged-timestamp block below is UNCHANGED and still fires for any alert that DOES
carry a real timestamp. Strict v402 behaviour is preserved behind an explicit
opt-in: `STALE_ALERT_BLOCK_MISSING_TS=1` (default `0`). `STALE_ALERT_POLICY=off`
still short-circuits the missing-ts branch entirely.

No change to order submission, queue, pusher, reaper, kill-switch, or the
confidence gate. Touches ONLY the missing-timestamp branch of one gate.

## Tests
`tests/test_stale_alert_ttl_v19_34_44.py`: previously-red `test_missing_ts_fail_open`
now green; +2 new (`test_missing_ts_fail_open_even_when_policy_block`,
`test_missing_ts_block_opt_in`). Full file: 12 passed.

## ROLLOUT
- INSTANT mitigation on the CURRENTLY-DEPLOYED (v402) code: add
  `STALE_ALERT_POLICY=observe` to `backend/.env`, restart backend. (observe never
  synthesises stale → flow restored.)
- DURABLE: Save-to-GitHub `main-2.0` → DGX pull → restart. After pull the default
  is already fail-open; the env override is optional.
- VERIFY: `confidence-gate/summary.today.evaluated` should climb within a scan or
  two and `rejection_daily_counts` `stale_alert_ttl` should stop dominating.

## FOLLOW-UP (separate, not in this fix)
1. (Enhancement) Thread the LiveAlert's real emission time into the auto-exec +
   scan-loop alert dicts so the TTL gate measures genuine pipeline lag instead of
   being a no-op for execution-path alerts. NOTE: `created_at` is a dedup-upsert
   artifact for re-fired daily setups, so this changes daily-alert trading
   semantics → must be observe-first.
2. (Operator-flagged P0/P1) 119 untracked IBM shares held all day — bot does not
   track them (not in `_open_trades`); orphan/tracking-gap class (ties to Seal #2).
