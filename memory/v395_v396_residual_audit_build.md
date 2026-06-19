# v395 / v396 — Residual audit closeout + Financial sub-score un-blind (2026-06-19)

## v395 — residual measurement diag (paste.rs https://paste.rs/TEBuh) READ-ONLY
`backend/scripts/diag_v395_residual_audit.py`. Live DGX results:
- SMB stamp rate: 98.8% real (smb_score_total>0), grades mostly C(47179)/B(2255) — GREEN, closed.
- Financial coverage: 0/1383 cached symbols had roe_pct/net_margin_pct/eps_change_pct/debt_to_equity — RED.
- Levels: 76% of alerts on default bands (50/35/65); 62.8% exactly 50 — RED (S/R mostly absent).

## v395b/c — financial ratio root-cause probes (READ-ONLY, IB clientId 12)
https://paste.rs/XuzTQ (census + spotlight) and https://paste.rs/xgGaV (full dump).
Root cause = PARSER FIELD-CODE MISMATCH, not missing data. Real IB ReportSnapshot codes:
- ROE = TTMROEPCT (parser had ROEPCT) — AAPL 140.9, JPM 17.0
- Net margin: NO ratio in snapshot (TTMNIPEREM absent; TTMGROSMGN=-99999.99 sentinel for banks).
  Derive from TTMNIAC / TTMREV (AAPL 27.0%, JPM 29.4%).
- EPS growth: lives in <ForecastData> ProjLTGrowthRate (AAPL 13.5, JPM 2.5), blank in main Ratios.
- Debt-to-equity: ABSENT from ReportSnapshot (no QTOTD2EQ). Drop it.
Cache DOES carry valuation fields (pe 72%, market_cap 73%, float 73%, beta 97%) — confirms snapshot
is parsed, only the financial-health codes never matched.

## v396 — fix (paste.rs https://paste.rs/LBZmI) 2 files, ON TOP OF v391
- ib_fundamentals_parser.py  PRE dc4082c9 (git HEAD) → POST c0ded2ec
  - _RATIO_FIELDS += TTMROEPCT→roe_pct, TTMNIAC→ttm_net_income, TTMREV→ttm_revenue,
    TTMGROSMGN→gross_margin_pct, TTMEPSXCLX→ttm_eps.
  - -99999 sentinel rejected in the ratio loop.
  - Derive net_margin_pct = ttm_net_income/ttm_revenue*100 (when net_margin_pct absent).
  - Parse <ForecastData> ProjLTGrowthRate → proj_lt_growth_pct.
- fundamental_quality.py  PRE 31b5f7c6 (v391 POST) → POST efefa992
  - _fin["growth"] = proj_lt_growth_pct (fallback eps_change_pct).
- Verified locally: AAPL financial 50→84, JPM 50→75 (3/4 metrics, D2E dropped).
- DEPLOY: apply patcher + ./start_backend.sh --force, then POST /api/short-data/warm-fundamentals
  (institutional:false) to backfill cache. Expect Financial coverage 0% → ~72%.

## STILL OPEN after v396
- Levels (76% default) — S/R data mostly absent from technical snapshot. Needs investigation of the
  S/R source before a fix. NEXT audit item.
- Tape feed (68% no L2/tape read) — scoring fixed in v393; the live tape data source is feed plumbing.
- RVOL (45% default 1.0) — needs secondary volume feed for names outside top-400 L1 push.
- EV (51.5% proxy) — cold-start learning gap; honest since v391; self-heals.
