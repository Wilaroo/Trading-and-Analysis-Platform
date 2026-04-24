/**
 * useTrainReadiness — polls GET /api/backfill/readiness and exposes a
 * single readiness object the UI can gate any "train" action against.
 *
 * Poll cadence: 60s. The endpoint is cheap (<3s) but the underlying
 * pymongo aggregations touch large collections so over-polling hurts
 * the collectors more than it helps the UI. 60s is a good middle
 * ground — the backfill drains in hours, not seconds.
 *
 * Returns:
 *   {
 *     loading:   true until first fetch completes,
 *     readiness: the most recent response (or null),
 *     error:     last error string (or null),
 *     ready:     bool — shortcut for readiness?.ready_to_train,
 *     verdict:   "green" | "yellow" | "red" | "unknown",
 *     blockers:  string[] — top-level reasons training is gated,
 *     refresh:   () => void — forces an immediate re-fetch,
 *   }
 *
 * Note: if `/api/backfill/readiness` is unreachable we treat that as
 * "unknown" (NOT green). Better to block an ambiguous train than to
 * silently allow one on a potentially-broken backend.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 60_000;

export function useTrainReadiness() {
  const [readiness, setReadiness] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const aliveRef = useRef(true);

  const fetchOnce = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/backfill/readiness`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (!aliveRef.current) return;
      setReadiness(json);
      setError(null);
    } catch (e) {
      if (!aliveRef.current) return;
      setError(String(e.message || e));
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    fetchOnce();
    const id = setInterval(fetchOnce, POLL_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
  }, [fetchOnce]);

  const ready = readiness?.ready_to_train === true;
  const verdict = readiness?.verdict || 'unknown';
  const blockers = readiness?.blockers || [];
  const warnings = readiness?.warnings || [];

  return {
    loading,
    readiness,
    error,
    ready,
    verdict,
    blockers,
    warnings,
    refresh: fetchOnce,
  };
}

export default useTrainReadiness;
