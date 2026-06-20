/**
 * tradeStyleMeta — v19.34.99
 *
 * Single source of truth for SentCom's 5 trade-style horizons on the
 * frontend. Maps any incoming style identifier (from `trade_style`,
 * `scan_tier`, or — as last-resort — `setup_type`) to:
 *
 *   - label    : Display string ("Scalp", "Intraday", "Swing"…)
 *   - horizon  : Human-readable hold horizon
 *   - tone     : Tailwind color tone used by `TradeStyleChip`
 *   - shortKey : Compact 4-6 char label for tight spaces ("SCALP", "POS")
 *
 * Backed by `SETUP_REGISTRY` in `services/smb_integration.py` —
 * keep this in sync when new styles or buckets are added.
 *
 * The setup→style fallback table covers the 68 setups currently
 * registered (v19.34.95 expansion). When a `trade_style` is already
 * supplied by the backend it always wins; the fallback only fires
 * when backend data is missing.
 */

export const TRADE_STYLE_META = {
  scalp: {
    label: 'Scalp',
    horizon: 'Minutes — 1 hour',
    tone: 'fuchsia',
    shortKey: 'SCALP',
    bucket: 'scalp',
  },
  intraday: {
    label: 'Intraday',
    horizon: '1 — 6 hours',
    tone: 'sky',
    shortKey: 'INTRA',
    bucket: 'intraday',
  },
  multi_day: {
    label: 'Multi-day',
    horizon: '1 — 5 days',
    tone: 'emerald',
    shortKey: 'M-DAY',
    bucket: 'swing',
  },
  swing: {
    label: 'Swing',
    horizon: '1 — 3 weeks',
    tone: 'emerald',
    shortKey: 'SWING',
    bucket: 'swing',
  },
  investment: {
    label: 'Investment',
    horizon: '3 weeks — 3 months',
    tone: 'amber',
    shortKey: 'INV',
    bucket: 'investment',
  },
  position: {
    label: 'Position',
    horizon: '3+ months',
    tone: 'rose',
    shortKey: 'POS',
    bucket: 'position',
  },
  unknown: {
    label: 'Unknown',
    horizon: 'Not classified',
    tone: 'slate',
    shortKey: '?',
    bucket: 'unknown',
  },
};

/**
 * Fallback setup → style mapping. Used ONLY when the backend hasn't
 * filled `trade_style` on the row. Mirrors `SETUP_REGISTRY` in
 * `services/smb_integration.py` v19.34.95.
 */
export const SETUP_TO_STYLE = {
  // ── SCALP (23)
  '9_ema_scalp': 'scalp', abc_scalp: 'scalp', backside: 'scalp', bella_fade: 'scalp',
  fashionably_late: 'scalp', first_move_down: 'scalp', first_move_up: 'scalp',
  gap_fade: 'scalp', gap_give_go: 'scalp', gap_pick_roll: 'scalp', hitchhiker: 'scalp',
  mean_reversion: 'scalp', off_sides: 'scalp', off_sides_short: 'scalp', puppy_dog: 'scalp',
  rubber_band: 'scalp', rubber_band_long: 'scalp', rubber_band_short: 'scalp',
  second_chance: 'scalp', spencer_scalp: 'scalp', fading_bounce: 'scalp',
  time_of_day_fade: 'scalp', volume_capitulation: 'scalp', vwap_fade: 'scalp',
  // ── INTRADAY (17)
  back_through_open: 'intraday', big_dog: 'intraday', breakdown: 'intraday',
  breaking_news: 'intraday', breakout: 'intraday', chart_pattern: 'intraday',
  first_vwap_pullback: 'intraday', hod_breakout: 'intraday', lod_breakdown: 'intraday',
  opening_drive: 'intraday', orb: 'intraday', range_break: 'intraday',
  relative_strength: 'intraday', relative_weakness: 'intraday', squeeze: 'intraday',
  up_through_open: 'intraday', vwap_bounce: 'intraday', vwap_continuation: 'intraday',
  premarket_high_break: 'intraday', the_3_30_trade: 'intraday', bouncy_ball: 'intraday',
  tidal_wave: 'intraday',                            // SSOT: momentum/breakout → intraday (was 'scalp')
  // ── SWING — pre-existing daily setups (multi_day) + v19.34.95 new (swing)
  base_breakout: 'swing',                            // v19.34.32 — re-mapped from 'position' (1-3 weeks is the realistic hold horizon)
  breakdown_confirmed: 'intraday',                   // SSOT: breakdown family → intraday (was 'multi_day')
  daily_breakout: 'multi_day',
  daily_squeeze: 'multi_day',
  day_2_continuation: 'swing',
  gap_fill_open: 'swing',
  trend_continuation: 'multi_day',
  pocket_pivot: 'swing',
  vcp_breakout: 'swing',
  three_week_tight: 'swing',
  bull_flag_break: 'swing',
  bear_flag_break: 'swing',
  ascending_triangle_break: 'swing',
  descending_triangle_break: 'swing',
  cup_with_high_handle: 'swing',
  // ── INVESTMENT (v19.34.95)
  weekly_breakout: 'investment',
  multi_quarter_base_break: 'investment',
  rs_leader_break: 'investment',
  fifty_two_week_high_break: 'investment',
  power_trend_stack: 'investment',
  // ── POSITION
  accumulation_entry: 'swing',                       // v19.34.32 — re-mapped from 'position' (typical hold 1-3 weeks)
  stage_2_breakout: 'position',
  stage_1_to_2_transition: 'position',
  stage_3_to_4_breakdown: 'position',
  golden_cross_filtered: 'position',
  death_cross_filtered: 'position',
  two_hundred_day_reclaim: 'position',
  two_hundred_day_loss: 'position',
};

/**
 * v19.34.271 (m4-frontend) — Live SSOT bridge.
 * `_dynamicStyleMap` is hydrated once from GET /api/sentcom/taxonomy so the
 * UI cannot drift from the backend canonical taxonomy (services/setup_taxonomy.py).
 * It maps canonical setup name → style bucket and takes precedence over the
 * static SETUP_TO_STYLE fallback. If the fetch fails (offline / cold start),
 * the static table keeps everything working — zero hard dependency.
 */
let _dynamicStyleMap = {};
let _taxonomyLoaded = false;

// v19.34.272 (T4) — taxonomy hydration is observable so React views re-render
// the moment the live SSOT map arrives (instead of being stuck on the static
// fallback for the session). subscribeTaxonomy/getTaxonomyVersion are pure JS
// (no React dep) so the node smoke test can import this file unchanged; the
// `useTaxonomyVersion` React hook lives in utils/useTaxonomy.js.
let _taxonomyVersion = 0;
const _taxonomySubs = new Set();

export const getTaxonomyVersion = () => _taxonomyVersion;

export const subscribeTaxonomy = (fn) => {
  _taxonomySubs.add(fn);
  return () => _taxonomySubs.delete(fn);
};

const _notifyTaxonomy = () => {
  _taxonomyVersion += 1;
  _taxonomySubs.forEach((fn) => {
    try { fn(_taxonomyVersion); } catch { /* ignore subscriber errors */ }
  });
};

export const initTaxonomyStyles = async () => {
  if (_taxonomyLoaded) return _dynamicStyleMap;
  try {
    const base = process.env.REACT_APP_BACKEND_URL || '';
    const res = await fetch(`${base}/api/sentcom/taxonomy`);
    if (!res.ok) return _dynamicStyleMap;
    const data = await res.json();
    const setups = (data && data.setups) || {};
    const next = {};
    Object.keys(setups).forEach((name) => {
      const style = setups[name] && setups[name].style;
      if (style && TRADE_STYLE_META[style]) next[name] = style;
    });
    _dynamicStyleMap = next;
    _taxonomyLoaded = true;
    _notifyTaxonomy();  // tell subscribed views the SSOT map is live
  } catch {
    // Network/parse failure — silently keep the static fallback.
  }
  return _dynamicStyleMap;
};

// Fire-and-forget hydrate on module load (browser only).
if (typeof window !== 'undefined') {
  // Defer so it never blocks first paint.
  setTimeout(() => { initTaxonomyStyles(); }, 0);
}

/**
 * Canonicalise any raw style/tier string. Handles backend variants
 * (e.g. "TRADE_2_HOLD" → "intraday", "A_PLUS" → "multi_day") and
 * un-lowercased values.
 */
const STYLE_ALIAS = {
  scalp: 'scalp', move_2_move: 'scalp',
  intraday: 'intraday', trade_2_hold: 'intraday',
  multi_day: 'multi_day', a_plus: 'multi_day', day: 'multi_day',
  swing: 'swing',
  investment: 'investment', invest: 'investment',
  position: 'position', longterm: 'position',
};

/**
 * Resolve a normalised style key from a trade-shaped object.
 * Order of precedence: explicit `trade_style` → `scan_tier` → `tier`
 * → `timeframe` → derive from `setup_type` via SETUP_TO_STYLE. Returns
 * "unknown" when none match.
 *
 * v19.34.32 — When `trade_style` is the GENERIC fallback `trade_2_hold`
 * (the default the backend stamps on every alert that didn't pick a
 * real horizon), it gets SKIPPED in favour of the setup-derived style.
 * Without this, every daily-timeframe setup (daily_squeeze,
 * accumulation_entry, day_2_continuation, …) was being mislabelled as
 * `intraday` because `trade_2_hold` aliases to `intraday`.
 *
 * v19.34.160 — Two fixes for "scalp positions labelled INTRADAY":
 *   1) Strip directional suffixes (`_long`, `_short`, `_buy`, `_sell`)
 *      from `setup_type` / `setup_variant` before SETUP_TO_STYLE
 *      lookup. Pre-fix, `vwap_fade_long` and `mean_reversion_long`
 *      missed the base table (which only had `vwap_fade` /
 *      `mean_reversion`) and fell through to the `trade_2_hold` →
 *      intraday alias.
 *   2) Include `row.timeframe` in the lookup chain. The bot already
 *      stamps `timeframe='scalp'` (e.g. USO vwap_fade_long position)
 *      but `resolveTradeStyle` never consulted it.
 */
const GENERIC_TRADE_STYLES = new Set(['trade_2_hold']);

// v19.34.160 — Directional suffixes stripped before SETUP_TO_STYLE lookup.
// Mirrors the convention used by isScalpStyle / OpenPositionsV5.SCALP_SETUPS:
// `gap_fade_long` shares the same bucket as `gap_fade`.
const DIRECTIONAL_SUFFIXES = ['_long', '_short', '_buy', '_sell'];

const stripDirectionalSuffix = (key) => {
  for (const suf of DIRECTIONAL_SUFFIXES) {
    if (key.endsWith(suf)) return key.slice(0, -suf.length);
  }
  return key;
};

const setupLookup = (raw) => {
  if (!raw) return null;
  const k = String(raw).trim().toLowerCase();
  if (!k) return null;
  // v19.34.271 — live SSOT map wins over the static fallback when hydrated.
  if (_dynamicStyleMap[k]) return _dynamicStyleMap[k];
  if (SETUP_TO_STYLE[k]) return SETUP_TO_STYLE[k];
  const stripped = stripDirectionalSuffix(k);
  if (stripped !== k) {
    return _dynamicStyleMap[stripped] || SETUP_TO_STYLE[stripped] || null;
  }
  return null;
};

export const resolveTradeStyle = (row = {}) => {
  const norm = (v) => String(v || '').trim().toLowerCase();
  const tryKey = (raw) => {
    const k = norm(raw);
    if (!k) return null;
    if (STYLE_ALIAS[k]) return STYLE_ALIAS[k];
    if (TRADE_STYLE_META[k]) return k;
    return null;
  };
  // v19.34.32 — setup-type wins over the generic `trade_2_hold` default.
  // v19.34.X (Feb 2026) — setup_variant (granular SMB name) preferred
  // over the broader setup_type when both are present.
  // v19.34.160 — both lookups now strip directional suffixes.
  const setupKey = setupLookup(row.setup_variant) || setupLookup(row.setup_type);
  const tradeStyleNorm = norm(row.trade_style);
  if (setupKey && GENERIC_TRADE_STYLES.has(tradeStyleNorm)) {
    return setupKey;
  }
  return (
    tryKey(row.trade_style)
    || tryKey(row.scan_tier)
    || tryKey(row.tier)
    || tryKey(row.symbol_tier)
    || tryKey(row.timeframe)        // v19.34.160 — bot stamps timeframe='scalp'
    || setupKey
    || 'unknown'
  );
};

// v19.34.160 — Single source of truth for "is this a scalp position?".
// Replaces the divergent OpenPositionsV5.isScalpPosition() hardcoded list
// which only knew about 14 setups vs SETUP_TO_STYLE's 23.
export const isScalpStyle = (row) => resolveTradeStyle(row) === 'scalp';

/**
 * Convenience: returns the full meta block (label/horizon/tone) for
 * a trade row, never null.
 */
export const getTradeStyleMeta = (row) => {
  const key = resolveTradeStyle(row);
  return TRADE_STYLE_META[key] || TRADE_STYLE_META.unknown;
};

/**
 * Setup-name humaniser used in trade rows. Drops underscores, title-
 * cases, and applies a few hand-tuned shorthand replacements so the
 * UI never shows raw machine identifiers.
 */
const SHORT_OVERRIDES = {
  fifty_two_week_high_break: '52-Wk High Break',
  multi_quarter_base_break: 'Multi-Qtr Base Break',
  stage_1_to_2_transition: 'Stage 1 → 2 Transition',
  stage_3_to_4_breakdown: 'Stage 3 → 4 Breakdown',
  two_hundred_day_reclaim: '200DMA Reclaim',
  two_hundred_day_loss: '200DMA Loss',
  golden_cross_filtered: 'Filtered Golden Cross',
  death_cross_filtered: 'Filtered Death Cross',
  cup_with_high_handle: 'Cup w/ High Handle',
  rs_leader_break: 'RS Leader Break',
  power_trend_stack: 'Power Trend Stack',
  vcp_breakout: 'VCP Breakout',
  three_week_tight: '3-Week Tight',
  power_earnings_gap_drift: 'Power Earnings Gap Drift',
  weekly_breakout: '26-Wk Weekly Breakout',
  stage_2_breakout: 'Stage 2 Breakout',
  pocket_pivot: 'Pocket Pivot',
  high_tight_flag: 'High Tight Flag',
  bull_flag_break: 'Bull Flag Break',
  bear_flag_break: 'Bear Flag Break',
  ascending_triangle_break: 'Asc. Triangle Break',
  descending_triangle_break: 'Desc. Triangle Break',
};

export const humanizeSetupName = (raw) => {
  if (!raw) return '';
  const key = String(raw).trim().toLowerCase();
  if (SHORT_OVERRIDES[key]) return SHORT_OVERRIDES[key];
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
};

export default {
  TRADE_STYLE_META,
  resolveTradeStyle,
  getTradeStyleMeta,
  humanizeSetupName,
  isScalpStyle,
  initTaxonomyStyles,
};
