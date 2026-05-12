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
const wrapped = new Function('module', 'exports', cjsSrc + '\nmodule.exports.TRADE_STYLE_META = TRADE_STYLE_META;\nmodule.exports.resolveTradeStyle = resolveTradeStyle;\nmodule.exports.getTradeStyleMeta = getTradeStyleMeta;\nmodule.exports.humanizeSetupName = humanizeSetupName;');
wrapped(module_, exports_);
const { TRADE_STYLE_META, resolveTradeStyle, getTradeStyleMeta, humanizeSetupName } = module_.exports;

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

  // unknown returns "unknown" not null/undefined
  [{}, 'unknown'],
  [{ setup_type: 'nonexistent_setup_42' }, 'unknown'],
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

console.log(`PASS: ${passed}/${passed + failed} resolveTradeStyle cases + 5 meta/humanize assertions`);
process.exit(failed === 0 ? 0 : 1);
