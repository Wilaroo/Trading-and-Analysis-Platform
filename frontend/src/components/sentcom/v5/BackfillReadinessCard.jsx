/**
 * BackfillReadinessCard — the "OK to train?" card shown at the top of
 * the FreshnessInspector modal.
 *
 * Calls `GET /api/backfill/readiness` once on mount and on manual
 * refresh (passed in via prop so the Inspector's refresh button can
 * re-trigger every section together). Displays:
 *
 *   - A giant verdict pill (READY / NOT READY) in green/yellow/red
 *   - The one-line summary string
 *   - A bulleted blockers list (only if red)
 *   - A bulleted warnings list (only if yellow)
 *   - A collapsed "what the checks found" table with per-check status
 *   - A "next steps" list the user should action before retraining
 *
 * Read-only — no train-trigger button here on purpose. We want the user
 * to consciously go kick off training; this card just tells them they
 * can.
 */

import React, { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const VERDICT_STYLE = {
  green: {
    pill: 'bg-emerald-900/40 text-emerald-200 border-emerald-700',
    dot: 'bg-emerald-400 animate-pulse',
    label: 'READY',
  },
  yellow: {
    pill: 'bg-amber-900/40 text-amber-200 border-amber-700',
    dot: 'bg-amber-400',
    label: 'NOT READY',
  },
  red: {
    pill: 'bg-rose-900/40 text-rose-200 border-rose-700',
    dot: 'bg-rose-400 animate-pulse',
    label: 'NOT READY',
  },
  unknown: {
    pill: 'bg-zinc-900/40 text-zinc-400 border-zinc-800',
    dot: 'bg-zinc-500',
    label: '—',
  },
};

const CHECK_LABELS = {
  queue_drained: 'Queue drained',
  critical_symbols_fresh: 'Critical symbols fresh',
  overall_freshness: 'Overall freshness',
  no_duplicates: 'No duplicate bars',
  density_adequate: 'Density adequate',
};

export const BackfillReadinessCard = ({ refreshToken = 0 }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/backfill/readiness`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshToken]);

  const verdict = data?.verdict || 'unknown';
  const style = VERDICT_STYLE[verdict] || VERDICT_STYLE.unknown;
  const checks = data?.checks || {};

  return (
    <section data-testid="backfill-readiness-card" data-help-id="backfill-readiness" className="space-y-2">
      <div className="v5-mono text-[10px] text-zinc-500 uppercase tracking-wide flex items-center gap-2">
        Backfill readiness · OK to train?
        {loading && (
          <span data-testid="readiness-loading" className="text-zinc-600">
            · loading…
          </span>
        )}
      </div>

      <div
        className={`flex items-start gap-3 p-3 rounded border ${style.pill}`}
        data-testid="readiness-verdict-pill"
        data-verdict={verdict}
      >
        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
          <span className="v5-mono font-bold text-sm uppercase tracking-wider">
            {style.label}
          </span>
        </div>
        <div className="flex-1 min-w-0 v5-mono text-[11px] leading-tight pt-0.5">
          {error && !data && (
            <span className="text-rose-400" data-testid="readiness-error">
              /api/backfill/readiness unreachable — {error}
            </span>
          )}
          {data && <span className="opacity-90">{data.summary}</span>}
        </div>
      </div>

      {/* Blockers — show prominently so a red verdict is impossible to miss */}
      {data?.blockers?.length > 0 && (
        <div data-testid="readiness-blockers" className="v5-mono text-[10px] pl-3">
          <div className="text-rose-400 uppercase tracking-wide font-bold mb-0.5">Blockers</div>
          <ul className="list-disc pl-4 space-y-0.5 text-rose-200">
            {data.blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {data?.warnings?.length > 0 && (
        <div data-testid="readiness-warnings" className="v5-mono text-[10px] pl-3">
          <div className="text-amber-400 uppercase tracking-wide font-bold mb-0.5">Warnings</div>
          <ul className="list-disc pl-4 space-y-0.5 text-amber-200">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Per-check matrix so the reader can drill into any one */}
      <div data-testid="readiness-checks-grid" className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1">
        {Object.entries(CHECK_LABELS).map(([key, label]) => {
          const c = checks[key];
          if (!c) return null;
          const cs = VERDICT_STYLE[c.status] || VERDICT_STYLE.unknown;
          return (
            <div
              key={key}
              data-testid={`readiness-check-${key}`}
              className={`px-2 py-1.5 rounded border ${cs.pill}`}
            >
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${cs.dot}`} />
                <span className="v5-mono text-[10px] font-bold">{label}</span>
                <span className="v5-mono text-[9px] uppercase opacity-70 ml-auto">
                  {c.status}
                </span>
              </div>
              <div className="v5-mono text-[9px] opacity-75 mt-0.5" title={c.detail}>
                {c.detail}
              </div>
            </div>
          );
        })}
      </div>

      {data?.next_steps?.length > 0 && (
        <div data-testid="readiness-next-steps" className="v5-mono text-[10px] pl-3 pt-1">
          <div className="text-zinc-400 uppercase tracking-wide font-bold mb-0.5">Next steps</div>
          <ul className="list-disc pl-4 space-y-0.5 text-zinc-300">
            {data.next_steps.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};

export default BackfillReadinessCard;
