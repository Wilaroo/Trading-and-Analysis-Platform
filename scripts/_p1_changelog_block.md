## v19.34.271 — P1 Style=Pattern (TQS scoring lens) — 2026-06-20
- TQS WEIGHTING lens now follows setup_taxonomy.style_of (pattern's intrinsic
  style), NOT the liquidity-inflated stamped trade_style. Liquidity stays a
  feasibility/size concern (brackets/TIF), never a silent relabel of the score
  lens. Reversible via env TQS_STYLE_FROM_PATTERN=false. Execution stamp untouched.
- setup_taxonomy.style_of: raw-first lookup fixes the breakdown_confirmed SSOT
  over-collapse (canonicalize stripped the suffix -> was scored intraday; now
  correctly multi_day).
- enhanced_scanner._enrich_alert_with_tqs: persists tqs_breakdown.weights_used
  (float profile) + tqs_breakdown.scoring_style for audit + UI drill.
- Watch/diagnostic triggers (approaching_breakout/hod/orb/range_break,
  carry_forward_watch) stay edge-excluded / no forced trade horizon; the real
  orb/breakout/hod_breakout/range_break setups remain intraday (unaffected).
- VERIFIED on DGX:
  - scripts/selftest_p1_tqs_lens.py  -> ALL PASS (offline, stubbed pillars).
  - scripts/diag_p1_verify.py --days 1 -> [2] pattern-correct 100%,
    [3] weight fidelity 100%, [4] stamp!=pattern 12.9% (expected by design).
- Files: backend/services/setup_taxonomy.py, backend/services/tqs/tqs_engine.py,
  backend/services/enhanced_scanner.py  (.p1bak backups saved; --rollback ready).
- Patchers: patch_p1_style_pattern.py, diag_p1_verify.py, selftest_p1_tqs_lens.py.

