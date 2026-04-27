/**
 * useMarketState — back-compat re-export of the canonical hook now
 * implemented in `contexts/MarketStateContext.jsx`.
 *
 * Background (2026-02): originally each consumer of `/api/market-state`
 * ran its own 60s polling effect — fine when there's one consumer, but
 * with the V5 wordmark moon + DataFreshnessBadge chip + FreshnessInspector
 * banner all reading the same snapshot we'd issue 3+ round-trips every
 * minute and risk the surfaces drifting out of sync during state flips.
 *
 * The implementation moved into a single Provider mounted once at the
 * top of `App.js`. This file stays so the existing
 * `import { useMarketState } from '../hooks/useMarketState'` imports
 * keep working — no consumer rewrites needed.
 */
export { useMarketState, default } from '../contexts/MarketStateContext';
