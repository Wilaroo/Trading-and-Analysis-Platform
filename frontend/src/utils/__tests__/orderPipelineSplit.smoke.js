/**
 * Offline smoke test for orderPipelineSplit (V6 Plan A Phase A §10).
 *
 * Run: cd frontend && node src/utils/__tests__/orderPipelineSplit.smoke.js
 *
 * Asserts the lifted helper reproduces the EXACT order-field output that
 * `SentComV5View.jsx :: derivePipelineCounts` produced inline — so the V5
 * HUD renders identically after the extraction (Phase A acceptance) and the
 * V6 TopStrip can share the one implementation.
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');

// Load the ESM helper under CommonJS (mirror the gradingStyle.smoke.js pattern).
const src = fs.readFileSync(path.join(__dirname, '../orderPipelineSplit.js'), 'utf8');
const cjsSrc = src
  .replace(/export default [^;]+;?/g, '')
  .replace(/export function /g, 'function ');
const module_ = { exports: {} };
const wrapped = new Function(
  'module', 'exports',
  cjsSrc + '\nmodule.exports.orderPipelineSplit = orderPipelineSplit;',
);
wrapped(module_, module_.exports);
const { orderPipelineSplit } = module_.exports;

// The original inline logic, copied verbatim from derivePipelineCounts, as
// the reference oracle.
function oracle(pipeline) {
  const p = pipeline || {};
  return {
    total: (p.pending ?? 0) + (p.ib_pending ?? 0) + (p.executing ?? 0) + (p.filled ?? p.filled_today ?? 0),
    split: (p.pending != null || p.ib_pending != null || p.executing != null)
      ? { queued: (p.pending ?? 0) + (p.executing ?? 0), ibPending: p.ib_pending ?? 0 }
      : null,
    sub: (p.pending != null || p.filled != null || p.filled_today != null)
      ? `${p.filled ?? p.filled_today ?? 0} filled · ${p.pending ?? 0} pending${p.ib_pending ? ` · ${p.ib_pending}@ib` : ''}${p.last_ack_s != null ? ` · ${p.last_ack_s}s ack` : ''}`
      : '—',
    lastAckS: p.last_ack_s ?? null,
  };
}

const cases = [
  undefined,
  null,
  {},
  { pending: 5, executing: 0, ib_pending: 3, filled: 2, last_ack_s: 4 },
  { pending: 0, executing: 2, ib_pending: 0, filled_today: 7 },
  { filled: 9 },                       // only filled → no split, has sub
  { ib_pending: 4 },                   // split present, no sub
  { pending: 1, filled: 0, last_ack_s: 0 },
  { pending: 11, ib_pending: 0, executing: 1, filled_today: 0 },
];

let pass = 0;
for (const c of cases) {
  const got = orderPipelineSplit(c);
  const want = oracle(c);
  assert.deepStrictEqual(got, want, `mismatch for ${JSON.stringify(c)}\n got=${JSON.stringify(got)}\nwant=${JSON.stringify(want)}`);
  pass++;
}

console.log(`✅ orderPipelineSplit smoke: ${pass}/${cases.length} cases match derivePipelineCounts oracle`);
