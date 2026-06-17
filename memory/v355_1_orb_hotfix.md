# v355.1 — ORB timestamp-key hotfix (CRITICAL: ORB was never firing)

## Bug (found via full pipeline trace)
_get_intraday_bars_from_db (realtime_technical_service.py:163) RENAMES date->timestamp.
v355 _check_orb `_etm()` read bar.get("date") -> always None -> opening range never built
-> ORB SILENTLY NEVER FIRED since v355 deploy. second_chance unaffected (OHLCV only).

## Fix: bar.get("timestamp") or bar.get("date")  (1 line in _etm)
PRE_FUNC_SHA (live v355 orb) = c4876ae8c64ffe8c790741272b4c5510440c98847ffe2e365ac6507d32936e50
POST_FUNC_SHA               = f62cdccdba75564508a5a9afb85ff51817eea1b32cae19058fd29d28f30c882d
DGX_WHOLE_PRE               = bacf7753595c6b2479db0a5cecc8dccf4193fc34b6bebfbb014fe994ae3ebcb7
patch_v355_1_orb_timestamp_fix.py -> https://paste.rs/L1Rp5  sha 37bc4045d37e08fdbeaea752a3ec202b6967ecd84dc3e0d88fafce8af727f399
test_v355_orb.py (now uses 'timestamp' key) -> https://paste.rs/bbHOp  sha 1437b7e543b9d9365ce9b748fe6db017313db5b03ecd04ff8f95abc2d519ace7

## Pipeline trace CONFIRMED (answer to operator's question)
- Dispatch (line 4088 checkers): orb->_check_orb, second_chance->_check_second_chance, vwap_bounce->_check_vwap_bounce.
- Flow: detector -> _enrich_alert_with_ai -> _enrich_alert_with_tqs -> _process_new_alert (persist live_alerts)
  -> _passes_ev_quality_gate -> _auto_execute_alert.
- Learning: _passes_ev_quality_gate keys base setup_type ("orb_long_confirmed"->"orb"; "second_chance"->"second_chance"),
  reads _strategy_stats[base].expected_value_r/win_rate from graded r_outcomes; 20-trade cold-start grace; must be +EV to auto-trade.
- vwap_bounce suppressed (returns None) -> no alerts, no harm, gate naturally skips.

## Status: AWAITING operator --check/--apply/pytest/commit/restart for v355.1.
## TODO suggested: read-only diag_live_setup_fires.py (per-setup alert counts last N sessions) for ongoing confidence.
## Next setup after hotfix: first_move_up / first_move_down.
