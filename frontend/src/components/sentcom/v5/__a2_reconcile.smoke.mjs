// Standalone smoke test for the v19.34.274 A2 grades-reconcile logic.
// Mirrors the reconcile loop in ScannerCardsV5.jsx (no React needed).
// Run: node src/components/sentcom/v5/__a2_reconcile.smoke.mjs

const hasPillarGrades = (g) =>
  !!g && typeof g === 'object' && Object.values(g).some(Boolean);

function reconcile(cache, rawCards) {
  const now = Date.now();
  for (const c of rawCards) {
    if (c.source !== 'alert') continue;
    if (hasPillarGrades(c.tqs_pillar_grades)) {
      cache.set(c.symbol, {
        grades: c.tqs_pillar_grades,
        grade: c.tqs_grade ?? null,
        score: c.tqs_score ?? null,
        ts: now,
      });
    } else {
      const cached = cache.get(c.symbol);
      if (cached && hasPillarGrades(cached.grades)) {
        c.tqs_pillar_grades = cached.grades;
        if (c.tqs_grade == null) c.tqs_grade = cached.grade;
        if (c.tqs_score == null) c.tqs_score = cached.score;
      }
    }
  }
  return rawCards;
}

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; } else { fail++; console.error('FAIL:', msg); } };

const cache = new Map();
const GRADES = { setup: 'A', technical: 'B', fundamental: 'C', context: 'B', execution: 'A' };

// Render 1: WS alert arrives WITH grades.
let cards = reconcile(cache, [
  { symbol: 'AAPL', source: 'alert', tqs_pillar_grades: GRADES, tqs_grade: 'B', tqs_score: 72 },
]);
ok(hasPillarGrades(cards[0].tqs_pillar_grades), 'r1 alert keeps grades');
ok(cache.has('AAPL'), 'r1 cache learned AAPL');

// Render 2: only REST setup remains (NO grades) — the flashing-bug trigger.
cards = reconcile(cache, [
  { symbol: 'AAPL', source: 'alert', tqs_pillar_grades: null, tqs_grade: null, tqs_score: null },
]);
ok(hasPillarGrades(cards[0].tqs_pillar_grades), 'r2 ring PERSISTS via backfill');
ok(cards[0].tqs_grade === 'B', 'r2 center grade backfilled');
ok(cards[0].tqs_score === 72, 'r2 score backfilled');

// Render 3: fresh grades override the cache.
const NEW = { setup: 'A', technical: 'A', fundamental: 'A', context: 'A', execution: 'A' };
cards = reconcile(cache, [
  { symbol: 'AAPL', source: 'alert', tqs_pillar_grades: NEW, tqs_grade: 'A', tqs_score: 91 },
]);
ok(cache.get('AAPL').grade === 'A', 'r3 cache updated to fresh grade');

// Non-alert (closed/position) cards are untouched.
cards = reconcile(cache, [
  { symbol: 'AAPL', source: 'position', tqs_pillar_grades: null },
]);
ok(!hasPillarGrades(cards[0].tqs_pillar_grades), 'non-alert card NOT backfilled');

// Unknown symbol with no grades + empty cache → stays empty (no ring).
cards = reconcile(cache, [
  { symbol: 'ZZZZ', source: 'alert', tqs_pillar_grades: null },
]);
ok(!hasPillarGrades(cards[0].tqs_pillar_grades), 'uncached symbol stays ringless');

console.log(`\nA2 reconcile smoke: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
