/**
 * CanonicalUniverseCard — answers "what is training about to do?"
 *
 * Calls `GET /api/backfill/universe?tier=all` and surfaces:
 *   - total qualified symbols + unqualifiable count
 *   - the dollar-volume thresholds in effect (intraday/swing/investment)
 *   - per-bar-size training universe sizes (1m/5m/.../1w → ## symbols)
 *
 * This is the user-facing single source of truth: smart-backfill keeps
 * exactly these symbols fresh, and the AI training pipeline trains on
 * exactly these same sets.
 */

import React, { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const BAR_SIZES_ORDER = [
  '1 min', '5 mins', '15 mins', '30 mins', '1 hour', '1 day', '1 week',
];

const TIER_TONE = {
  intraday:   'text-emerald-300 border-emerald-800/60 bg-emerald-900/20',
  swing:      'text-cyan-300 border-cyan-800/60 bg-cyan-900/20',
  investment: 'text-violet-300 border-violet-800/60 bg-violet-900/20',
};

const fmtMoney = (n) => {
  if (!n && n !== 0) return '—';
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(0)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${n}`;
};

export const CanonicalUniverseCard = ({ refreshToken = 0 }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/backfill/universe?tier=all`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshToken]);

  const stats = data?.stats || {};
  const perBs = stats.training_universe_per_bar_size || {};
  const thresholds = stats.thresholds || {};

  return (
    <section
      data-testid="canonical-universe-card"
      className="border border-zinc-800 rounded-lg bg-zinc-950/60 p-3"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide">
          Canonical training universe
        </div>
        {loading && (
          <span className="text-[11px] text-zinc-500" data-testid="canonical-universe-loading">
            loading…
          </span>
        )}
      </div>

      {error && (
        <div
          className="text-[13px] text-rose-400"
          data-testid="canonical-universe-error"
        >
          Universe stats unavailable: {error}
        </div>
      )}

      {!error && data && (
        <>
          {/* Top-line counts */}
          <div className="grid grid-cols-3 gap-1.5 mb-2.5">
            <div
              data-testid="canonical-universe-qualified"
              className="border border-zinc-800 rounded bg-zinc-900/40 px-2 py-1.5"
            >
              <div className="text-[11px] text-zinc-500 uppercase">Qualified</div>
              <div className="text-sm text-zinc-100 v5-mono">
                {stats.qualified_total ?? '—'}
              </div>
            </div>
            <div
              data-testid="canonical-universe-intraday"
              className={`border rounded px-2 py-1.5 ${TIER_TONE.intraday}`}
            >
              <div className="text-[11px] uppercase opacity-70">
                Intraday ≥ {fmtMoney(thresholds.intraday)}
              </div>
              <div className="text-sm v5-mono">
                {stats.intraday ?? '—'}
              </div>
            </div>
            <div
              data-testid="canonical-universe-unqualifiable"
              className="border border-zinc-800 rounded bg-zinc-900/40 px-2 py-1.5"
            >
              <div className="text-[11px] text-zinc-500 uppercase">Unqualifiable</div>
              <div className="text-sm text-zinc-300 v5-mono">
                {stats.unqualifiable ?? 0}
              </div>
            </div>
          </div>

          {/* Per bar-size training universe — what training is about to do */}
          <div
            className="grid grid-cols-2 sm:grid-cols-4 gap-1.5"
            data-testid="canonical-universe-per-bar-size"
          >
            {BAR_SIZES_ORDER.map((bs) => {
              const row = perBs[bs];
              if (!row) return null;
              const tone = TIER_TONE[row.tier] || 'text-zinc-300 border-zinc-800 bg-zinc-900/40';
              return (
                <div
                  key={bs}
                  data-testid={`canonical-universe-bar-${bs.replace(/\s+/g, '-')}`}
                  className={`border rounded px-2 py-1 ${tone}`}
                  title={`${bs} trains on the ${row.tier} tier`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] v5-mono opacity-80">{bs}</span>
                    <span className="text-[11px] uppercase opacity-60">
                      {row.tier}
                    </span>
                  </div>
                  <div className="text-sm v5-mono">{row.symbols}</div>
                </div>
              );
            })}
          </div>

          <div className="mt-2 text-[11px] text-zinc-500 leading-snug">
            Smart-backfill keeps these symbols fresh; AI training trains on
            exactly the same sets. Single source of truth:
            <span className="text-zinc-400 v5-mono"> services/symbol_universe.py</span>.
          </div>
        </>
      )}
    </section>
  );
};

export default CanonicalUniverseCard;
