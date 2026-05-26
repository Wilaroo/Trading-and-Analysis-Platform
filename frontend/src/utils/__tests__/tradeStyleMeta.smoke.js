/**
 * Quick offline smoke test for v19.34.99 tradeStyleMeta + TradeStyleChip.
 * Run with: cd frontend && node src/utils/__tests__/tradeStyleMeta.smoke.js
 *
 * Validates the pure-function `resolveTradeStyle()` against a curated
 * sample covering every bucket and every fallback path.
 */
const assert = require('assert');

// Load using a tiny transpile trick — directly require the ESM by reading
// the module source and evaluating it in this scope. Keeps the smoke test
// dependency-free.
const path = require('path');
const fs = require('fs');
const src = fs.readFileSync(path.join(__dirname, '../tradeStyleMeta.js'), 'utf8');
// Strip ESM bindings so it runs under CommonJS eval.
const cjsSrc = src
  .replace(/export const /g, 'const ')
  .replace(/export default /g, 'module.exports.default = ')
  .replace(/export \{[^}]+\};?/g, '');
const exports_ = {};
const module_ = { exports: exports_ };
const wrapped = new Function('module', 'exports', cjsSrc + '\nmodule.exports.TRADE_STYLE_META = TRADE_STYLE_META;\nmodule.exports.resolveTradeStyle = resolveTradeStyle;\nmodule.exports.getTradeStyleMeta = getTradeStyleMeta;\nmodule.exports.humanizeSetupName = humanizeSetupName;\nmodule.exports.isScalpStyle = isScalpStyle;');
wrapped(module_, exports_);
const { TRADE_STYLE_META, resolveTradeStyle, getTradeStyleMeta, humanizeSetupName, isScalpStyle } = module_.exports;

const cases = [
  // explicit trade_style (preferred)
  [{ trade_style: 'scalp' }, 'scalp'],
  [{ trade_style: 'INTRADAY' }, 'intraday'],
  [{ trade_style: 'multi_day' }, 'multi_day'],
  [{ trade_style: 'swing' }, 'swing'],
  [{ trade_style: 'investment' }, 'investment'],
  [{ trade_style: 'position' }, 'position'],

  // legacy aliases
  [{ trade_style: 'A_PLUS' }, 'multi_day'],
  [{ trade_style: 'TRADE_2_HOLD' }, 'intraday'],
  [{ trade_style: 'MOVE_2_MOVE' }, 'scalp'],

  // scan_tier fallback
  [{ scan_tier: 'swing' }, 'swing'],
  [{ tier: 'investment' }, 'investment'],

  // setup_type fallback for each bucket
  [{ setup_type: 'rubber_band' }, 'scalp'],
  [{ setup_type: 'first_vwap_pullback' }, 'intraday'],
  [{ setup_type: 'pocket_pivot' }, 'swing'],
  [{ setup_type: 'weekly_breakout' }, 'investment'],
  [{ setup_type: 'stage_2_breakout' }, 'position'],
  [{ setup_type: 'golden_cross_filtered' }, 'position'],
  [{ setup_type: 'two_hundred_day_reclaim' }, 'position'],

  // v19.34.X (Feb 2026) — setup_variant wins over setup_type
  [{ setup_variant: 'rubber_band', setup_type: 'SCALP' }, 'scalp'],
  // generic trade_style + setup_variant → use setup_variant
  [{ trade_style: 'TRADE_2_HOLD', setup_variant: 'weekly_breakout' }, 'investment'],

  // unknown returns "unknown" not null/undefined
  [{}, 'unknown'],
  [{ setup_type: 'nonexistent_setup_42' }, 'unknown'],

  // ── v19.34.160 — directional suffix stripping for SETUP_TO_STYLE lookup.
  // These mirror live positions observed on the user's DGX (Feb 2026):
  //   USO/BP/etc have setup_type='vwap_fade_long' or 'mean_reversion_long'
  //   but trade_style='trade_2_hold' (generic). Pre-fix the chip read
  //   "INTRA" — should read "SCALP".
  [{ setup_type: 'vwap_fade_long', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'vwap_fade_short', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'mean_reversion_long', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'mean_reversion_short', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'gap_fade_long', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'rubber_band_long', trade_style: 'trade_2_hold' }, 'scalp'],
  [{ setup_type: 'rubber_band_short', trade_style: 'trade_2_hold' }, 'scalp'],
  // Setup_variant carrying directional suffix → still resolves correctly
  [{ setup_variant: 'vwap_fade_short', trade_style: 'trade_2_hold' }, 'scalp'],
  // Non-scalp setups with directional suffix → respect their actual bucket
  [{ setup_type: 'breakout_long', trade_style: 'trade_2_hold' }, 'intraday'],
  // Already-stripped variants still work
  [{ setup_type: 'vwap_fade' }, 'scalp'],

  // ── v19.34.160 — `timeframe` is now consulted in the fallback chain.
  // USO live position: setup_type='vwap_fade_long', timeframe='scalp'.
  // Either signal alone is sufficient.
  [{ timeframe: 'scalp' }, 'scalp'],
  [{ timeframe: 'SCALP' }, 'scalp'],  // case-insensitive
  // timeframe='scalp' still wins over an empty trade_style
  [{ timeframe: 'scalp', trade_style: '' }, 'scalp'],

  // ── v19.34.160 — squeeze stays INTRADAY (most user positions are squeeze).
  // This is a regression guard: the fix must NOT inadvertently flip
  // squeeze / vwap_continuation / accumulation_entry buckets.
  [{ setup_type: 'squeeze', trade_style: 'trade_2_hold' }, 'intraday'],
  [{ setup_type: 'vwap_continuation', trade_style: 'trade_2_hold' }, 'intraday'],
  [{ setup_type: 'accumulation_entry', trade_style: 'trade_2_hold' }, 'swing'],
];

let passed = 0;
let failed = 0;
for (const [row, expected] of cases) {
  const got = resolveTradeStyle(row);
  if (got === expected) {
    passed++;
  } else {
    failed++;
    console.error(`FAIL: resolveTradeStyle(${JSON.stringify(row)}) returned "${got}", expected "${expected}"`);
  }
}

// getTradeStyleMeta returns non-null meta for everything
assert.ok(getTradeStyleMeta({}).label, 'getTradeStyleMeta returns non-null for empty row');
assert.strictEqual(getTradeStyleMeta({ trade_style: 'position' }).label, 'Position');
assert.strictEqual(getTradeStyleMeta({ trade_style: 'position' }).horizon, '3+ months');

// humanizeSetupName
assert.strictEqual(humanizeSetupName('stage_2_breakout'), 'Stage 2 Breakout');
assert.strictEqual(humanizeSetupName('vcp_breakout'), 'VCP Breakout');
assert.strictEqual(humanizeSetupName('two_hundred_day_reclaim'), '200DMA Reclaim');
assert.strictEqual(humanizeSetupName(''), '');

// ── v19.34.160 — isScalpStyle convenience export.
assert.strictEqual(isScalpStyle({ setup_type: 'vwap_fade_long', trade_style: 'trade_2_hold' }), true, 'isScalpStyle: directional suffix should resolve to scalp');
assert.strictEqual(isScalpStyle({ setup_type: 'squeeze', trade_style: 'trade_2_hold' }), false, 'isScalpStyle: squeeze must NOT be scalp');
assert.strictEqual(isScalpStyle({ timeframe: 'scalp' }), true, 'isScalpStyle: timeframe stamp alone is sufficient');
assert.strictEqual(isScalpStyle({}), false, 'isScalpStyle: empty row is not a scalp');

console.log(`PASS: ${passed}/${passed + failed} resolveTradeStyle cases + 9 meta/humanize/isScalpStyle assertions`);
process.exit(failed === 0 ? 0 : 1);
