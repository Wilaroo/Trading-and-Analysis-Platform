/**
 * useRecentShadowDecisions — V5 stream-row companion hook.
 *
 * Fetches `/api/ai-modules/shadow/decisions?limit=200` every 60s and
 * returns a Map<symbol_upper, latestDecision> so individual stream rows
 * can render an inline shadow-tracker chip without each row paying a
 * separate API hop.
 *
 * Why this hook (and not a context):
 *   - Two `UnifiedStreamV5` instances exist in `SentComV5View` (one
 *     wide-layout, one narrow). React only mounts ONE at any time so
 *     a hook-scoped fetch is the right surface — no provider boilerplate.
 *   - Even if both mounted, ~2 GETs / 60s on this endpoint is trivial.
 *
 * Map value shape (one per symbol — most-recent decision wins):
 *   {
 *     recommendation: "proceed" | "pass" | "reduce_size",
 *     confidence_score: 0.0–1.0,
 *     was_executed: bool,
 *     trigger_time: ISO string,
 *     trigger_ms: number,        // parsed once for cheap age math
 *     module_count: int,         // how many AI modules contributed
 *   }
 *
 * 2026-04-30 v11 — operator-flagged enhancement: divergence signal
 * was visible only as an aggregate in `ShadowVsRealTile`; now also
 * actionable per-alert via inline badges in the unified stream.
 */
import { useEffect, useState, useRef } from 'react';
import api from '../../../utils/api';

const POLL_INTERVAL_MS = 60_000;
// Only badge a stream row when the shadow decision is within this
// window of the row's timestamp — older decisions are stale signals.
export const SHADOW_FRESHNESS_WINDOW_MS = 10 * 60 * 1000; // 10 min

const _normalize = (decisions) => {
  if (!Array.isArray(decisions)) return new Map();
  // Keep only the most-recent decision per symbol. Decisions arrive
  // newest-first by default but we don't depend on order — pick max
  // trigger_time per symbol explicitly for safety.
  const out = new Map();
  for (const d of decisions) {
    const sym = (d.symbol || '').toUpperCase();
    if (!sym) continue;
    const ts = Date.parse(d.trigger_time || d.created_at || '');
    if (Number.isNaN(ts)) continue;
    const existing = out.get(sym);
    if (existing && existing.trigger_ms >= ts) continue;
    out.set(sym, {
      recommendation: d.combined_recommendation || '',
      confidence_score: Number(d.confidence_score) || 0,
      was_executed: Boolean(d.was_executed),
      trigger_time: d.trigger_time,
      trigger_ms: ts,
      module_count: Array.isArray(d.modules_used) ? d.modules_used.length : 0,
    });
  }
  return out;
};

export const useRecentShadowDecisions = () => {
  const [bySymbol, setBySymbol] = useState(() => new Map());
  const cancelRef = useRef(false);

  useEffect(() => {
    cancelRef.current = false;
    let timer = null;

    const load = async () => {
      try {
        const res = await api.get('/api/ai-modules/shadow/decisions?limit=200');
        if (cancelRef.current) return;
        if (res?.data?.success) {
          setBySymbol(_normalize(res.data.decisions));
        }
      } catch {
        // Silent — shadow tracker may be uninitialised on a fresh
        // backend; the badge just won't render. Don't pollute logs.
      }
    };

    load();
    timer = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelRef.current = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  return bySymbol;
};

export default useRecentShadowDecisions;
