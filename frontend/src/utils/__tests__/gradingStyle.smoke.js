/**
 * Offline smoke test for v19.34.272 gradingStyleKey / getGradingStyleMeta
 * (UI Track A / P1 "Scored as"). Pattern-intrinsic grading style — must
 * IGNORE the liquidity trade_style stamp and prefer persisted scoring_style.
 *
 * Run: cd frontend && node src/utils/__tests__/gradingStyle.smoke.js
 *
 * Note: runs under CommonJS with NO live taxonomy fetch, so it validates the
 * STATIC SETUP_TO_STYLE fallback (which must agree with the backend SSOT).
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');

const src = fs.readFileSync(path.join(__dirname, '../tradeStyleMeta.js'), 'utf8');
const cjsSrc = src
  .replace(/export const /g, 'const ')
  .replace(/export default /g, 'module.exports.default = ')
  .replace(/export \{[^}]+\};?/g, '');
const exports_ = {};
const module_ = { exports: exports_ };
const wrapped = new Function(
  'module', 'exports',
  cjsSrc +
  '\nmodule.exports.gradingStyleKey = gradingStyleKey;' +
  '\nmodule.exports.getGradingStyleMeta = getGradingStyleMeta;',
);
wrapped(module_, exports_);
const { gradingStyleKey, getGradingStyleMeta } = module_.exports;

const cases = [
  // persisted scoring_style ALWAYS wins
  [{ scoring_style: 'multi_day', setup_type: 'orb' }, 'multi_day'],
  [{ tqs_breakdown: { scoring_style: 'position' }, setup_type: 'vwap_fade' }, 'position'],
  // IGNORES the liquidity trade_style stamp — pattern only
  [{ trade_style: 'intraday', setup_type: 'breakdown_confirmed' }, 'multi_day'],
  [{ trade_style: 'scalp', setup_type: 'daily_breakout' }, 'multi_day'],
  [{ trade_style: 'intraday', setup_type: 'stage_2_breakout' }, 'position'],
  // setup-derived pattern (no stamp)
  [{ setup_type: 'orb' }, 'intraday'],
  [{ setup_type: 'vwap_fade' }, 'scalp'],
  [{ setup_type: 'weekly_breakout' }, 'investment'],
  // directional suffix stripping
  [{ setup_type: 'vwap_fade_long' }, 'scalp'],
  // unknown / empty
  [{ setup_type: 'totally_made_up_setup' }, 'unknown'],
  [{}, 'unknown'],
];

let pass = 0;
for (const [row, expect] of cases) {
  const got = gradingStyleKey(row);
  assert.strictEqual(got, expect,
    `gradingStyleKey(${JSON.stringify(row)}) = ${got}, expected ${expect}`);
  pass += 1;
}

// meta resolves & never throws
assert.ok(getGradingStyleMeta({ setup_type: 'breakdown_confirmed' }).label === 'Multi-day');
assert.ok(getGradingStyleMeta({}).label === 'Unknown');

console.log(`gradingStyle.smoke: ${pass}/${cases.length} cases PASS + meta OK`);
