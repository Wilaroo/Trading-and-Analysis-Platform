/**
 * SetupGradeChip — v19.34.113
 *
 * Compact inline chip showing the rolling 30-day grade for a
 * `setup_type`. Pulls from `/api/setup-grades` and caches the entire
 * card map per session — the chip is read-mostly, the EOD scheduler
 * refreshes the data once per day at 16:10 ET.
 *
 * Surfaces:
 *   • A+ / A / B+ / B / C → green-to-amber gradient
 *   • F                   → rose (operator-readable danger signal)
 *   • INSUFFICIENT_DATA   → muted slate
 *
 * On hover: tooltip shows trades_count, win_rate, avg_r, total_realized_pnl.
 *
 * This is INTENTIONALLY observe-only — the chip does not block the
 * alert / trade entry. A future PR can wire a hard block once the
 * grade formula is sanity-checked against a week of live data.
 *
 * Usage:
 *   <SetupGradeChip setupType="nine_ema_scalp" />
 *   <SetupGradeChip setupType="breakout" days={7} />
 *   <SetupGradeChip setupType="scalp" compact />
 */
import React, { useEffect, useState } from 'react';

const GRADE_TONE = {
  'A+': 'bg-emerald-950/60 text-emerald-300 border-emerald-800',
  'A':  'bg-emerald-950/40 text-emerald-400 border-emerald-800/60',
  'B+': 'bg-sky-950/50 text-sky-300 border-sky-800',
  'B':  'bg-sky-950/40 text-sky-400 border-sky-800/60',
  'C':  'bg-amber-950/50 text-amber-300 border-amber-800',
  'F':  'bg-rose-950/60 text-rose-300 border-rose-700',
  INSUFFICIENT_DATA: 'bg-slate-900/60 text-slate-500 border-slate-700',
};

// Session-scoped cache. Refreshed on first request per setup_type per
// `days` window per page load. The EOD scheduler refreshes the
// underlying data once per day, so a single in-memory cache per
// session is the right call — we do not need cache invalidation here.
const _cache = new Map(); // key: `${days}:${setupType}` -> grade card
const _inflight = new Map(); // key: `${days}:${setupType}` -> Promise
let _allRollingPromise = null;

async function fetchRollingCard(setupType, days = 30) {
  const cacheKey = `${days}:${setupType}`;
  if (_cache.has(cacheKey)) return _cache.get(cacheKey);
  if (_inflight.has(cacheKey)) return _inflight.get(cacheKey);

  // On the very first call we fetch the FULL roster in one shot —
  // every chip on a list view triggers this and we don't want N HTTP
  // calls. Subsequent setup types hit the cache.
  if (!_allRollingPromise) {
    const base = process.env.REACT_APP_BACKEND_URL || '';
    _allRollingPromise = fetch(`${base}/api/setup-grades?days=${days}`)
      .then(r => r.ok ? r.json() : { success: false, grades: [] })
      .catch(() => ({ success: false, grades: [] }));
  }
  const all = await _allRollingPromise;
  for (const card of (all.grades || [])) {
    _cache.set(`${days}:${card.setup_type}`, card);
  }
  // Mark un-seen setup_types as `null` so we don't re-fetch in a tight loop.
  if (!_cache.has(cacheKey)) _cache.set(cacheKey, null);
  return _cache.get(cacheKey);
}

const SetupGradeChip = ({
  setupType,
  days = 30,
  compact = false,
  size = 'sm',
  testIdSuffix = '',
}) => {
  const [card, setCard] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!setupType) {
      setLoaded(true);
      return;
    }
    fetchRollingCard(setupType, days).then((c) => {
      if (cancelled) return;
      setCard(c);
      setLoaded(true);
    });
    return () => { cancelled = true; };
  }, [setupType, days]);

  if (!loaded || !card) {
    // Don't render anything until we know the grade — avoids layout
    // jitter and prevents false-INSUFFICIENT_DATA flashes.
    return null;
  }

  const grade = card.grade || 'INSUFFICIENT_DATA';
  const tone = GRADE_TONE[grade] || GRADE_TONE.INSUFFICIENT_DATA;
  const wrPct = ((card.win_rate ?? 0) * 100).toFixed(0);
  const avgRStr = (card.avg_r ?? 0) >= 0 ? `+${card.avg_r.toFixed(2)}R` : `${card.avg_r.toFixed(2)}R`;
  const tradesStr = card.trades_count ?? 0;
  const pnlStr = (card.total_realized_pnl ?? 0) >= 0
    ? `+$${card.total_realized_pnl.toFixed(0)}`
    : `-$${Math.abs(card.total_realized_pnl).toFixed(0)}`;

  const tooltip = grade === 'INSUFFICIENT_DATA'
    ? `${setupType} · only ${tradesStr} trades in last ${days}d — need 5+ for grade`
    : `${setupType} · last ${days}d\n${tradesStr} trades · ${wrPct}% WR · avg ${avgRStr} · ${pnlStr}`;

  const sizeClass = size === 'xs' ? 'text-[10px] px-1 py-0' : 'text-[11px] px-1.5 py-0.5';
  const testId = `setup-grade-chip-${setupType}${testIdSuffix ? `-${testIdSuffix}` : ''}`;

  if (grade === 'INSUFFICIENT_DATA') {
    return (
      <span
        className={`inline-flex items-center border rounded-sm font-mono uppercase tracking-wide ${tone} ${sizeClass}`}
        title={tooltip}
        data-testid={testId}
      >
        n/a
      </span>
    );
  }

  if (compact) {
    return (
      <span
        className={`inline-flex items-center gap-1 border rounded-sm font-mono uppercase tracking-wide ${tone} ${sizeClass}`}
        title={tooltip}
        data-testid={testId}
      >
        <span className="font-bold">{grade}</span>
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 border rounded-sm font-mono uppercase tracking-wide ${tone} ${sizeClass}`}
      title={tooltip}
      data-testid={testId}
    >
      <span className="font-bold">{grade}</span>
      <span className="opacity-70 normal-case">{wrPct}% · {avgRStr}</span>
    </span>
  );
};

export default SetupGradeChip;
export { SetupGradeChip };
