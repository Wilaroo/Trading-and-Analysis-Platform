## v19.34.272 — UI Track A · A1 "Scored as" (P1 Style=Pattern surfacing) — 2026-06-20
- Makes the P1 fix visible in the cockpit: every scanner row + the TQS drawer
  now show the PATTERN-INTRINSIC grading style TQS used to weight the score,
  distinct from the liquidity horizon stamp (TradeStyleChip). A breakdown_confirmed
  on a liquid name reads horizon=INTRA but SCORED M-DAY.
- NEW frontend/src/components/sentcom/v5/ScoredAsChip.jsx — compact "SCORED · <STYLE>"
  chip; re-renders on live SSOT taxonomy hydration; renders nothing for unknown.
- NEW frontend/src/utils/__tests__/gradingStyle.smoke.js — 11 offline cases.
- utils/tradeStyleMeta.js: + gradingStyleKey()/getGradingStyleMeta() (prefers
  persisted tqs_breakdown.scoring_style, else setup-derived pattern via the live
  SSOT bridge, IGNORES the trade_style stamp). Also fixed the stale static
  fallback breakdown_confirmed 'intraday' -> 'multi_day' to match backend style_of.
- v5/TqsPillarPanel.jsx: "Grading style: <Style>" line above the weights.
- v5/TqsDrillDownDrawer.jsx: derives + passes scoringStyle.
- v5/ScannerCardsV5.jsx: renders <ScoredAsChip/> on each card.
- VERIFIED: yarn build clean (no new warnings); gradingStyle.smoke 11/11;
  patcher applied to a pristine clone → byte-identical to the dev build;
  rollback restores tracked tree to HEAD exactly.
- Delivered: scripts/patch_a1_scored_as.py (paste.rs/7Wafo). Apply: --apply then
  cd frontend && yarn build. Rollback: --rollback.
- NOTE follow-up (A1b, optional): have GET /api/tqs/card-detail return the
  persisted scoring_style so the drawer shows the EXACT stamped lens instead of
  the setup-derived one (identical for all tradeable setups today).

